"""0013 add LGPD/GDPR consent record to users

Adds ``terms_accepted_at``, ``terms_version``, ``privacy_version`` so we
can prove (and re-prompt for) consent when the legal documents change.

Backfill rule: existing users get ``terms_accepted_at = created_at``
with ``terms_version = privacy_version = '1.0'``. Documented in CHANGELOG
as implicit consent for accounts created before the explicit checkbox
shipped — operator should communicate this in the next product email.

Revision ID: 0013add_consent
Revises: 0012add_trial
Create Date: 2026-05-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401


revision: str = "0013add_consent"
down_revision: Union[str, None] = "0012add_trial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("terms_version", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("privacy_version", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
    )

    op.execute(
        """
        UPDATE users
           SET terms_accepted_at = created_at,
               terms_version    = '1.0',
               privacy_version  = '1.0'
         WHERE terms_accepted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("users", "privacy_version")
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")
