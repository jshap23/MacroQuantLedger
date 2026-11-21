"""A small in-page Undo snackbar for one-click actions (Still holds, recall ratings)."""

from __future__ import annotations

import inspect

from nicegui import context, ui

_active: dict[str, "UndoToast"] = {}


def inject_undo_css() -> None:
    ui.add_head_html("""<style id="mq-undo-css">
      .mq-undo-toast{position:fixed;left:50%;bottom:1.4rem;transform:translateX(-50%);z-index:6000;display:flex;align-items:center;gap:.8rem;padding:.5rem .6rem .5rem 1rem;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border-strong);border-radius:8px;box-shadow:0 10px 28px rgba(0,0,0,.4);font:600 .78rem 'IBM Plex Mono',monospace;max-width:92vw}
      body.light-mode .mq-undo-toast{box-shadow:0 10px 28px rgba(0,0,0,.15)}
    </style>""")


class UndoToast:
    """One visible Undo offer; undo() runs its callback at most once."""

    def __init__(self, element, client_id: str, on_undo) -> None:
        self._element = element
        self._client_id = client_id
        self._on_undo = on_undo
        self.used = False

    def dismiss(self) -> None:
        if _active.get(self._client_id) is self:
            _active.pop(self._client_id, None)
        try:
            self._element.delete()
        except Exception:
            pass

    async def undo(self) -> None:
        if self.used:
            return
        self.used = True
        self.dismiss()
        result = self._on_undo()
        if inspect.isawaitable(result):
            await result


def show_undo(message: str, on_undo, seconds: float = 8.0) -> UndoToast:
    """Offer to reverse the action just taken; a newer offer replaces an older one."""
    client = context.client
    previous = _active.get(client.id)
    if previous is not None:
        previous.dismiss()
    with client.content:
        element = ui.element("div").classes("mq-undo-toast")
        toast = UndoToast(element, client.id, on_undo)
        with element:
            ui.label(message)
            ui.button("Undo", on_click=toast.undo).props("flat dense no-caps")
            ui.timer(seconds, toast.dismiss, once=True)
    _active[client.id] = toast
    return toast
