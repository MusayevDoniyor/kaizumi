import asyncio
import threading
import json
import sys
import os
import time
import traceback
from pathlib import Path

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


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


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


def _get_style_from_memory(memory: dict | None) -> tuple[str, str]:
    """
    Returns (mode, mood).
    Stored under preferences.assistant_mode / preferences.assistant_mood.
    """
    if not memory:
        return ("butler", "calm")

    prefs = memory.get("preferences", {}) if isinstance(memory, dict) else {}

    mode_entry = prefs.get("assistant_mode")
    mood_entry = prefs.get("assistant_mood")

    mode = mode_entry.get("value") if isinstance(mode_entry, dict) else mode_entry
    mood = mood_entry.get("value") if isinstance(mood_entry, dict) else mood_entry

    mode = (str(mode or "").strip().lower() or "butler")
    mood = (str(mood or "").strip().lower() or "calm")

    valid_modes = {"girlfriend", "friend", "butler", "casual"}
    valid_moods = {"calm", "playful", "romantic", "strict"}

    if mode not in valid_modes:
        mode = "butler"
    if mood not in valid_moods:
        mood = "calm"

    return (mode, mood)


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


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


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    jarvis_text = (jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
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
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage, zip/compress, unzip/extract archives.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info | zip | compress | unzip | extract"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
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
            "'girlfriend mode', 'friend mode', 'butler mode', 'casual mode', "
            "'be more like Batman's butler', 'switch your mode'. "
            "This persists across sessions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {
                    "type": "STRING",
                    "description": "One of: girlfriend | friend | butler | casual"
                }
            },
            "required": ["mode"]
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
]


class JarvisLive:

    def __init__(self, ui: JarvisUI, remote_port: int | None = None):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._last_play_ts  = 0.0
        self._turn_complete = False
        self.ui.on_text_command = self._on_text_command
        self.remote_clients = set()
        self.remote_port    = None

        try:
            wake_service.configure(on_detect=self._on_wake_detect)
        except Exception:
            pass

    def _on_wake_detect(self):
        """Excited when the wake word is heard — un-mute and listen (barge-in)."""
        try:
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
                        lambda: "🔇 Unmute" if self.ui.muted else "🔊 Mute (F4)",
                        _on_ui(self.ui._toggle_mute),
                    ),
                    pystray.MenuItem(
                        lambda: "😴 Stop Wake Word" if _wake_active() else "💤 Activate Wake Word",
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
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        mode, mood = _get_style_from_memory(memory)
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
            "Follow the mode/mood rules from the system prompt.\n\n"
        )

        parts = [time_ctx]
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
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

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

        # ── set_mode / set_mood: persist style across sessions ───────────────
        if name == "set_mode":
            mode = str(args.get("mode", "")).strip().lower()
            valid = {"girlfriend", "friend", "butler", "casual"}
            if mode not in valid:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": f"Invalid mode '{mode}'. Use: girlfriend, friend, butler, casual."}
                )
            update_memory({"preferences": {"assistant_mode": {"value": mode}}})
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Mode set to: {mode}."}
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

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[KAIZUMI] 📤 {name} → {str(result)[:80]}")

        # ── Result: tek cümle söyle, dur ──────────────────────────────────────
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

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
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Kaizumi: {full_out}")
                            out_buf = []

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

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
                await asyncio.to_thread(stream.write, chunk)
                self._last_play_ts = time.monotonic()
                if self.remote_clients:
                    message = bytes(chunk)
                    for ws in list(self.remote_clients):
                        try:
                            await ws.send(message)
                        except Exception as e:
                            print(f"[Play] ⚠️ remote send: {e}")
                            self.remote_clients.discard(ws)
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

        while True:
            try:
                print("[KAIZUMI] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=64)

                    print("[KAIZUMI] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: Kaizumi online.")

                    if self.remote_port:
                        from remote_bridge import start_bridge
                        tg.create_task(start_bridge(self, self.remote_port))

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._watch_speaking())

            except Exception as e:
                print(f"[KAIZUMI] ⚠️ {e}")
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[KAIZUMI] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)


def main():
    _ensure_core_deps()
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
    ui.root.mainloop()


if __name__ == "__main__":
    main()
