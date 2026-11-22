"""AI closed-loop learning: baca hasil TP/SL sebenar client dari paper_trades,
agregat ikut corak setup (TF, BOS, CHoCH, conf), dan jana 'lessons' ringkas
yang disuap balik ke prompt vision supaya model elak corak yang selalu SL.

Tiada training model — ini retrieval-augmented: fakta statistik dari data
sebenar, dikemas kini setiap jam (cache), dan dimasukkan sebagai konteks.
"""
import json
import pathlib
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
_cache = {"at": 0, "lessons": "", "stats": None}
CACHE_TTL = 3600
MIN_N = 4          # corak perlu >= 4 trade baru boleh dipercayai


def _sec():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


def _rows():
    sec = _sec()
    url = sec["SUPABASE_URL"].rstrip("/")
    req = urllib.request.Request(
        url + "/rest/v1/paper_trades?select=pair,side,status,ai_tf,ai_bos,ai_choch,ai_conf,ai_rr,ai_hour&status=in.(tp,sl)&ai_conf=not.is.null&limit=2000",
        headers={"apikey": sec["SUPABASE_SERVICE_KEY"],
                 "Authorization": "Bearer " + sec["SUPABASE_SERVICE_KEY"]})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r) or []


def _bucket(r):
    """Kunci corak: TF + arah + BOS searah? + CHoCH + jalur conf."""
    tf = (r.get("ai_tf") or "M15").upper()
    side = (r.get("side") or "").upper()
    bos = (r.get("ai_bos") or "RANGE").upper()
    aligned = (side == "BUY" and bos == "UP") or (side == "SELL" and bos == "DOWN")
    choch = bool(r.get("ai_choch"))
    conf = float(r.get("ai_conf") or 0)
    band = "high" if conf >= 0.6 else ("mid" if conf >= 0.4 else "low")
    return (tf, side, "aligned" if aligned else "counter", "choch" if choch else "nochoch", band)


def calibration(min_n=3):
    """Uji sama ada confidence AI JUIUR: bila AI cakap 70%, adakah betul 70% menang?

    Return list of bands {band, stated, actual, n} — stated = purata conf,
    actual = win-rate sebenar. Jika actual jauh < stated, conf tidak boleh dipercayai.
    """
    rows = _rows()
    bands = {}
    for r in rows:
        conf = float(r.get("ai_conf") or 0)
        if conf <= 0:
            continue
        # ai_conf disimpan sebagai 0..1 (lama) atau 0..100 (baru) — normalkan ke 0..1
        if conf > 1.0:
            conf = conf / 100.0
        lo = int(round(conf * 10)) * 10   # 50,60,70 ...
        key = f"{lo}-{lo + 10}%"
        b = bands.setdefault(key, {"stated": [], "tp": 0, "n": 0})
        b["stated"].append(conf)
        b["n"] += 1
        b["tp"] += 1 if r.get("status") == "tp" else 0
    out = []
    for k in sorted(bands):
        b = bands[k]
        if b["n"] < min_n:
            continue
        out.append({"band": k,
                    "stated": round(sum(b["stated"]) / len(b["stated"]) * 100, 1),
                    "actual": round(100.0 * b["tp"] / b["n"], 1),
                    "n": b["n"]})
    return out


def calibration_note():
    """Teks ringkas untuk suntik ke prompt: band yang AI selalu terlebih yakin."""
    cal = calibration()
    if not cal:
        return ""
    over = [c for c in cal if c["actual"] + 8 < c["stated"]]
    under = [c for c in cal if c["actual"] > c["stated"] + 8]
    parts = []
    if over:
        parts.append("CAUTION — you have been OVERCONFIDENT on these bands: " + "; ".join(
            f"{c['band']} you said {c['stated']:.0f}% but only {c['actual']:.0f}% won (n={c['n']})"
            for c in over[:3]) + ".")
    if under:
        parts.append("Underconfident (safe to trust more): " + "; ".join(
            f"{c['band']} said {c['stated']:.0f}% actual {c['actual']:.0f}% (n={c['n']})"
            for c in under[:2]) + ".")
    return " ".join(parts)


def compute():
    rows = _rows()
    agg = defaultdict(lambda: [0, 0])   # bucket -> [tp, sl]
    overall = [0, 0]
    for r in rows:
        b = _bucket(r)
        win = 1 if r.get("status") == "tp" else 0
        agg[b][0] += win
        agg[b][1] += 1 - win
        overall[0] += win
        overall[1] += 1 - win
    good, bad = [], []
    for b, (tp, sl) in agg.items():
        n = tp + sl
        if n < MIN_N:
            continue
        wr = tp / n
        tf, side, align, ch, band = b
        label = f"{tf} {side} {align} {ch} conf-{band}"
        if wr >= 0.6:
            good.append((wr, n, label))
        elif wr <= 0.35:
            bad.append((wr, n, label))
    good.sort(key=lambda x: (-x[0], -x[1]))
    bad.sort(key=lambda x: (x[0], -x[1]))
    parts = []
    if overall[0] + overall[1] >= MIN_N:
        parts.append(f"Overall {overall[0]}TP/{overall[1]}SL "
                     f"({100*overall[0]/(overall[0]+overall[1]):.0f}% win, n={overall[0]+overall[1]}).")
    if good:
        parts.append("PROVEN patterns (favour): " + "; ".join(
            f"{lab} {100*wr:.0f}% win n={n}" for wr, n, lab in good[:3]) + ".")
    if bad:
        parts.append("AVOID patterns (historically SL-prone): " + "; ".join(
            f"{lab} {100*wr:.0f}% win n={n}" for wr, n, lab in bad[:3]) + ".")
    lessons = " ".join(parts)
    stats = {"tp": overall[0], "sl": overall[1],
             "good": [{"label": l, "win": round(w, 2), "n": n} for w, n, l in good[:4]],
             "bad": [{"label": l, "win": round(w, 2), "n": n} for w, n, l in bad[:4]]}
    return lessons, stats


def lessons():
    now = time.time()
    if now - _cache["at"] < CACHE_TTL and _cache["lessons"] is not None:
        return _cache["lessons"], _cache["stats"]
    try:
        l, st = compute()
    except Exception:
        l, st = "", None
    _cache.update(at=now, lessons=l, stats=st)
    return l, st


if __name__ == "__main__":
    l, st = compute()
    print("LESSONS:", l or "(belum cukup data)")
    print(json.dumps(st, indent=1))
