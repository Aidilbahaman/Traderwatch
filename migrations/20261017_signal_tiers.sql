-- TraderWatch signal tiers migration for Supabase
-- Run once in Supabase > SQL Editor > New query > Run

-- Step 1: allow max plan
DO $$
BEGIN
  ALTER TABLE public.profiles DROP CONSTRAINT profiles_plan_check;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_plan_check CHECK (plan IN ('free','pro','max'));

-- Step 2: upgrade signals table
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS timeframe text DEFAULT 'H1';
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS verified boolean DEFAULT false;

DO $$
BEGIN
  ALTER TABLE public.signals DROP CONSTRAINT signals_timeframe_check;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE public.signals
  ADD CONSTRAINT signals_timeframe_check CHECK (timeframe IN ('H1','M1'));

-- Step 3: member RPC, plan-aware, verified only
DROP FUNCTION IF EXISTS public.get_signals();

CREATE FUNCTION public.get_signals()
RETURNS TABLE (id bigint, pair text, timeframe text, side text, entry text, sl text, tp text, posted_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT s.id, s.pair, s.timeframe, s.side, s.entry, s.sl, s.tp, s.posted_at
  FROM public.signals s
  WHERE auth.uid() IS NOT NULL
    AND s.verified IS TRUE
    AND s.posted_at >= (date_trunc('day', now() AT TIME ZONE 'Asia/Kuala_Lumpur') AT TIME ZONE 'Asia/Kuala_Lumpur')
    AND s.posted_at < ((date_trunc('day', now() AT TIME ZONE 'Asia/Kuala_Lumpur') AT TIME ZONE 'Asia/Kuala_Lumpur') + interval '1 day')
    AND (
      ((SELECT p.plan FROM public.profiles p WHERE p.id = auth.uid()) = 'free'
        AND upper(regexp_replace(s.pair, '[^A-Za-z]', '', 'g')) IN ('XAUUSD','GBPUSD','EURUSD'))
      OR
      (COALESCE((SELECT p.plan FROM public.profiles p WHERE p.id = auth.uid()), 'free') IN ('pro','max')
        AND upper(regexp_replace(s.pair, '[^A-Za-z]', '', 'g')) IN ('XAUUSD','GBPUSD','EURUSD','USDJPY','AUDUSD','USDCAD'))
      OR
      ((SELECT p.plan FROM public.profiles p WHERE p.id = auth.uid()) IS NULL
        AND upper(regexp_replace(s.pair, '[^A-Za-z]', '', 'g')) IN ('XAUUSD','GBPUSD','EURUSD'))
    )
  ORDER BY s.posted_at DESC, s.id DESC
  LIMIT CASE
    WHEN (SELECT p.plan FROM public.profiles p WHERE p.id = auth.uid()) = 'pro' THEN 10
    WHEN (SELECT p.plan FROM public.profiles p WHERE p.id = auth.uid()) = 'max' THEN 1000
    ELSE 3 END;
$$;

REVOKE ALL ON FUNCTION public.get_signals() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.get_signals() TO authenticated;

-- Step 4: public RPC for landing page
CREATE OR REPLACE FUNCTION public.get_public_signals()
RETURNS TABLE (id bigint, pair text, timeframe text, side text, entry text, sl text, tp text, posted_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT s.id, s.pair, s.timeframe, s.side, s.entry, s.sl, s.tp, s.posted_at
  FROM public.signals s
  WHERE s.verified IS TRUE
    AND upper(regexp_replace(s.pair, '[^A-Za-z]', '', 'g')) IN ('XAUUSD','GBPUSD','EURUSD')
    AND s.posted_at >= (date_trunc('day', now() AT TIME ZONE 'Asia/Kuala_Lumpur') AT TIME ZONE 'Asia/Kuala_Lumpur')
    AND s.posted_at < ((date_trunc('day', now() AT TIME ZONE 'Asia/Kuala_Lumpur') AT TIME ZONE 'Asia/Kuala_Lumpur') + interval '1 day')
  ORDER BY s.posted_at DESC, s.id DESC
  LIMIT 3;
$$;

REVOKE ALL ON FUNCTION public.get_public_signals() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_public_signals() TO anon, authenticated;
