-- Allow M15 signals alongside H1.
-- The old check constraint only permitted H1/M1, so every M15 insert failed.
-- M1 stays allowed so historical rows remain valid.
-- Idempotent: safe to re-run.

DO $$
BEGIN
  ALTER TABLE public.signals DROP CONSTRAINT IF EXISTS signals_timeframe_check;
EXCEPTION WHEN undefined_object THEN
  NULL;
END $$;

ALTER TABLE public.signals
  ADD CONSTRAINT signals_timeframe_check
  CHECK (timeframe IN ('H1', 'M1', 'M15'));
