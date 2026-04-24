"""In-memory session store (FR-09 recompute, FR-14 generate, FR-15 player).

Replaced by TinyDB / persistent store later; the interface below is what
routes & tests rely on, so swapping the backend is a one-file change.
"""
from __future__ import annotations

import threading
import uuid
from typing import Dict, List, Optional

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.control_step import ControlStepSequence
from app.schemas.session import SessionState


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    # --- CRUD ---------------------------------------------------------------

    def create(
        self,
        system_config: SystemConfig,
        car_ports: Optional[List[CarPortInput]] = None,
    ) -> SessionState:
        sid = uuid.uuid4().hex
        state = SessionState(
            session_id=sid,
            system_config=system_config,
            car_ports=list(car_ports or []),
        )
        with self._lock:
            self._sessions[sid] = state
        return state

    def get(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            s = self._sessions.get(session_id)
            return s.model_copy(deep=True) if s else None

    def list_ids(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    # --- mutations ----------------------------------------------------------

    def update(
        self,
        session_id: str,
        *,
        system_config: Optional[SystemConfig] = None,
        car_ports: Optional[List[CarPortInput]] = None,
    ) -> Optional[SessionState]:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return None
            if system_config is not None:
                s.system_config = system_config
            if car_ports is not None:
                s.car_ports = list(car_ports)
            # Any structural change invalidates a stored step sequence (FR-15).
            s.step_sequence = None
            s.current_step_index = 0
            s.mode = "edit"
            return s.model_copy(deep=True)

    def set_step_sequence(
        self, session_id: str, seq: ControlStepSequence
    ) -> Optional[SessionState]:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return None
            s.step_sequence = seq
            s.current_step_index = 0
            s.mode = "player"
            return s.model_copy(deep=True)


# Module-level singleton — FastAPI dependency resolves to this.
_store = SessionStore()


def get_store() -> SessionStore:
    return _store


def reset_store_for_tests() -> None:
    """Only for tests — wipes the in-memory store."""

    global _store
    _store = SessionStore()
