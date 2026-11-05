"""Feature: quantitative indicators (spec §1.4 group E).

ATR · RSI · MACD · ADX/DMI · ROC · EMA 20/50/200 + slope · realized volatility.
Indikator adalah EVIDENCE SOKONGAN, bukan trigger tunggal (spec §1.4 E).
"""
from __future__ import annotations

import math


def ema(vals, n):
    if len(vals) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(vals[:n]) / n]
    for v in vals[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(vals, n=14):
    if len(vals) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, n + 1):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = sum(gains) / n, sum(losses) / n
    for i in range(n + 1, len(vals)):
        d = vals[i] - vals[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 3)


def atr(bars, i, n=14):
    tr = []
    for k in range(max(1, i - n + 1), i + 1):
        pc = bars[k - 1]["close"]
        tr.append(max(bars[k]["high"] - bars[k]["low"],
                      abs(bars[k]["high"] - pc), abs(bars[k]["low"] - pc)))
    return sum(tr) / len(tr) if tr else 0.0


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None
    ef, es = ema(closes, fast), ema(closes, slow)
    if not ef or not es:
        return None
    # Sejajarkan hujung
    n = min(len(ef), len(es))
    line = [ef[-n + k] - es[-n + k] for k in range(n)]
    sig = ema(line, signal)
    if not sig:
        return None
    hist = line[-1] - sig[-1]
    return {"line": round(line[-1], 6), "signal": round(sig[-1], 6),
            "hist": round(hist, 6)}


def adx(bars, i, n=14):
    """ADX/DMI — kekuatan trend (bukan arah)."""
    if i < n * 2:
        return None
    plus, minus, trs = [], [], []
    for k in range(i - n + 1, i + 1):
        up = bars[k]["high"] - bars[k - 1]["high"]
        dn = bars[k - 1]["low"] - bars[k]["low"]
        plus.append(up if (up > dn and up > 0) else 0.0)
        minus.append(dn if (dn > up and dn > 0) else 0.0)
        pc = bars[k - 1]["close"]
        trs.append(max(bars[k]["high"] - bars[k]["low"],
                       abs(bars[k]["high"] - pc), abs(bars[k]["low"] - pc)))
    tr_s = sum(trs) or 1e-9
    pdi = 100 * (sum(plus) / n) / (tr_s / n)
    mdi = 100 * (sum(minus) / n) / (tr_s / n)
    denom = pdi + mdi
    dx = 100 * abs(pdi - mdi) / denom if denom else 0.0
    return {"adx": round(dx, 3), "plus_di": round(pdi, 3), "minus_di": round(mdi, 3)}


def roc(closes, n=10):
    if len(closes) < n + 1:
        return None
    return round((closes[-1] - closes[-n - 1]) / closes[-n - 1] * 100, 4)


def realized_vol(closes, n=50):
    if len(closes) < n + 1:
        return None
    rets = [math.log(closes[k] / closes[k - 1])
            for k in range(len(closes) - n, len(closes)) if closes[k - 1] > 0]
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(252 * 96) * 100, 4)  # annualised M15


def ema_slope(vals, n):
    e = ema(vals, n)
    if len(e) < 2:
        return None
    return round((e[-1] - e[-2]) / e[-2] * 100, 5)


def quant_features(bars, i):
    """Kumpulan feature quant untuk bar i."""
    closes = [b["close"] for b in bars[max(0, i - 260):i + 1]]
    a = atr(bars, i)
    r = rsi(closes)
    m = macd(closes)
    ax = adx(bars, i)
    rc = roc(closes)
    rv = realized_vol(closes)
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    s20 = ema_slope(closes, 20)
    s50 = ema_slope(closes, 50)

    ev, score, codes = [], 0.0, []
    c = bars[i]["close"]

    # EMA alignment
    if e20 and e50:
        if e20[-1] > e50[-1]:
            score += 0.2
            codes.append("EMA_BULL")
        else:
            score -= 0.2
            codes.append("EMA_BEAR")
        if e200:
            ev.append({"type": "EMA_STACK",
                       "above_200": e20[-1] > e200[-1]})
    # RSI
    if r is not None:
        ev.append({"type": "RSI", "value": r})
        if r > 70:
            score -= 0.15
            codes.append("RSI_OB")
        elif r < 30:
            score += 0.15
            codes.append("RSI_OS")
    # MACD
    if m:
        ev.append({"type": "MACD", **m})
        score += 0.15 if m["hist"] > 0 else -0.15
    # ADX regime + DMI arah
    if ax:
        ev.append({"type": "ADX", **ax})
        if ax["adx"] > 25:
            codes.append("STRONG_TREND")
            # DMI: +DI > -DI = tekanan beli, sebaliknya jual
            if ax["plus_di"] > ax["minus_di"]:
                score += 0.15
                codes.append("DMI_BULL")
            else:
                score -= 0.15
                codes.append("DMI_BEAR")
        # Kesan konflik EMA vs DMI — ini bukan neutral, ini tanda berlawanan
        if e20 and e50:
            ema_bull = e20[-1] > e50[-1]
            dmi_bull = ax["plus_di"] > ax["minus_di"]
            if ax["adx"] > 25 and ema_bull != dmi_bull:
                codes.append("CONFLICT_EMA_DMI")
    # Slope
    if s20 is not None:
        score += 0.1 if s20 > 0 else -0.1
        ev.append({"type": "EMA20_SLOPE", "value": s20})

    score = max(-1.0, min(1.0, score))
    direction = "BULLISH" if score > 0.15 else ("BEARISH" if score < -0.15 else "NEUTRAL")
    return {"score": round(score, 4), "direction": direction,
            "coverage": 1.0, "quality": 1.0, "evidence": ev, "reason_codes": codes,
            "raw": {"atr": round(a, 8), "rsi": r, "macd": m, "adx": ax,
                    "roc": rc, "realized_vol": rv,
                    "ema20": round(e20[-1], 8) if e20 else None,
                    "ema50": round(e50[-1], 8) if e50 else None,
                    "ema200": round(e200[-1], 8) if e200 else None}}
