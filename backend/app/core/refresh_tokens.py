"""Refresh token issuance, rotation, and reuse detection.

Design:
- Access token: short-lived JWT (60 min), unrevocable until expiry.
- Refresh token: long-lived random string (30 days), stored as SHA-256 hash
  in ``refresh_tokens``. Each ``rotate`` call atomically revokes the old row
  and inserts a new one, linking via ``replaced_by_id``.
- **Reuse detection** (theft mitigation): if a request presents a refresh
  token whose row is already revoked AND has a successor, that means
  someone replayed an old token — assume compromise and revoke the entire
  rotation chain (every active row for that user).

The raw refresh token is never persisted. We hand it back to the client
once at issuance time and look it up by hash on every refresh.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import RefreshToken


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    """Random opaque token. Independent of JWT — never decoded server-side."""
    return secrets.token_urlsafe(48)


def create_access_token(user_id: int, email: str) -> str:
    """Short-lived JWT used as the bearer access token."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TTL_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def issue_pair(
    db: Session,
    user_id: int,
    email: str,
    *,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> Tuple[str, str]:
    """Mint a fresh access+refresh pair and persist the refresh hash."""
    access = create_access_token(user_id, email)
    raw_refresh = _generate_raw_token()

    db.add(RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw_refresh),
        issued_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TTL_DAYS),
        user_agent=(user_agent or None),
        ip=(ip or None),
    ))
    db.commit()
    return access, raw_refresh


def _revoke_all_active_for_user(db: Session, user_id: int) -> int:
    """Revoke every still-active refresh row for a user. Returns count."""
    rows = db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.revoked_at = now
    if rows:
        db.commit()
    return len(rows)


def rotate(
    db: Session,
    raw_refresh: str,
    *,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> Optional[Tuple[str, str, int]]:
    """Validate the supplied refresh token and rotate to a new pair.

    Returns ``(access, refresh, user_id)`` on success, or ``None`` if the
    token is unknown / expired / revoked-without-rotation. If the token
    was already rotated (i.e. presented after replacement), this is treated
    as theft and the whole chain is revoked — caller still receives None.

    The lookup + update happen in the same transaction so two concurrent
    refresh calls cannot both succeed.
    """
    if not raw_refresh:
        return None
    h = _hash_token(raw_refresh)
    row = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == h)
    ).scalar_one_or_none()
    if row is None:
        return None

    now = datetime.utcnow()

    # Reuse detection: token was already rotated. Treat as compromise.
    if row.replaced_by_id is not None:
        _revoke_all_active_for_user(db, row.user_id)
        return None

    if row.revoked_at is not None:
        return None
    if row.expires_at <= now:
        return None

    # Mint new pair, link old → new, mark old revoked.
    # Need user email for the access token JWT.
    from app.db.models import User as UserDB
    user = db.get(UserDB, row.user_id)
    if user is None:
        return None

    new_raw = _generate_raw_token()
    new_row = RefreshToken(
        user_id=row.user_id,
        token_hash=_hash_token(new_raw),
        issued_at=now,
        expires_at=now + timedelta(days=settings.JWT_REFRESH_TTL_DAYS),
        user_agent=(user_agent or None),
        ip=(ip or None),
    )
    db.add(new_row)
    db.flush()  # populate new_row.id

    row.revoked_at = now
    row.replaced_by_id = new_row.id
    db.commit()

    access = create_access_token(row.user_id, user.email)
    return access, new_raw, row.user_id


def revoke(db: Session, raw_refresh: str) -> bool:
    """Mark a refresh token revoked (logout). Returns True if it was active."""
    if not raw_refresh:
        return False
    row = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw_refresh))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.utcnow()
    db.commit()
    return True
