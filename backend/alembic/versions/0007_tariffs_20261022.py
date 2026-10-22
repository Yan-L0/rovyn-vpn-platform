"""New purchases use the approved finite quotas and speed policies."""
from alembic import op

revision = "0007_tariffs_20261022"
down_revision = "0006_transport_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = """
      UPDATE plans SET price_minor=11100, traffic_limit_bytes=26843545600,
        access_policy=jsonb_build_object('mbps',70),
        description='25 ГБ на весь срок · до 70 Мбит/с'
      WHERE code='MONTH';
      UPDATE plans SET price_minor=56000, traffic_limit_bytes=214748364800,
        access_policy=jsonb_build_object('mbps',100),
        description='200 ГБ на весь срок · до 100 Мбит/с'
      WHERE code='HALF_YEAR';
      UPDATE plans SET price_minor=96000, traffic_limit_bytes=0,
        access_policy=jsonb_build_object('mbps',0,'fup',true),
        description='Безлимитный трафик. При среднем скачивании выше 100 Мбит/с за 10 минут — до 100 Мбит/с. Восстановление после 15 минут нагрузки ниже 10 Мбит/с.'
      WHERE code='YEAR';
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("""
      UPDATE plans SET traffic_limit_bytes=0, access_policy='{}'::jsonb,
        price_minor=CASE code WHEN 'MONTH' THEN 10500 WHEN 'HALF_YEAR' THEN 52500 ELSE 94500 END,
        description=CASE code WHEN 'MONTH' THEN 'Чтобы познакомиться'
          WHEN 'HALF_YEAR' THEN 'Оптимальный период' ELSE 'Максимальная выгода' END
      WHERE code IN ('MONTH','HALF_YEAR','YEAR');
    """)
