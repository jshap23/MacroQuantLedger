# AGENTS.md

This file provides guidance to **OpenCode** when working with code in this repository.

## Environment

Always use the **`mqledger` conda environment** for all Python commands. On Windows the launcher uses **miniforge3**:

```bash
conda activate mqledger
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Install isolated NumPy runtime for interview speech transcription (run once)
python setup_speech_runtime.py

# Run the app (serves on http://localhost:8080 by default; override with MQLEDGER_PORT)
# Production-style launch: no console window, single-instance enforcement, auto-opens browser
launch_macroQuantLedger.bat
# Or directly from an activated conda shell:
python launch.py
# Open straight into My Views > Flip through (all | stale | shaky | core); the .bat forwards its arguments
python launch.py --deck shaky
# Development / manual run:
python app.py

# Validate syntax across core files
python check_syntax.py

# Validate TopicView <-> Obsidian sync logic (uses temp dirs only)
python validate_topic_view_sync.py

# Validate interview practice persistence/evaluation logic (uses temp dirs only)
python validate_interview_practice.py

# Validate My Views levels, freshness, streak, and personal bests (pure in-memory, no files or network)
python validate_view_levels.py
```

There are **no automated test suites, linters, or CI pipelines**. Two standalone validation scripts must pass after changes to the code they cover: `validate_topic_view_sync.py` (TopicView/Obsidian sync) and `validate_interview_practice.py` (interview practice persistence, evaluation, and postmortems).

## Critical Architecture Notes

### CSS Injection Pattern (IMPORTANT)

**Never use `ui.add_css()` directly** — it appends a new `<style>` element on every page refresh, causing CSS duplication and layout breakage after 2-3 refreshes.

**Always use `ui.add_head_html()` with a unique ID:**

```python
# WRONG - causes duplication on refresh
ui.add_css(""".my-class { ... }""")

# CORRECT - replaces existing style on refresh
ui.add_head_html('<style id="mq-unique-id">.my-class { ... }</style>')
```

All component CSS must follow this pattern. Current IDs in use:
- `mq-main-css` (app.py)
- `mq-macro-views-css` (components/macro_views.py)
- `mq-briefing-css` (components/briefing.py)
- `mq-attribution-css` (components/attribution.py)
- `mq-topic-views-css` (components/topic_views.py)
- `mq-view-deck-css` (components/view_deck.py)
- `mq-undo-css` (components/undo_toast.py)
- `mq-interview-css` (components/interview_practice.py)

## Architecture

**MacroQuantLedger** is a local single-page dashboard for macro-quant research tracking. It uses [NiceGUI](https://nicegui.io/) (Python → Vue.js/Quasar) for the web UI, Pydantic v2 for data models, and JSON for persistence.

### Tabs (4 primary tabs + secondary tabs)

1. **Views** (landing tab)
   - **My Views** — Living rolodex of structured arguments (TopicViews); the "Top of Mind" strip sits at the top of the page
   - **Macro** — 7 fixed macro themes with direction badges and conviction bars
   - **Assets** — 13 asset scores (1-5) with tenure tracking
   - **Trades** — ETF position tracker with P&L
2. **Research**
   - **Economic Data** — FRED indicators with charts (requires `FRED_API_KEY`)
   - **Fed Watch** — FOMC statements, minutes, and speeches reader with LLM summaries
   - **Papers** — Research paper feed (FEDS, FEDS Notes, IFDP, arXiv q-fin) with read tracking
3. **Review**
   - **Weekly Review** — Time allocation and synthesis log
   - **Attribution** — View-vs-returns analysis with echarts
4. **Practice** — Interview practice with typed or voice answers, optional OpenRouter TTS question playback, and scoring. The home opens with a **PRACTICE** header and a reps-only pulse line, then the **My Views** quick-start board, the **QUANT REVIEW** card (My Models library, Quant Drill, Weak Spots, Surprise Me), a collapsed **Interview Prep** expansion (Job Interview, Research Defense, Readiness Check), and a centered **Custom session…** link; short setups open inline under their own section, unfinished sessions resume there too, and there is no Performance section

### Data Flow

1. User edits a UI field → event handler updates in-memory `AppState`
2. `save_state(state)` serializes to `data/state.json`
3. NiceGUI reactivity updates the UI; save-status label refreshes
4. Daily snapshots saved to `data/snapshots/state_YYYY-MM-DD.json`

### Module Responsibilities

| Module | Role |
|---|---|
| `app.py` | Entry point, MQ monogram header, global CSS theming (dark/light), 4-tab + secondary-tab routing, import/export/reset/settings dialogs |
| `config.py` | LLM provider defaults (OpenRouter and OpenCode Go), chat and Practice-TTS model slugs, max tokens, temperature; plus Obsidian default paths and interview fallback notes |
| `models/schema.py` | Pydantic v2 models: `AppState`, `MacroView`, `AssetView`, `Reconciliation`, `BriefingStrip`, `Trade`, plus `TopicView`, `ViewPoint`, `ViewFact`, `ViewPracticeMeta` |
| `models/interview.py` | Interview-practice models: `InterviewSession`, `InterviewQuestion`, `InterviewAnswer`, `InterviewPostmortem`, `InterviewDatabase` (`InterviewSession` also carries `model_note_ids`/`model_note_titles`/`model_context` for My Models sessions) |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON persistence; daily snapshots; schema migration |
| `storage/user_settings.py` | `data/user_settings.json` persistence (Obsidian paths, LLM provider/API keys/models, and Practice TTS enabled/model preferences) |
| `storage/interview_store.py` | `data/interview_history.json` persistence + performance summary + `model_practice_stats()` (per-note practice history) + read-time provenance (`effective_rubric_id`, `effective_input_method`, `comparability_key`, `trend_eligible`) and key-scoped trend numbers |
| `storage/fred_client.py` | FRED API client — ~50 macro indicators; ETF data via yfinance |
| `storage/fed_client.py` | Federal Reserve communications — FOMC statements/minutes/speeches listings, `#article` text extraction, permanent body cache |
| `storage/research_feeds.py` | Paper feed aggregator (FEDS, FEDS Notes, IFDP, arXiv q-fin) + `data/research_feed.json` read-state persistence |
| `storage/trade_prices.py` | yfinance price history — both raw close and adj close per ticker |
| `storage/model_library.py` | Read-only Obsidian Models folder scanner for My Models — `scan_model_notes()`, `models_folder_path()`, `model_context_for()`, `find_comparison_note()`; never writes, malformed files degrade to filename fallback |
| `services/talking_points.py` | Pure synthesis — `macro_prose()`, `fred_snippet()`, `asset_verbal()` |
| `services/llm_polish.py` | OpenRouter chat — briefing generation, polish, document summaries (`summarize()`), and disk cache |
| `services/attribution.py` | View-vs-returns engine — asset benchmark mapping (`ASSET_BENCH`), macro benchmark mapping (`MACRO_BENCH`), score timeline, hit-rate calculation |
| `services/topic_views.py` | TopicView AI helpers — `challenge_view()`, `views_context()` (note-structuring LLM helper removed); pure deck helpers `split_point()` (claim-first point splitting) and `RECALL_RATINGS` |
| `storage/topic_view_markdown.py` | TopicView Markdown parser/renderer for Obsidian sync |
| `storage/topic_view_sync.py` | TopicView <-> Obsidian Views folder sync engine and `data/topic_view_sync.json` persistence |
| `services/interview_llm.py` | Provider-neutral LLM client for interview practice |
| `services/interview_controller.py` | Interview session state machine — `start_session()`, `evaluate_answer()`, `advance_session()`, `session_stats()`, `synthesize_session()`; ordinary (postmortem-free) per-turn schema, one repair per turn, separate end-of-interview synthesis, controller-owned session end; `start_session()` accepts model-note metadata + hidden `model_context` |
| `services/interview_prompts.py` | Versioned prompt pack (`PROMPT_PACK_VERSION`) + built-in presets, including four model-note presets (`model_explain`/`model_defend`/`model_compare`/`model_deep_dive`, all Drill mode) and `QUANT_FUNDAMENTALS_OPENERS` |
| `services/interview_speech.py` | Local faster-whisper transcription server, `/api/interview/transcribe` route, and `speech_bias_context()` vocabulary prompt |
| `services/interview_speech_worker.py` | Isolated whisper worker subprocess |
| `services/interview_tts.py` | OpenRouter TTS proxy + `/api/interview/tts` route; per-model voice/capability mapping, safe voice fallback, and Gemini PCM-to-MP3 conversion |
| `services/fact_check.py` | Advisory web-grounded **Check facts** for a Say it rep — `fact_check_session()` (cached on the session, never raises on model failure), input-neutral `check_claims()`, pure `validate_claims()` (citation gate), and `_web_complete()` (one OpenRouter call with the `openrouter:web_search` server tool) |
| `setup_speech_runtime.py` | One-time installer for the isolated NumPy runtime used by whisper |
| `components/status_bar.py` | Summary staleness indicator ("X current / Y need review" + weekly review age) |
| `components/macro_views.py` | 7 fixed macro view rows — side-drawer editor, conviction bars, direction badges |
| `components/asset_views.py` | Asset Class Views tab — score grid + conviction tenure table |
| `components/topic_views.py` | My Views tab — TopicView rolodex, editor, AI assists; cards show level pips, a freshness stripe, and a one-click Still holds |
| `components/view_deck.py` | My Views **Flip through** deck — a picker (all listed / Core / Shaky last time / by tag), then one View at a time in Recall (default) or Read mode with a saved self-rated recall, Still holds, Quick edit (saves immediately, new facts dated today), **Say it** (one Deliver rep graded inline, typed or voice, with an optional click-gated **Check facts** block under the result), keyboard shortcuts, and an end-of-deck summary; also owns the shared level pips / freshness helpers |
| `services/view_progress.py` | Pure My Views weekly streak (`weekly_streak()`, `activity_dates()`, `note_activity()`), personal bests (`is_personal_best()`, `band_index()`), and `?deck=` link selection (`deck_for_link()`) |
| `components/undo_toast.py` | `show_undo()` — a small in-page Undo snackbar (one per client, 8 s) used by Still holds, recall ratings, and the Macro/Asset confirm buttons |
| `services/session_cleanup.py` | `stale_active_sessions()` (pure) and `abandon_stale_sessions()` — marks unfinished practice sessions older than 7 days abandoned via the controller's own abandon path |
| `services/view_levels.py` | Pure My Views levels (Blank → Sketch → Supported → Rehearsed → Battle-tested) and freshness (age vs priority cadence), derived at read time from View content and interview history; nothing stored |
| `components/briefing_strip.py` | "Top of Mind" textarea (rendered at the top of the My Views page) |
| `components/briefing.py` | Morning Briefing tab — LLM generation or template fallback |
| `components/reconciliation.py` | Weekly reconciliation form + history log (capped at 52) + quant focus inputs |
| `components/fred_panel.py` | FRED economic data — HTML tables with click-to-chart (echarts) |
| `components/fed_watch.py` | Fed Watch tab — two-pane reader for statements/minutes/speeches, LLM summary button |
| `components/research_feed.py` | Papers tab — merged feed list, unread/all filter, mark-read state |
| `components/trades.py` | Trade Tracker tab — add/close/delete ETF positions, price return vs total return |
| `components/attribution.py` | Attribution tab — echarts timeline, score analysis, streak badges |
| `components/interview_practice.py` | Practice tab UI — home is a PRACTICE header with a reps-only pulse line, then a My Views quick-start board (Deliver/Discuss/Defend toggle, PICK UP NEXT / KEEPING WARM rows), a QUANT REVIEW card (My Models library, Quant Drill, Weak Spots, Surprise Me), a collapsed Interview Prep expansion (Job Interview, Research Defense, Readiness Check), and a Custom session… link; short setups open inline per section, no Performance section; sparring loop, keyboard shortcuts, exit confirmation, draft-only answer tips, optional question TTS controls, immediate postmortem with a separate summary synthesis + Retry summary |
| `components/interview_speech.py` | Browser-side recorder glue for voice answers (live-caption preview + audio capture) |
| `components/interview_tts.py` | Browser playback glue for server-generated Practice question audio |
| `export/excel.py` | Multi-sheet Excel workbook — macro views, asset views, reconciliations |
| `export/topics.py` | One-way TopicView Markdown export placeholder; not the bidirectional sync engine |
| `validate_topic_view_sync.py` | Standalone validation for the TopicView ↔ Obsidian sync engine (temp dirs only, no network) |
| `validate_view_levels.py` | Standalone validation for My Views levels, grader isolation, freshness, Still holds, deck point splitting, weekly streak, and personal bests (pure in-memory) |
| `validate_interview_practice.py` | Standalone validation for interview practice persistence, per-turn evaluation/repair, provider-vs-output errors, controller-owned session end, and postmortems (temp dirs only, no network) |

### Header Visual Design (Current)

- **MQ Monogram** — Large gradient "MQ" logo (teal-to-green), staggered positioning
- **Title** — "MACROQUANT LEDGER" beside monogram
- **Live Clock** — Date + time below title, updates every 10s
- **Live Dot** — Pulsing green indicator showing app is active
- **Gradient Line** — Fading teal accent line under header
- **Status Bar** — Summary text showing current vs. needing-review macro views plus weekly-review age

### Pydantic Models

**`MacroView`** — 7 fixed instances:
- `id`: stable key (`growth`, `global_growth`, `inflation`, `fed`, `term_premium`, `credit`, `usd`)
- `name`: display label
- `lean`: short thesis text
- `signals`: list of 3 signal strings
- `counter`: prompt for what would change the view
- `direction`: `"Bullish"` | `"Neutral"` | `"Bearish"` | `"No View"`
- `conviction`: `"High"` | `"Medium"` | `"Low"` | `"—"`
- `flag`: UI color tag (default `"green"`)
- `last_touched`: timestamp for staleness

**`AssetView`** — 13 fixed instances (1 L1 + 7 Equities + 5 Fixed Income):
- `id`, `name`, `group` (`"l1"` | `"equities"` | `"fixed_income"`)
- `direction`: score `"—"` | `"1"` | `"2"` | `"3"` | `"4"` | `"5"`
- `"5"` = strong overweight, `"1"` = strong underweight
- `conviction`, `note`, `commentary`, `last_touched`

**`Trade`** — ETF positions:
- `id`, `ticker`, `entry_date`, `exit_date` (None = open), `size` ($ notional), `note`, `created_at`
- Price and total return fetched via yfinance

**`TopicView`** — dynamic "My Views" entries:
- `id`, `name`, `bottom_line`, `points` (list of `ViewPoint`)
- `counterargument`, `changes_my_mind`, `watch` (list of watch items)
- `status`: `"Developing"` | `"Ready"` | `"Needs Refresh"`
- `priority`: `"Core"` | `"Normal"` | `"Low Priority"`
- `archived`, `related_view_ids`, `created_at`, `updated_at`, `reviewed_at` (app-only "Still holds" timestamp, never synced), `practice` (`ViewPracticeMeta`)

**`AppState`** top-level fields:
- `macro_views`, `macro_notes`, `asset_views`, `quant_focus`, `quant_focus_next`
- `activity_days` (local ISO dates of My Views actions; capped at 400; feeds the weekly streak)
- `reconciliations`, `briefing`, `trades`, `topic_views`, `topic_views_version`

### Key Design Decisions

- **Fixed macro/asset sections** — Exactly 7 macro views and 13 asset views; no dynamic add/remove for those.
- **Dynamic TopicViews** — My Views entries can be created, archived, reordered, and deleted.
- **Asset scoring** — 1-5 score strings, not direction enums. Direction badge colors calculated from score.
- **Trade returns** — Uses adjusted close (includes dividends) for P&L. Critical for bond ETFs.
- **Staleness** — `last_touched` on every edit. Status summary flags views older than 28 days.
- **Attribution** — `ASSET_BENCH` maps asset views to ETFs; `MACRO_BENCH` maps macro views to FRED indicators. Timeline walks daily snapshots to find score change dates. Echarts shows price + score overlay.
- **Persistence** — JSON only. No database. Every edit calls `save_state()`.
- **Snapshots** — One per calendar day at `data/snapshots/`. Used for conviction tenure and attribution calculation.
- **LLM Cache** — `data/briefing_cache.json` keyed by (base URL + model + content hash); document summaries share it via a `"SUMMARY::"` digest prefix.
- **Fed doc bodies never change once published** — `fed_client.document_body()` caches them permanently to `data/fed_cache/<hash>.txt`; only the RSS listings re-fetch.
- **Schema Migration** — `persistence.py` `_migrate()` handles old `state.json` gracefully, seeds `topic_views_version`, and migrates legacy asset directions to 1-5 scores.
- **Interview History** — Practice sessions are persisted separately in `data/interview_history.json`. Sessions can be `active`, `completed`, or `abandoned`; exiting an in-progress session preserves any submitted answers but does not count it as completed or update My View practice metadata. If the file exists but cannot be read (bad JSON, a schema violation, or bad encoding), `load_database()` backs it up to `data/backups/interview_history_unreadable_<timestamp>.json` and raises `InterviewHistoryUnreadable` instead of returning an empty database, so no save can overwrite unreadable history; the Practice tab renders one error card naming the backup path, and the rest of the app keeps working. Re-reading an identical unreadable file reuses its existing backup rather than writing another.
- **My Views levels, freshness, and deck** — Levels are derived at read time (`services/view_levels.py`), never stored. Content: Sketch = bottom line + two titled points; Supported = also a counterargument and two facts. Practice: Rehearsed = at least two scored reps with the latest at 5+ (Band 5–6); Battle-tested = also a Defend rep at 7+ (Band 7–8). The View's level is the higher of its content and practice levels, and practice needs only a Sketch, so reps are never discarded for missing optional facts. Reps are grouped by (rubric id, grader model) and never mixed across groups, so switching grader can neither remove an earned level nor combine graders; retries, abandoned, custom, and unanchored sessions do not count. Preset and input method are deliberately not in the group (fixed bands of one shared rubric, not a trend), unlike `comparability_key()`. Freshness is days since `max(updated_at, reviewed_at)` over the priority cadence (`VIEW_CADENCE_DAYS`); the card stripe fades teal → slate between 0.5× and 2× cadence. **Still holds** sets only `reviewed_at`, so it never touches `updated_at` and never queues an Obsidian sync change. **Flip through** keeps the user's own order by default (Stalest first and Shuffle are opt-in); it never ranks or nags. It opens in **Recall** mode: the card starts face down (title, level, point count), Space reveals it in place (so an open Say it result survives), and the user rates the recall Nailed / Shaky / Blanked (keys 1/2/3, auto-advance). The rating is a local self-assessment saved as `ViewPracticeMeta.recall_last` / `recall_at` (app-only, not synced, no LLM call); it is shown subtly ("Recall: Shaky") and never affects levels, which only graded reps can raise. **Read** mode shows everything with no rating. Points render claim-first (`split_point`: a leading **bold** phrase, else the first sentence of a long point), with the remainder and facts folded under Details, and Markdown is rendered rather than shown raw. The Still holds / rating / Quick edit / Say it controls sit in a sticky bar (the Quasar panel ancestors are let overflow only while a deck is open, via `:has(.vd-shell)`). Keys are ignored while a panel is open, except Esc, which closes it. Finishing a pass shows a one-line summary (confirmed, edited, reps, level-ups, recall counts) and **Run the Shaky ones again**; per-pass stats are in memory only. **Weekly streak**: consecutive Monday-start weeks with any activity, where activity is a completed practice rep (any preset) or a recorded My Views action (`state.activity_days`: a real edit, Still holds, or a recall rating). An empty current week does not break it (it counts back from last week), and it is shown only at two or more weeks, as a quiet suffix on the My Views progress line and in the deck summary; it is not on the Practice home. **New best**: a Say it rep whose rubric band is higher than every earlier completed rep for that View under the same rubric, grader model, and practice style (bands, never raw scores; needs at least one earlier rep); shown as `NEW BEST · Band x–y` on the card and counted in the deck summary. There are no badges. **Deep link**: `/?deck=all|stale|shaky|core` opens the deck once on page load (`stale` is all Views stalest first; `shaky` is Shaky/Blanked; `core` is Core priority); an unknown key or an empty filter shows the overview with an info notice, and a plain `/` is unchanged. `launch.py --deck [choice]` builds that URL (a bare `--deck` means `all`) and `launch_macroQuantLedger.bat` forwards its arguments. **Undo**: Still holds (deck, overview card, Macro, Assets) and recall ratings offer an 8-second Undo toast that restores the previous `reviewed_at` / `last_touched` / recall values; in the deck the `U` key triggers it and returns to the undone card. The toast must be shown before any refresh that deletes the clicked button. **Macro and Asset Still holds** only refresh `last_touched` (it drives the staleness labels and the status bar's "current / need review" counts, and appears as the Excel export's last-touched column); attribution and conviction tenure come from daily snapshots, so confirming never changes them. **Clean up unfinished sessions…** (··· menu) marks active sessions started more than 7 days ago as abandoned after a confirm dialog: answers are kept and nothing counts as completed. **Say it** is a one-question `view_deliver` session (`start_session` + `evaluate_answer`) and counts as a full rep (View counts, diagnostics, trends); the card shows the band, critique, and fix immediately and the whole-session summary is written in the background. A provider/output failure keeps the draft and reuses the same session on retry; closing or leaving the panel mid-rep abandons the unfinished session so it never lingers as an active session in Practice.
- **My Models** — Quant Practice adds Explain / Defend / Compare / Deep Dive modes powered by read-only interview-facing model notes in an Obsidian folder; notes are hidden LLM context, never rewritten by the app, and nothing breaks when the folder is unavailable. See "Quant Model Notes (My Models)" below.
- **Practice feedback contract** — Every turn, in every mode, requires `score`, `critique`, and `fix`; those fields are private, are never placed in the question text, and `critique`/`fix` are written in the second person. Ordinary turns request only those fields plus one next question. The final turn is ordinary too: it evaluates the last answer only and requests no postmortem. One repair per turn (at most two LLM calls): a malformed response, missing score, or empty critique triggers a single retry at 1.5× the first call's budget, whose repair message lists every problem at once. A valid score saves as `ok` (score + critique + fix) or `partial` (score with critique or fix missing) on `InterviewAnswer.evaluation_status`; when a repair ran, the higher-ranked evaluation wins (a tie prefers the repair) and the next question keeps the better of the first and repair responses. No valid score after the repair raises `InterviewOutputError` and saves nothing. Empty model content is an output problem (`InterviewOutputError`, starvation hint logged, never displayed) rather than a provider failure (`InterviewProviderError`); the submit card shows distinct messages for the two and keeps the draft. The controller owns session end (`done = final_turn`) and sends `questions_remaining`.
- **End-of-interview synthesis** — Completion saves the final answer, sets `status="completed"`, and sets `postmortem = InterviewPostmortem(status="pending")`; the whole-interview review is a separate `synthesize_session()` call fed one record per answer plus app-computed `session_stats()` numbers stated as facts the model must not recompute (retries excluded everywhere; `partial` answers with scores count). Answer text is capped at 1,000 characters unless the session has three or fewer questions. One repair at 1.5× `SYNTHESIS_MAX_TOKENS` (900). Failures never raise: they record `status="missing"` plus `InterviewPostmortem.synthesis_error` (`"provider"` or `"output"`). An `ok` summary is never re-billed and a usable `partial` summary is never downgraded. The review follows a coach's-debrief tone contract: honest about every gap, but every weakness is paired with what a stronger answer would have said and one concrete drill, gaps are expressed as fixable behaviors rather than global judgments, and no pass/fail verdict is written (Job Interview reports the distance to the bar instead of a pass likelihood). This is a tone-only contract — the rubric, bands, and score scale are unchanged, so `PROMPT_PACK_VERSION` is deliberately not bumped. `_record_view_counts()` bumps View counts once at completion; `_record_view_diagnostic()` writes the review's diagnostics only when the session is the newest completed session for that View. The results screen renders immediately with "Writing summary…", then a muted stats line, and — for `pending` (interrupted), `missing`, or `partial` — a **Retry summary** button inside the summary card; the refreshed session is applied only if the user is still on that session.
- **Anchored scoring rubric** — The shared 1-10 score is graded against a rubric with reachable bands, not a bare "integer 1-10". Phase 2 splits it into three families in `interview_controller.RUBRICS`: `argument-v3`, `technical-v3`, and `interview-v3`. All three keep the same score ranges, grade-discipline paragraph, and closing sentence; only the band descriptors differ (argument keeps the Phase 1 bands verbatim), and `rubric_family_for()` selects a session's bands (legacy `shared-v2`/`unanchored` use argument). Each preset declares a `rubric_family` in `interview_prompts.py`; `_evaluation_schema()` injects the session's family rubric and `reference_answer()` cites it. `PROMPT_PACK_VERSION` was bumped to `2026.09.24-v3`; the old value is preserved as `LEGACY_V2_PROMPT_PACK` (`2026.09.22-v2`). Legacy data is never rewritten: `effective_rubric_id()` derives `"custom"` (prompt override), `"shared-v2"` (== `LEGACY_V2_PROMPT_PACK`), or `"unanchored"` (older); `start_session()` stores `"custom"` for a prompt override, otherwise the preset family's id.
- **Grader default, not a hard pin** — Scored View modes (Deliver/Discuss/Defend) default the model selector to `INTERVIEW_GRADER_MODEL` (falling back to the saved `preferred_model`), but the model stays selectable so a more thoughtful model can be chosen per session. Scores are only comparable within one **comparability key** (`storage/interview_store.comparability_key()` = effective rubric id, grader model, preset key, effective input method), and `trend_eligible()` admits only completed, non-retry, scored answers from a real rubric family.
- **Trend comparability** — `view_practice_stats()` computes each View's series, latest, previous, best, deltas and the 10-rep suppression count only from sessions sharing the key of its most recent eligible session, and reports `other_key_sessions` for the rest. `performance_summary()` and `model_practice_stats()` count score numbers only from `*-v3` answers by the currently selected grader (`preferred_model`); `performance_summary()`'s improving flag is evaluated within one comparability key per topic. `weakness_context()` keeps failure tags from all sessions (prompt hints, not displayed scores) while its strong-topic score numbers follow the same rule. `shared-v2` sessions form their own key and are never merged with `*-v3`.
- **Practice failure tags** — `recent_answers()` in `interview_store.py` returns completed sessions only, newest-first, flattened to answers, filtering on `practice_style`/`preset_key` (never `mode`: Deliver is `mode == "Discussion"`, `practice_style == "Deliver"`, `preset_key == "view_deliver"`). The schema caps `failure_tags` at **3** (`_evaluation_schema` line + controller clamp + chip cap). The postmortem renders the rep's tags plus per-tag counts over the last 10 reps, a direction clause (`down from N of 10 before`) only once 20 reps exist, and at most **two** `TAG — not flagged in last N reps` lines, shown only for tags absent from **two or more** consecutive reps whose last flag was within the **last 10 reps** (one absence is noise; a tag last seen deep in the history is padding, not progress, and the gate also bounds the streak so no line can span the whole history). Empty tags render nothing — no empty chip row.
- **Postmortem presentation** — The results screen is a reading column capped at `68ch` (`.pm-col`); body text uses `.pm-body` (15px, `var(--text-primary)`, AA in both themes) while section labels and the red chips are unchanged. The `not flagged` line uses the one dedicated positive accent (`.pm-cleared`, `#34d399` dark / `#15803d` light). Button order is Try Again (primary, leftmost) … Surprise Again (secondary, rightmost). `InterviewPostmortem.status` drives honest rendering: legacy sessions (`status == ""`) render exactly as before; `missing` replaces OVERALL with an amber `.pm-warn` note ("Summary unavailable …") and shows no band; `partial` adds an amber `PARTIAL SUMMARY` label. New (non-legacy) sessions also get a collapsed **Answer-by-answer feedback** expansion (score, `evaluation_status`, retry marker, question, tags, critique, and `FIX` per answer), shown only when at least one answer has a critique. A Drill turn with `evaluation_status == "partial"` shows an amber "Partial feedback — the model returned a score but was missing a critique or fix." note instead of the removed "No material failure identified." fallback. The results screen renders immediately after the final answer as `pending` ("Writing summary…"), then shows a muted `session_stats()` line (e.g. "12 of 14 answers evaluated · average 6.4 · Band: 5–6 · most frequent: RAMBLE"), then the review once `synthesize_session()` succeeds. `pending` (interrupted), `missing`, and `partial` show a **Retry summary** button inside the summary card; `missing` states whether the failure was provider or output (`synthesis_error`).
- **Postmortem score band** — The postmortem surfaces the session score only as its rubric band, directly under OVERALL: `Band 3–4 · <descriptor>` (`.pm-body`, semibold) plus a dimmed `Next band: <descriptor>` line (`var(--text-muted)`), omitted for the top band (9–10) and when no answer was scored. Descriptors come verbatim from the session's family rubric via `rubric_band_for()` — never paraphrased, and the raw 1–10 integer is never shown on this screen. The band is computed by `interview_controller.session_band()`: new sessions average only first-attempt answers (retries excluded, matching `view_practice_stats()`) and show no band unless at least **75% of first attempts** are scored and the postmortem status is not `missing`; legacy sessions (`status == ""`) keep the historical average over every graded answer. Rounding is half up (`int(avg + 0.5)`); averaging is within-session only, never across models. The band line renders only when `band_visible(session)` is true (effective rubric id not `unanchored`/`custom`), so Phase 1 anchored sessions keep their band while custom and unanchored sessions hide it. The mid-session Drill feedback `SCORE x / 10` is unchanged.
- **Practice home pulse** — A single dimmed line under the Practice header (`practice_pulse()`) shows only `N reps this week`, and it is hidden when the count is zero.
- **Practice reference answer** — A click-gated **Show a strong version** button in the View and Job Interview postmortems makes one extra LLM call for a 150-200 word answer at the 7-8 bar plus 2-3 structural differences from the user's own delivery, grounded in the session's own question and context (stored View or Job Interview materials). It is never auto-shown, and the result is cached on `InterviewSession.reference_answer` so a re-render never re-bills the call.
- **Quick-start movement suppressed** — Movement (delta, sparkline/trend, and delta tooltip) requires two gates: app-wide, at least 10 `trend_eligible()` sessions whose effective rubric id is a current `*-v3` id (`storage/interview_store.trend_session_count()`, not scoped to View sessions); per View, at least 2 eligible sessions under its current comparability key (`current_key_sessions`). Latest/best scores remain visible. Where a View's trend is shown, a small muted note reads "N earlier sessions graded differently aren't compared." when `other_key_sessions > 0`, and "New scoring — building a baseline." when the current key has fewer than two sessions.
- **Practice draft tips** — **Get Answer Tips** is a separate, plain-text coaching call on the unsaved current draft. It returns exactly three actionable tips (structure, reasoning/mechanism, evidence/caveat), never scores, saves, or advances the answer. Stored View content is optional secondary context only and may be stale; it must never be treated as authoritative or forced into an answer.
- **Practice keyboard flow** — `Ctrl/Cmd+Enter` submits an answer (or advances from Drill feedback); `Alt+M` starts/stops voice recording. Bare Enter and Space remain available for writing, and question replay remains button-only to avoid browser shortcut conflicts.
- **Practice Surprise Again** — Sessions launched from either surprise path (random My View or random model note) persist `InterviewSession.surprise`. Their postmortem shows a **Surprise Again** button that immediately starts a fresh surprise of the same kind; for Views it re-draws another active View via `_pick_recent()` (avoiding the last few), and for Quant it re-draws a random model note and mode. **Try Again is the primary (teal) action and sits leftmost in both postmortem rows; Surprise Again is secondary and rightmost.** Non-surprise sessions do not show Surprise Again.
- **Practice voice controls** — Voice capture produces an editable live draft: on stop, the browser's instant live captions seed the draft and the local faster-whisper pipeline then refines it with a vocabulary-biased transcript (`components/interview_practice.py::transcribe_voice`). An untouched caption draft is replaced in place; if the candidate edited the draft while whisper ran, the edits are kept and the refined text is offered via a **Use refined transcript** button (setting the answer to `base + refined`) instead of being appended, which used to duplicate the answer. If the isolated speech runtime is unavailable or transcription fails, the caption draft simply stands — no error, no extra editing step — so a machine without the whisper runtime still works. The bias prompt is `services/interview_speech.py::speech_bias_context` (≤500 chars): the standing `STT_GLOSSARY` (term premium, hyperscaler, capex, basis points, HY, IG, BB/BBB, r>g, breakeven, duration, carry, spread, dispersion, AI data centers, HBM) plus the session topic and a trim of the stored View, deliberately **not** the caption text, which would anchor the mishearing. A transcript that lands after the turn was submitted or discarded is dropped (`turn_token`). A small violet **Replay** control (`.interview-replay-btn`, inside `mq-interview-css`) toggles playback of the just-recorded answer straight from the browser-memory Blob — no server round-trip, nothing written to disk or to `AppState`. Voice audio is retained for the current answer turn only and released by `cancel_recording()`/`dispose()` on submit, discard, or a new recording; transcription success deliberately no longer nulls `lastBlob`, since that used to destroy the audio the instant the transcript arrived.
- **Transcript grading safety net** — `compose_runtime_prompt(..., transcript_note=True)` appends `TRANSCRIPT_NOTE` to the **RESPONSE CONTRACT** and only there; `BASE_INTERVIEWER_PROMPT` is untouched. It applies **only to voice-origin answers** (`InterviewAnswer.voice`, threaded through `evaluate_answer(..., voice_origin=...)` from the recorder flow), so typed answers keep full strictness. The clause tells the grader the answer is an unedited transcript and forbids penalizing plausible mishearing, homophone, or missing-punctuation artifacts — or assigning a failure tag on that basis. `PROMPT_PACK_VERSION` is deliberately not bumped: the rubric and score scale are unchanged.
- **Stale-card grading note** — Sessions that carry a stored View (`session.view_context`: Deliver, Discuss, Defend, Say it) get `prompts.view_currency_note(today)` appended to the **RESPONSE CONTRACT** only (after `EVALUATION_PRIVACY_NOTE`, before `TRANSCRIPT_NOTE`), plus the same note in the synthesis prompt's `setup` and the reference-answer prompt. It tells the grader the View is the candidate's own notes and may be out of date, that answers are graded on quality and accuracy rather than fidelity to the card, and that omitting a stale point or adding correct newer material is not a weakness; an unverifiable figure is not to be marked wrong or tagged `KNOWLEDGE_GAP`/`UNSUPPORTED_ASSERTION` on that basis alone. `PRESET_VIEW_DELIVER`'s postmortem lists only still-current stored points under "Missed / weak" and adds a "Beyond the notes" item. `interview_controller._today()` supplies the date (monkeypatchable in tests) and `view_context()` ends with a `last_updated` key (latest of `updated_at`/`reviewed_at`). Sessions without a View (Quant Drill, My Models, Job Interview) are unchanged. `PROMPT_PACK_VERSION` and the rubric ids are deliberately not bumped: comparability keys on the stored `rubric_id`, so a bump would separate nothing and a new id would break the `*-v3` gates. Expect View scores to run slightly higher than before where a card was stale.
- **Check facts** — A secondary button in the deck's Say it result (shown only when an OpenRouter key is stored) makes one `fact_check_session()` call: the model checks up to 6 verifiable claims from the answer (origin `answer`) and then dated facts from the stored View (origin `card`) using OpenRouter's `openrouter:web_search` server tool (the deprecated `web` plugin searches once on the whole prompt; the server tool lets the model write targeted queries, capped by `FACT_CHECK_MAX_SEARCHES`). It is **advisory only**: never in the score, band, levels, trends, failure tags, synthesis, or personal bests, and the block says so. It is click-gated, never automatic, and deck-only. The result is cached on `InterviewSession.fact_check` (`FactCheck` / `FactCheckClaim` in `models/interview.py`; old history files load with `None`), so re-rendering never re-bills; a failure stores `status="missing"` with `error` `provider` or `output` and never raises, and an `ok` result with `error="no_citations"` is stored but can be retried. Statuses are **citation-gated** (`validate_claims`): `current`/`outdated`/`wrong` stand only if the claim's `source_url` is among the `url_citation` annotations the search returned (compared by host and path, ignoring scheme, `www`, query, and trailing slash); otherwise it becomes `unverifiable` and any figure, date, and URL it carried are dropped rather than shown. A dictated answer's number that could be misheard is `unverifiable`, never `wrong`. It always uses the stored OpenRouter key even when chat runs on OpenCode Go, defaults to `FACT_CHECK_MODEL_DEFAULT` (`z-ai/glm-5.3`, override `INTERVIEW_FACT_CHECK_MODEL`; a model without native search is served by OpenRouter's Exa fallback), omits `temperature` (several search models reject it), sends `reasoning: {effort: minimal}` instead of disabling reasoning (GLM 5.3 refuses to disable it, and with the search tool in the request OpenRouter reports that as a generic `400 invalid request` that never mentions reasoning, so it cannot be detected from the message; a 400 is retried once without the hint, anything else is never resent), and gets a larger token budget (`FACT_CHECK_MAX_TOKENS`, 1500) than other compact calls because reasoning and tool turns share it. `check_claims()` takes an answer and/or card facts so a later card-level Refresh can reuse it.
- **Background session writes** — Anything that makes a slow model call between loading and saving a session (`synthesize_session`, `reference_answer`, `fact_check_session`) must do the call first and then change only its own field through `interview_store.update_session(session_id, mutate)`, which reloads the stored session under the lock. Saving the copy loaded before the call erased fields written meanwhile (for example a summary finishing after "Show a strong version"). `synthesize_session` applies its never-downgrade comparison to the freshly loaded session.
- **Practice TTS** — Optional question playback uses the local `/api/interview/tts` proxy and the stored OpenRouter key, never a browser-exposed key or the interview chat provider. The selectable models are Gemini 3.1 Flash TTS (default), Grok Voice TTS, and Deepgram Flux. Voice IDs and format behavior are explicitly per-model; Gemini PCM is transcoded to MP3 in memory with PyAV before browser playback.

### TopicView Obsidian Sync (Optional)

My Views can optionally sync bidirectionally with a dedicated Obsidian Views folder.

- **Separate from export** — `export/topics.py` is a one-way export. Sync is handled by `storage/topic_view_markdown.py` (parse/render) and `storage/topic_view_sync.py` (reconciliation).
- **Opt-in** — Configure the Obsidian Views folder and enable sync in **··· → Settings**. If disabled or unconfigured, the app behaves exactly as before.
- **Mapping** — Markdown `view_id` maps to `TopicView.id`, H1 title to `TopicView.name`, `## My View` to `bottom_line`, ordered `## Why` items to `points` with indented sub-bullets as `facts` (text only), `## Watch` bullets to `watch`, `## Counterargument` and `## What Changes My Mind` to those fields. `status`, `priority`, and `archived` sync via frontmatter. Timestamps round-trip as human-readable `YYYY-MM-DD HH:MM:SS` (UTC, second precision); the parser also accepts full ISO 8601 and date-only values.
- **Tags, not type** — Notes are typed by a guaranteed `view` entry in `tags` (user-added custom tags preserved verbatim); there is no `type` frontmatter property, and any legacy one is removed on rewrite.
- **Lossless bodies** — Content outside owned sections (extra headings, prose, callouts) is preserved byte-for-byte and in position on every rewrite; the app only regenerates its own sections. Duplicate owned sections fail closed: the note is excluded from all sync decisions, left untouched, and flagged with the offending headings until manually resolved.
- **Absent section ≠ empty** — If an owned section is missing from a note, the corresponding app field is left untouched rather than wiped. Present-but-empty clears it.
- **Merge-on-import** — Vault edits are merged onto existing points/facts by title/text alignment (in-place edits keep object identity, so fact source/as_of/note survive); reorders reuse objects by key; genuinely new lines create blank-fact points.
- **Two-truth hashing** — Sync records store a full-file hash (vault side) plus a layout-independent canonical render hash (app side), so reorganizing or annotating a note never registers as an app change. A `format_version` mismatch triggers one-time re-baselining via merge-import.
- **Pre-migration backup** — Before that re-baseline modifies anything, all vault notes plus `data/state.json` and the current sync-state file are copied into `data/backups/pre_migration_<timestamp>/`. Backup failure aborts the sync with no modifications; successful reruns after recovery create new timestamped backups rather than overwriting.
- **App-only fields preserved** — fact `source`/`as_of`/`note` detail, `related_view_ids`, `practice` metadata, and internal IDs remain in `data/state.json` and never enter the notes; everything else in the contract round-trips losslessly through Markdown.
- **Stable identity** — Notes use the existing `TopicView.id`. If a note lacks an id, the app assigns one and writes it back safely. Renaming the note title or filename does not create duplicates.
- **Title-based filenames** — Notes are named after the View title (e.g. `US Labor.md`); identity comes solely from frontmatter `view_id`. Renaming a View in the app renames the note on next sync; manually renaming a file in Obsidian is respected and kept. Duplicate titles get a short-id suffix (e.g. `Alpha (1a2b3c4d).md`). If multiple notes declare the same id, the engine prefers the last-synced one and surfaces a warning.
- **JSON persistence remains authoritative** — `data/state.json` is still the source of truth for overall `AppState`. Obsidian is an optional external representation.
- **Conflict behavior** — When both the app and a vault note change since the last sync, the View is marked as conflicting. No side is overwritten automatically; the user chooses **Keep App**, **Keep Vault**, or dismisses.
- **Deletion safety** — The sync engine never automatically deletes an app View or an Obsidian file. Missing files or deleted app Views are surfaced as conflicts or left untouched.
- **Sync triggers** — Sync is fully manual: it runs only when the user clicks **Review & Sync…**, which opens a diff-selection dialog (via `plan_sync()` / `apply_sync_plan()` in `storage/topic_view_sync.py`). Nothing syncs on tab open or after saving; every EXPORT/IMPORT/CREATE requires an explicit per-View "Use App" / "Use Obsidian" choice, and notes whose bytes changed since the plan was built are skipped with a warning instead of written.
- **View editor apply model** — The TopicView editor edits a deep-copied draft; nothing persists until **Apply Changes** (sticky bar at the top lists exactly which fields changed). Discard reverts the draft; leaving the editor with unsaved changes prompts first. Overview-level actions (new/delete/reorder topic) still persist immediately since each is itself an explicit click. Archiving lives only at the bottom of the View editor behind a confirm dialog (blocked while the draft has unsaved edits); restoring happens via a Restore button on cards in the Archived expansion — there is no one-click archive on active cards.
- **Sync state** — Lightweight sync metadata (content hashes, `updated_at`, conflict status) is stored in `data/topic_view_sync.json`, not inside the user's Markdown notes.

### Quant Model Notes (My Models)

Quant Practice reads interview-facing model notes from a personal Obsidian Models folder and uses them as hidden context for technique practice. This is intentionally simpler than the My Views sync — the folder is **read-only**; Obsidian owns the Markdown and the app never rewrites it.

- **Config** — "Quant Models Folder" user setting (`storage/user_settings.py::quant_models_folder()`), defaulting to `config.OBSIDIAN_MODELS_FOLDER_DEFAULT`. Override with `QUANT_MODELS_FOLDER`. The app starts and generic Quant Drill works even when the folder is missing or empty; My Models just shows a setup/empty state. This keeps a future work-computer copy without the vault fully functional.
- **Discovery** — `storage/model_library.py::scan_model_notes()` finds Markdown files and derives title (frontmatter `title` > first H1 > filename), path, tags, `status`/`priority`, kind, mtime, and raw body — no LLM, no shared heading schema. Index notes and `_`-prefixed/`.`-hidden paths are skipped; malformed YAML or an unclosed fence degrades only that one file to a filename title with a warning and leaves the bytes untouched. Titles/ids trim a trailing "Interview" suffix.
- **Usage** — Notes are rendered by `model_context_for()` into a single hidden `# MODEL REFERENCE NOTES` block passed to `start_session()` as `model_context`; it is composed into the system prompt only. All four modes (**Explain / Defend / Compare / Deep Dive**) reuse the existing **Drill** engine, voice/TTS, scoring, and failure-tag system — no parallel practice engine or analytics. **Compare** auto-attaches a dedicated "A vs B" note via `find_comparison_note()` (title-word / tag / acronym matching) when one exists.
- **Never fabricate experience** — Model prompts forbid inventing the candidate's datasets, results, hyperparameters, or projects; the note describes the technique, and "How did you use this?" is answered by the user and evaluated normally.
- **History** — `InterviewSession` stores `model_note_ids` / `model_note_titles` / `model_context` and `practice_style`; `storage/interview_store.py::model_practice_stats()` powers the per-note "Last practiced…" line for future reporting. No dedicated dashboard yet.
- **Refresh** — The library rescans each time the Practice home / model library renders and on the explicit **Refresh Models** button; no filesystem watcher and no background sync.
- **Quant Fundamentals stays separate** — The generic Quant Drill answers "can I handle general quant questions?"; My Models answers "can I explain and defend techniques I claim to know?" Both coexist.

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `FRED_API_KEY` | Optional | FRED macro indicator data (panel hidden if absent) |
| `OPENROUTER_API_KEY` | Optional | LLM API key when provider is OpenRouter |
| `OPENROUTER_BASE_URL` | Optional | OpenRouter-compatible endpoint override |
| `OPENROUTER_MODEL` | Optional | Default chat model override for OpenRouter |
| `OPENROUTER_POLISH_MODEL` | Optional | Polish-specific model for OpenRouter |
| `OPENROUTER_RESEARCH_MODEL` | Optional | Research-summary model for OpenRouter |
| `OPENROUTER_MAX_TOKENS_POLISH` | Optional | Polish token limit |
| `OPENROUTER_TEMPERATURE` | Optional | Sampling temperature |
| `OPENROUTER_HTTP_REFERER` | Optional | OpenRouter HTTP referer header |
| `OPENROUTER_APP_NAME` | Optional | OpenRouter app name header |
| `OPENCODE_API_KEY` | Optional | LLM API key when provider is OpenCode Go |
| `OPENCODE_BASE_URL` | Optional | OpenCode Go endpoint override |
| `OPENCODE_MODEL` | Optional | Default chat model override for OpenCode Go |
| `OPENCODE_POLISH_MODEL` | Optional | Polish-specific model for OpenCode Go |
| `OPENCODE_RESEARCH_MODEL` | Optional | Research-summary model for OpenCode Go |
| `MQLEDGER_LLM_PROVIDER` | Optional | `openrouter` (default) or `opencode_go`; overrides Settings |
| `OBSIDIAN_EXPORT_PATH` | Optional | Override Obsidian export folder |
| `OBSIDIAN_VIEWS_FOLDER` | Optional | Override Obsidian Views folder for bidirectional My Views sync |
| `QUANT_MODELS_FOLDER` | Optional | Override read-only Obsidian Models folder powering Practice "My Models" (falls back to Settings, then `config.OBSIDIAN_MODELS_FOLDER_DEFAULT`) |
| `MQLEDGER_PORT` | Optional | App port (default `8080`) |
| `MQLEDGER_HOST` | Optional | App bind host (default `127.0.0.1`) |
| `INTERVIEW_API_KEY` | Optional | API key for interview LLM |
| `INTERVIEW_BASE_URL` | Optional | Interview LLM endpoint |
| `INTERVIEW_MODEL` | Optional | Interview model slug |
| `INTERVIEW_GRADER_MODEL` | Optional | Default model for scored View practice (Deliver/Discuss/Defend); still user-selectable per session (defaults `z-ai/glm-5.3` on OpenRouter, `glm-5.3` on OpenCode Go) |
| `INTERVIEW_FACT_CHECK_MODEL` | Optional | OpenRouter model for the deck's Check facts (default `z-ai/glm-5.3`; always uses the stored OpenRouter key, even if interview chat uses OpenCode Go) |
| `INTERVIEW_TTS_MODEL` | Optional | OpenRouter model for Practice question playback (default `google/gemini-3.1-flash-tts-preview`; requires an OpenRouter key even if interview chat uses OpenCode Go) |
| `INTERVIEW_STT_MODEL` | Optional | Whisper model for transcription (default `small.en`) |
| `INTERVIEW_STT_DEVICE` | Optional | Whisper device: `cpu`, `cuda`, or `auto` (default `cpu`) |
| `INTERVIEW_STT_TIMEOUT` | Optional | Whisper transcription timeout in seconds (default `300`) |

### Data Directory

```
data/
├── state.json              # Current app state (gitignored)
├── briefing_cache.json     # LLM response cache (gitignored)
├── user_settings.json      # Obsidian export path + Obsidian Views folder + app settings (gitignored)
├── interview_history.json  # Interview practice history (gitignored)
├── topic_view_sync.json    # Obsidian View sync state: hashes, timestamps, conflicts (gitignored)
├── research_feed.json      # Paper feed items + read/unread state (gitignored)
├── fed_cache/              # Cached full text of Fed statements/minutes/speeches (gitignored)
├── snapshots/
│   └── state_YYYY-MM-DD.json  # One snapshot per calendar day (gitignored)
├── models/
│   └── whisper/            # Downloaded faster-whisper model (gitignored)
└── speech_runtime/
    └── numpy/              # Isolated NumPy runtime for whisper (gitignored)
```

### Known Issues & Constraints

- **Reasoning models starve compact budgets** — `max_tokens` is a *combined* budget: hidden reasoning tokens are charged against it before any visible content is emitted. With the compact budgets used here, reasoning consumes the whole allowance and the call returns **empty content**, not an error. Every interview and polish call therefore disables reasoning via `extra_body={"reasoning": {"enabled": False}}` — `extra_body` specifically, because the OpenAI SDK has no `**kwargs` and rejects a plain `reasoning=` kwarg with `TypeError`. **Raising the budget is not a fix**: `tencent/hy4-preview` burned 1500 tokens on reasoning and still returned nothing. Tell-tale symptoms if this regresses: the *"The model returned unusable feedback twice."* message in Practice, *"The model returned an empty response. Try again or switch models."* on **Get Answer Tips**, or empty Briefing text.
- **OpenCode Go may be unusable — parked, not investigated** — `POST https://opencode.ai/zen/go/v1/chat/completions` returns `400 MissingSessionID` (*"Request is missing x-opencode-session"*) and the app sends no such header. Separately, the configured `OPENCODE_API_KEY` is **suspected stale**; verify/replace the key before investigating the header, since a key problem would mask it. Practice was confirmed to be running on OpenRouter, so this does not currently affect the reported Practice failures.

### Deprecated / Removed

- **Bull/Bear icons** — No longer rendered in the UI. The `_BULL_SVG` and `_BEAR_SVG` constants still exist in `app.py` as unused dead code.
- **Today tab** — Removed; the app opens on Views → My Views, and the "Top of Mind" strip now sits at the top of My Views (`render_briefing_strip(..., compact=True)` in `components/topic_views.py`). The strip's `.today-top-of-mind*` CSS classes keep their historic names.
- **Subtitle** — "view inventory · quant tracker · reconciliation" removed. Replaced with live clock.
- `ui.add_css()` — **Never use.** Use `ui.add_head_html('<style id="...">...</style>')` instead.
- **`SPEC.md`** — Removed entirely. Any reference to it as authoritative is stale.

### Documentation Notes

- **`CLAUDE.md` is now stale.** It still describes a 6-tab layout, 15 asset views, a hardcoded Obsidian path, and `SPEC.md` as authoritative. Do not trust it for current structure.
- **`check_syntax.py` checks 51 files** (`services/fact_check.py` is the newest; 44 before the My Views deck and its helpers — `view_deck`, `undo_toast`, `view_levels`, `view_progress`, `session_cleanup`, and `validate_view_levels.py` — were added).
- **Trust actual source code** over any markdown documentation.
