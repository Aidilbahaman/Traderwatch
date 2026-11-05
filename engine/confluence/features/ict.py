"""Feature: ICT / SMC setup evidence (spec §1.4 group C).

Menggunakan semula detector yang sudah diuji dalam `engine/ict_features.py`
(jangan tulis semula — ia lulus held-out). Modul ini MEMBUNGKUS outputnya
jadi bentuk group-score yang spec mahu.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

# Muat modul ict_features sedia ada (nama ada sengkang? tidak — guna terus)
_spec = importlib.util.spec_from_file_location(
    "ict_features",
    str(Path(__file__).resolve().parent.parent.parent / "ict_features.py"))
_ict = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ict)


def to_tuple_bars(bars):
    """Tukar format dict -> format ict_features: (ts_ms, high, low, close)."""
    return [(int(b["open_time"].timestamp() * 1000), b["high"], b["low"], b["close"])
            for b in bars]


def ict_group(bars, i, atr):
    """Kumpulan ICT/SMC: FVG, OB, sweep, displacement, premium/discount."""
    tb = to_tuple_bars(bars)
    try:
        # ict_features pulangkan (list[float], detail_dict) — bukan senarai rata
        feats, detail = _ict.ict_features(tb, i, atr)
    except Exception as ex:
        return {"score": 0.0, "direction": "UNAVAILABLE", "coverage": 0.0,
                "quality": 0.0, "evidence": [], "reason_codes": ["ICT_FAIL"],
                "raw": {"error": type(ex).__name__}}
    if feats is None:
        return {"score": 0.0, "direction": "UNAVAILABLE", "coverage": 0.0,
                "quality": 0.0, "evidence": [], "reason_codes": ["ICT_HISTORY_SHORT"],
                "raw": {}}

    names = _ict.ICT_FEATURE_NAMES
    f = dict(zip(names, feats))
    f.update(detail or {})
    ev, score, codes = [], 0.0, []

    # FVG berdekatan
    if f.get("fvg_bull_near"):
        score += 0.2; codes.append("FVG_BULL"); ev.append({"type": "FVG", "side": "BULL"})
    if f.get("fvg_bear_near"):
        score -= 0.2; codes.append("FVG_BEAR"); ev.append({"type": "FVG", "side": "BEAR"})
    # Order block
    if f.get("ob_bull_atr") is not None and abs(f.get("ob_bull_atr") or 99) < 1.0:
        score += 0.15; codes.append("OB_BULL")
    if f.get("ob_bear_atr") is not None and abs(f.get("ob_bear_atr") or 99) < 1.0:
        score -= 0.15; codes.append("OB_BEAR")
    # Sweep
    if f.get("sweep_bull"):
        score += 0.3; codes.append("SWEEP_BULL")
    if f.get("sweep_bear"):
        score -= 0.3; codes.append("SWEEP_BEAR")
    # Displacement: nilai bertanda (positif = naik)
    disp = f.get("displacement")
    if isinstance(disp, (int, float)) and abs(disp) > 0.6:
        codes.append("DISP_UP" if disp > 0 else "DISP_DN")
        score += 0.15 if disp > 0 else -0.15
        ev.append({"type": "DISPLACEMENT", "value": round(disp, 4)})

    pd = f.get("premium_disc")
    if pd is not None:
        ev.append({"type": "PREMIUM_DISCOUNT", "value": round(pd, 4)})
        # ICT: beli di discount, jual di premium
        score += (0.5 - pd) * 0.25

    score = max(-1.0, min(1.0, score))
    direction = ("BULLISH" if score > 0.15
                 else ("BEARISH" if score < -0.15 else "NEUTRAL"))
    return {"score": round(score, 4), "direction": direction,
            "coverage": 1.0, "quality": 1.0, "evidence": ev,
            "reason_codes": codes,
            "raw": {k: (round(v, 6) if isinstance(v, float) else v)
                    for k, v in f.items()}}
