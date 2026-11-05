"""Fasa 3 — Decision engine (spec §1.6 decision states, §1.7 hard gates).

BUY/SELL hanya bila: setup SAH + trigger SAH + SEMUA gate lulus.
Kalau tidak -> WAIT (arah ada, trigger tiada) atau NO_TRADE (gate blok).
"""
from __future__ import annotations


def check_gates(bars, i, atr, instrument, spread_points=None,
                news_block=False, min_history=260, extra=None):
    """Semua hard gate dari spec §1.7. Pulangkan (lulus, senarai_kod, details)."""
    codes, details = [], {}

    # 1. Data kritikal segar
    if i < min_history:
        codes.append("GATE_HISTORY_SHORT")
    # 2. Harga sah
    c = bars[i]["close"] if bars else 0
    if not c or c <= 0:
        codes.append("GATE_PRICE_INVALID")
    # 3. Sequence candle sah (high >= max(o,c), low <= min(o,c))
    b = bars[i]
    if not (b["high"] >= max(b["open"], b["close"]) - 1e-9
            and b["low"] <= min(b["open"], b["close"]) + 1e-9):
        codes.append("GATE_CANDLE_INVALID")
    # 4. ATR sah
    if not atr or atr <= 0:
        codes.append("GATE_ATR_INVALID")
    # 5. Spread
    if spread_points is not None:
        limit = SPREAD_LIMITS.get(instrument, 3.0)
        details["spread_points"] = spread_points
        details["spread_limit"] = limit
        if spread_points > limit:
            codes.append("GATE_SPREAD_WIDE")
    # 6. News blackout
    if news_block:
        codes.append("GATE_NEWS_BLACKOUT")
    # 7. Volatiliti abnormal
    if extra and extra.get("vol_pct") is not None and extra["vol_pct"] >= 0.98:
        codes.append("GATE_VOL_EXTREME")
    # 8. Konflik bukti teruk
    if extra and extra.get("conflict_score", 0) >= 0.6:
        codes.append("GATE_EVIDENCE_CONFLICT")

    return (len(codes) == 0), codes, details


# Had spread (point) ikut instrumen — boleh ditala nanti
SPREAD_LIMITS = {
    "XAUUSD": 40.0,    # emas spread lebar
    "XAGUSD": 40.0,
    "BTCUSD": 800.0,
    "ETHUSD": 80.0,
    "DEFAULT": 3.0,    # FX major
}


def _median_spread(bars, i, n=50):
    """Proksi spread dari julat bar bila data spread sebenar tiada.

    Spec §1.4 F: jangan dakwa tick volume sebagai volume institusi.
    Sama di sini — ini PROKSI, ditanda sebagai anggaran.
    """
    rs = [(bars[k]["high"] - bars[k]["low"]) for k in range(max(0, i - n + 1), i + 1)]
    if not rs:
        return None
    rs.sort()
    return rs[len(rs) // 2]


def decide(confluence, setup, trigger, gates_ok, gate_codes, regime):
    """Buat keputusan akhir + reason codes.

    setup: {"valid": bool, "side": "BUY"/"SELL"/None, "entry":..., "sl":..., "tp":...}
    trigger: {"confirmed": bool, ...}
    """
    codes = []

    # Gate blok -> NO_TRADE (BUKAN BUY/SELL keyakinan rendah) — §1.7
    if not gates_ok:
        return {"decision": "NO_TRADE", "reason_codes": gate_codes + ["BLOCKED_BY_GATE"]}

    direction = confluence.get("direction", "NEUTRAL")
    if direction == "NEUTRAL":
        codes.append("NO_DIRECTIONAL_EDGE")
        return {"decision": "WAIT", "reason_codes": codes}

    if not setup or not setup.get("valid"):
        codes.append("SETUP_NOT_VALID")
        return {"decision": "WAIT", "reason_codes": codes}

    side = "BUY" if direction == "BULLISH" else "SELL"
    if setup.get("side") != side:
        codes.append("SETUP_DIRECTION_MISMATCH")
        return {"decision": "WAIT", "reason_codes": codes}

    if not trigger or not trigger.get("confirmed"):
        codes.append("TRIGGER_NOT_CONFIRMED")
        return {"decision": "WAIT", "reason_codes": codes}

    if regime == "VOLATILE":
        codes.append("REGIME_VOLATILE_CAUTION")
    if confluence.get("coverage_score", 0) < 0.5:
        codes.append("LOW_COVERAGE")

    return {"decision": side, "reason_codes": codes + ["SETUP_TRIGGER_ALIGNED"]}
