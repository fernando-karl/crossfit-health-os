"""
Notifications API — list / mark-read for the current user (SQLAlchemy).
"""
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.models import Notification as NotificationDB
from app.db.session import get_session

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _to_dict(n: NotificationDB) -> Dict[str, Any]:
    return {
        "id": str(n.id),
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "data": n.data or {},
        "read": n.read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("")
async def list_notifications(
    limit: int = 20,
    unread_only: bool = False,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """List the user's most recent notifications.

    Response shape matches the dashboard JS contract:
        {"notifications": [...], "unread_count": N}
    """
    user_id = int(current_user["id"])
    limit = max(1, min(limit, 100))

    stmt = select(NotificationDB).where(NotificationDB.user_id == user_id)
    if unread_only:
        stmt = stmt.where(NotificationDB.read.is_(False))
    stmt = stmt.order_by(NotificationDB.created_at.desc()).limit(limit)

    rows = db.execute(stmt).scalars().all()

    unread_count = db.execute(
        select(NotificationDB)
        .where(NotificationDB.user_id == user_id, NotificationDB.read.is_(False))
    ).scalars().all()

    return {
        "notifications": [_to_dict(n) for n in rows],
        "unread_count": len(unread_count),
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Mark a single notification as read."""
    user_id = int(current_user["id"])
    n = db.get(NotificationDB, notification_id)
    if n is None or n.user_id != user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read = True
    db.commit()
    return {"status": "success", "id": str(n.id)}


@router.post("/read-all")
async def mark_all_read(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Mark all of the user's unread notifications as read."""
    user_id = int(current_user["id"])
    rows = db.execute(
        select(NotificationDB).where(
            NotificationDB.user_id == user_id, NotificationDB.read.is_(False)
        )
    ).scalars().all()
    for n in rows:
        n.read = True
    db.commit()
    return {"status": "success", "marked_read": len(rows)}
