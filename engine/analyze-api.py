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
import sq_collector as SQC      # noqa: E402

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PORT = int(os.environ.get("ANALYZE_PORT", "8102"))
ALLOWED_PAIRS = {"XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD",
                 "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"}   # pairs dengan data bar live
MIN_GAP_S = 20                      # min seconds between analyses per user
HOURLY_CAP = 12                     # max analyses per user per hour
BARS_COUNT = 300                    # M15 bars fed to the analyst

_last_call = {}                     # uid -> ts of last accepted analysis
_hour_count = {}                    # uid -> [window_start_ts, count]


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


def rate_check(uid):
    """Return (ok, message). Enforces min gap + hourly cap per user."""
    now = time.time()
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


def fetch_bars(pair):
    rows = SQC.candles_from_bars(pair, "M15", BARS_COUNT)
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
    rows = SQC.candles_from_bars(pair, base_gran, 2000)
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


def run_analysis(pair):
    bars = fetch_bars(pair)
    if len(bars) < 100:
        return {"error": "Data bar tidak mencukupi untuk analisis. Cuba lagi sebentar."}
    disp = pair[:3] + "/" + pair[3:]
    pip = M.pip_of(disp)
    spread = SMC.SPREAD_PIPS.get(pair, SMC.DEFAULT_SPREAD_PIPS)
    verdict = LA.analyze(disp, bars, pip, spread)
    price = bars[-1][3]
    if verdict is None:
        return {"side": "HOLD", "pair": disp, "price": price,
                "reason": "Tiada setup jelas sekarang. Enjin menunggu peluang lebih baik.",
                "generated_at": datetime.now(timezone.utc).isoformat()}
    verdict.update({"pair": disp, "price": price,
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
                candles = fetch_ohlc(pair, tf)
            except Exception as e:
                log(f"bars {pair} error {type(e).__name__}: {str(e)[:120]}")
                return self._send(500, {"error": "Gagal memuatkan data chart."})
            if not candles:
                return self._send(404, {"error": "Tiada data bar untuk pair ini."})
            return self._send(200, {"pair": pair, "tf": tf, "candles": candles})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
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
        if pair not in ALLOWED_PAIRS:
            return self._send(400, {"error": "Buat masa ini hanya XAUUSD dibuka untuk analisis."})
        ok, msg = rate_check(uid)
        if not ok:
            return self._send(429, {"error": msg})
        rate_commit(uid)
        log(f"{uid[:8]} request {pair}")
        try:
            result = run_analysis(pair)
        except Exception as e:
            log(f"{pair} error {type(e).__name__}: {str(e)[:160]}")
            return self._send(500, {"error": "Analisis gagal buat masa ini. Cuba lagi sebentar."})
        log(f"{uid[:8]} {pair} -> {result.get('side')}")
        return self._send(200, result)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"listening on 127.0.0.1:{PORT} (pairs={sorted(ALLOWED_PAIRS)})")
    srv.serve_forever()


if __name__ == "__main__":
    main()