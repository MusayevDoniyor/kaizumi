from vision.event_store import VisionEventStore
from vision.runtime import PerformanceMeter, select_device
from vision.vision_events import VisionEvent
from vision.voice_identity import VoiceIdentityMatcher, VoiceProfileStore
from vision.workflows import VisionWorkflowRouter


def test_event_store_and_workflow_router(tmp_path):
    store = VisionEventStore(tmp_path / "events.db")
    event = VisionEvent(type="motion_detected", label="motion")
    store.add(event)
    assert store.recent(1)[0]["type"] == "motion_detected"
    seen = []
    router = VisionWorkflowRouter()
    router.on("motion_detected", seen.append)
    router.dispatch(event)
    assert seen == [event]


def test_voice_matcher_and_runtime():
    store = VoiceProfileStore("data/vision/test_voice_profiles.json")
    store.profiles = {"Doniyor": [1.0, 0.0]}
    name, score = VoiceIdentityMatcher(store, threshold=0.8).identify([1.0, 0.0])
    assert name == "Doniyor"
    assert score > 0.99
    assert select_device("cpu") == "cpu"
    assert PerformanceMeter().tick() > 0
