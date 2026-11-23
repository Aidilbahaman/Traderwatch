#!/usr/bin/env python3
"""LLM analyst untuk enjin signal AI — Gemini 4 Neon (Antigravity CLI) utama.

Owner 2026-11-23: Tukar model analisis utama kepada Gemini 4 Neon (melalui
Antigravity CLI `agy -p`), dengan sandaran rootsys (deepseek-v4.1-flash) +
serveras jika agy/kuota gagal.

Owner 2026-11-20: LLM sahaja sebagai penganalisis (ganti model logistic +
gate SMC yang terlalu ketat). Setiap scan, hantar konteks H1 + M15 kepada
LLM; ia jawab BUY/SELL/HOLD + SL/TP1/TP2 + confidence + sebab ringkas.

Reka bentuk (belajar dari kegagalan bot_v2):
  * Prompt RINGKAS (<6k char). Prompt panjang membuat thinking model bakar
    token pada reasoning dan content kosong.
  * max_tokens 1500 + temperature 0.2; parser extract JSON dari mana-mana
    bahagian content (GLM tulis prose dahulu sebelum JSON).
  * Chain model: gemini-4-neon-high (agy CLI) utama -> sandaran rootsys
    (deepseek-v4.1-flash) -> sandaran serveras percuma.
    Kegagalan HTTP/CLI/parse -> cuba model seterusnya. Penolakan validasi
    (aras tak sah / SL terlalu lebar) = muktamad, TIDAK "shop" model lain.
  * Fail-closed: semua model gagal -> None (enjin skip pair, bukan pos).
  * Audit: setiap panggilan direkod ke state/llm-analysis-log.jsonl.

Validasi sanity (bukan sekatan strategi — owner 2026-11-20: jarak SL/TP
sepenuhnya keputusan LLM, TIADA cap): susunan aras, risk > 0, lantai
3x spread (mekanikal — spread jangan makan stop), RR1 >= 1.5 (konvensyen
ticket TP1/TP2 sistem).
"""
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
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
try:
    import quant_engine as QE  # noqa: E402  (multi-TF causal quant setup engine)
except Exception:
    QE = None

REPO = HERE.parent
AUDIT_FILE = REPO / "state" / "llm-analysis-log.jsonl"
ROOTSYS_KEY_FILE = Path.home() / ".config/opencode/secrets/rootsys-key"
ROOTSYS_QWEN_KEY_FILE = Path.home() / ".config/opencode/secrets/rootsys-qwen-key"
TW_BOT_ENV = Path("/home/ubuntu/tw-bot/.env")

AGY_BIN = os.environ.get("AGY_BIN", str(Path.home() / ".local/bin/agy"))
VISION_MODEL = os.environ.get("AI_LLM_VISION_MODEL", "gemini-4-neon-high")
VISION_FALLBACK_MODEL = os.environ.get("AI_LLM_VISION_FALLBACK", "gemini-4-neon-medium")
VISION_FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "AI_LLM_VISION_FALLBACKS",
    "gemini-4-neon-medium,deepseek-v4.1-flash"
).split(",") if m.strip()]
VISION_ENABLED = os.environ.get("AI_LLM_VISION", "1") == "1"
QUANT_ENABLED = os.environ.get("AI_QUANT_ENGINE", "1") == "1"
PRIMARY_MODEL = os.environ.get("AI_LLM_MODEL", "gemini-4-neon-high")
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "AI_LLM_FALLBACKS",
    "gemini-4-neon-medium,deepseek-v4.1-flash,asai/freemodel-1-GLM,asai/freemodel-2-MiniMax,asai/deepseek-v4-flash"
).split(",") if m.strip()]
CALL_TIMEOUT_S = float(os.environ.get("AI_LLM_CALL_TIMEOUT", "60"))
# Had atas RR1 lalai (untuk panggilan tanpa rr1_max eksplisit).
RR1_MAX = float(os.environ.get("AI_RR1_MAX", "1.6"))
# Toleransi pembundaran float untuk semakan RR1 (elak "RR1 1.00 below 1.0").
RR1_EPS = 0.015
BUDGET_S = float(os.environ.get("AI_LLM_BUDGET_S", "120"))

# Timeframe-aware trading styles. Aligned with quant_engine.TF_CONFIG across
# all 5 timeframes (M5, M15, H1, H4, D1) so rr1_min < quant_rr1 < rr1_max
# with zero contradictory bounds.
TF_PROFILES = {
    "M5": dict(ctx_factor=3, ctx_name="M15", min_bars=80, ctx_show=24, base_show=60,
               rr1_min=1.3, rr1_max=1.8, role="SCALPER",
               approach=("You are SCALPING. Backtest-verified config: SL = 1.5x ATR from entry "
                         "(tight, above spread), TP1 = 1.5R, TP2 = 2.2R. Trade WITH short momentum "
                         "(EMA8 vs EMA21 direction). Only enter when volatility is expanding — if the "
                         "last bars are compressed or sideways, HOLD. Quality over quantity: a clean "
                         "momentum push is enough; do NOT wait for a perfect macro setup.")),
    "M15": dict(ctx_factor=4, ctx_name="H1", min_bars=100, ctx_show=24, base_show=48,
                rr1_min=1.2, rr1_max=1.7, role="INTRADAY",
                approach=("Intraday trading with momentum: SL = 1.4x ATR, TP1 = 1.3R, TP2 = 2.0R. "
                          "Trade WITH momentum direction (EMA8 vs EMA21 on this TF). Require the trend to "
                          "agree with higher TF. If price is mid-range or ATR is compressed, HOLD — "
                          "spread will eat a tight target.")),
    "H1": dict(ctx_factor=4, ctx_name="H4", min_bars=60, ctx_show=24, base_show=48,
               rr1_min=0.80, rr1_max=1.80, role="SWING TREND",
               approach=("You are SWING trading the H1 chart. Focus on clean structural trend breakouts "
                         "and continuation patterns aligned with the H4 trend and EMA50 slope. Stops sit "
                         "outside structural volatility (~2.4x H1 ATR). TP1 ~0.85-1.2R, TP2 ~1.65R+.")),
    "H4": dict(ctx_factor=6, ctx_name="D1", min_bars=60, ctx_show=20, base_show=40,
               rr1_min=0.80, rr1_max=2.00, role="POSITION TREND",
               approach=("You are POSITION trading the H4 chart. Trade macro-aligned pullbacks and swing "
                         "breakouts aligned with the Daily/EMA200 trend. Stops beyond H4 volatility (~2.6x ATR). "
                         "TP1 ~0.85-1.3R at clean liquidity, TP2 ~1.65R+.")),
    "D1": dict(ctx_factor=5, ctx_name="W1", min_bars=55, ctx_show=12, base_show=30,
               rr1_min=0.85, rr1_max=2.20, role="POSITION TREND",
               approach=("You are POSITION trading the Daily chart. Trade institutional macro trend "
                         "continuation breakouts aligned with EMA20/EMA50/EMA100. Wide volatility stops "
                         "(~2.4x D1 ATR). TP1 ~0.90-1.5R, TP2 ~1.80R+.")),
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


# ===== SCALPING GATE (bukti backtest 33 hari, spread dikira) =====
# Baseline scalping = RUGI (-0.13R/trade). Dengan 3 filter di bawah:
#   BTCUSD +0.084R/trade (180 trade), XAUUSD +0.258R/trade (127 trade)
VOL_MULT = float(os.environ.get("AI_SCALP_VOL_MULT", "1.1"))      # ATR >= VOL_MULT x median
MOM_MIN = float(os.environ.get("AI_SCALP_MOM_MIN", "0.5"))        # |EMA8-EMA21|/ATR
SCALP_SESSIONS = {7, 8, 9, 10, 11, 12, 13, 14, 15, 16}            # London + NY


def scalp_gate(bars, hour_utc, tf):
    """Untuk M5/M15: pastikan volatility cukup, momentum ada, sesi aktif.

    Return (ok, reason). ok=False -> HOLD (elak bayar spread dalam chop).
    Backtest: tanpa gate -0.13R/trade; dengan gate +0.08R (BTC) / +0.26R (XAU).
    """
    if str(tf).upper() not in ("M5", "M15"):
        return True, ""
    if not bars or len(bars) < 60:
        return False, "insufficient bars for scalp gate"
    if hour_utc not in SCALP_SESSIONS:
        return False, "outside London/NY session (low liquidity for scalping)"
    cl = [b[3] for b in bars]
    # ATR semasa
    atr_now = M.atr_s(bars)[-1]
    if atr_now <= 0:
        return False, "ATR unavailable"
    # Volatility: ATR semasa vs MEDIAN ATR 150 bar sebelum ini.
    # Backtest: XAU +0.42R/trade pada 1.2x; BTC negatif di semua threshold.
    def _atr(seg):
        if len(seg) < 15:
            return 0.0
        tr = [max(seg[j][1] - seg[j][2], abs(seg[j][1] - seg[j - 1][3]),
                  abs(seg[j][2] - seg[j - 1][3])) for j in range(len(seg) - 14, len(seg))]
        return sum(tr) / len(tr)

    if len(bars) >= 165:
        prior = _atr(bars[-165:-15])
        if prior > 0:
            ratio = atr_now / prior
            if ratio < VOL_MULT:
                return False, (f"volatility {ratio:.2f}x below median (need {VOL_MULT}x) "
                               "— spread would eat a tight target")
    # momentum
    if len(cl) >= 21:
        e8 = sum(cl[-8:]) / 8.0
        e21 = sum(cl[-21:]) / 21.0
        mom = abs(e8 - e21) / atr_now
        if mom < MOM_MIN:
            return False, (f"no momentum ({mom:.2f} < {MOM_MIN}) — chop, spread would eat profit")
    return True, ""


def validate_verdict(j, price, pip, spread_pips, rr1_min=1.5, pair_hint="", rr1_max=None):
    """Semak sanity jawapan LLM; pulangkan verdict bersih atau raise ValueError.

    Jarak SL/TP = keputusan LLM (tiada cap). Semakan di sini mekanikal:
    susunan aras, risk positif, lantai spread, julat RR1 [rr1_min, rr1_max]
    dengan toleransi pembundaran float (RR1_EPS).
    """
    bias = str(j.get("bias", "")).strip().upper()
    reason = str(j.get("reason", ""))[:200]
    try:
        raw_conf = float(j.get("confidence", 5))
        conf = min(1.0, max(0.0, raw_conf / 10.0)) if math.isfinite(raw_conf) else 0.5
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
    if not (math.isfinite(sl) and math.isfinite(tp1) and math.isfinite(tp2) and math.isfinite(price)):
        raise ValueError("medan harga bukan nombor terhingga")
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
    cap = RR1_MAX if rr1_max is None else float(rr1_max)
    if rr1 + RR1_EPS < rr1_min:
        raise ValueError(f"RR1 {rr1:.2f} below {rr1_min}")
    if rr1 - RR1_EPS > cap:
        raise ValueError(f"RR1 {rr1:.2f} above cap {cap} (TP too far — unrealistic)")
    sp = session_penalty(pair_hint, datetime.now(timezone.utc).hour)
    return {"side": bias, "entry": round(price, 5), "sl": round(sl, 5),
            "tp1": round(tp1, 5), "tp2": round(tp2, 5),
            "conf": round(min(0.95, conf * sp), 2), "reason": reason,
            "rr1": round(rr1, 2), "rr2": round(rr2, 2)}


# Sumber panggilan semasa (thread-local supaya analyze-api berbilang thread selamat).
# "member" = manusia tekan butang · "bot" = signal-engine auto-scan · "backtest" = ujian.
# Lencana "Requests this hour" pada pair card hanya kira "member".
_AUDIT_CTX = threading.local()


def _audit(record):
    try:
        record.setdefault("src", getattr(_AUDIT_CTX, "src", "bot"))
        tap = getattr(_AUDIT_CTX, "tap", None)
        if tap:
            record.setdefault("tap", tap)
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > 5_000_000:
            lines = AUDIT_FILE.read_text().splitlines()[-2000:]
            AUDIT_FILE.write_text("\n".join(lines) + "\n")
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"WARN audit gagal: {type(e).__name__}")


def _is_agy_model(model):
    bare = model.split("/", 1)[-1].lower()
    return model.startswith("agy/") or bare.startswith("gemini-")


def _call_agy(model, prompt, timeout, image_b64=None):
    """Panggil model Antigravity CLI (contoh: gemini-4-neon-medium) secara headless."""
    if not Path(AGY_BIN).is_file():
        raise RuntimeError(f"agy binary tidak dijumpai: {AGY_BIN}")
    slug = model.split("/", 1)[-1]
    timeout_s = max(15, int(timeout))
    img_path = None
    try:
        if image_b64:
            fd, img_path = tempfile.mkstemp(prefix="tw_chart_", suffix=".png", dir="/tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(image_b64))
            full_prompt = (
                f"First call read_file on {img_path} to inspect the chart image. "
                "Do not call any other tools. Then reply strictly following these instructions:\n\n"
                + prompt
            )
        else:
            full_prompt = (
                "Do not call any tools. Reply directly following these instructions:\n\n"
                + prompt
            )
        env = os.environ.copy()
        env.setdefault("HOME", str(Path.home()))
        local_bin = str(Path.home() / ".local/bin")
        if local_bin not in env.get("PATH", ""):
            env["PATH"] = f"{local_bin}:{env.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"
        cmd = [
            AGY_BIN,
            "-p", full_prompt,
            "--model", slug,
            "--output-format", "json",
            "--disable-slash-commands",
            "--print-timeout", f"{timeout_s}s",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s + 15,
            cwd="/tmp",
            env=env,
        )
        raw = (proc.stdout or "").strip()
        data = None
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if not isinstance(data, dict):
            err = (proc.stderr or raw or f"exit {proc.returncode}")[:180]
            raise RuntimeError(f"agy non-JSON output: {err}")
        if data.get("status") != "SUCCESS":
            err = (data.get("error") or proc.stderr or data.get("status"))
            raise RuntimeError(f"agy gagal: {str(err)[:180]}")
        return data.get("response") or ""
    finally:
        if img_path:
            try:
                os.unlink(img_path)
            except OSError:
                pass


def _call_model(model, prompt, timeout):
    if _is_agy_model(model):
        return _call_agy(model, prompt, timeout)
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


def _call_vision_b64(model, prompt, b64, timeout, max_tokens=700):
    """Panggil model vision (agy CLI atau HTTP OpenAI-compatible) dengan PNG base64."""
    if _is_agy_model(model):
        return _call_agy(model, prompt, timeout, image_b64=b64)
    url, key = _route(model)
    if not key:
        raise RuntimeError(f"tiada API key untuk vision {model}")
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": [
                           {"type": "text", "text": prompt},
                           {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}],
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode())
    choice = (j.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content") or ""


def _call_vision(model, prompt, bars, pair, tf, timeout, bos="", choch=False, levels=None):
    """Vision model: hantar prompt + screenshot chart (bar <= masa semasa)."""
    b64 = VC.render(bars, pair=pair, tf=tf, bos=bos, choch=choch, levels=levels)
    if not b64:
        raise RuntimeError("vision chart render gagal")
    return _call_vision_b64(model, prompt, b64, timeout, max_tokens=700)


def _vision_chain():
    """Deduplicated ordered list of vision models (Neon High -> Neon Medium -> fallback)."""
    out = []
    for m in [VISION_MODEL, VISION_FALLBACK_MODEL] + list(VISION_FALLBACK_MODELS):
        if m and m not in out:
            out.append(m)
    return out


def alignment(pair, tf_bars, timeout=60):
    """Multi-TF alignment: satu imej gabungan (M5/H1/H4), satu panggilan vision.
    tf_bars = {tf: bars}. Return {tfs:{tf:bias}, aligned, note} atau None."""
    panels = [(tf, tf_bars[tf]) for tf in ("M5", "H1", "H4") if tf_bars.get(tf)]
    if not panels:
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
    for mdl in _vision_chain():
        try:
            content = _call_vision_b64(mdl, prompt, b64, timeout, max_tokens=300)
            m = json.loads(content[content.find("{"):content.rfind("}") + 1])
            t = {k: str(v).upper() for k, v in (m.get("tfs") or {}).items() if str(v).upper() in ("BUY", "SELL", "HOLD")}
            if not t:
                continue
            dirs = [v for v in t.values() if v in ("BUY", "SELL")]
            aligned = len(dirs) >= 2 and len(set(dirs)) == 1
            return {"tfs": t, "aligned": aligned, "note": str(m.get("note") or "")[:80], "model": mdl}
        except Exception as e:
            log(f"{pair} alignment {mdl} gagal ({type(e).__name__}: {str(e)[:80]})")
    return None


def build_quant_vision_prompt(pair, tf, price, spread_pips, tf_key, trend, bos,
                              e20, e50, rsi14, atr, dec, prof, q, market_ctx="", held=None):
    """Build the Quant + Vision confirmation prompt for Gemini 4 Neon.

    Shared by live analyze() and end-to-end backtests so zero prompt drift occurs.
    """
    rr_min = prof["rr1_min"]
    rr_max = prof["rr1_max"]
    qm = q.get("metrics") or {}
    held_line = ""
    if held:
        if len(held) > 1:
            held_line = "Both BUY and SELL already open on this pair -> reply HOLD.\n"
        else:
            hs = next(iter(held))
            opp = "BUY" if hs == "SELL" else "SELL"
            held_line = f"Open position: {hs}. Do NOT issue {opp} (no hedging).\n"
    ctx_block = ("MARKET CONTEXT (real data):\n" + market_ctx + "\n") if market_ctx else ""
    return (
        f"You are the senior visual risk analyst confirming a statistically validated {tf} quant setup.\n"
        f"Pair: {pair} {tf} | Live price: {price:.{dec}f} | Spread: {spread_pips:g} pips\n"
        f"Higher TF ({tf_key}) trend: {trend} | Structure BOS: {bos} | Macro EMA200 bias: {qm.get('macro', trend)}\n"
        f"Indicators (real bars): EMA20={e20:.{dec}f}, EMA50={e50:.{dec}f}, "
        f"EMA200={qm.get('ema200', e50):.{dec}f}, RSI2={qm.get('rsi2', 50)}, "
        f"RSI14={rsi14:.1f}, StochK={qm.get('stoch_k', 50)}, ATR14={atr:.{dec}f} "
        f"(ATR/spread={qm.get('atr_to_spread', 0)}x).\n"
        f"QUANT CANDIDATE: {q['side']} | Triggers: {q['setup_label']} | Grade {q['grade']} "
        f"(score={q['score']}, quant_conf={int(q['base_conf']*10)}/10)\n"
        f"PROPOSED LEVELS (drawn on chart): entry={q['entry']:.{dec}f}, "
        f"sl={q['sl']:.{dec}f} ({q['risk_atr']}x ATR), "
        f"tp1={q['tp1']:.{dec}f} ({q['rr1']}R), tp2={q['tp2']:.{dec}f} ({q['rr2']}R).\n"
        f"{ctx_block}{held_line}"
        "Inspect the chart image (candlesticks: lime body=close above open, red body=close below open, "
        "wick high-low range, amber=EMA20, purple=EMA50, "
        "circles=swings, red=SL, green=TP1, cyan=TP2).\n"
        "DECISION RULES:\n"
        f"1. APPROVE ({q['side']}) if the chart structure supports this {q['side']} setup without a severe visual trap. "
        "Keep the proposed calibrated SL/TP1/TP2 (only adjust slightly if a clear swing demands it; "
        f"RR1 must stay between {rr_min:g} and {rr_max:g}).\n"
        "2. VETO (HOLD) ONLY for a CLEAR, severe visual invalidation right now: "
        "(a) buying straight into an obvious multi-swing double-top/brick-wall ceiling before TP1, "
        "(b) selling straight into an obvious multi-swing floor before TP1, "
        "(c) violent parabolic spike / whipsaw news bar, or (d) clear structural breakdown opposing the setup. "
        "Do NOT veto normal pullbacks in a healthy trend.\n"
        f"3. Never flip to the opposite side — reply only {q['side']} or HOLD.\n"
        "Confidence is honest probability (6=60%, 7=68%, 8=75%, 9=rare).\n"
        'Reply ONLY one compact JSON object, no markdown: '
        '{"bias":"BUY"|"SELL"|"HOLD","sl":num,"tp1":num,"tp2":num,"confidence":0-10,"reason":"<max 10 words>"}'
    )


def build_quant_text_prompt(base_prompt, q, prof, market_ctx=""):
    """Append quant candidate details onto the OHLC text prompt for text-only fallback models.

    Unlike build_quant_vision_prompt(), this never references a chart image and preserves
    the full higher-TF + base-TF OHLC rows in `base_prompt`.
    """
    rr_min = prof["rr1_min"]
    rr_max = prof["rr1_max"]
    ctx_block = ("\nMARKET CONTEXT (real data):\n" + market_ctx) if market_ctx else ""
    return (
        base_prompt
        + ctx_block
        + f"\nQUANT CANDIDATE (validated setup): {q['side']} | Triggers: {q['setup_label']} "
        f"| Grade {q['grade']} (score={q['score']}, quant_conf={int(q['base_conf']*10)}/10)\n"
        f"PROPOSED CALIBRATED LEVELS: entry={q['entry']}, sl={q['sl']} ({q['risk_atr']}x ATR), "
        f"tp1={q['tp1']} ({q['rr1']}R), tp2={q['tp2']} ({q['rr2']}R).\n"
        f"Confirm {q['side']} (keeping calibrated levels; RR1 between {rr_min:g} and {rr_max:g}) "
        f"OR veto with HOLD if recent OHLC shows a severe trap/reversal. Never flip to opposite side."
    )


def analyze(pair, bars, pip, spread_pips, call=None, budget_s=None, held=None, tf="M15",
            src="bot", tap=None):
    """Analisis LLM untuk satu pair mengikut timeframe. Return verdict dict / None.

    TF-aware: M5=scalping, M15=intraday, H1=swing, H4/D1=position.
    Dalam mod live/vision (AI_QUANT_ENGINE=1), quant_engine menyaring setup
    berkebarangkalian tinggi terlebih dahulu, kemudian Gemini 4 Neon memeriksa
    carta visual (dengan EMA20/50 + paras SL/TP1/TP2) untuk sahkan atau veto.

    src = "member" (tekan butang), "bot" (auto-scan enjin), atau "backtest".
    Hanya "member" dikira dalam lencana permintaan pada pair card.
    tap = id satu ketukan UI. Scan 5 TF dalam satu ketukan berkongsi tap yang
    sama, jadi lencana kira SATU permintaan, bukan lima.
    """
    _AUDIT_CTX.src = src
    _AUDIT_CTX.tap = tap
    explicit_call = call is not None
    call = call or _call_model
    budget_s = budget_s or BUDGET_S
    tf = str(tf).upper() if str(tf).upper() in TF_PROFILES else "M15"
    prof = tf_profile(tf)
    if not bars or len(bars) < prof["min_bars"]:
        log(f"{pair} {tf}: bar tidak cukup ({len(bars or [])} < {prof['min_bars']})")
        return None
    price = bars[-1][3]
    atr = M.atr_s(bars)[-1]
    # Data FLAT (market tutup / collector mati) -> tolak, jangan biar AI reka.
    _uniq = len({(round(b[1], 6), round(b[2], 6)) for b in bars[-60:]})
    if _uniq < 5:
        log(f"{pair} {tf}: tolak — data flat ({_uniq} harga unik /60 bar)")
        return {"side": "HOLD", "conf": 0.0, "tf": tf,
                "reason": "Market data unavailable — no price movement "
                          "(market closed or feed stalled).", "stale_data": True}
    # Scalping gate (M5/M15): volatility + momentum + sesi.
    # Backtest: baseline -0.13R/trade; dengan gate +0.08R (BTC) / +0.26R (XAU).
    _gok, _greason = scalp_gate(bars, datetime.now(timezone.utc).hour, tf)
    if not _gok:
        log(f"{pair} {tf}: HOLD — scalp gate ({_greason})")
        return {"side": "HOLD", "conf": 0.2,
                "reason": "Scalp gate: " + _greason, "scalp_blocked": True}

    # Berita high-impact dekat (<=1 jam) -> HOLD paksa, jangan panggil LLM.
    # Bukti: spread melebar & stop-hunt biasa semasa release; lebih baik duduk luar.
    if not explicit_call and MC is not None:
        try:
            _nr = MC.news_risk(pair)
            if _nr and _nr.get("blocked"):
                log(f"{pair} {tf}: HOLD — news blackout ({_nr['reason']})")
                return {"side": "HOLD", "conf": 0.2, "tf": tf,
                        "reason": "News blackout: " + _nr["reason"][:80],
                        "news_blocked": True}
        except Exception:
            pass

    ctx = resample(bars, prof["ctx_factor"])
    closes_ctx = [b[4] for b in ctx]
    trend = "FLAT"
    if len(closes_ctx) >= 50:
        e20c, e50c = M.ema(closes_ctx, 20), M.ema(closes_ctx, 50)
        trend = "UP" if e20c[-1] > e50c[-1] else ("DOWN" if e20c[-1] < e50c[-1] else "FLAT")
    win = bars[-96:]
    hh, ll = max(b[1] for b in win), min(b[2] for b in win)
    text_prompt = build_prompt(pair, price, ctx[-prof["ctx_show"]:], with_opens(bars)[-prof["base_show"]:],
                               atr, trend, hh, ll, spread_pips, tf=tf, held=held)
    vision_prompt = None
    _ctx = ""
    bos = trend if trend in ("UP", "DOWN") else "RANGE"
    choch = False
    q_setup = None
    rr_min = prof["rr1_min"]
    rr_max = prof.get("rr1_max", RR1_MAX)

    if VISION_ENABLED and not explicit_call:
        tf_key = {"M5": "M15", "M15": "H1", "H1": "H4", "H4": "D1", "D1": "W1"}[tf]
        s_hi = s_lo = "RANGE"
        fvg_n = 0
        if ICT is not None:
            try:
                hi_bars = [{"h": b[2], "l": b[3], "c": b[4]} for b in ctx]
                lo_bars = [{"h": b[1], "l": b[2], "c": b[3]} for b in bars]
                s_hi = ICT.swing_trend(hi_bars, 3, 2)
                s_lo = ICT.swing_trend(lo_bars, 3, 2)
                fvg_n = len(ICT.unfilled_fvg(lo_bars, price))
                bos = s_lo if s_lo != "RANGE" else s_hi
                choch = (s_hi != "RANGE" and s_lo != "RANGE" and s_lo != s_hi)
            except Exception:
                pass
        _cl = [b[3] for b in bars]
        e20 = M.ema(_cl, 20)[-1] if len(_cl) >= 20 else price
        e50 = M.ema(_cl, 50)[-1] if len(_cl) >= 50 else price
        _rsi14 = M.rsi_s(_cl, 14)[-1]
        _dec = 2 if price > 500 else (3 if pip >= 0.01 else 5)
        if MC is not None:
            try:
                _l, _ = (ai_learn.lessons() if ai_learn is not None else ("", None))
                _c = (ai_learn.calibration_note() if ai_learn is not None else "")
                _ctx = MC.format_context(pair, tf, lessons=_l or "", calibration=_c or "")
            except Exception:
                _ctx = ""

        if QUANT_ENABLED and QE is not None:
            q_setup = QE.scan(bars, pair, tf, pip, spread_pips)

        ai_meta = {
            "bos": bos, "choch": choch, "fvg": fvg_n,
            "atr": round(atr, 5 if _dec == 5 else 3),
            "hour": datetime.now(timezone.utc).hour,
            "quant": ({
                "side": q_setup.get("side"),
                "setups": q_setup.get("setups", []),
                "setup_label": q_setup.get("setup_label", ""),
                "grade": q_setup.get("grade", "NONE"),
                "score": q_setup.get("score", 0),
                "risk_atr": q_setup.get("risk_atr"),
            } if q_setup else None),
            "input": {
                "ema20": round(e20, _dec), "ema50": round(e50, _dec),
                "rsi14": round(_rsi14, 1), "atr14": round(atr, _dec),
                "bars": len(bars), "tf": tf,
                "h1_trend": trend, "structure": bos,
                "context": _ctx, "vision": bool(VISION_ENABLED),
            },
        }

        if q_setup is not None:
            # Anti-hedge gate sebelum panggil LLM
            if q_setup.get("side") and held:
                if len(held) > 1 or q_setup["side"] not in held:
                    reason = f"Anti-hedge: open {sorted(held)} blocks {q_setup['side']}."
                    log(f"{pair} {tf} quant HOLD: {reason}")
                    return {
                        "side": "HOLD", "conf": 0.3, "reason": reason, "tf": tf,
                        "model": f"{VISION_MODEL}+quant", "latency_s": 0.0,
                        "vision": False, "ai_meta": ai_meta,
                    }
            # Tiada trigger quant -> HOLD pantas tanpa bakar masa/kuota LLM
            if not q_setup.get("side"):
                reason = q_setup.get("hold_reason") or f"Waiting for clean {tf} setup."
                _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                        "model": f"{VISION_MODEL}+quant", "vision": False, "latency_s": 0.0,
                        "side": "HOLD", "conf": 0.35, "quant_gate": reason[:140]})
                log(f"{pair} {tf} quant-gate: HOLD ({reason[:90]})")
                return {
                    "side": "HOLD", "conf": 0.35, "reason": reason, "tf": tf,
                    "model": f"{VISION_MODEL}+quant", "latency_s": 0.0,
                    "vision": False, "ai_meta": ai_meta,
                }
            # Setup quant aktif -> Gemini 4 Neon sahkan secara visual pada carta
            vision_prompt = build_quant_vision_prompt(
                pair, tf, price, spread_pips, tf_key, trend, bos,
                e20, e50, _rsi14, atr, _dec, prof, q_setup,
                market_ctx=_ctx, held=held,
            )
            text_prompt = build_quant_text_prompt(text_prompt, q_setup, prof, market_ctx=_ctx)
        else:
            # Standalone vision fallback jika AI_QUANT_ENGINE=0
            vision_prompt = (
                "Look at this price chart image and trade WITH the trend. "
                f"{pair} {tf}, current price {price:.{_dec}f}, spread {spread_pips:g} pips. "
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
                "SL outside volatility/swing (~2-2.5x ATR, must exceed 3x spread). "
                f"RR1 must be between {rr_min:g} and {rr_max:g}; TP2 further at next target. "
                'Reply ONLY: {"bias":"BUY"|"SELL"|"HOLD","sl":num,'
                '"tp1":num,"tp2":num,"confidence":0-10,"reason":"<8 words>"}')
    else:
        ai_meta = {"bos": bos, "choch": False, "fvg": 0, "atr": round(atr, 3),
                   "hour": datetime.now(timezone.utc).hour}

    # Closed-loop learning fallback bila tiada MC context (hanya untuk bukan explicit_call)
    if not _ctx and not explicit_call and ai_learn is not None:
        try:
            _lessons, _ = ai_learn.lessons()
            _cal = ai_learn.calibration_note()
            _extra = " ".join(x for x in (_lessons, _cal) if x)
            if _extra:
                text_prompt += "\nLEARNED from real client outcomes: " + _extra
                if vision_prompt is not None:
                    vision_prompt += "\nLEARNED from real client outcomes: " + _extra
        except Exception:
            pass

    # Vision first: Gemini 4 Neon (High -> Medium) tengok carta (EMA20/50 + SL/TP1/TP2).
    # Gagal vision -> cuba sandaran vision -> jatuh ke chain text sedia ada (fail-safe).
    vision_failed = set()
    if VISION_ENABLED and not explicit_call and vision_prompt is not None:
        for v_model in _vision_chain():
            t0 = time.time()
            try:
                content = _call_vision(
                    v_model, vision_prompt, bars, pair, tf, CALL_TIMEOUT_S,
                    bos=bos, choch=choch, levels=q_setup if (q_setup and q_setup.get("side")) else None,
                )
                j = parse_response(content)
            except Exception as e:
                vision_failed.add(v_model)
                log(f"{pair} vision {v_model} gagal ({type(e).__name__}: {str(e)[:90]}) - cuba seterusnya")
                _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                        "model": v_model, "vision": True,
                        "error": f"{type(e).__name__}: {str(e)[:200]}"})
                continue
            latency = time.time() - t0
            # Jika quant mencadangkan arah tertentu dan vision cuba terbalik arah -> HOLD (elak konflik).
            if q_setup and q_setup.get("side"):
                v_bias = str(j.get("bias", "")).strip().upper()
                if v_bias in ("BUY", "SELL") and v_bias != q_setup["side"]:
                    log(f"{pair} {tf} {v_model} conflict: quant={q_setup['side']} vision={v_bias} -> HOLD")
                    verdict = {
                        "side": "HOLD", "conf": 0.4,
                        "reason": f"Quant ({q_setup['side']}) vs Vision ({v_bias}) conflict — stay flat.",
                    }
                    verdict.update(model=v_model, tf=tf, latency_s=round(latency, 1),
                                   vision=True, ai_meta=ai_meta)
                    _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                            "model": v_model, "vision": True, "latency_s": round(latency, 1),
                            "side": "HOLD", "conflict": f"{q_setup['side']}!={v_bias}"})
                    return verdict
            try:
                verdict = validate_verdict(
                    j, price, pip, spread_pips,
                    rr1_min=rr_min, rr1_max=rr_max, pair_hint=pair,
                )
            except ValueError as e:
                log(f"{pair} {v_model} (vision) verdict ditolak ({e})")
                _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                        "model": v_model, "vision": True, "verdict_rejected": str(e)[:200]})
                return None
            verdict.update(model=v_model, tf=tf, latency_s=round(latency, 1),
                           vision=True, ai_meta=ai_meta)
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                    "model": v_model, "vision": True, "latency_s": round(latency, 1),
                    "side": verdict["side"], "conf": verdict.get("conf"),
                    "setup": q_setup.get("setup_label") if q_setup else ""})
            log(f"{pair} {tf} {v_model} (vision): {verdict['side']} conf={verdict.get('conf')} "
                f"rr1={verdict.get('rr1')} ({latency:.1f}s)")
            return verdict

    chain = [m for m in ([PRIMARY_MODEL] + [m for m in FALLBACK_MODELS if m != PRIMARY_MODEL])
             if m not in vision_failed]
    t_start = time.time()
    for model in chain:
        if time.time() - t_start > budget_s:
            log(f"{pair}: budget {budget_s}s habis")
            break
        t0 = time.time()
        try:
            content = call(model, text_prompt, CALL_TIMEOUT_S)
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
        if q_setup and q_setup.get("side"):
            v_bias = str(j.get("bias", "")).strip().upper()
            if v_bias in ("BUY", "SELL") and v_bias != q_setup["side"]:
                verdict = {
                    "side": "HOLD", "conf": 0.4, "model": model, "tf": tf,
                    "latency_s": round(latency, 1), "vision": False, "ai_meta": ai_meta,
                    "reason": f"Quant ({q_setup['side']}) vs LLM ({v_bias}) conflict — stay flat.",
                }
                _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair, "tf": tf,
                        "model": model, "latency_s": round(latency, 1), "verdict": verdict})
                return verdict
        try:
            verdict = validate_verdict(
                j, price, pip, spread_pips,
                rr1_min=rr_min, rr1_max=rr_max, pair_hint=pair,
            )
        except ValueError as e:
            log(f"{pair} {model}: verdict ditolak ({e})")
            _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair,
                    "model": model, "latency_s": round(latency, 1),
                    "content": content[:600], "reject": str(e)})
            return None
        verdict["model"] = model
        verdict["tf"] = tf
        verdict["latency_s"] = round(latency, 1)
        verdict["vision"] = False
        verdict["ai_meta"] = ai_meta
        log(f"{pair} {model}: {verdict['side']} conf={verdict.get('conf')} "
            f"({latency:.1f}s) {verdict.get('reason', '')}")
        _audit({"ts": datetime.now(timezone.utc).isoformat(), "pair": pair,
                "model": model, "latency_s": round(latency, 1),
                "content": content[:600], "verdict": verdict})
        return verdict
    return None