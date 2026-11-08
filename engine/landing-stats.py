#!/usr/bin/env python3
"""Generate landing-stats.json for the traderwatch.org hero counters.

Counts are REAL, from the live systems — never invented:
  members : number of accounts in Supabase Auth (admin API, paginated)
  active  : live trades right now = open MT5 positions + working MT5 pending orders

"active" deliberately counts BROKER state (what is actually open), not
signal-status.json rows, because a published setup that has not been filled is
not an active trade. Signal rows with status "active" are a superset.

Runs after engine/signal-status.py in the 5-minute cron.
The landing page shows an em dash when a value is 0 or the file is missing,
so a broken run degrades to "—" instead of a false number.
"""
import json
import pathlib
import subprocess
import urllib.request

REPO = pathlib.Path("/home/ubuntu/web/Traderwatch-repo")
OUT = REPO / "landing-stats.json"
ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")

MT5_HOST_SCRIPT = "C:\\mt5work\\mt5_pending.py"
MT5_CMD = [
    "sudo", "-u", "mt5", "/usr/bin/env",
    "DISPLAY=:99", "WINEPREFIX=/home/mt5/.mt5",
    "/opt/wine-staging/bin/wine",
    "C:\\Python311\\python.exe", MT5_HOST_SCRIPT,
]


def load_env():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


def count_members(sec):
    """Total Supabase Auth accounts, paginated (per_page caps at 200 in GoTrue)."""
    url = sec["SUPABASE_URL"].rstrip("/")
    key = sec["SUPABASE_SERVICE_KEY"]
    total = 0
    page = 1
    while True:
        req = urllib.request.Request(
            f"{url}/auth/v1/admin/users?page={page}&per_page=200",
            headers={"apikey": key, "Authorization": "Bearer " + key},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read())
        users = data.get("users", data) if isinstance(data, dict) else data
        if not users:
            break
        total += len(users)
        if len(users) < 200:
            break
        page += 1
    return total


def count_live_trades():
    """Open MT5 positions + working pending orders = trades active right now.

    Reads broker state through the same Wine bridge the execution engine uses,
    so the number matches what the account actually holds. Returns 0 on any
    failure so the landing page degrades to an em dash rather than a guess.
    """
    try:
        proc = subprocess.run(
            MT5_CMD + ['{"action": "state"}'],
            capture_output=True, text=True, timeout=60, cwd="/tmp",
        )
        raw = (proc.stdout or "").strip().splitlines()
        payload = None
        for line in reversed(raw):
            line = line.strip()
            if line.startswith("{"):
                try:
                    payload = json.loads(line)
                    break
                except Exception:
                    continue
        if not payload or not payload.get("ok"):
            return 0
        return len(payload.get("positions") or []) + len(payload.get("orders") or [])
    except Exception:
        return 0


def main():
    try:
        sec = load_env()
        payload = {
            "members": count_members(sec),
            "active": count_live_trades(),
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1))
        tmp.replace(OUT)
        print(f"landing-stats.json written: members={payload['members']} active={payload['active']}")
    except Exception as e:
        print("landing-stats error:", e)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
