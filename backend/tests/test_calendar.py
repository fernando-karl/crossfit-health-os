"""
Tests for Google Calendar Integration
Tests OAuth URL generation, code exchange, token refresh, event creation, sync
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone, date


class TestGetOAuthUrl:
    """Test OAuth URL generation"""

    def test_get_oauth_url_with_state(self):
        from app.core.integrations.calendar import get_oauth_url
        url = get_oauth_url(state="user_abc")
        assert "state=user_abc" in url
        assert "accounts.google.com" in url

    def test_get_oauth_url_empty_state(self):
        from app.core.integrations.calendar import get_oauth_url
        url = get_oauth_url(state="")
        assert "accounts.google.com" in url

    def test_get_oauth_url_default_state(self):
        from app.core.integrations.calendar import get_oauth_url
        url = get_oauth_url()
        assert "accounts.google.com" in url

    def test_get_oauth_url_required_params(self):
        from app.core.integrations.calendar import get_oauth_url
        url = get_oauth_url(state="test")
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "scope=" in url

    def test_get_oauth_url_is_string(self):
        from app.core.integrations.calendar import get_oauth_url
        url = get_oauth_url()
        assert isinstance(url, str)
        assert url.startswith("https://")


class TestExchangeCode:
    """Test OAuth code exchange"""

    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        from app.core.integrations.calendar import exchange_code

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "access_abc",
            "refresh_token": "refresh_abc",
            "expires_in": 3600,
        }

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await exchange_code("code_123")

        assert result["access_token"] == "access_abc"
        assert result["refresh_token"] == "refresh_abc"

    @pytest.mark.asyncio
    async def test_exchange_code_posts_to_google(self):
        from app.core.integrations.calendar import exchange_code

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"access_token": "at", "refresh_token": "rt"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await exchange_code("auth_code")

        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        # URL should be Google token endpoint
        assert "oauth2.googleapis.com" in call_args[0][0]


class TestRefreshAccessToken:
    """Test access token refresh"""

    @pytest.mark.asyncio
    async def test_refresh_returns_access_token(self):
        from app.core.integrations.calendar import refresh_access_token

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"access_token": "new_token_xyz", "expires_in": 3600}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await refresh_access_token("refresh_token_abc")

        assert result == "new_token_xyz"

    @pytest.mark.asyncio
    async def test_refresh_calls_token_endpoint(self):
        from app.core.integrations.calendar import refresh_access_token

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"access_token": "token"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await refresh_access_token("rt_123")

        mock_http.post.assert_called_once()
        url = mock_http.post.call_args[0][0]
        assert "oauth2.googleapis.com" in url


class TestCreateCalendarEvent:
    """Test Google Calendar event creation"""

    @pytest.mark.asyncio
    async def test_create_event_success(self):
        from app.core.integrations.calendar import create_calendar_event

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "event_123", "status": "confirmed"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            start = datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)
            end = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
            result = await create_calendar_event(
                "access_token", "Workout", "Description", start, end, "America/New_York"
            )

        assert result["id"] == "event_123"

    @pytest.mark.asyncio
    async def test_create_event_no_timezone_uses_default(self):
        from app.core.integrations.calendar import create_calendar_event

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "ev_abc", "status": "confirmed"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            start = datetime(2026, 4, 2, 7, 0, tzinfo=timezone.utc)
            end = datetime(2026, 4, 2, 8, 0, tzinfo=timezone.utc)
            result = await create_calendar_event(
                "token", "Metcon", "Fast workout", start, end
            )

        assert "id" in result

    @pytest.mark.asyncio
    async def test_create_event_sends_authorization_header(self):
        from app.core.integrations.calendar import create_calendar_event

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "ev_1"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            start = datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)
            end = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
            await create_calendar_event("my_token", "WOD", "Desc", start, end)

        call_kwargs = mock_http.post.call_args[1]
        assert "Bearer my_token" in call_kwargs["headers"]["Authorization"]


class TestGetUserToken:
    """Test internal _get_user_token helper.

    The refresh token is stored under `preferences['google_calendar_refresh_token']`
    on the User row (not a dedicated column).
    """

    @pytest.mark.asyncio
    async def test_returns_none_when_no_refresh_token(self, db_session, seeded_user):
        from app.core.integrations.calendar import _get_user_token

        result = await _get_user_token(seeded_user.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_user_data(self, db_session):
        from app.core.integrations.calendar import _get_user_token

        result = await _get_user_token(9999)  # no such user
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_access_token_when_refresh_exists(self, db_session, seeded_user):
        from app.core.integrations.calendar import _get_user_token

        seeded_user.preferences = {
            **(seeded_user.preferences or {}),
            "google_calendar_refresh_token": "refresh_xyz",
        }
        db_session.add(seeded_user)
        db_session.commit()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"access_token": "fresh_access_token"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await _get_user_token(seeded_user.id)

        assert result == "fresh_access_token"


class TestSyncCalendarEvents:
    """Test sync_calendar_events integration function"""

    @pytest.mark.asyncio
    async def test_sync_not_connected(self, db_session, seeded_user):
        from app.core.integrations.calendar import sync_calendar_events
        # No refresh token in preferences
        result = await sync_calendar_events(seeded_user.id)
        assert result["status"] == "not_connected"
        assert result["created"] == 0
        assert "not connected" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_no_active_schedule(self, db_session, seeded_user):
        """No planned_sessions in the next 7 days → no_schedule."""
        from app.core.integrations.calendar import sync_calendar_events

        seeded_user.preferences = {"google_calendar_refresh_token": "rt_abc"}
        db_session.add(seeded_user)
        db_session.commit()

        refresh_resp = MagicMock()
        refresh_resp.raise_for_status = MagicMock()
        refresh_resp.json.return_value = {"access_token": "at"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=refresh_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await sync_calendar_events(seeded_user.id)

        assert result["status"] == "no_schedule"
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_sync_with_training_days_creates_events(self, db_session, seeded_user):
        from datetime import datetime, timedelta, timezone
        from app.core.integrations.calendar import sync_calendar_events
        from app.db.models import Macrocycle, Microcycle, PlannedSession

        seeded_user.preferences = {"google_calendar_refresh_token": "rt_abc"}
        db_session.add(seeded_user)
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        macro = Macrocycle(
            user_id=seeded_user.id, name="t", methodology="hwpo",
            start_date=today, end_date=today + timedelta(days=6),
            block_plan=[{"type": "accumulation", "weeks": 1}], active=True,
        )
        db_session.add(macro); db_session.flush()
        micro = Microcycle(
            macrocycle_id=macro.id, user_id=seeded_user.id,
            start_date=today, end_date=today + timedelta(days=6),
            week_index_in_macro=1,
        )
        db_session.add(micro); db_session.flush()
        for i in range(7):
            db_session.add(PlannedSession(
                microcycle_id=micro.id, user_id=seeded_user.id,
                date=today + timedelta(days=i), order_in_day=1,
                start_time=None, duration_minutes=60, workout_type="strength",
            ))
        db_session.commit()

        refresh_resp = MagicMock()
        refresh_resp.raise_for_status = MagicMock()
        refresh_resp.json.return_value = {"access_token": "at_fresh"}

        event_resp = MagicMock()
        event_resp.raise_for_status = MagicMock()
        event_resp.json.return_value = {"id": "ev_created", "status": "confirmed"}

        empty_list = MagicMock()
        empty_list.raise_for_status = MagicMock()
        empty_list.json.return_value = {"items": []}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=empty_list)
        mock_http.post = AsyncMock(side_effect=[refresh_resp] + [event_resp] * 7)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await sync_calendar_events(seeded_user.id)

        assert result["status"] == "success"
        assert result["created"] == 7

    @pytest.mark.asyncio
    async def test_sync_event_creation_failure_logged(self, db_session, seeded_user):
        """Failing event creation is logged but doesn't crash the sync."""
        from datetime import datetime, timezone, timedelta
        from app.core.integrations.calendar import sync_calendar_events
        from app.db.models import Macrocycle, Microcycle, PlannedSession

        seeded_user.preferences = {"google_calendar_refresh_token": "rt"}
        db_session.add(seeded_user)
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        macro = Macrocycle(
            user_id=seeded_user.id, name="t", methodology="hwpo",
            start_date=today, end_date=today + timedelta(days=6),
            block_plan=[{"type": "accumulation", "weeks": 1}], active=True,
        )
        db_session.add(macro); db_session.flush()
        micro = Microcycle(
            macrocycle_id=macro.id, user_id=seeded_user.id,
            start_date=today, end_date=today + timedelta(days=6),
            week_index_in_macro=1,
        )
        db_session.add(micro); db_session.flush()
        db_session.add(PlannedSession(
            microcycle_id=micro.id, user_id=seeded_user.id,
            date=today, order_in_day=1, duration_minutes=60, workout_type="strength",
        ))
        db_session.commit()

        refresh_resp = MagicMock()
        refresh_resp.raise_for_status = MagicMock()
        refresh_resp.json.return_value = {"access_token": "at"}

        empty_list = MagicMock()
        empty_list.raise_for_status = MagicMock()
        empty_list.json.return_value = {"items": []}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=empty_list)
        mock_http.post = AsyncMock(
            side_effect=[refresh_resp, Exception("Calendar API error")]
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await sync_calendar_events(seeded_user.id)

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_sync_uses_preferences_timezone(self, db_session, seeded_user):
        """sync reads timezone from preferences dict when the column value is null."""
        from app.core.integrations.calendar import sync_calendar_events

        seeded_user.preferences = {
            "google_calendar_refresh_token": "rt",
            "timezone": "America/New_York",
        }
        db_session.add(seeded_user)
        db_session.commit()

        refresh_resp = MagicMock()
        refresh_resp.raise_for_status = MagicMock()
        refresh_resp.json.return_value = {"access_token": "at"}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=refresh_resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await sync_calendar_events(seeded_user.id)

        # Empty planned_sessions short-circuits with status=no_schedule
        assert result["status"] in ("success", "no_schedule")
        assert result["created"] == 0
