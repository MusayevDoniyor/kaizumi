<p align="center">
  <img src="assets/banner.png" alt="Kaizumi Banner" width="100%">
</p>

<p align="center">
  <b>Your real-time, voice-driven AI companion for Windows</b><br>
  <i>It hears you. It sees your screen. It acts.</i>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-configuration">Configuration</a> •
  <a href="#-remote-control">Remote Control</a> •
  <a href="#-safety-model">Safety</a> •
  <a href="#-tools">Tools</a> •
  <a href="#-how-it-works">How it works</a> •
  <a href="#-tests">Tests</a>
</p>

---

# 🤖 Kaizumi

**Kaizumi** is a real-time, voice-driven AI assistant that lives on your Windows
computer. It can **hear** you, **see** your screen, understand context, answer
with a **natural human-like voice**, and **take action** — launching apps,
managing files, running commands, sending messages, controlling smart-home
devices, creating presentations, and much more.

Kaizumi runs **locally** on your Windows machine; AI inference and optional
integrations (Gemini, Telegram, Google, weather, flights, smart home) use
external APIs. It is **free to self-host** — you only need a Gemini API key
(free tier available at [Google AI Studio](https://aistudio.google.com/apikey)).

> 👤 **Project owner:** Musayev Doniyor ([GitHub](https://github.com/MusayevDoniyor)) · nick **Kaizo**

> ⚠️ **Security note:** This project was made public from a personal codebase.
> Before your first run, open `config/api_keys.json` and confirm it only
> contains your own keys. **Never commit that file** — it is git-ignored.

---

## ✨ Features

| Area | What Kaizumi does |
|------|-------------------|
| 🎙️ **Real-time voice** | Natural, low-latency speech-to-speech conversation in any language |
| 👁️ **Visual awareness** | Screen analysis, screenshot understanding, webcam vision, click-on-command |
| 🧠 **Persistent memory** | Remembers your name, preferences, projects, and plans across sessions |
| 🖥️ **Full PC control** | Launch apps, manage files, run terminal commands, change settings |
| 📱 **Bluetooth phone app** | Native Android app controls Kaizumi over BLE — no USB, no ADB, no website |
| 💬 **Telegram control** | Remote-control from any Telegram chat (text + voice notes) |
| 🕐 **Guardian** | Watches battery, RAM, CPU, disk, and temperature; alerts on thresholds |
| 🗓️ **Google integration** | Gmail, Calendar, Drive via OAuth (device flow) |
| 🧩 **53 tools** | Web search, reminders, PDF/Word/Excel/PowerPoint, YouTube, weather, translation, and more |
| 🎭 **Modes & moods** | 6 modes × 4 moods change Kaizumi's personality |
| 🎨 **Themed UI** | 4 themes (cyber, ocean, aurora, sunset) + animated canvas |
| 🔊 **30+ voices** | Pick from 30 Gemini voices (male/female, warm/clear/soft…) |
| 🔇 **Hotkeys** | `F4` mute, `F5` cycle theme |
| ⌨️ **Keyboard input** | Type commands in the UI instead of speaking |
| 🗓️ **In-app scheduler** | "Remind me in 10 minutes" — fires with speech + phone notification |
| 🧠 **Agent mode** | Background `agent/` planner-executor handles multi-step tasks |
| 🔒 **Safety gate** | Central risk model — HIGH-risk actions need your verbal confirmation |

---

## 📦 Requirements

- **Windows 10 / 11**
- **Python 3.11+** (tested on 3.14)
- A microphone and speakers
- Bluetooth adapter (optional — for the Android app)
- A free [Gemini API key](https://aistudio.google.com/apikey)

---

## 🚀 Quick Start

```bash
git clone https://github.com/MusayevDoniyor/kaizumi.git
cd kaizumi

python -m venv .venv
.venv\Scripts\activate

python setup.py        # installs deps, Playwright browsers, creates config files
python main.py
```

On first launch the app shows a setup dialog asking for your Gemini API key —
or configure it manually in `config/api_keys.json`:

```jsonc
// config/api_keys.json
{
    "gemini_api_key": "AIzaSy...",                          // required
    "gemini_api_keys": ["AIzaSy...", "AIzaSy..."],          // optional: multi-key rotation on 429
    "telegram_bot_token": "",                               // optional: Telegram remote control
    "telegram_chat_id": null,                               // optional: your chat id (numeric)
    "gmail_user": "",                                       // optional: Gmail address
    "gmail_app_password": "",                               // optional: Gmail app password
    "google_client_id": "",                                 // optional: Google OAuth
    "google_client_secret": ""                              // optional: Google OAuth
}
```

Secrets can also be provided as environment variables (docker/CI friendly):

| Env var | Replaces |
|---------|----------|
| `KAIZUMI_GEMINI_API_KEY` | `gemini_api_key` |
| `KAIZUMI_GEMINI_API_KEYS` | `gemini_api_keys` (comma-separated) |
| `KAIZUMI_TELEGRAM_TOKEN` | `telegram_bot_token` |
| `KAIZUMI_TELEGRAM_CHAT_ID` | `telegram_chat_id` |
| `KAIZUMI_BRIDGE_TOKEN` | Bluetooth-app token (auto-generated in `config/bridge_token.txt`) |

System ready in minutes.

---

## ⚙️ Configuration

All configuration lives in `config/`. `python setup.py` copies any
`*.example.json` to a real `.json` automatically (it never overwrites existing
files).

| File | Purpose |
|------|---------|
| `api_keys.json` | Gemini key(s), Telegram bot, Gmail, Google OAuth |
| `guardian.json` | Health-guardian thresholds (battery, RAM, CPU, disk, temp) |
| `smart_home.json` | Smart home devices (Home Assistant / webhook / simulated) |
| `bridge_token.txt` | Auto-generated access token for the Bluetooth Android app |

### Guardian thresholds (`guardian.json`)

```jsonc
{
    "enabled": true,
    "battery_low": 20,        // warn when battery drops below 20%
    "battery_full_plugged": 100,
    "disk_min_free_gb": 10,   // warn when free disk < 10 GB
    "ram_high": 90,           // warn when RAM usage > 90%
    "cpu_high": 95,           // warn when CPU usage > 95%
    "temp_high": 85,          // warn when temperature > 85°C
    "backup_days": 7,
    "cooldown": 3600          // seconds between repeated alerts
}
```

### Smart home (`smart_home.json`)

Supports **Home Assistant**, **generic webhooks**, or a **simulated** mode —
plus a per-device config (rooms, switches, lights, thermostats…).

---

## 📱 Remote Control

Kaizumi has **two** remote channels: Bluetooth (native Android app) and
Telegram. Both route commands through the **same Gemini Live session** as local
voice, so every tool, the safety gate, and memory behave identically.

### 1. Bluetooth — native Android app (no USB / no ADB / no website)

```bash
python main.py --remote
```

- Starts a BLE GATT peripheral advertising as **"Kaizumi Remote"**.
- Build & install the Android app from `android/` (see
  [`android/README.md`](android/README.md)). The build token is automatically
  generated in `config/bridge_token.txt` on first run.
- Open the app, enter the token, tap **Connect** — it pairs via the
  encrypted characteristic, authenticates, and shows *Authenticated*.
- Type a command and tap **Send** — Kaizumi replies and streams live events
  (tool status, phase changes, system alerts) to your phone.

### 2. Telegram — remote control from anywhere

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Message your new bot once (this gives you the numeric chat id), then find
   your chat id with `@userinfobot` or via `getUpdates`.
3. Put both in `config/api_keys.json`:

```jsonc
{
    "telegram_bot_token": "123456:ABC-DEF...",
    "telegram_chat_id": 123456789
}
```

Kaizumi starts polling automatically and **only responds to your chat id**.
Built-in commands: `/status`, `/mute`, `/unmute`, `/mode`, `/voice`,
`/screenshot`, `/help` — plus quick-reply keyboards. Voice notes are
transcribed on the fly.

---

## 🛡️ Safety model

Kaizumi classifies every tool into **LOW / MEDIUM / HIGH** risk (`safety.py`)
and enforces it centrally — no per-tool ad-hoc checks.

- **HIGH-risk actions** (delete/move files, run terminal commands, send
  email/SMS, kill processes, auto-update games, shutdown/restart, drive
  deletes, …) **require your explicit verbal confirmation** before they run.
- When a high-risk tool is requested, Kaizumi asks *"May I …?"* and waits for
  an explicit **yes** before re-invoking the action.
- The model is instructed to **never set `confirm=true` on its own** — only
  after you approve.
- Secrets (API keys, tokens, passwords) are **redacted from logs** and never
  written to memory.
- The Bluetooth app requires the access token (constant-time comparison);
  Telegram is locked to your chat id.
- The desktop AI sandbox blocks `ctypes`/subprocess/escalation escapes and
  obfuscated variants of dangerous calls.
- URL fetching (document/web QA) refuses loopback, private, link-local, and
  cloud-metadata targets (SSRF guard).

---

## 🧩 Tools

Kaizumi exposes **53 tools** to the model. The full list lives in `main.py`
(`_build_tool_schemas`); highlights:

| Category | Tools |
|----------|-------|
| 🖥️ **System** | `system_status`, `task_manager`, `computer_settings`, `autostart`, `clipboard`, `media_control`, `notify`, `pc_health` |
| 🗂️ **Files** | `file_controller`, `open_app`, `desktop_control`, `read_pdf`, `pdf_qa`, `read_document`, `document_qa`, `create_presentation`, `create_spreadsheet` |
| 🌐 **Web** | `web_search`, `browser_control`, `youtube_video`, `weather_report`, `flight_finder`, `translate` |
| 💬 **Communication** | `send_message`, `gmail`, `email_watch`, `calendar`, `drive`, `google_auth`, `google_auth_status` |
| 🤖 **Automation** | `cmd_control`, `code_helper`, `dev_agent`, `agent_task`, `schedule`, `daily_briefing`, `game_updater`, `smart_home_control` |
| 👁️ **Vision** | `screen_process`, `vision_gesture`, `vision_click`, `wake_word` |
| 🧠 **Memory** | `save_memory`, `recall_memory`, `forget_memory`, `clear_memory`, `set_mode`, `set_voice`, `set_mood` |
| 🔑 **Admin** | `api_add_key` |

Every tool is dispatched through a single handler table with per-tool
timeouts and a loop guard that stops identical-arg / ping-pong tool loops.

---

## 🎭 Modes, moods & voices

- **Modes:** `normal`, `girlfriend`, `crazy_friend`, `butler`, `friend`,
  `casual` — set with `set_mode` or Telegram `/mode`.
- **Moods:** `calm`, `playful`, `romantic`, `strict` — set with `set_mood`.
- **Voices:** 30 Gemini voices (Aoede, Charon, Fenrir, Kore, Puck, Zephyr,
  …) — set with `set_voice` or Telegram `/voice`. Preferences persist across
  sessions in memory.

---

## 🧠 How it works

- **Gemini Live API** (`models/gemini-3.1-flash-live-preview`) powers real-time
  speech-to-speech interaction. Voice, screen, and control code run on-device;
  speech understanding/generation and tool reasoning happen via Google's Gemini
  API.
- **Planner/executor** (`agent/`) breaks multi-step requests into tool calls,
  runs them in order, and auto-recovers: retry → skip → replan → abort.
- **Resilience layer** (`agent/resilience.py`) wraps every tool with a hard
  timeout and bounded retries — a hung tool can't freeze the session.
- **Loop guard** (`agent/loop_guard.py`) detects identical-arg / ping-pong
  tool loops in live mode.
- **Guardian** (`actions/guardian.py`) runs a background loop, watching system
  health and speaking alerts.
- **Monitor** (`actions/monitor.py`) watches user-defined rules (CPU, RAM,
  battery, disk, temperature) and pushes alerts.
- **In-app scheduler** (`main._scheduler_loop`) fires reminders with speech +
  phone notification — no Windows Task Scheduler needed.
- **Wake word** (`actions/wake_word.py`) uses openwakeword on-device for
  hands-free "Hey Kaizumi" activation (you can record your own wake word).
- **Logging** (`logger.py`) writes one log file per run under `logs/` and
  redacts secrets.

---

## 📁 Project structure

```
kaizumi/
├── main.py                    # engine: Gemini Live session, tools, scheduler
├── ui.py                      # Tkinter animated UI, setup dialog, themes
├── telegram_bot.py            # Telegram long-polling transport
├── api_keys.py                # multi-key loading + 429 auto-rotation
├── safety.py                  # central risk model + confirmation gate
├── google_oauth.py            # Google device-flow OAuth
├── setup.py                   # one-shot install + config creation
├── actions/                   # 40+ tool implementations
├── agent/                     # planner, executor, error recovery, task queue
├── memory/                    # persistent memory (CRUD, pruning, secrets)
├── remote/                    # Bluetooth BLE transport (GATT peripheral)
├── android/                   # native Android companion app (Kotlin)
├── docs/PROTOCOL.md           # Bluetooth wire protocol spec
├── config/                    # configuration (git-ignored)
└── tests/                     # unit tests (no API keys, no network)
```

---

## 🛠️ Troubleshooting

- **`1007 Request contains an invalid argument`** during a session: this
  happens when text turns are sent via `send_client_content` instead of
  `send_realtime_input`. Current code uses `send_realtime_input(text=...)` for
  in-conversation text — if you fork and see it, check your send paths.
- **Microphone not detected:** check the default input device in Windows sound
  settings.
- **Bluetooth "No bridge token":** run `python main.py --remote` once — the
  token is generated automatically in `config/bridge_token.txt`. Or set
  `KAIZUMI_BRIDGE_TOKEN` (min 16 chars).
- **`winrt` not available:** Bluetooth transport needs
  `winrt-Windows.Devices.Bluetooth.*` packages (see `requirements.txt`).
  Without them, Kaizumi runs fine — only the Bluetooth channel is disabled.
- **Voice/tool errors are spoken aloud** — read the log file in `logs/` for
  details (one file per run).
- **Slow startup:** heavy ML packages (mediapipe, openwakeword) load on first
  launch; subsequent runs are faster.

---

## 🧪 Tests

Unit tests live in `tests/` and require **no API keys and no network** —
external services (Gemini, Telegram, Google) are never called.

```bash
python -m unittest discover -s tests -v
# or
python -m pytest tests -q
```

Covered: risk classification & confirmation gate (`safety.py`), memory
CRUD/pruning/secret filtering (`memory/memory_manager.py`), log redaction
(`logger.py`), zip-slip protection (`file_controller.py`), multi-key/env
loading (`api_keys.py`), plus the P0 security fixes — SSRF guard, exec-sandbox
hardening, executor unknown-tool handling, and API-key readiness checks
(`tests/test_p0_security.py`).

---

## 📄 License

[MIT](LICENSE) © Musayev Doniyor (Kaizo)

---

<p align="center">
  Made with ❤️ by <b>Musayev Doniyor</b> (Kaizo) · Star the repo if you find it useful! ⭐
</p>