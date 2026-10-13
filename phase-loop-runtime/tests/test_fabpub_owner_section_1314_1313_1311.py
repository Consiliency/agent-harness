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
