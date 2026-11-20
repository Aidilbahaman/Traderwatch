#!/usr/bin/env python3
"""TraderWatch Paper Trading League API.

Member-triggered paper trading + leaderboard. Virtual $10,000 balance;
outcomes are resolved by engine/paper-league-resolver.py from real prices,
so results cannot be self-reported.

Endpoints (Caddy proxies /api/league* here):
  GET  /api/league/me          -> balance, net_r, win_rate, open count, rank
  GET  /api/league/trades      -> my trades (newest first)
  GET  /api/league/leaderboard -> aggregated standings (RPC, no private data)
  POST /api/league/trade       -> open a paper trade {pair,side,entry,sl,tp,risk_pct|lot}
                                  optional mt5:true (OWNER ONLY) also places a real
                                  MT5 pending order with the exact lot chosen.

Auth: Supabase member Bearer token on every call.
"""
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Owner-only real-money sync ("Take this trade" -> MT5). Optional: if the MT5
# module cannot load, the league keeps working paper-only.
try:
    import mt5_ondemand as MO
except Exception:
    MO = None

# Live prices from the same Swissquote feed the resolver uses — paper trades
# fill at the CURRENT market price (instant entry), not the stale verdict entry.
try:
    import sq_collector as SQC
except Exception:
    SQC = None


def live_price(pair):
    """Latest M1 close from sq-bars.db, or None if feed missing/stale."""
    if SQC is None:
        return None
    try:
        rows = SQC.candles_from_bars(pair, "M1", 2)
        if not rows:
            return None
        last = rows[-1]
        t = datetime.fromisoformat(str(last["t"]).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - t).total_seconds() > 240:
            return None
        p = float(last["c"])
        return p if p > 0 else None
    except Exception:
        return None

HERE = pathlib.Path(__file__).resolve().parent
ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PORT = int(os.environ.get("LEAGUE_PORT", "8103"))
SEASON = int(os.environ.get("LEAGUE_SEASON", "1"))
START_BALANCE = 10000.0
ALLOWED_PAIRS = {"XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD",
                 "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"}
MAX_OPEN_PER_PAIR = 1
MAX_OPEN_TOTAL = 5
RISK_CHOICES = (1.0, 2.0)
# Contract multiplier (USD per 1.0 price move per 1 lot) — matches frontend lotFor.
CONTRACT_MULT = {"XAUUSD": 100.0, "XAGUSD": 5000.0, "BTCUSD": 1.0}
DEFAULT_MULT = 100000.0  # standard forex lot
MAX_LOT = 100.0
MIN_LOT = 0.01


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
    try:
        req = urllib.request.Request(SB_URL + "/auth/v1/user")
        req.add_header("apikey", SB_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None


def display_name(user):
    meta = user.get("user_metadata") or {}
    return (meta.get("name") or (user.get("email") or "trader").split("@")[0])[:40]


def my_trades(uid, limit=100):
    return sb("GET", "/rest/v1/paper_trades", params={
        "select": "*", "user_id": f"eq.{uid}", "season": f"eq.{SEASON}",
        "order": "opened_at.desc", "limit": str(limit)}) or []


def balance_of(trades):
    closed = [t for t in trades if t["status"] in ("tp", "sl", "be") and t.get("r_result") is not None]
    profit = sum(float(t["r_result"]) * float(t["risk_usd"]) for t in closed)
    return round(START_BALANCE + profit, 2), closed


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
            if path == "/api/league/trades":
                return self._send(200, {"trades": my_trades(uid), "season": SEASON})
            if path == "/api/league/leaderboard":
                rows = sb("POST", "/rest/v1/rpc/get_leaderboard", body={"p_season": SEASON}) or []
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
                board = sb("POST", "/rest/v1/rpc/get_leaderboard", body={"p_season": SEASON}) or []
                me = display_name(user)
                rank = next((i + 1 for i, r in enumerate(board) if r.get("user_id") == uid), None)
                return self._send(200, {
                    "balance": bal, "start_balance": START_BALANCE, "net_r": net_r,
                    "win_rate": round(100.0 * wins / dec, 1) if dec else None,
                    "trades_closed": len(closed), "trades_open": open_n,
                    "rank": rank, "season": SEASON, "username": me,
                    "is_owner": bool(MO and MO.is_owner(uid))})
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
            row = sb("POST", "/rest/v1/paper_trades", body=body)
            tr = (row or [{}])[0]
            log(f"{uid[:8]} opened {pair} {side} " + (f"lot={custom_lot}" if custom_lot is not None else f"risk {risk_pct}%"))
            # Owner-only: also place a REAL MT5 pending order with the exact lot
            # chosen (custom lot, or the risk-% lot). Members / mt5 absent -> paper only.
            mt5res = None
            if req.get("mt5") and MO and MO.is_owner(uid):
                if custom_lot is not None:
                    use_lot = custom_lot
                else:
                    mult = CONTRACT_MULT.get(pair, DEFAULT_MULT)
                    use_lot = round(risk_usd / (abs(entry - sl) * mult), 2)
                verdict = {"pair": pair, "side": side, "entry": entry, "sl": sl, "tp1": tp}
                try:
                    mt5res = MO.sync_verdict(verdict, uid, lot=use_lot)
                except Exception as e:
                    log(f"mt5 sync error {type(e).__name__}: {str(e)[:120]}")
                    mt5res = {"synced": False, "reason": "sync-error"}
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