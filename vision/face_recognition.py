"""Opt-in face profiles with an optional local face-recognition backend."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FaceProfile:
    name: str
    embedding: list[float]


class FaceProfileStore:
    """Small JSON-backed profile store; biometric data stays local."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.profiles: dict[str, FaceProfile] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.profiles = {
                name: FaceProfile(name, [float(v) for v in values])
                for name, values in data.items()
            }
        except (FileNotFoundError, ValueError, TypeError, OSError):
            self.profiles = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({name: profile.embedding for name, profile in self.profiles.items()}, indent=2),
            encoding="utf-8",
        )

    def add(self, name: str, embedding: list[float]) -> None:
        clean = str(name).strip()
        if not clean:
            raise ValueError("Face profile name cannot be empty")
        self.profiles[clean] = FaceProfile(clean, [float(v) for v in embedding])
        self.save()

    def remove(self, name: str) -> bool:
        existed = self.profiles.pop(name, None) is not None
        if existed:
            self.save()
        return existed


class FaceRecognitionEngine:
    """Use face_recognition when installed, otherwise expose a safe status."""

    def __init__(self, store: FaceProfileStore):
        self.store = store
        self._backend = None
        self.error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._backend is not None

    def load(self) -> bool:
        if self._backend is not None:
            return True
        try:
            import face_recognition
            self._backend = face_recognition
            self.error = None
            return True
        except ImportError:
            self.error = "face_recognition is not installed; recognition remains disabled"
            return False

    def embedding_from_frame(self, frame: Any) -> list[float] | None:
        if frame is None or not self.load():
            return None
        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            locations = self._backend.face_locations(rgb, model="hog")
            values = self._backend.face_encodings(rgb, locations)
            return values[0].tolist() if values else None
        except Exception as exc:
            self.error = f"Face embedding failed: {exc}"
            return None

    def identify(self, embedding: list[float], tolerance: float = 0.48) -> str | None:
        if not self.load() or not embedding:
            return None
        try:
            import numpy as np
            names = list(self.store.profiles)
            known = [self.store.profiles[name].embedding for name in names]
            matches = self._backend.compare_faces(known, embedding, tolerance=tolerance)
            distances = self._backend.face_distance(known, embedding)
            if not any(matches):
                return None
            return names[int(np.argmin(distances))]
        except Exception as exc:
            self.error = f"Face identification failed: {exc}"
            return None
