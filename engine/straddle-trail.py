#!/usr/bin/env python3
"""XAUUSD StraddleTrail OCO bridge, 24/7.

Two pending stops are placed together. Once one fills, the other is cancelled.
Filled positions trail their SL. Lot sizing risks STRADDLE_RISK_PCT of live
balance per side, using broker tick value/size. No MT5 EA attach required.
"""
import importlib.util
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STATE = REPO / "state" / "straddle-trail.json"
LOCK = Path("/tmp/straddle-trail.lock")
SYMBOL = "XAUUSD"
MAGIC = int(os.environ.get("STRADDLE_MAGIC", "26111001"))
RISK_PCT = float(os.environ.get("STRADDLE_RISK_PCT", "7.0"))
ENTRY_POINTS = int(os.environ.get("STRADDLE_ENTRY_POINTS", "150"))
SL_POINTS = int(os.environ.get("STRADDLE_SL_POINTS", "200"))
TP_POINTS = int(os.environ.get("STRADDLE_TP_POINTS", "0"))
PENDING_EXPIRY_MIN = int(os.environ.get("STRADDLE_EXPIRY_MIN", "15"))
TRAIL_START = int(os.environ.get("STRADDLE_TRAIL_START", "150"))
TRAIL_DISTANCE = int(os.environ.get("STRADDLE_TRAIL_DISTANCE", "100"))
TRAIL_STEP = int(os.environ.get("STRADDLE_TRAIL_STEP", "10"))
MAX_SPREAD = int(os.environ.get("STRADDLE_MAX_SPREAD", "0"))
COOLDOWN_MIN = int(os.environ.get("STRADDLE_COOLDOWN_MIN", "0"))
SLEEP = 2
MYT = timezone(timedelta(hours=8))


def log(s):
    print(datetime.now(MYT).strftime("%Y-%m-%dT%H:%M:%S"), s, flush=True)


def bridge():
    spec = importlib.util.spec_from_file_location("pending", HERE / "mt5-pending.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.mt5

MT5 = bridge()


def load():
    try: return json.loads(STATE.read_text())
    except Exception: return {"day": "", "start_balance": 0.0, "last_close": 0}


def save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    t = STATE.with_suffix(".tmp")
    t.write_text(json.dumps(d))
    t.replace(STATE)


def mine(data, key):
    return [x for x in data.get(key, []) if str(x.get("symbol", "")).upper() == SYMBOL and int(x.get("magic", 0) or 0) == MAGIC]


def lot_for(price, sl, balance, spec):
    tick_size = float(spec.get("tick_size") or spec.get("point") or .01)
    tick_value = float(spec.get("tick_value") or 0)
    step = float(spec.get("vol_step") or .01)
    vmin = float(spec.get("vol_min") or step)
    vmax = float(spec.get("vol_max") or 100)
    loss = abs(price - sl) / tick_size * tick_value
    if loss <= 0 or tick_value <= 0: return 0.0
    raw = balance * RISK_PCT / 100.0 / loss
    return round(max(vmin, min(vmax, int(raw / step) * step)), 2)


def cancel_orders(orders):
    for o in orders:
        r = MT5({"action": "cancel", "ticket": int(o["ticket"])})
        log(f"OCO-CANCEL ticket={o['ticket']} ok={r.get('ok')} retcode={r.get('retcode')}")


def trail(positions, spec):
    tick = MT5({"action": "tick", "symbol": SYMBOL})
    bid, ask = float(tick.get("bid", 0)), float(tick.get("ask", 0))
    point = float(spec.get("point") or .01)
    min_dist = max(float(spec.get("stops_level") or 0), float(spec.get("freeze_level") or 0)) * point
    for p in positions:
        typ, openp = int(p["type"]), float(p["price_open"])
        old = float(p.get("sl") or 0)
        if typ == 0:  # BUY
            if (bid - openp) / point < TRAIL_START: continue
            new = round(bid - max(TRAIL_DISTANCE * point, min_dist), 2)
            if old == 0 or new >= old + TRAIL_STEP * point:
                r = MT5({"action": "modify_position", "ticket": int(p["ticket"]), "sl": new, "tp": float(p.get("tp") or 0)})
                log(f"TRAIL BUY ticket={p['ticket']} sl={new} ok={r.get('ok')}")
        else:  # SELL
            if (openp - ask) / point < TRAIL_START: continue
            new = round(ask + max(TRAIL_DISTANCE * point, min_dist), 2)
            if old == 0 or new <= old - TRAIL_STEP * point:
                r = MT5({"action": "modify_position", "ticket": int(p["ticket"]), "sl": new, "tp": float(p.get("tp") or 0)})
                log(f"TRAIL SELL ticket={p['ticket']} sl={new} ok={r.get('ok')}")


def cycle():
    st = load()
    state = MT5({"action": "state"})
    if not state.get("ok"):
        log(f"MT5-ERR {state.get('error')}"); return
    balance = float(state.get("balance") or 0)
    day = datetime.now(MYT).strftime("%Y-%m-%d")
    if st.get("day") != day:
        st.update({"day": day, "start_balance": balance, "last_close": 0}); save(st)
        log(f"DAY-RESET balance={balance:.2f}")
    spec = MT5({"action": "symbol", "symbol": SYMBOL})
    tick = MT5({"action": "tick", "symbol": SYMBOL})
    if not spec.get("ok") or not tick.get("ok"): return
    bid, ask = float(tick["bid"]), float(tick["ask"])
    point = float(spec.get("point") or .01)
    spread_pt = (ask - bid) / point
    if MAX_SPREAD and spread_pt > MAX_SPREAD:
        log(f"SPREAD-SKIP {spread_pt:.1f}>{MAX_SPREAD}"); return
    positions, orders = mine(state, "positions"), mine(state, "orders")
    if positions:
        if orders: cancel_orders(orders)
        trail(positions, spec); return
    if len(orders) == 1:
        cancel_orders(orders); return
    if len(orders) >= 2:
        if PENDING_EXPIRY_MIN:
            # Bridge state does not expose setup time reliably; replace stale
            # straddles using local placement timestamp.
            if time.time() - float(st.get("pending_at", time.time())) >= PENDING_EXPIRY_MIN * 60:
                cancel_orders(orders); st["pending_at"] = 0; save(st)
        return
    if time.time() - float(st.get("last_close", 0)) < COOLDOWN_MIN * 60: return
    entry_dist = max(ENTRY_POINTS * point, float(spec.get("stops_level") or 0) * point + (ask - bid))
    sl_dist = max(SL_POINTS * point, float(spec.get("stops_level") or 0) * point)
    tp_dist = TP_POINTS * point if TP_POINTS > 0 else 0
    buy_entry, sell_entry = round(ask + entry_dist, 2), round(bid - entry_dist, 2)
    buy_sl, sell_sl = round(buy_entry - sl_dist, 2), round(sell_entry + sl_dist, 2)
    buy_tp = round(buy_entry + tp_dist, 2) if tp_dist else 0
    sell_tp = round(sell_entry - tp_dist, 2) if tp_dist else 0
    buy_lot = lot_for(buy_entry, buy_sl, balance, spec)
    sell_lot = lot_for(sell_entry, sell_sl, balance, spec)
    if not buy_lot or not sell_lot:
        log("LOT-SKIP risk calculation failed"); return
    common = {"symbol": SYMBOL, "magic": MAGIC, "deviation": 20, "comment": "STRADDLE"}
    rb = MT5({"action": "place_limit", **common, "side": "BUY", "entry": buy_entry, "sl": buy_sl, "tp": buy_tp, "lot": buy_lot})
    log(f"PLACE BUY_STOP entry={buy_entry} lot={buy_lot} risk={RISK_PCT}% ok={rb.get('ok')} retcode={rb.get('retcode')}")
    if not rb.get("ok"):
        return
    rs = MT5({"action": "place_limit", **common, "side": "SELL", "entry": sell_entry, "sl": sell_sl, "tp": sell_tp, "lot": sell_lot})
    log(f"PLACE SELL_STOP entry={sell_entry} lot={sell_lot} risk={RISK_PCT}% ok={rs.get('ok')} retcode={rs.get('retcode')}")
    if not rs.get("ok"):
        if rb.get("ticket"): MT5({"action": "cancel", "ticket": int(rb["ticket"])})
        return
    st["pending_at"] = time.time(); save(st)


if __name__ == "__main__":
    import fcntl, sys
    fd = open(LOCK, "w")
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: sys.exit(0)
    while True:
        try: cycle()
        except Exception as e: log(f"FATAL {type(e).__name__}: {e}")
        time.sleep(2)
