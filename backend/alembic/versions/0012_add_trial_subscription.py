"""0012 add trial / subscription columns to users

Adds trial_started_at, trial_expires_at, subscription_status,
stripe_customer_id, subscription_id to the users table.

Backfill rule: existing users get trial_started_at = NOW() - 7 days, so
they have 7 days remaining on their 14-day trial before the paywall
kicks in. Gives the operator a buffer to set up Stripe + email comms
before locking out anyone.

Revision ID: 0012add_trial
Revises: 0011add_referrals
Create Date: 2026-05-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401


revision: str = "0012add_trial"
down_revision: Union[str, None] = "0011add_referrals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("trial_started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("trial_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "subscription_status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default="trialing",
        ),
    )
    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("subscription_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    )

    # Backfill existing users: 7 days into a 14-day trial.
    op.execute(
        """
        UPDATE users
           SET trial_started_at = (NOW() AT TIME ZONE 'utc') - INTERVAL '7 days',
               trial_expires_at = (NOW() AT TIME ZONE 'utc') + INTERVAL '7 days'
         WHERE trial_started_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("users", "subscription_id")
    op.drop_column("users", "stripe_customer_id")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "trial_expires_at")
    op.drop_column("users", "trial_started_at")
