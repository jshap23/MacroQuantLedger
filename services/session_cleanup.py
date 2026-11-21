"""Housekeeping for practice sessions left unfinished (status "active")."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from models.interview import InterviewSession
from services.interview_controller import abandon_session
from storage.interview_store import load_database

_log = logging.getLogger(__name__)

STALE_DAYS = 7


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def stale_active_sessions(
    sessions: Iterable[InterviewSession],
    days: int = STALE_DAYS,
    now: datetime | None = None,
) -> list[InterviewSession]:
    """Active sessions started more than ``days`` ago; pure, never modifies anything."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return [
        session
        for session in sessions
        if session.status == "active" and _as_utc(session.started_at) < cutoff
    ]


def abandon_stale_sessions(days: int = STALE_DAYS) -> int:
    """Mark stale unfinished sessions abandoned and return how many changed.

    Uses the controller's own abandon path, so answers are kept and the sessions
    neither count as completed nor touch any View's practice metadata.
    """
    changed = 0
    for session in stale_active_sessions(load_database().sessions, days):
        try:
            abandon_session(session.id)
            changed += 1
        except Exception:
            _log.warning(
                "Could not abandon stale session %s", session.id, exc_info=True
            )
    return changed
