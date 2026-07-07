"""
Integrations API — HealthKit + Google Calendar (SQLAlchemy).
"""
import logging
from datetime import date as _Date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.integrations.calendar import (
    exchange_code,
    get_oauth_url,
    sync_calendar_events,
)
from app.core.oauth_state import consume_state, issue_state
from app.core.integrations.healthkit import sync_healthkit_data
from app.db.models import (
    HealthkitData as HealthkitDataDB,
    RecoveryMetric as RecoveryMetricDB,
    User as UserDB,
)
from app.db.session import get_session
from app.db.user_id import user_id_equals
from app.models.health import HealthKitSyncRequest

router = APIRouter()
logger = logging.getLogger(__name__)

HEALTHKIT_STALE_HOURS = 36


def _infer_recovery_source(
    today_recovery: RecoveryMetricDB | None,
    last_hk_row: HealthkitDataDB | None,
) -> str:
    """Best-effort source label for today's recovery row."""
    if not today_recovery:
        return "none"

    hk_fields = (
        today_recovery.hrv_ms is not None
        or today_recovery.resting_heart_rate_bpm is not None
        or today_recovery.sleep_duration_hours is not None
    )
    manual_fields = (
        today_recovery.stress_level is not None
        or today_recovery.muscle_soreness is not None
        or today_recovery.energy_level is not None
    )

    if last_hk_row and hk_fields:
        hk_date = (
            last_hk_row.start_date.date()
            if last_hk_row.start_date
            else last_hk_row.created_at.date()
        )
        if hk_date == today_recovery.date:
            return "mixed" if manual_fields else "healthkit"

    if hk_fields and manual_fields:
        return "mixed"
    if manual_fields:
        return "manual"
    if hk_fields:
        return "healthkit"
    return "none"


def _healthkit_last_metrics(row: HealthkitDataDB | None) -> dict | None:
    if not row:
        return None
    payload = row.data if isinstance(row.data, dict) else {}
    metrics = {
        "hrv_rmssd_ms": payload.get("hrv_rmssd_ms"),
        "sleep_duration_hours": payload.get("sleep_duration_hours"),
        "resting_heart_rate_bpm": payload.get("resting_heart_rate_bpm"),
        "device": payload.get("device") or row.device_name,
        "metric_date": (
            row.start_date.date().isoformat()
            if row.start_date
            else row.created_at.date().isoformat()
        ),
    }
    if not any(
        metrics.get(k) is not None
        for k in ("hrv_rmssd_ms", "sleep_duration_hours", "resting_heart_rate_bpm")
    ):
        return None
    return metrics


# ============================================
# HealthKit
# ============================================

@router.post("/healthkit/sync")
async def sync_healthkit(
    payload: HealthKitSyncRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    # Pydantic enforces field bounds + extra="forbid"; we hand the
    # already-validated dict to the existing storage helper.
    result = await sync_healthkit_data(user_id, payload.model_dump(exclude_none=True))
    return {
        "status": "success",
        "records_synced": result.get("count", 0),
        "recovery_metric_updated": result.get("recovery_metric_updated", False),
        "metric_date": result.get("metric_date"),
        "readiness_score": result.get("readiness_score"),
    }


@router.get("/healthkit/status")
async def healthkit_status(
    request: Request,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Last HealthKit sync, connection health, and inferred recovery data source."""
    user_id = int(current_user["id"])
    today = _Date.today()

    last_hk_row = db.execute(
        select(HealthkitDataDB)
        .where(user_id_equals(HealthkitDataDB.user_id, user_id))
        .order_by(HealthkitDataDB.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_sync = last_hk_row.created_at if last_hk_row else None

    today_recovery = db.execute(
        select(RecoveryMetricDB).where(
            RecoveryMetricDB.user_id == user_id,
            RecoveryMetricDB.date == today,
        )
    ).scalar_one_or_none()

    connected = last_sync is not None
    stale = False
    if last_sync:
        age = datetime.utcnow() - last_sync.replace(tzinfo=None)
        stale = age > timedelta(hours=HEALTHKIT_STALE_HOURS)

    recovery_source = _infer_recovery_source(today_recovery, last_hk_row)
    last_metrics = _healthkit_last_metrics(last_hk_row)

    base_url = str(request.base_url).rstrip("/")
    today_payload = None
    if today_recovery:
        today_payload = {
            "readiness_score": today_recovery.readiness_score,
            "hrv_rmssd_ms": today_recovery.hrv_ms,
            "sleep_duration_hours": today_recovery.sleep_duration_hours,
            "resting_heart_rate_bpm": today_recovery.resting_heart_rate_bpm,
        }

    return {
        "connected": connected,
        "stale": stale,
        "last_sync_at": last_sync.isoformat() if last_sync else None,
        "recovery_source": recovery_source,
        "last_metrics": last_metrics,
        "sync_url": f"{base_url}/api/v1/integrations/healthkit/sync",
        "today_recovery": today_payload,
        "user_email": current_user.get("email"),
    }


# ============================================
# Google Calendar
# ============================================

@router.get("/calendar/oauth/url")
async def get_calendar_oauth_url(current_user: dict = Depends(get_current_user)):
    from app.core.integrations.calendar import is_google_calendar_configured

    if not is_google_calendar_configured():
        raise HTTPException(
            status_code=503,
            detail="google_calendar_not_configured",
        )

    # Single-use random nonce bound to this user. Replaces the prior
    # ``state=user_id`` design which let an attacker hijack the callback
    # to write tokens into another user's row.
    state = issue_state(int(current_user["id"]))
    url = get_oauth_url(state=state)
    return {"auth_url": url}


async def handle_calendar_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    *,
    db: Session,
):
    """OAuth2 callback from Google. Stores refresh_token in users.preferences."""
    if error:
        logger.warning(f"Calendar OAuth error: {error}")
        return RedirectResponse(url="/dashboard/integrations?calendar=error")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Atomically consume the nonce — single-use, expires in 10 minutes.
    # Unknown/expired/replayed nonce → 400 (no DB write happens).
    user_id = consume_state(state)
    if user_id is None:
        logger.warning("Calendar OAuth callback: invalid or expired state")
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    try:
        tokens = await exchange_code(code)
        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            logger.warning(
                "Calendar OAuth callback: no refresh_token for user %s", user_id
            )
            return RedirectResponse(
                url="/dashboard/integrations?calendar=no_refresh"
            )

        user = db.get(UserDB, user_id)
        if user:
            prefs = dict(user.preferences or {})
            prefs["google_calendar_refresh_token"] = refresh_token
            user.preferences = prefs
            db.commit()

        return RedirectResponse(url="/dashboard/integrations?calendar=connected")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar OAuth exchange failed: {e}", exc_info=True)
        return RedirectResponse(url="/dashboard/integrations?calendar=error")


@router.get("/calendar/oauth/callback")
async def calendar_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_session),
):
    """Legacy API-path callback (kept for consoles that register the /api/... URI)."""
    return await handle_calendar_oauth_callback(
        request, code=code, state=state, error=error, db=db
    )


@router.post("/calendar/sync")
async def sync_google_calendar(current_user: dict = Depends(get_current_user)):
    """Sync workout schedule to Google Calendar for the next 7 days."""
    user_id = int(current_user["id"])
    result = await sync_calendar_events(user_id)

    if result.get("status") == "not_connected":
        raise HTTPException(
            status_code=400,
            detail=result.get("message", "Google Calendar not connected"),
        )

    return {
        "status": "success",
        "events_created": result.get("created", 0),
        "message": f"Created {result.get('created', 0)} calendar events for the next 7 days",
    }


@router.delete("/calendar/disconnect")
async def disconnect_calendar(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    user = db.get(UserDB, user_id)
    if user:
        prefs = dict(user.preferences or {})
        prefs.pop("google_calendar_refresh_token", None)
        user.preferences = prefs
        db.commit()

    return {"status": "success", "message": "Google Calendar disconnected"}
