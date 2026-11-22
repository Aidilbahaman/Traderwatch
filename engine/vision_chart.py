"""Render chart OHLC ringkas daripada bar (ts_ms,h,l,c) -> PNG base64
untuk model vision. Ringan: PIL sahaja. Bar terakhir = harga semasa.
"""
import base64
import io
from PIL import Image, ImageDraw

W, H = 640, 360


def render(bars, pair="XAUUSD", tf="M15", bos="", choch=False):
    """Line chart harga tutup + marker swing high/low -> PNG base64.

    Guna LINE (bukan candle) atas permintaan owner. Untuk elak kehilangan
    maklumat wick, kita lukis:
      * garis tebal = harga TUTUP (trend jelas)
      * marker kecil = swing high/low sebenar (AI nampak rejection)
      * shadow halus = julat high-low setiap bar (wick context)
    """
    if not bars:
        return ""
    im = Image.new("RGB", (W, H), (10, 14, 11))
    d = ImageDraw.Draw(im)
    hi = max(b[1] for b in bars)
    lo = min(b[2] for b in bars)
    rng = (hi - lo) or 1.0
    y = lambda v: 18 + (hi - v) / rng * (H - 56)
    x = lambda i: 12 + i * (W - 90) / max(1, len(bars) - 1)

    for g in range(5):
        gy = 18 + g * (H - 56) / 4
        d.line([(0, gy), (W - 80, gy)], fill=(30, 40, 32))

    # 1) shadow julat high-low (nipis) — kekalkan konteks wick
    for i, b in enumerate(bars):
        xx = x(i)
        d.line([(xx, y(b[1])), (xx, y(b[2]))], fill=(28, 40, 30), width=1)

    # 2) garis harga tutup — terang & tebal (trend utama)
    pts = [(x(i), y(b[3])) for i, b in enumerate(bars)]
    for i in range(1, len(pts)):
        d.line([pts[i - 1], pts[i]], fill=(183, 243, 107), width=3)
        # sendi bulat untuk keterbacaan
        d.ellipse([pts[i][0] - 1.5, pts[i][1] - 1.5,
                   pts[i][0] + 1.5, pts[i][1] + 1.5], fill=(183, 243, 107))

    # 3) marker swing (high/low setempat) — AI nampak rejection struktur
    for i in range(2, len(bars) - 2):
        w = bars[i - 2:i + 3]
        if bars[i][1] >= max(b[1] for b in w):
            d.ellipse([x(i) - 2.4, y(bars[i][1]) - 2.4,
                       x(i) + 2.4, y(bars[i][1]) + 2.4], outline=(214, 255, 154))
        if bars[i][2] <= min(b[2] for b in w):
            d.ellipse([x(i) - 2.4, y(bars[i][2]) - 2.4,
                       x(i) + 2.4, y(bars[i][2]) + 2.4], outline=(255, 159, 159))

    price = bars[-1][3]
    ly = y(price)
    d.line([(0, ly), (W - 80, ly)], fill=(120, 180, 255), width=1)
    d.text((W - 76, ly - 6), f"LIVE {price:.2f}", fill=(120, 180, 255))
    d.text((10, 6), f"{pair} {tf} | BOS={bos} | CHoCH={'YES' if choch else 'NO'}",
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
