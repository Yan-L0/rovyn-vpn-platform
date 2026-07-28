"""Initial business schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-21
"""

from alembic import op

from vpn_platform.db.base import Base
from vpn_platform.db import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This bootstrap revision is frozen at the first development baseline. Before
    # Phase 3 is signed off it is replaced by reviewed, explicit Alembic ops.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    op.execute(
        """
        INSERT INTO plans (
            id, code, name, description, duration_days, traffic_limit_bytes,
            device_limit, price_minor, currency, server_groups, active, sort_order
        ) VALUES
          ('10000000-0000-4000-8000-000000000001', 'BASIC', 'Basic',
           'Для личного использования', 30, 107374182400, 2, 19900, 'RUB',
           '["STANDARD"]'::jsonb, true, 10),
          ('10000000-0000-4000-8000-000000000002', 'PREMIUM', 'Premium',
           'Больше трафика и резервные маршруты', 30, 322122547200, 5, 34900, 'RUB',
           '["STANDARD", "GAME", "RESERVE"]'::jsonb, true, 20),
          ('10000000-0000-4000-8000-000000000003', 'ULTIMATE', 'Ultimate',
           'Максимальный набор серверных групп', 30, 536870912000, 10, 59900, 'RUB',
           '["STANDARD", "GAME", "LTE", "RESERVE"]'::jsonb, true, 30)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
