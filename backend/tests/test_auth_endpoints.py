"""
Tests for Auth API Endpoints (PostgreSQL version)
Tests registration, login, logout, helper functions
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock
from passlib.context import CryptContext


# ============================================
# Helper function unit tests
# ============================================

class TestPasswordHelpers:
    """Test password hashing and verification helpers"""

    def test_create_jwt_token_returns_string(self):
        from app.api.v1.auth import create_jwt_token
        token = create_jwt_token(user_id=1, email="a@b.com")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_create_jwt_token_is_deterministic_for_same_payload(self):
        """JWTs with identical payload+timestamp would be equal; this just
        verifies the function produces a decodable token."""
        from app.api.v1.auth import create_jwt_token, verify_jwt_token
        token = create_jwt_token(user_id=42, email="x@y.com")
        payload = verify_jwt_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["email"] == "x@y.com"


class TestRegisterRequestValidation:
    """Test RegisterRequest model validation"""

    def test_valid_password_passes(self):
        from app.api.v1.auth import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="SecurePass123",
            confirm_password="SecurePass123",
            name="Test User",
        )
        assert req.validate_password() is True

    def test_password_mismatch_raises(self):
        from app.api.v1.auth import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="SecurePass123",
            confirm_password="Different123",
            name="Test User",
        )
        with pytest.raises(ValueError, match="do not match"):
            req.validate_password()

    def test_no_uppercase_raises(self):
        from app.api.v1.auth import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="nouppercase123",
            confirm_password="nouppercase123",
            name="Test User",
        )
        with pytest.raises(ValueError, match="uppercase"):
            req.validate_password()

    def test_no_lowercase_raises(self):
        from app.api.v1.auth import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="NOLOWERCASE123",
            confirm_password="NOLOWERCASE123",
            name="Test User",
        )
        with pytest.raises(ValueError, match="lowercase"):
            req.validate_password()

    def test_no_digit_raises(self):
        from app.api.v1.auth import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="NoDigitPass",
            confirm_password="NoDigitPass",
            name="Test User",
        )
        with pytest.raises(ValueError, match="number"):
            req.validate_password()


class TestRegisterEndpoint:
    """Test /api/v1/auth/register endpoint"""

    @pytest.mark.asyncio
    async def test_register_password_mismatch_returns_400(self, async_client: AsyncClient):
        """Validation failure before DB access → 400"""
        payload = {
            "email": "test@example.com",
            "password": "SecurePass123",
            "confirm_password": "DifferentPass456",
            "name": "Test User",
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
        assert "do not match" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_no_uppercase_returns_400(self, async_client: AsyncClient):
        """Password without uppercase → 400"""
        payload = {
            "email": "test@example.com",
            "password": "nouppercase123",
            "confirm_password": "nouppercase123",
            "name": "Test User",
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
        assert "uppercase" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_no_digit_returns_400(self, async_client: AsyncClient):
        """Password without digit → 400"""
        payload = {
            "email": "test@example.com",
            "password": "NoDigitPass",
            "confirm_password": "NoDigitPass",
            "name": "Test User",
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
        assert "number" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_too_short_password_returns_422(self, async_client: AsyncClient):
        """Password under 8 chars → pydantic 422"""
        payload = {
            "email": "test@example.com",
            "password": "Ab1",
            "confirm_password": "Ab1",
            "name": "Test User",
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_email_returns_422(self, async_client: AsyncClient):
        """Invalid email → pydantic 422"""
        payload = {
            "email": "not-an-email",
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
            "name": "Test User",
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_existing_user_returns_400(self, async_client: AsyncClient):
        """Duplicate email → 400"""
        existing_user = ("id@1", "existing@example.com", "hash", "Name", None, None, None, "beginner", [])

        with patch("app.api.v1.auth.get_user_by_email", return_value=existing_user):
            payload = {
                "email": "existing@example.com",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
                "name": "Duplicate User",
                "accepted_terms": True,
                "accepted_health_data": True,
            }
            response = await async_client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_success(self, async_client: AsyncClient):
        """Successful registration returns 201"""
        with patch("app.api.v1.auth.get_user_by_email", return_value=None):
            with patch("app.api.v1.auth.create_user", return_value=42):
                payload = {
                    "email": "new@example.com",
                    "password": "SecurePass123",
                    "confirm_password": "SecurePass123",
                    "name": "New User",
                    "fitness_level": "beginner",
                    "goals": ["strength"],
                    "accepted_terms": True,
                    "accepted_health_data": True,
                }
                response = await async_client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 201
        data = response.json()
        # /register now returns the same shape as /login so the frontend
        # doesn't need a second round-trip.
        assert data["token_type"] == "bearer"
        assert data["access_token"]
        assert data["user"]["email"] == "new@example.com"
        assert data["user"]["id"] == 42

    @pytest.mark.asyncio
    async def test_register_db_error_returns_500(self, async_client: AsyncClient):
        """DB failure during create_user → 500"""
        with patch("app.api.v1.auth.get_user_by_email", return_value=None):
            with patch("app.api.v1.auth.create_user", side_effect=Exception("DB error")):
                payload = {
                    "email": "new@example.com",
                    "password": "SecurePass123",
                    "confirm_password": "SecurePass123",
                    "name": "New User",
                    "accepted_terms": True,
                    "accepted_health_data": True,
                }
                response = await async_client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_register_without_terms_returns_400(self, async_client: AsyncClient):
        """LGPD consent: missing terms checkbox → 400 'terms_required'."""
        payload = {
            "email": "new@example.com",
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
            "name": "New User",
            "accepted_terms": False,
            "accepted_health_data": True,
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
        assert response.json()["detail"] == "terms_required"

    @pytest.mark.asyncio
    async def test_register_without_health_consent_returns_400(self, async_client: AsyncClient):
        """LGPD art. 11: missing health-data consent → 400 'health_consent_required'."""
        payload = {
            "email": "new@example.com",
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
            "name": "New User",
            "accepted_terms": True,
            "accepted_health_data": False,
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
        assert response.json()["detail"] == "health_consent_required"


class TestLoginEndpoint:
    """Test /api/v1/auth/login endpoint"""

    @pytest.mark.asyncio
    async def test_login_user_not_found_returns_401(self, async_client: AsyncClient):
        """Non-existent user → 401"""
        with patch("app.api.v1.auth.get_user_by_email", return_value=None):
            response = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": "AnyPass123"},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, async_client: AsyncClient):
        """Wrong password → 401"""
        mock_user_row = (1, "user@example.com", "hashed_pw", "Test User", None, None, None, "beginner", [])

        with patch("app.api.v1.auth.get_user_by_email", return_value=mock_user_row):
            with patch("app.api.v1.auth.verify_password", return_value=False):
                response = await async_client.post(
                    "/api/v1/auth/login",
                    json={"email": "user@example.com", "password": "WrongPass456"},
                )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_success_returns_token(self, async_client: AsyncClient):
        """Correct credentials → 200 with token"""
        mock_user_row = (1, "user@example.com", "hashed_pw", "Test User", None, 80.0, 175.0, "intermediate", ["strength"])

        with patch("app.api.v1.auth.get_user_by_email", return_value=mock_user_row):
            with patch("app.api.v1.auth.verify_password", return_value=True):
                response = await async_client.post(
                    "/api/v1/auth/login",
                    json={"email": "user@example.com", "password": "CorrectPass123"},
                )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_login_missing_password_returns_422(self, async_client: AsyncClient):
        """Missing password field → 422 validation error"""
        response = await async_client.post(
            "/api/v1/auth/login", json={"email": "user@example.com"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_missing_email_returns_422(self, async_client: AsyncClient):
        """Missing email field → 422 validation error"""
        response = await async_client.post(
            "/api/v1/auth/login", json={"password": "AnyPass123"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_with_birth_date_in_response(self, async_client: AsyncClient):
        """Login returns birth_date when user has one"""
        from datetime import date

        birth_date_val = date(1990, 5, 20)
        mock_user_row = (2, "dated@example.com", "hashed_pw", "Dated User", birth_date_val, None, None, "beginner", [])

        with patch("app.api.v1.auth.get_user_by_email", return_value=mock_user_row):
            with patch("app.api.v1.auth.verify_password", return_value=True):
                response = await async_client.post(
                    "/api/v1/auth/login",
                    json={"email": "dated@example.com", "password": "SecurePass123"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["birth_date"] == "1990-05-20"


class TestLogoutEndpoint:
    """Test /api/v1/auth/logout endpoint"""

    @pytest.mark.asyncio
    async def test_logout_returns_200(self, async_client: AsyncClient):
        response = await async_client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert "message" in response.json()


class TestGetMeEndpoint:
    """Test /api/v1/auth/me endpoint"""

    @pytest.mark.asyncio
    async def test_get_me_without_token_returns_401(self, async_client: AsyncClient):
        """Missing Authorization header returns 401 Unauthorized."""
        response = await async_client.get("/api/v1/auth/me")
        assert response.status_code == 401


class TestCreateUser:
    """Unit tests for create_user helper"""

    def test_create_user_calls_execute_and_fetchone(self):
        from app.api.v1.auth import create_user, RegisterRequest

        req = RegisterRequest(
            email="new@example.com",
            password="SecurePass123",
            confirm_password="SecurePass123",
            name="New User",
        )

        with patch("app.api.v1.auth.hash_password", return_value="hashed"):
            with patch("app.api.v1.auth.execute", return_value=1):
                with patch("app.api.v1.auth.fetchone", return_value=(99,)):
                    result = create_user(req)

        assert result == 99

    def test_create_user_returns_none_when_fetchone_empty(self):
        from app.api.v1.auth import create_user, RegisterRequest

        req = RegisterRequest(
            email="new@example.com",
            password="SecurePass123",
            confirm_password="SecurePass123",
            name="New User",
        )

        with patch("app.api.v1.auth.hash_password", return_value="hashed"):
            with patch("app.api.v1.auth.execute", return_value=1):
                with patch("app.api.v1.auth.fetchone", return_value=None):
                    result = create_user(req)

        assert result is None


class TestGetUserByEmail:
    """Unit tests for get_user_by_email helper"""

    def test_returns_none_when_not_found(self):
        from app.api.v1.auth import get_user_by_email

        with patch("app.api.v1.auth.fetchone", return_value=None):
            result = get_user_by_email("missing@example.com")

        assert result is None

    def test_returns_row_when_found(self):
        from app.api.v1.auth import get_user_by_email

        mock_row = (1, "found@example.com", "hashed", "Found User", None, None, None, "beginner", [])
        with patch("app.api.v1.auth.fetchone", return_value=mock_row):
            result = get_user_by_email("found@example.com")

        assert result == mock_row
