# Cara Setup Stripe Connect Express (duit masuk akaun KAU)

## Masalah sekarang

Payment Link kau dibuat dalam **akaun Stripe abang** (`AI Web Development` /
`acct_1TboIXBt8VyL0G4S`). Semua bayaran member akan masuk akaun itu — kau
tak boleh withdraw sendiri, dan abang yang kena liability/tax.

**Penyelesaian:** Stripe Connect — kau buka akaun Stripe ** sendiri** (percuma),
link ia kepada page TraderWatch, duit masuk terus ke bank kau.

---

## Kenapa Connect (bukan "tukar nama" sahaja)

Stripe bind payout ke bank account berdaftar + identity verification. Kalau kau
tukar bank account ke bank kau pada akaun abang:

- Stripe akan minta verification owners (KPIC / MyKad)
- Kalau tak match → akaun disuspend atau ditolak

**Connect** avoidance tu sepenuhnya — kau ada akaun sendiri, Stripe verify
kau sendiri, payout terus ke bank kau.

---

## Langkah (15-20 minit)

### 1. Buka akaun Stripe sendiri

1. https://dashboard.stripe.com/register
2. Email kau (jangan email abang)
3. Negara: **Malaysia**
4. Jenis akaun: **Individual / Sole Proprietor** (paling cepat)
5. Stripe tanya maklumat peribadi:
   - Nama penuh (= MyKad)
   - No. KPIC
   - Alamat penuh
   - No. telefon
   - Bank account (debit/credit) — **bank kau**

### 2. Lengkapkan onboarding

Stripe akan minta:
- **Identity verification** — upload MyKad (depan & belakang)
- **Business details** — boleh tulis "Individual", website TraderWatch
- **Statement descriptor** — contoh: `TRADERWATCH` (muncul pada statement bank member)
- **Payout schedule** — weekly atau monthly (weekly recommended)

Payouts aktif biasanya **sehari-dua** selepas verification lengkap.

### 3. Aktifkan Stripe Connect pada akaun kau

1. https://dashboard.stripe.com/connect
2. Klik **Enable Connect**
3. Pilih **Express** (Stripe handle onboarding member/kustomer — kau tak perlu
   collect KYB member)
4. Set platform country = Malaysia, currency = MYR

### 4. Jana `client_secret` untuk Stripe Payment Link pada akaun kau

Penting: Payment Link mesti **dibuat dalam akaun KAU**, bukan akaun abang.

1. https://dashboard.stripe.com/payment-links → **Create payment link**
2. Buat **2 link sahaja** (Free tidak perlu payment):
   - **Pro** — $20 / RM 82 (atau harga kau)
   - **Max** — $50 / RM 204
3. **Payment method types** — enable:
   - Card
   - FPX (Malaysian banks)
   - Google Pay / Apple Pay
   - Touch 'n Go eWallet (kalau ada Malaysia support)
4. Copy link URL (contoh `https://buy.stripe.com/aFaXXXX...`)

### 5. Update `config.js`

Ganti URL dalam `checkoutUrls` (free kekal empty — dia bukan paid plan):

```js
checkoutUrls: {
  free: "",
  pro:  "https://buy.stripe.com/YAU_PRO_DALAM_AKAUN_KAU",
  max:  "https://buy.stripe.com/YAU_MAX_DALAM_AKAUN_KAU"
}
```

Aku boleh update automatik bila kau hantar URL baru.

### 6. Test

1. Buka `https://aidilbahaman.github.io/Traderwatch/subscribe-stripe.html?plan=pro`
2. Klik butang → Stripe checkout load
3. Bayar dengan test card: `4242 4242 4242 4242` (exp any, CVC any)
4. Semak Stripe Dashboard → Payments → ada transaksi
5. Semak member dashboard → plan auto-upgrade (webhook aktif)

### 7. Webhook (sudah ada, cuma tukar endpoint secret)

Stripe Dashboard → Webhooks → Add endpoint:
```
URL: https://vicfiftvhxemuhxxmkxk.supabase.co/functions/v1/stripe-webhook
Events:
  checkout.session.completed
  customer.subscription.updated
  customer.subscription.deleted
```

Copy signing secret (`whsec_...`) → hantar kat Bob (aku set secret).

---

## Alternatif lebih mudah (kalau Connect terlalu ribet)

### Pilihan A: Payout manual dari abang

1. Kau guna akaun abang & link dia (sudah ada)
2. Member bayar → masuk akaun abang
3. Abang transfer RM balik ke bank kau setiap minggu/bulan

**Kelebihan:** Guna terus yang ada, zero setup.
**Kelemahan:** Manual, prone to disputes, tax unclear, abang pegang liability.

### Pilihan B: Abang buat **Stripe Custom** account, transfer ke kau

1. Stripe Dashboard abang → Settings → payments → transfers
2. Create a **destination** account (connect account id)
3. Payment Link → `transfer_data.destination` = id kau

**Kelebihan:** Duit split automatik.
**Kelemahan:** Kau masih kena onboard Stripe (KYC), sama seperti Connect.

### Pilihan C: Guna gateway lain yang ada **payout MYR ke bank kau**

Contoh: **Dolocatece / Billplz / Toyyibpay / LenongPay**

- Ada Malaysian payment gateway yang allow payout ke bank kau **tanpa** Stripe
- Member boleh bayar FPX / DuitNow / Touch 'n Go
- Payout automatik ke bank Malaysia
- **Fee** biasanya 2-3% (Stripe juga ~3% + RM0.50)

---

## Ringkasan

| Cara | Duit masuk | Setup | KYC |
|---|---|---|---|
| **Stripe Connect Express** | Akaun kau | 15 minit | KAU |
| **Akaun abang + payout manual** | Akaun abang → manual | 0 minit | ABANG |
| **Stripe Custom transfer** | Split automatik | 30 minit | KAU + ABANG |
| **Billplz / Toyyibpay** | Akaun kau | 30 minit | KAU |

**Rekomendasi:** **Stripe Connect Express** — kau ada email & MyKad, tak perlu
tunggu abang, payout automatik ke bank kau, tapi liabiliti 100% kau.

---

## Nota

- Tiada Stripe key dalam repo git.
- `STRIPE_RESTRICTED_KEY` & `STRIPE_PUBLISHABLE_KEY` disimpan dalam
  `/home/ubuntu/.secrets/stripe.env` (chmod 600).
- Supabase Edge Function `stripe-webhook` sudah deployed & live.