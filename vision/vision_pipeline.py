"""Composable frame pipeline for Kaizumi's vision modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .camera_manager import FramePacket
from .object_detector import ObjectDetector
from .ocr_engine import CodeReader, OCREngine
from .face_privacy import FacePrivacyProcessor
from .vision_events import VisionEvent


@dataclass(slots=True)
class PipelineResult:
    sequence: int
    timestamp: float
    events: list[VisionEvent]


class VisionPipeline:
    """Run enabled detectors on a frame and publish normalized events."""

    def __init__(self, detector: ObjectDetector | None = None,
                 on_event: Callable[[VisionEvent], None] | None = None,
                 ocr: OCREngine | None = None, codes: CodeReader | None = None,
                 privacy: FacePrivacyProcessor | None = None):
        self.detector = detector
        self.ocr = ocr
        self.codes = codes
        self.privacy = privacy
        self.last_frame: Any = None
        self.on_event = on_event
        self.last_result: PipelineResult | None = None

    def process(self, packet: FramePacket) -> PipelineResult:
        frame = packet.frame
        events: list[VisionEvent] = []
        if self.privacy is not None:
            frame, privacy_events = self.privacy.blur(frame)
            events.extend(privacy_events)
        if self.detector is not None:
            events.extend(self.detector.detect(frame, packet.timestamp))
        if self.ocr is not None:
            events.extend(self.ocr.extract(frame))
        if self.codes is not None:
            events.extend(self.codes.read(frame))
        self.last_frame = frame
        result = PipelineResult(packet.sequence, packet.timestamp, events)
        self.last_result = result
        if self.on_event:
            for event in events:
                try:
                    self.on_event(event)
                except Exception:
                    # UI or automation subscribers must not stop inference.
                    pass
        return result
