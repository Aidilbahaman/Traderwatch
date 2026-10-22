#!/usr/bin/env python3
"""TraderWatch Telegram signal sender.

Sends newly-inserted verified signals to every Pro/Max member whose
profiles.telegram_chat_id is set. Called automatically after
signal-engine.py inserts (cron chain), or standalone for a re-send window.

Sent state is tracked in /home/ubuntu/web/.tg-sent-ids.json so a signal
is never sent twice. Telegram message limit guards against floods.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 25
SENT_FILE = Path("/home/ubuntu/web/.tg-sent-ids.json")
# Ujian pada diri sendiri: kalau fail ini wujud, sender HANYA hantar ke chat
# itu dan guna fail sent berasingan supaya state production tidak tercemar.
TEST_CHAT_FILE = Path("/home/ubuntu/web/.sender-test-chat")
TEST_SENT_FILE = Path("/home/ubuntu/web/.tg-sent-ids-test.json")


def test_chat():
    try:
        v = TEST_CHAT_FILE.read_text().strip()
        return int(v) if v else None
    except Exception:
        return None
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


def tg_call(token, method, chat_id, text, reply_markup=None):
    """Returns (ok, error_code, description)."""
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"}
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup)
    url = (f"https://api.telegram.org/bot{token}/{method}?"
           + urllib.parse.urlencode(params))
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


def tg_send(chat_id, text, reply_markup=None):
    """Send a signal via the signals bot. Returns (ok, needs_start)."""
    ok, code, desc = tg_call(SIGNALS_TOKEN, "sendMessage", chat_id, text, reply_markup=reply_markup)
    if ok:
        return True, False
    # 403 = member never pressed Start in the signals bot (or blocked it).
    needs_start = (code == 403) or ("chat not found" in desc.lower()) \
        or ("can't initiate" in desc.lower()) or ("blocked" in desc.lower())
    log(f"SEND-FAIL chat={chat_id} code={code} desc={desc[:120]}")
    return False, needs_start


def tg_send_photo(chat_id, png, caption, reply_markup=None):
    """Send a chart PNG with caption via the signals bot. (ok, needs_start)."""
    boundary = "----TWSigChart"
    body = b""
    for k, v in (("chat_id", str(chat_id)), ("caption", caption[:1024]),
                 ("parse_mode", "HTML")):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\""
                 f"\r\n\r\n{v}\r\n").encode()
    if reply_markup is not None:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"reply_markup\""
                 f"\r\n\r\n{json.dumps(reply_markup)}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
             f"filename=\"signal.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
    body += png + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{SIGNALS_TOKEN}/sendPhoto", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return bool(json.loads(r.read().decode()).get("ok")), False
    except urllib.error.HTTPError as ex:
        try:
            desc = json.loads(ex.read().decode()).get("description", "")
        except Exception:
            desc = str(ex)
        needs_start = ex.code == 403 or "chat not found" in desc.lower() \
            or "can't initiate" in desc.lower() or "blocked" in desc.lower()
        log(f"PHOTO-FAIL chat={chat_id} code={ex.code} desc={desc[:120]}")
        return False, needs_start
    except Exception as ex:
        log(f"PHOTO-FAIL chat={chat_id} {type(ex).__name__} {ex}")
        return False, False


def render_signal_chart(s):
    """Render dark M15 chart for one signal. None if unavailable."""
    try:
        # bot_v2.py requires BOT_TOKEN during import even though chart rendering
        # itself does not use it. Supply the admin bot token from our loaded env.
        os.environ.setdefault("BOT_TOKEN", TG.get("TELEGRAM_BOT_TOKEN", ""))
        sys.path.insert(0, "/home/ubuntu/tw-bot")
        import bot_v2 as bv2
        pair = str(s["pair"]).replace("/", "")
        m15 = bv2.get_candles(pair, "M15", 120)
        if not m15 or len(m15) < 10:
            log(f"CHART-SKIP {pair}: {len(m15 or [])} bars")
            return None
        png = bv2.render_chart(pair, m15[-96:], None,
                               (float(s["entry"]), float(s["sl"]), float(s["tp"])),
                               ("ENTRY", "SL", "TP"))
        return png
    except Exception as ex:
        log(f"CHART-ERR {s.get('pair')}: {type(ex).__name__} {ex}")
        return None


# ---------- Wallet Ticket (MP4) ----------
TICKET_DIR = Path("/home/ubuntu/web/Traderwatch-repo/engine/ticket")
TICKET_TMP = Path("/tmp/tw-ticket")
TICKET_ENABLED = True          # set False untuk kembali ke chart PNG

DECIMALS = {"BTC/USD": 2, "XAU/USD": 2, "USD/JPY": 3}
DEFAULT_DECIMALS = 5


def _decimals(pair):
    return DECIMALS.get(pair, DEFAULT_DECIMALS)


def _move_note(s, level, sign):
    pip = PIP.get(s["pair"], DEFAULT_PIP)
    n = abs(float(level) - float(s["entry"])) / pip
    if s["pair"] == "BTC/USD":
        return f"{sign}${n:,.2f}"
    return f"{sign}{n:.1f} pips"


GRADES = ("A+", "A", "B", "C")


def trade_grade(sid):
    """Gred trade (A+/A/B/C) yang ditentukan AI, dari bot.db."""
    try:
        import sqlite3
        db = sqlite3.connect("/home/ubuntu/tw-bot/bot.db", timeout=10)
        row = db.execute(
            "SELECT detail FROM trades WHERE supabase_id=? ORDER BY id DESC LIMIT 1",
            (str(sid),)).fetchone()
        db.close()
        if not row or not row[0]:
            return None
        g = str(json.loads(row[0]).get("grade") or "").strip().upper()
        return g if g in GRADES else None
    except Exception:
        return None


def ticket_caption(s):
    """Caption pendek: emoji + level + R:R + disclaimer."""
    d = _decimals(s["pair"])
    arrow = "🟢 BUY" if s["side"] == "BUY" else "🔴 SELL"
    pip = PIP.get(s["pair"], DEFAULT_PIP)
    e, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
    risk = abs(e - sl) / pip
    reward = abs(tp - e) / pip
    rr = reward / risk if risk else 0.0
    grade = trade_grade(s.get("id"))
    grade_line = f"🏅 Grade  {grade}\n" if grade else ""
    return (f"📡 {arrow} {s['pair']} · {s['timeframe']}\n\n"
            f"🎯 Entry  {e:,.{d}f}\n"
            f"🛡️ SL     {sl:,.{d}f}\n"
            f"💎 TP     {tp:,.{d}f}\n"
            f"⚖️ R:R    1 : {rr:.1f}\n"
            f"{grade_line}\n"
            "📊 Live price update. We give the signal, you decide whether to enter.\n"
            "⚠️ Not financial advice — trade at your own risk.")


def render_ticket_mp4(s):
    """Render Wallet Ticket MP4 for one signal. Returns path or None."""
    if not TICKET_ENABLED:
        return None
    try:
        sys.path.insert(0, str(TICKET_DIR))
        import render_ticket as rt
        TICKET_TMP.mkdir(parents=True, exist_ok=True)
        sig = {
            "pair": s["pair"],
            "timeframe": s["timeframe"],
            "side": str(s["side"]).upper(),
            "entry": float(s["entry"]),
            "sl": float(s["sl"]),
            "tp": float(s["tp"]),
            "decimals": _decimals(s["pair"]),
            "sl_note": _move_note(s, s["sl"], "-"),
            "tp_note": _move_note(s, s["tp"], "+"),
            "id": str(s.get("id", "")),
        }
        out = TICKET_TMP / f"sig-{s.get('id','x')}.mp4"
        rt.render_mp4(rt.load_signal(sig), str(out))
        if not out.exists() or out.stat().st_size < 5000:
            log(f"TICKET-EMPTY {s.get('pair')}")
            return None
        return str(out)
    except Exception as ex:
        log(f"TICKET-ERR {s.get('pair')}: {type(ex).__name__} {ex}")
        return None


def tg_send_animation(chat_id, mp4_path, caption, reply_markup=None):
    """Hantar MP4 senyap sebagai animation. (ok, needs_start)."""
    boundary = "----TWSigTicket"
    body = b""
    fields = [("chat_id", str(chat_id)), ("caption", caption[:1024]),
              ("parse_mode", "HTML"), ("width", "1080"),
              ("height", "1350"), ("duration", "5")]
    for k, v in fields:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\""
                 f"\r\n\r\n{v}\r\n").encode()
    if reply_markup is not None:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"reply_markup\""
                 f"\r\n\r\n{json.dumps(reply_markup)}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"animation\"; "
             f"filename=\"ticket.mp4\"\r\nContent-Type: video/mp4\r\n\r\n").encode()
    body += Path(mp4_path).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{SIGNALS_TOKEN}/sendAnimation", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return bool(json.loads(r.read().decode()).get("ok")), False
    except urllib.error.HTTPError as ex:
        try:
            desc = json.loads(ex.read().decode()).get("description", "")
        except Exception:
            desc = str(ex)
        needs_start = ex.code == 403 or "chat not found" in desc.lower() \
            or "can't initiate" in desc.lower() or "blocked" in desc.lower()
        log(f"ANIM-FAIL chat={chat_id} code={ex.code} desc={desc[:120]}")
        return False, needs_start
    except Exception as ex:
        log(f"ANIM-FAIL chat={chat_id} {type(ex).__name__} {ex}")
        return False, False


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


def _sent_path():
    return TEST_SENT_FILE if test_chat() is not None else SENT_FILE


def load_sent():
    p = _sent_path()
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            return set()
    return set()


def save_sent(sent):
    keep = sorted(sent, reverse=True)[:500]   # bound the file
    _sent_path().write_text(json.dumps(keep))


def fetch_targets():
    st, rows = http_json(
        f"{SB_URL}/rest/v1/profiles"
        "?select=id,name,plan,telegram_chat_id"
        "&plan=in.(pro,max)&telegram_chat_id=not.is.null",
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"})
    if st != 200:
        raise RuntimeError(f"profiles fetch {st}")
    rows = rows or []
    tc = test_chat()
    if tc is not None:
        rows = [r for r in rows if int(r["telegram_chat_id"]) == tc]
        log(f"TEST MODE: only chat {tc} ({len(rows)} target)")
    return rows


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


PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01, "BTC/USD": 1.0}
DEFAULT_PIP = 0.0001


MUTES_FILE = Path("/home/ubuntu/web/.tw-signal-mutes.json")


def is_muted(chat_id, sid):
    try:
        m = json.loads(MUTES_FILE.read_text())
        return str(sid) in m.get(str(chat_id), [])
    except Exception:
        return False


def build_kb(sid, chat_id):
    muted = is_muted(chat_id, sid)
    bell = "🔕 Alert: Off" if muted else "🔔 Alert: On"
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Detail Sniper", "callback_data": f"mb:detail:{sid}"},
                {"text": "🔬 Indepth Analysis", "callback_data": f"mb:indepth:{sid}"},
            ],
            [
                {"text": "📈 Chart", "callback_data": f"mb:chart:{sid}"},
                {"text": "✅ Status", "callback_data": f"mb:status:{sid}"},
            ],
            [
                {"text": bell, "callback_data": f"mb:toggle_mute:{sid}"},
            ],
        ]
    }


def move_text(s, value, sign=""):
    """BTC movement dalam USD; pair lain dalam pips."""
    if s["pair"] == "BTC/USD":
        return f"{sign}${value:,.2f}"
    return f"{sign}{value:.1f}p"


def price_text(s, value):
    d = 2 if s["pair"] == "BTC/USD" else (3 if s["pair"] == "USD/JPY" else 5)
    return f"{float(value):,.{d}f}" if s["pair"] == "BTC/USD" else f"{float(value):.{d}f}".rstrip("0").rstrip(".")


def fmt(s):
    arrow = "🟢 BUY" if s["side"] == "BUY" else "🔴 SELL"
    pip = PIP.get(s["pair"], DEFAULT_PIP)
    entry, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
    sl_p = abs(entry - sl) / pip
    tp_p = abs(tp - entry) / pip
    rr = tp_p / sl_p if sl_p else 0.0
    levels = ("<pre>"
              f"Entry   {price_text(s, s['entry'])}\n"
              f"SL      {price_text(s, s['sl'])}   -{move_text(s, sl_p)}\n"
              f"TP      {price_text(s, s['tp'])}   +{move_text(s, tp_p)}\n"
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
            f'👉 <a href="https://rinfinity.com/en/welcome-bonus?a=wnzx">Claim your $30 welcome bonus</a>')


LOCK = Path("/tmp/tw-sender.lock")


def main():
    # Guard against overlapping runs (cron tick + instant trigger from the
    # admin console). Without this, both could read the same sent-ids file
    # and deliver the same signal twice.
    if LOCK.exists():
        try:
            age = time.time() - LOCK.stat().st_mtime
        except OSError:
            age = 0
        if age < 180:
            log(f"SKIP already running ({age:.0f}s)")
            return 0
        log(f"WARN stale lock ({age:.0f}s) removed")
        LOCK.unlink(missing_ok=True)
    LOCK.write_text(str(os.getpid()))
    try:
        return _run()
    finally:
        LOCK.unlink(missing_ok=True)


def _run():
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
        # Wallet Ticket MP4 (format baharu yang diluluskan). Jika gagal,
        # jatuh ke chart PNG, kemudian teks — signal tidak boleh hilang.
        mp4 = render_ticket_mp4(s)
        caption = ticket_caption(s) if mp4 else fmt(s)
        png = None if mp4 else render_signal_chart(s)
        ok_all = True
        for t in targets:
            if count >= MAX_MSGS:
                log("hit MAX_MSGS cap, remaining signals will retry next run")
                return 1
            chat_id = t["telegram_chat_id"]
            if is_muted(chat_id, s["id"]):
                continue
            kb = build_kb(s["id"], chat_id)
            if mp4:
                ok, needs_start = tg_send_animation(chat_id, mp4, caption, reply_markup=kb)
                if not ok:
                    ok, needs_start = tg_send_photo(chat_id, png, caption,
                                                    reply_markup=kb) if png else (False, needs_start)
                    if not ok:
                        ok, needs_start = tg_send(chat_id, fmt(s), reply_markup=kb)
            elif png:
                ok, needs_start = tg_send_photo(chat_id, png, caption, reply_markup=kb)
                if not ok:
                    ok, needs_start = tg_send(chat_id, fmt(s), reply_markup=kb)
            else:
                ok, needs_start = tg_send(chat_id, fmt(s), reply_markup=kb)
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
        # Buang MP4 sementara supaya /tmp tidak penuh.
        if mp4:
            try:
                Path(mp4).unlink(missing_ok=True)
            except Exception:
                pass
    save_sent(sent)
    log(f"DONE sent={count} nudged={nudged} marked={len(sent)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL {type(e).__name__} {e}")
        sys.exit(1)
