# actions/monitor.py
# Kaizumi — PC monitoring alerts (CPU / RAM / battery / disk thresholds)
#
# Rules are stored in config/monitor.json. A background loop in main.py calls
# check_rules() every N seconds and speaks + pushes any newly-triggered alert
# to the connected phone.

import json
import sys
import threading
import time
from pathlib import Path

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_FILE = get_base_dir() / "config" / "monitor.json"
WATCH_FILE  = get_base_dir() / "config" / "email_watch.json"

_lock   = threading.Lock()
_rules  = None
_loaded = False

_WATCH_DEFAULT = {"enabled": False, "last_uid": 0, "interval": 120}  # interval unused (fixed loop) but kept for clarity

_DEFAULT_COOLDOWN = 300  # seconds between repeats of the same rule


def _load() -> list[dict]:
    global _rules, _loaded
    with _lock:
        if _loaded:
            return _rules
        if CONFIG_FILE.exists():
            try:
                _rules = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                _rules = []
        else:
            _rules = []
        _loaded = True
        return _rules


def _save() -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(_rules or [], indent=2), encoding="utf-8")


def _read_value(kind: str) -> tuple[float | None, str]:
    """Return (current_value, human_label). None value = unavailable."""
    if not _PSUTIL:
        return None, "psutil not installed"
    kind = kind.lower()
    try:
        if kind == "cpu":
            return psutil.cpu_percent(interval=0.4), "CPU usage"
        if kind == "ram":
            return psutil.virtual_memory().percent, "RAM usage"
        if kind == "disk":
            drive = str(get_base_dir())[:3]
            return psutil.disk_usage(drive).percent, f"Disk ({drive})"
        if kind == "battery":
            batt = psutil.sensors_battery()
            if batt is None:
                return None, "Battery"
            return float(batt.percent), "Battery"
    except Exception:
        pass
    return None, kind.title()


def add_rule(kind: str, threshold: float, above: bool = True,
             message: str = "") -> str:
    rules = _load()
    kind = kind.lower()
    if kind not in ("cpu", "ram", "disk", "battery"):
        return f"Unknown metric '{kind}'. Use: cpu | ram | disk | battery."
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return "Threshold must be a number."

    with _lock:
        rid = max([r.get("id", 0) for r in rules] or [0]) + 1
        rules.append({
            "id": rid, "kind": kind, "threshold": threshold,
            "above": bool(above), "message": message,
            "last_fired": 0,
        })
        _save()
    cmp = "above" if above else "below"
    return (f"Alert added (ID {rid}): warn me when {kind} goes {cmp} "
            f"{threshold}%.")


def remove_rule(rid: int) -> str:
    rules = _load()
    before = len(rules)
    rules[:] = [r for r in rules if r.get("id") != rid]
    if len(rules) == before:
        return f"No alert with ID {rid}, sir."
    _save()
    return f"Alert ID {rid} removed, sir."


def list_rules() -> str:
    rules = _load()
    if not rules:
        return ("No monitoring alerts are set, sir. Say 'alert me when CPU goes "
                "above 90 percent' or use monitor_alerts add.")
    lines = []
    for r in rules:
        cmp = "above" if r.get("above") else "below"
        msg = f" — {r['message']}" if r.get("message") else ""
        lines.append(f"ID {r['id']}: {r['kind']} {cmp} {r['threshold']}%{msg}")
    return "Monitoring alerts:\n" + "\n".join(lines)


def check_rules(cooldown: float = _DEFAULT_COOLDOWN) -> list[str]:
    """Return alert texts for rules that just crossed their threshold."""
    rules = _load()
    alerts = []
    now = time.time()
    for r in rules:
        value, label = _read_value(r.get("kind", ""))
        if value is None:
            continue
        above = bool(r.get("above", True))
        hit = value > r.get("threshold", 100) if above else value < r.get("threshold", 0)
        if not hit:
            continue
        if now - float(r.get("last_fired", 0)) < cooldown:
            continue
        r["last_fired"] = now
        msg = r.get("message") or (
            f"{label} is {'above' if above else 'below'} {r['threshold']}% "
            f"right now ({value:.0f}%).")
        alerts.append(f"[Monitor] {msg} (ID {r['id']})")
    if alerts:
        with _lock:
            _save()
    return alerts


def monitor_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Monitoring alert rules: list | add | remove | status | check"""
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    kind   = str(params.get("kind", "")).lower()
    above  = str(params.get("above", "true")).lower() not in ("false", "0", "no", "below")
    threshold = params.get("threshold")

    if action in ("list", "show"):
        return list_rules()

    if action in ("add", "create", "set"):
        if not kind:
            return ("I need a metric, sir: cpu, ram, disk, or battery.")
        if threshold is None:
            return ("I need a threshold, sir — e.g. 'alert me when cpu is above 90'.")
        msg = str(params.get("message", "")).strip()
        return add_rule(kind, threshold, above, msg)

    if action in ("remove", "delete", "cancel"):
        try:
            rid = int(params.get("id", 0))
        except (TypeError, ValueError):
            return "I need the alert ID to remove, sir."
        return remove_rule(rid)

    if action in ("check", "test", "now"):
        alerts = check_rules(cooldown=0)
        if not alerts:
            return "Nothing is crossing any threshold right now, sir."
        return " | ".join(alerts)

    if action in ("status", "info"):
        rules = _load()
        if not rules:
            return ("Monitoring is on but no alerts are set, sir. "
                    "Say 'alert me when ram is above 85'.")
        return f"Monitoring is on with {len(rules)} alert rule(s)."

    return f"Unknown action '{action}', sir. Use: list | add | remove | check | status."


# ── Gmail new-mail watcher ────────────────────────────────────────────────────

def _watch_state() -> dict:
    if WATCH_FILE.exists():
        try:
            return json.loads(WATCH_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"enabled": False, "last_uid": 0}


def _save_watch(state: dict) -> None:
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def email_watch_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Gmail new-mail watcher: enable | disable | status"""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()

    cfg = json.loads((get_base_dir() / "config" / "api_keys.json").read_text(
        encoding="utf-8")) if (get_base_dir() / "config" / "api_keys.json").exists() else {}
    if not (cfg.get("gmail_user") and cfg.get("gmail_app_password")):
        return ("Email watching needs Gmail configured, sir: save 'gmail_user' "
                "and 'gmail_app_password' in config/api_keys.json.")

    state = _watch_state()

    if action in ("enable", "on", "start"):
        state["enabled"] = True
        _save_watch(state)
        return ("Email watching enabled, sir. I'll alert you when new mail "
                "arrives in your inbox.")

    if action in ("disable", "off", "stop"):
        state["enabled"] = False
        _save_watch(state)
        return "Email watching disabled, sir."

    if action in ("status", "info"):
        return ("Email watching is " + ("ON" if state.get("enabled") else "OFF")
                + f" (last seen UID {state.get('last_uid', 0)}).")

    return f"Unknown email_watch action '{action}', sir. Use enable | disable | status."


def check_email_watch() -> list[str]:
    """Poll Gmail for UIDs newer than the last seen one. Returns alert texts."""
    state = _watch_state()
    if not state.get("enabled"):
        return []

    cfg_path = get_base_dir() / "config" / "api_keys.json"
    if not cfg_path.exists():
        return []
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    user = (cfg.get("gmail_user") or "").strip()
    pwd  = (cfg.get("gmail_app_password") or "").strip()
    if not (user and pwd):
        return []

    try:
        import imaplib
        import email as email_mod
        from email.header import decode_header

        def _dec(s: str) -> str:
            if not s:
                return ""
            try:
                parts = decode_header(s)
            except Exception:
                return str(s)
            out = []
            for t, enc in parts:
                if isinstance(t, bytes):
                    try:
                        t = t.decode(enc or "utf-8", errors="replace")
                    except Exception:
                        t = t.decode("utf-8", errors="replace")
                out.append(str(t))
            return "".join(out)

        with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30) as conn:
            conn.login(user, pwd)
            conn.select("INBOX")
            typ, data = conn.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return []
            uids = [int(u) for u in data[0].split()]
            if not uids:
                return []
            max_uid = max(uids)
            last = int(state.get("last_uid", 0))
            new = [u for u in uids if u > last][-5:]
            state["last_uid"] = max_uid
            _save_watch(state)
            if not new:
                return []

            alerts = []
            for uid in new:
                try:
                    typ2, msg_data = conn.uid("fetch", str(uid).encode(),
                                              "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                    if typ2 != "OK" or not msg_data:
                        continue
                    raw = msg_data[0][1]
                    msg = email_mod.message_from_bytes(raw)
                    frm  = _dec(msg.get("From", "?"))
                    subj = _dec(msg.get("Subject", "(no subject)"))
                    name = frm.split("<")[0].strip().rstrip(",") or frm
                    alerts.append(f"[Email] New mail from {name}: {subj}")
                except Exception:
                    continue
            return alerts
    except Exception:
        return []
