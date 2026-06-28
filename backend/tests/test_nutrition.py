"""
Tests for Nutrition API — meal logging and macro tracking (SQLAlchemy).
"""
from datetime import datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient


class TestMealLogging:
    @pytest.mark.asyncio
    async def test_log_meal(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        payload = {
            "meal_type": "breakfast",
            "logged_at": datetime.utcnow().isoformat(),
            "description": "Oatmeal with berries",
            "calories": 350,
            "protein_g": 12,
            "carbs_g": 55,
            "fat_g": 8,
        }
        response = await authenticated_client.post("/api/v1/nutrition/meals", json=payload)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["meal_type"] == "breakfast"
        assert data["calories"] == 350

    @pytest.mark.asyncio
    async def test_get_todays_meals(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import MealLog
        for meal_type, cal in [("breakfast", 350), ("lunch", 600)]:
            db_session.add(MealLog(
                user_id=seeded_user.id,
                meal_type=meal_type,
                calories=cal,
                protein_g=20,
                carbs_g=40,
                fat_g=10,
            ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/nutrition/meals/today")
        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_get_todays_meals_empty(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.get("/api/v1/nutrition/meals/today")
        assert response.status_code == 200
        assert response.json() == []


class TestMacroSummary:
    @pytest.mark.asyncio
    async def test_get_macro_summary(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import MealLog
        db_session.add(MealLog(
            user_id=seeded_user.id, calories=350, protein_g=12, carbs_g=55, fat_g=8,
        ))
        db_session.add(MealLog(
            user_id=seeded_user.id, calories=600, protein_g=45, carbs_g=50, fat_g=20,
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/nutrition/macros/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["calories"] == 950
        assert data["protein_g"] == 57
        assert data["carbs_g"] == 105
        assert data["fat_g"] == 28
        assert data["meals_logged"] == 2
        assert data["targets"]["calories"] == 2000
        assert data["target_source"] == "default"

    @pytest.mark.asyncio
    async def test_get_macro_summary_no_meals(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.get("/api/v1/nutrition/macros/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["calories"] == 0
        assert data["meals_logged"] == 0

    @pytest.mark.asyncio
    async def test_get_macro_summary_partial_data(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        from app.db.models import MealLog
        db_session.add(MealLog(
            user_id=seeded_user.id,
            calories=350,
            protein_g=None,  # missing
            carbs_g=55,
            fat_g=8,
        ))
        db_session.commit()

        response = await authenticated_client.get("/api/v1/nutrition/macros/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["calories"] == 350
        assert data["protein_g"] == 0
        assert data["carbs_g"] == 55


class TestMacroTargets:
    @pytest.mark.asyncio
    async def test_set_and_get_manual_targets(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.put(
            "/api/v1/nutrition/targets",
            json={"calories": 2600, "protein": 180, "carbs": 250, "fat": 80},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["calories"] == 2600
        assert data["source"] == "manual"

        get_resp = await authenticated_client.get("/api/v1/nutrition/targets")
        assert get_resp.status_code == 200
        assert get_resp.json()["calories"] == 2600
        assert get_resp.json()["source"] == "manual"

    @pytest.mark.asyncio
    async def test_reset_manual_targets(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        await authenticated_client.put(
            "/api/v1/nutrition/targets",
            json={"calories": 2400, "protein": 160, "carbs": 220, "fat": 75},
        )
        reset = await authenticated_client.delete("/api/v1/nutrition/targets")
        assert reset.status_code == 200
        assert reset.json()["source"] == "default"
        assert reset.json()["calories"] == 2000

    @pytest.mark.asyncio
    async def test_set_targets_rejects_invalid_calories(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        response = await authenticated_client.put(
            "/api/v1/nutrition/targets",
            json={"calories": 500},
        )
        assert response.status_code == 422


class TestMealPhotoAnalysis:
    """Photo upload endpoint — uses a stub parser to keep tests offline."""

    # Smallest possible valid PNG (1x1 transparent pixel) so the endpoint
    # accepts it as an image.
    _PNG_1x1 = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )

    @pytest.fixture
    def stub_parser(self, monkeypatch):
        async def _fake(image_bytes, content_type=""):
            return {
                "foods": [{"name": "Frango grelhado", "portion": "150g", "calories": 240, "protein_g": 45, "carbs_g": 0, "fat_g": 6}],
                "totals": {"calories": 240, "protein_g": 45, "carbs_g": 0, "fat_g": 6},
                "description": "Filé de frango grelhado",
                "confidence": "medium",
                "ai_used": True,
            }
        # Patch the symbol the route imported, not the source module.
        import app.api.v1.nutrition as nutrition_route
        monkeypatch.setattr(nutrition_route, "parse_meal_photo", _fake)
        return _fake

    @pytest.mark.asyncio
    async def test_photo_analyze_only(
        self, authenticated_client: AsyncClient, db_session, seeded_user, stub_parser
    ):
        files = {"file": ("plate.png", self._PNG_1x1, "image/png")}
        response = await authenticated_client.post(
            "/api/v1/nutrition/meals/photo", files=files, data={"save": "false"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["analysis"]["totals"]["protein_g"] == 45
        assert body["meal"] is None  # not persisted

    @pytest.mark.asyncio
    async def test_photo_analyze_and_save(
        self, authenticated_client: AsyncClient, db_session, seeded_user, stub_parser
    ):
        files = {"file": ("plate.png", self._PNG_1x1, "image/png")}
        response = await authenticated_client.post(
            "/api/v1/nutrition/meals/photo",
            files=files,
            data={"save": "true", "meal_type": "lunch"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["meal"] is not None
        assert body["meal"]["meal_type"] == "lunch"
        assert body["meal"]["calories"] == 240
        assert body["meal"]["ai_estimation"] is True

    @pytest.mark.asyncio
    async def test_photo_rejects_non_image_extension(
        self, authenticated_client: AsyncClient, db_session, seeded_user, stub_parser
    ):
        files = {"file": ("plate.txt", b"hello", "text/plain")}
        response = await authenticated_client.post(
            "/api/v1/nutrition/meals/photo", files=files
        )
        assert response.status_code == 400
        assert "Allowed image formats" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_photo_rejects_empty_file(
        self, authenticated_client: AsyncClient, db_session, seeded_user, stub_parser
    ):
        files = {"file": ("plate.png", b"", "image/png")}
        response = await authenticated_client.post(
            "/api/v1/nutrition/meals/photo", files=files
        )
        assert response.status_code == 400
