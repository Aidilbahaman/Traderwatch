#!/usr/bin/env python3
"""Walk-forward calibration for the M15 Fully-AI model.

For each pair: build feature/label rows with the EXACT ticket pipeline from
train-ai-model.py (imported, not duplicated), fit a fresh model on the older
80% of rows, and evaluate on the newest 20% holdout. Also scores a candidate
model file and (optionally) a baseline model file on the SAME holdout, so the
weekly retrain job can make a promote/keep decision.

Metrics per side (long/short): log-loss, Brier, accuracy / precision / recall
at the 0.55 live gate, ECE (10-bin), plus base rate and holdout size.
Aggregate = sample-weighted mean holdout log-loss across pairs and sides.

Deterministic: chronological split, zero-init full-batch fit, fixed pair
order. Re-running on unchanged caches yields identical numbers.

Usage:
  python3 engine/ai-calibration.py
  python3 engine/ai-calibration.py --bars 5000
  python3 engine/ai-calibration.py --model state/ai-m15-model.json
  python3 engine/ai-calibration.py --model /tmp/candidate.json --compare state/ai-m15-model.json

Writes state/ai-calibration.json and prints plain KEY=val lines.
"""
import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M  # noqa: E402

# Single source of truth for bars/labels/ticket: reuse train-ai-model.py.
_spec = importlib.util.spec_from_file_location(
    "train_ai_model", HERE / "train-ai-model.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)

REPO = HERE.parent
OUT = REPO / "state" / "ai-calibration.json"
DEPLOYED = REPO / "state" / "ai-m15-model.json"

PAIRS = T.PAIRS
THRESHOLD = 0.55
HOLDOUT_FRAC = 0.20
MIN_ROWS = 200
STALE_DAYS = 30.0
EPS = 1e-12
N_BINS = 10


def metrics(ys, ps, gate=THRESHOLD):
    n = len(ys)
    if n == 0:
        return {"n": 0}
    pc = [min(max(p, EPS), 1 - EPS) for p in ps]
    ll = -sum(y * math.log(p) + (1 - y) * math.log(1 - p)
              for y, p in zip(ys, pc)) / n
    brier = sum((p - y) ** 2 for y, p in zip(ys, ps)) / n
    pred = [1 if p >= gate else 0 for p in ps]
    tp = sum(1 for y, q in zip(ys, pred) if y == 1 and q == 1)
    tn = sum(1 for y, q in zip(ys, pred) if y == 0 and q == 0)
    fp = sum(1 for y, q in zip(ys, pred) if y == 0 and q == 1)
    fn = sum(1 for y, q in zip(ys, pred) if y == 1 and q == 0)
    ece_num, ece_den = 0.0, 0
    for b in range(N_BINS):
        lo, hi = b / N_BINS, (b + 1) / N_BINS
        idx = [i for i, p in enumerate(ps)
               if (lo <= p < hi) or (hi == 1.0 and p == hi)]
        if not idx:
            continue
        acc = sum(ys[i] for i in idx) / len(idx)
        conf = sum(ps[i] for i in idx) / len(idx)
        ece_num += abs(acc - conf) * len(idx)
        ece_den += len(idx)
    ece = ece_num / ece_den if ece_den else 0.0
    return {"n": n, "logloss": round(ll, 4), "brier": round(brier, 4),
            "acc": round((tp + tn) / n, 4),
            "prec": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
            "rec": round(tp / (tp + fn), 4) if (tp + fn) else 0.0,
            "ece": round(ece, 4), "n_pred_pos": tp + fp,
            "base_rate": round(sum(ys) / n, 4)}


def eval_stored(stored_pairs, pair, holdout):
    """Score a stored model payload on holdout rows; None if pair absent."""
    entry = (stored_pairs or {}).get(pair)
    if not entry or not entry.get("long") or not entry.get("short"):
        return None
    return {
        "long": metrics([r["y_long"] for r in holdout],
                        [M.predict(entry["long"], r["f"]) for r in holdout]),
        "short": metrics([r["y_short"] for r in holdout],
                         [M.predict(entry["short"], r["f"]) for r in holdout]),
    }


def build_rows(pair, bars):
    closes = [b[3] for b in bars]
    e20, e50 = M.ema(closes, 20), M.ema(closes, 50)
    rsi, atr = M.rsi_s(closes), M.atr_s(bars)
    rows = []
    for i in range(60, len(bars) - 1):
        f = M.feature_row(pair, bars, e20, e50, rsi, atr, i)
        if f is None:
            continue
        sl_b, tp_b = T.levels(pair, "BUY", closes[i], atr[i])
        sl_s, tp_s = T.levels(pair, "SELL", closes[i], atr[i])
        pl = T.resolve(bars, i, pair, "BUY", sl_b, tp_b)
        ps = T.resolve(bars, i, pair, "SELL", sl_s, tp_s)
        rows.append({"f": f,
                     "y_long": 1 if pl > 0 else 0,
                     "y_short": 1 if ps > 0 else 0})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0,
                    help="limit to the most recent N M15 bars (0 = all)")
    ap.add_argument("--model", default=str(DEPLOYED),
                    help="candidate model file to score on the holdout")
    ap.add_argument("--compare", default="",
                    help="baseline model file for promote/keep comparison")
    args = ap.parse_args()

    try:
        cand_pairs = (json.loads(Path(args.model).read_text()).get("pairs")
                      or {})
    except Exception as e:
        print(f"ERROR cannot load candidate model {args.model}: {e}")
        return 1
    base_pairs = None
    if args.compare:
        try:
            base_pairs = (json.loads(Path(args.compare).read_text())
                          .get("pairs") or {})
        except Exception as e:
            print(f"ERROR cannot load baseline model {args.compare}: {e}")
            return 1

    now = datetime.now(timezone.utc)
    pairs_out = {}
    n_eval = 0
    for pair in PAIRS:
        m1 = T.load_m1(pair)
        if not m1:
            print(f"PAIR={pair} STATUS=SKIP REASON=no_M1_cache")
            pairs_out[pair] = {"status": "SKIP", "reason": "no_M1_cache"}
            continue
        bars = T.to_m15(m1)
        if args.bars:
            bars = bars[-args.bars:]
        age_days = (now.timestamp() * 1000 - bars[-1][0]) / 86400000
        if age_days > STALE_DAYS:
            print(f"PAIR={pair} STATUS=SKIP REASON=stale_cache "
                  f"AGE_DAYS={age_days:.1f}")
            pairs_out[pair] = {"status": "SKIP", "reason": "stale_cache",
                               "cache_age_days": round(age_days, 1)}
            continue
        rows = build_rows(pair, bars)
        if len(rows) < MIN_ROWS:
            print(f"PAIR={pair} STATUS=SKIP REASON=too_few_rows N={len(rows)}")
            pairs_out[pair] = {"status": "SKIP", "reason": "too_few_rows",
                               "n_rows": len(rows)}
            continue
        cut = int(len(rows) * (1 - HOLDOUT_FRAC))
        train_rows, holdout = rows[:cut], rows[cut:]

        wL, mL, sL = M.fit(train_rows, "y_long")
        wS, mS, sS = M.fit(train_rows, "y_short")
        wf = {
            "long": metrics(
                [r["y_long"] for r in holdout],
                [M.predict({"w": wL, "mu": mL, "sd": sL}, r["f"])
                 for r in holdout]),
            "short": metrics(
                [r["y_short"] for r in holdout],
                [M.predict({"w": wS, "mu": mS, "sd": sS}, r["f"])
                 for r in holdout]),
        }
        cand_m = eval_stored(cand_pairs, pair, holdout)
        base_m = (eval_stored(base_pairs, pair, holdout)
                  if base_pairs is not None else None)
        n_eval += 1
        pairs_out[pair] = {"status": "OK", "n_train": len(train_rows),
                           "n_holdout": len(holdout),
                           "cache_age_days": round(age_days, 2),
                           "walkforward": wf, "candidate": cand_m,
                           "baseline": base_m}
        line = (f"PAIR={pair} N_TRAIN={len(train_rows)} "
                f"N_HOLDOUT={len(holdout)} "
                f"WF_LOGLOSS_L={wf['long']['logloss']} "
                f"WF_LOGLOSS_S={wf['short']['logloss']} "
                f"WF_BRIER_L={wf['long']['brier']} "
                f"WF_ACC_L={wf['long']['acc']} "
                f"WF_PREC_L={wf['long']['prec']} "
                f"WF_REC_L={wf['long']['rec']} "
                f"WF_ECE_L={wf['long']['ece']}")
        if cand_m:
            line += (f" CAND_LOGLOSS_L={cand_m['long']['logloss']} "
                     f"CAND_LOGLOSS_S={cand_m['short']['logloss']}")
        if base_m:
            line += (f" BASE_LOGLOSS_L={base_m['long']['logloss']} "
                     f"BASE_LOGLOSS_S={base_m['short']['logloss']}")
        print(line, flush=True)

    def wmean(key_path):
        num, den = 0.0, 0
        for info in pairs_out.values():
            if info.get("status") != "OK":
                continue
            for side in ("long", "short"):
                node = info
                for k in key_path + [side]:
                    node = (node or {}).get(k)
                if node is None:
                    return None
                num += node["logloss"] * node["n"]
                den += node["n"]
        return round(num / den, 4) if den else None

    agg = {"pairs_evaluated": n_eval,
           "mean_holdout_logloss_walkforward": wmean(["walkforward"]),
           "mean_holdout_logloss_candidate": wmean(["candidate"]),
           "mean_holdout_logloss_baseline": wmean(["baseline"])}
    agg["n_holdout_predictions"] = sum(
        info["n_holdout"] * 2 for info in pairs_out.values()
        if info.get("status") == "OK")

    decision = {"metric": "aggregate_holdout_logloss"}
    if n_eval == 0:
        decision.update(verdict="KEEP", reason="no_pairs_evaluated")
    elif agg["mean_holdout_logloss_candidate"] is None:
        decision.update(verdict="KEEP", reason="candidate_missing_all_pairs")
    elif agg["mean_holdout_logloss_baseline"] is None:
        decision.update(verdict="KEEP", reason="no_baseline_given")
    elif (agg["mean_holdout_logloss_candidate"]
            < agg["mean_holdout_logloss_baseline"]):
        decision.update(verdict="PROMOTE",
                        reason="candidate_holdout_logloss_lower")
    else:
        decision.update(verdict="KEEP",
                        reason="candidate_not_better_on_holdout")

    print(f"AGG_PAIRS={n_eval} "
          f"AGG_WF_LOGLOSS={agg['mean_holdout_logloss_walkforward']} "
          f"AGG_CAND_LOGLOSS={agg['mean_holdout_logloss_candidate']} "
          f"AGG_BASE_LOGLOSS={agg['mean_holdout_logloss_baseline']} "
          f"DECISION={decision['verdict']} REASON={decision['reason']}",
          flush=True)
    payload = {"updated": now.isoformat(timespec="seconds"),
               "threshold": THRESHOLD, "holdout_frac": HOLDOUT_FRAC,
               "bars_limit": args.bars,
               "candidate_model": args.model,
               "baseline_model": args.compare or None,
               "pairs": pairs_out, "aggregate": agg, "decision": decision}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"CALIBRATION_SAVED={OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
