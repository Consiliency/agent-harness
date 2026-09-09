"""Consiliency/agent-harness#789 Workstream D, Lane D1 — partition-rotation falsifiers.

RED-first falsifier module for
``plans/detailed-789d-fabpub-partition-rotation-20260908.md`` (anchors A0–A26).
Lane D1 is ``tests_only``: this module is NEW, ``_fabpub_tdd_guard.py`` is
untouched, and every helper is IMPORTED from its owning module (never copied),
following the Consiliency/agent-harness#800 precedent (``d79564d0``).

Two guard layers, stacked per test (``pytestmark`` is deliberately empty):

* ``_requires_fabpub`` — the FABPUB capability marker, exactly as every sibling
  FABPUB module.
* ``_requires_789d`` — Lane D2 has not landed.  A test under this mark runs when
  ``PHASE_LOOP_TDD_EXPECT_789D=1`` is exported (RED at its anchor today) or when
  the production symbol ``rotate_blocked_partition`` exists in ``live``.

Runnable-now controls (only ``_requires_fabpub``): A0 (derivation sweep), A16
and A21 (v2 baselines), A22 (fresh-authority-root laundering), the v2 halves of
A8 (archived-orphan shape)/A12/A14/A18/A24.  Everything else asserts the production symbol FIRST
(``_production``) so a missing D2 fails at a named ``789D-RED-ANCHOR::<name>``
line, never at an ``AttributeError`` deep in a helper.

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
* Lineage scope (plan D3): every enumerable predecessor key must carry the
  ``publish_committed_branch`` verb prefix; any other verb, and any
  non-terminal history (a dangling ``provider_call_in_flight`` intent, an
  unsealed adapter-start owner without a terminal) is a
  ``PartitionRotationRefused`` even when the attestation covers it.
* Dispositions (plan D3): ``observed_landed`` — the successor answers the key
  as a duplicate, NO provider call, no owner I/O; ``attested_not_landed`` —
  exactly one governed publish of the exact intended branch, then ordinary
  idempotency.  A COMPLETED predecessor terminal (``effect_terminal_observed``)
  is carried by ``promote_legacy_terminal`` minting for the ACTIVE store; a
  predecessor whose bytes drifted from the sealed digests refuses the carry.
* Attestation (plan D4; see ``_attestation``): schema, ``attested_by``,
  ``attested_at``, ``predecessor_generation``, ``predecessor_receipt_digest``,
  ``predecessor_store_digests`` (name → sha256), and per key ``disposition``,
  ``observed_head`` / ``branch_absent``, ``evidence_url``, ``ambiguity_digest``,
  and the attempt identity (``owner_nonce`` / ``transaction_id``) when an owner
  file names the key.  The successor receipt pins the attestation digest per key
  (``adjudicated_effect_dispositions[key]["attestation_digest"]``); an
  attestation bound to a spent attempt is refused on re-presentation.
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
* Refusal scope (plan D7 item 3): resolver-only states (``ACTIVE`` missing,
  torn, non-integer, naming a nonexistent or receipt-less generation, and
  ``generations`` present as a regular file) refuse routing for THAT partition
  while clean siblings still pass the barrier; only a symlink or an unreadable
  member refuses HOST-WIDE from ``_tree_file_inventory`` — a barrier over the
  clean siblings alone refuses too, exactly as v2 does today (A18).

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
import hashlib
import json
import os
import pathlib
import threading
import time
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
    _authority_preimage,
    _cutover_symbol,
    _git,
    _init_repo,
    _jsonl,
    _manifest_row,
    _publish_transaction_request,
    _seed_legacy_root,
    _service,
    _stage,
    _supported_contracts,
    _write_train,
)

pytestmark: list = []  # explicitly no module-level skip

LIVE_MODULE = "phase_loop_runtime.convergence.broker.live"
EVIDENCE_MODULE = "phase_loop_runtime.convergence.broker.evidence"
ADMISSION_MODULE = "phase_loop_runtime.convergence.broker.admission"
VERBS_MODULE = "phase_loop_runtime.convergence.broker.verbs"
PUBLISHING_MODULE = "phase_loop_runtime.publishing"

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
ROTATION_ID_2 = "rotation-789d-2"
#: The permanent block every successful rotation in this module carries: a
#: ``publish_committed_branch`` lineage key (plan D3 verb scope).  The
#: unprefixed ``BLOCKED_KEY`` of the sibling module is used ONLY where a
#: non-publish lineage must be REFUSED (A10).
ROTATED_KEY = "publish_committed_branch\x00ah789d-prior-ambiguous-publish"
EXPECTED_CRASH_STEPS = (
    "before_generations_rename",
    "after_generations_rename",
    "between_successor_files",
    "after_successor_receipt_before_flip",
    "after_journal_draining",
    "after_journal_inventory_sealed",
    "after_journal_armed",
)
#: Every file a generation store may hold.  ``_store_bytes`` snapshots all of
#: them so a predecessor mutation of ANY store file is visible (codex r1 finding 5).
STORE_FILES = (
    "admissions.jsonl",
    "evidence.jsonl",
    "admissions.lock",
    "partition-receipt.json",
    "adapter-start-owner.json",
    "legacy-promotions.jsonl",
)
#: The predecessor files a v3 receipt must digest (D4 binds the predecessor's
#: store bytes; the lock file is empty by construction and the promotions
#: ledger may be absent).
DIGESTED_FILES = ("admissions.jsonl", "evidence.jsonl", "partition-receipt.json", "adapter-start-owner.json")
#: Mandatory v3 receipt fields (plan D4/D5; A14c asserts them on the successor).
RECEIPT_V3_FIELDS = (
    "generation",
    "predecessor_generation",
    "predecessor_digests",
    "adjudicated_effect_dispositions",
    "rotation_cutover_id",
    "legacy_epoch_high_water",
)

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


def _sha256_bytes(data: bytes | None) -> str:
    return hashlib.sha256(data or b"").hexdigest()


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
        p.base = base
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


def _fresh_request(p, tag: str):
    """A NEW committed transaction on ``p.repo`` (branch ``feat/<tag>``) — the
    ``_partition`` idiom, so a fresh publish is never a replay of ``p.request``."""
    prepare = fabpub_symbol(PUBLISHING_MODULE, "prepare_publish_transaction")
    assert prepare is not None
    branch = f"feat/{tag}"
    _git(p.repo, "checkout", "-q", "-b", branch)
    _stage(p.repo, f"{tag}.py", f"{tag} = 1\n")
    transaction = prepare(
        p.repo,
        owned_paths=(f"{tag}.py",),
        checkpoint_root=p.base / "coordinator" / f"{p.label}-{tag}",
        branch=branch,
        envelope_authority_preimage=_authority_preimage(p.identity, branch),
    )
    transaction.resume()
    assert transaction.committed_head_sha == transaction.expected_commit_oid
    return _publish_transaction_request(p.identity, branch, transaction, p.repo)


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


def _complete_key(p, key: str) -> None:
    """A COMPLETED terminal under ``key`` (intent, then ``effect_terminal_observed``)."""
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    store = p.service.evidence_store
    store.record_intent(key)
    store.record_terminal(
        EvidenceRecord(key, TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, "ah789d-completed")
    )


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


def _active_store_root(p) -> Path:
    """The ACTIVE store root as the production resolver sees it (falls back to the
    container before D2 lands, so attestations can be built RED)."""
    live = _live()
    try:
        return live.repository_snapshot(p.repo).store_root
    except Exception:
        return p.container


def _owner_attempt_identity(store_root: Path, key: str) -> dict:
    """Attempt identity (owner nonce / transaction id) for ``key`` when the ACTIVE
    store's owner file names it (plan D4)."""
    path = store_root / "adapter-start-owner.json"
    if not path.exists():
        return {}
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    if owner.get("effect_key") == key or owner.get("idempotency_key") == key:
        return {
            "owner_nonce": owner.get("owner_nonce"),
            "transaction_id": owner.get("transaction_id"),
        }
    return {}


def _attestation(
    p,
    *,
    keys=None,
    dispositions=None,
    predecessor_generation=None,
    observed_head=None,
    store_root=None,
) -> dict:
    """Operator attestation covering every permanent block on ``p``'s ACTIVE store.

    Complete per plan D4: every entry names the observed head (or an explicit
    ``branch_absent``), the evidence URL, who and when; the whole attestation
    binds the predecessor receipt digest, the predecessor store digests and, when
    an owner file names the key, the attempt identity.  ``store_root`` overrides
    the resolved ACTIVE store (used to build an attestation against a
    predecessor after a later rotation moved the pointer).
    """
    store_root = Path(store_root) if store_root is not None else _active_store_root(p)
    evidence_path = store_root / "evidence.jsonl"
    if keys is None:
        keys = _blocked_keys(evidence_path)
    effects = {}
    for key in keys:
        disposition = (dispositions or {}).get(key, ATTESTED_NOT_LANDED)
        head = observed_head if disposition == OBSERVED_LANDED else None
        effects[key] = {
            "disposition": disposition,
            "observed_head": head,
            "branch_absent": disposition == ATTESTED_NOT_LANDED,
            "evidence_url": f"https://example.invalid/ah789d/{hashlib.sha256(key.encode()).hexdigest()[:12]}",
            "ambiguity_digest": _ambiguity_digest(evidence_path, key),
            **_owner_attempt_identity(store_root, key),
        }
    receipt_path = store_root / "partition-receipt.json"
    return {
        "schema": ATTESTATION_SCHEMA,
        "attested_by": "operator",
        "attested_at": "2026-09-09T00:00:00Z",
        "predecessor_generation": (
            _generation_of(p.container) if predecessor_generation is None else predecessor_generation
        ),
        "predecessor_receipt_digest": _sha256(receipt_path) if receipt_path.exists() else None,
        "predecessor_store_digests": {
            name: _sha256_bytes(_read_or_none(store_root / name)) for name in DIGESTED_FILES
        },
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


def _journal_path(p, cutover_id=ROTATION_ID) -> Path:
    return _ceremony_dir(p) / f"{cutover_id}.journal.jsonl"


def _journal_states(p, cutover_id=ROTATION_ID) -> list[str]:
    path = _journal_path(p, cutover_id)
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
        not _journal_path(p, cutover_id).exists()
        and not (_ceremony_dir(p) / f"{cutover_id}.inventory.json").exists(),
        f"a refused rotation left ceremony files under {_ceremony_dir(p)}",
    )


def _latch_bytes(p) -> bytes | None:
    """The repository-common writer latch file (``writer-generation.json``)."""
    return _read_or_none(_live().WriterGenerationLatch.for_store_root(p.container).path)


def _refusal_snapshot(p) -> dict:
    """Everything a REFUSED rotation must leave untouched: generation 0's bytes
    and the writer latch — a refusal may neither leave the latch DRAINING nor
    bump its generation (codex r3 finding 7).  Take it AFTER ``_release_all``."""
    return {"store": _store_bytes(p.container), "latch": _latch_bytes(p)}


def _assert_refused_without_writes(request, p, *, cutover_id=ROTATION_ID, before=None) -> None:
    """A refused rotation: no generation debris, no ceremony files, no store
    change, and the writer latch as it was (``before`` is a ``_refusal_snapshot``)."""
    _assert_no_durable_rotation(request, p, cutover_id=cutover_id)
    latch = _live().WriterGenerationLatch.for_store_root(p.container)
    _require(request, latch.read().generation_state != "DRAINING", "a refused rotation left the writer latch DRAINING")
    if before is not None:
        _require(request, _store_bytes(p.container) == before["store"], "the refusal changed generation 0")
        _require(request, _latch_bytes(p) == before["latch"], "the refusal changed the writer latch")


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


def _expect_routed_publish_refused(request, p, req, *, label: str) -> None:
    """The production route refuses ``req`` and the provider is never reached.

    The refusal may come from store construction — ``_stores_for`` revalidates
    the namespace latch (``live.py:3628``) and a latch a crashed ceremony left
    DRAINING refuses there with ``WriterGenerationBlocked`` — or from
    ``execute`` on the partition's own block.  Both are ``PermissionError``;
    neither may reach the adapter, and any lease the router acquired before
    refusing is released (codex r4 finding 3).
    """
    from phase_loop_runtime.convergence.broker.verbs import BrokerService

    live = _live()
    router = live._RepositoryRoutingBrokerService(
        admission_policy=lambda _request: True, run=None, allowed_hosts=()
    )
    adapter = _CountingAdapter()
    try:
        with pytest.raises(PermissionError):
            admission, evidence = router._stores_for(live.repository_snapshot(p.repo))
            BrokerService(
                admission, evidence, adapter, contracts=_supported_contracts("publish_committed_branch")
            ).execute(req)
        _require(request, adapter.calls == [], f"[{label}] the blocked partition reached the provider")
    finally:
        _release_router(SimpleNamespace(router=router))


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


def _publish_on_successor(request, outcome, p, req, *, adapter=None):
    """Execute ``req`` through a routed successor service; return (result, adapter calls).

    A typed ``PermissionError`` from the RESOLVER (``_stores_for``) is returned
    the same way as one from ``execute`` — a refused route is a refusal, not a
    test error (codex r2 finding 8); the router is released only when built.
    """
    adapter = adapter or _CountingAdapter()
    try:
        routed = _successor_service(request, outcome, p, adapter)
    except PermissionError as exc:
        return exc, list(adapter.calls)
    try:
        try:
            result = routed.service.execute(req)
        except PermissionError as exc:
            result = exc
        return result, list(adapter.calls)
    finally:
        _release_router(routed)


def _seed_owner(root: Path, p, key: str, *, sealed: bool = True) -> dict:
    """Write a VALID ``adapter-start-owner.json`` (every ``AdapterStartOwnership`` field)."""
    from phase_loop_runtime.convergence.broker.verbs import AdapterStartOwnership

    owner = AdapterStartOwnership(
        repository_identity=p.identity,
        idempotency_key=key,
        transaction_id="txn-789d-seeded",
        attempt_id="attempt-789d-seeded",
        committed_head=p.request.head_sha,
        adapter_operation="publish_committed_branch",
        owner_nonce="nonce-789d-seeded",
        effect_key=key,
        sealed=sealed,
    )
    body = json.dumps(owner.__dict__, sort_keys=True, separators=(",", ":")) + "\n"
    (root / "adapter-start-owner.json").write_text(body, encoding="utf-8")
    return dict(owner.__dict__)


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
    """The RESOLVER-ONLY refusal states (plan D7 item 3): name → mutator.

    Every mutator is reversible through ``_restore_pointer``; the
    ``generations_non_directory`` leg parks the real tree at
    ``generations.saved`` instead of deleting it (codex r1 finding 6).
    """
    pointer = _pointer(p)
    gens = p.container / GENERATIONS_DIR

    def missing():
        pointer.unlink()

    def torn():
        pointer.write_bytes(b"1\x00\x00")

    def non_integer():
        pointer.write_text("one\n", encoding="utf-8")

    def nonexistent_generation():
        pointer.write_text("42\n", encoding="utf-8")

    def receiptless_generation():
        target = gens / "7"
        target.mkdir(parents=True, exist_ok=True)
        (target / "admissions.lock").touch()
        pointer.write_text("7\n", encoding="utf-8")

    def generations_non_directory():
        gens.rename(p.container / f"{GENERATIONS_DIR}.saved")
        gens.write_text("0\n", encoding="utf-8")

    return {
        "missing": missing,
        "torn": torn,
        "non_integer": non_integer,
        "nonexistent_generation": nonexistent_generation,
        "receiptless_generation": receiptless_generation,
        "generations_non_directory": generations_non_directory,
    }


def _host_wide_states(p):
    """Pointer states the barrier must refuse HOST-WIDE (``_tree_file_inventory``):
    a symlink member only; the unreadable member is built by ``_unreadable``."""
    pointer = _pointer(p)

    def symlink():
        pointer.unlink()
        pointer.symlink_to(p.container / "partition-receipt.json")

    return {"symlink": symlink}


def _restore_pointer(p, saved: dict) -> None:
    gens = p.container / GENERATIONS_DIR
    parked = p.container / f"{GENERATIONS_DIR}.saved"
    if gens.exists() and not gens.is_dir():
        gens.unlink()
    if parked.is_dir() and not gens.exists():
        parked.rename(gens)
    stray = gens / "7"
    if stray.is_dir() and not (stray / "partition-receipt.json").exists():
        for child in stray.iterdir():
            child.unlink()
        stray.rmdir()
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
        on_disk = json.loads((p.container / "partition-receipt.json").read_text(encoding="utf-8")).get("schema")
        _require(request, on_disk == "LegacyRepositoryPartitionReceipt.v2", f"{p.label}: on-disk schema {on_disk!r}")
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
        _require(request, _barrier_admitted(report, fx.repos.values()), f"barrier did not admit every partition: {report.get('repositories')} deferred={report.get('deferred')}")
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
            not (second_root / ROTATION_CEREMONY_DIR).exists()
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
# A1–A10 — dispositions, carried terminals, refusals (D2-gated)
# ---------------------------------------------------------------------------


def _blocked_fixture(tmp_path, monkeypatch, labels=("alpha", "beta")):
    """Bootstrap + a permanent block on alpha under a publish-verb lineage key."""
    fx = _bootstrap(tmp_path, monkeypatch, labels=labels)
    _block_key(fx.alpha, ROTATED_KEY)
    fx.gen0 = _store_bytes(fx.alpha.container)
    return fx


def _owner_read_spy(monkeypatch):
    """Record every ``read_adapter_start_owner`` root through the seam
    ``BrokerService`` actually calls (``evidence_module.read_adapter_start_owner``)."""
    import phase_loop_runtime.convergence.broker.evidence as evidence_mod
    import phase_loop_runtime.convergence.broker.verbs as verbs

    reads: list = []
    real = evidence_mod.read_adapter_start_owner

    def _spy(root, *args, **kwargs):
        reads.append(Path(root))
        return real(root, *args, **kwargs)

    monkeypatch.setattr(evidence_mod, "read_adapter_start_owner", _spy)
    monkeypatch.setattr(verbs, "read_adapter_start_owner", _spy)
    return reads


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a1_observed_landed_is_answered_as_a_duplicate(tmp_path, monkeypatch, request):
    """A1: an ``observed_landed`` predecessor key is a DUPLICATE on the successor.

    The block is written under the REAL dedup key of ``p.request``; the
    attestation names the observed head.  After rotation: the pointer flips,
    a retry of that exact transaction is accepted WITHOUT a provider call and
    without any owner I/O, and a genuinely new transaction still publishes
    (exactly one provider call).  Generation 0 is byte-identical throughout.
    """
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    _block_key(p, carried_key)
    gen0 = _store_bytes(p.container)
    attestation = _attestation(
        p, dispositions={carried_key: OBSERVED_LANDED}, observed_head=p.request.head_sha
    )
    outcome = _rotate(request, p, attestation=attestation)
    _require(request, outcome.state == "ACTIVE", f"rotation state {outcome.state!r}")
    _require(request, outcome.generation == 1, f"successor generation {outcome.generation!r}")
    _require(
        request,
        outcome.store_root == p.container / GENERATIONS_DIR / "1",
        f"successor store root {outcome.store_root}",
    )
    _require(request, outcome.predecessor_store_root == p.container, "predecessor is the container")
    _require(request, _generation_of(p.container) == 1, "ACTIVE pointer did not flip to 1")
    recorded = outcome.receipt.adjudicated_effect_dispositions.get(carried_key)
    _require(request, recorded is not None, "the carried key is missing from the successor receipt")
    _require(request, recorded["disposition"] == OBSERVED_LANDED, f"disposition {recorded!r}")
    _require(request, recorded["observed_head"] == p.request.head_sha, f"observed head {recorded!r}")
    reads = _owner_read_spy(monkeypatch)
    result, calls = _publish_on_successor(request, outcome, p, p.request)
    _require(request, not isinstance(result, Exception), f"the duplicate was refused: {result!r}")
    _require(request, result.accepted is True, f"the duplicate was not accepted: {result.reason}")
    _require(request, calls == [], "an observed_landed key reached the provider")
    _require(request, reads == [], f"an observed_landed duplicate read an owner file: {reads}")
    _require(request, p.adapter.calls == [], "the generation-0 adapter must not have been reached")
    _require(
        request,
        not (outcome.store_root / "adapter-start-owner.json").exists(),
        "a duplicate answer created an owner file under the successor",
    )
    fresh = _fresh_request(p, "a1-fresh")
    result, calls = _publish_on_successor(request, outcome, p, fresh)
    _require(request, not isinstance(result, Exception) and result.accepted is True, f"fresh publish refused: {result!r}")
    _require(request, len(calls) == 1, f"fresh publish made {len(calls)} provider calls")
    _require(request, _store_bytes(p.container) == gen0, "generation-0 bytes changed after rotation")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a2_attested_not_landed_publishes_exactly_once(tmp_path, monkeypatch, request):
    """A2: an ``attested_not_landed`` key gets exactly ONE governed publish, then idempotency.

    The carried key is the real dedup key of ``p.request``; the successor
    performs one provider effect for it and answers the second attempt from its
    own evidence (same evidence reference, no second call).
    """
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    _block_key(p, carried_key)
    gen0 = _store_bytes(p.container)
    outcome = _rotate(request, p, attestation=_attestation(p, dispositions={carried_key: ATTESTED_NOT_LANDED}))
    recorded = outcome.receipt.adjudicated_effect_dispositions.get(carried_key)
    _require(request, recorded is not None and recorded["disposition"] == ATTESTED_NOT_LANDED, f"disposition {recorded!r}")
    routed = _successor_service(request, outcome, p)
    try:
        first = routed.service.execute(p.request)
        _require(request, first.accepted is True, f"attested_not_landed publish refused: {first.reason}")
        _require(request, len(routed.adapter.calls) == 1, f"{len(routed.adapter.calls)} provider calls for the first attempt")
        second = routed.service.execute(p.request)
        _require(request, second.accepted is True, f"second attempt refused: {second.reason}")
        _require(request, len(routed.adapter.calls) == 1, f"{len(routed.adapter.calls)} provider calls after the replay")
        _require(
            request,
            second.evidence.evidence_reference == first.evidence.evidence_reference,
            "the replay did not answer with the first attempt's evidence",
        )
    finally:
        _release_router(routed)
    _require(request, p.adapter.calls == [], "the generation-0 adapter must not have been reached")
    _require(request, _store_bytes(p.container) == gen0, "generation-0 bytes changed")
    _require(
        request,
        (outcome.store_root / "evidence.jsonl").exists() and (outcome.store_root / "admissions.jsonl").exists(),
        "the successor publish wrote nothing under the successor store",
    )
    # A second rotation: the consumed key is a generation-1 COMPLETED terminal and
    # generation 2 answers it with zero additional provider calls (codex r2 finding 6).
    routed = _successor_service(request, outcome, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah789d-a2-gen1-ambiguous")
    finally:
        _release_router(routed)
    second = _rotate(request, p, cutover_id=ROTATION_ID_2)
    _require(request, second.generation == 2, f"second rotation produced generation {second.generation}")
    result, calls = _publish_on_successor(request, second, p, p.request)
    _require(request, not isinstance(result, Exception) and result.accepted is True, f"generation 2 refused the consumed key: {result!r}")
    _require(request, calls == [], "a consumed attested_not_landed key reached the provider again on generation 2")
    _require(
        request,
        result.evidence.evidence_reference == first.evidence.evidence_reference,
        "generation 2 did not answer with the generation-1 publish's evidence",
    )
    _require(request, _store_bytes(p.container) == gen0, "generation-0 bytes changed across the second rotation")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a3_attestation_must_cover_every_blocked_key(tmp_path, monkeypatch, request):
    """A3: two publish-verb blocks — a partial attestation refuses before any durable write; full covers."""
    refused = _production(request, "PartitionRotationRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    second = "publish_committed_branch\x00ah789d-second-ambiguous-publish"
    _block_key(p, second)
    _release_all(p)
    before = _refusal_snapshot(p)
    keys = _blocked_keys(p.evidence)
    _require(request, set(keys) == {ROTATED_KEY, second}, f"blocks {keys}")
    with pytest.raises(refused):
        _rotate(request, p, attestation=_attestation(p, keys=[ROTATED_KEY]))
    _assert_refused_without_writes(request, p, before=before)
    outcome = _rotate(request, p, attestation=_attestation(p, keys=keys))
    dispositions = outcome.receipt.adjudicated_effect_dispositions
    _require(request, set(dispositions) == {ROTATED_KEY, second}, f"dispositions {sorted(dispositions)}")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a4_predecessor_bytes_are_sealed_and_drift_refuses_the_carry(tmp_path, monkeypatch, request):
    """A4: the successor answers a carried key from SEALED predecessor bytes.

    Generation 0 carries a valid sealed owner file; the receipt digests every
    predecessor store file including it; a carried replay never writes
    generation 0; and a foreign append to generation 0's evidence AFTER the
    rotation makes the next carried answer refuse (no provider call).
    """
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    _block_key(p, carried_key)
    _release_all(p)
    _seed_owner(p.container, p, carried_key, sealed=True)
    gen0 = _store_bytes(p.container)
    outcome = _rotate(
        request, p, attestation=_attestation(p, dispositions={carried_key: OBSERVED_LANDED}, observed_head=p.request.head_sha)
    )
    digests = outcome.receipt.predecessor_digests
    for name in DIGESTED_FILES:
        _require(
            request,
            digests.get(name) == _sha256_bytes(gen0[name]),
            f"receipt digest for {name} does not bind generation 0's sealed bytes",
        )
    result, calls = _publish_on_successor(request, outcome, p, p.request)
    _require(request, not isinstance(result, Exception) and result.accepted is True, f"carried answer refused: {result!r}")
    _require(request, calls == [], "a carried key reached the provider")
    _require(request, _store_bytes(p.container) == gen0, "a carried replay wrote generation 0")
    # Drift generation 0 behind the seal: the carry must refuse, never re-run.
    with (p.container / "evidence.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"idempotency_key": carried_key, "state": "provider_call_in_flight", "evidence_reference": "drift"}) + "\n")
    result, calls = _publish_on_successor(request, outcome, p, p.request)
    _require(request, isinstance(result, PermissionError), f"a drifted predecessor was still answered: {result!r}")
    _require(request, calls == [], "a drifted predecessor key reached the provider")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a5_owner_file_semantics_across_the_rotation(tmp_path, monkeypatch, request):
    """A5: no owner I/O for an ``observed_landed`` answer; an ``attested_not_landed``
    attempt that crashed after its owner + intent refuses the next attempt.

    Generation 0 carries TWO blocked keys: ``p.request``'s (``observed_landed``,
    with an unsealed owner naming it) and a second transaction's
    (``attested_not_landed``).  The successor never carries or copies generation
    0's owner file; the ``observed_landed`` answer does no owner I/O; the
    ``attested_not_landed`` key's first successor attempt crashes at
    ``after_broker_intent_before_adapter_started``, leaves an unsealed owner on
    the SUCCESSOR, and the retry is a typed ``unsealed adapter-start owner``
    refusal with no provider call (codex r2 finding 4: the crashed attempt is the
    ADJUDICATED key, not an unrelated fresh publish).
    """
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    fresh = _fresh_request(p, "a5-anl")
    anl_key = p.service._dedup_key(fresh)
    assert anl_key != carried_key
    _block_key(p, carried_key)
    _block_key(p, anl_key)
    _release_all(p)
    _seed_owner(p.container, p, carried_key, sealed=False)
    gen0 = _store_bytes(p.container)
    outcome = _rotate(
        request,
        p,
        attestation=_attestation(
            p,
            dispositions={carried_key: OBSERVED_LANDED, anl_key: ATTESTED_NOT_LANDED},
            observed_head=p.request.head_sha,
        ),
    )
    _require(request, not (outcome.store_root / "adapter-start-owner.json").exists(), "owner file copied to the successor")
    reads = _owner_read_spy(monkeypatch)
    result, calls = _publish_on_successor(request, outcome, p, p.request)
    _require(request, not isinstance(result, Exception) and result.accepted is True, f"duplicate refused: {result!r}")
    _require(request, calls == [] and reads == [], f"observed_landed answer did owner I/O: reads={reads} calls={calls}")
    # attested_not_landed: the adjudicated key's first successor attempt crashes
    # after owner + intent.
    publishing = __import__(PUBLISHING_MODULE, fromlist=["crash_after", "PublishCrashInjected"])
    routed = _successor_service(request, outcome, p)
    try:
        with publishing.crash_after("after_broker_intent_before_adapter_started"):
            with pytest.raises(publishing.PublishCrashInjected):
                routed.service.execute(fresh)
        _require(request, routed.adapter.calls == [], "the crashed attempt reached the provider")
        owner_path = outcome.store_root / "adapter-start-owner.json"
        _require(request, owner_path.exists(), "the crashed attempt left no owner on the successor")
        _require(
            request,
            _owner_attempt_identity(outcome.store_root, anl_key) != {},
            "the successor owner does not name the attested_not_landed key",
        )
        with pytest.raises(PermissionError) as info:
            routed.service.execute(fresh)
        _require(request, "unsealed adapter-start owner" in str(info.value), f"refusal {info.value!r}")
        _require(request, routed.adapter.calls == [], "the retry behind an unsealed owner reached the provider")
    finally:
        _release_router(routed)
    _require(request, _store_bytes(p.container) == gen0, "generation 0 changed")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a6_completed_predecessor_terminals_are_carried_by_minting(tmp_path, monkeypatch, request):
    """A6: a COMPLETED generation-0 terminal is answered on every later generation via
    ``promote_legacy_terminal`` minting for the ACTIVE store — never re-run.

    A real publish lands on generation 0; the partition is then blocked under a
    different key and rotated.  The successor answers the completed key as
    ``effect_terminal_observed`` with zero provider calls, the mint is for the
    SUCCESSOR root, and generation 0 is untouched.  A second rotation still
    answers through the mint AND still answers a generation-0 ``observed_landed``
    disposition that was never replayed on generation 1 (codex r2 finding 6);
    a drifted predecessor refuses.
    """
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    landed = p.service.execute(p.request)
    _require(request, landed.accepted is True and len(p.adapter.calls) == 1, "generation-0 publish did not land")
    unreplayed = _fresh_request(p, "a6-observed")
    unreplayed_key = p.service._dedup_key(unreplayed)
    _block_key(p, ROTATED_KEY)
    _block_key(p, unreplayed_key)
    gen0 = _store_bytes(p.container)
    minted: list = []
    real = live._mint_cutover_promotion_capability

    def _spy(root, key, *args, **kwargs):
        minted.append((Path(root), key))
        return real(root, key, *args, **kwargs)

    monkeypatch.setattr(live, "_mint_cutover_promotion_capability", _spy)
    outcome = _rotate(
        request,
        p,
        attestation=_attestation(
            p,
            dispositions={ROTATED_KEY: ATTESTED_NOT_LANDED, unreplayed_key: OBSERVED_LANDED},
            observed_head=unreplayed.head_sha,
        ),
    )
    result, calls = _publish_on_successor(request, outcome, p, p.request)
    _require(request, not isinstance(result, Exception), f"the carried terminal was refused: {result!r}")
    _require(request, result.accepted is True, f"carried terminal not accepted: {result.reason}")
    _require(request, result.evidence.terminal_state == "effect_terminal_observed", f"state {result.evidence.terminal_state!r}")
    _require(request, calls == [], "a completed predecessor terminal reached the provider")
    _require(request, minted and minted[-1] == (outcome.store_root, carried_key), f"minted for {minted}")
    _require(request, _store_bytes(p.container) == gen0, "the carry wrote generation 0")
    # Chain: block generation 1, rotate again, generation 2 still answers via the mint.
    routed = _successor_service(request, outcome, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah789d-gen1-ambiguous")
    finally:
        _release_router(routed)
    second = _rotate(request, p, cutover_id=ROTATION_ID_2)
    minted.clear()
    result, calls = _publish_on_successor(request, second, p, p.request)
    _require(request, not isinstance(result, Exception) and result.accepted is True, f"generation 2 refused the carry: {result!r}")
    _require(request, calls == [] and minted and minted[-1][0] == second.store_root, f"generation-2 carry: calls={calls} minted={minted}")
    # The generation-0 observed_landed disposition was never replayed on
    # generation 1; generation 2 still answers it as a duplicate with no call.
    result, calls = _publish_on_successor(request, second, p, unreplayed)
    _require(request, not isinstance(result, Exception) and result.accepted is True, f"generation 2 refused the unreplayed observed_landed key: {result!r}")
    _require(request, calls == [], "an unreplayed observed_landed key reached the provider on generation 2")
    _require(request, _store_bytes(p.container) == gen0, "generation 0 changed across the second rotation")
    # A drifted predecessor refuses the carry (no provider call).
    with (p.container / "evidence.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    result, calls = _publish_on_successor(request, second, p, p.request)
    _require(request, isinstance(result, PermissionError), f"drifted predecessor still answered: {result!r}")
    _require(request, calls == [], "a drifted predecessor key reached the provider")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a7_attestation_binds_attempt_identity_and_is_single_use(tmp_path, monkeypatch, request):
    """A7: the attestation binds the predecessor's receipt, store bytes and ATTEMPT
    identity; the successor pins its digest; a spent attestation refuses.

    Generation 0 is blocked under the real dedup key of ``p.request`` with a
    sealed owner (``nonce-789d-seeded`` / ``txn-789d-seeded``).  After the
    rotation the SAME key is driven to a fresh ambiguity on generation 1 through
    the real owner machinery: the attested-not-landed publish crashes at
    ``after_broker_intent_before_adapter_started`` and leaves an unsealed owner
    with a NEW ``owner_nonce`` / ``transaction_id``; the ambiguity is then
    recorded.  Re-presenting A (verbatim, or with only the generation bumped)
    refuses; a fresh attestation that names the key but carries generation 0's
    SPENT identity refuses too — an implementation that matched on the key alone
    would accept it (fable r2 finding 4); so does a fresh attestation with any
    ONE other bound field corrupted (owner nonce, transaction id, predecessor
    receipt digest, one predecessor store digest, ambiguity digest); only a
    fresh attestation naming the new attempt produces generation 2.
    """
    refused = _production(request, "PartitionRotationRefused")
    publishing = __import__(PUBLISHING_MODULE, fromlist=["crash_after", "PublishCrashInjected"])
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    key = p.service._dedup_key(p.request)
    _block_key(p, key)
    _release_all(p)
    _seed_owner(p.container, p, key, sealed=True)
    gen0 = _store_bytes(p.container)
    attestation = _attestation(p)
    entry = attestation["effects"][key]
    _require(request, entry.get("owner_nonce") == "nonce-789d-seeded", "attestation did not bind the owner nonce")
    _require(request, entry.get("transaction_id") == "txn-789d-seeded", "attestation did not bind the transaction id")
    _require(request, attestation["predecessor_receipt_digest"] == _sha256(p.container / "partition-receipt.json"), "receipt digest")
    digest = _attestation_digest(attestation)
    outcome = _rotate(request, p, attestation=attestation)
    recorded = outcome.receipt.adjudicated_effect_dispositions[key]["attestation_digest"]
    _require(request, recorded == digest, f"recorded digest {recorded} != {digest}")
    _require(request, _store_bytes(p.container) == gen0, "the rotation changed generation 0")
    # The same key reaches a FRESH ambiguity on generation 1 through the real
    # owner machinery (attested_not_landed ⇒ the successor runs the publish).
    routed = _successor_service(request, outcome, p)
    try:
        with publishing.crash_after("after_broker_intent_before_adapter_started"):
            with pytest.raises(publishing.PublishCrashInjected):
                routed.service.execute(p.request)
        _require(request, routed.adapter.calls == [], "the crashed attempt reached the provider")
        with pytest.raises(PermissionError) as info:
            routed.service.execute(p.request)
        _require(request, "unsealed adapter-start owner" in str(info.value), f"retry refusal {info.value!r}")
        _require(request, routed.adapter.calls == [], "the retry behind the unsealed owner reached the provider")
        _block_key(SimpleNamespace(service=routed.service), key)
    finally:
        _release_router(routed)
    seeded = {"owner_nonce": "nonce-789d-seeded", "transaction_id": "txn-789d-seeded"}
    new_identity = _owner_attempt_identity(outcome.store_root, key)
    _require(
        request,
        new_identity.get("owner_nonce") and new_identity.get("transaction_id") and new_identity != seeded,
        f"generation 1 owner identity {new_identity!r} (generation 0 seeded {seeded!r})",
    )
    gen1 = _store_bytes(outcome.store_root)

    def _refuses(label: str, candidate: dict) -> None:
        with pytest.raises(refused):
            _rotate(request, p, cutover_id=ROTATION_ID_2, attestation=candidate)
        _require(request, _generation_of(p.container) == 1, f"[{label}] a refused attestation moved the pointer")
        _require(request, _store_bytes(outcome.store_root) == gen1, f"[{label}] a refused re-rotation changed generation 1")
        _require(request, not (p.container / GENERATIONS_DIR / "2").exists(), f"[{label}] a refused re-rotation created generation 2")

    _refuses("verbatim", attestation)
    _refuses("generation-bumped", dict(attestation, predecessor_generation=1))
    _refuses("future-generation", _attestation(p, predecessor_generation=3))
    spent = _attestation(p)
    _require(
        request,
        spent["effects"][key].get("owner_nonce") == new_identity["owner_nonce"],
        "a fresh attestation did not bind generation 1's owner nonce",
    )
    spent["effects"][key].update(seeded)
    _refuses("spent-identity", spent)

    # Every OTHER bound field, corrupted alone in an otherwise fresh and valid
    # attestation, refuses too (codex r3 finding 3): the attestation binds each
    # field it carries, not only the attempt identity.
    def _fresh_with(mutate) -> dict:
        candidate = json.loads(json.dumps(_attestation(p)))
        mutate(candidate)
        return candidate

    forged = "0" * 64
    _refuses("owner-nonce", _fresh_with(lambda a: a["effects"][key].update(owner_nonce="nonce-789d-forged")))
    _refuses("transaction-id", _fresh_with(lambda a: a["effects"][key].update(transaction_id="txn-789d-forged")))
    _refuses("receipt-digest", _fresh_with(lambda a: a.update(predecessor_receipt_digest=forged)))
    _refuses("store-digest", _fresh_with(lambda a: a["predecessor_store_digests"].update({"evidence.jsonl": forged})))
    _refuses("ambiguity-digest", _fresh_with(lambda a: a["effects"][key].update(ambiguity_digest=forged)))
    second = _rotate(request, p, cutover_id=ROTATION_ID_2, attestation=_attestation(p))
    _require(request, second.generation == 2, f"fresh attestation produced generation {second.generation}")
    _require(
        request,
        second.receipt.adjudicated_effect_dispositions[key]["attestation_digest"] != digest,
        "generation 2 pinned the spent attestation digest",
    )


def _mark_receipt_ambiguous(live, p) -> None:
    """Make ``p``'s ON-DISK receipt say ``ambiguous: true`` the way production
    seals it: the sealed cutover inventory's partition entry is flipped, the
    partition-map and inventory digests are recomputed with the production
    helpers, and the receipt bytes are regenerated from the sealed partition so
    ``load_partition_receipt`` still authenticates the chain end to end.
    """
    receipt = live.load_partition_receipt(p.container)
    assert receipt is not None and receipt.ambiguous is False
    journal = Path(receipt.global_journal_path)
    inventory_path = journal.parent / f"{receipt.cutover_id}.inventory.json"
    sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
    partition = sealed["partitions"][p.identity]
    partition["ambiguous"] = True
    sealed["partition_map_sha256"] = live._partition_map_digest(sealed["partitions"])
    sealed["inventory_sha256"] = live._inventory_digest(sealed)
    inventory_path.write_text(json.dumps(sealed, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    expected = live._receipt_from_partition(receipt.cutover_id, partition, sealed, journal)
    (p.container / "partition-receipt.json").write_bytes(expected.file_bytes(partition.get("zero_source_proof")))
    reloaded = live.load_partition_receipt(p.container)
    assert reloaded is not None and reloaded.ambiguous is True
    assert live._receipt_bootstrap_claim(reloaded) is not None, "the bootstrap claim did not survive"


def _traditional_partition_with_archived_orphan(tmp_path: Path) -> SimpleNamespace:
    """A TRADITIONAL v2 partition whose legacy root archived a lone
    ``provider_call_in_flight`` — the real cutover classifies the orphan as
    ambiguous (``live.py`` ``_classify_legacy_evidence``: an orphaned in-flight
    is an unknown effect) and the receipt carries ``ambiguous: true``.
    """
    repo = _init_repo(tmp_path / "orphaned")
    ledger = tmp_path / "legacy-orphaned"
    train = _write_train(tmp_path / "train-orphaned" / "release.md", str(repo))
    seeded = _seed_legacy_root(ledger, train_path=train, serialized_repo=str(repo), epochs=(1, 2))
    orphan = {
        "idempotency_key": "publish_committed_branch\x00ah789d-archived-orphan",
        "state": "provider_call_in_flight",
        "evidence_reference": "",
    }
    seeded["evidence"].write_text(json.dumps(orphan, sort_keys=True) + "\n", encoding="utf-8")
    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    transaction = _cutover_symbol("run_legacy_broker_cutover")(
        manifest_cls(
            cutover_id="fabpub-789d-orphaned",
            rows=(_manifest_row(ledger, train, repo, str(repo), tmp_path),),
        )
    )
    assert transaction.state == "ARMED"
    transaction.activate()
    assert transaction.state == "ACTIVE"
    identity = _cutover_symbol("canonical_repository_identity")(repo)
    root = Path(_cutover_symbol("repository_broker_namespace")(repo))
    return SimpleNamespace(
        label="orphaned",
        repo=repo,
        identity=identity,
        container=root,
        authority=Path(os.environ["PHASE_LOOP_FABPUB_AUTHORITY_ROOT"]),
        store=None,
        service=None,
    )


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a8_non_terminal_history_refuses_even_when_attested(tmp_path, monkeypatch, request):
    """A8: rotation needs a fully terminal predecessor — (i) an ambiguous RECEIPT
    on disk, (ii) a dangling ``provider_call_in_flight`` intent, (iii) an
    unsealed owner without a terminal — each refuses with no durable write,
    even when the attestation names every canonical key.

    (i-a) is the plan's literal shape (``ambiguous: true`` with EMPTY canonical
    evidence, attestation with no effects): the only block is the receipt's,
    and it cannot be attested away.  (i-b) adds a canonical block under
    ``ROTATED_KEY`` to the same receipt shape and attests THAT key: a D2 that
    read ambiguity from canonical rows only (m10) would find the one block
    attested and rotate — so (i-b) is the m10 discriminator, (i-a) the plan
    text.  Both receipts are regenerated on disk with the production digest
    helpers, so the receipt still authenticates and still carries its
    bootstrap claim (fable r2 finding 5): a rotation that reads it through any
    seam sees the same ``ambiguous: true``.  The ARCHIVED orphaned in-flight
    shape is only constructible on a TRADITIONAL partition, which A25 refuses
    on the authority axis before any inventory runs; it is witnessed on disk by
    the ungated ``test_partition_rotation_a8_v2_archived_orphan_is_receipt_ambiguity_today``
    and is NOT counted as m10 coverage (grok r3 / fable r3 finding 2).
    """
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    # (i-a) plan-literal: receipt ambiguity, empty canonical evidence, no effects to attest.
    fx = _bootstrap(tmp_path / "receipt", monkeypatch)
    p = fx.alpha
    _release_all(p)
    _mark_receipt_ambiguous(live, p)
    _require(request, live.partition_is_ambiguity_blocked(p.container) is True, "receipt ambiguity not seen by production")
    _require(request, _blocked_keys(p.evidence) == [], f"canonical evidence is not empty: {_blocked_keys(p.evidence)}")
    before = _refusal_snapshot(p)
    with pytest.raises(refused):
        _rotate(request, p, attestation=_attestation(p, keys=[]))
    _assert_refused_without_writes(request, p, before=before)
    # (i-b) the same receipt shape with one canonical block, attested: still refused.
    fx = _blocked_fixture(tmp_path / "receipt-and-key", monkeypatch)
    p = fx.alpha
    _release_all(p)
    _mark_receipt_ambiguous(live, p)
    _require(request, _blocked_keys(p.evidence) == [ROTATED_KEY], f"blocks {_blocked_keys(p.evidence)}")
    before = _refusal_snapshot(p)
    with pytest.raises(refused):
        _rotate(request, p, attestation=_attestation(p, keys=[ROTATED_KEY]))
    _assert_refused_without_writes(request, p, before=before)
    # (ii) a dangling intent: attesting it does not make it terminal.
    fx = _blocked_fixture(tmp_path / "intent", monkeypatch)
    p = fx.alpha
    orphan = "publish_committed_branch\x00ah789d-orphan-intent"
    p.service.evidence_store.record_intent(orphan)
    _release_all(p)
    before = _refusal_snapshot(p)
    attestation = _attestation(p, keys=[ROTATED_KEY])
    attestation["effects"][orphan] = {
        "disposition": ATTESTED_NOT_LANDED,
        "observed_head": None,
        "branch_absent": True,
        "evidence_url": "https://example.invalid/ah789d/orphan",
        "ambiguity_digest": None,
    }
    with pytest.raises(refused):
        _rotate(request, p, attestation=attestation)
    _assert_refused_without_writes(request, p, before=before)
    # (iii) an unsealed owner without a terminal.
    fx2 = _blocked_fixture(tmp_path / "owner", monkeypatch)
    q = fx2.alpha
    _release_all(q)
    _seed_owner(q.container, q, "publish_committed_branch\x00ah789d-unsealed-owner", sealed=False)
    before = _refusal_snapshot(q)
    with pytest.raises(refused):
        _rotate(request, q, attestation=_attestation(q))
    _assert_refused_without_writes(request, q, before=before)


@_requires_fabpub
def test_partition_rotation_a8_v2_archived_orphan_is_receipt_ambiguity_today(tmp_path, request):
    """Ungated control for A8's archived shape: on v2 today a TRADITIONAL
    partition whose legacy root archived a lone ``provider_call_in_flight``
    carries ``ambiguous: true`` in its receipt with EMPTY canonical evidence —
    the ambiguity lives only in the receipt (and the archived history), never
    in a canonical row.  Under the generational design this partition is
    refused by A25 (authority axis) before any inventory runs, so it is a
    witness of the shape, not an m10 discriminator (grok r3 / fable r3
    finding 2).
    """
    live = _live()
    r = _traditional_partition_with_archived_orphan(tmp_path)
    receipt = live.load_partition_receipt(r.container)
    _require(request, receipt is not None and receipt.ambiguous is True, f"archived-orphan receipt {receipt!r}")
    _require(request, receipt.zero_source is False, "the archived-orphan partition is not traditional")
    _require(request, live.partition_is_ambiguity_blocked(r.container) is True, "receipt ambiguity not seen by production")
    _require(request, _blocked_keys(r.container / "evidence.jsonl") == [], "the archived orphan reached a canonical row")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a9_unblocked_partition_refuses_rotation(tmp_path, monkeypatch, request):
    """A9: rotation is for permanently blocked partitions only — typed refusal, no
    writes, and the partition keeps publishing afterwards."""
    fx = _bootstrap(tmp_path, monkeypatch)
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    p = fx.beta
    _release_all(*fx.partitions.values())
    before = _refusal_snapshot(p)
    with pytest.raises(refused) as info:
        _rotate(request, p, attestation=_attestation(p, keys=[]))
    _require(request, not isinstance(info.value, live.LegacyCutoverConflict), "must not be a LegacyCutoverConflict")
    _assert_refused_without_writes(request, p, before=before)
    # The refused partition is still a live generation 0: it publishes through
    # the production route (the latch was not left DRAINING — codex r3 finding 7).
    routed = _routed_service(p)
    try:
        result = routed.service.execute(p.request)
        _require(request, result.accepted is True, f"publish refused after a refused rotation: {result.reason}")
        _require(request, len(routed.adapter.calls) == 1, "one adapter call expected")
    finally:
        _release_router(routed)


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a10_non_publish_lineage_refuses_rotation(tmp_path, monkeypatch, request):
    """A10: any predecessor key WITHOUT the ``publish_committed_branch`` prefix refuses
    the rotation (plan D3) — even when the attestation covers it, and even when
    the key is a COMPLETED terminal that needs no attestation — with no durable
    write; the sibling module's unprefixed block and a ``refresh_pull_request``
    key (blocked, or completed) are all such lineages.
    """
    refused = _production(request, "PartitionRotationRefused")
    for label, key, completed in (
        ("unprefixed", BLOCKED_KEY, False),
        ("other-verb", "refresh_pull_request\x00abc", False),
        ("completed-other-verb", "refresh_pull_request\x00done", True),
    ):
        fx = _bootstrap(tmp_path / label, monkeypatch)
        p = fx.alpha
        if completed:
            # A COMPLETED non-publish terminal: not blocked, so the attestation
            # over the blocked keys is complete — the lineage still refuses
            # (codex r3 finding 5: a blocked-keys-only verb scan misses it).
            _complete_key(p, key)
        _block_key(p, ROTATED_KEY)
        if completed:
            pass
        elif key == BLOCKED_KEY:
            _block_partition(p.service)
        else:
            _block_key(p, key)
        _release_all(p)
        keys = _blocked_keys(p.evidence)
        expected = {ROTATED_KEY} if completed else {ROTATED_KEY, key}
        _require(request, set(keys) == expected, f"[{label}] blocks {keys}")
        before = _refusal_snapshot(p)
        with pytest.raises(refused):
            _rotate(request, p, attestation=_attestation(p, keys=keys))
        _assert_refused_without_writes(request, p, before=before)
        _require(request, _generation_of(p.container) == 0, f"[{label}] a refused rotation moved the pointer")


# ---------------------------------------------------------------------------
# A11–A15 — crash sweep, chaining, pointer resolver, debris, pre-v3 readers
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
    """Post-crash invariant: generation 0 resolves, refuses a publish, refuses onboarding.

    The publish refusal is accepted at either production stage (store
    construction on a DRAINING latch, or ``execute`` on the block); the
    resolver and the bytes are checked independently of it.
    """
    live = _live()
    snapshot = live.repository_snapshot(p.repo)
    _require(request, snapshot.store_root == p.container, f"[{step}] pointer left generation 0 unroutable")
    _expect_routed_publish_refused(request, p, p.request, label=step)
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
        result, calls = _publish_on_successor(request, outcome, p, p.request)
        _require(request, not isinstance(result, Exception) and result.accepted is True, f"[{step}] successor publish refused: {result!r}")
        _require(request, len(calls) == 1, f"[{step}] {len(calls)} provider calls")
        _require(request, _store_bytes(p.container) == fx.gen0, f"[{step}] generation-0 bytes changed on resume")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a12_pointer_refusal_states_are_typed_and_final(tmp_path, monkeypatch, request):
    """A12: each pointer refusal state → ``PartitionRoutingRefused`` everywhere, no fallback.

    Resolver-only states (including ``generations`` as a regular file) are
    asserted at ``repository_snapshot().store_root``, at ``_stores_for`` and
    through ``onboard_zero_legacy_repository`` (no onboarding fallback).  The
    host-wide states (symlink, unreadable) are refused at the resolver too —
    but onboarding runs the pre-existing bootstrap inventory walk BEFORE any
    resolver (``_active_bootstrap_inventory``, then
    ``_onboard_zero_legacy_repository_under_seal``), so for those two members
    onboarding refuses from ``_tree_file_inventory`` with the walk's own
    ``LegacyCutoverConflict`` / ``OSError`` (plan D7: the resolver's refusal
    "is reachable only when the walk is not on the path").  A leg without a
    construction is a failure, not a skip.  Also: after an
    ``after_generations_rename`` crash the pointer reads ``0``; after a clean
    rotation no ``ACTIVE`` temp file remains.
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

    def _resolver_refuses(name: str) -> None:
        with pytest.raises(routing_refused):
            _ = live.repository_snapshot(p.repo).store_root
        router = live._RepositoryRoutingBrokerService(admission_policy=lambda _r: True, run=None, allowed_hosts=())
        with pytest.raises(routing_refused):
            router._stores_for(live.repository_snapshot(p.repo))
        _release_router(SimpleNamespace(router=router))

    def _onboarding_refuses_in_walk(name: str) -> None:
        with pytest.raises((live.LegacyCutoverConflict, OSError)) as excinfo:
            live.onboard_zero_legacy_repository(p.repo, authority_root=p.authority)
        _require(request, _raised_inside(excinfo.value, "_tree_file_inventory"), f"[{name}] onboarding refused outside the host-wide walk: {excinfo.value!r}")

    for name, mutate in _pointer_states(p).items():
        _restore_pointer(p, saved)
        mutate()
        _resolver_refuses(name)
        with pytest.raises(routing_refused):
            live.onboard_zero_legacy_repository(p.repo, authority_root=p.authority)
        _require(request, not (p.container / GENERATIONS_DIR / "2").exists(), f"[{name}] a refusal created a generation")
    for name, mutate in _host_wide_states(p).items():
        _restore_pointer(p, saved)
        mutate()
        _resolver_refuses(name)
        _onboarding_refuses_in_walk(name)
        _require(request, not (p.container / GENERATIONS_DIR / "2").exists(), f"[{name}] a refusal created a generation")
    _restore_pointer(p, saved)
    with _unreadable(monkeypatch, _pointer(p)):
        _resolver_refuses("unreadable")
        _onboarding_refuses_in_walk("unreadable")
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
def test_partition_rotation_a13_second_rotation_chains_generations(tmp_path, monkeypatch, request):
    """A13: rotating a blocked generation 1 yields generation 2 with generation 1 as predecessor.

    Crash steps are swept for the 1→2 rotation; after every crash the pointer
    still names generation 1 (which routes and refuses on ITS block); the
    successor's ``predecessor_generation`` and digests bind generation 1's
    final bytes; a different-id ceremony refuses an existing unowned
    ``generations/2``; and a completed generation-0 terminal is still answered
    on generation 2 through the mint (floor never drops).
    """
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    steps = _crash_steps(request)
    gen1_key = "publish_committed_branch\x00ah789d-gen1-ambiguous"
    for step in ("clean",) + steps:
        fx = _bootstrap(tmp_path / step, monkeypatch)
        p = fx.alpha
        carried_key = p.service._dedup_key(p.request)
        landed = p.service.execute(p.request)
        _require(request, landed.accepted is True, f"[{step}] generation-0 publish did not land")
        _block_key(p, ROTATED_KEY)
        gen0 = _store_bytes(p.container)
        first = _rotate(request, p)
        floor1 = live.authenticated_partition_floor(first.store_root)
        routed = _successor_service(request, first, p)
        try:
            _block_key(SimpleNamespace(service=routed.service), gen1_key)
        finally:
            _release_router(routed)
        gen1_bytes = _store_bytes(first.store_root)
        if step != "clean":
            _crash_rotation(request, p, step, cutover_id=ROTATION_ID_2)
            _require(request, _generation_of(p.container) == 1, f"[{step}] crash moved the pointer off 1")
            _require(request, live.repository_snapshot(p.repo).store_root == first.store_root, f"[{step}] post-crash routing is not generation 1")
            _expect_routed_publish_refused(request, p, _fresh_request(p, f"a13-{step}"), label=step)
            _require(request, _store_bytes(first.store_root) == gen1_bytes, f"[{step}] generation-1 bytes changed across the crash")
        second = _rotate(request, p, cutover_id=ROTATION_ID_2)
        _require(request, second.generation == 2, f"[{step}] second rotation generation {second.generation}")
        _require(request, second.predecessor_store_root == first.store_root, f"[{step}] predecessor is not generation 1")
        _require(request, second.receipt.predecessor_generation == 1, f"[{step}] predecessor_generation != 1")
        digests = second.receipt.predecessor_digests
        for name in DIGESTED_FILES:
            _require(
                request,
                digests.get(name) == _sha256_bytes(gen1_bytes[name]),
                f"[{step}] predecessor digest for {name} does not bind generation 1's final bytes",
            )
        _require(request, _store_bytes(first.store_root) == gen1_bytes, f"[{step}] generation 1 changed")
        _require(request, _store_bytes(p.container) == gen0, f"[{step}] generation 0 changed")
        _require(request, live.authenticated_partition_floor(second.store_root) >= floor1, f"[{step}] floor dropped on generation 2")
        result, calls = _publish_on_successor(request, second, p, p.request)
        _require(request, not isinstance(result, Exception) and result.accepted is True, f"[{step}] generation 2 refused the carried terminal: {result!r}")
        _require(request, result.evidence.terminal_state == "effect_terminal_observed" and calls == [], f"[{step}] carried terminal re-ran: {calls}")
        _require(request, carried_key not in _blocked_keys(second.store_root / "evidence.jsonl"), f"[{step}] the carried key was re-blocked")
    # A different cutover id must not adopt an existing, unowned generations/2.
    fx = _blocked_fixture(tmp_path / "unowned", monkeypatch)
    p = fx.alpha
    first = _rotate(request, p)
    routed = _successor_service(request, first, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), gen1_key)
    finally:
        _release_router(routed)
    stray = p.container / GENERATIONS_DIR / "2"
    stray.mkdir()
    (stray / "admissions.lock").touch()
    with pytest.raises(refused):
        _rotate(request, p, cutover_id="rotation-789d-unowned")
    _require(request, _generation_of(p.container) == 1, "a refused ceremony moved the pointer")
    _require(request, sorted(x.name for x in stray.iterdir()) == ["admissions.lock"], "the refused ceremony wrote into the unowned directory")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a14_successor_receipt_binding_is_enforced(tmp_path, monkeypatch, request):
    """A14: a successor generation authenticates only with ITS OWN receipt.

    (a) a foreign-identity v2 receipt AND a foreign-identity v3 receipt (from a
    rotated sibling) under ``generations/1`` refuse; (b) a receipt-less
    ``generations/2`` refuses at ``_authorize`` on both stores; (c) generation
    1's receipt copied under ``generations/2`` refuses at the loader and at
    both stores; the successor receipt carries every mandatory v3 field.
    """
    live = _live()
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _blocked_fixture(tmp_path, monkeypatch, labels=("alpha", "beta"))
    p = fx.alpha
    outcome = _rotate(request, p)
    gen1 = outcome.store_root
    receipt_bytes = (gen1 / "partition-receipt.json").read_bytes()
    payload = json.loads(receipt_bytes)
    missing = [field for field in RECEIPT_V3_FIELDS if field not in payload]
    _require(request, payload.get("schema") == RECEIPT_SCHEMA_V3 and not missing, f"v3 receipt lacks {missing} (schema {payload.get('schema')!r})")
    # A valid foreign v3 receipt: rotate beta too.
    _block_key(fx.beta, ROTATED_KEY)
    beta_outcome = _rotate(request, fx.beta)
    foreign_v3 = (beta_outcome.store_root / "partition-receipt.json").read_bytes()
    # (a) foreign identity receipts (v2 container, v3 successor).
    def _gen1_refuses(label: str) -> None:
        for what, attempt in (
            ("loader", lambda: live.load_partition_receipt(gen1)),
            ("evidence", lambda: BrokerEvidenceStore(gen1)._authorize()),
            ("admission", lambda: LinearizableAdmissionStore(gen1, lambda _r: True)._authorize()),
        ):
            try:
                attempt()
            except (PermissionError, live.LegacyCutoverConflict):
                continue
            _require(request, False, f"[{label}] {what} accepted the tampered generation 1")

    for label, foreign in (("v2", (fx.beta.container / "partition-receipt.json").read_bytes()), ("v3", foreign_v3)):
        (gen1 / "partition-receipt.json").write_bytes(foreign)
        _gen1_refuses(f"foreign-{label}")
    # (a') same identity, same generation: a tampered receipt (one payload
    # byte changed, or a re-serialised payload whose ``ambiguous`` flag is
    # flipped) and a tampered sealed rotation inventory both fail
    # authentication — the binding is to the sealed bytes, not to the
    # identity+generation coordinates.
    tampered = json.loads(receipt_bytes)
    tampered["ambiguous"] = not tampered.get("ambiguous", False)
    (gen1 / "partition-receipt.json").write_bytes(json.dumps(tampered, sort_keys=True).encode("utf-8"))
    _gen1_refuses("flipped-ambiguous")
    reserialised = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
    if reserialised == receipt_bytes:
        reserialised = json.dumps(payload, sort_keys=True, indent=4).encode("utf-8")
    (gen1 / "partition-receipt.json").write_bytes(reserialised)
    _gen1_refuses("same-payload-different-bytes")
    (gen1 / "partition-receipt.json").write_bytes(receipt_bytes)
    _require(request, live.load_partition_receipt(gen1) is not None, "generation 1 lost authentication after the receipt tamper legs")
    inventory = _ceremony_dir(p) / f"{ROTATION_ID}.inventory.json"
    _require(request, inventory.is_file(), f"no sealed rotation inventory at {inventory}")
    original = inventory.read_bytes()
    sealed = json.loads(original)
    sealed["ah789d_tamper"] = True
    inventory.write_bytes(json.dumps(sealed, sort_keys=True).encode("utf-8"))
    try:
        _gen1_refuses("sealed-inventory")
    finally:
        inventory.write_bytes(original)
    _require(request, live.load_partition_receipt(gen1) is not None, "generation 1 lost authentication after the inventory tamper legs")
    receipt = live.load_partition_receipt(gen1)
    _require(request, receipt.zero_source is False, "successor receipt claims zero_source (plan: successor is never zero-source)")
    _require(request, receipt.ambiguous is False, "successor receipt is ambiguous")
    _require(request, Path(receipt.target_namespace) == p.container, f"successor target_namespace {receipt.target_namespace!r} is not the container")
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
        live.load_partition_receipt(gen2)
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


def _stub_promotion_capability(monkeypatch, live, *, reference="stubbed-promotion"):
    """Replace the cutover-promotion mint with a permissive stub so a promotion
    reaches the IN-LOCK generation fence / provenance append rather than
    refusing at the mint (A17e, A26)."""
    monkeypatch.setattr(
        live,
        "_mint_cutover_promotion_capability",
        lambda root, key, *a, **k: SimpleNamespace(
            store_root=Path(root),
            key=key,
            provenance={"evidence_reference": reference, "serialized_repository": "stub"},
        ),
    )


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a17_flip_fences_pre_flip_lease_and_fresh_writers(tmp_path, monkeypatch, request):
    """A17a–d: a lease taken in the drain→flip gap, fresh leases, UNDECLARED stores, promotion.

    (a) a writer that acquires a generation-0 lease immediately AFTER the real
    drain returns (the pre-flip gap) is refused with ``WriterGenerationBlocked``
    on a generation-0 append after the flip, AND on the successor store — the
    flip promoted a fresh namespace latch generation, so the pre-flip lease is
    refused everywhere, not only where the store is retired (plan D6 "fresh
    namespace latch generation ... every pre-flip lease on every in-lock
    append"; codex r5 finding 3);
    (b) a fresh post-flip lease on the container is GRANTED by the latch (the
    latch is generation-exact) but every write through it is refused in-lock
    on both stores; (c) an UNDECLARED store on the container is refused at
    ``_authorize``; (d) a genuinely promotable carried key IS promoted on the
    successor under a fresh post-flip lease — state ``effect_terminal_observed``,
    only successor files change.  Generation-0 bytes are unchanged throughout.
    Assumes D2 drains through ``WriterGenerationLatch.await_quiescent`` (as
    onboarding does).
    """
    live = _live()
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    landed = p.service.execute(p.request)
    _require(request, landed.accepted is True, "generation-0 publish did not land")
    _block_key(p, ROTATED_KEY)
    gen0 = _store_bytes(p.container)
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
    with pytest.raises(live.WriterGenerationBlocked):
        late.record_intent("publish_committed_branch\x00late-gap-writer")
    late_admission = LinearizableAdmissionStore(p.container, lambda _r: True, generation_lease=gap["lease"])
    with pytest.raises(live.WriterGenerationBlocked):
        late_admission.admit(p.request.admission)
    # (a') the namespace latch generation moved past the gap lease's, and the
    # gap lease is refused on the SUCCESSOR store too (a retired-store check
    # alone would pass a D2 that never bumped the latch).
    post_flip = live.WriterGenerationLatch.for_store_root(outcome.store_root).read()
    _require(request, post_flip.generation != gap["generation"], f"the flip did not promote a fresh namespace latch generation: {gap['generation']!r} -> {post_flip.generation!r}")
    with pytest.raises(live.WriterGenerationBlocked):
        BrokerEvidenceStore(outcome.store_root, generation_lease=gap["lease"]).record_intent("publish_committed_branch\x00late-gap-writer-successor")
    with pytest.raises(live.WriterGenerationBlocked):
        LinearizableAdmissionStore(outcome.store_root, lambda _r: True, generation_lease=gap["lease"]).admit(p.request.admission)
    with contextlib.suppress(Exception):
        gap["lease"].release()
    # (b) fresh post-flip lease on the container: granted, then fenced in-lock on BOTH stores.
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    fresh = latch.acquire(generation=latch.read().generation)
    try:
        with pytest.raises(PermissionError):
            BrokerEvidenceStore(p.container, generation_lease=fresh)._authorize()
        with pytest.raises(PermissionError):
            BrokerEvidenceStore(p.container, generation_lease=fresh).record_intent("publish_committed_branch\x00fresh")
        with pytest.raises(PermissionError):
            LinearizableAdmissionStore(p.container, lambda _r: True, generation_lease=fresh)._authorize()
        with pytest.raises(PermissionError):
            LinearizableAdmissionStore(p.container, lambda _r: True, generation_lease=fresh).admit(p.request.admission)
    finally:
        with contextlib.suppress(Exception):
            fresh.release()
    # (c) UNDECLARED stores on the container.
    with pytest.raises(PermissionError):
        BrokerEvidenceStore(p.container)._authorize()
    with pytest.raises(PermissionError):
        LinearizableAdmissionStore(p.container, lambda _r: True)._authorize()
    _require(request, _store_bytes(p.container) == gen0, "a fenced writer changed generation 0")
    # (d) a genuinely promotable carried key IS promoted on the successor.
    successor_before = _store_bytes(outcome.store_root)
    successor_latch = live.WriterGenerationLatch.for_store_root(outcome.store_root)
    lease = successor_latch.acquire(generation=successor_latch.read().generation)
    try:
        promoted = BrokerEvidenceStore(outcome.store_root, generation_lease=lease).promote_legacy_terminal(carried_key)
    finally:
        with contextlib.suppress(Exception):
            lease.release()
    _require(request, promoted is not None and getattr(promoted, "state", None) is not None, f"promotion returned {promoted!r}")
    _require(request, promoted.state.value == "effect_terminal_observed", f"promoted state {promoted.state!r}")
    _require(request, _store_bytes(p.container) == gen0, "promotion on the successor touched generation 0")
    after = _store_bytes(outcome.store_root)
    changed = {k for k in STORE_FILES if after[k] != successor_before[k]}
    _require(request, changed <= {"evidence.jsonl", "admissions.lock", "legacy-promotions.jsonl"}, f"promotion changed {sorted(changed)}")
    _require(request, "evidence.jsonl" in changed, "the promotion wrote no successor evidence")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a17e_authorized_before_flip_is_refused_in_lock(tmp_path, monkeypatch, request):
    """A17e: a store that passed ``_authorize`` BEFORE the flip is still refused in-lock after it.

    ``_authorize`` is run once pre-flip and then neutralised, and the promotion
    mint is stubbed permissive, so the only remaining check is the in-lock
    generation predicate at the append / admit / provenance sites
    (``evidence.py`` ``_append``, ``_append_provenance_locked``; ``admission.py``
    ``admit``).
    """
    live = _live()
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
    _stub_promotion_capability(monkeypatch, live)
    with pytest.raises(PermissionError):
        evidence.promote_legacy_terminal("publish_committed_branch\x00pre-authorized-promotion")
    _require(request, _store_bytes(p.container) == fx.gen0, "a pre-authorized writer changed generation 0")
    # A writer that DECLARES a lease taken fresh AFTER the flip (so the store
    # goes through the declared-lease branch of ``_require_generation``, not the
    # undeclared one) is fenced the same way at every site: the lease's
    # generation is the latch's current one, but the store's root is a
    # non-ACTIVE generation (codex r3 finding 6).  A pre-flip declared lease
    # would have made ``await_quiescent`` wait on it, so post-flip is the case
    # that isolates the predicate.
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    fresh = latch.acquire(generation=latch.read().generation)
    try:
        declared = BrokerEvidenceStore(p.container, generation_lease=fresh)
        declared_admission = LinearizableAdmissionStore(p.container, lambda _r: True, generation_lease=fresh)
        monkeypatch.setattr(declared, "_authorize", lambda: None)
        monkeypatch.setattr(declared_admission, "_authorize", lambda: None)
        with pytest.raises(PermissionError):
            declared._append(_record("publish_committed_branch\x00declared-lease"))
        with pytest.raises(PermissionError):
            declared_admission.admit(p.request.admission)
        with pytest.raises(PermissionError):
            declared.promote_legacy_terminal("publish_committed_branch\x00declared-lease-promotion")
    finally:
        fresh.release()
    _require(request, _store_bytes(p.container) == fx.gen0, "a declared-lease writer changed generation 0")


# ---------------------------------------------------------------------------
# A18 — host-wide barrier vs one rotated partition (D2-gated)
# ---------------------------------------------------------------------------


def _barrier(live, worktrees):
    report = live.fabpub_activation_barrier(worktrees=tuple(worktrees))
    return report


def _barrier_admitted(report, worktrees) -> bool:
    """True iff every worktree entered the barrier (listed under
    ``repositories``) and none was deferred — the report is a dict even when
    nothing was admitted, so ``report is not None`` proves nothing."""
    expected = {str(Path(w)) for w in worktrees}
    admitted = set(report.get("repositories", []))
    return admitted == expected and not report.get("deferred")


def _raised_inside(exc: BaseException, function_name: str) -> bool:
    """True iff ``function_name`` is on the traceback of ``exc`` — the refusal
    is attributable to that production function, not to a resolver."""
    return any(frame.name == function_name for frame in traceback.extract_tb(exc.__traceback__))


def _barrier_refuses_host_wide(live, request, worktrees, tag: str) -> None:
    """The barrier over ``worktrees`` refuses from the pre-existing bootstrap
    inventory walk (``_tree_file_inventory``, plan D7 / A18a "exactly as it does
    today"): a ``LegacyCutoverConflict`` (symlink) or the uncaught ``OSError``
    (unreadable) raised INSIDE the walk — a ``PartitionRoutingRefused`` from a
    resolver, or any refusal raised elsewhere, fails the leg."""
    with pytest.raises((live.LegacyCutoverConflict, OSError)) as excinfo:
        report = _barrier(live, worktrees)
        live.release_barrier_leases(report)
    _require(
        request,
        _raised_inside(excinfo.value, "_tree_file_inventory"),
        f"[{tag}] barrier over {[Path(w).name for w in worktrees]} refused outside the host-wide walk: {excinfo.value!r}",
    )


def _siblings_pass_barrier_and_publish(live, request, siblings, tag: str, counter: dict) -> None:
    report = _barrier(live, [s.repo for s in siblings])
    try:
        _require(request, _barrier_admitted(report, [s.repo for s in siblings]), f"[{tag}] barrier did not admit the clean siblings: {report}")
    finally:
        live.release_barrier_leases(report)
    counter["n"] += 1
    for s in siblings:
        req = _fresh_request(s, f"a18-{counter['n']}")
        routed = _routed_service(s)
        try:
            result = routed.service.execute(req)
            _require(request, result.accepted is True, f"[{tag}] {s.label} refused: {result.reason}")
            _require(request, len(routed.adapter.calls) == 1, f"[{tag}] {s.label} made {len(routed.adapter.calls)} provider calls")
        finally:
            _release_router(routed)


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a18_barrier_and_siblings_survive_rotated_pointer_states(tmp_path, monkeypatch, request):
    """A18a/b/d: clean v2 siblings pass the barrier and publish FRESH transactions
    while alpha is rotated, and still do with alpha's pointer in each
    RESOLVER-ONLY refusal state (alpha alone refuses at the resolver, and a
    barrier that includes alpha refuses with the resolver's typed refusal).
    The symlink / unreadable members are the other way round (plan D7, A18a):
    the pre-existing bootstrap inventory walk refuses HOST-WIDE — a barrier
    over the clean siblings ALONE refuses too, from ``_tree_file_inventory``,
    because every barrier re-validates every sealed worktree row — and no
    pointer or generation changes.  Bootstrap re-validation is unchanged with
    the rotation directory present.
    """
    live = _live()
    routing_refused = _production(request, "PartitionRoutingRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch, labels=("alpha", "beta", "gamma"))
    alpha, beta, gamma = fx.alpha, fx.beta, fx.gamma
    _release_all(alpha, beta, gamma)
    outcome = _rotate(request, alpha)
    siblings = [beta, gamma]
    everyone = [alpha.repo, beta.repo, gamma.repo]
    counter = {"n": 0}

    def _barrier_with_alpha_refuses_at_resolver(tag: str) -> None:
        with pytest.raises(routing_refused) as excinfo:
            report = _barrier(live, everyone)
            live.release_barrier_leases(report)
        _require(request, not _raised_inside(excinfo.value, "_tree_file_inventory"), f"[{tag}] a resolver-only state was refused by the host-wide walk: {excinfo.value!r}")

    def _host_wide(tag: str) -> None:
        sibling_bytes = {s.label: _store_bytes(s.container) for s in siblings}
        _barrier_refuses_host_wide(live, request, everyone, tag)
        _barrier_refuses_host_wide(live, request, [s.repo for s in siblings], tag)
        _require(request, not (alpha.container / GENERATIONS_DIR / "2").exists(), f"[{tag}] a host-wide refusal created a generation")
        _require(request, {s.label: _store_bytes(s.container) for s in siblings} == sibling_bytes, f"[{tag}] a host-wide refusal changed a sibling store")

    _siblings_pass_barrier_and_publish(live, request, siblings, "rotated", counter)
    report = _barrier(live, everyone)
    try:
        _require(request, _barrier_admitted(report, everyone), f"barrier over the rotated partition did not admit all three: {report}")
    finally:
        live.release_barrier_leases(report)
    saved = _save_pointer(alpha)
    for name, mutate in _pointer_states(alpha).items():
        _restore_pointer(alpha, saved)
        mutate()
        _siblings_pass_barrier_and_publish(live, request, siblings, name, counter)
        with pytest.raises(routing_refused):
            _ = live.repository_snapshot(alpha.repo).store_root
        _barrier_with_alpha_refuses_at_resolver(name)
    for name, mutate in _host_wide_states(alpha).items():
        _restore_pointer(alpha, saved)
        mutate()
        _host_wide(name)
        _require(request, _pointer(alpha).is_symlink(), f"[{name}] the host-wide refusal replaced the symlink pointer")
    _restore_pointer(alpha, saved)
    with _unreadable(monkeypatch, _pointer(alpha)):
        _host_wide("unreadable")
    _require(request, _pointer(alpha).read_bytes() == saved[str(_pointer(alpha))], "the unreadable leg changed the pointer bytes")
    # A18d: bootstrap re-validation unchanged with the rotation directory present.
    resumed = live.bootstrap_zero_history_authority(fx.inventory, confirmed_zero_history=True)
    _require(request, resumed["state"] == "ACTIVE", "bootstrap re-validation changed under the rotation dir")
    _require(request, live.repository_snapshot(alpha.repo).store_root == outcome.store_root, "pointer restore failed")


@_requires_fabpub
def test_partition_rotation_a18_v2_host_wide_walk_refuses_the_sibling_barrier_today(tmp_path, monkeypatch, request):
    """A18 (v2 half, runnable now): the host-wide walk the gated A18 relies on
    exists TODAY.  With a symlink (or an unreadable file) under alpha's
    ``generations/`` — nothing a v2 resolver reads — a barrier over the clean
    siblings alone refuses from ``_tree_file_inventory``; removing it restores
    the barrier.  This pins the satisfiability of the gated host-wide legs to
    plan D9-A's byte-for-byte promise, not to Lane D2.
    """
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch, labels=("alpha", "beta", "gamma"))
    alpha, beta, gamma = fx.alpha, fx.beta, fx.gamma
    _release_all(alpha, beta, gamma)
    siblings = [beta, gamma]
    counter = {"n": 0}
    _siblings_pass_barrier_and_publish(live, request, siblings, "clean", counter)
    gens = alpha.container / GENERATIONS_DIR
    gens.mkdir()
    pointer = gens / ACTIVE_POINTER
    pointer.symlink_to(alpha.container / "partition-receipt.json")
    _barrier_refuses_host_wide(live, request, [s.repo for s in siblings], "symlink")
    pointer.unlink()
    pointer.write_text("0\n", encoding="utf-8")
    with _unreadable(monkeypatch, pointer):
        _barrier_refuses_host_wide(live, request, [s.repo for s in siblings], "unreadable")
    pointer.unlink()
    gens.rmdir()
    _siblings_pass_barrier_and_publish(live, request, siblings, "restored", counter)


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a18c_successor_without_global_authority_or_journal_refuses(tmp_path, monkeypatch, request):
    """A18c: the successor receipt needs its bootstrap claim AND an ACTIVE rotation journal.

    Without the global bootstrap inventory the successor has no active
    authority (``_receipt_active_authority_exists`` False) and the barrier
    refuses at its no-matching-authority site; with the rotation journal
    stopped at ARMED, torn, or deleted the barrier refuses too.
    """
    live = _live()
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    outcome = _rotate(request, p)
    successor = live.load_partition_receipt(outcome.store_root)
    _require(request, successor is not None, "successor receipt did not authenticate")
    on_disk = json.loads((outcome.store_root / "partition-receipt.json").read_text(encoding="utf-8")).get("schema")
    _require(request, on_disk == RECEIPT_SCHEMA_V3, f"successor on-disk schema {on_disk!r}")
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
    journal = _journal_path(p)
    original = journal.read_bytes()
    # A well-formed journal that stops at ARMED (the ACTIVE row never landed):
    # not a torn line, not a missing file — the ceremony is simply not ACTIVE,
    # and the successor has no active authority (codex r3 finding 4).
    lines = original.decode("utf-8").splitlines(keepends=True)
    states = [json.loads(line).get("state") for line in lines if line.strip()]
    _require(request, "ARMED" in states and states[-1] == "ACTIVE", f"journal states after a clean rotation: {states}")
    armed_prefix = "".join(lines[: max(i for i, s in enumerate(states) if s == "ARMED") + 1]).encode("utf-8")
    journal.write_bytes(armed_prefix)
    _require(
        request,
        not live._receipt_active_authority_exists(successor, authority_root=p.authority),
        "successor authority survives a journal that never reached ACTIVE",
    )
    with pytest.raises((live.LegacyCutoverConflict, PermissionError)):
        report = _barrier(live, [p.repo])
        live.release_barrier_leases(report)
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
        _require(request, _barrier_admitted(report, [p.repo]), f"barrier did not admit the successor after the journal was restored: {report}")
    finally:
        live.release_barrier_leases(report)


# ---------------------------------------------------------------------------
# A19, A20, A23, A24, A25, A26 — ceremony artifacts, forward-compat, floor,
# remote silence, traditional authority, concurrent writer (D2-gated)
# ---------------------------------------------------------------------------


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a19_foreign_and_torn_ceremony_artifacts_refuse(tmp_path, monkeypatch, request):
    """A19: foreign-id temp debris, a non-ACTIVE journal, a torn journal, a journal whose
    ``cutover_id`` field names another ceremony, and a journal with an invalid
    state order each refuse with the typed refusal and leave the artifacts —
    journal AND whatever the ceremony staged under ``generations/1`` — as found."""
    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    # (a) foreign-id generations temp debris.
    fx = _blocked_fixture(tmp_path / "debris", monkeypatch)
    p = fx.alpha
    debris = p.container / f"{GENERATIONS_DIR}.tmp.rotation-other"
    debris.mkdir()
    with pytest.raises(refused):
        _rotate(request, p)
    _require(request, not (p.container / GENERATIONS_DIR).exists(), "rotated over foreign debris")
    _require(request, debris.is_dir() and list(debris.iterdir()) == [], "the refusal touched the foreign debris")
    _require(request, _store_bytes(p.container) == fx.gen0, "debris refusal changed generation 0")
    # (b) a new cutover id while the previous journal is not ACTIVE.
    fx = _blocked_fixture(tmp_path / "journal", monkeypatch)
    p = fx.alpha
    _crash_rotation(request, p, "after_journal_armed")
    states = _journal_states(p)
    _require(request, states and states[-1] != "ACTIVE", f"journal after ARMED crash: {states}")
    armed = _journal_path(p).read_bytes()
    # Whatever the ceremony staged under generations/1 before ARMED (the plan
    # writes the successor receipt BEFORE the ARMED row) is an artifact of the
    # SAME ceremony; every refused resume below must leave it byte-identical.
    successor_dir = p.container / GENERATIONS_DIR / "1"
    staged = _store_bytes(successor_dir) if successor_dir.exists() else None
    with pytest.raises(refused):
        _rotate(request, p, cutover_id="rotation-789d-new")
    _require(request, _journal_states(p, "rotation-789d-new") == [], "a refused new id wrote a journal")
    _require(request, _journal_path(p).read_bytes() == armed, "the refused new id rewrote the armed journal")
    # (c) a torn journal for the SAME id refuses resume with a typed refusal.
    journal = _journal_path(p)
    torn = armed[:-7]
    journal.write_bytes(torn)
    with pytest.raises(refused):
        _rotate(request, p)
    _require(request, _generation_of(p.container) == 0, "a torn journal flipped the pointer")
    _require(request, journal.read_bytes() == torn, "resume rewrote the torn journal")
    _require(request, (_store_bytes(successor_dir) if successor_dir.exists() else None) == staged, "a torn-journal refusal touched the staged successor")
    # (d) a well-formed journal whose cutover_id field names ANOTHER ceremony.
    lines = [json.loads(line) for line in armed.decode("utf-8").splitlines() if line.strip()]
    foreign = [dict(line, cutover_id="rotation-789d-elsewhere") for line in lines]
    body = "".join(json.dumps(line, sort_keys=True) + "\n" for line in foreign).encode("utf-8")
    journal.write_bytes(body)
    with pytest.raises(refused):
        _rotate(request, p)
    _require(request, _generation_of(p.container) == 0, "a foreign-id journal flipped the pointer")
    _require(request, journal.read_bytes() == body, "resume rewrote the foreign-id journal")
    _require(request, (_store_bytes(successor_dir) if successor_dir.exists() else None) == staged, "a foreign-id refusal touched the staged successor")
    # (e) an invalid state order (ACTIVE recorded before ARMED).
    reordered = list(reversed(lines)) if len(lines) > 1 else [dict(lines[0], state="ACTIVE"), dict(lines[0])]
    body = "".join(json.dumps(line, sort_keys=True) + "\n" for line in reordered).encode("utf-8")
    journal.write_bytes(body)
    with pytest.raises(refused):
        _rotate(request, p)
    _require(request, _generation_of(p.container) == 0, "an out-of-order journal flipped the pointer")
    _require(request, journal.read_bytes() == body, "resume rewrote the out-of-order journal")
    _require(request, (_store_bytes(successor_dir) if successor_dir.exists() else None) == staged, "an out-of-order refusal touched the staged successor")


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
    """A23: the successor's authenticated floor equals the predecessor's high-water,
    through an idle generation AND through an allocating one.

    Generation 0 first LANDS a publish so its high-water is strictly positive
    (an all-zero floor would make ``>=`` vacuous); the floor is then asserted
    EQUAL on generation 1 and, after an allocation-free generation 1 is blocked
    and rotated, on generation 2.  A second fixture then has generation 1
    ALLOCATE above its inherited floor before it is blocked and rotated:
    generation 2's floor must equal that higher allocation, not the receipt
    floor generation 1 inherited — the plan's ``max(predecessor receipt floor,
    predecessor max allocated epoch)`` (D2; m12; codex r5 finding 2).
    """
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    landed = p.service.execute(p.request)
    _require(request, landed.accepted is True, "generation-0 publish did not land")
    _block_key(p, ROTATED_KEY)
    pred_receipt = live.load_partition_receipt(p.container)
    epochs = [line.get("epoch", 0) for line in _jsonl(p.admissions)] if p.admissions.exists() else []
    expected = max([pred_receipt.legacy_epoch_high_water, *epochs])
    _require(request, expected > 0, f"generation-0 high-water is {expected}; the floor assertion would be vacuous")
    first = _rotate(request, p)
    _require(request, live.authenticated_partition_floor(first.store_root) == expected, "generation-1 floor != predecessor high-water")
    # Generation 1 allocates nothing, gets blocked, rotates → generation 2 still carries the floor.
    routed = _successor_service(request, first, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah789d-gen1-ambiguous")
    finally:
        _release_router(routed)
    second = _rotate(request, p, cutover_id=ROTATION_ID_2)
    _require(
        request,
        live.authenticated_partition_floor(second.store_root) == expected,
        "generation-2 floor != predecessor high-water through an idle generation",
    )
    # Allocating leg: generation 1 publishes ABOVE its inherited floor.
    fx2 = _bootstrap(tmp_path / "allocating", monkeypatch)
    q = fx2.alpha
    _require(request, q.service.execute(q.request).accepted is True, "generation-0 publish did not land (allocating leg)")
    _block_key(q, ROTATED_KEY)
    q_receipt = live.load_partition_receipt(q.container)
    q_epochs = [line.get("epoch", 0) for line in _jsonl(q.admissions)] if q.admissions.exists() else []
    inherited = max([q_receipt.legacy_epoch_high_water, *q_epochs])
    _require(request, inherited > 0, f"generation-0 high-water is {inherited} (allocating leg)")
    q_first = _rotate(request, q)
    _require(request, live.authenticated_partition_floor(q_first.store_root) == inherited, "generation-1 floor != predecessor high-water (allocating leg)")
    result, _calls = _publish_on_successor(request, q_first, q, _fresh_request(q, "a23-gen1"))
    _require(request, getattr(result, "accepted", None) is True, f"generation-1 publish did not land: {result!r}")
    gen1_admissions = q_first.store_root / "admissions.jsonl"
    gen1_epochs = [line.get("epoch", 0) for line in _jsonl(gen1_admissions)] if gen1_admissions.exists() else []
    allocated = max([inherited, *gen1_epochs])
    _require(request, allocated > inherited, f"generation 1 allocated nothing above its inherited floor {inherited}: {gen1_epochs}")
    routed = _successor_service(request, q_first, q)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah789d-gen1-allocated-ambiguous")
    finally:
        _release_router(routed)
    q_second = _rotate(request, q, cutover_id=ROTATION_ID_2)
    _require(
        request,
        live.authenticated_partition_floor(q_second.store_root) == allocated,
        f"generation-2 floor != generation 1's max allocated epoch {allocated} (a copied receipt floor would be {inherited})",
    )


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a24_ceremony_never_probes_the_remote(tmp_path, monkeypatch, request):
    """A24 (gated half): the ceremony itself — success, refusal and crash+resume — makes
    no remote probe.  The v2 half (``a24_v2``) proves the successor PUBLISH is
    silent; this half proves the CEREMONY is.
    """
    fx = _blocked_fixture(tmp_path / "ok", monkeypatch)
    p = fx.alpha
    with _no_remote_probe(monkeypatch) as attempts:
        outcome = _rotate(request, p)
    _require(request, outcome.generation == 1, "rotation failed")
    _require(request, attempts == [], f"a clean rotation consulted the remote: {attempts}")
    fx = _blocked_fixture(tmp_path / "refused", monkeypatch)
    p = fx.alpha
    with _no_remote_probe(monkeypatch) as attempts:
        with pytest.raises(PermissionError):
            _rotate(request, p, attestation=_attestation(p, keys=[]))
    _require(request, attempts == [], f"a refused rotation consulted the remote: {attempts}")
    fx = _blocked_fixture(tmp_path / "crash", monkeypatch)
    p = fx.alpha
    with _no_remote_probe(monkeypatch) as attempts:
        _crash_rotation(request, p, "after_journal_armed")
        outcome = _rotate(request, p)
    _require(request, outcome.generation == 1, "resume failed")
    _require(request, attempts == [], f"crash+resume consulted the remote: {attempts}")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a25_traditional_v2_authority_refuses_rotation(tmp_path, request):
    """A25: a partition under the traditional (non-bootstrap) v2 authority is refused, no writes.

    The fixture's receipt shape is pinned so the refusal is proven on the
    TRADITIONAL authority (``zero_source`` false, a populated legacy-root
    inventory, no bootstrap claim) and not on a mis-built fixture (grok r2
    finding 1).  ``_two_partitions`` seeds zero-history legacy roots — "zero
    history" means zero epochs, not a zero-source bootstrap.
    """
    refused = _production(request, "PartitionRotationRefused")
    live = _live()
    alpha, _beta = _two_partitions(tmp_path)
    receipt = live.load_partition_receipt(alpha.root)
    _require(request, receipt is not None and receipt.zero_source is False, f"traditional receipt {receipt!r}")
    _require(request, receipt.legacy_root_inventory != (), "the traditional receipt names no legacy root")
    _require(request, live._receipt_bootstrap_claim(receipt) is None, "the traditional receipt carries a bootstrap claim")
    _block_key(alpha, ROTATED_KEY)
    _release_all(alpha, _beta)
    alpha.container = alpha.root
    alpha.authority = Path(os.environ["PHASE_LOOP_FABPUB_AUTHORITY_ROOT"])
    before = _store_bytes(alpha.root)
    with pytest.raises(refused):
        _rotate(request, alpha, attestation=_attestation(alpha, store_root=alpha.root))
    _assert_no_durable_rotation(request, alpha)
    _require(request, _store_bytes(alpha.root) == before, "refusal changed the traditional partition")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a26_concurrent_writer_lands_before_digest_or_is_fenced(tmp_path, monkeypatch, request):
    """A26: a writer INSIDE generation 1's lock (past ``_authorize`` and the mint)
    across a 1→2 rotation lands before the predecessor digest is taken or is
    fenced in-lock — never after the digest.

    The writer is a real ``promote_legacy_terminal`` on generation 1, paused
    AFTER its last append (the ``effect_terminal_observed`` row) while it
    still holds ``admissions.lock`` (the promotion mint is stubbed permissive
    so the writer reaches the lock).  Its bytes are therefore final before
    the rotator starts, so the attestation the rotator builds binds
    generation 1's FINAL bytes and the only admissible outcome is the plan's
    "lands before the digests are taken" arm (the in-lock fence arm is A17's;
    the writer paused BEFORE its terminal append — where the digest could be
    taken over stale bytes — is A26b's).
    While the writer holds the lock the rotation MUST NOT complete (m28: a
    digest taken without the predecessor lock would still equal the final
    bytes here, so the liveness check is what kills it); once released, the
    rotation succeeds and its predecessor digest equals the final bytes.
    """
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    live = _live()
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    first = _rotate(request, p)
    routed = _successor_service(request, first, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah789d-gen1-ambiguous")
    finally:
        _release_router(routed)
    gen1 = first.store_root
    writer_key = "publish_committed_branch\x00ah789d-concurrent-writer"
    _stub_promotion_capability(monkeypatch, live)
    holding = threading.Event()
    proceed = threading.Event()
    result: dict = {}

    def writer():
        store = BrokerEvidenceStore(gen1)
        real = store._append_locked

        def paused(record):
            appended = real(record)
            if record.state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED:
                # Every write of this writer is durable; the lock is still held.
                holding.set()
                proceed.wait(120)
            return appended

        store._append_locked = paused
        try:
            result["promoted"] = store.promote_legacy_terminal(writer_key)
            result["landed"] = True
        except PermissionError as exc:
            result["fenced"] = str(exc)
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            result["error"] = repr(exc)
        finally:
            holding.set()

    def rotator():
        try:
            result["outcome"] = _rotate(request, p, cutover_id=ROTATION_ID_2)
        except Exception as exc:
            result["rotation_error"] = exc

    t_writer = threading.Thread(target=writer, daemon=True)
    t_rotate = threading.Thread(target=rotator, daemon=True)
    try:
        t_writer.start()
        _require(request, holding.wait(60), "writer never reached the in-lock append")
        _require(request, "error" not in result and "fenced" not in result, f"writer did not reach the lock: {result}")
        landed_bytes = _store_bytes(gen1)
        _require(
            request,
            writer_key in {line.get("idempotency_key") for line in _jsonl(gen1 / "evidence.jsonl")},
            "the writer's terminal is not on disk at the pause point",
        )
        t_rotate.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and t_rotate.is_alive():
            time.sleep(0.05)
        _require(request, t_rotate.is_alive(), "the rotation completed while a writer held generation 1's lock")
        _require(request, _generation_of(p.container) == 1 and not (p.container / GENERATIONS_DIR / "2" / "partition-receipt.json").exists(), "the rotation sealed generation 2 while a writer held generation 1's lock")
    finally:
        proceed.set()
        t_writer.join(120)
        t_rotate.join(120)
    _require(request, "rotation_error" not in result, f"rotation failed: {result.get('rotation_error')!r}")
    _require(request, "error" not in result, f"writer errored: {result.get('error')}")
    _require(request, result.get("landed") is True, f"the writer did not land: {result}")
    _require(request, not t_writer.is_alive() and not t_rotate.is_alive(), "threads did not finish")
    outcome = result["outcome"]
    final = _store_bytes(gen1)
    _require(request, final == landed_bytes, "generation 1's bytes changed after the writer's last append")
    digests = outcome.receipt.predecessor_digests
    for name in ("evidence.jsonl", "admissions.jsonl"):
        if final.get(name) is None:
            continue
        _require(
            request,
            digests.get(name) == _sha256_bytes(final[name]),
            f"predecessor {name} digest does not bind generation 1's FINAL bytes",
        )
    _require(request, outcome.generation == 2 and _generation_of(p.container) == 2, "the rotation did not reach generation 2")


@_requires_fabpub
@_requires_789d
def test_partition_rotation_a26b_writer_paused_before_first_write_is_never_digested_stale(tmp_path, monkeypatch, request):
    """A26b: a writer inside generation 1's lock paused BEFORE its first store
    write — the lock is held, the store is still clean and fully terminal —
    across a 1→2 rotation whose attestation was built over those CLEAN bytes.
    The attestation binds the predecessor store digests and the ceremony
    re-verifies it under the predecessor lock (plan D4; D9-C "final
    predecessor validation ... held across"), so the ONLY admissible outcome
    is a typed refusal: no generation-2 receipt, pointer still 1, generation 1
    still what the resolver names.  A success receipt here means the digests
    were captured over stale bytes or the attestation was never re-verified
    in-lock (fable r3 finding 1; codex r4 finding 1).  The pause point matters
    (fable r5 finding 1; codex r5 finding 1): with NO dangling row on disk a
    pre-lock lineage scan has nothing to refuse on, so a D2 that verifies the
    digests only pre-lock blocks on the lock, then completes over bytes the
    writer changed — the D9-C violation this anchor pins.  While the writer
    holds the lock the ceremony may block on it or refuse early from a
    pre-lock check (a try-lock "busy" refusal, fable r4 F2) — it must not
    COMPLETE (m28).  Whatever journal the refused ceremony leaves is A19
    debris and is left as found; no recovery rotation is chained over it
    (plan D1: a non-ACTIVE journal refuses a new ceremony; grok r4).
    """
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    live = _live()
    refused = _production(request, "PartitionRotationRefused")
    fx = _blocked_fixture(tmp_path, monkeypatch)
    p = fx.alpha
    first = _rotate(request, p)
    routed = _successor_service(request, first, p)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah789d-gen1-ambiguous")
    finally:
        _release_router(routed)
    gen1 = first.store_root
    writer_key = "publish_committed_branch\x00ah789d-paused-writer"
    _stub_promotion_capability(monkeypatch, live)
    holding = threading.Event()
    proceed = threading.Event()
    result: dict = {}

    def writer():
        store = BrokerEvidenceStore(gen1)
        real = store._append_provenance_locked

        def paused(key, provenance):
            # Provenance is the FIRST write under the lock (evidence.py
            # ``promote_legacy_terminal``: authorize → flock → mint → provenance
            # → in-flight → terminal); pausing before it leaves generation 1
            # clean and fully terminal while the lock is held.
            holding.set()
            proceed.wait(120)
            return real(key, provenance)

        store._append_provenance_locked = paused
        try:
            result["promoted"] = store.promote_legacy_terminal(writer_key)
            result["landed"] = True
        except PermissionError as exc:
            result["fenced"] = str(exc)
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            result["error"] = repr(exc)
        finally:
            holding.set()

    def rotator(attestation):
        try:
            result["outcome"] = _rotate(request, p, cutover_id=ROTATION_ID_2, attestation=attestation)
        except refused as exc:
            result["refused"] = exc
        except Exception as exc:
            result["rotation_error"] = exc

    clean = _store_bytes(gen1)
    t_writer = threading.Thread(target=writer, daemon=True)
    t_rotate = None
    try:
        t_writer.start()
        _require(request, holding.wait(60), "writer never reached the in-lock provenance append")
        _require(request, "error" not in result and "fenced" not in result and "landed" not in result, f"writer did not pause inside the lock: {result}")
        stale = _store_bytes(gen1)
        _require(request, stale == clean, "the writer wrote before the pause point; the store is not clean")
        rows = [line.get("state") for line in _jsonl(gen1 / "evidence.jsonl") if line.get("idempotency_key") == writer_key]
        _require(request, rows == [], f"writer rows at the pause point: {rows}")
        # The attestation is built over the CLEAN bytes (about to go stale),
        # without touching the lock (an explicit ``store_root`` keeps the
        # builder off the resolver).
        attestation = _attestation(p, store_root=gen1)
        _require(
            request,
            attestation["predecessor_store_digests"]["evidence.jsonl"] == _sha256_bytes(stale["evidence.jsonl"]),
            "the attestation does not bind the pre-pause bytes",
        )
        t_rotate = threading.Thread(target=rotator, args=(attestation,), daemon=True)
        t_rotate.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and t_rotate.is_alive():
            time.sleep(0.05)
        # Blocked on the lock (alive) or refused early, typed — never completed.
        _require(request, t_rotate.is_alive() or "refused" in result, f"the rotation ended without a typed refusal while a writer held generation 1's lock: {result}")
        _require(request, "outcome" not in result and _generation_of(p.container) == 1 and not (p.container / GENERATIONS_DIR / "2" / "partition-receipt.json").exists(), "the rotation sealed generation 2 while a writer held generation 1's lock")
    finally:
        proceed.set()
        t_writer.join(120)
        if t_rotate is not None:
            t_rotate.join(120)
    _require(request, "rotation_error" not in result, f"rotation failed outside the typed refusal: {result.get('rotation_error')!r}")
    _require(request, "error" not in result, f"writer errored: {result.get('error')}")
    _require(request, result.get("landed") is True, f"the writer did not land: {result}")
    final = _store_bytes(gen1)
    _require(request, final["evidence.jsonl"] != stale["evidence.jsonl"], "the writer's terminal row never landed")
    # The attestation's store digest is now stale; the in-lock re-verification
    # must have refused.  A success receipt is the D9-C violation.
    _require(request, "refused" in result and "outcome" not in result, f"a rotation attested over stale predecessor bytes was not refused: {result}")
    _require(request, _generation_of(p.container) == 1, "a refused rotation moved the pointer")
    _require(request, not (p.container / GENERATIONS_DIR / "2" / "partition-receipt.json").exists(), "a refused rotation sealed a generation-2 receipt")
    _require(request, live.repository_snapshot(p.repo).store_root == gen1, "generation 1 is no longer what the resolver names")
    _require(request, "ACTIVE" not in _journal_states(p, ROTATION_ID_2), "a refused rotation journaled ACTIVE")
    _require(request, _store_bytes(gen1) == final, "generation 1's bytes changed after the refusal")
