# evcs-optima

EVCS Optima (智慧充電站電力管理系統) — Python simulation engine + FastAPI service + Bun/React web UI for an Electric Vehicle Charging Station power management system. Algorithms are designed to be portable to embedded C on real MCU hardware.

## Quick start

```bash
# Install
pip install -r requirements.txt

# Run baselines
PYTHONPATH=. python -m pytest tests/ -q                                # simulation core
PYTHONPATH=.:services/evcs-api python -m pytest services/evcs-api/tests -q   # backend
( cd web/evcs-ui && npx tsc --noEmit )                                 # frontend type check

# Start the web service (FastAPI on :8000)
python -m uvicorn app.main:app --app-dir services/evcs-api --reload --port 8000

# Start the web UI (Vite dev server on :5173, requires the backend above)
( cd web/evcs-ui && bun run dev )
```

Expected baselines (Sprint 2 finalized 2026-05-11):
- `tests/`: **241 passed**
- `services/evcs-api/tests`: **92 passed, 1 xfailed, 2 deselected**
- `web/evcs-ui` tsc: **0 errors**

## Where to look

| For | Read |
|---|---|
| Project guidance for Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| Architectural spec (authoritative, Traditional Chinese) | [`docs/SPEC.md`](docs/SPEC.md) |
| Web service / API spec | [`docs/SPEC-WEB-API.md`](docs/SPEC-WEB-API.md) |
| Web UI spec | [`docs/SPEC-WEB-UI.md`](docs/SPEC-WEB-UI.md) |
| Test spec | [`associate/TEST-SPEC.md`](associate/TEST-SPEC.md) |
| **Sprint 2 final status + vocabulary canonical** | [`outputs/SPRINT2_FINAL_STATUS.md`](outputs/SPRINT2_FINAL_STATUS.md) |
