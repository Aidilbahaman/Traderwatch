#!/usr/bin/env python3
"""M15 head-to-head: current rule engine vs Fully AI (Raisa V11).

Both strategies see the SAME M15 bars, the SAME execution ticket, the SAME
spread, the SAME one-position-per-pair lock and the SAME expiry rule. Only the
decision function differs, so the win-rate gap is attributable to the strategy.

Ticket (identical for both sides):
  SL = max(1.5 * ATR14, 12 pips)
  TP = 2 * SL
  max hold = 16 M15 bars (4 hours)
  expiry resolves at market close, spread always deducted
  ambiguous bar (TP and SL in one bar) counts as a LOSS

Data: cached M1 candles resampled to M15. No network calls, no writes to
Supabase, no Telegram. This is research only.

Usage:
  python3 research/m15_compare.py
  python3 research/m15_compare.py --json out.json
"""
import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

M1DIR = Path("/home/ubuntu/web/state/ai-m1")
PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD"]
PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001
SPREAD = {"EUR/USD": 1.0, "GBP/USD": 1.3, "AUD/USD": 1.3,
          "USD/CAD": 1.5, "USD/JPY": 1.5, "XAU/USD": 3.0}

SCALP_MIN_SL_PIPS = 12.0
SCALP_RR = 2.0
MAX_HOLD_BARS = 16          # 16 x M15 = 4 hours
TRAIN_HOURS = 96
TEST_HOURS = 24
THRESHOLD = 0.55
BAR_MIN = 15


def pip_of(pair):
    return PIP.get(pair, DEFAULT_PIP)


# ---------------------------------------------------------------- indicators
def ema(v, n):
    k = 2.0 / (n + 1)
    e = v[0]
    out = [e]
    for x in v[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi_s(v, n=14):
    if len(v) < n + 2:
        return [50.0] * len(v)
    gains, losses = [0.0], [0.0]
    for i in range(1, len(v)):
        d = v[i] - v[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[1:n + 1]) / n
    al = sum(losses[1:n + 1]) / n
    out = [50.0] * (n + 1)
    for i in range(n + 1, len(v)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out.append(100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al))
    return out


def atr_s(bars, n=14):
    tr = []
    for i, (ts, h, l, c) in enumerate(bars):
        pc = bars[i - 1][3] if i else c
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(tr) < n + 1:
        return [0.0] * len(bars)
    a = sum(tr[1:n + 1]) / n
    out = [a] * (n + 1)
    for x in tr[n + 1:]:
        a = (a * (n - 1) + x) / n
        out.append(a)
    return out


# -------------------------------------------------------------------- data
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
    """Aggregate M1 into M15 bars aligned to the 15-minute clock."""
    buckets = {}
    for ts, h, l, c in m1:
        slot = ts - (ts % (BAR_MIN * 60 * 1000))
        if slot in buckets:
            b = buckets[slot]
            buckets[slot] = (b[0], max(b[1], h), min(b[2], l), c)
        else:
            buckets[slot] = (slot, h, l, c)
    return [buckets[k] for k in sorted(buckets)]


# ------------------------------------------------------------------ ticket
def levels(pair, side, price, atr):
    pip = pip_of(pair)
    sl_dist = max(1.5 * atr, SCALP_MIN_SL_PIPS * pip)
    tp_dist = sl_dist * SCALP_RR
    if side == "BUY":
        return price - sl_dist, price + tp_dist
    return price + sl_dist, price - tp_dist


def resolve(bars, i, pair, side, sl, tp):
    """Resolve from bar i+1 forward. Ambiguous bar = loss. Spread deducted."""
    pip = pip_of(pair)
    spread = SPREAD[pair]
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


# ------------------------------------------------- current rule (EMA/RSI)
def rule_side(closes, e20, e50, rsi, i):
    """Mirror of engine/signal-engine.py build_setup()."""
    c = closes[i]
    bull = c > e50[i] and e20[i] > e50[i]
    bear = c < e50[i] and e20[i] < e50[i]
    cross_up = rsi[i - 1] < 55.0 <= rsi[i] and rsi[i] < 72.0
    cross_dn = rsi[i - 1] > 45.0 >= rsi[i] and rsi[i] > 28.0
    if bull and cross_up:
        return "BUY"
    if bear and cross_dn:
        return "SELL"
    if bull and rsi[i - 1] < 45.0 <= rsi[i]:
        return "BUY"
    if bear and rsi[i - 1] > 55.0 >= rsi[i]:
        return "SELL"
    if bull and 46.0 <= rsi[i] <= 68.0:
        return "BUY"
    if bear and 32.0 <= rsi[i] <= 54.0:
        return "SELL"
    return None


# ------------------------------------------------------------- fully AI
def sigmoid(z):
    if z > 30:
        return 1.0
    if z < -30:
        return 0.0
    return 1 / (1 + math.exp(-z))


def fit(rows, key, epochs=250, lr=0.06, l2=0.02):
    n = len(rows[0]["f"])
    mu, sd = [0.0] * n, [1.0] * n
    for j in range(n):
        vals = [r["f"][j] for r in rows]
        m = sum(vals) / len(vals)
        s = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        mu[j], sd[j] = m, s
    Z = [[(r["f"][j] - mu[j]) / sd[j] for j in range(n)] for r in rows]
    w = [0.0] * (n + 1)
    N = len(rows)
    for _ in range(epochs):
        g = [0.0] * (n + 1)
        for r, z in zip(rows, Z):
            p = sigmoid(w[0] + sum(w[j + 1] * z[j] for j in range(n)))
            d = p - r[key]
            g[0] += d
            for j in range(n):
                g[j + 1] += d * z[j]
        w[0] -= lr * g[0] / N
        for j in range(1, n + 1):
            w[j] -= lr * (g[j] / N + l2 * w[j])
    return w, mu, sd


def predict(w, mu, sd, f):
    z = [(f[j] - mu[j]) / sd[j] for j in range(len(f))]
    return sigmoid(w[0] + sum(w[j + 1] * z[j] for j in range(len(z))))


def features(pair, bars, e20, e50, rsi, atr, i):
    pip = pip_of(pair)
    a = atr[i]
    if a <= 0:
        return None
    hour = datetime.fromtimestamp(bars[i][0] / 1000, tz=timezone.utc).hour
    return [
        (e20[i] - e50[i]) / a,
        (bars[i][3] - e20[i]) / a,
        (rsi[i] - 50) / 25,
        (rsi[i] - rsi[i - 1]) / 5,
        a / pip / 100,
        1.0 if 7 <= hour < 16 else 0.0,
        1.0 if 12 <= hour < 21 else 0.0,
        1.0,
    ]


# ------------------------------------------------------------------- stats
def bootstrap_ci(vals, iters=10000, seed=7):
    if len(vals) < 5:
        return (None, None)
    rnd = random.Random(seed)
    means = []
    n = len(vals)
    for _ in range(iters):
        s = sum(vals[rnd.randrange(n)] for _ in range(n)) / n
        means.append(s)
    means.sort()
    return (round(means[int(0.025 * iters)], 2), round(means[int(0.975 * iters)], 2))


def summarize(trades):
    n = len(trades)
    if not n:
        return {"n": 0, "wins": 0, "wr": 0.0, "pips": 0.0, "avg": 0.0,
                "ci": (None, None)}
    wins = sum(1 for t in trades if t["pips"] > 0)
    total = sum(t["pips"] for t in trades)
    lo, hi = bootstrap_ci([t["pips"] for t in trades])
    return {"n": n, "wins": wins, "wr": round(100 * wins / n, 1),
            "pips": round(total, 2), "avg": round(total / n, 2), "ci": (lo, hi)}


# -------------------------------------------------------------------- runs
def run_rule(pair, bars):
    closes = [b[3] for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    rsi = rsi_s(closes)
    atr = atr_s(bars)
    trades = []
    lock_until = -1
    for i in range(60, len(bars) - 1):
        if i <= lock_until:
            continue
        side = rule_side(closes, e20, e50, rsi, i)
        if not side:
            continue
        sl, tp = levels(pair, side, closes[i], atr[i])
        pnl = resolve(bars, i, pair, side, sl, tp)
        trades.append({"pair": pair, "side": side, "pips": round(pnl, 2)})
        lock_until = i + MAX_HOLD_BARS
    return trades


def run_ai(pair, bars):
    closes = [b[3] for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    rsi = rsi_s(closes)
    atr = atr_s(bars)
    rows = []
    for i in range(60, len(bars) - 1):
        f = features(pair, bars, e20, e50, rsi, atr, i)
        if f is None:
            continue
        sl_b, tp_b = levels(pair, "BUY", closes[i], atr[i])
        sl_s, tp_s = levels(pair, "SELL", closes[i], atr[i])
        pl = resolve(bars, i, pair, "BUY", sl_b, tp_b)
        ps = resolve(bars, i, pair, "SELL", sl_s, tp_s)
        rows.append({"i": i, "ts": bars[i][0], "f": f,
                     "y_long": 1 if pl > 0 else 0,
                     "y_short": 1 if ps > 0 else 0,
                     "pnl_long": pl, "pnl_short": ps})
    if len(rows) < 200:
        return []

    train_ms = TRAIN_HOURS * 3600 * 1000
    test_ms = TEST_HOURS * 3600 * 1000
    t0, t1 = rows[0]["ts"], rows[-1]["ts"]
    start = t0 + train_ms
    trades = []
    while start + test_ms <= t1:
        tr = [r for r in rows if start - train_ms <= r["ts"] < start]
        te = [r for r in rows if start <= r["ts"] < start + test_ms]
        if len(tr) >= 100 and te:
            wL, mL, sL = fit(tr, "y_long")
            wS, mS, sS = fit(tr, "y_short")
            lock = -1
            for r in te:
                if r["i"] <= lock:
                    continue
                pl = predict(wL, mL, sL, r["f"])
                ps = predict(wS, mS, sS, r["f"])
                side = "BUY" if pl >= ps else "SELL"
                conf = max(pl, ps)
                if conf < THRESHOLD:
                    continue
                pnl = r["pnl_long"] if side == "BUY" else r["pnl_short"]
                trades.append({"pair": pair, "side": side, "pips": round(pnl, 2),
                               "conf": round(conf, 3)})
                lock = r["i"] + MAX_HOLD_BARS
        start += test_ms
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write full results to this path")
    args = ap.parse_args()

    rule_all, ai_all = [], []
    per_pair = []

    for pair in PAIRS:
        m1 = load_m1(pair)
        if not m1:
            print(f"{pair}: no cached M1")
            continue
        bars = to_m15(m1)
        days = (bars[-1][0] - bars[0][0]) / 86400000
        rt = run_rule(pair, bars)
        at = run_ai(pair, bars)
        rule_all += rt
        ai_all += at
        rs, as_ = summarize(rt), summarize(at)
        per_pair.append({"pair": pair, "days": round(days, 1),
                         "bars": len(bars), "rule": rs, "ai": as_})
        print(f"{pair:9} {days:5.1f}d bars={len(bars):5} | "
              f"RULE n={rs['n']:3} WR={rs['wr']:5.1f}% {rs['pips']:+8.1f}p | "
              f"AI n={as_['n']:3} WR={as_['wr']:5.1f}% {as_['pips']:+8.1f}p")

    rs, as_ = summarize(rule_all), summarize(ai_all)
    print("\n=== M15 HEAD-TO-HEAD (identical ticket) ===")
    print(f"{'':16}{'n':>5}{'wins':>7}{'WR':>8}{'pips':>10}{'avg':>8}   CI95 avg")
    for name, s in (("CURRENT RULE", rs), ("FULLY AI", as_)):
        ci = f"[{s['ci'][0]}, {s['ci'][1]}]" if s["ci"][0] is not None else "-"
        print(f"{name:16}{s['n']:>5}{s['wins']:>7}{s['wr']:>7.1f}%"
              f"{s['pips']:>10.1f}{s['avg']:>8.2f}   {ci}")

    if rs["n"] and as_["n"]:
        diff = as_["wr"] - rs["wr"]
        print(f"\nWin-rate gap (AI - rule): {diff:+.1f} points")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"per_pair": per_pair, "rule": rs, "ai": as_,
             "ticket": {"sl": f"max(1.5*ATR, {SCALP_MIN_SL_PIPS}p)",
                        "tp": f"{SCALP_RR}x SL", "max_hold_bars": MAX_HOLD_BARS,
                        "threshold": THRESHOLD}}, indent=1))
        print(f"saved {args.json}")


if __name__ == "__main__":
    main()
