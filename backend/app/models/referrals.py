"""Pydantic schemas for /api/v1/referrals."""
from __future__ import annotations

from datetime import datetime as _Datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReferralCodeResponse(BaseModel):
    code: str
    share_url: str
    total_signups: int = 0
    converted_count: int = 0
    months_earned: int = 0


class RedeemRequest(BaseModel):
    code: str = Field(min_length=2, max_length=24)


class RedeemResponse(BaseModel):
    ok: bool
    code: str
    inviter_name: Optional[str] = None
    months_credit: int = 1


class ReferralListItem(BaseModel):
    referee_name: str  # first name only
    joined_at: _Datetime
    status: str  # pending | converted


class ReferralListResponse(BaseModel):
    items: List[ReferralListItem]
