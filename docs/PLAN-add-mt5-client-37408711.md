# Pelan: Tambah akaun MT5 RoboForex-Pro 37408711 (client) — dual account

## Keadaan semasa (evidence)
- Terminal MT5 (Wine) aktif: `mt5-holygrid.service` → `/home/mt5/.mt5`, login **37412125** (Ade Aidil), XAUUSD M1. **EA Holy Grid telah DIBUANG (2026-11-22)** — service cuma jalankan terminal untuk data harga + bot auto-trade. Nama service kekal `mt5-holygrid` (tak di-rename untuk elak risiko).
- Bot auto-trade `traderwatch-mt5-auto.service` guna `mt5.initialize()` tanpa credential → **ikut akaun terminal semasa** (37412125).
- MT5 Hub (FastAPI, `127.0.0.1:8000`, `hub.traderwatch.org`) guna SQLite `/home/ubuntu/mt5-hub/backend/dev.db`.
  - `accounts`: hanya id=1, user_id=3 (`aidilvevo@gmail.com`), login=37412125, mode=investor.
  - `MT5_BRIDGES=1:18812` → bridge rpyc read-only untuk akaun personal.
- Satu terminal MT5 hanya boleh login satu akaun → perlu **Wine prefix + terminal kedua** untuk client.
- Disk: 32 GB free; prefix sedia ada ~6.7 GB → clone sesuai.
- Trade password client: `<REDACTED - lihat credential vault>` (akan dienkrip AES-GCM sebelum disimpan; tidak dalam git).

## Matlamat
1. Akaun client 37408711 **tersimpan dalam MT5 Hub** (dashboard).
2. Akaun client **berjalan di terminal MT5 kedua**, login dengan trade password, **monitor sahaja (tiada EA)**.
3. Akaun personal 37412125 **tidak diganggu** — terminal, EA, bot auto-trade, bridge 18812 kekal.

## Langkah

### Fasa 0 — Backup (sebelum ubah)
- DB Hub: `cp dev.db dev.db.bak-20261122-client` (mtime + hash).
- `.env`: `cp .env .env.bak-...`.
- Snapshot status semasa: `account_info` 37412125, `systemctl is-active`, `ss -ltnp 18812` → rekod dalam `state/`.

### Fasa 1 — Daftar akaun di MT5 Hub
- `POST /api/v1/accounts` (JWT user 3) dengan:
  - `label`: `Abe Client (RoboForex)`, `broker`: `RoboForex`, `server`: `RoboForex-Pro`
  - `login`: `37408711`, `mode`: `trade`, `email`: `aidilvevo@gmail.com`
  - `password`: `<REDACTED - lihat credential vault>` → dienkrip oleh `encrypt_credentials()` (AES-GCM, key dari `.env`).
  - Token JWT: hasilkan dengan `create_access_token("3")` terus dari modul `app.security` (register ditutup; guna utiliti tempatan, bukan endpoint register).
- Sahkan: `GET /api/v1/accounts` tunjuk 2 akaun; `audit_log` ada `account.create login=37408711`.
- **Catatan:** `decrypt_credentials()` tiada caller — Hub simpan credential tapi tidak guna untuk login MT5.

### Fasa 2 — Wine prefix + terminal kedua (client)
- Clone prefix: `cp -a /home/mt5/.mt5 /home/mt5/.mt5-37408711` (owner mt5:mt5, 6.7 GB).
- Buat config bersih untuk client: `/home/mt5/.mt5-37408711/drive_c/HB/client.ini`
  ```ini
  [Startup]
  symbol = XAUUSD
  period = M1
  [Experts]
  enabled = 0
  allowlivetrading = 0
  active = 0
  ```
  (tiada `chart01`, tiada EA → monitor sahaja)
- **Pembersihan identiti dalam clone** (elak server fikir ini sesi duplicate):
  - Padam `config/accounts.dat` + `config/common.ini` dalam clone (terminal akan guna login dari `mt5.initialize(login=..., password=..., server=...)`).
  - Pastikan tiada rujukan `Z:\home\mt5\.mt5\` dalam registry clone (hanya ada `mt5setup.exe`, yang dikongsi dan OK).
- Log masuk akaun client: dijalankan sekali via `mt5.initialize(login=37408711, password=<vault>, server="RoboForex-Pro")` dalam prefix clone; script sementara dipadam selepas guna. Disahkan `account_info()` = 37408711 / RoboForex-Pro / **trade_allowed=false (disabled on server — investor password)**.
- Service systemd baru `/etc/systemd/system/mt5-client.service` (User=mt5, `WINEPREFIX=/home/mt5/.mt5-37408711`, `DISPLAY=:99`, **JANGAN** guna `mt5-autostart.sh` karena script itu `pkill terminal64.exe` — akan bunuh akaun personal). ExecStart terus `wine ...terminal64.exe /portable /config:.../HB/client.ini`, `Restart=always`, `RestartSec=20`.
- **Risiko:** `wineserver` dikongsi antara prefix. Semak `pgrep wineserver`; jika terminal client gagal sebab wineserver sibuk, tambah `WINEPREFIX` isolation (setiap prefix ada wineserver sendiri bila berbeza WINEPREFIX — wine memang support multi-prefix serentak).

### Fasa 3 — Bridge kedua untuk Hub
- Copy `hub_bridge_server.py` ke `/home/mt5/.mt5-37408711/drive_c/mt5work/`.
- Service user mt5 `/home/mt5/.config/systemd/user/hub-bridge-client.service`:
  - `Environment=WINEPREFIX=/home/mt5/.mt5-37408711`, `DISPLAY=:99`, `WINEDEBUG=-all`
  - `ExecStart=wine C:\Python311\python.exe C:\mt5work\hub_bridge_server.py 18813`
  - loopback sahaja, `MemoryMax=150M`, `Restart=always`.
- Enable `--user` service (loginctl user mt5 mesti ada session / linger; status current `hub-bridge` = inactive walaupun proses jalan manual → semak dan guna `loginctl enable-linger mt5` jika perlu).
- Update `/home/ubuntu/mt5-hub/backend/.env`: `MT5_BRIDGES=1:18812,2:18813` (id 2 = akaun client selepas Fasa 1). Backup dulu.
- Restart `mt5-hub-backend.service` (user systemd).
- Sahkan `GET /api/v1/accounts/2/summary` → login 37408711, status connected, equity/balance benar.

### Fasa 4 — Verifikasi akhir
- `python3 engine/mt5_read.py account` → masih 37412125 (personal tak berubah).
- `systemctl is-active mt5-holygrid mt5-client traderwatch-mt5-auto` → semua active.
- `ss -ltnp | grep -E '18812|18813'` → dua bridge dengar.
- Dashboard Hub (`hub.traderwatch.org`) → dua akaun, client `connected`.
- Log terminal client → `account 37408711` login, tiada EA loaded.
- Tiada password plaintext dalam git / fail dunia-boleh-baca (`grep` audit).

## Rollback
- Fasa 1: `cp dev.db.bak-... dev.db` + restore `.env`, restart backend.
- Fasa 2: `systemctl stop/disable mt5-client`, padam `/home/mt5/.mt5-37408711`.
- Fasa 3: restore `.env`, restart backend.
- Akaun personal tidak pernah disentuh (tiada pkill, tiada restart holygrid).

## Open questions / caveats
- `<REDACTED - lihat credential vault>` — status sekarang: **investor / read-only** ("disabled on server"). Client akan **deposit dulu** (2026-11-22). Selepas deposit: semak semula `trade_allowed`; jika masih false, client perlu generate **trade password** baru di portal RoboForex, kemudian saya tukar credential dalam Hub + login semula terminal client.
- Client **tiada EA** (monitor sahaja).
- Nama label "Abe Client (RoboForex)" — boleh tukar jika user mahu.
- Hub `status` field kekal `unknown` dalam DB (provider guna status dinamik) — ini behavior sedia ada, bukan bug.
