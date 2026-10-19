#!/usr/bin/env python3
"""TraderWatch link bot (@Traderwatchmembershipbot).

Long-polls Telegram getUpdates and handles:
  /start <user_uuid>  -> stores chat_id on profiles.telegram_chat_id
  /start              -> asks for the link from the dashboard
  /stop               -> unlinks (clears telegram_chat_id)
  /status             -> shows linked plan

Only Pro/Max members receive signals; linking is allowed for any plan so
free members can link now and start receiving on upgrade.

Secrets: ~/.secrets/telegram.env (TELEGRAM_BOT_TOKEN),
         ~/.secrets/supabase.env (SUPABASE_URL, SUPABASE_SERVICE_KEY)
Run under systemd or cron @reboot; single instance enforced via /tmp lock.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 30
POLL_WAIT = 25
LOCK = Path("/tmp/twreg-bot.lock")
OFFSET_FILE = Path("/home/ubuntu/web/.twreg-offset")

API = "https://api.telegram.org/bot{token}/{method}"


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}", flush=True)


def load_secrets(name):
    path = Path.home() / ".secrets" / name
    vals = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


TG = load_secrets("telegram.env")
SB = load_secrets("supabase.env")
# Linking happens in the signals bot (@Traderwatchmembershipbot).
# @Twreg_bot is now used only for outbound welcome/nudge messages.
TOKEN = TG.get("TELEGRAM_SIGNALS_BOT_TOKEN") or TG["TELEGRAM_BOT_TOKEN"]
SB_URL = SB["SUPABASE_URL"]
SB_KEY = SB["SUPABASE_SERVICE_KEY"]


def tg(method, **params):
    url = API.format(token=TOKEN, method=method)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        log(f"TG-ERR {method} {e.code} {e.read().decode()[:200]}")
        return {"ok": False}
    except Exception as e:
        log(f"TG-ERR {method} {type(e).__name__} {e}")
        return {"ok": False}


def sb(path, method="GET", body=None, prefer=None):
    headers = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip() else None)


def sb_get(path):
    """GET -> (status, json_or_None)."""
    _, rows = sb(path)
    return rows


def resolve_token(token):
    """Validate a one-time link token. Returns (user_row, error_str).
    On success the token is consumed (used_at set) and deleted."""
    if not token or len(token) < 16:
        return None, "Invalid token format. Press 'Link Telegram' in the dashboard to get a fresh link."
    rows = sb_get(f"link_tokens?select=token,user_id,created_at,used_at&token=eq.{token}&limit=1")
    if not rows:
        return None, "Token not found or already used. Press 'Link Telegram' in the dashboard for a new link."
    t = rows[0]
    if t.get("used_at"):
        return None, "This link has already been used. Press 'Link Telegram' in the dashboard for a new link."
    import datetime
    # PostgREST returns timestamptz as an ISO-8601 string; parse it first.
    created = t["created_at"]
    if isinstance(created, str):
        created = datetime.datetime.fromisoformat(
            created.replace("Z", "+00:00"))
    age = datetime.datetime.now(datetime.timezone.utc) - created
    if age.total_seconds() > 900:
        return None, "This link has expired (15 min limit). Press 'Link Telegram' in the dashboard for a fresh link."
    uid = t["user_id"]
    # Consume: mark used, then delete.
    sb(f"link_tokens?token=eq.{token}", "PATCH",
       {"used_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    sb(f"link_tokens?token=eq.{token}", "DELETE")
    # Fetch the profile to confirm the account still exists.
    prof = profile_for(uid)
    return prof, None


def reply(chat_id, text):
    tg("sendMessage", chat_id=chat_id, text=text,
       parse_mode="HTML", disable_web_page_preview="true")


def profile_for(uid):
    _, rows = sb(f"profiles?select=id,name,plan,telegram_chat_id&id=eq.{uid}")
    return rows[0] if rows else None


def welcome_text(who, plan):
    plan = (plan or "free").lower()
    if plan == "free":
        return (
            "✅ Linked successfully!\n"
            "================================\n"
            f"Welcome, {who}.\n\n"
            "Your TraderWatch account is now connected to Telegram.\n\n"
            "📊 Current plan: <b>FREE</b>\n"
            "• Up to 3 verified setups daily\n"
            "• 3 hot pairs\n"
            "• Member dashboard + charts\n\n"
            "Signals start arriving here automatically once you upgrade to "
            "Pro or Max.\n\n"
            "Open dashboard → https://aidilbahaman.github.io/Traderwatch/members.html\n\n"
            "Send /status to check your link, /stop to unlink."
        )
    plan_label = plan.upper()
    emoji = "🚀" if plan == "max" else "⚡"
    perks = ("• Unlimited verified setups across 6 hot pairs\n"
             if plan == "max" else
             "• Up to 10 verified setups daily across 6 hot pairs\n")
    return (
        f"{emoji} Access upgraded to {plan_label}!\n"
        f"================================\n"
        f"Welcome, {who}.\n\n"
        f"Your TraderWatch plan is now <b>{plan_label}</b>.\n"
        f"New signals will arrive here automatically — no extra steps needed.\n\n"
        f"📊 What you get:\n"
        + perks
        + "• Live charts + position tools\n"
        + "• Telegram signals delivered here\n\n"
        + "Open dashboard → https://aidilbahaman.github.io/Traderwatch/members.html\n\n"
        + "Send /status to check your link, /stop to unlink."
    )


def link(prof, chat_id, name):
    """Attach chat_id to the profile resolved from a valid one-time token."""
    if not prof:
        reply(chat_id, "❌ That link is not valid. Open the member dashboard "
                       "and press <b>Link Telegram</b> again.")
        return
    uid = prof["id"]
    # Clear this chat from any other account first (one chat = one account).
    try:
        sb(f"profiles?telegram_chat_id=eq.{chat_id}&id=neq.{uid}",
           "PATCH", {"telegram_chat_id": None}, prefer="return=minimal")
    except Exception as e:
        log(f"WARN clear-old-link {e}")
    sb(f"profiles?id=eq.{uid}", "PATCH",
       {"telegram_chat_id": chat_id}, prefer="return=minimal")
    who = prof.get("name") or name or "trader"
    plan = prof.get("plan")
    reply(chat_id, welcome_text(who, plan))


def unlink(chat_id):
    try:
        sb(f"profiles?telegram_chat_id=eq.{chat_id}", "PATCH",
           {"telegram_chat_id": None}, prefer="return=minimal")
        reply(chat_id, "🔕 Unlinked. You will no longer receive signals here.")
    except Exception as e:
        log(f"ERR unlink {e}")
        reply(chat_id, "⚠️ Could not unlink. Try again in a minute.")


def status(chat_id):
    _, rows = sb(f"profiles?select=name,plan,email&telegram_chat_id=eq.{chat_id}")
    if not rows:
        reply(chat_id, "Not linked yet. Open the member dashboard and press "
                       "<b>Link Telegram</b>.")
        return
    p = rows[0]
    reply(chat_id, f"👤 {p.get('name') or 'Member'}\n"
                   f"📧 {p.get('email') or '-'}\n"
                   f"📊 Plan: <b>{(p.get('plan') or 'free').upper()}</b>")


def handle(msg):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text.startswith("/"):
        return
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    name = (chat.get("first_name") or "").strip()

    if cmd == "/start":
        arg = parts[1].strip() if len(parts) > 1 else ""
        if arg:
            prof, err = resolve_token(arg)
            if err:
                reply(chat_id, "❌ " + err)
            else:
                link(prof, chat_id, name)
        else:
            reply(chat_id, "👋 Welcome to TraderWatch signals.\n\n"
                           "Open your member dashboard and press "
                           "<b>Link Telegram</b> — it sends you a personal "
                           "link that connects this chat to your account.")
    elif cmd == "/stop":
        unlink(chat_id)
    elif cmd == "/status":
        status(chat_id)
    elif cmd == "/help":
        reply(chat_id, "/start &lt;link&gt; — connect from dashboard\n"
                       "/status — show linked account\n"
                       "/stop — unlink this chat")


def main():
    if LOCK.exists():
        # stale lock guard: remove if older than 10 min
        try:
            if time.time() - LOCK.stat().st_mtime > 600:
                LOCK.unlink()
            else:
                log("SKIP already running")
                return 0
        except FileNotFoundError:
            pass
    LOCK.write_text(str(os.getpid()))
    offset = 0
    if OFFSET_FILE.exists():
        try:
            offset = int(OFFSET_FILE.read_text().strip())
        except ValueError:
            offset = 0
    me = tg("getMe")
    log(f"bot @{(me.get('result') or {}).get('username')} polling")
    try:
        while True:
            res = tg("getUpdates", offset=offset, timeout=POLL_WAIT,
                     allowed_updates='["message"]')
            if not res.get("ok"):
                time.sleep(5)
                continue
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    OFFSET_FILE.write_text(str(offset))
                except Exception:
                    pass
                msg = upd.get("message")
                if msg:
                    try:
                        handle(msg)
                    except Exception as e:
                        log(f"ERR handle {type(e).__name__} {e}")
    finally:
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("stopped")
