-- SQL migration for TraderWatch — run in Supabase SQL Editor
-- Fixes: get_signals() / get_public_signals() RPC missing (404)
-- Source: signal-status.json + mt5-orders.json schema

CREATE OR REPLACE FUNCTION public.get_signals()
RETURNS SETOF json AS $$
BEGIN
  RETURN QUERY
  SELECT to_jsonb(r) FROM (
    SELECT
      pair,
      side,
      entry,
      sl,
      tp,
      status,
      entry_at,
      closed,
      pips,
      r,
      posted_at,
      time,
      timeframe
    FROM public.signals  -- adjust table name if different
    ORDER BY posted_at DESC NULLS LAST
  ) r;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.get_public_signals()
RETURNS SETOF json AS $$
BEGIN
  RETURN QUERY
  SELECT to_jsonb(r) FROM (
    SELECT
      pair,
      side,
      entry,
      sl,
      tp,
      status,
      entry_at,
      posted_at,
      time,
      timeframe
    FROM public.signals
    WHERE (status = 'active' OR status = 'entry' OR status = 'pending')
    ORDER BY posted_at DESC NULLS LAST
  ) r;
END;
$$ LANGUAGE plpgsql STABLE;

-- Grant execute to anon/auth if needed; adjust RLS policies separately.
GRANT EXECUTE ON FUNCTION public.get_signals() TO anon, service_role, authenticated;
GRANT EXECUTE ON FUNCTION public.get_public_signals() TO anon, service_role, authenticated;

ALTER FUNCTION public.get_signals() SET search_path = public, pg_temp;
ALTER FUNCTION public.get_public_signals() SET search_path = public, pg_temp;

COMMENT ON FUNCTION public.get_signals() IS 'TraderWatch signal feed for members.html (auth required)';
COMMENT ON FUNCTION public.get_public_signals() IS 'Public signal feed (open)';
