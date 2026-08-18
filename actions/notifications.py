# actions/notifications.py
# Kaizumi — Windows toast notifications + native notifications

import sys

try:
    from winotify import Notification, audio
    _WINOTIFY = True
except ImportError:
    _WINOTIFY = False


def notify(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Show a Windows toast notification.
    params: title (optional), message (required)"""
    params  = parameters or {}
    title   = str(params.get("title", "Kaizumi")).strip() or "Kaizumi"
    message = str(params.get("message", "")).strip()
    if not message:
        return "No notification message provided, sir."

    if _WINOTIFY:
        try:
            note = Notification(
                app_id="Kaizumi",
                title=title,
                msg=message,
                duration="short",
            )
            note.set_audio(audio.Default, loop=False)
            note.show()
            return f"Notification sent: {message[:80]}"
        except Exception as e:
            print(f"[Notify] ⚠️ winotify failed: {e}")

    return "No notification engine available, sir. Run: pip install winotify"