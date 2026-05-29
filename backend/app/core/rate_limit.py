"""Rate limiting via slowapi.

One shared ``limiter`` instance is registered on the FastAPI app at
startup; endpoints opt in by decorating with ``@limiter.limit("5/minute")``.

Storage backend:
- Redis (``REDIS_URL`` env) — preferred for multi-worker prod, since the
  in-memory backend resets per process and lets each worker grant its own
  quota.
- In-memory — used in dev and tests when no Redis is configured.

Key strategy:
- Auth endpoints (login/register) → keyed by client IP, since the user
  isn't authenticated yet.
- Authenticated endpoints → keyed by user id when available, falling back
  to IP. This stops one user from exhausting another's quota by sharing
  an outbound IP.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    """Resolve client IP, honoring X-Forwarded-For when behind a proxy.

    Most prod deploys (Coolify, nginx, cloud LBs) terminate TLS upstream
    and set X-Forwarded-For. Without this, every request appears to come
    from the proxy IP and rate limits collapse to a single bucket.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # First entry = original client. Strip the rest (proxy chain).
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


def _user_or_ip_key(request: Request) -> str:
    """Prefer the authenticated user id; fall back to client IP.

    The dependency injector hasn't run by the time slowapi inspects the
    request, so we peek at the Authorization header and decode the JWT
    cheaply. Failures (no header / bad token) fall back to IP.
    """
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1]
        try:
            from jose import jwt
            from app.core.config import settings
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001 — degrade to IP on any decode failure
            pass
    return f"ip:{_client_ip(request)}"


def _resolve_storage_uri() -> Optional[str]:
    """Use Redis if REDIS_URL is set; else None → in-memory backend."""
    url = os.getenv("REDIS_URL")
    if url:
        # slowapi/limits expect e.g. ``redis://host:port/db``. The repo's
        # default ``redis://redis:6379/0`` already matches.
        return url
    return None


storage_uri = _resolve_storage_uri()
if storage_uri:
    logger.info("Rate limiter using Redis backend")
    limiter = Limiter(key_func=_user_or_ip_key, storage_uri=storage_uri)
else:
    logger.info("Rate limiter using in-memory backend (no REDIS_URL set)")
    limiter = Limiter(key_func=_user_or_ip_key)


# Per-IP key for unauthenticated endpoints (login/register/forgot-password).
# Used directly via @limiter.limit("...", key_func=ip_key).
def ip_key(request: Request) -> str:
    return f"ip:{_client_ip(request)}"
