# actions/system_tray.py
# Kaizumi — background system-tray icon + optional global hotkeys.
# Optional deps: pystray (tray) and keyboard (global hotkeys). Both are
# guarded — missing ones simply disable that feature instead of crashing.

import threading

try:
    import pystray
    from PIL import Image, ImageDraw
    _PYSTRAY = True
except Exception:
    _PYSTRAY = False

try:
    import keyboard
    _KEYBOARD = True
except Exception:
    _KEYBOARD = False

_tray_icon          = None
_tray_thread        = None
_hotkeys_registered = False

DEFAULT_HOTKEYS = {
    "ctrl+alt+m": "toggle_mute",
    "ctrl+alt+w": "toggle_wake",
    "ctrl+alt+h": "hide_show",
    "ctrl+alt+b": "briefing",
    "ctrl+alt+q": "quit",
}


def _build_icon():
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(0, 212, 255, 255))
    draw.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
    draw.arc((9, 9, 55, 55), start=30, end=150, fill=(10, 40, 60, 255), width=4)
    return img


def configure_icon(menu_factory, title: str = "Kaizumi") -> bool:
    """Build a pystray icon with the given menu factory and show it in a thread."""
    global _tray_icon, _tray_thread
    if not _PYSTRAY:
        return False
    if _tray_icon is not None:
        return True
    try:
        icon = pystray.Icon(
            name="Kaizumi",
            icon=_build_icon(),
            title=title,
            menu=menu_factory,
        )
        _tray_icon   = icon
        _tray_thread = threading.Thread(target=icon.run, daemon=True, name="TrayThread")
        _tray_thread.start()
        return True
    except Exception as e:
        print(f"[Tray] ⚠️ {e}")
        return False


def register_hotkeys(callbacks: dict) -> int:
    """Register global hotkeys mapped to callback keys (toggle_mute, etc)."""
    global _hotkeys_registered
    if not _KEYBOARD:
        return 0
    try:
        count = 0
        for hotkey, cb_key in DEFAULT_HOTKEYS.items():
            cb = callbacks.get(cb_key)
            if not cb:
                continue
            keyboard.add_hotkey(hotkey, cb, suppress=False)
            count += 1
        _hotkeys_registered = True
        return count
    except Exception as e:
        print(f"[Tray] ⚠️ Hotkey registration failed: {e}")
        return 0


def stop():
    global _tray_icon, _tray_thread
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon   = None
        _tray_thread = None
    if _KEYBOARD and _hotkeys_registered:
        try:
            keyboard.unhook_all_hotkeys()
            _hotkeys_registered = False
        except Exception:
            pass


def available() -> str:
    parts = []
    parts.append("tray: on" if _PYSTRAY else "tray: off (pip install pystray)")
    parts.append("hotkeys: on" if _KEYBOARD else "hotkeys: off (pip install keyboard)")
    return ", ".join(parts)