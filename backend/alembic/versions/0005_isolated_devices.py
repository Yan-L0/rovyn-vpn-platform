"""Separate device credentials while preserving legacy subscriptions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_isolated_devices"
down_revision = "0004_merge_identity_and_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("isolated_devices", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "vpn_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider_user_id", sa.String(128), unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_vpn_devices_subscription_id", "vpn_devices", ["subscription_id"])


def downgrade() -> None:
    op.drop_table("vpn_devices")
    op.drop_column("subscriptions", "isolated_devices")
