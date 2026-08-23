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
```

There are **no automated tests, linters, or CI pipelines**.

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
| `config.py` | OpenRouter defaults — base URL, default model slug, max tokens, temperature; plus `OBSIDIAN_EXPORT_PATH_DEFAULT` and interview fallback notes |
| `models/schema.py` | Pydantic v2 models: `AppState`, `MacroView`, `AssetView`, `Reconciliation`, `BriefingStrip`, `Trade`, plus `TopicView`, `ViewPoint`, `ViewFact`, `ViewPracticeMeta` |
| `models/interview.py` | Interview-practice models: `InterviewSession`, `InterviewQuestion`, `InterviewAnswer`, `InterviewPostmortem`, `InterviewDatabase` |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON persistence; daily snapshots; schema migration |
| `storage/user_settings.py` | `data/user_settings.json` persistence (Obsidian export path) |
| `storage/interview_store.py` | `data/interview_history.json` persistence + performance summary |
| `storage/fred_client.py` | FRED API client — ~50 macro indicators; ETF data via yfinance |
| `storage/trade_prices.py` | yfinance price history — both raw close and adj close per ticker |
| `services/talking_points.py` | Pure synthesis — `macro_prose()`, `fred_snippet()`, `asset_verbal()` |
| `services/llm_polish.py` | OpenRouter chat — briefing generation, polish, and disk cache |
| `services/attribution.py` | View-vs-returns engine — asset benchmark mapping (`ASSET_BENCH`), macro benchmark mapping (`MACRO_BENCH`), score timeline, hit-rate calculation |
| `services/topic_views.py` | TopicView AI helpers — `structure_notes()`, `improve_flow()`, `challenge_view()`, `views_context()` |
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
| `export/obsidian.py` | Obsidian Vault markdown export — YAML frontmatter, callout blocks; destination configurable via Settings |

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
- `counterargument`, `changes_my_mind`
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

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `FRED_API_KEY` | Optional | FRED macro indicator data (panel hidden if absent) |
| `OPENROUTER_API_KEY` | Optional | LLM briefing/polish generation |
| `OPENROUTER_BASE_URL` | Optional | OpenRouter-compatible endpoint override |
| `OPENROUTER_MODEL` | Optional | Default chat model override |
| `OPENROUTER_BRIEFING_MODEL` | Optional | Briefing-specific model |
| `OPENROUTER_POLISH_MODEL` | Optional | Polish-specific model |
| `OPENROUTER_MAX_TOKENS_BRIEFING` | Optional | Briefing token limit |
| `OPENROUTER_MAX_TOKENS_POLISH` | Optional | Polish token limit |
| `OPENROUTER_TEMPERATURE` | Optional | Sampling temperature |
| `OPENROUTER_HTTP_REFERER` | Optional | OpenRouter HTTP referer header |
| `OPENROUTER_APP_NAME` | Optional | OpenRouter app name header |
| `OBSIDIAN_EXPORT_PATH` | Optional | Override Obsidian export folder |
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
├── user_settings.json      # Obsidian export path + app settings (gitignored)
├── interview_history.json  # Interview practice history (gitignored)
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
- **`check_syntax.py` checks 33 files** (previously 18).
- **Trust actual source code** over any markdown documentation.
