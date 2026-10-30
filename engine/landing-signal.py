#!/usr/bin/env python3
"""Generate public landing-signal.json for traderwatch.org hero setups card.

Runs right after engine/signal-status.py in the same 5-minute cron (chained),
or standalone: python3 landing-signal.py
Anonymous-public payload only: pair, side, timeframe, levels, status.
Never includes member data, chat ids, or broker state.
"""
import json
import pathlib
import urllib.request

REPO = pathlib.Path("/home/ubuntu/web/Traderwatch-repo")
OUT = REPO / "landing-signal.json"
ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")

def load_env():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec

def fetch_latest():
    sec = load_env()
    url = sec["SUPABASE_URL"].rstrip("/")
    key = sec["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(
        url + "/rest/v1/signals?select=id,pair,side,entry,sl,tp,timeframe,posted_at&order=posted_at.desc&limit=1",
        headers={"apikey": key, "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        rows = json.loads(r.read())
    return rows[0] if rows else None

def status_of(pair, sid, posted_at):
    """Match by signal_id first (robust); fallback to MYT timestamp key."""
    f = REPO / "signal-status.json"
    try:
        d = json.loads(f.read_text())
        sigs = d.get("signals") or {}
        for k, v in sigs.items():
            if v.get("signal_id") == sid:
                return v.get("status") or "active"
        # Fallback: keys are MYT (UTC+8) — convert posted_at before matching.
        import datetime
        t = datetime.datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        myt = t.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        key = f"{pair.replace('/', '')}_{myt.strftime('%Y%m%d_%H%M%S')}"
        v = sigs.get(key)
        if v:
            return v.get("status") or "active"
    except Exception:
        pass
    return "active"

def posted_key(ts):
    # posted_at '2026-10-30T04:07:11.794373' is UTC; status keys use UTC too.
    return ts[:4] + ts[5:7] + ts[8:10] + ts[11:13] + ts[14:16] + ts[17:19]

def main():
    try:
        row = fetch_latest()
        if not row:
            raise SystemExit("no signals")
        pair = row.get("pair") or ""
        key = f"{pair.replace('/', '')}_{posted_key(row.get('posted_at',''))}"
        payload = {
            "id": row.get("id"),
            "pair": pair,
            "side": (row.get("side") or "").upper(),
            "entry": row.get("entry"),
            "sl": row.get("sl"),
            "tp": row.get("tp"),
            "timeframe": row.get("timeframe") or "M15",
            "posted_at": row.get("posted_at"),
            "status": status_of(pair, row.get("id"), row.get("posted_at", "")),
        }
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1))
        tmp.replace(X := OUT)
        print("landing-signal.json written:", pair, payload["status"])
    except SystemExit:
        raise
    except Exception as e:
        print("landing-signal error:", e)
        raise SystemExit(1)

if __name__ == "__main":
    main()
