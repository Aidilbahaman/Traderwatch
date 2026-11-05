#!/usr/bin/env python3.12
"""Ujian sensitiviti threshold — cari konfigurasi yang benar-benar ada edge.

Langkah:
  1. Jalankan pipeline SEKALI per (pair, bar) dan simpan skor + semua yang
     perlu. Ini elak kira semula 5x untuk 5 threshold berbeza.
  2. Untuk setiap threshold, tapis trade yang skor melepasi jalur.
  3. Split kronologi 70/30 + walk-forward. Laporkan SEMUA, bukan yang bagus.

Jalankan: /usr/bin/python3.12 engine/confluence/sensitivity.py [--step N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.confluence import market_data as md                       # noqa: E402
from engine.confluence import pipeline as pl, backtest as bt           # noqa: E402

PAIRS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"]
THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40]


def collect(symbol, step=10, min_history=300, expiry_bars=16):
    """Kumpul SEMUA titik analisis + simulasi trade untuk setiap titik.

    Simpan skor mentah supaya threshold boleh diuji tanpa kira semula.
    Guna tf_cache + bars yang dimuat SEKALI supaya ~17ms/titik bukan 136ms.
    """
    bars = md.dedupe(md.load_bars(symbol, "M15"))
    if len(bars) < min_history + 200:
        return []
    cache = pl.build_tf_cache(bars)
    rows = []
    i = min_history
    while i < len(bars) - expiry_bars - 1:
        try:
            res = pl.analyze(symbol, bars=bars, i=i, tf_cache=cache)
        except Exception:
            i += step
            continue
        s = res.get("setup") or {}
        if s.get("valid") and s.get("side") and s.get("sl") and s.get("tp"):
            tr = bt.simulate(bars, i, s["side"], s["entry"], s["sl"], s["tp"],
                             expiry_bars=expiry_bars)
            if tr:
                ec = bt.trade_cost(symbol, s["entry"], slippage_points=1.0)
                xc = bt.trade_cost(symbol, tr["exit"] or s["entry"], slippage_points=1.0)
                tr["net_r"] = bt.net_r(tr, symbol, s["entry"], s["sl"], ec, xc)
                tr.update({
                    "symbol": symbol, "bar": i, "side": s["side"],
                    "score": res["directional_score"],
                    "abs_score": abs(res["directional_score"]),
                    "score_matches_side": (
                        (res["directional_score"] > 0 and s["side"] == "BUY") or
                        (res["directional_score"] < 0 and s["side"] == "SELL")),
                    "regime": res["regime"],
                    "coverage": res["coverage_score"],
                    "trigger": res["trigger"]["confirmed"],
                    "gates_ok": res["gates"]["passed"],
                    "decision": res["decision"],
                })
        i += step
    return rows


def evaluate(rows, thr):
    """Tapis ikut threshold + trigger + gate, kira metrik IS/OOS."""
    sel = [r for r in rows
           if r["abs_score"] >= thr and r["score_matches_side"]
           and r["trigger"] and r["gates_ok"]]
    sel.sort(key=lambda r: r["bar"])
    if not sel:
        return {"n": 0}
    is_r, oos_r = bt.split_chrono(sel, 0.7)
    return {"full": bt.metrics(sel), "is": bt.metrics(is_r), "oos": bt.metrics(oos_r),
            "rows": sel}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=10)
    ap.add_argument("--pairs", type=int, default=7)
    a = ap.parse_args()

    syms = PAIRS[:a.pairs]
    print(f"Ujian sensitiviti · pair={len(syms)} step={a.step}bar")
    t0 = time.time()
    pool = []
    for s in syms:
        rows = collect(s, step=a.step)
        pool += rows
        print(f"  {s:<8} {len(rows):>4} setup sah")
    print(f"\nTotal setup sah dianalisis: {len(pool)}  ({time.time()-t0:.0f}s)")
    if not pool:
        print("⚠️ Tiada setup sah sama sekali.")
        return

    print(f"\n{'thr':<6}{'n':<6}{'WR%':<8}{'expR':<10}{'PF':<7}{'IS_exp':<10}{'OOS_n':<7}{'OOS_exp':<10}{'OOS_WR%'}")
    print("-" * 76)
    results = {}
    for thr in THRESHOLDS:
        r = evaluate(pool, thr)
        if r["n"] == 0:
            print(f"{thr:<6}0")
            continue
        f, i, o = r["full"], r["is"], r["oos"]
        print(f"{thr:<6}{f['n']:<6}{f['win_rate']:<8}{f['expectancy_r']:+.4f}   "
              f"{f['profit_factor']:<7}{i['expectancy_r']:+.4f}    "
              f"{o['n']:<7}{o.get('expectancy_r',0):+.4f}    {o.get('win_rate',0)}")
        results[str(thr)] = {"full": f, "is": i, "oos": o}

    # Pecahan terbaik ikut OOS expectancy (tapi laporkan n)
    valid = {k: v for k, v in results.items() if v["oos"].get("n", 0) >= 10}
    if valid:
        best = max(valid.items(), key=lambda kv: kv[1]["oos"]["expectancy_r"])
        print(f"\nThreshold terbaik (OOS n>=10): {best[0]} "
              f"exp={best[1]['oos']['expectancy_r']:+.4f}R n={best[1]['oos']['n']}")
    else:
        print("\n⚠️ TIADA threshold dengan OOS n>=10 — sample terlalu kecil untuk pilih pemenang.")

    out = Path(__file__).parent.parent.parent / "state" / "confluence-sensitivity.json"
    out.write_text(json.dumps({"step": a.step, "pool_size": len(pool),
                               "results": results}, indent=1))
    print(f"\nDisimpan -> {out}")


if __name__ == "__main__":
    main()
