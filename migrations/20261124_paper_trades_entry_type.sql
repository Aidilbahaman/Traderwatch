-- 2026-11-24: Manage Your Risk — jenis entry ikut risk level.
-- market = instant fill (high risk); buy_limit/sell_limit = pending order
-- (low/medium risk) yang menunggu harga retrace. Resolver fill-first sudah
-- menyokong pending: expired 6j jika tak pernah terisi, tiada R impact.
alter table public.paper_trades add column if not exists entry_type text default 'market';
