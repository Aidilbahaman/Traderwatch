#!/usr/bin/env python3
"""Backtest teknik BOS + CHoCH: qwen4-max vs deepseek-v4-pro vs glm-5.3-flash.

BOS  = break of structure: swing trend HH/HL (UP) atau LH/LL (DOWN) pada M15.
CHoCH= change of character: arah swing M15 berubah lawan swing H1 sebelumnya
       (tanda reversal / agihan struktur).

10 titik XAUUSD historical. Tiada look-ahead: prompt guna bar <= T, outcome
diukur dari M1 selepas T sehingga +8 jam (TP/SL pertama menang).
"""
import json
import time
import urllib.request
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

la = load("llm_analyst")
sqc = load("sq_collector")
ict = load("ict_filter")

KEY_Q = open('/home/ubuntu/.config/opencode/secrets/rootsys-qwen-key').read().strip()
KEY_D = open('/home/ubuntu/.config/opencode/secrets/rootsys-key').read().strip()
MODELS = {'qwen4-max': KEY_Q, 'deepseek-v4-pro': KEY_D, 'glm-5.3-flash': KEY_D}
POINTS = ["2026-11-19T02:00:00", "2026-11-19T06:00:00", "2026-11-19T10:00:00",
          "2026-11-19T14:00:00", "2026-11-19T18:00:00", "2026-11-19T22:00:00",
          "2026-11-20T02:00:00", "2026-11-20T06:00:00", "2026-11-20T10:00:00",
          "2026-11-20T14:00:00"]


def bars_at(until, gran, n):
    return [dict(r) for r in sqc.candles_from_bars("XAUUSD", gran, n, until=until)]


def structure(until):
    m15 = bars_at(until, "M15", 120)
    h1 = bars_at(until, "M60", 80)
    b15 = ict.swing_trend(m15, lookback=3, need=2)
    b1 = ict.swing_trend(h1, lookback=3, need=2)
    # CHoCH: M15 bertentangan dengan H1 dan H1 bukan RANGE
    choch = b1 != "RANGE" and b15 != "RANGE" and b15 != b1
    bos = b15 if b15 != "RANGE" else b1
    return {"m15": b15, "h1": b1, "bos": bos, "choch": choch}


def prompt_bos(price, atr, st, spread=2.5):
    c = "YES — M15 structure flipped against H1 (potential reversal/CHoCH)." if st['choch'] else "No CHoCH; follow the dominant BOS."
    return f"""ICT/SMC BOS + CHoCH analyst. XAUUSD price {price}. M15 ATR {atr:.2f}, spread {spread} pips.
Higher-timeframe H1 swing: {st['h1']}. M15 swing/BOS: {st['m15']}. CHoCH: {c}
Rules: trade IN the direction of the BOS. If CHoCH=YES, prefer the NEW M15 direction (reversal).
Entry = current price. SL beyond the last opposing swing (never inside spread).
TP at next structure target. RR1 >= 1.5. If structure unclear, bias HOLD.
Reply ONLY one compact JSON: {{"bias":"BUY"|"SELL"|"HOLD","sl":num,"tp1":num,"tp2":num,"confidence":0-10,"reason":"<max 12 words>"}}
BUY: sl<entry<tp1<tp2. SELL: sl>entry>tp1>tp2. Confidence honest."""


def call(model, key, prompt):
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                       'max_tokens': 4000, 'temperature': 0.2}).encode()
    req = urllib.request.Request('https://rootsys.cloud/v1/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    content = (d.get('choices') or [{}])[0].get('message', {}).get('content') or ''
    return content, round(time.time() - t0, 1)


def outcome(side, sl, tp, until):
    rows = sqc.candles_from_bars("XAUUSD", "M1", 500)
    fut = [r for r in rows if r['t'] > until][:480]
    for r in fut:
        if side == 'BUY':
            if r['h'] >= tp: return 'TP'
            if r['l'] <= sl: return 'SL'
        else:
            if r['l'] <= tp: return 'TP'
            if r['h'] >= sl: return 'SL'
    return 'NONE'


rows = []
for until in POINTS:
    bars = bars_at(until, "M15", 300)
    if len(bars) < 100:
        continue
    price = bars[-1]['c']
    tup = [(b['t'], b['h'], b['l'], b['c']) for b in bars]
    atr = la.M.atr_s(tup)[-1]
    st = structure(until)
    prompt = prompt_bos(price, atr, st)
    for model, key in MODELS.items():
        rec = {'t': until, 'model': model, 'price': price, 'bos': st['bos'], 'choch': st['choch']}
        try:
            content, lat = call(model, key, prompt)
            rec['lat'] = lat
            j = la.parse_response(content)
            v = la.validate_verdict(j, price, 0.01, 2.5, 1.5)
            rec.update(side=v['side'], conf=v['conf'], sl=v.get('sl'), tp=v.get('tp1'),
                       reason=j.get('reason', '')[:70])
            if v['side'] != 'HOLD':
                rec['outcome'] = outcome(v['side'], v['sl'], v['tp1'], until)
        except Exception as e:
            rec['error'] = f"{type(e).__name__}:{str(e)[:60]}"
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

print('\n=== RINGKASAN BOS/CHoCH ===')
for model in MODELS:
    rr = [r for r in rows if r['model'] == model]
    tr = [r for r in rr if 'outcome' in r]
    tp = sum(1 for r in tr if r['outcome'] == 'TP')
    sl = sum(1 for r in tr if r['outcome'] == 'SL')
    err = sum(1 for r in rr if 'error' in r)
    hold = sum(1 for r in rr if r.get('side') == 'HOLD')
    lat = sum(r.get('lat', 0) for r in rr) / max(1, len(rr))
    print(f"{model}: n={len(rr)} TP={tp} SL={sl} HOLD={hold} ERR={err} lat={lat:.1f}s win={tp}/{tp+sl if tp+sl else 1}")
json.dump(rows, open(HERE.parent / 'research' / 'backtest-bos-choch-20261122.json', 'w'), indent=1)
