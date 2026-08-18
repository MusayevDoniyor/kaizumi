"""Optional YOLO object detection adapter for the shared vision pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any

from .vision_events import VisionEvent


@dataclass(slots=True)
class DetectorConfig:
    model_path: str | Path | None = None
    confidence: float = 0.45
    iou: float = 0.50
    classes: set[str] | None = None
    device: str = "auto"


class ObjectDetector:
    """Run YOLO when an optional model/runtime is available.

    The detector is deliberately lazy: importing Kaizumi never loads a large
    neural model. A missing model or optional ``ultralytics`` package produces
    a readable status instead of breaking the camera or assistant.
    """

    def __init__(self, config: DetectorConfig | None = None):
        self.config = config or DetectorConfig()
        self._model: Any = None
        self._backend = "unavailable"
        self._error: str | None = None
        self._loaded = False
        self._last_events: list[VisionEvent] = []

    @property
    def is_ready(self) -> bool:
        return self._loaded and self._model is not None

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def error(self) -> str | None:
        return self._error

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.is_ready,
            "backend": self._backend,
            "model": str(self.config.model_path or ""),
            "error": self._error,
            "detections": len(self._last_events),
        }

    def load(self) -> bool:
        """Load a configured model, returning False when setup is incomplete."""
        if self._loaded:
            return self.is_ready
        self._loaded = True
        model_path = Path(self.config.model_path) if self.config.model_path else None
        if model_path is None:
            self._error = "No YOLO model configured"
            return False
        if not model_path.exists():
            self._error = f"YOLO model not found: {model_path}"
            return False

        try:
            from ultralytics import YOLO
        except ImportError:
            self._error = "ultralytics is not installed; install it to enable YOLO"
            return False

        try:
            self._model = YOLO(str(model_path))
            self._backend = "ultralytics"
            self._error = None
            return True
        except Exception as exc:
            self._error = f"YOLO model load failed: {exc}"
            self._model = None
            return False

    def detect(self, frame: Any, timestamp: float | None = None) -> list[VisionEvent]:
        """Return normalized events for one BGR/RGB frame."""
        if not self.load() or frame is None:
            self._last_events = []
            return []

        try:
            kwargs = {
                "conf": self.config.confidence,
                "iou": self.config.iou,
                "verbose": False,
            }
            if self.config.device != "auto":
                kwargs["device"] = self.config.device
            result = self._model.predict(frame, **kwargs)[0]
            names = result.names or {}
            events: list[VisionEvent] = []
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                self._last_events = []
                return []
            for box in boxes:
                cls_id = int(box.cls[0].item())
                label = str(names.get(cls_id, cls_id))
                if self.config.classes and label not in self.config.classes:
                    continue
                xyxy = [int(round(value)) for value in box.xyxy[0].tolist()]
                confidence = float(box.conf[0].item())
                events.append(VisionEvent(
                    type="object_detected",
                    timestamp=timestamp if timestamp is not None else time(),
                    label=label,
                    confidence=confidence,
                    bbox=(xyxy[0], xyxy[1], xyxy[2] - xyxy[0], xyxy[3] - xyxy[1]),
                ))
            self._last_events = events
            return events
        except Exception as exc:
            self._error = f"YOLO inference failed: {exc}"
            self._last_events = []
            return []


def default_detector(model_path: str | Path | None = None) -> ObjectDetector:
    """Create a detector with conservative defaults for Kaizumi."""
    return ObjectDetector(DetectorConfig(model_path=model_path))
