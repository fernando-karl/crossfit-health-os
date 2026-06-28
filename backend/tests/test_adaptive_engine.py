"""
Tests for app/core/engine/adaptive.py
Covers pure-logic methods: _calculate_readiness_score, _determine_volume_adjustment,
_adjust_movements, _generate_reasoning, _create_default_workout
"""
import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.engine.adaptive import AdaptiveTrainingEngine
from app.models.training import Movement, Methodology


@pytest.fixture
def engine():
    # Adaptive engine no longer holds a Supabase client — takes a Session per call.
    return AdaptiveTrainingEngine()


# ─────────────────────────────────────────────
# _calculate_readiness_score
# ─────────────────────────────────────────────

class TestCalculateReadinessScore:
    def test_optimal_recovery(self, engine):
        # HRV elevated, great sleep, low stress, low soreness
        recovery = {
            "hrv_ratio": 1.2,
            "sleep_quality": 9,
            "stress_level": 2,
            "muscle_soreness": 2,
        }
        score = engine._calculate_readiness_score(recovery)
        assert score >= 80

    def test_poor_recovery(self, engine):
        recovery = {
            "hrv_ratio": 0.6,
            "sleep_quality": 3,
            "stress_level": 9,
            "muscle_soreness": 9,
        }
        score = engine._calculate_readiness_score(recovery)
        assert score < 50

    def test_default_values(self, engine):
        """Empty dict should use defaults and return a mid-range score"""
        score = engine._calculate_readiness_score({})
        assert 0 <= score <= 100

    def test_clamped_to_100(self, engine):
        recovery = {
            "hrv_ratio": 2.0,  # well above max expected
            "sleep_quality": 10,
            "stress_level": 1,
            "muscle_soreness": 1,
        }
        score = engine._calculate_readiness_score(recovery)
        assert score <= 100

    def test_clamped_to_zero(self, engine):
        recovery = {
            "hrv_ratio": 0.0,
            "sleep_quality": 1,
            "stress_level": 10,
            "muscle_soreness": 10,
        }
        score = engine._calculate_readiness_score(recovery)
        assert score >= 0

    def test_baseline_hrv_ratio_gives_midrange(self, engine):
        # HRV ratio of 1.0 with moderate metrics
        recovery = {
            "hrv_ratio": 1.0,
            "sleep_quality": 7,
            "stress_level": 5,
            "muscle_soreness": 5,
        }
        score = engine._calculate_readiness_score(recovery)
        assert 40 <= score <= 80

    def test_returns_integer(self, engine):
        score = engine._calculate_readiness_score({"hrv_ratio": 1.0})
        assert isinstance(score, int)


# ─────────────────────────────────────────────
# _determine_volume_adjustment
# ─────────────────────────────────────────────

class TestDetermineVolumeAdjustment:
    def test_force_rest_returns_zero(self, engine):
        multiplier, rec = engine._determine_volume_adjustment(90, force_rest=True)
        assert multiplier == 0.0
        assert "rest" in rec.lower() or "forced" in rec.lower()

    def test_optimal_readiness_pushes_volume(self, engine):
        multiplier, rec = engine._determine_volume_adjustment(85, force_rest=False)
        assert multiplier == 1.1

    def test_normal_readiness_maintains_volume(self, engine):
        multiplier, rec = engine._determine_volume_adjustment(70, force_rest=False)
        assert multiplier == 1.0

    def test_reduced_readiness_cuts_volume(self, engine):
        multiplier, rec = engine._determine_volume_adjustment(50, force_rest=False)
        assert multiplier == 0.8

    def test_very_low_readiness_active_recovery(self, engine):
        multiplier, rec = engine._determine_volume_adjustment(30, force_rest=False)
        assert multiplier == 0.5

    def test_boundaries_exactly_80(self, engine):
        multiplier, _ = engine._determine_volume_adjustment(80, force_rest=False)
        assert multiplier == 1.1

    def test_boundaries_exactly_60(self, engine):
        multiplier, _ = engine._determine_volume_adjustment(60, force_rest=False)
        assert multiplier == 1.0

    def test_boundaries_exactly_40(self, engine):
        multiplier, _ = engine._determine_volume_adjustment(40, force_rest=False)
        assert multiplier == 0.8

    def test_boundary_below_40(self, engine):
        multiplier, _ = engine._determine_volume_adjustment(39, force_rest=False)
        assert multiplier == 0.5


# ─────────────────────────────────────────────
# _adjust_movements
# ─────────────────────────────────────────────

class TestAdjustMovements:
    def _make_movement(self, sets=5, reps=5, weight=100.0):
        return Movement(movement="back_squat", sets=sets, reps=reps, weight_kg=weight, rest="3min", intensity="80%")

    def test_increases_sets_above_1_0(self, engine):
        movements = [self._make_movement(sets=4)]
        adjusted = engine._adjust_movements(movements, 1.1, 85)
        assert adjusted[0].sets >= 4

    def test_reduces_sets_below_1_0(self, engine):
        movements = [self._make_movement(sets=5)]
        adjusted = engine._adjust_movements(movements, 0.8, 50)
        assert adjusted[0].sets <= 5

    def test_zero_multiplier_returns_empty(self, engine):
        movements = [self._make_movement(sets=5)]
        assert engine._adjust_movements(movements, 0.0, 70) == []

    def test_minimum_sets_is_1(self, engine):
        movements = [self._make_movement(sets=1)]
        adjusted = engine._adjust_movements(movements, 0.5, 30)
        assert adjusted[0].sets == 1

    def test_reduces_weight_for_low_readiness(self, engine):
        movements = [self._make_movement(weight=100.0)]
        adjusted = engine._adjust_movements(movements, 0.5, 30)
        assert adjusted[0].weight_kg < 100.0

    def test_does_not_reduce_weight_for_high_readiness(self, engine):
        movements = [self._make_movement(weight=100.0)]
        adjusted = engine._adjust_movements(movements, 1.0, 80)
        assert adjusted[0].weight_kg == 100.0

    def test_adds_fatigue_note_for_low_readiness(self, engine):
        movements = [self._make_movement(weight=100.0)]
        adjusted = engine._adjust_movements(movements, 0.5, 30)
        assert adjusted[0].notes is not None
        assert "fatigue" in adjusted[0].notes.lower() or "reduced" in adjusted[0].notes.lower()

    def test_string_reps_not_adjusted(self, engine):
        m = Movement(movement="pull_up", reps="AMRAP", rest="2min")
        adjusted = engine._adjust_movements([m], 1.1, 85)
        assert adjusted[0].reps == "AMRAP"

    def test_empty_movements_returns_empty(self, engine):
        assert engine._adjust_movements([], 1.0, 70) == []

    def test_original_not_mutated(self, engine):
        m = self._make_movement(sets=5)
        engine._adjust_movements([m], 0.5, 30)
        assert m.sets == 5  # original unchanged


# ─────────────────────────────────────────────
# _generate_reasoning
# ─────────────────────────────────────────────

class TestGenerateReasoning:
    def test_returns_string(self, engine):
        recovery = {"hrv_ratio": 1.0, "sleep_quality_score": 75}
        result = engine._generate_reasoning(recovery, 70, 1.0, Methodology.HWPO)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_includes_readiness(self, engine):
        recovery = {"hrv_ratio": 1.0}
        result = engine._generate_reasoning(recovery, 75, 1.0, Methodology.HWPO)
        assert "75" in result

    def test_hrv_elevated_message(self, engine):
        recovery = {"hrv_ratio": 1.2}
        result = engine._generate_reasoning(recovery, 85, 1.1, Methodology.HWPO)
        assert "elevated" in result.lower() or "excellent" in result.lower()

    def test_hrv_suppressed_message(self, engine):
        recovery = {"hrv_ratio": 0.8}
        result = engine._generate_reasoning(recovery, 50, 0.8, Methodology.HWPO)
        assert "suppressed" in result.lower() or "incomplete" in result.lower()

    def test_volume_increase_message(self, engine):
        recovery = {"hrv_ratio": 1.2}
        result = engine._generate_reasoning(recovery, 85, 1.1, Methodology.HWPO)
        assert "increasing" in result.lower() or "capitalize" in result.lower()

    def test_volume_decrease_message(self, engine):
        recovery = {"hrv_ratio": 0.7}
        result = engine._generate_reasoning(recovery, 30, 0.5, Methodology.HWPO)
        assert "reducing" in result.lower() or "recovery" in result.lower()

    def test_methodology_included(self, engine):
        recovery = {"hrv_ratio": 1.0}
        result = engine._generate_reasoning(recovery, 70, 1.0, Methodology.HWPO)
        assert "hwpo" in result.lower()

    def test_good_sleep_message(self, engine):
        recovery = {"hrv_ratio": 1.0, "sleep_quality_score": 85}
        result = engine._generate_reasoning(recovery, 70, 1.0, Methodology.HWPO)
        assert "sleep" in result.lower()


# ─────────────────────────────────────────────
# _create_default_workout
# ─────────────────────────────────────────────

class TestCreateDefaultWorkout:
    def test_strength_workout(self, engine):
        w = engine._create_default_workout("strength", "max_strength")
        assert w.workout_type == "strength"
        assert len(w.movements) > 0
        assert w.methodology == Methodology.CUSTOM

    def test_metcon_workout(self, engine):
        w = engine._create_default_workout("metcon", "power_endurance")
        assert w.workout_type == "metcon"
        assert len(w.movements) > 0

    def test_other_type_returns_conditioning(self, engine):
        w = engine._create_default_workout("conditioning", "recovery")
        assert w.workout_type == "conditioning"
        assert len(w.movements) > 0

    def test_returns_workout_template(self, engine):
        from app.models.training import WorkoutTemplate
        w = engine._create_default_workout("strength", "max_strength")
        assert isinstance(w, WorkoutTemplate)

    def test_skill_type_falls_to_run_default(self, engine):
        # "skill" is not "strength" or "metcon", hits the else branch
        w = engine._create_default_workout("skill", "body_control")
        assert len(w.movements) > 0


# ─────────────────────────────────────────────
# _calculate_hrv_baseline (async, with mock)
# ─────────────────────────────────────────────

def _mock_db_response(data):
    """Create a mock Supabase response that passes handle_supabase_response checks."""
    resp = MagicMock()
    resp.error = None
    resp.data = data
    return resp


class TestCalculateHrvBaseline:
    """The adaptive engine now takes a SQLAlchemy session. Tests use the
    `db_session` + `seeded_user` fixtures from conftest to insert recovery rows."""

    def test_insufficient_data_returns_default(self, engine, db_session, seeded_user):
        baseline = engine._calculate_hrv_baseline(db_session, seeded_user.id)
        assert baseline == AdaptiveTrainingEngine.DEFAULT_HRV_MS

    def test_calculates_average_when_enough_data(self, engine, db_session, seeded_user):
        from app.db.models import RecoveryMetric
        values = [50, 55, 60, 48, 52, 58]
        today = date.today()
        for i, v in enumerate(values):
            db_session.add(RecoveryMetric(
                user_id=seeded_user.id,
                date=today - timedelta(days=i),
                hrv_ms=v,
            ))
        db_session.commit()
        baseline = engine._calculate_hrv_baseline(db_session, seeded_user.id)
        expected = sum(values) / len(values)
        assert abs(baseline - expected) < 0.1

    def test_none_hrv_values_filtered(self, engine, db_session, seeded_user):
        from app.db.models import RecoveryMetric
        today = date.today()
        for i in range(5):
            db_session.add(RecoveryMetric(
                user_id=seeded_user.id,
                date=today - timedelta(days=i),
                hrv_ms=None,
                sleep_quality=7,
            ))
        db_session.commit()
        # Rows with NULL hrv_ms are excluded, so count < MIN_HRV_DATA_POINTS → default
        baseline = engine._calculate_hrv_baseline(db_session, seeded_user.id)
        assert baseline == AdaptiveTrainingEngine.DEFAULT_HRV_MS
