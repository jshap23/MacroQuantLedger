# MacroQuant Ledger — Project Specification

## Overview

A local-only personal dashboard for a macro-quant research analyst to maintain an inventory of macro views, track quantitative skill development, and perform weekly self-reconciliation. Runs on localhost via NiceGUI. Not a public website — a personal productivity tool launched from the terminal.

## Stack

- **Framework**: NiceGUI (Python)
- **Data persistence**: JSON file on disk (`data/state.json`)
- **Data modeling**: Pydantic v2
- **Excel export**: openpyxl
- **Python**: 3.10+
- **Launch**: `python app.py` → opens browser at `http://localhost:8080`

## Project Structure

```
macroquant-ledger/
├── app.py                  # Entry point — NiceGUI app, tab routing, layout
├── requirements.txt        # nicegui, pydantic, openpyxl
├── README.md               # Setup: pip install -r requirements.txt → python app.py
│
├── models/
│   ├── __init__.py
│   └── schema.py           # Pydantic models for all data structures
│
├── storage/
│   ├── __init__.py
│   └── persistence.py      # Read/write state.json, auto-create from defaults
│
├── components/
│   ├── __init__.py
│   ├── status_bar.py       # Top-level staleness indicators
│   ├── macro_views.py      # Macro view cards with expand/collapse
│   ├── quant_tracker.py    # Projects, skills, readiness — dynamic add/remove
│   └── reconciliation.py   # Weekly form + history log
│
├── export/
│   ├── __init__.py
│   └── excel.py            # Generate formatted .xlsx from current state
│
└── data/
    └── .gitkeep            # state.json created automatically on first run
```

## Data Model (models/schema.py)

Use Pydantic BaseModel for all structures. The top-level model is `AppState`.

```
AppState
├── macro_views: list[MacroView]       # exactly 7 items
├── macro_notes: str                   # free text
├── quant_tracker: QuantTracker
├── reconciliations: list[Reconciliation]  # most recent first, cap at 52
```

### MacroView
| Field      | Type         | Default     | Notes |
|------------|--------------|-------------|-------|
| id         | str          | required    | Stable identifier (e.g. "growth", "fed") |
| name       | str          | required    | Display name, editable by user |
| lean       | str          | ""          | One sentence directional lean |
| signals    | list[str]    | ["","",""]  | Exactly 3 supporting signals |
| counter    | str          | ""          | Best argument against the view |
| conviction | str          | "No View"   | One of: "High", "Medium", "Low", "No View" |
| flag       | str          | "green"     | One of: "green", "yellow", "red" |
| last_touched | datetime or None | None  | Auto-set when any field changes |

Default macro views (7 total):
1. Growth Trajectory
2. Global Growth
3. Inflation Dynamics
4. Fed Policy Path
5. Term Premium
6. USD
7. Credit

These names are editable. The set of 7 views is fixed (no add/remove on macro views — just the Notes section for overflow).

### QuantTracker
```
QuantTracker
├── projects: list[Project]
├── skills: list[Skill]
├── readiness: list[ReadinessItem]
```

All three lists are dynamic — user can add and remove items freely.

#### Project
| Field      | Type         | Default |
|------------|--------------|---------|
| id         | str          | uuid    |
| name       | str          | ""      |
| status     | str          | ""      |
| next_step  | str          | ""      |
| priority   | str          | "—"     | One of: "—", "High", "Medium", "Low" |
| last_touched | datetime or None | None |

#### Skill
| Field              | Type  | Default |
|--------------------|-------|---------|
| id                 | str   | uuid    |
| name               | str   | ""      |
| level              | str   | "—"     | One of: "—", "Beginner", "Working", "Strong" |
| building           | str   | ""      | What they're doing to develop this skill |
| interview_relevance| str   | "—"     | One of: "—", "High", "Medium", "Low" |
| last_touched       | datetime or None | None |

#### ReadinessItem
| Field      | Type  | Default |
|------------|-------|---------|
| id         | str   | uuid    |
| area       | str   | ""      | Topic area (user-defined) |
| strength   | str   | ""      | One of: "", "Strength", "Gap", "Mixed" |
| evidence   | str   | ""      | Can you demo this? |
| action     | str   | ""      | Action this week |
| last_touched | datetime or None | None |

### Reconciliation
| Field           | Type  |
|-----------------|-------|
| id              | str   |
| date            | datetime |
| macro_scan      | str   |
| quant_check     | str   |
| time_macro      | int   | Percentage |
| time_quant      | int   |
| time_other      | int   |
| synthesis       | str   |

Start each section with one blank item. Never pre-populate field values with examples — leave them empty. Placeholder text in the UI is fine.

## Persistence Layer (storage/persistence.py)

- On startup, check if `data/state.json` exists
- If not, create it from default AppState (7 macro views, one blank item per quant section, empty reconciliations)
- `load_state() -> AppState`: read and parse the JSON file
- `save_state(state: AppState)`: write to JSON file
- Save should be called on every meaningful user edit (field blur or dropdown change)
- All timestamps are ISO 8601 strings in the JSON

## UI Layout (app.py)

### Header
- Title: "MACROQUANT LEDGER" 
- Subtitle: "view inventory · quant tracker · reconciliation"
- Two buttons in top right: "Export Excel" (prominent) and "Reset" (subdued, with confirmation dialog)

### Status Bar
Three indicators displayed horizontally below the header:
- **STALE VIEWS**: count of macro views where last_touched is null or > 14 days ago. Show as "X/7". Color: green (0), yellow (1-2), red (3+).
- **QUANT TRACKER**: staleness of most recently touched item across all three quant sections. Color based on days since last touch.
- **LAST RECONCILIATION**: days since most recent reconciliation entry. Green ≤7d, yellow 8-10d, red >10d or never.

Staleness color logic (used everywhere):
- ≤ 14 days: green
- 14-28 days: yellow/amber
- 28-42 days: orange
- > 42 days or never: red

### Tabs
Three tabs: **Macro Views** | **Quant Development** | **Weekly Reconciliation**

## Tab 1: Macro Views (components/macro_views.py)

Display 7 macro view cards in a vertical list. Each card has:

**Collapsed state** (default):
- Left: Variable name (bold) + conviction badge (colored: High=green, Medium=yellow, Low=orange, No View=gray) + consistency flag dot (green/yellow/red circle)
- Right: Staleness label (e.g. "3d ago", "never updated") colored by staleness + expand arrow
- If the view has a directional lean, show it as a preview line below the header in italic gray

**Expanded state** (click header to toggle):
- VARIABLE NAME: text input (editable name)
- DIRECTIONAL LEAN: textarea. Placeholder: "One sentence — direction, magnitude, where uncertainty sits…"
- THREE SUPPORTING SIGNALS: three text inputs, numbered 1-2-3. Placeholder: "Data point, model output, or market behavior…"
- THE COUNTER: textarea. Placeholder: "Best argument against your own view…"
- CONVICTION: dropdown (High / Medium / Low / No View)
- CONSISTENCY FLAG: dropdown (Coherent / Tension / Inconsistent) — maps to green/yellow/red

Any edit to any field should update `last_touched` to now and trigger a save.

**Below the 7 cards**: A Notes section with a section header "NOTES" and a large textarea. Placeholder: "Cross-cutting themes, half-formed ideas, anything that doesn't fit neatly into a single variable…"

## Tab 2: Quant Development (components/quant_tracker.py)

Three sections, each with a gold/accent section header and a dynamic list of cards.

### Section: ACTIVE RESEARCH PROJECTS
Each project card shows:
- Row 1: PROJECT (text input, flex), PRIORITY (dropdown: —/High/Medium/Low), TOUCHED (staleness label), ✕ remove button
- Row 2: CURRENT STATUS (textarea). Placeholder: "What's working, what's stuck…"
- Row 3: NEXT STEP (text input). Placeholder: "Next concrete deliverable…"

Below all project cards: "+ Add project" button (dashed border, full width)

### Section: TECHNICAL SKILLS INVENTORY
Each skill card shows:
- Row 1: SKILL / METHOD (text input, flex), LEVEL (dropdown: —/Beginner/Working/Strong), INTERVIEW RELEVANCE (dropdown: —/High/Medium/Low), ✕ remove button
- Row 2: WHAT YOU'RE DOING TO BUILD IT (text input). Placeholder: "Paper, codebase, course…"

Below: "+ Add skill" button

### Section: INTERVIEW READINESS
Each readiness card shows:
- Row 1: TOPIC AREA (text input, flex), STRENGTH OR GAP? (dropdown: —/Strength/Gap/Mixed), TOUCHED (staleness label), ✕ remove button
- Row 2: EVIDENCE — CAN YOU DEMO THIS? (text input, flex) + ACTION THIS WEEK (text input, flex)

Below: "+ Add topic" button

All add/remove operations save immediately. Remove should work on any item — no minimum count enforced (if they remove everything, the section is empty with just the add button).

## Tab 3: Weekly Reconciliation (components/reconciliation.py)

### Entry form
Hidden by default. Show a "+ Start Weekly Reconciliation" button. When clicked, display a form card:

- Title: "Weekly Reconciliation — Mar 17, 2026" (current date)
- MACRO INVENTORY SCAN: textarea. Placeholder: "What changed? What's stale? What should have changed but didn't?"
- QUANT DEVELOPMENT CHECK: textarea. Placeholder: "Did you build or code anything? Or just consume?"
- TIME ALLOCATION (% of discretionary hours): three number inputs side by side — Macro, Quant Dev, Other. Default: 33/33/34. Show warning if total ≠ 100%.
- SYNTHESIS — ONE SENTENCE: textarea. Placeholder: "One sentence: the tape + your positioning…"
- Submit button + Cancel button

On submit: create a Reconciliation entry, prepend to the list (most recent first), cap at 52 entries, save, close the form.

### History
Below the form button, display all past reconciliation entries as cards:
- Header: date (formatted like "Mon, Mar 17") + ✕ delete button
- Synthesis sentence in italic (if present)
- Time allocation: "Macro 40% · Quant 35% · Other 25%"
- Macro scan text (if present)
- Quant check text (if present)

## Excel Export (export/excel.py)

Triggered by the "Export Excel" button in the header. Generates a formatted .xlsx file using openpyxl and triggers a browser download. Filename: `macroquant_ledger_YYYY-MM-DD.xlsx`

### Formatting
- Clean, light professional theme: white background, warm cream alternating rows
- Navy blue column headers with white text
- Dark gold accent on sheet titles
- Calibri font throughout
- Frozen header rows

### Sheet 1: Macro Views
Columns: Variable | Directional Lean | Signal 1 | Signal 2 | Signal 3 | The Counter | Conviction | Flag | Last Touched

Populate from current state. Below the data rows, include a Notes section if macro_notes is non-empty.

### Sheet 2: Implication Map
Columns: Macro Variable | Duration/Rates | Credit | Equities | Vol (Rates+Eq) | FX/USD | Commodities

Pre-populate the variable names from current state. Implication cells are empty — this is a worksheet for manual use.

### Sheet 3: Quant Tracker
Three sub-tables with section headers:
- ACTIVE RESEARCH PROJECTS: Project | Current Status | Next Step | Priority | Last Touched
- TECHNICAL SKILLS INVENTORY: Skill/Method | Level | Building | Interview Relevance | Last Touched
- INTERVIEW READINESS: Topic Area | Strength/Gap | Evidence | Action This Week | Last Touched

All populated from current state.

### Sheet 4: Reconciliation
Columns: Week Of | Macro Scan | Quant Check | % Macro | % Quant | % Other | Synthesis

Populated from reconciliation history, most recent first.

## Visual Design

Dark theme, terminal-influenced but not a terminal. Professional, information-dense.

- Background: very dark gray (#111114)
- Card backgrounds: slightly lighter (#18181c)
- Text: light gray (#e0e0e0)
- Accent: dark gold (#c9a84c) for titles, active tab, section headers
- Borders: subtle (#222, #2a2a2e)
- Inputs/textareas: dark background (#111114) with subtle border, light text
- Font: IBM Plex Mono for the monospace feel (import from Google Fonts or use system monospace as fallback)

NiceGUI supports custom CSS. Use `ui.add_head_html()` or `ui.add_css()` to inject the dark theme globally. NiceGUI's default Quasar components can be styled with `.props()` and CSS classes.

NiceGUI dark mode: use `ui.dark_mode(True)` as a starting point, then override with custom CSS for the specific palette above.

## Behavior Notes

- Auto-save: every field change should persist. Use NiceGUI's `on_change` or `on_blur` events. Debounce if needed for text fields (save on blur rather than every keystroke).
- Show a brief "✓ saved" indicator near the header after each save, auto-dismiss after 1.5s.
- Reset button: confirmation dialog ("Reset all data? This cannot be undone."), then replace state.json with defaults.
- The app is single-user, local-only. No auth, no sessions, no deployment concerns.
- NiceGUI's `app.on_startup` is a good place to ensure the data directory and state file exist.

## Launch

```bash
pip install -r requirements.txt
python app.py
```

`app.py` should end with:
```python
ui.run(title="MacroQuant Ledger", port=8080, reload=False)
```

This opens the browser automatically. Set `reload=False` for production feel (set to `True` during development).

## Requirements

```
nicegui>=1.4
pydantic>=2.0
openpyxl>=3.1
```
