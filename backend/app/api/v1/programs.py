"""
Programs API — generate cfai mesocycle programs (HeuristicComposer / HybridComposer).

Wires the cfai package into FastAPI: builds an Athlete from the authenticated
User (+ their PRs and Injuries), runs MesocyclePlanner with the requested
composer, and persists the full Mesocycle as JSONB.
"""
from __future__ import annotations

import logging
import time
from datetime import date as _Date, datetime as _Datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_active_subscription
from app.core.rate_limit import limiter
from app.core.program_projection import project_program_to_periodization
from app.db.models import (
    Injury as InjuryDB,
    Macrocycle as MacrocycleDB,
    PersonalRecord as PersonalRecordDB,
    Program as ProgramDB,
    User as UserDB,
)
from app.db.session import get_session
from app.models.programs import (
    ProgramActivationResponse,
    ProgramGenerateRequest,
    ProgramResponse,
    ProgramSummary,
)

# cfai imports — package is installed editable via backend/requirements.txt
from cfai.athlete import Athlete, Injury as CfaiInjury, InjurySeverity, OneRepMax
from cfai.composer_hybrid import HybridComposer
from cfai.cost_tracker import cost_tracker
from cfai.llm_providers import PROVIDER_CLASSES
from cfai.mesocycle_planner import MesocyclePlanner, MesocycleSpec
from cfai.movements_seed import load_default_library
from cfai.programmer import HeuristicComposer
from cfai.workout_schema import Phase

router = APIRouter()
logger = logging.getLogger(__name__)


# ==========================================================
# User → cfai.Athlete adapter
# ==========================================================

def _next_monday(today: _Date) -> _Date:
    """Return the next Monday (today if today is Monday)."""
    days_until_monday = (7 - today.weekday()) % 7
    return today + timedelta(days=days_until_monday or 7)


def _severity_to_cfai(s: str) -> InjurySeverity:
    return {
        "mild": InjurySeverity.MINOR,
        "minor": InjurySeverity.MINOR,
        "moderate": InjurySeverity.MODERATE,
        "severe": InjurySeverity.MAJOR,
        "major": InjurySeverity.MAJOR,
    }.get((s or "moderate").lower(), InjurySeverity.MODERATE)


def _build_athlete(db: Session, user: UserDB) -> Athlete:
    """Map a backend User (+ PRs, Injuries) to a cfai Athlete."""
    # 1RMs from personal_records (record_type=1rm, unit=kg)
    pr_rows = db.execute(
        select(PersonalRecordDB).where(
            PersonalRecordDB.user_id == user.id,
            PersonalRecordDB.record_type == "1rm",
        )
    ).scalars().all()
    one_rep_maxes: dict[str, OneRepMax] = {}
    for pr in pr_rows:
        # cfai uses snake_case movement_ids (back_squat, deadlift, ...)
        mid = pr.movement_name.lower().replace(" ", "_").replace("-", "_")
        if pr.unit and pr.unit.lower() == "kg" and pr.value > 0:
            one_rep_maxes[mid] = OneRepMax(
                movement_id=mid,
                value_kg=float(pr.value),
                tested_date=pr.achieved_at.date() if pr.achieved_at else _Date.today(),
                confidence="tested",
            )

    # Active injuries
    inj_rows = db.execute(
        select(InjuryDB).where(
            InjuryDB.user_id == user.id,
            InjuryDB.resolved_at.is_(None),
        )
    ).scalars().all()
    active_injuries: list[CfaiInjury] = [
        CfaiInjury(
            description=row.description or row.body_part,
            severity=_severity_to_cfai(row.severity),
            affected_movements=[],
            affected_patterns=row.restriction_tags or [],
            start_date=row.started_at,
            resolved_date=row.resolved_at,
            notes=row.notes,
        )
        for row in inj_rows
    ]

    # Compute training_age conservatively — fall back to 1.0 if unknown
    training_age = 1.0
    if user.birth_date:
        # No real signal; just use a sane default
        training_age = 2.0

    return Athlete(
        id=str(user.id),
        name=user.name or user.email,
        birthdate=user.birth_date or _Date(1990, 1, 1),
        body_weight_kg=user.weight_kg or 80.0,
        height_cm=user.height_cm,
        training_age_years=training_age,
        one_rep_maxes=one_rep_maxes,
        active_injuries=active_injuries,
        equipment_available=["barbell", "rack", "rower", "bike", "dumbbells", "kettlebell", "pull_up_bar", "rings", "box"],
        primary_goals=user.goals or [],
        sessions_per_week=5,
    )


# ==========================================================
# Composer factory
# ==========================================================

_LIBRARY = None  # lazy singleton — loading the seed is non-trivial


def _get_library():
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = load_default_library()
    return _LIBRARY


def _build_composer(key: str, library):
    if key == "heuristic":
        return HeuristicComposer(library)
    if not key.startswith("hybrid_"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown composer '{key}'. Use 'heuristic' or 'hybrid_<provider>'.",
        )
    provider_name = key[len("hybrid_"):]
    cls = PROVIDER_CLASSES.get(provider_name)
    if cls is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider_name}'. Known: {sorted(PROVIDER_CLASSES)}",
        )
    try:
        provider = cls()
    except (ValueError, ImportError) as e:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider_name}' unavailable: {e}",
        )
    return HybridComposer(provider, library, max_retries=2)


# ==========================================================
# Phase parsing
# ==========================================================

def _parse_phases(week_strs: List[str]) -> List[Phase]:
    out: list[Phase] = []
    for w in week_strs:
        try:
            out.append(Phase(w.lower()))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid phase '{w}'. Allowed: {[p.value for p in Phase]}",
            )
    return out


# ==========================================================
# POST /generate
# ==========================================================

@router.post("/generate", response_model=ProgramResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def generate_program(
    request: Request,
    payload: ProgramGenerateRequest,
    db: Session = Depends(get_session),
    current_user: dict = Depends(require_active_subscription),
):
    """Generate a cfai Mesocycle for the authenticated user.

    Runs `MesocyclePlanner` with the requested composer over `payload.weeks`,
    persists the full Mesocycle JSON when `payload.persist` is true, and
    returns the program payload.
    """
    user_id = int(current_user["id"])
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate inputs
    phases = _parse_phases(payload.weeks)
    if not phases:
        raise HTTPException(status_code=400, detail="At least one week is required")
    deload_weeks = set(payload.deload_weeks or [])
    invalid = [w for w in deload_weeks if w < 1 or w > len(phases)]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"deload_weeks {invalid} out of range 1..{len(phases)}",
        )

    # Build athlete + composer
    athlete = _build_athlete(db, user)
    library = _get_library()
    composer = _build_composer(payload.composer, library)
    spec = MesocycleSpec(weeks=phases, deload_weeks=deload_weeks)

    start_date = payload.start_date or _next_monday(_Date.today())
    name = payload.name or f"{payload.composer} {phases[0].value} mesocycle"

    # Generate
    cost_before = sum(r.cost_usd for r in cost_tracker.records)
    t0 = time.monotonic()
    try:
        planner = MesocyclePlanner(library, composer, sessions_per_week=payload.sessions_per_week)
        meso = planner.plan_mesocycle(
            athlete=athlete,
            spec=spec,
            start_date=start_date,
            primary_focus=payload.primary_focus,
            weekly_focus=payload.weekly_focus,
            meso_id=f"user_{user_id}_{int(t0)}",
            meso_name=name,
        )
    except Exception as e:
        logger.error(f"Mesocycle generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {type(e).__name__}: {e}")
    elapsed_s = time.monotonic() - t0
    cost_delta = sum(r.cost_usd for r in cost_tracker.records) - cost_before

    # Serialize cfai models
    meso_json = meso.model_dump(mode="json")
    spec_json = {
        "weeks": [p.value for p in phases],
        "deload_weeks": sorted(deload_weeks),
    }
    athlete_snap = athlete.model_dump(mode="json")
    gen_meta = {
        "elapsed_seconds": round(elapsed_s, 3),
        "cost_usd": round(cost_delta, 6),
        "composer": payload.composer,
        "n_weeks": len(phases),
        "n_sessions": sum(len(w.sessions) for w in meso.weeks),
    }

    # Persist
    program_id: Optional[UUID] = None
    persisted = False
    created_at: Optional[_Datetime] = None
    if payload.persist:
        row = ProgramDB(
            user_id=user_id,
            name=name,
            composer_used=payload.composer,
            phase=meso.phase.value,
            start_date=start_date,
            duration_weeks=len(phases),
            sessions_per_week=payload.sessions_per_week,
            primary_focus=payload.primary_focus,
            spec=spec_json,
            athlete_snapshot=athlete_snap,
            mesocycle=meso_json,
            generation_metadata=gen_meta,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        program_id = row.id
        persisted = True
        created_at = row.created_at

    return ProgramResponse(
        id=program_id,
        user_id=user_id,
        name=name,
        composer_used=payload.composer,
        phase=meso.phase.value,
        start_date=start_date,
        duration_weeks=len(phases),
        sessions_per_week=payload.sessions_per_week,
        primary_focus=payload.primary_focus,
        spec=spec_json,
        mesocycle=meso_json,
        generation_metadata=gen_meta,
        created_at=created_at,
        persisted=persisted,
    )


# ==========================================================
# GET / and GET /{id}
# ==========================================================

@router.get("/", response_model=List[ProgramSummary])
async def list_programs(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = db.execute(
        select(ProgramDB)
        .where(ProgramDB.user_id == user_id)
        .order_by(ProgramDB.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [
        ProgramSummary(
            id=r.id,
            name=r.name,
            composer_used=r.composer_used,
            phase=r.phase,
            start_date=r.start_date,
            duration_weeks=r.duration_weeks,
            sessions_per_week=r.sessions_per_week,
            primary_focus=r.primary_focus or [],
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{program_id}", response_model=ProgramResponse)
async def get_program(
    program_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    row = db.get(ProgramDB, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Program not found")
    if row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return ProgramResponse(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        composer_used=row.composer_used,
        phase=row.phase,
        start_date=row.start_date,
        duration_weeks=row.duration_weeks,
        sessions_per_week=row.sessions_per_week,
        primary_focus=row.primary_focus or [],
        spec=row.spec or {},
        mesocycle=row.mesocycle or {},
        generation_metadata=row.generation_metadata or {},
        created_at=row.created_at,
        persisted=True,
    )


# ==========================================================
# POST /{id}/activate
# ==========================================================

@router.post("/{program_id}/activate", response_model=ProgramActivationResponse)
async def activate_program(
    program_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Project a stored Program into Macrocycle/Microcycle/PlannedSession rows.

    Deactivates any prior active macrocycle for the user. Generated
    PlannedSessions get `status='planned'` and a `generated_template_id`
    so `/training/today` and `/training/workouts/next` surface them.
    """
    user_id = int(current_user["id"])
    program = db.get(ProgramDB, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    if program.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        result = project_program_to_periodization(db, program)
        # Link the program back to its macrocycle for reverse lookup
        program.macrocycle_id = result["macrocycle_id"]
        db.add(program)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Activation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Activation failed: {type(e).__name__}: {e}"
        )

    return ProgramActivationResponse(
        program_id=program.id,
        macrocycle_id=result["macrocycle_id"],
        microcycles=result["microcycles"],
        workout_templates=result["workout_templates"],
        planned_sessions=result["planned_sessions"],
    )
