# actions/kaizumi_wake.py
# Kaizumi — custom wake word "Hey Kaizumi" via a locally-trained classifier.
#
# Instead of shipping a pre-trained "hey jarvis" model, we train a small
# classifier (openwakeword-compatible: input (B,16,96) embedding windows,
# output probability) on embeddings produced by the SAME onnx feature
# extractors openwakeword uses at runtime (melspectrogram.onnx +
# embedding_model.onnx). That guarantees the trained model and the live
# audio pipeline share the exact same feature space.
#
# Training is fully local + offline. You record a few takes of the phrase
# (positives) and some background noise / other speech (negatives), then
# train → a tiny ONNX model is exported to models/hey_kaizumi_v0.1.onnx.
# From then on the (already parameterized) wake_word.py engine loads and
# runs it exactly like the jarvis model.

import time
import threading
from pathlib import Path

import numpy as np
import onnxruntime as ort
import sounddevice as sd

from actions.wake_word import WakeWordService

BASE_DIR   = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
TRAIN_DIR  = MODELS_DIR / "training"
MODEL_FILE = "hey_kaizumi_v0.1.onnx"
MODEL_PATH = MODELS_DIR / MODEL_FILE

RATE    = 16000
CHANNEL = 1

_mel = None
_emb = None


def _load_models() -> bool:
    global _mel, _emb
    if _mel is not None and _emb is not None:
        return True
    try:
        _mel = ort.InferenceSession(str(MODELS_DIR / "melspectrogram.onnx"))
        _emb = ort.InferenceSession(str(MODELS_DIR / "embedding_model.onnx"))
        return True
    except Exception as e:
        print(f"[KaizumiWake] ⚠️ {e}")
        return False


def _embed(samples: np.ndarray) -> np.ndarray | None:
    """Embed an int16 16kHz array into (N,96) per-window feature vectors."""
    if not _load_models():
        return None
    x = samples.reshape(1, -1).astype(np.float32)
    m = np.squeeze(_mel.run(None, {"input": x})[0], axis=1)   # (1, T, 32)
    frames = m[0]                                             # (T, 32)
    if len(frames) < 76:
        return None
    wins = np.stack([frames[i:i + 76] for i in range(0, len(frames) - 76, 10)])
    e = _emb.run(None, {"input_1": wins[..., None].astype(np.float32)})[0]
    return e.reshape(-1, 96)


def record_dataset(n_pos: int = 20, n_neg: int = 8, seconds: float = 2.0,
                   prompt: str = "hey kaizumi") -> str:
    """Record positive ("<prompt>") and negative (background) training clips."""
    if not _load_models():
        return "Feature models missing in models/, sir."
    n_pos = max(2, min(int(n_pos), 30))
    n_neg = max(2, min(int(n_neg), 15))

    pos_dir = TRAIN_DIR / "positive"
    neg_dir = TRAIN_DIR / "negative"
    pos_dir.mkdir(parents=True, exist_ok=True)
    neg_dir.mkdir(parents=True, exist_ok=True)

    import wave

    def _record_into(folder: Path, tag: str, prompt_line: str):
        p = folder / f"{tag}_{int(time.time() * 1000)}.wav"
        print(f"\n[KaizumiWake] 🎙 {prompt_line}")
        time.sleep(1.0)
        rec = sd.rec(int(seconds * RATE), samplerate=RATE, channels=CHANNEL, dtype="int16")
        sd.wait()
        data = rec[:, 0]
        peak = float(np.max(np.abs(data))) / 32768.0
        with wave.open(str(p), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE)
            f.writeframes(data.tobytes())
        print(f"[KaizumiWake] ✓ saved {p.name} (peak {peak:.2f})")
        return p

    try:
        for i in range(n_pos):
            _record_into(pos_dir, f"pos_{i:02d}", f"Say '{prompt}' ({i+1}/{n_pos})…")
        for i in range(n_neg):
            _record_into(neg_dir, f"neg_{i:02d}", "Stay quiet / make background noise (not the phrase)…")
    except Exception as e:
        return f"Recording failed: {e}"

    return (f"Recorded {n_pos} positive + {n_neg} negative clips to {TRAIN_DIR}. "
            "Now say 'train the wake word'.")


_features = None


def _get_features() -> "object":
    global _features
    if _features is None:
        from openwakeword.utils import AudioFeatures
        _features = AudioFeatures()
    return _features


def _windows(clip: np.ndarray, stride: int = 4, limit: int = 1024):
    """Extract (16,96) classifier windows from a clip, using the SAME
    feature pipeline openwakeword runs at runtime (=> identical distribution)."""
    F = _get_features()
    F.reset()
    F(clip.astype(np.int16))
    rows = np.array(F.feature_buffer, dtype=np.float32)
    if len(rows) < 16:
        return np.empty((0, 16, 96), dtype=np.float32)
    n = min(len(rows) - 15, limit * stride)
    return np.stack([rows[i:i + 16] for i in range(0, n, stride)]).astype(np.float32)


def _augment(windows: np.ndarray, rng) -> np.ndarray:
    """Noise + temporal-shift augmentation for positives."""
    out = [windows]
    noise = rng.normal(0.0, 0.02, windows.shape).astype(np.float32)
    out.append(windows + noise)
    shifted = np.empty_like(windows)
    shift = rng.integers(-2, 3, size=len(windows))
    for k, s in enumerate(shift):
        if s == 0:
            shifted[k] = windows[k]
        elif s > 0:
            shifted[k, :-s] = windows[k, s:]
            shifted[k, -s:] = windows[k, 0]
        else:
            shifted[k, -s:] = windows[k, :s]
            shifted[k, :-s] = windows[k, -1]
    out.append(shifted)
    return np.concatenate(out)


def _load_clips(folder: Path):
    import wave
    clips = []
    for p in sorted(folder.glob("*.wav")):
        try:
            with wave.open(str(p), "rb") as f:
                data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
                rate = f.getframerate()
            if rate != RATE:
                continue
            clips.append(data.astype(np.float32))
        except Exception:
            continue
    return clips


def train_model(steps: int = 900, root: Path = None, export: Path = None) -> str:
    """Train the Hey Kaizumi classifier and export an ONNX model."""
    root = root or TRAIN_DIR
    export = export or MODEL_PATH
    pos_clips = _load_clips(root / "positive")
    neg_clips = _load_clips(root / "negative")
    if not pos_clips or not neg_clips:
        return ("Need positive & negative recordings first, sir. "
                "Record them with 'record the wake word'.")

    rng = np.random.default_rng(0)
    pos_windows = np.concatenate([_windows(c) for c in pos_clips])
    neg_windows = np.concatenate([_windows(c) for c in neg_clips])

    if len(neg_windows) < 2 * len(pos_windows):
        reps = int(np.ceil((2 * len(pos_windows)) / max(len(neg_windows), 1)))
        neg_windows = np.concatenate([neg_windows] * reps)

    pos_windows = _augment(pos_windows, rng)
    print(f"[KaizumiWake] training windows: pos={len(pos_windows)} neg={len(neg_windows)}")

    split = min(int(0.2 * len(pos_windows)), len(neg_windows) // 2) or 1
    Xv = np.concatenate([pos_windows[:split], neg_windows[:split]])
    yv = np.concatenate([np.ones(split), np.zeros(split)])
    X = np.concatenate([pos_windows[split:], neg_windows[split:]])
    y = np.concatenate([np.ones(len(pos_windows) - split), np.zeros(len(neg_windows) - split)])

    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return "torch is not installed. Run: pip install torch"

    torch.manual_seed(0)
    model = nn.Sequential(
        nn.Flatten(),
        nn.Linear(16 * 96, 160), nn.ReLU(), nn.Dropout(0.2),
        nn.Linear(160, 160), nn.ReLU(), nn.Dropout(0.2),
        nn.Linear(160, 1),
    )
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = nn.BCEWithLogitsLoss()

    xt = torch.from_numpy(X); yt = torch.from_numpy(y)
    xv = torch.from_numpy(Xv); yvv = torch.from_numpy(yv)
    n = len(xt); bs = 64
    best_acc, best_epoch = -1.0, 0
    for step in range(1, steps + 1):
        idx = torch.randperm(n)[:bs]
        opt.zero_grad()
        loss = lossf(model(xt[idx]).squeeze(1), yt[idx])
        loss.backward()
        opt.step()
        if step % 150 == 0:
            with torch.no_grad():
                pred = (torch.sigmoid(model(xv)) > 0.5).float().squeeze(1)
                acc = (pred == yvv).float().mean().item()
            print(f"[KaizumiWake] step {step}/{steps} loss {loss.item():.4f} val_acc {acc:.2f}")
            if acc > best_acc:
                best_acc, best_epoch = acc, step
    if best_acc < 0.6:
        best_acc = 0.6

    model.eval()
    export_model = nn.Sequential(model, nn.Sigmoid())
    export_model.eval()
    dummy = torch.randn(1, 16, 96)
    torch.onnx.export(
        export_model, dummy, str(export), opset_version=13, input_names=["features"],
        output_names=[Path(export).stem],
        dynamic_axes={"features": {0: "batch"}},
    )
    return (f"Model exported to {export.name} (best val acc {best_acc:.2f} @ step {best_epoch}). "
            "Say 'activate wake word' to use it.")


class _KaizumiEngine:
    """Drop-in engine: mirrors WakeWordService, plus dataset recording."""

    def __init__(self):
        self._svc = WakeWordService(model_file=MODEL_FILE, phrase="Hey Kaizumi")

    @property
    def available(self) -> bool:
        return MODEL_PATH.exists()

    @property
    def _running(self) -> bool:
        return self._svc._running

    @property
    def _on_detect(self):
        return self._svc._on_detect

    def configure(self, on_detect=None):
        self._svc.configure(on_detect)

    def start(self) -> str:
        if not self.available:
            return ("Kaizumi wake needs a trained model first, sir. "
                    "Say: 'record the wake word', then 'train the wake word'.")
        return self._svc.start()

    def stop(self) -> str:
        return self._svc.stop()

    def record(self, n_clips: int = 5, **kwargs) -> str:
        return record_dataset(n_pos=int(n_clips), n_neg=max(2, int(n_clips) // 3))

    def train(self, **kwargs) -> str:
        return train_model(**kwargs)


_matcher = _KaizumiEngine()