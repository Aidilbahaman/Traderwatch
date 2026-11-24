#!/usr/bin/env python3
"""TraderWatch on-demand AI analysis API.

Owner request (2026-11-20): client clicks a pair (XAUUSD) to request an
analysis on demand; the LLM analyst activates and returns entry / SL / TP.
This is separate from the scheduled auto-signal engine — it runs only when
a member asks.

Endpoint (proxied by Caddy at /api/analyze):
  POST /api/analyze   {"pair":"XAUUSD"}  + Authorization: Bearer <supabase token>
  GET  /api/analyze/health

Safety:
  * Auth required (Supabase member token) — members only.
  * Only XAUUSD enabled for now (owner: "klik pair xauusd sahaja").
  * Rate limit per user (LLM cost control): min gap + hourly cap.
  * Reuses the SAME llm_analyst the scheduled engine uses (Qwen4 Max rootsys
    primary, free fallbacks), so quality/validation are identical.
  * Fail-closed: any error -> JSON error, never a fabricated signal.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import pathlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M            # noqa: E402
import smc_filter as SMC        # noqa: E402
import llm_analyst as LA        # noqa: E402
import sq_collector as SQC      # noqa: E402  (kept for compat; NOT used as feed)
import mt5_data as M5           # noqa: E402  MT5 broker = single market-data source

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PORT = int(os.environ.get("ANALYZE_PORT", "8102"))
REPO_LIVE_LAST = pathlib.Path(__file__).resolve().parent.parent / "state" / "ai-live-last.json"
ALLOWED_PAIRS = {"XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD",
                 "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"}   # pairs dengan data bar live
# Had longgar — client bayar untuk analisis tanpa had; jangan sekat kerja dia.
# Semua boleh dilaras guna env tanpa ubah kod.
MIN_GAP_S = float(os.environ.get("ANALYZE_MIN_GAP_S", "60"))
HOURLY_CAP = int(os.environ.get("ANALYZE_HOURLY_CAP", "40"))   # kos LLM: max 40 scan/jam
# Cooldown selepas buka trade: 0 = tiada sekatan (client bebas scan semula).
TRADE_COOLDOWN_S = float(os.environ.get("ANALYZE_TRADE_COOLDOWN_S", "0"))
BARS_COUNT = 300                    # M15 bars fed to the analyst
# Cloudflare Turnstile (login anti-bot). Test secret = always-pass for demo;
# set TURNSTILE_SECRET to your real secret in the service env for production.
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "1x0000000000000000000000000000000AA")
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# Audit M2 (2026-11-21): endpoint verify Turnstile tiada auth — had per-IP
# supaya tidak boleh disalah guna untuk spam siteverify Cloudflare.
TURNSTILE_RL_MAX = 10               # max verify requests per IP per window
TURNSTILE_RL_WINDOW_S = 60

_last_call = {}                     # uid -> ts of last accepted analysis
_hour_count = {}                    # uid -> [window_start_ts, count]
_turnstile_rl = {}                  # ip -> [window_start_ts, count]
_turnstile_rl_lock = threading.Lock()

# /api/bars cache: MT5 candle read + resample ~1-2s per call; the member app
# fires 9 pair cards in parallel on open -> 5-6s contention. Bars advance every
# 5min, so a 20s TTL is safe and cuts repeat calls to ~0ms.
_BARS_CACHE = {}                    # (pair,tf) -> (ts, candles)
_BARS_CACHE_LOCK = threading.Lock()
BARS_CACHE_TTL = 20

# Live AI activity: siapa sedang minta analisis apa. TTL 60s supaya senarai
# tidak tersangkut bila sesi terputus. Hanya inisial didedah (privasi).
_LIVE = {}                          # uid -> {pair, tf, who, started}
_LIVE_LOCK = threading.Lock()
LIVE_TTL = 60


def live_mark(uid, pair, tf, who):
    now = time.time()
    with _LIVE_LOCK:
        for k in [k for k, v in _LIVE.items() if now - v["started"] > LIVE_TTL]:
            _LIVE.pop(k, None)
        _LIVE[uid] = {"pair": pair, "tf": tf, "who": who, "started": now}


def live_list():
    now = time.time()
    with _LIVE_LOCK:
        rows = [dict(uid=k, **v) for k, v in _LIVE.items()
                if now - v["started"] <= LIVE_TTL]
    rows.sort(key=lambda r: r["started"])
    return rows



def load_env():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


SEC = load_env()
SB_URL = SEC["SUPABASE_URL"].rstrip("/")
SB_KEY = SEC["SUPABASE_SERVICE_KEY"]


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} ANALYZE {msg}", flush=True)


def bump_analyses(uid):
    """Atomic per-account analysis counter (Supabase RPC). Best-effort: a counter
    failure must never break the analysis response."""
    try:
        req = urllib.request.Request(SB_URL + "/rest/v1/rpc/bump_analyses",
                                     data=json.dumps({"p_uid": uid}).encode(),
                                     headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
                                              "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
    except Exception as e:
        log(f"bump_analyses {uid[:8]} skipped: {type(e).__name__}")


_auth_cache = {}                    # token -> (ts, user); 120s TTL
AUTH_CACHE_TTL = 120


def verify_user(token):
    if not token:
        return None
    now = time.time()
    with _BARS_CACHE_LOCK:
        hit = _auth_cache.get(token)
        if hit and now - hit[0] <= AUTH_CACHE_TTL:
            return hit[1]
    try:
        req = urllib.request.Request(SB_URL + "/auth/v1/user")
        req.add_header("apikey", SB_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as r:
            user = json.loads(r.read().decode())
        if user and user.get("id"):
            with _BARS_CACHE_LOCK:
                _auth_cache[token] = (now, user)
        return user
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None


# Mesej disiplin — AI ajar client sabar selepas buka trade (rotate).
_COOLDOWN_TIPS = [
    "Overtrading is the fastest way to blow an account. Let this trade breathe.",
    "One good trade beats ten rushed ones. Patience is an edge.",
    "The market will still be here in 5 minutes — your capital might not be.",
    "Winners wait. Let your setup play out before chasing the next one.",
]


def last_trade_age_s(uid):
    """Seconds since user's most recent paper trade opened (None if none/error)."""
    try:
        url = (SB_URL + "/rest/v1/paper_trades?select=opened_at&user_id=eq." + uid
               + "&order=opened_at.desc&limit=1")
        req = urllib.request.Request(url, headers={"apikey": SB_KEY,
                                                   "Authorization": "Bearer " + SB_KEY})
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read().decode())
        if not rows:
            return None
        opened = datetime.fromisoformat(str(rows[0]["opened_at"]).replace("Z", "+00:00"))
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - opened).total_seconds()
    except Exception:
        return None                      # fail-open: jangan lock user jika query gagal


def open_tf_lock(uid, pair, tf):
    """Owner 2026-11-23: lock the timeframe the client committed to with
    'take this trade'. Returns the open trade dict if that pair+TF already has
    a LIVE trade (status open), else None. The lock releases automatically when
    the trade closes at TP/SL (status != open) — no timer, no manual unlock."""
    if not tf:
        return None
    try:
        url = (SB_URL + "/rest/v1/paper_trades?select=id,pair,side,ai_tf,status,opened_at"
               "&user_id=eq." + uid + "&status=eq.open&pair=eq." + pair
               + "&ai_tf=eq." + tf)
        req = urllib.request.Request(url, headers={"apikey": SB_KEY,
                                                   "Authorization": "Bearer " + SB_KEY})
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read().decode())
        return rows[0] if rows else None
    except Exception:
        return None                      # fail-open: jangan sekat jika query gagal


def rate_check(uid, pair=None, tf=None):
    """Return (ok, message). TF-lock + min gap + hourly cap.

    TF-lock (owner 2026-11-23): sekali client tekan 'take this trade' pada satu
    timeframe, timeframe itu (pair sama) dikunci sampai trade tu tutup TP/SL.
    Lock dilepas automatik bila status != open — tiada timer.
    """
    now = time.time()
    # 1) TF-lock: pair+TF ada trade LIVE -> tak boleh scan semula TF itu.
    locked = open_tf_lock(uid, pair, tf) if (pair and tf) else None
    if locked:
        since = locked.get("opened_at") or ""
        return False, (f"🔒 {tf} dikunci untuk {pair} — anda sudah 'take this trade' "
                       f"pada TF ini. Analisis {tf} akan dibuka semula selepas trade "
                       f"itu hit TP atau SL. Anda masih boleh scan TF lain atau pair lain.")
    # 2) Min gap between scans (LLM cost control). Default 1 minit.
    last = _last_call.get(uid, 0)
    if now - last < MIN_GAP_S:
        return False, f"Please wait {max(1, int(MIN_GAP_S - (now - last)))}s before the next analysis."
    win = _hour_count.get(uid)
    if not win or now - win[0] >= 3600:
        win = [now, 0]
    if win[1] >= HOURLY_CAP:
        reset_in = int(3600 - (now - win[0]))
        mm, ss = divmod(max(0, reset_in), 60)
        return False, (f"Hourly analysis limit reached ({HOURLY_CAP}). "
                       f"Resets in {mm}m {ss:02d}s.")
    return True, ""


def rate_commit(uid):
    now = time.time()
    _last_call[uid] = now
    win = _hour_count.get(uid)
    if not win or now - win[0] >= 3600:
        win = [now, 0]
    win[1] += 1
    _hour_count[uid] = win


def turnstile_rate_ok(ip):
    """Per-IP fixed-window rate limit for the unauthenticated Turnstile verify
    endpoint (audit M2): max TURNSTILE_RL_MAX requests per TURNSTILE_RL_WINDOW_S.
    Counts every request (even bad JSON) and prunes expired windows in passing."""
    now = time.time()
    with _turnstile_rl_lock:
        for k in [k for k, w in _turnstile_rl.items()
                  if now - w[0] >= TURNSTILE_RL_WINDOW_S]:
            del _turnstile_rl[k]
        win = _turnstile_rl.get(ip)
        if not win or now - win[0] >= TURNSTILE_RL_WINDOW_S:
            win = [now, 0]
        if win[1] >= TURNSTILE_RL_MAX:
            return False
        win[1] += 1
        _turnstile_rl[ip] = win
        return True


def fetch_bars(pair):
    rows = M5.candles(pair, "M15", BARS_COUNT)
    out = []
    for c in rows:
        try:
            d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            out.append((int(d.timestamp() * 1000), float(c["h"]),
                        float(c["l"]), float(c["c"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}

# Chart-OHLC cache: every client opening the same chart used to spawn its own
# ~2s wine bridge call. Cache per (pair,tf) for 60s so N viewers cost 1 call.
_OHLC_CACHE = {}      # (pair,tf) -> (ts, bars)
_OHLC_TTL = 60.0


def fetch_ohlc(pair, tf, limit=200):
    """Real OHLC candles for the chart, resampled to the requested timeframe."""
    tf = tf if tf in TF_MINUTES else "M5"
    ck = (pair, tf)
    hit = _OHLC_CACHE.get(ck)
    if hit and (time.time() - hit[0]) < _OHLC_TTL:
        return hit[1][-limit:]
    bars = _fetch_ohlc_raw(pair, tf, limit)
    if bars:
        _OHLC_CACHE[ck] = (time.time(), bars)
        # housekeeping: drop stale entries
        for k, v in list(_OHLC_CACHE.items()):
            if (time.time() - v[0]) > _OHLC_TTL * 4:
                _OHLC_CACHE.pop(k, None)
    return bars


def _fetch_ohlc_raw(pair, tf, limit=200):
    """Real OHLC candles for the chart using native MT5 timeframes (M5..D1),
    with automatic fallback to M15 resampling if native H1/H4/D1 is empty."""
    tf = tf if tf in TF_MINUTES else "M5"
    gran = {"M1": "M1", "M5": "M5", "M15": "M15", "H1": "M60"}.get(tf, "M15")

    def _parse(rows):
        out = []
        for c in rows or []:
            try:
                d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                out.append((int(d.timestamp() * 1000), float(c["o"]), float(c["h"]),
                            float(c["l"]), float(c["c"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    bars = _parse(M5.candles(pair, gran, max(limit, 200)))
    if not bars and tf in ("H1", "H4", "D1"):
        base_rows = _parse(M5.candles(pair, "M15", 800))
        factor = max(1, TF_MINUTES[tf] // 15)
        res = []
        for i in range(0, len(base_rows) - factor + 1, factor):
            g = base_rows[i:i + factor]
            res.append((g[0][0], g[0][1], max(x[2] for x in g),
                        min(x[3] for x in g), g[-1][4]))
        bars = res
    return [{"t": t, "o": o, "h": h, "l": l, "c": c} for t, o, h, l, c in bars[-limit:]]


ANALYSIS_TFS = ("M1", "M5", "M15", "H1")
TF_MIN_BARS = {"M1": 60, "M5": 80, "M15": 100, "H1": 60}


def fetch_bars_tf(pair, tf):
    """Base-TF bars (ts_ms,h,l,c) for the analyst. Uses native MT5 candles for
    M5/M15/H1/H4/D1 (giving 300 true broker bars on H4 & D1 instead of resampled
    M60), with automatic fallback to M60 resampling if native returns too few."""
    tf = tf if tf in ANALYSIS_TFS else "M5"
    gran = {"M1": "M1", "M5": "M5", "M15": "M15", "H1": "M60"}.get(tf, "M5")
    # 520 bukan 300: quant_engine menolak setup bila bar < WARMUP_BARS
    # (M15/M5 = 400) sebab EMA200 di-seed dari bar pertama. Feed 300 bar
    # bermakna setiap analisis pulang HOLD "warmup" — app jadi bisu.
    count = {"M1": 620, "M5": 520, "M15": 520, "H1": 420}.get(tf, 520)

    def _parse(rows):
        out = []
        for c in rows or []:
            try:
                d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                out.append((int(d.timestamp() * 1000), float(c["h"]), float(c["l"]), float(c["c"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    bars = _parse(M5.candles(pair, gran, count))
    if len(bars) >= TF_MIN_BARS.get(tf, 60) or tf not in ("H4", "D1"):
        return bars
    # Fallback: resample from M60 if broker H4/D1 feed returned insufficient bars
    m60 = _parse(M5.candles(pair, "M60", 1600 if tf == "H4" else 2400))
    factor = 4 if tf == "H4" else 24
    res = []
    for i in range(0, len(m60) - factor + 1, factor):
        g = m60[i:i + factor]
        res.append((g[0][0], max(x[1] for x in g), min(x[2] for x in g), g[-1][3]))
    return res


def run_analysis(pair, tf="M15", tap=None, risk_level="med"):
    tf = tf if tf in ANALYSIS_TFS else "M5"
    bars = fetch_bars_tf(pair, tf)
    if len(bars) < TF_MIN_BARS.get(tf, 100):
        return {"error": "Not enough bar data for this timeframe yet. Try another TF or pair."}
    disp = pair[:3] + "/" + pair[3:]
    pip = M.pip_of(disp)
    spread = SMC.SPREAD_PIPS.get(pair, SMC.DEFAULT_SPREAD_PIPS)
    verdict = LA.analyze(disp, bars, pip, spread, tf=tf, src="member", tap=tap,
                         risk_level=risk_level)
    price = bars[-1][3]
    if verdict is None:
        return {"side": "HOLD", "pair": disp, "price": price, "tf": tf,
                "reason": "No clear setup right now. The engine is waiting for a better opportunity.",
                "generated_at": datetime.now(timezone.utc).isoformat()}
    verdict.update({"pair": disp, "price": price, "tf": tf,
                    "generated_at": datetime.now(timezone.utc).isoformat()})
    return verdict


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client tutup fetching (app reload / navigasi) — biasa, jangan log traceback

    def _token(self):
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/analyze/live":
            user = verify_user(self._token())
            if not user or not user.get("id"):
                return self._send(401, {"error": "Please sign in as a member."})
            rows = live_list()
            last = None
            try:
                p = pathlib.Path(REPO_LIVE_LAST)
                if p.exists():
                    last = json.loads(p.read_text())
            except Exception:
                last = None
            return self._send(200, {"live": rows, "last": last})
        if path == "/api/analyze/health":
            return self._send(200, {"ok": True, "pairs": sorted(ALLOWED_PAIRS)})
        if path == "/api/analyze/learn":
            user = verify_user(self._token())
            if not user or not user.get("id"):
                return self._send(401, {"error": "Please sign in as a member."})
            try:
                import ai_learn
                _lessons, _stats = ai_learn.lessons()
            except Exception:
                _lessons, _stats = "", None
            return self._send(200, {"lessons": _lessons or "", "stats": _stats})
        if path == "/api/bars":
            user = verify_user(self._token())
            if not user or not user.get("id"):
                return self._send(401, {"error": "Sila log masuk sebagai ahli."})
            q = urllib.parse.parse_qs(parsed.query)
            pair = str(q.get("pair", [""])[0]).upper().replace("/", "").replace(" ", "")
            tf = str(q.get("tf", ["M15"])[0]).upper()
            if pair not in ALLOWED_PAIRS:
                return self._send(400, {"error": "Pair ini belum dibuka untuk analisis AI."})
            try:
                now = time.time()
                ck = (pair, tf)
                with _BARS_CACHE_LOCK:
                    hit = _BARS_CACHE.get(ck)
                    if hit and now - hit[0] <= BARS_CACHE_TTL:
                        candles = hit[1]
                    else:
                        candles = None
                if candles is None:
                    candles = fetch_ohlc(pair, tf)
                    with _BARS_CACHE_LOCK:
                        _BARS_CACHE[ck] = (now, candles)
            except Exception as e:
                log(f"bars {pair} error {type(e).__name__}: {str(e)[:120]}")
                return self._send(500, {"error": "Gagal memuatkan data chart."})
            if not candles:
                return self._send(404, {"error": "Tiada data bar untuk pair ini."})
            return self._send(200, {"pair": pair, "tf": tf, "candles": candles})
        return self._send(404, {"error": "not found"})

    def _save_risk(self, level):
        """Simpan risk_level (low|med|high) ke user_metadata — kekal per-user."""
        user = verify_user(self._token())
        if not user or not user.get("id"):
            return self._send(401, {"error": "sign in required"})
        if level not in ("low", "med", "high"):
            return self._send(400, {"error": "level must be low|med|high"})
        try:
            req = urllib.request.Request(SB_URL + "/auth/v1/user",
                                         data=json.dumps({"data": {"risk_level": level}}).encode(),
                                         headers={"apikey": SB_KEY,
                                                  "Authorization": "Bearer " + self._token(),
                                                  "Content-Type": "application/json"},
                                         method="PUT")
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            # buang cache auth supaya metadata baru terbaca serta-merta
            with _BARS_CACHE_LOCK:
                _auth_cache.pop(self._token(), None)
        except Exception as e:
            log(f"save risk_level {level} failed: {type(e).__name__}")
            return self._send(502, {"error": "save failed"})
        return self._send(200, {"ok": True, "risk_level": level})

    def _alignment(self):
        user = verify_user(self._token())
        if not user or not user.get("id"):
            return self._send(401, {"error": "Sila log masuk sebagai ahli."})
        uid = user["id"]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return self._send(400, {"error": "JSON tidak sah."})
        pair = str(req.get("pair", "")).upper().replace("/", "").replace(" ", "")
        if pair not in ALLOWED_PAIRS:
            return self._send(400, {"error": "This pair is not open for analysis yet."})
        if not M5.is_up():
            return self._send(503, {"error": "MT5 data bridge offline.", "bridge_down": True})
        # Alignment datang sebaik sahaja scan utama siap — jangan kongsi
        # cooldown 20s /api/analyze (nanti 429). Guna throttle 30s berasingan.
        now = time.time()
        ak = "align:" + uid
        with _BARS_CACHE_LOCK:
            last = (_BARS_CACHE.get(ak) or (0, 0))[0]
            if now - last < 30:
                cached_res = _BARS_CACHE.get("alignres:" + pair + ":" + uid)
                if cached_res and now - cached_res[0] < 300:
                    return self._send(200, cached_res[1])
            _BARS_CACHE[ak] = (now, 1)
        tf_bars = {}
        for tf in LA.ALIGN_TFS:
            try:
                tf_bars[tf] = fetch_bars_tf(pair, tf)
            except Exception:
                tf_bars[tf] = []
        res = LA.alignment(pair, tf_bars)
        if res is None:
            return self._send(502, {"error": "Alignment unavailable — try again."})
        res["pair"] = pair
        with _BARS_CACHE_LOCK:
            _BARS_CACHE["alignres:" + pair + ":" + uid] = (now, res)
        return self._send(200, res)

    def _turnstile(self):
        if not turnstile_rate_ok(self.client_address[0]):
            return self._send(429, {"ok": False, "error": "rate limited"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return self._send(400, {"ok": False, "error": "bad json"})
        token = str(req.get("token", ""))
        if not token:
            return self._send(400, {"ok": False, "error": "missing token"})
        try:
            data = urllib.parse.urlencode({"secret": TURNSTILE_SECRET, "response": token}).encode()
            r = urllib.request.Request(TURNSTILE_VERIFY_URL, data=data,
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(r, timeout=15) as resp:
                out = json.loads(resp.read().decode())
            ok = bool(out.get("success"))
            log(f"turnstile verify ok={ok}")
            return self._send(200, {"ok": ok})
        except Exception as e:
            log(f"turnstile error {type(e).__name__}: {str(e)[:120]}")
            # Fail open on network error so legit users are not locked out.
            return self._send(200, {"ok": True, "fallback": True})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/turnstile/verify":
            return self._turnstile()
        if path == "/api/analyze/alignment":
            return self._alignment()
        if path == "/api/analyze/risk":
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, {"error": "JSON tidak sah."})
            return self._save_risk(str(body.get("level", "med")).lower())
        if path != "/api/analyze":
            return self._send(404, {"error": "not found"})
        user = verify_user(self._token())
        if not user or not user.get("id"):
            return self._send(401, {"error": "Sila log masuk sebagai ahli untuk analisis."})
        uid = user["id"]
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "JSON tidak sah."})
        pair = str(req.get("pair", "")).upper().replace("/", "").replace(" ", "")
        tf = str(req.get("timeframe", "M15")).upper()
        risk_level = str(req.get("risk_level", "med")).lower()
        if risk_level not in ("low", "med", "high"):
            risk_level = "med"
        # Satu ketukan UI = satu permintaan pada lencana, walau scan 5 TF.
        # Frontend hantar id yang sama untuk semua TF dalam ketukan itu.
        tap = str(req.get("tap") or "").strip()[:40] or None
        if pair not in ALLOWED_PAIRS:
            return self._send(400, {"error": "This pair is not open for analysis yet."})
        ok, msg = rate_check(uid, pair, tf)
        if not ok:
            return self._send(429, {"error": msg, "tf_locked": "dikunci" in msg})
        rate_commit(uid)
        meta = (user.get("user_metadata") or {})
        nm = str(meta.get("username") or meta.get("full_name") or meta.get("name")
                 or (user.get("email") or "member").split("@")[0])
        parts = [p for p in nm.replace("_", " ").replace(".", " ").split() if p]
        who = " ".join([parts[0][:1].upper() + "."] + [p[:1].upper() + "." for p in parts[1:2]]) if parts else "A."
        live_mark(uid, pair, tf, who)
        log(f"{uid[:8]} request {pair} {tf}")
        # MT5 broker is the single data source. If the bridge is down, fail closed
        # with a clear message (the site banner also shows bridge/market status).
        if not M5.is_up():
            return self._send(503, {"error": "MT5 data bridge is offline — analysis paused. Please try again shortly.", "bridge_down": True})
        # Forex/metals closed on weekends — only crypto (BTCUSD) trades 24/7.
        if M5.read_status().get("market") == "closed" and pair != "BTCUSD":
            return self._send(409, {"error": "Market closed for this pair — it reopens soon. BTCUSD is available 24/7.", "market_closed": True})
        try:
            result = run_analysis(pair, tf, tap=tap, risk_level=risk_level)
        except Exception as e:
            log(f"{pair} error {type(e).__name__}: {str(e)[:160]}")
            return self._send(500, {"error": "Analisis gagal buat masa ini. Cuba lagi sebentar."})
        log(f"{uid[:8]} {pair} -> {result.get('side')}")
        # Simpan verdict terakhir untuk orb hub (siapa nampak aktiviti AI).
        try:
            REPO_LIVE_LAST.parent.mkdir(parents=True, exist_ok=True)
            REPO_LIVE_LAST.write_text(json.dumps({
                "pair": result.get("pair") or pair, "tf": result.get("tf") or tf,
                "side": result.get("side"), "conf": result.get("conf"),
                "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
        except Exception as e:
            log(f"live-last write fail {type(e).__name__}")
        bump_analyses(uid)   # server-side per-account count (replaces browser-local)
        # MT5 sync moved to "Take this trade" (league-api) so the owner's
        # chosen lot is used. Scans no longer place orders. See mt5_ondemand.py.
        return self._send(200, result)


def _bars_refresh_loop():
    """Keep the 9 pair-card caches warm sequentially (MT5 bridge is serial).
    Runs in background so no member request ever pays the 1-2s candle read.

    The per-pair sleep sits outside the cache check on purpose. The previous
    version used `continue` to skip fresh pairs, which also skipped the sleep:
    whenever all 9 pairs were still cached the loop re-entered `while True`
    with no wait at all and spun a Python core at ~65% for the 15s between
    expiry windows (measured 2026-11-24, load 6.6 on 2 vCPU)."""
    while True:
        for pair in ALLOWED_PAIRS:
            ck = (pair, "M15")
            try:
                now = time.time()
                with _BARS_CACHE_LOCK:
                    hit = _BARS_CACHE.get(ck)
                    fresh = bool(hit and now - hit[0] <= BARS_CACHE_TTL - 5)
                if not fresh:
                    candles = fetch_ohlc(pair, "M15")
                    with _BARS_CACHE_LOCK:
                        _BARS_CACHE[ck] = (now, candles)
            except Exception as e:
                log(f"bars prewarm {pair} {type(e).__name__}: {str(e)[:80]}")
            # Sleep on EVERY pass, fresh or not. The old `continue` skipped this
            # whenever all 9 pairs were still cached, so the loop re-entered
            # `while True` with no wait: ~65% of a core burned on an empty pass
            # (measured 2026-11-24, load 6.6 on 2 vCPU). Cadence now identical
            # to the intended 0.2s-per-pair pace.
            time.sleep(0.2)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=_bars_refresh_loop, daemon=True, name="bars-prewarm").start()
    log(f"listening on 127.0.0.1:{PORT} (pairs={sorted(ALLOWED_PAIRS)})")
    srv.serve_forever()


if __name__ == "__main__":
    main()