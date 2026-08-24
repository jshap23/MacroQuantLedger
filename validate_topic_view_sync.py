"""Standalone validation script for TopicView <-> Obsidian Markdown sync.

Run with: python validate_topic_view_sync.py

All scenarios use temporary directories; the live Obsidian vault and app data are
never touched.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from models.schema import AppState, TopicView, ViewFact, ViewPoint, _now_utc
from storage.topic_view_markdown import note_filename, parse_topic_view, render_topic_view
from storage.topic_view_sync import (
    SyncRecord,
    SyncState,
    resolve_conflict,
    set_sync_enabled,
    sync_topic_views,
)
from storage import topic_view_sync as sync_mod

SAMPLE_MARKDOWN = """---
view_id: view-abc-123
title: "US Labor"
type: view
status: developing
priority: normal
tags:
  - views
  - macro
aliases:
  - Labor Market
cssclasses:
  - some-class
---

# US Labor

## My View

The U.S. labor market is in a low-hire, low-fire equilibrium.

## Why

1. Labor demand is weak but not collapsing.
2. Labor supply is also growing very slowly.
3. Growth is increasingly capital/productivity intensive.

## Watch

- Initial claims
- Hiring rate
- Payroll growth
"""


def _temp_state_file():
    tmp = Path(tempfile.mkdtemp())
    return tmp / "topic_view_sync.json"


def _patch_state_file(tmp_file: Path):
    sync_mod.SYNC_STATE_FILE = tmp_file
    if tmp_file.exists():
        tmp_file.unlink()


def _make_view() -> TopicView:
    return TopicView(
        id="view-abc-123",
        name="US Labor",
        bottom_line="The labor market is stable.",
        points=[ViewPoint(title="Point one"), ViewPoint(title="Point two")],
        watch=["Claims", "Payrolls"],
        counterargument="A recession would change this.",
        changes_my_mind="Claims above 300k.",
        status="Developing",
        priority="Core",
    )


def test_parse() -> None:
    parsed = parse_topic_view(SAMPLE_MARKDOWN)
    view = parsed.view
    assert view.id == "view-abc-123"
    assert view.name == "US Labor"
    assert "low-hire, low-fire" in view.bottom_line
    assert len(view.points) == 3
    assert view.points[0].title == "Labor demand is weak but not collapsing."
    assert view.watch == ["Initial claims", "Hiring rate", "Payroll growth"]
    assert view.status == "Developing"
    assert view.priority == "Normal"
    assert parsed.frontmatter.get("tags") == ["views", "macro"]
    assert parsed.frontmatter.get("aliases") == ["Labor Market"]
    print("PASS: parse")


def test_round_trip() -> None:
    parsed = parse_topic_view(SAMPLE_MARKDOWN)
    view = parsed.view
    view.bottom_line = "Updated bottom line."
    rendered = render_topic_view(view, prior=parsed)
    assert "Updated bottom line." in rendered
    assert "1. Labor demand is weak but not collapsing." in rendered
    assert "views" in rendered
    assert "macro" in rendered
    assert "aliases" in rendered
    assert "cssclasses" in rendered
    re_parsed = parse_topic_view(rendered)
    assert re_parsed.view.bottom_line == "Updated bottom line."
    assert re_parsed.frontmatter.get("aliases") == ["Labor Market"]
    print("PASS: round trip")


def _rich_view() -> TopicView:
    return TopicView(
        id="rich-view-0001",
        name="Term Premium",
        bottom_line="Term premium is too low for the fiscal path.",
        points=[
            ViewPoint(title="Deficits are large", facts=[
                ViewFact(text="Primary deficit near 6% of GDP", source="CBO", as_of="2026-07", note="cycle-adjusted"),
                ViewFact(text="Interest cost exceeds defense spend"),
            ]),
            ViewPoint(title="Supply risk is rising", facts=[
                ViewFact(text="Auction tails widening since spring"),
            ]),
            ViewPoint(title="QT continues"),
        ],
        counterargument="Growth scare would flatten curves first.",
        changes_my_mind="Deficit sustainably below 4% of GDP.",
        watch=["10y auction tails", "Coupon issuance pace"],
        status="Ready",
        priority="Core",
    )


def test_lossless_round_trip() -> None:
    view = _rich_view()
    text_one = render_topic_view(view)
    parsed = parse_topic_view(text_one)
    got = parsed.view
    assert [p.title for p in got.points] == ["Deficits are large", "Supply risk is rising", "QT continues"]
    assert got.points[0].facts[0].text == "Primary deficit near 6% of GDP"
    assert got.counterargument == "Growth scare would flatten curves first."
    assert got.changes_my_mind == "Deficit sustainably below 4% of GDP."
    assert got.watch == ["10y auction tails", "Coupon issuance pace"]
    text_two = render_topic_view(got)
    assert text_two == text_one
    stamp = re.search(r"created_at: '?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'?", text_one)
    assert stamp, "timestamps should be human-readable"
    assert parse_topic_view(text_one).view.created_at.strftime("%Y-%m-%d %H:%M:%S") == stamp.group(1)
    print("PASS: lossless round trip (render->parse->render byte-identical)")


def test_type_property_retired_in_favor_of_view_tag() -> None:
    parsed = parse_topic_view(SAMPLE_MARKDOWN)
    rendered = render_topic_view(parsed.view, prior=parsed)

    assert "type:" not in rendered
    assert re.search(r"^tags:\n(?:- .+\n)+", rendered, flags=re.MULTILINE)
    assert re.search(r"^- view$", rendered, flags=re.MULTILINE)
    assert "- views" in rendered
    assert "- macro" in rendered

    tagless = parse_topic_view(
        "---\nview_id: t-1\ntitle: T\n---\n\n# T\n\n## My View\n\nx\n"
    )
    rendered_two = render_topic_view(tagless.view, prior=tagless)
    assert "type:" not in rendered_two
    assert re.search(r"^tags:\n- view$", rendered_two, flags=re.MULTILINE)
    print("PASS: type property retired; 'view' tag always present, custom tags kept")


def test_foreign_content_preserved_verbatim() -> None:
    note = (
        "---\n"
        "view_id: keep-1\n"
        "type: view\n"
        "tags:\n  - macro\n"
        "---\n"
        "\n"
        "# Keep Test\n"
        "\n"
        "Personal intro prose that must survive.\n"
        "\n"
        "## My View\n"
        "\n"
        "Original bottom.\n"
        "\n"
        "## Evidence Log\n"
        "\n"
        "- custom bullet one\n"
        "- embed ![[chart.png]]\n"
        "\n"
        "## Why\n"
        "\n"
        "1. Point A\n"
        "\n"
        "## Random Thoughts\n"
        "\n"
        "Free-form musing paragraph.\n"
        "\n"
        "## Watch\n"
        "\n"
        "- W1\n"
    )
    parsed = parse_topic_view(note)
    view = parsed.view
    view.bottom_line = "Edited bottom."
    out = render_topic_view(view, prior=parsed)

    assert "Personal intro prose that must survive." in out
    assert "- custom bullet one" in out and "![[chart.png]]" in out
    assert "Free-form musing paragraph." in out
    assert "Edited bottom." in out
    assert out.index("## Evidence Log") < out.index("## Why") < out.index("## Random Thoughts")

    reparsed = parse_topic_view(out)
    assert reparsed.view.name == "Keep Test"
    assert reparsed.view.points[0].title == "Point A"
    print("PASS: foreign body content preserved verbatim and in position")


def test_vault_edit_preserves_facts_and_metadata() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        state = AppState(topic_views=[_rich_view()])
        sync_topic_views(state, vault_path)

        note = vault_path / "Term Premium.md"
        content = note.read_text(encoding="utf-8")
        assert "   - Primary deficit near 6% of GDP" in content

        edited = content.replace("too low for the fiscal path", "quite low given the path")
        note.write_text(edited, encoding="utf-8")

        result = sync_topic_views(state, vault_path)
        assert result.imported == ["Term Premium"]

        point = state.topic_views[0].points[0]
        assert point.title == "Deficits are large"
        assert len(point.facts) == 2
        assert point.facts[0].text == "Primary deficit near 6% of GDP"
        assert point.facts[0].source == "CBO"
        assert point.facts[0].as_of == "2026-07"
        assert point.facts[0].note == "cycle-adjusted"

        follow_up = sync_topic_views(state, vault_path)
        assert not any([follow_up.conflicts, follow_up.imported, follow_up.exported])
        print("PASS: vault edit preserves facts and their metadata")


def test_counter_and_changes_sections_sync() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        state = AppState(topic_views=[_rich_view()])
        sync_topic_views(state, vault_path)

        note = vault_path / "Term Premium.md"
        content = note.read_text(encoding="utf-8")
        assert "## Counterargument" in content
        assert "What Changes My Mind" in content

        duplicate = content + "\n## Counterargument\n\nVault-side objection.\n"
        note.write_text(duplicate, encoding="utf-8")
        result = sync_topic_views(state, vault_path)
        assert any("duplicate owned section" in e and "Counterargument" in e for e in result.errors)
        assert note.read_text(encoding="utf-8") == duplicate
        assert state.topic_views[0].counterargument == "Growth scare would flatten curves first."

        fixed = duplicate.replace(
            "## Counterargument\nGrowth scare would flatten curves first.\n\n",
            "",
            1,
        )
        note.write_text(fixed, encoding="utf-8")
        result = sync_topic_views(state, vault_path)
        assert result.imported == ["Term Premium"]
        assert state.topic_views[0].counterargument == "Vault-side objection."
        assert state.topic_views[0].changes_my_mind == "Deficit sustainably below 4% of GDP."

        state.topic_views[0].changes_my_mind = "App-side trigger."
        state.topic_views[0].updated_at = _now_utc()
        follow_up = sync_topic_views(state, vault_path)
        assert not follow_up.errors
        final_text = note.read_text(encoding="utf-8")
        assert "App-side trigger." in final_text
        assert "Vault-side objection." in final_text
        print("PASS: counterargument / changes-my-mind sync, duplicates fail closed")


def test_duplicate_owned_sections_fail_closed() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        ambiguous = (
            "---\n"
            "view_id: dup-1\n"
            "type: view\n"
            "---\n"
            "\n"
            "# Dup\n"
            "\n"
            "## My View\n"
            "\n"
            "bottom here\n"
            "\n"
            "## Why\n"
            "\n"
            "1. First version\n"
            "   - keep me\n"
            "\n"
            "## Why\n"
            "\n"
            "1. Second version\n"
            "   - keep me\n"
        )
        note = vault_path / "Dup.md"
        note.write_text(ambiguous, encoding="utf-8")

        view = TopicView(
            id="dup-1",
            name="Dup",
            points=[ViewPoint(title="App original", facts=[
                ViewFact(text="keep me", source="SRC", as_of="2026-01"),
            ])],
        )
        state = AppState(topic_views=[view])

        result = sync_topic_views(state, vault_path)
        assert any("duplicate owned section" in e and "Why" in e for e in result.errors)
        assert not any([result.imported, result.exported, result.created, result.conflicts])
        assert note.read_text(encoding="utf-8") == ambiguous
        assert state.topic_views[0].points[0].title == "App original"
        assert state.topic_views[0].points[0].facts[0].source == "SRC"

        resolution = resolve_conflict(state, "dup-1", "vault", vault_path)
        assert resolution.errors

        fixed = ambiguous.replace("## Why\n\n1. First version\n   - keep me\n\n", "", 1)
        note.write_text(fixed, encoding="utf-8")
        result = sync_topic_views(state, vault_path)
        assert not result.errors
        assert state.topic_views[0].points[0].title == "Second version"
        assert state.topic_views[0].points[0].facts[0].source == "SRC"

        follow_up = sync_topic_views(state, vault_path)
        assert not any([follow_up.errors, follow_up.imported, follow_up.exported])
        print("PASS: duplicate owned sections fail closed until manually resolved")


def test_pre_migration_backup_and_recovery() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        backup_root = Path(vault) / "backups"
        sync_mod.BACKUP_ROOT = backup_root

        state = AppState(topic_views=[_rich_view()])
        sync_topic_views(state, vault_path)
        note = vault_path / "Term Premium.md"
        upgraded_bytes = note.read_text(encoding="utf-8")
        assert not backup_root.exists()

        legacy = SyncState(
            format_version=1,
            enabled=True,
            folder=str(vault_path),
            records={
                "rich-view-0001": SyncRecord(
                    view_id="rich-view-0001",
                    rel_path="Term Premium.md",
                    content_hash="legacy",
                    view_updated_at=_now_utc(),
                )
            },
        )
        tmp_state.write_text(legacy.model_dump_json(), encoding="utf-8")

        result = sync_topic_views(state, vault_path)
        assert any("Pre-migration backup saved" in w for w in result.warnings)
        backup_dirs = list(backup_root.glob("pre_migration_*"))
        assert len(backup_dirs) == 1
        backup = backup_dirs[0]
        assert (backup / "notes" / "Term Premium.md").read_text(encoding="utf-8") == upgraded_bytes
        assert (backup / "topic_view_sync.json").exists()
        assert (backup / "MANIFEST.txt").exists()

        persisted = sync_mod.load_sync_state()
        assert persisted.format_version == sync_mod.FORMAT_VERSION
        migrated_bytes = note.read_text(encoding="utf-8")
        assert "   - Primary deficit near 6% of GDP" in migrated_bytes

        def body(text: str) -> str:
            return text.split("---", 2)[-1]

        shutil.copy2(backup / "notes" / "Term Premium.md", note)
        shutil.copy2(backup / "topic_view_sync.json", tmp_state)
        assert note.read_text(encoding="utf-8") == upgraded_bytes

        rerun = sync_topic_views(state, vault_path)
        assert not rerun.errors
        assert any("Pre-migration backup saved" in w for w in rerun.warnings)
        assert len(list(backup_root.glob("pre_migration_*"))) == 2
        assert body(note.read_text(encoding="utf-8")) == body(migrated_bytes)
        print("PASS: pre-migration backup created once per upgrade and recovery round-trips")


def test_missing_owned_sections_do_not_wipe_app_fields() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        note = vault_path / "Sparse.md"
        note.write_text(
            "---\n"
            f"view_id: sparse-1\n"
            "type: view\n"
            "---\n"
            "\n"
            "# Sparse\n"
            "\n"
            "## My View\n"
            "\n"
            "Only a bottom line here.\n",
            encoding="utf-8",
        )

        state = AppState(topic_views=[_rich_view()])
        state.topic_views[0].id = "sparse-1"
        result = sync_topic_views(state, vault_path)
        assert result.imported == ["Term Premium"] or result.imported

        view = state.topic_views[0]
        assert view.bottom_line == "Only a bottom line here."
        assert len(view.points) == 3
        assert view.points[0].facts[0].source == "CBO"
        assert view.counterargument == "Growth scare would flatten curves first."
        assert view.watch == ["10y auction tails", "Coupon issuance pace"]

        rewritten = note.read_text(encoding="utf-8")
        assert "   - Primary deficit near 6% of GDP" in rewritten
        print("PASS: missing owned sections never wipe app-only data")


def test_new_obsidian_note_gets_id() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        note = vault_path / "missing_id.md"
        note.write_text(
            "---\n"
            "type: view\n"
            "status: ready\n"
            "priority: core\n"
            "tags:\n  - macro\n"
            "---\n\n"
            "# Inflation\n\n"
            "## My View\n\nInflation is falling.\n\n"
            "## Why\n\n1. Goods deflation.\n\n"
            "## Watch\n\n- CPI\n",
            encoding="utf-8",
        )

        state = AppState(topic_views=[])
        result = sync_topic_views(state, vault_path)
        assert len(state.topic_views) == 1
        view = state.topic_views[0]
        assert view.name == "Inflation"
        assert view.status == "Ready"
        assert view.priority == "Core"
        assert len(view.id) > 8

        # File should have been rewritten with the assigned id.
        content = note.read_text(encoding="utf-8")
        assert f"view_id: {view.id}" in content
        print("PASS: new Obsidian note gets id")


def test_app_edit_pushes_to_vault() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        state = AppState(topic_views=[_make_view()])
        # First sync creates the file, named after the view title.
        sync_topic_views(state, vault_path)
        assert (vault_path / "US Labor.md").exists()

        # Edit in the app.
        state.topic_views[0].bottom_line = "App-edited bottom line."
        state.topic_views[0].updated_at = _now_utc()
        result = sync_topic_views(state, vault_path)

        file_path = vault_path / "US Labor.md"
        content = file_path.read_text(encoding="utf-8")
        assert "App-edited bottom line." in content
        print("PASS: app edit pushes to vault")


def test_external_edit_pulls_to_app() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        view = _make_view()
        state = AppState(topic_views=[view])
        sync_topic_views(state, vault_path)  # establish baseline

        # Edit the markdown file directly.
        file_path = vault_path / "US Labor.md"
        content = file_path.read_text(encoding="utf-8")
        content = content.replace("The labor market is stable.", "Vault-edited bottom line.")
        file_path.write_text(content, encoding="utf-8")

        result = sync_topic_views(state, vault_path)
        assert state.topic_views[0].bottom_line == "Vault-edited bottom line."
        assert state.topic_views[0].counterargument == "A recession would change this."
        print("PASS: external edit pulls to app")


def test_conflict_detected() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        view = _make_view()
        state = AppState(topic_views=[view])
        sync_topic_views(state, vault_path)  # baseline

        # Change both sides.
        original_bottom = view.bottom_line
        state.topic_views[0].bottom_line = "App change."
        state.topic_views[0].updated_at = _now_utc()
        file_path = vault_path / "US Labor.md"
        content = file_path.read_text(encoding="utf-8")
        content = content.replace(original_bottom, "Vault change.")
        file_path.write_text(content, encoding="utf-8")

        result = sync_topic_views(state, vault_path)
        assert result.conflicts
        assert state.topic_views[0].bottom_line == "App change."
        assert "Vault change." not in state.topic_views[0].bottom_line
        print("PASS: conflict detected")


def test_disabled_sync_leaves_state_untouched() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(False)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        (vault_path / "inflation.md").write_text("# Inflation\n\n## My View\n\nRising.\n", encoding="utf-8")
        state = AppState(topic_views=[_make_view()])
        result = sync_topic_views(state, vault_path)
        assert len(state.topic_views) == 1
        assert state.topic_views[0].name == "US Labor"
        assert not (vault_path / note_filename("US Labor")).exists()
        print("PASS: disabled sync leaves state untouched")


def test_app_title_rename_moves_file() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        view = _make_view()
        state = AppState(topic_views=[view])
        sync_topic_views(state, vault_path)  # creates US Labor.md
        old_file = vault_path / "US Labor.md"
        assert old_file.exists()

        state.topic_views[0].name = "US Jobs"
        state.topic_views[0].updated_at = _now_utc()
        result = sync_topic_views(state, vault_path)
        assert not result.errors
        new_file = vault_path / "US Jobs.md"
        assert new_file.exists()
        assert not old_file.exists()
        assert f"view_id: {view.id}" in new_file.read_text(encoding="utf-8")

        follow_up = sync_topic_views(state, vault_path)
        assert not any([follow_up.conflicts, follow_up.exported, follow_up.imported])
        print("PASS: app title rename moves the note file")


def test_duplicate_titles_get_distinct_files() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        first = TopicView(name="Alpha", bottom_line="First.")
        second = TopicView(name="Alpha", bottom_line="Second.")
        state = AppState(topic_views=[first, second])
        sync_topic_views(state, vault_path)

        files = sorted(p for p in vault_path.glob("*.md"))
        assert len(files) == 2
        all_text = "".join(p.read_text(encoding="utf-8") for p in files)
        assert f"view_id: {first.id}" in all_text
        assert f"view_id: {second.id}" in all_text
        print("PASS: duplicate titles get distinct files")


def test_keep_vault_with_friendly_filename() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        view = _make_view()
        state = AppState(topic_views=[view])
        sync_topic_views(state, vault_path)

        friendly_name = vault_path / "US Labor.md"
        assert friendly_name.exists()

        original_bottom = view.bottom_line
        state.topic_views[0].bottom_line = "App change."
        state.topic_views[0].updated_at = _now_utc()
        content = friendly_name.read_text(encoding="utf-8").replace(original_bottom, "Vault change.")
        friendly_name.write_text(content, encoding="utf-8")

        result = sync_topic_views(state, vault_path)
        assert result.conflicts == [view.name]

        resolution = resolve_conflict(state, view.id, "vault", vault_path)
        assert not resolution.errors
        assert resolution.imported == [view.name]
        assert state.topic_views[0].bottom_line == "Vault change."

        resolved_text = friendly_name.read_text(encoding="utf-8")
        assert "Vault change." in resolved_text

        follow_up = sync_topic_views(state, vault_path)
        assert not follow_up.conflicts
        assert not follow_up.exported and not follow_up.imported and not follow_up.created
        print("PASS: keep vault resolves and stays resolved")


def test_missing_file_keep_vault_reports_error() -> None:
    tmp_state = _temp_state_file()
    _patch_state_file(tmp_state)
    set_sync_enabled(True)

    with tempfile.TemporaryDirectory() as vault:
        vault_path = Path(vault)
        view = _make_view()
        state = AppState(topic_views=[view])
        sync_topic_views(state, vault_path)

        (vault_path / "US Labor.md").unlink()
        result = sync_topic_views(state, vault_path)
        assert result.conflicts == [view.name]

        app_copy = state.topic_views[0].bottom_line
        resolution = resolve_conflict(state, view.id, "vault", vault_path)
        assert resolution.errors
        assert state.topic_views[0].bottom_line == app_copy

        still = sync_topic_views(state, vault_path)
        assert still.conflicts == [view.name]
        print("PASS: missing file keep-vault reports error instead of silent no-op")


def main() -> None:
    print("Validating TopicView <-> Obsidian Markdown sync...\n")
    test_parse()
    test_round_trip()
    test_lossless_round_trip()
    test_type_property_retired_in_favor_of_view_tag()
    test_foreign_content_preserved_verbatim()
    test_new_obsidian_note_gets_id()
    test_app_edit_pushes_to_vault()
    test_external_edit_pulls_to_app()
    test_vault_edit_preserves_facts_and_metadata()
    test_counter_and_changes_sections_sync()
    test_missing_owned_sections_do_not_wipe_app_fields()
    test_duplicate_owned_sections_fail_closed()
    test_pre_migration_backup_and_recovery()
    test_conflict_detected()
    test_disabled_sync_leaves_state_untouched()
    test_app_title_rename_moves_file()
    test_duplicate_titles_get_distinct_files()
    test_keep_vault_with_friendly_filename()
    test_missing_file_keep_vault_reports_error()
    print("\nAll validation scenarios passed.")


if __name__ == "__main__":
    main()
