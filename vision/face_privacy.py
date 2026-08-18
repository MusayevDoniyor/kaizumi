"""Local face detection and privacy-preserving blur processor."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any

from .vision_events import VisionEvent


@dataclass(slots=True)
class FacePrivacyConfig:
    scale_factor: float = 1.1
    min_neighbors: int = 5
    blur_strength: int = 31
    padding: float = 0.12


class FacePrivacyProcessor:
    """Detect faces with OpenCV Haar cascades and blur them locally."""

    def __init__(self, config: FacePrivacyConfig | None = None):
        self.config = config or FacePrivacyConfig()
        self._classifier = None
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        return self._error

    def _load(self) -> bool:
        if self._classifier is not None:
            return True
        try:
            import cv2
            path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._classifier = cv2.CascadeClassifier(path)
            if self._classifier.empty():
                raise RuntimeError("Haar face cascade could not be loaded")
            return True
        except Exception as exc:
            self._error = f"Face privacy unavailable: {exc}"
            return False

    def detect(self, frame: Any) -> list[VisionEvent]:
        if frame is None or not self._load():
            return []
        try:
            import cv2
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._classifier.detectMultiScale(
                gray, scaleFactor=self.config.scale_factor,
                minNeighbors=self.config.min_neighbors,
            )
            return [VisionEvent(
                type="face_detected", timestamp=time(), label="face",
                confidence=1.0, bbox=(int(x), int(y), int(w), int(h)),
                metadata={"privacy": "blurred"},
            ) for x, y, w, h in faces]
        except Exception as exc:
            self._error = f"Face detection failed: {exc}"
            return []

    def blur(self, frame: Any) -> tuple[Any, list[VisionEvent]]:
        """Return a blurred copy and the corresponding face events."""
        if frame is None:
            return frame, []
        events = self.detect(frame)
        if not events:
            return frame.copy(), events
        try:
            import cv2
            result = frame.copy()
            height, width = result.shape[:2]
            kernel = max(3, int(self.config.blur_strength) | 1)
            for event in events:
                x, y, w, h = event.bbox
                pad_x, pad_y = int(w * self.config.padding), int(h * self.config.padding)
                x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
                x1, y1 = min(width, x + w + pad_x), min(height, y + h + pad_y)
                result[y0:y1, x0:x1] = cv2.GaussianBlur(
                    result[y0:y1, x0:x1], (kernel, kernel), 0
                )
            return result, events
        except Exception as exc:
            self._error = f"Face blur failed: {exc}"
            return frame.copy(), []
