#!/usr/bin/env python3.12
"""Laporan sensitiviti — jana deliverables A–H dari cf_sensitivity_full.json.

Jalankan: /usr/bin/python3.12 engine/confluence/report_sensitivity.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "state" / "cf_sensitivity_full.json"


def load():
    if not SRC.exists():
        print(f"⚠️ {SRC} tiada — jalankan sensitivity_full.py dahulu")
        sys.exit(1)
    return json.loads(SRC.read_text())


def fmt_row(k, r):
    f = r.get("full") or {}
    i = r.get("is") or {}
    o = r.get("oos") or {}
    ci = f.get("win_rate_ci95", (0, 0))
    return (f"{r['threshold']:<6}{r['step']:<6}{f.get('n',0):<6}"
            f"{f.get('win_rate',0):<8}{f.get('expectancy_r',0):+.4f}   "
            f"{f.get('profit_factor',0):<8}{f.get('total_r',0):+.1f}    "
            f"{f.get('max_dd_r',0):<8}{i.get('expectancy_r',0):+.4f}    "
            f"{o.get('n',0):<7}{o.get('expectancy_r',0):+.4f}    "
            f"[{ci[0]:.0f},{ci[1]:.0f}]")


def main():
    d = load()
    R = d["results"]
    print("=" * 104)
    print("A. JADUAL PERBANDINGAN 18 KONFIGURASI")
    print("=" * 104)
    print(f"config={d['config_version']} strategy={d['strategy_version']} "
          f"feature={d['feature_version']}")
    print(f"dataset_fingerprint={d['dataset_fingerprint']}")
    print(f"pair={d['pairs']}\nsplit IS/OOS={int(d['is_fraction']*100)}/"
          f"{int((1-d['is_fraction'])*100)} · slippage={d['slippage_points']}pt")
    print()
    print(f"{'thr':<6}{'step':<6}{'n':<6}{'WR%':<8}{'expR':<10}{'PF':<8}"
          f"{'totR':<8}{'maxDD':<8}{'IS_exp':<10}{'OOS_n':<7}{'OOS_exp':<10}{'CI95 WR'}")
    print("-" * 104)
    for k, r in R.items():
        if r.get("full", {}).get("n", 0):
            print(fmt_row(k, r))

    # B — sensitivity threshold (purata merentas step)
    print("\n" + "=" * 104)
    print("B. SENSITIVITI THRESHOLD (purata merentas 3 step)")
    print("=" * 104)
    print(f"{'thr':<8}{'bil config':<12}{'avg n':<9}{'avg expR':<11}"
          f"{'avg OOS exp':<14}{'avg OOS n':<11}")
    print("-" * 60)
    for thr in d["thresholds"]:
        rs = [r for r in R.values()
              if r["threshold"] == thr and r.get("full", {}).get("n", 0)]
        if not rs:
            print(f"{thr:<8}0 config")
            continue
        an = sum(r["full"]["n"] for r in rs) / len(rs)
        ae = sum(r["full"]["expectancy_r"] for r in rs) / len(rs)
        aoe = sum((r.get("oos") or {}).get("expectancy_r", 0) for r in rs) / len(rs)
        aon = sum((r.get("oos") or {}).get("n", 0) for r in rs) / len(rs)
        print(f"{thr:<8}{len(rs):<12}{an:<9.1f}{ae:<11.4f}{aoe:<14.4f}{aon:<11.1f}")

    print("\n" + "=" * 104)
    print("C. SENSITIVITI STEP (purata merentas 6 threshold)")
    print("=" * 104)
    print(f"{'step':<8}{'bil config':<12}{'avg n':<9}{'avg expR':<11}"
          f"{'avg OOS exp':<14}")
    print("-" * 60)
    for st in d["steps"]:
        rs = [r for r in R.values()
              if r["step"] == st and r.get("full", {}).get("n", 0)]
        if not rs:
            print(f"{st:<8}0 config")
            continue
        an = sum(r["full"]["n"] for r in rs) / len(rs)
        ae = sum(r["full"]["expectancy_r"] for r in rs) / len(rs)
        aoe = sum((r.get("oos") or {}).get("expectancy_r", 0) for r in rs) / len(rs)
        print(f"{st:<8}{len(rs):<12}{an:<9.1f}{ae:<11.4f}{aoe:<14.4f}")

    # D — IS vs OOS
    print("\n" + "=" * 104)
    print("D. PERBANDINGAN IS vs OOS (semua config dengan n>0)")
    print("=" * 104)
    print(f"{'thr':<6}{'step':<6}{'IS_exp':<11}{'OOS_exp':<11}{'beza':<11}{'tanda'}")
    print("-" * 55)
    for k, r in R.items():
        f = r.get("full", {})
        if not f.get("n"):
            continue
        ie = (r.get("is") or {}).get("expectancy_r", 0)
        oe = (r.get("oos") or {}).get("expectancy_r", 0)
        diff = oe - ie
        flag = "✅ OOS+" if oe > 0 else "❌ OOS−"
        print(f"{r['threshold']:<6}{r['step']:<6}{ie:<+11.4f}{oe:<+11.4f}"
              f"{diff:<+11.4f}{flag}")

    # E — XAUUSD
    print("\n" + "=" * 104)
    print("E. DIAGNOSTIK XAUUSD")
    print("=" * 104)
    print(f"{'thr':<6}{'step':<6}{'n':<6}{'WR%':<8}{'expR':<10}{'totR':<9}{'PF'}")
    print("-" * 50)
    for k, r in R.items():
        b = (r.get("by_symbol") or {}).get("XAUUSD") or {}
        if b.get("n"):
            print(f"{r['threshold']:<6}{r['step']:<6}{b['n']:<6}{b['win_rate']:<8}"
                  f"{b['expectancy_r']:+.4f}   {b['total_r']:+.1f}    {b['profit_factor']}")

    # G — kebolehpercayaan
    print("\n" + "=" * 104)
    print("G. PENILAIAN KEBOLEHPERCAYAAN STATISTIK")
    print("=" * 104)
    big = [(k, r) for k, r in R.items()
           if (r.get("oos") or {}).get("n", 0) >= 30]
    if big:
        print(f"Config dengan OOS n>=30: {len(big)}")
        for k, r in big:
            o = r["oos"]
            print(f"  {k}: OOS n={o['n']} exp={o['expectancy_r']:+.4f}R "
                  f"WR={o['win_rate']}% CI95={o['win_rate_ci95']}")
    else:
        print("❌ TIADA config dengan OOS n>=30 — sample terlalu kecil untuk")
        print("   sebarang kesimpulan statistik yang boleh dipercayai.")

    # coverage
    print("\n" + "=" * 104)
    print("COVERAGE (data UNAVAILABLE)")
    print("=" * 104)
    for sym, c in (d.get("coverage") or {}).items():
        print(f"  {sym:<8} coverage={c['coverage_score']} "
              f"unavailable={c['unavailable_groups']}")


if __name__ == "__main__":
    main()
