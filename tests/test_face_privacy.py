import numpy as np

from vision.face_privacy import FacePrivacyProcessor


def test_face_privacy_handles_empty_frame():
    processor = FacePrivacyProcessor()
    result, events = processor.blur(None)
    assert result is None
    assert events == []


def test_face_privacy_returns_same_shape_for_blank_frame():
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    result, events = FacePrivacyProcessor().blur(frame)
    assert result.shape == frame.shape
    assert events == []
