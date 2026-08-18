"""Composable frame pipeline for Kaizumi's vision modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .camera_manager import FramePacket
from .object_detector import ObjectDetector
from .vision_events import VisionEvent


@dataclass(slots=True)
class PipelineResult:
    sequence: int
    timestamp: float
    events: list[VisionEvent]


class VisionPipeline:
    """Run enabled detectors on a frame and publish normalized events."""

    def __init__(self, detector: ObjectDetector | None = None,
                 on_event: Callable[[VisionEvent], None] | None = None):
        self.detector = detector
        self.on_event = on_event
        self.last_result: PipelineResult | None = None

    def process(self, packet: FramePacket) -> PipelineResult:
        events: list[VisionEvent] = []
        if self.detector is not None:
            events.extend(self.detector.detect(packet.frame, packet.timestamp))
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
