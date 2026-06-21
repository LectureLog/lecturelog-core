import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Портативный sa.JSON (не JSONB) — schema совместима с SQLite (guard-тест).
    op.add_column(
        "tasks",
        sa.Column("usage", sa.JSON, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "usage")
