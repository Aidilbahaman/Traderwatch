-- Push notification subscriptions (Web Push / VAPID). One row per endpoint;
-- user may subscribe multiple browsers. kinds: 'tpsl' | 'all' (incl verdicts).
create table if not exists public.push_subs (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  kinds text not null default 'tpsl',
  created_at timestamptz not null default now()
);
alter table public.push_subs enable row level security;
create policy "own subs" on public.push_subs for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
