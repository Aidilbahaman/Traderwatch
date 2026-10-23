-- TraderWatch: security fix S1 + S2 (audit 2026-10-23).
--
-- S1 (Critical): link_tokens had no Row-Level Security, so anon and
-- authenticated could SELECT every live bearer token. A token is a
-- credential: reading one and sending it to /start rebinds that member's
-- telegram_chat_id to the attacker, so the victim's paid signals are
-- delivered to the attacker instead. Only service_role (which bypasses
-- RLS) needs access, and the bot already uses the service key.
--
-- S2 (High): create_link_token() is SECURITY DEFINER and granted to
-- authenticated, but it never compared p_user_id with auth.uid(). Any
-- logged-in member could mint a token for someone else's user id.
--
-- Applied 2026-10-23 via the Supabase Management API. Idempotent.

ALTER TABLE public.link_tokens ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.link_tokens FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.create_link_token(p_user_id uuid)
RETURNS text
LANGUAGE plpgsql security definer set search_path = public, extensions as $$
DECLARE
  new_token text;
BEGIN
  -- A token may only be minted for the caller themself.
  IF auth.uid() IS NULL OR p_user_id <> auth.uid() THEN
    RAISE EXCEPTION 'not owner' USING ERRCODE = '42501';
  END IF;

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

-- If a future caller legitimately needs to mint a token for another user
-- (for example a bot-side flow), add a separate service-role-only function
-- rather than loosening the check above:
--
--   CREATE OR REPLACE FUNCTION public.create_link_token_for(p_user_id uuid)
--   RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path = public, extensions AS $$
--     SELECT public.create_link_token_internal(p_user_id);
--   $$;
--   REVOKE ALL ON FUNCTION public.create_link_token_for(uuid) FROM PUBLIC, anon, authenticated;
--   GRANT EXECUTE ON FUNCTION public.create_link_token_for(uuid) TO service_role;