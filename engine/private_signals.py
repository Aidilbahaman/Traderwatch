"""Signal private owner-only.

Fail `state/private-signals.json` menyimpan senarai id signal yang HANYA
dihantar kepada owner (ADMIN_CHAT) dan tidak pernah kepada member.

Kenapa fail, bukan kolum DB: elak migration + RLS change pada Supabase
(tindakan yang perlu kelulusan owner sebelum dijalankan).

Modul ini sengaja tiada kebergantungan luar supaya boleh diimport oleh
lifecycle, sender, dan bot.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILE = REPO / "state" / "private-signals.json"


def ids():
    """Set id signal private (string). Fail hilang/rosak -> set kosong."""
    try:
        data = json.loads(FILE.read_text())
        return {str(x) for x in (data.get("ids") or [])}
    except Exception:
        return set()


def is_private(sid):
    """True bila signal ini owner-only."""
    if sid is None:
        return False
    return str(sid) in ids()


def add(sid):
    """Daftarkan signal sebagai private. Return senarai id terkini."""
    cur = ids() | {str(sid)}
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"ids": sorted(cur)}, indent=1) + "\n")
    return sorted(cur)


def remove(sid):
    """Nyahdaftar signal private. Return senarai id terkini."""
    cur = ids() - {str(sid)}
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"ids": sorted(cur)}, indent=1) + "\n")
    return sorted(cur)
