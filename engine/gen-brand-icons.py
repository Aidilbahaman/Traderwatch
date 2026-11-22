#!/usr/bin/env python3
"""Jana semua icon TraderWatch — bintang 4-mata, lukis guna Pillow (anti-alias 4x).

Bentuk bintang sama dengan logo cinematic:
  M0,-20 Q0,0 20,0  Q0,0 0,20  Q0,0 -20,0  Q0,0 0,-20 Z
(sisi cekung ke pusat = sparkle 4 mata)

Output:
  icons/icon-{180,192,512}.png       latar squircle gelap + bintang lime
  icons/icon-maskable-512.png        bintang lebih kecil (safe zone)
  icons/apple-touch-icon.png         180px penuh latar (tiada alpha)
  favicon.ico                        48/32/16
  assets/traderwatch-logo-{1024,2048}.png
"""
import pathlib

from PIL import Image, ImageDraw, ImageFilter

REPO = pathlib.Path(__file__).resolve().parent.parent
ICONS = REPO / "icons"
ASSETS = REPO / "assets"

LIME_TOP = (234, 255, 196)
LIME_BOT = (159, 232, 63)
BG_TOP = (16, 23, 16)
BG_BOT = (5, 8, 6)
SS = 4   # supersample


def quad_bezier(p0, p1, p2, steps=24):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        out.append((x, y))
    return out


def star_points(size_px, fill_ratio=1.0):
    """Titik bintang 4-mata dalam piksel, berpusat."""
    half = size_px / 2.0 * fill_ratio
    r = half                     # jejari hujung bintang (unit 20 -> half)
    c = size_px / 2.0
    k = r / 20.0                 # skala unit (bintang asal 20 unit)
    pts = []
    # hujung: atas -> kanan -> bawah -> kiri ; kawalan di pusat (0,0)
    quads = [
        ((0, -20), (0, 0), (20, 0)),      # atas -> kanan
        ((20, 0), (0, 0), (0, 20)),       # kanan -> bawah
        ((0, 20), (0, 0), (-20, 0)),      # bawah -> kiri
        ((-20, 0), (0, 0), (0, -20)),     # kiri -> atas
    ]
    for p0, p1, p2 in quads:
        seg = quad_bezier((p0[0] * k + c, p0[1] * k + c),
                          (p1[0] * k + c, p1[1] * k + c),
                          (p2[0] * k + c, p2[1] * k + c), steps=28)
        pts.extend(seg[:-1])
    return pts


def vgrad(size, top, bot):
    """Gradient menegak RGBA."""
    g = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        g.putpixel((0, y), (int(top[0] + (bot[0] - top[0]) * t),
                            int(top[1] + (bot[1] - top[1]) * t),
                            int(top[2] + (bot[2] - top[2]) * t), 255))
    return g.resize((size, size))


def squircle_mask(size, radius_ratio=0.22):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    r = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return m


def render(size, fill_ratio=1.0, transparent=False, glow=True):
    S = size * SS
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if not transparent:
        bg = vgrad(S, BG_TOP, BG_BOT)
        mask = squircle_mask(S)
        canvas.paste(bg, (0, 0), mask)

    # glow lembut di belakang bintang
    if glow:
        gl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.polygon(star_points(S, fill_ratio * 0.98), fill=(183, 243, 107, 120))
        gl = gl.filter(ImageFilter.GaussianBlur(S * 0.035))
        canvas = Image.alpha_composite(canvas, gl)

    # bintang lime bergradien
    star_mask = Image.new("L", (S, S), 0)
    smd = ImageDraw.Draw(star_mask)
    smd.polygon(star_points(S, fill_ratio), fill=255)
    star = vgrad(S, LIME_TOP, LIME_BOT)
    canvas.paste(star, (0, 0), star_mask)

    return canvas.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    ICONS.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)

    for s in (180, 192, 512):
        render(s, fill_ratio=0.86).save(ICONS / f"icon-{s}.png")
        print("wrote icons/icon-%d.png" % s)

    # maskable: bintang lebih kecil (safe zone ~80%)
    render(512, fill_ratio=0.58).save(ICONS / "icon-maskable-512.png")
    print("wrote icons/icon-maskable-512.png")

    # apple touch: penuh latar, tiada alpha
    render(180, fill_ratio=0.86, glow=True).convert("RGB").save(ICONS / "apple-touch-icon.png")
    print("wrote icons/apple-touch-icon.png")

    # favicon.ico (pelbagai saiz, latar squircle)
    ico = render(256, fill_ratio=0.82)
    ico.save(REPO / "favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)])
    print("wrote favicon.ico")

    # favicon PNG untuk pelayar moden
    render(64, fill_ratio=0.82).save(ICONS / "favicon-64.png")
    print("wrote icons/favicon-64.png")

    for big in (1024, 2048):
        render(big, fill_ratio=0.80).save(ASSETS / f"traderwatch-logo-{big}.png")
        print("wrote assets/traderwatch-logo-%d.png" % big)

    # versi transparent (untuk guna atas latar lain)
    render(512, fill_ratio=0.88, transparent=True, glow=False).save(
        ASSETS / "traderwatch-star-512.png")
    print("wrote assets/traderwatch-star-512.png")
