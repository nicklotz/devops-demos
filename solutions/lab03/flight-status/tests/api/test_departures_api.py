"""API tests for the departures board endpoint."""


def test_departures_for_ord(client):
    numbers = [f["number"] for f in client.get("/airports/ord/departures").json()]
    assert numbers == ["UA101", "UA202", "UA707"]


def test_delayed_flight_moves_down_the_board(client):
    client.patch("/flights/UA101/status", json={"status": "DELAYED", "delay_minutes": 60})
    numbers = [f["number"] for f in client.get("/airports/ORD/departures").json()]
    assert numbers == ["UA202", "UA101", "UA707"]


def test_departed_flight_leaves_the_board(client):
    client.patch("/flights/UA101/status", json={"status": "BOARDING"})
    client.patch("/flights/UA101/status", json={"status": "DEPARTED"})
    numbers = [f["number"] for f in client.get("/airports/ORD/departures").json()]
    assert "UA101" not in numbers
