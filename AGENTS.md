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
python app.py

# Validate syntax across core files
python check_syntax.py

# Validate TopicView <-> Obsidian sync logic (uses temp dirs only)
python validate_topic_view_sync.py
```

There are **no automated test suites, linters, or CI pipelines**. The TopicView/Obsidian sync layer has a standalone validation script (`validate_topic_view_sync.py`) that must pass after changes to it.

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
- `mq-interview-css` (components/interview_practice.py)

## Architecture

**MacroQuantLedger** is a local single-page dashboard for macro-quant research tracking. It uses [NiceGUI](https://nicegui.io/) (Python → Vue.js/Quasar) for the web UI, Pydantic v2 for data models, and JSON for persistence.

### Tabs (5 primary tabs + secondary tabs)

1. **Today** — Landing dashboard: greeting, "Top of Mind" strip, desk-status metric cards
2. **Views**
   - **My Views** — Living rolodex of structured arguments (TopicViews)
   - **Macro** — 7 fixed macro themes with direction badges and conviction bars
   - **Assets** — 13 asset scores (1-5) with tenure tracking
   - **Trades** — ETF position tracker with P&L
3. **Research**
   - **Briefing** — LLM-generated morning brief or template view
   - **Economic Data** — FRED indicators with charts (requires `FRED_API_KEY`)
4. **Review**
   - **Weekly Review** — Time allocation and synthesis log
   - **Attribution** — View-vs-returns analysis with echarts
5. **Practice** — Interview practice with typed or voice answers, scoring, and performance history

### Data Flow

1. User edits a UI field → event handler updates in-memory `AppState`
2. `save_state(state)` serializes to `data/state.json`
3. NiceGUI reactivity updates the UI; save-status label refreshes
4. Daily snapshots saved to `data/snapshots/state_YYYY-MM-DD.json`

### Module Responsibilities

| Module | Role |
|---|---|
| `app.py` | Entry point, MQ monogram header, global CSS theming (dark/light), 5-tab + secondary-tab routing, import/export/reset/settings dialogs |
| `config.py` | OpenRouter defaults — base URL, default model slug, max tokens, temperature; plus `OBSIDIAN_EXPORT_PATH_DEFAULT`, `OBSIDIAN_VIEWS_FOLDER_DEFAULT`, and interview fallback notes |
| `models/schema.py` | Pydantic v2 models: `AppState`, `MacroView`, `AssetView`, `Reconciliation`, `BriefingStrip`, `Trade`, plus `TopicView`, `ViewPoint`, `ViewFact`, `ViewPracticeMeta` |
| `models/interview.py` | Interview-practice models: `InterviewSession`, `InterviewQuestion`, `InterviewAnswer`, `InterviewPostmortem`, `InterviewDatabase` |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON persistence; daily snapshots; schema migration |
| `storage/user_settings.py` | `data/user_settings.json` persistence (Obsidian export path and Obsidian Views folder) |
| `storage/interview_store.py` | `data/interview_history.json` persistence + performance summary |
| `storage/fred_client.py` | FRED API client — ~50 macro indicators; ETF data via yfinance |
| `storage/trade_prices.py` | yfinance price history — both raw close and adj close per ticker |
| `services/talking_points.py` | Pure synthesis — `macro_prose()`, `fred_snippet()`, `asset_verbal()` |
| `services/llm_polish.py` | OpenRouter chat — briefing generation, polish, and disk cache |
| `services/attribution.py` | View-vs-returns engine — asset benchmark mapping (`ASSET_BENCH`), macro benchmark mapping (`MACRO_BENCH`), score timeline, hit-rate calculation |
| `services/topic_views.py` | TopicView AI helpers — `structure_notes()`, `improve_flow()`, `challenge_view()`, `views_context()` |
| `storage/topic_view_markdown.py` | TopicView Markdown parser/renderer for Obsidian sync |
| `storage/topic_view_sync.py` | TopicView <-> Obsidian Views folder sync engine and `data/topic_view_sync.json` persistence |
| `services/interview_llm.py` | Provider-neutral LLM client for interview practice |
| `services/interview_controller.py` | Interview session state machine — `start_session()`, `evaluate_answer()`, `advance_session()` |
| `services/interview_prompts.py` | Versioned prompt pack (`PROMPT_PACK_VERSION`) + built-in presets |
| `services/interview_speech.py` | Local faster-whisper transcription server + `/api/interview/transcribe` route |
| `services/interview_speech_worker.py` | Isolated whisper worker subprocess |
| `setup_speech_runtime.py` | One-time installer for the isolated NumPy runtime used by whisper |
| `components/status_bar.py` | Summary staleness indicator ("X current / Y need review" + weekly review age) |
| `components/today.py` | Today tab dashboard |
| `components/macro_views.py` | 7 fixed macro view rows — side-drawer editor, conviction bars, direction badges |
| `components/asset_views.py` | Asset Class Views tab — score grid + conviction tenure table |
| `components/topic_views.py` | My Views tab — TopicView rolodex, editor, AI assists |
| `components/briefing_strip.py` | "Top of Mind" textarea (rendered inside the Today tab) |
| `components/briefing.py` | Morning Briefing tab — LLM generation or template fallback |
| `components/reconciliation.py` | Weekly reconciliation form + history log (capped at 52) + quant focus inputs |
| `components/fred_panel.py` | FRED economic data — HTML tables with click-to-chart (echarts) |
| `components/trades.py` | Trade Tracker tab — add/close/delete ETF positions, price return vs total return |
| `components/attribution.py` | Attribution tab — echarts timeline, score analysis, streak badges |
| `components/interview_practice.py` | Practice tab UI — setup, sparring loop, postmortem, performance stats |
| `components/interview_speech.py` | Browser-side recorder glue for voice answers |
| `export/excel.py` | Multi-sheet Excel workbook — macro views, asset views, reconciliations |
| `export/topics.py` | One-way TopicView Markdown export placeholder; not the bidirectional sync engine |

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
- `archived`, `related_view_ids`, `created_at`, `updated_at`, `practice` (`ViewPracticeMeta`)

**`AppState`** top-level fields:
- `macro_views`, `macro_notes`, `asset_views`, `quant_focus`, `quant_focus_next`
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
- **LLM Cache** — `data/briefing_cache.json` keyed by (base URL + model + content hash).
- **Schema Migration** — `persistence.py` `_migrate()` handles old `state.json` gracefully, seeds `topic_views_version`, and migrates legacy asset directions to 1-5 scores.
- **Interview History** — Practice sessions are persisted separately in `data/interview_history.json`.

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
- **Sync triggers** — Sync runs when the My Views tab opens, when the user clicks **Sync Views**, and after saving a View in the app.
- **Sync state** — Lightweight sync metadata (content hashes, `updated_at`, conflict status) is stored in `data/topic_view_sync.json`, not inside the user's Markdown notes.

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `FRED_API_KEY` | Optional | FRED macro indicator data (panel hidden if absent) |
| `OPENROUTER_API_KEY` | Optional | LLM polish generation for TopicViews |
| `OPENROUTER_BASE_URL` | Optional | OpenRouter-compatible endpoint override |
| `OPENROUTER_MODEL` | Optional | Default chat model override |
| `OPENROUTER_POLISH_MODEL` | Optional | Polish-specific model |
| `OPENROUTER_MAX_TOKENS_POLISH` | Optional | Polish token limit |
| `OPENROUTER_TEMPERATURE` | Optional | Sampling temperature |
| `OPENROUTER_HTTP_REFERER` | Optional | OpenRouter HTTP referer header |
| `OPENROUTER_APP_NAME` | Optional | OpenRouter app name header |
| `OBSIDIAN_EXPORT_PATH` | Optional | Override Obsidian export folder |
| `OBSIDIAN_VIEWS_FOLDER` | Optional | Override Obsidian Views folder for bidirectional My Views sync |
| `MQLEDGER_PORT` | Optional | App port (default `8080`) |
| `INTERVIEW_API_KEY` | Optional | API key for interview LLM |
| `INTERVIEW_BASE_URL` | Optional | Interview LLM endpoint |
| `INTERVIEW_MODEL` | Optional | Interview model slug |
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
├── snapshots/
│   └── state_YYYY-MM-DD.json  # One snapshot per calendar day (gitignored)
├── models/
│   └── whisper/            # Downloaded faster-whisper model (gitignored)
└── speech_runtime/
    └── numpy/              # Isolated NumPy runtime for whisper (gitignored)
```

### Deprecated / Removed

- **Bull/Bear icons** — No longer rendered in the UI. The `_BULL_SVG` and `_BEAR_SVG` constants still exist in `app.py` as unused dead code.
- **Subtitle** — "view inventory · quant tracker · reconciliation" removed. Replaced with live clock.
- `ui.add_css()` — **Never use.** Use `ui.add_head_html('<style id="...">...</style>')` instead.
- **`SPEC.md`** — Removed entirely. Any reference to it as authoritative is stale.

### Documentation Notes

- **`CLAUDE.md` is now stale.** It still describes a 6-tab layout, 15 asset views, a hardcoded Obsidian path, and `SPEC.md` as authoritative. Do not trust it for current structure.
- **`check_syntax.py` checks 37 files** (previously 33).
- **Trust actual source code** over any markdown documentation.
