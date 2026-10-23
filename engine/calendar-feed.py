#!/usr/bin/env python3
"""Hasilkan calendar.json untuk dashboard ahli.

Sumber: ForexFactory weekly feed (sama seperti bot). Output ditulis ke repo
supaya GitHub Pages boleh membacanya tanpa CORS/proxy.

Gagal-selamat: jika feed gagal DAN cache lama, fail lama dikekalkan (tidak
dikosongkan) supaya dashboard tidak hilang data secara tiba-tiba.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

MYT = timezone(timedelta(hours=8))
OUT = Path("/home/ubuntu/web/Traderwatch-repo/calendar.json")
CACHE = Path("/home/ubuntu/tw-bot/calendar-cache.json")
URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "TraderWatch/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read()
    if body.lstrip()[:1] not in (b"[", b"{"):
        raise ValueError("respons bukan JSON")
    data = json.loads(body)
    CACHE.write_bytes(body)
    return data


def load_cache():
    age = datetime.now().timestamp() - CACHE.stat().st_mtime
    if age > 48 * 3600:
        raise RuntimeError(f"cache terlalu lama ({age/3600:.1f} jam)")
    return json.loads(CACHE.read_text())


def build(raw):
    now = datetime.now(MYT)
    events = []
    for x in raw:
        try:
            when = datetime.fromisoformat(x["date"]).astimezone(MYT)
        except Exception:
            continue
        if when <= now:
            continue
        events.append({
            "iso": when.isoformat(),
            "ccy": (x.get("country") or "").upper(),
            "title": x.get("title") or "",
            "impact": x.get("impact") or "",
            "forecast": x.get("forecast") or "",
            "previous": x.get("previous") or "",
        })
    events.sort(key=lambda e: e["iso"])

    high = [e for e in events if e["impact"] == "High"]
    usd_high = [e for e in high if e["ccy"] == "USD"]

    return {
        "generated_at": now.isoformat(),
        "source": "ForexFactory weekly feed",
        "next_high": high[0] if high else None,
        "next_usd_high": usd_high[0] if usd_high else None,
        "upcoming_high": high[:12],
        "counts": {"all_upcoming": len(events), "high": len(high), "usd_high": len(usd_high)},
    }


def main():
    raw, err = None, None
    try:
        raw = fetch()
        log(f"feed OK: {len(raw)} events")
    except Exception as ex:
        err = ex
        log(f"feed FAIL: {type(ex).__name__}: {ex}")
        try:
            raw = load_cache()
            log(f"cache OK: {len(raw)} events")
        except Exception as ex2:
            log(f"cache FAIL: {ex2}")

    if raw is None:
        if OUT.exists():
            log("kekalkan calendar.json sedia ada (tiada data baharu)")
            return 0
        OUT.write_text(json.dumps({
            "generated_at": datetime.now(MYT).isoformat(),
            "source": "unavailable",
            "next_high": None, "next_usd_high": None, "upcoming_high": [],
            "counts": {"all_upcoming": 0, "high": 0, "usd_high": 0},
        }, indent=1))
        log("tulis calendar.json kosong (tiada cache)")
        return 0

    payload = build(raw)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    tmp.replace(OUT)
    c = payload["counts"]
    nxt = payload["next_high"]
    log(f"wrote {OUT.name}: upcoming={c['all_upcoming']} high={c['high']} usd_high={c['usd_high']}")
    log(f"next_high={nxt['iso'] if nxt else None} {nxt['ccy'] if nxt else ''} {nxt['title'] if nxt else ''}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        log(f"FATAL {type(ex).__name__}: {ex}")
        sys.exit(1)
