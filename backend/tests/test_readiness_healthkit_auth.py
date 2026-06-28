"""Tests for shared readiness module and HealthKit sync."""
import pytest
from datetime import date
from unittest.mock import patch, AsyncMock, MagicMock

from app.core.engine.readiness import (
    calculate_readiness_score,
    normalize_sleep_quality,
    compute_and_persist_readiness,
)
from app.db.models import RecoveryMetric as RecoveryMetricDB


class TestReadinessModule:
    def test_normalize_sleep_quality_100_scale(self):
        assert normalize_sleep_quality(85) == 8
        assert normalize_sleep_quality(7) == 7

    def test_calculate_readiness_optimal(self):
        score = calculate_readiness_score({
            "hrv_ratio": 1.2,
            "sleep_quality": 9,
            "stress_level": 2,
            "muscle_soreness": 2,
        })
        assert score >= 80

    def test_compute_and_persist_readiness(self, db_session, seeded_user):
        row = RecoveryMetricDB(
            user_id=seeded_user.id,
            date=date.today(),
            hrv_ms=55,
            sleep_quality=8,
            stress_level=3,
            muscle_soreness=3,
        )
        db_session.add(row)
        db_session.commit()
        score = compute_and_persist_readiness(db_session, seeded_user.id, row)
        assert 0 <= score <= 100
        assert row.readiness_score == score


class TestHealthkitSync:
    @pytest.mark.asyncio
    async def test_sync_persists_sleep_quality(self, db_session, seeded_user):
        from app.core.integrations.healthkit import sync_healthkit_data

        with patch("app.core.integrations.healthkit.SessionLocal") as mock_local:
            mock_local.return_value.__enter__ = lambda s: db_session
            mock_local.return_value.__exit__ = lambda *a: False
            result = await sync_healthkit_data(seeded_user.id, {
                "hrv_rmssd_ms": 60,
                "sleep_duration_hours": 7.5,
                "sleep_quality_score": 80,
                "start_date": date.today().isoformat(),
            })

        assert result["recovery_metric_updated"] is True
        db_session.expire_all()
        from sqlalchemy import select
        row = db_session.execute(
            select(RecoveryMetricDB).where(
                RecoveryMetricDB.user_id == seeded_user.id,
                RecoveryMetricDB.date == date.today(),
            )
        ).scalar_one()
        assert row.hrv_ms == 60
        assert row.sleep_quality == 8
        assert row.readiness_score is not None


class TestPasswordReset:
    @pytest.mark.asyncio
    async def test_forgot_password_always_success(self, async_client):
        with patch("app.api.v1.auth.get_user_by_email", return_value=None):
            resp = await async_client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "nobody@example.com"},
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_invalid_token(self, async_client):
        resp = await async_client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "invalid",
                "password": "NewPass123",
                "confirm_password": "NewPass123",
            },
        )
        assert resp.status_code == 400
