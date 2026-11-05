-- TraderWatch: private AI signals NEVER in public/member feed (permanent fix)
-- Idempotent. Uses is_private column, not hardcoded ID lists in app code.

alter table if exists public.signals
  add column if not exists is_private boolean not null default false;

-- Flag existing private AI signals (from state/private-signals.json registry)
update public.signals set is_private = true where id in (214, 215, 216, 217, 218, 219, 220, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 235, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255, 256, 257);

-- RPC: hide private AI signals from member feed
drop function if exists public.get_signals();
create function public.get_signals()
returns table (
  id bigint, pair text, side text, entry numeric, sl numeric, tp numeric,
  timeframe text, posted_at timestamptz, verified boolean
)
language sql stable security definer set search_path = public, pg_temp as $$
  with me as (
    select coalesce((select p.plan from public.profiles p where p.id = auth.uid()), 'free') as plan
  ),
  cap as (
    select case when me.plan = 'max' then 1000 when me.plan = 'pro' then 10 else 3 end as n from me
  ),
  allowed as (
    select s.*, row_number() over (order by s.posted_at desc, s.id desc) as rn
    from public.signals s, me
    where auth.uid() is not null
      and s.verified is true
      and s.is_private is not true
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

drop function if exists public.get_public_signals();
create function public.get_public_signals()
returns table (
  id bigint, pair text, side text, entry numeric, sl numeric, tp numeric,
  timeframe text, posted_at timestamptz, verified boolean
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
    and s.is_private is not true
    and s.posted_at >= (now() - interval '4 days')
  order by s.posted_at desc, s.id desc
  limit 50;
$$;

revoke all on function public.get_public_signals() from public, anon;
grant execute on function public.get_public_signals() to authenticated;

-- RLS: direct table access also must not expose private AI signals
drop policy if exists "members read verified signals" on public.signals;
create policy "members read verified signals" on public.signals
for select to authenticated
using (
  auth.uid() is not null
  and verified is true
  and is_private is not true
  and posted_at >= (now() - interval '4 days')
  and (
    upper(regexp_replace(pair, '[^A-Za-z]', '', 'g')) in ('XAUUSD','GBPUSD','EURUSD')
    or coalesce((select p.plan from public.profiles p where p.id = auth.uid()), 'free') in ('pro','max')
  )
);
