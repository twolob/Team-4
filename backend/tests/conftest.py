# ruff: noqa: E402
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["FASTAPI_ENV"] = "development"
os.environ["EMAILS_FROM_EMAIL"] = "noreply@example.com"

# Configure a disposable database before importing any application modules.
_test_directory = tempfile.TemporaryDirectory(prefix="agtrack-tests-")
os.environ["DATABASE_URL"] = (
    "sqlite:///" + (Path(_test_directory.name) / "test.db").as_posix()
)

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    with Session(engine) as session:
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
        init_db(session)
        yield session
        session.rollback()
        from app.models import SQLModel

        for table in reversed(SQLModel.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    engine.dispose()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )


@pytest.fixture(autouse=True)
def mock_email_transport():
    """Exercise email rendering without sending external messages."""
    with patch("emails.Message.send"):
        yield
