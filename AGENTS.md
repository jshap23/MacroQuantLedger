# AGENTS.md

This file provides guidance to **OpenCode** when working with code in this repository.

## Environment

Always use the **`mqledger` conda environment** for all Python commands. On Windows the launcher uses **miniforge3**:

```bash
conda activate mqledger
```

## Commands

```bash
# Run the app (serves on http://localhost:8080)
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
- `mq-attribution-css` (components/attribution.py)
- `mq-briefing-css` (components/briefing.py)
- `mq-macro-views-css` (components/macro_views.py)

## Architecture

**MacroQuantLedger** is a local single-page dashboard for macro-quant research tracking. It uses [NiceGUI](https://nicegui.io/) (Python → Vue.js/Quasar) for the web UI, Pydantic v2 for data models, and JSON for persistence.

### Tabs (7 total)

1. **Macro Views** — 7 fixed macro themes with direction badges and conviction bars
2. **Asset Class Views** — 13 asset scores (1-5) with tenure tracking
3. **Briefing** — LLM-generated morning brief or template view
4. **Weekly Reconciliation** — Time allocation and synthesis log
5. **Economic Data** — FRED indicators with charts (requires `FRED_API_KEY`)
6. **Trades** — ETF position tracker with P&L
7. **Attribution** — **NEW** View-vs-returns analysis with echarts

### Data Flow

1. User edits a UI field → event handler updates in-memory `AppState`
2. `save_state(state)` serializes to `data/state.json`
3. NiceGUI reactivity updates the UI; toast notification fires
4. Daily snapshots saved to `data/snapshots/state_YYYY-MM-DD.json`

### Module Responsibilities

| Module | Role |
|---|---|
| `app.py` | Entry point, **MQ monogram header**, global CSS theming (dark/light), 7-tab routing |
| `config.py` | OpenRouter defaults — base URL, default model slug, max tokens, temperature |
| `models/schema.py` | Pydantic v2 models: `AppState`, `MacroView`, `AssetView`, `Reconciliation`, `BriefingStrip`, `Trade` |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON persistence; daily snapshots; schema migration |
| `storage/fred_client.py` | FRED API client — 50+ macro indicators; ETF data via yfinance + Finnhub (optional) |
| `storage/trade_prices.py` | yfinance price history — both raw close and adj close per ticker |
| `services/talking_points.py` | Pure synthesis — `macro_prose()`, `fred_snippet()` |
| `services/llm_polish.py` | OpenRouter chat — briefing generation with disk cache |
| `services/attribution.py` | **NEW** View-vs-returns engine — benchmark mapping, score timeline, hit rate calculation |
| `components/status_bar.py` | **7 dots** staleness indicator (replaced "5/7" text), live reconciliation label |
| `components/macro_views.py` | 7 fixed macro view rows — side-drawer editor, conviction bars, direction badges |
| `components/asset_views.py` | Asset Class Views tab — score grid + conviction tenure table |
| `components/briefing_strip.py` | "Top of Mind" textarea (lives inside Macro Views tab) |
| `components/briefing.py` | Morning Briefing tab — LLM generation or template fallback |
| `components/reconciliation.py` | Weekly reconciliation form + history log (capped at 52) |
| `components/fred_panel.py` | FRED economic data — HTML tables with click-to-chart (echarts) |
| `components/trades.py` | Trade Tracker tab — add/close/delete ETF positions |
| `components/attribution.py` | **NEW** Attribution tab — echarts timeline, score analysis, streak badges |
| `export/excel.py` | Multi-sheet Excel workbook — macro views, asset views, trades, reconciliations |
| `export/obsidian.py` | Obsidian Vault markdown export — YAML frontmatter, callout blocks |

### Header Visual Design (Current)

- **MQ Monogram** — Large gradient "MQ" logo (teal-to-green), staggered positioning
- **Title** — "MACROQUANT LEDGER" beside monogram
- **Live Clock** — Date + time below title, updates every 10s
- **Live Dot** — Pulsing green indicator showing app is active
- **Gradient Line** — Fading teal accent line under header
- **Status Bar** — 7 colored dots showing view freshness + reconciliation age

### Pydantic Models

**`MacroView`** — 7 fixed instances:
- `id`: stable key (`growth`, `global_growth`, `inflation`, `fed`, `term_premium`, `credit`, `usd`)
- `direction`: `"Bullish"` | `"Neutral"` | `"Bearish"` | `"No View"`
- `conviction`: `"High"` | `"Medium"` | `"Low"` | `"—"`

**`AssetView`** — 13 fixed instances (1 L1 + 7 Equities + 5 Fixed Income):
- `direction`: score `"—"` | `"1"` | `"2"` | `"3"` | `"4"` | `"5"`
- `"5"` = strong overweight, `"1"` = strong underweight

**`Trade`** — ETF positions:
- `ticker`, `entry_date`, `exit_date` (None = open), `size` ($ notional), `note`
- Price and total return fetched via yfinance

### Key Design Decisions

- **Fixed sections** — No dynamic add/remove. Exactly 7 macro views, 13 asset views.
- **Asset scoring** — 1-5 score strings, not direction enums. Direction badge colors calculated from score.
- **Trade returns** — Uses adjusted close (includes dividends) for P&L. Critical for bond ETFs.
- **Staleness** — `last_touched` on every edit. Status dots: ≤14d green, ≤28d amber, ≤42d orange, >42d red.
- **Attribution** — Benchmark mapping (`ASSET_BENCH`) links asset views to ETFs. Timeline walks daily snapshots to find score change dates. Echarts shows price + score overlay.
- **Persistence** — JSON only. No database. Every edit calls `save_state()`.
- **Snapshots** — One per calendar day at `data/snapshots/`. Used for conviction tenure calculation.
- **LLM Cache** — `data/briefing_cache.json` keyed by (base URL + model + content hash).
- **Schema Migration** — `persistence.py` `_migrate()` handles old `state.json` gracefully.

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `FRED_API_KEY` | Optional | FRED macro indicator data (panel hidden if absent) |
| `FINNHUB_API_KEY` | Optional | Real-time ETF quotes in FRED panel |
| `OPENROUTER_API_KEY` | Optional | LLM briefing generation on Briefing tab |
| `OPENROUTER_*` | Optional | Various overrides (model, tokens, temperature, etc.) |

### Data Directory

```
data/
├── state.json              # Current app state (gitignored)
├── briefing_cache.json     # LLM response cache (gitignored)
└── snapshots/
    └── state_YYYY-MM-DD.json  # One snapshot per calendar day (gitignored)
```

### Deprecated / Removed

- **Bull/Bear icons** — Removed after multiple failed SVG iterations. Replaced with MQ monogram.
- **Subtitle** — "view inventory · quant tracker · reconciliation" removed. Replaced with live clock.
- `ui.add_css()` — **Never use.** Use `ui.add_head_html('<style id="...">...</style>')` instead.

### Documentation Notes

- **`SPEC.md` is stale.** Ignore it. Describes old 3-tab architecture.
- **`check_syntax.py` checks 18 files** (was incomplete at 7 files previously).
- **Trust `CLAUDE.md` and actual source code** over any markdown documentation.
