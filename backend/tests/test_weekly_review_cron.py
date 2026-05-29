"""Tests for the weekly review scheduler + internal cron endpoint."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services import weekly_review_scheduler as svc
from app.db.models import User as UserDB, WeeklyReview as WeeklyReviewDB


# ==========================================================
# target_week_for — most recent Mon-Sun fully elapsed
# ==========================================================

class TestTargetWeekFor:
    def test_monday_returns_prior_week(self):
        # Mon 2026-05-11 → Mon 2026-05-04 .. Sun 2026-05-10
        start, end = svc.target_week_for(date(2026, 5, 11))
        assert (start, end) == (date(2026, 5, 4), date(2026, 5, 10))

    def test_sunday_returns_two_weeks_back(self):
        # Sun 2026-05-10 → Sun's data still incomplete; we return the
        # previous full week.
        start, end = svc.target_week_for(date(2026, 5, 10))
        assert (start, end) == (date(2026, 4, 27), date(2026, 5, 3))

    def test_window_is_seven_days(self):
        for offset in range(0, 14):
            d = date(2026, 5, 1) + timedelta(days=offset)
            start, end = svc.target_week_for(d)
            assert (end - start).days == 6
            assert start.weekday() == 0  # Monday
            assert end.weekday() == 6    # Sunday


# ==========================================================
# run_weekly_reviews — eligibility + idempotency
# ==========================================================

@pytest.mark.asyncio
class TestRunWeeklyReviews:
    async def test_skips_canceled_users(self, db_session, seeded_user):
        seeded_user.subscription_status = "canceled"
        db_session.commit()

        with patch.object(svc.weekly_reviewer, "generate_weekly_review",
                          new_callable=AsyncMock) as gen:
            summary = await svc.run_weekly_reviews()
        assert gen.await_count == 0
        assert summary["considered"] == 0
        assert summary["generated"] == 0

    async def test_skips_expired_trials(self, db_session, seeded_user):
        seeded_user.subscription_status = "trialing"
        seeded_user.trial_expires_at = datetime.utcnow() - timedelta(days=1)
        db_session.commit()

        with patch.object(svc.weekly_reviewer, "generate_weekly_review",
                          new_callable=AsyncMock) as gen:
            summary = await svc.run_weekly_reviews()
        assert gen.await_count == 0
        assert summary["considered"] == 0

    async def test_processes_active_user(self, db_session, seeded_user):
        seeded_user.subscription_status = "active"
        db_session.commit()

        with patch.object(svc.weekly_reviewer, "generate_weekly_review",
                          new_callable=AsyncMock) as gen:
            summary = await svc.run_weekly_reviews()
        assert gen.await_count == 1
        assert summary["generated"] == 1

    async def test_processes_trialing_not_expired(self, db_session, seeded_user):
        seeded_user.subscription_status = "trialing"
        seeded_user.trial_expires_at = datetime.utcnow() + timedelta(days=5)
        db_session.commit()

        with patch.object(svc.weekly_reviewer, "generate_weekly_review",
                          new_callable=AsyncMock) as gen:
            summary = await svc.run_weekly_reviews()
        assert gen.await_count == 1

    async def test_skips_existing_review(self, db_session, seeded_user):
        seeded_user.subscription_status = "active"
        # Pre-seed a review for the target week.
        from uuid import uuid4
        start, end = svc.target_week_for(date.today())
        db_session.add(WeeklyReviewDB(
            id=uuid4(),
            user_id=seeded_user.id,
            week_number=1,
            week_start_date=start,
            week_end_date=end,
            summary="prev",
            ai_model_used="test",
            recovery_status="adequate",
            volume_assessment="appropriate",
            coach_message="—",
        ))
        db_session.commit()

        with patch.object(svc.weekly_reviewer, "generate_weekly_review",
                          new_callable=AsyncMock) as gen:
            summary = await svc.run_weekly_reviews()
        assert gen.await_count == 0
        assert summary["skipped_existing"] == 1
        assert summary["generated"] == 0

    async def test_one_user_failure_does_not_break_batch(self, db_session, seeded_user):
        # Two active users; first one's review generation throws.
        seeded_user.subscription_status = "active"
        from app.db.models import User as UserDB_local
        u2 = UserDB_local(
            id=2, email="b@x.com", password_hash="x", name="Two",
            fitness_level="beginner", subscription_status="active",
        )
        db_session.add(u2)
        db_session.commit()

        async def flaky(user_id, **kw):
            if user_id == seeded_user.id:
                raise RuntimeError("boom")
            return None
        with patch.object(svc.weekly_reviewer, "generate_weekly_review", side_effect=flaky):
            summary = await svc.run_weekly_reviews()
        assert summary["considered"] == 2
        assert summary["failed"] == 1
        assert summary["generated"] == 1


# ==========================================================
# Internal cron endpoint
# ==========================================================

@pytest.mark.asyncio
class TestInternalCronEndpoint:
    async def test_missing_secret_returns_401(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.INTERNAL_CRON_SECRET", "expected-secret-value-32-chars-min!!")
        r = await async_client.post("/api/v1/internal/cron/weekly-reviews")
        assert r.status_code == 401

    async def test_wrong_secret_returns_401(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.INTERNAL_CRON_SECRET", "expected-secret-value")
        r = await async_client.post(
            "/api/v1/internal/cron/weekly-reviews",
            headers={"X-Internal-Cron-Secret": "wrong"},
        )
        assert r.status_code == 401

    async def test_unconfigured_server_returns_503(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.INTERNAL_CRON_SECRET", "")
        r = await async_client.post(
            "/api/v1/internal/cron/weekly-reviews",
            headers={"X-Internal-Cron-Secret": "anything"},
        )
        assert r.status_code == 503

    async def test_correct_secret_runs(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.INTERNAL_CRON_SECRET",
            "expected-secret-value",
        )
        with patch("app.api.v1.internal_cron.run_weekly_reviews",
                   new_callable=AsyncMock,
                   return_value={"generated": 0, "considered": 0}) as runner:
            r = await async_client.post(
                "/api/v1/internal/cron/weekly-reviews",
                headers={"X-Internal-Cron-Secret": "expected-secret-value"},
            )
        assert r.status_code == 200, r.text
        assert runner.await_count == 1
