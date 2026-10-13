"""Consiliency/agent-harness#1310: an attested_not_landed disposition survives later rotations.

agent-harness#1296 let the successor of a rotation re-admit an already-admitted
publish transaction once, when the rotation's attestation disposes its key
``attested_not_landed``.  Only the ACTIVE generation's receipt was consulted, so
a rotation for an unrelated key, run before the retry, dropped the disposition
and the retry was refused with no rotation able to fix it.  The recovery now
walks the authenticated receipt chain back to the disposing rotation and
requires every generation since to be untouched by the key.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_partition_rotation_789d import (
    ATTESTED_NOT_LANDED,
    ROTATION_ID,
    ROTATION_ID_2,
    _attestation,
    _block_key,
    _bootstrap,
    _publish_on_successor,
    _release_router,
    _rotate,
    _routed_service,
    _seed_owner,
)
from test_fabpub_sealed_head_recovery_1296 import (
    AMBIGUOUS,
    _broker_state,
    _checkpoint_bytes,
    _failed_sealed_publish,
    _owner,
)
from test_fabpub_shared_epoch import _CountingAdapter, _git, _jsonl, _stage

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

ROTATION_ID_3 = "rotation-1310-3"
UNRELATED = "publish_committed_branch\x00ah1310-unrelated-{}"


def _live():
    from phase_loop_runtime.convergence.broker import live

    return live


def _on_active(p, action) -> None:
    """Run ``action(service)`` against the partition's ACTIVE generation, routed."""
    routed = _routed_service(p)
    try:
        action(routed.service)
    finally:
        _release_router(routed)


def _block_unrelated(p, n: int) -> None:
    _on_active(p, lambda service: _block_key(SimpleNamespace(service=service), UNRELATED.format(n)))


def _rotate_for_unrelated(p, n: int, cutover_id: str):
    """Block an unrelated key in the active generation, then rotate it away."""
    _block_unrelated(p, n)
    return _rotate(None, p, cutover_id=cutover_id)


def _disposed_then_superseded(tmp_path, monkeypatch):
    """R1 disposes K attested_not_landed; R2 rotates generation 1 for an unrelated key."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    first = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    second = _rotate_for_unrelated(p, 1, ROTATION_ID_2)
    assert (first.generation, second.generation) == (1, 2)
    assert key not in second.receipt.adjudicated_effect_dispositions
    return p, key, first, second


def _assert_refused_without_writes(result, store_root, calls, before=None):
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    assert isinstance(result, PublicationRecoveryRequired), result
    assert calls == []
    assert _owner(store_root) is None
    assert _jsonl(store_root / "admissions.jsonl") == []
    if before is not None:
        assert _broker_state(store_root) == before, "the refusal wrote broker state"
    return str(result)


def test_disposition_survives_an_unrelated_rotation_and_recovers_once(tmp_path, monkeypatch):
    """C1: the incident shape of agent-harness#1310 publishes exactly once, then replays."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    checkpoint = _checkpoint_bytes(p)
    adapter = _CountingAdapter()
    result, calls = _publish_on_successor(None, second, p, p.request, adapter=adapter)
    assert not isinstance(result, Exception), f"recovery refused: {result!r}"
    assert result.accepted is True and len(calls) == 1
    sent = calls[0]
    assert (sent.branch, sent.head_sha) == (p.request.branch, p.transaction.expected_commit_oid)
    assert sent.admission.fence_token == p.transaction.transaction_id

    replay, calls = _publish_on_successor(None, second, p, p.request, adapter=adapter)
    assert not isinstance(replay, Exception), f"replay refused: {replay!r}"
    assert replay.accepted is True and len(calls) == 1, "the replay reached the provider again"

    after = _checkpoint_bytes(p)
    added = sorted(set(after) - set(checkpoint))
    assert added == [f"{p.transaction.transaction_id}.recovery.2.json"], added
    record = json.loads(after[added[0]])
    assert record["cutover_id"] == ROTATION_ID == first.cutover_id
    assert record["attestation_sha256"] == first.receipt.attestation_sha256
    assert record["inventory_sha256"] == first.receipt.inventory_sha256
    assert (record["disposing_generation"], record["readmitting_generation"]) == (1, 2)
    assert (record["predecessor_generation"], record["generation"]) == (0, 2)
    assert record["intervening_rotations"] == [ROTATION_ID_2]
    assert record["transaction_id"] == p.transaction.transaction_id

    # The late contender that passed execute's replay check still makes no second call.
    routed = _routed_service(p, adapter)
    try:
        with pytest.raises(PermissionError, match="already re-admitted"):
            routed.service._fresh_publish(p.request, key)
    finally:
        _release_router(routed)
    assert len(adapter.calls) == 1


def test_disposition_survives_two_unrelated_rotations(tmp_path, monkeypatch):
    """C2: the walk crosses more than one intervening generation."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    third = _rotate_for_unrelated(p, 2, ROTATION_ID_3)
    assert third.generation == 3
    result, calls = _publish_on_successor(None, third, p, p.request)
    assert not isinstance(result, Exception), f"recovery refused: {result!r}"
    assert result.accepted is True and len(calls) == 1
    record = json.loads(
        p.transaction.store.recovery_path(p.transaction.transaction_id, 3).read_text(encoding="utf-8")
    )
    assert record["intervening_rotations"] == [ROTATION_ID_2, ROTATION_ID_3]
    assert (record["disposing_generation"], record["readmitting_generation"]) == (1, 3)


def test_a_successful_recovery_is_not_repeated_after_a_later_rotation(tmp_path, monkeypatch):
    """Once across generations: after the recovery published in generation 2 and a later
    rotation, the disposition authorizes nothing and the retry makes no provider call."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    adapter = _CountingAdapter()
    result, _calls = _publish_on_successor(None, second, p, p.request, adapter=adapter)
    assert result.accepted is True and len(adapter.calls) == 1
    third = _rotate_for_unrelated(p, 2, ROTATION_ID_3)
    with pytest.raises(_live().RecoveryChainSuperseded):
        _live().attested_not_landed_recovery(third.store_root, key)
    again, _calls = _publish_on_successor(None, third, p, p.request, adapter=adapter)
    assert len(adapter.calls) == 1, "the recovered publication reached the provider twice"
    # The carried terminal is replayed from the later generation's receipt.
    assert not isinstance(again, Exception), f"replay refused: {again!r}"
    assert again.accepted is True


def test_later_generation_evidence_for_the_key_refuses(tmp_path, monkeypatch):
    """C3: a generation after the disposing rotation holds a row for K (here a settled
    ``no_effect_terminal_proven`` that the next rotation does not carry): refuse typed,
    naming that generation, before any write.  Fails with the evidence sweep removed."""
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))

    def proven(service):
        service.evidence_store.record_intent(key)
        service.evidence_store.record_terminal(
            EvidenceRecord(key, TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN, "ah1310-proven")
        )

    _on_active(p, proven)
    second = _rotate_for_unrelated(p, 1, ROTATION_ID_2)
    assert key not in second.receipt.legacy_completed_effect_keys
    before = _broker_state(second.store_root)
    result, calls = _publish_on_successor(None, second, p, p.request)
    message = _assert_refused_without_writes(result, second.store_root, calls, before)
    assert "generation 1 holds evidence" in message
    assert "inspect generation 1" in message


def test_later_generation_owner_for_the_key_refuses(tmp_path, monkeypatch):
    """A sealed generation after the disposing one carries an adapter-start owner naming K.
    Fails with the owner check removed."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    first = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    _seed_owner(first.store_root, p, key, sealed=True)
    second = _rotate_for_unrelated(p, 1, ROTATION_ID_2)
    result, calls = _publish_on_successor(None, second, p, p.request)
    message = _assert_refused_without_writes(result, second.store_root, calls)
    assert "adapter-start owner" in message and "generation 1" in message


def test_the_newest_disposition_is_the_current_word(tmp_path, monkeypatch):
    """C4: the first recovery attempt is ambiguous again, a second rotation re-disposes K.
    The walk stops at that newest disposition (generation 1, which holds the blocked
    attempt, is its predecessor and is not swept), so the second recovery publishes.
    Fails if the walk continues past the first disposition it meets."""
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    first = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    failed, calls = _publish_on_successor(
        None, first, p, p.request, adapter=_CountingAdapter(terminal_state=AMBIGUOUS)
    )
    assert failed.accepted is False and len(calls) == 1
    attestation = _attestation(p, dispositions={key: ATTESTED_NOT_LANDED})
    assert attestation["effects"][key]["transaction_id"] == p.transaction.transaction_id
    second = _rotate(None, p, cutover_id=ROTATION_ID_2, attestation=attestation)
    result, calls = _publish_on_successor(None, second, p, p.request)
    assert not isinstance(result, Exception), f"recovery refused: {result!r}"
    assert result.accepted is True and len(calls) == 1
    record = json.loads(
        p.transaction.store.recovery_path(p.transaction.transaction_id, 2).read_text(encoding="utf-8")
    )
    assert record["cutover_id"] == ROTATION_ID_2
    assert (record["disposing_generation"], record["intervening_rotations"]) == (2, [])


def test_a_receipt_carrying_the_key_as_completed_refuses(tmp_path, monkeypatch):
    """A receipt met on the walk that carries K as a completed effect refuses, even if
    nothing else would.  Fails with the carried-key check removed."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    live = _live()
    real = live.load_partition_receipt

    def carrying(store_root):
        receipt = real(store_root)
        if store_root == second.store_root:
            keys = tuple(receipt.legacy_completed_effect_keys) + (key,)
            return dataclasses.replace(receipt, legacy_completed_effect_keys=keys)
        return receipt

    monkeypatch.setattr(live, "load_partition_receipt", carrying)
    with pytest.raises(live.RecoveryChainSuperseded, match="completed effect"):
        live.attested_not_landed_recovery(second.store_root, key)


def test_a_walked_receipt_that_is_not_the_sealed_one_refuses(tmp_path, monkeypatch):
    """C5 (object binding): the predecessor receipt the walk uses must be the bytes its
    successor sealed.  Fails with that comparison removed (the walk would then fall
    through to generation 0 and return no disposition)."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    live = _live()
    real = live.load_partition_receipt

    def substituted(store_root):
        receipt = real(store_root)
        if store_root == first.store_root:
            return dataclasses.replace(receipt, adjudicated_effect_dispositions={})
        return receipt

    monkeypatch.setattr(live, "load_partition_receipt", substituted)
    with pytest.raises(live.LegacyCutoverConflict, match="not the receipt its successor sealed"):
        live.attested_not_landed_recovery(second.store_root, key)


def test_tampered_intermediate_receipt_refuses_typed_without_writes(tmp_path, monkeypatch):
    """C5 (bytes): generation 1's receipt changes after R2; nothing routes or writes."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    receipt_path = first.store_root / "partition-receipt.json"
    raw = json.loads(receipt_path.read_text(encoding="utf-8"))
    raw["adjudicated_effect_dispositions"] = {}
    receipt_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")
    before = _broker_state(second.store_root)
    adapter = _CountingAdapter()
    result, calls = _publish_on_successor(None, second, p, p.request, adapter=adapter)
    assert isinstance(result, PermissionError), result
    assert calls == []
    assert _broker_state(second.store_root) == before
    assert _owner(second.store_root) is None
    with pytest.raises((_live().LegacyCutoverConflict, PermissionError)):
        _live().attested_not_landed_recovery(second.store_root, key)


def test_intermediate_evidence_must_be_the_sealed_bytes(tmp_path, monkeypatch):
    """C6: the sweep reads each sealed generation's evidence once and requires the digest
    its successor sealed, so bytes swapped after the loader's own check are refused
    rather than trusted.  The loader's check is disabled here to reach that window.
    Fails with the sweep's digest comparison removed (the emptied log hides nothing)."""
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    first = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))

    def proven(service):
        service.evidence_store.record_intent(key)
        service.evidence_store.record_terminal(
            EvidenceRecord(key, TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN, "ah1310-proven")
        )

    _on_active(p, proven)
    second = _rotate_for_unrelated(p, 1, ROTATION_ID_2)
    live = _live()
    monkeypatch.setattr(
        live,
        "_require_rotation_receipt_binds",
        lambda expected, container, generation, path: (
            container if generation == 1 else container / live.GENERATIONS_DIR / str(generation - 1)
        ),
    )
    (first.store_root / "evidence.jsonl").write_bytes(b"")
    with pytest.raises(live.LegacyCutoverConflict, match="not the bytes its successor receipt sealed"):
        live.attested_not_landed_recovery(second.store_root, key)


def test_transaction_mismatch_is_still_refused_across_an_intervening_rotation(tmp_path, monkeypatch):
    """C7: the walked disposition binds T1; an admitted T2 for the same key is refused."""
    from phase_loop_runtime.publishing import PublishTransactionState as S
    from phase_loop_runtime.publishing import prepare_prebuilt_transaction
    from test_fabpub_shared_epoch import _authority_preimage, _publish_transaction_request

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    branch = "feat/same-key-1310"
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
    _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    second = _rotate_for_unrelated(p, 1, ROTATION_ID_2)

    t2, request2 = prebuilt("t2", {**first_authority, "roadmap_digest": "7" * 64})
    assert t2.transaction_id != t1.transaction_id and p.service._dedup_key(request2) == key
    while t2.state != S.TERMINAL_SEALED:
        t2.project(S.ORDERED[S.ORDERED.index(t2.state) + 1])
    result, calls = _publish_on_successor(None, second, p, request2)
    message = _assert_refused_without_writes(result, second.store_root, calls)
    assert t1.transaction_id in message and "not this one" in message
