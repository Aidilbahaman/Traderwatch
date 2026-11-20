-- 2026-11-20: Paper Trading League — Fasa 1 (owner request).
-- Ahli buka "paper trade" dengan modal maya $10,000; outcome (TP/SL/BE)
-- di-resolve AUTOMATIK oleh engine/paper-league-resolver.py dari harga
-- sq-bars.db sebenar — ahli TIDAK boleh self-report / tipu.
-- Leaderboard guna Net R (gandaan risiko) supaya adil untuk semua modal.
--
-- English adalah bahasa utama app. Tiada wang sebenar terlibat.
-- Rollback: drop function get_leaderboard; drop table paper_trades.

create table if not exists public.paper_trades (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  username text not null,
  pair text not null,
  side text not null check (side in ('BUY','SELL')),
  entry numeric not null,
  sl numeric not null,
  tp numeric not null,
  risk_pct numeric not null default 1,
  risk_usd numeric not null,
  status text not null default 'open' check (status in ('open','tp','sl','be','expired')),
  r_result numeric,
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  season int not null default 1
);
create index if not exists paper_trades_user on public.paper_trades(user_id, opened_at desc);
create index if not exists paper_trades_open on public.paper_trades(status) where status='open';
create index if not exists paper_trades_season on public.paper_trades(season, status);
alter table public.paper_trades enable row level security;
drop policy if exists "read own trades" on public.paper_trades;
create policy "read own trades" on public.paper_trades for select using (auth.uid()=user_id);
drop policy if exists "insert own trades" on public.paper_trades;
create policy "insert own trades" on public.paper_trades for insert with check (auth.uid()=user_id);

create or replace function public.get_leaderboard(p_season int default 1)
returns table(username text, trades bigint, wins bigint, net_r numeric, win_rate numeric, profit_usd numeric)
language sql stable security definer set search_path=public as $$
  select username,
         count(*) filter (where status in ('tp','sl','be')) as trades,
         count(*) filter (where status='tp') as wins,
         coalesce(sum(r_result) filter (where status in ('tp','sl','be')),0) as net_r,
         case when count(*) filter (where status in ('tp','sl'))>0
              then round(100.0*count(*) filter (where status='tp')/count(*) filter (where status in ('tp','sl')),1)
              else 0 end as win_rate,
         coalesce(sum(r_result*risk_usd) filter (where status in ('tp','sl','be')),0) as profit_usd
  from public.paper_trades
  where season=p_season and status in ('tp','sl','be')
  group by username
  having count(*) filter (where status in ('tp','sl','be'))>0
  order by net_r desc
  limit 50;
$$;
revoke all on function public.get_leaderboard(int) from public, anon;
grant execute on function public.get_leaderboard(int) to authenticated, service_role;