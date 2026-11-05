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


def render(pair="XAUUSD", tf="M60", limit=300, stale_style="ghost"):
    """stale_style: "none" (zon sahaja) · "ghost" (label pudar + masa) ·
    "extend" (label penuh + garis sambung ke harga semasa)."""
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

    # Jika kitaran berlabel tamat jauh dari harga semasa, label gelombang
    # mengelirukan. Ganti dengan paparan "FASA PEMBENTUKAN": tiada nombor
    # gelombang, hanya zon harga terkini + arah belum selesai.
    stale = (detail or {}).get("staleness_bars", 0) if valid else 999
    show_formation = (not valid) or stale > 12

    # MOD D (stale_style="ghost"): tunjuk label gelombang tetapi dipudarkan
    # dengan tanda masa, supaya struktur sejarah nampak tanpa mengelirukan.
    # MOD E (stale_style="extend"): tunjuk label penuh + sambungan garis ke harga semasa.
    if marked and (not show_formation or stale_style in ("ghost", "extend")):
        ghost = show_formation and stale_style == "ghost"
        line_col = "#6b6250" if ghost else GOLD
        lab_col = "#8a7f66" if ghost else GOLD
        lw = 1.4 if ghost else 2.0
        alpha = 0.55 if ghost else 1.0
        wx = [p[0] for p in marked]
        wy = [p[1] for p in marked]

        # MOD E: sambung garis dari pivot terakhir ke harga semasa
        if show_formation and stale_style == "extend":
            wx = wx + [len(bars) - 1]
            wy = wy + [c[-1]]

        ax.plot(wx, wy, color=line_col, linewidth=lw, linestyle="--" if ghost else "-",
                marker="o", markersize=6 if ghost else 7, markerfacecolor=BG,
                markeredgecolor=line_col, markeredgewidth=1.4, zorder=5, alpha=alpha)
        for (ix, iy, kind, lab) in marked:
            ax.annotate(lab, (ix, iy), textcoords="offset points",
                        xytext=(0, 14 if kind == "H" else -20),
                        ha="center", fontsize=12 if ghost else 13, fontweight="bold",
                        color=lab_col, zorder=6, alpha=alpha,
                        bbox=dict(boxstyle="round,pad=0.26", facecolor=BG,
                                  edgecolor=lab_col, linewidth=1.0, alpha=0.9))
        if ghost:
            ax.annotate(f"struktur {stale} jam lalu",
                        xy=(wx[-1], wy[-1]), xytext=(6, -26),
                        textcoords="offset points", fontsize=9,
                        color="#8a7f66", style="italic", zorder=7)

    # Zon harga semasa (dipapar untuk semua mod bila stale)
    if show_formation and piv:
        recent = [p for p in piv if p[0] >= len(bars) - 40]
        if len(recent) >= 2 and stale_style != "extend":
            ax.plot([p[0] for p in recent], [p[1] for p in recent],
                    color=BLUE, linewidth=1.8, linestyle="--", alpha=0.75,
                    marker="o", markersize=5, markerfacecolor=BG,
                    markeredgecolor=BLUE, markeredgewidth=1.6, zorder=5)
        zlo = min(b[3] for b in bars[-40:])
        zhi = max(b[2] for b in bars[-40:])
        ax.axhspan(zlo, zhi, xmin=max(0, 1 - 40 / len(bars)), xmax=1,
                   color=BLUE, alpha=0.07, zorder=1)
        ax.annotate(f"ZON SEMASA\n{px(pair, zlo)} — {px(pair, zhi)}",
                    xy=(len(bars) - 20, zhi), xytext=(len(bars) - 20, zhi),
                    ha="center", va="bottom", fontsize=9.5, fontweight="bold",
                    color=BLUE, zorder=7,
                    bbox=dict(boxstyle="round,pad=0.4", facecolor=BG,
                              edgecolor=BLUE, linewidth=1.2, alpha=0.92))

    last = c[-1]
    ax.axhline(last, color=MUTED, linewidth=0.8, linestyle="--", alpha=0.6)
    ax.annotate(px(pair, last), (len(bars) - 1, last), textcoords="offset points",
                xytext=(8, 0), color=MUTED, fontsize=10, va="center")

    ax.set_title(f"{pair} · {tf} · "
                 + ("Fasa Pembentukan (kitaran baru)" if show_formation
                    else "Elliot Wave 8-gelombang (Fibonacci)"),
                 color=TEXT, fontsize=17, fontweight="bold", pad=14, loc="left")
    ax.text(0, 1.012, f"{len(bars)} bar · {bars[0][0][:16]} → {bars[-1][0][:16]}",
            transform=ax.transAxes, color=MUTED, fontsize=10)

    if show_formation:
        badge_col = BLUE
        badge_txt = ("[..] FASA PEMBENTUKAN - gelombang baru belum selesai"
                     if valid else f"⚠ {verdict}")
    else:
        badge_col = GOLD
        badge_txt = f"[OK] {verdict}"
    ax.text(0.995, 1.012, badge_txt, transform=ax.transAxes,
            color=badge_col, fontsize=10.5, fontweight="bold", ha="right")

    # Panel ratio Fibonacci (bila kitaran sah)
    if valid and not show_formation and detail.get("ratios"):
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
    # Margin: kiri kecil, KANAN lapang untuk panel probabiliti & label
    ax.set_xlim(-3, len(bars) + 55)

    step = max(1, len(bars) // 8)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([bars[i][0][5:16].replace("T", " ") for i in xs[::step]],
                       rotation=0, ha="center", fontsize=8)

    # ---------- PROBABILITY WAVE 4 ----------
    # Statistik klasik: Wave 4 paling kerap retrace 23.6%–38.2% Wave 3, dan
    # hampir tidak pernah bertindih wilayah Wave 1. Kira kebarangkalian
    # berdasarkan kedudukan harga SEMASA, bukan tekaan.
    if valid and marked and len(marked) >= 5:
        try:
            p3 = marked[3][1]   # Wave 3
            p4 = marked[4][1]   # Wave 4
            p5 = marked[5][1]   # Wave 5
            p2 = marked[2][1]   # Wave 2
            w3_range = abs(p3 - p2)
            lo_236 = p3 - w3_range * 0.236
            lo_382 = p3 - w3_range * 0.382
            lo_500 = p3 - w3_range * 0.500
            # Zon sasaran Wave 4 yang sah (tidak masuk wilayah Wave 1)
            p1 = marked[1][1]   # Wave 1 (had wilayah)
            zmin = min(p1, lo_500)
            zmax = max(lo_236, zmin) if lo_236 > zmin else lo_236
            cur = bars[-1][4]

            # Kebarangkalian: berapa dekat harga semasa dengan zon Wave 4 klasik
            if zmax >= zmin and zmin <= cur <= zmax:
                prob = 78
                note = "harga dalam zon retrace 23.6–50%"
            elif cur > zmax:
                prob = 55
                note = "harga atas zon — Wave 4 belum mula"
            else:
                prob = 40
                note = "harga bawah zon — struktur berisiko"

            ax.axhspan(lo_382, lo_236, xmin=max(0, 1 - 60 / len(bars)), xmax=1,
                       color="#f3cb75", alpha=0.10, zorder=1)
            ax.annotate(
                f"WAVE 4 TARGET\n{px(pair, lo_382)} — {px(pair, lo_236)}\n"
                f"probabiliti ~{prob}%  ·  {note}",
                xy=(len(bars) + 12, (lo_236 + lo_382) / 2),
                ha="left", va="center", fontsize=9, fontweight="bold",
                color=GOLD, zorder=8,
                bbox=dict(boxstyle="round,pad=0.45", facecolor=BG,
                          edgecolor=GOLD, linewidth=1.2, alpha=0.94))
            # Garis sasaran mendatar
            for lv, tag in ((lo_236, "23.6%"), (lo_382, "38.2%")):
                ax.plot([len(bars) - 60, len(bars) + 8], [lv, lv],
                        color=GOLD, linewidth=0.9, linestyle=":", alpha=0.7, zorder=4)
        except Exception:
            pass

    suffix = "" if stale_style == "ghost" else f"-{stale_style}"
    out = REPO / "state" / f"elliot-{pair}-{tf}{suffix}.png"
    plt.subplots_adjust(left=0.075, right=0.90, top=0.90, bottom=0.115)
    plt.savefig(out, facecolor=BG)
    plt.close()
    print("SAVED:", out)
    print("Pivots detected:", len(piv))
    print("Verdict:", verdict)
    if detail:
        print("  Fib:", " | ".join(detail.get("fib", [])))
        print("  Bentuk:", detail.get("shape_note", "-"))
    if show_formation:
        zlo = min(b[3] for b in bars[-40:]); zhi = max(b[2] for b in bars[-40:])
        print(f"  [FASA PEMBENTUKAN] zon {px(pair, zlo)} — {px(pair, zhi)} · harga {px(pair, bars[-1][4])}")
    else:
        for (ix, iy, kind, lab) in marked:
            print(f"  Wave {lab}: {kind} @ {iy:,.2f} (bar {ix})")
    return out


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    tf = sys.argv[2] if len(sys.argv) > 2 else "M60"
    render(pair, tf)
