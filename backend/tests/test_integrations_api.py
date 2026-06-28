"""
Tests for Integrations API endpoints
Tests HealthKit sync, Google Calendar OAuth and sync
"""
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4


class TestHealthKitSync:
    """Test HealthKit sync endpoint"""

    @pytest.mark.asyncio
    async def test_sync_healthkit_success(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """Successful HealthKit sync with a fully-typed payload."""
        data = {
            "type": "recovery",
            "device": "Apple Watch",
            "start_date": "2026-03-30T07:00:00Z",
            "end_date": "2026-03-30T08:00:00Z",
            "hrv_rmssd_ms": 65,
            "resting_heart_rate_bpm": 52,
            "sleep_duration_hours": 7.5,
            "sleep_quality_score": 80,
        }

        with patch(
            "app.api.v1.integrations.sync_healthkit_data",
            new_callable=AsyncMock,
            return_value={
                "count": 5,
                "recovery_metric_updated": True,
                "metric_date": "2026-03-30",
                "readiness_score": 72,
            },
        ):
            response = await authenticated_client.post(
                "/api/v1/integrations/healthkit/sync", json=data
            )

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
        assert result["records_synced"] == 5
        assert result["recovery_metric_updated"] is True
        assert result["readiness_score"] == 72

    @pytest.mark.asyncio
    async def test_sync_healthkit_empty_data(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """Empty payload is valid (all fields are optional)."""
        with patch(
            "app.api.v1.integrations.sync_healthkit_data",
            new_callable=AsyncMock,
            return_value={"count": 0},
        ):
            response = await authenticated_client.post(
                "/api/v1/integrations/healthkit/sync", json={}
            )

        assert response.status_code == 200
        result = response.json()
        assert result["records_synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_healthkit_missing_count_in_result(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """Payload with one valid field; helper returns no count."""
        with patch(
            "app.api.v1.integrations.sync_healthkit_data",
            new_callable=AsyncMock,
            return_value={},
        ):
            response = await authenticated_client.post(
                "/api/v1/integrations/healthkit/sync",
                json={"hrv_rmssd_ms": 50},
            )

        assert response.status_code == 200
        # Should default to 0
        assert response.json()["records_synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_healthkit_rejects_unknown_field(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """extra='forbid' blocks attempts to smuggle arbitrary JSON."""
        response = await authenticated_client.post(
            "/api/v1/integrations/healthkit/sync",
            json={"hrv_rmssd_ms": 50, "evil_blob": "x" * 1000},
        )
        assert response.status_code == 422
        body = response.json()
        # Pydantic surfaces the offending field name in the error.
        assert any("evil_blob" in str(e) for e in body.get("detail", []))

    @pytest.mark.asyncio
    async def test_sync_healthkit_rejects_out_of_range_hrv(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """HRV outside 5–400 ms is rejected (likely a parse error or junk)."""
        response = await authenticated_client.post(
            "/api/v1/integrations/healthkit/sync",
            json={"hrv_rmssd_ms": 99999},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_sync_healthkit_rejects_negative_sleep(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        response = await authenticated_client.post(
            "/api/v1/integrations/healthkit/sync",
            json={"sleep_duration_hours": -1.0},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_sync_healthkit_rejects_giant_string(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """`device` has max_length=64 — long strings rejected."""
        response = await authenticated_client.post(
            "/api/v1/integrations/healthkit/sync",
            json={"device": "X" * 1000},
        )
        assert response.status_code == 422


class TestHealthkitStatus:
  @pytest.mark.asyncio
  async def test_healthkit_status_no_sync(
      self, authenticated_client: AsyncClient
  ):
      response = await authenticated_client.get("/api/v1/integrations/healthkit/status")
      assert response.status_code == 200
      data = response.json()
      assert data["last_sync_at"] is None
      assert data["recovery_source"] == "none"
      assert data["connected"] is False
      assert data["stale"] is False
      assert "sync_url" in data
      assert data["sync_url"].endswith("/api/v1/integrations/healthkit/sync")


class TestCalendarOAuthUrl:
    """Test GET /calendar/oauth/url"""

    @pytest.mark.asyncio
    async def test_get_oauth_url_returns_auth_url(
        self, authenticated_client: AsyncClient, mock_supabase, mock_user
    ):
        """Test OAuth URL endpoint returns a URL"""
        response = await authenticated_client.get("/api/v1/integrations/calendar/oauth/url")

        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert isinstance(data["auth_url"], str)
        assert "accounts.google.com" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_get_oauth_url_state_is_random_not_user_id(
        self, authenticated_client: AsyncClient, mock_supabase, mock_user
    ):
        """OAuth URL must use a random nonce as state, not the bare user id.

        Old vuln: ``state=user_id`` let an attacker callback with the
        victim's id. State is now a single-use, server-side nonce.
        """
        response = await authenticated_client.get("/api/v1/integrations/calendar/oauth/url")

        assert response.status_code == 200
        url = response.json()["auth_url"]
        assert "state=" in url
        # The bare user id MUST NOT appear as the state value.
        assert f"state={mock_user['id']}&" not in url + "&"
        assert not url.endswith(f"state={mock_user['id']}")


class TestCalendarOAuthCallback:
    """Test GET /calendar/oauth/callback"""

    @pytest.mark.asyncio
    async def test_callback_with_error_redirects(self, async_client: AsyncClient):
        """Test OAuth error redirects to profile error page"""
        response = await async_client.get(
            "/api/v1/integrations/calendar/oauth/callback?error=access_denied",
            follow_redirects=False,
        )
        assert response.status_code in [302, 307]
        assert "calendar=error" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_callback_missing_code_returns_400(self, async_client: AsyncClient):
        """Test callback without code returns 400"""
        response = await async_client.get(
            "/api/v1/integrations/calendar/oauth/callback?state=user123",
        )
        assert response.status_code == 400
        assert "Missing" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_callback_missing_state_returns_400(self, async_client: AsyncClient):
        """Test callback without state returns 400"""
        response = await async_client.get(
            "/api/v1/integrations/calendar/oauth/callback?code=auth_code_abc",
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_success_stores_refresh_token(
        self, async_client: AsyncClient, db_session, seeded_user
    ):
        """Test successful callback stores refresh token in user preferences."""
        from app.core.oauth_state import issue_state
        tokens = {"access_token": "at_abc", "refresh_token": "rt_xyz"}
        state = issue_state(seeded_user.id)

        with patch(
            "app.api.v1.integrations.exchange_code",
            new_callable=AsyncMock,
            return_value=tokens,
        ):
            response = await async_client.get(
                f"/api/v1/integrations/calendar/oauth/callback?code=auth_code&state={state}",
                follow_redirects=False,
            )

        assert response.status_code in [302, 307]
        assert "calendar=connected" in response.headers.get("location", "")

        db_session.refresh(seeded_user)
        assert (seeded_user.preferences or {}).get("google_calendar_refresh_token") == "rt_xyz"

    @pytest.mark.asyncio
    async def test_callback_no_refresh_token_still_redirects(
        self, async_client: AsyncClient, mock_supabase, seeded_user
    ):
        """Test callback when response has no refresh_token still succeeds"""
        from app.core.oauth_state import issue_state
        tokens = {"access_token": "at_abc"}  # No refresh_token
        state = issue_state(seeded_user.id)

        with patch(
            "app.api.v1.integrations.exchange_code",
            new_callable=AsyncMock,
            return_value=tokens,
        ):
            response = await async_client.get(
                f"/api/v1/integrations/calendar/oauth/callback?code=auth_code&state={state}",
                follow_redirects=False,
            )

        assert response.status_code in [302, 307]
        assert "calendar=connected" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_callback_exchange_failure_redirects_error(
        self, async_client: AsyncClient, mock_supabase, seeded_user
    ):
        """Test callback handles exchange failure gracefully"""
        from app.core.oauth_state import issue_state
        state = issue_state(seeded_user.id)

        with patch(
            "app.api.v1.integrations.exchange_code",
            new_callable=AsyncMock,
            side_effect=Exception("Token exchange failed"),
        ):
            response = await async_client.get(
                f"/api/v1/integrations/calendar/oauth/callback?code=bad_code&state={state}",
                follow_redirects=False,
            )

        assert response.status_code in [302, 307]
        assert "calendar=error" in response.headers.get("location", "")


class TestCalendarSync:
    """Test POST /calendar/sync"""

    @pytest.mark.asyncio
    async def test_sync_not_connected_returns_400(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """Test sync when calendar not connected returns 400"""
        with patch(
            "app.api.v1.integrations.sync_calendar_events",
            new_callable=AsyncMock,
            return_value={"status": "not_connected", "created": 0, "message": "Google Calendar not connected"},
        ):
            response = await authenticated_client.post("/api/v1/integrations/calendar/sync")

        assert response.status_code == 400
        assert "not connected" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_sync_success_returns_event_count(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """Test successful calendar sync returns event count"""
        with patch(
            "app.api.v1.integrations.sync_calendar_events",
            new_callable=AsyncMock,
            return_value={"status": "success", "created": 5},
        ):
            response = await authenticated_client.post("/api/v1/integrations/calendar/sync")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["events_created"] == 5

    @pytest.mark.asyncio
    async def test_sync_zero_events_created(
        self, authenticated_client: AsyncClient, mock_supabase
    ):
        """Test sync with zero events (all rest days) returns success"""
        with patch(
            "app.api.v1.integrations.sync_calendar_events",
            new_callable=AsyncMock,
            return_value={"status": "success", "created": 0},
        ):
            response = await authenticated_client.post("/api/v1/integrations/calendar/sync")

        assert response.status_code == 200
        data = response.json()
        assert data["events_created"] == 0


class TestCalendarDisconnect:
    """Test DELETE /calendar/disconnect"""

    @pytest.mark.asyncio
    async def test_disconnect_returns_success(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test calendar disconnect clears refresh token."""
        seeded_user.preferences = {
            **(seeded_user.preferences or {}),
            "google_calendar_refresh_token": "rt_existing",
        }
        db_session.add(seeded_user)
        db_session.commit()

        response = await authenticated_client.delete("/api/v1/integrations/calendar/disconnect")
        assert response.status_code == 200
        assert "disconnected" in response.json()["message"].lower()

        db_session.refresh(seeded_user)
        assert "google_calendar_refresh_token" not in (seeded_user.preferences or {})
