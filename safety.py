"""
safety.py — centralized risk classification + confirmation gate.

Single source of truth for:
  * which tools are risky (LOW / MEDIUM / HIGH)
  * whether a specific call (tool + args) requires explicit user confirmation
  * a short human-readable description of what an action will do
  * sanitizing sensitive args before they reach logs / UI / remote bridge

The confirmation gate itself lives in main.py (_execute_tool / _dispatch_tool),
but every decision about risk lives HERE, so a tool can never be gated by
ad-hoc per-tool logic. Extend TOOL_RISK / _ACTION_RISK instead of scattering
checks across the codebase.
"""

from enum import IntEnum


class Risk(IntEnum):
    LOW = 0      # read-only / harmless — never requires confirmation
    MEDIUM = 1   # can change state, but reversible / low impact
    HIGH = 2     # destructive, irreversible, or arbitrary code — MUST confirm


# ── Per-tool base risk ────────────────────────────────────────────────────────
# Default risk for each tool when it has no action-specific override below.
TOOL_RISK = {
    # Read-only / informational
    "web_search":        Risk.LOW,
    "weather_report":    Risk.LOW,
    "system_status":     Risk.LOW,
    "recall_memory":     Risk.LOW,
    "read_pdf":          Risk.LOW,
    "pdf_qa":            Risk.LOW,
    "read_document":     Risk.LOW,
    "document_qa":       Risk.LOW,
    "phone_info":        Risk.LOW,
    "read_notifications": Risk.LOW,
    "monitor_alerts":    Risk.LOW,
    "pc_health":         Risk.LOW,
    "translate":         Risk.LOW,
    "flight_finder":     Risk.LOW,
    "youtube_video":     Risk.LOW,
    "daily_briefing":    Risk.LOW,
    "create_presentation": Risk.LOW,
    "create_spreadsheet": Risk.LOW,
    "google_auth_status": Risk.LOW,

    # Style / memory / personality — local, reversible
    "set_mode":          Risk.LOW,
    "set_voice":         Risk.LOW,
    "set_mood":          Risk.LOW,
    "save_memory":       Risk.LOW,

    # Informational system access
    "screen_process":    Risk.LOW,
    "notify":            Risk.LOW,
    "media_control":     Risk.MEDIUM,

    # State-changing but user-friendly
    "open_app":          Risk.MEDIUM,
    "reminder":          Risk.MEDIUM,
    "schedule":          Risk.MEDIUM,
    "wake_word":         Risk.MEDIUM,
    "clipboard":         Risk.MEDIUM,
    "browser_control":   Risk.MEDIUM,
    "computer_settings": Risk.MEDIUM,
    "computer_control":  Risk.MEDIUM,
    "vision_gesture":    Risk.MEDIUM,
    "vision_click":      Risk.MEDIUM,
    "screen_process":    Risk.LOW,
    "smart_home_control": Risk.MEDIUM,
    "api_add_key":       Risk.MEDIUM,
    "google_auth":       Risk.MEDIUM,

    # Communicate externally
    "send_message":      Risk.MEDIUM,
    "send_sms":          Risk.HIGH,
    "gmail":             Risk.MEDIUM,
    "phone_ring":        Risk.LOW,

    # Arbitrary / destructive
    "cmd_control":       Risk.HIGH,
    "desktop_control":   Risk.HIGH,
    "code_helper":       Risk.MEDIUM,
    "dev_agent":         Risk.MEDIUM,
    "agent_task":        Risk.MEDIUM,
    "file_controller":   Risk.MEDIUM,
    "task_manager":      Risk.MEDIUM,
    "game_updater":      Risk.HIGH,
    "autostart":         Risk.MEDIUM,
    "calendar":          Risk.MEDIUM,
    "drive":             Risk.MEDIUM,
}


# ── Action-specific risk overrides ────────────────────────────────────────────
# (tool_name, action) -> Risk. High-impact / irreversible actions are HIGH.
# `None` as the action key means "any other action" for that tool.
_ACTION_RISK = {
    "file_controller": {
        "delete": Risk.HIGH,
        "move": Risk.HIGH,
        "rename": Risk.MEDIUM,
        "organize": Risk.HIGH,
        "organize_desktop": Risk.HIGH,
        "undo_organize": Risk.MEDIUM,
        "write": Risk.MEDIUM,
        "unzip": Risk.HIGH,
        "zip": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "cmd_control": {
        None: Risk.HIGH,
    },
    "desktop_control": {
        None: Risk.HIGH,
    },
    "gmail": {
        "send": Risk.HIGH,
        "compose": Risk.HIGH,
        "delete": Risk.HIGH,
        None: Risk.LOW,
    },
    "send_sms": {
        None: Risk.HIGH,
    },
    "task_manager": {
        "kill": Risk.HIGH,
        "end": Risk.HIGH,
        "kill_process": Risk.HIGH,
        None: Risk.MEDIUM,
    },
    "autostart": {
        "enable": Risk.MEDIUM,
        "disable": Risk.MEDIUM,
        "add": Risk.MEDIUM,
        "remove": Risk.MEDIUM,
        "delete": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "code_helper": {
        "run": Risk.HIGH,
        "build": Risk.HIGH,
        "screen_debug": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "computer_settings": {
        "wifi_off": Risk.MEDIUM,
        "wifi_on": Risk.MEDIUM,
        "shutdown": Risk.HIGH,
        "restart": Risk.HIGH,
        "sleep": Risk.HIGH,
        "lock": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "calendar": {
        "delete": Risk.MEDIUM,
        "remove": Risk.MEDIUM,
        "cancel": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "drive": {
        "delete": Risk.HIGH,
        "remove": Risk.HIGH,
        None: Risk.MEDIUM,
    },
    "game_updater": {
        "update": Risk.HIGH,
        "close_game": Risk.MEDIUM,
        "quit_game": Risk.MEDIUM,
        None: Risk.HIGH,
    },
}

# Params that may carry the user's explicit "yes" — the model must set this to
# True after the user verbally approves a high-risk action.
CONFIRM_PARAM = "confirm"

# Message returned to the model when a high-risk tool is called WITHOUT the
# user's consent. The model must relay it, wait for an explicit yes, then
# re-invoke the tool with confirm=true.
CONFIRM_MESSAGE = (
    "⛔ This action requires your permission: {desc}. "
    "I must not run it without the user's explicit approval. "
    "Ask the user: 'May I {desc}?' and WAIT for an explicit yes or no. "
    "Only call this tool again with {param}=true after the user says yes."
)


def classify(name: str, args: dict | None) -> Risk:
    """Return the risk level for a concrete tool call (name + args)."""
    args = args or {}
    action = str(args.get("action", "")).lower().strip()
    overrides = _ACTION_RISK.get(name)
    if overrides is not None:
        risk = overrides.get(action, overrides.get(None))
        if risk is not None:
            return risk
    return TOOL_RISK.get(name, Risk.MEDIUM)


def needs_confirmation(name: str, args: dict | None, confirm: bool = False) -> bool:
    """True if this call must not run until the user confirms."""
    if confirm:
        return False
    return classify(name, args) == Risk.HIGH


def describe(name: str, args: dict | None) -> str:
    """Short human-readable description of what an action will do."""
    args = args or {}
    action = str(args.get("action", "")).lower().strip()

    if name == "file_controller":
        target = args.get("name") or args.get("path") or "item"
        verbs = {
            "delete": f"delete {target}",
            "move": f"move {target}",
            "rename": f"rename {target}",
            "write": f"write to {target}",
            "unzip": f"extract archive to {args.get('destination', 'target folder')}",
            "organize": f"organize files in {args.get('scope', 'desktop')}",
            "organize_desktop": "organize desktop files",
        }
        return verbs.get(action, f"{action} {target}")

    if name == "cmd_control":
        cmd = args.get("command") or args.get("cmd") or args.get("text") or ""
        return f"run the command: {cmd[:80]}"

    if name == "desktop_control":
        script = args.get("script") or args.get("code") or args.get("text") or ""
        return f"run this code on the desktop: {script[:80]}"

    if name == "gmail" and action in ("send", "compose"):
        return f"send an email to {args.get('to', args.get('recipient', 'recipient'))}"

    if name == "send_sms":
        return f"send an SMS to {args.get('phone', 'recipient')}"

    if name == "task_manager" and action in ("kill", "end", "kill_process"):
        return f"kill the process {args.get('process', args.get('name', 'unknown'))}"

    if name == "code_helper" and action in ("run", "build"):
        return f"{action} code for {args.get('file_path', args.get('description', 'the task'))}"

    if name in ("game_updater",):
        return f"update the game {args.get('game', '')}"

    if name == "computer_settings" and action in ("shutdown", "restart", "sleep"):
        return f"{action} the computer"

    if name == "drive" and action in ("delete", "remove"):
        return f"delete {args.get('file_id', args.get('name', 'a file'))} from Drive"

    if name == "smart_home_control":
        return f"{action} the {args.get('device', 'smart home device')}"

    # Fallback: tool name + first couple of args
    brief = " ".join(str(v) for v in args.values())[:60]
    return f"{name} ({brief})" if brief else name


# ── Secret redaction for logs / UI / remote ──────────────────────────────────
_SECRET_KEYS = {
    "api_key", "api_key_id", "apikey", "token", "access_token", "auth_token",
    "password", "passwd", "secret", "client_secret", "code", "key",
}


def sanitize(name: str, args: dict | None) -> dict:
    """Return args with sensitive values masked, safe for logging/UI/remote."""
    if not args:
        return {}
    safe = {}
    for k, v in args.items():
        lk = str(k).lower()
        if lk in _SECRET_KEYS or "token" in lk or "key" in lk or "secret" in lk:
            safe[k] = "***"
        elif isinstance(v, dict):
            safe[k] = sanitize(name, v)
        elif isinstance(v, list):
            safe[k] = [sanitize(name, {"i": x})["i"] if isinstance(x, dict) else x for x in v]
        else:
            safe[k] = v
    return safe