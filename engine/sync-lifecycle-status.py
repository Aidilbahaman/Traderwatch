#!/usr/bin/env python3
"""Selaraskan .signal-lifecycle.json -> signal-status.json.

Masalah: signal-lifecycle-alert.py menutup setup (expired/tp/sl) dalam state
dalaman sahaja. signal-status.json (dibaca website) tidak dikemas kini, jadi
setup yang sudah expired masih dipaparkan 'pending' di website walaupun
Telegram sudah dimaklumkan.

Idempotent: hanya menulis bila ada perbezaan.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

LIFECYCLE = Path("/home/ubuntu/web/.signal-lifecycle.json")
STATUS = Path("/home/ubuntu/web/Traderwatch-repo/signal-status.json")
SECRETS = Path.home() / ".secrets" / "supabase.env"
MYT = timezone(timedelta(hours=8))
TERMINAL = {"tp", "sl", "expired", "cancelled", "collected"}


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def load_supabase():
    vals = {}
    try:
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        return None, None
    url = (vals.get("SUPABASE_URL") or vals.get("VITE_SUPABASE_URL") or "").rstrip("/")
    key = vals.get("SUPABASE_SERVICE_KEY") or vals.get("SUPABASE_SERVICE_ROLE_KEY")
    return url, key


def fetch_signals(url, key):
    """Ambil id -> status_key untuk semua signal (id diperlukan oleh lifecycle)."""
    req = urllib.request.Request(
        f"{url}/rest/v1/signals?select=id,pair,posted_at&order=id.asc&limit=500",
        headers={"apikey": key, "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode() or "[]")

    out = {}
    for row in rows:
        raw = str(row["posted_at"]).replace("Z", "+00:00")
        try:
            d = datetime.fromisoformat(raw)
        except Exception:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(MYT)
        code = "".join(ch for ch in str(row["pair"]).upper() if ch.isalpha())
        out[str(row["id"])] = f"{code}_{d:%Y%m%d}_{d:%H%M%S}"
    return out


def main():
    try:
        lc = json.loads(LIFECYCLE.read_text())
    except Exception as ex:
        log(f"SKIP: cannot read lifecycle ({ex})")
        return 0

    try:
        st = json.loads(STATUS.read_text())
    except Exception as ex:
        log(f"FAIL: cannot read signal-status ({ex})")
        return 1

    url, key = load_supabase()
    if not url or not key:
        log("FAIL: supabase credentials missing")
        return 1

    try:
        id_to_key = fetch_signals(url, key)
    except Exception as ex:
        log(f"FAIL: cannot fetch signals ({ex})")
        return 1

    sigs = st.get("signals") or {}
    changed = []

    for sid, state in lc.items():
        closed = state.get("closed")
        if not closed:
            continue
        key = id_to_key.get(str(sid))
        if not key:
            continue
        cur = sigs.get(key)
        if not isinstance(cur, dict):
            continue
        if cur.get("status") in TERMINAL:
            continue
        if cur.get("status") == closed:
            continue

        old = cur.get("status")
        cur["status"] = closed
        if closed == "expired" and not cur.get("closed"):
            cur["closed"] = datetime.now(MYT).isoformat(timespec="seconds")
        changed.append(f"#{sid} {key}: {old} -> {closed}")

    if changed:
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=0, ensure_ascii=False))
        tmp.replace(STATUS)
        log(f"updated {len(changed)}: " + "; ".join(changed))
    else:
        log("no change")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        log(f"FATAL {type(ex).__name__}: {ex}")
        sys.exit(1)
