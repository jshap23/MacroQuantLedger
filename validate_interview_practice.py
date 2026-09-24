"""Standalone validation script for interview practice persistence and fixes.

Run with: python validate_interview_practice.py

All scenarios use temporary directories; the live data/interview_history.json is
never touched. Cases 1-3 cover Task 1 (never lose history when the file is
unreadable); cases 4-14 cover the validated per-turn evaluation, the
single-repair call budget (Tasks 2 and 3), provider-vs-output failures
(Task 4), controller-owned session end (Task 5), and honest postmortems
(Tasks 6 and 7).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from models.interview import (
    InterviewAnswer, InterviewDatabase, InterviewPostmortem, InterviewQuestion,
    InterviewSession,
)
from services import interview_controller as controller
from services.interview_controller import (
    EVAL_MAX_TOKENS,
    FALLBACK_FOLLOW_UP,
    RUBRICS,
    _evaluation_schema,
    band_visible,
    evaluate_answer,
    session_band,
    start_session,
)
from services.interview_llm import (
    CompletionOptions, InterviewOutputError, InterviewProviderError,
    OpenAICompatibleProvider,
)
from services.interview_prompts import (
    LEGACY_V2_PROMPT_PACK, PRESETS, PROMPT_PACK_VERSION,
)
from storage import interview_store as store
from storage.interview_store import (
    InterviewHistoryUnreadable,
    comparability_key,
    effective_input_method,
    effective_rubric_id,
    load_database,
    save_session,
    trend_eligible,
)


def _temp_history_file() -> Path:
    tmp = Path(tempfile.mkdtemp())
    return tmp / "interview_history.json"


def _patch_history_file(path: Path) -> None:
    store.INTERVIEW_FILE = path


def _backups_for(path: Path) -> list[Path]:
    return sorted((path.parent / "backups").glob("interview_history_unreadable_*.json"))


def _legacy_payload() -> dict:
    """A file as written by the pre-Task-2 schema.

    Answers carry no ``fix``/``evaluation_status`` and the postmortem keeps the
    old ``"Session completed."`` default text.
    """
    return {
        "preferred_model": "z-ai/glm-5.3",
        "sessions": [
            {
                "id": "legacy-session-1",
                "mode": "Drill",
                "topic": "Term premium",
                "status": "completed",
                "questions": [
                    {
                        "id": "q1",
                        "text": "What drives the term premium?",
                        "answers": [
                            {
                                "text": "Supply and policy uncertainty.",
                                "score": 6,
                                "failure_tags": ["hand-waving"],
                                "critique": "Mechanism was asserted, not shown.",
                            }
                        ],
                    }
                ],
                "postmortem": {
                    "overall_performance": "Session completed.",
                    "biggest_problems": [],
                    "strongest_areas": [],
                    "concepts_to_repeat": [],
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Fake provider harness for the controller tests.
# ---------------------------------------------------------------------------


class FakeProvider:
    """Returns scripted strings (or raises scripted exceptions) and records calls."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, messages, options: CompletionOptions) -> str:
        self.calls.append({"messages": messages, "options": options})
        if not self.responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


MARK_REVIEW_SCORES: list[int | None] = []


def _install_controller_stubs() -> None:
    """Stub history-dependent context and spy on mark_review for the run."""
    controller.weakness_context = lambda: ""
    real_mark_review = controller.mark_review

    def spy(question, score, tags, is_retry):
        MARK_REVIEW_SCORES.append(score)
        return real_mark_review(question, score, tags, is_retry)

    controller.mark_review = spy


def _new_session(**overrides) -> InterviewSession:
    """Start a non-final Drill session against a fresh temp history file."""
    _patch_history_file(_temp_history_file())
    params = {
        "mode": "Drill", "topic": "Term premium", "preset_key": "quant_drill",
        "model": "test-model", "target_questions": 6,
    }
    params.update(overrides)
    return start_session(**params)


def _json(payload: dict) -> str:
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Task 1: never lose history.
# ---------------------------------------------------------------------------


def test_unreadable_history_is_backed_up_not_wiped() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    payload = _legacy_payload()
    payload["sessions"][0]["status"] = "needs_review"  # not a valid Literal
    original = json.dumps(payload, indent=2).encode("utf-8")
    history.write_bytes(original)

    raised: InterviewHistoryUnreadable | None = None
    try:
        load_database()
    except InterviewHistoryUnreadable as exc:
        raised = exc
    assert raised is not None, "load_database must not swallow an invalid history file"
    assert raised.source == history
    assert raised.backup.exists()
    assert raised.backup.read_bytes() == original
    assert history.read_bytes() == original, "original file must be byte-identical"
    assert _backups_for(history) == [raised.backup]

    # A following save must not overwrite the unreadable file.
    session = InterviewSession(mode="Drill", topic="Rates")
    try:
        save_session(session)
    except InterviewHistoryUnreadable:
        pass
    else:
        raise AssertionError("save_session must refuse to overwrite an unreadable history")
    assert history.read_bytes() == original
    # save_session went through load_database again: an identical file must
    # reuse its existing backup rather than writing another.
    assert _backups_for(history) == [raised.backup], "identical unreadable file must reuse its backup"
    print("PASS: unreadable history is backed up and never overwritten")


def test_undecodable_history_is_backed_up() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    original = b"\xff\xfe\x00\x00 not valid utf-8"
    history.write_bytes(original)

    raised: InterviewHistoryUnreadable | None = None
    try:
        load_database()
    except InterviewHistoryUnreadable as exc:
        raised = exc
    assert raised is not None, "an undecodable history file must not be treated as empty"
    assert raised.source == history
    assert raised.backup.exists()
    assert raised.backup.read_bytes() == original
    assert history.read_bytes() == original
    print("PASS: undecodable history is backed up, not treated as empty")


def test_missing_history_returns_empty_and_first_save_creates_file() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    assert not history.exists()

    database = load_database()
    assert isinstance(database, InterviewDatabase)
    assert database.sessions == []
    assert database.preferred_model == ""

    session = InterviewSession(mode="Drill", topic="Rates")
    save_session(session)
    assert history.exists()
    reloaded = load_database()
    assert [s.id for s in reloaded.sessions] == [session.id]
    print("PASS: missing history loads empty; first save creates the file")


def test_legacy_history_loads_without_error() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    history.write_text(json.dumps(_legacy_payload(), indent=2), encoding="utf-8")

    database = load_database()
    session = database.sessions[0]
    assert session.status == "completed"
    answer = session.questions[0].answers[0]
    assert answer.score == 6
    assert answer.failure_tags == ["hand-waving"]
    assert answer.critique == "Mechanism was asserted, not shown."
    assert answer.fix == ""
    assert answer.evaluation_status == ""
    postmortem = session.postmortem
    assert postmortem is not None
    assert postmortem.overall_performance == "Session completed."
    # InterviewPostmortem.status arrives in Task 6; stay tolerant until then.
    assert getattr(postmortem, "status", "") == ""
    print("PASS: legacy history loads without error")


# ---------------------------------------------------------------------------
# Tasks 2 and 3: validated evaluation and one repair per turn.
# ---------------------------------------------------------------------------


def test_incomplete_evaluation_twice_raises_and_saves_nothing() -> None:
    session = _new_session()
    provider = FakeProvider([_json({"next_question": "Why?"})] * 2)
    try:
        evaluate_answer(session.id, "My answer.", provider=provider)
    except InterviewOutputError:
        pass
    else:
        raise AssertionError("an incomplete evaluation twice must raise InterviewOutputError")
    assert len(provider.calls) == 2
    reloaded = load_database()
    stored = next(s for s in reloaded.sessions if s.id == session.id)
    assert stored.questions[-1].answers == []
    print("PASS: incomplete evaluation twice raises and saves nothing")


def test_valid_evaluation_saves_ok_in_one_call() -> None:
    session = _new_session()
    provider = FakeProvider([_json({
        "score": "7/10",
        "critique": "Mechanism was asserted, not shown.",
        "fix": "State the causal chain before the conclusion.",
        "next_question": "What evidence supports that?",
    })])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 1
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert answer.evaluation_status == "ok"
    assert answer.fix == "State the causal chain before the conclusion."
    assert result["done"] is False
    print("PASS: valid evaluation saves score 7 as ok in one call")


def test_empty_critique_triggers_one_repair_with_1_5x_budget() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "Do X.", "next_question": "Why?"}),
        _json({"score": 7, "critique": "Say the mechanism.", "fix": "Do X.", "next_question": "Why?"}),
    ])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    first, retry = provider.calls
    assert first["options"].max_tokens == EVAL_MAX_TOKENS
    assert retry["options"].max_tokens == int(EVAL_MAX_TOKENS * 1.5)
    assert updated.questions[-1].answers[-1].evaluation_status == "ok"
    print("PASS: empty critique triggers one repair at 1.5x budget")


def test_empty_critique_twice_saves_partial() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 6, "critique": "", "fix": "", "next_question": "Why?"}),
        _json({"score": 6, "critique": "", "fix": "", "next_question": "Why?"}),
    ])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 6
    assert answer.evaluation_status == "partial"
    print("PASS: score with no critique on both calls saves as partial")


def test_unusable_repair_keeps_the_first_partial_and_its_question() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "", "next_question": "What evidence supports that?"}),
        "not valid json at all",
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert answer.evaluation_status == "partial"
    assert result["next_question"] == "What evidence supports that?"
    assert updated.pending_move["next_question"] == "What evidence supports that?"
    print("PASS: unusable repair keeps the first partial evaluation and its question")


def test_repair_empty_response_keeps_first_valid_score() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "Do X.", "next_question": "Why?"}),
        InterviewOutputError("empty content"),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert answer.evaluation_status == "partial"
    assert result["next_question"] == "Why?"
    print("PASS: an empty repair response keeps the first valid score and its question")


def test_recovery_empty_response_falls_back_to_follow_up() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "Fine.", "fix": "Do X."}),
        InterviewOutputError("empty content"),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    assert updated.questions[-1].answers[-1].score == 7
    assert result["next_question"] == FALLBACK_FOLLOW_UP
    print("PASS: an empty recovery response falls back to FALLBACK_FOLLOW_UP")


def test_provider_failure_during_repair_aborts_the_turn() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "Do X.", "next_question": "Why?"}),
        InterviewProviderError("rate limited"),
    ])
    try:
        evaluate_answer(session.id, "My answer.", provider=provider)
    except InterviewProviderError:
        pass
    else:
        raise AssertionError("a provider failure during repair must abort the turn")
    reloaded = load_database()
    stored = next(s for s in reloaded.sessions if s.id == session.id)
    assert stored.questions[-1].answers == []
    print("PASS: a provider failure during repair aborts the turn and saves nothing")


def test_malformed_then_valid_without_question_uses_fallback() -> None:
    session = _new_session()
    provider = FakeProvider([
        "not valid json at all",
        _json({"score": 7, "critique": "Mechanism missing.", "fix": "Show the chain."}),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    assert result["next_question"] == FALLBACK_FOLLOW_UP
    assert updated.pending_move["next_question"] == FALLBACK_FOLLOW_UP
    print("PASS: malformed JSON then valid without a question uses FALLBACK_FOLLOW_UP")


def test_model_done_flag_cannot_end_a_session_early() -> None:
    session = _new_session(mode="Discussion", preset_key="view_discuss", target_questions=6)
    provider = FakeProvider([_json({
        "score": 7, "critique": "Clear view.", "fix": "Add evidence.",
        "next_question": "Why does that matter?", "done": True,
    })])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert result["done"] is False
    assert updated.status == "active"
    assert "questions_remaining" in provider.calls[0]["messages"][0]["content"]
    assert updated.pending_move["next_question"] == "Why does that matter?"
    print("PASS: a model done flag cannot end a session early; questions_remaining is sent")


def test_final_postmortem_aliases_map_and_mark_ok() -> None:
    session = _new_session(target_questions=1)
    provider = FakeProvider([_json({
        "score": 7, "critique": "Bottom line was late.", "fix": "Lead with the view.",
        "postmortem": {
            "overall_performance": "Solid; would likely pass.",
            "strengths": ["Clear mechanism"],
            "weaknesses": ["Thin evidence"],
            "next_steps": ["Add magnitudes"],
        },
    })])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 1
    assert updated.status == "completed"
    post = updated.postmortem
    assert post.status == "ok"
    assert post.strongest_areas == ["Clear mechanism"]
    assert post.biggest_problems == ["Thin evidence"]
    assert post.concepts_to_repeat == ["Add magnitudes"]
    print("PASS: final postmortem aliases map to canonical fields with status ok")


def test_missing_postmortem_twice_completes_as_missing() -> None:
    session = _new_session(target_questions=1)
    response = _json({
        "score": 7, "critique": "Bottom line was late.", "fix": "Lead with the view.",
    })
    provider = FakeProvider([response, response])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert updated.status == "completed"
    post = updated.postmortem
    assert post.status == "missing"
    assert post.overall_performance == ""
    print("PASS: a missing postmortem twice completes as missing without a fake summary")


def test_rank_picks_first_evaluation_and_keeps_repair_postmortem() -> None:
    session = _new_session(target_questions=1)
    provider = FakeProvider([
        _json({"score": 7, "critique": "First critique.", "fix": "First fix."}),
        _json({
            "score": 7, "critique": "", "fix": "",
            "postmortem": {
                "overall_performance": "Repair summary.",
                "biggest_problems": ["p"],
                "strongest_areas": ["s"],
                "concepts_to_repeat": ["c"],
            },
        }),
    ])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    # The first evaluation is 'ok'; the repair is 'partial' with the postmortem.
    assert answer.evaluation_status == "ok"
    assert answer.critique == "First critique."
    assert updated.postmortem.status == "ok"
    assert updated.postmortem.overall_performance == "Repair summary."
    print("PASS: rank picks the first evaluation; the repair's postmortem is kept")


class _ExplodingCompletions:
    def create(self, **kwargs):
        raise ConnectionError("connection reset by peer")


class _ExplodingChat:
    completions = _ExplodingCompletions()


class _ExplodingClient:
    chat = _ExplodingChat()


class ProviderFailureProvider:
    """Simulates a provider whose transport call raises."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, options):
        self.calls += 1
        raise InterviewProviderError("connection reset by peer")


def test_sdk_failure_is_wrapped_as_provider_error() -> None:
    provider = object.__new__(OpenAICompatibleProvider)
    provider.client = _ExplodingClient()
    try:
        provider.complete([{"role": "user", "content": "hi"}], CompletionOptions(model="test"))
    except InterviewProviderError:
        pass
    else:
        raise AssertionError("an SDK failure must surface as InterviewProviderError")
    print("PASS: SDK failure is wrapped as InterviewProviderError")


def test_provider_failure_surfaces_and_saves_nothing() -> None:
    session = _new_session()
    provider = ProviderFailureProvider()
    try:
        evaluate_answer(session.id, "My answer.", provider=provider)
    except InterviewProviderError:
        pass
    else:
        raise AssertionError("a provider failure must surface as InterviewProviderError")
    assert provider.calls == 1
    reloaded = load_database()
    stored = next(s for s in reloaded.sessions if s.id == session.id)
    assert stored.questions[-1].answers == []
    print("PASS: provider failure surfaces and saves nothing")


def test_turn_schema_requires_fix_and_drops_empty_outside_drill() -> None:
    # The schema is preset-independent; iterating documents that no preset can
    # reintroduce the old "empty outside Drill" wording or drop the fix field.
    for key in PRESETS:
        schema = _evaluation_schema(final_turn=False)
        text = json.dumps(schema)
        assert "empty outside Drill" not in text, key
        assert "fix" in schema, key
        assert schema["failure_tags"] == "array of 0-3 tag strings", key
    print("PASS: every preset's turn-1 schema requires fix and drops 'empty outside Drill'")


def test_session_band_excludes_retries_and_hides_when_missing() -> None:
    def answer(score, is_retry=False):
        return InterviewAnswer(text="x", score=score, is_retry=is_retry)

    session = InterviewSession(
        mode="Drill", topic="Term premium", status="completed",
        prompt_pack_version=PROMPT_PACK_VERSION,
        questions=[InterviewQuestion(text="q", answers=[answer(8), answer(2, is_retry=True)])],
        postmortem=InterviewPostmortem(
            overall_performance="ok", biggest_problems=["p"], strongest_areas=["s"],
            concepts_to_repeat=["c"], status="ok",
        ),
    )
    band = session_band(session)
    assert band is not None
    # Average of first attempts is 8. Including the retry's 2 would make it 5-6.
    assert band[0] == "7-8", band

    session.postmortem.status = "missing"
    assert session_band(session) is None
    print("PASS: band excludes retries and hides when the postmortem is missing")


def test_mark_review_never_receives_a_missing_score() -> None:
    assert MARK_REVIEW_SCORES, "expected at least one scored answer from cases 4-8"
    assert all(score is not None for score in MARK_REVIEW_SCORES), MARK_REVIEW_SCORES
    print("PASS: mark_review never received a missing score")


# ---------------------------------------------------------------------------
# Phase 2 batch A (Tasks 1-2): provenance, comparability, and rubric families.
# ---------------------------------------------------------------------------


def test_p1_legacy_rubric_ids_and_history_untouched() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    payload = {
        "preferred_model": "z-ai/glm-5.3",
        "sessions": [
            {
                "id": "p1-v2", "mode": "Drill", "topic": "Term premium",
                "status": "completed", "prompt_pack_version": LEGACY_V2_PROMPT_PACK,
            },
            {
                "id": "p1-old", "mode": "Drill", "topic": "Rates",
                "status": "completed", "prompt_pack_version": "2025.01.01-v1",
            },
        ],
    }
    history.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    before = history.read_bytes()

    database = load_database()
    by_id = {session.id: session for session in database.sessions}
    assert by_id["p1-v2"].rubric_id == "", "a legacy session must load with no stored rubric_id"
    assert effective_rubric_id(by_id["p1-v2"]) == "shared-v2"
    assert effective_rubric_id(by_id["p1-old"]) == "unanchored"
    assert history.read_bytes() == before, "reading must never rewrite the history file"
    print("PASS: P1 legacy rubric ids derive as shared-v2 / unanchored and history is byte-identical")


def test_p2_input_method_derives_and_records() -> None:
    assert effective_input_method(InterviewAnswer(text="legacy", voice=True)) == "voice"
    assert effective_input_method(InterviewAnswer(text="typed")) == "typed"

    session = _new_session()
    provider = FakeProvider([_json({
        "score": 7, "critique": "Mechanism missing.", "fix": "Show the chain.",
        "next_question": "Why?",
    })])
    updated, _ = evaluate_answer(
        session.id, "My spoken answer.", voice_origin=True, provider=provider,
    )
    answer = updated.questions[-1].answers[-1]
    assert answer.input_method == "voice", "a voice-origin answer must store input_method=voice"
    assert answer.voice is True
    assert effective_input_method(answer) == "voice"
    assert comparability_key(updated, answer) == (
        "technical-v3", "test-model", "quant_drill", "voice",
    )
    print("PASS: P2 input method derives from voice and new answers store it")


def test_p3_trend_eligible_rejects_incomparable_answers() -> None:
    def session_with(**answer_kwargs) -> tuple[InterviewSession, InterviewAnswer]:
        answer = InterviewAnswer(text="x", **answer_kwargs)
        session = InterviewSession(
            mode="Drill", topic="Term premium", status="completed",
            rubric_id="argument-v3",
            questions=[InterviewQuestion(text="q", answers=[answer])],
        )
        return session, answer

    cases = {
        "retry": session_with(score=7, is_retry=True),
        "no score": session_with(score=None),
        "active session": (
            InterviewSession(
                mode="Drill", topic="Term premium", status="active",
                rubric_id="argument-v3",
                questions=[InterviewQuestion(
                    text="q", answers=[InterviewAnswer(text="x", score=7)],
                )],
            ),
            None,
        ),
    }
    for label, (session, answer) in cases.items():
        answer = answer or session.questions[0].answers[0]
        assert not trend_eligible(session, answer), label

    custom, custom_answer = session_with(score=8)
    custom.rubric_id = "custom"
    assert not trend_eligible(custom, custom_answer), "custom session"

    unanchored, unanchored_answer = session_with(score=8)
    unanchored.rubric_id = "unanchored"
    assert not trend_eligible(unanchored, unanchored_answer), "unanchored session"

    eligible, eligible_answer = session_with(score=7)
    assert trend_eligible(eligible, eligible_answer), "a scored non-retry v3 answer is eligible"
    print("PASS: P3 trend_eligible is false for retries, missing scores, custom, unanchored, and active")


def test_p4_presets_have_a_family_and_family_rubric() -> None:
    families = {"argument", "technical", "interview"}
    for key, preset in PRESETS.items():
        family = preset.rubric_family
        assert family in families, f"{key} has rubric_family={family!r}"
        schema = _evaluation_schema(final_turn=False, rubric_family=family)
        score_desc = schema["score"]
        assert RUBRICS[family][1] in score_desc, f"{key} schema must carry its own rubric"
        for other in families - {family}:
            assert RUBRICS[other][1] not in score_desc, f"{key} schema leaked {other} rubric"
    print("PASS: P4 every preset has a family and its own rubric text, not the others'")


def test_p5_start_session_stores_family_rubric_id() -> None:
    _patch_history_file(_temp_history_file())
    argument = start_session(
        mode="Discussion", topic="Term premium", preset_key="view_deliver", target_questions=3,
    )
    technical = start_session(
        mode="Drill", topic="Term premium", preset_key="quant_drill", target_questions=3,
    )
    interview = start_session(
        mode="Simulation", topic="Term premium", preset_key="job_interview", target_questions=3,
    )
    custom = start_session(
        mode="Discussion", topic="Term premium", preset_key="view_deliver",
        target_questions=3, prompt_override="Act as my own interviewer.",
    )
    assert argument.rubric_id == "argument-v3"
    assert technical.rubric_id == "technical-v3"
    assert interview.rubric_id == "interview-v3"
    assert custom.rubric_id == "custom", "a prompt override must be marked custom"
    print("PASS: P5 start_session stores each family rubric id and custom for overrides")


def test_p6_band_gate_keeps_phase1_and_hides_incomparable() -> None:
    assert PROMPT_PACK_VERSION != LEGACY_V2_PROMPT_PACK, "Task 2 must bump the prompt pack"

    def session(**overrides) -> InterviewSession:
        params = {
            "mode": "Drill", "topic": "Term premium", "status": "completed",
            "prompt_pack_version": LEGACY_V2_PROMPT_PACK,
            "questions": [InterviewQuestion(
                text="q", answers=[InterviewAnswer(text="x", score=8)],
            )],
            "postmortem": InterviewPostmortem(
                overall_performance="ok", biggest_problems=["p"],
                strongest_areas=["s"], concepts_to_repeat=["c"], status="ok",
            ),
        }
        params.update(overrides)
        return InterviewSession(**params)

    phase1 = session()
    assert band_visible(phase1), "a Phase 1 anchored session still shows its band"
    assert session_band(phase1) is not None

    assert not band_visible(session(prompt_override="Custom.")), "custom sessions hide the band"
    assert not band_visible(session(prompt_pack_version="2025.01.01-v1")), \
        "unanchored sessions hide the band"
    print("PASS: P6 band shows for Phase 1 and hides for custom and unanchored sessions")


def main() -> None:
    print("Validating interview practice persistence and evaluation...\n")
    _install_controller_stubs()
    test_unreadable_history_is_backed_up_not_wiped()
    test_undecodable_history_is_backed_up()
    test_missing_history_returns_empty_and_first_save_creates_file()
    test_legacy_history_loads_without_error()
    test_incomplete_evaluation_twice_raises_and_saves_nothing()
    test_valid_evaluation_saves_ok_in_one_call()
    test_empty_critique_triggers_one_repair_with_1_5x_budget()
    test_empty_critique_twice_saves_partial()
    test_unusable_repair_keeps_the_first_partial_and_its_question()
    test_repair_empty_response_keeps_first_valid_score()
    test_recovery_empty_response_falls_back_to_follow_up()
    test_provider_failure_during_repair_aborts_the_turn()
    test_malformed_then_valid_without_question_uses_fallback()
    test_model_done_flag_cannot_end_a_session_early()
    test_final_postmortem_aliases_map_and_mark_ok()
    test_missing_postmortem_twice_completes_as_missing()
    test_rank_picks_first_evaluation_and_keeps_repair_postmortem()
    test_turn_schema_requires_fix_and_drops_empty_outside_drill()
    test_sdk_failure_is_wrapped_as_provider_error()
    test_provider_failure_surfaces_and_saves_nothing()
    test_session_band_excludes_retries_and_hides_when_missing()
    test_mark_review_never_receives_a_missing_score()
    test_p1_legacy_rubric_ids_and_history_untouched()
    test_p2_input_method_derives_and_records()
    test_p3_trend_eligible_rejects_incomparable_answers()
    test_p4_presets_have_a_family_and_family_rubric()
    test_p5_start_session_stores_family_rubric_id()
    test_p6_band_gate_keeps_phase1_and_hides_incomparable()
    print("\nAll validation scenarios passed.")


if __name__ == "__main__":
    main()
