#!/usr/bin/env python3
"""Zero-lookahead Multi-Timeframe Backtest (M5, M15, H1, H4, D1):
Part 1: Full-history 50/50 walk-forward validation of quant_engine across all 9 live pairs.
Part 2: Live end-to-end Gemini 4 Neon (gemini-4-neon-high) visual confirmation backtest
        across all 5 timeframes on strictly out-of-sample (second-half) setups.

Zero look-ahead:
  * At bar index `i`, only bars[i - N + 1 : i + 1] are visible to quant_engine,
    ICT structure, vision_chart, and Gemini 4 Neon.
  * Future evaluation starts strictly at bar `i + 1`.
  * Conservative tie-break: SL is checked BEFORE TP1 on every bar.
"""
import concurrent.futures
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ai_model as M
import ict_filter as ICT
import llm_analyst as LA
import quant_engine as QE
import smc_filter as SMC

DATA_PATH = Path("/tmp/tw_research_bars_9p.json")
OUT_PATH = HERE.parent / "research" / "backtest-mtf-neon.json"
TFS = ("M5", "M15", "H1", "H4", "D1")
MAX_HOLD = {"M5": 96, "M15": 96, "H1": 72, "H4": 48, "D1": 30}
BARS_PER_DAY = {"M5": 288, "M15": 96, "H1": 24, "H4": 6, "D1": 1}
NEON_MODEL = sys.argv[1] if len(sys.argv) > 1 else LA.VISION_MODEL
NEON_PER_TF = int(sys.argv[2]) if len(sys.argv) > 2 else 10
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 5


def check_outcome(side, sl_p, tp1_p, ind, i, max_h, sp=0.0):
    """Evaluate TP1 vs SL strictly on bars > i. Conservative SL-first tie-break."""
    n = ind["n"]
    end = min(n, i + 1 + max_h)
    for j in range(i + 1, end):
        hi, lo = ind["h"][j], ind["l"][j]
        if side == "BUY":
            if lo <= sl_p + sp:
                return "SL", j
            if hi >= tp1_p + sp:
                return "TP", j
        else:
            if hi + sp >= sl_p:
                return "SL", j
            if lo + sp <= tp1_p:
                return "TP", j
    return "OPEN", min(n - 1, end - 1)


def run_part1_quant(data, pairs_subset=None, spread_in_fill=True):
    """Full 50/50 IS/OOS walk-forward evaluation of quant_engine on exact live 4-tuples
    with mark-to-market accounting on any OPEN trades at horizon end."""
    pairs = pairs_subset or list(data.keys())
    out = {}
    for tf in TFS:
        out[tf] = {}
        mh = MAX_HOLD[tf]
        bpd = BARS_PER_DAY[tf]
        cfg = QE.TF_CONFIG[tf]
        for split in ("IS", "OOS", "ALL"):
            tp = sl = op = 0
            r_sum = 0.0
            mtm_sum = 0.0
            tot_bars = 0
            per_pair = {}
            for p in pairs:
                raw_bars = data[p].get(tf) or []
                if len(raw_bars) < cfg["min_bars"] + 20:
                    continue
                # Match live analyze-api.py / signal-engine-ai.py 4-tuple (ts, h, l, c)
                bars4 = [(b[0], float(b[2]), float(b[3]), float(b[4])) for b in raw_bars]
                disp = p[:3] + "/" + p[3:]
                pip = M.pip_of(disp)
                sp_pips = SMC.SPREAD_PIPS.get(p, SMC.DEFAULT_SPREAD_PIPS)
                sp = sp_pips * pip if spread_in_fill else 0.0
                ind = QE.compute_series(bars4)
                n = ind["n"]
                start = cfg["min_bars"]
                mid = start + (n - start) // 2
                s_i, e_i = (start, mid) if split == "IS" else ((mid, n - 2) if split == "OOS" else (start, n - 2))
                tot_bars += max(0, e_i - s_i)
                ptp = psl = pop = 0
                pr = 0.0
                pmtm = 0.0
                busy = -1
                for i in range(s_i, e_i):
                    if i <= busy:
                        continue
                    sig = QE.scan_index(ind, i, tf, pip, sp_pips)
                    if not sig["side"]:
                        continue
                    res, exit_j = check_outcome(sig["side"], sig["sl"], sig["tp1"], ind, i, mh, sp=sp)
                    busy = exit_j
                    if res == "TP":
                        ptp += 1; pr += sig["rr1"]
                    elif res == "SL":
                        psl += 1; pr -= 1.0
                    else:
                        pop += 1
                        ce = ind["c"][exit_j]
                        if sig["side"] == "BUY":
                            pmtm += (ce - (sig["entry"] + sp)) / sig["risk"]
                        else:
                            pmtm += (sig["entry"] - (ce + sp)) / sig["risk"]
                tp += ptp; sl += psl; op += pop; r_sum += pr; mtm_sum += pmtm
                pdec = ptp + psl
                per_pair[p] = {
                    "trades": ptp + psl + pop, "tp": ptp, "sl": psl, "open": pop,
                    "wr": round(100.0 * ptp / pdec, 1) if pdec else 0.0,
                    "exp_r": round(pr / pdec, 3) if pdec else 0.0,
                    "total_r_mtm": round(pr + pmtm, 2),
                }
            dec = tp + sl
            tot_n = tp + sl + op
            days = (tot_bars / max(1, len(pairs))) / bpd
            out[tf][split] = {
                "pairs": len(pairs),
                "trades": tot_n,
                "tp": tp, "sl": sl, "open": op,
                "winrate_pct": round(100.0 * tp / dec, 1) if dec else 0.0,
                "expectancy_r": round(r_sum / dec, 3) if dec else 0.0,
                "total_r": round(r_sum, 2),
                "open_mtm_r": round(mtm_sum, 2),
                "total_r_with_mtm": round(r_sum + mtm_sum, 2),
                "trades_per_day": round(tot_n / max(days, 0.1), 2),
                "per_pair": per_pair,
            }
    return out


def to_4tuple(seg):
    out = []
    for t, _o, h, l, c in seg:
        d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append((int(d.timestamp() * 1000), float(h), float(l), float(c)))
    return out


def collect_oos_candidates(data, tf, target_n):
    """Collect evenly spaced non-overlapping OOS quant setups across 6 diverse pairs (metals, crypto, FX)."""
    pairs = ["XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD", "AUDUSD"]
    cfg = QE.TF_CONFIG[tf]
    mh = MAX_HOLD[tf]
    cands = []
    for p in pairs:
        raw_bars = data[p][tf]
        bars4 = [(b[0], float(b[2]), float(b[3]), float(b[4])) for b in raw_bars]
        disp = p[:3] + "/" + p[3:]
        pip = M.pip_of(disp)
        sp_pips = SMC.SPREAD_PIPS.get(p, SMC.DEFAULT_SPREAD_PIPS)
        ind = QE.compute_series(bars4)
        n = ind["n"]
        start = cfg["min_bars"]
        mid = start + (n - start) // 2
        busy = -1
        pair_hits = []
        for i in range(max(mid, 250 if tf in ("M5", "M15") else 120), n - min(mh, 20)):
            if i <= busy:
                continue
            sig = QE.scan_index(ind, i, tf, pip, sp_pips)
            if not sig["side"]:
                continue
            res_mid, ej = check_outcome(sig["side"], sig["sl"], sig["tp1"], ind, i, mh, sp=0.0)
            res_sp, _ = check_outcome(sig["side"], sig["sl"], sig["tp1"], ind, i, mh, sp=sp_pips * pip)
            busy = ej
            if res_mid in ("TP", "SL"):
                pair_hits.append((p, disp, pip, sp_pips, i, sig, res_mid, res_sp))
        # Evenly sample from this pair
        want = max(1, (target_n + len(pairs) - 1) // len(pairs))
        if len(pair_hits) <= want:
            chosen = pair_hits
        else:
            step = len(pair_hits) / want
            chosen = [pair_hits[int(k * step)] for k in range(want)]
        cands.extend(chosen)
    return cands[:target_n]


def eval_neon_point(data, tf, cand):
    """Run exact live Quant + Gemini 4 Neon Vision pipeline on a single OOS bar."""
    p, disp, pip, sp_pips, idx, _sig_full, q_mid, q_sp = cand
    raw_bars = data[p][tf]
    win_start = max(0, idx - 299)
    seg = raw_bars[win_start:idx + 1]
    bars = to_4tuple(seg)
    ts = raw_bars[idx][0]

    # Run quant_engine strictly on the 300-bar window (exactly as live analyze-api.py does!)
    q = QE.scan(bars, disp, tf, pip, sp_pips)
    if not q or not q.get("side"):
        return {"pair": p, "tf": tf, "ts": ts, "status": "NO_QUANT", "lat": 0.0}

    prof = LA.tf_profile(tf)
    price = bars[-1][3]
    atr = M.atr_s(bars)[-1]
    ctx = LA.resample(bars, prof["ctx_factor"])
    closes_ctx = [b[4] for b in ctx]
    trend = "FLAT"
    if len(closes_ctx) >= 50:
        e20c, e50c = M.ema(closes_ctx, 20), M.ema(closes_ctx, 50)
        trend = "UP" if e20c[-1] > e50c[-1] else ("DOWN" if e20c[-1] < e50c[-1] else "FLAT")
    tf_key = {"M5": "M15", "M15": "H1", "H1": "H4", "H4": "D1", "D1": "W1"}[tf]
    hi_bars = [{"h": b[2], "l": b[3], "c": b[4]} for b in ctx]
    lo_bars = [{"h": b[1], "l": b[2], "c": b[3]} for b in bars]
    s_hi = ICT.swing_trend(hi_bars, 3, 2)
    s_lo = ICT.swing_trend(lo_bars, 3, 2)
    bos = s_lo if s_lo != "RANGE" else s_hi
    choch = (s_hi != "RANGE" and s_lo != "RANGE" and s_lo != s_hi)
    cl = [b[3] for b in bars]
    e20 = M.ema(cl, 20)[-1] if len(cl) >= 20 else price
    e50 = M.ema(cl, 50)[-1] if len(cl) >= 50 else price
    rsi14 = M.rsi_s(cl, 14)[-1]
    dec = 2 if price > 500 else (3 if pip >= 0.01 else 5)

    prompt = LA.build_quant_vision_prompt(
        disp, tf, price, sp_pips, tf_key, trend, bos,
        e20, e50, rsi14, atr, dec, prof, q, market_ctx="", held=None,
    )
    t0 = time.time()
    neon_models = [NEON_MODEL] + (["gemini-4-neon-medium"] if NEON_MODEL != "gemini-4-neon-medium" else [])
    used_model = NEON_MODEL
    last_err = None
    j = None
    for mdl in neon_models:
        try:
            raw = LA._call_vision(mdl, prompt, bars, disp, tf, 60, bos=bos, choch=choch, levels=q)
            j = LA.parse_response(raw)
            used_model = mdl
            break
        except Exception as e:
            last_err = e
            continue
    if j is None:
        return {"pair": p, "tf": tf, "ts": ts, "status": "ERROR",
                "err": f"{type(last_err).__name__}: {str(last_err)[:100]}",
                "q_mid": q_mid, "q_sp": q_sp, "q_rr1": q["rr1"], "lat": round(time.time() - t0, 1)}
    try:
        v_bias = str(j.get("bias", "")).strip().upper()
        if v_bias in ("BUY", "SELL") and v_bias != q["side"]:
            verdict = {"side": "HOLD", "conf": 0.4, "reason": f"conflict {q['side']}!={v_bias}"}
        else:
            verdict = LA.validate_verdict(
                j, price, pip, sp_pips,
                rr1_min=prof["rr1_min"], rr1_max=prof["rr1_max"], pair_hint=disp,
            )
    except ValueError as e:
        return {"pair": p, "tf": tf, "ts": ts, "status": "REJECT", "err": str(e)[:120],
                "model": used_model, "q_mid": q_mid, "q_sp": q_sp, "q_rr1": q["rr1"],
                "lat": round(time.time() - t0, 1)}

    lat = round(time.time() - t0, 1)
    if verdict["side"] == "HOLD":
        return {"pair": p, "tf": tf, "ts": ts, "status": "VETO_HOLD",
                "model": used_model, "q_side": q["side"], "q_setup": q["setup_label"],
                "q_mid": q_mid, "q_sp": q_sp, "q_rr1": q["rr1"],
                "reason": verdict.get("reason"), "lat": lat}

    # Evaluate Neon's exact approved levels strictly forward on raw_bars[idx+1:]
    ind_full = QE.compute_series([(b[0], float(b[2]), float(b[3]), float(b[4])) for b in raw_bars])
    out_mid, _ = check_outcome(verdict["side"], verdict["sl"], verdict["tp1"], ind_full, idx, MAX_HOLD[tf], sp=0.0)
    out_sp, _ = check_outcome(verdict["side"], verdict["sl"], verdict["tp1"], ind_full, idx, MAX_HOLD[tf], sp=sp_pips * pip)
    r_mid = verdict["rr1"] if out_mid == "TP" else (-1.0 if out_mid == "SL" else 0.0)
    r_sp = verdict["rr1"] if out_sp == "TP" else (-1.0 if out_sp == "SL" else 0.0)
    return {
        "pair": p, "tf": tf, "ts": ts, "status": out_mid, "status_sp": out_sp,
        "model": used_model, "side": verdict["side"], "q_setup": q["setup_label"],
        "entry": verdict["entry"], "sl": verdict["sl"], "tp1": verdict["tp1"],
        "rr1": verdict["rr1"], "conf": verdict["conf"],
        "r_mid": r_mid, "r_sp": r_sp, "q_mid": q_mid, "q_sp": q_sp,
        "reason": verdict.get("reason"), "lat": lat,
    }


def summarize_neon(rows):
    app = [x for x in rows if x["status"] in ("TP", "SL", "OPEN")]
    veto = [x for x in rows if x["status"] == "VETO_HOLD"]
    rej = [x for x in rows if x["status"] == "REJECT"]
    err = [x for x in rows if x["status"] == "ERROR"]

    tp_m = sum(1 for x in app if x["status"] == "TP")
    sl_m = sum(1 for x in app if x["status"] == "SL")
    dec_m = tp_m + sl_m
    tot_rm = round(sum(x["r_mid"] for x in app if x["status"] in ("TP", "SL")), 2)

    tp_s = sum(1 for x in app if x.get("status_sp") == "TP")
    sl_s = sum(1 for x in app if x.get("status_sp") == "SL")
    dec_s = tp_s + sl_s
    tot_rs = round(sum(x["r_sp"] for x in app if x.get("status_sp") in ("TP", "SL")), 2)

    veto_tp = sum(1 for x in veto if x.get("q_mid") == "TP")
    veto_dec = sum(1 for x in veto if x.get("q_mid") in ("TP", "SL"))

    return {
        "tested_setups": len(rows),
        "approved": len(app),
        "veto_hold": len(veto),
        "reject": len(rej),
        "error": len(err),
        "tp_mid": tp_m, "sl_mid": sl_m,
        "wr_mid_pct": round(100.0 * tp_m / dec_m, 1) if dec_m else 0.0,
        "exp_mid_r": round(tot_rm / dec_m, 3) if dec_m else 0.0,
        "tot_mid_r": tot_rm,
        "tp_sp": tp_s, "sl_sp": sl_s,
        "wr_sp_pct": round(100.0 * tp_s / dec_s, 1) if dec_s else 0.0,
        "exp_sp_r": round(tot_rs / dec_s, 3) if dec_s else 0.0,
        "tot_sp_r": tot_rs,
        "veto_would_have_wr_pct": round(100.0 * veto_tp / veto_dec, 1) if veto_dec else None,
        "avg_lat_s": round(sum(x.get("lat", 0.0) for x in rows) / max(1, len(rows)), 1),
    }


def main():
    t_all = time.time()
    data = json.loads(DATA_PATH.read_text())
    print("=== PART 1: FULL 9-PAIR 5-TF WALK-FORWARD QUANT ENGINE ===", flush=True)
    p1_sp = run_part1_quant(data, spread_in_fill=True)
    p1_mid = run_part1_quant(data, spread_in_fill=False)
    p1_flag_sp = run_part1_quant(data, pairs_subset=["XAUUSD", "XAGUSD", "BTCUSD"], spread_in_fill=True)
    p1_flag_mid = run_part1_quant(data, pairs_subset=["XAUUSD", "XAGUSD", "BTCUSD"], spread_in_fill=False)

    print("\n[All 9 live pairs — SPREAD-ADJUSTED fills, conservative SL-first]")
    for tf in TFS:
        a = p1_sp[tf]["ALL"]; o = p1_sp[tf]["OOS"]
        print(f"  {tf:3} | ALL: tr={a['trades']:4} WR={a['winrate_pct']:5.1f}% EXP={a['expectancy_r']:+6.3f}R TOT={a['total_r']:+7.2f}R ({a['trades_per_day']:5.2f}/day) "
              f"| OOS: tr={o['trades']:4} WR={o['winrate_pct']:5.1f}% EXP={o['expectancy_r']:+6.3f}R TOT={o['total_r']:+7.2f}R", flush=True)

    print("\n[All 9 live pairs — MID-TO-MID fills (paper league / backtest-neon convention)]")
    for tf in TFS:
        a = p1_mid[tf]["ALL"]; o = p1_mid[tf]["OOS"]
        print(f"  {tf:3} | ALL: tr={a['trades']:4} WR={a['winrate_pct']:5.1f}% EXP={a['expectancy_r']:+6.3f}R TOT={a['total_r']:+7.2f}R ({a['trades_per_day']:5.2f}/day) "
              f"| OOS: tr={o['trades']:4} WR={o['winrate_pct']:5.1f}% EXP={o['expectancy_r']:+6.3f}R TOT={o['total_r']:+7.2f}R", flush=True)

    print("\n[3 Flagship pairs (XAU/XAG/BTC) — SPREAD-ADJUSTED vs MID]")
    for tf in TFS:
        s = p1_flag_sp[tf]["ALL"]; m = p1_flag_mid[tf]["ALL"]
        print(f"  {tf:3} | SPREAD: tr={s['trades']:4} WR={s['winrate_pct']:5.1f}% EXP={s['expectancy_r']:+6.3f}R TOT={s['total_r']:+6.2f}R "
              f"| MID: tr={m['trades']:4} WR={m['winrate_pct']:5.1f}% EXP={m['expectancy_r']:+6.3f}R TOT={m['total_r']:+6.2f}R", flush=True)

    print(f"\n=== PART 2: LIVE END-TO-END {NEON_MODEL} VISION BACKTEST ({NEON_PER_TF} OOS setups/TF) ===", flush=True)
    neon_by_tf = {}
    all_neon_rows = []
    for tf in TFS:
        cands = collect_oos_candidates(data, tf, NEON_PER_TF)
        rows = [None] * len(cands)
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(eval_neon_point, data, tf, c): i for i, c in enumerate(cands)}
            for f in concurrent.futures.as_completed(futs):
                i = futs[f]
                rows[i] = f.result()
        s = summarize_neon(rows)
        neon_by_tf[tf] = {"summary": s, "details": rows}
        all_neon_rows.extend(rows)
        print(
            f"  {tf:3} | tested={s['tested_setups']:2} app={s['approved']:2} veto={s['veto_hold']:2} "
            f"rej={s['reject']} err={s['error']} | "
            f"MID: WR={s['wr_mid_pct']:5.1f}% EXP={s['exp_mid_r']:+6.3f}R ({s['tot_mid_r']:+5.2f}R) | "
            f"SP: WR={s['wr_sp_pct']:5.1f}% EXP={s['exp_sp_r']:+6.3f}R ({s['tot_sp_r']:+5.2f}R) | "
            f"vetoWR={s['veto_would_have_wr_pct']}% avgLat={s['avg_lat_s']}s",
            flush=True,
        )

    neon_overall = summarize_neon(all_neon_rows)
    print(
        f"\nTOTAL LIVE {NEON_MODEL} (5 TFs): tested={neon_overall['tested_setups']} "
        f"app={neon_overall['approved']} veto={neon_overall['veto_hold']} "
        f"rej={neon_overall['reject']} err={neon_overall['error']} | "
        f"MID: WR={neon_overall['wr_mid_pct']}% EXP={neon_overall['exp_mid_r']:+.3f}R ({neon_overall['tot_mid_r']:+.2f}R) | "
        f"SP: WR={neon_overall['wr_sp_pct']}% EXP={neon_overall['exp_sp_r']:+.3f}R ({neon_overall['tot_sp_r']:+.2f}R) | "
        f"vetoWR={neon_overall['veto_would_have_wr_pct']}% avgLat={neon_overall['avg_lat_s']}s",
        flush=True,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "neon_model": NEON_MODEL,
        "elapsed_s": round(time.time() - t_all, 1),
        "part1_quant_9p_spread": p1_sp,
        "part1_quant_9p_mid": p1_mid,
        "part1_quant_flagship3_spread": p1_flag_sp,
        "part1_quant_flagship3_mid": p1_flag_mid,
        "part2_live_neon_overall": neon_overall,
        "part2_live_neon_by_tf": neon_by_tf,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSaved {OUT_PATH} ({report['elapsed_s']}s)", flush=True)


if __name__ == "__main__":
    main()
