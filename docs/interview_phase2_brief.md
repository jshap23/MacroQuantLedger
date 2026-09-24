# MacroQuantLedger Interview Practice — Phase 2 Brief for Coding Agent

Sep 24, 2026 · @Anna Di

## How to run Phase 2

### For you (the user): four checkpoints

1. **Set up.** Back up `data\interview_history.json` to your Desktop. Save this doc's text as `docs/interview_phase2_brief.md` in the project. Create a branch: `git checkout -b feature/interview-phase2`.
2. **Send batch A** (Tasks 1 and 2), then paste the agent's full response back to Claude for review:

```
Read AGENTS.md, then docs/interview_phase2_brief.md.
Implement Tasks 1 and 2 only. Add validation cases P1–P6.
Stop after running check_syntax.py, validate_interview_practice.py and
validate_topic_view_sync.py. Show the diff, the preset-to-family mapping
table, and the full script output. Commit on the current branch when the
checks pass. Do not start Task 3.
```

3. **Send batch B** (Task 3) once Claude approves batch A:

```
Implement Task 3 from docs/interview_phase2_brief.md. Add cases P7–P14.
Stop after running the three check scripts. Show the new
synthesize_session(), the changed evaluate_answer() completion path, the
postmortem UI diff, and the full script output. Commit when checks pass.
Do not start Task 4.
```

4. **Send batch C** (Task 4 and AGENTS.md) once Claude approves batch B:

```
Implement Task 4 and the AGENTS.md updates from
docs/interview_phase2_brief.md. Add cases P15–P20. Stop after running the
three check scripts. Show the diffs of every stats function, the AGENTS.md
diff, the full script output, and a list of every place the code didn't
match the brief. Commit when checks pass.
```

Then run the manual checks in "Definition of done" and merge: `git checkout main`, `git merge feature/interview-phase2`.

### For the coding agent: ground rules

- Read `AGENTS.md` first and follow it. Use the `mqledger` conda environment.
- Phase 1 is merged. Trust the current code over this brief; where they differ, find the equivalent and report the difference.
- Keep the stack: Python, NiceGUI, Pydantic v2, JSON. No new dependencies, no database, no pytest. Extend `validate_interview_practice.py`.
- New model fields are plain `str`/`list`/`dict` with defaults. No `Literal` on stored fields. Never rewrite existing sessions in the history file; derive legacy values when reading.
- CSS goes inside the existing `mq-interview-css` block.
- At most one repair per LLM call; never more than two calls per evaluation or synthesis attempt.
- Commit at the end of each batch, on the current branch.

Stop and ask before proceeding if:

- A preset doesn't clearly belong to one rubric family (Task 2).
- A change would make an existing session render differently, other than the score-band gate described in Task 2.
- Synthesis needs content the session doesn't store (for example, View text for a Deliver comparison).

## Starting point and design

Phase 1 made every turn return a validated score, critique and fix, and made missing feedback visible. Three problems remain, and Phase 2 fixes them:

- **The whole-interview review is still written on the final turn.** It sees only the last few answers (`_recent_context()` takes the last four questions), shares one call with the last answer's evaluation, and can't be retried once the session completes.
- **One thesis-shaped rubric grades every question type.** `SCORE_RUBRIC` rewards "bottom line first" and "what would falsify the view", which a correct quant answer or a behavioral answer can't show.
- **Trends mix scores that weren't graded the same way.** `view_practice_stats()` and `performance_summary()` split by grader model only, so pre-v2 and v2 sessions, Deliver/Discuss/Defend, and custom-prompt sessions land in one series.

The design:

| Piece | Decision |
| --- | --- |
| Final turn | An ordinary turn: evaluates the last answer only, no postmortem fields |
| Whole-interview review | A separate `synthesize_session()` call after completion, fed one record per answer; retryable; cached once it succeeds |
| Numbers in the review | Computed in code (band, coverage, tag counts), never by the LLM |
| Rubrics | Three families with their own `rubric_id`: argument, technical, interview. Same 1–10 scale and band thresholds |
| Trend comparisons | Only within one comparability key: `(rubric_id, grader model, preset_key, input_method)` |
| Legacy sessions | Never rewritten; their `rubric_id` is derived when read: `"unanchored"` (pre-v2) or `"shared-v2"`. Custom-prompt sessions are `"custom"` and excluded from trends |

## Phase 2 tasks

### Task 1 — Provenance and the comparability key (batch A)

Files: `models/interview.py`, `storage/interview_store.py`. No prompt or UI change in this task.

1. Add `InterviewSession.rubric_id: str = ""` and `InterviewAnswer.input_method: str = ""`. `evaluate_answer()` sets `input_method` to `"voice"` or `"typed"` from `voice_origin` (Phase 3 adds `"mixed"`).
2. Add read-time helpers in `interview_store.py`. None of them writes to the file:
   - `effective_rubric_id(session)`: the stored value if set; otherwise `"custom"` if the session used a custom prompt override; otherwise `"shared-v2"` if `prompt_pack_version == LEGACY_V2_PROMPT_PACK`; otherwise `"unanchored"`. If sessions don't record whether an override was used, report it and treat those legacy sessions as `"shared-v2"`.
   - `effective_input_method(answer)`: the stored value, else `"voice"` if `answer.voice` else `"typed"`.
   - `comparability_key(session, answer)`: `(effective_rubric_id, session.model or "", session.preset_key, effective_input_method)`.
   - `trend_eligible(session, answer)`: session completed, answer not a retry, score not `None`, and rubric id not `"custom"` or `"unanchored"`.

### Task 2 — Three rubric families (batch A)

Files: `services/interview_prompts.py`, `services/interview_controller.py`, `components/interview_practice.py`.

1. Give every preset an explicit `rubric_family`: `"argument"`, `"technical"` or `"interview"`. Default mapping:
   - argument: View Deliver, Discuss and Defend; 20-Minute Maintenance; Research Defense.
   - technical: Quant Drill and every model mode.
   - interview: Job Interview.
   - Anything else (for example the 60-Minute Diagnostic or a weaknesses preset): **stop and ask** with a proposed mapping.
2. Replace the single `SCORE_RUBRIC` with `RUBRICS = {family: (rubric_id, text)}`, ids `"argument-v3"`, `"technical-v3"`, `"interview-v3"`. Keep the current band thresholds and band names exactly, so `session_band()` keeps working. Only the criteria text differs per family:
   - **argument**: clear conclusion early; causal mechanism; evidence with magnitudes; the key risk or what would change the view; the practical implication.
   - **technical**: correct result or method; reasoning shown in steps; assumptions stated; a sanity check or edge case; precise terms.
   - **interview**: answers the question directly; a specific example with the candidate's own role; result or impact, quantified where possible; relevance to the role; concise.
   - All three end with: "Grade against what this question asks. A narrow follow-up needs a precise answer to that follow-up, not a full thesis."
   - Keep each text about the length of the current `SCORE_RUBRIC`. Show all three texts in the batch report for review.
3. `_evaluation_schema()` uses the session's family rubric for the `score` description.
4. `start_session()` stores `rubric_id` from the preset's family, or `"custom"` when a prompt override is used (still graded with the family rubric).
5. Before bumping `PROMPT_PACK_VERSION`, copy its current value into a new constant `LEGACY_V2_PROMPT_PACK`. Then bump it.
6. `_render_score_band()` currently shows the band only when `prompt_pack_version == PROMPT_PACK_VERSION`, which would hide the band on every Phase 1 session after the bump. Replace that gate with `effective_rubric_id(session) not in {"unanchored", "custom"}`. This is the only allowed rendering change to existing sessions.

### Task 3 — Separate end-of-interview synthesis (batch B)

Files: `services/interview_controller.py`, `models/interview.py`, `components/interview_practice.py`.

Controller:

1. The final turn becomes ordinary. Remove the postmortem from `_evaluation_schema()`, remove the final-turn postmortem repair and better-of-two logic, and use the normal `EVAL_MAX_TOKENS` budget.
2. On the final turn, save the answer and set status `completed`, `completed_at`, `pending_move = {}`, and `postmortem = InterviewPostmortem(status="pending")`. Split `_record_view_practice()` in two: `_record_view_counts()` runs here, once per completion; `_record_view_diagnostic()` runs after a successful synthesis (keep Phase 1's rule: overwrite only with non-empty content).
3. Add pure `session_stats(session)`: first-attempt count, evaluated count, coverage, mean first-attempt score, band (via `session_band()`), and tag counts from first attempts.
4. Add `synthesize_session(session_id, provider=None) -> InterviewSession`:
   - Completed sessions only. If postmortem status is already `ok`, return without calling the model.
   - Input: setup (topic, role, preset label, `compact_brief`), the `session_stats()` numbers stated as facts the model must not recompute, and one record per answer: question number and text, attempt (first or retry), score, tags, critique, fix, status, and the answer text capped at 1,000 characters. Use full answer text when the session has three or fewer answers.
   - Include the preset's end-of-session instructions (for example Deliver's Covered / Missed / Delivery). If they're only embedded in preset prose, pass the preset text with a line saying the interview is over and to write only the review.
   - Output JSON: `overall_performance` (2–4 sentences), `strongest_areas` (up to 3, each citing question numbers such as "Q2, Q5: …"), `biggest_problems` (up to 3, each citing question numbers and starting with one category: knowledge, evidence, reasoning, communication or pressure), `concepts_to_repeat` (up to 3 concrete next drills).
   - Validate with Phase 1's `_build_postmortem()` rules. One repair at 1.5× `SYNTHESIS_MAX_TOKENS` (start at 900).
   - Never downgrade: keep the better of the existing and new postmortem.
   - Failures never raise to the caller. Record `status="missing"` and a new `InterviewPostmortem.synthesis_error: str = ""` set to `"provider"` or `"output"`.
   - After `ok` or `partial`, call `_record_view_diagnostic()`. Save.

UI:

5. After the final answer, render the postmortem immediately and run `synthesize_session()` off the UI thread the same way other model calls run, then refresh. Keep an in-memory set of session ids being synthesized.
6. For sessions whose postmortem status is not `""` (legacy):
   - `pending` and currently running: "Writing summary…".
   - `pending` but not running (interrupted), `missing`, or `partial`: show a **Retry summary** button. For `missing`, say whether it was a provider or output failure.
   - Always show one stats line from `session_stats()`, for example "12 of 14 answers evaluated · average 6.4 · Band: … · most frequent: RAMBLE, NO\_NUMBERS".
   - Phase 1 sessions can use Retry summary too; their stored answers have critiques.
7. Keep the answer-by-answer section and the existing postmortem button order. Place Retry summary inside the summary card.

### Task 4 — Trends compare like with like (batch C)

Files: `storage/interview_store.py`, `components/interview_practice.py`.

1. Aggregate scores only from `trend_eligible()` answers. Include `partial` answers (they have scores).
2. `view_practice_stats()`: for each View, take the comparability key of its most recent eligible session. Compute latest, previous, best, delta, sparkline and the 10-rep suppression count only from sessions with that key. Add `other_key_sessions`: the View's eligible sessions under a different key.
3. `performance_summary()` and `model_practice_stats()`: score numbers count only answers graded with a current rubric (`*-v3`) by the currently selected grader model. Compute the "improving" flag within one comparability key.
4. `weakness_context()`: failure tags may still come from all sessions (they are hints for the next prompt, not displayed scores). Any score numbers it includes follow rule 3. Report what it includes.
5. `"shared-v2"` sessions form their own key and are never merged with `*-v3`.
6. UI: where a View's trend is shown, add a small muted note when `other_key_sessions > 0`: "N earlier sessions graded differently aren't compared." When the current key has fewer than two sessions: "New scoring — building a baseline." No new charts.

## Validation cases

Extend `validate_interview_practice.py` with the same fake-provider harness and temp directories. To test the band gate without a NiceGUI client, extract it into a pure helper (for example `band_visible(session)`), as Phase 1 did with `session_band()`.

**Batch A (Tasks 1–2)**

| # | Setup | Must be true |
| --- | --- | --- |
| P1 | Legacy sessions: one with `LEGACY_V2_PROMPT_PACK`, one with an older pack, neither with `rubric_id` | Effective ids are `"shared-v2"` and `"unanchored"`; the history file is byte-identical after loading |
| P2 | Legacy answer with `voice=True`; new answer submitted with `voice_origin=True` | Effective method `"voice"` for both; the new answer stores `input_method="voice"` |
| P3 | Retry answer, `None` score, `"custom"` session, `"unanchored"` session, active session | `trend_eligible()` is false for each |
| P4 | Every preset in `PRESETS` | Has a family in {argument, technical, interview}; its turn-1 schema contains its own family's rubric text and not the other two |
| P5 | `start_session()` for one preset per family, and one with a prompt override | Stores `"argument-v3"`, `"technical-v3"`, `"interview-v3"`, and `"custom"` |
| P6 | Phase 1 fixture session (old pack, postmortem status `ok`); custom and unanchored sessions | `PROMPT_PACK_VERSION != LEGACY_V2_PROMPT_PACK`; band visible for the Phase 1 session; hidden for custom and unanchored |

**Batch B (Task 3)**

| # | Setup | Must be true |
| --- | --- | --- |
| P7 | Final turn | Schema has no postmortem; one call; session `completed` with postmortem status `pending` |
| P8 | 14-question session with one retry; one answer longer than 1,000 characters | Synthesis input has 15 records with the retry marked; long answer cut to 1,000 characters; status `ok`; View diagnostic written |
| P9 | 2-answer session with a 1,500-character answer | Full answer text appears in the synthesis input |
| P10 | Any synthesis | Input contains the `session_stats()` numbers; those stats exclude retries |
| P11 | Malformed then valid; separately malformed twice | Two calls then `ok`; second case `missing`, `synthesis_error="output"`, no exception |
| P12 | Provider raises during synthesis | `missing`, `synthesis_error="provider"`, no exception; View diagnostic untouched; View counts bumped exactly once for the session |
| P13 | Retry after `ok`; separately a retry returning worse output than an existing `partial` | Zero calls in the first; `partial` kept in the second |
| P14 | Phase 1 fixture session with postmortem status `missing` | `synthesize_session()` upgrades it to `ok` |

**Batch C (Task 4)**

| # | Setup | Must be true |
| --- | --- | --- |
| P15 | One View: two `shared-v2` sessions, then three `argument-v3` sessions | Stats come from the three v3 sessions only; `other_key_sessions == 2` |
| P16 | Same View graded by two different models | Not merged; the latest session's model defines the series |
| P17 | Same View practiced in Deliver and in Discuss | Separate series |
| P18 | Custom and unanchored sessions with high scores | Absent from `view_practice_stats()`, `performance_summary()` and `model_practice_stats()` numbers |
| P19 | Retry and `partial` answers | Retries excluded from every average; `partial` answers included |
| P20 | Scores improving under one key and falling under another | The "improving" flag reflects only the current key |

## Definition of done

Scripted (the agent runs these after every batch):

- [ ] `python check_syntax.py` passes.
- [ ] `python validate_interview_practice.py` passes all Phase 1 cases and P1–P20.
- [ ] `python validate_topic_view_sync.py` still passes.

Manual (you run these after batch C, with your real grader model and a backup of your history). Write pass or fail for each:

1. **Old sessions look the same.** Open a pre-Phase-1 session and a Phase 1 session. Both render as before; the Phase 1 one still shows its band.
2. **Long interview summary.** Run a Job Interview with at least 8 questions. The summary appears after a short "Writing summary…" wait, and its strengths and problems cite question numbers from early in the interview, not just the last few.
3. **Short Deliver.** Practice one View in Deliver mode. The summary uses the Covered / Missed / Delivery structure and the stats line shows "1 of 1 answers evaluated".
4. **Fair technical scoring.** Answer a Quant Drill question correctly and concisely. The score isn't pulled down for missing a "thesis" or "what would falsify the view".
5. **Retry summary.** Complete a short session, and while "Writing summary…" shows, disconnect from the internet. You see "Summary unavailable" with a provider-failure note and a Retry summary button. Reconnect and press it; the summary appears.
6. **Trends.** Practice a View you've practiced before. Its trend shows "New scoring — building a baseline" and says earlier sessions aren't compared, rather than a jump up or down from your old scores.
7. **Saved data.** Open `data\interview_history.json`. The new session has `rubric_id`, each answer has `input_method`, and the postmortem has `status` `ok`.

`AGENTS.md` updates in batch C:

- Practice feedback contract: final turn is ordinary; the review comes from `synthesize_session()`; one repair; failures recorded, not raised; Retry summary.
- Scoring: three rubric families and their ids; `LEGACY_V2_PROMPT_PACK`; how legacy rubric ids are derived.
- Trends: comparability key, `trend_eligible()`, and which functions follow which rule.
- Postmortem presentation: `pending`, `synthesis_error`, the stats line, the band gate.
- Module table and the `check_syntax.py` file count, if either changed.

## Phase 3 preview: voice quality (do not start)

Phase 3 makes poor transcripts visible instead of silently lowering scores. Keep Phase 2 compatible with it: `input_method` must accept a third value, `"mixed"`, without code changes elsewhere.

- The whisper worker returns confidence measures (duration, words per second, `avg_logprob`, `no_speech_prob`, `compression_ratio`); try `vad_filter=True`.
- Transcripts that look unreliable are flagged with an amber "review before submitting" note, still graded, and excluded from trends.
- Each answer records `transcript_source` (whisper or captions), and `input_method` becomes typed, voice or mixed, replacing the sticky voice flag.
- A Retry transcription button appears whenever the audio is still held.

## Do not change

Everything Phase 1 built stays as is, plus the original list:

- Phase 1 per-turn behavior: required score, critique and fix; `ok` / `partial`; one repair; at most two calls; `FALLBACK_FOLLOW_UP`; controller-owned session end; the better-of-two evaluation selection.
- `load_database()` backup-and-raise behavior and `InterviewHistoryUnreadable`.
- The answer-by-answer feedback section and the Drill feedback card.
- `_opening_question()` and the deterministic first turn.
- The reasoning-disable `extra_body` and its GLM fallback; the provider-error wrapping in `OpenAICompatibleProvider.complete()`.
- JSON-only persistence and the atomic write in `save_database()`.
- `recent_answers()` filtering on `practice_style` / `preset_key`, never `mode`.
- The `FAILURE_TAGS` vocabulary, the 3-tag cap, and `gone_quiet_tags()` gates.
- Band thresholds and band names (only rubric criteria text changes).
- No mid-interview feedback in Simulation, Research Defense and View Discuss/Defend modes.
- The click-gated reference answer, TTS, and the voice pipeline (Phase 3 owns voice).
- The read-only model library, the "never fabricate experience" guard, and never rewriting the user's View content.
- Keyboard shortcuts, the `mq-interview-css` injection pattern, and the postmortem button order.
