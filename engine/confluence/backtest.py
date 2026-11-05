"""Fasa 5 — Backtest & walk-forward dengan kos dagangan (spec §4.2).

Model kos:
  - Spread: ikut instrumen (dari decision.SPREAD_LIMITS, tukar ke harga)
  - Komisen: configurable per lot/round-trip
  - Swap: configurable per malam (opsional)
  - Slippage: configurable dalam point

Metrik (spec §4.3): n, WR + CI, expectancy R, PF, avg win/loss, max DD,
MAE/MFE, pecahan ikut symbol/regime/sesi/arah.

Splits: kronologi 70/30 (IS/OOS) + walk-forward rolling.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


# ---------- kos dagangan ----------
def spread_cost_price(symbol, price, spread_points=None):
    """Spread dalam unit harga."""
    from . import instruments as ins, decision as dc
    m = ins.meta(symbol)
    pts = spread_points if spread_points is not None \
        else dc.SPREAD_LIMITS.get(symbol, dc.SPREAD_LIMITS["DEFAULT"])
    return pts * m["point_size"]


def trade_cost(symbol, price, lots=1.0, commission_per_lot=0.0,
               slippage_points=0.0):
    """Jumlah kos satu leg (masuk ATAU keluar) dalam unit harga."""
    from . import instruments as ins
    m = ins.meta(symbol)
    slip = slippage_points * m["point_size"]
    return spread_cost_price(symbol, price) / 2 + slip


# ---------- simulasi satu trade ----------
def simulate(bars, entry_idx, side, entry, sl, tp, expiry_bars=16,
             symbol=None, mae_mfe=True):
    """Simulasi dari bar entry_idx+1 (causal). Pulangkan hasil trade.

    entry_idx: bar di mana signal dibuat (entry tidak boleh pada bar ini)
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    out = {"result": "OPEN", "bars_held": 0, "exit": None,
           "mae_R": 0.0, "mfe_R": 0.0, "r_multiple": 0.0}
    end = min(len(bars), entry_idx + 1 + expiry_bars)
    for k in range(entry_idx + 1, end):
        b = bars[k]
        hi, lo = b["high"], b["low"]
        # MAE/MFE
        if side == "BUY":
            out["mfe_R"] = max(out["mfe_R"], (hi - entry) / risk)
            out["mae_R"] = min(out["mae_R"], (lo - entry) / risk)
        else:
            out["mfe_R"] = max(out["mfe_R"], (entry - lo) / risk)
            out["mae_R"] = min(out["mae_R"], (entry - hi) / risk)
        # SL dulu (konservatif — kalau dua-dua kena dalam bar sama, anggap SL)
        hit_sl = lo <= sl if side == "BUY" else hi >= sl
        hit_tp = hi >= tp if side == "BUY" else lo <= tp
        if hit_sl:
            out.update(result="HIT_SL", exit=sl,
                       bars_held=k - entry_idx,
                       r_multiple=-1.0)
            return out
        if hit_tp:
            out.update(result="HIT_TP", exit=tp,
                       bars_held=k - entry_idx,
                       r_multiple=abs(tp - entry) / risk)
            return out
    # Tamat masa
    last = bars[end - 1]["close"]
    out.update(result="EXPIRED", exit=last, bars_held=end - 1 - entry_idx,
               r_multiple=(last - entry) / risk if side == "BUY" else (entry - last) / risk)
    return out


def net_r(tr, symbol, entry, sl, entry_cost, exit_cost):
    """R bersih selepas kos dagangan."""
    risk = abs(entry - sl)
    if risk <= 0:
        return tr["r_multiple"]
    total_cost = entry_cost + exit_cost
    return tr["r_multiple"] - (total_cost / risk)


# ---------- metrik ----------
def wilson_ci(wins, n, z=1.96):
    """Selang keyakinan Wilson untuk win rate (spec §4.3 — jangan lapor WR sahaja)."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h) * 100, 2), round(min(1, c + h) * 100, 2))


def metrics(rows):
    """Kira metrik penuh dari senarai trade."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    rs = [r["net_r"] for r in rows]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gp = sum(r for r in rs if r > 0)
    gl = abs(sum(r for r in rs if r < 0))
    # Drawdown pada kurva ekuiti R
    peak = cum = 0.0
    dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    ci = wilson_ci(len(wins), n)
    return {
        "n": n,
        "win_rate": round(len(wins) / n * 100, 2),
        "win_rate_ci95": ci,
        "expectancy_r": round(sum(rs) / n, 4),
        "profit_factor": round(gp / gl, 3) if gl > 0 else float("inf"),
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else 0.0,
        "total_r": round(sum(rs), 2),
        "max_dd_r": round(dd, 3),
        "avg_mae_r": round(sum(r.get("mae_R", 0) for r in rows) / n, 3),
        "avg_mfe_r": round(sum(r.get("mfe_R", 0) for r in rows) / n, 3),
        "avg_bars": round(sum(r.get("bars_held", 0) for r in rows) / n, 1),
    }


def split_chrono(rows, is_frac=0.7):
    """Split kronologi (spec §4.2 — JANGAN shuffle)."""
    cut = int(len(rows) * is_frac)
    return rows[:cut], rows[cut:]


def breakdown(rows, key):
    """Pecahan metrik ikut field (regime/session/direction/symbol)."""
    buckets = {}
    for r in rows:
        buckets.setdefault(r.get(key, "?"), []).append(r)
    return {k: metrics(v) for k, v in sorted(buckets.items())}


def walk_forward(rows, folds=4):
    """Walk-forward: potong jadi folds, uji setiap segmen selepas yang pertama."""
    if len(rows) < folds * 10:
        return []
    size = len(rows) // folds
    out = []
    for f in range(1, folds):
        train = rows[:f * size]
        test = rows[f * size:(f + 1) * size]
        if not test:
            continue
        out.append({"fold": f, "train_n": len(train), "test_n": len(test),
                    "train": metrics(train), "test": metrics(test)})
    return out
