"""Bidirectional synchronization between AppState TopicViews and Obsidian Markdown notes."""
from __future__ import annotations

import shutil
import threading
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from models.schema import AppState, TopicView, ViewFact, ViewPoint, _now_utc
from storage import persistence as _persistence
from storage.topic_view_markdown import (
    CANONICAL_HEADINGS,
    MarkdownTopicView,
    note_filename,
    parse_topic_view,
    render_topic_view,
    topic_view_content_hash,
    write_topic_view,
)
from storage.user_settings import obsidian_views_folder

SYNC_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "topic_view_sync.json"
BACKUP_ROOT = Path(__file__).resolve().parent.parent / "data" / "backups"
FORMAT_VERSION = 3
_LOCK = threading.RLock()


def _backup_before_migration(folder: Path) -> tuple[bool, str]:
    """Copy every vault note plus state/sync-state files to a timestamped dir.

    Called once when a sync-state format mismatch is detected, before any note
    is modified. On partial failure the copied files are kept and the caller
    must abort without writing anything.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    dest = BACKUP_ROOT / f"pre_migration_{stamp}"
    notes_dir = dest / "notes"
    try:
        notes_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for src in sorted(folder.glob("*.md")):
            shutil.copy2(src, notes_dir / src.name)
            count += 1
        if _persistence.STATE_FILE.exists():
            shutil.copy2(_persistence.STATE_FILE, dest / "state.json")
        if SYNC_STATE_FILE.exists():
            shutil.copy2(SYNC_STATE_FILE, dest / "topic_view_sync.json")
        manifest = "\n".join([
            "Pre-migration backup",
            f"Created: {datetime.now(timezone.utc).isoformat()}",
            f"Notes copied: {count}",
            "",
            "To recover: copy notes/*.md back into the Obsidian Views folder and",
            "topic_view_sync.json back into data/, then restart the app.",
        ])
        (dest / "MANIFEST.txt").write_text(manifest, encoding="utf-8")
        return True, str(dest)
    except OSError as exc:
        return False, f"{exc} (partial backup preserved at {dest})"


class SyncRecord(BaseModel):
    view_id: str
    rel_path: str
    content_hash: str
    view_hash: str = ""
    view_updated_at: datetime
    status: str = "clean"


class SyncState(BaseModel):
    format_version: int = FORMAT_VERSION
    enabled: bool = False
    folder: str | None = None
    records: dict[str, SyncRecord] = Field(default_factory=dict)


class SyncResult(BaseModel):
    imported: list[str] = Field(default_factory=list)
    exported: list[str] = Field(default_factory=list)
    created: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def has_changes(self) -> bool:
        return bool(self.imported or self.exported or self.created or self.conflicts or self.errors)


class SyncDecision(BaseModel):
    """One reviewable difference between the app and the vault.

    `key` is the view_id, or ``path:<filename>`` for vault notes that do not
    carry an adopted id yet. `vault_hash` pins the note bytes seen at plan
    time so apply can refuse to act on files that changed since review.
    """
    key: str
    view_id: str = ""
    name: str
    action: str  # EXPORT | IMPORT | CREATE | CONFLICT
    filename: str = ""
    vault_hash: str = ""
    detail: str = ""
    app_updated_at: Optional[datetime] = None
    vault_updated_at: Optional[datetime] = None
    app_points: int = 0
    vault_points: int = 0
    app_bottom_line: str = ""
    vault_bottom_line: str = ""


class SyncPlan(BaseModel):
    decisions: list[SyncDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def load_sync_state() -> SyncState:
    """Return the persisted state verbatim, including a stale format_version.

    Version detection is the migration gate's job: it must see the raw value
    to know a pre-migration backup is required before anything is written.
    """
    with _LOCK:
        try:
            raw = SYNC_STATE_FILE.read_text(encoding="utf-8")
            return SyncState.model_validate_json(raw)
        except (FileNotFoundError, ValueError, OSError):
            return SyncState()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def save_sync_state(state: SyncState) -> None:
    with _LOCK:
        SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = SYNC_STATE_FILE.with_suffix(".tmp")
        temp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(SYNC_STATE_FILE)


def sync_is_enabled() -> bool:
    return load_sync_state().enabled


def set_sync_enabled(enabled: bool) -> None:
    state = load_sync_state()
    state.enabled = enabled
    save_sync_state(state)


def _record_for(state: SyncState, view_id: str) -> SyncRecord | None:
    return state.records.get(view_id)


def _vault_fallback(folder: Path, view_id: str) -> Path:
    return folder / f"{view_id}.md"


def _scan_vault(
    folder: Path,
    records: dict[str, SyncRecord] | None = None,
    write_back: bool = True,
) -> tuple[dict[str, MarkdownTopicView], dict[str, str], list[str], list[dict]]:
    """Scan folder for Markdown notes keyed by frontmatter view_id.

    Notes with duplicate owned sections are unsafe: they are excluded from all
    sync decisions (and never adopted/rewritten) and returned for reporting.
    With ``write_back=False`` (read-only planning) notes lacking a view id are
    NOT adopted; they are indexed under a ``path:<filename>`` pseudo key so a
    plan can reference them without touching the file.
    Returns (found, occupied, warnings, unsafe).
    """
    found: dict[str, MarkdownTopicView] = {}
    occupied: dict[str, str] = {}
    warnings: list[str] = []
    unsafe: list[dict] = []
    candidates: dict[str, list[tuple[Path, str]]] = {}

    if not folder.exists():
        return found, occupied, warnings, unsafe

    for path in sorted(folder.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            parsed = parse_topic_view(text, path)
        except (OSError, ValueError):
            continue
        if parsed.ambiguous:
            occupied[path.name.lower()] = parsed.view.id
            unsafe.append({
                "path": path,
                "view_id": str(parsed.frontmatter.get("view_id") or parsed.frontmatter.get("id") or "").strip(),
                "duplicates": list(parsed.ambiguous),
            })
            continue
        try:
            if not (parsed.frontmatter.get("view_id") or parsed.frontmatter.get("id")):
                if not write_back:
                    pseudo = f"path:{path.name}"
                    candidates.setdefault(pseudo, []).append((path, text))
                    occupied[path.name.lower()] = pseudo
                    continue
                write_topic_view(parsed.view, path, prior=parsed)
                text = path.read_text(encoding="utf-8")
                parsed = parse_topic_view(text, path)
            candidates.setdefault(parsed.view.id, []).append((path, text))
            occupied[path.name.lower()] = parsed.view.id
        except (OSError, ValueError):
            continue

    for view_id, items in candidates.items():
        record = records.get(view_id) if records else None
        chosen: tuple[Path, str] | None = None
        if record is not None:
            chosen = next(((p, t) for p, t in items if p.name == record.rel_path), None)
        if chosen is None:
            chosen = max(items, key=lambda item: item[0].stat().st_mtime)
        if len(items) > 1:
            names = ", ".join(p.name for p, _ in items)
            warnings.append(f"Multiple notes declare view_id {view_id} ({names}); using {chosen[0].name}.")
        try:
            found[view_id] = parse_topic_view(chosen[1], chosen[0])
        except ValueError:
            continue
    return found, occupied, warnings, unsafe


def _fingerprint(view: TopicView, parsed: MarkdownTopicView | None) -> str:
    return topic_view_content_hash(render_topic_view(view, prior=parsed))


def _remap(old_objs: list, new_keys: list[str], get_key, make_new, update):
    """Align existing objects onto a new key sequence without losing identity.

    Tiers: identical order -> in-place; pure reorder -> reuse by key;
    structural change -> SequenceMatcher blocks with exact-key salvage.
    """
    old_keys = [get_key(o) for o in old_objs]
    if old_keys == new_keys:
        for o, k in zip(old_objs, new_keys):
            update(o, k)
        return list(old_objs)
    if sorted(old_keys) == sorted(new_keys):
        pool: dict[str, list] = {}
        for o in old_objs:
            pool.setdefault(get_key(o), []).append(o)
        out = []
        for k in new_keys:
            o = pool[k].pop(0)
            update(o, k)
            out.append(o)
        return out
    matcher = SequenceMatcher(a=old_keys, b=new_keys, autojunk=False)
    available = dict(enumerate(old_objs))
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                o = available.pop(i1 + offset)
                update(o, new_keys[j1 + offset])
                out.append(o)
        else:
            window = [available.pop(idx) for idx in range(i1, i2) if idx in available]
            if len(window) == 1 and j2 - j1 == 1:
                o = window[0]
                update(o, new_keys[j1])
                out.append(o)
                continue
            for j in range(j1, j2):
                k = new_keys[j]
                match_at = next((n for n, o in enumerate(window) if get_key(o) == k), None)
                if match_at is not None:
                    o = window.pop(match_at)
                    update(o, k)
                    out.append(o)
                else:
                    out.append(make_new(k))
    return out


def _merge_points(view: TopicView, incoming: list[ViewPoint]) -> None:
    merged = _remap(
        view.points,
        [p.title for p in incoming],
        lambda p: p.title,
        lambda t: ViewPoint(title=t),
        lambda p, t: setattr(p, "title", t),
    )
    for point, source in zip(merged, incoming):
        point.facts = _remap(
            point.facts,
            [f.text for f in source.facts],
            lambda f: f.text,
            lambda t: ViewFact(text=t),
            lambda f, t: setattr(f, "text", t),
        )
    view.points = merged


def _apply_vault_to_view(view: TopicView, parsed: MarkdownTopicView) -> None:
    """Merge vault edits into the app view. Sections absent from the note are
    left untouched rather than wiped; aligned points/facts keep their objects,
    so app-only metadata (fact source/as_of/note) survives."""
    src = parsed.view
    view.name = src.name
    if "my view" in parsed.present:
        view.bottom_line = src.bottom_line
    if "why" in parsed.present:
        _merge_points(view, src.points)
    if "watch" in parsed.present:
        view.watch = list(src.watch)
    if "counterargument" in parsed.present:
        view.counterargument = src.counterargument
    if "what changes my mind" in parsed.present:
        view.changes_my_mind = src.changes_my_mind
    view.status = src.status
    view.priority = src.priority
    view.archived = src.archived
    view.tags = list(src.tags)
    view.updated_at = _now_utc()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _note_target(folder: Path, view: TopicView, occupied: dict[str, str]) -> Path:
    base = note_filename(view.name)
    owner = occupied.get(base.lower())
    if owner is not None and owner != view.id:
        base = f"{Path(base).stem} ({view.id[:8]}).md"
    return folder / base


def _export_note(
    folder: Path,
    view: TopicView,
    parsed: MarkdownTopicView | None,
    occupied: dict[str, str],
    record: SyncRecord | None,
) -> tuple[Path, str | None, list[str], list[str]]:
    """Write the app view to its note file.

    Notes are titled after the View. A stale self-named file (one this engine
    wrote under an older title) is renamed; a manually renamed file is kept.
    Returns (target_path, written_content|None, errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []
    current = parsed.path if parsed else None
    canonical = _note_target(folder, view, occupied)

    target = canonical
    old_path: Path | None = None
    if current is not None and current.name.lower() != canonical.name.lower():
        user_renamed = record is None or record.rel_path != current.name
        if user_renamed:
            target = current
        else:
            target = canonical
            old_path = current

    try:
            write_topic_view(view, target, prior=parsed)
    except OSError as exc:
        errors.append(f"Could not write {target.name}: {exc}")
        return target, None, errors, warnings

    if old_path is not None:
        try:
            old_path.unlink()
        except OSError:
            warnings.append(f"Could not remove old note {old_path.name}; you can delete it manually.")
        else:
            occupied.pop(old_path.name.lower(), None)

    content = _read_text(target)
    if content is None:
        errors.append(f"Could not read back {target.name}.")
        return target, content, errors, warnings
    occupied[target.name.lower()] = view.id
    return target, content, errors, warnings


def _decide_action(
    view: TopicView | None,
    parsed: MarkdownTopicView | None,
    record: SyncRecord | None,
    file_content: str | None,
    view_fp: str = "",
) -> str:
    """Return one of: EXPORT, IMPORT, CREATE, CONFLICT, NOOP.

    `content_hash` tracks the note bytes (vault truth); `view_hash` tracks a
    layout-independent canonical render of the app view, so reorganizing or
    annotating a note in Obsidian never masquerades as an app-side change.
    """
    if view is None and parsed is None:
        return "NOOP"
    if view is None:
        return "CREATE" if record is None else "NOOP"
    if parsed is None or file_content is None:
        return "EXPORT" if record is None else "CONFLICT"

    file_hash = topic_view_content_hash(file_content)

    if record is None:
        return "IMPORT"

    remote_changed = bool(file_hash) and file_hash != record.content_hash
    local_changed = bool(view_fp) and view_fp != record.view_hash

    if remote_changed and local_changed:
        return "CONFLICT"
    if remote_changed:
        return "IMPORT"
    if local_changed:
        return "EXPORT"
    return "NOOP"


def _update_record(
    state: SyncState,
    view: TopicView,
    rel_path: str,
    file_content: str,
) -> None:
    state.records[view.id] = SyncRecord(
        view_id=view.id,
        rel_path=rel_path,
        content_hash=topic_view_content_hash(file_content),
        view_hash=_fingerprint(view, None),
        view_updated_at=_ensure_utc(view.updated_at),
        status="clean",
    )


def _migration_gate(sync_state: SyncState, folder: Path, result: SyncResult) -> bool:
    """One-time format migration with a pre-change backup. False aborts callers."""
    if sync_state.format_version == FORMAT_VERSION:
        return True
    ok, detail = _backup_before_migration(folder)
    if not ok:
        result.errors.append(
            f"Pre-migration backup failed; sync aborted and nothing was modified. {detail}"
        )
        return False
    sync_state.records.clear()
    sync_state.format_version = FORMAT_VERSION
    save_sync_state(sync_state)
    result.warnings.append(f"Pre-migration backup saved to {detail}")
    return True


def _resolve_folder(folder: Path | None) -> Path | None:
    if folder is not None:
        return folder
    raw = obsidian_views_folder()
    return Path(raw) if raw else None


def sync_topic_views(state: AppState, folder: Path | None = None) -> SyncResult:
    """Reconcile app state with the Obsidian Views folder and apply safe changes."""
    result = SyncResult()
    sync_state = load_sync_state()

    folder = _resolve_folder(folder)
    if folder is None or not sync_state.enabled:
        return result

    if not folder.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.errors.append(f"Could not create sync folder: {exc}")
            return result

    sync_state.folder = str(folder)

    if not _migration_gate(sync_state, folder, result):
        return result

    vault_views, occupied, scan_warnings, unsafe_notes = _scan_vault(folder, sync_state.records)
    result.warnings.extend(scan_warnings)
    app_index = {view.id: view for view in state.topic_views}

    blocked = {u["view_id"]: u for u in unsafe_notes if u["view_id"]}
    for view_id in set(app_index.keys()) | set(vault_views.keys()):
        if view_id in blocked:
            entry = blocked[view_id]
            name = app_index[view_id].name if view_id in app_index else entry["path"].stem
            dups = ", ".join(entry["duplicates"])
            result.errors.append(
                f"'{name}' ({entry['path'].name}): duplicate owned section(s): {dups}. "
                "Edit the note so each appears once, then Sync Views. File left untouched."
            )
            continue
        view = app_index.get(view_id)
        parsed = vault_views.get(view_id)
        record = _record_for(sync_state, view_id)

        if parsed is not None:
            file_path = parsed.path
        elif view is not None:
            file_path = _note_target(folder, view, occupied)
        else:
            file_path = _vault_fallback(folder, view_id)
        file_content = _read_text(file_path)

        action = _decide_action(
            view,
            parsed,
            record,
            file_content,
            view_fp=_fingerprint(view, None) if view else "",
        )

        if action == "NOOP":
            continue

        if action == "CONFLICT":
            name = view.name if view else (parsed.view.name if parsed else view_id)
            result.conflicts.append(name)
            if record:
                record.status = "conflict"
            continue

        if action == "CREATE":
            new_view = parsed.view
            state.topic_views.append(new_view)
            target = parsed.path or _note_target(folder, new_view, occupied)
            try:
                write_topic_view(new_view, target, prior=parsed)
                written = _read_text(target)
            except OSError as exc:
                result.errors.append(f"Could not write {target.name}: {exc}")
                continue
            if written is None:
                result.errors.append(f"Could not read back {target.name}.")
                continue
            result.created.append(new_view.name)
            occupied[target.name.lower()] = new_view.id
            _update_record(sync_state, new_view, target.name, written)
            continue

        if action == "IMPORT":
            _apply_vault_to_view(view, parsed)
            target = parsed.path or _vault_fallback(folder, view_id)
            try:
                write_topic_view(view, target, prior=parsed)
                written = _read_text(target)
            except OSError as exc:
                result.warnings.append(f"Could not normalize {target.name}: {exc}; using existing note bytes.")
                written = file_content
            result.imported.append(view.name)
            _update_record(sync_state, view, target.name, written or "")
            continue

        if action == "EXPORT":
            target, written, errors, warnings = _export_note(folder, view, parsed, occupied, record)
            result.errors.extend(errors)
            result.warnings.extend(warnings)
            if written is None:
                continue
            result.exported.append(view.name)
            _update_record(sync_state, view, target.name, written)
            continue

    for entry in unsafe_notes:
        if not entry["view_id"] or entry["view_id"] in blocked:
            continue
        dups = ", ".join(entry["duplicates"])
        result.errors.append(
            f"{entry['path'].name}: duplicate owned section(s): {dups}. "
            "Edit the note so each appears once, then Sync Views. File left untouched."
        )

    save_sync_state(sync_state)
    return result


def resolve_conflict(
    state: AppState,
    view_id: str,
    side: str,
    folder: Path | None = None,
) -> SyncResult:
    """Resolve an existing conflict by choosing the app or vault version.

    Locates the note by scanning for its view_id so renamed notes still resolve.
    The winning side is normalized to canonical formatting before recording the
    sync state, so the conflict cannot immediately reappear.
    """
    result = SyncResult()
    sync_state = load_sync_state()

    folder = _resolve_folder(folder)
    if folder is None:
        result.errors.append("No Obsidian Views folder configured.")
        return result

    view = next((v for v in state.topic_views if v.id == view_id), None)

    vault_views, occupied, scan_warnings, unsafe_notes = _scan_vault(folder, sync_state.records)
    result.warnings.extend(scan_warnings)
    parsed = vault_views.get(view_id)
    record = sync_state.records.get(view_id)

    unsafe_entry = next((u for u in unsafe_notes if u["view_id"] == view_id), None)
    if unsafe_entry is not None:
        dups = ", ".join(unsafe_entry["duplicates"])
        result.errors.append(
            f"{unsafe_entry['path'].name}: duplicate owned section(s): {dups}. "
            "Fix the note manually before resolving conflicts. File left untouched."
        )
        return result

    if side == "app":
        if view is None:
            result.errors.append("App view not found.")
            return result
        target, written, errors, warnings = _export_note(folder, view, parsed, occupied, record)
        result.errors.extend(errors)
        result.warnings.extend(warnings)
        if written is None:
            return result
        result.exported.append(view.name)
        _update_record(sync_state, view, target.name, written)
    elif side == "vault":
        if parsed is None:
            result.errors.append(
                "No Obsidian note found for this View. Use Keep App to recreate it."
            )
            return result
        file_path = parsed.path
        if view is None:
            state.topic_views.append(parsed.view)
            target_view = parsed.view
            result.created.append(target_view.name)
        else:
            _apply_vault_to_view(view, parsed)
            target_view = view
            result.imported.append(target_view.name)
        try:
            write_topic_view(target_view, file_path, prior=parsed)
            written = _read_text(file_path)
        except OSError as exc:
            result.errors.append(f"Could not update {file_path.name}: {exc}")
            return result
        _update_record(sync_state, target_view, file_path.name, written or "")
    else:
        result.errors.append(f"Unknown conflict side: {side}")
        return result

    save_sync_state(sync_state)
    return result


def _decision_key(view: TopicView | None, parsed: MarkdownTopicView) -> str:
    if view is not None:
        return view.id
    fm_id = str(parsed.frontmatter.get("view_id") or parsed.frontmatter.get("id") or "").strip()
    return fm_id if fm_id else f"path:{parsed.path.name}"


def _decision_for(
    view: TopicView | None,
    parsed: MarkdownTopicView | None,
    record: SyncRecord | None,
    file_content: str | None,
) -> SyncDecision | None:
    action = _decide_action(
        view,
        parsed,
        record,
        file_content,
        view_fp=_fingerprint(view, None) if view is not None else "",
    )
    if action == "NOOP":
        return None
    key = _decision_key(view, parsed) if parsed is not None else (view.id if view else "")
    missing_note = view is not None and parsed is None
    return SyncDecision(
        key=key,
        view_id="" if key.startswith("path:") else key,
        name=view.name if view is not None else (parsed.view.name if parsed else key),
        action=action,
        filename=parsed.path.name if parsed is not None else (note_filename(view.name) if view else ""),
        vault_hash=topic_view_content_hash(file_content) if file_content else "",
        detail="Note missing in Obsidian" if missing_note else "",
        app_updated_at=_ensure_utc(view.updated_at) if view is not None else None,
        vault_updated_at=_ensure_utc(parsed.view.updated_at) if parsed is not None else None,
        app_points=len(view.points) if view is not None else 0,
        vault_points=len(parsed.view.points) if parsed is not None else 0,
        app_bottom_line=(view.bottom_line or "")[:200] if view is not None else "",
        vault_bottom_line=(parsed.view.bottom_line or "")[:200] if parsed is not None else "",
    )


def plan_sync(state: AppState, folder: Path | None = None) -> SyncPlan:
    """Read-only app-vs-vault diff. Writes nothing: records untouched, notes
    untouched, id-less notes reported under ``path:`` keys rather than adopted.
    Pair with apply_sync_plan, which executes only the approved subset."""
    plan = SyncPlan()
    sync_state = load_sync_state()
    folder = _resolve_folder(folder)
    if folder is None or not sync_state.enabled:
        return plan

    if not _migration_gate(sync_state, folder, plan):
        return plan
    if not folder.exists():
        return plan

    vault_views, _occupied, scan_warnings, unsafe_notes = _scan_vault(
        folder, sync_state.records, write_back=False
    )
    plan.warnings.extend(scan_warnings)
    for entry in unsafe_notes:
        dups = ", ".join(entry["duplicates"])
        plan.errors.append(
            f"{entry['path'].name}: duplicate owned section(s): {dups}. "
            "Edit the note so each appears once; it stays excluded from sync."
        )

    seen: set[str] = set()
    for view in state.topic_views:
        seen.add(view.id)
        parsed = vault_views.get(view.id)
        record = sync_state.records.get(view.id)
        file_content = _read_text(parsed.path) if parsed is not None else None
        decision = _decision_for(view, parsed, record, file_content)
        if decision is not None:
            plan.decisions.append(decision)

    for key, parsed in vault_views.items():
        if key in seen or key.startswith("path:") and _decision_key(None, parsed) in seen:
            continue
        record = sync_state.records.get(key)
        decision = _decision_for(None, parsed, record, _read_text(parsed.path) or "")
        if decision is not None:
            plan.decisions.append(decision)
    return plan


def apply_sync_plan(
    state: AppState,
    decisions: list[SyncDecision],
    choices: dict[str, str],
    folder: Path | None = None,
) -> SyncResult:
    """Execute only the approved subset: choices maps decision.key to 'app'
    (export) or 'vault' (import); missing/'skip' entries stay untouched.
    Each chosen note is re-read and compared with its plan-time hash, so files
    that changed since review are skipped with a warning, never clobbered."""
    result = SyncResult()
    planned = {d.key: d for d in decisions}
    wanted = {k: s for k, s in choices.items() if s in ("app", "vault") and k in planned}
    if not wanted:
        return result

    sync_state = load_sync_state()
    folder = _resolve_folder(folder)
    if folder is None or not sync_state.enabled:
        result.errors.append("Obsidian sync is not configured or is disabled.")
        return result
    if not _migration_gate(sync_state, folder, result):
        return result
    if not folder.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.errors.append(f"Could not create sync folder: {exc}")
            return result

    vault_views, occupied, scan_warnings, unsafe_notes = _scan_vault(
        folder, sync_state.records, write_back=False
    )
    result.warnings.extend(scan_warnings)
    blocked_ids = {u["view_id"] for u in unsafe_notes if u["view_id"]}

    for key, side in wanted.items():
        decision = planned[key]
        view = next((v for v in state.topic_views if v.id == decision.view_id), None)
        parsed = vault_views.get(key)

        file_text: str | None
        if parsed is not None:
            file_text = _read_text(parsed.path)
        elif key.startswith("path:"):
            orphan_path = folder / key[5:]
            file_text = _read_text(orphan_path)
            if file_text is not None:
                try:
                    parsed = parse_topic_view(file_text, orphan_path)
                except ValueError:
                    parsed = None
        else:
            file_text = None

        if side == "app" and view is None:
            result.warnings.append(f"'{decision.name}': no app version to keep; skipped.")
            continue
        if side == "vault" and parsed is None:
            result.warnings.append(f"'{decision.name}': Obsidian note unavailable; skipped.")
            continue
        if decision.view_id and decision.view_id in blocked_ids:
            result.errors.append(
                f"'{decision.name}': note still has duplicate owned sections; fix it first."
            )
            continue

        # Data-loss guard: skip (with a warning) any note whose bytes changed since review.
        if file_text is not None:
            if not decision.vault_hash or topic_view_content_hash(file_text) != decision.vault_hash:
                result.warnings.append(
                    f"'{decision.name}' changed since review; skipped. Run Review & Sync again."
                )
                continue
        elif decision.vault_hash:
            result.warnings.append(
                f"'{decision.name}': Obsidian note disappeared since review; skipped."
            )
            continue

        if side == "app":
            target, written, errors, warnings = _export_note(
                folder, view, parsed, occupied, sync_state.records.get(view.id)
            )
            result.errors.extend(errors)
            result.warnings.extend(warnings)
            if written is None:
                continue
            result.exported.append(view.name)
            _update_record(sync_state, view, target.name, written)
            continue

        file_path = parsed.path
        if view is None:
            target_view = parsed.view
            state.topic_views.append(target_view)
            result.created.append(target_view.name)
        else:
            _apply_vault_to_view(view, parsed)
            target_view = view
            result.imported.append(target_view.name)
        try:
            write_topic_view(target_view, file_path, prior=parsed)
            written = _read_text(file_path)
        except OSError as exc:
            result.errors.append(f"Could not normalize {file_path.name}: {exc}")
            written = _read_text(file_path)
        if written is None:
            result.errors.append(f"Could not read back {file_path.name}.")
            continue
        occupied[file_path.name.lower()] = target_view.id
        _update_record(sync_state, target_view, file_path.name, written)

    save_sync_state(sync_state)
    return result
