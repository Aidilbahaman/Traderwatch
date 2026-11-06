#!/usr/bin/env python3.12
"""Diagnostik kumpulan — cari kumpulan mana yang MEROSAKKAN skor.

Kaedah: uji setiap kumpulan SECARA BERASINGAN sebagai penapis tunggal.
Kumpulan yang berguna mesti ada expectancy positif bila dipakai sendiri.
Kalau kumpulan merosakkan, buang atau baiki.

Hindari masalah "confluence palsu": jangan gabung 10 kumpulan dan harap
jumlahnya berfungsi.

Jalankan: /usr/bin/python3.12 engine/confluence/group_diagnostics.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.confluence import market_data as md                       # noqa: E402
from engine.confluence import pipeline as pl, backtest as bt           # noqa: E402

PAIRS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"]
STEP = 20
MIN_HISTORY = 300
EXPIRY_BARS = 16


def collect(symbol):
    """Kumpul SEMUA titik + skor setiap kumpulan (bukan hanya agregat)."""
    bars = md.dedupe(md.load_bars(symbol, "M15"))
    if len(bars) < MIN_HISTORY + 200:
        return []
    cache = pl.build_tf_cache(bars)
    rows = []
    i = MIN_HISTORY
    last_exit = -1
    while i < len(bars) - EXPIRY_BARS - 1:
        try:
            r = pl.analyze(symbol, bars=bars, i=i, tf_cache=cache, direction_band=0.05)
        except Exception:
            i += STEP
            continue
        s = r.get("setup") or {}
        if s.get("valid") and s.get("side") and i > last_exit:
            tr = bt.simulate(bars, i, s["side"], s["entry"], s["sl"], s["tp"],
                             expiry_bars=EXPIRY_BARS)
            if tr:
                ec = bt.trade_cost(symbol, s["entry"], slippage_points=1.0)
                xc = bt.trade_cost(symbol, tr["exit"] or s["entry"], slippage_points=1.0)
                tr["net_r"] = bt.net_r(tr, symbol, s["entry"], s["sl"], ec, xc)
                tr["symbol"] = symbol
                tr["bar"] = i
                tr["side"] = s["side"]
                tr["groups"] = dict(r["group_scores"])
                tr["aggr_score"] = r["directional_score"]
                rows.append(tr)
                last_exit = i + (tr.get("bars_held") or 0)
        i += STEP
    return rows


def eval_group(rows, name, thr):
    """Uji satu kumpulan sebagai penapis tunggal."""
    sel = [r for r in rows
           if abs(r["groups"].get(name, 0)) >= thr
           and (r["groups"].get(name, 0) > 0) == (r["side"] == "BUY")]
    if not sel:
        return None
    sel.sort(key=lambda r: r["bar"])
    is_r, oos_r = bt.split_chrono(sel, 0.7)
    return {"n": len(sel), "full": bt.metrics(sel),
            "is": bt.metrics(is_r), "oos": bt.metrics(oos_r)}


def main():
    t0 = time.time()
    print("Diagnostik kumpulan — setiap kumpulan diuji SENDIRI")
    print(f"pair={len(PAIRS)} step={STEP}\n")
    pool = []
    for s in PAIRS:
        r = collect(s)
        pool += r
        print(f"  {s:<8} {len(r):>4} titik")
    print(f"\nTotal: {len(pool)} titik ({time.time()-t0:.0f}s)")

    # Baseline: semua trade tanpa tapisan kumpulan
    pool.sort(key=lambda r: r["bar"])
    base_is, base_oos = bt.split_chrono(pool, 0.7)
    print(f"\n=== BASELINE (tiada tapisan) ===")
    print(f"  penuh: n={bt.metrics(pool)['n']} exp={bt.metrics(pool)['expectancy_r']:+.4f}R")
    print(f"  IS:    exp={bt.metrics(base_is)['expectancy_r']:+.4f}R")
    print(f"  OOS:   n={bt.metrics(base_oos)['n']} exp={bt.metrics(base_oos)['expectancy_r']:+.4f}R")

    groups = ["structure", "liquidity", "ict", "quant", "mtf", "session"]
    print(f"\n=== SETIAP KUMPULAN SENDIRI (threshold 0.45) ===")
    print(f"{'kumpulan':<12}{'n':<7}{'WR%':<8}{'expR':<10}{'IS_exp':<10}{'OOS_n':<7}{'OOS_exp':<10}{'nilai'}")
    print("-" * 76)
    verdicts = {}
    for g in groups:
        r = eval_group(pool, g, 0.45)
        if not r:
            print(f"{g:<12}— tiada trade melepasi")
            verdicts[g] = "TIADA_DATA"
            continue
        f, i, o = r["full"], r["is"], r["oos"]
        oe = o.get("expectancy_r", 0)
        verdict = ("✅ BERGUNA" if oe > 0.02 and o.get("n", 0) >= 30
                   else "⚠️ LEMAH" if oe > 0 else "❌ MEROSAKKAN")
        verdicts[g] = verdict
        print(f"{g:<12}{f['n']:<7}{f['win_rate']:<8}{f['expectancy_r']:+.4f}   "
              f"{i['expectancy_r']:+.4f}   {o.get('n',0):<7}{oe:+.4f}    {verdict}")

    print(f"\n=== RUMUSAN ===")
    for g, v in verdicts.items():
        print(f"  {g:<12} {v}")

    good = [g for g, v in verdicts.items() if v == "✅ BERGUNA"]
    print(f"\nKumpulan berguna: {good or 'TIADA'}")
    print("Kumpulan yang merosakkan patut dibuang atau dibaiki berasingan.")

    out = Path(__file__).parent.parent.parent / "state" / "cf_group_diagnostics.json"
    out.write_text(json.dumps({"pool": len(pool), "verdicts": verdicts}, indent=1))
    print(f"\nDisimpan -> {out}")


if __name__ == "__main__":
    main()
