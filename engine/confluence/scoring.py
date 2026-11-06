"""Fasa 3 — Confluence aggregation (spec §1.5, §3.1 langkah 4).

Prinsip:
  - Evidence sebelum skor.
  - Kumpulan berkorelasi TIDAK dikira sebagai pengesahan berasingan (§1.2 #2).
  - Skor bukan kebarangkalian untung (§1.5).
  - Coverage dan conflict dilaporkan BERASINGAN, bukan dilebur ke dalam skor.
  - Data UNAVAILABLE tidak dikira neutral, tidak diagih semula (§1.3).
"""
from __future__ import annotations

# Wajaran awal dari spec §1.3 — hipotesis untuk ujian, bukan dakwaan untung.
WEIGHTS = {
    "structure": 20,
    "liquidity": 18,
    "ict": 15,
    "mtf": 12,
    "volume": 10,        # UNAVAILABLE — tiada sumber sah
    "macro": 8,          # UNAVAILABLE
    "quant": 7,
    "intermarket": 5,    # UNAVAILABLE
    "session": 3,
    "elliot": 2,
}

# Kumpulan yang SENGAJA tiada data — ditanda UNAVAILABLE, bukan sifar.
UNAVAILABLE_GROUPS = {"volume", "macro", "intermarket"}

# Kumpulan yang saling berkorelasi tinggi. Bila dua-dua bersetuju, jangan
# kira sebagai dua pengesahan penuh — kurangkan sumbangan yang lebih lemah.
CORRELATED_PAIRS = [
    ("structure", "mtf"),     # kedua-dua baca arah trend
    ("ict", "liquidity"),     # kedua-dua dari struktur swing
]

BANDS = {"bullish": 0.35, "bearish": -0.35}   # cadangan awal spec §1.5


def aggregate(group_results, band=None):
    """Gabung hasil kumpulan jadi skor confluence.

    group_results: {"structure": {...}, "liquidity": {...}, ...}
    Setiap kumpulan: {score, direction, coverage, quality, evidence, reason_codes}
    band: jalur arah (default BANDS["bullish"]). Boleh diturunkan untuk
    kajian sensitiviti — JANGAN ubah default tanpa ujian.
    """
    bull_band = BANDS["bullish"] if band is None else abs(band)
    active, missing = {}, []
    for name, w in WEIGHTS.items():
        g = group_results.get(name)
        if not g or g.get("direction") == "UNAVAILABLE" or g.get("coverage", 0) <= 0:
            missing.append(name)
            continue
        active[name] = g

    # --- Kawalan korelasi: kumpulan berkorelasi tak dikira dua kali penuh ---
    adjusted = dict(active)
    corr_codes = []
    for a, b in CORRELATED_PAIRS:
        if a in active and b in active:
            sa, sb = active[a]["score"], active[b]["score"]
            if sa * sb > 0:   # setuju arah sama
                weaker = a if abs(sa) < abs(sb) else b
                g = dict(active[weaker])
                g["score"] = g["score"] * 0.5
                g["corr_discounted"] = True
                adjusted[weaker] = g
                corr_codes.append(f"CORR_DISCOUNT_{weaker.upper()}")

    # --- Skor mentah ---
    raw = 0.0
    weight_sum = 0.0
    for name, g in adjusted.items():
        w = WEIGHTS[name]
        contrib = w * g.get("score", 0) * g.get("quality", 1) * g.get("coverage", 1)
        raw += contrib
        weight_sum += w
    normalized = round(raw / weight_sum, 4) if weight_sum else 0.0

    # --- Coverage ---
    total_w = sum(WEIGHTS.values())
    avail_w = sum(WEIGHTS[n] for n in active)
    coverage = round(avail_w / total_w, 4)

    # --- Conflict: kumpulan bertentangan arah ---
    dirs = [g.get("direction") for g in active.values()]
    bulls = dirs.count("BULLISH")
    bears = dirs.count("BEARISH")
    conflict_score = round(min(bulls, bears) / max(1, len(dirs)), 4)

    codes = list(corr_codes)
    if missing:
        codes.append("GROUPS_UNAVAILABLE:" + ",".join(sorted(missing)))
    if conflict_score >= 0.4:
        codes.append("EVIDENCE_CONFLICT")

    direction = ("BULLISH" if normalized >= bull_band
                 else ("BEARISH" if normalized <= -bull_band else "NEUTRAL"))

    return {
        "normalized_score": normalized,
        "coverage_score": coverage,
        "conflict_score": conflict_score,
        "direction": direction,
        "active_groups": sorted(active),
        "unavailable_groups": sorted(set(missing)),
        "group_scores": {k: v["score"] for k, v in active.items()},
        "reason_codes": codes,
        "note": "Skor ini kekuatan bukti berarah, BUKAN kebarangkalian untung.",
    }
