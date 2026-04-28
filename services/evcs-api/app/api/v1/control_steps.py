"""Control-step routes — FR-14 (Apply and Generate) + FR-15 (player)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.adapters.evcs_core_adapter import (
    AdapterError,
    PrioritiesIncompleteError,
    TargetExceedsCapacityError,
    generate_control_steps,
)
from app.schemas.control_step import ControlStepSequence
from app.schemas.snapshot import VisualSnapshot
from app.services.session_service import SessionStore, get_store

router = APIRouter(prefix="/sessions", tags=["control_steps"])


class StepPlayerView(BaseModel):
    current_step_index: int
    total_steps: int
    snapshot: VisualSnapshot
    description: str


_HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None) or 422


def _adapter_to_http(exc: AdapterError) -> HTTPException:
    return HTTPException(
        status_code=_HTTP_422,
        detail={"errors": [e.model_dump() for e in exc.errors]},
    )


@router.post(
    "/{session_id}/apply-and-generate",
    response_model=ControlStepSequence,
)
def apply_and_generate(
    session_id: str, store: SessionStore = Depends(get_store)
) -> ControlStepSequence:
    """FR-14: produce the Present → Target control-step sequence and store it."""

    s = store.get(session_id)
    if s is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found"
        )

    try:
        seq = generate_control_steps(s.system_config, s.car_ports)
    except (TargetExceedsCapacityError, PrioritiesIncompleteError) as exc:
        raise _adapter_to_http(exc) from exc

    store.set_step_sequence(session_id, seq)
    return seq


@router.get(
    "/{session_id}/control-steps",
    response_model=ControlStepSequence,
)
def get_control_steps(
    session_id: str, store: SessionStore = Depends(get_store)
) -> ControlStepSequence:
    """FR-15: return the stored sequence for the player."""

    s = store.get(session_id)
    if s is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found"
        )
    if s.step_sequence is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id} has no control-step sequence — call apply-and-generate first",
        )
    return s.step_sequence


@router.post(
    "/{session_id}/step",
    response_model=StepPlayerView,
)
def advance_step(
    session_id: str,
    direction: Literal["forward", "back"] = Query("forward"),
    store: SessionStore = Depends(get_store),
) -> StepPlayerView:
    """FR-15 player: advance forward or back, with end-of-sequence wrap.

    - Forward past last step → wraps to step 0 (Initial State).
    - Back past first step (0) → wraps to last step.
    - Forward when no steps exist → stays at 0.
    """

    s = store.get(session_id)
    if s is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found"
        )
    if s.step_sequence is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id} has no control-step sequence — call apply-and-generate first",
        )

    seq = s.step_sequence
    total = seq.total_steps
    idx = s.current_step_index

    if direction == "forward":
        new_idx = 0 if idx >= total else idx + 1
    else:
        new_idx = total if idx <= 0 else idx - 1

    store.set_step_index(session_id, new_idx)

    if new_idx == 0:
        snapshot = seq.initial_state
        description = "Initial State (Present)"
    else:
        step = seq.steps[new_idx - 1]
        snapshot = step.snapshot
        description = step.description

    return StepPlayerView(
        current_step_index=new_idx,
        total_steps=total,
        snapshot=snapshot,
        description=description,
    )
