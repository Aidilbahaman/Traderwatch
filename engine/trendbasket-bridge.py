#!/usr/bin/env python3
"""TrendBasket Bridge (Python port of TrendBasket_EA_v3.mq5).

Ciri:
  1. XAUUSD M1 / timeframe pilihan.
  2. Signal: EMA8 vs EMA21 + ADX > 20 + bar dah tutup (tak repaint).
  3. Batch: 4 posisi setiap signal dengan risiko 5% equity (dibahagi rata).
  4. TP & SL sama jarak (150 points / 15 pips).
  5. Pengurusan posisi aktif: Break-Even (80pts), Trailing (100pts start, 50pts dist),
     Basket Lock (bila peak profit >= USD1 dan jatuh 40% dari peak atau basket >= USD).
  6. Had rugi harian: 5%.
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state" / "trendbasket-bridge.json"
LOCK = Path("/tmp/trendbasket-bridge.lock")
MYT = timezone(timedelta(hours=8))

SYMBOL = "XAUUSD"
INP_POSITIONS = int(os.environ.get("TB_POSITIONS", "4"))
INP_RISK_PCT = float(os.environ.get("TB_RISK_PCT", "5.0"))
INP_TP_POINTS = int(os.environ.get("TB_TP_POINTS", "150"))
INP_SL_POINTS = int(os.environ.get("TB_SL_POINTS", "150"))
INP_TP_STEP_MULT = float(os.environ.get("TB_TP_STEP_MULT", "0.5"))
INP_BE_TRIGGER = int(os.environ.get("TB_BE_TRIGGER", "80"))
INP_BE_BUFFER = int(os.environ.get("TB_BE_BUFFER", "10"))
INP_TRAIL_START = int(os.environ.get("TB_TRAIL_START", "100"))
INP_TRAIL_DIST = int(os.environ.get("TB_TRAIL_DIST", "50"))
INP_TRAIL_STEP = int(os.environ.get("TB_TRAIL_STEP", "5"))
INP_BASKET_START = float(os.environ.get("TB_BASKET_START", "1.0"))
INP_BASKET_GIVEBACK = float(os.environ.get("TB_BASKET_GIVEBACK", "40.0"))
INP_BASKET_PROFIT = float(os.environ.get("TB_BASKET_PROFIT", "0.0"))
INP_MAX_SPREAD = int(os.environ.get("TB_MAX_SPREAD", "25"))
INP_MIN_TP_RATIO = float(os.environ.get("TB_MIN_TP_RATIO", "3.0"))
INP_ADX_MIN = int(os.environ.get("TB_ADX_MIN", "20"))
INP_COOLDOWN_SEC = int(os.environ.get("TB_COOLDOWN", "60"))
INP_START_HOUR = int(os.environ.get("TB_START_HOUR", "8"))
INP_END_HOUR = int(os.environ.get("TB_END_HOUR", "20"))
INP_DAILY_LOSS = float(os.environ.get("TB_DAILY_LOSS", "5.0"))
MAGIC = int(os.environ.get("TB_MAGIC", "20261111"))
SLEEP_SEC = 2


def log(m):
    print(f"{datetime.now(MYT).strftime('%Y-%m-%dT%H:%M:%S')} [TrendBasket] {m}", flush=True)


def mt5(payload, timeout=120):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pending", HERE / "mt5-pending.py")
    pend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pend)
    return pend.mt5(payload, timeout=timeout)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"day": "", "start_balance": 0.0, "basket_peak": 0.0, "last_close": 0}


def save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    t = STATE.with_suffix(".tmp")
    t.write_text(json.dumps(d))
    t.replace(STATE)


def get_risk_lot(equity, sl_points, pt, tick_size, tick_val):
    risk_money_total = equity * (INP_RISK_PCT / 100.0)
    risk_money_each = risk_money_total / max(1, INP_POSITIONS)
    loss_per_lot = (sl_points * pt / tick_size) * tick_val
    if loss_per_lot <= 0:
        return 0.01
    lot = risk_money_each / loss_per_lot
    # Normalize lot step (0.01)
    step = 0.01
    lot = max(0.01, round(round(lot / step) * step, 2))
    return lot


def ema(closes, n):
    if len(closes) < n:
        return closes
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    out = [e] * n
    for x in closes[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    # Pad awal supaya sama panjang
    while len(out) < len(closes):
        out.insert(0, out[0])
    return out


def calc_adx(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return 25.0, 0, 0
    # Anggaran ADX ringkas dari siri harga
    import math
    tr, pdm, mdm = [], [], []
    for i in range(1, len(closes)):
        h, l, c_prev = highs[i], lows[i], closes[i-1]
        tr.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0)
        mdm.append(dn if (dn > up and dn > 0) else 0)
    
    # Smooth sederhana
    atrv = sum(tr[-period:]) / period
    if atrv <= 0:
        return 20.0, 0, 0
    pdi = 100.0 * (sum(pdm[-period:]) / period) / (atrv / period + 1e-9)
    mdi = 100.0 * (sum(mdm[-period:]) / period) / (atrv / period + 1e-9)
    dx = 100.0 * abs(pdi - mdi) / max(1.0, (pdi + mdi))
    return dx, pdi, mdi


def get_signal(bars):
    if len(bars) < 30:
        return 0
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    
    f = ema(closes, 8)
    s = ema(closes, 21)
    adx, pdi, mdi = calc_adx(highs, lows, closes, 14)
    
    if adx < INP_ADX_MIN:
        return 0
    
    c1 = closes[-2] # bar tertutup
    if f[-2] > s[-2] and f[-2] > f[-3] and c1 > f[-2] and pdi > mdi:
        return 1
    if f[-2] < s[-2] and f[-2] < f[-3] and c1 < f[-2] and mdi > pdi:
        return -1
    return 0


def manage_positions(positions, info, pt, bid, ask):
    spr = float(info.get("spread_price", 0)) / pt
    for p in positions:
        if int(p.get("magic", 0)) != MAGIC:
            continue
        t = int(p["ticket"])
        ptype = p.get("type")
        open_px = float(p.get("price_open", 0))
        sl = float(p.get("sl", 0))
        tp = float(p.get("tp", 0))
        
        if ptype == "BUY":
            prof = (bid - open_px) / pt
            new_sl = sl
            if INP_BE_TRIGGER > 0 and prof >= INP_BE_TRIGGER:
                be = open_px + (spr + INP_BE_BUFFER) * pt
                if new_sl == 0 or be > new_sl:
                    new_sl = be
            if INP_TRAIL_START > 0 and INP_TRAIL_DIST > 0 and prof >= INP_TRAIL_START:
                tr = bid - INP_TRAIL_DIST * pt
                if new_sl == 0 or tr > new_sl:
                    new_sl = tr
            if new_sl > 0 and new_sl != sl and (sl == 0 or new_sl - sl >= INP_TRAIL_STEP * pt):
                mt5({"action": "modify_position", "ticket": t, "sl": round(new_sl, 2), "tp": tp})
        elif ptype == "SELL":
            prof = (open_px - ask) / pt
            new_sl = sl
            if INP_BE_TRIGGER > 0 and prof >= INP_BE_TRIGGER:
                be = open_px - (spr + INP_BE_BUFFER) * pt
                if new_sl == 0 or be < new_sl:
                    new_sl = be
            if INP_TRAIL_START > 0 and INP_TRAIL_DIST > 0 and prof >= INP_TRAIL_START:
                tr = ask + INP_TRAIL_DIST * pt
                if new_sl == 0 or tr < new_sl:
                    new_sl = tr
            if new_sl > 0 and new_sl != sl and (sl == 0 or sl - new_sl >= INP_TRAIL_STEP * pt):
                mt5({"action": "modify_position", "ticket": t, "sl": round(new_sl, 2), "tp": tp})


def main():
    st = load_state()
    day = datetime.now(MYT).strftime("%Y-%m-%d")
    
    live = mt5({"action": "state"})
    if not live.get("ok"):
        log(f"MT5-ERR {live.get('error')}")
        time.sleep(5)
        return
    
    bal = float(live.get("balance", 0))
    eq = float(live.get("equity", bal))
    if st.get("day") != day:
        st["day"] = day
        st["start_balance"] = bal
        st["basket_peak"] = 0.0
        save_state(st)
        log(f"DAY-RESET {day} start_balance={bal:.2f}")

    start_bal = float(st.get("start_balance", bal))
    if INP_DAILY_LOSS > 0 and start_bal > 0 and (start_bal - eq) / start_bal * 100.0 >= INP_DAILY_LOSS:
        log(f"DAILY-LOSS-HIT eq={eq:.2f} start={start_bal:.2f}")
        return

    positions = [p for p in live.get("positions", []) if int(p.get("magic", 0)) == MAGIC]
    
    info_res = mt5({"action": "symbol", "symbol": SYMBOL})
    if not info_res.get("ok"):
        return
    pt = float(info_res.get("point", 0.01))
    tick_size = float(info_res.get("tick_size", pt))
    tick_val = float(info_res.get("tick_value", 1.0))
    bid = float(info_res.get("bid", 0))
    ask = float(info_res.get("ask", 0))
    if bid <= 0 or ask <= 0:
        # fallback ambil dari tick jika belum dipulangkan
        tick_res = mt5({"action": "tick", "symbol": SYMBOL})
        bid = float(tick_res.get("bid", bid))
        ask = float(tick_res.get("ask", ask))
    spread = float(info_res.get("spread_price", 0)) / pt

    if positions:
        manage_positions(positions, info_res, pt, bid, ask)
        bp = sum(float(p.get("profit", 0)) + float(p.get("swap", 0)) for p in positions)
        peak = max(float(st.get("basket_peak", 0)), bp)
        st["basket_peak"] = peak
        save_state(st)
        
        close_now = False
        if INP_BASKET_PROFIT > 0 and bp >= INP_BASKET_PROFIT:
            close_now = True
        if INP_BASKET_START > 0 and peak >= INP_BASKET_START and bp <= peak * (1.0 - INP_BASKET_GIVEBACK / 100.0):
            close_now = True
            
        if close_now:
            log(f"BASKET-CLOSE profit={bp:.2f} peak={peak:.2f}")
            for p in positions:
                mt5({"action": "close_position", "ticket": int(p["ticket"])})
            st["basket_peak"] = 0.0
            save_state(st)
        return

    # Cooldown & jam
    if time.time() - st.get("last_close", 0) < INP_COOLDOWN_SEC:
        return
    hh = datetime.now(MYT).hour
    if not (INP_START_HOUR <= hh < INP_END_HOUR):
        return
    if spread > INP_MAX_SPREAD:
        return

    # Ambil candles M1
    candles_res = mt5({"action": "candles", "symbol": SYMBOL, "count": 100})
    if not candles_res.get("ok"):
        return
    bars = candles_res.get("bars", [])
    
    sig = get_signal(bars)
    if sig == 0:
        return

    # Kira lot risiko 5%
    lot = get_risk_lot(eq, INP_SL_POINTS, pt, tick_size, tick_val)
    
    log(f"SIGNAL {('BUY' if sig > 0 else 'SELL')} lot={lot} equity={eq:.2f}")
    for i in range(INP_POSITIONS):
        tp_pts = INP_TP_POINTS * (1.0 + i * INP_TP_STEP_MULT)
        side = "BUY" if sig > 0 else "SELL"
        p_entry = ask if side == "BUY" else bid
        # XAUUSD point vs digit scaling: 1 point = pt (biasanya 0.01 untuk 2-digit XAUUSD)
        sl_dist = INP_SL_POINTS * pt
        tp_dist = tp_pts * pt
        if side == "BUY":
            sl_px = p_entry - sl_dist
            tp_px = p_entry + tp_dist
        else:
            sl_px = p_entry + sl_dist
            tp_px = p_entry - tp_dist
        
        r = mt5({
            "action": "market",
            "symbol": SYMBOL,
            "side": side,
            "lot": lot,
            "sl": round(sl_px, 2),
            "tp": round(tp_px, 2),
            "magic": MAGIC,
            "deviation": 20,
            "comment": f"TB_v3_{i+1}"
        })
        if r.get("ok"):
            log(f"OPEN {side} ticket={r.get('ticket')} lot={lot} sl={sl_px:.2f} tp={tp_px:.2f}")
        else:
            log(f"OPEN-FAIL {side}: {r}")
        time.sleep(0.3)
        
    st["last_close"] = time.time()
    st["basket_peak"] = 0.0
    save_state(st)


if __name__ == "__main__":
    import fcntl
    fd = open(LOCK, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("Instance lain sedang jalan")
        sys.exit(0)
    log("TrendBasket Bridge dimulakan (5% risk, TP=SL=150, BE/Trail/Basket)")
    while True:
        try:
            main()
        except Exception as ex:
            log(f"FATAL {type(ex).__name__}: {ex}")
        time.sleep(SLEEP_SEC)
