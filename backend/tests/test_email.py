"""Tests for SMTP email helpers."""
from unittest.mock import MagicMock, patch

from app.core.email import send_email, send_password_reset_email, smtp_configured


class TestSmtpConfigured:
    def test_false_when_host_missing(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "SMTP_HOST", "")
        monkeypatch.setattr(config.settings, "SMTP_FROM", "noreply@test.com")
        assert smtp_configured() is False

    def test_true_when_host_and_from_set(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "SMTP_HOST", "smtp.test.com")
        monkeypatch.setattr(config.settings, "SMTP_FROM", "noreply@test.com")
        assert smtp_configured() is True


class TestSendEmail:
    def test_returns_false_when_smtp_disabled(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "SMTP_HOST", "")
        assert send_email(to_email="u@test.com", subject="Hi", text_body="body") is False

    @patch("app.core.email.smtplib.SMTP")
    def test_sends_via_starttls(self, mock_smtp_cls, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "SMTP_HOST", "smtp.test.com")
        monkeypatch.setattr(config.settings, "SMTP_PORT", 587)
        monkeypatch.setattr(config.settings, "SMTP_FROM", "noreply@test.com")
        monkeypatch.setattr(config.settings, "SMTP_USER", "user")
        monkeypatch.setattr(config.settings, "SMTP_PASSWORD", "pass")
        monkeypatch.setattr(config.settings, "SMTP_USE_TLS", True)
        monkeypatch.setattr(config.settings, "SMTP_USE_SSL", False)

        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        mock_smtp_cls.return_value = conn

        ok = send_password_reset_email("athlete@test.com", "https://app.test/reset?token=abc")
        assert ok is True
        mock_smtp_cls.assert_called_once_with("smtp.test.com", 587, timeout=30)
        conn.starttls.assert_called_once()
        conn.login.assert_called_once_with("user", "pass")
        conn.sendmail.assert_called_once()
