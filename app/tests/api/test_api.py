"""API tests: HTTP requests against the app with an in-memory store."""

import pytest
from fastapi.testclient import TestClient

from flightstatus.main import create_app
from flightstatus.store import PostgresStore

NEW_FLIGHT = {
    "number": "UA999",
    "origin": "DEN",
    "destination": "SFO",
    "departure": "2026-10-27T18:30:00Z",
    "gate": "B30",
}


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_with_memory_store(client):
    assert client.get("/ready").json() == {"status": "ready", "storage": "memory"}


def test_not_ready_when_database_is_unreachable():
    # Port 1 on localhost refuses connections, so the readiness check fails fast.
    app = create_app(store=PostgresStore("postgresql://nobody@127.0.0.1:1/none"))
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not ready"


def test_version_fields(client):
    assert set(client.get("/version").json()) == {"version", "commit", "environment"}


def test_sample_flights_are_loaded(client):
    assert len(client.get("/flights").json()) == 8


def test_filter_by_origin(client):
    flights = client.get("/flights", params={"origin": "ord"}).json()
    assert {f["number"] for f in flights} == {"UA101", "UA202", "UA707"}


def test_filter_by_status(client):
    flights = client.get("/flights", params={"status": "DELAYED"}).json()
    assert [f["number"] for f in flights] == ["UA505"]


def test_get_flight_ignores_case(client):
    response = client.get("/flights/ua101")
    assert response.status_code == 200
    assert response.json()["destination"] == "SFO"


def test_unknown_flight_returns_404(client):
    assert client.get("/flights/UA1").status_code == 404


def test_create_flight(client):
    assert client.post("/flights", json=NEW_FLIGHT).status_code == 201
    assert client.get("/flights/UA999").json()["gate"] == "B30"


def test_create_duplicate_returns_409(client):
    client.post("/flights", json=NEW_FLIGHT)
    assert client.post("/flights", json=NEW_FLIGHT).status_code == 409


@pytest.mark.parametrize(
    "change", [{"origin": "Denver"}, {"destination": "DEN"}, {"number": "UNITED1"}]
)
def test_invalid_flight_returns_422(client, change):
    assert client.post("/flights", json=NEW_FLIGHT | change).status_code == 422


def test_status_update(client):
    response = client.patch("/flights/UA101/status", json={"status": "BOARDING"})
    assert response.status_code == 200
    assert client.get("/flights/UA101").json()["status"] == "BOARDING"


def test_forbidden_status_update_returns_409(client):
    response = client.patch("/flights/UA101/status", json={"status": "ARRIVED"})
    assert response.status_code == 409
    assert "SCHEDULED to ARRIVED" in response.json()["detail"]


def test_home_page_lists_flights(client):
    page = client.get("/").text
    assert "UA101" in page
    assert "Version dev" in page


def test_production_needs_a_database(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app()
