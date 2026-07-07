"""
Google Calendar Integration
Auto-schedule workouts and meal windows via Google Calendar API.

Flow:
1. User clicks "Connect Google Calendar" → redirected to Google OAuth
2. After consent, callback stores refresh_token in users table
3. sync_calendar_events() creates events for next 7 days of training
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional, TypedDict, List
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SCOPES = "https://www.googleapis.com/auth/calendar.events"

_PLACEHOLDER_VALUES = frozenset({
    "",
    "your-client-id",
    "your-client-secret",
    "changeme",
    "change-me",
})


def is_google_calendar_configured() -> bool:
    """True when real OAuth credentials are present (not empty/placeholder)."""
    client_id = (settings.GOOGLE_CALENDAR_CLIENT_ID or "").strip()
    client_secret = (settings.GOOGLE_CALENDAR_CLIENT_SECRET or "").strip()
    if client_id.lower() in _PLACEHOLDER_VALUES or client_secret.lower() in _PLACEHOLDER_VALUES:
        return False
    return bool(client_id and client_secret)


def calendar_redirect_uri() -> str:
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/auth/callback"


def get_oauth_url(state: str = "") -> str:
    """Generate Google OAuth2 authorization URL."""
    if not is_google_calendar_configured():
        raise ValueError("Google Calendar OAuth is not configured on this server")

    params = {
        "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID.strip(),
        "redirect_uri": calendar_redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


class SessionSlot(TypedDict, total=False):
    """Training session slot from the weekly schedule"""
    time: str          # "HH:MM" or time object
    duration_minutes: int
    workout_type: str
    notes: str


class DaySchedule(TypedDict, total=False):
    """Single day entry in a weekly schedule dict"""
    rest_day: bool
    sessions: List[SessionSlot]


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
            "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            "redirect_uri": calendar_redirect_uri(),
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> str:
    """Get a fresh access token from a refresh token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
            "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        return resp.json()["access_token"]


async def _get_user_token(user_id: int) -> Optional[str]:
    """Get a valid access token for a user, refreshing if needed.

    The refresh token is stored under `preferences['google_calendar_refresh_token']`
    on the User row (JSONB).
    """
    from app.db.models import User as UserDB
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        user = session.get(UserDB, int(user_id))
        if not user:
            return None
        refresh_token = (user.preferences or {}).get("google_calendar_refresh_token")

    if not refresh_token:
        return None
    return await refresh_access_token(refresh_token)


async def find_calendar_event_by_session(access_token: str, session_id: str) -> Optional[dict]:
    """Return an existing CHOS-tagged event for a planned session, if any."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "privateExtendedProperty": f"chos_session_id={session_id}",
                "singleEvents": "true",
            },
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return items[0] if items else None


async def create_calendar_event(
    access_token: str,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    timezone: str = None,
    color_id: str = "9",  # blueberry
    session_id: Optional[str] = None,
) -> dict:
    """Create a single Google Calendar event."""
    tz = timezone or settings.DEFAULT_TIMEZONE

    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
        "colorId": color_id,
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 30},
            ],
        },
    }
    if session_id:
        event["extendedProperties"] = {"private": {"chos_session_id": session_id}}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            json=event,
        )
        resp.raise_for_status()
        return resp.json()


async def sync_calendar_events(user_id: int) -> dict:
    """
    Create Google Calendar events for the user's next 7 days of training.

    Reads planned_sessions from the periodization model and creates one event
    per session with workout-type-specific coloring.
    """
    from sqlalchemy import select
    from app.db.models import PlannedSession as PlannedSessionDB, User as UserDB
    from app.db.session import SessionLocal

    access_token = await _get_user_token(user_id)
    if not access_token:
        return {"created": 0, "status": "not_connected", "message": "Google Calendar not connected. Please authorize first."}

    today = datetime.now(dt_timezone.utc).date()
    end = today + timedelta(days=6)

    with SessionLocal() as session:
        user = session.get(UserDB, int(user_id))
        user_timezone = (
            (user.timezone if user else None)
            or (user.preferences or {}).get("timezone") if user else None
        ) or settings.DEFAULT_TIMEZONE

        sessions = session.execute(
            select(PlannedSessionDB)
            .where(
                PlannedSessionDB.user_id == int(user_id),
                PlannedSessionDB.date >= today,
                PlannedSessionDB.date <= end,
            )
            .order_by(PlannedSessionDB.date, PlannedSessionDB.order_in_day)
        ).scalars().all()

    if not sessions:
        return {"created": 0, "status": "no_schedule", "message": "No planned sessions in the next 7 days."}

    color_map = {
        "strength": "9",      # blueberry
        "metcon": "11",       # tomato
        "skill": "2",         # sage
        "conditioning": "7",  # peacock
        "mixed": "5",         # banana
    }
    created = 0
    skipped = 0

    for ps in sessions:
        workout_type = ps.workout_type or "training"
        session_type = workout_type.capitalize()
        duration_min = ps.duration_minutes or 60
        session_date = ps.date

        if ps.start_time:
            hour, minute = ps.start_time.hour, ps.start_time.minute
        else:
            hour, minute = 6, 0

        try:
            tz = ZoneInfo(user_timezone)
        except Exception:
            tz = ZoneInfo(settings.DEFAULT_TIMEZONE)

        start_dt = datetime(
            session_date.year, session_date.month, session_date.day,
            hour, minute, tzinfo=tz,
        )
        end_dt = start_dt + timedelta(minutes=duration_min)

        summary = f"🏋️ {session_type} — CrossFit Health OS"
        description_parts = [
            f"Type: {session_type}",
            f"Duration: {duration_min} min",
        ]
        if ps.focus:
            description_parts.append(f"Focus: {ps.focus}")
        if ps.notes:
            description_parts.append(f"Notes: {ps.notes}")
        description_parts.append("Generated by CrossFit Health OS")
        description = "\n".join(description_parts)

        color_id = color_map.get(workout_type.lower(), "9")
        session_id = str(ps.id)

        try:
            existing = await find_calendar_event_by_session(access_token, session_id)
            if existing:
                skipped += 1
                continue

            await create_calendar_event(
                access_token, summary, description,
                start_dt, end_dt, user_timezone, color_id,
                session_id=session_id,
            )
            created += 1
        except Exception as e:
            logger.error(f"Failed to create calendar event: {e}")

    return {"created": created, "skipped": skipped, "status": "success"}
