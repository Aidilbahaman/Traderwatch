#!/usr/bin/env python3
"""
Swissquote live-quote collector → M15 bars in SQLite.

Architecture:
  sq-collector.py  (daemon, poll setiap 5s) → sq-bars.db
  candles_swissquote(pair, gran, count)       ← bot_v2.py & signal-engine-ai.py

Poll cadence: 5 saat. Setiap poll update bar semasa (O/H/L/C).
Sesi: 08:00-01:00 MYT (pair forex) + 24j (XAU/USD, XAG/USD).
Baki bar yang belum lengkap (<5 poll) disimpan sebagai "draft".

Kos: 0. Had: tiada. Key: tiada.
"""
import json, os, sys, time, sqlite3, threading, pathlib, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE     = pathlib.Path(__file__).resolve().parent
DB_PATH = HERE.parent / "state" / "sq-bars.db"
LOCK    = pathlib.Path("/tmp/sq-collector.lock")
POLL    = 5          # saat antara polls
TZ_MYT  = timezone(timedelta(hours=8))
UA      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0 Safari/537.36"

# (pair: Swissquote symbol)
SQ_PAIRS = {
    "XAUUSD": "XAU/USD", "XAGUSD": "XAG/USD",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
}
# (pair: Coinbase product) — BTC/USD tidak tersedia di Swissquote.
CB_PAIRS = {
    "BTCUSD": "BTC-USD",
}
PAIR_DEC = {"XAUUSD": 2, "XAGUSD": 3, "USDJPY": 3, "BTCUSD": 2}
DEC      = 5  # default decimal places

GRANS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def _db():
    return sqlite3.connect(str(DB_PATH), timeout=10)


def init_db():
    db = _db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS bars (
            pair   TEXT NOT NULL,
            gran   TEXT NOT NULL,
            ts     TEXT NOT NULL,   -- ISO8601 UTC open time
            o      REAL NOT NULL,
            h      REAL NOT NULL,
            l      REAL NOT NULL,
            c      REAL NOT NULL,
            polls  INTEGER DEFAULT 1,
            PRIMARY KEY (pair, gran, ts)
        );
        CREATE INDEX IF NOT EXISTS idx_bar_lookup ON bars(pair, gran, ts DESC);
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY, val TEXT
        );
    """)
    db.commit()
    return db


def bar_ts(ts, gran_min):
    """UTC timestamp of open for the M-n bar containing `ts`."""
    d  = datetime.fromtimestamp(ts, tz=timezone.utc)
    mn = (d.minute // gran_min) * gran_min
    return datetime(d.year, d.month, d.day, d.hour, mn, 0, tzinfo=timezone.utc)


def poll_swissquote(pair):
    """Return (mid, spread) or raise."""
    sq  = SQ_PAIRS.get(pair, pair)
    url = f"https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{sq}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    # Cari harga dari server dengan spread paling ketat (elite > prime > premium > standard)
    best_bid, best_ask, best_spread = None, None, float("inf")
    for entry in data:
        for price in entry.get("spreadProfilePrices", []):
            s = float(price.get("bidSpread", 99))
            if s < best_spread:
                best_spread = s
                best_bid    = float(price["bid"])
                best_ask    = float(price["ask"])
    if best_bid is None:
        raise RuntimeError(f"tiada harga untuk {pair}")
    return (best_bid + best_ask) / 2, best_ask - best_bid


def update_bar(db, pair, gran_min, open_ts, mid):
    ts_str  = open_ts.strftime("%Y-%m-%dT%H:%M:%S")
    dec     = PAIR_DEC.get(pair, DEC)
    rounded = round(mid, dec)
    db.execute("""
        INSERT INTO bars (pair, gran, ts, o, h, l, c, polls)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(pair, gran, ts) DO UPDATE SET
            h    = MAX(h,    excluded.h),
            l    = MIN(l,    excluded.l),
            c    = excluded.c,
            polls = polls + 1
    """, (pair, f"M{gran_min}", ts_str, rounded, rounded, rounded, rounded))


def poll_coinbase(pair):
    """Return (mid, spread) dari Coinbase ticker. Raise jika gagal."""
    product = CB_PAIRS.get(pair, pair)
    url = f"https://api.exchange.coinbase.com/products/{product}/ticker"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"coinbase HTTP {ex.code} untuk {pair}") from ex
    try:
        bid = float(data["bid"]); ask = float(data["ask"])
    except (KeyError, TypeError, ValueError) as ex:
        raise RuntimeError(f"coinbase respons tak lengkap untuk {pair}") from ex
    return (bid + ask) / 2, ask - bid


def backfill_coinbase(pair, gran_min=15):
    """Tarik 300 bar M15 dari Coinbase candles, insert terus ke DB.

    Kembali (n_bars, oldest_ts, newest_ts). Raise jika gagal.
    """
    product = CB_PAIRS.get(pair, pair)
    url = (f"https://api.exchange.coinbase.com/products/{product}/candles"
           f"?granularity=900")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read())
    if not rows or len(rows) < 10:
        raise RuntimeError(f"coinbase candles kosong untuk {pair}")
    # API pulang [t,low,high,open,close,vol] paling baru dulu.
    dec = PAIR_DEC.get(pair, DEC)
    db = _db()
    n = 0
    for t, lo, hi, o, c, _vol in sorted(rows, key=lambda x: x[0]):
        bts = bar_ts(t, gran_min)
        ts_str = bts.strftime("%Y-%m-%dT%H:%M:%S")
        db.execute("""
            INSERT INTO bars (pair, gran, ts, o, h, l, c, polls)
            VALUES (?, ?, ?, ?, ?, ?, ?, 300)
            ON CONFLICT(pair, gran, ts) DO NOTHING
        """, (pair, f"M{gran_min}", ts_str,
              round(float(o), dec), round(float(hi), dec),
              round(float(lo), dec), round(float(c), dec)))
        n += 1
    db.commit()
    db.close()
    oldest = bar_ts(sorted(rows, key=lambda x: x[0])[0][0], gran_min)
    newest = bar_ts(sorted(rows, key=lambda x: x[0])[-1][0], gran_min)
    return (n, oldest.strftime("%Y-%m-%dT%H:%M:%S"),
            newest.strftime("%Y-%m-%dT%H:%M:%S"))


def poll_all(db):
    for pair in SQ_PAIRS:
        try:
            mid, spread = poll_swissquote(pair)
            for gran_min in [1, 5, 15, 30, 60]:
                ts   = datetime.now(timezone.utc)
                bts  = bar_ts(ts.timestamp(), gran_min)
                update_bar(db, pair, gran_min, bts, mid)
            db.commit()
        except Exception as ex:
            log(f"ERR {pair}: {ex}")
    for pair in CB_PAIRS:
        try:
            mid, spread = poll_coinbase(pair)
            for gran_min in [1, 5, 15, 30, 60]:
                ts   = datetime.now(timezone.utc)
                bts  = bar_ts(ts.timestamp(), gran_min)
                update_bar(db, pair, gran_min, bts, mid)
            db.commit()
        except Exception as ex:
            log(f"ERR {pair}: {ex}")


_GRAN_MAP = {"M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
             "H1": "M60", "M60": "M60"}


def get_bars(pair, gran, count):
    """Return list of [o,h,l,c] bars, newest last."""
    g = _GRAN_MAP.get(str(gran).upper(), str(gran).upper())
    db = _db()
    rows = db.execute("""
        SELECT o, h, l, c FROM bars
        WHERE pair=? AND gran=? AND ts <= datetime('now')
        ORDER BY ts DESC LIMIT ?""",
        (pair, g, count)).fetchall()
    db.close()
    return [list(r) for r in reversed(rows)]


def candles_from_bars(pair, gran, count, until=None):
    """Return list of {t,o,h,l,c} for bot_v2 / signal-engine.

    `until` (str "YYYY-MM-DDTHH:MM:SS", UTC) menapis bar supaya carta
   achievement berhenti pada masa trade ditutup. Tanpa ia, carta bagi
    trade yang sudah tutup akan tunjuk harga terkini berbanding harga
    ketika SL/TP kena — mengelirukan member yang查看 carta lama.
    """
    g = _GRAN_MAP.get(str(gran).upper(), str(gran).upper())
    db = _db()
    if until:
        rows = db.execute("""
            SELECT ts, o, h, l, c FROM bars
            WHERE pair=? AND gran=? AND ts<=?
            ORDER BY ts DESC LIMIT ?""",
            (pair, g, until, count)).fetchall()
    else:
        rows = db.execute("""
            SELECT ts, o, h, l, c FROM bars
            WHERE pair=? AND gran=?
            ORDER BY ts DESC LIMIT ?""",
            (pair, g, count)).fetchall()
    db.close()
    out = []
    for i, (ts, o, h, l, c) in enumerate(reversed(rows)):
        out.append({"t": f"{ts}Z", "o": o, "h": h, "l": l, "c": c,
                    "done": i < len(rows) - 1})
    return out


def main():
    if LOCK.exists():
        try:
            age = time.time() - LOCK.stat().st_mtime
            if age < 300:
                log(f"LOCK exists ({age:.0f}s) — skip")
                return 0
            log(f"WARN stale lock ({age:.0f}s) removed")
            LOCK.unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    LOCK.write_text(str(os.getpid()))
    try:
        init_db()
        log(f"START pairs={list(SQ_PAIRS)} poll={POLL}s")
        while True:
            poll_all(_db())
            time.sleep(POLL)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("stopped")
