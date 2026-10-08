"""Consiliency/agent-harness#1296: recovery of a sealed, failed current-head publication.

A publication whose adapter returned ``outcome_ambiguous_blocked`` leaves the
publish transaction ``TERMINAL_SEALED`` (the broker seals on every terminal
class) and the partition ambiguity-blocked with an unsealed adapter-start
owner.  The supported recovery is a partition rotation whose operator
attestation disposes the effect ``attested_not_landed``.  On 0.7.24 the
successor then routed the retry to ``_fresh_publish``, wrote a fresh owner and
refused at admission (``broker admission precondition denied``) because the
precondition required ``COMMITTED_HEAD_RESOLVED``: the supported recovery
rejected the very transaction it exists to recover, and left a new blocker.

``test_fabpub_partition_rotation_789d.py`` A2 never saw this: it blocks a
``COMMITTED_HEAD_RESOLVED`` transaction synthetically.  Every test here drives
the block through a real failed publish, so the transaction is sealed exactly
as production seals it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_partition_rotation_789d import (
    ATTESTED_NOT_LANDED,
    OBSERVED_LANDED,
    _attestation,
    _block_key,
    _bootstrap,
    _publish_on_successor,
    _release_all,
    _release_router,
    _rotate,
    _routed_service,
    _store_bytes,
)
from test_fabpub_recovery_controls_789 import _no_remote_probe
from test_fabpub_shared_epoch import _CountingAdapter, _git, _jsonl, _stage

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

AMBIGUOUS = "outcome_ambiguous_blocked"


def _inspect(p):
    from phase_loop_runtime.publishing import inspect_publish_resume_candidate

    return inspect_publish_resume_candidate(
        p.repo,
        checkpoint_root=p.transaction.checkpoint_root,
        node_id=p.transaction.store.node_id,
    )


def _checkpoint_bytes(p) -> dict[str, bytes]:
    """Every byte of the transaction store, keyed by file name."""
    root = p.transaction.store.root
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def _failed_sealed_publish(tmp_path, monkeypatch):
    """Bootstrap, then a REAL publish whose provider outcome is ambiguous.

    Returns the fixture, alpha's partition and the effect key.  Afterwards the
    transaction is ``TERMINAL_SEALED`` for the current head, generation 0 holds
    one ``outcome_ambiguous_blocked`` row and an UNSEALED owner naming the key:
    the incident shape of treesitter-chunker#480.
    """
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    p.service.adapter = _CountingAdapter(terminal_state=AMBIGUOUS)
    key = p.service._dedup_key(p.request)
    failed = p.service.execute(p.request)
    assert failed.accepted is False
    assert failed.evidence.terminal_state == AMBIGUOUS
    assert len(p.service.adapter.calls) == 1
    assert _inspect(p).state == "TERMINAL_SEALED"
    owner = json.loads((p.container / "adapter-start-owner.json").read_text(encoding="utf-8"))
    assert owner["effect_key"] == key and owner["sealed"] is False
    assert owner["transaction_id"] == p.transaction.transaction_id
    assert p.service.evidence_store.epoch_blocked is True
    return fx, p, key


def _broker_state(root: Path) -> dict:
    """Store bytes minus the lock file, which opening the section creates empty."""
    return {name: data for name, data in _store_bytes(root).items() if name != "admissions.lock"}


def _owner(root: Path) -> dict | None:
    path = root / "adapter-start-owner.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_sealed_head_attested_not_landed_publishes_the_exact_candidate_once(tmp_path, monkeypatch):
    """The incident: one provider call for the exact sealed candidate, then provider-free replay."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    attestation = _attestation(p, dispositions={key: ATTESTED_NOT_LANDED})
    assert attestation["effects"][key]["transaction_id"] == p.transaction.transaction_id
    outcome = _rotate(None, p, attestation=attestation)
    assert outcome.state == "ACTIVE" and outcome.generation == 1
    gen0 = _store_bytes(p.container)
    checkpoint = _checkpoint_bytes(p)

    adapter = _CountingAdapter()
    with _no_remote_probe(monkeypatch) as probes:
        first, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
        assert not isinstance(first, Exception), f"recovery refused: {first!r}"
        assert first.accepted is True, first.reason
        assert len(calls) == 1, "the recovered candidate must reach the provider exactly once"
        sent = calls[0]
        assert (sent.branch, sent.head_sha) == (p.request.branch, p.transaction.expected_commit_oid)
        assert tuple(sent.owned_paths) == tuple(p.transaction.owned_paths)
        assert sent.admission.fence_token == p.transaction.transaction_id

        replay, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
        assert not isinstance(replay, Exception), f"replay refused: {replay!r}"
        assert replay.accepted is True
        assert len(calls) == 1, "the replay reached the provider again"
        assert replay.evidence.evidence_reference == first.evidence.evidence_reference
    assert probes == []

    # The predecessor generation and the original checkpoint bytes are untouched.
    assert _store_bytes(p.container) == gen0
    after = _checkpoint_bytes(p)
    assert {name: after[name] for name in checkpoint} == checkpoint
    assert _inspect(p).state == "TERMINAL_SEALED"
    # The successor owner is sealed by the observed terminal: no new blocker.
    owner = _owner(outcome.store_root)
    assert owner is not None and owner["sealed"] is True
    assert owner["transaction_id"] == p.transaction.transaction_id

    # Provenance: one write-once record beside the checkpoint binds the recovery.
    added = sorted(set(after) - set(checkpoint))
    assert added == [f"{p.transaction.transaction_id}.recovery.1.json"], added
    record = json.loads(after[added[0]])
    predecessor_owner = attestation["effects"][key]
    assert record["schema"] == "PublishTransactionRecovery.v1"
    assert record["recovered_transaction_state"] == "TERMINAL_SEALED"
    assert record["effect_key"] == key
    assert record["transaction_id"] == p.transaction.transaction_id
    assert record["predecessor_owner_nonce"] == predecessor_owner["owner_nonce"]
    assert record["ambiguity_digest"] == predecessor_owner["ambiguity_digest"]
    assert record["cutover_id"] == outcome.cutover_id
    assert record["attestation_sha256"] == outcome.receipt.attestation_sha256
    assert record["inventory_sha256"] == outcome.receipt.inventory_sha256
    assert (record["predecessor_generation"], record["generation"]) == (0, 1)
    assert record["expected_commit_oid"] == p.transaction.expected_commit_oid
    assert record["exact_ref"] == p.transaction.exact_ref
    assert record["owned_paths"] == list(p.transaction.owned_paths)
    assert record["roadmap_digest"] == p.request.admission.roadmap_digest
    assert record["verification_plan_digest"] == p.request.admission.verification_plan_digest
    assert record["historical_disposition"] == ATTESTED_NOT_LANDED
    assert p.adapter.calls == []  # the original fixture adapter was replaced, never reached


def test_sealed_head_observed_landed_replays_without_provider_or_owner(tmp_path, monkeypatch):
    """``observed_landed`` over a sealed transaction stays a provider-free duplicate."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    attestation = _attestation(
        p, dispositions={key: OBSERVED_LANDED}, observed_head=p.transaction.expected_commit_oid
    )
    outcome = _rotate(None, p, attestation=attestation)
    checkpoint = _checkpoint_bytes(p)
    with _no_remote_probe(monkeypatch) as probes:
        result, calls = _publish_on_successor(None, outcome, p, p.request)
    assert probes == []
    assert not isinstance(result, Exception), f"duplicate refused: {result!r}"
    assert result.accepted is True
    assert calls == []
    assert _owner(outcome.store_root) is None
    assert _checkpoint_bytes(p) == checkpoint


@pytest.mark.parametrize("state", ["ADMISSION_DURABLE", "ADAPTER_STARTED", "TERMINAL_SEALED"])
def test_unadjudicated_sealed_transaction_refuses_without_owner_or_admission(tmp_path, monkeypatch, state):
    """No rotation adjudicated the key: refuse typed, before ANY owner/admission write."""
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    while p.transaction.state != state:
        from phase_loop_runtime.publishing import PublishTransactionState as S

        p.transaction.project(S.ORDERED[S.ORDERED.index(p.transaction.state) + 1])
    before = _broker_state(p.container)
    with _no_remote_probe(monkeypatch) as probes:
        with pytest.raises(PermissionError) as refused:
            p.service.execute(p.request)
    assert probes == []
    assert p.adapter.calls == []
    assert _broker_state(p.container) == before, "the refusal wrote broker state"
    assert _owner(p.container) is None
    assert isinstance(refused.value, PublicationRecoveryRequired)
    message = str(refused.value)
    assert state in message
    assert p.transaction.transaction_id in message
    assert "attested_not_landed" in message
    # No disposition and no evidence for the key: a rotation cannot dispose it (board item 4).
    assert "a rotation cannot help here" in message and "agent-harness#1310" in message


def test_sealed_head_without_bound_transaction_refuses_after_rotation(tmp_path, monkeypatch):
    """A not-landed disposition that binds no transaction id authorizes nothing.

    The block here has no adapter-start owner, so the attestation (correctly)
    carries no ``transaction_id``.  Recovery must not infer the binding.
    """
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired
    from phase_loop_runtime.publishing import PublishTransactionState as S

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    key = p.service._dedup_key(p.request)
    while p.transaction.state != S.TERMINAL_SEALED:
        p.transaction.project(S.ORDERED[S.ORDERED.index(p.transaction.state) + 1])
    _block_key(p, key)
    attestation = _attestation(p, dispositions={key: ATTESTED_NOT_LANDED})
    assert "transaction_id" not in attestation["effects"][key]
    outcome = _rotate(None, p, attestation=attestation)
    result, calls = _publish_on_successor(None, outcome, p, p.request)
    assert isinstance(result, PublicationRecoveryRequired), result
    assert "binds no transaction" in str(result)
    assert calls == []
    assert _owner(outcome.store_root) is None
    assert _jsonl(outcome.store_root / "admissions.jsonl") == []


def test_sealed_head_recovery_is_single_use_after_a_second_failure(tmp_path, monkeypatch):
    """A recovery attempt that fails again blocks the successor; it is not retried blindly."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    again = _CountingAdapter(terminal_state=AMBIGUOUS)
    first, calls = _publish_on_successor(None, outcome, p, p.request, adapter=again)
    assert not isinstance(first, Exception) and first.accepted is False
    assert len(calls) == 1
    second, calls = _publish_on_successor(None, outcome, p, p.request, adapter=again)
    assert not isinstance(second, Exception), second
    assert second.accepted is False and second.evidence.terminal_state == AMBIGUOUS
    assert len(calls) == 1, "an ambiguous recovery attempt was retried without a new rotation"


def test_publish_from_worktree_recovers_the_sealed_current_head(tmp_path, monkeypatch):
    """The SDK route: fail, rotate, then the same publish call completes the same commit."""
    from phase_loop_runtime.publishing import PublishAuthorityPreimages, publish_from_worktree
    from test_fabpub_shared_epoch import _authority_preimage

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    _git(p.repo, "checkout", "-q", "-b", "feat/sdk")
    _stage(p.repo, "sdk.py", "def sdk():\n    return 1\n")
    root = tmp_path / "coordinator" / "sdk"
    authority = PublishAuthorityPreimages(root, _authority_preimage(p.identity, "feat/sdk"))

    def publish(adapter):
        routed = _routed_service(p, adapter)
        try:
            return publish_from_worktree(
                p.repo,
                ("sdk.py",),
                broker_client=routed.service,
                publish_authority=authority,
                checkpoint_root=root,
            )
        finally:
            _release_router(routed)

    _release_all(p)
    failed = publish(_CountingAdapter(terminal_state=AMBIGUOUS))
    assert failed["status"] == "publication_blocked", failed
    head = _git(p.repo, "rev-parse", "HEAD")
    gen0_evidence = _jsonl(p.container / "evidence.jsonl")
    key = gen0_evidence[-1]["idempotency_key"]
    assert gen0_evidence[-1]["state"] == AMBIGUOUS
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    assert outcome.generation == 1
    adapter = _CountingAdapter()
    published = publish(adapter)
    assert published["status"] == "published", published
    assert published["head_sha"] == head, "recovery published a different commit"
    assert len(adapter.calls) == 1
    again = publish(adapter)
    assert again["status"] == "published", again
    assert len(adapter.calls) == 1
    assert _git(p.repo, "rev-parse", "HEAD") == head


def test_human_handoff_names_the_rotation_recovery(tmp_path, monkeypatch):
    """The human route reports the precise next step, not a generic authority repair."""
    from phase_loop_runtime.publishing import _human_publication_handoff

    fx = _bootstrap(tmp_path, monkeypatch)
    handoff = _human_publication_handoff(
        fx.alpha.repo, next_step="resolve_publication_recovery_refusal"
    )
    assert handoff["next_step"] == "resolve_publication_recovery_refusal"
    assert "only while the key is blocked" in handoff["next_step_source"]
    assert handoff["rotate_command_when_key_blocked"][:2] == ["phase-loop", "fabpub-rotate-partition"]
    assert str(fx.alpha.repo.resolve()) in handoff["rotate_command_when_key_blocked"]
    assert "attested_not_landed" in handoff["rotate_requires"]
    assert "not proof" in handoff["rotate_requires"]


def test_adapter_exception_leaves_an_admitted_transaction_that_rotation_recovers(tmp_path, monkeypatch):
    """An adapter EXCEPTION leaves the transaction ADAPTER_STARTED, not sealed; same recovery."""
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    p.service.adapter = _CountingAdapter(explode=True)
    key = p.service._dedup_key(p.request)
    failed = p.service.execute(p.request)
    assert failed.accepted is False and failed.reason == "outcome_ambiguous"
    assert _inspect(p).state == "ADAPTER_STARTED"
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    checkpoint = _checkpoint_bytes(p)
    adapter = _CountingAdapter()
    first, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(first, Exception), f"recovery refused: {first!r}"
    assert first.accepted is True and len(calls) == 1
    replay, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert replay.accepted is True and len(calls) == 1
    after = _checkpoint_bytes(p)
    assert {name: after[name] for name in checkpoint} == checkpoint
    # Broker layer only: the broker never moves the checkpoint.  The SDK closeout
    # seals it afterwards (test_sdk_recovery_after_an_adapter_exception_seals_...).
    assert _inspect(p).state == "ADAPTER_STARTED", "the broker layer projected the checkpoint"
    record = json.loads(after[f"{p.transaction.transaction_id}.recovery.1.json"])
    assert record["recovered_transaction_state"] == "ADAPTER_STARTED"


def test_concurrent_retry_after_a_recovered_publish_makes_no_second_provider_call(tmp_path, monkeypatch):
    """A retry that passed ``execute``'s replay check before the first attempt's
    terminal reaches ``_fresh_publish`` with a sealed successor owner.  The
    broker never moves the checkpoint under recovery, so the state cannot stop
    it; the in-lock evidence check must."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    adapter = _CountingAdapter()
    routed = _routed_service(p, adapter)
    try:
        first = routed.service.execute(p.request)
        assert first.accepted is True and len(adapter.calls) == 1
        assert _owner(outcome.store_root)["sealed"] is True
        admissions = (outcome.store_root / "admissions.jsonl").read_bytes()
        with pytest.raises(PermissionError, match="already re-admitted"):
            routed.service._fresh_publish(p.request, key)  # the late contender
        assert len(adapter.calls) == 1
        assert (outcome.store_root / "admissions.jsonl").read_bytes() == admissions
        assert _owner(outcome.store_root)["sealed"] is True
    finally:
        _release_router(routed)


def test_failed_recovery_provenance_write_leaves_no_owner(tmp_path, monkeypatch):
    """The provenance is written before the owner: if it fails, nothing blocks the successor."""
    from phase_loop_runtime.publishing import PublishTransaction, PublishTransactionConflict

    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))

    def refuse(self, record):
        raise PublishTransactionConflict("injected provenance failure")

    adapter = _CountingAdapter()
    with monkeypatch.context() as patch:
        patch.setattr(PublishTransaction, "record_recovery", refuse)
        with pytest.raises(PublishTransactionConflict, match="injected"):
            _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert adapter.calls == []
    assert _owner(outcome.store_root) is None
    assert _jsonl(outcome.store_root / "admissions.jsonl") == []
    assert _jsonl(outcome.store_root / "evidence.jsonl") == []
    retry, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(retry, Exception) and retry.accepted is True and len(calls) == 1


@pytest.mark.parametrize(
    "change", [{"pr_body": "a different body"}, {"draft": False}, {"base": "develop"}]
)
def test_recovery_refuses_a_request_that_differs_from_the_frozen_transaction(tmp_path, monkeypatch, change):
    """The attestation adjudicated the transaction as admitted; the provider request is
    built from the retry's base/draft/pr_body, so they must equal the frozen values."""
    import dataclasses

    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    checkpoint = _checkpoint_bytes(p)
    altered = dataclasses.replace(p.request, **change)
    result, calls = _publish_on_successor(None, outcome, p, altered)
    assert isinstance(result, PublicationRecoveryRequired), result
    assert next(iter(change)) in str(result)
    assert calls == []
    assert _owner(outcome.store_root) is None
    assert _jsonl(outcome.store_root / "admissions.jsonl") == []
    assert _checkpoint_bytes(p) == checkpoint, "a refused recovery wrote provenance"


def test_sdk_recovery_after_an_adapter_exception_seals_and_frees_the_branch(tmp_path, monkeypatch):
    """SDK route (board item 1): the broker leaves the checkpoint alone, the SDK closeout
    seals it after the observed terminal, the recovery record keeps the recovered
    state, and the sealed checkpoint does not block the next head on the branch."""
    from phase_loop_runtime.publishing import PublishAuthorityPreimages, publish_from_worktree
    from test_fabpub_shared_epoch import _authority_preimage

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    _git(p.repo, "checkout", "-q", "-b", "feat/sdk-exc")
    _stage(p.repo, "sdkexc.py", "def sdkexc():\n    return 1\n")
    root = tmp_path / "coordinator" / "sdk-exc"
    authority = PublishAuthorityPreimages(root, _authority_preimage(p.identity, "feat/sdk-exc"))

    def publish(adapter, paths=("sdkexc.py",), prebuilt=False):
        routed = _routed_service(p, adapter)
        try:
            return publish_from_worktree(
                p.repo, paths, broker_client=routed.service,
                publish_authority=authority, checkpoint_root=root, prebuilt=prebuilt,
            )
        finally:
            _release_router(routed)

    _release_all(p)
    failed = publish(_CountingAdapter(explode=True))
    assert failed["status"] == "publication_blocked", failed
    store = next((root / "publish-transactions").iterdir())
    [checkpoint_path] = [
        f for f in store.iterdir()
        if f.suffix == ".json" and ".recovery." not in f.name and f.name != "active.json"
    ]
    tid = checkpoint_path.stem
    assert json.loads(checkpoint_path.read_text())["state"] == "ADAPTER_STARTED"
    key = _jsonl(p.container / "evidence.jsonl")[-1]["idempotency_key"]
    _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    adapter = _CountingAdapter()
    published = publish(adapter)
    assert published["status"] == "published", published
    assert len(adapter.calls) == 1
    assert json.loads(checkpoint_path.read_text())["state"] == "TERMINAL_SEALED"
    record = json.loads((store / f"{tid}.recovery.1.json").read_text())
    assert record["recovered_transaction_state"] == "ADAPTER_STARTED"
    again = publish(adapter)
    assert again["status"] == "published" and len(adapter.calls) == 1

    # The sealed checkpoint released the active pointer: a new head prepares and publishes.
    _stage(p.repo, "sdknext.py", "def sdknext():\n    return 2\n")
    _git(p.repo, "commit", "-q", "-m", "next head")
    nxt = publish(adapter, paths=("sdknext.py",), prebuilt=True)
    assert nxt["status"] == "published", nxt
    assert len(adapter.calls) == 2
    assert nxt["head_sha"] != published["head_sha"]


def _record_fixture(tmp_path, monkeypatch):
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    return p, outcome, p.transaction.store.recovery_path(p.transaction.transaction_id, outcome.generation)


def test_recovery_record_write_contract(tmp_path, monkeypatch):
    """Board item 2: an owner-only regular file beside unchanged checkpoint bytes."""
    import stat

    p, outcome, record_path = _record_fixture(tmp_path, monkeypatch)
    checkpoint = p.transaction.checkpoint_path.read_bytes()
    previous = os.umask(0o022)  # a permissive umask must not widen the record
    try:
        result, calls = _publish_on_successor(None, outcome, p, p.request)
    finally:
        os.umask(previous)
    assert result.accepted is True and len(calls) == 1
    assert p.transaction.checkpoint_path.read_bytes() == checkpoint
    info = os.lstat(record_path)
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert not [f for f in record_path.parent.iterdir() if f.name.endswith(".tmp")]


@pytest.mark.parametrize("shape", ["symlink", "directory", "not_json"])
def test_existing_recovery_record_that_is_not_a_json_regular_file_refuses(tmp_path, monkeypatch, shape):
    """Board item 2: fail closed, typed, with no owner, admission or provider call."""
    from phase_loop_runtime.publishing import PublishTransactionConflict

    p, outcome, record_path = _record_fixture(tmp_path, monkeypatch)
    if shape == "symlink":
        target = tmp_path / "elsewhere.json"
        target.write_text("{}\n")
        record_path.symlink_to(target)
    elif shape == "directory":
        record_path.mkdir()
    else:
        record_path.write_text("not json\n")
    adapter = _CountingAdapter()
    with pytest.raises(PublishTransactionConflict):
        _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert adapter.calls == []
    assert _owner(outcome.store_root) is None
    assert _jsonl(outcome.store_root / "admissions.jsonl") == []
    if shape == "symlink":
        assert target.read_text() == "{}\n", "the refusal wrote through the symlink"


def test_rotation_bound_to_one_transaction_refuses_another_with_the_same_key(tmp_path, monkeypatch):
    """Board item 3: the rotation binds T1; an admitted T2 for the same effect key is refused."""
    import dataclasses

    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired
    from phase_loop_runtime.publishing import PublishTransactionState as S
    from phase_loop_runtime.publishing import prepare_prebuilt_transaction
    from test_fabpub_shared_epoch import _authority_preimage, _publish_transaction_request

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    branch = "feat/same-key"
    _git(p.repo, "checkout", "-q", "-b", branch)
    _stage(p.repo, "samekey.py", "def samekey():\n    return 1\n")
    _git(p.repo, "commit", "-q", "-m", "plain commit")

    def prebuilt(label, authority):
        txn = prepare_prebuilt_transaction(
            p.repo, owned_paths=("samekey.py",), checkpoint_root=tmp_path / "coordinator" / label,
            branch=branch, envelope_authority_preimage=authority,
        )
        txn.resume()
        request = _publish_transaction_request(p.identity, branch, txn, p.repo)
        envelope = dataclasses.replace(request.admission, roadmap_digest=authority["roadmap_digest"])
        return txn, dataclasses.replace(request, admission=envelope)

    first_authority = _authority_preimage(p.identity, branch)
    t1, request1 = prebuilt("t1", first_authority)
    p.service.adapter = _CountingAdapter(terminal_state=AMBIGUOUS)
    key = p.service._dedup_key(request1)
    assert p.service.execute(request1).accepted is False
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))

    second_authority = {**first_authority, "roadmap_digest": "7" * 64}
    t2, request2 = prebuilt("t2", second_authority)
    assert t2.transaction_id != t1.transaction_id
    assert p.service._dedup_key(request2) == key
    while t2.state != S.TERMINAL_SEALED:
        t2.project(S.ORDERED[S.ORDERED.index(t2.state) + 1])
    result, calls = _publish_on_successor(None, outcome, p, request2)
    assert isinstance(result, PublicationRecoveryRequired), result
    assert t1.transaction_id in str(result) and "not this one" in str(result)
    assert calls == []
    assert _owner(outcome.store_root) is None
    assert _jsonl(outcome.store_root / "admissions.jsonl") == []


def test_intervening_rotation_refuses_without_promising_a_rotation_fix(tmp_path, monkeypatch):
    """Board item 4: a rotation after the disposing one supersedes it; the refusal is
    typed, writes nothing, and does not claim another rotation would resolve it."""
    from types import SimpleNamespace

    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired
    from test_fabpub_partition_rotation_789d import ROTATION_ID_2

    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    first = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    routed = _routed_service(p)
    try:
        _block_key(SimpleNamespace(service=routed.service), "publish_committed_branch\x00ah1296-unrelated")
    finally:
        _release_router(routed)
    second = _rotate(None, p, cutover_id=ROTATION_ID_2)
    assert (first.generation, second.generation) == (1, 2)
    result, calls = _publish_on_successor(None, second, p, p.request)
    assert isinstance(result, PublicationRecoveryRequired), result
    message = str(result)
    assert "agent-harness#1310" in message
    assert "a rotation cannot help here" in message
    assert calls == []
    assert _owner(second.store_root) is None
    assert _jsonl(second.store_root / "admissions.jsonl") == []
