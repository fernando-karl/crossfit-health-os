"""Tests for landing SEO metadata and JSON-LD schema."""
import json

import pytest

from app.web.seo import landing_schema_json, landing_seo_meta


class TestLandingSeoMeta:
    def test_meta_includes_description_and_hreflang(self):
        meta = landing_seo_meta("en")
        assert "CrossFit Health OS" in meta["title"]
        assert meta["description"]
        assert meta["canonical_url"].endswith("/")
        assert "lang=en" in meta["hreflang_en"]
        assert "lang=pt-BR" in meta["hreflang_pt_br"]

    def test_meta_og_locale_pt_br(self):
        assert landing_seo_meta("pt-BR")["og_locale"] == "pt_BR"

    def test_meta_og_locale_en(self):
        assert landing_seo_meta("en")["og_locale"] == "en_US"


class TestLandingSchemaJson:
    @pytest.mark.parametrize("locale", ["en", "pt-BR"])
    def test_schema_graph_types(self, locale: str):
        raw = landing_schema_json(locale)
        payload = json.loads(raw)

        assert payload["@context"] == "https://schema.org"
        types = {node["@type"] for node in payload["@graph"]}
        assert types >= {
            "Organization",
            "WebSite",
            "SoftwareApplication",
            "FAQPage",
        }

    def test_schema_faq_has_eight_questions_en(self):
        payload = json.loads(landing_schema_json("en"))
        faq = next(n for n in payload["@graph"] if n["@type"] == "FAQPage")
        assert len(faq["mainEntity"]) == 8
        assert faq["mainEntity"][0]["acceptedAnswer"]["text"]

    def test_schema_offer_price(self):
        payload = json.loads(landing_schema_json("en"))
        app = next(n for n in payload["@graph"] if n["@type"] == "SoftwareApplication")
        offers = app["offers"]
        assert len(offers) == 2
        assert offers[0]["price"] == "29.00"
        assert offers[0]["priceCurrency"] == "USD"
        assert offers[1]["price"] == "0"
        assert offers[1]["eligibleDuration"]["value"] == 14

    def test_schema_json_is_utf8_safe(self):
        raw = landing_schema_json("pt-BR")
        assert "CrossFit Health OS" in raw
        json.loads(raw)
