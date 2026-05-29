"""Referrals API — user-to-user invite codes.

Each user has one human-friendly code (e.g. ``fernando42``). Sharing
that code with a friend who signs up grants both sides one free month
once the friend becomes a paying user. The reward is recorded as
intent in the ``referrals`` table; checkout will read from it.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.referrals import (
    REWARD_MONTHS_PER_CONVERSION,
    count_referrals,
    get_or_create_code,
    reward_months_earned,
)
from app.db.models import Referral as ReferralDB, ReferralCode as ReferralCodeDB, User as UserDB
from app.db.session import get_session
from app.models.referrals import (
    RedeemRequest,
    RedeemResponse,
    ReferralCodeResponse,
    ReferralListItem,
    ReferralListResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/referrals", tags=["referrals"])


def _share_url(request: Request, code: str) -> str:
    """Build a public signup URL with the code prefilled.

    Uses the request's own scheme+host so dev (localhost:8001) and prod
    work without extra config. Falls back to ``settings.FRONTEND_URL``.
    """
    base = str(request.base_url).rstrip("/") if request.base_url else settings.FRONTEND_URL.rstrip("/")
    return f"{base}/register?ref={code}"


@router.get("/me", response_model=ReferralCodeResponse)
def get_my_code(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Return the caller's referral code, creating one on first call."""
    user = db.execute(select(UserDB).where(UserDB.id == current_user["id"])).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    code = get_or_create_code(user.id, user.name, db)
    total, converted = count_referrals(code.id, db)
    return ReferralCodeResponse(
        code=code.code,
        share_url=_share_url(request, code.code),
        total_signups=total,
        converted_count=converted,
        months_earned=reward_months_earned(converted),
    )


@router.post("/redeem", response_model=RedeemResponse)
def redeem_code(
    payload: RedeemRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Apply someone else's referral code to the caller.

    Rejects: unknown codes, self-redeem, double-redeem, inactive codes.
    """
    code_norm = payload.code.strip().lower()
    referral_code = db.execute(
        select(ReferralCodeDB).where(ReferralCodeDB.code == code_norm)
    ).scalar_one_or_none()
    if referral_code is None or not referral_code.active:
        raise HTTPException(status_code=404, detail="Code not found or inactive")

    referee_id = current_user["id"]
    if referral_code.user_id == referee_id:
        raise HTTPException(status_code=400, detail="Cannot redeem your own code")

    already_redeemed = db.execute(
        select(ReferralDB).where(ReferralDB.referred_user_id == referee_id)
    ).scalar_one_or_none()
    if already_redeemed is not None:
        raise HTTPException(status_code=409, detail="A referral code was already applied")

    referral = ReferralDB(
        code_id=referral_code.id,
        referred_user_id=referee_id,
        status="pending",
    )
    db.add(referral)
    db.commit()

    inviter = db.execute(select(UserDB).where(UserDB.id == referral_code.user_id)).scalar_one_or_none()
    inviter_first_name = (inviter.name.split()[0] if inviter and inviter.name else None)

    return RedeemResponse(
        ok=True,
        code=referral_code.code,
        inviter_name=inviter_first_name,
        months_credit=REWARD_MONTHS_PER_CONVERSION,
    )


@router.get("/me/list", response_model=ReferralListResponse)
def list_my_referrals(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """List people who used my code, anonymized to first name + date + status."""
    code = db.execute(
        select(ReferralCodeDB).where(ReferralCodeDB.user_id == current_user["id"])
    ).scalar_one_or_none()
    if code is None:
        return ReferralListResponse(items=[])

    referrals = db.execute(
        select(ReferralDB).where(ReferralDB.code_id == code.id).order_by(ReferralDB.created_at.desc())
    ).scalars().all()

    items = []
    for ref in referrals:
        referee = db.execute(select(UserDB).where(UserDB.id == ref.referred_user_id)).scalar_one_or_none()
        first = (referee.name.split()[0] if referee and referee.name else "Athlete")
        items.append(ReferralListItem(
            referee_name=first,
            joined_at=ref.created_at,
            status=ref.status,
        ))
    return ReferralListResponse(items=items)
