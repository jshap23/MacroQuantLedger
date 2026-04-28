# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Always use the **`mqledger` conda environment** for all Python commands:

```bash
conda activate mqledger
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app (serves on http://localhost:8080)
python app.py

# Validate syntax across all core files
python check_syntax.py
```

There are no automated tests, linting, or build steps beyond the above.

## Architecture

**MacroQuantLedger** is a local single-page dashboard for macro-quant research tracking. It uses [NiceGUI](https://nicegui.io/) (Python → Vue.js/Quasar) for the web UI, Pydantic v2 for data models, and JSON for persistence.

### Data Flow

1. User edits a UI field → event handler updates in-memory `AppState`
2. `save_state(state)` serializes to `data/state.json`
3. NiceGUI reactivity updates the UI; toast notification fires

### Module Responsibilities

| Module | Role |
|---|---|
| `app.py` | Entry point, global CSS theming (dark/light), layout, 6-tab routing |
| `config.py` | OpenRouter defaults — base URL, default model slug, max tokens, temperature (overridable via env) |
| `models/schema.py` | Pydantic v2 models: `AppState`, `MacroView`, `AssetView`, `Reconciliation`, `BriefingStrip`, `Trade` |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON at `data/state.json`; daily snapshots to `data/snapshots/`; schema migration |
| `storage/fred_client.py` | FRED API client — 50+ macro indicators with transforms; ETF data via yfinance + Finnhub (optional) |
| `storage/trade_prices.py` | yfinance price history — returns both raw close (price return) and adj close (total return) per ticker |
| `services/talking_points.py` | Pure synthesis — `macro_prose()`, `fred_snippet()`, `asset_verbal()` (no I/O, no UI) |
| `services/llm_polish.py` | OpenRouter (OpenAI-compatible) chat — briefing generation and polish; disk cache keyed by base URL + model + content hash |
| `components/status_bar.py` | Top-of-page staleness indicators (views current, last reconciliation) |
| `components/macro_views.py` | 7 fixed macro view rows — side-drawer editor, conviction bars, direction badges |
| `components/asset_views.py` | Asset Class Views tab — 1–5 score grid (L1 + Equities + Fixed Income) + conviction tenure table |
| `components/briefing_strip.py` | "Top of Mind" textarea with staleness label (lives inside Macro Views tab) |
| `components/briefing.py` | Morning Briefing tab — LLM generation or template fallback, structured context builder |
| `components/reconciliation.py` | Weekly reconciliation form + history log (capped at 52 entries) |
| `components/fred_panel.py` | FRED economic data — grouped HTML tables with click-to-chart (echarts time series) |
| `components/trades.py` | Trade Tracker tab — add/close/delete ETF positions; price return vs. total return columns; footnote |
| `export/excel.py` | Multi-sheet Excel workbook (openpyxl) — macro views, asset views, trades, reconciliations |
| `export/obsidian.py` | Obsidian Vault markdown export — YAML frontmatter, callout blocks, hardcoded to `C:\Users\jshap\JS_Obsidian\MacroQuant` |

### Pydantic Models (`models/schema.py`)

**`MacroView`** — 7 fixed instances:
- `id`: stable key (`growth`, `global_growth`, `inflation`, `fed`, `term_premium`, `credit`, `usd`)
- `name`, `lean`, `signals: list[str]` (always 3), `counter`
- `direction`: `"Bullish"` | `"Neutral"` | `"Bearish"` | `"No View"`
- `conviction`: `"High"` | `"Medium"` | `"Low"` | `"—"`
- `last_touched: Optional[datetime]`

**`AssetView`** — 15 fixed instances across 3 groups:
- `id`, `name`, `group` (`"l1"` | `"equities"` | `"fixed_income"`)
- `direction`: score string `"—"` | `"1"` | `"2"` | `"3"` | `"4"` | `"5"` (not a direction enum)
- `note`, `last_touched: Optional[datetime]`

**`Reconciliation`**: `id` (UUID), `date`, `macro_scan`, `quant_check`, `time_macro/quant/other` (int %, must sum to 100), `synthesis`

**`BriefingStrip`**: `top_of_mind: str`, `top_of_mind_touched: Optional[datetime]`

**`Trade`**: `id` (UUID), `ticker`, `entry_date` (YYYY-MM-DD), `exit_date` (None = open), `size: Optional[float]` ($ notional), `note`, `created_at`

**`AppState`** (top-level):
- `macro_views`, `macro_notes`, `asset_views`, `quant_focus`, `quant_focus_next`
- `reconciliations` (capped at 52), `briefing: BriefingStrip`, `trades: list[Trade]`

### Key Design Decisions

- **Fixed sections:** `MacroView` has exactly 7 items; `AssetView` has exactly 15 items (1 L1 + 7 Equities + 7 Fixed Income). There are no dynamic add/remove lists.
- **Asset scoring:** `AssetView.direction` stores a 1–5 score string, not a direction. `"—"` = no view, `"1"` = strong underweight, `"5"` = strong overweight.
- **Trade total return:** `trade_prices.py` fetches with `auto_adjust=False` to get both `"Close"` (price return) and `"Adj Close"` (total return including dividends). Both columns are shown in the UI. P&L uses total return. Especially meaningful for bond ETFs.
- **Staleness logic:** `last_touched` updated on every field edit. Status bar colors: ≤14d green, ≤28d amber, ≤42d orange, >42d red.
- **Conviction tenure:** `asset_views.py` loads daily snapshots to calculate how long each asset score has been held; displayed in the tenure table.
- **Persistence:** No database. Every edit calls `save_state()`. Load failure falls back to `default_state()`. Daily snapshots written to `data/snapshots/state_YYYY-MM-DD.json`.
- **Container-based refresh:** Sections that change dynamically (e.g., trades, reconciliation history) use a NiceGUI container `.clear()`ed and re-rendered.
- **LLM briefing:** `services/llm_polish.py` calls OpenRouter’s Chat Completions API (`openai` SDK with `base_url` set to OpenRouter). Model and tuning come from `config.py` and `OPENROUTER_*` env vars. Results cached in `data/briefing_cache.json` (hash includes API base URL and model id so switching models does not reuse stale entries). Cache is checked before any API call.
- **FRED integration:** Optional — panel only renders if `FRED_API_KEY` is set. `FINNHUB_API_KEY` optional for real-time ETF quotes. `OPENROUTER_API_KEY` optional for AI briefing generation on the Briefing tab.
- **Schema migration:** `persistence.py` `_migrate()` handles old `state.json` gracefully — seeds missing asset views, resets invalid enum values.
- **SPEC.md** is the authoritative specification for all features, field names, defaults, and validation rules — consult it before changing behavior.

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `FRED_API_KEY` | Optional | FRED macro indicator data (panel hidden if absent) |
| `FINNHUB_API_KEY` | Optional | Real-time ETF quotes in FRED panel |
| `OPENROUTER_API_KEY` | Optional | LLM briefing generation (OpenRouter) on Briefing tab |
| `OPENROUTER_BASE_URL` | Optional | API base URL (default `https://openrouter.ai/api/v1`) |
| `OPENROUTER_MODEL` | Optional | Default OpenRouter model slug for all LLM calls |
| `OPENROUTER_BRIEFING_MODEL` | Optional | Override model for full briefing only |
| `OPENROUTER_POLISH_MODEL` | Optional | Override model for polish only |
| `OPENROUTER_HTTP_REFERER` | Optional | `HTTP-Referer` header for OpenRouter rankings |
| `OPENROUTER_APP_NAME` | Optional | `X-Title` header (default `MacroQuantLedger`) |
| `OPENROUTER_MAX_TOKENS_BRIEFING` | Optional | Max completion tokens for briefing (default from `config.py`) |
| `OPENROUTER_MAX_TOKENS_POLISH` | Optional | Max completion tokens for polish (default from `config.py`) |
| `OPENROUTER_TEMPERATURE` | Optional | Sampling temperature (default from `config.py`) |

### Data Directory

```
data/
├── state.json              # Current app state (gitignored)
├── briefing_cache.json     # LLM response cache (keys include base URL + model + content hash; gitignored)
└── snapshots/
    └── state_YYYY-MM-DD.json  # One snapshot per calendar day (gitignored)
```
