-- TraderWatch plan-change notification outbox (Option B).
-- When a plan changes to pro/max, a row is queued here; a small Python
-- worker picks it up and sends the Telegram welcome message to the member
-- (if their Telegram is linked). The RPC that changes the plan never waits
-- for Telegram, so approval cannot break if the bot is offline.

-- 1) Outbox table
CREATE TABLE IF NOT EXISTS public.plan_notifications (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  old_plan text NOT NULL,
  new_plan text NOT NULL CHECK (new_plan IN ('free','pro','max')),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','sent','skipped','failed')),
  attempts integer NOT NULL DEFAULT 0,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);
ALTER TABLE public.plan_notifications ENABLE ROW LEVEL SECURITY;
-- No select/insert/update policies on purpose: only the admin RPC
-- (security definer) and the service-role worker touch this table.

-- 2) Helper: queue a notification only when a plan actually changes
--    AND the new plan is pro or max. Free/downgrade changes are ignored
--    silently (nothing to announce).
CREATE OR REPLACE FUNCTION public.queue_plan_notification(
  p_user uuid, p_old_plan text, p_new_plan text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF p_new_plan IN ('pro','max') AND p_old_plan IS DISTINCT FROM p_new_plan THEN
    INSERT INTO public.plan_notifications (user_id, old_plan, new_plan)
    VALUES (p_user, COALESCE(p_old_plan,'free'), p_new_plan);
  END IF;
END $$;
REVOKE ALL ON FUNCTION public.queue_plan_notification(uuid,text,text) FROM PUBLIC, anon;

-- 3) Hook into the two admin plan-change paths.
--    admin_review_payment: read the old plan before updating it.
CREATE OR REPLACE FUNCTION public.admin_review_payment(p_id bigint, p_decision text, p_note text DEFAULT NULL)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_plan text;
  v_uid uuid;
  v_status text;
  v_old_plan text;
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
    SELECT plan INTO v_old_plan FROM public.profiles WHERE id = v_uid;
    UPDATE public.payment_requests
      SET status = 'approved', reviewed_at = now(), reviewed_by = auth.uid(), note = p_note
      WHERE id = p_id;
    -- Never downgrade an existing Max member to Pro.
    UPDATE public.profiles
      SET plan = CASE WHEN plan = 'max' AND v_plan = 'pro' THEN 'max' ELSE v_plan END
      WHERE id = v_uid;
    PERFORM public.queue_plan_notification(
      v_uid, v_old_plan,
      CASE WHEN v_old_plan = 'max' AND v_plan = 'pro' THEN 'max' ELSE v_plan END);
    RETURN 'approved';
  END IF;

  UPDATE public.payment_requests
    SET status = 'rejected', reviewed_at = now(), reviewed_by = auth.uid(), note = p_note
    WHERE id = p_id;
  RETURN 'rejected';
END $$;
REVOKE ALL ON FUNCTION public.admin_review_payment(bigint,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.admin_review_payment(bigint,text,text) TO authenticated;

--    admin_set_plan: read the old plan before overwriting it.
CREATE OR REPLACE FUNCTION public.admin_set_plan(p_email text, p_plan text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_uid uuid;
  v_old_plan text;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;
  IF p_plan NOT IN ('free','pro','max') THEN
    RAISE EXCEPTION 'invalid plan' USING ERRCODE = '22023';
  END IF;

  SELECT id, plan INTO v_uid, v_old_plan
  FROM public.profiles
  WHERE lower(email) = lower(btrim(p_email)) FOR UPDATE;

  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'member not found' USING ERRCODE = 'P0002';
  END IF;

  UPDATE public.profiles SET plan = p_plan WHERE id = v_uid;
  PERFORM public.queue_plan_notification(v_uid, v_old_plan, p_plan);
  RETURN p_plan;
END $$;
REVOKE ALL ON FUNCTION public.admin_set_plan(text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.admin_set_plan(text,text) TO authenticated;
