-- Per-account AI analysis counter (server-side, replaces browser-local localStorage).
-- Owner report 2026-11-21: "analyses made" was browser-local so new logins inherited
-- the previous account's count and the real owner's count appeared reset to 0.
-- This stores the count per user_id, incremented atomically by analyze-api.

create table if not exists public.user_analyses (
  user_id    uuid primary key,
  count      integer not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.user_analyses enable row level security;
drop policy if exists "read own analyses" on public.user_analyses;
create policy "read own analyses" on public.user_analyses
  for select using (auth.uid() = user_id);

-- Atomic increment (upsert). security definer so the API role can bump any uid.
create or replace function public.bump_analyses(p_uid uuid)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare n integer;
begin
  insert into public.user_analyses (user_id, count)
  values (p_uid, 1)
  on conflict (user_id)
  do update set count = public.user_analyses.count + 1, updated_at = now()
  returning count into n;
  return n;
end $$;

grant execute on function public.bump_analyses(uuid) to service_role, authenticated;