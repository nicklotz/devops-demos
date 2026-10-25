# Flight status API

A small FastAPI service used in the Intermediate DevOps course labs.
It tracks flights and their status, and enforces the allowed status changes.

| Endpoint | Purpose |
|---|---|
| `GET /` | HTML page with all flights and the running version |
| `GET /health` | Liveness check |
| `GET /ready` | Readiness check (can the service reach its storage?) |
| `GET /version` | Version, commit and environment |
| `GET /flights?origin=ORD&status=DELAYED` | List flights, optionally filtered |
| `GET /flights/{number}` | One flight |
| `POST /flights` | Add a flight |
| `PATCH /flights/{number}/status` | Change a flight's status |

Settings are environment variables: `DATABASE_URL`, `APP_ENV`, `APP_VERSION`, `GIT_COMMIT`, `SEED_DATA`.
Without `DATABASE_URL` the service keeps flights in memory.

Tests live in `tests/`:

- `tests/unit`: business rules only
- `tests/api`: HTTP requests against the app with in-memory storage
- `tests/integration`: the PostgreSQL store; skipped unless `DATABASE_URL` is set
