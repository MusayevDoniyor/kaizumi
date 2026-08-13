"""
loop_guard.py — Anti-loop protection for Kaizumi's tool calls.
--------------------------------------------------------------
Guards against two failure modes while the model drives tools in a live
session:

  1. Identical tool + arguments called repeatedly (e.g. stuck on retrying the
     same failing action) — blocked after `max_identical` consecutive calls.
  2. Ping-pong loops between exactly two tools (A, B, A, B, ...) — blocked when
     the alternation repeats `ping_pong` times.

When a loop is detected, `check()` returns a short instruction string for the
model ("stop and report the last result"); the caller passes it back as the
tool result so the model can break the cycle instead of apologizing blindly.
"""

import json


class LoopGuard:

    def __init__(self, max_identical: int = 3, ping_pong: int = 3):
        self.max_identical = max_identical
        self.ping_pong     = ping_pong
        self._last_sig     = None
        self._same_count   = 0
        self._recent       = []

    @staticmethod
    def _signature(name: str, args: dict) -> tuple:
        try:
            compact = json.dumps(dict(args or {}), sort_keys=True, default=str)
        except Exception:
            compact = str(args)
        return (name, compact[:200])

    def check(self, name: str, args: dict) -> str | None:
        """Record a tool call; return a block instruction string if a loop is
        detected, otherwise None."""
        sig = self._signature(name, args)

        if sig == self._last_sig:
            self._same_count += 1
        else:
            self._last_sig   = sig
            self._same_count = 1

        if self._same_count >= self.max_identical:
            return (
                f"Loop guard: tool '{name}' was called {self._same_count} times "
                f"in a row with identical arguments. This is a loop — do NOT call "
                f"'{name}' again. Stop and report the current state to the user."
            )

        self._recent.append(name)
        if len(self._recent) > 8:
            self._recent.pop(0)

        if len(self._recent) >= 4:
            a, b, c, d = self._recent[-4:]
            if a == c and b == d and a != b:
                return (
                    f"Loop guard: detected a ping-pong loop between '{a}' and "
                    f"'{b}'. Stop alternating these tools and report the last "
                    f"successful result to the user."
                )
        return None

    def reset(self) -> None:
        self._last_sig   = None
        self._same_count = 0
        self._recent     = []
