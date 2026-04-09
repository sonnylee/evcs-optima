from abc import ABC, abstractmethod
from typing import Any


class SimulationModule(ABC):
    """Base interface for all simulation modules."""

    @abstractmethod
    def step(self, dt: float) -> None:
        ...

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        ...
