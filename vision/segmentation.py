"""Local foreground segmentation and background removal utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SegmentationConfig:
    iterations: int = 5
    margin: float = 0.08
    background_blur: int = 0


class ForegroundSegmenter:
    """Extract a foreground subject with OpenCV GrabCut.

    A detector bbox can be supplied for better results. Without one, a
    centered rectangle is used, which is useful for portraits and webcam
    experiments without requiring another neural model.
    """

    def __init__(self, config: SegmentationConfig | None = None):
        self.config = config or SegmentationConfig()
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        return self._error

    def segment(self, frame: Any, bbox: tuple[int, int, int, int] | None = None):
        if frame is None:
            return None
        try:
            import cv2
            import numpy as np

            height, width = frame.shape[:2]
            if bbox is None:
                margin_x = int(width * self.config.margin)
                margin_y = int(height * self.config.margin)
                rect = (margin_x, margin_y, width - 2 * margin_x, height - 2 * margin_y)
            else:
                x, y, w, h = bbox
                rect = (max(0, int(x)), max(0, int(y)),
                        min(width - int(x), int(w)), min(height - int(y), int(h)))
            if rect[2] <= 1 or rect[3] <= 1:
                raise ValueError("segmentation rectangle is too small")

            mask = np.zeros((height, width), np.uint8)
            bgd_model = np.zeros((1, 65), np.float64)
            fgd_model = np.zeros((1, 65), np.float64)
            cv2.grabCut(frame, mask, rect, bgd_model, fgd_model,
                        self.config.iterations, cv2.GC_INIT_WITH_RECT)
            return np.where(
                (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
            ).astype(np.uint8)
        except Exception as exc:
            self._error = f"Segmentation failed: {exc}"
            return None

    def remove_background(self, frame: Any,
                          bbox: tuple[int, int, int, int] | None = None,
                          transparent: bool = True):
        """Return a foreground image with transparent or blurred background."""
        if frame is None:
            return None
        mask = self.segment(frame, bbox)
        if mask is None:
            return frame.copy()
        try:
            import cv2
            import numpy as np

            if transparent:
                result = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
                result[:, :, 3] = mask
                return result

            result = frame.copy()
            blur_size = self.config.background_blur or 31
            blur_size = max(3, int(blur_size) | 1)
            blurred = cv2.GaussianBlur(result, (blur_size, blur_size), 0)
            foreground = mask > 0
            result[~foreground] = blurred[~foreground]
            return result
        except Exception as exc:
            self._error = f"Background removal failed: {exc}"
            return frame.copy()
