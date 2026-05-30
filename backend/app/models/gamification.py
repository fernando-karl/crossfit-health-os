"""
Gamification models - streaks, badges, achievements
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
from enum import Enum


class BadgeType(str, Enum):
    FIRST_WORKOUT = "first_workout"
    WEEK_STREAK_3 = "week_streak_3"
    WEEK_STREAK_7 = "week_streak_7"
    WEEK_STREAK_30 = "week_streak_30"
    PR_BREAKER = "pr_breaker"
    MONTH_WORKER = "month_worker"
    EARLY_BIRD = "early_bird"
    NIGHT_OWL = "night_owl"
    VOLUME_KING = "volume_king"
    PERFECT_WEEK = "perfect_week"


class Badge(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    earned_at: Optional[datetime] = None

    @classmethod
    def from_db(cls, row: dict) -> "Badge":
        return cls(
            id=row["badge_id"],
            name=BADGE_DEFINITIONS.get(row["badge_id"], {}).get("name", "Unknown"),
            description=BADGE_DEFINITIONS.get(row["badge_id"], {}).get("description", ""),
            icon=BADGE_DEFINITIONS.get(row["badge_id"], {}).get("icon", "🏆"),
            earned_at=row.get("earned_at")
        )


BADGE_DEFINITIONS = {
    BadgeType.FIRST_WORKOUT: {
        "name": "First Blood",
        "description": "Complete your first workout",
        "icon": "🎯",
        "xp": 100
    },
    BadgeType.WEEK_STREAK_3: {
        "name": "Getting Warmed Up",
        "description": "3 consecutive days of training",
        "icon": "🔥",
        "xp": 200
    },
    BadgeType.WEEK_STREAK_7: {
        "name": "Week Warrior",
        "description": "7 consecutive days of training",
        "icon": "⚡",
        "xp": 500
    },
    BadgeType.WEEK_STREAK_30: {
        "name": "Iron Will",
        "description": "30 consecutive days of training",
        "icon": "💪",
        "xp": 2000
    },
    BadgeType.PR_BREAKER: {
        "name": "PR Breaker",
        "description": "Set a new personal record",
        "icon": "🏆",
        "xp": 300
    },
    BadgeType.MONTH_WORKER: {
        "name": "Monthly Warrior",
        "description": "Complete 20 workouts in a month",
        "icon": "🗓️",
        "xp": 1000
    },
    BadgeType.EARLY_BIRD: {
        "name": "Early Bird",
        "description": "Complete a workout before 7 AM",
        "icon": "🌅",
        "xp": 150
    },
    BadgeType.NIGHT_OWL: {
        "name": "Night Owl",
        "description": "Complete a workout after 9 PM",
        "icon": "🦉",
        "xp": 150
    },
    BadgeType.VOLUME_KING: {
        "name": "Volume King",
        "description": "Lift 10,000kg in a single workout",
        "icon": "👑",
        "xp": 400
    },
    BadgeType.PERFECT_WEEK: {
        "name": "Perfect Week",
        "description": "Complete all scheduled workouts in a week",
        "icon": "⭐",
        "xp": 750
    }
}


class StreakData(BaseModel):
    current_streak: int = 0
    longest_streak: int = 0
    last_workout_date: Optional[date] = None
    this_week_workouts: int = 0
    this_month_workouts: int = 0


class UserStats(BaseModel):
    total_workouts: int = 0
    total_volume_kg: float = 0
    average_rpe: float = 0
    current_streak: int = 0
    longest_streak: int = 0
    level: int = 1
    xp: int = 0
    xp_to_next_level: int = 1000
    badges: List[Badge] = []


def calculate_level(xp: int) -> tuple[int, int]:
    """Calculate level and XP needed for next level."""
    # XP requirements: 1000, 2500, 5000, 10000, etc (exponential)
    level = 1
    required_xp = 1000

    while xp >= required_xp:
        xp -= required_xp
        level += 1
        required_xp = int(required_xp * 1.5)

    return level, required_xp


def xp_for_action(action: str) -> int:
    """Get XP reward for an action."""
    xp_map = {
        "workout_complete": 200,
        "pr_set": 300,
        "streak_3": 200,
        "streak_7": 500,
        "streak_30": 2000,
        "badge_earned": 100,
        "week_complete": 500,
        "onboarding_complete": 300
    }
    return xp_map.get(action, 50)
