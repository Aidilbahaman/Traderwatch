#!/usr/bin/env python3
"""Kuota Telegram untuk ahli Free: 3 signal setiap tetingkap 5 jam.

Tetingkap diselaraskan kepada grid 5 jam bermula 00:00 MYT, jadi semua ahli
Free menerima reset pada masa yang sama (00:00, 05:00, 10:00, 15:00, 20:00).
State disimpan dalam fail JSON supaya kekal selepas restart/cron.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

MYT = timezone(timedelta(hours=8))
STATE = Path(os.environ.get("FREE_QUOTA_STATE", "/home/ubuntu/tw-bot/free-quota.json"))
WINDOW_HOURS = 5
FREE_LIMIT = 3


def _now():
    return datetime.now(MYT)


def current_window(now=None):
    """Kunci tetingkap 5-jam untuk masa sekarang (grid 00/05/10/15/20 MYT)."""
    now = now or _now()
    start_hour = (now.hour // WINDOW_HOURS) * WINDOW_HOURS
    start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=WINDOW_HOURS)
    return start.strftime("%Y%m%dT%H"), start, end


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(data):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(STATE)
    try:
        STATE.chmod(0o600)
    except Exception:
        pass


def remaining(profile_id):
    """Baki kuota untuk profil ini dalam tetingkap semasa."""
    key, start, end = current_window()
    data = _load()
    used = int((data.get(key) or {}).get(str(profile_id), 0))
    return {
        "window": key,
        "used": used,
        "remaining": max(0, FREE_LIMIT - used),
        "limit": FREE_LIMIT,
        "reset_at": end.isoformat(),
        "reset_label": end.strftime("%H:%M MYT"),
    }


def consume(profile_id, count=1):
    """Tolak kuota. Pulangkan dict status; remaining=0 bermakna kuota habis."""
    key, start, end = current_window()
    data = _load()
    # buang tetingkap lama supaya fail tidak membesar
    data = {k: v for k, v in data.items() if k == key}
    bucket = data.setdefault(key, {})
    pid = str(profile_id)
    used = int(bucket.get(pid, 0))
    if used >= FREE_LIMIT:
        return {
            "allowed": False, "window": key, "used": used,
            "remaining": 0, "limit": FREE_LIMIT,
            "reset_at": end.isoformat(), "reset_label": end.strftime("%H:%M MYT"),
        }
    take = min(count, FREE_LIMIT - used)
    bucket[pid] = used + take
    _save(data)
    return {
        "allowed": True, "window": key, "used": used + take,
        "remaining": FREE_LIMIT - (used + take), "limit": FREE_LIMIT,
        "reset_at": end.isoformat(), "reset_label": end.strftime("%H:%M MYT"),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        pid = sys.argv[2] if len(sys.argv) > 2 else "test"
        print(json.dumps(remaining(pid), indent=1))
    else:
        print(json.dumps({"window": current_window()[0],
                          "limit": FREE_LIMIT,
                          "hours": WINDOW_HOURS}, indent=1))
