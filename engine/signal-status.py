#!/usr/bin/env python3
"""TraderWatch signal status updater.

Reads open signals from Supabase, fetches 1-minute candles, determines
TP/SL/expired/cancelled, writes signal-status.json, and commits only when
something changed. Never invents prices: on missing data the existing status
is preserved and the error is logged.

Data source: MT5 M1 via the wine bridge (engine/mt5_read.py) is the SINGLE
market-data source (RoboForex broker). No Swissquote/TwelveData fallback:
when the bridge is down or the terminal is stale, candles() fails closed
(returns None) so no TP/SL verdict is ever made on substituted data.
"""
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path("/home/ubuntu/web/Traderwatch-repo")
# The engine package lives one level up: `from engine.private_signals import ...`
# needs the repo root on sys.path, not this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STATUS_FILE = REPO / "signal-status.json"
SECRETS = Path.home() / ".secrets"
TZ_KL = timezone(timedelta(hours=8))
LOOKBACK_DAYS = 7
EXPIRY_SCALP = None  # M15 stays active until TP/SL or explicit cancellation
EXPIRY_H1 = timedelta(hours=48)
MAX_AGE = timedelta(days=90)
CALL_GAP = 9

# --- Fair rotation over the signal backlog (2026-11-25) ----------------------
# Before this, the loop walked `rows` from index 0 every run and broke at
# MAX_CHECKS. With 456 verified signals in the 7-day window and only 40
# checks per run, the same 40 were re-tested forever and the rest were never
# read — a signal could sit "active" for hours after its TP was hit because
# it was never its turn. Checks are ~1.35 s each, so one run is ~55 s.
#
# Now: the newest ROTATE_FRESH signals are always checked (a fresh signal's
# SL/TP is what the operator is watching), then a cursor sweeps the rest so
# every signal is covered on a bounded cycle.
ROTATE_FRESH = 30
MAX_CHECKS = 110
# rows fetched per run; must exceed the number of signals that can be
# genuinely active inside LOOKBACK_DAYS
ROWS_LIMIT = 600
PIP = {"XAUUSD": 0.1, "XAGUSD": 0.001, "USDJPY": 0.01, "BTCUSD": 1.0}
DEFAULT_PIP = 0.0001
# BTC movement is measured in USD, not forex pips.
USD_UNIT = {"BTCUSD"}


LIFECYCLE_FILE = Path("/home/ubuntu/web/.signal-lifecycle.json")

def lifecycle_closed_by_id():
    """Map Supabase signal id -> closed status dari lifecycle-alert.

    Lifecycle-alert ialah sumber kebenaran untuk expiry: dia yang hantar
    notifikasi EXPIRED ke member. signal-status.py MESTI hormat verdict
    itu — jangan overwrite expired jadi tp/sl kemudian (bug #207:
    lifecycle kata expired, website tunjuk SL -127.4 pips palsu).
    Keyed by Supabase id (str); lifecycle file keyed by sid.
    """
    try:
        return {str(k): str(v.get("closed") or "") for k, v in
                json.loads(LIFECYCLE_FILE.read_text()).items()
                if isinstance(v, dict) and v.get("closed")}
    except Exception:
        return {}


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


def _mt5_candles(code, start, end):
    """MT5 M1 via wine bridge — rows [(ts_string, high, low)] oldest->newest.

    MT5 bar `t` ialah waktu server broker yang diencode sebagai unix epoch
    (di sini UTC+2, musim panas UTC+3). Offset diterbitkan dari bar terbaru
    vs waktu sebenar, dibundar ke jam penuh — jadi pertukaran DST tidak
    memecahkan alignment. Jika terminal stale (>15 min) offset tidak boleh
    dipercayai: tolak data, jangan evaluate TP/SL atas timestamp tersalah.
    Returns (rows, err); rows None bila gagal/tak cukup coverage.
    """
    from engine.mt5_read import run as mt5_run
    now = datetime.now(timezone.utc)
    need = int((now - start).total_seconds() // 60) + 5
    need = max(60, min(need, 15000))
    out, err = mt5_run(["candles", code, "1min", str(need)], timeout=120)
    if not out:
        return None, f"no output: {err[:90]}"
    payload = json.loads(out)
    if payload.get("error"):
        return None, f"error: {str(payload['error'])[:90]}"
    bars = payload.get("bars") or []
    if not bars:
        return None, "empty bars"
    bars.sort(key=lambda b: b["t"])
    off = round((bars[-1]["t"] - now.timestamp()) / 3600) * 3600
    if now.timestamp() - (bars[-1]["t"] - off) > 15 * 60:
        return None, "stale terminal"
    rows = []
    for b in bars:
        d = datetime.fromtimestamp(b["t"] - off, tz=timezone.utc)
        if start <= d <= end:
            rows.append((d.strftime("%Y-%m-%dT%H:%M:%S"),
                         float(b["h"]), float(b["l"])))
    if not rows:
        return None, "no bars in window"
    first = datetime.fromtimestamp(bars[0]["t"] - off, tz=timezone.utc)
    if first > start + timedelta(minutes=1):
        return None, "history does not cover window start"
    return rows, ""


def candles(pair, start, end):
    """Fetch 1-minute candles between start and end (UTC) from the MT5 broker
    (single source — no Swissquote/TwelveData fallback). Returns (rows, source)
    or (None, err) when the bridge is down / data stale."""
    try:
        rows, err = _mt5_candles(_sq_pair(pair), start, end)
        if rows:
            return rows, "mt5"
        return None, err or "mt5 no data"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:90]}"


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
    rows_raw = sb_get("signals?select=id,pair,side,entry,sl,tp,timeframe,posted_at,verified"
                  f"&verified=is.true&posted_at=gte.{since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                  f"&order=posted_at.desc&limit={ROWS_LIMIT}")
    # Tapis private signal daripada status web
    from engine.private_signals import is_private
    rows = [r for r in (json.loads(rows_raw or "[]") if isinstance(rows_raw,str) else (rows_raw or []))
            if not is_private(r.get("id"))]
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
    _lc_map = lifecycle_closed_by_id()

    # --- build the sweep order (see ROTATE_FRESH) ---------------------------
    # Skip entries already in a terminal state so the cursor measures real
    # work, not rows that are about to be `continue`d.
    live_idx = []
    for i, _r in enumerate(rows):
        try:
            _k = key_for(_r.get("pair"), _r.get("posted_at"))
        except Exception:
            _k = None          # unparseable row: the main loop skips it too
        if _k and state["signals"].get(_k, {}).get("status") in (
                "tp", "sl", "expired", "cancelled", "collected", "void_unfilled"):
            continue
        live_idx.append(i)

    fresh = live_idx[:ROTATE_FRESH]
    tail = live_idx[ROTATE_FRESH:]
    cursor = state.get("_cursor") or 0
    cap = MAX_CHECKS - len(fresh)
    if tail and cap > 0:
        if cursor >= len(tail):
            cursor = 0
        order = fresh + (tail[cursor:] + tail[:cursor])[:cap]
        new_cursor = cursor + min(cap, len(tail))
        if new_cursor >= len(tail):
            new_cursor = 0
    else:
        order = fresh[:MAX_CHECKS]
        new_cursor = 0
    state["_cursor"] = new_cursor
    log(f"rotate fresh={len(fresh)} tail={len(tail)} cursor={cursor} "
        f"-> {new_cursor} planned={len(order)}")

    for row in (rows[i] for i in order):
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
        
        # Tapis private signal
        from engine.private_signals import is_private
        if is_private(sig.get("signal_id")):
            continue

        # Status terminal: jangan evaluate semula. void_unfilled mesti
        # ada di sini — tanpanya cron akan reset ke "active" pada run
        # seterusnya dan hantar notifikasi palsu lagi (bug trade #110).
        if prev.get("status") in ("tp", "sl", "expired", "cancelled", "collected",
                                  "void_unfilled"):
            continue
        # GATE LIFECYCLE (bug #207): lifecycle-alert ialah sumber kebenaran
        # untuk expiry — dia yang hantar notifikasi EXPIRED ke member.
        # Kalau lifecycle dah tutup (expired/ignored/void), jangan tulis
        # tp/sl atas key yang sama. Contoh: id 207 expired (entry tak kena)
        # tapi bar kemudian sentuh entry+SL → tanpa gate ini website
        # tunjuk SL -127.4 pips palsu walhal member terima EXPIRED.
        lc_closed = _lc_map.get(str(row.get("id") or ""))
        if lc_closed and lc_closed not in ("tp", "sl", "collected"):
            if prev.get("status") != lc_closed:
                state["signals"][key] = {
                    "status": "expired",
                    "closed": now.astimezone(TZ_KL).isoformat(timespec="seconds"),
                    "note": "lifecycle:" + lc_closed}
                changed += 1
                log(f"LIFECYCLE {sig['pair']} #{row.get('id')} -> expired "
                    f"(lifecycle:{lc_closed})")
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
            # Belt-and-braces: `order` is already capped, so this should never
            # fire. Kept so a future edit cannot silently re-create the
            # starvation bug this rotation was written to fix.
            log(f"CAP reached {MAX_CHECKS} checks unexpectedly; rest deferred")
            break
        # An open-ended scalping setup still needs a bounded API window per
        # request; evaluate from posting time through now.
        end = now if limit is None else min(now, posted + limit)
        data, src = candles(sig["pair"], posted, end)
        # Swissquote M1 ialah SQLite lokal, MT5 ialah bridge wine lokal —
        # tiada rate limit, jadi tiada keperluan tunggu CALL_GAP. Hanya
        # TwelveData (network) perlu gap.
        gap = 0 if src in ("swissquote", "mt5") else CALL_GAP
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
        # Prune by age only. A key must NOT be dropped just because its
        # Supabase row is gone: the signals table has its own retention and
        # old rows get deleted, but signal-status.json is the historical
        # record the dashboard's win-rate/pip stats are computed from.
        # Dropping them here wiped 151 closed setups in one run and reset the
        # member performance stats to zero.
        if ts < cutoff:
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
        if not _commit_and_push(changed):
            return 1
    return 0 if errors == 0 else 1


def _commit_and_push(changed):
    """Commit + push signal-status.json, surviving a concurrent editor.

    The repo is edited by hand (and by T3) while this cron runs every 5 min.
    A push sent from a parent that is 20-30 s stale is rejected with
    `cannot lock ref 'refs/heads/main'` — observed 2026-11-25 00:27:44, 24 s
    after an interactive commit. 288 runs a day make that race common even
    though it is harmless. Re-pull then retry instead of losing the run down
    the `return 1` path.
    """
    for attempt in (1, 2, 3):
        git("add", "signal-status.json")
        commit = git("commit", "-m", f"status: {changed} signal update(s)")
        committed_now = commit.returncode == 0
        if not committed_now:
            # "nothing to commit" is expected in two cases: the working tree
            # is genuinely clean, or attempt 1 already created the commit and
            # the pull just rebased it. Either way we still push — a previous
            # run may have left a commit unpushed after a lock-ref rejection,
            # and this is the only place that drains it.
            if "nothing to commit" not in (commit.stdout or ""):
                log("COMMIT-FAIL " + (commit.stderr or "")[:160])
                return False

        push = git("push", "origin", "main")
        if push.returncode == 0:
            return True

        err = (push.stderr or "") + (push.stdout or "")
        log(f"PUSH-FAIL attempt {attempt}: " + err[:160])
        if attempt == 3:
            break
        # Someone else advanced main. Rebase our single status commit on top
        # and try again. --autostash protects any half-written working tree.
        rebase = git("-c", "rebase.autoStash=true", "pull", "--rebase", "--quiet")
        if rebase.returncode != 0:
            git("rebase", "--abort")
            log("PUSH-RETRY abandoned: pull --rebase failed")
            return False

    log("PUSH-FAIL final — giving up after 3 attempts")
    return False


if __name__ == "__main__":
    sys.exit(main())
