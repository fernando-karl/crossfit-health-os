"""
Web routes for serving HTML pages with Jinja2
"""
import json
import time

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from pathlib import Path

from app.core.config import settings as _settings
from app.core.i18n import DEFAULT_LOCALE, get_catalog, t as _t

router = APIRouter()

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


# Make `t`, `locale`, and `i18n_json` callable from any template/base.html.
templates.env.globals["t"] = _t_global
templates.env.globals["locale"] = _locale_global
templates.env.globals["i18n_json"] = _i18n_json_global
templates.env.globals["asset_version"] = _current_asset_version


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
    return templates.TemplateResponse("health.html", {
        "request": request,
        "active_page": "health",
        "biomarkers": [],
        "recovery_trend": []
    })


@router.get("/dashboard/nutrition")
async def nutrition_page(request: Request):
    """Nutrition page"""
    return templates.TemplateResponse("nutrition.html", {
        "request": request,
        "active_page": "nutrition",
        "today_macros": {"protein": 0, "carbs": 0, "fat": 0, "calories": 0},
        "targets": {"protein": 150, "carbs": 200, "fat": 70, "calories": 2000},
        "meals": [],
        "protein_pct": 0,
        "carbs_pct": 0,
        "fat_pct": 0
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
# Auth Verification Routes (Supabase callbacks)
# ============================================

@router.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle Supabase auth callback"""
    from app.core.config import settings
    
    token = request.query_params.get("token")
    type_param = request.query_params.get("type")
    redirect_to = request.query_params.get("redirect_to", "/dashboard")
    
    return templates.TemplateResponse("auth_callback.html", {
        "request": request,
        "token": token,
        "type": type_param,
        "redirect_to": redirect_to,
        "supabase_url": settings.SUPABASE_URL,
        "supabase_anon_key": settings.SUPABASE_ANON_KEY
    })


@router.get("/auth/verify")
async def auth_verify(request: Request):
    """Alternative verify route"""
    token = request.query_params.get("token")
    type_param = request.query_params.get("type")
    
    return templates.TemplateResponse("auth_callback.html", {
        "request": request,
        "token": token,
        "type": type_param,
        "redirect_to": "/dashboard"
    })


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
    return HTMLResponse(
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


@router.get("/reset-password")
async def reset_password_redirect(request: Request):
    """Redirect from forgot-password email to update-password page"""
    from fastapi.responses import RedirectResponse
    # Preserve hash fragment by redirecting to update-password
    return RedirectResponse(url="/update-password", status_code=302)


@router.get("/update-password")
async def update_password_page(request: Request):
    """Page to set new password after recovery link"""
    from app.core.config import settings
    
    return templates.TemplateResponse("update_password.html", {
        "request": request,
        "supabase_url": settings.SUPABASE_URL,
        "supabase_anon_key": settings.SUPABASE_ANON_KEY
    })
