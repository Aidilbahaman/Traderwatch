#!/usr/bin/env python3
"""TraderWatch AI signal engine - M15, logistic model decides side + trade.

The model is trained offline by train-ai-model.py and loaded from
state/ai-m15-model.json. This script never refits, so a cron tick cannot stall.

Differences from signal-engine.py (the rule engine):
  * decision is a trained logistic model, not EMA/RSI trigger rules
  * timeframe is M15 only
  * threshold gate: emit only when max(p_long, p_short) >= THRESHOLD

Shared with the rule engine:
  * one active setup per pair across all timeframes (pair lifecycle guard)
  * one setup per pair per timeframe per day (daily dedupe)
  * SL = max(1.5*ATR, 12 pips), TP = 2*SL
  * fail closed when the status file or Supabase check errors

Secrets: ~/.secrets/twelve.env, ~/.secrets/supabase.env
"""
import importlib.util
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import ai_model as M  # noqa: E402

TIMEOUT = 25
TZ_KL = timezone(timedelta(hours=8))
CALL_GAP = 9
RETRY_WAIT = 62
CANDLES = 300
REPO = HERE.parent
STATUS_FILE = REPO / "signal-status.json"
MODEL_FILE = REPO / "state" / "ai-m15-model.json"
MEMO_FILE = REPO / "state" / "learning-memo.json"
LOCK = Path("/tmp/signal-engine-ai.lock")

# Mod private: AI terus publish ke akaun OWNER sahaja (bukan member).
# Signal didaftarkan dalam state/private-signals.json supaya lifecycle
# hantar owner sahaja dan MT5 execute dengan lot risiko 1%.
PRIVATE_MODE = os.environ.get("AI_PRIVATE", "1") == "1"
THRESHOLD = 0.50  # diturunkan owner 5 Nov 2026 (dari 0.55) supaya calon 0.50-0.54 lulus
XAUUSD_THRESHOLD = 0.35
# Lantai SL 15 pip: spread RoboForex besar (EURUSD 1.3, USDJPY 1.9,
# XAUUSD 2.1 pip). 15 pip hadkan drag spread bawah ~13% SL.
SCALP_MIN_SL_PIPS = 15.0
SCALP_RR = 2.0
TIMEFRAME = "M15"
TD_INTERVAL = "15min"

PAIRS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"]
DP = {"XAU/USD": 2, "USD/JPY": 3}
DEFAULT_DP = 5


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def load_secrets(name):
    vals = {}
    p = Path.home() / ".secrets" / name
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


SB = load_secrets("supabase.env")
SB_URL = SB["SUPABASE_URL"]
SB_KEY = SB["SUPABASE_SERVICE_KEY"]
TD_KEY = ""


def sb(path, method="GET", body=None, prefer="return=minimal"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{path}", data=data, method=method,
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                 "Content-Type": "application/json",
                 "Prefer": prefer})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def sq_bars(symbol, interval, outputsize=CANDLES):
    """Swissquote bars (dari collector daemon) - tiada had kuota."""
    import importlib.util as _il
    spec = _il.spec_from_file_location("sqc", HERE / "sq_collector.py")
    m = _il.module_from_spec(spec)
    spec.loader.exec_module(m)
    pair = symbol.replace("/", "")
    # Collector simpan gran sebagai M1/M5/M15/... ; enjin hantar format TD.
    gran = {"1min": "M1", "5min": "M5", "15min": "M15", "30min": "M30",
            "1h": "H1", "60min": "H1"}.get(str(interval).lower(), interval)
    rows = m.candles_from_bars(pair, gran, outputsize)
    # Selaraskan dengan parse_candles(): (ts_ms, high, low, close)
    out = []
    for c in rows:
        try:
            d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            out.append((int(d.timestamp() * 1000), float(c["h"]),
                        float(c["l"]), float(c["c"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def td_get(symbol, interval, outputsize=CANDLES):
    for attempt in (1, 2):
        url = ("https://api.twelvedata.com/time_series"
               f"?symbol={urllib.parse.quote(symbol, safe='')}&interval={interval}"
               f"&outputsize={outputsize}&apikey={TD_KEY}&timezone=UTC")
        req = urllib.request.Request(url, headers={"User-Agent": "TraderWatch-ai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            if e.code == 429 and attempt == 1:
                log(f"RATE-LIMIT {symbol}: wait {RETRY_WAIT}s")
                time.sleep(RETRY_WAIT)
                continue
            return {"code": e.code, "message": body}
        except Exception as e:
            return {"code": -1, "message": f"{type(e).__name__}: {e}"}
    return {"code": 429, "message": "rate limit persisted"}


def parse_candles(payload):
    vals = (payload or {}).get("values")
    if not vals:
        return None, f"no candles: {str(payload)[:150]}"
    out = []
    for v in reversed(vals):
        d = datetime.fromisoformat(v["datetime"].replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append((int(d.timestamp() * 1000), float(v["high"]),
                    float(v["low"]), float(v["close"])))
    return out, ""


def today_start():
    now_kl = datetime.now(timezone.utc).timestamp() + 8 * 3600
    kl_date = datetime.fromtimestamp(now_kl, tz=timezone.utc).strftime("%Y-%m-%d")
    start_utc = datetime.fromisoformat(kl_date + "T00:00:00+00:00").timestamp() - 8 * 3600
    return datetime.fromtimestamp(start_utc, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key_for(pair, posted_at):
    """Same key shape signal-status.py writes: CODE_YYYYMMDD_HHMMSS in KL."""
    code = "".join(ch for ch in str(pair).upper() if ch.isalpha())
    d = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return f"{code}_{d.astimezone(TZ_KL).strftime('%Y%m%d_%H%M%S')}"


def pair_recent_unresolved(pair, state):
    """True when the pair's newest DB signal is not yet resolved.

    Closes the race between posting a signal and signal-status.py recording it
    as active: an unknown or active key both block a new post.
    """
    code, txt = sb(f"signals?select=posted_at&pair=eq.{urllib.parse.quote(pair)}"
                   f"&verified=is.true&order=posted_at.desc&limit=1")
    if code != 200:
        return True
    try:
        rows = json.loads(txt or "[]")
    except Exception:
        return True
    if not rows:
        return False
    key = key_for(pair, rows[0]["posted_at"])
    info = (state.get("signals") or {}).get(key)
    if not info:
        return True
    return str(info.get("status")).lower() == "active"


def already_posted(pair):
    code, txt = sb(f"signals?select=id&pair=eq.{urllib.parse.quote(pair)}"
                   f"&timeframe=eq.{TIMEFRAME}&verified=is.true"
                   f"&posted_at=gte.{today_start()}&limit=1")
    if code != 200:
        return True
    return txt.strip() not in ("[]", "")


def load_status_state():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception as e:
        log(f"ERROR status file: {e}")
        return None


def lifecycle_state():
    """State lifecycle (entry/closed) dikongsi dengan signal-lifecycle-alert.py."""
    p = REPO.parent / ".signal-lifecycle.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def gated_by_memo(pair):
    """True jika learning-memo gate pair ini (WR<25% / net<=-25, min 5 setups).

    Fail open bila memo tiada - gate prestasi, bukan gate keselamatan.
    """
    try:
        gates = (json.loads(MEMO_FILE.read_text()).get("gates") or {}).get("pairs") or []
        return pair.replace("/", "").upper() in {str(g).upper() for g in gates}
    except Exception:
        return False


def pair_blocked(pair, state, life):
    """True jika pair patut dilangkau kerana setup masih hidup.

    Setup yang sudah expired/legacy/tp/sl TIDAK menyekat pair baru - ini
    yang membolehkan enjin cari setup pengganti selepas 30 minit tamat.
    """
    code, txt = sb(f"signals?select=id,posted_at&pair=eq.{urllib.parse.quote(pair)}"
                   f"&verified=is.true&order=posted_at.desc&limit=1")
    if code != 200:
        return True                     # fail closed
    try:
        rows = json.loads(txt or "[]")
    except Exception:
        return True
    if not rows:
        return False

    row = rows[0]
    info = life.get(str(row["id"])) or {}
    closed = str(info.get("closed") or "").lower()
    if closed in ("expired", "legacy", "tp", "sl"):
        return False                    # sudah selesai -> jangan sekat
    if info.get("entry"):
        return True                     # posisi masih terbuka

    # Tiada rekod lifecycle: guna signal-status.json seperti asal.
    key = key_for(pair, row["posted_at"])
    st = (state.get("signals") or {}).get(key)
    if not st:
        return True
    return str(st.get("status")).lower() == "active"


def pair_has_active(pair, state):
    code = "".join(ch for ch in pair.upper() if ch.isalpha())
    for key, info in (state.get("signals") or {}).items():
        if str(info.get("status")).lower() != "active":
            continue
        if str(key).split("_", 1)[0] == code:
            return True
    return False


def in_session(now=None):
    """08:00-01:00 MYT - covers Asian open through New York close.

    Sized so 7 pairs at a 10-minute scan plus a 15-minute status sweep land
    around 700 of the 800 free daily credits.
    """
    h = (now or datetime.now(TZ_KL)).astimezone(TZ_KL).hour
    return h >= 8 or h < 1


def h1_trend(bars_m15):
    """Trend H1 daripada agregat M15: +1 UP, -1 DOWN, 0 tidak jelas.

    4 bar M15 = 1 jam. EMA20/EMA50 atas 60 jam (~240 bar M15).
    """
    closes = [b[3] for b in bars_m15]
    if len(closes) < 240:
        return 0
    h1 = [closes[i] for i in range(3, len(closes), 4)]
    if len(h1) < 60:
        return 0
    e20, e50 = M.ema(h1, 20), M.ema(h1, 50)
    gap = (e20[-1] - e50[-1]) / max(1e-9, e20[-1])
    if gap > 0.0005:
        return 1
    if gap < -0.0005:
        return -1
    return 0


# Pair yang wajib ikut arah H1 (peraturan owner 30 Okt 2026):
# XAU/USD dilarang counter-trend selepas BUY #185 dalam downtrend.
TREND_FOLLOW_PAIRS = {"XAU/USD"}


def decide(model, bars):
    """Return (side, confidence) or (None, 0.0)."""
    closes = [b[3] for b in bars]
    if len(closes) < 60:
        return None, 0.0
    e20, e50 = M.ema(closes, 20), M.ema(closes, 50)
    rsi, atr = M.rsi_s(closes), M.atr_s(bars)
    i = len(bars) - 1
    feat_idx = model.get("feat_idx")
    if feat_idx is None or feat_idx == "v1-8dim":
        # v1 pair: frozen 8-dim features, unchanged path.
        f = M.feature_row(model["_pair"], bars, e20, e50, rsi, atr, i)
    else:
        # v2x pair: project the shared v2 computation to the pair's indices.
        # Fail closed on any v2 input shortfall (returns None, 0.0 below).
        try:
            ctx = M.build_v2_ctx(model["_pair"], bars,
                                 STATUS_FILE if STATUS_FILE.exists() else None)
            f = M.feature_row_v2x(model["_pair"], bars, e20, e50, rsi, atr,
                                  i, ctx, feat_idx)
        except Exception:
            f = None
    if f is None:
        return None, 0.0
    p_long = M.predict(model["long"], f)
    p_short = M.predict(model["short"], f)
    side = "BUY" if p_long >= p_short else "SELL"
    conf = max(p_long, p_short)
    pair_key = model.get("_pair")
    thresh = XAUUSD_THRESHOLD if pair_key == "XAU/USD" else THRESHOLD
    if conf < thresh:
        return None, conf
    HIGH_CONF_FADE = 0.85   # partial-exception owner 5 Nov 2026
    FADE_ATR = 0.5          # SELL counter-trend dibenarkan hanya bila conf >= 0.85
    FADE_LOOKBACK = 96      # DAN harga <= 0.5 ATR dari high 24 jam (96x M15).
    if model.get("_pair") in TREND_FOLLOW_PAIRS:
        tr = h1_trend(bars)
        want = "BUY" if tr > 0 else ("SELL" if tr < 0 else None)
        if want is None and conf < HIGH_CONF_FADE:
            log(f"TREND-SKIP {model.get('_pair')}: H1 tidak jelas, counter-trend dilarang")
            return None, conf
        if side != want:
            _atr = M.atr_s(bars)[-1] or 0.0
            _hh = max(b[1] for b in bars[-FADE_LOOKBACK:])
            _ll = min(b[2] for b in bars[-FADE_LOOKBACK:])
            _px = bars[-1][3]
            if side == "SELL" and tr > 0 and (conf >= HIGH_CONF_FADE
                                               and _px >= _hh - FADE_ATR * _atr):
                log(f"FADE-OK {model.get('_pair')}: SELL conf {conf:.3f} >= {HIGH_CONF_FADE} "
                    f"dekat high 24j ({_px:.2f} vs {_hh:.2f}) - fade top dibenarkan")
            elif side == "BUY" and tr < 0 and (conf >= HIGH_CONF_FADE
                                               and _px <= _ll + FADE_ATR * _atr):
                log(f"FADE-OK {model.get('_pair')}: BUY conf {conf:.3f} >= {HIGH_CONF_FADE} "
                    f"dekat low 24j ({_px:.2f} vs {_ll:.2f}) - fade bottom dibenarkan")
            else:
                log(f"TREND-SKIP {model.get('_pair')}: model {side} lawan H1 "
                    f"({'UP' if tr > 0 else 'DOWN'}), disekat")
                return None, conf
    return side, conf


def build_levels(pair, side, price, atr):
    pip = M.pip_of(pair)
    sl_dist = max(1.5 * atr, SCALP_MIN_SL_PIPS * pip)
    tp_dist = sl_dist * SCALP_RR
    if side == "BUY":
        return price - sl_dist, price + tp_dist
    return price + sl_dist, price - tp_dist


OWNER_CHAT_ID = "7696607055"


def notify_owner(pair, side, row, conf, txt, news_line="", executed=False):
    """Hantar signal AI kepada owner secara private (Telegram).

    Mod private (executed=True): signal sudah publish + didaftarkan private.
    Mesej kepada owner ialah "SUDAH LIVE — MT5 akan execute / posisi
    dibina", bukan cadangan. Tiada butang Post — tak perlu approve.
    Risiko SL sudah ditulis supaya owner tahu dollar at risk.

    Mod cadangan (executed=False): draft verified=False. Mesej lama kekal:
    butang Post ke member / Tolak.

    Sender: @CCSTWbot (BOT_TOKEN dalam /home/ubuntu/tw-bot/.env) supaya
    nampak sebagai chat dengan bot admin, bukan sender member.
    Fail-safe: sebarang kegagalan hantar TIDAK menggagalkan engine run;
    private signal tetap live di DB + private registry.
    """
    try:
        bot_tok = ""
        try:
            bot_tok = pathlib.Path("/home/ubuntu/tw-bot/.env").read_text().split("BOT_TOKEN=")[1].split()[0].strip().strip('"').strip("'")
        except Exception:
            bot_tok = ""
        if not bot_tok:
            # Fallback: jika admin bot mati (404/revoke), guna bot signals yang aktif
            # supaya notifikasi private tetap sampai ke owner (chat sama).
            sev = load_secrets("telegram.env")
            bot_tok = sev.get("TELEGRAM_ADMIN_BOT_TOKEN", "") or sev.get("TELEGRAM_BOT_TOKEN", "") or sev.get("TELEGRAM_SIGNALS_BOT_TOKEN", "")
        if not bot_tok:
            log("WARN notify_owner: tiada token Telegram, skip notifikasi")
            return
        try:
            sid = (json.loads(txt or "[]") or [{}])[0].get("id", "?")
        except Exception:
            sid = "?"
        icon = "\U0001f7e2 BUY" if str(side).upper() == "BUY" else "\U0001f534 SELL"
        rr = (abs(float(row["tp"]) - float(row["entry"]))
              / max(1e-9, abs(float(row["entry"]) - float(row["sl"]))))
        pip = M.pip_of(pair)
        sl_pips = abs(float(row["entry"]) - float(row["sl"])) / pip
        tp_pips = abs(float(row["tp"]) - float(row["entry"])) / pip
        # Anggaran wang pada 0.01 lot: 1 pip FX ~ $0.10; XAU 0.1 pip-unit ~ $0.10.
        risk_usd = sl_pips * 0.1
        reward_usd = tp_pips * 0.1
        acct_note = (f"\n\u26a0\ufe0f Risiko ~<b>${risk_usd:.0f}</b> ({sl_pips:.1f} pips) | "
                     f"Reward ~<b>${reward_usd:.0f}</b> ({tp_pips:.1f} pips) pada 0.01 lot"
                     + (" - akaun bawah $100, pertimbang skip atau lot lebih kecil" if risk_usd > 5 else ""))
        arrow = "\u2b06\ufe0f" if str(side).upper() == "BUY" else "\u2b07\ufe0f"
        kb = None      # mod private tiada butang; ditakrif di sini supaya
                       # cabang `executed` tidak UnboundLocalError.
        if executed:
            # Sesuai permintaan: Ai Signal (Pair) (Buy/Sell) (Size lot) (Account balance)
            # Dapatkan equity live atau anggaran ~$353
            msg = (f"🤖 <b>AI Signal</b>  <b>{pair}</b>  <b>{side}</b>  ~10% Risk  |  Equity ~$353\n"
                   f"━━━━━━━━━━━━━━━━━━━━\n"
                   f"{icon}  Entry <code>{row['entry']}</code>\n"
                   f"🛡️ SL <code>{row['sl']}</code> ({sl_pips:.1f} pips)\n"
                   f"🎯 TP <code>{row['tp']}</code> ({tp_pips:.1f} pips, RR 1:{rr:.1f})\n"
                   f"Confidence {conf:.3f} • Grade A+ • Private AI\n"
                   f"{news_line}\n\n"
                   f"Setup active — MT5 auto-executing.")
        else:
            msg = (f"\U0001f916 <b>AI CADANGAN (draft #{sid})</b>\n"
                   f"\U0001f4ca <b>{pair}</b> \u00b7 M15\n"
                   f"{icon}\n"
                   f"\U0001f3af Entry <code>{row['entry']}</code>\n"
                   f"\U0001f6e1\ufe0f SL <code>{row['sl']}</code> ({sl_pips:.1f} pips) | "
                   f"\U0001f3af TP <code>{row['tp']}</code> ({tp_pips:.1f} pips, RR 1:{rr:.1f})\n"
                   f"\U0001f9e0 Confidence {conf:.3f}{acct_note}{news_line}\n\n"
                   f"Balas di bot: <b>Post</b> untuk hantar ke member, "
                   f"<b>Tolak</b> untuk buang draft ini.")
            kb = {"inline_keyboard": [[
                {"text": "\u2705 Post ke member", "callback_data": f"ai:post:{sid}"},
                {"text": "\u274c Tolak", "callback_data": f"ai:reject:{sid}"}]]}
        payload = {"chat_id": OWNER_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        if kb:
            payload["reply_markup"] = json.dumps(kb)
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + bot_tok + "/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        log(f"NOTIFY owner #{sid} {pair} {side} executed={executed}")
    except Exception as e:
        detail = ""
        try:
            import urllib.error as _ue
            if isinstance(e, _ue.HTTPError):
                detail = f" HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
        except Exception:
            pass
        log(f"WARN notify_owner gagal ({type(e).__name__}{detail}); draft kekal untuk review manual")


CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CAL_CACHE = REPO / "state" / "calendar-cache.json"
NEWS_WINDOW_MIN = 30     # embargo +/-30 min (peraturan sedia ada)
BOOST_WINDOW_H = 6       # pengesahan kuat: High-impact <=6j ke depan


def _get_calendar():
    """Kalendar ForexFactory mingguan; cache <=6j; raise bila tiada data segar."""
    raw = None
    try:
        req = urllib.request.Request(CAL_URL, headers={"User-Agent": "TraderWatch/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
        if body.lstrip()[:1] in (b"[", b"{"):
            raw = json.loads(body)
            CAL_CACHE.write_bytes(body)
    except Exception:
        raw = None
    if raw is None:
        age = 1e18
        try:
            age = datetime.now().timestamp() - CAL_CACHE.stat().st_mtime
        except Exception:
            pass
        if age <= 6 * 3600:
            raw = json.loads(CAL_CACHE.read_text())
        else:
            raise RuntimeError("kalendar tidak tersedia")
    out = []
    for x in raw if isinstance(raw, list) else []:
        if x.get("impact") != "High":
            continue
        t = datetime.fromisoformat(str(x.get("date")))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        out.append({"when": t.astimezone(TZ_KL), "ccy": x.get("country", ""),
                    "title": x.get("title", ""),                    "fc": x.get("forecast", ""),
                    "prev": x.get("previous", "")})
    return sorted(out, key=lambda z: z["when"])


def news_context(pair, now_kl=None):
    """Kembalikan (embargo_event, upcoming_list) untuk pair.

    ccys = mata wang pair + USD. embargo = dalam +/-NEWS_WINDOW_MIN.
    upcoming = High-impact dalam 0..BOOST_WINDOW_H jam ke depan.
    Gagal kalendar -> raise (lapor, jangan anggap tiada berita).
    """
    now_kl = now_kl or datetime.now(TZ_KL)
    ccys = {"USD", pair[:3], pair[4:7]}
    embargo, upcoming = None, []
    for ev in _get_calendar():
        if ev["ccy"] not in ccys:
            continue
        dt_min = (ev["when"] - now_kl).total_seconds() / 60
        if abs(dt_min) <= NEWS_WINDOW_MIN and embargo is None:
            embargo = ev
        elif 0 < dt_min <= BOOST_WINDOW_H * 60:
            upcoming.append(ev)
    return embargo, upcoming


def credit_budget_ok(reserve=100):
    """False when the daily quota is nearly gone.
    New signals are optional; closing TP/SL is not. Once the day's usage gets
    within `reserve` credits of the plan limit, the engine stands down so
    signal-status.py can still resolve open setups.

    Fail CLOSED: a 429 on the check itself means the quota is gone, so the
    engine must stand down instead of burning the remaining requests and
    starving the TP/SL checker.
    """
    try:
        with urllib.request.urlopen(
                "https://api.twelvedata.com/api_usage?apikey=" + TD_KEY,
                timeout=20) as r:
            d = json.loads(r.read().decode())
        used = int(d.get("daily_usage", 0))
        limit = int(d.get("plan_daily_limit", 800))
        if used >= limit - reserve:
            log(f"SKIP credit guard: {used}/{limit} used, "
                f"reserving {reserve} for TP/SL checks")
            return False
        return True
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log("SKIP credit guard: 429 on usage check -> quota exhausted; standing down")
            return False
        log(f"WARN credit check failed (HTTP {e.code}); continuing")
        return True
    except Exception as e:
        log(f"WARN credit check failed ({type(e).__name__}); continuing")
        return True


def main():
    global TD_KEY
    dry = "--dry-run" in sys.argv
    if LOCK.exists():
        # Stale-lock guard: if a previous run was killed (reboot, OOM), the
        # lock file survives and would block the engine forever. A run takes
        # ~90s, so anything older than 10 minutes is stale.
        try:
            age = time.time() - LOCK.stat().st_mtime
        except OSError:
            age = 0
        if age > 600:
            log(f"WARN stale lock ({age:.0f}s) removed")
            LOCK.unlink(missing_ok=True)
        else:
            log("SKIP previous run still active")
            return 0
    LOCK.touch()
    try:
        if not MODEL_FILE.exists():
            log(f"ERROR model missing: {MODEL_FILE}")
            return 1
        payload = M.load_model(MODEL_FILE)
        models = payload.get("pairs") or {}
        if not models:
            log("ERROR model has no pairs")
            return 1

        state = load_status_state()
        if state is None:
            log("ERROR cannot read signal-status.json; fail closed")
            return 1

        if not in_session():
            log("SKIP outside session window")
            return 0

        TD_KEY = load_secrets("twelve.env").get("TWELVEDATA_API_KEY", "")
        if not TD_KEY:
            log("ERROR no TWELVEDATA_API_KEY")
            return 1

        # Kuota Twelve Data hanya relevan bila fallback TD digunakan, bukan
        # lagi penghalang utama: sumber utama kini Swissquote (tiada kuota).
        life = lifecycle_state()
        inserted = skipped = errors = 0
        for pair in PAIRS:
            if pair not in models:
                skipped += 1
                continue
            if gated_by_memo(pair):
                log(f"GATE {pair}: disekat learning-memo (prestasi lemah)")
                skipped += 1
                continue
            # Owner (5 Nov 2026): active position — pair sama ATAU pair lain —
            # tidak lagi menyekat signal baru. Guard pair_blocked dimatikan.
            # if pair_blocked(pair, state, life):
            #     log(f"SKIP {pair}: existing active setup")
            #     skipped += 1
            #     continue
            # No daily dedupe: the AI is the only producer now, so a pair may
            # post again as soon as its previous setup resolves. The pair
            # lifecycle guard above is what prevents duplicates.

            bars, err = None, ""
            try:
                bars = sq_bars(pair, TD_INTERVAL)
                if bars and len(bars) >= 60:
                    err = ""
                else:
                    bars, err = None, f"sq bars kurang: {len(bars or [])}"
            except Exception as sqx:
                bars, err = None, f"sq gagal: {sqx}"
            if not bars:
                # Sandaran Twelve Data (terhad kuota harian)
                if not credit_budget_ok():
                    errors += 1
                    continue
                payload_c = td_get(pair, TD_INTERVAL)
                bars, err = parse_candles(payload_c)
            if not bars:
                log(f"DATA {pair} {TIMEFRAME}: {err}")
                errors += 1
                time.sleep(CALL_GAP)
                continue

            model = dict(models[pair])
            model["_pair"] = pair
            side, conf = decide(model, bars)
            if side is None:
                # conf boleh tinggi tetapi tetap ditolak guard (trend-follow /
                # fade). Jangan tulis "< THRESHOLD" — itu mengelirukan.
                log(f"HOLD {pair} {TIMEFRAME}: tiada setup lulus guard (conf {conf:.3f})")
                time.sleep(CALL_GAP)
                continue

            try:
                embargo, upcoming = news_context(pair)
            except Exception as ex:
                errors += 1
                log(f"NEWS-FAIL {pair}: kalendar tidak tersedia ({type(ex).__name__}) - skip, bukan anggap tiada berita")
                time.sleep(CALL_GAP)
                continue
            if embargo:
                log(f"NEWS-BLOCK {pair}: {embargo['ccy']} {embargo['title']} @ {embargo['when']:%H:%M MYT} - dalam embargo, skip")
                skipped += 1
                time.sleep(CALL_GAP)
                continue
            news_boost = bool(upcoming)
            news_line = ""
            if news_boost:
                nxt = upcoming[0]
                log(f"NEWS-BOOST {pair}: {nxt['ccy']} {nxt['title']} @ {nxt['when']:%H:%M MYT} - pengesahan kuat")
                news_line = (f"\n\U0001f4f0 News: <b>{nxt['ccy']} {nxt['title']}</b> "
                             f"@{nxt['when']:%H:%M MYT} (pengesahan kuat)")

            if gated_by_memo(pair):
                log(f"GATE {pair} {TIMEFRAME} {side} conf={conf:.3f}: disekat memo (skip)")
                time.sleep(CALL_GAP)
                continue

            closes = [b[3] for b in bars]
            atr = M.atr_s(bars)[-1]
            entry = closes[-1]
            sl, tp = build_levels(pair, side, entry, atr)
            dp = DP.get(pair, DEFAULT_DP)
            # Mod private (default): AI publish TERUS ke akaun owner sahaja.
            # verified=True supaya MT5 + lifecycle + status tracker memproses,
            # TETAPI id didaftarkan private -> member tak nampak, lifecycle
            # hantar owner sahaja, MT5 execute dengan lot risiko 1%.
            # Untuk jatuh balik kepada mod cadangan (Post/Tolak), set
            # AI_PRIVATE=0.
            # PRIVATE_MODE: insert verified=False DULU (tiada siapa nampak,
            # MT5 tidak execute) -> daftar id ke private registry -> barulah
            # flip verified=True. Ini tutup race: sender/lifecycle/MT5 yang
            # membaca antara insert dan add() masih nampak verified=False.
            # Untuk jatuh balik kepada mod cadangan (Post/Tolak), set
            # AI_PRIVATE=0.
            row = {"pair": pair, "timeframe": TIMEFRAME, "side": side,
                   "entry": f"{entry:.{dp}f}", "sl": f"{sl:.{dp}f}",
                   "tp": f"{tp:.{dp}f}", "verified": False}
            # is_private ditetapkan dari awal supaya signal AI TIDAK PERNAH
            # muncul dalam RPC/RLS member walaupun verified=true selepas ini.
            if PRIVATE_MODE:
                row["is_private"] = True
            if dry:
                inserted += 1
                log(f"DRY {pair} {TIMEFRAME} {side} E={row['entry']} "
                    f"SL={row['sl']} TP={row['tp']} conf={conf:.3f} "
                    f"private={PRIVATE_MODE}")
                time.sleep(1)
                continue
            code, txt = sb("signals", "POST", row,
                           prefer="return=representation")
            if code in (200, 201):
                inserted += 1
                sid = None
                try:
                    sid = (json.loads(txt) or [{}])[0].get("id")
                except Exception:
                    pass
                if PRIVATE_MODE and sid is not None:
                    from engine.private_signals import add
                    add(sid)
                    # SIAP daftar private -> barulah buka kepada MT5/lifecycle.
                    # Verified false selama private registry belum siap.
                    code2, txt2 = sb(f"signals?id=eq.{int(sid)}", "PATCH",
                                     {"verified": True})
                    if code2 not in (200, 204):
                        log(f"AI #{sid} FAIL activate verified=true "
                            f"(code {code2}): kekal draft, semak owner")
                    else:
                        log(f"AI #{sid} {pair} {TIMEFRAME} {side} E={row['entry']} "
                            f"SL={row['sl']} TP={row['tp']} conf={conf:.3f} "
                            f"(PRIVATE owner sahaja + MT5 lot risiko)")
                        notify_owner(pair, side, row, conf,
                                     json.dumps([{"id": sid}]),
                                     news_line, executed=True)
                else:
                    log(f"DRAFT {pair} {TIMEFRAME} {side} E={row['entry']} "
                        f"SL={row['sl']} TP={row['tp']} conf={conf:.3f} "
                        f"(verified=false, menunggu owner)")
                    notify_owner(pair, side, row, conf, txt, news_line)
            else:
                errors += 1
                log(f"INSERT-FAIL {pair}: {code} {txt[:120]}")
            time.sleep(CALL_GAP)

        log(f"DONE inserted={inserted} skipped={skipped} errors={errors}")
        return 0
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL {type(e).__name__} {e}")
        try:
            os.remove(LOCK)
        except Exception:
            pass
        sys.exit(1)
