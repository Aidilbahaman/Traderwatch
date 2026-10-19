#!/usr/bin/env python3
"""TraderWatch signal status updater.

Reads open signals from Supabase, fetches M1 candles from Twelve Data,
determines TP/SL/expired/cancelled, writes signal-status.json, and commits
only when something changed. Never invents prices: on missing data the
existing status is preserved and the error is logged.
"""
import json
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
EXPIRY_SCALP = None  # stays active until TP/SL or explicit cancellation
EXPIRY_H1 = timedelta(hours=48)
MAX_AGE = timedelta(days=90)
CALL_GAP = 9
PIP = {"XAUUSD": 0.1, "USDJPY": 0.01}
DEFAULT_PIP = 0.0001
# Cap how many open setups are evaluated per run to stay inside the free
# Twelve Data credit budget (8/min, 800/day).
MAX_CHECKS = 8


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


def candles(pair, start, end):
    """Fetch M1 candles between start and end (UTC)."""
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
            return out, ""
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                time.sleep(62)
                continue
            return None, f"HTTP {e.code}"
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:90]}"
    return None, "rate limit persisted"


def parse_ts(value):
    """Parse a Supabase timestamp into an aware UTC datetime."""
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


def evaluate(sig, rows):
    """Return (status, pips, r, ambiguous). rows ordered oldest->newest."""
    entry, sl, tp = sig["entry"], sig["sl"], sig["tp"]
    side = sig["side"].upper()
    code = "".join(ch for ch in sig["pair"].upper() if ch.isalpha())
    for _ts, high, low in rows:
        hit_tp = high >= tp if side == "BUY" else low <= tp
        hit_sl = low <= sl if side == "BUY" else high >= sl
        if hit_tp and hit_sl:
            pips = -abs(entry - sl) / pip_size(code)
            return "sl", round(pips, 1), -1, True
        if hit_sl:
            pips = -abs(entry - sl) / pip_size(code)
            return "sl", round(pips, 1), -1, False
        if hit_tp:
            pips = abs(tp - entry) / pip_size(code)
            rr = round(abs(tp - entry) / abs(entry - sl), 2) if entry != sl else 0
            return "tp", round(pips, 1), rr, False
    return None, None, None, False


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True)


def main():
    subprocess.run(["git", "-C", str(REPO), "pull", "--rebase", "--quiet"],
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
        if prev.get("status") in ("tp", "sl", "expired", "cancelled"):
            continue

        posted = parse_ts(sig["posted_at"])
        age = now - posted
        limit = EXPIRY_SCALP if sig["timeframe"] == "M1" else EXPIRY_H1
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
        data, err = candles(sig["pair"], posted, end)
        if data is None:
            log(f"DATA {sig['pair']}: {err}")
            errors += 1
            time.sleep(CALL_GAP)
            continue
        if not data:
            log(f"DATA {sig['pair']}: empty candle set")
            errors += 1
            time.sleep(CALL_GAP)
            continue

        status, pips, r, ambiguous = evaluate(sig, data)
        if status:
            entry = {"status": status, "pips": pips, "r": r,
                     "closed": now.astimezone(TZ_KL).isoformat(timespec="seconds")}
            if ambiguous:
                entry["ambiguous"] = True
            state["signals"][key] = entry
            changed += 1
            log(f"{'TP' if status=='tp' else 'SL'} {sig['pair']} {pips:+.1f} pips")
        elif prev.get("status") != "active":
            state["signals"][key] = {"status": "active"}
            changed += 1
        time.sleep(CALL_GAP)

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
    STATUS_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")

    log(f"DONE checked={checked} changed={changed} errors={errors} total={len(state['signals'])}")

    if changed:
        git("add", "signal-status.json")
        git("commit", "-m", f"status: {changed} signal update(s)")
        push = git("push", "origin", "main")
        if push.returncode != 0:
            log("PUSH-FAIL " + (push.stderr or "")[:160])
            return 1
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
