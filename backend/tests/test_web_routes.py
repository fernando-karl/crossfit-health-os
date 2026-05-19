"""
Tests for Web Routes (HTML Pages)
Tests that all web pages return 200 OK
"""
import pytest
from httpx import AsyncClient


class TestPublicPages:
    """Test public web pages"""
    
    @pytest.mark.asyncio
    async def test_home_page(self, async_client: AsyncClient):
        """Test landing page"""
        response = await async_client.get("/")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_login_page(self, async_client: AsyncClient):
        """Test login page"""
        response = await async_client.get("/login")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_register_page(self, async_client: AsyncClient):
        """Test registration page"""
        response = await async_client.get("/register")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_forgot_password_page(self, async_client: AsyncClient):
        """Test forgot password page"""
        response = await async_client.get("/forgot-password")
        assert response.status_code == 200


class TestDashboardPages:
    """Test dashboard pages"""
    
    @pytest.mark.asyncio
    async def test_dashboard_home(self, async_client: AsyncClient):
        """Test main dashboard page"""
        response = await async_client.get("/dashboard")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_workouts_page(self, async_client: AsyncClient):
        """Test workouts page"""
        response = await async_client.get("/dashboard/workouts")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_schedule_page(self, async_client: AsyncClient):
        """Test schedule page"""
        response = await async_client.get("/dashboard/schedule")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_health_page(self, async_client: AsyncClient):
        """Test health/biometrics page"""
        response = await async_client.get("/dashboard/health")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_nutrition_page(self, async_client: AsyncClient):
        """Test nutrition page"""
        response = await async_client.get("/dashboard/nutrition")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_reviews_page(self, async_client: AsyncClient):
        """Test reviews page"""
        response = await async_client.get("/dashboard/reviews")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_programs_page_renders_form(self, async_client: AsyncClient):
        """Programs page renders with the generation form + JS hook."""
        response = await async_client.get("/dashboard/programs")
        assert response.status_code == 200
        html = response.text
        # Form fields the JS depends on
        for marker in ("prog-composer", "prog-weeks", "prog-deload",
                       "prog-spw", "prog-focus", "prog-start",
                       "prog-activate", "btn-program-submit"):
            assert marker in html, f"missing {marker!r} in programs page"
        # JS bundle wired
        assert "/static/js/programs.js" in html

    @pytest.mark.asyncio
    async def test_programs_page_localized_en(self, async_client: AsyncClient):
        response = await async_client.get("/dashboard/programs?lang=en")
        assert response.status_code == 200
        assert "AI Programs" in response.text

    @pytest.mark.asyncio
    async def test_programs_page_localized_pt(self, async_client: AsyncClient):
        response = await async_client.get("/dashboard/programs?lang=pt-BR")
        assert response.status_code == 200
        assert "Programas AI" in response.text
    
    @pytest.mark.asyncio
    async def test_profile_page(self, async_client: AsyncClient):
        """Test profile page"""
        response = await async_client.get("/dashboard/profile")
        assert response.status_code == 200


class TestAuthCallbackPages:
    """Test authentication callback pages"""
    
    @pytest.mark.asyncio
    async def test_auth_callback(self, async_client: AsyncClient):
        """Test Supabase auth callback handler"""
        response = await async_client.get(
            "/auth/callback?token=test_token&type=signup&redirect_to=/dashboard"
        )
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_auth_verify(self, async_client: AsyncClient):
        """Test auth verify route"""
        response = await async_client.get("/auth/verify?token=test_token&type=email")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_auth_handler(self, async_client: AsyncClient):
        """Test auth handler for URL hash tokens"""
        response = await async_client.get("/auth/handler")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_update_password_page(self, async_client: AsyncClient):
        """Test update password page"""
        response = await async_client.get("/update-password")
        assert response.status_code == 200


class TestErrorPages:
    """Test custom error page handlers"""

    @pytest.mark.asyncio
    async def test_html_404_renders_template(self, async_client: AsyncClient):
        """Browser requests for unknown paths get the rendered 404 template,
        not a JSON 500 (regression: shared Jinja env must be used so
        i18n globals like `locale`/`t` resolve)."""
        response = await async_client.get(
            "/this-page-does-not-exist",
            headers={"Accept": "text/html"},
        )
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
        assert ">404<" in response.text
        # i18n key must be resolved, not left raw
        assert "errors.page_404_title" not in response.text

    @pytest.mark.asyncio
    async def test_api_404_returns_json(self, async_client: AsyncClient):
        """Unknown /api/* paths return JSON regardless of Accept header."""
        response = await async_client.get(
            "/api/v1/does-not-exist",
            headers={"Accept": "text/html"},
        )
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"detail": "Not Found"}

    @pytest.mark.asyncio
    async def test_non_html_404_returns_json(self, async_client: AsyncClient):
        """Non-API, non-HTML requests fall back to JSON."""
        response = await async_client.get(
            "/missing-non-html",
            headers={"Accept": "*/*"},
        )
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")

    @pytest.mark.asyncio
    async def test_html_500_renders_template(self):
        """Unhandled exceptions on browser requests render 500.html."""
        from fastapi import APIRouter
        from httpx import ASGITransport
        from app.main import app

        router = APIRouter()

        @router.get("/__test_boom_html__")
        def _boom():
            raise RuntimeError("synthetic blast for html 500 test")

        app.include_router(router)
        try:
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/__test_boom_html__",
                    headers={"Accept": "text/html"},
                )
        finally:
            # Remove the temp route so it doesn't leak into other tests.
            app.router.routes = [
                r for r in app.router.routes
                if getattr(r, "path", None) != "/__test_boom_html__"
            ]

        assert response.status_code == 500
        assert response.headers["content-type"].startswith("text/html")
        assert ">500<" in response.text
        assert "errors.page_500_title" not in response.text

    @pytest.mark.asyncio
    async def test_api_500_returns_json(self):
        """Unhandled exceptions on /api/* always return JSON."""
        from fastapi import APIRouter
        from httpx import ASGITransport
        from app.main import app

        router = APIRouter()

        @router.get("/api/v1/__test_boom_json__")
        def _boom():
            raise RuntimeError("synthetic blast for api 500 test")

        app.include_router(router)
        try:
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/__test_boom_json__",
                    headers={"Accept": "text/html"},
                )
        finally:
            app.router.routes = [
                r for r in app.router.routes
                if getattr(r, "path", None) != "/api/v1/__test_boom_json__"
            ]

        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"] == "Internal Server Error"


class TestAPIHealthEndpoints:
    """Test API health check endpoints"""
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client: AsyncClient):
        """Test root API endpoint"""
        response = await async_client.get("/api")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data
        assert "version" in data
    
    @pytest.mark.asyncio
    async def test_health_check(self, async_client: AsyncClient):
        """Test detailed health check"""
        response = await async_client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data
