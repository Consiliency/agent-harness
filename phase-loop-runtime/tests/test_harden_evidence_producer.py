"""HARDEN SL-4 tests-only contract for the retained-evidence producer."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any, Callable
from xml.etree import ElementTree

import pytest


ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_HARDEN_PRODUCER"
INPUT_SCHEMA = "harden_evidence_inputs.v1"
PRODUCER_PATH = "phase-loop-runtime/scripts/build_harden_evidence.py"
SKIP_REASON = (
    "HARDEN aggregate producer is absent (SL-4 tests-only boundary): "
    f"set {ACTIVATION_ENV}=1 to record the deterministic RED anchors"
)
ANCHORS = {
    "derive": "HARDEN-PRODUCER-RED::derive-live-facts",
    "assemble": "HARDEN-PRODUCER-RED::assemble-retained-evidence",
    "seal": "HARDEN-PRODUCER-RED::two-stage-seal",
}
RAW_ARTIFACT_NAMES = (
    "plan_authority",
    "sl0_review",
    "preproduction_red_raw",
    "preproduction_red_junit",
    "preproduction_control_raw",
    "preproduction_control_junit",
    "candidate_focused_raw",
    "candidate_focused_junit",
    "candidate_broad_raw",
    "candidate_broad_junit",
    "candidate_lint_raw",
    "candidate_ci",
    "candidate_review_request",
    "candidate_broker_receipts",
    "canonical_main_focused_raw",
    "canonical_main_focused_junit",
    "canonical_main_broad_raw",
    "canonical_main_broad_junit",
    "canonical_main_lint_raw",
    "canonical_main_ci",
    "canonical_main_review_request",
    "canonical_main_broker_receipts",
)
RAW_JUNIT_PAIRS = (
    ("preproduction_red_raw", "preproduction_red_junit"),
    ("preproduction_control_raw", "preproduction_control_junit"),
    ("candidate_focused_raw", "candidate_focused_junit"),
    ("candidate_broad_raw", "candidate_broad_junit"),
    ("canonical_main_focused_raw", "canonical_main_focused_junit"),
    ("canonical_main_broad_raw", "canonical_main_broad_junit"),
)
ROLE_NAMES = ("coordinator", "author", "reviewer")


def _repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent,
    )
    return Path(completed.stdout.strip()).resolve()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8", errors="strict")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate key: {key}")
        value[key] = item
    return value


def _strict_json(path: Path) -> Any:
    data = path.read_bytes()
    value = json.loads(
        data,
        object_pairs_hook=_no_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    assert data == _canonical_bytes(value)
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _different_hex(value: str) -> str:
    replacement = os.urandom(len(value) // 2).hex()
    while replacement == value:
        replacement = os.urandom(len(value) // 2).hex()
    return replacement


def _different_count(value: int) -> int:
    return value + 1 + os.urandom(1)[0]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str, paths: dict[str, str]) -> str:
    for relative, contents in paths.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _write_ref(root: Path, relative: str, data: bytes) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": relative, "sha256": _sha256(data)}


def _junit_bytes(outcomes: tuple[str, ...]) -> bytes:
    suite = ElementTree.Element(
        "testsuite",
        tests=str(len(outcomes)),
        failures=str(outcomes.count("failed")),
        errors="0",
        skipped=str(outcomes.count("skipped")),
    )
    for index, outcome in enumerate(outcomes):
        case = ElementTree.SubElement(
            suite,
            "testcase",
            classname="retained",
            name=f"case_{index}",
        )
        if outcome == "failed":
            ElementTree.SubElement(case, "failure", message="falsifier bit")
        elif outcome == "skipped":
            ElementTree.SubElement(case, "skipped", message="capability absent")
    return ElementTree.tostring(suite, encoding="utf-8", xml_declaration=True)


def _fixture_variants() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    suffix = _sha256(os.urandom(16))[:12]
    runtime_red = ("failed",) * (2 + int(suffix[0], 16) % 3) + (
        "passed",
        "skipped",
    )
    runtime_final = ("passed",) * (2 + int(suffix[1], 16) % 4)
    return (
        (
            "codex-gpt-5.6-terra",
            ("failed", "passed", "skipped"),
            ("passed", "passed"),
        ),
        (
            "claude-fable-5",
            ("failed", "failed", "passed", "passed"),
            ("passed", "passed", "passed"),
        ),
        (
            f"runtime-vendor-{suffix}",
            runtime_red,
            runtime_final,
        ),
    )


def _runtime_variant(seed: Path) -> str:
    return "runtime-" + _sha256(os.fsencode(str(seed.resolve())))[:16]


def _producer_module(case: str) -> Any:
    path = _repo_root() / PRODUCER_PATH
    if not path.is_file():
        if os.environ.get(ACTIVATION_ENV) == "1":
            pytest.fail(ANCHORS[case], pytrace=False)
        pytest.skip(SKIP_REASON)
    spec = importlib.util.spec_from_file_location("harden_evidence_producer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _producer_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_repo_root() / PRODUCER_PATH), *args],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _load_shipped_verifier() -> Any:
    path = _repo_root() / "phase-loop-runtime/scripts/verify_harden_evidence.py"
    spec = importlib.util.spec_from_file_location("shipped_harden_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_fixture(
    root: Path,
    *,
    variant: str = "valid",
    author_vendor: str = "codex-gpt-5.6-terra",
    red_outcomes: tuple[str, ...] = ("failed", "passed", "skipped"),
    final_outcomes: tuple[str, ...] = ("passed", "passed"),
) -> dict[str, Any]:
    repo = root / "repo"
    source_root = root / "retained-source"
    repo.mkdir(parents=True)
    source_root.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "producer-test@example.invalid")
    _git(repo, "config", "user.name", "HARDEN producer test")
    base = _commit(
        repo,
        "base",
        {
            "README.md": "base\n",
            "plans/phase-plan-v10-HARDEN.md": "# HARDEN raw-input fixture\n",
            "plans/manifest.json": '{"plans":[]}\n',
            ".gitignore": ".phase-loop/\n",
            ".github/workflows/test.yml": (
                "name: test\n\n"
                "on:\n"
                "  push:\n"
                "    branches: [main]\n"
                "  pull_request:\n\n"
                "jobs:\n"
                "  gate:\n"
                "    name: suite gate\n"
                "    runs-on: ubuntu-latest\n"
                "    steps: []\n"
            ),
        },
    )
    frozen_paths = (
        f"phase-loop-runtime/tests/test_{variant}_one.py",
        f"phase-loop-runtime/tests/test_{variant}_two.py",
    )
    reviewed = _commit(
        repo,
        "tests only",
        {
            path: f"def test_{index}(): pass\n"
            for index, path in enumerate(frozen_paths)
        },
    )
    landing = _commit(repo, "land tests", {"CHANGELOG.md": "tests landed\n"})
    production_path = f"phase-loop-runtime/src/phase_loop_runtime/{variant}.py"
    candidate = _commit(repo, "production", {production_path: "CAPABILITY = 1\n"})
    sibling_path = f"sibling/{variant}.txt"
    canonical_main = _commit(repo, "sibling landing", {sibling_path: "sibling\n"})
    commits = {
        "sl0_base": base,
        "reviewed_sl0": reviewed,
        "landing": landing,
        "candidate": candidate,
        "canonical_main": canonical_main,
    }
    trees = {
        name: _git(repo, "rev-parse", f"{commit}^{{tree}}")
        for name, commit in commits.items()
    }
    evidence_id = _sha256(f"evidence:{variant}".encode())
    operation_nonces = [
        _sha256(f"{variant}:operation:{index}".encode()) for index in range(13)
    ]
    ci_seed = int(_sha256(f"{variant}:ci".encode())[:12], 16)
    ci_run_ids = {
        "candidate": ci_seed * 2 + 1,
        "canonical_main": ci_seed * 2 + 2,
    }
    routes = [
        {
            "harness": harness,
            "requested_model": f"{harness}-{variant}-requested",
            "resolved_model": f"{harness}-{variant}-resolved",
        }
        for harness in ("claude", "codex", "gemini", "grok")
    ]
    plan_authority = {
        "schema": "harden_plan_authority.v1",
        "evidence_id": evidence_id,
        "repository": "Consiliency/agent-harness",
        "commits": commits,
        "author_vendor": author_vendor,
    }
    sl0_review = {
        "schema": "harden_sl0_review.v1",
        "base_commit": base,
        "reviewed_commit": reviewed,
        "landing_commit": landing,
        "frozen_test_paths": list(frozen_paths),
    }
    raw_outputs = {
        "preproduction_red_raw": (
            f"{red_outcomes.count('failed')} failed, "
            f"{red_outcomes.count('passed')} passed, "
            f"{red_outcomes.count('skipped')} skipped\n"
        ).encode(),
        "preproduction_control_raw": b"2 passed\n",
        "candidate_focused_raw": f"{len(final_outcomes)} passed\n".encode(),
        "candidate_broad_raw": f"{len(final_outcomes) + 1} passed\n".encode(),
        "candidate_lint_raw": b"All checks passed!\n",
        "canonical_main_focused_raw": f"{len(final_outcomes)} passed\n".encode(),
        "canonical_main_broad_raw": f"{len(final_outcomes) + 2} passed\n".encode(),
        "canonical_main_lint_raw": b"All checks passed!\n",
    }
    junits = {
        "preproduction_red_junit": _junit_bytes(red_outcomes),
        "preproduction_control_junit": _junit_bytes(("passed", "passed")),
        "candidate_focused_junit": _junit_bytes(final_outcomes),
        "candidate_broad_junit": _junit_bytes(final_outcomes + ("passed",)),
        "canonical_main_focused_junit": _junit_bytes(final_outcomes),
        "canonical_main_broad_junit": _junit_bytes(
            final_outcomes + ("passed", "passed")
        ),
    }
    artifacts: dict[str, dict[str, str]] = {
        "plan_authority": _write_ref(
            source_root, "raw/plan-authority.json", _canonical_bytes(plan_authority)
        ),
        "sl0_review": _write_ref(
            source_root, "raw/sl0-review.json", _canonical_bytes(sl0_review)
        ),
    }
    for name, data in {**raw_outputs, **junits}.items():
        extension = "xml" if name.endswith("junit") else "txt"
        artifacts[name] = _write_ref(source_root, f"raw/{name}.{extension}", data)
    for round_name, head in (
        ("candidate", candidate),
        ("canonical_main", canonical_main),
    ):
        run_id = ci_run_ids[round_name]
        ci = {
            "schema": "harden_ci_result.v1",
            "provider": "github_actions",
            "repository": "Consiliency/agent-harness",
            "head": head,
            "run_id": run_id,
            "workflow": "test",
            "event": "pull_request" if round_name == "candidate" else "push",
            "run_attempt": 1,
            "check": "suite gate",
            "status": "completed",
            "conclusion": "success",
        }
        artifacts[f"{round_name}_ci"] = _write_ref(
            source_root, f"raw/{round_name}-ci.json", _canonical_bytes(ci)
        )
        request = {
            "schema": "harden_review_request.v1",
            "round": round_name,
            "head": head,
            "tree": trees[round_name],
            "routes": routes,
            "operation_nonce": operation_nonces[0 if round_name == "candidate" else 1],
        }
        artifacts[f"{round_name}_review_request"] = _write_ref(
            source_root,
            f"raw/{round_name}-review-request.json",
            _canonical_bytes(request),
        )
        receipts = {
            "schema": "harden_broker_receipts.v1",
            "round": round_name,
            "receipts": [
                {
                    **route,
                    "result_kind": "live",
                    "terminal_verdict": "AGREE",
                    "operation_nonce": operation_nonces[
                        (2 if round_name == "candidate" else 6) + index
                    ],
                }
                for index, route in enumerate(routes)
            ],
        }
        artifacts[f"{round_name}_broker_receipts"] = _write_ref(
            source_root,
            f"raw/{round_name}-broker-receipts.json",
            _canonical_bytes(receipts),
        )
    sessions = {
        role: _sha256(f"{variant}:{role}-session".encode()) for role in ROLE_NAMES
    }
    role_attestations = {
        role: _write_ref(
            source_root,
            f"raw/{role}-attestation.json",
            _canonical_bytes(
                {
                    "schema": "harden_role_attestation.v1",
                    "role": role,
                    "session_sha256": session,
                    "evidence_id": evidence_id,
                    "operation_nonce": operation_nonces[10 + index],
                }
            ),
        )
        for index, (role, session) in enumerate(sessions.items())
    }
    manifest = {
        "schema": INPUT_SCHEMA,
        "artifacts": artifacts,
        "role_attestations": role_attestations,
    }
    assert set(artifacts) == set(RAW_ARTIFACT_NAMES)
    manifest_path = root / "harden-evidence-inputs.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    unrelated_registry_id = _sha256(f"{variant}:unrelated-evidence".encode())
    unrelated_registry_nonce = _sha256(f"{variant}:unrelated-nonce".encode())
    registry_path = root / "reuse-registry.json"
    registry_path.write_bytes(
        _canonical_bytes(
            {
                "schema": "harden_evidence_registry.v1",
                "evidence_ids": [unrelated_registry_id],
                "operation_nonces": [unrelated_registry_nonce],
            }
        )
    )
    ci_responses = {
        str(run_id): {
            "databaseId": run_id,
            "headSha": commits[round_name],
            "status": "completed",
            "conclusion": "success",
            "event": "pull_request" if round_name == "candidate" else "push",
            "workflowName": "test",
            "attempt": 1,
            "jobs": [
                {
                    "databaseId": run_id * 100 + 1,
                    "name": "suite gate",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
        for round_name, run_id in ci_run_ids.items()
    }
    ci_query = root / "fake-gh"
    ci_query.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"RESPONSES = {ci_responses!r}\n"
        "print(json.dumps(RESPONSES[sys.argv[3]]))\n",
        encoding="utf-8",
    )
    ci_query.chmod(0o700)
    expected = {
        "evidence_id": evidence_id,
        "commits": commits,
        "trees": trees,
        "changed_paths": {
            "reviewed_sl0": sorted(frozen_paths),
            "candidate": [production_path],
            "canonical_main": [sibling_path],
        },
        "frozen_test_paths": sorted(frozen_paths),
        "run_counts": {
            name: {
                outcome: outcomes.count(outcome)
                for outcome in ("passed", "failed", "skipped")
            }
            for name, outcomes in (
                ("preproduction_red", red_outcomes),
                ("preproduction_control", ("passed", "passed")),
                ("candidate_focused", final_outcomes),
                ("candidate_broad", final_outcomes + ("passed",)),
                ("canonical_main_focused", final_outcomes),
                ("canonical_main_broad", final_outcomes + ("passed", "passed")),
            )
        },
        "author_vendor": author_vendor,
        "routes": routes,
        "operation_nonces": operation_nonces,
        "registry": {
            "evidence_ids": [unrelated_registry_id],
            "operation_nonces": [unrelated_registry_nonce],
        },
        "ci_run_ids": ci_run_ids,
    }
    return {
        "root": root,
        "repo": repo,
        "source_root": source_root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "registry": registry_path,
        "sessions": sessions,
        "expected": expected,
        "evidence_root": root / "prepared-evidence",
        "output": root / "verification-evidence.v3.json",
        "request": root / "completion-request.json",
        "ci_query": ci_query,
    }


def _persist_manifest(context: dict[str, Any]) -> None:
    context["manifest_path"].write_bytes(_canonical_bytes(context["manifest"]))


def _prepare_command(context: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return _producer_command(
        "prepare",
        "--inputs",
        str(context["manifest_path"]),
        "--source-root",
        str(context["source_root"]),
        "--evidence-root",
        str(context["evidence_root"]),
        "--repo",
        str(context["repo"]),
        "--output",
        str(context["output"]),
        "--completion-request",
        str(context["request"]),
        "--reuse-registry",
        str(context["registry"]),
        "--expected-coordinator-session-sha256",
        context["sessions"]["coordinator"],
        "--expected-author-session-sha256",
        context["sessions"]["author"],
    )


def _seal_command(
    context: dict[str, Any],
    ledger: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return _producer_command(
        "seal",
        "--pre-completion",
        str(context["output"]),
        "--evidence-root",
        str(context["evidence_root"]),
        "--repo",
        str(context["repo"]),
        "--ledger",
        str(ledger),
        "--output",
        str(output),
        "--reuse-registry",
        str(context["registry"]),
        "--expected-coordinator-session-sha256",
        context["sessions"]["coordinator"],
        "--expected-author-session-sha256",
        context["sessions"]["author"],
    )


def _assert_no_prepare_output(context: dict[str, Any]) -> None:
    assert not context["output"].exists()
    assert not context["request"].exists()
    assert not context["evidence_root"].exists() or not any(
        context["evidence_root"].iterdir()
    )


def _normalized_precompletion_digest(evidence: dict[str, Any]) -> str:
    normalized = copy.deepcopy(evidence)
    normalized["completion"] = {"mode": "pre_completion"}
    return _sha256(_canonical_bytes(normalized))


def _completion_event(
    request: dict[str, Any], *, timestamp: str = "2026-09-04T00:00:00Z"
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "phase": "HARDEN",
        "action": "phase_execute",
        "status": "complete",
        "metadata": {
            "harden_completion": {
                "schema": "harden_completion.v1",
                "evidence_sha256": request["evidence_sha256"],
                "canonical_commit": request["canonical_commit"],
                "canonical_tree": request["canonical_tree"],
                "visual_render_declared": False,
            }
        },
    }


def _history_event() -> dict[str, Any]:
    return {
        "timestamp": "2026-09-03T00:00:00Z",
        "phase": "SCHED",
        "action": "phase_execute",
        "status": "complete",
        "metadata": {"history": True},
    }


def _blocked_harden_event() -> dict[str, Any]:
    return {
        "timestamp": "2026-09-03T12:00:00Z",
        "phase": "HARDEN",
        "action": "phase_execute",
        "status": "blocked",
        "metadata": {"history": True},
    }


def _ledger_history_bytes() -> bytes:
    return _canonical_bytes(_history_event()) + _canonical_bytes(
        _blocked_harden_event()
    )


def _ledger_bytes(request: dict[str, Any]) -> bytes:
    return _ledger_history_bytes() + _canonical_bytes(_completion_event(request))


def _contained_ref_path(root: Path, ref: dict[str, str], label: str) -> Path:
    assert set(ref) == {"path", "sha256"}
    raw = ref["path"]
    relative = PurePosixPath(raw)
    assert not relative.is_absolute(), f"{label} path must be relative"
    assert str(relative) == raw and all(
        part not in {"", ".", ".."} for part in relative.parts
    ), f"{label} path must be normalized"
    assert not root.is_symlink(), f"{label} root is a symlink"
    unresolved = root
    for part in relative.parts:
        unresolved /= part
        assert not unresolved.is_symlink(), f"{label} path contains a symlink"
    root_resolved = root.resolve(strict=True)
    path = unresolved.resolve(strict=True)
    assert path.is_relative_to(root_resolved), f"{label} path escaped its root"
    assert path.is_file(), f"{label} is not a regular file"
    assert _sha256(path.read_bytes()) == ref["sha256"], f"{label} digest mismatch"
    return path


def _reachable_artifact_refs(value: Any, root: Path) -> set[tuple[str, str]]:
    reachable: set[tuple[str, str]] = set()
    queued = [value]
    while queued:
        item = queued.pop()
        if isinstance(item, list):
            queued.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        if set(item) == {"path", "sha256"}:
            path = _contained_ref_path(root, item, "reachable retained artifact")
            key = (item["path"], item["sha256"])
            if key in reachable:
                continue
            reachable.add(key)
            if path.suffix == ".json":
                queued.append(_strict_json(path))
            continue
        queued.extend(item.values())
    return reachable


def _verify_with_shipped_verifier(
    context: dict[str, Any], evidence_path: Path, label: str
) -> None:
    verifier = _load_shipped_verifier()
    registry = context["root"] / f"shipped-verifier-{label}-registry.json"
    registry.write_bytes(
        _canonical_bytes(
            {
                "schema": "harden_evidence_registry.v1",
                "evidence_ids": [],
                "operation_nonces": [],
            }
        )
    )
    verifier.verify(
        evidence_path,
        context["evidence_root"],
        context["repo"],
        reuse_registry=registry,
        expected_coordinator_session=context["sessions"]["coordinator"],
        expected_author_session=context["sessions"]["author"],
        ci_query=context["ci_query"],
    )


def _assert_prepared(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = _strict_json(context["output"])
    request = _strict_json(context["request"])
    assert set(evidence) == {
        "schema",
        "evidence_id",
        "repository",
        "git",
        "authority",
        "sl0",
        "verification",
        "ci",
        "reviews",
        "roles",
        "completion",
    }
    assert evidence["schema"] == "verification_evidence.v3"
    assert evidence["completion"] == {"mode": "pre_completion"}
    assert evidence["evidence_id"] == context["expected"]["evidence_id"]
    for name, commit in context["expected"]["commits"].items():
        assert evidence["git"][name] == {
            "commit": commit,
            "tree": context["expected"]["trees"][name],
        }
    assert (
        sorted(item["path"] for item in evidence["sl0"]["frozen_inventory"])
        == (context["expected"]["frozen_test_paths"])
    )
    for round_name, run_id in context["expected"]["ci_run_ids"].items():
        assert (
            evidence["ci"][round_name]["head"]
            == context["expected"]["commits"][round_name]
        )
        assert evidence["ci"][round_name]["run_id"] == run_id
    assert set(evidence["reviews"]) == {"candidate", "canonical_main"}
    assert set(evidence["roles"]) == set(ROLE_NAMES)

    def retained_json(ref: dict[str, str], label: str) -> dict[str, Any]:
        path = _contained_ref_path(context["evidence_root"], ref, label)
        value = _strict_json(path)
        assert isinstance(value, dict)
        return value

    receipt_refs = {
        "preproduction_red": evidence["sl0"]["activated_red"]["receipt"],
        "preproduction_control": evidence["sl0"]["pure_control"]["receipt"],
        "candidate_focused": evidence["verification"]["candidate"]["focused"][
            "receipt"
        ],
        "candidate_broad": evidence["verification"]["candidate"]["broad"]["receipt"],
        "canonical_main_focused": evidence["verification"]["canonical_main"]["focused"][
            "receipt"
        ],
        "canonical_main_broad": evidence["verification"]["canonical_main"]["broad"][
            "receipt"
        ],
    }
    for name, ref in receipt_refs.items():
        summary = retained_json(ref, f"{name} receipt")["summary"]
        expected_counts = context["expected"]["run_counts"][name]
        assert {
            outcome: summary[outcome] for outcome in ("passed", "failed", "skipped")
        } == expected_counts

    author = retained_json(evidence["roles"]["author"], "author attestation")
    assert author["vendor"] == context["expected"]["author_vendor"]
    expected_routes = {
        route["harness"]: route for route in context["expected"]["routes"]
    }
    for round_name in ("candidate", "canonical_main"):
        review = evidence["reviews"][round_name]
        review_request = retained_json(
            review["request"], f"{round_name} review request"
        )
        assert {
            seat["harness"]: seat["requested_model"] for seat in review_request["seats"]
        } == {
            harness: route["requested_model"]
            for harness, route in expected_routes.items()
        }
        assert {
            item["harness"]: retained_json(
                item["artifact"], f"{round_name} {item['harness']} seat"
            )["resolved_model"]
            for item in review["seats"]
        } == {
            harness: route["resolved_model"]
            for harness, route in expected_routes.items()
        }
    assert set(request) == {
        "schema",
        "phase",
        "evidence_sha256",
        "canonical_commit",
        "canonical_tree",
        "visual_render_declared",
        "input_manifest_sha256",
        "copied_artifacts",
    }
    assert request["schema"] == "harden_completion_request.v1"
    assert request["phase"] == "HARDEN"
    assert request["evidence_sha256"] == _normalized_precompletion_digest(evidence)
    assert request["input_manifest_sha256"] == _sha256(
        context["manifest_path"].read_bytes()
    )
    assert (
        request["canonical_commit"] == context["expected"]["commits"]["canonical_main"]
    )
    assert request["canonical_tree"] == context["expected"]["trees"]["canonical_main"]
    assert request["visual_render_declared"] is False
    source_inventory = {
        path.relative_to(context["source_root"]).as_posix(): _sha256(path.read_bytes())
        for path in context["source_root"].rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    copies = request["copied_artifacts"]
    assert isinstance(copies, list) and copies
    copied_sources = {
        item["source"]["path"]: item["source"]["sha256"] for item in copies
    }
    assert len(copies) == len(copied_sources) == len(source_inventory)
    assert copied_sources == source_inventory
    retained_paths = [item["retained"]["path"] for item in copies]
    retained_refs = [
        (item["retained"]["path"], item["retained"]["sha256"]) for item in copies
    ]
    assert len(retained_paths) == len(set(retained_paths))
    assert len(retained_refs) == len(set(retained_refs))
    copied_by_source = {
        (item["source"]["path"], item["source"]["sha256"]): item["retained"]
        for item in copies
    }
    for item in copies:
        assert set(item) == {"source", "retained"}
        assert set(item["source"]) == {"path", "sha256"}
        source = _contained_ref_path(
            context["source_root"], item["source"], "source artifact"
        )
        retained = _contained_ref_path(
            context["evidence_root"], item["retained"], "copied retained artifact"
        )
        assert source.read_bytes() == retained.read_bytes()
    assert not any(path.is_symlink() for path in context["evidence_root"].rglob("*"))
    required_reachable_refs = [
        context["manifest"]["artifacts"][name] for name in sorted(RAW_ARTIFACT_NAMES)
    ] + [context["manifest"]["role_attestations"][name] for name in ROLE_NAMES]
    required_retained_refs = {
        (
            copied_by_source[(ref["path"], ref["sha256"])]["path"],
            copied_by_source[(ref["path"], ref["sha256"])]["sha256"],
        )
        for ref in required_reachable_refs
    }
    assert len(required_retained_refs) == len(required_reachable_refs)
    reachable = _reachable_artifact_refs(evidence, context["evidence_root"])
    assert required_retained_refs <= reachable
    _verify_with_shipped_verifier(context, context["output"], "prepared")
    return evidence, request


def test_harden_producer_derives_live_facts_without_historical_literals() -> None:
    producer = _producer_module("derive")
    source = (_repo_root() / PRODUCER_PATH).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=PRODUCER_PATH)
    forbidden = {
        "FINAL_RUN_SPECS",
        "FROZEN_SL0_PATHS",
        "PLAN_PRODUCTION_PATHS",
        "SELF_TEST_ROUTES",
        "_fixture",
        "self_test",
    }
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not forbidden & referenced

    def static_string(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = static_string(node.left)
            right = static_string(node.right)
            if left is not None and right is not None:
                return left + right
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], (ast.List, ast.Tuple))
        ):
            separator = static_string(node.func.value)
            parts = [static_string(item) for item in node.args[0].elts]
            if separator is not None and all(part is not None for part in parts):
                return separator.join(part for part in parts if part is not None)
        if isinstance(node, ast.Subscript) and isinstance(
            node.value, (ast.List, ast.Tuple)
        ):
            index_node = node.slice
            sign = 1
            while isinstance(index_node, ast.UnaryOp) and isinstance(
                index_node.op, (ast.UAdd, ast.USub)
            ):
                if isinstance(index_node.op, ast.USub):
                    sign *= -1
                index_node = index_node.operand
            if isinstance(index_node, ast.Constant) and isinstance(
                index_node.value, int
            ):
                index = sign * index_node.value
                if -len(node.value.elts) <= index < len(node.value.elts):
                    return static_string(node.value.elts[index])
        return None

    alias_names = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.alias)
        for name in (node.name.rsplit(".", 1)[-1], node.asname)
        if name is not None
    }
    reconstructed_strings = {
        value for node in ast.walk(tree) if (value := static_string(node)) is not None
    }
    dynamic_accesses: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            value = static_string(node.slice)
            if value is not None:
                dynamic_accesses.add(value)
        if not isinstance(node, ast.Call):
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        argument_index = 0 if function_name == "attrgetter" else 1
        if (
            function_name
            in {
                "attrgetter",
                "delattr",
                "getattr",
                "hasattr",
                "setattr",
            }
            and len(node.args) > argument_index
        ):
            value = static_string(node.args[argument_index])
            if value is not None:
                dynamic_accesses.add(value)
    assert not {"_fixture", "self_test"} & (
        alias_names | reconstructed_strings | dynamic_accesses
    )
    for literal in (
        "16 failed, 439 passed, 3 skipped",
        "454 passed",
        "codex-gpt-5.6-terra",
    ):
        assert literal not in source
    assert INPUT_SCHEMA in source
    for name in ("derive_live_facts", "prepare", "seal"):
        assert callable(getattr(producer, name, None)), name

    facts_seen = []
    for author, red, final in _fixture_variants():
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(
                fixture_root,
                variant=_runtime_variant(fixture_root),
                author_vendor=author,
                red_outcomes=red,
                final_outcomes=final,
            )
            facts = producer.derive_live_facts(
                context["manifest_path"],
                evidence_root=context["source_root"],
                repo=context["repo"],
            )
            assert set(facts) == {
                "schema",
                "git",
                "changed_paths",
                "frozen_test_paths",
                "run_counts",
                "author_vendor",
                "routes",
            }
            assert facts["schema"] == "harden_live_facts.v1"
            assert facts["git"] == {
                name: {
                    "commit": context["expected"]["commits"][name],
                    "tree": context["expected"]["trees"][name],
                }
                for name in context["expected"]["commits"]
            }
            for key in (
                "changed_paths",
                "frozen_test_paths",
                "run_counts",
                "author_vendor",
                "routes",
            ):
                assert facts[key] == context["expected"][key]
            facts_seen.append(facts)
    for key in (
        "git",
        "changed_paths",
        "frozen_test_paths",
        "run_counts",
        "author_vendor",
        "routes",
    ):
        assert len({_canonical_bytes(facts[key]) for facts in facts_seen}) == len(
            facts_seen
        )


def test_harden_producer_assembles_only_contained_retained_evidence() -> None:
    _producer_module("assemble")

    for author, red, final in _fixture_variants():
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(
                fixture_root,
                variant=_runtime_variant(fixture_root),
                author_vendor=author,
                red_outcomes=red,
                final_outcomes=final,
            )
            registry_before = context["registry"].read_bytes()
            completed = _prepare_command(context)
            assert completed.returncode == 0, completed.stderr
            _assert_prepared(context)
            assert context["registry"].read_bytes() == registry_before

    def rejected(
        name: str,
        mutate: Callable[[dict[str, Any]], None],
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
            mutate(context)
            _persist_manifest(context)
            registry_before = context["registry"].read_bytes()
            completed = _prepare_command(context)
            assert completed.returncode != 0, name
            diagnostic = (completed.stderr + completed.stdout).lower()
            assert message.lower() in diagnostic, f"{name}: {diagnostic}"
            _assert_no_prepare_output(context)
            assert context["registry"].read_bytes() == registry_before

    rejected(
        "wrong-manifest-schema",
        lambda context: context["manifest"].__setitem__(
            "schema", f"{os.urandom(16).hex()}.v1"
        ),
        "input manifest schema mismatch",
    )
    rejected(
        "unknown-manifest-key",
        lambda context: context["manifest"].__setitem__(os.urandom(16).hex(), True),
        "unknown input manifest field",
    )
    for artifact in RAW_ARTIFACT_NAMES:
        rejected(
            f"missing-artifact-{artifact}",
            lambda context, artifact=artifact: context["manifest"]["artifacts"].pop(
                artifact
            ),
            "missing required input",
        )
    for role in ROLE_NAMES:
        rejected(
            f"missing-role-{role}",
            lambda context, role=role: context["manifest"]["role_attestations"].pop(
                role
            ),
            "missing required input",
        )
    rejected(
        "extra-artifact-key",
        lambda context: context["manifest"]["artifacts"].__setitem__(
            os.urandom(16).hex(),
            copy.deepcopy(context["manifest"]["artifacts"]["plan_authority"]),
        ),
        "unknown artifact input",
    )
    rejected(
        "extra-role-key",
        lambda context: context["manifest"]["role_attestations"].__setitem__(
            os.urandom(16).hex(),
            copy.deepcopy(context["manifest"]["role_attestations"]["author"]),
        ),
        "unknown role attestation",
    )
    for group, names, label in (
        ("artifacts", RAW_ARTIFACT_NAMES, "artifact"),
        ("role_attestations", ROLE_NAMES, "role attestation"),
    ):
        for value in (
            None,
            [],
            os.urandom(16).hex(),
            True,
            _different_count(0),
            _different_count(0) + 0.5,
        ):
            rejected(
                f"{group}-wrong-container-{type(value).__name__}",
                lambda context, group=group, value=value: context[
                    "manifest"
                ].__setitem__(group, value),
                f"{group} must be an object",
            )
        for name in names:
            for value in (
                None,
                [],
                os.urandom(16).hex(),
                True,
                _different_count(0),
                _different_count(0) + 0.5,
            ):
                rejected(
                    f"{name}-ref-wrong-container-{type(value).__name__}",
                    lambda context, group=group, name=name, value=value: context[
                        "manifest"
                    ][group].__setitem__(name, value),
                    f"{label} reference must be an object",
                )
            rejected(
                f"{name}-ref-empty",
                lambda context, group=group, name=name: context["manifest"][
                    group
                ].__setitem__(name, {}),
                f"{label} reference fields mismatch",
            )
            for field in ("path", "sha256"):
                rejected(
                    f"{name}-ref-missing-{field}",
                    lambda context, group=group, name=name, field=field: context[
                        "manifest"
                    ][group][name].pop(field),
                    f"{label} reference fields mismatch",
                )
                for value in (
                    None,
                    [],
                    {},
                    True,
                    _different_count(0),
                    _different_count(0) + 0.5,
                ):
                    rejected(
                        f"{name}-ref-{field}-wrong-type-{type(value).__name__}",
                        lambda context, group=group, name=name, field=field, value=value: (
                            context["manifest"][group][name].__setitem__(field, value)
                        ),
                        f"{label} reference field type",
                    )
            rejected(
                f"{name}-ref-extra-field",
                lambda context, group=group, name=name: context["manifest"][group][
                    name
                ].__setitem__(os.urandom(16).hex(), True),
                f"{label} reference fields mismatch",
            )

    def secret_extra_ref(context: dict[str, Any]) -> None:
        context["manifest"]["artifacts"][os.urandom(16).hex()] = _write_ref(
            context["source_root"],
            "raw/data.txt",
            f"api_key={os.urandom(24).hex()}\n".encode(),
        )

    rejected("secret-bearing-extra-ref", secret_extra_ref, "unknown artifact input")

    rejected(
        "caller-receipts",
        lambda context: context["manifest"].__setitem__(
            "receipts", {"candidate": {"passed": True}}
        ),
        "caller-authored receipt",
    )
    rejected(
        "caller-counts",
        lambda context: context["manifest"].__setitem__(
            "counts",
            {
                "passed": _different_count(
                    context["expected"]["run_counts"]["candidate_focused"]["passed"]
                )
            },
        ),
        "caller-authored counts",
    )
    rejected(
        "caller-git",
        lambda context: context["manifest"].__setitem__(
            "git",
            {
                "candidate_tree": _different_hex(
                    context["expected"]["trees"]["candidate"]
                )
            },
        ),
        "caller-authored git",
    )
    rejected(
        "caller-inventory",
        lambda context: context["manifest"].__setitem__("frozen_inventory", []),
        "caller-authored frozen_inventory",
    )
    rejected(
        "caller-author-vendor",
        lambda context: context["manifest"].__setitem__(
            "author_vendor", f"runtime-vendor-{os.urandom(16).hex()}"
        ),
        "caller-authored author_vendor",
    )
    rejected(
        "caller-routes",
        lambda context: context["manifest"].__setitem__("resolved_routes", []),
        "caller-authored resolved_routes",
    )

    def input_ref(context: dict[str, Any], group: str, name: str) -> dict[str, str]:
        return context["manifest"][group][name]

    attack_inputs = (
        *((f"artifact-{name}", "artifacts", name) for name in RAW_ARTIFACT_NAMES),
        *((f"role-{name}", "role_attestations", name) for name in ROLE_NAMES),
    )
    for label, group, artifact in attack_inputs:

        def absolute_path(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            ref["path"] = str((context["source_root"] / ref["path"]).resolve())

        rejected(f"{label}-absolute-path", absolute_path, "normalized relative path")

        def parent_traversal(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            ref["path"] = "raw/../raw/" + Path(ref["path"]).name

        rejected(f"{label}-parent-traversal", parent_traversal, "parent traversal")

        def digest_mismatch(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            ref["sha256"] = _different_hex(ref["sha256"])

        rejected(f"{label}-digest-mismatch", digest_mismatch, "digest mismatch")

        def direct_symlink(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            original = context["source_root"] / ref["path"]
            target = context["root"] / "data"
            target.write_bytes(original.read_bytes())
            original.unlink()
            original.symlink_to(target)

        rejected(f"{label}-direct-symlink", direct_symlink, "symlink")

        def ancestor_symlink(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            parent = (context["source_root"] / ref["path"]).parent
            target = context["root"] / "data"
            parent.replace(target)
            parent.symlink_to(target, target_is_directory=True)

        rejected(f"{label}-ancestor-symlink", ancestor_symlink, "symlink")

    def replace_input(
        context: dict[str, Any], group: str, name: str, value: Any
    ) -> None:
        ref = context["manifest"][group][name]
        data = value if isinstance(value, bytes) else _canonical_bytes(value)
        (context["source_root"] / ref["path"]).write_bytes(data)
        ref["sha256"] = _sha256(data)

    def replace_artifact(context: dict[str, Any], artifact: str, value: Any) -> None:
        replace_input(context, "artifacts", artifact, value)

    def secret_input(group: str, name: str) -> Callable[[dict[str, Any]], None]:
        def mutate(context: dict[str, Any]) -> None:
            secret_value = os.urandom(24).hex()
            ref = context["manifest"][group][name]
            path = context["source_root"] / ref["path"]
            if name.endswith("_raw"):
                value: Any = path.read_bytes() + f"api_key={secret_value}\n".encode()
            elif name.endswith("_junit"):
                value = path.read_bytes().replace(
                    b"</testsuite>",
                    (
                        f"<system-out>api_key={secret_value}</system-out></testsuite>"
                    ).encode(),
                )
                assert value != path.read_bytes()
            else:
                value = _strict_json(path)
                value[os.urandom(16).hex()] = f"api_key={secret_value}"
            replace_input(context, group, name, value)

        return mutate

    for artifact in RAW_ARTIFACT_NAMES:
        rejected(
            f"secret-artifact-{artifact}",
            secret_input("artifacts", artifact),
            "secret",
        )
    for role in ROLE_NAMES:
        rejected(
            f"secret-role-{role}",
            secret_input("role_attestations", role),
            "secret",
        )

    def lie_in_json(
        artifact: str, mutate: Callable[[dict[str, Any]], None]
    ) -> Callable[[dict[str, Any]], None]:
        def apply(context: dict[str, Any]) -> None:
            ref = context["manifest"]["artifacts"][artifact]
            record = _strict_json(context["source_root"] / ref["path"])
            mutate(record)
            replace_artifact(context, artifact, record)

        return apply

    rejected(
        "plan-live-git-lie",
        lie_in_json(
            "plan_authority",
            lambda record: record["commits"].__setitem__(
                "candidate", _different_hex(record["commits"]["candidate"])
            ),
        ),
        "plan authority does not match live Git",
    )
    rejected(
        "sl0-live-git-lie",
        lie_in_json(
            "sl0_review",
            lambda record: record.__setitem__(
                "reviewed_commit", record["landing_commit"]
            ),
        ),
        "SL-0 authority does not match live Git",
    )
    for round_name in ("candidate", "canonical_main"):
        for suffix, collection, label, fields in (
            (
                "broker_receipts",
                "receipts",
                "broker receipt",
                (
                    "harness",
                    "requested_model",
                    "resolved_model",
                    "result_kind",
                    "terminal_verdict",
                    "operation_nonce",
                ),
            ),
            (
                "review_request",
                "routes",
                "review route",
                ("harness", "requested_model", "resolved_model"),
            ),
        ):
            artifact = f"{round_name}_{suffix}"
            rejected(
                f"{artifact}-missing-{collection}",
                lie_in_json(
                    artifact,
                    lambda record, collection=collection: record.pop(collection),
                ),
                f"missing {label}",
            )
            rejected(
                f"{artifact}-empty-{collection}",
                lie_in_json(
                    artifact,
                    lambda record, collection=collection: record.__setitem__(
                        collection, []
                    ),
                ),
                f"missing {label}",
            )
            for index in range(4):
                rejected(
                    f"{artifact}-missing-seat-{index}",
                    lie_in_json(
                        artifact,
                        lambda record, collection=collection, index=index: record[
                            collection
                        ].pop(index),
                    ),
                    f"missing {label}",
                )
                for field in fields:
                    rejected(
                        f"{artifact}-seat-{index}-missing-{field}",
                        lie_in_json(
                            artifact,
                            lambda record, collection=collection, index=index, field=field: (
                                record[collection][index].pop(field)
                            ),
                        ),
                        "missing broker result"
                        if field in {"result_kind", "terminal_verdict"}
                        else f"missing {label} field",
                    )
            rejected(
                f"{artifact}-duplicate-harness",
                lie_in_json(
                    artifact,
                    lambda record, collection=collection: record[collection][
                        1
                    ].__setitem__("harness", record[collection][0]["harness"]),
                ),
                f"duplicate {label} harness",
            )
        for field in (
            "schema",
            "provider",
            "repository",
            "head",
            "run_id",
            "workflow",
            "event",
            "run_attempt",
            "check",
            "status",
            "conclusion",
        ):
            rejected(
                f"{round_name}-ci-missing-{field}",
                lie_in_json(
                    f"{round_name}_ci", lambda record, field=field: record.pop(field)
                ),
                "missing CI result"
                if field in {"status", "conclusion"}
                else "missing CI required field",
            )
        for field in ("schema", "round", "head", "tree", "operation_nonce"):
            rejected(
                f"{round_name}-review-missing-{field}",
                lie_in_json(
                    f"{round_name}_review_request",
                    lambda record, field=field: record.pop(field),
                ),
                "missing review required field",
            )
        for field, value in (("status", "queued"), ("conclusion", "failure")):
            rejected(
                f"{round_name}-ci-unsuccessful-{field}",
                lie_in_json(
                    f"{round_name}_ci",
                    lambda record, field=field, value=value: record.__setitem__(
                        field, value
                    ),
                ),
                "CI result is not successful",
            )
        for index in range(4):
            for field, value, message in (
                ("result_kind", "synthetic_self_test", "self-test material"),
                ("terminal_verdict", "DISAGREE", "broker result is not successful"),
            ):
                rejected(
                    f"{round_name}-broker-seat-{index}-invalid-{field}",
                    lie_in_json(
                        f"{round_name}_broker_receipts",
                        lambda record, index=index, field=field, value=value: record[
                            "receipts"
                        ][index].__setitem__(field, value),
                    ),
                    message,
                )

        def ci_head_lie(context: dict[str, Any], round_name: str = round_name) -> None:
            artifact = f"{round_name}_ci"
            ref = context["manifest"]["artifacts"][artifact]
            record = _strict_json(context["source_root"] / ref["path"])
            record["head"] = context["expected"]["commits"]["landing"]
            replace_artifact(context, artifact, record)

        rejected(
            f"{round_name}-ci-head-live-git-lie",
            ci_head_lie,
            "CI head does not match live Git",
        )
        for field, fact in (("head", "commits"), ("tree", "trees")):

            def review_identity_lie(
                context: dict[str, Any],
                round_name: str = round_name,
                field: str = field,
                fact: str = fact,
            ) -> None:
                artifact = f"{round_name}_review_request"
                ref = context["manifest"]["artifacts"][artifact]
                record = _strict_json(context["source_root"] / ref["path"])
                stale = context["expected"][fact]["landing"]
                assert stale != record[field]
                record[field] = stale
                replace_artifact(context, artifact, record)

            rejected(
                f"{round_name}-review-stale-{field}",
                review_identity_lie,
                f"review {field} does not match live Git",
            )
        rejected(
            f"{round_name}-broker-within-class-duplicate-nonce",
            lie_in_json(
                f"{round_name}_broker_receipts",
                lambda record: record["receipts"][1].__setitem__(
                    "operation_nonce", record["receipts"][0]["operation_nonce"]
                ),
            ),
            "duplicate input operation nonce",
        )

    def role_session_mismatch(context: dict[str, Any]) -> None:
        ref = context["manifest"]["role_attestations"]["coordinator"]
        record = _strict_json(context["source_root"] / ref["path"])
        record["session_sha256"] = context["sessions"]["reviewer"]
        replace_input(context, "role_attestations", "coordinator", record)

    rejected("role-session-mismatch", role_session_mismatch, "role session mismatch")

    def role_duplicate_nonce(context: dict[str, Any]) -> None:
        coordinator_ref = context["manifest"]["role_attestations"]["coordinator"]
        coordinator = _strict_json(context["source_root"] / coordinator_ref["path"])
        reviewer_ref = context["manifest"]["role_attestations"]["reviewer"]
        reviewer = _strict_json(context["source_root"] / reviewer_ref["path"])
        reviewer["operation_nonce"] = coordinator["operation_nonce"]
        replace_input(context, "role_attestations", "reviewer", reviewer)

    rejected(
        "role-within-class-duplicate-nonce",
        role_duplicate_nonce,
        "duplicate input operation nonce",
    )

    for raw_name, junit_name in RAW_JUNIT_PAIRS:
        pair_name = raw_name.removesuffix("_raw")
        rejected(
            f"{pair_name}-raw-count-mismatch",
            lambda context, raw_name=raw_name, pair_name=pair_name: replace_artifact(
                context,
                raw_name,
                (
                    f"{_different_count(context['expected']['run_counts'][pair_name]['passed'])}"
                    " passed\n"
                ).encode(),
            ),
            "raw/JUnit count mismatch",
        )
        rejected(
            f"{pair_name}-junit-count-mismatch",
            lambda context, junit_name=junit_name, pair_name=pair_name: (
                replace_artifact(
                    context,
                    junit_name,
                    _junit_bytes(
                        ("passed",)
                        * _different_count(
                            context["expected"]["run_counts"][pair_name]["passed"]
                        )
                    ),
                )
            ),
            "raw/JUnit count mismatch",
        )

    def reuse_id(context: dict[str, Any]) -> None:
        context["registry"].write_bytes(
            _canonical_bytes(
                {
                    "schema": "harden_evidence_registry.v1",
                    "evidence_ids": [
                        *context["expected"]["registry"]["evidence_ids"],
                        context["expected"]["evidence_id"],
                    ],
                    "operation_nonces": context["expected"]["registry"][
                        "operation_nonces"
                    ],
                }
            )
        )

    rejected("reused-evidence", reuse_id, "reused evidence_id")

    def reuse_nonce(index: int) -> Callable[[dict[str, Any]], None]:
        def mutate(context: dict[str, Any]) -> None:
            context["registry"].write_bytes(
                _canonical_bytes(
                    {
                        "schema": "harden_evidence_registry.v1",
                        "evidence_ids": context["expected"]["registry"]["evidence_ids"],
                        "operation_nonces": [
                            *context["expected"]["registry"]["operation_nonces"],
                            context["expected"]["operation_nonces"][index],
                        ],
                    }
                )
            )

        return mutate

    for index in range(13):
        if index < 2:
            kind = "review-request"
        elif index < 10:
            kind = "broker-receipt"
        else:
            kind = "role-attestation"
        rejected(
            f"reused-{kind}-nonce-{index}",
            reuse_nonce(index),
            "reused operation nonce",
        )

    def duplicate_review_request_nonce(context: dict[str, Any]) -> None:
        ref = context["manifest"]["artifacts"]["canonical_main_review_request"]
        record = _strict_json(context["source_root"] / ref["path"])
        record["operation_nonce"] = context["expected"]["operation_nonces"][0]
        replace_artifact(context, "canonical_main_review_request", record)

    rejected(
        "duplicate-review-request-nonce",
        duplicate_review_request_nonce,
        "duplicate input operation nonce",
    )

    def duplicate_input_nonce(context: dict[str, Any]) -> None:
        nonce = context["expected"]["operation_nonces"][0]
        broker_ref = context["manifest"]["artifacts"]["candidate_broker_receipts"]
        broker = _strict_json(context["source_root"] / broker_ref["path"])
        broker["receipts"][0]["operation_nonce"] = nonce
        replace_artifact(context, "candidate_broker_receipts", broker)
        role_ref = context["manifest"]["role_attestations"]["coordinator"]
        role = _strict_json(context["source_root"] / role_ref["path"])
        role["operation_nonce"] = nonce
        role_data = _canonical_bytes(role)
        (context["source_root"] / role_ref["path"]).write_bytes(role_data)
        role_ref["sha256"] = _sha256(role_data)

    rejected(
        "duplicate-input-nonce-across-request-broker-role",
        duplicate_input_nonce,
        "duplicate input operation nonce",
    )

    with tempfile.TemporaryDirectory(prefix="pl-") as td:
        fixture_root = Path(td) / "fixture"
        context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
        body = _canonical_bytes(context["manifest"])
        duplicate = body.replace(
            b'"schema":"harden_evidence_inputs.v1"}',
            b'"schema":"harden_evidence_inputs.v1",'
            b'"schema":"harden_evidence_inputs.v1"}',
        )
        assert duplicate != body
        assert isinstance(json.loads(duplicate), dict)
        context["manifest_path"].write_bytes(duplicate)
        registry_before = context["registry"].read_bytes()
        completed = _prepare_command(context)
        assert completed.returncode != 0
        diagnostic = (completed.stderr + completed.stdout).lower()
        assert "duplicate json key" in diagnostic, diagnostic
        _assert_no_prepare_output(context)
        assert context["registry"].read_bytes() == registry_before

    top_help = _producer_command("--help")
    assert top_help.returncode == 0, top_help.stderr
    assert "prepare" in top_help.stdout and "seal" in top_help.stdout
    prepare_help = _producer_command("prepare", "--help")
    assert prepare_help.returncode == 0, prepare_help.stderr
    for option in (
        "--inputs",
        "--source-root",
        "--evidence-root",
        "--repo",
        "--output",
        "--completion-request",
        "--reuse-registry",
        "--expected-coordinator-session-sha256",
        "--expected-author-session-sha256",
    ):
        assert option in prepare_help.stdout


def test_harden_producer_prepare_then_seal_binds_one_canonical_event() -> None:
    _producer_module("seal")

    with tempfile.TemporaryDirectory(prefix="pl-") as td:
        fixture_root = Path(td) / "fixture"
        context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
        registry_before_bytes = context["registry"].read_bytes()
        registry_before = _strict_json(context["registry"])
        prepared = _prepare_command(context)
        assert prepared.returncode == 0, prepared.stderr
        evidence, request = _assert_prepared(context)
        assert context["registry"].read_bytes() == registry_before_bytes
        canonical_ledger = context["repo"] / ".phase-loop/events.jsonl"
        canonical_ledger.parent.mkdir(parents=True)
        canonical_ledger.write_bytes(_ledger_bytes(request))
        sealed_path = context["root"] / "sealed-evidence.json"
        sealed_run = _seal_command(context, canonical_ledger, sealed_path)
        assert sealed_run.returncode == 0, sealed_run.stderr
        sealed = _strict_json(sealed_path)
        assert sealed["completion"]["mode"] == "post_completion"
        assert _normalized_precompletion_digest(sealed) == request["evidence_sha256"]
        assert _normalized_precompletion_digest(evidence) == request["evidence_sha256"]
        ledger_ref = sealed["completion"]["ledger"]
        assert set(ledger_ref) == {"path", "sha256"}
        retained_ledger = _contained_ref_path(
            context["evidence_root"], ledger_ref, "sealed completion ledger"
        )
        assert retained_ledger.read_bytes() == canonical_ledger.read_bytes()
        assert not any(
            path.is_symlink() for path in context["evidence_root"].rglob("*")
        )
        registry = _strict_json(context["registry"])
        assert len(registry["evidence_ids"]) == len(registry_before["evidence_ids"]) + 1
        assert set(registry["evidence_ids"]) == {
            *registry_before["evidence_ids"],
            evidence["evidence_id"],
        }
        assert len(registry["operation_nonces"]) == (
            len(registry_before["operation_nonces"]) + 13
        )
        assert set(registry["operation_nonces"]) == {
            *registry_before["operation_nonces"],
            *context["expected"]["operation_nonces"],
        }
        _verify_with_shipped_verifier(context, sealed_path, "sealed")

    def seal_rejected(
        name: str,
        mutate: Callable[[dict[str, Any], Path, dict[str, Any]], Path],
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
            prepared = _prepare_command(context)
            assert prepared.returncode == 0, prepared.stderr
            _evidence, request = _assert_prepared(context)
            canonical = context["repo"] / ".phase-loop/events.jsonl"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(_ledger_bytes(request))
            ledger_argument = mutate(context, canonical, request)
            output = context["root"] / "sealed-evidence.json"
            registry_before = context["registry"].read_bytes()
            completed = _seal_command(context, ledger_argument, output)
            assert completed.returncode != 0, name
            diagnostic = (completed.stderr + completed.stdout).lower()
            assert message.lower() in diagnostic, f"{name}: {diagnostic}"
            assert not output.exists()
            assert context["registry"].read_bytes() == registry_before

    def detached(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        path = context["root"] / "events.jsonl"
        path.write_bytes(canonical.read_bytes())
        assert path.is_file() and not path.is_symlink()
        return path

    seal_rejected("regular-detached-ledger", detached, "canonical ledger path")

    for group, names in (
        ("artifacts", RAW_ARTIFACT_NAMES),
        ("role_attestations", ROLE_NAMES),
    ):
        for name in names:

            def retained_byte_drift(
                context: dict[str, Any],
                canonical: Path,
                request: dict[str, Any],
                group: str = group,
                name: str = name,
            ) -> Path:
                source = context["manifest"][group][name]
                retained = next(
                    item["retained"]
                    for item in request["copied_artifacts"]
                    if item["source"] == source
                )
                path = _contained_ref_path(
                    context["evidence_root"], retained, "retained drift target"
                )
                path.write_bytes(path.read_bytes() + b"\n")
                assert _sha256(path.read_bytes()) != retained["sha256"]
                return canonical

            seal_rejected(
                f"retained-byte-drift-{group}-{name}",
                retained_byte_drift,
                "digest mismatch",
            )

    def zero_event(
        _context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        canonical.write_bytes(_ledger_history_bytes())
        return canonical

    seal_rejected("zero-event", zero_event, "missing HARDEN completion")

    def duplicate(
        _context: dict[str, Any], canonical: Path, request: dict[str, Any]
    ) -> Path:
        canonical.write_bytes(
            _ledger_history_bytes()
            + _canonical_bytes(_completion_event(request))
            + _canonical_bytes(
                _completion_event(request, timestamp="2026-09-04T00:00:01Z")
            )
        )
        return canonical

    seal_rejected("duplicate-event", duplicate, "duplicate HARDEN completion")

    def registry_evidence_collision(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        registry = _strict_json(context["registry"])
        registry["evidence_ids"].append(context["expected"]["evidence_id"])
        context["registry"].write_bytes(_canonical_bytes(registry))
        return canonical

    seal_rejected(
        "seal-registry-evidence-collision",
        registry_evidence_collision,
        "reused evidence_id",
    )

    def registry_nonce_collision(
        index: int,
    ) -> Callable[[dict[str, Any], Path, dict[str, Any]], Path]:
        def mutate(
            context: dict[str, Any], canonical: Path, _request: dict[str, Any]
        ) -> Path:
            registry = _strict_json(context["registry"])
            registry["operation_nonces"].append(
                context["expected"]["operation_nonces"][index]
            )
            context["registry"].write_bytes(_canonical_bytes(registry))
            return canonical

        return mutate

    for index in range(13):
        seal_rejected(
            f"seal-registry-nonce-collision-{index}",
            registry_nonce_collision(index),
            "reused operation nonce",
        )

    def stale_precompletion(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        evidence = _strict_json(context["output"])
        evidence["evidence_id"] = _different_hex(evidence["evidence_id"])
        context["output"].write_bytes(_canonical_bytes(evidence))
        return canonical

    seal_rejected(
        "stale-precompletion",
        stale_precompletion,
        "pre-completion digest mismatch",
    )

    def mismatched_event_field(
        field: str,
    ) -> Callable[[dict[str, Any], Path, dict[str, Any]], Path]:
        def mutate(
            _context: dict[str, Any], canonical: Path, request: dict[str, Any]
        ) -> Path:
            event = _completion_event(request)
            proof = event["metadata"]["harden_completion"]
            proof[field] = _different_hex(proof[field])
            canonical.write_bytes(
                _ledger_history_bytes()
                + _canonical_bytes(event)
                + _canonical_bytes(
                    _completion_event(request, timestamp="2026-09-04T00:00:01Z")
                )
            )
            return canonical

        return mutate

    seal_rejected(
        "mismatched-event-digest",
        mismatched_event_field("evidence_sha256"),
        "completion event evidence digest mismatch",
    )
    seal_rejected(
        "mismatched-event-commit",
        mismatched_event_field("canonical_commit"),
        "completion event commit mismatch",
    )
    seal_rejected(
        "mismatched-event-tree",
        mismatched_event_field("canonical_tree"),
        "completion event tree mismatch",
    )

    def invalid_completion(
        mutate: Callable[[dict[str, Any]], None],
        *,
        encode: Callable[[dict[str, Any]], bytes] = _canonical_bytes,
    ) -> Callable[[dict[str, Any], Path, dict[str, Any]], Path]:
        def apply(
            _context: dict[str, Any], canonical: Path, request: dict[str, Any]
        ) -> Path:
            event = _completion_event(request)
            mutate(event)
            canonical.write_bytes(
                _ledger_history_bytes()
                + encode(event)
                + _canonical_bytes(
                    _completion_event(request, timestamp="2026-09-04T00:00:01Z")
                )
            )
            return canonical

        return apply

    seal_rejected(
        "wrong-completion-schema",
        invalid_completion(
            lambda event: event["metadata"]["harden_completion"].__setitem__(
                "schema", f"{os.urandom(16).hex()}.v1"
            )
        ),
        "completion schema mismatch",
    )
    seal_rejected(
        "wrong-completion-visual-declaration",
        invalid_completion(
            lambda event: event["metadata"]["harden_completion"].__setitem__(
                "visual_render_declared", True
            )
        ),
        "completion visual_render_declared mismatch",
    )
    seal_rejected(
        "missing-completion-proof",
        invalid_completion(lambda event: event["metadata"].pop("harden_completion")),
        "missing HARDEN completion proof",
    )
    for value in (
        None,
        [],
        os.urandom(16).hex(),
        True,
        _different_count(0),
        _different_count(0) + 0.5,
    ):
        seal_rejected(
            f"invalid-completion-proof-{type(value).__name__}",
            invalid_completion(
                lambda event, value=value: event["metadata"].__setitem__(
                    "harden_completion", value
                )
            ),
            "invalid HARDEN completion proof",
        )
    seal_rejected(
        "empty-completion-proof",
        invalid_completion(
            lambda event: event["metadata"].__setitem__("harden_completion", {})
        ),
        "completion proof fields mismatch",
    )
    for field in (
        "schema",
        "evidence_sha256",
        "canonical_commit",
        "canonical_tree",
        "visual_render_declared",
    ):
        seal_rejected(
            f"completion-proof-missing-{field}",
            invalid_completion(
                lambda event, field=field: event["metadata"]["harden_completion"].pop(
                    field
                )
            ),
            "completion proof fields mismatch",
        )
        invalid_types = (
            (None, [], {}, "false", "", 0, 1, 0.0, 1.0)
            if field == "visual_render_declared"
            else (None, [], {}, False, _different_count(0), _different_count(0) + 0.5)
        )
        for index, value in enumerate(invalid_types):
            seal_rejected(
                f"completion-proof-{field}-wrong-type-{index}",
                invalid_completion(
                    lambda event, field=field, value=value: event["metadata"][
                        "harden_completion"
                    ].__setitem__(field, value)
                ),
                "completion proof field type",
            )
    seal_rejected(
        "completion-proof-extra-field",
        invalid_completion(
            lambda event: event["metadata"]["harden_completion"].__setitem__(
                os.urandom(16).hex(), True
            )
        ),
        "completion proof fields mismatch",
    )
    seal_rejected(
        "malformed-completion-json",
        invalid_completion(
            lambda event: None,
            encode=lambda event: _canonical_bytes(event)[:-2] + b"\n",
        ),
        "invalid completion ledger JSON",
    )
    seal_rejected(
        "duplicate-completion-proof-key",
        invalid_completion(
            lambda event: None,
            encode=lambda event: _canonical_bytes(event).replace(
                b'"visual_render_declared":false',
                b'"visual_render_declared":false,"visual_render_declared":false',
            ),
        ),
        "duplicate JSON key",
    )
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        seal_rejected(
            f"nonfinite-completion-proof-{token.decode()}",
            invalid_completion(
                lambda event: None,
                encode=lambda event, token=token: _canonical_bytes(event).replace(
                    b'"visual_render_declared":false',
                    b'"visual_render_declared":' + token,
                ),
            ),
            "invalid completion ledger JSON",
        )

    def symlink_canonical_ledger(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        target = context["root"] / "events.jsonl"
        canonical.replace(target)
        canonical.symlink_to(target)
        return canonical

    seal_rejected(
        "symlink-canonical-ledger",
        symlink_canonical_ledger,
        "canonical ledger symlink",
    )

    def symlink_canonical_ledger_ancestor(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        phase_loop = canonical.parent
        target = context["root"] / "data"
        phase_loop.replace(target)
        phase_loop.symlink_to(target, target_is_directory=True)
        return canonical

    seal_rejected(
        "symlink-canonical-ledger-ancestor",
        symlink_canonical_ledger_ancestor,
        "canonical ledger symlink",
    )

    seal_help = _producer_command("seal", "--help")
    assert seal_help.returncode == 0, seal_help.stderr
    for option in (
        "--pre-completion",
        "--evidence-root",
        "--repo",
        "--ledger",
        "--output",
        "--reuse-registry",
        "--expected-coordinator-session-sha256",
        "--expected-author-session-sha256",
    ):
        assert option in seal_help.stdout
