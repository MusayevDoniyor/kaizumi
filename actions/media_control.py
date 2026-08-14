# actions/media_control.py
# Kaizumi — universal media/music control via global media keys
# (works with Spotify, YouTube, YouTube Music, VLC, Windows Media Player, ...)

_MEDIA_KEYS = {
    "play":         "play/pause media",
    "pause":        "play/pause media",
    "toggle":       "play/pause media",
    "play_pause":   "play/pause media",
    "next":         "next track",
    "skip":         "next track",
    "prev":         "prev track",
    "previous":     "prev track",
    "back":         "prev track",
    "volume_up":    "volume up",
    "vol_up":       "volume up",
    "volume_down":  "volume down",
    "vol_down":     "volume down",
    "mute":         "volume mute",
    "unmute":       "volume mute",
}

_HUMAN = {
    "play/pause media": "play/pause",
    "next track": "next track",
    "prev track": "previous track",
    "volume up": "volume up",
    "volume down": "volume down",
    "volume mute": "mute/unmute",
}


def media_control_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Control any playing media: play/pause, next/prev, volume."""
    params = parameters or {}
    action = str(params.get("action", "toggle")).lower().strip()

    key = _MEDIA_KEYS.get(action)
    if not key:
        return ("Unknown media action, sir. Use: play | pause | toggle | next | "
                "prev | volume_up | volume_down | mute.")

    try:
        import keyboard
        keyboard.press_and_release(key)
    except Exception as e:
        return f"Could not press media key: {e}"

    return f"Pressed {_HUMAN.get(key, key)}, sir."
