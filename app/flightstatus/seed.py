"""Sample flights loaded when the store is empty."""

from datetime import UTC, datetime, timedelta

from .models import Flight, FlightStatus


def sample_flights(now: datetime | None = None) -> list[Flight]:
    """Eight flights between United hubs, departing over the next few hours."""
    base = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)

    def at(hours: float) -> datetime:
        return base + timedelta(hours=hours)

    return [
        Flight(number="UA101", origin="ORD", destination="SFO", departure=at(1), gate="C17"),
        Flight(number="UA202", origin="ORD", destination="EWR", departure=at(1.5), gate="C9"),
        Flight(number="UA303", origin="DEN", destination="IAH", departure=at(2), gate="B44"),
        Flight(number="UA404", origin="SFO", destination="ORD", departure=at(2.5), gate="F12"),
        Flight(
            number="UA505",
            origin="IAH",
            destination="DEN",
            departure=at(3),
            gate="E6",
            status=FlightStatus.DELAYED,
            delay_minutes=40,
        ),
        Flight(number="UA606", origin="EWR", destination="LAX", departure=at(3.5), gate="C120"),
        Flight(number="UA707", origin="ORD", destination="DEN", departure=at(4), gate="B11"),
        Flight(number="UA808", origin="LAX", destination="IAD", departure=at(5), gate="7B"),
    ]
