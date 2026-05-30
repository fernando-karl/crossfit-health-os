"""
Custom Diet API — handle user-uploaded diet plan PDFs (SQLAlchemy).

Storage-to-bucket upload is intentionally dropped in this slice: we keep the
parsed JSON + filename in `user_diet_plans` (no file_url) until a new storage
backend is wired in.
"""
import io
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.models import UserDietPlan as UserDietPlanDB
from app.db.session import get_session
from app.services.diet_parser import parse_diet_pdf

router = APIRouter(prefix="/api/v1/diet", tags=["diet"])
logger = logging.getLogger(__name__)


@router.post("/upload")
async def upload_diet_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Upload a diet plan PDF, parse it, and store the structured data."""
    user_id = int(current_user["id"])

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        pdf_text = _extract_pdf_text(content)
        if not pdf_text or len(pdf_text) < 50:
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from PDF. Ensure the PDF contains selectable text.",
            )

        diet_data = parse_diet_pdf(pdf_text)

        # Deactivate previous plans.
        existing = db.execute(
            select(UserDietPlanDB).where(
                UserDietPlanDB.user_id == user_id, UserDietPlanDB.active.is_(True)
            )
        ).scalars().all()
        for p in existing:
            p.active = False

        plan = UserDietPlanDB(
            user_id=user_id,
            file_name=file.filename,
            file_url=None,
            daily_calories=diet_data.get("daily_calories"),
            protein_g=(diet_data.get("macros") or {}).get("protein_g"),
            carbs_g=(diet_data.get("macros") or {}).get("carbs_g"),
            fat_g=(diet_data.get("macros") or {}).get("fat_g"),
            meals=diet_data.get("meals") or [],
            supplements=diet_data.get("supplements") or [],
            notes=diet_data.get("notes"),
            parsed_data=diet_data,
            uploaded_at=datetime.utcnow(),
            active=True,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        return {
            "success": True,
            "plan_id": str(plan.id),
            "file_name": plan.file_name,
            "parsed": {
                "daily_calories": plan.daily_calories,
                "macros": {
                    "protein_g": plan.protein_g,
                    "carbs_g": plan.carbs_g,
                    "fat_g": plan.fat_g,
                },
                "meals_count": len(plan.meals or []),
                "supplements": (plan.supplements or [])[:5],
            },
            "message": "Diet plan uploaded and parsed successfully!",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Diet upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {e}")


@router.get("/current")
async def get_current_diet_plan(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    plan = db.execute(
        select(UserDietPlanDB).where(
            UserDietPlanDB.user_id == user_id, UserDietPlanDB.active.is_(True)
        ).order_by(UserDietPlanDB.uploaded_at.desc()).limit(1)
    ).scalar_one_or_none()

    if not plan:
        return {"has_plan": False, "message": "No diet plan uploaded yet"}

    formatted_meals = []
    for meal in plan.meals or []:
        formatted_meals.append({
            "name": (meal.get("name") or "").replace("_", " ").title(),
            "time": meal.get("time", ""),
            "foods": (meal.get("foods") or [])[:3],
            "calories": meal.get("calories"),
        })

    return {
        "has_plan": True,
        "plan": {
            "id": str(plan.id),
            "file_name": plan.file_name,
            "uploaded_at": plan.uploaded_at.isoformat() if plan.uploaded_at else None,
            "daily_calories": plan.daily_calories,
            "macros": {
                "protein_g": plan.protein_g,
                "carbs_g": plan.carbs_g,
                "fat_g": plan.fat_g,
            },
            "meals": formatted_meals,
            "supplements": (plan.supplements or [])[:5],
            "notes": plan.notes,
        },
    }


@router.delete("/current")
async def delete_diet_plan(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = db.execute(
        select(UserDietPlanDB).where(
            UserDietPlanDB.user_id == user_id, UserDietPlanDB.active.is_(True)
        )
    ).scalars().all()
    for p in rows:
        p.active = False
    db.commit()
    return {"success": True, "message": "Diet plan deleted"}


@router.get("/reminders")
async def get_diet_reminders(current_user: dict = Depends(get_current_user)):
    """Meal reminders are not persisted in this slice — return empty."""
    return {"reminders": []}


# ==========================================================
# Helpers
# ==========================================================

def _convert_to_24h(time_str: str) -> str:
    match = re.match(r"(\d{1,2}):?(\d{2})?\s*(am|pm)", (time_str or "").lower())
    if not match:
        return time_str
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3)
    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


# Public aliases kept for legacy tests.
convert_to_24h = _convert_to_24h


def _extract_pdf_text(content: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None
    if pdfplumber is not None:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                return text
        except Exception:
            # Corrupt / non-PDF bytes — fall through to PyMuPDF, then "".
            # The caller treats "" as "couldn't extract" → clean 400.
            pass
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        return text
    except Exception:
        return ""


extract_pdf_text = _extract_pdf_text
