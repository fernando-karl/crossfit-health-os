"""
Database helpers for PostgreSQL (sync version using psycopg2)
"""
import psycopg2.pool  # loads psycopg2 + the .pool submodule (used in type annotations below)
from contextlib import contextmanager
from typing import Optional
import os

from app.core.config import settings

# Connection pool
connection_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

def get_pool():
    """Get or create database connection pool"""
    global connection_pool
    if connection_pool is None:
        # Prefer process env (docker-compose / systemd) over settings so
        # tests/CI can override; fall back to settings.DATABASE_URL, which
        # pydantic-settings loads from .env.
        db_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL

        # Parse the URL
        if "://" in db_url:
            # postgresql://user:pass@host:port/dbname
            db_url = db_url.replace("postgresql://", "")
            parts = db_url.split("@")
            user_pass = parts[0].split(":")
            host_db = parts[1].split("/")
            host_port = host_db[0].split(":")

            user = user_pass[0]
            password = user_pass[1] if len(user_pass) > 1 else ""
            host = host_port[0]
            port = host_port[1] if len(host_port) > 1 else "5432"
            database = host_db[1] if len(host_db) > 1 else "crossfit"
        else:
            user = "postgres"
            password = "postgres"
            host = "127.0.0.1"
            port = "5432"
            database = "crossfit"

        connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
    return connection_pool

def close_pool():
    """Close database connection pool"""
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        connection_pool = None

@contextmanager
def get_connection():
    """Get a connection from the pool"""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)

def init_db():
    """Initialize database tables"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    birth_date DATE,
                    weight_kg FLOAT,
                    height_cm FLOAT,
                    fitness_level VARCHAR(50) DEFAULT 'beginner',
                    goals TEXT[],
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("✅ Users table created/verified")

def execute(query: str, *args):
    """Execute a query"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, args)
            return cur.rowcount


def execute_returning(query: str, *args):
    """Execute a query with RETURNING and fetch the first column of the first row."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, args)
            row = cur.fetchone()
            return row[0] if row else None


def fetchone(query: str, *args):
    """Fetch one row"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, args)
            return cur.fetchone()

def fetchall(query: str, *args):
    """Fetch all rows"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, args)
            return cur.fetchall()
