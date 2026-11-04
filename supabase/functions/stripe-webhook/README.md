# Stripe webhook (Supabase Edge Function)

Auto-activate member plan selepas Stripe payment berjaya.

## Deploy

```bash
supabase login                 # guna SUPABASE_ACCESS_TOKEN dari ~/.secrets/supabase.env
supabase link --project-ref vicfiftvhxemuhxxmkxk
supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_xxxxx
supabase functions deploy stripe-webhook
```

`SUPABASE_URL` dan `SUPABASE_SERVICE_ROLE_KEY` di-set automatik oleh Supabase.

## Stripe Dashboard setup

1. **Developers -> Webhooks -> Add endpoint**
   - URL: `https://vicfiftvhxemuhxxmkxk.supabase.co/functions/v1/stripe-webhook`
   - Events: `checkout.session.completed`,
     `customer.subscription.updated`,
     `customer.subscription.deleted`
2. Salin **signing secret** (`whsec_...`) -> `supabase secrets set STRIPE_WEBHOOK_SECRET=...`
3. **Setiap Payment Link** buka -> **Client reference ID** atau
   **URL parameter** `client_reference_id={{{SUBSCRIBER_ID}}}` — tapi Payment
   Link tidak menyokong placeholder Supabase auth uid.

   **Cara page ini berfungsi:** `subscribe-stripe.html` menghantar
   `client_reference_id=<auth uid>` sebagai query param. Stripe Payment Link
   meneruskan query param itu ke Checkout Session, jadi webhook dapat uid.

   Uji: buka `?plan=pro`, klik butang, semak log Stripe ->
   `checkout.session.completed` ada `client_reference_id`.

## Verify

```bash
stripe trigger checkout.session.completed   # Stripe CLI
stripe listen --forward-to vicfiftvhxemuhxxmkxk.supabase.co/functions/v1/stripe-webhook
```

## Nota keselamatan

- Tiada Stripe secret key dalam repo. `STRIPE_WEBHOOK_SECRET` disimpan sebagai
  Supabase secret, bukan dalam git.
- `plan` only accepts `free` / `pro` / `max` (whitelist) — nilai lain diabaikan.
- Replay >5 minit ditolak (timestamp check).
- Signature disahkan dengan HMAC-SHA256 + timing-safe compare.
