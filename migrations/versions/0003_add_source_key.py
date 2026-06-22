import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Портативный sa.String (не нативный PG-тип) — schema совместима с SQLite (guard-тест).
    op.add_column("tasks", sa.Column("source_key", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "source_key")
