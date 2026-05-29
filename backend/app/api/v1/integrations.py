"""
Integrations API — HealthKit + Google Calendar (SQLAlchemy).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.integrations.calendar import (
    exchange_code,
    get_oauth_url,
    sync_calendar_events,
)
from app.core.oauth_state import consume_state, issue_state
from app.core.integrations.healthkit import sync_healthkit_data
from app.db.models import User as UserDB
from app.db.session import get_session
from app.models.health import HealthKitSyncRequest

router = APIRouter()
logger = logging.getLogger(__name__)


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
    }


# ============================================
# Google Calendar
# ============================================

@router.get("/calendar/oauth/url")
async def get_calendar_oauth_url(current_user: dict = Depends(get_current_user)):
    # Single-use random nonce bound to this user. Replaces the prior
    # ``state=user_id`` design which let an attacker hijack the callback
    # to write tokens into another user's row.
    state = issue_state(int(current_user["id"]))
    url = get_oauth_url(state=state)
    return {"auth_url": url}


@router.get("/calendar/oauth/callback")
async def calendar_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_session),
):
    """OAuth2 callback from Google. Stores refresh_token in users.preferences."""
    if error:
        logger.warning(f"Calendar OAuth error: {error}")
        return RedirectResponse(url="/dashboard/profile?calendar=error")

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

        if refresh_token:
            user = db.get(UserDB, user_id)
            if user:
                prefs = dict(user.preferences or {})
                prefs["google_calendar_refresh_token"] = refresh_token
                user.preferences = prefs
                db.commit()

        return RedirectResponse(url="/dashboard/profile?calendar=connected")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar OAuth exchange failed: {e}", exc_info=True)
        return RedirectResponse(url="/dashboard/profile?calendar=error")


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
