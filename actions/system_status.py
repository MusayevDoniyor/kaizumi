# actions/system_status.py
# Kaizumi — System Health & Status Reporting (battery, CPU, RAM, disk, network, processes)

import time
import platform
import socket
import subprocess

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


def _boot_time() -> str:
    try:
        bt = psutil.boot_time()
        up = int(time.time() - bt)
        days, rem = divmod(up, 86400)
        hrs, rem = divmod(rem, 3600)
        mins = rem // 60
        return f"{days}d {hrs}h {mins}m"
    except Exception:
        return "unknown"


def _battery() -> str:
    if not hasattr(psutil, "sensors_battery"):
        return "Battery info not available."
    try:
        batt = psutil.sensors_battery()
    except Exception:
        batt = None
    if batt is None:
        return "No battery detected (desktop, likely on AC power)."
    pct  = int(batt.percent)
    plug = "charging" if batt.power_plugged else "on battery"
    secs = ""
    if batt.secsleft is not None and batt.secsleft >= 0 and not batt.power_plugged:
        secs = f" (~{int(batt.secsleft // 60)} min left)"
    return f"{pct}% ({plug}){secs}"


def _cpu() -> str:
    try:
        per = psutil.cpu_percent(interval=0.4)
        freq = ""
        try:
            f = psutil.cpu_freq()
            if f:
                freq = f", {int(f.current)} MHz"
        except Exception:
            pass
        return f"{per}% usage, {psutil.cpu_count()} cores{freq}"
    except Exception:
        return "unavailable"


def _memory() -> str:
    try:
        mem = psutil.virtual_memory()
        used_gb = mem.used / 1024**3
        tot_gb  = mem.total / 1024**3
        return f"{mem.percent}% used ({used_gb:.1f}/{tot_gb:.1f} GB)"
    except Exception:
        return "unavailable"


def _disk() -> str:
    parts = []
    try:
        for part in psutil.disk_partitions(all=False):
            if not part.fstype or part.fstype in ("cdrom",):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                parts.append(f"{part.mountpoint}: {usage.percent}% ({usage.free/1024**3:.0f} GB free)")
            except Exception:
                continue
    except Exception:
        return "unavailable"
    return "; ".join(parts) if parts else "unavailable"


def _network() -> str:
    lines = []
    try:
        addrs = psutil.net_if_addrs()
        for iface, entries in addrs.items():
            for e in entries:
                if e.family == socket.AF_INET and not e.address.startswith("127."):
                    lines.append(f"{iface}: {e.address}")
        stats = psutil.net_if_stats()
        down = [name for name, s in stats.items() if s.isup]
        if down:
            lines.append(f"Active: {', '.join(down[:5])}")
    except Exception:
        pass
    return "; ".join(lines) if lines else "unknown"


def _top_processes(n: int = 5) -> str:
    items = []
    try:
        for proc in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                items.append((proc.info["cpu_percent"] or 0, proc.info["name"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        items.sort(reverse=True)
        top = [name for _, name in items[:n] if name]
        return ", ".join(top)
    except Exception:
        return "unavailable"


def system_status(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Report system health. `focus` can be: overview | battery | cpu | memory | disk | network | processes."""
    if not _PSUTIL:
        return "psutil is not installed. Run: pip install psutil"

    params = parameters or {}
    focus  = str(params.get("focus") or params.get("query") or "").lower().strip()

    if "battery" in focus or "power" in focus:
        return f"Battery: {_battery()}."
    if "cpu" in focus or "processor" in focus:
        return f"CPU: {_cpu()}."
    if "memory" in focus or "ram" in focus:
        return f"Memory: {_memory()}."
    if "disk" in focus or "storage" in focus or "drive" in focus:
        return f"Disk: {_disk()}."
    if "network" in focus or "wifi" in focus or "internet" in focus or "ip" in focus:
        return f"Network: {_network()}."
    if "process" in focus or "running" in focus or "task" in focus:
        return f"Top processes: {_top_processes()}."
    if "uptime" in focus or "on since" in focus or "how long" in focus:
        return f"System uptime: {_boot_time()}."

    report = (
        f"System status, sir. Battery: {_battery()}. "
        f"CPU: {_cpu()}. Memory: {_memory()}. "
        f"Disk: {_disk()}. Network: {_network()}. "
        f"Uptime: {_boot_time()}. Top processes: {_top_processes()}."
    )
    return report
