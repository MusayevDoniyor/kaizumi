# actions/autostart.py
# Kaizumi — start automatically on Windows login (HKCU Run key)

import sys
import winreg
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
TASK_NAME    = "Kaizumi"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _launch_command(remote: bool) -> str:
    base   = get_base_dir()
    main   = base / "main.py"
    exe    = sys.executable
    pyw = Path(exe).with_name("pythonw.exe")
    if not pyw.exists():
        pyw = Path(exe)
    cmd = f'"{pyw}" -u "{main}"'
    if remote:
        cmd += " --remote"
    return cmd


def _set_run(cmd: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, cmd)


def _del_run() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, TASK_NAME)
        return True
    except FileNotFoundError:
        return False


def _get_run() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, TASK_NAME)
            return value
    except FileNotFoundError:
        return None


def autostart_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Autostart control: status | enable | disable"""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    remote = str(params.get("remote", "true")).lower() in ("true", "1", "yes", "on")

    try:
        if action in ("status", "check"):
            val = _get_run()
            if not val:
                return ("Kaizumi is NOT set to start automatically, sir. Say "
                        "'enable autostart' to start it at every login.")
            return ("Kaizumi will start automatically at login, sir. "
                    f"Command: {val}")

        if action in ("enable", "on", "add"):
            cmd = _launch_command(remote)
            _set_run(cmd)
            suffix = "with the phone bridge (--remote)" if remote else "in local mode"
            return f"Autostart enabled, sir. Kaizumi will launch at login {suffix}."

        if action in ("disable", "off", "remove", "delete"):
            removed = _del_run()
            return ("Autostart disabled, sir. Kaizumi will no longer start at "
                    "login." if removed else
                    "Autostart was already off, sir.")

        return f"Unknown autostart action: {action}. Use status | enable | disable."
    except Exception as e:
        return f"Autostart operation failed: {e}"
