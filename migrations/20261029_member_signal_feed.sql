-- TraderWatch member signal feed repair
-- Safe/idempotent: no DROP TABLE/COLUMN, no writes to signals.
-- Fixes old RPCs that referenced non-existent signals.status.

-- Direct table access is read-only and limited to verified, recent, plan-allowed rows.
alter table if exists public.signals enable row level security;
grant select on table public.signals to authenticated;
drop policy if exists "members read verified signals" on public.signals;
create policy "members read verified signals" on public.signals
for select to authenticated
using (
  auth.uid() is not null
  and verified is true
  and posted_at >= (now() - interval '4 days')
  and (
    upper(regexp_replace(pair, '[^A-Za-z]', '', 'g')) in ('XAUUSD','GBPUSD','EURUSD')
    or coalesce((select p.plan from public.profiles p where p.id = auth.uid()), 'free') in ('pro','max')
  )
);

-- The member feed RPC is the preferred browser path. It does not reference status;
-- lifecycle status remains in signal-status.json and is joined client-side.
drop function if exists public.get_signals();
create function public.get_signals()
returns table (
  id bigint,
  pair text,
  side text,
  entry numeric,
  sl numeric,
  tp numeric,
  timeframe text,
  posted_at timestamptz,
  verified boolean
)
language sql stable security definer set search_path = public, pg_temp as $$
  with me as (
    select coalesce((select p.plan from public.profiles p where p.id = auth.uid()), 'free') as plan
  ),
  cap as (
    select case when me.plan = 'max' then 1000 when me.plan = 'pro' then 10 else 3 end as n from me
  ),
  allowed as (
    select s.*,
           row_number() over (order by s.posted_at desc, s.id desc) as rn
    from public.signals s, me
    where auth.uid() is not null
      and s.verified is true
      and s.posted_at >= (now() - interval '4 days')
      and (
        upper(regexp_replace(s.pair, '[^A-Za-z]', '', 'g')) in ('XAUUSD','GBPUSD','EURUSD')
        or me.plan in ('pro','max')
      )
  )
  select a.id, a.pair, a.side,
         nullif(a.entry::text, '')::numeric,
         nullif(a.sl::text, '')::numeric,
         nullif(a.tp::text, '')::numeric,
         a.timeframe, a.posted_at, a.verified
  from allowed a, cap c
  where a.rn <= c.n
  order by a.posted_at desc, a.id desc;
$$;

revoke all on function public.get_signals() from public, anon;
grant execute on function public.get_signals() to authenticated;

-- Kept for older clients, but still requires authentication and uses the real schema.
drop function if exists public.get_public_signals();
create function public.get_public_signals()
returns table (
  id bigint,
  pair text,
  side text,
  entry numeric,
  sl numeric,
  tp numeric,
  timeframe text,
  posted_at timestamptz,
  verified boolean
)
language sql stable security definer set search_path = public, pg_temp as $$
  select s.id, s.pair, s.side,
         nullif(s.entry::text, '')::numeric,
         nullif(s.sl::text, '')::numeric,
         nullif(s.tp::text, '')::numeric,
         s.timeframe, s.posted_at, s.verified
  from public.signals s
  where auth.uid() is not null
    and s.verified is true
    and s.posted_at >= (now() - interval '4 days')
  order by s.posted_at desc, s.id desc
  limit 50;
$$;

revoke all on function public.get_public_signals() from public, anon;
grant execute on function public.get_public_signals() to authenticated;
