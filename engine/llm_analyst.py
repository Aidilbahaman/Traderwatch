#!/usr/bin/env python3
"""LLM analyst untuk enjin signal AI — Qwen4 Max (rootsys) buat keputusan.

Owner 2026-11-20: LLM sahaja sebagai penganalisis (ganti model logistic +
gate SMC yang terlalu ketat). Setiap scan, hantar konteks H1 + M15 kepada
LLM; ia jawab BUY/SELL/HOLD + SL/TP1/TP2 + confidence + sebab ringkas.

Reka bentuk (belajar dari kegagalan bot_v2):
  * Prompt RINGKAS (<6k char). Prompt panjang membuat thinking model bakar
    token pada reasoning dan content kosong.
  * max_tokens 1500 + temperature 0.2; parser extract JSON dari mana-mana
    bahagian content (GLM tulis prose dahulu sebelum JSON).
  * Chain model: qwen4-max (rootsys) utama -> sandaran serveras percuma.
    Kegagalan HTTP/parse -> cuba model seterusnya. Penolakan validasi
    (aras tak sah / SL terlalu lebar) = muktamad, TIDAK "shop" model lain.
  * Fail-closed: semua model gagal -> None (enjin skip pair, bukan pos).
  * Audit: setiap panggilan direkod ke state/llm-analysis-log.jsonl.

Validasi sanity (bukan sekatan strategi — owner 2026-11-20: jarak SL/TP
sepenuhnya keputusan LLM, TIADA cap): susunan aras, risk > 0, lantai
3x spread (mekanikal — spread jangan makan stop), RR1 >= 1.5 (konvensyen
ticket TP1/TP2 sistem).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_model as M  # noqa: E402
import vision_chart as VC  # noqa: E402  (render PNG untuk model vision)
try:
    import ict_filter as ICT  # noqa: E402  (BOS/CHoCH/FVG metadata untuk vision)
except Exception:
    ICT = None
try:
    import ai_learn  # noqa: E402  (closed-loop: corak TP/SL sebenar client)
except Exception:
    ai_learn = None
try:
    import market_context as MC  # noqa: E402  (sesi, berita, konteks sebenar)
except Exception:
    MC = None

REPO = HERE.parent
AUDIT_FILE = REPO / "state" / "llm-analysis-log.jsonl"
ROOTSYS_KEY_FILE = Path.home() / ".config/opencode/secrets/rootsys-key"
ROOTSYS_QWEN_KEY_FILE = Path.home() / ".config/opencode/secrets/rootsys-qwen-key"
TW_BOT_ENV = Path("/home/ubuntu/tw-bot/.env")

VISION_MODEL = os.environ.get("AI_LLM_VISION_MODEL", "deepseek-v4.1-flash")
VISION_ENABLED = os.environ.get("AI_LLM_VISION", "1") == "1"
PRIMARY_MODEL = os.environ.get("AI_LLM_MODEL", "qwen4-max")
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "AI_LLM_FALLBACKS",
    "asai/freemodel-1-GLM,asai/freemodel-2-MiniMax,asai/deepseek-v4-flash"
).split(",") if m.strip()]
CALL_TIMEOUT_S = float(os.environ.get("AI_LLM_CALL_TIMEOUT", "60"))
# Had atas RR1: backtest mekanikal 780 trade (BTC/XAU/EUR, 33 hari) tunjuk
# expectancy jatuh negatif bila TP > 1.5R. Hadkan supaya TP realistik.
RR1_MAX = float(os.environ.get("AI_RR1_MAX", "1.6"))
BUDGET_S = float(os.environ.get("AI_LLM_BUDGET_S", "120"))

# Timeframe-aware trading styles. Lower TF = scalping (tight SL, quick targets,
# opportunistic); higher TF = swing/position (wide SL, big targets, selective).
# ctx_factor = how many base bars make one context (higher-TF) bar.
TF_PROFILES = {
    "M5": dict(ctx_factor=3, ctx_name="M15", min_bars=80, ctx_show=24, base_show=60,
               rr1_min=1.0, role="SCALPER",
               approach=("You are SCALPING the M5 chart. Take quick, high-probability momentum setups "
                         "aligned with the M15 trend. Stops are TIGHT (just beyond the nearest micro "
                         "swing / liquidity sweep, ~0.6-1.0x M5 ATR). Targets are QUICK: TP1 at the nearest "
                         "liquidity pool (~1-1.5R), TP2 a little further (~2-2.5R). Be opportunistic — scalps "
                         "are frequent; a clean micro sweep + displacement is enough, you do NOT need a perfect "
                         "higher-TF setup. Still avoid dead chop and news spikes.")),
    "M15": dict(ctx_factor=4, ctx_name="H1", min_bars=100, ctx_show=24, base_show=48,
                rr1_min=1.0, role="INTRADAY TREND",
                approach=("Be selective and patient: only trade a CLEAR, confirmed setup aligned with the "
                          "H1 trend. Do NOT chase price extended deep into discount/premium — wait for a "
                          "pullback to an unmitigated FVG/order-block. In choppy/rangebound markets or without "
                          "a clean edge, choose HOLD. Quality over quantity.")),
    "H1": dict(ctx_factor=4, ctx_name="H4", min_bars=60, ctx_show=24, base_show=48,
               rr1_min=1.2, role="SWING TREND",
               approach=("You are SWING trading the H1 chart. Only take clear structural setups aligned with "
                         "the H4 trend. Stops sit beyond the invalidating H1 swing (wider, ~1-1.5x ATR). "
                         "Targets are larger: TP1 ~2R at a meaningful liquidity level, TP2 ~3R+. Be selective "
                         "— a few high-quality swings, not noise. HOLD if structure is unclear.")),
    "H4": dict(ctx_factor=6, ctx_name="D1", min_bars=40, ctx_show=20, base_show=40,
               rr1_min=1.5, role="POSITION TREND",
               approach=("You are POSITION trading the H4 chart. Trade only major structural setups aligned "
                         "with the Daily trend. Wide stops beyond the invalidating H4 swing. Targets are "
                         "ambitious: TP1 ~2.5-3R, TP2 ~4R+ at major liquidity. Very selective — patience; "
                         "HOLD unless the edge is strong and clean.")),
    "D1": dict(ctx_factor=5, ctx_name="W1", min_bars=20, ctx_show=12, base_show=30,
               rr1_min=2.0, role="POSITION TREND",
               approach=("You are POSITION trading the Daily chart. Trade only major macro structural setups "
                         "aligned with the Weekly trend. Very wide stops beyond the invalidating Daily swing. "
                         "Targets: TP1 ~3R, TP2 ~5R+ at major weekly liquidity. Extremely selective — HOLD "
                         "unless a rare, high-conviction setup is present.")),
}


def tf_profile(tf):
    return TF_PROFILES.get(str(tf).upper(), TF_PROFILES["M15"])


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} LLM {msg}", flush=True)


def _read_env_file(path):
    vals = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


ROOTSYS_GATEWAY_MODELS = {
    "glm-5.2", "glm-5.3-flash", "glm-5.3-flash-mod", "glm-5.3-flash-beta",
    "glm-5.3-beta", "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4.1-flash",
    "deepseek-v4-pro-mod", "deepseek-v4.1-flash-mod", "step-5-preview",
    "space-bunny", "mimo-v2.6-pro", "minimax-m3.1-flash", "hy4std",
    "hy4flash-free", "glm-5.3-flashx",
}


def _route(model):
    """(url, key) untuk model. Dibaca setiap panggilan supaya perubahan
    .env berkuat kuasa tanpa restart."""
    bare = model.split("/", 1)[-1]
    if bare == "qwen4-max":
        try:
            key = ROOTSYS_QWEN_KEY_FILE.read_text().strip()
        except OSError:
            key = ""
        return "https://rootsys.cloud/v1/chat/completions", key
    if (model == PRIMARY_MODEL or model.startswith("rootsys/")
            or bare in ROOTSYS_GATEWAY_MODELS):
        key = os.environ.get("ROOTSYS_API_KEY", "")
        if not key:
            try:
                key = ROOTSYS_KEY_FILE.read_text().strip()
            except OSError:
                key = ""
        return "https://rootsys.cloud/v1/chat/completions", key
    # Sandaran: serveras (key bot Telegram)
    env = _read_env_file(TW_BOT_ENV)
    key = os.environ.get("HERMES_CUSTOM_SERVERAS_CLICK_API_KEY", "") or \
        env.get("HERMES_CUSTOM_SERVERAS_CLICK_API_KEY", "")
    return env.get("LLM_URL", "https://serveras.click/v1/chat/completions"), key


def with_opens(bars):
    """(ts,h,l,c) -> (ts,o,h,l,c); open = close bar sebelumnya (anggaran)."""
    out = []
    prev = bars[0][3] if bars else 0.0
    for ts, h, l, c in bars:
        out.append((ts, prev, h, l, c))
        prev = c
    return out


def resample(bars, factor):
    """(ts,h,l,c) base bars -> higher-TF (ts,o,h,l,c), `factor` bars per group."""
    ohlc = with_opens(bars)
    out = []
    for i in range(0, len(ohlc) - factor + 1, factor):
        g = ohlc[i:i + factor]
        out.append((g[0][0], g[0][1], max(b[2] for b in g),
                    min(b[3] for b in g), g[-1][4]))
    return out


def resample_h1(bars):
    """M15 (ts,h,l,c) -> H1 (ts,o,h,l,c), 4 bar segrup. (compat alias)"""
    return resample(bars, 4)


def _fmt_rows(rows):
    return "\n".join(f"{o:g} {h:g} {l:g} {c:g}" for _, o, h, l, c in rows)


def build_prompt(pair, price, ctx, base, atr, trend, hh, ll, spread_pips, tf="M15", held=None):
    prof = tf_profile(tf)
    held_line = ""
    if held:
        if len(held) > 1:
            held_line = ("Both BUY and SELL already open on this pair; prefer HOLD "
                         "(do not add more hedging).\n")
        else:
            hs = next(iter(held))
            opp = "BUY" if hs == "SELL" else "SELL"
            held_line = (f"You already hold a {hs} position on this pair. Do NOT issue "
                         f"{opp} (no hedging). Only add {hs} or HOLD.\n")
    return f"""FX {prof['role']} analyst. Pair {pair} now {price}. Trading timeframe {tf}.
Context: {prof['ctx_name']} trend {trend}, {tf} ATR {atr:.3f}, recent high {hh:g} low {ll:g}, spread {spread_pips:g} pips.
{prof['ctx_name']} O H L C (oldest->newest):
{_fmt_rows(ctx)}
{tf} O H L C (oldest->newest):
{_fmt_rows(base)}
Analyze structure: trend, liquidity sweeps, displacement/FVG, premium/discount.
{prof['approach']}
{held_line}Reply ONLY one compact JSON object, no prose, no markdown:
{{"bias":"BUY"|"SELL"|"HOLD","sl":num,"tp1":num,"tp2":num,"confidence":0-10,"reason":"<max 12 words>"}}
Rules: entry=current price. BUY: sl<entry<tp1<tp2. SELL: sl>entry>tp1>tp2.
You decide SL/TP distances from structure and volatility (SL beyond the
invalidating swing/wick, TP at logical liquidity targets). No fixed cap.
tp1 distance >= {prof['rr1_min']}x SL distance; tp2 further at the next target.
SL must be more than 3x spread ({3 * spread_pips:g} pips) from entry.
No clean setup = bias HOLD. Confidence honest, not inflated."""


def parse_response(content):
    """Extract objek JSON pertama dari content (abaikan prose/fences)."""
    if not content:
        raise ValueError("content kosong")
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    for m in re.finditer(r"\{[^{}]*\}", text, re.S):
        try:
            j = json.loads(m.group(0))
            if isinstance(j, dict):
                return j
        except json.JSONDecodeError:
            continue
    raise ValueError("tiada JSON valid dalam response")


# Sesi lemah ikut backtest 780 trade: XAU London/NY negatif, EUR Asia negatif.
# Format: pair -> set jam-UTC yang DIDENDA (penalti conf, bukan sekatan keras).
WEAK_SESSIONS = {
    "XAU": {7, 8, 9, 10, 11, 12, 13, 14, 15, 16},   # London+NY: -0.16R / -0.12R
    "EUR": {0, 1, 2, 3, 4, 5, 6},                     # Asia: -0.01R (marginal)
    "GBP": {0, 1, 2, 3, 4, 5, 6},
}


def session_penalty(pair, hour_utc):
    """Pendarab confidence ikut sesi lemah (bukti backtest). 1.0 = tiada denda."""
    pref = str(pair).upper()[:3]
    return 0.88 if hour_utc in WEAK_SESSIONS.get(pref, ()) else 1.0


def validate_verdict(j, price, pip, spread_pips, rr1_min=1.5, pair_hint=""):
    """Semak sanity jawapan LLM; pulangkan verdict bersih atau raise ValueError.

    Jarak SL/TP = keputusan LLM (tiada cap). Semakan di sini mekanikal:
    susunan aras, risk positif, lantai spread, RR1 >= 1.5 (konvensyen ticket).
    """
    bias = str(j.get("bias", "")).strip().upper()
    reason = str(j.get("reason", ""))[:200]
    try:
        conf = min(1.0, max(0.0, float(j.get("confidence", 5)) / 10.0))
    except (TypeError, ValueError):
        conf = 0.5
    if bias == "HOLD":
        return {"side": "HOLD", "conf": conf, "reason": reason}
    if bias not in ("BUY", "SELL"):
        raise ValueError(f"bias tidak sah: {bias!r}")
    try:
        sl, tp1, tp2 = float(j["sl"]), float(j["tp1"]), float(j["tp2"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("medan sl/tp1/tp2 tiada atau bukan nombor")
    if bias == "BUY":
        ok = sl < price < tp1 < tp2
    else:
        ok = sl > price > tp1 > tp2
    if not ok:
        raise ValueError("susunan aras tidak konsisten dengan arah")
    risk = abs(price - sl)
    floor = 3.0 * spread_pips * pip
    if risk <= 0 or risk < floor:
        raise ValueError(f"SL {risk:.5f} bawah lantai spread {floor:.5f}")
    rr1 = abs(tp1 - price) / risk
    rr2 = abs(tp2 - price) / risk
    if rr1 < rr1_min:
        raise ValueError(f"RR1 {rr1:.2f} below {rr1_min}")
    # Had atas: backtest 780 trade -> RR>1.5 expectancy negatif pada M5/H1.
    if rr1 > RR1_MAX:
        raise ValueError(f"RR1 {rr1:.2f} above cap {RR1_MAX} (TP too far — unrealistic)")
    sp = session_penalty(pair_hint, datetime.now(timezone.utc).hour)
    return {"side": bias, "entry": round(price, 5), "sl": round(sl, 5),
            "tp1": round(tp1, 5), "tp2": round(tp2, 5),
            "conf": round(min(0.95, conf * sp), 2), "reason": reason,
            "rr1": round(rr1, 2), "rr2": round(rr2, 2)}


def _audit(record):
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > 5_000_000:
            lines = AUDIT_FILE.read_text().splitlines()[-2000:]
            AUDIT_FILE.write_text("\n".join(lines) + "\n")
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"WARN audit gagal: {type(e).__name__}")


def _call_model(model, prompt, timeout):
    url, key = _route(model)
    if not key:
        raise RuntimeError(f"tiada API key untuk {model}")
    # max_tokens 4000: thinking model (qwen4-max) bakar ~800-2000 token pada
    # reasoning sebelum JSON. 1500 menyebabkan content kosong / JSON terpotong
    # (dilihat live 2026-11-19: XAU parse gagal, XAG content kosong).
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 4000, "temperature": 0.2}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode())
    choice = (j.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content") or ""


def _call_vision(model, prompt, bars, pair, tf, timeout):
    """Vision model: hantar prompt + screenshot chart (bar <= masa semasa)."""
    url, key = _route(model)
    if not key:
        raise RuntimeError(f"tiada API key untuk vision {model}")
    b64 = VC.render(bars, pair=pair, tf=tf)
    if not b64:
        raise RuntimeError("vision chart render gagal")
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": [
                           {"type": "text", "text": prompt},
                           {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}],
                       "max_tokens": 700}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode())
    choice = (j.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content") or ""


def alignment(pair, tf_bars, timeout=60):
    """Multi-TF alignment: satu imej gabungan (M5/H1/H4), satu panggilan vision.
    tf_bars = {tf: bars}. Return {tfs:{tf:bias}, aligned, note} atau None."""
    panels = [(tf, tf_bars[tf]) for tf in ("M5", "H1", "H4") if tf_bars.get(tf)]
    if not panels:
        return None
    url, key = _route(VISION_MODEL)
    if not key:
        return None
    b64 = VC.render_multi(panels, pair=pair)
    if not b64:
        return None
    tfs = [tf for tf, _ in panels]
    prompt = ("You see " + str(len(panels)) + " stacked candlestick charts of " + pair +
              " labelled " + ", ".join(tfs) + " (top to bottom). For EACH timeframe give the "
              "short-term structural bias from its candles: BUY, SELL or HOLD. "
              'Reply ONLY compact JSON: {"tfs":{"' + '":"BUY|SELL|HOLD","'.join(tfs) +
              '":"BUY|SELL|HOLD"},"note":"<8 words on alignment>"}')
    body = json.dumps({"model": VISION_MODEL,
                       "messages": [{"role": "user", "content": [
                           {"type": "text", "text": prompt},
                           {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}],
                       "max_tokens": 300}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode())
        content = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        m = json.loads(content[content.find("{"):content.rfind("}") + 1])
        t = {k: str(v).upper() for k, v in (m.get("tfs") or {}).items() if str(v).upper() in ("BUY", "SELL", "HOLD")}
        if not t:
            return None
        dirs = [v for v in t.values() if v in ("BUY", "SELL")]
        aligned = len(dirs) >= 2 and len(set(dirs)) == 1
        return {"tfs": t, "aligned": aligned, "note": str(m.get("note") or "")[:80]}
    except Exception as e:
        log(f"{pair} alignment gagal ({type(e).__name__}: {str(e)[:80]})")
        return None


def analyze(pair, bars, pip, spread_pips, call=None, budget_s=None, held=None, tf="M15"):
    """Analisis LLM untuk satu pair mengikut timeframe. Return verdict dict / None.

    TF-aware: M5=scalping (longgar, target cepat), M15=intraday, H1=swing,
    H4/D1=position (ketat struktur, target besar). tf default M15 = kelakuan
    enjin berjadual sedia ada (backward compatible).
    """
    explicit_call = call is not None
    call = call or _call_model
    budget_s = budget_s or BUDGET_S
    prof = tf_profile(tf)
    tf = str(tf).upper() if str(tf).upper() in TF_PROFILES else "M15"
    if not bars or len(bars) < prof["min_bars"]:
        log(f"{pair} {tf}: bar tidak cukup ({len(bars or [])} < {prof['min_bars']})")
        return None
    price = bars[-1][3]
    atr = M.atr_s(bars)[-1]
    # Data FLAT (market tutup / collector mati) -> tolak, jangan biar AI reka.
    _uniq = len({(round(b[1], 6), round(b[2], 6)) for b in bars[-60:]})
    if _uniq < 5:
        log(f"{pair} {tf}: tolak — data flat ({_uniq} harga unik /60 bar)")
        return {"side": "HOLD", "conf": 0.0,
                "reason": "Market data unavailable — no price movement "
                          "(market closed or feed stalled).", "stale_data": True}
    ctx = resample(bars, prof["ctx_factor"])
    closes_ctx = [b[4] for b in ctx]
    trend = "FLAT"
    if len(closes_ctx) >= 50:
        e20, e50 = M.ema(closes_ctx, 20), M.ema(closes_ctx, 50)
        trend = "UP" if e20[-1] > e50[-1] else ("DOWN" if e20[-1] < e50[-1] else "FLAT")
    win = bars[-96:]
    hh, ll = max(b[1] for b in win), min(b[2] for b in win)
    prompt = build_prompt(pair, price, ctx[-prof["ctx_show"]:], with_opens(bars)[-prof["base_show"]:],
                          atr, trend, hh, ll, spread_pips, tf=tf, held=held)
    if VISION_ENABLED and not explicit_call:
        # Model nampak imej: prompt kaya BOS + CHoCH + FVG (backtest 7/7 TP,
        # engine/backtest-bos-choch.py). Struktur dikira deterministik dari bar,
        # model cuma sahkan dari imej + pilih SL/TP.
        tf_key = {"M5": "M15", "M15": "H1", "H1": "H4", "H4": "D1", "D1": "D1"}[tf]
        gran = {"M5": "M5", "M15": "M15", "H1": "M60", "H4": "M60", "D1": "M60"}[tf]
        s_hi = s_lo = "RANGE"
        bos = trend if trend in ("UP", "DOWN") else "RANGE"
        choch = False
        fvg_n = 0
        if ICT is not None:
            try:
                # Higher TF swing dari bar asing (guna ctx yang dah resample).
                hi_bars = [{"h": b[2], "l": b[3], "c": b[4]} for b in ctx]
                lo_bars = [{"h": b[1], "l": b[2], "c": b[3]} for b in bars]
                s_hi = ICT.swing_trend(hi_bars, 3, 2)
                s_lo = ICT.swing_trend(lo_bars, 3, 2)
                fvg_n = len(ICT.unfilled_fvg(lo_bars, price))
                bos = s_lo if s_lo != "RANGE" else s_hi
                choch = (s_hi != "RANGE" and s_lo != "RANGE" and s_lo != s_hi)
            except Exception:
                pass
        rr_min = prof["rr1_min"]
        # Indikator sebenar dihantar ke AI (ia tidak boleh baca nombor dari imej).
        _cl = [b[3] for b in bars]
        e20 = M.ema(_cl, 20)[-1] if len(_cl) >= 20 else price
        e50 = M.ema(_cl, 50)[-1] if len(_cl) >= 50 else price
        _rsi14 = M.rsi_s(_cl, 14)[-1]
        _dec = 2 if (price > 100 or "JPY" in pair.upper()) else 5
        # Konteks pasaran sebenar — apa yang carta SAHAJA tidak beritahu
        # (sesi, berita high-impact, prestasi lampau, kalibrasi diri).
        _ctx = ""
        if MC is not None:
            try:
                _l, _ = (ai_learn.lessons() if ai_learn is not None else ("", None))
                _c = (ai_learn.calibration_note() if ai_learn is not None else "")
                _ctx = MC.format_context(pair, tf, lessons=_l or "", calibration=_c or "")
            except Exception:
                _ctx = ""
        # Prompt: analyst buat keputusan dengan konteks penuh, bukan nasib.
        prompt = (
            "Look at this candlestick chart image and trade WITH the trend. "
            f"{pair} {tf}, current price {price:g}, spread {spread_pips:g} pips. "
            f"Higher TF ({tf_key}) trend: {trend}. Lower TF trend: {bos}. "
            f"Indicators (real bars): EMA20={e20:.{_dec}f} EMA50={e50:.{_dec}f} "
            f"RSI14={_rsi14:.1f} ATR14={atr:.{_dec}f}. "
            "If price makes higher highs and higher lows -> BUY. "
            "If lower highs and lower lows -> SELL. "
            "If choppy or sideways with no clear direction -> HOLD. "
            + (("MARKET CONTEXT (real data):\n" + _ctx + "\n") if _ctx else "") +
            "Confidence is a PROBABILITY: 5=coin flip, 6=55-62%, 7=62-70%, "
            "8=70-78%, 9+=rare. If you can name 2+ real counter-arguments, HOLD. "
            "Entry at CURRENT price (instant market entry). "
            "SL just beyond nearest opposing swing (must exceed 3x spread). "
            f"TP1 = exactly 1R from entry (risk x 1.0), TP2 = 1.5R. Keep TP1 CLOSE. "
            f"RR1 must be between {rr_min:g} and {rr_min+0.3:.2f} (TP1 near 1R). "
            'Reply ONLY: {"bias":"BUY"|"SELL"|"HOLD","sl":num,'
            '"tp1":num,"tp2":num,"confidence":0-10,"reason":"<6 words>"}')
        ai_meta = {"bos": bos, "choch": choch,
                   "fvg": fvg_n,
                   "atr": round(atr, 3), "hour": datetime.now(timezone.utc).hour,
                   # apa AI BACA (dipaparkan kepada client, bukan rahsia)
                   "input": {"ema20": round(e20, _dec), "ema50": round(e50, _dec),
                             "rsi14": round(_rsi14, 1), "atr14": round(atr, _dec),
                             "bars": len(bars), "tf": tf,
                             "h1_trend": trend, "structure": bos,
                             "context": _ctx,
                             "vision": bool(VISION_ENABLED)}}
    else:
        ai_meta = {"bos": trend if trend in ("UP", "DOWN") else "RANGE",
                   "choch": False, "fvg": 0, "atr": round(atr, 3),
                   "hour": datetime.now(timezone.utc).hour}
    # Closed-loop learning: suap statistik corak TP/SL sebenar client ke prompt.
    # Retrieval-augmented (bukan training) — cache 1 jam, fail-safe bila tiada data.
    # Lessons + kalibrasi sudah disuntik SEKALI melalui MC.format_context.
    # (Dulu ditambah dua kali -> buang token & kelirukan model.)
    if not _ctx and ai_learn is not None:
        try:
            _lessons, _ = ai_learn.lessons()
            _cal = ai_learn.calibration_note()
            _extra = " ".join(x for x in (_lessons, _cal) if x)
            if _extra:
                prompt += "\nLEARNED from real client outcomes: " + _extra
        except Exception:
            pass
    # Berita high-impact dekat (<=1 jam) -> HOLD paksa, jangan panggil LLM.
    # Bukti: spread melebar & stop-hunt biasa semasa release; lebih baik duduk luar.
    if MC is not None:
        try:
            _nr = MC.news_risk(pair)
            if _nr and _nr.get("blocked"):
                log(f"{pair} {tf}: HOLD — news blackout ({_nr['reason']})")
                return {"side": "HOLD", "conf": 0.2,
                        "reason": "News blackout: " + _nr["reason"][:80],
                        "news_blocked": True}
        except Exception:
            pass
    # Vision first: model tengok terus carta (kurang risiko prompt salah gambar).
    # Gagal vision -> jatuh ke chain text sedia ada (fail-safe).
    # Nota: `call` dioverride di atas untuk injection test; guna flag asal.
    if VISION_ENABLED and not explicit_call:
        t0 = time.time()
        try:
            content = _call_vision(VISION_MODEL, prompt, bars, pair, tf, CALL_TIMEOUT_S)
            j = parse_response(content)
        except Exception as e:
            log(f"{pair} vision {VISION_MODEL} gagal ({type(e).__name__}: {str(e)[:90]}) - cuba text")
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                    "model": VISION_MODEL, "vision": True,
                    "error": f"{type(e).__name__}: {str(e)[:200]}"})
        else:
            latency = time.time() - t0
            try:
                verdict = validate_verdict(j, price, pip, spread_pips, rr1_min=prof["rr1_min"], pair_hint=pair)
            except ValueError as e:
                # Rejection (aras/RR tak sah) muktamad — jangan shop model lain.
                log(f"{pair} {VISION_MODEL} (vision) verdict ditolak ({e})")
                _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                        "model": VISION_MODEL, "vision": True, "verdict_rejected": str(e)[:200]})
                return None
            verdict.update(model=VISION_MODEL, latency_s=round(latency, 1), vision=True, ai_meta=ai_meta)
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                    "model": VISION_MODEL, "vision": True, "latency_s": round(latency, 1),
                    "side": verdict["side"], "conf": verdict.get("conf")})
            log(f"{pair} {VISION_MODEL} (vision): {verdict['side']} conf={verdict.get('conf')} "
                f"rr1={verdict.get('rr1')} ({latency:.1f}s)")
            return verdict
    chain = [PRIMARY_MODEL] + [m for m in FALLBACK_MODELS if m != PRIMARY_MODEL]
    t_start = time.time()
    for model in chain:
        if time.time() - t_start > budget_s:
            log(f"{pair}: budget {budget_s}s habis")
            break
        t0 = time.time()
        try:
            content = call(model, prompt, CALL_TIMEOUT_S)
        except Exception as e:
            log(f"{pair} {model}: panggilan gagal ({type(e).__name__}: {str(e)[:100]})")
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair,
                    "model": model, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            continue
        latency = time.time() - t0
        try:
            j = parse_response(content)
        except ValueError as e:
            log(f"{pair} {model}: parse gagal ({e}) - cuba model seterusnya")
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair,
                    "model": model, "latency_s": round(latency, 1),
                    "content": content[:600], "reject": f"parse: {e}"})
            continue
        try:
            verdict = validate_verdict(j, price, pip, spread_pips, rr1_min=prof["rr1_min"], pair_hint=pair)
        except ValueError as e:
            # Penolakan sah = muktamad. Jangan "shop" model lain untuk jawapan
            # yang lepas — itu menipu diri sendiri tentang kualiti setup.
            log(f"{pair} {model}: verdict ditolak ({e})")
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair,
                    "model": model, "latency_s": round(latency, 1),
                    "content": content[:600], "reject": str(e)})
            return None
        verdict["model"] = model
        verdict["tf"] = tf
        verdict["latency_s"] = round(latency, 1)
        log(f"{pair} {model}: {verdict['side']} conf={verdict.get('conf')} "
            f"({latency:.1f}s) {verdict.get('reason', '')}")
        _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair,
                "model": model, "latency_s": round(latency, 1),
                "content": content[:600], "verdict": verdict})
        return verdict
    return None