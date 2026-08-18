from vision.camera_manager import FramePacket
from vision.vision_events import VisionEvent
from vision.vision_pipeline import VisionPipeline


class FakeDetector:
    def detect(self, frame, timestamp):
        return [VisionEvent(type="object_detected", label=str(frame), timestamp=timestamp)]


class FakeOCR:
    def extract(self, frame):
        return [VisionEvent(type="text_detected", label="hello")]


def test_pipeline_publishes_detector_events():
    received = []
    pipeline = VisionPipeline(FakeDetector(), received.append)
    result = pipeline.process(FramePacket("laptop", 2, 123.5))

    assert result.sequence == 2
    assert result.events[0].label == "laptop"
    assert received[0].type == "object_detected"


def test_pipeline_without_detectors_still_returns_result():
    result = VisionPipeline().process(FramePacket("frame", 1, 10.0))
    assert result.events == []
    assert result.timestamp == 10.0


def test_pipeline_can_combine_object_and_text_processors():
    result = VisionPipeline(FakeDetector(), ocr=FakeOCR()).process(
        FramePacket("frame", 3, 20.0)
    )
    assert [event.type for event in result.events] == ["object_detected", "text_detected"]
