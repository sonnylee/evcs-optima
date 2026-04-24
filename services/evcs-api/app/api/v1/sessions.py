"""POST/GET/PATCH/DELETE /api/v1/sessions — session store endpoints (FR-09, FR-14, FR-15)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.session import SessionCreateRequest, SessionState, SessionUpdateRequest
from app.services.session_service import SessionStore, get_store

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionState, status_code=status.HTTP_201_CREATED)
def create_session(
    req: SessionCreateRequest, store: SessionStore = Depends(get_store)
) -> SessionState:
    return store.create(req.system_config, req.car_ports)


@router.get("", response_model=List[str])
def list_sessions(store: SessionStore = Depends(get_store)) -> List[str]:
    return store.list_ids()


@router.get("/{session_id}", response_model=SessionState)
def get_session(
    session_id: str, store: SessionStore = Depends(get_store)
) -> SessionState:
    s = store.get(session_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found")
    return s


@router.patch("/{session_id}", response_model=SessionState)
def update_session(
    session_id: str,
    req: SessionUpdateRequest,
    store: SessionStore = Depends(get_store),
) -> SessionState:
    s = store.update(
        session_id,
        system_config=req.system_config,
        car_ports=req.car_ports,
    )
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found")
    return s


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, store: SessionStore = Depends(get_store)) -> None:
    if not store.delete(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found")
