-- TraderWatch: Automation Trade (single tier) — all AI signals on website + MT5.
-- Removes: private-signal filter, old plan gating (free/pro/max), pair allowlist,
--          per-plan row cap. Every authenticated member (Automation Trade) sees
--          all verified signals for the configured focus pairs within 4 days.

-- 0) Unflag existing AI signals so the website status updater (signal-status.py)
--    and this RPC can see them. New signals are inserted verified + non-private.
update public.signals set is_private = false where is_private is true;

-- 1) Member RPC: no private filter, no plan gating, no cap, all focus pairs.
drop function if exists public.get_signals();
create function public.get_signals()
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
    and s.posted_at >= (now() - interval '4 days')
  order by s.posted_at desc, s.id desc
  limit 200;
$$;

revoke all on function public.get_signals() from public, anon;
grant execute on function public.get_signals() to authenticated;

-- 2) Public RPC (landing / unauthenticated preview): same rule.
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
  where s.verified is true
    and s.posted_at >= (now() - interval '4 days')
  order by s.posted_at desc, s.id desc
  limit 50;
$$;

revoke all on function public.get_public_signals() from public;
grant execute on function public.get_public_signals() to anon, authenticated;

-- 3) RLS: direct table read for authenticated members — no private/plan/pair gating.
drop policy if exists "members read verified signals" on public.signals;
create policy "members read verified signals" on public.signals
for select to authenticated
using (
  auth.uid() is not null
  and verified is true
  and posted_at >= (now() - interval '4 days')
);
