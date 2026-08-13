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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REMOTE_HTML_PATH = Path(__file__).resolve().parent / "remote" / "interface.html"
REMOTE_HTML      = REMOTE_HTML_PATH.read_text(encoding="utf-8")

DEFAULT_PORT = 8765


class _PageHandler(BaseHTTPRequestHandler):
    ws_port = DEFAULT_PORT
    html    = ""

    def do_GET(self):
        if self.path in ("/", "/remote.html", "/index.html"):
            body = self.html.replace("__WS_PORT__", str(self.ws_port)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):
        pass


def _phone_wake_service(on_detect):
    """A wake-word service fed by the PHONE's mic instead of the PC's."""
    try:
        from actions.wake_word import WakeWordService
        svc = WakeWordService(model_file="hey_jarvis_v0.1.onnx", phrase="Hey Jarvis")
        svc.configure(on_detect)
        return svc
    except Exception as e:
        print(f"[Bridge] ⚠️ Phone wake unavailable: {e}")
        return None


async def start_bridge(jarvis, port: int = DEFAULT_PORT):
    """Start the remote bridge bound to a JarvisLive instance.

    jarvis must expose: remote_clients (set), ui (muted flag + write_log),
    out_queue (asyncio.Queue of audio media dicts), session.
    """
    from websockets.asyncio.server import serve

    _PageHandler.ws_port = port
    _PageHandler.html    = REMOTE_HTML
    httpd     = ThreadingHTTPServer(("0.0.0.0", port + 1), _PageHandler)
    httpd_thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="BridgeHttp")
    httpd_thread.start()

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
        if mtype == "text":
            text = str(data.get("text", "")).strip()
            if text and jarvis_.session:
                print(f"[Bridge] 📱 Text: {text[:80]}")
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
            if not jarvis.remote_clients:
                jarvis.ui.muted = False
                jarvis.ui.write_log("SYS: 📱 Remote off — local mode restored.")
            print("[Bridge] 🎧 Phone disconnected")

    server = await serve(handler, "0.0.0.0", port)
    print(
        f"[Bridge] 📱 Phone bridge ON — open http://<PC-IP>:{port + 1} on your phone "
        f"(WebSocket on :{port})"
    )
    return server, httpd, httpd_thread


def close_bridge(server, httpd, httpd_thread) -> None:
    """Shut the bridge down and free its ports (called when the app exits)."""
    try:
        server.close()
    except Exception:
        pass
    try:
        httpd.shutdown()
        httpd.server_close()
    except Exception:
        pass
    try:
        httpd_thread.join(timeout=2)
    except Exception:
        pass