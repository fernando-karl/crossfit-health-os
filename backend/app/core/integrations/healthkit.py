"""
Apple HealthKit Integration (SQLAlchemy).

Receives HRV, sleep, workout data from the iOS app, stores the raw payload in
`healthkit_data`, and upserts the recovery-relevant fields into
`recovery_metrics` so the adaptive engine can actually consume them.

Fields propagated to `recovery_metrics`:
  - hrv_rmssd_ms              -> recovery_metrics.hrv_ms
  - resting_heart_rate_bpm    -> recovery_metrics.resting_heart_rate_bpm
  - sleep_duration_hours      -> recovery_metrics.sleep_duration_hours
  - sleep_quality_score       -> recovery_metrics.sleep_quality (normalized 1-10)

Manually-entered fields (stress, soreness, energy, notes) are never overwritten.
"""
from datetime import date as _Date, datetime
from typing import Any, Dict

from sqlalchemy import select

from app.core.engine.readiness import compute_and_persist_readiness, normalize_sleep_quality
from app.db.models import (
    HealthkitData as HealthkitDataDB,
    RecoveryMetric as RecoveryMetricDB,
)
from app.db.session import SessionLocal


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.utcnow()
    return datetime.utcnow()


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def sync_healthkit_data(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store a HealthKit payload and propagate HRV/sleep/RHR into recovery_metrics.
    """
    user_id = int(user_id)
    start_dt = _parse_dt(data.get("start_date"))
    end_dt = _parse_dt(data.get("end_date"))

    raw_row = HealthkitDataDB(
        user_id=user_id,
        data_type=data.get("type", "mixed"),
        start_date=start_dt,
        end_date=end_dt,
        data=data,
        device_name=data.get("device", "iPhone"),
        source_app="HealthKit",
    )

    hrv_ms = _coerce_int(data.get("hrv_rmssd_ms"))
    rhr_bpm = _coerce_int(data.get("resting_heart_rate_bpm"))
    sleep_hours = _coerce_float(data.get("sleep_duration_hours"))
    sleep_quality = normalize_sleep_quality(_coerce_int(data.get("sleep_quality_score")))

    metric_date: _Date = start_dt.date() if start_dt else _Date.today()
    recovery_updated = False
    readiness_score = None

    with SessionLocal() as db:
        db.add(raw_row)

        if hrv_ms is not None or rhr_bpm is not None or sleep_hours is not None or sleep_quality is not None:
            existing = db.execute(
                select(RecoveryMetricDB).where(
                    RecoveryMetricDB.user_id == user_id,
                    RecoveryMetricDB.date == metric_date,
                )
            ).scalar_one_or_none()

            if existing is None:
                existing = RecoveryMetricDB(user_id=user_id, date=metric_date)
                db.add(existing)

            if hrv_ms is not None:
                existing.hrv_ms = hrv_ms
            if rhr_bpm is not None:
                existing.resting_heart_rate_bpm = rhr_bpm
            if sleep_hours is not None:
                existing.sleep_duration_hours = sleep_hours
            if sleep_quality is not None:
                existing.sleep_quality = sleep_quality

            readiness_score = compute_and_persist_readiness(db, user_id, existing, as_of=metric_date)
            recovery_updated = True

        db.commit()

    return {
        "count": 1,
        "status": "success",
        "recovery_metric_updated": recovery_updated,
        "metric_date": metric_date.isoformat() if recovery_updated else None,
        "readiness_score": readiness_score,
    }
