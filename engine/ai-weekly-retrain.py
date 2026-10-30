#!/usr/bin/env python3
"""Weekly retrain gate for the M15 Fully-AI model.

  1. Snapshot the deployed model (state/ai-m15-model.json) as baseline.
  2. Re-run train-ai-model.py on the latest cached data.
  3. Run ai-calibration.py scoring the new model (candidate) against the
     baseline snapshot on the SAME newest-20% holdout per pair.
  4. Promote only if candidate aggregate holdout log-loss is strictly lower:
       PROMOTE -> keep new model, stash baseline as .bak-YYYYMMDD
       KEEP    -> byte-restore the baseline, model file left untouched.

Never touches live inference (signal-engine-ai.py), feature code
(ai_model.py), the LLM bot, services, or the 5-minute cron chain.

Usage:
  python3 engine/ai-weekly-retrain.py [--bars N]

Weekly cron (runs Mondays 01:17 UTC, outside session hours):
  17 1 * * 1 /usr/bin/python3.12 /home/ubuntu/web/Traderwatch-repo/engine/ai-weekly-retrain.py >> /tmp/ai-weekly-retrain.log 2>&1
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MODEL = REPO / "state" / "ai-m15-model.json"
CALIB = REPO / "state" / "ai-calibration.json"
CACHE_DIR = Path("/home/ubuntu/web/state/ai-m1")
TMP_BASE = Path("/tmp/ai-weekly-baseline.json")

PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
         "NZD/USD"]


def cache_status(pair):
    p = CACHE_DIR / f"{pair.replace('/', '')}_M1.json"
    if not p.exists():
        return "missing", 0, None
    try:
        raw = json.loads(p.read_text())
    except Exception:
        return "unreadable", 0, None
    if not raw:
        return "empty", 0, None
    try:
        last = str(raw[-1].get("datetime", ""))
    except Exception:
        last = "?"
    return "ok", len(raw), last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0,
                    help="most recent N M15 bars for retrain (0 = all)")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d")

    have_baseline = MODEL.exists()
    baseline_bytes = MODEL.read_bytes() if have_baseline else None
    if have_baseline:
        TMP_BASE.write_bytes(baseline_bytes)
        print(f"BASELINE_SNAPSHOT={TMP_BASE}", flush=True)
    else:
        print("BASELINE_SNAPSHOT=none (no deployed model yet)", flush=True)

    usable = 0
    for pair in PAIRS:
        st, n, last = cache_status(pair)
        print(f"CACHE pair={pair} status={st} n_m1={n} last={last}",
              flush=True)
        if st == "ok" and n >= 5000:
            usable += 1
    if usable == 0:
        print("DECISION=KEEP REASON=no_usable_cache", flush=True)
        return 0

    cmd = [sys.executable, str(HERE / "train-ai-model.py")]
    if args.bars:
        cmd += ["--bars", str(args.bars)]
    print("+" + " ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    if rc != 0:
        print(f"TRAIN_FAILED rc={rc}; model left unchanged", flush=True)
        if have_baseline:
            MODEL.write_bytes(baseline_bytes)
            print("MODEL_RESTORED=1", flush=True)
        return rc

    cmd = [sys.executable, str(HERE / "ai-calibration.py")]
    if args.bars:
        cmd += ["--bars", str(args.bars)]
    cmd += ["--model", str(MODEL)]
    if have_baseline:
        cmd += ["--compare", str(TMP_BASE)]
    print("+" + " ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    if rc != 0:
        print(f"CALIBRATION_FAILED rc={rc}; restoring baseline", flush=True)
        if have_baseline:
            MODEL.write_bytes(baseline_bytes)
            print("MODEL_RESTORED=1", flush=True)
        return rc

    try:
        calib = json.loads(CALIB.read_text())
    except Exception as e:
        print(f"CALIBRATION_UNREADABLE {e}; restoring baseline", flush=True)
        if have_baseline:
            MODEL.write_bytes(baseline_bytes)
            print("MODEL_RESTORED=1", flush=True)
        return 1
    decision = (calib.get("decision") or {}).get("verdict", "KEEP")
    reason = (calib.get("decision") or {}).get("reason", "?")
    agg = calib.get("aggregate") or {}
    print(f"CALIB_CAND_LOGLOSS={agg.get('mean_holdout_logloss_candidate')} "
          f"CALIB_BASE_LOGLOSS={agg.get('mean_holdout_logloss_baseline')} "
          f"CALIB_WF_LOGLOSS={agg.get('mean_holdout_logloss_walkforward')}",
          flush=True)

    if decision == "PROMOTE" and have_baseline:
        bak = MODEL.parent / f"ai-m15-model.json.bak-{stamp}"
        bak.write_bytes(baseline_bytes)
        print(f"DECISION=PROMOTE REASON={reason}", flush=True)
        print(f"BACKUP={bak}", flush=True)
        print(f"MODEL_UPDATED={MODEL}", flush=True)
    elif decision == "PROMOTE" and not have_baseline:
        print(f"DECISION=PROMOTE REASON={reason} (initial model)",
              flush=True)
        print(f"MODEL_CREATED={MODEL}", flush=True)
    else:
        if have_baseline:
            MODEL.write_bytes(baseline_bytes)
            print("MODEL_RESTORED=1", flush=True)
        print(f"DECISION=KEEP REASON={reason}", flush=True)
    try:
        TMP_BASE.unlink()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
