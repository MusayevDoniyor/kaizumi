# actions/translate.py
# Kaizumi — translate any text between languages via Gemini

import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = get_base_dir() / "config" / "api_keys.json"
MODEL = "gemini-2.5-flash"


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def translate_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Translate text to a target language."""
    params = parameters or {}
    text   = str(params.get("text", "")).strip()
    target = str(params.get("to", params.get("target", ""))).strip() or "English"
    source = str(params.get("from", "")).strip()

    if not text:
        return "What text should I translate, sir?"

    prompt = (
        f"Translate the following text into {target}"
        + (f" (it is originally in {source})" if source else " (detect the source language yourself)")
        + ". Output ONLY the translation, nothing else.\n\n"
        f"TEXT:\n{text}"
    )
    from google import genai
    client = genai.Client(api_key=_get_api_key())
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=prompt)
        return (resp.text or "").strip() or "Translation failed, sir."
    except Exception as e:
        return f"Translation failed: {e}"