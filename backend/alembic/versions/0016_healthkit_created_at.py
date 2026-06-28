"""0016 align healthkit_data timestamp column with production schema

Production was created with ``created_at``; migration 0006 used ``synced_at``.
The SQLModel now maps ``created_at``. This revision renames when needed and is
a no-op when ``created_at`` already exists.

Revision ID: 0016healthkit_ts
Revises: 0015realign_diet
Create Date: 2026-06-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016healthkit_ts"
down_revision: Union[str, None] = "0015realign_diet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "healthkit_data" not in insp.get_table_names():
        return

    cols = {c["name"]: c for c in insp.get_columns("healthkit_data")}

    if "synced_at" in cols and "created_at" not in cols:
        op.alter_column("healthkit_data", "synced_at", new_column_name="created_at")
    elif "created_at" not in cols:
        op.add_column(
            "healthkit_data",
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )

    user_col = cols.get("user_id")
    if user_col and user_col["type"].__class__.__name__ in ("TEXT", "String", "VARCHAR"):
        op.execute(
            "ALTER TABLE healthkit_data "
            "ALTER COLUMN user_id TYPE INTEGER USING user_id::integer"
        )
        existing_fks = {fk["name"] for fk in insp.get_foreign_keys("healthkit_data")}
        if "healthkit_data_user_id_fkey" not in existing_fks:
            op.create_foreign_key(
                "healthkit_data_user_id_fkey",
                "healthkit_data",
                "users",
                ["user_id"],
                ["id"],
            )

    for col_name in ("start_date", "end_date"):
        col = cols.get(col_name)
        if col and col["type"].__class__.__name__ in ("TEXT", "String", "VARCHAR"):
            op.execute(
                f"ALTER TABLE healthkit_data "
                f"ALTER COLUMN {col_name} TYPE TIMESTAMP "
                f"USING NULLIF({col_name}, '')::timestamp"
            )
            op.alter_column("healthkit_data", col_name, nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "healthkit_data" not in insp.get_table_names():
        return

    cols = {c["name"] for c in insp.get_columns("healthkit_data")}
    if "created_at" in cols and "synced_at" not in cols:
        op.alter_column("healthkit_data", "created_at", new_column_name="synced_at")
