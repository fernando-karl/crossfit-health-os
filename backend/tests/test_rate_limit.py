"""Tests for slowapi rate limiting on auth + AI endpoints.

slowapi tracks state on the Limiter instance. To prevent leaking quota
between tests we reset the limiter between cases.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Clear slowapi's in-memory storage before each test."""
    from app.core.rate_limit import limiter
    # slowapi/limits MemoryStorage exposes .reset()
    storage = getattr(limiter, "_storage", None) or getattr(limiter, "limiter", None)
    try:
        if hasattr(storage, "reset"):
            storage.reset()
        elif hasattr(limiter, "reset"):
            limiter.reset()
    except Exception:
        pass
    yield


@pytest.mark.asyncio
class TestLoginRateLimit:
    async def test_blocks_after_5_attempts_per_minute(self, async_client: AsyncClient):
        """6th login attempt within a minute → 429."""
        # Use unique IP per test by setting X-Forwarded-For (slowapi honors it).
        headers = {"X-Forwarded-For": "203.0.113.10"}
        payload = {"email": "nobody@example.com", "password": "WrongPass1"}

        # First 5 attempts: 401 (invalid creds), but accepted by limiter.
        for i in range(5):
            r = await async_client.post(
                "/api/v1/auth/login", json=payload, headers=headers
            )
            assert r.status_code in (401, 400), (
                f"attempt {i+1} unexpected: {r.status_code}"
            )

        # 6th attempt: 429 from slowapi.
        r = await async_client.post(
            "/api/v1/auth/login", json=payload, headers=headers
        )
        assert r.status_code == 429


@pytest.mark.asyncio
class TestRegisterRateLimit:
    async def test_blocks_after_3_attempts_per_hour(self, async_client: AsyncClient):
        """4th register attempt within an hour → 429.

        Use a payload that passes pydantic validation (so the limiter sees
        the request) but fails consent (cheap path; no DB).
        """
        headers = {"X-Forwarded-For": "203.0.113.20"}
        payload = {
            "email": "x@example.com",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "name": "Athlete",
            "accepted_terms": False,
            "accepted_health_data": False,
        }
        for i in range(3):
            r = await async_client.post(
                "/api/v1/auth/register", json=payload, headers=headers
            )
            assert r.status_code == 400, f"attempt {i+1}: {r.status_code} {r.text}"

        r = await async_client.post(
            "/api/v1/auth/register", json=payload, headers=headers
        )
        assert r.status_code == 429


@pytest.mark.asyncio
class TestRateLimitIsolatedByKey:
    """Limit buckets are per-key, so a different IP starts at zero."""

    async def test_different_ip_independent_quota(self, async_client: AsyncClient):
        # Burn through one IP's quota for /login.
        h1 = {"X-Forwarded-For": "203.0.113.30"}
        h2 = {"X-Forwarded-For": "203.0.113.31"}
        payload = {"email": "n@example.com", "password": "Pw12345A"}
        for _ in range(5):
            await async_client.post("/api/v1/auth/login", json=payload, headers=h1)

        # IP1 is exhausted.
        r1 = await async_client.post("/api/v1/auth/login", json=payload, headers=h1)
        assert r1.status_code == 429

        # IP2 still has its full quota.
        r2 = await async_client.post("/api/v1/auth/login", json=payload, headers=h2)
        assert r2.status_code in (401, 400), r2.text


class TestLimiterBackendSelection:
    """Limiter picks Redis when REDIS_URL is set, in-memory otherwise."""

    def test_in_memory_when_no_redis(self, monkeypatch):
        from app.core import rate_limit
        monkeypatch.delenv("REDIS_URL", raising=False)
        # Reload the module to re-read env
        import importlib
        importlib.reload(rate_limit)
        # No storage_uri attribute set → MemoryStorage
        assert rate_limit.storage_uri is None

    def test_picks_redis_when_url_set(self, monkeypatch):
        from app.core import rate_limit
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
        import importlib
        importlib.reload(rate_limit)
        assert rate_limit.storage_uri == "redis://localhost:6379/1"
        # Clean up: force memory backend for the rest of the suite.
        monkeypatch.delenv("REDIS_URL", raising=False)
        importlib.reload(rate_limit)
