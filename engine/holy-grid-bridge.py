#!/usr/bin/env python3
"""Holy Grid Bridge (Python port of TraderWatch_Holy_Grid_EA.mq5).

M1 signal: EMA9 vs EMA21 close-of-last-closed bar.
Grid: adverse 300 points per order on existing side, lot multiplier.
Basket TP: combined P/L of side reaches $2.00.
Ability: one initial entry per closed candle, one grid add per evaluation.
"""
import json, math, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state" / "holy-grid-bridge.json"
LOCK = Path("/tmp/holy-grid-bridge.lock")
MYT = timezone(timedelta(hours=8))

SYMBOL = os.environ.get("HG_SYMBOL", "XAUUSD")
MAGIC = int(os.environ.get("HG_MAGIC", "26111001"))
START_LOT = float(os.environ.get("HG_START_LOT", "0.01"))
LOT_MULT = float(os.environ.get("HG_LOT_MULT", "1.50"))
MAX_LOT_ORDER = float(os.environ.get("HG_MAX_LOT", "0.25"))
GRID_STEP_PTS = float(os.environ.get("HG_GRID_STEP", "300"))
MAX_POS_SIDE = int(os.environ.get("HG_MAX_POS", "6"))
MAX_TOTAL_LOTS = float(os.environ.get("HG_MAX_TOTAL_LOTS", "1.20"))
HG_RISK_PCT = float(os.environ.get("HG_RISK_PCT", "7.0"))
MAX_SPREAD_PTS = float(os.environ.get("HG_MAX_SPREAD", "80"))
BASKET_TP = float(os.environ.get("HG_BASKET_TP", "2.00"))
BASKET_SL = float(os.environ.get("HG_BASKET_SL", "0.0"))
MAX_EQ_DD_PCT = float(os.environ.get("HG_EQ_DD_PCT", "20.0"))
DAILY_LOSS = float(os.environ.get("HG_DAILY_LOSS", "0.0"))
HG_REVERSE_LOSS = float(os.environ.get("HG_REVERSE_LOSS", "100.0"))
HG_HEDGE_TP = float(os.environ.get("HG_HEDGE_TP", "3.0"))
HG_HEDGE_RELEASE = float(os.environ.get("HG_HEDGE_RELEASE", "10.0"))
SLEEP_SEC = 1
# ---- Farming mode: kerap bank untung kecil, satu arah pada satu masa ----
FARM_MODE = os.environ.get("HG_FARM_MODE", "0") == "1"
FARM_TP_PCT = float(os.environ.get("HG_FARM_TP_PCT", "0.35"))   # % equity per basket
FARM_SL_PCT = float(os.environ.get("HG_FARM_SL_PCT", "0.0"))    # 0 = off (tiada had rugi)
HEDGE_ENABLED = os.environ.get("HG_HEDGE_ENABLED", "1") == "1"
GRID_COOLDOWN_SEC = float(os.environ.get("HG_GRID_COOLDOWN", "60"))


# ---------- Equity TIER auto-scale (20$ -> 1000$+) ----------
TIERS = [
    (0.0,    "T1 Saver",       dict(risk=1.0, grid=100.0, max_lot=0.01, max_total=0.03, basket_tp=1.00, hedge=8.0,   hedge_tp=2.00, hedge_release=2.0, free_min=2.0,  max_pos=3)),
    (100.0,  "T2 Growing",     dict(risk=2.0, grid=150.0, max_lot=0.10, max_total=0.40, basket_tp=2.00, hedge=40.0,  hedge_tp=2.50, hedge_release=4.0, free_min=10.0, max_pos=10)),
    (300.0,  "T3 Scaling",     dict(risk=3.0, grid=200.0, max_lot=0.25, max_total=0.40, basket_tp=3.50, hedge=70.0,  hedge_tp=3.00, hedge_release=6.0, free_min=25.0, max_pos=10)),
    (600.0,  "T4 Established", dict(risk=4.0, grid=250.0, max_lot=0.50, max_total=1.00, basket_tp=5.00, hedge=100.0, hedge_tp=4.00, hedge_release=8.0, free_min=40.0, max_pos=10)),
    (1000.0, "T5 Full",        dict(risk=4.0, grid=300.0, max_lot=2.00, max_total=2.00, basket_tp=10.00, hedge=100.0, hedge_tp=3.00, hedge_release=10.0, free_min=100.0, max_pos=10)),
]
def tier_params(bal):
    cur = TIERS[0]
    for lo, name, cfg in TIERS:
        if bal >= lo:
            cur = (lo, name, cfg)
    return cur[1], cur[2]

def log(m):
    print(f"{datetime.now(MYT).strftime('%Y-%m-%dT%H:%M:%S')} [HolyGrid] {m}", flush=True)


def mt5(payload, timeout=120):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pending", HERE / "mt5-pending.py")
    pend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pend)
    return pend.mt5(payload, timeout=timeout)


def ema(closes, n):
    if len(closes) < n:
        return closes[:]
    k = 2 / (n + 1)
    e = closes[0]
    out = [e]
    for x in closes[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    t = STATE.with_suffix(".tmp")
    t.write_text(json.dumps(d))
    t.replace(STATE)


def is_buy_type(t):
    # MT5 buy type is int 0; bridge may return "BUY" or 0
    return str(t).upper() in ("BUY", "0")


def dynamic_lot(equity, n, tick_value, vol_step, vol_min, eff_risk=None, bal=0):
    """Lot berasaskan equity & smart dynamic max lot (bal/500)."""
    risk_pct = eff_risk if eff_risk is not None else HG_RISK_PCT
    risk_money = equity * risk_pct / 100.0
    loss_per_grid = GRID_STEP_PTS * float(tick_value)
    if loss_per_grid <= 0:
        return max(vol_min, START_LOT)
    base = risk_money / loss_per_grid
    lot = base * (LOT_MULT ** n)
    # Smart dynamic max lot (balance/500)
    dynamic_max_lot = max(0.10, min(20.0, float(bal) / 500.0))
    lot = min(dynamic_max_lot, max(vol_min, lot))
    step = float(vol_step or 0.01)
    if step > 0:
        lot = math.floor(lot / step) * step
    return round(lot, 2) if step < 1 else int(lot)


def main():
    st = load_state()
    day = datetime.now(MYT).strftime("%Y-%m-%d")

    live = mt5({"action": "state"}, timeout=120)
    if not live.get("ok"):
        log(f"MT5-ERR {live.get('error')}")
        return

    bal = float(live.get("balance", 0))
    eq = float(live.get("equity", bal))
    snapshot = int(time.time())

    tier_name, T = tier_params(bal)
    env_tp = float(os.environ.get("HG_BASKET_TP", "0"))
    if st.get("tier") != tier_name:
        effective_tp = env_tp if env_tp > 0 else float(T["basket_tp"])
        log(f"TIER-SHIFT -> {tier_name} bal=${bal:.2f} | risk={T['risk']}% grid={T['grid']}pt basketTP=${effective_tp:.2f} (env_override={env_tp>0}) maxTotal={T['max_total']}")
        st["tier"] = tier_name
        save_state(st)

    # Kemas kini globals supaya dynamic_lot()/basket logic ikut TIER (bukan nilai lama)
    globals()["HG_RISK_PCT"] = T["risk"]
    globals()["GRID_STEP_PTS"] = T["grid"]
    globals()["MAX_LOT_ORDER"] = T["max_lot"]
    globals()["MAX_TOTAL_LOTS"] = T["max_total"]
    globals()["BASKET_TP"] = T["basket_tp"]
    # Hedge trigger: tier value, tetapi tidak boleh lebih dari 50% balance semasa (min $1)
    env_hedge = float(os.environ.get("HG_HEDGE_USD", "0") or 0)
    tier_hedge = env_hedge if env_hedge > 0 else T["hedge"]
    hedge_trigger = min(tier_hedge, max(1.0, float(bal) * 0.5))
    T["hedge"] = hedge_trigger
    globals()["HG_REVERSE_LOSS"] = hedge_trigger
    globals()["HG_HEDGE_TP"] = T["hedge_tp"]
    globals()["HG_HEDGE_RELEASE"] = T["hedge_release"]
    globals()["FREE_MARGIN_MIN"] = T["free_min"]
    globals()["MAX_POS_SIDE"] = T["max_pos"]
    HG_RISK_PCT = T["risk"]; GRID_STEP_PTS = T["grid"]; MAX_LOT_ORDER = T["max_lot"]
    MAX_TOTAL_LOTS = T["max_total"]; BASKET_TP = T["basket_tp"]; HG_REVERSE_LOSS = T["hedge"]
    HG_HEDGE_TP = T["hedge_tp"]; HG_HEDGE_RELEASE = T["hedge_release"]
    # Override Basket TP jika diset melalui env (cth: HG_BASKET_TP=5.00)
    if env_tp > 0:
        globals()["BASKET_TP"] = env_tp
        BASKET_TP = env_tp
    elif FARM_MODE:
        farm_tp = max(0.10, min(float(T["basket_tp"]), eq * FARM_TP_PCT / 100.0))
        globals()["BASKET_TP"] = farm_tp
        BASKET_TP = farm_tp
    FREE_MARGIN_MIN = T["free_min"]; MAX_POS_SIDE = T["max_pos"]
    eff_risk = T["risk"]  # fallback — risk adaptif (drawdown tiers) ditambah kemudian jika perlu

    if st.get("day") != day:
        st = {"day": day, "day_start_balance": bal, "start_equity": eq, "last_bar": 0, "tier": tier_name}
        save_state(st)
        log(f"DAY-RESET {day} bal={bal:.2f} eq={eq:.2f} tier={tier_name}")

    # ---------- Symbol ----------
    info = mt5({"action": "symbol", "symbol": SYMBOL}, timeout=120)
    if not info.get("ok"):
        log(f"SYM-ERR {info}")
        return
    pt = float(info.get("point", 0.01))
    bid = float(info.get("bid", 0))
    ask = float(info.get("ask", 0))
    # Wine/MT5 boleh pulangkan bid/ask=0 atau nilai stale. Jangan benarkan
    # bacaan invalid mengaktifkan grid/entry atau mengira spread secara palsu.
    if bid <= 0 or ask <= 0 or ask < bid:
        log(f"PRICE-SKIP invalid quote bid={bid} ask={ask}")
        return
    tick_size = float(info.get("tick_size", pt) or pt)
    tick_value = float(info.get("tick_value", 1.0))
    if tick_value <= 0 or pt <= 0:
        log(f"PRICE-SKIP invalid metadata point={pt} tick_value={tick_value}")
        return
    vol_min = float(info.get("vol_min", 0.01))
    vol_step = float(info.get("vol_step", 0.01) or 0.01)
    spread_pts = float(info.get("spread_price", 1e9)) / pt if pt else 1e9
    if MAX_SPREAD_PTS > 0 and spread_pts > MAX_SPREAD_PTS:
        return

    # ---------- Positions ----------
    positions = [p for p in live.get("positions", []) if int(p.get("magic", 0) or 0) == MAGIC]
    # Grid cap hanya dikira untuk posisi ARAH (bukan hedge) supaya hedge sentiasa ada ruang
    base_positions = [p for p in positions if not str(p.get("comment") or "").startswith("HG_HEDGE")]
    # FIX: hedge TIDAK boleh masuk buys/sells — jika tidak BASKET-TP akan tutup hedge
    # dan net_lots jadi salah (hedge trigger berulang / HEDGE-RESET pramatang)
    buys = [p for p in base_positions if is_buy_type(p.get("type"))]
    sells = [p for p in base_positions if not is_buy_type(p.get("type"))]
    total_lots = sum(float(p.get("volume", 0)) for p in base_positions)
    buy_lots = sum(float(p.get("volume", 0)) for p in buys)
    sell_lots = sum(float(p.get("volume", 0)) for p in sells)
    net_lots = buy_lots - sell_lots

    # ---------- Basket management ----------
    buy_profit = sum(float(p.get("profit", 0)) + float(p.get("swap", 0)) for p in buys)
    sell_profit = sum(float(p.get("profit", 0)) + float(p.get("swap", 0)) for p in sells)
    if buys:
        if BASKET_TP > 0 and buy_profit >= BASKET_TP:
            log(f"BASKET-TP BUY profit=${buy_profit:.2f} closing {len(buys)} positions")
            for p in buys:
                mt5({"action": "close_position", "ticket": int(p["ticket"])})
            return
        if BASKET_SL > 0 and buy_profit <= -BASKET_SL:
            log(f"BASKET-SL BUY profit=${buy_profit:.2f} closing {len(buys)} positions")
            for p in buys:
                mt5({"action": "close_position", "ticket": int(p["ticket"])})
            return
    if sells:
        if BASKET_TP > 0 and sell_profit >= BASKET_TP:
            log(f"BASKET-TP SELL profit=${sell_profit:.2f} closing {len(sells)} positions")
            for p in sells:
                mt5({"action": "close_position", "ticket": int(p["ticket"])})
            return
        if BASKET_SL > 0 and sell_profit <= -BASKET_SL:
            log(f"BASKET-SL SELL profit=${sell_profit:.2f} closing {len(sells)} positions")
            for p in sells:
                mt5({"action": "close_position", "ticket": int(p["ticket"])})
            return

    # ---------- Hedge management (auto-TP / auto-release) ----------
    hedges = [q for q in positions if str(q.get("comment") or "").startswith("HG_HEDGE")]
    if HEDGE_ENABLED and hedges:
        hedge_profit = sum(float(q.get("profit", 0)) + float(q.get("swap", 0)) for q in hedges)
        total_float = sum(float(q.get("profit", 0)) + float(q.get("swap", 0)) for q in positions)
        if HG_HEDGE_TP > 0 and hedge_profit >= HG_HEDGE_TP:
            log(f"HEDGE-TP profit=${hedge_profit:.2f} closing hedges (lock hedge profit)")
            for q in hedges:
                mt5({"action": "close_position", "ticket": int(q["ticket"])})
            st["hedge_trigger"] = False  # reset supaya boleh hedge semula bila perlu
            save_state(st)
            return
        if HG_HEDGE_RELEASE > 0 and total_float >= -HG_HEDGE_RELEASE:
            log(f"HEDGE-RELEASE float={total_float:.2f} recovered to <$10 loss, closing hedges")
            for q in hedges:
                mt5({"action": "close_position", "ticket": int(q["ticket"])})
            st["hedge_trigger"] = False
            save_state(st)
            return

    # ---------- Counter-hedge (HG_REVERSE_LOSS) ----------
    if HEDGE_ENABLED and positions and HG_REVERSE_LOSS > 0:
        float_pnl = sum(float(p.get("profit", 0)) + float(p.get("swap", 0)) for p in positions)
        base_float = sum(float(p.get("profit", 0)) + float(p.get("swap", 0)) for p in base_positions)
        # Release mesti lebih ketat daripada trigger, jika tidak hedge reset serta-merta
        # pada titik trigger dan berulang setiap tick.
        release_level = max(0.50, HG_REVERSE_LOSS * 0.40)
        if float_pnl <= -HG_REVERSE_LOSS and abs(net_lots) > 1e-8:
            side = "SELL" if net_lots > 0 else "BUY"  # counter opposite net exposure
            net_abs = abs(net_lots)
            step = float(vol_step or 0.01)
            hedge_max = max(0.10, min(20.0, float(bal) / 500.0))
            hedge_lot = min(net_abs, hedge_max)
            if step > 0:
                hedge_lot = math.floor(hedge_lot / step) * step
            hedge_lot = round(hedge_lot, 2)
            if hedge_lot >= vol_min and not st.get("hedge_trigger"):
                log(f"HEDGE-{side} lot={hedge_lot} float={float_pnl:.2f} (counter net {net_lots:+.2f})")
                r = mt5({"action": "market", "symbol": SYMBOL, "side": side,
                         "lot": hedge_lot, "magic": MAGIC, "comment": "HG_HEDGE"})
                log(f"HEDGE-{side} res: {r}")
                st["hedge_trigger"] = True
                save_state(st)
            elif hedge_lot < vol_min:
                log(f"HEDGE-SKIP side={side} float={float_pnl:.2f} insufficient room (total {total_lots:.2f}/{MAX_TOTAL_LOTS})")
        elif st.get("hedge_trigger") and base_float >= -release_level:
            log(f"HEDGE-RESET base_float={base_float:.2f} recovered above -{release_level:.2f}; ready to hedge again")
            st["hedge_trigger"] = False
            save_state(st)

    # ---------- Grid adds (FIXED: rujukan harga betul + cooldown) ----------
    step = GRID_STEP_PTS * pt
    now_ts = time.time()
    last_grid_ts = float(st.get("last_grid_ts", 0) or 0)
    cooldown_ok = (now_ts - last_grid_ts) >= GRID_COOLDOWN_SEC
    if positions and total_lots < MAX_TOTAL_LOTS - 1e-8 and cooldown_ok and not hedges:
        # Quote sudah divalidasi di atas; grid dibekukan jika hedge wujud.
        # BUY: Tambah layer HANYA bila harga semasa jatuh melepasi harga BUY TERENDAH - step
        if 0 < len(buys) < MAX_POS_SIDE:
            lowest_buy = min(float(p["price_open"]) for p in buys)
            if bid <= lowest_buy - step:
                n = len(buys)
                next_lot = dynamic_lot(eq, n, tick_value, vol_step, vol_min, eff_risk, bal)
                if total_lots + next_lot <= MAX_TOTAL_LOTS:
                    log(f"GRID-BUY add #{n+1} lot={next_lot} (bid {bid} <= lowest {lowest_buy} - {step})")
                    r = mt5({"action": "market", "symbol": SYMBOL, "side": "BUY",
                             "lot": round(next_lot, 2), "magic": MAGIC, "comment": "HG_G_BUY"})
                    log(f"GRID-BUY res: {r}")
                    st["last_grid_ts"] = time.time()
                    save_state(st)
                    time.sleep(1.0)
        # SELL: Tambah layer HANYA bila harga semasa naik melepasi harga SELL TERTINGGI + step
        if 0 < len(sells) < MAX_POS_SIDE:
            highest_sell = max(float(p["price_open"]) for p in sells)
            if ask >= highest_sell + step:
                n = len(sells)
                next_lot = dynamic_lot(eq, n, tick_value, vol_step, vol_min, eff_risk, bal)
                if total_lots + next_lot <= MAX_TOTAL_LOTS:
                    log(f"GRID-SELL add #{n+1} lot={next_lot} (ask {ask} >= highest {highest_sell} + {step})")
                    r = mt5({"action": "market", "symbol": SYMBOL, "side": "SELL",
                             "lot": round(next_lot, 2), "magic": MAGIC, "comment": "HG_G_SELL"})
                    log(f"GRID-SELL res: {r}")
                    st["last_grid_ts"] = time.time()
                    save_state(st)
                    time.sleep(1.0)

    # ---------- Initial entry once per closed bar ----------
    candles = mt5({"action": "candles", "symbol": SYMBOL, "count": 100}, timeout=120)
    bars = (candles or {}).get("bars", [])
    if not bars or len(bars) < 30:
        return
    last_bar_t = int(bars[-2]["t"])  # last closed candle
    if st.get("last_bar") == last_bar_t:
        return
    closes = [float(b["c"]) for b in bars]
    f9 = ema(closes, 9)
    s21 = ema(closes, 21)
    signal = 0
    if f9[-1] > s21[-1]:
        signal = 1
    elif f9[-1] < s21[-1]:
        signal = -1
    limit = dynamic_lot(eq, 0, tick_value, vol_step, vol_min, eff_risk, bal) + 1e-8
    if signal > 0 and (not FARM_MODE or not base_positions) and not buys and total_lots + limit <= MAX_TOTAL_LOTS:
        log(f"INITIAL-BUY entry lot={limit:.2f} (risk {HG_RISK_PCT}% equity) bar={last_bar_t}")
        r = mt5({"action": "market", "symbol": SYMBOL, "side": "BUY",
                 "lot": limit, "magic": MAGIC, "comment": "HG_INIT_BUY"})
        log(f"INITIAL-BUY res: {r}")
    elif signal < 0 and (not FARM_MODE or not base_positions) and not sells and total_lots + limit <= MAX_TOTAL_LOTS:
        log(f"INITIAL-SELL entry lot={limit:.2f} (risk {HG_RISK_PCT}% equity) bar={last_bar_t}")
        r = mt5({"action": "market", "symbol": SYMBOL, "side": "SELL",
                 "lot": limit, "magic": MAGIC, "comment": "HG_INIT_SELL"})
        log(f"INITIAL-SELL res: {r}")
    st["last_bar"] = last_bar_t
    save_state(st)


if __name__ == "__main__":
    import fcntl
    fd = open(LOCK, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Holy Grid already running")
        sys.exit(0)
    log("Smart Money Management aktif: adaptive tier risk, free-margin guard, anti-martingale")
    log("Holy Grid Bridge v2 dimulakan (M1 EMA9/21, 1 init/bar, grid 300pts, basket TP $2)")
    while True:
        try:
            main()
        except Exception as ex:
            log(f"FATAL {type(ex).__name__}: {ex}")
        time.sleep(SLEEP_SEC)
