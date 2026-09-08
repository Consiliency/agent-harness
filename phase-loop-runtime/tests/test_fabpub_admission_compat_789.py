"""Consiliency/agent-harness#789 falsifiers — pre-admission runtime-compatibility guard.

Workstream A of ``plans/detailed-789-fabpub-pre-admission-compat-20260906.md``.
tests_only lane, RED-first, following the FABPUB idiom (``_fabpub_tdd_guard``):

* production-dependent falsifiers are ``skipif``-gated per test (no module-level
  skip, no ``xfail``) and GREEN-by-skip until the guard is activated;
* activation is the exact env switch ``PHASE_LOOP_TDD_EXPECT_789=1`` or the
  presence of the production symbol ``AdmissionStoreIncompatible`` on
  ``phase_loop_runtime.convergence.broker.admission``;
* every activated falsifier asserts its live source anchor FIRST, so a run
  against production-identical ``main`` fails at its unique
  ``789-RED-ANCHOR::<name>`` string rather than with an ``ImportError``;
* past the anchor gate every assertion is about a value PRODUCTION produced on
  disk (the owner file, ``admissions.jsonl``, ``evidence.jsonl``, the durable
  transaction checkpoint) or a counter a spy wired into a production seam
  incremented — never a list the test filled in itself.

The incident (Consiliency/agent-harness#789): a stale installed runtime whose
``AdmissionRecord`` lacked ``binding`` read a newer ``admissions.jsonl``.  The
owner file was written first, THEN ``_records()`` raised ``TypeError`` inside
``admit_next`` — an unsealed owner with no admission.  The guard must refuse
BEFORE the owner write, typed, and must keep owner + admission under ONE
``admissions.lock`` acquisition so no writer of any version can interleave.

This module is a NEW file so the count-guarded FABPUB corpus is untouched; its
helpers are IMPORTED from ``test_fabpub_shared_epoch`` (never copied).
"""

from __future__ import annotations

import dataclasses
import errno
import fcntl
import inspect
import json
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from _fabpub_tdd_guard import (
    FABPUB_SKIP_REASON,
    fabpub_capability_active,
    fabpub_symbol,
)
from test_fabpub_shared_epoch import (
    _CountingAdapter,
    _authorized_publish_fixture,
    _counting_store,
    _jsonl,
    _publish_transaction_request,
    _service,
)

pytestmark: list = []  # explicitly no module-level skip

ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_789"
ADMISSION_MODULE = "phase_loop_runtime.convergence.broker.admission"
VERBS_MODULE = "phase_loop_runtime.convergence.broker.verbs"
SKIP_REASON = (
    "ah#789 pre-admission compatibility guard is absent (tests_only boundary): "
    f"set {ACTIVATION_ENV}=1 to run this falsifier against production"
)

#: Unique RED anchors, one per production-dependent falsifier.
RED_ANCHORS = {
    name: f"789-RED-ANCHOR::{name}"
    for name in (
        "test_incompatible_admission_record_refused_before_owner_acquisition",
        "test_legacy_reader_shape_reproduces_incident",
        "test_incompatible_reader_performs_no_mutation_before_owner_path",
        "test_probe_readable_creates_nothing",
        "test_incompatible_record_landing_after_probe_still_refused_before_owner_write",
        "test_owner_and_admission_share_one_lock_acquisition",
        "test_incompatible_record_after_probe_refused_inside_block_unsealed_owner",
        "test_lock_held_without_lock_fails_loud",
        "test_second_entry_contention_message_is_distinct",
    )
}

#: The raw unknown key an incompatible (newer-runtime) writer leaves behind.
FUTURE_KEY = "future_field"
WAIT_SECONDS = 30.0


def _guard_active() -> bool:
    """Exact activation predicate: the env switch, or the production symbol."""
    if os.environ.get(ACTIVATION_ENV) == "1":
        return True
    return fabpub_symbol(ADMISSION_MODULE, "AdmissionStoreIncompatible") is not None


_requires_789 = pytest.mark.skipif(not _guard_active(), reason=SKIP_REASON)
_requires_fabpub = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)


def _require(request, condition, detail: str = "") -> None:
    """Assert ``condition`` with this test's unique frozen RED anchor."""
    anchor = RED_ANCHORS[request.node.originalname]
    if not condition:
        suffix = f" — {detail}" if detail else ""
        raise AssertionError(f"{anchor}{suffix}")


def _incompatible_cls():
    return fabpub_symbol(ADMISSION_MODULE, "AdmissionStoreIncompatible")


def _has_lock_held(qualname: str, module: str) -> bool:
    target = fabpub_symbol(module, qualname)
    if target is None:
        return False
    return "lock_held" in inspect.signature(target).parameters


# ---------------------------------------------------------------------------
# Fixture plumbing — every store here is a REAL routed store in an activated
# repository partition, built by the shared-epoch helpers.
# ---------------------------------------------------------------------------


def _routed(tmp_path: Path, *, name: str) -> SimpleNamespace:
    worktree, transaction, identity, root = _authorized_publish_fixture(tmp_path, name=name)
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)
    request = _publish_transaction_request(identity, "feat/x", transaction, worktree)
    assert store.lock_path == service.evidence_store.lock_path == root / "admissions.lock"
    return SimpleNamespace(
        worktree=worktree,
        transaction=transaction,
        identity=identity,
        root=root,
        adapter=adapter,
        store=store,
        service=service,
        request=request,
        admissions=root / "admissions.jsonl",
        evidence=root / "evidence.jsonl",
        owner=root / "adapter-start-owner.json",
        # The one lock file every writer of any version takes (shared by the
        # admission store and the evidence store).
        lock=store.lock_path,
    )


def _compatible_record(identity: str, epoch: int = 1) -> dict:
    """One admission line every runtime this repo has shipped can read."""
    return {
        "sequence": epoch,
        "epoch": epoch,
        "request": {
            "attempt_id": f"seed-attempt-{epoch}",
            "lease_epoch": epoch,
            "fence_token": f"seed-fence-{epoch}",
            "approval_digest": f"seed-approval-{epoch}",
            "expected_version_predicate": "head == committed",
            "authority_domain_scope": f"repository:{identity}",
            "idempotency_key": f"seed-key-{epoch}",
        },
        "binding": None,
    }


def _binding_record(identity: str, worktree: Path, checkpoint_root: Path, epoch: int = 1) -> dict:
    """One ``binding``-bearing readmit record — the shape the incident's reader lacked."""
    return {
        "sequence": epoch,
        "epoch": epoch,
        "request": {
            "repository": identity,
            "adapter_worktree": str(worktree),
            "checkpoint_root": str(checkpoint_root),
            "branch": "feat/x",
            "base": "main",
            "prior_head_sha": "a" * 40,
            "proposed_head_sha": "b" * 40,
            "train_id": "train-789",
            "node_id": "node-789",
            "fab_run_id": "run-789",
            "roadmap_digest": "r" * 64,
            "provenance_digest": "p" * 64,
            "owned_scope": ["a.py"],
        },
        "binding": {
            "prior_head_sha": "a" * 40,
            "proposed_head_sha": "b" * 40,
            "node_id": "node-789",
            "owned_scope": ["a.py"],
            "authority_digest": "d" * 64,
            "attempt_identity": "attempt-789",
        },
    }


def _append_raw(path: Path, record: dict) -> None:
    """A byte-level append — the incompatible writer is simulated at the line level."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read_or_none(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _durable_state(transaction) -> str:
    return json.loads(transaction.checkpoint_path.read_text(encoding="utf-8"))["state"]


def _snapshot(fx: SimpleNamespace) -> dict:
    return {
        "admissions": _read_or_none(fx.admissions),
        "evidence": _read_or_none(fx.evidence),
        "owner": _read_or_none(fx.owner),
        "state": _durable_state(fx.transaction),
    }


def _assert_refused_before_owner(fx: SimpleNamespace, before: dict) -> None:
    """The chronology the guard owes: nothing durable moved, the adapter never ran."""
    assert not fx.owner.exists(), "adapter-start-owner.json must not be written by an incompatible reader"
    assert _read_or_none(fx.evidence) == before["evidence"], "evidence.jsonl must be byte-identical"
    assert _read_or_none(fx.admissions) == before["admissions"], "admissions.jsonl must be byte-identical"
    assert _durable_state(fx.transaction) == "COMMITTED_HEAD_RESOLVED"
    assert before["state"] == "COMMITTED_HEAD_RESOLVED"
    assert fx.adapter.calls == []
    assert fx.store.admit_next_calls == 0


# ---------------------------------------------------------------------------
# Falsifiers
# ---------------------------------------------------------------------------


@_requires_789
def test_incompatible_admission_record_refused_before_owner_acquisition(tmp_path, request):
    """An unknown admission key is a TYPED refusal before any owner acquisition."""
    _require(
        request,
        _incompatible_cls() is not None,
        "AdmissionStoreIncompatible is absent; an unknown admission key still surfaces as a "
        "bare TypeError after the owner file is durable",
    )
    incompatible = _incompatible_cls()
    assert issubclass(incompatible, PermissionError), (
        "the typed refusal must remain a PermissionError so every fail-closed path stays closed"
    )

    fx = _routed(tmp_path, name="compat-refused")
    seeded = _compatible_record(fx.identity)
    seeded[FUTURE_KEY] = 1
    _append_raw(fx.admissions, seeded)
    before = _snapshot(fx)

    with pytest.raises(incompatible) as info:
        fx.service.execute(fx.request)

    message = str(info.value)
    assert FUTURE_KEY in message, f"the refusal must name the unknown key; got: {message}"
    assert str(fx.store.path) in message, f"the refusal must name the store path; got: {message}"
    runtime = __import__("phase_loop_runtime")
    assert runtime.__version__ in message, f"the refusal must name the refusing runtime version; got: {message}"
    assert str(Path(runtime.__file__)) in message, f"the refusal must name the refusing runtime file; got: {message}"
    _assert_refused_before_owner(fx, before)
    assert fx.store.admit_next_calls == 0, "the refusal precedes admission entirely"


@_requires_789
def test_legacy_reader_shape_reproduces_incident(tmp_path, request, monkeypatch):
    """Acceptance item 1: the incident's reader shape (no ``binding``) is refused typed, pre-owner."""
    _require(
        request,
        _incompatible_cls() is not None,
        "AdmissionStoreIncompatible is absent; the legacy reader shape replays the incident "
        "(owner durable, then TypeError)",
    )
    incompatible = _incompatible_cls()
    admission_module = __import__(ADMISSION_MODULE, fromlist=["AdmissionRecord"])

    @dataclasses.dataclass(frozen=True)
    class LegacyAdmissionRecord:  # the shape the stale installed runtime carried
        sequence: int
        epoch: int
        request: object

    fx = _routed(tmp_path, name="compat-legacy")
    _append_raw(
        fx.admissions,
        _binding_record(fx.identity, fx.worktree, fx.transaction.checkpoint_root),
    )
    before = _snapshot(fx)
    monkeypatch.setattr(admission_module, "AdmissionRecord", LegacyAdmissionRecord)

    with pytest.raises(incompatible) as info:
        fx.service.execute(fx.request)

    message = str(info.value)
    assert "binding" in message, f"the refusal must name the field the reader lacks; got: {message}"
    _assert_refused_before_owner(fx, before)


@_requires_789
def test_incompatible_reader_performs_no_mutation_before_owner_path(tmp_path, request):
    """Acceptance item 2: the early probe keeps an incompatible reader out of ``_block_unsealed_owner``."""
    _require(
        request,
        _incompatible_cls() is not None,
        "AdmissionStoreIncompatible is absent; an incompatible reader still reaches "
        "_block_unsealed_owner and appends evidence records",
    )
    incompatible = _incompatible_cls()
    owner_cls = fabpub_symbol(VERBS_MODULE, "AdapterStartOwnership")
    assert owner_cls is not None

    fx = _routed(tmp_path, name="compat-foreign-owner")
    foreign = owner_cls(
        fx.identity,
        "foreign-key",
        "foreign-transaction",
        "foreign-attempt",
        "f" * 40,
        "publish_committed_branch",
        "foreign-nonce-0000000000000000",
        "foreign-key",
        False,
    )
    fx.root.mkdir(parents=True, exist_ok=True)
    fx.owner.write_text(
        json.dumps(foreign.__dict__, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    seeded = _compatible_record(fx.identity)
    seeded[FUTURE_KEY] = 1
    _append_raw(fx.admissions, seeded)
    before = _snapshot(fx)
    assert before["evidence"] is None or b"foreign-key" not in before["evidence"], (
        "fixture precondition: the foreign owner has NO evidence record yet"
    )

    with pytest.raises(incompatible):
        fx.service.execute(fx.request)

    assert _read_or_none(fx.evidence) == before["evidence"], (
        "evidence.jsonl must be byte-identical: no PROVIDER_CALL_IN_FLIGHT / "
        "OUTCOME_AMBIGUOUS_BLOCKED record may be appended by an incompatible reader"
    )
    assert fx.owner.read_bytes() == before["owner"], "the foreign owner must be untouched"
    assert _read_or_none(fx.admissions) == before["admissions"]
    assert _durable_state(fx.transaction) == "COMMITTED_HEAD_RESOLVED"
    assert fx.adapter.calls == []


@_requires_789
def test_probe_readable_creates_nothing(tmp_path, request):
    """``probe_readable`` is read-only: a never-created store root stays absent."""
    probe = fabpub_symbol(ADMISSION_MODULE, "LinearizableAdmissionStore.probe_readable")
    _require(
        request,
        probe is not None,
        "LinearizableAdmissionStore.probe_readable is absent",
    )
    store_cls = fabpub_symbol(ADMISSION_MODULE, "LinearizableAdmissionStore")
    root = tmp_path / "never-created" / "repositories" / "x"
    store = store_cls(root, lambda _request: True)

    count = store.probe_readable()

    assert count == 0
    assert not root.exists(), "the probe must not create the store root"
    assert not root.parent.exists()
    assert not store.lock_path.exists() and not store.path.exists()


@_requires_789
def test_incompatible_record_landing_after_probe_still_refused_before_owner_write(
    tmp_path, request, monkeypatch
):
    """F1: a record that lands AFTER the early probe is still refused before the owner write."""
    _require(
        request,
        _incompatible_cls() is not None
        and fabpub_symbol(ADMISSION_MODULE, "LinearizableAdmissionStore.probe_readable") is not None,
        "AdmissionStoreIncompatible / probe_readable are absent; the store-mutates-after-probe "
        "race cannot be expressed",
    )
    incompatible = _incompatible_cls()
    fx = _routed(tmp_path, name="compat-after-probe")
    original_probe = fx.store.probe_readable
    probe_calls: list[int] = []

    def probe_then_mutate():
        count = original_probe()
        probe_calls.append(count)
        # The store mutates AFTER the early probe returned success: a newer
        # runtime's writer lands an incompatible line before our critical section.
        seeded = _compatible_record(fx.identity)
        seeded[FUTURE_KEY] = 1
        _append_raw(fx.admissions, seeded)
        return count

    monkeypatch.setattr(fx.store, "probe_readable", probe_then_mutate)
    state_before = _durable_state(fx.transaction)
    evidence_before = _read_or_none(fx.evidence)

    with pytest.raises(incompatible) as info:
        fx.service.execute(fx.request)

    assert probe_calls == [0], "the early probe ran once against a compatible (empty) store"
    assert FUTURE_KEY in str(info.value)
    assert not fx.owner.exists(), (
        "adapter-start-owner.json must be absent: the in-section validation (step 1) refuses "
        "before the owner write even though the early probe succeeded"
    )
    persisted = _jsonl(fx.admissions)
    assert len(persisted) == 1 and persisted[0].get(FUTURE_KEY) == 1, "no admission was appended"
    assert _read_or_none(fx.evidence) == evidence_before
    assert _durable_state(fx.transaction) == state_before == "COMMITTED_HEAD_RESOLVED"
    assert fx.adapter.calls == []


@_requires_789
def test_owner_and_admission_share_one_lock_acquisition(tmp_path, request, monkeypatch):
    """Owner write and admission happen under ONE ``admissions.lock`` acquisition.

    The witness is the lock itself, observed from the test thread while the
    publisher is parked between the owner write (step 3) and ``admit_next``
    (step 4): a non-blocking ``flock`` through a second descriptor MUST be
    refused with ``EWOULDBLOCK``.  If it succeeds, the gap is open and the
    incident chronology is reproduced (branch ii) — reported as a FAIL.
    """
    _require(
        request,
        _has_lock_held("LinearizableAdmissionStore.admit_next", ADMISSION_MODULE)
        and _has_lock_held("append_adapter_start_owner", VERBS_MODULE),
        "admit_next / append_adapter_start_owner carry no lock_held parameter; owner and "
        "admission are still allocated under separate acquisitions",
    )
    incompatible = _incompatible_cls()
    fx = _routed(tmp_path, name="compat-one-acquisition")
    original_admit_next = fx.store.admit_next
    parked = threading.Event()
    release = threading.Event()
    worker: dict = {}

    def parked_admit_next(make_request, **kwargs):
        # (a) the owner is durable — step (3) has returned — before we park.
        if not fx.owner.exists():
            raise AssertionError("hold point reached before the owner write returned")
        parked.set()
        if not release.wait(timeout=WAIT_SECONDS):
            raise AssertionError("parked publisher was never released")
        return original_admit_next(make_request, **kwargs)

    monkeypatch.setattr(fx.store, "admit_next", parked_admit_next)

    def run_publisher():
        try:
            worker["result"] = fx.service.execute(fx.request)
        except BaseException as error:  # re-raised in the test thread
            worker["error"] = error

    thread = threading.Thread(target=run_publisher, name="789-publisher", daemon=True)
    thread.start()

    probe_fd: int | None = None
    try:
        deadline = WAIT_SECONDS
        while not parked.is_set():
            if not thread.is_alive():
                break
            parked.wait(timeout=0.05)
            deadline -= 0.05
            if deadline <= 0:
                pytest.fail("publisher never reached the hold point")
        if not parked.is_set():
            if "error" in worker:
                raise worker["error"]
            pytest.fail(f"publisher finished without parking: {worker.get('result')!r}")

        assert fx.owner.exists(), "the owner is durable while the publisher is parked"
        probe_fd = os.open(str(fx.lock), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as refusal:
            # (i) the acquisition spans owner -> admission: no writer can enter.
            assert refusal.errno in (errno.EWOULDBLOCK, errno.EAGAIN), (
                f"unexpected flock refusal errno on {fx.lock}: {refusal!r}"
            )
            gap_open = False
        else:
            # (ii) the gap is open: an incompatible writer lands a record between
            # the durable owner and the admission, exactly as the incident did.
            seeded = _compatible_record(fx.identity)
            seeded[FUTURE_KEY] = 1
            _append_raw(fx.admissions, seeded)
            fcntl.flock(probe_fd, fcntl.LOCK_UN)
            gap_open = True
    finally:
        release.set()
        if probe_fd is not None:
            os.close(probe_fd)

    thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive(), "publisher did not finish after release"

    if gap_open:
        outcome = worker.get("error", worker.get("result"))
        pytest.fail(
            "789 gap open: a non-blocking flock on "
            f"{fx.lock} succeeded while the owner was durable and the admission not yet "
            f"allocated; a foreign record landed in between and the publisher finished with "
            f"{outcome!r} (incompatible={incompatible is not None and isinstance(outcome, incompatible)}, "
            f"owner_present={fx.owner.exists()}) — the incident chronology"
        )

    if "error" in worker:
        raise worker["error"]
    assert worker["result"].accepted
    assert fx.store.admit_next_calls == 1 and fx.store.allocated_epochs == [1]
    persisted = _jsonl(fx.admissions)
    assert len(persisted) == 1 and persisted[0]["sequence"] == 1
    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is True
    assert persisted[0]["request"]["attempt_id"] == owner["attempt_id"], (
        "the first admission is the parked publisher's own"
    )

    # A REAL later writer (readmit_advanced_head, which never consults the owner)
    # lands strictly AFTER the publisher's admission: zero records in between.
    delta_cls = fabpub_symbol("phase_loop_runtime.convergence.contracts", "DeltaReadmitAuthority")
    envelope = fx.request.admission
    checkpoint = fx.transaction.checkpoint_root
    (checkpoint / "train.json").write_text(
        json.dumps({"train_id": envelope.train_id, "repository": fx.identity}), encoding="utf-8"
    )
    (checkpoint / f"{envelope.node_id}.json").write_text(
        json.dumps({"node_id": envelope.node_id}), encoding="utf-8"
    )
    (fx.worktree / "a.py").write_text("v2 advance\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(fx.worktree), "add", "a.py"], check=True, timeout=60)
    subprocess.run(
        ["git", "-C", str(fx.worktree), "commit", "-q", "-m", "advance"], check=True, timeout=60
    )
    delta_sha = subprocess.check_output(
        ["git", "-C", str(fx.worktree), "rev-parse", "HEAD"], text=True, timeout=60
    ).strip()
    delta_auth = delta_cls(
        repository=fx.identity,
        adapter_worktree=str(fx.worktree),
        checkpoint_root=str(checkpoint),
        branch="feat/x",
        base="main",
        prior_head_sha=fx.transaction.committed_head_sha,
        proposed_head_sha=delta_sha,
        train_id=envelope.train_id,
        node_id=envelope.node_id,
        fab_run_id="run-789",
        roadmap_digest=envelope.roadmap_digest,
        provenance_digest="p" * 64,
        owned_scope=("a.py",),
    )
    readmit: dict = {}

    def run_readmit():
        # Bounded: a lock the publisher failed to release would otherwise hang here.
        try:
            readmit["receipt"] = fx.service.readmit_advanced_head(delta_auth)
        except BaseException as error:  # re-raised in the test thread
            readmit["error"] = error

    readmit_thread = threading.Thread(target=run_readmit, name="789-readmit", daemon=True)
    readmit_thread.start()
    readmit_thread.join(timeout=WAIT_SECONDS)
    if readmit_thread.is_alive():
        pytest.fail(f"readmit_advanced_head did not return within {WAIT_SECONDS}s: admissions.lock still held?")
    if "error" in readmit:
        raise readmit["error"]
    receipt = readmit["receipt"]
    assert receipt is not None and receipt.allocated_epoch == 2
    persisted = _jsonl(fx.admissions)
    assert [record["sequence"] for record in persisted] == [1, 2]
    assert persisted[1]["binding"]["proposed_head_sha"] == delta_sha
    assert fx.adapter.calls[-1].admission.lease_epoch == 1 and len(fx.adapter.calls) == 1


# ---------------------------------------------------------------------------
# ah#803 round-2 falsifiers (codex blocking; fable #1 / #4).
# ---------------------------------------------------------------------------


def _seed_unsealed_foreign_owner(fx: SimpleNamespace):
    """Persist an unsealed owner of another publisher with NO evidence record."""
    owner_cls = fabpub_symbol(VERBS_MODULE, "AdapterStartOwnership")
    assert owner_cls is not None
    foreign = owner_cls(
        fx.identity,
        "foreign-key",
        "foreign-transaction",
        "foreign-attempt",
        "f" * 40,
        "publish_committed_branch",
        "foreign-nonce-0000000000000000",
        "foreign-key",
        False,
    )
    fx.root.mkdir(parents=True, exist_ok=True)
    fx.owner.write_text(
        json.dumps(foreign.__dict__, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return foreign


@_requires_789
def test_incompatible_record_after_probe_refused_inside_block_unsealed_owner(
    tmp_path, request, monkeypatch
):
    """Codex r1 (blocking): the probe→``_block_unsealed_owner`` gap is closed under the lock.

    The early probe succeeds against a compatible store; an incompatible line
    then lands BEFORE ``_block_unsealed_owner`` takes ``admissions.lock`` for an
    unsealed foreign owner.  The refusal must still be typed and must precede
    the PROVIDER_CALL_IN_FLIGHT / OUTCOME_AMBIGUOUS_BLOCKED appends.
    """
    _require(
        request,
        _incompatible_cls() is not None
        and fabpub_symbol(ADMISSION_MODULE, "LinearizableAdmissionStore.probe_readable") is not None,
        "AdmissionStoreIncompatible / probe_readable are absent; the in-lock re-validation "
        "of _block_unsealed_owner cannot be expressed",
    )
    incompatible = _incompatible_cls()
    fx = _routed(tmp_path, name="compat-after-probe-owner")
    _seed_unsealed_foreign_owner(fx)
    original_probe = fx.store.probe_readable
    probe_calls: list[int] = []

    def probe_then_mutate():
        count = original_probe()
        probe_calls.append(count)
        seeded = _compatible_record(fx.identity)
        seeded[FUTURE_KEY] = 1
        _append_raw(fx.admissions, seeded)
        return count

    monkeypatch.setattr(fx.store, "probe_readable", probe_then_mutate)
    before = _snapshot(fx)
    assert before["evidence"] is None or b"foreign-key" not in before["evidence"], (
        "fixture precondition: the foreign owner has NO evidence record yet"
    )

    with pytest.raises(incompatible) as info:
        fx.service.execute(fx.request)

    assert probe_calls == [0], "the early probe ran once against a compatible (empty) store"
    assert FUTURE_KEY in str(info.value)
    assert _read_or_none(fx.evidence) == before["evidence"], (
        "evidence.jsonl must be byte-identical: _block_unsealed_owner re-validates the "
        "admission store under the lock BEFORE appending PROVIDER_CALL_IN_FLIGHT / "
        "OUTCOME_AMBIGUOUS_BLOCKED"
    )
    assert fx.owner.read_bytes() == before["owner"], "the foreign owner must be untouched"
    assert _durable_state(fx.transaction) == before["state"] == "COMMITTED_HEAD_RESOLVED"
    assert fx.adapter.calls == []
    assert fx.store.admit_next_calls == 0


@_requires_789
def test_lock_held_without_lock_fails_loud(tmp_path, request):
    """Fable r1 #1: ``lock_held=True`` with a free ``admissions.lock`` refuses loudly.

    Positive control: with the lock genuinely held on another descriptor, the
    same call proceeds through the critical section and allocates epoch 1.
    """
    _require(
        request,
        _has_lock_held("LinearizableAdmissionStore.admit_next", ADMISSION_MODULE),
        "admit_next carries no lock_held parameter",
    )
    fx = _routed(tmp_path, name="compat-lock-held-guard")
    envelope, _transaction = fx.service._validated_envelope(fx.request)

    def make_request(epoch: int, attempt_id: str):
        return fx.service._final_admission(envelope, fx.request, epoch, attempt_id)

    before = _snapshot(fx)
    with pytest.raises(RuntimeError, match="without admissions.lock held"):
        fx.store.admit_next(
            make_request,
            attempt_id="guard-attempt",
            precondition=lambda: True,
            lock_held=True,
        )
    assert _read_or_none(fx.admissions) == before["admissions"], "nothing was allocated"
    # The guard's own probe acquisition was released: the lock is free again.
    with fx.lock.open("a+", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            record = fx.store.admit_next(
                make_request,
                attempt_id="guard-attempt",
                precondition=lambda: True,
                lock_held=True,
            )
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
    assert record.epoch == 1
    persisted = _jsonl(fx.admissions)
    assert len(persisted) == 1 and persisted[0]["request"]["attempt_id"] == "guard-attempt"


@_requires_789
def test_second_entry_contention_message_is_distinct(tmp_path, request, monkeypatch):
    """Fable r1 #4: losing the section twice is reported as retryable contention."""
    _require(
        request,
        _has_lock_held("append_adapter_start_owner", VERBS_MODULE),
        "the two-entry critical section is absent",
    )
    fx = _routed(tmp_path, name="compat-contended-twice")
    foreign = _seed_unsealed_foreign_owner(fx)
    section_calls: list[str] = []
    block_calls: list[str] = []

    def contended_section(request_, owner, make_request, attempt_id):
        section_calls.append(attempt_id)
        return foreign, None, None

    def retired(owner):
        block_calls.append(owner.effect_key)
        return False

    monkeypatch.setattr(fx.service, "_owner_and_admission_under_one_lock", contended_section)
    monkeypatch.setattr(fx.service, "_block_unsealed_owner", retired)

    with pytest.raises(PermissionError) as info:
        fx.service.execute(fx.request)

    assert "contended twice" in str(info.value) and "retry" in str(info.value)
    assert "blocks fresh provider effect" not in str(info.value)
    # One resolution on the pre-existing pre-section path (the seeded owner is
    # observed before the section) plus one per section entry.
    assert len(section_calls) == 2 and len(block_calls) == 3
    assert fx.adapter.calls == []


# ---------------------------------------------------------------------------
# Positive control — a "define the symbol and always refuse" stub cannot pass.
# ---------------------------------------------------------------------------


@_requires_fabpub
def test_compatible_store_publishes_exactly_once(tmp_path):
    """A compatible store still publishes exactly once through ``admit_next``."""
    fx = _routed(tmp_path, name="compat-positive")

    outcome = fx.service.execute(fx.request)

    assert outcome.accepted
    assert (fx.store.admit_calls, fx.store.admit_next_calls) == (0, 1)
    assert fx.store.allocated_epochs == [1]
    assert len(fx.adapter.calls) == 1
    assert fx.adapter.calls[-1].admission.lease_epoch == 1
    persisted = _jsonl(fx.admissions)
    assert len(persisted) == 1 and persisted[0]["request"]["lease_epoch"] == 1
    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is True and owner["committed_head"] == fx.transaction.committed_head_sha
    assert _durable_state(fx.transaction) == "TERMINAL_SEALED"
