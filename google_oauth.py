"""Google OAuth2 via Device Flow.

The user pastes `google_client_id` + `google_client_secret` (from a Google
Cloud "Desktop app" OAuth client) into config/api_keys.json. Then:

  auth_start()     -> returns a device-code URL + user code (for the phone)
  auth_poll(code)  -> polls the token endpoint until the user authorizes
  get_credentials()-> cached google.oauth2.credentials.Credentials (auto-refresh)

Access & refresh tokens are saved in config/google_token.json.
"""
import json
import sys
import time
from pathlib import Path

import requests

import google.auth.transport.requests as gtr
from google.oauth2 import credentials as gcreds

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
]

TOKEN_URI    = "https://oauth2.googleapis.com/token"
DEVICE_URI   = "https://oauth2.googleapis.com/device/code"
USER_URI     = "https://www.googleapis.com/oauth2/v2/userinfo"
AUTH_URI     = "https://accounts.google.com/o/oauth2/v2/auth"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_PATH = get_base_dir() / "config" / "api_keys.json"
TOKEN_PATH  = get_base_dir() / "config" / "google_token.json"

_cached = None


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_token() -> dict:
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_token(tok: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def client_ids() -> tuple:
    cfg = _load_config()
    cid = (cfg.get("google_client_id") or "").strip()
    sec = (cfg.get("google_client_secret") or "").strip()
    return cid, sec


def is_configured() -> bool:
    cid, sec = client_ids()
    return bool(cid and sec)


def has_token() -> bool:
    return bool(_load_token().get("refresh_token"))


_PAGE = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kaizumi</title>
<style>
  body { margin:0; font-family:'Segoe UI',Arial,sans-serif;
         background:radial-gradient(1200px 600px at 50% -100px,#2b1e4e,#0e0f1a 70%); }
  .card { max-width:420px; margin:12vh auto 0; padding:40px 36px; text-align:center;
          background:#161827; border:1px solid #2a2c4a; border-radius:20px;
          box-shadow:0 20px 60px rgba(0,0,0,.5); color:#eef0ff; }
  .badge { width:84px; height:84px; margin:0 auto 20px; border-radius:50%;
           background:#1dbf73; color:#fff; font-size:44px; line-height:84px;
           box-shadow:0 0 0 12px rgba(29,191,115,.15), 0 8px 30px rgba(29,191,115,.4); }
  h1 { font-size:22px; margin:0 0 10px; }
  p  { color:#a7abcf; font-size:14px; line-height:1.6; margin:6px 0; }
  .mono { color:#8f95c9; font-size:12px; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%;
         background:#1dbf73; margin-right:6px; }
</style>
</head>
<body>
  <div class="card">
    <div class="badge">&#10003;</div>
    <h1>%TITLE%</h1>
    <p>%SUBTEXT%</p>
    <p class="mono"><span class="dot"></span>Bu oynani endi yopishingiz mumkin</p>
  </div>
</body>
</html>"""


def _result_page(ok: bool) -> bytes:
    if ok:
        title   = "Kaizumi ulandi!"
        subtext = ("Google hisobingiz muvaffaqiyatli bog&#8216;landi. "
                   "Endi Telegram orqali email, kalendar va Drive "
                   "buyruqlarini bera olasiz.")
    else:
        title   = "Avtorizatsiya amalga oshmadi"
        subtext = ("Ro&#8216;yxatga qayting va qaytadan urinib ko&#8216;ring. "
                   "Agar xato davom etsa, Kaizumi jurnalini tekshiring.")
    return _PAGE.replace("%TITLE%", title).replace("%SUBTEXT%", subtext).encode("utf-8")


def auth_browser(timeout_seconds: int = 240) -> dict:
    """Standard consent flow: opens the default browser on the PC.

    Works for Desktop-app OAuth clients (local redirect). The user authorizes
    in the browser, the flow saves the token and returns the account email.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    cid, sec = client_ids()
    if not cid or not sec:
        return {"ok": False, "error": "google_client_id/secret not configured."}
    client_config = {
        "installed": {
            "client_id":     cid,
            "client_secret": sec,
            "auth_uri":      AUTH_URI,
            "token_uri":     TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    try:
        creds = flow.run_local_server(
            host="localhost", port=0,
            open_browser=True,
            success_message="Kaizumi ulandi! Bu oynani yopishingiz mumkin. ✅",
        )
    except TypeError:
        creds = flow.run_local_server(
            host="localhost", port=0, open_browser=True,
        )
    tok = {
        "client_id":     cid,
        "client_secret": sec,
        "refresh_token": creds.refresh_token,
        "token":         creds.token,
        "scopes":        " ".join(creds.scopes),
    }
    _save_token(tok)
    email = email_address()
    return {"ok": True, "email": email}


def auth_browser_nopkce(port: int = 8787, timeout_seconds: int = 300) -> dict:
    """Consent flow WITHOUT PKCE, using a fixed localhost server.

    The classic code flow works reliably even for clients where the device
    flow is rejected. Opens the default browser; token is saved on success.
    """
    from urllib.parse import urlencode, parse_qs, urlparse
    import http.server, threading, webbrowser, secrets

    cid, sec = client_ids()
    if not cid or not sec:
        return {"ok": False, "error": "google_client_id/secret not configured."}

    redirect = f"http://localhost:{port}/"
    state = secrets.token_urlsafe(16)
    auth_url = (AUTH_URI + "?" + urlencode({
        "client_id":      cid,
        "redirect_uri":   redirect,
        "response_type":  "code",
        "scope":          " ".join(SCOPES),
        "access_type":    "offline",
        "prompt":         "consent",
        "state":          state,
    }))

    result = {"code": None, "state": state}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("state") == [result["state"]] and qs.get("code"):
                result["code"] = qs["code"][0]
                body = _result_page(ok=True)
            else:
                body = _result_page(ok=False)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    webbrowser.open(auth_url)
    import time
    deadline = time.time() + timeout_seconds
    while time.time() < deadline and not result["code"]:
        time.sleep(1)
    server.shutdown()

    if not result["code"]:
        return {"ok": False, "error": "timed out waiting for authorization."}

    resp = requests.post(TOKEN_URI, data={
        "client_id":     cid,
        "client_secret": sec,
        "code":          result["code"],
        "grant_type":    "authorization_code",
        "redirect_uri":  redirect,
    }, timeout=30)
    data = resp.json()
    if resp.status_code != 200:
        return {"ok": False, "error": f"token exchange failed: {data.get('error', resp.text[:200])}"}
    tok = {
        "client_id":     cid,
        "client_secret": sec,
        "refresh_token": data.get("refresh_token"),
        "token":         data.get("access_token"),
        "scopes":        data.get("scope", " ".join(SCOPES)),
    }
    _save_token(tok)
    return {"ok": True, "email": email_address()}


def auth_start() -> dict:
    """Start device flow; returns URL + user code + device_code + poll info."""
    cid, _ = client_ids()
    if not cid:
        return {"ok": False, "error": "google_client_id is not set in config/api_keys.json."}
    resp = requests.post(DEVICE_URI, data={
        "client_id": cid,
        "scope": " ".join(SCOPES),
    }, timeout=30)
    if resp.status_code != 200:
        return {"ok": False, "error": f"device/code failed: {resp.text[:300]}"}
    data = resp.json()
    data["ok"] = True
    return data


def auth_poll(device_code: str, interval: int = 5, timeout: int = 300) -> dict:
    """Poll the token endpoint until the user authorizes (or timeouts)."""
    cid, sec = client_ids()
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.post(TOKEN_URI, data={
            "client_id":     cid,
            "client_secret": sec,
            "device_code":   device_code,
            "grant_type":    "urn:ietf:params:oauth:grant-type:device_code",
        }, timeout=30)
        data = resp.json()
        if resp.status_code == 200:
            tok = {
                "client_id":      cid,
                "client_secret":  sec,
                "refresh_token":  data.get("refresh_token"),
                "token":          data.get("access_token"),
                "scopes":         data.get("scope", " ".join(SCOPES)),
            }
            if not tok["refresh_token"]:
                # token endpoint usually omits refresh_token for offline? keep anyway
                pass
            _save_token(tok)
            email = _fetch_email(data.get("access_token"))
            return {"ok": True, "email": email}
        if data.get("error") not in ("authorization_pending", "slow_down"):
            return {"ok": False, "error": f"token error: {data.get('error', resp.text[:200])}"}
        time.sleep(interval)
    return {"ok": False, "error": "timed out waiting for authorization."}


def _fetch_email(access_token: str) -> str | None:
    try:
        r = requests.get(USER_URI, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
        if r.status_code == 200:
            return r.json().get("email")
    except Exception:
        pass
    return None


def get_credentials(force_refresh: bool = False):
    """Return a working Credentials object, or None if not authorized."""
    global _cached
    tok = _load_token()
    refresh = tok.get("refresh_token")
    cid     = tok.get("client_id")
    sec     = tok.get("client_secret")
    if not refresh or not cid or not sec:
        return None
    if _cached is not None and not force_refresh:
        return _cached
    creds = gcreds.Credentials(
        token=tok.get("token"),
        refresh_token=refresh,
        token_uri=TOKEN_URI,
        client_id=cid,
        client_secret=sec,
        scopes=tok.get("scopes", SCOPES),
    )
    if creds.expired or force_refresh:
        try:
            creds.refresh(gtr.Request())
            tok["token"] = creds.token
            _save_token(tok)
        except Exception:
            return None
    _cached = creds
    return creds


def email_address() -> str:
    tok = _load_token()
    if tok.get("email"):
        return tok["email"]
    creds = get_credentials()
    if not creds:
        return ""
    try:
        r = requests.get(USER_URI, headers={
            "Authorization": f"Bearer {creds.token}"}, timeout=15)
        if r.status_code == 200:
            em = r.json().get("email", "")
            tok["email"] = em
            _save_token(tok)
            return em
    except Exception:
        pass
    return ""


def status() -> str:
    cid, sec = client_ids()
    has_cfg  = bool(cid and sec)
    has_tok  = has_token()
    email    = email_address() if has_tok else ""
    lines = [
        "Google OAuth:",
        f"  client configured: {has_cfg}",
        f"  authorized:        {has_tok}" + (f" ({email})" if email else ""),
    ]
    return "\n".join(lines)
