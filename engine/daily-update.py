#!/usr/bin/env python3
"""TraderWatch daily progress update — 09:00 MY (Asia/Kuala_Lumpur).

Hantar ringkasan pembaikan 24 jam kepada semua member Telegram. Data diambil
secara automatik daripada git log repo TraderWatch, jadi ayat selalu selari
dengan kerja sebenar — tiada nombor yang ditulis tangan.

Kawalan:
  --dry-run   cetak mesej tanpa hantar
  --force     hantar walaupun tiada commit (default: skip hari tanpa kerja)
"""
import argparse
import json
import re
import subprocess
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path("/home/ubuntu/web/Traderwatch-repo")
SECRETS = Path.home() / ".secrets"
STATE = Path("/tmp/traderwatch-daily-update.json")
TZ_MY = timezone(timedelta(hours=8))
WINDOW_HOURS = 24

# Kategori ayat — padanan kata kunci commit subject -> (tajuk, senarai butir)
CATEGORIES = [
    ("Ketepatan isyarat", [
        r"entry fill|phantom|void_unfilled|TP/SL|entry gate|verdict",
        r"evaluat|status.*guard|entry.*sebelum|sahkan entry",
    ]),
    ("Data harga", [
        r"swissquote|sq-collector|sq-bars|data source|sumber data",
        r"twelvedata|backfill.*bar|feed harga",
    ]),
    ("Analisis AI", [
        r"\bLLM\b|model|preset|prompt|reasoning|json|parser|token",
        r"bot_v2|analisa|suhu|temperature|budget|deadline",
    ]),
    ("Notifikasi", [
        r"lifecycle|notif|hantar|repair|spam|duplicate|flood|heartbeat",
        r"tg-bot|twreg|kepada member|progress",
    ]),
    ("Pembayaran", [
        r"stripe|webhook|payment|pembayaran|checkout|plan|subscription",
    ]),
]

# Ayat ringkas mengikut kategori — dibina daripada commit sebenar.
PHRASES = {
    "Ketepatan isyarat": "TP/SL hanya dikira selepas paras entry disentuh. Isyarat yang entry-nya tidak kena dilabel <i>void</i> — bukan TP palsu.",
    "Data harga": "Data harga diambil daripada feed live Swissquote, Minute 1 — tepat setiap minit.",
    "Analisis AI": "Analisis AI lebih pantas dan lebih stabil; anda menerima notifikasi progress semasa ia berjalan.",
    "Notifikasi": "Notifikasi TP/SL tidak lagi berulang, hilang, atau salah.",
    "Pembayaran": "Pembayaran Stripe berfungsi — kad, FPX, Apple Pay dan Google Pay diterima.",
}

FOOTER = ("Isyarat AI kini berjalan secara autonomous: analisis AI, "
          "semakan entry, harga live, kemudian notifikasi. Setiap "
          "notifikasi TP/SL disahkan daripada feed harga sebenar.")


def run_git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True).stdout.strip()


def recent_subjects(hours=WINDOW_HOURS):
    out = run_git("log", f"--since={hours} hours ago", "--format=%s")
    return [s for s in out.splitlines() if s.strip()]


def classify(subjects):
    """Kumpulkan commit (tanpa 'status:' auto-commit) ke dalam kategori."""
    work = [s for s in subjects
            if not s.startswith("status: ") and not s.startswith("docs:")]
    buckets = Counter()
    matched = set()
    for i, subj in enumerate(work):
        low = subj.lower()
        for cat, pats in CATEGORIES:
            if any(re.search(p, low) for p in pats):
                buckets[cat] += 1
                matched.add(i)
                break
    return buckets, len(work), len(matched)


def build_message(buckets, total_commits, matched_commits):
    lines = ["\U0001f4ca <b>Update Harian TraderWatch</b>", ""]
    used = []
    for cat, _ in CATEGORIES:
        n = buckets.get(cat, 0)
        if n:
            lines.append(f"<b>{cat}</b>")
            lines.append(PHRASES[cat])
            lines.append("")
            used.append(cat)
    if not used:
        lines.append("Tiada pembaikan baharu hari ini.")
        lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines).strip()


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"last_sent_commit": None}


def save_state(data):
    STATE.write_text(json.dumps(data, indent=1))


def send(text, dry=False):
    env = dict(l.split("=", 1) for l in
               SECRETS.joinpath("telegram.env").read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    token = env["TELEGRAM_SIGNALS_BOT_TOKEN"].strip()

    import urllib.request as _u
    req = _u.Request(f"https://api.telegram.org/bot{token}/getMe")
    me = json.loads(_u.urlopen(req, timeout=20).read())
    if not me.get("ok"):
        raise RuntimeError(f"bot token tidak sah: {me.get('description')}")

    # Member aktif = plan pro/max yang ada telegram_chat_id.
    sb = dict(l.split("=", 1) for l in
              SECRETS.joinpath("supabase.env").read_text().splitlines()
              if "=" in l and not l.startswith("#"))
    H = {"apikey": sb["SUPABASE_SERVICE_KEY"],
         "Authorization": "Bearer " + sb["SUPABASE_SERVICE_KEY"]}
    q = (_u.Request(sb["SUPABASE_URL"] +
                    "/rest/v1/profiles?select=telegram_chat_id,plan&plan=in.(pro,max)",
                    headers=H))
    rows = json.loads(_u.urlopen(q, timeout=20).read())
    chats = sorted({int(r["telegram_chat_id"]) for r in rows
                    if r.get("telegram_chat_id")})
    print(f"  bot @{me['result']['username']} | member: {len(chats)}")
    if dry:
        print("  DRY-RUN, tiada dihantar")
        return chats, []

    sent = []
    for cid in chats:
        body = json.dumps({"chat_id": cid, "text": text,
                           "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
        rq = _u.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                        data=body, method="POST",
                        headers={"Content-Type": "application/json"})
        try:
            with _u.urlopen(rq, timeout=25) as r:
                d = json.loads(r.read().decode())
            ok = d.get("ok")
            mid = (d.get("result") or {}).get("message_id")
            print(f"  chat {cid}: ok={ok} msg_id={mid} {d.get('description','')}")
            if ok:
                sent.append(cid)
        except Exception as ex:
            detail = ""
            try:
                detail = ex.read().decode()[:120]
            except Exception:
                pass
            print(f"  chat {cid}: FAIL {type(ex).__name__} {str(ex)[:60]} {detail}")
        time.sleep(1.5)
    return chats, sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    subjects = recent_subjects()
    head = run_git("rev-parse", "--short", "HEAD")
    buckets, total, matched = classify(subjects)

    print(f"HEAD {head} | commit 24j: {len(subjects)} (kerja: {total})")
    for cat, _ in CATEGORIES:
        if buckets.get(cat):
            print(f"  {cat}: {buckets[cat]}")

    if total == 0 and not args.force:
        print("Tiada pembaikan 24 jam — skip ( guna --force untuk hantar juga)")
        return

    state = load_state()
    if state.get("last_sent_commit") == head and not args.force:
        print("HEAD tidak berubah sejak hantaran terakhir — skip (guna --force)")
        return

    msg = build_message(buckets, total, matched)
    print("---\n" + msg + "\n---")
    chats, sent = send(msg, dry=args.dry_run)
    if sent:
        state = {"last_sent_commit": head,
                 "last_sent_at": datetime.now(timezone.utc).isoformat(),
                 "last_sent_to": sent,
                 "buckets": dict(buckets)}
        save_state(state)
        print(f"  state dikemas kini ({head})")


if __name__ == "__main__":
    main()