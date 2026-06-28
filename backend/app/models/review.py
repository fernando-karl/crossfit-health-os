"""
Pydantic models for Weekly Review and Performance Tracking
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum
from uuid import UUID


class RecoveryStatus(str, Enum):
    """Recovery assessment"""
    OPTIMAL = "optimal"
    ADEQUATE = "adequate"
    COMPROMISED = "compromised"


class VolumeAssessment(str, Enum):
    """Volume appropriateness"""
    TOO_LOW = "too_low"
    APPROPRIATE = "appropriate"
    TOO_HIGH = "too_high"


class IntensityChange(str, Enum):
    """Intensity adjustment"""
    DECREASE = "decrease"
    MAINTAIN = "maintain"
    INCREASE = "increase"


# ============================================
# Session Performance Tracking
# ============================================

class MovementPerformance(BaseModel):
    """Individual movement performance within a session"""
    movement: str
    prescribed_sets: Optional[int] = None
    prescribed_reps: Optional[int | str] = None
    prescribed_weight_kg: Optional[float] = None
    prescribed_intensity: Optional[str] = None  # "80%", "RPE 8"

    actual_sets: int
    actual_reps: List[int] = Field(default_factory=list, description="Reps per set [5,5,5,4,3]")
    actual_weight_kg: List[float] = Field(default_factory=list, description="Weight per set")

    breaks_taken: List[str] = Field(default_factory=list, description="List of break points, e.g., 'after_set_3', 'during_set_5'")
    technique_quality: Optional[int] = Field(None, ge=1, le=10, description="1-10 scale")
    notes: Optional[str] = None


class SessionFeedback(BaseModel):
    """Post-session subjective feedback"""
    session_id: UUID
    date: date

    rpe_score: int = Field(..., ge=1, le=10, description="Rate of Perceived Exertion")
    difficulty: str = Field(..., description="too_easy|appropriate|hard_but_manageable|too_hard")
    technique_quality: int = Field(..., ge=1, le=10)
    pacing: str = Field(..., description="too_fast|good|too_slow")
    energy_level_pre: int = Field(..., ge=1, le=10)
    energy_level_post: int = Field(..., ge=1, le=10)

    would_repeat: bool = True
    favorite_part: Optional[str] = None
    least_favorite_part: Optional[str] = None
    notes: Optional[str] = None

    movements_feedback: List[MovementPerformance] = Field(default_factory=list)


class SessionFeedbackCreate(SessionFeedback):
    """Create session feedback"""
    pass


class SessionFeedbackResponse(SessionFeedback):
    """Session feedback response"""
    id: UUID
    user_id: int
    created_at: datetime


# ============================================
# Weekly Review
# ============================================

class PerformanceHighlight(BaseModel):
    """Something that went well"""
    movement: str
    improvement: str
    confidence: str = Field(..., description="high|medium|low")


class PerformanceChallenge(BaseModel):
    """Area needing improvement"""
    movement: str
    issue: str
    suggested_focus: str


class NextWeekAdjustments(BaseModel):
    """AI-suggested adjustments for next week"""
    volume_change_pct: float = Field(0, ge=-50, le=50, description="% change in volume")
    intensity_change: IntensityChange
    focus_movements: List[str] = Field(default_factory=list)
    special_notes: Optional[str] = None
    add_skill_work_minutes: int = Field(0, ge=0, le=30)
    add_mobility_work: bool = False


class WeeklyReviewCreate(BaseModel):
    """Generate weekly review request"""
    week_number: int = Field(..., ge=1, le=52)
    week_start_date: date
    week_end_date: date
    athlete_notes: Optional[str] = Field(None, description="Optional feedback from athlete")


class WeeklyReview(BaseModel):
    """Complete weekly review from AI"""
    id: UUID
    user_id: int
    week_number: int
    week_start_date: date
    week_end_date: date

    # Overview
    summary: str
    planned_sessions: int
    completed_sessions: int
    adherence_rate: float = Field(..., ge=0, le=100)
    avg_rpe: float
    avg_readiness: float
    overall_satisfaction: Optional[int] = Field(None, ge=1, le=10)

    # Analysis
    strengths: List[PerformanceHighlight]
    weaknesses: List[PerformanceChallenge]
    recovery_status: RecoveryStatus
    volume_assessment: VolumeAssessment

    # Progression
    progressions_detected: List[str] = Field(default_factory=list)

    # Next week
    next_week_adjustments: NextWeekAdjustments
    coach_message: str = Field(..., description="Motivational message from AI coach")

    # Metadata
    created_at: datetime
    ai_model_used: str = Field("claude-3-5-sonnet", description="AI model used for review")
    applied: bool = False

    model_config = {"from_attributes": True}


# ============================================
# Monthly Analysis
# ============================================

class StrengthProgress(BaseModel):
    """Strength progression over time"""
    movement: str
    start_value: float
    end_value: float
    change_pct: float
    unit: str = "kg"


class ConditioningProgress(BaseModel):
    """Conditioning benchmark progress"""
    benchmark_name: str
    start_time: str  # "4:32"
    end_time: str    # "4:15"
    improvement_seconds: int


class MonthlyAnalysis(BaseModel):
    """Monthly performance trends"""
    id: UUID
    user_id: int
    month: str  # "2026-02"

    total_sessions: int
    adherence_rate: float

    strength_progress: List[StrengthProgress]
    conditioning_progress: List[ConditioningProgress]

    body_composition: Optional[Dict[str, float]] = None
    injury_report: Optional[Dict[str, Any]] = None

    volume_trend: str = Field(..., description="increasing|stable|decreasing")
    overall_assessment: str

    created_at: datetime
    ai_model_used: str = "gemini-1.5-pro"
