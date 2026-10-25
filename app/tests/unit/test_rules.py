"""Unit tests: business rules, no web server and no database."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from flightstatus.models import Flight, StatusUpdate
from flightstatus.models import FlightStatus as S
from flightstatus.rules import InvalidTransition, apply_update, can_transition, estimated_departure


def make_flight(**changes) -> Flight:
    data = {
        "number": "UA100",
        "origin": "ORD",
        "destination": "SFO",
        "departure": datetime(2026, 10, 27, 14, 0, tzinfo=UTC),
    }
    data.update(changes)
    return Flight(**data)


@pytest.mark.parametrize(
    "current, new",
    [
        (S.SCHEDULED, S.BOARDING),
        (S.SCHEDULED, S.DELAYED),
        (S.SCHEDULED, S.CANCELLED),
        (S.DELAYED, S.BOARDING),
        (S.BOARDING, S.DEPARTED),
        (S.DEPARTED, S.ARRIVED),
    ],
)
def test_allowed_transitions(current, new):
    assert can_transition(current, new)


@pytest.mark.parametrize(
    "current, new",
    [
        (S.SCHEDULED, S.DEPARTED),
        (S.SCHEDULED, S.ARRIVED),
        (S.BOARDING, S.SCHEDULED),
        (S.DEPARTED, S.CANCELLED),
        (S.ARRIVED, S.DELAYED),
        (S.CANCELLED, S.BOARDING),
    ],
)
def test_forbidden_transitions(current, new):
    assert not can_transition(current, new)


def test_apply_update_changes_status():
    updated = apply_update(make_flight(), StatusUpdate(status=S.BOARDING))
    assert updated.status == S.BOARDING


def test_apply_update_does_not_change_the_original():
    flight = make_flight()
    apply_update(flight, StatusUpdate(status=S.BOARDING))
    assert flight.status == S.SCHEDULED


def test_forbidden_update_raises_with_reason():
    with pytest.raises(InvalidTransition, match="from SCHEDULED to ARRIVED"):
        apply_update(make_flight(), StatusUpdate(status=S.ARRIVED))


def test_delay_needs_minutes():
    with pytest.raises(InvalidTransition, match="delay_minutes"):
        apply_update(make_flight(), StatusUpdate(status=S.DELAYED))


def test_delay_moves_estimated_departure():
    delayed = apply_update(make_flight(), StatusUpdate(status=S.DELAYED, delay_minutes=45))
    assert delayed.delay_minutes == 45
    assert estimated_departure(delayed) == datetime(2026, 10, 27, 14, 45, tzinfo=UTC)


def test_delay_is_kept_when_boarding_starts():
    delayed = make_flight(status=S.DELAYED, delay_minutes=30)
    boarding = apply_update(delayed, StatusUpdate(status=S.BOARDING))
    assert boarding.delay_minutes == 30


def test_origin_and_destination_must_differ():
    with pytest.raises(ValidationError, match="must be different"):
        make_flight(destination="ORD")


@pytest.mark.parametrize("number", ["UA1", "UA1234", "9K42"])
def test_valid_flight_numbers(number):
    assert make_flight(number=number).number == number


@pytest.mark.parametrize("number", ["ua12", "UA12345", "U1", "UA-12"])
def test_invalid_flight_numbers(number):
    with pytest.raises(ValidationError):
        make_flight(number=number)
