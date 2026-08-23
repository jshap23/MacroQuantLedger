"""Pure helpers and lightweight AI suggestions for structured topic Views."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from models.schema import TopicView
from services.interview_llm import CompletionOptions, default_provider, interview_model, parse_json_response


def touch(view: TopicView) -> None:
    view.updated_at = datetime.now(timezone.utc)


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


def _complete(task: str, payload: dict, schema: dict, max_tokens: int = 900) -> dict:
    prompt = (
        "You help a user structure their own investment and macro views. Be concise. "
        "Never fabricate facts, sources, dates, or the user's beliefs. Treat uncertain note fragments as proposals. "
        "Return JSON only and do not add fields outside the schema.\n\n"
        + json.dumps({"task": task, "input": payload, "output_schema": schema}, ensure_ascii=False)
    )
    raw = default_provider().complete(
        [{"role": "system", "content": prompt}, {"role": "user", "content": "Return the concise structured suggestion."}],
        CompletionOptions(model=interview_model(), max_tokens=max_tokens),
    )
    return parse_json_response(raw)


def structure_notes(topic: str, notes: str) -> dict:
    return _complete(
        "Convert messy notes into a proposed structured View. Use 2–4 points. Keep facts short. Do not invent evidence.",
        {"topic": topic, "notes": notes[:12000]},
        {
            "bottom_line": "1–3 sentence proposal",
            "points": [{"title": "concise claim", "facts": ["short fact or note fragment"]}],
            "counterargument": "concise proposal",
            "changes_my_mind": "concise proposal",
        },
    )


def improve_flow(view: TopicView) -> dict:
    return _complete(
        "Recommend a spoken ordering only. Do not rewrite content.",
        {"topic": view.name, "bottom_line": view.bottom_line, "points": [
            {"id": point.id, "title": point.title} for point in view.points
        ]},
        {"ordered_point_ids": ["existing point id"], "reason": "one concise rationale"},
        350,
    )


def challenge_view(view: TopicView) -> dict:
    return _complete(
        "Pressure-test this View. Identify the weakest point, missing evidence, unsupported assumptions, counterargument, and logical gaps. Do not rewrite it.",
        json.loads(view_context(view)),
        {"observations": ["maximum five concise, actionable observations"]},
        500,
    )
