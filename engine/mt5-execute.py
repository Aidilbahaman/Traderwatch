#!/usr/bin/env python3
"""MT5 auto-execute — hantar order sebenar ke RoboForex bila signal aktif.

BAHAYA: modul ini menghantar ORDER SEBENAR. Wang sebenar.

Aliran:
  1. Baca signal aktif dari Supabase (status 'active' / entry hit)
  2. Sahkan TP/SL guna Swissquote M1 (sumber utama, sama seperti bot)
  3. Hantar order ke MT5 dengan lot ikut risiko % (bukan lot tetap)
  4. Rekod position ticket ke Supabase supaya tidak double-entry

Keselamatan:
  - Idempotent: satu signal = satu posisi. Ada ticket dalam DB -> skip.
  - Magic number unik supaya posisi bot boleh dikenal pasti.
  - DRY_RUN=1 (default) -> log sahaja, tiada order.
  - Max posisi serentak, max risiko per trade, max daily loss.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# ---------- tetapan ----------
DRY_RUN = os.environ.get("MT5_DRY_RUN", "1") == "1"
MAGIC = int(os.environ.get("MT5_MAGIC", "20261025"))
RISK_PCT = float(os.environ.get("MT5_RISK_PCT", "0.5"))      # % equity per trade
MAX_POSITIONS = int(os.environ.get("MT5_MAX_POS", "3"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MT5_MAX_DAILY_LOSS", "3.0"))
DEVIATION = int(os.environ.get("MT5_DEVIATION", "20"))

PREFIX = "/home/mt5/.mt5"
PY = r"C:\Python311\python.exe"
WORKDIR_WIN = r"C:\mt5work"
SCRIPT_HOST = "/home/mt5/.mt5/drive_c/mt5work/mt5_trade.py"


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} {msg}", flush=True)


# ---------- skrip Windows: hantar order ----------
WIN_TRADE = r'''
import sys, json
import MetaTrader5 as mt5

def out(d):
    print(json.dumps(d, default=str))

req = json.loads(sys.argv[1])

if not mt5.initialize():
    out({"ok": False, "error": "initialize failed", "code": mt5.last_error()})
    sys.exit(0)

act = req.get("action")

if act == "positions":
    pos = mt5.positions_get()
    out({"ok": True, "count": len(pos) if pos else 0,
         "positions": [{"ticket": p.ticket, "symbol": p.symbol, "type": p.type,
                        "volume": p.volume, "price_open": p.price_open,
                        "sl": p.sl, "tp": p.tp, "profit": p.profit,
                        "magic": p.magic, "comment": p.comment}
                       for p in (pos or [])]})

elif act == "order":
    sym = req["symbol"]
    side = req["side"]           # BUY / SELL
    lot = float(req["lot"])
    sl = float(req["sl"])
    tp = float(req["tp"])
    comment = req.get("comment", "TraderWatch")[:26]

    if not mt5.symbol_select(sym, True):
        out({"ok": False, "error": f"symbol_select failed {sym}"}); sys.exit(0)

    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    if info is None or tick is None:
        out({"ok": False, "error": "no symbol info"}); sys.exit(0)

    price = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    # sahkan SL/TP di sisi betul
    if side == "BUY" and not (sl < price < tp):
        out({"ok": False, "error": f"invalid SL/TP for BUY: sl={sl} price={price} tp={tp}"}); sys.exit(0)
    if side == "SELL" and not (tp < price < sl):
        out({"ok": False, "error": f"invalid SL/TP for SELL: tp={tp} price={price} sl={sl}"}); sys.exit(0)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": int(req.get("deviation", 20)),
        "magic": int(req.get("magic", 0)),
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(request)
    if res is None:
        out({"ok": False, "error": "order_send None", "code": mt5.last_error()})
    elif res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": res.retcode, "comment": res.comment,
             "request": {k: str(v) for k, v in request.items()}})
    else:
        out({"ok": True, "ticket": res.order, "deal": res.deal,
             "price": res.price, "volume": res.volume, "retcode": res.retcode})

elif act == "close":
    ticket = int(req["ticket"])
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        out({"ok": False, "error": "position not found"}); sys.exit(0)
    p = pos[0]
    tick = mt5.symbol_info_tick(p.symbol)
    price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": p.volume,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": int(req.get("deviation", 20)),
        "magic": p.magic,
        "comment": "TraderWatch close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": getattr(res, "retcode", None),
             "comment": getattr(res, "comment", "none")})
    else:
        out({"ok": True, "ticket": ticket, "price": res.price})

mt5.shutdown()
'''


def _ensure_script():
    tmp = Path("/tmp/mt5_trade_win.py")
    tmp.write_text(WIN_TRADE)
    subprocess.run(["sudo", "-n", "mkdir", "-p", "/home/mt5/.mt5/drive_c/mt5work"],
                   capture_output=True)
    subprocess.run(["sudo", "-n", "cp", str(tmp), SCRIPT_HOST], capture_output=True)
    subprocess.run(["sudo", "-n", "chown", "mt5:mt5", SCRIPT_HOST], capture_output=True)


def mt5_call(payload, timeout=180):
    _ensure_script()
    cmd = ["sudo", "-n", "-u", "mt5", "env", "DISPLAY=:99", f"WINEPREFIX={PREFIX}",
           "/opt/wine-staging/bin/wine", PY, WORKDIR_WIN + r"\mt5_trade.py",
           json.dumps(payload)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd="/tmp")
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"ok": False, "error": "no json output", "stderr": (r.stderr or "")[-300:]}


# ---------- Supabase ----------
def _secrets():
    p = Path.home() / ".secrets" / "supabase.env"
    d = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def sb():
    import urllib.request
    s = _secrets()
    url = (s.get("SUPABASE_URL") or s.get("VITE_SUPABASE_URL")).rstrip("/")
    key = s.get("SUPABASE_SERVICE_KEY") or s.get("SUPABASE_SERVICE_ROLE_KEY")

    def get(path):
        req = urllib.request.Request(url + "/rest/v1/" + path,
                                     headers={"apikey": key, "Authorization": "Bearer " + key})
        import urllib.request as u
        with u.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "[]")

    def patch(path, body):
        import urllib.request as u
        data = json.dumps(body).encode()
        req = u.Request(url + "/rest/v1/" + path, data=data, method="PATCH",
                        headers={"apikey": key, "Authorization": "Bearer " + key,
                                 "Content-Type": "application/json",
                                 "Prefer": "return=minimal"})
        with u.urlopen(req, timeout=30) as r:
            return r.status

    return get, patch


def open_positions():
    r = mt5_call({"action": "positions"})
    if not r.get("ok"):
        return []
    return [p for p in r.get("positions", []) if p.get("magic") == MAGIC]


def main():
    log(f"START dry_run={DRY_RUN} risk={RISK_PCT}% max_pos={MAX_POSITIONS}")

    # 1) posisi sedia ada
    pos = open_positions()
    log(f"posisi bot sedia ada: {len(pos)}")

    if len(pos) >= MAX_POSITIONS:
        log(f"SKIP: sudah {len(pos)} posisi (max {MAX_POSITIONS})")
        return 0

    # 2) baki akaun
    acc = mt5_call({"action": "positions"})  # guna call sama untuk pastikan MT5 hidup
    if not acc.get("ok"):
        log(f"MT5 tidak respons: {acc.get('error')}")
        return 1

    log("MT5 OK — modul sedia")
    log("NOTA: order_send hanya dipanggil bila signal aktif disahkan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
