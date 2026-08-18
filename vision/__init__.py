"""Shared computer-vision primitives for Kaizumi."""

from .camera_manager import CameraManager, CameraConfig, FramePacket
from .vision_events import VisionEvent

__all__ = ["CameraManager", "CameraConfig", "FramePacket", "VisionEvent"]
