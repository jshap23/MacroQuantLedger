from __future__ import annotations

import json
import re
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


# Anchored scoring rubric for the shared 1-10 score field. Kept as one constant
# so the reference-answer prompt can cite the same 7-8 bar without drifting.
SCORE_RUBRIC = (
    "integer 1-10, graded against this rubric:\n"
    "  1-2  Did not answer the question asked, or the core claim is wrong.\n"
    "  3-4  Relevant content, but no clear bottom line; factors named without mechanism.\n"
    "  5-6  Clear view stated; partial mechanism; evidence thin, vague, or unsupported.\n"
    "  7-8  Bottom line first; at least one causal chain explained end to end; evidence\n"
    "       with magnitudes; states what would falsify the view.\n"
    "  9-10 All of 7-8, plus handles the strongest counterargument and translates the\n"
    "       view into an implementable decision.\n"
    "Grade the answer as given, against the rubric. Do not grade on a curve. Do not\n"
    "withhold 7+ from an answer that meets the 7-8 bar. Most practice answers land\n"
    "3-6; that is expected and is not a reason to compress the scale further."
)

# SCORE_RUBRIC is the only definition of the bands. These patterns read them back
# out of it so the postmortem can print a band verbatim and never drift from the
# rubric text.
_BAND_LINE = re.compile(r"^ {2}(\d+)-(\d+)\s+(.*)$")
_BAND_CONT = re.compile(r"^ {7}(\S.*)$")


def rubric_bands() -> list[tuple[str, str]]:
    """The five rubric bands as (label, descriptor), verbatim from SCORE_RUBRIC.

    Descriptors wrapped over two source lines are joined with a single space so
    a band can be shown on one line without rewording anything.
    """
    bands: list[tuple[str, str]] = []
    current: list[str] | None = None
    for line in SCORE_RUBRIC.splitlines():
        match = _BAND_LINE.match(line)
        if match:
            if current:
                bands.append((current[0], current[1]))
            current = [f"{match.group(1)}-{match.group(2)}", match.group(3).strip()]
            continue
        continuation = _BAND_CONT.match(line)
        if continuation and current:
            current[1] = f"{current[1]} {continuation.group(1).strip()}"
            continue
        if current:
            bands.append((current[0], current[1]))
            current = None
    if current:
        bands.append((current[0], current[1]))
    return bands


def rubric_band_for(score: int | None) -> tuple[str, str, str | None] | None:
    """Map a 1-10 score to (band label, descriptor, next band descriptor).

    The next-band descriptor is None for the top band (9-10), which has no
    higher band to point at.
    """
    if score is None:
        return None
    bands = rubric_bands()
    for index, (label, descriptor) in enumerate(bands):
        low, high = (int(part) for part in label.split("-"))
        if low <= score <= high:
            following = bands[index + 1][1] if index + 1 < len(bands) else None
            return (label, descriptor, following)
    return None


def _system(
    session: InterviewSession, current_session_state: str, transcript_note: bool = False,
) -> str:
    return compose_runtime_prompt(
        preset_key=session.preset_key,
        mode=session.mode,
        practice_state=weakness_context(),
        role=session.role,
        focus_areas=session.focus_areas,
        materials="\n\n".join(part for part in (session.materials, session.view_context) if part),
        model_context=session.model_context,
        current_session_state=current_session_state,
        prompt_override=session.prompt_override,
        transcript_note=transcript_note,
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
    if session.preset_key == "model_explain":
        return f"Walk me through {topic}."
    if session.preset_key == "model_defend":
        return f"Why should I believe {topic} is the right tool for a hard problem?"
    if session.preset_key == "model_compare":
        return f"What is the key difference between {topic}, and when would you pick one over the other?"
    if session.preset_key == "model_deep_dive":
        return f"What exactly is {topic} optimizing?"
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
    model_note_ids: list[str] | None = None,
    model_note_titles: list[str] | None = None,
    model_context: str = "",
    initial_question: str = "",
    surprise: bool = False,
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
        model_note_ids=model_note_ids or [],
        model_note_titles=model_note_titles or [],
        model_context=model_context or "",
        target_questions=max(1, min(50, int(target_questions))),
        weakness_session=weakness_session or preset.key == "weaknesses",
        model=interview_model(model),
        surprise=surprise,
    )
    # The opening question is deterministic. This makes practice immediately
    # available with providers that do not reliably honor JSON mode (notably
    # some DeepSeek-compatible endpoints), while all later turns still use
    # the selected model to respond to the candidate's actual answer.
    opening = initial_question.strip() or _opening_question(session)
    if opening:
        session.questions.append(_question({"question": opening}, session.topic))
        session.compact_brief = session.materials[:1200] or (model_context or "")[:1200]
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
        "score": SCORE_RUBRIC,
        "failure_tags": "array, maximum 3",
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
    voice_origin: bool = False,
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
            {"role": "system", "content": _system(session, json.dumps(prompt), transcript_note=voice_origin)},
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
                {"role": "system", "content": _system(session, json.dumps(prompt), transcript_note=voice_origin)},
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
                {"role": "system", "content": _system(session, json.dumps(prompt), transcript_note=voice_origin)},
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
    tags = [str(tag) for tag in raw_tags if str(tag) in FAILURE_TAGS][:3]
    critique = _compact_critique(data.get("critique"))
    question.answers.append(InterviewAnswer(
        text=answer_text.strip(), score=score, failure_tags=tags,
        critique=critique, is_retry=is_retry, voice=voice_origin,
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


def reference_answer(
    session_id: str,
    provider: LLMProvider | None = None,
) -> str:
    """Return (and cache) a model answer that would score 7-8 on the rubric.

    Strictly click-gated by the UI: this is the only path that produces a model
    answer, and only after the session is over. The result is cached on the
    session so a re-render never re-bills the extra call.
    """
    session = get_session(session_id)
    if session is None or session.status != "completed":
        raise RuntimeError("A reference answer is only available after a completed session.")
    if session.reference_answer:
        return session.reference_answer
    answer_text = ""
    for question in session.questions:
        if question.answers:
            answer_text = question.answers[0].text
            break
    if not answer_text:
        raise RuntimeError("This session has no answer to reference.")
    prompt = {
        "topic": session.topic,
        "stored_view": session.view_context[:6000],
        "candidate_answer": answer_text[:4000],
        "target_rubric": SCORE_RUBRIC,
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": (
                "You are a demanding interview coach. Write one reference answer that would "
                "score 7-8 on the rubric supplied in target_rubric for the given topic, using "
                "the stored View as background. Speak it as if answering the question aloud in "
                "150-200 words: bottom line first, one causal chain explained end to end, "
                "evidence with magnitudes, and what would falsify the view. Do not invent facts "
                "that neither the stored View nor general knowledge supports. Then, under the "
                "heading 'What the strong version does differently', list exactly two or three "
                "short structural differences from the candidate's answer (not word-level edits). "
                "Return plain text only."
            )},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        CompletionOptions(
            model=session.model or interview_model(), max_tokens=650,
            temperature=0.3, json_mode=False,
        ),
    )
    text = raw.strip()
    if not text:
        raise RuntimeError("The interview model did not return a reference answer.")
    session.reference_answer = text
    save_session(session)
    return text
