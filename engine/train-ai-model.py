#!/usr/bin/env python3
"""Train the M15 Fully-AI model from cached candles.

Produces state/ai-m15-model.json, which signal-engine-ai.py loads at runtime.
Training happens offline; the live engine never refits, so a cron run cannot
stall on a long fit.

Labels use the exact ticket the live engine will trade:
  SL = max(1.5 * ATR14, 12 pips), TP = 2 * SL, 4h hold, expiry at market,
  spread deducted, ambiguous bar counted as a loss.

Usage:
  python3 engine/train-ai-model.py
  python3 engine/train-ai-model.py --bars 1000
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M  # noqa: E402

REPO = HERE.parent
M1DIR = Path("/home/ubuntu/web/state/ai-m1")
OUT = REPO / "state" / "ai-m15-model.json"

PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"]
SPREAD = {"EUR/USD": 1.0, "GBP/USD": 1.3, "AUD/USD": 1.3, "NZD/USD": 1.5,
          "USD/CAD": 1.5, "USD/JPY": 1.5, "XAU/USD": 3.0}
SCALP_MIN_SL_PIPS = 12.0
SCALP_RR = 2.0
MAX_HOLD_BARS = 16


def load_m1(pair):
    p = M1DIR / f"{pair.replace('/', '')}_M1.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    bars = []
    for v in raw:
        d = datetime.fromisoformat(v["datetime"].replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        bars.append((int(d.timestamp() * 1000), float(v["high"]),
                     float(v["low"]), float(v["close"])))
    bars.sort(key=lambda x: x[0])
    return bars


def to_m15(m1):
    buckets = {}
    for ts, h, l, c in m1:
        slot = ts - (ts % (M.BAR_MIN * 60 * 1000))
        if slot in buckets:
            b = buckets[slot]
            buckets[slot] = (b[0], max(b[1], h), min(b[2], l), c)
        else:
            buckets[slot] = (slot, h, l, c)
    return [buckets[k] for k in sorted(buckets)]


def levels(pair, side, price, atr):
    pip = M.pip_of(pair)
    sl_dist = max(1.5 * atr, SCALP_MIN_SL_PIPS * pip)
    tp_dist = sl_dist * SCALP_RR
    if side == "BUY":
        return price - sl_dist, price + tp_dist
    return price + sl_dist, price - tp_dist


def resolve(bars, i, pair, side, sl, tp):
    pip = M.pip_of(pair)
    spread = SPREAD.get(pair, 1.5)
    entry = bars[i][3]
    sign = 1 if side == "BUY" else -1
    end = min(len(bars), i + 1 + MAX_HOLD_BARS)
    for j in range(i + 1, end):
        hi, lo = bars[j][1], bars[j][2]
        hit_tp = hi >= tp if sign > 0 else lo <= tp
        hit_sl = lo <= sl if sign > 0 else hi >= sl
        if hit_tp and hit_sl:
            return -abs(entry - sl) / pip - spread
        if hit_sl:
            return -abs(entry - sl) / pip - spread
        if hit_tp:
            return abs(tp - entry) / pip - spread
    close = bars[min(len(bars) - 1, i + MAX_HOLD_BARS)][3]
    return (close - entry) * sign / pip - spread


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0,
                    help="limit to the most recent N M15 bars (0 = all)")
    args = ap.parse_args()

    models, report = {}, []
    for pair in PAIRS:
        m1 = load_m1(pair)
        if not m1:
            print(f"{pair:9} SKIP no cached M1")
            continue
        bars = to_m15(m1)
        if args.bars:
            bars = bars[-args.bars:]
        closes = [b[3] for b in bars]
        e20, e50 = M.ema(closes, 20), M.ema(closes, 50)
        rsi, atr = M.rsi_s(closes), M.atr_s(bars)

        rows = []
        for i in range(60, len(bars) - 1):
            f = M.feature_row(pair, bars, e20, e50, rsi, atr, i)
            if f is None:
                continue
            sl_b, tp_b = levels(pair, "BUY", closes[i], atr[i])
            sl_s, tp_s = levels(pair, "SELL", closes[i], atr[i])
            pl = resolve(bars, i, pair, "BUY", sl_b, tp_b)
            ps = resolve(bars, i, pair, "SELL", sl_s, tp_s)
            rows.append({"f": f,
                         "y_long": 1 if pl > 0 else 0,
                         "y_short": 1 if ps > 0 else 0})
        if len(rows) < 200:
            print(f"{pair:9} SKIP only {len(rows)} rows")
            continue

        wL, mL, sL = M.fit(rows, "y_long")
        wS, mS, sS = M.fit(rows, "y_short")
        models[pair] = {"long": {"w": wL, "mu": mL, "sd": sL},
                        "short": {"w": wS, "mu": mS, "sd": sS}}
        days = (bars[-1][0] - bars[0][0]) / 86400000
        base_long = sum(r["y_long"] for r in rows) / len(rows)
        base_short = sum(r["y_short"] for r in rows) / len(rows)
        report.append({"pair": pair, "days": round(days, 1), "rows": len(rows),
                       "base_long": round(base_long, 3),
                       "base_short": round(base_short, 3)})
        print(f"{pair:9} rows={len(rows):5} days={days:4.1f} "
              f"base_long={base_long:.2f} base_short={base_short:.2f}")

    if not models:
        print("no models trained", file=sys.stderr)
        return 1

    payload = {"version": M.FEATURE_VERSION,
               "timeframe": "M15",
               "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "ticket": {"sl": f"max(1.5*ATR,{SCALP_MIN_SL_PIPS}p)",
                          "tp": f"{SCALP_RR}xSL", "max_hold_bars": MAX_HOLD_BARS},
               "pairs": models,
               "report": report}
    M.save_model(OUT, payload)
    print(f"\nsaved {OUT} ({len(models)} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
