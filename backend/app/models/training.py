"""
Pydantic models for Training domain
"""
import logging
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Dict
import datetime as dt_module
from datetime import datetime, date, time as dt_time, timedelta
from enum import Enum
from uuid import UUID

logger = logging.getLogger(__name__)


class WorkoutType(str, Enum):
    """Workout type enumeration"""
    STRENGTH = "strength"
    METCON = "metcon"
    SKILL = "skill"
    CONDITIONING = "conditioning"
    MIXED = "mixed"


class ScoreType(str, Enum):
    """Workout score type"""
    TIME = "time"
    ROUNDS = "rounds"
    REPS = "reps"
    WEIGHT = "weight"
    DISTANCE = "distance"


class Methodology(str, Enum):
    """Training methodology"""
    HWPO = "hwpo"
    MAYHEM = "mayhem"
    COMPTRAIN = "comptrain"
    CUSTOM = "custom"


# ============================================
# Movement & Exercise Models
# ============================================

class Movement(BaseModel):
    """Individual movement in a workout"""
    movement: str = Field(..., description="Movement name (e.g., 'back_squat', 'thruster')")
    sets: Optional[int] = None
    reps: Optional[int | str] = None  # Can be '21-15-9' or int
    reps_unit: Optional[str] = Field("reps", description="Unit for reps: 'reps', 'cal', 'm'")
    weight_kg: Optional[float] = None
    distance_meters: Optional[float] = None
    duration_seconds: Optional[float] = None
    rest: Optional[str] = None  # '3min', '90s' — per-set rest (legacy AI path)
    intensity: Optional[str] = None  # '85%', 'RPE 8'
    notes: Optional[str] = None

    # Block grouping metadata — populated by cfai program projection so the
    # drawer can render movements grouped under their block (one
    # "AMRAP 10:00" header for the whole metcon, not three repeated lines).
    # Same value for every movement that belongs to the same block.
    block_id: Optional[str] = None
    block_label: Optional[str] = None        # "metcon", "strength_primary", ...
    block_prescription: Optional[str] = None # "AMRAP 10:00", "EMOM 12:00", ...
    block_intent: Optional[str] = None       # "Mixed modal triplet"
    block_rest_seconds: Optional[int] = None # rest between rounds/sets, when set


class ExerciseSet(BaseModel):
    """Individual set within a workout session"""
    set_number: int
    movement_name: str
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    distance_meters: Optional[float] = None
    duration_seconds: Optional[float] = None
    form_rating: Optional[int] = Field(None, ge=1, le=5)
    tempo: Optional[str] = None
    rest_after_seconds: Optional[int] = None
    notes: Optional[str] = None


# ============================================
# Workout Template Models
# ============================================

class WorkoutTemplateBase(BaseModel):
    """Base workout template"""
    name: str
    description: Optional[str] = None
    methodology: Methodology
    difficulty_level: str = "rx"
    workout_type: WorkoutType
    duration_minutes: Optional[int] = None
    movements: List[Movement]
    target_stimulus: Optional[str] = None
    rep_scheme: Optional[str] = None
    warm_up: Optional[str] = Field(default=None, description="Warm-up instructions for the session")
    tags: List[str] = []
    equipment_required: List[str] = []
    video_url: Optional[str] = None


class WorkoutTemplateCreate(WorkoutTemplateBase):
    """Create workout template"""
    pass


class WorkoutTemplate(WorkoutTemplateBase):
    """Workout template response"""
    id: UUID
    created_at: datetime
    is_public: bool
    created_by_coach_id: Optional[UUID] = None
    # Extra fields injected by /workouts/next endpoint (use alias to allow both names)
    next_session_date: Optional[str] = Field(default=None)
    next_session_shift: Optional[str] = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Workout Session Models
# ============================================

class WorkoutSessionBase(BaseModel):
    """Base workout session"""
    workout_type: WorkoutType
    movements: List[Movement]
    prescribed_weight_kg: Optional[Dict[str, float]] = None
    prescribed_reps: Optional[Dict[str, int]] = None
    notes: Optional[str] = None
    location: Optional[str] = "gym"


class WorkoutSessionCreate(WorkoutSessionBase):
    """Create workout session"""
    template_id: Optional[UUID] = None
    scheduled_at: Optional[datetime] = None
    allow_retroactive: bool = False  # Allow logging past workouts

    @field_validator('scheduled_at')
    @classmethod
    def validate_future_date(cls, v, info):
        """
        Validate scheduled_at date

        - For scheduled workouts (future planning): must be in future
        - For retroactive logging: can be in past if allow_retroactive=True
        """
        if not v:
            return v

        # Allow retroactive logging if flag is set
        allow_retroactive = info.data.get('allow_retroactive', False)
        if allow_retroactive:
            # For retroactive logging, allow past dates up to 30 days back
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            if v < thirty_days_ago:
                raise ValueError('Retroactive workouts must be within the last 30 days')
            return v

        # For scheduled workouts, ensure future date
        if v < datetime.utcnow():
            raise ValueError('Scheduled workouts must be in the future. Use allow_retroactive=True to log past workouts.')

        return v


class WorkoutSessionUpdate(BaseModel):
    """Update workout session (after completion or to mark incomplete)"""
    completed_at: Optional[datetime] = None
    duration_minutes: Optional[float] = None
    actual_weight_kg: Optional[Dict[str, float]] = None
    actual_reps: Optional[Dict[str, int]] = None
    score: Optional[float] = None
    score_type: Optional[ScoreType] = None
    rpe_score: Optional[int] = Field(None, ge=1, le=10)

    # Heart rate data
    avg_heart_rate_bpm: Optional[int] = None
    max_heart_rate_bpm: Optional[int] = None
    calories_burned: Optional[int] = None

    # Pre-workout metrics
    hrv_pre_workout: Optional[int] = None
    sleep_quality_pre: Optional[int] = Field(None, ge=1, le=10)

    # Post-workout
    muscle_groups_worked: List[str] = []
    video_url: Optional[str] = None


class WorkoutSession(WorkoutSessionBase):
    """Workout session response"""
    id: UUID
    user_id: int
    template_id: Optional[UUID] = None

    scheduled_at: Optional[datetime] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_minutes: Optional[float] = None

    actual_weight_kg: Optional[Dict[str, float]] = None
    actual_reps: Optional[Dict[str, int]] = None
    score: Optional[float] = None
    score_type: Optional[ScoreType] = None
    rpe_score: Optional[int] = None

    avg_heart_rate_bpm: Optional[int] = None
    max_heart_rate_bpm: Optional[int] = None
    calories_burned: Optional[int] = None

    hrv_pre_workout: Optional[int] = None
    sleep_quality_pre: Optional[int] = None

    muscle_groups_worked: List[str] = []
    video_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Workout Generation Models
# ============================================

class WorkoutGenerationRequest(BaseModel):
    """Request to generate adaptive workout"""
    user_id: Optional[int] = None  # Filled from authenticated user if not provided
    date: Optional[dt_module.date] = None  # Defaults to today if not provided
    force_rest: bool = False  # Override and force rest day


class AdaptiveWorkoutResponse(BaseModel):
    """Generated workout with volume adjustment"""
    template: WorkoutTemplate
    volume_multiplier: float = Field(..., ge=0.0, le=2.0, description="1.0 = normal, 0.8 = reduced, 1.1 = increased")
    readiness_score: int = Field(..., ge=0, le=100)
    recommendation: str
    adjusted_movements: List[Movement]
    reasoning: str = Field(..., description="Why this workout and volume")


# ============================================
# Personal Records
# ============================================

class PersonalRecordType(str, Enum):
    """PR type"""
    ONE_RM = "1rm"
    THREE_RM = "3rm"
    FIVE_RM = "5rm"
    TEN_RM = "10rm"
    MAX_REPS = "max_reps"
    BEST_TIME = "best_time"


class PersonalRecordCreate(BaseModel):
    """Create personal record"""
    movement_name: str
    record_type: PersonalRecordType
    value: float
    unit: str
    notes: Optional[str] = None
    video_url: Optional[str] = None


class PersonalRecord(PersonalRecordCreate):
    """Personal record response"""
    id: UUID
    user_id: int
    achieved_at: datetime
    session_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Periodization: Macrocycles, Microcycles, Planned Sessions
# ============================================

class DayOfWeek(str, Enum):
    """Days of the week (kept for utilities that convert between date and weekday)"""
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class BlockType(str, Enum):
    """Periodization block types"""
    ACCUMULATION = "accumulation"
    INTENSIFICATION = "intensification"
    REALIZATION = "realization"
    DELOAD = "deload"
    TEST = "test"
    TRANSITION = "transition"


class Shift(str, Enum):
    """Time-of-day shift label for a planned session"""
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    CUSTOM = "custom"


class PlannedSessionStatus(str, Enum):
    PLANNED = "planned"
    GENERATED = "generated"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class BlockPlanItem(BaseModel):
    """One block in the macrocycle's block_plan"""
    type: BlockType
    weeks: int = Field(..., ge=1, le=16)


class MacrocycleCreate(BaseModel):
    """Create a macrocycle. block_plan can be omitted — API fills from methodology default."""
    name: str = Field(..., max_length=100)
    methodology: Methodology = Methodology.HWPO
    start_date: date = Field(..., description="Any date in the starting week — server snaps to Monday")
    block_plan: Optional[List[BlockPlanItem]] = Field(
        default=None,
        description="If omitted, uses METHODOLOGY_BLOCK_PLANS default for the methodology"
    )
    goal: Optional[str] = None
    available_minutes_per_session: int = Field(default=60, ge=15, le=240, description="Default target session duration in minutes")
    training_days_per_week: int = Field(default=5, ge=1, le=7, description="How many days per week the athlete can train")


class Macrocycle(BaseModel):
    """Macrocycle API response"""
    id: UUID
    user_id: int
    name: str
    methodology: Methodology
    start_date: date
    end_date: date
    block_plan: List[BlockPlanItem]
    goal: Optional[str] = None
    available_minutes_per_session: int = 60
    training_days_per_week: int = 5
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MacrocycleUpdate(BaseModel):
    """Patch a macrocycle (extend via appended blocks, rename, change goal)"""
    name: Optional[str] = Field(None, max_length=100)
    goal: Optional[str] = None
    block_plan: Optional[List[BlockPlanItem]] = None
    active: Optional[bool] = None


class PlannedSessionCreate(BaseModel):
    """Create a planned session within a microcycle"""
    date: date
    order_in_day: int = Field(..., ge=1, le=5, description="1 = first of day, up to 5")
    shift: Optional[Shift] = None
    start_time: Optional[dt_time] = None
    duration_minutes: int = Field(60, ge=15, le=240)
    workout_type: Optional[WorkoutType] = None
    focus: Optional[str] = Field(None, description="e.g., 'heavy back squat + short metcon'")
    notes: Optional[str] = None
    status: Optional[PlannedSessionStatus] = None


class PlannedSessionUpdate(BaseModel):
    """Patch fields of a planned session"""
    shift: Optional[Shift] = None
    start_time: Optional[dt_time] = None
    duration_minutes: Optional[int] = Field(None, ge=15, le=240)
    workout_type: Optional[WorkoutType] = None
    focus: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[PlannedSessionStatus] = None


class PlannedSession(PlannedSessionCreate):
    """Planned session API response"""
    id: UUID
    microcycle_id: UUID
    user_id: int
    status: PlannedSessionStatus = PlannedSessionStatus.PLANNED
    generated_template_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SwapSessionsRequest(BaseModel):
    """Move a session to a target date, optionally swapping with the session there."""
    source_id: UUID
    target_date: date
    target_id: Optional[UUID] = None


class Microcycle(BaseModel):
    """Microcycle (1 week) API response with real dates"""
    id: UUID
    macrocycle_id: UUID
    user_id: int
    start_date: date            # Monday
    end_date: date              # Sunday
    week_index_in_macro: int
    intensity_target: Optional[str] = None
    volume_target: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    # Derived (populated by service layer, not stored)
    block_type: Optional[BlockType] = None
    week_index_in_block: Optional[int] = None
    sessions: List[PlannedSession] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MicrocycleUpdate(BaseModel):
    """Patch a microcycle (target intensity/volume, notes)"""
    intensity_target: Optional[str] = None
    volume_target: Optional[str] = None
    notes: Optional[str] = None


class MacrocycleWithMicrocycles(Macrocycle):
    """Macrocycle response with nested microcycles"""
    microcycles: List[Microcycle] = Field(default_factory=list)


# ============================================
# Meal Timing (Synced with Training)
# Weekly meal plan storage is handled in the nutrition module; this only exposes
# the building blocks that may be reused by meal-planning logic tied to planned_sessions.
# ============================================

class MealType(str, Enum):
    """Meal types"""
    PRE_WORKOUT = "pre_workout"
    POST_WORKOUT = "post_workout"
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class MealWindow(BaseModel):
    """Meal timing window"""
    meal_type: MealType
    time: dt_time
    duration_minutes: int = Field(30, ge=15, le=90)
    macros: Optional[Dict[str, float]] = Field(None, description="Target macros: {protein, carbs, fats}")
    notes: Optional[str] = None


class DailyMealPlan(BaseModel):
    """Meal plan for a single day"""
    date: date
    meals: List[MealWindow] = Field(..., min_length=1, max_length=8)
    total_calories: Optional[int] = None
    training_day: bool = True
