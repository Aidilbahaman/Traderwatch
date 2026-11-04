#!/usr/bin/env python3
"""TraderWatch Wallet Ticket card renderer.

Signal JSON in -> PNG (static) and/or silent H.264 MP4 (animated) out.
Needs: Python 3.9+, Pillow, ffmpeg on PATH.

Usage:
    python render_ticket.py samples/btc_buy.json --out out/
    python render_ticket.py signal.json --out out/ --mp4-only
"""
import argparse, json, math, os, subprocess, sys, shutil
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350          # final size (4:5)
S = 2                      # supersampling factor for smooth edges
FPS, DUR = 30, 5.0
# Eksperimen Telegram: matikan animasi dan kekalkan semua maklumat terlihat
# sepanjang 5 saat. Ini membetulkan "4 kotak tak muncul" pada autoplay/frame awal.
STATIC_HOLD = True

CANVAS = (0, 0, 0)
CARD = (11, 15, 26)
WHITE = (255, 255, 255)
SOFT = (229, 231, 235)
GRAY = (142, 142, 147)
DIM = (99, 99, 102)
LINE = (44, 44, 46)
TRACK = (28, 33, 46)
GREEN = (48, 209, 88)
RED = (255, 69, 58)
PILL = {"BUY": (15, 42, 26), "SELL": (51, 18, 16)}

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------- fonts ----------
def _first(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


REG = _first([
    os.environ.get("TW_FONT_REGULAR"),
    os.path.join(HERE, "fonts", "Inter-Regular.ttf"),
    "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
])
MED = _first([
    os.environ.get("TW_FONT_MEDIUM"),
    os.path.join(HERE, "fonts", "Inter-Medium.ttf"),
    "/usr/share/fonts/truetype/inter/Inter-Medium.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
])
if not REG or not MED:
    sys.exit("No usable font found. Put Inter-Regular.ttf and Inter-Medium.ttf in ./fonts/")
if "Inter" not in os.path.basename(REG):
    print("NOTE: Inter font not found, using fallback font. Add fonts/Inter-Regular.ttf "
          "and fonts/Inter-Medium.ttf for the intended look.", file=sys.stderr)

_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(MED if kind == "m" else REG, int(round(size * S)))
    return _cache[key]


# ---------- helpers ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, a, b):
    return clamp((t - a) / (b - a))


def ease(x):  # ease-out cubic
    return 1 - (1 - x) ** 3


def lerp_c(c0, c1, a):
    return tuple(int(round(c0[i] + (c1[i] - c0[i]) * a)) for i in range(3))


def fmt(v, dec):
    return f"{v:,.{dec}f}" if abs(v) >= 1000 else f"{v:.{dec}f}"


def load_signal(path_or_dict):
    sig = path_or_dict if isinstance(path_or_dict, dict) else json.load(open(path_or_dict))
    side = str(sig["side"]).upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    if side == "BUY" and not (sl < e < tp):
        raise ValueError("BUY needs sl < entry < tp")
    if side == "SELL" and not (tp < e < sl):
        raise ValueError("SELL needs tp < entry < sl")
    risk, reward = abs(e - sl), abs(tp - e)
    dec = int(sig.get("decimals", 2))
    return {
        "pair": sig["pair"], "tf": sig.get("timeframe", ""), "side": side,
        "entry": e, "sl": sl, "tp": tp, "dec": dec, "risk": risk, "reward": reward,
        "rr": reward / risk, "brand": sig.get("brand", "TraderWatch"),
        "sl_note": sig.get("sl_note", ""), "tp_note": sig.get("tp_note", ""),
        "id": str(sig.get("id", "")),
    }


# ---------- static base (card, notches, perforation) ----------
def make_base():
    img = Image.new("RGB", (W * S, H * S), CANVAS)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40 * S, 40 * S, 1040 * S, 1310 * S], radius=72 * S, fill=CARD)
    py = 940
    for cx in (40, 1040):
        d.ellipse([(cx - 44) * S, (py - 44) * S, (cx + 44) * S, (py + 44) * S], fill=CANVAS)
    x = 110
    while x < 970:
        d.line([x * S, py * S, min(x + 18, 970) * S, py * S], fill=LINE, width=3 * S)
        x += 32
    return img


# ---------- one frame ----------
def draw_frame(base, sg, t):
    img = base.copy()
    d = ImageDraw.Draw(img)
    # STATIC_HOLD: papar keadaan akhir (semua maklumat) dari frame pertama.
    # Masa sebenar disimpan untuk gerakan halus di hujung.
    t_real = t
    if STATIC_HOLD:
        t = 4.0

    def text(x, y, s, kind, size, color, a=1.0, dy=0.0, anchor="ls"):
        c = lerp_c(CARD, color, a)
        d.text((x * S, (y + dy) * S), s, font=font(kind, size), fill=c, anchor=anchor)

    def grp(a0, a1):
        p = ease(prog(t, a0, a1))
        return p, (1 - p) * 24

    side_col = GREEN if sg["side"] == "BUY" else RED

    # header + pair + pill
    p, dy = grp(0.25, 0.70)
    text(120, 140, sg["brand"], "r", 36, SOFT, p, dy)
    text(960, 140, sg["tf"], "r", 36, GRAY, p, dy, anchor="rs")
    text(120, 290, sg["pair"], "m", 112, WHITE, p, dy)
    label = "Buy" if sg["side"] == "BUY" else "Sell"
    tw = d.textlength(label, font=font("m", 40)) / S
    pw = tw + 72
    y0 = 345 + dy
    d.rounded_rectangle([120 * S, y0 * S, (120 + pw) * S, (y0 + 80) * S], radius=40 * S,
                        fill=lerp_c(CARD, PILL[sg["side"]], p))
    text(120 + pw / 2, 400, label, "m", 40, side_col, p, dy, anchor="ms")

    # range bar
    x0, x1, by, th = 120, 960, 610, 28
    frac = clamp(sg["risk"] / (sg["risk"] + sg["reward"]), 0.12, 0.88)
    xe = x0 + (x1 - x0) * frac
    d.rounded_rectangle([x0 * S, (by - th / 2) * S, x1 * S, (by + th / 2) * S],
                        radius=th / 2 * S, fill=TRACK)
    pr = ease(prog(t, 0.9, 1.5))
    pg = ease(prog(t, 0.9, 2.25))
    lr, lg = (xe - 12) - x0, x1 - (xe + 12)
    if lr * pr > 2:
        d.rounded_rectangle([((xe - 12) - lr * pr) * S, (by - th / 2) * S, (xe - 12) * S, (by + th / 2) * S],
                            radius=th / 2 * S, fill=RED)
    if lg * pg > 2:
        d.rounded_rectangle([(xe + 12) * S, (by - th / 2) * S, ((xe + 12) + lg * pg) * S, (by + th / 2) * S],
                            radius=th / 2 * S, fill=GREEN)
    pd = ease(prog(t, 0.4, 0.75))
    r = 26 * pd
    if r > 1:
        d.ellipse([(xe - r) * S, (by - r) * S, (xe + r) * S, (by + r) * S], fill=WHITE)
    pring = prog(t, 0.5, 1.6)
    if 0 < pring < 1:
        rr_ = 26 + 50 * ease(pring)
        d.ellipse([(xe - rr_) * S, (by - rr_) * S, (xe + rr_) * S, (by + rr_) * S],
                  outline=lerp_c(CARD, WHITE, 0.45 * (1 - pring)), width=3 * S)

    # SL / TP labels
    p, dy = grp(1.5, 1.95)
    text(120, 720, "Stop loss", "r", 34, GRAY, p, dy)
    text(120, 795, fmt(sg["sl"], sg["dec"]), "m", 60, RED, p, dy)
    if sg["sl_note"]:
        text(120, 855, sg["sl_note"], "r", 34, lerp_c(CARD, RED, 0.75), p, dy)
    p, dy = grp(2.25, 2.70)
    text(960, 720, "Take profit", "r", 34, GRAY, p, dy, anchor="rs")
    text(960, 795, fmt(sg["tp"], sg["dec"]), "m", 60, GREEN, p, dy, anchor="rs")
    if sg["tp_note"]:
        text(960, 855, sg["tp_note"], "r", 34, lerp_c(CARD, GREEN, 0.75), p, dy, anchor="rs")

    # entry (bottom left)
    p, dy = grp(0.50, 0.95)
    es = fmt(sg["entry"], sg["dec"])
    size = 112
    while d.textlength(es, font=font("m", size)) / S > 560 and size > 60:
        size -= 4
    text(120, 1020, "Entry", "r", 38, GRAY, p, dy)
    text(120, 1150, es, "m", size, WHITE, p, dy)

    # risk:reward + footer
    p, dy = grp(2.90, 3.35)
    text(960, 1090, "Risk : reward", "r", 30, GRAY, p, dy, anchor="rs")
    text(960, 1150, f"1 : {sg['rr']:.1f}", "m", 60, WHITE, p, dy, anchor="rs")
    p, dy = grp(3.20, 3.65)
    text(120, 1255, "Not financial advice · trade at your own risk", "r", 28, DIM, p, dy)

    out = img.resize((W, H), Image.LANCZOS)
    # Kandungan penuh sepanjang 5s; gerakan halus ditambah supaya ia kekal
    # sebagai video (Telegram autoplay) bukan imej statik.
    if STATIC_HOLD:
        fade = 1.0
    else:
        fade = ease(prog(t, 0.0, 0.25)) * (1 - ease(prog(t, 4.6, 5.0)))
    if fade < 1:
        out = Image.blend(Image.new("RGB", (W, H), CANVAS), out, fade)
    if STATIC_HOLD:
        out = _motion(out, sg, t_real)
    return out


def _motion(out, sg, t):
    """Gerakan halus dilukis TERUS pada imej siap (tiada overlay hitam)."""
    d = ImageDraw.Draw(out)
    frac = clamp(sg["risk"] / (sg["risk"] + sg["reward"]), 0.12, 0.88)
    xe = 120 + (960 - 120) * frac
    by = 610

    # 1) Denyut berulang pada titik entry (kitaran 1.25s).
    cyc = (t % 1.25) / 1.25
    rr = 26 + 58 * ease(cyc)
    shade = int(200 * (1 - cyc))
    col = (shade, shade, shade)
    d.ellipse([xe - rr, by - rr, xe + rr, by + rr], outline=col, width=3)

    # 2) Kilau melintasi bar (kitaran 2.5s).
    sc = (t % 2.5) / 2.5
    bx = 120 + (960 - 120) * ease(sc)
    g = int(70 * math.sin(math.pi * sc))
    if g > 0:
        d.rounded_rectangle([bx - 23, by - 14, bx + 23, by + 14],
                            radius=14, fill=(g, g, g))

    # 3) Titik entry berdenyut.
    pr = 26 + 2.5 * math.sin(t * math.pi * 2)
    d.ellipse([xe - pr, by - pr, xe + pr, by + pr], fill=(255, 255, 255))
    return out


# ---------- outputs ----------
def render_png(sg, path):
    draw_frame(make_base(), sg, 4.0).save(path, optimize=True)
    return path


def render_mp4(sg, path):
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")
    base = make_base()
    # Kad statik dilukis SEKALI. Setiap frame hanya menambah gerakan halus,
    # jadi render turun dari ~30s ke beberapa saat.
    static = draw_frame(base, sg, 4.0) if STATIC_HOLD else None
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an",
           "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(FPS * DUR)
    hold = None
    for i in range(n):
        t = i / FPS
        if static is not None:
            frame = _motion(static.copy(), sg, t)
        elif 3.7 <= t < 4.55 and hold is not None:
            proc.stdin.write(hold)
            continue
        else:
            frame = draw_frame(base, sg, t)
            if 3.7 <= t < 4.55:
                hold = frame.tobytes()
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("signal", help="signal JSON file")
    ap.add_argument("--out", default="out")
    ap.add_argument("--png-only", action="store_true")
    ap.add_argument("--mp4-only", action="store_true")
    a = ap.parse_args()
    sg = load_signal(a.signal)
    os.makedirs(a.out, exist_ok=True)
    stem = f"{sg['pair'].replace('/', '')}_{sg['side'].lower()}_{sg['tf']}" + (f"_{sg['id']}" if sg["id"] else "")
    res = {}
    if not a.mp4_only:
        res["png"] = render_png(sg, os.path.join(a.out, stem + ".png"))
    if not a.png_only:
        res["mp4"] = render_mp4(sg, os.path.join(a.out, stem + ".mp4"))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
