#!/usr/bin/env python3
"""TraderWatch single market-data source: the owner's MT5 broker (RoboForex).

Owner decision (2026-11-21): MT5 is THE feed for every client-facing flow
(live price, on-demand scan, auto signals, paper league). There is NO
Swissquote fallback — when the bridge is down we fail closed and the website
shows a maintenance banner (state/mt5-bridge-status.json -> data/mt5-bridge.json)
so the owner can restart the bridge instead of silently trading another feed.

Bar timestamps come back in the broker SERVER timezone (RoboForex UTC+2/+3);
we detect the offset against a 24/7 symbol (BTCUSD) and normalize to UTC so
bar times line up with opened_at / posted_at (which are UTC).

Interface mirrors sq_collector.candles_from_bars so consumers swap with a
one-line change: candles() -> [{"t": ISO_UTC, "o","h","l","c"}, ...] or [].
"""
import importlib.util as _il
import json
import pathlib
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
STATE = REPO / "state"
STATUS_FILE = STATE / "mt5-bridge-status.json"
OFFSET_FILE = STATE / "mt5-time-offset.json"
# Web-accessible copies (Caddy serves /data/* no-cache). All three app roots.
DATA_TARGETS = [REPO / "pwa-app" / "data", REPO / "member" / "data", REPO / "data"]

_spec = _il.spec_from_file_location("mt5_read", HERE / "mt5_read.py")
_mr = _il.module_from_spec(_spec)
_spec.loader.exec_module(_mr)

# Swissquote gran labels -> MT5 timeframe (collector stored H1 as "M60").
_GRAN = {"M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
         "M60": "H1", "H1": "H1", "H4": "H4", "D1": "D1"}


def _now():
    return datetime.now(timezone.utc)


def _call(args, timeout=90):
    """Run a mt5_read bridge command; return parsed dict or None on any failure."""
    try:
        out, _err = _mr.run(args, timeout=timeout)
        if not out:
            return None
        d = json.loads(out)
        return None if d.get("error") else d
    except Exception:
        return None


def read_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {"ok": None, "checked_at": None, "last_error": "status unknown"}


def is_up():
    return read_status().get("ok") is True


def _write_status(ok, error="", extra=None):
    prev = read_status()
    st = {
        "ok": bool(ok),
        "checked_at": _now().isoformat(),
        "last_ok_at": _now().isoformat() if ok else prev.get("last_ok_at"),
        "last_error": "" if ok else (error or "MT5 bridge unavailable"),
        "consecutive_fails": 0 if ok else int(prev.get("consecutive_fails", 0)) + 1,
    }
    if extra:
        st.update(extra)
    try:
        STATE.mkdir(exist_ok=True)
        STATUS_FILE.write_text(json.dumps(st))
    except Exception:
        pass
    return st


def publish_status(st=None):
    """Copy bridge status to every web data/ dir so the site banner can read it."""
    st = st or read_status()
    payload = {"ok": st.get("ok"), "checked_at": st.get("checked_at"),
               "last_ok_at": st.get("last_ok_at"), "last_error": st.get("last_error"),
               "consecutive_fails": st.get("consecutive_fails", 0),
               "market": st.get("market", "open"), "next_open": st.get("next_open"),
               "broker_offset_hours": st.get("broker_offset_hours", 0),
               "source": "MT5 broker (RoboForex)"}
    for d in DATA_TARGETS:
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "mt5-bridge.json.tmp"
            tmp.write_text(json.dumps(payload, separators=(",", ":")))
            tmp.replace(d / "mt5-bridge.json")
        except Exception:
            pass


def _forex_market(offset):
    """Forex session status from the broker server offset (auto DST-adjust).
    RoboForex forex runs Mon 00:00 -> Fri 23:59 SERVER time. Monday 00:00
    server == Sunday (24-offset):00 UTC. Returns (closed, next_open_utc).
    Crypto (BTCUSD) trades 24/7 — this is the forex/metals session banner."""
    now = _now()
    open_hour = (24 - int(offset)) % 24
    days_to_sun = (6 - now.weekday()) % 7
    nxt = (now + timedelta(days=days_to_sun)).replace(
        hour=open_hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=7)
    prev_close = nxt - timedelta(days=2)   # Friday same hour UTC
    return (prev_close <= now < nxt), nxt


def health():
    """Bridge liveness = account_info responds (terminal up). Market-closed on
    weekends is NOT a bridge failure — it is reported separately with the next
    forex open time so the site can show a countdown in the client's timezone.
    Writes + publishes status; returns it."""
    acc = _call(["account"], timeout=60)
    bridge_up = bool(acc and acc.get("login"))
    offset = _offset_hours()
    closed, nxt = _forex_market(offset)
    extra = {"market": "closed" if closed else "open",
             "next_open": nxt.isoformat(), "broker_offset_hours": offset}
    if bridge_up:
        extra.update({"server": acc.get("server"), "equity": acc.get("equity"),
                      "login": acc.get("login")})
        st = _write_status(True, "", extra)
    else:
        st = _write_status(False, "MT5 bridge/terminal not responding — restart the bridge", extra)
    publish_status(st)
    return st


def _offset_hours():
    """Broker server-time offset (hours), cached <=1h. Detected from a BTCUSD
    tick (crypto trades 24/7, so reliable even on forex weekends)."""
    cached, updated = 0, None
    try:
        d = json.loads(OFFSET_FILE.read_text())
        cached = int(d.get("offset_hours", 0))
        updated = datetime.fromisoformat(d.get("updated"))
    except Exception:
        pass
    if updated and (_now() - updated).total_seconds() < 3600:
        return cached
    tk = _call(["tick", "BTCUSD"], timeout=60)
    if tk and tk.get("time"):
        t = datetime.fromtimestamp(int(tk["time"]), timezone.utc)
        off = round((t - _now()).total_seconds() / 3600)
        if -14 <= off <= 14:
            try:
                OFFSET_FILE.write_text(json.dumps({"offset_hours": off,
                                                   "updated": _now().isoformat()}))
            except Exception:
                pass
            return off
    return cached


def candles(pair, gran="M15", count=300):
    """MT5 broker bars as sq_collector-compatible rows [{t:ISO_UTC,o,h,l,c}].
    Returns [] when the bridge is down (NO Swissquote fallback)."""
    g = _GRAN.get(str(gran).upper(), "M15")
    p = "".join(ch for ch in str(pair).upper() if ch.isalpha())
    d = _call(["candles", p, g, str(int(count))])
    if not d or not d.get("bars"):
        return []
    off = _offset_hours()
    rows = []
    for b in d["bars"]:
        try:
            t = datetime.fromtimestamp(int(b["t"]), timezone.utc) - timedelta(hours=off)
            rows.append({"t": t.isoformat(), "o": float(b["o"]), "h": float(b["h"]),
                         "l": float(b["l"]), "c": float(b["c"])})
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def tick(pair):
    p = "".join(ch for ch in str(pair).upper() if ch.isalpha())
    return _call(["tick", p])


def mid(pair):
    """(bid+ask)/2 from the broker, or None when the bridge is down."""
    tk = tick(pair)
    if tk and tk.get("bid") and tk.get("ask"):
        return round((float(tk["bid"]) + float(tk["ask"])) / 2.0, 5)
    return None


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    if cmd == "health":
        print(json.dumps(health(), indent=1))
    elif cmd == "status":
        print(json.dumps(read_status(), indent=1))
    elif cmd == "candles":
        print(json.dumps(candles(sys.argv[2], sys.argv[3], int(sys.argv[4]))[:3], indent=1))
    elif cmd == "mid":
        print(mid(sys.argv[2]))