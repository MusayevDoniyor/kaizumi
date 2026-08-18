from vision.face_recognition import FaceProfileStore
from vision.opencv_face_verifier import OpenCVFaceVerifier


def test_opencv_verifier_loads_bundled_models(tmp_path):
    verifier = OpenCVFaceVerifier(
        "models/face_detection_yunet_2023mar.onnx",
        "models/face_recognition_sface_2021dec.onnx",
        FaceProfileStore(tmp_path / "faces.json"),
    )
    assert verifier.load() is True


def test_opencv_verifier_handles_no_face(tmp_path):
    import numpy as np
    verifier = OpenCVFaceVerifier(
        "models/face_detection_yunet_2023mar.onnx",
        "models/face_recognition_sface_2021dec.onnx",
        FaceProfileStore(tmp_path / "faces.json"),
    )
    assert verifier.verify(np.zeros((80, 80, 3), dtype=np.uint8))[0] is False
