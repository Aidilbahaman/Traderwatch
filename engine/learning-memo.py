#!/usr/bin/env python3
"""Learning memo + performance gate untuk TraderWatch signals bot.

- Kata daripada signal-status.json (semua closed setups, pips-unit sahaja).
- Hasilkan state/learning-memo.json:
    gates   : pair/session disekat (WR < 25% atau net <= -25 pips, min 5 setups)
    memo    : teks ringkas untuk disuntik ke PROMPT LLM bot (learn from mistakes)
- Jalankan oleh cron setiap 5 minit selepas signal-status.py.

Usage: python3.12 engine/learning-memo.py
"""
import json
import pathlib
from collections import defaultdict

REPO = pathlib.Path("/home/ubuntu/web/Traderwatch-repo")
STATUS = REPO / "signal-status.json"
OUT = REPO / "state" / "learning-memo.json"
MIN_N = 5          # minimum closed setups sebelum pair disekat
WR_FLOOR = 25.0    # % — bawah ini disekat
NET_FLOOR = -25.0  # pips — bawah ini disekat
SESSION_RANGE = {"Asia": (0, 7), "London": (8, 15), "NY": (16, 23)}


def session_of(hour):
    for name, (lo, hi) in SESSION_RANGE.items():
        if lo <= hour <= hi:
            return name
    return "?"


def load_closed():
    d = json.loads(STATUS.read_text())
    out = []
    for k, v in (d.get("signals") or {}).items():
        if v.get("status") not in ("tp", "sl", "collected"):
            continue
        if str(v.get("unit") or "pips").lower() == "usd":
            continue
        pair = k.split("_")[0]
        # entry_at dalam MYT; hanya jam diperlukan
        hour = None
        ea = v.get("entry_at") or v.get("closed") or ""
        try:
            hour = int(ea[11:13])
        except Exception:
            pass
        out.append({
            "pair": pair,
            "status": v.get("status"),
            "pips": v.get("pips") or 0.0,
            "r": v.get("r"),
            "session": session_of(hour) if hour is not None else "?",
            "key": k,
        })
    out.sort(key=lambda x: x["key"])
    return out


def wr_net(rows):
    n = len(rows)
    w = sum(1 for x in rows if x["pips"] > 0)
    net = sum(x["pips"] for x in rows)
    return (100.0 * w / n if n else 0.0), net, n


def build(rows):
    by_pair = defaultdict(list)
    by_ps = defaultdict(list)  # (pair, session)
    for x in rows:
        by_pair[x["pair"]].append(x)
        by_ps[(x["pair"], x["session"])].append(x)

    gates, notes = {}, []
    for pair, rs in sorted(by_pair.items()):
        wr, net, n = wr_net(rs)
        recent = rs[-20:]
        rwr, rnet, _ = wr_net(recent)
        blocked = n >= MIN_N and (wr < WR_FLOOR or net < NET_FLOOR)
        if blocked:
            gates.setdefault("pairs", []).append(pair)
        line = (f"{pair}: {n} closed, WR {wr:.0f}%, net {net:+.1f} pips "
                f"(last20: WR {rwr:.0f}%, {rnet:+.1f})")
        if blocked:
            line += " -> GATED (jangan hasilkan setup pair ini sehingga review)"
        elif rwr < WR_FLOOR and len(recent) >= MIN_N:
            line += " -> CAUTION (recent form lemah, hanya ambil setup grade A+ sahaja)"
        notes.append(line)

    sess_notes = []
    for s in ("Asia", "London", "NY"):
        rs = [x for x in rows if x["session"] == s]
        if len(rs) >= MIN_N:
            wr, net, n = wr_net(rs)
            sess_notes.append(f"{s}: n={n}, WR {wr:.0f}%, net {net:+.1f} pips")

    memo = (
        "PERFORMANCE MEMO (auto dari closed setups):\n"
        + "\n".join(notes)
        + "\nSESI (MYT): " + " | ".join(sess_notes)
        + "\nARAHAN: Elakkan pair yang GATED. Utamakan sesi London; "
        "berhati-hati sesi Asia (WR terendah). Pastikan RR1 >= 1.5 dan "
        "hanya grade A+/A. Belajar daripada losses lalu — jangan ulang "
        "pola yang sama (contoh: NZD counter-trend sesi Asia)."
    )
    return {"updated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "gates": gates, "memo": memo, "n_analyzed": len(rows)}


def main():
    rows = load_closed()
    if not rows:
        OUT.write_text(json.dumps({"updated": None, "gates": {}, "memo": "no closed data"}, indent=1))
        print("no closed data")
        return
    res = build(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    tmp.replace(OUT)
    print(f"memo ok: n={res['n_analyzed']}, gates={res['gates'].get('pairs', [])}")


if __name__ == "__main__":
    main()
