"""Integration tests: the PostgreSQL store against a real database.

These tests are skipped unless DATABASE_URL is set, for example:
DATABASE_URL=postgresql://flights:flights@db:5432/flights
"""

import os
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flightstatus.main import create_app
from flightstatus.models import Flight, FlightStatus
from flightstatus.store import FlightExists, PostgresStore

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not set"),
]

FLIGHT = Flight(
    number="UA321",
    origin="EWR",
    destination="ORD",
    departure=datetime(2026, 10, 28, 9, 15, tzinfo=UTC),
)


@pytest.fixture
def store():
    """A Postgres store with an empty flights table."""
    s = PostgresStore(DATABASE_URL)
    # In a pipeline, the database service may still be starting. Wait up to 30 seconds.
    deadline = time.monotonic() + 30
    while not s.ping():
        if time.monotonic() > deadline:
            pytest.fail(f"database at {DATABASE_URL} did not become ready")
        time.sleep(1)
    s.setup()
    with s._connect() as conn:
        conn.execute("TRUNCATE flights")
    return s


def test_ping(store):
    assert store.ping()


def test_add_and_get(store):
    store.add(FLIGHT)
    assert store.get("UA321") == FLIGHT


def test_duplicate_is_rejected(store):
    store.add(FLIGHT)
    with pytest.raises(FlightExists):
        store.add(FLIGHT)


def test_save_updates_status(store):
    store.add(FLIGHT)
    store.save(FLIGHT.model_copy(update={"status": FlightStatus.DELAYED, "delay_minutes": 20}))
    assert store.get("UA321").delay_minutes == 20


def test_data_survives_a_new_connection(store):
    store.add(FLIGHT)
    assert PostgresStore(DATABASE_URL).list() == [FLIGHT]


def test_api_reports_postgres_storage(store):
    with TestClient(create_app(store=store)) as client:
        assert client.get("/ready").json() == {"status": "ready", "storage": "postgres"}
        assert len(client.get("/flights").json()) == 8
