# Akses MT5 melalui SSH Tunnel (pilihan C — paling selamat)

Tiada perubahan pada server. Tiada port terbuka ke internet.
VNC hanya boleh diakses melalui tunnel SSH yang anda buka sendiri.

---

## Langkah 1 — Buka tunnel (di PC anda)

**macOS / Linux** — buka Terminal:

```bash
ssh -L 5900:127.0.0.1:5900 ubuntu@43.163.100.247
```

**Windows** — buka PowerShell:

```powershell
ssh -L 5900:127.0.0.1:5900 ubuntu@43.163.100.247
```

Biarkan tetingkap ini **terbuka** sepanjang sesi. Jangan tutup.

---

## Langkah 2 — Sambung VNC viewer

### Pilihan A: VNC Viewer (percuma)

1. Muat turun: https://www.realvnc.com/en/connect/download/viewer/
2. Buka VNC Viewer
3. Alamat: `localhost:5900`
4. Password: `zXVBjisd`

### Pilihan B: Browser (tiada install)

Buka: https://novnc.com/noVNC/vnc.html

- Host: `localhost`
- Port: `5900`
- Password: `zXVBjisd`
- Klik **Connect**

---

## Langkah 3 — Login MT5

Dalam desktop MT5 yang terbuka:

1. Menu **File** → **Login to Trade Account**
2. Isi:
   - **Login:** (nombor akaun anda)
   - **Password:** (password trading anda)
   - **Server:** `RoboForex-Pro`
3. Klik **OK**
4. Tunggu — status bar bawah akan tunjuk baki akaun (bukan `0.00`)

---

## Selepas login berjaya

Beritahu saya. Saya akan:

1. Baca state MT5 dari server (baki, simbol, data harga)
2. Pasang Python Windows + pkg `MetaTrader5` dalam prefix wine
3. Uji `account_info()`, `symbol_info()`, `copy_rates_from_pos()`
4. Sambung ke bot TraderWatch

---

## Tutup tunnel

Tekan `Ctrl+C` dalam tetingkap SSH, atau tutup tetingkap itu.

Selepas tunnel ditutup, VNC tidak boleh diakses dari mana-mana — termasuk dari internet.

---

## Nota keselamatan

| | Status |
|---|---|
| Port 5900 terbuka ke internet | ❌ tidak (localhost sahaja) |
| Port 6080 terbuka | ❌ tidak (dimatikan) |
| Caddy route noVNC | ❌ dibuang |
| Encryption | ✅ SSH (AES) |
| Password melalui internet | ✅ dalam tunnel SSH |

Password VNC `zXVBjisd` hanya dihantar melalui tunnel SSH yang di-encrypt. Tiada risiko sniffing.

---

## Kalau SSH tak boleh connect

Kemungkinan:
- Port 22 disekat oleh firewall rangkaian anda → cuba rangkaian lain
- Kunci SSH berbeza → beritahu saya, saya semak `~/.ssh/authorized_keys`
- Perlu password SSH → beritahu saya, saya semak konfigurasi
