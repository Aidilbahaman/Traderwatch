#!/usr/bin/env python3
"""TraderWatch chat API — server-side chat with mandatory content filtering.

Why this exists: the brief requires that links, phone numbers and emails be
filtered ON THE SERVER. A client-side filter is decoration — anyone can POST
straight to the API and bypass it. So every write goes through `sanitise()`
here, and the filtered text is what gets stored.

Endpoints (all JSON, all under /api/):
  GET  /api/chat/messages?limit=50      -> newest-first message list + online count
  POST /api/chat/messages               -> {"text": "..."} -> stored message
  POST /api/chat/alert                  -> {"level": "off|team|all"}
  POST /api/chat/presence               -> heartbeat; returns {ok, online}

Presence: the member app sends a heartbeat every 60s while visible. A member
counts as "online" if their last heartbeat is within PRESENCE_TTL seconds.
Only the COUNT is exposed — never who is online (privacy).

Auth: a Supabase access token is required in `Authorization: Bearer <token>`.
The token is verified against Supabase /auth/v1/user. Without a valid token the
request is rejected, so only signed-in members can read or post.

Storage: Supabase table `chat_messages`. Run this SQL once in the SQL editor:

  create table if not exists public.chat_messages (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    username    text not null,
    body        text not null,
    created_at  timestamptz not null default now()
  );
  create index if not exists chat_messages_created_idx
    on public.chat_messages (created_at desc);
  alter table public.chat_messages enable row level security;
  -- no public policies: the service role (this server) is the only writer/reader

The table is intentionally NOT readable with the anon key. All reads go through
this server so the filter and the auth check can never be bypassed.
"""
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PORT = int(os.environ.get("CHAT_PORT", "8101"))
MYT = timezone(timedelta(hours=8))
MAX_LEN = 500
RATE_LIMIT_SECONDS = 5          # one message per 5s per user
DAILY_RESET_HOUR_MYT = 0        # community chat clears at 12am Malaysia

_last_post = {}                 # user_id -> unix ts of last accepted message

# ---- presence (online count) ----
PRESENCE_TTL = float(os.environ.get("PRESENCE_TTL", "150"))  # 60s heartbeat + margin
_presence = {}                  # user_id -> unix ts of last heartbeat
_presence_lock = threading.Lock()


def presence_beat(uid):
    now = time.time()
    with _presence_lock:
        _presence[uid] = now
        return sum(1 for ts in _presence.values() if now - ts <= PRESENCE_TTL)


def presence_count():
    now = time.time()
    with _presence_lock:
        stale = [u for u, ts in _presence.items() if now - ts > PRESENCE_TTL]
        for u in stale:
            _presence.pop(u, None)
        return len(_presence)


# ---------------------------------------------------------------- secrets
def load_env():
    sec = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


SEC = load_env()
SB_URL = SEC["SUPABASE_URL"].rstrip("/")
SB_KEY = SEC["SUPABASE_SERVICE_KEY"]


# ---------------------------------------------------------------- filtering
# The brief: "Pautan, nombor telefon, emel dan butiran hubungan disekat."
URL_RE = re.compile(r"(https?://|www\.)\S+", re.I)
DOMAIN_RE = re.compile(r"\b[a-z0-9][a-z0-9-]{1,60}\.(com|net|org|io|co|my|sg|id|xyz|me|info|biz|app|dev|link|site|online|store|pro|cc|ru|to|gg)\b", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# phone: 8+ digits allowing spaces/dashes, plus classic Malaysian patterns
PHONE_RE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s-]?)?(?:\d[\s-]?){8,15}\d")
MY_PHONE_RE = re.compile(r"\b0\d{1,2}[\s-]?\d{3,4}[\s-]?\d{4}\b")
# social handles / contact asks
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_.]{3,}", re.I)
CONTACT_RE = re.compile(
    r"\b(whatsapp|wasap|ws|telegram|tg|wechat|line|signal|dm|pm me|inbox|"
    r"contact me|hubungi saya|call me|text me|add me|follow me|join my|"
    r"group saya|grup saya|channel saya)\b", re.I)


def sanitise(text):
    """Return (clean_text, actions). Blocked content is REPLACED, not silently
    dropped, so the sender can see their message was filtered."""
    actions = []
    t = text

    t, n = URL_RE.subn("[pautan disekat]", t)
    if n:
        actions.append("link")
    t, n = DOMAIN_RE.subn("[pautan disekat]", t)
    if n:
        actions.append("link")
    t, n = EMAIL_RE.subn("[emel disekat]", t)
    if n:
        actions.append("email")
    t, n = MY_PHONE_RE.subn("[nombor disekat]", t)
    if n:
        actions.append("phone")
    t, n = PHONE_RE.subn("[nombor disekat]", t)
    if n:
        actions.append("phone")
    t, n = HANDLE_RE.subn("[handle disekat]", t)
    if n:
        actions.append("handle")
    t, n = CONTACT_RE.subn("[hubungan disekat]", t)
    if n:
        actions.append("contact")

    t = re.sub(r"\s{2,}", " ", t).strip()
    return t, sorted(set(actions))


def has_blocked(text):
    """True if the raw text carried anything that must not reach members."""
    return bool(URL_RE.search(text) or DOMAIN_RE.search(text)
                or EMAIL_RE.search(text) or MY_PHONE_RE.search(text)
                or PHONE_RE.search(text) or HANDLE_RE.search(text)
                or CONTACT_RE.search(text))


# ---------------------------------------------------------------- supabase
def sb(method, path, body=None, token=None, params=None):
    url = SB_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SB_KEY)
    req.add_header("Authorization", "Bearer " + (token or SB_KEY))
    req.add_header("Content-Type", "application/json")
    if method == "POST":
        req.add_header("Prefer", "return=representation")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise RuntimeError(f"supabase {e.code}: {detail}") from None


def verify_user(token):
    """Return the authed user dict, or None."""
    if not token:
        return None
    try:
        req = urllib.request.Request(SB_URL + "/auth/v1/user")
        req.add_header("apikey", SB_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def display_name(user):
    md = user.get("user_metadata") or {}
    return (md.get("username") or md.get("full_name") or md.get("name")
            or (user.get("email") or "").split("@")[0] or "member")


def day_start_utc():
    """Start of the current MYT day, in UTC — chat resets at 12am Malaysia."""
    now_myt = datetime.now(MYT)
    start_myt = now_myt.replace(hour=DAILY_RESET_HOUR_MYT, minute=0, second=0, microsecond=0)
    return start_myt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    server_version = "TraderWatchChat/1.0"

    def log_message(self, fmt, *args):
        pass                                  # keep the journal quiet

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token(self):
        h = self.headers.get("Authorization") or ""
        return h[7:].strip() if h.lower().startswith("bearer ") else None

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/chat/health":
            return self._send(200, {"ok": True, "time": datetime.now(timezone.utc).isoformat()})
        if path != "/api/chat/messages":
            return self._send(404, {"error": "not found"})

        user = verify_user(self._token())
        if not user:
            return self._send(401, {"error": "sign in required"})

        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            limit = min(100, max(1, int((q.get("limit") or ["50"])[0])))
        except ValueError:
            limit = 50

        try:
            rows = sb("GET", "/rest/v1/chat_messages",
                      params={"select": "id,username,body,created_at",
                              "created_at": "gte." + day_start_utc(),
                              "order": "created_at.desc",
                              "limit": limit})
        except RuntimeError as e:
            return self._send(502, {"error": str(e)})
        uid = user.get("id") or ""
        if uid:
            presence_beat(uid)  # reading chat = active too
        return self._send(200, {"messages": rows or [], "reset_at_utc": day_start_utc(),
                                "online": presence_count()})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        user = verify_user(self._token())
        if not user:
            return self._send(401, {"error": "sign in required"})

        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            return self._send(400, {"error": "bad json"})

        # ---- presence heartbeat (online count)
        if path == "/api/chat/presence":
            uid = user.get("id") or ""
            if not uid:
                return self._send(401, {"error": "sign in required"})
            return self._send(200, {"ok": True, "online": presence_beat(uid)})

        # ---- alert preference: stored on the user's metadata
        if path == "/api/chat/alert":
            level = payload.get("level")
            if level not in ("off", "team", "all"):
                return self._send(400, {"error": "level must be off|team|all"})
            try:
                sb("PUT", "/auth/v1/user",
                   body={"data": {"alert_level": level}}, token=self._token())
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            return self._send(200, {"ok": True, "level": level})

        if path != "/api/chat/messages":
            return self._send(404, {"error": "not found"})

        raw = str(payload.get("text") or "").strip()
        if not raw:
            return self._send(400, {"error": "empty message"})
        if len(raw) > MAX_LEN:
            return self._send(400, {"error": f"max {MAX_LEN} characters"})

        uid = user.get("id") or ""
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_post.get(uid, 0) < RATE_LIMIT_SECONDS:
            return self._send(429, {"error": "slow down"})

        clean, actions = sanitise(raw)
        if not clean:
            return self._send(400, {"error": "message filtered out"})

        _last_post[uid] = now
        try:
            rows = sb("POST", "/rest/v1/chat_messages",
                      body={"user_id": uid, "username": display_name(user), "body": clean})
        except RuntimeError as e:
            return self._send(502, {"error": str(e)})
        return self._send(201, {"message": (rows or [{}])[0], "filtered": actions})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"chat api listening on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
