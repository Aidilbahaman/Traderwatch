"""Fasa 3 — Regime classification (spec §3.1 langkah 3).

Deterministik dahulu (ADX, volatility percentile, structure). Tiada ML di sini.
Regime: TRENDING · RANGING · VOLATILE · NEWS_DRIVEN · UNCERTAIN
"""
from __future__ import annotations


def volatility_percentile(bars, i, window=200):
    """Kedudukan ATR semasa dalam taburan ATR sejarah → 0..1."""
    from .features import quant as qt
    if i < window:
        return None
    vals = []
    for k in range(i - window, i + 1):
        vals.append(qt.atr(bars, k, 14))
    cur = vals[-1]
    if not vals or cur <= 0:
        return None
    below = sum(1 for v in vals if v <= cur)
    return round(below / len(vals), 4)


def classify(bars, i, atr, mtf_result=None, quant_result=None, news_block=False):
    """Klasifikasi regime pada bar i.

    Pulangkan dict: {regime, confidence, evidence, reason_codes}
    """
    from .features import quant as qt
    ev, codes = [], []

    if news_block:
        return {"regime": "NEWS_DRIVEN", "confidence": 0.9,
                "evidence": [{"type": "NEWS_BLOCK"}], "reason_codes": ["NEWS_WINDOW"]}

    q = quant_result or qt.quant_features(bars, i)
    adx = (q["raw"].get("adx") or {}).get("adx")
    volp = volatility_percentile(bars, i)
    ev.append({"type": "ADX", "value": adx})
    ev.append({"type": "VOL_PERCENTILE", "value": volp})

    # Volatiliti melampau -> VOLATILE
    if volp is not None and volp >= 0.95:
        codes.append("VOL_EXTREME")
        return {"regime": "VOLATILE", "confidence": round(volp, 3),
                "evidence": ev, "reason_codes": codes,
                "metrics": {"adx": adx, "vol_pct": volp}}

    # Trend kuat
    if adx is not None and adx >= 25:
        codes.append("ADX_STRONG")
        conf = min(1.0, adx / 50)
        # Sahkan dengan struktur MTF bila ada
        if mtf_result and not mtf_result["raw"].get("conflict"):
            codes.append("MTF_ALIGNED")
            conf = min(1.0, conf + 0.15)
        return {"regime": "TRENDING", "confidence": round(conf, 3),
                "evidence": ev, "reason_codes": codes,
                "metrics": {"adx": adx, "vol_pct": volp}}

    # Range
    if adx is not None and adx < 20:
        codes.append("ADX_WEAK")
        if mtf_result and mtf_result["direction"] == "NEUTRAL":
            codes.append("MTF_RANGE")
        return {"regime": "RANGING", "confidence": round(1 - adx / 25, 3),
                "evidence": ev, "reason_codes": codes,
                "metrics": {"adx": adx, "vol_pct": volp}}

    # Zon kelabu (20-25 ADX) atau data kurang
    codes.append("REGIME_UNCERTAIN")
    return {"regime": "UNCERTAIN", "confidence": 0.4,
            "evidence": ev, "reason_codes": codes,
            "metrics": {"adx": adx, "vol_pct": volp}}
