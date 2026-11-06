#!/usr/bin/env python3.12
"""Ujian sensitiviti penuh — 18 konfigurasi (6 threshold x 3 step).

SYARAT KETAT (dipatuhi):
  1. Logik entry/exit/SL/TP TIDAK diubah — guna bt.simulate + bt.net_r sedia ada.
  2. Kos dagangan TIDAK diubah — guna bt.trade_cost (spread+slippage).
  3. IS/OOS kronologi dikekalkan (bt.split_chrono 70/30).
  4. Tiada trade bertindih: satu trade per bar entry; kalau trade sebelumnya
     masih terbuka, langkau entry baharu pada symbol sama.
  5. Tiada optimasi atas OOS — semua config dilaporkan, tiada pemilihan automatik.
  6. Coverage dilaporkan berasingan (kumpulan UNAVAILABLE).
  7. XAUUSD disiasat berasingan.
  8. Setiap pair dibandingkan sendiri.
  9. CI + sample size disertakan (bt.wilson_ci).
 10. Versi config + dataset direkod.

Output: state/cf_sensitivity_full.json
Jalankan: /usr/bin/python3.12 engine/confluence/sensitivity_full.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.confluence import market_data as md                       # noqa: E402
from engine.confluence import pipeline as pl, backtest as bt           # noqa: E402

REPO = Path(__file__).resolve().parents[2]

PAIRS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"]
THRESHOLDS = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
STEPS = [10, 20, 30]
IS_FRAC = 0.70
EXPIRY_BARS = 16
SLIPPAGE_POINTS = 1.0
MIN_HISTORY = 300

CONFIG_VERSION = "cf-sens-v1.0"
STRATEGY_VERSION = pl.STRATEGY_VERSION
FEATURE_VERSION = pl.FEATURE_VERSION


# --------------------------------------------------------------- pengumpulan
def collect_pair(symbol, step):
    """Kumpul setup sah + simulasi trade. Cache bars/TF sekali per pair.

    Langkau entry bertindih: kalau trade sebelumnya masih terbuka pada bar
    entry seterusnya, JANGAN buka trade baharu (syarat #4).
    """
    bars = md.dedupe(md.load_bars(symbol, "M15"))
    if len(bars) < MIN_HISTORY + 200:
        return [], None
    cache = pl.build_tf_cache(bars)
    rows = []
    i = MIN_HISTORY
    last_exit_bar = -1
    coverage_seen = None
    while i < len(bars) - EXPIRY_BARS - 1:
        try:
            res = pl.analyze(symbol, bars=bars, i=i, tf_cache=cache)
        except Exception:
            i += step
            continue
        if coverage_seen is None:
            coverage_seen = (res["coverage_score"], res["unavailable_groups"],
                             res["active_groups"])
        s = res.get("setup") or {}
        if (s.get("valid") and s.get("side") and s.get("sl") and s.get("tp")
                and res["trigger"]["confirmed"] and res["gates"]["passed"]
                and i > last_exit_bar):
            tr = bt.simulate(bars, i, s["side"], s["entry"], s["sl"], s["tp"],
                             expiry_bars=EXPIRY_BARS)
            if tr:
                ec = bt.trade_cost(symbol, s["entry"], slippage_points=SLIPPAGE_POINTS)
                xc = bt.trade_cost(symbol, tr["exit"] or s["entry"],
                                   slippage_points=SLIPPAGE_POINTS)
                tr["net_r"] = bt.net_r(tr, symbol, s["entry"], s["sl"], ec, xc)
                tr.update({
                    "symbol": symbol, "bar": i, "side": s["side"],
                    "score": res["directional_score"],
                    "abs_score": abs(res["directional_score"]),
                    "regime": res["regime"],
                    "session": ((res.get("evidence", {}).get("session") or [{}])[0]
                                .get("name", ["?"]) or ["?"])[0],
                    "coverage": res["coverage_score"],
                })
                rows.append(tr)
                last_exit_bar = i + (tr.get("bars_held") or 0)
        i += step
    return rows, coverage_seen


def dataset_fingerprint():
    """Hash dataset untuk reproduksibiliti (syarat #10)."""
    h = hashlib.sha256()
    for s in PAIRS:
        p = md.HIST / f"{s}_M15.json"
        if p.exists():
            st = p.stat()
            h.update(f"{s}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:24]


# --------------------------------------------------------------- penilaian
def evaluate(rows, thr):
    """Tapis ikut threshold. Tiada perubahan logik trade."""
    sel = [r for r in rows if r["abs_score"] >= thr]
    sel.sort(key=lambda r: r["bar"])
    if not sel:
        return {"n": 0}
    is_r, oos_r = bt.split_chrono(sel, IS_FRAC)
    return {"full": bt.metrics(sel), "is": bt.metrics(is_r), "oos": bt.metrics(oos_r)}


def main():
    t0 = time.time()
    print(f"{'='*74}")
    print(f"Ujian sensitiviti penuh · config={CONFIG_VERSION}")
    print(f"threshold={THRESHOLDS}")
    print(f"step={STEPS}")
    print(f"pair={len(PAIRS)} · split IS/OOS={int(IS_FRAC*100)}/{int((1-IS_FRAC)*100)}")
    print(f"kos: spread ikut instrumen + slippage {SLIPPAGE_POINTS}pt")
    print(f"dataset_fingerprint={dataset_fingerprint()}")
    print(f"{'='*74}\n")

    # Cache pool: pengumpulan ambil ~12 minit. Simpan supaya boleh ulang
    # penilaian tanpa kumpul semula.
    cache_file = REPO / "state" / "cf_sensitivity_pool.json"
    fp = dataset_fingerprint()
    pools, coverage = {}, {}
    if cache_file.exists():
        try:
            c = json.loads(cache_file.read_text())
            if c.get("fingerprint") == fp:
                for k, v in c["pools"].items():
                    pair, st = k.rsplit("|", 1)
                    pools[(pair, int(st))] = v
                coverage = c.get("coverage", {})
                print(f"pool dimuat dari cache ({sum(len(v) for v in pools.values())} setup)")
        except Exception:
            pools = {}
    if not pools:
        for step in STEPS:
            for s in PAIRS:
                rows, cov = collect_pair(s, step)
                pools[(s, step)] = rows
                if cov:
                    coverage[s] = {"coverage_score": cov[0],
                                   "unavailable_groups": cov[1],
                                   "active_groups": cov[2]}
                print(f"  step={step:<3} {s:<8} {len(rows):>4} setup")
        cache_file.write_text(json.dumps({
            "fingerprint": fp,
            "pools": {f"{k[0]}|{k[1]}": v for k, v in pools.items()},
            "coverage": coverage}, indent=1))
        print(f"pool disimpan -> {cache_file}")
    print(f"\npengumpulan selesai: {time.time()-t0:.0f}s")

    # 18 konfigurasi
    results = {}
    print(f"\n{'thr':<6}{'step':<6}{'n':<6}{'WR%':<8}{'expR':<10}{'PF':<8}"
          f"{'totR':<8}{'maxDD':<8}{'IS_exp':<10}{'OOS_n':<7}{'OOS_exp':<10}")
    print("-" * 90)
    for thr in THRESHOLDS:
        for step in STEPS:
            pool = []
            for s in PAIRS:
                pool += pools[(s, step)]
            r = evaluate(pool, thr)
            key = f"thr{thr}_step{step}"
            if r.get("full", {}).get("n", 0) == 0:
                print(f"{thr:<6}{step:<6}0      —")
                results[key] = {"threshold": thr, "step": step, "n": 0}
                continue
            f, i, o = r["full"], r["is"], r["oos"]
            results[key] = {
                "threshold": thr, "step": step,
                "full": f, "is": i, "oos": o,
                "by_symbol": {s: bt.metrics([x for x in pool
                                             if x["symbol"] == s and x["abs_score"] >= thr])
                              for s in PAIRS},
                "by_regime": bt.breakdown(
                    [x for x in pool if x["abs_score"] >= thr], "regime"),
            }
            print(f"{thr:<6}{step:<6}{f['n']:<6}{f['win_rate']:<8}"
                  f"{f['expectancy_r']:+.4f}   {f['profit_factor']:<8}"
                  f"{f['total_r']:+.1f}    {f['max_dd_r']:<8}"
                  f"{i['expectancy_r']:+.4f}    {o['n']:<7}{o['expectancy_r']:+.4f}")

    out = {
        "config_version": CONFIG_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "feature_version": FEATURE_VERSION,
        "dataset_fingerprint": dataset_fingerprint(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": THRESHOLDS, "steps": STEPS, "pairs": PAIRS,
        "is_fraction": IS_FRAC, "expiry_bars": EXPIRY_BARS,
        "slippage_points": SLIPPAGE_POINTS,
        "coverage": coverage,
        "results": results,
        "elapsed_s": round(time.time() - t0, 1),
    }
    p = REPO / "state" / "cf_sensitivity_full.json"
    p.write_text(json.dumps(out, indent=1))
    print(f"\nDisimpan -> {p}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
