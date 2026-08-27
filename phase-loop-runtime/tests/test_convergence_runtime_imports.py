"""RUNTIME public surface, SL-0 fences, and the v10 re-grounding record (EC-RUNTIME-4/5)."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import phase_loop_runtime.convergence as convergence
from phase_loop_runtime.convergence import FencedAdmissionFactory, RepositoryDispatchRequest, SupportedConvergenceVersions, refresh_downstream_after_merge
from phase_loop_runtime.train_runner import CoordinatorRuntime

from _runtime_tdd_guard import (
    FORBIDDEN_BROKER_SYMBOLS, PERMITTED_BROKER_MODULE_SYMBOLS,
    assert_no_forbidden_broker_imports, repo_root,
)
from runtime_content_tdd_adapter import (
    RUNTIME_CASES, RUNTIME_INVENTORY, RUNTIME_TEST_MODULES, assert_all_production_anchors,
    verify_sl0_landing_bytes,
)

#: The exact IF-0-RUNTIME-1 public surface INTEG consumes.
IF_0_RUNTIME_1_SURFACE = (
    "default_convergence_event_log_path",
    "record_intent",
    "record_outcome",
    "read_convergence_events",
    "recover_train_state",
    "reconcile_train_state",
    "build_train_status",
    "render_train_status",
    "RecoveredTrainState",
    "ReconciliationVerdict",
    "ExactStateProbes",
    "TrainStatusSnapshot",
    "AdapterExecutionRequest",
    "run_codex_adapter",
    "run_claude_adapter",
    "run_outside_agent_adapter",
)


# ---------------------------------------------------------------------------
# Retained skeleton behaviour


def test_runtime_import_surface_exposes_runtime_gate():
    for name in ("default_convergence_event_log_path", "record_intent", "record_outcome", "read_convergence_events", "recover_train_state", "reconcile_train_state"):
        assert hasattr(convergence, name)


def test_convergence_runtime_exports_and_coordinator_boundary(tmp_path):
    assert FencedAdmissionFactory and RepositoryDispatchRequest and SupportedConvergenceVersions and refresh_downstream_after_merge
    runtime = CoordinatorRuntime("train", tmp_path, "train.md", "digest", "workspace", broker_client=object())
    assert runtime.train_id == "train"


# ---------------------------------------------------------------------------
# IF-0-RUNTIME-1 public surface


def test_if_0_runtime_1_surface_is_importable_and_exported():
    for name in IF_0_RUNTIME_1_SURFACE:
        assert hasattr(convergence, name), f"{name} is missing from the public package"
        assert name in convergence.__all__, f"{name} is not exported"


def test_public_package_imports_in_a_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root() / "phase-loop-runtime" / "src")
    completed = subprocess.run(
        [sys.executable, "-c", "import phase_loop_runtime.convergence as c; print(len(c.__all__))"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert int(completed.stdout.strip()) >= len(IF_0_RUNTIME_1_SURFACE)


def test_runtime_capability_version_is_one_whenever_the_reducer_has_landed():
    """SL-4 alone adds the gate; whenever present it is exactly the frozen value.

    This case never skips: the surface claim below is unconditional, so the RED
    leg's zero-skip accounting stays exact while SL-4 remains unlanded.
    """
    for name in IF_0_RUNTIME_1_SURFACE:
        assert hasattr(convergence, name)
    if hasattr(convergence, "RUNTIME_CAPABILITY_VERSION"):
        assert convergence.RUNTIME_CAPABILITY_VERSION == 1
        assert "RUNTIME_CAPABILITY_VERSION" in convergence.__all__


# ---------------------------------------------------------------------------
# SL-0 fences


def test_sl0_bytes_import_no_forbidden_broker_symbol():
    assert_no_forbidden_broker_imports(RUNTIME_INVENTORY)


def test_the_import_fence_permits_the_pure_credential_scrubber():
    from phase_loop_runtime.convergence.broker.credsep import strip_mutation_credentials

    assert "strip_mutation_credentials" in PERMITTED_BROKER_MODULE_SYMBOLS
    assert "strip_mutation_credentials" not in FORBIDDEN_BROKER_SYMBOLS
    assert strip_mutation_credentials({"GH_TOKEN": "x", "PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


def test_sl0_inventory_matches_the_files_on_disk():
    root = repo_root()
    for relative in RUNTIME_INVENTORY:
        assert (root / relative).is_file(), f"SL-0 inventory names a missing file: {relative}"
    assert len(RUNTIME_TEST_MODULES) == 6
    assert set(RUNTIME_TEST_MODULES) < set(RUNTIME_INVENTORY)


def test_every_mapped_case_enters_its_production_symbol():
    assert_all_production_anchors()
    anchors = {case.anchor for case in RUNTIME_CASES.values()}
    assert len(anchors) == len(RUNTIME_CASES), "typed anchors must be one per case"
    for case_id, case in RUNTIME_CASES.items():
        assert case.anchor == f"RUNTIME-RED-ANCHOR::{case_id}"
        assert case.production_path.startswith("phase-loop-runtime/src/")


# ---------------------------------------------------------------------------
# EC-RUNTIME-0: SL-0 bytes are immutable after their landing


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _new_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    _git(path, "config", "user.email", "sl0@example.invalid")
    _git(path, "config", "user.name", "RUNTIME SL-0")
    return path


def _synthetic_landing(tmp_path: Path) -> tuple[Path, str, list[dict], list[tuple[str, str]]]:
    """A repo whose landing commit freezes one stub byte per SL-0 inventory path."""
    repo = _new_repo(tmp_path / "landing-repo")
    for relative in RUNTIME_INVENTORY:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# landed {Path(relative).name}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tests-only landing")
    landing = _git(repo, "rev-parse", "HEAD")
    inventory = [{"path": path, "sha256": _digest(repo / path)} for path in RUNTIME_INVENTORY]
    receipt_files = [(path, _digest(repo / path)) for path in RUNTIME_INVENTORY]
    return repo, landing, inventory, receipt_files


def test_sl0_verification_rejects_a_mutation_with_refreshed_digests(tmp_path):
    """A later SL-0 edit cannot verify by refreshing the receipt and companion.

    Both records are ordinary files that whoever edits an SL-0 byte can rewrite in
    the same breath, so EC-RUNTIME-0's later-SL-0-byte falsifier has to bind the
    frozen landing blob -- including when the mutated path is simply dropped from
    the companion's inventory.
    """
    repo, landing, inventory, receipt_files = _synthetic_landing(tmp_path)
    assert verify_sl0_landing_bytes(
        repo, landing, companion_inventory=inventory, receipt_files=receipt_files
    ) is None, "the unchanged landing must verify"

    victim = "phase-loop-runtime/tests/test_convergence_event_log.py"
    (repo / victim).write_text("# mutated after the landing\n", encoding="utf-8")
    refreshed = _digest(repo / victim)
    companion_refreshed = [
        dict(row, sha256=refreshed) if row["path"] == victim else row for row in inventory
    ]
    receipt_refreshed = [
        (path, refreshed if path == victim else digest) for path, digest in receipt_files
    ]

    assert verify_sl0_landing_bytes(
        repo, landing, companion_inventory=companion_refreshed, receipt_files=receipt_refreshed
    ) is not None, "a mutation with both digests refreshed must not verify"
    assert verify_sl0_landing_bytes(
        repo,
        landing,
        companion_inventory=[row for row in companion_refreshed if row["path"] != victim],
        receipt_files=receipt_refreshed,
    ) is not None, "dropping the mutated path from the companion must not verify"
    assert verify_sl0_landing_bytes(
        repo, landing, companion_inventory=inventory, receipt_files=receipt_refreshed
    ) is not None, "a refreshed receipt digest must not verify"
    assert verify_sl0_landing_bytes(
        repo, landing, companion_inventory=companion_refreshed, receipt_files=receipt_files
    ) is not None, "a refreshed companion digest must not verify"

    (repo / victim).write_text(f"# landed {Path(victim).name}\n", encoding="utf-8")
    assert verify_sl0_landing_bytes(
        repo, landing, companion_inventory=inventory, receipt_files=receipt_files
    ) is None, "restoring the landed byte must verify again"


def test_sl0_verification_requires_a_closed_companion_inventory(tmp_path):
    """The companion must cover the SL-0 inventory exactly: no gap, extra, or duplicate."""
    repo, landing, inventory, receipt_files = _synthetic_landing(tmp_path)
    victim = "phase-loop-runtime/tests/_runtime_tdd_guard.py"

    unclosed = {
        "missing": [row for row in inventory if row["path"] != victim],
        "duplicated": [*inventory, dict(inventory[0])],
        "extra": [*inventory, {"path": "phase-loop-runtime/tests/conftest.py", "sha256": "0" * 64}],
        "malformed digest": [
            dict(row, sha256="not-a-digest") if row["path"] == victim else row for row in inventory
        ],
        "unstructured": [victim],
        "empty": [],
    }
    for label, companion in unclosed.items():
        assert verify_sl0_landing_bytes(
            repo, landing, companion_inventory=companion, receipt_files=receipt_files
        ) is not None, f"an inventory with an {label} row was accepted"

    assert verify_sl0_landing_bytes(
        repo,
        landing,
        companion_inventory=inventory,
        receipt_files=[item for item in receipt_files if item[0] != victim],
    ) is not None, "a receipt that drops an SL-0 path was accepted"
    assert verify_sl0_landing_bytes(
        repo, landing, companion_inventory=inventory, receipt_files=[*receipt_files, *receipt_files]
    ) is not None, "a receipt that duplicates an SL-0 path was accepted"


# ---------------------------------------------------------------------------
# EC-RUNTIME-5: the v10 re-grounding record


#: Lifecycle transitions that may follow the re-grounding record without retiring
#: the row's authority. The executor appends ``executing`` at dispatch and then
#: ``completed``/``failed`` at closeout, so the durable record -- not whichever
#: transition happens to be last -- carries EC-RUNTIME-5. ``orphaned``, the
#: manifest's only non-execution terminal, is deliberately absent.
LIVE_AUTHORITY_TRANSITIONS = frozenset(
    {"committed", "executing", "completed", "failed", "authority_switch"}
)

_SHA1_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _manifest_rows() -> dict[str, dict]:
    manifest_path = repo_root() / "plans" / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip("repository manifest is absent in standalone clean-room")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {row["slug"]: row for row in payload["plans"] if "slug" in row}


def _selectable_runtime_slugs(rows: dict[str, dict]) -> list[str]:
    return [
        slug
        for slug, row in rows.items()
        if row.get("phase_alias") == "RUNTIME" and row.get("status") != "orphaned"
    ]


def reground_defect(
    row: dict,
    *,
    root: Path,
    head: str = "HEAD",
    roadmap_digest: str | None = None,
) -> str | None:
    """Return the first defect in a row's durable re-grounding record, else ``None``.

    EC-RUNTIME-5 is about the *current* authority carrying a re-grounding record
    that cites an ancestral main SHA, not about which transition happens to sit
    last: execution appends leave that record untouched, so this stays exact
    through dispatch and closeout while still rejecting an absent, malformed,
    non-ancestral, or orphaned current authority.
    """

    if not isinstance(row, dict):
        return f"manifest row is not an object: {row!r}"
    if row.get("status") == "orphaned":
        return "the current RUNTIME authority is orphaned"
    lifecycle = row.get("lifecycle")
    if not isinstance(lifecycle, list) or not lifecycle:
        return "the current RUNTIME row has no lifecycle"
    for index, event in enumerate(lifecycle):
        if not isinstance(event, dict):
            return f"lifecycle[{index}] is not an object"
        transition = event.get("transition")
        if transition not in LIVE_AUTHORITY_TRANSITIONS:
            return f"lifecycle[{index}] retires the current authority: {transition!r}"

    grounding = None
    for event in lifecycle:
        metadata = event.get("metadata")
        if event.get("transition") == "committed" and isinstance(metadata, dict):
            if "planning_base" in metadata:
                grounding = metadata
                break
    if grounding is None:
        return "no committed re-grounding record cites a planning base"
    if grounding.get("phase_alias") != "RUNTIME":
        return f"the re-grounding record is not RUNTIME's: {grounding.get('phase_alias')!r}"

    planning_base = grounding.get("planning_base")
    if not isinstance(planning_base, str) or _SHA1_RE.fullmatch(planning_base) is None:
        return f"malformed planning_base: {planning_base!r}"
    seal = grounding.get("roadmap_sha256")
    if not isinstance(seal, str) or _SHA256_RE.fullmatch(seal) is None:
        return f"malformed roadmap seal: {seal!r}"
    if roadmap_digest is not None and seal != roadmap_digest:
        return "the re-grounding record's roadmap seal is not the on-disk roadmap"
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", planning_base, head],
        cwd=root,
        capture_output=True,
    ).returncode:
        return f"planning_base {planning_base} is not ancestral to {head}"
    return None


def test_runtime_v10_reground_record_is_present_and_ancestral():
    """The new plan resolves uniquely while the provenance-only row stays orphaned."""
    root = repo_root()
    rows = _manifest_rows()

    current = rows["v10-RUNTIME"]
    assert current["file"] == "plans/phase-plan-v10-RUNTIME.md"

    plan_path = root / "plans" / "phase-plan-v10-RUNTIME.md"
    roadmap_path = root / "specs" / "phase-plans-v10.md"
    roadmap_digest = hashlib.sha256(roadmap_path.read_bytes()).hexdigest()
    defect = reground_defect(current, root=root, roadmap_digest=roadmap_digest)
    assert defect is None, f"the v10-RUNTIME re-grounding record is not durable: {defect}"
    assert f"roadmap_sha256: {roadmap_digest}" in plan_path.read_text(encoding="utf-8")

    superseded = rows["vergence-v1-RUNTIME"]
    assert superseded["status"] == "orphaned"
    assert superseded["file"] == "plans/phase-plan-vergence-v1-RUNTIME.md"
    assert superseded["lifecycle"][-1]["transition"] == "orphaned"

    assert _selectable_runtime_slugs(rows) == ["v10-RUNTIME"], "the v10 plan must resolve uniquely"


def _diverged_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A repo with an ancestral base, its head, and a real non-ancestral commit."""
    repo = _new_repo(tmp_path / "manifest-repo")

    def commit(message: str, body: str) -> str:
        (repo / "main.md").write_text(body, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", message)
        return _git(repo, "rev-parse", "HEAD")

    base = commit("planning base", "base\n")
    head = commit("execution base", "head\n")
    _git(repo, "checkout", "-q", "-b", "side", base)
    diverged = commit("unrelated line of history", "side\n")
    _git(repo, "checkout", "-q", "main")
    return repo, base, head, diverged


def test_the_reground_falsifier_survives_execution_appends(tmp_path):
    """Dispatch and closeout appends never falsify the durable re-grounding record.

    The executor appends ``executing`` at dispatch and ``completed``/``failed`` at
    closeout, so an assertion pinned to ``lifecycle[-1]`` would fail this immutable
    suite the moment RUNTIME runs -- outside any typed anchor, and unrepairable
    with SL-0 frozen.
    """
    repo, base, head, _diverged = _diverged_repo(tmp_path)
    seal = hashlib.sha256(b"roadmap").hexdigest()
    row = {
        "slug": "v10-RUNTIME",
        "phase_alias": "RUNTIME",
        "status": "committed",
        "file": "plans/phase-plan-v10-RUNTIME.md",
        "lifecycle": [
            {
                "transition": "committed",
                "by": "codex-plan-phase",
                "metadata": {
                    "phase_alias": "RUNTIME",
                    "planning_base": base,
                    "roadmap_sha256": seal,
                },
            }
        ],
    }
    assert reground_defect(row, root=repo, head=head, roadmap_digest=seal) is None

    for transition, status in (("executing", "executing"), ("completed", "completed")):
        row["lifecycle"].append({"transition": transition, "by": "phase-loop", "metadata": {}})
        row["status"] = status
        defect = reground_defect(row, root=repo, head=head, roadmap_digest=seal)
        assert defect is None, f"a legal {transition} append falsified the record: {defect}"


def test_the_reground_falsifier_rejects_absent_malformed_and_orphaned_authority(tmp_path):
    """Absent, malformed, non-ancestral, and orphaned authority all still fail."""
    repo, base, head, diverged = _diverged_repo(tmp_path)
    seal = hashlib.sha256(b"roadmap").hexdigest()
    valid = {
        "slug": "v10-RUNTIME",
        "phase_alias": "RUNTIME",
        "status": "executing",
        "file": "plans/phase-plan-v10-RUNTIME.md",
        "lifecycle": [
            {
                "transition": "committed",
                "by": "codex-plan-phase",
                "metadata": {
                    "phase_alias": "RUNTIME",
                    "planning_base": base,
                    "roadmap_sha256": seal,
                },
            },
            {"transition": "executing", "by": "phase-loop", "metadata": {}},
        ],
    }
    assert reground_defect(valid, root=repo, head=head, roadmap_digest=seal) is None

    def mutated(**changes) -> dict:
        row = copy.deepcopy(valid)
        for key, value in changes.items():
            row[key] = value
        return row

    def regrounded(**changes) -> dict:
        row = copy.deepcopy(valid)
        for key, value in changes.items():
            if value is None:
                row["lifecycle"][0]["metadata"].pop(key, None)
            else:
                row["lifecycle"][0]["metadata"][key] = value
        return row

    broken = {
        "absent record": mutated(lifecycle=[dict(valid["lifecycle"][1])]),
        "absent lifecycle": mutated(lifecycle=[]),
        "absent planning base": regrounded(planning_base=None),
        "malformed planning base": regrounded(planning_base=base[:39]),
        "non-hex planning base": regrounded(planning_base="z" * 40),
        "non-ancestral planning base": regrounded(planning_base=diverged),
        "unknown planning base": regrounded(planning_base="0" * 40),
        "malformed roadmap seal": regrounded(roadmap_sha256="deadbeef"),
        "drifted roadmap seal": regrounded(roadmap_sha256=hashlib.sha256(b"other").hexdigest()),
        "foreign phase": regrounded(phase_alias="INTEG"),
        "orphaned status": mutated(status="orphaned"),
        "orphaned append": mutated(
            lifecycle=[*copy.deepcopy(valid["lifecycle"]),
                       {"transition": "orphaned", "by": "x", "metadata": {}}]
        ),
    }
    for label, row in broken.items():
        assert reground_defect(row, root=repo, head=head, roadmap_digest=seal) is not None, (
            f"{label} was accepted as a durable re-grounding record"
        )


def test_only_one_runtime_row_may_be_selectable():
    """The provenance-only row becoming selectable is still a falsifier."""
    rows = _manifest_rows()
    assert _selectable_runtime_slugs(rows) == ["v10-RUNTIME"]

    unorphaned = copy.deepcopy(rows)
    unorphaned["vergence-v1-RUNTIME"]["status"] = "committed"
    assert _selectable_runtime_slugs(unorphaned) != ["v10-RUNTIME"]

    retired = copy.deepcopy(rows)
    retired["v10-RUNTIME"]["status"] = "orphaned"
    assert _selectable_runtime_slugs(retired) == []


def test_superseded_runtime_plan_is_not_selectable_for_v10():
    rows = _manifest_rows()
    superseded = rows["vergence-v1-RUNTIME"]
    assert superseded["roadmap_ref"]["file"] == "specs/phase-plans-convergence-v1.md"
    assert superseded["roadmap_ref"]["file"] != "specs/phase-plans-v10.md"
    assert Path(superseded["file"]).name != "phase-plan-v10-RUNTIME.md"
