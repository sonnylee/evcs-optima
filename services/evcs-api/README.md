# EVCS Optima FastAPI Service — Phases 1 + 2

Implements `docs/SPEC-WEB-API.md` §4 Phase 1 (Foundation) and Phase 2 (Topology & Visual Snapshot API).

## Phase 1 — Foundation

- `GET /api/v1/health` — liveness probe.
- `GET /api/v1/constants` — publishes FR-08 / FR-10 / FR-11 bounds.
- `GET /api/v1/palette?count=N&cycle=true|false` — REC BD identification colors (FR-01, FR-10).
- `POST /api/v1/validate/module-powers` — parse + validate the `"50, 75, 75, 50"` string (FR-11).
- `POST /api/v1/validate/car-ports` — clamp / round raw Max Required / Present / Target and check priority rules (FR-08, FR-12, FR-13, FR-16).
- `POST /api/v1/validate/system-config` — validate the whole `SystemConfig` shape (FR-10 + FR-11).
- `POST | GET | PATCH | DELETE /api/v1/sessions[/{id}]` — in-memory session store (FR-09 / FR-14 / FR-15 foundation).

## Phase 2 — Topology & Visual Snapshot

- `POST /api/v1/topology/preview` — static layout given a `SystemConfig`: REC BD colors, 25 kW pack slicing per FR-11, output / inter-group / bridge relay ids (FR-01, FR-10, FR-11).
- `POST /api/v1/snapshot/compute` — **stateless** VisualSnapshot given `(SystemConfig, car_ports)`: REC BD live power + status (FR-02), pack coloring (FR-03), relay states (FR-04), car color (FR-05), warnings for oversubscribed capacity.
- `GET /api/v1/sessions/{id}/snapshot` — session-bound snapshot; PATCH the session's `car_ports`, then GET to see the recomputed state (FR-09).

### Allocation rules (Phase 2 preview)

Phase 2 uses a **simple greedy allocator**, not the full EVCS simulation (that arrives in Phase 3 via `EvcsCoreAdapter`). Rules:

1. Sort ports by priority asc (ties → port_id); ports without priority sort after, also by port_id.
2. Each port claims from its **home REC BD** first (port 1 anchors at pack 0, port 2 at last pack — SPEC §5.2 anchor convention).
3. When home is exhausted, walk neighbors with SPEC §2.2 priority: **right > left**, ring wraps when N≥3.
4. Bridge relays close iff a port's consumption crosses the REC BD boundary.
5. Inter-group relays close iff a single port uses packs on both sides of that relay.
6. Pack color = consuming port's **home REC BD color** (FR-03 interpretation: pack shows where power flows *to*).

Control-step generation (FR-14 / FR-15) is Phase 3; its routes are deliberately not exposed yet.

## Run

From the repo root:

```bash
python3 -m uvicorn app.main:app --app-dir services/evcs-api --reload --port 8000
```

Open http://localhost:8000/docs for Swagger UI.

## Tests

```bash
python3 -m pytest services/evcs-api -q
```

