#!/usr/bin/env python3
"""TraderWatch new-registration notifier.

Polls Supabase `profiles` for rows created after the last run and alerts the
admin once per member (Telegram + email). Complements:
  - payment-notifier.py   -> pending / approved payments
  - plan-notify-worker.py -> member-facing upgrade messages

First run seeds the baseline silently so existing members never trigger a
burst of alerts. State lives in /tmp so a redeploy cannot replay old rows.
"""
import json
import os
import sys
import ssl
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

BASE = Path.home() / ".secrets"
STATE = Path("/tmp/traderwatch-registration-alerts.json")
LOOKBACK_HOURS = 48          # only consider recent rows on a cold start
SENT_LOG = Path("/home/ubuntu/web/logs/telegram-sent.jsonl")
ADMIN_URL = "https://aidilbahaman.github.io/Traderwatch/admin.html"
_BOT_NAME = None


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def load(name):
    vals = {}
    for line in (BASE / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def sb_get(path):
    s = load("supabase.env")
    req = urllib.request.Request(
        s["SUPABASE_URL"] + "/rest/v1/" + path,
        headers={"apikey": s["SUPABASE_SERVICE_KEY"],
                 "Authorization": "Bearer " + s["SUPABASE_SERVICE_KEY"]})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def bot_name(token):
    """Telegram username of the bot behind a token, cached per process."""
    global _BOT_NAME
    if _BOT_NAME is None:
        try:
            with urllib.request.urlopen(
                    "https://api.telegram.org/bot" + token + "/getMe",
                    timeout=15) as r:
                _BOT_NAME = json.loads(r.read().decode())["result"]["username"]
        except Exception:
            _BOT_NAME = "unknown"
    return _BOT_NAME


def record_send(entry):
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SENT_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    SENT_LOG.chmod(0o600)


def send_email(subject, body):
    try:
        s = load("smtp.env")
        m = EmailMessage()
        m["From"] = s["BREVO_SMTP_ADMIN_EMAIL"]
        m["To"] = s["BREVO_SMTP_ADMIN_EMAIL"]
        m["Subject"] = subject
        m.set_content(body)
        with smtplib.SMTP(s["BREVO_SMTP_HOST"],
                          int(s["BREVO_SMTP_PORT"]), timeout=25) as c:
            c.starttls(context=ssl.create_default_context())
            c.login(s["BREVO_SMTP_USER"], s["BREVO_SMTP_PASSWORD"])
            c.send_message(m)
        return True
    except Exception as e:
        log(f"EMAIL-FAIL {type(e).__name__} {e}")
        return False


def send_telegram(text, kind="registration"):
    """Send to the admin chat; return a dict so callers keep the message_id."""
    result = {"ok": False, "message_id": None, "bot": None, "chat": None}
    try:
        s = load("telegram.env")
        # Registration/admin alerts belong to @Twreg_bot. The membership bot
        # is reserved for member-facing welcome messages and trading signals.
        token = s.get("TELEGRAM_BOT_TOKEN")
        chat = s.get("TELEGRAM_ADMIN_CHAT_ID")
        result["chat"] = chat
        if not token or not chat:
            log("TG-SKIP missing token or admin chat id")
            return result
        result["bot"] = bot_name(token)
        url = ("https://api.telegram.org/bot" + token + "/sendMessage?"
               + urllib.parse.urlencode({"chat_id": chat, "text": text,
                                         "parse_mode": "HTML",
                                         "disable_web_page_preview": "true"}))
        with urllib.request.urlopen(url, timeout=20) as r:
            payload = json.loads(r.read().decode())
        result["ok"] = bool(payload.get("ok"))
        result["message_id"] = payload.get("result", {}).get("message_id")
        if result["ok"]:
            record_send({"ts": datetime.now(timezone.utc).isoformat(),
                         "kind": kind, "bot": result["bot"],
                         "chat": str(chat), "message_id": result["message_id"],
                         "preview": text.splitlines()[0][:80]})
        return result
    except Exception as e:
        log(f"TG-FAIL {type(e).__name__} {e}")
        return result


def delete_message(message_id):
    s = load("telegram.env")
    token = s.get("TELEGRAM_BOT_TOKEN")
    url = ("https://api.telegram.org/bot" + token + "/deleteMessage?"
           + urllib.parse.urlencode({"chat_id": s["TELEGRAM_ADMIN_CHAT_ID"],
                                     "message_id": message_id}))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            payload = json.loads(r.read().decode())
        if payload.get("ok"):
            log(f"deleted message_id={message_id}")
            return True
        log(f"DELETE-FAIL id={message_id} {payload.get('description')}")
    except Exception as e:
        log(f"DELETE-FAIL id={message_id} {type(e).__name__} {e}")
    return False


def show_sent(limit=20):
    if not SENT_LOG.exists():
        print("no sends recorded yet")
        return 0
    rows = [json.loads(l) for l in SENT_LOG.read_text().splitlines() if l.strip()]
    for r in rows[-limit:]:
        print(f"  {r['ts'][:19]}  bot=@{r['bot']:28} chat=***{str(r['chat'])[-3:]} "
              f"id={r['message_id']:<10} {r['preview']}")
    print(f"  total recorded: {len(rows)}")
    return 0


def fmt(m):
    name = (m.get("name") or "").strip() or "—"
    plan = (m.get("plan") or "free").upper()
    role = (m.get("role") or "member").lower()
    created = (m.get("created_at") or "")[:19].replace("T", " ")
    badge = "🆕 <b>New registration</b>" if role == "member" else "🆕 <b>New account</b>"
    return (f"{badge}\n\n"
            f"Name: {name}\n"
            f"Email: {m.get('email') or '—'}\n"
            f"Plan: {plan}\n"
            f"Time: {created} UTC\n\n"
            f"Open admin → {ADMIN_URL}")


def main():
    since = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS))
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sb_get("profiles?select=id,name,email,plan,role,created_at"
                  f"&created_at=gte.{since_iso}"
                  "&order=created_at.asc&limit=100")

    cold_start = not STATE.exists()
    try:
        seen = set(json.loads(STATE.read_text())) if not cold_start else set()
    except Exception:
        seen = set()

    if cold_start:
        # Seed silently: never blast existing members on first deploy.
        ids = [str(r["id"]) for r in rows]
        STATE.write_text(json.dumps(sorted(ids)))
        STATE.chmod(0o600)
        log(f"baseline seeded with {len(ids)} existing profile(s); no alerts sent")
        return 0

    sent = 0
    for r in rows:
        key = str(r["id"])
        if key in seen:
            continue
        if (r.get("role") or "").lower() == "admin":
            seen.add(key)          # never announce the admin account
            continue
        text = fmt(r)
        tg = send_telegram(text)
        ok_mail = send_email(
            f"TraderWatch: new registration ({r.get('plan','free').upper()})",
            text.replace("<b>", "").replace("</b>", ""))
        if tg["ok"] or ok_mail:
            seen.add(key)
            sent += 1
            log(f"alerted {r.get('email')} plan={r.get('plan')} "
                f"tg={tg['ok']} id={tg['message_id']} bot=@{tg['bot']} "
                f"mail={ok_mail}")
        else:
            log(f"alert-failed {r.get('email')} (will retry next run)")

    if sent:
        STATE.write_text(json.dumps(sorted(seen)))
        STATE.chmod(0o600)
    log(f"rows={len(rows)} new_alerts={sent}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        raise SystemExit(show_sent(n))
    if len(sys.argv) > 2 and sys.argv[1] == "--delete":
        raise SystemExit(0 if delete_message(int(sys.argv[2])) else 1)
    raise SystemExit(main())
