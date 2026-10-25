"""Storage for flights.

MemoryStore keeps flights in a dictionary and loses them on restart.
PostgresStore keeps them in a PostgreSQL table. make_store() picks one
from the DATABASE_URL setting.
"""

import psycopg
from psycopg.rows import dict_row

from .models import Flight


class FlightExists(Exception):
    """Raised when a flight with the same number is already stored."""


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._flights: dict[str, Flight] = {}

    def setup(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    def list(self) -> list[Flight]:
        return sorted(self._flights.values(), key=lambda f: f.departure)

    def get(self, number: str) -> Flight | None:
        return self._flights.get(number)

    def add(self, flight: Flight) -> None:
        if flight.number in self._flights:
            raise FlightExists(flight.number)
        self._flights[flight.number] = flight

    def save(self, flight: Flight) -> None:
        self._flights[flight.number] = flight


SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    number        TEXT PRIMARY KEY,
    origin        CHAR(3) NOT NULL,
    destination   CHAR(3) NOT NULL,
    departure     TIMESTAMPTZ NOT NULL,
    status        TEXT NOT NULL,
    gate          TEXT,
    delay_minutes INTEGER NOT NULL DEFAULT 0
)
"""

COLUMNS = "number, origin, destination, departure, status, gate, delay_minutes"


class PostgresStore:
    kind = "postgres"

    def __init__(self, url: str) -> None:
        self.url = url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, connect_timeout=3, row_factory=dict_row)

    def setup(self) -> None:
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def ping(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False

    def list(self) -> list[Flight]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {COLUMNS} FROM flights ORDER BY departure").fetchall()
        return [Flight(**row) for row in rows]

    def get(self, number: str) -> Flight | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM flights WHERE number = %s", (number,)
            ).fetchone()
        return Flight(**row) if row else None

    def add(self, flight: Flight) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    f"INSERT INTO flights ({COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    _values(flight),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise FlightExists(flight.number) from exc

    def save(self, flight: Flight) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE flights SET status = %s, gate = %s, delay_minutes = %s WHERE number = %s",
                (flight.status.value, flight.gate, flight.delay_minutes, flight.number),
            )


def _values(flight: Flight) -> tuple:
    return (
        flight.number,
        flight.origin,
        flight.destination,
        flight.departure,
        flight.status.value,
        flight.gate,
        flight.delay_minutes,
    )


def make_store(database_url: str | None) -> MemoryStore | PostgresStore:
    if database_url:
        return PostgresStore(database_url)
    return MemoryStore()
