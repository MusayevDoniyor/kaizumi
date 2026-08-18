"""Safe event-to-automation hooks for future custom workflows."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from .vision_events import VisionEvent


class VisionWorkflowRouter:
    def __init__(self):
        self._handlers: dict[str, list[Callable[[VisionEvent], None]]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable[[VisionEvent], None]) -> None:
        self._handlers[event_type].append(handler)

    def dispatch(self, event: VisionEvent) -> None:
        for handler in tuple(self._handlers.get(event.type, ())):
            try:
                handler(event)
            except Exception:
                pass
