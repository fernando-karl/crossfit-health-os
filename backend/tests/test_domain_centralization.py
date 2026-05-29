"""Verify that APP_DOMAIN + SUPPORT_EMAIL / DPO_EMAIL flow correctly into
both server-rendered templates and the JS-injected i18n catalog."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import config as _config_module


@pytest.fixture
def with_domain_overrides(monkeypatch):
    """Force fresh email settings for the duration of a single test."""
    def _apply(support: str = "help@example.com", dpo: str = "privacy@example.com"):
        monkeypatch.setattr(_config_module.settings, "SUPPORT_EMAIL", support)
        monkeypatch.setattr(_config_module.settings, "DPO_EMAIL", dpo)
    return _apply


class TestDomainDefaults:
    def test_derives_emails_from_app_domain(self, monkeypatch):
        """Empty SUPPORT/DPO emails → derived from APP_DOMAIN."""
        s = _config_module.Settings(
            APP_DOMAIN="crossfit.example.com",
            APP_SCHEME="https",
            FRONTEND_URL="",
            SUPPORT_EMAIL="",
            DPO_EMAIL="",
            SECRET_KEY="x" * 48,
        )
        _config_module._resolve_domain_defaults(s)
        assert s.SUPPORT_EMAIL == "support@crossfit.example.com"
        assert s.DPO_EMAIL == "dpo@crossfit.example.com"
        assert s.FRONTEND_URL == "https://crossfit.example.com"

    def test_explicit_emails_take_precedence(self):
        s = _config_module.Settings(
            APP_DOMAIN="example.com",
            APP_SCHEME="https",
            FRONTEND_URL="",
            SUPPORT_EMAIL="custom-support@elsewhere.com",
            DPO_EMAIL="custom-dpo@elsewhere.com",
            SECRET_KEY="x" * 48,
        )
        _config_module._resolve_domain_defaults(s)
        assert s.SUPPORT_EMAIL == "custom-support@elsewhere.com"
        assert s.DPO_EMAIL == "custom-dpo@elsewhere.com"

    def test_strips_port_from_domain_for_email(self):
        s = _config_module.Settings(
            APP_DOMAIN="localhost:8001",
            APP_SCHEME="http",
            FRONTEND_URL="",
            SUPPORT_EMAIL="",
            DPO_EMAIL="",
            SECRET_KEY="x" * 48,
        )
        _config_module._resolve_domain_defaults(s)
        # No port in the email address part.
        assert s.SUPPORT_EMAIL == "support@localhost"
        assert s.DPO_EMAIL == "dpo@localhost"
        # But FRONTEND_URL keeps the port.
        assert s.FRONTEND_URL == "http://localhost:8001"

    def test_public_origin_appended_to_cors(self):
        s = _config_module.Settings(
            APP_DOMAIN="real.example.com",
            APP_SCHEME="https",
            CORS_ORIGINS=["http://localhost:3000"],
            FRONTEND_URL="",
            SECRET_KEY="x" * 48,
        )
        _config_module._resolve_domain_defaults(s)
        assert "https://real.example.com" in s.CORS_ORIGINS


@pytest.mark.asyncio
class TestServerSideRendering:
    async def test_help_page_renders_with_configured_email(
        self, async_client: AsyncClient, with_domain_overrides
    ):
        with_domain_overrides(support="help@crossfit.example.com")
        r = await async_client.get("/help")
        assert r.status_code == 200
        body = r.text
        assert "help@crossfit.example.com" in body
        # Placeholder must NOT leak into the rendered page.
        assert "{support_email}" not in body
        assert "crossfithealth.os" not in body

    async def test_terms_renders_with_configured_dpo(
        self, async_client: AsyncClient, with_domain_overrides
    ):
        with_domain_overrides(dpo="privacy@crossfit.example.com")
        r = await async_client.get("/terms")
        assert r.status_code == 200
        body = r.text
        assert "privacy@crossfit.example.com" in body
        assert "{dpo_email}" not in body


@pytest.mark.asyncio
class TestClientSideI18nCatalog:
    """``window.I18N = {...}`` must already have placeholders resolved so the
    client-side ``t()`` (which has no access to settings) renders correctly."""

    async def test_window_i18n_has_substituted_emails(
        self, async_client: AsyncClient, with_domain_overrides
    ):
        with_domain_overrides(
            support="help@example.com", dpo="privacy@example.com"
        )
        r = await async_client.get("/")
        body = r.text
        # window.I18N gets the resolved values, never the placeholder.
        assert "{support_email}" not in body
        assert "{dpo_email}" not in body
        # And the substituted email shows up in the embedded JSON.
        assert "help@example.com" in body or "privacy@example.com" in body
