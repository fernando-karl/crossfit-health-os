"""
Weekly Review Engine
Analyzes athlete performance and suggests adjustments using Claude 3.5 Sonnet
"""
from datetime import date
from typing import Dict, Optional
import json
import logging

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.models.review import (
    WeeklyReview,
    PerformanceHighlight,
    PerformanceChallenge,
    NextWeekAdjustments,
    RecoveryStatus,
    VolumeAssessment,
    IntensityChange
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Macrocycle as MacrocycleDB,
    PlannedSession as PlannedSessionDB,
    RecoveryMetric as RecoveryMetricDB,
    SessionFeedback as SessionFeedbackDB,
    User as UserDB,
    WeeklyReview as WeeklyReviewDB,
    WorkoutSession as WorkoutSessionDB,
)
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class WeeklyReviewEngine:
    """
    AI-powered weekly performance review
    Uses Claude 3.5 Sonnet for deep analysis
    """

    def __init__(self):
        # Try Claude first (best for analysis), fallback to OpenAI
        self.anthropic_client = None
        self.openai_client = None

        if hasattr(settings, 'ANTHROPIC_API_KEY') and settings.ANTHROPIC_API_KEY:
            self.anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            logger.info("Weekly reviewer using Claude 3.5 Sonnet")
        elif hasattr(settings, 'OPENAI_API_KEY') and settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("Weekly reviewer using GPT-4o (fallback)")
        else:
            logger.warning("No AI API keys configured for weekly review")

    async def generate_weekly_review(
        self,
        user_id: int,
        week_number: int,
        week_start: date,
        week_end: date,
        athlete_notes: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> WeeklyReview:
        """
        Generate comprehensive weekly review with AI analysis

        Args:
            user_id: User UUID
            week_number: Week number in mesocycle
            week_start: Start date of week
            week_end: End date of week
            athlete_notes: Optional feedback from athlete

        Returns:
            WeeklyReview object with analysis and recommendations
        """
        owns_session = db is None
        if db is None:
            db = SessionLocal()

        try:
            # Collect all data for the week
            weekly_data = self._collect_weekly_data(db, user_id, week_start, week_end)

            # Get user profile
            user_profile = self._get_user_profile(db, user_id)

            # Generate review using AI
            if self.anthropic_client:
                review_data = await self._generate_review_claude(
                    user_profile, weekly_data, week_number, athlete_notes
                )
                model_used = "claude-3-5-sonnet"
            elif self.openai_client:
                review_data = await self._generate_review_openai(
                    user_profile, weekly_data, week_number, athlete_notes
                )
                model_used = "gpt-4o"
            else:
                review_data = self._generate_review_fallback(weekly_data, week_number)
                model_used = "rule-based"

            # Build review and persist
            saved_review = self._save_review(
                db=db,
                user_id=user_id,
                week_number=week_number,
                week_start=week_start,
                week_end=week_end,
                review_data=review_data,
                model_used=model_used,
            )
            return saved_review
        finally:
            if owns_session:
                db.close()

    def _collect_weekly_data(
        self,
        db: Session,
        user_id: int,
        week_start: date,
        week_end: date,
    ) -> Dict:
        """Collect sessions, recovery, feedback for the week."""
        from datetime import datetime as _dt

        sessions = db.execute(
            select(WorkoutSessionDB).where(
                WorkoutSessionDB.user_id == user_id,
                WorkoutSessionDB.started_at >= _dt.combine(week_start, _dt.min.time()),
                WorkoutSessionDB.started_at <= _dt.combine(week_end, _dt.max.time()),
            )
        ).scalars().all()

        recovery = db.execute(
            select(RecoveryMetricDB).where(
                RecoveryMetricDB.user_id == user_id,
                RecoveryMetricDB.date >= week_start,
                RecoveryMetricDB.date <= week_end,
            )
        ).scalars().all()

        feedback = db.execute(
            select(SessionFeedbackDB).where(
                SessionFeedbackDB.user_id == user_id,
                SessionFeedbackDB.date >= week_start,
                SessionFeedbackDB.date <= week_end,
            )
        ).scalars().all()

        planned_count = db.execute(
            select(PlannedSessionDB).where(
                PlannedSessionDB.user_id == user_id,
                PlannedSessionDB.date >= week_start,
                PlannedSessionDB.date <= week_end,
            )
        ).scalars().all()

        completed = len([s for s in sessions if s.completed_at])
        planned_total = len(planned_count) or len(sessions)

        rpe_scores = [f.rpe_score for f in feedback if f.rpe_score]
        rpe_scores.extend([s.rpe_score for s in sessions if s.rpe_score])
        avg_rpe = sum(rpe_scores) / len(rpe_scores) if rpe_scores else 7
        avg_readiness = (
            sum((r.readiness_score or 70) for r in recovery) / len(recovery)
            if recovery else 70
        )

        return {
            "sessions": [_ws_to_dict(s) for s in sessions],
            "recovery_metrics": [_rm_to_dict(r) for r in recovery],
            "feedback": [_fb_to_dict(f) for f in feedback],
            "planned_sessions": planned_total,
            "completed_sessions": completed,
            "adherence_rate": (completed / planned_total * 100) if planned_total else 0,
            "avg_rpe": avg_rpe,
            "avg_readiness": avg_readiness,
        }

    def _get_user_profile(self, db: Session, user_id: int) -> Dict:
        user = db.get(UserDB, user_id)
        if not user:
            return {}
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "fitness_level": user.fitness_level,
            "weight_kg": user.weight_kg,
            "goals": user.goals or [],
            "preferences": user.preferences or {},
        }

    async def _generate_review_claude(
        self,
        user_profile: Dict,
        weekly_data: Dict,
        week_number: int,
        athlete_notes: Optional[str]
    ) -> Dict:
        """
        Generate review using Claude 3.5 Sonnet
        """
        prompt = self._build_review_prompt(user_profile, weekly_data, week_number, athlete_notes)

        try:
            response = await self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                temperature=0.7,
                system=self._get_coach_system_prompt(),
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            # Parse response
            review_text = response.content[0].text

            # Extract JSON from markdown code block if present
            if "```json" in review_text:
                json_start = review_text.find("```json") + 7
                json_end = review_text.find("```", json_start)
                review_text = review_text[json_start:json_end].strip()

            review_data = json.loads(review_text)

            return self._parse_review_response(review_data, weekly_data)

        except Exception as e:
            logger.error(f"Failed to generate review with Claude: {e}", exc_info=True)
            return self._generate_review_fallback(weekly_data, week_number)

    async def _generate_review_openai(
        self,
        user_profile: Dict,
        weekly_data: Dict,
        week_number: int,
        athlete_notes: Optional[str]
    ) -> Dict:
        """
        Fallback: Generate review using GPT-4o
        """
        prompt = self._build_review_prompt(user_profile, weekly_data, week_number, athlete_notes)

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": self._get_coach_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )

            review_data = json.loads(response.choices[0].message.content)

            return self._parse_review_response(review_data, weekly_data)

        except Exception as e:
            logger.error(f"Failed to generate review with GPT-4: {e}", exc_info=True)
            return self._generate_review_fallback(weekly_data, week_number)

    def _get_coach_system_prompt(self) -> str:
        """System prompt for AI coach"""
        return """You are an elite CrossFit coach analyzing athlete performance for a weekly review.

Your role:
1. Analyze workout completion, RPE, and recovery metrics
2. Identify 2-3 specific strengths (movements, skills improving)
3. Identify 2-3 areas needing attention (technique issues, stagnation)
4. Assess recovery status (HRV, sleep, readiness scores)
5. Determine if volume/intensity were appropriate
6. Suggest specific adjustments for next week
7. Provide motivational, personalized coaching message

Communication style:
- Be specific and evidence-based
- Use athlete's name if available
- Balance encouragement with honest assessment
- Provide actionable recommendations
- Keep coach message under 200 words

Return structured JSON with your analysis."""

    def _resolve_phase(self, db: Session, user_id: int, week_number: int) -> str:
        macro = db.execute(
            select(MacrocycleDB).where(
                MacrocycleDB.user_id == user_id,
                MacrocycleDB.active.is_(True),
            ).limit(1)
        ).scalar_one_or_none()
        if macro and macro.block_plan:
            cumulative = 0
            for block in macro.block_plan:
                weeks = int(block.get("weeks", 1))
                cumulative += weeks
                if week_number <= cumulative:
                    return str(block.get("type", "accumulation")).replace("_", " ").title()
        if week_number <= 3:
            return "Accumulation"
        if week_number == 4:
            return "Deload"
        if week_number <= 7:
            return "Intensification"
        return "Test Week"

    def _resolve_phase_for_review(self, user_profile: Dict, week_number: int) -> str:
        user_id = user_profile.get("id")
        if user_id:
            with SessionLocal() as db:
                return self._resolve_phase(db, int(user_id), week_number)
        if week_number <= 3:
            return "Accumulation"
        if week_number == 4:
            return "Deload"
        if week_number <= 7:
            return "Intensification"
        return "Test Week"

    def _build_review_prompt(
        self,
        user_profile: Dict,
        weekly_data: Dict,
        week_number: int,
        athlete_notes: Optional[str]
    ) -> str:
        """Build prompt for AI review"""

        phase = self._resolve_phase_for_review(user_profile, week_number)

        prompt = f"""Analyze this athlete's Week {week_number} ({phase} phase) performance:

ATHLETE PROFILE:
- Name: {user_profile.get('name', 'Athlete')}
- Level: {user_profile.get('fitness_level', 'intermediate')}
- Goals: {json.dumps(user_profile.get('preferences', {}).get('goals', []))}
- Weaknesses: {json.dumps(user_profile.get('preferences', {}).get('weaknesses', []))}

WEEK SUMMARY:
- Planned sessions: {weekly_data['planned_sessions']}
- Completed: {weekly_data['completed_sessions']}
- Adherence: {weekly_data['adherence_rate']:.1f}%
- Avg RPE: {weekly_data['avg_rpe']:.1f}/10
- Avg Readiness: {weekly_data['avg_readiness']:.1f}/100

SESSIONS:
{json.dumps(weekly_data['sessions'], indent=2, default=str)}

RECOVERY METRICS:
{json.dumps(weekly_data['recovery_metrics'], indent=2, default=str)}

ATHLETE FEEDBACK:
{json.dumps(weekly_data['feedback'], indent=2, default=str)}
{f"Additional notes: {athlete_notes}" if athlete_notes else ""}

Provide review in this JSON format:
{{
  "summary": "Brief 2-3 sentence overview",
  "strengths": [
    {{"movement": "back_squat", "improvement": "Increased working weight 2kg", "confidence": "high"}},
    {{"movement": "muscle_up", "improvement": "First unbroken sets", "confidence": "medium"}}
  ],
  "weaknesses": [
    {{"movement": "handstand_walk", "issue": "Balance inconsistent", "suggested_focus": "Add 10min skill work 3x/week"}}
  ],
  "recovery_status": "optimal|adequate|compromised",
  "volume_assessment": "appropriate|too_high|too_low",
  "progressions_detected": ["Back squat +2kg", "Fran -8 seconds"],
  "next_week_adjustments": {{
    "volume_change_pct": 0,
    "intensity_change": "maintain|increase|decrease",
    "focus_movements": ["handstand_walk", "snatch"],
    "special_notes": "Week 4 deload - reduce volume 40%",
    "add_skill_work_minutes": 10,
    "add_mobility_work": true
  }},
  "coach_message": "Personalized, motivational message addressing specific performance"
}}"""

        return prompt

    def _parse_review_response(self, review_data: Dict, weekly_data: Dict) -> Dict:
        """Parse AI response into WeeklyReview fields"""

        # Parse strengths
        strengths = [
            PerformanceHighlight(**s) for s in review_data.get("strengths", [])
        ]

        # Parse weaknesses
        weaknesses = [
            PerformanceChallenge(**w) for w in review_data.get("weaknesses", [])
        ]

        # Parse adjustments
        adjustments_data = review_data.get("next_week_adjustments", {})
        next_week_adjustments = NextWeekAdjustments(
            volume_change_pct=adjustments_data.get("volume_change_pct", 0),
            intensity_change=IntensityChange(adjustments_data.get("intensity_change", "maintain")),
            focus_movements=adjustments_data.get("focus_movements", []),
            special_notes=adjustments_data.get("special_notes"),
            add_skill_work_minutes=adjustments_data.get("add_skill_work_minutes", 0),
            add_mobility_work=adjustments_data.get("add_mobility_work", False)
        )

        return {
            "summary": review_data.get("summary", "Week completed successfully."),
            "planned_sessions": weekly_data["planned_sessions"],
            "completed_sessions": weekly_data["completed_sessions"],
            "adherence_rate": weekly_data["adherence_rate"],
            "avg_rpe": weekly_data["avg_rpe"],
            "avg_readiness": weekly_data["avg_readiness"],
            "overall_satisfaction": None,  # From athlete feedback if available
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recovery_status": RecoveryStatus(review_data.get("recovery_status", "adequate")),
            "volume_assessment": VolumeAssessment(review_data.get("volume_assessment", "appropriate")),
            "progressions_detected": review_data.get("progressions_detected", []),
            "next_week_adjustments": next_week_adjustments,
            "coach_message": review_data.get("coach_message", "Keep up the great work!")
        }

    def _generate_review_fallback(self, weekly_data: Dict, week_number: int) -> Dict:
        """Rule-based fallback review"""

        adherence = weekly_data["adherence_rate"]
        avg_rpe = weekly_data["avg_rpe"]
        avg_readiness = weekly_data["avg_readiness"]

        # Simple rule-based assessment
        if adherence >= 90:
            summary = f"Excellent adherence this week ({adherence:.0f}%). "
        elif adherence >= 70:
            summary = f"Good adherence ({adherence:.0f}%). "
        else:
            summary = f"Low adherence ({adherence:.0f}%). Consider adjusting schedule. "

        if avg_rpe > 8:
            summary += "High RPE suggests volume may be too high."
            volume_assessment = VolumeAssessment.TOO_HIGH
        elif avg_rpe < 6:
            summary += "Low RPE suggests room to increase intensity."
            volume_assessment = VolumeAssessment.TOO_LOW
        else:
            summary += "RPE indicates appropriate training load."
            volume_assessment = VolumeAssessment.APPROPRIATE

        if avg_readiness < 60:
            recovery_status = RecoveryStatus.COMPROMISED
        elif avg_readiness < 75:
            recovery_status = RecoveryStatus.ADEQUATE
        else:
            recovery_status = RecoveryStatus.OPTIMAL

        return {
            "summary": summary,
            "planned_sessions": weekly_data["planned_sessions"],
            "completed_sessions": weekly_data["completed_sessions"],
            "adherence_rate": adherence,
            "avg_rpe": avg_rpe,
            "avg_readiness": avg_readiness,
            "overall_satisfaction": None,
            "strengths": [],
            "weaknesses": [],
            "recovery_status": recovery_status,
            "volume_assessment": volume_assessment,
            "progressions_detected": [],
            "next_week_adjustments": NextWeekAdjustments(
                volume_change_pct=0,
                intensity_change=IntensityChange.MAINTAIN,
                focus_movements=[],
                special_notes="AI review unavailable. Manual review recommended."
            ),
            "coach_message": f"Week {week_number} completed. Keep training consistently!"
        }

    def _save_review(
        self,
        db: Session,
        user_id: int,
        week_number: int,
        week_start: date,
        week_end: date,
        review_data: Dict,
        model_used: str,
    ) -> WeeklyReview:
        """Persist review row + return API schema."""
        def _to_json(value):
            if value is None:
                return None
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json")
            if isinstance(value, list):
                return [_to_json(v) for v in value]
            return value

        next_adj = review_data.get("next_week_adjustments")
        adjustments_json = _to_json(next_adj) or {}

        row = WeeklyReviewDB(
            user_id=user_id,
            week_number=week_number,
            week_start_date=week_start,
            week_end_date=week_end,
            summary=review_data.get("summary", ""),
            planned_sessions=review_data.get("planned_sessions", 0),
            completed_sessions=review_data.get("completed_sessions", 0),
            adherence_rate=review_data.get("adherence_rate", 0),
            avg_rpe=review_data.get("avg_rpe", 0),
            avg_readiness=review_data.get("avg_readiness", 0),
            overall_satisfaction=review_data.get("overall_satisfaction"),
            strengths=_to_json(review_data.get("strengths", [])) or [],
            weaknesses=_to_json(review_data.get("weaknesses", [])) or [],
            recovery_status=(review_data.get("recovery_status").value
                             if hasattr(review_data.get("recovery_status"), "value")
                             else review_data.get("recovery_status", "adequate")),
            volume_assessment=(review_data.get("volume_assessment").value
                               if hasattr(review_data.get("volume_assessment"), "value")
                               else review_data.get("volume_assessment", "appropriate")),
            progressions_detected=review_data.get("progressions_detected", []),
            next_week_adjustments=adjustments_json,
            coach_message=review_data.get("coach_message", ""),
            ai_model_used=model_used,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Build API schema from row
        return WeeklyReview(
            id=row.id,
            user_id=row.user_id,
            week_number=row.week_number,
            week_start_date=row.week_start_date,
            week_end_date=row.week_end_date,
            summary=row.summary,
            planned_sessions=row.planned_sessions,
            completed_sessions=row.completed_sessions,
            adherence_rate=row.adherence_rate,
            avg_rpe=row.avg_rpe,
            avg_readiness=row.avg_readiness,
            overall_satisfaction=row.overall_satisfaction,
            strengths=[PerformanceHighlight(**s) for s in (row.strengths or [])],
            weaknesses=[PerformanceChallenge(**w) for w in (row.weaknesses or [])],
            recovery_status=RecoveryStatus(row.recovery_status),
            volume_assessment=VolumeAssessment(row.volume_assessment),
            progressions_detected=row.progressions_detected or [],
            next_week_adjustments=NextWeekAdjustments(**(row.next_week_adjustments or {})),
            coach_message=row.coach_message,
            created_at=row.created_at,
            ai_model_used=row.ai_model_used,
        )


# -------- DB→dict adapters (kept at module level so the engine methods stay tidy) --------

def _ws_to_dict(s) -> dict:
    return {
        "id": str(s.id),
        "user_id": s.user_id,
        "workout_type": s.workout_type,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "duration_minutes": s.duration_minutes,
        "rpe_score": s.rpe_score,
        "score": s.score,
    }


def _rm_to_dict(r) -> dict:
    return {
        "id": str(r.id),
        "user_id": r.user_id,
        "date": r.date.isoformat() if r.date else None,
        "sleep_quality": r.sleep_quality,
        "hrv_ms": r.hrv_ms,
        "stress_level": r.stress_level,
        "readiness_score": r.readiness_score,
    }


def _fb_to_dict(f) -> dict:
    return {
        "id": str(f.id),
        "user_id": f.user_id,
        "session_id": str(f.session_id),
        "date": f.date.isoformat() if f.date else None,
        "rpe_score": f.rpe_score,
        "difficulty": f.difficulty,
        "technique_quality": f.technique_quality,
    }


# Global instance
weekly_reviewer = WeeklyReviewEngine()
