"""
SQLModel entities — the single source of truth for DB schema.

Tables covered by this module:
- users (matches auth.py schema)
- workout_templates, workout_sessions, recovery_metrics (minimal shells used
  by the scheduling/engines path; richer structure can be added incrementally)
- macrocycles, microcycles, planned_sessions (periodization)

Everything else in `infra/supabase/migrations/*.sql` remains on the Supabase
side for now — this module only covers what the SQLAlchemy-migrated layer needs
to read/write today.

"""
from __future__ import annotations

from datetime import date as _Date, datetime as _Datetime, time as _Time
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, JSON, SQLModel


# ==========================================================
# JSON column helper: JSONB on Postgres, JSON on SQLite (tests)
# ==========================================================

def _json_column(**kwargs) -> Column:
    return Column(JSON().with_variant(JSONB(), "postgresql"), **kwargs)


# ==========================================================
# User (mirrors app/api/v1/auth.py init_db)
# ==========================================================

class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(sa_column_kwargs={"unique": True}, max_length=255)
    password_hash: str = Field(max_length=255)
    name: str = Field(max_length=255)
    birth_date: Optional[_Date] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    fitness_level: str = Field(default="beginner", max_length=50)
    goals: List[str] = Field(default_factory=list, sa_column=_json_column())
    timezone: str = Field(default="America/Sao_Paulo", max_length=64)
    locale: Optional[str] = Field(default=None, max_length=10)
    preferences: dict = Field(default_factory=dict, sa_column=_json_column())
    # Subscription / trial state. Set at signup; flipped by Stripe webhooks
    # once payments are wired. `subscription_status` values:
    # trialing | active | past_due | canceled.
    trial_started_at: Optional[_Datetime] = None
    trial_expires_at: Optional[_Datetime] = None
    subscription_status: str = Field(default="trialing", max_length=20)
    stripe_customer_id: Optional[str] = Field(default=None, max_length=64)
    subscription_id: Optional[str] = Field(default=None, max_length=64)
    # LGPD/GDPR consent record — captured at signup, versioned so we can
    # re-prompt when terms change.
    terms_accepted_at: Optional[_Datetime] = None
    terms_version: Optional[str] = Field(default=None, max_length=16)
    privacy_version: Optional[str] = Field(default=None, max_length=16)
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    updated_at: _Datetime = Field(default_factory=_Datetime.utcnow)


# ==========================================================
# Workout templates / sessions / recovery — minimal shells
# ==========================================================

class WorkoutTemplate(SQLModel, table=True):
    __tablename__ = "workout_templates"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    name: str
    description: Optional[str] = None
    methodology: str = Field(max_length=20)
    difficulty_level: str = Field(default="rx", max_length=20)
    workout_type: str = Field(max_length=20)
    duration_minutes: Optional[int] = None
    movements: List[dict] = Field(default_factory=list, sa_column=_json_column())
    target_stimulus: Optional[str] = None
    rep_scheme: Optional[str] = None
    warm_up: Optional[str] = None
    tags: List[str] = Field(default_factory=list, sa_column=_json_column())
    equipment_required: List[str] = Field(default_factory=list, sa_column=_json_column())
    is_public: bool = False
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class WorkoutSession(SQLModel, table=True):
    __tablename__ = "workout_sessions"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    template_id: Optional[UUID] = Field(default=None, foreign_key="workout_templates.id")
    planned_session_id: Optional[UUID] = Field(default=None, foreign_key="planned_sessions.id")

    scheduled_at: Optional[_Datetime] = None
    started_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    completed_at: Optional[_Datetime] = None
    duration_minutes: Optional[float] = None

    workout_type: str = Field(max_length=20)
    score: Optional[float] = None
    rpe_score: Optional[int] = None
    notes: Optional[str] = None


class RecoveryMetric(SQLModel, table=True):
    __tablename__ = "recovery_metrics"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_recovery_user_date"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    date: _Date = Field(index=True)
    sleep_duration_hours: Optional[float] = None
    sleep_quality: Optional[int] = None  # 1-10
    hrv_ms: Optional[int] = None
    resting_heart_rate_bpm: Optional[int] = None
    stress_level: Optional[int] = None
    muscle_soreness: Optional[int] = None
    energy_level: Optional[int] = None
    readiness_score: Optional[int] = None
    notes: Optional[str] = None
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)


# ==========================================================
# Periodization: macrocycles → microcycles → planned_sessions
# ==========================================================

class Macrocycle(SQLModel, table=True):
    __tablename__ = "macrocycles"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=100)
    methodology: str = Field(max_length=20)  # hwpo/mayhem/comptrain/custom
    start_date: _Date  # always a Monday (server-snapped)
    end_date: _Date
    # List[{"type": "accumulation", "weeks": 3}, ...]
    block_plan: List[dict] = Field(default_factory=list, sa_column=_json_column())
    goal: Optional[str] = None
    # Training availability settings
    available_minutes_per_session: int = Field(
        default=60,
        ge=15, le=240,
        description="Default target session duration in minutes"
    )
    training_days_per_week: int = Field(
        default=5, ge=1, le=7,
        description="How many days per week the athlete can train"
    )
    active: bool = True
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    updated_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class Microcycle(SQLModel, table=True):
    __tablename__ = "microcycles"
    __table_args__ = (
        UniqueConstraint("macrocycle_id", "week_index_in_macro", name="uq_micro_macro_week"),
        Index("idx_micro_user_date", "user_id", "start_date"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    macrocycle_id: UUID = Field(foreign_key="macrocycles.id", ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id")

    start_date: _Date  # Monday
    end_date: _Date    # Sunday
    week_index_in_macro: int

    intensity_target: Optional[str] = Field(default=None, max_length=20)
    volume_target: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = None
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class Program(SQLModel, table=True):
    """cfai-generated mesocycle program. Stores the full Mesocycle as JSONB."""
    __tablename__ = "programs"
    __table_args__ = (
        Index("idx_programs_user_created", "user_id", "created_at"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    macrocycle_id: Optional[UUID] = Field(default=None, foreign_key="macrocycles.id")

    name: str = Field(max_length=200)
    composer_used: str = Field(max_length=40)  # heuristic / hybrid_openai / ...
    phase: str = Field(max_length=20)          # mesocycle root phase
    start_date: _Date
    duration_weeks: int
    sessions_per_week: int = 5

    primary_focus: List[str] = Field(default_factory=list, sa_column=_json_column())
    spec: dict = Field(default_factory=dict, sa_column=_json_column())  # MesocycleSpec
    athlete_snapshot: dict = Field(default_factory=dict, sa_column=_json_column())
    mesocycle: dict = Field(default_factory=dict, sa_column=_json_column())  # full cfai Mesocycle
    generation_metadata: dict = Field(default_factory=dict, sa_column=_json_column())

    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    updated_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class PlannedSession(SQLModel, table=True):
    __tablename__ = "planned_sessions"
    __table_args__ = (
        UniqueConstraint("microcycle_id", "date", "order_in_day", name="uq_planned_micro_date_order"),
        Index("idx_planned_user_date", "user_id", "date"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    microcycle_id: UUID = Field(foreign_key="microcycles.id", ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id")

    date: _Date
    order_in_day: int  # 1..5
    shift: Optional[str] = Field(default=None, max_length=20)
    start_time: Optional[_Time] = None
    duration_minutes: Optional[int] = None
    workout_type: Optional[str] = Field(default=None, max_length=20)
    focus: Optional[str] = None
    notes: Optional[str] = None
    status: str = Field(default="planned", max_length=20)
    generated_template_id: Optional[UUID] = Field(default=None, foreign_key="workout_templates.id")

    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    updated_at: _Datetime = Field(default_factory=_Datetime.utcnow)


# ==========================================================
# Gamification: user_stats + user_badges
# ==========================================================

class UserStatsRow(SQLModel, table=True):
    __tablename__ = "user_stats"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    xp: int = 0
    level: int = 1
    current_streak: int = 0
    longest_streak: int = 0
    last_workout_date: Optional[_Date] = None
    updated_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class UserBadge(SQLModel, table=True):
    __tablename__ = "user_badges"
    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    badge_id: str = Field(max_length=40)
    earned_at: _Datetime = Field(default_factory=_Datetime.utcnow)


# ==========================================================
# Notifications
# ==========================================================

class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    type: str = Field(max_length=40)
    title: str
    body: str
    data: dict = Field(default_factory=dict, sa_column=_json_column())
    read: bool = False
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow, index=True)


# ==========================================================
# HealthKit raw data dump
# ==========================================================

class HealthkitData(SQLModel, table=True):
    __tablename__ = "healthkit_data"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    synced_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    data_type: str = Field(max_length=40)
    start_date: _Datetime
    end_date: _Datetime
    data: dict = Field(default_factory=dict, sa_column=_json_column())
    device_name: Optional[str] = Field(default=None, max_length=80)
    source_app: Optional[str] = Field(default=None, max_length=80)


# ==========================================================
# Custom diet plans (user-uploaded)
# ==========================================================

class UserDietPlan(SQLModel, table=True):
    __tablename__ = "user_diet_plans"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    file_name: Optional[str] = Field(default=None, max_length=255)
    file_url: Optional[str] = None
    daily_calories: Optional[int] = None
    protein_g: Optional[int] = None
    carbs_g: Optional[int] = None
    fat_g: Optional[int] = None
    meals: List[dict] = Field(default_factory=list, sa_column=_json_column())
    supplements: List[str] = Field(default_factory=list, sa_column=_json_column())
    notes: Optional[str] = None
    parsed_data: dict = Field(default_factory=dict, sa_column=_json_column())
    uploaded_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    active: bool = True


# ==========================================================
# Weekly reviews & session feedback
# ==========================================================

class SessionFeedback(SQLModel, table=True):
    __tablename__ = "session_feedback"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    session_id: UUID = Field(foreign_key="workout_sessions.id", index=True)
    date: _Date = Field(index=True)

    rpe_score: int
    difficulty: str = Field(max_length=30)
    technique_quality: int
    pacing: str = Field(max_length=20)
    energy_level_pre: int
    energy_level_post: int
    would_repeat: bool = True
    favorite_part: Optional[str] = None
    least_favorite_part: Optional[str] = None
    notes: Optional[str] = None

    movements_feedback: List[dict] = Field(default_factory=list, sa_column=_json_column())
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class WeeklyReview(SQLModel, table=True):
    __tablename__ = "weekly_reviews"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    week_number: int
    week_start_date: _Date
    week_end_date: _Date

    summary: str
    planned_sessions: int = 0
    completed_sessions: int = 0
    adherence_rate: float = 0.0
    avg_rpe: float = 0.0
    avg_readiness: float = 0.0
    overall_satisfaction: Optional[int] = None

    strengths: List[dict] = Field(default_factory=list, sa_column=_json_column())
    weaknesses: List[dict] = Field(default_factory=list, sa_column=_json_column())
    recovery_status: str = Field(max_length=20)
    volume_assessment: str = Field(max_length=20)

    progressions_detected: List[str] = Field(default_factory=list, sa_column=_json_column())
    next_week_adjustments: dict = Field(default_factory=dict, sa_column=_json_column())
    coach_message: str

    created_at: _Datetime = Field(default_factory=_Datetime.utcnow, index=True)
    ai_model_used: str = Field(default="claude-3-5-sonnet", max_length=50)


# ==========================================================
# Meal logs
# ==========================================================

class MealLog(SQLModel, table=True):
    __tablename__ = "meal_logs"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    logged_at: _Datetime = Field(default_factory=_Datetime.utcnow, index=True)
    meal_type: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    foods: List[dict] = Field(default_factory=list, sa_column=_json_column())
    photo_url: Optional[str] = None
    ai_estimation: bool = False
    notes: Optional[str] = None


# ==========================================================
# Biomarker readings
# ==========================================================

class BiomarkerReading(SQLModel, table=True):
    __tablename__ = "biomarker_readings"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    biomarker_name: str = Field(max_length=100)
    value: Optional[float] = None
    unit: str = Field(default="", max_length=50)
    reference_min: Optional[float] = None
    reference_max: Optional[float] = None
    status: str = Field(default="normal", max_length=20)  # normal/low/high/critical
    category: str = Field(default="other", max_length=50)
    test_date: _Date = Field(index=True)
    lab_name: Optional[str] = None
    source: Optional[str] = Field(default=None, max_length=20)  # ocr_upload/manual/api
    pdf_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)


# ==========================================================
# Injuries / movement restrictions (drafted; not yet consumed by AI prompts)
# ==========================================================


class Injury(SQLModel, table=True):
    __tablename__ = "injuries"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    body_part: str = Field(max_length=50)  # "left_knee", "lower_back", "right_shoulder"
    description: Optional[str] = None
    # Movement-pattern tags to exclude when programming, e.g.
    # ["jumping", "overhead_pressing", "deep_squat", "running"]. Consumed by the
    # AI programmer prompt as exclusion filters once wired.
    restriction_tags: List[str] = Field(default_factory=list, sa_column=_json_column())
    severity: str = Field(default="moderate", max_length=20)  # mild/moderate/severe
    started_at: _Date
    resolved_at: Optional[_Date] = None
    notes: Optional[str] = None
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    updated_at: _Datetime = Field(default_factory=_Datetime.utcnow)


# ==========================================================
# Personal Records
# ==========================================================

class PersonalRecord(SQLModel, table=True):
    __tablename__ = "personal_records"
    __table_args__ = (
        UniqueConstraint("user_id", "movement_name", "record_type", name="uq_pr_user_movement_record"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    movement_name: str = Field(max_length=100)
    record_type: str = Field(max_length=20)  # 1rm/3rm/5rm/10rm/max_reps/best_time
    value: float
    unit: str = Field(max_length=20)
    achieved_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    session_id: Optional[UUID] = Field(default=None, foreign_key="workout_sessions.id")
    notes: Optional[str] = None
    video_url: Optional[str] = None


# ==========================================================
# Referrals: user-to-user invite codes + conversion tracking
# ==========================================================

class ReferralCode(SQLModel, table=True):
    __tablename__ = "referral_codes"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    code: str = Field(max_length=24, sa_column_kwargs={"unique": True})
    active: bool = Field(default=True)
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)


class Referral(SQLModel, table=True):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_referral_referee"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    code_id: UUID = Field(foreign_key="referral_codes.id", index=True)
    referred_user_id: int = Field(foreign_key="users.id")
    status: str = Field(default="pending", max_length=20)  # pending / converted
    created_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    converted_at: Optional[_Datetime] = None


# ==========================================================
# Refresh tokens — rotation chain w/ reuse detection
# ==========================================================

class RefreshToken(SQLModel, table=True):
    """One row per issued refresh token.

    The raw token is **never** stored — only its sha256 hash. A new pair
    is issued on each ``/auth/refresh`` call; the old row is updated with
    ``replaced_by_id`` so we can detect reuse (theft scenario): if a row
    flagged as replaced is presented again, we revoke the entire family.
    """
    __tablename__ = "refresh_tokens"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(max_length=64, sa_column_kwargs={"unique": True})
    issued_at: _Datetime = Field(default_factory=_Datetime.utcnow)
    expires_at: _Datetime
    revoked_at: Optional[_Datetime] = None
    replaced_by_id: Optional[UUID] = Field(default=None, foreign_key="refresh_tokens.id")
    user_agent: Optional[str] = Field(default=None, max_length=255)
    ip: Optional[str] = Field(default=None, max_length=64)


__all__ = [
    "User",
    "WorkoutTemplate",
    "WorkoutSession",
    "RecoveryMetric",
    "Macrocycle",
    "Microcycle",
    "PlannedSession",
    "Program",
    "PersonalRecord",
    "BiomarkerReading",
    "MealLog",
    "SessionFeedback",
    "WeeklyReview",
    "UserStatsRow",
    "UserBadge",
    "HealthkitData",
    "UserDietPlan",
    "Notification",
    "Injury",
    "ReferralCode",
    "Referral",
    "RefreshToken",
]
