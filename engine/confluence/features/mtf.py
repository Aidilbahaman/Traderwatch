"""Feature: multi-timeframe alignment (spec §1.4 group D) + session (§1.4 I).

Hierarchy: HTF bias (H4/D1) -> setup (H1/M15) -> trigger (M5).
Kita TIDAK memerlukan semua timeframe setuju (spec §1.4 D) — ada hierarki
dan polisi konflik eksplisit.
"""
from __future__ import annotations

from datetime import timezone

# Method: 'nearest' bila timeframe diminta tidak dikumpul terus
TF_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

# Sesi (UTC) — spec §1.4 I
SESSIONS = {
    "asia": (0, 8),
    "london": (7, 16),
    "newyork": (12, 21),
    "overlap_london_ny": (12, 16),
}


def resample(bars, factor):
    """Gabung bar jadi timeframe lebih tinggi (causal, tiada lookahead).

    factor: berapa bar asal untuk satu bar baharu (M15->H1 = 4).
    """
    if factor <= 1:
        return bars
    out = []
    for k in range(0, len(bars) - factor + 1, factor):
        chunk = bars[k:k + factor]
        out.append({
            "open_time": chunk[0]["open_time"],
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
            "tick_volume": sum(b["tick_volume"] for b in chunk),
        })
    return out


def session_of(dt):
    """Nama sesi untuk datetime UTC. Pulangkan list (boleh bertindih)."""
    h = dt.astimezone(timezone.utc).hour
    out = [name for name, (a, b) in SESSIONS.items() if a <= h < b]
    return out or ["off_hours"]


def mtf_bias(bars_by_tf):
    """Bias setiap timeframe dari EMA20 vs EMA50 + struktur ringkas.

    bars_by_tf: {"H4": [...], "H1": [...], "M15": [...]}
    Return skor sejajar -1..+1 dengan polisi konflik eksplisit.
    """
    from . import quant as qt

    bias = {}
    for tf, bars in bars_by_tf.items():
        if len(bars) < 60:
            bias[tf] = {"bias": "UNAVAILABLE", "score": 0.0}
            continue
        closes = [b["close"] for b in bars[-260:]]
        e20, e50 = qt.ema(closes, 20), qt.ema(closes, 50)
        if not e20 or not e50:
            bias[tf] = {"bias": "UNAVAILABLE", "score": 0.0}
            continue
        d = 1 if e20[-1] > e50[-1] else -1
        bias[tf] = {"bias": "BULLISH" if d > 0 else "BEARISH", "score": d * 0.5}

    # Hierarchy: HTF (H4/D1) > setup (H1/M15) > trigger (M5)
    W = {"D1": 0.35, "H4": 0.30, "H1": 0.20, "M15": 0.10, "M5": 0.05}
    num = den = 0.0
    for tf, b in bias.items():
        if b["bias"] == "UNAVAILABLE":
            continue
        w = W.get(tf, 0.05)
        num += w * b["score"]
        den += w
    score = round(num / den, 4) if den else 0.0

    # Konflik: HTF lawan LTF
    htf = bias.get("H4", bias.get("D1", {})).get("bias")
    ltf = bias.get("M15", bias.get("M5", {})).get("bias")
    conflict = bool(htf and ltf and htf != ltf and htf != "UNAVAILABLE")
    countertrend = conflict

    direction = "BULLISH" if score > 0.15 else ("BEARISH" if score < -0.15 else "NEUTRAL")
    codes = []
    if conflict:
        codes.append("MTF_CONFLICT")
    if countertrend:
        codes.append("COUNTERTREND")
    for tf, b in bias.items():
        if b["bias"] != "UNAVAILABLE":
            codes.append(f"{tf}_{'UP' if b['score'] > 0 else 'DN'}")

    cov = sum(1 for b in bias.values() if b["bias"] != "UNAVAILABLE") / max(1, len(bias))
    return {"score": score, "direction": direction,
            "coverage": round(cov, 3), "quality": 1.0,
            "evidence": [{"type": "MTF_BIAS", "by_tf": bias}],
            "reason_codes": codes,
            "raw": {"by_tf": bias, "htf_bias": htf, "ltf_bias": ltf,
                    "conflict": conflict, "countertrend": countertrend}}


def session_features(bars, i):
    """Feature sesi: nama, high/low sesi, hari, hujung bulan."""
    d = bars[i]["open_time"]
    sess = session_of(d)
    # High/low sesi semasa
    hs, ls = [], []
    for k in range(i, -1, -1):
        bt = bars[k]["open_time"]
        if bt.date() != d.date():
            break
        if session_of(bt)[0] == sess[0]:
            hs.append(bars[k]["high"])
            ls.append(bars[k]["low"])
    dow = d.weekday()  # 0=Mon
    is_month_end = d.day >= 25
    codes = [f"SESSION_{sess[0].upper()}" if sess else "SESSION_UNKNOWN"]
    if dow >= 5:
        codes.append("WEEKEND")
    if is_month_end:
        codes.append("MONTH_END")
    return {"score": 0.0, "direction": "NEUTRAL",
            "coverage": 1.0, "quality": 1.0,
            "evidence": [{"type": "SESSION", "name": sess,
                          "hour_utc": d.hour, "dow": dow}],
            "reason_codes": codes,
            "raw": {"session": sess, "hour_utc": d.hour,
                    "session_high": round(max(hs), 8) if hs else None,
                    "session_low": round(min(ls), 8) if ls else None,
                    "day_of_week": dow, "month_end": is_month_end}}
