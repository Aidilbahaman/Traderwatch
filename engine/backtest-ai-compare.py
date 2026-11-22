#!/usr/bin/env python3
"""Backtest perbandingan v1 vs v2 (win rate trading sebenar).

Untuk setiap pair fokus: bina fitur v1 (8-dim) & v2 (13-dim SMC/sesi) pada bar
M15 yang SAMA, split kronologi 80/20 (train/holdout, tiada lookahead), latih
model logistic berasingan, kemudian pada holdout simulasi strategi sebenar:
  side = argmax(p_long, p_short); fire jika conf >= gate;
  trade dengan ticket SL/TP; resolve outcome pada bar seterusnya.

Metrik: n_trades, win_rate, net_R, avg_R, profit_factor. Diuji pada beberapa
gate (0.30 / 0.40 / 0.50). v2 guna ctx H1+POI+sesi+ATR-percentile (R-mean
neutral 0 dalam backtest offline — fitur adaptif R tidak exercised).

Usage: python3 engine/backtest-ai-compare.py [--bars N]
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M  # noqa: E402

_spec = importlib.util.spec_from_file_location("train_ai_model", HERE / "train-ai-model.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)

GATES = [0.30, 0.40, 0.50]
HOLDOUT_FRAC = 0.20


def build_records(pair, bars):
    closes = [b[3] for b in bars]
    e20, e50 = M.ema(closes, 20), M.ema(closes, 50)
    rsi, atr = M.rsi_s(closes), M.atr_s(bars)
    ctx = M.build_v2_ctx(pair, bars, None)  # R-mean neutral (offline)
    recs = []
    for i in range(60, len(bars) - 1):
        f1 = M.feature_row(pair, bars, e20, e50, rsi, atr, i)
        f2 = M.feature_row_v2(pair, bars, e20, e50, rsi, atr, i, ctx)
        if f1 is None or f2 is None:
            continue
        a = atr[i]
        sl_b, tp_b = T.levels(pair, "BUY", closes[i], a)
        sl_s, tp_s = T.levels(pair, "SELL", closes[i], a)
        pl = T.resolve(bars, i, pair, "BUY", sl_b, tp_b)
        ps = T.resolve(bars, i, pair, "SELL", sl_s, tp_s)
        pip = M.pip_of(pair)
        recs.append({
            "i": i, "f1": f1, "f2": f2,
            "y_long": 1 if pl > 0 else 0, "y_short": 1 if ps > 0 else 0,
            "sl_b": sl_b, "tp_b": tp_b, "sl_s": sl_s, "tp_s": tp_s,
            "risk_b": abs(closes[i] - sl_b) / pip,
            "risk_s": abs(closes[i] - sl_s) / pip,
            "pl": pl, "ps": ps,
        })
    return recs


def trade_stats(recs, preds, gate, bars, pair):
    """preds: list of (p_long, p_short) aligned with recs."""
    n = wins = 0
    net_r = gross_win = gross_loss = 0.0
    for r, (pl, ps) in zip(recs, preds):
        conf = max(pl, ps)
        if conf < gate:
            continue
        side = "BUY" if pl >= ps else "SELL"
        if side == "BUY":
            res_pips = T.resolve(bars, r["i"], pair, "BUY", r["sl_b"], r["tp_b"])
            risk = r["risk_b"]
        else:
            res_pips = T.resolve(bars, r["i"], pair, "SELL", r["sl_s"], r["tp_s"])
            risk = r["risk_s"]
        R = res_pips / risk if risk > 0 else 0.0
        n += 1
        net_r += R
        if res_pips > 0:
            wins += 1
            gross_win += R
        else:
            gross_loss += abs(R)
    return {
        "n": n,
        "win_rate": round(wins / n * 100, 1) if n else 0.0,
        "net_R": round(net_r, 1),
        "avg_R": round(net_r / n, 3) if n else 0.0,
        "pf": round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0)
    args = ap.parse_args()
    results = {}
    for pair in T.PAIRS:
        m1 = T.load_m1(pair)
        if not m1:
            print(f"{pair}: SKIP no cache")
            continue
        bars = T.to_m15(m1)
        if args.bars:
            bars = bars[-args.bars:]
        recs = build_records(pair, bars)
        if len(recs) < 300:
            print(f"{pair}: SKIP only {len(recs)} records")
            continue
        cut = int(len(recs) * (1 - HOLDOUT_FRAC))
        train, hold = recs[:cut], recs[cut:]
        # train v1 (fit expects feature vector under key 'f')
        tr1 = [{"f": r["f1"], "y_long": r["y_long"], "y_short": r["y_short"]} for r in train]
        v1L = M.fit(tr1, "y_long"); v1S = M.fit(tr1, "y_short")
        m1L = {"w": v1L[0], "mu": v1L[1], "sd": v1L[2]}
        m1S = {"w": v1S[0], "mu": v1S[1], "sd": v1S[2]}
        # train v2 (reuse f2 as feature vector under key 'f')
        tr2 = [{"f": r["f2"], "y_long": r["y_long"], "y_short": r["y_short"]} for r in train]
        v2L = M.fit(tr2, "y_long"); v2S = M.fit(tr2, "y_short")
        m2L = {"w": v2L[0], "mu": v2L[1], "sd": v2L[2]}
        m2S = {"w": v2S[0], "mu": v2S[1], "sd": v2S[2]}
        p1 = [(M.predict(m1L, r["f1"]), M.predict(m1S, r["f1"])) for r in hold]
        p2 = [(M.predict(m2L, r["f2"]), M.predict(m2S, r["f2"])) for r in hold]
        print(f"\n=== {pair}  (train={len(train)} holdout={len(hold)} bars) ===")
        print(f"{'gate':>5} | {'v1 trades':>9} {'v1 WR%':>7} {'v1 netR':>8} {'v1 PF':>6} | "
              f"{'v2 trades':>9} {'v2 WR%':>7} {'v2 netR':>8} {'v2 PF':>6}")
        pair_res = {}
        for g in GATES:
            s1 = trade_stats(hold, p1, g, bars, pair)
            s2 = trade_stats(hold, p2, g, bars, pair)
            pair_res[g] = {"v1": s1, "v2": s2}
            print(f"{g:>5.2f} | {s1['n']:>9} {s1['win_rate']:>7} {s1['net_R']:>8} {s1['pf']:>6} | "
                  f"{s2['n']:>9} {s2['win_rate']:>7} {s2['net_R']:>8} {s2['pf']:>6}")
        results[pair] = pair_res
    # aggregate across pairs per gate
    print("\n=== AGGREGATE (all focus pairs) ===")
    print(f"{'gate':>5} | {'v1 trades':>9} {'v1 WR%':>7} {'v1 netR':>8} {'v1 PF':>6} | "
          f"{'v2 trades':>9} {'v2 WR%':>7} {'v2 netR':>8} {'v2 PF':>6}")
    agg = {}
    for g in GATES:
        def tot(ver):
            n = sum(results[p][g][ver]["n"] for p in results)
            wr = sum(results[p][g][ver]["win_rate"] * results[p][g][ver]["n"] for p in results)
            net = sum(results[p][g][ver]["net_R"] for p in results)
            return n, (wr / n if n else 0), net
        n1, wr1, net1 = tot("v1"); n2, wr2, net2 = tot("v2")
        agg[g] = {"v1": {"n": n1, "win_rate": round(wr1, 1), "net_R": round(net1, 1)},
                  "v2": {"n": n2, "win_rate": round(wr2, 1), "net_R": round(net2, 1)}}
        print(f"{g:>5.2f} | {n1:>9} {wr1:>7.1f} {net1:>8.1f} {'':>6} | "
              f"{n2:>9} {wr2:>7.1f} {net2:>8.1f} {'':>6}")
    out = HERE.parent / "state" / "ai-v1-v2-backtest.json"
    out.write_text(json.dumps({"pairs": results, "aggregate": agg}, indent=1))
    print(f"\nSAVED={out}")


if __name__ == "__main__":
    raise SystemExit(main())
