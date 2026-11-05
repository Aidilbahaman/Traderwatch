"""Market data adapter — MT5 read-only (spec Fasa 1).

Prinsip:
  - SEMUA timestamp dalam UTC (spec §2.1).
  - Candle dedup + gap detection + staleness check.
  - Tiada tulisan ke broker. Baca sahaja.
  - Sumber utama untuk backtest = fail JSON di state/mt5-hist (data broker
    sebenar, ~20000 bar M15 setiap pair). Live = Wine bridge mt5_read.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
HIST = REPO.parent / "state" / "mt5-hist"

# Timeframe -> minit (untuk gap detection)
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def available_symbols():
    """Pair yang ada fail sejarah M15."""
    if not HIST.exists():
        return []
    return sorted(p.name.replace("_M15.json", "")
                  for p in HIST.glob("*_M15.json"))


def _to_utc(ts):
    """Epoch saat -> datetime UTC (aware)."""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def load_bars(symbol, timeframe="M15", limit=None, hist_dir=None):
    """Baca candle dari fail sejarah. Pulangkan list dict UTC + OHLCV.

    Format output (satu bentuk untuk semua modul confluence):
        {"open_time": dt_utc, "open": f, "high": f, "low": f,
         "close": f, "tick_volume": int}
    """
    d = Path(hist_dir) if hist_dir else HIST
    f = d / f"{symbol}_{timeframe}.json"
    if not f.exists():
        return []
    raw = json.loads(f.read_text()).get("bars") or []
    if limit:
        raw = raw[-limit:]
    out = []
    for b in raw:
        try:
            out.append({
                "open_time": _to_utc(b["t"]),
                "open": float(b["o"]),
                "high": float(b["h"]),
                "low": float(b["l"]),
                "close": float(b["c"]),
                "tick_volume": int(b.get("v") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def dedupe(bars):
    """Buang candle duplicate open_time. Kekal yang TERAKHIR (correction)."""
    seen = {}
    for b in bars:
        seen[b["open_time"]] = b
    return [seen[k] for k in sorted(seen)]


def find_gaps(bars, timeframe="M15"):
    """Cari lubang masa. Pulangkan list (selepas, sebelum, minit_jarak).

    Weekend FX normal: gap > 24 jam antara Jumaat-Monday bukan ralat.
    Gap dikelaskan supaya penilaian kualiti tak salah tuduh.
    """
    if len(bars) < 2:
        return []
    step = TF_MINUTES.get(timeframe, 15)
    gaps = []
    for i in range(1, len(bars)):
        delta = (bars[i]["open_time"] - bars[i - 1]["open_time"]).total_seconds() / 60
        if delta > step * 1.5:
            # Klasifikasi: weekend (>=24j) dan rollover harian (<=4j, corak
            # tetap setiap hari) adalah NORMAL untuk instrumen tertentu.
            # XAUUSD/contoh: rehat 23:45->01:00 UTC tiap hari = 75 minit.
            from datetime import time as _t
            near_midnight = (bars[i - 1]["open_time"].hour >= 22
                             or bars[i]["open_time"].hour <= 2)
            gaps.append({
                "after": bars[i - 1]["open_time"].isoformat(),
                "before": bars[i]["open_time"].isoformat(),
                "minutes": round(delta, 1),
                "bars_missing": max(0, int(delta / step) - 1),
                "likely_weekend": delta >= 1440,
                "likely_rollover": delta <= 240 and near_midnight,
            })
    return gaps


def staleness_seconds(bars, now=None):
    """Berapa lama sejak candle terakhir TUTUP."""
    if not bars:
        return None
    now = now or datetime.now(timezone.utc)
    last = bars[-1]["open_time"]
    return round((now - last).total_seconds(), 1)


def health(symbol, timeframe="M15", now=None):
    """Data health untuk satu symbol (spec Fasa 1: data health endpoint).

    Pulangkan dict dengan status, bilangan bar, gap, staleness.
    """
    bars = dedupe(load_bars(symbol, timeframe))
    if not bars:
        return {"symbol": symbol, "timeframe": timeframe, "status": "UNAVAILABLE",
                "reason": "tiada fail data", "bars": 0}
    gaps = find_gaps(bars, timeframe)
    stale = staleness_seconds(bars, now)
    step = TF_MINUTES.get(timeframe, 15)
    # Stale threshold: 3x timeframe (toleransi sesi lembap / hujung minggu)
    stale_limit = step * 60 * 3
    status = "OK"
    reasons = []
    if stale is not None and stale > stale_limit:
        status = "STALE"
        reasons.append(f"candle terakhir {stale/3600:.1f} jam lalu")
    real_gaps = [g for g in gaps
                 if not g["likely_weekend"] and not g["likely_rollover"]]
    if real_gaps:
        if status == "OK":
            status = "DEGRADED"
        reasons.append(f"{len(real_gaps)} gap tidak normal")
    return {
        "symbol": symbol, "timeframe": timeframe, "status": status,
        "bars": len(bars),
        "first": bars[0]["open_time"].isoformat(),
        "last": bars[-1]["open_time"].isoformat(),
        "staleness_seconds": stale,
        "gaps_total": len(gaps),
        "gaps_non_weekend": len(real_gaps),
        "gaps_weekend": sum(1 for g in gaps if g["likely_weekend"]),
        "gaps_rollover": sum(1 for g in gaps if g["likely_rollover"]),
        "reasons": reasons,
    }


def health_all(timeframe="M15"):
    """Health semua symbol yang ada data."""
    return [health(s, timeframe) for s in available_symbols()]
