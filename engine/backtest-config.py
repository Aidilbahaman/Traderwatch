#!/usr/bin/env python3
"""Backtest KONFIGURASI SEMASA vs BASELINE LAMA — mekanikal, tiada LLM.

Tujuan: sahkan sama ada perubahan (RR cap, TP 1R, sesi, kualiti struktur)
benar-benar menambah expectancy pada 33 hari data sebenar.

Baseline lama   : TP pada swing jauh, RR>=1.5, semua sesi, tiada gate
Konfig sekarang : TP1 = tepat 1R, RR cap 1.6, SL swing penuh,
                  gate struktur (BOS mesti jelas), penalti sesi lemah

Tiada look-ahead: isyarat dari bar <= T, outcome dari bar > T.
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

N_BARS = 300
FORWARD = 72          # 6 jam keluar (M5)


def bars_of(pair):
    con = sqlite3.connect(str(DB))
    r = con.execute("select ts,o,h,l,c from bars where pair=? and gran='M5' order by ts",
                    (pair,)).fetchall()
    con.close()
    return r


def swings(seg):
    b = [{"h": x[2], "l": x[3], "c": x[4]} for x in seg]
    sw = ict._swings(b, 3)
    return ([v for _, v, _ in sw if v], [v for _, _, v in sw if v])


def hour_of(ts):
    try:
        return datetime.fromisoformat(ts).hour
    except Exception:
        return 12


WEAK = {"XAU": set(range(7, 17)), "EUR": set(range(0, 7)), "GBP": set(range(0, 7))}


def simulate(pair, mode):
    """mode: 'old' | 'new'. Kembalikan kiraan TP/SL dan R terkumpul."""
    rows = bars_of(pair)
    pip = 0.01 if pair in ("BTCUSD", "XAUUSD") else 0.0001
    stats = {"tp": 0, "sl": 0, "open": 0, "r": [], "n": 0}
    for i in range(N_BARS, len(rows) - FORWARD, 6):
        seg = rows[i - N_BARS:i]
        price = seg[-1][4]
        hs, ls = swings(seg)
        if len(hs) < 3 or len(ls) < 3:
            continue
        up = [x for x in hs if x > price]
        dn = [x for x in ls if x < price]
        if not up or not dn:
            continue

        # arah ikut 2 swing high terakhir (struktur)
        if hs[-1] < hs[-2]:
            side = "SELL"
        elif hs[-1] > hs[-2]:
            side = "BUY"
        else:
            continue

        if side == "SELL":
            sl = max(up)
            risk = sl - price
        else:
            sl = min(dn)
            risk = price - sl
        if risk <= 3 * 2.5 * pip:
            continue

        if mode == "new":
            # gate struktur: BOS mesti jelas (tidak RANGE)
            lo = [{"h": x[2], "l": x[3], "c": x[4]} for x in seg]
            bos = ict.swing_trend(lo, 3, 2)
            if bos == "RANGE":
                continue
            # penalti sesi: langkau sesi lemah
            if hour_of(seg[-1][0]) in WEAK.get(pair[:3], set()):
                continue
            tp1 = price - risk if side == "SELL" else price + risk   # tepat 1R
            rr = 1.0
        else:
            # lama: TP ke swing seterusnya (boleh jauh)
            if side == "SELL":
                tgt = [x for x in dn if (price - x) / risk >= 1.5]
                tp1 = max(tgt) if tgt else None
            else:
                tgt = [x for x in up if (x - price) / risk >= 1.5]
                tp1 = min(tgt) if tgt else None
            if tp1 is None:
                continue
            rr = abs(tp1 - price) / risk

        stats["n"] += 1
        fut = rows[i:i + FORWARD]
        res = None
        for b in fut:
            hi, lo_ = b[2], b[3]
            if side == "SELL":
                if hi >= sl:
                    res = "SL"
                    break
                if lo_ <= tp1:
                    res = "TP"
                    break
            else:
                if lo_ <= sl:
                    res = "SL"
                    break
                if hi >= tp1:
                    res = "TP"
                    break
        if res == "TP":
            stats["tp"] += 1
            stats["r"].append(rr)
        elif res == "SL":
            stats["sl"] += 1
            stats["r"].append(-1.0)
        else:
            stats["open"] += 1
    return stats


def rep(label, s):
    dec = s["tp"] + s["sl"]
    if not dec:
        print(f"  {label:8} n={s['n']:4}  tiada trade selesai")
        return {"n": s["n"], "decided": 0}
    wr = 100 * s["tp"] / dec
    tot = sum(s["r"])
    avg = tot / len(s["r"])
    print(f"  {label:8} n={s['n']:4} TP={s['tp']:3} SL={s['sl']:3} win={wr:5.1f}% "
          f"avgR={avg:+6.3f} totalR={tot:+8.2f}")
    return {"n": s["n"], "tp": s["tp"], "sl": s["sl"], "win": wr,
            "avgR": avg, "totalR": tot}


if __name__ == "__main__":
    pairs = sys.argv[1:] or ["BTCUSD", "XAUUSD", "EURUSD"]
    out = {}
    print("=== BACKTEST: konfigurasi LAMA vs SEKARANG (mekanikal, 33 hari) ===\n")
    for p in pairs:
        print(f"{p}:")
        old = simulate(p, "old")
        new = simulate(p, "new")
        out[p] = {"old": rep("LAMA", old), "new": rep("SEKARANG", new)}
        print()
    tot_old = sum(v["old"].get("totalR", 0) for v in out.values())
    tot_new = sum(v["new"].get("totalR", 0) for v in out.values())
    print(f"JUMLAH R — LAMA {tot_old:+.2f}  |  SEKARANG {tot_new:+.2f}  "
          f"(delta {tot_new - tot_old:+.2f})")
    # pecahan bulanan (konsistensi)
    print("\n=== KONSISTENSI BULANAN (konfig SEKARANG) ===")
    for p in pairs:
        rows = bars_of(p)
        pip = 0.01 if p in ("BTCUSD", "XAUUSD") else 0.0001
        mo = {}
        for i in range(N_BARS, len(rows) - FORWARD, 6):
            seg = rows[i - N_BARS:i]; price = seg[-1][4]
            hs, ls = swings(seg)
            if len(hs) < 3 or len(ls) < 3:
                continue
            up = [x for x in hs if x > price]; dn = [x for x in ls if x < price]
            if not up or not dn:
                continue
            side = "SELL" if hs[-1] < hs[-2] else ("BUY" if hs[-1] > hs[-2] else None)
            if not side:
                continue
            sl = max(up) if side == "SELL" else min(dn)
            risk = (sl - price) if side == "SELL" else (price - sl)
            if risk <= 3 * 2.5 * pip:
                continue
            lo = [{"h": x[2], "l": x[3], "c": x[4]} for x in seg]
            if ict.swing_trend(lo, 3, 2) == "RANGE":
                continue
            if hour_of(seg[-1][0]) in WEAK.get(p[:3], set()):
                continue
            tp1 = price - risk if side == "SELL" else price + risk
            d = mo.setdefault(seg[-1][0][:7], [0, 0, 0.0]); d[0] += 1
            res = None
            for b in rows[i:i + FORWARD]:
                hi, lo_ = b[2], b[3]
                if side == "SELL":
                    if hi >= sl: res = "SL"; break
                    if lo_ <= tp1: res = "TP"; break
                else:
                    if lo_ <= sl: res = "SL"; break
                    if hi >= tp1: res = "TP"; break
            if res == "TP": d[1] += 1; d[2] += 1.0
            elif res == "SL": d[2] -= 1.0
        print(f"  {p}: " + "  ".join(f"{k}={v[2]:+.1f}R" for k, v in sorted(mo.items())))

    path = HERE.parent / "research" / "backtest-config-compare.json"
    path.write_text(json.dumps(out, indent=1))
    print("saved", path)
