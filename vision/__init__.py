"""Shared computer-vision primitives for Kaizumi."""

from .camera_manager import CameraManager, CameraConfig, FramePacket
from .vision_events import VisionEvent
from .object_detector import DetectorConfig, ObjectDetector, default_detector
from .vision_pipeline import PipelineResult, VisionPipeline

__all__ = [
    "CameraManager", "CameraConfig", "FramePacket", "VisionEvent",
    "DetectorConfig", "ObjectDetector", "default_detector",
    "PipelineResult", "VisionPipeline",
]
