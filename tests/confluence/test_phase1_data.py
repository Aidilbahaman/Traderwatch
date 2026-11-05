#!/usr/bin/env python3.12
"""Ujian Fasa 1 — market data adapter + instrument metadata.

Dijalankan: /usr/bin/python3.12 tests/confluence/test_phase1_data.py
Tiada pytest diperlukan — assert biasa supaya boleh jalan atas VPS.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")
from engine.confluence import market_data as md, instruments as ins  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


print("=== 1. Instrument metadata ===")
m = ins.meta("XAU/USD")
check("XAU/USD -> XAUUSD canonical", m["symbol"] == "XAUUSD")
check("XAUUSD digits=2", m["digits"] == 2)
check("XAUUSD pip=0.1", m["pip_size"] == 0.1)
check("XAUUSD bukan anggaran", m["is_estimated"] is False)
check("EURUSD digits=5", ins.meta("EURUSD")["digits"] == 5)
check("USDJPY digits=3", ins.meta("USDJPY")["digits"] == 3)
check("BTCUSD pip=1.0 (dolar)", ins.meta("BTCUSD")["pip_size"] == 1.0)
unknown = ins.meta("ZZZJPY")
check("symbol tak dikenali ditanda estimated", unknown["is_estimated"] is True)
check("fallback JPY -> 3 digit", unknown["digits"] == 3)
check("format XAUUSD 2dp", ins.format_price("XAUUSD", 4102.567) == "4,102.57")
check("format EURUSD 5dp", ins.format_price("EURUSD", 1.122345) == "1.12234")
check("format None -> dash", ins.format_price("EURUSD", None) == "—")

print("\n=== 2. Market data load ===")
syms = md.available_symbols()
check(">=30 pair tersedia", len(syms) >= 30, f"dapat {len(syms)}")
bars = md.load_bars("XAUUSD", "M15")
check("XAUUSD ada bar", len(bars) > 1000, f"{len(bars)}")
check("bar ada OHLCV", all(k in bars[0] for k in
                          ("open_time", "open", "high", "low", "close", "tick_volume")))
check("timestamp UTC aware", bars[0]["open_time"].tzinfo is not None)
check("timeframe tidak wujud -> kosong", md.load_bars("XAUUSD", "H4") == [])

print("\n=== 3. Dedup ===")
dup = bars[:5] + bars[:5]
check("dedup buang duplicate", len(md.dedupe(dup)) == 5)
check("dedup kekal susunan", md.dedupe(dup) == bars[:5])

print("\n=== 4. Gap detection ===")
gaps = md.find_gaps(bars, "M15")
check("gap dikesan", len(gaps) > 0)
check("gap ada metadata", all(k in gaps[0] for k in
                              ("after", "before", "minutes", "likely_weekend", "likely_rollover")))
weekend = [g for g in gaps if g["likely_weekend"]]
check("weekend gap dikesan", len(weekend) > 0, f"{len(weekend)}")
roll = [g for g in gaps if g["likely_rollover"]]
check("rollover harian dikesan", len(roll) > 0, f"{len(roll)}")

print("\n=== 5. Health ===")
h = md.health("XAUUSD")
check("health ada status", h["status"] in ("OK", "DEGRADED", "STALE", "UNAVAILABLE"))
check("health kira rollover", h["gaps_rollover"] > 0)
check("health kira weekend", h["gaps_weekend"] > 0)
check("health abnormal kecil", h["gaps_non_weekend"] < 20, f"{h['gaps_non_weekend']}")
h2 = md.health("TIDAKWUJUD")
check("symbol tiada -> UNAVAILABLE", h2["status"] == "UNAVAILABLE")

print("\n=== 6. Staleness ===")
st = md.staleness_seconds(bars)
check("staleness positif", st is not None and st > 0)
now = bars[-1]["open_time"] + timedelta(minutes=15)
check("staleness tepat bila diberi now", md.staleness_seconds(bars, now) == 900.0)

print(f"\n{'='*50}\nLULUS: {PASS}  GAGAL: {FAIL}")
sys.exit(1 if FAIL else 0)
