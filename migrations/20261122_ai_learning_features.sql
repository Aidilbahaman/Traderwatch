-- AI closed-loop learning: capture setup features at trade-open so the
-- resolver's TP/SL outcome can teach the model which patterns work.
alter table public.paper_trades
  add column if not exists ai_tf text,
  add column if not exists ai_conf numeric,
  add column if not exists ai_bos text,
  add column if not exists ai_choch boolean,
  add column if not exists ai_fvg int,
  add column if not exists ai_rr numeric,
  add column if not exists ai_atr numeric,
  add column if not exists ai_hour int;
