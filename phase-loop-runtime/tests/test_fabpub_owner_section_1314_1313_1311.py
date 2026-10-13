"""FABPUB owner section: refusals leave no owner; liveness before ambiguity.

Follow-ups of the board ruling on Consiliency/agent-harness#1298:

* agent-harness#1311 — the transaction's state changes between ``_fresh_publish``'s
  early validation and the in-lock check of ``_owner_and_admission_under_one_lock``:
  the refusal is typed and no unsealed adapter-start owner remains.
* agent-harness#1314 — every refusal inside ``admit_next`` after the owner write
  restores the owner path to the exact bytes the section found.
* agent-harness#1313 — an unsealed owner whose writer is still alive is NOT
  promoted to permanent ambiguity: the refusal is retryable and writes nothing.

Every store here is a real routed store in an activated repository partition,
built by the shared-epoch helpers through the 789-compat ``_routed`` fixture.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_admission_compat_789 import (
    _durable_state,
    _read_or_none,
    _routed,
    _seed_unsealed_foreign_owner,
)
from test_fabpub_shared_epoch import _CountingAdapter, _jsonl, _service

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

AMBIGUOUS = "outcome_ambiguous_blocked"
WAIT_SECONDS = 30.0


def _verbs():
    from phase_loop_runtime.convergence.broker import verbs

    return verbs


def _state(fx) -> dict:
    return {
        "admissions": _read_or_none(fx.admissions),
        "evidence": _read_or_none(fx.evidence),
        "owner": _read_or_none(fx.owner),
    }


def _hold(path: Path) -> int:
    """A live writer's lock on the current owner inode, from a separate descriptor."""
    descriptor = os.open(str(path), os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


def _seed_sealed_owner_bytes(fx) -> bytes:
    """A sealed prior owner, serialized unlike this runtime would (pretty-printed).

    The restore must put these exact bytes back, not a re-serialization.
    """
    owner = _verbs().AdapterStartOwnership(
        fx.identity,
        "prior-key",
        "prior-transaction",
        "prior-attempt",
        "e" * 40,
        "publish_committed_branch",
        "prior-nonce-00000000000000000000",
        "prior-key",
        True,
    )
    body = (json.dumps(owner.__dict__, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fx.root.mkdir(parents=True, exist_ok=True)
    fx.owner.write_bytes(body)
    return body


# ---------------------------------------------------------------------------
# agent-harness#1311: the in-lock state check under a race
# ---------------------------------------------------------------------------


def test_state_change_between_early_validation_and_section_leaves_no_owner(tmp_path, monkeypatch):
    fx = _routed(tmp_path, name="race-1311")
    before = _state(fx)
    assert before["owner"] is None
    original = fx.service._validated_envelope
    calls: list[str] = []

    def racing_validated_envelope(request):
        calls.append(_durable_state(fx.transaction))
        if len(calls) == 2:
            # The in-section call: another writer advanced the transaction after
            # ``_fresh_publish``'s early validation passed.
            fx.transaction.project("ADMISSION_DURABLE")
        return original(request)

    monkeypatch.setattr(fx.service, "_validated_envelope", racing_validated_envelope)

    with pytest.raises(PermissionError) as info:
        fx.service.execute(fx.request)

    message = str(info.value)
    assert "precondition denied" in message and "ADMISSION_DURABLE" in message
    assert "no owner or admission was written" in message
    assert calls == ["COMMITTED_HEAD_RESOLVED", "COMMITTED_HEAD_RESOLVED"]
    assert not fx.owner.exists(), "an unsealed adapter-start owner remained"
    assert _state(fx) == before
    assert fx.store.admit_next_calls == 0
    assert fx.adapter.calls == []


# ---------------------------------------------------------------------------
# agent-harness#1314: refusals inside admit_next after the owner write
# ---------------------------------------------------------------------------


def _deny_policy(fx, monkeypatch):
    monkeypatch.setattr(fx.store, "policy", lambda _request: False)
    return PermissionError, "broker admission denied"


def _block_epoch(fx, monkeypatch):
    monkeypatch.setattr(fx.store, "epoch_blocked", lambda: True)
    return PermissionError, "broker admission denied"


def _lose_generation(fx, monkeypatch):
    original = fx.store._require_generation

    def require_generation():
        # The store's revalidation inside ``admit_next``, after this attempt's
        # unsealed owner is durable, is the one that refuses.
        if fx.owner.exists() and json.loads(fx.owner.read_text(encoding="utf-8"))["sealed"] is False:
            raise PermissionError("writer generation lease was superseded")
        return original()

    monkeypatch.setattr(fx.store, "_require_generation", require_generation)
    return PermissionError, "writer generation lease was superseded"


def _break_make_request(fx, monkeypatch):
    def broken(*_args, **_kwargs):
        raise ValueError("admission request could not be built")

    monkeypatch.setattr(fx.service, "_final_admission", broken)
    return ValueError, "admission request could not be built"


REFUSALS = {
    "policy": _deny_policy,
    "epoch_blocked": _block_epoch,
    "generation": _lose_generation,
    "make_request": _break_make_request,
}


@pytest.mark.parametrize("prior", ["absent", "sealed"])
@pytest.mark.parametrize("refusal", sorted(REFUSALS))
def test_refusal_after_owner_write_restores_owner_bytes(tmp_path, monkeypatch, refusal, prior):
    fx = _routed(tmp_path, name=f"refuse-{refusal}-{prior}")
    prior_bytes = _seed_sealed_owner_bytes(fx) if prior == "sealed" else None
    before = _state(fx)
    assert before["owner"] == prior_bytes
    written: list = []
    verbs = _verbs()
    original_append = verbs.evidence_module.append_adapter_start_owner

    def witnessed_append(*args, **kwargs):
        recorded = original_append(*args, **kwargs)
        written.append(json.loads(fx.owner.read_text(encoding="utf-8")))
        return recorded

    monkeypatch.setattr(verbs.evidence_module, "append_adapter_start_owner", witnessed_append)
    error_type, text = REFUSALS[refusal](fx, monkeypatch)

    with pytest.raises(error_type) as info:
        fx.service.execute(fx.request)

    assert text in str(info.value)
    # The refusal really came after a durable owner write of THIS attempt.
    assert len(written) == 1 and written[0]["sealed"] is False
    assert written[0]["transaction_id"] == fx.transaction.transaction_id
    # ... and the section put the owner path back exactly as it found it.
    assert _read_or_none(fx.owner) == prior_bytes
    assert _state(fx) == before
    assert fx.adapter.calls == []
    assert _durable_state(fx.transaction) == "COMMITTED_HEAD_RESOLVED"

    # No blocker remains: once the refusal's cause is gone the head publishes.
    monkeypatch.undo()
    outcome = fx.service.execute(fx.request)
    assert outcome.accepted is True
    assert len(fx.adapter.calls) == 1
    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is True and owner["transaction_id"] == fx.transaction.transaction_id


def test_crash_inside_admit_next_gets_no_cleanup(tmp_path, monkeypatch):
    """A simulated crash keeps the owner a real crash would leave behind."""
    from phase_loop_runtime.publishing import PublishCrashInjected

    fx = _routed(tmp_path, name="refuse-crash")

    def crashing_admit_next(*_args, **_kwargs):
        raise PublishCrashInjected("FABPUB crash injected inside admit_next")

    monkeypatch.setattr(fx.store, "admit_next", crashing_admit_next)
    with pytest.raises(PublishCrashInjected):
        fx.service.execute(fx.request)

    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is False
    assert owner["transaction_id"] == fx.transaction.transaction_id
    # The crashed attempt's liveness lock went with it: the owner reads dead.
    assert _verbs()._owner_writer_alive(fx.root) is False


# ---------------------------------------------------------------------------
# agent-harness#1313: liveness before promotion to ambiguity
# ---------------------------------------------------------------------------


def test_live_writer_owner_refuses_retryable_then_dead_owner_promotes(tmp_path):
    verbs = _verbs()
    fx = _routed(tmp_path, name="live-1313")
    _seed_unsealed_foreign_owner(fx)
    before = _state(fx)
    descriptor = _hold(fx.owner)
    try:
        with pytest.raises(verbs.AdapterStartOwnerLive) as info:
            fx.service.execute(fx.request)
        assert "retry" in str(info.value) and "No evidence was written" in str(info.value)
        assert _state(fx) == before, "a live owner was promoted or the store moved"
        assert fx.adapter.calls == []
    finally:
        os.close(descriptor)

    # The writer is gone (its lock released): promotion exactly as before.
    with pytest.raises(PermissionError) as info:
        fx.service.execute(fx.request)
    assert not isinstance(info.value, verbs.AdapterStartOwnerLive)
    assert "blocks fresh provider effect" in str(info.value)
    states = [row["state"] for row in _jsonl(fx.evidence) if row.get("idempotency_key") == "foreign-key"]
    assert states[-1] == AMBIGUOUS
    assert fx.adapter.calls == []


class _ParkedAdapter(_CountingAdapter):
    """Parks inside the provider call until released."""

    def __init__(self) -> None:
        super().__init__()
        self.parked = threading.Event()
        self.release = threading.Event()

    def execute(self, request):
        self.parked.set()
        if not self.release.wait(timeout=WAIT_SECONDS):
            raise AssertionError("parked provider call was never released")
        return super().execute(request)


def test_concurrent_attempt_does_not_promote_a_live_writer(tmp_path):
    """Two services in one process: the second must not poison the first's attempt."""
    verbs = _verbs()
    fx = _routed(tmp_path, name="live-concurrent-1313")
    parked = _ParkedAdapter()
    fx.service.adapter = parked
    worker: dict = {}

    def run_first():
        try:
            worker["result"] = fx.service.execute(fx.request)
        except BaseException as error:  # re-raised below
            worker["error"] = error

    thread = threading.Thread(target=run_first, name="1313-writer", daemon=True)
    thread.start()
    try:
        assert parked.parked.wait(timeout=WAIT_SECONDS), "the first attempt never reached the provider"
        assert json.loads(fx.owner.read_text(encoding="utf-8"))["sealed"] is False
        evidence_before = _read_or_none(fx.evidence)

        second_adapter = _CountingAdapter()
        second = _service(fx.root, second_adapter, store=fx.store)
        with pytest.raises(verbs.AdapterStartOwnerLive):
            second.execute(fx.request)
        assert _read_or_none(fx.evidence) == evidence_before, "the live attempt was promoted"
        assert second_adapter.calls == []
    finally:
        parked.release.set()
        thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive()
    if "error" in worker:
        raise worker["error"]
    first = worker["result"]
    assert first.accepted is True, first.reason
    assert len(parked.calls) == 1
    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is True
    assert AMBIGUOUS not in {row["state"] for row in _jsonl(fx.evidence)}
    # The finished attempt released its lock.
    assert verbs._owner_writer_alive(fx.root) is False


_HOLDER = """
import fcntl, os, sys, time
descriptor = os.open(sys.argv[1], os.O_RDWR)
fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("locked", flush=True)
time.sleep(600)
"""


def test_killed_writer_reads_dead(tmp_path):
    """Process death releases the lock: a SIGKILLed writer's owner is promoted."""
    verbs = _verbs()
    fx = _routed(tmp_path, name="killed-1313")
    _seed_unsealed_foreign_owner(fx)
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(fx.owner)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert verbs._owner_writer_alive(fx.root) is True
        with pytest.raises(verbs.AdapterStartOwnerLive):
            fx.service.execute(fx.request)
    finally:
        holder.kill()
        holder.wait(timeout=WAIT_SECONDS)
        holder.stdout.close()

    assert verbs._owner_writer_alive(fx.root) is False
    with pytest.raises(PermissionError) as info:
        fx.service.execute(fx.request)
    assert "blocks fresh provider effect" in str(info.value)
    assert fx.service.evidence_store.epoch_blocked is True


# ---------------------------------------------------------------------------
# agent-harness#1577: never call the provider for a key that is no longer this
# attempt's in-flight record.  The prober below is an OLDER runtime: it takes
# no notice of the writer's liveness lock (``_owner_writer_alive`` reads dead).
# ---------------------------------------------------------------------------


IN_FLIGHT = "provider_call_in_flight"


def _key_states(fx, key: str) -> list[str]:
    return [row["state"] for row in _jsonl(fx.evidence) if row.get("idempotency_key") == key]


def _old_prober(fx, monkeypatch):
    """Promote the writer's owner the way a runtime without agent-harness#1313 would."""
    verbs = _verbs()
    monkeypatch.setattr(verbs, "_owner_writer_alive", lambda _root: False)
    owner = verbs.read_adapter_start_owner(fx.root, repository_identity=fx.identity)
    assert owner is not None and owner.sealed is False
    prober = _service(fx.root, _CountingAdapter(), store=fx.store)
    assert prober._block_unsealed_owner(owner) is True


def test_promotion_before_provider_entry_refuses_without_call(tmp_path, monkeypatch):
    """Window (b): promoted after the section, before the guard; the writer must not call it."""
    fx = _routed(tmp_path, name="promote-before-entry-1577")
    key = fx.service._dedup_key(fx.request)
    parked = threading.Event()
    release = threading.Event()
    original_intent = fx.service.evidence_store.record_intent

    def parked_intent(intent_key):
        parked.set()
        if not release.wait(timeout=WAIT_SECONDS):
            raise AssertionError("parked writer was never released")
        return original_intent(intent_key)

    fx.service.evidence_store.record_intent = parked_intent
    worker: dict = {}

    def run_writer():
        try:
            worker["result"] = fx.service.execute(fx.request)
        except BaseException as error:  # re-raised below
            worker["error"] = error

    thread = threading.Thread(target=run_writer, name="1577-writer", daemon=True)
    thread.start()
    try:
        assert parked.wait(timeout=WAIT_SECONDS), "the writer never left the section"
        _old_prober(fx, monkeypatch)
        assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    finally:
        release.set()
        thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive()
    if "error" in worker:
        raise AssertionError(f"the writer raised instead of returning the stored row: {worker['error']!r}")
    result = worker["result"]
    assert fx.adapter.calls == [], "the provider was called for a key promoted to ambiguity"
    assert result.accepted is False
    assert result.reason == "outcome_ambiguous"
    assert result.evidence.terminal_state == AMBIGUOUS
    assert result.evidence.evidence_reference == "unsealed-adapter-start-owner"
    assert result.provider_call_made is False
    # Nothing written by the writer after the promotion; the owner stays unsealed.
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    assert json.loads(fx.owner.read_text(encoding="utf-8"))["sealed"] is False
    assert _durable_state(fx.transaction) == "BROKER_INTENT_DURABLE"


def test_promotion_during_provider_call_is_documented_residual(tmp_path, monkeypatch):
    """Window (a), split out to agent-harness#1591: promoted while the provider call runs.

    No guard before the call can see a promotion that happens during it.  This
    pins today's outcome: one provider call, and the key stays ambiguous.
    """
    fx = _routed(tmp_path, name="promote-during-call-1591")
    key = fx.service._dedup_key(fx.request)
    parked = _ParkedAdapter()
    fx.service.adapter = parked
    worker: dict = {}

    def run_writer():
        try:
            worker["result"] = fx.service.execute(fx.request)
        except BaseException as error:  # re-raised below
            worker["error"] = error

    thread = threading.Thread(target=run_writer, name="1591-writer", daemon=True)
    thread.start()
    try:
        assert parked.parked.wait(timeout=WAIT_SECONDS), "the writer never reached the provider"
        _old_prober(fx, monkeypatch)
    finally:
        parked.release.set()
        thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive()
    if "error" in worker:
        raise worker["error"]
    result = worker["result"]
    assert len(parked.calls) == 1
    assert result.accepted is False
    assert result.evidence.terminal_state == AMBIGUOUS
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    assert fx.service.evidence_store.epoch_blocked is True


def test_promotion_after_guard_lock_release_is_documented_residual(tmp_path, monkeypatch):
    """Window (a) starts at the guard's lock release, not at provider entry (agent-harness#1591).

    The guard releases ``admissions.lock`` before the ``ADAPTER_STARTED``
    projection, request finalization, lease acquisition and the call, and nothing
    re-checks after it.  A promotion landing in that interval still makes one
    provider call, honestly reported with ``provider_call_made: true``.
    """
    from phase_loop_runtime.publishing import PublishTransaction

    fx = _routed(tmp_path, name="promote-after-guard-1591")
    key = fx.service._dedup_key(fx.request)
    real_project = PublishTransaction.project
    promoted: list[str] = []

    def project(self, state):
        result = real_project(self, state)
        if state == "ADAPTER_STARTED" and not promoted:
            # The guard has released admissions.lock; the provider is not entered yet.
            assert fx.adapter.calls == []
            _old_prober(fx, monkeypatch)
            promoted.append(state)
        return result

    monkeypatch.setattr(PublishTransaction, "project", project)
    result = fx.service.execute(fx.request)

    assert promoted == ["ADAPTER_STARTED"]
    assert len(fx.adapter.calls) == 1
    assert result.accepted is False
    assert result.evidence.terminal_state == AMBIGUOUS
    assert result.provider_call_made is True
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    assert fx.service.evidence_store.epoch_blocked is True


# ---------------------------------------------------------------------------
# agent-harness#1578 ask 1, option (i): a failed ADMISSION_DURABLE projection
# restores the owner only while nothing past COMMITTED_HEAD_RESOLVED is durable.
# ---------------------------------------------------------------------------


def _fail_admission_durable(monkeypatch, *, after_write: bool):
    from phase_loop_runtime.publishing import PublishTransaction

    real_project = PublishTransaction.project

    def project(self, state):
        if state == "ADMISSION_DURABLE":
            if after_write:
                real_project(self, state)
            raise OSError("simulated ADMISSION_DURABLE checkpoint failure")
        return real_project(self, state)

    monkeypatch.setattr(PublishTransaction, "project", project)


@pytest.mark.parametrize("prior", ["absent", "sealed"])
def test_admission_durable_failure_restores_owner(tmp_path, monkeypatch, prior):
    fx = _routed(tmp_path, name=f"admission-durable-{prior}-1578")
    prior_bytes = _seed_sealed_owner_bytes(fx) if prior == "sealed" else None
    key = fx.service._dedup_key(fx.request)
    _fail_admission_durable(monkeypatch, after_write=False)

    with pytest.raises(OSError, match="ADMISSION_DURABLE checkpoint failure"):
        fx.service.execute(fx.request)

    assert _read_or_none(fx.owner) == prior_bytes, "this attempt's owner was left behind"
    assert _key_states(fx, key) == []
    assert _durable_state(fx.transaction) == "COMMITTED_HEAD_RESOLVED"
    assert fx.adapter.calls == []
    # The admission line stays (``admit_next`` dedups the retry by attempt id).
    assert fx.store.admit_next_calls == 1

    monkeypatch.undo()
    outcome = fx.service.execute(fx.request)
    assert outcome.accepted is True, outcome.reason
    assert len(fx.adapter.calls) == 1
    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is True and owner["transaction_id"] == fx.transaction.transaction_id


def _assert_left_for_rotation(fx, monkeypatch, key: str) -> None:
    """The owner stays; the next attempt promotes it, which a rotation adjudicates."""
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    owner = json.loads(fx.owner.read_text(encoding="utf-8"))
    assert owner["sealed"] is False and owner["transaction_id"] == fx.transaction.transaction_id
    assert _key_states(fx, key) == []
    assert fx.adapter.calls == []

    monkeypatch.undo()
    with pytest.raises(PermissionError) as info:
        fx.service.execute(fx.request)
    # A restored owner would strand the admitted checkpoint behind
    # ``_recovery_authority`` ("a rotation cannot help here").
    assert not isinstance(info.value, PublicationRecoveryRequired), str(info.value)
    assert "blocks fresh provider effect" in str(info.value)
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    assert fx.adapter.calls == []


def test_evidence_generation_loss_leaves_owner_for_rotation(tmp_path, monkeypatch):
    """A superseded generation's writer must not touch that generation's owner."""
    from phase_loop_runtime.convergence.broker import evidence as evidence_module

    fx = _routed(tmp_path, name="generation-loss-1578")
    key = fx.service._dedup_key(fx.request)
    original = evidence_module._require_generation

    def require_generation(root, lease):
        if fx.owner.exists() and json.loads(fx.owner.read_text(encoding="utf-8"))["sealed"] is False:
            raise PermissionError("writer generation lease was superseded")
        return original(root, lease)

    monkeypatch.setattr(evidence_module, "_require_generation", require_generation)
    _fail_admission_durable(monkeypatch, after_write=False)

    with pytest.raises(OSError, match="ADMISSION_DURABLE checkpoint failure"):
        fx.service.execute(fx.request)
    assert _durable_state(fx.transaction) == "COMMITTED_HEAD_RESOLVED"
    _assert_left_for_rotation(fx, monkeypatch, key)


def test_admission_durable_written_then_failing_leaves_owner_for_rotation(tmp_path, monkeypatch):
    """The projection is durable but reports failure: the checkpoint is admitted, so no restore."""
    fx = _routed(tmp_path, name="admission-durable-written-1578")
    key = fx.service._dedup_key(fx.request)
    _fail_admission_durable(monkeypatch, after_write=True)

    with pytest.raises(OSError, match="ADMISSION_DURABLE checkpoint failure"):
        fx.service.execute(fx.request)
    assert _durable_state(fx.transaction) == "ADMISSION_DURABLE"
    _assert_left_for_rotation(fx, monkeypatch, key)


# ---------------------------------------------------------------------------
# agent-harness#1576 ask 2: the #1314 restore on the RECOVERY path (closed in
# code by agent-harness#1551), then a clean retry.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed_sealed_other_key", [False, True])
def test_recovery_path_epoch_block_restores_owner(tmp_path, monkeypatch, seed_sealed_other_key):
    from test_fabpub_partition_rotation_789d import _release_router, _successor_service
    from test_fabpub_sealed_head_recovery_1296 import (
        ATTESTED_NOT_LANDED,
        _attestation,
        _failed_sealed_publish,
        _publish_on_successor,
        _rotate,
    )

    verbs = _verbs()
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    owner_path = outcome.store_root / "adapter-start-owner.json"
    if seed_sealed_other_key:
        other = verbs.AdapterStartOwnership(
            p.identity, "other-key", "other-tx", "other-attempt", "e" * 40,
            "publish_committed_branch", "other-nonce", "other-key", True,
        )
        owner_path.write_bytes((json.dumps(other.__dict__, indent=2, sort_keys=True) + "\n").encode())
    before = _read_or_none(owner_path)
    evidence_before = _read_or_none(outcome.store_root / "evidence.jsonl")

    adapter = _CountingAdapter()
    routed = _successor_service(None, outcome, p, adapter)
    try:
        # The admission store's in-lock epoch check (inside ``admit_next``, after
        # the owner write) is the one that refuses.
        routed.service.admission_store.epoch_blocked = lambda: True
        with pytest.raises(PermissionError) as info:
            routed.service.execute(p.request)
    finally:
        _release_router(routed)
    assert "broker admission denied" in str(info.value)
    assert adapter.calls == []
    assert _read_or_none(owner_path) == before, "the recovery attempt's owner was left behind"
    assert _read_or_none(outcome.store_root / "evidence.jsonl") == evidence_before

    retry, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(retry, Exception), f"recovery retry refused: {retry!r}"
    assert retry.accepted is True, retry.reason
    assert len(calls) == 1
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert owner["sealed"] is True and owner["transaction_id"] == p.transaction.transaction_id
