"""Runtime/device selection and lightweight performance telemetry."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeConfig:
    device: str = "auto"
    max_fps: int = 30
    detection_interval: int = 1


def select_device(preferred: str = "auto") -> str:
    if preferred and preferred != "auto":
        return preferred
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


class PerformanceMeter:
    def __init__(self):
        self.frames = 0
        self._started = time.perf_counter()

    def tick(self) -> float:
        self.frames += 1
        elapsed = max(0.001, time.perf_counter() - self._started)
        return self.frames / elapsed
