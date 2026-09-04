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
ROLE_NAMES = ("coordinator", "author", "reviewer")
HEX64_A = "a" * 64
HEX64_B = hashlib.sha256(b"01a04424-61d9-7712-94a6-e058cbe1349e").hexdigest()


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
        artifacts[name] = _write_ref(
            source_root, f"raw/{name}.{extension}", data
        )
    for round_name, head in (
        ("candidate", candidate),
        ("canonical_main", canonical_main),
    ):
        ci = {
            "schema": "harden_ci_result.v1",
            "provider": "github_actions",
            "repository": "Consiliency/agent-harness",
            "head": head,
            "run_id": 100 if round_name == "candidate" else 200,
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
        "coordinator": HEX64_A,
        "author": HEX64_B,
        "reviewer": _sha256(f"{variant}:reviewer-session".encode()),
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
    registry_path = root / "reuse-registry.json"
    registry_path.write_bytes(
        _canonical_bytes(
            {
                "schema": "harden_evidence_registry.v1",
                "evidence_ids": [],
                "operation_nonces": [],
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
        for round_name, run_id in (("candidate", 100), ("canonical_main", 200))
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
            "preproduction_red": {
                name: red_outcomes.count(name)
                for name in ("passed", "failed", "skipped")
            },
            "candidate_focused": {
                name: final_outcomes.count(name)
                for name in ("passed", "failed", "skipped")
            },
        },
        "author_vendor": author_vendor,
        "routes": routes,
        "operation_nonces": operation_nonces,
        "ci_run_ids": {"candidate": 100, "canonical_main": 200},
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


def _completion_event(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": "2026-09-04T00:00:00Z",
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


def _contained_ref_path(root: Path, ref: dict[str, str], label: str) -> Path:
    assert set(ref) == {"path", "sha256"}
    raw = ref["path"]
    relative = PurePosixPath(raw)
    assert not relative.is_absolute(), f"{label} path must be relative"
    assert str(relative) == raw and all(
        part not in {"", ".", ".."} for part in relative.parts
    ), f"{label} path must be normalized"
    root_resolved = root.resolve()
    path = (root / Path(*relative.parts)).resolve()
    assert path.is_relative_to(root_resolved), f"{label} path escaped its root"
    assert path.is_file() and not path.is_symlink(), f"{label} is not a regular file"
    assert _sha256(path.read_bytes()) == ref["sha256"], f"{label} digest mismatch"
    return path


def _reachable_artifact_digests(value: Any, root: Path) -> set[str]:
    reachable: set[str] = set()
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
            data = path.read_bytes()
            if item["sha256"] in reachable:
                continue
            reachable.add(item["sha256"])
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
    assert sorted(item["path"] for item in evidence["sl0"]["frozen_inventory"]) == (
        context["expected"]["frozen_test_paths"]
    )
    for round_name, run_id in context["expected"]["ci_run_ids"].items():
        assert evidence["ci"][round_name]["head"] == context["expected"]["commits"][
            round_name
        ]
        assert evidence["ci"][round_name]["run_id"] == run_id
    assert set(evidence["reviews"]) == {"candidate", "canonical_main"}
    assert set(evidence["roles"]) == set(ROLE_NAMES)
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
    assert request["canonical_commit"] == context["expected"]["commits"][
        "canonical_main"
    ]
    assert request["canonical_tree"] == context["expected"]["trees"][
        "canonical_main"
    ]
    assert request["visual_render_declared"] is False
    source_inventory = {
        path.relative_to(context["source_root"]).as_posix(): _sha256(path.read_bytes())
        for path in context["source_root"].rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    copies = request["copied_artifacts"]
    assert isinstance(copies, list) and copies
    assert {
        item["source"]["path"]: item["source"]["sha256"] for item in copies
    } == source_inventory
    for item in copies:
        assert set(item) == {"source", "retained"}
        assert set(item["source"]) == {"path", "sha256"}
        source = context["source_root"] / item["source"]["path"]
        retained = _contained_ref_path(
            context["evidence_root"], item["retained"], "copied retained artifact"
        )
        assert source.read_bytes() == retained.read_bytes()
    assert not any(path.is_symlink() for path in context["evidence_root"].rglob("*"))
    required_reachable_refs = [
        context["manifest"]["artifacts"][name]
        for name in sorted(RAW_ARTIFACT_NAMES)
    ] + [context["manifest"]["role_attestations"][name] for name in ROLE_NAMES]
    reachable = _reachable_artifact_digests(evidence, context["evidence_root"])
    assert {ref["sha256"] for ref in required_reachable_refs} <= reachable
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
    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not forbidden & referenced
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
    with tempfile.TemporaryDirectory(prefix="harden-live-facts-") as td:
        for variant, author, red, final in (
            (
                "alpha",
                "codex-gpt-5.6-terra",
                ("failed", "passed", "skipped"),
                ("passed", "passed"),
            ),
            (
                "beta",
                "claude-fable-5",
                ("failed", "failed", "passed", "passed"),
                ("passed", "passed", "passed"),
            ),
        ):
            context = _raw_fixture(
                Path(td) / variant,
                variant=variant,
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
        assert facts_seen[0][key] != facts_seen[1][key]


def test_harden_producer_assembles_only_contained_retained_evidence() -> None:
    _producer_module("assemble")

    with tempfile.TemporaryDirectory(prefix="harden-prepare-success-") as td:
        valid = _raw_fixture(Path(td) / "valid")
        completed = _prepare_command(valid)
        assert completed.returncode == 0, completed.stderr
        _assert_prepared(valid)

    def rejected(
        name: str,
        mutate: Callable[[dict[str, Any]], None],
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix=f"harden-{name}-") as td:
            context = _raw_fixture(Path(td) / "valid")
            mutate(context)
            _persist_manifest(context)
            registry_before = context["registry"].read_bytes()
            completed = _prepare_command(context)
            assert completed.returncode != 0
            diagnostic = (completed.stderr + completed.stdout).lower()
            assert message.lower() in diagnostic, diagnostic
            _assert_no_prepare_output(context)
            assert context["registry"].read_bytes() == registry_before

    rejected(
        "caller-receipts",
        lambda context: context["manifest"].__setitem__(
            "receipts", {"candidate": {"passed": True}}
        ),
        "caller-authored receipt",
    )
    rejected(
        "caller-counts",
        lambda context: context["manifest"].__setitem__("counts", {"passed": 454}),
        "caller-authored counts",
    )
    rejected(
        "caller-git",
        lambda context: context["manifest"].__setitem__(
            "git", {"candidate_tree": "0" * 40}
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
            "author_vendor", "codex-gpt-5.6-terra"
        ),
        "caller-authored author_vendor",
    )
    rejected(
        "caller-routes",
        lambda context: context["manifest"].__setitem__("resolved_routes", []),
        "caller-authored resolved_routes",
    )
    rejected(
        "absolute-path",
        lambda context: context["manifest"]["artifacts"][
            "plan_authority"
        ].__setitem__(
            "path", str((context["source_root"] / "raw/plan-authority.json").resolve())
        ),
        "normalized relative path",
    )
    rejected(
        "parent-traversal",
        lambda context: context["manifest"]["artifacts"][
            "plan_authority"
        ].__setitem__("path", "raw/../plan-authority.json"),
        "parent traversal",
    )
    rejected(
        "digest-mismatch",
        lambda context: context["manifest"]["artifacts"][
            "plan_authority"
        ].__setitem__("sha256", "f" * 64),
        "digest mismatch",
    )

    def symlink_input(context: dict[str, Any]) -> None:
        original = context["source_root"] / "raw/plan-authority.json"
        target = context["root"] / "outside.json"
        target.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(target)

    rejected("symlink", symlink_input, "symlink")

    def replace_artifact(
        context: dict[str, Any], artifact: str, value: Any
    ) -> None:
        ref = context["manifest"]["artifacts"][artifact]
        data = value if isinstance(value, bytes) else _canonical_bytes(value)
        (context["source_root"] / ref["path"]).write_bytes(data)
        ref["sha256"] = _sha256(data)

    rejected(
        "secret",
        lambda context: replace_artifact(
            context,
            "candidate_ci",
            {
                "schema": "harden_ci_result.v1",
                "api_key": "synthetic-token-0123456789abcdef",
            },
        ),
        "secret",
    )
    rejected(
        "raw-junit-count-mismatch",
        lambda context: replace_artifact(
            context,
            "candidate_broad_raw",
            b"999 passed\n",
        ),
        "raw/JUnit count mismatch",
    )

    def copied_self_test(context: dict[str, Any]) -> None:
        ref = context["manifest"]["artifacts"]["candidate_broker_receipts"]
        record = _strict_json(context["source_root"] / ref["path"])
        record["receipts"][0]["result_kind"] = "synthetic_self_test"
        replace_artifact(context, "candidate_broker_receipts", record)

    rejected("copied-self-test", copied_self_test, "self-test material")

    def reuse_id(context: dict[str, Any]) -> None:
        context["registry"].write_bytes(
            _canonical_bytes(
                {
                    "schema": "harden_evidence_registry.v1",
                    "evidence_ids": [context["expected"]["evidence_id"]],
                    "operation_nonces": [],
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
                        "evidence_ids": [],
                        "operation_nonces": [
                            context["expected"]["operation_nonces"][index]
                        ],
                    }
                )
            )

        return mutate

    rejected("reused-review-request-nonce", reuse_nonce(0), "reused operation nonce")
    rejected("reused-broker-receipt-nonce", reuse_nonce(2), "reused operation nonce")
    rejected("reused-role-attestation-nonce", reuse_nonce(10), "reused operation nonce")

    def duplicate_input_nonce(context: dict[str, Any]) -> None:
        ref = context["manifest"]["artifacts"]["canonical_main_review_request"]
        record = _strict_json(context["source_root"] / ref["path"])
        record["operation_nonce"] = context["expected"]["operation_nonces"][0]
        replace_artifact(context, "canonical_main_review_request", record)

    rejected(
        "duplicate-input-nonce",
        duplicate_input_nonce,
        "duplicate input operation nonce",
    )

    with tempfile.TemporaryDirectory(prefix="harden-duplicate-key-") as td:
        context = _raw_fixture(Path(td) / "valid")
        body = _canonical_bytes(context["manifest"])
        context["manifest_path"].write_bytes(
            b'{"schema":"harden_evidence_inputs.v1",'
            b'"schema":"harden_evidence_inputs.v1",'
            + body.split(b",", 1)[1]
        )
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

    with tempfile.TemporaryDirectory(prefix="harden-two-stage-") as td:
        context = _raw_fixture(Path(td) / "valid")
        prepared = _prepare_command(context)
        assert prepared.returncode == 0, prepared.stderr
        evidence, request = _assert_prepared(context)
        canonical_ledger = context["repo"] / ".phase-loop/events.jsonl"
        canonical_ledger.parent.mkdir(parents=True)
        canonical_ledger.write_bytes(_canonical_bytes(_completion_event(request)))
        sealed_path = context["root"] / "sealed-evidence.json"
        sealed_run = _seal_command(context, canonical_ledger, sealed_path)
        assert sealed_run.returncode == 0, sealed_run.stderr
        sealed = _strict_json(sealed_path)
        assert sealed["completion"]["mode"] == "post_completion"
        assert _normalized_precompletion_digest(sealed) == request["evidence_sha256"]
        assert _normalized_precompletion_digest(evidence) == request["evidence_sha256"]
        ledger_ref = sealed["completion"]["ledger"]
        assert set(ledger_ref) == {"path", "sha256"}
        retained_ledger = context["evidence_root"] / ledger_ref["path"]
        assert retained_ledger.read_bytes() == canonical_ledger.read_bytes()
        registry = _strict_json(context["registry"])
        assert evidence["evidence_id"] in registry["evidence_ids"]
        assert set(context["expected"]["operation_nonces"]) <= set(
            registry["operation_nonces"]
        )
        _verify_with_shipped_verifier(context, sealed_path, "sealed")

    def seal_rejected(
        name: str,
        mutate: Callable[[dict[str, Any], Path, dict[str, Any]], Path],
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix=f"harden-seal-{name}-") as td:
            context = _raw_fixture(Path(td) / "valid")
            prepared = _prepare_command(context)
            assert prepared.returncode == 0, prepared.stderr
            _evidence, request = _assert_prepared(context)
            canonical = context["repo"] / ".phase-loop/events.jsonl"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(_canonical_bytes(_completion_event(request)))
            ledger_argument = mutate(context, canonical, request)
            output = context["root"] / "must-not-exist.json"
            registry_before = context["registry"].read_bytes()
            completed = _seal_command(context, ledger_argument, output)
            assert completed.returncode != 0
            diagnostic = (completed.stderr + completed.stdout).lower()
            assert message.lower() in diagnostic, diagnostic
            assert not output.exists()
            assert context["registry"].read_bytes() == registry_before

    def detached(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        path = context["root"] / "detached-ledger.jsonl"
        path.write_bytes(canonical.read_bytes())
        assert path.is_file() and not path.is_symlink()
        return path

    seal_rejected("regular-detached-ledger", detached, "canonical ledger path")

    def zero_event(
        _context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        canonical.write_bytes(b"")
        return canonical

    seal_rejected("zero-event", zero_event, "missing HARDEN completion")

    def duplicate(
        _context: dict[str, Any], canonical: Path, request: dict[str, Any]
    ) -> Path:
        canonical.write_bytes(
            _canonical_bytes(_completion_event(request))
            + _canonical_bytes(_completion_event(request))
        )
        return canonical

    seal_rejected("duplicate-event", duplicate, "duplicate HARDEN completion")

    def stale_precompletion(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        evidence = _strict_json(context["output"])
        evidence["evidence_id"] = "f" * 64
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
            proof[field] = "f" * len(proof[field])
            canonical.write_bytes(_canonical_bytes(event))
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

    def symlink_canonical_ledger(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        target = context["root"] / "canonical-ledger-target.jsonl"
        canonical.replace(target)
        canonical.symlink_to(target)
        return canonical

    seal_rejected(
        "symlink-canonical-ledger",
        symlink_canonical_ledger,
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
