"""Tests for the readiness overlay applied to ``/training/today``.

When the user has an active program, the planned-session template now
goes through ``AdaptiveTrainingEngine.adapt_template`` so volume reflects
how the athlete feels today — matching the landing promise.
"""
from __future__ import annotations

from datetime import date as _Date, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.datetime_utils import user_today
from app.db.models import (
    Macrocycle as MacrocycleDB,
    Microcycle as MicrocycleDB,
    PlannedSession as PlannedSessionDB,
    RecoveryMetric as RecoveryMetricDB,
    WorkoutSession as WorkoutSessionDB,
    WorkoutTemplate as WorkoutTemplateDB,
)


def _test_today():
    """Align seeded planned-session dates with /training/today (user timezone)."""
    return user_today({"timezone": "America/Sao_Paulo"})


def _seed_active_program(db_session, user_id: int, *, sets: int = 5, reps: int = 10):
    """Create macro → micro → planned_session → template chain for today."""
    today = _test_today()
    macro = MacrocycleDB(
        id=uuid4(), user_id=user_id, name="Test", methodology="hwpo",
        start_date=today, end_date=today, block_plan=[{"type": "build", "weeks": 1}],
        active=True,
    )
    db_session.add(macro)
    db_session.flush()

    micro = MicrocycleDB(
        id=uuid4(), user_id=user_id, macrocycle_id=macro.id,
        week_index_in_macro=0, start_date=today, end_date=today,
    )
    db_session.add(micro)
    db_session.flush()

    template = WorkoutTemplateDB(
        id=uuid4(), owner_user_id=user_id, name="Back Squat 5x10",
        methodology="hwpo", workout_type="strength",
        movements=[{
            "movement": "back_squat",
            "sets": sets,
            "reps": str(reps),
            "weight_kg": 100.0,
        }],
    )
    db_session.add(template)
    db_session.flush()

    db_session.add(PlannedSessionDB(
        id=uuid4(), user_id=user_id, microcycle_id=micro.id,
        date=today, order_in_day=0, status="generated",
        generated_template_id=template.id,
    ))
    db_session.commit()
    return template


def _seed_recovery(db_session, user_id: int, *, sleep_q=10, stress=1, soreness=1, hrv=80):
    """High readiness by default — caller can flip values for low-readiness path."""
    db_session.add(RecoveryMetricDB(
        id=uuid4(), user_id=user_id, date=_test_today(),
        sleep_duration_hours=8.0, sleep_quality=sleep_q,
        hrv_ms=hrv, resting_heart_rate_bpm=55,
        stress_level=stress, muscle_soreness=soreness, energy_level=10,
    ))
    db_session.commit()


@pytest.mark.asyncio
class TestTodayWorkoutOverlay:
    async def test_no_program_returns_null(self, authenticated_client: AsyncClient, db_session, seeded_user):
        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        assert r.json() == {"workout": None}

    async def test_active_program_returns_adapted_meta(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        _seed_active_program(db_session, seeded_user.id)
        _seed_recovery(db_session, seeded_user.id)  # high readiness

        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        body = r.json()
        assert body["workout"] is not None
        assert "adapted_meta" in body
        assert "volume_multiplier" in body["adapted_meta"]
        assert "readiness_score" in body["adapted_meta"]

    async def test_low_readiness_reduces_volume(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Sleep 1, soreness 10, stress 10 → readiness < 40 → multiplier 0.5×."""
        _seed_active_program(db_session, seeded_user.id, sets=10, reps=10)
        _seed_recovery(db_session, seeded_user.id, sleep_q=1, stress=10, soreness=10, hrv=20)

        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        body = r.json()
        meta = body["adapted_meta"]
        assert meta["volume_multiplier"] <= 0.8, f"expected reduction; got {meta}"
        assert meta["readiness_score"] < 60

        # Movement volume in the response is downscaled.
        movements = body["workout"]["movements"]
        assert movements[0]["sets"] < 10

    async def test_high_readiness_at_or_above_baseline(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        _seed_active_program(db_session, seeded_user.id, sets=5, reps=10)
        _seed_recovery(db_session, seeded_user.id, sleep_q=10, stress=1, soreness=1, hrv=80)

        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        meta = r.json()["adapted_meta"]
        assert meta["volume_multiplier"] >= 1.0
        assert meta["readiness_score"] >= 60

    async def test_today_returns_planned_session_id(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        _seed_active_program(db_session, seeded_user.id)
        _seed_recovery(db_session, seeded_user.id)

        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        body = r.json()
        assert body["workout"] is not None
        assert body["planned_session_id"]
        assert body["template_id"]

    async def test_today_completed_when_planned_session_done(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        _seed_active_program(db_session, seeded_user.id)
        planned = db_session.execute(
            select(PlannedSessionDB).where(PlannedSessionDB.user_id == seeded_user.id)
        ).scalar_one()
        db_session.add(WorkoutSessionDB(
            user_id=seeded_user.id,
            planned_session_id=planned.id,
            workout_type="strength",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        ))
        db_session.commit()

        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        body = r.json()
        assert body["workout"] is None
        assert body["completed"] is True
        assert body["planned_session_id"] == str(planned.id)
