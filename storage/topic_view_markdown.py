"""Lossless parse/render between TopicView and Obsidian Markdown notes.

Owned sections (My View, Why, Watch, Counterargument, What Changes My Mind)
are regenerated from the model. Every other part of the body — extra headings,
prose, callouts — is preserved verbatim and in its original position.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from models.schema import TopicView, ViewFact, ViewPoint, _now_utc, _uuid

FM_BOUNDARY = "---\n"

_STATUS_MAP = {
    "developing": "Developing",
    "ready": "Ready",
    "needs refresh": "Needs Refresh",
    "needs_refresh": "Needs Refresh",
}

_PRIORITY_MAP = {
    "core": "Core",
    "normal": "Normal",
    "low priority": "Low Priority",
    "low_priority": "Low Priority",
}

CANONICAL_HEADINGS = {
    "my view": "My View",
    "why": "Why",
    "watch": "Watch",
    "counterargument": "Counterargument",
    "what changes my mind": "What Changes My Mind",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WHY_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_FACT_RE = re.compile(r"^\s+[-*]\s+(.*)$")


def _normalize_status(value: str | None) -> str:
    if not value:
        return "Developing"
    key = str(value).strip().lower()
    return _STATUS_MAP.get(key, key.title() if key else "Developing")


def _normalize_priority(value: str | None) -> str:
    if not value:
        return "Normal"
    key = str(value).strip().lower()
    return _PRIORITY_MAP.get(key, key.title() if key else "Normal")


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return _now_utc()
    text = str(value).strip().strip("'\"")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return _now_utc()


def _format_timestamp(value: datetime | None) -> str:
    """Human-readable note format: second precision, UTC, no microseconds."""
    if not value:
        value = _now_utc()
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _single_line(text: str) -> str:
    return re.sub(r"\s*\r?\n\s*", " ", text or "").strip()


class MarkdownTopicView:
    """Parsed note: the TopicView, raw frontmatter, and the body layout needed
    for verbatim re-rendering of foreign content."""

    def __init__(
        self,
        view: TopicView,
        frontmatter: dict[str, Any],
        blocks: Optional[list[dict]] = None,
        present: Optional[set[str]] = None,
        path: Path | None = None,
        ambiguous: Optional[list[str]] = None,
    ):
        self.view = view
        self.frontmatter = frontmatter
        self.blocks = blocks or []
        self.present = present or set()
        self.path = path
        self.ambiguous = ambiguous or []


def _extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split(FM_BOUNDARY, 2)
    if len(parts) < 3:
        return {}, text
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        frontmatter = {}
    body_lines = parts[2].splitlines()
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    body = "\n".join(body_lines)
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


def _classify(heading_text: str) -> str | None:
    key = heading_text.strip().lower()
    return key if key in CANONICAL_HEADINGS else None


def _parse_why(content: str) -> list[ViewPoint]:
    points: list[ViewPoint] = []
    for line in content.splitlines():
        item = _WHY_ITEM_RE.match(line)
        if item:
            points.append(ViewPoint(title=item.group(2).strip()))
            continue
        fact = _FACT_RE.match(line)
        if fact and points:
            text = fact.group(1).strip()
            if text:
                points[-1].facts.append(ViewFact(text=text))
    return points


def _parse_free_text(content: str) -> str:
    return content.strip()


def _parse_watch(content: str) -> list[str]:
    items: list[str] = []
    for line in content.splitlines():
        match = re.match(r"^\s*[-*]\s+(.*)$", line)
        if match:
            text = match.group(1).strip()
            if text:
                items.append(text)
    return items


def parse_topic_view(text: str, file_path: Path | None = None) -> MarkdownTopicView:
    frontmatter, body = _extract_frontmatter(text)

    view_id = str(frontmatter.get("view_id") or frontmatter.get("id") or "").strip()
    if not view_id:
        view_id = _uuid()

    blocks: list[dict] = []
    present: set[str] = set()
    title = ""

    pending: tuple[tuple[str, str] | None, list[str]] = (None, [])
    segments: list[tuple[tuple[str, str] | None, list[str]]] = []
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            segments.append(pending)
            pending = ((match.group(1), match.group(2)), [])
        else:
            pending[1].append(line)
    segments.append(pending)

    h1_index = next(
        (i for i, (head, _) in enumerate(segments) if head is not None and head[0] == "#"),
        None,
    )

    owned_counts: dict[str, int] = {}
    for index, (head, lines) in enumerate(segments):
        if head is None:
            blocks.append({"head": None, "owned": None, "lines": lines})
            continue
        if index == h1_index:
            title = head[1].strip()
            blocks.append({"head": None, "owned": "__h1__", "lines": lines})
            continue
        owned = _classify(head[1])
        if owned:
            present.add(owned)
            owned_counts[owned] = owned_counts.get(owned, 0) + 1
        blocks.append({
            "head": f"{head[0]} {head[1]}",
            "owned": owned,
            "lines": lines,
        })

    ambiguous = sorted(
        CANONICAL_HEADINGS[name] for name, count in owned_counts.items() if count > 1
    )

    if not title:
        title = str(frontmatter.get("title") or "").strip()

    def section_text(name: str) -> str:
        for block in reversed(blocks):
            if block["owned"] == name:
                return "\n".join(block["lines"])
        return ""

    tags = _format_tags(frontmatter.get("tags"))
    if "view" not in [t.lower() for t in tags]:
        tags.append("view")

    view = TopicView(
        id=view_id,
        name=title or "Untitled View",
        bottom_line=_parse_free_text(section_text("my view")),
        points=_parse_why(section_text("why")),
        watch=_parse_watch(section_text("watch")),
        counterargument=_parse_free_text(section_text("counterargument")) if "counterargument" in present else "",
        changes_my_mind=_parse_free_text(section_text("what changes my mind")) if "what changes my mind" in present else "",
        status=_normalize_status(frontmatter.get("status")),
        priority=_normalize_priority(frontmatter.get("priority")),
        archived=bool(frontmatter.get("archived", False)),
        tags=tags,
        created_at=_parse_iso(frontmatter.get("created_at")),
        updated_at=_parse_iso(frontmatter.get("updated_at")),
    )
    return MarkdownTopicView(view, frontmatter, blocks, present, file_path, ambiguous)


def _owned_content(name: str, view: TopicView) -> list[str]:
    if name == "my view":
        text = _single_line(view.bottom_line)
        return [text] if text else [""]
    if name == "why":
        lines: list[str] = []
        for index, point in enumerate(view.points, 1):
            lines.append(f"{index}. {_single_line(point.title)}")
            for fact in point.facts:
                text = _single_line(fact.text)
                if text:
                    lines.append(f"   - {text}")
        return lines or ["1. "]
    if name == "watch":
        return [f"- {item}" for item in view.watch] or [""]
    if name == "counterargument":
        text = _single_line(view.counterargument)
        return [text] if text else [""]
    if name == "what changes my mind":
        text = _single_line(view.changes_my_mind)
        return [text] if text else [""]
    return [""]


def _format_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tags] if tags else []
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    return []


def render_topic_view(
    view: TopicView,
    prior: MarkdownTopicView | None = None,
    frontmatter: dict[str, Any] | None = None,
) -> str:
    fm = dict(prior.frontmatter) if prior is not None else dict(frontmatter or {})

    fm.pop("type", None)
    fm["view_id"] = view.id
    fm["title"] = view.name
    fm["status"] = str(view.status).lower()
    fm["priority"] = str(view.priority).lower().replace(" ", "_")
    fm["archived"] = bool(view.archived)
    tags = _format_tags(view.tags)
    if "view" not in [t.lower() for t in tags]:
        tags.append("view")
    fm["tags"] = tags
    fm["created_at"] = _format_timestamp(view.created_at)
    fm["updated_at"] = _format_timestamp(view.updated_at)

    yaml_text = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)

    lines: list[str] = ["---", yaml_text.rstrip(), "---", ""]

    blocks = prior.blocks if prior is not None else None
    if not blocks:
        lines.append(f"# {view.name}")
        lines.append("")
        for name in ("my view", "why", "watch"):
            lines.append(f"## {CANONICAL_HEADINGS[name]}")
            lines.extend(_owned_content(name, view))
            lines.append("")
        for name in ("counterargument", "what changes my mind"):
            content = _owned_content(name, view)
            if any(part.strip() for part in content):
                lines.append(f"## {CANONICAL_HEADINGS[name]}")
                lines.extend(content)
                lines.append("")
    else:
        owned_seen: set[str] = set()
        for block in blocks:
            name = block["owned"]
            if name and name != "__h1__":
                if name in owned_seen:
                    raise ValueError(
                        "Refusing to render a note with duplicate owned sections: "
                        f"{CANONICAL_HEADINGS[name]}"
                    )
                owned_seen.add(name)

        emitted: set[str] = set()
        for block in blocks:
            owned = block["owned"]
            if owned == "__h1__":
                lines.append(f"# {view.name}")
                lines.extend(block["lines"])
            elif block["head"] is None:
                lines.extend(block["lines"])
            elif owned:
                lines.append(block["head"])
                lines.extend(_owned_content(owned, view))
                lines.append("")
                emitted.add(owned)
            else:
                lines.append(block["head"])
                lines.extend(block["lines"])
        for name in ("my view", "why", "watch", "counterargument", "what changes my mind"):
            if name in emitted:
                continue
            content = _owned_content(name, view)
            if name in ("counterargument", "what changes my mind") and not any(p.strip() for p in content):
                continue
            lines.append(f"## {CANONICAL_HEADINGS[name]}")
            lines.extend(content)
            lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def write_topic_view(
    view: TopicView,
    path: Path,
    prior: MarkdownTopicView | None = None,
    frontmatter: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_topic_view(view, prior=prior, frontmatter=frontmatter)
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def topic_view_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def note_filename(title: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("-", (title or "").strip()).strip()
    cleaned = cleaned.rstrip(" .") or "Untitled View"
    if cleaned.upper().split(".")[0] in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > 118:
        cleaned = cleaned[:118].rstrip(" .")
    return f"{cleaned}.md"
