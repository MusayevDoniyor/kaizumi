"""Privacy-aware local video recording."""

from __future__ import annotations

from pathlib import Path
from time import time
from typing import Any


class VisionRecorder:
    def __init__(self):
        self._writer = None
        self.path: Path | None = None
        self.frames = 0

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    def start(self, path: str | Path, frame_size: tuple[int, int], fps: int = 20) -> Path:
        import cv2
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.stop()
        width, height = frame_size
        self._writer = cv2.VideoWriter(
            str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )
        if not self._writer.isOpened():
            self._writer = None
            raise RuntimeError(f"Could not open video writer: {output}")
        self.path = output
        self.frames = 0
        return output

    def write(self, frame: Any) -> bool:
        if self._writer is None or frame is None:
            return False
        self._writer.write(frame)
        self.frames += 1
        return True

    def stop(self) -> Path | None:
        writer, path = self._writer, self.path
        self._writer = None
        self.path = None
        if writer is not None:
            writer.release()
        return path

    @staticmethod
    def default_path(root: str | Path) -> Path:
        return Path(root) / "data" / "vision" / f"vision_{int(time())}.mp4"
