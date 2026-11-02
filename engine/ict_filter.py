"""TraderWatch Phase 2 (terhad): ICT filter deterministik.

Tiga detection atas candles M15+H1 sedia ada (sq-bars.db / acandles):
  1. swing_trend()  — BOS arah: HH/HL (up), LH/LL (down), range selain itu.
  2. unfilled_fvg()  — senarai Fair Value Gap belum terisi berhampiran harga.
  3. sweep()         — liquidity sweep: wick ambil high/low lepas, close balik dalam range.

ict_verdict(pair, side, entry, h1, m15) -> dict:
  {verdict: PASS|SOFT_VETO|HARD_VETO, trend, reasons[], fvg_near, swept}

Peraturan veto (konservatif — elak false veto):
  - HARD_VETO hanya bila side lawan trend H1+M15 yang SEHALA (kedua-dua jelas),
    atau entry betul-betul di dalam premium/discount ekstrem lawan arah.
  - SOFT_VETO bila tiada FVG menyokong arah, atau sweep baru lawan arah.
  - Selain itu PASS (LLM kekal penentu).

Tiada ramalan, tiada skor keyakinan — hanya fakta struktur.
"""
from __future__ import annotations


def _swings(bars, lookback=3):
    """Kembalikan senarai (idx, high, low) swing points."""
    hs = [float(b["h"]) for b in bars]
    ls = [float(b["l"]) for b in bars]
    out = []
    for i in range(lookback, len(bars) - lookback):
        if hs[i] == max(hs[i - lookback:i + lookback + 1]):
            out.append((i, hs[i], None))
        if ls[i] == min(ls[i - lookback:i + lookback + 1]):
            out.append((i, None, ls[i]))
    return out


def swing_trend(bars, lookback=3, need=2):
    """UP jika HH+HL konsisten, DOWN jika LH+LL konsisten, else RANGE."""
    sw = _swings(bars, lookback)
    highs = [h for _, h, _ in sw if h is not None][-4:]
    lows = [l for _, _, l in sw if l is not None][-4:]
    up = (len(highs) >= need and all(b > a for a, b in zip(highs, highs[1:]))
          and len(lows) >= need and all(b > a for a, b in zip(lows, lows[1:])))
    dn = (len(highs) >= need and all(b < a for a, b in zip(highs, highs[1:]))
          and len(lows) >= need and all(b < a for a, b in zip(lows, lows[1:])))
    if up:
        return "UP"
    if dn:
        return "DOWN"
    return "RANGE"


def unfilled_fvg(bars, price, atr_mult=3.0):
    """FVG bullish (low[i+2] > high[i]) / bearish belum terisi berhampiran harga."""
    out = []
    atr = _atr(bars) or 0.0
    lim = atr * atr_mult
    for i in range(len(bars) - 2):
        b0, _, b2 = bars[i], bars[i + 1], bars[i + 2]
        gap_up = float(b2["l"]) - float(b0["h"])
        gap_dn = float(b0["l"]) - float(b2["h"])
        if gap_up > 0 and abs(float(bars[-1]["c"]) - (float(b0["h"]) + gap_up / 2)) <= lim:
            out.append({"dir": "BUY", "top": float(b2["l"]), "bot": float(b0["h"])})
        elif gap_dn > 0 and abs(float(bars[-1]["c"]) - (float(b2["h"]) + gap_dn / 2)) <= lim:
            out.append({"dir": "SELL", "top": float(b0["l"]), "bot": float(b2["h"])})
    return out


def _atr(bars, n=14):
    if len(bars) < n + 1:
        return 0.0
    trs = []
    for i in range(1, n + 1):
        b, p = bars[-i], bars[-i - 1]
        trs.append(max(float(b["h"]) - float(b["l"]),
                       abs(float(b["h"]) - float(p["c"])),
                       abs(float(b["l"]) - float(p["c"]))))
    return sum(trs) / len(trs)


def sweep(bars, lookback=20):
    """Sweep terkini: wick pecah high/low window tapi close balik dalam range."""
    if len(bars) < lookback + 2:
        return None
    win = bars[-(lookback + 2):-2]
    last = bars[-1]
    hh = max(float(b["h"]) for b in win)
    ll = min(float(b["l"]) for b in win)
    if float(last["h"]) > hh and float(last["c"]) < hh:
        return {"dir": "SELL", "level": hh}
    if float(last["l"]) < ll and float(last["c"]) > ll:
        return {"dir": "BUY", "level": ll}
    return None


def premium_discount(bars, price):
    """Kedudukan harga dalam range 50-bar: >0.7 premium, <0.3 discount."""
    if not bars:
        return 0.5
    hh = max(float(b["h"]) for b in bars[-50:])
    ll = min(float(b["l"]) for b in bars[-50:])
    if hh <= ll:
        return 0.5
    return (float(price) - ll) / (hh - ll)


def _ok(bars):
    return isinstance(bars, list) and len(bars) >= 10 and all(
        isinstance(b, dict) and all(k in b for k in ("o", "h", "l", "c")) for b in bars[-10:])


def ict_verdict(pair, side, entry, h1, m15):
    # Data tidak cukup -> PASS neutral (jangan veto buta).
    if not _ok(h1) or not _ok(m15):
        return {"verdict": "PASS", "trend": "UNKNOWN", "reasons": ["data tidak cukup"],
                "fvg_near": 0, "swept": None}
    side = str(side).upper()
    t_h1 = swing_trend(h1)
    t_m15 = swing_trend(m15)
    price = float(entry)
    fvgs = unfilled_fvg(m15, price)
    sup = [f for f in fvgs if f["dir"] == side]
    sw = sweep(m15)
    pd = premium_discount(h1, price)
    reasons = [f"H1:{t_h1} M15:{t_m15}", f"pos:{pd:.2f}",
               f"FVG sokong:{len(sup)}/{len(fvgs)}"]
    if sw:
        reasons.append(f"sweep:{sw['dir']}@{sw['level']}")
    # HARD_VETO: kedua-dua timeframe sehala lawan side.
    want = "UP" if side == "BUY" else "DOWN"
    if t_h1 != "RANGE" and t_m15 != "RANGE" and t_h1 == t_m15 and t_h1 != want:
        reasons.append("lawan-trend H1+M15 sehala")
        return {"verdict": "HARD_VETO", "trend": t_h1, "reasons": reasons,
                "fvg_near": len(sup), "swept": sw}
    # Ekstrem premium/discount lawan arah.
    if side == "BUY" and pd > 0.85 and t_h1 == "DOWN":
        reasons.append("beli di premium dalam downtrend")
        return {"verdict": "HARD_VETO", "trend": t_h1, "reasons": reasons,
                "fvg_near": len(sup), "swept": sw}
    if side == "SELL" and pd < 0.15 and t_h1 == "UP":
        reasons.append("jual di discount dalam uptrend")
        return {"verdict": "HARD_VETO", "trend": t_h1, "reasons": reasons,
                "fvg_near": len(sup), "swept": sw}
    # SOFT_VETO: sweep fresh lawan arah, atau tiada FVG sokong langsung.
    if sw and sw["dir"] != side:
        reasons.append("sweep fresh lawan arah")
        return {"verdict": "SOFT_VETO", "trend": t_m15, "reasons": reasons,
                "fvg_near": len(sup), "swept": sw}
    if not sup and fvgs:
        reasons.append("tiada FVG sokong arah")
        return {"verdict": "SOFT_VETO", "trend": t_m15, "reasons": reasons,
                "fvg_near": 0, "swept": sw}
    return {"verdict": "PASS", "trend": t_m15, "reasons": reasons,
            "fvg_near": len(sup), "swept": sw}
