#!/usr/bin/env python3
"""PWA data sync (pwa-app/ prototype + member/ app + root/ public app).

Every 5 min (cron, flock):
  1. Copy the live public feeds (signal-status.json, landing-signal.json)
      from the repo root into pwa-app/data/, member/data/ AND data/ (root
      app) so all three apps show the same numbers. Atomic write (tmp +
      os.replace).
  2. Re-export the latest 120 M15 bars for XAUUSD / XAGUSD / BTCUSD from
      the MT5 broker (RoboForex, engine/mt5_data.py) into all three data/
      dirs as bars-*.json. Fail closed: bridge down -> skip, keep last file.

Deliberately NOT synced:
  - landing-stats.json  -> internal feed, blocked by Caddy (stays private;
                           never written to any data/ dir).
  - replay-*.json       -> historical demo snapshot, must stay frozen.

Stdlib only; safe to run manually: python3 engine/pwa-data-sync.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mt5_data as M5

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = [
    os.path.join(REPO, "pwa-app", "data"),
    os.path.join(REPO, "member", "data"),
    os.path.join(REPO, "data"),
]
FEEDS = ["signal-status.json", "landing-signal.json"]
CHART_PAIRS = [("XAUUSD", "xauusd"), ("XAGUSD", "xagusd"), ("BTCUSD", "btcusd")]
BAR_LIMIT = 120
MT5_CMD = [
    "sudo", "-n", "-u", "mt5", "/usr/bin/env",
    "DISPLAY=:99", "WINEPREFIX=/home/mt5/.mt5",
    "/opt/wine-staging/bin/wine",
    "C:\\Python311\\python.exe", "C:\\mt5work\\mt5_pending.py",
]


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def sync_feeds():
    for name in FEEDS:
        src = os.path.join(REPO, name)
        if not os.path.exists(src):
            print(f"skip {name}: source missing")
            continue
        with open(src) as f:
            obj = json.load(f)  # validate JSON before publishing
        for data_dir in TARGETS:
            atomic_write_json(os.path.join(data_dir, name), obj)
            print(f"synced {os.path.relpath(os.path.join(data_dir, name), REPO)}")


def mt5_mid(pair):
    """(bid+ask)/2 dari broker MT5, atau None bila gagal."""
    try:
        req = json.dumps({"action": "tick", "symbol": pair})
        r = subprocess.run(MT5_CMD + [req], capture_output=True, text=True,
                           timeout=60, cwd="/tmp")
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            d = json.loads(line)
            if d.get("ok") and d.get("bid") and d.get("ask"):
                return round((float(d["bid"]) + float(d["ask"])) / 2.0, 5)
    except Exception:
        pass
    return None


def export_live_prices():
    """Tulis live-price.json (tick broker) ke semua data/ — harga padan MT5 client."""
    from datetime import datetime, timezone
    prices = {"updated": datetime.now(timezone.utc).isoformat(),
              "source": "MT5 broker tick (bid+ask)/2", "prices": {}}
    for pair, slug in CHART_PAIRS:
        mid = mt5_mid(pair)
        if mid is None:
            continue
        prices["prices"][slug] = mid
    if not prices["prices"]:
        print("skip live-price: MT5 tick unavailable")
        return
    for data_dir in TARGETS:
        atomic_write_json(os.path.join(data_dir, "live-price.json"), prices)
        print(f"exported {os.path.relpath(os.path.join(data_dir, 'live-price.json'), REPO)} "
              f"({len(prices['prices'])} pairs)")


def export_bars():
    for pair, slug in CHART_PAIRS:
        rows = M5.candles(pair, "M15", BAR_LIMIT)
        if not rows:
            print(f"skip bars {pair}: MT5 unavailable/no data (fail closed, keep last file)")
            continue
        bars = [[r["t"], r["o"], r["h"], r["l"], r["c"]] for r in rows]
        updated = bars[-1][0]
        payload = {
            "pair": pair, "gran": "M15", "updated": updated,
            "source": "MT5 broker (RoboForex)",
            "bars": bars,
        }
        for data_dir in TARGETS:
            dst = os.path.join(data_dir, f"bars-{slug}.json")
            atomic_write_json(dst, payload)
            print(f"exported {os.path.relpath(dst, REPO)} ({len(bars)} bars, updated {updated})")


def main():
    for data_dir in TARGETS:
        os.makedirs(data_dir, exist_ok=True)
    sync_feeds()
    export_bars()
    export_live_prices()
    print("pwa-data-sync: done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"pwa-data-sync ERROR: {e}", file=sys.stderr)
        sys.exit(1)