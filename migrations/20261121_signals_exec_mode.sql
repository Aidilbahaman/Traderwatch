-- 2026-11-21: Instant entry for AI LLM signals.
-- signals.exec_mode: 'pending' (default, SMC/model structural entries) or
-- 'market' (LLM signals — executed instantly at live price by mt5-pending.py).
-- Applied via Supabase management API on 2026-11-21.
ALTER TABLE public.signals
  ADD COLUMN IF NOT EXISTS exec_mode text NOT NULL DEFAULT 'pending';