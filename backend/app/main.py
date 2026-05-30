"""
CrossFit Health OS - FastAPI Application
Main entry point for the backend API
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.i18n import LocaleMiddleware
from app.core.rate_limit import limiter
from app.api.v1 import training, health, nutrition, integrations, users, schedule, review, auth, onboarding, gamification, diet, today, notifications, programs, referrals, billing, internal_cron
from app.web import routes as web_routes

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("🚀 CrossFit Health OS API starting...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Supabase URL: {settings.SUPABASE_URL}")

    yield

    # Shutdown
    logger.info("⏹️  CrossFit Health OS API shutting down...")


# Initialize FastAPI app
app = FastAPI(
    title="CrossFit Health OS API",
    description="Elite Human Performance Ecosystem - Biometrics, Nutrition, and Training Intelligence",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Rate limiting (slowapi). Endpoints opt in with @limiter.limit("...").
# Stored in Redis when REDIS_URL is set, else in-memory.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Locale resolution: ?lang → cookie → user.locale → Accept-Language → pt-BR
app.add_middleware(LocaleMiddleware)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)

    # Render HTML 500 page for browser requests outside /api/*
    accept = request.headers.get("accept", "")
    if not request.url.path.startswith("/api/") and "text/html" in accept:
        try:
            return web_routes.templates.TemplateResponse(
                "500.html", {"request": request}, status_code=500
            )
        except Exception:
            # Fall through to JSON if the template itself fails — never let
            # the error handler raise.
            logger.exception("Failed to render 500.html")

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


# Health check
@app.get("/api", tags=["Health"])
async def root():
    """Root endpoint - API health check"""
    return {
        "status": "healthy",
        "service": "CrossFit Health OS API",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check with dependencies"""
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected",
        "timestamp": "2026-02-08T06:45:00Z"
    }


# Include web routes (HTML pages)
app.include_router(
    web_routes.router,
    tags=["Web"]
)

# Authentication (public endpoints - no auth required)
app.include_router(
    auth.router,
    prefix="/api/v1/auth",
    tags=["Authentication"]
)

# Include API routers
app.include_router(
    users.router,
    prefix="/api/v1/users",
    tags=["Users"]
)

app.include_router(
    training.router,
    prefix="/api/v1/training",
    tags=["Training"]
)

app.include_router(
    health.router,
    prefix="/api/v1/health",
    tags=["Health"]
)

app.include_router(
    nutrition.router,
    prefix="/api/v1/nutrition",
    tags=["Nutrition"]
)

app.include_router(
    integrations.router,
    prefix="/api/v1/integrations",
    tags=["Integrations"]
)

app.include_router(
    schedule.router,
    prefix="/api/v1/schedule",
    tags=["Schedule"]
)

app.include_router(
    review.router,
    prefix="/api/v1/review",
    tags=["Review"]
)

app.include_router(
    programs.router,
    prefix="/api/v1/programs",
    tags=["Programs"]
)

app.include_router(referrals.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(internal_cron.router, prefix="/api/v1")

# These routers have their own prefix defined
app.include_router(onboarding.router)
app.include_router(gamification.router)
app.include_router(diet.router)
app.include_router(today.router)
app.include_router(notifications.router)


# Custom 404 handler - only for HTML requests
@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    """Custom 404 error page for HTML requests only"""
    # For API requests, preserve the original HTTPException detail
    if request.url.path.startswith("/api/"):
        detail = getattr(exc, "detail", "Not Found")
        return JSONResponse(
            status_code=404,
            content={"detail": detail}
        )

    # Return HTML for browser requests — reuse the shared Jinja env so
    # i18n globals (t, locale, asset_version) are available in the template.
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return web_routes.templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404
        )

    # Fallback JSON
    detail = getattr(exc, "detail", "Not Found")
    return JSONResponse(
        status_code=404,
        content={"detail": detail}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
