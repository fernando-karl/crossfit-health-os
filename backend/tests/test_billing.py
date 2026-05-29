"""Tests for billing — stubs (501 when not configured), real flows when wired,
and webhook event handling including referral conversion."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


def _stripe_off(monkeypatch):
    """Force the 501-not-configured path."""
    monkeypatch.setattr("app.core.config.settings.STRIPE_SECRET_KEY", "")


def _stripe_on(monkeypatch, *, with_webhook_secret: bool = True):
    monkeypatch.setattr("app.core.config.settings.STRIPE_SECRET_KEY", "sk_test_x")
    if with_webhook_secret:
        monkeypatch.setattr("app.core.config.settings.STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setattr("app.core.config.settings.STRIPE_PRICE_ID", "price_test_123")


# ==========================================================
# 501 when Stripe is not configured
# ==========================================================

@pytest.mark.asyncio
class TestStripeNotConfigured:
    async def test_checkout_returns_501(self, authenticated_client: AsyncClient, monkeypatch):
        _stripe_off(monkeypatch)
        r = await authenticated_client.post("/api/v1/billing/checkout", json={})
        assert r.status_code == 501
        assert r.json()["detail"]["code"] == "stripe_not_configured"

    async def test_portal_returns_501(self, authenticated_client: AsyncClient, monkeypatch):
        _stripe_off(monkeypatch)
        r = await authenticated_client.get("/api/v1/billing/portal")
        assert r.status_code == 501

    async def test_cancel_returns_501(self, authenticated_client: AsyncClient, monkeypatch):
        _stripe_off(monkeypatch)
        r = await authenticated_client.post("/api/v1/billing/cancel", json={})
        assert r.status_code == 501

    async def test_endpoints_require_auth(self, async_client: AsyncClient):
        r = await async_client.post("/api/v1/billing/checkout", json={})
        assert r.status_code in (401, 403)


# ==========================================================
# /checkout — happy path with mocked Stripe client
# ==========================================================

@pytest.mark.asyncio
class TestCheckout:
    async def test_creates_session_and_caches_customer_id(
        self, authenticated_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        with patch("app.api.v1.billing.stripe_client.ensure_customer", return_value="cus_42") as ensure_cust, \
             patch("app.api.v1.billing.stripe_client.ensure_price", return_value="price_test_123"), \
             patch(
                 "app.api.v1.billing.stripe_client.create_checkout_session",
                 return_value=SimpleNamespace(url="https://checkout.stripe.com/fake-session")
             ) as create_sess:
            r = await authenticated_client.post("/api/v1/billing/checkout", json={})

        assert r.status_code == 200, r.text
        assert r.json()["checkout_url"] == "https://checkout.stripe.com/fake-session"
        ensure_cust.assert_called_once()
        # Customer id is persisted on the user row.
        db_session.expire_all()
        from app.db.models import User as UserDB
        u = db_session.get(UserDB, seeded_user.id)
        assert u.stripe_customer_id == "cus_42"

        # Checkout was called with the right price + url placeholders.
        kwargs = create_sess.call_args.kwargs
        assert kwargs["price_id"] == "price_test_123"
        assert "/dashboard/billing?status=ok" in kwargs["success_url"]
        assert "/dashboard/billing?status=canceled" in kwargs["cancel_url"]


# ==========================================================
# /portal — needs an existing customer id
# ==========================================================

@pytest.mark.asyncio
class TestPortal:
    async def test_400_when_no_customer(
        self, authenticated_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        r = await authenticated_client.get("/api/v1/billing/portal")
        assert r.status_code == 400

    async def test_returns_portal_url(
        self, authenticated_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        seeded_user.stripe_customer_id = "cus_42"
        db_session.commit()
        with patch(
            "app.api.v1.billing.stripe_client.create_portal_session",
            return_value=SimpleNamespace(url="https://billing.stripe.com/p/portal-fake"),
        ):
            r = await authenticated_client.get("/api/v1/billing/portal")
        assert r.status_code == 200
        assert r.json()["portal_url"].startswith("https://billing.stripe.com")


# ==========================================================
# /cancel — schedules at period end via subscription.modify
# ==========================================================

@pytest.mark.asyncio
class TestCancel:
    async def test_400_without_subscription(
        self, authenticated_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        r = await authenticated_client.post("/api/v1/billing/cancel", json={})
        assert r.status_code == 400

    async def test_calls_modify_with_period_end(
        self, authenticated_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        seeded_user.subscription_id = "sub_42"
        db_session.commit()
        with patch(
            "app.api.v1.billing.stripe_client.cancel_at_period_end",
            return_value=SimpleNamespace(current_period_end=1_700_000_000),
        ) as cancel_call:
            r = await authenticated_client.post("/api/v1/billing/cancel", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "scheduled_cancel"
        assert body["current_period_end"] == 1_700_000_000
        cancel_call.assert_called_once_with("sub_42")


# ==========================================================
# /webhook — signature verification + handlers
# ==========================================================

@pytest.mark.asyncio
class TestWebhook:
    async def test_503_when_secret_missing(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.STRIPE_WEBHOOK_SECRET", "")
        r = await async_client.post(
            "/api/v1/billing/webhook", content=b"{}",
            headers={"Stripe-Signature": "x"},
        )
        assert r.status_code == 503

    async def test_400_on_bad_signature(self, async_client: AsyncClient, monkeypatch):
        _stripe_on(monkeypatch)
        with patch(
            "app.api.v1.billing.stripe_client.verify_webhook",
            side_effect=Exception("bad sig"),
        ):
            r = await async_client.post(
                "/api/v1/billing/webhook", content=b"{}",
                headers={"Stripe-Signature": "garbage"},
            )
        assert r.status_code == 400

    async def test_checkout_completed_marks_active(
        self, async_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        seeded_user.stripe_customer_id = "cus_42"
        seeded_user.subscription_status = "trialing"
        db_session.commit()

        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_42", "subscription": "sub_42"}},
        }
        with patch("app.api.v1.billing.stripe_client.verify_webhook", return_value=event):
            r = await async_client.post(
                "/api/v1/billing/webhook", content=b"{}",
                headers={"Stripe-Signature": "x"},
            )
        assert r.status_code == 200, r.text

        from app.db.models import User as UserDB
        db_session.expire_all()
        u = db_session.get(UserDB, seeded_user.id)
        assert u.subscription_status == "active"
        assert u.subscription_id == "sub_42"

    async def test_subscription_deleted_marks_canceled(
        self, async_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        seeded_user.stripe_customer_id = "cus_42"
        seeded_user.subscription_status = "active"
        db_session.commit()

        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_42"}},
        }
        with patch("app.api.v1.billing.stripe_client.verify_webhook", return_value=event):
            r = await async_client.post(
                "/api/v1/billing/webhook", content=b"{}",
                headers={"Stripe-Signature": "x"},
            )
        assert r.status_code == 200

        from app.db.models import User as UserDB
        db_session.expire_all()
        assert db_session.get(UserDB, seeded_user.id).subscription_status == "canceled"

    async def test_invoice_paid_converts_referral_and_credits_inviter(
        self, async_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        # seeded_user is the REFEREE. Set up an inviter + a pending referral.
        from app.db.models import (
            User as UserDB, ReferralCode as ReferralCodeDB, Referral as ReferralDB
        )
        inviter = UserDB(
            id=99, email="inviter@x.com", password_hash="h", name="Alice",
            fitness_level="advanced",
            stripe_customer_id="cus_inviter",
        )
        db_session.add(inviter)
        code = ReferralCodeDB(user_id=99, code="alice42")
        db_session.add(code)
        db_session.flush()
        referral = ReferralDB(
            code_id=code.id, referred_user_id=seeded_user.id, status="pending",
        )
        db_session.add(referral)

        seeded_user.stripe_customer_id = "cus_referee"
        db_session.commit()

        event = {
            "type": "invoice.paid",
            "data": {"object": {"customer": "cus_referee"}},
        }
        with patch("app.api.v1.billing.stripe_client.verify_webhook", return_value=event), \
             patch("app.api.v1.billing.stripe_client.grant_one_month_coupon",
                   return_value="ii_credit_xyz") as grant:
            r = await async_client.post(
                "/api/v1/billing/webhook", content=b"{}",
                headers={"Stripe-Signature": "x"},
            )
        assert r.status_code == 200, r.text

        # Referral flipped + inviter credited.
        db_session.expire_all()
        ref = db_session.execute(
            __import__("sqlalchemy").select(ReferralDB).where(
                ReferralDB.referred_user_id == seeded_user.id
            )
        ).scalar_one()
        assert ref.status == "converted"
        assert ref.converted_at is not None
        grant.assert_called_once()
        assert grant.call_args.kwargs["customer_id"] == "cus_inviter"

    async def test_invoice_paid_without_referral_is_a_noop(
        self, async_client: AsyncClient, db_session, seeded_user, monkeypatch
    ):
        _stripe_on(monkeypatch)
        seeded_user.stripe_customer_id = "cus_42"
        db_session.commit()

        event = {
            "type": "invoice.paid",
            "data": {"object": {"customer": "cus_42"}},
        }
        with patch("app.api.v1.billing.stripe_client.verify_webhook", return_value=event), \
             patch("app.api.v1.billing.stripe_client.grant_one_month_coupon") as grant:
            r = await async_client.post(
                "/api/v1/billing/webhook", content=b"{}",
                headers={"Stripe-Signature": "x"},
            )
        assert r.status_code == 200
        # No referral exists → no credit attempt.
        grant.assert_not_called()


# ==========================================================
# Page render
# ==========================================================

@pytest.mark.asyncio
class TestBillingPageRender:
    async def test_renders(self, async_client: AsyncClient):
        r = await async_client.get("/dashboard/billing")
        assert r.status_code == 200
        body = r.text
        assert "btn-subscribe" in body
        assert "trial-countdown" in body
        assert "cancelConfirmModal" in body
