"""Tests for oauth_state nonce store + calendar OAuth state validation."""
from __future__ import annotations

import time
from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient

from app.core import oauth_state
from app.core.oauth_state import _MemoryBackend, consume_state, issue_state


@pytest.fixture(autouse=True)
def _fresh_memory_backend(monkeypatch):
    """Each test gets a fresh in-memory store so nonces don't leak."""
    backend = _MemoryBackend()
    monkeypatch.setattr(oauth_state, "_backend", backend)
    yield backend


# ==========================================================
# Unit — issue/consume primitive
# ==========================================================

class TestIssueAndConsume:
    def test_round_trip(self):
        token = issue_state(user_id=42)
        assert isinstance(token, str)
        assert len(token) > 20  # secrets.token_urlsafe(32) → ~43 chars
        assert consume_state(token) == 42

    def test_consume_is_single_use(self):
        token = issue_state(user_id=42)
        assert consume_state(token) == 42
        # Replay → None
        assert consume_state(token) is None

    def test_unknown_token_returns_none(self):
        assert consume_state("never-issued") is None

    def test_empty_token_returns_none(self):
        assert consume_state("") is None
        assert consume_state(None) is None  # type: ignore[arg-type]

    def test_each_call_returns_different_token(self):
        a = issue_state(user_id=1)
        b = issue_state(user_id=1)
        assert a != b

    def test_expired_token_returns_none(self, _fresh_memory_backend):
        token = issue_state(user_id=42, ttl=1)
        # Manually rewind the stored expiry to the past — simpler than sleep.
        _fresh_memory_backend._store[token] = (42, time.time() - 1)
        assert consume_state(token) is None


# ==========================================================
# Endpoint — /calendar/oauth/url issues a fresh random state
# ==========================================================

@pytest.mark.asyncio
class TestCalendarOAuthUrl:
    async def test_state_is_random_not_user_id(
        self, authenticated_client: AsyncClient, mock_user
    ):
        """The state in the auth URL must NOT be the bare user id."""
        with patch(
            "app.api.v1.integrations.get_oauth_url",
            return_value="https://accounts.google.com/auth?state=PLACEHOLDER",
        ) as mock_get_url:
            r = await authenticated_client.get("/api/v1/integrations/calendar/oauth/url")

        assert r.status_code == 200
        # Pull the state passed to get_oauth_url.
        kwargs = mock_get_url.call_args.kwargs
        state = kwargs.get("state")
        assert state, "state must be provided to get_oauth_url"
        assert state != str(mock_user["id"]), "state must not equal user id"
        # The issued state must round-trip back to the user id.
        assert consume_state(state) == mock_user["id"]


# ==========================================================
# Endpoint — /calendar/oauth/callback rejects bad/expired state
# ==========================================================

@pytest.mark.asyncio
class TestCalendarOAuthCallback:
    async def test_unknown_state_returns_400(self, async_client: AsyncClient):
        r = await async_client.get(
            "/api/v1/integrations/calendar/oauth/callback",
            params={"code": "abc", "state": "never-issued"},
        )
        assert r.status_code == 400

    async def test_replayed_state_returns_400(self, async_client: AsyncClient, seeded_user):
        token = issue_state(user_id=seeded_user.id)

        # First callback succeeds (mock token exchange).
        with patch(
            "app.api.v1.integrations.exchange_code",
            new=AsyncMock(return_value={"refresh_token": "rt-1"}),
        ):
            r1 = await async_client.get(
                "/api/v1/integrations/calendar/oauth/callback",
                params={"code": "abc", "state": token},
                follow_redirects=False,
            )
        assert r1.status_code in (302, 307), r1.text

        # Replay with the same state → 400 (single-use enforced).
        r2 = await async_client.get(
            "/api/v1/integrations/calendar/oauth/callback",
            params={"code": "abc", "state": token},
        )
        assert r2.status_code == 400

    async def test_attacker_cannot_use_victim_user_id(self, async_client: AsyncClient, seeded_user):
        """Old vuln: ``state=<victim_id>`` would write attacker's token into
        the victim's row. With random nonces, even guessing the user id
        gets you nowhere — the bare id isn't a valid state."""
        r = await async_client.get(
            "/api/v1/integrations/calendar/oauth/callback",
            params={"code": "abc", "state": str(seeded_user.id)},
        )
        assert r.status_code == 400

    async def test_happy_path_writes_refresh_token(self, async_client: AsyncClient, seeded_user, db_session):
        from app.db.models import User as UserDB
        token = issue_state(user_id=seeded_user.id)

        with patch(
            "app.api.v1.integrations.exchange_code",
            new=AsyncMock(return_value={"refresh_token": "rt-from-google"}),
        ):
            r = await async_client.get(
                "/api/v1/integrations/calendar/oauth/callback",
                params={"code": "abc", "state": token},
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        # The refresh token is now in the user's preferences.
        db_session.expire_all()
        user = db_session.get(UserDB, seeded_user.id)
        assert user.preferences.get("google_calendar_refresh_token") == "rt-from-google"
