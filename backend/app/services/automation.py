"""
Automation service (SQLAlchemy).

Daily/weekly automation hooks. Weekly program generation is now driven through
the periodization endpoints (`/api/v1/schedule/microcycles/{id}/generate`);
this service only handles cross-user batch operations like streak checks and
onboarding email reminders.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Notification as NotificationDB, User as UserDB, WorkoutSession as WorkoutSessionDB
from app.db.session import SessionLocal


class AutomationService:
    """Batch/background tasks — always accept a Session or open one internally."""

    @staticmethod
    def generate_weekly_program_for_user(user_id: int, db: Session | None = None) -> Dict[str, Any]:
        """
        Thin shim over the ai_programmer. Generates the next microcycle in the
        user's active macrocycle (the one that contains today).
        """
        from sqlalchemy import select as _select
        from app.core.engine.ai_programmer import ai_programmer
        from app.db.models import Macrocycle, Microcycle

        close_after = db is None
        if db is None:
            db = SessionLocal()
        try:
            macro = db.execute(
                _select(Macrocycle).where(
                    Macrocycle.user_id == int(user_id),
                    Macrocycle.active.is_(True),
                ).limit(1)
            ).scalar_one_or_none()
            if not macro:
                return {"success": False, "error": "No active macrocycle"}

            today = date.today()
            micro = db.execute(
                _select(Microcycle).where(
                    Microcycle.macrocycle_id == macro.id,
                    Microcycle.start_date <= today,
                    Microcycle.end_date >= today,
                ).limit(1)
            ).scalar_one_or_none()
            if not micro:
                return {"success": False, "error": "No active microcycle covers today"}

            import asyncio
            generated = asyncio.run(
                ai_programmer.generate_microcycle_program(db=db, microcycle=micro, user_id=int(user_id))
            )
            db.add(NotificationDB(
                user_id=int(user_id),
                type="weekly_program_ready",
                title="📅 New Week, New Program!",
                body=f"Your {generated}-workout week is ready.",
                data={"workout_count": generated},
            ))
            db.commit()
            return {"success": True, "workouts_generated": generated}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if close_after:
                db.close()

    @staticmethod
    def check_and_notify_streaks(user_id: int, db: Session | None = None) -> Dict[str, Any]:
        """Warn if the user has a streak at risk (no workout today)."""
        close_after = db is None
        if db is None:
            db = SessionLocal()
        try:
            today = date.today()
            yesterday = today - timedelta(days=1)
            rows = db.execute(
                select(WorkoutSessionDB).where(
                    WorkoutSessionDB.user_id == int(user_id),
                    WorkoutSessionDB.completed_at.is_not(None),
                    WorkoutSessionDB.completed_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()),
                )
            ).scalars().all()
            completed_dates = {r.completed_at.date() for r in rows}
            current = 0
            cursor = today if today in completed_dates else yesterday
            while cursor in completed_dates:
                current += 1
                cursor -= timedelta(days=1)
            if current >= 2 and today not in completed_dates:
                db.add(NotificationDB(
                    user_id=int(user_id),
                    type="streak_warning",
                    title="🔥 Don't Lose Your Streak!",
                    body=f"You've been on a {current}-day streak. Train today to keep it alive!",
                    data={"streak": current},
                ))
                db.commit()
                return {"success": True, "warned": True, "streak": current}
            return {"success": True, "warned": False, "streak": current}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if close_after:
                db.close()

    @staticmethod
    def run_weekly_generation() -> Dict[str, Any]:
        """Run weekly generation for all users with onboarding completed
        (`preferences["onboarding_completed"] is True`)."""
        with SessionLocal() as db:
            users = db.execute(select(UserDB)).scalars().all()
            processed = 0
            successful = 0
            for user in users:
                if not (user.preferences or {}).get("onboarding_completed"):
                    continue
                processed += 1
                result = AutomationService.generate_weekly_program_for_user(user.id, db=db)
                if result.get("success"):
                    successful += 1
            return {
                "success": True,
                "users_processed": processed,
                "programs_generated": successful,
            }


def run_daily_tasks():
    """Run all daily automated tasks."""
    today = date.today()
    if today.weekday() == 0:
        result = AutomationService.run_weekly_generation()
        print(f"Weekly generation: {result}")

    with SessionLocal() as db:
        users = db.execute(select(UserDB)).scalars().all()
        for user in users:
            if (user.preferences or {}).get("onboarding_completed"):
                AutomationService.check_and_notify_streaks(user.id, db=db)


def run_automated_onboarding_email():
    """Send welcome email to users who haven't completed onboarding (placeholder)."""
    with SessionLocal() as db:
        users = db.execute(select(UserDB)).scalars().all()
        for user in users:
            if (user.preferences or {}).get("onboarding_completed"):
                continue
            print(f"Would send onboarding email to {user.email}")
