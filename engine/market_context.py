"""Konteks pasaran untuk analyst — apa yang carta SAHAJA tidak beritahu.

Setiap fungsi murah (cache) dan fail-safe: jika data tiada, pulangkan None
supaya prompt tidak dirosakkan dengan teks kosong/mengarut.

Hakikat: LLM yang hanya nampak imej candle akan buat kesilapan yang trader
manusia tidak buat — masuk 10 minit sebelum NFP, atau trade XAU semasa London
padahal data kita tunjuk London rugi. Modul ini menutup jurang itu.
"""
import json
import pathlib
import time
import urllib.request
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parent.parent
CAL_CACHE = REPO / "state" / "calendar-feed.json"
CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

_cal = {"at": 0.0, "events": None}
CAL_TTL = 3600


def _fetch_calendar():
    """Ambil kalendar ekonomi (ForexFactory weekly). Cache 1 jam."""
    now = time.time()
    if _cal["events"] is not None and now - _cal["at"] < CAL_TTL:
        return _cal["events"]
    raw = None
    try:
        req = urllib.request.Request(CAL_URL, headers={"User-Agent": "TraderWatch/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
        if body.lstrip()[:1] in (b"[", b"{"):
            raw = json.loads(body)
            try:
                CAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
                CAL_CACHE.write_bytes(body)
            except OSError:
                pass
    except Exception:
        raw = None
    if raw is None:
        # fallback: cache lama (jika ada)
        try:
            age = time.time() - CAL_CACHE.stat().st_mtime
            if age < 72 * 3600:
                raw = json.loads(CAL_CACHE.read_text())
        except Exception:
            raw = None
    events = []
    for x in raw or []:
        if str(x.get("impact") or "") != "High":
            continue
        try:
            when = datetime.fromisoformat(str(x.get("date"))).astimezone(timezone.utc)
        except Exception:
            continue
        events.append({"at": when, "ccy": (x.get("country") or "").upper(),
                       "title": (x.get("title") or "")[:60],
                       "forecast": str(x.get("forecast") or ""),
                       "previous": str(x.get("previous") or "")})
    events.sort(key=lambda e: e["at"])
    _cal.update(at=now, events=events)
    return events


def news_risk(pair, hours_ahead=6, hours_before=1, hours_after=2):
    """Berita High-impact untuk matawang pair ini + USD (sentimen global).

    Return dict {blocked, reason, upcoming: [...]} atau None jika tiada data.
    """
    events = _fetch_calendar()
    if events is None:
        return None
    p = str(pair).upper().replace("/", "")
    cur = {p[:3], p[3:6]}
    if p.endswith("USD"):
        cur.add("USD")
    if p.startswith("XAU") or p.startswith("XAG"):
        cur.add("USD")   # logam dipacu USD
    now = datetime.now(timezone.utc)
    rel = []
    for e in events:
        if e["ccy"] not in cur:
            continue
        mins = (e["at"] - now).total_seconds() / 60.0
        if -hours_after * 60 <= mins <= hours_ahead * 60:
            rel.append({"mins": round(mins), "ccy": e["ccy"], "title": e["title"],
                        "forecast": e["forecast"], "previous": e["previous"]})
    # sekat jika berita High dalam tetingkap bahaya
    danger = [r for r in rel if -hours_after * 60 <= r["mins"] <= hours_before * 60]
    if danger:
        d = danger[0]
        when = (f"in {-d['mins']} min" if d["mins"] > 0 else
                f"{-d['mins']} min ago")
        return {"blocked": True,
                "reason": f"High-impact {d['ccy']} {d['title']} {when}",
                "upcoming": rel[:3]}
    return {"blocked": False, "reason": "", "upcoming": rel[:3]}


def session_info(hour_utc=None):
    """Sesi semasa + kualiti ikut data backtest (780 trade)."""
    h = hour_utc if hour_utc is not None else datetime.now(timezone.utc).hour
    if 7 <= h < 12:
        name, quality = "London", "good"
    elif 12 <= h < 17:
        name, quality = "London/New York overlap", "best"
    elif 17 <= h < 21:
        name, quality = "New York", "ok"
    else:
        name, quality = "Asia", "ok"
    return {"hour": h, "name": name, "quality": quality}


def format_context(pair, tf, hour_utc=None, lessons="", calibration=""):
    """Bina blok teks konteks untuk disuntik ke prompt. Fail-safe."""
    lines = []
    s = session_info(hour_utc)
    lines.append(f"Session: {s['name']} (UTC {s['hour']:02d}:00) — liquidity quality: {s['quality']}.")

    n = news_risk(pair)
    if n is not None:
        if n["blocked"]:
            lines.append(f"NEWS RISK — DO NOT ENTER: {n['reason']}. "
                         "Spread widens and stop-hunts are common around releases; HOLD.")
        elif n["upcoming"]:
            ups = "; ".join(f"{u['ccy']} {u['title']} in {u['mins']}m" for u in n["upcoming"][:2])
            lines.append(f"Upcoming high-impact news: {ups}. Avoid opening right before it.")
        else:
            lines.append("No high-impact news for this pair in the next 6 hours.")
    else:
        lines.append("Economic calendar unavailable — rely on technicals only.")

    # Konteks USD (DXY sintetik) — penting untuk logam, tiada untuk yang lain.
    try:
        import usd_context as UC
        u = UC.usd_context(pair)
        if u:
            lines.append(u)
    except Exception:
        pass

    if lessons:
        lines.append("PROVEN/AVOID from real client outcomes: " + lessons)
    if calibration:
        lines.append(calibration)
    return "\n".join(lines)
