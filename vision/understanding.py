"""Deterministic local scene captioning and visual Q&A primitives."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .vision_events import VisionEvent


def _labels(events: Iterable[VisionEvent]) -> Counter:
    return Counter(event.label for event in events if event.label)


class SceneCaptioner:
    """Create a useful local caption from detector/OCR events.

    A multimodal LLM can replace this later, while this offline fallback keeps
    the assistant useful without sending camera frames anywhere.
    """

    def caption(self, events: Iterable[VisionEvent]) -> str:
        events = list(events)
        objects = _labels(e for e in events if e.type == "object_detected")
        texts = [e.label for e in events if e.type == "text_detected"]
        faces = sum(1 for e in events if e.type == "face_detected")
        parts = []
        if objects:
            parts.append("I can see " + ", ".join(
                f"{count} {label}" for label, count in objects.items()
            ))
        if faces:
            parts.append(f"{faces} face(s) detected")
        if texts:
            parts.append("readable text: " + " ".join(texts)[:240])
        return ". ".join(parts) + "." if parts else "I don't see anything confidently identifiable."


class VisualQuestionAnswering:
    """Answer simple scene questions from normalized local vision events."""

    def answer(self, question: str, events: Iterable[VisionEvent]) -> str:
        question = (question or "").lower().strip()
        events = list(events)
        objects = _labels(e for e in events if e.type == "object_detected")
        texts = [e.label for e in events if e.type == "text_detected"]
        if any(word in question for word in ("how many", "nechta", "qancha")):
            for label in objects:
                if label in question:
                    return f"I see {objects[label]} {label}."
            return f"I see {sum(objects.values())} detected object(s)."
        if any(word in question for word in ("text", "matn", "yozuv", "read")):
            return "Readable text: " + (" ".join(texts)[:500] if texts else "none detected")
        if objects:
            return "Visible objects: " + ", ".join(
                f"{count} {label}" for label, count in objects.items()
            ) + "."
        return "I don't have enough visual evidence to answer that yet."
