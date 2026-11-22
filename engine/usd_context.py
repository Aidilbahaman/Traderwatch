"""DXY (dollar index) sintetik + konteks USD untuk analyst.

Kenapa sintetik: broker (RoboForex) tiada symbol DXY, dan tiada feed yield.
DXY ICE sebenar = EUR 57.6% + JPY 13.6% + GBP 11.9% + CAD 9.1% + SEK 4.2% + CHF 3.6%.
Kita ada 4 daripada 6 (92.2% berat), cukup untuk arah & momentum USD.

Disahkan pada data 33 hari: korelasi return DXY-sintetik vs XAU = -0.307
(negatif seperti teori; EURUSD sahaja cuma +0.04, jadi bakul lebih bermakna).

Guna untuk XAU/XAG sahaja (logam paling dipacu USD). Pair forex lain sudah
mengandungi USD sendiri, jadi konteks baharu ini tidak menduplikasi maklumat.
"""
import math
import sqlite3
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "state" / "sq-bars.db"

WEIGHTS = {"EUR": 57.6, "GBP": 11.9, "JPY": 13.6, "CAD": 9.1}
_cache = {"at": 0.0, "val": None}
TTL = 300


def _closes(pair, n=200):
    try:
        con = sqlite3.connect(str(DB))
        rows = con.execute(
            "select ts,c from bars where pair=? and gran='M5' order by ts desc limit ?",
            (pair, n)).fetchall()
        con.close()
        return list(reversed(rows))
    except Exception:
        return []


def dxy_state():
    """Pulangkan {value, chg_1h, chg_6h, trend} atau None."""
    now = time.time()
    if _cache["val"] is not None and now - _cache["at"] < TTL:
        return _cache["val"]
    tot = sum(WEIGHTS.values())
    eu = _closes("EURUSD")
    gb = _closes("GBPUSD")
    jp = _closes("USDJPY")
    ca = _closes("USDCAD")
    if not (eu and gb and jp and ca):
        return None
    m = min(len(eu), len(gb), len(jp), len(ca))
    if m < 80:
        return None
    ts = [r[0] for r in eu[-m:]]
    idx = {}
    for name, rows in (("EUR", eu), ("GBP", gb), ("JPY", jp), ("CAD", ca)):
        d = {r[0]: r[1] for r in rows}
        if any(t not in d for t in ts):
            return None
        idx[name] = [d[t] for t in ts]

    def value(i):
        v = 1.0
        v *= idx["EUR"][i] ** (-WEIGHTS["EUR"] / tot)   # USD naik bila EUR turun
        v *= idx["GBP"][i] ** (-WEIGHTS["GBP"] / tot)
        v *= idx["JPY"][i] ** (WEIGHTS["JPY"] / tot)     # USD naik bila USDJPY naik
        v *= idx["CAD"][i] ** (WEIGHTS["CAD"] / tot)
        return v

    last = value(-1)
    i1h = max(0, len(ts) - 13)      # 12 x M5 = 1 jam
    i6h = max(0, len(ts) - 73)      # 72 x M5 = 6 jam
    chg1 = (last / value(i1h) - 1) * 100 if value(i1h) else 0
    chg6 = (last / value(i6h) - 1) * 100 if value(i6h) else 0
    # trend: banding purata 20 bar terkini vs 20 sebelumnya
    a = sum(value(i) for i in range(max(0, len(ts) - 20), len(ts))) / 20
    b = sum(value(i) for i in range(max(0, len(ts) - 40), max(1, len(ts) - 20))) / 20
    trend = "UP" if a > b * 1.0003 else ("DOWN" if a < b * 0.9997 else "FLAT")
    out = {"value": round(last, 3), "chg_1h": round(chg1, 3),
           "chg_6h": round(chg6, 3), "trend": trend}
    _cache.update(at=now, val=out)
    return out


def usd_context(pair):
    """Teks konteks USD untuk logam. None jika tidak berkaitan/tiada data."""
    p = str(pair).upper().replace("/", "")
    if not (p.startswith("XAU") or p.startswith("XAG")):
        return None
    d = dxy_state()
    if not d:
        return None
    direction = {"UP": "rising (USD strengthening → pressure on metals)",
                 "DOWN": "falling (USD weakening → tailwind for metals)",
                 "FLAT": "flat"}[d["trend"]]
    bias = ("Bias: BUY metals needs USD slowing/falling; SELL metals fits USD rising."
            if d["trend"] != "FLAT" else "USD flat — metals direction from chart structure.")
    return (f"USD index (DXY synthetic): {d['value']:.3f}, 1h {d['chg_1h']:+.2f}%, "
            f"6h {d['chg_6h']:+.2f}%, trend {direction}. {bias}")
