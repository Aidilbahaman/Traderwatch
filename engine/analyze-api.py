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
ALLOWED_PAIRS = {"XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD",
                 "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"}   # pairs dengan data bar live
MIN_GAP_S = 20                      # min seconds between analyses per user
HOURLY_CAP = 12                     # max analyses per user per hour
# Disiplin trading (owner 2026-11-21): selepas client tekan "add to trade",
# enforced cooldown sebelum scan seterusnya — AI ajar sabar, jangan overtrade.
TRADE_COOLDOWN_S = float(os.environ.get("ANALYZE_TRADE_COOLDOWN_S", "300"))
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


def rate_check(uid):
    """Return (ok, message). Trade-discipline cooldown + min gap + hourly cap."""
    now = time.time()
    # 1) Disiplin trading: cooldown 5 minit selepas client buka trade.
    age = last_trade_age_s(uid)
    if age is not None and 0 <= age < TRADE_COOLDOWN_S:
        remain = int(TRADE_COOLDOWN_S - age)
        mm, ss = divmod(remain, 60)
        wait = f"{mm}m {ss:02d}s" if mm else f"{ss}s"
        tip = _COOLDOWN_TIPS[int(now) % len(_COOLDOWN_TIPS)]
        return False, (f"☕ You just opened a trade — chill first. Wait {wait} "
                       f"before your next scan. {tip}")
    # 2) Min gap between scans (LLM cost control).
    last = _last_call.get(uid, 0)
    if now - last < MIN_GAP_S:
        return False, f"Sila tunggu {int(MIN_GAP_S - (now - last))}s sebelum analisis seterusnya."
    win = _hour_count.get(uid)
    if not win or now - win[0] >= 3600:
        win = [now, 0]
    if win[1] >= HOURLY_CAP:
        return False, "Had analisis sejam dicapai. Cuba lagi sejam kemudian."
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


TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def fetch_ohlc(pair, tf, limit=200):
    """Real OHLC candles for the chart, resampled to the requested timeframe."""
    tf = tf if tf in TF_MINUTES else "M15"
    base_gran = "M5" if tf == "M5" else "M15"
    base_min = 5 if tf == "M5" else 15
    rows = M5.candles(pair, base_gran, 2000)
    bars = []
    for c in rows:
        try:
            d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            bars.append((int(d.timestamp() * 1000), float(c["o"]), float(c["h"]),
                         float(c["l"]), float(c["c"])))
        except (KeyError, TypeError, ValueError):
            continue
    factor = max(1, TF_MINUTES[tf] // base_min)
    if factor > 1:
        res = []
        for i in range(0, len(bars) - factor + 1, factor):
            g = bars[i:i + factor]
            res.append((g[0][0], g[0][1], max(x[2] for x in g),
                        min(x[3] for x in g), g[-1][4]))
        bars = res
    return [{"t": t, "o": o, "h": h, "l": l, "c": c} for t, o, h, l, c in bars[-limit:]]


ANALYSIS_TFS = ("M5", "M15", "H1", "H4", "D1")
TF_MIN_BARS = {"M5": 80, "M15": 100, "H1": 60, "H4": 40, "D1": 20}


def fetch_bars_tf(pair, tf):
    """Base-TF bars (ts_ms,h,l,c) for the analyst. M5/M15/H1 from DB gran;
    H4/D1 resampled from M60. Returns list of (ts_ms, high, low, close)."""
    gran = {"M5": "M5", "M15": "M15", "H1": "M60", "H4": "M60", "D1": "M60"}.get(tf, "M15")
    count = {"M5": 300, "M15": 300, "H1": 300, "H4": 800, "D1": 1500}.get(tf, 300)
    rows = M5.candles(pair, gran, count)
    bars = []
    for c in rows:
        try:
            d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            bars.append((int(d.timestamp() * 1000), float(c["h"]), float(c["l"]), float(c["c"])))
        except (KeyError, TypeError, ValueError):
            continue
    factor = {"H4": 4, "D1": 24}.get(tf, 1)
    if factor > 1:
        res = []
        for i in range(0, len(bars) - factor + 1, factor):
            g = bars[i:i + factor]
            res.append((g[0][0], max(x[1] for x in g), min(x[2] for x in g), g[-1][3]))
        bars = res
    return bars


def run_analysis(pair, tf="M15"):
    tf = tf if tf in ANALYSIS_TFS else "M15"
    bars = fetch_bars_tf(pair, tf)
    if len(bars) < TF_MIN_BARS.get(tf, 100):
        return {"error": "Not enough bar data for this timeframe yet. Try another TF or pair."}
    disp = pair[:3] + "/" + pair[3:]
    pip = M.pip_of(disp)
    spread = SMC.SPREAD_PIPS.get(pair, SMC.DEFAULT_SPREAD_PIPS)
    verdict = LA.analyze(disp, bars, pip, spread, tf=tf)
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
        self.wfile.write(body)

    def _token(self):
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/analyze/health":
            return self._send(200, {"ok": True, "pairs": sorted(ALLOWED_PAIRS)})
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
        if pair not in ALLOWED_PAIRS:
            return self._send(400, {"error": "This pair is not open for analysis yet."})
        ok, msg = rate_check(uid)
        if not ok:
            return self._send(429, {"error": msg})
        rate_commit(uid)
        log(f"{uid[:8]} request {pair} {tf}")
        # MT5 broker is the single data source. If the bridge is down, fail closed
        # with a clear message (the site banner also shows bridge/market status).
        if not M5.is_up():
            return self._send(503, {"error": "MT5 data bridge is offline — analysis paused. Please try again shortly.", "bridge_down": True})
        # Forex/metals closed on weekends — only crypto (BTCUSD) trades 24/7.
        if M5.read_status().get("market") == "closed" and pair != "BTCUSD":
            return self._send(409, {"error": "Market closed for this pair — it reopens soon. BTCUSD is available 24/7.", "market_closed": True})
        try:
            result = run_analysis(pair, tf)
        except Exception as e:
            log(f"{pair} error {type(e).__name__}: {str(e)[:160]}")
            return self._send(500, {"error": "Analisis gagal buat masa ini. Cuba lagi sebentar."})
        log(f"{uid[:8]} {pair} -> {result.get('side')}")
        bump_analyses(uid)   # server-side per-account count (replaces browser-local)
        # MT5 sync moved to "Take this trade" (league-api) so the owner's
        # chosen lot is used. Scans no longer place orders. See mt5_ondemand.py.
        return self._send(200, result)


def _bars_refresh_loop():
    """Keep the 9 pair-card caches warm sequentially (MT5 bridge is serial).
    Runs in background so no member request ever pays the 1-2s candle read."""
    while True:
        for pair in ALLOWED_PAIRS:
            ck = (pair, "M15")
            try:
                now = time.time()
                with _BARS_CACHE_LOCK:
                    hit = _BARS_CACHE.get(ck)
                    if hit and now - hit[0] <= BARS_CACHE_TTL - 5:
                        continue
                candles = fetch_ohlc(pair, "M15")
                with _BARS_CACHE_LOCK:
                    _BARS_CACHE[ck] = (now, candles)
            except Exception as e:
                log(f"bars prewarm {pair} {type(e).__name__}: {str(e)[:80]}")
            time.sleep(0.2)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=_bars_refresh_loop, daemon=True, name="bars-prewarm").start()
    log(f"listening on 127.0.0.1:{PORT} (pairs={sorted(ALLOWED_PAIRS)})")
    srv.serve_forever()


if __name__ == "__main__":
    main()