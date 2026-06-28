"""
Users API — profile management + stats (SQLAlchemy).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.i18n import SUPPORTED_LOCALES, normalize_locale
from app.db.models import (
    PersonalRecord as PersonalRecordDB,
    User as UserDB,
    WorkoutSession as WorkoutSessionDB,
)
from app.db.session import get_session

router = APIRouter()


# Fields on `users` the user is allowed to patch via this endpoint.
ALLOWED_UPDATE_FIELDS = {
    "name",
    "birth_date",
    "weight_kg",
    "height_cm",
    "fitness_level",
    "goals",
    "timezone",
    "locale",
    "preferences",
}


@router.get("/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    return current_user


@router.patch("/me")
async def update_user_profile(
    updates: dict,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Update the authenticated user's profile (only whitelisted fields)."""
    user_id = int(current_user["id"])
    user = db.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changed = False
    for key, value in updates.items():
        if key not in ALLOWED_UPDATE_FIELDS:
            continue
        if key == "locale" and value is not None:
            normalized = normalize_locale(value)
            if normalized is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"locale must be one of {list(SUPPORTED_LOCALES)}",
                )
            value = normalized
        if key == "preferences" and isinstance(value, dict):
            current = dict(user.preferences or {})
            current.update(value)
            value = current
        setattr(user, key, value)
        changed = True

    if changed:
        db.commit()
        db.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "weight_kg": user.weight_kg,
        "height_cm": user.height_cm,
        "fitness_level": user.fitness_level,
        "goals": user.goals or [],
        "timezone": user.timezone,
        "locale": user.locale,
        "preferences": user.preferences or {},
    }


@router.get("/stats")
async def get_user_stats(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])

    total_workouts = db.execute(
        select(func.count(WorkoutSessionDB.id)).where(WorkoutSessionDB.user_id == user_id)
    ).scalar_one()
    total_prs = db.execute(
        select(func.count(PersonalRecordDB.id)).where(PersonalRecordDB.user_id == user_id)
    ).scalar_one()

    user = db.get(UserDB, user_id)
    member_since = user.created_at.isoformat() if user and user.created_at else None

    return {
        "total_workouts": total_workouts,
        "personal_records": total_prs,
        "member_since": member_since,
    }
