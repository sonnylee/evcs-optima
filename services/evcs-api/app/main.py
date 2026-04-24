"""FastAPI app factory — Phase 1 foundation (docs/SPEC-WEB-API.md §4 Phase 1)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import constants, health, palette, sessions, snapshot, topology, validation


def create_app() -> FastAPI:
    app = FastAPI(
        title="EVCS Optima API",
        version="0.1.0",
        description=(
            "FastAPI service wrapping the existing EVCS simulation core. "
            "Phase 1 (this release): foundation — /health, /constants, /palette, "
            "session store + validation endpoints."
        ),
    )
    # Dev UI is served by Bun (web/evcs-ui/) on a different origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(constants.router, prefix=prefix)
    app.include_router(palette.router, prefix=prefix)
    app.include_router(validation.router, prefix=prefix)
    app.include_router(sessions.router, prefix=prefix)
    app.include_router(topology.router, prefix=prefix)
    app.include_router(snapshot.router, prefix=prefix)
    return app


app = create_app()
