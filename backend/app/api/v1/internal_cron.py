"""Internal cron endpoints — invoked by an external scheduler.

Auth via the ``X-Internal-Cron-Secret`` header against
``settings.INTERNAL_CRON_SECRET``. Endpoints are not user-facing; they
exist so Coolify (or any external cron / GitHub Actions / k8s CronJob)
can drive scheduled jobs without an in-app worker.

Why not Celery beat: Celery is configured but no broker tasks ship
today. Adding a thin internal endpoint is faster, observable from the
HTTP log, and easier to unstuck when things go wrong. Migration to
Celery later is a one-file rewrap if needed.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import settings
from app.services.weekly_review_scheduler import run_weekly_reviews

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/cron", tags=["internal-cron"])


def _verify_cron_secret(provided: str | None) -> None:
    """Constant-time check; refuse to run if the server has no secret set."""
    expected = (settings.INTERNAL_CRON_SECRET or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_CRON_SECRET not configured on the server",
        )
    if not provided or not secrets.compare_digest(provided.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid cron secret",
        )


@router.post("/weekly-reviews")
async def trigger_weekly_reviews(
    x_internal_cron_secret: str | None = Header(default=None),
):
    """Generate last-week review for every eligible user. Idempotent."""
    _verify_cron_secret(x_internal_cron_secret)
    summary = await run_weekly_reviews()
    logger.info("weekly review cron summary: %s", summary)
    return summary
