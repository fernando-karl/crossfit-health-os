"""
Health API — recovery metrics and biomarker readings (SQLAlchemy).
"""
from datetime import date as _Date
from typing import List, Optional
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_active_subscription
from app.core.rate_limit import limiter
from app.core.integrations.ocr import parse_lab_report
from app.core.engine.readiness import compute_and_persist_readiness, normalize_sleep_quality
from app.db.models import (
    BiomarkerReading as BiomarkerReadingDB,
    RecoveryMetric as RecoveryMetricDB,
)
from app.db.session import get_session
from app.db.user_id import user_id_equals, user_id_value
from app.models.health import (
    BiomarkerReading,
    RecoveryMetric,
    RecoveryMetricCreate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _rm_to_schema(row: RecoveryMetricDB) -> RecoveryMetric:
    return RecoveryMetric(
        id=row.id,
        user_id=row.user_id,
        date=row.date,
        sleep_duration_hours=row.sleep_duration_hours,
        sleep_quality_score=row.sleep_quality,  # remap: DB column is sleep_quality (1-10)
        hrv_rmssd_ms=row.hrv_ms,
        resting_heart_rate_bpm=row.resting_heart_rate_bpm,
        stress_level=row.stress_level,
        muscle_soreness=row.muscle_soreness,
        energy_level=row.energy_level,
        mood_score=None,
        notes=row.notes,
        readiness_score=row.readiness_score,
        created_at=row.created_at,
    )


def _bm_to_schema(row: BiomarkerReadingDB) -> BiomarkerReading:
    uid = row.user_id
    if isinstance(uid, str) and uid.isdigit():
        uid = int(uid)
    return BiomarkerReading(
        id=row.id,
        user_id=uid,
        biomarker_name=row.biomarker_name,
        test_date=row.test_date,
        value=row.value,
        unit=row.unit,
        reference_min=row.reference_min,
        reference_max=row.reference_max,
        status=row.status,
        category=row.category,
        lab_name=row.lab_name,
        notes=row.notes,
        source=row.source,
        pdf_url=row.pdf_url,
        created_at=row.created_at,
    )


_RECOVERY_FIELD_MAP = {
    "sleep_duration_hours": "sleep_duration_hours",
    "sleep_quality_score": "sleep_quality",
    "hrv_rmssd_ms": "hrv_ms",
    "resting_heart_rate_bpm": "resting_heart_rate_bpm",
    "stress_level": "stress_level",
    "muscle_soreness": "muscle_soreness",
    "energy_level": "energy_level",
    "notes": "notes",
}


def _apply_recovery_updates(row: RecoveryMetricDB, metric: RecoveryMetricCreate) -> None:
    """Patch only fields present in the request — never wipe omitted metrics."""
    payload = metric.model_dump(exclude_unset=True)
    for api_field, db_column in _RECOVERY_FIELD_MAP.items():
        if api_field not in payload:
            continue
        value = payload[api_field]
        if db_column == "sleep_quality":
            row.sleep_quality = normalize_sleep_quality(value)
        else:
            setattr(row, db_column, value)


@router.post("/recovery", response_model=RecoveryMetric)
async def create_recovery_metric(
    metric: RecoveryMetricCreate,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Record daily recovery metrics (upsert on user_id + date)."""
    user_id = int(current_user["id"])

    existing = db.execute(
        select(RecoveryMetricDB).where(
            RecoveryMetricDB.user_id == user_id,
            RecoveryMetricDB.date == metric.date,
        )
    ).scalar_one_or_none()

    if existing:
        row = existing
    else:
        row = RecoveryMetricDB(user_id=user_id, date=metric.date)
        db.add(row)

    _apply_recovery_updates(row, metric)

    compute_and_persist_readiness(db, user_id, row, as_of=metric.date)

    db.commit()
    db.refresh(row)
    return _rm_to_schema(row)


@router.get("/recovery", response_model=List[RecoveryMetric])
async def list_recovery_metrics(
    start_date: Optional[_Date] = None,
    end_date: Optional[_Date] = None,
    limit: int = 30,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    stmt = select(RecoveryMetricDB).where(RecoveryMetricDB.user_id == user_id)
    if start_date:
        stmt = stmt.where(RecoveryMetricDB.date >= start_date)
    if end_date:
        stmt = stmt.where(RecoveryMetricDB.date <= end_date)
    stmt = stmt.order_by(RecoveryMetricDB.date.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [_rm_to_schema(r) for r in rows]


@router.get("/recovery/latest", response_model=Optional[RecoveryMetric])
async def get_latest_recovery(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return the user's most recent recovery record, or `null` if none yet.

    Used by the dashboard/health/training pages to render a "today's readiness"
    card; treating "no data" as 200-with-null keeps the empty-state path on
    the client clean and stops new users from seeing 404s in their devtools.
    """
    user_id = int(current_user["id"])
    row = db.execute(
        select(RecoveryMetricDB)
        .where(RecoveryMetricDB.user_id == user_id)
        .order_by(RecoveryMetricDB.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        return None
    return _rm_to_schema(row)


@router.post("/biomarkers/upload")
@limiter.limit("10/hour")
async def upload_lab_report(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    current_user: dict = Depends(require_active_subscription),
):
    """Upload lab report (PDF or image), extract biomarkers via GPT-4o Vision, persist readings."""
    allowed = (".pdf", ".jpg", ".jpeg", ".png")
    if not any((file.filename or "").lower().endswith(ext) for ext in allowed):
        raise HTTPException(status_code=400, detail="Allowed formats: PDF, JPG, PNG")

    file_bytes = await file.read()
    if len(file_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    biomarkers = await parse_lab_report(
        file_bytes=file_bytes,
        filename=file.filename,
        content_type=file.content_type or "",
    )

    if not biomarkers:
        return {
            "status": "warning",
            "message": "No biomarkers found in the uploaded file",
            "biomarkers_found": 0,
            "biomarkers": [],
        }

    user_id = int(current_user["id"])
    today = _Date.today()
    saved = 0

    for bm in biomarkers:
        try:
            db.add(BiomarkerReadingDB(
                user_id=user_id_value(user_id),
                biomarker_name=bm.get("name", "Unknown"),
                value=bm.get("value"),
                unit=bm.get("unit", ""),
                reference_min=bm.get("reference_min"),
                reference_max=bm.get("reference_max"),
                status=bm.get("status", "normal"),
                category=bm.get("category", "other"),
                test_date=today,
                source="ocr_upload",
            ))
            saved += 1
        except Exception as exc:
            logger.warning("Failed to save biomarker %s: %s", bm.get("name"), exc)
    db.commit()

    return {
        "status": "success",
        "biomarkers_found": len(biomarkers),
        "biomarkers_saved": saved,
        "biomarkers": biomarkers,
    }


@router.get("/biomarkers", response_model=List[BiomarkerReading])
async def list_biomarkers(
    limit: int = 50,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    rows = db.execute(
        select(BiomarkerReadingDB)
        .where(user_id_equals(BiomarkerReadingDB.user_id, user_id))
        .order_by(BiomarkerReadingDB.test_date.desc())
        .limit(limit)
    ).scalars().all()
    return [_bm_to_schema(r) for r in rows]
