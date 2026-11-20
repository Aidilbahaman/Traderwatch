#!/usr/bin/env python3
"""TraderWatch Paper Trading League — auto-resolver.

Every minute: read open paper_trades, check live Swissquote M1/M5 bars, and
close trades when price hits TP or SL. R result is computed from risk_pct,
so nobody can self-report a win. Everything is derived from real prices.

Fill-first rule (2026-11-21): a trade can only close at TP/SL AFTER its entry
was actually touched. Market-entry trades fill on the bar they opened;
pending-style entries that never touched expire after 6h with no R impact
(previously an unfilled buy stop could be wrongly closed at "SL").

Also tracks BE: if price reaches entry + 1R after fill, SL moves to entry
(break-even protection). Trade then closes as 'be' when price comes back
to entry.

Usage: python3 engine/paper-league-resolver.py
"""
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
SEASON = int(os.environ.get("LEAGUE_SEASON", "1"))
BAR_LIMIT = 30  # M1 bars since open (roughly 30 min lookback)


def load_env():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


SEC = load_env()
SB_URL = SEC["SUPABASE_URL"].rstrip("/")
SB_KEY = SEC["SUPABASE_SERVICE_KEY"]


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} LEAGUE {msg}", flush=True)


def sb(method, path, body=None, params=None):
    url = SB_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SB_KEY)
    req.add_header("Authorization", "Bearer " + SB_KEY)
    req.add_header("Content-Type", "application/json")
    if method == "POST":
        req.add_header("Prefer", "return=representation")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        log(f"sb {method} {path} HTTP {e.code}: {e.read().decode()[:200]}")
        raise


def bars(pair, gran="M1", count=BAR_LIMIT):
    """Read from sq-bars.db (read-only) via sq_collector."""
    import importlib.util as il
    spec = il.spec_from_file_location("sqc", HERE / "sq_collector.py")
    m = il.module_from_spec(spec)
    spec.loader.exec_module(m)
    p = pair.replace("/", "").replace(" ", "").upper()
    rows = m.candles_from_bars(p, gran, count)
    out = []
    for c in rows:
        try:
            d = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            out.append({"t": d, "h": float(c["h"]), "l": float(c["l"]), "c": float(c["c"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def resolve(trade):
    pair = trade["pair"]
    side = trade["side"]
    entry = float(trade["entry"])
    sl = float(trade["sl"])
    tp = float(trade["tp"])
    opened = datetime.fromisoformat(trade["opened_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age_min = (now - opened).total_seconds() / 60.0
    # Look back far enough to cover the whole life of the trade (not just 30m).
    count = min(10000, max(BAR_LIMIT, int(age_min) + 5))
    # Include the M1 bar containing opened_at so market entries register filled.
    series = [b for b in bars(pair, count=count)
              if b["t"] >= opened - timedelta(seconds=60)]
    if not series:
        return None
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    # 1) Fill check — entry must actually be touched before TP/SL applies.
    fill_t = None
    for b in series:
        if (side == "BUY" and b["h"] >= entry) or (side == "SELL" and b["l"] <= entry):
            fill_t = b["t"]
            break
    if fill_t is None:
        if age_min > 360:  # never filled within 6h -> expired, no R impact
            return ("expired", 0.0)
        return None
    active = [b for b in series if b["t"] >= opened and b["t"] >= fill_t]
    if not active:
        return None
    be_level = entry + risk if side == "BUY" else entry - risk
    hit_be = any((b["h"] >= be_level if side == "BUY" else b["l"] <= be_level) for b in active)
    # Check chronological: first touch wins
    for b in active:
        if side == "BUY":
            if b["h"] >= tp:
                return ("tp", round(abs(tp - entry) / risk, 2))
            if b["l"] <= sl:
                return ("sl", -1.0)
        else:
            if b["l"] <= tp:
                return ("tp", round(abs(tp - entry) / risk, 2))
            if b["h"] >= sl:
                return ("sl", -1.0)
    if hit_be:
        # price reached 1R — protection active; if it came back to entry, close BE
        for b in active:
            if side == "BUY" and b["l"] <= entry:
                return ("be", 0.0)
            if side == "SELL" and b["h"] >= entry:
                return ("be", 0.0)
    return None


def main():
    open_trades = sb("GET", "/rest/v1/paper_trades", params={
        "select": "id,pair,side,entry,sl,tp,risk_pct,risk_usd,opened_at",
        "status": "eq.open", "season": f"eq.{SEASON}", "limit": "200"
    }) or []
    log(f"open trades: {len(open_trades)}")
    for tr in open_trades:
        try:
            result = resolve(tr)
        except Exception as e:
            log(f"trade {tr['id']} resolve error {type(e).__name__}: {str(e)[:120]}")
            continue
        if not result:
            continue
        status, r = result
        sb("PATCH", f"/rest/v1/paper_trades?id=eq.{tr['id']}", body={
            "status": status, "r_result": r,
            "closed_at": datetime.now(timezone.utc).isoformat()
        })
        log(f"trade {tr['id']} {tr['pair']} {tr['side']} -> {status} {r:+.2f}R")
    log("done")


if __name__ == "__main__":
    main()