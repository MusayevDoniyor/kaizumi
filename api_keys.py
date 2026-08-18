"""Multi-key Gemini API rotation.

Reads all configured API keys (legacy `gemini_api_key` + new list
`gemini_api_keys`) from config/api_keys.json. When a key hits the free-tier
daily quota (429 RESOURCE_EXHAUSTED), it is marked exhausted with a cooldown
and the next configured key is tried automatically. Keys recover once the
cooldown expires (daily quota resets), so old keys keep working again later.
"""
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_PATH = get_base_dir() / "config" / "api_keys.json"
STATE_PATH  = get_base_dir() / "config" / "api_key_state.json"

# Free-tier daily quota resets ~midnight; 8h cooldown is a safe approximation.
RESET_COOLDOWN = 8 * 3600

_lock  = threading.Lock()
_state = None  # {key_hash: {"until": ts}}
_pos   = 0


def _hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _load_state() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _state = {}
    return _state


def _save_state() -> None:
    try:
        tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def get_all_keys() -> list:
    keys = []
    # Environment variables first (dev / CI / docker friendly).
    env_key = os.environ.get("KAIZUMI_GEMINI_API_KEY", "").strip()
    env_keys = os.environ.get("KAIZUMI_GEMINI_API_KEYS", "").strip()
    if env_key:
        keys.append(env_key)
    if env_keys:
        keys.extend(k.strip() for k in env_keys.split(",") if k.strip())
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    lst = cfg.get("gemini_api_keys")
    if isinstance(lst, list):
        keys.extend(k for k in lst if isinstance(k, str) and k.strip())
    single = cfg.get("gemini_api_key")
    if isinstance(single, str) and single.strip():
        keys.insert(0, single)
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def mark_exhausted(key: str) -> None:
    if not key:
        return
    with _lock:
        st = _load_state()
        st[_hash(key)] = {"until": time.time() + RESET_COOLDOWN}
        _save_state()


def next_key() -> str:
    """Return the next available key, preferring ones not in cooldown."""
    global _pos
    with _lock:
        keys = get_all_keys()
        if not keys:
            raise KeyError("gemini_api_key not configured in config/api_keys.json")
        st = _load_state()
        now = time.time()
        n   = len(keys)
        pos = _pos % n
        for i in range(n):
            k = keys[(pos + i) % n]
            entry = st.get(_hash(k))
            if not entry or entry.get("until", 0) <= now:
                _pos = (pos + i + 1) % n
                return k
        # All keys in cooldown — force a retry on the next one (may have recovered).
        k = keys[pos]
        _pos = (pos + 1) % n
        st.pop(_hash(k), None)
        _save_state()
        return k


def _is_quota_error(e) -> bool:
    msg = str(e)
    return ("429" in msg) or ("RESOURCE_EXHAUSTED" in msg)


def add_key(key: str) -> int:
    key = (key or "").strip()
    if not key:
        raise ValueError("Empty API key.")
    if not key.startswith("AIza"):
        raise ValueError("That doesn't look like a Gemini API key (should start with 'AIza').")
    with _lock:
        cfg = {}
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        keys = cfg.get("gemini_api_keys")
        if not isinstance(keys, list):
            keys = []
        if key not in keys:
            keys.append(key)
        cfg["gemini_api_keys"] = keys
        if not cfg.get("gemini_api_key"):
            cfg["gemini_api_key"] = key
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(keys)


async def aio_generate(model, contents, config=None, api_version=None):
    """Generate content, automatically retrying across all keys on 429."""
    from google import genai

    keys = get_all_keys()
    last_err = None
    for k in keys:
        try:
            kwargs = {}
            if api_version:
                kwargs["http_options"] = {"api_version": api_version}
            client = genai.Client(api_key=k, **kwargs)
            resp = await client.aio.models.generate_content(
                model=model, contents=contents, config=config)
            return resp
        except Exception as e:
            if _is_quota_error(e):
                mark_exhausted(k)
                last_err = e
                continue
            raise
    if last_err is None:
        raise KeyError("No Gemini API keys configured — add one in config/api_keys.json")
    raise last_err


def generate_with_retry(model, contents, config=None, api_version=None):
    """Sync version of aio_generate (for transcribe_voice and legacy modules)."""
    from google import genai

    keys = get_all_keys()
    last_err = None
    for k in keys:
        try:
            kwargs = {}
            if api_version:
                kwargs["http_options"] = {"api_version": api_version}
            client = genai.Client(api_key=k, **kwargs)
            resp = client.models.generate_content(
                model=model, contents=contents, config=config)
            return resp
        except Exception as e:
            if _is_quota_error(e):
                mark_exhausted(k)
                last_err = e
                continue
            raise
    if last_err is None:
        raise KeyError("No Gemini API keys configured — add one in config/api_keys.json")
    raise last_err
