#!/usr/bin/env python3
"""TraderWatch Starling Automated IB Onboarding Bot (Telegram).

Automates the entire Introducing Broker (IB) onboarding workflow for RoboForex
(IB code: wnzx) and syncs verified members to the TraderWatch Supabase DB
(profiles.plan = 'pro', telegram_chat_id) to unlock full Unlimited Analyst features:
  - Cheerful 2D anime + Starling welcoming video on /start (cached via Telegram file_id)
  - Bilingual (BM / EN) guided menus (Register, Transfer IB, Deposit/MT5, Verify)
  - 3-step Verify flow: MT5 Account ID -> RoboForex Email (+ optional photo) -> TraderWatch Email
  - Pluggable IB Verification Engine:
      * Auto-API mode when ROBOFOREX_API_KEY + ROBOFOREX_AUTO_VERIFY=1 are set
      * 1-Click Admin Approve/Reject card mode while waiting for Partner API key
  - Automatic Supabase DB sync on approval (upgrades profiles.plan = 'pro')
  - 24/7 Starling AI Q&A powered by TraderWatch LLM gateway + starling_kb.json
  - SQLite WAL state at state/starling-ib.db
"""
import json
import logging
import os
import pathlib
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
KB_PATH = REPO / "bot" / "starling_kb.json"
DB_PATH = REPO / "state" / "starling-ib.db"
WELCOME_VIDEO_PATH = REPO / "bot" / "assets" / "starling-welcome.mp4"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [starling-ib] %(levelname)s %(message)s",
)
log = logging.getLogger("starling-ib")


def load_env_files():
    """Load key=value pairs from secret env files without overriding explicit env."""
    candidates = [
        pathlib.Path("/home/ubuntu/.secrets/starling-ib.env"),
        pathlib.Path("/home/ubuntu/.secrets/telegram.env"),
        pathlib.Path("/home/ubuntu/.secrets/supabase.env"),
        pathlib.Path("/home/ubuntu/.hermes/.env"),
        REPO / "engine" / ".env",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception as e:
            log.warning("Could not read %s: %s", p, e)


load_env_files()

BOT_TOKEN = os.environ.get("STARLING_IB_BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in (
        os.environ.get("STARLING_ADMIN_IDS")
        or os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        or ""
    ).split(",")
    if x.strip().lstrip("-").isdigit()
}

# RoboForex Partner API config (falls back to RINFINITY_* for compatibility)
ROBOFOREX_API_KEY = (
    os.environ.get("ROBOFOREX_API_KEY") or os.environ.get("RINFINITY_API_KEY") or ""
).strip()
ROBOFOREX_API_URL = (
    os.environ.get("ROBOFOREX_API_URL") or os.environ.get("RINFINITY_API_URL") or ""
).strip()
ROBOFOREX_AUTO_VERIFY = (
    os.environ.get("ROBOFOREX_AUTO_VERIFY") or os.environ.get("RINFINITY_AUTO_VERIFY") or "0"
).strip().lower() in ("1", "true", "yes")

SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

LLM_URL = os.environ.get("STARLING_LLM_URL", "https://serveras.click/v1/chat/completions")
LLM_MODEL = os.environ.get("STARLING_LLM_MODEL", "asai/freemodel-4-ds-v4.1flash")
LLM_KEY = (
    os.environ.get("STARLING_LLM_KEY")
    or os.environ.get("HERMES_CUSTOM_SERVERAS_CLICK_API_KEY")
    or os.environ.get("OPENROUTER_API_KEY")
    or ""
).strip()

KB = json.loads(KB_PATH.read_text())

USER_STATE: dict[int, dict] = {}
LAST_AI_CALL: dict[int, float] = {}
AI_COOLDOWN_S = 3.0


# ------------------------------------------------------------------ SQLite DB
def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS ib_leads (
            tg_id          INTEGER PRIMARY KEY,
            username       TEXT,
            first_name     TEXT,
            lang           TEXT NOT NULL DEFAULT 'ms',
            stage          TEXT NOT NULL DEFAULT 'new',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            clicked_reg_at TEXT,
            followup_sent  INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ib_submissions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id          INTEGER NOT NULL,
            username       TEXT,
            account_id     TEXT NOT NULL,
            email          TEXT NOT NULL,
            tw_email       TEXT,
            photo_file_id  TEXT,
            status         TEXT NOT NULL DEFAULT 'pending',
            verify_source  TEXT NOT NULL DEFAULT 'admin',
            sb_synced      INTEGER NOT NULL DEFAULT 0,
            note           TEXT,
            created_at     TEXT NOT NULL,
            resolved_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS bot_kv (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ib_sub_tg ON ib_submissions(tg_id, status);
        """
    )
    # Auto-migrate existing DBs cleanly
    cols = {r[1] for r in con.execute("PRAGMA table_info(ib_submissions)").fetchall()}
    if "tw_email" not in cols:
        con.execute("ALTER TABLE ib_submissions ADD COLUMN tw_email TEXT")
    if "sb_synced" not in cols:
        con.execute("ALTER TABLE ib_submissions ADD COLUMN sb_synced INTEGER NOT NULL DEFAULT 0")
    con.commit()
    con.close()


def db_conn():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def kv_get(k: str) -> str:
    con = db_conn()
    try:
        r = con.execute("SELECT v FROM bot_kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else ""
    finally:
        con.close()


def kv_set(k: str, v: str):
    con = db_conn()
    try:
        con.execute("INSERT OR REPLACE INTO bot_kv (k, v) VALUES (?, ?)", (k, v))
        con.commit()
    finally:
        con.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_lead(user, lang=None, stage=None, clicked_reg=False):
    con = db_conn()
    try:
        ts = now_iso()
        row = con.execute("SELECT * FROM ib_leads WHERE tg_id=?", (user.id,)).fetchone()
        if not row:
            use_lang = lang or ("ms" if (user.language_code or "").startswith(("ms", "id")) else "en")
            con.execute(
                """INSERT INTO ib_leads (tg_id, username, first_name, lang, stage, created_at, updated_at, clicked_reg_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user.id,
                    user.username or "",
                    user.first_name or "",
                    use_lang,
                    stage or "new",
                    ts,
                    ts,
                    ts if clicked_reg else None,
                ),
            )
            con.commit()
            return use_lang
        use_lang = lang or row["lang"] or "ms"
        use_stage = stage or row["stage"]
        reg_ts = ts if clicked_reg else row["clicked_reg_at"]
        con.execute(
            """UPDATE ib_leads
               SET username=?, first_name=?, lang=?, stage=?, updated_at=?, clicked_reg_at=?
               WHERE tg_id=?""",
            (user.username or "", user.first_name or "", use_lang, use_stage, ts, reg_ts, user.id),
        )
        con.commit()
        return use_lang
    finally:
        con.close()


def get_lang(tg_id: int, default="ms") -> str:
    con = db_conn()
    try:
        r = con.execute("SELECT lang FROM ib_leads WHERE tg_id=?", (tg_id,)).fetchone()
        return r["lang"] if r and r["lang"] in ("ms", "en") else default
    finally:
        con.close()


# ---------------------------------------------------- Supabase TraderWatch DB
async def sync_traderwatch_db(tw_email: str, tg_id: int) -> tuple[bool, str]:
    """Unlock full features (plan='pro') & bind telegram_chat_id in Supabase profiles."""
    if not (SB_URL and SB_KEY and tw_email):
        return (False, "Supabase env not configured")
    headers = {
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            q_email = urllib.parse.quote(tw_email.strip().lower(), safe="")
            r = await client.get(
                f"{SB_URL}/rest/v1/profiles?email=ilike.{q_email}&select=id,email,plan",
                headers=headers,
            )
            if r.status_code != 200:
                log.warning("Supabase lookup HTTP %s: %s", r.status_code, r.text[:160])
                return (False, f"Lookup HTTP {r.status_code}")
            rows = r.json()
            if not rows:
                return (False, "Email not registered in TraderWatch yet")
            uid = rows[0]["id"]
            r2 = await client.patch(
                f"{SB_URL}/rest/v1/profiles?id=eq.{urllib.parse.quote(str(uid), safe='')}",
                headers=headers,
                json={"plan": "pro", "telegram_chat_id": str(tg_id)},
            )
            if r2.status_code not in (200, 204):
                log.warning("Supabase patch HTTP %s: %s", r2.status_code, r2.text[:160])
                return (False, f"Update HTTP {r2.status_code}")
            log.info("Synced TraderWatch profile %s (%s) -> plan=pro, tg=%s", uid, tw_email, tg_id)
            return (True, f"Unlocked PRO for {tw_email}")
    except Exception as e:
        log.warning("Supabase sync error: %s", e)
        return (False, f"Sync error: {type(e).__name__}")


# ----------------------------------------------------------- Partner Verifier
async def verify_with_roboforex_api(account_id: str, email: str) -> tuple[str, str]:
    """Pluggable RoboForex Partner API verifier."""
    if not (ROBOFOREX_AUTO_VERIFY and ROBOFOREX_API_KEY and ROBOFOREX_API_URL):
        return ("manual", "")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                ROBOFOREX_API_URL,
                params={"account_id": account_id, "email": email, "partner_code": KB["ib_code"]},
                headers={"Authorization": f"Bearer {ROBOFOREX_API_KEY}"},
            )
            if r.status_code != 200:
                log.warning("RoboForex API HTTP %s: %s", r.status_code, r.text[:160])
                return ("manual", f"API HTTP {r.status_code}")
            data = r.json()
            if data.get("verified") is True or data.get("under_ib") is True:
                return ("approved", "Auto-verified via RoboForex Partner API")
            if data.get("verified") is False or data.get("under_ib") is False:
                return ("rejected", data.get("reason") or "Account not linked to IB code wnzx")
            return ("manual", "Unexpected API payload")
    except Exception as e:
        log.warning("RoboForex API verify error: %s", e)
        return ("manual", f"API error: {type(e).__name__}")


# ------------------------------------------------------------------ AI Reply
async def ask_starling_ai(user_text: str, lang: str) -> str:
    if not LLM_KEY:
        return (
            "Saya Starling ✨ Guna menu di bawah untuk panduan daftar RoboForex, tukar IB, deposit MT5, atau sahkan akaun IB anda!"
            if lang == "ms"
            else "I'm Starling ✨ Use the menu below for the RoboForex registration guide, IB transfer, MT5 deposit, or IB verification!"
        )
    lang_hint = "Reply in Bahasa Melayu." if lang == "ms" else "Reply in English."
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": KB["system_prompt"] + "\n" + lang_hint},
            {"role": "user", "content": user_text[:800]},
        ],
        "temperature": 0.4,
        "max_tokens": 260,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                LLM_URL,
                json=payload,
                headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
            )
            if r.status_code == 200:
                data = r.json()
                txt = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if txt:
                    return txt
            log.warning("LLM HTTP %s: %s", r.status_code, r.text[:160])
    except Exception as e:
        log.warning("LLM call error: %s", e)
    return (
        "Maaf, Starling sedang sibuk sebentar ✨ Anda boleh guna butang menu di bawah untuk panduan daftar & sahkan akaun RoboForex."
        if lang == "ms"
        else "Sorry, Starling is briefly busy ✨ You can use the menu buttons below to register or verify your RoboForex IB account."
    )


# --------------------------------------------------------------- Keyboards
def main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    if lang == "ms":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Daftar Akaun RoboForex Baru", callback_data="m:reg")],
            [InlineKeyboardButton("🔄 Dah Ada Akaun (Tukar IB)", callback_data="m:xfer")],
            [InlineKeyboardButton("💳 Panduan Deposit & Login MT5", callback_data="m:mt5")],
            [InlineKeyboardButton("✅ Sahkan Akaun IB & Unlock App", callback_data="m:verify")],
            [
                InlineKeyboardButton("📢 Channel Telegram", url=KB["channel_url"]),
                InlineKeyboardButton("🇬🇧 Switch to EN", callback_data="lang:en"),
            ],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Open New RoboForex Account", callback_data="m:reg")],
        [InlineKeyboardButton("🔄 Transfer Existing Account to IB", callback_data="m:xfer")],
        [InlineKeyboardButton("💳 Deposit & MT5 Login Guide", callback_data="m:mt5")],
        [InlineKeyboardButton("✅ Verify IB & Unlock Full App", callback_data="m:verify")],
        [
            InlineKeyboardButton("📢 Official Channel", url=KB["channel_url"]),
            InlineKeyboardButton("🇲🇾 Tukar ke BM", callback_data="lang:ms"),
        ],
    ])


def reg_kb(lang: str) -> InlineKeyboardMarkup:
    if lang == "ms":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Daftar RoboForex Sekarang (IB: wnzx)", url=KB["ib_link"])],
            [InlineKeyboardButton("✅ Saya Dah Daftar — Sahkan Sekarang", callback_data="m:verify")],
            [InlineKeyboardButton("⬅️ Menu Utama", callback_data="m:home")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Register RoboForex Now (IB: wnzx)", url=KB["ib_link"])],
        [InlineKeyboardButton("✅ I've Registered — Verify Now", callback_data="m:verify")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="m:home")],
    ])


def back_verify_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Sahkan Akaun IB" if lang == "ms" else "✅ Verify IB Account",
            callback_data="m:verify",
        )],
        [InlineKeyboardButton(
            "⬅️ Menu Utama" if lang == "ms" else "⬅️ Main Menu",
            callback_data="m:home",
        )],
    ])


def approved_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⚡ Buka TraderWatch AI App" if lang == "ms" else "⚡ Open TraderWatch AI App",
            url=KB["app_url"],
        )],
        [InlineKeyboardButton(
            "📢 Channel Rasmi TraderWatch" if lang == "ms" else "📢 TraderWatch Official Channel",
            url=KB["channel_url"],
        )],
    ])


def welcome_text(first_name: str, lang: str) -> str:
    nm = first_name or "Trader"
    if lang == "ms":
        return (
            f"✨ <b>Hai {nm}! Saya Starling — Pembantu AI IB TraderWatch.</b>\n\n"
            "Saya sedia bantu anda <b>24/7 secara automatik</b> untuk:\n"
            "• Daftar akaun <b>RoboForex</b> di bawah IB TraderWatch\n"
            "• Tukar IB bagi akaun sedia ada\n"
            "• Panduan deposit & login MT5\n"
            "• Pengesahan akaun IB & <b>auto-unlock Full Unlimited Analyst</b> di app TraderWatch\n\n"
            "Pilih menu di bawah atau <b>taip terus soalan anda</b> 👇"
        )
    return (
        f"✨ <b>Hi {nm}! I'm Starling — TraderWatch's AI IB Assistant.</b>\n\n"
        "I'm here <b>24/7 automatically</b> to help you:\n"
        "• Open a <b>RoboForex</b> account under TraderWatch IB\n"
        "• Transfer an existing account to our IB\n"
        "• Deposit & log in to MT5\n"
        "• Verify your IB account & <b>auto-unlock Full Unlimited Analyst</b> in the TraderWatch app\n\n"
        "Choose an option below or <b>type any question directly</b> 👇"
    )


async def send_welcome_video(update: Update):
    """Send the cheerful 2D anime + Starling welcome video, caching Telegram file_id."""
    if not WELCOME_VIDEO_PATH.is_file():
        return
    mtime = str(int(WELCOME_VIDEO_PATH.stat().st_mtime))
    kv_key = f"welcome_vid_id:{mtime}"
    cached_id = kv_get(kv_key)
    caption = "✨ <b>Welcome to TraderWatch!</b> — Starling AI"
    try:
        if cached_id:
            await update.effective_message.reply_video(
                video=cached_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True,
            )
            return
        with WELCOME_VIDEO_PATH.open("rb") as fh:
            sent = await update.effective_message.reply_video(
                video=fh,
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True,
            )
        if sent and sent.video and sent.video.file_id:
            kv_set(kv_key, sent.video.file_id)
    except Exception as e:
        log.warning("Could not send welcome video: %s", e)


# --------------------------------------------------------------- Handlers
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    USER_STATE.pop(user.id, None)
    lang = upsert_lead(user)
    if (update.effective_message.text or "").startswith("/start"):
        await send_welcome_video(update)
    await update.effective_message.reply_text(
        welcome_text(user.first_name, lang),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(lang),
        disable_web_page_preview=True,
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    con = db_conn()
    try:
        leads = con.execute("SELECT COUNT(*) FROM ib_leads").fetchone()[0]
        clicked = con.execute("SELECT COUNT(*) FROM ib_leads WHERE clicked_reg_at IS NOT NULL").fetchone()[0]
        pend = con.execute("SELECT COUNT(*) FROM ib_submissions WHERE status='pending'").fetchone()[0]
        appr = con.execute("SELECT COUNT(*) FROM ib_submissions WHERE status='approved'").fetchone()[0]
        synced = con.execute("SELECT COUNT(*) FROM ib_submissions WHERE sb_synced=1").fetchone()[0]
        rej = con.execute("SELECT COUNT(*) FROM ib_submissions WHERE status='rejected'").fetchone()[0]
    finally:
        con.close()
    mode = "AUTO API" if (ROBOFOREX_AUTO_VERIFY and ROBOFOREX_API_KEY) else "1-Click Admin"
    await update.effective_message.reply_text(
        f"📊 <b>Starling RoboForex IB Stats</b>\n\n"
        f"• Total Leads: <b>{leads}</b>\n"
        f"• Clicked Register: <b>{clicked}</b>\n"
        f"• Pending Verify: <b>{pend}</b>\n"
        f"• Approved IB: <b>{appr}</b> (DB Synced: <b>{synced}</b>)\n"
        f"• Rejected: <b>{rej}</b>\n"
        f"• Verify Mode: <code>{mode}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    con = db_conn()
    try:
        rows = con.execute(
            "SELECT * FROM ib_submissions WHERE status='pending' ORDER BY id ASC LIMIT 10"
        ).fetchall()
    finally:
        con.close()
    if not rows:
        await update.effective_message.reply_text("✅ Tiada permohonan IB pending buat masa ini.")
        return
    for r in rows:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve & Unlock App", callback_data=f"adm:ok:{r['id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"adm:no:{r['id']}"),
        ]])
        await update.effective_message.reply_text(
            f"🛂 <b>Pending RoboForex IB #{r['id']}</b>\n"
            f"User: @{r['username'] or '—'} (<code>{r['tg_id']}</code>)\n"
            f"MT5 ID: <code>{r['account_id']}</code>\n"
            f"RoboForex Email: <code>{r['email']}</code>\n"
            f"TraderWatch Email: <code>{r['tw_email'] or r['email']}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )


async def finalize_submission(
    ctx: ContextTypes.DEFAULT_TYPE,
    user,
    chat_msg,
    lang: str,
    acct: str,
    rf_email: str,
    tw_email: str,
    photo_id: str | None,
):
    api_status, api_note = await verify_with_roboforex_api(acct, rf_email)

    con = db_conn()
    try:
        cur = con.execute(
            """INSERT INTO ib_submissions
               (tg_id, username, account_id, email, tw_email, photo_file_id, status, verify_source, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                user.id,
                user.username or "",
                acct,
                rf_email,
                tw_email,
                photo_id,
                "roboforex_api" if api_status != "manual" else "admin",
                api_note,
                now_iso(),
            ),
        )
        sid = cur.lastrowid
        con.commit()
    finally:
        con.close()

    if api_status in ("approved", "rejected"):
        await resolve_submission(ctx, sid, api_status, reason=api_note)
        return

    await chat_msg.reply_text(
        f"📨 <b>Permohonan Pengesahan #{sid} Diterima!</b>\n\n"
        f"• MT5 ID (RoboForex): <code>{acct}</code>\n"
        f"• Email RoboForex: <code>{rf_email}</code>\n"
        f"• Email TraderWatch: <code>{tw_email}</code>\n\n"
        "Starling sedang menyemak akaun anda di bawah IB <code>wnzx</code>. Sebaik disahkan, akaun TraderWatch anda akan <b>auto-unlock Full Features Unlimited Analyst</b>! ✨"
        if lang == "ms"
        else f"📨 <b>Verification Request #{sid} Received!</b>\n\n"
             f"• MT5 ID (RoboForex): <code>{acct}</code>\n"
             f"• RoboForex Email: <code>{rf_email}</code>\n"
             f"• TraderWatch Email: <code>{tw_email}</code>\n\n"
             "Starling is verifying your account under IB <code>wnzx</code>. Once confirmed, your TraderWatch app will <b>auto-unlock Full Features Unlimited Analyst</b>! ✨",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(lang),
    )

    adm_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve & Unlock App", callback_data=f"adm:ok:{sid}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"adm:no:{sid}"),
    ]])
    adm_txt = (
        f"🛂 <b>Permohonan Verify RoboForex IB #{sid}</b>\n\n"
        f"• Client: {user.first_name or ''} (@{user.username or '—'})\n"
        f"• TG ID: <code>{user.id}</code>\n"
        f"• MT5 ID: <code>{acct}</code>\n"
        f"• RoboForex Email: <code>{rf_email}</code>\n"
        f"• TraderWatch Email: <code>{tw_email}</code>\n"
        f"• Broker: RoboForex (IB: <code>{KB['ib_code']}</code>)"
    )
    for aid in ADMIN_IDS:
        try:
            if photo_id:
                await ctx.bot.send_photo(
                    chat_id=aid, photo=photo_id, caption=adm_txt,
                    parse_mode=ParseMode.HTML, reply_markup=adm_kb,
                )
            else:
                await ctx.bot.send_message(
                    chat_id=aid, text=adm_txt,
                    parse_mode=ParseMode.HTML, reply_markup=adm_kb,
                )
        except Exception as e:
            log.warning("Could not notify admin %s: %s", aid, e)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    user = q.from_user
    lang = get_lang(user.id)

    if data.startswith("lang:"):
        new_lang = data.split(":", 1)[1]
        if new_lang in ("ms", "en"):
            lang = upsert_lead(user, lang=new_lang)
        await q.edit_message_text(
            welcome_text(user.first_name, lang),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(lang),
            disable_web_page_preview=True,
        )
        return

    if data == "m:home":
        USER_STATE.pop(user.id, None)
        await q.edit_message_text(
            welcome_text(user.first_name, lang),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(lang),
            disable_web_page_preview=True,
        )
        return

    if data == "m:reg":
        USER_STATE.pop(user.id, None)
        upsert_lead(user, stage="registering", clicked_reg=True)
        await q.edit_message_text(
            KB["guides"][lang]["register"],
            parse_mode=ParseMode.HTML,
            reply_markup=reg_kb(lang),
            disable_web_page_preview=True,
        )
        return

    if data == "m:xfer":
        USER_STATE.pop(user.id, None)
        upsert_lead(user, stage="transferring", clicked_reg=True)
        await q.edit_message_text(
            KB["guides"][lang]["transfer"],
            parse_mode=ParseMode.HTML,
            reply_markup=back_verify_kb(lang),
            disable_web_page_preview=True,
        )
        return

    if data == "m:mt5":
        USER_STATE.pop(user.id, None)
        await q.edit_message_text(
            KB["guides"][lang]["deposit_mt5"],
            parse_mode=ParseMode.HTML,
            reply_markup=back_verify_kb(lang),
            disable_web_page_preview=True,
        )
        return

    if data == "m:verify":
        USER_STATE[user.id] = {"step": "await_account"}
        msg = (
            "✅ <b>Pengesahan Akaun IB RoboForex</b>\n\n"
            "Langkah 1/3: Sila taip <b>No. Akaun MT5 RoboForex</b> anda (contoh: <code>12345678</code>)."
            if lang == "ms"
            else "✅ <b>RoboForex IB Account Verification</b>\n\n"
                 "Step 1/3: Please type your <b>RoboForex MT5 Account ID</b> (e.g. <code>12345678</code>)."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "✖️ Batal" if lang == "ms" else "✖️ Cancel", callback_data="m:home"
        )]])
        await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "v:same_email":
        st = USER_STATE.get(user.id)
        if not st or st.get("step") != "await_tw_email":
            return
        acct = st["account_id"]
        rf_email = st["email"]
        photo_id = st.get("photo_id")
        USER_STATE.pop(user.id, None)
        await finalize_submission(ctx, user, q.message, lang, acct, rf_email, rf_email, photo_id)
        return

    if data.startswith("adm:"):
        if user.id not in ADMIN_IDS:
            return
        _, action, sid_str = data.split(":", 2)
        sid = int(sid_str)
        await resolve_submission(ctx, sid, "approved" if action == "ok" else "rejected", q)


async def resolve_submission(ctx: ContextTypes.DEFAULT_TYPE, sid: int, decision: str, query=None, reason=""):
    con = db_conn()
    try:
        row = con.execute("SELECT * FROM ib_submissions WHERE id=?", (sid,)).fetchone()
        if not row:
            if query:
                await query.edit_message_text("Submission tidak dijumpai.")
            return
        if row["status"] != "pending":
            if query:
                await query.edit_message_text(f"ℹ️ Submission #{sid} sudah diproses ({row['status']}).")
            return
        tw_email = row["tw_email"] or row["email"]
    finally:
        con.close()

    sb_ok, sb_msg = (False, "")
    if decision == "approved":
        sb_ok, sb_msg = await sync_traderwatch_db(tw_email, row["tg_id"])

    con = db_conn()
    try:
        con.execute(
            "UPDATE ib_submissions SET status=?, sb_synced=?, note=?, resolved_at=? WHERE id=?",
            (decision, 1 if sb_ok else 0, (reason or sb_msg or decision), now_iso(), sid),
        )
        con.execute(
            "UPDATE ib_leads SET stage=?, updated_at=? WHERE tg_id=?",
            ("verified" if decision == "approved" else "rejected", now_iso(), row["tg_id"]),
        )
        con.commit()
    finally:
        con.close()

    c_lang = get_lang(row["tg_id"])
    if decision == "approved":
        if sb_ok:
            sync_line = (
                "🔓 <b>TraderWatch App: Full Features &amp; Unlimited Analyst DIBUKA!</b>"
                if c_lang == "ms"
                else "🔓 <b>TraderWatch App: Full Features &amp; Unlimited Analyst UNLOCKED!</b>"
            )
        else:
            sync_line = (
                "ℹ️ <i>Daftar akaun TraderWatch dengan email di atas untuk aktifkan akses penuh.</i>"
                if c_lang == "ms"
                else "ℹ️ <i>Sign up on TraderWatch with the email above to activate full access.</i>"
            )
        txt = KB["guides"][c_lang]["approved"].format(
            account_id=row["account_id"], tw_email=tw_email, sync_line=sync_line
        )
        kb = approved_kb(c_lang)
    else:
        r_txt = reason or (
            "Akaun tidak ditemui di bawah kod IB wnzx."
            if c_lang == "ms"
            else "Account not found under IB code wnzx."
        )
        txt = KB["guides"][c_lang]["rejected"].format(account_id=row["account_id"], reason=r_txt)
        kb = back_verify_kb(c_lang)

    try:
        await ctx.bot.send_message(
            chat_id=row["tg_id"],
            text=txt,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning("Could not notify client %s: %s", row["tg_id"], e)

    if query:
        badge = "✅ APPROVED" if decision == "approved" else "❌ REJECTED"
        sync_badge = f"\nDB Sync: {'✅ ' + sb_msg if sb_ok else '⚠️ ' + sb_msg}" if decision == "approved" else ""
        res_text = (
            f"{badge} — RoboForex IB #{sid}\n"
            f"User: @{row['username'] or '—'} (<code>{row['tg_id']}</code>)\n"
            f"MT5 ID: <code>{row['account_id']}</code>\n"
            f"RoboForex: <code>{row['email']}</code> · TW: <code>{tw_email}</code>{sync_badge}"
        )
        if query.message and query.message.photo:
            await query.edit_message_caption(caption=res_text, parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text(text=res_text, parse_mode=ParseMode.HTML)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ACCT_RE = re.compile(r"^[A-Za-z0-9_-]{4,24}$")


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return
    lang = upsert_lead(user)
    text = (msg.text or msg.caption or "").strip()
    st = USER_STATE.get(user.id)

    # Step 1/3: MT5 Account ID
    if st and st.get("step") == "await_account":
        acct = re.sub(r"\s+", "", text)
        if not ACCT_RE.match(acct):
            await msg.reply_text(
                "⚠️ Format No. Akaun MT5 tidak sah. Sila masukkan nombor akaun sahaja (contoh: <code>12345678</code>)."
                if lang == "ms"
                else "⚠️ Invalid MT5 Account ID format. Please enter numbers/ID only (e.g. <code>12345678</code>).",
                parse_mode=ParseMode.HTML,
            )
            return
        st["account_id"] = acct
        st["step"] = "await_email"
        await msg.reply_text(
            f"✅ No. Akaun MT5: <code>{acct}</code>\n\n"
            "Langkah 2/3: Sila taip <b>Email berdaftar RoboForex</b> anda (boleh juga sertakan screenshot jika ada)."
            if lang == "ms"
            else f"✅ MT5 Account ID: <code>{acct}</code>\n\n"
                 "Step 2/3: Please type your <b>registered RoboForex email</b> (you may also attach a screenshot).",
            parse_mode=ParseMode.HTML,
        )
        return

    # Step 2/3: RoboForex Email (+ optional screenshot)
    if st and st.get("step") == "await_email":
        email = text.split()[0] if text else ""
        if not EMAIL_RE.match(email):
            await msg.reply_text(
                "⚠️ Sila masukkan alamat email RoboForex yang sah (contoh: <code>nama@email.com</code>)."
                if lang == "ms"
                else "⚠️ Please enter a valid RoboForex email address (e.g. <code>name@email.com</code>).",
                parse_mode=ParseMode.HTML,
            )
            return
        st["email"] = email.lower()
        st["photo_id"] = msg.photo[-1].file_id if msg.photo else None
        st["step"] = "await_tw_email"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✅ Sama ({email.lower()})" if lang == "ms" else f"✅ Same email ({email.lower()})",
                callback_data="v:same_email",
            )],
            [InlineKeyboardButton("✖️ Batal" if lang == "ms" else "✖️ Cancel", callback_data="m:home")],
        ])
        await msg.reply_text(
            f"✅ Email RoboForex: <code>{email.lower()}</code>\n\n"
            "Langkah 3/3: Sila taip <b>Email yang anda daftar di app TraderWatch</b> supaya sistem dapat <b>auto-sync & unlock Full Features Unlimited Analyst</b>.\n\n"
            "Jika sama dengan email RoboForex, tekan butang di bawah 👇"
            if lang == "ms"
            else f"✅ RoboForex Email: <code>{email.lower()}</code>\n\n"
                 "Step 3/3: Please type the <b>Email you registered on the TraderWatch app</b> so we can <b>auto-sync & unlock Full Features Unlimited Analyst</b>.\n\n"
                 "If it's the same as your RoboForex email, just tap below 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    # Step 3/3: TraderWatch App Email
    if st and st.get("step") == "await_tw_email":
        tw_email = text.split()[0] if text else ""
        if not EMAIL_RE.match(tw_email):
            await msg.reply_text(
                "⚠️ Sila masukkan alamat email TraderWatch yang sah (contoh: <code>nama@email.com</code>)."
                if lang == "ms"
                else "⚠️ Please enter a valid TraderWatch email address (e.g. <code>name@email.com</code>).",
                parse_mode=ParseMode.HTML,
            )
            return
        acct = st["account_id"]
        rf_email = st["email"]
        photo_id = st.get("photo_id") or (msg.photo[-1].file_id if msg.photo else None)
        USER_STATE.pop(user.id, None)
        await finalize_submission(ctx, user, msg, lang, acct, rf_email, tw_email.lower(), photo_id)
        return

    # Free-form 24/7 Starling AI Q&A
    if not text:
        return
    now = time.monotonic()
    if now - LAST_AI_CALL.get(user.id, 0) < AI_COOLDOWN_S:
        return
    LAST_AI_CALL[user.id] = now

    try:
        await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)
    except Exception:
        pass
    reply = await ask_starling_ai(text, lang)
    await msg.reply_text(
        reply,
        reply_markup=main_menu_kb(lang),
        disable_web_page_preview=True,
    )


def main():
    if not BOT_TOKEN:
        raise SystemExit("ERROR: STARLING_IB_BOT_TOKEN is not set (add to /home/ubuntu/.secrets/starling-ib.env)")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, on_message))

    log.info(
        "Starling RoboForex IB Bot starting (admins=%s, auto_verify=%s, sb_sync=%s, video=%s)",
        sorted(ADMIN_IDS),
        ROBOFOREX_AUTO_VERIFY,
        bool(SB_URL and SB_KEY),
        WELCOME_VIDEO_PATH.is_file(),
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
