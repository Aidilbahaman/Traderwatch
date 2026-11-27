#!/usr/bin/env python3
"""TraderWatch chat API — server-side chat with mandatory content filtering.

Why this exists: the brief requires that links, phone numbers and emails be
filtered ON THE SERVER. A client-side filter is decoration — anyone can POST
straight to the API and bypass it. So every write goes through `sanitise()`
here, and the filtered text is what gets stored.

Endpoints (all JSON, all under /api/):
  GET  /api/chat/messages?limit=50      -> newest-first message list + online count
  POST /api/chat/messages               -> {"text": "..."} -> stored message
  POST /api/chat/edit                   -> {"id": 12, "text": "..."} -> own message edited
  POST /api/chat/delete                 -> {"id": 12} -> own message soft-deleted
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
import base64
import io
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

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PORT = int(os.environ.get("CHAT_PORT", "8101"))
MYT = timezone(timedelta(hours=8))
MAX_LEN = 500
RATE_LIMIT_SECONDS = 5          # one message per 5s per user
DAILY_RESET_HOUR_MYT = 0        # community chat clears at 12am Malaysia

_last_post = {}                 # user_id -> unix ts of last accepted message
_last_dm = {}                   # user_id -> unix ts of last DM
_last_wave = {}                 # user_id -> unix ts of last wave
DM_RATE_LIMIT = 1.2
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
DEV_UIDS = {x.strip() for x in os.environ.get("DEV_UIDS", "c59521e0-f0e7-48cb-856a-8990a643e3ae").split(",") if x.strip()}
DEV_NAME = "Aidil (Dev)"


def is_dev_uid(uid):
    return bool(uid) and str(uid) in DEV_UIDS


PUSH_ENV = pathlib.Path("/home/ubuntu/.secrets/push.env")

# ---- rooms / signal cards / reactions (needs migrations/20261124_chat_rooms_cards_reactions.sql) ----
ROOMS = ("XAUUSD", "XAGUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD")
EMOJIS = ("🔥", "🎯", "👏", "👍")
CARD_TFS = ("M1", "M5", "M15", "H1", "H4")
SEASON = int(os.environ.get("LEAGUE_SEASON", "1"))
REACT_COOLDOWN = 0.4            # seconds between reaction toggles per user
_last_react = {}
_cache_lock = threading.Lock()
_cache = {}
_feat = {"ext": (0.0, False), "rx": (0.0, False), "ed": (0.0, False)}
_last_edit = {}                 # user_id -> unix ts of last accepted edit
EDIT_RATE_LIMIT = 1.5           # seconds between edits per user

# ---- profile avatars (auto-compressed <= 500 KB on disk) ----
AVATAR_DIR = pathlib.Path(__file__).resolve().parent.parent / "member" / "avatars"
AVATAR_MAX_BYTES = 500 * 1024   # strict 500 KB cap on disk
AVATAR_MAX_RAW = 2 * 1024 * 1024  # 2 MB max incoming payload
AVATAR_MAX_DIM = 768
_last_avatar = {}
AVATAR_RATE_LIMIT = 3.0


def avatar_url_for(uid):
    """Return cache-busted local avatar URL if this user has uploaded a photo."""
    if not uid or not UUID_RE.match(str(uid)):
        return ""
    p = AVATAR_DIR / f"{uid}.jpg"
    try:
        return f"/member/avatars/{uid}.jpg?v={int(p.stat().st_mtime)}"
    except OSError:
        return ""


def save_avatar_image(uid, data_url):
    """Decode base64 image, center-crop square, compress to <= 500 KB JPEG, save atomically."""
    if not UUID_RE.match(uid or ""):
        raise ValueError("invalid user")
    if Image is None:
        raise RuntimeError("image processor unavailable")
    s = str(data_url or "").strip()
    if s.startswith("data:"):
        comma = s.find(",")
        if comma < 0:
            raise ValueError("bad data url")
        s = s[comma + 1:]
    try:
        raw = base64.b64decode(s, validate=True)
    except Exception:
        raise ValueError("invalid base64 image")
    if not raw or len(raw) > AVATAR_MAX_RAW:
        raise ValueError("image too large")
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        if ImageOps is not None:
            im = ImageOps.exif_transpose(im)
    except Exception:
        raise ValueError("unsupported image format")
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        bg = Image.new("RGB", im.size, (17, 22, 18))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    w, h = im.size
    side = min(w, h)
    if side <= 0:
        raise ValueError("empty image")
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))

    out = None
    for dim in (min(side, AVATAR_MAX_DIM), min(side, 512), min(side, 384), min(side, 256)):
        cur = im.resize((dim, dim), Image.Resampling.LANCZOS) if dim < side else im
        for q in (88, 80, 72, 62, 52, 42, 32):
            buf = io.BytesIO()
            cur.save(buf, format="JPEG", quality=q, optimize=True, progressive=True)
            data = buf.getvalue()
            if len(data) <= AVATAR_MAX_BYTES:
                out = data
                break
        if out is not None:
            break
    if out is None:
        raise ValueError("could not compress under 500KB")

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    dst = AVATAR_DIR / f"{uid}.jpg"
    tmp = AVATAR_DIR / f".{uid}.{os.getpid()}.tmp"
    tmp.write_bytes(out)
    os.replace(tmp, dst)
    return f"/member/avatars/{uid}.jpg?v={int(time.time())}", len(out)

# ---- presence (online count) ----
PRESENCE_TTL = float(os.environ.get("PRESENCE_TTL", "150"))  # 60s heartbeat + margin
_presence = {}                  # user_id -> unix ts of last heartbeat
_presence_lock = threading.Lock()


# ---- last seen (orbit: nama kekal sehingga 12 malam, hilang esok kalau tak online) ----
# _presence di atas hilang bila server restart. Orbit pula perlu tahu siapa yang
# pernah online HARI INI, jadi cap masa terakhir disimpan ke state/presence.json.
SEEN_FILE = pathlib.Path(__file__).resolve().parent.parent / "state" / "presence.json"
SEEN_KEEP = 30 * 86400          # simpan 30 hari — "last online" rakan (orbit guna "hari ini" sahaja)
_seen = {}                      # user_id -> unix ts terakhir dikesan online
_seen_dirty = False
_seen_last_flush = 0.0
_seen_lock = threading.Lock()


def _load_seen():
    try:
        raw = json.loads(SEEN_FILE.read_text())
    except (OSError, ValueError):
        return
    now = time.time()
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, (int, float)) and now - v < SEEN_KEEP:
                _seen[k] = float(v)


def _flush_seen(force=False):
    global _seen_dirty, _seen_last_flush
    now = time.time()
    with _seen_lock:
        if not _seen_dirty:
            return
        if not force and now - _seen_last_flush < 60:
            return
        _seen_dirty = False
        _seen_last_flush = now
        data = {k: v for k, v in _seen.items() if now - v < SEEN_KEEP}
    try:
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, SEEN_FILE)
    except OSError:
        pass                            # disk penuh / read-only: jangan rosakkan chat


def mark_seen(uid):
    """Cap masa 'online' terkini. Dipanggil setiap heartbeat & setiap API call sah."""
    global _seen_dirty
    if not uid:
        return
    with _seen_lock:
        _seen[uid] = time.time()
        _seen_dirty = True
    _flush_seen()


def presence_beat(uid):
    now = time.time()
    with _presence_lock:
        _presence[uid] = now
        n = sum(1 for ts in _presence.values() if now - ts <= PRESENCE_TTL)
    mark_seen(uid)
    return n


def presence_count():
    now = time.time()
    with _presence_lock:
        stale = [u for u, ts in _presence.items() if now - ts > PRESENCE_TTL]
        for u in stale:
            _presence.pop(u, None)
        return len(_presence)


def presence_online_set():
    now = time.time()
    with _presence_lock:
        stale = [u for u, ts in _presence.items() if now - ts > PRESENCE_TTL]
        for u in stale:
            _presence.pop(u, None)
        return set(_presence.keys())


def last_seen_iso(uid):
    """ISO8601 (UTC) cap masa terakhir ahli dikesan online, atau '' jika tak pernah."""
    ts = _seen.get(uid)
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# ---- typing indicator (in-memory sahaja; luput sendiri dalam beberapa saat) ----
TYPING_TTL = 5.0
_typing = {}                    # (sender_id, recipient_id) -> unix ts typing terakhir
_typing_lock = threading.Lock()


def typing_set(sender, recipient, on):
    key = (sender, recipient)
    with _typing_lock:
        if on:
            _typing[key] = time.time()
        else:
            _typing.pop(key, None)
        if len(_typing) > 2000:         # elak membesar tanpa had
            cutoff = time.time() - 60
            for k in [k for k, v in _typing.items() if v < cutoff]:
                _typing.pop(k, None)


def is_typing(sender, recipient):
    with _typing_lock:
        ts = _typing.get((sender, recipient))
    return bool(ts and time.time() - ts <= TYPING_TTL)


_load_seen()


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


def sanitise(text, admin=False):
    """Return (clean_text, actions). Word filter DISABLED for everyone per owner
    request 2026-11-26 — messages pass through unfiltered. Keep the signature
    and actions list for API compatibility (actions always empty now). The
    admin flag is accepted but no longer changes behaviour."""
    del admin
    return (re.sub(r"\s{2,}", " ", text or "").strip(), [])


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


AUTH_TTL = 120          # token -> user cache (seconds). Tokens are JWTs with
_auth_cache = {}        # ~1h lifetime; caching 2 min is safe and removes a
_auth_lock = threading.Lock()  # Supabase round-trip from every poll (DM polls
                               # every 4s, presence every 30s, friends refresh).

def verify_user(token):
    """Return the authed user dict, or None. Cached per token for AUTH_TTL:
    the DM sheet polls every 4s, so without this every poll paid one Supabase
    /auth round-trip (~150-350ms) - the "Loading private chat..." slowness."""
    if not token:
        return None
    now = time.time()
    with _auth_lock:
        hit = _auth_cache.get(token)
        if hit:
            ts, val = hit
            if now - ts <= AUTH_TTL:
                return val
            del _auth_cache[token]
    try:
        req = urllib.request.Request(SB_URL + "/auth/v1/user")
        req.add_header("apikey", SB_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as r:
            user = json.loads(r.read().decode())
    except Exception:
        return None
    with _auth_lock:
        _auth_cache[token] = (now, user)
        if len(_auth_cache) > 1000:  # had lembut, buang tertua
            for k, _ in sorted(_auth_cache.items(), key=lambda kv: kv[1][0])[:200]:
                _auth_cache.pop(k, None)
    return user


# ---------------------------------------------------------------- privacy
# Nama penuh tidak pernah keluar dari server. Setiap nama paparan melalui
# public_name(), yang mengambil SATU perkataan sahaja:
#   "Farrah Wahida Zulkifli" -> "Farrah"
#   "M SHAMRAIZ"             -> "Shamraiz"   (token 1 huruf dilangkau)
#   "Mr T “SharulR”"         -> "SharulR"
#   "MUHAMMAD ASYRAF BIN ..."-> "Muhammad"
# Ini melindungi identiti ahli baru yang tersenarai dalam direktori awam,
# dan konsisten dengan cara chat komuniti memaparkan nama.
HONORIFICS = {"mr", "mrs", "ms", "dr", "haji", "hj", "bin", "binti", "a/l", "a/p"}


def public_name(raw):
    """One-token display name. Never returns a full legal name."""
    txt = str(raw or "").strip()
    if not txt:
        return "Trader"
    # buang emoji/simbol pelik tetapi kekalkan huruf, digit, . ' - dan ruang
    txt = re.sub(r"[^\w\s.'-]", " ", txt)
    tokens = [t for t in txt.split() if t]
    # langkau gelaran & partikel — tetapi jangan buang token terakhir
    # (nama pengguna "MS" ialah nama, bukan gelaran "Ms").
    while len(tokens) > 1 and tokens[0].strip(".").lower() in HONORIFICS:
        tokens.pop(0)
    # token pertama yang ada huruf sebenar (bukan "M", bukan "A.")
    pick = ""
    for t in tokens:
        core = t.strip(".'-")
        if len(re.sub(r"[^A-Za-z]", "", core)) >= 2:
            pick = core
            break
    if not pick and tokens:
        pick = tokens[0].strip(".'-")
    if not pick:
        return "Trader"
    # Title case supaya "SHAMRAIZ" jadi "Shamraiz"; kekalkan akronim pendek berhuruf besar
    if pick.isupper() and len(pick) <= 2:
        return pick
    return pick[:1].upper() + pick[1:].lower() if pick.isupper() else pick[:1].upper() + pick[1:]


def _suffix(raw, taken):
    """Huruf pembeza daripada token kedua nama penuh: "Aidil Bahaman" -> "B."."""
    txt = re.sub(r"[^\w\s.'-]", " ", str(raw or "")).split()
    txt = [t for t in txt if t.strip(".'-")]
    if len(txt) > 1:
        for t in txt[1:]:
            core = re.sub(r"[^A-Za-z]", "", t)
            if core:
                letter = core[0].upper() + "."
                if letter not in taken:
                    return letter
    return ""


def disambiguate(items):
    """Beri akhiran hanya kepada nama yang berlanggar.
    items: [{"id":.., "raw": "<nama mentah>"}] -> {id: "Aidil B."}

    Peraturan: nama yang TIADA token kedua (cth. "Aidil") mengekalkan nama
    bersih, kerana ia tidak boleh dibezakan dengan cara lain. Nama yang ADA
    token kedua ("Aidil Bahaman") menerima akhiran huruf pertama token itu.
    Nama unik tidak disentuh langsung."""
    base = {it["id"]: public_name(it["raw"]) for it in items}
    groups = {}
    for it in items:
        groups.setdefault(base[it["id"]], []).append(it)

    out = {}
    for nm, members in groups.items():
        if len(members) == 1:
            out[members[0]["id"]] = nm
            continue

        taken = set()
        plain = [it for it in members if not _suffix_parts(it["raw"])]
        suffixed = [it for it in members if _suffix_parts(it["raw"])]

        # yang tak boleh diberi akhiran dapat nama bersih dahulu
        for idx, it in enumerate(plain):
            if idx == 0 and nm not in taken:
                taken.add(nm)
                out[it["id"]] = nm
            else:
                cand = nm + " " + str(it["id"])[:2].upper()
                while cand in taken:
                    cand += "2"
                taken.add(cand)
                out[it["id"]] = cand

        # selebihnya terima akhiran
        for it in suffixed:
            final = None
            for p in _suffix_parts(it["raw"]):
                cand = nm + " " + p
                if cand not in taken and cand not in out.values():
                    final = cand
                    break
            if not final:
                cand = nm + " " + str(it["id"])[:2].upper()
                while cand in taken or cand in out.values():
                    cand += "2"
                final = cand
            taken.add(final)
            out[it["id"]] = final
    return out


def _suffix_parts(raw):
    """Calon akhiran daripada token kedua dan seterusnya: ["B.", "BAH"]."""
    txt = [t for t in re.sub(r"[^\w\s.'-]", " ", str(raw or "")).split() if t.strip(".'-")]
    parts = []
    for t in txt[1:]:
        core = re.sub(r"[^A-Za-z]", "", t)
        if core:
            parts.append(core[0].upper() + ".")
    if len(txt) > 1:
        # fallback: dua huruf penuh token terakhir, kalau perlu pembeza lanjut
        core = re.sub(r"[^A-Za-z]", "", txt[-1])
        if len(core) >= 2:
            parts.append(core[:2].upper())
    return parts


def display_name(user):
    md = user.get("user_metadata") or {}
    raw = (md.get("username") or md.get("full_name") or md.get("name")
           or (user.get("email") or "").split("@")[0] or "member")
    return public_name(raw)


def display_name_full(user):
    """Nama paparan MENTAH (belum dibezakan) — untuk disambiguate()."""
    md = user.get("user_metadata") or {}
    return (md.get("username") or md.get("full_name") or md.get("name")
            or (user.get("email") or "").split("@")[0] or "member")


def day_start_utc():
    """Start of the current MYT day, in UTC — chat resets at 12am Malaysia."""
    now_myt = datetime.now(MYT)
    start_myt = now_myt.replace(hour=DAILY_RESET_HOUR_MYT, minute=0, second=0, microsecond=0)
    return start_myt.astimezone(timezone.utc).isoformat()


def purge_dm_expired():
    """Delete DM rows older than 24 hours. Private chat is temporary."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        sb("DELETE", "/rest/v1/dm_messages", params={"created_at": f"lt.{cutoff}"})
    except RuntimeError:
        pass


def _dm_purge_loop():
    """Every 30 minutes, drop DMs older than 24h."""
    while True:
        try:
            purge_dm_expired()
        except Exception:
            pass
        time.sleep(1800)


# ---------------------------------------------------------------- handler
def _cached(key, ttl, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] <= ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def _probe(name, path, params):
    """True if the optional schema is present. Cached 30s so an un-migrated
    database costs one cheap failing query per 30s, not one per request."""
    now = time.time()
    with _cache_lock:
        ts, ok = _feat[name]
        if now - ts < 30:
            return ok
    try:
        sb("GET", path, params=params)
        ok = True
    except RuntimeError:
        ok = False
    with _cache_lock:
        _feat[name] = (now, ok)
    return ok


def ext_ok():
    return _probe("ext", "/rest/v1/chat_messages", {"select": "room,kind,payload", "limit": 1})


def rx_ok():
    return _probe("rx", "/rest/v1/chat_reactions", {"select": "message_id", "limit": 1})


def ed_ok():
    """True once the edited_at column exists (migrations/20261126_chat_edit_delete.sql)."""
    return _probe("ed", "/rest/v1/chat_messages", {"select": "edited_at", "limit": 1})


# ---------------------------------------------------------------- GIF picker
# Media chat: GIF disimpan sebagai kind='gif' + payload JSON (bukan teks), jadi
# penapis pautan tidak menyentuhnya dan URL sentiasa divalidasi semula di sini.
# Provider sebenar (Klipy/Giphy) dipanggil server-side supaya API key
# tidak pernah sampai ke pelayar. Tanpa key, app guna pek reaksi terbina dalam.
GIF_ENV = pathlib.Path("/home/ubuntu/.secrets/gif.env")
GIF_LOCAL_RE = re.compile(r"^/member/gifs/[a-z0-9_-]{1,40}\.gif$", re.I)
# Tenor is dead (Google discontinued the API in 2026) — Klipy is the official
# migration path, Giphy the alternate. Media hosts stay pinned so a stored
# payload can never point anywhere else.
GIF_HOSTS = {
    "static.klipy.com", "static1.klipy.com", "static2.klipy.com",
    "media.giphy.com", "i.giphy.com", "media0.giphy.com", "media1.giphy.com",
    "media2.giphy.com", "media3.giphy.com", "media4.giphy.com",
}
GIF_RATE = 20                  # carian GIF / minit / user
_last_gif = {}
_gif_key_cache = {"at": 0.0, "keys": {}}


def gif_keys():
    """Provider keys from the environment or /home/ubuntu/.secrets/gif.env.
    Cache 60s so editing the secrets file does not need a restart."""
    now = time.time()
    if now - _gif_key_cache["at"] < 60 and _gif_key_cache["keys"] is not None:
        return _gif_key_cache["keys"]
    keys = {k: (os.environ.get(k) or "").strip() for k in
            ("KLIPY_APP_KEY", "GIPHY_API_KEY")}
    try:
        for line in GIF_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in keys:
                keys[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    good = {k: v for k, v in keys.items() if v and not v.lower().startswith(("no", "changeme", "xxx"))}
    _gif_key_cache.update({"at": now, "keys": good})
    return good


def gif_ok():
    return bool(gif_keys())


def clean_gif(g):
    """Validate a GIF reference. Only same-site pack files or https media from
    a known provider host survive; everything else is rejected, never stored."""
    if not isinstance(g, dict):
        return None
    url = str(g.get("url") or "").strip()
    if len(url) > 500:
        return None
    if GIF_LOCAL_RE.match(url):
        final = url
    else:
        try:
            p = urllib.parse.urlparse(url)
        except ValueError:
            return None
        if p.scheme != "https" or (p.hostname or "").lower() not in GIF_HOSTS:
            return None
        final = urllib.parse.urlunparse(p._replace(query="", fragment=""))
        if len(final) > 400:
            return None
    title = re.sub(r"[\x00-\x1f]", "", str(g.get("title") or ""))[:60].strip() or "GIF"
    try:
        w = max(40, min(800, int(g.get("w") or 240)))
        h = max(40, min(800, int(g.get("h") or 240)))
    except (TypeError, ValueError):
        w = h = 240
    gid = re.sub(r"[^A-Za-z0-9_-]", "", str(g.get("id") or ""))[:60]
    return {"url": final, "title": title, "w": w, "h": h, "id": gid or None}


def _gif_http(url, timeout=8):
    req = urllib.request.Request(url, headers={
        "User-Agent": "TraderWatch/1.0 (+https://traderwatch.org)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _gif_fetch_klipy(q, key, limit):
    path = "search" if q else "trending"
    qs = {"per_page": max(8, min(50, limit)), "content_filter": "high", "locale": "en"}
    if q:
        qs["q"] = q
    url = "https://api.klipy.com/api/v1/%s/gifs/%s?%s" % (
        urllib.parse.quote(key, safe=""), path, urllib.parse.urlencode(qs))
    data = _gif_http(url)
    out = []
    for it in ((data.get("data") or {}).get("data") or [])[:limit]:
        files = it.get("file") or {}
        md = files.get("md") or files.get("hd") or files.get("sm") or {}
        gif = md.get("gif") or {}
        sm = (files.get("sm") or {}).get("gif") or gif
        if not gif.get("url"):
            continue
        out.append({"id": str(it.get("id") or it.get("slug") or ""),
                    "title": (it.get("title") or "GIF")[:60],
                    "url": gif["url"], "preview": sm.get("url") or gif["url"],
                    "w": int(gif.get("width") or 240), "h": int(gif.get("height") or 240)})
    return out


def _gif_fetch_giphy(q, key, limit):
    path = "search" if q else "trending"
    qs = {"api_key": key, "limit": limit, "rating": "pg-13"}
    if q:
        qs["q"] = q
    data = _gif_http("https://api.giphy.com/v1/gifs/%s?%s" % (path, urllib.parse.urlencode(qs)))
    out = []
    for it in data.get("data", [])[:limit]:
        imgs = it.get("images") or {}
        gif = imgs.get("downsized") or imgs.get("original") or {}
        prev = imgs.get("fixed_width_small") or imgs.get("fixed_width") or {}
        if not gif.get("url"):
            continue
        out.append({"id": str(it.get("id") or ""), "title": (it.get("title") or "GIF")[:60],
                    "url": gif["url"], "preview": prev.get("url") or gif["url"],
                    "w": int(gif.get("width") or 240), "h": int(gif.get("height") or 240)})
    return out


GIF_PROVIDERS = (("KLIPY_APP_KEY", "klipy", _gif_fetch_klipy),
                 ("GIPHY_API_KEY", "giphy", _gif_fetch_giphy))


def gif_search(q, limit=24):
    """Search the configured provider. Returns (provider, results); never raises
    past this point — the picker degrades to the built-in pack on any failure."""
    keys = gif_keys()
    for env_key, name, fn in GIF_PROVIDERS:
        key = keys.get(env_key)
        if not key:
            continue
        cache_key = "gif:%s:%s:%d" % (name, q.lower(), limit)
        def load(k=key, f=fn):
            try:
                return f(q, k, limit)
            except Exception:
                return []
        return name, _cached(cache_key, 300, load)
    return None, []


def rate_gif(uid):
    """Simple per-user token bucket: GIF_RATE searches per rolling minute."""
    now = time.time()
    slot = [t for t in _last_gif.get(uid, []) if now - t < 60]
    if len(slot) >= GIF_RATE:
        _last_gif[uid] = slot
        return False
    slot.append(now)
    _last_gif[uid] = slot
    return True


def is_admin_uid(uid):
    """Profiles role check, cached 60s. Only used to let admins moderate other
    people's messages; failure degrades to 'not admin' instead of erroring."""
    if not uid:
        return False

    def load():
        try:
            rows = sb("GET", "/rest/v1/profiles",
                      params={"select": "role", "id": "eq." + uid, "limit": 1}) or []
        except RuntimeError:
            return False
        return bool(rows) and (rows[0].get("role") or "").lower() == "admin"

    return _cached("admin:" + uid, 60, load)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 6) if f == f and abs(f) < 1e9 else None


def clean_card(c):
    """Validate a shared AI-signal card. Returns a normalised dict or None.
    Everything is re-validated server-side; the client is never trusted."""
    if not isinstance(c, dict):
        return None
    pair = str(c.get("pair") or "").upper()
    side = str(c.get("side") or "").upper()
    tf = str(c.get("tf") or "").upper()
    entry, sl, tp = _num(c.get("entry")), _num(c.get("sl")), _num(c.get("tp"))
    if pair not in ROOMS or side not in ("BUY", "SELL") or None in (entry, sl, tp):
        return None
    if tf not in CARD_TFS:
        tf = "M15"
    try:
        conf = max(0, min(100, int(float(c.get("conf") or 0))))
    except (TypeError, ValueError):
        conf = 0
    if side == "BUY" and not (sl < entry < tp):
        return None
    if side == "SELL" and not (tp < entry < sl):
        return None
    out = {"pair": pair, "side": side, "tf": tf, "entry": entry, "sl": sl, "tp": tp, "conf": conf}
    ctype = str(c.get("card_type") or "").lower()
    if ctype in ("tp", "trade", "signal"):
        out["card_type"] = ctype
    st = str(c.get("status") or "").lower()
    if st in ("open", "tp", "sl", "be", "expired"):
        out["status"] = st
    for ts_k in ("opened_at", "closed_at"):
        ts_v = str(c.get(ts_k) or "").strip()[:40]
        if ts_v:
            try:
                datetime.fromisoformat(ts_v.replace("Z", "+00:00"))
                out[ts_k] = ts_v
            except Exception:
                pass
    r_res = _num(c.get("r_result"))
    if r_res is not None and -50 <= r_res <= 200:
        out["r_result"] = round(r_res, 2)
    p_usd = _num(c.get("profit_usd"))
    if p_usd is not None and -1e6 <= p_usd <= 1e6:
        out["profit_usd"] = round(p_usd, 2)
    return out


def _rank_key(r):
    """Susunan rasmi liga — mesti sama dengan league-api.rank_key dan
    sortBoard() dalam member/index.html: win rate, kemudian net_r, kemudian
    bilangan trade. Kalau tidak, badge dalam chat bercanggah dengan senarai."""
    def f(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0
    def i(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    return (-f(r.get("win_rate")), -f(r.get("net_r")), -i(r.get("trades")))


def rank_map():
    """user_id -> league rank for the current top 3 (shown as a badge)."""
    def load():
        try:
            rows = sb("POST", "/rest/v1/rpc/get_leaderboard", body={"p_season": SEASON}) or []
        except RuntimeError:
            return {}
        rows = sorted(rows, key=_rank_key)
        return {r.get("user_id"): i + 1 for i, r in enumerate(rows[:3]) if r.get("user_id")}
    return _cached("rank", 60, load)


def room_counts():
    def load():
        try:
            rows = sb("GET", "/rest/v1/chat_messages",
                      params={"select": "room", "created_at": "gte." + day_start_utc(), "limit": 2000}) or []
        except RuntimeError:
            return {}
        out = {}
        for r in rows:
            rm = r.get("room") or "all"
            out[rm] = out.get(rm, 0) + 1
        return out
    return _cached("rooms", 10, load)


def load_reactions(ids, uid):
    """message_id -> {"reactions": {emoji: n}, "mine": [emoji]} (user ids never leave the server)."""
    out = {i: {"reactions": {}, "mine": []} for i in ids}
    if not ids or not rx_ok():
        return out
    try:
        rows = sb("GET", "/rest/v1/chat_reactions",
                  params={"select": "message_id,emoji,user_id",
                          "message_id": "in.(" + ",".join(str(int(i)) for i in ids) + ")",
                          "limit": 3000}) or []
    except RuntimeError:
        return out
    for r in rows:
        slot = out.get(r.get("message_id"))
        em = r.get("emoji")
        if slot is None or em not in EMOJIS:
            continue
        slot["reactions"][em] = slot["reactions"].get(em, 0) + 1
        if r.get("user_id") == uid:
            slot["mine"].append(em)
    return out


# ---------------------------------------------------------------- Orbit Friends / Welcoming / Private DM
def _push_env():
    if not PUSH_ENV.exists():
        return {}
    sec = {}
    for line in PUSH_ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


def send_push_async(uid, title, body, url, tag="tw-friends"):
    """Best-effort Web Push in a background thread (never blocks HTTP)."""
    def _worker():
        try:
            env = _push_env()
            priv = env.get("VAPID_PRIVATE_KEY")
            if not priv:
                return
            rows = sb("GET", "/rest/v1/push_subs", params={
                "select": "id,endpoint,p256dh,auth",
                "user_id": "eq." + uid, "limit": "30"}) or []
            if not rows:
                return
            from pywebpush import webpush
            data = json.dumps({
                "title": title,
                "body": body,
                "icon": "/member/icons/icon-192.png?v=20261124a",
                "tag": tag,
                "url": url,
            })
            subj = env.get("VAPID_SUBJECT", "mailto:ops@traderwatch.org")
            for sub in rows:
                try:
                    webpush(
                        subscription_info={"endpoint": sub["endpoint"],
                                           "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                        data=data, vapid_private_key=priv, vapid_claims={"sub": subj})
                except Exception as e:
                    scode = getattr(getattr(e, "response", None), "status_code", None)
                    if scode in (404, 410):
                        try:
                            sb("DELETE", "/rest/v1/push_subs", params={"id": "eq." + str(sub["id"])})
                        except Exception:
                            pass
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


def _valid_uuid(s):
    return isinstance(s, str) and bool(UUID_RE.match(s.strip()))


TEST_EMAIL_DOMAINS = (
    "test.traderwatch.org", "example.com", "example.org", "example.net",
    "localhost", "invalid", "test.local",
)
TEST_LOCAL_RE = re.compile(r"^(qc-|tw-auth-|e2e-|qa-|smoke-|bot-)", re.I)


def is_real_client(u):
    """Only include real verified clients — exclude QA/test/bot and unconfirmed accounts."""
    email = (u.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return False
    local, dom = email.rsplit("@", 1)
    if dom in TEST_EMAIL_DOMAINS or dom.endswith(".test") or dom.endswith(".example"):
        return False
    if TEST_LOCAL_RE.match(local):
        return False
    if not u.get("email_confirmed_at"):
        return False
    if u.get("is_anonymous"):
        return False
    return True


def users_directory():
    """Cached public directory from auth.users (real verified clients only;
    id, display name, created_at ONLY — never exposes email or private metadata)."""
    def load():
        by_id = {}
        ordered = []
        for page in range(1, 11):
            try:
                res = sb("GET", "/auth/v1/admin/users",
                         params={"page": page, "per_page": 200}) or {}
            except RuntimeError:
                break
            batch = res.get("users") if isinstance(res, dict) else (res if isinstance(res, list) else [])
            if not batch:
                break
            for u in batch:
                uid = u.get("id")
                if not uid or not is_real_client(u):
                    continue
                item = {
                    "id": uid,
                    "raw": display_name_full(u),   # mentah, untuk disambiguate()
                    "created_at": u.get("created_at") or "",
                }
                by_id[uid] = item
                ordered.append(item)
            if len(batch) < 200:
                break
        ordered.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        # Nama yang berlanggar ("Aidil" vs "Aidil") dibezakan sekali sahaja di
        # sini, ikut uid; setiap endpoint kemudian guna nama yang sama.
        names = disambiguate(ordered)
        for item in ordered:
            item["username"] = names.get(item["id"], "Trader")
        return {"by_id": by_id, "ordered": ordered}
    return _cached("users_dir", 20, load)


def _pair_filter(a, b):
    return f"(and(requester_id.eq.{a},addressee_id.eq.{b}),and(requester_id.eq.{b},addressee_id.eq.{a}))"


def get_friendship(a, b):
    rows = sb("GET", "/rest/v1/friendships", params={
        "select": "id,requester_id,addressee_id,status,created_at",
        "or": _pair_filter(a, b), "limit": 1}) or []
    return rows[0] if rows else None


def is_friends(a, b):
    """Dengan cache 30s: DM poll setiap 4s dan handler panggil ini setiap kali -
    tanpa cache, tiap poll bayar 1-2 query Supabase lagi."""
    key = "fr:" + (a + b if a < b else b + a)
    def load():
        row = get_friendship(a, b)
        return bool(row and row.get("status") == "accepted")
    return _cached(key, 30, load)


def build_friends_overview(uid):
    directory = users_directory()
    by_id = directory["by_id"]
    ordered = directory["ordered"]
    ranks = rank_map()
    online_ids = presence_online_set()
    day0 = day_start_utc()
    # Orbit space: kekal selama 1 jam sahaja (offline > 1 jam → hilang dari space).
    # Kiraan harian New Traders kekal reset 12:00 tengah malam waktu Malaysia (day0).
    seen_1h_ids = {u for u, ts in _seen.items() if ts >= time.time() - 3600} | online_ids
    seen_today_ids = seen_1h_ids

    today_joined = sum(1 for u in ordered if (u.get("created_at") or "") >= day0)
    total_members = len(ordered)

    try:
        frows = sb("GET", "/rest/v1/friendships", params={
            "select": "id,requester_id,addressee_id,status,created_at,updated_at",
            "or": f"(requester_id.eq.{uid},addressee_id.eq.{uid})",
            "order": "updated_at.desc", "limit": 300}) or []
    except RuntimeError:
        frows = []

    rel_map = {}         # other_id -> accepted | pending_out | pending_in
    friend_ids = []
    requests_in = []
    outgoing_ids = []
    for f in frows:
        st = f.get("status")
        req_id, add_id = f.get("requester_id"), f.get("addressee_id")
        other = add_id if req_id == uid else req_id
        if not other or other == uid:
            continue
        if st == "accepted":
            rel_map[other] = "accepted"
            friend_ids.append(other)
        elif st == "pending":
            if req_id == uid:
                rel_map[other] = "pending_out"
                outgoing_ids.append(other)
            else:
                rel_map[other] = "pending_in"
                info = by_id.get(other) or {"username": "Trader"}
                requests_in.append({
                    "id": other,
                    "friendship_id": f.get("id"),
                    "username": DEV_NAME if is_dev_uid(other) else info["username"],
                    "is_dev": is_dev_uid(other),
                    "avatar_url": avatar_url_for(other),
                    "rank": ranks.get(other),
                    "created_at": f.get("created_at") or "",
                })

    # Latest DM & unread count per friend
    last_dm = {}
    unread_by = {}
    if friend_ids:
        cutoff24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        try:
            drows = sb("GET", "/rest/v1/dm_messages", params={
                "select": "id,sender_id,recipient_id,body,kind,payload,read_at,created_at",
                "or": f"(sender_id.eq.{uid},recipient_id.eq.{uid})",
                "created_at": f"gte.{cutoff24}",
                "order": "created_at.desc", "limit": 400}) or []
        except RuntimeError:
            drows = []
        fset = set(friend_ids)
        for m in drows:
            s_id, r_id = m.get("sender_id"), m.get("recipient_id")
            other = r_id if s_id == uid else s_id
            if other not in fset:
                continue
            if other not in last_dm:
                last_dm[other] = m
            if r_id == uid and not m.get("read_at"):
                unread_by[other] = unread_by.get(other, 0) + 1

    friends = []
    for fid in friend_ids:
        info = by_id.get(fid) or {"username": "Trader"}
        lm = last_dm.get(fid)
        preview = ""
        if lm:
            if lm.get("kind") == "signal" and isinstance(lm.get("payload"), dict):
                p = lm["payload"]
                preview = f"Shared {p.get('pair', '')} {p.get('side', '')} setup".strip()
            else:
                preview = lm.get("body") or ""
        friends.append({
            "id": fid,
            "username": DEV_NAME if is_dev_uid(fid) else info["username"],
            "is_dev": is_dev_uid(fid),
            "avatar_url": avatar_url_for(fid),
            "online": fid in online_ids,
            "last_seen": last_seen_iso(fid),
            "seen_today": fid in seen_today_ids,
            "rank": ranks.get(fid),
            "unread": unread_by.get(fid, 0),
            "last_msg": preview,
            "last_from_me": bool(lm and lm.get("sender_id") == uid),
            "last_at": (lm.get("created_at") if lm else "") or "",
        })
    friends.sort(key=lambda x: (1 if x["last_at"] else 0, x["last_at"], 1 if x["online"] else 0, x["username"].lower()), reverse=True)

    # Unlimited new registrations hari ini (reset 12:00 malam waktu Malaysia / MYT)
    newest_24h = [u for u in ordered if u["id"] != uid and (u.get("created_at") or "") >= day0]
    newest = newest_24h if newest_24h else [u for u in ordered if u["id"] != uid][:12]
    wave_counts = {}
    my_waves = set()
    if newest:
        ids_csv = ",".join(u["id"] for u in newest[:150])
        try:
            wrows = sb("GET", "/rest/v1/member_waves", params={
                "select": "from_user_id,to_user_id",
                "to_user_id": f"in.({ids_csv})", "limit": 500}) or []
        except RuntimeError:
            wrows = []
        for w in wrows:
            tid = w.get("to_user_id")
            wave_counts[tid] = wave_counts.get(tid, 0) + 1
            if w.get("from_user_id") == uid:
                my_waves.add(tid)

    arrivals = [{
        "id": u["id"],
        "username": DEV_NAME if is_dev_uid(u["id"]) else u["username"],
        "is_dev": is_dev_uid(u["id"]),
        "avatar_url": avatar_url_for(u["id"]),
        "created_at": u["created_at"],
        "rank": ranks.get(u["id"]),
        "online": u["id"] in online_ids,
        "waved": u["id"] in my_waves,
        "waves": wave_counts.get(u["id"], 0),
        "rel": rel_map.get(u["id"], "none"),
        "seen_today": u["id"] in seen_1h_ids,
        "seen_1h": u["id"] in seen_1h_ids,
    } for u in newest]

    # Semua ahli (bukan rakan) yang aktif dalam 1 jam terakhir — tiada had bilangan
    friend_set = set(friend_ids)
    orbit_active = []
    for u in ordered:
        oid = u["id"]
        if oid == uid or oid in friend_set or oid not in seen_1h_ids:
            continue
        orbit_active.append({
            "id": oid,
            "username": DEV_NAME if is_dev_uid(oid) else u["username"],
            "is_dev": is_dev_uid(oid),
            "avatar_url": avatar_url_for(oid),
            "created_at": u["created_at"],
            "rank": ranks.get(oid),
            "online": oid in online_ids,
            "last_seen": last_seen_iso(oid),
            "waved": oid in my_waves,
            "waves": wave_counts.get(oid, 0),
            "rel": rel_map.get(oid, "none"),
            "is_new": (u.get("created_at") or "") >= day0,
            "seen_1h": True,
        })
    orbit_active.sort(key=lambda x: (1 if x["online"] else 0, x["last_seen"] or x["created_at"] or ""), reverse=True)

    unread_dm_total = sum(unread_by.values())
    return {
        "me": {"id": uid, "username": (by_id.get(uid) or {}).get("username") or "Trader"},
        "today_joined": today_joined,
        "new_24h_count": len(newest_24h),
        "total_members": total_members,
        "online_count": presence_count(),
        "friends": friends,
        "requests": requests_in,
        "outgoing": outgoing_ids,
        "arrivals": arrivals,
        "orbit_active": orbit_active,
        "unread_total": unread_dm_total + len(requests_in),
        "unread_dm": unread_dm_total,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TraderWatchChat/1.0"

    def log_message(self, fmt, *args):
        pass                                  # keep the journal quiet

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        origin = self.headers.get("Origin") or ""
        allow = origin if origin in ("https://traderwatch.org", "https://www.traderwatch.org") else "https://traderwatch.org"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Vary", "Origin")
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

        user = verify_user(self._token())
        if not user:
            return self._send(401, {"error": "sign in required"})
        uid = user.get("id") or ""
        if uid:
            presence_beat(uid)          # sebarang aktiviti API dikira online
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        # ---- Orbit Friends overview (friends, requests, live arrivals, unread)
        if path == "/api/chat/friends/overview":
            if uid:
                presence_beat(uid)
            try:
                return self._send(200, build_friends_overview(uid))
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})

        # ---- Search traders by display name (never searches/exposes emails)
        if path == "/api/chat/friends/search":
            term = ((q.get("q") or [""])[0] or "").strip().lower()
            if not term:
                return self._send(200, {"results": []})
            directory = users_directory()
            ranks = rank_map()
            try:
                frows = sb("GET", "/rest/v1/friendships", params={
                    "select": "requester_id,addressee_id,status",
                    "or": f"(requester_id.eq.{uid},addressee_id.eq.{uid})", "limit": 300}) or []
            except RuntimeError:
                frows = []
            rel_map = {}
            for f in frows:
                st = f.get("status")
                other = f["addressee_id"] if f["requester_id"] == uid else f["requester_id"]
                if st == "accepted":
                    rel_map[other] = "accepted"
                elif st == "pending":
                    rel_map[other] = "pending_out" if f["requester_id"] == uid else "pending_in"
            hits = []
            for u in directory["ordered"]:
                if u["id"] == uid:
                    continue
                if term in u["username"].lower():
                    hits.append({
                        "id": u["id"],
                        "username": DEV_NAME if is_dev_uid(u["id"]) else u["username"],
                        "is_dev": is_dev_uid(u["id"]),
                        "avatar_url": avatar_url_for(u["id"]),
                        "rank": ranks.get(u["id"]),
                        "rel": rel_map.get(u["id"], "none"),
                    })
                    if len(hits) >= 15:
                        break
            return self._send(200, {"results": hits})

        # ---- Lightweight friend status (online / last seen / typing) — in-memory, murah
        #      untuk di-poll setiap ~2s semasa DM dibuka.
        if path == "/api/chat/dm/status":
            other = ((q.get("with") or [""])[0] or "").strip()
            if not _valid_uuid(other) or other == uid:
                return self._send(400, {"error": "invalid friend id"})
            try:
                if not is_friends(uid, other):
                    return self._send(403, {"error": "friends only"})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            return self._send(200, {
                "id": other,
                "online": other in presence_online_set(),
                "last_seen": last_seen_iso(other),
                "typing": is_typing(other, uid),
            })

        # ---- Private DM thread (strictly accepted friends only)
        if path == "/api/chat/dm":
            other = ((q.get("with") or [""])[0] or "").strip()
            if not _valid_uuid(other) or other == uid:
                return self._send(400, {"error": "invalid friend id"})
            try:
                if not is_friends(uid, other):
                    return self._send(403, {"error": "friends only"})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            try:
                limit = min(100, max(1, int((q.get("limit") or ["60"])[0])))
            except ValueError:
                limit = 60
            if uid:
                presence_beat(uid)
            cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            try:
                rows = sb("GET", "/rest/v1/dm_messages", params={
                    "select": ("id,sender_id,recipient_id,body,kind,payload,read_at,created_at,"
                               "reply_to,pinned,deleted,deleted_by,"
                               "parent:dm_messages!reply_to(id,body,kind,payload,sender_id,deleted)"),
                    "or": f"(and(sender_id.eq.{uid},recipient_id.eq.{other}),and(sender_id.eq.{other},recipient_id.eq.{uid}))",
                    "created_at": f"gte.{cutoff_iso}",
                    "order": "created_at.desc", "limit": limit}) or []
                # Mark incoming unread as read
                if any(r.get("recipient_id") == uid and not r.get("read_at") for r in rows):
                    sb("PATCH", "/rest/v1/dm_messages",
                       params={"sender_id": "eq." + other, "recipient_id": "eq." + uid, "read_at": "is.null"},
                       body={"read_at": datetime.now(timezone.utc).isoformat()})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            rows.reverse()
            # Bila PIN ditukar, Supabase PostgREST boleh pulangkan baris yang
            # sama dua kali (re-fetch dalam embed) — nyah-duplikasi ikut id.
            seen_ids = set()
            uniq = []
            for r in rows:
                if r["id"] in seen_ids:
                    continue
                seen_ids.add(r["id"])
                uniq.append(r)
            rows = uniq
            msgs = []
            for r in rows:
                deleted = bool(r.get("deleted"))
                parent = r.get("parent") or None
                # PostgREST boleh pulangkan embed sebagai SENARAI (bukan objek)
                # bila relationship !reply_to resolve ke banyak baris — ambil
                # yang pertama sahaja supaya handler tak crash (126x AttributeError).
                if isinstance(parent, list):
                    parent = parent[0] if parent else None
                if parent and parent.get("deleted"):
                    parent = dict(parent, body="")
                msgs.append({
                    "id": r["id"],
                    "me": r["sender_id"] == uid,
                    # Soft-deleted: isi disembunyikan, baris kekal (bubble "dipadam")
                    "body": "" if deleted else (r.get("body") or ""),
                    "kind": r.get("kind") or "text",
                    "payload": None if deleted else r.get("payload"),
                    "created_at": r.get("created_at") or "",
                    "deleted": deleted,
                    "mine_deleted": deleted and r.get("deleted_by") == uid,
                    "pinned": bool(r.get("pinned")),
                    "reply_to": r.get("reply_to"),
                    "reply": ({"id": parent["id"], "body": (parent.get("body") or "")[:90],
                               "kind": parent.get("kind") or "text",
                               "me": parent.get("sender_id") == uid} if parent else None),
                })
            info = (users_directory()["by_id"].get(other)) or {"username": "Trader"}
            info = dict(info, username=public_name(info.get("username")))
            pinned = [{"id": m["id"], "body": m["body"][:80], "kind": m["kind"], "me": m["me"]}
                      for m in msgs if m["pinned"] and not m["deleted"]]
            return self._send(200, {
                "friend": {
                    "id": other,
                    "username": DEV_NAME if is_dev_uid(other) else info["username"],
                    "is_dev": is_dev_uid(other),
                    "avatar_url": avatar_url_for(other),
                    "online": other in presence_online_set(),
                    "last_seen": last_seen_iso(other),
                    "typing": is_typing(other, uid),
                    "rank": rank_map().get(other),
                },
                "messages": msgs,
                "pinned": pinned[-1:],
            })

        # ---- GIF picker search (server-side proxy so no API key hits the client)
        if path == "/api/chat/gif":
            q_raw = ((q.get("q") or [""])[0] or "").strip()
            if len(q_raw) > 60:
                return self._send(400, {"error": "query too long"})
            if not rate_gif(uid):
                return self._send(429, {"error": "slow down"})
            provider, rows = gif_search(q_raw, 24)
            if not provider:
                return self._send(200, {"provider": None, "results": [],
                                        "hint": "no provider configured"})
            return self._send(200, {"provider": provider, "results": rows})

        if path != "/api/chat/messages":
            return self._send(404, {"error": "not found"})

        try:
            limit = min(100, max(1, int((q.get("limit") or ["50"])[0])))
        except ValueError:
            limit = 50

        ext = ext_ok()
        room = ((q.get("room") or ["all"])[0] or "all").upper()
        edit_ok = ed_ok()
        sel = "id,user_id,username,body,created_at" + (",room,kind,payload" if ext else "")
        if edit_ok:
            sel += ",edited_at"
        params = {"select": sel,
                  "created_at": "gte." + day_start_utc(),
                  "order": "created_at.desc",
                  "limit": limit}
        if ext and room in ROOMS:
            params["room"] = "eq." + room
        try:
            rows = sb("GET", "/rest/v1/chat_messages", params=params) or []
        except RuntimeError as e:
            return self._send(502, {"error": str(e)})
        if uid:
            presence_beat(uid)  # reading chat = active too
        ranks = rank_map()
        rx = load_reactions([r["id"] for r in rows], uid)
        # Nama baris chat ditulis semasa menghantar dan mungkin nama penuh lama.
        # Utamakan nama direktori (sudah ditapis + dibezakan ikut uid) supaya
        # "Aidil" dan "Aidil B." kekal konsisten dengan senarai rakan.
        dir_by_id = users_directory()["by_id"]
        for r in rows:
            owner = r.pop("user_id", None)
            dev = is_dev_uid(owner)
            r["username"] = DEV_NAME if dev else ((dir_by_id.get(owner) or {}).get("username") or public_name(r.get("username")))
            r["is_dev"] = dev
            r["avatar_url"] = avatar_url_for(owner)
            r["rank"] = ranks.get(owner)
            r["own"] = bool(uid) and owner == uid   # ownership by id, not by display name
            slot = rx.get(r["id"]) or {"reactions": {}, "mine": []}
            r["reactions"], r["mine"] = slot["reactions"], slot["mine"]
        return self._send(200, {"messages": rows, "reset_at_utc": day_start_utc(),
                                "online": presence_count(),
                                "rooms": room_counts() if ext else {},
                                "features": {"rooms": ext, "cards": ext,
                                             "reactions": rx_ok(), "edit": edit_ok,
                                             "gifs": gif_ok(), "mod": is_admin_uid(uid)}})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        user = verify_user(self._token())
        if not user:
            return self._send(401, {"error": "sign in required"})
        if user.get("id"):
            presence_beat(user["id"])   # sebarang aktiviti API dikira online

        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > AVATAR_MAX_RAW + 131072:
                return self._send(413, {"error": "payload too large"})
            payload = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            return self._send(400, {"error": "bad json"})

        # ---- profile picture upload / remove (auto-compressed <= 500 KB)
        if path == "/api/chat/avatar":
            uid = user.get("id") or ""
            if not uid or not UUID_RE.match(uid):
                return self._send(401, {"error": "sign in required"})
            now = time.time()
            if now - _last_avatar.get(uid, 0) < AVATAR_RATE_LIMIT:
                return self._send(429, {"error": "slow down"})
            _last_avatar[uid] = now
            if payload.get("remove"):
                try:
                    p = AVATAR_DIR / f"{uid}.jpg"
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
                try:
                    sb("PUT", "/auth/v1/user",
                       body={"data": {"avatar_url": ""}}, token=self._token())
                except RuntimeError as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"ok": True, "avatar_url": ""})
            img = payload.get("image")
            if not img:
                return self._send(400, {"error": "missing image"})
            try:
                url, nbytes = save_avatar_image(uid, img)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except RuntimeError as e:
                return self._send(500, {"error": str(e)})
            try:
                sb("PUT", "/auth/v1/user",
                   body={"data": {"avatar_url": url}}, token=self._token())
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            return self._send(200, {"ok": True, "avatar_url": url, "bytes": nbytes})

        # ---- presence heartbeat (online count)
        if path == "/api/chat/presence":
            uid = user.get("id") or ""
            if not uid:
                return self._send(401, {"error": "sign in required"})
            return self._send(200, {"ok": True, "online": presence_beat(uid)})

        # ---- typing indicator: {"to": "<friend uuid>", "typing": true|false}
        if path == "/api/chat/dm/typing":
            uid_t = user.get("id") or ""
            to_t = str(payload.get("to") or "").strip()
            if not uid_t or not _valid_uuid(to_t) or to_t == uid_t:
                return self._send(400, {"error": "invalid friend id"})
            try:
                if not is_friends(uid_t, to_t):
                    return self._send(403, {"error": "friends only"})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            typing_set(uid_t, to_t, bool(payload.get("typing", True)))
            return self._send(200, {"ok": True})

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

        # ---- reaction toggle: {"message_id": 12, "emoji": "🔥"}
        if path == "/api/chat/react":
            uid = user.get("id") or ""
            emoji = payload.get("emoji")
            try:
                mid = int(payload.get("message_id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "bad message_id"})
            if emoji not in EMOJIS:
                return self._send(400, {"error": "emoji not allowed"})
            if not rx_ok():
                return self._send(501, {"error": "reactions not enabled yet"})
            now = time.time()
            if now - _last_react.get(uid, 0) < REACT_COOLDOWN:
                return self._send(429, {"error": "slow down"})
            _last_react[uid] = now
            try:
                have = sb("GET", "/rest/v1/chat_reactions",
                          params={"select": "message_id", "message_id": "eq." + str(mid),
                                  "user_id": "eq." + uid, "emoji": "eq." + emoji, "limit": 1})
                if have:
                    sb("DELETE", "/rest/v1/chat_reactions",
                       params={"message_id": "eq." + str(mid), "user_id": "eq." + uid, "emoji": "eq." + emoji})
                else:
                    sb("POST", "/rest/v1/chat_reactions",
                       body={"message_id": mid, "user_id": uid, "emoji": emoji})
            except RuntimeError:
                return self._send(400, {"error": "message not found"})
            slot = load_reactions([mid], uid).get(mid) or {"reactions": {}, "mine": []}
            return self._send(200, {"ok": True, "message_id": mid, **slot})

        # ---- Friend request (auto-accepts if inverse pending exists)
        if path == "/api/chat/friends/request":
            uid = user.get("id") or ""
            target = str(payload.get("user_id") or "").strip()
            if not _valid_uuid(target) or target == uid:
                return self._send(400, {"error": "invalid user_id"})
            if target not in users_directory()["by_id"]:
                return self._send(404, {"error": "user not found"})
            me_name = display_name(user)
            try:
                ex = get_friendship(uid, target)
                now_iso = datetime.now(timezone.utc).isoformat()
                if ex:
                    if ex["status"] == "accepted":
                        return self._send(200, {"ok": True, "status": "accepted"})
                    if ex["status"] == "pending" and ex["requester_id"] == target:
                        sb("PATCH", "/rest/v1/friendships",
                           params={"id": "eq." + str(ex["id"])},
                           body={"status": "accepted", "updated_at": now_iso})
                        send_push_async(target, "You're now friends",
                                        f"{me_name} accepted your friend request",
                                        "https://traderwatch.org/member/?view=friends&dm=" + uid,
                                        "tw-fr-" + uid[:8])
                        return self._send(200, {"ok": True, "status": "accepted"})
                    if ex["status"] == "pending" and ex["requester_id"] == uid:
                        return self._send(200, {"ok": True, "status": "pending"})
                    sb("PATCH", "/rest/v1/friendships",
                       params={"id": "eq." + str(ex["id"])},
                       body={"requester_id": uid, "addressee_id": target, "status": "pending", "updated_at": now_iso})
                else:
                    sb("POST", "/rest/v1/friendships",
                       body={"requester_id": uid, "addressee_id": target, "status": "pending"})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            send_push_async(target, "Friend request",
                            f"{me_name} wants to connect on Trader Watch",
                            "https://traderwatch.org/member/?view=friends",
                            "tw-fr-" + uid[:8])
            return self._send(201, {"ok": True, "status": "pending"})

        # ---- Respond to friend request or unfriend: accept | decline | remove | cancel
        if path == "/api/chat/friends/respond":
            uid = user.get("id") or ""
            target = str(payload.get("user_id") or "").strip()
            action = str(payload.get("action") or "").strip().lower()
            if not _valid_uuid(target) or target == uid or action not in ("accept", "decline", "remove", "cancel"):
                return self._send(400, {"error": "invalid request"})
            try:
                ex = get_friendship(uid, target)
                if not ex:
                    return self._send(404, {"error": "not found"})
                if action == "accept":
                    if ex["status"] == "accepted":
                        return self._send(200, {"ok": True, "status": "accepted"})
                    if ex["addressee_id"] != uid or ex["status"] != "pending":
                        return self._send(403, {"error": "cannot accept"})
                    sb("PATCH", "/rest/v1/friendships",
                       params={"id": "eq." + str(ex["id"])},
                       body={"status": "accepted", "updated_at": datetime.now(timezone.utc).isoformat()})
                    send_push_async(target, "You're now friends",
                                    f"{display_name(user)} accepted your friend request",
                                    "https://traderwatch.org/member/?view=friends&dm=" + uid,
                                    "tw-fr-" + uid[:8])
                    return self._send(200, {"ok": True, "status": "accepted"})
                sb("DELETE", "/rest/v1/friendships", params={"id": "eq." + str(ex["id"])})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            return self._send(200, {"ok": True, "status": "removed"})

        # ---- Wave welcome to a newcomer
        if path == "/api/chat/friends/wave":
            uid = user.get("id") or ""
            target = str(payload.get("user_id") or "").strip()
            if not _valid_uuid(target) or target == uid:
                return self._send(400, {"error": "invalid user_id"})
            if target not in users_directory()["by_id"]:
                return self._send(404, {"error": "user not found"})
            now = time.time()
            if now - _last_wave.get(uid, 0) < 0.8:
                return self._send(429, {"error": "slow down"})
            _last_wave[uid] = now
            try:
                have = sb("GET", "/rest/v1/member_waves", params={
                    "select": "id", "from_user_id": "eq." + uid, "to_user_id": "eq." + target, "limit": 1}) or []
                if have:
                    return self._send(200, {"ok": True, "already": True})
                sb("POST", "/rest/v1/member_waves", body={"from_user_id": uid, "to_user_id": target})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            send_push_async(target, "Welcome to Trader Watch",
                            f"{display_name(user)} waved to welcome you!",
                            "https://traderwatch.org/member/?view=friends",
                            "tw-wave-" + uid[:8])
            return self._send(201, {"ok": True, "already": False})

        # ---- Send private DM (strictly between accepted friends)
        # ---- pin / unpin a DM (either party may pin) ----
        if path == "/api/chat/dm/pin":
            uid = user.get("id") or ""
            try:
                mid = int(payload.get("id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "bad id"})
            want = bool(payload.get("pinned"))
            try:
                rows = sb("GET", "/rest/v1/dm_messages", params={
                    "select": "id,sender_id,recipient_id,pinned",
                    "id": f"eq.{mid}", "limit": 1}) or []
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            if not rows or uid not in (rows[0]["sender_id"], rows[0]["recipient_id"]):
                return self._send(403, {"error": "not your chat"})
            try:
                upd = sb("PATCH", "/rest/v1/dm_messages",
                         params={"id": f"eq.{mid}"}, body={"pinned": want}) or []
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            m = (upd or [{}])[0]
            return self._send(200, {"ok": True, "id": mid, "pinned": bool(m.get("pinned", want))})

        # ---- soft-delete own message (content hidden, row kept) ----
        if path == "/api/chat/dm/delete":
            uid = user.get("id") or ""
            try:
                mid = int(payload.get("id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "bad id"})
            try:
                rows = sb("GET", "/rest/v1/dm_messages", params={
                    "select": "id,sender_id", "id": f"eq.{mid}", "limit": 1}) or []
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            if not rows or rows[0]["sender_id"] != uid:
                return self._send(403, {"error": "only your own messages"})
            try:
                sb("PATCH", "/rest/v1/dm_messages", params={"id": f"eq.{mid}"},
                   body={"deleted": True, "deleted_by": uid, "body": "", "payload": None})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            return self._send(200, {"ok": True, "id": mid, "deleted": True})

        if path == "/api/chat/dm":
            uid = user.get("id") or ""
            target = str(payload.get("to") or "").strip()
            if not _valid_uuid(target) or target == uid:
                return self._send(400, {"error": "invalid recipient"})
            try:
                if not is_friends(uid, target):
                    return self._send(403, {"error": "friends only"})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            now = time.time()
            if now - _last_dm.get(uid, 0) < DM_RATE_LIMIT:
                return self._send(429, {"error": "slow down"})
            raw = str(payload.get("text") or "").strip()
            card = None
            if payload.get("card"):
                card = clean_card(payload.get("card"))
                if not card:
                    return self._send(400, {"error": "invalid signal card"})
            gif = None
            if payload.get("gif"):
                gif = clean_gif(payload.get("gif"))
                if not gif:
                    return self._send(400, {"error": "invalid gif"})
            if not raw and not card and not gif:
                return self._send(400, {"error": "empty message"})
            if len(raw) > MAX_LEN:
                return self._send(400, {"error": f"max {MAX_LEN} characters"})
            clean_txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw).strip()
            if not clean_txt and card:
                clean_txt = f"Shared {card['pair']} {card['side']} setup"
            row = {
                "sender_id": uid,
                "recipient_id": target,
                "body": clean_txt,
                "kind": "gif" if gif else ("signal" if card else "text"),
                "payload": gif or card,
            }
            # Reply-to: mesti mesej dalam thread yang sama (rakan sahaja).
            rt = payload.get("reply_to")
            if rt is not None:
                try:
                    rt_id = int(rt)
                except (TypeError, ValueError):
                    return self._send(400, {"error": "bad reply_to"})
                try:
                    chk = sb("GET", "/rest/v1/dm_messages", params={
                        "select": "id,sender_id,recipient_id",
                        "id": f"eq.{rt_id}", "limit": 1}) or []
                except RuntimeError:
                    chk = []
                ok = bool(chk) and {chk[0]["sender_id"], chk[0]["recipient_id"]} == {uid, target}
                if ok:
                    row["reply_to"] = rt_id
            _last_dm[uid] = now
            typing_set(uid, target, False)      # mesej dihantar → tamat "typing"
            try:
                rows = sb("POST", "/rest/v1/dm_messages", body=row) or [{}]
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            m = rows[0]
            out_msg = {
                "id": m.get("id"),
                "me": True,
                "body": m.get("body") or clean_txt,
                "kind": m.get("kind") or row["kind"],
                "payload": m.get("payload"),
                "created_at": m.get("created_at") or datetime.now(timezone.utc).isoformat(),
                "pinned": bool(m.get("pinned")),
                "deleted": False,
                "reply_to": m.get("reply_to"),
                "reply": ({"id": rt_id, "body": str(payload.get("reply_body") or "")[:90],
                           "me": False} if row.get("reply_to") else None),
            }
            me_name = display_name(user)
            push_body = (f"Shared {card['pair']} {card['side']} setup" if card
                         else ("Sent a GIF" if gif else clean_txt[:120]))
            send_push_async(target, me_name, push_body,
                            "https://traderwatch.org/member/?view=friends&dm=" + uid,
                            "tw-dm-" + uid[:8])
            return self._send(201, {"message": out_msg})

        # ---- edit / delete your own community message -------------------------
        # {"id": 12, "text": "..."}  |  {"id": 12}
        # Ownership is checked against chat_messages.user_id, never the display
        # name. Admins may delete (not edit) anyone's message for moderation.
        if path in ("/api/chat/edit", "/api/chat/delete"):
            uid = user.get("id") or ""
            try:
                mid = int(payload.get("id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "bad id"})
            if not ed_ok():
                return self._send(501, {"error": "edit/delete not enabled yet"})
            try:
                rows = sb("GET", "/rest/v1/chat_messages", params={
                    "select": "id,user_id,body,kind,created_at",
                    "id": f"eq.{mid}", "created_at": "gte." + day_start_utc(),
                    "limit": 1}) or []
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            if not rows:
                return self._send(404, {"error": "message not found"})
            row = rows[0]
            mine = row.get("user_id") == uid

            if path == "/api/chat/delete":
                if not mine and not is_admin_uid(uid):
                    return self._send(403, {"error": "only your own messages"})
                params = {"id": f"eq.{mid}"}
                if mine:
                    params["user_id"] = f"eq.{uid}"      # belt and braces
                try:
                    sb("DELETE", "/rest/v1/chat_messages", params=params)
                except RuntimeError as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"ok": True, "id": mid, "deleted": True})

            if not mine:
                return self._send(403, {"error": "only your own messages"})
            if (row.get("kind") or "text") == "signal":
                return self._send(400, {"error": "signal cards cannot be edited"})
            raw = str(payload.get("text") or "").strip()
            if not raw:
                return self._send(400, {"error": "empty message"})
            if len(raw) > MAX_LEN:
                return self._send(400, {"error": f"max {MAX_LEN} characters"})
            now = time.time()
            if now - _last_edit.get(uid, 0) < EDIT_RATE_LIMIT:
                return self._send(429, {"error": "slow down"})
            clean, actions = sanitise(raw)
            if not clean:
                return self._send(400, {"error": "message filtered out"})
            _last_edit[uid] = now
            edited_at = datetime.now(timezone.utc).isoformat()
            try:
                upd = sb("PATCH", "/rest/v1/chat_messages", params={"id": f"eq.{mid}"},
                         body={"body": clean, "edited_at": edited_at}) or []
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            stored = (upd or [{}])[0]
            return self._send(200, {"ok": True, "id": mid,
                                    "body": stored.get("body", clean),
                                    "edited_at": stored.get("edited_at", edited_at),
                                    "filtered": actions})

        if path != "/api/chat/messages":
            return self._send(404, {"error": "not found"})

        raw = str(payload.get("text") or "").strip()
        card = None
        if payload.get("card"):
            card = clean_card(payload.get("card"))
            if not card:
                return self._send(400, {"error": "invalid signal card"})
            if not ext_ok():
                return self._send(501, {"error": "signal cards not enabled yet"})
        gif = None
        if payload.get("gif"):
            gif = clean_gif(payload.get("gif"))
            if not gif:
                return self._send(400, {"error": "invalid gif"})
            if not ext_ok():
                return self._send(501, {"error": "gifs not enabled yet"})
        if not raw and not card and not gif:
            return self._send(400, {"error": "empty message"})
        if len(raw) > MAX_LEN:
            return self._send(400, {"error": f"max {MAX_LEN} characters"})

        uid = user.get("id") or ""
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_post.get(uid, 0) < RATE_LIMIT_SECONDS:
            return self._send(429, {"error": "slow down"})

        clean, actions = sanitise(raw) if raw else ("", [])
        if not clean and not card and not gif:
            return self._send(400, {"error": "message filtered out"})
        if not clean and card:
            clean = "Kongsi setup AI"
        if not clean and gif:
            clean = "GIF"

        dev_post = is_dev_uid(uid)
        row = {"user_id": uid, "username": DEV_NAME if dev_post else public_name(display_name(user)), "body": clean}
        if ext_ok():
            room = str(payload.get("room") or "").upper()
            row["room"] = card["pair"] if card else (room if room in ROOMS else "all")
            row["kind"] = "gif" if gif else ("signal" if card else "text")
            if card:
                row["payload"] = card
            if gif:
                row["payload"] = gif

        _last_post[uid] = now
        try:
            rows = sb("POST", "/rest/v1/chat_messages", body=row)
        except RuntimeError as e:
            return self._send(502, {"error": str(e)})
        msg = (rows or [{}])[0]
        msg.pop("user_id", None)
        msg["own"] = True
        msg["is_dev"] = dev_post
        if dev_post:
            msg["username"] = DEV_NAME
        msg["avatar_url"] = avatar_url_for(uid)
        msg.setdefault("reactions", {})
        msg.setdefault("mine", [])
        return self._send(201, {"message": msg, "filtered": actions})


def main():
    threading.Thread(target=_dm_purge_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"chat api listening on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
