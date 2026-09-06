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
    """Normalize the common question shapes returned by compatible models."""
    value = (
        data.get("question") or data.get("next_question") or data.get("nextQuestion")
        or data.get("text") or ""
    )
    if isinstance(value, dict):
        value = value.get("text") or value.get("question") or value.get("content") or ""
    text = str(value).strip()
    if not text:
        raise RuntimeError("The interview model did not return a question.")
    return InterviewQuestion(
        text=text,
        topic=str(data.get("topic") or fallback_topic).strip(),
        concept=str(data.get("concept") or "").strip(),
        difficulty=str(data.get("difficulty") or "").strip() or None,
    )


def _opening_question(session: InterviewSession) -> str:
    """Provide a reliable first turn without relying on JSON-mode support."""
    topic = session.topic
    if session.preset_key == "quant_drill":
        return f"What is the core intuition behind {topic}?"
    if session.preset_key == "job_interview":
        return f"What makes you a strong fit for {session.role or topic}?"
    if session.preset_key == "research_defense":
        return f"What is your main conclusion on {topic}, and what is the strongest evidence for it?"
    return f"What's your view on {topic}?"


def _has_question(data: dict, fallback_topic: str) -> bool:
    try:
        _question(data, fallback_topic)
        return True
    except RuntimeError:
        return False


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
    initial_question: str = "",
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
    # The opening question is deterministic. This makes practice immediately
    # available with providers that do not reliably honor JSON mode (notably
    # some DeepSeek-compatible endpoints), while all later turns still use
    # the selected model to respond to the candidate's actual answer.
    opening = initial_question.strip() or _opening_question(session)
    if opening:
        session.questions.append(_question({"question": opening}, session.topic))
        session.compact_brief = session.materials[:1200]
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


def _evaluation_schema(final_turn: bool) -> dict:
    """Keep ordinary turns compact; postmortems belong only to the final turn."""
    schema = {
        "score": "integer 1-10; hidden by UI outside Drill",
        "failure_tags": "array, maximum 2",
        "critique": "maximum 2 sentences and 60 words; empty outside Drill",
        "materially_weak": "boolean",
        "next_question": "one candidate-facing question, or empty if done",
        "next_topic": "string", "concept": "underlying concept", "difficulty": "optional string",
        "done": "boolean",
    }
    if final_turn:
        schema["postmortem"] = {
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
        }
    return schema


def _parse_evaluation_data(raw: str) -> dict:
    """Reject incomplete JSON that the generic chat parser treats as prose."""
    data = parse_json_response(raw)
    expected = {
        "score", "failure_tags", "critique", "materially_weak", "next_question",
        "next_topic", "concept", "difficulty", "done", "postmortem",
    }
    if not any(key in data for key in expected):
        raise ValueError("The interview model response did not contain evaluation fields.")
    return data


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
        "output_schema": _evaluation_schema(final_turn),
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": _system(session, json.dumps(prompt))},
            {"role": "user", "content": "Make the next interviewer move using the required JSON schema."},
        ],
        CompletionOptions(model=session.model or interview_model(), max_tokens=650 if final_turn else 350),
    )
    try:
        data = _parse_evaluation_data(raw)
    except (ValueError, json.JSONDecodeError):
        # A provider can still cut off a structured response. Retry once with
        # the already-scoped compact contract instead of losing the answer.
        recovery = llm.complete(
            [
                {"role": "system", "content": _system(session, json.dumps(prompt))},
                {"role": "user", "content": (
                    "Your previous response was malformed. Return valid JSON only using "
                    "the exact required schema, with no preamble or extra fields."
                )},
            ],
            CompletionOptions(model=session.model or interview_model(), max_tokens=650 if final_turn else 350),
        )
        try:
            data = _parse_evaluation_data(recovery)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("The interview model returned malformed structured feedback twice.") from exc
    # A few OpenAI-compatible DeepSeek endpoints emit prose or a partial JSON
    # object despite response_format=json_object. Recover with a tiny plain-
    # text request instead of failing the candidate's submitted answer.
    if not (bool(data.get("done")) or final_turn) and not _has_question(data, session.topic):
        recovery = llm.complete(
            [
                {"role": "system", "content": _system(session, json.dumps(prompt))},
                {"role": "user", "content": "Ask one concise follow-up question only. Return plain text; no JSON, analysis, score, or preamble."},
            ],
            CompletionOptions(
                model=session.model or interview_model(), max_tokens=100,
                temperature=0.2, json_mode=False,
            ),
        )
        recovered = parse_json_response(recovery)
        if _has_question(recovered, session.topic):
            data["next_question"] = _question(recovered, session.topic).text
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
        # Some providers retain the opening-turn field name ("question")
        # despite being asked for "next_question".  _question intentionally
        # accepts both so a valid follow-up cannot be discarded.
        "question": (
            result.get("next_question") or result.get("nextQuestion")
            or result.get("question") or result.get("text")
        ),
        "topic": result.get("next_topic") or session.topic,
        "concept": result.get("concept"),
        "difficulty": result.get("difficulty"),
    }, session.topic))
    session.pending_move = {}
    save_session(session)
    return session


def abandon_session(session_id: str) -> InterviewSession:
    """End a session without scoring it or recording View-practice metadata."""
    session = get_session(session_id)
    if session is None or session.status != "active":
        raise RuntimeError("This practice session is no longer active.")
    session.status = "abandoned"
    session.completed_at = datetime.now(timezone.utc)
    session.pending_move = {}
    save_session(session)
    return session


def answer_tips(
    session_id: str,
    answer_text: str,
    provider: LLMProvider | None = None,
) -> str:
    """Coach a draft without evaluating, saving, or advancing the session."""
    session = get_session(session_id)
    if session is None or session.status != "active" or not session.questions:
        raise RuntimeError("This practice session is no longer active.")
    draft = answer_text.strip()
    if not draft:
        raise ValueError("Write a draft before requesting tips.")
    question = session.questions[-1]
    prompt = {
        "current_question": question.text,
        "draft_answer": draft,
        "session_topic": session.topic,
        "stored_view_context": session.view_context[:6000],
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": (
                "You are a concise interview-answer coach. Give exactly 3 short, actionable "
                "tips for improving the candidate's draft before they submit it. Prioritize: "
                "(1) answering the question up front and structure, (2) missing causal mechanism "
                "or reasoning, and (3) evidence, caveat, or likely pushback when relevant. Do not "
                "score the answer, ask another question, or write a replacement answer. The stored "
                "View context is optional secondary reference material; it may be stale, so do not "
                "treat it as authoritative or force it into the answer. Return plain text with three "
                "numbered tips only."
            )},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        CompletionOptions(
            model=session.model or interview_model(), max_tokens=300,
            temperature=0.25, json_mode=False,
        ),
    )
    return raw.strip() or "No tips were returned. Review the answer for a clear conclusion and supporting mechanism."
