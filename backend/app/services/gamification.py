"""
Gamification service (SQLAlchemy).

Streaks, badges, XP. Takes a `Session` in the constructor so callers control
the transaction lifecycle.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Macrocycle as MacrocycleDB,
    Microcycle as MicrocycleDB,
    PlannedSession as PlannedSessionDB,
    UserBadge,
    UserStatsRow,
    WorkoutSession as WorkoutSessionDB,
)
from app.models.gamification import (
    BADGE_DEFINITIONS,
    Badge,
    BadgeType,
    StreakData,
    UserStats,
    calculate_level,
    xp_for_action,
)


class GamificationService:
    """Service for managing user gamification elements."""

    def __init__(self, user_id: int, db: Session):
        self.user_id = int(user_id)
        self.db = db

    # ------------------------------------------------------------
    # Read-side helpers
    # ------------------------------------------------------------

    def _get_user_sessions(self) -> List[WorkoutSessionDB]:
        return self.db.execute(
            select(WorkoutSessionDB)
            .where(WorkoutSessionDB.user_id == self.user_id)
            .order_by(WorkoutSessionDB.started_at.desc())
        ).scalars().all()

    def _get_stats_row(self) -> UserStatsRow:
        row = self.db.get(UserStatsRow, self.user_id)
        if not row:
            row = UserStatsRow(user_id=self.user_id)
            self.db.add(row)
            self.db.flush()
        return row

    def _get_user_xp(self) -> int:
        row = self.db.get(UserStatsRow, self.user_id)
        return row.xp if row else 0

    def _get_user_badges(self) -> List[Badge]:
        rows = self.db.execute(
            select(UserBadge).where(UserBadge.user_id == self.user_id)
        ).scalars().all()
        return [
            Badge(
                id=r.badge_id,
                name=BADGE_DEFINITIONS.get(r.badge_id, {}).get("name", "Unknown"),
                description=BADGE_DEFINITIONS.get(r.badge_id, {}).get("description", ""),
                icon=BADGE_DEFINITIONS.get(r.badge_id, {}).get("icon", "🏆"),
                earned_at=r.earned_at,
            )
            for r in rows
        ]

    # ------------------------------------------------------------
    # Streak calculation (uses completed_at on WorkoutSession)
    # ------------------------------------------------------------

    def _calculate_streak(self, sessions: Optional[List[WorkoutSessionDB]] = None) -> StreakData:
        if sessions is None:
            sessions = self._get_user_sessions()

        streak = StreakData()
        completed_dates = {
            s.completed_at.date()
            for s in sessions
            if s.completed_at
        }
        if not completed_dates:
            return streak

        sorted_dates = sorted(completed_dates, reverse=True)
        streak.last_workout_date = sorted_dates[0]

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        streak.this_week_workouts = len([d for d in completed_dates if d >= week_start])
        streak.this_month_workouts = len([d for d in completed_dates if d >= month_start])

        current = 0
        check = today
        if check not in completed_dates:
            check -= timedelta(days=1)
        while check in completed_dates:
            current += 1
            check -= timedelta(days=1)

        streak.current_streak = current
        streak.longest_streak = max(current, self._longest_streak_from_set(completed_dates))
        return streak

    @staticmethod
    def _longest_streak_from_set(dates: set[date]) -> int:
        if not dates:
            return 0
        sorted_dates = sorted(dates)
        longest = current = 1
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1
        return longest

    # ------------------------------------------------------------
    # XP & level
    # ------------------------------------------------------------

    def get_user_stats(self) -> UserStats:
        stats = UserStats()
        sessions = self._get_user_sessions()
        stats.total_workouts = len([s for s in sessions if s.completed_at])

        streak = self._calculate_streak(sessions)
        stats.current_streak = streak.current_streak
        stats.longest_streak = streak.longest_streak

        stats.xp = self._get_user_xp()
        stats.level, stats.xp_to_next_level = calculate_level(stats.xp)

        stats.badges = self._get_user_badges()

        completed_with_rpe = [s for s in sessions if s.rpe_score is not None]
        if completed_with_rpe:
            stats.average_rpe = sum(s.rpe_score for s in completed_with_rpe) / len(completed_with_rpe)
        return stats

    def add_xp(self, amount: int) -> tuple[int, int]:
        """Add XP to user and return (new_level, new_xp)."""
        row = self._get_stats_row()
        row.xp += amount
        new_level, _xp_needed = calculate_level(row.xp)
        row.level = new_level
        row.updated_at = datetime.utcnow()
        self.db.commit()
        return new_level, row.xp

    # ------------------------------------------------------------
    # Badges
    # ------------------------------------------------------------

    def _award_badge(self, badge_id: str) -> Optional[Badge]:
        existing = self.db.execute(
            select(UserBadge).where(
                UserBadge.user_id == self.user_id,
                UserBadge.badge_id == badge_id,
            )
        ).scalar_one_or_none()
        if existing:
            return None
        row = UserBadge(user_id=self.user_id, badge_id=badge_id)
        self.db.add(row)
        self.db.commit()
        return Badge(
            id=row.badge_id,
            name=BADGE_DEFINITIONS.get(row.badge_id, {}).get("name", "Unknown"),
            description=BADGE_DEFINITIONS.get(row.badge_id, {}).get("description", ""),
            icon=BADGE_DEFINITIONS.get(row.badge_id, {}).get("icon", "🏆"),
            earned_at=row.earned_at,
        )

    def check_and_award_badges(self, session_data: Optional[Dict] = None) -> List[Badge]:
        new_badges: List[Badge] = []
        existing_ids = {b.id for b in self._get_user_badges()}
        sessions = self._get_user_sessions()
        streak = self._calculate_streak(sessions)

        def _maybe(badge_type: BadgeType, condition: bool):
            if badge_type.value in existing_ids or not condition:
                return
            badge = self._award_badge(badge_type.value)
            if badge:
                new_badges.append(badge)
                existing_ids.add(badge.id)

        _maybe(BadgeType.FIRST_WORKOUT, len([s for s in sessions if s.completed_at]) >= 1)
        _maybe(BadgeType.WEEK_STREAK_3, streak.current_streak >= 3)
        _maybe(BadgeType.WEEK_STREAK_7, streak.current_streak >= 7)
        _maybe(BadgeType.WEEK_STREAK_30, streak.current_streak >= 30)
        _maybe(BadgeType.MONTH_WORKER, streak.this_month_workouts >= 20)
        _maybe(BadgeType.PERFECT_WEEK, self._check_perfect_week(streak))

        if session_data:
            hour = datetime.now().hour
            _maybe(BadgeType.EARLY_BIRD, hour < 7)
            _maybe(BadgeType.NIGHT_OWL, hour >= 21)
            volume = session_data.get("total_volume_kg", 0) or 0
            _maybe(BadgeType.VOLUME_KING, volume >= 10000)

        return new_badges

    def _check_perfect_week(self, streak: StreakData) -> bool:
        """Did the user hit every scheduled planned_session this week?"""
        today = date.today()

        macro = self.db.execute(
            select(MacrocycleDB).where(
                MacrocycleDB.user_id == self.user_id, MacrocycleDB.active.is_(True)
            ).limit(1)
        ).scalar_one_or_none()
        if not macro:
            return False

        micro = self.db.execute(
            select(MicrocycleDB).where(
                MicrocycleDB.macrocycle_id == macro.id,
                MicrocycleDB.start_date <= today,
                MicrocycleDB.end_date >= today,
            ).limit(1)
        ).scalar_one_or_none()
        if not micro:
            return False

        scheduled = self.db.execute(
            select(PlannedSessionDB).where(PlannedSessionDB.microcycle_id == micro.id)
        ).scalars().all()
        return streak.this_week_workouts >= len(scheduled) > 0

    # ------------------------------------------------------------
    # Workout completion hook
    # ------------------------------------------------------------

    def record_workout_complete(self, session_data: Dict) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "new_badges": [],
            "xp_earned": 0,
            "level_up": False,
            "old_level": 0,
            "new_level": 0,
        }
        old_xp = self._get_user_xp()
        old_level, _ = calculate_level(old_xp)
        result["old_level"] = old_level

        xp_earned = xp_for_action("workout_complete")
        streak = self._calculate_streak()
        if streak.current_streak >= 3:
            xp_earned += xp_for_action("streak_3")
        if streak.current_streak >= 7:
            xp_earned += xp_for_action("streak_7")
        result["xp_earned"] = xp_earned

        new_level, _ = self.add_xp(xp_earned)
        result["new_level"] = new_level
        result["level_up"] = new_level > old_level

        new_badges = self.check_and_award_badges(session_data)
        result["new_badges"] = [
            {"id": b.id, "name": b.name, "icon": b.icon} for b in new_badges
        ]

        for badge in new_badges:
            xp = BADGE_DEFINITIONS.get(badge.id, {}).get("xp", 100)
            if xp:
                self.add_xp(xp)

        return result
