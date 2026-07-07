"""
Web routes for serving HTML pages with Jinja2
"""
import json
import logging
import time

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from pathlib import Path

from app.core.config import settings as _settings
from app.core.i18n import DEFAULT_LOCALE, get_catalog, t as _t
from app.core.nutrition_targets import get_active_diet_plan, resolve_macro_targets
from app.db.session import get_session
from app.web.seo import landing_schema_json as build_landing_schema_json
from app.web.seo import landing_seo_meta as build_landing_seo_meta

router = APIRouter()
logger = logging.getLogger(__name__)

# Setup Jinja2 templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Cache-busting tag — derived from the newest mtime under static/. This
# means a JS or CSS edit alone invalidates the browser cache, even when
# uvicorn's --reload (Python-only) wouldn't restart the process. Cached
# for 5s to avoid scanning the dir on every request.
_STATIC_DIR = Path(__file__).parent.parent / "static"
_ASSET_VERSION_CACHE = {"value": "", "checked_at": 0.0}
_ASSET_VERSION_TTL_SECONDS = 5.0


def _current_asset_version() -> str:
    now = time.time()
    if now - _ASSET_VERSION_CACHE["checked_at"] < _ASSET_VERSION_TTL_SECONDS \
            and _ASSET_VERSION_CACHE["value"]:
        return _ASSET_VERSION_CACHE["value"]
    try:
        latest = max(
            p.stat().st_mtime
            for p in _STATIC_DIR.rglob("*")
            if p.is_file()
        )
        version = str(int(latest))
    except (ValueError, OSError):
        version = str(int(now))
    _ASSET_VERSION_CACHE["value"] = version
    _ASSET_VERSION_CACHE["checked_at"] = now
    return version


def _request_locale(ctx) -> str:
    request = ctx.get("request")
    if request is None:
        return DEFAULT_LOCALE
    return getattr(request.state, "locale", DEFAULT_LOCALE)


def _auto_vars() -> dict:
    """Vars auto-injected into every t() call.

    Strings in the i18n catalog use ``{support_email}`` / ``{dpo_email}``
    placeholders so the domain can be flipped via env without touching
    every legal doc string.
    """
    return {
        "support_email": _settings.SUPPORT_EMAIL or "",
        "dpo_email": _settings.DPO_EMAIL or "",
    }


@pass_context
def _t_global(ctx, key: str, **kwargs) -> str:
    return _t(_request_locale(ctx), key, **{**_auto_vars(), **kwargs})


@pass_context
def _locale_global(ctx) -> str:
    return _request_locale(ctx)


@pass_context
def _i18n_json_global(ctx) -> str:
    """Serialize the catalog with placeholders pre-substituted so the
    client-side ``t()`` (which has no settings access) renders correctly."""
    raw = json.dumps(get_catalog(_request_locale(ctx)), ensure_ascii=False)
    av = _auto_vars()
    return (
        raw
        .replace("{support_email}", av["support_email"])
        .replace("{dpo_email}", av["dpo_email"])
    )


@pass_context
def _get_landing_seo(ctx) -> dict:
    return build_landing_seo_meta(_request_locale(ctx))


@pass_context
def _get_landing_schema(ctx) -> str:
    return build_landing_schema_json(_request_locale(ctx))


# Make `t`, `locale`, and `i18n_json` callable from any template/base.html.
templates.env.globals["t"] = _t_global
templates.env.globals["locale"] = _locale_global
templates.env.globals["i18n_json"] = _i18n_json_global
templates.env.globals["asset_version"] = _current_asset_version
templates.env.globals["get_landing_seo"] = _get_landing_seo
templates.env.globals["get_landing_schema"] = _get_landing_schema


# ============================================
# Public pages
# ============================================

@router.get("/")
async def home(request: Request):
    """Landing page"""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/login")
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register")
async def register_page(request: Request):
    """Registration page"""
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    """Forgot password page"""
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@router.get("/help")
async def help_page(request: Request):
    """Public help center / documentation page."""
    return templates.TemplateResponse("help.html", {"request": request})


@router.get("/terms")
async def terms_page(request: Request):
    """Public Terms of Service page."""
    return templates.TemplateResponse("terms.html", {"request": request})


@router.get("/privacy")
async def privacy_page(request: Request):
    """Public Privacy Policy page (LGPD-compliant)."""
    return templates.TemplateResponse("privacy.html", {"request": request})


# ============================================
# Dashboard pages
# ============================================

@router.get("/dashboard")
async def dashboard_page(request: Request):
    """Main dashboard"""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard"
    })


@router.get("/dashboard/workouts")
async def workouts_page(request: Request):
    """Workouts page"""
    return templates.TemplateResponse("training.html", {
        "request": request,
        "active_page": "workouts",
    })


@router.get("/dashboard/schedule")
async def schedule_page(request: Request):
    """Schedule page"""
    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "active_page": "schedule"
    })


@router.get("/dashboard/billing")
async def billing_page(request: Request):
    """Subscription / billing page. Stripe integration pending —
    today this is a placeholder explaining the trial state."""
    return templates.TemplateResponse("billing.html", {
        "request": request,
        "active_page": "billing"
    })


@router.get("/dashboard/referrals")
async def referrals_page(request: Request):
    """Referral code + invitations dashboard."""
    return templates.TemplateResponse("referrals.html", {
        "request": request,
        "active_page": "referrals"
    })


@router.get("/dashboard/programs")
async def programs_page(request: Request):
    """cfai program generation page — generate Mesocycle + activate as macrocycle."""
    return templates.TemplateResponse("programs.html", {
        "request": request,
        "active_page": "programs"
    })


@router.get("/dashboard/health")
async def health_page(request: Request):
    """Health/biometrics page"""
    from sqlalchemy import select

    from app.db.models import BiomarkerReading as BiomarkerReadingDB
    from app.db.session import SessionLocal

    biomarkers = []
    user_id = _web_user_id(request)
    if user_id:
        try:
            with SessionLocal() as db:
                rows = db.execute(
                    select(BiomarkerReadingDB)
                    .where(BiomarkerReadingDB.user_id == str(user_id))
                    .order_by(BiomarkerReadingDB.test_date.desc())
                    .limit(12)
                ).scalars().all()
                biomarkers = [
                    {
                        "name": r.biomarker_name,
                        "value": r.value,
                        "unit": r.unit,
                        "status": r.status or "normal",
                        "date": r.test_date.isoformat() if r.test_date else "",
                    }
                    for r in rows
                ]
        except Exception:
            logger.exception("Failed to load biomarkers for health page (user_id=%s)", user_id)

    return templates.TemplateResponse("health.html", {
        "request": request,
        "active_page": "health",
        "biomarkers": biomarkers,
        "recovery_trend": [],
    })


@router.get("/dashboard/integrations")
async def integrations_page(request: Request):
    """Third-party integrations (Google Calendar, HealthKit instructions)."""
    return templates.TemplateResponse("integrations.html", {
        "request": request,
        "active_page": "integrations",
    })



_DEFAULT_MACRO_TARGETS = {"protein": 150, "carbs": 200, "fat": 70, "calories": 2000}
_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # Python weekday() order


def _web_user_id(request: Request):
    """Best-effort current user id for server-rendered pages, read from the
    HttpOnly ``access_token`` cookie set at login. Returns an int id or None.

    Never raises: an unauthenticated page still renders (client JS redirects
    to /login), so this stays a soft lookup."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from jose import jwt

        from app.db.models import User as _UserDB
        from app.db.session import SessionLocal

        payload = jwt.decode(token, _settings.SECRET_KEY, algorithms=[_settings.JWT_ALGORITHM])
        uid = payload.get("sub")
        if uid is None:
            return None
        with SessionLocal() as db:
            user = db.get(_UserDB, int(uid))
            return user.id if user else None
    except Exception:  # noqa: BLE001 — soft auth; render the page regardless
        return None


@router.get("/dashboard/nutrition")
async def nutrition_page(request: Request):
    """Nutrition page — server-rendered with the user's real macros, targets
    and today's logged meals (falls back to empty/defaults when logged out)."""
    from datetime import datetime as _dt, timedelta as _td

    from sqlalchemy import select

    from app.db.models import MealLog as _MealLog
    from app.db.session import SessionLocal

    today_macros = {"protein": 0, "carbs": 0, "fat": 0, "calories": 0}
    targets = dict(_DEFAULT_MACRO_TARGETS)
    target_source = "default"
    recent_meals = []
    diet_plan = None

    # Weekly macro trend: last 7 days (oldest→today). label_keys map to the
    # nutrition.weekday.* i18n keys client-side; series default to zeros.
    _week_days = [_dt.utcnow().date() - _td(days=i) for i in range(6, -1, -1)]
    macro_trend = {
        "label_keys": [_WEEKDAY_KEYS[d.weekday()] for d in _week_days],
        "protein": [0] * 7,
        "carbs": [0] * 7,
        "fat": [0] * 7,
    }

    user_id = _web_user_id(request)
    if user_id is not None:
        with SessionLocal() as db:
            today_start = _dt.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            rows = db.execute(
                select(_MealLog)
                .where(_MealLog.user_id == user_id, _MealLog.logged_at >= today_start)
                .order_by(_MealLog.logged_at)
            ).scalars().all()

            # 7-day buckets for the trend chart.
            week_start = _dt.combine(_week_days[0], _dt.min.time())
            day_index = {d: i for i, d in enumerate(_week_days)}
            for r in db.execute(
                select(_MealLog).where(
                    _MealLog.user_id == user_id, _MealLog.logged_at >= week_start
                )
            ).scalars().all():
                i = day_index.get(r.logged_at.date()) if r.logged_at else None
                if i is not None:
                    macro_trend["protein"][i] += round(r.protein_g or 0)
                    macro_trend["carbs"][i] += round(r.carbs_g or 0)
                    macro_trend["fat"][i] += round(r.fat_g or 0)

            today_macros = {
                "protein": round(sum(r.protein_g or 0 for r in rows)),
                "carbs": round(sum(r.carbs_g or 0 for r in rows)),
                "fat": round(sum(r.fat_g or 0 for r in rows)),
                "calories": round(sum(r.calories or 0 for r in rows)),
            }
            recent_meals = [
                {
                    "id": str(r.id),
                    "meal_type": r.meal_type or "",
                    "time": r.logged_at.strftime("%H:%M") if r.logged_at else "",
                    "name": (r.description
                             or (r.meal_type or "").replace("_", " ").title()
                             or "Meal"),
                    "calories": round(r.calories or 0),
                    "protein": round(r.protein_g or 0),
                    "carbs": round(r.carbs_g or 0),
                    "fat": round(r.fat_g or 0),
                }
                for r in rows
            ]

            # Targets: manual preferences > diet plan PDF > 2000 kcal default.
            try:
                resolved = resolve_macro_targets(db, user_id)
                targets = resolved["targets"]
                target_source = resolved["source"]

                plan = get_active_diet_plan(db, user_id)
                if plan:
                    diet_plan = {
                        "file_name": plan.file_name or "diet-plan.pdf",
                        "uploaded_at": plan.uploaded_at.strftime("%Y-%m-%d") if plan.uploaded_at else "",
                        "calories": plan.daily_calories,
                        "protein": plan.protein_g,
                        "carbs": plan.carbs_g,
                        "fat": plan.fat_g,
                    }
            except Exception:  # noqa: BLE001 — schema drift on user_diet_plans
                db.rollback()

    return templates.TemplateResponse("nutrition.html", {
        "request": request,
        "active_page": "nutrition",
        "today_macros": today_macros,
        "targets": targets,
        "target_source": target_source,
        "recent_meals": recent_meals,
        "diet_plan": diet_plan,
        "macro_trend": macro_trend,
    })


@router.get("/dashboard/reviews")
async def reviews_page(request: Request):
    """Reviews page"""
    return templates.TemplateResponse("reviews.html", {
        "request": request,
        "active_page": "reviews"
    })


@router.get("/dashboard/profile")
async def profile_page(request: Request):
    """Profile page"""
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "active_page": "profile"
    })


@router.get("/dashboard/badges")
async def badges_page(request: Request):
    """Badges/Achievements page"""
    return templates.TemplateResponse("badges.html", {
        "request": request,
        "active_page": "badges"
    })


@router.get("/onboarding")
async def onboarding_page(request: Request):
    """Onboarding page for new users"""
    return templates.TemplateResponse("onboarding.html", {"request": request})


# ============================================
# Auth Verification Routes (legacy — redirect to local JWT auth)
# ============================================

@router.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db=Depends(get_session),
):
    from fastapi.responses import RedirectResponse

    # Google Calendar OAuth return (registered redirect URI in Google Cloud).
    # Legacy Supabase email links use ?token=…&type=… — not Google OAuth.
    query = request.query_params
    is_calendar_oauth = bool(error or code or state) and not query.get("token")
    if is_calendar_oauth:
        from app.api.v1.integrations import handle_calendar_oauth_callback
        return await handle_calendar_oauth_callback(
            request, code=code, state=state, error=error, db=db
        )

    return RedirectResponse(url="/login?legacy_auth=1", status_code=302)


@router.get("/auth/verify")
async def auth_verify(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login?legacy_auth=1", status_code=302)


@router.get("/auth/handler")
async def auth_handler(request: Request):
    """Handle auth responses with tokens in URL hash"""
    return templates.TemplateResponse("auth_handler.html", {"request": request})


@router.get("/logout")
async def logout_page(request: Request):
    """No-JS-dependent logout: clear localStorage tokens and redirect to /.

    The navbar Logout link points here so the click works even if the
    progressive-enhancement JS handler hasn't attached yet (e.g. behind
    Cloudflare Rocket Loader)."""
    from fastapi.responses import HTMLResponse
    resp = HTMLResponse(
        """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Saindo...</title><meta name="robots" content="noindex"></head>
<body><script>
try {
  ['access_token','refresh_token','user','sb-access-token','sb-refresh-token']
    .forEach(function(k){ localStorage.removeItem(k); });
} catch (e) {}
window.location.replace('/');
</script><noscript><meta http-equiv="refresh" content="0; url=/">
<a href="/">Voltar para o início</a></noscript></body></html>"""
    )
    # Also drop the server-side HttpOnly auth cookie.
    resp.delete_cookie("access_token", path="/")
    return resp


@router.get("/reset-password")
async def reset_password_redirect(request: Request):
    """Redirect from forgot-password email to update-password page"""
    from fastapi.responses import RedirectResponse
    # Preserve hash fragment by redirecting to update-password
    return RedirectResponse(url="/update-password", status_code=302)


@router.get("/update-password")
async def update_password_page(request: Request):
    """Page to set new password after recovery link"""
    return templates.TemplateResponse("update_password.html", {
        "request": request,
    })
