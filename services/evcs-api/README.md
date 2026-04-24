# EVCS Optima FastAPI Service — Phase 1 (Foundation)

Implements the Phase 1 work package from `docs/SPEC-WEB-API.md` §4:

- `GET /api/v1/health` — liveness probe.
- `GET /api/v1/constants` — publishes FR-08 / FR-10 / FR-11 bounds.
- `GET /api/v1/palette?count=N&cycle=true|false` — REC BD identification colors (FR-01, FR-10).
- `POST /api/v1/validate/module-powers` — parse + validate the `"50, 75, 75, 50"` string (FR-11).
- `POST /api/v1/validate/car-ports` — clamp / round raw Max Required / Present / Target and check priority rules (FR-08, FR-12, FR-13, FR-16).
- `POST /api/v1/validate/system-config` — validate the whole `SystemConfig` shape (FR-10 + FR-11).
- `POST | GET | PATCH | DELETE /api/v1/sessions[/{id}]` — in-memory session store that holds `SystemConfig` + Car Port list (FR-09 / FR-14 / FR-15 foundation).

Snapshot (Phase 2) and control-step (Phase 3) routes are deliberately not exposed yet; the schemas are scaffolded so adapters can fill them in without schema churn.

## Run

From the repo root:

```bash
python3 -m uvicorn app.main:app --app-dir services/evcs-api --reload --port 8000
```

Open http://localhost:8000/docs for Swagger UI.

## Tests

```bash
cd services/evcs-api && python3 -m pytest -q
```
