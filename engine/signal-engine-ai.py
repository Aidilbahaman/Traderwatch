#!/usr/bin/env python3
"""TraderWatch AI signal engine — M15, logistic model decides side + trade.

The model is trained offline by train-ai-model.py and loaded from
state/ai-m15-model.json. This script never refits, so a cron tick cannot stall.

Differences from signal-engine.py (the rule engine):
  * decision is a trained logistic model, not EMA/RSI trigger rules
  * timeframe is M15 only
  * threshold gate: emit only when max(p_long, p_short) >= THRESHOLD

Shared with the rule engine:
  * one active setup per pair across all timeframes (pair lifecycle guard)
  * one setup per pair per timeframe per day (daily dedupe)
  * SL = max(1.5*ATR, 12 pips), TP = 2*SL
  * fail closed when the status file or Supabase check errors

Secrets: ~/.secrets/twelve.env, ~/.secrets/supabase.env
"""
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M  # noqa: E402

TIMEOUT = 25
TZ_KL = timezone(timedelta(hours=8))
CALL_GAP = 9
RETRY_WAIT = 62
CANDLES = 300
REPO = HERE.parent
STATUS_FILE = REPO / "signal-status.json"
MODEL_FILE = REPO / "state" / "ai-m15-model.json"
LOCK = Path("/tmp/signal-engine-ai.lock")

THRESHOLD = 0.55
SCALP_MIN_SL_PIPS = 12.0
SCALP_RR = 2.0
TIMEFRAME = "M15"
TD_INTERVAL = "15min"

PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"]
DP = {"XAU/USD": 2, "USD/JPY": 3}
DEFAULT_DP = 5


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def load_secrets(name):
    vals = {}
    p = Path.home() / ".secrets" / name
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


SB = load_secrets("supabase.env")
SB_URL = SB["SUPABASE_URL"]
SB_KEY = SB["SUPABASE_SERVICE_KEY"]
TD_KEY = ""


def sb(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{path}", data=data, method=method,
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                 "Content-Type": "application/json",
                 "Prefer": "return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def td_get(symbol, interval, outputsize=CANDLES):
    for attempt in (1, 2):
        url = ("https://api.twelvedata.com/time_series"
               f"?symbol={urllib.parse.quote(symbol, safe='')}&interval={interval}"
               f"&outputsize={outputsize}&apikey={TD_KEY}&timezone=UTC")
        req = urllib.request.Request(url, headers={"User-Agent": "TraderWatch-ai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            if e.code == 429 and attempt == 1:
                log(f"RATE-LIMIT {symbol}: wait {RETRY_WAIT}s")
                time.sleep(RETRY_WAIT)
                continue
            return {"code": e.code, "message": body}
        except Exception as e:
            return {"code": -1, "message": f"{type(e).__name__}: {e}"}
    return {"code": 429, "message": "rate limit persisted"}


def parse_candles(payload):
    vals = (payload or {}).get("values")
    if not vals:
        return None, f"no candles: {str(payload)[:150]}"
    out = []
    for v in reversed(vals):
        d = datetime.fromisoformat(v["datetime"].replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append((int(d.timestamp() * 1000), float(v["high"]),
                    float(v["low"]), float(v["close"])))
    return out, ""


def today_start():
    now_kl = datetime.now(timezone.utc).timestamp() + 8 * 3600
    kl_date = datetime.fromtimestamp(now_kl, tz=timezone.utc).strftime("%Y-%m-%d")
    start_utc = datetime.fromisoformat(kl_date + "T00:00:00+00:00").timestamp() - 8 * 3600
    return datetime.fromtimestamp(start_utc, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key_for(pair, posted_at):
    """Same key shape signal-status.py writes: CODE_YYYYMMDD_HHMMSS in KL."""
    code = "".join(ch for ch in str(pair).upper() if ch.isalpha())
    d = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return f"{code}_{d.astimezone(TZ_KL).strftime('%Y%m%d_%H%M%S')}"


def pair_recent_unresolved(pair, state):
    """True when the pair's newest DB signal is not yet resolved.

    Closes the race between posting a signal and signal-status.py recording it
    as active: an unknown or active key both block a new post.
    """
    code, txt = sb(f"signals?select=posted_at&pair=eq.{urllib.parse.quote(pair)}"
                   f"&verified=is.true&order=posted_at.desc&limit=1")
    if code != 200:
        return True
    try:
        rows = json.loads(txt or "[]")
    except Exception:
        return True
    if not rows:
        return False
    key = key_for(pair, rows[0]["posted_at"])
    info = (state.get("signals") or {}).get(key)
    if not info:
        return True
    return str(info.get("status")).lower() == "active"


def already_posted(pair):
    code, txt = sb(f"signals?select=id&pair=eq.{urllib.parse.quote(pair)}"
                   f"&timeframe=eq.{TIMEFRAME}&verified=is.true"
                   f"&posted_at=gte.{today_start()}&limit=1")
    if code != 200:
        return True
    return txt.strip() not in ("[]", "")


def load_status_state():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception as e:
        log(f"ERROR status file: {e}")
        return None


def pair_has_active(pair, state):
    code = "".join(ch for ch in pair.upper() if ch.isalpha())
    for key, info in (state.get("signals") or {}).items():
        if str(info.get("status")).lower() != "active":
            continue
        if str(key).split("_", 1)[0] == code:
            return True
    return False


def in_session(now=None):
    """08:00-01:00 MYT — covers Asian open through New York close.

    Sized so 7 pairs at a 10-minute scan plus a 15-minute status sweep land
    around 700 of the 800 free daily credits.
    """
    h = (now or datetime.now(TZ_KL)).astimezone(TZ_KL).hour
    return h >= 8 or h < 1


def decide(model, bars):
    """Return (side, confidence) or (None, 0.0)."""
    closes = [b[3] for b in bars]
    if len(closes) < 60:
        return None, 0.0
    e20, e50 = M.ema(closes, 20), M.ema(closes, 50)
    rsi, atr = M.rsi_s(closes), M.atr_s(bars)
    i = len(bars) - 1
    f = M.feature_row(model["_pair"], bars, e20, e50, rsi, atr, i)
    if f is None:
        return None, 0.0
    p_long = M.predict(model["long"], f)
    p_short = M.predict(model["short"], f)
    side = "BUY" if p_long >= p_short else "SELL"
    conf = max(p_long, p_short)
    if conf < THRESHOLD:
        return None, conf
    return side, conf


def build_levels(pair, side, price, atr):
    pip = M.pip_of(pair)
    sl_dist = max(1.5 * atr, SCALP_MIN_SL_PIPS * pip)
    tp_dist = sl_dist * SCALP_RR
    if side == "BUY":
        return price - sl_dist, price + tp_dist
    return price + sl_dist, price - tp_dist


def credit_budget_ok(reserve=100):
    """False when the daily quota is nearly gone.

    New signals are optional; closing TP/SL is not. Once the day's usage gets
    within `reserve` credits of the plan limit, the engine stands down so
    signal-status.py can still resolve open setups.
    """
    try:
        with urllib.request.urlopen(
                "https://api.twelvedata.com/api_usage?apikey=" + TD_KEY,
                timeout=20) as r:
            d = json.loads(r.read().decode())
        used = int(d.get("daily_usage", 0))
        limit = int(d.get("plan_daily_limit", 800))
        if used >= limit - reserve:
            log(f"SKIP credit guard: {used}/{limit} used, "
                f"reserving {reserve} for TP/SL checks")
            return False
        return True
    except Exception as e:
        log(f"WARN credit check failed ({type(e).__name__}); continuing")
        return True


def main():
    global TD_KEY
    dry = "--dry-run" in sys.argv
    if LOCK.exists():
        log("SKIP previous run still active")
        return 0
    LOCK.touch()
    try:
        if not MODEL_FILE.exists():
            log(f"ERROR model missing: {MODEL_FILE}")
            return 1
        payload = M.load_model(MODEL_FILE)
        models = payload.get("pairs") or {}
        if not models:
            log("ERROR model has no pairs")
            return 1

        state = load_status_state()
        if state is None:
            log("ERROR cannot read signal-status.json; fail closed")
            return 1

        if not in_session():
            log("SKIP outside session window")
            return 0

        TD_KEY = load_secrets("twelve.env").get("TWELVEDATA_API_KEY", "")
        if not TD_KEY:
            log("ERROR no TWELVEDATA_API_KEY")
            return 1

        if not credit_budget_ok():
            return 0

        inserted = skipped = errors = 0
        for pair in PAIRS:
            if pair not in models:
                skipped += 1
                continue
            if pair_has_active(pair, state) or pair_recent_unresolved(pair, state):
                log(f"SKIP {pair}: existing active setup")
                skipped += 1
                continue
            # No daily dedupe: the AI is the only producer now, so a pair may
            # post again as soon as its previous setup resolves. The pair
            # lifecycle guard above is what prevents duplicates.

            payload_c = td_get(pair, TD_INTERVAL)
            bars, err = parse_candles(payload_c)
            if not bars:
                log(f"DATA {pair} {TIMEFRAME}: {err}")
                errors += 1
                time.sleep(CALL_GAP)
                continue

            model = dict(models[pair])
            model["_pair"] = pair
            side, conf = decide(model, bars)
            if side is None:
                log(f"HOLD {pair} {TIMEFRAME}: conf {conf:.3f} < {THRESHOLD}")
                time.sleep(CALL_GAP)
                continue

            closes = [b[3] for b in bars]
            atr = M.atr_s(bars)[-1]
            entry = closes[-1]
            sl, tp = build_levels(pair, side, entry, atr)
            dp = DP.get(pair, DEFAULT_DP)
            row = {"pair": pair, "timeframe": TIMEFRAME, "side": side,
                   "entry": f"{entry:.{dp}f}", "sl": f"{sl:.{dp}f}",
                   "tp": f"{tp:.{dp}f}", "verified": True}
            if dry:
                inserted += 1
                log(f"DRY {pair} {TIMEFRAME} {side} E={row['entry']} "
                    f"SL={row['sl']} TP={row['tp']} conf={conf:.3f}")
                time.sleep(1)
                continue
            code, txt = sb("signals", "POST", row)
            if code in (200, 201):
                inserted += 1
                log(f"POST {pair} {TIMEFRAME} {side} E={row['entry']} "
                    f"SL={row['sl']} TP={row['tp']} conf={conf:.3f}")
            else:
                errors += 1
                log(f"INSERT-FAIL {pair}: {code} {txt[:120]}")
            time.sleep(CALL_GAP)

        log(f"DONE inserted={inserted} skipped={skipped} errors={errors}")
        return 0
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL {type(e).__name__} {e}")
        try:
            os.remove(LOCK)
        except Exception:
            pass
        sys.exit(1)
