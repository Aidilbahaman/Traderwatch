#!/usr/bin/env python3.12
"""Ujian Fasa 3 — regime, scoring, gates, decision, pipeline.

Jalankan: /usr/bin/python3.12 tests/confluence/test_phase3_decision.py
"""
import sys

sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")
from engine.confluence import market_data as md, regime as rg, scoring as sc  # noqa: E402
from engine.confluence import decision as dc, pipeline as pl                  # noqa: E402
from engine.confluence.features import quant as qt                            # noqa: E402

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

print("=== 1. Regime ===")
r = rg.classify(BARS, I, ATR)
check("regime sah", r["regime"] in ("TRENDING", "RANGING", "VOLATILE",
                                    "NEWS_DRIVEN", "UNCERTAIN"))
check("confidence 0..1", 0 <= r["confidence"] <= 1)
rn = rg.classify(BARS, I, ATR, news_block=True)
check("news -> NEWS_DRIVEN", rn["regime"] == "NEWS_DRIVEN")
vp = rg.volatility_percentile(BARS, I)
check("vol percentile 0..1", vp is None or 0 <= vp <= 1, f"{vp}")

print("\n=== 2. Scoring ===")
groups = {
    "structure": {"score": 0.5, "direction": "BULLISH", "coverage": 1.0, "quality": 1.0},
    "liquidity": {"score": 0.4, "direction": "BULLISH", "coverage": 1.0, "quality": 1.0},
    "ict": {"score": 0.3, "direction": "BULLISH", "coverage": 1.0, "quality": 1.0},
    "quant": {"score": -0.2, "direction": "BEARISH", "coverage": 1.0, "quality": 1.0},
    "session": {"score": 0.0, "direction": "NEUTRAL", "coverage": 1.0, "quality": 1.0},
    "volume": {"score": 0.0, "direction": "UNAVAILABLE", "coverage": 0.0, "quality": 0.0},
}
a = sc.aggregate(groups)
check("normalized -1..1", -1 <= a["normalized_score"] <= 1)
check("coverage 0..1", 0 <= a["coverage_score"] <= 1)
check("UNAVAILABLE tidak dikira aktif", "volume" not in a["active_groups"])
check("UNAVAILABLE dilaporkan", "volume" in a["unavailable_groups"])
check("korelasi didiskaun", any("CORR_DISCOUNT" in c for c in a["reason_codes"]),
      f"{a['reason_codes']}")
check("nota bukan kebarangkalian", "BUKAN kebarangkalian" in a["note"])
# Coverage: 5 aktif dari 10 kumpulan (=20+18+15+7+3=63 dari 100)
check("coverage dikira betul", abs(a["coverage_score"] - 0.63) < 0.01,
      f"{a['coverage_score']}")

print("\n=== 3. Hard gates ===")
ok, codes, det = dc.check_gates(BARS, I, ATR, "XAUUSD")
check("gate lulus untuk data sihat", ok, f"{codes}")
ok2, codes2, _ = dc.check_gates(BARS, 10, ATR, "XAUUSD")
check("sejarah pendek -> GATE_HISTORY_SHORT", "GATE_HISTORY_SHORT" in codes2)
ok3, codes3, _ = dc.check_gates(BARS, I, ATR, "XAUUSD", spread_points=999)
check("spread lebar -> GATE_SPREAD_WIDE", "GATE_SPREAD_WIDE" in codes3)
ok4, codes4, _ = dc.check_gates(BARS, I, ATR, "XAUUSD", news_block=True)
check("news -> GATE_NEWS_BLACKOUT", "GATE_NEWS_BLACKOUT" in codes4)
ok5, codes5, _ = dc.check_gates(BARS, I, 0, "XAUUSD")
check("ATR 0 -> GATE_ATR_INVALID", "GATE_ATR_INVALID" in codes5)
# EURUSD limit 3.0, XAUUSD limit 40
_, c_fx, _ = dc.check_gates(BARS, I, ATR, "EURUSD", spread_points=5)
check("had spread ikut instrumen (EURUSD 3.0)", "GATE_SPREAD_WIDE" in c_fx)

print("\n=== 4. Decision states ===")
conf_bull = {"direction": "BULLISH", "coverage_score": 0.8, "conflict_score": 0.1}
setup_ok = {"valid": True, "side": "BUY", "entry": 4100, "sl": 4090, "tp": 4120}
trig_ok = {"confirmed": True}
d1 = dc.decide(conf_bull, setup_ok, trig_ok, True, [], "TRENDING")
check("setup+trigger+gate -> BUY", d1["decision"] == "BUY", d1["decision"])
d2 = dc.decide(conf_bull, setup_ok, {"confirmed": False}, True, [], "TRENDING")
check("trigger tiada -> WAIT", d2["decision"] == "WAIT")
d3 = dc.decide(conf_bull, setup_ok, trig_ok, False, ["GATE_SPREAD_WIDE"], "TRENDING")
check("gate blok -> NO_TRADE", d3["decision"] == "NO_TRADE")
check("NO_TRADE bukan BUY keyakinan rendah", "BLOCKED_BY_GATE" in d3["reason_codes"])
d4 = dc.decide({"direction": "NEUTRAL"}, setup_ok, trig_ok, True, [], "RANGING")
check("neutral -> WAIT", d4["decision"] == "WAIT")
setup_bad = {"valid": True, "side": "SELL"}
d5 = dc.decide(conf_bull, setup_bad, trig_ok, True, [], "TRENDING")
check("setup arah salah -> WAIT", d5["decision"] == "WAIT")

print("\n=== 5. Pipeline ===")
res = pl.analyze("XAUUSD")
for k in ("symbol", "decision", "regime", "bias", "directional_score",
          "coverage_score", "conflict_score", "reason_codes", "setup",
          "trigger", "gates", "data_quality"):
    check(f"pipeline ada '{k}'", k in res)
check("decision sah", res["decision"] in ("BUY", "SELL", "WAIT", "NO_TRADE"))
check("unavailable groups dilaporkan", len(res["unavailable_groups"]) > 0)
check("macro sentiasa UNAVAILABLE", "macro" in res["unavailable_groups"])
check("volume sentiasa UNAVAILABLE", "volume" in res["unavailable_groups"])
check("confidence note bukan kebarangkalian",
      "BUKAN kebarangkalian" in res["confidence_note"])
check("strategy version ada", res["strategy_version"].startswith("confluence-"))
r2 = pl.analyze("TIDAKWUJUD")
check("symbol tiada data -> NO_TRADE", r2["decision"] == "NO_TRADE")
check("reason NO_DATA", "NO_DATA" in r2["reason_codes"])

print("\n=== 6. Semua 36 pair ===")
ok_all = 0
syms = md.available_symbols()
for s in syms:
    try:
        rr = pl.analyze(s)
        if rr["decision"] in ("BUY", "SELL", "WAIT", "NO_TRADE"):
            ok_all += 1
    except Exception as ex:
        print(f"    ✗ {s}: {type(ex).__name__} {ex}")
check(f"semua {len(syms)} pair dianalisis", ok_all == len(syms), f"{ok_all}/{len(syms)}")

print(f"\n{'='*50}\nLULUS: {PASS}  GAGAL: {FAIL}")
sys.exit(1 if FAIL else 0)
