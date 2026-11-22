#!/usr/bin/env python3
"""Holy Grid Bridge LIVE Backtest — actual MT5 API, M1 XAUUSD, smart tiers.

Strategy (per Test & Tier):
  M1 signal: EMA9 > EMA21 → BUY / below → SELL
  Initial: entry lot = base on current equity, capped by tier; once/bar only.
  Grid: adverse next grid pt from latest entry, lot base each add (LOT_MULT=1.0).
  Basket TP: combined profit on side >= tier basket_tp → close ALL that side, bank.
  Hedge: float total <= -tier hedge → open opposite net exposure lot; auto-TP $2+ , auto-release ≤ -tier hedge release.
  Tier switch: $bal vs $20-$100 T1 / $100-$300 T2 / $300-$600 T3 / $600-$1000 T4 / $1000+ T5.
  Spread: $0.20 USD per open+close (real market slippage proxy included as small extra $0.10 round trip fix).
  Commission: skipped, but realistic tight spread accounts for its cost via trade-open/close friction only.
  margin safety: if equity < entry lot*0.01*open_price*spread*0.5 — no new order else close exit all.
"""
import json, math, os, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path("/home/ubuntu/web/Traderwatch-repo/engine")
SERVICE = Path("/home/ubuntu/web/Traderwatch-repo/state/holy-grid-bridge.json")
MYT = timezone_local()

tiers = [
    (0.0,    "T1 Saver",       dict(risk=1.0, grid=100.0, max_lot=0.01, max_total=0.03, basket_tp=1.00, hedge=8.0,  hedge_release=2.0)),
    (100.0,  "T2 Growing",      dict(risk=2.0, grid=150.0, max_lot=0.10, max_total=0.15, basket_tp=2.00, hedge=40.0, hedge_release=4.0)),
    (300.0,  "T3 Scaling",    dict(risk=3.0, grid=200.0, max_lot=0.25, max_total=0.40, basket_tp=3.50, hedge=70.0, hedge_release=6.0)),
    (600.0,  "T4 Established", dict(risk=4.0, grid=250.0, max_lot=0.50, max_total=1.00, basket_tp=5.00, hedge=100.0, hedge_release=8.0)),
    (1000.0, "T5 Full",        dict(risk=4.0, grid=300.0, max_lot=2.00, max_total=2.00, basket_tp=10.00, hedge=100.0, hedge_release=10.0)),
]

def tier_params(bal):
    cur = tiers[0][2]
    for lo, name, cfg in tiers:
        if bal >= lo: cur = cfg; break
    else: cur = tiers[-1][2]
    return name, cur

def ema(closes, n):
    if not closes: return []
    k = 2/(n+1); e=closes[0]; out=[e]
    for x in closes[1:]:
        e = x*k + e*(1-k); out.append(e)
    return out

def backtest(start_balance, tick_value=0.8918, vol_step=0.01, vol_min=0.01):
    bc = None
    try:
        bc = importlib.util.spec_from_file_location("pend", HERE/"mt5-pending.py")
    except Exception: pass
    pending = None
    def mt5call(req, timeout=120):
        nonlocal pending
        pending = None
        try:
            cmd = ["sudo","-n","-u","mt5","env","DISPLAY=:99",f"WINEPREFIX={"/home/mt5/.mt5"}",
                   "/opt/wine-staging/bin/wine","C:\\Python311\\python.exe","/home/mt5/.mt5/drive_c/mt5work/mt5_pending.py", json.dumps(req)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            for line in (r.stdout or"").splitlines():
                line=line.strip(); if line.startswith("{"): try: return json.loads(line)
                    except: pass
        except Exception as ex: pass
        return {"ok": False, "error":"api error", "detail": str(ex)}
    import subprocess
    mt5call({"action":"account"})  # warm-up init maybe needed
    end = mt5call({"action":"symbol","symbol":"XAUUSD"}, timeout=120)
    if not end.get("ok"): print("MT5 API failed for symbol:", end); return {}
    info = end; pt = float(info.get("point",1)); tv = float(info.get("tick_value",1)); vmin=float(info.get("vol_min",0.01))
    count = 259200
    data = mt5call({"action":"candles","symbol":"XAUUSD","count":count}, timeout=600)
    bars = data.get("bars", [])
    if not bars or len(bars) < 60: print("insufficient candles:", len(bars)); return {}

    positions = []; balance = start_balance; eq = start_balance
    open_price = {}; pnl = {}
    baskets = {"buy":0.0,"sell":0.0}; betas = {}  # lot holdings by side category (grid + initial)
    hedges = []          # side category -> list of dict
    peak = start_balance
    daily_loss = 0.0; day_start = start_balance; day_bar=0
    trades = 0; wins=0; losses=0; tprof=[]
    mcall_n=0; swap=0.0
    rows=[]; dt=[]; latest_row={}

    for i in range(len(bars)):
        o = bars[i]; closes = [float(x["c"]) for x in bars[max(0,i-2):i]]
        candle_close = float(o["c"])
        ptv = pt; tv = tick_value
        step_pts = tiers.__iter__() -> None
        grid = last_entry_level(previous opposes) — hard inline
        nxt_signal_zero if overlaps
        eq_delta = candle_close - int_candle_open
        eq_update
        track up day_loss & day_drawdown
        peak update
        # tier check by current balance
        name, T = tier_params(eq)
        max_total = T["max_total"]; max_lot_order=T["max_lot"]
        # compute positions & baskets quickly
        # initial only once per closed bar; grid adds follow; basket TP and hedge handled below
        sig=0
        if len(closes)>=22:
            f9=ema(closes,9); s21=ema(closes,21); sig=int((f9[-1]-s21[-1])>0)-1
        updates...
    print(...)
    return summary
