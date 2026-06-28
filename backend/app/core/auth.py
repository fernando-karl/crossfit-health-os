"""
Authentication dependency.

Validates the local JWT issued by `app/api/v1/auth.py::login` and returns the
user as a plain dict (compatible with the existing endpoint signatures).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import User
from app.db.session import get_session

security = HTTPBearer()


def _nutrition_enabled(user: User) -> bool:
    prefs = user.preferences or {}
    if prefs.get("app_focus") == "training_only":
        return False
    if "nutrition_enabled" in prefs:
        return bool(prefs["nutrition_enabled"])
    return True


def _user_to_dict(user: User) -> dict:
    prefs = user.preferences or {}
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "fitness_level": user.fitness_level,
        "weight_kg": user.weight_kg,
        "height_cm": user.height_cm,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "goals": user.goals or [],
        "timezone": user.timezone,
        "preferences": prefs,
        "nutrition_enabled": _nutrition_enabled(user),
        "subscription_status": getattr(user, "subscription_status", "trialing"),
        "trial_expires_at": (
            user.trial_expires_at.isoformat()
            if getattr(user, "trial_expires_at", None) else None
        ),
        "stripe_customer_id": getattr(user, "stripe_customer_id", None),
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> dict:
    """Decode the bearer token, load the user, return as dict."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return _user_to_dict(user)


def require_active_subscription(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency that gates premium endpoints behind an active subscription.

    Allows: subscription_status == 'active' OR (status == 'trialing' AND
    trial not yet expired). Anything else → 402 Payment Required with a
    structured detail the frontend can translate into an upgrade modal.
    """
    status_str = (current_user.get("subscription_status") or "trialing").lower()

    if status_str == "active":
        return current_user

    if status_str == "trialing":
        expires_iso = current_user.get("trial_expires_at")
        # Missing trial_expires_at → treat as expired (defensive: pre-migration users).
        if expires_iso:
            try:
                expires = datetime.fromisoformat(expires_iso)
            except ValueError:
                expires = None
            if expires and expires > datetime.utcnow():
                return current_user

    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "subscription_required",
            "subscription_status": status_str,
            "trial_expires_at": current_user.get("trial_expires_at"),
            "message": "Trial expired or subscription inactive. Upgrade to continue.",
        },
    )
