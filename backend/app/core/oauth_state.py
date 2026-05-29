"""Single-use, expiring nonce store for OAuth ``state`` parameters.

Why this exists: passing ``state=user_id`` (the prior implementation)
let an attacker run the OAuth dance with someone else's user_id and
write *their own* refresh token into the victim's row. A random,
server-side nonce bound to the issuing user prevents that.

API:
    state = issue_state(user_id)        # call before redirect to Google
    user_id = consume_state(state)      # call in callback; returns None
                                        # if unknown / expired / already used

Storage:
    - Redis when REDIS_URL is set (multi-worker safe).
    - In-memory dict with manual TTL sweep as fallback (dev/tests).
"""
from __future__ import annotations

import logging
import os
import secrets
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 600  # 10 minutes — generous for slow-clicking users
KEY_PREFIX = "oauth_state:"


# ----- Backend selection ---------------------------------------------------

class _MemoryBackend:
    """Process-local store. Fine for dev / single-worker tests; not for prod."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[int, float]] = {}  # token → (user_id, expires_at)

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            stale = [k for k, (_, exp) in self._store.items() if exp <= now]
            for k in stale:
                self._store.pop(k, None)

    def set(self, token: str, user_id: int, ttl: int) -> None:
        self._sweep()
        with self._lock:
            self._store[token] = (user_id, time.time() + ttl)

    def pop(self, token: str) -> Optional[int]:
        self._sweep()
        with self._lock:
            entry = self._store.pop(token, None)
        if not entry:
            return None
        user_id, expires_at = entry
        if expires_at <= time.time():
            return None
        return user_id


class _RedisBackend:
    def __init__(self, url: str) -> None:
        # Imported lazily so the import doesn't fail in test env without redis.
        import redis
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def set(self, token: str, user_id: int, ttl: int) -> None:
        self._client.setex(KEY_PREFIX + token, ttl, str(user_id))

    def pop(self, token: str) -> Optional[int]:
        # Atomic: GET + DEL via pipeline keeps single-use guarantee even
        # under concurrent callbacks.
        key = KEY_PREFIX + token
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw, _ = pipe.execute()
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None


def _make_backend():
    url = os.getenv("REDIS_URL")
    if url:
        try:
            backend = _RedisBackend(url)
            # Sanity check the connection so we fall back instead of failing
            # on the first issue_state call.
            backend._client.ping()
            logger.info("OAuth state store using Redis backend")
            return backend
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "OAuth state store falling back to memory: Redis ping failed (%s)", e
            )
    return _MemoryBackend()


_backend = _make_backend()


# ----- Public API ----------------------------------------------------------

def issue_state(user_id: int, ttl: int = DEFAULT_TTL_SECONDS) -> str:
    """Generate a fresh random nonce bound to ``user_id`` and persist it."""
    token = secrets.token_urlsafe(32)
    _backend.set(token, int(user_id), ttl)
    return token


def consume_state(token: str) -> Optional[int]:
    """Return the bound user_id and atomically invalidate the nonce.

    Returns None for unknown, expired, or already-consumed nonces.
    """
    if not token:
        return None
    return _backend.pop(token)
