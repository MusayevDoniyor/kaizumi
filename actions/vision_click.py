# actions/vision_click.py
# Kaizumi — click anywhere on screen by describing it (vision → coordinates)

import io
import json
import re
import sys
from pathlib import Path

try:
    import mss
    _MSS = True
except ImportError:
    _MSS = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

MODEL = "gemini-2.5-flash"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = get_base_dir() / "config" / "api_keys.json"


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _screenshot_jpeg() -> bytes:
    if not _MSS:
        raise RuntimeError("mss is not installed.")
    with mss.mss() as sct:
        shot      = sct.grab(sct.monitors[1])
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)
    if _PIL:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        img.thumbnail([1280, 1280], Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    return png_bytes


def _find_coordinates(image_bytes: bytes, target: str) -> tuple[int, int] | None:
    from google.genai import types as gtypes
    from google import genai
    client = genai.Client(api_key=_get_api_key())
    prompt = (
        "You are Kaizumi's screen-click module. Find the UI element described "
        "by the user in this screenshot. Return ONLY JSON with the pixel "
        "coordinates of the element's CENTER, in the screenshot's own pixel "
        f"dimensions.\n\nUser wants to click on: \"{target}\"\n\n"
        "Reply with exactly: {\"x\": <int>, \"y\": <int>}"
    )
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=[
                gtypes.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt,
            ],
        )
    except Exception as e:
        raise RuntimeError(f"Vision call failed: {e}")

    text = (resp.text or "").strip()
    match = re.search(r"\{\s*\"x\"\s*:\s*(-?\d+)\s*,\s*\"y\"\s*:\s*(-?\d+)\s*\}",
                      text, re.IGNORECASE)
    if not match:
        raise RuntimeError(f"Could not locate the element: '{target}'.")
    return int(match.group(1)), int(match.group(2))


def vision_click_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Click a UI element on screen by describing it."""
    params = parameters or {}
    target = str(params.get("target", params.get("what", ""))).strip()
    double = str(params.get("click", "")).lower() in ("double", "2", "twice")
    just_report = str(params.get("only_coords", "")).lower() in ("true", "1", "yes")

    if not target:
        return ("Tell me what to click on the screen, sir — e.g. 'the Send "
                "button', 'the search box'.")

    try:
        img  = _screenshot_jpeg()
        x, y = _find_coordinates(img, target)
    except Exception as e:
        return f"Vision click failed: {e}"

    if just_report:
        return f"Found '{target}' at screen coordinates ({x}, {y}), sir."

    try:
        import pyautogui
        if double:
            pyautogui.doubleClick(x, y)
            return f"Double-clicked '{target}' at ({x}, {y}), sir."
        pyautogui.click(x, y)
        return f"Clicked '{target}' at ({x}, {y}), sir."
    except Exception as e:
        return f"Found '{target}' at ({x}, {y}) but the click failed: {e}"
