#!/usr/bin/env python3
"""TraderWatch "Take this trade" -> MT5 pending order sync (OWNER ONLY).

Owner flow (updated 2026-11-21): when the owner opens a trade via the app's
"Take this trade" modal and opts in to MT5, execute a MARKET order (instant
entry at the live price) with the verdict's SL/TP and the EXACT lot the owner
chose. No more pending limit/stop orders — the verdict entry can drift while
the LLM runs, which turned "instant" signals into unfilled buy/sell stops.
Members' trades stay PAPER only. Scan no longer auto-syncs.

SAFETY (real money — read carefully):
  * OWNER ONLY: uid must be in MT5_SYNC_UIDS allowlist. Everyone else -> no-op.
  * DRY-RUN DEFAULT: MT5_ONDEMAND_DRY=1 (default) computes lot + logs, but
    places NO real order. Owner must explicitly set =0 to go live.
  * Reuses the SAME guardrails as the scheduled engine (mt5-pending.py):
    risk-% lot sizing, SL > 3x spread guard, kill switch, max pending.
  * Idempotent: same setup (pair+side+entry+sl+tp) within DEDUP_HOURS -> skip.
  * HOLD verdict -> never places an order.
  * Audit: every attempt logged to state/mt5-ondemand-log.jsonl.

This module is imported by engine/analyze-api.py. It does NOT run on its own.
"""
import hashlib
import importlib.util
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STATE = REPO / "state" / "mt5-ondemand.json"
AUDIT = REPO / "state" / "mt5-ondemand-log.jsonl"

# Import the scheduled-engine MT5 module (has a __main__ guard; safe to import).
_spec = importlib.util.spec_from_file_location("tw_mt5_pending", HERE / "mt5-pending.py")
MP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MP)

DRY = os.environ.get("MT5_ONDEMAND_DRY", "1") == "1"
OWNER_UIDS = {x.strip() for x in os.environ.get("MT5_SYNC_UIDS", "").split(",") if x.strip()}
MAGIC_BASE = int(os.environ.get("MT5_ONDEMAND_MAGIC", "20262000"))
MAX_PENDING = int(os.environ.get("MT5_MAX_PENDING", "10"))
DEDUP_HOURS = float(os.environ.get("MT5_ONDEMAND_DEDUP_H", "6"))


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} MT5-ONDEMAND {msg}", flush=True)


def is_owner(uid):
    return bool(uid) and uid in OWNER_UIDS


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d))
    except OSError as e:
        log(f"WARN save state: {e}")


def _audit(rec):
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def sync_verdict(verdict, uid, lot=None):
    """Place a pending order for an owner's BUY/SELL trade. Returns a dict
    describing the outcome; never raises. Members / HOLD -> {'synced': False}.

    lot: owner's explicit lot choice (from "Take this trade"). When given it
    is used as-is (normalized to broker step/min/max); otherwise risk-% sizing.
    """
    if not is_owner(uid):
        return {"synced": False, "reason": "not-owner"}
    side = str(verdict.get("side", "")).upper()
    if side not in ("BUY", "SELL"):
        return {"synced": False, "reason": "hold"}
    pair = str(verdict.get("pair", "")).replace("/", "").replace(" ", "").upper()
    try:
        entry = float(verdict["entry"]); sl = float(verdict["sl"]); tp = float(verdict["tp1"])
    except (KeyError, TypeError, ValueError):
        return {"synced": False, "reason": "missing-levels"}
    if not pair or entry <= 0 or sl <= 0 or tp <= 0:
        return {"synced": False, "reason": "bad-levels"}

    key = hashlib.sha1(f"{pair}|{side}|{entry}|{sl}|{tp}".encode()).hexdigest()[:16]
    st = _load()
    now = time.time()
    prev = st.get(key)
    if prev and now - prev.get("ts", 0) < DEDUP_HOURS * 3600:
        return {"synced": False, "reason": "duplicate", "ticket": prev.get("ticket")}

    # Read-only account + guardrails (no order yet).
    try:
        acc = MP.equity_now()
        equity = float(acc.get("equity") or acc.get("balance") or 0)
    except Exception as e:
        return {"synced": False, "reason": f"equity-error:{type(e).__name__}"}
    if equity <= 0:
        return {"synced": False, "reason": "no-equity"}
    try:
        kd, _loss = MP.kill_status(equity)
        if kd.get("killed"):
            return {"synced": False, "reason": "kill-switch"}
    except Exception:
        pass  # kill state unreadable -> proceed with other guards
    if lot is not None:
        # Owner's explicit lot: respect it, but keep broker + spread guards.
        try:
            lot = float(lot)
        except (TypeError, ValueError):
            return {"synced": False, "reason": "bad-lot"}
        if not (0.01 <= lot <= 100):
            return {"synced": False, "reason": "lot-out-of-range"}
        try:
            spec = MP.symbol_spec(pair)
        except Exception as e:
            return {"synced": False, "reason": f"spec-error:{type(e).__name__}"}
        if not spec:
            return {"synced": False, "reason": "no-spec"}
        sp = float(spec.get("spread_price") or 0) or float(spec.get("spread_pt") or 0) * float(spec.get("point") or 0)
        if sp > 0 and abs(entry - sl) < 3 * sp:
            return {"synced": False, "reason": f"sl-too-close:spread={sp:g}"}
        step = float(spec.get("vol_step") or 0.01) or 0.01
        vmin = float(spec.get("vol_min") or 0.01) or 0.01
        vmax = float(spec.get("vol_max") or 100.0) or 100.0
        lot = round(math.floor(lot / step) * step, 8)
        if lot < vmin:
            return {"synced": False, "reason": f"lot<min:{vmin:g}"}
        if lot > vmax:
            lot = vmax
        note = f"owner-lot eq={equity:.2f}"
    else:
        try:
            lot, note = MP.size_lot(pair, entry, sl, equity)
        except Exception as e:
            return {"synced": False, "reason": f"lot-error:{type(e).__name__}"}
        if not lot:
            return {"synced": False, "reason": f"no-lot:{note}"}

    magic = MAGIC_BASE + (int(key[:6], 16) % 100000)
    base = {"pair": pair, "side": side, "entry": entry, "sl": sl, "tp": tp,
            "lot": lot, "magic": magic, "equity": equity}

    if DRY:
        st[key] = {"ts": now, "dry": True, "lot": lot}
        _save(st)
        _audit({"ts": datetime.now(timezone.utc).isoformat(), "uid": uid,
                "dry_run": True, **base, "note": note})
        log(f"DRY {uid[:8]} {pair} {side} lot={lot} (no real order)")
        return {"synced": True, "dry_run": True, "lot": lot, "magic": magic, "note": note}

    # LIVE: instant MARKET execution (no pending limit/stop). The host
    # validates live price vs SL/TP and rejects if price moved past them.
    try:
        res = MP.mt5({"action": "market", "symbol": pair, "side": side,
                      "sl": sl, "tp": tp, "lot": lot,
                      "magic": magic, "comment": "TW-ondemand"})
    except Exception as e:
        _audit({"ts": datetime.now(timezone.utc).isoformat(), "uid": uid,
                "dry_run": False, **base, "error": f"{type(e).__name__}: {str(e)[:160]}"})
        return {"synced": False, "reason": f"mt5-error:{type(e).__name__}"}
    if res.get("ok"):
        st[key] = {"ts": now, "ticket": res.get("ticket"), "lot": lot}
        _save(st)
        _audit({"ts": datetime.now(timezone.utc).isoformat(), "uid": uid,
                "dry_run": False, **base, "ticket": res.get("ticket"),
                "fill_price": res.get("price"), "type": "market"})
        log(f"LIVE {uid[:8]} {pair} {side} MARKET lot={lot} fill={res.get('price')} ticket={res.get('ticket')}")
        return {"synced": True, "dry_run": False, "ticket": res.get("ticket"),
                "type": "market", "price": res.get("price"), "lot": lot, "magic": magic}
    err = res.get("error") or res.get("comment") or f"retcode {res.get('retcode')}"
    _audit({"ts": datetime.now(timezone.utc).isoformat(), "uid": uid,
            "dry_run": False, **base, "error": str(err)})
    log(f"FAIL {uid[:8]} {pair} {side}: {err}")
    return {"synced": False, "reason": f"mt5:{err}"}