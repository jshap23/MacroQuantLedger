from __future__ import annotations

import json
from datetime import datetime, timezone

from models.interview import InterviewAnswer, InterviewPostmortem, InterviewQuestion, InterviewSession
from services.interview_llm import (
    CompletionOptions, FAILURE_TAGS, LLMProvider, default_provider,
    interview_model, parse_json_response,
)
from services.interview_prompts import (
    PROMPT_PACK_VERSION, compose_runtime_prompt, get_preset,
)
from storage.interview_store import get_session, mark_review, save_session, weakness_context


def _system(session: InterviewSession, current_session_state: str) -> str:
    return compose_runtime_prompt(
        preset_key=session.preset_key,
        mode=session.mode,
        practice_state=weakness_context(),
        role=session.role,
        focus_areas=session.focus_areas,
        materials="\n\n".join(part for part in (session.materials, session.view_context) if part),
        current_session_state=current_session_state,
        prompt_override=session.prompt_override,
    )


def _question(data: dict, fallback_topic: str) -> InterviewQuestion:
    text = str(data.get("question") or data.get("next_question") or "").strip()
    if not text:
        raise RuntimeError("The interview model did not return a question.")
    return InterviewQuestion(
        text=text,
        topic=str(data.get("topic") or fallback_topic).strip(),
        concept=str(data.get("concept") or "").strip(),
        difficulty=str(data.get("difficulty") or "").strip() or None,
    )


def start_session(
    mode: str,
    topic: str,
    role: str = "",
    focus_areas: str = "",
    materials: str = "",
    target_questions: int = 10,
    weakness_session: bool = False,
    model: str = "",
    preset_key: str = "",
    prompt_override: str = "",
    view_ids: list[str] | None = None,
    practice_style: str = "",
    view_context: str = "",
    provider: LLMProvider | None = None,
) -> InterviewSession:
    preset = get_preset(preset_key, mode)
    session = InterviewSession(
        mode=preset.mode,
        preset_key=preset.key,
        prompt_pack_version=PROMPT_PACK_VERSION,
        prompt_override=prompt_override.strip(),
        topic=topic.strip() or "General professional interview",
        role=role.strip(),
        focus_areas=focus_areas.strip(),
        materials=materials.strip(),
        view_ids=view_ids or [],
        practice_style=practice_style.strip(),
        view_context=view_context.strip(),
        target_questions=max(1, min(50, int(target_questions))),
        weakness_session=weakness_session or preset.key == "weaknesses",
        model=interview_model(model),
    )
    setup = {
        "task": "Start the session with one question.",
        "topic": session.topic,
        "role": session.role,
        "focus_areas": session.focus_areas,
        "target_questions": session.target_questions,
        "preset": preset.label,
        "output_schema": {
            "question": "string", "topic": "string", "concept": "string",
            "difficulty": "optional string",
            "session_brief": "under 120 words: claims/topics to revisit; no coaching",
        },
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": _system(session, json.dumps(setup))},
            {"role": "user", "content": "Start the session with exactly one question using the required JSON schema."},
        ],
        CompletionOptions(model=session.model, max_tokens=220),
    )
    data = parse_json_response(raw)
    session.questions.append(_question(data, session.topic))
    session.compact_brief = str(data.get("session_brief") or session.materials[:1200]).strip()
    save_session(session)
    return session


def _recent_context(session: InterviewSession) -> list[dict]:
    recent = []
    for question in session.questions[-4:]:
        if question.answers:
            answer = question.answers[-1]
            recent.append({"question": question.text, "answer": answer.text[:1800], "tags": answer.failure_tags})
    return recent


def _compact_critique(value) -> str:
    """Enforce the Drill contract even if a provider ignores prompt limits."""
    text = " ".join(str(value or "").split())
    sentence_ends = [index for index, char in enumerate(text) if char in ".!?" ]
    if len(sentence_ends) >= 2:
        text = text[:sentence_ends[1] + 1]
    words = text.split()
    return " ".join(words[:60])


def evaluate_answer(
    session_id: str,
    answer_text: str,
    is_retry: bool = False,
    provider: LLMProvider | None = None,
) -> tuple[InterviewSession, dict]:
    session = get_session(session_id)
    if session is None or session.status != "active" or not session.questions:
        raise RuntimeError("This practice session is no longer active.")
    question = session.questions[-1]
    final_turn = len(session.questions) >= session.target_questions
    prompt = {
        "task": "Evaluate privately, then decide the single next interviewer move. Finish if final_turn is true.",
        "current_question": question.text,
        "candidate_answer": answer_text.strip(),
        "is_retry": is_retry,
        "final_turn": final_turn,
        "recent_context": _recent_context(session),
        "setup": {
            "topic": session.topic, "role": session.role,
            "focus_areas": session.focus_areas, "compact_brief": session.compact_brief,
        },
        "output_schema": {
            "score": "integer 1-10; hidden by UI outside Drill",
            "failure_tags": "array, maximum 2",
            "critique": "maximum 2 sentences and 60 words; empty outside Drill",
            "materially_weak": "boolean",
            "next_question": "one candidate-facing question, or empty if done",
            "next_topic": "string", "concept": "underlying concept", "difficulty": "optional string",
            "done": "boolean",
            "postmortem": {
                "overall_performance": "brief overall assessment or pass likelihood",
                "biggest_problems": "max 3; also used for Work on / Still weak / risks",
                "strongest_areas": "max 3; also used for Strong / Improved",
                "concepts_to_repeat": "short list; also used for Repeat / Next priority",
                "root_causes": {
                    "knowledge": "include questions exposing knowledge gaps when relevant",
                    "evidence/research": "", "reasoning": "",
                    "communication": "include questions where knowledge was present but communication failed when relevant",
                    "pressure handling": "",
                },
                "trend": "improving, unchanged, or worsening when history supports it",
            },
        },
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": _system(session, json.dumps(prompt))},
            {"role": "user", "content": "Make the next interviewer move using the required JSON schema."},
        ],
        CompletionOptions(model=session.model or interview_model(), max_tokens=650 if final_turn else 350),
    )
    data = parse_json_response(raw)
    try:
        score = max(1, min(10, int(data.get("score"))))
    except (TypeError, ValueError):
        score = None
    raw_tags = data.get("failure_tags") if isinstance(data.get("failure_tags"), list) else []
    tags = [str(tag) for tag in raw_tags if str(tag) in FAILURE_TAGS][:2]
    critique = _compact_critique(data.get("critique"))
    question.answers.append(InterviewAnswer(
        text=answer_text.strip(), score=score, failure_tags=tags,
        critique=critique, is_retry=is_retry,
    ))
    mark_review(question, score, tags, is_retry)

    done = bool(data.get("done")) or final_turn
    data.update({"score": score, "failure_tags": tags, "critique": critique, "done": done})
    if done:
        raw_postmortem = data.get("postmortem") if isinstance(data.get("postmortem"), dict) else {}
        def strings(key: str, limit: int = 3) -> list[str]:
            value = raw_postmortem.get(key, [])
            if isinstance(value, str):
                value = [value]
            return [str(item).strip() for item in value if str(item).strip()][:limit] if isinstance(value, list) else []

        roots = raw_postmortem.get("root_causes")
        roots = {str(k): str(v) for k, v in roots.items()} if isinstance(roots, dict) else {}
        session.postmortem = InterviewPostmortem(
            overall_performance=str(raw_postmortem.get("overall_performance") or "Session completed.").strip(),
            biggest_problems=strings("biggest_problems"),
            strongest_areas=strings("strongest_areas"),
            concepts_to_repeat=strings("concepts_to_repeat", 6),
            root_causes=roots,
            trend=str(raw_postmortem.get("trend") or "").strip(),
        )
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        session.pending_move = {}
        _record_view_practice(session)
    else:
        session.pending_move = {
            key: data.get(key) for key in (
                "score", "failure_tags", "critique", "materially_weak",
                "next_question", "next_topic", "concept", "difficulty", "done",
            )
        }
    save_session(session)
    return session, data


def _record_view_practice(session: InterviewSession) -> None:
    """Close the loop without ever rewriting the user's underlying View."""
    if not session.view_ids:
        return
    from storage.persistence import load_state, save_state
    state = load_state()
    diagnostics: list[str] = []
    if session.postmortem:
        diagnostics = (session.postmortem.biggest_problems + session.postmortem.strongest_areas)[:3]
    style = session.practice_style.lower()
    for view in state.topic_views:
        if view.id not in session.view_ids:
            continue
        view.practice.last_practiced = session.completed_at
        view.practice.practice_count += 1
        if style == "deliver":
            view.practice.delivery_attempts += 1
        elif style == "discuss":
            view.practice.discussion_attempts += 1
        elif style == "defend":
            view.practice.defense_attempts += 1
        view.practice.latest_diagnostic = diagnostics
    save_state(state)


def advance_session(session_id: str, result: dict) -> InterviewSession:
    session = get_session(session_id)
    if session is None or session.status != "active":
        raise RuntimeError("This practice session is no longer active.")
    session.questions.append(_question({
        "question": result.get("next_question"),
        "topic": result.get("next_topic") or session.topic,
        "concept": result.get("concept"),
        "difficulty": result.get("difficulty"),
    }, session.topic))
    session.pending_move = {}
    save_session(session)
    return session
