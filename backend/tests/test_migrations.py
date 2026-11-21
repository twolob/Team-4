"""Validate upgrades with historical records without touching the local database."""

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings


def test_upgrade_preserves_existing_records(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "a127d9b47c01")
    engine = create_engine(url)
    user_id, farm_id, item_id = [uuid.uuid4().hex for _ in range(3)]
    with engine.begin() as connection:
        connection.execute(
            text(
                'INSERT INTO "user" (id,email,is_active,is_superuser,hashed_password) VALUES (:id,:email,1,0,:password)'
            ),
            {"id": user_id, "email": "legacy@example.com", "password": "hash"},
        )
        connection.execute(
            text(
                "INSERT INTO farm (id,owner_id,name,county,farm_type,created_at) VALUES (:id,:owner,'Legacy Farm','Bong','Crops',CURRENT_TIMESTAMP)"
            ),
            {"id": farm_id, "owner": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO item (id,owner_id,title) VALUES (:id,:owner,'Legacy Item')"
            ),
            {"id": item_id, "owner": user_id},
        )
    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert len(set(inspector.get_table_names()) - {"alembic_version"}) == 9
    assert inspector.get_foreign_keys("item")
    assert "ix_item_farm_id" in {
        index["name"] for index in inspector.get_indexes("item")
    }
    assert inspector.get_foreign_keys("lossrecord")
    with engine.connect() as connection:
        old_item = connection.execute(
            text("SELECT farm_id,quantity,title FROM item WHERE id=:id"),
            {"id": item_id},
        ).one()
        assert tuple(old_item) == (None, 0, "Legacy Item")
        assert (
            connection.execute(
                text('SELECT email FROM "user" WHERE id=:id'), {"id": user_id}
            ).scalar()
            == "legacy@example.com"
        )
        assert (
            connection.execute(
                text("SELECT name FROM farm WHERE id=:id"), {"id": farm_id}
            ).scalar()
            == "Legacy Farm"
        )
    command.check(config)
    engine.dispose()
