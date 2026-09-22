"""پیکربندی تست‌های خودکار Pytest."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from mas_app.config import Settings
from mas_app.db.session import Database
from mas_app.main import create_app


@pytest.fixture(scope="session")
def temp_storage_dir() -> Generator[str, None, None]:
    path = tempfile.mkdtemp(prefix="mas_test_storage_")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def settings(temp_storage_dir: str) -> Settings:
    return Settings(
        env="test",
        database_url="sqlite:///:memory:",
        secret_key="test-secret-key-at-least-32-characters-long",
        storage_backend="local",
        storage_dir=temp_storage_dir,
        login_max_attempts=10,
        run_migrations_on_startup=True,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app) -> Database:
    return app.state.database


@pytest.fixture
def db_session(db: Database) -> Generator[Session, None, None]:
    with db.session() as s:
        yield s
