"""Exact-context retirement preserves publication history and normal replay."""
from __future__ import annotations

import dataclasses
import fcntl
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from phase_loop_runtime import publishing as pub
from phase_loop_runtime.convergence.broker import live, verbs
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore, EvidenceRecord, PostAmbiguityObservation
from phase_loop_runtime.convergence.contracts import AdmissionRequest, DeltaReadmitAuthority, ReadmitAdmissionBinding
from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
from test_publishing import _git, _make_repo, _human_publish_artifacts
from test_fabpub_shared_epoch import _CountingAdapter, _seed_legacy_root, _write_train, _manifest_row
from test_fabpub_partition_rotation_789d import _attestation


@pytest.fixture
def stranded(tmp_path, monkeypatch, request):
    repo = _make_repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    plan, proof = _human_publish_artifacts(tmp_path)
    authority_root = tmp_path / "authority"
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(authority_root))
    if getattr(request, "param", "zero") == "migrated":
        ledger = tmp_path / "legacy"
        train = _write_train(tmp_path / "train" / "release.md", str(repo))
        _seed_legacy_root(ledger, train_path=train, serialized_repo=str(repo), epochs=(1,))
        migration = live.run_legacy_broker_cutover(live.LegacyBrokerCutoverManifest(
            cutover_id="migrated-fixture", rows=(_manifest_row(ledger, train, repo, str(repo), tmp_path),),
        ))
        migration.activate()
    else:
        inventory = live.probe_zero_history_bootstrap(
            cutover_id="prebuilt-fixture", authority_root=authority_root, worktrees=(repo,),
        )
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
    monkeypatch.setattr(pub, "_check_gh_auth", lambda: None)
    (repo / "owned.py").write_text("value = 1\n")
    _git(repo, "add", "--", "owned.py")
    snapshot = live.repository_snapshot(repo)
    branch = _git(repo, "branch", "--show-current").stdout.strip()
    digest = pub._human_publication_context_digest(snapshot.identity, branch, ("owned.py",), pub._sha256(plan.read_bytes()), pub._sha256(proof.read_bytes()))
    checkpoint_root = snapshot.common_dir / "phase-loop-human-publication-v1" / digest
    authority = pub._human_publication_authority(
        repo, ("owned.py",), plan_sha256=pub._sha256(plan.read_bytes()),
        verification_artifact_sha256=pub._sha256(proof.read_bytes()), branch=branch,
        checkpoint_root=checkpoint_root,
    ).envelope_authority_preimage
    transaction = pub.prepare_prebuilt_transaction(
        repo, owned_paths=("owned.py",), checkpoint_root=checkpoint_root, branch=branch,
        envelope_authority_preimage=authority, node_id=authority["node_id"],
    )
    adapter = _CountingAdapter()
    monkeypatch.setattr(live.GitHubBrokerAdapter, "execute", lambda _self, request: adapter.execute(request))
    return SimpleNamespace(
        repo=repo, plan=plan, proof=proof, snapshot=snapshot, transaction=transaction,
        root=snapshot.store_root, container=snapshot.container, authority_root=authority_root,
        context=dict(checkpoint_root=checkpoint_root, node_id=authority["node_id"], authority=authority,
                     branch=branch, owned_paths=("owned.py",), base="main", draft=True, pr_body=""),
        adapter=adapter,
    )


def _retire(fx):
    with live.build_routing_broker_client() as router:
        router.abandon_unadmitted_prebuilt(fx.repo, fx.transaction.transaction_id, **fx.context)


def _publish(fx, *, recover=True, **options):
    return pub.publish_human_invoked_from_worktree(
        fx.repo, ("owned.py",), plan_path=fx.plan, verification_artifact_path=fx.proof,
        **({"abandon_unadmitted_prebuilt": fx.transaction.transaction_id} if recover else {}), **options,
    )


def _durable(fx):
    result = {}
    for directory in (fx.transaction.store.root, fx.container):
        for path in directory.rglob("*"):
            if path.name.endswith(".lock"):
                continue
            if path.is_symlink():
                result[str(path)] = ("link", os.readlink(path))
            elif path.is_file():
                result[str(path)] = path.read_bytes()
            elif not path.is_dir():
                result[str(path)] = "nonregular"
    return result


def _refused(fx):
    before = _durable(fx)
    with pytest.raises(pub.UnadmittedPrebuiltConflict) as raised:
        _retire(fx)
    assert raised.value.provider_call_made is False
    assert _durable(fx) == before
    assert fx.adapter.calls == []


def _checkpoint(fx, **changes):
    pub._atomic_json(fx.transaction.checkpoint_path, {**fx.transaction._payload, **changes})


def _owner(fx, **changes):
    return verbs.AdapterStartOwnership(
        **{**dict(repository_identity=fx.snapshot.identity, idempotency_key="unrelated",
                  transaction_id="other", attempt_id="other", committed_head="e" * 40,
                  adapter_operation="publish_committed_branch", owner_nonce="other", effect_key="unrelated", sealed=True), **changes}
    )


def _key(fx):
    from phase_loop_runtime.convergence.contracts import publish_committed_branch_idempotency_key
    return "publish_committed_branch\0" + publish_committed_branch_idempotency_key(fx.snapshot.identity, fx.context["branch"], fx.transaction.expected_commit_oid)


def _admission(fx, **changes):
    return AdmissionRequest(**{**dict(attempt_id="other", lease_epoch=1, fence_token="other", approval_digest="other",
                                    expected_version_predicate="other", authority_domain_scope="other", idempotency_key="other"), **changes})


def _append(path, row):
    with path.open("ab") as stream:
        stream.write(json.dumps(row).encode() + b"\n")


def test_recovery_preserves_history_and_publishes_once(stranded):
    fx = stranded
    original = fx.transaction.checkpoint_path.read_bytes()
    head = _git(fx.repo, "rev-parse", "HEAD").stdout
    index = _git(fx.repo, "write-tree").stdout
    ordinary = _publish(fx, recover=False)
    assert ordinary["reason"] == "publication_transaction_conflicted"
    assert fx.transaction.checkpoint_path.read_bytes() == original
    _retire(fx)
    retired = json.loads(fx.transaction.checkpoint_path.read_bytes())
    assert retired == {**json.loads(original), "state": "ABANDONED"}
    before_repeat = _durable(fx)
    assert _publish(fx, recover=False, prebuilt=True)["reason"] == "publication_workspace_invalid"
    assert _durable(fx) == before_repeat
    assert _git(fx.repo, "rev-parse", "HEAD").stdout == head
    assert _git(fx.repo, "write-tree").stdout == index
    result = _publish(fx)
    assert result["status"] == "published", result
    assert _git(fx.repo, "show", "HEAD:owned.py").stdout == "value = 1\n"
    assert len(fx.adapter.calls) == 1
    assert _publish(fx)["status"] == "published"
    assert len(fx.adapter.calls) == 1
    assert json.loads(fx.transaction.checkpoint_path.read_bytes()) == retired


def test_fresh_staged_prebuilt_refuses_before_preparation(stranded, monkeypatch):
    fx = stranded
    # A fresh context has no legacy checkpoint; the public preparation helper
    # above deliberately creates the old shape for recovery tests.
    fx.plan.write_text("# Another bounded plan\n")
    monkeypatch.setattr(pub, "prepare_prebuilt_transaction", lambda *_a, **_k: pytest.fail("prepared a staged prebuilt transaction"))
    result = _publish(fx, recover=False, prebuilt=True)
    assert result["reason"] == "publication_workspace_invalid"
    assert fx.adapter.calls == []


@pytest.mark.parametrize("stage", ["tombstone", "pointer", "checkpoint"])
def test_retirement_crash_retry_preserves_tombstone(stranded, monkeypatch, stage):
    fx = stranded
    if stage == "tombstone":
        original = pub.PublishTransaction.write_tombstone
        def crash(transaction, state):
            original(transaction, state)
            raise pub.PublishCrashInjected(stage)
        monkeypatch.setattr(pub.PublishTransaction, "write_tombstone", crash)
    elif stage == "pointer":
        original = Path.unlink
        def crash(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == fx.transaction.active_pointer_path:
                raise pub.PublishCrashInjected(stage)
            return result
        monkeypatch.setattr(Path, "unlink", crash)
    else:
        original = pub.PublishTransaction._write
        def crash(transaction):
            original(transaction)
            if transaction.state == "ABANDONED":
                raise pub.PublishCrashInjected(stage)
        monkeypatch.setattr(pub.PublishTransaction, "_write", crash)
    with pytest.raises(pub.PublishCrashInjected):
        _retire(fx)
    tombstone = fx.transaction.tombstone_path.read_bytes()
    candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
    if stage != "checkpoint":
        assert candidate.transaction.transaction_id == fx.transaction.transaction_id
        assert candidate.state == "CONFLICTED"
    if stage == "tombstone": monkeypatch.setattr(pub.PublishTransaction, "write_tombstone", original)
    elif stage == "pointer": monkeypatch.setattr(Path, "unlink", original)
    else: monkeypatch.setattr(pub.PublishTransaction, "_write", original)
    _retire(fx)
    assert fx.transaction.tombstone_path.read_bytes() == tombstone
    assert json.loads(fx.transaction.checkpoint_path.read_bytes())["state"] == "ABANDONED"
    assert fx.adapter.calls == []


@pytest.mark.parametrize("kind", ["legacy", "post-id", "post-key", "sidecar", "empty-owner", "bad-post", "bad-admissions"])
def test_auxiliary_witnesses_refuse(stranded, kind):
    fx = stranded
    if kind == "legacy":
        _append(fx.root / "legacy-promotions.jsonl", dict(idempotency_key=_key(fx), promotion_provenance={}))
    elif kind.startswith("post-"):
        row = PostAmbiguityObservation(
            _key(fx) if kind == "post-key" else "other", "no_effect_terminal_proven", "fixture",
            "e" * 40, "other", fx.transaction.transaction_id if kind == "post-id" else "other", "other", "e" * 64,
        ).row()
        _append(fx.root / "post-ambiguity-observations.jsonl", row)
    elif kind == "sidecar":
        fx.transaction.store.recovery_path(fx.transaction.transaction_id, 0).write_text("{}")
    else:
        path = fx.root / {"empty-owner": "adapter-start-owner.json", "bad-post": "post-ambiguity-observations.jsonl", "bad-admissions": "admissions.jsonl"}[kind]
        path.write_bytes(b"" if kind == "empty-owner" else b"not-json\n")
    _refused(fx)


@pytest.mark.parametrize("which", ["prior", "proposed"])
def test_readmission_authority_is_a_witness(stranded, which):
    fx = stranded
    request = DeltaReadmitAuthority(
        fx.snapshot.identity, str(fx.repo), str(fx.context["checkpoint_root"]), fx.context["branch"], "main",
        fx.transaction.expected_commit_oid if which == "prior" else "e" * 40,
        fx.transaction.expected_commit_oid if which == "proposed" else "f" * 40,
        "train", "node", "run", "roadmap", "provenance", ("owned.py",),
    )
    _append(fx.root / "admissions.jsonl", dict(sequence=1, epoch=1, request=dataclasses.asdict(request)))
    _refused(fx)


def test_changed_head_refuses_unfinished_retirement(stranded):
    fx = stranded
    _git(fx.repo, "commit", "-m", "later source")
    _refused(fx)


@pytest.mark.parametrize("shape", ["missing", "corrupt", "normal", "checkpoint-link", "tombstone-link"])
def test_nontrigger_inspector_shapes_stay_unchanged(stranded, shape, tmp_path):
    fx = stranded
    fx.transaction.store.clear_active(fx.transaction.transaction_id)
    fx.transaction.tombstone_path.write_text("not-json")
    if shape == "missing": fx.transaction.checkpoint_path.unlink()
    elif shape == "normal": _checkpoint(fx, mode="normal")
    elif shape == "checkpoint-link":
        target = tmp_path / "kept-checkpoint.json"
        target.write_bytes(fx.transaction.checkpoint_path.read_bytes())
        fx.transaction.checkpoint_path.unlink()
        fx.transaction.checkpoint_path.symlink_to(target)
    elif shape == "tombstone-link":
        fx.transaction.tombstone_path.unlink()
        fx.transaction.tombstone_path.symlink_to(tmp_path / "absent-tombstone")
    before = _durable(fx)
    candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
    assert candidate.state == "CONFLICTED"
    assert (candidate.transaction is None) == (shape == "missing")
    assert _durable(fx) == before


def test_two_normal_tombstones_keep_existing_empty_candidate(stranded):
    fx = stranded
    fx.transaction.store.clear_active(fx.transaction.transaction_id)
    _checkpoint(fx, mode="normal")
    fx.transaction.tombstone_path.write_text("not-json")
    fx.transaction.store.tombstone_path("e" * 64).write_text("not-json")
    candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
    assert candidate.state == "CONFLICTED" and candidate.transaction is None


def test_stale_admission_after_retirement_has_no_writes(stranded):
    fx = stranded
    request = pub._envelope_from_transaction(fx.transaction, fx.context["authority"], fx.repo)
    from phase_loop_runtime.convergence.contracts import BrokerRequest, BrokerVerb
    request = BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, request, fx.snapshot.identity, fx.context["branch"], fx.transaction.expected_commit_oid, ("owned.py",), adapter_worktree=str(fx.repo))
    _retire(fx)
    with live.build_routing_broker_client() as router:
        service = router._service_for(str(fx.repo))
        before = _durable(fx)
        with pytest.raises(PermissionError):
            service._owner_and_admission_under_one_lock(request, _owner(fx), lambda _epoch: _admission(fx), "other")
        assert _durable(fx) == before
    assert fx.adapter.calls == []


@pytest.mark.parametrize("field,value", [
    ("mode", "normal"), ("state", "ADMISSION_DURABLE"), ("state", "TERMINAL_SEALED"),
    ("state", "CONFLICTED"), ("base_tip_sha", "e" * 40),
    ("staged_diff_sha256", pub._sha256(b"")), ("canonical_repository_identity", "other"),
    ("repo", "/other"), ("checkpoint_root", "/other"), ("branch", "other"),
    ("exact_ref", "refs/heads/other"), ("node_id", "other"),
])
def test_checkpoint_mismatch_refuses_without_writes(stranded, field, value):
    _checkpoint(stranded, **{field: value})
    _refused(stranded)


@pytest.mark.parametrize("field,value", [("branch", "other"), ("owned_paths", ("other.py",)), ("base", "other"), ("draft", False), ("pr_body", "other"), ("node_id", "other")])
def test_context_mismatch_refuses_without_writes(stranded, field, value):
    stranded.context[field] = value
    _refused(stranded)


@pytest.mark.parametrize("witness", ["fence", "attempt", "key", "envelope", "unknown", "binding-head", "binding-attempt", "malformed-envelope", "torn"])
def test_admission_witnesses_refuse(stranded, witness):
    fx = stranded
    attempt = pub.publish_attempt_id(fx.snapshot.identity, fx.context["branch"], fx.transaction.expected_commit_oid)
    request = _admission(fx, **({"fence_token": fx.transaction.transaction_id} if witness == "fence" else
                              {"attempt_id": attempt} if witness == "attempt" else
                              {"idempotency_key": _key(fx)} if witness == "key" else {}))
    if witness in ("envelope", "malformed-envelope"):
        request = pub._envelope_from_transaction(fx.transaction, fx.context["authority"], fx.repo)
        if witness == "malformed-envelope":
            request = dataclasses.replace(request, operation_identity="other", transaction_id="e" * 64)
    row = dict(sequence=1, epoch=1, request=dataclasses.asdict(request))
    if witness == "unknown":
        row["request"] = {"future": "request"}
    if witness.startswith("binding-"):
        row["binding"] = dataclasses.asdict(ReadmitAdmissionBinding(
            fx.transaction.expected_commit_oid if witness == "binding-head" else "e" * 40,
            "f" * 40, "other", ("other.py",), "other", attempt if witness == "binding-attempt" else "other",
        ))
    path = fx.root / "admissions.jsonl"
    _append(path, row)
    if witness == "torn":
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
    _refused(fx)


@pytest.mark.parametrize("state", list(TerminalOutcomeState))
def test_every_evidence_class_is_a_witness(stranded, state):
    _append(stranded.root / "evidence.jsonl", dict(idempotency_key=_key(stranded), state=state.value, evidence_reference="fixture"))
    _refused(stranded)


@pytest.mark.parametrize("field", ["transaction_id", "attempt_id", "effect_key", "idempotency_key", "unsealed", "alias"])
def test_owner_witnesses_refuse(stranded, field):
    fx = stranded
    changes = {field: fx.transaction.transaction_id if field == "transaction_id" else
               pub.publish_attempt_id(fx.snapshot.identity, fx.context["branch"], fx.transaction.expected_commit_oid) if field == "attempt_id" else _key(fx)}
    if field == "unsealed": changes = {"sealed": False}
    if field == "alias": changes = {}
    row = dataclasses.asdict(_owner(fx, **changes))
    if field == "alias": row["owner_alias"] = row.pop("transaction_id")
    (fx.root / "adapter-start-owner.json").write_text(json.dumps(row))
    _refused(fx)


@pytest.mark.parametrize("name", ["admissions.jsonl", "evidence.jsonl", "adapter-start-owner.json", "post-ambiguity-observations.jsonl", "legacy-promotions.jsonl", "partition-receipt.json", "checkpoint", "tombstone", "sidecar"])
@pytest.mark.parametrize("kind", ["dangling", "symlink", "directory", "fifo"])
def test_nonregular_inputs_refuse_without_following(stranded, name, kind, tmp_path):
    fx = stranded
    path = fx.transaction.checkpoint_path if name == "checkpoint" else fx.transaction.tombstone_path if name == "tombstone" else fx.transaction.store.recovery_path(fx.transaction.transaction_id, 0) if name == "sidecar" else fx.root / name
    if path.exists(): path.unlink()
    target = tmp_path / "alias-target"
    if kind == "symlink": target.write_text("{}\n")
    if kind in ("dangling", "symlink"): path.symlink_to(target)
    elif kind == "directory": path.mkdir()
    else: os.mkfifo(path)
    _refused(fx)


def test_empty_snapshot_never_reopens_a_path(tmp_path):
    path = tmp_path / "unreadable"
    path.symlink_to(tmp_path / "missing")
    for cls, reader in [(LinearizableAdmissionStore, "_records"), (BrokerEvidenceStore, "replay")]:
        store = object.__new__(cls)
        store.path = path
        assert getattr(store, reader)(b"") in ([], {})


def test_draining_and_revoked_lease_refuse_before_writes(stranded):
    fx = stranded
    with live.build_routing_broker_client() as router:
        service = router._service_for(str(fx.repo))
        service.evidence_store.generation_lease.release()
        before = _durable(fx)
        with pytest.raises(pub.UnadmittedPrebuiltConflict):
            service.abandon_unadmitted_prebuilt(fx.snapshot, fx.transaction.transaction_id, **fx.context)
        assert _durable(fx) == before
    latch = live.WriterGenerationLatch(fx.snapshot.namespace_root)
    latch.begin_draining()
    _refused(fx)


def test_generations_entry_refuses_writing(stranded):
    generations = stranded.container / live.GENERATIONS_DIR
    generations.mkdir()
    (generations / live.ACTIVE_POINTER).write_bytes(b"0\n")
    _refused(stranded)


def test_stale_handle_cannot_project_resume_or_conflict(stranded):
    fx = stranded
    _retire(fx)
    before = _durable(fx)
    for action in (lambda: fx.transaction.project(fx.transaction.state), fx.transaction.resume, lambda: fx.transaction._conflict("stale")):
        with pytest.raises(pub.PublishTransactionConflict): action()
        assert _durable(fx) == before


def test_conflict_first_is_never_retired(stranded):
    fx = stranded
    with pytest.raises(pub.PublishTransactionConflict): fx.transaction._conflict("first")
    _refused(fx)


def test_stale_handle_with_dangling_tombstone_refuses(stranded, tmp_path):
    fx = stranded
    fx.transaction.tombstone_path.symlink_to(tmp_path / "missing")
    before = _durable(fx)
    with pytest.raises(pub.PublishTransactionConflict): fx.transaction.project(fx.transaction.state)
    assert _durable(fx) == before


def test_completed_inspection_is_read_only_under_admissions_lock(stranded):
    fx = stranded
    _retire(fx)
    before = _durable(fx)
    done = threading.Event()
    result = []
    with (fx.root / "admissions.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        def lock_and_lease_files():
            namespace = fx.snapshot.namespace_root
            leases = namespace / "generation-leases"
            paths = set(namespace.rglob("*.lock")) | set(leases.glob("*"))
            return leases.exists(), {str(path): (path.stat().st_ino, path.read_bytes()) for path in paths}

        metadata_before = lock_and_lease_files()
        thread = threading.Thread(target=lambda: (result.append(pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])), done.set()), daemon=True)
        thread.start()
        assert done.wait(5), "inspection waited for a writer lock"
        thread.join(5)
        assert lock_and_lease_files() == metadata_before
    assert result[0].transaction is None
    assert _durable(fx) == before


def test_completed_done_takes_no_router_lease(stranded, monkeypatch):
    fx = stranded
    _retire(fx)
    monkeypatch.setattr(live._RepositoryRoutingBrokerService, "_service_for", lambda *_a, **_k: pytest.fail("Done took a lease"))
    _retire(fx)


def test_retired_history_keeps_a_later_conflict_attached(stranded):
    fx = stranded
    _retire(fx)
    later = pub.prepare_publish_transaction(fx.repo, owned_paths=("owned.py",), checkpoint_root=fx.context["checkpoint_root"], branch=fx.context["branch"], envelope_authority_preimage=fx.context["authority"], node_id=fx.context["node_id"], commit_message="later")
    with pytest.raises(pub.PublishTransactionConflict): later._conflict("later")
    candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
    assert candidate.transaction.transaction_id == later.transaction_id
    assert candidate.state == "CONFLICTED"
    extra = later.store.tombstone_path("e" * 64)
    pub._atomic_json(extra, {"schema": "PublishTransactionTombstone.v1", "transaction_id": "e" * 64, "state": "CONFLICTED"})
    with pytest.raises(pub.PublishTransactionConflict):
        pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])


@pytest.mark.parametrize("kind", ["none", "admission", "no-effect", "owner", "owner-key", "owner-attempt", "unknown", "effect", "disposition", "drift", "post-link", "legacy-link"] + [
    f"{shape}:{name}" for shape in ("fifo", "symlink", "directory") for name in (
        "partition-receipt.json", "admissions.jsonl", "evidence.jsonl", "adapter-start-owner.json",
        "post-ambiguity-observations.jsonl", "legacy-promotions.jsonl",
    )
])
def test_completed_history_after_unrelated_rotation(stranded, kind):
    fx = stranded
    _retire(fx)
    with live.build_routing_broker_client() as router:
        service = router._service_for(str(fx.repo))
        if kind == "admission":
            _append(fx.root / "admissions.jsonl", dict(sequence=1, epoch=1, request=dataclasses.asdict(_admission(fx, fence_token=fx.transaction.transaction_id))))
        if kind == "unknown":
            _append(fx.root / "admissions.jsonl", dict(sequence=1, epoch=1, request={"future": "shape"}))
        if kind in ("no-effect", "effect", "disposition"):
            service.evidence_store.record_intent(_key(fx))
            state = TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN if kind == "no-effect" else TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED if kind == "effect" else TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
            service.evidence_store.record_terminal(EvidenceRecord(_key(fx), state, "fixture"))
        if kind in ("owner", "owner-key", "owner-attempt"):
            changes = {"transaction_id": fx.transaction.transaction_id} if kind == "owner" else {"idempotency_key": _key(fx)} if kind == "owner-key" else {"attempt_id": pub.publish_attempt_id(fx.snapshot.identity, fx.context["branch"], fx.transaction.expected_commit_oid)}
            verbs._owner_atomic_write(fx.root / "adapter-start-owner.json", _owner(fx, **changes))
        unrelated = "publish_committed_branch\0unrelated"
        service.evidence_store.record_intent(unrelated)
        service.evidence_store.record_terminal(EvidenceRecord(unrelated, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "fixture"))
    partition = SimpleNamespace(repo=fx.repo, container=fx.container)
    attestation = _attestation(partition)
    live.rotate_blocked_partition(fx.repo, cutover_id="unrelated-rotation", attestation=attestation, authority_root=fx.authority_root)
    if kind == "drift":
        _append(fx.root / "admissions.jsonl", dict(sequence=1, epoch=1, request=dataclasses.asdict(_admission(fx))))
    if kind in ("post-link", "legacy-link"):
        (fx.root / ("post-ambiguity-observations.jsonl" if kind == "post-link" else "legacy-promotions.jsonl")).symlink_to(fx.repo / "missing")
    if ":" in kind:
        shape, name = kind.split(":", 1)
        path = fx.root / name
        if path.exists(): path.unlink()
        if shape == "fifo": os.mkfifo(path)
        elif shape == "directory": path.mkdir()
        else: path.symlink_to(fx.repo / "missing")
    if kind == "none":
        _retire(fx)
        assert _publish(fx)["status"] == "published"
        assert len(fx.adapter.calls) == 1
    else:
        _refused(fx)
        candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
        assert candidate.transaction.transaction_id == fx.transaction.transaction_id


@pytest.mark.parametrize("stranded", ["migrated"], indirect=True)
def test_migrated_generation_zero_refuses_retirement_writes(stranded):
    receipt = live.load_partition_receipt(stranded.root)
    assert not receipt.zero_source and receipt.legacy_epoch_high_water == 1
    _refused(stranded)


def test_completed_replay_preserves_replacement_owner_handoff(stranded):
    fx = stranded
    _retire(fx)
    replacement = pub.prepare_publish_transaction(
        fx.repo, owned_paths=("owned.py",), checkpoint_root=fx.context["checkpoint_root"],
        branch=fx.context["branch"], envelope_authority_preimage=fx.context["authority"],
        node_id=fx.context["node_id"], commit_message="replacement",
    )
    replacement.resume()
    replacement_bytes = replacement.checkpoint_path.read_bytes()
    verbs._owner_atomic_write(fx.root / "adapter-start-owner.json", _owner(
        fx, transaction_id=replacement.transaction_id, committed_head=replacement.expected_commit_oid,
        idempotency_key="publish_committed_branch\0replacement", effect_key="publish_committed_branch\0replacement", sealed=False,
    ))
    result = _publish(fx)
    assert result["status"] == "publication_blocked"
    assert result["handoff"]["next_step"] == "adjudicate_publication_by_partition_rotation"
    assert replacement.checkpoint_path.read_bytes() == replacement_bytes
    assert fx.adapter.calls == []


@pytest.mark.parametrize("action", ["project", "conflict"])
def test_tombstone_is_rechecked_after_waiting_for_transaction_lock(stranded, monkeypatch, action):
    import contextlib

    fx = stranded
    original = pub.PublishTransactionStore.exclusive
    waiting = threading.Event()
    outcomes = []
    main_thread = threading.get_ident()

    @contextlib.contextmanager
    def observed_lock(store):
        if threading.get_ident() != main_thread:
            waiting.set()
        with original(store):
            yield

    monkeypatch.setattr(pub.PublishTransactionStore, "exclusive", observed_lock)

    def contender():
        try:
            if action == "project": fx.transaction.project(fx.transaction.state)
            else: fx.transaction._conflict("waiting contender")
        except pub.PublishTransactionConflict as error:
            outcomes.append(error)

    checkpoint = fx.transaction.checkpoint_path.read_bytes()
    with original(fx.transaction.store):
        thread = threading.Thread(target=contender, daemon=True)
        thread.start()
        assert waiting.wait(5)
        # The first retirement write lands while the contender waits; the
        # durable checkpoint still has exactly its original state and bytes.
        fx.transaction.write_tombstone("ABANDONED")
        tombstone = fx.transaction.tombstone_path.read_bytes()
    thread.join(5)
    assert not thread.is_alive() and len(outcomes) == 1
    assert fx.transaction.checkpoint_path.read_bytes() == checkpoint
    assert fx.transaction.tombstone_path.read_bytes() == tombstone
    assert fx.adapter.calls == []


def test_completed_identity_mismatch_keeps_history_blocking(stranded):
    fx = stranded
    _retire(fx)
    _checkpoint(fx, state="ABANDONED", canonical_repository_identity="f" * 64)
    _refused(fx)
    before = _durable(fx)
    candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
    assert candidate.state == "CONFLICTED"
    assert candidate.transaction.transaction_id == fx.transaction.transaction_id
    assert _durable(fx) == before


@pytest.mark.parametrize("field", ["canonical_repository_identity", "repo", "checkpoint_root", "node_id", "repository", "unloadable"])
def test_completed_replay_preserves_invalid_replacement(stranded, field):
    fx = stranded
    _retire(fx)
    replacement = pub.prepare_publish_transaction(
        fx.repo, owned_paths=("owned.py",), checkpoint_root=fx.context["checkpoint_root"],
        branch=fx.context["branch"], envelope_authority_preimage=fx.context["authority"],
        node_id=fx.context["node_id"], commit_message="replacement",
    )
    payload = {**replacement._payload, "state": "TERMINAL_SEALED"}
    if field == "unloadable": payload.pop("final_message_b64")
    else: payload[field] = str(fx.repo / "other") if field in ("repo", "checkpoint_root") else "f" * 64
    pub._atomic_json(replacement.checkpoint_path, payload)
    before = _durable(fx)
    head = _git(fx.repo, "rev-parse", "HEAD").stdout
    index = _git(fx.repo, "diff", "--cached", "--binary").stdout
    result = _publish(fx)
    assert result["status"] == "publication_blocked"
    assert result["reason"] == "publication_transaction_conflicted"
    assert result["provider_call_made"] is False
    assert _durable(fx) == before
    assert _git(fx.repo, "rev-parse", "HEAD").stdout == head
    assert _git(fx.repo, "diff", "--cached", "--binary").stdout == index
    assert fx.adapter.calls == []


def test_sibling_pointer_keeps_existing_inspector_result(stranded):
    fx = stranded
    pub.PublishTransactionStore(fx.context["checkpoint_root"], "other").write_active("e" * 64)
    before = _durable(fx)
    candidate = pub.inspect_publish_resume_candidate(fx.repo, checkpoint_root=fx.context["checkpoint_root"], node_id=fx.context["node_id"])
    assert candidate.state == "CONFLICTED" and candidate.transaction is None
    assert _durable(fx) == before


@pytest.mark.parametrize("transaction_id", ["a" * 63, "A" * 64, "g" * 64, False])
def test_invalid_recovery_id_refuses_before_work(stranded, monkeypatch, transaction_id):
    fx = stranded
    calls = []
    def unexpected(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeError("unexpected work")
    monkeypatch.setattr(live, "repository_snapshot", unexpected)
    monkeypatch.setattr(pub, "_check_gh_auth", unexpected)
    before = _durable(fx)
    result = _publish(fx, recover=False, abandon_unadmitted_prebuilt=transaction_id)
    assert result["reason"] == "publication_transaction_conflicted"
    assert result["provider_call_made"] is False
    with live.build_routing_broker_client() as router:
        with pytest.raises(pub.UnadmittedPrebuiltConflict, match="exact lowercase") as raised:
            router.abandon_unadmitted_prebuilt(fx.repo, transaction_id, **fx.context)
    assert raised.value.provider_call_made is False
    assert calls == [] and fx.adapter.calls == []
    assert _durable(fx) == before


@pytest.mark.parametrize("options", [{"prebuilt": True}, {"scope_correction_from": (Path("unused"), "e" * 64)}])
def test_recovery_mode_combination_refuses_before_work(stranded, monkeypatch, options):
    fx = stranded
    monkeypatch.setattr(pub, "_check_gh_auth", lambda: pytest.fail("invalid combination reached authentication"))
    before = _durable(fx)
    result = _publish(fx, **options)
    assert result["reason"] == "publication_transaction_conflicted"
    assert result["provider_call_made"] is False
    assert _durable(fx) == before and fx.adapter.calls == []


@pytest.mark.parametrize("kind", ["missing", "other"])
def test_wrong_recovery_id_preserves_transactions(stranded, kind):
    fx = stranded
    transaction_id = "f" * 64
    if kind == "other":
        fx.transaction.store.clear_active(fx.transaction.transaction_id)
        other = pub.prepare_publish_transaction(
            fx.repo, owned_paths=("owned.py",), checkpoint_root=fx.context["checkpoint_root"],
            branch=fx.context["branch"], envelope_authority_preimage=fx.context["authority"],
            node_id=fx.context["node_id"], commit_message="other transaction",
        )
        transaction_id = other.transaction_id
        assert transaction_id != fx.transaction.transaction_id
    before = _durable(fx)
    result = _publish(fx, recover=False, abandon_unadmitted_prebuilt=transaction_id)
    assert result["reason"] == "publication_transaction_conflicted"
    assert result["provider_call_made"] is False
    assert _durable(fx) == before and fx.adapter.calls == []


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_missing_or_corrupt_tombstone_refuses(stranded, completed, kind):
    fx = stranded
    if completed: _retire(fx)
    if kind == "missing":
        if completed: fx.transaction.tombstone_path.unlink()
        else: fx.transaction.store.clear_active(fx.transaction.transaction_id)
    else: fx.transaction.tombstone_path.write_text("not-json")
    _refused(fx)


def test_unrelated_ambiguity_refuses_retirement_writes(stranded):
    fx = stranded
    with live.build_routing_broker_client() as router:
        service = router._service_for(str(fx.repo))
        key = "publish_committed_branch\0unrelated"
        service.evidence_store.record_intent(key)
        service.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "fixture"))
    _refused(fx)


@pytest.mark.parametrize("scenario", ["active", "rotated-completed", "rotated-unfinished"])
def test_public_recovery_screens_fifo_before_activation(stranded, monkeypatch, scenario):
    fx = stranded
    if scenario == "rotated-completed": _retire(fx)
    if scenario != "active":
        with live.build_routing_broker_client() as router:
            service = router._service_for(str(fx.repo))
            key = "publish_committed_branch\0unrelated"
            service.evidence_store.record_intent(key)
            service.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "fixture"))
        live.rotate_blocked_partition(fx.repo, cutover_id="unrelated-rotation", attestation=_attestation(SimpleNamespace(repo=fx.repo, container=fx.container)), authority_root=fx.authority_root)
    path = fx.root / live.RECEIPT_FILENAME
    path.unlink()
    os.mkfifo(path)
    before = _durable(fx)
    # A regression fails at this boundary instead of blocking in the real loader.
    monkeypatch.setattr(live, "fabpub_activation_barrier", lambda *_a, **_k: pytest.fail("nonregular history reached activation"))
    result = _publish(fx)
    assert result["reason"] == "publication_transaction_conflicted"
    assert result["provider_call_made"] is False
    assert _durable(fx) == before and fx.adapter.calls == []


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("name", ["partition-receipt.json", "admissions.jsonl", "evidence.jsonl", "adapter-start-owner.json", "post-ambiguity-observations.jsonl", "legacy-promotions.jsonl"])
def test_unfinished_rotated_recovery_screens_predecessor_before_routing(stranded, monkeypatch, partial, name):
    fx = stranded
    if partial: fx.transaction.write_tombstone("ABANDONED")
    with live.build_routing_broker_client() as router:
        service = router._service_for(str(fx.repo))
        key = "publish_committed_branch\0unrelated"
        service.evidence_store.record_intent(key)
        service.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "fixture"))
    live.rotate_blocked_partition(fx.repo, cutover_id="unrelated-rotation", attestation=_attestation(SimpleNamespace(repo=fx.repo, container=fx.container)), authority_root=fx.authority_root)
    path = fx.root / name
    if path.exists(): path.unlink()
    os.mkfifo(path)
    monkeypatch.setattr(live._RepositoryRoutingBrokerService, "_service_for", lambda *_a, **_k: pytest.fail("nonregular history reached store selection"))
    _refused(fx)
