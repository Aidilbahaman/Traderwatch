#!/usr/bin/env python3
"""MT5 bridge (Linux side) — baca data dari MT5 via Python Windows dalam wine.

Dijalankan sebagai user mt5 dengan WINEPREFIX=/home/mt5/.mt5.
Output JSON ke stdout supaya boleh dipanggil dari bot.

Penggunaan:
    python3 mt5_read.py account
    python3 mt5_read.py symbols
    python3 mt5_read.py candles XAUUSD M15 300
    python3 mt5_read.py tick XAUUSD
"""
import subprocess, sys, json, os

PREFIX = "/home/mt5/.mt5"
PY = r"C:\Python311\python.exe"
WORKDIR = "/home/mt5/.mt5/drive_c/mt5work"

# Skrip Python Windows yang dijalankan di dalam wine
WIN_SCRIPT = r'''
import sys, json
try:
    import MetaTrader5 as mt5
except ImportError:
    print(json.dumps({"error": "MetaTrader5 package not installed"}))
    sys.exit(1)

if not mt5.initialize():
    print(json.dumps({"error": "initialize failed", "code": mt5.last_error()}))
    sys.exit(1)

cmd = sys.argv[1] if len(sys.argv) > 1 else "account"

def out(d):
    print(json.dumps(d, default=str))

if cmd == "account":
    a = mt5.account_info()
    if a is None:
        out({"error": "account_info None"})
    else:
        out({"login": a.login, "server": a.server, "balance": a.balance,
             "equity": a.equity, "margin": a.margin, "free_margin": a.margin_free,
             "leverage": a.leverage, "currency": a.currency,
             "company": a.company, "name": a.name, "trade_allowed": a.trade_allowed})

elif cmd == "symbols":
    syms = mt5.symbols_get()
    out({"count": len(syms) if syms else 0,
         "names": [s.name for s in (syms or [])][:200]})

elif cmd == "candles":
    sym = sys.argv[2]; tf = sys.argv[3]; n = int(sys.argv[4])
    TFS = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
           "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
           "D1": mt5.TIMEFRAME_D1,
           "1min": mt5.TIMEFRAME_M1, "5min": mt5.TIMEFRAME_M5, "15min": mt5.TIMEFRAME_M15,
           "30min": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1, "60min": mt5.TIMEFRAME_H1,
           "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}
    if not mt5.symbol_select(sym, True):
        out({"error": f"symbol_select failed for {sym}"}); sys.exit(0)
    rates = mt5.copy_rates_from_pos(sym, TFS.get(tf, mt5.TIMEFRAME_M1), 0, n)
    if rates is None:
        out({"error": "copy_rates None", "code": mt5.last_error()})
    else:
        out({"symbol": sym, "timeframe": tf, "count": len(rates),
             "bars": [{"t": int(r["time"]), "o": float(r["open"]), "h": float(r["high"]),
                       "l": float(r["low"]), "c": float(r["close"]),
                       "v": int(r["tick_volume"])} for r in rates]})

elif cmd == "tick":
    sym = sys.argv[2]
    mt5.symbol_select(sym, True)
    t = mt5.symbol_info_tick(sym)
    if t is None:
        out({"error": "tick None"})
    else:
        out({"symbol": sym, "bid": t.bid, "ask": t.ask, "last": t.last,
             "time": int(t.time), "volume": t.volume})

mt5.shutdown()
'''

SCRIPT_PATH = "/home/mt5/.mt5/drive_c/mt5work/mt5_query.py"

# Cache untuk ensure_script(): elak tulis semula fail yang sama setiap panggilan.
# _ENSURE_TTL membenarkan deploy baru merebak tanpa restart servis.
import time as _time
_SCRIPT_OK = False
_SCRIPT_AT = 0.0
_ENSURE_TTL = 600.0

def ensure_script(force=False):
    """Tulis script ke drive_c supaya wine nampak sebagai C:\\mt5work.

    Dioptimumkan 2026-11-24. Dulu fail ini ditulis semula SETIAP panggilan:
    mkdir + cp + chown = 3 sudo, setiap kali candles()/tick(). Diukur 202
    spawn sudo/minit dan load 11 pada 2 vCPU — fork storm, bukan kerja.

    Sekarang: hash script yang ada disemak dahulu (sudoers benarkan
    `cat /home/mt5/*` tanpa password). Kalau sama, ketiga-tiga sudo dilangkau.
    Hasil cache dipegang per-proses selama _ENSURE_TTL detik supaya deploy
    baru merebak dalam 10 minit tanpa perlu restart servis.
    """
    global _SCRIPT_OK, _SCRIPT_AT
    import hashlib
    now = _time.time()
    if (_SCRIPT_OK and not force
            and (now - _SCRIPT_AT) < _ENSURE_TTL):
        return
    want = hashlib.sha256(WIN_SCRIPT.encode()).hexdigest()
    try:
        cur = subprocess.run(["sudo", "-n", "cat", SCRIPT_PATH],
                             capture_output=True, text=True, timeout=20)
        if (cur.returncode == 0
                and hashlib.sha256((cur.stdout or "").encode()).hexdigest() == want):
            _SCRIPT_OK, _SCRIPT_AT = True, now
            return
    except (OSError, subprocess.SubprocessError):
        pass
    # script tiada atau berbeza — tulis semula (3 sudo, jarang berlaku)
    import tempfile, os as _os
    subprocess.run(["sudo", "-n", "-u", "mt5", "mkdir", "-p",
                    _os.path.dirname(SCRIPT_PATH)], capture_output=True)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(WIN_SCRIPT)
        tmp = f.name
    try:
        subprocess.run(["sudo", "-n", "cp", tmp, SCRIPT_PATH],
                       capture_output=True, check=False)
        subprocess.run(["sudo", "-n", "chown", "mt5:mt5", SCRIPT_PATH],
                       capture_output=True, check=False)
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
    _SCRIPT_OK, _SCRIPT_AT = True, now


def run(win_args, timeout=180):
    ensure_script()
    cmd = ["sudo", "-n", "-u", "mt5", "env", "DISPLAY=:99", f"WINEPREFIX={PREFIX}",
           "/opt/wine-staging/bin/wine", PY, r"C:\mt5work\mt5_query.py"] + win_args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       cwd="/tmp")
    # buang fixme noise
    lines = [l for l in (r.stdout or "").splitlines()
             if l.strip() and not l.startswith("fixme") and "Warning" not in l]
    return "\n".join(lines), r.stderr.strip()


if __name__ == "__main__":
    args = sys.argv[1:] or ["account"]
    out, err = run(args)
    if out:
        print(out)
    elif err:
        print(json.dumps({"error": "wine stderr", "detail": err[:400]}))
    else:
        print(json.dumps({"error": "no output"}))
