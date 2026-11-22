#!/usr/bin/env python3
"""TraderWatch Web Push API (VAPID).

Endpoints (Caddy proxies /api/push/* here, port 8105):
  GET  /api/push/vapid        -> {publicKey}
  POST /api/push/subscribe    -> {endpoint, keys:{p256dh,auth}, kinds} upsert by endpoint
  POST /api/push/unsubscribe  -> {endpoint} delete own row
  GET  /api/push/status        -> {subscribed, kinds}
  POST /api/push/test         -> send a test push to own subs -> {sent:n}

Auth: Supabase member Bearer token on every call (same pattern as league-api).
"""
import json
import os
import pathlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENV = pathlib.Path("/home/ubuntu/.secrets/supabase.env")
PUSH_ENV = pathlib.Path("/home/ubuntu/.secrets/push.env")
PORT = int(os.environ.get("PUSH_PORT", "8105"))

_cache = {}
_cache_lock = threading.Lock()
AUTH_TTL = 120


def load_env(path):
    sec = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    return sec


SEC = load_env(ENV)
PUSH = load_env(PUSH_ENV) if PUSH_ENV.exists() else {}
SB_URL = SEC["SUPABASE_URL"].rstrip("/")
SB_KEY = SEC["SUPABASE_SERVICE_KEY"]
VAPID_PUBLIC = PUSH.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE = PUSH.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = PUSH.get("VAPID_SUBJECT", "mailto:ops@traderwatch.org")


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat()} PUSH-API {msg}", flush=True)


def sb(method, path, body=None, params=None, token=None):
    url = SB_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SB_KEY)
    req.add_header("Authorization", "Bearer " + (token or SB_KEY))
    req.add_header("Content-Type", "application/json")
    headers = {"Prefer": "resolution=merge-duplicates"} if method == "POST" else {}
    for k, v in headers.items():
        req.add_header(k, v)
    if method == "POST":
        url += "&" if "?" in url else "?"
        url += "on_conflict=endpoint"
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip() else None


def verify_user(token):
    if not token:
        return None
    ck = "auth:" + token
    now = time.time()
    with _cache_lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] <= AUTH_TTL:
            return hit[1]
    try:
        req = urllib.request.Request(SB_URL + "/auth/v1/user")
        req.add_header("apikey", SB_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as r:
            user = json.loads(r.read().decode())
        if user and user.get("id"):
            with _cache_lock:
                _cache[ck] = (now, user)
        return user
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None


def webpush_send(sub, payload):
    """Send one push. Raises on failure. sub = row dict from push_subs.
    Returns the HTTP status. Lazily imports pywebpush (installed --user)."""
    from pywebpush import webpush
    resp = webpush(
        subscription_info={
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        },
        data=json.dumps(payload),
        vapid_private_key=VAPID_PRIVATE,
        vapid_claims={"sub": VAPID_SUBJECT},
    )
    return resp.status_code


def send_to_user(uid, payload):
    """Push payload to all of a user's subs. Deletes dead rows (404/410).
    Returns count sent. NEVER raises (push must not break callers)."""
    sent = 0
    try:
        rows = sb("GET", "/rest/v1/push_subs", params={
            "select": "id,endpoint,p256dh,auth,kinds",
            "user_id": f"eq.{uid}", "limit": "50"}) or []
    except Exception as e:
        log(f"send_to_user {uid[:8]} fetch error {type(e).__name__}: {str(e)[:120]}")
        return 0
    for sub in rows:
        try:
            code = webpush_send(sub, payload)
            if code in (200, 201):
                sent += 1
        except Exception as e:
            code = getattr(e, "response", None)
            scode = getattr(code, "status_code", None) or getattr(e, "status_code", None)
            log(f"push fail {sub['id']} {type(e).__name__}: {str(e)[:120]}")
            if scode in (404, 410):
                try:
                    sb("DELETE", "/rest/v1/push_subs", params={"id": f"eq.{sub['id']}"})
                    log(f"deleted dead sub {sub['id']} ({scode})")
                except Exception as de:
                    log(f"delete sub error {de}")
    return sent


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _token(self):
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def _user(self):
        u = verify_user(self._token())
        return u if u and u.get("id") else None

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/push/health":
            return self._send(200, {"ok": True})
        user = self._user()
        if not user:
            return self._send(401, {"error": "Please sign in as a member."})
        uid = user["id"]
        try:
            if path == "/api/push/vapid":
                return self._send(200, {"publicKey": VAPID_PUBLIC})
            if path == "/api/push/status":
                rows = sb("GET", "/rest/v1/push_subs", params={
                    "select": "kinds", "user_id": f"eq.{uid}", "limit": "50"}) or []
                kinds = sorted({r.get("kinds", "tpsl") for r in rows})
                return self._send(200, {"subscribed": bool(rows), "kinds": kinds})
        except urllib.error.HTTPError as e:
            log(f"GET {path} sb HTTP {e.code}")
            return self._send(502, {"error": "Push service error. Try again."})
        except Exception as e:
            log(f"GET {path} error {type(e).__name__}: {str(e)[:140]}")
            return self._send(500, {"error": "Something went wrong. Try again."})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/api/push/subscribe", "/api/push/unsubscribe", "/api/push/test"):
            return self._send(404, {"error": "not found"})
        user = self._user()
        if not user:
            return self._send(401, {"error": "Please sign in as a member."})
        uid = user["id"]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return self._send(400, {"error": "Invalid request."})
        try:
            if path == "/api/push/subscribe":
                endpoint = str(req.get("endpoint") or "").strip()
                keys = req.get("keys") or {}
                p256dh = str(keys.get("p256dh") or "").strip()
                auth = str(keys.get("auth") or "").strip()
                kinds = req.get("kinds") if req.get("kinds") in ("tpsl", "all") else "tpsl"
                if not (endpoint.startswith("https://") and p256dh and auth):
                    return self._send(400, {"error": "Invalid subscription."})
                sb("POST", "/rest/v1/push_subs", body={
                    "user_id": uid, "endpoint": endpoint,
                    "p256dh": p256dh, "auth": auth, "kinds": kinds})
                log(f"{uid[:8]} subscribed kinds={kinds}")
                return self._send(200, {"ok": True, "kinds": kinds})
            if path == "/api/push/unsubscribe":
                endpoint = str(req.get("endpoint") or "").strip()
                if not endpoint:
                    return self._send(400, {"error": "Missing endpoint."})
                sb("DELETE", "/rest/v1/push_subs", params={
                    "user_id": f"eq.{uid}", "endpoint": f"eq.{endpoint}"})
                log(f"{uid[:8]} unsubscribed")
                return self._send(200, {"ok": True})
            if path == "/api/push/test":
                sent = send_to_user(uid, {
                    "title": "🔔 TraderWatch",
                    "body": "Notifikasi ujian berjaya — alert TP/SL akan sampai di sini.",
                    "url": "https://traderwatch.org/member/"})
                return self._send(200, {"sent": sent})
        except urllib.error.HTTPError as e:
            log(f"POST {path} sb HTTP {e.code}: {e.read().decode()[:160]}")
            return self._send(502, {"error": "Push service error. Try again."})
        except Exception as e:
            log(f"POST {path} error {type(e).__name__}: {str(e)[:140]}")
            return self._send(500, {"error": "Something went wrong. Try again."})


def main():
    if not VAPID_PUBLIC or not VAPID_PRIVATE:
        log("WARNING: VAPID keys missing — subscribe/send will fail")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"listening on 127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
