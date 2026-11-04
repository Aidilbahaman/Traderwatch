#!/usr/bin/env python3
"""Empat variasi design kad isyarat potret.

V1 minimal  — chrome minimum, chart mendominasi
V2 dense    — data padat, gaya terminal trading
V3 bignum   — nombor besar, kontras tinggi
V4 report   — gaya laporan, seksyen berstruktur

Semua: 1080 x 1620 (2:3), teks Telegram hanya pair/side/tf.
"""
import io, os, sys, pathlib

sys.path.insert(0, "/home/ubuntu/tw-bot")
os.environ.setdefault("BOT_TOKEN", "dummy")
import bot_v2 as bv2

BG = "#061a31"
INK = "#eaf2fa"
MUTED = "#8fb0cb"
LINE = "#1d4570"
GREEN = "#b7f34b"
RED = "#ff6b6b"
BLUE = "#8ab4ff"
TEAL = "#4dd0a5"
GOLD = "#f5c95c"

W, H = 1080, 1620


def _fmt_pair(p): return str(p).replace("_", "/")


def _price(pair, v):
    v = float(v)
    if "BTC" in pair.upper(): return f"{v:,.2f}"
    s = f"{v:.3f}" if ("JPY" in pair or "XAU" in pair) else f"{v:.5f}"
    return s.rstrip("0").rstrip(".")


def _move(sig, level):
    e, l = float(sig["entry"]), float(level)
    if "BTC" in sig["pair"].upper(): return f"${abs(l - e):,.2f}"
    pip = 0.1 if "XAU" in sig["pair"] else (0.01 if "JPY" in sig["pair"] else 0.0001)
    return f"{abs(l - e) / pip:.1f} pips"


def _rr(sig):
    e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    r = abs(e - sl)
    return abs(tp - e) / r if r else 0.0


def _base(sig, bars):
    """Sediakan axes biasa + data chart. Returns (fig, axc, pair, side, ...)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch, Rectangle
    from matplotlib.colors import LinearSegmentedColormap
    import numpy as np
    import pandas as pd
    import mplfinance as mpf

    pair = _fmt_pair(sig["pair"])
    side = str(sig["side"]).upper()
    fig = plt.figure(figsize=(10.8, 16.2), dpi=100)
    fig.patch.set_facecolor(BG)
    return fig


def _chart(axc, bars, sig):
    import pandas as pd
    import mplfinance as mpf
    idx = pd.to_datetime([b["t"] for b in bars], utc=True) \
            .tz_convert("Asia/Kuala_Lumpur").tz_localize(None)
    df = pd.DataFrame({"Open": [b["o"] for b in bars], "High": [b["h"] for b in bars],
                       "Low": [b["l"] for b in bars], "Close": [b["c"] for b in bars]},
                      index=idx)
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor=BG, figcolor=BG, gridcolor="#143452",
                               gridstyle=":")
    pad = max(6, int(len(df) * 0.30))
    mpf.plot(df, type="candle", style=style, ax=axc,
             datetime_format="%d/%m %H:%M", xrotation=0,
             xlim=(idx[0], idx[-1] + pd.Timedelta(minutes=15 * pad)))
    lv = [float(sig["entry"]), float(sig["sl"]), float(sig["tp"])]
    lo = min([float(b["l"]) for b in bars] + lv)
    hi = max([float(b["h"]) for b in bars] + lv)
    span = (hi - lo) or 1.0
    axc.set_ylim(lo - span * 0.09, hi + span * 0.09)
    for lvl, lab, col in zip(lv, ("ENTRY", "SL", "TP"), (BLUE, RED, TEAL)):
        axc.axhline(lvl, color=col, ls="--", lw=1.9, alpha=0.95, zorder=6)
        axc.text(0.008, lvl, f" {lab} {_price(sig['pair'], lvl)} ",
                 transform=axc.get_yaxis_transform(), va="bottom", ha="left",
                 fontsize=9.5, color="#08192b", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.2", fc=col, ec="none", alpha=0.97),
                 zorder=7, clip_on=True)
    axc.tick_params(colors=MUTED, labelsize=8.5)
    for s in axc.spines.values():
        s.set_color(LINE)


# ─────────────────────────── V1 MINIMAL ───────────────────────────
def v1_minimal(sig, bars):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch
    fig = _base(sig, bars)
    gs = gridspec.GridSpec(3, 1, height_ratios=[1.0, 7.2, 1.9], hspace=0.06,
                           left=0.055, right=0.945, top=0.975, bottom=0.018)
    side = str(sig["side"]).upper()
    col = GREEN if side == "BUY" else RED

    ax = fig.add_subplot(gs[0]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.72, _fmt_pair(sig["pair"]), fontsize=44, fontweight="bold",
            color=INK, ha="left", va="center")
    ax.text(0, 0.24, f"{sig.get('timeframe') or 'M15'}", fontsize=12,
            color=MUTED, ha="left", va="center")
    ax.add_patch(FancyBboxPatch((0.80, 0.22), 0.20, 0.56,
                                boxstyle="round,pad=0.014,rounding_size=0.05",
                                fc=col, ec="none"))
    ax.text(0.90, 0.50, side, ha="center", va="center", fontsize=19,
            fontweight="bold", color="#0b2b12" if side == "BUY" else "#3a0d0d")

    axc = fig.add_subplot(gs[1]); _chart(axc, bars, sig)

    ax2 = fig.add_subplot(gs[2]); ax2.axis("off"); ax2.set_xlim(0, 1); ax2.set_ylim(0, 1)
    e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    rows = [("Entry", _price(sig["pair"], e), BLUE, "—"),
            ("SL", _price(sig["pair"], sl), RED,
             _move(sig, sl).replace("pips", "p")),
            ("TP", _price(sig["pair"], tp), TEAL,
             "+" + _move(sig, tp).replace("pips", "p"))]
    for i, (lab, val, c, d) in enumerate(rows):
        y = 0.78 - i * 0.27
        ax2.text(0.0, y, lab, fontsize=11, color=MUTED, ha="left", va="center")
        ax2.text(0.22, y, val, fontsize=17, fontweight="bold", color=INK,
                 ha="left", va="center")
        ax2.text(0.62, y, d, fontsize=12, color=c, ha="left", va="center",
                 fontweight="bold")
    ax2.text(1.0, 0.08, f"R:R 1:{_rr(sig):.1f}", fontsize=15, fontweight="bold",
             color=GOLD, ha="right", va="center")
    return _save(fig, "v1-minimal")


# ─────────────────────────── V2 DENSE ───────────────────────────
def v2_dense(sig, bars):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch, Rectangle
    fig = _base(sig, bars)
    gs = gridspec.GridSpec(5, 1, height_ratios=[0.85, 4.9, 1.5, 1.5, 1.35],
                           hspace=0.05, left=0.045, right=0.955,
                           top=0.975, bottom=0.018)
    side = str(sig["side"]).upper()
    col = GREEN if side == "BUY" else RED

    ax = fig.add_subplot(gs[0]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(Rectangle((0, 0.30), 1.0, 0.44, fc="#0d2c4d", ec="none"))
    ax.text(0.02, 0.52, "TRADERWATCH", fontsize=10, fontweight="bold",
            color=GREEN, ha="left", va="center")
    ax.text(0.52, 0.52, "LIVE", fontsize=10, fontweight="bold",
            color=GREEN, ha="left", va="center")
    ax.text(0.68, 0.52, _fmt_pair(sig["pair"]), fontsize=13, fontweight="bold",
            color=INK, ha="left", va="center")
    ax.text(0.98, 0.52, f"{sig.get('timeframe') or 'M15'}", fontsize=11,
            color=MUTED, ha="right", va="center")

    axc = fig.add_subplot(gs[1]); _chart(axc, bars, sig)

    # grid metrik
    axm = fig.add_subplot(gs[2]); axm.axis("off"); axm.set_xlim(0, 1); axm.set_ylim(0, 1)
    e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    metrics = [("ENTRY", _price(sig["pair"], e), BLUE, "—"),
               ("STOP LOSS", _price(sig["pair"], sl), RED, f"-{_move(sig, sl)}"),
               ("TAKE PROFIT", _price(sig["pair"], tp), TEAL, f"+{_move(sig, tp)}")]
    cw, gap = 0.305, 0.0425
    for i, (lab, val, c, d) in enumerate(metrics):
        x = i * (cw + gap)
        axm.add_patch(FancyBboxPatch((x, 0.08), cw, 0.84,
                                     boxstyle="round,pad=0.012,rounding_size=0.02",
                                     fc="#0e3054", ec=c, lw=1.5))
        axm.text(x + cw / 2, 0.80, lab, fontsize=8.5, fontweight="bold",
                 color=MUTED, ha="center", va="center")
        axm.text(x + cw / 2, 0.55, val, fontsize=16, fontweight="bold",
                 color=INK, ha="center", va="center")
        axm.text(x + cw / 2, 0.28, d, fontsize=10.5, fontweight="bold",
                 color=c, ha="center", va="center")

    # bar RR
    axr = fig.add_subplot(gs[3]); axr.axis("off"); axr.set_xlim(0, 1); axr.set_ylim(0, 1)
    axr.add_patch(FancyBboxPatch((0, 0.10), 1.0, 0.78,
                                 boxstyle="round,pad=0.012,rounding_size=0.02",
                                 fc="#0a2743", ec=LINE, lw=1.2))
    axr.text(0.04, 0.49, "RISK : REWARD", fontsize=10, fontweight="bold",
             color=MUTED, ha="left", va="center")
    axr.text(0.96, 0.49, f"1 : {_rr(sig):.1f}", fontsize=20, fontweight="bold",
             color=GOLD, ha="right", va="center")

    # footer
    axf = fig.add_subplot(gs[4]); axf.axis("off"); axf.set_xlim(0, 1); axf.set_ylim(0, 1)
    axf.add_patch(FancyBboxPatch((0, 0.05), 1.0, 0.90,
                                 boxstyle="round,pad=0.012,rounding_size=0.02",
                                 fc="#0d3a24", ec=GREEN, lw=1.2))
    axf.text(0.05, 0.72, "$30  NEW TRADER OFFER", fontsize=11, fontweight="bold",
             color=GREEN, ha="left", va="center")
    axf.text(0.05, 0.42, "rinfinity.com · not financial advice · trade at your own risk",
             fontsize=9.5, color=MUTED, ha="left", va="center")
    return _save(fig, "v2-dense")


# ─────────────────────────── V3 BIG NUMBERS ───────────────────────────
def v3_bignum(sig, bars):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch
    fig = _base(sig, bars)
    gs = gridspec.GridSpec(4, 1, height_ratios=[1.15, 1.5, 5.2, 1.4], hspace=0.05,
                           left=0.055, right=0.945, top=0.975, bottom=0.018)
    side = str(sig["side"]).upper()
    col = GREEN if side == "BUY" else RED
    e = float(sig["entry"])

    ax = fig.add_subplot(gs[0]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.55, f"{'▲' if side == 'BUY' else '▼'} {side}", fontsize=15,
            fontweight="bold", color=col, ha="left", va="center")
    ax.text(1.0, 0.55, f"{sig.get('timeframe') or 'M15'}", fontsize=12,
            color=MUTED, ha="right", va="center")

    axn = fig.add_subplot(gs[1]); axn.axis("off"); axn.set_xlim(0, 1); axn.set_ylim(0, 1)
    axn.text(0.0, 0.62, _fmt_pair(sig["pair"]), fontsize=42, fontweight="bold",
             color=INK, ha="left", va="center")
    axn.text(0.0, 0.16, _price(sig["pair"], e), fontsize=30, fontweight="bold",
             color=BLUE, ha="left", va="center")

    axc = fig.add_subplot(gs[2]); _chart(axc, bars, sig)

    axl = fig.add_subplot(gs[3]); axl.axis("off"); axl.set_xlim(0, 1); axl.set_ylim(0, 1)
    axl.text(0.0, 0.72, f"SL  {_price(sig['pair'], sig['sl'])}  ({_move(sig, sig['sl'])})",
             fontsize=13, fontweight="bold", color=RED, ha="left", va="center")
    axl.text(0.0, 0.32, f"TP  {_price(sig['pair'], sig['tp'])}  (+{_move(sig, sig['tp'])})",
             fontsize=13, fontweight="bold", color=TEAL, ha="left", va="center")
    axl.text(0.0, 0.0, f"R:R  1 : {_rr(sig):.1f}", fontsize=15, fontweight="bold",
             color=GOLD, ha="left", va="top")
    axl.text(1.0, 0.0, "not financial advice", fontsize=9, color=MUTED,
             ha="right", va="top")
    return _save(fig, "v3-bignum")


# ─────────────────────────── V4 REPORT ───────────────────────────
def v4_report(sig, bars):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch, Rectangle
    fig = _base(sig, bars)
    gs = gridspec.GridSpec(6, 1, height_ratios=[1.0, 0.55, 4.3, 0.4, 2.0, 1.35],
                           hspace=0.05, left=0.06, right=0.94,
                           top=0.975, bottom=0.018)
    side = str(sig["side"]).upper()
    col = GREEN if side == "BUY" else RED
    e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])

    ax = fig.add_subplot(gs[0]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(Rectangle((0, 0.15), 1.0, 0.70, fc="#0d2c4d", ec="none"))
    ax.add_patch(Rectangle((0, 0.15), 0.006, 0.70, fc=GREEN, ec="none"))
    ax.text(0.035, 0.62, "SIGNAL REPORT", fontsize=10, fontweight="bold",
            color=GREEN, ha="left", va="center")
    ax.text(0.035, 0.30, f"{_fmt_pair(sig['pair'])} · {sig.get('timeframe') or 'M15'}",
            fontsize=19, fontweight="bold", color=INK, ha="left", va="center")
    ax.text(0.965, 0.50, f"{'▲' if side == 'BUY' else '▼'} {side}", fontsize=16,
            fontweight="bold", color=col, ha="right", va="center")

    axs = fig.add_subplot(gs[1]); axs.axis("off"); axs.set_xlim(0, 1); axs.set_ylim(0, 1)
    axs.text(0.0, 0.5, "MARKET STRUCTURE · M15", fontsize=9, fontweight="bold",
             color=MUTED, ha="left", va="center")

    axc = fig.add_subplot(gs[2]); _chart(axc, bars, sig)

    axd = fig.add_subplot(gs[3]); axd.axis("off"); axd.set_xlim(0, 1); axd.set_ylim(0, 1)
    axd.plot([0.0, 1.0], [0.5, 0.5], color=LINE, lw=1)

    axt = fig.add_subplot(gs[4]); axt.axis("off"); axt.set_xlim(0, 1); axt.set_ylim(0, 1)
    rows = [("ENTRY", _price(sig["pair"], e), "—", BLUE),
            ("STOP LOSS", _price(sig["pair"], sl), f"-{_move(sig, sl)}", RED),
            ("TAKE PROFIT", _price(sig["pair"], tp), f"+{_move(sig, tp)}", TEAL),
            ("RISK : REWARD", f"1 : {_rr(sig):.1f}", "", GOLD)]
    for i, (lab, val, d, c) in enumerate(rows):
        y = 0.88 - i * 0.24
        axt.add_patch(Rectangle((0, y - 0.10), 1.0, 0.20,
                                fc="#0e3054" if i % 2 == 0 else "none",
                                ec="none"))
        axt.text(0.03, y, lab, fontsize=10.5, fontweight="bold", color=MUTED,
                 ha="left", va="center")
        axt.text(0.50, y, val, fontsize=15, fontweight="bold", color=INK,
                 ha="left", va="center")
        axt.text(0.97, y, d, fontsize=11, fontweight="bold", color=c,
                 ha="right", va="center")

    axf = fig.add_subplot(gs[5]); axf.axis("off"); axf.set_xlim(0, 1); axf.set_ylim(0, 1)
    axf.add_patch(FancyBboxPatch((0, 0.05), 1.0, 0.88,
                                 boxstyle="round,pad=0.012,rounding_size=0.02",
                                 fc="#0d3a24", ec=GREEN, lw=1.2))
    axf.text(0.05, 0.66, "$30 NEW TRADER OFFER", fontsize=11, fontweight="bold",
             color=GREEN, ha="left", va="center")
    axf.text(0.05, 0.36, "rinfinity.com · not financial advice · trade at your own risk",
             fontsize=9.5, color=MUTED, ha="left", va="center")
    return _save(fig, "v4-report")


def _save(fig, name):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=BG, bbox_inches="tight",
                pad_inches=0.12)
    import matplotlib.pyplot as plt
    plt.close(fig)
    out = f"/home/ubuntu/web/out/card-{name}.png"
    pathlib.Path(out).write_bytes(buf.getvalue())
    return out, len(buf.getvalue())


VARIANTS = {"v1": v1_minimal, "v2": v2_dense, "v3": v3_bignum, "v4": v4_report}


def build(pair="BTCUSD"):
    m15 = bv2.get_candles(pair, "M15", 120)
    px = float(m15[-1]["c"])
    if "BTC" in pair:
        entry, sl, tp = round(px, 2), round(px * 0.997, 2), round(px * 1.006, 2)
    else:
        entry, sl, tp = round(px, 5), round(px * 0.997, 5), round(px * 1.006, 5)
    sig = {"pair": bv2.PAIR_PUBLIC.get(pair, pair), "side": "BUY",
           "entry": entry, "sl": sl, "tp": tp, "timeframe": "M15"}
    out = []
    for key, fn in VARIANTS.items():
        path, size = fn(sig, m15[-96:])
        out.append((key, path, size))
        print(f"{key}: {path} ({size} bytes)")
    return sig, out


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSD"
    build(pair)
