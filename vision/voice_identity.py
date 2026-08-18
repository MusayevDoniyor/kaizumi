"""Optional voice identity profiles with a backend-independent matcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np


class VoiceProfileStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.profiles: dict[str, list[float]] = {}
        try:
            self.profiles = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def add(self, name: str, embedding: Iterable[float]) -> None:
        self.profiles[str(name).strip()] = [float(v) for v in embedding]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.profiles, indent=2), encoding="utf-8")


class VoiceIdentityMatcher:
    def __init__(self, store: VoiceProfileStore, threshold: float = 0.82):
        self.store = store
        self.threshold = threshold

    def identify(self, embedding: Iterable[float]) -> tuple[str | None, float]:
        value = np.asarray(list(embedding), dtype=np.float32)
        best_name, best_score = None, -1.0
        for name, raw in self.store.profiles.items():
            known = np.asarray(raw, dtype=np.float32)
            score = float(np.dot(value, known) / (np.linalg.norm(value) * np.linalg.norm(known) + 1e-8))
            if score > best_score:
                best_name, best_score = name, score
        return (best_name if best_score >= self.threshold else None), best_score
