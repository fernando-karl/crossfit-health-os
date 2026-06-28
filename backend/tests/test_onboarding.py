"""
Tests for Onboarding API (SQLAlchemy).
"""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


def _payload(**overrides):
    base = {
        "name": "Test Athlete",
        "fitness_level": "intermediate",
        "primary_goal": "strength",
        "available_days": ["monday", "wednesday", "friday"],
        "preferred_time": "morning",
        "training_duration": 60,
        "methodologies": ["hwpo"],
        "focus_weaknesses": ["snatch"],
        "has_gym_access": True,
        "has_barbell": True,
        "has_rings": False,
        "has_pullup_bar": True,
        "app_focus": "full",
        "nutrition_enabled": True,
    }
    base.update(overrides)
    return base


class TestCompleteOnboarding:
    @pytest.mark.asyncio
    @patch("app.services.starter_program.create_starter_program", return_value=None)
    async def test_complete_onboarding_success(
        self, mock_program, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.post(
            "/api/v1/onboarding/complete", json=_payload()
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success"] is True
        assert data["xp_earned"] == 300
        assert data["schedule_created"] is False

        db_session.refresh(seeded_user)
        prefs = seeded_user.preferences or {}
        assert prefs["onboarding_completed"] is True
        assert prefs["primary_goal"] == "strength"
        assert prefs["methodologies"] == ["hwpo"]
        mock_program.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "app.services.starter_program.create_starter_program",
        return_value={"program_id": "p1", "macrocycle_id": "m1", "planned_sessions": 12},
    )
    async def test_complete_onboarding_creates_program_when_available(
        self, mock_program, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.post(
            "/api/v1/onboarding/complete", json=_payload()
        )
        assert response.status_code == 200
        data = response.json()
        assert data["schedule_created"] is True
        assert data["program"]["planned_sessions"] == 12

    @pytest.mark.asyncio
    async def test_complete_onboarding_with_birth_date_young(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        payload = _payload(birth_date="2003-01-01")  # ~23 years old
        response = await authenticated_client.post(
            "/api/v1/onboarding/complete", json=payload
        )
        assert response.status_code == 200
        db_session.refresh(seeded_user)
        assert (seeded_user.preferences or {}).get("baseline_readiness") == 85

    @pytest.mark.asyncio
    async def test_complete_onboarding_with_birth_date_older(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        payload = _payload(birth_date="1975-01-01")  # ~50 years old
        response = await authenticated_client.post(
            "/api/v1/onboarding/complete", json=payload
        )
        assert response.status_code == 200
        db_session.refresh(seeded_user)
        assert (seeded_user.preferences or {}).get("baseline_readiness") == 55

    @pytest.mark.asyncio
    async def test_complete_onboarding_bad_birth_date_uses_default(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        payload = _payload(birth_date="not-a-date")
        response = await authenticated_client.post(
            "/api/v1/onboarding/complete", json=payload
        )
        assert response.status_code == 200
        db_session.refresh(seeded_user)
        # Invalid birth_date → readiness defaults to 70
        assert (seeded_user.preferences or {}).get("baseline_readiness") == 70

    @pytest.mark.asyncio
    async def test_complete_onboarding_without_auth_returns_401(
        self, async_client: AsyncClient
    ):
        response = await async_client.post("/api/v1/onboarding/complete", json=_payload())
        assert response.status_code == 401


class TestOnboardingProgress:
    @pytest.mark.asyncio
    async def test_progress_fresh_user(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.get("/api/v1/onboarding/progress")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == 1
        assert data["profile_complete"] is False
        assert data["schedule_created"] is False
        assert data["first_workout_done"] is False

    @pytest.mark.asyncio
    async def test_progress_after_profile_complete(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        seeded_user.preferences = {"onboarding_completed": True}
        db_session.add(seeded_user)
        db_session.commit()

        response = await authenticated_client.get("/api/v1/onboarding/progress")
        data = response.json()
        assert data["profile_complete"] is True
        assert data["step"] >= 2

    @pytest.mark.asyncio
    async def test_progress_full(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import Macrocycle, WorkoutSession

        seeded_user.preferences = {"onboarding_completed": True}
        db_session.add(seeded_user)
        db_session.add(Macrocycle(
            user_id=seeded_user.id, name="m", methodology="hwpo",
            start_date=date.today(), end_date=date.today() + timedelta(days=6),
            block_plan=[{"type": "accumulation", "weeks": 1}], active=True,
        ))
        db_session.add(WorkoutSession(
            user_id=seeded_user.id, workout_type="strength",
            started_at=datetime.utcnow() - timedelta(hours=1),
            completed_at=datetime.utcnow(),
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/onboarding/progress")
        data = response.json()
        assert data["completed"] is True
        assert data["profile_complete"] is True
        assert data["schedule_created"] is True
        assert data["first_workout_done"] is True


class TestOnboardingSuggestions:
    @pytest.mark.asyncio
    async def test_get_suggestions_beginner(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        seeded_user.fitness_level = "beginner"
        db_session.add(seeded_user)
        db_session.commit()

        response = await authenticated_client.get("/api/v1/onboarding/suggestions")
        assert response.status_code == 200
        data = response.json()
        titles = [s["title"] for s in data["suggestions"]]
        assert any("Start Light" in t for t in titles)

    @pytest.mark.asyncio
    async def test_get_suggestions_strength_goal(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        seeded_user.preferences = {
            **(seeded_user.preferences or {}),
            "primary_goal": "strength",
        }
        db_session.add(seeded_user)
        db_session.commit()

        response = await authenticated_client.get("/api/v1/onboarding/suggestions")
        assert response.status_code == 200
        titles = [s["title"] for s in response.json()["suggestions"]]
        assert any("Compound" in t for t in titles)

    @pytest.mark.asyncio
    async def test_get_suggestions_conditioning_goal(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        seeded_user.preferences = {
            **(seeded_user.preferences or {}),
            "primary_goal": "conditioning",
        }
        db_session.add(seeded_user)
        db_session.commit()

        response = await authenticated_client.get("/api/v1/onboarding/suggestions")
        assert response.status_code == 200
        titles = [s["title"] for s in response.json()["suggestions"]]
        assert any("Engine" in t for t in titles)

    @pytest.mark.asyncio
    async def test_get_suggestions_always_includes_track_tip(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.get("/api/v1/onboarding/suggestions")
        titles = [s["title"] for s in response.json()["suggestions"]]
        assert any("Track" in t for t in titles)

    @pytest.mark.asyncio
    async def test_get_suggestions_user_not_found(
        self, authenticated_client: AsyncClient, db_session
    ):
        """User seeded in JWT but no DB row => 404 on suggestions."""
        # mock_user id=1 but we never added the row → 404
        response = await authenticated_client.get("/api/v1/onboarding/suggestions")
        assert response.status_code == 404
