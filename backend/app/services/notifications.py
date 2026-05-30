"""
Notification service (SQLAlchemy).

Minimal persistent notifications table. User-level preferences live under
`users.preferences["notifications"]` (not a separate table). Scheduled reminders
are not implemented in this slice — the hooks return no-op results so callers
don't break.
"""
import random
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Notification as NotificationDB, User as UserDB


class NotificationType(str, Enum):
    WORKOUT_REMINDER = "workout_reminder"
    STREAK_WARNING = "streak_warning"
    STREAK_BROKEN = "streak_broken"
    WEEKLY_PROGRAM_READY = "weekly_program_ready"
    NEW_BADGE = "new_badge"
    LEVEL_UP = "level_up"
    PR_ACHIEVED = "pr_achieved"
    WEEKLY_SUMMARY = "weekly_summary"
    MOTIVATIONAL = "motivational"
    CHECK_IN = "check_in"


MOTIVATIONAL_QUOTES = [
    "The only bad workout is the one that didn't happen.",
    "Consistency beats intensity. Show up every day.",
    "Your body can stand almost anything. It's your mind you have to convince.",
    "The pain you feel today will be the strength you feel tomorrow.",
    "Don't stop when you're tired. Stop when you're done.",
    "Champions are made when no one is watching and everyone doubts.",
    "The difference between try and triumph is a little umph.",
    "You don't have to be great to start, but you have to start to be great.",
    "Every workout counts. Make today one that matters.",
    "Your only limit is you. Push harder than yesterday.",
]


class NotificationPreferences(BaseModel):
    workout_reminders: bool = True
    reminder_time: str = "07:00"
    streak_alerts: bool = True
    weekly_summary: bool = True
    motivational: bool = True
    motivational_interval: int = 3
    check_in_enabled: bool = True
    check_in_time: str = "20:00"


class NotificationService:
    """Create/list/mark-read notifications for one user."""

    def __init__(self, user_id: int | str, db: Session):
        self.user_id = int(user_id)
        self.db = db

    # ------------------------------------------------------------
    # Preferences (stored in users.preferences["notifications"])
    # ------------------------------------------------------------

    def get_user_preferences(self) -> NotificationPreferences:
        user = self.db.get(UserDB, self.user_id)
        if not user:
            return NotificationPreferences()
        raw = (user.preferences or {}).get("notifications") or {}
        try:
            return NotificationPreferences(**raw)
        except Exception:
            return NotificationPreferences()

    def update_preferences(self, prefs: NotificationPreferences) -> bool:
        user = self.db.get(UserDB, self.user_id)
        if not user:
            return False
        prefs_dict = prefs.model_dump()
        existing = dict(user.preferences or {})
        existing["notifications"] = prefs_dict
        user.preferences = existing
        self.db.commit()
        return True

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    def create_notification(
        self,
        notification_type: NotificationType,
        title: str,
        body: str,
        data: Optional[Dict] = None,
    ) -> Optional[str]:
        row = NotificationDB(
            user_id=self.user_id,
            type=notification_type.value,
            title=title,
            body=body,
            data=data or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return str(row.id)

    def get_notifications(self, limit: int = 20, unread_only: bool = False) -> List[Dict]:
        stmt = select(NotificationDB).where(NotificationDB.user_id == self.user_id)
        if unread_only:
            stmt = stmt.where(NotificationDB.read.is_(False))
        stmt = stmt.order_by(NotificationDB.created_at.desc()).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        return [
            {
                "id": str(r.id),
                "type": r.type,
                "title": r.title,
                "body": r.body,
                "data": r.data or {},
                "read": r.read,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def get_unread_count(self) -> int:
        from sqlalchemy import func
        return self.db.execute(
            select(func.count(NotificationDB.id)).where(
                NotificationDB.user_id == self.user_id,
                NotificationDB.read.is_(False),
            )
        ).scalar_one()

    def mark_as_read(self, notification_id: str) -> bool:
        from uuid import UUID as _UUID
        try:
            nid = _UUID(notification_id)
        except (TypeError, ValueError):
            return False
        row = self.db.get(NotificationDB, nid)
        if not row or row.user_id != self.user_id:
            return False
        row.read = True
        self.db.commit()
        return True

    def mark_all_read(self) -> bool:
        rows = self.db.execute(
            select(NotificationDB).where(
                NotificationDB.user_id == self.user_id,
                NotificationDB.read.is_(False),
            )
        ).scalars().all()
        for r in rows:
            r.read = True
        self.db.commit()
        return True

    def cleanup_old_notifications(self, days: int = 30) -> int:
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = self.db.execute(
            select(NotificationDB).where(
                NotificationDB.user_id == self.user_id,
                NotificationDB.read.is_(True),
                NotificationDB.created_at < cutoff,
            )
        ).scalars().all()
        for r in rows:
            self.db.delete(r)
        self.db.commit()
        return len(rows)

    # ------------------------------------------------------------
    # Scheduled reminders (not persisted in this slice)
    # ------------------------------------------------------------

    def schedule_workout_reminder(self, day: str, time_str: str) -> Dict:
        return {"success": False, "reason": "Scheduled reminders not implemented in this slice"}

    # ------------------------------------------------------------
    # Convenience emitters
    # ------------------------------------------------------------

    def send_streak_warning(self, current_streak: int) -> Optional[str]:
        if not self.get_user_preferences().streak_alerts:
            return None
        return self.create_notification(
            NotificationType.STREAK_WARNING,
            "🔥 Don't Lose Your Streak!",
            f"You've been on a {current_streak}-day streak. Train today to keep it alive!",
            {"streak": current_streak},
        )

    def send_streak_broken(self, previous_streak: int) -> Optional[str]:
        if not self.get_user_preferences().streak_alerts:
            return None
        return self.create_notification(
            NotificationType.STREAK_BROKEN,
            "😔 Streak Lost",
            f"Your {previous_streak}-day streak ended. Start a new one today!",
            {"previous_streak": previous_streak},
        )

    def send_new_badge(self, badge_name: str, badge_icon: str, xp_earned: int) -> Optional[str]:
        return self.create_notification(
            NotificationType.NEW_BADGE,
            f"{badge_icon} Badge Earned!",
            f"You unlocked '{badge_name}'! +{xp_earned} XP",
            {"badge_name": badge_name, "xp": xp_earned},
        )

    def send_level_up(self, new_level: int) -> Optional[str]:
        return self.create_notification(
            NotificationType.LEVEL_UP,
            "🎉 Level Up!",
            f"Congratulations! You've reached Level {new_level}!",
            {"level": new_level},
        )

    def send_weekly_summary(self, stats: Dict) -> Optional[str]:
        if not self.get_user_preferences().weekly_summary:
            return None
        workouts = stats.get("workouts", 0)
        volume = stats.get("volume_kg", 0) or 0
        avg_rpe = stats.get("avg_rpe", 0) or 0
        return self.create_notification(
            NotificationType.WEEKLY_SUMMARY,
            "📊 Weekly Summary",
            f"You completed {workouts} workouts, {volume/1000:.1f}t total volume, avg RPE {avg_rpe:.1f}/10",
            stats,
        )

    def send_motivational(self) -> Optional[str]:
        if not self.get_user_preferences().motivational:
            return None
        quote = random.choice(MOTIVATIONAL_QUOTES)
        return self.create_notification(
            NotificationType.MOTIVATIONAL,
            "💪 Stay Strong",
            quote,
            {},
        )

    def send_check_in(self) -> Optional[str]:
        if not self.get_user_preferences().check_in_enabled:
            return None
        return self.create_notification(
            NotificationType.CHECK_IN,
            "📝 How are you feeling?",
            "Log your recovery metrics to get personalized workout recommendations.",
            {"action": "log_recovery"},
        )
