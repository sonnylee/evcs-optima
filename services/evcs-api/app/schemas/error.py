"""Error & warning payload schemas."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine-readable error code (e.g. 'MAX_REQUIRED_OUT_OF_RANGE').")
    field: Optional[str] = Field(None, description="Dotted path to the offending field (e.g. 'car_ports[2].max_required').")
    message: str = Field(..., description="Human-readable error message.")


class WarningDetail(BaseModel):
    """Non-blocking advisory — e.g. input was clamped or rounded per FR-12."""

    code: str
    field: Optional[str] = None
    message: str
    original_value: Optional[int] = None
    adjusted_value: Optional[int] = None


class ApiError(BaseModel):
    errors: List[ErrorDetail]
