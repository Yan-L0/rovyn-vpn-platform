"""Merge email identity and production catalog migration branches.

Revision ID: 0004_merge_identity_and_catalog
Revises: 0003_email_accounts, 0003_rovyn_catalog
"""

from collections.abc import Sequence

revision: str = "0004_merge_identity_and_catalog"
down_revision: tuple[str, str] = ("0003_email_accounts", "0003_rovyn_catalog")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
