"""Optional OCR adapter with OpenCV preprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any

from .vision_events import VisionEvent


@dataclass(slots=True)
class OCRConfig:
    languages: str = "eng"
    min_confidence: float = 35.0
    scale: float = 1.5


class OCREngine:
    """Extract text when the optional pytesseract/Tesseract stack is ready."""

    def __init__(self, config: OCRConfig | None = None):
        self.config = config or OCRConfig()
        self._loaded = False
        self._pytesseract = None
        self._error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._pytesseract is not None and self._error is None

    @property
    def error(self) -> str | None:
        return self._error

    def load(self) -> bool:
        if self._loaded:
            return self.is_ready
        self._loaded = True
        try:
            import pytesseract
            self._pytesseract = pytesseract
            # This also checks that the native Tesseract executable is present.
            pytesseract.get_tesseract_version()
            return True
        except Exception as exc:
            self._pytesseract = None
            self._error = f"OCR unavailable: {exc}"
            return False

    def extract(self, frame: Any) -> list[VisionEvent]:
        if frame is None or not self.load():
            return []
        try:
            import cv2
            import numpy as np

            image = frame
            if self.config.scale != 1.0:
                image = cv2.resize(image, None, fx=self.config.scale, fy=self.config.scale,
                                   interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            data = self._pytesseract.image_to_data(
                processed, lang=self.config.languages,
                output_type=self._pytesseract.Output.DICT,
            )
            events: list[VisionEvent] = []
            for i, raw_text in enumerate(data.get("text", [])):
                text = str(raw_text).strip()
                try:
                    confidence = float(data["conf"][i])
                except (ValueError, TypeError, KeyError):
                    confidence = 0.0
                if not text or confidence < self.config.min_confidence:
                    continue
                x, y = int(data["left"][i]), int(data["top"][i])
                w, h = int(data["width"][i]), int(data["height"][i])
                events.append(VisionEvent(
                    type="text_detected", timestamp=time(), label=text,
                    confidence=confidence / 100.0, bbox=(x, y, w, h),
                    metadata={"language": self.config.languages},
                ))
            return events
        except Exception as exc:
            self._error = f"OCR inference failed: {exc}"
            return []


class CodeReader:
    """Read QR codes and OpenCV barcode detections from a frame."""

    def __init__(self):
        self._qr = None
        self._barcode = None

    def read(self, frame: Any) -> list[VisionEvent]:
        if frame is None:
            return []
        try:
            import cv2
            if self._qr is None:
                self._qr = cv2.QRCodeDetector()
            events: list[VisionEvent] = []
            data, points, _ = self._qr.detectAndDecode(frame)
            if data:
                bbox = self._points_bbox(points)
                events.append(VisionEvent(
                    type="qr_detected", timestamp=time(), label=data[:500],
                    confidence=1.0, bbox=bbox,
                ))

            barcode_cls = getattr(cv2, "barcode_BarcodeDetector", None)
            if barcode_cls is not None:
                if self._barcode is None:
                    self._barcode = barcode_cls()
                ok, decoded, types, points = self._barcode.detectAndDecode(frame)
                if ok and decoded:
                    for value, code_type in zip(decoded, types or []):
                        if value:
                            events.append(VisionEvent(
                                type="barcode_detected", timestamp=time(), label=str(value),
                                confidence=1.0,
                                metadata={"format": str(code_type)},
                            ))
            return events
        except Exception:
            return []

    @staticmethod
    def _points_bbox(points):
        if points is None:
            return None
        values = points.reshape(-1, 2)
        x0, y0 = values.min(axis=0)
        x1, y1 = values.max(axis=0)
        return int(x0), int(y0), int(x1 - x0), int(y1 - y0)
