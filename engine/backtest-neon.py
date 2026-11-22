#!/usr/bin/env python3
"""Head-to-head zero-lookahead backtest: Gemini 4 Neon vs DeepSeek v4.1 Flash.

Fixes the OHLC tuple indexing bug in older backtest scripts (rows are (ts,o,h,l,c)
so high=b[2], low=b[3]). Uses the exact live vision prompt & validate_verdict from
llm_analyst.py on real historical M15 bars from state/sq-bars.db.

Input   : 300 M15 bars up to T (active market only, flat bars filtered out)
Forward : 48 M15 bars (12 hours) after T; SL checked before TP1 if both hit same bar
Pairs   : XAUUSD, XAGUSD, BTCUSD (flagship TraderWatch pairs)
"""
import concurrent.futures
import importlib.util
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ai_model as M
import ict_filter as ICT
import llm_analyst as LA
import smc_filter as SMC

DB = HERE.parent / "state" / "sq-bars.db"
PAIRS = ["XAUUSD", "XAGUSD", "BTCUSD"]
TF = "M15"
GRAN = "M15"
N_BARS = 300
FORWARD = 48
POINTS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
MODELS = ["gemini-4-neon-medium", "deepseek-v4.1-flash"]


def load_rows(pair):
    db = sqlite3.connect(str(DB))
    r = db.execute(
        "SELECT ts, o, h, l, c FROM bars WHERE pair=? AND gran=? ORDER BY ts",
        (pair, GRAN),
    ).fetchall()
    db.close()
    return r


def to_bars(seg):
    return [
        (int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() * 1000), h, l, c)
        for t, o, h, l, c in seg
    ]


def is_active_window(seg):
    # Match llm_analyst.py's flat-market guard so we only test real active candles
    uniq = len({(round(b[2], 6), round(b[3], 6)) for b in seg[-60:]})
    return uniq >= 10


def select_indices(allr, points):
    valid = [i for i in range(N_BARS, len(allr) - FORWARD) if is_active_window(allr[i - N_BARS:i])]
    if len(valid) <= points:
        return valid
    step = len(valid) / points
    return [valid[int(k * step)] for k in range(points)]


def check_outcome(v, future):
    """Evaluate TP1 vs SL on future (ts,o,h,l,c) bars. Conservative: SL wins ties."""
    side = v.get("side")
    if side not in ("BUY", "SELL"):
        return "SKIP"
    sl, tp1 = v["sl"], v["tp1"]
    for _, _o, hi, lo, _c in future[:FORWARD]:
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


def build_live_vision_prompt(pair, bars, spread_pips, tf=TF):
    prof = LA.tf_profile(tf)
    price = bars[-1][3]
    atr = M.atr_s(bars)[-1]
    ctx = LA.resample(bars, prof["ctx_factor"])
    closes_ctx = [b[4] for b in ctx]
    trend = "FLAT"
    if len(closes_ctx) >= 50:
        e20c, e50c = M.ema(closes_ctx, 20), M.ema(closes_ctx, 50)
        trend = "UP" if e20c[-1] > e50c[-1] else ("DOWN" if e20c[-1] < e50c[-1] else "FLAT")
    tf_key = {"M5": "M15", "M15": "H1", "H1": "H4", "H4": "D1", "D1": "D1"}[tf]
    hi_bars = [{"h": b[2], "l": b[3], "c": b[4]} for b in ctx]
    lo_bars = [{"h": b[1], "l": b[2], "c": b[3]} for b in bars]
    s_hi = ICT.swing_trend(hi_bars, 3, 2)
    s_lo = ICT.swing_trend(lo_bars, 3, 2)
    bos = s_lo if s_lo != "RANGE" else s_hi
    rr_min = prof["rr1_min"]
    cl = [b[3] for b in bars]
    e20 = M.ema(cl, 20)[-1] if len(cl) >= 20 else price
    e50 = M.ema(cl, 50)[-1] if len(cl) >= 50 else price
    rsi14 = M.rsi_s(cl, 14)[-1]
    dec = 2 if (price > 100 or "JPY" in pair.upper()) else 5
    prompt = (
        "Look at this candlestick chart image and trade WITH the trend. "
        f"{pair} {tf}, current price {price:g}, spread {spread_pips:g} pips. "
        f"Higher TF ({tf_key}) trend: {trend}. Lower TF trend: {bos}. "
        f"Indicators (real bars): EMA20={e20:.{dec}f} EMA50={e50:.{dec}f} "
        f"RSI14={rsi14:.1f} ATR14={atr:.{dec}f}. "
        "If price makes higher highs and higher lows -> BUY. "
        "If lower highs and lower lows -> SELL. "
        "If choppy or sideways with no clear direction -> HOLD. "
        "Confidence is a PROBABILITY: 5=coin flip, 6=55-62%, 7=62-70%, "
        "8=70-78%, 9+=rare. If you can name 2+ real counter-arguments, HOLD. "
        "Entry at CURRENT price (instant market entry). "
        "SL just beyond nearest opposing swing (must exceed 3x spread). "
        "TP1 = exactly 1R from entry (risk x 1.0), TP2 = 1.5R. Keep TP1 CLOSE. "
        f"RR1 must be between {rr_min:g} and {rr_min+0.3:.2f} (TP1 near 1R). "
        'Reply ONLY: {"bias":"BUY"|"SELL"|"HOLD","sl":num,'
        '"tp1":num,"tp2":num,"confidence":0-10,"reason":"<6 words>"}'
    )
    return prompt, price, prof["rr1_min"]


def eval_point(model, pair, disp, pip, spread, ts, seg, fut):
    bars = to_bars(seg)
    prompt, price, rr1_min = build_live_vision_prompt(disp, bars, spread, tf=TF)
    t0 = time.time()
    try:
        raw = LA._call_vision(model, prompt, bars, disp, TF, 60)
        j = LA.parse_response(raw)
        verdict = LA.validate_verdict(j, price, pip, spread, rr1_min=rr1_min, pair_hint=disp)
    except ValueError as e:
        return {"ts": ts, "status": "REJECT", "err": str(e)[:120], "lat": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ts": ts, "status": "ERROR", "err": f"{type(e).__name__}: {str(e)[:100]}", "lat": round(time.time() - t0, 1)}
    lat = round(time.time() - t0, 1)
    side = verdict["side"]
    if side == "HOLD":
        return {"ts": ts, "status": "HOLD", "conf": verdict.get("conf"), "reason": verdict.get("reason"), "lat": lat}
    out = check_outcome(verdict, fut)
    r_val = verdict["rr1"] if out == "TP" else (-1.0 if out == "SL" else 0.0)
    return {
        "ts": ts,
        "status": out,
        "side": side,
        "entry": verdict["entry"],
        "sl": verdict["sl"],
        "tp1": verdict["tp1"],
        "rr1": verdict["rr1"],
        "conf": verdict["conf"],
        "r": r_val,
        "reason": verdict.get("reason"),
        "lat": lat,
    }


def summarize(rows_res):
    tp = sum(1 for x in rows_res if x["status"] == "TP")
    sl = sum(1 for x in rows_res if x["status"] == "SL")
    op = sum(1 for x in rows_res if x["status"] == "OPEN")
    hold = sum(1 for x in rows_res if x["status"] == "HOLD")
    rej = sum(1 for x in rows_res if x["status"] == "REJECT")
    err = sum(1 for x in rows_res if x["status"] == "ERROR")
    dec = tp + sl
    wr = round(100.0 * tp / dec, 1) if dec else 0.0
    tot_r = round(sum(x.get("r", 0.0) for x in rows_res if x["status"] in ("TP", "SL")), 2)
    exp_r = round(tot_r / dec, 3) if dec else 0.0
    avg_lat = round(sum(x["lat"] for x in rows_res) / len(rows_res), 1) if rows_res else 0.0
    avg_rr = round(
        sum(x["rr1"] for x in rows_res if x["status"] in ("TP", "SL", "OPEN")) /
        max(1, tp + sl + op), 2
    )
    return {
        "points": len(rows_res),
        "signals": tp + sl + op,
        "tp": tp,
        "sl": sl,
        "open": op,
        "hold": hold,
        "reject": rej,
        "error": err,
        "winrate_pct": wr,
        "avg_rr1": avg_rr,
        "expectancy_r": exp_r,
        "total_r": tot_r,
        "avg_lat_s": avg_lat,
    }


def main():
    t_all = time.time()
    # Pre-select identical timestamps for both models
    dataset = {}
    for pair in PAIRS:
        allr = load_rows(pair)
        idxs = select_indices(allr, POINTS)
        dataset[pair] = [(allr[i - 1][0], allr[i - N_BARS:i], allr[i:i + FORWARD]) for i in idxs]
        print(f"Prepared {pair}: {len(idxs)} active M15 points ({allr[idxs[0]-1][0]} -> {allr[idxs[-1]-1][0]})", flush=True)

    full = {"tf": TF, "points_per_pair": POINTS, "forward_bars": FORWARD, "models": {}}
    for model in MODELS:
        t0 = time.time()
        print(f"\n=== RUNNING MODEL: {model} ===", flush=True)
        m_out = {"pairs": {}, "all_results": []}
        for pair in PAIRS:
            disp = pair[:3] + "/" + pair[3:]
            pip = M.pip_of(disp)
            spread = SMC.SPREAD_PIPS.get(pair, SMC.DEFAULT_SPREAD_PIPS)
            jobs = dataset[pair]
            res_list = [None] * len(jobs)
            with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
                futs = {
                    ex.submit(eval_point, model, pair, disp, pip, spread, ts, seg, fut): idx
                    for idx, (ts, seg, fut) in enumerate(jobs)
                }
                done = 0
                for f in concurrent.futures.as_completed(futs):
                    idx = futs[f]
                    res_list[idx] = f.result()
                    done += 1
                    r = res_list[idx]
                    if done % 5 == 0 or done == len(jobs):
                        print(f"  [{model}] {pair} {done}/{len(jobs)} last={r['status']} ({r['lat']}s)", flush=True)
            s = summarize(res_list)
            m_out["pairs"][pair] = {"summary": s, "details": res_list}
            m_out["all_results"].extend(res_list)
            print(
                f"  >> {model} {pair:6}: sig={s['signals']} (TP={s['tp']} SL={s['sl']} OPEN={s['open']}) "
                f"HOLD={s['hold']} REJ={s['reject']} ERR={s['error']} | "
                f"WIN={s['winrate_pct']:5.1f}% EXP={s['expectancy_r']:+6.3f}R TOT={s['total_r']:+6.2f}R avgLat={s['avg_lat_s']}s",
                flush=True,
            )
        overall = summarize(m_out["all_results"])
        overall["elapsed_s"] = round(time.time() - t0, 1)
        m_out["overall"] = overall
        del m_out["all_results"]
        full["models"][model] = m_out
        print(
            f"\nTOTAL {model}: sig={overall['signals']} (TP={overall['tp']} SL={overall['sl']} OPEN={overall['open']}) "
            f"HOLD={overall['hold']} REJ={overall['reject']} ERR={overall['error']} | "
            f"WIN={overall['winrate_pct']:5.1f}% EXP={overall['expectancy_r']:+6.3f}R TOT={overall['total_r']:+6.2f}R "
            f"({overall['elapsed_s']}s)",
            flush=True,
        )

    out_path = HERE.parent / "research" / "backtest-neon-vs-deepseek.json"
    out_path.write_text(json.dumps(full, ensure_ascii=False, indent=2))
    print(f"\nSaved {out_path} (total {time.time() - t_all:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
