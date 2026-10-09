"""Split `**bold**` markup into segments, so renderers never parse user text."""

from typing import TypedDict


class Segment(TypedDict, total=False):
    text: str
    bold: bool
    url: str


def to_segments(text: str) -> list[Segment]:
    """'a **b** c' -> [{text: 'a ', bold: False}, {text: 'b', bold: True}, ...]."""
    parts = text.split("**")  # the schema guarantees ** is balanced
    return [{"text": part, "bold": i % 2 == 1} for i, part in enumerate(parts) if part]
