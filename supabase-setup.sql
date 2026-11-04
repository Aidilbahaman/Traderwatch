-- TraderWatch: run this once in Supabase > SQL Editor > New query > Run

-- 1) Member profiles (one row per account, created automatically at sign-up)
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  name text,
  email text,
  plan text not null default 'free' check (plan in ('free','pro')),
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;

-- Members can read their own row only. There is NO update policy, so nobody
-- can make themselves Pro from the website. You change plans in the dashboard.
drop policy if exists "read own profile" on public.profiles;
create policy "read own profile" on public.profiles
  for select using (auth.uid() = id);

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, name, email)
  values (new.id, new.raw_user_meta_data->>'name', new.email);
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 2) Signals table (you add rows here in Table Editor)
create table if not exists public.signals (
  id bigint generated always as identity primary key,
  pair text not null,                              -- e.g. XAU/USD
  side text not null check (side in ('BUY','SELL')),
  entry text not null,
  sl text not null,
  tp text not null,
  posted_at timestamptz not null default now()
);
alter table public.signals enable row level security;
-- No select policy on purpose: the website can only read signals through
-- get_signals() below, which hides Pro signals from Free members.

create or replace function public.get_signals()
returns table (id bigint, pair text, side text, entry text, sl text, tp text, posted_at timestamptz, locked boolean)
language sql stable security definer set search_path = public as $$
  with me as (
    select coalesce((select p.plan from public.profiles p where p.id = auth.uid()), 'free') as plan
  ),
  ranked as (
    select s.*, row_number() over (order by s.posted_at desc) as rn
    from public.signals s
  )
  select r.id,
         r.pair,
         case when me.plan = 'pro' or r.rn = 1 then r.side  end,
         case when me.plan = 'pro' or r.rn = 1 then r.entry end,
         case when me.plan = 'pro' or r.rn = 1 then r.sl    end,
         case when me.plan = 'pro' or r.rn = 1 then r.tp    end,
         r.posted_at,
         not (me.plan = 'pro' or r.rn = 1)
  from ranked r, me
  where auth.uid() is not null
  order by r.posted_at desc
  limit 30;
$$;

revoke all on function public.get_signals() from public, anon;
grant execute on function public.get_signals() to authenticated;

-- Make someone Pro after you confirm their payment:
--   update public.profiles set plan = 'pro' where email = 'member@example.com';
-- Put them back on Free:
--   update public.profiles set plan = 'free' where email = 'member@example.com';
