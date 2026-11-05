"""Validasi Elliot Wave — 8 gelombang + Fibonacci + bentuk koreksi.

Reka bentuk:
  - _hard_rules()    : 4 peraturan WAJIB Elliot
  - fib_score()      : guideline Fibonacci (0-100)
  - classify_abc()   : kenal bentuk koreksi (zigzag / flat / triangle)
  - score_cycle()    : markah penuh satu kitaran 8 gelombang
  - label_waves()    : cari kitaran TERBAIK, bukan pertama

Nota penting:
  Wave 6/7/8 dalam senarai pivot ialah A/B/C bagi koreksi selepas impulse.
  Koreksi TIDAK semestinya bertentangan arah sepenuhnya — flat & triangle
  boleh retrace cetek atau menyamping. Jangan tolak kerana sebab itu.
"""

# Ratio Fibonacci rujukan
FIB_W2 = (0.382, 0.5, 0.618, 0.786)     # retrace Wave 2 dari Wave 1
FIB_W4 = (0.236, 0.382, 0.5)            # retrace Wave 4 dari Wave 3
FIB_W5 = (0.618, 1.0, 1.272, 1.618)     # Wave 5 vs Wave 1
FIB_B = (0.382, 0.5, 0.618, 0.786, 1.0)  # retrace Wave B dari Wave A
FIB_C = (0.618, 1.0, 1.236, 1.618)      # Wave C vs Wave A


def _near(x, targets, tol=0.12):
    """True kalau x hampir mana-mana target Fibonacci (±tol absolut)."""
    return any(abs(x - t) <= tol for t in targets)


# Jarak bar minimum antara pivot supaya "gelombang" ada masa sebenar.
# H1: 1 bar = 1 jam. Gelombang Elliot tidak boleh selesai dalam 1-2 bar
# apabila gelombang lain ambil 50 bar — itu bunyi (noise), bukan struktur.
# Jarak bar minimum. Gelombang utama (0->1, 2->3, 4->5) perlu masa;
# sub-gelombang kecil (1->2, 3->4) boleh lebih pendek. Kajian teori:
# gelombang 1 dan 3 biasanya paling memakan masa dalam kitaran impulse.
MIN_BARS_MAIN = 3     # gelombang 1, 3, 5
MIN_BARS_SUB = 2      # gelombang 2, 4, dan B


def _time_ok(p):
    """True kalau setiap gelombang ada jarak masa munasabah.

    Tanpa semakan ini, ZigZag pada H1 boleh tanda gelombang "1 jam" sebagai
    struktur Elliot — mustahil kerana gelombang lain mengambil berpuluh bar.
    Gelombang impulse utama perlu >= MIN_BARS_MAIN bar; sub-gelombang >= MIN_BARS_SUB.
    """
    idx = [x[0] for x in p[:9]]
    # (gelombang, minimum bar): 0->1 (W1), 1->2 (W2), 2->3 (W3), 3->4 (W4), 4->5 (W5), 5->6 (A), 6->7 (B), 7->8 (C)
    req = [MIN_BARS_MAIN, MIN_BARS_SUB, MIN_BARS_MAIN, MIN_BARS_SUB,
           MIN_BARS_MAIN, MIN_BARS_SUB, MIN_BARS_SUB, MIN_BARS_SUB]
    for i in range(1, len(idx)):
        gap = idx[i] - idx[i - 1]
        need = req[i - 1]
        if gap < need:
            return False, f"gelombang {i-1}->{i} hanya {gap} bar (perlu {need})"
    return True, "jarak masa munasabah"


def _hard_rules(p, up):
    """4 peraturan WAJIB Elliot. Return (ok, sebab).

    Rasional setiap peraturan dinyatakan supaya kegagalan mudah difahami.
    """
    if len(p) < 6:
        return False, "pivot tidak cukup"
    p0, p1, p2, p3, p4, p5 = [x[1] for x in p[:6]]
    if up:
        # R1: Wave 2 tak boleh retrace >100% Wave 1
        if p2 <= p0:
            return False, "R1: Wave 2 retrace penuh Wave 1"
        # R2: Wave 3 mesti melebihi hujung Wave 1
        if p3 <= p1:
            return False, "R2: Wave 3 tak capai hujung Wave 1"
        # R3: Wave 4 tak boleh bertindih wilayah Wave 1
        if p4 <= p1:
            return False, "R3: Wave 4 bertindih wilayah Wave 1"
        l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
    else:
        if p2 >= p0:
            return False, "R1: Wave 2 retrace penuh Wave 1"
        if p3 >= p1:
            return False, "R2: Wave 3 tak capai hujung Wave 1"
        if p4 >= p1:
            return False, "R3: Wave 4 bertindih wilayah Wave 1"
        l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
    # R4: Wave 3 tak boleh jadi terpendek antara 1,3,5
    if l1 <= 0 or l3 <= 0 or l5 <= 0:
        return False, "R4: panjang gelombang tidak sah"
    if l3 < l1 and l3 < l5:
        return False, "R4: Wave 3 gelombang terpendek"
    return True, "4 peraturan wajib lulus"


def fib_score(p, up):
    """Markah Fibonacci 0-100. Return (skor, nota, senarai ratio)."""
    p0, p1, p2, p3, p4, p5 = [x[1] for x in p[:6]]
    w1, w3 = abs(p1 - p0), abs(p3 - p2)
    if w1 <= 0 or w3 <= 0:
        return 0, ["panjang gelombang sifar"], {}

    score, notes, ratios = 0, [], {}
    r2 = abs(p2 - p1) / w1
    ratios["r2"] = r2
    if _near(r2, FIB_W2):
        score += 25
        notes.append(f"W2 retrace {r2:.3f} ✓")
    else:
        notes.append(f"W2 retrace {r2:.3f} ✗")

    r3 = w3 / w1
    ratios["r3"] = r3
    if r3 >= 1.618:
        score += 25
        notes.append(f"W3 {r3:.3f}x W1 ✓ extended")
    elif r3 >= 1.0:
        score += 14
        notes.append(f"W3 {r3:.3f}x W1 ~ cukup")
    else:
        notes.append(f"W3 {r3:.3f}x W1 ✗ lemah")

    r4 = abs(p4 - p3) / w3
    ratios["r4"] = r4
    if _near(r4, FIB_W4):
        score += 25
        notes.append(f"W4 retrace {r4:.3f} ✓")
    else:
        notes.append(f"W4 retrace {r4:.3f} ✗")

    r5 = abs(p5 - p4) / w1
    ratios["r5"] = r5
    if _near(r5, FIB_W5, 0.15):
        score += 25
        notes.append(f"W5 {r5:.3f}x W1 ✓")
    else:
        notes.append(f"W5 {r5:.3f}x W1 ✗")
    return score, notes, ratios


def classify_abc(w5, a, b, c, up):
    """Kenal bentuk koreksi selepas impulse.

    Pulangan: (nama_bentuk, skor 0-25, nota)

    Bentuk yang sah dalam teori Elliot:
      - ZigZag   : B retrace cetek (0.382-0.618 A), C > A
      - Flat     : B retrace hampir penuh (>=0.9 A), C ~ saiz A
      - Triangle : B retrace sederhana, C < A (menyempit)

    Koreksi TIDAK semestinya melebihi harga Wave 5. Yang penting bentuk
    dalaman A-B-C konsisten, bukan arah mutlak.
    """
    la = abs(a - w5)      # panjang Wave A
    lb = abs(b - a)       # panjang Wave B
    lc = abs(c - b)       # panjang Wave C
    if la <= 0:
        return "tidak sah", 0, "panjang Wave A sifar"

    rb = lb / la
    rc = lc / la
    note = f"A={la:.5g} B/A={rb:.3f} C/A={rc:.3f}"

    # Semakan bentuk: nombor mesti masuk akal dulu
    if not (0.15 <= rb <= 1.5):
        return "tidak sah", 0, f"B retrace luar julat ({note})"

    # ZigZag: B cetek, C lanjut melebihi A
    if 0.3 <= rb <= 0.7 and rc >= 0.9:
        return "ZigZag", 22, f"bentuk ZigZag ({note})"
    # Flat: B hampir penuh
    if rb >= 0.85 and 0.7 <= rc <= 1.4:
        return "Flat", 22, f"bentuk Flat ({note})"
    # Triangle: menyempit
    if rb >= 0.4 and rc < 0.75:
        return "Triangle", 18, f"bentuk Triangle ({note})"
    # Kombinasi longgar — masih koreksi, cuma kurang kemas
    if 0.2 <= rb <= 1.0 and 0.4 <= rc <= 1.8:
        return "Koreksi longgar", 12, f"koreksi longgar ({note})"
    return "tidak sah", 0, f"bentuk koreksi tidak dikenali ({note})"


def score_cycle(pivots, start):
    """Nilai kitaran 8 gelombang dari indeks start.

    Kitaran = 6 pivot impulse (0-5) + 2 pivot koreksi (A, B) + 1 penutup (C).
    Return (skor, sebab, up, butiran).
    """
    if len(pivots) < start + 9:
        return -1, "pivot tidak cukup untuk 8 gelombang", None, {}
    win = pivots[start:start + 9]
    up = win[0][2] == "L"
    ok, why = _time_ok(win)
    if not ok:
        return -1, f"masa: {why}", up, {}
    ok, why = _hard_rules(win, up)
    if not ok:
        return -1, why, up, {}

    fs, notes, ratios = fib_score(win, up)
    w5 = win[5][1]
    a, b, c = win[6][1], win[7][1], win[8][1]
    shape, csc, cnote = classify_abc(w5, a, b, c, up)

    # Skor mentah: fib (maks 100) + bentuk koreksi (maks 22) -> normalisasi ke 100
    total = round((fs + csc) / 122 * 100)
    reason = (f"peraturan lulus · fib {fs}/100 · {shape} ({cnote.split('(')[0].strip()})")
    detail = {"fib": notes, "ratios": ratios, "shape": shape, "shape_note": cnote}
    return total, reason, up, detail


def label_waves(pivots, validate=True, min_score=50):
    """Label kitaran Elliot TERBAIK (8 gelombang), bukan yang pertama."""
    if not validate or len(pivots) < 9:
        LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C", "D", "E"]
        return ([(p[0], p[1], p[2], LABELS[i % len(LABELS)])
                 for i, p in enumerate(pivots)],
                "TIDAK SAH — pivot tidak cukup untuk 8 gelombang (perlu 9)", {})

    # Pilih kitaran TERBAIK, tetapi beri penalti pada kitaran purba:
    # kitaran yang tamat jauh dari harga terkini kurang berguna untuk dagang.
    # Penalty 0.4 mata setiap bar jarak (kitaran tamat 47 bar lalu = -19 mata).
    newest_bar = pivots[-1][0]
    best = (-1, None, None, {})
    for start in range(len(pivots) - 9, -1, -1):
        sc, why, up, detail = score_cycle(pivots, start)
        if sc < 0:
            continue
        end_bar = pivots[start + 8][0]
        staleness = newest_bar - end_bar
        adj = sc - min(30, staleness * 0.4)
        if adj > best[0]:
            best = (adj, start, why, detail)
    sc, start, why, detail = best
    if start is not None:
        end_bar = pivots[start + 8][0]
        detail = dict(detail or {})
        detail["staleness_bars"] = newest_bar - end_bar

    if start is None or sc < min_score:
        # Jatuh balik: label kitaran SEPARA dari 6 pivot TERAKHIR (impulse sahaja)
        # supaya chart tetap berkaitan harga semasa, bukan kosong.
        for st in range(len(pivots) - 6, -1, -1):
            win = pivots[st:st + 6]
            ok_h, _ = _hard_rules(win, win[0][2] == "L")
            ok_t, _ = _time_ok(win)
            if ok_h and ok_t:
                out2 = [(p[0], p[1], p[2], ["0", "1", "2", "3", "4", "5"][i])
                        for i, p in enumerate(win)]
                tail = pivots[st + 6:st + 9]
                for i, p in enumerate(tail):
                    out2.append((p[0], p[1], p[2], ["A", "B", "C"][i]))
                gap = pivots[-1][0] - win[-1][0]
                return out2, (f"SEPARA — impulse 0-5 sah (koreksi belum lengkap), "
                              f"tamat {gap} bar di belakang"), {"partial": True}
        return ([(p[0], p[1], p[2], "?") for p in pivots],
                f"TIDAK SAH — {why or 'tiada kitaran lulus'} (skor maks {max(sc, 0)})",
                detail)

    LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C"]
    out = [(p[0], p[1], p[2], LABELS[i])
           for i, p in enumerate(pivots[start:start + 9])]
    grade = "A" if sc >= 85 else ("B" if sc >= 70 else "C")
    return out, f"SAH (grade {grade}, {sc}/100) · {why}", detail
