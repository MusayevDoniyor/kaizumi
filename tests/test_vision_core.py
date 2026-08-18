from vision.camera_manager import CameraConfig, CameraManager, FramePacket
from vision.vision_events import VisionEvent


def test_vision_event_serializes_bbox_and_metadata():
    event = VisionEvent(
        type="object_detected",
        label="person",
        confidence=0.93,
        bbox=(1, 2, 30, 40),
        track_id=7,
        metadata={"zone": "desk"},
    )

    value = event.to_dict()
    assert value["bbox"] == [1, 2, 30, 40]
    assert value["track_id"] == 7
    assert value["metadata"]["zone"] == "desk"


def test_camera_manager_starts_stopped_and_has_no_frame():
    manager = CameraManager(CameraConfig(index=99))
    assert not manager.is_running
    assert manager.latest() is None
    manager.stop()
    assert not manager.is_running


def test_frame_packet_keeps_capture_metadata():
    packet = FramePacket(frame="frame", sequence=4, timestamp=123.0)
    assert packet.frame == "frame"
    assert packet.sequence == 4
    assert packet.timestamp == 123.0
