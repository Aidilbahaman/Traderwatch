#!/usr/bin/env python3
"""Regression tests for the phantom-fill bug (2026-10-23).

Bug class: TP/SL was evaluated WITHOUT checking that the market actually
traded through the entry level. Signal #110 (USD/CAD SELL) was reported to
members as "TP reached +20.6 pips" while price never touched entry -- entry
sat 30 pips ABOVE market and TP 9.4 pips ABOVE market at posting time.

These tests pin the entry-gate behaviour so it cannot silently return.

Run:  python3 test-phantom-fill.py
"""
import importlib.util
import sys
from pathlib import Path

ENGINE = Path("/home/ubuntu/web/Traderwatch-repo/engine")
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")

FAIL = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")
        FAIL.append(name)


def load(fname, modname):
    spec = importlib.util.spec_from_file_location(modname, ENGINE / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


# --------------------------------------------------------------- signal-status
st_mod = load("signal-status.py", "tw_status")

E, SL, TP = 1.40356, 1.4045, 1.4015
sig = {"pair": "USD/CAD", "side": "SELL", "entry": E, "sl": SL, "tp": TP,
       "timeframe": "M15", "posted_at": "2026-10-22T18:54:18.511068"}

print("signal-status.py :: evaluate()")

# #110 exactly: price drifts 1.40042..1.40080, never reaches entry 1.40356.
# Old code saw low<=tp on the first bar and returned a 20.6-pip TP win.
rows_110 = [("2026-10-22T18:54:00Z", 1.40059, 1.40055),
            ("2026-10-22T18:55:00Z", 1.40056, 1.40050),
            ("2026-10-22T18:56:00Z", 1.40069, 1.40050),
            ("2026-10-22T18:57:00Z", 1.40070, 1.40068)]
check("#110 real bars -> no verdict (was tp +20.6)",
      st_mod.evaluate(sig, rows_110)[0], None)

# A genuine SELL fill: price trades up into entry, then runs to TP.
rows_real = [("2026-10-22T19:00:00Z", 1.40300, 1.40290),
             ("2026-10-22T19:01:00Z", 1.40360, 1.40340),   # touches entry
             ("2026-10-22T19:02:00Z", 1.40250, 1.40140)]   # low <= TP
check("genuine SELL fill -> tp",
      st_mod.evaluate(sig, rows_real)[0], "tp")

# Genuine fill that stops out first.
rows_stop = [("2026-10-22T19:00:00Z", 1.40360, 1.40340),   # touches entry
             ("2026-10-22T19:01:00Z", 1.40500, 1.40460)]   # high >= SL
check("genuine SELL fill -> sl", st_mod.evaluate(sig, rows_stop)[0], "sl")

# BUY mirror: entry above market, price never climbs to it, but low <= tp.
sig_b = {"pair": "EUR/USD", "side": "BUY", "entry": 1.1226, "sl": 1.12325,
         "tp": 1.1215, "timeframe": "M15", "posted_at": "2026-10-22T18:54:34"}
rows_b = [("2026-10-22T18:54:00Z", 1.12195, 1.12190),
          ("2026-10-22T19:10:00Z", 1.12190, 1.12170)]
check("BUY never filled -> no verdict (was tp)", st_mod.evaluate(sig_b, rows_b)[0], None)

# Same bar fills and runs to SL -- conservative rule must pick SL.
rows_amb = [("2026-10-22T19:00:00Z", 1.40460, 1.40140)]
check("fill + both levels same bar -> sl (conservative)",
      st_mod.evaluate(sig, rows_amb)[0], "sl")

# --------------------------------------------------------------- lifecycle bot
lc_mod = load("signal-lifecycle-alert.py", "tw_lifecycle")

print("\nsignal-lifecycle-alert.py :: evaluate()")

# The exact live prices logged for #110: 1.40051 then 1.40050.
st = {"entry": False, "closed": None, "first_touch": None}
check("#110 poll 1 (price 1.40051) -> no events", lc_mod.evaluate(sig, 1.40051, st), [])
check("#110 after poll 1 -> entry still falsy", bool(st.get("entry")), False)
check("#110 poll 2 (price 1.40050) -> no events", lc_mod.evaluate(sig, 1.40050, st), [])
check("#110 marked void", st.get("void"), "entry_never_touched")

# A real SELL fill must still produce entry, then tp.
st2 = {"entry": False, "closed": None, "first_touch": None}
check("real SELL: entry touched -> ['entry']",
      lc_mod.evaluate(sig, 1.40360, st2), ["entry"])
check("real SELL: then tp -> ['tp']",
      lc_mod.evaluate(sig, 1.40140, st2), ["tp"])

print("\nsignal-lifecycle-alert.py :: evaluate_bars()")
st3 = {"entry": False, "closed": None, "first_touch": None}
bars_110 = [("2026-10-22T18:54:00Z", 1.40059, 1.40055),
            ("2026-10-22T18:55:00Z", 1.40056, 1.40050),
            ("2026-10-22T18:56:00Z", 1.40069, 1.40050)]
check("#110 bars -> no events", lc_mod.evaluate_bars(sig, bars_110, st3), [])
check("#110 bars -> entry still falsy", bool(st3.get("entry")), False)
check("#110 bars -> closed still None", st3.get("closed"), None)

st4 = {"entry": False, "closed": None, "first_touch": None}
bars_real = [("2026-10-22T19:00:00Z", 1.40300, 1.40290),
             ("2026-10-22T19:01:00Z", 1.40360, 1.40340),
             ("2026-10-22T19:02:00Z", 1.40250, 1.40140)]
check("real fill bars -> ['entry','tp']",
      lc_mod.evaluate_bars(sig, bars_real, st4), ["entry", "tp"])

# ------------------------------------------------------------------- void guard
print("\nsignal-lifecycle-alert.py :: void guard (no resend)")

# #110 now carries void=entry_never_touched after the fix. A repair pass must
# NOT re-send the phantom TP even though it is still inside the age window.
st_void = {"entry": False, "closed": "tp", "first_touch": None,
           "void": "entry_never_touched", "notified": []}
targets = [{"telegram_chat_id": 7696607055}]
check("repair on void signal sends nothing",
      lc_mod._repair_notify(sig, st_void, "110", targets, [7696607055],
                            dry_run=True), False)
check("void signal flagged repaired", st_void.get("legacy_repaired"), True)

# ---------------------------------------------------------------- timing label
print("\nsignal-lifecycle-alert.py :: timing label")
st5 = {"entry": True, "closed": "tp", "entry_at": "2026-10-22T18:55:00Z",
       "closed_at": "2026-10-22T18:56:00Z", "first_touch": None}
line = lc_mod._timing_line(st5, "2026-10-22T18:55:00Z", "2026-10-22T18:56:00Z")
check("timing states its source", "entry" in line, True)
check("timing shows 1m", "1m" in line, True)

# ------------------------------------------------------------------- summary
print()
if FAIL:
    print(f"FAILED: {len(FAIL)} check(s): {FAIL}")
    sys.exit(1)
print("ALL CHECKS PASSED")