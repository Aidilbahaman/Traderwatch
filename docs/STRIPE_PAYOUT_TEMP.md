# Aliran payout sementara (akaun Stripe rakan kongsi)

## Situasi sekarang

Payment Link dibuat dalam **akaun Stripe rakan kongsi** (`AI Web Development`).
Semua bayaran member masuk akaun itu. Kau belum boleh onboard akaun Stripe
sendiri kerana IC belum ada.

## Flow payout (untuk sementara)

```
Member bayar (RM 20 / RM 50)
    ↓
Masuk akaun Stripe RAKAN KONGGI   ← Stripe dikira "pending"
    ↓
Rakan kongsi transfer ke bank KAU  ← payout_from_that_account
    ↓
Kau urus bayaran member (baki, kos, dll)
```

Webhook akan hantar notifikasi Telegram setiap kali duit masuk, supaya kau
tahu reference + jumlah untukDeclare pend半个小时。

## Notifikasi webhook

Setiap `checkout.session.completed` → Telegram admin:

```
💰 <b>Stripe payment masuk</b>
Plan: PRO
Member: member@email.com
Jumlah: 20.00 MYR
Session: cs_live_...
Bayar: paid

👉 Transfer kepada KAU dulu (akaun Stripe ini milik rakan kongsi).
Selepas duit sampai, urus bayaran member sendiri.
```

## ⚠️ Perkara perlu selesaikan dengan rakan kongsi

| Perkara | Kenapa |
|---|---|
| **Payout ke bank kau** | Rakan kongsi perlu tambah bank account kau di Stripe Settings → Payouts |
| **Timing** | Payout Stripe biasanya 2-7 hari selepas charge (rolling reserve 7 hari untuk akaun baru) |
| **Amount** | Rakan kongsi kena guna — pastikan dia setuju sebelum configure |
| **Tax** | Stripe report hanya迟Tx dan settlement pada akaun dia |
| **Refund** | Kalau member minta refund, ia keluar dari akaun dia |

## Untuk autoimmune (pilihan masa depan)

Stripe **separate charges & transfers** — rakan kongsi configure payout
destination ke bank kau:

```
Stripe Dashboard (rakan kongsi) → Settings → payouts → bank account (bank kau)
```

Selepas itu, bayaran member masuk akaun dia, dan dia cuma klik **Payout** untuk
hantar ke bank kau. Ataum boleh guna Payouts API untuk auto-payout setiap hari.

## Bila IC dah ada

Bila kau boleh onboard akaun Stripe sendiri:
1. Buka akaun Stripe Sendiri (Malaysia)
2. Payment Link baru dalam akaun kau
3. Ganti URL dalam `config.js` — webhook tak perlu berubah
4.|archive rakan kongsi dari flow

Guide penuh: `docs/STRIPE_CONNECT_SETUP.md`
