#!/usr/bin/env python3
"""TraderWatch Telegram signal sender.

Sends newly-inserted verified signals to every Pro/Max member whose
profiles.telegram_chat_id is set. Called automatically after
signal-engine.py inserts (cron chain), or standalone for a re-send window.

Sent state is tracked in /home/ubuntu/web/.tg-sent-ids.json so a signal
is never sent twice. Telegram message limit guards against floods.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 25
SENT_FILE = Path("/home/ubuntu/web/.tg-sent-ids.json")
MAX_MSGS = 60          # hard cap per run
BATCH_GAP = 0.6        # seconds between sends


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
# Everything member-facing now comes from @Traderwatchmembershipbot:
# signals, nudges and plan-upgrade messages.
SIGNALS_TOKEN = TG.get("TELEGRAM_SIGNALS_BOT_TOKEN") or TG["TELEGRAM_BOT_TOKEN"]
SB_URL = SB["SUPABASE_URL"]
SB_KEY = SB["SUPABASE_SERVICE_KEY"]


def http_json(url, method="GET", body=None, headers=None):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip() else None)


def tg_call(token, method, chat_id, text):
    """Returns (ok, error_code, description)."""
    url = (f"https://api.telegram.org/bot{token}/{method}?"
           + urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                     "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"}))
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode())
        return bool(body.get("ok")), 0, ""
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            desc = body.get("description", "")
            code = body.get("error_code", e.code)
        except Exception:
            desc, code = str(e), e.code
        return False, code, desc
    except Exception as e:
        return False, -1, f"{type(e).__name__} {e}"


def tg_send(chat_id, text):
    """Send a signal via the signals bot. Returns (ok, needs_start)."""
    ok, code, desc = tg_call(SIGNALS_TOKEN, "sendMessage", chat_id, text)
    if ok:
        return True, False
    # 403 = member never pressed Start in the signals bot (or blocked it).
    needs_start = (code == 403) or ("chat not found" in desc.lower()) \
        or ("can't initiate" in desc.lower()) or ("blocked" in desc.lower())
    log(f"SEND-FAIL chat={chat_id} code={code} desc={desc[:120]}")
    return False, needs_start


def nudge_start(chat_id):
    """Fallback if the signals bot cannot reach a member.

    Linking now happens inside @Traderwatchmembershipbot, so a 403 almost
    always means the member blocked or deleted the bot. Send one short
    reminder from the same bot; if that also fails there is nothing else
    we can do from here.
    """
    text = ("📡 <b>Signals are paused for this chat</b>\n\n"
            "You appear to have blocked or removed "
            "<b>@Traderwatchmembershipbot</b>, so new setups cannot be "
            "delivered.\n\n"
            "Open the bot and press <b>Start</b> to resume. You can also "
            "relink from your dashboard.")
    ok, code, desc = tg_call(SIGNALS_TOKEN, "sendMessage", chat_id, text)
    if ok:
        log(f"NUDGE sent chat={chat_id}")
    else:
        log(f"NUDGE-FAIL chat={chat_id} code={code} {desc[:100]}")
    return ok


def load_sent():
    if SENT_FILE.exists():
        try:
            return set(json.loads(SENT_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_sent(sent):
    keep = sorted(sent, reverse=True)[:500]   # bound the file
    SENT_FILE.write_text(json.dumps(keep))


def fetch_targets():
    st, rows = http_json(
        f"{SB_URL}/rest/v1/profiles"
        "?select=id,name,plan,telegram_chat_id"
        "&plan=in.(pro,max)&telegram_chat_id=not.is.null",
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"})
    if st != 200:
        raise RuntimeError(f"profiles fetch {st}")
    return rows or []


def fetch_new_signals(sent):
    st, rows = http_json(
        f"{SB_URL}/rest/v1/signals"
        "?select=id,pair,timeframe,side,entry,sl,tp,posted_at"
        "&verified=is.true&order=posted_at.desc&limit=15",
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"})
    if st != 200:
        raise RuntimeError(f"signals fetch {st}")
    fresh = [s for s in (rows or []) if s["id"] not in sent]
    # oldest first so a flood of new signals keeps chronological order
    return sorted(fresh, key=lambda s: s["posted_at"])


PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001


def fmt(s):
    arrow = "🟢 BUY" if s["side"] == "BUY" else "🔴 SELL"
    pip = PIP.get(s["pair"], DEFAULT_PIP)
    entry, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
    sl_p = abs(entry - sl) / pip
    tp_p = abs(tp - entry) / pip
    rr = tp_p / sl_p if sl_p else 0.0
    levels = ("<pre>"
              f"Entry   {s['entry']}\n"
              f"SL      {s['sl']}   -{sl_p:.1f}p\n"
              f"TP      {s['tp']}   +{tp_p:.1f}p\n"
              f"R:R     1 : {rr:.1f}"
              "</pre>")
    return (f"📡 <b>TRADERWATCH · LIVE SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{arrow} <b>{s['pair']}</b> · {s['timeframe']}\n\n"
            f"{levels}\n"
            f"This is live price update. We giving the signal, you decide to "
            f"enter or not. Not financial advice, trade at your own risk.\n\n"
            f"🎁 <b>New trader offer</b>\n"
            f"Register through our partner link to claim a <b>$30 welcome bonus</b>. "
            f"Eligibility and conditions apply — please review the broker's terms before registering.\n"
            f"👉 https://rinfinity.com/en/welcome-bonus?a=wnzx")


def main():
    sent = load_sent()
    signals = fetch_new_signals(sent)
    if not signals:
        log("no new signals")
        return 0
    targets = fetch_targets()
    if not targets:
        log(f"{len(signals)} signal(s) but no linked Pro/Max members")
        save_sent(sent | {s["id"] for s in signals})
        return 0
    log(f"{len(signals)} new signal(s) -> {len(targets)} member(s)")
    count = nudged = 0
    for s in signals:
        text = fmt(s)
        ok_all = True
        for t in targets:
            if count >= MAX_MSGS:
                log("hit MAX_MSGS cap, remaining signals will retry next run")
                return 1
            chat_id = t["telegram_chat_id"]
            ok, needs_start = tg_send(chat_id, text)
            if ok:
                count += 1
            else:
                ok_all = False
                # Not started in the signals bot yet: send one nudge via the
                # link bot so the member knows what to do. At most once per
                # run per member (nudge only on the first signal of the run).
                if needs_start and s is signals[0]:
                    if nudge_start(chat_id):
                        nudged += 1
            time.sleep(BATCH_GAP)
        if ok_all:
            sent.add(s["id"])
    save_sent(sent)
    log(f"DONE sent={count} nudged={nudged} marked={len(sent)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL {type(e).__name__} {e}")
        sys.exit(1)
