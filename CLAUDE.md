# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (use conda env `mqledger`)
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
| `models/schema.py` | Pydantic models: `AppState`, `MacroView`, `QuantTracker`, `Project`, `Skill`, `ReadinessItem`, `Reconciliation` |
| `storage/persistence.py` | `load_state()` / `save_state()` — JSON file at `data/state.json` |
| `components/macro_views.py` | 7 fixed macro view cards (expand/collapse, staleness tracking) |
| `components/quant_tracker.py` | Dynamic lists for Projects, Skills, Readiness |
| `components/status_bar.py` | Staleness indicators at top of page |
| `components/reconciliation.py` | Weekly reconciliation form + history |
| `export/excel.py` | Excel export (`data/macroquant_ledger_YYYY-MM-DD.xlsx`) |

### Key Design Decisions

- **Fixed vs. dynamic sections:** `MacroView` has exactly 7 items (Growth, Global Growth, Inflation, Fed, Term Premium, USD, Credit). Quant tracker sections (Projects, Skills, Readiness) are dynamic.
- **Staleness logic:** `last_touched` is updated on any field edit. Status bar colors: ≤14d green, 14–28d blue, 28–42d orange, >42d red.
- **Persistence:** No database. Every edit calls `save_state()`. On load failure, defaults are used. Reconciliation history is capped at 52 entries.
- **Container-based refresh:** Dynamic sections use a NiceGUI container that is `.clear()`ed and re-rendered to reflect list changes.
- **SPEC.md** is the authoritative specification for all features, field names, defaults, and validation rules — consult it before changing behavior.
