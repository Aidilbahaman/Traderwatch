-- 2026-11-20: Jadual diagnostik auth (sementara, untuk debug isu login bounce)
-- Beacon dari login.html / verify.html / member/auth.js: metadata sahaja
-- (event, UA, state storage, exp token) — TIADA credential dihantar.
-- Insert-only untuk anon/authenticated; baca hanya service key (admin).
-- DROP table ini selepas isu login selesai disiasat.

create table if not exists public.auth_diag (
  id bigint generated always as identity primary key,
  ts timestamptz not null default now(),
  event text not null,
  detail jsonb not null default '{}'::jsonb
);
alter table public.auth_diag enable row level security;
drop policy if exists "diag insert only" on public.auth_diag;
create policy "diag insert only" on public.auth_diag
  for insert to anon, authenticated with check (true);