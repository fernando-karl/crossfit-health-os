"""Stripe client + lazy product/price provisioning.

The first time a Stripe-dependent endpoint runs, ``ensure_price()`` looks
for a Product tagged ``metadata.app_id == 'chos'`` and a recurring price
of ``$29/month``. If they don't exist, they're created idempotently using
metadata-based lookup so re-runs don't duplicate.

Set ``STRIPE_PRICE_ID`` in env to bypass the lookup entirely (faster cold
path; recommended for prod once the price is stable).
"""
from __future__ import annotations

import logging
from typing import Optional

import stripe

from app.core.config import settings

logger = logging.getLogger(__name__)

PRODUCT_NAME = "CrossFit Health OS"
APP_ID = "chos"
PLAN_AMOUNT_CENTS = 2900  # $29.00
PLAN_CURRENCY = "usd"
PLAN_INTERVAL = "month"


def _api_key() -> str:
    key = (settings.STRIPE_SECRET_KEY or "").strip()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    return key


def _client() -> "stripe":
    """Configure the Stripe SDK and return the module (acts as the client)."""
    stripe.api_key = _api_key()
    # Pin the API version so server-side behavior is reproducible.
    stripe.api_version = "2024-11-20.acacia"
    return stripe


# ----------------------------------------------------------------
# Product / price provisioning
# ----------------------------------------------------------------

def _find_product_by_app_id(client) -> Optional["stripe.Product"]:
    """Search products by the app_id metadata tag. Stripe limits 100/page."""
    for product in client.Product.list(limit=100, active=True).auto_paging_iter():
        if product.metadata and product.metadata.get("app_id") == APP_ID:
            return product
    return None


def _find_recurring_price(client, product_id: str) -> Optional["stripe.Price"]:
    for price in client.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
        if (
            price.recurring
            and price.recurring.get("interval") == PLAN_INTERVAL
            and price.unit_amount == PLAN_AMOUNT_CENTS
            and price.currency == PLAN_CURRENCY
        ):
            return price
    return None


def ensure_price() -> str:
    """Return the active recurring price id, creating product+price if missing.

    Cached after first lookup via ``settings.STRIPE_PRICE_ID``.
    """
    if settings.STRIPE_PRICE_ID:
        return settings.STRIPE_PRICE_ID

    client = _client()

    product = _find_product_by_app_id(client)
    if product is None:
        product = client.Product.create(
            name=PRODUCT_NAME,
            description="Smart training, recovery, and weekly reviews.",
            metadata={"app_id": APP_ID},
        )
        logger.info("Stripe product created: %s", product.id)

    price = _find_recurring_price(client, product.id)
    if price is None:
        price = client.Price.create(
            product=product.id,
            unit_amount=PLAN_AMOUNT_CENTS,
            currency=PLAN_CURRENCY,
            recurring={"interval": PLAN_INTERVAL},
            metadata={"app_id": APP_ID},
        )
        logger.info("Stripe price created: %s", price.id)

    # Cache on the live settings object so subsequent calls skip the round-trip.
    settings.STRIPE_PRICE_ID = price.id
    return price.id


# ----------------------------------------------------------------
# Customer
# ----------------------------------------------------------------

def ensure_customer(user_email: str, user_id: int, existing_customer_id: Optional[str]) -> str:
    """Return a Stripe customer id, creating one if the user doesn't have one yet."""
    client = _client()
    if existing_customer_id:
        # Defensive: confirm it still exists. Cheap because the SDK caches.
        try:
            customer = client.Customer.retrieve(existing_customer_id)
            if not getattr(customer, "deleted", False):
                return existing_customer_id
        except stripe.error.InvalidRequestError:
            pass  # fall through to create

    customer = client.Customer.create(
        email=user_email,
        metadata={"app_id": APP_ID, "user_id": str(user_id)},
    )
    return customer.id


# ----------------------------------------------------------------
# Checkout / portal / cancel
# ----------------------------------------------------------------

def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    *,
    discount_coupon_id: Optional[str] = None,
) -> "stripe.checkout.Session":
    client = _client()
    params = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": True,
    }
    if discount_coupon_id:
        params["discounts"] = [{"coupon": discount_coupon_id}]
    return client.checkout.Session.create(**params)


def create_portal_session(customer_id: str, return_url: str) -> "stripe.billing_portal.Session":
    client = _client()
    return client.billing_portal.Session.create(customer=customer_id, return_url=return_url)


def cancel_at_period_end(subscription_id: str) -> "stripe.Subscription":
    client = _client()
    return client.Subscription.modify(subscription_id, cancel_at_period_end=True)


# ----------------------------------------------------------------
# Coupons (used to grant inviter their reward month on referral conversion)
# ----------------------------------------------------------------

def grant_one_month_coupon(customer_id: str, reason: str = "referral_reward") -> str:
    """Apply an invoice-level credit equivalent to one month free.

    We use Stripe's invoice item with negative amount on the customer's
    next invoice. Cleaner than coupons for this use case (one-shot, no
    duration/once dance, no risk of stacking).
    """
    client = _client()
    item = client.InvoiceItem.create(
        customer=customer_id,
        amount=-PLAN_AMOUNT_CENTS,
        currency=PLAN_CURRENCY,
        description=f"Referral reward (one month free) — {reason}",
        metadata={"app_id": APP_ID, "reason": reason},
    )
    return item.id


# ----------------------------------------------------------------
# Webhook signature verification
# ----------------------------------------------------------------

def verify_webhook(payload: bytes, sig_header: str) -> "stripe.Event":
    """Validate a webhook signature and return the parsed Event.

    Raises ``stripe.error.SignatureVerificationError`` on bad sig.
    """
    secret = (settings.STRIPE_WEBHOOK_SECRET or "").strip()
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not configured")
    return stripe.Webhook.construct_event(payload, sig_header, secret)
