# actions/guardian.py
# Kaizumi — PC Health Guardian: proactive smart alerts + battery health report.
#
# Unlike monitor_alerts (user-defined threshold rules), the guardian works with
# sensible defaults out of the box and needs zero configuration:
#   - battery low (on battery)                 -> speak + toast
#   - battery full (100% while plugged)       -> unplug reminder
#   - low disk free space (system drive)       -> speak + toast
#   - high RAM / high CPU usage                -> speak + toast
#   - high CPU temperature (when available)    -> speak + toast
#   - backup overdue                          -> speak + toast
#
# The background loop in main.py calls check_guardian() every interval and
# speaks + pushes any newly-fired alert. Alerts are rate-limited per key so
# they do not spam (default cooldown 1 hour).

import json
import re
import subprocess
import sys
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


CONFIG_FILE = get_base_dir() / "config" / "guardian.json"

_DEFAULTS = {
    "enabled": True,
    "battery_low": 20,          # alert when on battery and % <= this
    "battery_full_plugged": 100,  # alert when plugged and % >= this
    "disk_min_free_gb": 10,     # alert when system drive free < this
    "ram_high": 90,             # alert when RAM usage % >= this
    "cpu_high": 95,             # alert when CPU usage % >= this
    "temp_high": 85,            # alert when CPU temp C >= this
    "backup_days": 7,           # remind when no backup for this many days
    "last_backup": None,        # epoch seconds of last confirmed backup
    "cooldown": 3600,           # seconds between repeats of the same alert
    "last_fired": {},           # key -> epoch of last fire
}

_NUM_KEYS = {
    "battery_low", "battery_full_plugged", "disk_min_free_gb",
    "ram_high", "cpu_high", "temp_high", "backup_days", "cooldown",
}
_KEYS_HELP = (
    "battery_low | battery_full_plugged | disk_min_free_gb | ram_high | "
    "cpu_high | temp_high | backup_days | cooldown"
)


def _load() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k in cfg:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def _save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Metric readers ─────────────────────────────────────────────────────────

def _battery() -> tuple[float | None, bool]:
    """Return (percent, plugged). percent None = no battery."""
    if not _PSUTIL:
        return None, False
    try:
        batt = psutil.sensors_battery()
    except Exception:
        batt = None
    if batt is None:
        return None, False
    return float(batt.percent), bool(batt.power_plugged)


def _disk_free_gb() -> float | None:
    if not _PSUTIL:
        return None
    try:
        drive = str(get_base_dir())[:3]
        return psutil.disk_usage(drive).free / 1024**3
    except Exception:
        return None


def _ram_pct() -> float | None:
    if not _PSUTIL:
        return None
    try:
        return float(psutil.virtual_memory().percent)
    except Exception:
        return None


def _cpu_pct() -> float | None:
    if not _PSUTIL:
        return None
    try:
        return float(psutil.cpu_percent(interval=0.4))
    except Exception:
        return None


def _temp_c() -> float | None:
    """CPU/board temperature when the OS exposes it (Linux sensors or WMI)."""
    if _PSUTIL:
        try:
            temps = psutil.sensors_temperatures()
            for entries in temps.values():
                for e in entries:
                    if e.current is not None and 0 <= e.current <= 110:
                        return float(e.current)
        except Exception:
            pass
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -Namespace root/wmi -ClassName "
             "MSAcpi_ThermalZoneTemperature).CurrentTemperature"],
            capture_output=True, text=True, timeout=10).stdout or ""
        vals = re.findall(r"[-+]?\d+(?:\.\d+)?", out)
        for v in vals:
            try:
                celsius = float(v) / 10.0 - 273.15
                if 0 <= celsius <= 110:
                    return round(celsius, 1)
            except Exception:
                continue
    except Exception:
        pass
    return None


def battery_health() -> str:
    """Battery wear report via `powercfg /batteryreport`. Returns a
    spoken-friendly string."""
    tmp = Path(time.strftime("kaizumi-batt-%Y%m%d-%H%M%S.html", time.localtime()))
    report = get_base_dir() / "config" / tmp.name
    try:
        subprocess.run(
            ["powercfg", "/batteryreport", "/output", str(report)],
            capture_output=True, timeout=20, check=True)
        html = report.read_text(encoding="utf-8", errors="ignore")
        design = re.findall(r"DESIGN\s+CAPACITY[^0-9]*([0-9,]+)", html, re.I)
        full   = re.findall(r"FULL\s+CHARGE\s+CAPACITY[^0-9]*([0-9,]+)", html, re.I)
        if design and full:
            d = float(design[0].replace(",", ""))
            f = float(full[0].replace(",", ""))
            if d > 0:
                pct = f / d * 100
                verdict = ("excellent" if pct >= 90 else
                           "good" if pct >= 80 else
                           "fair" if pct >= 70 else "worn out")
                return (f"Battery health is {pct:.0f} percent of design "
                        f"capacity ({verdict}).")
    except Exception:
        pass
    finally:
        try:
            report.unlink(missing_ok=True)
        except Exception:
            pass
    return ("Battery health report is unavailable on this laptop right now.")


# ── Alert checks ───────────────────────────────────────────────────────────

def _fired(cfg: dict, key: str) -> bool:
    last = cfg.get("last_fired", {}).get(key, 0)
    return (time.time() - float(last)) < float(cfg.get("cooldown", 3600))


def _mark_fired(cfg: dict, key: str) -> None:
    cfg.setdefault("last_fired", {})[key] = time.time()


def check_guardian() -> list[str]:
    """Return alert texts for newly-crossed health conditions. Called from the
    background monitor loop in main.py."""
    cfg = _load()
    if not cfg.get("enabled"):
        return []
    alerts: list[str] = []
    changed = False

    # Battery
    pct, plugged = _battery()
    if pct is not None:
        if not plugged and pct <= float(cfg.get("battery_low", 20)):
            key = "battery_low"
            if not _fired(cfg, key):
                _mark_fired(cfg, key)
                alerts.append(f"[Guardian] Battery is at {pct:.0f} percent. "
                              f"Plug in the charger soon.")
                changed = True
        if plugged and pct >= float(cfg.get("battery_full_plugged", 100)):
            key = "battery_full"
            if not _fired(cfg, key):
                _mark_fired(cfg, key)
                alerts.append(f"[Guardian] Battery is full ({pct:.0f} percent) "
                              f"and still plugged in. Unplug to protect the "
                              f"battery.")
                changed = True

    # Disk free space on the system drive
    free = _disk_free_gb()
    min_free = float(cfg.get("disk_min_free_gb", 10))
    if free is not None and free < min_free:
        key = "disk_low"
        if not _fired(cfg, key):
            _mark_fired(cfg, key)
            alerts.append(f"[Guardian] Low disk space: only {free:.1f} GB free "
                          f"on the system drive.")
            changed = True

    # RAM
    ram = _ram_pct()
    if ram is not None and ram >= float(cfg.get("ram_high", 90)):
        key = "ram_high"
        if not _fired(cfg, key):
            _mark_fired(cfg, key)
            alerts.append(f"[Guardian] High memory usage: {ram:.0f} percent of "
                          f"RAM in use.")
            changed = True

    # CPU
    cpu = _cpu_pct()
    if cpu is not None and cpu >= float(cfg.get("cpu_high", 95)):
        key = "cpu_high"
        if not _fired(cfg, key):
            _mark_fired(cfg, key)
            alerts.append(f"[Guardian] High CPU usage: {cpu:.0f} percent.")
            changed = True

    # Temperature
    temp = _temp_c()
    if temp is not None and temp >= float(cfg.get("temp_high", 85)):
        key = "temp_high"
        if not _fired(cfg, key):
            _mark_fired(cfg, key)
            alerts.append(f"[Guardian] Laptop temperature is high: {temp:.0f} "
                          f"degrees.")
            changed = True

    # Backup overdue
    last = cfg.get("last_backup")
    if last:
        days = (time.time() - float(last)) / 86400
        if days >= float(cfg.get("backup_days", 7)):
            key = "backup_due"
            if not _fired(cfg, key):
                _mark_fired(cfg, key)
                alerts.append(f"[Guardian] Last backup was {days:.0f} days ago. "
                              f"Run a backup when you can.")
                changed = True

    if changed:
        _save(cfg)
    return alerts


# ── Tool actions ───────────────────────────────────────────────────────────

def guardian_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """PC health guardian: status | report | enable | disable | set | backup |
    check | reset"""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    cfg = _load()

    if action in ("report", "health", "summary"):
        parts = []
        pct, plugged = _battery()
        if pct is None:
            parts.append("No battery detected (desktop, on AC power).")
        else:
            parts.append(f"Battery {pct:.0f} percent "
                         f"({ 'charging' if plugged else 'on battery' }).")
        parts.append(battery_health())
        free = _disk_free_gb()
        if free is not None:
            parts.append(f"{free:.1f} GB free on the system drive.")
        ram = _ram_pct()
        if ram is not None:
            parts.append(f"RAM {ram:.0f} percent used.")
        cpu = _cpu_pct()
        if cpu is not None:
            parts.append(f"CPU {cpu:.0f} percent.")
        temp = _temp_c()
        if temp is not None:
            parts.append(f"Temperature {temp:.0f} degrees.")
        return "Health report, sir. " + " ".join(parts)

    if action in ("enable", "on", "start"):
        cfg["enabled"] = True
        _save(cfg)
        return ("PC health guardian is ON, sir. I'll watch your battery, disk, "
                "memory, CPU, temperature and backups automatically.")

    if action in ("disable", "off", "stop"):
        cfg["enabled"] = False
        _save(cfg)
        return "PC health guardian is OFF, sir."

    if action in ("check", "test", "now"):
        alerts = check_guardian()
        if not alerts:
            return "All health checks look fine right now, sir."
        return " | ".join(alerts)

    if action in ("backup", "backup_done", "done"):
        cfg["last_backup"] = time.time()
        _save(cfg)
        return "Backup recorded. I'll remind you again if none happens for a while, sir."

    if action in ("set", "config"):
        key = str(params.get("key", "")).lower().strip()
        value = params.get("value")
        if key not in _NUM_KEYS:
            return f"Unknown setting '{key}', sir. Use one of: {_KEYS_HELP}."
        try:
            cfg[key] = float(value)
        except (TypeError, ValueError):
            return "Value must be a number, sir."
        _save(cfg)
        return f"Guardian setting {key} is now {cfg[key]}."

    if action in ("reset", "defaults"):
        cfg = dict(_DEFAULTS)
        _save(cfg)
        return "Guardian reset to default settings, sir."

    if action in ("status", "info"):
        state = "ON" if cfg.get("enabled") else "OFF"
        parts = [f"PC health guardian is {state}."]
        if cfg.get("enabled"):
            parts.append(f"Battery low threshold {cfg.get('battery_low')}%, "
                         f"disk below {cfg.get('disk_min_free_gb')} GB free, "
                         f"RAM above {cfg.get('ram_high')}%, CPU above "
                         f"{cfg.get('cpu_high')}%.")
        last = cfg.get("last_backup")
        if last:
            days = (time.time() - float(last)) / 86400
            parts.append(f"Last backup {days:.0f} days ago.")
        return " ".join(parts)

    return (f"Unknown action '{action}', sir. Use: status | report | enable | "
            f"disable | check | backup | set | reset.")
