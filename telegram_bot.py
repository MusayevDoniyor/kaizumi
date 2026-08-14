# telegram_bot.py
# Kaizumi — Telegram remote-control bot.
#
# Plain HTTP long-polling (no extra deps). Only the owner's chat_id is allowed.
# Supports text commands and voice messages (transcribed via Gemini).

import io
import json
import sys
import time
from pathlib import Path

try:
    import requests
    _REQUESTS = True
except ImportError:
    _REQUESTS = False

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TRANSCRIBE_MODEL = "gemini-2.5-flash"

_last_update = 0


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def load_config() -> dict:
    path = get_base_dir() / "config" / "api_keys.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def api_call(token: str, method: str, json_data: dict | None = None,
             params: dict | None = None, timeout: int = 40) -> dict | None:
    if not _REQUESTS:
        return None
    url = TELEGRAM_API.format(token=token, method=method)
    try:
        if json_data is not None:
            resp = requests.post(url, json=json_data, timeout=timeout)
        else:
            resp = requests.get(url, params=params, timeout=timeout)
        data = resp.json()
        return data if data.get("ok") else None
    except Exception:
        return None


def get_updates(token: str, offset: int, timeout: int = 30) -> list[dict]:
    """Long-poll for new updates. Returns a list of update dicts."""
    data = api_call(token, "getUpdates",
                    params={"offset": offset, "timeout": timeout,
                            "allowed_updates": ["message"]}, timeout=timeout + 10)
    return (data or {}).get("result") or []


def send_message(token: str, chat_id, text: str) -> bool:
    if not text:
        return False
    chunks = _split_text(text)
    for chunk in chunks:
        api_call(token, "sendMessage",
                 {"chat_id": chat_id, "text": chunk})
    return True


def _split_text(text: str, limit: int = 3800) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts = []
    while text:
        cut = text[:limit]
        if len(text) > limit:
            idx = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("; "))
            if idx > limit // 2:
                cut, text = cut[:idx + 1], text[idx + 1:].lstrip()
            else:
                text = text[limit:]
        else:
            text = ""
        parts.append(cut)
    return parts


def download_file(token: str, file_id: str) -> bytes | None:
    """Download a Telegram file (e.g. a voice message) as bytes."""
    data = api_call(token, "getFile", {"file_id": file_id})
    if not data:
        return None
    path = data.get("result", {}).get("file_path")
    if not path:
        return None
    try:
        resp = requests.get(
            f"https://api.telegram.org/file/bot{token}/{path}", timeout=40)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None


def transcribe_voice(api_key: str, audio_bytes: bytes) -> str:
    """Transcribe a Telegram voice note (ogg/opus) with Gemini."""
    import api_keys
    from google.genai import types
    mime = "audio/ogg"
    try:
        resp = api_keys.generate_with_retry(
            model=TRANSCRIBE_MODEL,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                ("Transcribe this voice message exactly, word for word. "
                 "Output only the transcribed text."),
            ],
        )
    except Exception:
        # fall back to the passed-in key (kept for legacy callers)
        from google import genai
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=TRANSCRIBE_MODEL,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                ("Transcribe this voice message exactly, word for word. "
                 "Output only the transcribed text."),
            ],
        )
    return (resp.text or "").strip()


def ping_bot(token: str) -> bool:
    """Verify the token works."""
    data = api_call(token, "getMe")
    return bool(data and data.get("result"))


def mark_read(token: str, offset: int):
    """Confirm an update offset so Telegram stops re-delivering it."""
    api_call(token, "getUpdates", params={"offset": offset, "timeout": 1})
