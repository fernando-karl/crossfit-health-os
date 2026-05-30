"""0015 realign user_diet_plans with the UserDietPlan model

The table was created in 0006 (calories_target/name/meals_per_day/… for a
hand-authored "macro target" plan) but the UserDietPlan model was later
rewritten around an uploaded-PDF plan (file_name/daily_calories/protein_g/
meals jsonb/…) with no migration. The drift made /api/v1/diet/* raise
``column "file_name" does not exist`` in prod.

The table has no rows in any known environment, so this drops the stale
columns and adds the model's columns (rather than a data-preserving rename).

Revision ID: 0015realign_diet
Revises: 0014add_refresh
Create Date: 2026-05-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel  # noqa: F401


revision: str = "0015realign_diet"
down_revision: Union[str, None] = "0014add_refresh"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_COLUMNS = (
    "name",
    "type",
    "calories_target",
    "protein_target",
    "carbs_target",
    "fat_target",
    "meals_per_day",
    "daily_feeding_window",
)


def upgrade() -> None:
    # New columns the model expects.
    op.add_column("user_diet_plans", sa.Column("file_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))
    op.add_column("user_diet_plans", sa.Column("file_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("daily_calories", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("protein_g", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("carbs_g", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("fat_g", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("meals", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # supplements: text -> jsonb (model stores List[str]).
    op.drop_column("user_diet_plans", "supplements")
    op.add_column("user_diet_plans", sa.Column("supplements", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Drop the stale "macro target" columns.
    for col in _OLD_COLUMNS:
        op.drop_column("user_diet_plans", col)


def downgrade() -> None:
    # Re-create the stale columns (nullable — the original NOT NULL on `name`
    # is relaxed so a downgrade can't fail on a populated table).
    op.add_column("user_diet_plans", sa.Column("name", sa.VARCHAR(length=100), nullable=True))
    op.add_column("user_diet_plans", sa.Column("type", sa.VARCHAR(length=50), nullable=True))
    op.add_column("user_diet_plans", sa.Column("calories_target", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("protein_target", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("carbs_target", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("fat_target", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("meals_per_day", sa.Integer(), nullable=True))
    op.add_column("user_diet_plans", sa.Column("daily_feeding_window", sa.Text(), nullable=True))

    op.drop_column("user_diet_plans", "supplements")
    op.add_column("user_diet_plans", sa.Column("supplements", sa.Text(), nullable=True))

    op.drop_column("user_diet_plans", "meals")
    op.drop_column("user_diet_plans", "fat_g")
    op.drop_column("user_diet_plans", "carbs_g")
    op.drop_column("user_diet_plans", "protein_g")
    op.drop_column("user_diet_plans", "daily_calories")
    op.drop_column("user_diet_plans", "file_url")
    op.drop_column("user_diet_plans", "file_name")
