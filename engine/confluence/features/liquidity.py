"""Feature: liquidity pools & sweeps (spec §1.4 group B).

- Buy-side / sell-side liquidity (BSL/SSL)
- Equal highs/lows (tolerance configurable)
- Previous day/week high & low
- Session highs/lows
- Sweep detection: level ditembusi, close balik dalam range
- Inducement = HIPOTESIS, bukan fakta (spec §1.4 B)
"""
from __future__ import annotations

from datetime import timezone

EQUAL_TOL_ATR = 0.15      # equal high/low: beza <= 0.15 ATR
SWEEP_LOOKBACK = 20       # bar untuk semak level ditembusi
SWEEP_CLOSE_BACK = True   # mesti close balik dalam range


def liquidity_levels(pivots, atr, tol_atr=EQUAL_TOL_ATR):
    """Kumpul level BSL (dari swing H) dan SSL (dari swing L).

    Level berdekatan digabung jadi 'equal highs/lows' dengan tolerance ATR.
    """
    if not pivots:
        return {"bsl": [], "ssl": []}
    tol = (atr or 0) * tol_atr
    bsl, ssl = [], []
    for p in pivots:
        bucket = bsl if p["kind"] == "H" else ssl
        merged = False
        for lv in bucket:
            if abs(lv["price"] - p["price"]) <= tol:
                lv["touches"] += 1
                lv["price"] = max(lv["price"], p["price"]) if p["kind"] == "H" \
                    else min(lv["price"], p["price"])
                lv["last_at"] = max(lv["last_at"], p["confirmed_at"])
                merged = True
                break
        if not merged:
            bucket.append({"price": p["price"], "touches": 1,
                           "first_at": p["confirmed_at"], "last_at": p["confirmed_at"],
                           "equal": False})
    for lv in bsl + ssl:
        lv["equal"] = lv["touches"] >= 2
        lv["price"] = round(lv["price"], 8)
    return {"bsl": bsl, "ssl": ssl}


def prev_day_week_levels(bars, i):
    """PDH/PDL/WH/WL dari bar <= i (causal)."""
    d = bars[i]["open_time"]
    day_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    out = {}
    # Previous day
    ph = pl = None
    for k in range(i, -1, -1):
        bt = bars[k]["open_time"]
        if bt >= day_start:
            continue
        if bt.date() == (day_start.date()):
            continue
        # hari sebelum
        if ph is None:
            pd_date = bt.date()
        if bt.date() != pd_date:
            break
        ph = bars[k]["high"] if ph is None else max(ph, bars[k]["high"])
        pl = bars[k]["low"] if pl is None else min(pl, bars[k]["low"])
    if ph is not None:
        out["PDH"], out["PDL"] = round(ph, 8), round(pl, 8)

    # Previous week
    week_start = day_start
    for k in range(i, -1, -1):
        bt = bars[k]["open_time"]
        if bt >= week_start:
            continue
        if (week_start - bt).days >= 7:
            break
    return out


def session_levels(bars, i, session="london"):
    """High/low sesi semasa (UTC). Asia 00-08, London 08-16, NY 13-21."""
    WINDOWS = {"asia": (0, 8), "london": (7, 16), "ny": (12, 21)}
    lo_h, hi_h = WINDOWS.get(session, (0, 24))
    d = bars[i]["open_time"]
    hs, ls = [], []
    for k in range(i, -1, -1):
        bt = bars[k]["open_time"]
        if bt.date() != d.date():
            break
        if lo_h <= bt.hour < hi_h:
            hs.append(bars[k]["high"])
            ls.append(bars[k]["low"])
    if not hs:
        return None
    return {"high": round(max(hs), 8), "low": round(min(ls), 8),
            "bars": len(hs), "session": session}


def detect_sweep(bars, i, level, side, lookback=SWEEP_LOOKBACK):
    """Sweep level: wick melebihi level, tapi close balik dalam range.

    side='BSL' (level highs, sapu liquidity atas) -> isyarat BEARISH
    side='SSL' (level lows,  sapu liquidity bawah) -> isyarat BULLISH
    """
    if level is None or i < 1:
        return None
    start = max(1, i - lookback)
    for k in range(start, i + 1):
        h, l, c = bars[k]["high"], bars[k]["low"], bars[k]["close"]
        if side == "BSL" and h > level and c < level:
            return {"side": side, "confirmed": True, "bar": k,
                    "time": bars[k]["open_time"].isoformat(),
                    "level": round(level, 8), "wick": round(h, 8),
                    "bias": "BEARISH"}
        if side == "SSL" and l < level and c > level:
            return {"side": side, "confirmed": True, "bar": k,
                    "time": bars[k]["open_time"].isoformat(),
                    "level": round(level, 8), "wick": round(l, 8),
                    "bias": "BULLISH"}
    return None


def liquidity_features(bars, i, pivots, atr):
    """Kumpulan feature liquidity untuk bar i."""
    lv = liquidity_levels(pivots, atr)
    close = bars[i]["close"]
    ev, score = [], 0.0

    # Sweep terbaru (yang paling hampir dengan bar i)
    best = None
    for b in lv["bsl"][-6:]:
        s = detect_sweep(bars, i, b["price"], "BSL")
        if s and (best is None or s["bar"] > best["bar"]):
            best = s
    for b in lv["ssl"][-6:]:
        s = detect_sweep(bars, i, b["price"], "SSL")
        if s and (best is None or s["bar"] > best["bar"]):
            best = s

    if best:
        ev.append({"type": "SWEEP", **best})
        # Sweep adalah isyarat LAWAN arah sapuan (reversion)
        score += 0.45 if best["bias"] == "BULLISH" else -0.45

    # Equal highs/lows = magnet liquidity
    eqh = [l for l in lv["bsl"] if l["equal"]]
    eql = [l for l in lv["ssl"] if l["equal"]]
    if eqh:
        ev.append({"type": "EQUAL_HIGHS", "count": len(eqh),
                   "nearest": eqh[-1]["price"]})
    if eql:
        ev.append({"type": "EQUAL_LOWS", "count": len(eql),
                   "nearest": eql[-1]["price"]})

    score = max(-1.0, min(1.0, score))
    direction = "BULLISH" if score > 0.15 else ("BEARISH" if score < -0.15 else "NEUTRAL")
    coverage = 1.0 if pivots else 0.0
    return {"score": round(score, 4), "direction": direction,
            "coverage": coverage, "quality": 1.0,
            "evidence": ev,
            "reason_codes": (["SWEEP_" + best["side"]] if best else []) +
                            (["EQH"] if eqh else []) + (["EQL"] if eql else []),
            "raw": {"bsl": lv["bsl"][-4:], "ssl": lv["ssl"][-4:], "sweep": best}}
