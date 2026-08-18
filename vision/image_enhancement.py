"""Optional image enhancement tools with dependency-free OpenCV fallbacks."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SuperResolution:
    def __init__(self, model_path: str | Path | None = None, scale: int = 2):
        self.model_path = Path(model_path) if model_path else None
        self.scale = max(2, int(scale))
        self._engine = None
        self._error: str | None = None

    def upscale(self, frame: Any):
        if frame is None:
            return None
        try:
            import cv2
            if self.model_path and self.model_path.exists() and hasattr(cv2, "dnn_superres"):
                if self._engine is None:
                    self._engine = cv2.dnn_superres.DnnSuperResImpl_create()
                    self._engine.readModel(str(self.model_path))
                    self._engine.setModel("edsr", self.scale)
                return self._engine.upsample(frame)
            return cv2.resize(frame, None, fx=self.scale, fy=self.scale,
                              interpolation=cv2.INTER_CUBIC)
        except Exception as exc:
            self._error = f"Super-resolution failed: {exc}"
            return frame.copy()


class ImageColorizer:
    """Colorize grayscale frames; neural colorization is optional."""

    def __init__(self, model_path: str | Path | None = None):
        self.model_path = Path(model_path) if model_path else None
        self._error: str | None = None

    def colorize(self, frame: Any):
        if frame is None:
            return None
        try:
            import cv2
            if len(frame.shape) == 2:
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            # A trained neural model can be plugged in later. For an already
            # colored image, preserve the source instead of damaging colors.
            return frame.copy()
        except Exception as exc:
            self._error = f"Colorization failed: {exc}"
            return frame.copy()
