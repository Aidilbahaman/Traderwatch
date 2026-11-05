-- Fasa 4 — Confluence Engine: analysis runs, signals, audit
-- Tambahan SAHAJA. Tidak mengubah table `signals` sedia ada, tidak mengubah
-- RLS atau policy sedia ada. Semua jadual baharu berasingan sepenuhnya.
--
-- Reka bentuk ikut spec 02_DATA_SCHEMA_AND_FEATURES.md:
--   analysis_runs · signals (confluence) · signal_audits
-- Prefix jadual `cf_` supaya jelas ia enjin baharu, bukan sistem lama.

create extension if not exists "pgcrypto";

-- ---------- analysis_runs: rekod kekal setiap analisis ----------
create table if not exists public.cf_analysis_runs (
  id            uuid primary key default gen_random_uuid(),
  symbol        text not null,
  as_of         timestamptz not null,
  strategy_version text not null,
  feature_version  text not null,
  model_version    text,
  regime           text,
  regime_confidence numeric,
  bias             text,
  directional_score numeric,
  coverage_score    numeric,
  conflict_score    numeric,
  decision          text not null,
  reason_codes      jsonb default '[]'::jsonb,
  evidence          jsonb default '{}'::jsonb,
  setup             jsonb default '{}'::jsonb,
  gates             jsonb default '{}'::jsonb,
  data_quality      jsonb default '{}'::jsonb,
  input_snapshot_hash text,
  created_at       timestamptz not null default now()
);
create index if not exists cf_runs_symbol_time on public.cf_analysis_runs (symbol, as_of desc);
create index if not exists cf_runs_decision    on public.cf_analysis_runs (decision);

-- ---------- cf_signals: signal confluence (BERASINGAN dari signals lama) ----------
create table if not exists public.cf_signals (
  id             uuid primary key default gen_random_uuid(),
  analysis_run_id uuid references public.cf_analysis_runs(id) on delete set null,
  symbol         text not null,
  signal_type    text not null,           -- BUY · SELL · WAIT · NO_TRADE
  status         text not null default 'DRAFT',
  entry_min      numeric,
  entry_max      numeric,
  stop_loss      numeric,
  take_profit_1  numeric,
  take_profit_2  numeric,
  take_profit_3  numeric,
  risk_reward    numeric,
  confidence_label text,
  summary        text,
  valid_from     timestamptz,
  expires_at     timestamptz,
  published_at   timestamptz,
  published_by   text,
  outcome        jsonb,
  created_at     timestamptz not null default now()
);
create index if not exists cf_signals_symbol on public.cf_signals (symbol, created_at desc);
create index if not exists cf_signals_status on public.cf_signals (status);
create index if not exists cf_signals_private_lookup on public.cf_signals (symbol, status, published_at);

-- Status yang sah (constraint eksplisit supaya tiada nilai sampah)
do $$ begin
  alter table public.cf_signals
    add constraint cf_signals_status_chk
    check (status in ('DRAFT','PUBLISHED','ACTIVE','HIT_TP','HIT_SL',
                      'EXPIRED','INVALIDATED','CANCELLED'));
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.cf_signals
    add constraint cf_signals_type_chk
    check (signal_type in ('BUY','SELL','WAIT','NO_TRADE'));
exception when duplicate_object then null; end $$;

-- ---------- cf_signal_audits: log kekal setiap tindakan ----------
create table if not exists public.cf_signal_audits (
  id          uuid primary key default gen_random_uuid(),
  signal_id   uuid references public.cf_signals(id) on delete cascade,
  event_type  text not null,
  actor_id    text,
  event_time  timestamptz not null default now(),
  details     jsonb default '{}'::jsonb
);
create index if not exists cf_audits_signal on public.cf_signal_audits (signal_id, event_time desc);

-- ---------- RLS: admin sahaja (private mode) ----------
-- Enjin ini PRIVATE buat masa ini (permintaan Aidil: backtest dulu).
-- Service key bypass RLS; authenticated user biasa LANGSUNG tidak nampak.
alter table public.cf_analysis_runs  enable row level security;
alter table public.cf_signals        enable row level security;
alter table public.cf_signal_audits  enable row level security;

-- Tiada policy SELECT untuk authenticated = tiada akses langsung.
-- Admin guna service key (server-side). Ini paling selamat untuk private mode.
drop policy if exists "cf admin read runs" on public.cf_analysis_runs;
drop policy if exists "cf admin read signals" on public.cf_signals;

comment on table public.cf_analysis_runs is
  'Confluence Engine analysis runs (private, service-key only). Bukan kebarangkalian untung.';
comment on table public.cf_signals is
  'Confluence Engine signals. Private mode: tiada akses authenticated, admin guna service key.';
