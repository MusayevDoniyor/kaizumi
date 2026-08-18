from vision.anomaly_monitor import AnomalyConfig, AnomalyMonitor
from vision.vision_events import VisionEvent


def _objects(*labels):
    return [VisionEvent(type="object_detected", label=label) for label in labels]


def test_anomaly_monitor_warms_up_then_detects_change():
    monitor = AnomalyMonitor(AnomalyConfig(warmup_frames=2))
    assert monitor.observe(_objects("person")) == []
    assert monitor.observe(_objects("person")) == []
    events = monitor.observe(_objects("person", "phone"))
    assert len(events) == 1
    assert events[0].type == "anomaly_detected"
