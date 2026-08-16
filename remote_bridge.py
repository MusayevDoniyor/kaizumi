# remote_bridge.py
# Kaizumi — phone voice bridge.
#
# Runs a WebSocket server on the PC (ws://PC-IP:8765) plus a tiny HTTP page
# server (http://PC-IP:8766) for the phone browser. The phone talks into the
# mic and PCM audio is streamed straight into the SAME Gemini Live session
# that local KAIZUMI uses. Tool calls, memory, and voice replies all work
# from the phone — no app install, no extra API keys.
#
# Event protocol (text frames = JSON):
#   {type:"transcript", role:"user"|"kaizumi", text:"..."}   — turn transcript
#   {type:"tool",       name:"open_app", status:"start"|"done"|"error", summary:"..."}
#   {type:"phase",      state:"LISTENING"|"THINKING"|"SPEAKING"|"MUTED"|"ONLINE"}
#   {type:"system",     text:"..."}                          — log line
#   {type:"wake"}                                            — wake word heard on phone
#   {type:"vision",     answer:"..."}                        — reply to a vision request
# Binary frames are always PCM int16 audio (bidirectional).

import asyncio
import json
import os
import secrets
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REMOTE_HTML_PATH = Path(__file__).resolve().parent / "remote" / "interface.html"
REMOTE_HTML      = REMOTE_HTML_PATH.read_text(encoding="utf-8")

DEFAULT_PORT = 8765
TOKEN_FILE   = Path(__file__).resolve().parent / "config" / "bridge_token.txt"


def get_bridge_token() -> str:
    """Return the persistent bridge auth token, generating it on first use.

    The token lives in config/bridge_token.txt (gitignored). Without it the
    WebSocket server refuses connections, so a phone can never control the PC
    just by finding the tunnel URL.
    """
    try:
        if TOKEN_FILE.exists():
            tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if len(tok) >= 16:
                return tok
        env_tok = os.environ.get("KAIZUMI_BRIDGE_TOKEN", "").strip()
        if env_tok and len(env_tok) >= 16:
            return env_tok
        tok = secrets.token_urlsafe(32)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(tok, encoding="utf-8")
        print(f"[Bridge] 🔑 New remote-access token generated — "
              f"save it: {tok}")
        return tok
    except Exception as e:
        print(f"[Bridge] ⚠️ Bridge token error: {e}")
        # Degrade gracefully: refuse connections rather than open access.
        return ""

# Phone request/response: pending PC->phone calls resolved by phone replies.
_PENDING_LOCK = threading.Lock()
_PENDING      = {}   # req_id -> (threading.Event, dict holder)
_CLIENTS_LOCK = threading.Lock()


def phone_connected(kaizumi) -> bool:
    with _CLIENTS_LOCK:
        return bool(getattr(kaizumi, "remote_clients", None))


def _request_phone(kaizumi, payload: dict, timeout: float = 12.0) -> dict | None:
    """Send a JSON request to the first connected phone and wait for its reply.

    The phone replies with the same req_id; the reply payload is returned, or
    None on timeout / no phone.
    """
    clients = getattr(kaizumi, "remote_clients", None)
    if not clients:
        return None
    loop = getattr(kaizumi, "_loop", None)
    if not loop:
        return None
    with _CLIENTS_LOCK:
        if not clients:
            return None
        try:
            ws = next(iter(clients))
        except StopIteration:
            return None
    req_id = uuid.uuid4().hex[:12]
    holder = {}
    event = threading.Event()
    with _PENDING_LOCK:
        _PENDING[req_id] = (event, holder)
    try:
        payload = dict(payload)
        payload["req_id"] = req_id
        sent = asyncio_send(loop, ws, payload)
        if not sent:
            return None
        event.wait(timeout)
    finally:
        with _PENDING_LOCK:
            _PENDING.pop(req_id, None)
    return holder.get("result") if event.is_set() else None


def asyncio_send(loop, ws, payload: dict) -> bool:
    try:
        fut = asyncio.run_coroutine_threadsafe(
            ws.send(json.dumps(payload, ensure_ascii=False)), loop
        )
        fut.result(timeout=5)
        return True
    except Exception:
        return False


def _resolve_pending(data: dict):
    req_id = data.get("req_id")
    if not req_id:
        return
    with _PENDING_LOCK:
        entry = _PENDING.pop(req_id, None)
    if entry:
        event, holder = entry
        holder["result"] = data
        event.set()


def _fail_all_pending(reason: str):
    with _PENDING_LOCK:
        items = list(_PENDING.values())
        _PENDING.clear()
    for event, holder in items:
        holder["result"] = {"ok": False, "error": reason}
        event.set()


def send_sms_via_phone(kaizumi, phone: str, message: str) -> str:
    if not phone.strip():
        return "Please provide the phone number to text, sir."
    if not message.strip():
        return "Please provide the message text."
    if not phone_connected(kaizumi):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(kaizumi, {"type": "sms_send", "phone": phone, "text": message})
    if reply is None:
        return "No reply from the phone (timeout) — is the Kaizumi app open and connected?"
    if not reply.get("ok"):
        return f"SMS not sent: {reply.get('error') or 'unknown error'}"
    return f"SMS sent to {phone}: {reply.get('detail') or 'delivered'}"


def read_notifications_via_phone(kaizumi, limit: int = 10) -> str:
    if not phone_connected(kaizumi):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(kaizumi, {"type": "read_notifications", "limit": int(limit or 10)})
    if reply is None:
        return "No reply from the phone (timeout)."
    if not reply.get("ok"):
        return f"Notifications unavailable: {reply.get('error') or 'unknown error'}"
    notifs = reply.get("notifications") or []
    if not notifs:
        return "No recent notifications on the phone."
    lines = [f"{n.get('app','?')}: {n.get('title','')} — {n.get('text','')}" for n in notifs]
    return "Recent phone notifications:\n" + "\n".join(lines)


def phone_info_via_phone(kaizumi) -> str:
    if not phone_connected(kaizumi):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(kaizumi, {"type": "phone_info"})
    if reply is None:
        return "No reply from the phone (timeout)."
    if not reply.get("ok"):
        return f"Phone info unavailable: {reply.get('error') or 'unknown error'}"
    i = reply.get("info") or {}
    return (
        f"Phone info:\n"
        f"  Model: {i.get('model', '?')}\n"
        f"  Android: {i.get('android', '?')}\n"
        f"  Battery: {i.get('battery', '?')}%\n"
        f"  Network: {i.get('network', '?')}\n"
        f"  Memory free: {i.get('ram_free', '?')}\n"
        f"  Storage free: {i.get('storage_free', '?')}"
    )


def ring_phone_via_phone(kaizumi) -> str:
    """Makes the connected phone vibrate + beep so the user can find it."""
    if not phone_connected(kaizumi):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(kaizumi, {"type": "ring_phone"})
    if reply is None:
        return ("No reply from the phone (timeout) — is the Kaizumi app open, "
                "on-screen and connected?")
    if not reply.get("ok"):
        return f"Could not ring the phone: {reply.get('error') or 'unknown error'}"
    return "Ringing your phone now — check the phone, sir!"


def _phone_wake_service(on_detect):
    """A wake-word service fed by the PHONE's mic instead of the PC's."""
    try:
        from actions.wake_word import WakeWordService
        svc = WakeWordService(model_file="hey_kaizumi_v0.1.onnx", phrase="Hey Kaizumi")
        svc.configure(on_detect)
        if svc.load():
            return svc
        print("[Bridge] ℹ️ Phone wake skipped (model not loaded).")
        return None
    except Exception as e:
        print(f"[Bridge] ⚠️ Phone wake unavailable: {e}")
        return None


async def start_bridge(kaizumi, port: int = DEFAULT_PORT):
    """Start the remote bridge bound to a KaizumiLive instance.

    Everything (HTML page + WebSocket) is served on a SINGLE port so the
    whole bridge can be exposed through one public tunnel. The phone page
    connects its WebSocket to the same origin (/ws), which works both on the
    LAN and behind an HTTPS tunnel.

    kaizumi must expose: remote_clients (set), ui (muted flag + write_log),
    out_queue (asyncio.Queue of audio media dicts), session.
    """
    from websockets.asyncio.server import serve
    import hmac

    token = get_bridge_token()

    # Fail closed: without a valid token nobody gets in (HTTP or WS).
    if not token or len(token) < 16:
        async def _deny_all(connection, request):
            print("[Bridge] ⛔ No bridge token configured — refusing all connections")
            return connection.respond(503, "bridge token not configured")
        server = await serve(_deny_all, "0.0.0.0", port)
        print("[Bridge] ⚠️ Phone bridge disabled — no valid access token available.")
        return server

    async def _process_request(connection, request):
        path = request.path
        if path in ("/", "/remote.html", "/index.html"):
            return connection.respond(200, REMOTE_HTML)
        if path in ("/favicon.ico",):
            return connection.respond(404, "not found")
        # WebSocket upgrade (e.g. /ws?token=...) — require the auth token.
        query = parse_qs(urlparse(path).query)
        supplied = (query.get("token") or [""])[0].strip()
        if not supplied or not hmac.compare_digest(supplied, token):
            print(f"[Bridge] ⛔ Unauthorized connection attempt rejected "
                  f"({connection.remote_address[0]})")
            return connection.respond(401, "unauthorized: missing or wrong token")
        return None  # allow WebSocket upgrade

    # Phone-mic wake word engine (only listens while a phone is connected).
    phone_wake_lock = threading.Lock()
    phone_wake      = {"svc": None, "ws": None}

    def _enable_phone_wake(ws):
        with phone_wake_lock:
            phone_wake["ws"] = ws
            if phone_wake["svc"] is None:
                phone_wake["svc"] = _phone_wake_service(_on_phone_wake)

    def _disable_phone_wake():
        with phone_wake_lock:
            phone_wake["ws"] = None

    def _on_phone_wake(_ignored_ws=None):
        # Read the current phone socket at call time, not the one that was
        # connected when the engine started (handles reconnects).
        with phone_wake_lock:
            ws = phone_wake["ws"]
        try:
            if ws is None:
                return
            payload = {"type": "wake"}
            asyncio_run = getattr(kaizumi, "_safely_send", None)
            if asyncio_run:
                asyncio_run(ws, payload)
            else:
                print("[Bridge] Wake detected on phone but bridge can't send.")
            kaizumi.ui.write_log("SYS: 📱 Wake word heard on phone — listening.")
        except Exception as e:
            print(f"[Bridge] ⚠️ phone wake handler: {e}")

    async def _handle_json(kaizumi_, data: dict, ws):
        mtype = data.get("type")
        if mtype in ("sms_result", "notifications_result", "phone_info_result", "ping_result"):
            _resolve_pending(data)
        elif mtype == "text":
            text = str(data.get("text", "")).strip()
            if text and kaizumi_.session and kaizumi_._send_lock:
                print(f"[Bridge] 📱 Text: {text[:80]}")
                async with kaizumi_._send_lock:
                    await kaizumi_.session.send_realtime_input(text=text)
        elif mtype == "vision":
            import base64
            b64 = str(data.get("image", "")).strip()
            if not b64:
                return
            try:
                image_bytes = base64.b64decode(b64)
            except Exception as e:
                print(f"[Bridge] ⚠️ Vision decode: {e}")
                return
            question = str(data.get("text", "")).strip() or "What do you see?"
            print(f"[Bridge] 📷 Vision request ({len(image_bytes)} bytes)")
            try:
                from actions.screen_processor import _analyze_image_text
                answer = await asyncio.to_thread(
                    _analyze_image_text, image_bytes, "image/jpeg", question)
            except Exception as e:
                answer = f"Vision error: {e}"
            await ws.send(json.dumps({"type": "vision", "answer": answer}, ensure_ascii=False))

    async def handler(ws):
        with _CLIENTS_LOCK:
            kaizumi.remote_clients.add(ws)
        kaizumi.ui.muted = True
        kaizumi.ui.write_log(f"SYS: 📱 Phone connected ({ws.remote_address[0]}) — mic muted, remote on.")
        print(f"[Bridge] 🎧 Phone connected: {ws.remote_address[0]}")
        _enable_phone_wake(ws)
        await ws.send("Connected to Kaizumi. Say: Hey Kaizumi, open YouTube…")
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)) and msg:
                    # PCM int16 @16kHz mono → live session + phone wake check
                    if kaizumi.out_queue is not None:
                        await kaizumi.out_queue.put({"data": bytes(msg), "mime_type": "audio/pcm"})
                    phone_wake_svc = phone_wake["svc"]
                    if phone_wake_svc is not None:
                        try:
                            import numpy as np
                            await asyncio.to_thread(
                                phone_wake_svc._feed,
                                np.frombuffer(msg, dtype=np.int16).copy())
                        except Exception as e:
                            print(f"[Bridge] ⚠️ phone wake feed: {e}")
                elif isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                        if isinstance(data, dict):
                            await _handle_json(kaizumi, data, ws)
                    except json.JSONDecodeError:
                        await _handle_json(kaizumi, {"type": "text", "text": msg}, ws)
        except Exception as e:
            print(f"[Bridge] ⚠️ {e}")
        finally:
            with _CLIENTS_LOCK:
                kaizumi.remote_clients.discard(ws)
            _disable_phone_wake()
            _fail_all_pending("phone disconnected")
            if not kaizumi.remote_clients:
                kaizumi.ui.muted = False
                kaizumi.ui.write_log("SYS: 📱 Remote off — local mode restored.")
            print("[Bridge] 🎧 Phone disconnected")

    server = await serve(handler, "0.0.0.0", port,
                         process_request=_process_request)
    print(
        f"[Bridge] 📱 Phone bridge ON — http://<PC-IP>:{port} "
        f"(page + WebSocket /ws on the same port)"
    )
    return server


def close_bridge(server, httpd=None, httpd_thread=None) -> None:
    """Shut the bridge down and free its ports (called when the app exits)."""
    try:
        server.close()
    except Exception:
        pass
    if httpd is not None:
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
    if httpd_thread is not None:
        try:
            httpd_thread.join(timeout=2)
        except Exception:
            pass