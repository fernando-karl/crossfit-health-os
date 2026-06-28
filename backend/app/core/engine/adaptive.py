"""
Adaptive Training Engine (SQLAlchemy).

Reads recovery metrics + planned_sessions to prescribe a daily workout adjusted
by readiness score.
"""
from __future__ import annotations

from datetime import date as _Date, datetime as _Datetime, timedelta
from typing import Optional, Tuple
from uuid import uuid4
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.engine.readiness import (
    calculate_hrv_baseline,
    calculate_readiness_score,
    normalize_sleep_quality,
    recovery_row_to_metric,
)
from app.db.models import (
    PlannedSession as PlannedSessionDB,
    RecoveryMetric as RecoveryMetricDB,
    User as UserDB,
    WorkoutTemplate as WorkoutTemplateDB,
)
from app.models.training import (
    AdaptiveWorkoutResponse,
    Methodology,
    Movement,
    WorkoutTemplate,
    WorkoutType,
)

logger = logging.getLogger(__name__)

FITNESS_TO_DIFFICULTY = {
    "beginner": ["scaled", "beginner"],
    "intermediate": ["rx", "intermediate"],
    "advanced": ["rx", "advanced"],
    "elite": ["rx", "elite"],
}


class AdaptiveTrainingEngine:
    """Readiness → volume → template selection."""

    OPTIMAL_THRESHOLD = 80
    NORMAL_THRESHOLD = 60
    REDUCED_THRESHOLD = 40

    DEFAULT_HRV_MS = 50.0
    DEFAULT_READINESS_SCORE = 70
    DEFAULT_SLEEP_QUALITY = 7
    DEFAULT_STRESS_LEVEL = 5
    DEFAULT_MUSCLE_SORENESS = 5
    DEFAULT_ENERGY_LEVEL = 7

    MIN_HRV_DATA_POINTS = 5
    HRV_BASELINE_LOOKBACK_DAYS = 30

    WEIGHT_REDUCTION_THRESHOLD = 50

    # ==========================================================
    # Public
    # ==========================================================

    async def generate_workout(
        self,
        db: Session,
        user_id: int,
        target_date: _Date,
        force_rest: bool = False,
        recovery_override: Optional[dict] = None,
    ) -> AdaptiveWorkoutResponse:
        recovery = self._resolve_recovery_metrics(db, user_id, target_date, recovery_override)
        readiness_score = recovery["readiness_score"]
        volume_multiplier, recommendation = self._determine_volume_adjustment(readiness_score, force_rest)

        user = db.get(UserDB, user_id)
        if force_rest or volume_multiplier == 0.0:
            base_workout = self._create_recovery_workout()
            adjusted_movements: list[Movement] = []
        else:
            base_workout = self._select_workout_template(db, user_id, target_date, user, readiness_score)
            adjusted_movements = self._adjust_movements(base_workout.movements, volume_multiplier, readiness_score)

        base_workout = self._persist_template_if_needed(db, user_id, base_workout)

        reasoning = self._generate_reasoning(recovery, readiness_score, volume_multiplier, base_workout.methodology)

        return AdaptiveWorkoutResponse(
            template=base_workout,
            volume_multiplier=volume_multiplier,
            readiness_score=readiness_score,
            recommendation=recommendation,
            adjusted_movements=adjusted_movements,
            reasoning=reasoning,
        )

    def adapt_template(
        self,
        db: Session,
        user_id: int,
        template: WorkoutTemplate,
        target_date: _Date,
        force_rest: bool = False,
    ) -> AdaptiveWorkoutResponse:
        """Apply the readiness multiplier over a pre-existing template."""
        recovery = self._get_recovery_metrics(db, user_id, target_date)
        readiness_score = self._calculate_readiness_score(recovery)
        volume_multiplier, recommendation = self._determine_volume_adjustment(
            readiness_score, force_rest=force_rest
        )
        if force_rest or volume_multiplier == 0.0:
            adjusted_movements: list[Movement] = []
        else:
            adjusted_movements = self._adjust_movements(
                template.movements, volume_multiplier, readiness_score
            )
        reasoning = self._generate_reasoning(
            recovery, readiness_score, volume_multiplier, template.methodology
        )
        return AdaptiveWorkoutResponse(
            template=template,
            volume_multiplier=volume_multiplier,
            readiness_score=readiness_score,
            recommendation=recommendation,
            adjusted_movements=adjusted_movements,
            reasoning=reasoning,
        )

    # ==========================================================
    # Recovery + readiness
    # ==========================================================

    def _calculate_hrv_baseline(
        self, db: Session, user_id: int, as_of: Optional[_Date] = None, lookback_days: int = 30
    ) -> float:
        return calculate_hrv_baseline(db, user_id, as_of=as_of, lookback_days=lookback_days)

    def _get_recovery_metrics(self, db: Session, user_id: int, target_date: _Date) -> dict:
        row = db.execute(
            select(RecoveryMetricDB).where(
                RecoveryMetricDB.user_id == user_id,
                RecoveryMetricDB.date == target_date,
            )
        ).scalar_one_or_none()
        return recovery_row_to_metric(db, user_id, row, as_of=target_date)

    def _resolve_recovery_metrics(
        self,
        db: Session,
        user_id: int,
        target_date: _Date,
        recovery_override: Optional[dict],
    ) -> dict:
        """Merge DB recovery with optional client snapshot for generate."""
        recovery = self._get_recovery_metrics(db, user_id, target_date)
        if not recovery_override:
            recovery["readiness_score"] = calculate_readiness_score(recovery)
            return recovery

        merged = dict(recovery)
        if recovery_override.get("hrv_rmssd_ms") is not None:
            merged["hrv_ms"] = recovery_override["hrv_rmssd_ms"]
            baseline = calculate_hrv_baseline(db, user_id, as_of=target_date)
            merged["hrv_ratio"] = recovery_override["hrv_rmssd_ms"] / baseline if baseline else 1.0
        if recovery_override.get("sleep_quality_score") is not None:
            merged["sleep_quality"] = normalize_sleep_quality(recovery_override["sleep_quality_score"])
        if recovery_override.get("muscle_soreness") is not None:
            merged["muscle_soreness"] = recovery_override["muscle_soreness"]
        if recovery_override.get("stress_level") is not None:
            merged["stress_level"] = recovery_override["stress_level"]
        if recovery_override.get("energy_level") is not None:
            merged["energy_level"] = recovery_override["energy_level"]

        if recovery_override.get("readiness_score") is not None:
            merged["readiness_score"] = recovery_override["readiness_score"]
        else:
            merged["readiness_score"] = calculate_readiness_score(merged)
        return merged

    def _persist_template_if_needed(
        self, db: Session, user_id: int, template: WorkoutTemplate
    ) -> WorkoutTemplate:
        """Persist ephemeral fallback templates so session FKs remain valid."""
        if template.id and db.get(WorkoutTemplateDB, template.id):
            return template

        workout_type = (
            template.workout_type.value
            if hasattr(template.workout_type, "value")
            else template.workout_type
        )
        methodology = (
            template.methodology.value
            if hasattr(template.methodology, "value")
            else template.methodology
        )
        difficulty = (
            template.difficulty_level.value
            if hasattr(template.difficulty_level, "value")
            else template.difficulty_level
        )

        row = WorkoutTemplateDB(
            id=template.id or uuid4(),
            owner_user_id=user_id,
            name=template.name,
            description=template.description,
            methodology=methodology,
            difficulty_level=difficulty or "rx",
            workout_type=workout_type,
            duration_minutes=template.duration_minutes,
            movements=[m.model_dump(mode="json") for m in template.movements],
            target_stimulus=template.target_stimulus,
            rep_scheme=template.rep_scheme,
            warm_up=template.warm_up,
            tags=template.tags or [],
            equipment_required=template.equipment_required or [],
            is_public=False,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _template_from_row(row)

    def _calculate_readiness_score(self, recovery: dict) -> int:
        return calculate_readiness_score(recovery)

    def _determine_volume_adjustment(self, readiness_score: int, force_rest: bool) -> Tuple[float, str]:
        if force_rest:
            return 0.0, "🛌 Forced rest day - complete recovery"
        if readiness_score >= self.OPTIMAL_THRESHOLD:
            return 1.1, "💪 Excellent readiness - push for PRs and high volume"
        if readiness_score >= self.NORMAL_THRESHOLD:
            return 1.0, "✅ Normal readiness - train as programmed"
        if readiness_score >= self.REDUCED_THRESHOLD:
            return 0.8, "⚠️  Moderate fatigue - reduce volume by 20%"
        return 0.5, "🔴 High fatigue - active recovery only (mobility, light cardio)"

    # ==========================================================
    # Template selection
    # ==========================================================

    def _select_workout_template(
        self,
        db: Session,
        user_id: int,
        target_date: _Date,
        user: Optional[UserDB],
        readiness_score: int,
    ) -> WorkoutTemplate:
        prefs = (user.preferences or {}) if user else {}
        methodology = prefs.get("methodology", "hwpo")
        fitness_level = user.fitness_level if user else "intermediate"

        planned = db.execute(
            select(PlannedSessionDB)
            .where(
                PlannedSessionDB.user_id == user_id,
                PlannedSessionDB.date == target_date,
            )
            .order_by(PlannedSessionDB.order_in_day)
            .limit(1)
        ).scalar_one_or_none()

        if planned:
            if planned.generated_template_id:
                tpl_row = db.get(WorkoutTemplateDB, planned.generated_template_id)
                if tpl_row:
                    return _template_from_row(tpl_row)
            workout_type = planned.workout_type or "mixed"
            target_stimulus = planned.focus or workout_type
            return self._pick_or_default_template(db, methodology, workout_type, fitness_level, target_stimulus)

        workout_type, target_stimulus = self._fallback_weekday_type(target_date.weekday(), readiness_score)
        return self._pick_or_default_template(db, methodology, workout_type, fitness_level, target_stimulus)

    def _pick_or_default_template(
        self,
        db: Session,
        methodology: str,
        workout_type: str,
        fitness_level: str,
        target_stimulus: str,
    ) -> WorkoutTemplate:
        difficulty_levels = FITNESS_TO_DIFFICULTY.get(fitness_level, [fitness_level, "rx"])
        row = db.execute(
            select(WorkoutTemplateDB).where(
                WorkoutTemplateDB.methodology == methodology,
                WorkoutTemplateDB.workout_type == workout_type,
                WorkoutTemplateDB.difficulty_level.in_(difficulty_levels),
            ).limit(1)
        ).scalar_one_or_none()
        if row:
            return _template_from_row(row)
        return self._create_default_workout(workout_type, target_stimulus)

    @staticmethod
    def _fallback_weekday_type(day_of_week: int, readiness_score: int) -> tuple[str, str]:
        if day_of_week == 0:
            return "strength", "max_strength"
        if day_of_week == 1:
            return "skill", "body_control"
        if day_of_week == 2:
            return ("conditioning" if readiness_score >= 60 else "skill"), "recovery"
        if day_of_week == 3:
            return "metcon", "power_endurance"
        if day_of_week == 4:
            return "mixed", "competition"
        if day_of_week == 5:
            return "metcon", "endurance"
        return "conditioning", "recovery"

    # ==========================================================
    # Movement adjustment & reasoning
    # ==========================================================

    def _adjust_movements(
        self,
        movements: list[Movement],
        volume_multiplier: float,
        readiness_score: int,
    ) -> list[Movement]:
        if volume_multiplier == 0.0:
            return []

        adjusted = []
        for movement in movements:
            m = movement.model_copy(deep=True)
            if m.sets:
                m.sets = max(1, round(m.sets * volume_multiplier)) if volume_multiplier > 0 else 0
            if isinstance(m.reps, int):
                m.reps = max(1, round(m.reps * volume_multiplier)) if volume_multiplier > 0 else 0
            if readiness_score < self.WEIGHT_REDUCTION_THRESHOLD and m.weight_kg:
                m.weight_kg = m.weight_kg * 0.85
                m.notes = (m.notes or "") + " (Weight reduced due to fatigue)"
            adjusted.append(m)
        return adjusted

    def _generate_reasoning(
        self,
        recovery: dict,
        readiness_score: int,
        volume_multiplier: float,
        methodology: Methodology,
    ) -> str:
        hrv_ratio = recovery.get("hrv_ratio", 1.0)
        sleep_quality = recovery.get("sleep_quality_score", recovery.get("sleep_quality", 7))
        parts: list[str] = []
        if hrv_ratio > 1.1:
            parts.append(f"HRV elevated ({hrv_ratio:.2f}x baseline) — excellent recovery")
        elif hrv_ratio < 0.9:
            parts.append(f"HRV suppressed ({hrv_ratio:.2f}x baseline) — incomplete recovery")
        else:
            parts.append(f"HRV normal ({hrv_ratio:.2f}x baseline)")
        if isinstance(sleep_quality, (int, float)):
            if sleep_quality >= 80 or (1 <= sleep_quality <= 10 and sleep_quality >= 8):
                parts.append(f"sleep quality excellent ({sleep_quality})")
            elif (10 < sleep_quality < 60) or (1 <= sleep_quality <= 10 and sleep_quality < 6):
                parts.append(f"sleep quality poor ({sleep_quality})")
        parts.append(f"Overall readiness: {readiness_score}/100")
        if volume_multiplier > 1.0:
            parts.append(f"Increasing volume by {int((volume_multiplier - 1) * 100)}% to capitalize on recovery")
        elif volume_multiplier < 1.0:
            parts.append(f"Reducing volume by {int((1 - volume_multiplier) * 100)}% to prioritize recovery")
        else:
            parts.append("Training at programmed volume")
        parts.append(f"Following {methodology.value.upper()} methodology")
        return " • ".join(parts)

    def _create_recovery_workout(self) -> WorkoutTemplate:
        return WorkoutTemplate(
            id=uuid4(),
            name="Active Recovery",
            description="Rest day — mobility and light movement only",
            methodology=Methodology.CUSTOM,
            difficulty_level="scaled",
            workout_type=WorkoutType.CONDITIONING,
            movements=[
                Movement(movement="walk", distance_meters=2000, notes="Easy pace"),
                Movement(movement="mobility", reps="10 min", notes="Full body"),
            ],
            target_stimulus="recovery",
            tags=["recovery", "rest_day"],
            equipment_required=[],
            created_at=_Datetime.utcnow(),
            is_public=False,
        )

    def _create_default_workout(self, workout_type: str, target_stimulus: str) -> WorkoutTemplate:
        if workout_type == "strength":
            movements = [Movement(movement="back_squat", sets=5, reps=5, intensity="80%", rest="3min")]
        elif workout_type == "metcon":
            movements = [
                Movement(movement="burpees", reps=21),
                Movement(movement="air_squats", reps=21),
                Movement(movement="burpees", reps=15),
                Movement(movement="air_squats", reps=15),
            ]
        else:
            movements = [Movement(movement="run", distance_meters=400, sets=5, rest="90s")]

        return WorkoutTemplate(
            id=uuid4(),
            name=f"Default {workout_type.title()}",
            description="Auto-generated fallback workout",
            methodology=Methodology.CUSTOM,
            difficulty_level="rx",
            workout_type=workout_type,
            movements=movements,
            target_stimulus=target_stimulus,
            tags=["auto_generated"],
            equipment_required=[],
            created_at=_Datetime.utcnow(),
            is_public=False,
        )


def _template_from_row(row: WorkoutTemplateDB) -> WorkoutTemplate:
    return WorkoutTemplate(
        id=row.id,
        name=row.name,
        description=row.description,
        methodology=Methodology(row.methodology),
        difficulty_level=row.difficulty_level,
        workout_type=WorkoutType(row.workout_type),
        duration_minutes=row.duration_minutes,
        movements=[Movement(**m) for m in (row.movements or [])],
        target_stimulus=row.target_stimulus,
        rep_scheme=row.rep_scheme,
        tags=row.tags or [],
        equipment_required=row.equipment_required or [],
        created_at=row.created_at,
        is_public=row.is_public,
    )


adaptive_engine = AdaptiveTrainingEngine()
