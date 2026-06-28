"""
Training API — workout generation, session tracking, personal records (SQLAlchemy).
"""
from datetime import date as _Date, datetime as _Datetime, timedelta
from typing import List, Optional
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_active_subscription
from app.core.datetime_utils import user_today
from app.core.rate_limit import limiter
from app.core.engine.adaptive import adaptive_engine
from app.db.models import (
    Macrocycle as MacrocycleDB,
    Microcycle as MicrocycleDB,
    PersonalRecord as PersonalRecordDB,
    PlannedSession as PlannedSessionDB,
    WorkoutSession as WorkoutSessionDB,
    WorkoutTemplate as WorkoutTemplateDB,
)
from app.db.session import get_session
from app.models.training import (
    AdaptiveWorkoutResponse,
    PersonalRecord,
    PersonalRecordCreate,
    Movement,
    Methodology,
    WorkoutGenerationRequest,
    WorkoutSession,
    WorkoutSessionCreate,
    WorkoutSessionUpdate,
    WorkoutTemplate,
    WorkoutType,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _ws_to_schema(row: WorkoutSessionDB) -> WorkoutSession:
    return WorkoutSession(
        id=row.id,
        user_id=row.user_id,
        template_id=row.template_id,
        planned_session_id=row.planned_session_id,
        scheduled_at=row.scheduled_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_minutes=row.duration_minutes,
        workout_type=WorkoutType(row.workout_type),
        movements=[],  # shell entity keeps movements elsewhere for now
        score=row.score,
        rpe_score=row.rpe_score,
        notes=row.notes,
    )


def _pr_to_schema(row: PersonalRecordDB) -> PersonalRecord:
    return PersonalRecord(
        id=row.id,
        user_id=row.user_id,
        movement_name=row.movement_name,
        record_type=row.record_type,
        value=row.value,
        unit=row.unit,
        notes=row.notes,
        video_url=row.video_url,
        achieved_at=row.achieved_at,
        session_id=row.session_id,
    )


def _template_to_schema(row: WorkoutTemplateDB) -> WorkoutTemplate:
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
        warm_up=row.warm_up,
        tags=row.tags or [],
        equipment_required=row.equipment_required or [],
        video_url=None,
        created_at=row.created_at,
        is_public=row.is_public,
    )


# ==========================================================
# Adaptive workout generation
# ==========================================================

@router.post("/generate", response_model=AdaptiveWorkoutResponse)
@limiter.limit("30/hour")
async def generate_adaptive_workout(
    request: Request,
    payload: WorkoutGenerationRequest,
    db: Session = Depends(get_session),
    current_user: dict = Depends(require_active_subscription),
):
    """Generate an adaptive workout adjusted for today's readiness."""
    user_id = payload.user_id if payload.user_id is not None else int(current_user["id"])
    target_date = payload.date or _Date.today()
    try:
        return await adaptive_engine.generate_workout(
            db=db,
            user_id=user_id,
            target_date=target_date,
            force_rest=payload.force_rest,
            recovery_override=payload.recovery_override_dict(),
        )
    except Exception as e:
        logger.error(f"generate_adaptive_workout failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate workout: {e}")


@router.get("/today")
async def get_today_workout(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return the planned workout for today, or `{workout: null}` if none.

    Shape matches the dashboard JS contract:
        {"workout": <WorkoutTemplate>|null}
    The dashboard's "Generate Today's Workout" CTA fires when workout is null.
    """
    uid = int(current_user["id"])
    today = user_today(current_user)

    macro = db.execute(
        select(MacrocycleDB).where(
            and_(MacrocycleDB.user_id == uid, MacrocycleDB.active.is_(True))
        )
    ).scalar_one_or_none()
    if not macro:
        return {"workout": None}

    session = db.execute(
        select(PlannedSessionDB)
        .where(
            and_(
                PlannedSessionDB.microcycle_id.in_(
                    select(MicrocycleDB.id).where(MicrocycleDB.macrocycle_id == macro.id)
                ),
                PlannedSessionDB.date == today,
                PlannedSessionDB.generated_template_id.isnot(None),
                PlannedSessionDB.status.in_(["generated", "planned"]),
            )
        )
        .order_by(PlannedSessionDB.order_in_day)
        .limit(1)
    ).scalar_one_or_none()

    if not session or not session.generated_template_id:
        return {"workout": None}

    already_done = db.execute(
        select(WorkoutSessionDB.id).where(
            WorkoutSessionDB.user_id == uid,
            WorkoutSessionDB.planned_session_id == session.id,
            WorkoutSessionDB.completed_at.isnot(None),
        )
    ).scalar_one_or_none()
    if already_done:
        return {
            "workout": None,
            "completed": True,
            "planned_session_id": str(session.id),
        }

    template = db.get(WorkoutTemplateDB, session.generated_template_id)
    if not template:
        return {"workout": None}

    # Apply today's readiness multiplier over the planned session so the
    # athlete actually sees an adapted volume (matches the landing promise
    # "fresh → push, wiped → lighter session"). Non-destructive — we mutate
    # the response, not the template row.
    template_schema = _template_to_schema(template)
    try:
        adapted = adaptive_engine.adapt_template(
            db=db, user_id=uid, template=template_schema, target_date=today
        )
    except Exception as e:  # noqa: BLE001 — overlay must never break the page
        logger.warning("adapt_template failed for user %s: %s", uid, e)
        return {
            "workout": template_schema.model_dump(mode="json"),
            "planned_session_id": str(session.id),
            "template_id": str(template.id),
        }

    workout = template_schema.model_copy(update={"movements": adapted.adjusted_movements})
    return {
        "workout": workout.model_dump(mode="json"),
        "planned_session_id": str(session.id),
        "template_id": str(template.id),
        "adapted_meta": {
            "volume_multiplier": adapted.volume_multiplier,
            "readiness_score": adapted.readiness_score,
            "recommendation": adapted.recommendation,
        },
    }


@router.get("/workouts/next", response_model=Optional[WorkoutTemplate])
async def get_next_workout(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Get the next scheduled workout from the active macrocycle. Returns None if no upcoming workout."""
    uid = int(current_user["id"])
    today = _Date.today()
    # Find active macrocycle
    macro = db.execute(
        select(MacrocycleDB).where(
            and_(MacrocycleDB.user_id == uid, MacrocycleDB.active.is_(True))
        )
    ).scalar_one_or_none()
    if not macro:
        return None
    # Find next session with a generated template (status = generated or planned)
    session = db.execute(
        select(PlannedSessionDB)
        .where(
            and_(
                PlannedSessionDB.microcycle_id.in_(
                    select(MicrocycleDB.id).where(MicrocycleDB.macrocycle_id == macro.id)
                ),
                PlannedSessionDB.generated_template_id.isnot(None),
                PlannedSessionDB.status.in_(["generated", "planned"]),
                PlannedSessionDB.date >= today,
            )
        )
        .order_by(PlannedSessionDB.date, PlannedSessionDB.order_in_day)
        .limit(1)
    ).scalar_one_or_none()
    if not session or not session.generated_template_id:
        return None
    template = db.get(WorkoutTemplateDB, session.generated_template_id)
    if not template:
        return None
    result = _template_to_schema(template)
    result.next_session_date = str(session.date)  # type: ignore
    result.next_session_shift = session.shift  # type: ignore
    return result


def _resolve_planned_session_id(
    db: Session,
    user_id: int,
    user: dict,
    explicit_id: Optional[UUID],
    template_id: Optional[UUID],
) -> Optional[UUID]:
    """Link workout session to calendar planned session when possible."""
    if explicit_id:
        ps = db.get(PlannedSessionDB, explicit_id)
        if ps and ps.user_id == user_id:
            return explicit_id
        return None

    if not template_id:
        return None

    today = user_today(user)
    ps = db.execute(
        select(PlannedSessionDB)
        .where(
            PlannedSessionDB.user_id == user_id,
            PlannedSessionDB.date == today,
            PlannedSessionDB.generated_template_id == template_id,
            PlannedSessionDB.status != "skipped",
        )
        .order_by(PlannedSessionDB.order_in_day)
        .limit(1)
    ).scalar_one_or_none()
    return ps.id if ps else None


# ==========================================================
# Workout sessions
# ==========================================================

@router.post("/sessions", response_model=WorkoutSession, status_code=status.HTTP_201_CREATED)
async def create_workout_session(
    payload: WorkoutSessionCreate,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    planned_session_id = _resolve_planned_session_id(
        db,
        user_id,
        current_user,
        payload.planned_session_id,
        payload.template_id,
    )
    row = WorkoutSessionDB(
        user_id=user_id,
        template_id=payload.template_id,
        planned_session_id=planned_session_id,
        scheduled_at=payload.scheduled_at,
        started_at=_Datetime.utcnow(),
        workout_type=payload.workout_type.value,
        notes=payload.notes,
        duration_minutes=payload.duration_minutes,
        rpe_score=payload.rpe_score,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _ws_to_schema(row)


@router.patch("/sessions/{session_id}", response_model=WorkoutSession)
async def complete_workout_session(
    session_id: UUID,
    update: WorkoutSessionUpdate,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.get(WorkoutSessionDB, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    data = update.model_dump(exclude_unset=True, mode="python")
    # Scalar fields only — drop legacy dict-shaped fields.
    for skip in ("actual_weight_kg", "actual_reps", "muscle_groups_worked", "video_url"):
        data.pop(skip, None)
    if "score_type" in data and hasattr(data["score_type"], "value"):
        data["score_type"] = data["score_type"].value
    for k, v in data.items():
        if hasattr(row, k):
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _ws_to_schema(row)


@router.get("/sessions", response_model=List[WorkoutSession])
async def list_workout_sessions(
    limit: int = 20,
    offset: int = 0,
    start_date: Optional[_Date] = None,
    end_date: Optional[_Date] = None,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    stmt = select(WorkoutSessionDB).where(WorkoutSessionDB.user_id == user_id)
    if start_date is not None:
        stmt = stmt.where(func.date(WorkoutSessionDB.started_at) >= start_date)
    if end_date is not None:
        stmt = stmt.where(func.date(WorkoutSessionDB.started_at) <= end_date)
    rows = db.execute(
        stmt.order_by(WorkoutSessionDB.started_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return [_ws_to_schema(r) for r in rows]


@router.get("/sessions/{session_id}", response_model=WorkoutSession)
async def get_workout_session(
    session_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.get(WorkoutSessionDB, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return _ws_to_schema(row)


# ==========================================================
# Personal records
# ==========================================================

@router.post("/prs", response_model=PersonalRecord, status_code=status.HTTP_201_CREATED)
async def create_personal_record(
    pr: PersonalRecordCreate,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    # Upsert on (user_id, movement_name, record_type)
    existing = db.execute(
        select(PersonalRecordDB).where(
            PersonalRecordDB.user_id == user_id,
            PersonalRecordDB.movement_name == pr.movement_name,
            PersonalRecordDB.record_type == pr.record_type.value,
        )
    ).scalar_one_or_none()
    if existing:
        existing.value = pr.value
        existing.unit = pr.unit
        existing.notes = pr.notes
        existing.video_url = pr.video_url
        existing.achieved_at = _Datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return _pr_to_schema(existing)

    row = PersonalRecordDB(
        user_id=user_id,
        movement_name=pr.movement_name,
        record_type=pr.record_type.value,
        value=pr.value,
        unit=pr.unit,
        notes=pr.notes,
        video_url=pr.video_url,
        achieved_at=_Datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _pr_to_schema(row)


@router.get("/prs", response_model=List[PersonalRecord])
async def list_personal_records(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = db.execute(
        select(PersonalRecordDB)
        .where(PersonalRecordDB.user_id == user_id)
        .order_by(PersonalRecordDB.achieved_at.desc())
    ).scalars().all()
    return [_pr_to_schema(r) for r in rows]


# ==========================================================
# Templates (public)
# ==========================================================

@router.get("/templates/{template_id}", response_model=WorkoutTemplate)
async def get_workout_template(
    template_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Get a single workout template by ID. Returns user's own or public templates."""
    row = db.get(WorkoutTemplateDB, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    uid = int(current_user["id"])
    if not row.is_public and row.owner_user_id != uid:
        raise HTTPException(status_code=403, detail="Access denied")
    return _template_to_schema(row)


@router.get("/templates", response_model=List[WorkoutTemplate])
async def list_workout_templates(
    methodology: Optional[str] = None,
    workout_type: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    current_uid = int(current_user["id"])
    stmt = select(WorkoutTemplateDB).where(
        or_(WorkoutTemplateDB.is_public.is_(True), WorkoutTemplateDB.owner_user_id == current_uid)
    )
    if methodology:
        stmt = stmt.where(WorkoutTemplateDB.methodology == methodology)
    if workout_type:
        stmt = stmt.where(WorkoutTemplateDB.workout_type == workout_type)
    stmt = stmt.limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [_template_to_schema(r) for r in rows]


# ==========================================================
# Training stats summary
# ==========================================================

@router.get("/stats/summary")
async def get_training_summary(
    days: int = 30,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    from_date = _Datetime.utcnow() - timedelta(days=days)
    rows = db.execute(
        select(WorkoutSessionDB).where(
            and_(
                WorkoutSessionDB.user_id == user_id,
                WorkoutSessionDB.started_at >= from_date,
            )
        )
    ).scalars().all()

    if not rows:
        return {
            "total_workouts": 0,
            "avg_duration_minutes": 0,
            "avg_rpe": 0,
            "workout_types": {},
            "period_days": days,
        }

    total = len(rows)
    avg_duration = sum((r.duration_minutes or 0) for r in rows) / total
    rpes = [r.rpe_score for r in rows if r.rpe_score is not None]
    avg_rpe = sum(rpes) / len(rpes) if rpes else 0

    types: dict[str, int] = {}
    for r in rows:
        types[r.workout_type] = types.get(r.workout_type, 0) + 1

    return {
        "total_workouts": total,
        "avg_duration_minutes": round(avg_duration, 1),
        "avg_rpe": round(avg_rpe, 1),
        "workout_types": types,
        "period_days": days,
    }
