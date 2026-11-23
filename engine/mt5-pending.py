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
import math
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent
STATE = REPO / "state" / "mt5-orders.json"
MYT = timezone(timedelta(hours=8))

MODE = os.environ.get("MT5_MODE", "live")          # plan | live
LOT = float(os.environ.get("MT5_LOT", "1.00"))
MAGIC_BASE = int(os.environ.get("MT5_MAGIC_BASE", "20261000"))
DEVIATION = int(os.environ.get("MT5_DEVIATION", "20"))
# Ubah max_pending jadi lebih banyak (cth: 10) supaya banyak pending order boleh masuk serentak
MAX_PENDING = int(os.environ.get("MT5_MAX_PENDING", "10"))
# Loop interval (saat). Setiap loop panggil wine bridge (~2s per call), jadi
# nilai kecil = CPU tinggi berterusan. Signal baru datang dari cron engine
# setiap 5 minit, jadi 15s masih "instant" untuk client (max delay 15s) tapi
# 7x lebih ringan pada CPU. Owner 2026-11-22: optimumkan CPU untuk client.
SLEEP_SEC = int(os.environ.get("MT5_SLEEP_SEC", "15"))
# Senarai symbol dibenarkan (kosong = semua). Guna untuk hadkan ke BTCUSD
# semasa ujian luar waktu forex.
ALLOW = [x.strip().upper() for x in os.environ.get("MT5_ALLOW", "").split(",") if x.strip()]

# ---------- auto-entry lock ----------
# Owner 2026-11-23: auto-trade hanya pada apps. Modul ini TIDAK boleh buka
# posisi baru dari signal cron — kalau tiada, 8 BUY BTCUSD berturut masuk
# sendiri dalam 7 jam tanpa sesiapa tekan apa-apa.
# AUTO_ENTRY=0 -> semua order baru disekat. PENGURUSAN posisi sedia ada
# (break-even SL, partial close di TP1, reconcile, cancel) tetap jalan supaya
# posisi yang sudah terbuka tak ditinggalkan tanpa perlindungan.
# AUTO_ENTRY=1 -> tingkah laku lama (hantar order sendiri).
AUTO_ENTRY = os.environ.get("MT5_AUTO_ENTRY", "0") == "1"

# ---------- kill switch ----------
# Berhenti hantar order baru bila rugi harian capai had. Posisi sedia ada
# TIDAK ditutup (biar TP/SL uruskan) — hanya tiada order baru.
KILL_PCT = float(os.environ.get("MT5_KILL_PCT", "3.0"))     # % equity sehari
KILL_STATE = REPO / "state" / "mt5-kill.json"

# ---------- lot sizing ikut risiko ----------
# RISK_PCT > 0 -> lot dikira dari equity live + jarak entry->SL.
# RISK_PCT = 0 -> guna LOT tetap (lama).
RISK_PCT = float(os.environ.get("MT5_RISK_PCT", "1.0"))      # % per trade
LOT_MIN_ALLOW = os.environ.get("MT5_LOT_MIN_ALLOW", "1") == "1"

# ---------- break-even protection (owner 2026-11-21) ----------
# Bila harga hit 1R (TP1), anjak SL ke entry supaya profit dilindungi dari
# patah balik jadi rugi penuh (selaras Paper League). MT5_BE_PARTIAL_PCT:
# peratus partial close di TP1 (0 = off, 50 = tutup 50% baki BE).
BE_ENABLED = os.environ.get("MT5_BREAK_EVEN", "1") == "1"
BE_PARTIAL_PCT = float(os.environ.get("MT5_BE_PARTIAL_PCT", "0"))

# ---------- compounding ----------
# Asas saiz lot naik/turun ikut modal. "equity" (DEFAULT, owner 2026-11-20)
# = lot ikut equity SEMASA termasuk floating P/L — lot membesar bila equity
# naik, mengecil bila equity turun. "balance" = untung REALIZED sahaja
# (compounding konservatif: lot naik hanya selepas profit banked).
# Nota: equity-based bermakna risiko terkumpul bila beberapa posisi searah
# masih terbuka; kill switch (realized balance) kekal sebagai pendinding.
COMPOUND_BASE = os.environ.get("MT5_COMPOUND_BASE", "equity").lower()
COMPOUND_FILE = REPO / "state" / "ai-compound.json"

# ---------- milestone compounding (notifikasi owner sahaja) ----------
# Dihantar sekali bila modal asas cecah setiap tahap. Lepas cecah, counter
# lot naik ~20% berbanding €500.
COMPOUND_MILESTONES = (600.0, 750.0, 1000.0)

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
    acc = mt5.account_info()
    out({"ok": True,
         "balance": acc.balance if acc else 0,
         "equity": acc.equity if acc else 0,
         "free_margin": getattr(acc, "margin_free", 0) or getattr(acc, "free_margin", 0) or 0,
         "margin_level": getattr(acc, "margin_level", 0) or 0,
         "orders": [{"ticket": o.ticket, "symbol": o.symbol, "type": o.type,
                     "volume": o.volume_current, "price_open": o.price_open,
                     "sl": o.sl, "tp": o.tp, "magic": o.magic,
                     "comment": o.comment} for o in orders],
         "positions": [{"ticket": p.ticket, "symbol": p.symbol, "type": p.type,
                        "volume": p.volume, "price_open": p.price_open,
                        "sl": p.sl, "tp": p.tp, "magic": p.magic,
                        "comment": p.comment, "profit": p.profit} for p in pos]})

elif act == "symbol":
    sym = req["symbol"]
    if not mt5.symbol_select(sym, True):
        out({"ok": False, "error": "symbol_select " + sym}); sys.exit(0)
    info = mt5.symbol_info(sym)
    if info is None:
        out({"ok": False, "error": "no symbol_info " + sym}); sys.exit(0)
    ask = bid = 0.0
    try:
        _t = mt5.symbol_info_tick(sym)
        if _t is not None:
            ask, bid = float(_t.ask), float(_t.bid)
    except Exception:
        pass
    out({"ok": True, "symbol": sym, "point": info.point, "digits": info.digits,
         "tick_size": info.trade_tick_size, "tick_value": info.trade_tick_value,
         "contract": info.trade_contract_size, "vol_min": info.volume_min,
         "vol_max": info.volume_max, "vol_step": info.volume_step,
         "stops_level": info.trade_stops_level,
         "spread_pt": getattr(info, "spread", 0),
         "spread_price": max(0.0, ask - bid),
         "bid": bid, "ask": ask})

elif act == "candles":
    sym = req["symbol"]
    count = int(req.get("count", 300))
    timeframe = getattr(mt5, "TIMEFRAME_M1", 1)
    rates = mt5.copy_rates_from_pos(sym, timeframe, 0, count)
    if rates is None or len(rates) < 50:
        out({"ok": False, "error": "insufficient candles", "count": len(rates) if rates is not None else 0}); sys.exit(0)
    out({"ok": True, "bars": [{"t": int(r["time"]), "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]), "v": int(r["tick_volume"])} for r in rates]})

elif act == "market":
    sym = req["symbol"]
    side = req["side"]
    lot = float(req["lot"])
    sl = float(req.get("sl", 0) or 0)
    tp = float(req.get("tp", 0) or 0)
    magic = int(req.get("magic", 0))
    comment = str(req.get("comment", "TW"))[:26]
    if not mt5.symbol_select(sym, True):
        out({"ok": False, "error": "symbol_select " + sym}); sys.exit(0)
    tick = mt5.symbol_info_tick(sym)
    info = mt5.symbol_info(sym)
    if tick is None or info is None:
        out({"ok": False, "error": "no tick/info"}); sys.exit(0)
    price = float(tick.ask if side == "BUY" else tick.bid)
    otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    if side == "BUY":
        if (sl == 0 and tp == 0) or sl < price < tp:
            pass
        else:
            out({"ok": False, "error": "SL/TP invalid BUY", "price": price}); sys.exit(0)
    if side == "SELL":
        if (sl == 0 and tp == 0) or (tp < price < sl):
            pass
        else:
            out({"ok": False, "error": "SL/TP invalid SELL", "price": price}); sys.exit(0)
    step = float(info.volume_step or 0.01)
    vmin = float(info.volume_min or step)
    vmax = float(info.volume_max or lot)
    lot = max(vmin, min(vmax, (int(lot / step) * step)))
    request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot,
               "type": otype, "price": price, "sl": sl, "tp": tp,
               "deviation": int(req.get("deviation", 20)), "magic": magic,
               "comment": comment, "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC}
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": getattr(res, "retcode", None),
             "comment": getattr(res, "comment", ""), "price": price, "lot": lot})
    else:
        out({"ok": True, "ticket": res.order, "deal": res.deal,
             "price": res.price, "volume": res.volume, "retcode": res.retcode})

elif act == "tick":
    sym = req["symbol"]
    if not mt5.symbol_select(sym, True):
        out({"ok": False, "error": "symbol_select " + sym}); sys.exit(0)
    t = mt5.symbol_info_tick(sym)
    if t is None:
        out({"ok": False, "error": "no tick"}); sys.exit(0)
    out({"ok": True, "bid": t.bid, "ask": t.ask, "time": t.time})

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
        if not (sl < entry) or (tp > 0 and not (entry < tp)):
            out({"ok": False, "error": "SL/TP invalid BUY"}); sys.exit(0)
    else:
        if entry > tick.bid:
            otype, tname = mt5.ORDER_TYPE_SELL_LIMIT, "SELL_LIMIT"
        else:
            otype, tname = mt5.ORDER_TYPE_SELL_STOP, "SELL_STOP"
        if not (tp < entry < sl) if tp > 0 else not (entry < sl):
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

elif act == "modify_position":
    ticket = int(req["ticket"])
    sl = float(req.get("sl", 0) or 0)
    tp = float(req.get("tp", 0) or 0)
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        out({"ok": False, "error": "position not found"}); sys.exit(0)
    p = pos[0]
    res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
                          "position": ticket, "sl": sl, "tp": tp,
                          "magic": p.magic})
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": getattr(res, "retcode", None),
             "comment": getattr(res, "comment", "")})
    else:
        out({"ok": True, "ticket": ticket, "sl": sl, "tp": tp})

elif act == "cancel":
    ticket = int(req["ticket"])
    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        out({"ok": False, "retcode": getattr(res, "retcode", None),
             "comment": getattr(res, "comment", "")})
    else:
        out({"ok": True, "ticket": ticket})

elif act == "close_position":
    ticket = int(req["ticket"])
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        out({"ok": False, "error": "position not found (mungkin sudah tutup)"})
    else:
        p = pos[0]
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        filling = mt5.ORDER_FILLING_IOC
        close_vol = float(req.get("volume", 0) or 0)
        if close_vol <= 0 or close_vol > p.volume:
            close_vol = p.volume          # full close jika volume tiada/lebih
        req_close = {"action": mt5.TRADE_ACTION_DEAL, "position": ticket,
            "symbol": p.symbol, "volume": close_vol, "type": close_type,
            "price": price, "deviation": 20, "magic": p.magic,
            "comment": "TW-CLOSE", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling}
        res = mt5.order_send(req_close)
        if res is not None and res.retcode == 10030:
            req_close["type_filling"] = mt5.ORDER_FILLING_RETURN
            res = mt5.order_send(req_close)
        if res is not None and res.retcode == 10030:
            req_close["type_filling"] = mt5.ORDER_FILLING_FOK
            res = mt5.order_send(req_close)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            out({"ok": False, "retcode": getattr(res, "retcode", None),
                 "comment": getattr(res, "comment", "")})
        else:
            out({"ok": True, "ticket": ticket, "deal": res.deal,
                 "profit": getattr(res, "profit", None)})

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
    """Signal owner-only yang BELUM entry (verified + private registry).

    MT5 private engine hanya mengambil signal yang didaftarkan dalam
    state/private-signals.json. Ini mengelakkan signal member masuk broker.

    Hanya signal yang belum kena entry layak jadi pending limit order.
    Signal yang sudah entry/tp/sl/expired TIDAK boleh di-order semula.
    """
    try:
        from engine.private_signals import is_private
    except Exception:
        from private_signals import is_private

    try:
        # Hanya signal verified=true (diluluskan owner) layak jadi pending order.
        # Draft verified=false (cadangan AI menunggu keputusan) MESTI diabaikan.
        rows = sb_get("signals?select=id,pair,side,timeframe,entry,sl,tp,posted_at,verified,exec_mode"
                      "&verified=is.true&order=posted_at.desc&limit=25")
    except Exception as e:
        log(f"SB-ERR {type(e).__name__}: {str(e)[:80]}")
        return []

    st = _status_map()
    out = []
    for s in rows:
        # Manual signals (NOT in private registry) continue as before:
        # they are a normal operation, executed with the fixed LOT.
        # Private AI signals (in registry) also pass — they use risk lot.
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


_SPEC_CACHE = {}


def symbol_spec(pair):
    """Cache spec simbol (tick value, volume step) dari broker."""
    if pair in _SPEC_CACHE:
        return _SPEC_CACHE[pair]
    r = mt5({"action": "symbol", "symbol": pair})
    _SPEC_CACHE[pair] = r if r.get("ok") else None
    return _SPEC_CACHE[pair]


def size_lot(pair, entry, sl, equity):
    """Kira lot dari risiko % equity pada jarak entry->SL.

    trade_tick_value dari MT5 sudah dalam MATA WANG AKAUN (akaun ini EUR),
    jadi tiada conversion manual diperlukan. Bulat ke BAWAH ke volume_step
    supaya risiko sebenar tidak melebihi had.

    Return (lot, nota). lot None bermakna tidak boleh dikira.
    """
    spec = symbol_spec(pair)
    if not spec:
        return None, "no-spec"
    tick_size = float(spec.get("tick_size") or 0) or float(spec.get("point") or 0)
    tick_value = float(spec.get("tick_value") or 0)
    if tick_size <= 0 or tick_value <= 0:
        return None, "bad-spec"
    dist = abs(float(entry) - float(sl))
    if dist <= 0:
        return None, "zero-sl"
    # Guard spread: SL mesti > 3x spread live. Kalau tidak, spread sahaja
    # boleh makan edge (RoboForex spread besar). Skip, bukan kecilkan lot.
    sp = float(spec.get("spread_price") or 0) or float(spec.get("spread_pt") or 0) * float(spec.get("point") or 0)
    if sp > 0 and dist < 3 * sp:
        return None, f"sl<{3*sp:g} (3x spread {sp:g})"
    loss_per_lot = (dist / tick_size) * tick_value
    if loss_per_lot <= 0:
        return None, "bad-loss"
    risk_money = float(equity) * RISK_PCT / 100.0
    raw = risk_money / loss_per_lot
    step = float(spec.get("vol_step") or 0.01) or 0.01
    vmin = float(spec.get("vol_min") or 0.01) or 0.01
    vmax = float(spec.get("vol_max") or 100.0) or 100.0
    lot = math.floor(raw / step) * step
    lot = round(lot, 8)
    if lot < vmin:
        # lot dikira di bawah minimum broker: samada langkau (default) atau
        # clamp ke vmin bila owner benarkan risiko lebih.
        if not LOT_MIN_ALLOW:
            return None, (f"lot<min raw={raw:.4f} min={vmin} "
                          f"risk_needed={loss_per_lot * vmin:.2f}")
        lot = vmin
    if lot > vmax:
        lot = vmax
    return lot, (f"eq={float(equity):.2f} risk={RISK_PCT}% money={risk_money:.2f} "
                 f"sl_dist={dist:g} loss/lot={loss_per_lot:.2f} lot={lot:g}")


def sizing_base(acc):
    """Modal asas untuk kira lot.

    equity  = equity semasa termasuk floating P/L (default, owner 2026-11-20:
              lot menaik ikut equity semasa).
    balance = untung realized sahaja (compounding konservatif).
    """
    bal = float(acc.get("balance") or 0)
    eq = float(acc.get("equity") or 0)
    if COMPOUND_BASE == "equity":
        return eq or bal
    return bal or eq


def _notify_owner(text):
    """Hantar mesej ke owner sahaja. Gagal senyap — jangan ganggu loop MT5."""
    try:
        from pathlib import Path as _P
        sec = {}
        for _ln in (_P.home() / ".secrets" / "telegram.env").read_text().splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                _k, _v = _ln.split("=", 1)
                sec[_k.strip()] = _v.strip().strip('"').strip("'")
        # Prefer token bot admin (@CCSTWbot) yang sama dengan AI signal.
        # TELEGRAM_ADMIN_BOT_TOKEN dalam telegram.env Cuma 28 aksara (bukan
        # token sah) — jangan guna ia dahulu.
        tok = ""
        try:
            _raw = _P("/home/ubuntu/tw-bot/.env").read_text()
            for _ln in _raw.splitlines():
                if _ln.strip().startswith("BOT_TOKEN="):
                    tok = _ln.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            tok = ""
        if not tok:
            for _k in ("TELEGRAM_SIGNALS_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
                if len(sec.get(_k) or "") >= 40:
                    tok = sec[_k]
                    break
        admin = sec.get("TELEGRAM_ADMIN_CHAT_ID", "")
        if not tok or not admin:
            return
        import urllib.parse as _up, urllib.request as _ur
        _ur.urlopen(_ur.Request(
            "https://api.telegram.org/bot" + tok + "/sendMessage",
            data=_up.urlencode({"chat_id": admin, "text": text,
                                "parse_mode": "HTML"}).encode()), timeout=20)
    except Exception as ex:
        log(f"MILESTONE-NOTIFY-FAIL {type(ex).__name__}")


def _milestone_lot(base, ref_risk_money):
    """Ref lot EURUSD SL 20pip (0.002) pada modal base — ilustrasi saiz baru."""
    try:
        spec = symbol_spec("EURUSD")
        step = float(spec.get("vol_step") or 0.01) or 0.01
        tick_size = float(spec.get("tick_size") or 1e-5)
        tick_value = float(spec.get("tick_value") or 0)
        if tick_size <= 0 or tick_value <= 0:
            return None
        raw = ref_risk_money / ((0.002 / tick_size) * tick_value)
        import math as _m
        return max(0.01, round(_m.floor(raw / step) * step, 8))
    except Exception:
        return None


def compound_track(base):
    """Rekod modal asas -> {start, base, peak, growth_pct, trades}. 
    
    Ditulis setiap loop; dipakai untuk log kemajuan compounding dan untuk
    kira berapa kali lot sudah naik berbanding modal mula.
    """
    try:
        d = json.loads(COMPOUND_FILE.read_text())
    except Exception:
        d = {}
    if not d.get("start") or float(d.get("start") or 0) <= 0:
        d = {"start": round(base, 2), "started_at": datetime.now(MYT).isoformat(timespec="seconds")}
    d["base"] = round(base, 2)
    d["peak"] = round(max(float(d.get("peak") or 0), base), 2)
    start = float(d["start"])
    d["growth_pct"] = round((base - start) / start * 100, 2) if start else 0.0
    d["multiplier"] = round(base / start, 4) if start else 1.0
    # ---------- milestone owner-only ----------
    # Hantar sekali bila modal asas melepasi setiap tahap. Simpan dalam
    # "milestones" supaya restart tidak menghantar semula.
    try:
        seen = set(d.get("milestones") or [])
        for m in COMPOUND_MILESTONES:
            if base >= m and str(m) not in {str(x) for x in seen}:
                rm = base * RISK_PCT / 100.0
                nl = _milestone_lot(base, rm)
                lot_txt = f"Contoh lot EURUSD SL 20pip: <b>{nl:g}</b>" if nl else ""
                _notify_owner(
                    f"🎯 <b>Compounding milestone: €{m:,.0f} tercapai</b>\n"
                    f"Modal AI kini <b>€{base:,.2f}</b> "
                    f"(mula €{start:,.2f}, +{d['growth_pct']:.1f}%, x{d['multiplier']:.2f}).\n"
                    f"Risiko {RISK_PCT:g}% = <b>€{rm:,.2f}</b> per trade. {lot_txt}\n"
                    f"Lot akan terus naik otomatik selagi profit terkumpul.")
                log(f"MILESTONE {m:,.0f} tercapai — notifikasi owner dihantar")
                seen.add(m)
        d["milestones"] = sorted(seen)
    except Exception as ex:
        log(f"MILESTONE-ERR {type(ex).__name__}")
    d["updated"] = datetime.now(MYT).isoformat(timespec="seconds")
    try:
        COMPOUND_FILE.parent.mkdir(parents=True, exist_ok=True)
        COMPOUND_FILE.write_text(json.dumps(d, indent=1, sort_keys=True))
    except Exception:
        pass
    return d


def _today():
    return datetime.now(MYT).strftime("%Y-%m-%d")


def kill_status(equity_now):
    """Semak sama ada kill switch aktif hari ini.

    Baseline = equity pada pemeriksaan PERTAMA hari itu. Jika equity jatuh
    lebih dari KILL_PCT dari baseline, kill = True sampai esok.

    KILL_PCT <= 0 = kill switch DIMATIKAN (owner 2026-11-20): tiada sekat
    kerugian harian. Perlindungan lain kekal: risiko 1% per trade, had
    pending, guard SL > 3x spread.
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

    if KILL_PCT <= 0:
        d["killed"] = False
        d["disabled"] = True
    elif loss_pct >= KILL_PCT:
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
    log(f"START mode={MODE} lot={LOT if RISK_PCT<=0 else 'RISK'+str(RISK_PCT)+'%'} "
        f"max_pending={MAX_PENDING} allow={ALLOW or 'semua'} "
        f"kill={'OFF' if KILL_PCT <= 0 else str(KILL_PCT) + '%'} "
        f"auto_entry={'ON' if AUTO_ENTRY else 'OFF (apps-only)'}")

    # ---------- kill switch check ----------
    # Guna BALANCE (realized), bukan equity (floating). Equity swing liar bila
    # banyak posisi terbuka -> baseline puncak + retrace biasa = false trigger.
    # Balance hanya turun bila rugi direalisasi -> kill switch stabil & masih
    # protect dari kerugian realized > KILL_PCT% sehari.
    acc = equity_now()
    bal = float(acc.get("balance") or 0)
    eq = float(acc.get("equity") or 0)
    if bal > 0:
        ks, loss_pct = kill_status(bal)
        log(f"balance={bal:.2f} equity={eq:.2f} baseline={ks['baseline']:.2f} "
            f"loss_hari_ini={loss_pct:.2f}% killed={ks.get('killed')}")
        if ks.get("killed"):
            log(f"KILL SWITCH AKTIF — rugi realized {loss_pct:.2f}% >= {KILL_PCT}%. "
                f"Tiada order baru sehingga esok.")
            return 0
    else:
        log("AMARAN: tidak dapat baca balance — kill switch dilangkau")

    # ---------- compounding ----------
    base = sizing_base(acc)
    comp = compound_track(base) if base > 0 else {}
    if comp:
        log(f"COMPOUND base={COMPOUND_BASE} modal={base:.2f} "
            f"mula={comp.get('start')} puncak={comp.get('peak')} "
            f"pertumbuhan={comp.get('growth_pct')}% x{comp.get('multiplier')}")
    if RISK_PCT > 0 and base <= 0:
        log("AMARAN: modal asas 0 — lot risiko dilangkau (guna LOT tetap)")

    st = load_state()
    seen = st.get("signals", {})
    try:
        from engine.private_signals import is_private
    except Exception:
        from private_signals import is_private

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
        # Auto-entry dimatikan (owner: auto-trade hanya pada apps). Rekod signal
        # sebagai "held" supaya tidak diulang setiap kitaran, TANPA hantar apa-apa
        # ke MT5. Posisi sedia ada masih diurus di bawah.
        if not AUTO_ENTRY:
            seen[sid] = {"status": "held", "pair": str(s.get("pair")),
                         "side": str(s.get("side")),
                         "reason": "auto-entry off (apps-only)"}
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

        lot_use, lot_note = LOT, "fixed-manual"
        if RISK_PCT > 0 and base > 0:
            calc, note = size_lot(pair, entry, sl, base)
            if calc is None:
                log(f"LOT-SKIP #{sid} {pair} {side}: {note} — tiada order "
                    f"(risiko akan melebihi {RISK_PCT}% atau spec tiada)")
                continue
            lot_use, lot_note = calc, "risk-" + note

        # Instant entry (signal LLM): MARKET order serta-merta pada harga live.
        # Jika harga sudah lepas SL/TP setup, host tolak -> void (jangan kejar).
        if str(s.get("exec_mode") or "pending") == "market":
            if MODE != "live":
                log(f"PLAN #{sid} {pair} {side} MARKET sl={sl} tp={tp} lot={lot_use} [{lot_note}]")
                seen[sid] = {"status": "planned", "pair": pair, "side": side,
                             "entry": entry, "sl": sl, "tp": tp, "magic": magic}
                placed += 1
                continue
            r = mt5({"action": "market", "symbol": pair, "side": side,
                     "sl": sl, "tp": tp, "lot": lot_use,
                     "magic": magic, "deviation": DEVIATION,
                     "comment": f"TW#{s['id']}"})
            if r.get("ok"):
                seen[sid] = {"status": "filled", "position_ticket": r.get("ticket"),
                             "pair": pair, "side": side, "entry": r.get("price"),
                             "sl": sl, "tp": tp, "magic": magic, "lot": lot_use,
                             "lot_note": lot_note,
                             "placed_at": datetime.now(MYT).isoformat()}
                log(f"OK #{sid} {pair} {side} MARKET fill={r.get('price')} "
                    f"ticket={r.get('ticket')} lot={lot_use}")
                placed += 1
            else:
                reason = str(r.get("error") or r.get("comment") or r.get("retcode"))[:120]
                seen[sid] = {"status": "void", "reason": reason}
                log(f"VOID #{sid} {pair} {side} MARKET: {reason} — setup luput, tidak dikejar")
            continue

        if MODE != "live":
            log(f"PLAN #{sid} {pair} {side} LIMIT entry={entry} sl={sl} tp={tp} "
                f"lot={lot_use} [{lot_note}]")
            seen[sid] = {"status": "planned", "pair": pair, "side": side,
                         "entry": entry, "sl": sl, "tp": tp, "magic": magic}
            placed += 1
            continue

        r = mt5({"action": "place_limit", "symbol": pair, "side": side,
                 "entry": entry, "sl": sl, "tp": tp, "lot": lot_use,
                 "magic": magic, "deviation": DEVIATION,
                 "comment": f"TW#{s['id']}"})
        if r.get("ok"):
            seen[sid] = {"status": "pending", "ticket": r["ticket"],
                         "type": r.get("type"), "pair": pair, "side": side,
                         "entry": entry, "sl": sl, "tp": tp, "magic": magic,
                         "lot": lot_use, "lot_note": lot_note,
                         "placed_at": datetime.now(MYT).isoformat()}
            log(f"OK #{sid} {pair} {side} {r.get('type')} ticket={r['ticket']} "
                f"entry={entry} lot={lot_use}")
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

    # ---- Break-even protection: SL -> entry selepas harga hit 1R (TP1) ----
    # Lindungi profit dari patah balik jadi rugi penuh (selaras Paper League).
    if BE_ENABLED:
        for p in positions:
            m = p.get("magic", 0)
            if m < MAGIC_BASE:
                continue
            sid = str(m - MAGIC_BASE)
            rec = seen.get(sid) or {}
            if rec.get("be_done") and (rec.get("partial_done") or BE_PARTIAL_PCT <= 0):
                continue                      # sudah diproses sepenuhnya
            entry = float(rec.get("entry") or p.get("price_open") or 0)
            orig_sl = float(rec.get("sl") or p.get("sl") or 0)
            if entry <= 0 or orig_sl <= 0:
                continue
            risk = abs(entry - orig_sl)
            if risk <= 0:
                continue
            is_buy = p.get("type") == 0
            be_level = entry + risk if is_buy else entry - risk
            tk = mt5({"action": "tick", "symbol": p["symbol"]})
            if not tk.get("ok"):
                continue
            px = float(tk.get("bid") if is_buy else tk.get("ask") or 0)
            reached = (px >= be_level) if is_buy else (px <= be_level)
            if not reached:
                continue
            cur_sl = float(p.get("sl") or 0)
            if not rec.get("be_done") and abs(cur_sl - entry) > 1e-9:
                r = mt5({"action": "modify_position", "ticket": p["ticket"],
                         "sl": entry, "tp": float(p.get("tp") or 0)})
                if r.get("ok"):
                    rec["be_done"] = True
                    rec["be_at"] = datetime.now(MYT).isoformat()
                    seen[sid] = rec
                    log(f"BE #{sid} {p['symbol']} SL->entry {entry} "
                        f"(1R {be_level:.2f} dicapai, profit dilindungi)")
                else:
                    log(f"BE-FAIL #{sid} {p['symbol']}: {r.get('error') or r.get('comment')} retcode={r.get('retcode')}")
            if BE_PARTIAL_PCT > 0 and not rec.get("partial_done"):
                vol = round(float(p.get("volume", 0)) * BE_PARTIAL_PCT / 100.0, 2)
                if vol > 0:
                    rc = mt5({"action": "close_position", "ticket": p["ticket"], "volume": vol})
                    if rc.get("ok"):
                        rec["partial_done"] = True
                        seen[sid] = rec
                        log(f"BE-PARTIAL #{sid} {p['symbol']} tutup {vol} lot ({BE_PARTIAL_PCT:g}%) di TP1")
                    else:
                        log(f"BE-PARTIAL-FAIL #{sid}: {rc.get('error') or rc.get('comment')}")

    save_state({"signals": seen})
    log(f"done: {placed} baru · {len(seen)} tracked")
    return 0


if __name__ == "__main__":
    import signal, time

    # Graceful shutdown flag — systemd sends SIGTERM on stop/restart.
    _stop = {"v": False}

    def sigterm_handler(signum, frame):
        log("SIGTERM — shutting down mt5-pending gracefully")
        _stop["v"] = True

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)

    # Continuous loop: check new signals every SLEEP_SEC seconds (instant).
    while not _stop["v"]:
        try:
            main()
        except SystemExit:
            pass  # main() may call sys.exit() for benign early returns
        except Exception as ex:
            log(f"FATAL {type(ex).__name__}: {ex}")
        # Sleep in short slices so SIGTERM is honoured promptly.
        for _ in range(SLEEP_SEC * 2):
            if _stop["v"]:
                break
            time.sleep(0.5)
    log("STOPPED")
