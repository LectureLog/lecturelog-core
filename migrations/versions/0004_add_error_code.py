import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Портативный sa.String(32), не нативный enum — schema совместима с SQLite (guard-тест).
    op.add_column("tasks", sa.Column("error_code", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "error_code")
