"""Store durable per-user daily VPN usage.

Revision ID: 0002_vpn_usage_daily
Revises: 0001_initial
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_vpn_usage_daily"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vpn_usage_daily",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "sampled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("used_bytes >= 0", name="ck_vpn_usage_daily_nonnegative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "usage_date"),
    )
    op.create_index(
        "ix_vpn_usage_daily_user_date",
        "vpn_usage_daily",
        ["user_id", "usage_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vpn_usage_daily_user_date", table_name="vpn_usage_daily")
    op.drop_table("vpn_usage_daily")
