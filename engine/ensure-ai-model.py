#!/usr/bin/env python3
"""Make sure every traded pair has an AI model.

Runs before the session opens. If a pair is missing from the model file it
fetches that pair's M1 cache (paged) and retrains the whole model, then exits.
When the model is already complete it does nothing and costs zero credits, so
it is safe to leave on a daily cron.

Usage:
  python3 engine/ensure-ai-model.py
  python3 engine/ensure-ai-model.py --dry-run
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MODEL = REPO / "state" / "ai-m15-model.json"
CACHE = Path("/home/ubuntu/web/state/ai-m1")
PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"]
BARS = 15000


def have_model():
    if not MODEL.exists():
        return set()
    try:
        return set((json.loads(MODEL.read_text()).get("pairs") or {}).keys())
    except Exception:
        return set()


def cached(pair):
    p = CACHE / f"{pair.replace('/', '')}_M1.json"
    if not p.exists():
        return False
    try:
        return len(json.loads(p.read_text())) >= 5000
    except Exception:
        return False


def run(cmd, dry):
    print("+", " ".join(cmd), flush=True)
    if dry:
        return 0
    return subprocess.call(cmd)


def main():
    dry = "--dry-run" in sys.argv
    modelled = have_model()
    missing = [p for p in PAIRS if p not in modelled]
    if not missing:
        print("model complete for all pairs; nothing to do")
        return 0

    print(f"missing model: {missing}", flush=True)
    need_fetch = [p for p in missing if not cached(p)]
    if need_fetch:
        print(f"missing cache: {need_fetch}", flush=True)
        rc = run([sys.executable, str(HERE / "fetch-ai-candles.py"),
                  "--pairs", ",".join(need_fetch), "--bars", str(BARS)], dry)
        if rc != 0:
            print("fetch failed; model left unchanged", file=sys.stderr)
            return rc

    still = [p for p in missing if not cached(p)]
    if still:
        print(f"no usable cache for {still}; cannot train those pairs", file=sys.stderr)

    rc = run([sys.executable, str(HERE / "train-ai-model.py")], dry)
    if rc == 0 and not dry:
        print("model now covers:", sorted(have_model()), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
