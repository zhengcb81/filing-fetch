"""Regression tests for completed-phase plan scoping."""

import json
from pathlib import Path

from tools.verify_plan_claims import _archived_by_manifest, parse_plan


def test_new_section_todos_do_not_attach_to_previous_completed_phase():
    plan = """
## Phase 6 — Historical work — 状态：completed
- [x] Historical task
### Nested evidence
- [x] Checked subtask

## 2026-10-03 Cross-project integration addendum
- [ ] Pending integration delivery
"""

    assert parse_plan(plan) == [
        {"number": 6, "unchecked": 0, "has_waiver": False},
    ]


def _write_plan(root: Path, relative: str) -> Path:
    plan = root / relative / "task_plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "## Phase 1 — Archived work — 状态：completed\n- [x] Historical task\n",
        encoding="utf-8",
    )
    (plan.parent / "progress.md").write_text("progress\n", encoding="utf-8")
    return plan


def test_manifest_declared_archive_plan_is_exempt(tmp_path):
    """A plan an archive manifest declares an archived input is not active."""
    plan = _write_plan(tmp_path, "archive-input/w06")
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({"scope": "A0 archive", "files": [{"path": "w06/task_plan.md"}]}),
        encoding="utf-8",
    )

    assert _archived_by_manifest(plan) is True


def test_undeclared_plan_is_not_exempt(tmp_path):
    """Without a manifest declaration the plan stays an active plan."""
    plan = _write_plan(tmp_path, "archive-input/w06")
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({"scope": "A0 archive", "files": [{"path": "w07/task_plan.md"}]}),
        encoding="utf-8",
    )

    assert _archived_by_manifest(plan) is False


def test_manifest_exemption_does_not_cover_sibling_plans(tmp_path):
    """A manifest that archives one plan never exempts another one."""
    archived = _write_plan(tmp_path, "archive-input/w06")
    other = _write_plan(tmp_path, "archive-input/w07")
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({"scope": "A0 archive", "files": [{"path": "w06/task_plan.md"}]}),
        encoding="utf-8",
    )

    assert _archived_by_manifest(archived) is True
    assert _archived_by_manifest(other) is False
