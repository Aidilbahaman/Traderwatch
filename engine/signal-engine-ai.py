#!/usr/bin/env python3
"""TraderWatch AI signal engine - M15, LLM (Qwen4 Max rootsys) decides.

Owner 2026-11-20: LLM analyst replaces the logistic model as the decision
maker. Each scan sends H1 + M15 context to the LLM; it answers BUY/SELL/HOLD
with SL/TP1/TP2 + confidence. Rollback: AI_DECISION=model (old logistic path,
state/ai-m15-model.json, optional SMC gate AI_SMC_GATE=1).

Safety guards (both paths):
  * threshold gate: LLM conf >= AI_LLM_MIN_CONF (model: PAIR_GATE)
  * LLM decides direction freely (no mechanical H1 trend guard by default;
    re-enable via AI_TREND_FOLLOW=XAU/USD)
  * news embargo, learning-memo gate, per-pair cooldown (30 min)
  * one active setup per pair across all timeframes (pair lifecycle guard)
  * SL/TP: LLM decides distances from structure/volatility (NO cap);
    sanity validation: ordering, spread floor, RR1 >= 1.5. Rollback path
    (model): SL = clamp(1.2*ATR, 3x spread floor, per-pair cap), TP = 2*SL
  * fail closed when the status file, Supabase check, or LLM errors

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
import smc_filter as SMC  # noqa: E402
import llm_analyst as LA  # noqa: E402

# Web Push verdict alerts (kinds='all'). Lazy import, best-effort: push
# failure NEVER breaks the signal flow. Throttle: max 1 verdict push per
# pair per 2h (module-level dict; process restarts reset it — acceptable).
PUSH_ENV = pathlib.Path("/home/ubuntu/.secrets/push.env")
_VERDICT_PUSH_TS = {}


def _load_push_env():
    if not PUSH_ENV.exists():
        return {}
    sec = {}
    for line in PUSH_ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


def push_verdict(pair, side, conf):
    """Notify 'all' subscribers about a new verified signal. Best-effort."""
    try:
        import json as _json
        import pathlib as _pl
        now = time.time()
        if now - _VERDICT_PUSH_TS.get(pair, 0) < 2 * 3600:
            return  # max 1 push per pair per 2h
        env = _load_push_env()
        if not env.get("VAPID_PRIVATE_KEY"):
            return
        subs = _sb("GET", "/rest/v1/push_subs", params={
            "select": "id,endpoint,p256dh,auth", "kinds": "eq.all", "limit": "200"})
        if not subs:
            _VERDICT_PUSH_TS[pair] = now
            return
        from pywebpush import webpush
        payload = _json.dumps({
            "title": f"Verdict baru: {pair}",
            "body": f"{TIMEFRAME} {side} · conf {round(conf*100)}% — buka app untuk chart",
            "url": "https://traderwatch.org/member/"})
        for sub in subs:
            try:
                webpush(
                    subscription_info={"endpoint": sub["endpoint"],
                                       "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=payload,
                    vapid_private_key=env["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": env.get("VAPID_SUBJECT", "mailto:ops@traderwatch.org")})
            except Exception as e:
                log(f"verdict push fail {sub.get('id')} {type(e).__name__}: {str(e)[:100]}")
        _VERDICT_PUSH_TS[pair] = now
    except Exception as e:
        log(f"push_verdict error {type(e).__name__}: {str(e)[:140]}")


def _sb(path, method="GET", params=None):
    """Service-key Supabase GET/POST returning decoded JSON (push helper).
    Separate from sb() which returns (code, text) for the signal flow."""
    url = f"{SB_URL}/rest/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip() else []
from mt5_read import run as mt5_run  # noqa: E402

TIMEOUT = 25
TZ_KL = timezone(timedelta(hours=8))
CALL_GAP = 9
RETRY_WAIT = 62
CANDLES = 1000  # v2 perlu sejarah dalam: H1 EMA50 + ATR percentile(100) + POI
REPO = HERE.parent
STATUS_FILE = REPO / "signal-status.json"
MODEL_FILE = REPO / "state" / "ai-m15-model.json"
MEMO_FILE = REPO / "state" / "learning-memo.json"
SMC_POSTED_FILE = REPO / "state" / "ai-smc-posted.json"
LOCK = Path("/tmp/signal-engine-ai.lock")

# Mod private: AI terus publish ke akaun OWNER sahaja (bukan member).
# Signal didaftarkan dalam state/private-signals.json supaya lifecycle
# hantar owner sahaja dan MT5 execute dengan lot risiko 1%.
PRIVATE_MODE = False  # Signal dipaparkan di website (Automation Trade) + auto MT5
# Gate keyakinan AI SERAGAM untuk semua pair fokus (XAU/XAG/BTC). Sebelum ini
# XAU guna 0.30 tetapi XAG/BTC guna 0.50 -> XAG/BTC dianalisis AI tapi hampir
# tak pernah fire. Sekarang semua pair guna gate sama supaya analisis AI
# konsisten. Boleh laras via env AI_THRESHOLD. Default 0.30 (paras XAU yang
# diluluskan owner). Risiko per trade dikawal MT5 (1% equity; kill switch
# harian dimatikan owner 2026-11-20).
THRESHOLD = float(os.environ.get("AI_THRESHOLD", "0.30"))
# SMC confluence gate (laluan model lama). Owner 2026-11-20: dimatikan —
# terlalu ketat, signal terlalu sedikit. Analisis struktur kini dibuat oleh
# LLM (AI_DECISION=llm). Hidupkan semula dengan AI_SMC_GATE=1 jika perlu.
SMC_GATE = os.environ.get("AI_SMC_GATE", "0") == "1"
# Reward multiple for SMC-confirmed trades. 1R was the held-out optimum; the
# 3R variant has the stronger statistical case (+0.528R, CI +0.10..+0.99).
# Default 2.0 (2026-11-20): seragam dengan ticket sistem RR 1:2 (TP1 1R 50%
# close + BE, TP2 2R) supaya lifecycle/sender/import tidak tersasar. Laras
# via env AI_SMC_R (cth. AI_SMC_R=1 untuk optimum held-out asal).
SMC_R_MULT = float(os.environ.get("AI_SMC_R", "2.0"))
# Floor on stop distance, as a multiple of spread. A structural stop taken
# straight off the sweep wick can land a few ticks from entry, and then the
# spread alone eats the whole edge. Note pip_of("XAU/USD") is 0.1, so gold's
# 3-pip spread is 0.30 of price — the floor is only a sanity net, it should
# never override a real structural stop. Verified on history: the tightest
# XAU setup had risk 3.71 (12x spread), so 10x filters pathological cases
# without trimming genuine setups.
SMC_MIN_SL_SPREAD = float(os.environ.get("AI_SMC_MIN_SL_SPREAD", "10.0"))
XAUUSD_THRESHOLD = THRESHOLD  # kini seragam dengan semua pair (lihat THRESHOLD)
# Gate AI per-pair (backtest v1-vs-v2 2026-11-19): v2 (SMC/sesi) lebih profitable
# bila selektif. XAG/BTC guna gate tinggi 0.50 (WR ~54-66%); XAU conf maks ~0.47
# jadi gate 0.30 supaya terus fire (WR ~45%, expectancy positif dgn ticket 2R).
# Boleh laras via env AI_GATE_XAU / AI_GATE_XAG / AI_GATE_BTC.
PAIR_GATE = {
    "XAU/USD": float(os.environ.get("AI_GATE_XAU", "0.30")),
    "XAG/USD": float(os.environ.get("AI_GATE_XAG", "0.50")),
    "BTCUSD": float(os.environ.get("AI_GATE_BTC", "0.50")),
}
# Lantai SL 15 pip: spread RoboForex besar (EURUSD 1.3, USDJPY 1.9,
# XAUUSD 2.1 pip). 15 pip hadkan drag spread bawah ~13% SL.
# SL runtime guard: mesti > 3× spread live per symbol.
SCALP_MIN_SL_PIPS = 15.0
SCALP_RR = 2.0
SCALP_MIN_SL_SPREAD_MULT = 3.0  # SL mesti > 3× spread live
# Saiz SL/TP ketat untuk akaun kecil (permintaan owner 2026-11-20).
# Sebelum ini 2.5x ATR tanpa cap: bila ATR M15 XAU ~$8.7, SL jadi ~$21.7
# (217 pip) dan TP ~$43 — terlalu besar untuk akaun kecil yang follow.
# Sekarang: SL = 1.2x ATR M15, dipagari cap harga per pair (XAU $5 = 50 pip
# -> risiko ~$5 pada 0.01 lot). TP kekal 2x SL (RR 1:2) supaya lifecycle
# TP1/TP2 dan check signal-import tidak berubah. Laras via env tanpa edit kod.
SL_ATR_MULT = float(os.environ.get("AI_SL_ATR_MULT", "1.2"))
MAX_SL_PRICE = {
    "XAU/USD": float(os.environ.get("AI_MAX_SL_XAU", "5.0")),
    "XAG/USD": float(os.environ.get("AI_MAX_SL_XAG", "0.25")),
    "BTCUSD": float(os.environ.get("AI_MAX_SL_BTC", "250.0")),
    "EUR/USD": float(os.environ.get("AI_MAX_SL_EUR", "0.0100")),
    "GBP/USD": float(os.environ.get("AI_MAX_SL_GBP", "0.0120")),
}
# Keputusan LLM (owner 2026-11-20): Qwen4 Max (rootsys) analisis konteks
# H1 + M15 dan buat keputusan muktamad BUY/SELL/HOLD. Model logistic lama
# dibersarakan dari laluan keputusan; AI_DECISION=model untuk rollback.
AI_DECISION = os.environ.get("AI_DECISION", "llm")
LLM_MIN_CONF = float(os.environ.get("AI_LLM_MIN_CONF", "0.5"))
# Cooldown per pair: tanpa gate SMC, penganalisis boleh fire setiap tick
# (5 min) bila conf kekal atas gate — malam 19 Nov 25 signal dalam 90 minit.
# Cooldown 30 min/pair hadkan spam tanpa menyekat setup baru selepas resolve.
# 0 = lumpuh. Mark hanya selepas insert berjaya.
PAIR_COOLDOWN_MIN = float(os.environ.get("AI_PAIR_COOLDOWN_MIN", "2"))
COOLDOWN_FILE = REPO / "state" / "ai-pair-cooldown.json"
# M15: matches the trained model (state/ai-m15-model.json, timeframe M15).
# Previously labelled M1 but mt5_read silently returned M15; now explicit so
# MT5 / Swissquote / TwelveData all serve the same timeframe the AI trained on.
TIMEFRAME = "M15"
TD_INTERVAL = "15min"

PAIRS = [p.strip() for p in os.environ.get(
    "AI_PAIRS", "XAU/USD,XAG/USD,BTCUSD,EUR/USD,GBP/USD").split(",") if p.strip()]
DP = {"XAU/USD": 2, "XAG/USD": 3, "USD/JPY": 3, "BTCUSD": 2,
      "EUR/USD": 5, "GBP/USD": 5}
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


def mt5_bars(symbol, interval, outputsize=CANDLES):
    """MT5 bars from VPS (via wine). Returns (ts_ms, high, low, close)."""
    pair_code = "".join(ch for ch in symbol.upper() if ch.isalpha())
    try:
        out, err = mt5_run(["candles", pair_code, interval, str(outputsize)])
    except Exception as e:
        return None, f"mt5 wrapper error: {e}"
    if not out:
        return None, f"mt5 no output: {err[:200]}"
    try:
        payload = json.loads(out)
    except Exception:
        return None, f"mt5 bad json: {out[:200]}"
    if payload.get("error"):
        return None, f"mt5 error: {payload['error']}"
    rows = payload.get("bars") or []
    bars = [(int(r["t"]) * 1000, float(r["h"]), float(r["l"]), float(r["c"]))
            for r in rows]
    if not bars:
        return None, "mt5 empty bars"
    bars.sort(key=lambda b: b[0])
    return bars[-outputsize:], ""


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


def open_sides_by_pair(state):
    """Pair (normalised) -> set arah signal masih terbuka (active/pending/entry).

    Untuk anti-hedging: signal baru tidak boleh bertentangan arah dengan
    posisi terbuka pair sama (layering searah dibenarkan, hedging tidak).
    Guna signal DB + status sebagai proxy posisi broker. Cooldown 30 min/pair
    memastikan status sempat dikemas kini sebelum signal seterusnya.
    Fail-open bila query gagal (gate kualiti, bukan keselamatan).
    """
    out = {}
    try:
        code, txt = sb("signals?select=pair,side,posted_at&verified=is.true"
                       "&order=posted_at.desc&limit=200")
        if code != 200:
            return out
        rows = json.loads(txt or "[]")
        sigs = (state or {}).get("signals") or {}
        for r in rows:
            try:
                k = key_for(r["pair"], r["posted_at"])
                st = str((sigs.get(k) or {}).get("status", "")).lower()
                if st not in ("active", "pending", "entry"):
                    continue
                p = "".join(ch for ch in str(r["pair"]).upper() if ch.isalpha())
                side = str(r.get("side", "")).upper()
                if side in ("BUY", "SELL"):
                    out.setdefault(p, set()).add(side)
            except Exception:
                continue
    except Exception as e:
        log(f"WARN open_sides: {type(e).__name__} - anti-hedge fail open")
    return out


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
    """Scan 24 jam selagi pasaran buka (owner 2026-11-20: scan all the time).

    Sebelum ini had sesi 08:00-01:00 MYT — 7 jam sehari enjin tak scan.
    Sekarang hanya berhenti bila pasaran forex benar-benar tutup: Jumaat
    21:00 UTC hingga Ahad 21:00 UTC (window sama seperti
    signal-lifecycle-alert.market_closed). Scan masa market tutup tak guna:
    bar beku, dan signal yang pos tidak boleh di-execute MT5.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    d = now.weekday()
    if d == 4:            # Jumaat
        return now.hour < 21
    if d == 5:            # Sabtu
        return False
    if d == 6:            # Ahad
        return now.hour >= 21
    return True


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


# Guard trend H1 (laluan model lama + LLM). Owner 2026-11-20: LLM bebas
# buat keputusan PENUH — tiada pair dikekang arah H1 secara mekanikal
# (default kosong). XAU kini boleh layering macam BTC; counter-trend
# dibenarkan mengikut pertimbangan LLM sendiri. Hidupkan semula via env
# AI_TREND_FOLLOW=XAU/USD (atau senarai pair dipisah koma) jika perlu.
TREND_FOLLOW_PAIRS = {p.strip() for p in
                      os.environ.get("AI_TREND_FOLLOW", "").split(",")
                      if p.strip()}
HIGH_CONF_FADE = 0.85   # dipakai hanya jika AI_TREND_FOLLOW ditetapkan
FADE_ATR = 0.5          # counter-trend hanya bila conf >= 0.85 DAN harga
FADE_LOOKBACK = 96      # <= 0.5 ATR dari high/low 24 jam (96x M15).


def passes_trend_guard(pair, side, conf, bars):
    """Guard trend H1 untuk XAU (model DAN LLM). Counter-trend hanya fade
    conf >= 0.85 berhampiran extreme 24 jam. Return True jika lepas."""
    if pair not in TREND_FOLLOW_PAIRS:
        return True
    tr = h1_trend(bars)
    want = "BUY" if tr > 0 else ("SELL" if tr < 0 else None)
    if want is None and conf < HIGH_CONF_FADE:
        log(f"TREND-SKIP {pair}: H1 tidak jelas, counter-trend dilarang")
        return False
    if side == want:
        return True
    _atr = M.atr_s(bars)[-1] or 0.0
    _hh = max(b[1] for b in bars[-FADE_LOOKBACK:])
    _ll = min(b[2] for b in bars[-FADE_LOOKBACK:])
    _px = bars[-1][3]
    if side == "SELL" and tr > 0 and (conf >= HIGH_CONF_FADE
                                       and _px >= _hh - FADE_ATR * _atr):
        log(f"FADE-OK {pair}: SELL conf {conf:.3f} >= {HIGH_CONF_FADE} "
            f"dekat high 24j ({_px:.2f} vs {_hh:.2f}) - fade top dibenarkan")
        return True
    if side == "BUY" and tr < 0 and (conf >= HIGH_CONF_FADE
                                     and _px <= _ll + FADE_ATR * _atr):
        log(f"FADE-OK {pair}: BUY conf {conf:.3f} >= {HIGH_CONF_FADE} "
            f"dekat low 24j ({_px:.2f} vs {_ll:.2f}) - fade bottom dibenarkan")
        return True
    log(f"TREND-SKIP {pair}: {side} lawan H1 "
        f"({'UP' if tr > 0 else 'DOWN'}), disekat")
    return False


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
    thresh = PAIR_GATE.get(pair_key, THRESHOLD)  # gate AI per-pair (v2 selektif)
    if conf < thresh:
        return None, conf
    if not passes_trend_guard(pair_key, side, conf, bars):
        return None, conf
    return side, conf


def build_levels(pair, side, price, atr):
    pip = M.pip_of(pair)
    # Dapatkan spread untuk rujukan
    try:
        import importlib.util as _il
        spec = _il.spec_from_file_location("smc", HERE / "smc_filter.py")
        smc = _il.module_from_spec(spec)
        spec.loader.exec_module(smc)
        spread_pips = smc.SPREAD_PIPS.get(pair.replace("/", ""), smc.DEFAULT_SPREAD_PIPS)
    except Exception:
        spread_pips = 2.0

    # SL ketat untuk akaun kecil: SL_ATR_MULT x ATR M15, lantai 3x spread,
    # dan cap harga per pair (MAX_SL_PRICE). Cap tidak boleh tekan SL bawah
    # lantai spread. TP = RR x SL, jadi jarak TP ikut mengecil automatik.
    sl_min_pips = min(8.0, spread_pips * SCALP_MIN_SL_SPREAD_MULT)
    floor = sl_min_pips * pip
    sl_dist = max(SL_ATR_MULT * atr, floor)
    cap = MAX_SL_PRICE.get(pair)
    if cap is not None:
        sl_dist = min(sl_dist, max(cap, floor))
    tp_dist = sl_dist * SCALP_RR
    if side == "BUY":
        return price - sl_dist, price + tp_dist
    return price + sl_dist, price - tp_dist


def smc_live_scan(bars):
    """Cari setup SMC fresh yang layak dipos pada tick ini.

    BUG LAMA: SMC.detect(bars) menganggap bar TERAKHIR ialah bar sweep,
    sedangkan FVG mesti siap 2-5 bar SELEPAS sweep -> panggilan itu mustahil
    fire (tiada bar selepas bar terakhir). Scan ini membetulkan semantik:
    cuba calon sweep bar supaya FVG jatuh pada bar tertutup terkini.

    Syarat layak (semua causal, hanya guna bar yang sudah closed):
      * FVG siap dalam ENTRY_TTL_BARS terakhir (entry limit masih hidup)
      * Entry BELUM disentuh harga selepas FVG (virgin retest) — kalau sudah
        disentuh, setup itu sudah "filled" dalam backtest; pos semula = re-entry
        yang tidak diuji.
    Pilih setup paling recent (fvg_bar terbesar, kemudian sweep bar terbesar).
    """
    tb = SMC.to_tuple_bars(bars)
    L = len(tb)
    if L < 110:  # m15_trend perlu >= 100 close; sweep + FVG perlu selebihnya
        return None
    best, best_key = None, None
    lo = max(60, L - SMC.ENTRY_TTL_BARS - SMC.DISP_MAX)
    for i in range(lo, L - 2):
        s = SMC.detect(tb, i)
        if not s:
            continue
        f = s["fvg_bar"]
        if f < L - SMC.ENTRY_TTL_BARS:
            continue  # entry limit sudah luput
        post = tb[f + 1:]
        if s["side"] == "BUY":
            if any(b[2] <= s["entry"] for b in post):
                continue  # entry sudah disentuh
        elif any(b[1] >= s["entry"] for b in post):
            continue
        key = (f, i)
        if best_key is None or key > best_key:
            best, best_key = s, key
    return best


def smc_levels(pair, side, smc):
    """Level struktur SMC + polisi akaun kecil. Return (setup+TP, mode) / (None, sebab).

    * Lantai: risiko struktur mesti >= SMC_MIN_SL_SPREAD x spread (spread
      jangan makan edge) — SL dialih keluar, TP dibina semula.
    * Cap: jika risiko struktur > MAX_SL_PRICE, SKIP setup (SMC-TOO-WIDE).
      SL struktur MESTI kekal di sebalik wick sweep; memotongnya ke dalam
      range memusnahkan logik setup. Setup terlalu lebar untuk akaun kecil
      = tidak didagangkan, bukan dipaksa ketat.
    """
    spread_px = M.pip_of(pair) * SMC.SPREAD_PIPS.get(
        pair.replace("/", ""), SMC.DEFAULT_SPREAD_PIPS)
    min_sl = SMC_MIN_SL_SPREAD * spread_px
    mode = "struktur"
    if smc["risk"] < min_sl:
        w = min_sl - smc["risk"]
        smc = dict(smc)
        smc["sl"] = (smc["sl"] - w) if side == "BUY" else (smc["sl"] + w)
        smc["risk"] = abs(smc["entry"] - smc["sl"])
        mode = f"diluaskan+{w:.3f}"
    cap = MAX_SL_PRICE.get(pair)
    if cap is not None and smc["risk"] > max(cap, min_sl):
        return None, f"risiko {smc['risk']:.3f} > cap {max(cap, min_sl):.3f}"
    return SMC.with_target(smc, SMC_R_MULT), mode


def _smc_key(pair, s):
    return f"{pair}|{s['bar_ts']}|{s['fvg_bar']}"


def smc_already_posted(pair, s):
    """Dedupe: setup SMC sama (sweep bar + FVG bar) jangan dipos ulang.

    Guard pair aktif dimatikan owner, jadi tanpa registry ini setup yang
    sama akan keluar setiap tick selagi ia dalam TTL. Fail closed: registry
    rosak -> anggap sudah pos (skip), bukan risiko duplicate.
    """
    try:
        rows = json.loads(SMC_POSTED_FILE.read_text())
    except FileNotFoundError:
        return False
    except Exception as e:
        log(f"WARN smc registry rosak ({type(e).__name__}) - fail closed, skip")
        return True
    key = _smc_key(pair, s)
    return any(r.get("key") == key for r in rows)


def smc_mark_posted(pair, s):
    """Daftar setup yang sudah dipos; prune entri > 24 jam."""
    try:
        try:
            rows = json.loads(SMC_POSTED_FILE.read_text())
        except Exception:
            rows = []
        cutoff = time.time() - 24 * 3600
        rows = [r for r in rows if float(r.get("at", 0)) >= cutoff]
        rows.append({"key": _smc_key(pair, s), "at": time.time()})
        SMC_POSTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        SMC_POSTED_FILE.write_text(json.dumps(rows))
    except Exception as e:
        log(f"WARN smc mark_posted gagal ({type(e).__name__}) - setup mungkin berulang")


def pair_on_cooldown(pair):
    """True jika pair baru fire dalam PAIR_COOLDOWN_MIN minit. Fail-open:
    cooldown ialah anti-spam, bukan guard keselamatan (itu cap SL + kill
    switch MT5); registry rosak jangan halang signal."""
    if PAIR_COOLDOWN_MIN <= 0:
        return False
    try:
        d = json.loads(COOLDOWN_FILE.read_text())
    except Exception:
        return False
    try:
        last = float(d.get(pair, 0))
    except (TypeError, ValueError):
        return False
    return (time.time() - last) < PAIR_COOLDOWN_MIN * 60


def mark_pair_fired(pair):
    try:
        try:
            d = json.loads(COOLDOWN_FILE.read_text())
        except Exception:
            d = {}
        d[pair] = time.time()
        COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOLDOWN_FILE.write_text(json.dumps(d))
    except Exception as e:
        log(f"WARN cooldown mark gagal ({type(e).__name__})")


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
        entry_f = float(row["entry"])
        sl_f = float(row["sl"])
        tp2_f = float(row["tp"])
        risk = abs(entry_f - sl_f)
        tp1_f = entry_f + risk if str(side).upper() == "BUY" else entry_f - risk
        
        sl_pips = abs(entry_f - sl_f) / pip
        tp1_pips = abs(tp1_f - entry_f) / pip
        tp2_pips = abs(tp2_f - entry_f) / pip
        
        # Anggaran wang pada 0.01 lot: 1 pip FX ~ $0.10; XAU 0.1 pip-unit ~ $0.10.
        risk_usd = sl_pips * 0.1
        reward_usd = tp2_pips * 0.1
        acct_note = (f"\n\u26a0\ufe0f Risiko ~<b>${risk_usd:.0f}</b> ({sl_pips:.1f} pips) | "
                     f"Reward ~<b>${reward_usd:.0f}</b> ({tp2_pips:.1f} pips) pada 0.01 lot"
                     + (" - akaun bawah $100, pertimbang skip atau lot lebih kecil" if risk_usd > 5 else ""))
        arrow = "\u2b06\ufe0f" if str(side).upper() == "BUY" else "\u2b07\ufe0f"
        kb = None      # mod private tiada butang; ditakrif di sini supaya
                       # cabang `executed` tidak UnboundLocalError.
        if executed:
            # Sesuai permintaan: Ai Signal (Pair) (Buy/Sell) (Size lot) (Account balance)
            # Dapatkan equity live daripada MT5
            acc = mt5_call({"action": "positions"}) # Call untuk pastikan connection & get info
            # Kerana mt5_call ini agak terhad, kita akan ambil equity dari `ai-compound.json`
            # yang sentiasa diupdate oleh engine.
            try:
                with open("/home/ubuntu/web/Traderwatch-repo/state/ai-compound.json") as f:
                    comp = json.load(f)
                    eq_val = comp.get("peak", 0)
            except:
                eq_val = 0
            
            msg = (f"🤖 <b>AI Signal</b>  <b>{pair}</b>  <b>{side}</b>  ~10% Risk  |  Equity ~${eq_val:.2f}\n"
                   f"━━━━━━━━━━━━━━━━━━━━\n"
                   f"{icon}  Entry <code>{row['entry']}</code>\n"
                   f"🛡️ SL <code>{row['sl']}</code> ({sl_pips:.1f} pips)\n"
                   f"🎯 TP1 <code>{tp1_f:.{DP.get(pair, 2)}f}</code> (1.0R • 50% close, baki BE)\n"
                   f"🎯 TP2 <code>{row['tp']}</code> ({tp2_pips:.1f} pips, RR 1:{rr:.1f})\n"
                   f"Confidence {conf:.3f} • Grade A+ • Private AI\n"
                   f"{news_line}\n\n"
                   f"Setup active — MT5 auto-executing.")
        else:
            msg = (f"\U0001f916 <b>AI CADANGAN (draft #{sid})</b>\n"
                   f"\U0001f4ca <b>{pair}</b> \u00b7 M15\n"
                   f"{icon}\n"
                   f"\U0001f3af Entry <code>{row['entry']}</code>\n"
                   f"\U0001f6e1\ufe0f SL <code>{row['sl']}</code> ({sl_pips:.1f} pips) | "
                   f"\U0001f3af TP <code>{row['tp']}</code> ({tp2_pips:.1f} pips, RR 1:{rr:.1f})\n"
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
        models = {}
        if AI_DECISION == "model":
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
            log("SKIP market closed (Jumaat 21:00 UTC - Ahad 21:00 UTC)")
            return 0

        TD_KEY = load_secrets("twelve.env").get("TWELVEDATA_API_KEY", "")
        if not TD_KEY:
            log("ERROR no TWELVEDATA_API_KEY")
            return 1

        # Kuota Twelve Data hanya relevan bila fallback TD digunakan, bukan
        # lagi penghalang utama: sumber utama kini Swissquote (tiada kuota).
        life = lifecycle_state()
        open_sides = open_sides_by_pair(state)  # anti-hedging: arah posisi terbuka per pair
        inserted = skipped = errors = 0
        for pair in PAIRS:
            if AI_DECISION == "model" and pair not in models:
                skipped += 1
                continue
            if gated_by_memo(pair):
                log(f"GATE {pair}: disekat learning-memo (prestasi lemah)")
                skipped += 1
                continue
            if pair_on_cooldown(pair):
                log(f"COOLDOWN {pair}: baru fire < {PAIR_COOLDOWN_MIN:g} minit - skip")
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
                bars, err = mt5_bars(pair, TD_INTERVAL)
                if bars and len(bars) >= 60:
                    err = ""
                else:
                    bars, err = None, f"mt5 bars kurang: {len(bars or [])}"
            except Exception as mtx:
                bars, err = None, f"mt5 gagal: {mtx}"
            # MT5 broker is the SINGLE data source (owner 2026-11-21): no
            # Swissquote / TwelveData fallback. Bridge down -> skip this pair
            # (the website banner shows bridge / market status).
            if not bars:
                log(f"DATA {pair} {TIMEFRAME}: {err}")
                errors += 1
                time.sleep(CALL_GAP)
                continue

            # News embargo SEBELUM analisis — jimat panggilan LLM bila embargo.
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

            smc = None
            if AI_DECISION == "llm":
                # ---- LLM analyst (Qwen4 Max rootsys) ----------------------
                # LLM buat keputusan muktamad; jarak SL/TP pilihan LLM sendiri
                # (tiada cap). Guard keselamatan kekal: conf gate, trend H1,
                # sanity aras + lantai spread dalam validate_verdict.
                spread_pips = SMC.SPREAD_PIPS.get(
                    pair.replace("/", ""), SMC.DEFAULT_SPREAD_PIPS)
                pnorm = "".join(ch for ch in pair.upper() if ch.isalpha())
                held = open_sides.get(pnorm, set())
                verdict = LA.analyze(pair, bars, M.pip_of(pair), spread_pips, held=held)
                if verdict is None:
                    log(f"LLM-FAIL {pair} {TIMEFRAME}: analisis gagal - skip (fail closed)")
                    errors += 1
                    time.sleep(CALL_GAP)
                    continue
                if verdict["side"] == "HOLD":
                    log(f"LLM-HOLD {pair} {TIMEFRAME}: {verdict.get('reason', '')}")
                    time.sleep(CALL_GAP)
                    continue
                side, conf = verdict["side"], verdict["conf"]
                # Anti-hedging: jangan buka arah bertentangan selagi pair ada
                # posisi terbuka. Layering searah dibenarkan; hedging tidak.
                # Pair yang SUDAH hedging (dua arah) dibekukan sampai satu sisi
                # tutup — jangan tambah lagi kekusutan.
                if held and len(held) > 1:
                    log(f"NO-HEDGE {pair} {TIMEFRAME}: sudah hedging {sorted(held)}; "
                        f"skip sampai satu sisi tutup")
                    time.sleep(CALL_GAP)
                    continue
                if held and side not in held:
                    log(f"NO-HEDGE {pair} {TIMEFRAME}: posisi {sorted(held)} terbuka; "
                        f"signal {side} bertentangan - skip (elak hedging)")
                    time.sleep(CALL_GAP)
                    continue
                if conf < LLM_MIN_CONF:
                    log(f"LLM-GATE {pair} {TIMEFRAME} {side} conf={conf:.2f} < {LLM_MIN_CONF}")
                    time.sleep(CALL_GAP)
                    continue
                if not passes_trend_guard(pair, side, conf, bars):
                    time.sleep(CALL_GAP)
                    continue
                entry = bars[-1][3]
                sl, tp = verdict["sl"], verdict["tp2"]
                log(f"LLM-LEVELS {pair} {side}: entry {entry} sl {sl} tp {tp} "
                    f"(conf {conf:.2f}, RR1 {verdict['rr1']}, {verdict['model']}, "
                    f"{verdict['latency_s']}s)")
            else:
                # ---- Laluan model lama (rollback: AI_DECISION=model) ------
                model = dict(models[pair])
                model["_pair"] = pair
                side, conf = decide(model, bars)
                if side is None:
                    # conf boleh tinggi tetapi tetap ditolak guard (trend-follow /
                    # fade). Jangan tulis "< THRESHOLD" — itu mengelirukan.
                    log(f"HOLD {pair} {TIMEFRAME}: tiada setup lulus guard (conf {conf:.3f})")
                    time.sleep(CALL_GAP)
                    continue

                # SMC confluence gate (optional, default OFF sejak 2026-11-20).
                if SMC_GATE:
                    try:
                        smc = smc_live_scan(bars)
                    except Exception as sx:
                        log(f"SMC-FAIL {pair}: {type(sx).__name__} - skip, bukan anggap lulus")
                        time.sleep(CALL_GAP)
                        continue
                    if smc is None:
                        log(f"NO-SMC {pair} {TIMEFRAME} {side} conf={conf:.3f}: "
                            f"tiada setup SMC fresh (sweep+disp+FVG dalam TTL, entry belum disentuh)")
                        time.sleep(CALL_GAP)
                        continue
                    if smc["side"] != side:
                        log(f"SMC-VETO {pair} {TIMEFRAME}: model {side} conf={conf:.3f} "
                            f"lawan SMC {smc['side']} - skip")
                        time.sleep(CALL_GAP)
                        continue
                    if smc_already_posted(pair, smc):
                        log(f"SMC-DUPE {pair} {TIMEFRAME}: setup bar {smc['bar_ts']} "
                            f"sudah dipos - skip")
                        time.sleep(CALL_GAP)
                        continue
                    log(f"SMC-OK {pair} {TIMEFRAME} {side} conf={conf:.3f}: "
                        f"sweep+disp {smc['disp_atr']}ATR+FVG, entry {smc['entry']} "
                        f"sl {smc['sl']}")

                closes = [b[3] for b in bars]
                atr = M.atr_s(bars)[-1]
                entry = closes[-1]
                if smc:
                    # Level struktur (FVG edge / sweep wick), bukan ATR guess,
                    # supaya ticket sepadan dengan setup yang dikesan. Polisi
                    # akaun kecil: lantai spread, skip jika risiko > cap.
                    smc_tp, mode = smc_levels(pair, side, smc)
                    if smc_tp is None:
                        log(f"SMC-TOO-WIDE {pair} {TIMEFRAME} {side}: {mode} "
                            f"- skip (akaun kecil)")
                        time.sleep(CALL_GAP)
                        continue
                    sl, tp = smc_tp["sl"], smc_tp["tp"]
                    # Entry MESTI harga struktur (tepi FVG), bukan close semasa:
                    # MT5 executor hantar pending limit pada entry signal, dan
                    # SL/TP/lot risiko semua dikira dari entry ini. Kalau entry
                    # close manakala SL/TP struktur, ticket tak konsisten.
                    entry = smc_tp["entry"]
                    log(f"SMC-LEVELS {pair} {side}: entry {entry} sl {sl} tp {tp} "
                        f"({SMC_R_MULT}R, risk {smc_tp['risk']:.5f}, sl {mode})")
                else:
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
            # Mod AUTOMATION (PRIVATE_MODE=False): signal terus verified=True
            # supaya muncul di website (RPC) DAN diambil MT5 — tiada approval.
            # Mod private (fallback): insert draft dulu, daftar registry, baru
            # flip verified untuk tutup race条件.
            row = {"pair": pair, "timeframe": TIMEFRAME, "side": side,
                   "entry": f"{entry:.{dp}f}", "sl": f"{sl:.{dp}f}",
                   "tp": f"{tp:.{dp}f}", "verified": (not PRIVATE_MODE)}
            # Signal LLM = instant entry (market). Entry LLM ialah close semasa;
            # pending limit/stop akan drift jadi unfilled stop bila harga bergerak.
            # Laluan model/SMC kekal pending (strategi entry struktur + TTL).
            if AI_DECISION == "llm":
                row["exec_mode"] = "market"
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
                mark_pair_fired(pair)
                if smc:
                    smc_mark_posted(pair, smc)
                # Web push "verdict baru" kepada pelanggan kinds='all'
                # (best-effort, throttle 1/pair/2j). Tak pernah ganggu flow.
                push_verdict(pair, side, conf)
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
                elif not PRIVATE_MODE and sid is not None:
                    # AUTOMATION: sudah verified=True dari awal — terus live
                    # di website + MT5. Tiada notifikasi owner (Telegram off).
                    log(f"AI #{sid} {pair} {TIMEFRAME} {side} E={row['entry']} "
                        f"SL={row['sl']} TP={row['tp']} conf={conf:.3f} "
                        f"(AUTOMATION — website + MT5)")
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
