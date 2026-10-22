#!/usr/bin/env python3
"""TraderWatch signal lifecycle alerts.

Menghantar notifikasi peringkat hayat signal kepada member:
  🎯 ENTRY TRIGGERED  — harga sentuh level entry
  🛑 SL HIT           — harga kena stop loss
  💎 TP HIT           — harga kena take profit

Sumber harga: Swissquote live quote (sama feed dengan chart bot), jadi
entry/SL/TP dinilai pada harga yang member nampak.

Prinsip keselamatan:
  - Bootstrap senyap: signal yang sudah lepas entry SEBELUM skrip ini mula
    direkod tanpa notifikasi, supaya member tak di-spam peristiwa lama.
  - Dedupe: setiap peristiwa dihantar sekali sahaja (state file).
  - SL diutamakan bila TP dan SL terkena serentak (konservatif).
  - TP tidak pernah dihantar sebelum entry.

Guna:
  python3 signal-lifecycle-alert.py            # hantar seperti biasa
  python3 signal-lifecycle-alert.py --dry-run  # cetak sahaja, tiada mesej
  python3 signal-lifecycle-alert.py --reset    # padam state (bootstrap semula)

Cron: * * * * * /usr/bin/python3.12 .../signal-lifecycle-alert.py
"""
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")

TIMEOUT = 25
SECRETS = Path.home() / ".secrets"
STATE_FILE = Path("/home/ubuntu/web/.signal-lifecycle.json")
LOCK = Path("/tmp/tw-lifecycle.lock")
# Ujian pada diri sendiri: kalau fail ini wujud, mesej hanya ke chat itu.
TEST_CHAT_FILE = Path("/home/ubuntu/web/.lifecycle-test-chat")
LOOKBACK_DAYS = 7
MAX_SIGNALS = 40
PHOTO_CAPTION_LIMIT = 1024
# Setup LIMIT yang tak kena entry dalam tempoh ini dianggap gagal.
# Hanya untuk buy limit / sell limit — setup yang dah entry tidak terjejas.
EXPIRY_MIN = int(__import__("os").environ.get("LIFECYCLE_EXPIRY_MIN", "30"))
# Grace window: signal yang baru posting (dalam GRACE_MIN minit) ketika bot
# mula/reset TIDAK boleh dilabel "legacy". Sebelum ini, signal yang posting
# 32 saat sebelum bot start di-bootstrap sebagai legacy dan notification
# TP/SL-nya hilang selamanya.
GRACE_MIN = int(__import__("os").environ.get("LIFECYCLE_GRACE_MIN", "15"))
# Backfill: notifikasi catch-up hanya dihantar jika peristiwa (TP/SL) benar
# berlaku dalam tempoh ini. Peristiwa lama (>BACKFILL_MAX_AGE_HOURS jam)
# hanya direkod dalam state, tiada mesej — elak spam member.
BACKFILL_MAX_AGE_HOURS = int(
    __import__("os").environ.get("LIFECYCLE_BACKFILL_HOURS", "24"))
# Anti-flood: maksimum notifikasi repair dalam satu run. Country run boleh
# mengambil masa lama (render chart + hantar ke 4 chat), dan pada masa
#-tu cron mungkin mula run seterusnya.
REPAIR_MAX_PER_RUN = int(
    __import__("os").environ.get("LIFECYCLE_REPAIR_MAX", "3"))

PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01, "BTC/USD": 1.0}
DEFAULT_PIP = 0.0001


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def load_secrets(name):
    vals = {}
    for line in (SECRETS / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


TG = load_secrets("telegram.env")
SB = load_secrets("supabase.env")
SIGNALS_TOKEN = TG.get("TELEGRAM_SIGNALS_BOT_TOKEN") or TG["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT = TG.get("TELEGRAM_ADMIN_CHAT_ID", "")
SB_URL = SB["SUPABASE_URL"].rstrip("/")
SB_KEY = SB["SUPABASE_SERVICE_KEY"]


def test_chat():
    try:
        v = TEST_CHAT_FILE.read_text().strip()
        return int(v) if v else None
    except Exception:
        return None


# ---------------------------------------------------------------- logik teras
def evaluate(sig, price, st, bootstrap=False):
    """Nilai satu signal pada harga semasa. Mutasi `st`, pulangkan event.

    events: subset of ["entry", "sl", "tp"]
    """
    if st.get("closed"):
        return []
    side = str(sig["side"]).upper()
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    tp = float(sig["tp"])
    events = []

    if not st.get("entry"):
        touched = price <= entry if side == "BUY" else price >= entry
        if not touched:
            # Kes tepi: harga sudah melepasi TP tanpa kita pernah nampak
            # sentuhan entry (contoh bot baru dihidupkan). Tandakan entry
            # supaya state jujur, tetapi JANGAN tembak TP pada panggilan
            # yang sama — kita tidak tahu bila ia berlaku.
            blown = price >= tp if side == "BUY" else price <= tp
            if not blown:
                return []
        st["entry"] = True
        events.append("entry")
        # Jangan nilai TP/SL pada panggilan yang sama dengan entry: harga
        # boleh lompat ke TP tanpa setup benar-benar aktif.
        if bootstrap:
            return []
        return events

    if side == "BUY":
        hit_sl, hit_tp = price <= sl, price >= tp
    else:
        hit_sl, hit_tp = price >= sl, price <= tp

    if hit_sl:
        st["closed"] = "sl"
        events.append("sl")
    elif hit_tp:
        st["closed"] = "tp"
        events.append("tp")
    if bootstrap:
        return []
    return events


def parse_ts(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def is_expired(sig, st, now_dt, expiry_min=None, price=None, bars=None):
    """True bila pending limit melebihi tempoh SELEPAS first-touch zon.

    Tanpa first_touch, setup terus menunggu. Entry yang sudah filled tidak
    pernah expired.

    Tiga lapisan perlindungan sebelum setup boleh ditutup:

    1. Harga SEDANG dalam zon POI  -> expiry dijeda sepenuhnya.
    2. Ada bar yang menyentuh entry -> entry belum direkod oleh collector,
       jadi JANGAN tutup; biar tick berikutnya rekod entry.
    3. Perlu 2 tick berturut-turut melaporkan luput sebelum benar-benar
       expired, supaya race sesaat tidak membunuh setup sah.

    Ketiga-tiganya menangani punca #94 (expired 16:36:11 pada minit yang
    sama harga menyentuh entry 4128.85).
    """
    if expiry_min is None:
        expiry_min = EXPIRY_MIN
    if st.get("closed") or st.get("entry"):
        return False
    first_touch = st.get("first_touch")
    if not first_touch:
        return False
    entry = float(sig["entry"])
    side = str(sig["side"]).upper()

    # Lapisan 2: ada bar yang menyentuh entry? Entry mungkin belum direkod
    # kerana bar semasa belum ditutup dalam DB.
    if bars:
        for _ts, hi, lo in bars:
            if lo <= entry <= hi:
                st.pop("expiry_strikes", None)
                return False

    # Lapisan 1: harga dalam zon POI -> jangan tutup.
    if price is not None:
        try:
            poi_low = float(sig.get("poi_low", entry))
            poi_high = float(sig.get("poi_high", entry))
            if poi_low <= float(price) <= poi_high:
                st["in_zone"] = True
                st.pop("expiry_strikes", None)
                return False
            if st.get("in_zone"):
                st["in_zone"] = False
                st["first_touch"] = now_dt.astimezone(timezone.utc).isoformat()
                st.pop("expiry_strikes", None)
                log(f"ZONE-EXIT {sig.get('id')} {sig.get('pair')} "
                    f"— expiry timer restart")
                return False
        except (KeyError, TypeError, ValueError):
            pass

    try:
        touched = parse_ts(first_touch)
    except Exception:
        return False
    if (now_dt - touched).total_seconds() <= expiry_min * 60:
        st.pop("expiry_strikes", None)
        return False

    # Lapisan 3: sahkan pada dua tick berturut-turut.
    st["expiry_strikes"] = int(st.get("expiry_strikes") or 0) + 1
    if st["expiry_strikes"] < 2:
        log(f"EXPIRY-PENDING {sig.get('id')} {sig.get('pair')} "
            f"strike={st['expiry_strikes']}/2 — tunggu tick seterusnya")
        return False
    st.pop("expiry_strikes", None)
    return True


def bars_since(pair, since_dt):
    """Bar (ts, high, low) sejak since_dt. M1 dahulu, M15 sebagai ganti."""
    try:
        from engine.sq_collector import candles_from_bars
    except Exception:
        return []
    code = pair.replace("/", "")
    for gran in ("M1", "M15"):
        try:
            rows = candles_from_bars(code, gran, 5000)
        except Exception:
            continue
        out = []
        for b in rows:
            try:
                ts = parse_ts(b["t"])
            except Exception:
                continue
            if ts >= since_dt:
                out.append((b["t"], float(b["h"]), float(b["l"])))
        if len(out) >= 2:
            return out
    return []


def evaluate_bars(sig, bars, st, bootstrap=False):
    """Nilai signal guna JULAT setiap bar, bukan satu snapshot harga.

    Snapshot hanya nampak keadaan sekarang: kalau harga sudah melepasi entry
    sebelum poll pertama, entry tak pernah ditanda dan setup dilaporkan
    expired walaupun ia sebenarnya berjalan ke TP. Bar high/low menutup
    jurang itu.
    """
    if st.get("closed"):
        return []
    side = str(sig["side"]).upper()
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    tp = float(sig["tp"])
    poi_low = float(sig.get("poi_low", entry))
    poi_high = float(sig.get("poi_high", entry))
    events = []

    for ts_raw, hi, lo in bars:
        # first_touch = kali pertama mana-mana bar bersilang dengan zon POI.
        if not st.get("first_touch") and lo <= poi_high and hi >= poi_low:
            st["first_touch"] = ts_raw
        if not st.get("entry"):
            touched = lo <= entry if side == "BUY" else hi >= entry
            if not touched:
                continue
            st["entry"] = True
            st["entry_at"] = ts_raw
            events.append("entry")
            if bootstrap:
                return []
            # TP/SL tidak dinilai pada bar yang sama dengan entry.
            continue

        hit_sl = lo <= sl if side == "BUY" else hi >= sl
        hit_tp = hi >= tp if side == "BUY" else lo <= tp
        if hit_sl:
            st["closed"] = "sl"
            st["closed_at"] = ts_raw
            events.append("sl")
            break
        if hit_tp:
            st["closed"] = "tp"
            st["closed_at"] = ts_raw
            events.append("tp")
            break

    if bootstrap:
        return []
    return events


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    # Tulis atomik: elak state separuh siap kalau proses mati di tengah jalan.
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=0, sort_keys=True))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------- I/O
def sb_get(path):
    req = urllib.request.Request(f"{SB_URL}/rest/v1/{path}",
                                headers={"apikey": SB_KEY,
                                         "Authorization": "Bearer " + SB_KEY})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode() or "[]")


def fetch_signals():
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS))
    q = ("signals?select=id,pair,side,entry,sl,tp,timeframe,posted_at,verified"
         "&verified=is.true"
         f"&posted_at=gte.{since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
         f"&order=posted_at.desc&limit={MAX_SIGNALS}")
    rows = sb_get(q)
    # Manual signals carry the POI zone only in bot.db. Attach it by
    # Supabase id; auto signals have no zone and fall back to entry itself.
    try:
        import sqlite3
        db = sqlite3.connect("/home/ubuntu/tw-bot/bot.db")
        zones = {}
        for r in db.execute("SELECT supabase_id,poi_low,poi_high,detail FROM trades "
                            "WHERE supabase_id IS NOT NULL"):
            detail = {}
            try:
                detail = json.loads(r[3] or "{}")
            except Exception:
                pass
            zones[str(r[0])] = (r[1], r[2], detail)
        db.close()
        for row in rows:
            z = zones.get(str(row.get("id")))
            if z and z[0] is not None and z[1] is not None:
                row["poi_low"], row["poi_high"] = float(z[0]), float(z[1])
                row["reason"] = (z[2].get("rating_reason") or z[2].get("plan")
                                 or z[2].get("trigger_m1") or "")
    except Exception as ex:
        log(f"ZONE-WARN {type(ex).__name__}: {ex}")
    return rows


def fetch_targets():
    rows = sb_get("profiles?select=id,name,plan,telegram_chat_id"
                  "&plan=in.(pro,max)&telegram_chat_id=not.is.null") or []
    tc = test_chat()
    if tc is not None:
        rows = [r for r in rows if int(r["telegram_chat_id"]) == tc]
        log(f"TEST MODE: only chat {tc} ({len(rows)} target)")
    return rows


def live_price(pair):
    """Harga mid untuk pair gaya 'XAU/USD'.

    Forex/XAU guna Swissquote; BTC guna Coinbase. Raise jika tiada data.
    """
    from engine.sq_collector import poll_swissquote, poll_coinbase
    code = str(pair).replace("/", "").upper()
    if code == "BTCUSD":
        mid, _spread = poll_coinbase(code)
        return float(mid)
    mid, _spread = poll_swissquote(code)
    return float(mid)


def tg_send(chat_id, text):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"}
    url = (f"https://api.telegram.org/bot{SIGNALS_TOKEN}/sendMessage?"
           + urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return bool(json.loads(r.read().decode()).get("ok")), ""
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode()).get("description", "")
        except Exception:
            desc = str(e)
        return False, desc
    except Exception as e:
        return False, f"{type(e).__name__} {e}"


def caption_for(text):
    """Telegram photo caption maksimum 1024 aksara."""
    if len(text) <= PHOTO_CAPTION_LIMIT:
        return text
    return text[:PHOTO_CAPTION_LIMIT - 1].rstrip() + "…"


def render_result_chart(sig, st, count=96, right_pad=0.43):
    """Render dark M15 chart dengan ENTRY/SL/TP untuk alert hasil.

    right_pad menambah ruang kosong di kanan (gaya TradingView) supaya harga
    semasa berada sekitar 3/4 lebar dan label tidak terpotong.
    """
    try:
        sys.path.insert(0, "/home/ubuntu/tw-bot/lib")
        import pandas as pd
        import mplfinance as mpf
        import matplotlib.pyplot as plt
        from engine.sq_collector import candles_from_bars
        code = sig["pair"].replace("/", "")
        bars = candles_from_bars(code, "M15", count)
        if len(bars) < 10:
            return None
        idx = (pd.to_datetime([b["t"] for b in bars], utc=True)
               .tz_convert("Asia/Kuala_Lumpur").tz_localize(None))
        df = pd.DataFrame({"Open": [b["o"] for b in bars],
                           "High": [b["h"] for b in bars],
                           "Low": [b["l"] for b in bars],
                           "Close": [b["c"] for b in bars]}, index=idx)
        # Ruang kosong di kanan (gaya TradingView): lanjutkan had paksi X
        # selepas plot. Bar NaN dibuang oleh mplfinance, jadi xlim digunakan.
        pad_n = max(6, int(len(df) * max(0.0, float(right_pad))))
        mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                                   edge="inherit", wick="inherit")
        style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                                   facecolor="#0f0f0f", figcolor="#0f0f0f",
                                   gridcolor="#1c1c1c")
        fig, axes = mpf.plot(df, type="candle", style=style, figsize=(10, 6),
                             datetime_format="%d/%m %H:%M", xrotation=0,
                             returnfig=True, tight_layout=True,
                             xlim=(idx[0], idx[-1] + pd.Timedelta(minutes=15 * pad_n)))
        ax = axes[0]
        status = str(st.get("closed") or "ACTIVE").upper()
        ax.set_title(f"Trade #{sig.get('id','—')} · {sig['pair']} · M15 · {status}",
                     fontsize=12, color="#e6e6e6", pad=8)
        lv = [float(sig["entry"]), float(sig["sl"]), float(sig["tp"])]
        # Pastikan semua level berada dalam julat Y, jika tidak label di luar
        # paksi akan mengembangkan kanvas (bbox tight) dan saiz gambar meledak.
        # Y-limit mestilah sekurang-kurangnya 6% span di ATAS harga tertinggi
        # dan 6% span di BAWAH harga terendah — termasuk SL/TP yang mungkin
        # berada di luar julat bar semasa (contoh TP > semua bar high).
        bar_lows = [float(b["l"]) for b in bars]
        bar_highs = [float(b["h"]) for b in bars]
        lo_price = min(bar_lows + lv)
        hi_price = max(bar_highs + lv)
        span = hi_price - lo_price or (abs(hi_price) * 0.001 or 1.0)
        ax.set_ylim(lo_price - span * 0.07, hi_price + span * 0.07)
        for lvl, lab, col in zip(lv, ("ENTRY", "SL", "TP"),
                                 ("#8ab4ff", "#ff6b6b", "#4dd0a5")):
            ax.axhline(lvl, color=col, linestyle="--", linewidth=1.8,
                       alpha=0.95, zorder=5)
            ax.text(0.006, lvl, f" {lab} {lvl} ", transform=ax.get_yaxis_transform(),
                    va="bottom", ha="left", fontsize=8.5, color="#0f0f0f",
                    bbox=dict(boxstyle="round,pad=0.18", fc=col, ec="none", alpha=0.95),
                    zorder=6, clip_on=True)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                    facecolor="#0f0f0f")
        plt.close(fig)
        return buf.getvalue()
    except Exception as ex:
        log(f"CHART-FAIL #{sig.get('id','?')}: {type(ex).__name__} {ex}")
        return None


def tg_photo(chat_id, png, caption):
    """Hantar PNG dengan caption HTML. Returns (ok, description)."""
    boundary = "----TWResultChart"
    body = b""
    for k, v in (("chat_id", str(chat_id)), ("caption", caption_for(caption)),
                 ("parse_mode", "HTML")):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\""
                 f"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
             f"filename=\"result.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
    body += png + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{SIGNALS_TOKEN}/sendPhoto", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode())
        return bool(payload.get("ok")), ""
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode()).get("description", "")
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__} {e}"


DECIMALS = {"XAU/USD": 3, "USD/JPY": 3, "BTC/USD": 2}
DEFAULT_DECIMALS = 5


def fmt_price(pair, value):
    """Format harga ikut pair, buang sifar berlebihan.

    Float mentah seperti 4117.514999999999 tidak boleh dipaparkan kepada
    member — ia nampak seperti pepijat walaupun nilai itu betul.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    d = DECIMALS.get(str(pair).upper(), DEFAULT_DECIMALS)
    s = f"{v:.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_pips(sig, level):
    pip = PIP.get(sig["pair"], DEFAULT_PIP)
    entry = float(sig["entry"])
    return abs(float(level) - entry) / pip


def fmt_duration(start, end):
    try:
        secs = max(0, int((parse_ts(end) - parse_ts(start)).total_seconds()))
    except Exception:
        return "—"
    mins = secs // 60
    h, m = divmod(mins, 60)
    return f"{h}j {m}m" if h else f"{m}m"


def _timing_line(st, start, end, label="TP hit"):
    """Baris masa dengan sumber timestamp dinyatakan.

    entry_at  = harga benar-benar sentuh entry
    first_touch = harga sentuh zon POI (lebih awal)
    bila hanya ada posted_at, kita cuma tahu bila setup di-SiLive, bukan bila
    entry kena — jadi label daran "Setup posted", bukan "Entry".
    """
    src = ("entry" if st.get("entry_at")
           else "POI touched" if st.get("first_touch")
           else "Setup posted")
    if not end:
        return (f"Entry {clock_my(start)} ➔ {label} "
                f"(⏱️ {src} ➔ close)")
    return f"Entry {clock_my(start)} ➔ {label} {clock_my(end)} ({fmt_duration(start, end)})"


def clock_my(value):
    try:
        return parse_ts(value).astimezone(timezone(timedelta(hours=8))).strftime("%H:%M MY")
    except Exception:
        return "—"


def fmt_move(sig, level, signed=False):
    """Paparkan jarak level: BTC dalam USD, pair lain dalam pips."""
    n = fmt_pips(sig, level)
    if sig.get("pair") == "BTC/USD":
        sign = "+" if signed and float(level) != float(sig["entry"]) else ""
        return f"{sign}${n:,.2f}"
    sign = "+" if signed and float(level) != float(sig["entry"]) else ""
    return f"{sign}{n:.1f} pips"


def build_message(event, sig, price, st=None):
    st = st or {}
    side = str(sig["side"]).upper()
    direction = "Long" if side == "BUY" else "Short"
    arrow = "🟢 BUY" if side == "BUY" else "🔴 SELL"
    head = "━━━━━━━━━━━━━━━━━━━━"
    if event == "entry":
        return (f"🎯 <b>ENTRY TRIGGERED</b>\n{head}\n"
                f"{arrow} <b>{sig['pair']}</b> · {sig.get('timeframe') or 'M15'}\n\n"
                f"<pre>Entry   {fmt_price(sig['pair'], sig['entry'])}\n"
                f"SL      {fmt_price(sig['pair'], sig['sl'])}   -{fmt_move(sig, sig['sl'])}\n"
                f"TP      {fmt_price(sig['pair'], sig['tp'])}   +{fmt_move(sig, sig['tp'])}</pre>\n"
                f"Price reached your entry ({fmt_price(sig['pair'], price)}).\n"
                f"Setup is now active — manage your risk.")
    if event == "sl":
        start = st.get("entry_at") or sig.get("posted_at")
        end = st.get("closed_at") or datetime.now(timezone.utc).isoformat()
        return (f"🛑 <b>Trade #{sig.get('id', '—')} • {sig['pair']} {side} ({direction})</b>\n"
                f"Stop Loss reached — the setup was closed according to the risk plan.\n"
                f"⏱️ Time: {_timing_line(st, start, end, 'SL hit')} "
                f"({fmt_duration(start, end)})\n\n"
                f"📍 Entry Zone: <code>{fmt_price(sig['pair'], sig['entry'])}</code>\n"
                f"🛡️ Stop Loss: <code>{fmt_price(sig['pair'], sig['sl'])}</code> "
                f"(-{fmt_move(sig, sig['sl'])})\n"
                f"🎯 Take Profit: <code>{fmt_price(sig['pair'], sig['tp'])}</code> "
                f"(+{fmt_move(sig, sig['tp'])})\n\n"
                f"Risk was contained as planned. Wait for the next confirmed setup — "
                f"do not chase price.\n\n"
                f"📡 Follow <b>@Traderwatchmembershipbot</b> for confirmed setups. "
                f"Educational information only — not financial advice.")
    if event == "expired":
        order = ("BUY pending order (Buy Limit / Buy Stop Limit)" if side == "BUY"
                 else "SELL pending order (Sell Limit / Sell Stop Limit)")
        return (f"⌛ <b>SETUP EXPIRED</b>\n{head}\n"
                f"{arrow} <b>{sig['pair']}</b> · {sig.get('timeframe') or 'M15'}\n\n"
                f"<pre>Entry   {fmt_price(sig['pair'], sig['entry'])}\n"
                f"SL      {fmt_price(sig['pair'], sig['sl'])}   -{fmt_move(sig, sig['sl'])}\n"
                f"TP      {fmt_price(sig['pair'], sig['tp'])}   +{fmt_move(sig, sig['tp'])}</pre>\n"
                f"Price did not reach the entry within <b>{EXPIRY_MIN} minutes</b>.\n\n"
                f"❌ <b>Cancel the {order} for this setup now.</b>\n\n"
                f"No position was opened. This setup is no longer valid.\n"
                f"We are scanning for a new setup.")
    # Timestamp sebenar. JANGAN jatuh balik kepada now(): bukan itu masa
    # TP kena, dan ialundur setiap kali mesej dibina semula — jadi duration
    # jadi berubah-ubah (laporan "TP hit 1m" padahal 6 minit).
    # Tanpa closed_at yang sah, lebih baik tunjuk "—" daripada angka salah.
    start = st.get("entry_at") or st.get("first_touch") or sig.get("posted_at")
    end = st.get("closed_at")
    risk = fmt_pips(sig, sig["sl"])
    reward = fmt_pips(sig, sig["tp"])
    rr = reward / risk if risk else 0.0
    reason = (sig.get("reason") or
              "Price reacted from the monitored entry area and moved in the planned direction "
              "until the Take Profit objective was reached. Risk remained defined by the "
              "original Stop Loss; future outcomes are not guaranteed.")
    return (f"🎯 <b>Trade #{sig.get('id', '—')} • {sig['pair']} {side} ({direction})</b>\n"
            f"Take Profit reached successfully!\n"
            f"⏱️ Time: {_timing_line(st, start, end)}\n\n"
            f"📍 Entry Zone: <code>{fmt_price(sig['pair'], sig['entry'])}</code>\n"
            f"🛡️ Stop Loss: <code>{fmt_price(sig['pair'], sig['sl'])}</code> "
            f"(-{fmt_move(sig, sig['sl'])})\n"
            f"🎯 Take Profit: <code>{fmt_price(sig['pair'], sig['tp'])}</code> "
            f"(+{fmt_move(sig, sig['tp'])} • R:R 1:{rr:.2f})\n\n"
            f"💡 <b>Execution Rationale:</b>\n{reason}\n\n"
            f"Want to receive confirmed setups in real time before price moves?\n"
            f"Follow <b>@Traderwatchmembershipbot</b>. "
            f"Educational information only — not financial advice.")


def _status_key(sig):
    """Kunci yang sama dengan signal-status.py: CODE_YYYYMMDD_HHMMSS (KL).

    WAJIB guna konvensi timezone yang sama: timestamp Supabase tanpa
    zon bermaksud UTC,tukar ke KL selepas. Kalau salah, kunci tak
    sepadan dengan signal-status.json dan backfill senyap je.
    """
    raw = str(sig["posted_at"]).replace("Z", "+00:00")
    d = datetime.fromisoformat(raw)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone(timedelta(hours=8)))
    code = "".join(ch for ch in str(sig["pair"]).upper() if ch.isalpha())
    return f"{code}_{d:%Y%m%d}_{d:%H%M%S}"


def _load_status_map():
    """Isi signal-status.json -> {key: {...}} (dikongsi antara proses)."""
    path = Path("/home/ubuntu/web/Traderwatch-repo/signal-status.json")
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data.get("signals") or {}


def _backfill_from_status(sig, st, sid, targets, dry_run=False):
    """Hantar notifikasi TP/SL yang tertinggal untuk signal 'legacy'.

    Syarat:
      - status.json ada rekod untuk signal ini
      - status adalah tp atau sl
      - peristiwa itu berlaku dalam BACKFILL_MAX_AGE_HOURS (elak spam
        member dengan keputusan lama yang masih belum ditutup)
    Return True bila notifikasi dihantar (atau di dry-run).
    """
    key = _status_key(sig)
    info = _load_status_map().get(key)
    if not info:
        # Tiada rekod status: jangan main semula bar lama (spam). Tutup
        # legacy sebagai "unknown" supaya tak di-recheck setiap minit.
        st["closed"] = "unknown"
        st["backfilled"] = False
        log(f"BACKFILL-NORECORD #{sid} {sig['pair']} key={key} — "
            f"tiada rekod status, ditutup senyap")
        return True
    status = str(info.get("status") or "").lower()
    if status not in ("tp", "sl"):
        return False
    closed_raw = info.get("closed")
    if not closed_raw:
        return False
    try:
        closed_dt = parse_ts(closed_raw)
    except Exception:
        return False
    age_h = (datetime.now(timezone.utc) - closed_dt).total_seconds() / 3600.0
    if age_h > BACKFILL_MAX_AGE_HOURS:
        # Peristiwa lama: tutup state TANPA hantar mesej. Kalau tak ditutup,
        # evaluate_bars akan main semula bar lama dan hantar notifikasi
        # basi — spam member dengan keputusan 2-3 hari lalu.
        st["closed"] = status
        st["closed_at"] = closed_dt.isoformat()
        st["backfilled"] = False
        log(f"BACKFILL-SKIP #{sid} {sig['pair']} {status} — lama "
            f"({age_h:.1f}h > {BACKFILL_MAX_AGE_HOURS}h), ditutup senyap")
        return True

    st["closed"] = status
    st["closed_at"] = closed_dt.isoformat()
    st["backfilled"] = True
    text = build_message(status, sig, None, st)
    png = render_result_chart(sig, st)
    s, f, ok_chats = dispatch(text, targets, dry_run=dry_run, png=png)
    st["notified"] = sorted(set(st.get("notified") or []) | set(str(c) for c in ok_chats))
    log(f"BACKFILL {status} #{sid} {sig['pair']} pips={info.get('pips')} "
        f"age={age_h:.1f}h chart={'yes' if png else 'no'} sent={s} fail={f}")
    return True


def _pending_chats(st, targets):
    """Chat yang belum dapat notifikasi untuk signal ini."""
    done = set(str(c) for c in (st.get("notified") or []))
    chats = [int(t["telegram_chat_id"]) for t in targets]
    if ADMIN_CHAT and ADMIN_CHAT.isdigit() and int(ADMIN_CHAT) not in chats:
        chats.append(int(ADMIN_CHAT))
    return [c for c in chats if str(c) not in done]


def _repair_notify(sig, st, sid, targets, pending, dry_run=False):
    """Hantar notifikasi TP/SL yang hilang kepada chat yang belum dapat."""
    closed_raw = st.get("closed_at")
    try:
        closed_dt = parse_ts(closed_raw) if closed_raw else datetime.now(timezone.utc)
    except Exception:
        closed_dt = datetime.now(timezone.utc)
    age_h = (datetime.now(timezone.utc) - closed_dt).total_seconds() / 3600.0
    if age_h > BACKFILL_MAX_AGE_HOURS:
        log(f"REPAIR-SKIP #{sid} {sig['pair']} {st.get('closed')} — lama "
            f"({age_h:.1f}h > {BACKFILL_MAX_AGE_HOURS}h)")
        st["legacy_repaired"] = True
        return False
    sub = [t for t in targets if int(t["telegram_chat_id"]) in pending]
    if not sub:
        st["legacy_repaired"] = True
        return False
    text = build_message(st["closed"], sig, None, st)
    png = render_result_chart(sig, st)
    s, f, ok_chats = dispatch(text, sub, dry_run=dry_run, png=png)
    st["notified"] = sorted(set(st.get("notified") or []) | set(str(c) for c in ok_chats))
    st["legacy_repaired"] = True
    log(f"REPAIR {st.get('closed')} #{sid} {sig['pair']} "
        f"pending={pending} sent={s} fail={f} age={age_h:.1f}h")
    return True


def dispatch(text, targets, dry_run=False, png=None):
    """Hantar ke semua target + admin. Jika ada PNG, guna photo+caption.

    Pulangkan (sent, failed, ok_chats) — ok_chats ialah senarai chat_id yang
    berjaya terima, supaya state boleh catat siapa yang sudah tahu. Tanpa
    ini, repair pass akan hantar semula mesej yang member sudah terima.
    """
    sent = failed = 0
    ok_chats = []
    chats = [int(t["telegram_chat_id"]) for t in targets]
    if ADMIN_CHAT and ADMIN_CHAT.isdigit() and int(ADMIN_CHAT) not in chats:
        chats.append(int(ADMIN_CHAT))
    for cid in chats:
        if dry_run:
            log(f"DRY-RUN would send -> {cid}")
            sent += 1
            continue
        ok, desc = tg_photo(cid, png, text) if png else tg_send(cid, text)
        if ok:
            sent += 1
            ok_chats.append(cid)
        else:
            failed += 1
            log(f"SEND-FAIL chat={cid} {desc[:100]}")
        time.sleep(0.4)
    return sent, failed, ok_chats


# ---------------------------------------------------------------- utama
def _run(dry_run=False):
    signals = fetch_signals()
    if not signals:
        log("no verified signals in window")
        return 0
    state = load_state()
    targets = fetch_targets()
    log(f"signals={len(signals)} targets={len(targets)} dry_run={dry_run}")

    seen = set()
    events = 0
    repair_sent = 0
    for sig in signals:
        sid = str(sig["id"])
        seen.add(sid)
        try:
            entry = float(sig["entry"])
            sl = float(sig["sl"])
            tp = float(sig["tp"])
        except (TypeError, ValueError):
            log(f"SKIP {sid}: level tidak sah")
            continue
        if not ((sig["side"] == "BUY" and sl < entry < tp) or
                (sig["side"] == "SELL" and tp < entry < sl)):
            log(f"SKIP {sid}: geometri SL/TP tidak sah")
            continue

        st = state.get(sid)
        bootstrap = st is None
        if bootstrap:
            st = {"entry": False, "closed": None, "first_touch": None}
        else:
            st.setdefault("first_touch", None)
        # REPAIR: signal yang sudah tutup (tp/sl) tapi ada member yang belum
        # dapat notifikasi. Contoh #102 XAU/USD TP +300 pips — state ditulis
        # 'closed' tapi mesej tak pernah dihantar (dry-run tersalah simpan
        # state). Hantar semula hanya kepada chat yang belum dapat.
        if (not bootstrap and st.get("closed") in ("tp", "sl")
                and not st.get("legacy_repaired")
                and not st.get("notified")):
            # Repair HANYA untuk signal yang belum pernah ada rekod
            # notifikasi langsung. Signal yang ada `notified` sudah pun
            # sampai ke member — jANGAN hantar semula.
            pending = _pending_chats(st, targets)
            if pending:
                if repair_sent >= REPAIR_MAX_PER_RUN:
                    log(f"REPAIR-CAP reached ({REPAIR_MAX_PER_RUN}) — "
                        f"hantar lagi pada run seterusnya")
                    continue
                if _repair_notify(sig, st, sid, targets, pending, dry_run):
                    repair_sent += 1
                    events += 1
                    state[sid] = st
                    continue
        # Legacy (warisan kod lama) — HARUS dikendalikan SEBELUM evaluate.
        # Kalau biarkan evaluate_bars main semula bar lama, notifikasi
        # TP/SL yang sudah 2-3 hari akan dihantar sekarang = spam member.
        if st.get("closed") == "legacy":
            if _backfill_from_status(sig, st, sid, targets, dry_run):
                state[sid] = st
                events += 1
            continue
        # Signal FRESH: baru posting (dalam grace window) ketika bot mula.
        # Such signal mesti dipantau seperti biasa, bukan "legacy".
        fresh = False
        if bootstrap:
            try:
                age_min = (datetime.now(timezone.utc) -
                           parse_ts(sig["posted_at"])).total_seconds() / 60.0
                fresh = age_min <= GRACE_MIN
            except Exception:
                fresh = False
            if fresh:
                bootstrap = False
                log(f"FRESH {sid} {sig['pair']} age={age_min:.1f}min "
                    f"— dipantau (bukan legacy)")

        price = None
        try:
            price = live_price(sig["pair"])
        except Exception as ex:
            log(f"PRICE-FAIL {sig['pair']}: {type(ex).__name__} {ex}")

        bars = bars_since(sig["pair"], parse_ts(sig["posted_at"]))
        if bars:
            if price is None:
                price = (bars[-1][1] + bars[-1][2]) / 2
            # State menyimpan entry yang telah diumumkan. Jangan replay semua
            # bar sejak posted_at selepas itu — bar TP lama (sebelum fill)
            # akan kelihatan selepas entry dan menghasilkan TP palsu.
            eval_bars = bars
            if st.get("entry") and st.get("entry_at"):
                entered_at = parse_ts(st["entry_at"])
                eval_bars = [b for b in bars if parse_ts(b[0]) > entered_at]
            found = evaluate_bars(sig, eval_bars, st, bootstrap=bootstrap)
        elif price is not None:
            found = evaluate(sig, price, st, bootstrap=bootstrap)
        else:
            continue
        state[sid] = st
        if bootstrap:
            # Baseline sahaja: apa-apa signal yang wujud sebelum feature ini
            # dimulakan tidak boleh menghasilkan notifikasi tertunggak.
            # Yang sudah entry DAN sudah TP/SL ditutup legacy; yang sudah
            # >30 min tanpa entry ditutup expired secara SENAP.
            # PENTING: posisi yang sudah entry tetapi BELUM TP/SL mesti
            # dipantau — kalau tidak, TP sebenar selepas bootstrap hilang
            # (ini yang menyebabkan TP USD/JPY #91 tidak pernah dihantar).
            if st.get("entry"):
                if st.get("closed") in ("tp", "sl"):
                    pass                      # sudah selesai semasa bootstrap
                elif is_expired(sig, st, datetime.now(timezone.utc), EXPIRY_MIN) \
                        and st.get("first_touch") is None:
                    st["closed"] = "expired"
                else:
                    # posisi aktif: jangan tutup, pantau macam biasa
                    log(f"BOOTSTRAP {sid} {sig['pair']} price={price} "
                        f"entry=True — monitoring (bukan legacy)")
                    state[sid] = st
                    continue
            elif is_expired(sig, st, datetime.now(timezone.utc), EXPIRY_MIN):
                st["closed"] = "expired"
            log(f"BOOTSTRAP {sid} {sig['pair']} price={price} "
                f"entry={st['entry']} closed={st['closed']}")
            continue

        # Hanya pending BUY LIMIT / SELL LIMIT. Bila entry=True, ia sudah jadi
        # posisi dan tidak tertakluk kepada expiry 30 minit.
        if is_expired(sig, st, datetime.now(timezone.utc), EXPIRY_MIN,
                      price=price, bars=bars):
            st["closed"] = "expired"
            text = build_message("expired", sig, None, st)
            png = render_result_chart(sig, st)
            s, f, ok_chats = dispatch(text, targets, dry_run=dry_run, png=png)
            st["notified"] = sorted(set(st.get("notified") or []) | set(str(c) for c in ok_chats))
            log(f"EVENT expired #{sid} {sig['pair']} "
                f"chart={'yes' if png else 'no'} sent={s} fail={f}")
            events += 1
            continue

        for ev in found:
            text = build_message(ev, sig, price, st)
            png = render_result_chart(sig, st) if ev in ("tp", "sl", "entry", "expired") else None
            s, f, ok_chats = dispatch(text, targets, dry_run=dry_run, png=png)
            st["notified"] = sorted(set(st.get("notified") or []) | set(str(c) for c in ok_chats))
            log(f"EVENT {ev} #{sid} {sig['pair']} price={price} "
                f"chart={'yes' if png else 'no'} sent={s} fail={f}")
            events += 1

    # buang state signal yang dah keluar tetingkap
    state = {k: v for k, v in state.items() if k in seen}
    # PENTING: dry-run TIDAK boleh tulis state. Sebelum ini, dry-run
    # menyimpan state "closed" untuk signal yang hartanya belum
    # dihantar — isyarat TP/SL hilang selamanya. Ini punca #102 XAU/USD
    # TP (+300 pips) tak pernah sampai ke member.
    if dry_run:
        log("DRY-RUN: state TIDAK disimpan")
    else:
        save_state(state)
    log(f"done events={events} tracked={len(state)}")
    return 0


def main():
    args = set(sys.argv[1:])
    if "--reset" in args:
        STATE_FILE.unlink(missing_ok=True)
        log("state direset")
        return 0
    dry_run = "--dry-run" in args

    # Flock-based single instance. Age-based "stale lock" tidak selamat:
    # satu run yang mengambil >120 saat (contohnya repair banyak signal)
    # akan pecah lock, dan cron seterusnya mula run kedua yang selari ->
    # notifikasi dihantar DUA kali. Flock tak boleh dipecah selagi proses
    # masih hidup.
    import fcntl
    lock_fd = open(LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("SKIP instance lain sedang jalan")
        lock_fd.close()
        return 0
    lock_fd.write(str(__import__("os").getpid()))
    lock_fd.flush()
    try:
        return _run(dry_run=dry_run)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        log(f"FATAL {type(ex).__name__}: {ex}")
        sys.exit(1)
