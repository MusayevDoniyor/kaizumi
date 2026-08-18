from vision.object_detector import DetectorConfig, ObjectDetector


def test_detector_without_model_is_safe_and_exposes_status():
    detector = ObjectDetector(DetectorConfig())

    assert detector.detect(None) == []
    status = detector.status()
    assert status["ready"] is False
    assert status["backend"] == "unavailable"
    assert "No YOLO model" in status["error"]


def test_detector_missing_model_does_not_raise():
    detector = ObjectDetector(DetectorConfig(model_path="models/does-not-exist.pt"))

    assert detector.load() is False
    assert detector.is_ready is False
    assert "not found" in detector.error
