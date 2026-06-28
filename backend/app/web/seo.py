"""Structured data and SEO metadata for public marketing pages."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.core.config import settings
from app.core.i18n import t as _t

_APP_NAME = "CrossFit Health OS"
_PRICE_USD = "29.00"
_TRIAL_DAYS = 14


def _base_url() -> str:
    return (settings.FRONTEND_URL or "http://localhost:8001").rstrip("/")


def _og_locale(locale: str) -> str:
    return "en_US" if locale == "en" else "pt_BR"


def landing_seo_meta(locale: str) -> Dict[str, str]:
    """Meta tags for the landing page (description, OG, canonical, hreflang)."""
    base = _base_url()
    title = f"{_APP_NAME} — {_t(locale, 'landing.hero.title_1')}"
    description = _t(locale, "landing.hero.lead")
    return {
        "title": title,
        "description": description,
        "canonical_url": f"{base}/",
        "og_type": "website",
        "og_locale": _og_locale(locale),
        "og_url": f"{base}/",
        "hreflang_en": f"{base}/?lang=en",
        "hreflang_pt_br": f"{base}/?lang=pt-BR",
        "hreflang_default": f"{base}/",
    }


def _faq_entities(locale: str) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    for i in range(1, 9):
        question = _t(locale, f"landing.faq.q{i}")
        answer = _t(locale, f"landing.faq.a{i}")
        if question.startswith("landing.faq.") or answer.startswith("landing.faq."):
            continue
        entities.append(
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
        )
    return entities


def _feature_list(locale: str) -> List[str]:
    keys = (
        "landing.pricing.feat1",
        "landing.pricing.feat2",
        "landing.pricing.feat3",
        "landing.pricing.feat4",
        "landing.pricing.feat5",
        "landing.pricing.feat6",
        "landing.pricing.feat7",
    )
    features: List[str] = []
    for key in keys:
        value = _t(locale, key)
        if not value.startswith("landing."):
            features.append(value)
    return features


def landing_schema_json(locale: str) -> str:
    """JSON-LD @graph for Organization, WebSite, SoftwareApplication, FAQPage."""
    base = _base_url()
    org_id = f"{base}/#organization"
    website_id = f"{base}/#website"
    app_id = f"{base}/#software"
    faq_id = f"{base}/#faq"

    description = _t(locale, "landing.hero.lead")
    in_language = "en" if locale == "en" else "pt-BR"

    graph: List[Dict[str, Any]] = [
        {
            "@type": "Organization",
            "@id": org_id,
            "name": _APP_NAME,
            "url": f"{base}/",
            "email": settings.SUPPORT_EMAIL or None,
        },
        {
            "@type": "WebSite",
            "@id": website_id,
            "url": f"{base}/",
            "name": _APP_NAME,
            "description": description,
            "inLanguage": ["en", "pt-BR"],
            "publisher": {"@id": org_id},
        },
        {
            "@type": "SoftwareApplication",
            "@id": app_id,
            "name": _APP_NAME,
            "applicationCategory": "HealthApplication",
            "applicationSubCategory": "FitnessApplication",
            "operatingSystem": "Web",
            "url": f"{base}/",
            "description": description,
            "inLanguage": in_language,
            "featureList": _feature_list(locale),
            "provider": {"@id": org_id},
            "isPartOf": {"@id": website_id},
            "offers": [
                {
                    "@type": "Offer",
                    "name": _t(locale, "landing.pricing.title"),
                    "price": _PRICE_USD,
                    "priceCurrency": "USD",
                    "url": f"{base}/register",
                    "availability": "https://schema.org/InStock",
                    "description": _t(locale, "landing.pricing.subtitle"),
                },
                {
                    "@type": "Offer",
                    "name": _t(locale, "landing.pricing.cta"),
                    "price": "0",
                    "priceCurrency": "USD",
                    "url": f"{base}/register",
                    "availability": "https://schema.org/InStock",
                    "description": _t(locale, "landing.pricing.no_card"),
                    "eligibleDuration": {
                        "@type": "QuantitativeValue",
                        "value": _TRIAL_DAYS,
                        "unitCode": "DAY",
                    },
                },
            ],
        },
    ]

    faq_entities = _faq_entities(locale)
    if faq_entities:
        graph.append(
            {
                "@type": "FAQPage",
                "@id": faq_id,
                "url": f"{base}/#faq",
                "inLanguage": in_language,
                "mainEntity": faq_entities,
            }
        )

    # Drop null email when unset (tests / local dev).
    org = graph[0]
    if not org.get("email"):
        org.pop("email", None)

    payload = {"@context": "https://schema.org", "@graph": graph}
    return json.dumps(payload, ensure_ascii=False)
