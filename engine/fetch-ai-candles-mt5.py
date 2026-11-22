#!/usr/bin/env python3
"""Fetch M1 candles from MT5 (VPS) into the AI training cache.

Same cache format as fetch-ai-candles.py (TwelveData) so train-ai-model.py
reads either source unchanged: list of {datetime, open, high, low, close,
volume}. Data comes from the MT5 terminal via mt5_read.py (wine bridge) —
no API credits, no rate limit.

Usage:
  python3 engine/fetch-ai-candles-mt5.py --pairs all --bars 20000
  python3 engine/fetch-ai-candles-mt5.py --pairs XAG/USD,BTCUSD --bars 20000
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt5_read import run as mt5_run  # noqa: E402

CACHE = Path("/home/ubuntu/web/state/ai-m1")
# Focus pairs for Automation Trade. Key = engine pair label; value = MT5 symbol.
PAIRS = {"XAU/USD": "XAUUSD", "XAG/USD": "XAGUSD", "BTCUSD": "BTCUSD"}


def fetch(symbol, bars_wanted):
    # M15 bars: the model trains/serves on M15. Requesting M15 directly gives
    # deep history (MT5 M1 history is shallow); train-ai-model.to_m15 is then a
    # no-op and features are computed on the same timeframe the engine uses.
    out, err = mt5_run(["candles", symbol, "15min", str(bars_wanted)])
    if not out:
        print(f"  {symbol}: no output ({err[:120]})", flush=True)
        return []
    try:
        payload = json.loads(out)
    except Exception as e:
        print(f"  {symbol}: bad json ({e})", flush=True)
        return []
    if payload.get("error"):
        print(f"  {symbol}: {payload['error']}", flush=True)
        return []
    rows = []
    for b in payload.get("bars") or []:
        dt = datetime.fromtimestamp(int(b["t"]), tz=timezone.utc)
        rows.append({"datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                     "open": float(b["o"]), "high": float(b["h"]),
                     "low": float(b["l"]), "close": float(b["c"]),
                     "volume": int(b.get("v", 0))})
    rows.sort(key=lambda r: r["datetime"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="all")
    ap.add_argument("--bars", type=int, default=20000)
    args = ap.parse_args()
    targets = PAIRS if args.pairs == "all" else {
        p.strip(): PAIRS.get(p.strip(), p.strip().replace("/", ""))
        for p in args.pairs.split(",")}
    CACHE.mkdir(parents=True, exist_ok=True)
    for pair, symbol in targets.items():
        path = CACHE / f"{pair.replace('/', '')}_M1.json"
        print(f"{pair} ({symbol}): fetching up to {args.bars} M1 bars from MT5",
              flush=True)
        rows = fetch(symbol, args.bars)
        if not rows:
            print(f"{pair}: nothing fetched, cache untouched", flush=True)
            continue
        path.write_text(json.dumps(rows))
        print(f"{pair}: cached {len(rows)} bars "
              f"({rows[0]['datetime']} -> {rows[-1]['datetime']}) -> {path.name}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
