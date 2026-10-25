"""Business rules for flight status changes.

A flight moves through a fixed set of states. ALLOWED_TRANSITIONS lists every
permitted change. Any other change is rejected with InvalidTransition.
"""

from datetime import datetime, timedelta

from .models import Flight, FlightStatus, StatusUpdate

S = FlightStatus

ALLOWED_TRANSITIONS: dict[FlightStatus, set[FlightStatus]] = {
    S.SCHEDULED: {S.BOARDING, S.DELAYED, S.CANCELLED},
    S.DELAYED: {S.DELAYED, S.BOARDING, S.CANCELLED},
    S.BOARDING: {S.DEPARTED, S.DELAYED},
    S.DEPARTED: {S.ARRIVED},
    S.ARRIVED: set(),
    S.CANCELLED: set(),
}


# Statuses after which a flight no longer appears on a departures board.
FINISHED = {S.DEPARTED, S.ARRIVED, S.CANCELLED}


class InvalidTransition(ValueError):
    """Raised when a status change breaks the rules."""


def can_transition(current: FlightStatus, new: FlightStatus) -> bool:
    return new in ALLOWED_TRANSITIONS[current]


def apply_update(flight: Flight, update: StatusUpdate) -> Flight:
    """Return a copy of the flight with the update applied, or raise InvalidTransition."""
    if not can_transition(flight.status, update.status):
        raise InvalidTransition(f"cannot change status from {flight.status} to {update.status}")

    delay = flight.delay_minutes
    if update.status == S.DELAYED:
        if not update.delay_minutes:
            raise InvalidTransition("a DELAYED status needs delay_minutes greater than 0")
        delay = update.delay_minutes

    return flight.model_copy(update={"status": update.status, "delay_minutes": delay})


def estimated_departure(flight: Flight) -> datetime:
    """Scheduled departure plus the current delay."""
    return flight.departure + timedelta(minutes=flight.delay_minutes)


def departures_board(flights: list[Flight], airport: str) -> list[Flight]:
    """Flights still to leave an airport, ordered by estimated departure."""
    upcoming = [f for f in flights if f.origin == airport and f.status not in FINISHED]
    return sorted(upcoming, key=estimated_departure)
