-- Widen the member signal window from "today only" to the last 4 days.
--
-- Why: get_signals() filtered posted_at to the current Kuala Lumpur day, so a
-- position that was still open disappeared from the dashboard at midnight, and
-- a closed one never showed its result the next morning. The engine tracks
-- status in signal-status.json; the dashboard now decides what to keep, so the
-- RPC must actually return the recent rows.
--
-- Plan gating, pair allow-lists and per-plan limits are unchanged.
-- Idempotent: safe to re-run.

DROP FUNCTION IF EXISTS public.get_signals();

CREATE FUNCTION public.get_signals()
RETURNS TABLE (id bigint, pair text, timeframe text, side text, entry text, sl text, tp text, posted_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT s.id, s.pair, s.timeframe, s.side, s.entry, s.sl, s.tp, s.posted_at
  FROM public.signals s
  WHERE auth.uid() IS NOT NULL
    AND s.verified IS TRUE
    AND s.posted_at >= (now() - interval '4 days')
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
