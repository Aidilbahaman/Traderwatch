#!/usr/bin/env python3
"""Backtest RANGE TRADING vs TREND-ONLY pada data sebenar.

Hipotesis: dalam market range 94% masa, tunggu trend = 6% peluang.
Range trading (buy support, sell resistance) sepatutnya bagi lebih entry
DAN masih untung — kalau betul.

Ujian:
  A. trend-only   : hanya trade bila struktur UP/DOWN (cara sekarang)
  B. range-bounce : pada RANGE, BUY jika harga dekat support (bawah 30% julat),
                    SELL jika dekat resistance (atas 70%); HOLD jika tengah
  C. range-wide   : sama tapi threshold 40%/60% (lebih banyak entry)

Semua: TP 1R, SL di sebalik swing, keluar max 6 jam.
"""
import importlib.util
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "state" / "sq-bars.db"


def load(n):
    sp = importlib.util.spec_from_file_location(n, HERE / f"{n}.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


ict = load("ict_filter")

N_BARS, FORWARD, STEP = 300, 72, 6
PAIRS = ["BTCUSD", "XAUUSD", "EURUSD"]


def rows_of(pair):
    con = sqlite3.connect(str(DB))
    r = con.execute("select ts,o,h,l,c from bars where pair=? and gran='M5' order by ts",
                    (pair,)).fetchall()
    con.close()
    return r


def swings(seg):
    b = [{"h": x[2], "l": x[3], "c": x[4]} for x in seg]
    sw = ict._swings(b, 3)
    return [v for _, v, _ in sw if v], [v for _, _, v in sw if v]


def run(pair, mode, lo_th=0.30, hi_th=0.70, rr=1.0):
    rows = rows_of(pair)
    pip = 0.01 if pair in ("BTCUSD", "XAUUSD") else 0.0001
    st = {"n": 0, "tp": 0, "sl": 0, "open": 0, "r": []}
    for i in range(N_BARS, len(rows) - FORWARD, STEP):
        seg = rows[i - N_BARS:i]
        price = seg[-1][4]
        hs, ls = swings(seg)
        if len(hs) < 3 or len(ls) < 3:
            continue
        b = [{"h": x[2], "l": x[3], "c": x[4]} for x in seg]
        trend = ict.swing_trend(b, 3, 2)
        up = [x for x in hs if x > price]
        dn = [x for x in ls if x < price]
        if not up or not dn:
            continue

        side = None
        if mode == "trend":
            if trend == "UP":
                side = "BUY"
            elif trend == "DOWN":
                side = "SELL"
        else:  # range-bounce / range-wide
            if trend == "RANGE":
                # posisi dalam julat 40 bar
                win = seg[-40:]
                rhi = max(x[2] for x in win)
                rlo = min(x[3] for x in win)
                span = (rhi - rlo) or 1e-9
                pos = (price - rlo) / span
                if pos <= lo_th:
                    side = "BUY"     # dekat support
                elif pos >= hi_th:
                    side = "SELL"    # dekat resistance
            else:
                # trend jelas -> ikut trend juga
                side = "BUY" if trend == "UP" else "SELL"

        if not side:
            continue
        if side == "BUY":
            sl = min(dn)
            risk = price - sl
        else:
            sl = max(up)
            risk = sl - price
        if risk <= 3 * 2.5 * pip:
            continue
        tp = price + risk * rr if side == "BUY" else price - risk * rr

        st["n"] += 1
        res = None
        for br in rows[i:i + FORWARD]:
            hi2, lo2 = br[2], br[3]
            if side == "BUY":
                if lo2 <= sl:
                    res = "SL"
                    break
                if hi2 >= tp:
                    res = "TP"
                    break
            else:
                if hi2 >= sl:
                    res = "SL"
                    break
                if lo2 <= tp:
                    res = "TP"
                    break
        if res == "TP":
            st["tp"] += 1
            st["r"].append(rr)
        elif res == "SL":
            st["sl"] += 1
            st["r"].append(-1.0)
        else:
            st["open"] += 1
    return st


def rep(label, s):
    dec = s["tp"] + s["sl"]
    if not dec:
        print(f"  {label:14} n={s['n']:4}  tiada trade selesai")
        return {"n": s["n"], "decided": 0, "totalR": 0}
    wr = 100 * s["tp"] / dec
    tot = sum(s["r"])
    print(f"  {label:14} n={s['n']:4}  TP={s['tp']:3} SL={s['sl']:3}  "
          f"win={wr:5.1f}%  totalR={tot:+7.2f}  avgR={tot/dec:+.3f}")
    return {"n": s["n"], "tp": s["tp"], "sl": s["sl"], "win": round(wr, 1),
            "totalR": round(tot, 2)}


if __name__ == "__main__":
    pairs = sys.argv[1:] or PAIRS
    out = {}
    print("=== RANGE TRADING vs TREND-ONLY (TP 1R, SL swing, 6j) ===\n")
    for p in pairs:
        print(f"{p}:")
        out[p] = {
            "trend": rep("A trend-only", run(p, "trend")),
            "range30": rep("B range 30/70", run(p, "range", 0.30, 0.70)),
            "range40": rep("C range 40/60", run(p, "range", 0.40, 0.60)),
        }
        print()
    tt = {k: sum(v[k]["totalR"] for v in out.values()) for k in ("trend", "range30", "range40")}
    print(f"JUMLAH R — trend {tt['trend']:+.2f} | range30 {tt['range30']:+.2f} | range40 {tt['range40']:+.2f}")
    path = HERE.parent / "research" / "backtest-range-trading.json"
    path.write_text(json.dumps(out, indent=1))
    print("saved", path)
