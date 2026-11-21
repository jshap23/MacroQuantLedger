"""Pure helpers for the My Views weekly streak and personal bests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from models.interview import InterviewSession
from models.schema import AppState, TopicView
from storage.interview_store import effective_rubric_id, trend_eligible

ACTIVITY_CAP = 400


def note_activity(state: AppState, today: date | None = None) -> None:
    """Record that the app was used today; the caller saves the state."""
    day = (today or date.today()).isoformat()
    if day in state.activity_days:
        return
    state.activity_days.append(day)
    del state.activity_days[:-ACTIVITY_CAP]


def _local_date(moment: datetime) -> date:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().date()


def activity_dates(state: AppState, sessions: Iterable[InterviewSession]) -> set[date]:
    """Days with a completed practice rep or a recorded My Views action."""
    days: set[date] = set()
    for raw in state.activity_days:
        try:
            days.add(date.fromisoformat(raw))
        except ValueError:
            continue
    for session in sessions:
        if session.status == "completed" and session.completed_at is not None:
            days.add(_local_date(session.completed_at))
    return days


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_streak(days: Iterable[date], today: date | None = None) -> int:
    """Consecutive Monday-start weeks with any activity, ending now.

    An empty current week does not break the streak: it still counts back from
    last week, so the streak only ends once a whole week has passed untouched.
    """
    weeks = {_monday(day) for day in days}
    week = _monday(today or date.today())
    if week not in weeks:
        week -= timedelta(days=7)
    count = 0
    while week in weeks:
        count += 1
        week -= timedelta(days=7)
    return count


def band_index(score: float) -> int:
    """Rubric band 0-4 for a 1-10 score (1-2, 3-4, 5-6, 7-8, 9-10), rounded half up."""
    return (min(10, max(1, int(score + 0.5))) - 1) // 2


def _run_score(session: InterviewSession) -> float | None:
    scores = [
        answer.score
        for question in session.questions
        for answer in question.answers
        if trend_eligible(session, answer)
    ]
    return sum(scores) / len(scores) if scores else None


def is_personal_best(
    session: InterviewSession, sessions: Iterable[InterviewSession]
) -> bool:
    """Whether this rep reached a higher rubric band than any earlier one for the View.

    Compared only against earlier completed reps of the same View, rubric,
    grader model, and practice style, so a different grader or a harder style
    never produces or hides a best. It needs at least one earlier rep, and it
    compares bands rather than raw scores.
    """
    score = _run_score(session)
    if session.status != "completed" or score is None or session.completed_at is None:
        return False
    here = _as_utc(session.completed_at)
    key = (effective_rubric_id(session), session.model or "", session.practice_style)
    views = set(session.view_ids)
    prior = []
    for other in sessions:
        if (
            other.id == session.id
            or other.status != "completed"
            or other.completed_at is None
        ):
            continue
        if not views & set(other.view_ids) or _as_utc(other.completed_at) >= here:
            continue
        if (effective_rubric_id(other), other.model or "", other.practice_style) != key:
            continue
        other_score = _run_score(other)
        if other_score is not None:
            prior.append(band_index(other_score))
    return bool(prior) and band_index(score) > max(prior)


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


DECK_LINKS = ("all", "stale", "shaky", "core")


def deck_for_link(views: list[TopicView], key: str) -> tuple[list[TopicView], str]:
    """Views and ordering for a ``?deck=<key>`` link; an unknown key selects nothing.

    ``all`` keeps the user's order, ``stale`` is the same Views stalest first,
    ``shaky`` is those last rated Shaky or Blanked, and ``core`` is Core priority.
    """
    key = (key or "").strip().lower()
    if key == "all":
        return list(views), "listed"
    if key == "stale":
        return list(views), "stale"
    if key == "shaky":
        return [v for v in views if v.practice.recall_last in ("Shaky", "Blanked")], "listed"
    if key == "core":
        return [v for v in views if v.priority == "Core"], "listed"
    return [], "listed"
