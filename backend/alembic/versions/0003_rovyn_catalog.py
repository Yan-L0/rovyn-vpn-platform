"""Align the production catalog with the approved cabinet offer.

Revision ID: 0003_rovyn_catalog
Revises: 0002_vpn_usage_daily
Create Date: 2026-08-09
"""

from alembic import op

revision = "0003_rovyn_catalog"
down_revision = "0002_vpn_usage_daily"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = (
        """
        UPDATE plans
        SET code = 'MONTH', name = 'NOVA Месяц', description = 'Чтобы познакомиться',
            duration_days = 30, traffic_limit_bytes = 0, device_limit = 5,
            price_minor = 10500,
            server_groups = '["STANDARD", "GAME", "LTE", "RESERVE"]'::jsonb,
            sort_order = 10
        WHERE id = '10000000-0000-4000-8000-000000000001'
        """,
        """
        UPDATE plans
        SET code = 'YEAR', name = 'NOVA Год', description = 'Максимальная выгода',
            duration_days = 365, traffic_limit_bytes = 0, device_limit = 5,
            price_minor = 94500,
            server_groups = '["STANDARD", "GAME", "LTE", "RESERVE"]'::jsonb,
            sort_order = 20
        WHERE id = '10000000-0000-4000-8000-000000000002'
        """,
        """
        UPDATE plans
        SET code = 'HALF_YEAR', name = 'NOVA Полгода',
            description = 'Оптимальный период', duration_days = 180,
            traffic_limit_bytes = 0, device_limit = 5, price_minor = 52500,
            server_groups = '["STANDARD", "GAME", "LTE", "RESERVE"]'::jsonb,
            sort_order = 30
        WHERE id = '10000000-0000-4000-8000-000000000003'
        """,
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = (
        """
        UPDATE plans
        SET code = 'BASIC', name = 'Basic', description = 'Для личного использования',
            duration_days = 30, traffic_limit_bytes = 107374182400,
            device_limit = 2, price_minor = 19900,
            server_groups = '["STANDARD"]'::jsonb, sort_order = 10
        WHERE id = '10000000-0000-4000-8000-000000000001'
        """,
        """
        UPDATE plans
        SET code = 'PREMIUM', name = 'Premium',
            description = 'Больше трафика и резервные маршруты',
            duration_days = 30, traffic_limit_bytes = 322122547200,
            device_limit = 5, price_minor = 34900,
            server_groups = '["STANDARD", "GAME", "RESERVE"]'::jsonb,
            sort_order = 20
        WHERE id = '10000000-0000-4000-8000-000000000002'
        """,
        """
        UPDATE plans
        SET code = 'ULTIMATE', name = 'Ultimate',
            description = 'Максимальный набор серверных групп',
            duration_days = 30, traffic_limit_bytes = 536870912000,
            device_limit = 10, price_minor = 59900,
            server_groups = '["STANDARD", "GAME", "LTE", "RESERVE"]'::jsonb,
            sort_order = 30
        WHERE id = '10000000-0000-4000-8000-000000000003'
        """,
    )
    for statement in statements:
        op.execute(statement)
