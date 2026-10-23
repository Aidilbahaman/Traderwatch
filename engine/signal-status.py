#!/usr/bin/env python3
"""TraderWatch signal status updater.

Reads open signals from Supabase, fetches 1-minute candles, determines
TP/SL/expired/cancelled, writes signal-status.json, and commits only when
something changed. Never invents prices: on missing data the existing status
is preserved and the error is logged.

Data source: Swissquote M1 from state/sq-bars.db is PRIMARY (local SQLite,
populated live by sq-collector — no network, no rate limit, no credit cost).
TwelveData 1-min is only a fallback for windows Swissquote does not cover
(older trades from before the collector started polling).
"""
import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path("/home/ubuntu/web/Traderwatch-repo")
STATUS_FILE = REPO / "signal-status.json"
SECRETS = Path.home() / ".secrets"
TZ_KL = timezone(timedelta(hours=8))
LOOKBACK_DAYS = 7
EXPIRY_SCALP = None  # M15 stays active until TP/SL or explicit cancellation
EXPIRY_H1 = timedelta(hours=48)
MAX_AGE = timedelta(days=90)
CALL_GAP = 9
PIP = {"XAUUSD": 0.1, "USDJPY": 0.01, "BTCUSD": 1.0}
DEFAULT_PIP = 0.0001
# BTC movement is measured in USD, not forex pips.
USD_UNIT = {"BTCUSD"}
# Cap how many open setups are evaluated per run. Swissquote M1 ialah SQLite
# lokal (tiada kredit/rate limit), jadi had ini hanya perlu cukup besar untuk
# semua setup terbuka — bukan lagi terikat bajet Twelve Data.
MAX_CHECKS = 40


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def load(name):
    vals = {}
    for line in (SECRETS / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


SB = load("supabase.env")
TD_KEY = load("twelve.env")["TWELVEDATA_API_KEY"]


def sb_get(path):
    req = urllib.request.Request(
        f"{SB['SUPABASE_URL']}/rest/v1/{path}",
        headers={"apikey": SB["SUPABASE_SERVICE_KEY"],
                 "Authorization": "Bearer " + SB["SUPABASE_SERVICE_KEY"]})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


SQ_DB = REPO / "state" / "sq-bars.db"


def _sq_pair(pair):
    """'USD/CAD' -> 'USDCAD' (kunci lajur dalam sq-bars.db)."""
    return "".join(c for c in str(pair).upper() if c.isalpha())


def candles(pair, start, end):
    """Fetch 1-minute candles between start and end (UTC).

    Swissquote M1 SQLite ialah sumber UTAMA: sq-collector poll live setiap
    beberapa saat dan simpan bar M1 terus ke state/sq-bars.db. Jadi semakan
    TP/SL tidak bergantung network, tidak ada had rate, dan percuma.

    TwelveData hanya sandaran bila Swissquote tiada bar dalam window itu
    (contoh trade lama sebelum collector mula poll).
    """
    try:
        if SQ_DB.exists():
            code = _sq_pair(pair)
            con = sqlite3.connect(f"file:{SQ_DB}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT ts, h, l FROM bars WHERE pair=? AND gran='M1' "
                    "AND ts>=? AND ts<=? ORDER BY ts",
                    (code, start.strftime("%Y-%m-%dT%H:%M:%S"),
                     end.strftime("%Y-%m-%dT%H:%M:%S"))).fetchall()
            finally:
                con.close()
            if rows:
                return [(r[0], float(r[1]), float(r[2])) for r in rows], "swissquote"
    except Exception as e:
        log(f"SQ-ERR {pair}: {type(e).__name__}: {str(e)[:70]}")

    # Sandaran: TwelveData 1-min.
    params = urllib.parse.urlencode({
        "symbol": pair, "interval": "1min", "timezone": "UTC",
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "outputsize": 5000, "apikey": TD_KEY,
    })
    url = "https://api.twelvedata.com/time_series?" + params
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TraderWatch-status/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            if data.get("status") == "error" or data.get("code"):
                msg = str(data.get("message", ""))[:140]
                if data.get("code") == 429 and attempt == 1:
                    log(f"RATE-LIMIT {pair}: wait 62s")
                    time.sleep(62)
                    continue
                return None, msg
            vals = data.get("values") or []
            out = []
            for v in reversed(vals):
                out.append((v["datetime"], float(v["high"]), float(v["low"])))
            return out, "twelvedata"
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                time.sleep(62)
                continue
            return None, f"HTTP {e.code}"
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:90]}"
    return None, "rate limit persisted"


def parse_ts(value):
    """Parse a Supabase timestamp into an aware UTC datetime.

    Supabase columns typed timestamptz come back NAIVE when the session
    timezone is UTC (the default for PostgREST). Treating that naive value
    as UTC is what key_for() does, so a signal posted 22 Oct 18:08 UTC is
    filed under 23 Oct 02:08 MY — the 23 Oct 02:08 key. That is correct:
    MY = UTC+8. Do not "fix" this by assuming the naive value is MY.
    """
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def key_for(pair, iso):
    d = parse_ts(iso).astimezone(TZ_KL)
    code = "".join(ch for ch in pair.upper() if ch.isalpha())
    return f"{code}_{d:%Y%m%d}_{d:%H%M%S}"


def pip_size(code):
    return PIP.get(code, DEFAULT_PIP)


def _iso_mine(ts):
    """Format a candle stamp as MY ISO +08:00.

    Accepts both shapes the two data sources emit:
      Swissquote SQLite -> "2026-10-22T18:50:00"
      TwelveData JSON   -> "2026-10-22 18:50:00"
    Both are UTC.
    """
    if not ts:
        return None
    raw = str(ts).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return d.astimezone(TZ_KL).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(raw)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(TZ_KL).isoformat(timespec="seconds")
    except Exception:
        return None


def evaluate(sig, rows):
    """Return (status, pips, r, ambiguous). rows ordered oldest->newest.

    ENTRY GATE: a TP/SL verdict is only valid once the market has actually
    traded through the entry level. Before that the position does not exist,
    so a pending setup can never "reach" TP or "hit" SL -- if price is merely
    beyond one of those levels the setup is still unfilled.

    Walk the bars in order and track fill state:
      - first bar whose range covers entry -> filled, verdict allowed;
      - a bar covering both SL and TP counts as SL (conservative);
      - bars before the fill are ignored for TP/SL purposes.
    """
    entry, sl, tp = sig["entry"], sig["sl"], sig["tp"]
    side = sig["side"].upper()
    code = "".join(ch for ch in sig["pair"].upper() if ch.isalpha())
    filled = False
    entry_at = None
    for _ts, high, low in rows:
        if not filled:
            hit_entry = low <= entry <= high
            if not hit_entry:
                # Setup still pending: skip TP/SL, price may sit beyond a
                # level without the trade existing.
                continue
            filled = True
            entry_at = _ts
        hit_tp = high >= tp if side == "BUY" else low <= tp
        hit_sl = low <= sl if side == "BUY" else high >= sl
        if hit_tp and hit_sl:
            pips = -abs(entry - sl) / pip_size(code)
            return "sl", round(pips, 1), -1, True, entry_at
        if hit_sl:
            pips = -abs(entry - sl) / pip_size(code)
            return "sl", round(pips, 1), -1, False, entry_at
        if hit_tp:
            pips = abs(tp - entry) / pip_size(code)
            rr = round(abs(tp - entry) / abs(entry - sl), 2) if entry != sl else 0
            return "tp", round(pips, 1), rr, False, entry_at
    # Fill happened but no TP/SL yet: report the fill so the lifecycle can
    # send the ENTRY alert and hold the position. This is what makes a manual
    # signal 24/7 — member gets told when the setup is actually live.
    if entry_at:
        return "active", None, None, False, entry_at
    return None, None, None, False, None


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True)


def main():
    # --autostash: working tree ada signal-status.json yang diubah cron
    # sebelumnya; tanpa autostash, "pull --rebase" gagal ("cannot pull with
    # rebase: You have unstaged changes") dan auto-commit mati.
    subprocess.run(["git", "-C", str(REPO), "pull", "--rebase", "--autostash",
                    "--quiet"],
                   capture_output=True, text=True)

    if STATUS_FILE.exists():
        state = json.loads(STATUS_FILE.read_text())
    else:
        state = {"updated": "", "signals": {}}
    state.setdefault("signals", {})

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=LOOKBACK_DAYS)
    history_since = now - MAX_AGE
    rows = sb_get("signals?select=pair,side,entry,sl,tp,timeframe,posted_at,verified"
                  f"&verified=is.true&posted_at=gte.{since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                  "&order=posted_at.desc&limit=200")
    history = sb_get("signals?select=pair,posted_at,verified"
                     f"&verified=is.true&posted_at=gte.{history_since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                     "&order=posted_at.desc&limit=1000")
    valid_keys = set()
    for h in history:
        try:
            valid_keys.add(key_for(h["pair"], h["posted_at"]))
        except Exception:
            continue

    checked = changed = errors = 0
    for row in rows:
        try:
            sig = {
                "pair": row["pair"], "side": row["side"],
                "entry": float(row["entry"]), "sl": float(row["sl"]), "tp": float(row["tp"]),
                "timeframe": (row.get("timeframe") or "H1").upper(),
                "posted_at": row["posted_at"],
            }
        except (TypeError, ValueError, KeyError):
            continue

        key = key_for(sig["pair"], sig["posted_at"])
        prev = state["signals"].get(key, {})
        # Status terminal: jangan evaluate semula. void_unfilled mesti
        # ada di sini — tanpanya cron akan reset ke "active" pada run
        # seterusnya dan hantar notifikasi palsu lagi (bug trade #110).
        if prev.get("status") in ("tp", "sl", "expired", "cancelled", "collected",
                                  "void_unfilled"):
            continue

        posted = parse_ts(sig["posted_at"])
        age = now - posted
        # M15 (and any legacy M1 rows) use the short scalping window.
        limit = EXPIRY_SCALP if sig["timeframe"] in ("M1", "M15") else EXPIRY_H1
        if limit is not None and age > limit:
            state["signals"][key] = {"status": "expired"}
            changed += 1
            continue

        checked += 1
        if checked > MAX_CHECKS:
            log(f"CAP reached {MAX_CHECKS} checks; remaining signals evaluated next run")
            break
        # An open-ended scalping setup still needs a bounded API window per
        # request; evaluate from posting time through now.
        end = now if limit is None else min(now, posted + limit)
        data, src = candles(sig["pair"], posted, end)
        # Swissquote M1 ialah SQLite lokal — tiada rate limit, jadi tiada
        # keperluan tunggu CALL_GAP. Hanya TwelveData (network) perlu gap.
        gap = 0 if src == "swissquote" else CALL_GAP
        if data is None:
            log(f"DATA {sig['pair']}: {src}")
            errors += 1
            if gap:
                time.sleep(gap)
            continue
        if not data:
            log(f"DATA {sig['pair']}: empty candle set")
            errors += 1
            if gap:
                time.sleep(gap)
            continue

        status, pips, r, ambiguous, entry_at = evaluate(sig, data)
        if status in ("tp", "sl"):
            code = "".join(ch for ch in sig["pair"].upper() if ch.isalpha())
            entry = {"status": status, "pips": pips, "r": r,
                     "unit": "usd" if code in USD_UNIT else "pips",
                     "closed": now.astimezone(TZ_KL).isoformat(timespec="seconds")}
            if ambiguous:
                entry["ambiguous"] = True
            if entry_at:
                entry["entry_at"] = _iso_mine(entry_at)
            state["signals"][key] = entry
            changed += 1
            log(f"{'TP' if status=='tp' else 'SL'} {sig['pair']} "
                f"{pips:+.1f} {'USD' if entry['unit']=='usd' else 'pips'}")
        elif status == "active":
            # Entry touched, no TP/SL yet — record the fill so the lifecycle
            # sends ENTRY TRIGGERED and holds the position.
            if not prev.get("entry_at"):     # jangan timpa fill yang direkod
                state["signals"][key] = dict(prev, status="active",
                                             entry_at=_iso_mine(entry_at))
                changed += 1
                log(f"ENTRY {sig['pair']} @ {sig['entry']} ({_iso_mine(entry_at)})")
        elif prev.get("status") != "active":
            # Setup BELUM filled: harga tidak pernah menyentuh entry, jadi
            # trade ini tidak wujud. Ia mesti "pending", bukan "active" —
            # kalau ditanda active, ia muncul sebagai posisi terbuka di
            # website walaupun tiada fill.
            state["signals"][key] = {"status": "pending"}
            changed += 1
        if gap:
            time.sleep(gap)

    cutoff = now - MAX_AGE
    for key in list(state["signals"]):
        parts = key.split("_")
        if len(parts) != 3:
            continue
        try:
            ts = datetime.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S").replace(tzinfo=TZ_KL)
        except ValueError:
            continue
        if ts < cutoff or key not in valid_keys:
            del state["signals"][key]
            changed += 1

    state["updated"] = now.astimezone(TZ_KL).isoformat(timespec="seconds")
    # Only keep fields this updater can verify. Drop unverified sample
    # strength/events payloads so the dashboard never shows invented data.
    state.pop("strength", None)
    state.pop("events", None)
    new_text = json.dumps(state, indent=1, ensure_ascii=False) + "\n"
    old_text = ""
    try:
        old_text = STATUS_FILE.read_text()
    except OSError:
        pass
    STATUS_FILE.write_text(new_text)

    log(f"DONE checked={checked} changed={changed} errors={errors} total={len(state['signals'])}")

    # Commit bila FILE berubah, bukan hanya bila ada perubahan status
    # signal. Field "updated" berubah setiap run, jadi commit setiap kali
    # memastikan Pages sentiasa dapat status live dan `git status` sentiasa
    # bersih (fail tak ternoda dalam working tree).
    if new_text != old_text:
        git("add", "signal-status.json")
        commit = git("commit", "-m", f"status: {changed} signal update(s)")
        if commit.returncode != 0:
            log("COMMIT-FAIL " + (commit.stderr or "")[:160])
        else:
            push = git("push", "origin", "main")
            if push.returncode != 0:
                log("PUSH-FAIL " + (push.stderr or "")[:160])
                return 1
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
