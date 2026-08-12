# remote_bridge.py
# Kaizumi — phone voice bridge.
#
# Runs a WebSocket server on the PC (ws://PC-IP:8765) plus a tiny HTTP page
# server (http://PC-IP:8766) for the phone browser. The phone talks into the
# mic and PCM audio is streamed straight into the SAME Gemini Live session
# that local JARVIS uses. Tool calls, memory, and voice replies all work
# from the phone — no app install, no extra API keys.

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

    async def _handle_text(jarvis_, msg: str):
        try:
            data = json.loads(msg)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if data.get("type") == "text":
            text = str(data.get("text", "")).strip()
            if text and jarvis_.session:
                print(f"[Bridge] 📱 Text: {text[:80]}")
                await jarvis_.session.send_client_content(
                    turns={"parts": [{"text": text}]},
                    turn_complete=True,
                )

    async def handler(ws):
        jarvis.remote_clients.add(ws)
        jarvis.ui.muted = True
        jarvis.ui.write_log(f"SYS: 📱 Phone connected ({ws.remote_address[0]}) — mic muted, remote on.")
        print(f"[Bridge] 🎧 Phone connected: {ws.remote_address[0]}")
        await ws.send("Connected to Kaizumi. Say: Hey Jarvis, open YouTube…")
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)) and msg:
                    # PCM int16 @16kHz mono → straight into the live session
                    await jarvis.out_queue.put({"data": bytes(msg), "mime_type": "audio/pcm"})
                elif isinstance(msg, str):
                    await _handle_text(jarvis, msg)
        except Exception as e:
            print(f"[Bridge] ⚠️ {e}")
        finally:
            jarvis.remote_clients.discard(ws)
            if not jarvis.remote_clients:
                jarvis.ui.muted = False
                jarvis.ui.write_log("SYS: 📱 Remote off — local mode restored.")
            print("[Bridge] 🎧 Phone disconnected")

    server = await serve(handler, "0.0.0.0", port)
    print(
        f"[Bridge] 📱 Phone bridge ON — open http://<PC-IP>:{port + 1} on your phone "
        f"(WebSocket on :{port})"
    )
    return server