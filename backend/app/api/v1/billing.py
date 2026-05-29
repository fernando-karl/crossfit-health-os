"""Billing endpoints — Stripe wired.

Returns 501 with ``code='stripe_not_configured'`` when Stripe is not set up
(no STRIPE_SECRET_KEY). Once configured, the endpoints create real Stripe
sessions; the source of truth for subscription state is the webhook.

Endpoints:
- POST /checkout → ``{checkout_url}`` redirect target
- GET  /portal   → ``{portal_url}`` Customer Portal
- POST /cancel   → cancels at period end (webhook flips status when Stripe
                    confirms the cancellation)
- POST /webhook  → Stripe → backend; updates subscription_status, converts
                    referrals, grants inviter rewards
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core import stripe_client
from app.db.models import User as UserDB
from app.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

_NOT_CONFIGURED = {
    "code": "stripe_not_configured",
    "message": "Payments are not yet enabled. Coming soon.",
}


def _stripe_ready() -> None:
    if not (settings.STRIPE_SECRET_KEY or "").strip():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_CONFIGURED
        )


def _frontend_base(request: Request) -> str:
    """Use the request's own base when FRONTEND_URL points at a stale port (dev)."""
    base = (settings.FRONTEND_URL or "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return base


# ----------------------------------------------------------------
# Checkout
# ----------------------------------------------------------------

@router.post("/checkout")
async def create_checkout_session(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Create a Stripe Checkout Session for the $29/mo subscription."""
    _stripe_ready()

    user = db.get(UserDB, int(current_user["id"]))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    customer_id = stripe_client.ensure_customer(
        user_email=user.email,
        user_id=user.id,
        existing_customer_id=user.stripe_customer_id,
    )
    if user.stripe_customer_id != customer_id:
        user.stripe_customer_id = customer_id
        db.commit()

    price_id = stripe_client.ensure_price()

    base = _frontend_base(request)
    session = stripe_client.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=f"{base}/dashboard/billing?status=ok&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}/dashboard/billing?status=canceled",
    )
    return {"checkout_url": session.url}


# ----------------------------------------------------------------
# Customer Portal (manage subscription, payment method, invoices)
# ----------------------------------------------------------------

@router.get("/portal")
async def get_customer_portal(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    _stripe_ready()
    user = db.get(UserDB, int(current_user["id"]))
    if user is None or not user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer on file. Subscribe first.",
        )
    base = _frontend_base(request)
    session = stripe_client.create_portal_session(
        customer_id=user.stripe_customer_id,
        return_url=f"{base}/dashboard/billing",
    )
    return {"portal_url": session.url}


# ----------------------------------------------------------------
# Cancel at period end
# ----------------------------------------------------------------

@router.post("/cancel")
async def cancel_subscription(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    _stripe_ready()
    user = db.get(UserDB, int(current_user["id"]))
    if user is None or not user.subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    sub = stripe_client.cancel_at_period_end(user.subscription_id)
    return {
        "status": "scheduled_cancel",
        "current_period_end": getattr(sub, "current_period_end", None),
    }


# ----------------------------------------------------------------
# Webhook (Stripe → us). Source of truth for status transitions.
# ----------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_session),
):
    """Stripe → backend. Verifies signature, then updates user state.

    Events handled:
    - ``checkout.session.completed``        — first paid checkout, set status active
    - ``invoice.paid``                       — convert any pending referral, grant inviter
    - ``customer.subscription.updated``      — track status (past_due / active)
    - ``customer.subscription.deleted``      — final cancellation
    """
    if not (settings.STRIPE_WEBHOOK_SECRET or "").strip():
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET not configured")

    payload = await request.body()
    try:
        event = stripe_client.verify_webhook(payload, stripe_signature or "")
    except Exception as e:  # noqa: BLE001
        logger.warning("stripe webhook signature failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        _on_checkout_completed(db, data)
    elif etype == "invoice.paid":
        _on_invoice_paid(db, data)
    elif etype == "customer.subscription.updated":
        _on_subscription_updated(db, data)
    elif etype == "customer.subscription.deleted":
        _on_subscription_deleted(db, data)
    else:
        logger.info("stripe webhook unhandled type: %s", etype)

    return {"received": True}


# ---- Webhook handlers ----

def _user_by_customer(db: Session, customer_id: str | None) -> UserDB | None:
    if not customer_id:
        return None
    return db.execute(
        select(UserDB).where(UserDB.stripe_customer_id == customer_id)
    ).scalar_one_or_none()


def _on_checkout_completed(db: Session, session: dict) -> None:
    user = _user_by_customer(db, session.get("customer"))
    if not user:
        logger.warning("checkout.session.completed: no user for customer %s", session.get("customer"))
        return
    user.subscription_status = "active"
    user.subscription_id = session.get("subscription") or user.subscription_id
    db.commit()


def _on_subscription_updated(db: Session, sub: dict) -> None:
    user = _user_by_customer(db, sub.get("customer"))
    if not user:
        return
    # Stripe statuses: active | past_due | canceled | incomplete | trialing | unpaid
    status_map = {
        "active": "active",
        "trialing": "active",  # paid trial — still gives access
        "past_due": "past_due",
        "unpaid": "past_due",
        "canceled": "canceled",
        "incomplete": "past_due",
        "incomplete_expired": "canceled",
    }
    user.subscription_status = status_map.get(sub.get("status"), user.subscription_status)
    user.subscription_id = sub.get("id") or user.subscription_id
    db.commit()


def _on_subscription_deleted(db: Session, sub: dict) -> None:
    user = _user_by_customer(db, sub.get("customer"))
    if not user:
        return
    user.subscription_status = "canceled"
    db.commit()


def _on_invoice_paid(db: Session, invoice: dict) -> None:
    """First successful payment: mark active and convert any pending referral.

    The inviter receives a one-month credit on their next invoice.
    """
    user = _user_by_customer(db, invoice.get("customer"))
    if not user:
        return
    user.subscription_status = "active"
    db.commit()

    # Referral conversion — only on the FIRST paid invoice for this user.
    from app.db.models import Referral as ReferralDB, ReferralCode as ReferralCodeDB
    referral = db.execute(
        select(ReferralDB).where(
            ReferralDB.referred_user_id == user.id,
            ReferralDB.status == "pending",
        )
    ).scalar_one_or_none()
    if not referral:
        return

    from datetime import datetime
    referral.status = "converted"
    referral.converted_at = datetime.utcnow()
    db.commit()

    # Credit the inviter (one month free on their next invoice).
    code = db.get(ReferralCodeDB, referral.code_id)
    if not code:
        return
    inviter = db.get(UserDB, code.user_id)
    if not inviter or not inviter.stripe_customer_id:
        logger.info(
            "referral converted but inviter %s has no stripe_customer_id; "
            "credit will be applied when they subscribe",
            code.user_id,
        )
        return
    try:
        stripe_client.grant_one_month_coupon(
            customer_id=inviter.stripe_customer_id,
            reason=f"referral_{referral.id}",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("failed to credit inviter %s: %s", inviter.id, e)
