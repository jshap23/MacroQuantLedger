"""Flip-through deck for My Views: recall, confirm, quick-edit, or rehearse one View at a time.

Also owns the small shared pieces the My Views cards reuse: level pips, the
freshness stripe, the "Still holds" confirmation, and the saved recall rating.
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, timezone

from nicegui import background_tasks, run, ui

from components.interview_practice import _sync_view_metadata
from components.undo_toast import show_undo
from components.interview_speech import (
    cancel_recording,
    start_recording,
    stop_recording,
    transcribe_recording,
)
from models.schema import AppState, TopicView, ViewFact
from services.interview_controller import (
    band_visible,
    evaluate_answer,
    session_band,
    start_session,
    synthesize_session,
)
from services.interview_llm import (
    InterviewOutputError,
    InterviewProviderError,
    available as llm_available,
    grader_model,
)
from services.interview_prompts import get_preset
from services.interview_speech import speech_bias_context, speech_runtime_available
from services.topic_views import RECALL_RATINGS, split_point, views_context
from services.view_progress import (
    activity_dates,
    is_personal_best,
    note_activity,
    weekly_streak,
)
from services.view_levels import (
    MAX_LEVEL,
    ViewLevel,
    days_since_confirmed,
    freshness_ratio,
    view_level,
)
from storage.interview_store import load_database, preferred_model

_log = logging.getLogger(__name__)

_FRESH_RGB = (45, 212, 191)
_STALE_RGB = (100, 116, 139)

_ORDERS = {"listed": "As listed", "stale": "Stalest first", "shuffle": "Shuffle"}
_MODES = {"recall": "Recall", "read": "Read"}
_RATING_UI = (
    ("Nailed", "Nailed it", "positive", "1"),
    ("Shaky", "Shaky", "warning", "2"),
    ("Blanked", "Blanked", "negative", "3"),
)


def inject_deck_css() -> None:
    ui.add_head_html("""<style id="mq-view-deck-css">
      .q-panel:has(.vd-shell),.q-panel-parent:has(.vd-shell){overflow:visible!important}
      .vd-shell{width:100%;max-width:820px;margin:0 auto}
      .vd-card{background:var(--bg-card);border:1px solid var(--border-strong);border-left:4px solid var(--vd-fresh,var(--accent));border-radius:7px;padding:1.2rem 1.35rem;width:100%}
      .vd-name{font-weight:700;font-size:1.3rem;color:var(--text-primary)}
      .vd-prompt{font-weight:600;font-size:1.15rem;color:var(--text-primary);margin:1.2rem 0 .3rem}
      .vd-md,.vd-md p,.vd-md li{color:var(--text-primary)}
      .vd-bottom{font-size:1.02rem;line-height:1.6;margin:.7rem 0 .9rem}
      .vd-bottom p{margin:0 0 .6rem}
      .vd-point{margin:.55rem 0}.vd-point-title{font-weight:600;font-size:.92rem;line-height:1.45;color:var(--text-primary)}
      .vd-more{margin-left:1.1rem}
      .vd-more .q-item{min-height:26px!important;padding:0 .2rem!important;font:600 .66rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .vd-more-body{font-size:.84rem;line-height:1.55;color:var(--text-muted);padding:.1rem .2rem .4rem}
      .vd-more-body p{margin:0 0 .4rem;color:var(--text-muted)}
      .vd-fact{font-size:.8rem;line-height:1.5;color:var(--text-muted)}
      .vd-ctrl{position:sticky;top:0;z-index:20;background:var(--bg-card);margin:.85rem 0 .3rem;padding:.5rem 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
      .vd-row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
      .vd-rate-label{font:600 .66rem 'IBM Plex Mono',monospace;color:var(--text-muted);margin-right:.2rem}
      .vd-kbd{display:inline-block;margin-left:.45rem;padding:0 .3rem;border:1px solid var(--border-strong);border-radius:3px;font:600 .58rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .submit-btn .vd-kbd{color:inherit;border-color:currentColor;opacity:.75}
      .vd-panel{margin-top:1rem;padding:.9rem 1rem;background:var(--bg-input);border:1px solid var(--border);border-radius:6px}
      .vd-question{font-weight:600;font-size:.95rem;color:var(--text-primary);margin:.35rem 0 .5rem}
      .vd-band{font-weight:600;font-size:.95rem;color:var(--text-primary);line-height:1.5}
      .vd-fb{font-size:.88rem;line-height:1.55;color:var(--text-primary);margin-top:.5rem}
      .vd-levelup{font:700 .72rem 'IBM Plex Mono',monospace;color:#34d399;margin-top:.5rem}
      body.light-mode .vd-levelup{color:#15803d}
      .vd-pips{display:inline-flex;gap:3px;align-items:center}
      .vd-pip{width:9px;height:9px;border-radius:2px;background:var(--border-strong)}
      .vd-pip.on{background:var(--accent)}
      .vd-level{display:inline-flex;gap:.4rem;align-items:center;font:600 .62rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .vd-count{font:600 .72rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .vd-order .q-btn{min-height:28px!important;text-transform:none!important;font:600 .66rem 'IBM Plex Mono',monospace!important}
      .vd-order .q-btn{color:var(--text-muted)!important;background:var(--bg-input)!important;border:1px solid var(--border)}
      .vd-order .q-btn .q-btn__content{color:inherit!important}
      .vd-order .q-btn.bg-primary{color:#1a1a1a!important;background:#f59e0b!important;border-color:#f59e0b}
      body.light-mode .vd-order .q-btn.bg-primary{color:#ffffff!important;background:#b45309!important;border-color:#b45309}
      .vd-keys{font:500 .62rem 'IBM Plex Mono',monospace;color:var(--text-faint);text-align:center;margin-top:.7rem}
      .vd-summary-line{font:600 .85rem 'IBM Plex Mono',monospace;color:var(--text-primary);line-height:1.7;margin:.6rem 0 1rem}
    </style>""")


# ── Shared card pieces ───────────────────────────────────────────────────────


def freshness_color(view: TopicView) -> str:
    """Teal while fresh, fading toward slate as the View ages past its cadence."""
    ratio = freshness_ratio(view)
    fade = min(1.0, max(0.0, (ratio - 0.5) / 1.5))
    r, g, b = (round(a + (c - a) * fade) for a, c in zip(_FRESH_RGB, _STALE_RGB))
    return f"rgb({r},{g},{b})"


def confirmed_label(view: TopicView) -> str:
    days = days_since_confirmed(view)
    return "Confirmed today" if days == 0 else f"Confirmed {days}d ago"


def recall_suffix(view: TopicView) -> str:
    """ " · Recall: Shaky" once a rating exists, else an empty string."""
    return (
        f" · Recall: {view.practice.recall_last}" if view.practice.recall_last else ""
    )


def level_pips(level: ViewLevel, show_name: bool = True) -> None:
    with ui.element("div").classes("vd-level") as holder:
        with ui.element("span").classes("vd-pips"):
            for index in range(1, MAX_LEVEL + 1):
                ui.element("span").classes(
                    "vd-pip on" if index <= level.level else "vd-pip"
                )
        if show_name:
            ui.label(level.name)
    tip = f"Level {level.level} of {MAX_LEVEL}: {level.name}."
    if level.next_hint:
        tip += f" Next: {level.next_hint}"
    holder.tooltip(tip)


def current_streak(state: AppState) -> int:
    """Consecutive weeks with a rep or a My Views action."""
    return weekly_streak(activity_dates(state, load_database().sessions))


def current_levels(views: list[TopicView]) -> dict[str, ViewLevel]:
    sessions = load_database().sessions
    return {view.id: view_level(view, sessions) for view in views}


def confirm_view(view: TopicView, persist) -> None:
    """ "Still holds": app-only timestamp, so nothing is queued for Obsidian sync."""
    view.reviewed_at = datetime.now(timezone.utc)
    persist()


def record_recall(view: TopicView, rating: str, persist) -> None:
    """Save a self-rated recall; app-only, never touches updated_at or the sync."""
    if rating not in RECALL_RATINGS:
        raise ValueError(f"Unknown recall rating: {rating}")
    view.practice.recall_last = rating
    view.practice.recall_at = datetime.now(timezone.utc)
    persist()


# ── Deck state ───────────────────────────────────────────────────────────────


def _ordered_ids(views: list[TopicView], order: str) -> list[str]:
    if order == "stale":
        return [v.id for v in sorted(views, key=freshness_ratio, reverse=True)]
    if order == "shuffle":
        ids = [v.id for v in views]
        random.shuffle(ids)
        return ids
    return [v.id for v in views]


def _new_stats() -> dict:
    return {
        "confirmed": set(),
        "edited": set(),
        "reps": 0,
        "levelups": 0,
        "bests": 0,
        "ratings": {},
    }


def start_deck(local: dict, views: list[TopicView], order: str = "listed") -> None:
    local["deck"] = {
        "base": [v.id for v in views],
        "ids": _ordered_ids(views, order),
        "i": 0,
        "order": order,
        "mode": "recall",
        "revealed": False,
        "done": False,
        "stats": _new_stats(),
        "panel": None,
        "cleanup": None,
        "undo": None,
    }


def open_deck_picker(local: dict, views: list[TopicView], refresh) -> None:
    """Choose which of the currently listed Views to flip through."""
    if not views:
        ui.notify("There are no Views to flip through.", type="warning")
        return
    groups = [(f"All listed Views ({len(views)})", views)]
    core = [v for v in views if v.priority == "Core"]
    shaky = [v for v in views if v.practice.recall_last in ("Shaky", "Blanked")]
    groups.append((f"Core only ({len(core)})", core))
    groups.append((f"Shaky or blanked last time ({len(shaky)})", shaky))
    for tag in sorted({t for v in views for t in v.tags if t != "view"}):
        tagged = [v for v in views if tag in v.tags]
        groups.append((f"Tagged {tag} ({len(tagged)})", tagged))

    with (
        ui.dialog() as dialog,
        ui.card().classes("tv-section").style("min-width:min(420px,92vw)"),
    ):
        ui.label("FLIP THROUGH").classes("section-header")
        ui.label("Which Views?").classes("tv-meta")

        def choose(subset: list[TopicView]) -> None:
            dialog.close()
            start_deck(local, subset)
            refresh()

        for label, subset in groups:
            button = (
                ui.button(label, on_click=lambda _, s=subset: choose(s))
                .props("flat no-caps align=left")
                .classes("w-full")
            )
            if not subset:
                button.disable()
        ui.button("Cancel", on_click=dialog.close).classes("cancel-btn").style(
            "margin-top:.4rem"
        )
    dialog.open()


async def _close_panel(deck: dict) -> None:
    cleanup = deck.get("cleanup")
    deck["cleanup"] = None
    deck["panel"] = None
    if cleanup is not None:
        await cleanup()


def _ago(value: datetime | None) -> str:
    if value is None:
        return "never"
    now = datetime.now(value.tzinfo) if value.tzinfo is not None else datetime.now()
    days = max(0, (now - value).days)
    return "today" if days == 0 else f"{days}d ago"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def summary_line(deck: dict, streak: int = 0) -> str:
    """One-line recap of a finished pass."""
    stats = deck["stats"]
    parts = [_plural(len(deck["base"]), "View")]
    if stats["confirmed"]:
        parts.append(f"{len(stats['confirmed'])} confirmed")
    if stats["edited"]:
        parts.append(f"{len(stats['edited'])} edited")
    if stats["reps"]:
        parts.append(_plural(stats["reps"], "rep"))
    if stats["levelups"]:
        parts.append(_plural(stats["levelups"], "level up"))
    if stats["bests"]:
        parts.append(_plural(stats["bests"], "new best"))
    counts = {r: 0 for r in RECALL_RATINGS}
    for rating in stats["ratings"].values():
        counts[rating] += 1
    recall = [f"{n} {r}" for r, n in counts.items() if n]
    if recall:
        parts.append("recall: " + ", ".join(recall))
    if streak >= 2:
        parts.append(f"{streak}-week streak")
    return " · ".join(parts)


# ── Deck ─────────────────────────────────────────────────────────────────────


def render_deck(state: AppState, local: dict, persist, refresh) -> None:
    deck = local["deck"]
    by_id = {v.id: v for v in state.topic_views if not v.archived}
    deck["ids"] = [i for i in deck["ids"] if i in by_id]
    if deck["ids"]:
        deck["i"] = max(0, min(deck["i"], len(deck["ids"]) - 1))

    async def leave() -> None:
        await _close_panel(deck)
        local["deck"] = None
        refresh()

    async def go(index: int) -> None:
        target = max(0, min(len(deck["ids"]) - 1, index))
        await _close_panel(deck)
        deck.update(i=target, revealed=False)
        refresh()

    async def finish() -> None:
        await _close_panel(deck)
        deck["done"] = True
        refresh()

    async def advance() -> None:
        if deck["i"] >= len(deck["ids"]) - 1:
            await finish()
        else:
            await go(deck["i"] + 1)

    async def set_order(value: str) -> None:
        if value == deck["order"]:
            return
        base = [by_id[i] for i in deck["base"] if i in by_id]
        await _close_panel(deck)
        deck.update(order=value, ids=_ordered_ids(base, value), i=0, revealed=False)
        refresh()

    async def set_mode(value: str) -> None:
        if value == deck["mode"]:
            return
        await _close_panel(deck)
        deck.update(mode=value, revealed=False)
        refresh()

    with ui.element("div").classes("vd-shell"):
        with ui.row().style(
            "width:100%;justify-content:space-between;align-items:center;gap:.65rem;flex-wrap:wrap"
        ):
            ui.button("All Views", icon="arrow_back", on_click=leave).classes(
                "cancel-btn"
            )
            if not deck["done"]:
                with ui.row().style("gap:.5rem;align-items:center;flex-wrap:wrap"):
                    ui.toggle(
                        _MODES,
                        value=deck["mode"],
                        on_change=lambda e: set_mode(e.value),
                    ).props("dense no-caps").classes("vd-order tv-toggle-side")
                    ui.toggle(
                        _ORDERS,
                        value=deck["order"],
                        on_change=lambda e: set_order(e.value),
                    ).props("dense no-caps").classes("vd-order tv-toggle-side")
                ui.label(
                    f"{deck['i'] + 1} / {len(deck['ids'])}" if deck["ids"] else "0 / 0"
                ).classes("vd-count")

        if deck["done"]:
            _render_summary(state, local, deck, by_id, refresh)
            return

        if not deck["ids"]:
            with ui.element("div").classes("tv-empty").style("margin-top:1rem"):
                ui.label("No Views to flip through.").style("font-weight:700")
            return

        view = by_id[deck["ids"][deck["i"]]]
        level = current_levels([view])[view.id]
        last = deck["i"] >= len(deck["ids"]) - 1
        recall_mode = deck["mode"] == "recall"

        async def return_to(view_id: str) -> None:
            """After an undo, bring the deck back to the card that was just undone."""
            if local.get("deck") is not deck or view_id not in deck["ids"]:
                return
            deck["done"] = False
            await go(deck["ids"].index(view_id))

        async def still_holds() -> None:
            view_id, previous = view.id, view.reviewed_at
            note_activity(state)
            confirm_view(view, persist)
            deck["stats"]["confirmed"].add(view_id)

            async def undo_confirm() -> None:
                view.reviewed_at = previous
                persist()
                deck["stats"]["confirmed"].discard(view_id)
                await return_to(view_id)

            deck["undo"] = show_undo(f"'{view.name}' confirmed", undo_confirm)
            await advance()

        async def rate(rating: str) -> None:
            view_id = view.id
            previous = (view.practice.recall_last, view.practice.recall_at)
            earlier = deck["stats"]["ratings"].get(view_id)
            note_activity(state)
            record_recall(view, rating, persist)
            deck["stats"]["ratings"][view_id] = rating

            async def undo_rating() -> None:
                view.practice.recall_last, view.practice.recall_at = previous
                persist()
                if earlier is None:
                    deck["stats"]["ratings"].pop(view_id, None)
                else:
                    deck["stats"]["ratings"][view_id] = earlier
                await return_to(view_id)

            deck["undo"] = show_undo(f"'{view.name}' rated {rating}", undo_rating)
            await advance()

        def reveal() -> None:
            if deck["revealed"]:
                return
            deck["revealed"] = True
            draw_ctrl()
            draw_content()

        def edited() -> None:
            deck["stats"]["edited"].add(view.id)

        card = (
            ui.element("div")
            .classes("vd-card")
            .style(f"--vd-fresh:{freshness_color(view)};margin-top:.8rem")
        )
        with card:
            with ui.row().style(
                "width:100%;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap"
            ):
                ui.label(view.name).classes("vd-name")
                with ui.row().style("gap:.6rem;align-items:center"):
                    level_pips(level)
                    ui.label(view.priority).classes("tv-pill")
            practiced = (
                f"Practiced {_ago(view.practice.last_practiced)}"
                if view.practice.last_practiced
                else "Not practiced yet"
            )
            recalled = (
                f" · Recall: {view.practice.recall_last} {_ago(view.practice.recall_at)}"
                if view.practice.recall_last
                else ""
            )
            ui.label(
                f"{confirmed_label(view)} · {practiced} · "
                f"{view.practice.practice_count} sessions{recalled}"
            ).classes("tv-meta")

            ctrl_slot = ui.element("div").classes("vd-ctrl")
            panel_slot = ui.element("div").style("width:100%")
            content_slot = ui.element("div").style("width:100%")

            def redraw_panel() -> None:
                panel_slot.clear()
                with panel_slot:
                    if deck["panel"] == "edit":
                        _quick_edit(view, persist, toggle_panel, refresh, edited)
                    elif deck["panel"] == "say":
                        _say_panel(view, state, deck, redraw_panel, toggle_panel)

            async def toggle_panel(name: str | None) -> None:
                same = name == deck["panel"]
                await _close_panel(deck)
                if name is not None and not same:
                    deck["panel"] = name
                redraw_panel()

            def say_button() -> None:
                say = ui.button(
                    "Say it", icon="mic", on_click=lambda: toggle_panel("say")
                ).props("flat no-caps")
                if not llm_available():
                    say.disable()
                    say.tooltip("Add an LLM API key in Settings to grade reps")

            def draw_ctrl() -> None:
                ctrl_slot.clear()
                hidden = recall_mode and not deck["revealed"]
                with ctrl_slot:
                    if hidden:
                        with ui.element("div").classes("vd-row"):
                            with ui.button(
                                "Reveal", icon="visibility", on_click=reveal
                            ).classes("submit-btn"):
                                ui.label("Space").classes("vd-kbd")
                            say_button()
                        return
                    if recall_mode:
                        with (
                            ui.element("div")
                            .classes("vd-row")
                            .style("margin-bottom:.5rem")
                        ):
                            ui.label("HOW DID YOUR RECALL GO?").classes("vd-rate-label")
                            for rating, label, color, key in _RATING_UI:
                                with ui.button(
                                    label, on_click=lambda _, r=rating: rate(r)
                                ).props(f"outline no-caps color={color}"):
                                    ui.label(key).classes("vd-kbd")
                    with ui.element("div").classes("vd-row"):
                        with (
                            ui.button("Still holds", icon="check", on_click=still_holds)
                            .classes("submit-btn")
                            .tooltip("Confirm this View as current without editing it")
                        ):
                            ui.label("H").classes("vd-kbd")
                        with ui.button(
                            "Quick edit",
                            icon="edit",
                            on_click=lambda: toggle_panel("edit"),
                        ).props("flat no-caps"):
                            ui.label("E").classes("vd-kbd")
                        say_button()
                        ui.element("div").style("flex:1")
                        ui.button(
                            "Open full editor",
                            icon="open_in_new",
                            on_click=lambda: _open_editor(local, view, deck, refresh),
                        ).props("flat dense no-caps")

            def draw_content() -> None:
                content_slot.clear()
                with content_slot:
                    if recall_mode and not deck["revealed"]:
                        ui.label(f"What's your view on {view.name}?").classes(
                            "vd-prompt"
                        )
                        ui.label(
                            f"{_plural(len([p for p in view.points if p.title.strip()]), 'point')} · "
                            "say it out loud first, then reveal"
                        ).classes("tv-meta")
                        return
                    _render_content(view)

            draw_ctrl()
            draw_content()

        with ui.row().style(
            "width:100%;justify-content:space-between;margin-top:.8rem"
        ):
            ui.button(
                "Previous", icon="chevron_left", on_click=lambda: go(deck["i"] - 1)
            ).props("flat no-caps").set_enabled(deck["i"] > 0)
            if last:
                ui.button("Finish", icon="flag", on_click=finish).props("flat no-caps")
            else:
                ui.button(
                    "Next", icon="chevron_right", on_click=lambda: go(deck["i"] + 1)
                ).props("flat no-caps icon-right=chevron_right")
        ui.label(
            "Space reveal · 1 2 3 rate · H still holds · E edit · S say it · U undo · ← → or J K flip · Esc close"
            if recall_mode
            else "H still holds · E edit · S say it · U undo · ← → or J K flip · Esc close"
        ).classes("vd-keys")

        async def on_key(e) -> None:
            if not e.action.keydown:
                return
            key = e.key.name
            if deck["panel"] is not None:
                if e.key.escape:
                    await toggle_panel(None)
                return
            hidden = recall_mode and not deck["revealed"]
            if e.key.space or key == " ":
                reveal()
            elif key in ("1", "2", "3") and recall_mode and not hidden:
                await rate(RECALL_RATINGS[int(key) - 1])
            elif key in ("h", "H") and not hidden:
                await still_holds()
            elif key in ("e", "E") and not hidden:
                await toggle_panel("edit")
            elif key in ("s", "S") and llm_available():
                await toggle_panel("say")
            elif key in ("u", "U"):
                if deck.get("undo") is not None and not deck["undo"].used:
                    await deck["undo"].undo()
            elif e.key.arrow_right or key in ("j", "J"):
                if not last:
                    await go(deck["i"] + 1)
            elif e.key.arrow_left or key in ("k", "K"):
                if deck["i"] > 0:
                    await go(deck["i"] - 1)

        ui.keyboard(
            on_key=on_key, repeating=False, ignore=["input", "select", "textarea"]
        )


def _render_content(view: TopicView) -> None:
    """Bottom line, then each point's claim with the detail and facts folded under it."""
    ui.markdown(view.bottom_line or "*Bottom line not developed yet.*").classes(
        "vd-md vd-bottom"
    )
    shown = 0
    for point in view.points:
        facts = [fact for fact in point.facts if fact.text.strip()]
        if not point.title.strip() and not facts:
            continue
        shown += 1
        lead, rest = split_point(point.title)
        with ui.element("div").classes("vd-point"):
            ui.label(f"{shown}. {lead or '(untitled point)'}").classes("vd-point-title")
            if rest or facts:
                label = "Details" + (
                    f" · {_plural(len(facts), 'fact')}" if facts else ""
                )
                with ui.expansion(label).props("dense").classes("vd-more"):
                    if rest:
                        ui.markdown(rest).classes("vd-more-body")
                    for fact in facts:
                        ui.label(f"• {fact.text}").classes("vd-fact")
    extras = [
        ("Counterargument", view.counterargument),
        ("What changes my mind", view.changes_my_mind),
    ]
    if any(text.strip() for _, text in extras):
        with (
            ui.expansion("Counterargument & what changes my mind")
            .classes("w-full")
            .style("margin-top:.4rem")
        ):
            for label, text in extras:
                if text.strip():
                    ui.label(label.upper()).classes("tv-meta").style(
                        "font-weight:700;margin-top:.4rem"
                    )
                    ui.markdown(text).classes("vd-md vd-fb").style("margin-top:.1rem")


def _render_summary(
    state: AppState, local: dict, deck: dict, by_id: dict, refresh
) -> None:
    shaky = [
        by_id[i]
        for i, rating in deck["stats"]["ratings"].items()
        if rating in ("Shaky", "Blanked") and i in by_id
    ]
    with ui.element("div").classes("vd-card").style("margin-top:.8rem"):
        ui.label("DECK COMPLETE").classes("section-header")
        ui.label(summary_line(deck, current_streak(state))).classes("vd-summary-line")
        with ui.element("div").classes("vd-row"):
            if shaky:

                def again() -> None:
                    start_deck(local, shaky)
                    refresh()

                ui.button(
                    f"Run the Shaky ones again ({len(shaky)})",
                    icon="replay",
                    on_click=again,
                ).classes("submit-btn")

            def start_over() -> None:
                start_deck(local, [by_id[i] for i in deck["base"] if i in by_id])
                refresh()

            ui.button("Start over", icon="restart_alt", on_click=start_over).props(
                "flat no-caps"
            )
            ui.button(
                "All Views",
                icon="arrow_back",
                on_click=lambda: (local.update(deck=None), refresh()),
            ).props("flat no-caps")


async def _open_editor(local: dict, view: TopicView, deck: dict, refresh) -> None:
    await _close_panel(deck)
    local.update(selected=view.id, deck=None)
    refresh()


# ── Quick edit ───────────────────────────────────────────────────────────────


def _quick_edit(view: TopicView, persist, toggle_panel, refresh, on_saved) -> None:
    with ui.element("div").classes("vd-panel"):
        ui.label("QUICK EDIT").classes("section-header")
        bottom = (
            ui.textarea(label="Bottom line", value=view.bottom_line)
            .classes("w-full dark-input tv-edit")
            .props("autogrow")
        )
        counter = (
            ui.textarea(label="Counterargument", value=view.counterargument)
            .classes("w-full dark-input tv-edit")
            .props("autogrow")
        )
        mind = (
            ui.textarea(label="What changes my mind", value=view.changes_my_mind)
            .classes("w-full dark-input tv-edit")
            .props("autogrow")
        )
        ui.label("POINTS · add a fact (dated today)").classes("tv-meta").style(
            "font-weight:700;margin-top:.6rem"
        )
        rows = []
        for index, point in enumerate(view.points, 1):
            with ui.element("div").style("margin-top:.4rem;width:100%"):
                title = ui.input(label=f"Point {index}", value=point.title).classes(
                    "w-full dark-input"
                )
                fact = ui.input(placeholder="+ new supporting fact").classes(
                    "w-full dark-input"
                )
            rows.append((point, title, fact))

        async def save() -> None:
            changed = False
            for field, control in (
                ("bottom_line", bottom),
                ("counterargument", counter),
                ("changes_my_mind", mind),
            ):
                value = (control.value or "").strip()
                if value != getattr(view, field):
                    setattr(view, field, value)
                    changed = True
            for point, title, fact in rows:
                value = (title.value or "").strip()
                if value != point.title:
                    point.title = value
                    changed = True
                text = (fact.value or "").strip()
                if text:
                    point.facts.append(
                        ViewFact(text=text, as_of=date.today().isoformat())
                    )
                    changed = True
            if changed:
                persist(view)
                on_saved()
                ui.notify(f"'{view.name}' updated.", type="positive", timeout=1500)
            await toggle_panel(None)
            if changed:
                refresh()

        with ui.row().style("justify-content:flex-end;gap:.5rem;margin-top:.7rem"):
            ui.button("Cancel", on_click=lambda: toggle_panel(None)).classes(
                "cancel-btn"
            )
            ui.button("Save", icon="check_circle", on_click=save).classes("submit-btn")


# ── Say it ───────────────────────────────────────────────────────────────────


def _combine(base: str, text: str) -> str:
    return f"{base.strip()} {text.strip()}".strip()


def _say_panel(
    view: TopicView, state: AppState, deck: dict, redraw_panel, toggle_panel
) -> None:
    rep = {"session_id": None}
    submitting = {"value": False}
    voice_active = {"value": False}
    voice_origin = {"value": False}
    token = {"value": 0}

    async def cleanup() -> None:
        """Release the mic and abandon an unfinished rep so it never lingers as 'active'."""
        token["value"] += 1
        await cancel_recording()
        session_id = rep["session_id"]
        rep["session_id"] = None
        if session_id:
            from services.interview_controller import abandon_session

            try:
                abandon_session(session_id)
            except Exception:
                _log.debug("Could not abandon quick rep %s", session_id, exc_info=True)

    deck["cleanup"] = cleanup

    with ui.element("div").classes("vd-panel"):
        ui.label("SAY IT").classes("section-header")
        ui.label(f"What's your view on {view.name}?").classes("vd-question")
        form = ui.element("div").style("width:100%")
        result_box = ui.element("div").style("width:100%")

        with form:
            answer = (
                ui.textarea(
                    placeholder="Say it out loud or type it. Bottom line first."
                )
                .classes("w-full dark-input tv-edit")
                .props("autogrow")
            )
            with ui.element("div").classes(
                "interview-recording-panel"
            ) as recording_panel:
                recording_status = ui.label("Microphone ready").classes(
                    "interview-recording-status"
                )
                with ui.element("div").classes("interview-audio-track"):
                    ui.element("div").classes("interview-audio-level")
                ui.label("").classes("interview-live-caption")
            recording_panel.visible = False
            error = ui.label("").style(
                "color:#f87171;font-size:.78rem;min-height:1rem;margin-top:.3rem"
            )

            async def begin() -> None:
                if voice_active["value"] or submitting["value"]:
                    return
                error.set_text("")
                mic.disable()
                try:
                    result = await start_recording()
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                mic.enable()
                if not result.get("ok"):
                    error.set_text(
                        str(result.get("error") or "Could not start recording.")
                    )
                    return
                voice_active["value"] = True
                recording_panel.visible = True
                recording_status.set_text("Recording 00:00 · pauses are safe")
                mic.visible = False
                stop_btn.visible = True
                submit_btn.disable()

            async def finish() -> None:
                if not voice_active["value"]:
                    return
                voice_active["value"] = False
                stop_btn.disable()
                my_token = token["value"]
                try:
                    result = await stop_recording()
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                stop_btn.visible = False
                stop_btn.enable()
                mic.visible = True
                submit_btn.enable()
                if not result.get("ok"):
                    error.set_text(str(result.get("error") or "Recording failed."))
                    recording_panel.visible = False
                    return
                base = (answer.value or "").strip()
                seed = _combine(base, str(result.get("preview") or ""))
                if seed != base:
                    answer.set_value(seed)
                    voice_origin["value"] = True
                    recording_status.set_text(
                        "Live draft ready · review before grading"
                    )
                else:
                    recording_status.set_text(
                        "Audio recorded · no live captions, so type your answer"
                    )
                if not speech_runtime_available():
                    return
                recording_status.set_text("Refining transcript locally…")
                try:
                    refined = await transcribe_recording(
                        speech_bias_context(view.name, views_context([view]))
                    )
                except Exception:
                    refined = {"ok": False}
                if my_token != token["value"] or submitting["value"]:
                    return
                if refined.get("ok") and (answer.value or "").strip() == seed:
                    answer.set_value(_combine(base, str(refined.get("text") or "")))
                    voice_origin["value"] = True
                    recording_status.set_text(
                        "Transcript ready · review before grading"
                    )
                else:
                    recording_status.set_text("Draft ready · review before grading")

            async def submit() -> None:
                if submitting["value"]:
                    return
                if voice_active["value"]:
                    error.set_text("Stop the recording before grading.")
                    return
                text = (answer.value or "").strip()
                if not text:
                    error.set_text(
                        "Answer the question, or say plainly that you do not know."
                    )
                    return
                submitting["value"] = True
                token["value"] += 1
                error.set_text("")
                submit_btn.disable()
                mic.disable()
                submit_btn.set_text("Grading…")
                before = current_levels([view])[view.id]
                try:
                    if rep["session_id"] is None:
                        preset = get_preset("view_deliver")
                        session = await run.io_bound(
                            lambda: start_session(
                                mode=preset.mode,
                                preset_key=preset.key,
                                topic=view.name,
                                view_ids=[view.id],
                                practice_style="Deliver",
                                view_context=views_context([view]),
                                initial_question=f"What's your view on {view.name}?",
                                target_questions=preset.default_questions,
                                model=preferred_model() or grader_model(),
                            )
                        )
                        rep["session_id"] = session.id
                    session_id = rep["session_id"]
                    updated, result = await run.io_bound(
                        lambda: evaluate_answer(
                            session_id,
                            text,
                            voice_origin=voice_origin["value"],
                        )
                    )
                except InterviewProviderError:
                    error.set_text(
                        "Could not reach the model. Your answer is still here; try again."
                    )
                except InterviewOutputError:
                    error.set_text(
                        "The model returned unusable feedback. Try again or switch models."
                    )
                except Exception:
                    _log.exception("Quick rep failed for view %s", view.id)
                    error.set_text(
                        "Something went wrong grading that. Your answer is still here."
                    )
                else:
                    rep["session_id"] = None
                    await cancel_recording()
                    _sync_view_metadata(state, [view.id])
                    background_tasks.create(_summarize(state, updated.id, view.id))
                    after = current_levels([view])[view.id]
                    deck["stats"]["reps"] += 1
                    if after.level > before.level:
                        deck["stats"]["levelups"] += 1
                    best = is_personal_best(updated, load_database().sessions)
                    if best:
                        deck["stats"]["bests"] += 1
                    form.set_visibility(False)
                    with result_box:
                        _result(
                            updated, result, before, after, best, redraw_panel, deck
                        )
                    submitting["value"] = False
                    return
                submitting["value"] = False
                submit_btn.enable()
                submit_btn.set_text("Grade it")
                mic.enable()

            with ui.row().style(
                "gap:.5rem;margin-top:.6rem;align-items:center;flex-wrap:wrap"
            ):
                mic = ui.button("Speak", icon="mic", on_click=begin).props(
                    "flat no-caps"
                )
                stop_btn = ui.button("Stop", icon="stop", on_click=finish).props(
                    "no-caps color=negative"
                )
                stop_btn.visible = False
                submit_btn = ui.button(
                    "Grade it", icon="check_circle", on_click=submit
                ).classes("submit-btn")
                ui.element("div").style("flex:1")
                ui.button("Close", on_click=lambda: toggle_panel(None)).classes(
                    "cancel-btn"
                )


def _result(
    session,
    result: dict,
    before: ViewLevel,
    after: ViewLevel,
    best: bool,
    redraw_panel,
    deck,
) -> None:
    band = session_band(session) if band_visible(session) else None
    if band:
        label, descriptor, following = band
        ui.label(f"Band {label} · {descriptor}").classes("vd-band")
        if following:
            ui.label(f"Next band: {following}").classes("tv-meta").style(
                "margin-top:.15rem"
            )
    if result.get("critique"):
        ui.label(result["critique"]).classes("vd-fb")
    if result.get("fix"):
        ui.label("FIX").classes("tv-meta").style("font-weight:700;margin-top:.55rem")
        ui.label(result["fix"]).classes("vd-fb").style("margin-top:.1rem")
    if result.get("evaluation_status") == "partial":
        ui.label(
            "Partial feedback — the model returned a score but was missing a critique or fix."
        ).classes("tv-meta").style("margin-top:.4rem")
    if best and band:
        ui.label(f"NEW BEST · Band {band[0]}").classes("vd-levelup")
    if after.level > before.level:
        ui.label(f"LEVEL UP · {after.name}").classes("vd-levelup")

    async def again() -> None:
        deck["cleanup"] = None
        deck["panel"] = "say"
        redraw_panel()

    with ui.row().style("gap:.5rem;margin-top:.7rem"):
        ui.button("Say it again", icon="replay", on_click=again).classes("submit-btn")
        ui.button(
            "Close", on_click=lambda: _close_and_redraw(deck, redraw_panel)
        ).classes("cancel-btn")


async def _close_and_redraw(deck: dict, redraw_panel) -> None:
    await _close_panel(deck)
    redraw_panel()


async def _summarize(state: AppState, session_id: str, view_id: str) -> None:
    """Whole-session review for the quick rep; runs after the card feedback is already shown."""
    try:
        await run.io_bound(lambda: synthesize_session(session_id))
    except Exception:
        _log.exception("Quick rep synthesis failed for session %s", session_id)
    finally:
        _sync_view_metadata(state, [view_id])
