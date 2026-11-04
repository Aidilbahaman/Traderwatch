#!/usr/bin/env python3
"""TraderWatch signal card — satu gambar potret memanjang.

Teks Telegram hanya: "🟢 BUY BTC/USD · M15".
Semua konteks lain (chart, level, R:R, disclaimer, promo) masuk dalam PNG.

Output: 1080 x 1620 px (2:3 potret), tema gelap navy.
"""
import io
import sys

# Tema
BG_TOP = "#061a31"
BG_BOT = "#0b3255"
INK = "#eaf2fa"
MUTED = "#8fb0cb"
LINE = "#1d4570"
GREEN = "#b7f34b"
RED = "#ff6b6b"
BLUE = "#8ab4ff"
TEAL = "#4dd0a5"
GOLD = "#f5c95c"

CARD_W, CARD_H = 1080, 1620


def _fmt_pair(pair):
    return str(pair).replace("_", "/")


def _is_btc(pair):
    return "BTC" in str(pair).upper()


def _price(pair, value):
    v = float(value)
    if _is_btc(pair):
        return f"{v:,.2f}"
    s = f"{v:.3f}" if ("JPY" in str(pair) or "XAU" in str(pair)) else f"{v:.5f}"
    return s.rstrip("0").rstrip(".")


def _move(sig, level):
    entry, lv = float(sig["entry"]), float(level)
    if _is_btc(sig["pair"]):
        return f"${abs(lv - entry):,.2f}"
    pip = 0.1 if "XAU" in str(sig["pair"]) else (0.01 if "JPY" in str(sig["pair"]) else 0.0001)
    return f"{abs(lv - entry) / pip:.1f} pips"


def _rr(sig):
    e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    risk = abs(e - sl)
    return abs(tp - e) / risk if risk else 0.0


def render_signal_card(sig, bars=None, pair_label=None, source="COINBASE"):
    """Render kad isyarat potret. Returns PNG bytes or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        from matplotlib.patches import FancyBboxPatch, Rectangle
        import numpy as np
        import pandas as pd
        import mplfinance as mpf
    except ImportError as ex:
        print(f"CARD-IMPORT-FAIL {ex}", file=sys.stderr)
        return None

    pair = _fmt_pair(pair_label or sig["pair"])
    side = str(sig["side"]).upper()
    is_buy = side == "BUY"
    side_col = GREEN if is_buy else RED
    tf = sig.get("timeframe") or "M15"
    entry, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    rr = _rr(sig)

    fig = plt.figure(figsize=(10.8, 16.2), dpi=100)
    fig.patch.set_facecolor(BG_TOP)

    gs = gridspec.GridSpec(
        5, 1, figure=fig,
        height_ratios=[2.15, 5.6, 2.5, 1.35, 1.5],
        hspace=0.055,
        left=0.055, right=0.945, top=0.975, bottom=0.018)

    # ---------- latar gradien ----------
    axbg = fig.add_axes([0, 0, 1, 1], zorder=-10)
    axbg.axis("off")
    grad = np.linspace(0, 1, 256).reshape(-1, 1)
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("tw", [BG_TOP, BG_BOT])
    axbg.imshow(grad, aspect="auto", cmap=cmap, extent=[0, 1, 0, 1], zorder=-10)

    # ---------- header ----------
    axh = fig.add_subplot(gs[0])
    axh.axis("off")
    axh.set_xlim(0, 1)
    axh.set_ylim(0, 1)
    # baris jenama
    axh.add_patch(FancyBboxPatch((0.0, 0.735), 0.075, 0.235,
                                 boxstyle="round,pad=0.012,rounding_size=0.018",
                                 fc=GREEN, ec="none", zorder=3))
    axh.text(0.0375, 0.8525, "T", ha="center", va="center",
             fontsize=24, fontweight="bold", color=BG_TOP, zorder=4)
    axh.text(0.095, 0.895, "TRADERWATCH", ha="left", va="center",
             fontsize=19, fontweight="bold", color=INK, zorder=4)
    axh.text(0.095, 0.775, "SUPER INTELLIGENT AGENTS", ha="left", va="center",
             fontsize=9, color=MUTED, zorder=4)
    axh.add_patch(FancyBboxPatch((0.775, 0.775), 0.225, 0.175,
                                 boxstyle="round,pad=0.012,rounding_size=0.03",
                                 fc="#123a5e", ec=LINE, lw=1.2, zorder=3))
    axh.text(0.8875, 0.8625, "LIVE SIGNAL", ha="center", va="center",
             fontsize=10.5, fontweight="bold", color=GREEN, zorder=4)
    # tajuk pair
    axh.text(0.0, 0.34, pair, ha="left", va="center",
             fontsize=46, fontweight="bold", color=INK, zorder=4)
    axh.text(0.0, 0.135, f"{tf} · {source}", ha="left", va="center",
             fontsize=12, color=MUTED, zorder=4)
    # badge arah
    axh.add_patch(FancyBboxPatch((0.655, 0.20), 0.345, 0.235,
                                 boxstyle="round,pad=0.014,rounding_size=0.04",
                                 fc=side_col, ec="none", zorder=3))
    axh.text(0.8275, 0.3175, f"{'▲' if is_buy else '▼'} {side}",
             ha="center", va="center", fontsize=20, fontweight="bold",
             color="#0b2b12" if is_buy else "#3a0d0d", zorder=4)

    # ---------- chart ----------
    axc = fig.add_subplot(gs[1])
    if bars and len(bars) >= 10:
        idx = pd.to_datetime([b["t"] for b in bars], utc=True) \
                .tz_convert("Asia/Kuala_Lumpur").tz_localize(None)
        df = pd.DataFrame({"Open": [b["o"] for b in bars],
                           "High": [b["h"] for b in bars],
                           "Low": [b["l"] for b in bars],
                           "Close": [b["c"] for b in bars]}, index=idx)
        mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                                   edge="inherit", wick="inherit")
        style = mpf.make_mpf_style(base_mpf_style="nightclouds",
                                   marketcolors=mc, facecolor=BG_TOP,
                                   figcolor=BG_TOP, gridcolor="#143452",
                                   gridstyle=":")
        pad_n = max(6, int(len(df) * 0.30))
        mpf.plot(df, type="candle", style=style, ax=axc,
                 datetime_format="%d/%m %H:%M", xrotation=0,
                 xlim=(idx[0], idx[-1] + pd.Timedelta(minutes=15 * pad_n)))
        lv = [entry, sl, tp]
        lo = min([float(b["l"]) for b in bars] + lv)
        hi = max([float(b["h"]) for b in bars] + lv)
        span = (hi - lo) or (abs(hi) * 0.001 or 1.0)
        axc.set_ylim(lo - span * 0.08, hi + span * 0.08)
        for lvl, lab, col in zip(lv, ("ENTRY", "SL", "TP"),
                                 (BLUE, RED, TEAL)):
            axc.axhline(lvl, color=col, ls="--", lw=1.9, alpha=0.95, zorder=6)
            axc.text(0.008, lvl, f" {lab} {_price(sig['pair'], lvl)} ",
                     transform=axc.get_yaxis_transform(), va="bottom", ha="left",
                     fontsize=9.5, color="#08192b", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.2", fc=col, ec="none",
                               alpha=0.97), zorder=7, clip_on=True)
        axc.tick_params(colors=MUTED, labelsize=8.5)
        for s in axc.spines.values():
            s.set_color(LINE)
    else:
        axc.axis("off")
        axc.text(0.5, 0.5, "chart data unavailable", ha="center", va="center",
                 color=MUTED, fontsize=13, transform=axc.transAxes)

    # ---------- level cards ----------
    axl = fig.add_subplot(gs[2])
    axl.axis("off")
    axl.set_xlim(0, 1)
    axl.set_ylim(0, 1)
    cards = [("ENTRY", _price(sig["pair"], entry), BLUE, ""),
             ("STOP LOSS", _price(sig["pair"], sl), RED, f"-{_move(sig, sl)}"),
             ("TAKE PROFIT", _price(sig["pair"], tp), TEAL, f"+{_move(sig, tp)}")]
    w, gap = 0.305, 0.0425
    for i, (lab, val, col, delta) in enumerate(cards):
        x = i * (w + gap)
        axl.add_patch(FancyBboxPatch((x, 0.46), w, 0.46,
                                     boxstyle="round,pad=0.012,rounding_size=0.02",
                                     fc="#0e3054", ec=col, lw=1.6, zorder=3))
        axl.add_patch(Rectangle((x, 0.88), w, 0.045, fc=col, ec="none", zorder=4))
        axl.text(x + w / 2, 0.80, lab, ha="center", va="center",
                 fontsize=9, fontweight="bold", color=MUTED, zorder=5)
        axl.text(x + w / 2, 0.63, val, ha="center", va="center",
                 fontsize=19, fontweight="bold", color=INK, zorder=5)
        if delta:
            axl.text(x + w / 2, 0.52, delta, ha="center", va="center",
                     fontsize=11, fontweight="bold", color=col, zorder=5)

    # ---------- R:R strip ----------
    axl.add_patch(FancyBboxPatch((0.0, 0.06), 1.0, 0.32,
                                 boxstyle="round,pad=0.012,rounding_size=0.02",
                                 fc="#0a2743", ec=LINE, lw=1.2, zorder=3))
    axl.text(0.045, 0.22, "RISK : REWARD", ha="left", va="center",
             fontsize=10, fontweight="bold", color=MUTED, zorder=5)
    axl.text(0.955, 0.22, f"1 : {rr:.1f}", ha="right", va="center",
             fontsize=21, fontweight="bold", color=GOLD, zorder=5)

    # ---------- footer ----------
    axf = fig.add_subplot(gs[3])
    axf.axis("off")
    axf.set_xlim(0, 1)
    axf.set_ylim(0, 1)
    axf.text(0.5, 0.72, "This is a live price update, not financial advice.",
             ha="center", va="center", fontsize=11.5, color=INK)
    axf.text(0.5, 0.40, "We publish the setup — you decide whether to trade.",
             ha="center", va="center", fontsize=11.5, color=INK)
    axf.text(0.5, 0.10, "Trade at your own risk. Past results do not guarantee future outcomes.",
             ha="center", va="center", fontsize=9.5, color=MUTED)

    # ---------- promo ----------
    axp = fig.add_subplot(gs[4])
    axp.axis("off")
    axp.set_xlim(0, 1)
    axp.set_ylim(0, 1)
    axp.add_patch(FancyBboxPatch((0.0, 0.10), 1.0, 0.80,
                                 boxstyle="round,pad=0.014,rounding_size=0.025",
                                 fc="#0d3a24", ec=GREEN, lw=1.4, zorder=3))
    # lencana $30 (bentuk dilukis — font sistem tiada emoji gift)
    axp.add_patch(FancyBboxPatch((0.045, 0.40), 0.115, 0.42,
                                 boxstyle="round,pad=0.010,rounding_size=0.025",
                                 fc=GREEN, ec="none", zorder=4))
    axp.text(0.1025, 0.61, "$30", ha="center", va="center",
             fontsize=17, fontweight="bold", color="#0b2b12", zorder=5)
    axp.text(0.185, 0.70, "NEW TRADER OFFER", ha="left", va="center",
             fontsize=11, fontweight="bold", color=GREEN, zorder=4)
    axp.text(0.185, 0.42, "Claim a $30 welcome bonus", ha="left", va="center",
             fontsize=17, fontweight="bold", color=INK, zorder=4)
    axp.text(0.045, 0.19, "rinfinity.com · eligibility & terms apply",
             ha="left", va="center", fontsize=9.5, color=MUTED, zorder=4)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=BG_TOP,
                bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()


def short_caption(sig):
    """Teks Telegram sahaja — pair, side, timeframe."""
    side = str(sig["side"]).upper()
    arrow = "🟢 BUY" if side == "BUY" else "🔴 SELL"
    return f"{arrow} {_fmt_pair(sig['pair'])} · {sig.get('timeframe') or 'M15'}"


if __name__ == "__main__":
    # Ujian pantas dengan data sebenar
    sys.path.insert(0, "/home/ubuntu/tw-bot")
    import os
    os.environ.setdefault("BOT_TOKEN", "dummy")
    import bot_v2 as bv2
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSD"
    m15 = bv2.get_candles(pair, "M15", 120)
    px = float(m15[-1]["c"])
    sig = {"pair": bv2.PAIR_PUBLIC.get(pair, pair), "side": "BUY",
           "entry": round(px, 2), "sl": round(px * 0.997, 2),
           "tp": round(px * 1.006, 2), "timeframe": "M15"}
    png = render_signal_card(sig, m15[-96:],
                             source="COINBASE" if "BTC" in pair else "SWISSQUOTE")
    out = f"/home/ubuntu/web/out/card-{pair.lower()}.png"
    import pathlib
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_bytes(png)
    print("saved", out, len(png), "bytes")
    print("caption:", short_caption(sig))
    print("levels:", sig["entry"], sig["sl"], sig["tp"], f"R:R 1:{_rr(sig):.2f}")
