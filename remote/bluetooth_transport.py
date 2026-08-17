# remote/bluetooth_transport.py
# Kaizumi — Bluetooth (BLE) phone transport.
#
# Windows acts as a BLE GATT peripheral advertising a "Kaizumi Remote" service.
# A native Android app scans, connects, pairs (the write characteristic requires
# encryption+authentication, so Windows forces Bluetooth pairing on first
# write), authenticates with the bridge token, then exchanges JSON messages.
#
# No USB, no ADB, no Developer Mode, no root — standard Android Bluetooth APIs
# on the phone, standard Windows WinRT APIs on the PC.
#
# Protocol: docs/PROTOCOL.md  (length-prefixed UTF-8 JSON envelopes).

import asyncio
import json
import os
import uuid
from pathlib import Path

from remote.client import RemoteClient

SERVICE_UUID = "8f5f4a5a-2f1a-4a9e-9b2a-3a6c9e1d2b4c"
WRITE_UUID   = "9f5f4a5a-2f1a-4a9e-9b2a-3a6c9e1d2b4c"
NOTIFY_UUID  = "a5f4a5a0-2f1a-4a9e-9b2a-3a6c9e1d2b4c"

_PROTOCOL_VERSION = 1

TOKEN_FILE = Path(__file__).resolve().parent.parent / "config" / "bridge_token.txt"


def get_bridge_token() -> str:
    """Token source (fail closed): config/bridge_token.txt, then env.
    If neither exists, generate a fresh token into the config file so the
    Android app always has one to use (auto-provisioning on first run)."""
    try:
        if TOKEN_FILE.exists():
            tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if len(tok) >= 16:
                return tok
        env_tok = os.environ.get("KAIZUMI_BRIDGE_TOKEN", "").strip()
        if env_tok and len(env_tok) >= 16:
            return env_tok
    except Exception:
        pass

    # Auto-provision: create the token file so --remote works out of the box.
    import secrets
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        fresh = secrets.token_hex(16)
        TOKEN_FILE.write_text(fresh, encoding="utf-8")
        print("[Bluetooth] 🔑 Generated config/bridge_token.txt")
        return fresh
    except Exception:
        return ""


def _envelope(mtype: str, payload: dict, msg_id: str = "") -> dict:
    msg = {"version": _PROTOCOL_VERSION, "type": mtype, "payload": payload}
    if msg_id:
        msg["id"] = msg_id
    return msg


class BluetoothRemoteClient(RemoteClient):
    """Adapter over one connected Android app (one GATT subscriber)."""

    transport = "bluetooth"

    def __init__(self, peer: str = "?"):
        super().__init__(peer)
        self._notify_char = None
        self._subscriber = None
        self.authenticated = False
        self.pending_command_id = ""   # id of the last in-flight command

    def bind_notify(self, notify_char) -> None:
        self._notify_char = notify_char

    def bind_subscriber(self, subscriber) -> None:
        self._subscriber = subscriber

    async def _send_buffer(self, data: bytes) -> bool:
        if self._notify_char is None:
            return False
        try:
            from winrt.windows.storage.streams import DataWriter
            writer = DataWriter()
            writer.write_bytes(data)
            from winrt.windows.devices.bluetooth.genericattributeprofile import (
                GattWriteOption,
            )
            await asyncio.to_thread(
                self._notify_char.notify_value_async,
                writer.detach_buffer(),
                GattWriteOption.WITH_RESPONSE,
            )
            return True
        except Exception as e:
            print(f"[Bluetooth] ⚠️ notify failed: {e}")
            return False

    async def send_json(self, payload: dict) -> bool:
        """Send a protocol envelope (or raw dict) to the phone."""
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            framed = len(body).to_bytes(2, "big") + body
            return await self._send_buffer(framed)
        except Exception as e:
            print(f"[Bluetooth] ⚠️ send_json: {e}")
            return False

    async def send_audio(self, data: bytes) -> bool:
        return False  # no real-time voice over BLE in v1

    async def close(self) -> None:
        self.authenticated = False


class BluetoothBridge:
    """Lifecycle for the Windows BLE GATT peripheral server."""

    def __init__(self, kaizumi):
        self.kaizumi = kaizumi
        self._provider = None
        self._advertising = False
        self._clients: set[BluetoothRemoteClient] = set()
        self._clients_lock = asyncio.Lock()
        self._token = get_bridge_token()

    def is_advertising(self) -> bool:
        return self._advertising

    def connected_count(self) -> int:
        return len(self._clients)

    # ── helpers ────────────────────────────────────────────────────────────────
    async def _notify_event(self, client: BluetoothRemoteClient, payload: dict):
        await client.send_json(_envelope("event", payload))

    async def _reply(self, client: BluetoothRemoteClient, mtype: str,
                     payload: dict, msg_id: str = ""):
        await client.send_json(_envelope(mtype, payload, msg_id))

    # ── incoming write handling (called from WinRT callback thread) ───────────
    def _on_write_requested(self, characteristic, args):
        try:
            request = args.request
            buf = request.value
            if buf is None or buf.length == 0:
                request.respond()
                return
            from winrt.windows.storage.streams import DataReader
            reader = DataReader.from_buffer(buf)
            data = bytes(reader.read_buffer(reader.unconsumed_buffer_length))
            request.respond()
        except Exception as e:
            print(f"[Bluetooth] ⚠️ write callback: {e}")
            return
        # Handle on the asyncio loop.
        loop = getattr(self.kaizumi, "_loop", None)
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._dispatch_client(characteristic, data), loop
        )

    async def _dispatch_client(self, characteristic, data: bytes):
        """Find the client for this characteristic, then process the message."""
        client = None
        async with self._clients_lock:
            for c in self._clients:
                if c._notify_char is characteristic:
                    client = c
                    break
        if client is None:
            return
        await self._handle_message(client, data)

    async def _handle_message(self, client: BluetoothRemoteClient, data: bytes):
        try:
            if len(data) < 2:
                return
            body_len = int.from_bytes(data[:2], "big")
            body = data[2:2 + body_len]
            msg = json.loads(body.decode("utf-8"))
        except Exception:
            await self._reply(client, "event",
                              {"kind": "system", "text": "Invalid message."})
            return

        if not isinstance(msg, dict):
            return
        mtype = msg.get("type")
        msg_id = str(msg.get("id", ""))
        payload = msg.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        # ── auth gate: nothing works before a valid token ──
        if mtype != "auth":
            if not client.authenticated:
                await self._reply(client, "auth_fail",
                                  {"error": "Not authenticated."}, msg_id)
                await client.close()
                return

        if mtype == "auth":
            tok = str(payload.get("token", ""))
            if self._token and tok and self._secure_eq(tok, self._token):
                client.authenticated = True
                print(f"[Bluetooth] 🔑 Phone authenticated: {client.peer}")
                await self._reply(client, "auth_ok", {}, msg_id)
            else:
                print(f"[Bluetooth] ⛔ Auth rejected for {client.peer}")
                await self._reply(client, "auth_fail",
                                  {"error": "Invalid bridge token."}, msg_id)
                await client.close()

        elif mtype == "ping":
            await self._reply(client, "pong", {}, msg_id)

        elif mtype == "status":
            ui = self.kaizumi.ui
            await self._reply(client, "response", {
                "text": f"Kaizumi is running. Mode: {getattr(ui, 'state', '?')}.",
                "state": getattr(ui, "state", "?"),
                "muted": getattr(ui, "muted", False),
            }, msg_id)

        elif mtype == "mute":
            muted = bool(payload.get("muted"))
            try:
                self.kaizumi.ui.muted = muted
                await self._reply(client, "response",
                                  {"text": f"Microphone {'muted' if muted else 'unmuted'}."},
                                  msg_id)
            except Exception as e:
                await self._reply(client, "response",
                                  {"text": f"Could not mute: {e}"}, msg_id)

        elif mtype == "stop":
            try:
                if getattr(self.kaizumi, "set_speaking", None):
                    self.kaizumi.set_speaking(False)
                await self._reply(client, "response", {"text": "Stopped."}, msg_id)
            except Exception as e:
                await self._reply(client, "response",
                                  {"text": f"Could not stop: {e}"}, msg_id)

        elif mtype == "disconnect":
            await self._reply(client, "event",
                              {"kind": "system", "text": "Disconnecting."})
            await client.close()

        elif mtype == "command":
            text = str(payload.get("text", "")).strip()
            if not text:
                await self._reply(client, "response",
                                  {"text": "Empty command."}, msg_id)
                return
            client.pending_command_id = msg_id
            print(f"[Bluetooth] 📱 Command: {text[:80]}")
            # Route through the SAME Gemini Live session as local voice / the
            # WebSocket bridge — this preserves tools, safety gate, memory.
            session = getattr(self.kaizumi, "session", None)
            send_lock = getattr(self.kaizumi, "_send_lock", None)
            if session is None or send_lock is None:
                await self._reply(client, "response",
                                  {"text": "Kaizumi is not ready yet, sir."}, msg_id)
                return
            try:
                async with send_lock:
                    await session.send_realtime_input(text=text)
            except Exception as e:
                await self._reply(client, "response",
                                  {"text": f"Command failed: {e}"}, msg_id)

        else:
            await self._reply(client, "event",
                              {"kind": "system",
                               "text": f"Unknown message type: {mtype}"})

    @staticmethod
    def _secure_eq(a: str, b: str) -> bool:
        import hmac
        return hmac.compare_digest(a, b)

    # ── transcript forwarding: kaizumi reply → response with pending id ──────
    async def forward_transcript(self, role: str, text: str):
        """Called by main.py when a turn completes so the phone gets the reply."""
        async with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            if not client.authenticated:
                continue
            if role == "kaizumi":
                await self._reply(client, "response",
                                  {"text": text}, client.pending_command_id)
            else:
                await self._notify_event(client, {"kind": "system",
                                                  "text": f"You: {text}"})

    # ── broadcast (tool / phase / system events) ──────────────────────────────
    async def broadcast(self, payload: dict):
        async with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            if not client.authenticated:
                continue
            if payload.get("type") == "tool":
                await self._notify_event(client, {
                    "kind": "tool",
                    "name": payload.get("name"),
                    "status": payload.get("status"),
                    "summary": payload.get("summary"),
                })
            elif payload.get("type") == "phase":
                await self._notify_event(client, {
                    "kind": "phase",
                    "state": payload.get("state"),
                })
            elif payload.get("type") == "system":
                await self._notify_event(client, {
                    "kind": "system",
                    "text": payload.get("text"),
                })
            elif payload.get("type") in ("transcript", "wake"):
                pass  # handled by forward_transcript / wake handled in main

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def start(self):
        if self._advertising:
            return
        if not self._token:
            print("[Bluetooth] ⛔ No bridge token — Bluetooth transport disabled.")
            return False

        try:
            from winrt.windows.devices.bluetooth.genericattributeprofile import (
                GattServiceProvider,
                GattServiceProviderAdvertisingParameters,
                GattLocalCharacteristicParameters,
                GattProtectionLevel,
                GattCharacteristicProperties,
            )
        except ImportError as e:
            print(f"[Bluetooth] ❌ winrt not available: {e}")
            return False

        result = await GattServiceProvider.create_async(uuid.UUID(SERVICE_UUID))
        if result.error.value != 0:
            print(f"[Bluetooth] ❌ GATT create error: {result.error.value}")
            return False
        provider = result.service_provider

        # Write characteristic (phone → PC), encrypted + authenticated.
        write_params = GattLocalCharacteristicParameters()
        write_params.characteristic_properties = GattCharacteristicProperties.WRITE
        write_params.write_protection_level = (
            GattProtectionLevel.ENCRYPTION_AND_AUTHENTICATION_REQUIRED
        )
        write_params.user_description = "Kaizumi In"
        wc = await provider.service.create_characteristic_async(
            uuid.UUID(WRITE_UUID), write_params
        )
        if wc.error.value != 0:
            print(f"[Bluetooth] ❌ write char error: {wc.error.value}")
            return False
        write_char = wc.characteristic

        # Notify characteristic (PC → phone).
        notify_params = GattLocalCharacteristicParameters()
        notify_params.characteristic_properties = GattCharacteristicProperties.NOTIFY
        notify_params.user_description = "Kaizumi Out"
        nc = await provider.service.create_characteristic_async(
            uuid.UUID(NOTIFY_UUID), notify_params
        )
        if nc.error.value != 0:
            print(f"[Bluetooth] ❌ notify char error: {nc.error.value}")
            return False
        notify_char = nc.characteristic

        # Register a client for this subscription when the phone subscribes.
        def on_subscribed(sender, args):
            loop = getattr(self.kaizumi, "_loop", None)
            if loop is None:
                return
            try:
                removed = list(args.removed_clients) if args else []
            except Exception:
                removed = []
            try:
                added = list(args.added_clients) if args else []
            except Exception:
                added = []
            asyncio.run_coroutine_threadsafe(
                self._on_clients_changed(sender, added, removed), loop
            )

        notify_char.add_subscribed_clients_changed(on_subscribed)

        write_char.add_write_requested(self._on_write_requested)

        params = GattServiceProviderAdvertisingParameters()
        params.is_discoverable = True
        params.is_connectable = True
        provider.start_advertising_with_parameters(params)

        self._provider = provider
        self._advertising = True
        print(f"[Bluetooth] 📡 BLE peripheral ON — service "
              f"{SERVICE_UUID} (scan for 'Kaizumi Remote')")
        return True

    async def _on_clients_changed(self, notify_char, added, removed):
        """Track GATT subscribers: add new ones, drop departed ones."""
        async with self._clients_lock:
            # Drop clients whose underlying subscriber left.
            removed_ids = {id(s) for s in removed}
            for c in list(self._clients):
                if c._subscriber is not None and id(c._subscriber) in removed_ids:
                    self._clients.discard(c)
                    print(f"[Bluetooth] 📵 Phone unsubscribed ({len(self._clients)} active)")
            # Add any new subscriber.
            for sub in added:
                client = BluetoothRemoteClient("BLE")
                client.bind_notify(notify_char)
                client.bind_subscriber(sub)
                client.attach_loop(getattr(self.kaizumi, "_loop", None))
                self._clients.add(client)
                print(f"[Bluetooth] 📱 Phone subscribed ({len(self._clients)} active)")

    async def stop(self):
        if not self._advertising:
            return
        try:
            self._provider.stop_advertising()
        except Exception as e:
            print(f"[Bluetooth] ⚠️ stop: {e}")
        self._advertising = False
        async with self._clients_lock:
            self._clients.clear()
        print("[Bluetooth] 🔴 BLE peripheral OFF")


# Module-level singleton bound at startup.
_bridge = None


def get_bluetooth_bridge() -> BluetoothBridge | None:
    return _bridge


async def start_bluetooth_bridge(kaizumi) -> BluetoothBridge | None:
    global _bridge
    _bridge = BluetoothBridge(kaizumi)
    ok = await _bridge.start()
    return _bridge if ok else None


def close_bluetooth_bridge() -> None:
    global _bridge
    b = _bridge
    _bridge = None
    if b is not None:
        try:
            loop = b.kaizumi._loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(b.stop(), loop)
        except Exception as e:
            print(f"[Bluetooth] ⚠️ close: {e}")