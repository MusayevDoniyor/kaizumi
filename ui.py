import os, json, time, math, random, threading
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk, ImageDraw
import sys
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"
THEME_FILE = CONFIG_DIR / "ui_theme.json"

SYSTEM_NAME = "KAIZUMI"
MODEL_BADGE = "KAIZUMI"

# ── High-DPI awareness: crisp text on 125% / 150% laptop scaling ───────────
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ── Themes ──────────────────────────────────────────────────────────────────
# Each theme: UI colors + RGB tuples for the orb / halos.
THEMES = {
    "cyber": {
        "name": "CYBER",
        "bg": "#000000", "pri": "#00d4ff", "mid": "#007a99",
        "dim": "#003344", "dimmer": "#001520",
        "acc": "#ff6600", "acc2": "#ffcc00",
        "text": "#8ffcff", "panel": "#010c10",
        "green": "#00ff88", "red": "#ff3333", "mutcol": "#ff3366",
        "hdr": "#00080d", "input": "#000d12", "inp_border": "#003344",
        "halo": (0, 212, 255), "halo_mut": (255, 30, 80),
        "orb": (0, 65, 120), "scan2": (255, 100, 0),
    },
    "ocean": {
        "name": "OCEAN",
        "bg": "#01060f", "pri": "#38bdf8", "mid": "#0e7490",
        "dim": "#0a3a55", "dimmer": "#031a2e",
        "acc": "#f97316", "acc2": "#fde047",
        "text": "#bae6fd", "panel": "#02101c",
        "green": "#4ade80", "red": "#f87171", "mutcol": "#fb7185",
        "hdr": "#020b16", "input": "#02111f", "inp_border": "#0a3a55",
        "halo": (56, 189, 248), "halo_mut": (251, 113, 133),
        "orb": (7, 89, 133), "scan2": (251, 146, 60),
    },
    "aurora": {
        "name": "AURORA",
        "bg": "#010b07", "pri": "#4ade80", "mid": "#16a34a",
        "dim": "#0b4f2c", "dimmer": "#032316",
        "acc": "#facc15", "acc2": "#fde047",
        "text": "#bbf7d0", "panel": "#02150c",
        "green": "#4ade80", "red": "#f87171", "mutcol": "#fb7185",
        "hdr": "#02130a", "input": "#02170d", "inp_border": "#0b4f2c",
        "halo": (74, 222, 128), "halo_mut": (244, 63, 94),
        "orb": (5, 80, 45), "scan2": (250, 204, 21),
    },
    "sunset": {
        "name": "SUNSET",
        "bg": "#0d0306", "pri": "#fb923c", "mid": "#9a3412",
        "dim": "#5b1e0b", "dimmer": "#2a0d06",
        "acc": "#f472b6", "acc2": "#fde047",
        "text": "#fed7aa", "panel": "#17070a",
        "green": "#4ade80", "red": "#f87171", "mutcol": "#fb7185",
        "hdr": "#15080a", "input": "#1c0a0c", "inp_border": "#5b1e0b",
        "halo": (251, 146, 60), "halo_mut": (251, 113, 133),
        "orb": (120, 45, 20), "scan2": (253, 224, 71),
    },
}


def _load_theme_name() -> str:
    try:
        if THEME_FILE.exists():
            data = json.loads(THEME_FILE.read_text(encoding="utf-8"))
            name = str(data.get("theme", "cyber")).strip()
            if name in THEMES:
                return name
    except Exception:
        pass
    return "cyber"


def _save_theme_name(name: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        THEME_FILE.write_text(json.dumps({"theme": name}, indent=2),
                              encoding="utf-8")
    except Exception:
        pass


class KaizumiUI:
    def __init__(self, face_path, size=None):
        self.root = tk.Tk()
        self.root.title("Kaizumi")
        self.root.resizable(True, True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 1000)
        H  = min(sh, 840)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg="#000000")
        self.root.minsize(640, 480)

        self.W = W
        self.H = H

        # DPI-scaled fonts: crisp on high-DPI laptop displays
        try:
            dpi = self.root.winfo_fpixels("1i")
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        self.FACE_SZ = min(int(H * 0.40), 360)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.11) + self.FACE_SZ // 2

        # ── State ────────────────────────────────────────────────────────────
        self.speaking     = False
        self.muted        = False          # Mute flag — main.py reads it
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISING"
        self.status_blink = True

        self._state = "INITIALISING"

        self.typing_queue = deque()
        self.is_typing    = False
        self._ui_deferred = deque()
        self._main_thread = threading.current_thread()

        # Persona / connection info (updated by main.py)
        self.persona_mode  = "normal"
        self.persona_mood  = "calm"
        self.persona_voice = "Aoede"
        self.connected     = False
        self.connecting    = False
        self.last_event    = ""
        self._batt_cache   = None
        self._batt_ts      = 0.0

        self.on_text_command = None
        self.vision_mode = "STANDBY"
        self.vision_signal = "Awaiting camera input"
        self._deck_buttons = []

        self._theme = _load_theme_name()
        self.col    = dict(THEMES[self._theme])
        self.root.configure(bg=self.col["bg"])

        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        # ── Canvas (background animation) ────────────────────────────────────
        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=self.col["bg"], highlightthickness=0)
        self.bg.place(x=0, y=0)

        # ── JARVIS command deck ────────────────────────────────────────────
        # This is intentionally built from native Tk widgets so it remains
        # lightweight and works together with the existing animated canvas.
        self._build_command_deck()

        # ── Log area ─────────────────────────────────────────────────────────
        LW = max(320, W - 440) if W >= 900 else int(W * 0.72)
        LH = int(H * 0.11)
        LOG_Y = H - LH - int(H * 0.13)
        self.log_frame = tk.Frame(self.root, bg=self.col["panel"],
                                  highlightbackground=self.col["mid"],
                                  highlightthickness=1)
        self.log_frame.place(x=(W - LW) // 2, y=LOG_Y, width=LW, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=self.col["text"],
                                bg=self.col["panel"],
                                insertbackground=self.col["text"], borderwidth=0,
                                wrap="word", font=("Segoe UI", 10), padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#e8e8e8")
        self.log_text.tag_config("ai",  foreground=self.col["pri"])
        self.log_text.tag_config("sys", foreground=self.col["acc2"])
        self.log_text.tag_config("err", foreground=self.col["red"])

        # ── Keyboard input ────────────────────────────────────────────────────
        INPUT_Y = LOG_Y + LH + 6
        self._build_input_bar(LW, INPUT_Y)

        # ── Mute button ───────────────────────────────────────────────────────
        self._build_mute_button()

        # ── Hotkeys ───────────────────────────────────────────────────────────
        self.root.bind("<F4>", lambda e: self._toggle_mute())
        self.root.bind("<F5>", lambda e: self.cycle_theme())

        # Re-layout widgets when the window is resized
        self.root.bind("<Configure>", self._on_configure)
        self._relayout()

        # ── API key ───────────────────────────────────────────────────────────
        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

    # ── Theme ────────────────────────────────────────────────────────────────

    def set_theme(self, name: str):
        if name not in THEMES:
            return
        self._theme = name
        self.col    = dict(THEMES[name])
        _save_theme_name(name)
        self._safe_ui(self._apply_theme_ui)

    def cycle_theme(self):
        names = list(THEMES.keys())
        idx   = names.index(self._theme)
        self.set_theme(names[(idx + 1) % len(names)])
        self.write_log(f"SYS: Theme → {THEMES[self._theme]['name']}.")

    def _apply_theme_ui(self):
        self.root.configure(bg=self.col["bg"])
        self.bg.configure(bg=self.col["bg"])
        self.log_frame.configure(bg=self.col["panel"],
                                 highlightbackground=self.col["mid"])
        self.log_text.configure(fg=self.col["text"], bg=self.col["panel"])
        self.log_text.tag_config("ai", foreground=self.col["pri"])
        self.log_text.tag_config("sys", foreground=self.col["acc2"])
        self.log_text.tag_config("err", foreground=self.col["red"])
        self._draw_mute_button()
        self._refresh_input_style()
        self._apply_deck_theme()

    def _refresh_input_style(self):
        try:
            self._input_text.configure(fg=self.col["text"],
                                       bg=self.col["input"],
                                       insertbackground=self.col["text"],
                                       highlightbackground=self.col["inp_border"],
                                       highlightcolor=self.col["pri"])
            self._clear_btn.configure(fg=self.col["mid"],
                                      highlightbackground=self.col["mid"])
            self._send_btn.configure(fg=self.col["pri"],
                                     highlightbackground=self.col["mid"])
        except Exception:
            pass

    def _build_command_deck(self):
        """Build the live control surface around the central Kaizumi core."""
        self._left_deck = tk.Frame(self.root, bg=self.col["panel"],
                                   highlightbackground=self.col["mid"], highlightthickness=1)
        self._right_deck = tk.Frame(self.root, bg=self.col["panel"],
                                    highlightbackground=self.col["mid"], highlightthickness=1)
        self._deck_title(self._left_deck, "COMMAND DECK", self.col["pri"])
        self._deck_title(self._right_deck, "VISION DECK", self.col["acc2"])

        self._deck_label(self._left_deck, "QUICK ACTIONS")
        for label, command in [
            ("DAILY BRIEFING", "give me my daily briefing"),
            ("SYSTEM STATUS", "show system status"),
            ("READ SCREEN", "read my screen"),
            ("FOCUS MODE", "start focus mode"),
        ]:
            self._deck_button(self._left_deck, label, command)

        self._deck_label(self._right_deck, "CAMERA CONTROL")
        for label, mode in [("GESTURE CONTROL", "gesture"), ("OBJECT DETECTION", "objects"),
                            ("AIR MOUSE", "air_mouse"),
                            ("VOLUME HAND", "volume"), ("POSTURE", "posture"),
                            ("MOTION WATCH", "motion")]:
            self._deck_button(self._right_deck, label, f"start vision {mode}", mode)
        self._deck_button(self._right_deck, "STOP VISION", "stop vision", "STANDBY")
        self._deck_label(self._right_deck, "ONE-SHOT SCANS")
        for label, command in [("SNAPSHOT", "take a camera snapshot"),
                                ("FACE COUNT", "count faces in front of the camera"),
                                ("READ QR", "read a QR code with the camera")]:
            self._deck_button(self._right_deck, label, command)
        self._vision_status = tk.Label(self._right_deck, text="● STANDBY", anchor="w",
                                       bg=self.col["panel"], fg=self.col["green"],
                                       font=("Consolas", 9, "bold"))
        self._vision_status.pack(fill="x", padx=12, pady=(10, 8))
        self._deck_label(self._right_deck, "LOCAL CV MODULES")
        for text in ("HAND LANDMARKS   READY", "POSE ESTIMATION   READY", "QR / FACE SCAN   READY"):
            self._deck_label(self._right_deck, text, compact=True)
        self._vision_signal_label = tk.Label(self._right_deck, text=self.vision_signal,
                                              anchor="w", justify="left", wraplength=170,
                                              bg=self.col["panel"], fg=self.col["text"],
                                              font=("Consolas", 8))
        self._vision_signal_label.pack(fill="x", padx=12, pady=(10, 12))

    def _deck_title(self, parent, text, color):
        tk.Label(parent, text=text, anchor="w", bg=self.col["panel"], fg=color,
                 font=("Consolas", 10, "bold")).pack(fill="x", padx=12, pady=(12, 8))

    def _deck_label(self, parent, text, compact=False):
        tk.Label(parent, text=text, anchor="w", bg=self.col["panel"], fg=self.col["dim"],
                 font=("Consolas", 8 if compact else 8, "bold")).pack(fill="x", padx=12,
                 pady=(5 if compact else 10, 3))

    def _deck_button(self, parent, text, command, mode=None):
        btn = tk.Button(parent, text="▸  " + text, anchor="w", command=lambda: self._deck_command(command, mode),
                        bg=self.col["input"], fg=self.col["text"], activebackground=self.col["pri"],
                        activeforeground=self.col["bg"], relief="flat", borderwidth=0,
                        highlightthickness=1, highlightbackground=self.col["dim"],
                        font=("Consolas", 8, "bold"), cursor="hand2")
        btn.pack(fill="x", padx=10, pady=3, ipady=5)
        self._deck_buttons.append(btn)

    def _deck_command(self, command, mode=None):
        self.vision_mode = (mode or self.vision_mode).upper()
        self._safe_ui(self._refresh_deck_status)
        self.write_log("SYS: Command deck → " + command)
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(command,), daemon=True).start()

    def _refresh_deck_status(self):
        if hasattr(self, "_vision_status"):
            color = self.col["green"] if self.vision_mode != "STANDBY" else self.col["dim"]
            self._vision_status.configure(text="● " + self.vision_mode, fg=color,
                                          bg=self.col["panel"])
        if hasattr(self, "_vision_signal_label"):
            self._vision_signal_label.configure(text=self.vision_signal,
                                                bg=self.col["panel"], fg=self.col["text"])

    def set_vision_signal(self, text: str):
        """Publish the latest local CV observation to the command deck."""
        self.vision_signal = str(text or "Awaiting camera input")[:120]
        self._safe_ui(self._refresh_deck_status)

    def set_vision_detections(self, events):
        """Show a compact object summary from the active detector."""
        counts = {}
        for event in events or []:
            label = getattr(event, "label", "object")
            counts[label] = counts.get(label, 0) + 1
        if counts:
            summary = "OBJECTS: " + ", ".join(
                f"{count}× {label}" for label, count in counts.items()
            )
            self.set_vision_signal(summary)

    def _apply_deck_theme(self):
        for deck in (getattr(self, "_left_deck", None), getattr(self, "_right_deck", None)):
            if deck is not None:
                deck.configure(bg=self.col["panel"], highlightbackground=self.col["mid"])
                for widget in deck.winfo_children():
                    try:
                        widget.configure(bg=self.col["panel"])
                    except tk.TclError:
                        pass
        for btn in getattr(self, "_deck_buttons", []):
            btn.configure(bg=self.col["input"], fg=self.col["text"],
                          activebackground=self.col["pri"], activeforeground=self.col["bg"],
                          highlightbackground=self.col["dim"])
        self._refresh_deck_status()

    # ── Persona / connection (called from main.py) ───────────────────────────

    def set_persona(self, mode: str, mood: str, voice: str):
        self.persona_mode  = mode or "normal"
        self.persona_mood  = mood or "calm"
        self.persona_voice = voice or "Aoede"

    def set_connection(self, ok: bool):
        self.connected  = bool(ok)
        self.connecting = False

    def set_connecting(self, on: bool = True):
        self.connecting = bool(on)

    # ── Mute button ───────────────────────────────────────────────────────────

    def _build_mute_button(self):
        BTN_W, BTN_H = 110, 32
        BTN_X = 18
        BTN_Y = self.H - 70

        self._mute_canvas = tk.Canvas(
            self.root, width=BTN_W, height=BTN_H,
            bg=self.col["bg"], highlightthickness=0, cursor="hand2"
        )
        self._mute_canvas.place(x=BTN_X, y=BTN_Y)
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

    def _draw_mute_button(self):
        c = self._mute_canvas
        c.delete("all")
        if self.muted:
            border = self.col["mutcol"]
            fill   = "#1a0008"
            icon   = "🔇"
            label  = " MUTED"
            fg     = self.col["mutcol"]
        else:
            border = self.col["mid"]
            fill   = self.col["panel"]
            icon   = "🎙"
            label  = " LIVE"
            fg     = self.col["green"]

        c.create_rectangle(0, 0, 110, 32, outline=border, fill=fill, width=1)
        c.create_text(55, 16, text=f"{icon}{label}",
                      fill=fg, font=("Segoe UI", 10, "bold"))

    def _toggle_mute(self):
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.set_state("MUTED")
            self.write_log("SYS: Microphone muted.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: Microphone active.")

    # ── Keyboard input ────────────────────────────────────────────────────────

    def _build_input_bar(self, lw: int, y: int):
        x0    = (self.W - lw) // 2
        BTN_W = 62
        CLR_W = 62
        INP_W = lw - BTN_W - CLR_W - 8

        self._input_text = tk.Text(
            self.root,
            fg=self.col["text"], bg=self.col["input"],
            insertbackground=self.col["text"],
            borderwidth=0,
            font=("Segoe UI", 10),
            wrap="word",
            height=2,
            padx=8, pady=4,
            highlightthickness=1,
            highlightbackground=self.col["inp_border"],
            highlightcolor=self.col["pri"],
        )
        self._input_text.place(x=x0, y=y, width=INP_W, height=46)
        self._input_text.bind("<Return>", self._on_input_submit)
        self._input_text.bind("<KP_Enter>", self._on_input_submit)
        self._input_text.bind("<Shift-Return>", self._on_newline)
        self._input_text.bind("<Shift-KP_Enter>", self._on_newline)
        self._input_text.bind("<Up>", self._on_hist_prev)
        self._input_text.bind("<Down>", self._on_hist_next)

        self._cmd_history = []
        self._hist_idx    = -1
        self._draft       = ""

        self._clear_btn = tk.Button(
            self.root,
            text="CLEAR",
            command=self._on_clear_log,
            fg=self.col["mid"], bg=self.col["panel"],
            activeforeground=self.col["bg"], activebackground=self.col["acc2"],
            font=("Segoe UI", 9, "bold"),
            borderwidth=0, cursor="hand2",
            highlightthickness=1,
            highlightbackground=self.col["mid"],
        )
        self._clear_btn.place(x=x0 + INP_W + 4, y=y, width=CLR_W, height=46)

        self._send_btn = tk.Button(
            self.root,
            text="SEND ▸",
            command=self._on_input_submit,
            fg=self.col["pri"], bg=self.col["panel"],
            activeforeground=self.col["bg"], activebackground=self.col["pri"],
            font=("Segoe UI", 9, "bold"),
            borderwidth=0, cursor="hand2",
            highlightthickness=1,
            highlightbackground=self.col["mid"],
        )
        self._send_btn.place(x=x0 + INP_W + CLR_W + 8, y=y,
                             width=BTN_W, height=46)

    def _relayout(self):
        W, H = self.W, self.H
        LW = max(320, W - 440) if W >= 900 else int(W * 0.72)
        LH = int(H * 0.11)
        LOG_Y = H - LH - int(H * 0.13)
        self.log_frame.place(x=(W - LW) // 2, y=LOG_Y, width=LW, height=LH)
        INPUT_Y = LOG_Y + LH + 6
        x0    = (W - LW) // 2
        BTN_W = 62
        CLR_W = 62
        INP_W = LW - BTN_W - CLR_W - 8
        self._input_text.place(x=x0, y=INPUT_Y, width=INP_W, height=46)
        self._clear_btn.place(x=x0 + INP_W + 4, y=INPUT_Y, width=CLR_W, height=46)
        self._send_btn.place(x=x0 + INP_W + CLR_W + 8, y=INPUT_Y,
                             width=BTN_W, height=46)
        self._mute_canvas.place(x=18, y=H - 70)
        if W >= 900:
            self._left_deck.place(x=16, y=96, width=184, height=max(260, H - 210))
            self._right_deck.place(x=W - 216, y=96, width=200, height=max(260, H - 210))
        else:
            self._left_deck.place_forget()
            self._right_deck.place_forget()

    def _on_configure(self, event=None):
        if event is None or event.widget is not self.root:
            return
        if event.width == self.W and event.height == self.H:
            return
        self.W = event.width
        self.H = event.height
        self.bg.configure(width=self.W, height=self.H)
        self.FACE_SZ = min(int(self.H * 0.40), 360)
        self.FCX     = self.W // 2
        self.FCY     = int(self.H * 0.11) + self.FACE_SZ // 2
        self._relayout()

    def _get_input(self) -> str:
        return self._input_text.get("1.0", "end-1c")

    def _set_input(self, text: str):
        self._input_text.delete("1.0", tk.END)
        self._input_text.insert("1.0", text)
        self._input_text.mark_set(tk.INSERT, "end-1c")

    def _on_newline(self, event=None):
        self._input_text.insert(tk.INSERT, "\n")
        return "break"

    def _on_hist_prev(self, event=None):
        if not self._cmd_history:
            return "break"
        if self._hist_idx == -1:
            self._draft    = self._get_input()
            self._hist_idx = len(self._cmd_history)
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._set_input(self._cmd_history[self._hist_idx])
        return "break"

    def _on_hist_next(self, event=None):
        if self._hist_idx == -1:
            return "break"
        if self._hist_idx < len(self._cmd_history) - 1:
            self._hist_idx += 1
            self._set_input(self._cmd_history[self._hist_idx])
        else:
            self._hist_idx = -1
            self._set_input(self._draft)
        return "break"

    def _on_input_submit(self, event=None):
        text = self._get_input().strip()
        if not text:
            return "break"
        self._set_input("")
        self._cmd_history.append(text)
        if len(self._cmd_history) > 50:
            del self._cmd_history[0]
        self._hist_idx = -1
        self._draft    = ""
        self.write_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(
                target=self.on_text_command,
                args=(text,),
                daemon=True
            ).start()
        return "break"

    def _on_clear_log(self):
        self._safe_ui(self._clear_log)

    def _clear_log(self):
        self.typing_queue.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    # ── State management ─────────────────────────────────────────────────────

    def _safe_ui(self, fn, *args):
        """Run a UI mutation on the Tk main thread only (thread-safe)."""
        if threading.current_thread() is self._main_thread:
            return fn(*args)
        self._ui_deferred.append((fn, args))

    def set_state(self, state: str):
        self._safe_ui(self._set_state, state)

    def _set_state(self, state: str):
        """
        Called from main.py.
        state: LISTENING | SPEAKING | THINKING | MUTED | ONLINE | PROCESSING
        """
        self._state = state
        if state == "MUTED":
            self.status_text = "MUTED"
            self.speaking    = False
        elif state == "SPEAKING":
            self.status_text = "SPEAKING"
            self.speaking    = True
        elif state == "THINKING":
            self.status_text = "THINKING"
            self.speaking    = False
        elif state == "LISTENING":
            self.status_text = "LISTENING"
            self.speaking    = False
        elif state == "PROCESSING":
            self.status_text = "PROCESSING"
            self.speaking    = False
        else:
            self.status_text = "ONLINE"
            self.speaking    = False

    # ── Face loading ─────────────────────────────────────────────────────────

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    # ── Animation loop ───────────────────────────────────────────────────────

    def _animate(self):
        while self._ui_deferred:
            _fn, _args = self._ui_deferred.popleft()
            try:
                _fn(*_args)
            except Exception:
                pass
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            elif self.muted:
                self.target_scale = random.uniform(0.998, 1.001)
                self.target_halo  = random.uniform(20, 32)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        for i, spd in enumerate([1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(16, self._animate)

    # ── Battery (cached, lightweight) ─────────────────────────────────────────

    def _battery_text(self) -> str:
        now = time.time()
        if self._batt_cache is None or now - self._batt_ts > 5:
            self._batt_ts = now
            try:
                import psutil
                batt = psutil.sensors_battery()
                if batt is None:
                    self._batt_cache = None
                else:
                    self._batt_cache = int(batt.percent)
            except Exception:
                self._batt_cache = None
        if self._batt_cache is None:
            return ""
        return f"🔋 {self._batt_cache}%"

    # ── Drawing ──────────────────────────────────────────────────────────────

    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        t    = self.tick
        FCX  = self.FCX
        FCY  = self.FCY
        FW   = self.FACE_SZ
        col  = self.col
        c.delete("all")

        # Background grid
        for x in range(0, W, 44):
            for y in range(0, H, 44):
                c.create_rectangle(x, y, x+1, y+1, fill=col["dimmer"], outline="")

        # Halo rings
        halo_rgb  = col["halo_mut"] if self.muted else col["halo"]
        for r in range(int(FW * 0.54), int(FW * 0.28), -22):
            frac = 1.0 - (r - FW * 0.28) / (FW * 0.26)
            ga   = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=self._ac(*halo_rgb, ga), width=2)

        # Pulse waves
        for pr in self.pulse_r:
            pa = max(0, int(220 * (1.0 - pr / (FW * 0.72))))
            r  = int(pr)
            colr = halo_rgb if not self.muted else (255, 30, 80)
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=self._ac(*colr, pa if not self.muted else pa // 3),
                          width=2)

        # Spinning rings
        for idx, (r_frac, w_ring, arc_l, gap) in enumerate([
                (0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]):
            ring_r = int(FW * r_frac)
            base_a = self.rings_spin[idx]
            a_val  = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            rcol   = halo_rgb if not self.muted else (255, 30, 80)
            for s in range(360 // (arc_l + gap)):
                start = (base_a + s * (arc_l + gap)) % 360
                c.create_arc(FCX-ring_r, FCY-ring_r, FCX+ring_r, FCY+ring_r,
                             start=start, extent=arc_l,
                             outline=self._ac(*rcol, a_val), width=w_ring, style="arc")

        # Scan arcs
        sr      = int(FW * 0.49)
        scan_a  = min(255, int(self.halo_a * 1.4))
        arc_ext = 70 if self.speaking else 42
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan_angle, extent=arc_ext,
                     outline=self._ac(*halo_rgb, scan_a), width=3, style="arc")
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan2_angle, extent=arc_ext,
                     outline=self._ac(*col["scan2"], scan_a // 2), width=2, style="arc")

        # Ticks
        t_out = int(FW * 0.495)
        t_in  = int(FW * 0.472)
        a_mk  = self._ac(*halo_rgb, 155)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 5
            c.create_line(FCX + t_out * math.cos(rad), FCY - t_out * math.sin(rad),
                          FCX + inn  * math.cos(rad), FCY - inn  * math.sin(rad),
                          fill=a_mk, width=1)

        # Crosshair
        ch_r = int(FW * 0.50)
        gap  = int(FW * 0.15)
        ch_a = self._ac(*halo_rgb, int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - gap, FCY), (FCX + gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - gap), (FCX, FCY + gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_a, width=1)

        # Corner brackets
        blen = 22
        bc   = self._ac(*halo_rgb, 200)
        hl = FCX - FW // 2; hr = FCX + FW // 2
        ht = FCY - FW // 2; hb = FCY + FW // 2
        for bx, by, sdx, sdy in [(hl, ht, 1, 1), (hr, ht, -1, 1),
                                   (hl, hb, 1, -1), (hr, hb, -1, -1)]:
            c.create_line(bx, by, bx + sdx * blen, by,            fill=bc, width=2)
            c.create_line(bx, by, bx,               by + sdy * blen, fill=bc, width=2)

        # Face / orb
        if self._has_face:
            fw = int(FW * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.004):
                scaled = self._face_pil.resize((fw, fw), Image.BILINEAR)
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            orb_r = int(FW * 0.27 * self.scale)
            orb_color = (255, 30, 80) if self.muted else col["orb"]
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga   = max(0, min(255, int(self.halo_a * 1.1 * frac)))
                c.create_oval(FCX-r2, FCY-r2, FCX+r2, FCY+r2,
                              fill=self._ac(int(orb_color[0]*frac),
                                            int(orb_color[1]*frac),
                                            int(orb_color[2]*frac), ga),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._ac(*halo_rgb, min(255, int(self.halo_a * 2))),
                          font=("Segoe UI", 14, "bold"))

        # ── Header ────────────────────────────────────────────────────────────
        HDR = 78
        c.create_rectangle(0, 0, W, HDR, fill=col["hdr"], outline="")
        c.create_line(0, HDR, W, HDR, fill=col["mid"], width=1)
        c.create_text(W // 2, 16, text=SYSTEM_NAME,
                      fill=col["pri"], font=("Segoe UI", 15, "bold"))
        c.create_text(W // 2, 36, text="Just A Rather Very Intelligent System",
                      fill=col["mid"], font=("Segoe UI", 8))
        c.create_text(16, 16, text=MODEL_BADGE,
                      fill=col["dim"], font=("Segoe UI", 8), anchor="w")
        c.create_text(W - 16, 18, text=time.strftime("%H:%M:%S"),
                      fill=col["pri"], font=("Segoe UI", 12, "bold"), anchor="e")

        # Connection indicator (right side of header)
        if self.connecting:
            conn_txt, conn_col = "◌ CONNECTING", col["acc2"]
        elif self.connected:
            conn_txt, conn_col = "● ONLINE", col["green"]
        else:
            conn_txt, conn_col = "○ OFFLINE", col["red"]
        c.create_text(W - 16, 40, text=conn_txt, fill=conn_col,
                      font=("Segoe UI", 8, "bold"), anchor="e")

        # Persona badges (left side of header)
        badge = (f"◈ {self.persona_mode.upper()} · "
                 f"{self.persona_mood.upper()} · {self.persona_voice}")
        c.create_text(16, 40, text=badge, fill=col["acc2"],
                      font=("Segoe UI", 8, "bold"), anchor="w")

        # ── Status indicator ──────────────────────────────────────────────────
        sy = FCY + FW // 2 + 45

        if self.muted:
            stat = "⊘ MUTED"
            sc   = col["mutcol"]
        elif self.speaking:
            stat = "● SPEAKING"
            sc   = col["acc"]
        elif self._state == "THINKING":
            sym  = "◈" if self.status_blink else "◇"
            stat = f"{sym} THINKING"
            sc   = col["acc2"]
        elif self._state == "PROCESSING":
            sym  = "▷" if self.status_blink else "▶"
            stat = f"{sym} PROCESSING"
            sc   = col["acc2"]
        elif self._state == "LISTENING":
            sym  = "●" if self.status_blink else "○"
            stat = f"{sym} LISTENING"
            sc   = col["green"]
        else:
            sym  = "●" if self.status_blink else "○"
            stat = f"{sym} {self.status_text}"
            sc   = col["pri"]

        c.create_text(W // 2, sy, text=stat,
                      fill=sc, font=("Segoe UI", 11, "bold"))

        # ── Sound wave ────────────────────────────────────────────────────────
        wy = sy + 22
        N  = 32
        BH = 18
        bw = 8
        total_w = N * bw
        wx0 = (W - total_w) // 2
        for i in range(N):
            if self.muted:
                hb  = 2
                wcol = col["mutcol"]
            elif self.speaking:
                hb  = random.randint(3, BH)
                wcol = col["pri"] if hb > BH * 0.6 else col["mid"]
            else:
                hb  = int(3 + 2 * math.sin(t * 0.08 + i * 0.55))
                wcol = col["dim"]
            bx = wx0 + i * bw
            c.create_rectangle(bx, wy + BH - hb, bx + bw - 1, wy + BH,
                               fill=wcol, outline="")

        # ── Footer / status bar ───────────────────────────────────────────────
        c.create_rectangle(0, H - 40, W, H, fill=col["hdr"], outline="")
        c.create_line(0, H - 40, W, H - 40, fill=col["dim"], width=1)

        # Last system event (alerts, reminders) — center-left
        if self.last_event:
            ev = self.last_event if len(self.last_event) <= 72 else self.last_event[:69] + "..."
            c.create_text(W // 2, H - 26, text=ev, fill=col["mid"],
                          font=("Segoe UI", 8), anchor="center")

        # Battery + hints — right side
        batt = self._battery_text()
        hints = "  ".join(x for x in [batt, "[F4] MUTE", "[F5] THEME"] if x)
        c.create_text(W - 16, H - 14, text=hints, fill=col["dim"],
                      font=("Segoe UI", 8), anchor="e")

        c.create_text(16, H - 14, text=f"Kaizumi · {THEMES[self._theme]['name']}",
                      fill=col["dim"], font=("Segoe UI", 8), anchor="w")

    # ── Log ───────────────────────────────────────────────────────────────────

    def write_log(self, text: str):
        self._safe_ui(self._write_log, text)

    def _write_log(self, text: str):
        self.typing_queue.append(text)
        stripped = text
        for prefix in ("[Guardian]", "[Monitor]", "[Email]", "⏰", "SYS:"):
            if text.startswith(prefix):
                stripped = text[len(prefix):].strip(" :")
                break
        self.last_event = stripped or self.last_event
        tl = text.lower()
        if tl.startswith("you:"):
            self.set_state("PROCESSING")
        elif tl.startswith("kaizumi:") or tl.startswith("ai:"):
            self.set_state("SPEAKING")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking and not self.muted:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        if tl.startswith("you:"):
            tag = "you"
        elif tl.startswith("kaizumi:") or tl.startswith("ai:"):
            tag = "ai"
        elif tl.startswith("err:") or "error" in tl or "failed" in tl:
            tag = "err"
        else:
            tag = "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    # ── Legacy compat methods (main.py may still call them) ──────────────────

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    # ── API key ───────────────────────────────────────────────────────────────

    def _api_keys_exist(self):
        """A usable Gemini key must exist (env or config), not just the file."""
        if os.environ.get("KAIZUMI_GEMINI_API_KEY", "").strip():
            return True
        if os.environ.get("KAIZUMI_GEMINI_API_KEYS", "").strip():
            return True
        try:
            cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            return False
        if isinstance(cfg.get("gemini_api_key"), str) and cfg["gemini_api_key"].strip():
            return True
        keys = cfg.get("gemini_api_keys")
        return bool(isinstance(keys, list) and
                    any(isinstance(k, str) and k.strip() for k in keys))

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self):
        self.setup_frame = tk.Frame(
            self.root, bg=THEMES[self._theme]["hdr"],
            highlightbackground=THEMES[self._theme]["pri"], highlightthickness=1
        )
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.setup_frame, text="◈  INITIALISATION REQUIRED",
                 fg=THEMES[self._theme]["pri"], bg=THEMES[self._theme]["hdr"],
                 font=("Segoe UI", 13, "bold")).pack(pady=(18, 4))
        tk.Label(self.setup_frame,
                 text="Enter your Gemini API key to boot Kaizumi.",
                 fg=THEMES[self._theme]["mid"], bg=THEMES[self._theme]["hdr"],
                 font=("Segoe UI", 9)).pack(pady=(0, 10))

        tk.Label(self.setup_frame, text="GEMINI API KEY",
                 fg=THEMES[self._theme]["dim"], bg=THEMES[self._theme]["hdr"],
                 font=("Segoe UI", 9)).pack(pady=(8, 2))
        self.gemini_entry = tk.Entry(
            self.setup_frame, width=52, fg=THEMES[self._theme]["text"],
            bg=THEMES[self._theme]["input"],
            insertbackground=THEMES[self._theme]["text"], borderwidth=0,
            font=("Segoe UI", 10), show="*"
        )
        self.gemini_entry.pack(pady=(0, 4))

        tk.Button(
            self.setup_frame, text="▸  INITIALISE SYSTEMS",
            command=self._save_api_keys, bg=THEMES[self._theme]["bg"],
            fg=THEMES[self._theme]["pri"],
            activebackground=THEMES[self._theme]["mid"], font=("Segoe UI", 10),
            borderwidth=0, pady=8
        ).pack(pady=14)

    def _save_api_keys(self):
        gemini = self.gemini_entry.get().strip()
        if not gemini:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": gemini}, f, indent=4)
        self.setup_frame.destroy()
        self._api_key_ready = True
        self.set_state("LISTENING")
        self.write_log("SYS: Systems initialised. Kaizumi online.")
