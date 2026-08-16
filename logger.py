import sys
from datetime import datetime
from pathlib import Path


_LOGFILE = None
_PRIMARY_OUT = None
_PRIMARY_ERR = None


class _Tee:
    def __init__(self, primary, mirror):
        self._p = primary
        self._m = mirror

    def write(self, data):
        try:
            self._p.write(data)
        except Exception:
            pass
        try:
            self._m.write(data)
        except Exception:
            pass
        return len(data)

    def flush(self):
        for s in (self._p, self._m):
            try:
                s.flush()
            except Exception:
                pass

    def fileno(self):
        try:
            return self._p.fileno()
        except Exception:
            return -1


class _FileMirror:
    def __init__(self, path):
        self._f = path.open("a", encoding="utf-8", errors="replace")
        self._path = path

    def write(self, data):
        if self._f.closed:
            return len(data)
        self._f.write(data)
        self._f.flush()
        return len(data)

    def flush(self):
        try:
            self._f.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass


def setup_logger(base_dir) -> Path:
    global _LOGFILE, _PRIMARY_OUT, _PRIMARY_ERR

    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"kaizumi-{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

    _LOGFILE = _FileMirror(log_file)

    _PRIMARY_OUT = sys.stdout or open("nul", "w")
    _PRIMARY_ERR = sys.stderr or _PRIMARY_OUT

    sys.stdout = _Tee(_PRIMARY_OUT, _LOGFILE)
    sys.stderr = _Tee(_PRIMARY_ERR, _LOGFILE)

    log("=" * 60)
    log(f"Kaizumi started — log file: {log_file}")
    log(f"Python {sys.version.split()[0]} | running from {Path(base_dir)}")
    log("=" * 60)
    return log_file


def log(msg, level="INFO"):
    try:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}")
    except Exception:
        try:
            if _LOGFILE is not None:
                _LOGFILE.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}\n")
        except Exception:
            pass


def log_tool(name, args, result=None, error=None):
    safe = _redact(args)
    summary = " ".join(str(v) for v in safe.values())[:200]
    line = f"ACTION  tool={name}  args={summary}"
    if error is not None:
        line += f"  => ERROR: {error}"
    elif result is not None:
        line += f"  => {str(result)[:200]}"
    log(line, level="INFO")


# Keys whose values are masked in logs (defense-in-depth: even callers that
# forget to sanitize cannot leak secrets through the log file).
_REDACT_KEYS = frozenset({
    "api_key", "api_key_id", "apikey", "token", "access_token", "auth_token",
    "password", "passwd", "secret", "client_secret", "key",
})


def _redact(value, depth=0):
    if depth > 3:
        return value
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _REDACT_KEYS
                or "token" in str(k).lower() or "secret" in str(k).lower()
                else _redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value]
    return value