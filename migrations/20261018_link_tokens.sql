-- TraderWatch: one-time link tokens (Option B / security upgrade).
-- Replaces the UUID-in-URL pattern with a short-lived random token.
-- A token is valid for 15 minutes and is deleted after one successful use.

-- Requires pgcrypto for gen_random_bytes (usually already enabled on Supabase).
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS public.link_tokens (
  token text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  used_at timestamptz
);

COMMENT ON TABLE public.link_tokens IS
  'One-time Telegram link tokens. Expires after 15 min or one use.';

-- Helper: generate and insert a fresh token for a user.
-- Returns the token string so the caller can build the deep-link URL.
CREATE OR REPLACE FUNCTION public.create_link_token(p_user_id uuid)
RETURNS text
LANGUAGE plpgsql security definer set search_path = public, extensions as $$
DECLARE
  new_token text;
BEGIN
  -- Invalidate any existing unused tokens for this user.
  DELETE FROM public.link_tokens WHERE user_id = p_user_id AND used_at IS NULL;
  -- 18 random bytes -> base64 -> strip +/=/ so it is safe in a URL.
  -- Yields a 24-char [A-Za-z0-9] token.
  new_token := translate(
    encode(extensions.gen_random_bytes(18), 'base64'), '+/=', '');
  INSERT INTO public.link_tokens (token, user_id)
  VALUES (new_token, p_user_id);
  RETURN new_token;
END $$;

REVOKE ALL ON FUNCTION public.create_link_token(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_link_token(uuid) TO authenticated;

-- Cleanup: expire old tokens (run daily or via cron).
-- PostgreSQL cannot call this from a trigger directly, so a cron job or
-- a wrapper script runs: DELETE FROM link_tokens WHERE created_at < now()-interval '15 minutes';
