# actions/wake_word.py
# Kaizumi — Hands-free "Hey Jarvis" wake word activation
#
# Uses openwakeword (free, local, on-device) to detect the phrase "hey jarvis"
# from the microphone in the background. When detected, Kaizumi un-mutes /
# signals that it's listening without needing keyboard or button presses.

import time
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

try:
    from openwakeword.model import Model
    _OWW_OK = True
except ImportError:
    _OWW_OK = False

try:
    import pyaudio
    _PYAUDIO = True
except ImportError:
    _PYAUDIO = False


BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

RATE       = 16000
CHANNELS   = 1
CHUNK      = 1280    # openwakeword expects 80ms@16k per prediction step
DTYPE      = "int16"
SAMPLE_NUMS = 15     # ~1.2s window of audio fed to the model per decision
DETECT_THRESHOLD = 0.6


class WakeWordService:

    def __init__(self, model_file: str = "hey_jarvis_v0.1.onnx", phrase: str = "Hey Jarvis"):
        self._running    = False
        self._thread     = None
        self._on_detect  = None      # callback invoked on wake word
        self._model      = None
        self._model_path = None
        self._model_file = model_file
        self._phrase     = phrase
        self._lock       = threading.Lock()

    @property
    def available(self) -> bool:
        return _OWW_OK and self._model is not None

    def load(self) -> bool:
        """Load the model so predictions work WITHOUT opening a mic stream.
        Used by the phone bridge, which feeds PCM chunks manually."""
        if self._model is not None:
            return True
        if not _OWW_OK:
            return False
        candidate = str(MODELS_DIR / self._model_file)
        if not Path(candidate).exists():
            return False
        try:
            self._model = Model(wakeword_model_paths=[candidate])
            self._model_path = candidate
            return True
        except Exception as e:
            print(f"[WakeWord] ⚠️ Load failed: {e}")
            return False

    def configure(self, on_detect=None):
        self._on_detect = on_detect

    def start(self) -> str:
        if not _OWW_OK:
            return "openwakeword is not installed. Run: pip install openwakeword"
        if self._running:
            return "Wake word is already listening, sir."

        candidate = str(MODELS_DIR / self._model_file)
        if not Path(candidate).exists():
            return "Wake word model not found in models/. Run the train helper first, sir."

        try:
            self._model = Model(wakeword_model_paths=[candidate])
        except Exception as e:
            return f"Could not load wake word model: {e}"

        self._model_path = candidate
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWordThread")
        self._thread.start()
        return f"Wake word active (Hey {self._phrase}). Say '{self._phrase}' to wake me."

    def stop(self) -> str:
        self._running = False
        if self._thread:
            self._thread = None
        return "Wake word stopped, sir."

    def _loop(self):
        if _PYAUDIO:
            self._loop_pyaudio()
        else:
            self._loop_sounddevice()

    def _loop_sounddevice(self):
        try:
            with sd.InputStream(
                samplerate=RATE, channels=CHANNELS,
                dtype=DTYPE, blocksize=CHUNK,
                callback=self._audio_callback,
            ):
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            print(f"[WakeWord] ❌ {e}")

    def _loop_pyaudio(self):
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK, stream_callback=self._pa_callback,
            )
            stream.start_stream()
            while self._running:
                time.sleep(0.1)
            stream.stop_stream()
            stream.close()
            pa.terminate()
        except Exception as e:
            print(f"[WakeWord] ❌ {e}")

    # stream buffer fed per block
    _audio_buffer = []   # rolling list of np arrays

    def _audio_callback(self, indata, frames, time_info, status):
        if self._running:
            self._feed(indata.copy())

    def _pa_callback(self, in_data, frame_count, time_info, status):
        self._feed(np.frombuffer(in_data, dtype=np.int16).copy())
        return (None, pyaudio.paContinue)

    def _feed(self, block: np.ndarray):
        if self._model is None:
            return
        with self._lock:
            self._audio_buffer.append(block)
            if len(self._audio_buffer) > SAMPLE_NUMS:
                self._audio_buffer.pop(0)
            audio = np.concatenate(self._audio_buffer)
        pred = self._model.predict(audio)
        stem = Path(self._model_file).stem
        keys = {stem, "hey_jarvis"} if stem.startswith("hey_jarvis") else {stem}
        score = max(pred.get(k, 0) for k in keys)
        if score > DETECT_THRESHOLD:
            print(f"[WakeWord] ✓ {self._phrase} detected ({score:.2f})")
            self._trigger()

    def _trigger(self):
        with self._lock:
            self._audio_buffer.clear()
        if self._on_detect:
            try:
                self._on_detect()
            except Exception as e:
                print(f"[WakeWord] ⚠️ callback error: {e}")


_service = WakeWordService()


def _pick_engine():
    """Return the wake-word engine that should be active right now."""
    from actions.kaizumi_wake import _matcher
    try:
        if _matcher.available:
            return "kaizumi", _matcher
    except Exception:
        pass
    return "jarvis", _service


def wake_word(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Control the wake word listener.
    action: start | stop | status | record | reset"""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()

    from actions.kaizumi_wake import _matcher

    if action in ("record", "record_wake_word"):
        n = int(params.get("clips") or params.get("count") or 5)
        return _matcher.record(n_clips=n)
    if action in ("train", "train_wake_word", "train_model"):
        return _matcher.train(
            steps=int(params.get("steps") or params.get("epochs") or 900),
        )

    engine_name, engine = _pick_engine()

    if action == "start":
        if engine is _matcher and not engine._on_detect and _service._on_detect:
            # reuse the callback main.py already wired on the jarvis engine
            engine.configure(on_detect=_service._on_detect)
        return engine.start()
    if action == "stop":
        return engine.stop()
    if action in ("status", "info"):
        state = "active" if engine._running else "inactive"
        if engine_name == "kaizumi":
            return f"Wake word is {state} (Hey Kaizumi). Model: reference loaded."
        avail = "available" if engine.available else "unavailable (install openwakeword)"
        return f"Wake word is {state} (Hey Jarvis). Model: {avail}."
    return f"Unknown wake word action: {action}, sir. Use start | stop | status | record"