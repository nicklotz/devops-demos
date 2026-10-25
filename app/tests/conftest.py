import pytest
from fastapi.testclient import TestClient

from flightstatus.main import create_app
from flightstatus.store import MemoryStore


@pytest.fixture
def client():
    """An API client backed by a fresh in-memory store with the sample flights."""
    with TestClient(create_app(store=MemoryStore())) as test_client:
        yield test_client
