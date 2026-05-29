"""Tests for the referral system: code generation, GET /me, redeem, list."""
from __future__ import annotations

import pytest

from app.core.referrals import (
    _slugify_name,
    generate_unique_code,
    get_or_create_code,
)
from app.db.models import Referral as ReferralDB, ReferralCode as ReferralCodeDB, User as UserDB


# ==========================================================
# Unit — slug + generator
# ==========================================================

class TestSlugify:
    def test_simple_name(self):
        assert _slugify_name("Fernando") == "fernando"

    def test_first_name_only(self):
        assert _slugify_name("Fernando Karl") == "fernando"

    def test_strips_accents(self):
        assert _slugify_name("João") == "joao"

    def test_strips_non_alpha(self):
        assert _slugify_name("Fer-nando42") == "fernando"

    def test_empty_falls_back(self):
        assert _slugify_name("") == "athlete"
        assert _slugify_name(None) == "athlete"
        assert _slugify_name("   ") == "athlete"

    def test_emoji_only_falls_back(self):
        assert _slugify_name("🔥💪") == "athlete"

    def test_truncates_long_names(self):
        slug = _slugify_name("Wolfeschlegelsteinhausenbergerdorff")
        assert len(slug) <= 10  # MAX_CODE_LEN(12) - 2 digits


class TestGenerateUniqueCode:
    def test_starts_with_slug(self, db_session):
        code = generate_unique_code("Fernando", db_session)
        assert code.startswith("fernando")
        assert len(code) <= 12

    def test_collision_retries(self, db_session):
        # Pre-seed every 2-digit suffix for "test" so generator must escalate
        # to 3 digits at least once.
        for n in range(100):
            db_session.add(ReferralCodeDB(user_id=10_000 + n, code=f"test{n:02d}"))
        db_session.commit()
        code = generate_unique_code("Test", db_session)
        assert code.startswith("test")
        # Must have escalated past 2-digit suffixes.
        assert len(code) >= len("test") + 3


# ==========================================================
# Unit — get_or_create_code
# ==========================================================

class TestGetOrCreateCode:
    def test_creates_on_first_call(self, db_session, seeded_user):
        code = get_or_create_code(seeded_user.id, seeded_user.name, db_session)
        assert code.user_id == seeded_user.id
        assert code.code.startswith("test")  # mock_user.name = "Test Athlete"

    def test_idempotent(self, db_session, seeded_user):
        c1 = get_or_create_code(seeded_user.id, seeded_user.name, db_session)
        c2 = get_or_create_code(seeded_user.id, seeded_user.name, db_session)
        assert c1.id == c2.id
        assert c1.code == c2.code


# ==========================================================
# Endpoint — GET /api/v1/referrals/me
# ==========================================================

@pytest.mark.asyncio
class TestGetMe:
    async def test_creates_code_and_returns_share_url(self, authenticated_client, seeded_user):
        r = await authenticated_client.get("/api/v1/referrals/me")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "code" in data
        assert data["code"].startswith("test")
        assert "/register?ref=" in data["share_url"]
        assert data["total_signups"] == 0
        assert data["months_earned"] == 0

    async def test_idempotent_across_calls(self, authenticated_client, seeded_user):
        r1 = await authenticated_client.get("/api/v1/referrals/me")
        r2 = await authenticated_client.get("/api/v1/referrals/me")
        assert r1.json()["code"] == r2.json()["code"]


# ==========================================================
# Endpoint — POST /api/v1/referrals/redeem
# ==========================================================

@pytest.mark.asyncio
class TestRedeem:
    async def test_unknown_code_returns_404(self, authenticated_client, seeded_user):
        r = await authenticated_client.post(
            "/api/v1/referrals/redeem", json={"code": "nobody99"}
        )
        assert r.status_code == 404

    async def test_self_redeem_rejected(self, authenticated_client, seeded_user, db_session):
        own = ReferralCodeDB(user_id=seeded_user.id, code="myown42")
        db_session.add(own)
        db_session.commit()
        r = await authenticated_client.post(
            "/api/v1/referrals/redeem", json={"code": "myown42"}
        )
        assert r.status_code == 400

    async def test_successful_redeem(self, authenticated_client, seeded_user, db_session):
        # Inviter is a different user; their code exists.
        inviter = UserDB(
            id=99, email="inviter@example.com", password_hash="x",
            name="Alice Smith", fitness_level="advanced",
        )
        db_session.add(inviter)
        db_session.add(ReferralCodeDB(user_id=99, code="alice12"))
        db_session.commit()

        r = await authenticated_client.post(
            "/api/v1/referrals/redeem", json={"code": "alice12"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["inviter_name"] == "Alice"
        assert body["months_credit"] == 1

        # And a Referral row was persisted.
        ref = db_session.query(ReferralDB).filter(
            ReferralDB.referred_user_id == seeded_user.id
        ).one_or_none()
        assert ref is not None
        assert ref.status == "pending"

    async def test_double_redeem_rejected(self, authenticated_client, seeded_user, db_session):
        inviter = UserDB(
            id=99, email="inviter@example.com", password_hash="x",
            name="Alice", fitness_level="advanced",
        )
        db_session.add(inviter)
        db_session.add(ReferralCodeDB(user_id=99, code="alice13"))
        db_session.commit()

        r1 = await authenticated_client.post(
            "/api/v1/referrals/redeem", json={"code": "alice13"}
        )
        assert r1.status_code == 200

        r2 = await authenticated_client.post(
            "/api/v1/referrals/redeem", json={"code": "alice13"}
        )
        assert r2.status_code == 409

    async def test_case_insensitive_lookup(self, authenticated_client, seeded_user, db_session):
        inviter = UserDB(
            id=99, email="inviter@example.com", password_hash="x",
            name="Alice", fitness_level="advanced",
        )
        db_session.add(inviter)
        db_session.add(ReferralCodeDB(user_id=99, code="alice14"))
        db_session.commit()

        r = await authenticated_client.post(
            "/api/v1/referrals/redeem", json={"code": "  ALICE14  "}
        )
        assert r.status_code == 200


# ==========================================================
# Endpoint — GET /api/v1/referrals/me/list
# ==========================================================

@pytest.mark.asyncio
class TestListMyReferrals:
    async def test_empty_when_no_signups(self, authenticated_client, seeded_user):
        r = await authenticated_client.get("/api/v1/referrals/me/list")
        assert r.status_code == 200
        assert r.json() == {"items": []}

    async def test_lists_signups_anonymized(self, authenticated_client, seeded_user, db_session):
        # Seed: my code, plus 2 referees with rows pointing at it.
        my_code = ReferralCodeDB(user_id=seeded_user.id, code="testxyz")
        db_session.add(my_code)
        db_session.flush()

        for uid, name, status in [
            (200, "Bruno Lima", "converted"),
            (201, "Carla", "pending"),
        ]:
            db_session.add(UserDB(
                id=uid, email=f"u{uid}@x.com", password_hash="x",
                name=name, fitness_level="intermediate",
            ))
            db_session.add(ReferralDB(
                code_id=my_code.id, referred_user_id=uid, status=status,
            ))
        db_session.commit()

        r = await authenticated_client.get("/api/v1/referrals/me/list")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        names = {it["referee_name"] for it in items}
        assert names == {"Bruno", "Carla"}  # first names only
        statuses = {it["status"] for it in items}
        assert statuses == {"pending", "converted"}


# ==========================================================
# Web route — /dashboard/referrals
# ==========================================================

@pytest.mark.asyncio
class TestReferralsWebRoute:
    async def test_page_renders(self, async_client):
        r = await async_client.get("/dashboard/referrals")
        assert r.status_code == 200
        body = r.text
        assert "Refer a friend" in body or "Indicar um amigo" in body


# ==========================================================
# Web — register page captures ?ref=
# ==========================================================

@pytest.mark.asyncio
class TestRegisterPageRefCapture:
    async def test_banner_placeholder_present(self, async_client):
        """Register page must include the hidden banner element + capture JS."""
        r = await async_client.get("/register")
        assert r.status_code == 200
        body = r.text
        assert 'id="ref-banner"' in body
        assert 'id="ref-banner-code"' in body
        # JS hook reads ?ref= from URL
        assert "ref" in body and "URLSearchParams" in body
        # Banner copy from i18n is injected
        assert ("Invited with code" in body) or ("Convidado com o código" in body)
