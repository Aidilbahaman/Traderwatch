"""Validasi Elliot Wave — 8 gelombang penuh + ratio Fibonacci.

Reka bentuk:
  - _impulse_ok()   : 3 peraturan wajib (hard rules) + skor Fibonacci
  - _corrective_ok(): sahkan koreksi A-B-C
  - score_cycle()   : markah 0-100 untuk kitaran 8 gelombang
  - label_waves()   : cari kitaran TERBAIK (skor tertinggi), bukan pertama
"""

# Rujukan ratio Fibonacci yang biasa dilihat dalam kitaran Elliot
FIB_W2 = (0.382, 0.618, 0.786)      # retrace Wave 2 dari Wave 1
FIB_W3 = (1.618, 2.618)             # sambungan Wave 3 dari Wave 1
FIB_W4 = (0.236, 0.382, 0.5)        # retrace Wave 4 dari Wave 3
FIB_ABC = (0.382, 0.618, 1.0)       # retrace Wave B dari Wave A


def _near(x, targets, tol=0.12):
    """True kalau x dekat mana-mana target Fibonacci (±tol relatif)."""
    return any(abs(x - t) <= tol for t in targets)


def _hard_rules(p, up):
    """3 peraturan WAJIB Elliot. Return (ok, sebab)."""
    p0, p1, p2, p3, p4, p5 = [x[1] for x in p[:6]]
    if up:
        if p2 <= p0:
            return False, "R1: Wave 2 jatuh bawah mula Wave 1"
        if p3 <= p1:
            return False, "R2: Wave 3 tidak melebihi hujung Wave 1"
        if p4 <= p1:
            return False, "R3: Wave 4 masuk wilayah Wave 1"
        l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
    else:
        if p2 >= p0:
            return False, "R1: Wave 2 melebihi mula Wave 1"
        if p3 >= p1:
            return False, "R2: Wave 3 tidak melebihi hujung Wave 1"
        if p4 >= p1:
            return False, "R3: Wave 4 masuk wilayah Wave 1"
        l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
    if l3 <= l1 and l3 <= l5:
        return False, "R4: Wave 3 gelombang terpendek"
    return True, "3 peraturan wajib lulus"


def fib_score(p, up):
    """Markah Fibonacci 0-100 + senarai nota. Guideline, bukan wajib."""
    p0, p1, p2, p3, p4, p5 = [x[1] for x in p[:6]]
    w1 = abs(p1 - p0)
    w3 = abs(p3 - p2)
    if w1 <= 0 or w3 <= 0:
        return 0, ["panjang gelombang sifar"]

    score, notes = 0, []
    # Wave 2 retrace dari Wave 1
    r2 = abs(p2 - p1) / w1
    if _near(r2, FIB_W2):
        score += 25
        notes.append(f"W2 retrace {r2:.3f} ✓ fib")
    else:
        notes.append(f"W2 retrace {r2:.3f} (luar fib)")
    # Wave 3 vs Wave 1
    r3 = w3 / w1
    if r3 >= FIB_W3[0]:
        score += 25
        notes.append(f"W3 = {r3:.3f}x W1 ✓ fib")
    elif r3 >= 1.0:
        score += 12
        notes.append(f"W3 = {r3:.3f}x W1 (sekadar >1)")
    else:
        notes.append(f"W3 = {r3:.3f}x W1 (lemah)")
    # Wave 4 retrace dari Wave 3, tidak bertindih Wave 1
    r4 = abs(p4 - p3) / w3
    if _near(r4, FIB_W4):
        score += 25
        notes.append(f"W4 retrace {r4:.3f} ✓ fib")
    else:
        notes.append(f"W4 retrace {r4:.3f} (luar fib)")
    # Wave 5 vs Wave 1 (sering sama panjang atau 0.618/1.618)
    w5 = abs(p5 - p4)
    r5 = w5 / w1
    if _near(r5, (0.618, 1.0, 1.618), 0.15):
        score += 25
        notes.append(f"W5 = {r5:.3f}x W1 ✓ fib")
    else:
        notes.append(f"W5 = {r5:.3f}x W1 (luar fib)")
    return score, notes


def _abc_ok(p, up):
    """Sahkan koreksi A-B-C selepas impulse. p = pivot 5,6,7."""
    if len(p) < 3:
        return False, "koreksi tidak lengkap", 0
    a, b, c = [x[1] for x in p[:3]]
    p5 = None
    score, notes = 0, []
    # Untuk impulse naik, koreksi turun: A < W5, B < mula A, C < B
    if up:
        if not (a < b and c < b):
            return False, "bentuk A-B-C tidak konsisten", 0
    else:
        if not (a > b and c > b):
            return False, "bentuk A-B-C tidak konsisten", 0
    rb = abs(b - a) / max(abs(a), 1e-9) if False else None
    return True, "koreksi A-B-C sah", score


def score_cycle(pivots, start):
    """Nilai kitaran 8 gelombang dari indeks start. Return (skor, sebab, up)."""
    if len(pivots) < start + 8:
        return -1, "pivot tidak cukup untuk 8 gelombang", None
    win = pivots[start:start + 8]
    up = win[0][2] == "L"
    ok, why = _hard_rules(win, up)
    if not ok:
        return -1, why, up
    fs, notes = fib_score(win, up)
    # Bonus bentuk koreksi
    ok_abc, abc_why, _ = _abc_ok(win[5:8], up)
    abc_bonus = 15 if ok_abc else 0
    total = fs + abc_bonus
    reason = (f"{why} · fib {fs}/100"
              + (" · A-B-C sah" if ok_abc else " · A-B-C lemah"))
    return total, reason, up


def label_waves(pivots, validate=True, min_score=50):
    """Label kitaran Elliot TERBAIK (8 gelombang), bukan yang pertama jumpa."""
    empty = ([(p[0], p[1], p[2], "?") for p in pivots],
             "TIDAK SAH — tiada kitaran 8-gelombang")
    if not validate or len(pivots) < 8:
        LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C", "D", "E"]
        return ([(p[0], p[1], p[2], LABELS[i % len(LABELS)])
                 for i, p in enumerate(pivots)], None)

    best = (-1, None, None)   # (skor, start, sebab)
    for start in range(len(pivots) - 8, -1, -1):
        sc, why, up = score_cycle(pivots, start)
        if sc > best[0]:
            best = (sc, start, why)
    sc, start, why = best

    if start is None or sc < min_score:
        detail = why or "skor terlalu rendah"
        return empty[0], f"TIDAK SAH — {detail} (skor {sc if sc >= 0 else 0})"

    # Label 8 gelombang: 0-5 impulse, A-B-C koreksi
    LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C"]
    out = [(p[0], p[1], p[2], LABELS[i])
           for i, p in enumerate(pivots[start:start + 9])]
    grade = "A" if sc >= 85 else ("B" if sc >= 70 else "C")
    return out, f"SAH (grade {grade}, skor {sc}/100) · {why}"
