"""Pure helpers for My Views levels and freshness.

Levels are derived at read time from a View's content and the interview history;
nothing is stored. Freshness is how recently the View was edited or confirmed
("Still holds") relative to its priority's refresh cadence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from models.interview import InterviewSession
from models.schema import TopicView
from storage.interview_store import (
    effective_rubric_id,
    trend_eligible,
    view_refresh_target,
)

LEVEL_NAMES = ("Blank", "Sketch", "Supported", "Rehearsed", "Battle-tested")
MAX_LEVEL = len(LEVEL_NAMES) - 1

REHEARSED_MIN_RUNS = 2
REHEARSED_MIN_SCORE = 5
BATTLE_TESTED_MIN_SCORE = 7

_NEXT_HINT = {
    0: "Add a bottom line and two titled points.",
    1: "Add a counterargument and at least two supporting facts.",
    2: f"Complete {REHEARSED_MIN_RUNS} scored reps, the latest at {REHEARSED_MIN_SCORE}+ (Band 5–6).",
    3: f"Score {BATTLE_TESTED_MIN_SCORE}+ (Band 7–8) in a Defend rep.",
    4: "",
}


@dataclass(frozen=True)
class ViewLevel:
    level: int
    name: str
    next_hint: str


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def confirmed_at(view: TopicView) -> datetime:
    """When the View was last edited or confirmed with "Still holds"."""
    moments = [_as_utc(view.updated_at)]
    if view.reviewed_at is not None:
        moments.append(_as_utc(view.reviewed_at))
    return max(moments)


def days_since_confirmed(view: TopicView, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return max(0, (now - confirmed_at(view)).days)


def freshness_ratio(view: TopicView, now: datetime | None = None) -> float:
    """Age over the View's refresh cadence: 0 is fresh, 1 is due, above 1 is overdue."""
    return days_since_confirmed(view, now) / view_refresh_target(view.priority)


def _content_level(view: TopicView) -> int:
    titled = [point for point in view.points if point.title.strip()]
    if not view.bottom_line.strip() or len(titled) < 2:
        return 0
    facts = sum(1 for point in view.points for fact in point.facts if fact.text.strip())
    if not view.counterargument.strip() or facts < 2:
        return 1
    return 2


def _practice_level(view_id: str, sessions: Iterable[InterviewSession]) -> int:
    """Highest practice level earned under any single grader and rubric.

    Scores are only compared within one rubric and grader model, never across
    them, so switching grader can neither take a level away nor combine reps
    from different graders. Preset and input method are not part of the group:
    the thresholds are fixed bands of one shared rubric, not a trend.
    """
    groups: dict[tuple[str, str], list[tuple[datetime, float, bool]]] = {}
    for session in sessions:
        if session.status != "completed" or view_id not in session.view_ids:
            continue
        completed = session.completed_at
        if completed is None:
            continue
        scores = [
            answer.score
            for question in session.questions
            for answer in question.answers
            if trend_eligible(session, answer)
        ]
        if not scores:
            continue
        key = (effective_rubric_id(session), session.model or "")
        groups.setdefault(key, []).append(
            (
                _as_utc(completed),
                sum(scores) / len(scores),
                session.practice_style == "Defend",
            )
        )

    best = 0
    for runs in groups.values():
        runs.sort(key=lambda run: run[0])
        if len(runs) < REHEARSED_MIN_RUNS or runs[-1][1] < REHEARSED_MIN_SCORE:
            continue
        defended = any(
            is_defend and score >= BATTLE_TESTED_MIN_SCORE
            for _, score, is_defend in runs
        )
        best = max(best, 4 if defended else 3)
    return best


def view_level(view: TopicView, sessions: Iterable[InterviewSession]) -> ViewLevel:
    """The higher of the content level and the practice level.

    Practice only needs a Sketch to count, so reps are never discarded because
    optional content such as supporting facts has not been written.
    """
    level = _content_level(view)
    if level >= 1:
        level = max(level, _practice_level(view.id, sessions))
    return ViewLevel(level, LEVEL_NAMES[level], _NEXT_HINT[level])


def view_levels(
    views: Iterable[TopicView], sessions: Iterable[InterviewSession]
) -> dict[str, ViewLevel]:
    sessions = list(sessions)
    return {view.id: view_level(view, sessions) for view in views}
