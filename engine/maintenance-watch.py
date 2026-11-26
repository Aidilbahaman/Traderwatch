#!/usr/bin/env python3
"""TraderWatch auto maintenance detector.

Detects backend patch activity by watching systemd ActiveEnterTimestamp of
the TW services. A restart newer than the last seen one = a patch just
landed -> writes data/maintenance.json maintenance=true (banner shows).
When every service has been stable for STABLE_SECS, banner clears itself.

State: data/maintenance-watch.json (git-ignored data dir).
Cron: every minute, flock-guarded.
"""
import json, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "data" / "maintenance-watch.json"
FLAG = REPO / "data" / "maintenance.json"
SERVICES = ["tw-chat-api", "tw-league-api", "tw-analyze-api", "tw-push-api",
            "sq-collector", "tw-mt5-client"]
STABLE_SECS = 180          # 3 minit stabil = patch selesai
RECENT_WINDOW = 120        # restart dalam 2 min terakhir = patch aktif

def svc_ts(name):
    """ExecMainStartTimestamp epoch, atau 0 kalau servis down.
    Format 'Thu 2026-11-26 21:34:20 CST' — parse manual (C locale tz abbr
    tak disokong fromisoformat). Monotonic tak boleh guna (reset per boot),
    tapi perbandingan relasi antara runs dalam boot sama tetap sah."""
    try:
        raw = subprocess.run(
            ["systemctl", "show", name, "--property=ExecMainStartTimestamp", "--value"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        if not raw:
            return 0
        # "Thu 2026-11-26 21:34:20 CST" -> parts: day,date,time,tz (4 items)
        parts = raw.split()
        if len(parts) < 3:
            return 0
        iso = parts[1] + " " + parts[2]          # "2026-11-26 21:34:20"
        dt = datetime.strptime(iso, "%Y-%m-%d %H:%M:%S")
        # Server tz (CST = waktu VPS) — banding dalam local naive epoch.
        return dt.timestamp()
    except Exception as e:
        try:
            print("svc_ts warn", name, str(e)[:80], flush=True)
        except Exception:
            pass
        return 0

def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"seen": {}, "active_since": None}

def save_state(st):
    STATE.write_text(json.dumps(st, indent=1))

def now():
    return datetime.now(timezone.utc)

def main():
    st = load_state()
    seen = st.get("seen", {})
    ts_now = now()
    latest = {}
    patching = False
    for svc in SERVICES:
        t = svc_ts(svc)
        latest[svc] = t
        prev = seen.get(svc, t or 0)
        if t and prev and t > prev + 5:                      # restart baharu
            patching = True
        elif t and not prev:                                  # first run
            pass
        if t:
            seen[svc] = t
    if patching:
        st["active_since"] = ts_now.isoformat()
        st["patch_detected_at"] = ts_now.isoformat()
    else:
        act = st.get("active_since")
        if act:
            try:
                age = (ts_now - datetime.fromisoformat(act)).total_seconds()
                if age >= STABLE_SECS:
                    st["active_since"] = None
            except ValueError:
                st["active_since"] = None
    banner_on = bool(st.get("active_since"))
    # Kekalkan manual override: kalau flag true tapi tiada patch aktif, biar
    # manual flag (owner set) menang — watcher hanya menulis bila berubah.
    flag = {}
    try:
        flag = json.loads(FLAG.read_text())
    except Exception:
        pass
    if flag.get("manual") is True:
        banner_on = True
    new_flag = {
        "maintenance": banner_on,
        "source": "auto-watch" if banner_on and st.get("active_since") else
                  ("manual" if banner_on else "off"),
        "note": "⚠️ TraderWatch under maintenance, sorry for any inconvenience during maintenance periods 🙏🏻",
        "updated_at": ts_now.isoformat(),
        "manual": flag.get("manual", False),
    }
    if new_flag.get("maintenance") != flag.get("maintenance") or \
       new_flag.get("source") != flag.get("source"):
        FLAG.write_text(json.dumps(new_flag, indent=1))
    st["seen"] = seen
    st["checked_at"] = ts_now.isoformat()
    save_state(st)
    print(f"patching={patching} banner={'ON' if banner_on else 'off'} "
          f"active_since={st.get('active_since')}")

if __name__ == "__main__":
    main()
