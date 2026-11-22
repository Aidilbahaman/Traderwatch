#!/usr/bin/env python3
"""TraderWatch MT5 Super Scalper — Python bridge (EA port, XAUUSD only).

Terjemahan logik SuperScalper.mq5 ke Python yang memandu MT5 terus via Wine
bridge, tanpa EA/attach GUI. Cycle:
  1. Baca tick + 200 bar M1 XAUUSD.
  2. Kira EMA8 vs EMA21 -> isyarat BUY/SELL.
  3. Jika tiada posisi/order (magic sendiri) -> buka InpPositions lot
     dengan SL/TP broker (pointize betul) + comment.
  4. Jika basket profit >= InpBasketProfit -> tutup SEMUA posisi magic.
  5. Jika rugi harian >= InpDailyLossPct -> berhenti buka order baharu.

Hanya XAUUSD (XAUUSD). Satu proses (flock). Log ke stdout (systemd journal).
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state" / "mt5-super-scalper.json"
LOCK = Path("/tmp/mt5-super-scalper.lock")

PREFIX = "/home/mt5/.mt5"
PY = r"C:\Python311\python.exe"
WIN_SCRIPT_HOST = "/home/mt5/.mt5/drive_c/mt5work/mt5_pending.py"  # bridge sedia ada
MYT = timezone(timedelta(hours=8))

SYMBOL = "XAUUSD"
ERROR_FLOOR_STD = 9.0  # SL minimum dalam mata (point) XAUUSD ~ 9-10 pips harga
INP_POSITIONS = int(os.environ.get("SCALP_POSITIONS", "4"))
INP_TP_POINTS = int(os.environ.get("SCALP_TP_POINTS", "150"))
INP_SL_POINTS = int(os.environ.get("SCALP_SL_POINTS", "150"))
INP_BASKET_PROFIT = float(os.environ.get("SCALP_BASKET_PROFIT", "0"))
INP_MAX_SPREAD = int(os.environ.get("SCALP_MAX_SPREAD", "25"))
INP_COOLDOWN_SEC = int(os.environ.get("SCALP_COOLDOWN", "3"))
INP_DAILY_LOSS_PCT = float(os.environ.get("SCALP_DAILY_LOSS_PCT", "5.0"))
INP_START_HOUR = int(os.environ.get("SCALP_START_HOUR", "8"))
INP_END_HOUR = int(os.environ.get("SCALP_END_HOUR", "20"))
INP_LOT_PER_BALANCE = float(os.environ.get("SCALP_LOT_PER_BALANCE", "0.01"))  # per 1000
SCALP_RISK_PCT = float(os.environ.get("SCALP_RISK_PCT", "5.0"))  # % equity per kitaran
SCALP_COMPOUND = os.environ.get("SCALP_COMPOUND", "equity").lower()  # balance|equity
MAGIC = int(os.environ.get("SCALP_MAGIC", "20261109"))
SLEEP_SEC = 2


def log(m):
    print(f"{datetime.now(MYT).strftime('%Y-%m-%dT%H:%M:%S')} {m}", flush=True)


def mt5(payload, timeout=120):
    tmp = Path("/tmp/mt5_bridge.py")
    # Bridge sedia ada dalam mt5-pending.py; guna helper tempatan untuk memanggil.
    import importlib.util
    spec = importlib.util.spec_from_file_location("pending", HERE / "mt5-pending.py")
    pend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pend)
    return pend.mt5(payload, timeout=timeout)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"cycles": [], "day": "", "start_balance": 0.0, "last_close": 0}


def save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    t = STATE.with_suffix(".tmp")
    t.write_text(json.dumps(d))
    t.replace(STATE)


def dynamic_lot(balance, equity, price, sl):
    """Lot berasaskan risiko + compounding.

    Jumlah risiko kitaran dibahagi sama rata kepada InpPositions supaya
    basket penuh maksimum SCALP_RISK_PCT daripada modal asas.
    """
    base = float(equity if SCALP_COMPOUND == "equity" else balance)
    risk_money_total = base * SCALP_RISK_PCT / 100.0
    risk_money_each = risk_money_total / max(1, INP_POSITIONS)
    # Ambil tick value/size secara terus dari broker untuk XAUUSD.
    spec = mt5({"action": "symbol", "symbol": SYMBOL})
    tick_size = float(spec.get("tick_size") or spec.get("point") or 0.01)
    tick_value = float(spec.get("tick_value") or 0)
    if tick_value <= 0 or tick_size <= 0 or abs(price - sl) <= 0:
        return 0.01
    loss_per_lot = abs(price - sl) / tick_size * tick_value
    lot = risk_money_each / loss_per_lot
    step = float(spec.get("vol_step") or 0.01)
    vmin = float(spec.get("vol_min") or step)
    vmax = float(spec.get("vol_max") or lot)
    lot = max(vmin, min(vmax, (int(lot / step) * step)))
    return round(lot, 2)


def get_signal(bars):
    """EMA8 vs EMA21 + harga >/< EMA9. Return +1 BUY, -1 SELL, 0."""
    closes = [b[3] for b in bars]
    if len(closes) < 60:
        return 0
    def ema(v, n):
        k = 2.0 / (n + 1)
        e = v[0]; out = [e]
        for x in v[1:]:
            e = x * k + e * (1 - k); out.append(e)
        return out
    f = ema(closes, 8)
    s = ema(closes, 21)
    last = closes[-1]
    if f[-1] > s[-1] and last > f[-1]:
        return 1
    if f[-1] < s[-1] and last < f[-1]:
        return -1
    return 0


def main():
    st = load_state()
    day = datetime.now(MYT).strftime("%Y-%m-%d")
    if st.get("day") != day:
        st["day"] = day
        st["start_balance"] = float((mt5({"action": "state"}).get("balance")) or 0)
        st["cycles"] = []
        save_state(st)
        log(f"DAY-RESET {day} start_balance={st['start_balance']:.2f}")

    live = mt5({"action": "state"})
    if not live.get("ok"):
        log(f"MT5-ERR {live.get('error')}")
        time.sleep(5)
        return
    orders = live.get("orders", [])
    positions = live.get("positions", [])
    mine_pos = [p for p in positions if int(p.get("magic", 0) or 0) == MAGIC]
    mine_ord = [o for o in orders if int(o.get("magic", 0) or 0) == MAGIC]

    # daily loss stop
    bal = float(live.get("balance") or 0)
    start = float(st.get("start_balance") or bal)
    if INP_DAILY_LOSS_PCT > 0 and start > 0 and bal <= start * (1 - INP_DAILY_LOSS_PCT / 100.0):
        log(f"DAILY-LOSS-HIT bal={bal:.2f} start={start:.2f} stop buka baharu")
        return

    # basket close
    if mine_pos and INP_BASKET_PROFIT > 0:
        total = sum(float(p.get("profit") or 0) for p in mine_pos)
        if total >= INP_BASKET_PROFIT:
            for p in mine_pos:
                r = mt5({"action": "close_position", "ticket": int(p["ticket"])})
                log(f"BASKET-CLOSE ticket={p['ticket']} total_profit={total:.2f} ok={r.get('ok')} retcode={r.get('retcode')}")
            save_state(st)
            return

    if mine_pos or mine_ord:
        st["last_close"] = time.time()
        save_state(st)
        return

    # cooldown
    if time.time() - st.get("last_close", 0) < INP_COOLDOWN_SEC:
        return

    # jam dagang (server/MYT)
    hh = datetime.now(MYT).hour
    if not (INP_START_HOUR <= hh < INP_END_HOUR):
        return

    # spread guard + tick
    info = mt5({"action": "symbol", "symbol": SYMBOL})
    if not info.get("ok"):
        log(f"SYM-ERR {SYMBOL}: {info.get('error')}")
        return
    spread = float(info.get("spread_price") or 0)
    if INP_MAX_SPREAD > 0 and spread > INP_MAX_SPREAD:
        log(f"SPREAD-SKIP {spread:.2f} > {INP_MAX_SPREAD}")
        return

    # kira signal (ambik 2 bar M1 terkini dari sq-bars.db kalau ada, jangan -glock)
    sig = 0
    try:
        data = mt5({"action": "candles", "symbol": SYMBOL, "count": 300})
        rows = data.get("bars", [])
        bars = [(float(r["t"]) * 1000, float(r["h"]), float(r["l"]), float(r["c"])) for r in rows]
        sig = get_signal(bars)
    except Exception as ex:
        log(f"BARS-WARN {type(ex).__name__}: {ex}")

    if sig == 0:
        log("SIGNAL-SKIP (tiada crossover EMA pada bar ini)")
        return

    tick = mt5({"action": "tick", "symbol": SYMBOL})
    bid = float(tick.get("bid") or info.get("bid") or 0)
    ask = float(tick.get("ask") or info.get("ask") or 0)
    point = float(info.get("point") or 0.01)
    tp_px = float(INP_TP_POINTS) * point
    sl_px = float(INP_SL_POINTS) * point
    for i in range(INP_POSITIONS):
        side = "BUY" if sig > 0 else "SELL"
        sl = (ask - sl_px) if side == "BUY" else (bid + sl_px)
        tp = (ask + tp_px) if side == "BUY" else (bid - tp_px)
        lot = dynamic_lot(bal, float(live.get("equity") or bal), ask if side == "BUY" else bid, sl)
        r = mt5({"action": "market", "symbol": SYMBOL, "side": side,
                 "sl": sl, "tp": tp, "lot": lot, "magic": MAGIC,
                 "deviation": 20, "comment": "SCALP"})
        if r.get("ok"):
            log(f"OPEN {side} lot={lot} risk={SCALP_RISK_PCT}% base={SCALP_COMPOUND} entry={r.get('price')} sl={sl} tp={tp} ticket={r.get('ticket')}")
        else:
            log(f"OPEN-FAIL {side} retcode={r.get('retcode')} comment={r.get('comment')} "
                f"bid={bid} ask={ask} lot={lot}")
        time.sleep(0.4)
    st["last_close"] = time.time()
    st.setdefault("cycles", []).append({"at": datetime.now(MYT).isoformat(), "side": "BUY" if sig > 0 else "SELL", "lot": lot, "risk_pct": SCALP_RISK_PCT})
    save_state(st)


if __name__ == "__main__":
    import sys, fcntl
    sys.path.insert(0, str(HERE))
    fd = open(LOCK, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("SKIP instance lain sedang jalan")
        sys.exit(0)
    while True:
        try:
            main()
        except Exception as ex:
            log(f"FATAL {type(ex).__name__}: {ex}")
        time.sleep(SLEEP_SEC)
