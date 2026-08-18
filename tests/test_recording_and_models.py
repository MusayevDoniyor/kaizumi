from vision.model_manager import ModelManager
from vision.recording import VisionRecorder


def test_model_manager_reports_builtin_model(tmp_path):
    status = ModelManager(tmp_path).status()[0]
    assert status["name"] == "object-detector"
    assert status["task"] == "detect"
    assert status["available"] is False


def test_recorder_default_path_is_in_vision_data(tmp_path):
    path = VisionRecorder.default_path(tmp_path)
    assert path.parent.name == "vision"
    assert path.suffix == ".mp4"
