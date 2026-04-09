from typing import Any

from simulation.base import SimulationModule


class TimeController(SimulationModule):
    """Heartbeat generator — advances simulation time by dt each step."""

    def __init__(self, dt: float, t_end: float):
        self.dt = dt
        self.t_end = t_end
        self.current_time: float = 0.0
        self.step_index: int = 0

    def tick(self) -> float:
        self.current_time += self.dt
        self.step_index += 1
        return self.current_time

    def is_finished(self) -> bool:
        return self.current_time >= self.t_end

    def step(self, dt: float) -> None:
        self.tick()

    def get_status(self) -> dict[str, Any]:
        return {
            "current_time": round(self.current_time, 6),
            "step_index": self.step_index,
            "dt": self.dt,
            "t_end": self.t_end,
        }
