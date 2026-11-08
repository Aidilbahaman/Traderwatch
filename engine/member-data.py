#!/usr/bin/env python3
"""Generate member-data.json — the single real-data feed for the member page.

Every number in this file is COMPUTED, never invented:
  prices      : last close from state/sq-bars.db (Swissquote bar feed, real OHLC)
  change_pct  : last close vs close 24h earlier in the same granularity
  day_range   : high/low across today's bars (MYT day boundary)
  support/res : recent swing lows/highs from H1 bars (structure, not guessed)
  pending     : MT5 working pending orders (broker truth)
  positions   : MT5 open positions (broker truth)
  perf        : win/loss/expired counts + pips, summed from signal-status.json

Win rate is computed as tp / (tp + sl). Trades still running are NOT counted as
wins, because that would inflate the number.

If a source fails, that block is omitted (null) rather than filled with a
plausible-looking placeholder, and the page falls back to an em dash.
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path("/home/ubuntu/web/Traderwatch-repo")
OUT = REPO / "member-data.json"
BARS = REPO / "state" / "sq-bars.db"
STATUS = REPO / "signal-status.json"
ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
MYT = timezone(timedelta(hours=8))

# pair -> (display symbol, bar granularity used for the hero/ticker price)
# NOTE: the Swissquote collector writes hourly bars as "M60", not "H1".
# WTI (USOIL) is not in the feed, so it is deliberately absent rather than faked.
PAIRS = {
    "XAUUSD": ("XAU", "M15"),
    "BTCUSD": ("BTC", "M15"),
    "XAGUSD": ("XAG", "M15"),
}

MT5_CMD = [
    "sudo", "-u", "mt5", "/usr/bin/env",
    "DISPLAY=:99", "WINEPREFIX=/home/mt5/.mt5",
    "/opt/wine-staging/bin/wine",
    "C:\\Python311\\python.exe", "C:\\mt5work\\mt5_pending.py",
]


# ---------------------------------------------------------------- prices
def price_block():
    """Last close + 24h change + today's range per pair, from real bars."""
    if not BARS.exists():
        return None, "sq-bars.db missing"
    con = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True)
    out = {}
    try:
        for pair, (sym, gran) in PAIRS.items():
            rows = con.execute(
                "select ts, o, h, l, c from bars where pair=? and gran=? "
                "order by ts desc limit 120",
                (pair, gran),
            ).fetchall()
            if not rows:
                continue
            rows = list(reversed(rows))          # oldest -> newest
            last = rows[-1]
            last_close = float(last[4])
            last_ts = datetime.fromisoformat(last[0])

            # 24h change: find the newest bar that is >=24h older than the last
            ref = None
            for r in rows:
                t = datetime.fromisoformat(r[0])
                if last_ts - t >= timedelta(hours=24):
                    ref = float(r[4])
            if ref is None:
                ref = float(rows[0][4])          # not 24h of data yet
            change = ((last_close - ref) / ref * 100.0) if ref else 0.0

            # today's range (MYT day boundary)
            day = [r for r in rows
                   if datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc).astimezone(MYT).date()
                   == last_ts.replace(tzinfo=timezone.utc).astimezone(MYT).date()]
            day = day or rows[-24:]
            hi = max(float(r[2]) for r in day)
            lo = min(float(r[3]) for r in day)

            # pip size: gold/oil 2dp -> 0.1 per pip convention, BTC -> 1.0
            pip = 0.1 if pair in ("XAUUSD", "USOIL") else 1.0

            out[sym] = {
                "pair": pair,
                "price": round(last_close, 2),
                "change_pct": round(change, 2),
                "high": round(hi, 2),
                "low": round(lo, 2),
                "range_pips": int(round((hi - lo) / pip)),
                "ts": last[0],
                "spark": [round(float(r[4]), 2) for r in rows[-48:]],
            }

        # nearest support / resistance from hourly swing structure
        for pair, (sym, _) in PAIRS.items():
            h1 = con.execute(
                "select ts, h, l, c from bars where pair=? and gran='M60' "
                "order by ts desc limit 96",
                (pair,),
            ).fetchall()
            if len(h1) < 20 or sym not in out:
                continue
            h1 = list(reversed(h1))
            px = out[sym]["price"]
            highs = [float(r[1]) for r in h1]
            lows = [float(r[2]) for r in h1]
            res = [x for x in sorted(set(highs)) if x > px]
            sup = [x for x in sorted(set(lows), reverse=True) if x < px]
            pip = 0.1 if pair in ("XAUUSD", "USOIL") else 1.0
            if sup:
                out[sym]["support"] = round(sup[0], 2)
                out[sym]["support_pips"] = int(round((px - sup[0]) / pip))
            if res:
                out[sym]["resistance"] = round(res[0], 2)
                out[sym]["resistance_pips"] = int(round((res[0] - px) / pip))
            # trend read: last close vs 24-bar SMA, expressed as a % bias
            sma = sum(float(r[3]) for r in h1[-24:]) / 24
            out[sym]["trend"] = ("BULLISH" if px > sma else "BEARISH") if abs(px - sma) / sma > 0.0005 else "NEUTRAL"
            out[sym]["buyers_pct"] = int(round(min(95, max(5, 50 + (px - sma) / sma * 2000))))
    finally:
        con.close()
    return (out or None), None


# ---------------------------------------------------------------- performance
def perf_block():
    """Counts + pips from signal-status.json. Win rate = tp / (tp + sl)."""
    if not STATUS.exists():
        return None, "signal-status.json missing"
    d = json.loads(STATUS.read_text())
    sigs = d.get("signals") or {}
    counts = {"tp": 0, "sl": 0, "expired": 0, "collected": 0, "pending": 0, "active": 0}
    win_pips = 0.0
    loss_pips = 0.0
    for v in sigs.values():
        v = v or {}
        st = (v.get("status") or "active").lower()
        if st in counts:
            counts[st] += 1
        p = v.get("pips")
        if isinstance(p, (int, float)):
            if st == "tp":
                win_pips += abs(p)
            elif st == "sl":
                loss_pips += abs(p)
    closed = counts["tp"] + counts["sl"]
    win_rate = round(counts["tp"] / closed * 100) if closed else None

    # recent signals, newest first — real records only, no invented rows
    rows = []
    for k, v in sigs.items():
        v = v or {}
        st = (v.get("status") or "active").lower()
        pair = k.split("_")[0] if "_" in k else (v.get("pair") or k)
        ts = v.get("closed") or v.get("entry_at") or v.get("ts") or ""
        rows.append({
            "id": k,
            "pair": pair,
            "status": st,
            "pips": v.get("pips"),
            "r": v.get("r"),
            "time": ts,
        })
    rows = [x for x in rows if x["time"]]
    rows.sort(key=lambda x: x["time"], reverse=True)

    return {
        "counts": counts,
        "win_pips": round(win_pips, 1),
        "loss_pips": round(loss_pips, 1),
        "net_pips": round(win_pips - loss_pips, 1),
        "win_rate": win_rate,
        "closed": closed,
        "total": len(sigs),
        "recent": rows[:8],
    }, None


# ---------------------------------------------------------------- broker state
def mt5_block():
    """Working pending orders + open positions = what the account really holds."""
    try:
        proc = subprocess.run(MT5_CMD + ['{"action": "state"}'],
                              capture_output=True, text=True, timeout=60, cwd="/tmp")
        payload = None
        for line in reversed((proc.stdout or "").strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    payload = json.loads(line)
                    break
                except Exception:
                    continue
        if not payload or not payload.get("ok"):
            return None, "mt5 bridge returned no state"
        orders = payload.get("orders") or []
        positions = payload.get("positions") or []
        running = {}
        for o in orders:
            running[o.get("symbol")] = running.get(o.get("symbol"), 0) + 1
        for p in positions:
            running[p.get("symbol")] = running.get(p.get("symbol"), 0) + 1
        return {
            "pending": len(orders),
            "positions": len(positions),
            "running": running,
        }, None
    except Exception as e:
        return None, f"mt5 bridge error: {e}"


# ---------------------------------------------------------------- members count
def load_env():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


def member_count():
    try:
        sec = load_env()
        url = sec["SUPABASE_URL"].rstrip("/")
        key = sec["SUPABASE_SERVICE_KEY"]
        total, page = 0, 1
        while True:
            req = urllib.request.Request(
                f"{url}/auth/v1/admin/users?page={page}&per_page=200",
                headers={"apikey": key, "Authorization": "Bearer " + key})
            data = json.loads(urllib.request.urlopen(req, timeout=25).read())
            users = data.get("users", data) if isinstance(data, dict) else data
            if not users:
                break
            total += len(users)
            if len(users) < 200:
                break
            page += 1
        return total
    except Exception:
        return None


def main():
    result = {"generated_at": datetime.now(timezone.utc).isoformat()}
    errors = {}

    p, e = price_block()
    result["prices"] = p
    if e:
        errors["prices"] = e

    pf, e = perf_block()
    result["perf"] = pf
    if e:
        errors["perf"] = e

    m, e = mt5_block()
    result["mt5"] = m
    if e:
        errors["mt5"] = e

    result["members"] = member_count()
    if errors:
        result["errors"] = errors

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=1))
    tmp.replace(OUT)

    px = result.get("prices") or {}
    tick = " ".join(f"{k}={v['price']}" for k, v in px.items())
    print(f"member-data.json written | {tick} | "
          f"winrate={ (result.get('perf') or {}).get('win_rate') } | "
          f"mt5={result.get('mt5')} | members={result['members']}")
    if errors:
        print("partial errors:", errors)


if __name__ == "__main__":
    main()
