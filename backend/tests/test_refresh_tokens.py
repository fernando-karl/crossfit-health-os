"""Tests for refresh token rotation, reuse detection, and logout revocation."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import refresh_tokens as rt
from app.db.models import RefreshToken, User as UserDB


# ==========================================================
# Unit — issue_pair / rotate / revoke
# ==========================================================

class TestIssuePair:
    def test_returns_two_distinct_strings(self, db_session, seeded_user):
        access, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        assert access and refresh and access != refresh

    def test_persists_only_hash_not_raw(self, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        rows = db_session.execute(select(RefreshToken)).scalars().all()
        assert len(rows) == 1
        assert rows[0].token_hash != refresh
        assert len(rows[0].token_hash) == 64  # sha256 hex


class TestRotate:
    def test_happy_path(self, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        result = rt.rotate(db_session, refresh)
        assert result is not None
        new_access, new_refresh, user_id = result
        assert new_refresh != refresh
        assert user_id == seeded_user.id

    def test_old_token_revoked_after_rotation(self, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        rt.rotate(db_session, refresh)
        rows = db_session.execute(select(RefreshToken)).scalars().all()
        assert len(rows) == 2
        # First row was revoked + linked to second
        old = next(r for r in rows if r.replaced_by_id is not None)
        assert old.revoked_at is not None
        assert old.replaced_by_id is not None

    def test_replay_revokes_entire_family(self, db_session, seeded_user):
        """Reuse detection: replaying a rotated token is treated as theft."""
        _, refresh1 = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        result = rt.rotate(db_session, refresh1)
        assert result is not None
        _, refresh2, _ = result

        # Attacker replays the OLD refresh token. Replay is rejected AND
        # the new live token is revoked.
        replay = rt.rotate(db_session, refresh1)
        assert replay is None

        # The legitimate (newly issued) refresh is now also revoked.
        retry = rt.rotate(db_session, refresh2)
        assert retry is None

    def test_unknown_token_returns_none(self, db_session):
        assert rt.rotate(db_session, "never-issued-anywhere") is None

    def test_empty_token_returns_none(self, db_session):
        assert rt.rotate(db_session, "") is None

    def test_expired_token_returns_none(self, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        # Force-expire the row.
        row = db_session.execute(select(RefreshToken)).scalar_one()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()
        assert rt.rotate(db_session, refresh) is None


class TestRevoke:
    def test_logout_revokes(self, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        assert rt.revoke(db_session, refresh) is True
        # Subsequent rotate fails.
        assert rt.rotate(db_session, refresh) is None

    def test_double_revoke_returns_false(self, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        assert rt.revoke(db_session, refresh) is True
        assert rt.revoke(db_session, refresh) is False


# ==========================================================
# Endpoints
# ==========================================================

@pytest.mark.asyncio
class TestLoginIssuesPair:
    async def test_login_returns_both_tokens(
        self, async_client: AsyncClient, db_session, seeded_user
    ):
        # Seed a known password hash so the login flow accepts the request.
        from app.api.v1.auth import hash_password
        seeded_user.password_hash = hash_password("Secret123A")
        db_session.commit()

        # Patch the raw-SQL helper used by the legacy auth path.
        row = (
            seeded_user.id, seeded_user.email, seeded_user.password_hash,
            seeded_user.name, seeded_user.birth_date, seeded_user.weight_kg,
            seeded_user.height_cm, seeded_user.fitness_level, seeded_user.goals,
        )
        with patch("app.api.v1.auth.get_user_by_email", return_value=row):
            r = await async_client.post(
                "/api/v1/auth/login",
                json={"email": seeded_user.email, "password": "Secret123A"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["access_token"] != body["refresh_token"]


@pytest.mark.asyncio
class TestRefreshEndpoint:
    async def test_rotates_pair(self, async_client: AsyncClient, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        r = await async_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"]
        assert body["refresh_token"] != refresh

    async def test_unknown_returns_401(self, async_client: AsyncClient):
        r = await async_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "garbage"}
        )
        assert r.status_code == 401

    async def test_replay_returns_401(self, async_client: AsyncClient, db_session, seeded_user):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        # First rotation succeeds.
        r1 = await async_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        )
        assert r1.status_code == 200
        # Second use of the same (now rotated) token is rejected.
        r2 = await async_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        )
        assert r2.status_code == 401


@pytest.mark.asyncio
class TestLogoutRevokesRefresh:
    async def test_logout_with_refresh_token_revokes_it(
        self, async_client: AsyncClient, db_session, seeded_user
    ):
        _, refresh = rt.issue_pair(db_session, seeded_user.id, seeded_user.email)
        r = await async_client.post(
            "/api/v1/auth/logout", json={"refresh_token": refresh}
        )
        assert r.status_code == 200
        # That refresh can no longer be rotated.
        rotated = await async_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        )
        assert rotated.status_code == 401

    async def test_logout_without_payload_still_works(self, async_client: AsyncClient):
        # Backwards-compat: callers without a refresh token still get 200.
        r = await async_client.post("/api/v1/auth/logout")
        assert r.status_code == 200
