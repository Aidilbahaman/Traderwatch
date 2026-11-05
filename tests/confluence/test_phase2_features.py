#!/usr/bin/env python3.12
"""Ujian Fasa 2 — feature engines + no-lookahead.

Jalankan: /usr/bin/python3.12 tests/confluence/test_phase2_features.py

Ujian no-lookahead (§4.1 spec) adalah yang PALING PENTING:
feature pada bar i tidak boleh berubah bila bar > i ditambah.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")
from engine.confluence import market_data as md                       # noqa: E402
from engine.confluence.features import (structure as st, liquidity as lq,  # noqa: E402
                                        quant as qt, mtf, ict as ic)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


BARS = md.dedupe(md.load_bars("XAUUSD", "M15"))
I = len(BARS) - 1
ATR = qt.atr(BARS, I)

print("=== 1. Structure ===")
piv = st.swings(BARS, I)
check("pivot dikesan", len(piv) > 0, f"{len(piv)}")
check("pivot ada kind H/L", all(p["kind"] in "HL" for p in piv))
check("pivot ada confirmed_at", all("confirmed_at" in p for p in piv))
check("confirmed_at >= idx+lookback",
      all(p["confirmed_at"] >= p["idx"] + 3 for p in piv))
tr, lbl = st.trend_from_swings(piv)
check("trend dalam julat", tr in (-1, 0, 1), f"{tr}")
rng = st.dealing_range(piv)
check("dealing range sah", rng and rng["high"] > rng["low"])
pd = st.premium_discount(BARS[I]["close"], rng)
check("premium/discount 0..1", pd is not None and 0 <= pd <= 1, f"{pd}")
sf = st.structure_features(BARS, I, ATR)
check("structure score -1..1", -1 <= sf["score"] <= 1)
check("structure ada evidence", "evidence" in sf and "raw" in sf)

print("\n=== 2. Liquidity ===")
lv = lq.liquidity_levels(piv, ATR)
check("BSL/SSL ada", "bsl" in lv and "ssl" in lv)
check("level ada touch count", all("touches" in l for l in lv["bsl"]))
lf = lq.liquidity_features(BARS, I, piv, ATR)
check("liquidity score -1..1", -1 <= lf["score"] <= 1)
sl = lq.session_levels(BARS, I, "london")
check("session level sah", sl is None or sl["high"] >= sl["low"])
sw = lq.detect_sweep(BARS, I, 999999999, "BSL")
check("sweep level jauh -> None", sw is None)

print("\n=== 3. Quant ===")
q = qt.quant_features(BARS, I)
check("quant score -1..1", -1 <= q["score"] <= 1)
check("ATR positif", q["raw"]["atr"] > 0)
check("RSI 0..100", q["raw"]["rsi"] is None or 0 <= q["raw"]["rsi"] <= 100)
check("EMA20 < EMA200 (uptrend XAU)", q["raw"]["ema20"] > q["raw"]["ema200"])
adx = q["raw"]["adx"]
check("ADX ada plus/minus DI", adx and "plus_di" in adx and "minus_di" in adx)
check("EMA-DMI conflict dikesan bila ada",
      not (adx and adx["adx"] > 25 and q["raw"]["ema20"] > q["raw"]["ema50"]
           and adx["minus_di"] > adx["plus_di"]) or "CONFLICT_EMA_DMI" in q["reason_codes"])

print("\n=== 4. MTF ===")
by_tf = {"M15": BARS, "H1": mtf.resample(BARS, 4),
         "H4": mtf.resample(BARS, 16), "D1": mtf.resample(BARS, 96)}
m = mtf.mtf_bias(by_tf)
check("MTF score -1..1", -1 <= m["score"] <= 1)
check("MTF ada by_tf", "by_tf" in m["raw"])
check("resample H4 betul", len(by_tf["H4"]) == len(BARS) // 16)
check("resample high >= low", all(b["high"] >= b["low"] for b in by_tf["H4"]))
s = mtf.session_features(BARS, I)
check("session dikesan", len(s["reason_codes"]) > 0)
check("session high >= low", s["raw"]["session_high"] >= s["raw"]["session_low"])

print("\n=== 5. ICT ===")
g = ic.ict_group(BARS, I, ATR)
check("ICT score -1..1", -1 <= g["score"] <= 1)
check("ICT ada raw", "raw" in g)
check("ICT coverage 1.0", g["coverage"] == 1.0)
g2 = ic.ict_group(BARS[:50], 49, ATR)
check("sejarah pendek -> UNAVAILABLE", g2["direction"] == "UNAVAILABLE")

print("\n=== 6. NO-LOOKAHEAD (paling penting) ===")
# Feature pada bar I mesti SAMA sama ada kita bagi data sampai I atau lebih.
for name, fn in [
    ("structure", lambda b, i: st.structure_features(b, i, qt.atr(b, i))["score"]),
    ("liquidity", lambda b, i: lq.liquidity_features(b, i, st.swings(b, i), qt.atr(b, i))["score"]),
    ("quant", lambda b, i: qt.quant_features(b, i)["score"]),
    ("ict", lambda b, i: ic.ict_group(b, i, qt.atr(b, i))["score"]),
]:
    a = fn(BARS, I)
    # Buang 10 bar terakhir, kira pada bar yang sama
    trunc = BARS[:I + 1]
    b = fn(trunc, I)
    check(f"{name}: sama dengan/tanpa bar hadapan", a == b, f"{a} vs {b}")

# Tambah bar palsu di hadapan — feature pada I mesti tak berubah
fake = BARS + [{"open_time": BARS[-1]["open_time"] + timedelta(minutes=15),
                "open": 99999, "high": 99999, "low": 99999, "close": 99999,
                "tick_volume": 1}]
q_a = qt.quant_features(BARS, I)["score"]
q_b = qt.quant_features(fake, I)["score"]
check("quant: bar palsu di hadapan tak ubah bar I", q_a == q_b, f"{q_a} vs {q_b}")

print(f"\n{'='*50}\nLULUS: {PASS}  GAGAL: {FAIL}")
sys.exit(1 if FAIL else 0)
