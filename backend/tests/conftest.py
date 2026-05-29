"""
Pytest configuration and shared fixtures.

Provides:
- `mock_user`: dict representation of an authenticated user (INT id).
- `override_auth`: replaces `get_current_user` with the mock user.
- `mock_supabase`: legacy supabase client mock (still used by unmigrated endpoints).
- `db_session`: SQLAlchemy session against an in-memory SQLite DB; the real
  `get_session` dependency is overridden so endpoints see the same session.
- `seeded_user`: creates a User row in `db_session` matching the mock_user id.
"""
import os
import sys
from unittest.mock import Mock, AsyncMock, MagicMock, patch

# Point the app at in-memory SQLite BEFORE importing app modules.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# Mock supabase module before any app imports
sys.modules['supabase'] = Mock()
sys.modules['supabase'].create_client = Mock()
sys.modules['supabase'].Client = Mock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from uuid import uuid4, UUID
from datetime import datetime, date

# Register SQLModel tables on metadata before anything else imports them.
import app.db.models  # noqa: F401
from app.db import session as db_session_module
from app.core.auth import get_current_user
from app.main import app  # imported last so `app` binds to the FastAPI instance


# ============================================
# Mock User Fixture
# ============================================

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear slowapi's quota state between tests so quotas don't leak."""
    try:
        from app.core.rate_limit import limiter
        # slowapi's Limiter exposes .reset() that flushes its storage.
        if hasattr(limiter, "reset"):
            limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture
def mock_user():
    """Mock authenticated user — id is INT to match auth.py/User table.

    Default state: a healthy trialing user with 7 days remaining. Endpoints
    gated by require_active_subscription will pass. Tests that need to
    exercise the paywall path can override individual fields.
    """
    from datetime import datetime, timedelta
    return {
        "id": 1,
        "auth_user_id": str(uuid4()),  # legacy field, kept for unmigrated tests
        "email": "test@example.com",
        "name": "Test Athlete",
        "fitness_level": "intermediate",
        "birth_date": "1990-01-01",
        "weight_kg": 80.0,
        "height_cm": 175.0,
        "goals": ["strength", "conditioning"],
        "timezone": "America/Sao_Paulo",
        "subscription_status": "trialing",
        "trial_expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        "preferences": {
            "goals": ["strength", "conditioning"],
            "methodology": "hwpo",
            "weaknesses": [],
        },
    }


@pytest.fixture
def mock_user_uuid(mock_user):
    """Legacy alias — returns int id (was UUID before auth migration)."""
    return mock_user["id"]


# ============================================
# Override get_current_user dependency
# ============================================

@pytest.fixture
def override_auth(mock_user):
    """Override authentication dependency to bypass auth checks"""
    async def _get_current_user_override():
        return mock_user

    # Override the dependency
    app.dependency_overrides[get_current_user] = _get_current_user_override

    yield mock_user

    # Clean up
    app.dependency_overrides.clear()


# ============================================
# SQLAlchemy session (in-memory SQLite)
# ============================================

@pytest.fixture(autouse=True)
def db_session():
    """Fresh in-memory SQLite DB per test — schema created from SQLModel metadata.

    `autouse=True` so any test (even those that don't list the fixture) gets
    tables available. The fixture also overrides `app.db.session.get_session`
    so FastAPI endpoints reach the same session.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # single in-memory DB shared across connections
    )
    SQLModel.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Swap the module-level engine/SessionLocal so `get_session` and any
    # helper that imports `SessionLocal` talk to this same DB.
    prev_engine = db_session_module.engine
    prev_sessionmaker = db_session_module.SessionLocal
    db_session_module.engine = engine
    db_session_module.SessionLocal = TestSession

    def _override_get_session():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    from app.db.session import get_session as _real_get_session
    app.dependency_overrides[_real_get_session] = _override_get_session

    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.pop(_real_get_session, None)
        db_session_module.engine = prev_engine
        db_session_module.SessionLocal = prev_sessionmaker
        engine.dispose()


@pytest.fixture
def seeded_user(db_session, mock_user):
    """Insert the mock_user into the DB and return the persisted row."""
    from app.db.models import User as UserDB

    user = UserDB(
        id=mock_user["id"],
        email=mock_user["email"],
        password_hash="$2b$12$placeholder",
        name=mock_user["name"],
        fitness_level=mock_user["fitness_level"],
        weight_kg=mock_user["weight_kg"],
        height_cm=mock_user["height_cm"],
        goals=mock_user["goals"],
        timezone=mock_user["timezone"],
        preferences=mock_user["preferences"],
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ============================================
# Mock Supabase Client
# ============================================

class MockSupabaseResponse:
    """Mock Supabase response object"""
    def __init__(self, data=None, error=None):
        self.data = data or []
        self.error = error


class MockSupabaseQuery:
    """Mock Supabase query builder"""
    def __init__(self, table_name, mock_data=None):
        self.table_name = table_name
        # Preserve the shared dict reference — `mock_data or {}` would replace
        # an empty (falsy) shared dict with a fresh one, breaking sequential
        # insert/select flows on the same table.
        self.mock_data = {} if mock_data is None else mock_data
        self._filters = {}
        self._single = False
        self._order_by = None
        self._limit_val = None
        self._offset_val = 0
    
    def select(self, *args):
        return self
    
    def insert(self, data):
        # Return inserted data with generated ID + timestamps (mirrors real Supabase defaults).
        now = datetime.utcnow().isoformat()
        if isinstance(data, list):
            result = []
            for item in data:
                item.setdefault("id", str(uuid4()))
                item.setdefault("created_at", now)
                item.setdefault("updated_at", now)
                result.append(item)
            self.mock_data["response"] = result
        else:
            data.setdefault("id", str(uuid4()))
            data.setdefault("created_at", now)
            data.setdefault("updated_at", now)
            self.mock_data["response"] = [data]
        return self
    
    def update(self, data):
        self.mock_data["update_data"] = data
        # Merge update data with existing mock data if available
        if "response" in self.mock_data and self.mock_data["response"]:
            existing = self.mock_data["response"]
            if isinstance(existing, dict):
                merged = {**existing, **data}
                merged["updated_at"] = datetime.utcnow().isoformat()
                self.mock_data["response"] = [merged]
            elif isinstance(existing, list) and existing:
                merged = {**existing[0], **data}
                merged["updated_at"] = datetime.utcnow().isoformat()
                self.mock_data["response"] = [merged]
            else:
                self.mock_data["response"] = [data] if data else []
        else:
            self.mock_data["response"] = [data] if data else []
        return self
    
    def upsert(self, data, **kwargs):
        if isinstance(data, list):
            result = []
            for item in data:
                if "id" not in item:
                    item["id"] = str(uuid4())
                if "created_at" not in item:
                    item["created_at"] = datetime.utcnow().isoformat()
                result.append(item)
            self.mock_data["response"] = result
        else:
            if "id" not in data:
                data["id"] = str(uuid4())
            if "created_at" not in data:
                data["created_at"] = datetime.utcnow().isoformat()
            self.mock_data["response"] = [data]
        return self
    
    def delete(self):
        self.mock_data["response"] = []
        return self
    
    def eq(self, column, value):
        self._filters[column] = value
        return self
    
    def gte(self, column, value):
        self._filters[f"{column}__gte"] = value
        return self
    
    def lte(self, column, value):
        self._filters[f"{column}__lte"] = value
        return self
    
    def order(self, column, **kwargs):
        self._order_by = (column, kwargs)
        return self
    
    def limit(self, limit):
        self._limit_val = limit
        return self
    
    def range(self, start, end):
        self._offset_val = start
        self._limit_val = end - start + 1
        return self
    
    def single(self):
        self._single = True
        return self
    
    def execute(self):
        """Execute the query and return mock response"""
        # Check if mock_data has explicit response
        if "response" in self.mock_data:
            data = self.mock_data["response"]
            if self._single and data:
                return MockSupabaseResponse(data=data[0] if isinstance(data, list) else data)
            return MockSupabaseResponse(data=data)
        
        # Otherwise return empty
        if self._single:
            return MockSupabaseResponse(data=None)
        return MockSupabaseResponse(data=[])


class MockSupabaseAuth:
    """Mock Supabase Auth"""
    def __init__(self):
        self.admin = Mock()
        self.admin.delete_user = Mock()
    
    def sign_up(self, credentials):
        user_id = str(uuid4())
        return Mock(
            user=Mock(id=user_id, email=credentials.get("email")),
            session=Mock(access_token=f"mock_token_{user_id}", expires_in=3600)
        )
    
    def sign_in_with_password(self, credentials):
        user_id = str(uuid4())
        return Mock(
            user=Mock(id=user_id, email=credentials.get("email")),
            session=Mock(access_token=f"mock_token_{user_id}", expires_in=3600)
        )
    
    def sign_out(self):
        return Mock()
    
    def get_user(self, token):
        return Mock(user=Mock(id=str(uuid4()), email="test@example.com"))
    
    def get_session(self):
        return Mock(
            access_token="mock_session_token",
            user=Mock(id=str(uuid4()), email="test@example.com"),
            expires_in=3600
        )

    def refresh_session(self, refresh_token):
        return Mock(
            session=Mock(
                access_token="mock_refreshed_token_" + str(uuid4())[:8],
                refresh_token="mock_new_refresh_token",
                user=Mock(id=str(uuid4()), email="test@example.com"),
                expires_in=3600
            )
        )
    
    def reset_password_email(self, email, **kwargs):
        return Mock()
    
    def update_user(self, data):
        return Mock()


class MockSupabaseClient:
    """Mock Supabase client"""
    def __init__(self):
        self.auth = MockSupabaseAuth()
        self._tables = {}
    
    def table(self, table_name):
        """Return mock query builder for table"""
        if table_name not in self._tables:
            self._tables[table_name] = {}
        return MockSupabaseQuery(table_name, self._tables[table_name])
    
    def set_mock_data(self, table_name, data):
        """Set mock data for a table"""
        self._tables[table_name] = {"response": data}


@pytest.fixture
def mock_supabase():
    """No-op stub kept so legacy tests that accept the fixture still collect.

    All production code paths have been migrated off supabase_client; this
    fixture just hands back an in-memory stand-in with `set_mock_data` so
    any remaining calls in tests don't crash during collection. Prefer using
    the `db_session` + `seeded_user` fixtures for new tests.
    """
    yield MockSupabaseClient()


# ============================================
# Mock OpenAI & Anthropic
# ============================================

@pytest.fixture
def mock_openai():
    """Mock OpenAI client"""
    with patch("openai.OpenAI") as mock:
        mock_client = Mock()
        mock_client.chat.completions.create = AsyncMock(return_value=Mock(
            choices=[Mock(message=Mock(content="Mock AI response"))]
        ))
        mock.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic client"""
    with patch("anthropic.Anthropic") as mock:
        mock_client = Mock()
        mock_client.messages.create = AsyncMock(return_value=Mock(
            content=[Mock(text="Mock Claude response")]
        ))
        mock.return_value = mock_client
        yield mock_client


# ============================================
# AsyncClient for FastAPI testing
# ============================================

@pytest_asyncio.fixture
async def async_client(mock_supabase):
    """Async HTTP client for FastAPI app"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def authenticated_client(async_client, override_auth):
    """Authenticated async client with mocked user"""
    async_client.headers.update({"Authorization": "Bearer mock_token"})
    yield async_client


# ============================================
# Mock psycopg2 database functions
# ============================================

from contextlib import contextmanager

class MockCursor:
    def __init__(self):
        self._result = []
        self.rowcount = 1
        self._lastval = 1  # Simulates PostgreSQL lastval()
    
    def execute(self, query, *args):
        # Check if this is a lastval() call
        if query and 'lastval' in query.lower():
            self._result = [(self._lastval,)]
        else:
            self._result = []
    
    def fetchone(self):
        result = self._result[0] if self._result else None
        self._result = []
        return result
    
    def fetchall(self):
        return self._result
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass

class MockConnection:
    def __init__(self):
        self._cursor = MockCursor()
    
    def cursor(self):
        return self._cursor
    
    def commit(self):
        pass
    
    def rollback(self):
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass

class MockPool:
    def getconn(self):
        return MockConnection()
    
    def putconn(self, conn):
        pass
    
    def closeall(self):
        pass

@pytest.fixture(autouse=True)
def mock_database(monkeypatch):
    """Mock database functions to avoid real DB connections"""
    from app.db import database
    
    mock_pool = MockPool()
    database.connection_pool = mock_pool
    
    @contextmanager
    def mock_get_connection():
        yield MockConnection()
    
    def mock_init_db():
        pass
    
    def mock_fetchone(query, *args):
        return None
    
    def mock_execute(query, *args):
        return 1
    
    monkeypatch.setattr("app.db.database.get_pool", lambda: mock_pool)
    monkeypatch.setattr("app.db.database.init_db", mock_init_db)
    monkeypatch.setattr("app.db.database.fetchone", mock_fetchone)
    monkeypatch.setattr("app.db.database.execute", mock_execute)
    monkeypatch.setattr("app.db.database.get_connection", mock_get_connection)
