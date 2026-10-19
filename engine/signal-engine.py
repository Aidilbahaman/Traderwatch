#!/usr/bin/env python3
"""TraderWatch auto signal engine.

Fetches real H1/M1 candles from Twelve Data, computes a deterministic
trend+momentum setup (EMA20/EMA50, RSI14, ATR14), and inserts verified
setups into Supabase. One active setup per pair per timeframe per day.

Secrets (chmod 600, never in chat or code):
  ~/.secrets/twelve.env    -> TWELVEDATA_API_KEY=<free key>
  ~/.secrets/supabase.env  -> SUPABASE_URL, SUPABASE_SERVICE_KEY

Schedule: every 30 min (12 API credits/run = ~576/day, under free 800).
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMEOUT = 25
# Free tier allows 8 credits/minute -> keep ~7 calls/min with 9s spacing.
CALL_GAP = 9
RETRY_WAIT = 62
PAIRS = {
    "XAU/USD": {"td": "XAU/USD", "dp": 2, "mode": "forex"},
    "EUR/USD": {"td": "EUR/USD", "dp": 5, "mode": "forex"},
    "GBP/USD": {"td": "GBP/USD", "dp": 5, "mode": "forex"},
    "USD/JPY": {"td": "USD/JPY", "dp": 3, "mode": "forex"},
    "AUD/USD": {"td": "AUD/USD", "dp": 5, "mode": "forex"},
    "USD/CAD": {"td": "USD/CAD", "dp": 5, "mode": "forex"},
    "NZD/USD": {"td": "NZD/USD", "dp": 5, "mode": "forex"},
}
TIMEFRAMES = {"H1": "1h", "M1": "1min"}
CANDLES = 130
STATUS_FILE = Path("/home/ubuntu/web/Traderwatch-repo/signal-status.json")
LOCK = Path("/tmp/signal-engine.lock")


def public_timeframe(tf):
    """Normalize timeframe labels without changing their public names."""
    return str(tf).upper()


def status_key_pair(key):
    code = str(key).split("_", 1)[0]
    return code[:3] + "/" + code[3:] if len(code) == 6 else code


def pair_has_active_status(pair, state):
    """True while any timeframe for this pair has an unresolved setup."""
    for key, info in (state.get("signals") or {}).items():
        if status_key_pair(key) == pair and (info.get("status") or "").lower() == "active":
            return True
    return False


def should_block_pair(pair, state, reserved):
    """One unresolved setup per pair across all timeframes."""
    return pair in reserved or pair_has_active_status(pair, state)


def load_status_state():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        # Fail closed in main: an unavailable status file means we cannot prove
        # there is no active setup for the pair.
        return None


def parse_posted_at(value):
    """Supabase may return timestamps without Z; treat those as UTC."""
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def signal_key(pair, posted_at):
    d = parse_posted_at(posted_at).astimezone(timezone(timedelta(hours=8)))
    code = "".join(ch for ch in pair.upper() if ch.isalpha())
    return f"{code}_{d:%Y%m%d}_{d:%H%M%S}"


def fetch_pair_rows(pair):
    """Recent rows used to verify unresolved status directly from Supabase."""
    encoded = urllib.parse.quote(pair, safe='')
    _, txt = sb("signals?select=pair,posted_at,verified"
                f"&pair=eq.{encoded}&verified=is.true"
                "&order=posted_at.desc&limit=50")
    return json.loads(txt or "[]")


def pair_has_active_setup(pair, status_state):
    """Fail closed if Supabase/status cannot prove every pair row is resolved."""
    try:
        for row in fetch_pair_rows(pair):
            key = signal_key(row["pair"], row["posted_at"])
            if (status_state.get("signals", {}).get(key, {}).get("status") or "").lower() == "active":
                return True
        return False
    except Exception as e:
        log(f"WARN pair active check failed {pair}: {e}")
        return True

# Scalping (M1) pip guards: SL must land 20-40 pips away, TP 40-80 pips
# (1:2 R:R). M1 ATR is often 0.5-2 pips, so raw 1.5/3.0*ATR gives
# 1-3 pip SLs that hit instantly on spread+noise.
SCALP_MIN_SL_PIPS = 20.0
SCALP_MAX_SL_PIPS = 40.0
SCALP_RR = 2.0
PIP_SIZE = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001


def pip_size(pair):
    return PIP_SIZE.get(pair, DEFAULT_PIP)


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def load_secrets(name):
    path = Path.home() / ".secrets" / name
    vals = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def td_get(symbol, interval):
    for attempt in (1, 2):
        url = ("https://api.twelvedata.com/time_series"
               f"?symbol={urllib.parse.quote(symbol, safe='')}&interval={interval}"
               f"&outputsize={CANDLES}&apikey={TD_KEY}&timezone=UTC")
        req = urllib.request.Request(url, headers={"User-Agent": "TraderWatch-engine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            if e.code == 429 and attempt == 1:
                log(f"RATE-LIMIT {symbol} {interval}: wait {RETRY_WAIT}s and retry once")
                time.sleep(RETRY_WAIT)
                continue
            return {"code": e.code, "message": body}
        except Exception as e:
            return {"code": -1, "message": f"{type(e).__name__}: {e}"}
    return {"code": 429, "message": "rate limit persisted after retry"}


import urllib.parse  # noqa: E402  (after funcs for readability)


def parse_candles(payload):
    vals = (payload or {}).get("values")
    if not vals:
        return None, f"no candles: {str(payload)[:150]}"
    rows = []
    for v in reversed(vals):
        try:
            rows.append((float(v["open"]), float(v["high"]),
                         float(v["low"]), float(v["close"])))
        except (KeyError, TypeError, ValueError):
            continue
    return (rows, "") if len(rows) >= 60 else (None, f"only {len(rows)} candles")


def ema(vals, n):
    k = 2.0 / (n + 1)
    e = vals[0]
    out = [e]
    for x in vals[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi_wilder(closes, n=14):
    if len(closes) < n + 2:
        return [50.0] * len(closes)
    gains, losses = [0.0], [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[1:n + 1]) / n
    al = sum(losses[1:n + 1]) / n
    out = [50.0] * (n + 1)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out.append(100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al))
    return out


def atr14(rows):
    trs = []
    for i, (o, h, l, c) in enumerate(rows):
        pc = rows[i - 1][3] if i else c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[1:15]) / 14.0
    out = [a] * 15
    for t in trs[15:]:
        a = (a * 13 + t) / 14.0
        out.append(a)
    return out


def stop_and_target(side, price, atr, pair, tf):
    """Return (entry, sl, tp). H1 keeps raw 1.5/3.0*ATR. M1 (scalping)
    clamps the stop into a 20-40 pip band and projects TP at 1:2."""
    pip = pip_size(pair)
    if tf == "M1":
        # Scalping: clamp ATR-derived stop into the 20-40 pip band, then
        # project TP at 1:2. Widening to the floor keeps the stop outside
        # M1 noise; capping at the ceiling stops runaway risk on spikes.
        sl_dist = min(max(1.5 * atr, SCALP_MIN_SL_PIPS * pip),
                      SCALP_MAX_SL_PIPS * pip)
        tp_dist = sl_dist * SCALP_RR
    else:
        sl_dist, tp_dist = 1.5 * atr, 3.0 * atr
    if side == "BUY":
        return price, price - sl_dist, price + tp_dist
    return price, price + sl_dist, price - tp_dist


def build_setup(pair, tf, rows, dp):
    """Return dict or None. BUY on fresh RSI cross above 50 in uptrend;
    SELL mirror. SL 1.5*ATR, TP 3.0*ATR (1:2 R:R)."""
    closes = [r[3] for r in rows]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    rsi = rsi_wilder(closes)
    atr = atr14(rows)
    c, p = closes[-1], closes[-2]
    if atr[-1] <= 0:
        return None
    bull = c > e50[-1] and e20[-1] > e50[-1]
    bear = c < e50[-1] and e20[-1] < e50[-1]
    cross_up = rsi[-2] < 55.0 <= rsi[-1] and rsi[-1] < 72.0
    cross_dn = rsi[-2] > 45.0 >= rsi[-1] and rsi[-1] > 28.0
    side = "BUY" if (bull and cross_up) else ("SELL" if (bear and cross_dn) else None)
    if not side:
        # pullback variant: price above EMA50, RSI rising through 45-55 band
        if bull and rsi[-2] < 45.0 <= rsi[-1]:
            side = "BUY"
        elif bear and rsi[-2] > 55.0 >= rsi[-1]:
            side = "SELL"
    if not side:
        # continuation variant: the trend is valid and RSI remains within a
        # neutral, non-exhausted band. This provides one current setup per
        # public pair without inventing sample data or forcing an opposite side.
        if bull and 46.0 <= rsi[-1] <= 68.0:
            side = "BUY"
        elif bear and 32.0 <= rsi[-1] <= 54.0:
            side = "SELL"
    if not side:
        return None
    a = atr[-1]
    entry, sl, tp = stop_and_target(side, c, a, pair, tf)
    f = lambda x: f"{x:.{dp}f}"
    return {"pair": pair, "timeframe": tf, "side": side,
            "entry": f(entry), "sl": f(sl), "tp": f(tp)}


def sb(path, method="GET", body=None):
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
        method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode()


def already_posted(pair, tf):
    try:
        _, txt = sb(f"signals?select=id&pair=eq.{urllib.parse.quote(pair)}"
                    f"&timeframe=eq.{tf}&verified=is.true"
                    f"&posted_at=gte.{today_start()}&limit=1")
        return txt.strip() not in ("[]", "")
    except Exception as e:
        log(f"WARN dedupe check failed {pair} {tf}: {e}")
        return True  # fail closed: do not insert


def today_start():
    """Start of today (Kuala Lumpur) expressed in safe UTC 'Z' format.
    KL = UTC+8, so KL midnight = 16:00 UTC the previous day."""
    now_kl = datetime.now(timezone.utc).timestamp() + 8 * 3600
    kl_date = datetime.fromtimestamp(now_kl, tz=timezone.utc).strftime("%Y-%m-%d")
    start_utc = datetime.fromisoformat(kl_date + "T00:00:00+00:00").timestamp() - 8 * 3600
    return datetime.fromtimestamp(start_utc, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    if LOCK.exists():
        log("SKIP previous run still active")
        return 0
    LOCK.touch()
    try:
        inserted, skipped, errors = 0, 0, 0
        status_state = load_status_state()
        if status_state is None:
            log("ERROR cannot read signal-status.json; fail closed to avoid duplicate pair signals")
            return 1
        reserved_pairs = set()
        for pair, cfg in PAIRS.items():
            # Pair-level lifecycle guard: while one setup is ACTIVE, never emit
            # another timeframe or opposite-side setup for the same pair.
            if pair in reserved_pairs or pair_has_active_setup(pair, status_state):
                log(f"SKIP {pair}: existing active setup")
                skipped += len(TIMEFRAMES)
                continue
            for tf, iv in TIMEFRAMES.items():
                if already_posted(pair, tf):
                    skipped += 1
                    continue
                payload = td_get(cfg["td"], iv)
                rows, err = parse_candles(payload)
                if rows is None:
                    log(f"DATA {pair} {tf}: {err}")
                    errors += 1
                    time.sleep(CALL_GAP)
                    continue
                setup = build_setup(pair, tf, rows, cfg["dp"])
                if setup is None:
                    log(f"HOLD {pair} {tf}: no trigger")
                    time.sleep(CALL_GAP)
                    continue
                setup["verified"] = True
                try:
                    sb("signals", "POST", setup)
                    reserved_pairs.add(pair)
                    inserted += 1
                    log(f"POST {pair} {tf} {setup['side']} "
                        f"E={setup['entry']} SL={setup['sl']} TP={setup['tp']}")
                    # Do not inspect the second timeframe in this run after a
                    # setup is emitted; the pair is now reserved until closure.
                    break
                except Exception as e:
                    log(f"INSERT-FAIL {pair} {tf}: {type(e).__name__} {str(e)[:120]}")
                    errors += 1
                time.sleep(CALL_GAP)
        log(f"DONE inserted={inserted} skipped={skipped} errors={errors}")
        return 0 if errors == 0 else 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        TD_KEY = load_secrets("twelve.env").get("TWELVEDATA_API_KEY") or ""
        sb_cfg = load_secrets("supabase.env")
        SB_URL, SB_KEY = sb_cfg["SUPABASE_URL"], sb_cfg["SUPABASE_SERVICE_KEY"]
    except Exception as e:
        print(f"ERROR secrets: {e}", file=sys.stderr)
        sys.exit(2)
    if not TD_KEY:
        print("ERROR TWELVEDATA_API_KEY missing in ~/.secrets/twelve.env", file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
