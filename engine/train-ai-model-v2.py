#!/usr/bin/env python3
"""Train the M15 Fully-AI model FEATURE VERSION 2 and gate its promotion.

v2 adds 5 SMC/session-aware features (see ai_model.feature_row_v2):
  H1 trend alignment, POI-proxy distance, KL session one-hot x3
  (replacing the v1 UTC flags), prior-20-trade R-mean, ATR percentile rank.

Protocol (mirrors train-ai-model.py labels exactly):
  SL = max(1.5*ATR14, 12 pips), TP = 2*SL, 16-bar hold, ambiguous = loss,
  spread deducted, labels from M1 caches /home/ubuntu/web/state/ai-m1/*_M1.json.

For each pair this script builds rows where BOTH v1 and v2 features exist
(identical timestamps, identical labels), splits 80/20 in time (no shuffle),
fits v1 weights and v2 weights on the oldest 80%, and evaluates BOTH on the
newest 20% holdout: per-pair log-loss, Brier, accuracy, precision/recall at
the 0.55 live gate, ECE. Metric functions are imported from ai-calibration.py
(single source of truth), not duplicated.

Promotion rule:
  * always writes state/ai-m15-model-v2.json (candidate artifact);
  * overwrites state/ai-m15-model.json ONLY if aggregate sample-weighted
    holdout log-loss improves by >= 0.005 AND no single pair degrades by
    more than 0.02 (per-pair LL = mean of long/short holdout log-loss).
    Otherwise the deployed v1 file is left byte-identical (KEEP + reason).
  * any replaced file is first backed up as state/backup/ai-m15-model.json.<stamp>.

Deterministic: zero-init full-batch gradient descent, chronological split,
fixed pair order. SEED = 0 documents the fixed point (no RNG is used, so
re-running on unchanged caches yields identical numbers).

Usage:
  python3 engine/train-ai-model-v2.py
  python3 engine/train-ai-model-v2.py --bars 1000

Never touches the live threshold (0.55), the LLM bot, services, or cron.
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
OUT_V2 = REPO / "state" / "ai-m15-model-v2.json"
DEPLOYED = REPO / "state" / "ai-m15-model.json"
EVAL_OUT = REPO / "state" / "ai-model-v2-eval.json"
BACKUP_DIR = REPO / "state" / "backup"

SEED = 0
THRESHOLD = 0.55
HOLDOUT_FRAC = 0.20
MIN_ROWS = 200
PROMOTE_MIN_AGG_GAIN = 0.005
PROMOTE_MAX_PAIR_DEGRADE = 0.02


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


def side_metrics(ys, ps):
    m = C.metrics(ys, ps, gate=THRESHOLD)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0,
                    help="limit to the most recent N M15 bars (0 = all)")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    v2_models, pairs_out, skipped = {}, {}, []
    agg_num_v1 = agg_num_v2 = agg_den = 0.0
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
            msg = f"only {len(rows_all)} v2 rows (<{MIN_ROWS})"
            print(f"{pair:9} SKIP {msg}")
            skipped.append({"pair": pair, "reason": msg,
                            "n_v2_rows": len(rows_all)})
            continue
        cut = int(len(rows_all) * (1 - HOLDOUT_FRAC))
        train_rows, hold = rows_all[:cut], rows_all[cut:]

        # Fit v1 and v2 on the same train split (v1 rows use f1, v2 use f2).
        t1 = [{"f": r["f1"], "y_long": r["y_long"],
               "y_short": r["y_short"]} for r in train_rows]
        t2 = [{"f": r["f2"], "y_long": r["y_long"],
               "y_short": r["y_short"]} for r in train_rows]
        wL1, mL1, sL1 = M.fit(t1, "y_long")
        wS1, mS1, sS1 = M.fit(t1, "y_short")
        wL2, mL2, sL2 = M.fit(t2, "y_long")
        wS2, mS2, sS2 = M.fit(t2, "y_short")
        v1 = {"long": {"w": wL1, "mu": mL1, "sd": sL1},
              "short": {"w": wS1, "mu": mS1, "sd": sS1}}
        v2 = {"long": {"w": wL2, "mu": mL2, "sd": sL2},
              "short": {"w": wS2, "mu": mS2, "sd": sS2}}
        v2_models[pair] = v2

        yl = [r["y_long"] for r in hold]
        ys = [r["y_short"] for r in hold]
        m1l = side_metrics(yl, [M.predict(v1["long"], r["f1"]) for r in hold])
        m1s = side_metrics(ys, [M.predict(v1["short"], r["f1"]) for r in hold])
        m2l = side_metrics(yl, [M.predict(v2["long"], r["f2"]) for r in hold])
        m2s = side_metrics(ys, [M.predict(v2["short"], r["f2"]) for r in hold])
        pair_ll_v1 = (m1l["logloss"] + m1s["logloss"]) / 2
        pair_ll_v2 = (m2l["logloss"] + m2s["logloss"]) / 2
        pairs_out[pair] = {
            "n_train": len(train_rows), "n_holdout": len(hold),
            "v1": {"long": m1l, "short": m1s,
                   "pair_logloss": round(pair_ll_v1, 4)},
            "v2": {"long": m2l, "short": m2s,
                   "pair_logloss": round(pair_ll_v2, 4)},
            "delta_logloss": round(pair_ll_v2 - pair_ll_v1, 4),
        }
        for m in (m1l, m1s):
            agg_num_v1 += m["logloss"] * m["n"]
            agg_den += m["n"]
        for m in (m2l, m2s):
            agg_num_v2 += m["logloss"] * m["n"]
        print(f"{pair:9} n_tr={len(train_rows):4} n_ho={len(hold):3} "
              f"V1 ll_L={m1l['logloss']:.4f} ll_S={m1s['logloss']:.4f} "
              f"acc_L={m1l['acc']:.3f} p_L={m1l['prec']:.3f} "
              f"r_L={m1l['rec']:.3f} brier_L={m1l['brier']:.4f} "
              f"ece_L={m1l['ece']:.4f} | "
              f"V2 ll_L={m2l['logloss']:.4f} ll_S={m2s['logloss']:.4f} "
              f"acc_L={m2l['acc']:.3f} p_L={m2l['prec']:.3f} "
              f"r_L={m2l['rec']:.3f} brier_L={m2l['brier']:.4f} "
              f"ece_L={m2l['ece']:.4f} | "
              f"dLL={pair_ll_v2 - pair_ll_v1:+.4f}", flush=True)

    if not pairs_out:
        print("no pairs trained; nothing written", file=sys.stderr)
        return 1

    agg_v1 = agg_num_v1 / agg_den
    agg_v2 = agg_num_v2 / agg_den
    gain = agg_v1 - agg_v2
    worst_degrade = max(v["delta_logloss"] for v in pairs_out.values())
    reasons = []
    if gain < PROMOTE_MIN_AGG_GAIN:
        reasons.append(
            f"aggregate gain {gain:+.4f} < +{PROMOTE_MIN_AGG_GAIN}")
    if worst_degrade > PROMOTE_MAX_PAIR_DEGRADE:
        bad = sorted((p, v["delta_logloss"]) for p, v in pairs_out.items()
                     if v["delta_logloss"] > PROMOTE_MAX_PAIR_DEGRADE)
        reasons.append(
            "per-pair degrade > +{:.3f}: {}".format(
                PROMOTE_MAX_PAIR_DEGRADE,
                ", ".join(f"{p} {d:+.4f}" for p, d in bad)))
    decision = "PROMOTE" if not reasons else "KEEP"
    reason = ("; ".join(reasons) if reasons
              else f"aggregate gain {gain:+.4f} "
              f">= +{PROMOTE_MIN_AGG_GAIN}, no pair "
              f"degrades > +{PROMOTE_MAX_PAIR_DEGRADE}")

    v2_payload = {
        "version": M.FEATURE_VERSION_V2,
        "features": "v2", "feature_names": M.V2_FEATURE_NAMES,
        "timeframe": "M15",
        "trained_at": now.isoformat(timespec="seconds"),
        "seed": SEED,
        "gate_threshold": THRESHOLD,
        "ticket": {"sl": f"max(1.5*ATR,{T.SCALP_MIN_SL_PIPS}p)",
                   "tp": f"{T.SCALP_RR}xSL",
                   "max_hold_bars": T.MAX_HOLD_BARS},
        "pairs": v2_models,
        "holdout_eval": {"pairs": pairs_out, "skipped": skipped,
                         "agg_logloss_v1": round(agg_v1, 4),
                         "agg_logloss_v2": round(agg_v2, 4),
                         "agg_gain": round(gain, 4),
                         "worst_pair_delta": round(worst_degrade, 4),
                         "decision": decision, "reason": reason},
    }
    M.save_model(OUT_V2, v2_payload)
    print(f"saved {OUT_V2} ({len(v2_models)} pairs)")

    eval_payload = dict(v2_payload["holdout_eval"])
    eval_payload.update({"updated": now.isoformat(timespec="seconds"),
                         "candidate_model": str(OUT_V2),
                         "deployed_model": str(DEPLOYED)})
    EVAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVAL_OUT.write_text(json.dumps(eval_payload, indent=1))

    print(f"AGG_LOGLOSS_V1={agg_v1:.4f} AGG_LOGLOSS_V2={agg_v2:.4f} "
          f"GAIN={gain:+.4f} WORST_PAIR_DELTA={worst_degrade:+.4f}")
    backup = None
    if decision == "PROMOTE":
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        if DEPLOYED.exists():
            backup = BACKUP_DIR / f"ai-m15-model.json.{stamp}"
            backup.write_bytes(DEPLOYED.read_bytes())
            print(f"BACKUP={backup}")
        M.save_model(DEPLOYED, {**v2_payload})
        print(f"DECISION=PROMOTE REASON={reason} MODEL_UPDATED={DEPLOYED}")
    else:
        print(f"DECISION=KEEP REASON={reason} "
              f"MODEL_UNCHANGED={DEPLOYED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
