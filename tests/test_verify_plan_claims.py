"""Regression tests for completed-phase plan scoping."""

import hashlib
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


def test_manifest_with_matching_digest_pins_the_archived_bytes(tmp_path):
    """With a pinned sha256 the exemption is bound to the archived bytes."""
    plan = _write_plan(tmp_path, "archive-input/w06")
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({
            "scope": "A0 archive",
            "files": [{"path": "w06/task_plan.md", "sha256": digest}],
        }),
        encoding="utf-8",
    )

    assert _archived_by_manifest(plan) is True

    # An edited snapshot no longer matches its pinned digest: the archived
    # status is refused, so the plan is verified like any other.
    plan.write_text("## Phase 1 — Edited — 状态：completed\n- [x] Task\n", encoding="utf-8")
    assert _archived_by_manifest(plan) is False


def test_pinned_digest_is_honored_across_line_endings(tmp_path):
    """A pin taken over another line-ending form still identifies the content."""
    plan = _write_plan(tmp_path, "archive-input/w06")
    lf = plan.read_bytes().replace(b"\r\n", b"\n")
    crlf_digest = hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({
            "scope": "A0 archive",
            "files": [{"path": "w06/task_plan.md", "sha256": crlf_digest}],
        }),
        encoding="utf-8",
    )

    assert _archived_by_manifest(plan) is True


def test_unreadable_manifests_grant_no_exemption(tmp_path):
    """A manifest this process cannot parse never grants an exemption."""
    plan = _write_plan(tmp_path, "archive-input/w06")
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"

    manifest.write_bytes(b"\xff\xfe\x00not-utf8")
    assert _archived_by_manifest(plan) is False

    manifest.write_text("{not json", encoding="utf-8")
    assert _archived_by_manifest(plan) is False

    manifest.write_text(json.dumps({"scope": "A0 archive"}), encoding="utf-8")
    assert _archived_by_manifest(plan) is False

    manifest.write_text(json.dumps({"files": "w06/task_plan.md"}), encoding="utf-8")
    assert _archived_by_manifest(plan) is False

    manifest.write_text(json.dumps({"files": ["w06/task_plan.md"]}), encoding="utf-8")
    assert _archived_by_manifest(plan) is False


def test_manifest_above_the_verified_root_is_not_consulted(tmp_path):
    """Only manifests inside the verified tree can grant an exemption."""
    plan = _write_plan(tmp_path, "tree/archive-input/w06")
    manifest = tmp_path / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({
            "scope": "A0 archive",
            "files": [{"path": "tree/archive-input/w06/task_plan.md"}],
        }),
        encoding="utf-8",
    )

    assert _archived_by_manifest(plan, root=tmp_path / "tree") is False
    assert _archived_by_manifest(plan) is True


def test_declared_path_separators_and_case_are_normalised(tmp_path):
    """A manifest written with backslashes names the same archived file."""
    plan = _write_plan(tmp_path, "archive-input/w06")
    manifest = tmp_path / "archive-input" / "ARCHIVE_MANIFEST.json"
    manifest.write_text(
        json.dumps({"scope": "A0 archive", "files": [{"path": "w06\\task_plan.md"}]}),
        encoding="utf-8",
    )

    assert _archived_by_manifest(plan) is True
