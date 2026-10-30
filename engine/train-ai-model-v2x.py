#!/usr/bin/env python3
"""Train the M15 Fully-AI model FEATURE VERSION 2.x: per-pair feature ablation.

v2 (13 dims: v1 core + H1 trend sign + POI distance + KL session one-hot x3 +
prior-20 R-mean + ATR percentile) helped GBP/EUR/NZD but hurt XAU/USD and
USD/JPY, so the full-v2 candidate was REJECTED (KEEP). v2x keeps the win per
pair: for each pair it tries feature subsets on the SAME 80/20 time-split
holdout with IDENTICAL labels/ticket, and picks the best subset per pair by
holdout pair log-loss (mean of long/short), requiring a minimum margin of
0.005 over v1 otherwise falling back to v1 for that pair.

Candidates (v2 indices: 0-4 v1 core, 5 h1_trend, 6 poi_dist, 7-9 KL one-hot,
10 rmean20, 11 atr_pctile, 12 bias):
  v1      = frozen ai_model.feature_row (8 dims, untouched)
  v1+h1   = v2[0,1,2,3,4,5,12]
  v1+poi  = v2[0,1,2,3,4,6,12]
  v1+kl   = v2[0,1,2,3,4,7,8,9,12]
  v1+r    = v2[0,1,2,3,4,10,12]
  v1+atrp = v2[0,1,2,3,4,11,12]
  v2full  = v2[0..12] (all 13)

Protocol (mirrors train-ai-model.py / train-ai-model-v2.py labels exactly):
  SL = max(1.5*ATR14, 12 pips), TP = 2*SL, 16-bar hold, ambiguous = loss,
  spread deducted, labels from M1 caches /home/ubuntu/web/state/ai-m1/*_M1.json.
Rows carry BOTH v1 and v2 features at identical (bar, label); every subset is
fit on the oldest 80% and scored on the newest 20% holdout. Metric functions
are imported from ai-calibration.py (single source of truth), labels/ticket
helpers from train-ai-model.py (imported, not duplicated).

Outputs:
  * always writes state/ai-m15-model-v2x.json (candidate artifact: per-pair
    chosen subset id + weights + selection table);
  * always writes state/ai-model-v2x-eval.json (full per-pair subset table);
  * overwrites state/ai-m15-model.json ONLY if aggregate sample-weighted
    holdout log-loss improves by >= 0.005 AND no single pair degrades by
    more than 0.02. Otherwise the deployed v1 file is left byte-identical
    (KEEP + reason). Any replaced file is first backed up as
    state/backup/ai-m15-model.json.<stamp>.

Deterministic: zero-init full-batch gradient descent, chronological split,
fixed pair order, fixed subset order. SEED = 0 documents the fixed point
(no RNG is used, so re-running on unchanged caches yields identical numbers).

Runtime note: the live engine (signal-engine-ai.py) currently calls
M.feature_row (v1 8-dim) for every pair. Pairs whose chosen subset is not
"v1" need a subset router mapping subset id -> feature constructor before a
promoted mixed-dim file can be consumed live. This script does NOT patch the
live engine; see payload["runtime_notes"].

Usage:
  python3 engine/train-ai-model-v2x.py
  python3 engine/train-ai-model-v2x.py --bars 1000

Never touches the live threshold (0.55), the LLM bot, services, or cron,
and never modifies v1 feature_row().
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "train_ai_model", HERE / "train-ai-model.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)

_cspec = importlib.util.spec_from_file_location(
    "ai_calibration", HERE / "ai-calibration.py")
C = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(C)

REPO = HERE.parent
M1DIR = Path("/home/ubuntu/web/state/ai-m1")
STATUS = REPO / "signal-status.json"
OUT_V2X = REPO / "state" / "ai-m15-model-v2x.json"
DEPLOYED = REPO / "state" / "ai-m15-model.json"
EVAL_OUT = REPO / "state" / "ai-model-v2x-eval.json"
BACKUP_DIR = REPO / "state" / "backup"

SEED = 0
THRESHOLD = 0.55
HOLDOUT_FRAC = 0.20
MIN_ROWS = 200
SELECT_MIN_MARGIN = 0.005   # subset must beat v1 by this LL margin to be chosen
PROMOTE_MIN_AGG_GAIN = 0.005
PROMOTE_MAX_PAIR_DEGRADE = 0.02

V1_FEATURE_NAMES = [
    "ema_gap_atr", "dist_ema20_atr", "rsi_norm", "rsi_slope", "atr_pips",
    "utc_flag_a", "utc_flag_b", "bias",
]

# subset id -> list of v2 indices; None means frozen v1 feature_row (8 dims).
SUBSETS = {
    "v1": None,
    "v1+h1": [0, 1, 2, 3, 4, 5, 12],
    "v1+poi": [0, 1, 2, 3, 4, 6, 12],
    "v1+kl": [0, 1, 2, 3, 4, 7, 8, 9, 12],
    "v1+r": [0, 1, 2, 3, 4, 10, 12],
    "v1+atrp": [0, 1, 2, 3, 4, 11, 12],
    "v2full": list(range(13)),
}
SUBSET_ORDER = ["v1", "v1+h1", "v1+poi", "v1+kl", "v1+r", "v1+atrp", "v2full"]


def subset_names(sid):
    if sid == "v1":
        return list(V1_FEATURE_NAMES)
    return [M.V2_FEATURE_NAMES[j] for j in SUBSETS[sid]]


def project(f2, sid):
    if sid == "v1":
        raise AssertionError("v1 uses feature_row, not projection")
    idx = SUBSETS[sid]
    return [f2[j] for j in idx]


def build_rows(pair, m1):
    """Rows carrying both v1 and v2 features at identical (bar, label)."""
    bars = T.to_m15(m1)
    closes = [b[3] for b in bars]
    e20, e50 = M.ema(closes, 20), M.ema(closes, 50)
    rsi, atr = M.rsi_s(closes), M.atr_s(bars)
    ctx = M.build_v2_ctx(pair, m1, STATUS if STATUS.exists() else None)
    rows = []
    for i in range(60, len(bars) - 1):
        f1 = M.feature_row(pair, bars, e20, e50, rsi, atr, i)
        if f1 is None:
            continue
        f2 = M.feature_row_v2(pair, bars, e20, e50, rsi, atr, i, ctx)
        if f2 is None:
            continue
        sl_b, tp_b = T.levels(pair, "BUY", closes[i], atr[i])
        sl_s, tp_s = T.levels(pair, "SELL", closes[i], atr[i])
        pl = T.resolve(bars, i, pair, "BUY", sl_b, tp_b)
        ps = T.resolve(bars, i, pair, "SELL", sl_s, tp_s)
        rows.append({"f1": f1, "f2": f2,
                     "y_long": 1 if pl > 0 else 0,
                     "y_short": 1 if ps > 0 else 0})
    return rows


def fit_subset(train_rows, sid, key):
    """Fit long/short weights for one subset on train rows. Deterministic."""
    if sid == "v1":
        sub = [{"f": r["f1"], "y_long": r["y_long"],
                "y_short": r["y_short"]} for r in train_rows]
    else:
        sub = [{"f": project(r["f2"], sid), "y_long": r["y_long"],
                "y_short": r["y_short"]} for r in train_rows]
    return M.fit(sub, key)


def predict_subset(model, row, sid):
    f = row["f1"] if sid == "v1" else project(row["f2"], sid)
    return M.predict(model, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0,
                    help="limit to the most recent N M15 rows (0 = all)")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    v2x_models, pairs_out, skipped = {}, {}, []
    agg_num_v1 = agg_num_ch = agg_den = 0.0
    for pair in T.PAIRS:
        m1 = T.load_m1(pair)
        if not m1:
            msg = "no cached M1"
            print(f"{pair:9} SKIP {msg}")
            skipped.append({"pair": pair, "reason": msg})
            continue
        rows_all = build_rows(pair, m1)
        if args.bars:
            rows_all = rows_all[-args.bars:]
        if len(rows_all) < MIN_ROWS:
            msg = f"only {len(rows_all)} rows (<{MIN_ROWS})"
            print(f"{pair:9} SKIP {msg}")
            skipped.append({"pair": pair, "reason": msg,
                            "n_rows": len(rows_all)})
            continue
        cut = int(len(rows_all) * (1 - HOLDOUT_FRAC))
        train_rows, hold = rows_all[:cut], rows_all[cut:]
        yl = [r["y_long"] for r in hold]
        ys = [r["y_short"] for r in hold]

        # Score every subset on the same holdout.
        scored = {}
        for sid in SUBSET_ORDER:
            wL, mL, sL = fit_subset(train_rows, sid, "y_long")
            wS, mS, sS = fit_subset(train_rows, sid, "y_short")
            mod = {"long": {"w": wL, "mu": mL, "sd": sL},
                   "short": {"w": wS, "mu": mS, "sd": sS}}
            mL_ = C.metrics(yl, [predict_subset(mod["long"], r, sid)
                                 for r in hold], gate=THRESHOLD)
            mS_ = C.metrics(ys, [predict_subset(mod["short"], r, sid)
                                 for r in hold], gate=THRESHOLD)
            pll = (mL_["logloss"] + mS_["logloss"]) / 2
            scored[sid] = {"model": mod, "long": mL_, "short": mS_,
                           "pair_logloss": pll}

        v1_ll = scored["v1"]["pair_logloss"]
        # Best non-v1 subset; needs min margin over v1, else fall back to v1.
        cands = sorted(((s["pair_logloss"], sid)
                        for sid, s in scored.items() if sid != "v1"))
        best_ll, best_sid = cands[0]
        if v1_ll - best_ll >= SELECT_MIN_MARGIN:
            chosen = best_sid
        else:
            chosen = "v1"
        ch_ll = scored[chosen]["pair_logloss"]

        entry_models = {"subset": chosen,
                        "feat_idx": ("v1-8dim" if chosen == "v1"
                                     else list(SUBSETS[chosen])),
                        "feature_names": subset_names(chosen),
                        "long": scored[chosen]["model"]["long"],
                        "short": scored[chosen]["model"]["short"]}
        v2x_models[pair] = entry_models

        subsets_out = {}
        for sid in SUBSET_ORDER:
            s = scored[sid]
            subsets_out[sid] = {
                "pair_logloss": round(s["pair_logloss"], 4),
                "delta_vs_v1": round(s["pair_logloss"] - v1_ll, 4),
                "long": s["long"], "short": s["short"],
            }
        pairs_out[pair] = {
            "n_train": len(train_rows), "n_holdout": len(hold),
            "chosen": chosen,
            "v1_pair_logloss": round(v1_ll, 4),
            "chosen_pair_logloss": round(ch_ll, 4),
            "delta_chosen_vs_v1": round(ch_ll - v1_ll, 4),
            "subsets": subsets_out,
        }
        for m in (scored["v1"]["long"], scored["v1"]["short"]):
            agg_num_v1 += m["logloss"] * m["n"]
            agg_den += m["n"]
        for m in (scored[chosen]["long"], scored[chosen]["short"]):
            agg_num_ch += m["logloss"] * m["n"]
        detail = " ".join(
            f"{sid}={scored[sid]['pair_logloss']:.4f}" for sid in SUBSET_ORDER)
        print(f"{pair:9} n_tr={len(train_rows):4} n_ho={len(hold):3} "
              f"chosen={chosen} d={ch_ll - v1_ll:+.4f} | {detail}",
              flush=True)

    if not pairs_out:
        print("no pairs trained; nothing written", file=sys.stderr)
        return 1

    agg_v1 = agg_num_v1 / agg_den
    agg_ch = agg_num_ch / agg_den
    gain = agg_v1 - agg_ch
    worst_degrade = max(v["delta_chosen_vs_v1"] for v in pairs_out.values())
    reasons = []
    if gain < PROMOTE_MIN_AGG_GAIN:
        reasons.append(
            f"aggregate gain {gain:+.4f} < +{PROMOTE_MIN_AGG_GAIN}")
    if worst_degrade > PROMOTE_MAX_PAIR_DEGRADE:
        bad = sorted((p, v["delta_chosen_vs_v1"]) for p, v in pairs_out.items()
                     if v["delta_chosen_vs_v1"] > PROMOTE_MAX_PAIR_DEGRADE)
        reasons.append(
            "per-pair degrade > +{:.3f}: {}".format(
                PROMOTE_MAX_PAIR_DEGRADE,
                ", ".join(f"{p} {d:+.4f}" for p, d in bad)))
    decision = "PROMOTE" if not reasons else "KEEP"
    reason = ("; ".join(reasons) if reasons
              else f"aggregate gain {gain:+.4f} "
              f">= +{PROMOTE_MIN_AGG_GAIN}, no pair "
              f"degrades > +{PROMOTE_MAX_PAIR_DEGRADE}")

    v2x_payload = {
        "version": "2.1",
        "features": "v2x",
        "timeframe": "M15",
        "trained_at": now.isoformat(timespec="seconds"),
        "seed": SEED,
        "gate_threshold": THRESHOLD,
        "selection": {"subsets": SUBSET_ORDER,
                      "select_min_margin": SELECT_MIN_MARGIN,
                      "holdout_frac": HOLDOUT_FRAC,
                      "min_rows": MIN_ROWS},
        "ticket": {"sl": f"max(1.5*ATR,{T.SCALP_MIN_SL_PIPS}p)",
                   "tp": f"{T.SCALP_RR}xSL",
                   "max_hold_bars": T.MAX_HOLD_BARS},
        "pairs": v2x_models,
        "holdout_eval": {"pairs": pairs_out, "skipped": skipped,
                         "agg_logloss_v1": round(agg_v1, 4),
                         "agg_logloss_v2x": round(agg_ch, 4),
                         "agg_gain": round(gain, 4),
                         "worst_pair_delta": round(worst_degrade, 4),
                         "decision": decision, "reason": reason},
        "runtime_notes": (
            "signal-engine-ai.py currently calls M.feature_row (v1 8-dim) "
            "for every pair. Pairs with chosen subset != 'v1' need a "
            "subset router (subset id -> feature constructor, see "
            "feat_idx/feature_names per pair) before a promoted mixed-dim "
            "file can be consumed live. This trainer does not patch the "
            "live engine."),
    }
    M.save_model(OUT_V2X, v2x_payload)
    print(f"saved {OUT_V2X} ({len(v2x_models)} pairs)")

    eval_payload = dict(v2x_payload["holdout_eval"])
    eval_payload.update({"updated": now.isoformat(timespec="seconds"),
                         "candidate_model": str(OUT_V2X),
                         "deployed_model": str(DEPLOYED)})
    EVAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVAL_OUT.write_text(json.dumps(eval_payload, indent=1))
    print(f"saved {EVAL_OUT}")

    print(f"AGG_LOGLOSS_V1={agg_v1:.4f} AGG_LOGLOSS_V2X={agg_ch:.4f} "
          f"GAIN={gain:+.4f} WORST_PAIR_DELTA={worst_degrade:+.4f}")
    if decision == "PROMOTE":
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        backup = None
        if DEPLOYED.exists():
            backup = BACKUP_DIR / f"ai-m15-model.json.{stamp}"
            backup.write_bytes(DEPLOYED.read_bytes())
            print(f"BACKUP={backup}")
        M.save_model(DEPLOYED, {**v2x_payload})
        print(f"DECISION=PROMOTE REASON={reason} MODEL_UPDATED={DEPLOYED}")
    else:
        print(f"DECISION=KEEP REASON={reason} "
              f"MODEL_UNCHANGED={DEPLOYED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
