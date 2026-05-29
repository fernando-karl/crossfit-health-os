"""Weekly review scheduler — generates last-week review for every active user.

Triggered by an external cron (Coolify cron job → POST
``/api/v1/internal/cron/weekly-reviews`` with the ``X-Internal-Cron-Secret``
header). Idempotent: if a review for the same week already exists, skip.

Run cadence: weekly on Sunday morning UTC. Each call processes the
"last full week" (Mon→Sun ending today minus N days, depending on when
the cron fires). The default `target_week_for(today)` returns the most
recent Mon→Sun window that is fully in the past.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.engine.weekly_reviewer import weekly_reviewer
from app.db.models import User as UserDB, WeeklyReview as WeeklyReviewDB
from app.db import session as _db_session_module

logger = logging.getLogger(__name__)


def target_week_for(today: date) -> Tuple[date, date]:
    """Return (week_start, week_end) of the most recent fully-elapsed Mon→Sun.

    Operator note: schedule the cron for **Monday morning** so this returns
    the week that just ended (Mon-Sun ending yesterday). A Sunday-morning
    cron returns the week ending the *previous* Sunday — Sundays' data
    isn't fully in yet so we don't process a half-elapsed week.

    Examples (today.weekday(): 0=Mon..6=Sun):
        - today=Mon May 11 → returns Mon May 4 .. Sun May 10 (week just ended)
        - today=Sun May 10 → returns Mon Apr 27 .. Sun May 3 (one week prior)
    """
    days_since_monday = today.weekday()  # 0..6
    # Monday of the most recent fully-elapsed Mon-Sun window.
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def _eligible_user_ids(db: Session) -> Iterable[int]:
    """Active subscribers + still-trialing users."""
    rows = db.execute(select(UserDB.id, UserDB.subscription_status, UserDB.trial_expires_at)).all()
    now = datetime.utcnow()
    for uid, status, trial_expires in rows:
        s = (status or "trialing").lower()
        if s == "active":
            yield uid
        elif s == "trialing" and trial_expires and trial_expires > now:
            yield uid


def _already_has_review(db: Session, user_id: int, week_start: date) -> bool:
    row = db.execute(
        select(WeeklyReviewDB.id).where(
            WeeklyReviewDB.user_id == user_id,
            WeeklyReviewDB.week_start_date == week_start,
        )
    ).first()
    return row is not None


async def run_weekly_reviews(today: date | None = None) -> dict:
    """Generate the prior-week review for every eligible user.

    Returns a summary dict (counts by outcome). Failures on a single user
    are logged and skipped — one bad user must not break the batch.
    """
    today = today or date.today()
    week_start, week_end = target_week_for(today)
    summary = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "generated": 0,
        "skipped_existing": 0,
        "failed": 0,
        "considered": 0,
    }

    with _db_session_module.SessionLocal() as db:
        user_ids = list(_eligible_user_ids(db))

    summary["considered"] = len(user_ids)

    for user_id in user_ids:
        with _db_session_module.SessionLocal() as db:
            try:
                if _already_has_review(db, user_id, week_start):
                    summary["skipped_existing"] += 1
                    continue
                # Week number = consecutive count + 1. Cheap heuristic; the
                # review engine itself can override if it needs program-aware
                # numbering.
                count = db.execute(
                    select(WeeklyReviewDB.id).where(WeeklyReviewDB.user_id == user_id)
                ).all()
                week_number = len(count) + 1

                await weekly_reviewer.generate_weekly_review(
                    user_id=user_id,
                    week_number=week_number,
                    week_start=week_start,
                    week_end=week_end,
                    db=db,
                )
                summary["generated"] += 1
            except Exception as e:  # noqa: BLE001 — one bad user must not stop the batch
                logger.exception("weekly review failed for user %s: %s", user_id, e)
                summary["failed"] += 1

    return summary
