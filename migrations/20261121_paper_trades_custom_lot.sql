-- 2026-11-21: Paper trade custom lot — client boleh set saiz lot sendiri.
-- lot NULL = risk-% trade (1/2%); lot nombor = custom lot.
-- risk_usd = lot x |entry-sl| x contract mult (XAU=100,XAG=5000,BTC=1,forex=100000).
alter table public.paper_trades add column if not exists lot numeric;
