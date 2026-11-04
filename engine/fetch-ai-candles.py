#!/usr/bin/env python3
"""Fetch M1 candles into the local cache used for AI model training.

Pulls 5000 bars per request and pages backwards until the requested depth is
reached. Cache is written once per pair and never refetched inside a sweep, so
a retrain costs zero API credits.

Usage:
  python3 engine/fetch-ai-candles.py --pairs NZD/USD --bars 15000
  python3 engine/fetch-ai-candles.py --pairs all --bars 15000
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path("/home/ubuntu/web/state/ai-m1")
PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"]
PAGE = 5000
GAP = 9


def load_secrets(name):
    vals = {}
    for line in (Path.home() / ".secrets" / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def get(url):
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "tw-cache/1.0"}),
                    timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:160]
            if e.code == 429 and attempt == 1:
                print(f"  rate limit, wait 62s", flush=True)
                time.sleep(62)
                continue
            return {"code": e.code, "message": body}
        except Exception as e:
            return {"code": -1, "message": str(e)[:120]}
    return {"code": 429, "message": "rate limit persisted"}


def fetch(pair, key, bars_wanted):
    got = {}
    end = None
    while len(got) < bars_wanted:
        params = {"symbol": pair, "interval": "1min", "outputsize": PAGE,
                  "apikey": key, "timezone": "UTC"}
        if end:
            params["end_date"] = end
        url = "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params)
        data = get(url)
        if data.get("code") or data.get("status") == "error":
            print(f"  stop: {str(data.get('message'))[:110]}", flush=True)
            break
        vals = data.get("values") or []
        if not vals:
            break
        for v in vals:
            got[v["datetime"]] = v
        oldest = min(v["datetime"] for v in vals)
        d = datetime.fromisoformat(oldest).replace(tzinfo=timezone.utc)
        end = (d - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  page -> {len(got)} bars (oldest {oldest})", flush=True)
        if len(vals) < PAGE:
            break
        time.sleep(GAP)
    out = [got[k] for k in sorted(got)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="all")
    ap.add_argument("--bars", type=int, default=15000)
    args = ap.parse_args()

    key = load_secrets("twelve.env").get("TWELVEDATA_API_KEY", "")
    if not key:
        print("no TWELVEDATA_API_KEY", file=sys.stderr)
        return 1

    targets = PAIRS if args.pairs == "all" else [p.strip() for p in args.pairs.split(",")]
    CACHE.mkdir(parents=True, exist_ok=True)
    for pair in targets:
        path = CACHE / f"{pair.replace('/', '')}_M1.json"
        print(f"{pair}: fetching up to {args.bars} M1 bars", flush=True)
        rows = fetch(pair, key, args.bars)
        if not rows:
            print(f"{pair}: nothing fetched, cache untouched", flush=True)
            continue
        path.write_text(json.dumps(rows))
        print(f"{pair}: cached {len(rows)} bars -> {path.name}", flush=True)
        time.sleep(GAP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
