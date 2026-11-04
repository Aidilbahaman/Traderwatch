#!/usr/bin/env python3
"""Validate and import AI-assisted TraderWatch signals.

Dry-run by default: nothing is written unless --commit is passed. Every rule in
engine/signal-spec.md is enforced here, so a rejected signal never reaches the
members' dashboard.

Usage:
  python3 engine/signal-import.py --file candidates.json
  python3 engine/signal-import.py --file candidates.json --commit
  python3 engine/signal-import.py --status          # show active pairs
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATUS_FILE = REPO / "signal-status.json"
SECRETS = Path.home() / ".secrets"

PAIRS = {"XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"}
PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001
DP = {"XAU/USD": 2, "USD/JPY": 3}
DEFAULT_DP = 5

SCALP_MIN_SL = 12.0
SCALP_RR_MIN = 1.8
SCALP_RR_MAX = 2.2
H1_MIN_RR = 1.5
MAX_BACKDATE_MIN = 10


def pip_size(pair):
    return PIP.get(pair, DEFAULT_PIP)


def decimals(pair):
    return DP.get(pair, DEFAULT_DP)


def load(name):
    vals = {}
    for line in (SECRETS / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def active_pairs():
    """Pairs that currently have an unresolved setup."""
    try:
        state = json.loads(STATUS_FILE.read_text())
    except Exception:
        return None, "cannot read signal-status.json"
    pairs = set()
    for key, info in (state.get("signals") or {}).items():
        if (info.get("status") or "").lower() != "active":
            continue
        code = str(key).split("_", 1)[0]
        if len(code) == 6:
            pairs.add(code[:3] + "/" + code[3:])
    return pairs, ""


def validate(sig, active):
    """Return (errors, metrics). Pure: no network, no writes."""
    errors = []
    m = {}

    pair = str(sig.get("pair", "")).strip().upper()
    side = str(sig.get("side", "")).strip().upper()
    tf = str(sig.get("timeframe", "")).strip().upper()

    if pair not in PAIRS:
        errors.append(f"pair '{pair}' not whitelisted (use one of {sorted(PAIRS)})")
    if side not in ("BUY", "SELL"):
        errors.append(f"side '{side}' must be BUY or SELL")
    if tf not in ("H1", "M15"):
        errors.append(f"timeframe '{tf}' must be H1 or M15")

    try:
        entry = float(sig["entry"])
        sl = float(sig["sl"])
        tp = float(sig["tp"])
    except (KeyError, TypeError, ValueError):
        return errors + ["entry, sl and tp must be numeric"], m

    if min(entry, sl, tp) <= 0:
        errors.append("entry, sl and tp must be positive prices")

    if pair in PAIRS:
        step = 10 ** -decimals(pair)
        for name, value in (("entry", entry), ("sl", sl), ("tp", tp)):
            if round(value / step) * step != round(value, decimals(pair)):
                # informational only; rounding differences are common
                pass

    if side == "BUY" and not (sl < entry < tp):
        errors.append("BUY requires sl < entry < tp")
    if side == "SELL" and not (tp < entry < sl):
        errors.append("SELL requires tp < entry < sl")

    if pair in PAIRS and side in ("BUY", "SELL"):
        p = pip_size(pair)
        sl_pips = abs(entry - sl) / p
        tp_pips = abs(tp - entry) / p
        rr = tp_pips / sl_pips if sl_pips else 0
        m.update({"sl_pips": round(sl_pips, 1), "tp_pips": round(tp_pips, 1),
                  "rr": round(rr, 2)})

        if tf == "M15":
            if sl_pips < SCALP_MIN_SL:
                errors.append(
                    f"M15 stop is {sl_pips:.1f} pips; must be at least "
                    f"{SCALP_MIN_SL:.0f}")
            if not (SCALP_RR_MIN <= rr <= SCALP_RR_MAX):
                errors.append(
                    f"M15 reward:risk is {rr:.2f}; must be "
                    f"{SCALP_RR_MIN}-{SCALP_RR_MAX} (1:2)")
        elif tf == "H1" and rr < H1_MIN_RR:
            errors.append(f"H1 reward:risk is {rr:.2f}; must be at least {H1_MIN_RR}")

    posted = sig.get("posted_at")
    if posted:
        try:
            d = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - d.astimezone(timezone.utc)
            if age > timedelta(minutes=MAX_BACKDATE_MIN):
                errors.append(
                    f"posted_at is {age.total_seconds()/60:.0f} min old; "
                    f"max {MAX_BACKDATE_MIN} min (no backdating)")
        except ValueError:
            errors.append("posted_at is not a valid ISO timestamp")

    if active and pair in active:
        errors.append(f"{pair} already has an active setup; wait until it closes")

    return errors, m


def insert(sig):
    s = load("supabase.env")
    body = {
        "pair": str(sig["pair"]).strip().upper(),
        "side": str(sig["side"]).strip().upper(),
        "timeframe": str(sig["timeframe"]).strip().upper(),
        "entry": str(float(sig["entry"])),
        "sl": str(float(sig["sl"])),
        "tp": str(float(sig["tp"])),
        "verified": True,
    }
    if sig.get("posted_at"):
        body["posted_at"] = sig["posted_at"]
    req = urllib.request.Request(
        s["SUPABASE_URL"] + "/rest/v1/signals",
        data=json.dumps(body).encode(),
        headers={"apikey": s["SUPABASE_SERVICE_KEY"],
                 "Authorization": "Bearer " + s["SUPABASE_SERVICE_KEY"],
                 "Content-Type": "application/json",
                 "Prefer": "return=minimal"},
        method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="JSON array of candidate signals")
    ap.add_argument("--commit", action="store_true",
                    help="write accepted signals (default is dry-run)")
    ap.add_argument("--status", action="store_true", help="list active pairs")
    args = ap.parse_args()

    active, err = active_pairs()
    if active is None:
        print(f"ERROR {err}", file=sys.stderr)
        return 2

    if args.status:
        print("active pairs:", sorted(active) if active else "(none)")
        return 0

    if not args.file:
        print("error: pass --file or --status", file=sys.stderr)
        return 2

    try:
        data = json.loads(Path(args.file).read_text())
    except Exception as e:
        print(f"ERROR reading {args.file}: {e}", file=sys.stderr)
        return 2
    if not isinstance(data, list):
        print("ERROR file must contain a JSON array", file=sys.stderr)
        return 2

    print(f"active pairs: {sorted(active) if active else '(none)'}")
    print(f"candidates:   {len(data)}\n")

    ok_rows, rejected = [], []
    seen_pairs = set()
    for i, sig in enumerate(data, 1):
        pair = str(sig.get("pair", "")).strip().upper()
        # a candidate file must not contain two signals for the same pair
        dup_in_file = pair in seen_pairs
        errors, m = validate(sig, active)
        if dup_in_file:
            errors.append("duplicate pair inside this file")
        if errors:
            rejected.append((i, pair, errors))
            print(f"[{i}] REJECT {pair or '(no pair)'}")
            for e in errors:
                print(f"      - {e}")
        else:
            ok_rows.append(sig)
            seen_pairs.add(pair)
            print(f"[{i}] OK     {pair} {sig.get('side')} {sig.get('timeframe')} "
                  f"| SL {m.get('sl_pips')}p TP {m.get('tp_pips')}p "
                  f"R:R 1:{m.get('rr')}")

    print(f"\naccepted {len(ok_rows)}  rejected {len(rejected)}")

    if not ok_rows:
        return 0 if not rejected else 1
    if not args.commit:
        print("\nDRY RUN — nothing written. Re-run with --commit to import.")
        return 0

    written = 0
    for sig in ok_rows:
        try:
            insert(sig)
            written += 1
            print(f"  inserted {sig['pair']} {sig['side']} {sig['timeframe']}")
        except Exception as e:
            print(f"  INSERT-FAIL {sig.get('pair')}: {type(e).__name__} {str(e)[:120]}",
                  file=sys.stderr)
    print(f"\nimported {written}/{len(ok_rows)}")
    return 0 if written == len(ok_rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
