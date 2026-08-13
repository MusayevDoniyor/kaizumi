import json
import sys
import urllib.request
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = get_base_dir() / "config" / "smart_home.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "mode": "simulated",  # "home_assistant" | "webhook" | "simulated"
    "home_assistant": {
        "url": "",
        "token": ""
    },
    "webhook": {
        "url": ""
    },
    "devices": []
}

# simulated mode keeps an in-memory state map so the tool is testable offline
_SIM_STATE: dict = {}


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text("utf-8"))
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception as e:
            print(f"[SmartHome] ⚠️ Could not parse config: {e}")
    return dict(DEFAULT_CONFIG)


def _find_device(cfg: dict, key: str):
    key = (key or "").strip().lower()
    for d in cfg.get("devices", []):
        if str(d.get("id", "")).lower() == key or str(d.get("name", "")).lower() == key:
            return d
    return None


def _sim_set(device_id: str, state: dict):
    _SIM_STATE[device_id] = state


def _sim_get(device_id: str) -> dict:
    return _SIM_STATE.get(device_id, {"state": "off"})


def _ha_request(cfg: dict, method: str, path: str, body=None):
    ha = cfg.get("home_assistant", {})
    base = (ha.get("url") or "").rstrip("/")
    token = ha.get("token") or ""
    if not base or not token:
        raise RuntimeError("Home Assistant is not configured (url/token missing in config/smart_home.json).")

    req = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    if body is not None:
        req.data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def _control_home_assistant(device: dict, action: str, value):
    entity = device.get("entity") or ""
    if not entity:
        raise RuntimeError(f"Device '{device.get('name')}' has no 'entity' set.")
    domain = entity.split(".")[0] if "." in entity else "homeassistant"
    value = _coerce_value(value)

    if action == "status":
        state = _ha_request({"home_assistant": _cfg_ha_global()}, "GET", f"/api/states/{entity}")
        attrs = state.get("attributes", {})
        level = ""
        if "brightness" in attrs:
            level = f", brightness {round(attrs['brightness'] / 2.55)}%"
        elif "temperature" in attrs:
            level = f", {attrs['temperature']}°"
        return f"{device.get('name')}: {state.get('state')}{level}"

    service_map = {
        "turn_on": "turn_on",
        "turn_off": "turn_off",
        "toggle": "toggle",
        "set_level": "turn_on",
    }
    service = service_map.get(action)
    if not service:
        raise RuntimeError(f"Unknown action '{action}'.")
    body = {"entity_id": entity}
    if action == "set_level":
        body["brightness_pct"] = max(0, min(100, int(value)))
    _ha_request(_cfg_ha_global(), "POST", f"/api/services/{domain}/{service}", body)
    return f"{device.get('name')}: {action} OK"


_cfg_ha_global = lambda: _load_config().get("home_assistant", {})


def _control_webhook(cfg: dict, device: dict, action: str, value):
    url = (cfg.get("webhook", {}).get("url") or "").strip()
    if not url:
        raise RuntimeError("Webhook mode is not configured (webhook.url missing).")
    payload = {
        "device": device.get("id") or device.get("name"),
        "action": action,
        "value": value,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    return f"{device.get('name')}: {action} sent to webhook"


def _coerce_value(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value


def _list_status(cfg: dict) -> str:
    devices = cfg.get("devices", [])
    if not devices:
        return "No devices configured. Add them to config/smart_home.json"
    lines = []
    for d in devices:
        if cfg.get("mode") == "simulated":
            st = _sim_get(str(d.get("id")))
            lines.append(f"- {d.get('name')} ({d.get('type')}): {st.get('state')}")
        else:
            try:
                lines.append(f"- {d.get('name')}: {_control_home_assistant(d, 'status', None)}")
            except Exception as e:
                lines.append(f"- {d.get('name')}: error ({e})")
    return "\n".join(lines)


def smart_home_control(action: str = "status", device: str = None, value=None) -> str:
    """Public entry point called from main.py tool dispatch."""
    cfg = _load_config()

    if not cfg.get("enabled", True):
        return "Smart home is disabled in config/smart_home.json"

    action = (action or "status").strip().lower()
    mode = cfg.get("mode", "simulated")

    if action in ("status", "list", "all") and device in (None, "", "all", "all_devices"):
        return _list_status(cfg)

    dev = _find_device(cfg, device) if device else None
    if device and dev is None:
        return f"Device '{device}' not found in config/smart_home.json"
    if not dev:
        return "Please specify a device id or name."

    try:
        if mode == "home_assistant":
            return _control_home_assistant(dev, action, value)
        if mode == "webhook":
            return _control_webhook(cfg, dev, action, value)
        # simulated
        did = str(dev.get("id"))
        st = _sim_get(did)
        if action == "turn_on":
            _sim_set(did, {"state": "on", "level": _coerce_value(value) if value is not None else 100})
            return f"{dev.get('name')}: turned on"
        if action == "turn_off":
            _sim_set(did, {"state": "off"})
            return f"{dev.get('name')}: turned off"
        if action == "toggle":
            new = "on" if st.get("state") != "on" else "off"
            _sim_set(did, {"state": new, **({"level": _coerce_value(value)} if value is not None else {})})
            return f"{dev.get('name')}: toggled to {new}"
        if action == "set_level":
            _sim_set(did, {"state": "on", "level": _coerce_value(value)})
            return f"{dev.get('name')}: level set to {value}"
        return f"{dev.get('name')}: {st.get('state')}"
    except Exception as e:
        return f"Smart home error: {e}"