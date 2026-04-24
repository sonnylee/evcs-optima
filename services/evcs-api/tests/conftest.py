"""Shared test fixtures — isolated FastAPI TestClient + session store reset."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.session_service import reset_store_for_tests


@pytest.fixture
def client() -> TestClient:
    reset_store_for_tests()
    # create_app reads the module-level store via the dependency, which we just reset.
    return TestClient(create_app())
