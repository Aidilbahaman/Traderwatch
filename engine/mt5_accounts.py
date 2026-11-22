"""Per-member MT5 account routing for the TraderWatch member app.

Maps a Supabase user id to an MT5 terminal/account profile so "Take this trade"
can be routed to the correct Wine prefix instead of always the owner's account.

The owner (c59521e0-...) keeps the default profile in mt5-pending.py unchanged.
Client profiles point at their own cloned Wine prefix + per-account state files.

Config source: repo/state/mt5-accounts.json (git-ignored, edited on the VPS).
Shape:
{
  "<supabase_uid>": {
    "key": "abieidham",              # short id used for state file names
    "login": 37408711,
    "server": "RoboForex-Pro",
    "prefix": "/home/mt5/.mt5-37408711",
    "can_trade": false,              # flips true after deposit + trade password
    "label": "Abe Client (RoboForex)",
    "magic_base": 20263000
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "state" / "mt5-accounts.json"


def _load() -> dict:
    try:
        d = json.loads(CONFIG.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def account_for(uid: str | None) -> dict | None:
    """Return the MT5 profile mapped to a Supabase uid, or None."""
    if not uid:
        return None
    d = _load().get(uid)
    return d if isinstance(d, dict) and d.get("prefix") else None


def can_trade(uid: str | None) -> bool:
    """True only when the account is explicitly marked trade-enabled."""
    a = account_for(uid)
    return bool(a and a.get("can_trade") is True)
