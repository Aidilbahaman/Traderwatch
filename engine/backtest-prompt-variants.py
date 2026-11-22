#!/usr/bin/env python3
"""Backtest PROMPT AI — 3 varian dibandingkan pada data sama (no look-ahead).

Varian:
  A. simple   : prompt live sekarang ("trade with trend", confidence 0-10)
  B. calibrate: confidence ditakrif dalam terma win-rate + wajib senarai bukti lawan
  C. strict   : kalibrasi + tolak entry jika BOS=RANGE + gate conf>=55

Semua guna LLM VISION SEBENAR (deepseek-v4.1-flash) + validate_verdict enjin.
Outcome: bar M5 selepas T (TP1 dulu=TP, SL dulu=SL, serentak=SL).
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
ict = load("ict_filter")
DB = HERE.parent / "state" / "sq-bars.db"

PAIRS = {"BTCUSD": 0.01, "XAUUSD": 0.01, "EURUSD": 0.0001}
N_BARS, FORWARD = 300, 48
TFS = ["M5"]

PROMPT_A = (
    "Look at this candlestick chart image and trade WITH the trend. "
    "{pair} {tf}, current price {price:g}, spread {spread:g} pips. "
    "Higher TF ({tf_hi}) trend: {trend}. Lower TF trend: {bos}. "
    "If price makes higher highs and higher lows -> BUY. "
    "If lower highs and lower lows -> SELL. "
    "If choppy or sideways with no clear direction -> HOLD. "
    "Entry at CURRENT price (instant market entry). "
    "SL just beyond nearest opposing swing (must exceed 3x spread). "
    "TP at the next swing in your direction. RR1 >= {rr_min:g}. "
    'Reply ONLY: {{"bias":"BUY"|"SELL"|"HOLD","sl":num,"tp1":num,"tp2":num,'
    '"confidence":0-10,"reason":"<6 words>"}}'
)

PROMPT_B = (
    "You are a probability-calibrated trading analyst reading this chart image. "
    "{pair} {tf}, price {price:g}, spread {spread:g} pips. Higher-TF ({tf_hi}) trend: {trend}. "
    "{tf} structure: {bos}. ATR {atr:.4g}. "
    "\n\nCONFIDENCE IS A PROBABILITY, NOT A FEELING. Use this scale exactly:\n"
    "  0-3 = you'd be guessing (<45% win) -> must HOLD\n"
    "  4-5 = edge unclear (45-55%) -> must HOLD\n"
    "  6   = mild edge (55-62%)\n"
    "  7   = solid edge (62-70%)\n"
    "  8   = strong edge (70-78%)\n"
    "  9-10 = exceptional (78%+), RARE, needs 3+ independent confirmations\n"
    "\n\nBEFORE deciding, you MUST list counter-evidence in 'against'. "
    "If you cannot name at least one real counter-argument, you have not analysed properly. "
    "If 'against' contains 2+ real points, confidence MUST be 5 or lower (HOLD).\n"
    "\nRules: trade IN the structure direction. SL beyond the invalidating swing "
    "(>3x spread). TP at the next real liquidity level — do NOT put TP at the nearest "
    "tiny swing; require RR1 >= {rr_min:g}. If structure is choppy/RANGE with no clean "
    "break, HOLD.\n"
    'Reply ONLY compact JSON: {{"bias":"BUY"|"SELL"|"HOLD","confidence":0-10,'
    '"against":["..."],"sl":num,"tp1":num,"tp2":num,"reason":"<8 words>"}}'
)


def rows_for(pair, gran="M5"):
    db = sqlite3.connect(str(DB))
    r = db.execute("select ts,o,h,l,c from bars where pair=? and gran=? order by ts",
                   (pair, gran)).fetchall()
    db.close()
    return r


def to_bars(seg):
    return [(int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() * 1000),
             h, l, c) for t, o, h, l, c in seg]


def outcome(v, future):
    if v.get("side") not in ("BUY", "SELL"):
        return None
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


def structure_at(bars):
    lo = [{"h": b[1], "l": b[2], "c": b[3]} for b in bars]
    hi = [{"h": b[1], "l": b[2], "c": b[3]} for b in bars[::4]]
    s_lo = ict.swing_trend(lo, 3, 2)
    s_hi = ict.swing_trend(hi, 3, 2)
    return (s_lo if s_lo != "RANGE" else s_hi), s_hi


def ask(model_prompt, bars, pair, tf, price, spread, rr_min):
    content = la._call_vision(la.VISION_MODEL, model_prompt, bars, pair, tf, 60)
    return la.parse_response(content)


def run_variant(name, prompt_fn, pair, pip, pts, gate=False):
    allrows = rows_for(pair)
    n = len(allrows)
    step = max(1, (n - N_BARS - FORWARD) // pts)
    idxs = list(range(N_BARS, n - FORWARD, step))[:pts]
    res = {"name": name, "pair": pair, "pts": 0, "tp": 0, "sl": 0, "open": 0,
           "hold": 0, "reject": 0, "r": [], "conf": [], "sides": {"BUY": 0, "SELL": 0}}
    for i in idxs:
        seg, fut = allrows[max(0, i - N_BARS):i], allrows[i:i + FORWARD]
        bars = to_bars(seg)
        price = bars[-1][3]
        bos, trend = structure_at(bars)
        atr = la.M.atr_s(bars)[-1]
        tf = "M5"
        prof = la.tf_profile(tf)
        try:
            j = ask(prompt_fn(pair=pair, tf=tf, price=price, spread=2.5,
                              trend=trend, bos=bos, atr=atr, rr_min=prof["rr1_min"]),
                    bars, pair, tf, price, 2.5, prof["rr1_min"])
        except Exception as e:
            res["reject"] += 1
            msg = f"{type(e).__name__}: {str(e)[:110]}"
            res.setdefault("errs", {})
            res["errs"][msg] = res["errs"].get(msg, 0) + 1
            continue
        res["pts"] += 1
        bias = str(j.get("bias") or "").strip().upper()
        if bias not in ("BUY", "SELL"):
            res["hold"] += 1
            continue
        # GATE: tolak jika struktur RANGE (varian C)
        if gate and bos == "RANGE":
            res["hold"] += 1
            continue
        try:
            v = la.validate_verdict(j, price, pip, 2.5, rr1_min=prof["rr1_min"])
        except ValueError as e:
            res["reject"] += 1
            continue
        if v.get("side") not in ("BUY", "SELL"):
            res["hold"] += 1
            continue
        # gate confidence (varian B/C): <0.55 -> HOLD
        if gate and (v.get("conf") or 0) < 0.55:
            res["hold"] += 1
            continue
        res["sides"][v["side"]] += 1
        res["conf"].append(v.get("conf") or 0)
        o = outcome(v, fut)
        if o == "TP":
            res["tp"] += 1
            res["r"].append(v.get("rr1") or 1.0)
        elif o == "SL":
            res["sl"] += 1
            res["r"].append(-1.0)
        else:
            res["open"] += 1
    return res


def report(r):
    dec = r["tp"] + r["sl"]
    wr = 100 * r["tp"] / dec if dec else 0
    tot = sum(r["r"])
    avg = tot / len(r["r"]) if r["r"] else 0
    print(f"{r['name']:10} {r['pair']:7}: pts={r['pts']:3} HOLD={r['hold']:3} REJ={r['reject']:2} "
          f"B/S={r['sides']['BUY']}/{r['sides']['SELL']} TP={r['tp']:2} SL={r['sl']:2} "
          f"OPEN={r['open']:2} | win={wr:5.1f}% avgR={avg:+6.3f} totalR={tot:+7.2f}", flush=True)
    for msg, n in (r.get("errs") or {}).items():
        print(f"           x{n} {msg}", flush=True)


VARIANTS = [
    ("A-simple", lambda **k: PROMPT_A.format(
        pair=k["pair"], tf=k["tf"], price=k["price"], spread=k["spread"],
        tf_hi="M15", trend=k["trend"], bos=k["bos"], rr_min=k["rr_min"]), False),
    ("B-calib", lambda **k: PROMPT_B.format(
        pair=k["pair"], tf=k["tf"], price=k["price"], spread=k["spread"],
        tf_hi="M15", trend=k["trend"], bos=k["bos"], atr=k["atr"], rr_min=k["rr_min"]), False),
    ("C-strict", lambda **k: PROMPT_B.format(
        pair=k["pair"], tf=k["tf"], price=k["price"], spread=k["spread"],
        tf_hi="M15", trend=k["trend"], bos=k["bos"], atr=k["atr"], rr_min=k["rr_min"]), True),
]

if __name__ == "__main__":
    pts = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    pairs = sys.argv[2:] or ["BTCUSD"]
    print(f"=== BACKTEST {pts} titik/pair, {pairs} ===\n", flush=True)
    out = {}
    for vname, pfn, gate in VARIANTS:
        for p in pairs:
            t0 = time.time()
            r = run_variant(vname, pfn, p, PAIRS[p], pts, gate)
            r["secs"] = round(time.time() - t0, 1)
            out[f"{vname}:{p}"] = r
            report(r)
    path = HERE.parent / "research" / "backtest-prompt-variants.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"\nsaved {path}", flush=True)
