"""Typed publication handoffs for FABPUB broker refusals.

agent-harness#1573 ask 4, agent-harness#1578 ask 5 (SA-F5), agent-harness#1594 ask 1
(SA-F2) and agent-harness#1574 ask 2 (rotation handoff wording).

The human route used to answer every ``PermissionError`` from the broker with
``next_step="repair_fabpub_authority"``. Contention, a stale routing client, a
blocked partition and a pre-provider refusal each need a different step. The
route now chooses the step by exception type, never by message text. Each test
drives the refusal through ``publish_human_invoked_from_worktree`` on a real
zero-history bootstrap, with only the GitHub adapter replaced (the fixture of
``test_fabpub_ambiguous_handoff_1312.py``).
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_ambiguous_handoff_1312 import _evidence_states, _human_route
from test_fabpub_shared_epoch import _CountingAdapter

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

AMBIGUOUS = "outcome_ambiguous_blocked"
IN_FLIGHT = "provider_call_in_flight"
ROTATION_STEP = "adjudicate_publication_by_partition_rotation"
AUTHORITY_STEP = "repair_fabpub_authority"
REBUILD_STEP = "rebuild_broker_client_and_retry"
CONTENTION_STEP = "retry_after_inflight_publication"
RETRY_ONCE_STEP = "retry_once_before_partition_rotation"


def _modules():
    from phase_loop_runtime.convergence.broker import evidence, live, verbs

    return SimpleNamespace(live=live, verbs=verbs, evidence=evidence)


def _store_root(repo: Path) -> Path:
    return Path(_modules().live.repository_snapshot(repo).store_root)


def _seed_unsealed_owner(repo: Path, key: str = "foreign-key", transaction: str = "foreign-transaction") -> Path:
    """An unsealed adapter-start owner of another publication, with no evidence row."""
    verbs = _modules().verbs
    owner = verbs.AdapterStartOwnership(
        _modules().live.repository_snapshot(repo).identity,
        key,
        transaction,
        "foreign-attempt",
        "f" * 40,
        "publish_committed_branch",
        "foreign-nonce-0000000000000000",
        key,
        False,
    )
    root = _store_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "adapter-start-owner.json"
    path.write_text(json.dumps(owner.__dict__, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def _assert_typed(result, next_step: str, *, reason: str = "repository_publication_authority_refused"):
    assert result["status"] == "publication_blocked", result
    assert result["reason"] == reason
    handoff = result["handoff"]
    assert handoff["schema"] == "HumanPublicationHandoff.v1"
    assert handoff["next_step"] == next_step, handoff
    if next_step != AUTHORITY_STEP:
        # Every typed refusal is raised before the provider is entered.
        assert result["provider_call_made"] is False
        assert "repair" not in handoff["resume"]
    return handoff


def _assert_rotation_fields(handoff, repo: Path):
    assert handoff["next_step"] == ROTATION_STEP
    command = handoff["rotate_command"]
    assert command[:2] == ["phase-loop", "fabpub-rotate-partition"]
    assert command[command.index("--worktree") + 1] == str(repo.resolve())
    # agent-harness#1574 ask 2: §1/§6, the authority root, the transaction id
    # source and the second-attestation warning.
    procedure = handoff["recovery_procedure"]
    for section in ("1", "3", "4", "6", "7", "8a"):
        assert section in procedure.replace(",", " ").split(), procedure
    assert "FABPUB_AUTHORITY_ROOT" in handoff["authority_root"]
    assert "--authority-root" in handoff["authority_root"]
    assert "a second time without new evidence" in handoff["rotate_requires"]
    assert "transaction_id" in handoff["rotate_requires"]
    assert handoff["resume"].startswith("only after the rotation")


# ---------------------------------------------------------------------------
# agent-harness#1573 ask 4: a routing client built before a rotation
# ---------------------------------------------------------------------------


def test_stale_routing_client_gets_rebuild_handoff(tmp_path, monkeypatch):
    m = _modules()
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    snapshot = m.live.repository_snapshot(repo)
    retired = tmp_path / "retired-generation"
    real_build = m.live.build_routing_broker_client

    def stale_client(*args, **kwargs):
        # A client that cached generation N's stores before a rotation moved the
        # ACTIVE pointer: the real ``_stores_for`` cache-hit comparison refuses.
        client = real_build(*args, **kwargs)
        client._stores[snapshot.identity] = (None, SimpleNamespace(root=retired))
        return client

    monkeypatch.setattr(m.live, "build_routing_broker_client", stale_client)
    result = publish()

    assert adapter.calls == []
    handoff = _assert_typed(result, REBUILD_STEP)
    assert "retired partition generation" in result["detail"]
    assert "build a new one" in handoff["resume"]
    assert "restart" in handoff["resume"]
    assert "rotate_command" not in handoff
    assert "section 8" in handoff["recovery_procedure"]


def test_stale_client_refusal_is_still_writer_generation_blocked():
    live = _modules().live
    assert issubclass(live.RoutingClientGenerationRetired, live.WriterGenerationBlocked)
    assert issubclass(live.RoutingClientGenerationRetired, PermissionError)


# ---------------------------------------------------------------------------
# agent-harness#1578 ask 5: another publication is in flight
# ---------------------------------------------------------------------------


def test_live_owner_gets_retry_handoff(tmp_path, monkeypatch):
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    owner = _seed_unsealed_owner(repo)
    descriptor = os.open(str(owner), os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = publish()
    finally:
        os.close(descriptor)

    assert adapter.calls == []
    handoff = _assert_typed(result, CONTENTION_STEP)
    assert "live writer" in result["detail"]
    assert "retry" in handoff["resume"]
    assert "rotate_command" not in handoff
    assert "in flight" in handoff["next_step_source"] or "still running" in handoff["next_step_source"]


def test_contended_twice_gets_retry_handoff(tmp_path, monkeypatch):
    m = _modules()
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    _seed_unsealed_owner(repo)
    foreign = m.verbs.read_adapter_start_owner(_store_root(repo), repository_identity=m.live.repository_snapshot(repo).identity)

    monkeypatch.setattr(
        m.verbs.BrokerService,
        "_owner_and_admission_under_one_lock",
        lambda self, *args, **kwargs: (foreign, None, None),
    )
    monkeypatch.setattr(m.verbs.BrokerService, "_block_unsealed_owner", lambda self, owner: False)
    result = publish()

    assert adapter.calls == []
    _assert_typed(result, CONTENTION_STEP)
    assert "contended twice" in result["detail"]


# ---------------------------------------------------------------------------
# A blocked partition: the rotation handoff names the BLOCKING key
# ---------------------------------------------------------------------------


def test_dead_unsealed_owner_gets_rotation_handoff_naming_its_key(tmp_path, monkeypatch):
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    _seed_unsealed_owner(repo, key="foreign-key", transaction="foreign-transaction")

    result = publish()

    assert adapter.calls == []
    assert "blocks fresh provider effect" in result["detail"]
    handoff = _assert_typed(result, ROTATION_STEP)
    _assert_rotation_fields(handoff, repo)
    assert handoff["blocking_effect_keys"] == ["foreign-key"]
    assert handoff["blocking_transaction_id"] == "foreign-transaction"
    assert "foreign-key" in handoff["rotate_requires"] or "blocking_effect_keys" in handoff["rotate_requires"]


def _new_context(tmp_path: Path, repo: Path, run: int) -> None:
    """A new head under a new publication context (its own checkpoint): a new key."""
    (repo / "owned.py").write_text(f"value = {run}\n", encoding="utf-8")
    (tmp_path / "verification.json").write_text(f'{{"status":"passed","run":{run}}}\n', encoding="utf-8")


def test_another_keys_ambiguity_gets_rotation_handoff_naming_it(tmp_path, monkeypatch):
    adapter = _CountingAdapter(terminal_state=AMBIGUOUS)
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    first = publish()
    assert first["terminal_state"] == AMBIGUOUS
    evidence = [json.loads(line) for line in (_store_root(repo) / "evidence.jsonl").read_text().splitlines() if line]
    blocking = sorted({row["idempotency_key"] for row in evidence if row["state"] == AMBIGUOUS})
    assert len(blocking) == 1
    owner_path = _store_root(repo) / "adapter-start-owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    # An ambiguous terminal leaves its owner unsealed.
    assert owner["sealed"] is False and owner["effect_key"] == blocking[0]

    # (1) As this runtime leaves it: the unsealed ambiguous owner refuses the new key.
    _new_context(tmp_path, repo, 2)
    result = publish()
    assert len(adapter.calls) == 1, "a blocked partition reached the provider"
    assert result["detail"] == "unsealed adapter-start owner blocks fresh provider effect"
    handoff = _assert_typed(result, ROTATION_STEP)
    _assert_rotation_fields(handoff, repo)
    assert handoff["blocking_effect_keys"] == blocking
    assert handoff["blocking_transaction_id"] == owner["transaction_id"]

    # (2) The owner is sealed (an older writer, or a later seal): the
    # partition's own epoch check refuses, naming the same blocking key.
    owner_path.write_text(json.dumps({**owner, "sealed": True}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    _new_context(tmp_path, repo, 3)
    result = publish()
    assert len(adapter.calls) == 1, "a blocked partition reached the provider"
    assert result["detail"] == "epoch permanently blocked"
    handoff = _assert_typed(result, ROTATION_STEP)
    _assert_rotation_fields(handoff, repo)
    assert handoff["blocking_effect_keys"] == blocking
    assert "blocking_transaction_id" not in handoff


def test_partition_refusals_stay_permission_errors():
    verbs = _modules().verbs
    for name in (
        "PartitionEpochBlocked",
        "UnsealedOwnerBlocksPartition",
        "AdapterStartOwnerContended",
        "ProviderEntryRefused",
    ):
        assert issubclass(getattr(verbs, name), PermissionError), name
    assert not issubclass(verbs.AdapterStartOwnerContended, verbs.AdapterStartOwnerLive)


# ---------------------------------------------------------------------------
# agent-harness#1594 ask 1 (SA-F2): refused after admission, before the provider
# ---------------------------------------------------------------------------


def _refuse_lease(monkeypatch):
    live = _modules().live

    def refuse(_self, _root):
        raise live.WriterGenerationBlocked("writer generation latch is DRAINING; lease refused")

    monkeypatch.setattr(live.GitHubBrokerAdapter, "_acquire_service_generation_lease", refuse)
    return "lease refused", [IN_FLIGHT]


def _refuse_intent(monkeypatch):
    m = _modules()

    def refuse(_self, _key):
        raise m.live.WriterGenerationBlocked("the repository generation latch entered DRAINING before this write")

    monkeypatch.setattr(m.evidence.BrokerEvidenceStore, "record_intent", refuse)
    return "entered DRAINING", []


@pytest.mark.parametrize("refusal", [_refuse_lease, _refuse_intent], ids=["lease", "record_intent"])
def test_pre_provider_refusal_gets_retry_once_then_rotation(tmp_path, monkeypatch, refusal):
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    with pytest.MonkeyPatch.context() as refused:
        text, states = refusal(refused)
        first = publish()

    assert adapter.calls == []
    assert text in first["detail"], "the refusal text changed"
    handoff = _assert_typed(first, RETRY_ONCE_STEP)
    key = handoff["effect_key"]
    assert key and handoff["transaction_id"]
    assert handoff["resume"].startswith("retry once")
    assert ROTATION_STEP in handoff["resume"]
    assert "intents without a terminal" in handoff["next_step_source"]
    assert "provider_call_made" in handoff["attestation_evidence"]
    assert "rotate_command" not in handoff
    assert _evidence_states(repo) == states

    # Following the handoff: one retry promotes this attempt's own owner, and
    # that retry's handoff is the rotation for exactly this key and transaction.
    retry = publish()
    assert adapter.calls == []
    retry_handoff = _assert_typed(retry, ROTATION_STEP)
    _assert_rotation_fields(retry_handoff, repo)
    assert retry_handoff["blocking_effect_keys"] == [key]
    assert retry_handoff["blocking_transaction_id"] == handoff["transaction_id"]
    assert _evidence_states(repo)[-1] == AMBIGUOUS


def test_window_generation_refusal_still_catchable_as_writer_generation_blocked(tmp_path, monkeypatch):
    """Board round 1, Claude seat F001: the typed refusal is still a ``WriterGenerationBlocked``.

    Callers that catch the generation refusal (runbook §6 SDK holders) behave as
    before, at the ``BrokerService.execute`` boundary, and the human route still
    answers it with the retry-once handoff.
    """
    m = _modules()
    adapter = _CountingAdapter()
    _repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    seen: list[BaseException] = []
    original = m.verbs.BrokerService.execute

    def spy(self, request):
        try:
            return original(self, request)
        except BaseException as error:
            seen.append(error)
            raise

    def refuse(_self, _key):
        raise m.live.WriterGenerationBlocked("the generation latch entered DRAINING before this write")

    monkeypatch.setattr(m.verbs.BrokerService, "execute", spy)
    monkeypatch.setattr(m.evidence.BrokerEvidenceStore, "record_intent", refuse)
    result = publish()

    assert adapter.calls == []
    assert seen, "the broker did not refuse"
    error = seen[-1]
    assert isinstance(error, m.live.WriterGenerationBlocked), type(error).__mro__
    assert isinstance(error, m.verbs.ProviderEntryRefused)
    assert isinstance(error.__cause__, m.live.WriterGenerationBlocked)
    # The original message, with its prefix once.
    assert str(error) == str(error.__cause__)
    assert str(error).count(m.live.GENERATION_BLOCKER) == 1
    _assert_typed(result, RETRY_ONCE_STEP)


def test_guard_missing_row_gets_retry_once(tmp_path, monkeypatch):
    """``_provider_entry_guard``'s own "no evidence row" refusal is a ``ProviderEntryRefused``."""
    m = _modules()
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    real_replay = m.evidence.BrokerEvidenceStore.replay
    calls = {"guard": False}
    real_guard = m.verbs.BrokerService._provider_entry_guard

    def guard(self, key, owner):
        calls["guard"] = True
        try:
            return real_guard(self, key, owner)
        finally:
            calls["guard"] = False

    def replay(self):
        rows = real_replay(self)
        # Inside the guard only: the store no longer holds this attempt's row.
        return {} if calls["guard"] else rows

    with pytest.MonkeyPatch.context() as refused:
        refused.setattr(m.verbs.BrokerService, "_provider_entry_guard", guard)
        refused.setattr(m.evidence.BrokerEvidenceStore, "replay", replay)
        result = publish()

    assert adapter.calls == []
    assert "no evidence row before provider entry" in result["detail"]
    handoff = _assert_typed(result, RETRY_ONCE_STEP)
    assert handoff["effect_key"] and handoff["transaction_id"]


def _eacces(evidence, store, key):
    return PermissionError(13, "Permission denied", str(store.path))


def _store_incompatible(evidence, store, key):
    return evidence.EvidenceStoreIncompatible(
        store.path,
        line=1,
        idempotency_key=key,
        constructor=evidence.EvidenceRecord,
        unknown_keys=("future_field",),
        missing_keys=(),
        cause=TypeError("unexpected keyword argument 'future_field'"),
    )


def _plain_lease_refusal(evidence, store, key):
    return None  # marker: refuse the lease, not record_intent


@pytest.mark.parametrize(
    "fault", [_eacces, _store_incompatible, _plain_lease_refusal], ids=["eacces", "store_incompatible", "plain_lease"]
)
def test_other_permission_errors_in_window_keep_authority_handoff(tmp_path, monkeypatch, fault):
    """Board round 1, SA-F3: only generation and guard refusals are retry-once.

    An errno-bearing ``PermissionError`` (EACCES), ``EvidenceStoreIncompatible``
    or a plain ``PermissionError`` from the lease in the provider-entry window
    propagates unchanged and keeps ``repair_fabpub_authority``, as on main.
    """
    m = _modules()
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    seen: dict = {}
    original = m.verbs.BrokerService.execute

    def spy(self, request):
        try:
            return original(self, request)
        except BaseException as error:
            seen["broker"] = error
            raise

    def refuse_intent(self, key):
        seen["raised"] = fault(m.evidence, self, key)
        raise seen["raised"]

    def refuse_lease(_self, _root):
        seen["raised"] = PermissionError("lease refused by an unrelated authority check")
        raise seen["raised"]

    from phase_loop_runtime import publishing

    real_typed = publishing._typed_refusal_handoff

    def route_spy(error):
        seen["route"] = error
        return real_typed(error)

    with pytest.MonkeyPatch.context() as refused:
        refused.setattr(m.verbs.BrokerService, "execute", spy)
        refused.setattr(publishing, "_typed_refusal_handoff", route_spy)
        if fault is _plain_lease_refusal:
            refused.setattr(m.live.GitHubBrokerAdapter, "_acquire_service_generation_lease", refuse_lease)
        else:
            refused.setattr(m.evidence.BrokerEvidenceStore, "record_intent", refuse_intent)
        result = publish()

    assert adapter.calls == []
    # Propagated unchanged: same object, so same type, errno and filename.
    assert seen["broker"] is seen["raised"] is seen["route"]
    assert not isinstance(seen["broker"], m.verbs.ProviderEntryRefused)
    handoff = _assert_typed(result, AUTHORITY_STEP)
    assert "provider_call_made" not in result
    assert "rotate_command" not in handoff
    if fault is _eacces:
        assert seen["route"].errno == 13
        assert seen["route"].filename.endswith("evidence.jsonl")


# ---------------------------------------------------------------------------
# Unrelated refusals keep the authority handoff
# ---------------------------------------------------------------------------


def test_unrelated_permission_error_keeps_authority_handoff(tmp_path, monkeypatch):
    from phase_loop_runtime.convergence.broker import admission

    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)

    def refuse(_self):
        raise PermissionError("an unrelated authority refusal")

    monkeypatch.setattr(admission.LinearizableAdmissionStore, "probe_readable", refuse)
    result = publish()

    assert adapter.calls == []
    handoff = _assert_typed(result, AUTHORITY_STEP)
    assert result["detail"] == "an unrelated authority refusal"
    assert "provider_call_made" not in result
    assert "rotate_command" not in handoff


def test_legacy_carried_block_without_a_blocking_key_keeps_authority_handoff(tmp_path, monkeypatch):
    """``epoch_blocked`` from a legacy receipt names no key in the store; no rotation is offered."""
    m = _modules()
    adapter = _CountingAdapter()
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)
    monkeypatch.setattr(m.evidence.BrokerEvidenceStore, "_legacy_partition_blocked", lambda _self: True)

    result = publish()

    assert adapter.calls == []
    assert result["detail"] == "epoch permanently blocked"
    handoff = _assert_typed(result, AUTHORITY_STEP)
    assert "rotate_command" not in handoff
