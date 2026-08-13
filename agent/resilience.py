"""
resilience.py — Tool execution hardening for Kaizumi.
------------------------------------------------------
Adds:
  - ToolResult: structured outcome of a tool call (ok / content / kind / timing).
  - classify_error(): cheap synchronous classification of exceptions into
    "retryable" (transient: 429, 5xx, network, quota) vs "fatal".
  - run_sync_tool(): runs a blocking tool in a thread pool with a hard per-call
    timeout and bounded retries ONLY for retryable failures (never on timeouts,
    never on side-effect-prone fatal errors).

The model receives ToolResult.content — so it can adapt (report a transient
failure, stop looping, etc.) instead of blindly anthropomorphizing an apology.
"""

import asyncio
import time
import traceback
from dataclasses import dataclass

RETRYABLE_PATTERNS = (
    "429", "408", "500", "502", "503", "504",
    "rate limit", "rate_limit", "quota", "slow down",
    "network", "timeout", "timed out", "temporarily",
    "connection reset", "connection refused", "socket", "ssl",
    "unavailable", "try again later", "backoff", "flood",
)


def classify_error(exc: Exception) -> str:
    """Classify an exception as 'retryable' or 'fatal' (cheap, no LLM)."""
    text = str(exc or "").lower()
    if any(token in text for token in RETRYABLE_PATTERNS):
        return "retryable"
    return "fatal"


@dataclass
class ToolResult:
    ok: bool = True
    content: str = "Done."
    duration_s: float = 0.0
    retries: int = 0
    error_kind: str = ""
    silent: bool = False


async def run_sync_tool(
    fn,
    name: str,
    timeout: float = 60.0,
    attempts: int = 3,
    backoff: float = 2.0,
) -> ToolResult:
    """Run a blocking tool `fn` in a thread pool with a hard timeout.

    - Success          -> ToolResult(ok=True, content=...)
    - Timeout          -> fatal ToolResult (never auto-retried: the tool may
                          have partially completed side effects).
    - Retryable error  -> retried with exponential backoff up to `attempts`.
    - Fatal error      -> returned immediately.
    """
    loop   = asyncio.get_event_loop()
    start  = time.monotonic()
    delay  = backoff
    used   = 0

    for attempt in range(1, attempts + 1):
        try:
            value = await asyncio.wait_for(
                loop.run_in_executor(None, fn), timeout=timeout
            )
            return ToolResult(
                ok=True,
                content=str(value or "Done."),
                duration_s=round(time.monotonic() - start, 2),
                retries=used,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                ok=False,
                content=f"Tool '{name}' timed out after {timeout}s (no retry to avoid double side-effects).",
                duration_s=round(time.monotonic() - start, 2),
                retries=used,
                error_kind="timeout",
            )
        except Exception as e:
            kind = classify_error(e)
            if kind != "retryable" or attempt == attempts:
                traceback.print_exc()
                short = str(e)[:400]
                return ToolResult(
                    ok=False,
                    content=f"Tool '{name}' failed: {short}",
                    duration_s=round(time.monotonic() - start, 2),
                    retries=used,
                    error_kind=kind,
                )
            used = attempt
            print(f"[Resilience] 🔁 {name} failed (retryable, attempt {attempt}/{attempts}): {str(e)[:120]}")
            await asyncio.sleep(delay)
            delay *= 2

    return ToolResult(ok=False, content=f"Tool '{name}' exhausted retries.", error_kind="retryable")