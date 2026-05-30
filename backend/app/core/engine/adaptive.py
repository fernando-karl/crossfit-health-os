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
    ) -> AdaptiveWorkoutResponse:
        recovery = self._get_recovery_metrics(db, user_id, target_date)
        readiness_score = self._calculate_readiness_score(recovery)
        volume_multiplier, recommendation = self._determine_volume_adjustment(readiness_score, force_rest)

        user = db.get(UserDB, user_id)
        base_workout = self._select_workout_template(db, user_id, target_date, user, readiness_score)

        adjusted_movements = self._adjust_movements(base_workout.movements, volume_multiplier, readiness_score)
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
    ) -> AdaptiveWorkoutResponse:
        """Apply the readiness multiplier over a pre-existing template.

        Used by ``GET /training/today`` when the user has an active program:
        instead of returning the raw planned session, we overlay today's
        recovery so volume/weight reflect how the athlete actually feels.
        """
        recovery = self._get_recovery_metrics(db, user_id, target_date)
        readiness_score = self._calculate_readiness_score(recovery)
        volume_multiplier, recommendation = self._determine_volume_adjustment(
            readiness_score, force_rest=False
        )
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

    def _calculate_hrv_baseline(self, db: Session, user_id: int, lookback_days: int = 30) -> float:
        from_date = _Date.today() - timedelta(days=lookback_days)
        rows = db.execute(
            select(RecoveryMetricDB.hrv_ms).where(
                RecoveryMetricDB.user_id == user_id,
                RecoveryMetricDB.date >= from_date,
                RecoveryMetricDB.hrv_ms.isnot(None),
            )
        ).scalars().all()

        if not rows or len(rows) < self.MIN_HRV_DATA_POINTS:
            return self.DEFAULT_HRV_MS
        return sum(rows) / len(rows)

    def _get_recovery_metrics(self, db: Session, user_id: int, target_date: _Date) -> dict:
        row = db.execute(
            select(RecoveryMetricDB).where(
                RecoveryMetricDB.user_id == user_id,
                RecoveryMetricDB.date == target_date,
            )
        ).scalar_one_or_none()

        if not row:
            return {
                "hrv_ratio": 1.0,
                "hrv_ms": self.DEFAULT_HRV_MS,
                "sleep_quality": self.DEFAULT_SLEEP_QUALITY,
                "stress_level": self.DEFAULT_STRESS_LEVEL,
                "muscle_soreness": self.DEFAULT_MUSCLE_SORENESS,
                "energy_level": self.DEFAULT_ENERGY_LEVEL,
                "readiness_score": self.DEFAULT_READINESS_SCORE,
            }

        metric = {
            "hrv_ms": row.hrv_ms,
            "sleep_quality": row.sleep_quality or self.DEFAULT_SLEEP_QUALITY,
            "stress_level": row.stress_level or self.DEFAULT_STRESS_LEVEL,
            "muscle_soreness": row.muscle_soreness or self.DEFAULT_MUSCLE_SORENESS,
            "energy_level": row.energy_level or self.DEFAULT_ENERGY_LEVEL,
            "readiness_score": row.readiness_score or self.DEFAULT_READINESS_SCORE,
        }

        if row.hrv_ms:
            baseline = self._calculate_hrv_baseline(db, user_id)
            metric["hrv_ratio"] = row.hrv_ms / baseline
        else:
            metric["hrv_ratio"] = 1.0
        return metric

    def _calculate_readiness_score(self, recovery: dict) -> int:
        hrv_ratio = recovery.get("hrv_ratio", 1.0)
        sleep_quality = recovery.get("sleep_quality", 7)
        stress = recovery.get("stress_level", 5)
        soreness = recovery.get("muscle_soreness", 5)

        hrv_normalized = max(0, min(1, (hrv_ratio - 0.5) / 1.0))
        sleep_normalized = (sleep_quality - 1) / 9
        stress_normalized = 1 - ((stress - 1) / 9)
        soreness_normalized = 1 - ((soreness - 1) / 9)

        readiness = (
            hrv_normalized * 0.4
            + sleep_normalized * 0.3
            + stress_normalized * 0.2
            + soreness_normalized * 0.1
        ) * 100
        return max(0, min(100, int(round(readiness))))

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
        """
        1. planned_session.generated_template_id → use that template directly.
        2. planned_session without linked template → pick any template that matches workout_type.
        3. no planned_session → readiness-aware HWPO weekday fallback.
        """
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
        row = db.execute(
            select(WorkoutTemplateDB).where(
                WorkoutTemplateDB.methodology == methodology,
                WorkoutTemplateDB.workout_type == workout_type,
                WorkoutTemplateDB.difficulty_level == fitness_level,
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
        adjusted = []
        for movement in movements:
            m = movement.model_copy(deep=True)
            if m.sets:
                m.sets = max(1, round(m.sets * volume_multiplier))
            if isinstance(m.reps, int):
                m.reps = max(1, round(m.reps * volume_multiplier))
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
