#!/usr/bin/env python3
"""TraderWatch Paper Trading League API.

Member-triggered paper trading + leaderboard. Virtual $10,000 balance;
outcomes are resolved by engine/paper-league-resolver.py from real prices,
so results cannot be self-reported.

Endpoints (Caddy proxies /api/league* here):
  GET  /api/league/me          -> balance, net_r, win_rate, open count, rank
  GET  /api/league/trades      -> my trades (newest first)
  GET  /api/league/leaderboard -> aggregated standings (RPC, no private data)
  GET  /api/league/quote?pair=XAUUSD -> {pair, price, ts} live tick for the
                                   member trade-detail modal (5s poll)
  POST /api/league/trade       -> open a paper trade {pair,side,entry,sl,tp,risk_pct|lot}
                                  optional mt5:true (OWNER ONLY) also places a real
                                  MT5 pending order with the exact lot chosen.

Auth: Supabase member Bearer token on every call.
"""
import json
import os
import pathlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
import sys
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))   # systemd runs from repo root; engine/ must be importable

try:
    import llm_analyst as LA
except Exception:
    LA = None

# Owner-only real-money sync ("Take this trade" -> MT5). Optional: if the MT5
# module cannot load, the league keeps working paper-only.
try:
    import mt5_ondemand as MO
except Exception:
    MO = None

# Per-member MT5 account routing (client account shown in the member app).
try:
    import mt5_accounts as MA
except Exception:
    MA = None

# Live entry price from the MT5 broker tick (single data source, no Swissquote
# fallback). Paper trades fill at the CURRENT broker price (instant entry).
try:
    import mt5_data as M5B
except Exception:
    M5B = None


def live_price(pair):
    """(bid+ask)/2 from the MT5 broker, or None when the bridge is down."""
    if M5B is None:
        return None
    return M5B.mid(pair)


def live_quote(pair):
    """(price, ts_iso) from the MT5 broker tick; (None, None) when bridge down.
    ts is the tick time normalized to UTC (same server-offset logic as
    mt5_data.candles), falling back to now when the tick carries no time."""
    if M5B is None:
        return None, None
    tk = M5B.tick(pair)
    if not tk or not tk.get("bid") or not tk.get("ask"):
        return None, None
    price = round((float(tk["bid"]) + float(tk["ask"])) / 2.0, 5)
    try:
        ts = (datetime.fromtimestamp(int(tk["time"]), timezone.utc)
              - timedelta(hours=M5B._offset_hours())).isoformat()
    except (KeyError, TypeError, ValueError):
        ts = datetime.now(timezone.utc).isoformat()
    return price, ts

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PORT = int(os.environ.get("LEAGUE_PORT", "8103"))
SEASON = int(os.environ.get("LEAGUE_SEASON", "1"))
START_BALANCE = 10000.0
ALLOWED_PAIRS = {"XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD",
                 "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"}
MAX_OPEN_PER_PAIR = 5
MAX_OPEN_TOTAL = 5
RISK_CHOICES = (1.0, 2.0)
# Contract multiplier (USD per 1.0 price move per 1 lot) — matches frontend lotFor.
CONTRACT_MULT = {"XAUUSD": 100.0, "XAGUSD": 5000.0, "BTCUSD": 1.0}
DEFAULT_MULT = 100000.0  # standard forex lot
MAX_LOT = 100.0
MIN_LOT = 0.01

# Cache: leaderboard (RPC) berubah bila trade ditutup ~1/min — 30s TTL selamat
# dan potong round-trip Supabase untuk /me + /leaderboard. Auth verify di-cache
# 120s supaya 3 endpoint serentak tak buat 3x /auth/v1/user.
_cache = {}
_cache_lock = threading.Lock()
LEADERBOARD_TTL = 30
AUTH_TTL = 120


MYT = timezone(timedelta(hours=8))   # Malaysia (UTC+8) — reset harian ikut waktu tempatan


def my_day_start_iso():
    """Awal hari ini (00:00 waktu Malaysia) dalam ISO-8601 UTC untuk query Supabase."""
    now = datetime.now(MYT)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat()


def cached(key, ttl, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] <= ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def cached_leaderboard():
    return cached("leaderboard", LEADERBOARD_TTL,
                  lambda: sb("POST", "/rest/v1/rpc/get_leaderboard",
                             body={"p_season": SEASON}) or [])


def invalidate_league(uid=None):
    """Panggil selepas write (buka trade). Cache resolver (proses lain)
    expire sendiri melalui TTL pendek. """
    with _cache_lock:
        _cache.pop("leaderboard", None)
        if uid:
            _cache.pop("trades:" + uid, None)


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
    print(f"{datetime.now(timezone.utc).isoformat()} LEAGUE-API {msg}", flush=True)


def sb(method, path, body=None, params=None, token=None):
    url = SB_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SB_KEY)
    req.add_header("Authorization", "Bearer " + (token or SB_KEY))
    req.add_header("Content-Type", "application/json")
    if method == "POST":
        req.add_header("Prefer", "return=representation")
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip() else None


def verify_user(token):
    if not token:
        return None
    ck = "auth:" + token
    now = time.time()
    with _cache_lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] <= AUTH_TTL:
            return hit[1]
    try:
        req = urllib.request.Request(SB_URL + "/auth/v1/user")
        req.add_header("apikey", SB_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as r:
            user = json.loads(r.read().decode())
        if user and user.get("id"):
            with _cache_lock:
                _cache[ck] = (now, user)
        return user
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None


def display_name(user):
    meta = user.get("user_metadata") or {}
    return (meta.get("name") or (user.get("email") or "trader").split("@")[0])[:40]


def my_trades(uid, limit=100):
    return cached("trades:" + uid, 10, lambda: sb("GET", "/rest/v1/paper_trades", params={
        "select": "*", "user_id": f"eq.{uid}", "season": f"eq.{SEASON}",
        "order": "opened_at.desc", "limit": str(limit)}) or [])


def balance_of(trades):
    closed = [t for t in trades if t["status"] in ("tp", "sl", "be") and t.get("r_result") is not None]
    profit = sum(float(t["r_result"]) * float(t["risk_usd"]) for t in closed)
    return round(START_BALANCE + profit, 2), closed


RECAP_COACH_FALLBACK = "Kekalkan disiplin — risiko kecil, konsisten menang."


def coach_line(uid, stats):
    """One-sentence Malay coaching line via glm-5.2; cached per uid+week (1h)."""
    week = datetime.now(timezone.utc).strftime("%G-W%V")
    ck = "coach:" + uid + ":" + week
    now = time.time()
    with _cache_lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] <= 3600:
            return hit[1]
    line = RECAP_COACH_FALLBACK
    if LA is not None:
        try:
            prompt = (
                "Anda coach trading disiplin Melayu. Data paper trading 7 hari "
                "ahli: " + json.dumps(stats, ensure_ascii=False) + ". "
                "Balas SATU ayat coaching max 18 patah perkataan. Nada: jujur, "
                "tenang, membina, hormat (seperti jurulatih profesional). "
                "DULUARAN: jangan guna perkataan 'buang duit', 'kau', 'dongok', "
                "atau apa-apa yang menghina. Fokus pada SATU tindakan praktikal "
                "untuk minggu depan. Contoh: '42% win dengan R negatif — kurangkan "
                "frekuensi, tunggu setup jelas; kualiti lebih penting dari kuantiti.' "
                "JSON sahaja: {\"coach\":\"...\"}")
            raw = LA._call_model("glm-5.2", prompt, 30)
            m = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            c = str(m.get("coach") or "").strip()
            if c:
                line = c[:200]
        except Exception as e:
            log(f"coach LLM fail {type(e).__name__}: {str(e)[:120]}")
    with _cache_lock:
        _cache[ck] = (now, line)
    return line


def weekly_recap(uid):
    """7-day recap: net R, win rate, streak, best pair, equity spark, coach."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = sb("GET", "/rest/v1/paper_trades", params={
        "select": "*", "user_id": f"eq.{uid}", "season": f"eq.{SEASON}",
        "opened_at": f"gte.{since}", "order": "opened_at.asc", "limit": "500"}) or []
    closed = [t for t in rows if t["status"] in ("tp", "sl", "be")
              and t.get("r_result") is not None]
    if not rows:
        return {"empty": True}
    closed.sort(key=lambda t: t.get("closed_at") or t["opened_at"])
    net_r = round(sum(float(t["r_result"]) for t in closed), 2)
    wins = sum(1 for t in closed if t["status"] == "tp")
    dec = sum(1 for t in closed if t["status"] in ("tp", "sl"))
    # Best streak: consecutive tp by closed_at order.
    streak = best = 0
    for t in closed:
        streak = streak + 1 if t["status"] == "tp" else 0
        best = max(best, streak)
    # Best pair by R contribution.
    by_pair = {}
    for t in closed:
        p = by_pair.setdefault(t["pair"], {"pair": t["pair"], "wins": 0,
                                           "total": 0, "r": 0.0})
        p["total"] += 1
        if t["status"] == "tp":
            p["wins"] += 1
        p["r"] = round(p["r"] + float(t["r_result"]), 2)
    best_pair = max(by_pair.values(), key=lambda p: p["r"]) if by_pair else None
    # Equity spark: cumulative R after each closed trade in order.
    spark, cum = [], 0.0
    for t in closed:
        cum += float(t["r_result"])
        spark.append(round(cum, 2))
    week_label = (datetime.now(timezone.utc) - timedelta(days=6)
                  ).strftime("%-d") + "\u2013" + datetime.now(timezone.utc).strftime("%-d %b")
    stats = {"net_r": net_r, "win_rate": round(100.0 * wins / dec, 1) if dec else 0,
             "trades": len(closed), "best_streak": best,
             "best_pair": best_pair["pair"] if best_pair else None}
    return {
        "week_label": week_label, "net_r": net_r,
        "win_rate": round(100.0 * wins / dec, 1) if dec else None,
        "trades": len(closed), "best_streak": best,
        "best_pair": best_pair, "equity_spark": spark,
        "coach": coach_line(uid, stats)}


ANALYSIS_LOG = pathlib.Path(__file__).resolve().parent.parent / "state" / "llm-analysis-log.jsonl"
_AI_AGG = {"at": 0.0, "out": {}}
_AI_AGG_TTL = 20


def pair_ai_requests(window_s=3600):
    """Kira berapa kali AHLI (manusia) minta analisis untuk setiap pair dalam
    1 jam terakhir — satu ketukan UI dikira SATU.

    Sumber: state/llm-analysis-log.jsonl (setiap analisis ditulis oleh llm_analyst).
    Hanya rekod src="member" dikira; panggilan bot auto-scan (src="bot") dan
    backtest tidak masuk lencana, supaya angka pada pair card bermaksud
    "manusia yang minta", bukan kitaran enjin.
    Setiap rekod member membawa medan tap (id ketukan). Scan 5 TF dalam satu
    ketukan berkongsi tap yang sama, jadi ia dikira sekali sahaja.
    Rekod lama tanpa tap: dikira ikut (pair, saat-dibulatkan-ke-minit) supaya
    satu ketukan berbilang-TF tidak berganda; rekod tanpa src dikira bot.
    Cache 60s supaya tak baca fail besar pada setiap request.
    """
    now = time.time()
    if now - _AI_AGG["at"] < _AI_AGG_TTL and _AI_AGG["out"]:
        return _AI_AGG["out"]
    seen = set()
    out = {}
    try:
        if ANALYSIS_LOG.exists():
            cutoff = now - window_s
            size = ANALYSIS_LOG.stat().st_size
            # Baca hanya ekor fail (max 2MB) untuk elak muat seluruh log.
            with ANALYSIS_LOG.open("rb") as f:
                if size > 2_000_000:
                    f.seek(size - 2_000_000)
                    f.readline()      # buang baris separuh
                for raw in f:
                    try:
                        r = json.loads(raw)
                    except Exception:
                        continue
                    # Hanya MEMBER (manusia tekan). Bot auto-scan dikecualikan
                    # supaya angka pada pair card = "berapa orang minta",
                    # bukan kitaran enjin. Rekod lama tanpa src TIDAK dikira
                    # (ia tidak boleh dibezakan bot vs member).
                    if r.get("src") != "member":
                        continue
                    ts = r.get("ts") or ""
                    pair = str(r.get("pair") or "").upper().replace("/", "")
                    if not pair or not ts:
                        continue
                    try:
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        continue
                    if t < cutoff:
                        continue
                    tap = str(r.get("tap") or "").strip()
                    # Kunci ketukan: tap eksplisit, atau pair+minit bila tiada.
                    key = (pair, "tap:" + tap) if tap else (pair, "min:%d" % int(t // 60))
                    if key in seen:
                        continue
                    seen.add(key)
                    out[pair] = out.get(pair, 0) + 1
    except Exception:
        out = {}
    _AI_AGG.update(at=now, out=out)
    return out


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

    def _user(self):
        u = verify_user(self._token())
        return u if u and u.get("id") else None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/league/health":
            return self._send(200, {"ok": True, "season": SEASON})
        user = self._user()
        if not user:
            return self._send(401, {"error": "Please sign in as a member."})
        uid = user["id"]
        try:
            if path == "/api/league/pair-traders":
                day_start = my_day_start_iso()
                counts = cached("pair-traders-day", 60, lambda: sb(
                    "GET", "/rest/v1/paper_trades",
                    params={"select": "pair,user_id",
                            "opened_at": f"gte.{day_start}",
                            "limit": "2000"}) or [])
                agg = {}
                for r in counts:
                    p = str(r.get("pair") or "").upper().replace("/", "")
                    if not p:
                        continue
                    agg.setdefault(p, set()).add(r.get("user_id"))
                out = {p: len(s) for p, s in agg.items()}
                return self._send(200, {"traders": out, "scope": "today",
                                        "since": day_start, "season": SEASON})
            if path == "/api/league/pair-ai-requests":
                return self._send(200, {"requests": pair_ai_requests(), "window": "1h"})
            if path == "/api/league/trades":
                return self._send(200, {"trades": my_trades(uid), "season": SEASON})
            if path == "/api/league/recap":
                return self._send(200, weekly_recap(uid))
            if path == "/api/league/leaderboard":
                rows = cached_leaderboard()
                for i, r in enumerate(rows):
                    r["rank"] = i + 1
                    r["is_me"] = (r.get("user_id") == uid)
                return self._send(200, {"leaderboard": rows, "season": SEASON,
                                        "start_balance": START_BALANCE})
            if path == "/api/league/me":
                trades = my_trades(uid)
                bal, closed = balance_of(trades)
                wins = sum(1 for t in closed if t["status"] == "tp")
                dec = sum(1 for t in closed if t["status"] in ("tp", "sl"))
                net_r = round(sum(float(t["r_result"]) for t in closed), 2)
                open_n = sum(1 for t in trades if t["status"] == "open")
                board = cached_leaderboard()
                me = display_name(user)
                rank = next((i + 1 for i, r in enumerate(board) if r.get("user_id") == uid), None)
                # Server-side per-account analysis count (user_analyses table).
                ana = cached("ana:" + uid, 60, lambda: sb("GET", "/rest/v1/user_analyses", params={
                    "select": "count", "user_id": f"eq.{uid}"}) or [])
                ana_count = int(ana[0]["count"]) if ana else 0
                # Per-member MT5 account snapshot for MAPPED clients only.
                # The owner keeps the legacy experience (is_owner flag) with no
                # extra terminal call on /me — zero regression to the owner path.
                mt5_info = None
                acct = MA.account_for(uid) if MA else None
                if acct and MO:
                    mt5_info = MO.snapshot(acct)
                return self._send(200, {
                    "balance": bal, "start_balance": START_BALANCE, "net_r": net_r,
                    "win_rate": round(100.0 * wins / dec, 1) if dec else None,
                    "trades_closed": len(closed), "trades_open": open_n,
                    "analyses_count": ana_count,
                    "rank": rank, "season": SEASON, "username": me,
                    "is_owner": bool(MO and MO.is_owner(uid)),
                    "mt5_account": mt5_info})
            if path == "/api/league/quote":
                qs = urllib.parse.parse_qs(parsed.query)
                pair = qs.get("pair", [""])[0].upper().replace("/", "").replace(" ", "")
                if pair not in ALLOWED_PAIRS:
                    return self._send(400, {"error": "This pair is not open for the league yet."})
                price, ts = live_quote(pair)
                if price is None:
                    return self._send(503, {"error": "Live price unavailable — try again in a moment."})
                return self._send(200, {"pair": pair, "price": price, "ts": ts})
        except urllib.error.HTTPError as e:
            log(f"GET {path} sb HTTP {e.code}")
            return self._send(502, {"error": "Could not load league data. Try again."})
        except Exception as e:
            log(f"GET {path} error {type(e).__name__}: {str(e)[:140]}")
            return self._send(500, {"error": "Something went wrong. Try again."})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/league/trade":
            return self._send(404, {"error": "not found"})
        user = self._user()
        if not user:
            return self._send(401, {"error": "Please sign in as a member."})
        uid = user["id"]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return self._send(400, {"error": "Invalid request."})
        pair = str(req.get("pair", "")).upper().replace("/", "").replace(" ", "")
        side = str(req.get("side", "")).upper()
        if pair not in ALLOWED_PAIRS:
            return self._send(400, {"error": "This pair is not open for the league yet."})
        if side not in ("BUY", "SELL"):
            return self._send(400, {"error": "Side must be BUY or SELL."})
        try:
            entry, sl, tp = float(req["entry"]), float(req["sl"]), float(req["tp"])
        except (KeyError, TypeError, ValueError):
            return self._send(400, {"error": "Missing entry / SL / TP."})
        # Instant entry: fill at the LIVE market price. The verdict entry can
        # drift while the LLM runs — using it created unfilled "pending" trades
        # that the resolver wrongly closed at SL/TP.
        live = live_price(pair)
        if live is None:
            return self._send(503, {"error": "Live price unavailable — try again in a moment."})
        entry = live
        if side == "BUY" and not (sl < entry < tp):
            return self._send(409, {"error": "Price moved beyond this setup's SL/TP — run a fresh scan."})
        if side == "SELL" and not (sl > entry > tp):
            return self._send(409, {"error": "Price moved beyond this setup's SL/TP — run a fresh scan."})
        # Custom lot (optional): client sets their own lot size. Otherwise risk %.
        custom_lot = None
        if req.get("lot") not in (None, "", 0):
            try:
                custom_lot = float(req["lot"])
            except (TypeError, ValueError):
                return self._send(400, {"error": "Invalid lot size."})
            if not (MIN_LOT <= custom_lot <= MAX_LOT):
                return self._send(400, {"error": f"Lot must be between {MIN_LOT} and {MAX_LOT}."})
            custom_lot = round(custom_lot, 2)
        else:
            try:
                risk_pct = float(req.get("risk_pct", 1))
            except (TypeError, ValueError):
                return self._send(400, {"error": "Invalid risk."})
            if risk_pct not in RISK_CHOICES:
                return self._send(400, {"error": "Risk must be 1% or 2%."})
        try:
            trades = my_trades(uid)
            open_tr = [t for t in trades if t["status"] == "open"]
            if sum(1 for t in open_tr if t["pair"] == pair) >= MAX_OPEN_PER_PAIR:
                return self._send(409, {"error": f"You already have an open {pair} trade."})
            if len(open_tr) >= MAX_OPEN_TOTAL:
                return self._send(409, {"error": "Max 5 open trades. Close one first."})
            bal, _ = balance_of(trades)
            if bal <= 0:
                return self._send(409, {"error": "Virtual balance depleted. New season resets it."})
            if custom_lot is not None:
                mult = CONTRACT_MULT.get(pair, DEFAULT_MULT)
                risk_usd = round(custom_lot * abs(entry - sl) * mult, 2)
                if risk_usd > bal:
                    return self._send(409, {"error": "That lot risks more than your virtual balance. Use a smaller lot."})
                risk_pct = round(risk_usd / bal * 100.0, 2)
            else:
                risk_usd = round(bal * risk_pct / 100.0, 2)
            body = {
                "user_id": uid, "username": display_name(user), "pair": pair,
                "side": side, "entry": entry, "sl": sl, "tp": tp,
                "risk_pct": risk_pct, "risk_usd": risk_usd, "season": SEASON}
            if custom_lot is not None:
                body["lot"] = custom_lot
            # AI learning: ciri setup masa ambil trade (untuk analisis TP/SL nanti).
            for k, cast in (("ai_tf", str), ("ai_bos", str), ("ai_choch", bool),
                            ("ai_fvg", int), ("ai_rr", float), ("ai_atr", float),
                            ("ai_hour", int), ("ai_conf", float)):
                if k in req and req[k] not in (None, ""):
                    try:
                        body[k] = cast(req[k])
                    except (TypeError, ValueError):
                        pass
            row = sb("POST", "/rest/v1/paper_trades", body=body)
            invalidate_league(uid)   # cache segar selepas trade baru
            tr = (row or [{}])[0]
            log(f"{uid[:8]} opened {pair} {side} " + (f"lot={custom_lot}" if custom_lot is not None else f"risk {risk_pct}%"))
            # Owner-only: also place a REAL MT5 market order. Mapped client
            # accounts can opt in too, but only when trade-enabled (deposit +
            # trade password). Everyone else -> paper only.
            mt5res = None
            acct = MA.account_for(uid) if MA else None
            allowed = bool((MO and MO.is_owner(uid)) or (acct and acct.get("can_trade") is True))
            if req.get("mt5") and MO and allowed:
                if custom_lot is not None:
                    use_lot = custom_lot
                else:
                    mult = CONTRACT_MULT.get(pair, DEFAULT_MULT)
                    use_lot = round(risk_usd / (abs(entry - sl) * mult), 2)
                verdict = {"pair": pair, "side": side, "entry": entry, "sl": sl, "tp1": tp}
                try:
                    mt5res = MO.sync_verdict(verdict, uid, lot=use_lot, account=acct)
                except Exception as e:
                    log(f"mt5 sync error {type(e).__name__}: {str(e)[:120]}")
                    mt5res = {"synced": False, "reason": "sync-error"}
                # Sync paper entry -> actual MT5 fill price (owner 2026-11-21).
                # Paper entry came from the Swissquote feed; the MT5 market order
                # fills at the broker price (spread/feed differ). Without this the
                # resolver arms BE at a different 1R level than MT5 and can mark
                # BE while the live MT5 trade goes on to hit TP (trade #26 bug).
                if mt5res.get("synced") and not mt5res.get("dry_run") and mt5res.get("price") and tr.get("id"):
                    fill = float(mt5res["price"])
                    if fill > 0 and abs(fill - entry) > 1e-9:
                        mult = CONTRACT_MULT.get(pair, DEFAULT_MULT)
                        new_risk = round(use_lot * abs(fill - sl) * mult, 2)
                        sb("PATCH", f"/rest/v1/paper_trades?id=eq.{tr['id']}", body={
                            "entry": fill, "risk_usd": new_risk,
                            "risk_pct": round(new_risk / bal * 100.0, 2) if bal > 0 else risk_pct})
                        tr["entry"] = fill
                        entry = fill
                        log(f"{uid[:8]} paper entry synced to MT5 fill {fill}")
                log(f"{uid[:8]} mt5 {pair} {side} lot={use_lot} -> {mt5res}")
            payload = {"trade": tr, "balance": bal}
            if mt5res is not None:
                payload["mt5"] = mt5res
            return self._send(201, payload)
        except urllib.error.HTTPError as e:
            log(f"POST trade sb HTTP {e.code}: {e.read().decode()[:160]}")
            return self._send(502, {"error": "Could not open trade. Try again."})
        except Exception as e:
            log(f"POST trade error {type(e).__name__}: {str(e)[:140]}")
            return self._send(500, {"error": "Something went wrong. Try again."})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"listening on 127.0.0.1:{PORT} season={SEASON}")
    srv.serve_forever()


if __name__ == "__main__":
    main()