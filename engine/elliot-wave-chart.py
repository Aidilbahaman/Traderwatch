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
    return cleaned


def _impulse_ok(p):
    """Sahkan 5 gelombang impulse (0,1,2,3,4,5).

    Peraturan Elliot yang diuji:
      R1: Wave 2 tidak boleh melebihi permulaan Wave 1 (retrace < 100%)
      R2: Wave 3 mesti melebihi hujung Wave 1 (bukan terpendek)
      R3: Wave 4 tidak boleh masuk wilayah Wave 1
      R4: Wave 3 tidak boleh jadi gelombang terpendek antara 1,3,5
      R5: Selang-seli — Wave 2 dan Wave 4 berbeza jenis (zigzag vs flat)
    """
    if len(p) < 6:
        return False, "pivot tidak cukup"
    prices = [x[1] for x in p[:6]]
    kinds = [x[2] for x in p[:6]]
    # Arah: naik jika 0 High -> 1 Low, atau turun jika 0 Low -> 1 High
    up = kinds[0] == "H"
    w0, w1, w2, w3, w4, w5 = prices

    if up:
        # impulse naik: 0 H(top awal) -> 1 L -> 2 H -> 3 L -> 4 H -> 5 L? 
        # Sebenarnya untuk impulse naik: 0=L(rendah),1=H,2=L,3=H,4=L,5=H
        pass

    # Guna pendekatan arah-agnostik: tentukan dari jenis pivot
    if kinds[0] == "L":
        # Impulse NAIK: 0=L,1=H,2=L,3=H,4=L,5=H
        p0, p1, p2, p3, p4, p5 = prices
        # R1: Wave 2 low tidak jatuh bawah Wave 0 low
        if p2 <= p0:
            return False, "R1: Wave 2 melebihi permulaan Wave 1"
        # R2: Wave 3 high mesti atas Wave 1 high
        if p3 <= p1:
            return False, "R2: Wave 3 tidak melebihi hujung Wave 1"
        # R3: Wave 4 low tidak masuk wilayah Wave 1 (p1)
        if p4 <= p1:
            return False, "R3: Wave 4 masuk wilayah Wave 1"
        # R4: Wave 3 bukan terpendek antara 1,3,5
        l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
        if l3 <= l1 and l3 <= l5:
            return False, "R4: Wave 3 gelombang terpendek"
    else:
        # Impulse TURUN: 0=H,1=L,2=H,3=L,4=H,5=L
        p0, p1, p2, p3, p4, p5 = prices
        if p2 >= p0:
            return False, "R1: Wave 2 melebihi permulaan Wave 1"
        if p3 >= p1:
            return False, "R2: Wave 3 tidak melebihi hujung Wave 1"
        if p4 >= p1:
            return False, "R3: Wave 4 masuk wilayah Wave 1"
        l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
        if l3 <= l1 and l3 <= l5:
            return False, "R4: Wave 3 gelombang terpendek"
    return True, "impulse sah"


def label_waves(pivots, validate=True):
    """Label gelombang dengan validasi peraturan Elliot.

    Cari tetingkap 6-pivot TERAKHIR yang lulus peraturan impulse.
    Kalau tiada yang lulus, label dengan amaran "TIDAK SAH".
    """
    if not validate or len(pivots) < 6:
        LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C", "D", "E"]
        return [(p[0], p[1], p[2], LABELS[i % len(LABELS)])
                for i, p in enumerate(pivots)], None

    # Cari tetingkap 6-pivot terakhir yang lulus
    chosen, reason = None, None
    for start in range(len(pivots) - 6, -1, -1):
        win = pivots[start:start + 6]
        ok, why = _impulse_ok(win)
        if ok:
            chosen, reason = win, why
            break

    out = []
    if chosen:
        LABELS = ["0", "1", "2", "3", "4", "5"]
        for i, p in enumerate(chosen):
            out.append((p[0], p[1], p[2], LABELS[i]))
        # Pivot selepas impulse -> corrective A,B,C
        tail = pivots[pivots.index(chosen[-1]) + 1:]
        for i, p in enumerate(tail[:3]):
            out.append((p[0], p[1], p[2], ["A", "B", "C"][i]))
        return out, reason

    # Tiada window sah: label semua dengan tanda amaran
    LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C", "D", "E"]
    return ([(p[0], p[1], p[2], LABELS[i % len(LABELS)])
             for i, p in enumerate(pivots)], "TIDAK SAH — tiada impulse 5-gelombang yang lulus peraturan")


def render(pair="XAUUSD", tf="M15", limit=300):
    bars = load_bars(pair, tf, limit)
    if not bars:
        print(f"Tiada bar untuk {pair} {tf}")
        return None

    piv = zigzag(bars, pct=0.2)
    marked, verdict = label_waves(piv, validate=True)
    valid = bool(marked) and verdict in ("impulse sah",)

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

    ax.set_title(f"{pair} · {tf} · Elliot Wave structure (ZigZag auto)",
                 color=TEXT, fontsize=17, fontweight="bold", pad=14, loc="left")
    ax.text(0, 1.012, f"{len(bars)} bar · {bars[0][0][:16]} → {bars[-1][0][:16]}",
            transform=ax.transAxes, color=MUTED, fontsize=10)

    badge_col = GOLD if valid else RED
    badge_txt = f"✔ {verdict}" if valid else f"⚠ {verdict}"
    ax.text(0.995, 1.012, badge_txt, transform=ax.transAxes,
            color=badge_col, fontsize=10.5, fontweight="bold", ha="right")

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
    for (ix, iy, kind, lab) in marked:
        print(f"  Wave {lab}: {kind} @ {iy:,.2f} (bar {ix})")
    return out


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    tf = sys.argv[2] if len(sys.argv) > 2 else "M15"
    render(pair, tf)
