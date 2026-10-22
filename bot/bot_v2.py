"""
Phantom-style Telegram bot v2: kad isyarat + gambar chart, Rincian Sniper,
Sweep Monitor, Macro Outlook, Berita, Jurnal, Kuota, Pengaturan, price watcher.

Pasang : pip install "python-telegram-bot[job-queue]>=21" mplfinance pandas
Env    : BOT_TOKEN, OANDA_TOKEN, HERMES_CMD, ADMIN_IDS, EXNESS_LINK
         (pilihan) OANDA_URL, CAL_URL, NEWS_RSS
Jalan  : python bot_v2.py
"""
import asyncio, html, io, json, os, pathlib, re, shlex, sqlite3, subprocess, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
import sys
import sys as _sys
_sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")
from engine.sq_collector import candles_from_bars as candles_swissquote  # noqa: E402
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton as IB, InlineKeyboardMarkup as IM
from telegram import ReplyKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

TOKEN = os.environ["BOT_TOKEN"]
HERMES_CMD = os.environ.get("HERMES_CMD", "hermes chat -q")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x}

# --- Mod ujian: bila TEST_CHAT_ID diset, bot HANYA layan chat itu dan semua
# notifikasi dialihkan ke situ. Client lain tidak akan menerima apa-apa.
TEST_CHAT_ID = int(os.environ["TEST_CHAT_ID"]) if os.environ.get("TEST_CHAT_ID") else None


def allowed(chat_id):
    return TEST_CHAT_ID is None or chat_id == TEST_CHAT_ID


def target(chat_id):
    """Destinasi sebenar untuk notifikasi (dikunci semasa ujian)."""
    return TEST_CHAT_ID if TEST_CHAT_ID else chat_id


def live_publish():
    """True bila signal patut masuk verified:true (member akan terima).

    Satu-satunya sumber kebenaran — dipakai oleh publish_trade() dan oleh
    banner mesej, supaya laporan tak bercanggah dengan row Supabase.
    PUBLISH_LIVE, bila diset, adalah suis induk: "0" memaksa mod ujian
    walaupun TEST_CHAT_ID sudah dibuang.
    """
    flag = os.environ.get("PUBLISH_LIVE")
    if flag is not None and flag.strip() != "":
        return flag.strip() == "1"
    return TEST_CHAT_ID is None


def mode_banner(live):
    """Teks status selepas terbit — mesti ikut `live`, bukan TEST_CHAT_ID."""
    if live:
        return ("🟢 <b>LIVE</b> — signal disimpan <code>verified:true</code>. "
                "Member akan terima pada tick sender seterusnya.")
    return ("🧪 <b>TEST MODE</b> — signal disimpan <code>verified:false</code>.\n"
            "Member TIDAK akan terima apa-apa. Buang TEST_CHAT_ID dari .env "
            "atau set PUBLISH_LIVE=1 untuk live.")
OANDA_TOKEN = os.environ.get("OANDA_TOKEN", "")
OANDA_URL = os.environ.get("OANDA_URL", "https://api-fxpractice.oanda.com")
CAL_URL = os.environ.get("CAL_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
NEWS_RSS = os.environ.get("NEWS_RSS", "https://www.fxstreet.com/rss/news")
EXNESS_LINK = os.environ.get("EXNESS_LINK", "https://example.com")

MIN_RR, VALID_MIN, CHAT_COST = 1.5, 45, 100
VISION_FREE = 1                                  # slot analisa sehari (FREE)
ENERGY = {"FREE": 3000, "PRO": 50000}

def energy_cap(tier): return ENERGY.get(str(tier).upper(), ENERGY["FREE"])
LINE = "━" * 20
WIB = timezone(timedelta(hours=7))
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
# pair: (instrumen OANDA, desimal, ukuran pip)
# Diselaraskan dengan HOT_PAIRS di members.html — 7 pair yang sama.
PAIRS = {"XAUUSD": ("XAU_USD", 2, 0.1), "GBPUSD": ("GBP_USD", 5, 0.0001),
         "EURUSD": ("EUR_USD", 5, 0.0001), "USDJPY": ("USD_JPY", 3, 0.01),
         "AUDUSD": ("AUD_USD", 5, 0.0001), "USDCAD": ("USD_CAD", 5, 0.0001),
         "NZDUSD": ("NZD_USD", 5, 0.0001),
         # BTC: 1 "pip" = 1 USD supaya pergerakan dipaparkan dalam dolar.
         "BTCUSD": ("BTC_USD", 2, 1.0)}

BTN_ANALISA, BTN_TOOLS = "📊 Terminal Analisa", "🛠️ Tools & Fitur PRO"
BTN_JURNAL, BTN_KUOTA = "📓 Jurnal & Equity", "👤 Cek Kuota & Akun"
BTN_SET, BTN_ABOUT = "⚙️ Pengaturan Bot", "🏛️ Tentang Hermes"
BTN_DRAFT = "🗂️ Draft Signal"
BTN_SCREENER = "🤖 Auto Screener"
BTN_PROFIT = "💰 Profit Guard"
MENU = ReplyKeyboardMarkup(
    [[BTN_ANALISA, BTN_TOOLS], [BTN_JURNAL, BTN_KUOTA], [BTN_SET, BTN_ABOUT]],
    resize_keyboard=True)
# Admin console: Auto Screener scan semua pair, Draft kekal untuk review.
MENU_ADMIN = ReplyKeyboardMarkup(
    [[BTN_ANALISA, BTN_DRAFT], [BTN_SCREENER, BTN_PROFIT],
     [BTN_TOOLS, BTN_KUOTA], [BTN_JURNAL, BTN_SET]],
    resize_keyboard=True)


def menu_for(tg_id):
    return MENU_ADMIN if tg_id in ADMIN_IDS else MENU

e = html.escape
def now(): return datetime.now(WIB)
def today(): return now().strftime("%Y-%m-%d")
def stamp(d): return f"{d.day:02d} {MONTHS[d.month-1]} {d.year} • {d:%H:%M} WIB"
def utc_iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
def parse_t(s): return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
def fmt(pair, x): return f"{float(x):.{PAIRS[pair][1]}f}"

# ---------------- database ----------------
db = sqlite3.connect("bot.db", check_same_thread=False, timeout=30)
db.execute("PRAGMA journal_mode=WAL")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(
  tg_id INTEGER PRIMARY KEY, name TEXT, tier TEXT DEFAULT 'FREE', exness_id TEXT,
  day TEXT, vision_used INTEGER DEFAULT 0, energy_used INTEGER DEFAULT 0,
  pair_filter TEXT DEFAULT 'XAUUSD', s_desk INTEGER DEFAULT 1, s_tp INTEGER DEFAULT 1,
  s_sweep INTEGER DEFAULT 1, s_news INTEGER DEFAULT 1, s_auto INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, pair TEXT, tf TEXT, bias TEXT,
  poi_low REAL, poi_high REAL, entry REAL, sl REAL, tp1 REAL, tp2 REAL, rr1 REAL, rr2 REAL,
  created_at TEXT, expires_at TEXT, status TEXT DEFAULT 'PENDING', pips REAL DEFAULT 0,
  detail TEXT);
""")
# Admin publishing state (non-destructive migration).
for _ddl in (
    "ALTER TABLE trades ADD COLUMN publish_status TEXT DEFAULT 'DRAFT'",
    "ALTER TABLE trades ADD COLUMN published_at TEXT",
    "ALTER TABLE trades ADD COLUMN supabase_id TEXT",
    "ALTER TABLE trades ADD COLUMN msg_id INTEGER",
):
    try:
        db.execute(_ddl)
    except sqlite3.OperationalError:
        pass
db.commit()


def _secrets_file(name):
    vals = {}
    try:
        for line in (pathlib.Path.home() / ".secrets" / name).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return vals

_SB = _secrets_file("supabase.env")
SB_URL = _SB.get("SUPABASE_URL", "")
SB_KEY = _SB.get("SUPABASE_SERVICE_KEY", "")
PAIR_PUBLIC = {"XAUUSD": "XAU/USD", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
               "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD",
               "NZDUSD": "NZD/USD", "BTCUSD": "BTC/USD"}

SIGNALS_TOKEN = _secrets_file("telegram.env").get("TELEGRAM_SIGNALS_BOT_TOKEN", "")
LIFECYCLE_STATE = pathlib.Path("/home/ubuntu/web/.signal-lifecycle.json")
STATUS_STATE = pathlib.Path("/home/ubuntu/web/Traderwatch-repo/signal-status.json")


def sb_request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SB_URL.rstrip("/") + "/rest/v1/" + path,
        data=data, method=method, headers={"apikey": SB_KEY,
        "Authorization": "Bearer " + SB_KEY, "Content-Type": "application/json",
        "Prefer": "return=representation"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip() else []


def fetch_member_targets():
    return sb_request("profiles?select=name,telegram_chat_id&plan=in.(pro,max)"
                      "&telegram_chat_id=not.is.null")


def telegram_send_member(chat_id, text):
    if not SIGNALS_TOKEN:
        return False, "signals bot token missing"
    body = urllib.parse.urlencode({"chat_id": str(chat_id), "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + SIGNALS_TOKEN + "/sendMessage",
                                 data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.load(r)
        return bool(d.get("ok")), str(d.get("description", ""))
    except Exception as ex:
        return False, f"{type(ex).__name__}: {str(ex)[:100]}"


def signal_status_key(pair, posted_at):
    d = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone(timedelta(hours=8)))
    code = "".join(ch for ch in pair.upper() if ch.isalpha())
    return f"{code}_{d:%Y%m%d}_{d:%H%M%S}"


def atomic_json(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def collect_profit_position(tid, admin_id, price, snap, dry_run=False):
    """Broadcast verified collect notice, then close DB/lifecycle/site as collected."""
    t = db.execute("SELECT * FROM trades WHERE id=? AND tg_id=?", (tid, admin_id)).fetchone()
    if not t:
        raise ValueError("active position not found")
    if t["status"] == "COLLECTED":
        return {"already collected": True, "sent": 0, "failed": 0}
    if t["status"] not in ("ACTIVE", "TP1") or not t["supabase_id"]:
        raise ValueError("position is not a published active trade")
    pair = PAIR_PUBLIC.get(t["pair"], t["pair"])
    pips = float(snap["pips"])
    movement = f"${pips:+.2f}" if t["pair"] == "BTCUSD" else f"{pips:+.1f} pips"
    text = (f"💰 <b>COLLECT PROFITS NOW</b>\n{LINE}\n"
            f"📊 <b>{pair}</b> · {t['bias']}\n"
            f"📍 Current price: <code>{fmt(t['pair'], price)}</code>\n"
            f"📈 Running profit: <b>{movement}</b>\n\n"
            "Close the active position and secure the running profit now.\n"
            "<i>Educational information only — confirm execution with your broker.</i>")
    sent = failed = 0
    if dry_run:
        return {"already collected": False, "sent": 0, "failed": 0,
                "pair": pair, "price": price, "pips": pips, "text": text}
    for target_row in fetch_member_targets():
        ok, _ = telegram_send_member(target_row["telegram_chat_id"], text)
        sent += int(ok); failed += int(not ok)
    if sent == 0:
        raise RuntimeError(f"collect broadcast failed for all targets (failed={failed})")

    # Only close after at least one real member delivery succeeded.
    db.execute("UPDATE trades SET status='COLLECTED', pips=? WHERE id=?", (pips, tid)); db.commit()
    life = json.loads(LIFECYCLE_STATE.read_text()) if LIFECYCLE_STATE.exists() else {}
    ls = life.setdefault(str(t["supabase_id"]), {})
    ls.update({"entry": True, "closed": "collected", "closed_at": datetime.now(timezone.utc).isoformat(),
               "collect_price": float(price), "collect_pips": pips})
    atomic_json(LIFECYCLE_STATE, life)

    signals = sb_request("signals?select=id,pair,posted_at&id=eq." +
                         urllib.parse.quote(str(t["supabase_id"])))
    if signals:
        website = json.loads(STATUS_STATE.read_text()) if STATUS_STATE.exists() else {"signals": {}}
        website.setdefault("signals", {})[signal_status_key(signals[0]["pair"], signals[0]["posted_at"])] = {
            "status": "collected", "pips": round(pips, 1),
            "unit": "usd" if t["pair"] == "BTCUSD" else "pips",
            "closed": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")}
        website["updated"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        atomic_json(STATUS_STATE, website)
    return {"already collected": False, "sent": sent, "failed": failed,
            "pair": pair, "price": price, "pips": pips}


SCREENER_PAIRS = ("XAUUSD", "GBPUSD", "EURUSD", "USDJPY",
                  "AUDUSD", "USDCAD", "NZDUSD")
SCREENER_RUNNING = set()
SCREENER_CACHE = {}


def publish_trade(tid, admin_id):
    """Validate a private candidate, then insert one verified Supabase signal."""
    t = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    if not t:
        raise ValueError("candidate tidak dijumpai")
    if int(t["tg_id"]) != int(admin_id):
        raise PermissionError("candidate bukan milik admin ini")
    if str(t["publish_status"] or "").upper() == "PUBLISHED":
        return t["supabase_id"], False, live_publish()
    pair = PAIR_PUBLIC.get(t["pair"])
    if not pair:
        raise ValueError(f"pair {t['pair']} belum disokong TraderWatch")
    side, entry, sl, tp = t["bias"].upper(), float(t["entry"]), float(t["sl"]), float(t["tp1"])
    if not ((side == "BUY" and sl < entry < tp) or (side == "SELL" and tp < entry < sl)):
        raise ValueError("arah/level tidak sah")
    if not SB_URL or not SB_KEY:
        raise RuntimeError("Supabase secret tidak tersedia")
    # live_publish() menentukan verified. Bila ia False, signal masuk sebagai
    # verified=false supaya website/membership bot TIDAK broadcast. Naik taraf
    # ke live dengan membuang TEST_CHAT_ID dari .env atau set PUBLISH_LIVE=1.
    live = live_publish()
    body = json.dumps({"pair": pair, "timeframe": "M15", "side": side,
                       "entry": entry, "sl": sl, "tp": tp,
                       "verified": live}).encode()
    req = urllib.request.Request(SB_URL.rstrip("/") + "/rest/v1/signals", data=body, method="POST",
        headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
                 "Content-Type": "application/json", "Prefer": "return=representation"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            rows = json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Supabase HTTP {ex.code}: {detail}") from ex
    sid = str(rows[0].get("id", "")) if rows else ""
    # Read-back: do not claim success until exact row is observable.
    if not sid:
        raise RuntimeError("Supabase insert tiada ID")
    q = urllib.request.Request(SB_URL.rstrip("/") + "/rest/v1/signals?id=eq." + urllib.parse.quote(sid) +
        "&select=id,pair,side,entry,sl,tp,verified", headers={"apikey": SB_KEY,
        "Authorization": "Bearer " + SB_KEY})
    with urllib.request.urlopen(q, timeout=25) as r:
        check = json.loads(r.read().decode() or "[]")
    if not check:
        raise RuntimeError("Supabase read-back gagal")
    if live and not check[0].get("verified"):
        raise RuntimeError("Supabase read-back: verified bukan true")
    db.execute("UPDATE trades SET publish_status=?,published_at=?,supabase_id=? WHERE id=?",
               ("PUBLISHED" if live else "TEST", utc_iso(now()), sid, tid)); db.commit()
    return sid, True, live


SENDER = "/home/ubuntu/web/signal-telegram-sender.py"


def trigger_sender():
    """Jalankan sender serta-merta supaya member terima dalam beberapa saat,
    bukan tunggu cron tick :05/:35. Sender ada lock sendiri, jadi ia selamat
    walaupun cron berjalan serentak.

    Output sender ditulis ke sender.log supaya setiap penghantaran segera
    boleh diaudit (cron tulis ke /tmp/signal-telegram.log, trigger tidak).
    """
    try:
        r = subprocess.run([sys.executable, SENDER], capture_output=True,
                           text=True, timeout=180)
        out = (r.stdout or "").strip()
        try:
            with open("/home/ubuntu/tw-bot/sender.log", "a") as fh:
                fh.write(f"--- trigger {datetime.now(WIB).isoformat(timespec='seconds')} "
                         f"exit={r.returncode}\n{out}\n")
                if r.stderr:
                    fh.write("STDERR: " + (r.stderr or "")[-1500:] + "\n")
        except Exception:
            pass
        return out.splitlines()[-1:] or [""]
    except Exception as ex:
        return [f"trigger gagal: {type(ex).__name__}"]


def reject_trade(tid, admin_id):
    cur = db.execute("UPDATE trades SET publish_status='REJECTED' WHERE id=? AND tg_id=? "
                     "AND COALESCE(publish_status,'DRAFT')<>'PUBLISHED'", (tid, admin_id))
    db.commit()
    return cur.rowcount > 0


def get_user(tg):
    db.execute("INSERT OR IGNORE INTO users(tg_id,name) VALUES(?,?)", (tg.id, tg.first_name))
    db.execute("UPDATE users SET day=?, vision_used=0, energy_used=0 "
               "WHERE tg_id=? AND (day IS NULL OR day<>?)", (today(), tg.id, today()))
    db.commit()
    return db.execute("SELECT * FROM users WHERE tg_id=?", (tg.id,)).fetchone()


def is_pro(u): return u["tier"] == "PRO"
def can_vision(u): return is_pro(u) or u["vision_used"] < VISION_FREE
def spend(tg_id, vision=0, energy=0):
    db.execute("UPDATE users SET vision_used=vision_used+?, energy_used=energy_used+? "
               "WHERE tg_id=?", (vision, energy, tg_id))
    db.commit()


# ---------------- agent Hermes ----------------
# Default route: MiniMax m3.1 flash (free) via OpenRouter — model yang sama
# digunakan Hermes. Serveras masih boleh dipilih lewat preset /model.
LLM_URL = os.environ.get("LLM_URL", "https://openrouter.ai/api/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "minimax/minimax-m3.1-flash:free")
LLM_KEY_ENV = os.environ.get("LLM_KEY_ENV", "OPENROUTER_API_KEY")

# Route per model supaya chain fellback boleh campur provider safely.
MODEL_ROUTES = {
    "minimax/minimax-m3.1-flash:free":
        ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "deepseek/deepseek-v4-flash":
        ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "deepseek/deepseek-v4.1-flash-1017":
        ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "openrouter/free":
        ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "nvidia/nemotron-3.5-lightning:free":
        ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "google/gemma-4-31b-it:free":
        ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "asai/freemodel-1-GLM":
        ("https://serveras.click/v1/chat/completions", "HERMES_CUSTOM_SERVERAS_CLICK_API_KEY"),
    "asai/freemodel-2-MiniMax":
        ("https://serveras.click/v1/chat/completions", "HERMES_CUSTOM_SERVERAS_CLICK_API_KEY"),
    "asai/deepseek-v4-flash":
        ("https://serveras.click/v1/chat/completions", "HERMES_CUSTOM_SERVERAS_CLICK_API_KEY"),
}


def _profile_secret(key):
    """Ambil key dari env atau .env profile BobBuilder tanpa mencetaknya."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        for line in (pathlib.Path.home() / ".hermes/profiles/bobbuilder/.env").read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


STARUH_TAIL = """

PENTING — format output:
Jawab dalam SATU baris sahaja, tanpa sebarang analisis, penjelasan,
penghuraian atau teks lain. Baris pertama respons MESTI tepat:

BIAS=<BUY/SELL> POI_LOW=<harga> POI_HIGH=<harga> SL=<harga> TP1=<harga> TP2=<harga>

Jangan tulis "Let me analyze", "Current price", "H1 bars" atau sebarang
ayat pendahuluan. Model yang menulis analisis akan gagal parse.

SYARAT WAJIB (semak dalam kepala sebelum jawab):
- BUY: SL < entry < TP1 < TP2.  SELL: TP2 < TP1 < entry < SL.
- Jarak TP1 dari entry MESTI sekurang-kurangnya 1.5x jarak SL dari entry.
  Kalau tidak cukup, jauhkan TP1 — jangan rapatkan SL.
- Entry = harga terkini yang diberi."""

def _llm_model_chain():
    """Model berbayar diutamakan; model free hanya sebagai sandaran.

    Dibaca pada setiap panggilan (bukan semasa import) supaya perubahan .env
    berkuat kuasa tanpa restart perkhidmatan.
    """
    chain = [LLM_MODEL]
    for m in (os.environ.get("LLM_FALLBACK_MODELS") or "").split(","):
        m = m.strip()
        if m and m not in chain:
            chain.append(m)
    return chain


def _is_payment_error(ex):
    """True bila provider kata kredit habis (402 / insufficient_credits)."""
    if isinstance(ex, urllib.error.HTTPError) and ex.code == 402:
        return True
    text = str(ex).lower()
    return "402" in text or "insufficient_credits" in text or "payment required" in text


# ---- Preset model: berbayar / percuma / auto ----
LLM_PRESETS = {
    "minimax": {"label": "\U0001f193 Model percuma \u2014 MiniMax",
                "desc": "MiniMax m3.1 flash (OpenRouter) \u2014 free, paling cepat",
                "model": "minimax/minimax-m3.1-flash:free",
                "fallback": "asai/freemodel-2-MiniMax",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "key_env": "OPENROUTER_API_KEY"},
    "deepseek": {"label": "\U0001f4b3 Model berbayar \u2014 DeepSeek",
                 "desc": "DeepSeek v4 Flash \u2014 analisis paling tepat (OpenRouter, sangat murah)",
                 "model": "deepseek/deepseek-v4-flash",
                 "fallback": "asai/deepseek-v4-flash",
                 "url": "https://openrouter.ai/api/v1/chat/completions",
                 "key_env": "OPENROUTER_API_KEY"},
    "free": {"label": "\U0001f193 Model percuma \u2014 GLM",
             "desc": "GLM free (serveras) \u2014 percuma, sandaran bila MiniMax sibuk",
             "model": "asai/freemodel-1-GLM",
             "fallback": "minimax/minimax-m3.1-flash:free",
             "url": "https://serveras.click/v1/chat/completions",
             "key_env": "HERMES_CUSTOM_SERVERAS_CLICK_API_KEY"},
}
# Semua preset disahkan hidup 22 Okt 2026:
#   minimax/minimax-m3.1-flash:free OK 0.8s | deepseek/deepseek-v4-flash OK 1.1s
#   asai/freemodel-1-GLM OK 4.0s | asai/freemodel-2-MiniMax OK 1.6s
# Tiada DeepSeek free: asai/freemodel-3-deepseekpro -> 404 model_not_found,
# semua asai/deepseek-* -> 402 insufficient_credits.


ENV_FILE = pathlib.Path("/home/ubuntu/tw-bot/.env")

# ---- PIN MODEL ----
# Model dikunci ke MiniMax m3.1 flash (OpenRouter) — model yang sama
# digunakan Hermes. Preset lain hanya sandaran automatik bila model
# utama tidak dapat dicapai; admin tak boleh tukar model dari /model.
DEFAULT_PRESET = "minimax"


def _apply_pin():
    """Tetapkan preset DEFAULT semasa startup dan simpan ke .env.

    Ini BUKAN hard lock — admin masih boleh tukar preset melalui /model.
    Fungsinya cuma memastikan selepas restart bot kembali kepada model
    lalai (MiniMax free) dan tidak tinggal pada preset yang rosak.
    """
    cfg = LLM_PRESETS.get(DEFAULT_PRESET)
    if not cfg:
        return None
    url, key_env = _preset_route(cfg)
    global LLM_MODEL, LLM_URL, LLM_KEY_ENV
    LLM_MODEL = cfg["model"]
    LLM_URL = url
    LLM_KEY_ENV = key_env
    os.environ["LLM_MODEL"] = cfg["model"]
    os.environ["LLM_FALLBACK_MODELS"] = cfg["fallback"]
    os.environ["LLM_URL"] = url
    os.environ["LLM_KEY_ENV"] = key_env
    try:
        _persist_llm_preset(DEFAULT_PRESET)
    except Exception as ex:
        print(f"[LLM] default: gagal simpan .env: {ex}", flush=True)
    print(f"[LLM] DEFAULT -> {DEFAULT_PRESET} ({cfg['model']})", flush=True)
    return cfg


def llm_preset_active():
    """Nama preset yang sepadan dengan keadaan runtime sekarang."""
    fb = (os.environ.get("LLM_FALLBACK_MODELS") or "").strip()
    for name, cfg in LLM_PRESETS.items():
        if cfg["model"] == LLM_MODEL and cfg["fallback"] == fb:
            return name
    return "custom"


def _preset_route(cfg):
    """URL + key env untuk preset (dengan fallback ke default global)."""
    model = cfg.get("model", "")
    url, key_env = MODEL_ROUTES.get(model, (LLM_URL, LLM_KEY_ENV))
    return cfg.get("url", url), cfg.get("key_env", key_env)


def _persist_llm_preset(name):
    """Tulis pilihan ke .env supaya kekal selepas restart."""
    cfg = LLM_PRESETS[name]
    url, key_env = _preset_route(cfg)
    try:
        lines = ENV_FILE.read_text().splitlines()
    except OSError:
        return False
    out, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key == "LLM_MODEL":
            out.append(f"LLM_MODEL={cfg['model']}"); seen.add(key)
        elif key == "LLM_FALLBACK_MODELS":
            out.append(f"LLM_FALLBACK_MODELS={cfg['fallback']}"); seen.add(key)
        elif key == "LLM_URL":
            out.append(f"LLM_URL={url}"); seen.add(key)
        elif key == "LLM_KEY_ENV":
            out.append(f"LLM_KEY_ENV={key_env}"); seen.add(key)
        else:
            out.append(line)
    if "LLM_MODEL" not in seen:
        out.append(f"LLM_MODEL={cfg['model']}")
    if "LLM_FALLBACK_MODELS" not in seen:
        out.append(f"LLM_FALLBACK_MODELS={cfg['fallback']}")
    if "LLM_URL" not in seen:
        out.append(f"LLM_URL={url}")
    if "LLM_KEY_ENV" not in seen:
        out.append(f"LLM_KEY_ENV={key_env}")
    ENV_FILE.write_text("\n".join(out).rstrip() + "\n")
    return True


def _apply_llm_preset(name, persist=True):
    """Tukar model serta-merta dalam proses ini; tiada restart diperlukan."""
    global LLM_MODEL, LLM_URL, LLM_KEY_ENV
    cfg = LLM_PRESETS[name]
    url, key_env = _preset_route(cfg)
    LLM_MODEL = cfg["model"]
    LLM_URL = url
    LLM_KEY_ENV = key_env
    os.environ["LLM_MODEL"] = cfg["model"]
    os.environ["LLM_FALLBACK_MODELS"] = cfg["fallback"]
    os.environ["LLM_URL"] = url
    os.environ["LLM_KEY_ENV"] = key_env
    if persist:
        _persist_llm_preset(name)
    return cfg


def llm_preset_text():
    active = llm_preset_active()
    cfg = LLM_PRESETS.get(active)
    lines = ["🧠 <b>PRESET MODEL AI</b>", LINE]
    if cfg:
        lines += [f"› Aktif: <b>{cfg['label']}</b>", f"› {e(cfg['desc'])}"]
    else:
        lines += ["› Aktif: <b>custom</b> (kombinasi bukan standard)"]
    lines += [LINE,
              f"› Utama: <code>{e(LLM_MODEL)}</code>",
              f"› Sandaran: <code>{e(os.environ.get('LLM_FALLBACK_MODELS') or '—')}</code>",
              LINE,
              "Pilih preset di bawah. Tukar serta-merta, tiada restart."]
    return "\n".join(lines)


def llm_preset_keyboard():
    active = llm_preset_active()
    rows = []
    for name, cfg in LLM_PRESETS.items():
        mark = "✅ " if name == active else ""
        rows.append([IB(f"{mark}{cfg['label']}", callback_data=f"llm:{name}")])
    return IM(rows)


def llm_preset_summary(name):
    cfg = LLM_PRESETS[name]
    return (f"✅ <b>Preset ditukar: {cfg['label']}</b>\n{LINE}\n"
            f"› {e(cfg['desc'])}\n"
            f"› Utama: <code>{e(cfg['model'])}</code>\n"
            f"› Sandaran: <code>{e(cfg['fallback'] or '—')}</code>\n\n"
            "Berkuat kuasa serta-merta untuk analisis seterusnya.")


def _run_agent(prompt, use_staruh=False):
    """Fast path: panggil API provider terus (~9s vs 50-160s melalui CLI).

    Model berbayar (v4-flash) dicuba dahulu kerana kualiti analisis lebih baik.
    Bila provider pulangkan 402 (kredit habis) atau gagal, rantaian turun ke
    model free secara automatik — satu kegagalan berbayar tidak boleh
    mematikan analisis sedangkan model free masih berfungsi.
    """
    key = _profile_secret(LLM_KEY_ENV)
    if key:
        content = prompt
        # JANGAN campur arahan STARUH dengan prompt yang sudah meminta JSON.
        # Prompt analisis (PROMPT) menyenaraikan ~20 medan JSON; menambah
        # arahan "balas satu baris BIAS=" menjadikan dua format bercanggah dan
        # model free pulangkan teks kosong.
        wants_json = ('"bias"' in prompt or "objek JSON" in prompt
                      or "JSON" in prompt[:400])
        if use_staruh and not wants_json and "STARUH" not in prompt:
            content = prompt + STARUH_TAIL
        models = _llm_model_chain()
        last_err = None
        payment_seen = False
        for model in models:
            m_url, m_key_env = MODEL_ROUTES.get(model, (LLM_URL, LLM_KEY_ENV))
            m_key = _profile_secret(m_key_env) or key
            for temp in (0.2, 0.45, 0.1, 0.3, 0.6):
                payload = {"model": model,
                           "messages": [{"role": "user", "content": content}],
                           "temperature": temp, "max_tokens": 2000}
                # Model reasoning (MiniMax m3.1 flash) guna token untuk
                # "reasoning" dahulu. Tanpa effort=low,ia habiskan
                # max_tokens sebelum tulis jawapan -> content=None ->
                # "model gagal beri jawapan". effort=low potong reasoning
                # (~21s -> ~12s) dan pastikan JSON keluar.
                if model.startswith("minimax/"):
                    payload["reasoning"] = {"effort": "low"}
                body = json.dumps(payload).encode()
                req = urllib.request.Request(m_url, data=body,
                    headers={"Authorization": "Bearer " + m_key,
                             "Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=90) as r:
                        data = json.load(r)
                    msg = data["choices"][0]["message"]
                    txt = (msg.get("content") or "").strip()
                    if not txt:
                        # Reasoning model: content Sometimes null bila
                        # max_tokens habis dalam reasoning. Teks penuh
                        # masih ada dalam field "reasoning".
                        txt = (msg.get("reasoning") or "").strip()
                    # Hanya terima jawapan yang ada payload boleh parse.
                    # Blok think-only / kosong mesti retry, bukan dipulangkan
                    # kepada validate sebagai "tiada setup".
                    clean = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", txt, flags=re.S).strip()
                    has_payload = ("BIAS=" in clean or "{\"" in clean or "{\n" in clean
                                   or ("\"bias\"" in clean) or ("\"entry\"" in clean))
                    if txt and len(txt) >= 12 and has_payload:
                        if model != LLM_MODEL:
                            print(f"[LLM] fallback model used: {model}", flush=True)
                        return txt
                    last_err = "jawapan kosong atau tiada payload"
                except Exception as ex:
                    last_err = f"{type(ex).__name__}: {str(ex)[:80]}"
                    if _is_payment_error(ex):
                        # Kredit model ini habis — jangan buang masa dengan
                        # suhu lain, terus ke model sandaran.
                        payment_seen = True
                        print(f"[LLM] {model} tiada kredit (402) — tukar model sandaran",
                              flush=True)
                        break
        detail = last_err
        if payment_seen:
            detail = f"402 Payment Required / insufficient credits ({last_err})"
        raise RuntimeError(f"model gagal beri jawapan ({detail})")

    base = shlex.split(HERMES_CMD)
    if "-Q" not in base and "--quiet" not in base:
        base.append("-Q")
    cmd = base + ([prompt] if ("-q" in base or "--query" in base) else ["-q", prompt])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                         cwd=os.environ.get("HERMES_CWD") or None)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or "Hermes gagal")[-500:])
    return out.stdout.strip()


async def ask_agent(prompt, use_staruh=False):
    return await asyncio.to_thread(_run_agent, prompt, use_staruh)


async def acalendar():
    return await asyncio.to_thread(get_calendar)


async def aheadlines(n=3):
    return await asyncio.to_thread(headlines, n)


def parse_staruh(raw):
    vals = {}
    for k, v in re.findall(r'(BIAS|POI_LOW|POI_HIGH|SL|TP1|TP2|RR[12])=([-\d.]+|\w+)', raw):
        try: vals[k] = float(v) if re.match(r'^-?\d', v) else v
        except Exception: vals[k] = v
    if not vals.get('BIAS'): return None
    return {"bias": str(vals['BIAS']).upper(), "poi_low": vals.get('POI_LOW', 0),
            "poi_high": vals.get('POI_HIGH', 0), "sl": vals.get('SL', 0),
            "tp1": vals.get('TP1', 0), "tp2": vals.get('TP2', 0),
            "rr1": vals.get('RR1', vals.get('RR2', 0)),
            "grade": str(vals.get('grade', 'C')),
            "confidence": int(vals.get('confidence', 5)),
            "bias_m5": str(vals.get('bias_m5', vals.get('BIAS'))).upper()}

def extract_json(text):
    # Model free kadang balut jawapan dalam blok pemikiran. Buang dahulu,
    # jika tidak parser nampak teks pemikiran dan bukan JSON sebenar.
    text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text, flags=re.S)
    text = re.sub(r"^\s*<think(?:ing)?>.*", "", text, flags=re.S)
    text = text.strip()
    s = parse_staruh(text)
    if s: return s
    try: return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception: pass
    # json in markdown
    m = re.search(r"```(?:json)?\n?(.*?)\n?```", text, re.S)
    if m: return json.loads(m.group(1).strip())
    raise ValueError(f"bukan STARUH atau JSON: {text[:80]}")


# ---------------- data pasar ----------------
DATA_SOURCE = os.environ.get("DATA_SOURCE", "swissquote").lower()
MT5_BRIDGE_URL = os.environ.get("MT5_BRIDGE_URL", "").rstrip("/")
MT5_BRIDGE_TOKEN = os.environ.get("MT5_BRIDGE_TOKEN", "")
def _secret(name, key):
    """Baca ~/.secrets/<name> supaya sama sumber dengan engine TraderWatch."""
    try:
        for line in (pathlib.Path.home() / ".secrets" / name).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


TWELVE_KEY = os.environ.get("TWELVEDATA_API_KEY") or _secret("twelve.env", "TWELVEDATA_API_KEY")

YAHOO = {"XAUUSD": "XAUUSD=X", "XAGUSD": "XAGUSD=X", "EURUSD": "EURUSD=X",
         "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X", "NASDAQ": "^IXIC", "DOW": "^DJI"}
YF_INTERVAL = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "60m", "H4": "1h"}


def _norm(rows):
    """Terima pelbagai bentuk, pulangkan format seragam bot."""
    out = []
    for c in rows:
        out.append({"t": c["t"], "o": float(c["o"]), "h": float(c["h"]),
                    "l": float(c["l"]), "c": float(c["c"]), "done": bool(c.get("done", True))})
    return out


def candles_mt5(pair, gran, count):
    """MT5 tak boleh jalan di Linux; guna jambatan HTTP pada mesin Windows.

    Bridge dijangka balas JSON: [{"t":"2026-10-20T01:00:00Z","o":..,"h":..,"l":..,"c":..,"done":true}, ...]
    """
    if not MT5_BRIDGE_URL:
        raise RuntimeError("MT5_BRIDGE_URL belum diset")
    q = urllib.parse.urlencode({"symbol": pair, "timeframe": gran, "count": count})
    req = urllib.request.Request(f"{MT5_BRIDGE_URL}/candles?{q}",
                                 headers={"X-Bridge-Token": MT5_BRIDGE_TOKEN} if MT5_BRIDGE_TOKEN else {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return _norm(json.load(r))


def candles_oanda(pair, gran, count):
    url = (f"{OANDA_URL}/v3/instruments/{PAIRS[pair][0]}/candles"
           f"?granularity={gran}&count={count}&price=M")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {OANDA_TOKEN}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    return _norm([{"t": c["time"], "o": c["mid"]["o"], "h": c["mid"]["h"],
                   "l": c["mid"]["l"], "c": c["mid"]["c"], "done": c["complete"]}
                  for c in data["candles"]])


def candles_twelvedata(pair, gran, count):
    TD_INTERVAL = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
                   "H1": "1h", "H4": "4h"}
    TD_SYMBOL = {"NASDAQ": "NDX", "DOW": "DJI"}
    if not TWELVE_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY tiada")
    sym = TD_SYMBOL.get(pair) or (f"{pair[:3]}/{pair[3:]}" if len(pair) == 6 else pair)
    q = urllib.parse.urlencode({"symbol": sym, "interval": TD_INTERVAL.get(gran, "15min"),
                                "outputsize": count, "apikey": TWELVE_KEY})
    with urllib.request.urlopen(f"https://api.twelvedata.com/time_series?{q}", timeout=20) as r:
        d = json.load(r)
    if "values" not in d:
        raise RuntimeError(d.get("message", "twelvedata error"))
    rows = [{"t": v["datetime"].replace(" ", "T") + "Z", "o": v["open"], "h": v["high"],
             "l": v["low"], "c": v["close"], "done": True} for v in reversed(d["values"])]
    return _norm(rows)


def candles_yahoo(pair, gran, count):
    """Sumber percuma tanpa kunci — untuk ujian, bukan production."""
    sym = YAHOO.get(pair)
    if not sym:
        raise RuntimeError(f"pair {pair} tiada dalam peta Yahoo")
    iv = YF_INTERVAL.get(gran, "15m")
    rng = {"1m": "2d", "5m": "5d", "15m": "1mo", "30m": "1mo", "60m": "3mo", "1h": "3mo"}[iv]
    q = urllib.parse.urlencode({"interval": iv, "range": rng})
    req = urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?{q}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    ts, qd = res["timestamp"], res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = qd["open"][i], qd["high"][i], qd["low"][i], qd["close"][i]
        if None in (o, h, l, c):
            continue
        rows.append({"t": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "o": o, "h": h, "l": l, "c": c, "done": True})
    return _norm(rows[-count:])


def candles_sqbars(pair, gran, count):
    """Baca bar dari sq-bars.db (Swissquote + Coinbase collector).

    Untuk BTC/USD, Swissquote tiada data — collector Coinbase menulis ke DB
    yang sama, jadi laluan ini sumber utama BTC.
    """
    from engine.sq_collector import candles_from_bars as _cfb
    rows = _cfb(pair, gran, count)
    if not rows:
        raise RuntimeError(f"sq-bars kosong untuk {pair} {gran}")
    return _norm(rows)


def candles_coinbase(pair, gran, count):
    """Coinbase candles langsung — sandaran bila DB belum cukup bar."""
    product = {"BTCUSD": "BTC-USD"}.get(pair)
    if not product:
        raise RuntimeError(f"coinbase tiada untuk {pair}")
    gmap = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
    gran_sec = gmap.get(gran)
    if not gran_sec:
        raise RuntimeError(f"granularity {gran} tidak disokong coinbase")
    url = (f"https://api.exchange.coinbase.com/products/{product}/candles"
           f"?granularity={gran_sec}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    # [time, low, high, open, close, volume] — paling baru dulu.
    rows = [{"t": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "o": float(o), "h": float(hi), "l": float(lo), "c": float(c), "done": True}
            for t, lo, hi, o, c, _v in sorted(data, key=lambda x: x[0])]
    return _norm(rows[-count:])


def candles_fake(pair, gran, count):
    """Data sintetik untuk ujian offline sahaja. JANGAN guna di production."""
    import math
    base = {"XAUUSD": 2650.0, "EURUSD": 1.0850, "GBPUSD": 1.2650,
            "USDJPY": 149.20, "XAGUSD": 31.5, "NASDAQ": 18500.0, "DOW": 42000.0}.get(pair, 1.0)
    d = PAIRS.get(pair, ("", 5, 0.0001))[1]
    step = base * 0.0006
    now_dt = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    for i in range(count):
        px = base + math.sin(i / 4.0) * step * 6 + math.sin(i / 11.0) * step * 3
        o = round(px, d); c = round(px + math.sin(i / 2.0) * step, d)
        rows.append({"t": (now_dt - timedelta(minutes=(count - i))).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "o": o, "h": round(max(o, c) + step * 0.6, d),
                     "l": round(min(o, c) - step * 0.6, d), "c": c, "done": True})
    return _norm(rows)


PROVIDERS = {"mt5": candles_mt5, "oanda": candles_oanda,
             "twelvedata": candles_twelvedata, "yahoo": candles_yahoo,
             "swissquote": candles_swissquote, "sqbars": candles_sqbars,
             "coinbase": candles_coinbase, "fake": candles_fake}

SOURCE_STATE = pathlib.Path("/home/ubuntu/web/.data-source-alert.json")

GRAN_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "M60": 60, "H4": 240}


def _is_weekend(now_ts):
    """Pasaran FX tutup Jumaat 21:00 UTC hingga Ahad 21:00 UTC."""
    d = datetime.fromtimestamp(now_ts, timezone.utc)
    wd, h = d.weekday(), d.hour
    if wd == 4 and h >= 21:
        return True
    if wd == 5:
        return True
    return wd == 6 and h < 21


def candles_fresh(rows, gran, now_ts, weekend=None):
    """True jika candle terakhir cukup baru untuk dipercayai.

    Ambang = max(5, 3 x tempoh bar) minit. Data basi bermakna collector mati,
    bukan pasaran sunyi — jadi ia mesti dikira GAGAL, bukan "OK".
    """
    if not rows:
        return False
    if weekend is None:
        weekend = _is_weekend(now_ts)
    if weekend:
        return True
    g = GRAN_MIN.get(str(gran).upper(), 15)
    threshold = max(5, 3 * g) * 60
    try:
        age = now_ts - parse_t(rows[-1]["t"]).timestamp()
    except Exception:
        return False
    return age <= threshold


def source_alert_decide(state, ok, now_ts, cooldown):
    """Tentukan bila perlu hantar amaran sumber data (elak spam).

    kind: "down" | "recovered" | None
    """
    st = dict(state or {})
    st.setdefault("failing", False)
    kind = None
    if ok:
        st["last_ok"] = now_ts
        if st.get("failing"):
            kind = "recovered"
            st["failing"] = False
            st["last_alert"] = now_ts
    else:
        st["last_fail"] = now_ts
        if not st.get("failing"):
            kind = "down"
            st["failing"] = True
            st["last_alert"] = now_ts
        elif now_ts - st.get("last_alert", 0) >= cooldown:
            kind = "down"
            st["last_alert"] = now_ts
    return kind, st


def admin_alert(text):
    """Hantar ke admin melalui @Twreg_bot (bukan broadcast ke member)."""
    try:
        tok = _secret("telegram.env", "TELEGRAM_BOT_TOKEN")
        chat = _secret("telegram.env", "TELEGRAM_ADMIN_CHAT_ID")
        if not tok or not chat:
            print("[SOURCE-ALERT] token/chat admin tiada", flush=True)
            return False
        q = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                    "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"})
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{tok}/sendMessage?{q}", timeout=15) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception as ex:
        print(f"[SOURCE-ALERT] hantar gagal: {type(ex).__name__} {ex}", flush=True)
        return False


def note_source(ok, source, detail=""):
    """Rekod status sumber data; cetak log dan hantar amaran bila perlu."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    state = None
    try:
        if SOURCE_STATE.exists():
            state = json.loads(SOURCE_STATE.read_text())
    except Exception:
        state = None
    kind, st = source_alert_decide(state, ok, now_ts, cooldown=1800)
    st["source"] = source
    st["detail"] = detail[:200]
    try:
        SOURCE_STATE.write_text(json.dumps(st))
    except Exception:
        pass
    if kind == "down":
        print(f"[SOURCE-DOWN] {source}: {detail}", flush=True)
        admin_alert(f"⚠️ <b>Sumber data gagal</b>\n{source} tidak memberi data.\n"
                    f"Detail: {detail[:180]}\nBot sedang guna sumber sandaran.")
    elif kind == "recovered":
        print(f"[SOURCE-OK] {source} pulih", flush=True)
        admin_alert(f"✅ <b>Sumber data pulih</b>\n{source} kembali normal.")
    return kind


def get_candles(pair, gran, count):
    # BTC/USD tiada di sumber FX/OANDA — baca sq-bars (collector Coinbase),
    # sandaran ke Coinbase API langsung.
    if pair == "BTCUSD":
        order = ["sqbars", "coinbase"]
    else:
        order = [DATA_SOURCE] + [k for k in ("mt5", "oanda", "twelvedata", "yahoo") if k != DATA_SOURCE]
    last = None
    for i, name in enumerate(order):
        fn = PROVIDERS.get(name)
        if not fn:
            continue
        try:
            rows = fn(pair, gran, count)
            if not rows:
                raise RuntimeError("tiada candle dikembalikan")
            now_ts = datetime.now(timezone.utc).timestamp()
            # Crypto 24/7: jangan guna weekend bypass FX untuk BTC.
            weekend = False if pair == "BTCUSD" else None
            if not candles_fresh(rows, gran, now_ts, weekend=weekend):
                raise RuntimeError(f"data basi: candle akhir {rows[-1]['t']}")
            if i == 0:
                note_source(True, name)
            else:
                note_source(False, DATA_SOURCE, f"jatuh ke {name} untuk {pair}")
            return rows
        except Exception as ex:
            last = ex
            continue
    note_source(False, DATA_SOURCE, f"semua sumber gagal untuk {pair}: {last}")
    raise RuntimeError(f"semua sumber data gagal: {last}")


async def acandles(pair, gran, count):
    return await asyncio.to_thread(get_candles, pair, gran, count)


def compact(cs, n, pair):
    d = PAIRS[pair][1]
    return "\n".join(f"{c['o']:.{d}f},{c['h']:.{d}f},{c['l']:.{d}f},{c['c']:.{d}f}" for c in cs[-n:])


_cal = {"at": None, "data": []}
CAL_CACHE = pathlib.Path(os.environ.get("CAL_CACHE", "/home/ubuntu/tw-bot/calendar-cache.json"))


def get_calendar():
    if _cal["at"] and now() - _cal["at"] < timedelta(minutes=15):
        return _cal["data"]
    raw, err = None, None
    for attempt in range(2):
        try:
            req = urllib.request.Request(CAL_URL, headers={"User-Agent": "TraderWatch/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
            if body.lstrip()[:1] not in (b"[", b"{"):
                raise ValueError("respons kalendar bukan JSON")
            raw = json.loads(body)
            CAL_CACHE.write_bytes(body)
            break
        except Exception as ex:
            err = ex
            if attempt == 0:
                import time as _time; _time.sleep(3)
    if raw is None:
        # Fail selamat hanya jika cache masih segar (<= 6 jam).
        try:
            age = datetime.now().timestamp() - CAL_CACHE.stat().st_mtime
            if age <= 6 * 3600:
                raw = json.loads(CAL_CACHE.read_text())
            else:
                raise RuntimeError("cache kalendar lebih 6 jam")
        except Exception:
            raise RuntimeError(f"kalendar tidak tersedia: {err}")
    out = []
    for x in raw:
        if x.get("impact") != "High":
            continue
        out.append({"when": datetime.fromisoformat(x["date"]).astimezone(WIB),
                    "ccy": x.get("country", ""), "title": x.get("title", ""),
                    "fc": x.get("forecast", ""), "prev": x.get("previous", "")})
    _cal.update(at=now(), data=sorted(out, key=lambda z: z["when"]))
    return _cal["data"]


def news_block(pair):
    """Embargo: berita High-Impact dalam +/-30 minit untuk mata wang berkaitan.

    None = tiada embargo, dict = event embargo. Kegagalan kalendar mesti
    dilaporkan, bukan dianggap "tiada berita".
    """
    ccys = {"USD", pair[:3], pair[3:6]}
    for ev in get_calendar():
        if ev["ccy"] in ccys and abs((ev["when"] - now()).total_seconds()) <= 1800:
            return ev
    return None


def headlines(n=3):
    try:
        with urllib.request.urlopen(NEWS_RSS, timeout=15) as r:
            root = ET.fromstring(r.read())
        return [i.findtext("title") for i in root.iter("item")][:n]
    except Exception:
        return []


# ---------------- gambar chart ----------------
def render_chart(pair, cs, zone=None, levels=(), labels=("Entry", "SL", "TP"),
                 right_pad=0.43):
    """Render dark M15 chart. right_pad meletak candle terakhir ~3/4 lebar."""
    try:
        import pandas as pd, mplfinance as mpf
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    if len(cs) < 10:
        return None
    df = pd.DataFrame({"Open": [c["o"] for c in cs], "High": [c["h"] for c in cs],
                       "Low": [c["l"] for c in cs], "Close": [c["c"] for c in cs]},
                      index=pd.to_datetime([c["t"] for c in cs], utc=True)
                      .tz_convert("Asia/Kuala_Lumpur").tz_localize(None))
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit", wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0f0f0f", figcolor="#0f0f0f", gridcolor="#1c1c1c")
    hl = [float(v) for v in levels]
    bar_l = [float(c["l"]) for c in cs]
    bar_h = [float(c["h"]) for c in cs]
    lo_p = min(bar_l + hl)
    hi_p = max(bar_h + hl)
    span = hi_p - lo_p or (abs(hi_p) * 0.001 or 1.0)
    pad_n = max(6, int(len(df) * max(0.0, float(right_pad))))
    kw = dict(type="candle", style=style, figsize=(10, 6),
              datetime_format="%d/%m %H:%M", xrotation=0,
              returnfig=True, tight_layout=True,
              xlim=(df.index[0], df.index[-1] + pd.Timedelta(minutes=15 * pad_n)))
    if hl:
        kw["hlines"] = dict(hlines=hl, colors=["#7f8cff"] * len(hl),
                            linestyle="--", linewidths=1.8)
    if zone:
        kw["fill_between"] = dict(y1=zone[0], y2=zone[1], alpha=0.15, color="#ef5350")
    fig, axes = mpf.plot(df, **kw)
    ax = axes[0]
    ax.set_ylim(lo_p - span * 0.07, hi_p + span * 0.07)
    ax.set_title(f"{pair} · M15 · {DATA_SOURCE.upper()} · {len(cs)} bar · "
                 f"terakhir {fmt(pair, cs[-1]['c'])}",
                 fontsize=12, color="#e6e6e6", pad=8)
    lvl_colors = ["#8ab4ff", "#ff6b6b", "#4dd0a5"]
    for lvl, lab, col in zip(hl, list(labels)[:len(hl)], lvl_colors):
        ax.axhline(lvl, color=col, linestyle="--", linewidth=1.8, alpha=0.95, zorder=5)
        ax.text(0.006, lvl, f" {lab} {fmt(pair, lvl)} ",
                transform=ax.get_yaxis_transform(),
                va="bottom", ha="left", fontsize=8.5, color="#0f0f0f",
                bbox=dict(boxstyle="round,pad=0.18", fc=col, ec="none", alpha=0.95),
                zorder=6, clip_on=True)
    # Lubang data (collector mati) perlu nampak.
    gaps = []
    for a, b in zip(cs, cs[1:]):
        try:
            d = (parse_t(b["t"]) - parse_t(a["t"])).total_seconds() / 60
        except Exception:
            continue
        if d > 30:
            gaps.append(int(d))
    if gaps:
        ax.annotate(f"⚠ lubang data: {', '.join(f'{g}min' for g in gaps[:3])}",
                    xy=(0.01, 0.02), xycoords="axes fraction",
                    fontsize=8, color="#ffb74d")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                facecolor="#0f0f0f")
    plt.close(fig)
    return buf.getvalue()


# ---------------- util hantar ----------------
def chunk_html(text, limit=3900):
    """Pecah pada sempadan baris; baris tunggal yang terlalu panjang
    dipecah pada ruang supaya tiada mesej melebihi had Telegram (4096)."""
    def split_long(line):
        if len(line) <= limit:
            return [line]
        pieces, buf = [], ""
        for word in line.split(" "):
            while len(word) > limit:              # satu ' perkataan' gergasi
                if buf:
                    pieces.append(buf); buf = ""
                pieces.append(word[:limit]); word = word[limit:]
            if len(buf) + len(word) + 1 > limit and buf:
                pieces.append(buf); buf = word
            else:
                buf = f"{buf} {word}" if buf else word
        if buf:
            pieces.append(buf)
        return pieces

    out, cur = [], ""
    for line in text.split("\n"):
        for piece in split_long(line):
            if len(cur) + len(piece) + 1 > limit and cur:
                out.append(cur); cur = piece
            else:
                cur = f"{cur}\n{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out or [""]


async def say(chat, text, kb=None):
    parts = chunk_html(text)
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        try:
            await chat.send_message(part, parse_mode=ParseMode.HTML,
                                    reply_markup=kb if last else None)
        except Exception:
            # fallback: hantar tanpa parse HTML daripada gagal senyap
            await chat.send_message(part.replace("<", "&lt;"), reply_markup=kb if last else None)


def bar(used, total):
    left = max(total - used, 0)
    n = round(10 * left / total)
    return f"[{'▓' * n}{'░' * (10 - n)}] {round(100 * left / total)}% ({left:,} / {total:,} Energi)"


# ---------------- analisa + kad isyarat ----------------
PROMPT = """Kamu analis SMC/ICT. Pair {pair}. Harga sekarang {price}.
H1 (open,high,low,close; 60 bar terakhir):
{h1}
M15 (80 bar terakhir):
{m15}
Balas HANYA satu objek JSON, tanpa teks lain, kunci tepat:
bias (BUY atau SELL), poi_low, poi_high (zon FVG/breaker M15 belum termitigasi),
sl, tp1, tp2 (nombor), grade (A+/A/B/C sahaja), confidence (0-10), bias_m5, plan (rencana eksekusi),
h1_trend, h1_levels (support/demand/resistance ringkas), h1_confluence (HIGH/MEDIUM/LOW),
m15_context, dol_type, dol_levels, poi_type, trigger_m1, rating_reason,
alignment (EXCELLENT/GOOD/MIXED), note, invalidation. Bahasa Indonesia.

Selain itu, beri versi Bahasa Inggeris untuk SEMUA medan naratif di atas
dengan akhiran _en: plan_en, h1_trend_en, h1_levels_en, m15_context_en,
dol_type_en, dol_levels_en, poi_type_en, trigger_m1_en, rating_reason_en,
note_en, invalidation_en. Nilai _en mesti terjemahan setia nilai asal —
jangan tambah atau buang maklumat, kekalkan semua nombor dan level.

Rubrik grade (pilih satu sahaja): A+ = confluence sangat tinggi, trend H1 dan
M15 searah, POI fresh, trigger jelas, R:R >= 3; A = confluence tinggi, satu
kelemahan kecil; B = confluence sederhana atau entry agak jauh dari POI;
C = banyak kelemahan, R:R rendah atau struktur bercanggah."""


def validate(pair, j):
    bias = str(j["bias"]).upper()
    lo, hi = sorted((float(j["poi_low"]), float(j["poi_high"])))
    entry = round((lo + hi) / 2, 5)                      # entry = tengah POI (CE 50%)
    sl, tp1, tp2 = float(j["sl"]), float(j["tp1"]), float(j["tp2"])
    ok = (sl > entry > tp1 > tp2) if bias == "SELL" else (sl < entry < tp1 < tp2)
    if bias not in ("BUY", "SELL") or not ok:
        raise ValueError("level tidak konsisten dengan arah")
    risk = abs(entry - sl)
    rr1, rr2 = abs(tp1 - entry) / risk, abs(tp2 - entry) / risk
    if rr1 < MIN_RR:
        raise ValueError(f"RR {rr1:.2f} di bawah {MIN_RR}")
    return dict(bias=bias, poi_low=lo, poi_high=hi, entry=entry, sl=sl, tp1=tp1,
                tp2=tp2, rr1=rr1, rr2=rr2)


def card_text(pair, tid, v, ts, status="DRAFT"):
    f = lambda x: fmt(pair, x)
    icon = "🔴 SELL" if v["bias"] == "SELL" else "🟢 BUY"
    badge = {"DRAFT": "📝 DRAFT", "TEST": "🧪 TEST — tidak dihantar ke member",
             "PUBLISHED": "🟢 LIVE — dihantar ke member"}.get(status, status)
    src = {"swissquote": "Swissquote", "twelvedata": "Twelve Data",
           "yahoo": "Yahoo", "mt5": "MT5", "oanda": "OANDA"}.get(DATA_SOURCE, DATA_SOURCE)
    return (f"⚡ <b>[TRADERWATCH // SMC STRUCTURE AUDIT]</b>\n{LINE}\n"
            f"📊 <b>Instrumen:</b> <code>{pair} [M15] (Trade #{tid})</code>\n"
            f"🔍 <b>Metode:</b> <code>OHLC H1+M15 + AI review</code>\n"
            f"📡 <b>Sumber data:</b> <code>{src}</code>\n"
            f"⚡ <b>Rekomendasi:</b> {icon}\n"
            f"📍 <b>Optimal Entry:</b> <code>{f(v['entry'])}</code>\n"
            f"🛡️ <b>SL:</b> <code>{f(v['sl'])}</code> | 🎯 <b>TP:</b> "
            f"<code>{f(v['tp1'])}</code> (RR 1:{v['rr1']:.1f})\n{LINE}\n"
            f"🤖 🎯 <b>POI Dipantau:</b> <code>{f(v['poi_low'])} — {f(v['poi_high'])}</code> "
            f"(Price Watcher Aktif)\n"
            f"📅 <b>Waktu Sinyal:</b> <code>{stamp(ts)}</code>\n"
            f"⏱️ <b>Validitas:</b> <code>Aktif {VALID_MIN} Menit</code>\n"
            f"🏷️ <b>Status:</b> {badge}\n"
            f"<i>Educational content only. Not financial advice.</i>")


def detail_text(t, j):
    p = t["pair"]; f = lambda x: fmt(p, x)
    g = lambda k: e(str(j.get(k, "-")))
    return (f"🎯 <b>ANALISIS SNIPER: {p}</b>\n\n---\n\n[ KESIMPULAN ]\n"
            f"› Setup: Grade {g('grade')}\n› Keyakinan: {g('confidence')} / 10\n"
            f"› Bias M5: {g('bias_m5')}\n\n---\n\n[ RENCANA EKSEKUSI ]\n{g('plan')}\n\n---\n\n"
            f"[ KOORDINAT & TAKTIK ]\n\n📊 <b>Konteks H1</b>\n› Trend: {g('h1_trend')}\n"
            f"› Level Kunci: {g('h1_levels')}\n› Rating Confluence: {g('h1_confluence')}\n\n"
            f"📈 <b>Konteks M15 (Prey Context)</b>\n{g('m15_context')}\n\n"
            f"🎯 <b>Target Likuiditas (DOL M15)</b>\n› Tipe: {g('dol_type')}\n"
            f"› Level: {g('dol_levels')}\n\n🏯 <b>Zona Penyergapan (POI)</b>\n"
            f"› Area: {f(t['poi_low'])} - {f(t['poi_high'])}\n› Tipe: {g('poi_type')}\n\n"
            f"💥 <b>Pemicu Entri (Trigger M1)</b>\n{g('trigger_m1')}\n\n"
            f"🎯 <b>Kondisi Pemicu (Two-Stage System)</b>\n"
            f"› Stage 1 (POI Alert): Harga masuk {f(t['poi_low'])} - {f(t['poi_high'])}\n"
            f"› Stage 2 (Confirmed Entry): Rejection wick / MSS terbentuk di M1\n\n---\n\n"
            f"[ PARAMETER MISI ]\n🎯 Entry : {f(t['poi_low'])} – {f(t['poi_high'])}\n"
            f"🛑 Stop Loss : {f(t['sl'])}\n"
            f"💎 TP 1 : {f(t['tp1'])} | R:R: 1:{t['rr1']:.1f}\n"
            f"💎 TP 2 : {f(t['tp2'])} | R:R: 1:{t['rr2']:.1f}\n\n---\n\n"
            f"[ JUSTIFIKASI & RISIKO ]\n› Alasan Rating:\n{g('rating_reason')}\n\n"
            f"› Alignment Timeframe: {g('alignment')}\n\n🗒️ <b>Catatan Khusus:</b>\n{g('note')}\n\n"
            f"› Invalidasi:\n{g('invalidation')}\n\n---\n\n⏱️ Validitas: ~{VALID_MIN} menit")


async def do_analysis(chat, tg, ctx, pair):
    u = get_user(tg)
    if not can_vision(u):
        return await say(chat, quota_out_text(), IM([[IB("👑 Panduan Aktivasi PRO", callback_data="pro_guide")]]))
    try:
        ev = await asyncio.to_thread(news_block, pair)
    except Exception as ex:
        return await say(chat, f"⚠️ Kalendar berita tidak tersedia ({e(str(ex))[:120]}). "
                               f"Analisa dihentikan untuk keselamatan; kuota tidak ditolak.")
    if ev:
        return await say(chat, f"🛡️ <b>STANDBY: berita High-Impact</b>\n"
                               f"[{e(ev['ccy'])}] {e(ev['title'])} • {ev['when']:%H:%M} WIB\n"
                               f"Analisa dikunci 30 minit sebelum dan selepas rilis.")
    st = await chat.send_message("⏳ <b>[1/4]</b> Mengambil data pasaran...", parse_mode=ParseMode.HTML)
    try:
        h1, m15 = await acandles(pair, "H1", 60), await acandles(pair, "M15", 120)
        await st.edit_text("🧠 <b>[2/4]</b> AI membaca struktur H1 + M15...", parse_mode=ParseMode.HTML)
        price = m15[-1]["c"]
        raw = await ask_agent(PROMPT.format(pair=pair, price=fmt(pair, price),
                                            h1=compact(h1, 45, pair), m15=compact(m15, 60, pair)),
                                   use_staruh=True)
        await st.edit_text("🧠 <b>[3/4]</b> Mengesahkan level & RR...", parse_mode=ParseMode.HTML)
        j = extract_json(raw)
        try:
            v = validate(pair, j)
        except Exception as first:
            repair_prompt = (PROMPT.format(pair=pair, price=fmt(pair, price),
                           h1=compact(h1, 45, pair), m15=compact(m15, 60, pair))
                           + "\n\nOutput sebelumnya tidak sah: " + str(first)
                           + ". Betulkan level supaya urutan arah konsisten dan RR1 >= 1.5. Balas JSON sahaja.")
            j = extract_json(await ask_agent(repair_prompt, True))
            v = validate(pair, j)
    except Exception as ex:
        return await st.edit_text(f"⚠️ Tiada setup layak sekarang ({e(str(ex))[:150]}). Kuota tidak ditolak.")
    ts = now()
    cur = db.execute(
        "INSERT INTO trades(tg_id,pair,tf,bias,poi_low,poi_high,entry,sl,tp1,tp2,rr1,rr2,"
        "created_at,expires_at,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tg.id, pair, "M15", v["bias"], v["poi_low"], v["poi_high"], v["entry"], v["sl"],
         v["tp1"], v["tp2"], v["rr1"], v["rr2"], utc_iso(ts),
         utc_iso(ts + timedelta(minutes=VALID_MIN)), json.dumps(j, ensure_ascii=False)))
    db.commit()
    tid = cur.lastrowid
    spend(tg.id, vision=1)
    png = await asyncio.to_thread(render_chart, pair, m15[-96:],
                                  (v["poi_low"], v["poi_high"]), (v["entry"], v["sl"], v["tp1"]))
    await st.delete()
    rows = [[IB("📋 Rincian Sniper", callback_data=f"detail:{tid}")]]
    if tg.id in ADMIN_IDS:
        rows.append([IB("✅ Post Signal", callback_data=f"admin:post:{tid}"),
                     IB("❌ Tolak", callback_data=f"admin:reject:{tid}")])
    kb = IM(rows)
    cap = card_text(pair, tid, v, ts)
    if png:
        sent = await chat.send_photo(png, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb)
        if sent:
            db.execute("UPDATE trades SET msg_id=? WHERE id=?", (sent.message_id, tid)); db.commit()
    else:
        await say(chat, cap, kb)


def screener_is_candidate(j, v):
    """Auto Screener hanya benarkan A+/A dengan RR tervalidasi."""
    grade = str(j.get("grade", "")).strip().upper()
    return grade in {"A+", "A"} and float(v.get("rr1", 0)) >= MIN_RR


async def screener_analyse_pair(pair):
    """Analisis satu pair tanpa simpan draft atau publish apa-apa."""
    ev = await asyncio.to_thread(news_block, pair)
    if ev:
        return {"pair": pair, "skip": "news"}
    h1, m15 = await acandles(pair, "H1", 60), await acandles(pair, "M15", 120)
    price = m15[-1]["c"]
    prompt = PROMPT.format(pair=pair, price=fmt(pair, price),
                           h1=compact(h1, 45, pair), m15=compact(m15, 60, pair))
    j = extract_json(await ask_agent(prompt, use_staruh=True))
    try:
        v = validate(pair, j)
    except Exception as first:
        repair = (prompt + "\n\nOutput sebelumnya tidak sah: " + str(first)
                  + ". Betulkan level supaya urutan arah konsisten dan RR1 >= 1.5. Balas JSON sahaja.")
        j = extract_json(await ask_agent(repair, True))
        v = validate(pair, j)
    return {"pair": pair, "j": j, "v": v, "h1": h1, "m15": m15}


def profit_snapshot(trade, price, pip, recent_bars):
    """Nilai profit berjalan secara deterministik; AI tidak mereka harga/pips.

    Cadangan collect hanya bila setup sudah untung dan sekurang-kurangnya:
    - 80% perjalanan ke TP1, atau
    - 1R profit berjalan.
    """
    side = str(trade["bias"]).upper()
    entry, sl, tp = float(trade["entry"]), float(trade["sl"]), float(trade["tp1"])
    move = (float(price) - entry) if side == "BUY" else (entry - float(price))
    target = abs(tp - entry)
    risk = abs(entry - sl)
    pips = move / float(pip)
    progress = (100 * move / target) if target else 0.0
    running_r = move / risk if risk else 0.0
    if move <= 0:
        reason = "Trade belum berada dalam profit. Kekalkan pelan asal dan pantau risiko."
        collect = False
    elif progress >= 80:
        reason = (f"Harga sudah melengkapkan {progress:.0f}% perjalanan ke TP1; "
                  "baki reward semakin kecil berbanding risiko pullback.")
        collect = True
    elif running_r >= 1.0:
        reason = (f"Profit berjalan sudah mencapai {running_r:.2f}R; melindungi keuntungan "
                  "adalah munasabah sebelum retracement.")
        collect = True
    else:
        reason = (f"Profit baru {running_r:.2f}R dan {progress:.0f}% menuju TP1; "
                  "belum cukup kuat untuk cadangan collect penuh.")
        collect = False
    return {"pips": pips, "progress": progress, "running_r": running_r,
            "collect": collect, "reason": reason}


async def active_profit_snapshot(t):
    """Read current M1 price and build one admin-only Profit Guard snapshot."""
    bars = await acandles(t["pair"], "M1", 30)
    price = float(bars[-1]["c"])
    snap = profit_snapshot(t, price, PAIRS[t["pair"]][2], bars)
    j = json.loads(t["detail"] or "{}")
    context = str(j.get("note", "") or j.get("rating_reason", "")).strip()
    return price, snap, context


def profit_guard_text(t, price, snap, context=""):
    decision = "✅ COLLECT PROFITS NOW" if snap["collect"] else "⏳ HOLD / MONITOR"
    movement = (f"${snap['pips']:+.2f}" if t["pair"] == "BTCUSD"
                else f"{snap['pips']:+.1f} pips")
    text = (f"💰 <b>{decision}</b>\n{LINE}\n"
            f"📊 <b>{t['pair']}</b> · {t['bias']} · Trade #{t['id']}\n"
            f"📍 Current price: <code>{fmt(t['pair'], price)}</code>\n"
            f"📈 Running: <b>{movement}</b> ({snap['running_r']:+.2f}R)\n"
            f"🎯 TP progress: {snap['progress']:.0f}%\n\n"
            f"<b>Reason:</b> {e(snap['reason'])}")
    if context:
        text += f"\n\n<b>Setup context:</b> {e(context[:350])}"
    return text + "\n\n<i>Admin decision support only — no member notification.</i>"


async def run_profit_guard(chat, tg):
    """List active positions first; admin chooses one to review."""
    rows = db.execute(
        "SELECT * FROM trades WHERE tg_id=? AND status IN ('ACTIVE','TP1') "
        "AND COALESCE(publish_status,'DRAFT')='PUBLISHED' ORDER BY id DESC",
        (tg.id,)).fetchall()
    if not rows:
        return await say(chat, "💰 <b>Profit Guard</b>\n\nTiada posisi LIVE aktif untuk diaudit sekarang.")

    buttons = []
    for t in rows:
        try:
            price, snap, _ = await active_profit_snapshot(t)
            movement = (f"${snap['pips']:+.2f}" if t["pair"] == "BTCUSD"
                        else f"{snap['pips']:+.1f}p")
            buttons.append([IB(f"📈 {t['pair']} {t['bias']} · {movement}",
                               callback_data=f"profit:select:{t['id']}")])
        except Exception:
            buttons.append([IB(f"⚠️ {t['pair']} #{t['id']} · price unavailable",
                               callback_data=f"profit:select:{t['id']}")])
    buttons.append([IB("❌ Cancel", callback_data="profit:cancel:0")])
    return await say(chat,
        f"💰 <b>Profit Guard · Active Position</b>\n\n"
        f"Pilih satu daripada {len(rows)} active position untuk lihat current price, "
        "running pips dan sebab cadangan.", IM(buttons))


async def run_auto_screener(chat, tg):
    """Scan pair satu demi satu dan pulangkan hanya calon A+/A untuk review."""
    status = await chat.send_message(
        "🤖 <b>Auto Screener bermula</b>\n\nAI sedang scan 7 pair untuk Grade A+ atau A. "
        "Tiada signal akan dipublish secara automatik.", parse_mode=ParseMode.HTML)
    found, skipped, failed = [], [], []
    total = len(SCREENER_PAIRS)
    for idx, pair in enumerate(SCREENER_PAIRS, 1):
        try:
            await status.edit_text(
                f"🤖 <b>Auto Screener [{idx}/{total}]</b>\nSedang scan <code>{pair}</code>...",
                parse_mode=ParseMode.HTML)
            r = await screener_analyse_pair(pair)
            if r.get("skip"):
                skipped.append(pair)
            elif screener_is_candidate(r["j"], r["v"]):
                found.append(r)
        except Exception as ex:
            failed.append((pair, str(ex)[:80]))

    found.sort(key=lambda r: (
        2 if str(r["j"].get("grade", "")).upper() == "A+" else 1,
        int(r["j"].get("confidence", 0) or 0), float(r["v"]["rr1"])), reverse=True)

    if not found:
        await status.edit_text(
            "🔍 <b>Auto Screener selesai</b>\n\n"
            "No high-probability A+/A setup found right now.\n\n"
            f"Scan: {total} pair · News lock: {len(skipped)} · Gagal: {len(failed)}",
            parse_mode=ParseMode.HTML)
        return

    await status.edit_text(
        f"✅ <b>Auto Screener selesai</b>\nDitemui {len(found)} setup Grade A+/A. "
        "Semak setiap calon sebelum simpan sebagai draft.", parse_mode=ParseMode.HTML)
    for rank, r in enumerate(found, 1):
        j, v, pair = r["j"], r["v"], r["pair"]
        grade = str(j.get("grade", "A")).upper()
        conf = int(j.get("confidence", 0) or 0)
        side = "🟢 BUY" if v["bias"] == "BUY" else "🔴 SELL"
        text = (f"🤖 <b>AUTO SCREENER #{rank}</b>\n{LINE}\n"
                f"📊 <b>{pair}</b> · {side}\n🏅 Grade <b>{grade}</b> · "
                f"Confidence {conf}/10 · R:R 1:{v['rr1']:.1f}\n"
                f"🎯 Entry <code>{fmt(pair, v['entry'])}</code> · "
                f"SL <code>{fmt(pair, v['sl'])}</code> · "
                f"TP <code>{fmt(pair, v['tp1'])}</code>\n\n"
                "Belum disimpan dan belum dihantar kepada member.")
        key = f"{tg.id}:{pair}:{int(now().timestamp())}:{rank}"
        SCREENER_CACHE[key] = r
        await say(chat, text, IM([
            [IB("🚀 Publish Now", callback_data=f"screen:publish:{key}"),
             IB("🔎 Review Setup", callback_data=f"screen:review:{key}")]]))


# ---------------- skrin lain ----------------
def quota_out_text():
    return (f"⚠️ <b>KUOTA HARIAN ANDA SUDAH HABIS ({VISION_FREE}x / Hari)</b>\n{LINE}\n"
            f"Untuk pengguna FREE, sistem membatasi {VISION_FREE} request analisa per hari "
            f"agar resource server tetap stabil.\n\n👑 <b>Mau Analisa Tanpa Batas 24/7?</b>\n"
            f"Akses PRO gratis dengan mendaftar atau memindahkan akun trading ke IB Exness kami.\n\n"
            f"Tekan tombol di bawah untuk panduan aktivasi!")


def profile_text(tg, u):
    pro = is_pro(u)
    slots = "Unlimited" if pro else f"{max(VISION_FREE - u['vision_used'], 0)} / {VISION_FREE}"
    return (f"👤 <b>PROFIL & KUOTA PENGGUNA</b>\n{LINE}\n🆔 Telegram ID: <code>{tg.id}</code>\n"
            f"👤 Nama: {e(tg.first_name)}\n🎖️ Status Tier: {'PRO MEMBER' if pro else 'FREE MEMBER'}\n"
            f"🏦 Akun Exness: {e(u['exness_id']) if u['exness_id'] else 'Belum Terdaftar'}\n{LINE}\n"
            f"📊 <b>KUOTA TERSEDIA HARI INI:</b>\n• 📸 Slot Analisa Vision: {slots}\n"
            f"• 🔋 Energi Chatbot AI:\n  ↳ {bar(u['energy_used'], energy_cap(u['tier']))}\n{LINE}\n"
            f"⏰ Reset kuota otomatis setiap hari pukul 00:00 WIB.")


def journal_text(tg):
    rows = db.execute("SELECT * FROM trades WHERE tg_id=? ORDER BY id DESC", (tg.id,)).fetchall()
    tp = sum(r["status"] in ("TP1", "TP2") for r in rows)
    sl = sum(r["status"] == "SL" for r in rows)
    run = sum(r["status"] in ("PENDING", "ALERTED", "ACTIVE", "TP1") for r in rows)
    wr = 100 * tp / (tp + sl) if tp + sl else 0
    pips = sum(r["pips"] for r in rows)
    hist = "\n".join(
        f"• [Trade #{r['id']}] {r['pair']} {r['bias']}\n  Zona: {fmt(r['pair'], r['entry'])} | "
        f"SL: {fmt(r['pair'], r['sl'])} | TP: {fmt(r['pair'], r['tp1'])}\n"
        f"  Hasil: {r['status']} ({r['pips']:.1f} Pips | RR 1:{r['rr1']:.2f})" for r in rows[:5]
    ) or "Belum ada setup."
    return (f"📓 <b>[JURNAL TRADING PRIBADI // {e(tg.first_name.upper())}]</b>\n{LINE}\n"
            f"🎯 <b>Statistik Akumulasi Anda:</b>\n• Total Setup Anda: {len(rows)} Trade\n"
            f"• Win Rate Pribadi: {wr:.1f}% ({tp} TP Hit / {sl} SL Hit)\n"
            f"• Realized Pips Anda: {pips:.1f} PIPS\n• Setup Aktif (Running): {run}\n{LINE}\n"
            f"📋 <b>Riwayat Setup Anda Terakhir:</b>\n{hist}\n{LINE}\n"
            f"⚡ Setiap setup didokumentasikan otomatis.")


SETTINGS = [("s_desk", "📡 Sinyal Desk Member Lain"), ("s_tp", "🔔 Alert Take Profit Partial (1:1) & BEP"),
            ("s_sweep", "⚡ Radar Liquidity Sweep Hunter"), ("s_news", "📰 Peringatan High-Impact News"),
            ("s_auto", "⏰ Jadwal Auto-Analisis")]


def settings_view(u):
    on = lambda k: "AKTIF ✅" if u[k] else "NONAKTIF ⚪"
    body = "\n".join(f"{n}: {on(k)}" for k, n in SETTINGS)
    txt = (f"⚙️ <b>[HERMES AGENT // PUSAT PENGATURAN]</b>\n{LINE}\n"
           f"Kelola preferensi notifikasi dan filter pair:\n\n{body}\n"
           f"🎯 Filter Pair Desk Aktif: {u['pair_filter']}\n{LINE}")
    rows = [[IB(n.split(' ', 1)[1], callback_data=f"set:{k}")] for k, n in SETTINGS]
    rows.append([IB(f"🎯 Pair: {u['pair_filter']} (ganti)", callback_data="set:pair")])
    return txt, IM(rows)


ABOUT = (f"🏛️ <b>[TENTANG BOT INI]</b>\n{LINE}\nAnalis pasaran autonomous berasaskan Hermes Agent: "
         f"Forex, Emas dan Kripto, 24/7.\n\n🧠 <b>Kelebihan:</b>\n• Direct Pixel Vision AI\n"
         f"• SMC & ICT: FVG, 50% CE, liquidity BSL/SSL, dealing range, killzone\n"
         f"• Episodic Memory: ingat setup sebelumnya\n• Real-Time Watcher: tick OANDA untuk POI dan TP/SL\n\n"
         f"⚠️ Bukan nasihat kewangan. Trading berisiko tinggi. DYOR.")

TOOLS = (f"🛠️ <b>[HERMES SUITE // TOOLS & FITUR PRO]</b>\n{LINE}\n"
         f"• ⚡ Liquidity Sweep Hunter: stop-hunt M15, reclaim M1, jejak Multi-TP\n"
         f"• 🔭 Macro Institutional Outlook: julat H4, 50% dealing range, playbook Buy vs Sell\n"
         f"• 📰 High-Impact News Sentinel: kalender berita dan amaran volatiliti\n"
         f"• 👑 Akses PRO: analisa tanpa had harian")


def killzone():
    h = datetime.now(timezone.utc).hour
    return ("ASIA KILLZONE" if h < 3 else "LONDON KILLZONE" if 7 <= h < 10
            else "NEW YORK KILLZONE" if 12 <= h < 15 else "OFF-KILLZONE / INTERSESSION DRIFT")


async def sweep_text(pair):
    c = await acandles(pair, "M15", 60)
    last = c[-20:]
    hi, lo = max(x["h"] for x in last[:-1]), min(x["l"] for x in last[:-1])
    n = 0
    for i in range(len(c) - 20, len(c)):
        prev = c[i - 10:i]
        ph, pl = max(x["h"] for x in prev), min(x["l"] for x in prev)
        n += (c[i]["h"] > ph and c[i]["c"] < ph) or (c[i]["l"] < pl and c[i]["c"] > pl)
    f = lambda x: fmt(pair, x)
    found = "Stop hunt terdeteksi." if n else "Belum ada stop hunt terdeteksi dalam 20 candle terakhir."
    return (f"⚡ <b>[SWEEP MONITOR // {pair}]</b>\n{LINE}\n🕰️ Sesi: {killzone()}\n"
            f"🕐 Waktu Server: {now():%d %b %Y, %H:%M} WIB\n\n📈 <b>KEY SWING LEVELS (M15):</b>\n"
            f"   • Swing High: {f(hi)}\n   • Swing Low:  {f(lo)}\n   • Running:    {f(c[-1]['c'])}\n"
            f"{LINE}\n{found}\n📊 Sweep dalam 20 candle: {n}\n⚡ Taip analisa untuk audit penuh.")


OUTLOOK_PROMPT = """Pair {pair}, harga {price}. Julat makro H4: {lo} sampai {hi}, EQ {eq}.
H4 (o,h,l,c; 60 bar):\n{h4}
Balas HANYA JSON: supply_low, supply_high, demand_low, demand_high, bsl, ssl,
buy_trigger, buy_validasi, buy_invalidasi, sell_trigger, sell_validasi, sell_invalidasi. Bahasa Indonesia."""


async def outlook_texts(pair):
    c = await acandles(pair, "H4", 60)
    hi, lo, px = max(x["h"] for x in c), min(x["l"] for x in c), c[-1]["c"]
    eq = (hi + lo) / 2
    f = lambda x: fmt(pair, x)
    regime = "PREMIUM ZONE 🔴" if px > eq else "DISCOUNT ZONE 🟢"
    j = extract_json(await ask_agent(OUTLOOK_PROMPT.format(
        pair=pair, price=f(px), lo=f(lo), hi=f(hi), eq=f(eq), h4=compact(c, 60, pair))))
    g = lambda k: e(str(j.get(k, "-")))
    a = (f"🏛️ <b>[HERMES MACRO OUTLOOK // {pair}]</b>\n{LINE}\n📊 HTF Structure: H4 Big Picture\n"
         f"⚖️ Macro Range: {f(lo)} — {f(hi)} (EQ: {f(eq)})\n📍 Regime Saat Ini: {regime}\n{LINE}\n"
         f"🏯 <b>ZONA BESAR INSTITUSI (H4 POI):</b>\n• 🔴 Macro Supply: {g('supply_low')} — {g('supply_high')}\n"
         f"• 🟢 Macro Demand: {g('demand_low')} — {g('demand_high')}\n"
         f"• 🎯 Macro DOL: BSL: {g('bsl')} | SSL: {g('ssl')}\n{LINE}\nPlaybook di bawah 👇")
    try:
        nxt = [x for x in await acalendar() if x["when"] > now()][:2]
        news = "\n".join(f"• 🔴 {x['when']:%Y-%m-%d %H:%M} WIB [{x['ccy']}] {e(x['title'])}" for x in nxt)
    except Exception:
        news = "• (kalendar tidak tersedia)"
    b = (f"⚔️ <b>[INSTITUTIONAL DUAL-SCENARIO PLAYBOOK // {pair}]</b>\n{LINE}\n"
         f"🟢 <b>SKENARIO BUY (DISCOUNT MITIGATION):</b>\n• Trigger: {g('buy_trigger')}\n"
         f"• Validasi: {g('buy_validasi')}\n• Target:\n  ↳ TP 1: EQ ({f(eq)})\n  ↳ TP 2: BSL {g('bsl')}\n"
         f"• Invalidasi: {g('buy_invalidasi')}\n\n{LINE}\n"
         f"🔴 <b>SKENARIO SELL (PREMIUM EXPANSION):</b>\n• Trigger: {g('sell_trigger')}\n"
         f"• Validasi: {g('sell_validasi')}\n• Target:\n  ↳ TP 1: EQ ({f(eq)})\n  ↳ TP 2: SSL {g('ssl')}\n"
         f"• Invalidasi: {g('sell_invalidasi')}\n\n{LINE}\n📰 <b>Berita Terdekat:</b>\n{news}\n{LINE}\n"
         f"💡 Disiplin risk management • Powered by Hermes Agent")
    return a, b


async def news_text():
    evs = [x for x in await acalendar() if now() < x["when"] < now() + timedelta(hours=48)]
    soon = any(x["when"] < now() + timedelta(hours=4) for x in evs)
    regime = "HIGH VOLATILITY ALERT (HIGH IMPACT EVENT IMMINENT)" if soon else "NORMAL"
    lines = "\n".join(f"🔴 {x['when']:%Y-%m-%d %H:%M} WIB | [{x['ccy']}] {e(x['title'])}\n"
                      f"   ↳ Forecast: {e(x['fc'] or '-')} | Prev: {e(x['prev'] or '-')}" for x in evs[:8]) \
        or "Tiada berita High-Impact dalam 48 jam."
    hl = "\n".join(f"• {e(h)}" for h in await aheadlines()) or "• (tiada tajuk)"
    return (f"📰 <b>[HERMES AGENT // HIGH IMPACT MACRO INTEL]</b>\n{LINE}\n"
            f"🛡️ Regime Pasar: {regime}\n{LINE}\n🔴 <b>Jadwal High Impact 24-48 Jam (WIB):</b>\n{lines}\n{LINE}\n"
            f"⚡ <b>Headlines:</b>\n{hl}\n{LINE}\n⚠️ DYOR • Powered by Hermes Agent")


# ---------------- handler ----------------
async def start(update: Update, ctx):
    if not allowed(update.effective_chat.id):
        return
    u = get_user(update.effective_user)
    is_admin = update.effective_user.id in ADMIN_IDS
    mode = ("\n🔧 <b>ADMIN CONSOLE</b> — analisa, semak draft, dan terbitkan ke website."
            if is_admin else "")
    await update.message.reply_html(
        f"⚡ <b>TRADERWATCH // SMC TERMINAL</b>\n{LINE}\n"
        f"Halo <b>{e(update.effective_user.first_name.upper())}</b>, selamat datang.\n\n"
        f"Saya menganalisis struktur pasaran (SMC/ICT) daripada data OHLC H1 + M15, "
        f"kemudian menilai setiap setup sebelum ia diterbitkan.{mode}\n\n"
        f"🎖️ <b>Status Akses: {u['tier']}</b>\n{LINE}\n"
        f"Guna menu di bawah atau taip bebas (contoh: 'analisa XAUUSD', 'berita hari ini').\n\n"
        f"<i>Educational content only. Not financial advice.</i>",
        reply_markup=menu_for(update.effective_user.id))


def pairs_kb():
    names = list(PAIRS)
    rows = [[IB(p, callback_data=f"pair:{p}") for p in names[i:i + 2]] for i in range(0, len(names), 2)]
    rows.append([IB("🔍 Cari Aset Lain", callback_data="other")])
    return IM(rows)


async def on_text(update: Update, ctx):
    if not allowed(update.effective_chat.id):
        return
    t, tg, chat = update.message.text.strip(), update.effective_user, update.effective_chat
    u = get_user(tg)
    if t == BTN_ANALISA:
        return await say(chat, "🏛️ <b>HERMES Terminal Analyst</b>\n\nSilakan pilih pair atau aset yang ingin "
                               "dianalisa dengan strategi smart money concept:", pairs_kb())
    if t == BTN_PROFIT:
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Profit Guard hanya untuk admin.")
        return await run_profit_guard(chat, tg)
    if t == BTN_SCREENER:
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Auto Screener hanya untuk admin.")
        if tg.id in SCREENER_RUNNING:
            return await say(chat, "⏳ Screener masih berjalan. Tunggu scan semasa selesai.")
        SCREENER_RUNNING.add(tg.id)
        try:
            return await run_auto_screener(chat, tg)
        finally:
            SCREENER_RUNNING.discard(tg.id)
    if t == BTN_TOOLS:
        return await say(chat, TOOLS, IM([[IB("⚡ Liquidity Sweep Hunter", callback_data="tool:sweep")],
                                          [IB("🔭 Macro Outlook", callback_data="tool:outlook")],
                                          [IB("📰 High-Impact News", callback_data="tool:news")]]))
    if t == BTN_JURNAL: return await say(chat, journal_text(tg))
    if t == BTN_KUOTA:
        return await say(chat, profile_text(tg, u),
                         None if is_pro(u) else IM([[IB("👑 Upgrade PRO", callback_data="pro_guide")]]))
    if t == BTN_SET:
        txt, kb = settings_view(u)
        return await say(chat, txt, kb)
    if t == BTN_ABOUT: return await say(chat, ABOUT)
    if t == BTN_DRAFT:
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Admin sahaja.")
        rows = db.execute("SELECT * FROM trades WHERE tg_id=? AND COALESCE(publish_status,'DRAFT') "
                          "IN ('DRAFT','TEST') ORDER BY id DESC LIMIT 5", (tg.id,)).fetchall()
        if not rows:
            return await say(chat, "🗂️ Tiada draft. Taip <code>analisa XAUUSD</code> untuk jana satu.")
        await say(chat, f"🗂️ <b>Draft Signal</b> ({len(rows)})\n{LINE}")
        for r in rows:
            kb = IM([[IB("✅ Post", callback_data=f"admin:post:{r['id']}"),
                      IB("❌ Tolak", callback_data=f"admin:reject:{r['id']}")]])
            await say(chat, f"#{r['id']} <b>{r['pair']}</b> {r['bias']} · entry "
                            f"<code>{fmt(r['pair'], r['entry'])}</code> · "
                            f"RR 1:{r['rr1']:.1f} · {r['publish_status'] or 'DRAFT'}", kb)
        return
    low = t.lower()
    if "berita" in low or "news" in low:
        return await say(chat, await news_text())
    if low.startswith(("analisa ", "analisis ")):
        asset = low.split(" ", 1)[1].upper().replace(" ", "")
        asset = {"GOLD": "XAUUSD", "EMAS": "XAUUSD", "SILVER": "XAGUSD"}.get(asset, asset)
        if asset in PAIRS:
            return await do_analysis(chat, tg, ctx, asset)
        if not can_vision(u):
            return await say(chat, quota_out_text(), IM([[IB("👑 Panduan Aktivasi PRO", callback_data="pro_guide")]]))
        await chat.send_message("⏳ Menganalisa...")
        try:
            reply = await ask_agent(f"Beri analisa SMC ringkas untuk {asset}. {t}")
        except Exception as ex:
            return await say(chat, f"⚠️ Gagal: {e(str(ex))[:150]}. Kuota tidak ditolak.")
        spend(tg.id, vision=1)          # caj hanya bila berjaya
        return await say(chat, e(reply))
    if u["energy_used"] + CHAT_COST > energy_cap(u["tier"]) and tg.id not in ADMIN_IDS:
        return await say(chat, "🔋 Energi chatbot habis hari ini. Reset 00:00 WIB atau upgrade PRO.")
    spend(tg.id, energy=CHAT_COST)
    await say(chat, e(await ask_agent(f"Kamu Phantom Analyst, analis SMC. Jawab ringkas dalam Bahasa Indonesia: {t}")))


async def on_callback(update: Update, ctx):
    q = update.callback_query
    await q.answer()
    if not allowed(q.message.chat.id):
        return
    tg, chat, d = q.from_user, q.message.chat, q.data
    u = get_user(tg)
    if d.startswith("llm:"):
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Admin sahaja.")
        name = d.split(":", 1)[1]
        if name not in LLM_PRESETS:
            return await say(chat, "⚠️ Preset tidak dikenali.")
        cfg = _apply_llm_preset(name)
        log_line = f"[LLM] preset -> {name} ({cfg['model']})"
        print(log_line, flush=True)
        try:
            await q.edit_message_text(llm_preset_summary(name),
                                      parse_mode=ParseMode.HTML,
                                      reply_markup=llm_preset_keyboard())
        except BadRequest as ex:
            # "Message is not modified" — pengguna tekan preset yang sama
            # dua kali. Bukan ralat sebenar; jangan biarkan stacktrace
            # dicetak dan callback menggantung.
            if "not modified" not in str(ex).lower():
                raise
            await q.answer()      # tutup loading spinner pada callback
        return
    if d.startswith("profit:"):
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Admin sahaja.")
        _, action, raw_id = d.split(":", 2)
        if action == "cancel":
            await q.edit_message_text(
                "❌ <b>Profit Guard dibatalkan.</b>\n\nTiada tindakan diambil; posisi kekal aktif.",
                parse_mode=ParseMode.HTML)
            return
        try:
            tid = int(raw_id)
        except ValueError:
            return await say(chat, "⚠️ Active position tidak sah.")
        t = db.execute(
            "SELECT * FROM trades WHERE id=? AND tg_id=? AND status IN ('ACTIVE','TP1') "
            "AND COALESCE(publish_status,'DRAFT')='PUBLISHED'", (tid, tg.id)).fetchone()
        if not t:
            return await say(chat, "⚠️ Posisi ini tidak lagi aktif.")
        try:
            price, snap, context = await active_profit_snapshot(t)
        except Exception as ex:
            return await say(chat, f"⚠️ Harga semasa gagal diperoleh — {e(str(ex))[:150]}")
        text = profit_guard_text(t, price, snap, context)
        if action == "select":
            return await say(chat, text, IM([
                [IB("💰 Collect Now", callback_data=f"profit:collect:{tid}")],
                [IB("📣 Notify Others & Close", callback_data=f"profit:notify:{tid}")],
                [IB("❌ Cancel", callback_data=f"profit:cancel:{tid}")]]))
        if action == "collect":
            return await say(chat,
                text + "\n\n💡 <b>Admin preview:</b> Tiada status diubah dan "
                "tiada mesej dihantar kepada member.", IM([
                    [IB("📣 Notify Others & Close", callback_data=f"profit:notify:{tid}")],
                    [IB("❌ Cancel", callback_data=f"profit:cancel:{tid}")]]))
        if action == "notify":
            try:
                result = await asyncio.to_thread(collect_profit_position, tid, tg.id, price, snap)
            except Exception as ex:
                return await say(chat, f"⚠️ Collect broadcast gagal — {e(str(ex))[:200]}. Posisi tidak ditutup.")
            if result.get("already collected"):
                return await say(chat, "ℹ️ Posisi ini sudah pernah ditutup sebagai COLLECTED.")
            return await say(chat,
                f"✅ <b>Position collected</b>\n{result['pair']} · "
                f"Current <code>{fmt(t['pair'], result['price'])}</code> · "
                f"{result['pips']:+.1f} {'USD' if t['pair']=='BTCUSD' else 'pips'}\n"
                f"Member notified: {result['sent']} · Failed: {result['failed']}")
    if d.startswith("screen:"):
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Admin sahaja.")
        _, action, key = d.split(":", 2)
        r = SCREENER_CACHE.get(key)
        if not r or not key.startswith(f"{tg.id}:"):
            return await say(chat, "⚠️ Calon screener sudah tamat. Jalankan scan baharu.")
        if action in ("review", "publish"):
            j, v, pair, m15 = r["j"], r["v"], r["pair"], r["m15"]
            ts = now()
            cur = db.execute(
                "INSERT INTO trades(tg_id,pair,tf,bias,poi_low,poi_high,entry,sl,tp1,tp2,rr1,rr2,"
                "created_at,expires_at,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tg.id, pair, "M15", v["bias"], v["poi_low"], v["poi_high"], v["entry"], v["sl"],
                 v["tp1"], v["tp2"], v["rr1"], v["rr2"], utc_iso(ts),
                 utc_iso(ts + timedelta(minutes=VALID_MIN)), json.dumps(j, ensure_ascii=False)))
            db.commit(); tid = cur.lastrowid
            if action == "publish":
                try:
                    sid, created, live = await asyncio.to_thread(publish_trade, tid, tg.id)
                    if not live:
                        raise RuntimeError("bot berada dalam TEST MODE; verified:false tidak dihantar")
                    out = await asyncio.to_thread(trigger_sender) if created else ["already published"]
                    SCREENER_CACHE.pop(key, None)
                    return await say(chat,
                        f"✅ <b>Auto Screener signal published</b>\n"
                        f"{pair} · Grade {e(str(j.get('grade','-')))} · Supabase ID <code>{e(str(sid))}</code>\n"
                        f"📤 {e(str(out[0]))}")
                except Exception as ex:
                    reject_trade(tid, tg.id)
                    return await say(chat, f"⚠️ Publish gagal — {e(str(ex))[:220]}")
            png = await asyncio.to_thread(render_chart, pair, m15[-96:],
                                           (v["poi_low"], v["poi_high"]),
                                           (v["entry"], v["sl"], v["tp1"]))
            kb = IM([[IB("📋 Rincian Sniper", callback_data=f"detail:{tid}")],
                     [IB("✅ Post Signal", callback_data=f"admin:post:{tid}"),
                      IB("❌ Tolak", callback_data=f"admin:reject:{tid}")]])
            cap = card_text(pair, tid, v, ts)
            sent = (await chat.send_photo(png, caption=cap, parse_mode=ParseMode.HTML,
                                          reply_markup=kb) if png else await say(chat, cap, kb))
            if sent:
                db.execute("UPDATE trades SET msg_id=? WHERE id=?", (sent.message_id, tid)); db.commit()
            SCREENER_CACHE.pop(key, None)
            return
    if d.startswith("demo:"):
        return await say(chat, "ℹ️ Ini <b>demo button</b> sahaja — tiada tindakan. "
                               "Button sebenar muncul pada kad analisa baru.")
    if d.startswith("admin:"):
        if tg.id not in ADMIN_IDS:
            return await say(chat, "🔒 Admin sahaja.")
        try:
            _, action, raw_id = d.split(":", 2)
            tid = int(raw_id)
            if action == "post":
                sid, created, live = await asyncio.to_thread(publish_trade, tid, tg.id)
                sent_line = ""
                if created and live:
                    out = await asyncio.to_thread(trigger_sender)
                    sent_line = f"\n📤 {e(str(out[0]))}"
                mode = mode_banner(live)
                text = (f"✅ <b>Signal diterbitkan</b>\n"
                        f"Supabase ID: <code>{e(sid)}</code>\n{mode}{sent_line}"
                        if created else
                        f"ℹ️ Signal ini sudah pernah diterbitkan. ID: <code>{e(str(sid))}</code>")
                # Kemas kini kad asal supaya status nampak LIVE/TEST
                try:
                    row = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
                    if row and row["msg_id"]:
                        new_status = "PUBLISHED" if live else "TEST"
                        v2 = {"bias": row["bias"], "entry": row["entry"], "sl": row["sl"],
                              "tp1": row["tp1"], "rr1": row["rr1"],
                              "poi_low": row["poi_low"], "poi_high": row["poi_high"]}
                        cap2 = card_text(row["pair"], tid, v2, parse_t(row["created_at"]), new_status)
                        await chat.edit_message_caption(caption=cap2, parse_mode=ParseMode.HTML,
                                                        reply_markup=IM([[IB("📋 Rincian Sniper", callback_data=f"detail:{tid}")]]))
                except Exception as _ex:
                    pass
                await say(chat, text)
            elif action == "reject":
                ok = reject_trade(tid, tg.id)
                await say(chat, "❌ Candidate ditolak." if ok else "⚠️ Candidate tak boleh ditolak.")
        except Exception as ex:
            await say(chat, f"⚠️ Publish gagal: {e(str(ex))[:250]}")
    elif d.startswith("pair:"):
        await do_analysis(chat, tg, ctx, d[5:])
    elif d == "other":
        await say(chat, "Taip nama aset, contoh: <i>analisa solana</i>")
    elif d.startswith("detail:"):
        t = db.execute("SELECT * FROM trades WHERE id=? AND tg_id=?", (int(d[7:]), tg.id)).fetchone()
        if t:
            await say(chat, detail_text(t, json.loads(t["detail"] or "{}")))
    elif d.startswith("tool:"):
        pair = u["pair_filter"]
        try:
            if d == "tool:sweep": await say(chat, await sweep_text(pair))
            elif d == "tool:news": await say(chat, await news_text())
            else:
                a, b = await outlook_texts(pair)
                await say(chat, a); await say(chat, b)
        except Exception as ex:
            await say(chat, f"⚠️ Gagal: {e(str(ex))[:200]}")
    elif d.startswith("set:"):
        k = d[4:]
        if k == "pair":
            names = list(PAIRS)
            nxt = names[(names.index(u["pair_filter"]) + 1) % len(names)]
            db.execute("UPDATE users SET pair_filter=? WHERE tg_id=?", (nxt, tg.id))
        elif k in dict(SETTINGS):
            db.execute(f"UPDATE users SET {k}=1-{k} WHERE tg_id=?", (tg.id,))
        db.commit()
        txt, kb = settings_view(get_user(tg))
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif d == "pro_guide":
        await say(chat, f"👑 <b>Aktivasi PRO</b>\n1. Daftar akaun Exness melalui pautan kami atau pindahkan akaun ke IB kami:\n"
                        f"{e(EXNESS_LINK)}\n2. Hantar ID akaun Exness anda kepada admin.\n3. Admin aktifkan PRO.\n\n"
                        f"<i>Nota: iklan/rujukan broker ialah hubungan komersial. Nyatakan dengan jelas kepada pengguna.</i>")


async def admin_cmd(update: Update, ctx):
    if not allowed(update.effective_chat.id):
        return
    if update.effective_user.id not in ADMIN_IDS or not ctx.args:
        return
    cmd = update.message.text.split()[0].lstrip("/").split("@")[0]
    try:
        uid = int(ctx.args[0])
    except (TypeError, ValueError):
        return await update.message.reply_text("Guna: /setpro <tg_id> [PRO|FREE]")
    if cmd == "setpro":
        db.execute("UPDATE users SET tier=? WHERE tg_id=?", (ctx.args[1].upper() if len(ctx.args) > 1 else "PRO", uid))
    elif cmd == "setexness":
        db.execute("UPDATE users SET exness_id=?, tier='PRO' WHERE tg_id=?", (ctx.args[1], uid))
    db.commit()
    await update.message.reply_text("OK")


# ---------------- price watcher ----------------
async def watch(ctx: ContextTypes.DEFAULT_TYPE):
    rows = db.execute("SELECT * FROM trades WHERE status IN ('PENDING','ALERTED','ACTIVE','TP1')").fetchall()
    if TEST_CHAT_ID is not None:
        rows = [r for r in rows if r["tg_id"] == TEST_CHAT_ID]
    for t in rows:
        try:
            await watch_one(ctx, t)
        except Exception:
            pass


async def watch_one(ctx, t):
    p, s = t["pair"], (1 if t["bias"] == "BUY" else -1)
    f = lambda x: fmt(p, x)
    created = parse_t(t["created_at"])
    age_min = max(1, int((now().astimezone(timezone.utc) - created).total_seconds() // 60) + 2)
    need = min(max(age_min, 60), 500)
    cs = [c for c in await acandles(p, "M1", need) if parse_t(c["t"]) >= created.replace(second=0)]
    if not cs:
        return

    pip = PAIRS[p][2]
    us = db.execute("SELECT * FROM users WHERE tg_id=?", (t["tg_id"],)).fetchone()
    status, msg, pips = t["status"], None, t["pips"]
    expired = utc_iso(now()) > t["expires_at"]

    def crosses(c, level, direction):
        """Candle ini menyentuh level dalam arah yang dimaksudkan."""
        return (c["l"] <= level) if direction == 1 else (c["h"] >= level)

    # Walk candle ikut masa: TP1 yang tercapai dahulu mesti direkod dahulu,
    # walaupun harga kemudian berpatah balik ke SL. Versi lama guna hi/lo
    # agregat dan boleh salah label TP1-then-SL sebagai SL.
    for c in cs:
        if status in ("PENDING", "ALERTED"):
            in_poi = c["l"] <= t["poi_high"] and c["h"] >= t["poi_low"]
            if status == "PENDING" and in_poi:
                status = "ALERTED"
                msg = (f"🎯 <b>[POI ALERT // #{t['id']} {p}]</b>\nHarga masuk zon "
                       f"{f(t['poi_low'])} - {f(t['poi_high'])}. Menunggu konfirmasi rejection/MSS di M1.")
            if status == "ALERTED":
                if crosses(c, t["sl"], s):
                    status = "INVALID"
                    msg = (f"❌ <b>[SETUP INVALID // #{t['id']} {p}]</b> Harga tembus SL "
                           f"{f(t['sl'])} sebelum konfirmasi entry.")
                    break
                if c["h"] > c["l"]:
                    wick = (c["h"] - max(c["o"], c["c"])) if s == -1 else (min(c["o"], c["c"]) - c["l"])
                    body_ok = c["c"] < c["o"] if s == -1 else c["c"] > c["o"]
                    if wick / (c["h"] - c["l"]) >= 0.4 and body_ok:
                        status = "ACTIVE"
                        msg = (f"✅ <b>[KONFIRMASI ENTRY // #{t['id']} {p}]</b> {t['bias']}\n"
                               f"Entry {f(t['entry'])} | SL {f(t['sl'])} | TP1 {f(t['tp1'])} | TP2 {f(t['tp2'])}")
            continue

        if status == "ACTIVE":
            if crosses(c, t["sl"], s):
                status, pips = "SL", -abs(t["entry"] - t["sl"]) / pip
                msg = f"🛑 <b>[SL HIT // #{t['id']} {p}]</b> pada {f(t['sl'])}."
                break
            if crosses(c, t["tp1"], -s):
                half = 0.5 * abs(t["tp1"] - t["entry"]) / pip
                status, pips = "TP1", half
                if us["s_tp"]:
                    msg = (f"💎 <b>[TP1 HIT // #{t['id']} {p}]</b> {f(t['tp1'])}. "
                           f"Tutup separa dan SL ke BEP.")
                # satu candle boleh terus capai TP2
                if crosses(c, t["tp2"], -s):
                    status, pips = "TP2", half + 0.5 * abs(t["tp2"] - t["entry"]) / pip
                    msg = f"💎 <b>[TP2 HIT // #{t['id']} {p}]</b> {f(t['tp2'])}."
                    break
                # BE TIDAK disemak pada candle yang sama: low/high candle itu
                # mungkin berlaku sebelum TP1, bukan selepas.
            continue

        if status == "TP1":
            half = 0.5 * abs(t["tp1"] - t["entry"]) / pip
            if crosses(c, t["tp2"], -s):
                status, pips = "TP2", half + 0.5 * abs(t["tp2"] - t["entry"]) / pip
                msg = f"💎 <b>[TP2 HIT // #{t['id']} {p}]</b> {f(t['tp2'])}."
                break
            if crosses(c, t["entry"], s):
                status, pips = "BE", half
                break

    if status in ("PENDING", "ALERTED") and expired:
        status, msg = "EXPIRED", f"⌛ Trade #{t['id']} {p}: setup tamat tempoh tanpa entry."

    if status != t["status"] or pips != t["pips"]:
        db.execute("UPDATE trades SET status=?, pips=? WHERE id=?", (status, pips, t["id"]))
        db.commit()
    if msg:
        await ctx.bot.send_message(target(t["tg_id"]), msg, parse_mode=ParseMode.HTML)


async def model_cmd(update: Update, ctx):
    """/model — tukar preset model AI (admin sahaja)."""
    if not allowed(update.effective_chat.id):
        return
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("🔒 Admin sahaja.")
    await say(update.effective_chat, llm_preset_text(), llm_preset_keyboard())


def main():
    # Kunci model ke preset yang dipin SEBELUM bot mula menerima permintaan.
    _apply_pin()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler(["setpro", "setexness"], admin_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.job_queue.run_repeating(watch, interval=20, first=10)
    app.run_polling()


if __name__ == "__main__":
    main()
