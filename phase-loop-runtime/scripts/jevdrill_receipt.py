"""Classify a JEV Drill companion leg from its pytest junit (JEVHOST §8).

The companion workflow (``.github/workflows/jevdrill-companion.yml``) runs the twelve
files of JEVHOST §1 and hands this script the junit and pytest's exit code. The leg
passes only when:

* pytest exited 0. An exit of 2, 3, 4 or 5 (interrupted, internal error, usage error,
  no tests) fails the leg whatever the junit says;
* no testcase failed or errored;
* every skip carries one of the four allowlisted reasons of ``SKIP_ALLOWLIST``, and that
  reason is allowed on this leg;
* the run is complete [N-RC]: each of the twelve files contributes a testcase, and the
  eight controls appear by node ID with their required outcome;
* on the installed leg, every item ``-m jevdrill_installed --collect-only -q`` collected
  appears by node ID and passed. The set is read from that output, never hard-coded.

Every skip is written, with its node ID and reason, to the job summary
(``$GITHUB_STEP_SUMMARY`` when set, or ``--summary``).

A second subcommand, ``compare-contract``, compares a jevdrill checkout's ``schemas/``
and ``tests/contracts/fixtures/`` with the harness copies under JEVHOST §5.

Node IDs here are relative to ``phase-loop-runtime/tests/``, as in JEVHOST §1.

Exit 0 when the leg passes, 1 when it fails, 2 on bad input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# The jevdrill commit the harness fixtures are synced to (JEVHOST §5). The companion
# workflow's `jevdrill_ref` input defaults to it; the shape test holds the two equal.
JEVDRILL_REF_DEFAULT = "998912b1e0195464e6f3aa048c5421c2bed57491"

# The twelve files of JEVHOST §1, relative to phase-loop-runtime/tests/.
TWELVE_FILES = (
    "test_jevdrill_adapter.py",
    "test_jevdrill_diagnostics.py",
    "test_jevdrill_discovery.py",
    "test_jevdrill_input.py",
    "test_jevdrill_queue.py",
    "test_jevdrill_usage.py",
    "test_windows_locking.py",
    "test_launcher_liveness.py",
    "test_windows_processes.py",
    "test_windows_storage.py",
    "test_phase_loop_launcher.py",
    "test_phase_loop_work_unit_observability.py",
)

# The eight controls of JEVHOST §1, with the installed split.
INSTALLED_CONTROLS = (
    "test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[alpha]",
    "test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[beta]",
    "test_jevdrill_discovery.py::test_entered_discovery_requires_harness_decomposition",
    "test_jevdrill_discovery.py::test_objective_tombstone_survives_restart_and_preserves_reports",
)
NON_INSTALLED_CONTROLS = (
    "test_jevdrill_discovery.py::test_native_unsupported_observer_records_unknown_capture",
    "test_jevdrill_adapter.py::test_guidance_is_verified_injected_once_and_deactivated",
    "test_jevdrill_queue.py::test_objective_guard_reuses_anchored_transaction_and_bounds_admission",
    "test_jevdrill_queue.py::test_objective_guard_bounds_other_thread_contention",
)

JEVDRILL_VARIABLES = ("JEVDRILL_TEST_CLI", "JEVDRILL_TEST_PYTHON")
SCHED_VARIABLE = "PHASE_LOOP_TDD_EXPECT_SCHED"

# JEVHOST §6's fixed skip reason for a `jevdrill_installed` item.
JEVDRILL_INSTALLED_REASON = "jevdrill_installed: neither JEVDRILL_TEST_CLI nor JEVDRILL_TEST_PYTHON is set"

# The allowlist of JEVHOST §8: exactly four reasons, matched by their fixed strings.
# Reason 3 is the two Windows-only files' module `skipif`, one string per file. Where
# each is allowed is `allowance_applies` below. There is no other exception.
SKIP_ALLOWLIST = {
    "dotfiles_integration": ("requires dotfiles tree (dotfiles_integration)",),
    "jevdrill_installed": (JEVDRILL_INSTALLED_REASON,),
    "windows_only_files": ("Native Windows Job Object proof", "Native NTFS storage proof"),
    "sched_unset": ("SCHED RED suite inactive; set PHASE_LOOP_TDD_EXPECT_SCHED=1",),
}

# Each Windows-only reason belongs to exactly one file.
WINDOWS_ONLY_REASON_FILES = {
    "Native Windows Job Object proof": "test_windows_processes.py",
    "Native NTFS storage proof": "test_windows_storage.py",
}

# pytest exit codes that fail a leg whatever the junit holds.
PYTEST_EXIT_MEANING = {
    1: "tests failed",
    2: "interrupted",
    3: "internal error",
    4: "usage error",
    5: "no tests collected",
}

LEGS = ("receipt", "installed")
OSES = ("linux", "macos", "windows")

# JEVHOST §5: the three fixtures and the counter placeholder.
FIXTURE_NAMES = ("discovery.json", "host.json", "route-inputs.json")
DIGESTS_NAME = "digests.json"
SCHEMA_COUNT = 14
COUNTER_PLACEHOLDER = b"<jev-token-counter-revision>"
COUNTER_LITERAL = b"utf8-bytes-upper-bound-v1"


@dataclass(frozen=True)
class Leg:
    kind: str  # "receipt" or "installed"
    os: str  # "linux", "macos" or "windows"
    jevdrill_variables: frozenset = frozenset()
    sched_set: bool = True


@dataclass
class Report:
    failures: list = field(default_factory=list)
    skips: list = field(default_factory=list)  # (node_id, reason)
    outcomes: dict = field(default_factory=dict)  # node_id -> passed|skipped|failure|error
    testcases: int = 0

    @property
    def passed(self) -> bool:
        return not self.failures


def allowance_applies(allowance: str, reason: str, node_id: str, leg: Leg) -> bool:
    """Whether an allowlisted reason may stand on this node of this leg."""
    if allowance == "dotfiles_integration":
        return True
    if allowance == "jevdrill_installed":
        return not leg.jevdrill_variables
    if allowance == "windows_only_files":
        return leg.os != "windows" and _file_of(node_id) == WINDOWS_ONLY_REASON_FILES[reason]
    if allowance == "sched_unset":
        return not leg.sched_set
    raise ValueError(f"unknown allowance {allowance!r}")


def allowance_for(reason: str) -> str | None:
    for allowance, reasons in SKIP_ALLOWLIST.items():
        if reason in reasons:
            return allowance
    return None


def _file_of(node_id: str) -> str:
    return node_id.split("::", 1)[0]


def normalize_node_id(raw: str) -> str:
    """A collected node ID, made relative to phase-loop-runtime/tests/."""
    path, sep, rest = raw.strip().partition("::")
    parts = path.replace("\\", "/").split("/")  # only the path: a parametrize id keeps its backslashes
    if "tests" in parts[:-1]:
        parts = parts[len(parts) - 1 - parts[::-1].index("tests"):]
        parts = parts[1:]
    return "/".join(parts) + sep + rest


def junit_node_id(classname: str, name: str) -> str:
    """Map a junit row back to its pytest node ID, relative to the tests directory.

    pytest writes ``classname`` as the dotted module path from its rootdir, then any
    class names, and ``name`` as the function name with its parametrize id. The rootdir
    prefix (``tests.``, ``phase-loop-runtime.tests.``) is dropped. The module is the
    first component that names a test file (``test_*``); the ones after it are classes.
    """
    parts = [p for p in classname.split(".") if p]
    module_index = next((i for i, p in enumerate(parts) if p.startswith("test_")), None)
    if module_index is None:
        return f"{classname}::{name}"
    prefix = parts[:module_index]
    if "tests" in prefix:
        prefix = prefix[len(prefix) - prefix[::-1].index("tests"):]
    path = "/".join(prefix + [parts[module_index] + ".py"])
    return "::".join([path, *parts[module_index + 1:], name]) if name else path


_RANK = {"passed": 0, "skipped": 1, "failure": 2, "error": 3}


def read_junit(junit: Path) -> list:
    """Every testcase as ``(node_id, outcome, skip_reason)``."""
    root = ET.parse(junit).getroot()
    rows = []
    for case in root.iter("testcase"):
        node_id = junit_node_id(case.get("classname") or "", case.get("name") or "")
        outcome, reason = "passed", None
        for tag in ("error", "failure", "skipped"):
            element = case.find(tag)
            if element is not None:
                outcome = tag
                if tag == "skipped":
                    reason = element.get("message") or ""
                    if element.get("type") == "pytest.xfail":
                        reason = f"xfail: {reason}"
                break
        rows.append((node_id, outcome, reason))
    return rows


def parse_collected(text: str) -> list:
    """The node IDs of ``pytest --collect-only -q`` output, in order.

    The node IDs are the lines before the first blank line. Any line there that is not a
    node ID is an error, so a changed output format cannot pass as an empty set.
    """
    nodes = []
    for line in text.splitlines():
        if not line.strip():
            break
        if "::" not in line or line != line.strip():
            raise ValueError(f"unexpected --collect-only line: {line!r}")
        node = normalize_node_id(line)
        if node not in nodes:
            nodes.append(node)
    return nodes


def classify(rows: list, leg: Leg, exit_code: int, expected_installed: list | None = None) -> Report:
    report = Report(testcases=len(rows))
    fail = report.failures.append

    if exit_code != 0:
        meaning = PYTEST_EXIT_MEANING.get(exit_code, "unexpected exit code")
        fail(f"pytest exited {exit_code} ({meaning}); the leg fails whatever the junit says")

    if leg.kind == "receipt" and leg.jevdrill_variables:
        fail(f"the receipt leg sets {', '.join(sorted(leg.jevdrill_variables))}; it must set neither variable")
    if leg.kind == "installed":
        if set(leg.jevdrill_variables) != set(JEVDRILL_VARIABLES):
            fail("the installed leg must set both JEVDRILL_TEST_CLI and JEVDRILL_TEST_PYTHON")
        if not expected_installed:
            fail("the installed leg has no collected jevdrill_installed items (--collected is empty)")
    expected = list(expected_installed or [])

    if not rows:
        fail("the junit holds no testcase: an empty run is not a receipt")

    for node_id, outcome, reason in rows:
        if _RANK[outcome] >= _RANK.get(report.outcomes.get(node_id, "passed"), 0):
            report.outcomes[node_id] = outcome
        if outcome in ("failure", "error"):
            fail(f"{node_id}: {outcome}")
        elif outcome == "skipped":
            report.skips.append((node_id, reason))
            if leg.kind == "installed" and node_id in expected:
                fail(f"{node_id}: a jevdrill_installed item skipped on the installed leg ({reason})")
                continue
            allowance = allowance_for(reason)
            if allowance is None:
                fail(f"{node_id}: skip reason outside the allowlist: {reason!r}")
            elif not allowance_applies(allowance, reason, node_id, leg):
                fail(f"{node_id}: skip reason {reason!r} ({allowance}) is not allowed on this leg")

    # [N-RC] completeness: each of the twelve files contributes a testcase.
    seen_files = {_file_of(node_id) for node_id, _, _ in rows}
    for name in TWELVE_FILES:
        if name not in seen_files:
            fail(f"{name}: contributed no testcase (partial run)")

    def require(node_id: str, outcome: str, reason: str | None = None) -> None:
        found = report.outcomes.get(node_id)
        if found is None:
            fail(f"{node_id}: control missing from the junit")
        elif found != outcome:
            fail(f"{node_id}: control is {found}, expected {outcome}")
        elif reason is not None and reason not in {r for n, r in report.skips if n == node_id}:
            fail(f"{node_id}: control skipped without the fixed reason {reason!r}")

    for node_id in NON_INSTALLED_CONTROLS:
        require(node_id, "passed")
    for node_id in INSTALLED_CONTROLS:
        if leg.kind == "receipt":
            require(node_id, "skipped", JEVDRILL_INSTALLED_REASON)
        else:
            require(node_id, "passed")
            if expected and node_id not in expected:
                fail(f"{node_id}: installed control not in the collected jevdrill_installed set")

    # A failed, errored or skipped expected item is reported above; here, a missing one.
    for node_id in expected:
        if node_id not in report.outcomes:
            fail(f"{node_id}: collected jevdrill_installed item missing from the junit")
    return report


def render_summary(report: Report, leg: Leg, title: str | None = None) -> str:
    verdict = "PASS" if report.passed else "FAIL"
    lines = [
        f"### {title or f'JEV Drill {leg.kind} leg ({leg.os})'}: {verdict}",
        "",
        f"- testcases: {report.testcases}",
        f"- skips: {len(report.skips)}",
        f"- JEVDRILL variables set: {', '.join(sorted(leg.jevdrill_variables)) or 'none'}",
        f"- {SCHED_VARIABLE}=1: {'yes' if leg.sched_set else 'no'}",
        "",
    ]
    if report.skips:
        lines += ["| skipped node ID | reason |", "| --- | --- |"]
        for node_id, reason in report.skips:
            lines.append(f"| `{node_id}` | {_cell(reason)} |")
        lines.append("")
    if report.failures:
        lines += ["**Failures:**", ""]
        lines += [f"- {_cell(item)}" for item in report.failures]
        lines.append("")
    return "\n".join(lines) + "\n"


def _cell(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _write_summary(text: str, summary: str | None) -> None:
    target = summary or os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)


def host_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def leg_from_environment(kind: str, os_label: str, environ=None) -> Leg:
    environ = os.environ if environ is None else environ
    return Leg(
        kind=kind,
        os=os_label,
        # Set means present, even when empty, as conftest's skip rule reads it.
        jevdrill_variables=frozenset(name for name in JEVDRILL_VARIABLES if environ.get(name) is not None),
        sched_set=environ.get(SCHED_VARIABLE) == "1",
    )


def compare_contract(jevdrill: Path, harness: Path) -> tuple[list, list]:
    """JEVHOST §5 comparison of a jevdrill checkout with the harness copies.

    Returns ``(problems, notes)``. Schemas compare by bytes; each fixture compares after
    the placeholder is replaced by the counter literal; ``digests.json`` must recompute.
    """
    problems, notes = [], []
    schemas = sorted(
        p.name for p in harness.glob("*.json") if p.name not in FIXTURE_NAMES and p.name != DIGESTS_NAME
    )
    if len(schemas) != SCHEMA_COUNT:
        problems.append(f"harness holds {len(schemas)} schemas, expected {SCHEMA_COUNT}")
    for name in schemas:
        theirs = jevdrill / "schemas" / name
        if not theirs.is_file():
            problems.append(f"schemas/{name}: absent from the jevdrill checkout")
        elif theirs.read_bytes() != (harness / name).read_bytes():
            problems.append(f"schemas/{name}: bytes differ from the harness copy")
    extra = sorted(
        p.name for p in (jevdrill / "schemas").glob("*.json") if p.name not in schemas
    ) if (jevdrill / "schemas").is_dir() else []
    if extra:
        notes.append(f"jevdrill schemas without a harness copy (not compared): {', '.join(extra)}")
    for name in FIXTURE_NAMES:
        ours_path, theirs = harness / name, jevdrill / "tests" / "contracts" / "fixtures" / name
        if not ours_path.is_file():
            problems.append(f"fixtures/{name}: absent from the harness")
            continue
        ours = ours_path.read_bytes()
        if COUNTER_LITERAL in ours:
            problems.append(f"fixtures/{name}: the harness copy holds the counter literal")
        if not theirs.is_file():
            problems.append(f"tests/contracts/fixtures/{name}: absent from the jevdrill checkout")
        elif ours.replace(COUNTER_PLACEHOLDER, COUNTER_LITERAL) != theirs.read_bytes():
            problems.append(f"fixtures/{name}: differs from jevdrill's after the placeholder substitution")
    digests_path = harness / DIGESTS_NAME
    try:
        digests = json.loads(digests_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"{DIGESTS_NAME}: unreadable ({exc})")
    else:
        recomputed = {name: hashlib.sha256((harness / name).read_bytes()).hexdigest() for name in schemas}
        if digests != recomputed:
            stale = sorted(set(digests) ^ set(recomputed)) + sorted(
                n for n in set(digests) & set(recomputed) if digests[n] != recomputed[n]
            )
            problems.append(f"{DIGESTS_NAME}: does not recompute ({', '.join(stale)})")
    return problems, notes


def _cmd_classify(args) -> int:
    if not args.junit.is_file():
        print(f"jevdrill receipt: junit {args.junit} does not exist; the leg fails", file=sys.stderr)
        return 1
    if args.os != host_os():
        print(f"jevdrill receipt: --os {args.os} but this runner is {host_os()}", file=sys.stderr)
        return 2
    expected = None
    if args.collected is not None:
        try:
            expected = parse_collected(args.collected.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"jevdrill receipt: {exc}", file=sys.stderr)
            return 2
    elif args.leg == "installed":
        print("jevdrill receipt: the installed leg needs --collected", file=sys.stderr)
        return 2
    try:
        rows = read_junit(args.junit)
    except ET.ParseError as exc:
        print(f"jevdrill receipt: {exc}", file=sys.stderr)
        return 2
    leg = leg_from_environment(args.leg, args.os)
    report = classify(rows, leg, args.exit_code, expected)
    text = render_summary(report, leg, args.title)
    _write_summary(text, args.summary)
    print(text)
    return 0 if report.passed else 1


def _cmd_compare(args) -> int:
    problems, notes = compare_contract(args.jevdrill, args.harness)
    lines = [f"### JEV Drill checkout comparison: {'FAIL' if problems else 'PASS'}", ""]
    lines += [f"- {p}" for p in problems] + [f"- note: {n}" for n in notes] + [""]
    text = "\n".join(lines) + "\n"
    _write_summary(text, args.summary)
    print(text)
    return 1 if problems else 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    classify_parser = sub.add_parser("classify", help="classify a leg's junit")
    classify_parser.add_argument("--junit", required=True, type=Path)
    classify_parser.add_argument("--leg", required=True, choices=LEGS)
    classify_parser.add_argument("--os", required=True, choices=OSES)
    classify_parser.add_argument("--exit-code", required=True, type=int, help="pytest's exit code")
    classify_parser.add_argument("--collected", type=Path, help="`-m jevdrill_installed --collect-only -q` output")
    classify_parser.add_argument("--summary", help="summary file (default: $GITHUB_STEP_SUMMARY)")
    classify_parser.add_argument("--title", help="summary heading")
    classify_parser.set_defaults(func=_cmd_classify)

    compare_parser = sub.add_parser("compare-contract", help="compare a jevdrill checkout under JEVHOST §5")
    compare_parser.add_argument("--jevdrill", required=True, type=Path, help="the jevdrill checkout")
    compare_parser.add_argument("--harness", required=True, type=Path, help="tests/fixtures/jevdrill")
    compare_parser.add_argument("--summary", help="summary file (default: $GITHUB_STEP_SUMMARY)")
    compare_parser.set_defaults(func=_cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
