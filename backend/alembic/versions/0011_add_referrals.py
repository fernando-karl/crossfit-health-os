"""0011 add referral codes + referrals tables

Each user gets one human-friendly referral code (slug + digits). Each
signup that redeemed a code is tracked as a Referral row, starting in
``pending`` and (once payments are wired) flipping to ``converted``.

Revision ID: 0011add_referrals
Revises: 0010add_programs
Create Date: 2026-05-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401


revision: str = "0011add_referrals"
down_revision: Union[str, None] = "0010add_programs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "referral_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(length=24), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_referral_codes_user_id"),
        sa.UniqueConstraint("code", name="uq_referral_codes_code"),
    )
    op.create_index(op.f("ix_referral_codes_user_id"), "referral_codes", ["user_id"], unique=False)

    op.create_table(
        "referrals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_id", sa.Uuid(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("converted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["code_id"], ["referral_codes.id"]),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name="uq_referral_referee"),
    )
    op.create_index(op.f("ix_referrals_code_id"), "referrals", ["code_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_referrals_code_id"), table_name="referrals")
    op.drop_table("referrals")
    op.drop_index(op.f("ix_referral_codes_user_id"), table_name="referral_codes")
    op.drop_table("referral_codes")
