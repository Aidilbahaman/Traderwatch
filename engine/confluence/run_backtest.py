#!/usr/bin/env python3.12
"""Fasa 5 — jalankan backtest Confluence Engine pada data sejarah.

Jalankan: /usr/bin/python3.12 engine/confluence/run_backtest.py [--pairs N] [--step N]

Cara: langkau bar (step) untuk kelajuan, analisis pada setiap titik,
simulasi trade bila keputusan BUY/SELL. Laporkan metrik IS/OOS.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.confluence import market_data as md, instruments as ins  # noqa: E402
from engine.confluence import pipeline as pl, backtest as bt          # noqa: E402

PAIRS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"]


def run_one(symbol, step=20, min_history=300, expiry_bars=16, verbose=False):
    """Backtest satu symbol. Pulangkan senarai trade."""
    bars = md.dedupe(md.load_bars(symbol, "M15"))
    if len(bars) < min_history + 200:
        return []
    trades = []
    i = min_history
    while i < len(bars) - expiry_bars - 1:
        try:
            res = pl.analyze(symbol, bars=bars, i=i)
        except Exception as ex:
            if verbose:
                print(f"    ✗ bar {i}: {type(ex).__name__}")
            i += step
            continue
        if res["decision"] in ("BUY", "SELL"):
            s = res["setup"]
            tr = bt.simulate(bars, i, res["decision"], s["entry"], s["sl"], s["tp"],
                             expiry_bars=expiry_bars, symbol=symbol)
            if tr:
                # Kos dagangan sebenar
                ec = bt.trade_cost(symbol, s["entry"], slippage_points=1.0)
                xc = bt.trade_cost(symbol, tr["exit"] or s["entry"], slippage_points=1.0)
                tr["net_r"] = bt.net_r(tr, symbol, s["entry"], s["sl"], ec, xc)
                tr.update({
                    "symbol": symbol, "bar": i,
                    "time": bars[i]["open_time"].isoformat(),
                    "side": res["decision"],
                    "regime": res["regime"],
                    "score": res["directional_score"],
                    "coverage": res["coverage_score"],
                    "session": (res.get("evidence", {}).get("session") or [{}])[0].get("name", ["?"])[0]
                               if res.get("evidence", {}).get("session") else "?",
                })
                trades.append(tr)
        i += step
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=7)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    syms = PAIRS[:a.pairs] if a.pairs <= len(PAIRS) else md.available_symbols()
    print(f"backtest Confluence Engine · pair={len(syms)} step={a.step}bar")
    print(f"data: {md.HIST}")
    t0 = time.time()
    all_tr = []
    for s in syms:
        tr = run_one(s, step=a.step)
        all_tr += tr
        print(f"  {s:<8} {len(tr):>4} trade")

    if not all_tr:
        print("\n⚠️  TIADA TRADE dijana. Ini bermakna engine tidak keluar BUY/SELL "
              "pada mana-mana titik ujian (semua WAIT/NO_TRADE).")
        print("Itu hasil yang sah — engine menolak trade bila tiada edge kukuh.")
        return

    all_tr.sort(key=lambda r: r["bar"])
    print(f"\nTotal {len(all_tr)} trade · {time.time()-t0:.0f}s")

    is_rows, oos_rows = bt.split_chrono(all_tr, 0.7)
    print("\n=== PENUH ===")
    m = bt.metrics(all_tr)
    print(f"  n={m['n']} WR={m['win_rate']}% CI95={m['win_rate_ci95']} "
          f"exp={m['expectancy_r']:+.4f}R PF={m['profit_factor']} "
          f"totR={m['total_r']:+.1f} maxDD={m['max_dd_r']}R")
    print("\n=== IN-SAMPLE (70%) ===")
    mi = bt.metrics(is_rows)
    print(f"  n={mi['n']} WR={mi['win_rate']}% exp={mi['expectancy_r']:+.4f}R PF={mi['profit_factor']}")
    print("\n=== OUT-OF-SAMPLE (30%) ===")
    mo = bt.metrics(oos_rows)
    print(f"  n={mo['n']} WR={mo['win_rate']}% exp={mo['expectancy_r']:+.4f}R PF={mo['profit_factor']}")

    print("\n=== IKUT SYMBOL ===")
    for k, v in bt.breakdown(all_tr, "symbol").items():
        print(f"  {k:<8} n={v['n']:<4} WR={v['win_rate']:<6}% exp={v['expectancy_r']:+.4f}R")

    print("\n=== IKUT REGIME ===")
    for k, v in bt.breakdown(all_tr, "regime").items():
        print(f"  {k:<12} n={v['n']:<4} WR={v['win_rate']:<6}% exp={v['expectancy_r']:+.4f}R")

    print("\n=== IKUT ARAH ===")
    for k, v in bt.breakdown(all_tr, "side").items():
        print(f"  {k:<6} n={v['n']:<4} WR={v['win_rate']:<6}% exp={v['expectancy_r']:+.4f}R")

    wf = bt.walk_forward(all_tr, folds=4)
    if wf:
        print("\n=== WALK-FORWARD ===")
        for f in wf:
            print(f"  fold {f['fold']}: train n={f['train_n']} exp={f['train']['expectancy_r']:+.4f}R "
                  f"| test n={f['test_n']} exp={f['test']['expectancy_r']:+.4f}R")

    if a.json:
        out = Path(__file__).parent.parent.parent / "state" / "confluence-backtest.json"
        out.write_text(json.dumps({"full": m, "is": mi, "oos": mo,
                                   "by_symbol": bt.breakdown(all_tr, "symbol"),
                                   "by_regime": bt.breakdown(all_tr, "regime"),
                                   "walk_forward": wf}, indent=1))
        print(f"\nDisimpan -> {out}")


if __name__ == "__main__":
    main()
