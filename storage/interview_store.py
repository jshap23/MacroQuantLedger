"""Small JSON-backed store for interview sessions and review history."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from threading import RLock

from models.interview import InterviewDatabase, InterviewSession


INTERVIEW_FILE = Path(__file__).resolve().parent.parent / "data" / "interview_history.json"
_LOCK = RLock()


def load_database() -> InterviewDatabase:
    with _LOCK:
        try:
            return InterviewDatabase.model_validate_json(INTERVIEW_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return InterviewDatabase()


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


def get_session(session_id: str) -> InterviewSession | None:
    return next((s for s in load_database().sessions if s.id == session_id), None)


def preferred_model() -> str:
    return load_database().preferred_model


def save_preferred_model(model: str) -> None:
    with _LOCK:
        database = load_database()
        database.preferred_model = model.strip()
        save_database(database)


def performance_summary() -> dict:
    sessions = load_database().sessions
    completed = [s for s in sessions if s.status == "completed"]
    answered_questions = [q for s in sessions for q in s.questions if q.answers]
    answers = [a for q in answered_questions for a in q.answers]
    tags = Counter(tag for answer in answers for tag in answer.failure_tags)
    weak_topics: Counter[str] = Counter()
    topic_scores: dict[str, list[int]] = defaultdict(list)
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
            scores = [a.score for a in question.answers if a.score is not None]
            if scores:
                topic_scores[question_topic].extend(scores)
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

    improving: list[str] = []
    for topic, scores in topic_scores.items():
        if len(scores) >= 4:
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


def model_practice_stats() -> dict[str, dict]:
    """Per-note practice history for model-note practice sessions."""
    notes: dict[str, dict] = {}
    for session in load_database().sessions:
        if not session.model_note_ids:
            continue
        session_day = session.started_at.date()
        scores = [
            answer.score
            for question in session.questions
            for answer in question.answers
            if answer.score is not None
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
