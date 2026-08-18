import io
import json
import sys
import time
import cv2
import mss
import mss.tools
from pathlib import Path

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from google import genai

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

IMG_MAX_W = 640
IMG_MAX_H = 360
JPEG_Q    = 55


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _get_camera_index() -> int:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "camera_index" in cfg:
            return int(cfg["camera_index"])
    except Exception:
        pass

    print("[Camera] 🔍 No camera index in config. Auto-detecting...")
    best_index = 0

    for idx in range(6):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue
        for _ in range(5):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.mean() > 5:
            best_index = idx
            print(f"[Camera] ✅ Camera found at index {idx} — saving to config.")
            break
        else:
            print(f"[Camera] ⚠️  Index {idx}: no valid frame.")

    try:
        cfg = {}
        if API_CONFIG_PATH.exists():
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["camera_index"] = best_index
        with open(API_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        print(f"[Camera] 💾 Camera index {best_index} saved to config.")
    except Exception as e:
        print(f"[Camera] ⚠️  Could not save camera index: {e}")

    return best_index


def _to_jpeg(img_bytes: bytes) -> bytes:
    if not _PIL_OK:
        return img_bytes
    img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
    return buf.getvalue()


def _capture_screenshot() -> bytes:
    with mss.mss() as sct:
        shot      = sct.grab(sct.monitors[1])
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)
    return _to_jpeg(png_bytes)


def _capture_camera() -> bytes:
    camera_index = _get_camera_index()
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Camera could not be opened: index {camera_index}")
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError("Could not capture camera frame.")
    if _PIL_OK:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
        return buf.getvalue()
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return buf.tobytes()


def _analyze_image_text(image_bytes: bytes, mime_type: str, user_text: str, model: str = "gemini-2.5-flash") -> str:
    """Synchronous vision: send image + question to Gemini, return the text answer.
    This is the path that feeds vision results BACK into the main conversation."""
    import google.genai.types as gtypes
    client = genai.Client(
        api_key=_get_api_key(),
        http_options={"api_version": "v1beta"}
    )
    prompt = (
        "You are Kaizumi's vision module. Analyze the attached image and answer "
        "the user's question. Be concise, accurate, and address the user as 'sir'. "
        "Max 2-3 short sentences. The main assistant will relay your answer.\n\n"
        f"User's question: {user_text}"
    )
    try:
        resp = client.models.generate_content(
            model=model,
            contents=[
                gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
        )
        text = (resp.text or "").strip()
        if not text:
            return "I looked at the image but couldn't make out an answer, sir."
        return text
    except Exception as e:
        return f"Vision analysis failed: {e}"


def screen_process(
    parameters:     dict,
    response:       str | None = None,
    player=None,
    session_memory=None,
) -> str:
    user_text = (parameters or {}).get("text") or (parameters or {}).get("user_text", "")
    user_text = (user_text or "").strip()
    if not user_text:
        return "No question provided for screen analysis, sir."

    angle = (parameters or {}).get("angle", "screen").lower().strip()
    print(f"[ScreenProcess] angle={angle!r}  text={user_text!r}")

    try:
        if angle == "camera":
            image_bytes = _capture_camera()
            mime_type   = "image/jpeg"
            print("[ScreenProcess] 📷 Camera captured")
        else:
            image_bytes = _capture_screenshot()
            mime_type   = "image/jpeg" if _PIL_OK else "image/png"
            print("[ScreenProcess] 🖥️ Screen captured")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[ScreenProcess] ❌ Capture error: {e}")
        return f"Screen capture failed: {e}"

    print(f"[ScreenProcess] 📦 {len(image_bytes)} bytes → analyzing")
    answer = _analyze_image_text(image_bytes, mime_type, user_text)
    if player:
        player.write_log(f"Kaizumi: {answer}")
    print(f"[ScreenProcess] 💬 {answer}")
    return answer


if __name__ == "__main__":
    print("[TEST] screen_processor.py v9 — image-only analysis")
    print("=" * 50)
    mode    = input("screen / camera (default: screen): ").strip().lower() or "screen"
    request = input("Question (Enter for default): ").strip() or "What do you see? Be brief."

    t0     = time.perf_counter()
    result = screen_process({"angle": mode, "text": request}, player=None)
    print(f"Analyzed — {time.perf_counter()-t0:.3f}s")
    print(f"\n{'✅' if result else '❌'}")
