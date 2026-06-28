"""Generate and activate a starter 4-week program after onboarding."""
from __future__ import annotations

import logging
import time
from datetime import date as _Date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.program_projection import project_program_to_periodization
from app.db.models import Program as ProgramDB, User as UserDB

logger = logging.getLogger(__name__)

_GOAL_FOCUS: dict[str, list[str]] = {
    "strength": ["squat_volume", "pressing_strength"],
    "conditioning": ["aerobic_threshold", "work_capacity"],
    "competition": ["olympic_lifts", "gymnastics"],
    "general_fitness": ["squat_volume", "aerobic_threshold"],
}


def _phases(week_strs: list[str]):
    from cfai.workout_schema import Phase
    return [Phase(w.lower()) for w in week_strs]


def create_starter_program(
    db: Session,
    user: UserDB,
    *,
    sessions_per_week: int,
    primary_goal: str,
    name: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Build a 4-week heuristic program and project it into the active macrocycle."""
    from app.api.v1.programs import (
        _build_athlete,
        _build_composer,
        _get_library,
        _next_monday,
    )
    from cfai.mesocycle_planner import MesocyclePlanner, MesocycleSpec

    weeks = ["base", "base", "build", "deload"]
    phases = _phases(weeks)
    focus = _GOAL_FOCUS.get(primary_goal, _GOAL_FOCUS["general_fitness"])
    start_date = _next_monday(_Date.today())
    program_name = name or "My first program"

    try:
        athlete = _build_athlete(db, user)
        library = _get_library()
        composer = _build_composer("heuristic", library)
        spec = MesocycleSpec(weeks=phases, deload_weeks={4})
        t0 = time.monotonic()
        planner = MesocyclePlanner(
            library, composer, sessions_per_week=max(1, min(7, sessions_per_week))
        )
        meso = planner.plan_mesocycle(
            athlete=athlete,
            spec=spec,
            start_date=start_date,
            primary_focus=focus,
            weekly_focus=[],
            meso_id=f"onboarding_{user.id}_{int(t0)}",
            meso_name=program_name,
        )
    except Exception as exc:
        logger.warning("Starter program generation failed for user %s: %s", user.id, exc)
        return None

    meso_json = meso.model_dump(mode="json")
    spec_json = {"weeks": weeks, "deload_weeks": [4]}
    row = ProgramDB(
        user_id=user.id,
        name=program_name,
        composer_used="heuristic",
        phase=meso.phase.value,
        start_date=start_date,
        duration_weeks=len(phases),
        sessions_per_week=max(1, min(7, sessions_per_week)),
        primary_focus=focus,
        spec=spec_json,
        athlete_snapshot=athlete.model_dump(mode="json"),
        mesocycle=meso_json,
        generation_metadata={"source": "onboarding", "composer": "heuristic"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    try:
        result = project_program_to_periodization(db, row)
        row.macrocycle_id = result["macrocycle_id"]
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Starter program activation failed for user %s: %s", user.id, exc)
        return None

    return {
        "program_id": str(row.id),
        "macrocycle_id": str(result["macrocycle_id"]),
        "planned_sessions": result.get("planned_sessions", 0),
    }
