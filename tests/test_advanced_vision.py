from vision.face_recognition import FaceProfileStore, FaceRecognitionEngine
from vision.multimodal import MultimodalVision


def test_face_profile_store_round_trips_local_embeddings(tmp_path):
    store = FaceProfileStore(tmp_path / "faces.json")
    store.add("Doniyor", [0.1, 0.2, 0.3])
    loaded = FaceProfileStore(tmp_path / "faces.json")
    assert loaded.profiles["Doniyor"].embedding == [0.1, 0.2, 0.3]
    assert loaded.remove("Doniyor") is True


def test_face_recognition_without_optional_backend_is_safe(tmp_path):
    engine = FaceRecognitionEngine(FaceProfileStore(tmp_path / "faces.json"))
    assert engine.identify([0.1, 0.2]) is None
    assert engine.error is not None


def test_multimodal_none_frame_is_safe():
    result = MultimodalVision().ask(None)
    assert isinstance(result, str)
