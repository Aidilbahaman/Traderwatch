# TraderWatch App — Cadangan Design Baru (PWA Mobile-First)

**Status:** Cadangan + prototype **signal-first** dalam `pwa-app/` (Fasa 1 siap, live di `traderwatch.org/pwa-app/`)
**Skop dokumen:** design system, skrin & UX flow, seni bina PWA, pelan migrasi, kriteria penerimaan, anggaran effort.
**Kemas kini Nov 2026:** hala tuju signal-first (§8), chart beranotasi entry/SL/TP (§9), laluan data produksi (§10), nota integriti (§11).
**Fail sedia ada yang dirujuk:** `pwa-app/manifest.webmanifest`, `pwa-app/sw.js`, `landing-signal.json`, `landing-stats.json`, `signal-status.json`, `notify_new_members.py`, `supabase/`, `state/sq-bars.db`, `bot/bot_v2.py`, `migrations/20261106_confluence_engine.sql`, `pwa-app/data/replay-signal.json`, `pwa-app/data/replay-bars.json`.

---

## 1. Ringkasan Eksekutif

### Masalah design semasa
- Laman utama (`index.html`) ialah **landing page tradisional** — scroll panjang, hero besar, CTA bertaburan. Di telefon, signal utama tenggelam di bawah fold; pengguna perlu scroll untuk benda yang mereka buka laman ini untuk lihat.
- `manifest.webmanifest` wujud di root, tetapi **tiada service worker didaftarkan di mana-mana** (tiada `navigator.serviceWorker.register` dalam repo). Jadi laman ini **belum PWA sebenar**: tidak installable dengan betul, tiada offline, tiada push.
- Dashboard ahli (`members.html`) dan modul pendidikan (`education.html`) terpisah — tiada satu "rumah app" yang menyatukan signal, chart, tools dan belajar.
- Data signal sudah tersedia sebagai JSON statik (`landing-signal.json`, `landing-stats.json`, `signal-status.json`) tetapi dipersembahkan sebagai seksyen marketing, bukan sebagai maklumat glanceable.

### Matlamat
Satu **app-style mobile-first PWA** yang:
1. **Rasa native** — bottom nav 5 tab, kad besar, thumb-zone, tiada scroll marketing.
2. **Installable** — Android (prompt `beforeinstallprompt`) dan iOS (arahan manual Add to Home Screen), ikon maskable, standalone display.
3. **Offline-capable** — app shell precache; data signal terakhir dipaparkan dengan badge masa bila tiada network.
4. **Push-ready** — service worker sudah ada handler `push`/`notificationclick`; backend VAPID disambung kemudian guna bot Python sedia ada.
5. **Kekalkan identiti brand** — dark lime/hijau yang sama, cuma disusun semula sebagai app, bukan landing page.

### Keputusan design yang dipersetujui
Arah: **App-style mobile-first**. Skop: **Proposal + prototype PWA penuh** dalam `pwa-app/` (index.html, app.css, app.js, icons/, data/).
**Kemas kini Nov 2026:** pemilik tetapkan hala tuju **signal-first** — client berdaftar fokus pada SIGNALS; chart mesti ada lukisan entry/SL/TP + sebab entry. Lihat §8–§11; bahagian §3 dan §5 dikemas kini selari.

---

## 2. Konsep Design "TraderWatch App"

### 2.1 Prinsip
| Prinsip | Maksud praktikal |
|---|---|
| Mobile-first | Reka untuk 390×844 dahulu; desktop = app column ~430px di tengah + panel pitch di kiri |
| Thumb-zone | Aksi utama (nav, CTA daftar, toggle) dalam 60% bawah skrin; header hanya info |
| Glanceable signal | Signal utama boleh difahami < 3 saat: pair, arah, entry, TP/SL, status chip |
| Dark-first, lime accent | Latar `#0a0e0b`; lime `#c6f36b` hanya untuk aksi & nombor penting — bukan hiasan |
| Jujur tentang keadaan | Sentiasa tunjuk state: LIVE / cache / offline / kosong — jangan sorok data basi |
| Progressive disclosure | Tetamu nampak struktur signal (blur/lock) + 3 signal percuma/hari; daftar untuk penuh |

### 2.2 Design tokens (penuh)

**Warna** (kekal identiti brand):
```css
:root {
  --bg:        #0a0e0b;  /* latar app */
  --surface:   #121813;  /* kad */
  --surface2:  #18211a;  /* kad bersarang, input, chip */
  --line:      #26332a;  /* border halus */
  --ink:       #f2f5ef;  /* teks utama */
  --muted:     #93a096;  /* teks sekunder */
  --lime:      #c6f36b;  /* accent / CTA / angka positif */
  --lime-ink:  #10170b;  /* teks di atas lime */
  --red:       #ff817d;  /* SL / negatif / amaran */
  --amber:     #ffd479;  /* EXP / pending / offline badge */
}
```

**Typography** — Inter, fallback `system-ui, -apple-system, sans-serif`; semua angka guna `font-variant-numeric: tabular-nums` supaya harga/pips tidak melompat.
| Token | Saiz/line-height | Kegunaan |
|---|---|---|
| `--text-xs` | 12/16 | label, timestamp, badge |
| `--text-sm` | 14/20 | teks sekunder, butang kecil |
| `--text-base` | 16/24 | body, input (≥16px elak auto-zoom iOS) |
| `--text-lg` | 18/26 | tajuk kad |
| `--text-xl` | 22/28 | greeting, tajuk skrin |
| `--text-2xl` | 28/34 | harga signal utama |
| `--text-stat` | 24/28, weight 700 | angka stat tile |

**Spacing** — skala tetap: `4 / 8 / 12 / 16 / 20 / 24` px. Padding kad 16–20px; jarak antara kad 12px; padding tepi skrin 16px; ruang bawah kandungan = tinggi bottom nav + `env(safe-area-inset-bottom)` + 16px.

**Radius & shadow**
| Token | Nilai | Kegunaan |
|---|---|---|
| `--radius-card` | 20px | semua kad |
| `--radius-chip` | 999px | chip status, pill tab, badge |
| `--radius-input` | 12px | input, butang kecil |
| `--shadow-card` | `0 1px 0 rgba(255,255,255,.03) inset, 0 8px 24px rgba(0,0,0,.35)` | kad timbul halus |
| `--shadow-nav` | `0 -8px 24px rgba(0,0,0,.45)` | bottom nav |
| `--glow-lime` | `0 0 0 1px rgba(198,243,107,.35), 0 0 24px rgba(198,243,107,.12)` | signal LIVE sahaja |

### 2.3 Komponen utama
| Komponen | Spesifikasi |
|---|---|
| **Signal card** | Kad 20px: baris atas = pair + arah (BUY lime / SELL red) + chip status; tengah = entry besar (tabular), grid TP1/TP2/SL; bawah = masa diterbitkan + sumber AI. Versi tetamu: nilai di-blur (`filter: blur(6px)`) + overlay lock + CTA "Daftar percuma" |
| **Status chip** | Pill 999px, 12px teks: `LIVE` (lime, dot berdenyut), `TP` (lime), `SL` (red), `EXP` (amber), `CACHE` (muted). Mapping dari `signal-status.json`: `tp/sl/expired` |
| **Stat tile** | Kad kecil surface2: angka `--text-stat` + label muted. Contoh: ahli (11), signal aktif (1), win rate, jumlah pips — dari `landing-stats.json` + agregasi `signal-status.json` |
| **Bottom nav** | Fixed, 5 tab (Home/Signal, Markets, Tools, Learn, Account), ikon 24px + label 11px; tab aktif lime; tinggi 56px + `padding-bottom: env(safe-area-inset-bottom)`; latar surface dengan shadow-nav |
| **Install banner** | Kad boleh tutup (dismiss disimpan di localStorage): ikon app + "Pasang TraderWatch" + butang pasang. Android: cetus `beforeinstallprompt`; iOS: buka sheet arahan manual |
| **Offline badge** | Pill amber di header: "Offline · data 14:32" — masa dari `generated_at` / timestamp cache. Tunjuk automatik bila `navigator.onLine === false` atau fetch gagal |
| **Skeleton** | Blok surface2 berkilau halus (shimmer 1.2s) mengikut bentuk signal card / stat tile semasa loading pertama |
| **Empty state** | Ikon outline + tajuk + satu ayat + CTA. Contoh bila `landing-signal.json = null`: "Tiada signal aktif sekarang. Signal baru akan muncul di sini — hidupkan notifikasi supaya tidak terlepas." |

---

## 3. Skrin & UX Flow

Routing: hash-based (`#/home`, `#/markets`, `#/tools`, `#/learn`, `#/account`, `#/signal`) — sepadan dengan shortcuts dalam `manifest.webmanifest`, selamat untuk static hosting dan offline. `#/signal` = skrin detail signal (§8.3).

### 3.1 Lima tab

**① Home / Signal** (laluan lalai `#/home`) — **signal-first** (kemas kini Nov 2026, §8)
- Header ringkas + offline badge; **toggle mod paparan Tetamu / Ahli (demo)** untuk tunjuk kedua-dua pengalaman tanpa auth sebenar.
- **Feed signal = hero**: kad signal utama boleh ketik → skrin detail `#/signal` (chart beranotasi + sebab entry, §9). Bukan greeting generik.
  - Ahli (demo): kad penuh, glow lime jika LIVE; ketik untuk detail.
  - Tetamu: struktur kad nampak tetapi entry/TP/SL blur + lock; overlay CTA daftar. Kuota **3 signal percuma/hari** dikira di client (localStorage).
- Barisan stat tile ringkas (ahli, signal aktif, keputusan terkini) — sekunder kepada feed.
- **Keputusan terkini**: senarai 5–8 signal ditutup dari `data/signal-status.json` (pair, chip TP/SL/EXP, pips/R, masa); ketik → detail replay.
- Empty state bila `landing-signal.json = null`: tunjuk signal terakhir sebagai replay berlabel, bukan skrin kosong.

**② Markets** (`#/markets`)
- Segmen XAU/USD · XAG/USD · BTC; **default = chart app sendiri** (canvas candlestick, §9) dari data OHLC sebenar `data/bars-*.json` — **offline-capable** (SWR, badge masa bila cache).
- **Toggle "TradingView live"** sebagai pilihan: widget advanced chart lazy-load hanya bila dipilih dan online. TV tidak boleh di-cache (lihat §4) — bila offline, kembali automatik ke chart sendiri + badge.

**③ Tools** (`#/tools`)
- **Kalkulator saiz posisi XAU**: input baki akaun (USD), risiko % (atau riskUSD terus), jarak SL (USD harga). Formula: `lot = riskUSD / (jarakSL × 100)` (1 lot XAU = 100 oz, pergerakan $1 = $100/lot). Output lot + anggaran risiko USD, angka tabular, amaran bila lot > had munasabah. **CTA dari skrin detail signal (§8.3) prefill jarak SL automatik** dari signal dipilih.
- **Converter demo**: USD↔MYR dan oz↔gram dengan kadar statik/demo (dilabel "demo" — bukan harga live).
- Semua input ≥16px, keypad numerik (`inputmode="decimal"`), keputusan dikira serta-merta tanpa butang hantar.

**④ Learn** (`#/learn`)
- Kad modul pendidikan (dari struktur `education-data.js` sedia ada): tajuk, tahap, anggaran masa, progress ringkas.
- Tap kad → buka `education.html` (modul sedia ada, belum di-port) dalam tab yang sama; kembali ke app melalui nav. Migrasi penuh modul ke dalam app = kerja kemudian, bukan skop prototype.

**⑤ Account** (`#/account`)
- Tetamu: kad login/signup (pautan ke `login.html` sedia ada), kad pelan **"Automation Trade — RM150 sekali bayar"** dengan senarai manfaat + CTA langgan (`subscribe.html` sedia ada).
- Ahli: profil ringkas, status pelan, butang logout.
- **Pasang app**: butang pasang (Android) / arahan iOS (Safari → Share → Add to Home Screen).
- **Toggle notifikasi**: minta `Notification.requestPermission()` → `pushManager.subscribe({ applicationServerKey: VAPID_PUBLIC })` → hantar subscription ke backend (§4.4). Tunjuk state sebenar: belum dibenarkan / aktif / disekat browser.
- FAQ (accordion) + **risk disclosure** tetap di bawah: dagangan berisiko, signal bukan nasihat kewangan, prestasi lepas bukan jaminan.

### 3.2 State setiap skrin
| State | Perlakuan |
|---|---|
| Loading | Skeleton mengikut bentuk komponen; hanya untuk load pertama (SWR bagi data cache serta-merta) |
| Empty | Komponen empty state khusus + CTA berkaitan (hidupkan notifikasi / daftar / cuba semula) |
| Error | Kad mesej ringkas + butang "Cuba lagi"; jangan paparkan stack trace / JSON mentah |
| Offline | Badge amber di header dengan masa data terakhir; data dari cache SWR; Markets & detail signal → chart cached terakhir + badge masa (bukan placeholder kosong); semua input tools tetap berfungsi (client-side) |

### 3.3 Flow tetamu → daftar → ahli
```
Buka app (tetamu)
  → Home: stat + signal blur/lock + kuota 3 percuma/hari
  → Tap signal terkunci / CTA "Daftar percuma"
  → Account: signup (login.html sedia ada, Supabase auth)
  → Daftar berjaya → kembali ke app, state ahli
  → Home: signal penuh terbuka; install banner digalakkan
  → Account: toggle notifikasi → subscribe push
  → (Pelan RM150 melalui subscribe.html sedia ada untuk Automation Trade)
```
Kuota harian tetamu disimpan di localStorage dengan tarikh; reset automatik hari baru. Ini UX demo — penguatkuasaan sebenar di backend bila auth diintegrasikan (Fasa 2).

---

## 4. Seni Bina PWA

### 4.1 Strategi cache (seperti dilaksanakan dalam `pwa-app/sw.js`)
| Jenis permintaan | Strategi | Sebab |
|---|---|---|
| App shell (HTML/CSS/JS/ikon/manifest) | **Precache + cache-first**, background update | Buka serta-merta, offline penuh |
| Navigasi (`request.mode === 'navigate'`) | **Network-first**, fallback `index.html` dari cache | HTML segar bila online; shell bila offline |
| Data JSON (`/data/…`) | **Stale-while-revalidate** | Papar cache terakhir serta-merta, kemas kini di latar; offline = data terakhir + badge masa |
| Pihak ketiga (TradingView dll.) | **Network-only** (SW tidak respond) | Widget dinamik, tidak boleh/tidak patut di-cache |

- Versi cache: `tw-pwa-v1` → dua cache: `tw-pwa-v1-shell`, `tw-pwa-v1-data`. Naik versi = `activate` memadam semua cache lama.
- `install`: `cache.addAll(SHELL_ASSETS)` → `skipWaiting()`; `activate`: buang cache bukan versi semasa → `clients.claim()`.
- SWR fallback terakhir: respons `'null'` (JSON sah) supaya client boleh handle empty state, bukan crash.
- Handler `message: 'SKIP_WAITING'` sedia untuk butang "Kemas kini sekarang" dalam app (§5, Fasa 3).

### 4.2 Manifest + shortcuts
`pwa-app/manifest.webmanifest` sudah lengkap dan konsisten dengan design ini:
- `name`: "TraderWatch — Read the Market", `short_name`: "TraderWatch", `lang: ms`.
- `display: standalone` (+ override `minimal-ui`), `orientation: portrait`, `theme_color`/`background_color` `#0a0e0b` — sepadan token `--bg`.
- Ikon: 192, 512, maskable-512 (tujuan `any`/`maskable`); `icon-180.png` untuk `apple-touch-icon` di index.html (dalam senarai precache SW).
- **Shortcuts** (long-press ikon app): Signal terkini → `#/home`, Chart pasaran → `#/markets`, Kalkulator risiko → `#/tools`. Routing hash app mesti menyokong deep-link ini.

### 4.3 Install prompt
- **Android/Chrome**: tangkap `beforeinstallprompt`, simpan event, tunjuk install banner; butang → `prompt()` → semak `userChoice`; sembunyikan banner selepas `appinstalled`.
- **iOS/Safari**: tiada API prompt — banner khas dengan arahan manual 3 langkah (Share → Add to Home Screen → Add). Kesan standalone hanya bila dibuka dari ikon homescreen.
- Banner tidak muncul semula selepas dismiss (localStorage), dan tidak muncul jika sudah standalone (`display-mode: standalone`).

### 4.4 Push notification (sedia VAPID)
**Client (sudah ada dalam sw.js):**
- Handler `push` baca payload JSON `{title, body, url, tag}`; default title "TraderWatch", tag `tw-signal` (notifikasi signal baru menggantikan yang lama, bukan bertindan).
- `notificationclick`: fokus window sedia ada + navigate ke `url`, atau buka window baru.
- App: toggle di Account → `pushManager.subscribe` dengan `applicationServerKey` (VAPID public key, base64url → Uint8Array).

**Backend (cadangan integrasi — guna yang sedia ada):**
1. **Jana VAPID keys sekali**: `vapid --gen` (atau `py_vapid`), simpan di `/home/ubuntu/.secrets/vapid.env` — ikut corak `notify_new_members.py` yang sudah membaca secrets dari situ.
2. **Simpan subscription dalam Supabase** (repo sudah ada `supabase/`, auth + `profiles` digunakan oleh `notify_new_members.py`): jadual baru `push_subscriptions (user_id uuid, endpoint text unique, p256dh text, auth text, created_at)`. RLS: user hanya boleh tulis subscription sendiri.
3. **Hantar push dari bot Python sedia ada**: bila engine menerbitkan signal baru (atau `notify_new_members.py` kesan event), skrip kecil `push_signals.py` membaca subscription dari Supabase dan hantar guna **`pywebpush`**:
   ```python
   from pywebpush import webpush
   webpush(subscription_info,
           json.dumps({"title": "Signal XAU/USD BUY",
                       "body": "Entry 2650.0 · TP 2662.0 · SL 2644.0",
                       "url": "./index.html#/home", "tag": "tw-signal"}),
           vapid_private_key=VAPID_PRIVATE,
           vapid_claims={"sub": "mailto:admin@traderwatch.org"})
   ```
4. **Hormati kuota & cleanup**: buang subscription yang pulangkan 404/410 (expired); had kadar hantar (cth. maksimum 1 push/signal, tag sama).
5. **Jadual pelaksanaan push**: Fasa 3 (selepas app live) — lihat §5. Telegram sedia ada kekal sebagai saluran utama; web push saluran tambahan.

---

## 5. Pelan Migrasi ke Production

### Fasa 1 — Prototype signal-first ✅ SIAP
- Deploy di **`traderwatch.org/pwa-app/`** (scope SW terhad ke `/pwa-app/`; subdomain `app.traderwatch.org` kekal pilihan bila mahu scope root).
- IA signal-first (§8): Home = feed signal, skrin detail `#/signal` dengan chart beranotasi (§9), toggle Tetamu/Ahli (demo).
- `data/` diisi salinan `landing-signal.json`, `landing-stats.json`, `signal-status.json` + `bars-*.json` (OHLC dari `sq-bars.db`) + `replay-signal.json`/`replay-bars.json` (demo replay, §9.3).
- Laman utama lama **tidak disentuh**; pautan "Cuba app baru (beta)" di landing untuk kutip feedback.
- Smoke test: install Android + iOS, offline mode (chart cached berfungsi), semua 5 tab + detail signal, shortcuts.

### Fasa 2 — Signal feed live + auth
- Bina endpoint terauthentiikasi `/api/bars` + `/api/signals` (§10) — caddy `reverse_proxy` ke service localhost; client tidak pernah pegang service key.
- Integrasi auth dengan sistem sedia ada: `login.html`, Supabase profiles — app baca sesi Supabase (SDK ringan); feed penuh untuk ahli, free kekal `get_signals()` RLS (signal terkini sahaja).
- Sebab entry production dari `cf_signals.summary` sebenar (§11) — ganti ringkasan demo.
- Setelah stabil: `pwa-app/index.html` menjadi `index.html` root (landing lama disimpan sebagai `landing-classic.html`); pelan RM150 kekal melalui `subscribe.html` / Stripe webhook sedia ada.

### Fasa 3 — Chart live refresh + push
- Chart detail & Markets refresh automatik dari `/api/bars` (poll ~15 min ikut collector, atau lebih kerap untuk gran M1); lifecycle signal refresh dari `/api/signals`.
- Laksanakan §4.4: VAPID keys, jadual `push_subscriptions`, `push_signals.py` + cron; push deep-link terus ke `#/signal?id=…`.
- **Auto-update SW**: `updatefound` → toast "Versi baru tersedia — Kemas kini" → `SKIP_WAITING` → reload. Naik `VERSION` setiap deploy shell.
- Pantau: log penghantaran push, kadar subscription, ralat cache, kesegaran bars.

### Risiko & mitigasi
| Risiko | Mitigasi |
|---|---|
| **Cache basi** (signal lama dipaparkan sebagai baru) | SWR sentiasa revalidate bila online; badge masa jelas ("data 14:32"); chip `CACHE`; timestamp `generated_at` dipapar pada signal |
| **iOS limitation push** | Web push iOS hanya berfungsi untuk app yang **dipasang ke Home Screen** (iOS 16.4+); UI toggle terangkan syarat ini; Safari lama/in-private → toggle disabled dengan mesej; Telegram kekal fallback |
| **TradingView perlukan network** | TV kini toggle pilihan sahaja; default chart app sendiri offline-capable dari bars cache + badge masa |
| **Service key Supabase bocor ke client** | `cf_signals` private (tiada policy SELECT); hanya service localhost baca dengan service key; client akses melalui endpoint terauthentiikasi (§10) |
| SW lama melekat selepas deploy | Version bump + `skipWaiting`/`clients.claim` + butang kemas kini manual; cache lama dipadam automatik semasa `activate` |
| Kuota tetamu (localStorage) mudah dipintas | Diterima untuk fasa demo; penguatkuasaan sebenar di backend pada Fasa 2 |
| Dua sumber data (root vs `pwa-app/data/`) bercanggah | Satu cron jana + salin kedua-dua lokasi; Fasa 2 hapuskan pendua |

---

## 6. Kriteria Penerimaan (Checklist)

- [ ] **Lighthouse PWA pass** (installable + service worker + offline) pada URL preview.
- [ ] **Installable Android**: prompt `beforeinstallprompt` berfungsi; ikon maskable betul; standalone tanpa address bar.
- [ ] **Installable iOS**: arahan manual jelas; `apple-touch-icon` 180px; buka dari homescreen = standalone.
- [ ] **Offline**: buka app tanpa network → shell penuh + data cache terakhir dengan **badge masa**; tiada skrin putih/crash.
- [ ] **Push demo berfungsi**: subscribe → hantar payload ujian `{title, body, url, tag}` → notifikasi muncul → klik membuka tab yang betul.
- [ ] **Kontras WCAG AA**: lime `#c6f36b` pada `#0a0e0b` lulus (nisbah ~15:1); teks muted `#93a096` pada surface ≥ 4.5:1; chip status tidak bergantung pada warna sahaja (ada teks TP/SL/EXP).
- [ ] **Focus-visible**: semua elemen interaktif ada outline focus yang jelas (lime), navigasi keyboard berfungsi.
- [ ] **`prefers-reduced-motion`**: shimmer skeleton, dot denyut LIVE dan transisi tab dimatikan/diperlahankan bila diminta.
- [ ] **Safe-area iPhone**: bottom nav + kandungan tidak terpotong oleh home indicator (`env(safe-area-inset-bottom)`); header hormati `safe-area-inset-top` dalam standalone.
- [ ] Empty state betul bila `landing-signal.json = null` — fallback replay berlabel, bukan skrin kosong.
- [ ] Kalkulator XAU: `lot = riskUSD / (jarakSL × 100)` disahkan dengan 3 kes ujian manual; CTA detail signal prefill jarak SL betul.
- [ ] Shortcuts manifest (Signal/Markets/Tools) mendarat di tab yang betul.
- [ ] **Lukisan chart betul pada skala harga**: zon POI (entry_min–entry_max), garisan ENTRY/SL/TP1/TP2, zon risiko/ganjaran dan penanda siaran/luput mendarat pada harga & masa yang tepat (uji dengan nilai demo yang diketahui).
- [ ] **Sebab entry dipaparkan untuk setiap signal diterbitkan** — summary + checklist confluence; signal tanpa summary tidak boleh diterbitkan (Fasa 2).
- [ ] **Chart berfungsi offline** dengan badge masa data terakhir (detail signal + Markets).
- [ ] **Demo replay dilabel jelas** "DEMO REPLAY · data sebenar" pada kad, chart dan skrin detail; zon POI ilustrasi ditanda (§11).

---

## 7. Anggaran Effort

| Fasa | Skop | Anggaran |
|---|---|---|
| Prototype signal-first | index.html + app.css + app.js + icons + data, 5 tab + detail signal, chart beranotasi, demo replay | **Siap (Fasa 1)** |
| Fasa 1 — Preview | Deploy `traderwatch.org/pwa-app/`, salinan data + bars + replay, smoke test Android/iOS | **Siap** |
| Fasa 2 — Feed live + auth | Endpoint `/api/bars` + `/api/signals` (caddy + service localhost), integrasi sesi Supabase, summary sebenar, swap landing | **3–4 hari** |
| Fasa 3 — Chart live + push | Refresh bars/lifecycle automatik, VAPID keys, jadual Supabase, `push_signals.py` + cron, UI kemas kini SW | **2–3 hari** |
| QA & pemantapan | Checklist §6 penuh, Lighthouse, peranti sebenar (iPhone + Android), pembetulan | **1 hari** |
| **Jumlah baki** | | **~6–8 hari bekerja** |

*Nota: anggaran untuk seorang pembina. Push (Fasa 3) boleh ditangguh tanpa menjejaskan nilai teras — signal feed + chart beranotasi + sebab entry sudah memberi majoriti manfaat untuk client berdaftar.*

---

## 8. Hala Tuju Signal-First (kemas kini Nov 2026)

### 8.1 Permintaan pemilik
> "Client berdaftar focus pada SIGNALS; chart mesti ada lukisan entry/SL/TP + sebab entry."

Implikasi: app bukan lagi landing-style dengan greeting generik — **signal ialah hero**. Setiap signal mesti boleh difahami sepenuhnya: level harga, lukisan pada chart, dan sebab mengapa entry itu diambil.

### 8.2 IA baru
| Laluan | Peranan |
|---|---|
| `#/home` | **Feed signal** — kad signal hero boleh ketik; stat tile sekunder; keputusan terkini; toggle mod paparan **Tetamu / Ahli (demo)** |
| `#/signal` | **Detail signal** — chart beranotasi (§9) + kad "Sebab entry" + timeline lifecycle + CTA kalkulator |
| `#/markets` | Chart app sendiri dari OHLC sebenar (default, offline-capable); toggle TradingView live |
| `#/tools` | Kalkulator saiz posisi (prefill dari signal), converter |
| `#/learn` | Modul pendidikan (pautan ke `education.html`) |
| `#/account` | Auth, pelan, pasang app, notifikasi, risk disclosure |

### 8.3 Skrin detail signal (`#/signal`)
- **Chart candlestick custom** dengan lukisan penuh (§9).
- **Kad "Sebab entry"**: summary AI + checklist confluence (sweep, POI/OB, RR ≥ 1.5, news gate, entry dalam zon) — setiap gate tunjuk pass/fail + nota.
- **Grid level penuh**: entry, SL, TP1, TP2 + RR (rr1/rr2).
- **Timeline lifecycle**: posted → active → tp/sl/expired, dengan masa sebenar setiap peringkat.
- **CTA "Kira saiz posisi"** → `#/tools` dengan jarak SL diprefill.

### 8.4 Prinsip
| Prinsip | Maksud praktikal |
|---|---|
| Signal = hero | Feed signal di Home, bukan greeting; kad hero boleh ketik → detail |
| Setiap signal boleh difahami | Level + lukisan pada chart + sebab entry — tiga-tiga wajib, bukan pilihan |
| Offline masih berguna | Chart cached terakhir + badge masa; signal terakhir sebagai replay berlabel |
| Jujur tentang data | Demo dilabel "DEMO REPLAY"; zon ilustrasi ditanda; jangan reka sebab (§11) |

---

## 9. Chart Beranotasi

### 9.1 Spesifikasi visual (warna ikut tokens §2.2)
| Elemen | Lukisan | Warna/token |
|---|---|---|
| Zon POI | Rect `entry_min`–`entry_max` merentasi chart | Lime pudar (sempadan `--lime`) |
| Garisan ENTRY | Garis putus-putus mendatar + label harga | Lime `#c6f36b` |
| Garisan SL | Garis mendatar + label | Merah `#ff817d` (`--red`) |
| Zon risiko | Lorek merah **8%** antara ENTRY–SL | `rgba(255,129,125,.08)` |
| TP1 / TP2 | Garis mendatar + label | Lime `#c6f36b` |
| Zon ganjaran | Lorek lime **6%** antara ENTRY–TP | `rgba(198,243,107,.06)` |
| Penanda masa siaran | Garis menegak + label "SIARAN" | Putih (`--ink`) |
| Penanda masa luput | Garis menegak + label "LUPUT" | Amber `#ffd479` (`--amber`) |
| Crosshair | Sentuh/hold → garis silang + tooltip OHLC bar tersebut | Muted + surface2 |

Semua label harga tabular-nums; skala harga auto-pad supaya zon risiko/ganjaran dan semua level sentiasa dalam viewport.

### 9.2 Kenapa custom canvas, bukan TradingView embed
- **TV embed tidak boleh lukis garisan programatik** — tiada API untuk overlay entry/SL/TP pada widget awam. Lukisan = keperluan teras pemilik, jadi chart mesti milik app.
- **Chart sendiri offline-capable** — bars JSON di-cache SWR (§4.1); TV network-only.
- **TV kekal sebagai toggle live** di Markets untuk pengguna yang mahu chart penuh pihak ketiga; bukan default.
- Implementasi: canvas 2D + chart.js (financial/candlestick) dalam `pwa-app/`, ringan dan boleh dikawal sepenuhnya.

### 9.3 Demo replay (prototype semasa)
- Signal sebenar lepas: **`XAUUSD_20261026_134403`** — BUY, entry 4008.81, SL 4003.26, TP 4019.28, RR 1.89; status **EXPIRED**, reason sebenar: *"outside POI zone >30min (entry not triggered)"*.
- Bar **M15 sebenar** dari `state/sq-bars.db`, window 26 Okt 02:00–14:00 UTC (`data/replay-bars.json`).
- Dilabel jelas **"DEMO REPLAY · data sebenar"** pada kad dan skrin detail.
- **Zon POI dalam demo = ilustrasi** — `poi_low`/`poi_high` sebenar tidak disimpan dalam feed awam; entry = CE 50% zon dikekalkan sebagai konsep (§11).

---

## 10. Laluan Data Produksi

### 10.1 Sumber sedia ada & jurang
| Keperluan | Sumber sedia ada | Jurang / tindakan |
|---|---|---|
| Bar OHLC live | `state/sq-bars.db` — collector Swissquote (forex/logam) + Coinbase (BTC); jadual `bars(pair,gran,ts,o,h,l,c,polls)`; gran M1/M5/M15/M30/M60; 9 pairs; kemas kini ~15 min; `ts` UTC naive (ISO8601) | Belum ada endpoint HTTP — perlu `/api/bars` baca DB ini |
| Signal aktif + level + sebab | Supabase `cf_signals` (migrations/20261106): `entry_min/entry_max`, `stop_loss`, `take_profit_1/2/3`, `risk_reward`, `confidence_label`, **`summary` (sebab entry)**; status DRAFT/PUBLISHED/ACTIVE/HIT_TP/HIT_SL/EXPIRED/INVALIDATED/CANCELLED | **PRIVATE** — service-key only, tiada policy SELECT. Perlu service localhost baca dengan service key, dedah melalui `/api/signals` terauthentiikasi |
| Signal awam (free/pro) | `public.signals` via RPC `get_signals()` (auth; free hanya signal terkini) | Kekalkan RLS sedia ada — jangan bypass |
| Status lifecycle + pips | `signal-status.json` (status + pips + reason kadangkala), `landing-signal.json` (signal semasa atau null) | Cukup untuk prototype; Fasa 2 pindah ke `/api/signals` |
| Enjin signal | `bot/bot_v2.py` — POI zone (`poi_low/poi_high`), entry = CE 50% zon, sl, tp1, tp2, rr1, rr2; confluence gates (`s_sweep`, `s_news` dll); jadual `trades` dalam `bot.db` (kosong di server ini; produksi di Supabase) | Tiada perubahan enjin diperlukan untuk PWA |

### 10.2 Seni bina endpoint (cadangan)
- **Caddy `reverse_proxy`** `/api/bars` + `/api/signals` → service localhost (Python ringan, corak bot sedia ada).
- Service baca `sq-bars.db` (read-only) dan Supabase dengan **service key disimpan di server** (`/home/ubuntu/.secrets/`, ikut corak `notify_new_members.py`). **Jangan sekali-kali dedah service key ke client.**
- Auth: sahkan JWT Supabase pengguna di service; ahli = feed penuh + summary; free = kekal `get_signals()` RLS (signal terkini sahaja, tanpa level penuh).

### 10.3 Shape JSON ringkas
```jsonc
// GET /api/bars?pair=XAUUSD&gran=M15&limit=200
{ "pair": "XAUUSD", "gran": "M15", "updated": "2026-11-19T15:45:00Z",
  "bars": [ { "ts": "2026-11-19T15:45:00Z", "o": 4010.1, "h": 4012.3, "l": 4009.2, "c": 4011.0 } ] }

// GET /api/signals?status=active   (ahli; JWT disahkan di service)
{ "signals": [ {
    "id": "XAUUSD_20261119_…", "pair": "XAUUSD", "side": "BUY",
    "entry_min": 4007.9, "entry_max": 4009.7, "entry": 4008.81,
    "sl": 4003.26, "tp1": 4019.28, "tp2": null, "rr": 1.89,
    "status": "ACTIVE", "posted_at": "…", "expires_at": "…",
    "summary": "…sebab entry sebenar dari cf_signals.summary…",
    "confluence": [ { "gate": "s_sweep", "pass": true } ]
} ] }
```

---

## 11. Nota Integriti Data

- **Demo guna data sebenar, tetapi zon POI ilustrasi.** Bar M15 dan signal (entry/SL/TP/RR/status/reason) adalah data sebenar; `poi_low/poi_high` dalam demo direka bentuk sebagai ilustrasi kerana zon sebenar tidak disimpan dalam feed awam. Mesti ditanda pada UI ("zon POI ilustrasi").
- **Ringkasan AI demo ditulis manual** berdasarkan reason sebenar signal tersebut — bukan output enjin. Dalam produksi, kad "Sebab entry" **mesti guna `cf_signals.summary` sebenar**; jangan reka atau janakan sebab di client.
- Signal tanpa summary/confluence lengkap tidak patut diterbitkan ke feed ahli — kuatkuasaan di enjin/service, bukan di UI.
- Prinsip am (§2.1 "Jujur tentang keadaan") terpakai pada data: LIVE / cache / offline / DEMO sentiasa dilabel; jangan persembahkan replay sebagai signal live.