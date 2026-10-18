-- TraderWatch Telegram signal linking (Option A)
-- Adds telegram_chat_id to profiles so Pro/Max members receive signals
-- in the Twreg_bot Telegram chat after linking from their dashboard.

-- 1) Link column (NULL until member links via bot /start)
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS telegram_chat_id bigint UNIQUE;

-- 2) Members may read their own link status; service_role writes.
-- No new RLS policy needed: existing "read own profile" select policy
-- already exposes their own row (including telegram_chat_id) after relink.
-- The bot stores chat_id using the service_role key, which bypasses RLS.

COMMENT ON COLUMN public.profiles.telegram_chat_id IS
  'Telegram chat id linked via bot /start; NULL until linked';
