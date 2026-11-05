"""Pipeline analysis — satukan semua fasa jadi satu panggilan (spec §3.1).

analyze(symbol, as_of_index) -> analysis run lengkap dengan BUY/SELL/WAIT/NO_TRADE.
Tiada penulisan DB di sini (Fasa 4). Tiada order broker (signal-only).
"""
from __future__ import annotations

from . import instruments as ins, market_data as md
from . import regime as rg, scoring as sc, decision as dc
from .features import structure as st, liquidity as lq, quant as qt, mtf as mt, ict as ic

STRATEGY_VERSION = "confluence-v1.0"
FEATURE_VERSION = "feat-v1.0"


def build_groups(bars, i, atr, pivots, by_tf):
    """Kira semua kumpulan feature untuk bar i."""
    return {
        "structure": st.structure_features(bars, i, atr),
        "liquidity": lq.liquidity_features(bars, i, pivots, atr),
        "ict": ic.ict_group(bars, i, atr),
        "quant": qt.quant_features(bars, i),
        "mtf": mt.mtf_bias(by_tf),
        "session": mt.session_features(bars, i),
        # Kumpulan tanpa sumber data sah — UNAVAILABLE, bukan neutral
        "volume": {"score": 0.0, "direction": "UNAVAILABLE", "coverage": 0.0,
                   "quality": 0.0, "evidence": [], "reason_codes": ["NO_VOLUME_SOURCE"],
                   "raw": {}},
        "macro": {"score": 0.0, "direction": "UNAVAILABLE", "coverage": 0.0,
                  "quality": 0.0, "evidence": [], "reason_codes": ["NO_MACRO_SOURCE"],
                  "raw": {}},
        "intermarket": {"score": 0.0, "direction": "UNAVAILABLE", "coverage": 0.0,
                        "quality": 0.0, "evidence": [], "reason_codes": ["NO_INTERMARKET_SOURCE"],
                        "raw": {}},
    }


def build_setup(groups, bars, i, atr, direction):
    """Setup dari bukti ICT + structure. Valid bila ada zon + nullification."""
    g_ict, g_st = groups["ict"], groups["structure"]
    if direction == "NEUTRAL":
        return {"valid": False, "side": None, "reason": "tiada arah"}
    side = "BUY" if direction == "BULLISH" else "SELL"
    close = bars[i]["close"]
    # Entry: guna zon terdekat dari evidence; SL di luar swing; TP 2R
    rng = g_st["raw"].get("range") or {}
    if side == "BUY":
        sl = rng.get("low", close - atr * 2) - atr * 0.25
        risk = max(close - sl, atr * 0.5)
        tp = close + risk * 2
    else:
        sl = rng.get("high", close + atr * 2) + atr * 0.25
        risk = max(sl - close, atr * 0.5)
        tp = close - risk * 2
    valid = bool(g_ict["reason_codes"]) or g_st["score"] != 0
    return {"valid": valid, "side": side if valid else None,
            "entry": round(close, 8), "sl": round(sl, 8), "tp": round(tp, 8),
            "risk_reward": round(abs(tp - close) / max(abs(close - sl), 1e-9), 3),
            "reason": "ICT/structure evidence" if valid else "tiada bukti zon"}


def build_trigger(groups, bars, i):
    """Trigger dari candle tertutup: displacement / sweep / BOS."""
    codes = []
    lqg = groups["liquidity"]
    ictg = groups["ict"]
    if lqg["raw"].get("sweep"):
        codes.append("TRIGGER_SWEEP")
    for c in ictg["reason_codes"]:
        if c.startswith("DISP_"):
            codes.append("TRIGGER_DISPLACEMENT")
        if c.startswith("FVG_"):
            codes.append("TRIGGER_FVG")
    if groups["structure"]["reason_codes"] and "BOS" in groups["structure"]["reason_codes"]:
        codes.append("TRIGGER_BOS")
    return {"confirmed": len(codes) > 0, "reason_codes": sorted(set(codes))}


def analyze(symbol, bars=None, i=None, spread_points=None, news_block=False):
    """Analysis lengkap satu symbol. Pulangkan analysis run dict."""
    symbol = ins.canonical(symbol)
    bars = bars if bars is not None else md.dedupe(md.load_bars(symbol, "M15"))
    if not bars:
        return {"symbol": symbol, "decision": "NO_TRADE",
                "reason_codes": ["NO_DATA"], "strategy_version": STRATEGY_VERSION}
    i = i if i is not None else len(bars) - 1
    atr = qt.atr(bars, i)
    pivots = st.swings(bars, i)
    by_tf = {"M15": bars, "H1": mt.resample(bars, 4),
             "H4": mt.resample(bars, 16), "D1": mt.resample(bars, 96)}

    groups = build_groups(bars, i, atr, pivots, by_tf)
    reg = rg.classify(bars, i, atr, mtf_result=groups["mtf"],
                      quant_result=groups["quant"], news_block=news_block)
    conf = sc.aggregate(groups)

    meta = ins.meta(symbol)
    prox = dc._median_spread(bars, i)
    sp = spread_points if spread_points is not None else None
    extra = {"vol_pct": reg.get("metrics", {}).get("vol_pct"),
             "conflict_score": conf["conflict_score"]}
    gates_ok, gate_codes, gate_details = dc.check_gates(
        bars, i, atr, symbol, spread_points=sp, news_block=news_block, extra=extra)

    direction = conf["direction"]
    setup = build_setup(groups, bars, i, atr, direction)
    trigger = build_trigger(groups, bars, i)
    dec = dc.decide(conf, setup, trigger, gates_ok, gate_codes, reg["regime"])

    # Kualiti data: staleness + gap
    h = md.health(symbol)
    data_quality = {"data_status": h["status"], "bars": h["bars"],
                    "staleness_s": h["staleness_seconds"],
                    "gaps_abnormal": h["gaps_non_weekend"],
                    "instrument_estimated": meta["is_estimated"],
                    "spread_proxy_median": round(prox, 8) if prox else None}

    return {
        "symbol": symbol,
        "as_of": bars[i]["open_time"].isoformat(),
        "strategy_version": STRATEGY_VERSION,
        "feature_version": FEATURE_VERSION,
        "regime": reg["regime"],
        "regime_confidence": reg["confidence"],
        "bias": direction,
        "directional_score": conf["normalized_score"],
        "coverage_score": conf["coverage_score"],
        "conflict_score": conf["conflict_score"],
        "decision": dec["decision"],
        "reason_codes": dec["reason_codes"],
        "active_groups": conf["active_groups"],
        "unavailable_groups": conf["unavailable_groups"],
        "setup": setup,
        "trigger": trigger,
        "gates": {"passed": gates_ok, "codes": gate_codes, "details": gate_details},
        "data_quality": data_quality,
        "confidence_label": ("STRONG" if abs(conf["normalized_score"]) >= 0.6
                             else "MODERATE" if abs(conf["normalized_score"]) >= 0.35
                             else "WEAK"),
        "confidence_note": "Label kekuatan bukti; BUKAN kebarangkalian untung.",
        "evidence": {k: v.get("evidence", []) for k, v in groups.items()},
        "group_scores": conf["group_scores"],
    }
