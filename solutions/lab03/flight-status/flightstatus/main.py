"""Flight status API.

Settings come from environment variables (twelve-factor style):
  DATABASE_URL  PostgreSQL connection URL. Without it, flights are kept in memory.
  APP_ENV       Environment name, for example dev or production.
  APP_VERSION   Version shown by /version and on the home page.
  GIT_COMMIT    Commit the image was built from.
  SEED_DATA     "true" (default) loads sample flights into an empty store.
"""

import html
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse

from .models import Flight, FlightStatus, StatusUpdate
from .rules import InvalidTransition, apply_update, departures_board, estimated_departure
from .seed import sample_flights
from .store import FlightExists, MemoryStore, PostgresStore, make_store


def create_app(store: MemoryStore | PostgresStore | None = None) -> FastAPI:
    app_env = os.environ.get("APP_ENV", "dev")
    version = os.environ.get("APP_VERSION", "dev")
    commit = os.environ.get("GIT_COMMIT", "unknown")
    seed = os.environ.get("SEED_DATA", "true").lower() == "true"

    if store is None:
        database_url = os.environ.get("DATABASE_URL")
        if app_env == "production" and not database_url:
            raise RuntimeError(
                "APP_ENV is production but DATABASE_URL is not set. "
                "Refusing to start with in-memory storage."
            )
        store = make_store(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.setup()
        if seed and not store.list():
            for flight in sample_flights():
                store.add(flight)
        yield

    app = FastAPI(title="Flight Status API", version=version, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        """Liveness: the process is running and can answer requests."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready(response: Response) -> dict:
        """Readiness: the service can reach its storage."""
        if store.ping():
            return {"status": "ready", "storage": store.kind}
        response.status_code = 503
        return {"status": "not ready", "storage": store.kind}

    @app.get("/version")
    def get_version() -> dict:
        return {"version": version, "commit": commit, "environment": app_env}

    @app.get("/flights")
    def list_flights(origin: str | None = None, status: FlightStatus | None = None) -> list[Flight]:
        flights = store.list()
        if origin:
            flights = [f for f in flights if f.origin == origin.upper()]
        if status:
            flights = [f for f in flights if f.status == status]
        return flights

    @app.get("/flights/{number}")
    def get_flight(number: str) -> Flight:
        flight = store.get(number.upper())
        if flight is None:
            raise HTTPException(status_code=404, detail=f"flight {number} not found")
        return flight

    @app.post("/flights", status_code=201)
    def create_flight(flight: Flight) -> Flight:
        try:
            store.add(flight)
        except FlightExists as exc:
            raise HTTPException(
                status_code=409, detail=f"flight {flight.number} already exists"
            ) from exc
        return flight

    @app.patch("/flights/{number}/status")
    def update_status(number: str, update: StatusUpdate) -> Flight:
        flight = get_flight(number)
        try:
            updated = apply_update(flight, update)
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        store.save(updated)
        return updated

    @app.get("/airports/{code}/departures")
    def departures(code: str) -> list[Flight]:
        """Departures board for one airport."""
        return departures_board(store.list(), code.upper())

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        rows = "".join(
            f"<tr><td>{html.escape(f.number)}</td><td>{f.origin}</td><td>{f.destination}</td>"
            f"<td>{estimated_departure(f):%H:%M} UTC</td><td>{html.escape(f.gate or '')}</td>"
            f"<td>{f.status}</td></tr>"
            for f in store.list()
        )
        return PAGE.format(version=html.escape(version), env=html.escape(app_env), rows=rows)

    return app


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Flight status</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 40px; color: #14263d; }}
table {{ border-collapse: collapse; min-width: 640px; }}
th, td {{ text-align: left; padding: 8px 16px 8px 0; border-bottom: 1px solid #e3e7ea; }}
.meta {{ color: #5c6b7b; }}
</style></head>
<body>
<h1>Flight status</h1>
<p class="meta">Version {version} &middot; environment {env}</p>
<table>
<tr><th>Flight</th><th>From</th><th>To</th><th>Departs</th><th>Gate</th><th>Status</th></tr>
{rows}
</table>
</body></html>
"""

app = create_app()
