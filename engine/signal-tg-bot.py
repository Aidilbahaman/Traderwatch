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
import datetime
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 30
# Tempoh sah setup seperti yang dipaparkan dalam analisis sniper (minit).
VALID_MIN = 45
POLL_WAIT = 25
LOCK = Path("/tmp/twreg-bot.lock")
# Flock di fail yang sama: safeguard sebenar single-instance. PID file
# sahaja tidak cukup — dua proses boleh hidup serentak bila satu baru
# start sebelum yang lama mati, dan dua getUpdates pada token sama
# mencetuskan ralat 409 "terminated by other getUpdates request".
LOCK_FD = None
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

# Admin contact. tg://user?id= membuka DM admin terus tanpa mendedahkan
# nombor ID kepada member — teks pautan yang dipaparkan ialah "Message Admin".
ADMIN_USER_ID = (TG.get("TELEGRAM_ADMIN_CHAT_ID") or "").strip()
ADMIN_LINK = (f'<a href="tg://user?id={ADMIN_USER_ID}">Message Admin</a>'
              if ADMIN_USER_ID.isdigit() else "the admin")

# Feedback member: rating 1-5 + nota pilihan, disimpan sebagai JSONL untuk
# disemak admin. Tiada quote diterbitkan tanpa kebenaran member.
FEEDBACK_FILE = Path("/home/ubuntu/web/.member-feedback.jsonl")
PENDING_FEEDBACK = {}          # chat_id -> {"rating": n, "at": epoch}
FEEDBACK_TTL = 900             # 15 minit untuk tinggalkan nota
# Member yang diminta feedback secara terus: mesej biasa mereka disimpan
# walaupun tiada rating. Fail supaya tahan restart service.
FEEDBACK_AWAIT_FILE = Path("/home/ubuntu/web/.feedback-await.json")
FEEDBACK_AWAIT_TTL = 604800    # 7 hari untuk membalas


def _load_await():
    try:
        return {int(k): float(v) for k, v in
                json.loads(FEEDBACK_AWAIT_FILE.read_text()).items()}
    except Exception:
        return {}


def _save_await(d):
    try:
        FEEDBACK_AWAIT_FILE.write_text(json.dumps({str(k): v for k, v in d.items()}))
    except Exception as e:
        log(f"FEEDBACK-AWAIT-ERR {type(e).__name__} {e}")


def awaiting_feedback(chat_id):
    """True kalau member ini sedang diminta feedback dan tempoh belum tamat."""
    d = _load_await()
    at = d.get(int(chat_id))
    if not at:
        return False
    if time.time() - at > FEEDBACK_AWAIT_TTL:
        d.pop(int(chat_id), None)
        _save_await(d)
        return False
    return True


def clear_await(chat_id):
    d = _load_await()
    if d.pop(int(chat_id), None) is not None:
        _save_await(d)


def save_feedback(chat_id, rating, note=""):
    rec = {"chat_id": int(chat_id), "rating": int(rating),
           "note": (note or "").strip()[:500],
           "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        with FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"FEEDBACK-WRITE-ERR {type(e).__name__} {e}")
        return False
    return True


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


REPO = Path("/home/ubuntu/web/Traderwatch-repo")
STATUS_FILE = REPO / "signal-status.json"
MUTES_FILE = Path("/home/ubuntu/web/.tw-signal-mutes.json")
PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001


def esc(x):
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def get_signal(sid):
    rows = sb_get(f"signals?select=id,pair,side,entry,sl,tp,timeframe,posted_at"
                  f"&id=eq.{sid}&limit=1")
    return rows[0] if rows else None


def key_for(pair, iso):
    """Same key shape signal-status.py writes: CODE_YYYYMMDD_HHMMSS (KL time)."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone(timedelta(hours=8)))
    code = "".join(ch for ch in str(pair).upper() if ch.isalpha())
    return f"{code}_{d:%Y%m%d}_{d:%H%M%S}"


def signal_status(sid, sig):
    """Exact lookup by pair+timestamp key, never by pair alone."""
    try:
        state = json.loads(STATUS_FILE.read_text())
    except Exception:
        return None
    key = key_for(sig["pair"], sig["posted_at"])
    info = (state.get("signals") or {}).get(key)
    return (key, info) if info else None


def analysis_for(sid):
    """Ambil analisis penuh (bot.db trades.detail) ikut supabase_id."""
    try:
        import sqlite3
        db = sqlite3.connect("/home/ubuntu/tw-bot/bot.db", timeout=10)
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT pair,poi_low,poi_high,entry,sl,tp1,tp2,rr1,rr2,detail "
            "FROM trades WHERE supabase_id=? ORDER BY id DESC LIMIT 1",
            (str(sid),)).fetchone()
        db.close()
        if not row:
            return None
        out = {k: row[k] for k in
               ("pair", "poi_low", "poi_high", "entry", "sl", "tp1", "tp2",
                "rr1", "rr2")}
        try:
            out.update(json.loads(row["detail"] or "{}"))
        except Exception:
            pass
        return out
    except Exception as ex:
        log(f"ANALYSIS-ERR {sid}: {type(ex).__name__} {ex}")
        return None


def _v(a, key, dash="—"):
    """English value first (key_en), else the original field, else dash."""
    for k in (f"{key}_en", key):
        val = a.get(k)
        if val is not None and not (isinstance(val, str) and not val.strip()):
            return esc(str(val).strip())
    return dash


def indepth_text(sig, a):
    """Analisis sniper penuh dalam Bahasa Inggeris (tab Indepth Analysis)."""
    pair = str(sig["pair"]).replace("/", "")
    side = str(sig["side"]).upper()
    lo = a.get("poi_low")
    hi = a.get("poi_high")
    zone = (f"{lo} – {hi}" if lo is not None and hi is not None else "—")
    rr1 = a.get("rr1")
    rr2 = a.get("rr2")
    rr1_s = f"{float(rr1):.1f}" if rr1 is not None else "—"
    rr2_s = f"{float(rr2):.1f}" if rr2 is not None else "—"
    return (
        f"🎯 <b>SNIPER ANALYSIS: {pair}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"[ <b>CONCLUSION</b> ]\n"
        f"› Setup: Grade {_v(a,'grade')}\n"
        f"› Confidence: {_v(a,'confidence')} / 10\n"
        f"› Bias M5: {_v(a,'bias_m5')}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"[ <b>EXECUTION PLAN</b> ]\n"
        f"{_v(a,'plan')}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"[ <b>COORDINATES &amp; TACTICS</b> ]\n\n"
        f"📊 <b>H1 Context</b>\n"
        f"› Trend: {_v(a,'h1_trend')}\n"
        f"› Key Levels: {_v(a,'h1_levels')}\n"
        f"› Confluence Rating: {_v(a,'h1_confluence')}\n\n"
        f"📈 <b>M15 Context (Prey Context)</b>\n"
        f"{_v(a,'m15_context')}\n\n"
        f"🎯 <b>Liquidity Target (DOL M15)</b>\n"
        f"› Type: {_v(a,'dol_type')}\n"
        f"› Level: {_v(a,'dol_levels')}\n\n"
        f"🏯 <b>Ambush Zone (POI)</b>\n"
        f"› Area: {zone}\n"
        f"› Type: {_v(a,'poi_type')}\n\n"
        f"💥 <b>Entry Trigger (M1)</b>\n"
        f"{_v(a,'trigger_m1')}\n\n"
        f"🎯 <b>Trigger Conditions (Two-Stage)</b>\n"
        f"› Stage 1 (POI Alert): price enters {zone}\n"
        f"› Stage 2 (Confirmed Entry): rejection wick / MSS forms on M1\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"[ <b>MISSION PARAMETERS</b> ]\n"
        f"🎯 Entry : {zone}\n"
        f"🛑 Stop Loss : {_v(a,'sl')}\n"
        f"💎 TP 1 : {_v(a,'tp1')} | R:R: 1:{rr1_s}\n"
        f"💎 TP 2 : {_v(a,'tp2')} | R:R: 1:{rr2_s}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"[ <b>JUSTIFICATION &amp; RISK</b> ]\n"
        f"› Rating Reason:\n{_v(a,'rating_reason')}\n\n"
        f"› Timeframe Alignment: {_v(a,'alignment')}\n\n"
        f"🗒️ <b>Special Note:</b>\n{_v(a,'note')}\n\n"
        f"› Invalidation:\n{_v(a,'invalidation')}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ Validity: ~{VALID_MIN} minutes\n\n"
        f"<i>Educational content only. Not financial advice.</i>")


def detail_text(sig):
    pip = PIP.get(sig["pair"], DEFAULT_PIP)
    entry, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    sl_p = abs(entry - sl) / pip
    tp_p = abs(tp - entry) / pip
    rr = tp_p / sl_p if sl_p else 0
    arrow = "🟢 BUY" if sig["side"] == "BUY" else "🔴 SELL"
    return (f"📋 <b>DETAIL SNIPER</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{arrow} <b>{esc(sig['pair'])}</b> · {esc(sig['timeframe'])}\n\n"
            f"<pre>Entry   {sig['entry']}\n"
            f"SL      {sig['sl']}   -{sl_p:.1f}p\n"
            f"TP      {sig['tp']}   +{tp_p:.1f}p\n"
            f"R:R     1 : {rr:.1f}</pre>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Cara guna:</b>\n"
            f"• Entry pada harga semasa atau tunggu retest\n"
            f"• SL wajib dipasang — jangan alih ke bawah\n"
            f"• TP1: tutup 50%, baki trailing ke BE\n\n"
            f"<i>Educational content only. Not financial advice.</i>")


def status_text(sig):
    hit = signal_status(sig["id"], sig)
    arrow = "🟢 BUY" if sig["side"] == "BUY" else "🔴 SELL"
    if not hit:
        state_line = "⏳ <b>AKTIF</b> — belum ada rekod penutupan"
    else:
        key, info = hit
        st = str(info.get("status", "")).lower()
        pips = info.get("pips")
        if st == "tp":
            state_line = f"✅ <b>TP HIT</b> — {pips:+.1f} pips" if pips is not None else "✅ <b>TP HIT</b>"
        elif st == "sl":
            state_line = f"❌ <b>SL HIT</b> — {pips:+.1f} pips" if pips is not None else "❌ <b>SL HIT</b>"
        elif st == "expired":
            state_line = "⌛ <b>EXPIRED</b>"
        elif st == "cancelled":
            state_line = "🚫 <b>CANCELLED</b>"
        else:
            state_line = "⏳ <b>AKTIF</b> — sedang dipantau"
    return (f"📊 <b>STATUS SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{arrow} <b>{esc(sig['pair'])}</b> · {esc(sig['timeframe'])}\n"
            f"Entry <code>{sig['entry']}</code> · SL <code>{sig['sl']}</code> · TP <code>{sig['tp']}</code>\n\n"
            f"{state_line}\n\n"
            f"<i>Dikemas kini setiap 15 minit oleh TraderWatch.</i>")


def toggle_mute(chat_id, sid):
    try:
        data = json.loads(MUTES_FILE.read_text())
    except Exception:
        data = {}
    key = str(chat_id)
    ids = set(data.get(key, []))
    if str(sid) in ids:
        ids.discard(str(sid))
        muted = False
    else:
        ids.add(str(sid))
        muted = True
    data[key] = sorted(ids)
    MUTES_FILE.write_text(json.dumps(data, indent=1))
    return muted


def send_chart(chat_id, sig):
    """Render a chart PNG from Swissquote bars and send it."""
    try:
        sys.path.insert(0, str(REPO))
        from engine.sq_collector import candles_from_bars
        pair = sig["pair"].replace("/", "")
        bars = candles_from_bars(pair, "M15", 96)
        if len(bars) < 20:
            reply(chat_id, "📈 Chart belum tersedia — data pasaran baru dikumpul "
                           f"({len(bars)} bar). Cuba lagi sebentar.")
            return
        out = Path(f"/tmp/tw-chart-{sig['id']}.png")
        sys.path.insert(0, "/home/ubuntu/tw-bot/lib")
        import mplfinance as mpf
        import matplotlib.pyplot as plt
        import pandas as pd
        # Guna timestamp SEBENAR setiap bar. Versi lama reka grid sendiri
        # (date_range end=now) sehingga paksi X menipu, lubang data hilang
        # dan candle tersusun pada jarak yang tidak wujud.
        idx = (pd.to_datetime([b["t"] for b in bars], utc=True)
               .tz_convert("Asia/Kuala_Lumpur").tz_localize(None))
        df = pd.DataFrame({"Open": [b["o"] for b in bars],
                           "High": [b["h"] for b in bars],
                           "Low": [b["l"] for b in bars],
                           "Close": [b["c"] for b in bars]}, index=idx)
        mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                                   edge="inherit", wick="inherit")
        style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                                   facecolor="#0f0f0f", figcolor="#0f0f0f",
                                   gridcolor="#1c1c1c")
        lv = [float(sig["entry"]), float(sig["sl"]), float(sig["tp"])]
        bar_l = [float(b["l"]) for b in bars]
        bar_h = [float(b["h"]) for b in bars]
        lo_p = min(bar_l + lv)
        hi_p = max(bar_h + lv)
        span = hi_p - lo_p or (abs(hi_p) * 0.001 or 1.0)
        pad_n = max(6, int(len(df) * 0.43))
        fig, axes = mpf.plot(df, type="candle", style=style, figsize=(10, 6),
                             datetime_format="%d/%m %H:%M", xrotation=0,
                             returnfig=True, tight_layout=True,
                             xlim=(idx[0], idx[-1] + pd.Timedelta(minutes=15 * pad_n)))
        ax = axes[0]
        ax.set_ylim(lo_p - span * 0.07, hi_p + span * 0.07)
        ax.set_title(f"{sig['pair']} · {sig['timeframe']} · Swissquote · {len(bars)} bar",
                     fontsize=12, color="#e6e6e6", pad=8)
        # Label di dalam axes, clip_on supaya bbox_inches tak meledak
        for lvl, lab, col in zip(lv, ("ENTRY", "SL", "TP"),
                                 ("#8ab4ff", "#ff6b6b", "#4dd0a5")):
            ax.axhline(lvl, color=col, linestyle="--", linewidth=1.8, alpha=0.95, zorder=5)
            ax.text(0.006, lvl, f" {lab} {lvl} ", transform=ax.get_yaxis_transform(),
                    va="bottom", ha="left", fontsize=8.5, color="#0f0f0f",
                    bbox=dict(boxstyle="round,pad=0.18", fc=col, ec="none", alpha=0.95),
                    zorder=6, clip_on=True)
        gaps = []
        for a, b in zip(bars, bars[1:]):
            try:
                d = (pd.Timestamp(b["t"]) - pd.Timestamp(a["t"])).total_seconds() / 60
            except Exception:
                continue
            if d > 30:
                gaps.append(int(d))
        if gaps:
            ax.annotate("⚠ lubang data: " + ", ".join(f"{g} min" for g in gaps[:3]),
                        xy=(0.01, 0.02), xycoords="axes fraction",
                        fontsize=8, color="#ffb74d")
        fig.savefig(out, dpi=100, bbox_inches="tight", facecolor="#0f0f0f")
        plt.close(fig)
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        import urllib.request as _u
        # multipart manual
        boundary = "----TWChart"
        body = b""
        for k, v in (("chat_id", str(chat_id)),
                     ("caption", f"📈 {sig['pair']} · {sig['timeframe']}")):
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
                 f"filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
        body += out.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = _u.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with _u.urlopen(req, timeout=30) as r:
            r.read()
    except Exception as e:
        log(f"CHART-ERR {type(e).__name__} {e}")
        reply(chat_id, "📈 Chart gagal dijana. Buka dashboard untuk chart penuh: "
                       "https://aidilbahaman.github.io/Traderwatch/members.html#charts")


def handle_callback(cq):
    cq_id = cq.get("id")
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id:
        return
    if data.startswith("fb:"):
        # Rating 1-5 dipilih; minta nota ringkas sebagai mesej seterusnya.
        try:
            rating = int(data.split(":", 1)[1])
        except ValueError:
            rating = 0
        tg("answerCallbackQuery", callback_query_id=cq_id,
           text=f"Terima kasih — {rating}/5 dicatat")
        PENDING_FEEDBACK[int(chat_id)] = {"rating": rating,
                                          "at": time.time()}
        reply(chat_id, "✅ Rating dicatat.\n\n"
                       "Sekarang taip satu atau dua ayat: apa yang membantu, "
                       "atau apa yang boleh diperbaiki?\n\n"
                       "Taip /skip kalau tak nak tinggalkan nota.")
        return
    tg("answerCallbackQuery", callback_query_id=cq_id)
    if not data.startswith("mb:"):
        return
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    sid = parts[2] if len(parts) > 2 else ""
    try:
        sid_i = int(sid)
    except ValueError:
        return
    sig = get_signal(sid_i)
    if not sig:
        reply(chat_id, "Signal ini tidak dijumpai.")
        return
    if action == "detail":
        reply(chat_id, detail_text(sig))
    elif action == "indepth":
        a = analysis_for(sig["id"])
        if not a:
            reply(chat_id, "🔬 In-depth analysis is not available for this "
                           "signal. Only manually analysed setups carry it.")
        else:
            reply(chat_id, indepth_text(sig, a))
    elif action == "status":
        reply(chat_id, status_text(sig))
    elif action == "chart":
        send_chart(chat_id, sig)
    elif action == "toggle_mute":
        muted = toggle_mute(chat_id, sid_i)
        tg("answerCallbackQuery", callback_query_id=cq_id,
           text=("🔕 Alert dimatikan untuk signal ini" if muted
                 else "🔔 Alert dihidupkan semula"), show_alert=True)


def handle(msg):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id:
        return
    # Nota feedback: mesej biasa selepas member pilih rating.
    pend = PENDING_FEEDBACK.get(int(chat_id))
    # Mesej biasa — simpan sebagai nota rating jika dalam sesi rating,
    # ATAU sebagai feedback terus jika sedang menunggu respons.
    if pend and text and not text.startswith("/"):
        PENDING_FEEDBACK.pop(int(chat_id), None)
        if time.time() - float(pend.get("at") or 0) > FEEDBACK_TTL:
            reply(chat_id, "⌛ Sesi feedback dah tamat. Taip /feedback untuk mula semula.")
            return
        if save_feedback(chat_id, pend.get("rating") or 0, text):
            reply(chat_id, "🙏 Terima kasih! Feedback awak dah disimpan.\n\n"
                           "Kami hanya terbitkan quote dengan kebenaran awak.")
        else:
            reply(chat_id, "⚠️ Feedback tak dapat disimpan. Cuba lagi nanti.")
        return
    if not chat_id:
        return
    # Feedback langsung (tanpa rating) — minta rating dulu.
    if awaiting_feedback(chat_id) and text and not text.startswith("/"):
        clear_await(chat_id)
        kb = json.dumps({"inline_keyboard": [[
            {"text": "⭐ 1", "callback_data": "fb:1"},
            {"text": "⭐ 2", "callback_data": "fb:2"},
            {"text": "⭐ 3", "callback_data": "fb:3"},
            {"text": "⭐ 4", "callback_data": "fb:4"},
            {"text": "⭐ 5", "callback_data": "fb:5"},
        ]]})
        # Simpan dulu sebagai pending supaya nota rating boleh guna.
        PENDING_FEEDBACK[int(chat_id)] = {"rating": 0, "note": text.strip()[:500],
                                            "at": time.time()}
        reply(chat_id, f"Sudah terima:\n<i>{text.strip()[:200]}</i>\n\n"
                       "Beri rating untuk signal terbaru yang awak terima:\n"
                       "(Taip /skip kalau nak batal.)")
        return
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    name = (chat.get("first_name") or "").strip()

    if cmd == "/feedback":
        kb = json.dumps({"inline_keyboard": [[
            {"text": "⭐ 1", "callback_data": "fb:1"},
            {"text": "⭐ 2", "callback_data": "fb:2"},
            {"text": "⭐ 3", "callback_data": "fb:3"},
            {"text": "⭐ 4", "callback_data": "fb:4"},
            {"text": "⭐ 5", "callback_data": "fb:5"},
        ]]})
        tg("sendMessage", chat_id=chat_id,
           text=("💬 <b>How is TraderWatch working for you?</b>\n\n"
                 "Pick a rating below. You can then add a short note — and "
                 "nothing is published unless you say yes."),
           parse_mode="HTML", reply_markup=kb)
        return
    if cmd == "/skip":
        PENDING_FEEDBACK.pop(int(chat_id), None)
        reply(chat_id, "Okay, skipped. Taip /feedback bila-bila masa.")
        return

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
                       "/stop — unlink this chat\n"
                       "/feedback — rate TraderWatch and leave a note\n"
                       f"/admin — {ADMIN_LINK}")
    elif cmd == "/admin":
        reply(chat_id, "👤 <b>Contact the admin</b>\n\n"
                       "Found a bug or error? Have an idea to improve the "
                       "system? Send a message directly:\n\n"
                       f"➡️ {ADMIN_LINK}\n\n"
                       "Every report is read. Thanks for helping us improve.")


def main():
    global LOCK_FD
    # Single-instance enforcement dengan flock: dua proses tidak boleh
    # memegang flock yang sama, jadi hanya satu boleh poll getUpdates
    # pada token bot. Ini punca sebenar ralat 409 sebelum ini.
    LOCK_FD = open(LOCK, "w")
    try:
        fcntl.flock(LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("SKIP instance lain sedang poll — keluar")
        LOCK_FD.close()
        LOCK_FD = None
        return 0
    LOCK_FD.write(str(os.getpid()))
    LOCK_FD.flush()
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
                     allowed_updates='["message","callback_query"]')
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
                cq = upd.get("callback_query")
                if cq:
                    try:
                        handle_callback(cq)
                    except Exception as e:
                        log(f"ERR callback {type(e).__name__} {e}")
    finally:
        if LOCK_FD is not None:
            try:
                fcntl.flock(LOCK_FD, fcntl.LOCK_UN)
            except OSError:
                pass
            LOCK_FD.close()
            LOCK_FD = None
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("stopped")
