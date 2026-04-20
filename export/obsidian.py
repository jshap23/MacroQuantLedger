from __future__ import annotations
from datetime import datetime
from pathlib import Path
from models.schema import AppState

VAULT_PATH = Path(r"C:\Users\jshap\JS_Obsidian\MacroQuant")

# Macro view id → YAML frontmatter key
_ID_TO_KEY = {
    "growth":       "us_growth",
    "global_growth":"global_growth",
    "inflation":    "inflation",
    "fed":          "fed_policy",
    "term_premium": "term_premium",
    "credit":       "credit",
    "usd":          "usd",
}

_CALLOUT = {
    "Bullish": "success",
    "Bearish": "danger",
    "Neutral": "note",
    "No View": "abstract",
}

_SCORE_LABEL = {
    "5": "5 ▲▲",
    "4": "4 ▲",
    "3": "3 —",
    "2": "2 ▼",
    "1": "1 ▼▼",
    "—": "—",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt)


def _pipe_safe(s: str) -> str:
    """Escape pipe characters so they don't break markdown tables."""
    return s.replace("|", "\\|") if s else ""


# ── Sections ───────────────────────────────────────────────────────────────────

def _frontmatter(state: AppState, date_str: str) -> str:
    lines = [
        "---",
        "tags: [macroquant/snapshot]",
        f"date: {date_str}",
    ]

    for mv in state.macro_views:
        key = _ID_TO_KEY.get(mv.id)
        if key:
            lines.append(f"{key}: {mv.direction}")

    high_conviction = [mv.name for mv in state.macro_views if mv.conviction == "High"]
    if high_conviction:
        lines.append("top_conviction:")
        for name in high_conviction:
            lines.append(f"  - \"{name}\"")
    else:
        lines.append("top_conviction: []")

    lines.append("---")
    return "\n".join(lines)


def _top_of_mind(state: AppState) -> str:
    tom = state.briefing.top_of_mind if state.briefing else ""
    if not tom or not tom.strip():
        return ""
    lines = ["## Top of Mind", ""]
    lines.append(tom.strip())
    lines.append("")
    return "\n".join(lines)


def _macro_views(state: AppState) -> str:
    lines = ["## Macro Views", ""]

    for mv in state.macro_views:
        callout = _CALLOUT.get(mv.direction, "abstract")
        conviction = mv.conviction if mv.conviction not in ("—", "") else "—"
        lines.append(f"> [!{callout}] {mv.name} — {mv.direction} · {conviction}")

        if mv.lean and mv.lean.strip():
            lines.append(f"> **Lean:** {mv.lean.strip()}")

        signals = [s.strip() for s in mv.signals if s.strip()]
        if signals:
            lines.append(f"> **Signals:** {'  ·  '.join(signals)}")

        if mv.counter and mv.counter.strip():
            lines.append(f"> **Counter:** {mv.counter.strip()}")

        lines.append("")  # blank line ends the callout

    if state.macro_notes and state.macro_notes.strip():
        lines.append(f"> [!quote] Cross-Cutting Notes")
        lines.append(f"> {state.macro_notes.strip()}")
        lines.append("")

    return "\n".join(lines)


def _asset_views(state: AppState) -> str:
    lines = ["## Asset Class Views", ""]

    groups = [
        ("l1",           "Level 1 — Cross-Asset"),
        ("equities",     "Equities"),
        ("fixed_income", "Fixed Income"),
    ]

    for group_key, group_label in groups:
        views = [v for v in state.asset_views if v.group == group_key]
        if not views:
            continue

        lines.append(f"### {group_label}")
        lines.append("")
        lines.append("| Asset | Score | Thesis | Commentary |")
        lines.append("|-------|-------|--------|------------|")

        for av in views:
            score  = _SCORE_LABEL.get(av.direction, av.direction)
            thesis = _pipe_safe(av.note)
            commentary = _pipe_safe(av.commentary)
            lines.append(f"| {av.name} | {score} | {thesis} | {commentary} |")

        lines.append("")

    return "\n".join(lines)


def _change_log(state: AppState) -> str:
    recent = [e for e in state.view_change_log[:10]]
    if not recent:
        return ""

    lines = ["## Recent View Changes", ""]
    lines.append("| Date | View | Field | Change | Reason |")
    lines.append("|------|------|-------|--------|--------|")

    for entry in recent:
        ts     = _fmt_dt(entry.timestamp)
        change = f"{entry.old_value} → **{entry.new_value}**"
        reason = _pipe_safe(entry.reason) if entry.reason else ""
        lines.append(f"| {ts} | {entry.view_name} | {entry.field} | {change} | {reason} |")

    lines.append("")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_obsidian_note(state: AppState) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")

    body_parts = [
        _frontmatter(state, date_str),
        "",
        f"# MacroQuant Ledger — {date_str}",
        "",
    ]

    tom = _top_of_mind(state)
    if tom:
        body_parts += [tom, "---", ""]

    body_parts += [_macro_views(state), "---", ""]
    body_parts += [_asset_views(state), "---", ""]

    log = _change_log(state)
    if log:
        body_parts.append(log)

    content = "\n".join(body_parts)

    VAULT_PATH.mkdir(parents=True, exist_ok=True)
    out_path = VAULT_PATH / f"{date_str}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path
