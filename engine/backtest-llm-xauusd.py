#!/usr/bin/env python3
"""Backtest adil: qwen4-max vs deepseek-v4-pro pada XAUUSD (M15).

6 titik masa historical (setiap 4j), prompt + validasi SAMA seperti enjin.
Tiada look-ahead: bar dimotong pada T (until=T); outcome diukur dari bar
selepas T sehingga +8 jam (M1) — TP/SL pertama yang kena menang.
Skor: arah betul (TP) / salah (SL) / tiada keputusan (HOLD/expired).
"""
import json
import time
import urllib.request
import urllib.error
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("la", HERE / "llm_analyst.py")
la = importlib.util.module_from_spec(spec); spec.loader.exec_module(la)
spec2 = importlib.util.spec_from_file_location("sqc", HERE / "sq_collector.py")
sqc = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(sqc)

KEY_Q = open('/home/ubuntu/.config/opencode/secrets/rootsys-qwen-key').read().strip()
KEY_D = open('/home/ubuntu/.config/opencode/secrets/rootsys-key').read().strip()
MODELS = {'qwen4-max': KEY_Q, 'deepseek-v4-pro': KEY_D}
POINTS = [
    "2026-11-19T02:00:00", "2026-11-19T06:00:00", "2026-11-19T10:00:00",
    "2026-11-19T14:00:00", "2026-11-19T18:00:00", "2026-11-19T22:00:00",
    "2026-11-20T02:00:00", "2026-11-20T06:00:00", "2026-11-20T10:00:00",
    "2026-11-20T14:00:00",
]
HORIZON_BARS = 480  # 8 jam M1


def bars_at(until):
    rows = sqc.candles_from_bars("XAUUSD", "M15", 300, until=until)
    return [(r['t'], r['h'], r['l'], r['c']) for r in rows]


def outcome(side, entry, sl, tp, until):
    rows = sqc.candles_from_bars("XAUUSD", "M1", HORIZON_BARS, until=None)
    fut = [r for r in rows if r['t'] > until][:HORIZON_BARS]
    for r in fut:
        if side == 'BUY':
            if r['h'] >= tp: return 'TP', r['t']
            if r['l'] <= sl: return 'SL', r['t']
        else:
            if r['l'] <= tp: return 'TP', r['t']
            if r['h'] >= sl: return 'SL', r['t']
    return 'NONE', None


def call(model, key, prompt):
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                       'max_tokens': 4000, 'temperature': 0.2}).encode()
    req = urllib.request.Request('https://rootsys.cloud/v1/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    content = (d.get('choices') or [{}])[0].get('message', {}).get('content') or ''
    return content, round(time.time() - t0, 1), (d.get('usage') or {}).get('total_tokens')


rows = []
for until in POINTS:
    bars = bars_at(until)
    if len(bars) < 300:
        print('skip', until, 'bars', len(bars)); continue
    price = bars[-1][3]
    atr = la.M.atr_s(bars)[-1]
    prof = la.tf_profile('M15')
    ctx = la.resample(bars, prof['ctx_factor'])
    closes = [b[4] for b in ctx]
    trend = 'UP' if la.M.ema(closes, 20)[-1] > la.M.ema(closes, 50)[-1] else 'DOWN'
    win = bars[-96:]
    prompt = la.build_prompt('XAUUSD', price, ctx[-prof['ctx_show']:],
        la.with_opens(bars)[-prof['base_show']:], atr, trend,
        max(b[1] for b in win), min(b[2] for b in win), 2.5, tf='M15')
    for model, key in MODELS.items():
        rec = {'t': until, 'model': model, 'price': price}
        try:
            content, lat, tok = call(model, key, prompt)
            rec.update(lat=lat, tok=tok)
            j = la.parse_response(content)
            v = la.validate_verdict(j, price, 0.01, 2.5, prof['rr1_min'])
            rec.update(side=v['side'], conf=v['conf'], sl=v.get('sl'), tp=v.get('tp1'),
                       reason=j.get('reason', '')[:70])
            if v['side'] != 'HOLD':
                oc, when = outcome(v['side'], price, v['sl'], v['tp1'], until)
                rec.update(outcome=oc, when=when)
        except Exception as e:
            rec.update(error=f"{type(e).__name__}:{str(e)[:70]}")
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

print('\n=== RINGKASAN ===')
for model in MODELS:
    rr = [r for r in rows if r['model'] == model]
    ok = [r for r in rr if 'outcome' in r]
    tp = sum(1 for r in ok if r['outcome'] == 'TP')
    sl = sum(1 for r in ok if r['outcome'] == 'SL')
    hold = sum(1 for r in rr if r.get('side') == 'HOLD')
    err = sum(1 for r in rr if 'error' in r)
    lat = sum(r.get('lat', 0) for r in rr) / max(1, len(rr))
    print(f"{model}: TP={tp} SL={sl} HOLD={hold} ERR={err} | winrate={tp}/{tp+sl if tp+sl else 1} | lat_avg={lat:.1f}s")
json.dump(rows, open(HERE.parent / 'research' / 'backtest-llm-xauusd-20261122.json', 'w'), indent=1)
