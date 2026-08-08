"""Verify that "completed" plan claims are backed by machine evidence (R5, RC-2).

Parses a markdown plan (default: ``task_plan.md``), finds every
``## Phase N（...）— 状态：completed`` section and reports:

1. **Unchecked items**: a completed section with ``[ ]`` items needs an
   explicit ``豁免`` (waiver) note inside the section, else it is a
   name-only completion (N-02/F-11 lesson).
2. **Evidence**: the progress log must mention the phase with a test command
   + pass count + date; a completed claim without evidence is reported.

Exit code 0 = all completed claims backed; 1 = problems found.
``--json`` emits a machine-readable report.  Runs standalone or in CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PHASE_HEADING = re.compile(
    # WU-8.3: company-wiki subplans write "状态：completed ✅（...）"; accept the
    # plain form and the emoji-suffixed form so F-027 conflicts are caught.
    r"^#{2,3}\s+Phase\s+(\d+)[^\n]*—\s*状态：completed(?:\s*[✅✔✓].*)?\s*$",
    re.IGNORECASE,
)
CHECKBOX_UNCHECKED = re.compile(r"\[ \]")
CHECKBOX_CHECKED = re.compile(r"\[x\]")


def parse_plan(plan_text: str) -> list[dict]:
    """Return per-phase: number, unchecked count, has_waiver."""
    phases: list[dict] = []
    current: dict | None = None
    for line in plan_text.splitlines():
        heading = PHASE_HEADING.match(line)
        if heading:
            current = {
                "number": int(heading.group(1)),
                "unchecked": 0,
                "has_waiver": False,
            }
            phases.append(current)
            continue
        if current is None:
            continue
        if CHECKBOX_UNCHECKED.search(line):
            current["unchecked"] += 1
        if "豁免" in line:
            current["has_waiver"] = True
    return phases


def evidence_in_progress(progress_text: str, phase_number: int) -> bool:
    """A phase is evidence-backed when the log mentions it plus a test command,
    a pass count, and a date — the machine-verifiable completion signature."""
    mentions_phase = (
        f"Phase {phase_number}" in progress_text
        or f"phase {phase_number}" in progress_text.lower()
    )
    if not mentions_phase:
        return False
    has_command = bool(re.search(r"pytest|python [\w./-]+\.py", progress_text))
    has_passed = bool(re.search(r"passed|通过|全绿", progress_text))
    has_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", progress_text))
    return has_command and has_passed and has_date


# WU-8.3: a completed phase whose DoD requires a 4-week observation period is
# only valid if the progress evidence date is at least 28 days after the
# completion claim.
MIN_OBSERVATION_DAYS = 28


def _latest_progress_date(progress_text: str) -> str | None:
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", progress_text)
    return dates[-1] if dates else None


def _timed_gate_problems(plan_text: str, progress_text: str) -> list[str]:
    """WU-8.3: a completed phase requiring a 4-week observation period must
    not be claimed before the observation window has elapsed. Also: a file
    that only plans must not simultaneously claim production apply."""
    from datetime import date

    problems: list[str] = []
    latest = _latest_progress_date(progress_text)
    if latest is None:
        return problems
    try:
        latest_d = date.fromisoformat(latest)
    except ValueError:
        return problems
    # find completed phases whose section mentions an observation period
    lines = plan_text.splitlines()
    current_phase: int | None = None
    phase_heading_date: str | None = None
    in_completed = False
    for line in lines:
        heading = PHASE_HEADING.match(line)
        if heading:
            current_phase = int(heading.group(1))
            in_completed = True
            heading_dates = re.findall(r"\d{4}-\d{2}-\d{2}", line)
            phase_heading_date = heading_dates[-1] if heading_dates else None
            # the observation-gated claim may live in the heading itself
            if re.search(r"4\s*周|观察期|观察窗口|observation", line, re.I):
                if phase_heading_date:
                    claimed = date.fromisoformat(phase_heading_date)
                    delta = (latest_d - claimed).days
                    if delta < MIN_OBSERVATION_DAYS:
                        problems.append(
                            f"Phase {current_phase}: observation-gated completion "
                            f"claimed {claimed} but latest evidence is only "
                            f"{delta} days later (need >= {MIN_OBSERVATION_DAYS})"
                        )
            continue
        if current_phase is None:
            continue
        if line.startswith("## "):
            current_phase = None
            in_completed = False
            phase_heading_date = None
            continue
        if not in_completed:
            continue
        if re.search(r"4\s*周|观察期|观察窗口|observation", line, re.I):
            # an observation-gated item is claimed; the evidence date must be
            # >= 28 days after the claim. Use the completion date from the
            # heading (or the gated line) as the claim anchor.
            completion_dates = re.findall(r"\d{4}-\d{2}-\d{2}", line)
            claimed_raw = completion_dates[-1] if completion_dates else phase_heading_date
            if claimed_raw:
                claimed = date.fromisoformat(claimed_raw)
                delta = (latest_d - claimed).days
                if delta < MIN_OBSERVATION_DAYS:
                    problems.append(
                        f"Phase {current_phase}: observation-gated completion "
                        f"claimed {claimed} but latest evidence is only "
                        f"{delta} days later (need >= {MIN_OBSERVATION_DAYS})"
                    )
    return problems


def _production_apply_conflict(plan_text: str) -> list[str]:
    """WU-8.3: a plan file that only plans must not also claim production
    apply. If the plan declares '只做计划/不实施' AND 'production/production
    apply/已实施' in the same file, that is a conflict."""
    problems: list[str] = []
    # skip rule-description lines ("规则：...不能...", "不得...") that merely
    # STATE the requirement rather than claim an apply.
    lines = [
        line
        for line in plan_text.splitlines()
        if not re.match(r"^\s*[-*]?\s*(规则|约束|不得|不能|禁止|要求)", line)
    ]
    body = "\n".join(lines)
    plans_only = re.search(r"只做计划|只做规划|不实施|plan.?only|planning.?only", body, re.I)
    # "production apply" is a SPECIFIC claim of having applied changes to the
    # production system; bare "production" mentions (config paths, design
    # goals) do not count.
    applies = re.search(
        r"production\s+apply|已应用到生产|production_apply|已实施到生产",
        body,
        re.I,
    )
    if plans_only and applies:
        problems.append("plan claims plan-only AND production apply (conflict)")
    return problems


_ARCHIVED_MARKERS = (
    "不再作为活动任务",
    "历史参考",
    "已归档",
    "archived",
    "deprecated",
)


def _is_archived(plan_text: str) -> bool:
    """WU-8.3: an explicitly archived/deprecated plan is exempt from
    completed-claim checks (it is historical reference, not an active plan)."""
    return any(marker in plan_text for marker in _ARCHIVED_MARKERS)


def verify(plan_text: str, progress_text: str) -> tuple[list[str], list[dict]]:
    if _is_archived(plan_text):
        return [], []
    problems: list[str] = []
    report: list[dict] = []
    for phase in parse_plan(plan_text):
        number = phase["number"]
        entry: dict = {
            "phase": number,
            "unchecked_items": phase["unchecked"],
            "waiver": phase["has_waiver"],
            "evidence": evidence_in_progress(progress_text, number),
            "ok": True,
            "problems": [],
        }
        if phase["unchecked"] > 0 and not phase["has_waiver"]:
            entry["ok"] = False
            entry["problems"].append(
                f"Phase {number}: {phase['unchecked']} unchecked item(s) in a "
                "completed section with no waiver note"
            )
        if not entry["evidence"]:
            entry["ok"] = False
            entry["problems"].append(
                f"Phase {number}: no machine evidence (test command + pass "
                "count + date) in progress.md"
            )
        if not entry["ok"]:
            problems.extend(entry["problems"])
        report.append(entry)
    problems.extend(_timed_gate_problems(plan_text, progress_text))
    problems.extend(_production_apply_conflict(plan_text))
    return problems, report


def _discover_plans(plan_dir: Path) -> list[tuple[Path, Path, Path | None]]:
    """WU-8.3: recursively find (task_plan.md, progress.md, findings.md) triples
    under a dir, including docs/plans/** subplans. findings.md is included so
    its claims can be cross-checked (a missing findings.md for an active plan
    is reported)."""
    pairs: list[tuple[Path, Path, Path | None]] = []
    for plan in sorted(plan_dir.rglob("task_plan.md")):
        progress = plan.parent / "progress.md"
        if progress.is_file():
            findings = plan.parent / "findings.md"
            pairs.append((plan, progress, findings if findings.is_file() else None))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify completed plan claims")
    parser.add_argument("--plan", type=Path, default=None, help="plan markdown path")
    parser.add_argument("--progress", type=Path, default=None, help="progress log path")
    parser.add_argument("--plan-dir", type=Path, default=None,
                        help="recursively verify all task_plan/progress pairs under a dir")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    all_problems: list[str] = []
    all_reports: list[dict] = []
    if args.plan_dir is not None:
        pairs = _discover_plans(args.plan_dir)
        if not pairs:
            print(f"no task_plan.md/progress.md pairs under {args.plan_dir}")
            return 2
        for plan_path, progress_path, findings_path in pairs:
            problems, report = verify(
                plan_path.read_text(encoding="utf-8"),
                progress_path.read_text(encoding="utf-8"),
            )
            if findings_path is None:
                problems.append("findings.md missing (WU-8.3 requires it for active plans)")
            for problem in problems:
                all_problems.append(f"{plan_path}: {problem}")
            all_reports.append({"plan": str(plan_path), "report": report})
    else:
        plan_path = args.plan or root / "task_plan.md"
        progress_path = args.progress or root / "progress.md"
        if not plan_path.is_file() or not progress_path.is_file():
            print(f"missing plan/progress file: {plan_path} {progress_path}")
            return 2
        problems, report = verify(
            plan_path.read_text(encoding="utf-8"),
            progress_path.read_text(encoding="utf-8"),
        )
        all_problems = problems
        all_reports = report
    if args.json:
        print(json.dumps({"ok": not all_problems, "problems": all_problems, "reports": all_reports}, indent=2, sort_keys=True))
        return 1 if all_problems else 0
    for problem in all_problems:
        print(f"PLAN-VERIFY: {problem}")
    if not all_problems:
        print(f"OK: all completed claims are evidence-backed ({len(all_reports)} plan(s))")
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
