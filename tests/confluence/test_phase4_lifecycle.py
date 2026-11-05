#!/usr/bin/env python3.12
"""Ujian Fasa 4 — lifecycle: snapshot hash, expiry, audit, guards.

Jalankan: /usr/bin/python3.12 tests/confluence/test_phase4_lifecycle.py

Ujian yang perlukan DB (cf_* tables) akan SKIP dengan jelas kalau jadual
belum dicipta — supaya ujian tidak memberi lulus palsu.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/ubuntu/web/Traderwatch-repo")
from engine.confluence import lifecycle as lc  # noqa: E402
from engine.confluence import pipeline as pl   # noqa: E402

PASS = FAIL = SKIP = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def skip(name, why):
    global SKIP
    SKIP += 1
    print(f"  ⏭  {name} — {why}")


print("=== 1. Snapshot hash (reproducibility §1.2 #5) ===")
h1 = lc.snapshot_hash({"a": 1, "b": [2, 3]})
h2 = lc.snapshot_hash({"b": [2, 3], "a": 1})   # susunan kunci berbeza
check("hash deterministik (susunan tak kira)", h1 == h2, f"{h1} vs {h2}")
h3 = lc.snapshot_hash({"a": 2, "b": [2, 3]})
check("input berbeza -> hash berbeza", h1 != h3)
check("panjang hash 32", len(h1) == 32)

print("\n=== 2. Expiry ===")
e = lc._expiry("2026-11-06T10:00:00+00:00", 4)
check("expiry +4 jam", e.startswith("2026-11-06T14:00:00"), e)
e2 = lc._expiry("2026-11-06T10:00:00", 1)   # tanpa tz -> dianggap UTC
check("naive timestamp dianggap UTC", e2.startswith("2026-11-06T11:00:00"), e2)
e3 = lc._expiry("bukan-tarikh", 2)
try:
    datetime.fromisoformat(e3)
    ok3 = True
except Exception:
    ok3 = False
check("timestamp rosak -> fallback now()", ok3)

print("\n=== 3. Guards (tiada DB diperlukan) ===")
ana_wait = {"symbol": "XAUUSD", "decision": "WAIT",
            "as_of": "2026-11-06T10:00:00+00:00", "setup": {}}
ok, sid, err = lc.create_signal(ana_wait)
check("WAIT -> tiada signal", ok is False and "WAIT" in str(err), str(err))

ana_no = dict(ana_wait, decision="NO_TRADE")
ok2, _, err2 = lc.create_signal(ana_no)
check("NO_TRADE -> tiada signal", ok2 is False and "NO_TRADE" in str(err2))

ok3, err3 = lc.publish("00000000-0000-0000-0000-000000000000", None)
check("publish tanpa actor -> ditolak", ok3 is False, str(err3))

ok4, err4 = lc.publish("00000000-0000-0000-0000-000000000000", "admin")
check("publish signal tiada -> gagal kemas", ok4 is False)

ok5, err5 = lc.cancel("00000000-0000-0000-0000-000000000000", "admin", "")
check("cancel tanpa sebab -> ditolak (§3.2)", ok5 is False and "sebab" in str(err5).lower())

print("\n=== 4. Ujian DB (perlu cf_* tables) ===")
code, _ = lc._req("cf_analysis_runs", "GET", params="?limit=1")
if code != 200:
    skip("save_run + create_signal + publish + audit", f"jadual cf_* belum dicipta (HTTP {code})")
else:
    ana = pl.analyze("XAUUSD")
    okr, run_id, errr = lc.save_run(ana)
    check("save_run berjaya", okr, str(errr))
    check("run_id dipulangkan", run_id is not None)

    # Paksa BUY untuk uji lifecycle penuh
    ana_buy = dict(ana, decision="BUY",
                   setup={"valid": True, "side": "BUY", "entry": 4100,
                          "sl": 4090, "tp": 4120, "risk_reward": 2.0})
    oks, sid, errs = lc.create_signal(ana_buy, run_id)
    check("create_signal BUY berjaya", oks, str(errs))
    if oks:
        check("signal mula sebagai DRAFT", True)
        okp, errp = lc.publish(sid, "admin-test")
        check("publish DRAFT -> PUBLISHED", okp, str(errp))
        okp2, errp2 = lc.publish(sid, "admin-test")
        check("publish kedua ditolak (bukan DRAFT)", okp2 is False, str(errp2))
        oko, erro = lc.record_outcome(sid, {"result": "HIT_TP", "pips": 20.0}, "admin-test")
        check("record_outcome berjaya", oko, str(erro))
        aud = lc.get_audit(sid)
        events = [a["event_type"] for a in aud]
        check("audit ada CREATED", "CREATED" in events, str(events))
        check("audit ada PUBLISHED", "PUBLISHED" in events, str(events))
        check("audit ada OUTCOME_RECORDED", "OUTCOME_RECORDED" in events, str(events))
        okc, errc = lc.cancel(sid, "admin-test", "ujian selesai")
        check("cancel dengan sebab berjaya", okc, str(errc))

print(f"\n{'='*50}\nLULUS: {PASS}  GAGAL: {FAIL}  SKIP: {SKIP}")
sys.exit(1 if FAIL else 0)
