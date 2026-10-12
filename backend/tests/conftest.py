import os
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://seatlock_test:test_only@127.0.0.1:55433/seatlock_test"
)
os.environ["ADMIN_TOKEN"] = "test-organizer-token"

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from alembic import command
from app.db import SessionLocal, engine
from app.main import app
from app.models import Event, Seat


@pytest.fixture(scope="session", autouse=True)
def migrate_test_database():
    if not engine.url.database.endswith("_test"):
        raise RuntimeError("Refusing to clear a database whose name does not end in _test")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def fixture_data():
    with SessionLocal.begin() as db:
        db.execute(text("TRUNCATE audit_events, seats, holds, events RESTART IDENTITY CASCADE"))
        event = Event(
            slug="test-show",
            title="Test Show",
            category="Music",
            venue="Test Hall",
            city="Bengaluru",
            starts_at=datetime.now(UTC) + timedelta(days=10),
            description="A fictional test performance.",
            theme="violet",
            price_paise=100000,
            published=True,
        )
        db.add(event)
        db.flush()
        db.add_all([Seat(event_id=event.id, row="A", number=n) for n in range(1, 9)])


@pytest.fixture
def client():
    with TestClient(app, headers={"X-Seatlock-Request": "1"}) as c:
        c.get("/api/session")
        yield c


@pytest.fixture
def other():
    with TestClient(app, headers={"X-Seatlock-Request": "1"}) as c:
        c.get("/api/session")
        yield c
