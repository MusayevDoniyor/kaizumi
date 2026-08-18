"""Shared computer-vision primitives for Kaizumi."""

from .camera_manager import CameraManager, CameraConfig, FramePacket
from .vision_events import VisionEvent
from .object_detector import DetectorConfig, ObjectDetector, default_detector
from .vision_pipeline import PipelineResult, VisionPipeline
from .ocr_engine import OCRConfig, OCREngine, CodeReader
from .face_privacy import FacePrivacyConfig, FacePrivacyProcessor
from .segmentation import SegmentationConfig, ForegroundSegmenter
from .understanding import SceneCaptioner, VisualQuestionAnswering
from .anomaly_monitor import AnomalyConfig, AnomalyMonitor
from .image_enhancement import SuperResolution, ImageColorizer
from .face_recognition import FaceProfile, FaceProfileStore, FaceRecognitionEngine
from .multimodal import MultimodalVision
from .recording import VisionRecorder
from .model_manager import ModelManager, ModelSpec

__all__ = [
    "CameraManager", "CameraConfig", "FramePacket", "VisionEvent",
    "DetectorConfig", "ObjectDetector", "default_detector",
    "PipelineResult", "VisionPipeline",
    "OCRConfig", "OCREngine", "CodeReader",
    "FacePrivacyConfig", "FacePrivacyProcessor",
    "SegmentationConfig", "ForegroundSegmenter",
    "SceneCaptioner", "VisualQuestionAnswering",
    "AnomalyConfig", "AnomalyMonitor",
    "SuperResolution", "ImageColorizer",
    "FaceProfile", "FaceProfileStore", "FaceRecognitionEngine",
    "MultimodalVision",
    "VisionRecorder", "ModelManager", "ModelSpec",
]
