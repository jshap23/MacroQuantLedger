"""Small JSON-backed store for interview sessions and review history."""
from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Callable

from pydantic import ValidationError

from models.interview import InterviewAnswer, InterviewDatabase, InterviewSession
from models.schema import TopicView
from services.interview_prompts import LEGACY_V2_PROMPT_PACK


INTERVIEW_FILE = Path(__file__).resolve().parent.parent / "data" / "interview_history.json"
_LOCK = RLock()


class InterviewHistoryUnreadable(RuntimeError):
    """The history file exists but could not be parsed.

    Raised instead of returning an empty database so a corrupt or
    schema-invalid file is never silently replaced by the next save.
    """

    def __init__(self, source: Path, backup: Path):
        self.source = source
        self.backup = backup
        super().__init__(
            f"Interview history at {source} could not be read; "
            f"an untouched copy was saved to {backup}."
        )


def _backup_unreadable_history() -> Path:
    """Copy the unreadable history aside, reusing an identical existing backup.

    Backups are named with a timestamp so lexicographic order is chronological.
    A repeated read of the same unreadable file must not litter the folder, so
    the newest backup is reused when it is byte-identical to the current file.
    """
    backup_dir = INTERVIEW_FILE.parent / "backups"
    existing = sorted(backup_dir.glob("interview_history_unreadable_*.json"))
    if existing:
        newest = existing[-1]
        if newest.read_bytes() == INTERVIEW_FILE.read_bytes():
            return newest
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"interview_history_unreadable_{stamp}.json"
    shutil.copy2(INTERVIEW_FILE, backup)
    return backup


def load_database() -> InterviewDatabase:
    with _LOCK:
        try:
            raw = INTERVIEW_FILE.read_text(encoding="utf-8")
        except FileNotFoundError:
            return InterviewDatabase()
        except UnicodeDecodeError as exc:
            # A file that cannot even be decoded is still user data: back it up
            # and surface it rather than returning an empty database.
            backup = _backup_unreadable_history()
            raise InterviewHistoryUnreadable(INTERVIEW_FILE, backup) from exc
        try:
            return InterviewDatabase.model_validate_json(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            backup = _backup_unreadable_history()
            raise InterviewHistoryUnreadable(INTERVIEW_FILE, backup) from exc


def save_database(database: InterviewDatabase) -> None:
    with _LOCK:
        INTERVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = INTERVIEW_FILE.with_suffix(".tmp")
        temp.write_text(database.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(INTERVIEW_FILE)


def save_session(session: InterviewSession) -> None:
    with _LOCK:
        database = load_database()
        for index, existing in enumerate(database.sessions):
            if existing.id == session.id:
                database.sessions[index] = session
                break
        else:
            database.sessions.insert(0, session)
        save_database(database)


def update_session(
    session_id: str, mutate: Callable[[InterviewSession], None],
) -> InterviewSession | None:
    """Apply ``mutate`` to the freshly stored session and save it.

    Background work (the summary, a reference answer, a fact check) makes a slow
    model call between loading a session and saving it. Saving that stale copy
    would erase anything another writer stored in the meantime, so such work
    must do its call first and then change only its own field through here.
    Returns None when the session no longer exists.
    """
    with _LOCK:
        database = load_database()
        for session in database.sessions:
            if session.id == session_id:
                mutate(session)
                save_database(database)
                return session
    return None


def get_session(session_id: str) -> InterviewSession | None:
    return next((s for s in load_database().sessions if s.id == session_id), None)


def effective_rubric_id(session: InterviewSession) -> str:
    """The rubric a session was graded under, derived for legacy sessions.

    Read-time only: never writes to the session or the history file. A session
    that stored ``rubric_id`` returns it verbatim. Legacy sessions are classified
    from what they do record — an explicit prompt override is ``"custom"``, the
    anchored v2 pack is ``"shared-v2"``, and anything older is ``"unanchored"``.
    Phase 1 sessions do record ``prompt_override``, so the override case is
    detectable rather than assumed.
    """
    if session.rubric_id:
        return session.rubric_id
    if session.prompt_override.strip():
        return "custom"
    if session.prompt_pack_version == LEGACY_V2_PROMPT_PACK:
        return "shared-v2"
    return "unanchored"


def effective_input_method(answer: InterviewAnswer) -> str:
    """The answer's input method, derived from ``voice`` for legacy answers."""
    if answer.input_method:
        return answer.input_method
    return "voice" if answer.voice else "typed"


def comparability_key(
    session: InterviewSession, answer: InterviewAnswer,
) -> tuple[str, str, str, str]:
    """The key under which scores may be compared: rubric, grader, preset, input."""
    return (
        effective_rubric_id(session),
        session.model or "",
        session.preset_key,
        effective_input_method(answer),
    )


def trend_eligible(session: InterviewSession, answer: InterviewAnswer) -> bool:
    """Whether an answer's score may join a trend line.

    Requires a completed session and a scored, non-retry answer whose effective
    rubric is a real family. Custom-prompt and unanchored sessions are excluded
    so scores produced under incomparable rubrics are never averaged together.
    """
    return (
        session.status == "completed"
        and not answer.is_retry
        and answer.score is not None
        and effective_rubric_id(session) not in {"custom", "unanchored"}
    )


def trend_session_count() -> int:
    """Sessions app-wide that contribute a current-rubric comparable score.

    A session counts when at least one of its answers is ``trend_eligible()``
    and its effective rubric id is a current ``*-v3`` family. This is the global
    gate for showing trend movement; it is not scoped to any one View.
    """
    count = 0
    for session in load_database().sessions:
        if not effective_rubric_id(session).endswith("-v3"):
            continue
        if any(
            trend_eligible(session, answer)
            for question in session.questions
            for answer in question.answers
        ):
            count += 1
    return count


def preferred_model() -> str:
    return load_database().preferred_model


def save_preferred_model(model: str) -> None:
    with _LOCK:
        database = load_database()
        database.preferred_model = model.strip()
        save_database(database)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to aware UTC for comparison."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def performance_summary() -> dict:
    database = load_database()
    sessions = database.sessions
    # The selected grader. Scores are only comparable within one grader, so
    # score numbers count a session only when it used this model.
    current_grader = database.preferred_model
    completed = [s for s in sessions if s.status == "completed"]
    answered_questions = [q for s in sessions for q in s.questions if q.answers]
    answers = [a for q in answered_questions for a in q.answers]
    # Failure tags are hints for the next prompt, not displayed scores, so they
    # may still come from every session.
    tags = Counter(tag for answer in answers for tag in answer.failure_tags)
    weak_topics: Counter[str] = Counter()
    topic_scores: dict[str, list[int]] = defaultdict(list)
    topic_runs: dict[str, list[tuple[str, datetime, int]]] = defaultdict(list)
    due: list[dict] = []
    review_concepts: list[dict] = []
    topic_last: dict[str, date] = {}
    today = date.today()

    # Sessions are stored newest-first; reverse them for a rough chronological
    # improvement comparison.
    for session in reversed(sessions):
        session_day = session.started_at.date()
        topic_last[session.topic] = max(session_day, topic_last.get(session.topic, session_day))
        for question in session.questions:
            question_topic = question.topic or session.topic
            topic_last[question_topic] = max(session_day, topic_last.get(question_topic, session_day))
            if question.should_return:
                weak_topics[question_topic] += 1
                review_concepts.append({
                    "concept": question.concept or question.text,
                    "topic": question_topic,
                    "priority": question.review_priority,
                })
                if question.next_review_date is None or question.next_review_date <= today:
                    due.append({
                        "concept": question.concept or question.text,
                        "topic": question_topic,
                        "priority": question.review_priority,
                    })
            # Score numbers count only a current rubric family graded by the
            # selected model, from trend_eligible() answers (scored, not retry).
            if not current_grader or session.model != current_grader:
                continue
            if not effective_rubric_id(session).endswith("-v3"):
                continue
            for answer in question.answers:
                if not trend_eligible(session, answer):
                    continue
                topic_scores[question_topic].append(answer.score)
                topic_runs[question_topic].append(
                    (comparability_key(session, answer), answer.submitted_at, answer.score)
                )

    improving: list[str] = []
    for topic, runs in topic_runs.items():
        # Only the topic's most recent comparability key is comparable; an older
        # rubric, grader, preset, or input method must not flag the topic.
        ordered = sorted(
            runs,
            key=lambda run: _as_utc(run[1]) or datetime.min.replace(tzinfo=timezone.utc),
        )
        current_key = ordered[-1][0]
        scores = [score for key, _, score in ordered if key == current_key]
        if len(scores) < 4:
            continue
        split = max(1, len(scores) // 2)
        first, second = scores[:split], scores[split:]
        if second and sum(second) / len(second) > sum(first) / len(first) + 0.5:
            improving.append(topic)

    return {
        "questions_answered": len(answered_questions),
        "sessions_completed": len(completed),
        "tag_counts": tags,
        "tag_total": sum(tags.values()),
        "weak_topics": weak_topics,
        "improving": improving[:5],
        "strong_topics": [
            topic for topic, scores in sorted(
                topic_scores.items(),
                key=lambda item: sum(item[1]) / len(item[1]),
                reverse=True,
            )
            if scores and sum(scores) / len(scores) >= 7
        ][:5],
        "due": sorted(due, key=lambda item: item["priority"], reverse=True)[:10],
        "review_concepts": sorted(
            review_concepts, key=lambda item: item["priority"], reverse=True
        )[:10],
        "stale_topics": [
            topic for topic, _ in sorted(topic_last.items(), key=lambda item: item[1])
            if (today - topic_last[topic]).days >= 21
        ][:5],
    }


def weakness_context() -> str:
    summary = performance_summary()
    if not summary["questions_answered"]:
        return ""
    tags = ", ".join(f"{tag} ({count})" for tag, count in summary["tag_counts"].most_common(5)) or "none yet"
    due = "; ".join(f"{item['topic']}: {item['concept']}" for item in summary["due"][:6]) or "none yet"
    missed = "; ".join(f"{item['topic']}: {item['concept']}" for item in summary["review_concepts"][:6]) or "none yet"
    topics = ", ".join(topic for topic, _ in summary["weak_topics"].most_common(5)) or "none yet"
    strong = ", ".join(summary["strong_topics"]) or "none established yet"
    stale = ", ".join(summary["stale_topics"]) or "none yet"
    return (
        f"Current recurring issues: {tags}. Weak topics: {topics}. "
        f"Recently strong: {strong}. Previously missed concepts: {missed}. Concepts due: {due}. "
        f"Areas not recently practiced: {stale}. Generate variants; do not "
        "repeat old wording."
    )


def mark_review(question, score: int | None, tags: list[str], is_retry: bool) -> None:
    weak = bool(tags) or (score is not None and score <= 6)
    if is_retry and score is not None and score >= 7:
        question.successful_retries += 1
        question.review_priority = max(0, question.review_priority - 1)
        question.next_review_date = date.today() + timedelta(days=14)
        question.should_return = question.review_priority > 0
    elif weak:
        question.should_return = True
        question.review_priority = min(5, question.review_priority + 1)
        delay = 2 if question.review_priority >= 3 else 7
        question.next_review_date = date.today() + timedelta(days=delay)


def recent_answers(
    topic: str | None = None,
    practice_style: str | None = None,
    model: str | None = None,
    limit: int = 10,
    preset_key: str | None = None,
) -> list[dict]:
    """Completed sessions only, newest-first, flattened to individual answers.

    Filters on ``practice_style`` and ``preset_key`` rather than ``mode``: a
    Deliver session has ``mode == "Discussion"`` but ``practice_style ==
    "Deliver"`` and ``preset_key == "view_deliver"``, while a model Defend
    session shares ``practice_style == "Defend"`` with a View Defend session
    and is only distinguished by ``preset_key``.
    """
    rows: list[tuple[datetime, dict]] = []
    for session in load_database().sessions:
        if session.status != "completed":
            continue
        if practice_style is not None and session.practice_style != practice_style:
            continue
        if preset_key is not None and session.preset_key != preset_key:
            continue
        if model is not None and session.model != model:
            continue
        if topic is not None and session.topic != topic:
            continue
        for question in session.questions:
            for answer in question.answers:
                submitted = answer.submitted_at
                if submitted.tzinfo is None:
                    submitted = submitted.replace(tzinfo=timezone.utc)
                rows.append((submitted, {
                    "session_id": session.id,
                    "text": answer.text,
                    "score": answer.score,
                    "failure_tags": list(answer.failure_tags),
                    "is_retry": answer.is_retry,
                    "submitted_at": submitted,
                    "topic": question.topic or session.topic,
                    "practice_style": session.practice_style,
                    "preset_key": session.preset_key,
                    "model": session.model,
                }))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in rows[:max(0, limit)]]


def recent_questions(preset_key: str, limit: int = 15) -> list[str]:
    """Question texts from recent completed sessions for this preset,
    newest-first, whitespace-normalized and deduplicated."""
    questions: list[str] = []
    seen: set[str] = set()
    for session in load_database().sessions:
        if session.status != "completed" or session.preset_key != preset_key:
            continue
        for question in session.questions:
            text = " ".join(question.text.split())
            if not text or text in seen:
                continue
            seen.add(text)
            questions.append(text)
    return questions[:max(0, limit)]


def gone_quiet_tags(
    reps: list[dict], minimum: int = 2, max_streak: int = 10, limit: int = 2,
) -> list[tuple[str, int]]:
    """Tags that went quiet after being an active, recent weakness.

    One absence is noise, so a tag is only called out once it has been absent
    from at least ``minimum`` consecutive reps. It must also have been flagged
    within the last ``max_streak`` reps: a tag last seen deep in the history is
    not a weakness that was fixed, so its absence is padding rather than
    progress. Returns at most ``limit`` streaks, longest first.
    """
    if len(reps) <= minimum:
        return []
    seen = {tag for rep in reps[minimum:] for tag in rep["failure_tags"]}
    results: list[tuple[str, int]] = []
    for tag in seen:
        streak = 0
        for rep in reps:
            if tag in rep["failure_tags"]:
                break
            streak += 1
        if minimum <= streak <= max_streak:
            results.append((tag, streak))
    results.sort(key=lambda item: (-item[1], item[0]))
    return results[:limit]


def practice_pulse(window: int = 20, limit: int = 200) -> dict:
    """Forward-looking signals for the Practice home strip.

    Returns the most persistent recent tag (only when there is a clear leader),
    the count of reps in the last seven days, and tags that have gone quiet
    after being a recent weakness (same gate as the postmortem line, so the two
    surfaces never disagree). Callers omit any empty signal rather than
    rendering a zero.
    """
    reps = recent_answers(limit=limit)
    window_reps = reps[:window]

    most_persistent = None
    if len(window_reps) >= 10:
        counts = Counter(tag for rep in window_reps for tag in rep["failure_tags"])
        ranked = counts.most_common()
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            most_persistent = ranked[0][0]

    not_flagged: list[str] = []
    if len(window_reps) >= 10:
        not_flagged = [tag for tag, _ in gone_quiet_tags(window_reps, limit=2)]

    week = datetime.now(timezone.utc) - timedelta(days=7)
    reps_this_week = sum(1 for rep in reps if rep["submitted_at"] >= week)
    return {
        "most_persistent": most_persistent,
        "reps_this_week": reps_this_week,
        "not_flagged": not_flagged,
    }


def model_practice_stats() -> dict[str, dict]:
    """Per-note practice history for model-note practice sessions.

    Session counts and recency include every note session; score averages count
    only comparable answers — a current rubric family graded by the selected
    model, from trend_eligible() answers (scored, not retry).
    """
    database = load_database()
    current_grader = database.preferred_model
    notes: dict[str, dict] = {}
    for session in database.sessions:
        if not session.model_note_ids:
            continue
        session_day = session.started_at.date()
        comparable = (
            bool(current_grader)
            and session.model == current_grader
            and effective_rubric_id(session).endswith("-v3")
        )
        scores = [
            answer.score
            for question in session.questions
            for answer in question.answers
            if comparable and trend_eligible(session, answer)
        ]
        for note_id in session.model_note_ids:
            note = notes.setdefault(note_id, {"last": None, "sessions": 0, "styles": {}})
            if note["last"] is None or session_day > note["last"]:
                note["last"] = session_day
            note["sessions"] += 1
            style = note["styles"].setdefault(
                session.practice_style, {"last": None, "count": 0, "scores": []},
            )
            if style["last"] is None or session_day > style["last"]:
                style["last"] = session_day
            style["count"] += 1
            style["scores"].extend(scores)
    return {
        note_id: {
            "last_practiced": note["last"],
            "sessions": note["sessions"],
            "by_style": {
                style: {
                    "last": data["last"],
                    "avg_score": (
                        round(sum(data["scores"]) / len(data["scores"]), 1)
                        if data["scores"] else None
                    ),
                    "count": data["count"],
                }
                for style, data in note["styles"].items()
            },
        }
        for note_id, note in notes.items()
    }


def view_practice_stats(window_days: int = 182) -> dict[str, dict]:
    """Per-View scored-practice history, compared only within one key.

    A View's series, latest, previous, best, and deltas come only from sessions
    sharing the comparability key of its most recent eligible session (rubric,
    grader model, preset, input method). Sessions under any other key are counted
    as ``other_key_sessions`` and never averaged into the series. Only
    trend_eligible() answers count, so retries are excluded and ``partial``
    answers (which have scores) are included.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    per_view: dict[str, list[dict]] = {}
    for session in load_database().sessions:
        if session.status != "completed" or not session.view_ids or session.completed_at is None:
            continue
        eligible = [
            answer
            for question in session.questions
            for answer in question.answers
            if trend_eligible(session, answer)
        ]
        if not eligible:
            continue
        completed = _as_utc(session.completed_at)
        scores = [answer.score for answer in eligible]
        key = comparability_key(session, eligible[0])
        run = {
            "completed": completed,
            "date": completed.date(),
            "score": round(sum(scores) / len(scores), 1),
            "key": key,
        }
        for view_id in session.view_ids:
            per_view.setdefault(view_id, []).append(run)

    stats: dict[str, dict] = {}
    for view_id, all_runs in per_view.items():
        ordered = sorted(all_runs, key=lambda run: run["completed"])
        # Only the most recent key defines the series; older keys are counted
        # separately instead of mixing incomparable scores.
        current_key = ordered[-1]["key"]
        runs = [run for run in ordered if run["key"] == current_key]
        other_key_sessions = len(ordered) - len(runs)
        scored_all = sorted(
            (run for run in runs if run["score"] is not None),
            key=lambda run: run["completed"],
        )
        latest = scored_all[-1] if scored_all else None
        previous = scored_all[-2] if len(scored_all) >= 2 else None
        window_runs = [run for run in runs if run["completed"] >= cutoff]
        window_scored = [run for run in window_runs if run["score"] is not None]
        best = max(window_scored, key=lambda run: run["score"]) if window_scored else None
        latest_score = latest["score"] if latest else None
        best_score = best["score"] if best else None
        previous_score = previous["score"] if previous else None
        stats[view_id] = {
            "latest": {"score": latest_score, "date": latest["date"]} if latest else None,
            "previous": {"score": previous_score, "date": previous["date"]} if previous else None,
            "best": {"score": best_score, "date": best["date"]} if best else None,
            "runs_6mo": len(window_runs),
            "scored_runs": len(window_scored),
            # All eligible sessions under the current key (the 10-rep
            # suppression count) and under any other key (never compared).
            "current_key_sessions": len(runs),
            "other_key_sessions": other_key_sessions,
            "delta_vs_best": (
                round(latest_score - best_score, 1)
                if latest_score is not None and best_score is not None else None
            ),
            "delta_vs_prev": (
                round(latest_score - previous_score, 1)
                if latest_score is not None and previous_score is not None else None
            ),
            # Most recent scored runs only, oldest first, for trend display.
            "series": [
                {"score": run["score"], "date": run["date"]} for run in scored_all[-12:]
            ],
        }
    return stats


VIEW_CADENCE_DAYS: dict[str, int] = {"Core": 7, "Normal": 21, "Low Priority": 45}

_PRIORITY_RANK = {"Core": 0, "Normal": 1, "Low Priority": 2}


def view_refresh_target(priority: str) -> int:
    """Days between refreshes for a View of this priority; unknown values fall back to Normal."""
    return VIEW_CADENCE_DAYS.get(priority, VIEW_CADENCE_DAYS["Normal"])


def view_practice_queue(
    views: list[TopicView], *, ghost_limit: int = 3, row_limit: int = 8
) -> list[dict]:
    """Rank non-archived TopicViews for the practice board."""
    now = datetime.now(timezone.utc)
    entries: list[dict] = []
    for view in views:
        target = view_refresh_target(view.priority)
        last = view.practice.last_practiced
        if last is None:
            entries.append({
                "view": view, "section": "next", "ghost": True,
                "days": None, "target": target, "ratio": None, "overdue": True,
            })
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days = (now - last).days
        overdue = days > target
        entries.append({
            "view": view, "section": "next" if overdue else "warm", "ghost": False,
            "days": days, "target": target,
            "ratio": round(days / target, 2), "overdue": overdue,
        })

    original_order = {id(view): index for index, view in enumerate(views)}
    ghosts = [entry for entry in entries if entry["ghost"]]
    ghosts.sort(key=lambda entry: (
        _PRIORITY_RANK.get(entry["view"].priority, 1),
        original_order[id(entry["view"])],
    ))
    overdue = [entry for entry in entries if not entry["ghost"] and entry["overdue"]]
    overdue.sort(key=lambda entry: entry["ratio"], reverse=True)
    warm = [entry for entry in entries if not entry["ghost"] and not entry["overdue"]]
    warm.sort(key=lambda entry: entry["days"])

    return (ghosts[:ghost_limit] + overdue + warm)[:row_limit]
