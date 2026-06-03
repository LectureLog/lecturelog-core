from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from lecturelog.infrastructure.persistence.orm import TaskRow


def test_migration_creates_columns_matching_orm(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db}")
    cols = {c["name"] for c in inspect(engine).get_columns("tasks")}
    orm_cols = {c.name for c in TaskRow.__table__.columns}
    assert cols == orm_cols
