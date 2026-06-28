"""Resolve daily macro/calorie targets for a user."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User as UserDB
from app.db.models import UserDietPlan as UserDietPlanDB

DEFAULT_MACRO_TARGETS: dict[str, int] = {
    "protein": 150,
    "carbs": 200,
    "fat": 70,
    "calories": 2000,
}

TargetSource = Literal["manual", "diet_plan", "default"]


class MacroTargetsResult(TypedDict):
    targets: dict[str, int]
    source: TargetSource


def _coerce_target(value: Any, fallback: int) -> int:
    try:
        n = int(round(float(value)))
        return n if n > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _from_mapping(raw: dict[str, Any] | None) -> dict[str, int] | None:
    if not raw:
        return None
    calories = raw.get("calories")
    if calories is None:
        return None
    return {
        "calories": _coerce_target(calories, DEFAULT_MACRO_TARGETS["calories"]),
        "protein": _coerce_target(raw.get("protein"), DEFAULT_MACRO_TARGETS["protein"]),
        "carbs": _coerce_target(raw.get("carbs"), DEFAULT_MACRO_TARGETS["carbs"]),
        "fat": _coerce_target(raw.get("fat"), DEFAULT_MACRO_TARGETS["fat"]),
    }


def get_active_diet_plan(db: Session, user_id: int) -> UserDietPlanDB | None:
    return db.execute(
        select(UserDietPlanDB)
        .where(UserDietPlanDB.user_id == user_id, UserDietPlanDB.active.is_(True))
        .order_by(UserDietPlanDB.uploaded_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def resolve_macro_targets(db: Session, user_id: int) -> MacroTargetsResult:
    """Manual preferences beat an uploaded diet plan; both beat the 2000 kcal default."""
    user = db.get(UserDB, user_id)
    prefs = dict(user.preferences or {}) if user else {}

    if prefs.get("macro_targets_manual"):
        manual = _from_mapping(prefs.get("macro_targets"))
        if manual:
            return {"targets": manual, "source": "manual"}

    plan = get_active_diet_plan(db, user_id)
    if plan and plan.daily_calories:
        return {
            "targets": {
                "calories": _coerce_target(plan.daily_calories, DEFAULT_MACRO_TARGETS["calories"]),
                "protein": _coerce_target(plan.protein_g, DEFAULT_MACRO_TARGETS["protein"]),
                "carbs": _coerce_target(plan.carbs_g, DEFAULT_MACRO_TARGETS["carbs"]),
                "fat": _coerce_target(plan.fat_g, DEFAULT_MACRO_TARGETS["fat"]),
            },
            "source": "diet_plan",
        }

    return {"targets": dict(DEFAULT_MACRO_TARGETS), "source": "default"}


def save_manual_macro_targets(db: Session, user_id: int, payload: dict[str, Any]) -> MacroTargetsResult:
    user = db.get(UserDB, user_id)
    if not user:
        raise ValueError("User not found")

    calories = payload.get("calories")
    if calories is None:
        raise ValueError("calories is required")

    targets = {
        "calories": _coerce_target(calories, DEFAULT_MACRO_TARGETS["calories"]),
        "protein": _coerce_target(payload.get("protein"), DEFAULT_MACRO_TARGETS["protein"]),
        "carbs": _coerce_target(payload.get("carbs"), DEFAULT_MACRO_TARGETS["carbs"]),
        "fat": _coerce_target(payload.get("fat"), DEFAULT_MACRO_TARGETS["fat"]),
    }

    prefs = dict(user.preferences or {})
    prefs["macro_targets"] = targets
    prefs["macro_targets_manual"] = True
    user.preferences = prefs
    db.commit()
    db.refresh(user)

    return {"targets": targets, "source": "manual"}


def clear_manual_macro_targets(db: Session, user_id: int) -> MacroTargetsResult:
    user = db.get(UserDB, user_id)
    if not user:
        raise ValueError("User not found")

    prefs = dict(user.preferences or {})
    prefs.pop("macro_targets", None)
    prefs.pop("macro_targets_manual", None)
    user.preferences = prefs
    db.commit()

    return resolve_macro_targets(db, user_id)
