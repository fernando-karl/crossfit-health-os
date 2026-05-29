"""Referral code generation + reward computation.

Codes are human-friendly: a name slug followed by random digits, e.g.
``fernando42``. Each user gets exactly one code. The reward for both
sides is currently expressed as a credit-month count, computed on the
fly from the ``referrals`` table — stored as intent until checkout is
wired.
"""
from __future__ import annotations

import random
import re
import unicodedata
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReferralCode, Referral

# Both inviter and referee get 1 free month each time someone they
# invited becomes a paying user. Held as intent — applied at checkout.
REWARD_MONTHS_PER_CONVERSION = 1
MAX_CODE_LEN = 12
DIGIT_RETRIES = 6  # tries at 2 digits, then 3, then 4 — increasing entropy


def _slugify_name(name: Optional[str]) -> str:
    """Best-effort ascii slug of a name. Falls back to ``athlete``."""
    if not name:
        return "athlete"
    # Strip accents, lowercase, keep [a-z]
    norm = unicodedata.normalize("NFKD", name)
    ascii_only = norm.encode("ascii", "ignore").decode("ascii").lower()
    first = ascii_only.strip().split()[0] if ascii_only.strip() else ""
    cleaned = re.sub(r"[^a-z]", "", first)
    return cleaned[:MAX_CODE_LEN - 2] or "athlete"


def generate_unique_code(name: Optional[str], db: Session) -> str:
    """Build a unique referral code from ``name``, retrying on collision."""
    slug = _slugify_name(name)
    for digits in (2, 3, 4):
        for _ in range(DIGIT_RETRIES):
            suffix = "".join(str(random.randint(0, 9)) for _ in range(digits))
            candidate = f"{slug}{suffix}"[:MAX_CODE_LEN]
            existing = db.execute(
                select(ReferralCode).where(ReferralCode.code == candidate)
            ).scalar_one_or_none()
            if existing is None:
                return candidate
    # Pathological: 18 collisions in a row. Append a longer random tail.
    tail = "".join(str(random.randint(0, 9)) for _ in range(6))
    return f"{slug[:MAX_CODE_LEN - 6]}{tail}"


def get_or_create_code(user_id: int, name: Optional[str], db: Session) -> ReferralCode:
    """Return the user's referral code, creating one if absent."""
    existing = db.execute(
        select(ReferralCode).where(ReferralCode.user_id == user_id)
    ).scalar_one_or_none()
    if existing:
        return existing
    code = ReferralCode(user_id=user_id, code=generate_unique_code(name, db))
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


def count_referrals(code_id, db: Session) -> tuple[int, int]:
    """Return (total_signups, converted_count) for a code."""
    rows = db.execute(
        select(Referral).where(Referral.code_id == code_id)
    ).scalars().all()
    total = len(rows)
    converted = sum(1 for r in rows if r.status == "converted")
    return total, converted


def reward_months_earned(converted_count: int) -> int:
    return converted_count * REWARD_MONTHS_PER_CONVERSION
