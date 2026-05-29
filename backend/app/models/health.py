"""
Pydantic models for Health domain
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, date
from uuid import UUID


class RecoveryMetricCreate(BaseModel):
    """Create recovery metric"""
    date: date
    sleep_duration_hours: Optional[float] = None
    sleep_quality_score: Optional[int] = Field(None, ge=1, le=100)
    hrv_rmssd_ms: Optional[int] = None
    resting_heart_rate_bpm: Optional[int] = None
    stress_level: Optional[int] = Field(None, ge=1, le=10)
    muscle_soreness: Optional[int] = Field(None, ge=1, le=10)
    energy_level: Optional[int] = Field(None, ge=1, le=10)
    mood_score: Optional[int] = Field(None, ge=1, le=10)
    notes: Optional[str] = None


class RecoveryMetric(RecoveryMetricCreate):
    """Recovery metric response"""
    id: UUID
    user_id: int
    hrv_baseline_ms: Optional[int] = None
    hrv_ratio: Optional[float] = None
    resting_hr_baseline_bpm: Optional[int] = None
    readiness_score: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BiomarkerReadingCreate(BaseModel):
    """Create biomarker reading (API schema — free-form name, not FK to biomarker_types)."""
    biomarker_name: str
    test_date: date
    value: Optional[float] = None
    unit: str = ""
    reference_min: Optional[float] = None
    reference_max: Optional[float] = None
    status: str = "normal"
    category: str = "other"
    lab_name: Optional[str] = None
    notes: Optional[str] = None


class BiomarkerReading(BiomarkerReadingCreate):
    """Biomarker reading response"""
    id: UUID
    user_id: int
    source: Optional[str] = None
    pdf_url: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# HealthKit ingest payload — strictly bounded to prevent abuse.
# ============================================================
# Replaces the prior `data: dict` body, which had no size cap and let an
# attacker ship arbitrary JSON. Fields here mirror what
# `app/core/integrations/healthkit.py::sync_healthkit_data` actually reads.

class HealthKitSyncRequest(BaseModel):
    """Bounded HealthKit payload from the iOS shortcut / native bridge."""
    type: Optional[str] = Field(default=None, max_length=64)
    device: Optional[str] = Field(default=None, max_length=64)
    start_date: Optional[str] = Field(default=None, max_length=40)  # ISO 8601
    end_date: Optional[str] = Field(default=None, max_length=40)

    # Recovery signals — bounded to physiologically plausible ranges.
    # HRV RMSSD typically 10–200ms in adults; we accept a generous 5–400.
    hrv_rmssd_ms: Optional[int] = Field(default=None, ge=5, le=400)
    # Resting HR: athletes can dip to high 30s; illness/anxiety pushes 150+.
    resting_heart_rate_bpm: Optional[int] = Field(default=None, ge=25, le=220)
    # Sleep: anything outside 0–24h is a parse error.
    sleep_duration_hours: Optional[float] = Field(default=None, ge=0.0, le=24.0)
    sleep_quality_score: Optional[int] = Field(default=None, ge=0, le=100)

    # Optional aggregated daily stats (also bounded).
    steps: Optional[int] = Field(default=None, ge=0, le=200_000)
    active_energy_kcal: Optional[float] = Field(default=None, ge=0, le=20_000)
    workout_duration_minutes: Optional[float] = Field(default=None, ge=0, le=24 * 60)

    # Reject unknown fields so an attacker can't smuggle a 100MB blob into
    # the raw `data` JSONB column.
    model_config = ConfigDict(extra="forbid")
