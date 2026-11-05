#!/usr/bin/env python3.12
"""Elliot Wave marking pada chart — data sebenar dari state/sq-bars.db.

Guna ZigZag swing detection pada M15 (atau TF diberi), label swing
tinggi/rendah bergilir sebagai gelombang, dan lukis impulse + corrective.
"""
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

REPO = Path("/home/ubuntu/web/Traderwatch-repo")
DB = REPO / "state" / "sq-bars.db"

# Ketepatan harga ikut instrumen (pips vs dolar)
DP = {"XAUUSD": 2, "XAGUSD": 3, "BTCUSD": 0}
DP_DEFAULT = 5


def px(pair, v):
    d = DP.get(pair, DP_DEFAULT)
    return f"{v:,.{d}f}"

BG = "#0b0d10"
PANEL = "#12151a"
TEXT = "#f0f3f6"
MUTED = "#89939f"
GREEN = "#b7f36b"
RED = "#ff777d"
BLUE = "#8ab4ff"
GOLD = "#f3cb75"


def load_bars(pair, tf, limit=220):
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT ts, o, h, l, c FROM bars WHERE pair=? AND gran=? "
        "ORDER BY ts DESC LIMIT ?", (pair, tf, limit)).fetchall()
    con.close()
    return list(reversed(rows))


def zigzag(bars, pct=0.6):
    """ZigZag swing: kesan pivot tinggi/rendah bergilir.
    pct = ambang pergerakan (%) untuk sahkan pivot baharu."""
    piv = []
    if not bars:
        return piv
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]

    def is_high(i):
        return highs[i] == max(highs[max(0, i - 2):i + 3])

    def is_low(i):
        return lows[i] == min(lows[max(0, i - 2):i + 3])

    cand = []
    for i in range(1, len(bars) - 1):
        if is_high(i):
            cand.append((i, highs[i], "H"))
        if is_low(i):
            cand.append((i, lows[i], "L"))

    # Kemas: buang pivot berturut-turut sama jenis, kekalkan ekstrem
    cleaned = []
    for c in cand:
        if not cleaned:
            cleaned.append(c)
            continue
        last = cleaned[-1]
        if last[2] == c[2]:
            if (c[2] == "H" and c[1] > last[1]) or (c[2] == "L" and c[1] < last[1]):
                cleaned[-1] = c
        else:
            move = abs(c[1] - last[1]) / last[1] * 100
            if move >= pct:
                cleaned.append(c)
    # Penapis akhir: pastikan GILIRAN H/L (setiap pivot bertukar jenis) dan
    # setiap gelombang ada jarak bar minimum. ZigZag naif sering hasilkan
    # H-H atau L-L berturutan, yang menjadikan "gelombang" palsu.
    min_gap = 3
    out = []
    for c in cleaned:
        if not out:
            out.append(c)
            continue
        last = out[-1]
        if c[2] == last[2]:
            # Jenis sama: kekalkan yang lebih ekstrem sahaja
            if (c[2] == "H" and c[1] > last[1]) or (c[2] == "L" and c[1] < last[1]):
                out[-1] = c
            continue
        # Jenis berbeza: terima hanya kalau jarak bar cukup
        if (c[0] - last[0]) >= min_gap:
            out.append(c)
        # Kalau terlalu rapat, abaikan pivot ini sepenuhnya (jangan ganti)
        # supaya giliran H/L kekal betul.
    return out


# Validasi Elliot Wave (8 gelombang + Fibonacci) dari modul elliot_rules
import importlib.util as _ilu
from pathlib import Path as _P
_spec = _ilu.spec_from_file_location("elliot_rules", "/home/ubuntu/web/Traderwatch-repo/engine/elliot_rules.py")
_er = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_er)

_impulse_ok = None  # digantikan oleh _er
label_waves = _er.label_waves


def render(pair="XAUUSD", tf="M60", limit=300):
    """tf lalai M60 (H1): ujian empirik 9 pair -> 78% kitaran sah, tertinggi."""
    bars = load_bars(pair, tf, limit)
    if not bars:
        print(f"Tiada bar untuk {pair} {tf}")
        return None

    piv = zigzag(bars, pct=0.3)
    marked, verdict, detail = label_waves(piv, validate=True)
    valid = bool(verdict) and verdict.startswith("SAH")

    xs = list(range(len(bars)))
    o = [b[1] for b in bars]
    h = [b[2] for b in bars]
    lo = [b[3] for b in bars]
    c = [b[4] for b in bars]

    fig, ax = plt.subplots(figsize=(16, 8), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    # Candlestick
    for i in xs:
        up = c[i] >= o[i]
        col = GREEN if up else RED
        ax.plot([i, i], [lo[i], h[i]], color=col, linewidth=0.6, alpha=0.9)
        ax.add_patch(Rectangle((i - 0.35, min(o[i], c[i])),
                               max(0.7, 0.7), max(abs(c[i] - o[i]), 1e-9),
                               facecolor=col, edgecolor=col, linewidth=0.3, alpha=0.85))

    # Wave zigzag line + labels
    if marked:
        wx = [p[0] for p in marked]
        wy = [p[1] for p in marked]
        ax.plot(wx, wy, color=GOLD, linewidth=2.0, marker="o",
                markersize=7, markerfacecolor=GOLD, markeredgecolor=BG,
                markeredgewidth=1.5, zorder=5, label="Elliot Wave structure")
        for (ix, iy, kind, lab) in marked:
            color = GOLD
            ax.annotate(lab, (ix, iy), textcoords="offset points",
                        xytext=(0, 14 if kind == "H" else -20),
                        ha="center", fontsize=13, fontweight="bold",
                        color=color, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.28", facecolor=BG,
                                  edgecolor=GOLD, linewidth=1.1, alpha=0.92))

    last = c[-1]
    ax.axhline(last, color=MUTED, linewidth=0.8, linestyle="--", alpha=0.6)
    ax.annotate(px(pair, last), (len(bars) - 1, last), textcoords="offset points",
                xytext=(8, 0), color=MUTED, fontsize=10, va="center")

    ax.set_title(f"{pair} · {tf} · Elliot Wave 8-gelombang (Fibonacci)",
                 color=TEXT, fontsize=17, fontweight="bold", pad=14, loc="left")
    ax.text(0, 1.012, f"{len(bars)} bar · {bars[0][0][:16]} → {bars[-1][0][:16]}",
            transform=ax.transAxes, color=MUTED, fontsize=10)

    badge_col = GOLD if valid else RED
    badge_txt = f"✔ {verdict}" if valid else f"⚠ {verdict}"
    ax.text(0.995, 1.012, badge_txt, transform=ax.transAxes,
            color=badge_col, fontsize=10.5, fontweight="bold", ha="right")

    # Panel ratio Fibonacci (bila kitaran sah)
    if valid and detail.get("ratios"):
        r = detail["ratios"]
        shp = detail.get("shape", "-")
        info = (f"W2 {r.get('r2', 0):.3f}  ·  W3 {r.get('r3', 0):.3f}x  ·  "
                f"W4 {r.get('r4', 0):.3f}  ·  W5 {r.get('r5', 0):.3f}x  ·  {shp}")
        ax.text(0, -0.075, info, transform=ax.transAxes, color=GOLD,
                fontsize=9.5, family="monospace")

    ax.tick_params(colors=MUTED, labelsize=9)
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: px(pair, v)))
    for s in ax.spines.values():
        s.set_color("#252b33")
    ax.grid(color="#ffffff0a", linewidth=0.7)
    ax.set_xlim(-2, len(bars) + 12)

    step = max(1, len(bars) // 8)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([bars[i][0][5:16].replace("T", " ") for i in xs[::step]],
                       rotation=0, ha="center", fontsize=8)

    out = REPO / "state" / f"elliot-{pair}-{tf}.png"
    plt.tight_layout()
    plt.savefig(out, facecolor=BG, bbox_inches="tight")
    plt.close()
    print("SAVED:", out)
    print("Pivots detected:", len(piv))
    print("Verdict:", verdict)
    if detail:
        print("  Fib:", " | ".join(detail.get("fib", [])))
        print("  Bentuk:", detail.get("shape_note", "-"))
    for (ix, iy, kind, lab) in marked:
        print(f"  Wave {lab}: {kind} @ {iy:,.2f} (bar {ix})")
    return out


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    tf = sys.argv[2] if len(sys.argv) > 2 else "M60"
    render(pair, tf)
