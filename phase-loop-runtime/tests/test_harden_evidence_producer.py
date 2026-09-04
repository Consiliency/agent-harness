"""HARDEN SL-4 tests-only contract for the retained-evidence producer.

The ordinary suite skips these three capability cases until the production
producer exists.  The explicit SL-4 TDD run instead stops at one unique marker
per contract seam.  Once SL-5 adds the producer, the same cases exercise the
real command and the shipped verifier; no synthetic completion artifact is
accepted as production evidence.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
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
RETAINED_ARTIFACT_NAMES = (
    "plan_authority",
    "sl0_review",
    "preproduction_verification",
    "candidate_verification",
    "canonical_main_verification",
    "candidate_ci",
    "candidate_review",
    "canonical_main_ci",
    "canonical_main_review",
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _producer_module(case: str) -> Any:
    path = _repo_root() / PRODUCER_PATH
    if not path.is_file():
        if os.environ.get(ACTIVATION_ENV) == "1":
            pytest.fail(ANCHORS[case], pytrace=False)
        pytest.skip(SKIP_REASON)
    spec = importlib.util.spec_from_file_location("harden_evidence_producer", path)
    assert spec is not None and spec.loader is not None, (
        f"{PRODUCER_PATH} does not resolve to an importable Python module"
    )
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


def _write_ref(root: Path, name: str, payload: bytes) -> dict[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": name, "sha256": _sha256(payload)}


def _input_manifest(root: Path) -> dict[str, Any]:
    placeholder = _canonical_bytes({"schema": "retained_harden_test_input.v1"})
    ref = _write_ref(root, "retained/placeholder.json", placeholder)
    return {
        "schema": INPUT_SCHEMA,
        "artifacts": {name: dict(ref) for name in RETAINED_ARTIFACT_NAMES},
        "role_attestations": {name: dict(ref) for name in ROLE_NAMES},
    }


def _run_invalid_prepare(
    root: Path,
    manifest: dict[str, Any] | bytes,
) -> subprocess.CompletedProcess[str]:
    manifest_path = root / "inputs.json"
    manifest_path.write_bytes(
        manifest if isinstance(manifest, bytes) else _canonical_bytes(manifest)
    )
    output = root / "verification-evidence.json"
    request = root / "completion-request.json"
    prepared_root = root / "prepared"
    registry = root / "reuse-registry.json"
    registry.write_bytes(
        _canonical_bytes(
            {
                "schema": "harden_evidence_registry.v1",
                "evidence_ids": [],
                "operation_nonces": [],
            }
        )
    )
    completed = _producer_command(
        "prepare",
        "--inputs",
        str(manifest_path),
        "--source-root",
        str(root),
        "--evidence-root",
        str(prepared_root),
        "--repo",
        str(_repo_root()),
        "--output",
        str(output),
        "--completion-request",
        str(request),
        "--reuse-registry",
        str(registry),
        "--expected-coordinator-session-sha256",
        "a" * 64,
        "--expected-author-session-sha256",
        "b" * 64,
    )
    assert completed.returncode != 0
    assert not output.exists()
    assert not request.exists()
    return completed


def _load_verifier() -> Any:
    path = _repo_root() / "phase-loop-runtime/scripts/verify_harden_evidence.py"
    spec = importlib.util.spec_from_file_location("harden_evidence_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verifier_fixture(verifier: Any, root: Path) -> dict[str, Any]:
    """Create only an ephemeral unit oracle; the producer may not call it."""

    root.mkdir()
    fixture = getattr(verifier, "_fixture", None)
    assert callable(fixture)
    (
        evidence_path,
        artifacts,
        repo,
        evidence,
        registry,
        coordinator,
        author,
    ) = fixture(root)
    return {
        "root": root,
        "evidence_path": evidence_path,
        "artifacts": artifacts,
        "repo": repo,
        "evidence": evidence,
        "registry": registry,
        "coordinator": coordinator,
        "author": author,
        "ci_query": root / "fake-gh",
    }


def _retained_manifest_from_fixture(
    verifier: Any,
    layout: dict[str, Any],
    source_root: Path,
) -> Path:
    """Split a valid verifier fixture into retained producer inputs.

    The producer receives references to independently retained sections and
    their transitive raw/JUnit/review/broker artifacts, never a caller-authored
    ``verification_evidence.v3`` aggregate.
    """

    shutil.copytree(layout["artifacts"], source_root)
    evidence = layout["evidence"]
    plan_authority = {
        "schema": "harden_plan_authority.v1",
        "evidence_id": evidence["evidence_id"],
        "repository": evidence["repository"],
        "git": {
            name: {"commit": record["commit"]}
            for name, record in evidence["git"].items()
        },
        "authority": evidence["authority"],
    }
    sections = {
        "plan_authority": plan_authority,
        "sl0_review": evidence["sl0"],
        "preproduction_verification": evidence["sl0"]["activated_red"],
        "candidate_verification": evidence["verification"]["candidate"],
        "canonical_main_verification": evidence["verification"]["canonical_main"],
        "candidate_ci": evidence["ci"]["candidate"],
        "canonical_main_ci": evidence["ci"]["canonical_main"],
        "candidate_review": evidence["reviews"]["candidate"],
        "canonical_main_review": evidence["reviews"]["canonical_main"],
    }
    artifacts = {
        name: _write_ref(
            source_root,
            f"producer-inputs/{name}.json",
            verifier.canonical_bytes(value),
        )
        for name, value in sections.items()
    }
    manifest = {
        "schema": INPUT_SCHEMA,
        "artifacts": artifacts,
        "role_attestations": copy.deepcopy(evidence["roles"]),
    }
    path = layout["root"] / "harden-evidence-inputs.json"
    path.write_bytes(_canonical_bytes(manifest))
    return path


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit_paths(repo: Path, message: str, paths: dict[str, str]) -> str:
    for name, contents in paths.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _junit_bytes(outcomes: tuple[str, ...]) -> bytes:
    counts = {name: outcomes.count(name) for name in ("passed", "failed", "skipped")}
    suite = ElementTree.Element(
        "testsuite",
        tests=str(len(outcomes)),
        failures=str(counts["failed"]),
        errors="0",
        skipped=str(counts["skipped"]),
    )
    for index, outcome in enumerate(outcomes):
        case = ElementTree.SubElement(
            suite,
            "testcase",
            classname="retained",
            name=f"case_{index}",
        )
        if outcome == "failed":
            ElementTree.SubElement(case, "failure", message="source-entered falsifier")
        elif outcome == "skipped":
            ElementTree.SubElement(case, "skipped", message="capability absent")
    return ElementTree.tostring(suite, encoding="utf-8", xml_declaration=True)


def _live_fact_fixture(
    root: Path,
    *,
    variant: str,
    author_vendor: str,
    red_outcomes: tuple[str, ...],
    final_outcomes: tuple[str, ...],
) -> tuple[Path, Path, Path, dict[str, Any]]:
    repo = root / "repo"
    evidence_root = root / "retained"
    repo.mkdir(parents=True)
    evidence_root.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "producer-test@example.invalid")
    _git(repo, "config", "user.name", "HARDEN producer test")
    base = _commit_paths(repo, "base", {"README.md": "base\n"})
    frozen_paths = (
        f"phase-loop-runtime/tests/test_{variant}_one.py",
        f"phase-loop-runtime/tests/test_{variant}_two.py",
    )
    reviewed = _commit_paths(
        repo,
        "tests-only",
        {path: f"def test_{index}(): pass\n" for index, path in enumerate(frozen_paths)},
    )
    production_paths = (
        f"phase-loop-runtime/src/phase_loop_runtime/{variant}_producer.py",
        f"sibling/{variant}.txt",
    )
    candidate = _commit_paths(
        repo,
        "production",
        {production_paths[0]: f"VALUE = {variant!r}\n"},
    )
    canonical_main = _commit_paths(
        repo,
        "independent sibling landing",
        {production_paths[1]: f"{variant}\n"},
    )
    commits = {
        "sl0_base": base,
        "reviewed_sl0": reviewed,
        "candidate": candidate,
        "canonical_main": canonical_main,
    }
    plan_authority = {
        "schema": "harden_plan_authority.v1",
        "commits": commits,
        "author_vendor": author_vendor,
    }
    sl0_review = {
        "schema": "harden_sl0_review.v1",
        "base_commit": base,
        "reviewed_commit": reviewed,
        "frozen_test_paths": list(frozen_paths),
    }
    routes = [
        {
            "harness": harness,
            "requested_model": f"{harness}-{variant}-requested",
            "resolved_model": f"{harness}-{variant}-resolved",
        }
        for harness in ("claude", "codex", "gemini", "grok")
    ]
    manifest = _input_manifest(evidence_root)
    manifest["artifacts"]["plan_authority"] = _write_ref(
        evidence_root,
        "facts/plan-authority.json",
        _canonical_bytes(plan_authority),
    )
    manifest["artifacts"]["sl0_review"] = _write_ref(
        evidence_root,
        "facts/sl0-review.json",
        _canonical_bytes(sl0_review),
    )
    manifest["artifacts"]["candidate_verification"] = _write_ref(
        evidence_root,
        "facts/candidate-junit.xml",
        _junit_bytes(final_outcomes),
    )
    manifest["artifacts"]["preproduction_verification"] = _write_ref(
        evidence_root,
        "facts/red-junit.xml",
        _junit_bytes(red_outcomes),
    )
    manifest["artifacts"]["candidate_review"] = _write_ref(
        evidence_root,
        "facts/routes.json",
        _canonical_bytes({"schema": "harden_routes.v1", "routes": routes}),
    )
    manifest_path = root / "inputs.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    expected = {
        "commits": commits,
        "trees": {
            name: _git(repo, "rev-parse", f"{commit}^{{tree}}")
            for name, commit in commits.items()
        },
        "changed_paths": {
            "reviewed_sl0": sorted(frozen_paths),
            "candidate": [production_paths[0]],
            "canonical_main": [production_paths[1]],
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
    }
    return manifest_path, evidence_root, repo, expected


def _completion_event(verifier: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    main = evidence["git"]["canonical_main"]
    return {
        "timestamp": "2026-09-04T00:00:00Z",
        "phase": "HARDEN",
        "action": "phase_execute",
        "status": "complete",
        "metadata": {
            "harden_completion": {
                "schema": "harden_completion.v1",
                "evidence_sha256": verifier.normalized_precompletion_digest(evidence),
                "canonical_commit": main["commit"],
                "canonical_tree": main["tree"],
                "visual_render_declared": False,
            }
        },
    }


def test_harden_producer_derives_live_facts_without_historical_literals() -> None:
    producer = _producer_module("derive")
    source_path = _repo_root() / PRODUCER_PATH
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=PRODUCER_PATH)

    forbidden_names = {
        "FINAL_RUN_SPECS",
        "FROZEN_SL0_PATHS",
        "PLAN_PRODUCTION_PATHS",
        "SELF_TEST_ROUTES",
        "_fixture",
        "self_test",
    }
    referenced_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not forbidden_names & referenced_names
    for historical_literal in (
        "16 failed, 439 passed, 3 skipped",
        "454 passed",
        "codex-gpt-5.6-terra",
    ):
        assert historical_literal not in source
    assert INPUT_SCHEMA in source
    for name in ("derive_live_facts", "prepare", "seal"):
        assert callable(getattr(producer, name, None)), name

    fact_sets = []
    with tempfile.TemporaryDirectory(prefix="harden-live-facts-") as td:
        root = Path(td)
        variants = (
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
        )
        for variant, author, red_outcomes, final_outcomes in variants:
            case_root = root / variant
            manifest, evidence_root, repo, expected = _live_fact_fixture(
                case_root,
                variant=variant,
                author_vendor=author,
                red_outcomes=red_outcomes,
                final_outcomes=final_outcomes,
            )
            facts = producer.derive_live_facts(
                manifest,
                evidence_root=evidence_root,
                repo=repo,
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
                    "commit": expected["commits"][name],
                    "tree": expected["trees"][name],
                }
                for name in expected["commits"]
            }
            for key in (
                "changed_paths",
                "frozen_test_paths",
                "run_counts",
                "author_vendor",
                "routes",
            ):
                assert facts[key] == expected[key]
            fact_sets.append(facts)
    assert (
        fact_sets[0]["git"]["canonical_main"]["tree"]
        != fact_sets[1]["git"]["canonical_main"]["tree"]
    )
    assert fact_sets[0]["changed_paths"] != fact_sets[1]["changed_paths"]
    assert fact_sets[0]["frozen_test_paths"] != fact_sets[1]["frozen_test_paths"]
    assert fact_sets[0]["run_counts"] != fact_sets[1]["run_counts"]
    assert fact_sets[0]["author_vendor"] != fact_sets[1]["author_vendor"]

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


def test_harden_producer_assembles_only_contained_retained_evidence() -> None:
    producer = _producer_module("assemble")

    with tempfile.TemporaryDirectory(prefix="harden-producer-contract-") as td:
        root = Path(td)

        def rejected(
            name: str,
            mutate,
            *,
            raw: bytes | None = None,
            prepare=None,
        ) -> None:
            with tempfile.TemporaryDirectory(
                prefix=name + "-", dir=root
            ) as case_dir:
                case_root = Path(case_dir)
                manifest = _input_manifest(case_root)
                if prepare is not None:
                    prepare(case_root, manifest)
                if raw is None:
                    mutate(case_root, manifest)
                    completed = _run_invalid_prepare(case_root, manifest)
                else:
                    completed = _run_invalid_prepare(case_root, raw)
                assert completed.stderr.strip() or completed.stdout.strip()

        rejected(
            "caller-derived-counts",
            lambda _root, value: value.__setitem__("counts", {"passed": 454}),
        )
        rejected(
            "caller-derived-git",
            lambda _root, value: value.__setitem__(
                "git", {"candidate_tree": "0" * 40}
            ),
        )
        rejected(
            "caller-derived-inventory",
            lambda _root, value: value.__setitem__("frozen_inventory", []),
        )
        rejected(
            "caller-derived-author",
            lambda _root, value: value.__setitem__(
                "author_vendor", "codex-gpt-5.6-terra"
            ),
        )
        rejected(
            "caller-derived-routes",
            lambda _root, value: value.__setitem__("resolved_routes", []),
        )
        rejected(
            "caller-authored-receipts",
            lambda _root, value: value.__setitem__(
                "receipts", {"candidate": {"passed": True}}
            ),
        )
        rejected(
            "absolute-path",
            lambda root, value: value["artifacts"]["plan_authority"].__setitem__(
                "path", str((root / "retained/placeholder.json").resolve())
            ),
        )
        rejected(
            "parent-traversal",
            lambda _root, value: value["artifacts"]["plan_authority"].__setitem__(
                "path", "retained/../placeholder.json"
            ),
        )
        rejected(
            "digest-mismatch",
            lambda _root, value: value["artifacts"]["plan_authority"].__setitem__(
                "sha256", "f" * 64
            ),
        )

        def replace_with_symlink(case_root: Path, value: dict[str, Any]) -> None:
            target = case_root / "outside.json"
            target.write_bytes(_canonical_bytes({"schema": "outside.v1"}))
            link = case_root / "retained/linked.json"
            link.symlink_to(target)
            value["artifacts"]["plan_authority"] = {
                "path": "retained/linked.json",
                "sha256": _sha256(target.read_bytes()),
            }

        rejected("symlink", replace_with_symlink)

        def replace_with_secret(case_root: Path, value: dict[str, Any]) -> None:
            payload = b'{"api_key":"synthetic-token-0123456789abcdef"}\n'
            value["artifacts"]["plan_authority"] = _write_ref(
                case_root, "retained/secret.json", payload
            )

        rejected("secret-bearing-artifact", replace_with_secret)
        rejected(
            "duplicate-json-key",
            lambda _root, _value: None,
            raw=(
                b'{"schema":"harden_evidence_inputs.v1",'
                b'"schema":"harden_evidence_inputs.v1",'
                b'"artifacts":{},"role_attestations":{}}\n'
            ),
        )

    verifier = _load_verifier()
    with tempfile.TemporaryDirectory(prefix="harden-producer-prepare-") as td:
        layout = _verifier_fixture(verifier, Path(td) / "valid")
        source_root = layout["root"] / "retained-source"
        manifest_path = _retained_manifest_from_fixture(
            verifier,
            layout,
            source_root,
        )
        prepared_root = layout["root"] / "prepared-evidence"
        output = layout["root"] / "verification-evidence.v3.json"
        request_path = layout["root"] / "completion-request.json"
        assert not prepared_root.exists()
        result = producer.prepare(
            manifest_path,
            source_root=source_root,
            evidence_root=prepared_root,
            repo=layout["repo"],
            output_path=output,
            completion_request_path=request_path,
            reuse_registry=layout["registry"],
            expected_coordinator_session=layout["coordinator"],
            expected_author_session=layout["author"],
            ci_query=layout["ci_query"],
        )
        assert (
            prepared_root.is_dir()
            and prepared_root.resolve() != source_root.resolve()
        )
        assert output.is_file() and request_path.is_file()
        evidence = verifier.parse_canonical_json(
            output.read_bytes(), "prepared verification evidence"
        )
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
        request_bytes = request_path.read_bytes()
        request = verifier.parse_canonical_json(
            request_bytes, "HARDEN completion request"
        )
        assert request_bytes == verifier.canonical_bytes(request)
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
        assert request["evidence_sha256"] == verifier.normalized_precompletion_digest(
            evidence
        )
        assert (
            request["canonical_commit"]
            == evidence["git"]["canonical_main"]["commit"]
        )
        assert request["canonical_tree"] == evidence["git"]["canonical_main"]["tree"]
        assert request["visual_render_declared"] is False
        assert request["input_manifest_sha256"] == _sha256(manifest_path.read_bytes())
        copies = request["copied_artifacts"]
        assert isinstance(copies, list) and copies
        assert all(set(item) == {"source", "retained"} for item in copies)
        assert all(
            item["source"]["sha256"] == item["retained"]["sha256"]
            for item in copies
        )
        source_inventory = {
            path.relative_to(source_root).as_posix(): _sha256(path.read_bytes())
            for path in source_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        copied_inventory = {
            item["source"]["path"]: item["source"]["sha256"] for item in copies
        }
        assert copied_inventory == source_inventory
        for item in copies:
            assert set(item["source"]) == {"path", "sha256"}
            assert set(item["retained"]) == {"path", "sha256"}
            source = source_root / item["source"]["path"]
            retained = prepared_root / item["retained"]["path"]
            assert source.is_file() and retained.is_file()
            assert source.read_bytes() == retained.read_bytes()
        assert not any(path.is_symlink() for path in prepared_root.rglob("*"))
        assert result == evidence or result is None
        verifier.verify(
            output,
            prepared_root,
            layout["repo"],
            reuse_registry=layout["registry"],
            expected_coordinator_session=layout["coordinator"],
            expected_author_session=layout["author"],
            ci_query=layout["ci_query"],
        )

        layout["registry"].write_bytes(
            verifier.canonical_bytes(
                {
                    "schema": "harden_evidence_registry.v1",
                    "evidence_ids": [evidence["evidence_id"]],
                    "operation_nonces": [],
                }
            )
        )
        reused_root = layout["root"] / "reused-evidence"
        reused_output = layout["root"] / "reused.json"
        reused_request = layout["root"] / "reused-request.json"
        with pytest.raises((ValueError, OSError, RuntimeError)):
            producer.prepare(
                manifest_path,
                source_root=source_root,
                evidence_root=reused_root,
                repo=layout["repo"],
                output_path=reused_output,
                completion_request_path=reused_request,
                reuse_registry=layout["registry"],
                expected_coordinator_session=layout["coordinator"],
                expected_author_session=layout["author"],
                ci_query=layout["ci_query"],
            )
        assert not reused_output.exists() and not reused_request.exists()


def test_harden_producer_prepare_then_seal_binds_one_canonical_event() -> None:
    producer = _producer_module("seal")
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
    verifier = _load_verifier()

    with tempfile.TemporaryDirectory(prefix="harden-producer-seal-") as td:
        layout = _verifier_fixture(verifier, Path(td) / "valid")
        evidence = layout["evidence"]
        before_digest = verifier.normalized_precompletion_digest(evidence)
        canonical_ledger = layout["repo"] / ".phase-loop/events.jsonl"
        canonical_ledger.parent.mkdir(parents=True, exist_ok=True)
        canonical_ledger.write_bytes(
            _canonical_bytes(_completion_event(verifier, evidence))
        )
        output = layout["root"] / "sealed-evidence.json"

        result = producer.seal(
            layout["evidence_path"],
            evidence_root=layout["artifacts"],
            repo=layout["repo"],
            ledger_path=canonical_ledger,
            output_path=output,
            reuse_registry=layout["registry"],
            expected_coordinator_session=layout["coordinator"],
            expected_author_session=layout["author"],
            ci_query=layout["ci_query"],
        )
        assert output.is_file()
        sealed = verifier.parse_canonical_json(
            output.read_bytes(), "sealed verification evidence"
        )
        assert sealed["completion"]["mode"] == "post_completion"
        assert verifier.normalized_precompletion_digest(sealed) == before_digest
        assert result == sealed or result is None
        verifier.verify(
            output,
            layout["artifacts"],
            layout["repo"],
            reuse_registry=layout["registry"],
            expected_coordinator_session=layout["coordinator"],
            expected_author_session=layout["author"],
            ci_query=layout["ci_query"],
        )

    def rejected(name: str, mutate) -> None:
        with tempfile.TemporaryDirectory(prefix=name + "-") as td:
            layout = _verifier_fixture(verifier, Path(td) / "invalid")
            evidence = layout["evidence"]
            ledger = layout["repo"] / ".phase-loop/events.jsonl"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            lines = [_completion_event(verifier, evidence)]
            mutate(layout, lines)
            ledger.write_bytes(b"".join(_canonical_bytes(line) for line in lines))
            output = layout["root"] / "must-not-exist.json"
            with pytest.raises((ValueError, OSError, RuntimeError)):
                producer.seal(
                    layout["evidence_path"],
                    evidence_root=layout["artifacts"],
                    repo=layout["repo"],
                    ledger_path=ledger,
                    output_path=output,
                    reuse_registry=layout["registry"],
                    expected_coordinator_session=layout["coordinator"],
                    expected_author_session=layout["author"],
                    ci_query=layout["ci_query"],
                )
            assert not output.exists()

    rejected("missing-completion-event", lambda _layout, lines: lines.clear())
    rejected("duplicate-completion-event", lambda _layout, lines: lines.append(copy.deepcopy(lines[0])))

    def stale_precompletion(layout: dict[str, Any], _lines: list[dict[str, Any]]) -> None:
        layout["evidence"]["evidence_id"] = "f" * 64
        layout["evidence_path"].write_bytes(_canonical_bytes(layout["evidence"]))

    rejected("stale-precompletion", stale_precompletion)

    def detached_ledger(layout: dict[str, Any], _lines: list[dict[str, Any]]) -> None:
        detached = layout["root"] / "detached-ledger.jsonl"
        detached.write_bytes(b"{}\n")
        canonical = layout["repo"] / ".phase-loop/events.jsonl"
        canonical.unlink(missing_ok=True)
        canonical.symlink_to(detached)

    rejected("symlink-ledger", detached_ledger)
