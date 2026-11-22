"""Render chart OHLC ringkas daripada bar (ts_ms,h,l,c) -> PNG base64
untuk model vision. Ringan: PIL sahaja. Bar terakhir = harga semasa.
"""
import base64
import io
from PIL import Image, ImageDraw

W, H = 640, 360


def render(bars, pair="XAUUSD", tf="M15", bos="", choch=False, levels=None, max_bars=80):
    """Candlestick chart + EMA20/50 + marker swing + paras cadangan -> PNG base64.

    CANDLE (bukan line) — badan + wick penuh supaya vision AI nampak:
      * badan = siapa menang dalam bar (open = tutup bar sebelumnya)
      * wick = julat sebenar disentuh (rejection / stop-hunt)
      * EMA20 (amber) + EMA50 (ungu halus) dikira atas keseluruhan bar (warm EMA)
      * marker bulat = swing high/low sebenar
      * paras cadangan SL/TP1/TP2 (jika `levels` dibekalkan) supaya vision AI
        nampak terus geometri risiko/ganjaran di atas carta.
    """
    if not bars:
        return ""
    # Kira EMA20 & EMA50 atas semua bar dahulu supaya warm, kemudian zoom pada
    # `max_bars` bar terkini agar struktur & swing jelas kelihatan oleh vision AI.
    all_closes = [b[3] for b in bars]
    ema_series = {}
    for period in (50, 20):
        if len(all_closes) >= 5:
            k = 2.0 / (period + 1)
            e = all_closes[0]
            arr = [e]
            for i in range(1, len(all_closes)):
                e = all_closes[i] * k + e * (1.0 - k)
                arr.append(e)
            ema_series[period] = arr

    view_start = max(0, len(bars) - max_bars) if max_bars and len(bars) > max_bars else 0
    view = bars[view_start:]

    im = Image.new("RGB", (W, H), (10, 14, 11))
    d = ImageDraw.Draw(im)
    hi = max(b[1] for b in view)
    lo = min(b[2] for b in view)
    if levels:
        for k in ("sl", "tp1", "tp2", "entry"):
            v = levels.get(k)
            if v is not None:
                hi = max(hi, float(v))
                lo = min(lo, float(v))
    rng = (hi - lo) or 1.0
    y = lambda v: 18 + (hi - v) / rng * (H - 56)
    x = lambda i: 12 + i * (W - 96) / max(1, len(view) - 1)

    for g in range(5):
        gy = 18 + g * (H - 56) / 4
        d.line([(0, gy), (W - 86, gy)], fill=(30, 40, 32))

    # 1) CANDLE — wick + badan (open = tutup bar sebelumnya)
    # separuh lebar badan = 31% jarak slot (badan penuh ~62%, tak bertindih)
    body_w = max(1, min(5, int((W - 96) / max(1, len(view)) * 0.31)))
    for i, b in enumerate(view):
        xx = x(i)
        op = view[i - 1][3] if i else b[3]  # bar tuple = (ts,h,l,c): no real open
        up = b[3] >= op
        col = (183, 243, 107) if up else (255, 119, 125)
        d.line([(xx, y(b[1])), (xx, y(b[2]))], fill=col, width=1)
        top, bot = y(max(op, b[3])), y(min(op, b[3]))
        d.rectangle([xx - body_w, top, xx + body_w, max(bot, top + 1)], fill=col)

    # 1b) EMA20 (amber) & EMA50 (ungu lembut) untuk konteks value zone
    for period, col in ((50, (145, 115, 190)), (20, (235, 180, 90))):
        arr = ema_series.get(period)
        if arr:
            sub = arr[view_start:]
            epts = [(x(i), y(v)) for i, v in enumerate(sub)]
            for i in range(1, len(epts)):
                d.line([epts[i - 1], epts[i]], fill=col, width=1)

    # 2) marker swing (high/low setempat) — AI nampak rejection struktur
    for i in range(2, len(view) - 2):
        w = view[i - 2:i + 3]
        if view[i][1] >= max(b[1] for b in w):
            d.ellipse([x(i) - 2.4, y(view[i][1]) - 2.4,
                       x(i) + 2.4, y(view[i][1]) + 2.4], outline=(214, 255, 154))
        if view[i][2] <= min(b[2] for b in w):
            d.ellipse([x(i) - 2.4, y(view[i][2]) - 2.4,
                       x(i) + 2.4, y(view[i][2]) + 2.4], outline=(255, 159, 159))

    # 4) paras cadangan SL / TP1 / TP2 jika ada
    price = view[-1][3]
    dec = 2 if price > 500 else (3 if price > 10 else 5)
    if levels:
        for key, lbl, col in (("sl", "SL", (255, 105, 110)),
                              ("tp1", "TP1", (130, 245, 130)),
                              ("tp2", "TP2", (100, 220, 255))):
            v = levels.get(key)
            if v is not None:
                vy = y(float(v))
                d.line([(0, vy), (W - 86, vy)], fill=col, width=1)
                d.text((W - 82, vy - 6), f"{lbl} {float(v):.{dec}f}", fill=col)

    ly = y(price)
    d.line([(0, ly), (W - 86, ly)], fill=(120, 180, 255), width=1)
    d.text((W - 82, ly - 6), f"LIVE {price:.{dec}f}", fill=(120, 180, 255))
    setup_tag = f" | {levels.get('side','')} {levels.get('setup_label','')}" if levels else ""
    d.text((10, 6), f"{pair} {tf} | BOS={bos} | CHoCH={'YES' if choch else 'NO'}{setup_tag}",
           fill=(220, 230, 220))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def render_multi(panels, pair="XAUUSD"):
    """panels = [(tf, bars), ...] -> satu imej gabungan (stack) untuk alignment.
    Setiap panel label TF di atas. Return base64 PNG."""
    if not panels:
        return ""
    ph = 150
    im = Image.new("RGB", (W, ph * len(panels)), (10, 14, 11))
    d = ImageDraw.Draw(im)
    for pi, (tf, bars) in enumerate(panels):
        oy = pi * ph
        if not bars:
            continue
        hi = max(b[1] for b in bars); lo = min(b[2] for b in bars)
        rng = (hi - lo) or 1.0
        y = lambda v: oy + 22 + (hi - v) / rng * (ph - 34)
        x = lambda i: 12 + i * (W - 90) / max(1, len(bars) - 1)
        d.text((10, oy + 4), f"{pair} {tf}", fill=(220, 230, 220))
        for i, b in enumerate(bars):
            xx = x(i)
            op = bars[i - 1][3] if i else b[3]
            col = (183, 243, 107) if b[3] >= op else (255, 119, 125)
            d.line([(xx, y(b[1])), (xx, y(b[2]))], fill=col, width=2)
            top, bot = y(max(op, b[3])), y(min(op, b[3]))
            d.rectangle([xx - 2, top, xx + 2, max(bot, top + 1)], fill=col)
        d.line([(0, oy + ph - 1), (W, oy + ph - 1)], fill=(34, 43, 35))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
