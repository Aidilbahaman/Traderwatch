#!/usr/bin/env python3
"""notify_new_members.py — notify admin of new registrations + Telegram links.

Reads from Supabase `profiles` (the real source of truth for website sign-ups),
NOT from tw-bot/bot.db (which has no created_at column and only holds bot users).

Two event types are detected:
  1. NEW REGISTRATION  — a profile whose created_at is recent and never seen before
  2. TELEGRAM LINKED   — a known profile that just gained a telegram_chat_id

State is kept in state/notify-members-state.json so each event is announced once.
The first run only seeds state (no backfill spam).

Usage:
  python3 notify_new_members.py            # normal cron run
  python3 notify_new_members.py --dry-run  # print what would be sent
  python3 notify_new_members.py --seed     # seed state from current profiles, send nothing
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(REPO, "state", "notify-members-state.json")
SECRETS_DIR = "/home/ubuntu/.secrets"
ADMIN_CHAT_ID = "7696607055"
TIMEOUT = 20
# Only announce registrations newer than this (hours). Prevents a first-run flood.
NEW_WINDOW_HOURS = 24


# ---------------------------------------------------------------- secrets
def load_secrets(name):
    path = os.path.join(SECRETS_DIR, name)
    vals = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as exc:
        print(f"WARN: cannot read {path}: {exc}", file=sys.stderr)
    return vals


SB = load_secrets("supabase.env")
TG = load_secrets("telegram.env")

SB_URL = SB.get("SUPABASE_URL", "")
SB_KEY = SB.get("SUPABASE_SERVICE_KEY", "")
# Registration/link notices go out from the admin bot (@CCSTWbot).
TOKEN = (TG.get("TELEGRAM_ADMIN_BOT_TOKEN") or TG.get("TELEGRAM_BOT_TOKEN") or "").strip()


# ---------------------------------------------------------------- helpers
def sb_get(path):
    if not SB_URL or not SB_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured")
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{path}",
        headers={
            "apikey": SB_KEY,
            "Authorization": f"Bearer {SB_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw.strip() else []


def send_telegram(text):
    if not TOKEN:
        print("WARN: no admin bot token; skipping send", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": ADMIN_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            print(f"telegram error: {body.get('description')}", file=sys.stderr)
            return False
        return True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"telegram send failed: {exc}", file=sys.stderr)
        return False


def load_state():
    try:
        with open(STATE_PATH) as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("profiles"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"profiles": {}, "seeded": False}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def esc(text):
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, do not send/save")
    ap.add_argument("--seed", action="store_true", help="record current profiles, send nothing")
    args = ap.parse_args()

    try:
        rows = sb_get(
            "profiles?select=id,name,email,plan,role,created_at,telegram_chat_id"
            "&order=created_at.desc&limit=500"
        )
    except Exception as exc:  # noqa: BLE001 - cron must never crash loudly
        print(f"ERROR fetching profiles: {exc}", file=sys.stderr)
        return 1

    if not isinstance(rows, list):
        print(f"ERROR unexpected profiles payload: {type(rows)}", file=sys.stderr)
        return 1

    state = load_state()
    known = state["profiles"]
    first_run = not state.get("seeded")

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=NEW_WINDOW_HOURS)

    new_regs, new_links = [], []

    for p in rows:
        pid = p.get("id")
        if not pid:
            continue
        chat_id = p.get("telegram_chat_id")
        prev = known.get(pid)
        created = parse_ts(p.get("created_at"))

        if prev is None:
            # Never seen. Only announce if it is genuinely recent, so the very
            # first run does not replay the whole member list.
            if not first_run and created and created >= cutoff:
                new_regs.append(p)
        elif chat_id and not prev.get("telegram_chat_id"):
            new_links.append(p)

        known[pid] = {
            "name": p.get("name"),
            "plan": p.get("plan"),
            "telegram_chat_id": chat_id,
            "created_at": p.get("created_at"),
        }

    if args.seed:
        state["seeded"] = True
        if not args.dry_run:
            save_state(state)
        print(f"seeded {len(known)} profiles (no notifications sent)")
        return 0

    sent = 0

    if new_regs:
        lines = ["📥 <b>New Registration</b>"]
        for p in new_regs:
            linked = "✅ linked" if p.get("telegram_chat_id") else "⏳ not linked"
            lines.append(
                f"👤 {esc(p.get('name') or 'Unknown')}\n"
                f"   plan: <b>{esc((p.get('plan') or 'free').upper())}</b> · {linked}\n"
                f"   {esc(p.get('email') or '')}"
            )
        text = "\n".join(lines)
        if args.dry_run:
            print("--- WOULD SEND (new registration) ---")
            print(text)
        elif send_telegram(text):
            sent += 1

    if new_links:
        lines = ["🔗 <b>Telegram Linked</b>"]
        for p in new_links:
            lines.append(
                f"👤 {esc(p.get('name') or 'Unknown')} · <b>{esc((p.get('plan') or 'free').upper())}</b>\n"
                f"   chat_id: <code>{esc(p.get('telegram_chat_id'))}</code>"
            )
        text = "\n".join(lines)
        if args.dry_run:
            print("--- WOULD SEND (telegram linked) ---")
            print(text)
        elif send_telegram(text):
            sent += 1

    state["seeded"] = True
    if not args.dry_run:
        save_state(state)

    print(
        f"ok: {len(rows)} profiles scanned, "
        f"{len(new_regs)} new registration(s), {len(new_links)} new link(s), {sent} message(s) sent"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
