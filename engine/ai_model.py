#!/usr/bin/env python3
"""Shared M15 feature + logistic-model code for the TraderWatch AI engine.

Kept separate from the research script so training and live inference use
exactly the same feature definitions. Any change here changes both sides.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001
BAR_MIN = 15
FEATURE_VERSION = 1


def pip_of(pair):
    return PIP.get(pair, DEFAULT_PIP)


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


def feature_row(pair, bars, e20, e50, rsi, atr, i):
    """Feature vector at bar i. Must stay in sync with train-ai-model.py."""
    a = atr[i]
    if a <= 0:
        return None
    hour = datetime.fromtimestamp(bars[i][0] / 1000, tz=timezone.utc).hour
    return [
        (e20[i] - e50[i]) / a,
        (bars[i][3] - e20[i]) / a,
        (rsi[i] - 50) / 25,
        (rsi[i] - rsi[i - 1]) / 5,
        a / pip_of(pair) / 100,
        1.0 if 7 <= hour < 16 else 0.0,
        1.0 if 12 <= hour < 21 else 0.0,
        1.0,
    ]


def sigmoid(z):
    if z > 30:
        return 1.0
    if z < -30:
        return 0.0
    return 1 / (1 + math.exp(-z))


# ---- FEATURE VERSION 2 (SMC / session-aware, additive) --------------------
# v1 feature_row() above is frozen. v2 keeps v1 dims 0-4 + bias, REPLACES the
# two UTC session flags with a 3-way KL (MYT) one-hot, and adds:
#   H1 trend alignment | POI-proxy distance | KL one-hot x3 | R-mean20 | ATR%
# Total v2 length = 13. feature_row_v2 returns None when bar history is
# insufficient (fail closed). The R-form feature falls back to 0.0 (neutral
# prior) when no closed trades precede the bar -- returning None there would
# erase nearly all training rows because the closed-trade record starts later
# than the M1 caches.
FEATURE_VERSION_V2 = 2
V2_MIN_H1_BARS = 50      # H1 EMA50 needs ~50 H1 bars before the gap is stable
V2_ATR_LOOKBACK = 100    # ATR percentile window
V2_POI_LOOKBACK = 20     # M15 swing scan window
V2_R_WINDOW = 20         # trailing closed trades per pair
V2_R_CLIP = 2.0
# KL (UTC+8) sessions, hours in MYT: Asia 00-07, London 08-15, NY 16-23.
KL_SESSIONS = (("asia", 0, 8), ("london", 8, 16), ("ny", 16, 24))

V2_FEATURE_NAMES = [
    "ema_gap_atr", "dist_ema20_atr", "rsi_norm", "rsi_slope", "atr_pips",
    "h1_trend_sign", "poi_dist_atr",
    "kl_asia", "kl_london", "kl_ny",
    "rmean20", "atr_pctile", "bias",
]


def pair_code(pair):
    return "".join(ch for ch in str(pair).upper() if ch.isalpha())


def build_v2_ctx(pair, m1_bars, status_path=None):
    """Precompute v2 side inputs: H1 EMA pair + per-pair closed-trade R list.

    m1_bars: sorted (ts_ms, high, low, close) M1 tuples.
    status_path: signal-status.json path (may be None -> R prior always 0.0).
    """
    from bisect import bisect_right  # local import: keeps module import-light

    # H1 bars aggregated from M1 (60-min slots), closes only for EMAs.
    buckets = {}
    for ts, h, l, c in m1_bars:
        slot = ts - (ts % 3600000)
        if slot in buckets:
            b = buckets[slot]
            buckets[slot] = (b[0], max(b[1], h), min(b[2], l), c)
        else:
            buckets[slot] = (slot, h, l, c)
    h1 = [buckets[k] for k in sorted(buckets)]
    h_ts = [b[0] for b in h1]
    h_close = [b[3] for b in h1]
    h_e20 = ema(h_close, 20) if h_close else []
    h_e50 = ema(h_close, 50) if h_close else []

    # Closed-trade R events for this pair, sorted by entry time.
    code = pair_code(pair)
    r_events = []
    if status_path is not None:
        try:
            sigs = json.loads(Path(status_path).read_text()).get("signals") or {}
        except Exception:
            sigs = {}
        for key, info in sigs.items():
            if not isinstance(info, dict):
                continue
            if str(key).split("_", 1)[0].upper() != code:
                continue
            r = info.get("r")
            if not isinstance(r, (int, float)):
                continue
            ea = info.get("entry_at") or info.get("closed")
            try:
                d = datetime.fromisoformat(str(ea).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            r_events.append((int(d.timestamp() * 1000), float(r)))
    r_events.sort(key=lambda x: x[0])
    return {"h_ts": h_ts, "h_e20": h_e20, "h_e50": h_e50,
            "r_ts": [t for t, _ in r_events],
            "r_vals": [r for _, r in r_events]}


def feature_row_v2(pair, bars, e20, e50, rsi, atr, i, ctx):
    """13-dim v2 feature vector at M15 bar i, or None on short history."""
    from bisect import bisect_right

    if i < 60:
        return None
    a = atr[i]
    if a <= 0:
        return None

    # H1 trend alignment: sign of the H1 EMA20/50 gap at this timestamp.
    h_ts = ctx.get("h_ts") or []
    hi = bisect_right(h_ts, bars[i][0]) - 1
    if hi < V2_MIN_H1_BARS or hi >= len(ctx.get("h_e20") or []):
        return None
    gap = ctx["h_e20"][hi] - ctx["h_e50"][hi]
    h1_sign = 1.0 if gap > 0 else (-1.0 if gap < 0 else 0.0)

    # ATR percentile rank vs trailing 100 bars.
    if i + 1 < V2_ATR_LOOKBACK:
        return None
    win = atr[i + 1 - V2_ATR_LOOKBACK:i + 1]
    atr_pct = sum(1 for x in win if x <= a) / float(len(win))

    # POI proxy: signed distance (in ATR) to the nearest unmitigated recent
    # M15 swing high/low. Swing = strict local extreme over +-2 bars inside
    # the trailing window; unmitigated = no later close through the level.
    if i < V2_POI_LOOKBACK + 2:
        return None
    start = i - V2_POI_LOOKBACK
    swings = []
    for k in range(start + 2, i):
        hk, lk = bars[k][1], bars[k][2]
        if all(hk > bars[m][1] for m in (k - 2, k - 1, k + 1, k + 2)):
            swings.append((k, hk, "high"))
        elif all(lk < bars[m][2] for m in (k - 2, k - 1, k + 1, k + 2)):
            swings.append((k, lk, "low"))
    if not swings:
        return None
    close = bars[i][3]
    unmit = []
    for k, lvl, kind in swings:
        later = [bars[m][3] for m in range(k + 1, i + 1)]
        if kind == "high" and any(c > lvl for c in later):
            continue
        if kind == "low" and any(c < lvl for c in later):
            continue
        unmit.append(lvl)
    pool = unmit or [lvl for _, lvl, _ in swings]
    level = min(pool, key=lambda L: abs(close - L))
    poi_dist = (close - level) / a

    # KL (MYT) session one-hot, replacing the v1 UTC flags.
    kl_hour = (datetime.fromtimestamp(
        bars[i][0] / 1000, tz=timezone.utc).hour + 8) % 24
    sess = [0.0, 0.0, 0.0]
    for s, (name, lo, hi_) in enumerate(KL_SESSIONS):
        if lo <= kl_hour < hi_:
            sess[s] = 1.0
            break

    # Prior-20-trade R-multiple rolling mean (neutral 0.0 when no history).
    r_ts, r_vals = ctx.get("r_ts") or [], ctx.get("r_vals") or []
    pos = bisect_right(r_ts, bars[i][0])
    recent = r_vals[max(0, pos - V2_R_WINDOW):pos]
    rmean = sum(recent) / len(recent) if recent else 0.0
    rmean = max(-V2_R_CLIP, min(V2_R_CLIP, rmean))

    return [
        (e20[i] - e50[i]) / a,
        (close - e20[i]) / a,
        (rsi[i] - 50) / 25,
        (rsi[i] - rsi[i - 1]) / 5,
        a / pip_of(pair) / 100,
        h1_sign,
        poi_dist,
        sess[0], sess[1], sess[2],
        rmean,
        atr_pct,
        1.0,
    ]


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


def predict(model, f):
    w, mu, sd = model["w"], model["mu"], model["sd"]
    z = [(f[j] - mu[j]) / sd[j] for j in range(len(f))]
    return sigmoid(w[0] + sum(w[j + 1] * z[j] for j in range(len(z))))


def save_model(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=1))


def load_model(path):
    return json.loads(Path(path).read_text())
