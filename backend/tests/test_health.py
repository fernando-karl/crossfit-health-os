"""
Tests for Health API — recovery metrics and biomarker tracking (SQLAlchemy).
"""
import io
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


class TestRecoveryMetrics:
    """Test recovery metric tracking"""

    @pytest.mark.asyncio
    async def test_create_recovery_metric(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        payload = {
            "date": date.today().isoformat(),
            "sleep_duration_hours": 8.5,
            "sleep_quality_score": 8,  # 1-10 scale (DB column)
            "hrv_rmssd_ms": 65,
            "resting_heart_rate_bpm": 52,
            "stress_level": 3,
            "muscle_soreness": 4,
            "energy_level": 8,
            "notes": "Felt great after rest day",
        }
        response = await authenticated_client.post("/api/v1/health/recovery", json=payload)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["sleep_duration_hours"] == 8.5
        assert data["hrv_rmssd_ms"] == 65

    @pytest.mark.asyncio
    async def test_create_recovery_metric_minimal(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        payload = {
            "date": date.today().isoformat(),
            "sleep_quality_score": 7,
            "energy_level": 7,
        }
        response = await authenticated_client.post("/api/v1/health/recovery", json=payload)
        assert response.status_code == 200
        assert response.json()["sleep_quality_score"] == 7

    @pytest.mark.asyncio
    async def test_recovery_partial_update_preserves_hrv(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Dashboard check-in sends only sleep/energy/soreness/stress — HRV must survive."""
        from app.db.models import RecoveryMetric

        today = date.today()
        db_session.add(RecoveryMetric(
            user_id=seeded_user.id,
            date=today,
            hrv_ms=72,
            resting_heart_rate_bpm=54,
            sleep_duration_hours=8.0,
        ))
        db_session.commit()

        response = await authenticated_client.post(
            "/api/v1/health/recovery",
            json={
                "date": today.isoformat(),
                "sleep_duration_hours": 7.0,
                "energy_level": 6,
                "muscle_soreness": 4,
                "stress_level": 5,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["hrv_rmssd_ms"] == 72
        assert data["resting_heart_rate_bpm"] == 54
        assert data["sleep_duration_hours"] == 7.0
        assert data["energy_level"] == 6

    @pytest.mark.asyncio
    async def test_get_latest_recovery(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import RecoveryMetric

        db_session.add(RecoveryMetric(
            user_id=seeded_user.id,
            date=date.today(),
            sleep_quality=8,
            hrv_ms=60,
            readiness_score=75,
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/health/recovery/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["readiness_score"] == 75

    @pytest.mark.asyncio
    async def test_get_latest_recovery_empty(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        # No records yet → endpoint returns 200 with null body so the UI's
        # empty-state path doesn't show a 404 in the user's devtools.
        response = await authenticated_client.get("/api/v1/health/recovery/latest")
        assert response.status_code == 200
        assert response.json() is None

    @pytest.mark.asyncio
    async def test_recovery_metric_validation(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Invalid stress_level > 10 → 422."""
        payload = {
            "date": date.today().isoformat(),
            "stress_level": 15,
            "sleep_quality_score": 7,
        }
        response = await authenticated_client.post("/api/v1/health/recovery", json=payload)
        assert response.status_code == 422


class TestBiomarkers:
    """Test biomarker tracking"""

    @pytest.mark.asyncio
    async def test_list_biomarkers(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import BiomarkerReading

        db_session.add(BiomarkerReading(
            user_id=seeded_user.id,
            biomarker_name="Glucose",
            test_date=date(2026, 2, 1),
            value=95.0,
            unit="mg/dL",
            lab_name="LabCorp",
            status="normal",
            category="metabolic",
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/health/biomarkers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["value"] == 95.0

    @pytest.mark.asyncio
    async def test_list_biomarkers_empty(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.get("/api/v1/health/biomarkers")
        assert response.status_code == 200
        assert response.json() == []


class TestLabReportUpload:
    """Test lab report upload (OCR integration)"""

    @pytest.mark.asyncio
    async def test_upload_invalid_format_returns_400(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.post(
            "/api/v1/health/biomarkers/upload",
            files={"file": ("report.txt", io.BytesIO(b"txt"), "text/plain")},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_file_too_large_returns_400(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        large = b"x" * (21 * 1024 * 1024)
        response = await authenticated_client.post(
            "/api/v1/health/biomarkers/upload",
            files={"file": ("report.pdf", io.BytesIO(large), "application/pdf")},
        )
        assert response.status_code == 400
        assert "too large" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_pdf_no_biomarkers_found(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        with patch("app.api.v1.health.parse_lab_report", new_callable=AsyncMock, return_value=[]):
            response = await authenticated_client.post(
                "/api/v1/health/biomarkers/upload",
                files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "warning"

    @pytest.mark.asyncio
    async def test_upload_pdf_success_saves_biomarkers(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        biomarkers = [
            {"name": "Glucose", "value": 95.0, "unit": "mg/dL",
             "reference_min": 70, "reference_max": 100, "status": "normal", "category": "metabolic"},
            {"name": "Hemoglobin", "value": 14.5, "unit": "g/dL",
             "reference_min": 12, "reference_max": 17, "status": "normal", "category": "hematology"},
        ]
        with patch("app.api.v1.health.parse_lab_report", new_callable=AsyncMock, return_value=biomarkers):
            response = await authenticated_client.post(
                "/api/v1/health/biomarkers/upload",
                files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["biomarkers_found"] == 2
        assert data["biomarkers_saved"] == 2

    @pytest.mark.asyncio
    async def test_upload_jpg_accepted(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        with patch("app.api.v1.health.parse_lab_report", new_callable=AsyncMock, return_value=[]):
            response = await authenticated_client.post(
                "/api/v1/health/biomarkers/upload",
                files={"file": ("lab.jpg", io.BytesIO(b"\xff\xd8\xff"), "image/jpeg")},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_png_accepted(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        with patch("app.api.v1.health.parse_lab_report", new_callable=AsyncMock, return_value=[]):
            response = await authenticated_client.post(
                "/api/v1/health/biomarkers/upload",
                files={"file": ("lab.png", io.BytesIO(b"\x89PNG"), "image/png")},
            )
        assert response.status_code == 200


class TestRecoveryWithDateRange:
    """Test recovery metrics with date range filtering"""

    @pytest.mark.asyncio
    async def test_list_recovery_with_start_date(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import RecoveryMetric

        db_session.add(RecoveryMetric(
            user_id=seeded_user.id, date=date(2026, 3, 20), sleep_quality=8,
        ))
        db_session.add(RecoveryMetric(
            user_id=seeded_user.id, date=date(2026, 2, 15), sleep_quality=5,
        ))
        db_session.commit()

        response = await authenticated_client.get(
            "/api/v1/health/recovery?start_date=2026-03-01"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["date"] == "2026-03-20"

    @pytest.mark.asyncio
    async def test_list_recovery_with_date_range(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import RecoveryMetric

        for d in [date(2026, 3, 15), date(2026, 4, 20)]:
            db_session.add(RecoveryMetric(user_id=seeded_user.id, date=d, sleep_quality=7))
        db_session.commit()

        response = await authenticated_client.get(
            "/api/v1/health/recovery?start_date=2026-03-01&end_date=2026-03-31"
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_list_recovery_empty(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.get("/api/v1/health/recovery")
        assert response.status_code == 200
        assert response.json() == []
