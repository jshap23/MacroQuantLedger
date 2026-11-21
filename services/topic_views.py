"""Pure helpers for structured topic Views."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from models.schema import TopicView


def touch(view: TopicView) -> None:
    view.updated_at = datetime.now(timezone.utc)


RECALL_RATINGS = ("Nailed", "Shaky", "Blanked")
_BOLD_LEAD = re.compile(r"^\s*\*\*(.+?)\*\*\s*(.*)$", re.S)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LONG_POINT = 160
_MIN_LEAD = 20


def split_point(title: str) -> tuple[str, str]:
    """Split a point into (lead, rest) so long points can show the claim first.

    A leading **bold** phrase is the lead. Otherwise a point longer than
    _LONG_POINT characters leads with its first sentence. Short points have no rest.
    """
    text = title.strip()
    bold = _BOLD_LEAD.match(text)
    if bold:
        return bold.group(1).strip(), bold.group(2).strip()
    if len(text) > _LONG_POINT:
        boundary = _SENTENCE_END.search(text)
        if boundary and boundary.start() >= _MIN_LEAD:
            return text[: boundary.start()], text[boundary.end():]
    return text, ""


def view_context(view: TopicView) -> str:
    points = []
    for index, point in enumerate(view.points, 1):
        facts = [
            {
                "text": fact.text,
                "source": fact.source,
                "as_of": fact.as_of,
                "note": fact.note,
            }
            for fact in point.facts if fact.text.strip()
        ]
        points.append({"number": index, "title": point.title, "facts": facts})
    return json.dumps({
        "instruction": (
            "This is hidden context owned by the user. It is a conceptual framework, not a script. "
            "Do not expose it verbatim or require exact wording."
        ),
        "topic": view.name,
        "bottom_line": view.bottom_line,
        "ordered_points": points,
        "counterargument": view.counterargument,
        "what_changes_my_mind": view.changes_my_mind,
    }, ensure_ascii=False, indent=2)


def views_context(views: list[TopicView]) -> str:
    return "# STORED VIEW CONTEXT\n\n" + "\n\n".join(view_context(view) for view in views)
