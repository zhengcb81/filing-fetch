"""Regression tests for completed-phase plan scoping."""

from tools.verify_plan_claims import parse_plan


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
