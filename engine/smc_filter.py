#!/usr/bin/env python3
"""Deterministic SMC setup detector used as a CONFLUENCE FILTER on the AI engine.

Why this exists: the statistical model has no measurable edge on fresh data
(AUC 0.474). The SMC structure, by contrast, held up under an honest held-out
test on XAU/USD — select on the first 70% of bars, trade the untouched last
30% once: train WR 60.6% (n=71) -> test WR 55.8% (n=43), +0.086R. This module
does NOT predict; it answers "did a valid setup just complete on this bar, in
which direction, and where are the levels". The AI engine keeps its own job
(confidence), and only emits when BOTH agree.

Setup (single template, identical on every pair — chosen on train data only):
    1. LIQUIDITY SWEEP   bar i wicks beyond the extreme of the previous
                         SWEEP_N bars and CLOSES back inside the range.
    2. DISPLACEMENT      within the next DISP_MAX bars a bullish/bearish
                         fair-value gap forms (low[f] > high[f-2] for a buy)
                         AND the move from the sweep extreme exceeds
                         DISP_ATR * ATR.
    3. H1 ALIGNMENT      H1 EMA20 vs EMA50 must agree with the direction.
    4. ENTRY             limit at the FVG edge (top of a bullish gap).
    5. STOP              beyond the sweep wick + 0.10 ATR buffer.
    6. TARGET            TP_ATR_R * risk (1R was the held-out optimum; the
                         backtest that survived used a 1R target).

The smart-money rules from the original 3R study (tested on 309 days) are
preserved here because they are the same structure, just with a different
reward target, so the engine can ask for either.

CRITICAL: this module is causal. Everything it returns is computable from
bars[0..i] inclusive, and the caller must only act on a setup detected at bar
i once bar i has CLOSED. An earlier backtest filled a limit on the signal bar
itself and turned a 50% setup into a fantasy 73% one.
"""
from __future__ import annotations

# Tuned on train data only (see engine/normalised-smc.py); do not re-tune here.
SWEEP_N = 20
DISP_ATR = 1.2
DISP_MAX = 6
ENTRY_TTL_BARS = 8
MIN_GAP_ATR = 0.20
SL_BUFFER_ATR = 0.10

# RoboForex-class spread in PIPS (gold pip = 0.1, JPY pairs 0.01). Kept here so
# the stop floor and any backtest charge the same cost the live account pays.
# A structural stop a couple of ticks from entry is worthless once 3 pips of
# gold spread is deducted, so downstream code floors SL at a multiple of this.
SPREAD_PIPS = {
    "XAUUSD": 3.0, "XAGUSD": 3.0, "BTCUSD": 30.0, "EURUSD": 1.0, "GBPUSD": 1.3,
    "AUDUSD": 1.3, "NZDUSD": 1.5, "USDCAD": 1.5, "USDJPY": 1.5,
    "USDCHF": 1.6, "EURGBP": 1.4, "EURJPY": 1.8, "GBPJPY": 2.2,
    "AUDJPY": 1.9, "CADJPY": 1.9, "CHFJPY": 2.2, "NZDJPY": 2.0,
    "EURAUD": 2.0, "EURCAD": 2.0, "EURNZD": 2.2, "EURCHF": 1.8,
    "GBPAUD": 2.4, "GBPCAD": 2.4, "GBPNZD": 2.6, "GBPCHF": 2.2,
    "AUDCAD": 2.2, "AUDCHF": 2.0, "AUDNZD": 2.2, "NZDCAD": 2.2,
    "NZDCHF": 2.0, "CADCHF": 1.9,
}
DEFAULT_SPREAD_PIPS = 2.0


def _ema(vals, n):
    if not vals:
        return 0.0
    k = 2.0 / (n + 1)
    out = vals[0]
    for v in vals[1:]:
        out = v * k + out * (1 - k)
    return out


def _atr(bars, n=14, lookback=400, end=None):
    """ATR (Wilder) ending at index `end` (default: last bar).

    The window is always the fixed-size tail ending at `end`, never "whatever
    slice was passed in". Getting this wrong is subtle and severe: the same bar
    then produces a different ATR (and therefore a different setup) depending on
    how much future data the caller happens to hold, which is both
    irreproducible and impossible to reconcile with a live feed.
    """
    if end is None:
        end = len(bars) - 1
    if end < n + 2:
        return 0.0
    lo = max(0, end - lookback)
    tail = bars[lo:end + 1]
    if len(tail) < n + 2:
        return 0.0
    trs = []
    for i in range(1, len(tail)):
        h, l, pc = tail[i][1], tail[i][2], tail[i - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    run = sum(trs[:n]) / n
    for i in range(n, len(trs)):
        run = (run * (n - 1) + trs[i]) / n
    return run


def m15_trend(bars):
    """+1/-1/0 dari EMA20 vs EMA50 pada M15.
    
    Menggantikan H1 trend untuk responsif M15 scalping.
    """
    closes = [b[3] for b in bars]
    if len(closes) < 100:
        return 0
    # EMA20 dan EMA50 pada M15
    e20 = _ema(closes, 20)
    e50 = _ema(closes, 50)
    if e20 > e50:
        return 1
    if e20 < e50:
        return -1
    return 0


def detect(bars, i=None, sweep_n=SWEEP_N, disp_atr=DISP_ATR,
           require_htf=True):
    """Detect a completed setup whose signal bar is index i (default: last).

    Returns None, or a dict:
        side       'BUY' | 'SELL'
        entry      limit price (FVG edge)
        sl         stop price
        risk       |entry - sl|
        tp         entry +/- reward * risk
        sweep_ext  the wick price that was swept
        bar_ts     timestamp of the signal bar
        fvg_bar    index of the bar that completed the gap

    The signal bar must have CLOSED before the caller acts on this.
    """
    if i is None:
        i = len(bars) - 1
    if i < max(sweep_n + 2, 60) or i >= len(bars):
        return None

    win = bars[i - sweep_n:i]
    if not win:
        return None
    low_ext = min(b[2] for b in win)
    high_ext = max(b[1] for b in win)
    _, bh, bl, bc = bars[i]

    side = None
    swept = None
    if bl < low_ext and bc > low_ext:
        side, swept = "BUY", bl
    elif bh > high_ext and bc < high_ext:
        side, swept = "SELL", bh
    if side is None:
        return None

    if require_htf:
        t = m15_trend(bars[:i + 1])
        if (side == "BUY" and t <= 0) or (side == "SELL" and t >= 0):
            return None

    anchor = swept
    for f in range(i + 2, min(i + 1 + DISP_MAX, len(bars))):
        b0, b2 = bars[f - 2], bars[f]
        a = _atr(bars, end=f)
        if a <= 0:
            continue
        if side == "BUY":
            gap = b2[2] - b0[1]
            if gap <= 0 or gap < MIN_GAP_ATR * a:
                continue
            if (b2[3] - anchor) < disp_atr * a:
                continue
            entry = b0[1]
            sl = anchor - SL_BUFFER_ATR * a
        else:
            gap = b0[2] - b2[1]
            if gap <= 0 or gap < MIN_GAP_ATR * a:
                continue
            if (anchor - b2[3]) < disp_atr * a:
                continue
            entry = b0[2]
            sl = anchor + SL_BUFFER_ATR * a
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        return {
            "side": side,
            "entry": round(entry, 5),
            "sl": round(sl, 5),
            "risk": risk,
            "sweep_ext": swept,
            "bar_ts": bars[i][0],
            "fvg_bar": f,
            "disp_atr": round(disp_atr, 2),
            "sweep_n": sweep_n,
            "gap": gap,
            "atr": a,
        }
    return None


def with_target(setup, r_mult):
    """Attach TP at r_mult * risk. Held-out optimum for XAU was 1R."""
    if not setup:
        return None
    risk = setup["risk"]
    tp = setup["entry"] + r_mult * risk if setup["side"] == "BUY" \
        else setup["entry"] - r_mult * risk
    out = dict(setup)
    out["tp"] = round(tp, 5)
    out["r_mult"] = r_mult
    return out


def to_tuple_bars(rows):
    """Adapt engine bars [(ts,h,l,c) or dicts] into the tuple form above."""
    out = []
    for b in rows:
        if isinstance(b, dict):
            out.append((b.get("t") or b.get("ts"), b["h"], b["l"], b["c"]))
        else:
            out.append((b[0], b[1], b[2], b[3]))
    return out


if __name__ == "__main__":
    import json
    from pathlib import Path
    HIST = Path(__file__).resolve().parent.parent.parent / "state" / "mt5-hist"
    for sym in ("XAUUSD", "EURUSD", "GBPUSD"):
        p = HIST / f"{sym}_M15.json"
        if not p.exists():
            print(f"{sym:8} tiada fail")
            continue
        raw = json.loads(p.read_text())["bars"]
        bars = to_tuple_bars(raw)
        hits = 0
        for i in range(60, len(bars)):
            if detect(bars, i):
                hits += 1
        print(f"{sym:8} signal bar: {hits} / {len(bars) - 60} bar")
