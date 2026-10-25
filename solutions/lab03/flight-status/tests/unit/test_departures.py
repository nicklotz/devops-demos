"""Unit tests for the departures board."""

from datetime import UTC, datetime

from flightstatus.models import Flight
from flightstatus.models import FlightStatus as S
from flightstatus.rules import departures_board


def flight(number, hour, **changes) -> Flight:
    return Flight(
        number=number,
        origin=changes.pop("origin", "ORD"),
        destination="SFO",
        departure=datetime(2026, 10, 27, hour, 0, tzinfo=UTC),
        **changes,
    )


def test_only_flights_from_the_airport():
    board = departures_board([flight("UA1", 9), flight("UA2", 10, origin="DEN")], "ORD")
    assert [f.number for f in board] == ["UA1"]


def test_finished_flights_are_not_listed():
    flights = [
        flight("UA1", 9, status=S.DEPARTED),
        flight("UA2", 10, status=S.CANCELLED),
        flight("UA3", 11),
    ]
    assert [f.number for f in departures_board(flights, "ORD")] == ["UA3"]


def test_ordered_by_estimated_departure():
    # UA1 is scheduled first, but a 90-minute delay moves it behind UA2.
    flights = [flight("UA1", 9, status=S.DELAYED, delay_minutes=90), flight("UA2", 10)]
    assert [f.number for f in departures_board(flights, "ORD")] == ["UA2", "UA1"]
