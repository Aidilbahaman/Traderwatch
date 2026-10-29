#!/usr/bin/env python3
"""MT5 pending-order sync — salin setup signal ke MT5 sebagai BUY/SELL LIMIT.

Aliran yang diminta owner:
  1. Owner post signal manual: XAUUSD SELL LIMIT @ entry, TP, SL
  2. Signal disimpan (Supabase) + dihantar ke semua member
  3. Modul ini letak PENDING LIMIT ORDER pada entry/TP/SL yang sama
  4. Biar harga berjalan. Bila harga sentuh entry, MT5 fill sendiri.
  5. Lifecycle hantar "ENTRY TRIGGERED" — tetapi MT5 TIDAK buka posisi baru
     (kerana limit order sudah jadi posisi). Ini elak double entry.

Kunci anti-duplicate:
  - Satu signal = satu pending order. Disimpan dalam state/mt5-orders.json
  - Magic number unik per signal (MAGIC_BASE + id)
  - Bila entry triggered, pending order jadi posisi — modul nampak ticket
    dan TIDAK hantar order baru.

Mod: MT5_MODE=plan (default, log sahaja) | live (hantar order)
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STATE = REPO / "state" / "mt5-orders.json"
MYT = timezone(timedelta(hours=8))

MODE = os.environ.get("MT5_MODE", "live")          # plan | live
LOT = float(os.environ.get("MT5_LOT", "1.00"))
MAGIC_BASE = int(os.environ.get("MT5_MAGIC_BASE", "20261000"))
DEVIATION = int(os.environ.get("MT5_DEVIATION", "20"))
# Ubah max_pending jadi lebih banyak (cth: 10) supaya banyak pending order boleh masuk serentak
MAX_PENDING = int(os.environ.get("MT5_MAX_PENDING", "10"))
# Turunkan sleep kepada 2 saat untuk respon yang lebih pantas (hampir instant)
SLEEP_SEC = 2
# Senarai symbol dibenarkan (kosong = semua). Guna untuk hadkan ke BTCUSD
# semasa ujian luar waktu forex.
ALLOW = [x.strip().upper() for x in os.environ.get("MT5_ALLOW", "").split(",") if x.strip()]

# ---------- kill switch ----------
# Berhenti hantar order baru bila rugi harian capai had. Posisi sedia ada
# TIDAK ditutup (biar TP/SL uruskan) — hanya tiada order baru.
KILL_PCT = float(os.environ.get("MT5_KILL_PCT", "3.0"))     # % equity sehari
KILL_STATE = REPO / "state" / "mt5-kill.json"

PREFIX = "/home/mt5/.mt5"
PY = r"C:\Python311\python.exe"
WIN_SCRIPT_HOST = "/home/mt5/.mt5/drive_c/mt5work/mt5_pending.py"


def log(m):
    ts = datetime.now(MYT).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} {m}", flush=True)


# ============================================================
# Skrip Windows: pending order + senarai pending/posisi
# ============================================================
WIN = r'''
import sys, json
import MetaTrader5 as mt5

def out(d):
    print(json.dumps(d, default=str))

req = json.loads(sys.argv[1])
if not mt5.initialize():
    out({"ok": False, "error": "init failed", "code": mt5.last_error()}); sys.exit(0)

act = req.get("action")

if act == "state":
    orders = mt5.orders_get() or []
    pos = mt5.positions_get() or []
    out({"ok": True,
         "orders": [{"ticket": o.ticket, "symbol": o.symbol, "type": o.type,
                     "volume": o.volume_current, "price_open": o.price_open,
                     "sl": o.sl, "tp": o.tp, "magic": o.magic,
                     "comment": o.comment} for o in orders],
         "positions": [{"ticket": p.ticket, "symbol": p.symbol, "type": p.type,
                        "volume": p.volume, "price_open": p.price_open,
                        "sl": p.sl, "tp": p.tp, "magic": p.magic,
                        "comment": p.comment, "profit": p.profit} for p in pos]})

elif act == "place_limit":
    sym   = req["symbol"]
    side  = req["side"]
    entry = float(req["entry"])
    sl    = float(req["sl"])
    tp    = float(req["tp"])
    lot   = float(req["lot"])
    magic = int(req["magic"])
    comment = str(req.get("comment", "TW"))[:26]

    if not mt5.symbol_select(sym, True):
        out({"ok": False, "error": "symbol_select " + sym}); sys.exit(0)

    tick = mt5.symbol_info_tick(sym)
    info = mt5.symbol_info(sym)
    if tick is None or info is None:
        out({"ok": False, "error": "no tick/info"}); sys.exit(0)

    if side == "BUY":
        if entry < tick.ask:
            otype, tname = mt5.ORDER_TYPE_BUY_LIMIT, "BUY_LIMIT"
        else:
            otype, tname = mt5.ORDER_TYPE_BUY_STOP, "BUY_STOP"
        if not (sl < entry < tp):
            out({"ok": False, "error": "SL/TP invalid BUY"}); sys.exit(0)
    else:
        if entry > tick.bid:
            otype, tname = mt5.ORDER_TYPE_SELL_LIMIT, "SELL_LIMIT"
        else:
            otype, tname = mt5.ORDER_TYPE_SELL_STOP, "SELL_STOP"
        if not (tp < entry < sl):
            out({"ok": False, "error": "SL/TP invalid SELL"}); sys.exit(0)

    stops_level = info.trade_stops_level * info.point
    if stops_level:
        if side == "BUY" and abs(entry - tick.ask) < stops_level:
            out({"ok": False, "error": "too close to market"}); sys.exit(0)
        if side == "SELL" and abs(entry - tick.bid) < stops_level:
            out({"ok": False, "error": "too close to market"}); sys.exit(0)

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": sym, "volume": lot, "type": otype,
        "price": entry, "sl": sl, "tp": tp,
        "deviation": int(req.get("deviation", 20)),
        "magic": magic, "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    res = mt5.order_send(request)
    if res is None:
        out({"ok": False, "error": "order_send None", "code": mt5.last_error()})
    elif res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": res.retcode, "comment": res.comment,
             "type": tname, "bid": tick.bid, "ask": tick.ask})
    else:
        out({"ok": True, "ticket": res.order, "type": tname,
             "price": entry, "sl": sl, "tp": tp, "lot": lot, "magic": magic})

elif act == "cancel":
    ticket = int(req["ticket"])
    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": getattr(res, "retcode", None),
             "comment": getattr(res, "comment", "")})
    else:
        out({"ok": True, "ticket": ticket})

mt5.shutdown()
'''


def _ensure_script():
    tmp = Path("/tmp/mt5_pending_win.py")
    tmp.write_text(WIN)
    subprocess.run(["sudo", "-n", "mkdir", "-p", "/home/mt5/.mt5/drive_c/mt5work"],
                   capture_output=True)
    subprocess.run(["sudo", "-n", "cp", str(tmp), WIN_SCRIPT_HOST], capture_output=True)
    subprocess.run(["sudo", "-n", "chown", "mt5:mt5", WIN_SCRIPT_HOST], capture_output=True)


def mt5(payload, timeout=180):
    _ensure_script()
    cmd = ["sudo", "-n", "-u", "mt5", "env", "DISPLAY=:99", f"WINEPREFIX={PREFIX}",
           "/opt/wine-staging/bin/wine", PY, r"C:\mt5work\mt5_pending.py",
           json.dumps(payload)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd="/tmp")
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"ok": False, "error": "no json", "stderr": (r.stderr or "")[-250:]}


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"signals": {}}


def save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    tmp.replace(STATE)


def _secrets():
    p = Path.home() / ".secrets" / "supabase.env"
    d = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def sb_get(path):
    import urllib.request
    s = _secrets()
    url = (s.get("SUPABASE_URL") or s.get("VITE_SUPABASE_URL")).rstrip("/")
    key = s.get("SUPABASE_SERVICE_KEY") or s.get("SUPABASE_SERVICE_ROLE_KEY")
    req = urllib.request.Request(url + "/rest/v1/" + path,
                                 headers={"apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "[]")


def _status_map():
    """signal-status.json -> {status_key: {status, entry, closed}}.

    Jadual `signals` Supabase tiada kolum status; status sebenar ada di
    signal-status.json (ditulis signal-status.py). Kunci format:
    PAIR_YYYYMMDD_HHMMSS (MYT).
    """
    try:
        return json.loads((REPO / "signal-status.json").read_text()).get("signals", {})
    except Exception as e:
        log(f"STATUS-ERR {type(e).__name__}: {str(e)[:60]}")
        return {}


def _myt_key(pair, iso):
    """Tukar posted_at (UTC-naive) -> PAIR_YYYYMMDD_HHMMSS dalam MYT."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    s = str(iso or "")
    if s and not s.endswith("Z") and "+" not in s[10:]:
        s = s.replace(" ", "T") + "Z"
    try:
        d = _dt.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return ""
    d = d.astimezone(_tz(_td(hours=8)))
    code = "".join(c for c in str(pair).upper() if c.isalpha())
    return f"{code}_{d.strftime('%Y%m%d_%H%M%S')}"


def active_signals():
    """Signal yang BELUM entry (tiada dalam status atau status=pending).

    Hanya signal yang belum kena entry layak jadi pending limit order.
    Signal yang sudah entry/tp/sl/expired TIDAK boleh di-order semula.
    """
    try:
        rows = sb_get("signals?select=id,pair,side,timeframe,entry,sl,tp,posted_at"
                      "&order=posted_at.desc&limit=25")
    except Exception as e:
        log(f"SB-ERR {type(e).__name__}: {str(e)[:80]}")
        return []

    st = _status_map()
    out = []
    for s in rows:
        if not all(s.get(k) is not None for k in ("entry", "sl", "tp")):
            continue
        key = _myt_key(s["pair"], s["posted_at"])
        rec = st.get(key) or {}
        status = str(rec.get("status") or "").lower()
        # buang yang sudah selesai atau sudah entry
        if status in ("tp", "sl", "collected", "expired", "cancelled"):
            continue
        if rec.get("entry") is True:
            continue
        out.append(s)
    log(f"calon: {len(out)}/{len(rows)} (selepas tapis status)")
    return out


def _today():
    return datetime.now(MYT).strftime("%Y-%m-%d")


def kill_status(equity_now):
    """Semak sama ada kill switch aktif hari ini.

    Baseline = equity pada pemeriksaan PERTAMA hari itu. Jika equity jatuh
    lebih dari KILL_PCT dari baseline, kill = True sampai esok.
    """
    try:
        d = json.loads(KILL_STATE.read_text())
    except Exception:
        d = {}

    day = _today()
    if d.get("day") != day:
        d = {"day": day, "baseline": equity_now, "killed": False}

    if d.get("baseline") is None or d.get("baseline", 0) <= 0:
        d["baseline"] = equity_now

    base = float(d["baseline"])
    loss_pct = (base - equity_now) / base * 100 if base else 0

    if loss_pct >= KILL_PCT:
        d["killed"] = True
        d["killed_at"] = datetime.now(MYT).isoformat()
        d["loss_pct"] = round(loss_pct, 2)

    KILL_STATE.parent.mkdir(parents=True, exist_ok=True)
    KILL_STATE.write_text(json.dumps(d, indent=1))
    return d, loss_pct


def equity_now():
    """Baca equity akaun dari MT5 (read-only)."""
    import subprocess as _sp
    cmd = ["sudo", "-n", "-u", "mt5", "env", "DISPLAY=:99", f"WINEPREFIX={PREFIX}",
           "/opt/wine-staging/bin/wine", PY, "-c",
           "import MetaTrader5 as m,json;m.initialize();"
           "a=m.account_info();"
           "print(json.dumps({'equity':a.equity if a else 0,'balance':a.balance if a else 0}));"
           "m.shutdown()"]
    r = _sp.run(cmd, capture_output=True, text=True, timeout=120, cwd="/tmp")
    for line in (r.stdout or "").splitlines():
        if line.strip().startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"equity": 0, "balance": 0}


def main():
    log(f"START mode={MODE} lot={LOT} max_pending={MAX_PENDING} allow={ALLOW or 'semua'} kill={KILL_PCT}%")

    # ---------- kill switch check ----------
    acc = equity_now()
    eq = float(acc.get("equity") or 0)
    if eq > 0:
        ks, loss_pct = kill_status(eq)
        log(f"equity={eq:.2f} baseline={ks['baseline']:.2f} "
            f"loss_hari_ini={loss_pct:.2f}% killed={ks.get('killed')}")
        if ks.get("killed"):
            log(f"KILL SWITCH AKTIF — rugi {loss_pct:.2f}% >= {KILL_PCT}%. "
                f"Tiada order baru sehingga esok.")
            return 0
    else:
        log("AMARAN: tidak dapat baca equity — kill switch dilangkau")

    st = load_state()
    seen = st.get("signals", {})

    live = mt5({"action": "state"})
    if not live.get("ok"):
        log(f"MT5-ERR {live.get('error')}")
        return 1
    pending = live.get("orders", [])
    positions = live.get("positions", [])
    log(f"MT5: {len(pending)} pending · {len(positions)} posisi")

    for o in pending:
        m = o.get("magic", 0)
        if m < MAGIC_BASE:
            continue
        sid = str(m - MAGIC_BASE)
        rec = seen.get(sid, {})
        if rec.get("status") in ("closed", "void", "expired"):
            if MODE == "live":
                r = mt5({"action": "cancel", "ticket": o["ticket"]})
                log(f"CANCEL #{sid} ticket={o['ticket']} ok={r.get('ok')}")
            else:
                log(f"PLAN cancel #{sid} ticket={o['ticket']}")

    if len(pending) >= MAX_PENDING:
        log(f"SKIP: pending penuh ({len(pending)}/{MAX_PENDING})")
        return 0

    placed = 0
    for s in active_signals():
        sid = str(s["id"])
        if sid in seen:
            continue
        if len(pending) + placed >= MAX_PENDING:
            log("capai max pending")
            break

        pair = str(s["pair"]).replace("/", "").upper()
        if ALLOW and pair not in ALLOW:
            continue
        side = str(s["side"]).upper()
        entry, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
        magic = MAGIC_BASE + int(s["id"])

        # Idempotency guard: order_send() boleh diterima MT5 tetapi bridge
        # Wine boleh timeout sebelum JSON sampai kepada parent. Dalam keadaan
        # itu state file belum sempat menyimpan sid, jadi retry seterusnya
        # mesti reconcile dengan order/position sebenar dahulu — jangan hantar
        # lot kedua untuk signal yang sama.
        existing_orders = [o for o in pending if int(o.get("magic", 0) or 0) == magic]
        existing_positions = [p for p in positions if int(p.get("magic", 0) or 0) == magic]
        if existing_orders or existing_positions:
            base = {"pair": pair, "side": side, "entry": entry, "sl": sl,
                    "tp": tp, "magic": magic}
            if existing_positions:
                base.update({"status": "filled", "position_ticket": existing_positions[0].get("ticket")})
            else:
                base.update({"status": "pending", "ticket": existing_orders[0].get("ticket"),
                             "type": existing_orders[0].get("type")})
            seen[sid] = base
            log(f"RECONCILE #{sid} existing={'position' if existing_positions else 'pending'} "
                f"count={len(existing_positions) + len(existing_orders)} — no duplicate order")
            continue

        if MODE != "live":
            log(f"PLAN #{sid} {pair} {side} LIMIT entry={entry} sl={sl} tp={tp} lot={LOT}")
            seen[sid] = {"status": "planned", "pair": pair, "side": side,
                         "entry": entry, "sl": sl, "tp": tp, "magic": magic}
            placed += 1
            continue

        r = mt5({"action": "place_limit", "symbol": pair, "side": side,
                 "entry": entry, "sl": sl, "tp": tp, "lot": LOT,
                 "magic": magic, "deviation": DEVIATION,
                 "comment": f"TW#{s['id']}"})
        if r.get("ok"):
            seen[sid] = {"status": "pending", "ticket": r["ticket"],
                         "type": r.get("type"), "pair": pair, "side": side,
                         "entry": entry, "sl": sl, "tp": tp, "magic": magic,
                         "placed_at": datetime.now(MYT).isoformat()}
            log(f"OK #{sid} {pair} {side} {r.get('type')} ticket={r['ticket']} entry={entry}")
            placed += 1
        else:
            log(f"FAIL #{sid} {pair} {side}: {r.get('error') or r.get('comment')} retcode={r.get('retcode')}")

    for o in pending:
        m = o.get("magic", 0)
        if m < MAGIC_BASE:
            continue
        sid = str(m - MAGIC_BASE)
        filled = [p for p in positions if p.get("magic") == m]
        if filled:
            seen.setdefault(sid, {})["status"] = "filled"
            seen[sid]["position_ticket"] = filled[0]["ticket"]
            log(f"FILLED #{sid} — posisi {filled[0]['ticket']} (TIADA order baru)")

    save_state({"signals": seen})
    log(f"done: {placed} baru · {len(seen)} tracked")
    return 0


if __name__ == "__main__":
    import signal, time
    # Continuous loop: check new signals every 5 seconds (instant)
    def sigterm_handler(signum, frame):
        log("SIGTERM — shutting down mt5-pending gracefully")
        sys.exit(0)
    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)
    while True:
        try:
            main()
        except SystemExit:
            pass  # main called sys.exit intentionally; continue loop
        except Exception as ex:
            log(f"FATAL {type(ex).__name__}: {ex}")
        time.sleep(SLEEP_SEC)
