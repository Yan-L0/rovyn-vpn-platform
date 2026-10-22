"""Snapshot transport terms independently of later catalog changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_transport_policy"
down_revision = "0005_isolated_devices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("plans", "subscriptions"):
        op.add_column(table, sa.Column("access_policy", postgresql.JSONB(), nullable=False,
                                     server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    for table in ("subscriptions", "plans"):
        op.drop_column(table, "access_policy")
