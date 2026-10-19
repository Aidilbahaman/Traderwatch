#!/usr/bin/env python3
"""TraderWatch closed-signal watcher.

Polls signal-status.json and alerts the admin (via @Twreg_bot) when any
open signal closes (TP / SL / expired / cancelled). Deduped via a state file
so each signal is announced exactly once.

Complements:
  - signal-telegram-sender.py -> pushes NEW trading signals to linked members
  - signal-status.py           -> evaluates open signals against live M1 data

Run via cron every 5 min:  */5 * * * *  signal-close-alert.py
"""
import json
import ssl
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

BASE = Path.home() / ".secrets"
STATUS = Path("/home/ubuntu/web/Traderwatch-repo/signal-status.json")
STATE = Path("/tmp/traderwatch-signal-closed-alerts.json")
TZ_OFFSET = 8  # Malaysia


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


def send_telegram(text):
    """Admin alert -> @Twreg_bot (the admin bot). Never broadcast."""
    try:
        s = load("telegram.env")
        token = s.get("TELEGRAM_BOT_TOKEN")
        chat = s.get("TELEGRAM_ADMIN_CHAT_ID")
        if not token or not chat:
            return False
        url = ("https://api.telegram.org/bot" + token + "/sendMessage?"
               + urllib.parse.urlencode({"chat_id": chat, "text": text,
                                         "parse_mode": "HTML",
                                         "disable_web_page_preview": "true"}))
        with urllib.request.urlopen(url, timeout=20) as r:
            payload = json.loads(r.read().decode())
        return bool(payload.get("ok"))
    except Exception as e:
        log(f"TG-FAIL {type(e).__name__} {e}")
        return False


def key_to_pair(key):
    code = key.split("_")[0]
    return f"{code[:3]}/{code[3:]}" if len(code) == 6 else code


def main():
    if not STATUS.exists():
        log("no signal-status.json yet; skipping")
        return 0
    state = json.loads(STATUS.read_text())
    signals = state.get("signals", {})

    try:
        seen = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    except Exception:
        seen = set()

    new_closed = []
    for key, info in signals.items():
        if key in seen:
            continue
        status = (info.get("status") or "").lower()
        if status in ("tp", "sl", "expired", "cancelled"):
            new_closed.append((key, status, info))
            seen.add(key)

    if not new_closed:
        log(f"no new closures (tracking {len(signals)} signals)")
        return 0

    for key, status, info in new_closed:
        pair = key_to_pair(key)
        pips = info.get("pips")
        pips_txt = f"{'+' if pips and pips > 0 else ''}{pips} pips" if pips is not None else ""
        emoji = {"tp": "✅", "sl": "❌", "expired": "⌛", "cancelled": "🚫"}.get(status, "📌")
        text = (f"{emoji} <b>Signal closed: {pair}</b>\n\n"
                f"Status: {status.upper()}\n"
                f"{pips_txt}\n"
                f"Time: {info.get('closed', '—')}")
        tg = send_telegram(text)
        mail = send_email(f"TraderWatch: {pair} {status.upper()}", text)
        log(f"alerted {pair} {status} tg={tg} mail={mail}")

    STATE.write_text(json.dumps(sorted(seen)))
    STATE.chmod(0o600)
    log(f"new closures={len(new_closed)} total tracked={len(seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
