# remote/client.py
# Kaizumi — transport abstraction.
#
# kaizumi.remote_clients was removed with the WebSocket bridge. Only the
# Bluetooth transport uses RemoteClient now; the core engine talks to it via
# remote.bluetooth_transport.BluetoothBridge.

import asyncio
import json


class RemoteClient:
    """A single connected remote (phone) endpoint.

    Subclasses must implement the async send primitives; the sync wrappers
    marshal onto the asyncio loop for thread-safe broadcasting.
    """

    transport = "abstract"

    def __init__(self, peer: str = "?"):
        self.peer = peer
        self._loop = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    # ── async primitives (subclass) ─────────────────────────────────────────
    async def send_json(self, payload: dict) -> bool:
        raise NotImplementedError

    async def send_audio(self, data: bytes) -> bool:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    # ── thread-safe sync helpers (core engine / bridge) ─────────────────────
    def send_json_sync(self, payload: dict) -> bool:
        """Send JSON from any thread (marshals onto the asyncio loop)."""
        loop = self._loop
        if loop is None:
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(self.send_json(payload), loop)
            fut.result(timeout=5)
            return True
        except Exception:
            return False

    def send_audio_sync(self, data: bytes) -> bool:
        loop = self._loop
        if loop is None:
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(self.send_audio(data), loop)
            fut.result(timeout=5)
            return True
        except Exception:
            return False