#!/usr/bin/env python3
"""Backtest prompt SIMPLE (ikut trend) dengan LLM vision sebenar.

Input  = 300 bar M5 sebelum T (tiada look-ahead)
Output = BUY/SELL/HOLD dari llm_analyst.analyze() (prompt ringkas sekarang)
Outcome = bar M5 selepas T: TP1 dulu = TP, SL dulu = SL, kedua satu bar = SL.
"""
import importlib.util
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


la = load("llm_analyst")
DB = HERE.parent / "state" / "sq-bars.db"
PAIRS = {"XAUUSD": 0.01, "EURUSD": 0.0001, "BTCUSD": 0.01}
N_BARS, FORWARD = 300, 48
POINTS = int(sys.argv[1]) if len(sys.argv) > 1 else 24


def rows(pair):
    db = sqlite3.connect(str(DB))
    r = db.execute("select ts,o,h,l,c from bars where pair=? and gran='M5' order by ts",
                   (pair,)).fetchall()
    db.close()
    return r


def to_bars(seg):
    return [(int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() * 1000),
             h, l, c) for t, o, h, l, c in seg]


def outcome(v, future):
    if v.get("side") not in ("BUY", "SELL"):
        return "SKIP"
    sl, tp1, side = v["sl"], v["tp1"], v["side"]
    for b in future[:FORWARD]:
        hi, lo = b[1], b[2]
        if side == "BUY":
            if lo <= sl:
                return "SL"
            if hi >= tp1:
                return "TP"
        else:
            if hi >= sl:
                return "SL"
            if lo <= tp1:
                return "TP"
    return "OPEN"


def run(pair, pip):
    allr = rows(pair)
    n = len(allr)
    step = max(1, (n - N_BARS - FORWARD) // POINTS)
    idxs = list(range(N_BARS, n - FORWARD, step))[:POINTS]
    r = {"pair": pair, "points": len(idxs), "buy": 0, "sell": 0, "hold": 0,
         "reject": 0, "tp": 0, "sl": 0, "open": 0, "rr": [], "conf": [],
         "signals": [], "secs": 0}
    t0 = time.time()
    for k, i in enumerate(idxs):
        seg, fut = allr[max(0, i - N_BARS):i], allr[i:i + FORWARD]
        ts = allr[i - 1][0]
        try:
            v = la.analyze(pair, to_bars(seg), pip, 2.5, tf="M5")
        except Exception as e:
            r["reject"] += 1
            print(f"  ERR {pair} {ts} {type(e).__name__}", flush=True)
            continue
        if not v:
            r["reject"] += 1
            continue
        if v.get("side") in ("BUY", "SELL"):
            key = "buy" if v["side"] == "BUY" else "sell"
            r[key] += 1
            r["rr"].append(v.get("rr1") or 0)
            r["conf"].append(v.get("conf") or 0)
            o = outcome(v, fut)
            r[{"TP": "tp", "SL": "sl", "OPEN": "open"}[o]] += 1
            r["signals"].append({"ts": ts, "side": v["side"], "conf": v.get("conf"),
                                 "rr": v.get("rr1"), "outcome": o,
                                 "reason": v.get("reason")})
            print(f"  {ts} {v['side']} conf={v.get('conf'):.2f} rr={v.get('rr1')} "
                  f"-> {o}  ({v.get('reason')})", flush=True)
        else:
            r["hold"] += 1
        print(f"  [{k+1}/{len(idxs)}] {pair} {v.get('side','?')} "
              f"({time.time()-t0:.0f}s)", flush=True)
    r["secs"] = round(time.time() - t0, 1)
    return r


def report(r):
    dec = r["tp"] + r["sl"]
    wr = 100 * r["tp"] / dec if dec else 0
    ar = sum(r["rr"]) / len(r["rr"]) if r["rr"] else 0
    ac = sum(r["conf"]) / len(r["conf"]) if r["conf"] else 0
    exp = (r["tp"] * ar - r["sl"]) / dec if dec else 0
    sig_day = (r["buy"] + r["sell"]) / 33
    print(f"\n{r['pair']:8}: pts={r['points']} BUY={r['buy']} SELL={r['sell']} "
          f"HOLD={r['hold']} REJ={r['reject']} | TP={r['tp']} SL={r['sl']} "
          f"OPEN={r['open']} | WIN={wr:5.1f}% avgRR={ar:4.2f} "
          f"conf={ac:4.2f} EXP={exp:+6.3f}R | ~{sig_day:.2f} signal/hari "
          f"({r['secs']}s)", flush=True)


if __name__ == "__main__":
    pairs = sys.argv[2:] or list(PAIRS)
    out = {}
    for p in pairs:
        out[p] = run(p, PAIRS[p])
        report(out[p])
    path = HERE.parent / "research" / "backtest-simple-trend.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nsaved: {path}", flush=True)
