"""
Onboarding API (SQLAlchemy).

Collects initial profile data, stores domain-specific preferences inside
`users.preferences` (instead of proliferating columns), and awards onboarding XP.
Creation of a training macrocycle is deferred to the proper scheduling flow.
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.models import User as UserDB, WorkoutSession as WorkoutSessionDB
from app.db.session import get_session
from app.services.gamification import GamificationService

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


class OnboardingData(BaseModel):
    """Data collected during onboarding."""
    name: str = Field(..., min_length=2, max_length=100)
    birth_date: Optional[str] = None
    weight_kg: Optional[float] = Field(None, ge=30, le=300)
    height_cm: Optional[float] = Field(None, ge=100, le=250)
    fitness_level: str = Field("intermediate")
    primary_goal: str = Field(...)
    available_days: List[str] = Field(default=["monday", "wednesday", "friday"])
    preferred_time: str = Field("morning")
    training_duration: int = Field(60, ge=30, le=180)
    methodologies: List[str] = Field(default=["hwpo"])
    focus_weaknesses: List[str] = Field(default=[])
    has_gym_access: bool = True
    has_barbell: bool = False
    has_rings: bool = False
    has_pullup_bar: bool = False
    app_focus: str = Field("full")
    nutrition_enabled: bool = Field(True)
    generate_first_program: bool = Field(True)


def _calculate_readiness_from_age(birth_date: Optional[str]) -> int:
    if not birth_date:
        return 70
    try:
        birth = date.fromisoformat(birth_date)
        age = (date.today() - birth).days // 365
        if age < 25:
            return 85
        if age < 35:
            return 75
        if age < 45:
            return 65
        return 55
    except Exception:
        return 70


@router.post("/complete")
async def complete_onboarding(
    data: OnboardingData,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Persist onboarding data and award 300 XP."""
    user_id = int(current_user["id"])
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Base columns
    user.name = data.name
    if data.birth_date:
        try:
            user.birth_date = date.fromisoformat(data.birth_date)
        except ValueError:
            pass
    user.weight_kg = data.weight_kg
    user.height_cm = data.height_cm
    user.fitness_level = data.fitness_level
    user.goals = [data.primary_goal] if data.primary_goal else (user.goals or [])

    # Everything else goes into preferences JSONB
    prefs = dict(user.preferences or {})
    prefs.update({
        "onboarding_completed": True,
        "primary_goal": data.primary_goal,
        "preferred_time": data.preferred_time,
        "training_duration": data.training_duration,
        "methodologies": data.methodologies,
        "focus_weaknesses": data.focus_weaknesses,
        "available_days": data.available_days,
        "has_gym_access": data.has_gym_access,
        "has_barbell": data.has_barbell,
        "has_rings": data.has_rings,
        "has_pullup_bar": data.has_pullup_bar,
        "baseline_readiness": _calculate_readiness_from_age(data.birth_date),
        "app_focus": data.app_focus,
        "nutrition_enabled": data.nutrition_enabled,
    })
    user.preferences = prefs
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    # XP
    svc = GamificationService(user_id, db)
    new_level, _ = svc.add_xp(300)

    schedule_created = False
    program_info = None
    if data.generate_first_program:
        from app.services import starter_program

        program_info = starter_program.create_starter_program(
            db,
            user,
            sessions_per_week=len(data.available_days) or 3,
            primary_goal=data.primary_goal,
            name=f"{user.name or 'My'} first program",
        )
        schedule_created = program_info is not None

    return {
        "success": True,
        "profile": {
            "name": user.name,
            "fitness_level": user.fitness_level,
            "goals": user.goals or [],
            "preferences": user.preferences or {},
        },
        "schedule_created": schedule_created,
        "program": program_info,
        "xp_earned": 300,
        "level": new_level,
        "message": (
            "Onboarding complete! Your first training week is ready."
            if schedule_created
            else "Onboarding complete! Set up your training calendar to get started."
        ),
    }


@router.get("/progress")
async def get_onboarding_progress(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    from app.db.models import Macrocycle as MacrocycleDB

    user_id = int(current_user["id"])
    user = db.get(UserDB, user_id)
    profile_complete = bool(user and (user.preferences or {}).get("onboarding_completed"))

    has_active_macro = db.execute(
        select(MacrocycleDB).where(
            MacrocycleDB.user_id == user_id, MacrocycleDB.active.is_(True)
        ).limit(1)
    ).scalar_one_or_none()
    schedule_created = has_active_macro is not None

    first_completed = db.execute(
        select(WorkoutSessionDB)
        .where(
            WorkoutSessionDB.user_id == user_id,
            WorkoutSessionDB.completed_at.is_not(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    first_workout_done = first_completed is not None

    step = 1
    if profile_complete:
        step = 2
    if schedule_created:
        step = 3
    if first_workout_done:
        step = 5

    return {
        "step": step,
        "total_steps": 5,
        "completed": step >= 5,
        "profile_complete": profile_complete,
        "schedule_created": schedule_created,
        "first_workout_done": first_workout_done,
    }


@router.get("/suggestions")
async def get_onboarding_suggestions(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    suggestions = []
    if user.fitness_level == "beginner":
        suggestions.append({
            "type": "tip",
            "title": "Start Light",
            "description": "Focus on form over weight. Proper technique beats heavy loads.",
        })
        suggestions.append({
            "type": "tip",
            "title": "Recovery Matters",
            "description": "As a beginner, rest is growth. Avoid back-to-back days on the same movements.",
        })

    primary_goal = (user.preferences or {}).get("primary_goal")
    if primary_goal == "strength":
        suggestions.append({
            "type": "tip",
            "title": "Compound Movements",
            "description": "Prioritize squats, deadlifts, presses, and pulls.",
        })
    elif primary_goal == "conditioning":
        suggestions.append({
            "type": "tip",
            "title": "Build Your Engine",
            "description": "Mix high-intensity intervals with low-intensity steady state.",
        })

    suggestions.append({
        "type": "tip",
        "title": "Track Everything",
        "description": "Consistent logging is the foundation of progress.",
    })
    return {"suggestions": suggestions}
