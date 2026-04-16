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
| `app.py` | Entry point, global CSS theming (dark/light), layout, tab routing |
| `models/schema.py` | Pydantic models: `AppState`, `MacroView`, `AssetView`, `QuantTracker`, `Project`, `Skill`, `ReadinessItem`, `Reconciliation`, `BriefingStrip`, `ViewChangeEntry` |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON file at `data/state.json` |
| `storage/fred_client.py` | FRED API client — fetches and transforms macro indicators (requires `FRED_API_KEY` env var) |
| `components/macro_views.py` | 7 fixed macro view cards (expand/collapse, staleness tracking) |
| `components/asset_views.py` | Asset Class Views tab — scored 1–5 across L1, Equities, Fixed Income groups |
| `components/quant_tracker.py` | Dynamic lists for Projects, Skills, Readiness |
| `components/status_bar.py` | Staleness indicators at top of page |
| `components/reconciliation.py` | Weekly reconciliation form + history |
| `components/briefing_strip.py` | "Top of Mind" textarea with staleness tracking |
| `components/view_change_log.py` | Log of direction/conviction changes with timestamps and reasons |
| `components/fred_panel.py` | FRED economic data panel rendered as inline-style HTML tables |
| `export/excel.py` | Excel export (`export/macroquant_ledger_YYYY-MM-DD.xlsx`) |

### Key Design Decisions

- **Fixed vs. dynamic sections:** `MacroView` has exactly 7 items (US Growth, Global Growth, Inflation, Fed Policy Path, Term Premium, Credit, USD). `AssetView` has exactly 13 fixed items across 3 groups (L1, Equities, Fixed Income). Quant tracker sections (Projects, Skills, Readiness) are dynamic.
- **Asset scoring:** Asset views use a 1–5 score system (1=red/lowest, 5=green/highest, `—`=no view) rather than direction/conviction.
- **View change log:** Direction and conviction changes on macro/asset views are recorded with timestamp and optional reason in `AppState.view_change_log`.
- **Staleness logic:** `last_touched` is updated on any field edit. Status bar colors: ≤14d green, 14–28d blue, 28–42d orange, >42d red.
- **Persistence:** No database. Every edit calls `save_state()`. On load failure, defaults are used. Reconciliation history is capped at 52 entries. Daily snapshots are written to `data/snapshots/`.
- **Container-based refresh:** Dynamic sections use a NiceGUI container that is `.clear()`ed and re-rendered to reflect list changes.
- **FRED integration:** Optional — panel only renders if `FRED_API_KEY` is set in the environment.
- **SPEC.md** is the authoritative specification for all features, field names, defaults, and validation rules — consult it before changing behavior.
