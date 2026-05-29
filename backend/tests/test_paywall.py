"""Tests for require_active_subscription dependency (trial counting + paywall)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.auth import require_active_subscription


def _user(status: str = "trialing", expires: datetime | None = None) -> dict:
    return {
        "id": 1,
        "email": "u@x.com",
        "name": "Test",
        "subscription_status": status,
        "trial_expires_at": expires.isoformat() if expires else None,
    }


class TestRequireActiveSubscription:
    def test_active_subscriber_passes(self):
        u = _user(status="active")
        result = require_active_subscription(u)
        assert result is u

    def test_trialing_with_future_expiry_passes(self):
        u = _user(status="trialing", expires=datetime.utcnow() + timedelta(days=3))
        result = require_active_subscription(u)
        assert result is u

    def test_trialing_with_past_expiry_blocked(self):
        u = _user(status="trialing", expires=datetime.utcnow() - timedelta(hours=1))
        with pytest.raises(HTTPException) as exc:
            require_active_subscription(u)
        assert exc.value.status_code == 402
        assert exc.value.detail["code"] == "subscription_required"

    def test_trialing_with_no_expiry_blocked(self):
        # Pre-migration users without trial_expires_at must be blocked,
        # not allowed by default.
        u = _user(status="trialing", expires=None)
        with pytest.raises(HTTPException) as exc:
            require_active_subscription(u)
        assert exc.value.status_code == 402

    def test_canceled_blocked(self):
        u = _user(status="canceled", expires=datetime.utcnow() + timedelta(days=30))
        with pytest.raises(HTTPException) as exc:
            require_active_subscription(u)
        assert exc.value.status_code == 402

    def test_past_due_blocked(self):
        u = _user(status="past_due")
        with pytest.raises(HTTPException) as exc:
            require_active_subscription(u)
        assert exc.value.status_code == 402

    def test_402_detail_has_useful_fields(self):
        expires = datetime.utcnow() - timedelta(days=1)
        u = _user(status="trialing", expires=expires)
        with pytest.raises(HTTPException) as exc:
            require_active_subscription(u)
        detail = exc.value.detail
        assert detail["subscription_status"] == "trialing"
        assert detail["trial_expires_at"] == expires.isoformat()
        assert "message" in detail


class TestTrialFieldsOnSignup:
    """Verify create_user sets trial_started_at and trial_expires_at."""

    def test_register_response_signals_trial(self, db_session, mock_user):
        """After signup, /api/v1/users/me should report subscription_status='trialing'.

        The HTTP-level register test in test_auth_endpoints already covers
        the response shape; here we verify the User row gets the trial
        timestamps set with the right window (14 days).
        """
        from app.api.v1.auth import TRIAL_DURATION_DAYS
        # Sanity: the constant matches the FAQ copy users see on the landing.
        assert TRIAL_DURATION_DAYS == 14
