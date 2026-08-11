# actions/clipboard.py
# Kaizumi — Clipboard Manager (copy, paste, read, history)

import time
import threading
import subprocess
from pathlib import Path

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

_HISTORY_LIMIT = 15
_history: list[str] = []
_history_lock = threading.Lock()


def _clipboard_get() -> str:
    if _PYPERCLIP:
        try:
            return pyperclip.paste()
        except Exception:
            pass
    if _win_clip_get() is not None:
        return _win_clip_get() or ""
    return ""


def _clipboard_set(text: str) -> bool:
    if _PYPERCLIP:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass
    return _win_clip_set(text)


def _win_clip_get() -> str | None:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard(0)
        try:
            if not user32.IsClipboardFormatAvailable(13):
                return ""
            h = user32.GetClipboardData(13)
            if not h:
                return ""
            p = kernel32.GlobalLock(h)
            if not p:
                return ""
            try:
                size = kernel32.GlobalSize(h)
                buf = ctypes.create_string_buffer(size)
                kernel32.memcpy(buf, p, size)
                return buf.value.decode("utf-8", errors="replace")
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def _win_clip_set(text: str) -> bool:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Set-Clipboard -Value '{text.replace(chr(39), chr(39)*2)}'"],
            capture_output=True, timeout=10
        )
        return proc.returncode == 0
    except Exception:
        return False


def _push_history(text: str):
    text = (text or "").strip()
    if not text:
        return
    with _history_lock:
        if text in _history:
            _history.remove(text)
        _history.insert(0, text)
        del _history[_HISTORY_LIMIT:]


def clipboard_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Clipboard operations: get | set | paste | clear | history | copy_last"""
    params = parameters or {}
    action = str(params.get("action", "get")).lower().strip()

    if action in ("get", "read", "what", "current"):
        text = _clipboard_get()
        if not text:
            return "The clipboard is empty, sir."
        return f"Clipboard: {text[:200]}"

    if action in ("set", "copy", "write"):
        text = str(params.get("text", "")).strip()
        if not text:
            return "Nothing to copy, sir."
        if _clipboard_set(text):
            _push_history(text)
            return f"Copied to clipboard: {text[:100]}"
        return "Failed to write to clipboard, sir."

    if action in ("paste", "type"):
        text = _clipboard_get()
        if not text:
            return "Clipboard is empty, nothing to paste, sir."
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
        except Exception:
            from actions.computer_settings import type_text
            type_text(text)
        _push_history(text)
        return f"Pasted from clipboard: {text[:60]}"

    if action in ("clear", "empty", "wipe"):
        if _clipboard_set(""):
            return "Clipboard cleared, sir."
        return "Could not clear clipboard, sir."

    if action in ("history", "recent"):
        with _history_lock:
            if not _history:
                return "No clipboard history yet, sir."
            return "Clipboard history: " + " | ".join(f"'{h[:40]}'" for h in _history[:8])

    if action in ("copy_last", "recall", "paste_last"):
        with _history_lock:
            if not _history:
                return "No clipboard history to recall, sir."
            text = _history[0]
        if _clipboard_set(text):
            return f"Recalled: {text[:100]}"
        return "Could not restore previous clipboard, sir."

    return f"Unknown clipboard action: {action}, sir."
