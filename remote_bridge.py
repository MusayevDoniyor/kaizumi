# remote_bridge.py
# Kaizumi — phone voice bridge.
#
# Runs a WebSocket server on the PC (ws://PC-IP:8765) plus a tiny HTTP page
# server (http://PC-IP:8766) for the phone browser. The phone talks into the
# mic and PCM audio is streamed straight into the SAME Gemini Live session
# that local JARVIS uses. Tool calls, memory, and voice replies all work
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

import json
import threading
import uuid
from pathlib import Path

REMOTE_HTML_PATH = Path(__file__).resolve().parent / "remote" / "interface.html"
REMOTE_HTML      = REMOTE_HTML_PATH.read_text(encoding="utf-8")

DEFAULT_PORT = 8765

# Phone request/response: pending PC->phone calls resolved by phone replies.
_PENDING_LOCK = threading.Lock()
_PENDING      = {}   # req_id -> (threading.Event, dict holder)


def phone_connected(jarvis) -> bool:
    return bool(getattr(jarvis, "remote_clients", None))


def _request_phone(jarvis, payload: dict, timeout: float = 12.0) -> dict | None:
    """Send a JSON request to the first connected phone and wait for its reply.

    The phone replies with the same req_id; the reply payload is returned, or
    None on timeout / no phone.
    """
    clients = getattr(jarvis, "remote_clients", None)
    if not clients:
        return None
    loop = getattr(jarvis, "_loop", None)
    if not loop:
        return None
    ws = next(iter(clients))
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
    import asyncio
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


def send_sms_via_phone(jarvis, phone: str, message: str) -> str:
    if not phone.strip():
        return "Please provide the phone number to text, sir."
    if not message.strip():
        return "Please provide the message text."
    if not phone_connected(jarvis):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(jarvis, {"type": "sms_send", "phone": phone, "text": message})
    if reply is None:
        return "No reply from the phone (timeout) — is the Kaizumi app open and connected?"
    if not reply.get("ok"):
        return f"SMS not sent: {reply.get('error') or 'unknown error'}"
    return f"SMS sent to {phone}: {reply.get('detail') or 'delivered'}"


def read_notifications_via_phone(jarvis, limit: int = 10) -> str:
    if not phone_connected(jarvis):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(jarvis, {"type": "read_notifications", "limit": int(limit or 10)})
    if reply is None:
        return "No reply from the phone (timeout)."
    if not reply.get("ok"):
        return f"Notifications unavailable: {reply.get('error') or 'unknown error'}"
    notifs = reply.get("notifications") or []
    if not notifs:
        return "No recent notifications on the phone."
    lines = [f"{n.get('app','?')}: {n.get('title','')} — {n.get('text','')}" for n in notifs]
    return "Recent phone notifications:\n" + "\n".join(lines)


def phone_info_via_phone(jarvis) -> str:
    if not phone_connected(jarvis):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(jarvis, {"type": "phone_info"})
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


def ring_phone_via_phone(jarvis) -> str:
    """Makes the connected phone vibrate + beep so the user can find it."""
    if not phone_connected(jarvis):
        return "No phone is connected right now — connect the app first."
    reply = _request_phone(jarvis, {"type": "ring_phone"})
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
        svc = WakeWordService(model_file="hey_jarvis_v0.1.onnx", phrase="Hey Jarvis")
        svc.configure(on_detect)
        if svc.load():
            return svc
        print("[Bridge] ℹ️ Phone wake skipped (model not loaded).")
        return None
    except Exception as e:
        print(f"[Bridge] ⚠️ Phone wake unavailable: {e}")
        return None


async def start_bridge(jarvis, port: int = DEFAULT_PORT):
    """Start the remote bridge bound to a JarvisLive instance.

    Everything (HTML page + WebSocket) is served on a SINGLE port so the
    whole bridge can be exposed through one public tunnel. The phone page
    connects its WebSocket to the same origin (/ws), which works both on the
    LAN and behind an HTTPS tunnel.

    jarvis must expose: remote_clients (set), ui (muted flag + write_log),
    out_queue (asyncio.Queue of audio media dicts), session.
    """
    from websockets.asyncio.server import serve

    async def _process_request(connection, request):
        path = request.path
        if path in ("/", "/remote.html", "/index.html"):
            return connection.respond(200, REMOTE_HTML)
        if path in ("/favicon.ico",):
            return connection.respond(404, "not found")
        return None  # allow WebSocket upgrade (any path, e.g. /ws)

    # Phone-mic wake word engine (only listens while a phone is connected).
    phone_wake_lock = threading.Lock()
    phone_wake      = {"svc": None, "ws": None}

    def _enable_phone_wake(ws):
        with phone_wake_lock:
            phone_wake["ws"] = ws
            if phone_wake["svc"] is None:
                phone_wake["svc"] = _phone_wake_service(lambda: _on_phone_wake(ws))

    def _disable_phone_wake():
        with phone_wake_lock:
            phone_wake["ws"] = None

    def _on_phone_wake(ws):
        try:
            payload = {"type": "wake"}
            asyncio_run = getattr(jarvis, "_safely_send", None)
            if asyncio_run:
                asyncio_run(ws, payload)
            else:
                print("[Bridge] Wake detected on phone but bridge can't send.")
            jarvis.ui.write_log("SYS: 📱 Wake word heard on phone — listening.")
        except Exception as e:
            print(f"[Bridge] ⚠️ phone wake handler: {e}")

    async def _handle_json(jarvis_, data: dict, ws):
        mtype = data.get("type")
        if mtype in ("sms_result", "notifications_result", "phone_info_result", "ping_result"):
            _resolve_pending(data)
        elif mtype == "text":
            text = str(data.get("text", "")).strip()
            if text and jarvis_.session and jarvis_._send_lock:
                print(f"[Bridge] 📱 Text: {text[:80]}")
                async with jarvis_._send_lock:
                    await jarvis_.session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )
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
                answer = _analyze_image_text(image_bytes, "image/jpeg", question)
            except Exception as e:
                answer = f"Vision error: {e}"
            await ws.send(json.dumps({"type": "vision", "answer": answer}, ensure_ascii=False))

    async def handler(ws):
        jarvis.remote_clients.add(ws)
        jarvis.ui.muted = True
        jarvis.ui.write_log(f"SYS: 📱 Phone connected ({ws.remote_address[0]}) — mic muted, remote on.")
        print(f"[Bridge] 🎧 Phone connected: {ws.remote_address[0]}")
        _enable_phone_wake(ws)
        await ws.send("Connected to Kaizumi. Say: Hey Jarvis, open YouTube…")
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)) and msg:
                    # PCM int16 @16kHz mono → live session + phone wake check
                    if jarvis.out_queue is not None:
                        await jarvis.out_queue.put({"data": bytes(msg), "mime_type": "audio/pcm"})
                    phone_wake_svc = phone_wake["svc"]
                    if phone_wake_svc is not None:
                        try:
                            import numpy as np
                            phone_wake_svc._feed(np.frombuffer(msg, dtype=np.int16).copy())
                        except Exception as e:
                            print(f"[Bridge] ⚠️ phone wake feed: {e}")
                elif isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                        if isinstance(data, dict):
                            await _handle_json(jarvis, data, ws)
                    except json.JSONDecodeError:
                        await _handle_json(jarvis, {"type": "text", "text": msg}, ws)
        except Exception as e:
            print(f"[Bridge] ⚠️ {e}")
        finally:
            jarvis.remote_clients.discard(ws)
            _disable_phone_wake()
            _fail_all_pending("phone disconnected")
            if not jarvis.remote_clients:
                jarvis.ui.muted = False
                jarvis.ui.write_log("SYS: 📱 Remote off — local mode restored.")
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