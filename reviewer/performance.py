"""Small, dependency-free reviewer performance telemetry."""
from __future__ import annotations
import json, time
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Performance:
    started: float = field(default_factory=time.perf_counter); timings: dict[str, float] = field(default_factory=dict)
    def measure(self, name: str):
        start=time.perf_counter()
        return lambda: self.timings.__setitem__(name, round(time.perf_counter()-start, 3))
    def write(self, output: Path, **counts: int) -> None:
        data={**self.timings, "total_seconds":round(time.perf_counter()-self.started,3), **counts}
        (output / "performance.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
