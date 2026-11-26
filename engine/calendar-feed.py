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
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

MYT = timezone(timedelta(hours=8))
OUT = Path("/home/ubuntu/web/Traderwatch-repo/calendar.json")
CACHE = Path("/home/ubuntu/tw-bot/calendar-cache.json")
URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TV_URL = "https://economic-calendar.tradingview.com/events"
LOOKAHEAD_DAYS = 21  # 3 minggu kehadapan
TV_COUNTRIES = "US,EU,GB,JP,AU,CA,NZ,CH"
TV_CCY = {"US": "USD", "EU": "EUR", "GB": "GBP", "JP": "JPY", "AU": "AUD", "CA": "CAD", "NZ": "NZD", "CH": "CHF"}


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def _fmt_val(v, unit="", scale=None):
    if v is None or v == "":
        return ""
    s = str(v)
    if s.endswith(".0"):
        s = s[:-2]
    suf = str(unit or "")
    if scale == "K" and not suf.endswith("K"):
        suf = "K" + suf
    elif scale == "M" and not suf.endswith("M"):
        suf = "M" + suf
    elif scale == "B" and not suf.endswith("B"):
        suf = "B" + suf
    return f"{s}{suf}".strip()


def fetch_tradingview():
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=LOOKAHEAD_DAYS)
    qs = urllib.parse.urlencode({
        "from": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "countries": TV_COUNTRIES,
    })
    req = urllib.request.Request(
        f"{TV_URL}?{qs}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    rows = data.get("result") or []
    out = []
    for e in rows:
        imp = e.get("importance")
        impact = "High" if imp == 1 else ("Medium" if imp == 0 else "Low")
        ctry = str(e.get("country") or "").upper()
        ccy = str(e.get("currency") or TV_CCY.get(ctry) or ctry).upper()
        unit = e.get("unit") or ""
        scale = e.get("scale")
        out.append({
            "date": e.get("date") or "",
            "country": ccy,
            "title": e.get("title") or "",
            "impact": impact,
            "forecast": _fmt_val(e.get("forecast"), unit, scale),
            "previous": _fmt_val(e.get("previous"), unit, scale),
        })
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "TraderWatch/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read()
    if body.lstrip()[:1] not in (b"[", b"{"):
        raise ValueError("respons bukan JSON")
    data = json.loads(body)
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(body)
    except OSError:
        pass
    return data


def load_cache():
    age = datetime.now().timestamp() - CACHE.stat().st_mtime
    if age > 48 * 3600:
        raise RuntimeError(f"cache terlalu lama ({age/3600:.1f} jam)")
    return json.loads(CACHE.read_text())


def build(raw, source="TradingView 21d feed"):
    now = datetime.now(MYT)
    end = now + timedelta(days=LOOKAHEAD_DAYS)
    events = []
    for x in raw:
        try:
            when = datetime.fromisoformat(str(x["date"]).replace("Z", "+00:00")).astimezone(MYT)
        except Exception:
            continue
        if when <= now or when > end:
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
        "source": source,
        "lookahead_days": LOOKAHEAD_DAYS,
        "next_high": high[0] if high else None,
        "next_usd_high": usd_high[0] if usd_high else None,
        "upcoming_high": high[:24],
        "upcoming_usd_high": usd_high[:30],
        "counts": {"all_upcoming": len(events), "high": len(high), "usd_high": len(usd_high)},
    }


def main():
    raw, source = None, "TradingView 21d feed"
    try:
        raw = fetch_tradingview()
        log(f"tv feed OK: {len(raw)} events (21d)")
    except Exception as ex:
        log(f"tv feed FAIL: {type(ex).__name__}: {ex}")
        try:
            raw = fetch()
            source = "ForexFactory weekly feed"
            log(f"ff feed OK: {len(raw)} events")
        except Exception as ex2:
            log(f"ff feed FAIL: {type(ex2).__name__}: {ex2}")
            try:
                raw = load_cache()
                source = "cached feed"
                log(f"cache OK: {len(raw)} events")
            except Exception as ex3:
                log(f"cache FAIL: {ex3}")

    if raw is None:
        if OUT.exists():
            log("kekalkan calendar.json sedia ada (tiada data baharu)")
            return 0
        OUT.write_text(json.dumps({
            "generated_at": datetime.now(MYT).isoformat(),
            "source": "unavailable",
            "lookahead_days": LOOKAHEAD_DAYS,
            "next_high": None, "next_usd_high": None,
            "upcoming_high": [], "upcoming_usd_high": [],
            "counts": {"all_upcoming": 0, "high": 0, "usd_high": 0},
        }, indent=1))
        log("tulis calendar.json kosong (tiada cache)")
        return 0

    payload = build(raw, source=source)
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
