"""Helpers for user_id columns that may be stored as int or text (legacy schemas)."""
from sqlalchemy import String, cast
from sqlalchemy.sql.elements import ColumnElement


def user_id_equals(column, user_id: int) -> ColumnElement:
    """Compare a user_id column against an int user id safely."""
    return cast(column, String) == str(user_id)


def user_id_value(user_id: int) -> str:
    """Normalize user id for inserts on text-typed legacy columns."""
    return str(user_id)
