-- 2026-11-21: Leaderboard identity by user_id (not username).
-- Problem: one account (email + Google + GitHub identities) showed as TWO
-- people ("Aidil" and "Aidil Bahaman") because Google sign-in overwrites
-- user_metadata.name/full_name, and rows stored the name at write time.
-- Fix: group by user_id; display the newest username per user. Historical
-- paper_trades/chat_messages rows normalized to each user's latest name.
-- Owner also got a canonical user_metadata.username (display_name priority)
-- so future OAuth metadata overwrites cannot drift the display name.
-- Applied via Supabase management API on 2026-11-21.

drop function if exists public.get_leaderboard(int);
create or replace function public.get_leaderboard(p_season int default 1)
returns table(user_id uuid, username text, trades bigint, wins bigint, net_r numeric, win_rate numeric, profit_usd numeric)
language sql stable security definer set search_path=public as $$
  select user_id,
         (array_agg(username order by opened_at desc))[1] as username,
         count(*) filter (where status in ('tp','sl','be')) as trades,
         count(*) filter (where status='tp') as wins,
         coalesce(sum(r_result) filter (where status in ('tp','sl','be')),0) as net_r,
         case when count(*) filter (where status in ('tp','sl'))>0
              then round(100.0*count(*) filter (where status='tp')/count(*) filter (where status in ('tp','sl')),1)
              else 0 end as win_rate,
         coalesce(sum(r_result*risk_usd) filter (where status in ('tp','sl','be')),0) as profit_usd
  from public.paper_trades
  where season=p_season and status in ('tp','sl','be')
  group by user_id
  having count(*) filter (where status in ('tp','sl','be'))>0
  order by net_r desc
  limit 50;
$$;

update public.paper_trades p set username = latest.username
from (select distinct on (user_id) user_id, username from public.paper_trades order by user_id, opened_at desc) latest
where p.user_id = latest.user_id and p.username <> latest.username;

update public.chat_messages c set username = latest.username
from (select distinct on (user_id) user_id, username from public.paper_trades order by user_id, opened_at desc) latest
where c.user_id = latest.user_id and c.username <> latest.username;