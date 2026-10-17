-- TraderWatch admin approval portal
-- Adds a payment-request queue and admin-only RPCs so plans can be
-- approved from a hosted page without exposing a service key.

-- 1) Admin flag on profiles
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'member';

DO $$
BEGIN
  ALTER TABLE public.profiles DROP CONSTRAINT profiles_role_check;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_role_check CHECK (role IN ('member','admin'));

-- 2) Payment request queue
CREATE TABLE IF NOT EXISTS public.payment_requests (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  email text NOT NULL,
  name text,
  plan text NOT NULL CHECK (plan IN ('pro','max')),
  method text NOT NULL DEFAULT 'qr',
  amount_usd text,
  amount_myr text,
  reference text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  note text,
  created_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  reviewed_by uuid
);

CREATE INDEX IF NOT EXISTS payment_requests_status_idx
  ON public.payment_requests (status, created_at DESC);

ALTER TABLE public.payment_requests ENABLE ROW LEVEL SECURITY;

-- No direct table access for anyone. All reads/writes go through RPCs below.
DROP POLICY IF EXISTS allow_all_payment_requests ON public.payment_requests;
DROP POLICY IF EXISTS allow_read_payment_requests ON public.payment_requests;

-- 3) Helpers
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE(
    (SELECT p.role = 'admin' FROM public.profiles p WHERE p.id = auth.uid()),
    false
  );
$$;
REVOKE ALL ON FUNCTION public.is_admin() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;

-- 4) Member: submit a payment reference
CREATE OR REPLACE FUNCTION public.submit_payment_request(
  p_plan text,
  p_reference text,
  p_method text DEFAULT 'qr',
  p_amount_usd text DEFAULT NULL,
  p_amount_myr text DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_uid uuid := auth.uid();
  v_email text;
  v_name text;
  v_id bigint;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'not authenticated' USING ERRCODE = '42501';
  END IF;
  IF p_plan NOT IN ('pro','max') THEN
    RAISE EXCEPTION 'invalid plan' USING ERRCODE = '22023';
  END IF;
  IF p_reference IS NULL OR length(btrim(p_reference)) < 4 THEN
    RAISE EXCEPTION 'reference too short' USING ERRCODE = '22023';
  END IF;

  SELECT u.email, COALESCE(pr.name, split_part(u.email, '@', 1))
    INTO v_email, v_name
  FROM auth.users u
  LEFT JOIN public.profiles pr ON pr.id = u.id
  WHERE u.id = v_uid;

  -- Reuse an existing pending request for the same plan instead of duplicating.
  SELECT id INTO v_id
  FROM public.payment_requests
  WHERE user_id = v_uid AND plan = p_plan AND status = 'pending'
  ORDER BY created_at DESC LIMIT 1;

  IF v_id IS NOT NULL THEN
    UPDATE public.payment_requests
      SET reference = btrim(p_reference),
          method = COALESCE(p_method, method),
          amount_usd = COALESCE(p_amount_usd, amount_usd),
          amount_myr = COALESCE(p_amount_myr, amount_myr),
          created_at = now()
      WHERE id = v_id;
    RETURN v_id;
  END IF;

  INSERT INTO public.payment_requests (user_id, email, name, plan, method, amount_usd, amount_myr, reference)
  VALUES (v_uid, v_email, v_name, p_plan, COALESCE(p_method,'qr'), p_amount_usd, p_amount_myr, btrim(p_reference))
  RETURNING id INTO v_id;

  RETURN v_id;
END $$;
REVOKE ALL ON FUNCTION public.submit_payment_request(text,text,text,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.submit_payment_request(text,text,text,text,text) TO authenticated;

-- 5) Member: read own requests (used to restore pending state across devices)
CREATE OR REPLACE FUNCTION public.my_payment_requests()
RETURNS TABLE (id bigint, plan text, status text, reference text, created_at timestamptz, reviewed_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT r.id, r.plan, r.status, r.reference, r.created_at, r.reviewed_at
  FROM public.payment_requests r
  WHERE r.user_id = auth.uid()
  ORDER BY r.created_at DESC
  LIMIT 20;
$$;
REVOKE ALL ON FUNCTION public.my_payment_requests() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.my_payment_requests() TO authenticated;

-- 6) Admin: queue listing
CREATE OR REPLACE FUNCTION public.admin_list_payment_requests(p_status text DEFAULT 'pending')
RETURNS TABLE (
  id bigint, user_id uuid, email text, name text, plan text, method text,
  amount_usd text, amount_myr text, reference text, status text,
  created_at timestamptz, reviewed_at timestamptz, current_plan text
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;

  RETURN QUERY
  SELECT r.id, r.user_id, r.email, r.name, r.plan, r.method,
         r.amount_usd, r.amount_myr, r.reference, r.status,
         r.created_at, r.reviewed_at, p.plan
  FROM public.payment_requests r
  LEFT JOIN public.profiles p ON p.id = r.user_id
  WHERE p_status IS NULL OR p_status = 'all' OR r.status = p_status
  ORDER BY r.created_at DESC
  LIMIT 200;
END $$;
REVOKE ALL ON FUNCTION public.admin_list_payment_requests(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.admin_list_payment_requests(text) TO authenticated;

-- 7) Admin: approve or reject
CREATE OR REPLACE FUNCTION public.admin_review_payment(p_id bigint, p_decision text, p_note text DEFAULT NULL)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_plan text;
  v_uid uuid;
  v_status text;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;
  IF p_decision NOT IN ('approve','reject') THEN
    RAISE EXCEPTION 'invalid decision' USING ERRCODE = '22023';
  END IF;

  SELECT plan, user_id, status INTO v_plan, v_uid, v_status
  FROM public.payment_requests WHERE id = p_id FOR UPDATE;

  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'request not found' USING ERRCODE = 'P0002';
  END IF;

  IF p_decision = 'approve' THEN
    UPDATE public.payment_requests
      SET status = 'approved', reviewed_at = now(), reviewed_by = auth.uid(), note = p_note
      WHERE id = p_id;
    -- Never downgrade an existing Max member to Pro.
    UPDATE public.profiles
      SET plan = CASE WHEN plan = 'max' AND v_plan = 'pro' THEN 'max' ELSE v_plan END
      WHERE id = v_uid;
    RETURN 'approved';
  END IF;

  UPDATE public.payment_requests
    SET status = 'rejected', reviewed_at = now(), reviewed_by = auth.uid(), note = p_note
    WHERE id = p_id;
  RETURN 'rejected';
END $$;
REVOKE ALL ON FUNCTION public.admin_review_payment(bigint,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.admin_review_payment(bigint,text,text) TO authenticated;

-- 8) Admin: manual plan override by email
CREATE OR REPLACE FUNCTION public.admin_set_plan(p_email text, p_plan text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;
  IF p_plan NOT IN ('free','pro','max') THEN
    RAISE EXCEPTION 'invalid plan' USING ERRCODE = '22023';
  END IF;

  UPDATE public.profiles SET plan = p_plan WHERE lower(email) = lower(btrim(p_email));
  IF NOT FOUND THEN
    RAISE EXCEPTION 'member not found' USING ERRCODE = 'P0002';
  END IF;
  RETURN p_plan;
END $$;
REVOKE ALL ON FUNCTION public.admin_set_plan(text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.admin_set_plan(text,text) TO authenticated;

-- 9) Admin: member overview
CREATE OR REPLACE FUNCTION public.admin_list_members(p_search text DEFAULT NULL)
RETURNS TABLE (id uuid, email text, name text, plan text, role text, created_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;

  RETURN QUERY
  SELECT p.id, p.email, p.name, p.plan, p.role, p.created_at
  FROM public.profiles p
  WHERE p_search IS NULL
     OR p_search = ''
     OR p.email ILIKE '%' || p_search || '%'
     OR COALESCE(p.name,'') ILIKE '%' || p_search || '%'
  ORDER BY p.created_at DESC
  LIMIT 200;
END $$;
REVOKE ALL ON FUNCTION public.admin_list_members(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.admin_list_members(text) TO authenticated;

-- 10) Bootstrap the first admin (run manually, once, with your own email):
--   UPDATE public.profiles SET role = 'admin' WHERE email = 'you@example.com';
