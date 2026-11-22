#!/usr/bin/env python3
"""
Ironwall Hedge V7 <-> Python bridge  (XAUUSD M5, hedge + doubling-lot recovery EA)

What it does
  * Reads the EA's live state from MetaTrader 5 (positions + pending STOP orders)
    and turns it into a snapshot: BUY/SELL lots, net exposure, floating P/L,
    ladder level (0.01 -> 0.02 -> 0.04 ... ), equity drawdown, margin level.
  * Logs every snapshot to JSONL, prints a status line, optionally sends Telegram alerts.
  * Serves the snapshot on http://127.0.0.1:8765/status and accepts commands
    (close_all, close_side, cancel_pending, halt, resume) so other tools/scripts can drive it.
  * Independent kill-switch guards (max floating loss, max drawdown %, max lot size,
    max ladder level, min margin level). Guards only ALERT unless you pass --enforce.

It does not need the EA's source: it identifies the EA by --symbol and optionally
--magic / --comment (magic 0 = every magic number).

Requirements: Windows + MetaTrader 5 terminal logged in + `pip install MetaTrader5`
(the official package only exists for Windows). Use --mock to try it anywhere.

Examples
  python ironwall_bridge.py --symbol XAUUSD --magic 0
  python ironwall_bridge.py --symbol XAUUSD --max-loss 300 --max-dd 15 --max-lot 0.64 --enforce
  python ironwall_bridge.py --mock --max-lot 0.32 --enforce
"""
import argparse
import json
import logging
import math
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

log = logging.getLogger("ironwall")
BUY, SELL = 0, 1  # mt5.POSITION_TYPE_BUY / SELL


# --------------------------------------------------------------------------- clients
class MT5Client:
    """Thin wrapper over the official MetaTrader5 package."""

    def __init__(self, args):
        import MetaTrader5 as mt5  # imported lazily so --mock works without it
        self.mt5 = mt5
        kw = {}
        if args.terminal:
            kw["path"] = args.terminal
        if args.login:
            kw.update(login=args.login, password=args.password or "", server=args.server or "")
        if not mt5.initialize(**kw):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.symbol_select(args.symbol, True):
            raise RuntimeError(f"Symbol {args.symbol} not found: {mt5.last_error()}")
        self.deviation = args.deviation

    def account(self):
        return self.mt5.account_info()

    def positions(self, symbol):
        return list(self.mt5.positions_get(symbol=symbol) or [])

    def orders(self, symbol):
        return list(self.mt5.orders_get(symbol=symbol) or [])

    def _filling(self, symbol):
        mt5 = self.mt5
        mode = mt5.symbol_info(symbol).filling_mode
        if mode & 1:
            return mt5.ORDER_FILLING_FOK
        if mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def close_position(self, p):
        mt5 = self.mt5
        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "position": p.ticket,
            "volume": p.volume, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask, "deviation": self.deviation,
            "magic": p.magic, "comment": "ironwall_bridge", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(p.symbol),
        }
        r = mt5.order_send(req)
        return r is not None and r.retcode == mt5.TRADE_RETCODE_DONE

    def delete_order(self, o):
        mt5 = self.mt5
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
        return r is not None and r.retcode == mt5.TRADE_RETCODE_DONE

    def shutdown(self):
        self.mt5.shutdown()


class MockClient:
    """Fake ladder that doubles every few polls, for testing the bridge off-Windows."""

    def __init__(self, args):
        self.t = 0
        self.balance = 10000.0
        self.pos, self.ord = [], []
        self.next_ticket = 1
        self._grow()

    def _mk(self, typ, vol, profit):
        self.next_ticket += 1
        return SimpleNamespace(ticket=self.next_ticket, symbol="XAUUSD", type=typ, volume=vol,
                               profit=profit, swap=0.0, magic=777, comment="IRONWALL")

    def _grow(self):
        lvl = len(self.pos) // 2
        vol = round(0.01 * 2 ** lvl, 2)
        self.pos += [self._mk(BUY, vol, -2.0 * vol * 100), self._mk(SELL, vol, -1.0 * vol * 100)]
        self.ord = [SimpleNamespace(ticket=self.next_ticket + 100, symbol="XAUUSD",
                                    type=4, volume=round(vol * 2, 2))]

    def account(self):
        fl = sum(p.profit for p in self.pos)
        eq = self.balance + fl
        used = 1000.0 * max(1, len(self.pos))
        return SimpleNamespace(balance=self.balance, equity=eq, margin=used,
                               margin_level=eq / used * 100)

    def positions(self, symbol):
        self.t += 1
        if self.t % 2 == 0 and len(self.pos) < 16:
            self._grow()
        return list(self.pos)

    def orders(self, symbol):
        return list(self.ord)

    def close_position(self, p):
        self.pos = [x for x in self.pos if x.ticket != p.ticket]
        return True

    def delete_order(self, o):
        self.ord = [x for x in self.ord if x.ticket != o.ticket]
        return True

    def shutdown(self):
        pass


# --------------------------------------------------------------------------- bridge
class Bridge:
    def __init__(self, client, args):
        self.c, self.a = client, args
        self.lock = threading.Lock()
        self.halted = False
        self.peak_equity = 0.0
        self.last_alert = {}
        self.snapshot = {}

    # ---- selection
    def _mine(self, items):
        a = self.a
        out = []
        for x in items:
            if a.magic and getattr(x, "magic", 0) != a.magic:
                continue
            if a.comment and a.comment.lower() not in (getattr(x, "comment", "") or "").lower():
                continue
            out.append(x)
        return out

    # ---- snapshot
    def take_snapshot(self):
        with self.lock:
            pos = self._mine(self.c.positions(self.a.symbol))
            pend = self._mine(self.c.orders(self.a.symbol))
            acc = self.c.account()
        buy = sum(p.volume for p in pos if p.type == BUY)
        sell = sum(p.volume for p in pos if p.type == SELL)
        floating = sum(p.profit + getattr(p, "swap", 0.0) for p in pos)
        max_lot = max([p.volume for p in pos] + [o.volume for o in pend] + [0.0])
        level = 0 if max_lot <= 0 else max(1, round(math.log2(max_lot / self.a.base_lot)) + 1)
        self.peak_equity = max(self.peak_equity, acc.equity)
        dd = (self.peak_equity - acc.equity) / self.peak_equity * 100 if self.peak_equity else 0.0
        self.snapshot = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "symbol": self.a.symbol,
            "positions": len(pos), "pending": len(pend),
            "buy_lots": round(buy, 2), "sell_lots": round(sell, 2), "net_lots": round(buy - sell, 2),
            "max_lot": round(max_lot, 2), "ladder_level": level,
            "floating": round(floating, 2), "balance": round(acc.balance, 2),
            "equity": round(acc.equity, 2), "dd_pct": round(dd, 2),
            "margin_level": round(acc.margin_level, 1) if acc.margin else None,
            "halted": self.halted,
        }
        return self.snapshot, pos, pend

    # ---- guards
    def breaches(self, s):
        a, out = self.a, []
        if a.max_loss and s["floating"] <= -a.max_loss:
            out.append(f"floating {s['floating']} <= -{a.max_loss}")
        if a.max_dd and s["dd_pct"] >= a.max_dd:
            out.append(f"drawdown {s['dd_pct']}% >= {a.max_dd}%")
        if a.max_lot and s["max_lot"] >= a.max_lot:
            out.append(f"lot {s['max_lot']} >= {a.max_lot}")
        if a.max_level and s["ladder_level"] >= a.max_level:
            out.append(f"ladder level {s['ladder_level']} >= {a.max_level}")
        if a.min_margin and s["margin_level"] is not None and s["margin_level"] <= a.min_margin:
            out.append(f"margin level {s['margin_level']}% <= {a.min_margin}%")
        return out

    # ---- actions
    def close_all(self, side=None, cancel_pending=True):
        closed = failed = 0
        with self.lock:
            pos = self._mine(self.c.positions(self.a.symbol))
            if side:
                pos = [p for p in pos if p.type == (BUY if side == "buy" else SELL)]
            for p in sorted(pos, key=lambda p: -p.volume):  # biggest exposure first
                if self.c.close_position(p):
                    closed += 1
                else:
                    failed += 1
            if cancel_pending and not side:
                for o in self._mine(self.c.orders(self.a.symbol)):
                    self.c.delete_order(o)
        return {"closed": closed, "failed": failed}

    def cancel_pending(self):
        n = 0
        with self.lock:
            for o in self._mine(self.c.orders(self.a.symbol)):
                n += bool(self.c.delete_order(o))
        return {"cancelled": n}

    def handle_command(self, cmd, side=None):
        if cmd == "close_all":
            return self.close_all()
        if cmd == "close_side" and side in ("buy", "sell"):
            return self.close_all(side=side)
        if cmd == "cancel_pending":
            return self.cancel_pending()
        if cmd == "halt":
            self.halted = True
            return {"halted": True, **self.close_all()}
        if cmd == "resume":
            self.halted = False
            return {"halted": False}
        return {"error": f"unknown command {cmd!r}"}

    # ---- alerts
    def alert(self, key, text):
        now = time.time()
        if now - self.last_alert.get(key, 0) < self.a.alert_every:
            return
        self.last_alert[key] = now
        log.warning(text)
        tok, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT")
        if tok and chat:
            try:
                data = urllib.parse.urlencode({"chat_id": chat, "text": f"[Ironwall] {text}"}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=10)
            except Exception as e:  # alerts must never crash the loop
                log.error("telegram failed: %s", e)

    # ---- main loop
    def run(self):
        logf = open(self.a.log, "a", encoding="utf-8") if self.a.log else None
        try:
            while True:
                try:
                    s, pos, _ = self.take_snapshot()
                    if logf:
                        logf.write(json.dumps(s) + "\n")
                        logf.flush()
                    log.info("pos=%d pend=%d BUY %.2f SELL %.2f lvl=%d float=%.2f eq=%.2f dd=%.1f%% ml=%s%s",
                             s["positions"], s["pending"], s["buy_lots"], s["sell_lots"], s["ladder_level"],
                             s["floating"], s["equity"], s["dd_pct"], s["margin_level"],
                             " HALTED" if self.halted else "")
                    hits = self.breaches(s)
                    if hits and not self.halted:
                        self.alert("guard", "GUARD: " + "; ".join(hits))
                        if self.a.enforce:
                            self.halted = True
                            self.alert("halt", f"enforce ON -> flattening: {self.close_all()}")
                    elif self.halted and pos:
                        # EA re-opened trades after a halt: keep flat until `resume`.
                        self.alert("reflat", "halted but EA opened trades again; disable the EA/AutoTrading. "
                                   f"Flattening: {self.close_all()}")
                except Exception as e:
                    log.exception("poll error: %s", e)
                if self.a.once:
                    return
                time.sleep(self.a.interval)
        finally:
            if logf:
                logf.close()


# --------------------------------------------------------------------------- http api
def make_handler(bridge, token):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self):
            if token and self.headers.get("X-Token") != token:
                self._send(401, {"error": "bad token"})
                return False
            return True

        def do_GET(self):
            if self.path == "/status" and self._auth():
                self._send(200, bridge.snapshot)
            elif self.path != "/status":
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/command" or not self._auth():
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                self._send(200, bridge.handle_command(req.get("cmd"), req.get("side")))
            except Exception as e:
                self._send(400, {"error": str(e)})

        def log_message(self, *_):
            pass
    return H


# --------------------------------------------------------------------------- main
def parse():
    p = argparse.ArgumentParser(description="Ironwall Hedge V7 Python bridge")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--magic", type=int, default=0, help="EA magic number (0 = any)")
    p.add_argument("--comment", default="", help="only trades whose comment contains this")
    p.add_argument("--base-lot", type=float, default=0.01, help="first lot of the ladder")
    p.add_argument("--interval", type=float, default=2.0, help="poll seconds")
    p.add_argument("--deviation", type=int, default=30)
    p.add_argument("--terminal", help="path to terminal64.exe")
    p.add_argument("--login", type=int)
    p.add_argument("--password")
    p.add_argument("--server")
    g = p.add_argument_group("guards (0 = off). Alert only, unless --enforce")
    g.add_argument("--max-loss", type=float, default=0, help="floating loss in account currency")
    g.add_argument("--max-dd", type=float, default=0, help="equity drawdown %% from peak")
    g.add_argument("--max-lot", type=float, default=0, help="largest single lot (position or pending)")
    g.add_argument("--max-level", type=int, default=0, help="ladder level (0.01=1, 0.02=2, 0.04=3...)")
    g.add_argument("--min-margin", type=float, default=0, help="margin level %% floor")
    g.add_argument("--enforce", action="store_true", help="close everything when a guard trips")
    p.add_argument("--alert-every", type=int, default=60, help="seconds between repeated alerts")
    p.add_argument("--port", type=int, default=8765, help="0 = disable HTTP API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--token", default=os.getenv("IRONWALL_TOKEN", ""), help="X-Token for the HTTP API")
    p.add_argument("--log", default="ironwall_log.jsonl")
    p.add_argument("--mock", action="store_true", help="simulated ladder, no MT5 needed")
    p.add_argument("--once", action="store_true", help="single poll then exit")
    return p.parse_args()


def main():
    a = parse()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    client = MockClient(a) if a.mock else MT5Client(a)
    bridge = Bridge(client, a)
    if a.port:
        srv = ThreadingHTTPServer((a.host, a.port), make_handler(bridge, a.token))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("API on http://%s:%d  (/status, POST /command)", a.host, a.port)
    try:
        bridge.run()
    except KeyboardInterrupt:
        pass
    finally:
        client.shutdown()


if __name__ == "__main__":
    sys.exit(main())
