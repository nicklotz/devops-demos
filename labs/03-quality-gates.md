# Lab 03: Quality gates, pull requests and integration tests

In Lab 02 the pipeline checked `main` after each push. When it found a problem, the problem was already on `main`. In this lab you move the checks in front of `main`. You run the integration tests against a real PostgreSQL database, on your machine and in the pipeline, and you add a coverage threshold. You then protect `main` with a branch rule: changes arrive only through pull requests, and a pull request can merge only after the `ci` pipeline passes. Finally you deliver a new feature the way a team would: a branch, tests on your machine, a pull request, a failed check, a fix, a review and a merge.

**Lecture:** L4 Testing and quality gates · **You need:** Lab 02. On a fresh machine, run `~/devops-demos/scripts/catch-up.sh 03` first (see the course README).

## Goals

- Run integration tests against a PostgreSQL container, on your machine and as a background service in the pipeline.
- Measure test coverage, and fail the pipeline when coverage is below a threshold.
- Protect `main` with a branch rule that requires pull requests and a passing `ci` check.
- Deliver a feature through a branch and a pull request, and fix the problems that the checks find.
- Explain which kind of problem each check catches: tests on your machine, the pipeline, the branch rule and the review.

## Before you start

Make sure your local `main` matches the server:

```bash
cd ~/flight-status
git switch main
git pull
git log --oneline -3
```

The `ci` pipeline from Lab 02 exists, with its push trigger, and its last run on `main` is green.

## Part 1: Integration tests on your machine

### 1.1 Start a PostgreSQL container

Unit tests and API tests use the in-memory store. They are fast, but they cannot find problems in the SQL code in `store.py`, such as a wrong column name or a missing unique constraint. Integration tests run the code against a real database.

You start PostgreSQL in a container named `testdb` on the `devops` network, with a test user and password. These credentials exist only in this throwaway container.

```bash
docker run -d --name testdb --network devops \
  -e POSTGRES_USER=flights \
  -e POSTGRES_PASSWORD=flights \
  -e POSTGRES_DB=flights \
  postgres:17-alpine
until docker exec testdb pg_isready -U flights; do sleep 1; done
```

`pg_isready` is PostgreSQL's own readiness check. The loop repeats it every second until the database accepts connections. You should see this line at the end:

```text
/var/run/postgresql:5432 - accepting connections
```

### 1.2 Run only the integration tests

`pytest -m integration` selects the tests that are marked as integration tests. The test container joins the `devops` network, so the tests reach the database by its container name, `testdb`. `DATABASE_URL` tells the tests where the database is and how to log in.

```bash
cd ~/flight-status
docker run --rm --network devops -v "$PWD":/src -w /src \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL=postgresql://flights:flights@testdb:5432/flights \
  python:3.12-slim \
  sh -c "pip install --quiet --root-user-action=ignore -r requirements-dev.txt && pytest -m integration"
```

You should see `6 passed, 44 deselected`. These are the 6 tests that were skipped in Lab 02.

### 1.3 Run all tests and measure coverage

Coverage measures which lines of the application ran during the tests. A line that never ran was not tested. Coverage cannot tell you whether the tests check the right things: a test can run a line without checking its result. Coverage is a lower bound, and it shows you the code that no test touches.

`--cov=flightstatus` measures the application package. `--cov-report=term-missing` prints the numbers of the lines that did not run.

```bash
docker run --rm --network devops -v "$PWD":/src -w /src \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL=postgresql://flights:flights@testdb:5432/flights \
  python:3.12-slim \
  sh -c "pip install --quiet --root-user-action=ignore -r requirements-dev.txt && pytest --cov=flightstatus --cov-report=term-missing"
```

You should see `50 passed` and a table similar to this one:

```text
Name                       Stmts   Miss  Cover   Missing
--------------------------------------------------------
flightstatus/__init__.py       0      0   100%
flightstatus/main.py          76      0   100%
flightstatus/models.py        28      0   100%
flightstatus/rules.py         18      0   100%
flightstatus/seed.py           7      0   100%
flightstatus/store.py         63      1    98%   126
--------------------------------------------------------
TOTAL                        192      1    99%
```

The missing line in `store.py` creates the in-memory store. It does not run when `DATABASE_URL` is set. Run the same command without `DATABASE_URL` and coverage drops, because the PostgreSQL code in `store.py` never runs.

### 1.4 Look at the data the tests left

Integration tests change real data. `psql` is PostgreSQL's command-line client. It is installed in the database container, so you run it there with `docker exec`.

```bash
docker exec testdb psql -U flights -d flights -c "SELECT number, origin, destination, status FROM flights ORDER BY number;"
```

You should see the eight sample flights. The last integration test started the application against this database, and the application loaded its sample data into the empty table.

### 1.5 Remove the database container

The container was only for this test run. `docker rm -f` stops and deletes it.

```bash
docker rm -f testdb
```

## Part 2: A database service in the pipeline

### 2.1 Add a background step

The pipeline needs a database too. A `background` step starts a container that keeps running while the next steps run. Harness makes it reachable under the step's name, so the tests connect to the host `db`. The user name and password in the YAML belong to a database that exists only for the length of one run. Real credentials never go into a pipeline file. Lab 06 covers them.

The new version also adds a coverage threshold. `--cov-fail-under=90` makes pytest end with an error when coverage is below 90%. The pipeline then fails, even when every test passed. The `report` step from Lab 02 is not part of this version.

Replace the content of `.harness/ci.yaml` with:

<!-- file: ~/flight-status/.harness/ci.yaml -->
```yaml
# Continuous integration for flight-status (Lab 03).
# Adds a PostgreSQL service for the integration tests and a coverage threshold.
kind: pipeline
spec:
  stages:
  - name: build
    type: ci
    spec:
      steps:
      - name: db
        type: background
        spec:
          container: postgres:17-alpine
          envs:
            POSTGRES_USER: flights
            POSTGRES_PASSWORD: flights
            POSTGRES_DB: flights
      - name: install
        type: run
        spec:
          container: python:3.12-slim
          script: |
            python -m venv .venv
            . .venv/bin/activate
            pip install --quiet -r requirements-dev.txt
      - name: lint
        type: run
        spec:
          container: python:3.12-slim
          script: |
            . .venv/bin/activate
            ruff check .
            ruff format --check .
      - name: test
        type: run
        spec:
          container: python:3.12-slim
          envs:
            DATABASE_URL: postgresql://flights:flights@db:5432/flights
          script: |
            . .venv/bin/activate
            pytest --cov=flightstatus --cov-report=term-missing --cov-fail-under=90
```

Compare the `test` step with the command you ran in step 1.3. The image, the `DATABASE_URL` and the pytest options are the same. Only the host name differs: `db` instead of `testdb`.

### 2.2 Push the change to main

`main` is not protected yet, so you can still push to it without a pull request. This is the last direct push to `main` in the course.

```bash
cd ~/flight-status
git commit -am "Run integration tests against PostgreSQL and require 90% coverage"
git push
```

<!-- test
h_wait flightops/flight-status ci success
h_log flightops/flight-status ci test | grep -q 'Required test coverage of 90% reached'
-->

The push trigger starts the pipeline. Open the run in Harness and look at:

- The **db** step. It starts first and keeps running while the other steps run.
- The **test** log. It shows `50 passed`, the coverage table and the line `Required test coverage of 90% reached. Total coverage: 99.48%`.

The Harness platform has the same step type, called a Background step, for services such as databases in a Build stage.

## Part 3: Protect main

### 3.1 Create a branch rule

So far the pipeline found problems after they reached `main`. A branch rule moves the check in front of `main`. Every change must then arrive through a pull request, and a pull request can merge only after the `ci` pipeline passes on it. A check that a change must pass before it may continue is called a quality gate.

In the `flight-status` repository, open **Settings**, then **Rules**, and select **New branch rule**. Enter:

- Name: `protect-main`
- Target branches: the default branch (`main`)
- **Require pull request**, which blocks direct pushes
- **Block force push** and **Block branch deletion**
- **Require status checks to pass**, with the check `ci`
- Bypass: leave it empty, and do not allow repository owners or administrators to bypass the rule

Save the rule. The labels can differ a little between Harness versions. What matters is the effect.


<!-- shots:begin -->
<img src="img/03-quality-gates/01-create_branch_rule-1.png" alt="Create the branch rule, step 1 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-2.png" alt="Create the branch rule, step 2 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-3.png" alt="Create the branch rule, step 3 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-4.png" alt="Create the branch rule, step 4 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-5.png" alt="Create the branch rule, step 5 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-6.png" alt="Create the branch rule, step 6 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-7.png" alt="Create the branch rule, step 7 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-8.png" alt="Create the branch rule, step 8 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-9.png" alt="Create the branch rule, step 9 of 10">

<img src="img/03-quality-gates/01-create_branch_rule-10.png" alt="Create the branch rule, step 10 of 10">

<!-- shots:end -->

<!-- ui: create_branch_rule flightops/flight-status protect-main ci -->

<!-- test
h_api GET /api/v1/repos/flightops%2Fflight-status/rules | jq -e '.[] | select(.identifier == "protect-main")' >/dev/null
-->

The status check `ci` is the identifier of your pipeline. Harness reports every pipeline run as a check on the commit that it built.

### 3.2 Try to push to main without a pull request

Test a rule before you rely on it. This push must fail.

<!-- expect-fail -->
```bash
cd ~/flight-status
echo "A direct change" >> README.md
git commit -am "Change main directly"
git push
```

You should see:

```text
remote: Rule "protect-main" violation: Push to branch "main" is not allowed. Please use pull requests.
remote: pre-receive: error: Blocked by protection rules., try --help
To http://localhost:3000/git/flightops/flight-status.git
 ! [remote rejected] main -> main (pre-receive hook declined)
error: failed to push some refs to 'http://localhost:3000/git/flightops/flight-status.git'
```

The rule applies to you too, even though you are the administrator.

### 3.3 Undo the local commit

Your local `main` now has a commit that the server will never accept. `git reset --hard origin/main` moves your branch back to the server's version and discards the commit. Use `reset --hard` only for commits that nobody else has, because it deletes them.

```bash
git reset --hard origin/main
git status --short --branch
```

You should see `## main...origin/main`, without "ahead".

## Part 4: Build a feature on a branch

The feature is a departures board for one airport, at `GET /airports/{code}/departures`. It lists the flights that have not left yet, in the order in which they will leave. A delayed flight moves down the board.

### 4.1 Create a branch

A branch holds work in progress without changing `main`. Teams that use trunk-based development keep branches small and short-lived: one feature, merged within a day or two.

```bash
cd ~/flight-status
git switch -c feature/departures
```

### 4.2 Add the business rule

The ordering rule belongs in `rules.py`, next to the other business rules, so that unit tests can check it without a web server. You add two things:

- `FINISHED`, the statuses after which a flight leaves the board.
- `departures_board()`, which keeps the flights from one airport that are not finished, and sorts them.

Replace the content of `flightstatus/rules.py` with the code below. The new parts are `FINISHED` after `ALLOWED_TRANSITIONS`, and `departures_board()` at the end of the file.

<!-- file: ~/flight-status/flightstatus/rules.py -->
```python
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
    return sorted(upcoming, key=lambda f: f.departure)
```

### 4.3 Add the API endpoint

The endpoint is a thin layer. It reads all flights from the store and passes them to `departures_board()`. Business logic stays out of the endpoint, which keeps it easy to test.

Replace the content of `flightstatus/main.py` with the code below. The new parts are `departures_board` in the import from `.rules`, and the route `/airports/{code}/departures` just before the home page route (`/`).

<!-- file: ~/flight-status/flightstatus/main.py -->
```python
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

    @app.get('/airports/{code}/departures')
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
```

### 4.4 Add the tests

New code needs tests at more than one level:

- The unit tests build their own flights and call `departures_board()` without the web API. `test_ordered_by_estimated_departure` describes the ordering rule: a flight that is scheduled first, but delayed by 90 minutes, moves behind a flight that is scheduled one hour later.
- The API tests send HTTP requests to the new endpoint and check the result against the sample flights. One test delays flight UA101 by 60 minutes and expects it to move behind UA202.

Create `tests/unit/test_departures.py`:

<!-- file: ~/flight-status/tests/unit/test_departures.py -->
```python
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
```

Create `tests/api/test_departures_api.py`:

<!-- file: ~/flight-status/tests/api/test_departures_api.py -->
```python
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
```

### 4.5 Run the tests on your machine

Run the tests before you push. A failure on your machine costs you a few seconds. The same failure in a pull request costs a pipeline run and the attention of a reviewer. Finding problems as early as possible is called "shifting left".

This run is expected to fail:

<!-- expect-fail -->
```bash
cd ~/flight-status
docker run --rm -v "$PWD":/src -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim \
  sh -c "pip install --quiet --root-user-action=ignore -r requirements-dev.txt && pytest"
```

Two tests fail:

```text
FAILED tests/api/test_departures_api.py::test_delayed_flight_moves_down_the_board - AssertionError: assert ['UA101', 'UA202', 'UA707'] == ['UA202', 'UA101', 'UA707']
FAILED tests/unit/test_departures.py::test_ordered_by_estimated_departure - AssertionError: assert ['UA1', 'UA2'] == ['UA2', 'UA1']
2 failed, 48 passed, 6 skipped in 0.83s
```

Read the unit test failure. The board returned `UA1` before `UA2`, but the test expected `UA2` first. UA1 is scheduled first, but its 90-minute delay should move it behind UA2. The API test shows the same problem with the sample flights.

### 4.6 Fix the bug

Look at the last line of `departures_board()`. It sorts with `key=lambda f: f.departure`, which is the scheduled time. The rule says "ordered by estimated departure", and `rules.py` already has a function for that: `estimated_departure()`, which adds the delay to the scheduled time. The `sed` command changes the sort key to that function.

```bash
sed -i 's/key=lambda f: f.departure)/key=estimated_departure)/' flightstatus/rules.py
grep -n 'return sorted' flightstatus/rules.py
```

You should see:

```text
57:    return sorted(upcoming, key=estimated_departure)
```

Run the tests again:

```bash
docker run --rm -v "$PWD":/src -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim \
  sh -c "pip install --quiet --root-user-action=ignore -r requirements-dev.txt && pytest"
```

You should see `50 passed, 6 skipped`.

<!-- test
diff -q flightstatus/rules.py ~/devops-demos/solutions/lab03/flight-status/flightstatus/rules.py
-->

## Part 5: Open a pull request

### 5.1 Commit and push the branch

`git push -u origin feature/departures` creates the branch on the server. Pushing a new branch is the "Branch created" event, so the push trigger from Lab 02 does not start a run. The pull request will.

```bash
cd ~/flight-status
git add .
git commit -m "Add a departures board for each airport"
git push -u origin feature/departures
```

The output ends with a line that suggests creating a pull request for `feature/departures`.

### 5.2 Open the pull request

A pull request asks the team to merge a branch into `main`. It shows the changes, the results of the checks and the review comments in one place.

In Harness, open the `flight-status` repository. Harness shows a banner for the branch you just pushed, with a button to create a pull request. If the banner is not there, open **Pull Requests** and select **New Pull Request**. Choose `feature/departures` as the source branch and `main` as the target branch. Enter the title `Add departures board`, and describe in the description what the change does and how you tested it. Select **Create pull request**.


<!-- shots:begin -->
<img src="img/03-quality-gates/02-open_pr-1.png" alt="Open the pull request, step 1 of 2">

<img src="img/03-quality-gates/02-open_pr-2.png" alt="Open the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: open_pr flightops/flight-status feature/departures main "Add departures board" -->

Creating the pull request starts the `ci` pipeline through the default pull request trigger.

<!-- test
h_wait flightops/flight-status ci failure
h_wait_pr_check flightops/flight-status ci failure
h_log flightops/flight-status ci lint | grep -q 'File would be reformatted'
h_log flightops/flight-status ci lint | grep -q 'flightstatus/main.py'
-->

### 5.3 Read the failed check

Wait until the run finishes, then reload the pull request. The checks section shows `ci` as failed. The merge is blocked, and Harness explains why: "The following status checks are required to be completed successfully: ci".

Open the failed run from the pull request. The **lint** step failed, and **test** was skipped:

```text
All checks passed!
unformatted: File would be reformatted
   --> flightstatus/main.py:102:14
    |
101 |
    -     @app.get('/airports/{code}/departures')
102 +     @app.get("/airports/{code}/departures")
103 |     def departures(code: str) -> list[Flight]:
    |
1 file would be reformatted, 16 files already formatted
```

`All checks passed!` comes from `ruff check`: the code has no lint problems. The rest comes from `ruff format --check`. It names the file and the line, and shows the change it would make: the line with `-` is your code, the line with `+` is the formatted version.

The tests passed on your machine, but you did not run the formatter. The pipeline runs every check on every change, including the checks you forget.


<!-- shots:begin -->
<img src="img/03-quality-gates/03-view_pr-1.png" alt="Open the pull request">

<!-- shots:end -->

<!-- ui: view_pr flightops/flight-status -->

### 5.4 Format the code

Run the formatter in a container. Without `--check`, ruff changes the files. `git diff` then shows what it changed.

```bash
cd ~/flight-status
docker run --rm -v "$PWD":/src -w /src python:3.12-slim \
  sh -c "pip install --quiet --root-user-action=ignore ruff==0.17.2 && ruff format ."
git diff
```

You should see one changed line. The new route uses single quotes, and ruff's style uses double quotes:

```text
-    @app.get('/airports/{code}/departures')
+    @app.get("/airports/{code}/departures")
```

A formatter does not change what the code does. It removes style discussions from code review, and it keeps diffs small, because nobody reformats lines that someone else wrote.

<!-- test
diff -q flightstatus/main.py ~/devops-demos/solutions/lab03/flight-status/flightstatus/main.py
-->

### 5.5 Push the fix

Every push to the branch of an open pull request runs the checks again. This time you see two runs: one for the push (your trigger from Lab 02) and one for the update of the pull request (the default trigger). Both build the same commit.

```bash
git commit -am "Format the departures route"
git push
```

<!-- test
h_wait flightops/flight-status ci success
h_wait_pr_check flightops/flight-status ci success
-->

Reload the pull request when the runs have finished. The `ci` check is green, and the merge button is available.

## Part 6: Review and merge

### 6.1 Review the pull request

A check proves that the code passes the tests and the linter. A review checks what tools cannot: whether this is the right change, whether it is clear, and whether something is missing. Even when you review your own change, read the diff the way a reviewer would.

Open the **Changes** tab of the pull request. Read the diff of `rules.py` and `main.py`. Add a comment on the `FINISHED` line, for example: "DELAYED flights stay on the board, because they have not left yet."


<!-- shots:begin -->
<img src="img/03-quality-gates/04-view_pr-1.png" alt="Open the pull request">

<!-- shots:end -->

<!-- ui: view_pr flightops/flight-status -->

### 6.2 Merge with squash

A squash merge combines the commits of the branch ("Add a departures board for each airport" and "Format the departures route") into one commit on `main`. `main` then has one commit per change, which is easier to read and to revert.

Select **Squash and merge**. Keep the option to delete the source branch, and confirm.


<!-- shots:begin -->
<img src="img/03-quality-gates/05-merge_pr-1.png" alt="Merge the pull request, step 1 of 2">

<img src="img/03-quality-gates/05-merge_pr-2.png" alt="Merge the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: merge_pr flightops/flight-status -->

The merge updates `main`, so the push trigger runs `ci` on `main` once more. The run checks the combination of your change and the latest `main`.

<!-- test
h_wait flightops/flight-status ci success --branch main
-->

### 6.3 Update your local copy

The squash commit exists only on the server so far. `git pull` brings it to your local `main`.

Because of the squash, Git cannot see that your local branch was merged: its two commits are not on `main`, only their combined content. `git branch -D`, with a capital D, deletes the branch anyway. `git fetch --prune` removes the local reference to the deleted server branch.

```bash
cd ~/flight-status
git switch main
git pull
git branch -D feature/departures
git fetch --prune
git log --oneline -3
```

You should see the squash commit at the top, with the pull request number in its message, for example `Add departures board (#1)`.

<!-- test
test -z "$(git status --porcelain)"
grep -q 'def departures_board' flightstatus/rules.py
-->

## Part 7: What each gate caught

Look back at what stopped which problem in this lab:

| Gate | What it caught in this lab |
|---|---|
| Tests on your machine | The sorting bug in `departures_board()`, before anyone else saw it |
| The `ci` check on the pull request | The formatting that you forgot to run |
| The branch rule | Your direct push to `main` |
| The review | Questions that tools cannot answer, such as whether DELAYED flights belong on the board |

Think about these questions:

- The pull request run tested your branch, and the merge started another run on `main`. Why run it again? Consider what happens when someone else merges to `main` while your pull request is open.
- The coverage threshold is 90%. Your new code has tests, so coverage stayed at about 99%. Would deleting the two new test files drop coverage below 90%? What kind of gap does a coverage threshold catch, and what kind does it miss?

## Troubleshooting

- **`Conflict. The container name "/testdb" is already in use`**: A `testdb` container from an earlier attempt still exists. Remove it with `docker rm -f testdb` and run step 1.1 again.
- **The `pg_isready` loop runs for more than a minute**: Read the database log with `docker logs testdb --tail 20`.
- **Integration tests fail with `connection refused` or `could not translate host name`**: The test container needs `--network devops`, and `DATABASE_URL` must use the host name `testdb`.
- **The pipeline's `test` step fails with `database at ... did not become ready`**: The `db` step did not start. Open its log and check the indentation of its `envs` block.
- **`FAIL Required test coverage of 90% not reached`**: New code has no tests, or the integration tests did not run. Check that the `test` step sets `DATABASE_URL`, and read the `Missing` column of the coverage table.
- **The pull request shows no check**: The default pull request trigger may be disabled. Open the pipeline settings, tab Triggers. You can also start a run on the branch with **Run** and the branch `feature/departures`.
- **The merge button stays disabled after the check passed**: Reload the page. If the rule asks for approvals, edit the rule and remove the approval requirement.
- **`error: the branch 'feature/departures' is not fully merged`**: You used `git branch -d`. After a squash merge, use `git branch -D`.
- **Permission denied when you save a file**: A container wrote the file as root. Give the files back to your user with `sudo chown -R $USER: ~/flight-status`.

<!-- runner: stop -->

## Going further (optional)

- **Require a review.** As the administrator, create a second user named `reviewer` in the Harness administration settings (Users). Edit the `protect-main` rule and require one approval. Open a small pull request, for example a README change. Then sign in as `reviewer` in a private browser window and approve it. Does Harness let you approve your own pull request?
- **Test the coverage threshold.** On a new branch, delete `tests/unit/test_departures.py` and `tests/api/test_departures_api.py`, push and open a pull request. Read the coverage in the `test` log. Close the pull request without merging and delete the branch.
- **Check before you push.** Git can run a script before every push. Create `.git/hooks/pre-push` with the lines below and make it executable with `chmod +x .git/hooks/pre-push`. A push now stops when the lint fails, before the pipeline sees it. Hooks are not shared through the repository, so every developer must install them.

  ```text
  #!/bin/sh
  docker run --rm -v "$PWD":/src -w /src python:3.12-slim \
    sh -c "pip install --quiet --root-user-action=ignore ruff==0.17.2 && ruff check . && ruff format --check ."
  ```

## Summary

- Integration tests ran against PostgreSQL, first in a container on your machine and then as a background step in the pipeline. They checked the SQL code that unit tests cannot reach.
- The pipeline now fails when test coverage drops below 90%. Coverage shows which code no test runs, but not whether the tests check the right results.
- The branch rule `protect-main` blocks direct pushes and requires the `ci` check, so problems stop before they reach `main`.
- You delivered a feature through a branch and a pull request. Your local tests found a bug, the pipeline found a formatting problem, and the review covered what tools cannot judge.
- A squash merge kept `main` at one commit per change, and the run after the merge checked the result on `main`.
