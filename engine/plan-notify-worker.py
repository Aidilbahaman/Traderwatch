#!/usr/bin/env python3
"""TraderWatch plan-change notification worker.

Watches the plan_notifications outbox table and sends a Telegram welcome
message to members whose plan just changed to Pro or Max (and who have a
linked Telegram chat). Updates the row status to sent/skipped/failed.

Run: every 5 min via cron, or once manually after admin approval.
No lock needed: it is idempotent and safe to run concurrently (status
is per-row, not per-run).
"""
import json, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

TIMEOUT = 25
BATCH = 50          # max rows per run
BATCH_GAP = 0.6     # seconds between Telegram sends

BOT_LOG = "/tmp/plan-notify-worker.log"


def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"{ts} {msg}", flush=True)
    try:
        Path(BOT_LOG).write_text(
            Path(BOT_LOG).read_text()[-50000:] + f"{ts} {msg}\n")
    except Exception:
        pass


def load(name):
    v = {}
    for l in (Path.home() / ".secrets" / name).read_text().splitlines():
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, val = l.split("=", 1)
            v[k.strip()] = val.strip().strip('"').strip("'")
    return v


TG = load("telegram.env")
SB = load("supabase.env")
# Plan/welcome messages come from @Traderwatchmembershipbot (same bot as signals).
TOKEN = TG.get("TELEGRAM_SIGNALS_BOT_TOKEN") or TG["TELEGRAM_BOT_TOKEN"]
SB_URL, SB_KEY = SB["SUPABASE_URL"], SB["SUPABASE_SERVICE_KEY"]


def supabase(method, path, body=None):
    headers = {
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{path}", data=data,
        headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip() else None)


def tg_send(chat_id, text):
    url = ("https://api.telegram.org/bot" + TOKEN + "/sendMessage?"
           + urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                    "parse_mode": "HTML"}))
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url), timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode())
        return body.get("ok", False)
    except Exception as e:
        log(f"TG-ERR chat={chat_id}: {type(e).__name__} {e}")
        return False


def welcome_msg(name, plan):
    plan_label = plan.upper()
    emoji = "🚀" if plan == "max" else "⚡"
    return (
        f"{emoji} Access upgraded to {plan_label}!\n"
        f"================================\n"
        f"Welcome{name and f', {name}' or ''}.\n\n"
        f"Your TraderWatch plan is now <b>{plan_label}</b>.\n"
        f"New signals will arrive here automatically — no extra steps needed.\n\n"
        f"📊 What you get:\n"
        + ("• Unlimited verified setups across 6 hot pairs\n"
           if plan == "max" else
           "• Up to 10 verified setups daily across 6 hot pairs\n")
        + "• Live charts + position tools\n"
        + "• Telegram signals delivered here\n\n"
        f"Open dashboard → https://aidilbahaman.github.io/Traderwatch/members.html\n\n"
        f"Send /status to @Traderwatchmembershipbot to check your link."
    )


def main():
    pending = supabase(
        "GET",
        f"plan_notifications?select=id,user_id,old_plan,new_plan,status,attempts"
        f"&status=eq.pending&order=created_at.asc&limit={BATCH}")
    if pending[0] != 200:
        log(f"fetch pending ERR {pending[0]}")
        return 1
    rows = pending[1] or []
    if not rows:
        log("no pending notifications")
        return 0

    log(f"{len(rows)} pending notification(s)")
    sent = skipped = failed = 0

    for row in rows:
        nid, uid, old_plan, new_plan = (
            row["id"], row["user_id"], row["old_plan"], row["new_plan"])

        # Get member profile (name + chat_id)
        st, prof = supabase(
            "GET",
            f"profiles?select=name,telegram_chat_id&id=eq.{uid}&limit=1")
        if st != 200 or not prof:
            log(f"profile ERR uid={uid} st={st}")
            supabase("PATCH",
                     f"plan_notifications?id=eq.{nid}",
                     {"status": "failed", "attempts": row["attempts"] + 1,
                      "last_error": "profile fetch failed"})
            failed += 1
            continue

        p = prof[0]
        chat_id = p.get("telegram_chat_id")

        if not chat_id:
            # Not linked yet — skip, but leave row pending so worker
            # picks it up again when (if) they link later.
            log(f"SKIP uid={uid} plan={new_plan} — no linked Telegram")
            supabase("PATCH",
                     f"plan_notifications?id=eq.{nid}",
                     {"status": "skipped", "attempts": row["attempts"] + 1,
                      "last_error": "telegram_chat_id not set"})
            skipped += 1
            continue

        name = p.get("name") or ""
        msg = welcome_msg(name, new_plan)
        if tg_send(chat_id, msg):
            supabase("PATCH",
                     f"plan_notifications?id=eq.{nid}",
                     {"status": "sent",
                      "sent_at": datetime.now(timezone.utc).isoformat(),
                      "attempts": row["attempts"] + 1})
            log(f"SENT uid={uid} name={name} plan={new_plan} chat={chat_id}")
            sent += 1
        else:
            supabase("PATCH",
                     f"plan_notifications?id=eq.{nid}",
                     {"status": "failed",
                      "attempts": row["attempts"] + 1,
                      "last_error": "Telegram send failed"})
            failed += 1
        time.sleep(BATCH_GAP)

    log(f"DONE sent={sent} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL {type(e).__name__} {e}")
        sys.exit(1)
