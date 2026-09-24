# MacroQuantLedger Interview Practice — Implementation Brief for Coding Agent

Sep 24, 2026 · @Anna Di

## How to use this brief

Implement **Phase 1 only** in this pass. Phases 2 and 3 are described so your Phase 1 choices don't block them; do not start them.

Ground rules:

- Read `AGENTS.md` before touching code and follow it. Use the `mqledger` conda environment.
- Trust the current source over any Markdown description, including this brief. If a line number or function here doesn't match the code, find the equivalent and note the discrepancy.
- Keep the stack: Python, NiceGUI, Pydantic v2, JSON files. No new dependencies, no database, no pytest. Tests go in a standalone `validate_interview_practice.py`, matching the existing `validate_*.py` scripts.
- CSS changes use `ui.add_head_html('<style id="mq-interview-css">…')`, never `ui.add_css()`.
- Every new Pydantic field has a default. Never tighten a type on an existing field in a way that could fail to load old `data/interview_history.json`.
- Do not bump `PROMPT_PACK_VERSION` in Phase 1. The rubric is unchanged.
- Make small, reviewable commits in the task order below. Task 1 must land first.

Stop and ask before proceeding if:

- A change would require deleting, rewriting or re-scoring existing sessions in `interview_history.json`.
- You find a preset or UI path that depends on the model ending a session early (Task 5).
- A task seems to need a change to anything in the "Do not change" list at the end.

## Background: confirmed defects

Phase 1 fixes defects that make the feature lose data or report missing feedback as success. Each was confirmed by reading the code; items marked (executed) were reproduced by calling the real controller with a fake LLM provider.

| # | Defect | Where |
| --- | --- | --- |
| D1 | One invalid field in the history file makes `load_database()` return an empty database; the next save overwrites all history (6 sessions became 1). (executed) | `storage/interview_store.py::load_database`, `save_session` |
| D2 | Schema tells the model `critique` is "empty outside Drill", so every non-Drill answer is stored with no critique. | `services/interview_controller.py::_evaluation_schema` |
| D3 | Any single expected key counts as a valid evaluation. `{"next_question":…}` saves `score=None, critique=""`; `"7/10"` becomes `None`. (executed) | `_parse_evaluation_data`, score parsing in `evaluate_answer` |
| D4 | Missing or misnamed postmortem fields become `"Session completed."` with empty lists, rendered as a normal result with a score band. (executed) | `evaluate_answer` postmortem block; `components/interview_practice.py::_render_postmortem_inner`, `_render_score_band` |
| D5 | Empty Drill critique is shown as "No material failure identified." | `_render_drill_feedback` |
| D6 | Model `done: true` on a non-final turn ends the session, but the postmortem schema was only requested on the final turn. (executed) | `evaluate_answer` (`done = … or final_turn`) |
| D7 | Up to three LLM calls per turn; the malformed-JSON retry uses the same token budget as the call that failed. (executed) | `evaluate_answer` |
| D8 | If the user edits the draft while whisper runs, the refined transcript is appended to the caption draft, duplicating the answer. | `components/interview_practice.py::handle_transcription` |
| D9 | Unscored answers with no tags are treated as "not weak" and never scheduled for review. | `storage/interview_store.py::mark_review` |

Out of scope for Phase 1 (handled later): the final-turn postmortem only sees the last 3 prior answers; one thesis-shaped rubric for all question types; trends mixing prompt versions and presets; no transcript-quality signal.

## Phase 1 tasks (do in this order)

Goal: never lose history, never save or show a missing evaluation as a successful one, and give actionable per-answer feedback in every mode. The final-turn postmortem architecture stays for now; Phase 2 replaces it.

### Task 1 — Stop the history wipe (D1)

File: `storage/interview_store.py`.

1. In `load_database()`, keep returning an empty `InterviewDatabase` only for `FileNotFoundError`.
2. On `json.JSONDecodeError` or a Pydantic `ValidationError`: copy the file to `data/backups/interview_history_unreadable_<YYYYMMDD-HHMMSS>.json`, then raise a new `InterviewHistoryUnreadable` exception naming both paths. Never return an empty database in this case.
3. Because every save goes through `load_database()`, this also stops `save_session()` and `save_preferred_model()` from overwriting the file.
4. In `components/interview_practice.py::render_interview_practice`, catch `InterviewHistoryUnreadable` inside `refresh()` and render one error card with the backup path. The rest of the app must keep working.

This task lands first, before any model change.

### Task 2 — Validated per-turn evaluation (D2, D3, D9)

Files: `models/interview.py`, `services/interview_controller.py`, `services/interview_prompts.py`.

1. Add to `InterviewAnswer`: `fix: str = ""` and `evaluation_status: str = ""`. Use plain `str`, not `Literal`. Empty string means a legacy answer where status was never recorded. New values: `"ok"`, `"partial"`.
2. Add a Pydantic `TurnEvaluation` model (controller module is fine) that parses the raw dict:
   - `score`: accept int, float, `"7"`, or `"7/10"`; clamp to 1–10; otherwise invalid.
   - `failure_tags`: keep only values in `FAILURE_TAGS`, max 3.
   - `critique`: pass through `_compact_critique()`; if the model returns a list, join it.
   - `fix`: one sentence, trimmed to 40 words.
   - Question fields: keep today's aliases (`next_question`, `nextQuestion`, `question`, `text`).
3. Classify the result: valid score + critique + fix → `ok`; valid score but critique or fix empty → `partial`; no valid score → invalid.
4. In `_evaluation_schema()`:
   - Replace the critique description with: required, 1–2 sentences, max 60 words, the most important weakness, specific to what the candidate said.
   - Add `"fix"`: required, one concrete thing to do differently next time.
   - Change `failure_tags` description to `"array of 0-3 tag strings"` and state value types for every field (integer, array of strings, boolean).
5. In `compose_runtime_prompt()`, append to the RESPONSE CONTRACT: evaluation fields are private notes stored for post-session review, never shown to the candidate mid-interview, and must always be filled even when the preset says not to coach or score. Do not edit preset texts. Do not bump `PROMPT_PACK_VERSION`.
6. `mark_review()` must never receive `score=None` under the new flow. Add an assertion in the validation script rather than changing its logic.

### Task 3 — One repair, at most two calls per turn (D7)

File: `services/interview_controller.py::evaluate_answer`.

1. Raise first-call budgets to 450 (non-final) and 900 (final). Keep the constants named at module level.
2. Retry once if the result is invalid **or** the critique is empty. The retry gets 1.5× the budget and a repair message naming what was wrong (for example "score missing", "critique empty", "postmortem missing").
3. After the retry: valid score → save as `ok` or `partial`; still no valid score → raise `InterviewOutputError` and save nothing (today's behavior).
4. The plain-text question-recovery call counts as the turn's single repair. If the repair was already used and `next_question` is still missing on a non-final turn, use a module constant `FALLBACK_FOLLOW_UP` ("Take that one level deeper: what is the mechanism, and what evidence supports it?"). Never make a third call.

### Task 4 — Distinguish provider failure from bad output

Files: `services/interview_llm.py`, `services/interview_controller.py`, `components/interview_practice.py`.

1. Define `InterviewProviderError` and `InterviewOutputError` in `interview_llm.py`.
2. In `OpenAICompatibleProvider.complete()`, wrap SDK exceptions (network, auth, rate limit, no choices) as `InterviewProviderError`. Keep the existing reasoning and `response_format` fallback logic exactly as is.
3. Treat empty content as an output problem, not a provider error; include the hint "possible reasoning-budget starvation" in the logged detail.
4. In `submit()`, show distinct messages. Provider: "The model provider failed (network, key, or rate limit). Nothing was saved; your answer is still here." Output: "The model returned unusable feedback twice. Nothing was saved; submit again."

### Task 5 — Controller owns session end (D6)

File: `services/interview_controller.py`.

1. Set `done = final_turn`. Ignore the model's `done` flag on non-final turns.
2. Add `"questions_remaining"` to the prompt payload so the model knows the session continues.
3. Before merging, grep presets and UI for any path relying on model-initiated endings. Stop and report if one exists.

### Task 6 — Harden the final-turn postmortem (D4, interim)

Files: `models/interview.py`, `services/interview_controller.py`.

1. Add `status: str = ""` to `InterviewPostmortem`. Empty = legacy. New values: `"ok"`, `"partial"`, `"missing"`.
2. Remove the `"Session completed."` default. Missing `overall_performance` stays empty.
3. Accept key aliases before reading: `strengths` → `strongest_areas`; `weaknesses`, `improvements` → `biggest_problems`; `next_steps` → `concepts_to_repeat`.
4. Status rule: `ok` needs overall text plus at least one item in each of the three lists; some content but not all → `partial`; nothing → `missing`.
5. If the final answer's turn fields are valid but the postmortem is `missing`, use the turn's one repair to ask for the full final JSON again. If it is still missing, complete the session anyway with `status="missing"`. The answer itself is valid and must be saved.
6. In `_record_view_practice()`, keep bumping counts, but overwrite `latest_diagnostic` only when postmortem status is `ok` or `partial`.

### Task 7 — Honest UI (D4, D5)

File: `components/interview_practice.py`. Add any new CSS (for example a `.pm-warn` amber class) inside the existing `mq-interview-css` block.

1. `_render_drill_feedback()`: remove the "No material failure identified." fallback. Show critique, then a `FIX` line. For `partial`, show an amber note: "Partial feedback — the model returned a score but no critique or fix."
2. `_render_postmortem_inner()`:
   - Legacy (`status == ""`): render exactly as today.
   - `missing`: replace OVERALL with an amber note: "Summary unavailable — the model didn't return a usable review. Per-answer feedback is below." Do not show a score band.
   - `partial`: show what exists plus an amber "Partial summary" label.
3. Add a collapsed "Answer-by-answer feedback" `ui.expansion` listing each question with score, tags, critique, fix and a small status marker. Show it only when at least one answer has a critique. This is the first place non-Drill users see per-answer feedback.
4. `_render_score_band()`: exclude retries (`is_retry`), matching `view_practice_stats()`. Render the band only if postmortem status is not `missing` and at least 75% of first-attempt answers have a score.

### Task 8 — Stop duplicated voice transcripts (D8)

File: `components/interview_practice.py::handle_transcription`.

1. Keep the current replace branch when the draft is unchanged.
2. If a caption draft exists and the user edited it, do not modify the textarea. Store the refined text and show a "Use refined transcript" button that sets the answer to `base + refined`. Status line: "Refined transcript ready — your edits were kept."
3. If there was no caption draft, append as today.
4. Keep the `turn_token` guard and audio retention unchanged.

## Phase 1 validation script

Create `validate_interview_practice.py` at the repo root, modeled on `validate_topic_view_sync.py`: plain asserts, temp directories only, no network, exit code 0 on success. Point `storage.interview_store.INTERVIEW_FILE` at a temp file, stub `weakness_context` to return `""`, and use a fake provider that returns scripted strings and records every call (messages and `CompletionOptions`).

| # | Setup | Must be true |
| --- | --- | --- |
| 1 | History file with one invalid field (e.g. `status: "needs_review"`) | `load_database()` raises `InterviewHistoryUnreadable`; original file byte-identical; backup exists; a following `save_session()` does not overwrite it |
| 2 | Missing history file | Empty database returned; first save creates the file |
| 3 | Fixture copied from today's schema (legacy answers with no `fix`/`evaluation_status`, postmortem `"Session completed."`) | Loads without error; statuses are `""` |
| 4 | Response `{"next_question":"Why?"}` twice | Two calls made; `InterviewOutputError` raised; nothing saved |
| 5 | Response `{"score":"7/10","critique":"…","fix":"…","next_question":"…"}` | Saved score is 7, status `ok`, one call |
| 6 | First response has score but empty critique; retry fills it | Two calls; retry budget is 1.5× first; status `ok` |
| 7 | Score valid, critique empty on both calls | Saved with status `partial` |
| 8 | Malformed JSON, then valid JSON without `next_question` on a non-final turn | Exactly two calls; next question equals `FALLBACK_FOLLOW_UP` |
| 9 | `done: true` on turn 1 of a 6-question `view_discuss` session | Session still `active`; prompt contains `questions_remaining` |
| 10 | Every preset in `PRESETS`: turn-1 schema text | Contains no "empty outside Drill"; includes `fix` |
| 11 | Final turn, postmortem uses `strengths`/`weaknesses`/`next_steps` | Mapped to the canonical fields; status `ok` |
| 12 | Final turn, valid turn fields, postmortem missing twice | Session `completed`; answer saved; postmortem status `missing`; `overall_performance` is empty, not `"Session completed."` |
| 13 | Provider raises a network-style exception | `InterviewProviderError` surfaces; nothing saved |
| 14 | Any saved answer in cases 4–12 | `score` is never `None` when `mark_review()` runs |
| 15 | Band helper with a retry answer included | Retry excluded from the average; no band when postmortem status is `missing` |

Also add `validate_interview_practice.py` to `check_syntax.py` and update the file count noted in `AGENTS.md`.

UI behavior (Tasks 7 and 8) can't be covered by this script. Verify it manually per the checklist in the next section.

## Phase 1 definition of done

Phase 1 is done when all scripted checks pass, the manual checks below have been run, and `AGENTS.md` describes the new contract.

Scripted:

- [ ] `python check_syntax.py` passes, including the new file.
- [ ] `python validate_interview_practice.py` passes all 15 cases.
- [ ] `python validate_topic_view_sync.py` still passes (it should be untouched).

Manual, with a real key on the default grader (`z-ai/glm-5.3`). Report what you saw for each:

- [ ] Start the app against a **copy** of the real `data/interview_history.json`. The Practice home, My Views board and old postmortems render as before.
- [ ] Quant Drill, 3 questions: every feedback card shows a critique and a FIX line; no "No material failure identified."
- [ ] View Deliver, single View: postmortem renders; the answer-by-answer section shows the critique.
- [ ] Job Interview, 4 questions: no feedback shown mid-interview; postmortem shows all four answers' critiques.
- [ ] Voice answer: edit the caption draft while whisper runs; no duplicated text; "Use refined transcript" works.
- [ ] Temporarily set an invalid API key: submit shows the provider message and the answer stays in the box.
- [ ] Open the saved JSON and confirm `evaluation_status`, `fix` and postmortem `status` are populated.

Update `AGENTS.md` in the same change. These bullets currently describe behavior Phase 1 replaces:

- **Practice feedback contract**: now every turn requires score, critique and fix in all modes; evaluation is private in non-Drill modes; one repair per turn; at most two LLM calls; controller owns session end.
- **Postmortem presentation / score band**: postmortem `status`, the missing/partial states, retries excluded from the band, the answer-by-answer section.
- **Practice voice controls**: refined transcript is offered, not appended, when the draft was edited.
- **Interview History**: unreadable history is backed up and surfaced, never replaced.
- Module table: add `validate_interview_practice.py`; update the `check_syntax.py` file count.

In your final report, list any code that did not match this brief and what you did about it.

## Phase 2 preview: synthesis, rubrics, comparable trends (do not start)

Phase 2 moves the whole-interview review into its own call and makes score history honest. Keep Phase 1 code easy to extend in these directions.

- **Final turn becomes ordinary.** It evaluates the last answer with the compact budget. No postmortem fields in that call.
- **New `synthesize_session()`** runs after completion. Input: one record per answer (question, score, tags, critique, fix, answer excerpt capped near 1,000 characters). Use full answer text only for sessions of three or fewer answers, such as Deliver. Output: overall, up to 3 strengths and 3 weaknesses with question numbers, up to 3 next steps. One repair, then `synthesis_status = "failed"` with a Retry summary button. Cache success so it never re-bills.
- **Deterministic aggregation.** Band from the mean of first-attempt scores, evaluation coverage, and tag counts are computed in code, not by the LLM.
- **`_record_view_practice()`** moves to run after synthesis.
- **Three rubric families**, each with a `rubric_id`: argument (Views, Maintenance, Research Defense), technical (Quant Drill, model modes), interview (Job Interview). Same 1–10 scale; shared line "grade against what this question asks." Bump `PROMPT_PACK_VERSION`.
- **Comparability key on each answer**: `(rubric_id, grader model, preset_key, input_method)`. `view_practice_stats`, `performance_summary`, `model_practice_stats` and `weakness_context` compute series only within one key. `prompt_override` sessions use `rubric_id = "custom"` and are excluded. Legacy sessions map to `"unanchored"` (pre-v2) or `"shared-v2"`.

Files: `services/interview_controller.py`, `services/interview_prompts.py`, `models/interview.py`, `storage/interview_store.py`, `components/interview_practice.py`, `validate_interview_practice.py`, `AGENTS.md`.

## Phase 3 preview: voice quality (do not start)

Phase 3 makes poor transcripts visible and recoverable instead of silently degrading grading.

- **Worker metrics.** `services/interview_speech_worker.py` returns duration, mean `avg_logprob`, max `no_speech_prob`, max `compression_ratio`, and words per second. Try `vad_filter=True` and verify on short and silent clips.
- **Suspect flag.** Mark a transcript suspect if words per second is below about 0.7 or above about 4, compression ratio is above 2.4, `avg_logprob` is below −1.0, or the text is mostly glossary terms. Show an amber "review before submitting" note; still grade, but exclude suspect answers from trends.
- **Provenance.** Store `transcript_source` (whisper or captions) and `input_method` (typed, voice, mixed) on each answer. Mixed means the user edited after dictation. Replace the sticky `voice_origin` flag. Apply `TRANSCRIPT_NOTE` to voice and mixed answers.
- **Retry transcription** button whenever the audio blob is retained.

Files: `services/interview_speech_worker.py`, `services/interview_speech.py`, `components/interview_speech.py`, `components/interview_practice.py`, `models/interview.py`, `services/interview_controller.py`, `storage/interview_store.py`, `AGENTS.md`.

## Do not change

Leave these as they are in every phase unless the user approves otherwise.

- `_opening_question()` and the deterministic first turn.
- `extra_body={"reasoning": {"enabled": False}}` and its GLM `effort: minimal` fallback in `OpenAICompatibleProvider.complete()`.
- JSON-only persistence; the atomic temp-file write in `save_database()`.
- `recent_answers()` filtering on `practice_style` / `preset_key`, never `mode`.
- The `FAILURE_TAGS` vocabulary, the 3-tag cap, and the `gone_quiet_tags()` gates.
- Preset prompt texts in `interview_prompts.py` (Phase 1 adds contract text only).
- No mid-interview feedback in Simulation, Research Defense and View Discuss/Defend modes.
- The click-gated, cached reference answer.
- `turn_token`, audio blob retention, and excluding live captions from `speech_bias_context()`.
- TTS (`services/interview_tts.py`, `components/interview_tts.py`).
- The read-only model library and the "never fabricate experience" guard.
- Never rewriting the user's View content; only `ViewPracticeMeta` is updated.
- Keyboard shortcuts, the `mq-interview-css` injection pattern, and button order on the postmortem.
