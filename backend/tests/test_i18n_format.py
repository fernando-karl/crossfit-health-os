"""Tests for i18n placeholder substitution."""
from app.core.i18n import t


def test_safe_format_leaves_unknown_placeholders():
    assert (
        t("en", "landing.loop.demo.step_of", support_email="help@example.com")
        == "Step {current} of {total}"
    )


def test_safe_format_substitutes_provided_vars():
    assert t("en", "landing.loop.demo.step_of", current=3, total=5) == "Step 3 of 5"


def test_safe_format_support_email_still_works():
    value = t("en", "help.support_body", support_email="help@example.com")
    assert "help@example.com" in value
    assert "{support_email}" not in value
