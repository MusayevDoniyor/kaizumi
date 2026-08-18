"""OpenCV YuNet + SFace local identity verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .face_recognition import FaceProfileStore


class OpenCVFaceVerifier:
    def __init__(self, detector_path: str | Path, recognizer_path: str | Path,
                 store: FaceProfileStore, threshold: float = 0.363):
        self.detector_path = Path(detector_path)
        self.recognizer_path = Path(recognizer_path)
        self.store = store
        self.threshold = threshold
        self._detector = None
        self._recognizer = None
        self._ort_session = None
        self.error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._detector is not None and (self._recognizer is not None or self._ort_session is not None)

    def load(self) -> bool:
        if self.is_ready:
            return True
        if not self.detector_path.exists() or not self.recognizer_path.exists():
            self.error = "YuNet/SFace model files are missing"
            return False
        try:
            import cv2
            self._detector = cv2.FaceDetectorYN.create(
                str(self.detector_path), "", (320, 320), 0.9, 0.3, 5000
            )
            try:
                self._recognizer = cv2.FaceRecognizerSF_create(str(self.recognizer_path), "")
            except Exception:
                import onnxruntime as ort
                self._ort_session = ort.InferenceSession(
                    str(self.recognizer_path), providers=["CPUExecutionProvider"]
                )
            return True
        except Exception as exc:
            self.error = f"OpenCV face verifier unavailable: {exc}"
            self._detector = None
            self._recognizer = None
            self._ort_session = None
            return False

    def _feature(self, frame: Any):
        if frame is None or not self.load():
            return None
        try:
            height, width = frame.shape[:2]
            self._detector.setInputSize((width, height))
            _, faces = self._detector.detect(frame)
            if faces is None or len(faces) == 0:
                self.error = "No face found in camera frame"
                return None
            face = max(faces, key=lambda row: float(row[2] * row[3]))
            if self._recognizer is not None:
                aligned = self._recognizer.alignCrop(frame, face)
                return self._recognizer.feature(aligned)
            # YuNet landmarks: right eye, left eye, nose, right mouth, left mouth.
            landmarks = face[4:14].reshape(5, 2).astype("float32")
            reference = __import__("numpy").array([
                [38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                [41.5493, 92.3655], [70.7299, 92.2041],
            ], dtype="float32")
            import cv2
            transform, _ = cv2.estimateAffinePartial2D(landmarks, reference, method=cv2.LMEDS)
            aligned = cv2.warpAffine(frame, transform, (112, 112))
            rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB).astype("float32")
            input_name = self._ort_session.get_inputs()[0].name
            output = self._ort_session.run(None, {input_name: rgb.transpose(2, 0, 1)[None]})[0]
            return output.reshape(1, -1).astype("float32")
        except Exception as exc:
            self.error = f"Face feature extraction failed: {exc}"
            return None

    def enroll(self, name: str, frame: Any) -> bool:
        feature = self._feature(frame)
        if feature is None:
            return False
        self.store.add(name, feature.flatten().astype(float).tolist())
        return True

    def verify(self, frame: Any, name: str | None = None) -> tuple[bool, str | None, float | None]:
        feature = self._feature(frame)
        if feature is None:
            return False, None, None
        candidates = [name] if name else list(self.store.profiles)
        best_name, best_score = None, -1.0
        import cv2
        for candidate in candidates:
            profile = self.store.profiles.get(candidate)
            if profile is None:
                continue
            import numpy as np
            known = np.asarray(profile.embedding, dtype=np.float32).reshape(1, -1)
            if self._recognizer is not None:
                score = float(self._recognizer.match(feature, known, cv2.FaceRecognizerSF_FR_COSINE))
            else:
                score = float(np.dot(feature.flatten(), known.flatten()) /
                              (np.linalg.norm(feature) * np.linalg.norm(known) + 1e-8))
            if score > best_score:
                best_name, best_score = candidate, score
        return best_score >= self.threshold, best_name, best_score if best_name else None
