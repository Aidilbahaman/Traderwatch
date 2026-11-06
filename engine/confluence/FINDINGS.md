# Confluence Engine — Rekod Kajian & Keputusan

**Tarikh:** 2026-11-06
**Status:** ❌ **TIDAK DILANCARKAN** — enjin **tiada edge** pada data sebenar
**Keputusan Aidil:** Kekal enjin lama (SMC)

---

## Ringkasan satu perenggan

Confluence Engine dibina lengkap (5 fasa, 131 ujian lulus, migration DB
dijalankan) tetapi **gagal pada ujian out-of-sample dengan sample besar**.
Enjin lama (SMC sahaja) **lebih baik** dari enjin baharu ini.

---

## Hasil ujian muktamad (18 konfigurasi, 7 pair)

| thr | step | n | WR% | expR | PF | OOS_n | OOS_exp |
|---|---|---|---|---|---|---|---|
| 0.05 | 10 | 6223 | 40.9 | −0.1274 | 0.705 | 1867 | −0.1303 |
| 0.10 | 10 | 3920 | 40.2 | −0.1403 | 0.689 | 1176 | −0.1381 |
| 0.15 | 10 | 2286 | 40.4 | −0.1498 | 0.680 | 686 | −0.1555 |
| 0.20 | 20 | 1019 | 42.8 | −0.1088 | 0.715 | 306 | −0.0886 |
| 0.25 | 20 | 538 | 46.1 | −0.0430 | 0.865 | 162 | −0.0371 |
| 0.30 | 30 | 147 | 49.0 | +0.0020 | 1.007 | 45 | +0.0229 |

**Hampir semua negatif.** Satu konfigurasi +0.002R = sifar praktikal.

### Perbandingan dengan enjin lama

| | Enjin Lama (SMC `ny`) | Confluence |
|---|---|---|
| n | 835 | 6,223 |
| expR | **+0.045R** | **−0.127R** |
| PF | 1.07 | 0.705 |
| OOS | positif kecil | **negatif** |

Confidence interval OOS (n=1867): **[40%, 42%]** — cukup sempit untuk
menyimpulkan bahawa win rate ~41% dan expectancy negatif adalah **kukuh**,
bukan INCONCLUSIVE.

---

## Pelajaran penting (elak ulang)

### 1. Sample kecil menipu
Backtest awal (21 trade) menunjukkan **+0.1496R**. Bila sample naik ke
**6,223 trade**, ia jadi **−0.127R**. "Edge" pada sample kecil adalah bunyi.

**Peraturan:** jangan percaya apa-apa di bawah ~200 trade OOS.

### 2. Selection bias menyembunyikan masalah
`build_setup()` menetapkan `valid` berdasarkan bukti ICT/structure — dan
bukti itu hanya muncul bila skor sudah tinggi. Akibatnya threshold
0.15–0.35 memberi angka **identik** (semua setup berskor 0.35–0.41).
Ujian kelihatan berjaya padahal ia tidak menguji apa-apa.

**Peraturan:** kalau dua threshold berbeza memberi angka sama, siasat
taburan skor sebelum mempercayai hasil.

### 3. Tambah trade = tambah rugi
| step | avg n | avg OOS exp |
|---|---|---|
| 10 | 2439 | −0.2484 |
| 20 | 1861 | −0.0894 |
| 30 | 1255 | −0.0476 |

Lebih banyak trade = lebih rugi. Tanda classik **overtrading bunyi bising** —
kos ditambah tanpa edge.

### 4. "Confluence" bukan bukti bebas
`structure` + `mtf` + `quant` semuanya membaca trend yang sama. Menambah
mereka tidak menambah pengesahan — ia mengira arah yang sama tiga kali.
WR ~41% merentas SEMUA threshold bermakna skor tidak diskriminatif.

### 5. Coverage rendah mengehadkan skor maksimum
4 dari 10 kumpulan UNAVAILABLE (macro, volume, intermarket, elliot) = 25
daripada 100 mata wajaran hilang. Skor maksimum praktikal ~±0.40.

---

## Pepijat prestasi yang dijumpai & dibetulkan

`analyze()` memanggil `md.health()` setiap kali — ia **baca semula 20,000 bar
dari disk** + kira gap. Membuangnya dari hot path: **136ms → 17ms/titik** (8×).

Ini masih berguna kalau kajian diteruskan.

---

## Apa yang KEKAL dalam repo (boleh guna semula)

| Fail | Guna untuk |
|---|---|
| `engine/confluence/instruments.py` | Metadata digit/pip 36 pair |
| `engine/confluence/market_data.py` | Adapter + dedup + gap (klasifikasi weekend/rollover) |
| `engine/confluence/features/*.py` | Structure, liquidity, ICT, quant, MTF, session |
| `engine/confluence/backtest.py` | Metrik + CI Wilson + walk-forward + kos |
| `engine/confluence/lifecycle.py` | Analysis run + audit (jadual `cf_*` ada di DB) |
| `tests/confluence/*` | 131 ujian |

Jadual DB `cf_analysis_runs`, `cf_signals`, `cf_signal_audits` masih ada —
**tiada akses authenticated** (private), tidak mengganggu sistem sedia ada.

---

## Keputusan

**Kekal enjin lama (SMC).** Confluence:
- Tiada cron
- Tiada service
- Tiada signal dihantar
- Tidak akan dijadualkan tanpa bukti baru

Jangan hidupkan tanpa:
1. Bukti OOS positif dengan n ≥ 200
2. Konsisten merentas regime dan pair
3. CI yang tidak meliputi sifar untuk expectancy

---

## Kalau kajian diteruskan (cadangan)

Uji setiap kumpulan **secara berasingan** dahulu untuk cari mana yang
merosakkan, kemudian baru gabung. Jangan gabung 10 kumpulan dan harap
jumlahnya berfungsi.
