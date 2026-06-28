"""
Nutrition API — meal logging and macro tracking (SQLAlchemy).
"""
from datetime import datetime as _Datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.integrations.meal_vision import parse_meal_photo
from app.core.nutrition_targets import (
    clear_manual_macro_targets,
    resolve_macro_targets,
    save_manual_macro_targets,
)
from app.db.models import MealLog as MealLogDB
from app.db.session import get_session

router = APIRouter()

_ALLOWED_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic")
_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


def _meal_to_dict(row: MealLogDB) -> dict:
    return {
        "id": str(row.id),
        "user_id": row.user_id,
        "logged_at": row.logged_at.isoformat() if row.logged_at else None,
        "meal_type": row.meal_type,
        "description": row.description,
        "calories": row.calories,
        "protein_g": row.protein_g,
        "carbs_g": row.carbs_g,
        "fat_g": row.fat_g,
        "fiber_g": row.fiber_g,
        "foods": row.foods or [],
        "photo_url": row.photo_url,
        "ai_estimation": row.ai_estimation,
        "notes": row.notes,
    }


@router.post("/meals")
async def log_meal(
    meal_data: dict,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Log a meal with macros."""
    user_id = int(current_user["id"])

    logged_at = meal_data.get("logged_at")
    if isinstance(logged_at, str):
        try:
            logged_at = _Datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
        except ValueError:
            logged_at = _Datetime.utcnow()
    if logged_at is None:
        logged_at = _Datetime.utcnow()
    # SQLite doesn't store tz-awareness well; drop tz for consistency
    if logged_at.tzinfo is not None:
        logged_at = logged_at.replace(tzinfo=None)

    row = MealLogDB(
        user_id=user_id,
        logged_at=logged_at,
        meal_type=meal_data.get("meal_type"),
        description=meal_data.get("description"),
        calories=meal_data.get("calories"),
        protein_g=meal_data.get("protein_g"),
        carbs_g=meal_data.get("carbs_g"),
        fat_g=meal_data.get("fat_g"),
        fiber_g=meal_data.get("fiber_g"),
        foods=meal_data.get("foods") or [],
        photo_url=meal_data.get("photo_url"),
        ai_estimation=bool(meal_data.get("ai_estimation", False)),
        notes=meal_data.get("notes"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _meal_to_dict(row)


def _fetch_todays_meals(db: Session, user_id: int) -> list[MealLogDB]:
    today_start = _Datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(MealLogDB).where(
            MealLogDB.user_id == user_id,
            MealLogDB.logged_at >= today_start,
        )
    ).scalars().all()


@router.get("/meals/today")
async def get_todays_meals(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = _fetch_todays_meals(db, user_id)
    return [_meal_to_dict(r) for r in rows]


@router.patch("/meals/{meal_id}")
async def update_meal(
    meal_id: str,
    meal_data: dict,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Update fields on one of the current user's logged meals."""
    from uuid import UUID

    user_id = int(current_user["id"])
    try:
        mid = UUID(meal_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Meal not found")

    row = db.get(MealLogDB, mid)
    if not row or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Meal not found")

    editable = ("meal_type", "description", "calories", "protein_g",
                "carbs_g", "fat_g", "fiber_g", "notes")
    for field in editable:
        if field in meal_data:
            setattr(row, field, meal_data[field])

    db.commit()
    db.refresh(row)
    return _meal_to_dict(row)


@router.delete("/meals/{meal_id}")
async def delete_meal(
    meal_id: str,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Delete one of the current user's logged meals."""
    from uuid import UUID

    user_id = int(current_user["id"])
    try:
        mid = UUID(meal_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Meal not found")

    row = db.get(MealLogDB, mid)
    # 404 (not 403) when it isn't theirs — don't leak existence.
    if not row or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Meal not found")

    db.delete(row)
    db.commit()
    return {"success": True}


@router.post("/meals/photo")
async def analyze_meal_photo(
    file: UploadFile = File(...),
    save: bool = Form(default=False),
    meal_type: Optional[str] = Form(default=None),
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Analyze a meal photo via GPT-4o Vision and return estimated macros.

    Form fields:
        file: image of the plate (jpg/png/webp/gif/heic, ≤10MB).
        save: if true, persist a MealLog with the parsed macros.
        meal_type: optional meal_type to attach when saving (breakfast/lunch/...).

    Response: {analysis: {...}, meal: {...} | None}
    """
    if not any((file.filename or "").lower().endswith(ext) for ext in _ALLOWED_PHOTO_EXT):
        raise HTTPException(status_code=400, detail=f"Allowed image formats: {', '.join(_ALLOWED_PHOTO_EXT)}")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    analysis = await parse_meal_photo(file_bytes, content_type=file.content_type or "")

    saved_meal = None
    if save and analysis.get("totals"):
        user_id = int(current_user["id"])
        totals = analysis["totals"]
        row = MealLogDB(
            user_id=user_id,
            logged_at=_Datetime.utcnow(),
            meal_type=meal_type,
            description=analysis.get("description") or None,
            calories=totals.get("calories"),
            protein_g=totals.get("protein_g"),
            carbs_g=totals.get("carbs_g"),
            fat_g=totals.get("fat_g"),
            foods=analysis.get("foods") or [],
            ai_estimation=bool(analysis.get("ai_used")),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        saved_meal = _meal_to_dict(row)

    return {"analysis": analysis, "meal": saved_meal}


@router.get("/macros/summary")
async def get_macro_summary(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = _fetch_todays_meals(db, user_id)
    total_calories = sum((r.calories or 0) for r in rows)
    total_protein = sum((r.protein_g or 0) for r in rows)
    total_carbs = sum((r.carbs_g or 0) for r in rows)
    total_fat = sum((r.fat_g or 0) for r in rows)
    resolved = resolve_macro_targets(db, user_id)
    targets = resolved["targets"]
    return {
        "calories": total_calories,
        "protein_g": total_protein,
        "carbs_g": total_carbs,
        "fat_g": total_fat,
        "meals_logged": len(rows),
        "targets": {
            "calories": targets["calories"],
            "protein_g": targets["protein"],
            "carbs_g": targets["carbs"],
            "fat_g": targets["fat"],
        },
        "target_source": resolved["source"],
    }


@router.get("/targets")
async def get_macro_targets(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    resolved = resolve_macro_targets(db, int(current_user["id"]))
    targets = resolved["targets"]
    return {
        "calories": targets["calories"],
        "protein": targets["protein"],
        "carbs": targets["carbs"],
        "fat": targets["fat"],
        "source": resolved["source"],
    }


@router.put("/targets")
async def set_macro_targets(
    payload: dict,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Save manual daily macro targets (overrides diet-plan defaults)."""
    user_id = int(current_user["id"])
    calories = payload.get("calories")
    if calories is None:
        raise HTTPException(status_code=422, detail="calories is required")
    try:
        cal = int(calories)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="calories must be a number")
    if not 800 <= cal <= 10000:
        raise HTTPException(status_code=422, detail="calories must be between 800 and 10000")

    for field in ("protein", "carbs", "fat"):
        if field in payload and payload[field] is not None:
            try:
                val = int(payload[field])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{field} must be a number")
            if not 0 <= val <= 1000:
                raise HTTPException(status_code=422, detail=f"{field} must be between 0 and 1000")

    resolved = save_manual_macro_targets(db, user_id, payload)
    targets = resolved["targets"]
    return {
        "calories": targets["calories"],
        "protein": targets["protein"],
        "carbs": targets["carbs"],
        "fat": targets["fat"],
        "source": resolved["source"],
    }


@router.delete("/targets")
async def reset_macro_targets(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Clear manual targets; fall back to diet plan or system default."""
    resolved = clear_manual_macro_targets(db, int(current_user["id"]))
    targets = resolved["targets"]
    return {
        "calories": targets["calories"],
        "protein": targets["protein"],
        "carbs": targets["carbs"],
        "fat": targets["fat"],
        "source": resolved["source"],
    }
