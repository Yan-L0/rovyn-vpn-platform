"""Use Rovyn for existing catalogue names without altering purchased terms."""
from alembic import op

revision = "0008_rovyn_brand"
down_revision = "0007_tariffs_20261022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE plans SET name = regexp_replace(name, '^NOVA', 'Rovyn') WHERE name LIKE 'NOVA%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE plans SET name = regexp_replace(name, '^Rovyn', 'NOVA') WHERE name LIKE 'Rovyn%'"
    )
