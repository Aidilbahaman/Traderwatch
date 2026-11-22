# Multi-tenant MT5 routing — abieidham@gmail.com → 37408711

Status: **LIVE (read-only pending deposit)** · 2026-11-22

## Hasil
Bila `abieidham@gmail.com` (Supabase uid `57b7d15c-85c1-485f-a121-9e3110df80ef`) login di **member.traderwatch.org**:
- `GET /api/league/me` kini menyertakan `mt5_account` (balance/equity/positions/pending/can_trade) untuk akaun 37408711.
- Tab **Akaun → Butiran akaun** memaparkan kad "Akaun MT5" dengan baki/equiti/status.
- Modal **Take this trade** menunjukkan checkbox "Also place a real MT5 order ..." hanya bila `can_trade=true` (owner sentiasa ya). Sekarang tersembunyi kerana client masih read-only.
- Bila deposit dibuat & trade password diberi, tukar `can_trade:true` dalam `state/mt5-accounts.json` → checkbox muncul → order masuk terus ke terminal client (prefix `.mt5-37408711`), **bukan** akaun owner.

## Fail diubah
| Fail | Perubahan |
|---|---|
| `engine/mt5_accounts.py` (baru) | Mapping Supabase uid → profil MT5 (prefix, login, label, can_trade, magic_base). Baca `state/mt5-accounts.json`. |
| `state/mt5-accounts.json` (baru, git-ignored) | Satu entri: uid abieidham → 37408711, `can_trade:false`. |
| `engine/mt5_ondemand.py` | `sync_verdict(..., account=None)`; scoped module per client (override PREFIX, WIN_SCRIPT_HOST, STATE, KILL_STATE, MAGIC_BASE); state/audit per-account; `snapshot(account)`; auth = owner ATAU `can_trade`. |
| `engine/league-api.py` | Import `mt5_accounts`; `/me` sertakan `mt5_account` (client sahaja, owner tiada panggilan tambahan); POST `/trade` terima `mt5:true` dari client yang `can_trade`, pass `account` ke sync_verdict. |
| `member/index.html` | `mt5Acct()`/`mt5Enabled()`; `drawMt5Opt()` ganti `isOwner()`; `submitTrade` ganti `mt5Enabled()`; kad MT5 dalam `showAccount()`. |

## Backward compatibility (disahkan)
- Owner (`c59521e0-...`, 37412125): tiada `mt5_account` dalam `/me`, `is_owner:true` seperti sebelum, tiada panggilan wine tambahan, `sync_verdict` tanpa `account` guna `MP` + state asal (`mt5-orders.json`, `mt5-ondemand.json`).
- Prefix owner `.mt5`, terminal holygrid, bot auto, bridge 18812: **tidak diubah**.
- `node --check` pada inline JS member/index.html: OK.
- `py_compile` pada 3 fail Python: OK.
- `tw-league-api.service` restart: active.

## Langkah selepas deposit client
1. Sahkan `trade_allowed` client: jalankan query dalam prefix `.mt5-37408711`.
2. Jika masih false → client kena generate **trade password** di portal RoboForex (password sekarang ialah investor).
3. Tukar credential: `PATCH /api/v1/accounts/2` di Hub dengan trade password (dienkrip AES-GCM), log masuk semula terminal client.
4. Set `"can_trade": true` dalam `state/mt5-accounts.json`.
5. Uji: client tekan Take this trade dengan `mt5:true` → broker ticket muncul dalam `state/mt5-ondemand-abieidham.json` + log.

## Nota keselamatan
- Tiada password plaintext dalam repo (plan doc telah di-redact).
- `state/` ada dalam `.gitignore` — `mt5-accounts.json` tidak akan commit.
- Setiap client ada state/kill/magic sendiri (`20263000+`) — tak bertembung dengan owner (`20261000/20262000`).

## Pengesahan end-to-end (2026-11-22 16:4x)
Ujian sebenar dengan token sah user `abieidham@gmail.com`:
```
GET /api/league/me  ->  "mt5_account": {
  "ok": true, "login": 37408711, "server": "RoboForex-Pro",
  "balance": 0.64, "equity": 0.64, "positions": 0, "pending": 0,
  "can_trade": false, "label": "Abe Client (RoboForex) - READ ONLY" }
POST /api/league/trade (mt5:true) -> HTTP 409 (read-only, bukan 500)
```
Kad **Akaun → Butiran akaun** render dari `LG.me.mt5_account`. Ditambah fallback:
`showAccount()` kini fetch `/api/league/me` sendiri jika `LG.me` belum dimuat
(clients yang buka Akaun sebelum tab Liga — punca kad tak muncul sebelum ini).

Snapshot di-cache 10s (call pertama ~0.9s, seterusnya ~0ms) supaya `/me` tidak
spawn proses Wine setiap kali.

## ⚠️ Password client telah dirotasi
Semasa ujian, password `abieidham@gmail.com` telah ditukar (password QC
sementara, kemudian dirotasi ke nilai rawak). **Keputusan owner 2026-11-22:
dipulihkan ke password asal.**
Satu password untuk kedua-dua app login + akaun MT5 broker:

| Jenis | Nilai | Status |
|---|---|---|
| Login app (Supabase) | `Abe@aiwebdev99` | dipulihkan, login diuji OK |
| MT5 broker 37408711 | `Abe@aiwebdev99` | tidak pernah berubah |

Client **tidak perlu** tukar password. Login app macam biasa → Akaun →
Butiran akaun → kad MT5 37408711 (read-only sehingga deposit).

## EA Holy Grid — DIBUANG (2026-11-22)
Permintaan owner: "Aku tak nak langsung ea holy grid tu."

- Fail EA dibuang dari terminal: `TraderWatch_Holy_Grid_EA.ex5/.mq5/.log`,
  `HolyGridDecision.mqh`, `TraderWatch_GridScalper.mq5`,
  `TraderWatch_VideoStyle_GridScalper_v1_1.mq5` (+ .ex5 DISABLED).
- Backup penuh: `/home/mt5/ea-holygrid-backup-20261122/`
- `hg.ini` → `[Experts] enabled=0, allowlivetrading=0, active=0`, tiada chart autoload.
- Backup config: `HB/hg.ini.bak-ea-removed-20261122`

Terminal MT5 (service `mt5-holygrid`) **kekal berjalan** — ia sumber data harga
(XAUUSD tick) untuk app + bot auto-trade `traderwatch-mt5-auto`. Menhentikannya
akan mematikan feed & bot. Nama service tidak di-rename (tiada cron/script
bergantung padanya, tetapi rename = risiko tak perlu).

Sahkan selepas buang: `mt5_read.py account` = 37412125, `tick XAUUSD` hidup,
tiada expert log hari ini (tiada EA dimuat).

## Paper trade client
Client `abieidham@gmail.com` masuk paper league **sama macam ahli lain**:
baki maya $10,000, season 1, `is_owner:false`, leaderboard biasa. Tambahan
hanya kad MT5 + (bila trade enabled) checkbox "Take this trade" ke akaun dia.
