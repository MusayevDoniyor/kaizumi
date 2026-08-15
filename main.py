import asyncio
import threading
import json
import sys
import os
import time
import traceback
from pathlib import Path

from logger import setup_logger, log, log_tool

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


try:
    import sounddevice as sd
except ModuleNotFoundError:
    sd = None

try:
    from google import genai
    from google.genai import types
except ModuleNotFoundError:
    genai = None
    types = None

from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)
from agent.resilience import ToolResult, run_sync_tool
from agent.loop_guard import LoopGuard

from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.cmd_control       import cmd_control
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_status     import system_status
from actions.task_manager      import task_manager
from actions.clipboard         import clipboard_action
from actions.vision_gesture    import vision_gesture
from actions.daily_briefing    import daily_briefing
from actions.notifications     import notify
from actions.wake_word         import _service as wake_service
from actions.gmail             import gmail_action
from actions.pdf_reader        import read_pdf as read_pdf_action, pdf_qa
from actions.autostart         import autostart_action
from actions.vision_click      import vision_click_action
from actions.document_qa       import read_document as read_document_action, document_qa as document_qa_action
from actions.monitor           import monitor_action, check_rules as check_monitor_rules, check_email_watch, email_watch_action
from actions.guardian          import guardian_action, check_guardian, battery_health
from actions.translate         import translate_action
from actions.media_control     import media_control_action
from actions.calendar          import calendar_action
from actions.drive             import drive_action


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-3.1-flash-live-preview"
THINKING_LEVEL      = "low"  # Gemini 3.1 thinking depth: minimal | low | medium | high
TG_MODEL            = "gemini-2.5-flash"

TG_HELP_TEXT = (
    "🤖 <b>Kaizumi — Telegram remote control</b>\n"
    "Yozing, men bajaraman. Misollar:\n"
    "• <code>notepadni och</code>\n"
    "• <code>Toshkent ob-havosi</code>\n"
    "• <code>CPU qancha</code>\n"
    "• <code>menga eslatma qo'y 10 daqiqadan keyin</code>\n"
    "• <code>clipboard'ni ko'rsat</code>\n"
    "• <code>yangi email bormi</code> / <code>email yubor ...</code>\n"
    "• <code>kalendarimni ko'rsat</code> / <code>ertaga 15:00 da uchrashuv qo'y</code>\n"
    "• <code>google_auth</code> (Google ulash) / <code>google tekshir</code>\n\n"
    "🎤 Ovozli xabar yuborsangiz ham tushunaman.\n"
    "⚡ Tezkor tugmalar va <code>/status</code>, <code>/mute</code>, "
    "<code>/unmute</code>, <code>/mode</code>, <code>/voice</code>, "
    "<code>/screenshot</code>, <code>/help</code>."
)

TG_QUICK_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "🔍 Status", "callback_data": "/status"},
            {"text": "🔇 Mute",  "callback_data": "/mute"},
            {"text": "🔊 Unmute", "callback_data": "/unmute"},
        ],
        [
            {"text": "🧭 Mode", "callback_data": "/mode"},
            {"text": "🗣 Voice", "callback_data": "/voice"},
        ],
        [
            {"text": "📸 Screenshot", "callback_data": "/screenshot"},
            {"text": "❓ Help", "callback_data": "/help"},
        ],
    ]
}

TG_MODE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "😐 Normal",   "callback_data": "/mode normal"},
            {"text": "💕 Girlfriend", "callback_data": "/mode girlfriend"},
        ],
        [
            {"text": "🤪 Crazy Friend", "callback_data": "/mode crazy_friend"},
            {"text": "🎩 Butler",       "callback_data": "/mode butler"},
        ],
        [
            {"text": "🤝 Friend",  "callback_data": "/mode friend"},
            {"text": "😎 Casual",  "callback_data": "/mode casual"},
        ],
    ]
}

TG_VOICE_KEYBOARD = None  # built after VOICE_NAMES is defined below


def _take_screenshot_bytes() -> bytes | None:
    """Capture the whole screen as PNG bytes (for /screenshot)."""
    try:
        import io
        import pyautogui
        buf = io.BytesIO()
        pyautogui.screenshot().save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

PHASE_IDLE, PHASE_LISTENING, PHASE_THINKING, PHASE_SPEAKING = (
    "idle", "listening", "thinking", "speaking"
)
MAX_ROLLING_CHARS = 16000


def _ensure_audio_deps():
    if sd is not None:
        return True
    return False


def _ensure_core_deps():
    missing = []
    if sd is None:
        missing.append("sounddevice")
    if genai is None or types is None:
        missing.append("google-genai")

    if not missing:
        return

    missing_str = ", ".join(missing)
    msg = (
        f"\nMissing dependencies: {missing_str}\n\n"
        "Install dependencies for this project:\n"
        f"  {sys.executable} -m pip install -r requirements.txt\n\n"
        "Tip: On Windows, make sure you install into the SAME Python you run.\n"
    )
    raise SystemExit(msg)


def _normalize_mode(text) -> str:
    """Map user wording to a canonical mode id, or '' if unknown."""
    m = (str(text or "").strip().lower()
         .replace("-", " ").replace("_", " "))
    aliases = {
        "normal": "normal", "default": "normal", "standard": "normal",
        "regular": "normal", "profonal": "normal", "professional": "normal",
        "romantic": "girlfriend", "romantic girlfriend": "girlfriend",
        "girlfriend": "girlfriend", "girl": "girlfriend",
        "crazy friend": "crazy_friend", "crazy_friend": "crazy_friend",
        "crazy": "crazy_friend", "funny friend": "crazy_friend",
        "friend": "friend", "friendly": "friend",
        "butler": "butler", "batman's butler": "butler", "butler mode": "butler",
        "alfred": "butler", "servant": "butler",
        "casual": "casual", "chill": "casual",
    }
    m = aliases.get(m, m)
    valid = {"normal", "girlfriend", "crazy_friend", "butler", "friend", "casual"}
    return m if m in valid else ""


VOICES = {
    "Achernar":      "mayin (Soft)",
    "Achird":        "do'stona (Friendly)",
    "Algenib":       "bo'g'iq (Gravelly)",
    "Algieba":       "silliq (Smooth)",
    "Alnilam":       "qat'iy (Firm)",
    "Aoede":         "engil ayol (Breezy)",
    "Autonoe":       "yorqin (Bright)",
    "Callirrhoe":    "erkin (Easy-going)",
    "Charon":        "chuqur erkak (Informative)",
    "Despina":       "silliq (Smooth)",
    "Enceladus":     "nafasli (Breathy)",
    "Erinome":       "aniq (Clear)",
    "Fenrir":        "qattiq erkak (Excitable)",
    "Gacrux":        "etuk (Mature)",
    "Iapetus":       "aniq (Clear)",
    "Kore":          "jonli ayol (Firm)",
    "Laomedeia":     "quvnoq (Upbeat)",
    "Leda":          "yoshlik (Youthful)",
    "Orus":          "qat'iy erkak (Firm)",
    "Puck":          "quvnoq erkak (Upbeat)",
    "Pulcherrima":   "dadil (Forward)",
    "Rasalgethi":    "ma'lumotli (Informative)",
    "Sadachbia":     "jonli (Lively)",
    "Sadaltager":    "bilimdon (Knowledgeable)",
    "Schedar":       "tinch (Even)",
    "Sulafat":       "iliq (Warm)",
    "Umbriel":       "erkin (Easy-going)",
    "Vindemiatrix":  "muloyim (Gentle)",
    "Zephyr":        "yorqin ayol (Bright)",
    "Zubenelgenubi": "oddiy (Casual)",
}
VOICE_NAMES = list(VOICES.keys())

TG_VOICE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": f"🎙 {name}", "callback_data": f"/voice {name}"}
            for name in VOICE_NAMES[i:i + 2]
        ]
        for i in range(0, len(VOICE_NAMES), 2)
    ]
}


def _normalize_voice(text) -> str:
    """Map user wording to a canonical Gemini voice name, or '' if unknown."""
    v = (str(text or "").strip().lower()
         .replace("-", " ").replace("_", " "))
    aliases = {
        "default": "Aoede", "auto": "Aoede", "standart": "Aoede",
        "normal": "Aoede", "classic": "Aoede",
        "aoede": "Aoede", "charon": "Charon", "fenrir": "Fenrir",
        "kore": "Kore", "puck": "Puck", "zephyr": "Zephyr",
        "ayol": "Aoede", "erkak": "Charon",
    }
    v = aliases.get(v, v.title())
    return v if v in VOICE_NAMES else ""


def _get_style_from_memory(memory: dict | None) -> tuple[str, str]:
    """
    Returns (mode, mood).
    Stored under preferences.assistant_mode / preferences.assistant_mood.
    """
    if not memory:
        return ("normal", "calm")

    prefs = memory.get("preferences", {}) if isinstance(memory, dict) else {}

    mode_entry = prefs.get("assistant_mode")
    mood_entry = prefs.get("assistant_mood")

    mode = mode_entry.get("value") if isinstance(mode_entry, dict) else mode_entry
    mood = mood_entry.get("value") if isinstance(mood_entry, dict) else mood_entry

    mode = _normalize_mode(mode) or "normal"
    mood = (str(mood or "").strip().lower() or "calm")

    valid_moods = {"calm", "playful", "romantic", "strict"}

    if mood not in valid_moods:
        mood = "calm"

    return (mode, mood)


def _get_voice_from_memory(memory: dict | None) -> str:
    """Returns the saved Gemini voice name (defaults to Aoede)."""
    prefs = memory.get("preferences", {}) if isinstance(memory, dict) else {}
    entry = prefs.get("assistant_voice")
    voice = entry.get("value") if isinstance(entry, dict) else entry
    voice = _normalize_voice(voice)
    return voice or "Aoede"


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Kaizumi, a sharp and efficient AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )


# ── Hafıza ────────────────────────────────────────────────────────────────────
_last_memory_input = ""
_memory_lock       = threading.Lock()
_memory_running    = False


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input, _memory_running

    user_text   = (user_text   or "").strip()
    jarvis_text = (jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return

    with _memory_lock:
        if _memory_running:
            print("[Memory] ⏳ Already extracting — skipping this turn.")
            return
        _memory_running = True

    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, jarvis_text, api_key):
            return
        data = extract_memory(user_text, jarvis_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")
    finally:
        with _memory_lock:
            _memory_running = False


# ── Tool declarations ─────────────────────────────────────────────────────────
TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image and RETURNS the analysis "
            "as text. MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. You have NO visual ability without "
            "this tool. After it returns, speak the result naturally. "
            "No other vision channel exists — this is the only way to see."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page, "
            "media playback (play/pause/next/previous), and per-app volume "
            "(e.g. 'mute Discord', 'lower Spotify only'). "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."},
                "app_name":    {"type": "STRING", "description": "App name for per-app volume (e.g. 'Spotify' for app_volume/mute_app)"}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders: list, create, delete, move, copy, rename, read, write, "
            "find, disk usage, zip/unzip, and full auto-organization. The 'organize' action "
            "groups loose files into category subfolders (Images, Documents, Spreadsheets, "
            "Code, ...) in mode by_type, by month in by_date, or by AI in mode ai. Use "
            "dry_run=true to preview first. 'undo_organize' restores the last run."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | organize | undo_organize | info | zip | unzip"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "scope":       {"type": "STRING", "description": "For organize: desktop | downloads | documents | pictures | music | videos | home | <custom path>"},
                "mode":        {"type": "STRING", "description": "For organize: by_type (default) | by_date | ai"},
                "dry_run":     {"type": "BOOLEAN", "description": "For organize: preview only, move nothing"},
                "include_subfolders": {"type": "BOOLEAN", "description": "For organize: also process files in subfolders"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy/zip/unzip"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands via natural language: disk space, processes, "
            "system info, network, find files, or anything in the command line."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Reports real-time computer status: battery, CPU, memory/RAM, disk/storage, "
            "network/WiFi, system uptime, and top running processes. "
            "Use when the user asks about system health, performance, battery, storage space, "
            "internet connection, or what's running on the computer."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "focus": {
                    "type": "STRING",
                    "description": "Optional focus area: overview | battery | cpu | memory | disk | network | processes | uptime. Default: overview"
                }
            },
            "required": []
        }
    },
    {
        "name": "set_mode",
        "description": (
            "Sets Kaizumi's conversation mode/persona. "
            "Use when the user says things like: "
            "'girlfriend mode', 'normal mode', 'crazy friend', 'butler mode', "
            "'engaging mode', 'switch your mode', 'o'zgartir'. "
            "This persists across sessions. Modes: "
            "normal | girlfriend | crazy_friend | butler | friend | casual."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {
                    "type": "STRING",
                    "description": "One of: normal | girlfriend | crazy_friend | butler | friend | casual"
                }
            },
            "required": ["mode"]
        }
    },
    {
        "name": "set_voice",
        "description": (
            "Changes Kaizumi's speaking voice (Gemini prebuilt voices). "
            "Use when the user asks to change/switch the voice, or says "
            "'ovozni o'zgartir', 'boshqa ovoz', 'speak with a male voice', "
            "'sounds too robotic'. This persists across sessions and takes "
            "effect shortly. Available voices: "
            + ", ".join(VOICE_NAMES) + "."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "voice": {
                    "type": "STRING",
                    "description": "One of: " + " | ".join(VOICE_NAMES)
                }
            },
            "required": ["voice"]
        }
    },
    {
        "name": "set_mood",
        "description": (
            "Sets Kaizumi's mood/energy within the current mode. "
            "Use when the user asks for calmer, more playful, more romantic, or stricter tone. "
            "This persists across sessions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mood": {
                    "type": "STRING",
                    "description": "One of: calm | playful | romantic | strict"
                }
            },
            "required": ["mood"]
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Search long-term memory for a stored fact about the user. "
            "Use when the user asks 'do you remember...', 'what do you know about...', "
            "'what's my favorite...', or when you need a saved detail mid-conversation "
            "(name, preferences, projects, people). Returns what you know."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":    {"type": "STRING", "description": "What to look for (e.g. 'favorite food', 'sister', 'project')"},
                "category": {"type": "STRING", "description": "Optional: identity | preferences | projects | relationships | wishes | notes"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "task_manager",
        "description": (
            "Check or control background agent tasks started via agent_task. "
            "Use for: 'how is my task going?', 'status of my task', 'cancel that task', "
            "'what tasks are running?'. You get a task_id when you start agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "status | list | cancel"},
                "task_id": {"type": "STRING", "description": "Task ID for status/cancel"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "clipboard",
        "description": (
            "Manage the system clipboard: read what's copied, copy text, paste it, "
            "clear it, or recall recent copied items. "
            "Use for 'copy that to clipboard', 'what's on my clipboard?', 'paste it'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "get | set | paste | clear | history | copy_last"},
                "text":   {"type": "STRING", "description": "Text for set/copy action"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "vision_gesture",
        "description": (
            "Full-body computer vision using the camera. Free, local, no AI API. "
            "Modes (continuous): 'gesture' recognizes hand gestures and finger counts; "
            "'air_mouse' moves the cursor with the index finger (pinch to click); "
            "'volume' controls volume via thumb-index pinch; 'motion' detects movement; "
            "'posture' reports body pose (arms raised, leaning); 'focus' watches the frame. "
            "One-shot actions: 'face_count' counts people, 'qr' reads a QR code, "
            "'snapshot' describes what's on camera. "
            "Use when the user asks about gestures, wants hand control, or camera actions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start | stop | face_count | qr | snapshot | status"},
                "mode":   {"type": "STRING", "description": "gesture | air_mouse | volume | motion | posture | focus (for start)"},
                "text":   {"type": "STRING", "description": "Optional question for snapshot"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "notify",
        "description": (
            "Sends a Windows toast notification popup (title + message). "
            "Use when the user asks to notify/alert me at a moment, pop a notification, "
            "or remind me with a popup, e.g. 'notify me when the download finishes'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message": {"type": "STRING", "description": "The notification message text (required)"},
                "title":   {"type": "STRING", "description": "Optional title (default: Kaizumi)"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "daily_briefing",
        "description": (
            "Morning briefing: today's date/time, weather for the user's city, "
            "key facts remembered about them, and system status. "
            "Use when the user says 'good morning', 'daily briefing', 'brief me', "
            "or asks what's going on today."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "Optional city for weather (defaults to saved memory)"}
            },
            "required": []
        }
    },
    {
        "name": "schedule",
        "description": (
            "Sets a timed in-app action that fires after a number of seconds. "
            "When it fires, Kaizumi speaks the message and sends a notification "
            "to the connected phone. Also lists and cancels pending schedules. "
            "Use for countdowns, 'remind me in X minutes', timers, or delayed tasks."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "set | list | cancel (default: list)"},
                "seconds": {"type": "INTEGER", "description": "Delay in seconds (set only, min 10)"},
                "message": {"type": "STRING", "description": "What to say/notify when it fires"},
                "id":      {"type": "INTEGER", "description": "Schedule id to cancel"}
            },
            "required": []
        }
    },
    {
        "name": "wake_word",
        "description": (
            "Controls the hands-free wake word listener ('Hey Kaizumi', "
            "or 'Hey Jarvis' before you record your own). "
            "When active, Kaizumi sleeps until the wake word is said, then listens. "
            "'record' samples your voice and builds a 'Hey Kaizumi' reference. "
            "Use when the user says 'activate wake word', 'record the wake word', "
            "'listen for hey kaizumi', or any wake-word command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start | stop | status | record (default: status)"},
                "clips":  {"type": "INTEGER", "description": "Number of clips to record for 'record' (default: 5)"}
            },
            "required": []
        }
    },
    {
        "name": "create_presentation",
        "description": (
            "Generates a PowerPoint (.pptx) file from a simple request and saves it "
            "to Documents/Kaizumi. Use for 'make me a presentation about X', "
            "'create slides about Y'. Pass the topic as title and the slides with "
            "their bullet points. After creating, tell the user where it was saved."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Presentation title / topic"
                },
                "filename": {
                    "type": "STRING",
                    "description": "Optional file name without extension (defaults to title)"
                },
                "slides": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title":   {"type": "STRING", "description": "Slide heading"},
                            "bullets": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Bullet points for the slide"}
                        },
                        "required": ["title"]
                    },
                    "description": "List of slides, each with a title and bullet points"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "create_spreadsheet",
        "description": (
            "Creates an Excel (.xlsx) spreadsheet with headers and data rows and saves it "
            "to Documents/Kaizumi. Use for 'make a spreadsheet of ...', "
            "'create a table with columns ... and these values'. "
            "After creating, tell the user where it was saved."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "filename":  {"type": "STRING", "description": "File name without extension"},
                "sheet_name": {"type": "STRING", "description": "Optional sheet name (default: Sheet1)"},
                "headers":   {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Column headers"},
                "rows":      {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}, "description": "Data rows; each row is an array of cell values"}
            },
            "required": ["filename"]
        }
    },
    {
        "name": "smart_home_control",
        "description": (
            "Controls smart home devices (lights, switches, plugs, thermostats) registered "
            "in config/smart_home.json. Supports Home Assistant, a custom webhook, or a "
            "simulated mode for testing. Actions: turn_on, turn_off, toggle, set_level, "
            "status. Use for 'turn on the living room light', 'set brightness to 50', "
            "'what is the state of the AC'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "turn_on | turn_off | toggle | set_level | status (default: status)"},
                "device": {"type": "STRING", "description": "Device id or name from smart_home.json"},
                "value":  {"type": "NUMBER", "description": "Level for set_level (e.g. brightness percent 0-100)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "send_sms",
        "description": (
            "Sends an SMS through the connected Android phone (the Kaizumi bridge "
            "app). Requires a phone to be connected to the PC bridge. "
            "Use for 'text X number saying Y', 'send an SMS to ...'. "
            "If no phone is connected, explain that the user needs to open the "
            "Kaizumi app and connect first."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "phone":   {"type": "STRING", "description": "Recipient phone number (international format preferred)"},
                "message": {"type": "STRING", "description": "SMS text to send"}
            },
            "required": ["phone", "message"]
        }
    },
    {
        "name": "read_notifications",
        "description": (
            "Reads the notifications currently visible on the connected Android "
            "phone (WhatsApp, Telegram, Messenger, calls, etc). Requires the Kaizumi "
            "bridge app to be connected and notification access to be enabled on the "
            "phone. Use when the user asks 'check my phone notifications', "
            "'did I get any messages'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limit": {"type": "INTEGER", "description": "Max number of notifications to return (default: 10)"}
            },
            "required": []
        }
    },
    {
        "name": "phone_info",
        "description": (
            "Returns status information about the connected Android phone: model, "
            "Android version, battery level, network type and free memory. "
            "Use when the user asks 'how is my phone', 'what is the battery on my "
            "phone', 'phone status'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "gmail",
        "description": (
            "Sends and reads Gmail. 'send' composes an email to any address; "
            "'read' lists the most recent inbox emails. Requires a Gmail app "
            "password saved in config/api_keys.json (gmail_user + "
            "gmail_app_password). Use for 'send an email to X', 'check my email', "
            "'what is in my inbox'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "send | read (default: send)"},
                "to":      {"type": "STRING", "description": "Recipient email address (send only)"},
                "subject": {"type": "STRING", "description": "Email subject (send only)"},
                "body":    {"type": "STRING", "description": "Email body text (send only)"},
                "limit":   {"type": "INTEGER", "description": "How many recent emails to read (read only, default 5)"}
            },
            "required": []
        }
    },
    {
        "name": "read_pdf",
        "description": (
            "Reads a PDF file and shows a preview of its content (page count and "
            "opening text). Give the file name or path, e.g. 'manual.pdf' or "
            "'C:\\Users\\you\\Documents\\manual.pdf'. Use for 'open/read the PDF', "
            "'what is in this document'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "PDF file name or full path"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "pdf_qa",
        "description": (
            "Answers a question about the contents of a PDF file. Finds the "
            "relevant parts of the document and answers from them. Use for "
            "'what does the PDF say about X', 'summarize this document', "
            "'find Y in the manual'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path":     {"type": "STRING", "description": "PDF file name or full path"},
                "question": {"type": "STRING", "description": "Question about the document's content"}
            },
            "required": ["path", "question"]
        }
    },
    {
        "name": "autostart",
        "description": (
            "Controls whether Kaizumi starts automatically at Windows login. "
            "Actions: status | enable | disable. 'enable' registers Kaizumi in "
            "the startup list (optionally with the phone bridge via 'remote'). "
            "Use for 'start at login', 'run on startup', 'open automatically'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | enable | disable (default: status)"},
                "remote": {"type": "BOOLEAN", "description": "For 'enable': also start the phone bridge (default true)"}
            },
            "required": []
        }
    },
    {
        "name": "vision_click",
        "description": (
            "Clicks anywhere on the screen by looking at it. Describe the element "
            "to click ('the Send button', 'the Chrome icon', 'the search box') and "
            "Kaizumi finds it on the screenshot and clicks it. Use for 'click the "
            "Send button', 'press the green button', 'click on the search field'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target":      {"type": "STRING", "description": "What to click, in plain words"},
                "click":       {"type": "STRING", "description": "Optional: 'double' for a double-click"},
                "only_coords": {"type": "BOOLEAN", "description": "Optional: return coordinates without clicking"}
            },
            "required": ["target"]
        }
    },
    {
        "name": "phone_ring",
        "description": (
            "Makes the connected phone vibrate and beep so it can be found. "
            "Use when the user asks 'find my phone', 'ring my phone', 'wheres my "
            "phone'. Requires the Kaizumi app to be open and connected on the phone."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "monitor_alerts",
        "description": (
            "Sets PC monitoring alerts: warn when CPU, RAM, disk or battery "
            "crosses a threshold, then Kaizumi speaks + notifies the phone. "
            "Actions: list | add | remove | check | status. "
            "Use for 'alert me when cpu goes above 90', 'warn me when my battery "
            "is below 20 percent', 'tell me if ram is high', 'monitor the pc'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "list | add | remove | check | status (default: list)"},
                "kind":      {"type": "STRING", "description": "Metric to watch: cpu | ram | disk | battery"},
                "threshold": {"type": "NUMBER", "description": "Percent threshold to trigger"},
                "above":     {"type": "BOOLEAN", "description": "True=alert above threshold (cpu/ram/disk), false=alert below (battery). Default true."},
                "message":   {"type": "STRING", "description": "Optional custom alert message"},
                "id":        {"type": "INTEGER", "description": "Alert id to remove"}
            },
            "required": []
        }
    },
    {
        "name": "pc_health",
        "description": (
            "PC Health Guardian: automatic proactive alerts for battery, disk "
            "space, RAM, CPU, temperature and backup reminders — works out of "
            "the box with smart defaults, no setup needed. "
            "Actions: status | report | enable | disable | check | backup | "
            "set | reset. Use for 'pc health report', 'how is my battery', "
            "'battery health', 'health check', 'backup done', 'stop monitoring', "
            "'warn me about low disk'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | report | enable | disable | check | backup | set | reset (default: status)"},
                "key":    {"type": "STRING", "description": "Setting to change with 'set': battery_low | battery_full_plugged | disk_min_free_gb | ram_high | cpu_high | temp_high | backup_days | cooldown"},
                "value":  {"type": "NUMBER", "description": "New numeric value for 'set'"}
            },
            "required": []
        }
    },
    {
        "name": "read_document",
        "description": (
            "Reads any local document or web page and shows a preview: PDF, TXT, "
            "Markdown, HTML, Word (.docx), CSV, Excel, PowerPoint, or a website "
            "URL. Use for 'read this document', 'what is in the file', "
            "'show me that page'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source": {"type": "STRING", "description": "File name, full path, or URL"}
            },
            "required": ["source"]
        }
    },
    {
        "name": "document_qa",
        "description": (
            "Answers questions about the content of ANY document or web page: "
            "PDF, Word, TXT, Markdown, HTML, Excel, PowerPoint or a website URL. "
            "Finds the relevant parts and answers from them. Use for "
            "'summarize this document', 'what does the file say about X', "
            "'what is on this website about Y'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source":   {"type": "STRING", "description": "File name, full path, or URL"},
                "question": {"type": "STRING", "description": "Question about the content"}
            },
            "required": ["source", "question"]
        }
    },
    {
        "name": "email_watch",
        "description": (
            "Turns on or off an automatic watcher that alerts the user as soon "
            "as new mail arrives in Gmail (speaks + notifies + phone push). "
            "Actions: enable | disable | status. Requires Gmail already "
            "configured. Use for 'alert me when I get new email', 'tell me when "
            "a new mail arrives', 'stop email alerts'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "enable | disable | status (default: status)"}
            },
            "required": []
        }
    },
    {
        "name": "translate",
        "description": (
            "Translates any text into another language. Use for 'translate this "
            "into Russian', 'how do I say X in English', 'translate Y to Uzbek'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text":  {"type": "STRING", "description": "Text to translate"},
                "to":    {"type": "STRING", "description": "Target language, e.g. English, Russian, Uzbek (default English)"},
                "from":  {"type": "STRING", "description": "Optional source language (auto-detected if omitted)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "media_control",
        "description": (
            "Controls whatever music or video is playing (Spotify, YouTube, "
            "VLC, media players): play/pause, next, previous, volume up/down, "
            "mute. Works with global media keys. Use for 'play music', 'pause', "
            "'next song', 'volume down', 'switch the track'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | pause | toggle | next | prev | volume_up | volume_down | mute (default: toggle)"}
            },
            "required": []
        }
    },
    {
        "name": "api_add_key",
        "description": (
            "Adds a NEW Gemini API key to the rotation pool. Use when the "
            "current key(s) hit their daily quota (the AI says the limit is "
            "exhausted). The user pastes a new key starting with 'AIza...'. "
            "Old keys are kept and reused automatically after their quota "
            "resets. Use for 'yangi api key qoshish', 'add api key AIza...', "
            "'key qo'sh'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "The new Gemini API key, starts with AIza"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "google_auth",
        "description": (
            "Starts Google authorization (Device Flow). Returns a code + URL "
            "that the user must open on their phone (google.com/device) and "
            "enter. Then authorization completes in the background. Use when "
            "Google Calendar/Drive/Gmail API need connecting, or when the AI "
            "says Google is not authorized."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "google_auth_status",
        "description": (
            "Reports whether Google is authorized (and which Gmail account), "
            "or is still waiting for the user to enter the code."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "calendar",
        "description": (
            "Google Calendar operations: list upcoming events, add a new "
            "event, delete an event. Use for 'what's on my calendar', 'add an "
            "event tomorrow at 3pm', 'dushanba 10da uchrashuv qo'y', 'delete "
            "the dentist appointment'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | add | delete (default: list)"},
                "summary":     {"type": "STRING", "description": "Event title (for add/delete)"},
                "start":       {"type": "STRING", "description": "Start 'YYYY-MM-DD HH:MM' or 'HH:MM' (for add)"},
                "end":         {"type": "STRING", "description": "End time, same format (for add)"},
                "description": {"type": "STRING", "description": "Optional details (for add)"},
                "event_id":    {"type": "STRING", "description": "Event id (for delete)"},
                "max_results": {"type": "INTEGER", "description": "How many events to list (default 10)"}
            },
            "required": []
        }
    },
    {
        "name": "drive",
        "description": (
            "Google Drive operations: list recent files, search, read a file's "
            "text content, upload a text file. Use for 'drive'dagi fayllar', "
            "'search my drive for X', 'read this document from drive', 'upload "
            "this note to drive'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "list | search | read | upload (default: list)"},
                "query":      {"type": "STRING", "description": "Search query (for search)"},
                "file_id":    {"type": "STRING", "description": "File id (for read)"},
                "name":       {"type": "STRING", "description": "File name (for upload)"},
                "content":    {"type": "STRING", "description": "Text content (for upload)"},
                "max_results":{"type": "INTEGER", "description": "How many files to list (default 10)"}
            },
            "required": []
        }
    },
]


class JarvisLive:

    def __init__(self, ui: JarvisUI, remote_port: int | None = None):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._send_lock     = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._last_play_ts  = 0.0
        self._turn_complete = False
        self._ready         = False
        self._phase         = PHASE_IDLE
        self._phase_lock    = threading.Lock()
        self._rolling_parts = []
        self._rolling_len   = 0
        self._roll_turns    = 0
        self.loop_guard     = LoopGuard()
        self._tool_handlers = self._build_tool_handlers()
        self.ui.on_text_command = self._on_text_command
        self.remote_clients = set()
        self.remote_port    = remote_port
        self._schedules     = []
        self._sched_lock    = threading.Lock()

        self.telegram_token = None
        self.telegram_chat  = None
        try:
            _tg_cfg = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
            self.telegram_token = (_tg_cfg.get("telegram_bot_token") or "").strip() or None
            self.telegram_chat  = _tg_cfg.get("telegram_chat_id")
        except Exception:
            pass

        try:
            wake_service.configure(on_detect=self._on_wake_detect)
        except Exception:
            pass

    def _on_wake_detect(self):
        """Excited when the wake word is heard — un-mute and listen (barge-in)."""
        try:
            if not self._ready or not self.session:
                print("[WakeWord] ⚠️ Ignored — session not ready.")
                return
            if self.remote_clients:
                print("[WakeWord] 🚫 Ignored — phone remote active, barge-in on the phone.")
                return
            self.ui.muted = False
            self.set_speaking(False)
            self.ui.write_log("SYS: Wake word heard — listening.")
        except Exception as e:
            print(f"[WakeWord] ⚠️ {e}")

    def attach_tray(self):
        """Background tray icon + global hotkeys (optional deps)."""
        try:
            from actions import system_tray

            def _on_ui(cb):
                return lambda: self.ui.root.after(0, cb)

            def _wake_active():
                from actions.wake_word import _pick_engine
                return _pick_engine()[1]._running

            def _toggle_wake():
                try:
                    from actions.wake_word import _pick_engine
                    from actions.kaizumi_wake import _matcher as kw_matcher
                    name, eng = _pick_engine()
                    if not eng.available:
                        print("[Tray] ⚠️ Wake word engine not ready:", name)
                        return
                    if eng._running:
                        r = eng.stop()
                    else:
                        eng.configure(on_detect=self._on_wake_detect)
                        r = eng.start()
                    print(f"[Tray] {r}")
                    self.ui.write_log(f"SYS: {r}")
                except Exception as e:
                    print(f"[Tray] ⚠️ {e}")

            def _hide_show():
                state = self.ui.root.state()
                if state in ("normal", "iconic"):
                    self.ui.root.withdraw()
                else:
                    self.ui.root.deiconify()
                    self.ui.root.lift()

            def _brief():
                if self._loop and self.session:
                    self.speak("Give me today's morning briefing.")
                print("[Tray] Briefing requested")

            def _quit():
                try:
                    self.ui.root.after(0, self.ui.root.destroy)
                except Exception:
                    os._exit(0)

            callbacks = {
                "toggle_mute": _on_ui(self.ui._toggle_mute),
                "toggle_wake": _toggle_wake,
                "hide_show":   _hide_show,
                "briefing":    _brief,
                "quit":        _quit,
            }

            def menu_factory():
                import pystray
                return pystray.Menu(
                    pystray.MenuItem(
                        lambda item: "🔇 Unmute" if self.ui.muted else "🔊 Mute (F4)",
                        _on_ui(self.ui._toggle_mute),
                    ),
                    pystray.MenuItem(
                        lambda item: "😴 Stop Wake Word" if _wake_active() else "💤 Activate Wake Word",
                        _toggle_wake,
                    ),
                    pystray.MenuItem("📋 Daily Briefing", _brief),
                    pystray.MenuItem("👁 Hide/Show Window", _hide_show),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("🚪 Quit Kaizumi", _quit, default=True),
                )

            tray_ok   = system_tray.configure_icon(menu_factory)
            hot_ok    = system_tray.register_hotkeys(callbacks)
            print(f"[Tray] 🖥 Tray: {'on' if tray_ok else 'off'} | Hotkeys: {hot_ok} registered ({system_tray.available()})")
        except Exception as e:
            print(f"[Tray] ⚠️ Could not attach tray: {e}")
            import traceback; traceback.print_exc()

    def _on_text_command(self, text: str):
        if not self._loop or not self.session or not self._send_lock:
            return
        async def _send():
            async with self._send_lock:
                await self.session.send_realtime_input(text=text)
        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        self._set_phase(PHASE_SPEAKING if value else PHASE_LISTENING)

    def _persona_info(self) -> tuple[str, str, str]:
        """Return (mode, mood, voice) for the UI header badges."""
        try:
            memory       = load_memory()
            mode, mood   = _get_style_from_memory(memory)
            voice        = _get_voice_from_memory(memory)
            return (mode, mood, voice)
        except Exception:
            return ("normal", "calm", "Aoede")

    def _set_phase(self, phase: str):
        with self._phase_lock:
            self._phase = phase
        if phase == PHASE_THINKING:
            self.ui.set_state("THINKING")
        elif phase == PHASE_SPEAKING:
            self.ui.set_state("SPEAKING")
        elif phase == PHASE_LISTENING:
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
        else:
            self.ui.set_state("ONLINE")
        if self.remote_clients:
            state = {
                PHASE_THINKING:  "THINKING",
                PHASE_SPEAKING:  "SPEAKING",
                PHASE_LISTENING: "MUTED" if self.ui.muted else "LISTENING",
            }.get(phase, "ONLINE")
            self.broadcast_remote({"type": "phase", "state": state})

    def broadcast_remote(self, payload: dict):
        """Send a JSON event to every connected phone (async-safe)."""
        if not self.remote_clients or not self._loop:
            return
        for ws in list(self.remote_clients):
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send(json.dumps(payload, ensure_ascii=False)), self._loop
                )
            except Exception:
                self.remote_clients.discard(ws)

    def _safely_send(self, ws, payload: dict):
        """Send one JSON event to one phone (async-safe)."""
        if not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(payload, ensure_ascii=False)), self._loop
            )
        except Exception:
            pass

    def _current_phase(self) -> str:
        with self._phase_lock:
            return self._phase

    def force_reset(self):
        """Single-owner guarantee: any failure path can force-clear the audio
        turn; set_speaking(False) alone is not enough in edge cases."""
        with self._speaking_lock:
            self._is_speaking = False
        self._set_phase(PHASE_LISTENING)

    def _schedule_session_reload(self):
        """Mode/voice changed — close the live session shortly so run() reconnects
        and re-applies the system prompt / speech config from memory."""
        if not self._loop or not self.session:
            return

        async def _reload_soon():
            await asyncio.sleep(2.5)
            try:
                await self.session.close()
            except Exception:
                pass

        try:
            asyncio.run_coroutine_threadsafe(_reload_soon(), self._loop)
        except Exception:
            pass

    def _update_rolling(self, user_text: str, kaizumi_text: str):
        if not user_text and not kaizumi_text:
            return
        part = f"User: {user_text}\nKaizumi: {kaizumi_text}\n"
        self._rolling_parts.append(part)
        self._rolling_len += len(part)
        with self._phase_lock:
            self._roll_turns += 1
        while self._rolling_len > MAX_ROLLING_CHARS and self._rolling_parts:
            old = self._rolling_parts.pop(0)
            self._rolling_len -= len(old)

    def _rolling_digest(self, limit: int = 1400) -> str:
        """Flatten the recent-context buffer into the prompt-able string."""
        joined = "".join(self._rolling_parts)[-MAX_ROLLING_CHARS:]
        if len(joined) > limit:
            joined = joined[-limit:]
            cut = joined.find("\n")
            if cut > 0:
                joined = joined[cut:]
        return joined.strip()

    def _persist_rolling_summary(self):
        """Save a compact summary of recent turns into long-term memory so a
        restart doesn't wipe the conversation context entirely."""
        try:
            with self._phase_lock:
                self._roll_turns = 0
            recent = self._rolling_digest(limit=2000)
            if not recent:
                return
            from datetime import datetime
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            update_memory({
                "notes": {
                    f"conversation_{stamp.replace(' ', '_').replace(':', '-')}": {
                        "value": recent[:400]
                    }
                }
            })
            print("[Memory] 🧠 Rolling summary persisted")
        except Exception as e:
            print(f"[Memory] ⚠️ Could not persist summary: {e}")

    def speak(self, text: str):
        if not self._loop or not self.session or not self._send_lock:
            return
        async def _send():
            async with self._send_lock:
                await self.session.send_realtime_input(text=text)
        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def _log_tool_error(self, tool_name: str, tr: ToolResult):
        short = str(tr.content)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        if tr.error_kind == "fatal":
            self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_tool_handlers(self):
        """name -> (handler(args)->str, timeout_seconds)."""
        ui    = self.ui
        speak = self.speak

        def _agent_task(args):
            from agent.task_queue import get_queue, TaskPriority
            priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
            priority = priority_map.get(str(args.get("priority", "normal")).lower(), TaskPriority.NORMAL)
            task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=speak)
            return f"Task started (ID: {task_id})."

        def _recall(args):
            from memory.memory_manager import search_memory
            return search_memory(args.get("query", ""), args.get("category", ""))

        def _wake(args):
            from actions.wake_word import wake_word as wake_word_action
            return wake_word_action(parameters=args, player=ui)

        def _save_memory(args):
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            return "ok"

        def _set_mode(args):
            mode = _normalize_mode(args.get("mode", ""))
            if not mode:
                return ("Invalid mode. Use: normal, girlfriend, crazy_friend, "
                        "butler, friend, casual.")
            update_memory({"preferences": {"assistant_mode": {"value": mode}}})
            self._schedule_session_reload()
            self.ui.set_persona(*self._persona_info())
            return f"Mode set to: {mode}."

        def _set_voice(args):
            voice = _normalize_voice(args.get("voice", ""))
            if not voice:
                return ("Invalid voice. Use: " + ", ".join(VOICE_NAMES) + ".")
            update_memory({"preferences": {"assistant_voice": {"value": voice}}})
            self._schedule_session_reload()
            self.ui.set_persona(*self._persona_info())
            return f"Voice set to: {voice}."

        def _set_mood(args):
            mood = str(args.get("mood", "")).strip().lower()
            valid = {"calm", "playful", "romantic", "strict"}
            if mood not in valid:
                return f"Invalid mood '{mood}'. Use: calm, playful, romantic, strict."
            update_memory({"preferences": {"assistant_mood": {"value": mood}}})
            self.ui.set_persona(*self._persona_info())
            return f"Mood set to: {mood}."

        def _api_add_key(args):
            import api_keys
            key = str(args.get("key", "")).strip()
            try:
                n = api_keys.add_key(key)
            except ValueError as e:
                return f"❌ {e}"
            return (f"✅ Yangi API kalit qo'shildi (jami: {n}). "
                    "Limit tugagan kalitlar avtomatik aylanadi.")

        def _google_auth(args):
            import threading
            import google_oauth
            if not google_oauth.is_configured():
                return ("Google OAuth not configured. Add 'google_client_id' and "
                        "'google_client_secret' to config/api_keys.json first, sir.")
            if google_oauth.has_token():
                return (f"Google allaqachon ulangan"
                        + (f" ({google_oauth.email_address()})" if google_oauth.email_address() else "")
                        + ". /google_auth_status bilan ko'ring.")
            info = google_oauth.auth_start()
            if not info.get("ok"):
                return f"❌ {info.get('error')}"
            device_code = info["device_code"]
            user_code   = info["user_code"]
            url         = info.get("verification_url", "google.com/device")

            def _poll():
                try:
                    google_oauth.auth_poll(device_code, interval=info.get("interval", 5), timeout=600)
                except Exception as e:
                    print(f"[Google] auth poll error: {e}")
            threading.Thread(target=_poll, daemon=True).start()
            return (f"📱 Avtorizatsiya kodi: *{user_code}*\n"
                    f"Telefonda oching: {url}\n"
                    "Google akkauntingizga kiring va kodni kiriting.\n"
                    "Tasdiqlagach men avtomatik saqlayman. 2-3 daqiqa kuting, "
                    "keyin 'google tekshir' deb so'rang.")

        def _google_auth_status(args):
            import google_oauth
            return google_oauth.status()

        return {
            "open_app":          (lambda a: open_app(parameters=a, response=None, player=ui), 60),
            "weather_report":    (lambda a: weather_action(parameters=a, player=ui), 60),
            "browser_control":   (lambda a: browser_control(parameters=a, player=ui), 120),
            "file_controller":   (lambda a: file_controller(parameters=a, player=ui), 60),
            "send_message":      (lambda a: send_message(parameters=a, response=None, player=ui, session_memory=None), 60),
            "reminder":          (lambda a: reminder(parameters=a, response=None, player=ui), 30),
            "youtube_video":     (lambda a: youtube_video(parameters=a, response=None, player=ui), 90),
            "screen_process":    (lambda a: screen_process(parameters=a, player=ui), 120),
            "computer_settings": (lambda a: computer_settings(parameters=a, response=None, player=ui), 120),
            "cmd_control":       (lambda a: cmd_control(parameters=a, player=ui), 120),
            "desktop_control":   (lambda a: desktop_control(parameters=a, player=ui), 60),
            "code_helper":       (lambda a: code_helper(parameters=a, player=ui, speak=speak), 180),
            "dev_agent":         (lambda a: dev_agent(parameters=a, player=ui, speak=speak), 180),
            "agent_task":        (_agent_task, 15),
            "web_search":        (lambda a: web_search_action(parameters=a, player=ui), 90),
            "computer_control":  (lambda a: computer_control(parameters=a, player=ui), 120),
            "system_status":     (lambda a: system_status(parameters=a, player=ui), 45),
            "task_manager":      (lambda a: task_manager(parameters=a, player=ui), 60),
            "clipboard":         (lambda a: clipboard_action(parameters=a, player=ui), 45),
            "vision_gesture":    (lambda a: vision_gesture(parameters=a, player=ui, speak=speak), 120),
            "recall_memory":     (_recall, 20),
            "game_updater":      (lambda a: game_updater(parameters=a, player=ui, speak=speak), 120),
            "flight_finder":     (lambda a: flight_finder(parameters=a, player=ui), 120),
            "notify":            (lambda a: notify(parameters=a, player=ui), 30),
            "daily_briefing":    (lambda a: daily_briefing(parameters=a, player=ui), 120),
            "wake_word":         (_wake, 45),
            "save_memory":       (_save_memory, 10),
            "set_mode":          (_set_mode, 10),
            "set_voice":         (_set_voice, 10),
            "set_mood":          (_set_mood, 10),
            "gmail":             (lambda a: gmail_action(parameters=a, response=None, player=ui), 60),
            "read_pdf":          (lambda a: read_pdf_action(parameters=a, response=None, player=ui), 60),
            "pdf_qa":            (lambda a: pdf_qa(parameters=a, response=None, player=ui), 90),
            "autostart":         (lambda a: autostart_action(parameters=a, response=None, player=ui), 20),
            "vision_click":      (lambda a: vision_click_action(parameters=a, response=None, player=ui), 90),
            "monitor_alerts":    (lambda a: monitor_action(parameters=a, response=None, player=ui), 15),
            "pc_health":         (lambda a: guardian_action(parameters=a, response=None, player=ui), 15),
            "email_watch":       (lambda a: email_watch_action(parameters=a, response=None, player=ui), 15),
            "translate":         (lambda a: translate_action(parameters=a, response=None, player=ui), 45),
            "media_control":     (lambda a: media_control_action(parameters=a, response=None, player=ui), 20),
            "read_document":     (lambda a: read_document_action(parameters=a, response=None, player=ui), 45),
            "document_qa":       (lambda a: document_qa_action(parameters=a, response=None, player=ui), 90),
            "api_add_key":       (_api_add_key, 15),
            "google_auth":       (_google_auth, 30),
            "google_auth_status": (_google_auth_status, 15),
            "calendar":          (lambda a: calendar_action(parameters=a, response=None, player=ui), 60),
            "drive":             (lambda a: drive_action(parameters=a, response=None, player=ui), 60),
        }

    async def _dispatch_tool(self, name: str, args: dict) -> ToolResult:
        blocked = self.loop_guard.check(name, args)
        if blocked:
            print(f"[KAIZUMI] 🛑 {name} blocked by loop guard")
            return ToolResult(ok=False, content=blocked, error_kind="loop")

        entry = self._tool_handlers.get(name)
        if entry is None:
            return ToolResult(ok=False, content=f"Unknown tool: {name}", error_kind="fatal")

        fn, timeout = entry
        return await run_sync_tool(lambda: fn(args), name, timeout=timeout)

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        mode, mood = _get_style_from_memory(memory)
        voice      = _get_voice_from_memory(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        style_ctx = (
            "[ASSISTANT MODE & MOOD]\n"
            f"Mode: {mode}\n"
            f"Mood: {mood}\n"
            f"Voice: {voice}\n"
            "Follow the mode/mood rules from the system prompt.\n\n"
        )

        parts = [time_ctx]
        recent_ctx = self._rolling_digest(limit=1400)
        if recent_ctx:
            parts.append(
                "[RECENT CONVERSATION — use it to stay consistent, but focus on what the user just said]\n"
                + recent_ctx + "\n"
            )
        if mem_str:
            parts.append(mem_str)
        parts.append(style_ctx)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
            thinking_config=types.ThinkingConfig(
                thinking_level=THINKING_LEVEL
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        log_tool(name, args)
        print(f"[KAIZUMI] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")

        # ── save_memory: sessiz, hızlı, Gemini'ye bildirim yok ───────────────
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        # ── set_mode / set_mood / set_voice: persist style across sessions ──
        if name == "set_mode":
            mode = _normalize_mode(args.get("mode", ""))
            if not mode:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": ("Invalid mode. Use: normal, girlfriend, "
                                         "crazy_friend, butler, friend, casual.")}
                )
            update_memory({"preferences": {"assistant_mode": {"value": mode}}})
            self._schedule_session_reload()
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Mode set to: {mode}."}
            )

        if name == "set_voice":
            voice = _normalize_voice(args.get("voice", ""))
            if not voice:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": ("Invalid voice. Use: "
                                          + ", ".join(VOICE_NAMES) + ".")}
                )
            update_memory({"preferences": {"assistant_voice": {"value": voice}}})
            self._schedule_session_reload()
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Voice set to: {voice}."}
            )

        if name == "set_mood":
            mood = str(args.get("mood", "")).strip().lower()
            valid = {"calm", "playful", "romantic", "strict"}
            if mood not in valid:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": f"Invalid mood '{mood}'. Use: calm, playful, romantic, strict."}
                )
            update_memory({"preferences": {"assistant_mood": {"value": mood}}})
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Mood set to: {mood}."}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        self.broadcast_remote({"type": "tool", "name": name, "status": "start",
                               "summary": " ".join(str(v) for v in args.values())[:120]})
        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                r = await loop.run_in_executor(None, lambda: screen_process(parameters=args, player=self.ui))
                result = r or "Vision analysis completed."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "cmd_control":
                r = await loop.run_in_executor(None, lambda: cmd_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, lambda: system_status(parameters=args, player=self.ui))
                result = r or "System status retrieved."

            elif name == "task_manager":
                r = await loop.run_in_executor(None, lambda: task_manager(parameters=args, player=self.ui))
                result = r or "Task info retrieved."

            elif name == "clipboard":
                r = await loop.run_in_executor(None, lambda: clipboard_action(parameters=args, player=self.ui))
                result = r or "Clipboard operation done."

            elif name == "vision_gesture":
                r = await loop.run_in_executor(
                    None, lambda: vision_gesture(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Vision action done."

            elif name == "recall_memory":
                from memory.memory_manager import search_memory
                r = await loop.run_in_executor(
                    None,
                    lambda: search_memory(args.get("query", ""), args.get("category", ""))
                )
                result = r or "No memory found."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "notify":
                r = await loop.run_in_executor(None, lambda: notify(parameters=args, player=self.ui))
                result = r or "Notification sent."

            elif name == "daily_briefing":
                r = await loop.run_in_executor(None, lambda: daily_briefing(parameters=args, player=self.ui))
                result = r or "Daily briefing delivered."

            elif name == "wake_word":
                from actions.wake_word import wake_word as wake_word_action
                r = await loop.run_in_executor(None, lambda: wake_word_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "schedule":
                result = await self._schedule(args)

            elif name == "create_presentation":
                from actions.office_builder import create_presentation as _make_pptx
                r = await loop.run_in_executor(
                    None,
                    lambda: _make_pptx(
                        title=args.get("title", ""),
                        slides=args.get("slides") or [],
                        filename=args.get("filename"),
                    ),
                )
                result = r

            elif name == "create_spreadsheet":
                from actions.office_builder import create_spreadsheet as _make_xlsx
                r = await loop.run_in_executor(
                    None,
                    lambda: _make_xlsx(
                        filename=args.get("filename", "spreadsheet"),
                        headers=args.get("headers") or [],
                        rows=args.get("rows") or [],
                        sheet_name=args.get("sheet_name", "Sheet1"),
                    ),
                )
                result = r

            elif name == "smart_home_control":
                from actions.smart_home import smart_home_control as _sh_control
                r = await loop.run_in_executor(
                    None,
                    lambda: _sh_control(
                        action=args.get("action", "status"),
                        device=args.get("device"),
                        value=args.get("value"),
                    ),
                )
                result = r

            elif name in ("send_sms", "read_notifications", "phone_info", "phone_ring"):
                from remote_bridge import (
                    send_sms_via_phone, read_notifications_via_phone,
                    phone_info_via_phone, ring_phone_via_phone,
                )
                if name == "send_sms":
                    r = await loop.run_in_executor(
                        None,
                        lambda: send_sms_via_phone(self, args.get("phone", ""), args.get("message", "")),
                    )
                elif name == "read_notifications":
                    r = await loop.run_in_executor(
                        None,
                        lambda: read_notifications_via_phone(self, args.get("limit", 10)),
                    )
                elif name == "phone_info":
                    r = await loop.run_in_executor(None, lambda: phone_info_via_phone(self))
                else:
                    r = await loop.run_in_executor(None, lambda: ring_phone_via_phone(self))
                result = r

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            log_tool(name, args, error=e)
            self.speak_error(name, e)
            self.broadcast_remote({"type": "tool", "name": name, "status": "error",
                                   "summary": str(e)[:120]})

        self.broadcast_remote({"type": "tool", "name": name, "status": "done",
                               "summary": str(result)[:120]})

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        log_tool(name, args, result=result)
        print(f"[KAIZUMI] 📤 {name} → {str(result)[:80]}")

        # ── Result: tek cümle söyle, dur ──────────────────────────────────────
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _schedule(self, args: dict) -> str:
        """In-app timed actions: when they fire, Kaizumi speaks + notifies the
        phone instead of relying on Windows Task Scheduler."""
        action = str(args.get("action", "list")).lower().strip()
        now = time.time()

        with self._sched_lock:
            if action in ("set", "add", "create"):
                try:
                    seconds = max(10, int(args.get("seconds", 60)))
                except (TypeError, ValueError):
                    return "I need `seconds` as a number."
                message = str(args.get("message", "Reminder")).strip() or "Reminder"
                sid = len(self._schedules) + 1
                if any(s.get("id") == sid and not s.get("fired") for s in self._schedules):
                    sid = max((s.get("id", 0) for s in self._schedules), default=0) + 1
                self._schedules.append({
                    "id": sid, "fire_at": now + seconds,
                    "message": message, "fired": False,
                })
                when = self._fmt_time(now + seconds)
                return (f"Scheduled: '{message}' in {seconds}s (ID {sid}, fires at {when}). "
                        "I will speak up and notify your phone.")

            if action in ("cancel", "delete", "remove"):
                try:
                    sid = int(args.get("id", 0))
                except (TypeError, ValueError):
                    return "I need `id` as a number."
                for s in self._schedules:
                    if s.get("id") == sid:
                        self._schedules.remove(s)
                        return f"Cancelled schedule ID {sid}."
                return f"No scheduled action with ID {sid}, sir."

            # list / status
            pending = [s for s in self._schedules if not s.get("fired")]
            if not pending:
                return "No active scheduled actions, sir."
            lines = [f"ID {s['id']} → '{s['message']}' at {self._fmt_time(s['fire_at'])}"
                     for s in pending[:8]]
            return "Active schedules: " + "; ".join(lines)

    @staticmethod
    def _fmt_time(ts: float) -> str:
        try:
            return time.strftime("%I:%M %p", time.localtime(ts))
        except Exception:
            return "?"

    async def _scheduler_loop(self):
        """Fire due scheduled actions — speak + notify phone, once each."""
        try:
            from actions.notifications import notify
        except Exception:
            notify = None
        while True:
            try:
                due = []
                with self._sched_lock:
                    for s in self._schedules:
                        if not s.get("fired") and time.time() >= s.get("fire_at", 0):
                            due.append(s)
                            s["fired"] = True
                for s in due:
                    msg = f"⏰ Reminder: {s['message']}"
                    print(f"[Scheduler] 🔔 {msg}")
                    if self.session:
                        self.speak(msg)
                    self.ui.write_log(msg)
                    self.broadcast_remote({"type": "system", "text": msg})
                    if notify:
                        try:
                            notify(parameters={"title": "Kaizumi", "message": s["message"]},
                                   player=self.ui)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[Scheduler] ⚠️ {e}")
            await asyncio.sleep(5)

    async def _monitor_loop(self, interval: float = 30.0):
        """Background watchdog: speak + push any newly-triggered alert."""
        while True:
            try:
                alerts = await asyncio.to_thread(check_monitor_rules)
                for text in alerts:
                    print(f"[Monitor] 🔔 {text}")
                    self.ui.write_log(text)
                    self.broadcast_remote({"type": "system", "text": text})
                    if self.session:
                        self.speak(text)
            except Exception as e:
                print(f"[Monitor] ⚠️ {e}")
            try:
                alerts = await asyncio.to_thread(check_guardian)
                for text in alerts:
                    print(f"[Guardian] 🔔 {text}")
                    self.ui.write_log(text)
                    self.broadcast_remote({"type": "system", "text": text})
                    from actions.notifications import notify
                    notify(parameters={"title": "PC Health", "message": text}, player=self.ui)
                    if self.session:
                        self.speak(text)
            except Exception as e:
                print(f"[Guardian] ⚠️ {e}")
            try:
                for text in await asyncio.to_thread(check_email_watch):
                    print(f"[Email] 🔔 {text}")
                    self.ui.write_log(text)
                    self.broadcast_remote({"type": "system", "text": text})
                    from actions.notifications import notify
                    notify(parameters={"title": "Kaizumi", "message": text}, player=self.ui)
                    if self.session:
                        self.speak(text)
            except Exception as e:
                print(f"[Email] ⚠️ {e}")
            await asyncio.sleep(interval)

    # ── Telegram remote-control bot ──────────────────────────────────────────

    def _telegram_context(self) -> str:
        from datetime import datetime
        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        mode, mood = _get_style_from_memory(memory)
        voice      = _get_voice_from_memory(memory)
        now        = datetime.now()
        parts = [
            "[CURRENT DATE & TIME]",
            f"Right now it is: {now.strftime('%A, %B %d, %Y — %I:%M %p')}",
            "",
            "[ASSISTANT MODE & MOOD]",
            f"Mode: {mode}  Mood: {mood}  Voice: {voice}",
            "",
        ]
        recent = self._rolling_digest(limit=1000)
        if recent:
            parts += ["[RECENT CONVERSATION]", recent, ""]
        tg_hist = self._tg_history_context(limit=900)
        if tg_hist:
            parts += [
                "[TELEGRAM CHAT HISTORY — previous exchanges with this user, "
                "use it to stay consistent]",
                tg_hist, "",
            ]
        if mem_str:
            parts.append(mem_str)
        parts.append(_load_system_prompt())
        return "\n".join(parts)

    def _tg_history_context(self, limit: int = 900) -> str:
        """Flatten the last Telegram exchanges into a prompt-able string."""
        hist = getattr(self, "_tg_history", None) or []
        if not hist:
            return ""
        lines, used = [], 0
        for role, txt in list(hist)[-8:]:
            line = f"{'User' if role == 'user' else 'Kaizumi'}: {txt}"
            if used + len(line) > limit:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    def _remember_tg_turn(self, role: str, text: str):
        if not getattr(self, "_tg_history", None):
            from collections import deque
            self._tg_history = deque(maxlen=20)
        text = (text or "").strip()[:500]
        if text:
            self._tg_history.append((role, text))

    async def _telegram_run_command(self, text: str) -> str:
        """Mini agent loop: Gemini interprets → tools run → text reply."""
        import api_keys
        from google.genai import types as gtypes
        config = gtypes.GenerateContentConfig(
            system_instruction=self._telegram_context(),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            temperature=0.4,
        )
        contents = [gtypes.Content(parts=[gtypes.Part(text=str(text))])]
        final = ""
        tool_results = []
        for _ in range(4):
            try:
                resp = await api_keys.aio_generate(
                    model=TG_MODEL, contents=contents,
                    config=config, api_version="v1beta")
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    return ("⚠️ Barcha API kalitlari limitga yetgan "
                            "(20 so'rov/kun). Yangi kalit qo'shing yoki "
                            "bir necha soatdan keyin urinib ko'ring.")
                return f"Model error: {e}"
            if resp.text:
                final = resp.text.strip()
            calls = getattr(resp, "function_calls", None)
            if not calls:
                break
            model_parts = (list(resp.candidates[0].content.parts)
                           if resp.candidates else [])
            tool_parts = []
            for fc in calls:
                name = fc.name
                args = dict(fc.args or {})
                tr = await self._dispatch_tool(name, args)
                raw = str(tr.content) if tr.ok else f"error: {tr.content}"
                if tr.ok and not str(tr.content).strip():
                    raw = f"(tool {name} returned no data)"
                result = raw[:400]
                tool_results.append(f"{name}: {result[:120]}")
                print(f"[Telegram] 🔧 {name} {args} → {str(result)[:80]}")
                tool_parts.append(gtypes.Part(
                    function_response=gtypes.FunctionResponse(
                        name=name, response={"result": result})))
            contents += [
                gtypes.Content(role="model", parts=model_parts),
                gtypes.Content(role="tool", parts=tool_parts),
            ]
        if not final:
            if tool_results:
                final = ("⚡ Bajarildi:\n• " +
                         "\n• ".join(tool_results[:6]))
            else:
                final = "Done, sir."
        return final

    async def _telegram_quick_command(self, token, chat, text: str):
        """Instant slash-commands and inline-keyboard callbacks.

        Returns (handled, result, reply_markup); result is None | str | bytes(photo)."""
        import telegram_bot as tg
        low = text.lower().strip()
        if low in ("/help", "/start", "help", "start"):
            tg.send_message(token, chat, TG_HELP_TEXT,
                            reply_markup=TG_QUICK_KEYBOARD)
            return True, None, None
        if low in ("/stop",):
            return True, None, None
        if low == "/status":
            return True, await self._telegram_status(), None
        if low == "/mute":
            if not self.ui.muted:
                self.ui.muted = True
                self.ui.set_state("MUTED")
                self.ui.write_log("SYS: Telegram: microphone muted.")
                self.ui._safe_ui(self.ui._draw_mute_button)
            return True, ("🔇 Mikrofon o'chirildi (MUTED). "
                          "Endi faqat matn/Telegram orqali gapiryapman."), None
        if low == "/unmute":
            if self.ui.muted:
                self.ui.muted = False
                self.ui.set_state("LISTENING")
                self.ui.write_log("SYS: Telegram: microphone active.")
                self.ui._safe_ui(self.ui._draw_mute_button)
            return True, "🎤 Mikrofon yoniq (LIVE). Gaplashavering.", None
        if low == "/screenshot":
            shot = await asyncio.to_thread(_take_screenshot_bytes)
            if shot:
                return True, shot, None
            return True, "📸 Screenshot olishning iloji bo'lmadi (pyautogui?).", None
        if low == "/mode" or low.startswith("/mode "):
            mode, mood = _get_style_from_memory(load_memory())
            rest = text.strip()[len("/mode"):].strip()
            if not rest:
                return True, (f"🧭 Hozirgi rejim: <b>{tg.html_escape(mode)}</b> "
                              f"(kayfiyat: {tg.html_escape(mood)})\n"
                              "Tanlang 👇"), TG_MODE_KEYBOARD
            new_mode = _normalize_mode(rest)
            if not new_mode:
                return True, ("❌ Noto'g'ri rejim. Tanlang: normal, girlfriend, "
                              "crazy_friend, butler, friend, casual."), None
            update_memory({"preferences": {"assistant_mode": {"value": new_mode}}})
            self._schedule_session_reload()
            return True, f"🔄 Rejim o'zgartirildi: <b>{tg.html_escape(new_mode)}</b>.", None
        if low == "/voice" or low.startswith("/voice "):
            current = _get_voice_from_memory(load_memory())
            rest = text.strip()[len("/voice"):].strip()
            if not rest:
                desc = "\n".join(f"• <b>{v}</b> — {VOICES[v]}" for v in VOICE_NAMES)
                return True, (f"🗣 Hozirgi ovoz: <b>{tg.html_escape(current)}</b>\n"
                              f"{desc}\nTanlang 👇"), TG_VOICE_KEYBOARD
            new_voice = _normalize_voice(rest)
            if not new_voice:
                return True, ("❌ Noto'g'ri ovoz. Tanlang: " +
                              ", ".join(VOICE_NAMES) + "."), None
            update_memory({"preferences": {"assistant_voice": {"value": new_voice}}})
            self._schedule_session_reload()
            return True, (f"🎙 Ovoz o'zgartirildi: <b>{tg.html_escape(new_voice)}</b>. "
                          "Bir necha soniyada yangi ovoz bilan ulanyapman..."), None
        return False, None, None

    async def _telegram_status(self) -> str:
        import telegram_bot as tg
        from datetime import datetime
        phase   = self._current_phase().upper()
        mode, mood = _get_style_from_memory(load_memory())
        voice   = _get_voice_from_memory(load_memory())
        clients = len(getattr(self, "remote_clients", None) or ())
        now     = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p")
        return (
            "📊 <b>Kaizumi statusi</b>\n"
            f"🕒 {tg.html_escape(now)}\n"
            f"🎙 Mikrofon: <b>{'🔇 MUTED' if self.ui.muted else '🎤 LIVE'}</b>\n"
            f"🔄 Holat: <b>{tg.html_escape(phase)}</b>\n"
            f"📱 Ulangan telefonlar: {clients}\n"
            f"🧭 Rejim: <b>{tg.html_escape(mode)}</b>  |  "
            f"Kayfiyat: <b>{tg.html_escape(mood)}</b>\n"
            f"🗣 Ovoz: <b>{tg.html_escape(voice)}</b>"
        )

    async def _telegram_handle_text(self, token, chat, text: str):
        import telegram_bot as tg
        handled, result, reply_markup = await self._telegram_quick_command(token, chat, text)
        if handled:
            if isinstance(result, bytes):
                tg.send_photo(token, chat, result,
                              caption="📸 Hozirgi ekran, sir.")
            elif result:
                tg.send_message(token, chat, result, reply_markup=reply_markup)
            return
        tg.send_typing(token, chat)
        placeholder = tg.send_message(token, chat, "⏳ ...") or {}
        msg_id = placeholder.get("message_id")
        answer = await self._telegram_run_command(text)
        safe   = tg.html_escape(answer)
        if msg_id:
            tg.edit_message(token, chat, msg_id, safe)
        else:
            tg.send_message(token, chat, safe)
        self._remember_tg_turn("user", text)
        self._remember_tg_turn("ai", answer)

    async def _telegram_handle_voice(self, token, chat, voice, caption: str = ""):
        import telegram_bot as tg
        file_id = (voice or {}).get("file_id")
        if not file_id:
            tg.send_message(token, chat, "That audio wasn't readable, sir.")
            return
        tg.send_typing(token, chat)
        placeholder = tg.send_message(token, chat, "🎧 ...") or {}
        msg_id = placeholder.get("message_id")

        def _edit(text: str):
            if msg_id:
                tg.edit_message(token, chat, msg_id, text)
            else:
                tg.send_message(token, chat, text)

        audio = await asyncio.to_thread(tg.download_file, token, file_id)
        if not audio:
            _edit("Couldn't download the voice message, sir.")
            return
        try:
            api_key = _get_api_key()
            transcript = await asyncio.to_thread(
                tg.transcribe_voice, api_key, audio)
        except Exception as e:
            _edit(f"Voice transcription failed: {tg.html_escape(str(e))}")
            return
        if not transcript:
            _edit("I couldn't hear anything, sir.")
            return
        if caption:
            transcript = caption
        _edit(f"📝 <i>Eshitildi:</i> {tg.html_escape(transcript[:300])}")
        answer = await self._telegram_run_command(transcript)
        _edit(tg.html_escape(answer))
        self._remember_tg_turn("user", transcript)
        self._remember_tg_turn("ai", answer)

    async def _telegram_loop(self):
        import telegram_bot as tg
        token = self.telegram_token
        if not token:
            return
        chat = self.telegram_chat
        if not await asyncio.to_thread(tg.ping_bot, token):
            print("[Telegram] ⚠️ Bot token rejected — check config/api_keys.json.")
            return
        offset_path = BASE_DIR / "config" / "telegram_offset.txt"

        def _load_offset() -> int:
            try:
                return int(offset_path.read_text(encoding="utf-8").strip())
            except Exception:
                return 0

        def _save_offset(off: int):
            try:
                offset_path.write_text(str(off), encoding="utf-8")
            except Exception:
                pass

        print("[Telegram] 🤖 Bot online — polling for your messages.")
        self.ui.write_log("SYS: Telegram bot online.")
        if not await asyncio.to_thread(tg.set_bot_commands, token):
            print("[Telegram] ⚠️ Could not set bot command menu.")
        offset = _load_offset()
        while True:
            try:
                for upd in await asyncio.to_thread(tg.get_updates, token, offset, 25):
                    offset = upd.get("update_id", 0) + 1
                    _save_offset(offset)
                    cbq = upd.get("callback_query")
                    msg = upd.get("message") or {}
                    if cbq:
                        cid = (cbq.get("message") or {}).get("chat", {}).get("id")
                    else:
                        cid = msg.get("chat", {}).get("id")
                    if str(cid) != str(chat):
                        continue
                    try:
                        if cbq:
                            cb_id = cbq.get("id")
                            data  = (cbq.get("data") or "").strip()
                            if cb_id:
                                tg.answer_callback(token, cb_id)
                            if data:
                                await self._telegram_handle_text(token, chat, data)
                            continue
                        text  = (msg.get("text") or "").strip()
                        voice = msg.get("voice") or msg.get("audio")
                        cap   = (msg.get("caption") or "").strip()
                        if voice:
                            await self._telegram_handle_voice(token, chat, voice, cap)
                        elif text:
                            await self._telegram_handle_text(token, chat, text)
                    except Exception as e:
                        import traceback; traceback.print_exc()
                        tg.send_message(token, chat, tg.html_escape(f"⚠️ {e}"))
            except Exception as e:
                print(f"[Telegram] ⚠️ {e}")
            await asyncio.sleep(0.5)

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            async with self._send_lock:
                await self.session.send_realtime_input(
                    audio=types.Blob(data=msg["data"], mime_type=msg["mime_type"])
                )

    async def _listen_audio(self):
        print("[KAIZUMI] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(self._safe_put_mic, data)

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[KAIZUMI] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[KAIZUMI] ❌ Mic: {e}")
            raise

    def _safe_put_mic(self, data):
        try:
            self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm"})
        except asyncio.QueueFull:
            pass

    async def _watch_speaking(self):
        while True:
            await asyncio.sleep(2)
            with self._speaking_lock:
                speaking = self._is_speaking
                last     = self._last_play_ts
            if speaking and last and time.monotonic() - last > 25:
                print("[KAIZUMI] ⏱ Speaking watchdog fired — force-cleared")
                self.set_speaking(False)

    async def _receive_audio(self):
        print("[KAIZUMI] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            self._turn_complete = True

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                self.broadcast_remote({"type": "transcript", "role": "user", "text": full_in})
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Kaizumi: {full_out}")
                                self.broadcast_remote({"type": "transcript", "role": "kaizumi", "text": full_out})
                            out_buf = []

                            self._update_rolling(full_in, full_out)

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                            # Persist a rolling summary every ~10 turns so a
                            # restart never wipes long-run context entirely.
                            with self._phase_lock:
                                n_turns = self._roll_turns
                            if n_turns >= 10:
                                self._persist_rolling_summary()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[KAIZUMI] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
                        # ── Boş turn YOK — bu "Anladım." sorununu yaratıyordu ──

        except Exception as e:
            print(f"[KAIZUMI] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[KAIZUMI] 🔊 Play started")
        loop = asyncio.get_event_loop()

        # Sürekli açık output stream — PyAudio'daki stream.write() davranışıyla aynı
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                if not self._is_speaking:
                    self.set_speaking(True)
                self._last_play_ts = time.monotonic()
                if self.remote_clients:
                    # Phone is the audio device — stream only to it, never the
                    # PC speakers too (that double-playback is what made the
                    # phone "hear itself" through the room).
                    message = bytes(chunk)
                    for ws in list(self.remote_clients):
                        try:
                            await ws.send(message)
                        except Exception as e:
                            print(f"[Play] ⚠️ remote send: {e}")
                            self.remote_clients.discard(ws)
                else:
                    await asyncio.to_thread(stream.write, chunk)
                if self.audio_in_queue.empty() and self._turn_complete:
                    self._turn_complete = False
                    self.set_speaking(False)
        except Exception as e:
            print(f"[KAIZUMI] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        bridge = None
        if self.remote_port:
            try:
                from remote_bridge import start_bridge
                bridge = await start_bridge(self, self.remote_port)
                log(f"Bridge ON (port {self.remote_port}, page + /ws)")
            except Exception as e:
                log(f"Bridge FAILED: {e}", level="ERROR")
                print(f"[Bridge] ⚠️ Could not start bridge: {e}")
                traceback.print_exc()

        tg_task = None
        if self.telegram_token:
            tg_task = asyncio.create_task(self._telegram_loop())

        try:
            while True:
                try:
                    print("[KAIZUMI] 🔌 Connecting...")
                    self.ui.set_state("THINKING")
                    self.ui.set_connecting(True)
                    config = self._build_config()

                    async with (
                        client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                        asyncio.TaskGroup() as tg,
                    ):
                        self.session        = session
                        self._loop          = asyncio.get_event_loop()
                        self._send_lock     = asyncio.Lock()
                        self.audio_in_queue = asyncio.Queue()
                        self.out_queue      = asyncio.Queue(maxsize=64)
                        self._ready         = True

                        log("Gemini session CONNECTED")
                        print("[KAIZUMI] ✅ Connected.")
                        self.ui.set_connection(True)
                        self.ui.set_persona(*self._persona_info())
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: Kaizumi online.")

                        tg.create_task(self._send_realtime())
                        tg.create_task(self._listen_audio())
                        tg.create_task(self._receive_audio())
                        tg.create_task(self._play_audio())
                        tg.create_task(self._watch_speaking())
                        tg.create_task(self._scheduler_loop())
                        tg.create_task(self._monitor_loop())

                except Exception as e:
                    log(f"Session error: {e}", level="ERROR")
                    print(f"[KAIZUMI] ⚠️ {e}")
                    traceback.print_exc()

                self._ready         = False
                self.session        = None
                self.out_queue      = None
                self.audio_in_queue = None
                self.set_speaking(False)
                self.ui.set_connection(False)
                self.ui.set_state("THINKING")
                log("Session lost — reconnecting in 3s", level="WARN")
                print("[KAIZUMI] 🔄 Reconnecting in 3s...")
                await asyncio.sleep(3)
        finally:
            if tg_task:
                try:
                    tg_task.cancel()
                except Exception:
                    pass
            if bridge:
                from remote_bridge import close_bridge
                close_bridge(bridge)


def _tk_exception_handler(exc_type, exc_value, tb):
    """Suppress the noisy 'Exception in Tkinter callback' block when the user
    presses Ctrl+C mid-draw; real errors still print normally."""
    if isinstance(exc_value, KeyboardInterrupt):
        return
    traceback.print_exception(exc_type, exc_value, tb)


def main():
    _ensure_core_deps()
    log_file = setup_logger(BASE_DIR)
    log(f"Base dir: {BASE_DIR}\nLog file: {log_file}")
    ui = JarvisUI("face.png")

    remote_port = None
    args = sys.argv[1:]
    if "--remote" in args:
        remote_port = 8765
    for i, a in enumerate(args):
        if a in ("--remote-port", "--port") and i + 1 < len(args):
            try:
                remote_port = int(args[i + 1])
            except ValueError:
                pass

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui, remote_port=remote_port)
        jarvis.attach_tray()
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.report_callback_exception = _tk_exception_handler
    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        print("\n🛑 Stopping Kaizumi (Ctrl+C)...")
        try:
            from actions.system_tray import stop as _tray_stop
            _tray_stop()
        except Exception:
            pass
        try:
            ui.root.destroy()
        except Exception:
            pass
        print("👋 Shut down cleanly. See you, sir!")


if __name__ == "__main__":
    main()
