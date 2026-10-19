-- Add NZD/USD + BTC/USD to TraderWatch paid-tier signals.
-- Public/Free pair set remains unchanged.
-- Idempotent: safe to re-run.

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
        AND upper(regexp_replace(s.pair, '[^A-Za-z]', '', 'g')) IN
          ('XAUUSD','GBPUSD','EURUSD','USDJPY','AUDUSD','USDCAD','NZDUSD'))
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
