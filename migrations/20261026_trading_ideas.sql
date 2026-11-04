-- TraderWatch trading ideas: members share their own view and analysis.
-- Run via: bash /home/ubuntu/web/run-supabase-migration.sh migrations/20261026_trading_ideas.sql
--
-- Design notes:
--  * Ideas belong to a profile (auth.uid()). Only the author may edit or
--    delete their own row; every signed-in member may read published ideas.
--  * Charts are stored as a TradingView symbol + interval, not as an uploaded
--    image. That keeps storage out of scope and lets the idea render live.
--  * One like per member per idea is enforced by a composite primary key.
--  * Nothing here is financial advice; the copy lives in the UI, not the DB.

-- ---------------------------------------------------------------- ideas table
CREATE TABLE IF NOT EXISTS public.ideas (
  id          bigserial PRIMARY KEY,
  user_id     uuid        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  pair        text        NOT NULL,
  side        text        NOT NULL DEFAULT 'NEUTRAL',
  timeframe   text        NOT NULL DEFAULT 'H1',
  title       text        NOT NULL,
  body        text        NOT NULL DEFAULT '',
  entry       numeric,
  sl          numeric,
  tp          numeric,
  symbol      text,                       -- TradingView symbol, e.g. OANDA:XAUUSD
  status      text        NOT NULL DEFAULT 'published',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  ALTER TABLE public.ideas DROP CONSTRAINT IF EXISTS ideas_side_check;
  ALTER TABLE public.ideas
    ADD CONSTRAINT ideas_side_check CHECK (side IN ('BUY','SELL','NEUTRAL'));
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE public.ideas DROP CONSTRAINT IF EXISTS ideas_status_check;
  ALTER TABLE public.ideas
    ADD CONSTRAINT ideas_status_check CHECK (status IN ('published','hidden'));
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE public.ideas DROP CONSTRAINT IF EXISTS ideas_title_len;
ALTER TABLE public.ideas
  ADD CONSTRAINT ideas_title_len CHECK (char_length(title) BETWEEN 3 AND 120);

ALTER TABLE public.ideas DROP CONSTRAINT IF EXISTS ideas_body_len;
ALTER TABLE public.ideas
  ADD CONSTRAINT ideas_body_len CHECK (char_length(body) <= 4000);

CREATE INDEX IF NOT EXISTS ideas_created_idx ON public.ideas (created_at DESC);
CREATE INDEX IF NOT EXISTS ideas_user_idx    ON public.ideas (user_id);
CREATE INDEX IF NOT EXISTS ideas_pair_idx    ON public.ideas (pair);

-- ---------------------------------------------------------------- likes table
CREATE TABLE IF NOT EXISTS public.idea_likes (
  idea_id    bigint      NOT NULL REFERENCES public.ideas(id) ON DELETE CASCADE,
  user_id    uuid        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (idea_id, user_id)
);

-- ---------------------------------------------------------------- comments
CREATE TABLE IF NOT EXISTS public.idea_comments (
  id         bigserial PRIMARY KEY,
  idea_id    bigint      NOT NULL REFERENCES public.ideas(id) ON DELETE CASCADE,
  user_id    uuid        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  body       text        NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.idea_comments DROP CONSTRAINT IF EXISTS idea_comments_body_len;
ALTER TABLE public.idea_comments
  ADD CONSTRAINT idea_comments_body_len CHECK (char_length(body) BETWEEN 1 AND 1000);

CREATE INDEX IF NOT EXISTS idea_comments_idea_idx ON public.idea_comments (idea_id, created_at);

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.ideas         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.idea_likes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.idea_comments ENABLE ROW LEVEL SECURITY;

-- ideas: any signed-in member reads published ideas, plus their own hidden ones
DROP POLICY IF EXISTS ideas_read ON public.ideas;
CREATE POLICY ideas_read ON public.ideas
  FOR SELECT USING (
    auth.uid() IS NOT NULL
    AND (status = 'published' OR user_id = auth.uid())
  );

DROP POLICY IF EXISTS ideas_insert ON public.ideas;
CREATE POLICY ideas_insert ON public.ideas
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND user_id = auth.uid());

DROP POLICY IF EXISTS ideas_update ON public.ideas;
CREATE POLICY ideas_update ON public.ideas
  FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS ideas_delete ON public.ideas;
CREATE POLICY ideas_delete ON public.ideas
  FOR DELETE USING (user_id = auth.uid());

-- likes: readable by members, writable only as yourself
DROP POLICY IF EXISTS idea_likes_read ON public.idea_likes;
CREATE POLICY idea_likes_read ON public.idea_likes
  FOR SELECT USING (auth.uid() IS NOT NULL);

DROP POLICY IF EXISTS idea_likes_write ON public.idea_likes;
CREATE POLICY idea_likes_write ON public.idea_likes
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND user_id = auth.uid());

DROP POLICY IF EXISTS idea_likes_delete ON public.idea_likes;
CREATE POLICY idea_likes_delete ON public.idea_likes
  FOR DELETE USING (user_id = auth.uid());

-- comments: readable by members, authored as yourself
DROP POLICY IF EXISTS idea_comments_read ON public.idea_comments;
CREATE POLICY idea_comments_read ON public.idea_comments
  FOR SELECT USING (auth.uid() IS NOT NULL);

DROP POLICY IF EXISTS idea_comments_insert ON public.idea_comments;
CREATE POLICY idea_comments_insert ON public.idea_comments
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND user_id = auth.uid());

DROP POLICY IF EXISTS idea_comments_delete ON public.idea_comments;
CREATE POLICY idea_comments_delete ON public.idea_comments
  FOR DELETE USING (user_id = auth.uid());

-- ---------------------------------------------------------------- updated_at
CREATE OR REPLACE FUNCTION public.touch_ideas_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS ideas_touch_updated_at ON public.ideas;
CREATE TRIGGER ideas_touch_updated_at
  BEFORE UPDATE ON public.ideas
  FOR EACH ROW EXECUTE FUNCTION public.touch_ideas_updated_at();

-- ---------------------------------------------------------------- feed RPC
-- One round trip returns the idea, its author, like count and whether the
-- caller already liked it. Avoids N+1 queries from the browser.
DROP FUNCTION IF EXISTS public.get_ideas(int, int);

CREATE FUNCTION public.get_ideas(p_limit int DEFAULT 30, p_offset int DEFAULT 0)
RETURNS TABLE (
  id          bigint,
  pair        text,
  side        text,
  timeframe   text,
  title       text,
  body        text,
  entry       numeric,
  sl          numeric,
  tp          numeric,
  symbol      text,
  created_at  timestamptz,
  author_id   uuid,
  author_name text,
  likes       bigint,
  liked       boolean,
  is_mine     boolean,
  comments    bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT
    i.id, i.pair, i.side, i.timeframe, i.title, i.body,
    i.entry, i.sl, i.tp, i.symbol, i.created_at,
    i.user_id,
    COALESCE(p.name, split_part(COALESCE(p.email,''), '@', 1), 'Member'),
    (SELECT count(*) FROM public.idea_likes l WHERE l.idea_id = i.id),
    EXISTS (SELECT 1 FROM public.idea_likes l WHERE l.idea_id = i.id AND l.user_id = auth.uid()),
    i.user_id = auth.uid(),
    (SELECT count(*) FROM public.idea_comments c WHERE c.idea_id = i.id)
  FROM public.ideas i
  LEFT JOIN public.profiles p ON p.id = i.user_id
  WHERE auth.uid() IS NOT NULL
    AND (i.status = 'published' OR i.user_id = auth.uid())
  ORDER BY i.created_at DESC
  LIMIT greatest(1, least(p_limit, 100))
  OFFSET greatest(0, p_offset);
$$;

GRANT EXECUTE ON FUNCTION public.get_ideas(int, int) TO authenticated;
