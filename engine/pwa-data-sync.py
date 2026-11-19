#!/usr/bin/env python3
"""PWA prototype data sync (pwa-app/).

Every 5 min (cron, flock):
  1. Copy the live public feeds (signal-status.json, landing-signal.json)
     from the repo root into pwa-app/data/ so the prototype shows the same
     numbers as the member dashboard. Atomic write (tmp + os.replace).
  2. Re-export the latest 120 M15 bars for XAUUSD / XAGUSD / BTCUSD from
     state/sq-bars.db (read-only) into pwa-app/data/bars-*.json.

Deliberately NOT synced:
  - landing-stats.json  -> internal feed, blocked by Caddy (stays private).
  - replay-*.json       -> historical demo snapshot, must stay frozen.

Stdlib only; safe to run manually: python3 engine/pwa-data-sync.py
"""
import json
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "pwa-app", "data")
BARS_DB = os.path.join(REPO, "state", "sq-bars.db")
FEEDS = ["signal-status.json", "landing-signal.json"]
CHART_PAIRS = [("XAUUSD", "xauusd"), ("XAGUSD", "xagusd"), ("BTCUSD", "btcusd")]
BAR_LIMIT = 120


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def sync_feeds():
    for name in FEEDS:
        src = os.path.join(REPO, name)
        dst = os.path.join(DATA, name)
        if not os.path.exists(src):
            print(f"skip {name}: source missing")
            continue
        with open(src) as f:
            obj = json.load(f)  # validate JSON before publishing
        atomic_write_json(dst, obj)
        print(f"synced {name}")


def export_bars():
    if not os.path.exists(BARS_DB):
        print("skip bars: sq-bars.db missing")
        return
    db = sqlite3.connect(f"file:{BARS_DB}?mode=ro", uri=True)
    try:
        for pair, slug in CHART_PAIRS:
            rows = db.execute(
                "SELECT ts,o,h,l,c FROM bars WHERE pair=? AND gran='M15' "
                "ORDER BY ts DESC LIMIT ?", (pair, BAR_LIMIT)
            ).fetchall()[::-1]
            if not rows:
                print(f"skip bars {pair}: no rows")
                continue
            updated = db.execute(
                "SELECT MAX(ts) FROM bars WHERE pair=? AND gran='M15'", (pair,)
            ).fetchone()[0]
            atomic_write_json(os.path.join(DATA, f"bars-{slug}.json"), {
                "pair": pair, "gran": "M15", "updated": updated,
                "source": "Swissquote/Coinbase collector (sq-bars.db)",
                "bars": [list(r) for r in rows],
            })
            print(f"exported bars-{slug}.json ({len(rows)} bars, updated {updated})")
    finally:
        db.close()


def main():
    os.makedirs(DATA, exist_ok=True)
    sync_feeds()
    export_bars()
    print("pwa-data-sync: done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"pwa-data-sync ERROR: {e}", file=sys.stderr)
        sys.exit(1)