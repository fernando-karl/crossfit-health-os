"""
Weekly Review & Session Feedback API (SQLAlchemy).
"""
from typing import List
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_active_subscription
from app.core.rate_limit import limiter
from app.core.engine.weekly_reviewer import weekly_reviewer
from app.db.models import (
    Macrocycle as MacrocycleDB,
    Microcycle as MicrocycleDB,
    SessionFeedback as SessionFeedbackDB,
    WeeklyReview as WeeklyReviewDB,
    WorkoutSession as WorkoutSessionDB,
)
from app.db.session import get_session
from app.models.review import (
    NextWeekAdjustments,
    PerformanceChallenge,
    PerformanceHighlight,
    RecoveryStatus,
    SessionFeedbackCreate,
    SessionFeedbackResponse,
    VolumeAssessment,
    WeeklyReview,
    WeeklyReviewCreate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _fb_to_schema(row: SessionFeedbackDB) -> SessionFeedbackResponse:
    return SessionFeedbackResponse(
        id=row.id,
        user_id=row.user_id,
        session_id=row.session_id,
        date=row.date,
        rpe_score=row.rpe_score,
        difficulty=row.difficulty,
        technique_quality=row.technique_quality,
        pacing=row.pacing,
        energy_level_pre=row.energy_level_pre,
        energy_level_post=row.energy_level_post,
        would_repeat=row.would_repeat,
        favorite_part=row.favorite_part,
        least_favorite_part=row.least_favorite_part,
        notes=row.notes,
        movements_feedback=row.movements_feedback or [],
        created_at=row.created_at,
    )


def _wr_to_schema(row: WeeklyReviewDB) -> WeeklyReview:
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
        applied=bool((row.next_week_adjustments or {}).get("_applied")),
    )


# ==========================================================
# Session Feedback
# ==========================================================

@router.post("/feedback", response_model=SessionFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_session_feedback(
    feedback: SessionFeedbackCreate,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Submit post-workout feedback for a session the user owns."""
    user_id = int(current_user["id"])

    session_row = db.get(WorkoutSessionDB, feedback.session_id)
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    row = SessionFeedbackDB(
        user_id=user_id,
        session_id=feedback.session_id,
        date=feedback.date,
        rpe_score=feedback.rpe_score,
        difficulty=feedback.difficulty,
        technique_quality=feedback.technique_quality,
        pacing=feedback.pacing,
        energy_level_pre=feedback.energy_level_pre,
        energy_level_post=feedback.energy_level_post,
        would_repeat=feedback.would_repeat,
        favorite_part=feedback.favorite_part,
        least_favorite_part=feedback.least_favorite_part,
        notes=feedback.notes,
        movements_feedback=[m.model_dump(mode="json") for m in (feedback.movements_feedback or [])],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _fb_to_schema(row)


@router.get("/feedback/{session_id}", response_model=SessionFeedbackResponse)
async def get_session_feedback(
    session_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.execute(
        select(SessionFeedbackDB).where(
            SessionFeedbackDB.session_id == session_id,
            SessionFeedbackDB.user_id == user_id,
        ).limit(1)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return _fb_to_schema(row)


@router.get("/feedback", response_model=List[SessionFeedbackResponse])
async def list_feedback(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = db.execute(
        select(SessionFeedbackDB)
        .where(SessionFeedbackDB.user_id == user_id)
        .order_by(SessionFeedbackDB.date.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [_fb_to_schema(r) for r in rows]


# ==========================================================
# Weekly review
# ==========================================================

@router.post("/weekly", response_model=WeeklyReview)
@limiter.limit("10/hour")
async def generate_weekly_review(
    request: Request,
    payload: WeeklyReviewCreate,
    db: Session = Depends(get_session),
    current_user: dict = Depends(require_active_subscription),
):
    user_id = int(current_user["id"])
    try:
        review = await weekly_reviewer.generate_weekly_review(
            user_id=user_id,
            week_number=payload.week_number,
            week_start=payload.week_start_date,
            week_end=payload.week_end_date,
            athlete_notes=payload.athlete_notes,
            db=db,
        )
        return review
    except Exception as e:
        logger.error(f"Failed to generate weekly review: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate review: {e}")


@router.get("/weekly/latest", response_model=WeeklyReview)
async def get_latest_review(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.execute(
        select(WeeklyReviewDB)
        .where(WeeklyReviewDB.user_id == user_id)
        .order_by(WeeklyReviewDB.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No reviews found")
    return _wr_to_schema(row)


@router.get("/weekly", response_model=List[WeeklyReview])
async def list_weekly_reviews(
    limit: int = 10,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = db.execute(
        select(WeeklyReviewDB)
        .where(WeeklyReviewDB.user_id == user_id)
        .order_by(WeeklyReviewDB.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [_wr_to_schema(r) for r in rows]


@router.get("/weekly/by-id/{review_id}", response_model=WeeklyReview)
async def get_review_by_id(
    review_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.get(WeeklyReviewDB, review_id)
    if not row or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Review not found")
    return _wr_to_schema(row)


@router.get("/weekly/{week_number}", response_model=WeeklyReview)
async def get_review_by_week(
    week_number: int,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.execute(
        select(WeeklyReviewDB)
        .where(WeeklyReviewDB.user_id == user_id, WeeklyReviewDB.week_number == week_number)
        .order_by(WeeklyReviewDB.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"No review found for week {week_number}")
    return _wr_to_schema(row)


# ==========================================================
# Auto-apply review adjustments
# ==========================================================

@router.post("/weekly/{review_id}/apply")
async def apply_review_adjustments(
    review_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Apply review adjustments to the next microcycle + regenerate its workouts."""
    from app.core.engine.ai_programmer import ai_programmer

    user_id = int(current_user["id"])

    review_row = db.get(WeeklyReviewDB, review_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found")
    if review_row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    adjustments = NextWeekAdjustments(**(review_row.next_week_adjustments or {}))
    next_week_index = review_row.week_number + 1

    macro = db.execute(
        select(MacrocycleDB).where(
            MacrocycleDB.user_id == user_id,
            MacrocycleDB.active.is_(True),
        ).limit(1)
    ).scalar_one_or_none()
    if not macro:
        raise HTTPException(status_code=404, detail="No active macrocycle")

    micro = db.execute(
        select(MicrocycleDB).where(
            MicrocycleDB.macrocycle_id == macro.id,
            MicrocycleDB.week_index_in_macro == next_week_index,
        ).limit(1)
    ).scalar_one_or_none()
    if not micro:
        raise HTTPException(
            status_code=404,
            detail=f"No microcycle found for week {next_week_index} in active macrocycle",
        )

    intensity_target = {
        "increase": "high",
        "decrease": "low",
        "maintain": None,
    }.get(
        adjustments.intensity_change.value
        if hasattr(adjustments.intensity_change, "value")
        else adjustments.intensity_change,
        None,
    )

    volume_target = None
    if adjustments.volume_change_pct >= 10:
        volume_target = "high"
    elif adjustments.volume_change_pct <= -10:
        volume_target = "low"

    if intensity_target is not None:
        micro.intensity_target = intensity_target
    if volume_target is not None:
        micro.volume_target = volume_target
    focus_note = (
        f" · Focus: {', '.join(adjustments.focus_movements)}"
        if adjustments.focus_movements else ""
    )
    micro.notes = f"Auto-adjusted from week {review_row.week_number} review" + focus_note

    adj_dict = dict(review_row.next_week_adjustments or {})
    adj_dict["_applied"] = True
    review_row.next_week_adjustments = adj_dict
    db.add(review_row)
    db.commit()

    try:
        generated = await ai_programmer.generate_microcycle_program(
            db=db, microcycle=micro, user_id=user_id
        )
        return {
            "status": "success",
            "message": f"Applied week {review_row.week_number} review adjustments to week {next_week_index}",
            "adjustments_applied": {
                "volume_change_pct": adjustments.volume_change_pct,
                "intensity_change": adjustments.intensity_change,
                "focus_movements": adjustments.focus_movements,
            },
            "microcycle_id": str(micro.id),
            "workouts_generated": generated,
        }
    except Exception as e:
        logger.error(f"Failed to apply adjustments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to apply adjustments: {e}")
