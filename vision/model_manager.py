"""Local model registry for built-in and custom Roboflow exports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ModelSpec:
    name: str
    path: Path
    task: str
    source: str = "local"


class ModelManager:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def object_detector(self) -> ModelSpec:
        custom = os.getenv("KAIZUMI_YOLO_MODEL", "").strip()
        path = Path(custom) if custom else self.root / "yolo11n.pt"
        return ModelSpec("object-detector", path, "detect", "custom" if custom else "builtin")

    def list_models(self) -> list[ModelSpec]:
        return [self.object_detector()]

    def status(self) -> list[dict]:
        return [
            {"name": spec.name, "task": spec.task, "source": spec.source,
             "path": str(spec.path), "available": spec.path.exists()}
            for spec in self.list_models()
        ]
