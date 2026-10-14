"""Consiliency/agent-harness#1591: a provider outcome on an already-ambiguous key is kept.

Window (a) of agent-harness#1577: an older-runtime prober (no agent-harness#1313
liveness probe) promotes a live writer's owner to ``outcome_ambiguous_blocked``
after the provider-entry guard released ``admissions.lock``.  The writer still
makes one provider call.  When that call returns a definite outcome, the broker
records it in ``post-ambiguity-observations.jsonl`` beside the evidence log,
bound to the blocked row (``ambiguity_digest``) and to this attempt's owner
(``owner_nonce``, ``transaction_id``).  The evidence log, the owner and the
epoch block are unchanged: only an operator rotation clears the key, and new
runtimes refuse to clear an observed effect ``attested_not_landed``.

Most tests promote inside the provider call (``_PromotingAdapter``), which is
the same store state as a promotion anywhere in window (a); the two pinned
windows themselves are in ``test_fabpub_owner_section_1314_1313_1311.py``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_admission_compat_789 import _durable_state, _routed
from test_fabpub_owner_section_1314_1313_1311 import (
    AMBIGUOUS,
    IN_FLIGHT,
    OBSERVATIONS,
    OBSERVED,
    WAIT_SECONDS,
    _assert_observed_effect,
    _key_states,
    _ParkedAdapter,
)
from test_fabpub_partition_rotation_789d import (
    ATTESTED_NOT_LANDED,
    OBSERVED_LANDED,
    ROTATION_ID,
    _ambiguity_digest,
    _assert_no_durable_rotation,
    _attestation,
    _bootstrap,
    _journal_states,
    _publish_on_successor,
    _release_all,
    _rotate,
)
from test_fabpub_shared_epoch import _CountingAdapter, _counting_store, _jsonl, _service

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

NO_EFFECT = "no_effect_terminal_proven"
EFFECT_REASON = "effect_observed_after_ambiguity"
NO_EFFECT_REASON = "no_effect_observed_after_ambiguity"
RUNTIME = Path(__file__).resolve().parents[1]
SCRIPTS = RUNTIME / "scripts"


def _verbs():
    from phase_loop_runtime.convergence.broker import verbs

    return verbs


def _live():
    from phase_loop_runtime.convergence.broker import live

    return live


def _promote(root: Path, identity: str, monkeypatch) -> None:
    """Promote the unsealed owner the way a runtime without agent-harness#1313 would."""
    verbs = _verbs()
    monkeypatch.setattr(verbs, "_owner_writer_alive", lambda _root: False)
    owner = verbs.read_adapter_start_owner(root, repository_identity=identity)
    assert owner is not None and owner.sealed is False
    store = _counting_store(root)
    try:
        prober = _service(root, _CountingAdapter(), store=store)
        assert prober._block_unsealed_owner(owner) is True
    finally:
        # The prober's own generation lease must not hold a later rotation's drain.
        lease = getattr(store, "generation_lease", None)
        if lease is not None:
            lease.release()


class _PromotingAdapter(_CountingAdapter):
    """The first provider call is promoted to ambiguity by an older prober while it runs."""

    def __init__(self, root: Path, identity: str, monkeypatch, *, after=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._where = (root, identity, monkeypatch)
        self._after = after
        self.promoted = 0

    def execute(self, request):
        if not self.promoted:
            self.promoted += 1
            _promote(*self._where)
            if self._after is not None:
                self._after()
        return super().execute(request)


def _promoting(fx, monkeypatch, **kwargs) -> _PromotingAdapter:
    adapter = _PromotingAdapter(fx.root, fx.identity, monkeypatch, **kwargs)
    fx.service.adapter = adapter
    return adapter


def _owner(root: Path) -> dict:
    return json.loads((Path(root) / "adapter-start-owner.json").read_text(encoding="utf-8"))


def _suffix(key: str) -> str:
    prefix = "publish_committed_branch\0"
    assert key.startswith(prefix)
    return key[len(prefix):]


# ---------------------------------------------------------------------------
# 2-5, 11: the broker
# ---------------------------------------------------------------------------


def test_replay_after_an_observation_returns_it_without_a_call(tmp_path, monkeypatch):
    fx = _routed(tmp_path, name="replay-1591")
    key = fx.service._dedup_key(fx.request)
    adapter = _promoting(fx, monkeypatch)
    first = fx.service.execute(fx.request)
    row = _assert_observed_effect(fx, key, first)
    side_file = (fx.root / OBSERVATIONS).read_bytes()

    for _ in range(2):
        replay = fx.service.execute(fx.request)
        assert len(adapter.calls) == 1, "a replay reached the provider"
        assert replay.accepted is False and replay.publish_result is None
        assert replay.reason == EFFECT_REASON
        assert replay.provider_call_made is False
        assert replay.evidence.terminal_state == AMBIGUOUS
        assert replay.observed_after_ambiguity is not None
        assert replay.observed_after_ambiguity.evidence_reference == row["evidence_reference"]
        assert replay.observed_after_ambiguity.durable is True
    # Replays read; they never write.
    assert (fx.root / OBSERVATIONS).read_bytes() == side_file
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]


def test_crash_after_the_observation_replays_it(tmp_path, monkeypatch):
    from phase_loop_runtime.publishing import PublishCrashInjected, crash_after

    fx = _routed(tmp_path, name="crash-after-observation-1591")
    key = fx.service._dedup_key(fx.request)
    adapter = _promoting(fx, monkeypatch)
    with crash_after("after_post_ambiguity_observation"):
        with pytest.raises(PublishCrashInjected):
            fx.service.execute(fx.request)
    rows = _jsonl(fx.root / OBSERVATIONS)
    assert [row["evidence_reference"] for row in rows] == ["https://gh/pr/1"]
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]

    retry = fx.service.execute(fx.request)
    assert len(adapter.calls) == 1
    assert retry.reason == EFFECT_REASON and retry.provider_call_made is False
    assert retry.observed_after_ambiguity.evidence_reference == "https://gh/pr/1"


def test_crash_before_the_observation_is_todays_shape(tmp_path, monkeypatch):
    """A crash after the provider returned and before the write loses the URL (residual)."""
    from phase_loop_runtime.publishing import PublishCrashInjected, crash_after

    fx = _routed(tmp_path, name="crash-before-observation-1591")
    key = fx.service._dedup_key(fx.request)
    adapter = _promoting(fx, monkeypatch)
    with crash_after("after_provider_return_before_terminal"):
        with pytest.raises(PublishCrashInjected):
            fx.service.execute(fx.request)
    assert not (fx.root / OBSERVATIONS).exists()
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    retry = fx.service.execute(fx.request)
    assert len(adapter.calls) == 1
    assert retry.accepted is False and retry.provider_call_made is False
    assert retry.evidence.terminal_state == AMBIGUOUS
    assert retry.reason not in (EFFECT_REASON, NO_EFFECT_REASON)
    assert retry.observed_after_ambiguity is None


def test_no_effect_on_an_ambiguous_row_is_recorded_as_supporting_evidence(tmp_path, monkeypatch):
    fx = _routed(tmp_path, name="no-effect-1591")
    key = fx.service._dedup_key(fx.request)
    _promoting(fx, monkeypatch, terminal_state=NO_EFFECT)
    result = fx.service.execute(fx.request)
    assert result.accepted is False and result.publish_result is None
    assert result.reason == NO_EFFECT_REASON
    assert result.provider_call_made is True
    assert result.evidence.terminal_state == AMBIGUOUS
    assert result.observed_after_ambiguity.observed_state == NO_EFFECT
    assert result.observed_after_ambiguity.evidence_reference == "github-observed"
    rows = _jsonl(fx.root / OBSERVATIONS)
    assert [(row["observed_state"], row["ambiguity_digest"]) for row in rows] == [
        (NO_EFFECT, _ambiguity_digest(fx.evidence, key))
    ]
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    assert fx.service.evidence_store.epoch_blocked is True
    assert _owner(fx.root)["sealed"] is False
    replay = fx.service.execute(fx.request)
    assert replay.reason == NO_EFFECT_REASON and replay.provider_call_made is False


@pytest.mark.parametrize("outcome", ["ambiguous", "raises"])
def test_an_ambiguous_or_raising_provider_on_an_ambiguous_row_is_unchanged(tmp_path, monkeypatch, outcome):
    fx = _routed(tmp_path, name=f"{outcome}-1591")
    key = fx.service._dedup_key(fx.request)
    if outcome == "ambiguous":
        _promoting(fx, monkeypatch, terminal_state=AMBIGUOUS)
    else:
        _promoting(fx, monkeypatch, explode=True)
    result = fx.service.execute(fx.request)
    assert len(fx.service.adapter.calls) == 1
    assert result.accepted is False
    assert result.reason == "outcome_ambiguous"
    assert result.provider_call_made is True
    assert result.observed_after_ambiguity is None
    assert result.evidence.evidence_reference == "unsealed-adapter-start-owner"
    assert not (fx.root / OBSERVATIONS).exists()
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]


class _ReleaseRaisingPromotingAdapter(_PromotingAdapter):
    def _acquire_service_generation_lease(self, _root):
        return "lease"

    def _release_service_generation_lease(self, lease):
        assert lease == "lease"
        raise OSError("simulated lease release failure after the provider returned")


def test_lease_release_failure_after_success_keeps_the_observation(tmp_path, monkeypatch):
    """D3: the observation is durable before the generation lease is released."""
    fx = _routed(tmp_path, name="release-raises-1591")
    key = fx.service._dedup_key(fx.request)
    fx.service.adapter = _ReleaseRaisingPromotingAdapter(fx.root, fx.identity, monkeypatch)
    result = fx.service.execute(fx.request)
    _assert_observed_effect(fx, key, result)


def test_lease_release_failure_after_success_on_a_live_row_is_the_terminal(tmp_path):
    """agent-harness#1593 Q5: with the terminal recorded first, a failed release is not ambiguity."""

    class _ReleaseRaising(_CountingAdapter):
        def _acquire_service_generation_lease(self, _root):
            return "lease"

        def _release_service_generation_lease(self, _lease):
            raise OSError("simulated lease release failure after the provider returned")

    fx = _routed(tmp_path, name="release-raises-live-1591")
    key = fx.service._dedup_key(fx.request)
    fx.service.adapter = _ReleaseRaising()
    result = fx.service.execute(fx.request)
    assert result.accepted is True
    assert result.publish_result.pr_url == "https://gh/pr/1"
    assert _key_states(fx, key) == [IN_FLIGHT, OBSERVED]
    assert fx.service.evidence_store.epoch_blocked is False


def test_owner_nonce_mismatch_writes_no_observation(tmp_path, monkeypatch):
    """The observation binds this attempt's owner; a different owner gets nothing durable."""
    fx = _routed(tmp_path, name="nonce-mismatch-1591")
    key = fx.service._dedup_key(fx.request)

    def rewrite_owner():
        owner = _owner(fx.root)
        owner["owner_nonce"] = "f" * 32
        fx.owner.write_text(json.dumps(owner, sort_keys=True) + "\n", encoding="utf-8")

    _promoting(fx, monkeypatch, after=rewrite_owner)
    result = fx.service.execute(fx.request)
    assert result.accepted is False and result.publish_result is None
    assert result.reason == EFFECT_REASON
    assert result.provider_call_made is True
    observation = result.observed_after_ambiguity
    assert observation is not None and observation.durable is False
    assert observation.evidence_reference == "https://gh/pr/1"
    assert not (fx.root / OBSERVATIONS).exists(), "an observation was bound to another owner"
    assert _key_states(fx, key) == [IN_FLIGHT, AMBIGUOUS]
    assert _owner(fx.root)["sealed"] is False


# ---------------------------------------------------------------------------
# 6-8: the ceremony, the preflight and the re-admission
# ---------------------------------------------------------------------------


def _observed_partition(tmp_path, monkeypatch, **adapter_kwargs):
    """Bootstrap, then a publish whose success lands on a row promoted during the call."""
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    adapter = _promoting(p, monkeypatch, **adapter_kwargs)
    key = p.service._dedup_key(p.request)
    result = p.service.execute(p.request)
    assert len(adapter.calls) == 1
    return fx, p, key, result, adapter


def _run_preflight(p, attestation: dict, tmp_path: Path, monkeypatch) -> dict:
    """The read-only preflight script, in-process, over the real partition."""
    path = tmp_path / "operator" / f"attestation-{len(list(tmp_path.glob('operator/*')))}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attestation), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("fabpub_rotation_preflight", SCRIPTS / "fabpub_rotation_preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fabpub_rotation_preflight.py", "--worktree", str(p.repo), "--attestation", str(path),
            "--cutover-id", ROTATION_ID, "--authority-root", str(p.authority), "--json",
        ],
    )
    out = io.StringIO()
    with redirect_stdout(out):
        module.main()
    return json.loads(out.getvalue())


def _run_builder(container: Path, out: Path, *, key: str, observed_head: str, evidence_url: str) -> str:
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "fabpub_rotation_attestation.py"),
            "--container", str(container), "--out", str(out), "--attested-by", "operator",
            "--effect-key-suffix", _suffix(key), "--observed-head", observed_head,
            "--evidence-url", evidence_url,
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_ceremony_and_preflight_refuse_attested_not_landed_and_observed_landed_rotates(tmp_path, monkeypatch):
    fx, p, key, result, _adapter = _observed_partition(tmp_path, monkeypatch)
    _assert_observed_effect(p, key, result)
    observation = result.observed_after_ambiguity
    _release_all(p)
    gen0 = {name: (p.container / name).read_bytes() for name in ("evidence.jsonl", OBSERVATIONS)}

    not_landed = _attestation(p, dispositions={key: ATTESTED_NOT_LANDED})
    report = _run_preflight(p, not_landed, tmp_path, monkeypatch)
    assert report["verdict"] == "would_refuse", report
    assert "observed" in report["refusal"] and "attested_not_landed" in report["refusal"]
    assert report["checks"][-1]["check"] == "no_attested_not_landed_over_observed_effect"
    with pytest.raises(_live().PartitionRotationRefused) as refused:
        _rotate(None, p, attestation=not_landed)
    assert "https://gh/pr/1" in str(refused.value) and "observed_landed" in str(refused.value)
    assert _journal_states(p) == []
    _assert_no_durable_rotation(None, p)
    assert _live().WriterGenerationLatch.for_store_root(p.container).read().generation_state == "ACTIVE"
    assert {name: (p.container / name).read_bytes() for name in gen0} == gen0

    # The observed handoff's inputs, through the stdlib builder.
    out = tmp_path / "operator" / "observed.json"
    printed = _run_builder(
        p.container, out, key=key,
        observed_head=observation.head_sha, evidence_url=observation.evidence_reference,
    )
    assert "post-ambiguity observation" in printed and "WARNING" not in printed
    observed = json.loads(out.read_text(encoding="utf-8"))
    entry = observed["effects"][key]
    assert entry["disposition"] == OBSERVED_LANDED
    assert (entry["owner_nonce"], entry["transaction_id"]) == (observation.owner_nonce, observation.transaction_id)
    assert entry["ambiguity_digest"] == observation.ambiguity_digest
    # "ready_but_drain_will_block" only reflects other run-train processes on this host.
    assert _run_preflight(p, observed, tmp_path, monkeypatch)["verdict"] in (
        "ready", "ready_but_drain_will_block"
    )
    outcome = _rotate(None, p, attestation=observed)
    assert outcome.state == "ACTIVE" and outcome.generation == 1

    adapter = _CountingAdapter()
    replay, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(replay, Exception), replay
    assert replay.accepted is True
    assert calls == [], "the observed effect was published a second time"
    assert replay.publish_result.pr_url == observation.evidence_reference


def test_builder_warns_when_its_inputs_disagree_with_the_observation(tmp_path, monkeypatch):
    fx, p, key, result, _adapter = _observed_partition(tmp_path, monkeypatch)
    printed = _run_builder(
        p.container, tmp_path / "operator" / "wrong.json", key=key,
        observed_head="0" * 40, evidence_url="https://example.invalid/other",
    )
    assert "WARNING" in printed and "--observed-head" in printed and "--evidence-url" in printed


def test_observation_written_during_the_drain_refuses_in_lock(tmp_path, monkeypatch):
    """The in-lock re-check: an observation landing after the zero-write adjudication."""
    from phase_loop_runtime.convergence.broker import evidence as evidence_module

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    p.service.adapter = _CountingAdapter(terminal_state=AMBIGUOUS)
    key = p.service._dedup_key(p.request)
    p.service.execute(p.request)
    owner = _owner(p.container)
    live = _live()
    real = live._derive_rotation_inventory

    def derive_then_observe(*args, **kwargs):
        # After the zero-write early check, before the ceremony takes the lock.
        derived = real(*args, **kwargs)
        row = evidence_module.PostAmbiguityObservation(
            idempotency_key=key,
            observed_state=OBSERVED,
            evidence_reference="https://gh/pr/late",
            head_sha=p.request.head_sha,
            branch=p.request.branch,
            transaction_id=owner["transaction_id"],
            owner_nonce=owner["owner_nonce"],
            ambiguity_digest=_ambiguity_digest(p.evidence, key),
        )
        assert evidence_module.append_post_ambiguity_observation(p.container, row) is True
        return derived

    monkeypatch.setattr(live, "_derive_rotation_inventory", derive_then_observe)
    with pytest.raises(live.PartitionRotationRefused) as refused:
        _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    assert "https://gh/pr/late" in str(refused.value)
    assert "INVENTORY_SEALED" not in _journal_states(p)
    assert live.WriterGenerationLatch.for_store_root(p.container).read().generation_state == "ACTIVE"
    assert not (p.container / "generations").exists()


def _old_ceremony(monkeypatch) -> None:
    """A ceremony without agent-harness#1591: it never reads the side file."""
    monkeypatch.setattr(_live(), "_refuse_attested_not_landed_over_observations", lambda *_a, **_k: None)


def test_readmission_refuses_an_observed_effect_an_old_ceremony_attested_not_landed(tmp_path, monkeypatch):
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    fx, p, key, result, _adapter = _observed_partition(tmp_path, monkeypatch)
    assert result.reason == EFFECT_REASON
    _old_ceremony(monkeypatch)
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    assert outcome.state == "ACTIVE"
    adapter = _CountingAdapter()
    refused, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert isinstance(refused, PublicationRecoveryRequired), refused
    assert calls == [], "the observed effect was published a second time"
    message = str(refused)
    assert "https://gh/pr/1" in message and "maintainer" in message
    assert not (outcome.store_root / "adapter-start-owner.json").exists()
    assert _jsonl(outcome.store_root / "admissions.jsonl") == []


def test_readmission_with_only_a_no_effect_observation_is_not_refused(tmp_path, monkeypatch):
    """D4: a no-effect observation supports attested_not_landed; it is not enforced."""
    fx, p, key, result, _adapter = _observed_partition(tmp_path, monkeypatch, terminal_state=NO_EFFECT)
    assert result.reason == NO_EFFECT_REASON
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    adapter = _CountingAdapter()
    published, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(published, Exception), published
    assert published.accepted is True and len(calls) == 1


def test_torn_side_file_refuses_ceremony_and_recovery(tmp_path, monkeypatch):
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    p.service.adapter = _CountingAdapter(terminal_state=AMBIGUOUS)
    key = p.service._dedup_key(p.request)
    p.service.execute(p.request)
    # A crash mid-append: a partial line with no newline.
    (p.container / OBSERVATIONS).write_bytes(b'{"idempotency_key": "publish_committed_branch')

    replay = p.service.execute(p.request)
    assert replay.accepted is False and replay.evidence.terminal_state == AMBIGUOUS
    assert replay.observed_after_ambiguity is None

    not_landed = _attestation(p, dispositions={key: ATTESTED_NOT_LANDED})
    _release_all(p)
    report = _run_preflight(p, not_landed, tmp_path, monkeypatch)
    assert report["verdict"] == "would_refuse" and "unreadable" in report["refusal"]
    with pytest.raises(_live().PartitionRotationRefused) as refused:
        _rotate(None, p, attestation=not_landed)
    assert "unreadable" in str(refused.value)
    assert _journal_states(p) == []

    _old_ceremony(monkeypatch)
    outcome = _rotate(None, p, attestation=not_landed)
    result, calls = _publish_on_successor(None, outcome, p, p.request)
    assert isinstance(result, PublicationRecoveryRequired), result
    assert "unreadable" in str(result) and "maintainer" in str(result)
    assert calls == []


# ---------------------------------------------------------------------------
# 9: the human route
# ---------------------------------------------------------------------------


HANDOFF_ADDITIONS = (
    "required_disposition",
    "forbidden_disposition",
    "attestation_inputs",
    "attestation_builder_command",
    "supporting_evidence",
)


class _HumanPromotingAdapter(_CountingAdapter):
    def __init__(self, repo: Path, monkeypatch, **kwargs) -> None:
        super().__init__(**kwargs)
        self._repo = repo
        self._monkeypatch = monkeypatch

    def execute(self, request):
        if not self.calls:
            snapshot = _live().repository_snapshot(self._repo)
            _promote(snapshot.store_root, snapshot.identity, self._monkeypatch)
        return super().execute(request)


def _human(tmp_path, monkeypatch, **kwargs):
    from test_fabpub_ambiguous_handoff_1312 import _human_route

    holder: dict = {}

    class _Late(_CountingAdapter):
        def execute(self, request):
            return holder["adapter"].execute(request)

    repo, publish = _human_route(tmp_path, monkeypatch, _Late())
    holder["adapter"] = _HumanPromotingAdapter(repo, monkeypatch, **kwargs)
    return repo, publish, holder["adapter"]


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_human_handoff_requires_observed_landed_and_its_builder_rotates(tmp_path, monkeypatch):
    from test_fabpub_ambiguous_handoff_1312 import ROTATION_STEP, _assert_rotation_handoff

    repo, publish, adapter = _human(tmp_path, monkeypatch)
    first = publish()
    assert len(adapter.calls) == 1
    snapshot = _live().repository_snapshot(repo)
    owner = _owner(snapshot.store_root)
    key = owner["effect_key"]
    head = _git_head(repo)
    for result, made in ((first, True), (publish(), False)):
        assert len(adapter.calls) == 1
        _assert_rotation_handoff(result, repo)
        assert result["reason"] == EFFECT_REASON
        assert result["provider_call_made"] is made
        observed = result["observed_after_ambiguity"]
        assert observed["evidence_reference"] == "https://gh/pr/1"
        handoff = result["handoff"]
        assert handoff["next_step"] == ROTATION_STEP
        assert handoff["required_disposition"] == OBSERVED_LANDED
        assert handoff["forbidden_disposition"] == ATTESTED_NOT_LANDED
        assert handoff["attestation_inputs"] == {
            "observed_head": head,
            "evidence_url": "https://gh/pr/1",
            "effect_key_suffix": _suffix(key),
            "owner_nonce": owner["owner_nonce"],
            "transaction_id": owner["transaction_id"],
        }
        assert "observed_landed" in handoff["rotate_requires"]
        assert "supporting_evidence" not in handoff
        builder = handoff["attestation_builder_command"]
        assert builder[1].endswith("scripts/fabpub_rotation_attestation.py")

    # The pre-filled builder argv, with the operator's two placeholders filled.
    argv = list(builder)
    out = tmp_path / "operator" / "observed.json"
    argv[0], argv[1] = sys.executable, str(SCRIPTS / "fabpub_rotation_attestation.py")
    argv[argv.index("--out") + 1] = str(out)
    argv[argv.index("--attested-by") + 1] = "operator"
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    assert completed.returncode == 0, completed.stderr
    attestation = json.loads(out.read_text(encoding="utf-8"))
    outcome = _live().rotate_blocked_partition(
        repo,
        cutover_id="observed-1591",
        attestation=attestation,
        authority_root=Path(os.environ[_live().FABPUB_AUTHORITY_ROOT_ENV]),
    )
    assert outcome.state == "ACTIVE"
    published = publish()
    assert published["status"] == "published", published
    assert published["pr_url"] == "https://gh/pr/1"
    assert len(adapter.calls) == 1, "the observed effect was published a second time"


def test_human_handoff_for_no_effect_cites_supporting_evidence(tmp_path, monkeypatch):
    repo, publish, adapter = _human(tmp_path, monkeypatch, terminal_state=NO_EFFECT)
    result = publish()
    assert result["reason"] == NO_EFFECT_REASON
    handoff = result["handoff"]
    assert handoff["next_step"] == "adjudicate_publication_by_partition_rotation"
    assert handoff["required_disposition"] is None
    assert "forbidden_disposition" not in handoff
    assert handoff["supporting_evidence"]["evidence_reference"] == "github-observed"
    assert handoff["supporting_evidence"]["observed_state"] == NO_EFFECT


def test_plain_ambiguity_keeps_the_1312_handoff(tmp_path, monkeypatch):
    from test_fabpub_ambiguous_handoff_1312 import _assert_rotation_handoff, _human_route

    repo, publish = _human_route(tmp_path, monkeypatch, _CountingAdapter(terminal_state=AMBIGUOUS))
    for result in (publish(), publish()):
        _assert_rotation_handoff(result, repo)
        assert "observed_after_ambiguity" not in result
        assert not set(HANDOFF_ADDITIONS) & set(result["handoff"])


# ---------------------------------------------------------------------------
# 10: real mixed versions, in separate processes
# ---------------------------------------------------------------------------

#: The last first-parent ``main`` commit before agent-harness#1313 (no liveness
#: probe): the "older prober" of window (a).
PRE_LIVENESS_COMMIT = "190220000d00f1dcc37d96fd04dcecf9f342a9a5"
#: The ``main`` commit this change is based on: a reader that knows nothing of
#: the side file.
PRE_OBSERVATION_COMMIT = "6ec6534221b20203e030516f391332a5fbbc8509"

_PROBER = r"""
import sys
from pathlib import Path
import phase_loop_runtime.convergence.broker.verbs as verbs
from test_fabpub_shared_epoch import _CountingAdapter, _counting_store, _service
root = Path(sys.argv[1]); identity = sys.argv[2]
service = _service(root, _CountingAdapter(), store=_counting_store(root))
owner = verbs.read_adapter_start_owner(root, repository_identity=identity)
print("FILE", verbs.__file__, flush=True)
print("RESULT", repr(service._block_unsealed_owner(owner)), flush=True)
"""

_READER = r"""
import json, sys
from pathlib import Path
from phase_loop_runtime.convergence.broker import evidence
store = evidence.BrokerEvidenceStore(Path(sys.argv[1]))
print("FILE", evidence.__file__)
print(json.dumps({
    "epoch_blocked": store.epoch_blocked,
    "replay": {key: [record.state.value, record.evidence_reference] for key, record in sorted(store.replay().items())},
}, sort_keys=True))
"""


@pytest.fixture(scope="module")
def _old_trees(tmp_path_factory):
    """``phase-loop-runtime/src`` of each pinned historical commit, from this checkout's git."""
    repo = RUNTIME.parent
    trees = {}
    for name, commit in (("prober", PRE_LIVENESS_COMMIT), ("reader", PRE_OBSERVATION_COMMIT)):
        present = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True, check=False,
        )
        if present.returncode != 0:
            pytest.skip(f"historical commit {commit} is not in this checkout (shallow clone?)")
        archive = subprocess.run(
            ["git", "-C", str(repo), "archive", "--format=tar", commit, "phase-loop-runtime/src"],
            capture_output=True, check=True,
        ).stdout
        target = tmp_path_factory.mktemp(f"old-{name}")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(target, filter="data")
        trees[name] = target / "phase-loop-runtime" / "src"
    return trees


def _run_old(src: Path, program: str, *argv: str) -> list[str]:
    env = dict(os.environ, PYTHONPATH=f"{src}{os.pathsep}{RUNTIME / 'tests'}")
    completed = subprocess.run(
        [sys.executable, "-c", program, *argv], env=env, capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    lines = completed.stdout.splitlines()
    assert lines[0].startswith("FILE ") and lines[0][5:].startswith(str(src)), lines[0]
    return lines[1:]


def test_real_old_prober_and_old_reader_processes(tmp_path, _old_trees):
    fx = _routed(tmp_path, name="mixed-1591")
    key = fx.service._dedup_key(fx.request)
    parked = _ParkedAdapter()
    fx.service.adapter = parked
    worker: dict = {}

    def run_writer():
        try:
            worker["result"] = fx.service.execute(fx.request)
        except BaseException as error:  # re-raised below
            worker["error"] = error

    thread = threading.Thread(target=run_writer, name="1591-mixed-writer", daemon=True)
    thread.start()
    try:
        assert parked.parked.wait(timeout=WAIT_SECONDS), "the writer never reached the provider"
        # A real pre-agent-harness#1313 process promotes the live writer's owner.
        assert _run_old(_old_trees["prober"], _PROBER, str(fx.root), fx.identity) == ["RESULT True"]
    finally:
        parked.release.set()
        thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive()
    if "error" in worker:
        raise worker["error"]
    _assert_observed_effect(fx, key, worker["result"])

    # A reader that predates the side file answers byte-identically with or without it,
    # and the same as this runtime.
    with_file = _run_old(_old_trees["reader"], _READER, str(fx.root))
    aside = tmp_path / "aside.jsonl"
    shutil.move(fx.root / OBSERVATIONS, aside)
    try:
        without_file = _run_old(_old_trees["reader"], _READER, str(fx.root))
    finally:
        shutil.move(aside, fx.root / OBSERVATIONS)
    assert with_file == without_file
    current = _run_old(RUNTIME / "src", _READER, str(fx.root))
    assert with_file == current
    answer = json.loads(with_file[0])
    assert answer["epoch_blocked"] is True
    assert answer["replay"][key] == [AMBIGUOUS, "unsealed-adapter-start-owner"]


# ---------------------------------------------------------------------------
# Board round 1 (Consiliency/agent-harness#1633)
# (1) A rotation that starts during the provider call holds admissions.lock across
#     its drain: the observation waits for the lock instead of being refused by the
#     DRAINING latch, the held lease keeps the ceremony from draining, and only a
#     writer whose lease was cleared loses the observation.
# (2) A ceremony whose own journal already holds INVENTORY_SEALED resumes; the
#     successor's re-admission refusal guards the observed effect.
# ---------------------------------------------------------------------------


class _PromoteThenWaitForDrain(_CountingAdapter):
    """An older prober promotes during the call; the provider returns only once a
    ceremony has put the latch in DRAINING."""

    def __init__(self, p, monkeypatch, *, drain=None) -> None:
        super().__init__()
        self.p, self.monkeypatch, self.drain = p, monkeypatch, drain
        self.promoted = threading.Event()

    def execute(self, request):
        import time

        if not self.calls:
            _promote(self.p.container, self.p.identity, self.monkeypatch)
            self.promoted.set()
            if self.drain is not None:
                self.drain()
            latch = _live().WriterGenerationLatch.for_store_root(self.p.container)
            deadline = time.monotonic() + WAIT_SECONDS
            while latch.read().generation_state != "DRAINING":
                assert time.monotonic() < deadline, "the ceremony never began draining"
                time.sleep(0.01)
        return super().execute(request)


def test_drain_started_during_the_call_does_not_lose_the_observed_effect(tmp_path, monkeypatch):
    """Board F001 shape: DRAINING lands during the call; the effect is never published twice."""
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    live = _live()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    adapter = _promoting(p, monkeypatch, after=latch.begin_draining)
    key = p.service._dedup_key(p.request)
    result = p.service.execute(p.request)
    assert len(adapter.calls) == 1
    assert result.reason == EFFECT_REASON
    assert result.observed_after_ambiguity.durable is True
    latch.resume_active()
    with pytest.raises(live.PartitionRotationRefused):
        _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))


def test_real_ceremony_during_the_call_does_not_drain_then_observed_landed_rotates_once(tmp_path, monkeypatch):
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    key = p.service._dedup_key(p.request)
    live = _live()
    real_await = live.WriterGenerationLatch.await_quiescent
    monkeypatch.setattr(
        live.WriterGenerationLatch,
        "await_quiescent",
        lambda self, *, worktree, timeout=60.0: real_await(self, worktree=worktree, timeout=3.0),
    )
    adapter = _PromoteThenWaitForDrain(p, monkeypatch)
    p.service.adapter = adapter
    box: dict = {}

    def ceremony():
        try:
            assert adapter.promoted.wait(WAIT_SECONDS)
            box["outcome"] = _rotate(
                None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}), release=False
            )
        except BaseException as error:  # asserted below
            box["error"] = error

    thread = threading.Thread(target=ceremony, name="1633-ceremony", daemon=True)
    thread.start()
    first = p.service.execute(p.request)
    thread.join(WAIT_SECONDS * 2)
    assert not thread.is_alive()
    assert first.reason == EFFECT_REASON and first.observed_after_ambiguity.durable is True
    assert "did not drain" in str(box.get("error")), box
    assert live.WriterGenerationLatch.for_store_root(p.container).read().generation_state == "ACTIVE"
    again = p.service.execute(p.request)
    assert again.reason == EFFECT_REASON and again.provider_call_made is False
    _release_all(p)
    with pytest.raises(live.PartitionRotationRefused):
        _rotate(
            None, p, cutover_id="rotation-1633-2",
            attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}),
        )
    observation = first.observed_after_ambiguity
    observed = _attestation(p, dispositions={key: OBSERVED_LANDED}, observed_head=observation.head_sha)
    observed["effects"][key]["evidence_url"] = observation.evidence_reference
    outcome = _rotate(None, p, attestation=observed)
    second, calls = _publish_on_successor(None, outcome, p, p.request, adapter=_CountingAdapter())
    assert len(adapter.calls) + len(calls) == 1, "the observed effect was published twice"
    assert second.publish_result.pr_url == "https://gh/pr/1"


def test_writer_whose_lease_was_cleared_and_generation_rotated_is_still_refused(tmp_path, monkeypatch):
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    key = p.service._dedup_key(p.request)
    box: dict = {}

    class _PromoteThenRotate(_CountingAdapter):
        def execute(self, request):
            if not self.calls:
                _promote(p.container, p.identity, monkeypatch)
                _release_all(p)  # the operator cleared the writer's lease (runbook §6)
                box["outcome"] = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
            return super().execute(request)

    p.service.adapter = _PromoteThenRotate()
    first = p.service.execute(p.request)
    assert first.reason == "outcome_ambiguous" and first.observed_after_ambiguity is None
    assert box["outcome"].state == "ACTIVE"
    assert not (p.container / OBSERVATIONS).exists()
    assert not (box["outcome"].store_root / OBSERVATIONS).exists()


def test_ceremony_sealed_by_an_older_runtime_resumes_and_readmission_refuses(tmp_path, monkeypatch):
    """Board F002 shape: a sealed pre-flip ceremony must still complete after the upgrade."""
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired
    from test_fabpub_partition_rotation_789d import _crash_rotation

    fx, p, key, result, adapter = _observed_partition(tmp_path, monkeypatch)
    assert result.reason == EFFECT_REASON
    live = _live()
    real_refusal = live._refuse_attested_not_landed_over_observations
    attestation = _attestation(p, dispositions={key: ATTESTED_NOT_LANDED})
    monkeypatch.setattr(live, "_refuse_attested_not_landed_over_observations", lambda *_a, **_k: None)
    _crash_rotation(None, p, "after_journal_inventory_sealed", attestation=attestation)
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED"]
    monkeypatch.setattr(live, "_refuse_attested_not_landed_over_observations", real_refusal)
    # agent-harness#1633 round 2: the preflight mirrors the sealed-resume exemption.
    _release_all(p)
    report = _run_preflight(p, attestation, tmp_path, monkeypatch)
    assert report["verdict"] in ("ready", "ready_but_drain_will_block"), report
    assert "no_attested_not_landed_over_observed_effect" not in {c["check"] for c in report["checks"]}
    outcome = _rotate(None, p, attestation=attestation)
    assert outcome.state == "ACTIVE"
    retry = _CountingAdapter()
    refused, calls = _publish_on_successor(None, outcome, p, p.request, adapter=retry)
    assert isinstance(refused, PublicationRecoveryRequired), refused
    assert calls == [] and len(adapter.calls) == 1


def test_new_ceremony_sealed_before_a_leaseless_observation_resumes_and_readmission_refuses(tmp_path, monkeypatch):
    """The exemption cannot seal attested_not_landed over a recorded effect into a second call."""
    from phase_loop_runtime.convergence.broker.verbs import PublicationRecoveryRequired

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    key = p.service._dedup_key(p.request)
    live = _live()

    class _PromoteSealCrash(_CountingAdapter):
        def execute(self, request):
            if not self.calls:
                _promote(p.container, p.identity, monkeypatch)
                _release_all(p)
                with monkeypatch.context() as m:
                    m.setattr(live, "_ROTATION_CRASH_STEP", "after_journal_inventory_sealed")
                    with pytest.raises(Exception):
                        _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
            return super().execute(request)

    adapter = _PromoteSealCrash()
    p.service.adapter = adapter
    p.service.execute(p.request)
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED"]
    outcome = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    assert outcome.state == "ACTIVE"
    retry = _CountingAdapter()
    refused, calls = _publish_on_successor(None, outcome, p, p.request, adapter=retry)
    assert isinstance(refused, PublicationRecoveryRequired), refused
    assert calls == [] and len(adapter.calls) == 1


def test_fresh_and_draining_only_ceremonies_are_still_refused(tmp_path, monkeypatch):
    """The exemption applies only to a journal that already holds INVENTORY_SEALED."""
    fx, p, key, result, _adapter = _observed_partition(tmp_path, monkeypatch)
    live = _live()
    with pytest.raises(live.PartitionRotationRefused):
        _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    assert _journal_states(p) == []
    real_refusal = live._refuse_attested_not_landed_over_observations
    monkeypatch.setattr(live, "_refuse_attested_not_landed_over_observations", lambda *_a, **_k: None)
    with monkeypatch.context() as m:
        m.setattr(live, "_ROTATION_CRASH_STEP", "after_journal_draining")
        with pytest.raises(Exception):
            _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    monkeypatch.setattr(live, "_refuse_attested_not_landed_over_observations", real_refusal)
    assert _journal_states(p) == ["DRAINING"]
    _release_all(p)
    report = _run_preflight(p, _attestation(p, dispositions={key: ATTESTED_NOT_LANDED}), tmp_path, monkeypatch)
    assert report["verdict"] == "would_refuse", report
    assert report["checks"][-1]["check"] == "no_attested_not_landed_over_observed_effect"
    with pytest.raises(live.PartitionRotationRefused):
        _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    observation = result.observed_after_ambiguity
    observed = _attestation(p, dispositions={key: OBSERVED_LANDED}, observed_head=observation.head_sha)
    observed["effects"][key]["evidence_url"] = observation.evidence_reference
    assert _rotate(None, p, attestation=observed).state == "ACTIVE"


def test_ordinary_terminal_under_a_draining_latch_is_still_refused(tmp_path, monkeypatch):
    """Only the post-ambiguity branch tolerates DRAINING; a live row's terminal does not."""
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    key = p.service._dedup_key(p.request)
    live = _live()
    latch = live.WriterGenerationLatch.for_store_root(p.container)

    class _DrainDuringCall(_CountingAdapter):
        def execute(self, request):
            latch.begin_draining()
            return super().execute(request)

    p.service.adapter = adapter = _DrainDuringCall()
    try:
        with pytest.raises(live.WriterGenerationBlocked):
            p.service.execute(p.request)
        assert len(adapter.calls) == 1
        assert _key_states(p, key) == [IN_FLIGHT], "a terminal was appended under DRAINING"
        assert _owner(p.container)["sealed"] is False
        assert not (p.container / OBSERVATIONS).exists()
    finally:
        latch.resume_active()


def test_observation_authorization_under_draining_still_checks_the_lease(tmp_path, monkeypatch):
    """agent-harness#1633 round 2: DRAINING alone is tolerated; the lease is not."""
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    live = _live()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    generation = latch.read().generation
    valid = latch.acquire(generation=generation)
    revoked = latch.acquire(generation=generation)
    forged = latch.acquire(generation=generation)
    latch.begin_draining()
    try:
        BrokerEvidenceStore(p.container, generation_lease=valid)._authorize(allow_draining=True)
        os.unlink(revoked.path)
        with pytest.raises(live.WriterGenerationBlocked, match="revoked"):
            BrokerEvidenceStore(p.container, generation_lease=revoked)._authorize(allow_draining=True)
        body = json.loads(forged.path.read_text(encoding="utf-8"))
        body["nonce"] = "0" * len(str(body["nonce"]))
        forged.path.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(live.WriterGenerationBlocked, match="does not bind the current canonical generation"):
            BrokerEvidenceStore(p.container, generation_lease=forged)._authorize(allow_draining=True)
        with pytest.raises(live.WriterGenerationBlocked, match="DRAINING"):
            BrokerEvidenceStore(p.container, generation_lease=valid)._authorize()
    finally:
        latch.resume_active()
        valid.release()
        forged.path.unlink(missing_ok=True)  # its handle no longer matches the file
