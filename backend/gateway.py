

import time
from collections import deque
from threading import Lock

from flask import current_app, g, jsonify, request, session

# Reachable without a Google session — everything else needs one.
PUBLIC_PATHS = {"/", "/health", "/login", "/oauth2callback", "/logout"}

DEFAULT_LIMIT = (120, 60)
ROUTE_LIMITS = {
    "/generate_email": (10, 60),
    "/summarize_email": (10, 60),
    "/send_email": (20, 60),
}

# GET responses worth reusing, and how long they stay fresh (seconds).
# /get_email is deliberately absent: reading one marks it read in Gmail.
CACHE_TTL = {"/list_emails": 30, "/list_labels": 300, "/folders": 60}

MAX_BODY_BYTES = 25 * 1024 * 1024  # /send_email accepts attachments

# ponytail: one lock over two in-process dicts, which is right for the single
# worker this runs as. Both move to Redis the day a second worker appears.
_lock = Lock()
_hits = {}  # (bucket, client ip) -> deque of request timestamps
_cache = {}  # (session id, full path) -> (expires_at, body, mimetype)


def _client():
    """Rate-limit identity: the IP, so dropping the cookie does not reset it."""
    return request.remote_addr or "unknown"


def _viewer():
    """Cache identity: the signed-in account, so one user never sees another's.

    Keying on the session id alone was not enough: /logout clears the session
    data but keeps the same id, so signing in as a second Google account on the
    same browser inherited the first account's cached inbox for the TTL.
    """
    return session.get("email_address") or getattr(session, "sid", None) or _client()


def _retry_after(client, path):
    """Seconds the client must wait, or 0 when the request may go through."""
    buckets = [(("*", client), DEFAULT_LIMIT)]
    if path in ROUTE_LIMITS:
        buckets.append(((path, client), ROUTE_LIMITS[path]))

    now = time.monotonic()
    with _lock:
        # check every bucket before recording, so a request denied by the global
        # limit is not also charged against the per-route one
        for key, (limit, window) in buckets:
            hits = _hits.setdefault(key, deque())
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                return int(window - (now - hits[0])) + 1

        for key, _ in buckets:
            _hits[key].append(now)

    return 0


def _cache_get(key):
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None

        expires_at, body, mimetype = entry
        if expires_at <= time.monotonic():
            del _cache[key]
            return None

        return body, mimetype


def _cache_put(key, ttl, body, mimetype):
    now = time.monotonic()
    with _lock:
        _cache[key] = (now + ttl, body, mimetype)
        for stale in [k for k, entry in _cache.items() if entry[0] <= now]:
            del _cache[stale]


def _cache_flush(viewer):
    """A write makes everything this viewer has cached suspect."""
    with _lock:
        for key in [k for k in _cache if k[0] == viewer]:
            del _cache[key]


def install_gateway(app):
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    _hits.clear()
    _cache.clear()

    @app.before_request
    def _gate():
        if request.method == "OPTIONS":  # CORS preflight carries no cookie
            return None

        if request.path not in PUBLIC_PATHS and "credentials" not in session:
            return jsonify({"error": "not_authenticated"}), 401

        wait = _retry_after(_client(), request.path)
        if wait:
            return (
                jsonify({"error": "rate_limited", "retry_after": wait}),
                429,
                {"Retry-After": str(wait)},
            )

        ttl = CACHE_TTL.get(request.path)
        if ttl and request.method == "GET":
            key = (_viewer(), request.full_path)
            cached = _cache_get(key)
            if cached is None:
                g.cache_key, g.cache_ttl = key, ttl
            else:
                body, mimetype = cached
                response = current_app.response_class(body, mimetype=mimetype)
                response.headers["X-Cache"] = "HIT"
                return response

        return None

    @app.after_request
    def _finish(response):
        key = g.pop("cache_key", None)

        if key and response.status_code == 200 and not response.direct_passthrough:
            _cache_put(key, g.cache_ttl, response.get_data(), response.mimetype)
            response.headers["X-Cache"] = "MISS"
        elif request.method not in ("GET", "HEAD", "OPTIONS"):
            _cache_flush(_viewer())

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response
