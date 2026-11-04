DROP FUNCTION IF EXISTS public.get_signals();
DROP FUNCTION IF EXISTS public.get_public_signals();

CREATE OR REPLACE FUNCTION public.get_signals()
RETURNS SETOF json AS $$
BEGIN
  RETURN QUERY
  SELECT to_jsonb(r) FROM (
    SELECT pair, side, entry, sl, tp, status, entry_at, closed, pips, r, posted_at, time, timeframe FROM public.signals ORDER BY posted_at DESC NULLS LAST
  ) r;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.get_public_signals()
RETURNS SETOF json AS $$
BEGIN
  RETURN QUERY
  SELECT to_jsonb(r) FROM (
    SELECT pair, side, entry, sl, tp, status, entry_at, posted_at, time, timeframe FROM public.signals WHERE (status = 'active' OR status = 'entry' OR status = 'pending') ORDER BY posted_at DESC NULLS LAST
  ) r;
END;
$$ LANGUAGE plpgsql STABLE;

GRANT EXECUTE ON FUNCTION public.get_signals() TO anon, service_role, authenticated;
GRANT EXECUTE ON FUNCTION public.get_public_signals() TO anon, service_role, authenticated;
ALTER FUNCTION public.get_signals() SET search_path = public, pg_temp;
ALTER FUNCTION public.get_public_signals() SET search_path = public, pg_temp;
