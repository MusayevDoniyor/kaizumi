"""Lightweight local anomaly monitoring over normalized vision events."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import time
from typing import Iterable

from .vision_events import VisionEvent


@dataclass(slots=True)
class AnomalyConfig:
    warmup_frames: int = 10
    min_count_delta: int = 1


class AnomalyMonitor:
    """Learn a simple normal object profile and emit change events."""

    def __init__(self, config: AnomalyConfig | None = None):
        self.config = config or AnomalyConfig()
        self._frames = 0
        self._profile: Counter[str] = Counter()

    @property
    def ready(self) -> bool:
        return self._frames >= self.config.warmup_frames

    @property
    def profile(self) -> dict[str, int]:
        return dict(self._profile)

    def observe(self, events: Iterable[VisionEvent]) -> list[VisionEvent]:
        counts = Counter(
            event.label for event in events if event.type == "object_detected" and event.label
        )
        self._frames += 1
        if self._frames <= self.config.warmup_frames:
            self._profile.update(counts)
            return []
        baseline = {
            label: round(total / max(1, self.config.warmup_frames))
            for label, total in self._profile.items()
        }
        changed = {
            label: (baseline.get(label, 0), count)
            for label, count in counts.items()
            if abs(count - baseline.get(label, 0)) >= self.config.min_count_delta
        }
        changed.update({
            label: (baseline[label], 0)
            for label in baseline if label not in counts and baseline[label] >= self.config.min_count_delta
        })
        if not changed:
            return []
        return [VisionEvent(
            type="anomaly_detected", timestamp=time(), label="scene_change",
            confidence=1.0, metadata={"changes": changed, "baseline": baseline},
        )]
