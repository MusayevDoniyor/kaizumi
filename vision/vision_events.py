"""Typed events emitted by Kaizumi vision pipelines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class VisionEvent:
    """A normalized observation that can be consumed by UI or automation."""

    type: str
    source: str = "camera_0"
    timestamp: float = field(default_factory=time)
    label: str = ""
    confidence: float | None = None
    bbox: tuple[int, int, int, int] | None = None
    track_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of the event."""
        value = asdict(self)
        if self.bbox is not None:
            value["bbox"] = list(self.bbox)
        return value
