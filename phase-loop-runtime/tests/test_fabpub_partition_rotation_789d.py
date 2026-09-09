"""Consiliency/agent-harness#789 Workstream D, Lane D1 — partition-rotation falsifiers.

RED-first falsifier module for
``plans/detailed-789d-fabpub-partition-rotation-20260908.md`` (anchors A0–A26).
Lane D1 is ``tests_only``: this module is NEW, ``_fabpub_tdd_guard.py`` is
untouched, and every helper is IMPORTED from its owning module (never copied),
following the ah#800 precedent (``d79564d0``).

Two guard layers, stacked per test (``pytestmark`` is deliberately empty):

* ``_requires_fabpub`` — the FABPUB capability marker, exactly as every sibling
  FABPUB module.
* ``_requires_789d`` — Lane D2 has not landed.  A test under this mark runs when
  ``PHASE_LOOP_TDD_EXPECT_789D=1`` is exported (RED at its anchor today) or when
  the production symbol ``rotate_blocked_partition`` exists in ``live``.

Runnable-now controls (only ``_requires_fabpub``): A0 (derivation sweep), A16
and A21 (v2 baselines), A22 (fresh-authority-root laundering), the v2 halves of
A12/A14.  Everything else asserts the production symbol FIRST (``_production``)
so a missing D2 fails at a named ``789D-RED-ANCHOR::<name>`` line, never at an
``AttributeError`` deep in a helper.

D2 contract these tests pin (tentative; the plan's Lane D2 owns the final shape,
and a D2 that lands a different spelling amends THIS module, not the guard):

* ``live.rotate_blocked_partition(worktree, *, cutover_id, attestation,
  authority_root=None)`` → outcome with ``.generation`` (int), ``.store_root``,
  ``.receipt``, ``.state == "ACTIVE"``, ``.predecessor_store_root``.  Resume is
  the same call with the same ``cutover_id``/attestation (idempotent, like
  ``bootstrap_zero_history_authority`` twice).
* Exceptions (all ``PermissionError`` subclasses, none a
  ``LegacyCutoverConflict``): ``PartitionRotationRefused`` (ceremony refusals),
  ``PartitionRoutingRefused`` (pointer-resolver refusals),
  ``PartitionReceiptIncompatible`` (A20 forward-compat; message names the
  unknown schema string and the receipt path).
* Constants: ``GENERATIONS_DIR = "generations"``, ``ACTIVE_POINTER = "ACTIVE"``,
  ``ROTATION_CEREMONY_DIR = "partition-rotations"``,
  ``RECEIPT_SCHEMA_V3 = "LegacyRepositoryPartitionReceipt.v3"``,
  ``ATTESTATION_SCHEMA = "PartitionRotationAttestation.v1"``, dispositions
  ``"observed_landed"`` / ``"attested_not_landed"``.
* Crash injection: ``live.ROTATION_CRASH_STEPS`` (tuple, superset of the steps
  in ``EXPECTED_CRASH_STEPS`` below), ``live.crash_at_rotation_step(step)``
  raising ``live._RotationCrash`` (a ``RuntimeError``), mirroring
  ``crash_at_cutover_step`` / ``_CutoverCrash``.
* Layout (plan D7): generation 0 is the container
  ``repositories/<identity>/`` (never moved); generation n≥1 lives at
  ``repositories/<identity>/generations/<n>/``; the pointer
  ``generations/ACTIVE`` is a regular file holding one integer (``0`` = the
  container).  Ceremony files live at
  ``<authority_root>/partition-rotations/<identity>/<cutover_id>.{inventory.json,journal.jsonl}``.

Sweep authority: A0's allow-list was produced by an AST sweep of
``convergence/broker/*.py`` at plan base ``3fe18ddb`` (kinds ``store_root``,
``parent.parent``, the ``"repositories"`` literal, ``target_namespace``) and is
asserted as ``observed == set(ALLOW_LIST)`` so a D2 that adds or removes a
derivation site must touch the list (and the plan's classification) on purpose.
Plan-seed sites not reachable by those tokens (``_receipt_active_authority_exists``,
``_receipt_seal_lock_paths``, ``_revalidate_bootstrap_sources``,
``_active_bootstrap_inventory``, ``_tree_file_inventory``) are covered by the
behavioural anchors (A18, A21, A22), not by the sweep.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest

from _fabpub_tdd_guard import (
    FABPUB_SKIP_REASON,
    fabpub_capability_active,
    fabpub_symbol,
)
from test_fabpub_recovery_controls_789 import (
    BLOCKED_KEY,
    BLOCKED_REFERENCE,
    _block_partition,
    _no_remote_probe,
    _partition,
    _two_partitions,
)
from test_fabpub_shared_epoch import (
    _CountingAdapter,
    _init_repo,
    _jsonl,
    _service,
    _supported_contracts,
)

pytestmark: list = []  # explicitly no module-level skip

LIVE_MODULE = "phase_loop_runtime.convergence.broker.live"
EVIDENCE_MODULE = "phase_loop_runtime.convergence.broker.evidence"
ADMISSION_MODULE = "phase_loop_runtime.convergence.broker.admission"
VERBS_MODULE = "phase_loop_runtime.convergence.broker.verbs"

_requires_fabpub = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)


def _guard_active() -> bool:
    if os.environ.get("PHASE_LOOP_TDD_EXPECT_789D") == "1":
        return True
    return fabpub_symbol(LIVE_MODULE, "rotate_blocked_partition") is not None


_requires_789d = pytest.mark.skipif(
    not _guard_active(),
    reason=(
        "Consiliency/agent-harness#789 Workstream D Lane D2 has not landed "
        "(export PHASE_LOOP_TDD_EXPECT_789D=1 to run these RED)"
    ),
)

# Test-pinned D2 spellings (see module docstring).
GENERATIONS_DIR = "generations"
ACTIVE_POINTER = "ACTIVE"
ROTATION_CEREMONY_DIR = "partition-rotations"
RECEIPT_SCHEMA_V3 = "LegacyRepositoryPartitionReceipt.v3"
ATTESTATION_SCHEMA = "PartitionRotationAttestation.v1"
OBSERVED_LANDED = "observed_landed"
ATTESTED_NOT_LANDED = "attested_not_landed"
ROTATION_ID = "rotation-789d-1"
EXPECTED_CRASH_STEPS = (
    "before_generations_rename",
    "after_generations_rename",
    "between_successor_files",
    "after_successor_receipt_before_flip",
    "after_journal_draining",
    "after_journal_inventory_sealed",
    "after_journal_armed",
)
STORE_FILES = ("admissions.jsonl", "evidence.jsonl", "admissions.lock", "partition-receipt.json")

RED_ANCHORS = {
    name: f"789D-RED-ANCHOR::{name}"
    for name in (
        "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11",
        "A12", "A13", "A14", "A15", "A16", "A17", "A18", "A19", "A20", "A21",
        "A22", "A23", "A24", "A25", "A26",
    )
}


def _anchor_of(request) -> str:
    """Anchor from the ``_a<N>[suffix]_`` token of the test name (``a17e`` → ``A17`` sub-anchor ``E``)."""
    import re

    name = request.node.originalname or request.node.name
    match = re.search(r"_a(\d+)([a-z]?)(?:_|$)", name)
    if match and f"A{match.group(1)}" in RED_ANCHORS:
        anchor = RED_ANCHORS[f"A{match.group(1)}"]
        return f"{anchor}{match.group(2).upper()}" if match.group(2) else anchor
    return f"789D-RED-ANCHOR::{name}"


def _require(request, condition, detail: str) -> None:
    if not condition:
        raise AssertionError(f"{_anchor_of(request)} — {detail}")


def _production(request, name: str, module: str = LIVE_MODULE):
    """Assert the D2 production symbol FIRST; return it."""
    symbol = fabpub_symbol(module, name)
    _require(request, symbol is not None, f"{module}.{name} is absent (Lane D2 not landed)")
    return symbol


def _live():
    import importlib

    return importlib.import_module(LIVE_MODULE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_or_none(path: Path):
    return path.read_bytes() if path.exists() else None


def _release(store) -> None:
    lease = getattr(store, "generation_lease", None)
    if lease is not None:
        with contextlib.suppress(Exception):
            lease.release()


def _release_all(*partitions) -> None:
    for p in partitions:
        _release(p.store)
        _release(getattr(p, "service", None) and p.service.evidence_store)


# ---------------------------------------------------------------------------
# Fixture — a real zero-history bootstrap over N repositories (v2 receipts today)
# ---------------------------------------------------------------------------


def _bootstrap(base: Path, monkeypatch, labels=("alpha", "beta")) -> SimpleNamespace:
    """Bootstrap one authority root over ``labels`` repos; return routed partitions.

    Uses the PRODUCTION zero-history probe + bootstrap (``probe_zero_history_bootstrap``
    → ``bootstrap_zero_history_authority``), the same idiom as
    ``test_fabpub_zero_history_bootstrap.py``.  Each partition is then wrapped by
    ``_partition`` (``test_fabpub_recovery_controls_789.py``) so publishes go
    through a real ``BrokerService`` on the CONTAINER root.
    """
    live = _live()
    authority = base / "authority"
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(authority))
    repos = {label: _init_repo(base / "repos" / label) for label in labels}
    inventory = live.probe_zero_history_bootstrap(
        cutover_id="bootstrap-789d",
        authority_root=authority,
        worktrees=tuple(repos.values()),
        legacy_roots=(base / "legacy",),
        historical_evidence_roots=(),
        search_roots=(base,),
    )
    report = live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    assert report["state"] == "ACTIVE", report
    partitions = {}
    for label, repo in repos.items():
        snapshot = live.repository_snapshot(repo)
        container = snapshot.namespace_root / "repositories" / snapshot.identity
        assert snapshot.store_root == container, "generation 0 must resolve to the container"
        p = _partition(base, repo, snapshot.identity, container, label=label)
        p.container = container
        p.authority = authority
        p.snapshot = snapshot
        partitions[label] = p
    return SimpleNamespace(
        base=base,
        authority=authority,
        repos=repos,
        inventory=inventory,
        report=report,
        partitions=partitions,
        **partitions,
    )


def _block_key(p, key: str) -> None:
    """Generalised ``_block_partition``: a permanent ambiguity under ``key``."""
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    store = p.service.evidence_store
    store.record_intent(key)
    store.record_terminal(
        EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, BLOCKED_REFERENCE)
    )
    assert store.epoch_blocked is True


def _blocked_keys(evidence_path: Path) -> list[str]:
    keys = []
    for line in _jsonl(evidence_path):
        if line.get("state") == "outcome_ambiguous_blocked":
            keys.append(line["idempotency_key"])
    return keys


def _ambiguity_digest(evidence_path: Path, key: str) -> str:
    last = None
    for raw in evidence_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        line = json.loads(raw)
        if line.get("idempotency_key") == key and line.get("state") == "outcome_ambiguous_blocked":
            last = raw
    assert last is not None, f"no permanent block for {key!r} in {evidence_path}"
    return hashlib.sha256(last.encode("utf-8")).hexdigest()


def _generation_of(store_root: Path) -> int:
    pointer = store_root / GENERATIONS_DIR / ACTIVE_POINTER
    if not pointer.exists():
        return 0
    return int(pointer.read_text(encoding="utf-8").strip())


def _attestation(
    p,
    *,
    keys=None,
    dispositions=None,
    predecessor_generation=None,
    observed_head=None,
) -> dict:
    """Operator attestation covering every permanent block on ``p``'s ACTIVE store."""
    live = _live()
    store_root = live.repository_snapshot(p.repo).store_root
    evidence_path = store_root / "evidence.jsonl"
    if keys is None:
        keys = _blocked_keys(evidence_path)
    effects = {}
    for key in keys:
        disposition = (dispositions or {}).get(key, ATTESTED_NOT_LANDED)
        effects[key] = {
            "disposition": disposition,
            "observed_head": observed_head if disposition == OBSERVED_LANDED else None,
            "ambiguity_digest": _ambiguity_digest(evidence_path, key),
        }
    return {
        "schema": ATTESTATION_SCHEMA,
        "attested_by": "operator",
        "predecessor_generation": (
            _generation_of(p.container) if predecessor_generation is None else predecessor_generation
        ),
        "effects": effects,
    }


def _attestation_digest(attestation: dict) -> str:
    live = _live()
    return hashlib.sha256(live.canonical_bytes(attestation)).hexdigest()


def _rotate(request, p, *, cutover_id=ROTATION_ID, attestation=None, release=True):
    """Run the PRODUCTION rotation on partition ``p`` (leases released first)."""
    rotate = _production(request, "rotate_blocked_partition")
    if release:
        _release_all(p)
    if attestation is None:
        attestation = _attestation(p)
    return rotate(p.repo, cutover_id=cutover_id, attestation=attestation, authority_root=p.authority)


def _ceremony_dir(p) -> Path:
    return p.authority / ROTATION_CEREMONY_DIR / p.identity


def _journal_states(p, cutover_id=ROTATION_ID) -> list[str]:
    path = _ceremony_dir(p) / f"{cutover_id}.journal.jsonl"
    if not path.exists():
        return []
    return [line.get("state") for line in _jsonl(path)]


def _store_bytes(root: Path) -> dict[str, bytes | None]:
    return {name: _read_or_none(root / name) for name in STORE_FILES}


def _assert_no_durable_rotation(request, p, *, cutover_id=ROTATION_ID) -> None:
    _require(
        request,
        not (p.container / GENERATIONS_DIR).exists()
        and not any(p.container.glob(f"{GENERATIONS_DIR}.tmp.*")),
        f"a refused rotation left generation debris under {p.container}",
    )
    _require(
        request,
        not (_ceremony_dir(p) / f"{cutover_id}.journal.jsonl").exists()
        and not (_ceremony_dir(p) / f"{cutover_id}.inventory.json").exists(),
        f"a refused rotation left ceremony files under {_ceremony_dir(p)}",
    )


def _routed_service(p, adapter=None):
    """A service built the way production routes: through ``_stores_for(snapshot)``."""
    from phase_loop_runtime.convergence.broker.verbs import BrokerService

    live = _live()
    router = live._RepositoryRoutingBrokerService(
        admission_policy=lambda _request: True, run=None, allowed_hosts=()
    )
    snapshot = live.repository_snapshot(p.repo)
    admission, evidence = router._stores_for(snapshot)
    adapter = adapter or _CountingAdapter()
    service = BrokerService(
        admission, evidence, adapter, contracts=_supported_contracts("publish_committed_branch")
    )
    return SimpleNamespace(router=router, snapshot=snapshot, service=service, adapter=adapter)


def _release_router(routed) -> None:
    for lease in list(getattr(routed.router, "_leases", {}).values()):
        with contextlib.suppress(Exception):
            lease.release()


def _successor_service(request, outcome, p, adapter=None):
    """Service over the successor generation, resolved through the production pointer."""
    live = _live()
    snapshot = live.repository_snapshot(p.repo)
    _require(
        request,
        snapshot.store_root == outcome.store_root,
        f"pointer resolves {snapshot.store_root}, rotation reported {outcome.store_root}",
    )
    return _routed_service(p, adapter)


def _pointer(p) -> Path:
    return p.container / GENERATIONS_DIR / ACTIVE_POINTER


@contextlib.contextmanager
def _unreadable(monkeypatch, target: Path):
    """Make exactly ``target`` raise ``OSError`` on open (the unreadable-pointer leg)."""
    real_open = pathlib.Path.open
    target = target.resolve()

    def _open(self, *args, **kwargs):
        if Path(self).resolve() == target:
            raise OSError(5, "simulated EIO reading the ACTIVE pointer")
        return real_open(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pathlib.Path, "open", _open)
        yield


def _pointer_states(p):
    """The resolver-only pointer refusal states (A12): name → mutator."""
    pointer = _pointer(p)

    def missing():
        pointer.unlink()

    def torn():
        pointer.write_bytes(b"1\x00\x00")

    def non_integer():
        pointer.write_text("one\n", encoding="utf-8")

    def nonexistent_generation():
        pointer.write_text("42\n", encoding="utf-8")

    def receiptless_generation():
        target = p.container / GENERATIONS_DIR / "7"
        target.mkdir(parents=True, exist_ok=True)
        (target / "admissions.lock").touch()
        pointer.write_text("7\n", encoding="utf-8")

    return {
        "missing": missing,
        "torn": torn,
        "non_integer": non_integer,
        "nonexistent_generation": nonexistent_generation,
        "receiptless_generation": receiptless_generation,
    }


def _host_wide_states(p):
    """Pointer states the barrier must refuse HOST-WIDE (inventory walk)."""
    pointer = _pointer(p)

    def symlink():
        pointer.unlink()
        pointer.symlink_to(p.container / "partition-receipt.json")

    def generations_non_directory():
        shutil.rmtree(p.container / GENERATIONS_DIR)
        (p.container / GENERATIONS_DIR).write_text("0\n", encoding="utf-8")

    return {"symlink": symlink, "generations_non_directory": generations_non_directory}


def _restore_pointer(p, saved: dict) -> None:
    gens = p.container / GENERATIONS_DIR
    if gens.exists() and not gens.is_dir():
        gens.unlink()
    for path, data in saved.items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        target.write_bytes(data)


def _save_pointer(p) -> dict:
    return {str(_pointer(p)): _pointer(p).read_bytes()}


# ---------------------------------------------------------------------------
# A0 — derivation sweep (runnable now)
# ---------------------------------------------------------------------------

#: (file, enclosing qualname, kind) triples at plan base 3fe18ddb.  Kinds:
#: ``store_root`` — attribute/arg/name use of ``store_root``;
#: ``parent.parent`` — a ``.parent.parent`` walk; ``"repositories"`` — the
#: literal path segment; ``target_namespace`` — receipt field use.
A0_ALLOW_LIST = (
    ("admission.py", "LinearizableAdmissionStore._authorize", '"repositories"'),
    ("admission.py", "LinearizableAdmissionStore._authorize", "parent.parent"),
    ("credsep.py", "GitHubBrokerAdapter._acquire_service_generation_lease", "store_root"),
    ("evidence.py", "BrokerEvidenceStore._authorize", '"repositories"'),
    ("evidence.py", "BrokerEvidenceStore._authorize", "parent.parent"),
    ("live.py", "LegacyBrokerCutoverTransaction.receipt_for", "target_namespace"),
    ("live.py", "LegacyBrokerCutoverTransaction.revalidate_armed", "target_namespace"),
    ("live.py", "LegacyRepositoryPartitionReceipt", "target_namespace"),
    ("live.py", "LegacyRepositoryPartitionReceipt.payload", "target_namespace"),
    ("live.py", "RepositorySnapshot.store_root", '"repositories"'),
    ("live.py", "WriterGenerationLatch.for_store_root", "store_root"),
    ("live.py", "WriterGenerationLatch.for_store_root", "parent.parent"),
    ("live.py", "_RepositoryRoutingBrokerService._stores_for", "store_root"),
    ("live.py", "_archive_targets_repository", "parent.parent"),
    ("live.py", "_classify_repository_namespace", "store_root"),
    ("live.py", "_classify_repository_namespace", "target_namespace"),
    ("live.py", "_drive_cutover", "target_namespace"),
    ("live.py", "_inventory_row_namespace_root", "parent.parent"),
    ("live.py", "_inventory_row_namespace_root", "target_namespace"),
    ("live.py", "_is_onboarding_atomic_temp", '"repositories"'),
    ("live.py", "_make_promotion_capability_factory._CutoverPromotionCapability.__init__", "store_root"),
    ("live.py", "_make_promotion_capability_factory.mint", "store_root"),
    ("live.py", "_onboard_zero_legacy_repository_under_seal", "store_root"),
    ("live.py", "_onboard_zero_legacy_repository_under_seal", "target_namespace"),
    ("live.py", "_plan_partitions", "target_namespace"),
    ("live.py", "_prove_zero_source", "store_root"),
    ("live.py", "_receipt_bootstrap_claim", "parent.parent"),
    ("live.py", "_receipt_bootstrap_claim", "target_namespace"),
    ("live.py", "_receipt_from_partition", "target_namespace"),
    ("live.py", "_target_store_lock_paths", "target_namespace"),
    ("live.py", "authenticated_partition_floor", "store_root"),
    ("live.py", "bootstrap_zero_history_authority", '"repositories"'),
    ("live.py", "fabpub_activation_barrier", '"repositories"'),
    ("live.py", "fabpub_activation_barrier", "store_root"),
    ("live.py", "load_partition_receipt", "store_root"),
    ("live.py", "partition_is_ambiguity_blocked", "store_root"),
    ("live.py", "repository_broker_namespace", "store_root"),
    ("live.py", "require_current_generation", "store_root"),
    ("live.py", "run_legacy_broker_cutover", "parent.parent"),
)

#: Plan classification of the 31 sites (by qualname).  ``resolver`` sites must
#: go through the generation pointer after D2; ``container`` sites stay bound
#: to generation 0 by design; ``inert`` sites carry the value without deriving.
A0_CLASSIFICATION = {
    "resolver": {
        "LinearizableAdmissionStore._authorize",
        "GitHubBrokerAdapter._acquire_service_generation_lease",
        "BrokerEvidenceStore._authorize",
        "RepositorySnapshot.store_root",
        "WriterGenerationLatch.for_store_root",
        "_RepositoryRoutingBrokerService._stores_for",
        "_make_promotion_capability_factory._CutoverPromotionCapability.__init__",
        "_make_promotion_capability_factory.mint",
        "_onboard_zero_legacy_repository_under_seal",
        "_prove_zero_source",
        "authenticated_partition_floor",
        "fabpub_activation_barrier",
        "load_partition_receipt",
        "partition_is_ambiguity_blocked",
        "repository_broker_namespace",
        "require_current_generation",
    },
    "container": {
        "LegacyRepositoryPartitionReceipt",
        "LegacyRepositoryPartitionReceipt.payload",
        "_classify_repository_namespace",
        "_drive_cutover",
        "_inventory_row_namespace_root",
        "_is_onboarding_atomic_temp",
        "_receipt_from_partition",
        "_target_store_lock_paths",
        "bootstrap_zero_history_authority",
    },
    "inert": {
        "LegacyBrokerCutoverTransaction.receipt_for",
        "LegacyBrokerCutoverTransaction.revalidate_armed",
        "_archive_targets_repository",
        "_plan_partitions",
        "_receipt_bootstrap_claim",
        "run_legacy_broker_cutover",
    },
}


def _sweep_derivation_sites(package_dir: Path) -> set[tuple[str, str, str]]:
    """AST sweep: every (file, enclosing qualname, kind) derivation site."""
    found: set[tuple[str, str, str]] = set()
    for source in sorted(package_dir.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        stack: list[str] = []

        def qual() -> str:
            return ".".join(stack) if stack else "<module>"

        def visit(node: ast.AST) -> None:
            scoped = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            if scoped:
                stack.append(node.name)
            if isinstance(node, ast.Attribute):
                if node.attr in ("store_root", "target_namespace"):
                    found.add((source.name, qual(), node.attr))
                if (
                    node.attr == "parent"
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "parent"
                ):
                    found.add((source.name, qual(), "parent.parent"))
            elif isinstance(node, ast.Name) and node.id in ("store_root", "target_namespace"):
                found.add((source.name, qual(), node.id))
            elif isinstance(node, ast.arg) and node.arg in ("store_root", "target_namespace"):
                found.add((source.name, qual(), node.arg))
            elif isinstance(node, ast.Constant) and node.value == "repositories":
                found.add((source.name, qual(), '"repositories"'))
            elif isinstance(node, ast.Constant) and node.value == "target_namespace":
                found.add((source.name, qual(), "target_namespace"))
            elif isinstance(node, ast.keyword) and node.arg in ("store_root", "target_namespace"):
                found.add((source.name, qual(), node.arg))
            for child in ast.iter_child_nodes(node):
                visit(child)
            if scoped:
                stack.pop()

        visit(tree)
    return found


@_requires_fabpub
def test_partition_rotation_a0_derivation_sites_match_the_plan_allow_list(request):
    """A0: the store-root derivation sites are exactly the plan's allow-list.

    A D2 that adds a derivation site (a new resolver, a new container-bound
    helper) or removes one must edit ``A0_ALLOW_LIST`` and place the qualname in
    ``A0_CLASSIFICATION`` — the sweep is the instrument, the classification is
    the claim (resolver sites are the ones A12/A17/A18 exercise).
    """
    live = _production(request, "repository_snapshot")
    package_dir = Path(live.__code__.co_filename).parent
    observed = _sweep_derivation_sites(package_dir)
    expected = set(A0_ALLOW_LIST)
    _require(
        request,
        observed == expected,
        "derivation sweep drifted from the plan allow-list; "
        f"added={sorted(observed - expected)} removed={sorted(expected - observed)}",
    )
    classified = set().union(*A0_CLASSIFICATION.values())
    qualnames = {qualname for _file, qualname, _kind in A0_ALLOW_LIST}
    _require(
        request,
        classified == qualnames,
        f"unclassified={sorted(qualnames - classified)} stale={sorted(classified - qualnames)}",
    )
    overlap = (
        (A0_CLASSIFICATION["resolver"] & A0_CLASSIFICATION["container"])
        | (A0_CLASSIFICATION["resolver"] & A0_CLASSIFICATION["inert"])
        | (A0_CLASSIFICATION["container"] & A0_CLASSIFICATION["inert"])
    )
    _require(request, not overlap, f"a site carries two classifications: {sorted(overlap)}")


# ---------------------------------------------------------------------------
# A16 / A21 / A22 / A24 — v2 baselines and controls (runnable now)
# ---------------------------------------------------------------------------


@_requires_fabpub
def test_partition_rotation_a21_v2_container_baseline_authenticates_and_publishes(tmp_path, monkeypatch, request):
    """A21: a fresh v2 bootstrap container authenticates, routes and passes the barrier.

    Baseline for every later anchor: the unrotated container is generation 0,
    ``load_partition_receipt`` authenticates the v2 receipt, the partition is
    not ambiguity-blocked, its receipt has an ACTIVE global authority, a publish
    through the PRODUCTION routing seam lands, and the activation barrier passes.
    """
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    for p in fx.partitions.values():
        receipt = live.load_partition_receipt(p.container)
        _require(request, receipt is not None, f"{p.label}: v2 receipt did not authenticate")
        _require(request, receipt.SCHEMA.endswith(".v2"), f"{p.label}: schema {receipt.SCHEMA}")
        _require(request, not live.partition_is_ambiguity_blocked(p.container), f"{p.label} blocked")
        _require(
            request,
            live._receipt_active_authority_exists(receipt, authority_root=p.authority),
            f"{p.label}: receipt has no ACTIVE global authority",
        )
        _release_all(p)
        routed = _routed_service(p)
        try:
            result = routed.service.execute(p.request)
            _require(request, result.accepted is True, f"{p.label}: publish refused: {result.reason}")
            _require(request, len(routed.adapter.calls) == 1, "one adapter call expected")
        finally:
            _release_router(routed)
    report = live.fabpub_activation_barrier(worktrees=tuple(fx.repos.values()))
    try:
        _require(request, report.get("state") in ("ACTIVE", None) or report, "barrier did not pass")
    finally:
        live.release_barrier_leases(report)


@_requires_fabpub
def test_partition_rotation_a16_v2_partitions_unaffected_by_foreign_rotation_dir(tmp_path, monkeypatch, request):
    """A16 (v2 half): an unrelated ``partition-rotations/`` tree changes nothing for v2 routing.

    A ceremony directory for an identity that does NOT exist in this authority
    root must neither block v2 partitions nor be mistaken for a rotation of
    theirs: receipts still authenticate, the global authority is still found,
    the routed publish still lands.  (Whether the authority-root inventory
    tolerates the directory is A18d, under the D2 guard: today's
    ``probe_zero_history_bootstrap`` refuses ANY unexpected authority file,
    ``live.py`` around line 2404.)
    """
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    foreign = fx.authority / ROTATION_CEREMONY_DIR / ("0" * 64)
    foreign.mkdir(parents=True)
    (foreign / "rotation-x.journal.jsonl").write_text(
        json.dumps({"state": "DRAINING", "cutover_id": "rotation-x"}) + "\n", encoding="utf-8"
    )
    for p in fx.partitions.values():
        receipt = live.load_partition_receipt(p.container)
        _require(request, receipt is not None, f"{p.label} lost authentication")
        _require(
            request,
            live._receipt_active_authority_exists(receipt, authority_root=p.authority),
            f"{p.label}: global authority lost under a foreign rotation dir",
        )
        _release_all(p)
        routed = _routed_service(p)
        try:
            result = routed.service.execute(p.request)
            _require(request, result.accepted is True, f"{p.label}: publish refused: {result.reason}")
        finally:
            _release_router(routed)


@_requires_fabpub
def test_partition_rotation_a22_fresh_authority_root_refuses_populated_namespace(tmp_path, monkeypatch, request):
    """A22: a NEW authority root over an already-populated namespace must refuse.

    Rotation must not be launderable by bootstrapping again elsewhere.  The
    plan expects the refusal at ``_classify_repository_namespace``; the
    innermost ``live.py`` frame is recorded in the assertion so the PR body can
    cite the observed site (a later site — e.g. ``LegacyRepositoryPartitionReceipt.write``
    — is acceptable and recorded; NO refusal joins scope).
    """
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    _release_all(*fx.partitions.values())
    second_root = tmp_path / "authority2"
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(second_root))
    refused_at = None
    try:
        inventory = live.probe_zero_history_bootstrap(
            cutover_id="bootstrap-789d-second",
            authority_root=second_root,
            worktrees=tuple(fx.repos.values()),
            legacy_roots=(tmp_path / "legacy",),
            historical_evidence_roots=(),
            search_roots=(tmp_path,),
        )
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    except live.LegacyCutoverConflict as exc:
        frames = [
            f for f in traceback.extract_tb(exc.__traceback__) if f.filename.endswith("live.py")
        ]
        refused_at = frames[-1].name if frames else "<no live.py frame>"
    _require(
        request,
        refused_at is not None,
        "a fresh authority root bootstrapped over a populated namespace — laundering hole (joins scope)",
    )
    # Observed refusal site, recorded for the PR body.
    assert refused_at in (
        "_classify_repository_namespace",
        "write",
        "_onboard_zero_legacy_repository_under_seal",
        "bootstrap_zero_history_authority",
        "probe_zero_history_bootstrap",
    ), f"A22 refused at unexpected site {refused_at!r} (record it in the PR body)"
    for p in fx.partitions.values():
        _require(request, live.load_partition_receipt(p.container) is not None, "original receipt damaged")
        _require(
            request,
            not (second_root / "partition-rotations").exists()
            and not list(second_root.glob("**/repositories/**/partition-receipt.json")),
            "the refusing bootstrap left receipts under the second root",
        )


@_requires_fabpub
def test_partition_rotation_a24_v2_publish_does_not_probe_the_remote(tmp_path, monkeypatch, request):
    """A24 (v2 half): a routed publish on the unrotated container never runs ``ls-remote``."""
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    _release_all(p)
    with _no_remote_probe(monkeypatch) as attempts:
        routed = _routed_service(p)
        try:
            result = routed.service.execute(p.request)
        finally:
            _release_router(routed)
    _require(request, result.accepted is True, f"publish refused: {result.reason}")
    _require(request, attempts == [], f"the publish consulted the remote: {attempts}")


# ---------------------------------------------------------------------------
# A1–A10 — the happy path, carried terminals, refusals (D2-gated)
# ---------------------------------------------------------------------------


def _blocked_fixture(tmp_path, monkeypatch, labels=("alpha", "beta")):
    fx = _bootstrap(tmp_path, monkeypatch, labels=labels)
    _block_partition(fx.alpha.service)
    fx.gen0 = _store_bytes(fx.alpha.container)
    return fx


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a1_rotated_partition_publishes_through_the_pointer(tmp_path, monkeypatch, request):
    """A1: after rotation the SAME repository publishes on the successor generation."""
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    outcome = _rotate(request, p)
    _require(request, outcome.state == "ACTIVE", f"rotation state {outcome.state!r}")
    _require(request, outcome.generation == 1, f"successor generation {outcome.generation!r}")
    _require(
        request,
        outcome.store_root == p.container / GENERATIONS_DIR / "1",
        f"successor store root {outcome.store_root}",
    )
    _require(request, outcome.predecessor_store_root == p.container, "predecessor is the container")
    _require(request, _generation_of(p.container) == 1, "ACTIVE pointer did not flip to 1")
    routed = _successor_service(request, outcome, p)
    try:
        result = routed.service.execute(p.request)
        _require(request, result.accepted is True, f"successor publish refused: {result.reason}")
        _require(
            request,
            result.evidence.terminal_state == "effect_terminal_observed",
            f"terminal {result.evidence.terminal_state!r}",
        )
        _require(request, len(routed.adapter.calls) == 1, "exactly one provider effect")
        _require(request, p.adapter.calls == [], "the generation-0 adapter must not have been reached")
    finally:
        _release_router(routed)
    _require(request, _store_bytes(p.container) == fx.gen0, "generation-0 bytes changed after rotation")
    _require(
        request,
        (outcome.store_root / "evidence.jsonl").exists()
        and (outcome.store_root / "admissions.jsonl").exists(),
        "successor publish wrote nothing under the successor store",
    )


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a2_successor_dedups_within_its_own_generation(tmp_path, monkeypatch, request):
    """A2: a second attempt on the successor replays — one provider effect total."""
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    outcome = _rotate(request, p)
    routed = _successor_service(request, outcome, p)
    try:
        first = routed.service.execute(p.request)
        second = routed.service.execute(p.request)
        _require(request, first.accepted is True and second.accepted is True, "publish refused")
        _require(request, len(routed.adapter.calls) == 1, f"{len(routed.adapter.calls)} adapter calls")
        _require(
            request,
            second.evidence.evidence_reference == first.evidence.evidence_reference,
            "the replay did not answer with the first attempt's evidence",
        )
    finally:
        _release_router(routed)


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a3_unblocked_partition_refuses_rotation(tmp_path, monkeypatch, request):
    """A3: rotation is for permanently blocked partitions only — typed refusal, no writes."""
    fx = _bootstrap(tmp_path, monkeypatch)
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    p = fx.beta
    _release_all(*fx.partitions.values())
    before = _store_bytes(p.container)
    with pytest.raises(refused) as info:
        _rotate(
            request,
            p,
            attestation={"schema": ATTESTATION_SCHEMA, "attested_by": "operator",
                         "predecessor_generation": 0, "effects": {}},
        )
    _require(request, not isinstance(info.value, live.LegacyCutoverConflict), "must not be a LegacyCutoverConflict")
    _assert_no_durable_rotation(request, p)
    _require(request, _store_bytes(p.container) == before, "refusal changed the store")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a4_successor_answers_carried_terminals(tmp_path, monkeypatch, request):
    """A4: a key blocked in generation 0 stays answered on the successor — no fresh effect.

    The block is written under the REAL dedup key of ``p.request`` (the key a
    retry of the same transaction produces), attested ``attested_not_landed``.
    The successor must answer that retry from the carried disposition — a typed
    refusal or a non-accepted result carrying the carried terminal — and the
    adapter must not be reached.
    """
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    _block_key(p, carried_key)
    gen0 = _store_bytes(p.container)
    outcome = _rotate(request, p)
    dispositions = outcome.receipt.adjudicated_effect_dispositions
    _require(request, carried_key in dispositions, f"carried block missing from {sorted(dispositions)}")
    _require(
        request,
        dispositions[carried_key]["disposition"] == ATTESTED_NOT_LANDED,
        f"disposition {dispositions[carried_key]!r}",
    )
    routed = _successor_service(request, outcome, p)
    try:
        try:
            result = routed.service.execute(p.request)
        except PermissionError:
            result = None
        _require(
            request,
            result is None or result.accepted is False,
            "the successor re-ran a carried (attested) transaction as fresh",
        )
        _require(request, routed.adapter.calls == [], "a carried terminal reached the provider")
    finally:
        _release_router(routed)
    _require(request, _store_bytes(p.container) == gen0, "generation 0 changed")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a5_successor_starts_with_no_adapter_owner(tmp_path, monkeypatch, request):
    """A5: the successor carries no ``adapter-start-owner.json`` and never reads one."""
    import phase_loop_runtime.convergence.broker.verbs as verbs

    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    # Give generation 0 an unsealed owner so a copied owner would be visible.
    p.owner.write_text(json.dumps({"attempt_id": "stale", "idempotency_key": BLOCKED_KEY}), encoding="utf-8")
    outcome = _rotate(request, p)
    _require(request, not (outcome.store_root / "adapter-start-owner.json").exists(), "owner file copied")
    reads: list = []
    real = verbs.read_adapter_start_owner

    def _spy(root, *args, **kwargs):
        reads.append(Path(root))
        return real(root, *args, **kwargs)

    monkeypatch.setattr(verbs, "read_adapter_start_owner", _spy)
    routed = _successor_service(request, outcome, p)
    try:
        result = routed.service.execute(p.request)
        _require(request, result.accepted is True, f"publish refused: {result.reason}")
    finally:
        _release_router(routed)
    _require(request, p.container not in reads, "the successor read generation 0's owner file")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a6_successor_promotion_mints_a_fresh_capability(tmp_path, monkeypatch, request):
    """A6: ``promote_legacy_terminal`` on the successor mints for the SUCCESSOR root."""
    live = _live()
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    outcome = _rotate(request, p)
    minted: list = []
    real = live._mint_cutover_promotion_capability

    def _spy(root, key, *args, **kwargs):
        minted.append((Path(root), key))
        return real(root, key, *args, **kwargs)

    monkeypatch.setattr(live, "_mint_cutover_promotion_capability", _spy)
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    store = BrokerEvidenceStore(outcome.store_root)
    with contextlib.suppress(PermissionError, ValueError):
        store.promote_legacy_terminal(BLOCKED_KEY)
    _require(request, minted and minted[-1][0] == outcome.store_root, f"minted for {minted}")
    _require(request, _store_bytes(p.container) == fx.gen0, "promotion touched generation 0")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a7_attestation_digest_is_single_use(tmp_path, monkeypatch, request):
    """A7: the successor records the attestation digest; re-using it for a later rotation refuses."""
    fx = _blocked_fixture(tmp_path, monkeypatch)
    refused = _production(request, "PartitionRotationRefused")
    p = fx.alpha
    attestation = _attestation(p)
    digest = _attestation_digest(attestation)
    outcome = _rotate(request, p, attestation=attestation)
    recorded = outcome.receipt.adjudicated_effect_dispositions[BLOCKED_KEY]["attestation_digest"]
    _require(request, recorded == digest, f"recorded digest {recorded} != {digest}")
    # Block the successor and try to rotate again with the SAME attestation bytes.
    routed = _successor_service(request, outcome, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), BLOCKED_KEY)
    finally:
        _release_router(routed)
    with pytest.raises(refused):
        _rotate(request, p, cutover_id="rotation-789d-2", attestation=attestation)
    _require(request, _generation_of(p.container) == 1, "a refused rotation moved the pointer")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a8_undisposed_ambiguity_refuses(tmp_path, monkeypatch, request):
    """A8: every ambiguity on the predecessor must be disposed — (i) receipt-level, (ii) key-level."""
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    # (i) the receipt itself says ambiguous → nothing can attest it away.
    real_load = live.load_partition_receipt

    def _ambiguous(root, *args, **kwargs):
        receipt = real_load(root, *args, **kwargs)
        if receipt is not None and Path(root) == p.container:
            return dataclasses.replace(receipt, ambiguous=True)
        return receipt

    with monkeypatch.context() as patch:
        patch.setattr(live, "load_partition_receipt", _ambiguous)
        with pytest.raises(refused):
            _rotate(request, p)
    _assert_no_durable_rotation(request, p)
    # (ii) an orphan intent (no terminal) plus the real block: attesting only the
    # blocked key refuses; attesting both succeeds.
    orphan = "publish_committed_branch\x00ah789d-orphan-intent"
    p.service.evidence_store.record_intent(orphan)
    _release_all(p)
    with pytest.raises(refused):
        _rotate(request, p, attestation=_attestation(p, keys=[BLOCKED_KEY]))
    _assert_no_durable_rotation(request, p)
    attestation = _attestation(p, keys=[BLOCKED_KEY])
    attestation["effects"][orphan] = {
        "disposition": ATTESTED_NOT_LANDED,
        "observed_head": None,
        "ambiguity_digest": None,
    }
    outcome = _rotate(request, p, attestation=attestation)
    _require(request, outcome.state == "ACTIVE", "both-keys attestation refused")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a9_stale_predecessor_generation_refuses(tmp_path, monkeypatch, request):
    """A9: an attestation naming the wrong predecessor generation is refused, no writes."""
    refused = _production(request, "PartitionRotationRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    with pytest.raises(refused):
        _rotate(request, p, attestation=_attestation(p, predecessor_generation=3))
    _assert_no_durable_rotation(request, p)
    _require(request, _store_bytes(p.container) == fx.gen0, "refusal changed generation 0")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a10_attestation_must_cover_every_blocked_key(tmp_path, monkeypatch, request):
    """A10: two blocks under two verbs — a partial attestation refuses; full covers."""
    refused = _production(request, "PartitionRotationRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    second = "refresh_pull_request\x00abc"
    _block_key(p, second)
    keys = _blocked_keys(p.evidence)
    _require(request, set(keys) == {BLOCKED_KEY, second}, f"blocks {keys}")
    with pytest.raises(refused):
        _rotate(request, p, attestation=_attestation(p, keys=[BLOCKED_KEY]))
    _assert_no_durable_rotation(request, p)
    outcome = _rotate(request, p, attestation=_attestation(p, keys=keys))
    dispositions = outcome.receipt.adjudicated_effect_dispositions
    _require(request, set(dispositions) == {BLOCKED_KEY, second}, f"dispositions {sorted(dispositions)}")


# ---------------------------------------------------------------------------
# A11–A15 — crash sweep, pointer resolver, debris, pre-v3 readers (D2-gated)
# ---------------------------------------------------------------------------


def _crash_steps(request) -> tuple[str, ...]:
    steps = _production(request, "ROTATION_CRASH_STEPS")
    missing = set(EXPECTED_CRASH_STEPS) - set(steps)
    _require(request, not missing, f"ROTATION_CRASH_STEPS lacks {sorted(missing)}")
    return tuple(steps)


def _crash_rotation(request, p, step, *, cutover_id=ROTATION_ID, attestation=None):
    live = _live()
    crash_at = _production(request, "crash_at_rotation_step")
    crash_cls = _production(request, "_RotationCrash")
    with crash_at(step):
        with pytest.raises(crash_cls):
            _rotate(request, p, cutover_id=cutover_id, attestation=attestation)
    return live


def _assert_generation_zero_routable_and_blocked(request, p, gen0, *, step: str) -> None:
    """Post-crash invariant: generation 0 routes, refuses on its block, refuses onboarding."""
    live = _live()
    snapshot = live.repository_snapshot(p.repo)
    _require(request, snapshot.store_root == p.container, f"[{step}] pointer left generation 0 unroutable")
    routed = _routed_service(p)
    try:
        with pytest.raises(PermissionError):
            routed.service.execute(p.request)
        _require(request, routed.adapter.calls == [], f"[{step}] the blocked partition reached the provider")
    finally:
        _release_router(routed)
    with pytest.raises(live.LegacyCutoverConflict):
        live.onboard_zero_legacy_repository(p.repo, authority_root=p.authority)
    _require(request, _store_bytes(p.container) == gen0, f"[{step}] generation-0 bytes changed")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a11_crash_sweep_leaves_generation_zero_routable_and_resumes(tmp_path, monkeypatch, request):
    """A11: at EVERY crash step generation 0 still routes and refuses; resume completes.

    Sweep iterates the PRODUCTION tuple — a step the production adds is
    exercised automatically; a step the plan names that production lacks fails
    at the anchor.
    """
    steps = _crash_steps(request)
    for step in steps:
        base = tmp_path / step
        fx = _blocked_fixture(base, monkeypatch)
        p = fx.alpha
        _crash_rotation(request, p, step)
        _assert_generation_zero_routable_and_blocked(request, p, fx.gen0, step=step)
        outcome = _rotate(request, p)
        _require(request, outcome.state == "ACTIVE" and outcome.generation == 1, f"[{step}] resume failed")
        routed = _successor_service(request, outcome, p)
        try:
            result = routed.service.execute(p.request)
            _require(request, result.accepted is True, f"[{step}] successor publish refused: {result.reason}")
        finally:
            _release_router(routed)
        _require(request, _store_bytes(p.container) == fx.gen0, f"[{step}] generation-0 bytes changed on resume")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a12_pointer_refusal_states_are_typed_and_final(tmp_path, monkeypatch, request):
    """A12: each pointer refusal state → ``PartitionRoutingRefused`` everywhere, no fallback.

    Resolver-only states are asserted at ``repository_snapshot().store_root``,
    at ``_stores_for`` and through ``onboard_zero_legacy_repository`` (no
    onboarding fallback).  The unreadable leg patches ``Path.open`` to raise
    ``OSError`` for the pointer; a leg without a construction is a failure,
    not a skip.  Also: after an ``after_generations_rename`` crash the pointer
    reads ``0``; after a clean rotation no ``ACTIVE`` temp file remains.
    """
    live = _live()
    routing_refused = _production(request, "PartitionRoutingRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    outcome = _rotate(request, p)
    _require(request, outcome.generation == 1, "rotation did not produce generation 1")
    gens = p.container / GENERATIONS_DIR
    leftovers = [x.name for x in gens.iterdir() if x.name.startswith(ACTIVE_POINTER) and x.name != ACTIVE_POINTER]
    _require(request, leftovers == [], f"pointer temp leftovers {leftovers}")
    saved = _save_pointer(p)
    states = dict(_pointer_states(p))
    states.update(_host_wide_states(p))
    for name, mutate in states.items():
        _restore_pointer(p, saved)
        mutate()
        with pytest.raises(routing_refused):
            _ = live.repository_snapshot(p.repo).store_root
        router = live._RepositoryRoutingBrokerService(admission_policy=lambda _r: True, run=None, allowed_hosts=())
        with pytest.raises(routing_refused):
            router._stores_for(live.repository_snapshot(p.repo))
        _release_router(SimpleNamespace(router=router))
        with pytest.raises((routing_refused, live.LegacyCutoverConflict)):
            live.onboard_zero_legacy_repository(p.repo, authority_root=p.authority)
        _require(request, not (p.container / GENERATIONS_DIR / "2").exists(), f"[{name}] a refusal created a generation")
    _restore_pointer(p, saved)
    with _unreadable(monkeypatch, _pointer(p)):
        with pytest.raises(routing_refused):
            _ = live.repository_snapshot(p.repo).store_root
    _require(request, live.repository_snapshot(p.repo).store_root == outcome.store_root, "pointer restore failed")
    # after_generations_rename crash: the pointer must read 0.
    fx2 = _blocked_fixture(tmp_path / "crash", monkeypatch)
    _crash_rotation(request, fx2.alpha, "after_generations_rename")
    _require(request, _pointer(fx2.alpha).exists(), "generations/ACTIVE missing after the rename")
    _require(request, _generation_of(fx2.alpha.container) == 0, "pointer after rename crash is not 0")


@_requires_fabpub
def test_partition_rotation_a12_v2_container_without_pointer_resolves_to_generation_zero(tmp_path, monkeypatch, request):
    """A12 (v2 half): a container with no ``generations/`` at all is generation 0."""
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    for p in fx.partitions.values():
        _require(request, not (p.container / GENERATIONS_DIR).exists(), "v2 bootstrap created generations/")
        _require(request, live.repository_snapshot(p.repo).store_root == p.container, "v2 store root moved")
        _require(request, _generation_of(p.container) == 0, "v2 generation is not 0")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a13_foreign_and_torn_ceremony_artifacts_refuse(tmp_path, monkeypatch, request):
    """A13: foreign-id temp debris, a non-ACTIVE journal, and a torn journal each refuse."""
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    # (a) foreign-id generations temp debris.
    fx = _blocked_fixture(tmp_path / "debris", monkeypatch)
    p = fx.alpha
    (p.container / f"{GENERATIONS_DIR}.tmp.rotation-other").mkdir()
    with pytest.raises(refused):
        _rotate(request, p)
    _require(request, not (p.container / GENERATIONS_DIR).exists(), "rotated over foreign debris")
    # (b) a new cutover id while the previous journal is not ACTIVE.
    fx = _blocked_fixture(tmp_path / "journal", monkeypatch)
    p = fx.alpha
    _crash_rotation(request, p, "after_journal_armed")
    states = _journal_states(p)
    _require(request, states and states[-1] != "ACTIVE", f"journal after ARMED crash: {states}")
    with pytest.raises(refused):
        _rotate(request, p, cutover_id="rotation-789d-new")
    _require(request, _journal_states(p, "rotation-789d-new") == [], "a refused new id wrote a journal")
    # (c) a torn journal for the SAME id refuses resume with a typed refusal.
    journal = _ceremony_dir(p) / f"{ROTATION_ID}.journal.jsonl"
    journal.write_bytes(journal.read_bytes()[:-7])
    with pytest.raises((refused, live.LegacyCutoverConflict)):
        _rotate(request, p)
    _require(request, _generation_of(p.container) == 0, "a torn journal flipped the pointer")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a14_successor_receipt_binding_is_enforced(tmp_path, monkeypatch, request):
    """A14: a successor generation authenticates only with ITS OWN receipt.

    (a) a foreign-identity receipt under ``generations/1`` refuses; (b) a
    receipt-less ``generations/2`` refuses at ``_authorize`` on both stores;
    (c) generation 1's receipt copied under ``generations/2`` refuses.
    """
    live = _live()
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _blocked_fixture(tmp_path, monkeypatch, labels=("alpha", "beta"))
    p = fx.alpha
    outcome = _rotate(request, p)
    gen1 = outcome.store_root
    receipt_bytes = (gen1 / "partition-receipt.json").read_bytes()
    # (a) foreign identity receipt.
    (gen1 / "partition-receipt.json").write_bytes(
        (fx.beta.container / "partition-receipt.json").read_bytes()
    )
    with pytest.raises((PermissionError, live.LegacyCutoverConflict)):
        live.load_partition_receipt(gen1)
    with pytest.raises((PermissionError, live.LegacyCutoverConflict)):
        BrokerEvidenceStore(gen1)._authorize()
    (gen1 / "partition-receipt.json").write_bytes(receipt_bytes)
    # (b) receipt-less generation 2.
    gen2 = p.container / GENERATIONS_DIR / "2"
    gen2.mkdir()
    (gen2 / "admissions.lock").touch()
    with pytest.raises(PermissionError):
        BrokerEvidenceStore(gen2)._authorize()
    with pytest.raises(PermissionError):
        LinearizableAdmissionStore(gen2, lambda _r: True)._authorize()
    # (c) generation 1's receipt copied under generation 2.
    (gen2 / "partition-receipt.json").write_bytes(receipt_bytes)
    with pytest.raises((PermissionError, live.LegacyCutoverConflict)):
        BrokerEvidenceStore(gen2)._authorize()
    with pytest.raises((PermissionError, live.LegacyCutoverConflict)):
        LinearizableAdmissionStore(gen2, lambda _r: True)._authorize()
    _require(request, live.load_partition_receipt(gen1) is not None, "generation 1 lost authentication")


@_requires_fabpub
def test_partition_rotation_a14_v2_container_receipt_binding_is_enforced(tmp_path, monkeypatch, request):
    """A14 (v2 half): the container refuses a sibling's receipt.

    Observed on v2 (recorded, not asserted): a receipt-less
    ``<container>/generations/1`` is NOT refused today — ``evidence.py``
    ``_authorize`` classifies a canonical store by ``parent.name ==
    "repositories"``, so a generation subdirectory is an ordinary
    non-canonical legacy store and authorizes freely.  Closing that hole is
    the gated A14 / plan residual F1 (site the generation predicate in the
    shared ``_require_generation`` helpers), not a v2 control.
    """
    live = _live()

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    original = (p.container / "partition-receipt.json").read_bytes()
    (p.container / "partition-receipt.json").write_bytes(
        (fx.beta.container / "partition-receipt.json").read_bytes()
    )
    with pytest.raises((PermissionError, live.LegacyCutoverConflict)):
        live.load_partition_receipt(p.container)
    (p.container / "partition-receipt.json").write_bytes(original)
    _require(request, live.load_partition_receipt(p.container) is not None, "container lost authentication")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a15_pre_v3_reader_on_the_container_stays_refused(tmp_path, monkeypatch, request):
    """A15: a pre-v3 reader bound to the container (ignores the pointer) is safe at every crash step.

    Such a reader refuses on the permanent block before, during and after
    rotation, never reaches the adapter, and never sees a successor receipt.
    """
    steps = _crash_steps(request)
    for step in steps + ("clean",):
        base = tmp_path / step
        fx = _blocked_fixture(base, monkeypatch)
        p = fx.alpha
        if step == "clean":
            _rotate(request, p)
        else:
            _crash_rotation(request, p, step)
        adapter = _CountingAdapter()
        legacy = _service(p.container, adapter)
        with pytest.raises(PermissionError):
            legacy.execute(p.request)
        _require(request, adapter.calls == [], f"[{step}] the pre-v3 reader reached the provider")
        _require(request, _store_bytes(p.container) == fx.gen0, f"[{step}] the pre-v3 reader wrote generation 0")
        _release(legacy.admission_store)
        _release(legacy.evidence_store)


# ---------------------------------------------------------------------------
# A17 — the flip is a fence for every writer class (D2-gated)
# ---------------------------------------------------------------------------


def _record(key: str):
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    return EvidenceRecord(key, TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, "late-writer")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a17_flip_fences_pre_flip_lease_and_fresh_writers(tmp_path, monkeypatch, request):
    """A17a–d: a lease taken in the drain→flip gap, fresh leases, UNDECLARED stores, promotion.

    (a) a writer that acquires a generation-0 lease immediately AFTER the real
    drain returns (the pre-flip gap) is refused in-lock after the flip;
    (b) a fresh post-flip lease on the container is refused; (c) an UNDECLARED
    store on the container is refused at ``_authorize``; (d)
    ``promote_legacy_terminal`` on the successor writes only successor files.
    Generation-0 bytes are unchanged throughout.  Assumes D2 drains through
    ``WriterGenerationLatch.await_quiescent`` (as onboarding does).
    """
    live = _live()
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    gap: dict = {}
    real_await = live.WriterGenerationLatch.await_quiescent

    def _await_then_grab(self, *args, **kwargs):
        result = real_await(self, *args, **kwargs)
        if not gap:
            state = self.read()
            gap["lease"] = self.acquire(generation=state.generation)
            gap["generation"] = state.generation
        return result

    monkeypatch.setattr(live.WriterGenerationLatch, "await_quiescent", _await_then_grab)
    outcome = _rotate(request, p)
    _require(request, "lease" in gap, "await_quiescent was not the drain seam (assumption in the docstring)")
    _require(request, outcome.generation == 1, "rotation did not complete under a gap lease")
    # (a) gap lease, generation-0 append.
    late = BrokerEvidenceStore(p.container, generation_lease=gap["lease"])
    with pytest.raises(PermissionError):
        late.record_intent("publish_committed_branch\x00late-gap-writer")
    late_admission = LinearizableAdmissionStore(p.container, lambda _r: True, generation_lease=gap["lease"])
    with pytest.raises(PermissionError):
        late_admission.admit(p.request.admission)
    with contextlib.suppress(Exception):
        gap["lease"].release()
    # (b) fresh post-flip lease on the container.
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    with pytest.raises(PermissionError):
        fresh = latch.acquire(generation=gap["generation"])
        try:
            BrokerEvidenceStore(p.container, generation_lease=fresh).record_intent("publish_committed_branch\x00fresh")
        finally:
            with contextlib.suppress(Exception):
                fresh.release()
    # (c) UNDECLARED stores on the container.
    with pytest.raises(PermissionError):
        BrokerEvidenceStore(p.container)._authorize()
    with pytest.raises(PermissionError):
        LinearizableAdmissionStore(p.container, lambda _r: True)._authorize()
    _require(request, _store_bytes(p.container) == fx.gen0, "a fenced writer changed generation 0")
    # (d) promotion on the successor writes only successor files.
    successor_before = _store_bytes(outcome.store_root)
    with contextlib.suppress(PermissionError, ValueError):
        BrokerEvidenceStore(outcome.store_root).promote_legacy_terminal(BLOCKED_KEY)
    _require(request, _store_bytes(p.container) == fx.gen0, "promotion on the successor touched generation 0")
    changed = {k for k in STORE_FILES if _store_bytes(outcome.store_root)[k] != successor_before[k]}
    _require(request, changed <= {"evidence.jsonl", "admissions.lock"}, f"promotion changed {sorted(changed)}")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a17e_authorized_before_flip_is_refused_in_lock(tmp_path, monkeypatch, request):
    """A17e: a store that passed ``_authorize`` BEFORE the flip is still refused in-lock after it.

    ``_authorize`` is run once pre-flip and then neutralised, so the only
    remaining check is the in-lock generation predicate at the append / admit
    sites (``evidence.py`` ``_append``, ``admission.py`` ``admit``).
    """
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    _release_all(p)
    evidence = BrokerEvidenceStore(p.container)
    admission = LinearizableAdmissionStore(p.container, lambda _r: True)
    evidence._authorize()
    admission._authorize()
    monkeypatch.setattr(evidence, "_authorize", lambda: None)
    monkeypatch.setattr(admission, "_authorize", lambda: None)
    outcome = _rotate(request, p)
    _require(request, outcome.generation == 1, "rotation failed")
    with pytest.raises(PermissionError):
        evidence._append(_record("publish_committed_branch\x00pre-authorized"))
    with pytest.raises(PermissionError):
        admission.admit(p.request.admission)
    with pytest.raises(PermissionError):
        evidence.promote_legacy_terminal(BLOCKED_KEY)
    _require(request, _store_bytes(p.container) == fx.gen0, "a pre-authorized writer changed generation 0")


# ---------------------------------------------------------------------------
# A18 — host-wide barrier vs one rotated partition (D2-gated)
# ---------------------------------------------------------------------------


def _barrier(live, worktrees):
    report = live.fabpub_activation_barrier(worktrees=tuple(worktrees))
    return report


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a18_barrier_and_siblings_survive_rotated_pointer_states(tmp_path, monkeypatch, request):
    """A18a/b/d: clean v2 siblings pass the barrier and publish while alpha is rotated,
    and still do with alpha's pointer in each RESOLVER-ONLY refusal state; the
    symlink / non-directory / unreadable members refuse HOST-WIDE from the
    inventory walk.  Bootstrap re-validation is unchanged with the rotation
    directory present.
    """
    live = _live()
    routing_refused = _production(request, "PartitionRoutingRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch, labels=("alpha", "beta", "gamma"))
    alpha, beta, gamma = fx.alpha, fx.beta, fx.gamma
    _release_all(alpha, beta, gamma)
    outcome = _rotate(request, alpha)
    siblings = [beta, gamma]

    def _siblings_publish_and_barrier_passes(tag: str) -> None:
        report = _barrier(live, [s.repo for s in siblings])
        try:
            _require(request, report is not None, f"[{tag}] barrier refused the clean siblings")
        finally:
            live.release_barrier_leases(report)
        for s in siblings:
            routed = _routed_service(s)
            try:
                result = routed.service.execute(s.request)
                _require(request, result.accepted is True, f"[{tag}] {s.label} refused: {result.reason}")
            finally:
                _release_router(routed)

    _siblings_publish_and_barrier_passes("rotated")
    report = _barrier(live, [alpha.repo, beta.repo, gamma.repo])
    try:
        _require(request, report is not None, "barrier over the rotated partition refused")
    finally:
        live.release_barrier_leases(report)
    saved = _save_pointer(alpha)
    for name, mutate in _pointer_states(alpha).items():
        _restore_pointer(alpha, saved)
        mutate()
        _siblings_publish_and_barrier_passes(name)
        with pytest.raises(routing_refused):
            _ = live.repository_snapshot(alpha.repo).store_root
    for name, mutate in _host_wide_states(alpha).items():
        _restore_pointer(alpha, saved)
        mutate()
        with pytest.raises((live.LegacyCutoverConflict, OSError, PermissionError)):
            report = _barrier(live, [alpha.repo, beta.repo, gamma.repo])
            live.release_barrier_leases(report)
    _restore_pointer(alpha, saved)
    with _unreadable(monkeypatch, _pointer(alpha)):
        with pytest.raises((live.LegacyCutoverConflict, OSError, PermissionError)):
            report = _barrier(live, [alpha.repo, beta.repo, gamma.repo])
            live.release_barrier_leases(report)
    # A18d: bootstrap re-validation unchanged with the rotation directory present.
    resumed = live.bootstrap_zero_history_authority(fx.inventory, confirmed_zero_history=True)
    _require(request, resumed["state"] == "ACTIVE", "bootstrap re-validation changed under the rotation dir")
    _require(request, live.repository_snapshot(alpha.repo).store_root == outcome.store_root, "pointer restore failed")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a18c_successor_without_global_authority_or_journal_refuses(tmp_path, monkeypatch, request):
    """A18c: the successor receipt needs its bootstrap claim AND an ACTIVE rotation journal.

    Without the global bootstrap inventory the successor has no active
    authority (``_receipt_active_authority_exists`` False) and the barrier
    refuses at its no-matching-authority site; with the rotation journal
    truncated or deleted the barrier refuses too.
    """
    live = _live()
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    outcome = _rotate(request, p)
    successor = live.load_partition_receipt(outcome.store_root)
    _require(request, successor is not None, "successor receipt did not authenticate")
    _require(request, successor.SCHEMA == RECEIPT_SCHEMA_V3, f"successor schema {successor.SCHEMA}")
    _require(
        request,
        live._receipt_active_authority_exists(successor, authority_root=p.authority),
        "successor receipt has no active authority on a clean rotation",
    )
    with monkeypatch.context() as patch:
        patch.setattr(live, "_active_bootstrap_inventory", lambda *a, **k: None)
        _require(
            request,
            not live._receipt_active_authority_exists(successor, authority_root=p.authority),
            "successor authority survives without the bootstrap inventory",
        )
        with pytest.raises(live.LegacyCutoverConflict):
            report = _barrier(live, [p.repo])
            live.release_barrier_leases(report)
    journal = _ceremony_dir(p) / f"{ROTATION_ID}.journal.jsonl"
    original = journal.read_bytes()
    journal.write_bytes(original[:-5])
    with pytest.raises((live.LegacyCutoverConflict, PermissionError)):
        report = _barrier(live, [p.repo])
        live.release_barrier_leases(report)
    journal.unlink()
    with pytest.raises((live.LegacyCutoverConflict, PermissionError)):
        report = _barrier(live, [p.repo])
        live.release_barrier_leases(report)
    journal.write_bytes(original)
    report = _barrier(live, [p.repo])
    try:
        _require(request, report is not None, "barrier refused after the journal was restored")
    finally:
        live.release_barrier_leases(report)


# ---------------------------------------------------------------------------
# A19 / A20 / A23 / A25 / A26 (D2-gated)
# ---------------------------------------------------------------------------


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a19_second_rotation_chains_generations(tmp_path, monkeypatch, request):
    """A19: rotating a blocked generation 1 yields generation 2 with generation 1 as predecessor.

    Crash steps are swept for the 1→2 rotation as well; the successor's
    ``predecessor_generation`` and digests bind generation 1, not the container.
    """
    steps = _crash_steps(request)
    for step in ("clean",) + steps:
        fx = _blocked_fixture(tmp_path / step, monkeypatch)
        p = fx.alpha
        first = _rotate(request, p)
        routed = _successor_service(request, first, p)
        try:
            _block_key(SimpleNamespace(service=routed.service), BLOCKED_KEY)
        finally:
            _release_router(routed)
        gen1_bytes = _store_bytes(first.store_root)
        if step != "clean":
            _crash_rotation(request, p, step, cutover_id="rotation-789d-2")
            _require(request, _generation_of(p.container) == 1, f"[{step}] crash moved the pointer off 1")
        second = _rotate(request, p, cutover_id="rotation-789d-2")
        _require(request, second.generation == 2, f"[{step}] second rotation generation {second.generation}")
        _require(request, second.predecessor_store_root == first.store_root, f"[{step}] predecessor is not generation 1")
        _require(request, second.receipt.predecessor_generation == 1, f"[{step}] predecessor_generation != 1")
        digests = second.receipt.predecessor_digests
        for name in ("admissions.jsonl", "evidence.jsonl", "partition-receipt.json"):
            _require(
                request,
                digests.get(name) == hashlib.sha256(gen1_bytes[name] or b"").hexdigest(),
                f"[{step}] predecessor digest for {name} does not bind generation 1's final bytes",
            )
        _require(request, _store_bytes(first.store_root) == gen1_bytes, f"[{step}] generation 1 changed")
        _require(request, _store_bytes(p.container) == fx.gen0, f"[{step}] generation 0 changed")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a20_unknown_receipt_schema_is_a_typed_forward_compat_refusal(tmp_path, monkeypatch, request):
    """A20: an unknown receipt schema → ``PartitionReceiptIncompatible`` naming schema + path.

    RED today: ``load_partition_receipt`` raises ``LegacyCutoverConflict("unknown
    partition receipt schema …")`` (live.py around line 807).  The refusal must
    not be a ``LegacyCutoverConflict`` (plan D5: forward-compat is not a cutover
    conflict), and the message names the schema string and the receipt path.
    """
    live = _live()
    incompatible = _production(request, "PartitionReceiptIncompatible")
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    path = p.container / "partition-receipt.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema"] = "LegacyRepositoryPartitionReceipt.v99"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(incompatible) as info:
        live.load_partition_receipt(p.container)
    _require(request, not isinstance(info.value, live.LegacyCutoverConflict), "forward-compat refusal is a cutover conflict")
    message = str(info.value)
    _require(request, "LegacyRepositoryPartitionReceipt.v99" in message, f"schema not named: {message}")
    _require(request, str(path) in message, f"receipt path not named: {message}")
    _release_all(p)
    with pytest.raises(incompatible):
        live._RepositoryRoutingBrokerService(admission_policy=lambda _r: True, run=None, allowed_hosts=())._stores_for(
            live.repository_snapshot(p.repo)
        )


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a23_successor_floor_carries_the_predecessor_epoch(tmp_path, monkeypatch, request):
    """A23: the successor's authenticated floor ≥ the predecessor's high-water, through an idle generation."""
    live = _live()
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    pred_receipt = live.load_partition_receipt(p.container)
    epochs = [line.get("epoch", 0) for line in _jsonl(p.admissions)] if p.admissions.exists() else []
    expected = max([pred_receipt.legacy_epoch_high_water, *epochs])
    first = _rotate(request, p)
    _require(request, live.authenticated_partition_floor(first.store_root) >= expected, "generation-1 floor dropped")
    # Generation 1 allocates nothing, gets blocked, rotates → generation 2 still carries the floor.
    routed = _successor_service(request, first, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), BLOCKED_KEY)
    finally:
        _release_router(routed)
    second = _rotate(request, p, cutover_id="rotation-789d-2")
    _require(
        request,
        live.authenticated_partition_floor(second.store_root) >= expected,
        "generation-2 floor dropped through an idle generation",
    )


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a25_traditional_v2_authority_refuses_rotation(tmp_path, request):
    """A25: a partition under the traditional (non-bootstrap) v2 authority is refused, no writes."""
    refused = _production(request, "PartitionRotationRefused")
    alpha, _beta = _two_partitions(tmp_path)
    _block_partition(alpha.service)
    _release_all(alpha, _beta)
    alpha.container = alpha.root
    alpha.authority = Path(os.environ["PHASE_LOOP_FABPUB_AUTHORITY_ROOT"])
    before = _store_bytes(alpha.root)
    with pytest.raises(refused):
        _rotate(request, alpha, attestation=_attestation(alpha))
    _assert_no_durable_rotation(request, alpha)
    _require(request, _store_bytes(alpha.root) == before, "refusal changed the traditional partition")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a26_concurrent_writer_lands_before_digest_or_is_fenced(tmp_path, monkeypatch, request):
    """A26: a writer holding generation 1's lock across a 1→2 rotation lands before the
    predecessor digest is taken or is fenced — never after the digest."""
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    first = _rotate(request, p)
    routed = _successor_service(request, first, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), BLOCKED_KEY)
    finally:
        _release_router(routed)
    gen1 = first.store_root
    key = "publish_committed_branch\x00ah789d-concurrent-writer"
    holding = threading.Event()
    proceed = threading.Event()
    result: dict = {}

    def writer():
        store = BrokerEvidenceStore(gen1)
        try:
            with open(gen1 / "admissions.lock", "a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                store._authorize()
                holding.set()
                proceed.wait(120)
                fcntl.flock(handle, fcntl.LOCK_UN)
            store.record_intent(key)
            result["landed"] = True
        except PermissionError as exc:
            result["fenced"] = str(exc)
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            result["error"] = repr(exc)

    def rotator():
        try:
            result["outcome"] = _rotate(request, p, cutover_id="rotation-789d-2")
        except Exception as exc:
            result["rotation_error"] = exc

    t_writer = threading.Thread(target=writer, daemon=True)
    t_rotate = threading.Thread(target=rotator, daemon=True)
    t_writer.start()
    _require(request, holding.wait(60), "writer never took the lock")
    t_rotate.start()
    t_rotate.join(2.0)  # let the rotation reach the seal
    proceed.set()
    t_writer.join(120)
    t_rotate.join(120)
    _require(request, "rotation_error" not in result, f"rotation failed: {result.get('rotation_error')!r}")
    _require(request, "error" not in result, f"writer errored: {result.get('error')}")
    _require(request, not t_writer.is_alive() and not t_rotate.is_alive(), "threads did not finish")
    outcome = result["outcome"]
    digests = outcome.receipt.predecessor_digests
    final = _store_bytes(gen1)
    _require(
        request,
        digests.get("evidence.jsonl") == hashlib.sha256(final["evidence.jsonl"] or b"").hexdigest(),
        "predecessor evidence digest does not bind generation 1's FINAL bytes",
    )
    landed = key in {line.get("idempotency_key") for line in _jsonl(gen1 / "evidence.jsonl")}
    _require(
        request,
        (result.get("landed") and landed) or ("fenced" in result and not landed),
        f"writer outcome {result} vs landed={landed}: a write after the digest",
    )
