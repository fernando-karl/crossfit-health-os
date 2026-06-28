"""
Shared readiness calculation used by adaptive engine, health API, and today window.
"""
from __future__ import annotations

from datetime import date as _Date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RecoveryMetric as RecoveryMetricDB

DEFAULT_HRV_MS = 50.0
DEFAULT_SLEEP_QUALITY = 7
DEFAULT_STRESS_LEVEL = 5
DEFAULT_MUSCLE_SORENESS = 5
DEFAULT_ENERGY_LEVEL = 7
MIN_HRV_DATA_POINTS = 5
HRV_BASELINE_LOOKBACK_DAYS = 30


def normalize_sleep_quality(score: Optional[int]) -> Optional[int]:
    """Map API scale (1-100) to DB/engine scale (1-10)."""
    if score is None:
        return None
    if score > 10:
        return max(1, min(10, round(score / 10)))
    return max(1, min(10, score))


def calculate_hrv_baseline(
    db: Session,
    user_id: int,
    as_of: Optional[_Date] = None,
    lookback_days: int = HRV_BASELINE_LOOKBACK_DAYS,
) -> float:
    ref = as_of or _Date.today()
    from_date = ref - timedelta(days=lookback_days)
    rows = db.execute(
        select(RecoveryMetricDB.hrv_ms).where(
            RecoveryMetricDB.user_id == user_id,
            RecoveryMetricDB.date >= from_date,
            RecoveryMetricDB.date <= ref,
            RecoveryMetricDB.hrv_ms.isnot(None),
        )
    ).scalars().all()

    if not rows or len(rows) < MIN_HRV_DATA_POINTS:
        return DEFAULT_HRV_MS
    return sum(rows) / len(rows)


def recovery_row_to_metric(
    db: Session,
    user_id: int,
    row: Optional[RecoveryMetricDB],
    as_of: Optional[_Date] = None,
) -> dict:
    if not row:
        return {
            "hrv_ratio": 1.0,
            "hrv_ms": DEFAULT_HRV_MS,
            "sleep_quality": DEFAULT_SLEEP_QUALITY,
            "stress_level": DEFAULT_STRESS_LEVEL,
            "muscle_soreness": DEFAULT_MUSCLE_SORENESS,
            "energy_level": DEFAULT_ENERGY_LEVEL,
            "readiness_score": 70,
        }

    metric = {
        "hrv_ms": row.hrv_ms,
        "sleep_quality": row.sleep_quality or DEFAULT_SLEEP_QUALITY,
        "stress_level": row.stress_level or DEFAULT_STRESS_LEVEL,
        "muscle_soreness": row.muscle_soreness or DEFAULT_MUSCLE_SORENESS,
        "energy_level": row.energy_level or DEFAULT_ENERGY_LEVEL,
        "readiness_score": row.readiness_score or 70,
    }

    if row.hrv_ms:
        baseline = calculate_hrv_baseline(db, user_id, as_of=as_of)
        metric["hrv_ratio"] = row.hrv_ms / baseline
    else:
        metric["hrv_ratio"] = 1.0
    return metric


def calculate_readiness_score(recovery: dict) -> int:
    hrv_ratio = recovery.get("hrv_ratio", 1.0)
    sleep_quality = normalize_sleep_quality(recovery.get("sleep_quality")) or DEFAULT_SLEEP_QUALITY
    stress = recovery.get("stress_level", DEFAULT_STRESS_LEVEL)
    soreness = recovery.get("muscle_soreness", DEFAULT_MUSCLE_SORENESS)

    hrv_normalized = max(0, min(1, (hrv_ratio - 0.5) / 1.0))
    sleep_normalized = (sleep_quality - 1) / 9
    stress_normalized = 1 - ((stress - 1) / 9)
    soreness_normalized = 1 - ((soreness - 1) / 9)

    readiness = (
        hrv_normalized * 0.4
        + sleep_normalized * 0.3
        + stress_normalized * 0.2
        + soreness_normalized * 0.1
    ) * 100
    return max(0, min(100, int(round(readiness))))


def compute_and_persist_readiness(
    db: Session,
    user_id: int,
    row: RecoveryMetricDB,
    as_of: Optional[_Date] = None,
) -> int:
    metric = recovery_row_to_metric(db, user_id, row, as_of=as_of or row.date)
    score = calculate_readiness_score(metric)
    row.readiness_score = score
    return score
