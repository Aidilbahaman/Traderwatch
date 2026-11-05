"""Feature: market structure & price action (spec §1.4 group A).

Semua pengiraan CAUSAL — pivot hanya sah selepas bar konfirmasi tutup.
Format bar: dict {"open_time", "open", "high", "low", "close", "tick_volume"}.
"""
from __future__ import annotations


def swings(bars, i, lookback=3, max_age=200):
    """Swing high/low CONFIRMED pada atau sebelum bar i.

    Pivot di bar k sah hanya bila `lookback` bar di KEDUA-DUA sisi sudah tutup
    (k+lookback <= i). Ini menutup lookahead — spec §2.4.
    """
    out = []
    start = max(lookback, i - max_age)
    end = i - lookback          # pivot mesti ada lookback bar selepasnya
    for k in range(start, end + 1):
        w = range(k - lookback, k + lookback + 1)
        hs = [bars[j]["high"] for j in w]
        ls = [bars[j]["low"] for j in w]
        if bars[k]["high"] == max(hs):
            out.append({"idx": k, "price": bars[k]["high"], "kind": "H",
                        "confirmed_at": k + lookback})
        if bars[k]["low"] == min(ls):
            out.append({"idx": k, "price": bars[k]["low"], "kind": "L",
                        "confirmed_at": k + lookback})
    # Buang pivot berturutan jenis sama, kekal ekstrem
    clean = []
    for p in out:
        if clean and clean[-1]["kind"] == p["kind"]:
            if (p["kind"] == "H" and p["price"] > clean[-1]["price"]) or \
               (p["kind"] == "L" and p["price"] < clean[-1]["price"]):
                clean[-1] = p
        else:
            clean.append(p)
    return clean


def trend_from_swings(pivots, n=4):
    """HH/HL vs LH/LL dari n pivot terakhir. Return (+1/-1/0, label)."""
    if len(pivots) < 4:
        return 0, "DATA_KURANG"
    recent = pivots[-n:]
    highs = [p["price"] for p in recent if p["kind"] == "H"]
    lows = [p["price"] for p in recent if p["kind"] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return 0, "DATA_KURANG"
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]
    if hh and hl:
        return 1, "HH_HL"
    if lh and ll:
        return -1, "LH_LL"
    return 0, "RANGE"


def bos(pivots, close, buffer_atr=0.0, atr=None):
    """Break of Structure: close melebihi swing terakhir.

    Return dict atau None. Buffer dalam ATR mengelak false break.
    """
    if not pivots:
        return None
    buf = (buffer_atr * atr) if (atr and buffer_atr) else 0.0
    last_h = next((p for p in reversed(pivots) if p["kind"] == "H"), None)
    last_l = next((p for p in reversed(pivots) if p["kind"] == "L"), None)
    if last_h and close > last_h["price"] + buf:
        return {"direction": "BULLISH", "level": last_h["price"],
                "confirmed_at": last_h["confirmed_at"]}
    if last_l and close < last_l["price"] - buf:
        return {"direction": "BEARISH", "level": last_l["price"],
                "confirmed_at": last_l["confirmed_at"]}
    return None


def dealing_range(pivots, n=6):
    """Julat dealing = swing high tertinggi & low terendah dari n pivot."""
    if len(pivots) < 2:
        return None
    recent = pivots[-n:]
    his = [p["price"] for p in recent if p["kind"] == "H"]
    los = [p["price"] for p in recent if p["kind"] == "L"]
    if not his or not los:
        return None
    return {"high": max(his), "low": min(los)}


def premium_discount(price, rng):
    """0.0 = discount penuh (range low), 1.0 = premium penuh (range high)."""
    if not rng or rng["high"] <= rng["low"]:
        return None
    return round((price - rng["low"]) / (rng["high"] - rng["low"]), 4)


def structure_features(bars, i, atr=None):
    """Kumpulan feature struktur untuk bar i. Skor -1..+1."""
    piv = swings(bars, i)
    close = bars[i]["close"]
    tr, tr_label = trend_from_swings(piv)
    rng = dealing_range(piv)
    pd = premium_discount(close, rng)
    b = bos(piv, close, buffer_atr=0.1 if atr else 0.0, atr=atr)

    # Skor struktur: trend + BOS + premium/discount
    score = tr * 0.6
    if b:
        score += 0.25 if b["direction"] == "BULLISH" else -0.25
    if pd is not None:
        # Discount (rendah) = peluang beli; premium (tinggi) = peluang jual
        score += (0.5 - pd) * 0.3
    score = max(-1.0, min(1.0, score))
    direction = "BULLISH" if score > 0.15 else ("BEARISH" if score < -0.15 else "NEUTRAL")

    ev = []
    if tr:
        ev.append({"type": "TREND", "label": tr_label, "value": tr})
    if b:
        ev.append({"type": "BOS", "direction": b["direction"], "level": b["level"]})
    if pd is not None:
        ev.append({"type": "PREMIUM_DISCOUNT", "value": pd,
                   "zone": "PREMIUM" if pd > 0.5 else "DISCOUNT"})
    return {"score": round(score, 4), "direction": direction,
            "coverage": 1.0 if piv else 0.0, "quality": 1.0,
            "evidence": ev, "reason_codes": [tr_label] + (["BOS"] if b else []),
            "raw": {"swings": piv[-6:], "range": rng, "premium_discount": pd}}
