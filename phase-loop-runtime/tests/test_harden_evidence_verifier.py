"""SL-0 guard controls that remain GREEN in both default and activated modes."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pytest

from harden_tdd_guard import (
    HARDEN_CASES,
    HARDEN_MARKER_MODULE,
    HARDEN_RED_ANCHORS,
    HARDEN_TEST_PATHS,
    _replicate_test_repository,
    harden_require,
)


def test_the_frozen_inventory_is_BOUND_to_the_plan_and_to_collection():
    """The 26-path set is GOVERNED, not merely counted.

    Raised in cross-vendor review of agent-harness#726: the inventory check
    asserted only `len(...) == 26` and uniqueness, then validated the five
    anchors. The other 21 entries were unbound — **replacing any non-anchor path
    with another unique path stayed green**, so an "exact frozen set" was enforced
    only in cardinality. A frozen inventory nothing reads is decoration, which is
    the property IF-0-HARDEN-1 exists to provide.

    The same 26 paths are written down three times: this tuple, the plan's
    `**Owned files**` line, and the plan's gate block. That is the ah#693 shape —
    one fact in several places drifts silently — so this asserts the two
    authoritative statements are equal rather than re-listing them a fourth time.

    Three bindings, each independently killable:

    1. **plan parity** — set equality with `**Owned files**`;
    2. **existence** — every entry is a real file;
    3. **collection** — every test module contributes at least one collected node,
       so an entry cannot be frozen while contributing nothing.
    """

    root = Path(__file__).resolve().parents[2]
    plan = (root / "plans" / "phase-plan-v10-HARDEN.md").read_text(encoding="utf-8")

    # Each swim lane states its own `**Owned files**`; SL-0's is the frozen set.
    # Selected by walking to the SL-0 heading rather than taking the first match,
    # so a reordered plan cannot silently bind this to another lane's inventory.
    lane, owned_line = None, None
    for line in plan.splitlines():
        heading = re.match(r"^#+\s*(SL-\d\S*)", line.strip()) or re.match(
            r"^\*\*(SL-\d\S*)", line.strip()
        )
        if heading:
            lane = heading.group(1)
        if line.startswith("- **Owned files**") and lane == "SL-0":
            assert owned_line is None, "SL-0 states its owned files more than once"
            owned_line = line
    assert owned_line is not None, "the plan has no SL-0 **Owned files** line"
    declared = set(re.findall(r"`([^`]+\.py)`", owned_line))

    assert declared == set(HARDEN_TEST_PATHS), (
        "the guard's frozen inventory and the plan's **Owned files** disagree; "
        f"only in guard: {sorted(set(HARDEN_TEST_PATHS) - declared)}; "
        f"only in plan: {sorted(declared - set(HARDEN_TEST_PATHS))}"
    )
    assert len(HARDEN_TEST_PATHS) == len(set(HARDEN_TEST_PATHS)) == 26

    # The gate block enumerates the same set minus the guard helper itself.
    gate = set(re.findall(r"^\s+(phase-loop-runtime/tests/\S+\.py)", plan, re.M))
    assert gate <= set(HARDEN_TEST_PATHS), (
        f"the gate block names paths outside the inventory: "
        f"{sorted(gate - set(HARDEN_TEST_PATHS))}"
    )

    missing = [p for p in HARDEN_TEST_PATHS if not (root / p).is_file()]
    assert not missing, f"frozen inventory names paths that do not exist: {missing}"

    # Collection binding: a path can be present, unique, and still contribute
    # nothing. Assert each test module yields at least one node.
    modules = [p for p in HARDEN_TEST_PATHS if Path(p).name.startswith("test_")]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header", *modules],
        cwd=root,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": f"{root / 'phase-loop-runtime' / 'src'}:{root / 'phase-loop-runtime' / 'tests'}",
        },
    )
    # Node IDs are printed relative to pytest's rootdir (`phase-loop-runtime/`),
    # so match on the module BASENAME rather than the repo-relative path — the
    # first version compared against the repo-relative form and reported every
    # module as uncollected.
    collected = proc.stdout
    uncollected = {m for m in modules if f"{Path(m).name}::" not in collected}

    # `test_phase_loop_injection.py` skips at MODULE level in the extracted
    # agent-harness layout: it reads dotfiles fleet paths that do not exist here,
    # and the `dotfiles_integration` marker keeps it deselected in CI. It
    # therefore contributes zero nodes legitimately.
    #
    # Pinned as an exact set rather than relaxed to "zero is fine": that would
    # readmit the defect this test exists to close, since an entry contributing
    # nothing is precisely what "frozen but unbound" looks like. A NEW silent
    # skip has to be added here deliberately.
    module_skipped = {"phase-loop-runtime/tests/test_phase_loop_injection.py"}
    assert uncollected == module_skipped, (
        f"frozen inventory entries contribute no collected node: "
        f"{sorted(uncollected - module_skipped)}; expected-but-now-collecting: "
        f"{sorted(module_skipped - uncollected)}\n{proc.stdout[-1500:]}"
    )

    # The module-skipped entry must still CONTAIN tests, or it is frozen for
    # nothing — collection cannot speak for it, so the AST does.
    for path in sorted(module_skipped):
        tree = ast.parse((root / path).read_text(encoding="utf-8"), filename=path)
        defined = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        assert defined, f"{path} is frozen but defines no tests"


def test_harden_guard_inventory_and_case_bindings_are_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = Path(__file__).resolve().parents[2]
    assert len(HARDEN_TEST_PATHS) == 26
    assert len(set(HARDEN_TEST_PATHS)) == 26
    assert HARDEN_MARKER_MODULE == "phase_loop_runtime.capability_registry"
    assert set(HARDEN_RED_ANCHORS) == set(HARDEN_CASES)
    assert set(HARDEN_RED_ANCHORS.values()) == {
        "HARDEN-RED-ANCHOR::staged-tree-containment",
        "HARDEN-RED-ANCHOR::cwd-independent-reconcile",
        "HARDEN-RED-ANCHOR::non-vacuous-goal-coverage",
        "HARDEN-RED-ANCHOR::login-shell-interpreter",
        "HARDEN-RED-ANCHOR::review-leg-isolation",
    }
    for case_id, case in HARDEN_CASES.items():
        test_path, _, test_name = case.nodeid.partition("::")
        path = root / test_path
        assert path.is_file(), f"{case_id}: missing owned test path {test_path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == test_name]
        assert len(matches) == 1, f"{case_id}: missing or duplicate {test_name}"
        source = ast.unparse(matches[0])
        assert f"harden_require('{case_id}')" in source or f'harden_require("{case_id}")' in source

    projection_source = tmp_path / "projection-source"
    projection_source.mkdir()
    (projection_source / "payload.txt").write_text("projected", encoding="utf-8")
    (projection_source / ".git").mkdir()
    (projection_source / ".git" / "config").write_text(
        "must not copy Git authority", encoding="utf-8"
    )
    projection = tmp_path / "projection"
    projection.mkdir(mode=0o700)
    real_open = os.open
    git_authority_open_attempts: list[str] = []

    def refuse_git_authority_open(path, flags, *args, **kwargs):
        if isinstance(path, str) and path.casefold() == ".git":
            git_authority_open_attempts.append(path)
            raise AssertionError("repository projection opened Git authority")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse_git_authority_open)
    _replicate_test_repository(projection_source, projection)
    assert projection.stat().st_mode & 0o777 == 0o700
    assert not (projection / ".git").exists()
    assert (projection / "payload.txt").read_text(encoding="utf-8") == "projected"
    for entry in projection.rglob("*"):
        expected_mode = 0o700 if entry.is_dir() else 0o600
        assert entry.stat().st_mode & 0o777 == expected_mode

    caller_git_authority = tmp_path / "caller-git-authority"
    caller_git_authority.mkdir()
    caller_git_config = b"caller write authority must remain outside scratch"
    (caller_git_authority / "config").write_bytes(caller_git_config)
    forbidden_git_payloads = {caller_git_config}
    alias_projections: list[Path] = []
    for source_name, alias_name, alias_kind in (
        ("uppercase-git-directory", ".GIT", "directory"),
        ("mixed-case-gitfile", ".GiT", "gitfile"),
    ):
        alias_source = tmp_path / f"{source_name}-source"
        alias_source.mkdir()
        (alias_source / "payload.txt").write_text("projected", encoding="utf-8")
        alias = alias_source / alias_name
        if alias_kind == "directory":
            alias.mkdir()
            alias_payload = b"uppercase Git authority must not project"
            (alias / "config").write_bytes(alias_payload)
        else:
            alias_payload = f"gitdir: {caller_git_authority}\n".encode()
            alias.write_bytes(alias_payload)
        forbidden_git_payloads.add(alias_payload)
        alias_projection = tmp_path / f"{source_name}-projection"
        alias_projection.mkdir(mode=0o700)
        _replicate_test_repository(alias_source, alias_projection)
        alias_projections.append(alias_projection)
        assert alias_projection.stat().st_mode & 0o777 == 0o700
        assert (alias_projection / "payload.txt").is_file()
        assert all(
            entry.name.casefold() != ".git"
            for entry in alias_projection.iterdir()
        )
    projected_payloads = {
        entry.read_bytes()
        for alias_projection in alias_projections
        for entry in alias_projection.rglob("*")
        if entry.is_file()
    }
    assert projected_payloads.isdisjoint(forbidden_git_payloads)
    assert git_authority_open_attempts == []
    monkeypatch.setattr(os, "open", real_open)

    source_link = tmp_path / "projection-source-link"
    source_link.symlink_to(projection_source, target_is_directory=True)
    linked_projection = tmp_path / "linked-projection"
    linked_projection.mkdir(mode=0o700)
    with pytest.raises(AssertionError, match="source root is unsafe"):
        _replicate_test_repository(source_link, linked_projection)
    assert not tuple(linked_projection.iterdir())

    race_source = tmp_path / "race-source"
    race_source.mkdir()
    (race_source / "race.txt").write_text("safe-before-open", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("must not cross the source boundary", encoding="utf-8")
    race_projection = tmp_path / "race-projection"
    race_projection.mkdir(mode=0o700)
    swaps: list[str] = []

    def swap_before_open(path, flags, *args, **kwargs):
        if path == "race.txt" and not swaps:
            (race_source / "race.txt").unlink()
            (race_source / "race.txt").symlink_to(outside)
            swaps.append(path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)
    with pytest.raises(AssertionError, match="entry changed or is unsafe"):
        _replicate_test_repository(race_source, race_projection)
    monkeypatch.setattr(os, "open", real_open)
    assert swaps == ["race.txt"]
    assert race_projection.stat().st_mode & 0o777 == 0o700
    assert not (race_projection / "race.txt").exists()

    special_source = tmp_path / "special-source"
    special_source.mkdir()
    os.mkfifo(special_source / "capability.fifo")
    special_projection = tmp_path / "special-projection"
    special_projection.mkdir(mode=0o700)
    with pytest.raises(AssertionError, match="refuses special entry"):
        _replicate_test_repository(special_source, special_projection)
    assert special_projection.stat().st_mode & 0o777 == 0o700
    assert not (special_projection / "capability.fifo").exists()


def _load_harden_evidence_verifier() -> Any:
    """Load the standalone verifier without importing the runtime package."""
    path = (
        Path(__file__).resolve().parents[2]
        / "phase-loop-runtime/scripts/verify_harden_evidence.py"
    )
    assert path.is_file(), "HARDEN verifier script is missing"
    name = "harden_evidence_verifier_contract_subject"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verifier_fixture(verifier: Any, root: Path) -> dict[str, Any]:
    """Use the verifier's retained-artifact fixture as its public self-test does."""
    root.mkdir()
    fixture = getattr(verifier, "_fixture", None)
    assert callable(fixture), "verifier must retain an executable adversarial fixture"
    (
        evidence_path,
        artifacts,
        repo,
        _evidence,
        registry,
        coordinator,
        author,
    ) = fixture(root)
    return {
        "root": root,
        "evidence_path": evidence_path,
        "artifacts": artifacts,
        "repo": repo,
        "registry": registry,
        "coordinator": coordinator,
        "author": author,
        "evidence": verifier.parse_canonical_json(
            evidence_path.read_bytes(), "test verification evidence"
        ),
    }


def _verify_fixture(
    verifier: Any, layout: dict[str, Any], *, ci_query: Path | None = None
) -> None:
    verifier.verify(
        layout["evidence_path"],
        layout["artifacts"],
        layout["repo"],
        reuse_registry=layout["registry"],
        expected_coordinator_session=layout["coordinator"],
        expected_author_session=layout["author"],
        ci_query=ci_query or layout["root"] / "fake-gh",
    )


def _persist_evidence(verifier: Any, layout: dict[str, Any]) -> None:
    layout["evidence_path"].write_bytes(verifier.canonical_bytes(layout["evidence"]))


def _artifact_json(verifier: Any, layout: dict[str, Any], ref: dict[str, str]) -> dict[str, Any]:
    return verifier.parse_canonical_json(
        (layout["artifacts"] / ref["path"]).read_bytes(), "test retained artifact"
    )


def _replace_artifact_json(
    verifier: Any,
    layout: dict[str, Any],
    ref: dict[str, str],
    value: dict[str, Any],
) -> None:
    body = verifier.canonical_bytes(value)
    (layout["artifacts"] / ref["path"]).write_bytes(body)
    ref["sha256"] = verifier.sha256(body)


def _request(verifier: Any, layout: dict[str, Any], round_name: str) -> dict[str, Any]:
    ref = layout["evidence"]["reviews"][round_name]["request"]
    return _artifact_json(verifier, layout, ref)


def _replace_request(
    verifier: Any,
    layout: dict[str, Any],
    round_name: str,
    request: dict[str, Any],
) -> None:
    """Reseal a request and every seat's request digest for a real adversary."""
    review = layout["evidence"]["reviews"][round_name]
    request_ref = review["request"]
    _replace_artifact_json(verifier, layout, request_ref, request)
    for item in review["seats"]:
        seat_ref = item["artifact"]
        seat = _artifact_json(verifier, layout, seat_ref)
        seat["request_sha256"] = request_ref["sha256"]
        _replace_artifact_json(verifier, layout, seat_ref, seat)


def _replace_broker_stage_digest(
    verifier: Any,
    layout: dict[str, Any],
    round_name: str,
    field: str,
    digest: str,
) -> None:
    for item in layout["evidence"]["reviews"][round_name]["seats"]:
        seat_ref = item["artifact"]
        seat = _artifact_json(verifier, layout, seat_ref)
        seat["broker"][field] = digest
        _replace_artifact_json(verifier, layout, seat_ref, seat)


def _recording_ci_query(layout: dict[str, Any]) -> tuple[Path, Path]:
    """Return a metadata-only fake provider that records every queried run id."""
    responses = {
        str(record["run_id"]): {
            "databaseId": record["run_id"],
            "headSha": record["head"],
            "status": "completed",
            "conclusion": "success",
            "event": record["event"],
            "workflowName": record["workflow"],
            "attempt": record["run_attempt"],
        }
        for record in layout["evidence"]["ci"].values()
    }
    responses_path = layout["root"] / "ci-responses.json"
    trace_path = layout["root"] / "ci-query-trace.txt"
    responses_path.write_text(json.dumps(responses), encoding="utf-8")
    query = layout["root"] / "recording-gh"
    query.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"responses = json.loads(Path({str(responses_path)!r}).read_text())\n"
        f"trace = Path({str(trace_path)!r})\n"
        "run_id = sys.argv[3]\n"
        "trace.write_text(trace.read_text() + run_id + '\\n' if trace.exists() else run_id + '\\n')\n"
        "print(json.dumps(responses[run_id]))\n",
        encoding="utf-8",
    )
    query.chmod(0o700)
    return query, trace_path


class HardenEvidenceVerifierContractTests(unittest.TestCase):
    def test_harden_review_request_retains_recomputed_git_bound_inputs(self) -> None:
        """Review input must be retained evidence, not a self-reported digest."""
        harden_require("review-leg-isolation")
        verifier = _load_harden_evidence_verifier()

        with tempfile.TemporaryDirectory() as td:
            layout = _verifier_fixture(verifier, Path(td) / "valid")
            _verify_fixture(verifier, layout)
            for round_name in ("candidate", "canonical_main"):
                review = layout["evidence"]["reviews"][round_name]
                request = _request(verifier, layout, round_name)
                self.assertEqual(
                    set(request),
                    {
                        "schema",
                        "round",
                        "head",
                        "tree",
                        "bundle",
                        "instructions",
                        "request_nonce",
                        "seats",
                    },
                )
                self.assertEqual(request["round"], round_name)
                self.assertEqual(request["head"], review["head"])
                self.assertEqual(request["tree"], review["tree"])
                for kind, stage_field in (
                    ("bundle", "stage_bundle_sha256"),
                    ("instructions", "stage_instructions_sha256"),
                ):
                    input_ref = request[kind]
                    input_record = _artifact_json(verifier, layout, input_ref)
                    self.assertEqual(
                        set(input_record),
                        {"schema", "kind", "head", "tree", "content"},
                    )
                    self.assertEqual(input_record["schema"], "harden_review_input.v1")
                    self.assertEqual(input_record["kind"], kind)
                    self.assertEqual(input_record["head"], review["head"])
                    self.assertEqual(input_record["tree"], review["tree"])
                    self.assertIsInstance(input_record["content"], str)
                    self.assertTrue(input_record["content"])
                    digest = verifier.sha256(input_record["content"].encode("utf-8"))
                    for seat_item in review["seats"]:
                        seat = _artifact_json(verifier, layout, seat_item["artifact"])
                        self.assertEqual(seat["broker"][stage_field], digest)

        def rejected(mutate) -> None:
            for round_name in ("candidate", "canonical_main"):
                with self.subTest(round_name=round_name, mutation=mutate.__name__), \
                        tempfile.TemporaryDirectory() as td:
                    layout = _verifier_fixture(verifier, Path(td) / "mutated")
                    mutate(layout, round_name)
                    _persist_evidence(verifier, layout)
                    with self.assertRaises(verifier.EvidenceError):
                        _verify_fixture(verifier, layout)

        def self_asserted_digest(layout: dict[str, Any], round_name: str) -> None:
            request = _request(verifier, layout, round_name)
            request["input_sha256"] = "a" * 64
            request["instructions_sha256"] = "b" * 64
            _replace_request(verifier, layout, round_name, request)

        def resealed_input_content(
            layout: dict[str, Any],
            round_name: str,
            kind: str,
            stage_field: str,
        ) -> None:
            request = _request(verifier, layout, round_name)
            input_ref = request[kind]
            input_record = _artifact_json(verifier, layout, input_ref)
            input_record["content"] += "\nretained-input drift must not be accepted"
            _replace_artifact_json(verifier, layout, input_ref, input_record)
            _replace_broker_stage_digest(
                verifier,
                layout,
                round_name,
                stage_field,
                verifier.sha256(input_record["content"].encode("utf-8")),
            )
            _replace_request(verifier, layout, round_name, request)

        def detached_bundle_content(layout: dict[str, Any], round_name: str) -> None:
            resealed_input_content(
                layout, round_name, "bundle", "stage_bundle_sha256"
            )

        def detached_instruction_content(
            layout: dict[str, Any], round_name: str
        ) -> None:
            resealed_input_content(
                layout, round_name, "instructions", "stage_instructions_sha256"
            )

        rejected(self_asserted_digest)
        rejected(detached_bundle_content)
        rejected(detached_instruction_content)

    def test_harden_candidate_and_main_ci_are_separate_authoritative_records(self) -> None:
        """A final main CI run cannot stand in for the candidate CI gate."""
        harden_require("review-leg-isolation")
        verifier = _load_harden_evidence_verifier()

        with tempfile.TemporaryDirectory() as td:
            layout = _verifier_fixture(verifier, Path(td) / "valid")
            ci = layout["evidence"]["ci"]
            self.assertEqual(set(ci), {"candidate", "canonical_main"})
            self.assertEqual(
                ci["candidate"]["head"], layout["evidence"]["git"]["candidate"]["commit"]
            )
            self.assertEqual(
                ci["canonical_main"]["head"],
                layout["evidence"]["git"]["canonical_main"]["commit"],
            )
            self.assertNotEqual(ci["candidate"]["run_id"], ci["canonical_main"]["run_id"])
            query, trace = _recording_ci_query(layout)
            _verify_fixture(verifier, layout, ci_query=query)
            self.assertEqual(
                trace.read_text(encoding="utf-8").splitlines(),
                [str(ci["candidate"]["run_id"]), str(ci["canonical_main"]["run_id"])],
            )

        def rejected(mutate) -> None:
            with tempfile.TemporaryDirectory() as td:
                layout = _verifier_fixture(verifier, Path(td) / "mutated")
                mutate(layout)
                _persist_evidence(verifier, layout)
                with self.assertRaises(verifier.EvidenceError):
                    _verify_fixture(verifier, layout)

        rejected(
            lambda layout: layout["evidence"].__setitem__(
                "ci", copy.deepcopy(layout["evidence"]["ci"]["canonical_main"])
            )
        )

        def swapped_candidate(layout: dict[str, Any]) -> None:
            layout["evidence"]["ci"]["candidate"] = copy.deepcopy(
                layout["evidence"]["ci"]["canonical_main"]
            )

        rejected(swapped_candidate)

        def detached_candidate(layout: dict[str, Any]) -> None:
            layout["evidence"]["ci"]["candidate"]["head"] = layout["evidence"][
                "git"
            ]["canonical_main"]["commit"]

        rejected(detached_candidate)
