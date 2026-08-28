#!/usr/bin/env python3
"""Fail-closed, retained-artifact verifier for ``verification_evidence.v3``.

The verifier deliberately has no dependency on ``phase_loop_runtime``.  It reads
canonical JSON evidence, retained artifacts and Git objects, and it queries the
authoritative CI provider.  It never executes a command recorded in evidence.
"""
from __future__ import annotations

import argparse
import ast
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable


SCHEMA = "verification_evidence.v3"
BROKER_SCHEMA = "parent_unix_broker_v1"
CANONICAL_GH = Path("/usr/bin/gh")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$")
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024

FROZEN_SL0_PATHS = (
    "phase-loop-runtime/tests/harden_tdd_guard.py",
    "phase-loop-runtime/tests/test_advisor_board_advisory_mode.py",
    "phase-loop-runtime/tests/test_advisor_board_backcompat.py",
    "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py",
    "phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py",
    "phase-loop-runtime/tests/test_advisor_board_cli_legacy.py",
    "phase-loop-runtime/tests/test_advisor_board_composition.py",
    "phase-loop-runtime/tests/test_advisor_board_config.py",
    "phase-loop-runtime/tests/test_advisor_board_golden.py",
    "phase-loop-runtime/tests/test_advisor_board_integration.py",
    "phase-loop-runtime/tests/test_advisor_board_live_research.py",
    "phase-loop-runtime/tests/test_advisor_board_observability.py",
    "phase-loop-runtime/tests/test_advisor_board_presets.py",
    "phase-loop-runtime/tests/test_advisor_board_research.py",
    "phase-loop-runtime/tests/test_advisor_board_resolver.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_harden_evidence_verifier.py",
    "phase-loop-runtime/tests/test_panel_invoker.py",
    "phase-loop-runtime/tests/test_panel_leg_failure_diagnostic.py",
    "phase-loop-runtime/tests/test_panel_native_fill_183.py",
    "phase-loop-runtime/tests/test_panel_streaming_verdicts.py",
    "phase-loop-runtime/tests/test_phase_loop_injection.py",
    "phase-loop-runtime/tests/test_ratification_policy.py",
    "phase-loop-runtime/tests/test_reconcile_portability_85c.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_verification_interpreter_guard_221.py",
)

PLAN_PRODUCTION_PATHS = {
    "phase-loop-runtime/src/phase_loop_runtime/cli.py",
    "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    "phase-loop-runtime/src/phase_loop_runtime/injection.py",
    "phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py",
    "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py",
    "phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py",
    "phase-loop-runtime/src/phase_loop_runtime/advisor_board/__init__.py",
    "phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py",
    "phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py",
    "phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py",
    "phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py",
    "phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py",
    "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    "phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py",
    "phase-loop-runtime/src/phase_loop_runtime/reconcile.py",
    "phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    "phase-loop-runtime/scripts/verify_harden_evidence.py",
    "CHANGELOG.md",
}

ANCHORS = {
    "staged-tree-containment": {
        "anchor": "HARDEN-RED-ANCHOR::staged-tree-containment",
        "nodeid": "phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_stage_rejects_every_escape_form_before_launch",
        "source": "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    },
    "cwd-independent-reconcile": {
        "anchor": "HARDEN-RED-ANCHOR::cwd-independent-reconcile",
        "nodeid": "phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_cwd_independent_reconcile_is_repo_anchored",
        "source": "phase-loop-runtime/src/phase_loop_runtime/reconcile.py",
    },
    "non-vacuous-goal-coverage": {
        "anchor": "HARDEN-RED-ANCHOR::non-vacuous-goal-coverage",
        "nodeid": "phase-loop-runtime/tests/test_goal_coverage.py::test_enforce_blocks_every_zero_declared_and_all_bare_legacy_is_distinct",
        "source": "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    },
    "login-shell-interpreter": {
        "anchor": "HARDEN-RED-ANCHOR::login-shell-interpreter",
        "nodeid": "phase-loop-runtime/tests/test_verification_interpreter_guard_221.py::test_argument_consuming_bash_options_and_profile_patch_version_fail_closed",
        "source": "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    },
    "review-leg-isolation": {
        "anchor": "HARDEN-RED-ANCHOR::review-leg-isolation",
        "nodeid": "phase-loop-runtime/tests/test_advisor_board_composition.py::test_review_leg_isolation_refuses_unbound_direct_invocation",
        "source": "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    },
}

ACTIVATED_RED_NODEIDS = (
    ANCHORS["staged-tree-containment"]["nodeid"],
    ANCHORS["cwd-independent-reconcile"]["nodeid"],
    ANCHORS["non-vacuous-goal-coverage"]["nodeid"],
    ANCHORS["login-shell-interpreter"]["nodeid"],
    ANCHORS["review-leg-isolation"]["nodeid"],
    "phase-loop-runtime/tests/test_advisor_board_composition.py::test_derived_review_refuses_missing_or_forged_authority_before_callback",
    "phase-loop-runtime/tests/test_advisor_board_composition.py::test_derived_review_explicit_spawn_remains_hermetic_after_marker",
    "phase-loop-runtime/tests/test_advisor_board_composition.py::test_derived_review_bounded_capture_control_reaches_stage_without_auth",
    "phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_authorizes_before_every_capability_auth_ok",
    "phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_denial_blocks_compose_before_every_probe",
    "phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_covers_default_load_boards_probes",
    "phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_denial_blocks_load_boards_before_every_probe",
    "phase-loop-runtime/tests/test_advisor_board_cli_legacy.py::AdvisorBoardCliTest::test_cli_harden_preflight_authorizes_before_compose_and_invoke",
    "phase-loop-runtime/tests/test_advisor_board_cli_legacy.py::AdvisorBoardCliTest::test_harden_real_invoker_revalidates_canonical_repository_authority",
    "phase-loop-runtime/tests/test_harden_evidence_verifier.py::HardenEvidenceVerifierContractTests::test_harden_review_request_retains_recomputed_git_bound_inputs",
    "phase-loop-runtime/tests/test_harden_evidence_verifier.py::HardenEvidenceVerifierContractTests::test_harden_candidate_and_main_ci_are_separate_authoritative_records",
)
_ACTIVATED_REVIEW_RED_COUNT = 12

ROUTES = {
    "claude": ("claude-fable-5", "claude-fable-5"),
    "codex": ("gpt-5.6-sol", "gpt-5.6-sol"),
    "gemini": ("gemini-3.7-flash", "gemini-3.7-flash-high"),
    "grok": ("grok-4.6", "grok-4.6"),
}
NO_TOOL_CONTROLS = {
    "claude": ("safe-mode", "no-chrome", "disable-slash-commands", "strict-mcp-config", "empty-mcp", "empty-agents", "tools-empty"),
    "codex": ("ignore-user-config", "ignore-rules", "ephemeral", "auth_elicitation", "shell_tool", "apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access", "image_generation", "computer_use", "code_mode_host", "in_app_browser", "in_app_local_automation", "goals", "guardian_approval", "memories", "multi_agent", "hooks", "plugins", "plugin_sharing", "remote_plugin", "shell_snapshot", "skill_mcp_dependency_install", "skill_search", "tool_call_mcp_elicitation", "tool_suggest", "unified_exec", "view_image", "workspace_dependencies", "read-only"),
    "gemini": ("disable-slash-commands", "inline-sealed-input", "no-add-dir", "no-dangerous-permissions"),
    "grok": ("tools-empty", "disable-web-search", "no-memory", "no-subagents", "permission-plan"),
}


class EvidenceError(ValueError):
    """The only expected verifier failure: evidence is unacceptable."""


def fail(message: str) -> None:
    raise EvidenceError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def json_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate JSON key")
        result[key] = value
    return result


def parse_canonical_json(data: bytes, label: str) -> Any:
    if not data or len(data) > MAX_JSON_BYTES:
        fail(f"{label}: invalid JSON byte size")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=json_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label}: invalid JSON")
    if canonical_bytes(value) != data:
        fail(f"{label}: JSON is not canonical")
    return value


def closed(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"{label}: unknown or missing field")
    return value


def text(value: Any, label: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{label}: expected non-empty string")
    if pattern and not pattern.fullmatch(value):
        fail(f"{label}: invalid value")
    return value


def integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        fail(f"{label}: expected integer")
    return value


def artifact_ref(value: Any, label: str) -> dict[str, str]:
    ref = closed(value, {"path", "sha256"}, label)
    return {"path": text(ref["path"], label + ".path"), "sha256": text(ref["sha256"], label + ".sha256", pattern=HEX64)}


def reject_secret_payloads(value: Any, path: str = "evidence") -> None:
    """Reject likely secret values, while allowing metadata *field names*."""
    if isinstance(value, dict):
        for key, item in value.items():
            reject_secret_payloads(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secret_payloads(item, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in ("bearer ", "sk-", "ghp_", "akia", "AIza")):
            fail(f"{path}: possible raw credential payload")


_RAW_SECRET = re.compile(
    rb"(?:-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----|"
    rb"\b(?:bearer|token|api[_-]?key|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}|"
    rb"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b)",
    re.IGNORECASE,
)


def reject_raw_secret_bytes(data: bytes, label: str) -> None:
    """Bounded payload scan; field names such as ``authorization_sha256`` survive."""
    if _RAW_SECRET.search(data):
        fail(f"{label}: possible raw credential payload")


class ArtifactStore:
    """Contained, regular, content-addressed evidence-root file reader."""

    def __init__(self, root: Path) -> None:
        try:
            root_stat = root.lstat()
        except OSError:
            fail("evidence root is unavailable")
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            fail("evidence root must be a real directory")
        self.root = root.resolve(strict=True)
        self._paths: set[str] = set()
        self._digests: set[str] = set()

    def read(self, ref: dict[str, str], label: str, *, distinct: bool = True) -> bytes:
        raw_path = ref["path"]
        candidate = Path(raw_path)
        if candidate.is_absolute() or not raw_path or "\\" in raw_path or any(part in {"", ".", ".."} for part in candidate.parts):
            fail(f"{label}: artifact path escapes evidence root")
        current = self.root
        for part in candidate.parts:
            current = current / part
            try:
                entry = current.lstat()
            except OSError:
                fail(f"{label}: missing artifact")
            if stat.S_ISLNK(entry.st_mode):
                fail(f"{label}: symlink artifact component")
        if not stat.S_ISREG(current.lstat().st_mode):
            fail(f"{label}: artifact is not a regular file")
        try:
            resolved = current.resolve(strict=True)
        except OSError:
            fail(f"{label}: unresolved artifact")
        if self.root not in (resolved, *resolved.parents):
            fail(f"{label}: artifact escapes evidence root")
        data = current.read_bytes()
        if len(data) > MAX_ARTIFACT_BYTES or sha256(data) != ref["sha256"]:
            fail(f"{label}: artifact digest mismatch")
        reject_raw_secret_bytes(data, label)
        if distinct:
            if raw_path in self._paths or ref["sha256"] in self._digests:
                fail(f"{label}: reused artifact")
            self._paths.add(raw_path)
            self._digests.add(ref["sha256"])
        return data

    def json(self, ref: dict[str, str], label: str, *, distinct: bool = True) -> Any:
        value = parse_canonical_json(self.read(ref, label, distinct=distinct), label)
        reject_secret_payloads(value, label)
        return value


def git(repo: Path, *args: str) -> str:
    command = ("git", "-C", str(repo), "--no-replace-objects", "-c", "core.hooksPath=/dev/null", *args)
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if completed.returncode:
        fail("Git authority check failed")
    return completed.stdout.strip()


def git_commit(repo: Path, commit_id: str, tree_id: str, label: str) -> None:
    text(commit_id, label + ".commit", pattern=HEX40)
    text(tree_id, label + ".tree", pattern=HEX40)
    if git(repo, "rev-parse", commit_id + "^{commit}") != commit_id:
        fail(f"{label}: commit is not exact")
    if git(repo, "rev-parse", commit_id + "^{tree}") != tree_id:
        fail(f"{label}: commit/tree mismatch")


def ancestor(repo: Path, older: str, newer: str, label: str) -> None:
    completed = subprocess.run(("git", "-C", str(repo), "--no-replace-objects", "merge-base", "--is-ancestor", older, newer), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if completed.returncode:
        fail(f"{label}: ancestry mismatch")


def changed_paths(repo: Path, older: str, newer: str) -> set[str]:
    out = git(repo, "diff", "--name-only", "--no-renames", older, newer)
    return {line for line in out.splitlines() if line}


def blob(repo: Path, revision: str, path: str) -> tuple[str, bytes]:
    object_id = git(repo, "rev-parse", f"{revision}:{path}")
    if not HEX40.fullmatch(object_id):
        fail("invalid frozen blob")
    data = subprocess.run(("git", "-C", str(repo), "--no-replace-objects", "show", f"{revision}:{path}"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if data.returncode:
        fail("frozen blob unavailable")
    return object_id, data.stdout


def git_bound_review_input(repo: Path, head: str, tree: str, kind: str) -> str:
    """Render the only retained review input form accepted by this reducer.

    The complete recursive tree listing is recomputed from the asserted Git head.
    This makes the retained bytes a deterministic Git-derived snapshot instead of
    an artifact whose content can be replaced and merely resealed by its producer.
    """
    if kind not in {"bundle", "instructions"}:
        fail("unknown retained review input kind")
    listing = git(repo, "ls-tree", "-r", "--full-tree", head)
    return (
        "HARDEN-GIT-BOUND-REVIEW-INPUT.v1\n"
        f"kind={kind}\nhead={head}\ntree={tree}\n"
        f"{listing}\n"
    )


def parse_junit(data: bytes, label: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        fail(f"{label}: invalid JUnit")
    cases: list[dict[str, str]] = []
    for case in root.findall(".//testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        status = "passed"
        detail = ""
        for child in list(case):
            if child.tag in {"failure", "error", "skipped"}:
                status = child.tag
                detail = "".join(child.itertext())
                break
        cases.append({"node": f"{classname}::{name}", "name": name, "status": status, "detail": detail})
    if not cases:
        fail(f"{label}: no concrete test cases")
    return cases


def exact_case(cases: list[dict[str, str]], nodeid: str, status: str, label: str) -> dict[str, str]:
    module_path, function = nodeid.rsplit("::", 1)
    prefix = "phase-loop-runtime/"
    if not module_path.startswith(prefix):
        fail(f"{label}: nodeid is outside phase-loop-runtime")
    module = module_path.removeprefix(prefix).removesuffix(".py").replace("/", ".")
    matches = [case for case in cases if case["node"] == f"{module}::{function}"]
    if len(matches) != 1 or matches[0]["status"] != status:
        fail(f"{label}: expected exact testcase result")
    return matches[0]


def all_passed(cases: list[dict[str, str]], label: str) -> None:
    if any(case["status"] != "passed" for case in cases):
        fail(f"{label}: failures, errors, skips, or xfails are forbidden")


def receipt(store: ArtifactStore, ref: dict[str, str], label: str, *, head: str, tree: str, kind: str, argv_class: str, exit_code: int, raw: dict[str, str], junit: dict[str, str] | None, source_binding: tuple[str, str] | None = None) -> dict[str, Any]:
    value = store.json(ref, label)
    expected = {"schema", "kind", "head", "tree", "process_nonce", "exit_code", "argv_class", "raw_sha256"}
    if junit is not None:
        expected.add("junit_sha256")
    if source_binding is not None:
        expected.update({"source_path", "source_sha256"})
    data = closed(value, expected, label)
    if data["schema"] != "harden_pytest_receipt.v1" or data["kind"] != kind or data["head"] != head or data["tree"] != tree:
        fail(f"{label}: receipt binding mismatch")
    if text(data["process_nonce"], label + ".process_nonce", pattern=HEX64) == "0" * 64:
        fail(f"{label}: placeholder process nonce")
    if integer(data["exit_code"], label + ".exit_code") != exit_code or data["argv_class"] != argv_class or data["raw_sha256"] != raw["sha256"]:
        fail(f"{label}: receipt result mismatch")
    if junit is not None and data["junit_sha256"] != junit["sha256"]:
        fail(f"{label}: receipt JUnit digest mismatch")
    if source_binding is not None and (data["source_path"], data["source_sha256"]) != source_binding:
        fail(f"{label}: receipt source binding mismatch")
    return data


def lint_receipt(store: ArtifactStore, ref: dict[str, str], label: str, *, head: str, tree: str, raw: dict[str, str]) -> str:
    data = closed(store.json(ref, label), {"schema", "head", "tree", "process_nonce", "exit_code", "tool_identity", "argv_class", "checks", "raw_sha256"}, label)
    if data["schema"] != "harden_static_receipt.v1" or data["head"] != head or data["tree"] != tree:
        fail(f"{label}: static head/tree mismatch")
    nonce = text(data["process_nonce"], label + ".process_nonce", pattern=HEX64)
    if nonce == "0" * 64 or integer(data["exit_code"], label + ".exit_code") != 0:
        fail(f"{label}: static receipt failed")
    if data["tool_identity"] != "harden_static_gate.v1" or data["argv_class"] != "harden_static_metadata_only_v1":
        fail(f"{label}: unsupported static tool")
    if data["checks"] != ["py_compile", "ruff", "git_diff_check"] or data["raw_sha256"] != raw["sha256"]:
        fail(f"{label}: static receipt mismatch")
    return nonce


def _marker_state(repo: Path, revision: str, *, required: bool) -> None:
    """Require the final literal marker and reject it on pre-production heads."""
    _, data = blob(repo, revision, "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py")
    try:
        tree = ast.parse(data.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        fail("capability registry is not parseable Python")
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "HARDEN_CAPABILITY_VERSION"
    ]
    literal_one = [node for node in assignments if isinstance(node.value, ast.Constant) and type(node.value.value) is int and node.value.value == 1]
    if required and len(assignments) != 1 or required and len(literal_one) != 1:
        fail("final capability marker is missing, duplicate, or nonliteral")
    if not required and assignments:
        fail("pre-production capability marker is present")


def verify_git_and_inventory(repo: Path, git_data: dict[str, Any], sl0: dict[str, Any]) -> dict[str, tuple[str, str]]:
    git_data = closed(git_data, {"sl0_base", "landing_first_parent", "reviewed_sl0", "landing", "candidate", "canonical_main"}, "git")
    commits: dict[str, tuple[str, str]] = {}
    for name in git_data:
        item = closed(git_data[name], {"commit", "tree"}, "git." + name)
        git_commit(repo, item["commit"], item["tree"], "git." + name)
        commits[name] = (item["commit"], item["tree"])
    base, first_parent, reviewed, landing, candidate, main = (commits[name][0] for name in ("sl0_base", "landing_first_parent", "reviewed_sl0", "landing", "candidate", "canonical_main"))
    ancestor(repo, base, first_parent, "landing first parent")
    ancestor(repo, base, reviewed, "reviewed SL-0")
    reviewed_changes = changed_paths(repo, base, reviewed)
    if git(repo, "merge-base", first_parent, reviewed) != base or not reviewed_changes or not reviewed_changes <= set(FROZEN_SL0_PATHS):
        fail("reviewed SL-0 is not a nonempty frozen-tests-only change from SL-0 base")
    parents = git(repo, "show", "-s", "--format=%P", landing).split()
    if parents != [first_parent, reviewed]:
        fail("landing merge topology is not landing-first-parent plus reviewed SL-0")
    ancestor(repo, landing, candidate, "candidate")
    ancestor(repo, candidate, main, "canonical main")
    if commits["candidate"][1] != commits["canonical_main"][1] or changed_paths(repo, candidate, main):
        fail("canonical main does not preserve the exact candidate tree")
    candidate_paths = changed_paths(repo, landing, candidate)
    if not candidate_paths or not candidate_paths <= PLAN_PRODUCTION_PATHS:
        fail("candidate changed paths escape HARDEN ownership")
    sl0 = closed(sl0, {"frozen_inventory", "activated_red", "pure_control", "mutations"}, "sl0")
    inventory = sl0["frozen_inventory"]
    if not isinstance(inventory, list) or len(inventory) != len(FROZEN_SL0_PATHS):
        fail("frozen inventory count mismatch")
    supplied = {entry.get("path") for entry in inventory if isinstance(entry, dict)}
    if supplied != set(FROZEN_SL0_PATHS):
        fail("frozen inventory paths mismatch")
    revisions = {"reviewed": reviewed, "landing": landing, "candidate": candidate, "canonical_main": main}
    for entry in inventory:
        entry = closed(entry, {"path", "reviewed", "landing", "candidate", "canonical_main"}, "frozen inventory entry")
        for stage, revision in revisions.items():
            record = closed(entry[stage], {"blob", "sha256", "bytes"}, "frozen." + stage)
            object_id, data = blob(repo, revision, entry["path"])
            if record["blob"] != object_id or record["sha256"] != sha256(data) or integer(record["bytes"], "frozen.bytes") != len(data):
                fail("frozen inventory blob mismatch")
        first = entry["reviewed"]
        if any(entry[stage] != first for stage in ("landing", "candidate", "canonical_main")):
            fail("frozen test changed after reviewed SL-0")
    _marker_state(repo, reviewed, required=False)
    _marker_state(repo, landing, required=False)
    _marker_state(repo, candidate, required=True)
    _marker_state(repo, main, required=True)
    return commits


def claim_nonce(value: str, used: set[str], label: str) -> None:
    if value in used:
        fail(f"{label}: reused operation nonce")
    used.add(value)


def verify_preproduction(store: ArtifactStore, sl0: dict[str, Any], reviewed: str, reviewed_tree: str, used_nonces: set[str], repo: Path) -> None:
    activated = closed(sl0["activated_red"], {"receipt", "raw", "junit"}, "activated RED")
    raw = artifact_ref(activated["raw"], "activated RED.raw")
    junit = artifact_ref(activated["junit"], "activated RED.junit")
    claim_nonce(receipt(store, artifact_ref(activated["receipt"], "activated RED.receipt"), "activated RED receipt", head=reviewed, tree=reviewed_tree, kind="activated_red", argv_class="pytest_harden_activated_v1", exit_code=1, raw=raw, junit=junit)["process_nonce"], used_nonces, "activated RED")
    raw_text = store.read(raw, "activated RED raw").decode("utf-8", "replace")
    cases = parse_junit(store.read(junit, "activated RED JUnit"), "activated RED JUnit")
    failures = [case for case in cases if case["status"] == "failure"]
    passed = [case for case in cases if case["status"] == "passed"]
    skipped = [case for case in cases if case["status"] == "skipped"]
    if len(failures) != 16 or len(passed) != 439 or len(skipped) != 3 or any(case["status"] == "error" for case in cases):
        fail("activated RED shape must be 16 failed, 439 passed, 3 skipped")
    for nodeid in ACTIVATED_RED_NODEIDS:
        exact_case(cases, nodeid, "failure", "activated RED")
    for item in ANCHORS.values():
        exact_case(cases, item["nodeid"], "failure", "activated RED")
        expected_count = _ACTIVATED_REVIEW_RED_COUNT if item is ANCHORS["review-leg-isolation"] else 1
        if raw_text.count(item["anchor"]) != expected_count:
            fail("activated RED anchor count mismatch")
    if re.search(r"\b(?:ERROR|XFAIL|XPASS)\b", raw_text) or "16 failed, 439 passed, 3 skipped" not in raw_text or "17 subtests passed" not in raw_text:
        fail("activated RED has unrelated outcome")
    pure = closed(sl0["pure_control"], {"receipt", "raw", "junit"}, "pre-production pure control")
    pure_raw = artifact_ref(pure["raw"], "pre-production pure raw")
    pure_junit = artifact_ref(pure["junit"], "pre-production pure junit")
    claim_nonce(receipt(store, artifact_ref(pure["receipt"], "pre-production pure receipt"), "pre-production pure receipt", head=reviewed, tree=reviewed_tree, kind="pure_control", argv_class="pytest_harden_pure_control_v1", exit_code=0, raw=pure_raw, junit=pure_junit)["process_nonce"], used_nonces, "pre-production pure")
    all_passed(parse_junit(store.read(pure_junit, "pre-production pure junit"), "pre-production pure junit"), "pre-production pure control")
    mutations = sl0["mutations"]
    if not isinstance(mutations, list) or len(mutations) != len(ANCHORS):
        fail("source-entered mutation coverage is incomplete")
    seen: set[str] = set()
    for entry in mutations:
        entry = closed(entry, {"case_id", "source_path", "nodeid", "mutated_source", "restored_source", "mutation", "restored"}, "mutation entry")
        case_id = text(entry["case_id"], "mutation case")
        expected = ANCHORS.get(case_id)
        if expected is None or case_id in seen or entry["source_path"] != expected["source"] or entry["nodeid"] != expected["nodeid"]:
            fail("mutation source/case binding mismatch")
        seen.add(case_id)
        reviewed_blob, reviewed_bytes = blob(repo, reviewed, expected["source"])
        restored_source = artifact_ref(entry["restored_source"], "restored source")
        mutated_source = artifact_ref(entry["mutated_source"], "mutated source")
        restored_bytes = store.read(restored_source, "restored source")
        mutated_bytes = store.read(mutated_source, "mutated source")
        if restored_bytes != reviewed_bytes or restored_source["sha256"] != sha256(reviewed_bytes) or mutated_bytes == reviewed_bytes:
            fail("source mutation/restoration bytes do not bind reviewed source")
        for phase, expected_kind, expected_exit, expected_argv, expected_status, marker in (
            ("mutation", "source_mutation", 1, "pytest_harden_source_mutation_v1", "failure", "HARDEN-MUTATION-BITE::" + case_id),
            ("restored", "restored_control", 0, "pytest_harden_restored_control_v1", "passed", "HARDEN-RESTORED-CONTROL::" + case_id),
        ):
            result = closed(entry[phase], {"receipt", "raw", "junit"}, "mutation " + phase)
            phase_raw = artifact_ref(result["raw"], "mutation raw")
            phase_junit = artifact_ref(result["junit"], "mutation junit")
            source_sha = mutated_source["sha256"] if phase == "mutation" else restored_source["sha256"]
            record = receipt(store, artifact_ref(result["receipt"], "mutation receipt"), "mutation receipt", head=reviewed, tree=reviewed_tree, kind=expected_kind, argv_class=expected_argv, exit_code=expected_exit, raw=phase_raw, junit=phase_junit, source_binding=(expected["source"], source_sha))
            claim_nonce(record["process_nonce"], used_nonces, "mutation receipt")
            raw_text = store.read(phase_raw, "mutation raw").decode("utf-8", "replace")
            cases = parse_junit(store.read(phase_junit, "mutation junit"), "mutation junit")
            if marker not in raw_text:
                fail("mutation chronology marker absent")
            exact_case(cases, expected["nodeid"], expected_status, "mutation chronology")
            if phase == "mutation":
                if len(cases) != 1 or cases[0]["status"] != "failure":
                    fail("mutation was not uniquely biting")
            else:
                all_passed(cases, "restored control")
    if seen != set(ANCHORS):
        fail("mutation cases do not cover every HARDEN anchor")


def verify_final_group(store: ArtifactStore, group: Any, label: str, commit_id: str, tree_id: str, used_nonces: set[str]) -> None:
    data = closed(group, {"commit", "tree", "run_nonce", "focused", "pure_control", "broad", "lint"}, label)
    if data["commit"] != commit_id or data["tree"] != tree_id:
        fail(f"{label}: head/tree mismatch")
    run_nonce = text(data["run_nonce"], label + ".run_nonce", pattern=HEX64)
    if run_nonce == "0" * 64 or run_nonce in used_nonces:
        fail(f"{label}: reused or placeholder process nonce")
    used_nonces.add(run_nonce)
    for key, kind, argv in (
        ("focused", "focused_activated", "pytest_harden_focused_activated_v1"),
        ("pure_control", "pure_control", "pytest_harden_pure_control_v1"),
        ("broad", "broad", "pytest_harden_broad_v1"),
    ):
        result = closed(data[key], {"receipt", "raw", "junit"}, label + "." + key)
        raw = artifact_ref(result["raw"], label + "." + key + ".raw")
        junit = artifact_ref(result["junit"], label + "." + key + ".junit")
        record = receipt(store, artifact_ref(result["receipt"], label + "." + key + ".receipt"), label + "." + key + ".receipt", head=commit_id, tree=tree_id, kind=kind, argv_class=argv, exit_code=0, raw=raw, junit=junit)
        nonce = record["process_nonce"]
        if nonce in used_nonces:
            fail(f"{label}: reused fresh-process nonce")
        used_nonces.add(nonce)
        all_passed(parse_junit(store.read(junit, label + "." + key + ".junit"), label + "." + key + ".junit"), label + "." + key)
    lint = closed(data["lint"], {"receipt", "raw"}, label + ".lint")
    lint_raw = artifact_ref(lint["raw"], label + ".lint.raw")
    lint_nonce = lint_receipt(store, artifact_ref(lint["receipt"], label + ".lint.receipt"), label + ".lint.receipt", head=commit_id, tree=tree_id, raw=lint_raw)
    if lint_nonce in used_nonces:
        fail(f"{label}: reused lint process nonce")
    used_nonces.add(lint_nonce)
    if not store.read(lint_raw, label + ".lint.raw").strip():
        fail(f"{label}: empty lint receipt output")


def query_ci(ci: dict[str, Any], query: Path) -> None:
    if not query.is_file() or not os.access(query, os.X_OK):
        fail("authoritative CI query is unavailable")
    command = (str(query), "run", "view", str(ci["run_id"]), "--repo", ci["repository"], "--json", "databaseId,headSha,status,conclusion,event,workflowName,attempt")
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=20)
    if completed.returncode:
        fail("authoritative CI query failed")
    try:
        response = json.loads(completed.stdout.decode("utf-8"), object_pairs_hook=json_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("CI provider returned invalid JSON")
    response = closed(response, {"databaseId", "headSha", "status", "conclusion", "event", "workflowName", "attempt"}, "CI provider response")
    if response != {"databaseId": ci["run_id"], "headSha": ci["head"], "status": "completed", "conclusion": "success", "event": ci["event"], "workflowName": ci["workflow"], "attempt": ci["run_attempt"]}:
        fail("authoritative CI state does not bind evidence")


def verify_ci(data: Any, candidate: str, main: str, repository: str, query: Path) -> None:
    groups = closed(data, {"candidate", "canonical_main"}, "ci")
    run_ids: set[int] = set()
    for label, head in (("candidate", candidate), ("canonical_main", main)):
        ci = closed(groups[label], {"provider", "repository", "run_id", "workflow", "event", "run_attempt", "head"}, "ci." + label)
        if ci["provider"] != "github_actions" or ci["head"] != head or ci["repository"] != repository:
            fail("unsupported CI provider or wrong CI head")
        text(ci["repository"], "ci.repository", pattern=IDENTITY)
        text(ci["workflow"], "ci.workflow", pattern=IDENTITY)
        text(ci["event"], "ci.event", pattern=IDENTITY)
        run_id = integer(ci["run_id"], "ci.run_id", minimum=1)
        if run_id in run_ids:
            fail("candidate and canonical-main CI runs must be distinct")
        run_ids.add(run_id)
        integer(ci["run_attempt"], "ci.run_attempt", minimum=1)
        query_ci(ci, query)


def verify_broker(value: Any, harness: str, requested: str, resolved: str, bundle_sha256: str, instructions_sha256: str) -> None:
    common = {
        "schema", "stage_bundle_sha256", "stage_instructions_sha256", "leg_authorization_issued_monotonic_ns", "leg_authorization_expires_monotonic_ns", "canonical_repo_sha256", "canonical_repo_probe_file_sha256", "cleanup_root_removed", "host_secret_probe_removed", "child_quiescent", "peer_pid", "peer_uid", "peer_gid", "peer_ancestry_verified", "bwrap", "outer_bwrap_pid", "outer_bwrap_start", "network_unshared", "close_fds_requested", "socket", "stage", "argv_sha256", "socket_present_before_launch", "stage_bundle_mode", "stage_instructions_mode", "client_probe_program_sha256", "client_probe_assertions", "canonical_repo_file_denied", "canonical_repo_directory_denied", "host_stage_path_denied", "no_inherited_fd_observed", "child_stderr_sha256", "child_returncode", "operation_deadline_s", "child_timeout", "broker_thread_quiescent", "provider_adapter_quiescent", "provider_cancel_requested", "provider_input_sha256", "provider_input_bytes", "provider_input_inline", "provider_live_tree_cwd", "provider_harness", "provider_model", "provider_argv_shape", "provider_argv_sha256", "provider_prompt_sha256", "provider_prompt_bytes", "provider_prompt_transport", "provider_cwd_class", "provider_cwd_sha256", "provider_env_keys", "provider_env_api_keys_scrubbed", "provider_env_direct_routes_scrubbed", "provider_no_tool_controls",
    }
    claude = {"claude_session_id_sha256", "claude_session_resume_forbidden", "claude_transcript_exact_path_sha256", "claude_transcript_preexisting", "claude_transcript_existed", "claude_transcript_sha256", "claude_transcript_bytes", "claude_transcript_cleanup_verified"}
    broker = closed(value, common | (claude if harness == "claude" else set()), "broker evidence")
    for field in ("stage_bundle_sha256", "stage_instructions_sha256", "canonical_repo_sha256", "canonical_repo_probe_file_sha256", "argv_sha256", "client_probe_program_sha256", "child_stderr_sha256", "provider_input_sha256", "provider_argv_sha256", "provider_prompt_sha256", "provider_cwd_sha256"):
        if text(broker[field], "broker." + field, pattern=HEX64) == "0" * 64:
            fail("broker digest placeholder")
    if broker["stage_bundle_sha256"] != bundle_sha256 or broker["stage_instructions_sha256"] != instructions_sha256:
        fail("broker staged inputs do not bind review request")
    if broker["schema"] != BROKER_SCHEMA or broker["bwrap"] != "/usr/bin/bwrap" or broker["socket"] != "/run/phase-loop-broker/intended-inference.sock" or broker["stage"] != "/run/phase-loop-review":
        fail("broker transport is not the required isolated transport")
    issued = integer(broker["leg_authorization_issued_monotonic_ns"], "broker.issued", minimum=1)
    expires = integer(broker["leg_authorization_expires_monotonic_ns"], "broker.expires", minimum=issued + 1)
    if expires - issued > 3605 * 1_000_000_000:
        fail("broker leg authorization is not short-lived")
    if not all(broker[field] is True for field in ("cleanup_root_removed", "host_secret_probe_removed", "child_quiescent", "peer_ancestry_verified", "network_unshared", "close_fds_requested", "socket_present_before_launch", "canonical_repo_file_denied", "canonical_repo_directory_denied", "host_stage_path_denied", "no_inherited_fd_observed", "broker_thread_quiescent", "provider_adapter_quiescent", "provider_input_inline", "provider_env_api_keys_scrubbed", "provider_env_direct_routes_scrubbed")):
        fail("broker evidence has failed isolation, cleanup, or quiescence fact")
    if broker["provider_live_tree_cwd"] is not False or broker["child_timeout"] is not False or broker["provider_cancel_requested"] is not False or integer(broker["child_returncode"], "broker.child_returncode") != 0:
        fail("broker evidence permits live tree or timeout")
    for field in ("peer_pid", "peer_uid", "peer_gid", "outer_bwrap_pid", "outer_bwrap_start", "provider_input_bytes", "provider_prompt_bytes"):
        integer(broker[field], "broker." + field, minimum=1)
    if not isinstance(broker["operation_deadline_s"], (int, float)) or isinstance(broker["operation_deadline_s"], bool) or broker["operation_deadline_s"] <= 0:
        fail("broker operation deadline is invalid")
    if broker["stage_bundle_mode"] != 0o400 or broker["stage_instructions_mode"] != 0o400:
        fail("immutable staged inputs are not read-only")
    assertions = broker["client_probe_assertions"]
    if assertions != ["credentialless_env", "readonly_stage", "no_live_bundle", "no_live_instructions", "no_host_secret", "no_live_tree", "no_inherited_fd", "fixed_socket_only", "no_af_inet"]:
        fail("broker client probes are incomplete")
    if broker["provider_harness"] != harness or broker["provider_model"] != resolved or broker["provider_cwd_class"] != "owned_empty_scratch":
        fail("broker harness/model provenance mismatch")
    if not isinstance(broker["provider_argv_shape"], list) or not broker["provider_argv_shape"] or any(not isinstance(item, str) or not item for item in broker["provider_argv_shape"]):
        fail("broker provider argv shape is malformed")
    if broker["provider_input_sha256"] != broker["provider_prompt_sha256"] or broker["provider_input_bytes"] != broker["provider_prompt_bytes"]:
        fail("broker provider input/prompt evidence is inconsistent")
    env_keys = broker["provider_env_keys"]
    if not isinstance(env_keys, list) or any(not isinstance(key, str) or not key for key in env_keys) or env_keys != sorted(env_keys) or len(env_keys) != len(set(env_keys)) or any(re.search(r"API_KEY|BASE_URL|GATEWAY|RESEARCH|PROVIDER|^(?:AGY|ANTIGRAVITY|GEMINI|XDG_CONFIG)_", key, re.I) for key in env_keys):
        fail("broker provider environment permits direct route metadata")
    controls = broker["provider_no_tool_controls"]
    if controls != list(NO_TOOL_CONTROLS[harness]):
        fail("broker no-tool controls are incomplete")
    if harness == "claude":
        if broker["provider_prompt_transport"] != "pty_input" or not all(broker[name] is True for name in ("claude_session_resume_forbidden", "claude_transcript_existed", "claude_transcript_cleanup_verified")) or broker["claude_transcript_preexisting"] is not False:
            fail("Claude owned-session proof is incomplete")
        for field in ("claude_session_id_sha256", "claude_transcript_exact_path_sha256", "claude_transcript_sha256"):
            text(broker[field], "broker." + field, pattern=HEX64)
        integer(broker["claude_transcript_bytes"], "broker.claude_transcript_bytes", minimum=1)
    elif broker["provider_prompt_transport"] != "argv_inline" or not isinstance(broker["provider_argv_shape"], list) or broker["provider_argv_shape"].count("<SEALED_INLINE_PROMPT>") != 1:
        fail("non-Claude broker evidence has unsafe prompt transport")


def verify_review_round(store: ArtifactStore, repo: Path, value: Any, round_name: str, head: str, tree: str, used_seat_ids: set[str], seat_sessions: set[str], operation_nonces: set[str]) -> None:
    round_data = closed(value, {"head", "tree", "request", "seats"}, "review " + round_name)
    if round_data["head"] != head or round_data["tree"] != tree:
        fail("review round head/tree mismatch")
    request_ref = artifact_ref(round_data["request"], "review request")
    request = closed(store.json(request_ref, "review request"), {"schema", "round", "head", "tree", "bundle", "instructions", "request_nonce", "seats"}, "review request")
    if request["schema"] != "harden_review_request.v1" or request["round"] != round_name or request["head"] != head or request["tree"] != tree:
        fail("review request is stale or malformed")
    input_digests: dict[str, str] = {}
    for kind in ("bundle", "instructions"):
        input_ref = artifact_ref(request[kind], "review request " + kind)
        input_record = closed(
            store.json(input_ref, "review request " + kind),
            {"schema", "kind", "head", "tree", "content"},
            "review request " + kind,
        )
        if (
            input_record["schema"] != "harden_review_input.v1"
            or input_record["kind"] != kind
            or input_record["head"] != head
            or input_record["tree"] != tree
        ):
            fail("review input head/tree binding mismatch")
        content = text(input_record["content"], "review input content")
        if content != git_bound_review_input(repo, head, tree, kind):
            fail("retained review input is not independently Git-bound")
        input_digests[kind] = sha256(content.encode("utf-8"))
    text(request["request_nonce"], "request nonce", pattern=HEX64)
    claim_nonce(request["request_nonce"], operation_nonces, "review request")
    request_seats = request["seats"]
    if not isinstance(request_seats, list) or len(request_seats) != len(ROUTES):
        fail("review request routes mismatch")
    request_routes: set[tuple[str, str]] = set()
    for request_seat in request_seats:
        request_seat = closed(request_seat, {"harness", "requested_model"}, "review request seat")
        route = (text(request_seat["harness"], "request harness"), text(request_seat["requested_model"], "request model"))
        if route in request_routes:
            fail("duplicate review request route")
        request_routes.add(route)
    if request_routes != {(harness, requested) for harness, (requested, _resolved) in ROUTES.items()}:
        fail("review request routes mismatch")
    seats = round_data["seats"]
    if not isinstance(seats, list) or len(seats) != 4:
        fail("review round must contain exactly four seats")
    seen_harnesses: set[str] = set()
    for item in seats:
        item = closed(item, {"harness", "artifact"}, "review seat reference")
        harness = text(item["harness"], "seat harness")
        if harness not in ROUTES or harness in seen_harnesses:
            fail("duplicate or unsupported review harness")
        seen_harnesses.add(harness)
        seat = closed(store.json(artifact_ref(item["artifact"], "seat artifact"), "seat artifact"), {"schema", "round", "head", "tree", "request_sha256", "harness", "requested_model", "resolved_model", "seat_id", "session_sha256", "harness_provenance", "status", "result_kind", "report", "report_sha256", "report_bytes", "broker"}, "seat artifact")
        requested, resolved = ROUTES[harness]
        if (seat["schema"], seat["round"], seat["head"], seat["tree"], seat["request_sha256"], seat["harness"], seat["requested_model"], seat["resolved_model"]) != ("harden_review_seat.v1", round_name, head, tree, request_ref["sha256"], harness, requested, resolved):
            fail("seat route/head/request binding mismatch")
        if seat["harness_provenance"] != "brokered_subscription_cli" or seat["status"] != "usable" or seat["result_kind"] != "real_subscription_inference":
            fail("synthetic, unavailable, or non-brokered review seat")
        seat_id = text(seat["seat_id"], "seat identity", pattern=IDENTITY)
        session = text(seat["session_sha256"], "seat session", pattern=HEX64)
        if seat_id in used_seat_ids or session in seat_sessions:
            fail("reused review seat/session identity")
        used_seat_ids.add(seat_id)
        seat_sessions.add(session)
        claim_nonce(session, operation_nonces, "review seat")
        report = text(seat["report"], "seat report")
        if report.rstrip().splitlines()[-1] != "AGREE" or sha256(report.encode()) != seat["report_sha256"] or integer(seat["report_bytes"], "seat report bytes") != len(report.encode()):
            fail("review seat has no terminal usable AGREE")
        verify_broker(seat["broker"], harness, requested, resolved, input_digests["bundle"], input_digests["instructions"])
    if seen_harnesses != set(ROUTES):
        fail("review round lacks a required route")


def verify_roles(store: ArtifactStore, value: Any, evidence_id: str, expected_coordinator_session: str, expected_author_session: str, seat_sessions: set[str]) -> None:
    roles = closed(value, {"coordinator", "author", "reviewer"}, "roles")
    identities: set[str] = set()
    sessions: set[str] = set()
    for role in ("coordinator", "author", "reviewer"):
        record = closed(store.json(artifact_ref(roles[role], "role artifact"), "role artifact"), {"schema", "role", "identity", "vendor", "session_sha256", "evidence_id", "issued_at"}, "role artifact")
        if record["schema"] != "harden_role_attestation.v1" or record["role"] != role or record["evidence_id"] != evidence_id:
            fail("role artifact binding mismatch")
        identity = text(record["identity"], "role identity", pattern=IDENTITY)
        session = text(record["session_sha256"], "role session", pattern=HEX64)
        text(record["vendor"], "role vendor", pattern=IDENTITY)
        text(record["issued_at"], "role timestamp", pattern=IDENTITY)
        if identity in identities or session in sessions or identity.lower() in {"unknown", "none", "null", "placeholder"}:
            fail("role identity/session is reused or placeholder")
        identities.add(identity)
        sessions.add(session)
        if role == "coordinator" and session != expected_coordinator_session:
            fail("coordinator session does not match external authority")
        if role == "author" and (record["vendor"] != "codex-gpt-5.6-terra" or session != expected_author_session):
            fail("sole author session/vendor provenance mismatch")
        if role == "reviewer":
            derived = sha256("\0".join(sorted(seat_sessions)).encode())
            if session != derived or identity != "reviewer-" + derived[:32]:
                fail("reviewer identity/session is not derived from all brokered seats")


def verify_reuse_registry(registry_path: Path, evidence_root: Path, evidence_id: str, operation_nonces: set[str]) -> None:
    try:
        entry = registry_path.lstat()
        root = evidence_root.resolve(strict=True)
        resolved = registry_path.resolve(strict=True)
    except OSError:
        fail("external reuse registry is unavailable")
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode) or root in (resolved, *resolved.parents):
        fail("reuse registry must be an external regular file")
    registry = closed(parse_canonical_json(registry_path.read_bytes(), "reuse registry"), {"schema", "evidence_ids", "operation_nonces"}, "reuse registry")
    if registry["schema"] != "harden_evidence_registry.v1" or not isinstance(registry["evidence_ids"], list) or not isinstance(registry["operation_nonces"], list):
        fail("reuse registry schema mismatch")
    ids = [text(item, "registered evidence id", pattern=HEX64) for item in registry["evidence_ids"]]
    nonces = [text(item, "registered operation nonce", pattern=HEX64) for item in registry["operation_nonces"]]
    if len(ids) != len(set(ids)) or len(nonces) != len(set(nonces)) or evidence_id in ids or operation_nonces & set(nonces):
        fail("evidence or operation nonce was already used")


def normalized_precompletion_digest(evidence: dict[str, Any]) -> str:
    """Stable digest first verified before a normal completion ledger append."""
    normalized = copy.deepcopy(evidence)
    normalized["completion"] = {"mode": "pre_completion"}
    return sha256(canonical_bytes(normalized))


def verify_completion(store: ArtifactStore, value: Any, evidence_digest: str, main: str, tree: str) -> None:
    if not isinstance(value, dict) or "authorized" in value:
        fail("completion authority cannot be self-reported")
    mode = value.get("mode")
    if mode == "pre_completion":
        closed(value, {"mode"}, "completion")
        return
    completion = closed(value, {"mode", "ledger"}, "completion")
    if completion["mode"] != "post_completion":
        fail("unsupported completion mode")
    ledger = store.read(artifact_ref(completion["ledger"], "completion ledger"), "completion ledger")
    matches = 0
    for line in ledger.splitlines():
        try:
            event = json.loads(line.decode("utf-8"), object_pairs_hook=json_no_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError):
            fail("completion ledger event is invalid JSON")
        if not isinstance(event, dict):
            fail("completion ledger event is not an object")
        if event.get("phase") != "HARDEN" or event.get("status") != "complete":
            continue
        metadata = event.get("metadata")
        if not isinstance(metadata, dict) or "harden_completion" not in metadata:
            continue
        proof = closed(metadata["harden_completion"], {"schema", "evidence_sha256", "canonical_commit", "canonical_tree", "visual_render_declared"}, "completion authority")
        if proof != {"schema": "harden_completion.v1", "evidence_sha256": evidence_digest, "canonical_commit": main, "canonical_tree": tree, "visual_render_declared": False}:
            fail("completion authority does not bind verified evidence")
        matches += 1
    if matches != 1:
        fail("completion ledger has missing or duplicate HARDEN completion")


def verify(evidence_path: Path, evidence_root: Path, repo: Path, *, reuse_registry: Path, expected_coordinator_session: str, expected_author_session: str, ci_query: Path = CANONICAL_GH) -> None:
    evidence_bytes = evidence_path.read_bytes()
    evidence = parse_canonical_json(evidence_bytes, "verification evidence")
    reject_secret_payloads(evidence)
    data = closed(evidence, {"schema", "evidence_id", "repository", "git", "sl0", "verification", "ci", "reviews", "roles", "completion"}, "verification evidence")
    if data["schema"] != SCHEMA:
        fail("unsupported evidence schema")
    evidence_id = text(data["evidence_id"], "evidence_id", pattern=HEX64)
    if evidence_id == "0" * 64:
        fail("placeholder evidence_id")
    text(expected_coordinator_session, "expected coordinator session", pattern=HEX64)
    required_author = sha256(b"01a04424-61d9-7712-94a6-e058cbe1349e")
    if text(expected_author_session, "expected author session", pattern=HEX64) != required_author:
        fail("expected author session is not the sole-author authority")
    if text(data["repository"], "repository", pattern=IDENTITY) != "Consiliency/agent-harness":
        fail("verification evidence is not bound to Consiliency/agent-harness")
    store = ArtifactStore(evidence_root)
    commits = verify_git_and_inventory(repo, data["git"], data["sl0"])
    reviewed, reviewed_tree = commits["reviewed_sl0"]
    candidate, candidate_tree = commits["candidate"]
    main, main_tree = commits["canonical_main"]
    nonces: set[str] = set()
    verify_preproduction(store, data["sl0"], reviewed, reviewed_tree, nonces, repo)
    verification = closed(data["verification"], {"candidate", "canonical_main"}, "verification")
    verify_final_group(store, verification["candidate"], "candidate verification", candidate, candidate_tree, nonces)
    verify_final_group(store, verification["canonical_main"], "canonical-main verification", main, main_tree, nonces)
    verify_ci(data["ci"], candidate, main, data["repository"], ci_query)
    reviews = closed(data["reviews"], {"candidate", "canonical_main"}, "reviews")
    seat_ids: set[str] = set()
    seat_sessions: set[str] = set()
    verify_review_round(store, repo, reviews["candidate"], "candidate", candidate, candidate_tree, seat_ids, seat_sessions, nonces)
    verify_review_round(store, repo, reviews["canonical_main"], "canonical_main", main, main_tree, seat_ids, seat_sessions, nonces)
    if len(seat_sessions) != 8:
        fail("reviewer authority lacks eight unique seat sessions")
    verify_roles(store, data["roles"], evidence_id, expected_coordinator_session, expected_author_session, seat_sessions)
    verify_reuse_registry(reuse_registry, evidence_root, evidence_id, nonces)
    verify_completion(store, data["completion"], normalized_precompletion_digest(data), main, main_tree)


# The fixture below is deliberately ephemeral.  It is a verifier exercise, not
# retained evidence and it never imports the runtime or invokes a provider.
def _run(command: list[str], cwd: Path) -> str:
    done = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if done.returncode:
        raise RuntimeError("self-test git setup failed")
    return done.stdout.strip()


def _self_git(root: Path) -> tuple[Path, dict[str, tuple[str, str]]]:
    repo = root / "repo"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "self-test@example.invalid"], repo)
    _run(["git", "config", "user.name", "HARDEN self-test"], repo)
    for path in FROZEN_SL0_PATHS:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("base " + path + "\n")
    (repo / "phase-loop-runtime/src/phase_loop_runtime").mkdir(parents=True)
    (repo / "phase-loop-runtime/src/phase_loop_runtime/runner.py").write_text("base\n")
    (repo / "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py").write_text("# marker intentionally absent before HARDEN final heads\n")
    for anchor in ANCHORS.values():
        target = repo / anchor["source"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("source " + anchor["source"] + "\n")
    _run(["git", "add", "."], repo); _run(["git", "commit", "-qm", "base"], repo)
    base = _run(["git", "rev-parse", "HEAD"], repo)
    _run(["git", "checkout", "-qb", "review"], repo)
    for path in FROZEN_SL0_PATHS[:2]:
        target = repo / path
        target.write_text("reviewed " + path + "\n")
    _run(["git", "add", "."], repo); _run(["git", "commit", "-qm", "reviewed sl0"], repo)
    reviewed = _run(["git", "rev-parse", "HEAD"], repo)
    _run(["git", "checkout", "-q", "master"], repo)
    (repo / "phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py").write_text("intervening runtime merge input\n")
    _run(["git", "add", "."], repo); _run(["git", "commit", "-qm", "intervening runtime"], repo)
    first_parent = _run(["git", "rev-parse", "HEAD"], repo)
    _run(["git", "merge", "--no-ff", "-qm", "landing", "review"], repo)
    landing = _run(["git", "rev-parse", "HEAD"], repo)
    (repo / "phase-loop-runtime/src/phase_loop_runtime/runner.py").write_text("candidate\n")
    (repo / "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py").write_text("HARDEN_CAPABILITY_VERSION = 1\n")
    _run(["git", "add", "."], repo); _run(["git", "commit", "-qm", "candidate"], repo)
    candidate = _run(["git", "rev-parse", "HEAD"], repo)
    _run(["git", "commit", "--allow-empty", "-qm", "canonical main"], repo)
    main = _run(["git", "rev-parse", "HEAD"], repo)
    def record(commit_id: str) -> tuple[str, str]:
        return commit_id, _run(["git", "rev-parse", commit_id + "^{tree}"], repo)
    return repo, {"sl0_base": record(base), "landing_first_parent": record(first_parent), "reviewed_sl0": record(reviewed), "landing": record(landing), "candidate": record(candidate), "canonical_main": record(main)}


def _fixture(root: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    repo, refs = _self_git(root)
    artifacts = root / "artifacts"; artifacts.mkdir()
    serial = 0
    def put(name: str, value: Any, *, raw: bool = False) -> dict[str, str]:
        nonlocal serial
        serial += 1
        path = f"{serial:03d}-{name}"
        data = value if raw else canonical_bytes(value)
        (artifacts / path).write_bytes(data)
        return {"path": path, "sha256": sha256(data)}
    def nonce(label: str) -> str: return sha256(label.encode())
    reviewed, reviewed_tree = refs["reviewed_sl0"]
    candidate, candidate_tree = refs["candidate"]
    main, main_tree = refs["canonical_main"]
    def junit(name: str, status: str, nodeid: str = "pkg::case") -> dict[str, str]:
        function = nodeid.rsplit("::", 1)[1]
        module_path = nodeid.rsplit("::", 1)[0]
        module = module_path.removeprefix("phase-loop-runtime/").removesuffix(".py").replace("/", ".")
        tag = "" if status == "passed" else f"<{status}>{name}</{status}>"
        return put(name + ".xml", f'<testsuite><testcase classname="{module}" name="{function}">{tag}<system-out>{name}</system-out></testcase></testsuite>'.encode(), raw=True)
    def receipt_art(kind: str, head: str, tree: str, raw: dict[str, str], junit_ref: dict[str, str] | None, exit_code: int, argv: str, source: tuple[str, str] | None = None) -> dict[str, str]:
        item: dict[str, Any] = {"schema": "harden_pytest_receipt.v1", "kind": kind, "head": head, "tree": tree, "process_nonce": nonce(f"receipt-{serial}-{kind}"), "exit_code": exit_code, "argv_class": argv, "raw_sha256": raw["sha256"]}
        if junit_ref is not None: item["junit_sha256"] = junit_ref["sha256"]
        if source is not None: item.update({"source_path": source[0], "source_sha256": source[1]})
        return put("receipt-" + kind, item)
    def pytest_art(kind: str, head: str, tree: str, status: str, nodeid: str, argv: str, marker: str = "") -> dict[str, Any]:
        raw = put("raw-" + kind, (marker or (kind + ": " + ("1 passed" if status == "passed" else "1 failed"))).encode(), raw=True)
        junit_ref = junit("junit-" + kind, status, nodeid)
        return {"receipt": receipt_art(kind, head, tree, raw, junit_ref, 0 if status == "passed" else 1, argv), "raw": raw, "junit": junit_ref}
    def red_anchor(nodeid: str) -> str:
        return ANCHORS["review-leg-isolation"]["anchor"] if "advisor_board_" in nodeid or "harden_evidence_verifier" in nodeid else next(item["anchor"] for item in ANCHORS.values() if item["nodeid"] == nodeid)
    red_raw = put("activated-red", ("16 failed, 439 passed, 3 skipped, 17 subtests passed\n" + "\n".join(red_anchor(nodeid) for nodeid in ACTIVATED_RED_NODEIDS)).encode(), raw=True)
    red_cases = "".join(f'<testcase classname="{nodeid.rsplit("::",1)[0].removeprefix("phase-loop-runtime/").removesuffix(".py").replace("/", ".")}" name="{nodeid.rsplit("::",1)[1]}"><failure>{red_anchor(nodeid)}</failure></testcase>' for nodeid in ACTIVATED_RED_NODEIDS)
    red_cases += "".join(f'<testcase classname="tests.preexisting" name="pass_{index}" />' for index in range(439))
    red_cases += "".join(f'<testcase classname="tests.preexisting" name="skip_{index}"><skipped /></testcase>' for index in range(3))
    red_junit = put("activated-red.xml", ("<testsuite>" + red_cases + "</testsuite>").encode(), raw=True)
    activated = {"receipt": receipt_art("activated_red", reviewed, reviewed_tree, red_raw, red_junit, 1, "pytest_harden_activated_v1"), "raw": red_raw, "junit": red_junit}
    pure = pytest_art("pre-pure", reviewed, reviewed_tree, "passed", "pkg::pure", "pytest_harden_pure_control_v1")
    pure["receipt"] = receipt_art("pure_control", reviewed, reviewed_tree, pure["raw"], pure["junit"], 0, "pytest_harden_pure_control_v1")
    mutations = []
    for case_id, anchor in ANCHORS.items():
        _, source_bytes = blob(repo, reviewed, anchor["source"])
        restored_source = put("restored-source-" + case_id, source_bytes, raw=True)
        mutated_source = put("mutated-source-" + case_id, source_bytes + b"# source-entered mutation\n", raw=True)
        mutation = pytest_art("mutation-" + case_id, reviewed, reviewed_tree, "failure", anchor["nodeid"], "pytest_harden_source_mutation_v1", "HARDEN-MUTATION-BITE::" + case_id)
        mutation["receipt"] = receipt_art("source_mutation", reviewed, reviewed_tree, mutation["raw"], mutation["junit"], 1, "pytest_harden_source_mutation_v1", (anchor["source"], mutated_source["sha256"]))
        restored = pytest_art("restored-" + case_id, reviewed, reviewed_tree, "passed", anchor["nodeid"], "pytest_harden_restored_control_v1", "HARDEN-RESTORED-CONTROL::" + case_id)
        restored["receipt"] = receipt_art("restored_control", reviewed, reviewed_tree, restored["raw"], restored["junit"], 0, "pytest_harden_restored_control_v1", (anchor["source"], restored_source["sha256"]))
        mutations.append({"case_id": case_id, "source_path": anchor["source"], "nodeid": anchor["nodeid"], "mutated_source": mutated_source, "restored_source": restored_source, "mutation": mutation, "restored": restored})
    inventory = []
    for path in FROZEN_SL0_PATHS:
        entry: dict[str, Any] = {"path": path}
        for stage in ("reviewed_sl0", "landing", "candidate", "canonical_main"):
            commit_id, _ = refs[stage]
            object_id, contents = blob(repo, commit_id, path)
            entry[{"reviewed_sl0": "reviewed", "landing": "landing", "candidate": "candidate", "canonical_main": "canonical_main"}[stage]] = {"blob": object_id, "sha256": sha256(contents), "bytes": len(contents)}
        inventory.append(entry)
    def final_group(label: str, head: str, tree: str) -> dict[str, Any]:
        group: dict[str, Any] = {"commit": head, "tree": tree, "run_nonce": nonce("run-" + label)}
        for key, kind, argv in (("focused", "focused_activated", "pytest_harden_focused_activated_v1"), ("pure_control", "pure_control", "pytest_harden_pure_control_v1"), ("broad", "broad", "pytest_harden_broad_v1")):
            group[key] = pytest_art(label + "-" + key, head, tree, "passed", "pkg::" + key, argv)
            group[key]["receipt"] = receipt_art(kind, head, tree, group[key]["raw"], group[key]["junit"], 0, argv)
        lint_raw = put(label + "-lint.raw", (label + ": py_compile ruff git diff --check passed\n").encode(), raw=True)
        group["lint"] = {"raw": lint_raw, "receipt": put(label + "-lint.receipt", {"schema": "harden_static_receipt.v1", "head": head, "tree": tree, "process_nonce": nonce("lint-" + label), "exit_code": 0, "tool_identity": "harden_static_gate.v1", "argv_class": "harden_static_metadata_only_v1", "checks": ["py_compile", "ruff", "git_diff_check"], "raw_sha256": lint_raw["sha256"]})}
        return group

    def broker(harness: str, requested: str, resolved: str, label: str, bundle_sha256: str, instructions_sha256: str) -> dict[str, Any]:
        common: dict[str, Any] = {
            "schema": BROKER_SCHEMA, "stage_bundle_sha256": bundle_sha256, "stage_instructions_sha256": instructions_sha256,
            "leg_authorization_issued_monotonic_ns": 1, "leg_authorization_expires_monotonic_ns": 2_000_000_000,
            "canonical_repo_sha256": nonce(label + "repo"), "canonical_repo_probe_file_sha256": nonce(label + "probe"),
            "cleanup_root_removed": True, "host_secret_probe_removed": True, "child_quiescent": True,
            "peer_pid": 123, "peer_uid": 1000, "peer_gid": 1000, "peer_ancestry_verified": True,
            "bwrap": "/usr/bin/bwrap", "outer_bwrap_pid": 122, "outer_bwrap_start": 12345, "network_unshared": True, "close_fds_requested": True,
            "socket": "/run/phase-loop-broker/intended-inference.sock", "stage": "/run/phase-loop-review", "argv_sha256": nonce(label + "argv"), "socket_present_before_launch": True,
            "stage_bundle_mode": 0o400, "stage_instructions_mode": 0o400, "client_probe_program_sha256": nonce(label + "client"),
            "client_probe_assertions": ["credentialless_env", "readonly_stage", "no_live_bundle", "no_live_instructions", "no_host_secret", "no_live_tree", "no_inherited_fd", "fixed_socket_only", "no_af_inet"],
            "canonical_repo_file_denied": True, "canonical_repo_directory_denied": True, "host_stage_path_denied": True, "no_inherited_fd_observed": True,
            "child_stderr_sha256": nonce(label + "stderr"), "child_returncode": 0, "operation_deadline_s": 30.0, "child_timeout": False, "broker_thread_quiescent": True, "provider_adapter_quiescent": True, "provider_cancel_requested": False,
            "provider_input_sha256": nonce(label + "prompt"), "provider_input_bytes": 10, "provider_input_inline": True, "provider_live_tree_cwd": False,
            "provider_harness": harness, "provider_model": resolved, "provider_argv_shape": [harness, "<SEALED_INLINE_PROMPT>"] if harness != "claude" else ["claude"], "provider_argv_sha256": nonce(label + "providerargv"),
            "provider_prompt_sha256": nonce(label + "prompt"), "provider_prompt_bytes": 10, "provider_prompt_transport": "argv_inline" if harness != "claude" else "pty_input", "provider_cwd_class": "owned_empty_scratch", "provider_cwd_sha256": nonce(label + "cwd"), "provider_env_keys": ["LANG", "PATH"], "provider_env_api_keys_scrubbed": True, "provider_env_direct_routes_scrubbed": True, "provider_no_tool_controls": list(NO_TOOL_CONTROLS[harness]),
        }
        if harness == "claude":
            common.update({"claude_session_id_sha256": nonce(label + "session"), "claude_session_resume_forbidden": True, "claude_transcript_exact_path_sha256": nonce(label + "path"), "claude_transcript_preexisting": False, "claude_transcript_existed": True, "claude_transcript_sha256": nonce(label + "transcript"), "claude_transcript_bytes": 12, "claude_transcript_cleanup_verified": True})
        return common
    def review(round_name: str, head: str, tree: str) -> dict[str, Any]:
        seats_request = [{"harness": h, "requested_model": route[0]} for h, route in ROUTES.items()]
        bundle = put("bundle-" + round_name, {"schema": "harden_review_input.v1", "kind": "bundle", "head": head, "tree": tree, "content": git_bound_review_input(repo, head, tree, "bundle")})
        instructions = put("instructions-" + round_name, {"schema": "harden_review_input.v1", "kind": "instructions", "head": head, "tree": tree, "content": git_bound_review_input(repo, head, tree, "instructions")})
        input_sha256 = sha256(git_bound_review_input(repo, head, tree, "bundle").encode())
        instructions_sha256 = sha256(git_bound_review_input(repo, head, tree, "instructions").encode())
        request = put("request-" + round_name, {"schema": "harden_review_request.v1", "round": round_name, "head": head, "tree": tree, "bundle": bundle, "instructions": instructions, "request_nonce": nonce("request-" + round_name), "seats": seats_request})
        seats = []
        for harness, (requested, resolved) in ROUTES.items():
            report = "Independent retained-artifact review\nAGREE"
            seat = put("seat-" + round_name + "-" + harness, {"schema": "harden_review_seat.v1", "round": round_name, "head": head, "tree": tree, "request_sha256": request["sha256"], "harness": harness, "requested_model": requested, "resolved_model": resolved, "seat_id": round_name + "-" + harness + "-seat", "session_sha256": nonce(round_name + harness + "session"), "harness_provenance": "brokered_subscription_cli", "status": "usable", "result_kind": "real_subscription_inference", "report": report, "report_sha256": sha256(report.encode()), "report_bytes": len(report.encode()), "broker": broker(harness, requested, resolved, round_name + harness, input_sha256, instructions_sha256)})
            seats.append({"harness": harness, "artifact": seat})
        return {"head": head, "tree": tree, "request": request, "seats": seats}
    reviews = {"candidate": review("candidate", candidate, candidate_tree), "canonical_main": review("canonical_main", main, main_tree)}
    evidence_id = nonce("evidence")
    coordinator_session = nonce("role-coordinator")
    author_session = sha256(b"01a04424-61d9-7712-94a6-e058cbe1349e")
    reviewer_session = sha256("\0".join(sorted(nonce(round_name + harness + "session") for round_name in ("candidate", "canonical_main") for harness in ROUTES)).encode())
    roles = {}
    for role, identity, vendor, session in (("coordinator", "coordinator-1", "coordinator", coordinator_session), ("author", "author-1", "codex-gpt-5.6-terra", author_session), ("reviewer", "reviewer-" + reviewer_session[:32], "reviewer", reviewer_session)):
        roles[role] = put("role-" + role, {"schema": "harden_role_attestation.v1", "role": role, "identity": identity, "vendor": vendor, "session_sha256": session, "evidence_id": evidence_id, "issued_at": "2026-08-27T00:00:00Z"})
    evidence: dict[str, Any] = {
        "schema": SCHEMA, "evidence_id": evidence_id, "repository": "Consiliency/agent-harness",
        "git": {name: {"commit": commit_id, "tree": tree} for name, (commit_id, tree) in refs.items()},
        "sl0": {"frozen_inventory": inventory, "activated_red": activated, "pure_control": pure, "mutations": mutations},
        "verification": {"candidate": final_group("candidate", candidate, candidate_tree), "canonical_main": final_group("main", main, main_tree)},
        "ci": {
            "candidate": {"provider": "github_actions", "repository": "Consiliency/agent-harness", "run_id": 98, "workflow": "HARDEN", "event": "push", "run_attempt": 1, "head": candidate},
            "canonical_main": {"provider": "github_actions", "repository": "Consiliency/agent-harness", "run_id": 99, "workflow": "HARDEN", "event": "push", "run_attempt": 1, "head": main},
        },
        "reviews": reviews, "roles": roles, "completion": {"mode": "pre_completion"},
    }
    evidence_path = root / "evidence.json"; evidence_path.write_bytes(canonical_bytes(evidence))
    fake_gh = root / "fake-gh"
    responses = {
        str(ci["run_id"]): {"databaseId": ci["run_id"], "headSha": ci["head"], "status": "completed", "conclusion": "success", "event": "push", "workflowName": ci["workflow"], "attempt": ci["run_attempt"]}
        for ci in evidence["ci"].values()
    }
    responses_path = root / "fake-gh-responses.json"
    responses_path.write_bytes(canonical_bytes(responses))
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"responses = json.loads(open({str(responses_path)!r}, encoding='utf-8').read())\n"
        "print(json.dumps(responses[sys.argv[3]]))\n"
    )
    fake_gh.chmod(0o700)
    registry = root / "operator-reuse-registry.json"
    registry.write_bytes(canonical_bytes({"schema": "harden_evidence_registry.v1", "evidence_ids": [], "operation_nonces": []}))
    return evidence_path, artifacts, repo, evidence, registry, coordinator_session, author_session


def _write_evidence(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(canonical_bytes(value))


def self_test() -> None:
    """Exercise a valid fixture and representative fail-closed mutations."""
    with tempfile.TemporaryDirectory(prefix="harden-evidence-self-test-") as temporary:
        root = Path(temporary)
        baseline = root / "baseline"
        baseline.mkdir()
        evidence_path, artifacts, repo, evidence, registry, coordinator, author = _fixture(baseline)
        verify(evidence_path, artifacts, repo, reuse_registry=registry, expected_coordinator_session=coordinator, expected_author_session=author, ci_query=baseline / "fake-gh")
        post_root = root / "post-completion"
        shutil.copytree(baseline, post_root, symlinks=True)
        post_path = post_root / "evidence.json"; post_model = parse_canonical_json(post_path.read_bytes(), "post-completion evidence")
        main = post_model["git"]["canonical_main"]
        event = {"timestamp": "2026-08-27T00:00:00Z", "phase": "HARDEN", "action": "phase_execute", "status": "complete", "metadata": {"harden_completion": {"schema": "harden_completion.v1", "evidence_sha256": normalized_precompletion_digest(post_model), "canonical_commit": main["commit"], "canonical_tree": main["tree"], "visual_render_declared": False}}}
        ledger = (json.dumps(event, sort_keys=True) + "\n").encode(); ledger_ref = {"path": "completion-ledger.jsonl", "sha256": sha256(ledger)}
        (post_root / "artifacts" / ledger_ref["path"]).write_bytes(ledger)
        post_model["completion"] = {"mode": "post_completion", "ledger": ledger_ref}
        _write_evidence(post_path, post_model)
        verify(post_path, post_root / "artifacts", post_root / "repo", reuse_registry=post_root / "operator-reuse-registry.json", expected_coordinator_session=coordinator, expected_author_session=author, ci_query=post_root / "fake-gh")
        def marker_rejected(name: str, body: str) -> None:
            marker_root = root / name
            shutil.copytree(baseline / "repo", marker_root)
            target = marker_root / "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py"
            target.write_text(body)
            _run(["git", "add", str(target.relative_to(marker_root))], marker_root)
            _run(["git", "commit", "-qm", name], marker_root)
            try:
                _marker_state(marker_root, _run(["git", "rev-parse", "HEAD"], marker_root), required=True)
            except EvidenceError:
                return
            raise AssertionError(name + " marker was accepted")
        marker_rejected("marker-missing", "# absent\n")
        marker_rejected("marker-wrong", "HARDEN_CAPABILITY_VERSION = 2\n")
        marker_rejected("marker-duplicate", "HARDEN_CAPABILITY_VERSION = 1\nHARDEN_CAPABILITY_VERSION = 1\n")
        marker_rejected("marker-nonliteral", "HARDEN_CAPABILITY_VERSION = int('1')\n")
        def replace(ref: dict[str, str], artifact_root: Path, data: bytes) -> None:
            (artifact_root / ref["path"]).write_bytes(data)
            ref["sha256"] = sha256(data)
        def mutate_json(ref: dict[str, str], artifact_root: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
            value = parse_canonical_json((artifact_root / ref["path"]).read_bytes(), "self-test artifact")
            mutate(value)
            replace(ref, artifact_root, canonical_bytes(value))
        checks: list[tuple[str, Callable[[dict[str, Any], Path, Path], None]]] = []
        def rejected(name: str, mutate: Callable[[dict[str, Any], Path, Path], None]) -> None:
            checks.append((name, mutate))
        def run_rejected(check: tuple[str, Callable[[dict[str, Any], Path, Path], None]]) -> None:
            name, mutate = check
            local_root = root / name
            shutil.copytree(baseline, local_root, symlinks=True)
            path = local_root / "evidence.json"; artifact_root = local_root / "artifacts"; local_repo = local_root / "repo"
            model = parse_canonical_json(path.read_bytes(), "self-test copied evidence")
            mutate(model, local_root, artifact_root)
            _write_evidence(path, model)
            try:
                verify(path, artifact_root, local_repo, reuse_registry=local_root / "operator-reuse-registry.json", expected_coordinator_session=coordinator, expected_author_session=author, ci_query=local_root / "fake-gh")
            except EvidenceError:
                return
            raise AssertionError(name + " was accepted")
        rejected("unknown-field", lambda model, _root, _artifacts: model.__setitem__("unknown", True))
        rejected("path-escape", lambda model, _root, _artifacts: model["sl0"]["activated_red"]["raw"].__setitem__("path", "../escape"))
        def symlink_escape(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            target = artifact_root / "symlink"; target.symlink_to(artifact_root / model["sl0"]["activated_red"]["raw"]["path"])
            model["sl0"]["activated_red"]["raw"]["path"] = "symlink"
        rejected("symlink", symlink_escape)
        rejected("blob-drift", lambda model, _root, _artifacts: model["sl0"]["frozen_inventory"][0]["candidate"].__setitem__("sha256", "0" * 64))
        rejected("topology", lambda model, _root, _artifacts: model["git"]["landing"].__setitem__("commit", model["git"]["candidate"]["commit"]))
        def conflated_base_and_first_parent(model: dict[str, Any], _root: Path, _artifacts: Path) -> None:
            model["git"]["landing_first_parent"] = copy.deepcopy(model["git"]["sl0_base"])
        rejected("base-first-parent-conflation", conflated_base_and_first_parent)
        rejected("tree-drift", lambda model, _root, _artifacts: model["git"]["candidate"].__setitem__("tree", "0" * 40))
        rejected("missing-red", lambda model, _root, _artifacts: model["sl0"]["mutations"].pop())
        def extra_anchor(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            red = model["sl0"]["activated_red"]; replace(red["raw"], artifact_root, (artifact_root / red["raw"]["path"]).read_bytes() + b"\nHARDEN-RED-ANCHOR::staged-tree-containment\n")
            mutate_json(red["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("raw_sha256", red["raw"]["sha256"]))
        rejected("extra-red", extra_anchor)
        def skipped_junit(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            red = model["sl0"]["activated_red"]; replace(red["junit"], artifact_root, b'<testsuite><testcase classname="pkg" name="x"><skipped/></testcase></testsuite>')
            mutate_json(red["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("junit_sha256", red["junit"]["sha256"]))
        rejected("skipped-junit", skipped_junit)
        def nonbiting(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            mutation = model["sl0"]["mutations"][0]["mutation"]; replace(mutation["raw"], artifact_root, b"1 failed but no bite marker\n")
            mutate_json(mutation["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("raw_sha256", mutation["raw"]["sha256"]))
        rejected("nonbiting", nonbiting)
        def wrong_junit_module(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            mutation = model["sl0"]["mutations"][0]["mutation"]
            old = (artifact_root / mutation["junit"]["path"]).read_bytes().replace(b'classname="tests.', b'classname="wrong.module.', 1)
            replace(mutation["junit"], artifact_root, old)
            mutate_json(mutation["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("junit_sha256", mutation["junit"]["sha256"]))
        rejected("wrong-module-same-function", wrong_junit_module)
        def old_prefixed_junit_module(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            mutation = model["sl0"]["mutations"][0]["mutation"]
            old = (artifact_root / mutation["junit"]["path"]).read_bytes().replace(b'classname="tests.', b'classname="phase-loop-runtime.tests.', 1)
            replace(mutation["junit"], artifact_root, old)
            mutate_json(mutation["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("junit_sha256", mutation["junit"]["sha256"]))
        rejected("old-prefixed-junit-module", old_prefixed_junit_module)
        def wrong_source_bytes(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            source = model["sl0"]["mutations"][0]["restored_source"]
            replace(source, artifact_root, b"wrong restored source\n")
            restored = model["sl0"]["mutations"][0]["restored"]
            mutate_json(restored["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("source_sha256", source["sha256"]))
        rejected("wrong-restored-source", wrong_source_bytes)
        rejected("stale-process", lambda model, _root, _artifacts: model["verification"]["canonical_main"].__setitem__("run_nonce", model["verification"]["candidate"]["run_nonce"]))
        rejected("detached-ci", lambda model, _root, _artifacts: model["ci"]["candidate"].__setitem__("run_id", 100))
        rejected("wrong-ci-head", lambda model, _root, _artifacts: model["ci"]["canonical_main"].__setitem__("head", model["git"]["candidate"]["commit"]))
        def failed_ci(model: dict[str, Any], local_root: Path, _artifacts: Path) -> None:
            ci = model["ci"]["candidate"]
            response = {"databaseId": ci["run_id"], "headSha": ci["head"], "status": "completed", "conclusion": "failure", "event": ci["event"], "workflowName": ci["workflow"], "attempt": ci["run_attempt"]}
            (local_root / "fake-gh").write_text("#!/bin/sh\nprintf '%s' '" + canonical_bytes(response).decode().replace("'", "'\\''") + "'\n"); (local_root / "fake-gh").chmod(0o700)
        rejected("failed-ci", failed_ci)
        def seat_mutation(change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any], Path, Path], None]:
            def mutate(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
                ref = model["reviews"]["candidate"]["seats"][0]["artifact"]; mutate_json(ref, artifact_root, change)
            return mutate
        rejected("synthetic-seat", seat_mutation(lambda seat: seat.__setitem__("result_kind", "synthetic")))
        rejected("wrong-model-seat", seat_mutation(lambda seat: seat.__setitem__("resolved_model", "wrong-model")))
        rejected("direct-route-seat", seat_mutation(lambda seat: seat["broker"].__setitem__("provider_env_keys", ["API_KEY"])))
        rejected("missing-broker-probe", seat_mutation(lambda seat: seat["broker"].__setitem__("client_probe_assertions", [])))
        rejected("cleanup-failure", seat_mutation(lambda seat: seat["broker"].__setitem__("cleanup_root_removed", False)))
        rejected("broker-stage-mismatch", seat_mutation(lambda seat: seat["broker"].__setitem__("stage_bundle_sha256", "0" * 64)))
        rejected("broker-child-nonzero", seat_mutation(lambda seat: seat["broker"].__setitem__("child_returncode", 1)))
        rejected("provider-input-prompt-mismatch", seat_mutation(lambda seat: seat["broker"].__setitem__("provider_input_sha256", "f" * 64)))
        rejected("stage-mode-0444", seat_mutation(lambda seat: seat["broker"].__setitem__("stage_bundle_mode", 0o444)))
        rejected("extra-no-tool-control", seat_mutation(lambda seat: seat["broker"]["provider_no_tool_controls"].append("extra")))
        rejected("duplicate-no-tool-control", seat_mutation(lambda seat: seat["broker"]["provider_no_tool_controls"].append(seat["broker"]["provider_no_tool_controls"][0])))
        def request_mutation(change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any], Path, Path], None]:
            def mutate(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
                ref = model["reviews"]["candidate"]["request"]
                mutate_json(ref, artifact_root, change)
            return mutate
        rejected("extra-review-request-seat", request_mutation(lambda request: request["seats"].append({"harness": "extra", "requested_model": "extra"})))
        rejected("nondict-review-request-seat", request_mutation(lambda request: request["seats"].__setitem__(0, "not-a-seat")))
        def duplicate_seat(model: dict[str, Any], _root: Path, _artifacts: Path) -> None:
            model["reviews"]["candidate"]["seats"][1]["artifact"] = model["reviews"]["candidate"]["seats"][0]["artifact"]
        rejected("duplicate-seat", duplicate_seat)
        def reused_round(model: dict[str, Any], _root: Path, _artifacts: Path) -> None:
            model["reviews"]["canonical_main"]["request"] = model["reviews"]["candidate"]["request"]
        rejected("reused-review-round", reused_round)
        def role_mutation(role_name: str, change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any], Path, Path], None]:
            def mutate(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
                mutate_json(model["roles"][role_name], artifact_root, change)
            return mutate
        rejected("substituted-coordinator", role_mutation("coordinator", lambda role: role.__setitem__("session_sha256", "f" * 64)))
        rejected("substituted-author", role_mutation("author", lambda role: role.__setitem__("session_sha256", "e" * 64)))
        rejected("substituted-reviewer", role_mutation("reviewer", lambda role: role.__setitem__("identity", "unknown")))
        def reused_evidence_id(model: dict[str, Any], local_root: Path, _artifacts: Path) -> None:
            registry = {"schema": "harden_evidence_registry.v1", "evidence_ids": [model["evidence_id"]], "operation_nonces": []}
            (local_root / "operator-reuse-registry.json").write_bytes(canonical_bytes(registry))
        rejected("reused-evidence-id", reused_evidence_id)
        def reused_operation_nonce(model: dict[str, Any], local_root: Path, _artifacts: Path) -> None:
            nonce_value = model["verification"]["candidate"]["run_nonce"]
            registry = {"schema": "harden_evidence_registry.v1", "evidence_ids": [], "operation_nonces": [nonce_value]}
            (local_root / "operator-reuse-registry.json").write_bytes(canonical_bytes(registry))
        rejected("reused-operation-nonce", reused_operation_nonce)
        def retained_secret(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            raw = model["verification"]["candidate"]["lint"]["raw"]
            replace(raw, artifact_root, b"token=0123456789abcdef0123456789abcdef\n")
            mutate_json(model["verification"]["candidate"]["lint"]["receipt"], artifact_root, lambda receipt_value: receipt_value.__setitem__("raw_sha256", raw["sha256"]))
        rejected("retained-secret", retained_secret)
        rejected("premature-ledger", lambda model, _root, _artifacts: model.__setitem__("completion", {"mode": "post_completion", "ledger": {"path": "missing", "sha256": "0" * 64}}))
        def duplicate_ledger(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            digest = normalized_precompletion_digest(model); main = model["git"]["canonical_main"]
            event = {"timestamp": "2026-08-27T00:00:00Z", "phase": "HARDEN", "action": "phase_execute", "status": "complete", "metadata": {"harden_completion": {"schema": "harden_completion.v1", "evidence_sha256": digest, "canonical_commit": main["commit"], "canonical_tree": main["tree"], "visual_render_declared": False}}}
            body = canonical_bytes(event) + canonical_bytes(event); ref = {"path": "duplicate-ledger.jsonl", "sha256": sha256(body)}; (artifact_root / ref["path"]).write_bytes(body); model["completion"] = {"mode": "post_completion", "ledger": ref}
        rejected("duplicate-ledger", duplicate_ledger)
        def wrong_ledger_binding(model: dict[str, Any], _root: Path, artifact_root: Path) -> None:
            main = model["git"]["canonical_main"]
            event = {"timestamp": "2026-08-27T00:00:00Z", "phase": "HARDEN", "action": "phase_execute", "status": "complete", "metadata": {"harden_completion": {"schema": "harden_completion.v1", "evidence_sha256": "0" * 64, "canonical_commit": main["commit"], "canonical_tree": main["tree"], "visual_render_declared": False}}}
            body = (json.dumps(event, sort_keys=True) + "\n").encode(); ref = {"path": "wrong-ledger.jsonl", "sha256": sha256(body)}; (artifact_root / ref["path"]).write_bytes(body); model["completion"] = {"mode": "post_completion", "ledger": ref}
        rejected("wrong-ledger-binding", wrong_ledger_binding)
        rejected("repository-mismatch", lambda model, _root, _artifacts: model.__setitem__("repository", "other/repository"))
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(run_rejected, checks))
    print("self-test: valid topology and post-completion ledger accepted; 49 adversarial mutations rejected")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, help="canonical verification_evidence.v3 JSON")
    parser.add_argument("--evidence-root", type=Path, help="retained artifact root")
    parser.add_argument("--repo", type=Path, help="repository containing retained Git objects")
    parser.add_argument("--reuse-registry", type=Path, help="operator-owned canonical reuse registry outside evidence root")
    parser.add_argument("--expected-coordinator-session-sha256", help="externally authorized coordinator session SHA-256")
    parser.add_argument("--expected-author-session-sha256", help="externally authorized sole-author session SHA-256")
    parser.add_argument("--self-test", action="store_true", help="run ephemeral valid/adversarial fixture")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            if any(item is not None for item in (args.evidence, args.evidence_root, args.repo, args.reuse_registry, args.expected_coordinator_session_sha256, args.expected_author_session_sha256)):
                fail("--self-test does not accept external evidence options")
            self_test()
            return 0
        if any(item is None for item in (args.evidence, args.evidence_root, args.repo, args.reuse_registry, args.expected_coordinator_session_sha256, args.expected_author_session_sha256)):
            fail("--evidence, --evidence-root, --repo, --reuse-registry, and expected session SHA-256 values are required")
        verify(args.evidence, args.evidence_root, args.repo, reuse_registry=args.reuse_registry, expected_coordinator_session=args.expected_coordinator_session_sha256, expected_author_session=args.expected_author_session_sha256)
    except (EvidenceError, OSError, subprocess.TimeoutExpired) as exc:
        print("HARDEN evidence rejected: " + str(exc), file=sys.stderr)
        return 1
    print("HARDEN evidence accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
