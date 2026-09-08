"""Read-only discovery of interview-prep model notes in an Obsidian folder.

Scans the configured Models folder (never writes to it), leniently parses
YAML frontmatter, and renders notes as hidden LLM context for the Practice
tab's "My Models" feature.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from storage.user_settings import quant_models_folder

GENERIC_TAGS: frozenset[str] = frozenset({"models", "quant", "interview-prep"})

_INTERVIEW_SUFFIX_RE = re.compile(r"\s*[-\u2013\u2014]\s*interview\s*$", re.IGNORECASE)
_VS_RE = re.compile(r"\bvs\.?\b|\bversus\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset({"model", "models", "the", "a", "vs", "versus", "interview", "prep"})
_PARSE_WARNING = "Could not parse frontmatter; using filename as title."
_BODY_CHAR_CAP = 12000


@dataclass(frozen=True)
class ModelNote:
    """One read-only model note discovered in the Obsidian Models folder."""

    id: str
    title: str
    path: Path
    relative_path: str
    tags: list[str]
    status: str
    priority: str
    kind: str
    modified_at: datetime
    body: str
    parse_warning: str

    @property
    def display_tags(self) -> list[str]:
        """Non-generic tags, capped at five for display."""
        return [tag for tag in self.tags if tag.lower() not in GENERIC_TAGS][:5]

    @property
    def updated_display(self) -> str:
        """Local-timezone YYYY-MM-DD rendering of the file modification time."""
        return self.modified_at.astimezone().strftime("%Y-%m-%d")


def _strip_interview_suffix(text: str) -> str:
    """Drop a trailing " - Interview" suffix (any dash style, any case)."""
    stripped = _INTERVIEW_SUFFIX_RE.sub("", text).strip()
    return stripped or text.strip()


def _slug_from_stem(stem: str) -> str:
    """Stable id slug: stem minus the Interview suffix, lowercase, dashed."""
    base = _strip_interview_suffix(stem).lower()
    slug = _NON_ALNUM_RE.sub("-", base).strip("-")
    return slug or "note"


def _first_h1(body: str) -> str:
    """First markdown H1 outside fenced code blocks, or ""."""
    in_fence = False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return ""


def _parse_frontmatter(content: str) -> tuple[dict, str, str]:
    """Split note content into (meta, body, parse_warning).

    A missing frontmatter block is not a warning. A malformed, non-dict, or
    unclosed block yields the whole file as body plus a warning.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, content, ""
    close = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            close = index
            break
    if close is None:
        return {}, content, _PARSE_WARNING
    try:
        meta = yaml.safe_load("\n".join(lines[1:close]))
    except yaml.YAMLError:
        return {}, content, _PARSE_WARNING
    if not isinstance(meta, dict):
        return {}, content, _PARSE_WARNING
    return meta, "\n".join(lines[close + 1:]), ""


def _text_field(meta: dict, key: str) -> str:
    value = meta.get(key)
    return "" if value is None else str(value).strip()


def _tags_from_meta(meta: dict) -> list[str]:
    """Tags accept a YAML list or a comma-separated string; anything else is none."""
    raw = meta.get("tags")
    if isinstance(raw, list):
        items = [str(item) for item in raw]
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        items = []
    return [item.strip() for item in items if item.strip()]


def _read_note(path: Path, root: Path) -> ModelNote | None:
    """Parse one file into a ModelNote; None when unreadable or index-kind."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    meta, body, warning = _parse_frontmatter(content)
    stem = path.stem
    if warning:
        raw_title = stem
    else:
        fm_title = meta.get("title")
        if isinstance(fm_title, str) and fm_title.strip():
            raw_title = fm_title.strip()
        else:
            raw_title = _first_h1(body) or stem
    kind = _text_field(meta, "type") or "model"
    if "index" in kind.lower():
        return None
    return ModelNote(
        id=_slug_from_stem(stem),
        title=_strip_interview_suffix(raw_title),
        path=path,
        relative_path=path.relative_to(root).as_posix(),
        tags=_tags_from_meta(meta),
        status=_text_field(meta, "status"),
        priority=_text_field(meta, "priority"),
        kind=kind,
        modified_at=modified_at,
        body=body,
        parse_warning=warning,
    )


def _is_included(path: Path, root: Path) -> bool:
    """Skip files/folders starting with "_" and folders starting with "."."""
    relative = path.relative_to(root)
    if relative.name.startswith("_"):
        return False
    return not any(part.startswith((".", "_")) for part in relative.parts[:-1])


def _ensure_unique_ids(notes: list[ModelNote]) -> list[ModelNote]:
    """Suffix shorter-stem notes on id collision with a hash of their path."""
    groups: dict[str, list[ModelNote]] = {}
    for note in notes:
        groups.setdefault(note.id, []).append(note)
    unique: list[ModelNote] = []
    for base, group in groups.items():
        if len(group) == 1:
            unique.append(group[0])
            continue
        winner = min(group, key=lambda n: (-len(n.path.stem), n.relative_path))
        unique.append(winner)
        for note in group:
            if note is winner:
                continue
            digest = hashlib.sha1(note.relative_path.encode("utf-8")).hexdigest()[:8]
            unique.append(replace(note, id=f"{base}-{digest}"))
    return unique


def _sort_key(note: ModelNote) -> tuple[bool, bool, str]:
    priority = note.priority.lower()
    return priority != "core", priority != "normal", note.title.lower()


def models_folder_path() -> Path | None:
    """Configured Models folder: QUANT_MODELS_FOLDER > saved setting > config default."""
    return quant_models_folder()


def scan_model_notes(folder: Path | None = None) -> list[ModelNote]:
    """Scan the Models folder (or an explicit one) into sorted ModelNotes.

    Missing folders and permission errors yield [] instead of raising;
    unreadable files and index-kind notes are skipped. Never writes.
    """
    root = models_folder_path() if folder is None else folder
    if root is None:
        return []
    if not root.is_absolute():
        root = root.resolve()
    try:
        if not root.is_dir():
            return []
        paths = [path for path in root.rglob("*.md") if _is_included(path, root)]
    except OSError:
        return []
    notes: list[ModelNote] = []
    for path in paths:
        note = _read_note(path, root)
        if note is not None:
            notes.append(note)
    return sorted(_ensure_unique_ids(notes), key=_sort_key)


def model_context_for(notes: list[ModelNote]) -> str:
    """Render notes as one hidden-context string for the interview LLM."""
    if not notes:
        return ""
    blocks: list[str] = []
    for note in notes:
        body = note.body[:_BODY_CHAR_CAP]
        if len(note.body) > _BODY_CHAR_CAP:
            body += "\n[Note truncated.]"
        tags = ", ".join(note.display_tags) or "n/a"
        blocks.append(
            f"## Reference note: {note.title}\n"
            f"(updated {note.updated_display}; tags: {tags})\n\n{body}"
        )
    return "\n\n".join(blocks)


def _significant_words(title: str) -> list[str]:
    """Title words minus stopwords and words shorter than two characters."""
    return [
        word
        for word in _WORD_RE.findall(title.lower())
        if len(word) >= 2 and word not in _STOPWORDS
    ]


def _compact(text: str) -> str:
    return _NON_ALNUM_RE.sub("", text.lower())


def _initials(text: str) -> str:
    return "".join(word[0] for word in _WORD_RE.findall(text.lower()))


def _side_matches(side: str, note: ModelNote) -> bool:
    """Whether one "A vs B" title side refers to the given note."""
    side_lower = side.lower()
    tags = [tag for tag in note.tags if tag.lower() not in GENERIC_TAGS]
    for tag in tags:
        tag_lower = tag.lower()
        if tag_lower in side_lower or tag_lower.replace("-", " ") in side_lower:
            return True
    words = _significant_words(note.title)
    if words and all(word in side_lower for word in words):
        return True
    side_compact = _compact(side)
    if not side_compact:
        return False
    if side_compact == _initials(note.title):
        return True
    return any(
        "-" in tag and side_compact == _initials(tag.replace("-", " "))
        for tag in tags
    )


def find_comparison_note(notes: list[ModelNote], a: ModelNote, b: ModelNote) -> ModelNote | None:
    """First note (in scan order) whose "A vs B" title compares a and b."""
    for note in notes:
        if note is a or note is b:
            continue
        if not _VS_RE.search(note.title):
            continue
        sides = [side.strip() for side in _VS_RE.split(note.title) if side.strip()]
        if len(sides) != 2:
            continue
        left, right = sides
        if (_side_matches(left, a) and _side_matches(right, b)) or (
            _side_matches(left, b) and _side_matches(right, a)
        ):
            return note
    return None
