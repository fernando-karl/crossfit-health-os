"""
Tests for Training API and Adaptive Engine
Tests workout generation for all 4 readiness bands
"""
import pytest
from httpx import AsyncClient
from datetime import date, datetime, timedelta
from uuid import uuid4


class TestAdaptiveEngine:
    """Test adaptive workout generation with different readiness scores"""
    
    @pytest.mark.asyncio
    async def test_generate_workout_optimal_readiness(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test workout generation with readiness >= 80 (optimal)"""
        from unittest.mock import patch, AsyncMock
        from app.models.training import AdaptiveWorkoutResponse, WorkoutTemplate, Movement, Methodology, WorkoutType
        
        # Mock the adaptive engine response
        mock_template = WorkoutTemplate(
            id=uuid4(),
            name="Heavy Back Squat",
            methodology=Methodology.HWPO,
            workout_type=WorkoutType.STRENGTH,
            difficulty_level="intermediate",
            movements=[Movement(movement="back_squat", sets=5, reps=5, intensity="85%")],
            target_stimulus="max_strength",
            tags=[],
            equipment_required=["barbell"],
            created_at=datetime.utcnow(),
            is_public=True
        )
        
        mock_response = AdaptiveWorkoutResponse(
            template=mock_template,
            volume_multiplier=1.1,
            readiness_score=85,
            recommendation="Excellent recovery - push hard today!",
            adjusted_movements=[Movement(movement="back_squat", sets=5, reps=5, intensity="85%")],
            reasoning="High readiness allows for increased volume"
        )
        
        with patch("app.core.engine.adaptive.adaptive_engine.generate_workout", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            
            payload = {
                "user_id": seeded_user.id,
                "date": date.today().isoformat(),
                "force_rest": False
            }
            
            response = await authenticated_client.post("/api/v1/training/generate", json=payload)
            
            assert response.status_code == 200
            data = response.json()
            
            # Should have increased volume (multiplier > 1.0)
            assert data["volume_multiplier"] >= 1.0
            assert data["readiness_score"] >= 80
            assert "push" in data["recommendation"].lower() or "excellent" in data["recommendation"].lower()
    
    @pytest.mark.asyncio
    async def test_generate_workout_normal_readiness(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test workout generation with readiness 60-79 (normal)"""
        from unittest.mock import patch, AsyncMock
        from app.models.training import AdaptiveWorkoutResponse, WorkoutTemplate, Movement, Methodology, WorkoutType
        
        mock_template = WorkoutTemplate(
            id=uuid4(),
            name="Conditioning",
            methodology=Methodology.HWPO,
            workout_type=WorkoutType.METCON,
            difficulty_level="intermediate",
            movements=[
                Movement(movement="burpees", reps=21),
                Movement(movement="air_squats", reps=21)
            ],
            target_stimulus="power_endurance",
            tags=[],
            equipment_required=[],
            created_at=datetime.utcnow(),
            is_public=True
        )
        
        mock_response = AdaptiveWorkoutResponse(
            template=mock_template,
            volume_multiplier=1.0,
            readiness_score=70,
            recommendation="Normal recovery - stick to programmed volume",
            adjusted_movements=[
                Movement(movement="burpees", reps=21),
                Movement(movement="air_squats", reps=21)
            ],
            reasoning="Adequate readiness for normal training"
        )
        
        with patch("app.core.engine.adaptive.adaptive_engine.generate_workout", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            
            payload = {
                "user_id": seeded_user.id,
                "date": date.today().isoformat(),
                "force_rest": False
            }
            
            response = await authenticated_client.post("/api/v1/training/generate", json=payload)
            
            assert response.status_code == 200
            data = response.json()
            
            # Should maintain normal volume (multiplier = 1.0)
            assert 0.9 <= data["volume_multiplier"] <= 1.1
            assert 60 <= data["readiness_score"] < 80
            assert "normal" in data["recommendation"].lower() or "programmed" in data["recommendation"].lower()
    
    @pytest.mark.asyncio
    async def test_generate_workout_moderate_fatigue(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test workout generation with readiness 40-59 (reduced volume)"""
        from unittest.mock import patch, AsyncMock
        from app.models.training import AdaptiveWorkoutResponse, WorkoutTemplate, Movement, Methodology, WorkoutType
        
        mock_template = WorkoutTemplate(
            id=uuid4(),
            name="Light Conditioning",
            methodology=Methodology.HWPO,
            workout_type=WorkoutType.CONDITIONING,
            difficulty_level="intermediate",
            movements=[Movement(movement="run", distance_meters=400, sets=5, rest="90s")],
            target_stimulus="recovery",
            tags=[],
            equipment_required=[],
            created_at=datetime.utcnow(),
            is_public=True
        )
        
        mock_response = AdaptiveWorkoutResponse(
            template=mock_template,
            volume_multiplier=0.8,
            readiness_score=50,
            recommendation="Moderate fatigue detected - reduce volume",
            adjusted_movements=[Movement(movement="run", distance_meters=400, sets=4, rest="90s")],
            reasoning="Reduced readiness requires volume reduction"
        )
        
        with patch("app.core.engine.adaptive.adaptive_engine.generate_workout", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            
            payload = {
                "user_id": seeded_user.id,
                "date": date.today().isoformat(),
                "force_rest": False
            }
            
            response = await authenticated_client.post("/api/v1/training/generate", json=payload)
            
            assert response.status_code == 200
            data = response.json()
            
            # Should reduce volume (multiplier < 1.0)
            assert data["volume_multiplier"] < 1.0
            assert 40 <= data["readiness_score"] < 60
            assert "reduce" in data["recommendation"].lower() or "fatigue" in data["recommendation"].lower()
    
    @pytest.mark.asyncio
    async def test_generate_workout_high_fatigue(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test workout generation with readiness < 40 (active recovery)"""
        from unittest.mock import patch, AsyncMock
        from app.models.training import AdaptiveWorkoutResponse, WorkoutTemplate, Movement, Methodology, WorkoutType
        
        mock_template = WorkoutTemplate(
            id=uuid4(),
            name="Active Recovery",
            methodology=Methodology.CUSTOM,
            workout_type=WorkoutType.CONDITIONING,
            difficulty_level="intermediate",
            movements=[Movement(movement="walk", distance_meters=1000, duration_seconds=600)],
            target_stimulus="recovery",
            tags=["recovery"],
            equipment_required=[],
            created_at=datetime.utcnow(),
            is_public=True
        )
        
        mock_response = AdaptiveWorkoutResponse(
            template=mock_template,
            volume_multiplier=0.5,
            readiness_score=30,
            recommendation="High fatigue - active recovery only",
            adjusted_movements=[Movement(movement="walk", distance_meters=1000, duration_seconds=600)],
            reasoning="Very low readiness requires active recovery"
        )
        
        with patch("app.core.engine.adaptive.adaptive_engine.generate_workout", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            
            payload = {
                "user_id": seeded_user.id,
                "date": date.today().isoformat(),
                "force_rest": False
            }
            
            response = await authenticated_client.post("/api/v1/training/generate", json=payload)
            
            assert response.status_code == 200
            data = response.json()
            
            # Should drastically reduce volume (multiplier <= 0.5)
            assert data["volume_multiplier"] <= 0.6
            assert data["readiness_score"] < 40
            assert "recovery" in data["recommendation"].lower() or "high fatigue" in data["recommendation"].lower()


class TestWorkoutSessions:
    """Test workout session CRUD"""
    
    @pytest.mark.asyncio
    async def test_create_workout_session_minimal_payload(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Frontend sends workout_type + notes without movements list."""
        payload = {
            "workout_type": "mixed",
            "duration_minutes": 45,
            "rpe_score": 7,
            "notes": "Quick session",
        }

        response = await authenticated_client.post("/api/v1/training/sessions", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["workout_type"] == "mixed"
        assert data["duration_minutes"] == 45
        assert data["rpe_score"] == 7

    @pytest.mark.asyncio
    async def test_create_workout_session(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test creating a new workout session"""
        payload = {
            "workout_type": "strength",
            "movements": [
                {"movement": "back_squat", "sets": 5, "reps": 5, "weight_kg": 100}
            ],
            "notes": "Felt strong today"
        }
        
        response = await authenticated_client.post("/api/v1/training/sessions", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        assert data["workout_type"] == "strength"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_session_links_explicit_planned_session(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """POST /sessions stores planned_session_id when provided."""
        from uuid import UUID

        macro = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={"name": "Link test", "methodology": "hwpo", "start_date": "2026-04-20"},
        )
        assert macro.status_code == 201, macro.text
        micro_id = macro.json()["microcycles"][0]["id"]
        listed = await authenticated_client.get(f"/api/v1/schedule/microcycles/{micro_id}")
        planned = next(s for s in listed.json()["sessions"] if s["date"] == "2026-04-20")

        response = await authenticated_client.post(
            "/api/v1/training/sessions",
            json={
                "workout_type": "strength",
                "planned_session_id": planned["id"],
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["planned_session_id"] == planned["id"]

    @pytest.mark.asyncio
    async def test_create_session_auto_links_planned_by_template_today(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """When template_id matches today's generated planned session, link automatically."""
        from datetime import date
        from uuid import uuid4

        from app.db.models import (
            Macrocycle as MacrocycleDB,
            Microcycle as MicrocycleDB,
            PlannedSession as PlannedSessionDB,
            WorkoutTemplate as WorkoutTemplateDB,
        )
        from app.core.datetime_utils import snap_to_monday, user_today

        today = user_today({"timezone": "America/Sao_Paulo"})
        monday = snap_to_monday(today)
        macro = MacrocycleDB(
            user_id=seeded_user.id,
            name="Auto link",
            methodology="hwpo",
            start_date=monday,
            end_date=monday + timedelta(days=6),
            block_plan=[{"type": "accumulation", "weeks": 1}],
            active=True,
        )
        db_session.add(macro)
        db_session.flush()
        micro = MicrocycleDB(
            macrocycle_id=macro.id,
            user_id=seeded_user.id,
            start_date=monday,
            end_date=monday + timedelta(days=6),
            week_index_in_macro=1,
        )
        db_session.add(micro)
        db_session.flush()
        tmpl = WorkoutTemplateDB(
            id=uuid4(),
            name="Today WOD",
            methodology="hwpo",
            workout_type="mixed",
            difficulty_level=3,
            movements=[],
        )
        db_session.add(tmpl)
        db_session.flush()
        planned = PlannedSessionDB(
            microcycle_id=micro.id,
            user_id=seeded_user.id,
            date=today,
            order_in_day=1,
            shift="morning",
            duration_minutes=60,
            workout_type="mixed",
            status="generated",
            generated_template_id=tmpl.id,
        )
        db_session.add(planned)
        db_session.commit()
        db_session.refresh(planned)

        response = await authenticated_client.post(
            "/api/v1/training/sessions",
            json={
                "workout_type": "mixed",
                "template_id": str(tmpl.id),
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["planned_session_id"] == str(planned.id)
    
    @pytest.mark.asyncio
    async def test_complete_workout_session(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test completing a workout session (seed via SQLAlchemy first)."""
        from app.db.models import WorkoutSession as WorkoutSessionDB

        row = WorkoutSessionDB(
            user_id=seeded_user.id,
            workout_type="strength",
            started_at=datetime.utcnow(),
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)

        payload = {
            "completed_at": datetime.utcnow().isoformat(),
            "duration_minutes": 60,
            "rpe_score": 8,
            "score": 100,
            "score_type": "weight",
        }
        response = await authenticated_client.patch(
            f"/api/v1/training/sessions/{row.id}", json=payload
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_workout_sessions(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import WorkoutSession as WorkoutSessionDB
        db_session.add(WorkoutSessionDB(
            user_id=seeded_user.id,
            workout_type="strength",
            started_at=datetime.utcnow(),
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/training/sessions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["workout_type"] == "strength"

    @pytest.mark.asyncio
    async def test_list_workout_sessions_date_filter(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from datetime import timedelta
        from app.db.models import WorkoutSession as WorkoutSessionDB

        today = datetime.utcnow()
        yesterday = today - timedelta(days=1)
        db_session.add(WorkoutSessionDB(
            user_id=seeded_user.id,
            workout_type="strength",
            started_at=today,
        ))
        db_session.add(WorkoutSessionDB(
            user_id=seeded_user.id,
            workout_type="metcon",
            started_at=yesterday,
        ))
        db_session.commit()

        today_iso = today.date().isoformat()
        response = await authenticated_client.get(
            f"/api/v1/training/sessions?start_date={today_iso}&end_date={today_iso}"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["workout_type"] == "strength"


class TestPersonalRecords:
    """Test personal records"""
    
    @pytest.mark.asyncio
    async def test_create_pr(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Test creating a personal record"""
        payload = {
            "movement_name": "back_squat",
            "record_type": "1rm",
            "value": 150.0,
            "unit": "kg",
            "notes": "New PR!"
        }
        
        response = await authenticated_client.post("/api/v1/training/prs", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        assert data["movement_name"] == "back_squat"
        assert data["value"] == 150.0
    
    @pytest.mark.asyncio
    async def test_list_prs(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import PersonalRecord as PRDB
        db_session.add(PRDB(
            user_id=seeded_user.id,
            movement_name="back_squat",
            record_type="1rm",
            value=150.0,
            unit="kg",
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/training/prs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["value"] == 150.0


class TestTrainingStats:
    """Test training statistics"""
    
    @pytest.mark.asyncio
    async def test_get_training_summary(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import WorkoutSession as WorkoutSessionDB
        for wt, dur, rpe in [("strength", 60, 7), ("metcon", 45, 8)]:
            db_session.add(WorkoutSessionDB(
                user_id=seeded_user.id,
                workout_type=wt,
                started_at=datetime.utcnow(),
                duration_minutes=dur,
                rpe_score=rpe,
            ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/training/stats/summary?days=30")
        assert response.status_code == 200
        data = response.json()
        assert data["total_workouts"] == 2
        assert data["workout_types"] == {"strength": 1, "metcon": 1}
        assert data["avg_rpe"] == 7.5
