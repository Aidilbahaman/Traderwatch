#!/usr/bin/env python3
"""Backtest VISION: model tengok terus screenshot chart XAUUSD M15 (BOS/CHoCH).

Model diuji: deepseek-v4.1-flash vs glm-5.3-flash-mod (kedua-duanya disahkan
terima imej & balas kandungan pada probe 2026-11-22).nota: deepseek-v4-pro &
glm-5.3-flash biasa TIADA/ gagal vision — tidak digunakan.

Chart dirender daripada bar M15 sebenar sehingga masa T (tiada look-ahead),
dengan anotasi BOS H1/M15 + CHoCH. Model balas JSON bias/sl/tp1/tp2; kami
validasi dengan enjin, lalu ukur outcome TP/SL dari bar M1 selepas T (+8 jam).
"""
import json
import time
import base64
import io
import urllib.request
import importlib.util
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
la = load("llm_analyst"); sqc = load("sq_collector"); ict = load("ict_filter")
KEY = open('/home/ubuntu/.config/opencode/secrets/rootsys-key').read().strip()
MODELS = ['deepseek-v4.1-flash', 'glm-5.3-flash-mod']
POINTS = ["2026-11-19T02:00:00", "2026-11-19T06:00:00", "2026-11-19T10:00:00",
          "2026-11-19T14:00:00", "2026-11-19T18:00:00", "2026-11-19T22:00:00",
          "2026-11-20T02:00:00", "2026-11-20T06:00:00", "2026-11-20T10:00:00",
          "2026-11-20T14:00:00"]
W, H = 640, 360


def bars_at(until, gran, n):
    return [dict(r) for r in sqc.candles_from_bars("XAUUSD", gran, n, until=until)]


def structure(until):
    m15 = bars_at(until, "M15", 120); h1 = bars_at(until, "M60", 80)
    s15 = ict.swing_trend(m15, 3, 2); s1 = ict.swing_trend(h1, 3, 2)
    return {"m15": s15, "h1": s1, "bos": s15 if s15 != "RANGE" else s1,
            "choch": s1 != "RANGE" and s15 != "RANGE" and s15 != s1}


def render_chart(rows, st, price):
    im = Image.new('RGB', (W, H), (10, 14, 11)); d = ImageDraw.Draw(im)
    hi = max(r['h'] for r in rows); lo = min(r['l'] for r in rows)
    y = lambda v: 18 + (hi - v) / (hi - lo) * (H - 56)
    x = lambda i: 12 + i * (W - 90) / len(rows)
    for g in range(5):
        gy = 18 + g * (H - 56) / 4
        d.line([(0, gy), (W - 80, gy)], fill=(30, 40, 32))
    for i, r in enumerate(rows):
        xx = x(i); col = (183, 243, 107) if r['c'] >= r['o'] else (255, 119, 125)
        d.line([(xx, y(r['h'])), (xx, y(r['l']))], fill=col, width=2)
        d.rectangle([xx - 3, y(max(r['o'], r['c'])), xx + 3, y(min(r['o'], r['c']))], fill=col)
    ly = y(price)
    d.line([(0, ly), (W - 80, ly)], fill=(120, 180, 255), width=1)
    d.text((W - 76, ly - 6), f"LIVE {price:.2f}", fill=(120, 180, 255))
    d.text((10, 6), f"XAUUSD M15 | BOS={st['bos']} | H1={st['h1']} | CHoCH={'YES' if st['choch'] else 'NO'}", fill=(220, 230, 220))
    buf = io.BytesIO(); im.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def call(model, b64, st, price):
    prompt = f"""You are an ICT/SMC trader. Analyze this XAUUSD M15 candlestick chart image.
Metadata (computed): BOS={st['bos']}, H1={st['h1']}, CHoCH={'YES' if st['choch'] else 'NO'}.
Trade in BOS direction; if CHoCH=YES prefer the reversal. Entry=current price {price}.
Choose SL beyond opposing swing and TP at structure target with RR1>=1.5, or HOLD if unclear.
Reply ONLY compact JSON: {{"bias":"BUY"|"SELL"|"HOLD","sl":num,"tp1":num,"tp2":num,"confidence":0-10,"reason":"<10 words>"}}"""
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': prompt},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + b64}}]}],
        'max_tokens': 700}).encode()
    req = urllib.request.Request('https://rootsys.cloud/v1/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'}, method='POST')
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    return (d.get('choices') or [{}])[0].get('message', {}).get('content') or '', round(time.time() - t0, 1)


def outcome(side, sl, tp, until):
    rows = sqc.candles_from_bars("XAUUSD", "M1", 500)
    for r in [r for r in rows if r['t'] > until][:480]:
        if side == 'BUY':
            if r['h'] >= tp: return 'TP'
            if r['l'] <= sl: return 'SL'
        else:
            if r['l'] <= tp: return 'TP'
            if r['h'] >= sl: return 'SL'
    return 'NONE'


rows = []
for until in POINTS:
    bars = bars_at(until, "M15", 100)
    if len(bars) < 60: continue
    price = bars[-1]['c']; st = structure(until)
    b64 = render_chart(bars, st, price)
    for model in MODELS:
        rec = {'t': until, 'model': model, 'price': price, 'bos': st['bos'], 'choch': st['choch']}
        try:
            content, lat = call(model, b64, st, price); rec['lat'] = lat
            j = la.parse_response(content)
            v = la.validate_verdict(j, price, 0.01, 2.5, 1.5)
            rec.update(side=v['side'], conf=v['conf'], sl=v.get('sl'), tp=v.get('tp1'),
                       reason=j.get('reason', '')[:70])
            if v['side'] != 'HOLD':
                rec['outcome'] = outcome(v['side'], v['sl'], v['tp1'], until)
        except Exception as e:
            rec['error'] = f"{type(e).__name__}:{str(e)[:60]}"
        rows.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)

print('\n=== RINGKASAN VISION BOS/CHoCH ===')
for model in MODELS:
    rr = [r for r in rows if r['model'] == model]
    tr = [r for r in rr if 'outcome' in r]
    tp = sum(1 for r in tr if r['outcome'] == 'TP'); sl = sum(1 for r in tr if r['outcome'] == 'SL')
    err = sum(1 for r in rr if 'error' in r); hold = sum(1 for r in rr if r.get('side') == 'HOLD')
    lat = sum(r.get('lat', 0) for r in rr) / max(1, len(rr))
    print(f"{model}: TP={tp} SL={sl} HOLD={hold} ERR={err} lat={lat:.1f}s win={tp}/{tp+sl if tp+sl else 1}")
json.dump(rows, open(HERE.parent / 'research' / 'backtest-vision-bos-choch-20261122.json', 'w'), indent=1)
