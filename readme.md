<p align="center">
  <img src="assets/banner.png" alt="Kaizumi Banner" width="100%">
</p>

# 🤖 Kaizumi

**Kaizumi** is a real-time, voice-driven AI assistant that lives on your Windows computer. It can hear you, see your screen, understand context, respond with a natural human-like voice, and take action — launching apps, managing files, running commands, sending messages, controlling smart home devices, and much more. Kaizumi runs **locally** on your Windows machine, while AI inference and optional integrations (Gemini, Telegram, Google, weather, flight search, smart home) use external APIs. **Free to self-host** — it requires a Gemini API key (free tier available from Google AI Studio).

> ⚠️ **Security note:** This project was made public from a personal codebase. Before your first run, open `config/api_keys.json` and confirm it only contains your own keys. Never commit that file.

---

## ✨ Features

- 🎙️ **Real-time voice conversation** — natural, low-latency speech in any language
- 👁️ **Visual awareness** — screen analysis and webcam understanding
- 🧠 **Persistent memory** — remembers your name, preferences, projects, and plans across sessions
- 🖥️ **Full PC control** — launch apps, manage files, run terminal commands, take screenshots
- 📱 **Phone bridge** — remote voice bridge via your phone over WebSocket
- 💬 **Telegram control** — remote-control the assistant from any Telegram chat
- 🕐 **Guardian** — watches battery, RAM, CPU, disk, and temperature; alerts you when thresholds are crossed
- 🗓️ **Google integration** — Gmail, Calendar, Drive via OAuth
- 🧩 **30+ tools** — web search, reminders, PDF reading, spreadsheets, PowerPoint, YouTube, weather, translation, and more
- 🔇 **Mute (F4)** — instantly silence the microphone
- ⌨️ **Keyboard input** — type commands in the UI instead of speaking
- 🎭 **Modes & moods** — normal, girlfriend, crazy_friend, butler, friend, casual + calm/playful/romantic/strict
- 🎨 **Themed UI** — 4 themes (cyber, ocean, aurora, sunset), toggle with F5

---

## 📦 Requirements

- **Windows 10 / 11**
- **Python 3.11+** (tested on 3.14)
- A microphone
- A free [Gemini API key](https://aistudio.google.com/apikey)
- (Optional) `cloudflared` for the public phone tunnel

---

## 🚀 Quick Start

```bash
git clone https://github.com/MusayevDoniyor/kaizumi.git
cd kaizumi

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install
python setup.py        # optional: copies config examples automatically
python main.py
```

On first launch the app will ask for your Gemini API key, or you can set it manually:

```jsonc
// config/api_keys.json
{
    "gemini_api_key": "AIzaSy...",
    "gemini_api_keys": ["AIzaSy...", "AIzaSy..."],  // optional: multiple keys (auto-rotation on 429)
    "telegram_bot_token": "",          // optional: Telegram remote control
    "telegram_chat_id": null,          // optional: your chat id (numeric)
    "gmail_user": "",                  // optional: Gmail address
    "gmail_app_password": "",          // optional: Gmail app password
    "google_client_id": "",            // optional: Google OAuth
    "google_client_secret": ""         // optional: Google OAuth
}
```

Alternatively, secrets can be provided as environment variables (useful for docker/CI):

| Env var | Replaces |
|---------|----------|
| `KAIZUMI_GEMINI_API_KEY` | `gemini_api_key` |
| `KAIZUMI_GEMINI_API_KEYS` | `gemini_api_keys` (comma-separated) |
| `KAIZUMI_TELEGRAM_TOKEN` | `telegram_bot_token` |
| `KAIZUMI_TELEGRAM_CHAT_ID` | `telegram_chat_id` |
| `KAIZUMI_BRIDGE_TOKEN` | phone-bridge token (otherwise auto-generated in `config/bridge_token.txt`) |

System ready in minutes.

---

## ⚙️ Configuration

All configuration lives in `config/`. Copy any `*.example.json` to `.json` (or run `python setup.py`) and edit.

| File | Purpose |
|------|---------|
| `api_keys.json` | Gemini API key(s), Telegram bot, Gmail, Google OAuth |
| `guardian.json` | Health-guardian thresholds (battery, RAM, CPU, disk, temp) |
| `smart_home.json` | Smart home devices (Home Assistant / webhook / simulated) |

### Remote control (optional)

- **Phone bridge:** `python main.py --remote` opens a WebSocket on port 8765. Open `remote/interface.html` on your phone, or start a tunnel:
  - `start_tunnel.cmd` — uses `cloudflared` to expose the port publicly and saves the URL to `logs/remote_url.txt`.
  - On first start a **random access token** is generated and shown in the UI (`config/bridge_token.txt`). You must enter it on the phone page — connections without it are rejected, even behind a public tunnel.
- **Telegram:** add your bot token and chat id to `config/api_keys.json`. Kaizumi starts polling automatically, and **only responds to messages from your configured chat id**.

---

## 🛡️ Safety model

Kaizumi classifies every tool into **LOW / MEDIUM / HIGH** risk (`safety.py`) and enforces it centrally — no per-tool ad-hoc checks.

- **HIGH-risk actions** (delete/move files, run terminal commands, send SMS/email, kill processes, auto-update games, shutdown/restart, drive deletes, …) **require your explicit verbal confirmation** before they run.
- When a high-risk tool is requested, Kaizumi asks *"May I …?"* and waits for an explicit yes before re-invoking the action.
- The model is instructed to **never set `confirm=true` on its own** — only after you approve.
- Secrets (API keys, tokens, passwords) are **redacted from logs and never written to memory**.
- Phone bridge requires the generated access token; Telegram is locked to your chat id.

---

## 🧠 How it works

- **Gemini Live API** (`models/gemini-3.1-flash-live-preview`) powers real-time speech-to-speech interaction. Voice, screen, and control code all run on-device; speech understanding/generation and tool reasoning happen via Google's Gemini API.
- The **planner/executor** (`agent/`) breaks multi-step requests into tool calls and runs them in order.
- The **guardian** (`actions/guardian.py`) runs a background loop, watching system health and speaking alerts.
- **Wake word** (`actions/wake_word.py`) uses openwakeword on-device for hands-free "Hey Kaizumi" activation (you can record your own).

---

## 🛠️ Troubleshooting

- **`1007 Request contains an invalid argument`** during a session: this happens when text turns are sent via `send_client_content` instead of `send_realtime_input`. Current code uses `send_realtime_input(text=...)` for in-conversation text — if you fork and see it, check your send paths.
- **Microphone not detected:** check default input device in Windows sound settings.
- **Voice/tool errors are spoken aloud** — read the log file in `logs/` for details (one file per run).

---

## 🧪 Tests

Unit tests live in `tests/` and require **no API keys and no network** — external services (Gemini, Telegram, Google) are never called. Run them with the stdlib only:

```bash
python -m unittest discover -s tests -v
```

Covered: risk classification & the confirmation gate (`safety.py`), memory CRUD/pruning/secret filtering (`memory/memory_manager.py`), log redaction (`logger.py`), zip-slip protection (`file_controller.py`), and multi-key/env loading (`api_keys.py`).

---

## 📄 License

[MIT](LICENSE)

---

Star the repo if you find it useful! ⭐