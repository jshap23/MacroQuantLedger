"""Obsidian export for TopicViews.

Detailed formatting logic (frontmatter schema, wikilinks, tags, ZIP bundles,
practice-history inclusion) will be provided in a future session. This module
exposes the intended interface so the rest of the app can wire up UI calls
without guessing at signatures.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from models.schema import TopicView


class TopicExportOptions(BaseModel):
    """Options governing how TopicViews are exported to Obsidian."""

    include_practice: bool = False
    include_wikilinks: bool = False
    include_sources: bool = True
    extra_tags: list[str] = []
    subfolder: str = "topics"  # relative to vault root
    zip_output: bool = False


class TopicWriter(Protocol):
    """Writer strategy for topic exports."""

    def write(self, view: TopicView, content: str, base_path: Path) -> Path:
        ...


def render_topic(view: TopicView, opts: TopicExportOptions) -> str:
    """Pure: render a single TopicView to an Obsidian markdown string."""
    # Placeholder: the detailed markdown/frontmatter schema will be provided
    # in the Topics/Views design session.
    lines = [
        "---",
        f"id: {view.id}",
        f"title: {view.name}",
        "---",
        "",
        f"# {view.name}",
        "",
        "(Obsidian topic export formatting is TBD.)",
    ]
    return "\n".join(lines)


def export_topic(
    view: TopicView,
    base_path: Path,
    opts: TopicExportOptions | None = None,
) -> Path:
    """Export a single TopicView to the Obsidian vault."""
    opts = opts or TopicExportOptions()
    content = render_topic(view, opts)
    dest = base_path / opts.subfolder
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"{view.id}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def export_topics(
    views: list[TopicView],
    base_path: Path,
    opts: TopicExportOptions | None = None,
) -> list[Path]:
    """Export multiple TopicViews. Returns the list of written file paths."""
    return [export_topic(v, base_path, opts) for v in views]
