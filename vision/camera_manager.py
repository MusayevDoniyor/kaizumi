"""Thread-safe camera capture shared by Kaizumi vision modules."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Any


@dataclass(slots=True)
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    backend: int | None = None


@dataclass(slots=True)
class FramePacket:
    frame: Any
    sequence: int
    timestamp: float


class CameraManager:
    """Own one capture thread and expose only the newest frame.

    Keeping a single newest frame prevents slow CV models from building an
    unbounded queue and ensures the assistant reacts to the current scene.
    OpenCV is imported lazily so unit tests and non-camera commands can run
    without importing the native camera dependency.
    """

    def __init__(self, config: CameraConfig | None = None):
        self.config = config or CameraConfig()
        self._lock = threading.Lock()
        self._latest: FramePacket | None = None
        self._capture = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: str | None = None
        self._sequence = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, on_frame: Callable[[FramePacket], None] | None = None) -> bool:
        """Start capture and wait briefly for the first camera result."""
        if self.is_running:
            return True
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(on_frame,),
            daemon=True,
            name="KaizumiCamera",
        )
        self._thread.start()
        self._ready.wait(timeout=3.0)
        return self.is_running and self._error is None

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._release_capture()

    def latest(self) -> FramePacket | None:
        with self._lock:
            return self._latest

    def _capture_loop(self, on_frame: Callable[[FramePacket], None] | None) -> None:
        try:
            import cv2

            backend = self.config.backend
            if backend is None and hasattr(cv2, "CAP_DSHOW"):
                backend = cv2.CAP_DSHOW
            self._capture = (cv2.VideoCapture(self.config.index, backend)
                             if backend is not None else cv2.VideoCapture(self.config.index))
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            self._capture.set(cv2.CAP_PROP_FPS, self.config.fps)
            if not self._capture.isOpened():
                self._error = f"Camera {self.config.index} could not be opened"
                self._ready.set()
                return

            self._ready.set()
            while not self._stop.is_set():
                ok, frame = self._capture.read()
                if not ok:
                    time.sleep(0.02)
                    continue
                self._sequence += 1
                packet = FramePacket(frame, self._sequence, time.time())
                with self._lock:
                    self._latest = packet
                if on_frame:
                    try:
                        on_frame(packet)
                    except Exception:
                        # A detector must not be able to kill camera capture.
                        pass
        except Exception as exc:
            self._error = str(exc)
            self._ready.set()
        finally:
            self._release_capture()

    def _release_capture(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
