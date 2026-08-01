"""LEGIBLE-A0 — frozen test-first falsifier suite (SL-2 half).

See ``plans/phase-plan-v10-LEGIBLE.md`` for the ratified contract this file
implements. This module owns 20 of the phase's 84 frozen nodeids: 5
chronology cases, 4 PR/ancestry cases, 7 fresh-process/sidecar cases, and 4
activation/JUnit/digest cases. Its sibling ``test_legible_roadmap_contract.py``
owns the remaining 64 (status/banner/selection, assumption probes, manifest
scope, and docs-catalog).

Every nodeid here is guarded by the SAME shared, test-owned activation rule as
the sibling file (the module-level ``skipif`` below is the only skip
mechanism for these nodeids). Before LEGIBLE-C2 lands
``phase_loop_runtime.legible_evidence`` — the wholly new reducer/attestation
module this file's contract targets — does not exist at all, so every test
below reaches a real "source injection anchor" (a literal, presently-true
fact read from the committed ``plans/phase-plan-v10-LEGIBLE.md`` chronology
contract or real Git history) before the resulting ``ImportError`` is
converted into the one tagged, intentional ``LEGIBLE_RED::<mutation-id>``
failure it must reach. No test here relies on collection/import failure,
``xfail``, or a deselected node as a substitute for that tagged assertion.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared activation rule (identical, by contract, in test_legible_roadmap_contract.py)

LEGIBLE_TDD_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_LEGIBLE"
LEGIBLE_CAPABILITY_MODULE = "phase_loop_runtime.legible_evidence"
LEGIBLE_CAPABILITY_VERSION = "legible.v1"


def _legible_capability_active() -> bool:
    if os.environ.get(LEGIBLE_TDD_ACTIVATION_ENV) == "1":
        return True
    spec = importlib.util.find_spec(LEGIBLE_CAPABILITY_MODULE)
    if spec is None:
        return False
    module = importlib.import_module(LEGIBLE_CAPABILITY_MODULE)
    return getattr(module, "LEGIBLE_CAPABILITY_VERSION", None) == LEGIBLE_CAPABILITY_VERSION


pytestmark = pytest.mark.skipif(
    not _legible_capability_active(),
    reason="LEGIBLE capability absent (set PHASE_LOOP_TDD_EXPECT_LEGIBLE=1, or install "
    "phase_loop_runtime.legible_evidence with LEGIBLE_CAPABILITY_VERSION == 'legible.v1')",
)


@functools.lru_cache(maxsize=None)
def _shared_guard_reason() -> str:
    """The ONE test-owned skip reason above, read back from the live marker rather
    than retyped, so a JUnit fixture claiming "the only skip reason is the shared
    guard" really carries the string this module can actually emit."""
    reason = pytestmark.mark.kwargs["reason"]
    assert reason.startswith("LEGIBLE capability absent"), reason
    return reason


def _red(mutation_id: str, detail: str) -> None:
    pytest.fail(f"LEGIBLE_RED::{mutation_id}: {detail}", pytrace=False)


def _new_symbol(module_name: str, symbol: str):
    module = importlib.import_module(module_name)
    if not hasattr(module, symbol):
        raise AttributeError(f"{module_name}.{symbol} is not implemented yet")
    return getattr(module, symbol)


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "plans" / "phase-plan-v10-LEGIBLE.md"
TEST_PATHS = (
    "phase-loop-runtime/tests/test_legible_roadmap_contract.py",
    "phase-loop-runtime/tests/test_legible_evidence.py",
)

# Frozen, verbatim excerpt of every ratified ``plans/phase-plan-v10-LEGIBLE.md``
# passage this file's source injection anchors cite (captured at LEGIBLE-A0
# authoring time). A canonical repository checkout never touches this constant:
# ``PLAN_PATH`` is read lazily below and always wins when it is present on disk.
# It exists purely so an installed-wheel clean-room tree (e.g. Gate A's
# ``tests/``-only standalone copy, which ships no ``plans/`` directory at all)
# can still assert every anchor byte-for-byte against a real ratified quote
# instead of crashing at import time or silently skipping the check.
_FROZEN_PLAN_EXCERPT = """\
3. With the marker absent and no env override, run the tests-only targeted command and ordinary
   broad CI. The targeted JUnit must say `tests=84`, `skipped=84`, `failures=0`, `errors=0`;
   the broad suite must stay green and its only newly skipped nodeids must be those exact 84.

   set `PHASE_LOOP_TDD_EXPECT_LEGIBLE=1` against the unchanged pre-implementation production
   base. Raw RED output and JUnit must prove all 84 nodeids ran, every node failed its intended
   `LEGIBLE_RED::<mutation-id>` assertion after its source injection anchor assertion succeeded,

5. Land the tests-only change on the target/default branch through ordinary green merge gates.
   Record the canonical landing commit whose first-parent diff changes exactly the two test
   paths, and cut the implementation branch from a fetched target head containing that commit.
6. Implement without editing either test path or activation logic. Before the capability marker


The implementation range must contain no diff at either frozen test path. The implementation
base/head and final canonical main must descend from the landed test commit, both test blobs
must remain identical at the test landing, implementation base, candidate head, and canonical
main, and the plan/roadmap blobs must match their recorded exact digests at each ref. A
same-branch `base -> tests -> implementation` sequence, a candidate not first pushed, reuse of
the builder process, or evidence from an earlier candidate/main OID fails. No existing test is

  signature does not gain a sidecar parameter. Its current v2 writer behavior is frozen:

  integrity mismatch but may never yield a false pass. No public CLI or function caller can
  inject an extension through a new argument.

  before returning `ok`. Generic readers accept any registry-known namespace with its registered
  closed record schema, so adding PROOFGATE's reserved namespace downstream does not invalidate
  LEGIBLE-only artifacts or tests; plan-aware LEGIBLE validation never requires the PROOFGATE
  namespace.
- Unknown top-level schema versions, unregistered v3 extension namespaces, incompatible registered
  extension
  schema versions, missing required fields, and fields outside the version-relative inventories
  fail closed. The loader keeps its public call signature and raises a typed `ValueError`
  subclass carrying the stable contract code; `validate_verification_artifact` keeps its public
  signature and converts that failure to `VerificationArtifactValidation` with
  `unsupported_schema_version`, `unsupported_extension_namespace`, or
  `unsupported_extension_version` as appropriate. Structurally malformed known versions,
  including a v1 `operational_exemptions`, a v2 `extensions`, a v3 missing `extensions`, or any
  other per-version additional field, remain `malformed_artifact`. These new typed outcomes apply

| no or empty `operational_exemptions`; no sidecar | schema v2, exactly `B` |
| nonempty `operational_exemptions`; no sidecar | schema v2, exactly `B ∪ {operational_exemptions}`, with the list preserved and not executed |
| no or empty `operational_exemptions`; valid sidecar | schema v3, exactly `B ∪ {extensions}` |
| nonempty `operational_exemptions`; valid sidecar | schema v3, exactly `B ∪ {operational_exemptions, extensions}`, with the list preserved through bind/load/validate |

- `roadmap_status`: registry path/length/SHA-256, selected path, Git-tracked path-set digest, and
  one stable path-sorted record for every tracked roadmap containing the registry status, parsed
  banner status, exact primary-declaration line number, and declaration SHA-256. Collection and
  `verify --head HEAD` both call `validate_roadmap_status_coherence(required=True)`; mismatched
  status, changed path coverage, malformed/ambiguous/missing declaration, or digest drift fails.

| LEGIBLE-C1 | impl | LEGIBLE-C0 | `.claude/docs-catalog.json`, `phase-loop-runtime/src/phase_loop_runtime/docs_freshness.py` | none; tests remain owned and frozen by SL-0 | add deterministic `rescan-catalog` and `check-catalog` module commands, populate repo-owned document entries including the owned verification-evidence contract document, and make empty mean count zero; do not infer or catalog client-owned documents while `Consiliency/agent-harness#367` is unresolved |
| LEGIBLE-C2 | impl | LEGIBLE-C0 | `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | none; tests remain owned and frozen by SL-0 | update the public contract document and implement strict version-relative schema parsing, the closed registered-extension namespace interface, coherent roadmap-status collection/revalidation, TDD activation/JUnit and exact-digest chronology collection/validation, phase-authored versus exact target-integration delta partitioning, implementation-PR test-path range rejection, candidate/main bootstrap provenance, PR snapshot/finalization, artifact SHA-256 calculation, atomic evidence writes, and staged `python -m phase_loop_runtime.legible_evidence verify`; preserve the exact public `run_verification(repo, run_dir, commands, suite_command, env_refresh, timeout_s, operational_exemptions=None, python_pin=None, phase_alias=None) -> VerificationResult` signature, exact nine-field v2 output when exemptions are absent/empty, exact ten-field v2 output when they are nonempty, and the value/return behavior required by the existing preflight test; have a freshly started runner invoke/capture the fixed `reviewtruth_fable_transition` adapter and implementation panel rather than accepting executor-authored JSON; parse the plan sidecar declaration and use the internal post-run v3 binder below to require, resolve, hash, preserve all non-derived v2 values, and seal the sidecar through the LEGIBLE-owned namespace; re-resolve/re-hash on validation; reject unsupported top-level/extension versions, unregistered namespaces, same-process, stale-head, fields outside the selected version's allowed inventory, missing/path-escaping/oversized, digest-drift, registry/banner/scope-drift, self-reported/raw-probe, test-blob/nodeid/JUnit drift, same-branch chronology, phase-authored unowned/test/integration-path diffs, target-base/refreshed-head/body/refresh-parent/path/comment-only/blob/tree/result drift, zero/non-ancestor cited SHAs, and non-merged/mismatched results; install `LEGIBLE_CAPABILITY_VERSION = "legible.v1"` only after SL-0, SL-1, C1, and C2 are complete |
| LEGIBLE-C3 | operational | LEGIBLE-C1, LEGIBLE-C2 | committed phase-authored candidate `P` and its remote branch | frozen chronology, activation, scope, and fresh-process falsifiers | require the capability marker and every production surface to be present; run the broad candidate-compatible gate as subprocesses; commit all phase-owned production/manifest/catalog changes without either test path or the frozen `agent-harness#347` integration path; push `P`, require remote branch OID equals local `HEAD`, record builder run/process identity, and return `awaiting_phase_closeout` without treating same-process verification as evidence |

  RED (exit 1, 84 intended failures, zero skip/error, one successful asserted injection anchor
  and `LEGIBLE_RED::<mutation-id>` failure per nodeid), and final marker-active candidate/main
  (`84 passed`, zero failure/error/skip). It records marker absence/presence at each ref and
  rejects xfail/xpass, collection/import errors, deselection, missing/extra nodeids, or a skip

prior builder/candidate run identity. Before importing any phase-owned attestation helper, the
fresh CLI process resolves the clean repo/worktree and exact `HEAD`, requires the expected
40-hex commit, snapshots its runner start token, then imports only from that worktree's
`phase-loop-runtime/src`; it rejects installed-runtime, different-worktree, dirty-tree, remote

binding rather than trusting a reducer command's exit or any executor-authored availability
claim. It invokes the fixed Fable adapter with no caller-supplied executable fields, caps retained
response metadata at 64 KiB and the serialized probe record at 16 KiB, and writes only the typed
metadata above. Raw auth JSON, account/subscription identity, prompt/body text, provider
transcript, stdout/stderr, environment values, credentials, and provider payloads are never
retained. Missing, over-bound, unredacted, handwritten, copied, same-process, or injected probe
evidence fails. After all verification commands return and before it seals `verification.json`,
the freshly loaded `runner.py` parses the required sidecar declaration below, resolves the
`<run-id>` token to its own runner-owned run directory, rejects
absolute/escaping/symlinked paths, requires the sidecar to exist, and passes its repo-relative
path, byte length, schema, SHA-256, stage, expected head, bootstrap head, and process start token
to the internal post-run binder, never to the frozen public `run_verification` signature. The

`validate_verification_artifact` then reopens the sidecar, revalidates bootstrap/module blobs and
head/plan/manifest/JUnit ancestry, requires the recorded schema/length/path/digest/stage/head/token
to match, and fails on missing or drifted bytes. Prose, a handwritten record, builder-process
verification, an unbound green command result, the planning-time snapshot above, or a green

  frozen test blob identities in `legible_evidence.v1`; the fresh-process verification artifact
  binds that record by digest. The reducer blocks unless the tests-only landing was first present
  on the target/default branch before implementation/target base `B`, phase-authored `B..P`

and the singleton net `B0..H` path/comment-only/blob contract frozen above; parse only rows matching
`` | `<7-40 lowercase hex>` | `` from the PR body's commit table; run
`git merge-base --is-ancestor <sha> H` for every parsed SHA; require at least one
SHA, the exact six-row set frozen above, and all results zero. In private temporary indexes,

`changed(B, T_BH)` to be the singleton external path, and the exact refreshed result identity
above. Require the PR to be non-draft with required checks/reviews satisfied; merge with
merge-commit method; then require
`state == MERGED`, non-null `mergedAt`, and a
non-null server merge commit `M` from

The runner requires `parents(M) == [B, H]`, `M^{tree} == T_BH`, and `changed(B, M)` to be exactly
the frozen transition ending at `R`; it creates integration commit `I` with
`parents(I) == [P, M]`, a second private-index recomputed clean-merge tree, and blob `R` at the
external path, then proves the phase/external partition above. The runner writes only redacted
"""


@functools.lru_cache(maxsize=None)
def _plan_text() -> str:
    """Lazily resolve the plan text this module's anchors are checked against.

    Deferred to first *use* (never called at import/collection time) so the
    module can import even when ``PLAN_PATH`` does not exist -- only a test
    whose body actually runs (i.e. is not skipped) ever reads it."""
    try:
        return PLAN_PATH.read_text(encoding="utf-8")
    except OSError:
        return _FROZEN_PLAN_EXCERPT


def _assert_plan_contains(anchor: str) -> None:
    text = _plan_text()
    assert anchor in text, (
        f"source injection anchor missing from {PLAN_PATH} "
        f"(and from its frozen installed-wheel excerpt): {anchor!r}"
    )


def _canonical_repo_ready() -> bool:
    """True in a normal repository checkout (this file's own dev/CI tree, or any
    other clone carrying its full ``.git`` history and ``plans/`` directory);
    False in an installed-wheel clean-room copy like Gate A's ``tests/``-only
    standalone tree, which has neither."""
    return (REPO_ROOT / ".git").exists() and PLAN_PATH.is_file()


def _real_commit_exists(sha: str, repo: Path = REPO_ROOT) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", sha], capture_output=True, text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "commit"


# ---------------------------------------------------------------------------
# Shared clean-room Git fixture (chronology + PR/ancestry groups)
#
# In a canonical checkout every chronology/PR nodeid below reads this repo's own
# real history. An installed-wheel clean room has no ``.git`` at all, so those
# nodeids would otherwise degrade into assertions over hand-typed placeholder
# strings. ``_synthetic_legible_repo`` instead builds ONE real, throwaway Git
# repository per test (under the test's own ``tmp_path``) carrying the actual
# commit/parent/branch/blob shape each contract clause is about: a tests-only
# landing whose first-parent diff is exactly the two frozen test paths, a target
# base descending from it, a candidate branch with a six-commit body-table range,
# a real non-ancestor commit, a real same-branch base->tests->impl sequence, a
# real merge commit whose parents are ``[B, H]``, and real drifted test blobs.
# Every identifier handed to the contract from here is a real immutable Git OID
# resolved out of that repository. It touches no REPO_ROOT history, no canonical
# working-tree path, no network, and no live ``Consiliency/agent-harness#347``.
# The repo-relative *names* under ``TEST_PATHS`` are reused inside the synthetic
# tree because the contract clauses are stated in terms of those names; nothing
# is read from the real files at those locations.

_SYNTHETIC_PRODUCTION_PATH = "phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py"
_SYNTHETIC_EXTERNAL_PATH = "docs/agent-harness-347-integration.md"
_SYNTHETIC_REPO_SLUG = "legible-red-fixture/synthetic"
_SYNTHETIC_PR_NUMBER = 1


class _SyntheticLegibleRepo:
    """Real, immutable Git identities from a throwaway clean-room repository."""

    __slots__ = (
        "path", "base", "landing", "impl_base", "candidate", "refreshed_head",
        "merge", "mixed", "non_ancestor", "same_branch", "body_shas",
        "test_blob_at_landing", "test_blob_at_candidate", "repo_slug", "number",
    )

    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _synthetic_write(repo: Path, rel_path: str, text: str) -> None:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _synthetic_commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-gpg-sign", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _synthetic_legible_repo(tmp_path) -> _SyntheticLegibleRepo:
    repo = tmp_path / "legible-red-fixture"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "legible-red@example.com")
    _git(repo, "config", "user.name", "Legible Red")
    _git(repo, "config", "commit.gpgsign", "false")

    # B0 -- refresh base: both frozen test paths plus one production and one
    # external path already tracked.
    for index, path in enumerate(TEST_PATHS):
        _synthetic_write(repo, path, f"# frozen legible test path {index}\n")
    _synthetic_write(repo, _SYNTHETIC_PRODUCTION_PATH, "LEGIBLE_CAPABILITY_VERSION = None\n")
    _synthetic_write(repo, _SYNTHETIC_EXTERNAL_PATH, "external integration path\n")
    base = _synthetic_commit(repo, "B0: refresh base")

    # T -- the tests-only landing: first-parent diff is exactly TEST_PATHS.
    for index, path in enumerate(TEST_PATHS):
        _synthetic_write(repo, path, f"# frozen legible test path {index}\n# landed\n")
    landing = _synthetic_commit(repo, "T: tests-only landing")

    # B -- implementation/target base, descending from the landing.
    _synthetic_write(repo, _SYNTHETIC_PRODUCTION_PATH, "LEGIBLE_CAPABILITY_VERSION = None  # base\n")
    impl_base = _synthetic_commit(repo, "B: implementation base")

    # H/P -- candidate branch: six body-table commits, none touching a test path.
    _git(repo, "checkout", "-q", "-b", "candidate", impl_base)
    body_shas = []
    for step in range(6):
        _synthetic_write(
            repo, _SYNTHETIC_PRODUCTION_PATH, f"LEGIBLE_CAPABILITY_VERSION = None  # step {step}\n"
        )
        body_shas.append(_synthetic_commit(repo, f"P{step}: implementation step {step}"))
    candidate = body_shas[-1]

    # A refreshed head observed after the pre-merge snapshot was taken.
    _synthetic_write(repo, _SYNTHETIC_EXTERNAL_PATH, "external integration path\nrefreshed\n")
    refreshed_head = _synthetic_commit(repo, "H': head change after snapshot")

    # M -- server merge commit with parents [B, H].
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "--no-gpg-sign", "-m", "M: merge candidate", candidate)
    merge = _git(repo, "rev-parse", "HEAD")

    # A commit that is NOT tests-only (test path plus production path).
    _synthetic_write(repo, TEST_PATHS[0], "# frozen legible test path 0\n# landed\n# edited\n")
    _synthetic_write(repo, _SYNTHETIC_PRODUCTION_PATH, "LEGIBLE_CAPABILITY_VERSION = 'legible.v1'\n")
    mixed = _synthetic_commit(repo, "mixed: test path plus production path")

    # A real, parentless commit that is genuinely not an ancestor of the candidate.
    empty_tree = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-w", "-t", "tree", "--stdin"],
        input="", capture_output=True, text=True, check=True,
    ).stdout.strip()
    non_ancestor = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", empty_tree, "-m", "unrelated"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # A real same-branch base -> tests -> implementation sequence.
    _git(repo, "checkout", "-q", "-b", "feature/x", base)
    _synthetic_write(repo, _SYNTHETIC_PRODUCTION_PATH, "LEGIBLE_CAPABILITY_VERSION = None  # x base\n")
    _synthetic_commit(repo, "feature/x: base")
    _synthetic_write(repo, TEST_PATHS[1], "# frozen legible test path 1\n# same-branch\n")
    _synthetic_commit(repo, "feature/x: tests")
    _synthetic_write(repo, _SYNTHETIC_PRODUCTION_PATH, "LEGIBLE_CAPABILITY_VERSION = 'legible.v1'  # x\n")
    _synthetic_commit(repo, "feature/x: implementation")

    # A branch whose frozen test blob really drifted away from the landing blob.
    _git(repo, "checkout", "-q", "-b", "drifted", candidate)
    _synthetic_write(repo, TEST_PATHS[0], "# frozen legible test path 0\n# DRIFTED\n")
    _synthetic_commit(repo, "drifted: frozen test blob edited")
    test_blob_at_landing = _git(repo, "rev-parse", f"{landing}:{TEST_PATHS[0]}")
    test_blob_at_candidate = _git(repo, "rev-parse", f"drifted:{TEST_PATHS[0]}")
    _git(repo, "checkout", "-q", "main")

    fixture = _SyntheticLegibleRepo(
        path=repo,
        base=base,
        landing=landing,
        impl_base=impl_base,
        candidate=candidate,
        refreshed_head=refreshed_head,
        merge=merge,
        mixed=mixed,
        non_ancestor=non_ancestor,
        same_branch="feature/x",
        body_shas=tuple(body_shas),
        test_blob_at_landing=test_blob_at_landing,
        test_blob_at_candidate=test_blob_at_candidate,
        repo_slug=_SYNTHETIC_REPO_SLUG,
        number=_SYNTHETIC_PR_NUMBER,
    )
    # The fixture only counts as a source injection anchor if the shape it claims
    # is really there, so assert it before any contract call consumes it.
    assert len(fixture.body_shas) == 6
    assert all(_real_commit_exists(sha, repo=repo) for sha in fixture.body_shas)
    assert _real_commit_exists(fixture.non_ancestor, repo=repo)
    assert test_blob_at_landing != test_blob_at_candidate
    assert _git(repo, "rev-list", "--parents", "-n", "1", merge).split()[1:] == [impl_base, candidate]
    assert sorted(
        _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", landing).splitlines()
    ) == sorted(TEST_PATHS)
    return fixture


# ===========================================================================
# Group 1 — chronology (5 nodeids)
# ===========================================================================


def test_chronology_rejects_non_test_only_commit(tmp_path):
    _assert_plan_contains(
        "Record the canonical landing commit whose first-parent diff changes exactly the two test\n   paths"
    )
    if _canonical_repo_ready():
        for path in TEST_PATHS:
            assert (REPO_ROOT / path.split("phase-loop-runtime/")[-1]).exists() or (REPO_ROOT / path).exists()
        repo, landing_commit = REPO_ROOT, "HEAD"
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        for path in TEST_PATHS:
            assert _git(fixture.path, "cat-file", "-t", f"{fixture.mixed}:{path}") == "blob"
        # ``mixed`` really changes a test path AND a production path, so it is
        # really not the tests-only landing the contract demands.
        repo, landing_commit = fixture.path, fixture.mixed
    try:
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_chronology")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleChronologyError")
    except (ImportError, AttributeError) as exc:
        _red("chronology-rejects-non-test-only-commit", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, landing_commit=landing_commit, allowed_paths=TEST_PATHS)


def test_chronology_rejects_same_branch_sequence(tmp_path):
    _assert_plan_contains("A\nsame-branch `base -> tests -> implementation` sequence")
    if _canonical_repo_ready():
        repo, branch = REPO_ROOT, "feature/x"
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo, branch = fixture.path, fixture.same_branch
        # One real branch really carrying base -> tests -> implementation.
        assert len(_git(repo, "rev-list", f"{fixture.base}..{branch}").splitlines()) == 3
    try:
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_chronology")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleChronologyError")
    except (ImportError, AttributeError) as exc:
        _red("chronology-rejects-same-branch-sequence", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, base_branch=branch, tests_branch=branch, impl_branch=branch)


def test_chronology_requires_test_landing_on_target_before_implementation_base(tmp_path):
    _assert_plan_contains("the tests-only landing was first present")
    if _canonical_repo_ready():
        repo = REPO_ROOT
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo = fixture.path
        # Real ancestry witness for the rejected ordering: B0 precedes the
        # tests-only landing, so an implementation base at B0 really does not
        # contain it.
        assert subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", fixture.landing, fixture.base],
            capture_output=True,
        ).returncode != 0
    try:
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_chronology")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleChronologyError")
    except (ImportError, AttributeError) as exc:
        _red("chronology-requires-test-landing-before-impl-base", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, tests_landing_ancestor_of_base=False)


def test_chronology_rejects_test_path_diff_in_implementation_pr_range(tmp_path):
    _assert_plan_contains("The implementation range must contain no diff at either frozen test path")
    if _canonical_repo_ready():
        repo = REPO_ROOT
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo = fixture.path
        # The frozen test paths are really tracked across the implementation
        # range this call declares as having changed them.
        for path in TEST_PATHS:
            assert _git(repo, "cat-file", "-t", f"{fixture.candidate}:{path}") == "blob"
    try:
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_chronology")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleChronologyError")
    except (ImportError, AttributeError) as exc:
        _red("chronology-rejects-test-path-diff-in-impl-range", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, implementation_range_changed_paths=TEST_PATHS)


def test_chronology_rejects_changed_frozen_test_blob(tmp_path):
    _assert_plan_contains("both test blobs\nmust remain identical at the test landing")
    if _canonical_repo_ready():
        repo = REPO_ROOT
        blob_at_landing, blob_at_candidate = "0" * 40, "1" * 40
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo = fixture.path
        # Two real, distinct blob OIDs for the SAME frozen test path.
        blob_at_landing = fixture.test_blob_at_landing
        blob_at_candidate = fixture.test_blob_at_candidate
        assert len(blob_at_landing) == len(blob_at_candidate) == 40
    try:
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_chronology")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleChronologyError")
    except (ImportError, AttributeError) as exc:
        _red("chronology-rejects-changed-frozen-test-blob", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, test_blob_oid_at_landing=blob_at_landing, test_blob_oid_at_candidate=blob_at_candidate)


# ===========================================================================
# Group 2 — PR/ancestry (4 nodeids)
# ===========================================================================


def test_pr_evidence_rejects_non_ancestor_body_sha(tmp_path):
    _assert_plan_contains("run\n`git merge-base --is-ancestor <sha> H` for every parsed SHA")
    if _canonical_repo_ready():
        repo, repo_slug, number = REPO_ROOT, "Consiliency/agent-harness", 347
        body_shas = ("10f1e3d", "0a0438a", "1b3f091", "f22030e", "a493b95", "a89dd82")
        intruder = "dedbeef"
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo, repo_slug, number = fixture.path, fixture.repo_slug, fixture.number
        # Six real commits that ARE ancestors of the candidate head, plus one
        # real commit that genuinely is not.
        body_shas = fixture.body_shas
        intruder = fixture.non_ancestor
        for sha in body_shas:
            assert subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, fixture.candidate],
                capture_output=True,
            ).returncode == 0
        assert subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", intruder, fixture.candidate],
            capture_output=True,
        ).returncode != 0
    assert len(body_shas) == 6
    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_pr_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegiblePrEvidenceError")
    except (ImportError, AttributeError) as exc:
        _red("pr-evidence-rejects-non-ancestor-body-sha", str(exc))
        return
    with pytest.raises(error_cls):
        collect(repo, repo_slug=repo_slug, number=number, body_shas=tuple(body_shas) + (intruder,))


def test_pr_evidence_rejects_head_or_body_change_before_merge(tmp_path):
    _assert_plan_contains("Require the PR to be non-draft with required checks/reviews satisfied")
    if _canonical_repo_ready():
        repo, repo_slug, number = REPO_ROOT, "Consiliency/agent-harness", 347
        snapshot_head = "0f12c4614e859fd1082525be852fca4e52624890"
        observed_head = "1111111111111111111111111111111111111111"
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo, repo_slug, number = fixture.path, fixture.repo_slug, fixture.number
        # Two real, distinct heads: the snapshotted candidate and the commit
        # really pushed on top of it before the merge.
        snapshot_head, observed_head = fixture.candidate, fixture.refreshed_head
        assert snapshot_head != observed_head
        assert _git(repo, "rev-parse", f"{observed_head}^") == snapshot_head
    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_pr_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegiblePrEvidenceError")
    except (ImportError, AttributeError) as exc:
        _red("pr-evidence-rejects-head-or-body-change-before-merge", str(exc))
        return
    with pytest.raises(error_cls):
        collect(
            repo,
            repo_slug=repo_slug,
            number=number,
            snapshot_head=snapshot_head,
            observed_head=observed_head,
        )


def test_pr_evidence_requires_merged_result_for_snapshotted_head(tmp_path):
    _assert_plan_contains("require\n`state == MERGED`, non-null `mergedAt`")
    if _canonical_repo_ready():
        repo, repo_slug, number = REPO_ROOT, "Consiliency/agent-harness", 347
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo, repo_slug, number = fixture.path, fixture.repo_slug, fixture.number
        # The snapshotted head really exists and really is unmerged on the
        # target branch at the moment this OPEN/null-mergedAt result is offered.
        assert _real_commit_exists(fixture.candidate, repo=repo)
    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_pr_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegiblePrEvidenceError")
    except (ImportError, AttributeError) as exc:
        _red("pr-evidence-requires-merged-result-for-snapshotted-head", str(exc))
        return
    with pytest.raises(error_cls):
        collect(repo, repo_slug=repo_slug, number=number, state="OPEN", merged_at=None)


def test_pr_evidence_rejects_unbound_target_integration_delta(tmp_path):
    _assert_plan_contains("it creates integration commit `I` with\n`parents(I) == [P, M]`")
    if _canonical_repo_ready():
        repo, candidate, server_merge = REPO_ROOT, "P", "M"
    else:
        fixture = _synthetic_legible_repo(tmp_path)
        repo, candidate, server_merge = fixture.path, fixture.candidate, fixture.merge
        # A real server merge whose parents really are [B, H]; the integration
        # parents offered below drop `M` and so cannot bind that transition.
        assert _git(repo, "rev-list", "--parents", "-n", "1", server_merge).split()[1:] == [
            fixture.impl_base, candidate,
        ]
    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_target_integration_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegiblePrEvidenceError")
    except (ImportError, AttributeError) as exc:
        _red("pr-evidence-rejects-unbound-target-integration-delta", str(exc))
        return
    with pytest.raises(error_cls):
        collect(repo, candidate=candidate, server_merge=server_merge, integration_parents=(candidate,))


# ---------------------------------------------------------------------------
# Verification-evidence contract (IF-0-LEGIBLE-2) fixtures and frozen tables
#
# These nodes exercise the REAL public writer/loader/validator on REAL temporary
# artifacts. The helpers below only *build* fixtures: every parse, seal
# recomputation that the contract owns, and every verdict comes from production
# (`phase_loop_runtime.verification_evidence`), so a fixture can neither
# re-implement the contract nor drift from it.

_CONTRACT_DOC_RELPATH = "_contract_docs/runtime/verification-evidence-contract.md"

# Base ``B``: the exact nine top-level fields the committed contract document
# freezes for schema v1/v2, in its documented order.
_BASE_TOP_LEVEL_FIELDS = (
    "schema_version",
    "run_id",
    "phase_alias",
    "commands",
    "env_refresh",
    "suite",
    "started_at",
    "finished_at",
    "log_sha256",
)
_OPERATIONAL_EXEMPTIONS_FIELD = "operational_exemptions"
_EXTENSIONS_FIELD = "extensions"

# Per-stage inventories (required, plus the additive v2 optional set).
_COMMAND_STAGE_REQUIRED = ("argv", "cwd", "exit_code", "duration_s", "log_offset")
_ENV_REFRESH_STAGE_REQUIRED = ("triggered", "manifests", "install_argv", "exit_code")
_SUITE_STAGE_REQUIRED = ("argv", "exit_code", "duration_s")
_STAGE_V2_OPTIONAL = ("log_end_offset", "failure_kind")

# The closed v3 extension registry at the LEGIBLE landing.
_LEGIBLE_EXTENSION_NAMESPACE = "phase_loop_runtime.legible_evidence"
_PROOFGATE_EXTENSION_NAMESPACE = "phase_loop_runtime.proofgate_evidence"
_SIDECAR_RECORD_SCHEMA = "verification_evidence_sidecar.v1"
_SIDECAR_RECORD_FIELDS = (
    "schema",
    "path",
    "byte_length",
    "sha256",
    "stage",
    "expected_head",
    "bootstrap_head",
    "process_start_token",
)

_FROZEN_RUN_VERIFICATION_SIGNATURE = (
    "run_verification(repo, run_dir, commands, suite_command, env_refresh, timeout_s, "
    "operational_exemptions=None, python_pin=None, phase_alias=None) -> VerificationResult"
)
_FROZEN_RUN_VERIFICATION_PARAMETERS = (
    ("repo", inspect.Parameter.empty),
    ("run_dir", inspect.Parameter.empty),
    ("commands", inspect.Parameter.empty),
    ("suite_command", inspect.Parameter.empty),
    ("env_refresh", inspect.Parameter.empty),
    ("timeout_s", inspect.Parameter.empty),
    ("operational_exemptions", None),
    ("python_pin", None),
    ("phase_alias", None),
)

# A command that is recorded as operator evidence and must never be executed.
_UNEXECUTED_EXEMPTION_COMMAND = "definitely-not-executed-legible-operational-command"
_EXECUTED_MARKER = "legible-contract-executed-marker"


def _verification_evidence_module():
    return importlib.import_module("phase_loop_runtime.verification_evidence")


@functools.lru_cache(maxsize=None)
def _verification_contract_doc_path() -> Path:
    """The committed contract document, resolved through the INSTALLED package so
    an installed-wheel clean room reads the same bytes as a canonical checkout
    (the document ships inside ``phase_loop_runtime/_contract_docs/``)."""
    package = importlib.import_module("phase_loop_runtime")
    for entry in list(getattr(package, "__path__", [])):
        candidate = Path(entry) / _CONTRACT_DOC_RELPATH
        if candidate.is_file():
            return candidate
    fallback = REPO_ROOT / "phase-loop-runtime" / "src" / "phase_loop_runtime" / _CONTRACT_DOC_RELPATH
    assert fallback.is_file(), f"verification evidence contract document not found: {fallback}"
    return fallback


def _assert_contract_doc_contains(anchor: str) -> None:
    path = _verification_contract_doc_path()
    text = path.read_text(encoding="utf-8")
    assert anchor in text, f"contract document anchor missing from {path}: {anchor!r}"


def _evidence_repo(tmp_path) -> Path:
    repo = tmp_path / "evidence-repo"
    (repo / ".phase-loop" / "runs").mkdir(parents=True, exist_ok=True)
    return repo


def _write_verification(repo: Path, run_name: str, exemptions):
    """Run the REAL public writer with a real subprocess command."""
    module = _verification_evidence_module()
    run_dir = repo / ".phase-loop" / "runs" / run_name
    result = module.run_verification(
        repo,
        run_dir,
        [[sys.executable, "-c", f"print({_EXECUTED_MARKER!r})"]],
        None,
        None,
        120,
        operational_exemptions=exemptions,
    )
    return result, run_dir


def _artifact_payload(run_dir: Path) -> dict:
    return json.loads((run_dir / "verification.json").read_text(encoding="utf-8"))


def _clone_run_dir(run_dir: Path, dest: Path) -> Path:
    shutil.copytree(run_dir, dest)
    return dest


def _seal_run_dir(run_dir: Path, payload: dict) -> dict:
    """Rewrite the artifact/log pair so it is COHERENTLY SEALED.

    Fixture plumbing only: the canonical payload digest, the trailer prefix, and
    the trailer region boundary all come from the production module, so this can
    never diverge from (or restate) the real seal rule."""
    module = _verification_evidence_module()
    log_path = run_dir / module.LOG_NAME
    raw = log_path.read_bytes()
    start = module._artifact_seal_region_start(raw)
    body = raw if start is None else raw[:start]
    seal = module._canonical_artifact_digest(payload)
    log_bytes = body + f"\n{module._ARTIFACT_SEAL_PREFIX}{seal}\n".encode("utf-8")
    log_path.write_bytes(log_bytes)
    payload = dict(payload)
    payload["log_sha256"] = hashlib.sha256(log_bytes).hexdigest()
    (run_dir / module.ARTIFACT_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def _unseal_run_dir(run_dir: Path, payload: dict) -> dict:
    """Drop the seal trailer, producing the legacy UNSEALED artifact/log pair."""
    module = _verification_evidence_module()
    log_path = run_dir / module.LOG_NAME
    raw = log_path.read_bytes()
    start = module._artifact_seal_region_start(raw)
    log_bytes = raw if start is None else raw[:start]
    log_path.write_bytes(log_bytes)
    payload = dict(payload)
    payload["log_sha256"] = hashlib.sha256(log_bytes).hexdigest()
    (run_dir / module.ARTIFACT_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def _downgrade_payload_to_v1(payload: dict) -> dict:
    """A legacy v1 payload: schema_version 1 and no additive v2 stage fields."""
    payload = json.loads(json.dumps(payload))
    payload["schema_version"] = 1
    for stage in list(payload["commands"]) + [payload.get("env_refresh"), payload.get("suite")]:
        if isinstance(stage, dict):
            for field in _STAGE_V2_OPTIONAL:
                stage.pop(field, None)
    payload.pop(_OPERATIONAL_EXEMPTIONS_FIELD, None)
    return payload


def _independent_payload_digest(payload) -> str:
    """Oracle for the contract's documented canonical digest ("all fields except
    the derived ``log_sha256``", sorted keys, tight separators) computed here from
    the document's own words rather than by calling the production sealer."""
    material = {key: value for key, value in payload.items() if key != "log_sha256"}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _log_trailer_digest(log_bytes: bytes) -> str | None:
    prefix = "verification-artifact-sha256:"
    for line in reversed(log_bytes.decode("utf-8", "replace").splitlines()):
        if line.strip():
            return line[len(prefix):] if line.startswith(prefix) else None
    return None


def _sidecar_record(sidecar_rel_path: str, sidecar_bytes: bytes) -> dict:
    return {
        "schema": _SIDECAR_RECORD_SCHEMA,
        "path": sidecar_rel_path,
        "byte_length": len(sidecar_bytes),
        "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
        "stage": "candidate",
        "expected_head": "b" * 40,
        "bootstrap_head": "b" * 40,
        "process_start_token": "legible-fresh-process-token",
    }


def _write_sidecar(repo: Path, run_name: str) -> tuple[str, bytes]:
    rel_path = f".phase-loop/runs/{run_name}/legible-verification-sidecar.json"
    payload = json.dumps(
        {"schema": _SIDECAR_RECORD_SCHEMA, "probe": "LEGIBLE-A3-REVIEWTRUTH-TRANSITION"},
        sort_keys=True,
    ).encode("utf-8")
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return rel_path, payload


# ---------------------------------------------------------------------------
# Real run-directory sidecar fixtures (Group 3 binder/validator nodes)
#
# The binder/validator clauses are stated about a REAL runner-owned run
# directory inside a REAL repository: a repo-relative path under
# ``.phase-loop/runs/<run-id>/``, real sidecar bytes, and a real 40-hex ``HEAD``
# the fresh process resolved. ``_build_sidecar_run`` builds exactly that -- a
# throwaway Git repository with one real commit, a real run directory, a real
# bounded Fable probe output file, and real sidecar bytes -- so every value the
# contract is handed below is measured from bytes on disk rather than typed in.

_SIDECAR_PROBE_RECORD_MAX_BYTES = 16 * 1024
_SIDECAR_STAGE = "candidate"
_SIDECAR_PROCESS_START_TOKEN = "legible-fresh-process-token-0f3a9c7d21b64e58"
_SIDECAR_FILE_NAME = "legible-verification-sidecar.json"
_FABLE_PROBE_FILE_NAME = "legible-fable-probe.json"


class _SidecarRun:
    """A real repo/run/sidecar triple; every field is measured, not asserted into
    existence."""

    __slots__ = (
        "repo", "head", "run_id", "run_dir", "rel_path", "sidecar_bytes",
        "probe_bytes", "record", "token",
    )

    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)

    @property
    def sidecar_path(self) -> Path:
        return self.repo / self.rel_path


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "legible-red@example.com")
    _git(repo, "config", "user.name", "Legible Red")
    _git(repo, "config", "commit.gpgsign", "false")


def _fable_probe_bytes(run_id: str, *, filler: int = 0) -> bytes:
    """A realistic, already-bounded and already-redacted probe observation of the
    shape the runner's fixed Fable adapter capture produces (typed metadata only:
    no prompt/transcript/stdout/stderr/credential/account material)."""
    record = {
        "schema": "roadmap_assumption_probe.v1",
        "probe_id": "LEGIBLE-A3-REVIEWTRUTH-TRANSITION",
        "repository": "Consiliency/agent-harness",
        "issue": 396,
        "state": "pending",
        "model": "claude-fable-5",
        "route": "first-party-claude",
        "response_sha256": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
        "response_byte_length": 4096,
        "elapsed_ms": 41213,
        "activity_bound_s": 600,
        "hard_bound_s": 1800,
        "run_id": run_id,
    }
    if filler:
        record["retained_response_metadata"] = "m" * filler
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _build_sidecar_run(tmp_path, name: str, *, filler: int = 0) -> _SidecarRun:
    repo = tmp_path / f"sidecar-{name}"
    _init_git_repo(repo)
    _synthetic_write(repo, "README.md", f"legible sidecar fixture {name}\n")
    _synthetic_write(repo, _SYNTHETIC_PRODUCTION_PATH, "LEGIBLE_CAPABILITY_VERSION = None\n")
    head = _synthetic_commit(repo, f"fixture: sidecar run {name}")

    run_id = f"20260801T000000Z-{name}"
    run_dir = repo / ".phase-loop" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    probe_bytes = _fable_probe_bytes(run_id, filler=filler)
    (run_dir / _FABLE_PROBE_FILE_NAME).write_bytes(probe_bytes)

    rel_path = f".phase-loop/runs/{run_id}/{_SIDECAR_FILE_NAME}"
    sidecar_bytes = json.dumps(
        {
            "schema": _SIDECAR_RECORD_SCHEMA,
            "run_id": run_id,
            "stage": _SIDECAR_STAGE,
            "expected_head": head,
            "bootstrap_head": head,
            "process_start_token": _SIDECAR_PROCESS_START_TOKEN,
            "probe": json.loads(probe_bytes.decode("utf-8")),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    (repo / rel_path).write_bytes(sidecar_bytes)

    record = {
        "schema": _SIDECAR_RECORD_SCHEMA,
        "path": rel_path,
        "byte_length": len(sidecar_bytes),
        "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
        "stage": _SIDECAR_STAGE,
        "expected_head": head,
        "bootstrap_head": head,
        "process_start_token": _SIDECAR_PROCESS_START_TOKEN,
    }

    # Presently-true facts about the fixture, asserted before any contract call:
    # a real nonzero 40-hex HEAD, real nonempty bytes at a real repo-relative
    # path inside the runner-owned run directory, and a record whose length and
    # digest were measured from those exact bytes.
    assert len(head) == 40 and re.fullmatch(r"[0-9a-f]{40}", head), head
    assert int(head, 16) != 0
    assert _real_commit_exists(head, repo=repo)
    assert (repo / rel_path).is_file()
    assert (repo / rel_path).read_bytes() == sidecar_bytes and sidecar_bytes
    assert (run_dir / _FABLE_PROBE_FILE_NAME).read_bytes() == probe_bytes
    assert len(probe_bytes) <= _SIDECAR_PROBE_RECORD_MAX_BYTES or filler
    assert set(record) == set(_SIDECAR_RECORD_FIELDS)
    return _SidecarRun(
        repo=repo,
        head=head,
        run_id=run_id,
        run_dir=run_dir,
        rel_path=rel_path,
        sidecar_bytes=sidecar_bytes,
        probe_bytes=probe_bytes,
        record=record,
        token=_SIDECAR_PROCESS_START_TOKEN,
    )


# ===========================================================================
# Group 3 — fresh-process/sidecar (7 nodeids)
# ===========================================================================

# The single fixed adapter boundary the probe entry point owns. It is the one
# seam a clean-room run may replace: callers still cannot supply a command,
# route, environment, timeout, or expected result through the public signature.
_FABLE_ADAPTER_BOUNDARY = "_invoke_reviewtruth_fable_adapter"

# Values that a real provider observation plausibly carries and that the record
# must never retain, in any form.
_FORBIDDEN_FABLE_VALUES = (
    "sk-ant-api03-legible-red-fixture-token",
    "jennertorrence@example.invalid",
    "Enterprise/Max subscription seat 42",
    "You are Claude Fable 5. Review the following diff",
    "=== fable pty transcript ===",
    "Traceback (most recent call last): fable adapter",
)

# A realistic, deliberately over-bound raw adapter observation.
_RAW_FABLE_OBSERVATION = {
    "issue": {"number": 396, "state": "OPEN", "stateReason": None},
    "route": {"provider": "first-party-claude", "model": "claude-fable-5", "capability": "ok"},
    "leg": {"status": "UNAVAILABLE", "final_verdict_token": "tui_adapter_required", "elapsed_ms": 41213},
    "bounds": {"activity_s": 600, "hard_s": 1800},
    "auth": {"raw_json": {"access_token": "sk-ant-api03-legible-red-fixture-token"}},
    "account": {"email": "jennertorrence@example.invalid", "subscription": "Enterprise/Max subscription seat 42"},
    "prompt": "You are Claude Fable 5. Review the following diff" + (" body" * 4096),
    "transcript": "=== fable pty transcript ===" + ("\nassistant: ..." * 4096),
    "stdout": "fable adapter stdout " * 4096,
    "stderr": "Traceback (most recent call last): fable adapter",
    "environment": {"ANTHROPIC_API_KEY": "sk-ant-api03-legible-red-fixture-token"},
    "response": {"body": "native-fill request absent; seat remains UNAVAILABLE " * 4096},
}


def test_verification_sidecar_runner_captures_bounded_redacted_fable_probe_evidence(tmp_path, monkeypatch):
    _assert_plan_contains("caps retained\nresponse metadata at 64 KiB")
    _assert_plan_contains(
        "metadata above. Raw auth JSON, account/subscription identity, prompt/body text, provider"
    )
    canonical = _canonical_repo_ready()
    repo = REPO_ROOT if canonical else _synthetic_legible_repo(tmp_path).path
    try:
        module = importlib.import_module("phase_loop_runtime.legible_evidence")
        probe = _new_symbol("phase_loop_runtime.legible_evidence", "run_reviewtruth_fable_probe")
        if not canonical:
            _new_symbol("phase_loop_runtime.legible_evidence", _FABLE_ADAPTER_BOUNDARY)
    except (ImportError, AttributeError) as exc:
        _red("verification-sidecar-bounded-redacted-fable-probe", str(exc))
        return
    if not canonical:
        # Installed-wheel clean room: no GitHub, no live Fable leg, no network.
        # ONE fixed, test-local monkeypatch at the module's own adapter boundary
        # feeds the public entry point a realistic RAW provider observation --
        # oversized and carrying every category of forbidden data -- so the same
        # public signature still exercises the real bounding/redaction route.
        monkeypatch.setattr(
            module, _FABLE_ADAPTER_BOUNDARY, lambda *args, **kwargs: _RAW_FABLE_OBSERVATION, raising=True,
        )
    record = probe(repo, repository="Consiliency/agent-harness", issue=396, model="claude-fable-5")
    # Bounds.
    assert len(record.serialized_bytes) <= 16 * 1024
    assert record.response_byte_length <= 64 * 1024
    # Typed schema fields (and only typed values).
    assert record.schema == "roadmap_assumption_probe.v1"
    assert record.probe_id == "LEGIBLE-A3-REVIEWTRUTH-TRANSITION"
    assert record.state in ("pending", "resolved")
    assert record.model == "claude-fable-5"
    assert record.route
    assert len(record.response_sha256) == 64
    assert isinstance(record.elapsed_ms, int) and record.elapsed_ms >= 0
    assert (record.activity_bound_s, record.hard_bound_s) == (600, 1800)
    # Redaction.
    serialized = record.to_json()
    for forbidden in ("prompt", "transcript", "stdout", "stderr", "credential"):
        assert forbidden not in serialized
    if not canonical:
        for secret in _FORBIDDEN_FABLE_VALUES:
            assert secret not in serialized


def test_verification_sidecar_runner_rejects_self_reported_fable_probe_evidence(tmp_path):
    _assert_plan_contains("self-reported/raw-probe")
    _assert_plan_contains(
        "Missing, over-bound, unredacted, handwritten, copied, same-process, or injected probe\nevidence fails."
    )
    # The SAME real repo/run/sidecar setup the stamping node binds successfully,
    # so the only defect this node introduces is the handwritten, executor-authored
    # probe evidence: the run directory, the sidecar bytes, the digest, and the
    # real HEAD are all present and valid, and a rejection therefore cannot be a
    # missing-run-path artifact.
    run = _build_sidecar_run(tmp_path, "self-reported")
    handwritten = {
        "schema": "roadmap_assumption_probe.v1",
        "probe_id": "LEGIBLE-A3-REVIEWTRUTH-TRANSITION",
        "state": "resolved",
        "source": "self_reported",
        "authored_by": "executor",
        "note": "transcribed by hand from the executor's own summary; no adapter invocation",
    }
    assert run.run_dir.is_dir()
    assert run.sidecar_path.is_file()
    assert hashlib.sha256(run.sidecar_bytes).hexdigest() == run.record["sha256"]
    assert handwritten["source"] == "self_reported" and "adapter" not in handwritten["schema"]
    try:
        bind = _new_symbol("phase_loop_runtime.legible_evidence", "bind_verification_sidecar")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleSidecarError")
    except (ImportError, AttributeError) as exc:
        _red("verification-sidecar-rejects-self-reported-fable-probe", str(exc))
        return
    with pytest.raises(error_cls) as excinfo:
        bind(
            run.repo,
            run_dir=run.run_dir,
            stage=_SIDECAR_STAGE,
            expected_head=run.head,
            bootstrap_head=run.head,
            process_start_token=run.token,
            probe_evidence=handwritten,
        )
    # Typed for THIS reason, not for a missing/unreadable run path.
    assert excinfo.value.code == "self_reported_probe_evidence", excinfo.value.code


def test_runner_stamps_legible_sidecar_path_and_digest(tmp_path):
    _assert_plan_contains(
        "passes its repo-relative\npath, byte length, schema, SHA-256, stage, expected head, bootstrap "
        "head, and process start token"
    )
    run = _build_sidecar_run(tmp_path, "stamp")
    # Source injection anchor: real bytes at a real repo-relative path in a real
    # repository at a real nonzero HEAD, all measured before the binder is called.
    assert run.sidecar_path.is_file() and len(run.sidecar_bytes) > 0
    assert len(run.sidecar_bytes) <= _SIDECAR_PROBE_RECORD_MAX_BYTES
    assert run.rel_path == f".phase-loop/runs/{run.run_id}/{_SIDECAR_FILE_NAME}"
    assert (run.repo / run.rel_path).resolve().is_relative_to(run.repo.resolve())
    assert int(run.head, 16) != 0 and len(run.head) == 40
    try:
        bind = _new_symbol("phase_loop_runtime.legible_evidence", "bind_verification_sidecar")
    except (ImportError, AttributeError) as exc:
        _red("runner-stamps-legible-sidecar-path-and-digest", str(exc))
        return
    result = bind(
        run.repo,
        run_dir=run.run_dir,
        stage=_SIDECAR_STAGE,
        expected_head=run.head,
        bootstrap_head=run.head,
        process_start_token=run.token,
    )
    # Every one of the eight stamped values, exactly, against the measured bytes.
    assert result.schema == _SIDECAR_RECORD_SCHEMA
    assert result.path == run.rel_path
    assert result.byte_length == len(run.sidecar_bytes)
    assert result.sha256 == hashlib.sha256(run.sidecar_bytes).hexdigest()
    assert result.stage == _SIDECAR_STAGE
    assert result.expected_head == run.head
    assert result.bootstrap_head == run.head
    assert result.process_start_token == run.token
    # ...and nothing else: the stamped record is exactly the frozen inventory.
    assert {field: getattr(result, field) for field in _SIDECAR_RECORD_FIELDS} == run.record


def test_sidecar_validation_rejects_missing_drift_path_escape_or_oversize(tmp_path):
    # ONE node, four independent real fixtures (CHAIR-6 inventory reallocation:
    # the four former parameter ids are now an internal table so three Group-3
    # nodeids can carry the frozen IF-0-LEGIBLE-2 contract cases). Each fixture is
    # its OWN repository/run directory carrying exactly one defect; every
    # unrelated field (schema, stage, heads, token, and the metadata the case does
    # not attack) stays valid, so a rejection can only be the intended one.
    anchors = {
        "missing": "requires the sidecar to exist",
        "digest_drift": "requires the recorded schema/length/path/digest/stage/head/token\nto match",
        "path_escape": "rejects\nabsolute/escaping/symlinked paths",
        "oversize": "caps retained\nresponse metadata at 64 KiB and the serialized probe record at 16 KiB",
    }
    for anchor in anchors.values():
        _assert_plan_contains(anchor)

    cases: list[tuple[str, _SidecarRun, dict, str]] = []

    # 1. Missing: the recorded path really no longer exists; digest/length/heads
    #    describe the bytes that were really there when the record was stamped.
    missing_run = _build_sidecar_run(tmp_path, "validate-missing")
    missing_run.sidecar_path.unlink()
    assert not missing_run.sidecar_path.exists()
    assert missing_run.run_dir.is_dir()
    cases.append(("missing", missing_run, dict(missing_run.record), "sidecar_missing"))

    # 2. Digest drift: same path, same byte length, really different bytes.
    drift_run = _build_sidecar_run(tmp_path, "validate-digest-drift")
    drifted_bytes = drift_run.sidecar_bytes.replace(b'"pending"', b'"resolve"', 1)
    assert len(drifted_bytes) == len(drift_run.sidecar_bytes)
    assert drifted_bytes != drift_run.sidecar_bytes
    drift_run.sidecar_path.write_bytes(drifted_bytes)
    assert drift_run.sidecar_path.read_bytes() == drifted_bytes
    assert hashlib.sha256(drifted_bytes).hexdigest() != drift_run.record["sha256"]
    assert drift_run.record["byte_length"] == len(drifted_bytes)
    cases.append(("digest_drift", drift_run, dict(drift_run.record), "sidecar_digest_drift"))

    # 3. Path escape: a real symlink inside the run directory whose real target is
    #    outside the repository, carrying byte-identical content so length and
    #    digest both still match and only the path is illegitimate.
    escape_run = _build_sidecar_run(tmp_path, "validate-path-escape")
    outside = tmp_path / "outside-the-repo-legible-sidecar.json"
    outside.write_bytes(escape_run.sidecar_bytes)
    escape_rel = f".phase-loop/runs/{escape_run.run_id}/{_SIDECAR_FILE_NAME}.link"
    (escape_run.repo / escape_rel).symlink_to(outside)
    assert (escape_run.repo / escape_rel).is_symlink()
    assert not (escape_run.repo / escape_rel).resolve().is_relative_to(escape_run.repo.resolve())
    assert (escape_run.repo / escape_rel).read_bytes() == escape_run.sidecar_bytes
    escape_record = dict(escape_run.record, path=escape_rel)
    assert escape_record["sha256"] == hashlib.sha256(
        (escape_run.repo / escape_rel).read_bytes()
    ).hexdigest()
    cases.append(("path_escape", escape_run, escape_record, "sidecar_path_escape"))

    # 4. Oversize: a real serialized probe record past the frozen 16 KiB cap, with
    #    a truthful recorded length and digest for those exact oversized bytes.
    oversize_run = _build_sidecar_run(tmp_path, "validate-oversize", filler=32 * 1024)
    assert len(oversize_run.sidecar_bytes) > _SIDECAR_PROBE_RECORD_MAX_BYTES
    assert oversize_run.record["byte_length"] == len(oversize_run.sidecar_bytes)
    assert oversize_run.record["sha256"] == hashlib.sha256(oversize_run.sidecar_bytes).hexdigest()
    cases.append(("oversize", oversize_run, dict(oversize_run.record), "sidecar_oversize"))

    # Four independent fixtures, four distinct repositories, four distinct defects.
    assert len({str(run.repo) for _label, run, _record, _code in cases}) == 4
    assert [label for label, _run, _record, _code in cases] == list(anchors)

    try:
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_verification_sidecar")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleSidecarError")
    except (ImportError, AttributeError) as exc:
        _red("sidecar-validation-rejects-missing-drift-path-escape-or-oversize", str(exc))
        return
    for label, run, record, code in cases:
        with pytest.raises(error_cls) as excinfo:
            validate(run.repo, sidecar=record)
        assert excinfo.value.code == code, (label, excinfo.value.code)
    # Positive control: the untouched stamping fixture validates clean, so the four
    # rejections above are the defects and not the shape of the fixture itself.
    healthy = _build_sidecar_run(tmp_path, "validate-healthy")
    assert validate(healthy.repo, sidecar=dict(healthy.record)).ok


def test_verification_contract_v1_v2_v3_field_inventory_and_exemptions_matrix(tmp_path):
    # --- source injection anchors: the committed contract document's exact
    # top-level/per-stage tables, and the plan's frozen writer/binder matrix.
    _assert_contract_doc_contains(
        "`verification.json` uses schema version 2 and contains exactly these top-level fields:\n\n"
        + "".join(f"- `{field}`\n" for field in _BASE_TOP_LEVEL_FIELDS)
    )
    _assert_contract_doc_contains(
        "Each `commands[]` item contains `argv`, `cwd`, `exit_code`, `duration_s`, and `log_offset`. "
        "`env_refresh`, when present, contains `triggered`, `manifests`, `install_argv`, and "
        "`exit_code`. `suite`, when present, contains `argv`, `exit_code`, and `duration_s`."
    )
    _assert_contract_doc_contains("`load_verification_artifact` accepts `schema_version` in `{1, 2}`.")
    _assert_contract_doc_contains(f"`{_FROZEN_RUN_VERIFICATION_SIGNATURE}`")
    _assert_plan_contains("| no or empty `operational_exemptions`; no sidecar | schema v2, exactly `B` |")
    _assert_plan_contains(
        "| nonempty `operational_exemptions`; no sidecar | schema v2, exactly "
        "`B ∪ {operational_exemptions}`, with the list preserved and not executed |"
    )
    _assert_plan_contains(
        "| no or empty `operational_exemptions`; valid sidecar | schema v3, exactly `B ∪ {extensions}` |"
    )
    _assert_plan_contains(
        "| nonempty `operational_exemptions`; valid sidecar | schema v3, exactly "
        "`B ∪ {operational_exemptions, extensions}`, with the list preserved through bind/load/validate |"
    )
    if _canonical_repo_ready():
        # The immutable compatibility sentinel this matrix must not disturb.
        sentinel = REPO_ROOT / "phase-loop-runtime" / "tests" / "test_preflight_verification.py"
        assert "def test_operational_evidence_is_recorded_but_not_executed" in sentinel.read_text(
            encoding="utf-8"
        )

    module = _verification_evidence_module()
    repo = _evidence_repo(tmp_path)
    exemptions = [{"command": _UNEXECUTED_EXEMPTION_COMMAND, "reason": "evidence: operational"}]

    # --- current-base behavior (true against unchanged production): the public
    # writer's v2 matrix rows, per-stage inventories, and legacy round-trips.
    writer_rows = (
        ("absent", None, set(_BASE_TOP_LEVEL_FIELDS)),
        ("empty", [], set(_BASE_TOP_LEVEL_FIELDS)),
        ("nonempty", exemptions, set(_BASE_TOP_LEVEL_FIELDS) | {_OPERATIONAL_EXEMPTIONS_FIELD}),
    )
    runs: dict[str, tuple[Path, dict]] = {}
    for label, supplied, expected_fields in writer_rows:
        result, run_dir = _write_verification(repo, f"writer-{label}", supplied)
        payload = _artifact_payload(run_dir)
        assert payload["schema_version"] == 2, label
        assert set(payload) == expected_fields, label
        assert result.schema_version == 2
        assert set(payload["commands"][0]) >= set(_COMMAND_STAGE_REQUIRED), label
        assert set(payload["commands"][0]) <= set(_COMMAND_STAGE_REQUIRED) | set(_STAGE_V2_OPTIONAL), label
        assert payload["env_refresh"] is None and payload["suite"] is None, label
        log_text = (run_dir / module.LOG_NAME).read_text(encoding="utf-8")
        assert _EXECUTED_MARKER in log_text, label
        # The exemption is recorded for operator inspection, never executed.
        assert _UNEXECUTED_EXEMPTION_COMMAND not in log_text, label
        if supplied:
            assert payload[_OPERATIONAL_EXEMPTIONS_FIELD] == exemptions, label
            assert result.operational_exemptions == exemptions, label
        assert module.validate_verification_artifact(run_dir / module.ARTIFACT_NAME).ok, label
        runs[label] = (run_dir, payload)

    # Sealed and unsealed legacy v1 and v2 fixtures, round-tripped through the
    # PUBLIC loader, with exact per-stage inventories and v1 defaults.
    base_run, base_payload = runs["absent"]
    legacy_expectations = (
        ("v1-sealed", 1, True),
        ("v1-unsealed", 1, False),
        ("v2-sealed", 2, True),
        ("v2-unsealed", 2, False),
    )
    for label, version, sealed in legacy_expectations:
        legacy_dir = _clone_run_dir(base_run, tmp_path / f"legacy-{label}")
        payload = _downgrade_payload_to_v1(base_payload) if version == 1 else json.loads(json.dumps(base_payload))
        payload = _seal_run_dir(legacy_dir, payload) if sealed else _unseal_run_dir(legacy_dir, payload)
        artifact = legacy_dir / module.ARTIFACT_NAME
        loaded = module.load_verification_artifact(artifact)
        assert loaded.schema_version == version, label
        assert set(payload) == set(_BASE_TOP_LEVEL_FIELDS), label
        stage = payload["commands"][0]
        if version == 1:
            assert set(stage) == set(_COMMAND_STAGE_REQUIRED), label
            assert loaded.commands[0].log_end_offset is None and loaded.commands[0].failure_kind is None, label
        else:
            assert set(stage) <= set(_COMMAND_STAGE_REQUIRED) | set(_STAGE_V2_OPTIONAL), label
            assert loaded.commands[0].log_end_offset is not None, label
        assert loaded.env_refresh is None and loaded.suite is None, label
        assert not loaded.operational_exemptions, label
        assert module.validate_verification_artifact(artifact).ok, label
        assert (_log_trailer_digest((legacy_dir / module.LOG_NAME).read_bytes()) is not None) == sealed, label
    # The frozen env_refresh/suite inventories are asserted structurally above and
    # documented here as the literal tables the contract document freezes.
    assert _ENV_REFRESH_STAGE_REQUIRED == ("triggered", "manifests", "install_argv", "exit_code")
    assert _SUITE_STAGE_REQUIRED == ("argv", "exit_code", "duration_s")

    # --- the not-yet-implemented v3 contract.
    try:
        bind = _new_symbol("phase_loop_runtime.verification_evidence", "_bind_sidecar_extension")
        registry = _new_symbol("phase_loop_runtime.verification_evidence", "EXTENSION_NAMESPACE_REGISTRY")
    except (ImportError, AttributeError) as exc:
        _red("verification-contract-v1-v2-v3-field-inventory-and-exemptions-matrix", str(exc))
        return

    assert registry[_LEGIBLE_EXTENSION_NAMESPACE] == _SIDECAR_RECORD_SCHEMA
    binder_rows = (
        ("absent", set(_BASE_TOP_LEVEL_FIELDS) | {_EXTENSIONS_FIELD}),
        ("empty", set(_BASE_TOP_LEVEL_FIELDS) | {_EXTENSIONS_FIELD}),
        ("nonempty", set(_BASE_TOP_LEVEL_FIELDS) | {_OPERATIONAL_EXEMPTIONS_FIELD, _EXTENSIONS_FIELD}),
    )
    for label, expected_fields in binder_rows:
        run_dir, before = runs[label]
        artifact = run_dir / module.ARTIFACT_NAME
        rel_path, sidecar_bytes = _write_sidecar(repo, f"writer-{label}")
        record = _sidecar_record(rel_path, sidecar_bytes)
        bind(artifact, namespace=_LEGIBLE_EXTENSION_NAMESPACE, record=record)
        after = _artifact_payload(run_dir)
        assert after["schema_version"] == 3, label
        assert set(after) == expected_fields, label
        # v2 -> v3 preservation oracle: exactly schema_version and log_sha256 are
        # removed from the comparison; every other v2 JSON value is identical.
        derived = {"schema_version", "log_sha256", _EXTENSIONS_FIELD}
        assert {k: v for k, v in after.items() if k not in derived} == {
            k: v for k, v in before.items() if k not in derived
        }, label
        assert set(after[_EXTENSIONS_FIELD]) == {_LEGIBLE_EXTENSION_NAMESPACE}, label
        assert set(after[_EXTENSIONS_FIELD][_LEGIBLE_EXTENSION_NAMESPACE]) == set(_SIDECAR_RECORD_FIELDS), label
        assert after[_EXTENSIONS_FIELD][_LEGIBLE_EXTENSION_NAMESPACE] == record, label
        if label == "nonempty":
            assert after[_OPERATIONAL_EXEMPTIONS_FIELD] == exemptions, label
            reloaded = module.load_verification_artifact(artifact)
            assert reloaded.operational_exemptions == exemptions, label
        # Independent reseal oracle: the FINAL trailer seals the FINAL v3 payload
        # and log_sha256 covers the complete final log, not the intermediate v2 one.
        log_bytes = (run_dir / module.LOG_NAME).read_bytes()
        assert _log_trailer_digest(log_bytes) == _independent_payload_digest(after), label
        assert after["log_sha256"] == hashlib.sha256(log_bytes).hexdigest(), label
        assert after["log_sha256"] != before["log_sha256"], label
        assert module.validate_verification_artifact(artifact).ok, label
        # Mutating the final trailer must fail closed.
        mutated_dir = _clone_run_dir(run_dir, tmp_path / f"trailer-mutated-{label}")
        mutated_log = mutated_dir / module.LOG_NAME
        mutated_log.write_bytes(
            log_bytes.replace(_log_trailer_digest(log_bytes).encode("ascii"), b"0" * 64)
        )
        mutated = module.validate_verification_artifact(mutated_dir / module.ARTIFACT_NAME)
        assert not mutated.ok, label
        assert mutated.code in ("log_sha256_mismatch", "artifact_seal_mismatch"), (label, mutated.code)

    # No sidecar always stays v2: an unbound run is untouched by the binder.
    _, untouched_dir = _write_verification(repo, "writer-no-sidecar", exemptions)
    assert _artifact_payload(untouched_dir)["schema_version"] == 2


def test_verification_contract_rejects_unknown_versions_fields_and_extension_namespaces(tmp_path):
    _assert_plan_contains(
        "Unknown top-level schema versions, unregistered v3 extension namespaces, incompatible registered"
    )
    _assert_plan_contains(
        "including a v1 `operational_exemptions`, a v2 `extensions`, a v3 missing `extensions`, or any\n"
        "  other per-version additional field, remain `malformed_artifact`"
    )
    _assert_plan_contains(
        "Generic readers accept any registry-known namespace with its registered\n"
        "  closed record schema, so adding PROOFGATE's reserved namespace downstream does not invalidate\n"
        "  LEGIBLE-only artifacts or tests"
    )
    _assert_contract_doc_contains("`load_verification_artifact` accepts `schema_version` in `{1, 2}`.")

    module = _verification_evidence_module()
    repo = _evidence_repo(tmp_path)
    _, run_dir = _write_verification(repo, "reject-base", None)
    base_payload = _artifact_payload(run_dir)
    artifact_name, log_name = module.ARTIFACT_NAME, module.LOG_NAME

    def _mutated(label: str, payload: dict) -> Path:
        clone = _clone_run_dir(run_dir, tmp_path / f"reject-{label}")
        _seal_run_dir(clone, payload)
        return clone / artifact_name

    # --- current-base behavior: a coherent v2 artifact validates, and an
    # out-of-inventory top-level version is already refused (untyped today).
    assert module.validate_verification_artifact(run_dir / artifact_name).ok
    unknown_version = json.loads(json.dumps(base_payload))
    unknown_version["schema_version"] = 4
    assert not module.validate_verification_artifact(_mutated("unknown-version-base", unknown_version)).ok

    try:
        error_cls = _new_symbol("phase_loop_runtime.verification_evidence", "VerificationArtifactContractError")
        register = _new_symbol("phase_loop_runtime.verification_evidence", "register_extension_namespace")
        plan_aware = _new_symbol(
            "phase_loop_runtime.verification_evidence", "validate_verification_artifact_for_plan"
        )
        bind = _new_symbol("phase_loop_runtime.verification_evidence", "_bind_sidecar_extension")
    except (ImportError, AttributeError) as exc:
        _red("verification-contract-rejects-unknown-versions-fields-and-namespaces", str(exc))
        return

    rel_path, sidecar_bytes = _write_sidecar(repo, "reject-base")
    record = _sidecar_record(rel_path, sidecar_bytes)
    v3_dir = _clone_run_dir(run_dir, tmp_path / "reject-v3-source")
    bind(v3_dir / artifact_name, namespace=_LEGIBLE_EXTENSION_NAMESPACE, record=record)
    v3_payload = _artifact_payload(v3_dir)

    v1_payload = _downgrade_payload_to_v1(base_payload)
    cases: list[tuple[str, dict, str]] = []

    def _with(payload: dict, **changes) -> dict:
        updated = json.loads(json.dumps(payload))
        updated.update(changes)
        return updated

    cases.append(("unknown-top-level-version", _with(base_payload, schema_version=4), "unsupported_schema_version"))
    cases.append(
        ("v1-operational-exemptions",
         _with(v1_payload, operational_exemptions=[{"command": "x", "reason": "evidence: operational"}]),
         "malformed_artifact")
    )
    cases.append(("v2-extensions", _with(base_payload, extensions={}), "malformed_artifact"))
    v3_missing = json.loads(json.dumps(v3_payload))
    v3_missing.pop(_EXTENSIONS_FIELD)
    cases.append(("v3-missing-extensions", v3_missing, "malformed_artifact"))
    for label, payload in (("v1", v1_payload), ("v2", base_payload), ("v3", v3_payload)):
        cases.append((f"{label}-extra-field", _with(payload, legible_surprise_field=1), "malformed_artifact"))
    cases.append(
        ("unregistered-namespace",
         _with(v3_payload, extensions={"phase_loop_runtime.unregistered_evidence": dict(record)}),
         "unsupported_extension_namespace")
    )
    cases.append(
        ("incompatible-extension-version",
         _with(v3_payload,
               extensions={_LEGIBLE_EXTENSION_NAMESPACE: dict(record, schema="verification_evidence_sidecar.v9")}),
         "unsupported_extension_version")
    )
    cases.append(
        ("extension-record-extra-field",
         _with(v3_payload,
               extensions={_LEGIBLE_EXTENSION_NAMESPACE: dict(record, surprise_field="x")}),
         "malformed_artifact")
    )

    for label, payload, code in cases:
        path = _mutated(label, payload)
        with pytest.raises(error_cls) as excinfo:
            module.load_verification_artifact(path)
        assert excinfo.value.code == code, (label, excinfo.value.code)
        assert isinstance(excinfo.value, ValueError), label
        validation = module.validate_verification_artifact(path)
        assert not validation.ok and validation.code == code, (label, validation.code)

    # A LEGIBLE-only v3 artifact stays valid, generically and plan-aware, after
    # PROOFGATE's reserved namespace is later registered.
    legible_only = v3_dir / artifact_name
    assert module.validate_verification_artifact(legible_only).ok
    assert plan_aware(legible_only, required_namespaces=(_LEGIBLE_EXTENSION_NAMESPACE,)).ok
    register(_PROOFGATE_EXTENSION_NAMESPACE, "proofgate_evidence_sidecar.v1")
    assert module.validate_verification_artifact(legible_only).ok
    assert plan_aware(legible_only, required_namespaces=(_LEGIBLE_EXTENSION_NAMESPACE,)).ok


def test_public_compatibility_run_verification_load_validate_and_cli_signatures():
    _assert_contract_doc_contains(f"`{_FROZEN_RUN_VERIFICATION_SIGNATURE}`")
    _assert_contract_doc_contains("`load_verification_artifact(path)` validates the persisted artifact")
    _assert_plan_contains("signature does not gain a sidecar parameter")
    _assert_plan_contains("No public CLI or function caller can\n  inject an extension through a new argument")

    module = _verification_evidence_module()

    def _forbidden(names) -> list[str]:
        return [name for name in names if "sidecar" in name or "extension" in name]

    # --- current-base behavior: the frozen public surfaces, exactly.
    writer = inspect.signature(module.run_verification)
    assert [
        (name, param.default) for name, param in writer.parameters.items()
    ] == list(_FROZEN_RUN_VERIFICATION_PARAMETERS)
    assert all(
        param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for param in writer.parameters.values()
    )
    assert not _forbidden(writer.parameters)
    assert list(inspect.signature(module.load_verification_artifact).parameters) == ["path"]
    assert list(inspect.signature(module.validate_verification_artifact).parameters) == ["path"]
    assert list(inspect.signature(module.validate_verification_commands).parameters) == ["repo", "commands"]

    cli = importlib.import_module("phase_loop_runtime.cli")
    parser = cli.build_parser()
    option_strings: list[str] = []

    def _walk(target) -> None:
        for action in target._actions:
            option_strings.extend(action.option_strings)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for choice in choices.values():
                    if hasattr(choice, "_actions"):
                        _walk(choice)

    _walk(parser)
    assert "--verification-log" in option_strings
    assert not _forbidden(option_strings)

    # --- the not-yet-implemented v3 surfaces.
    try:
        bind = _new_symbol("phase_loop_runtime.verification_evidence", "_bind_sidecar_extension")
        plan_aware = _new_symbol(
            "phase_loop_runtime.verification_evidence", "validate_verification_artifact_for_plan"
        )
        register = _new_symbol("phase_loop_runtime.verification_evidence", "register_extension_namespace")
    except (ImportError, AttributeError) as exc:
        _red("public-compatibility-run-verification-load-validate-and-cli-signatures", str(exc))
        return

    # The binder is internal and keyword-bound; it is reachable from neither the
    # frozen public writer signature nor any CLI option.
    binder = inspect.signature(bind)
    assert list(binder.parameters) == ["artifact_path", "namespace", "record"]
    assert binder.parameters["namespace"].kind is inspect.Parameter.KEYWORD_ONLY
    assert binder.parameters["record"].kind is inspect.Parameter.KEYWORD_ONLY
    assert bind.__name__.startswith("_")
    assert not _forbidden(inspect.signature(module.run_verification).parameters)
    assert not _forbidden(option_strings)
    assert list(inspect.signature(module.load_verification_artifact).parameters) == ["path"]
    assert list(inspect.signature(module.validate_verification_artifact).parameters) == ["path"]
    assert list(inspect.signature(plan_aware).parameters) == ["path", "required_namespaces"]
    assert list(inspect.signature(register).parameters) == ["namespace", "schema"]


# ---------------------------------------------------------------------------
# The joint frozen 84-nodeid inventory and its JUnit fixtures
#
# The reducer's contract is stated over the phase's ONE frozen 84-nodeid set:
# this module's literal 20 plus its sibling's literal 64. The union is built
# from those two literal constants -- never from a live pytest collection and
# never from hand-typed placeholders -- and the sibling constant is read by
# loading ``test_legible_roadmap_contract.py`` from THIS directory by local file
# path. Both frozen test files are present side by side in every tree that runs
# this suite, including Gate A's copied ``tests/``-only tree, so the helper needs
# no canonical repository, no ``plans/`` directory, and no ``.git``.

_LEGIBLE_SIBLING_TEST_FILENAME = "test_legible_roadmap_contract.py"
_LEGIBLE_SIBLING_NODEID_COUNT = 64
_LEGIBLE_OWN_NODEID_COUNT = 20
LEGIBLE_JOINT_NODEID_COUNT = 84
# SHA-256 over the stable-sorted joint tuple joined by newlines. Frozen at
# LEGIBLE-A0 authoring time: any addition, removal, rename, or reordering of a
# nodeid in either file changes it.
LEGIBLE_JOINT_NODEID_DIGEST = "8b6d153cd009bdc68ebf0f3eca2f60c505386f9d164afca3aafead981a84be22"

# Short, stable per-file prefixes for the assigned mutation ids below.
_LEGIBLE_MODULE_SHORT_NAMES = {
    "test_legible_evidence": "evidence",
    "test_legible_roadmap_contract": "roadmap-contract",
}


@functools.lru_cache(maxsize=None)
def _sibling_expected_nodeids() -> tuple[str, ...]:
    tests_dir = Path(__file__).resolve().parent
    path = tests_dir / _LEGIBLE_SIBLING_TEST_FILENAME
    assert path.is_file(), f"frozen sibling test module missing: {path}"
    spec = importlib.util.spec_from_file_location("_legible_sibling_inventory", path)
    module = importlib.util.module_from_spec(spec)
    # The sibling imports its co-located tests-tree helpers by top-level name, so
    # execute it with its own directory importable regardless of how this run's
    # sys.path was assembled.
    restore = str(tests_dir) in sys.path
    if not restore:
        sys.path.insert(0, str(tests_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        if not restore:
            sys.path.remove(str(tests_dir))
    nodeids = tuple(module.LEGIBLE_EXPECTED_NODEIDS_V1)
    assert len(nodeids) == _LEGIBLE_SIBLING_NODEID_COUNT, len(nodeids)
    return nodeids


def _nodeid_tuple_digest(nodeids) -> str:
    return hashlib.sha256("\n".join(nodeids).encode("utf-8")).hexdigest()


def _joint_expected_nodeids() -> tuple[str, ...]:
    """The exact frozen union, asserted (not assumed) to be 84 unique, stable-sorted
    nodeids with the frozen tuple digest."""
    own = LEGIBLE_EXPECTED_NODEIDS_V1
    sibling = _sibling_expected_nodeids()
    assert len(own) == _LEGIBLE_OWN_NODEID_COUNT, len(own)
    assert len(sibling) == _LEGIBLE_SIBLING_NODEID_COUNT, len(sibling)
    assert not set(own) & set(sibling), sorted(set(own) & set(sibling))
    joint = tuple(sorted(set(own) | set(sibling)))
    assert len(joint) == len(set(joint)) == LEGIBLE_JOINT_NODEID_COUNT, len(joint)
    assert list(joint) == sorted(joint)
    assert all(nodeid.count("::") == 1 and nodeid.endswith(nodeid.split("::")[1]) for nodeid in joint)
    assert _nodeid_tuple_digest(joint) == LEGIBLE_JOINT_NODEID_DIGEST, _nodeid_tuple_digest(joint)
    return joint


def _assigned_mutation_id(nodeid: str) -> str:
    """The unique ``LEGIBLE_RED::<mutation-id>`` suffix assigned to one nodeid.

    Derived deterministically from the nodeid itself (file short name plus the
    slugified test name, parameter id included), so the assignment is one-to-one
    across all 84 by construction."""
    rel_path, _, name = nodeid.partition("::")
    short = _LEGIBLE_MODULE_SHORT_NAMES[Path(rel_path).stem]
    slug = re.sub(r"[^a-z0-9]+", "-", name.removeprefix("test_").lower()).strip("-")
    return f"{short}-{slug}"


def _junit_case_attrs(nodeid: str) -> tuple[str, str]:
    rel_path, _, name = nodeid.partition("::")
    assert rel_path.endswith(".py"), nodeid
    return rel_path[: -len(".py")].replace("/", "."), name


def _write_legible_junit(path: Path, statuses: dict) -> Path:
    """Write a real pytest-shaped JUnit XML whose ``<testcase>`` records map
    one-to-one onto the given nodeids, with per-node status."""
    suite = ET.Element("testsuite", name="pytest", hostname="legible-red", time="1.234")
    counts = {"passed": 0, "skipped": 0, "failure": 0}
    for nodeid, status in statuses.items():
        classname, name = _junit_case_attrs(nodeid)
        case = ET.SubElement(suite, "testcase", classname=classname, name=name, time="0.010")
        if status == "skipped":
            skipped = ET.SubElement(
                case, "skipped", type="pytest.skip", message=_shared_guard_reason()
            )
            skipped.text = _shared_guard_reason()
        elif status == "failure":
            message = f"LEGIBLE_RED::{_assigned_mutation_id(nodeid)}: missing production contract"
            failure = ET.SubElement(case, "failure", message=message)
            failure.text = f"{message}\n(source injection anchor asserted before this failure)"
        else:
            assert status == "passed", (nodeid, status)
        counts[status] += 1
    suite.set("tests", str(len(statuses)))
    suite.set("errors", "0")
    suite.set("failures", str(counts["failure"]))
    suite.set("skipped", str(counts["skipped"]))
    root = ET.Element("testsuites")
    root.append(suite)
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return path


def _parse_legible_junit(path: Path) -> dict:
    """Reconstruct ``{nodeid: (status, message)}`` from the written artifact."""
    observed: dict = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        nodeid = f"{case.get('classname').replace('.', '/')}.py::{case.get('name')}"
        children = list(case)
        assert len(children) <= 1, nodeid
        if not children:
            status, message = "passed", ""
        else:
            child = children[0]
            assert child.tag in ("skipped", "failure"), child.tag
            status, message = child.tag, child.get("message")
        assert nodeid not in observed, nodeid
        observed[nodeid] = (status, message)
    return observed


def _assert_junit_matches(path: Path, expected: dict) -> None:
    """Assert the artifact's parsed nodeid SET and per-node status, exactly."""
    observed = _parse_legible_junit(path)
    assert set(observed) == set(expected), (
        sorted(set(expected) - set(observed)), sorted(set(observed) - set(expected)),
    )
    assert {nodeid: status for nodeid, (status, _message) in observed.items()} == expected
    # No generic placeholder nodeids anywhere in the artifact.
    assert "test_legible_frozen_case_" not in path.read_text(encoding="utf-8")


# ===========================================================================
# Group 4 — activation/JUnit/digest (4 nodeids)
# ===========================================================================


def test_process_bootstrap_head_and_plan_digest_ancestry_controls(tmp_path):
    _assert_plan_contains("resolves the clean repo/worktree and exact `HEAD`, requires the expected\n40-hex commit")
    if _canonical_repo_ready():
        # Canonical repository control: a specific, presently-real commit.
        assert _real_commit_exists("6b77dc3")
        target_repo = REPO_ROOT
    else:
        # Installed-wheel clean room: there is no canonical ``.git`` history to
        # name a real historical commit from, so prove the identical "a real
        # commit resolves True" contract with a synthetic frozen one-commit
        # repo instead, exercising the same ``_real_commit_exists`` predicate.
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=target_repo, check=True)
        subprocess.run(["git", "config", "user.email", "legible-red@example.com"], cwd=target_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Legible Red"], cwd=target_repo, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=target_repo, check=True)
        (target_repo / "README.md").write_text("legible-red fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=target_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"], cwd=target_repo, check=True, stdout=subprocess.DEVNULL
        )
        synthetic_sha = subprocess.run(
            ["git", "-C", str(target_repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert _real_commit_exists(synthetic_sha, repo=target_repo)
    try:
        attest = _new_symbol("phase_loop_runtime.legible_evidence", "attest")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleProcessBootstrapError")
    except (ImportError, AttributeError) as exc:
        _red("process-bootstrap-head-and-plan-digest-ancestry", str(exc))
        return
    with pytest.raises(error_cls):
        attest(repo=target_repo, stage="candidate", expected_head="0" * 40, builder_run_id="fixture")


def test_default_junit_reports_84_skipped_zero_failed_zero_errors(tmp_path):
    _assert_plan_contains("The targeted JUnit must say `tests=84`, `skipped=84`, `failures=0`, `errors=0`")
    _assert_plan_contains(
        "rejects xfail/xpass, collection/import errors, deselection, missing/extra nodeids, or a skip"
    )
    # A JUnit fixture carrying the exact frozen 84-nodeid inventory -- built here
    # rather than by spawning a NESTED pytest run of this very suite (which would
    # recurse once the capability marker this file's contract installs makes the
    # whole file active by default rather than only under the forced env).
    joint = _joint_expected_nodeids()
    reason = _shared_guard_reason()
    expected = {nodeid: "skipped" for nodeid in joint}
    junit_path = _write_legible_junit(tmp_path / "default.junit.xml", expected)
    # Presently-true facts about the artifact, asserted before any contract call:
    # exactly the 84 real nodeids, each skipped exactly once, all with the one
    # shared, test-owned guard reason.
    _assert_junit_matches(junit_path, expected)
    observed = _parse_legible_junit(junit_path)
    assert len(observed) == LEGIBLE_JOINT_NODEID_COUNT
    assert {message for _status, message in observed.values()} == {reason}
    assert junit_path.read_text(encoding="utf-8").count("<testcase ") == 84
    assert junit_path.read_text(encoding="utf-8").count("<skipped ") == 84
    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_test_execution_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleTestExecutionError")
    except (ImportError, AttributeError) as exc:
        _red("default-junit-84-skipped-zero-failed-errors", str(exc))
        return
    evidence = collect(REPO_ROOT, junit_path=junit_path, expected_total=84)
    assert evidence.skipped == 84 and evidence.failed == 0 and evidence.errors == 0
    assert tuple(evidence.nodeids) == joint
    assert set(evidence.skip_reasons) == {reason}

    # Non-vacuity arms: the collector must reject a nodeid set that is one short,
    # one long, or carries one node in the wrong status.
    missing = {nodeid: status for nodeid, status in expected.items() if nodeid != joint[0]}
    extra = dict(expected)
    extra["tests/test_legible_evidence.py::test_legible_not_in_the_frozen_inventory"] = "skipped"
    wrong_status = dict(expected, **{joint[0]: "passed"})
    for label, statuses in (("missing", missing), ("extra", extra), ("wrong-status", wrong_status)):
        bad_path = _write_legible_junit(tmp_path / f"default-{label}.junit.xml", statuses)
        _assert_junit_matches(bad_path, statuses)
        with pytest.raises(error_cls):
            collect(REPO_ROOT, junit_path=bad_path, expected_total=84)


def test_forced_red_and_final_marker_junit_report_84_failed_then_84_passed(tmp_path):
    # ONE node, two independent literal observations (CHAIR-6 inventory
    # reallocation): the forced-RED run and the final marker-active run, each
    # reduced from its OWN real JUnit artifact.
    _assert_plan_contains("Raw RED output and JUnit must prove all 84 nodeids ran")
    _assert_plan_contains("final marker-active candidate/main\n  (`84 passed`, zero failure/error/skip)")

    joint = _joint_expected_nodeids()
    mutation_ids = {nodeid: _assigned_mutation_id(nodeid) for nodeid in joint}
    # The assignment really is one-to-one over the frozen inventory.
    assert len(set(mutation_ids.values())) == LEGIBLE_JOINT_NODEID_COUNT

    forced_expected = {nodeid: "failure" for nodeid in joint}
    final_expected = {nodeid: "passed" for nodeid in joint}
    forced_junit = _write_legible_junit(tmp_path / "forced-red.junit.xml", forced_expected)
    final_junit = _write_legible_junit(tmp_path / "final.junit.xml", final_expected)

    # Real artifacts carrying the exact frozen nodeid set and per-node status,
    # asserted before any contract call.
    _assert_junit_matches(forced_junit, forced_expected)
    _assert_junit_matches(final_junit, final_expected)
    forced_observed = _parse_legible_junit(forced_junit)
    for nodeid, (_status, message) in forced_observed.items():
        assert message.startswith(f"LEGIBLE_RED::{mutation_ids[nodeid]}:"), (nodeid, message)
    assert len({message for _status, message in forced_observed.values()}) == 84
    for junit_path in (forced_junit, final_junit):
        assert junit_path.read_text(encoding="utf-8").count("<testcase ") == 84
    assert forced_junit.read_text(encoding="utf-8").count("LEGIBLE_RED::") == 168
    assert final_junit.read_text(encoding="utf-8").count("LEGIBLE_RED::") == 0

    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_test_execution_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleTestExecutionError")
    except (ImportError, AttributeError) as exc:
        _red("forced-red-and-final-marker-junit-84-failed-then-84-passed", str(exc))
        return

    forced = collect(REPO_ROOT, junit_path=forced_junit, expected_total=84, mode="forced_red")
    assert forced.failed == 84 and forced.skipped == 0 and forced.errors == 0
    assert tuple(forced.nodeids) == joint
    assert len(forced.asserted_mutation_ids) == len(set(forced.asserted_mutation_ids)) == 84
    assert all(mutation_id.startswith("LEGIBLE_RED::") for mutation_id in forced.asserted_mutation_ids)
    assert set(forced.asserted_mutation_ids) == {
        f"LEGIBLE_RED::{mutation_id}" for mutation_id in mutation_ids.values()
    }

    final = collect(REPO_ROOT, junit_path=final_junit, expected_total=84, mode="final")
    assert final.passed == 84 and final.failed == 0 and final.skipped == 0 and final.errors == 0
    assert tuple(final.nodeids) == joint

    # Non-vacuity arm: one frozen nodeid that did not reach its intended failure.
    hybrid = dict(forced_expected, **{joint[0]: "passed"})
    hybrid_junit = _write_legible_junit(tmp_path / "forced-red-one-passed.junit.xml", hybrid)
    _assert_junit_matches(hybrid_junit, hybrid)
    with pytest.raises(error_cls):
        collect(REPO_ROOT, junit_path=hybrid_junit, expected_total=84, mode="forced_red")


def test_status_evidence_rejects_registry_banner_drift_or_path_set_change(tmp_path):
    _assert_plan_contains(
        "- `roadmap_status`: registry path/length/SHA-256, selected path, Git-tracked path-set digest, and\n"
        "  one stable path-sorted record for every tracked roadmap containing the registry status, parsed\n"
        "  banner status, exact primary-declaration line number, and declaration SHA-256."
    )
    _assert_plan_contains(
        "`verify --head HEAD` both call `validate_roadmap_status_coherence(required=True)`; mismatched\n"
        "  status, changed path coverage, malformed/ambiguous/missing declaration, or digest drift fails."
    )

    active_line3 = "> **Status (2026-07-29): ACTIVE — created this date, nothing executed yet.**"
    superseded_line3 = "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)"
    tracked = {
        "specs/phase-plans-v10.md": ("active", active_line3),
        "specs/phase-plans-v9.md": ("superseded", superseded_line3),
    }

    def _roadmap_bytes(rel_path: str, line3: str) -> str:
        return f"# Fixture {rel_path}\n\n{line3}\n\n## Body\n\ncontent\n"

    def _build(repo_name: str, *, statuses=None, banners=None, extra_roadmap=None) -> Path:
        repo = tmp_path / repo_name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _git(repo, "config", "user.email", "legible-red@example.com")
        _git(repo, "config", "user.name", "Legible Red")
        _git(repo, "config", "commit.gpgsign", "false")
        paths = {rel: line3 for rel, (_status, line3) in tracked.items()}
        if extra_roadmap is not None:
            paths[extra_roadmap] = superseded_line3
        for rel_path, line3 in paths.items():
            line = (banners or {}).get(rel_path, line3)
            _synthetic_write(repo, rel_path, _roadmap_bytes(rel_path, line))
        registry = {
            "schema": "roadmap_status_manifest.v1",
            "selected_roadmap": "specs/phase-plans-v10.md",
            "roadmaps": [
                {"path": rel_path, "status": (statuses or {}).get(rel_path, status)}
                for rel_path, (status, _line3) in sorted(tracked.items())
            ],
        }
        _synthetic_write(repo, "specs/roadmap-status.json", json.dumps(registry, indent=2, sort_keys=True) + "\n")
        _synthetic_commit(repo, "fixture: roadmap status")
        return repo

    coherent = _build("status-coherent")
    # Real, presently-true fixture facts, asserted before any contract call: the
    # tracked path set, the banner's exact line number, and its byte digest.
    coherent_tracked = sorted(_git(coherent, "ls-files", "specs").splitlines())
    assert coherent_tracked == sorted(list(tracked) + ["specs/roadmap-status.json"])
    for rel_path, (_status, line3) in tracked.items():
        lines = (coherent / rel_path).read_text(encoding="utf-8").splitlines()
        assert lines[2] == line3, rel_path
        assert len(hashlib.sha256(line3.encode("utf-8")).hexdigest()) == 64

    mutations = (
        ("registry_status_drift",
         _build("status-registry-drift", statuses={"specs/phase-plans-v10.md": "superseded"})),
        ("banner_declaration_drift",
         _build("status-banner-drift", banners={"specs/phase-plans-v10.md": superseded_line3})),
        ("tracked_path_set_change",
         _build("status-path-set", extra_roadmap="specs/phase-plans-v11.md")),
    )
    # Each mutation really differs from the coherent fixture in its own dimension.
    assert json.loads((mutations[0][1] / "specs/roadmap-status.json").read_text(encoding="utf-8")) != json.loads(
        (coherent / "specs/roadmap-status.json").read_text(encoding="utf-8")
    )
    assert (mutations[1][1] / "specs/phase-plans-v10.md").read_text(encoding="utf-8") != (
        coherent / "specs/phase-plans-v10.md"
    ).read_text(encoding="utf-8")
    assert sorted(_git(mutations[2][1], "ls-files", "specs").splitlines()) != coherent_tracked

    try:
        collect = _new_symbol("phase_loop_runtime.legible_evidence", "collect_roadmap_status")
        validate = _new_symbol("phase_loop_runtime.legible_evidence", "validate_roadmap_status_evidence")
        error_cls = _new_symbol("phase_loop_runtime.legible_evidence", "LegibleStatusEvidenceError")
    except (ImportError, AttributeError) as exc:
        _red("status-evidence-rejects-registry-banner-drift-or-path-set-change", str(exc))
        return

    # Positive control: a coherent repository collects and revalidates clean.
    record = collect(coherent, required=True)
    assert record["registry_path"] == "specs/roadmap-status.json"
    assert record["selected_roadmap"] == "specs/phase-plans-v10.md"
    assert len(record["registry_sha256"]) == 64 and record["registry_byte_length"] > 0
    assert len(record["tracked_path_set_sha256"]) == 64
    assert [entry["path"] for entry in record["roadmaps"]] == sorted(tracked)
    for entry in record["roadmaps"]:
        assert entry["registry_status"] == entry["banner_status"] == tracked[entry["path"]][0]
        assert entry["declaration_line"] == 3
        assert entry["declaration_sha256"] == hashlib.sha256(
            tracked[entry["path"]][1].encode("utf-8")
        ).hexdigest()
    assert validate(coherent, record, required=True).ok

    expected_codes = {
        "registry_status_drift": "roadmap_status_coherence_drift",
        "banner_declaration_drift": "roadmap_status_coherence_drift",
        "tracked_path_set_change": "roadmap_status_path_set_drift",
    }
    for label, repo in mutations:
        with pytest.raises(error_cls) as excinfo:
            collect(repo, required=True)
        assert excinfo.value.code == expected_codes[label], (label, excinfo.value.code)

    # Digest drift: declaration bytes change AFTER a coherent collection, so
    # revalidating the recorded digests must fail typed.
    drifted = _build("status-digest-drift")
    drifted_record = collect(drifted, required=True)
    _synthetic_write(
        drifted,
        "specs/phase-plans-v10.md",
        f"# Fixture specs/phase-plans-v10.md\n\n{active_line3} (amended)\n\n## Body\n\ncontent\n",
    )
    _synthetic_commit(drifted, "fixture: declaration bytes drift")
    with pytest.raises(error_cls) as excinfo:
        validate(drifted, drifted_record, required=True)
    assert excinfo.value.code == "roadmap_status_digest_drift"


# ===========================================================================
# Frozen nodeid inventory (LEGIBLE-A0)
# ===========================================================================

LEGIBLE_EXPECTED_NODEIDS_V1: tuple[str, ...] = tuple(sorted([
    "tests/test_legible_evidence.py::test_chronology_rejects_non_test_only_commit",
    "tests/test_legible_evidence.py::test_chronology_rejects_same_branch_sequence",
    "tests/test_legible_evidence.py::test_chronology_requires_test_landing_on_target_before_implementation_base",
    "tests/test_legible_evidence.py::test_chronology_rejects_test_path_diff_in_implementation_pr_range",
    "tests/test_legible_evidence.py::test_chronology_rejects_changed_frozen_test_blob",
    "tests/test_legible_evidence.py::test_pr_evidence_rejects_non_ancestor_body_sha",
    "tests/test_legible_evidence.py::test_pr_evidence_rejects_head_or_body_change_before_merge",
    "tests/test_legible_evidence.py::test_pr_evidence_requires_merged_result_for_snapshotted_head",
    "tests/test_legible_evidence.py::test_pr_evidence_rejects_unbound_target_integration_delta",
    "tests/test_legible_evidence.py::test_verification_sidecar_runner_captures_bounded_redacted_fable_probe_evidence",
    "tests/test_legible_evidence.py::test_verification_sidecar_runner_rejects_self_reported_fable_probe_evidence",
    "tests/test_legible_evidence.py::test_runner_stamps_legible_sidecar_path_and_digest",
    "tests/test_legible_evidence.py::test_sidecar_validation_rejects_missing_drift_path_escape_or_oversize",
    "tests/test_legible_evidence.py::test_verification_contract_v1_v2_v3_field_inventory_and_exemptions_matrix",
    "tests/test_legible_evidence.py::test_verification_contract_rejects_unknown_versions_fields_and_extension_namespaces",
    "tests/test_legible_evidence.py::test_public_compatibility_run_verification_load_validate_and_cli_signatures",
    "tests/test_legible_evidence.py::test_process_bootstrap_head_and_plan_digest_ancestry_controls",
    "tests/test_legible_evidence.py::test_default_junit_reports_84_skipped_zero_failed_zero_errors",
    "tests/test_legible_evidence.py::test_forced_red_and_final_marker_junit_report_84_failed_then_84_passed",
    "tests/test_legible_evidence.py::test_status_evidence_rejects_registry_banner_drift_or_path_set_change",
]))

assert len(LEGIBLE_EXPECTED_NODEIDS_V1) == 20, len(LEGIBLE_EXPECTED_NODEIDS_V1)
