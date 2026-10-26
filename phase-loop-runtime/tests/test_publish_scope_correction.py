"""Isolated real Git/broker controls for PublishScopeCorrection.v1."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import hashlib
import json
import subprocess

import pytest

from phase_loop_runtime import publishing
from phase_loop_runtime.convergence.broker.credsep import GitHubBrokerAdapter
from phase_loop_runtime.convergence.contracts import BrokerRequest, BrokerVerb
from phase_loop_runtime.publish_scope_correction import MODE, prepare
from test_convergence_live_enable import _fake_git_gh
from test_fabpub_shared_epoch import (
    _activate_repository_authority, _authority_preimage, _git, _init_repo,
    _service, _stage,
)


@pytest.fixture(autouse=True)
def _isolated_process_inventory(monkeypatch):
    # Cutover here prepares an isolated authority fixture; host process discovery
    # is covered by the native quiescence controls in test_fabpub_shared_epoch.
    # Their deliberately held legacy writer must not block this module under
    # xdist. Keep all cutover, receipt, generation and provider checks real.
    from phase_loop_runtime.convergence.broker import live

    monkeypatch.setattr(live, "_iter_live_run_train_processes", lambda: iter(()))


def _fixture(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-b", "feat/x")
    _stage(repo, "companion.py", "companion = True\n")
    _git(repo, "commit", "-m", "companion work")
    identity, namespace = _activate_repository_authority(tmp_path, repo, label="correction")
    _stage(repo, "a.py", "a = True\n")
    authority = _authority_preimage(identity, "feat/x")
    tx = publishing.prepare_publish_transaction(
        repo, owned_paths=("a.py",), checkpoint_root=tmp_path / "original",
        branch="feat/x", envelope_authority_preimage=authority,
    )
    tx.resume()
    calls = []
    fake = _fake_git_gh(head=tx.committed_head_sha, branch="feat/x")

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "git" and argv[3] in ("branch", "rev-parse", "diff"):
            return subprocess.run(argv, **kwargs)
        return fake(argv, **kwargs)

    adapter = GitHubBrokerAdapter(repo, run=run)
    service = _service(namespace, adapter)
    request = BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH,
        publishing._envelope_from_transaction(tx, authority, repo), identity,
        "feat/x", tx.committed_head_sha, tx.owned_paths, adapter_worktree=str(repo))
    result = service.execute(request)
    assert result.evidence.terminal_state == "no_effect_terminal_proven"
    assert result.evidence.evidence_reference == "owned-scope-exceeded:companion.py"
    assert not any("push" in x or "create" in x for x in calls)
    original = publishing.inspect_publish_resume_candidate(repo, checkpoint_root=tx.checkpoint_root, node_id=tx.store.node_id).transaction
    assert original.state == "TERMINAL_SEALED"
    return SimpleNamespace(repo=repo, original=original, service=service, request=request, calls=calls,
                           authority=authority, namespace=namespace, tmp=tmp_path)


def _correction(f, *, scope=("a.py", "companion.py"), **changes):
    authority = dict(f.authority, node_id="scope-correction",
                     effective_code_digest=hashlib.sha256("\0".join(scope).encode()).hexdigest())
    kw = dict(original_checkpoint_root=f.original.checkpoint_root,
              original_node_id=f.original.store.node_id, checkpoint_root=f.tmp / "corrected",
              owned_paths=scope, branch="feat/x", authority=authority,
              base=f.original.base, draft=f.original.draft, pr_body=f.original.pr_body)
    kw.update(changes)
    tx = prepare(f.repo, **kw)
    request = BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH,
        publishing._envelope_from_transaction(tx, authority, f.repo), f.request.repo,
        "feat/x", tx.committed_head_sha, tx.owned_paths, base=tx.base, draft=tx.draft,
        pr_body=tx.pr_body, adapter_worktree=str(f.repo), scope_correction_of=f.original.transaction_id)
    return tx, request


def _provider_calls(f):
    return sum("push" in c for c in f.calls), sum(c[:3] == ["gh", "pr", "create"] for c in f.calls)


def test_scope_correction_preserves_original_and_publishes_same_commit_once(tmp_path):
    f = _fixture(tmp_path)
    original_bytes = f.original.checkpoint_path.read_bytes()
    original_terminal = f.service.evidence_store.replay()[f.service._dedup_key(f.request)]
    head = _git(f.repo, "rev-parse", "HEAD")
    tx, request = _correction(f)
    assert tx.mode == MODE
    assert tx.final_commit_message_bytes == f.original.final_commit_message_bytes
    result = f.service.execute(request)
    assert result.accepted, result
    assert _provider_calls(f) == (1, 1)
    assert f.service.execute(request).accepted
    assert _provider_calls(f) == (1, 1)
    # Ordinary request still reports its original rejection; no terminal is replaced.
    assert f.service.execute(f.request).evidence.terminal_state == "no_effect_terminal_proven"
    assert f.service.evidence_store.replay()[f.service._dedup_key(f.request)] == original_terminal
    assert f.original.checkpoint_path.read_bytes() == original_bytes
    assert _git(f.repo, "rev-parse", "HEAD") == head
    assert _git(f.repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("change", ["scope", "body", "base", "proof", "head", "dirty"])
def test_scope_correction_refuses_changed_inputs_before_provider(tmp_path, change):
    f = _fixture(tmp_path)
    kw = {}
    if change == "scope": kw["scope"] = ("companion.py",)
    if change == "body": kw["pr_body"] = "changed body"
    if change == "base": kw["base"] = "main~1"
    if change == "proof": kw["authority"] = dict(f.authority, roadmap_digest="f" * 64)
    if change == "head":
        _stage(f.repo, "new.py", "changed\n")
        _git(f.repo, "commit", "-m", "different work")
    if change == "dirty": (f.repo / "unrelated.txt").write_text("preserve\n")
    with pytest.raises((PermissionError, publishing.PublishTransactionConflict)):
        _correction(f, **kw)
    assert _provider_calls(f) == (0, 0)


def test_scope_correction_reservation_refuses_different_successor_scope(tmp_path):
    f = _fixture(tmp_path)
    tx, request = _correction(f)
    from phase_loop_runtime.publish_scope_correction import authorize
    authorize(f.service, request)
    _other, conflicting = _correction(f, scope=("a.py", "companion.py", "extra.py"), checkpoint_root=tmp_path / "other")
    with pytest.raises(PermissionError, match="different scope correction"):
        f.service.execute(conflicting)
    assert f.service.execute(request).accepted
    assert _provider_calls(f) == (1, 1)


def test_scope_correction_request_must_bind_checkpoint_predecessor(tmp_path):
    f = _fixture(tmp_path)
    _tx, request = _correction(f)
    with pytest.raises(PermissionError): f.service.execute(replace(request, scope_correction_of="f" * 64))
    with pytest.raises(PermissionError): f.service.execute(replace(request, owned_paths=("a.py",)))
    assert _provider_calls(f) == (0, 0)


def test_scope_correction_refuses_unsealed_owner_and_corrupt_receipt(tmp_path):
    f = _fixture(tmp_path)
    _tx, request = _correction(f)
    from phase_loop_runtime.publish_scope_correction import authorize
    authorize(f.service, request)
    receipt = next(f.namespace.glob("scope-correction-*.json"))
    data = json.loads(receipt.read_text())
    data["committed_head"] = "f" * 40
    receipt.write_text(json.dumps(data))
    with pytest.raises(PermissionError, match="different scope correction"):
        f.service.execute(request)
    assert _provider_calls(f) == (0, 0)


def test_scope_correction_sdk_route_retries_after_reserved_receipt(tmp_path):
    f = _fixture(tmp_path)
    tx, request = _correction(f)
    from phase_loop_runtime.publish_scope_correction import authorize
    authorize(f.service, request)  # Crash boundary: reserved, not yet admitted.
    receipt = next(f.namespace.glob("scope-correction-*.json"))
    reserved = receipt.read_bytes()
    kw = dict(
        owned_paths=tx.owned_paths, broker_client=f.service,
        publish_authority=publishing.PublishAuthorityPreimages(tx.checkpoint_root, tx.envelope_authority_preimage),
        checkpoint_root=tx.checkpoint_root, base=tx.base, draft=tx.draft,
        pr_body=tx.pr_body,
        scope_correction_from=(f.original.checkpoint_root, f.original.store.node_id),
    )
    result = publishing.publish_from_worktree(f.repo, **kw)
    assert result["status"] == "published", result
    assert publishing.publish_from_worktree(f.repo, **kw)["status"] == "published"
    assert receipt.read_bytes() == reserved
    assert _provider_calls(f) == (1, 1)


@pytest.mark.parametrize("terminal", ["missing", "push-rejected", "ambiguous", "effect"])
def test_scope_correction_requires_exact_original_scope_terminal(tmp_path, monkeypatch, terminal):
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
    f = _fixture(tmp_path)
    _tx, request = _correction(f)
    # Model an unavailable or different authenticated predecessor at its read
    # boundary. No caller assertion about remote absence can authorize recovery.
    key = f.service._dedup_key(f.request)
    states = {"push-rejected": TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
              "ambiguous": TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED,
              "effect": TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED}
    records = {} if terminal == "missing" else {key: EvidenceRecord(key, states[terminal], "provider-result")}
    monkeypatch.setattr(f.service.evidence_store, "replay", lambda: records)
    with pytest.raises(PermissionError, match="ownership-scope no-effect"):
        f.service.execute(request)
    assert not list(f.namespace.glob("scope-correction-*.json"))
    assert _provider_calls(f) == (0, 0)


@pytest.mark.parametrize("field,value", [("base", "other"), ("draft", False), ("pr_body", "changed")])
def test_scope_correction_request_cannot_change_frozen_inputs(tmp_path, field, value):
    f = _fixture(tmp_path)
    _tx, request = _correction(f)
    with pytest.raises(PermissionError, match="frozen publication inputs"):
        f.service.execute(replace(request, **{field: value}))
    assert _provider_calls(f) == (0, 0)


def test_scope_correction_refuses_unsealed_predecessor_owner(tmp_path, monkeypatch):
    from phase_loop_runtime.convergence.broker import evidence
    f = _fixture(tmp_path)
    _tx, request = _correction(f)
    owner = evidence.read_adapter_start_owner(f.namespace, repository_identity=f.request.repo)
    monkeypatch.setattr(evidence, "read_adapter_start_owner", lambda *a, **kw: replace(owner, sealed=False))
    with pytest.raises(PermissionError, match="sealed predecessor owner"):
        f.service.execute(request)
    assert not list(f.namespace.glob("scope-correction-*.json"))
    assert _provider_calls(f) == (0, 0)


def test_scope_correction_concurrent_retries_enter_provider_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = _fixture(tmp_path)
    _tx, request = _correction(f)
    barrier = Barrier(2)
    fresh = f.service._fresh_publish
    def synchronized(*args):
        barrier.wait(timeout=15)
        return fresh(*args)
    f.service._fresh_publish = synchronized
    def attempt():
        try:
            return f.service.execute(request)
        except PermissionError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sum(getattr(r, "accepted", False) for r in results) >= 1, results
    assert _provider_calls(f) == (1, 1)


@pytest.mark.parametrize("outcome", ["predecessor-unavailable", "ambiguous"])
def test_scope_correction_handoff_does_not_offer_unsupported_rotation(tmp_path, monkeypatch, outcome):
    from phase_loop_runtime.convergence.broker import live
    from phase_loop_runtime.publish_scope_correction import ScopeCorrectionPredecessorUnavailable
    f = _fixture(tmp_path)
    plan, proof = tmp_path / "plan.md", tmp_path / "verification.json"
    plan.write_text("bounded correction\n")
    proof.write_text('{}\n')
    monkeypatch.setattr(publishing, "_check_gh_auth", lambda: None)
    monkeypatch.setattr(publishing, "_check_publish_origin", lambda repo: None)
    monkeypatch.setattr(live, "fabpub_activation_barrier", lambda repos: {"repositories": [str(f.repo)], "leases": []})
    monkeypatch.setattr(live, "release_barrier_leases", lambda report: None)
    monkeypatch.setattr(live, "build_routing_broker_client", lambda: f.service)
    def outcome_at_boundary(*args, **kwargs):
        if outcome == "predecessor-unavailable":
            raise ScopeCorrectionPredecessorUnavailable("active predecessor unavailable after rotation")
        return {"status": "publication_blocked", "reason": "outcome_ambiguous",
                "terminal_state": "outcome_ambiguous_blocked", "provider_call_made": True}
    monkeypatch.setattr(publishing, "publish_from_worktree", outcome_at_boundary)
    result = publishing.publish_human_invoked_from_worktree(
        f.repo, ["a.py", "companion.py"], plan_path=plan, verification_artifact_path=proof,
        scope_correction_from=(f.original.checkpoint_root, f.original.store.node_id),
    )
    expected = "inspect_scope_correction_predecessor" if outcome == "predecessor-unavailable" else "review_scope_correction_outcome"
    assert result["handoff"]["next_step"] == expected
    assert "does not support rotate-then-retry" in result["handoff"]["resume"]
    assert "rotate_command" not in result["handoff"]


@pytest.mark.parametrize("field,value", [
    ("pr_body", "changed after terminal"), ("draft", False), ("base", "other"),
    ("proof", "f" * 64),
])
def test_original_saved_inputs_remain_bound_to_original_intent(tmp_path, field, value):
    f = _fixture(tmp_path)
    original = json.loads(f.original.checkpoint_path.read_text())
    if field == "proof":
        original["envelope_authority_preimage"]["verification_plan_digest"] = value
    else:
        original[field] = value
    f.original.checkpoint_path.write_text(json.dumps(original))
    with pytest.raises(PermissionError, match="original predecessor intent"):
        _correction(f)
    assert not (tmp_path / "corrected").exists()
    assert _provider_calls(f) == (0, 0)


@pytest.mark.parametrize("field,value", [
    ("original_message_b64", "Y2hhbmdlZA=="),
    ("original_commit_message_sha256", "f" * 64),
    ("staged_diff_sha256", "f" * 64),
])
def test_successor_preserves_all_copied_original_metadata(tmp_path, field, value):
    f = _fixture(tmp_path)
    tx, request = _correction(f)
    data = json.loads(tx.checkpoint_path.read_text())
    data[field] = value
    tx.checkpoint_path.write_text(json.dumps(data))
    if field == "original_commit_message_sha256":
        request = replace(request, admission=replace(request.admission, original_commit_message_sha256=value))
    with pytest.raises(PermissionError, match="original metadata"):
        f.service.execute(request)
    assert _provider_calls(f) == (0, 0)


def test_advanced_head_with_complete_scope_refuses_before_successor_write(tmp_path):
    f = _fixture(tmp_path)
    _stage(f.repo, "new.py", "new = True\n")
    _git(f.repo, "commit", "-m", "new work after original refusal")
    with pytest.raises(PermissionError, match="HEAD must equal"):
        _correction(f, scope=("a.py", "companion.py", "new.py"))
    assert not (tmp_path / "corrected").exists()
    assert _provider_calls(f) == (0, 0)


def test_original_ref_remains_derived_from_original_branch(tmp_path):
    f = _fixture(tmp_path)
    _git(f.repo, "checkout", "-b", "feat/alternate")
    payload = json.loads(f.original.checkpoint_path.read_text())
    payload["exact_ref"] = "refs/heads/feat/alternate"
    f.original.checkpoint_path.write_text(json.dumps(payload))
    with pytest.raises(PermissionError, match="original predecessor branch reference"):
        _correction(f)
    assert not (tmp_path / "corrected").exists()
    assert _provider_calls(f) == (0, 0)


def test_correction_crash_before_provider_preserves_original_and_never_reenters(tmp_path):
    f = _fixture(tmp_path)
    original = f.original.checkpoint_path.read_bytes()
    _tx, request = _correction(f)
    with pytest.raises(publishing.PublishCrashInjected):
        with publishing.crash_after("after_broker_intent_before_adapter_started"):
            f.service.execute(request)
    assert _provider_calls(f) == (0, 0)
    with pytest.raises(PermissionError):
        f.service.execute(request)
    key = f.service._dedup_key(request)
    assert f.service.evidence_store.replay()[key].state.value == "outcome_ambiguous_blocked"
    assert _provider_calls(f) == (0, 0)
    assert f.original.checkpoint_path.read_bytes() == original


def test_correction_crash_after_provider_does_not_repeat_mutation(tmp_path):
    f = _fixture(tmp_path)
    original = f.original.checkpoint_path.read_bytes()
    _tx, request = _correction(f)
    with pytest.raises(publishing.PublishCrashInjected):
        with publishing.crash_after("after_provider_return_before_terminal"):
            f.service.execute(request)
    assert _provider_calls(f) == (1, 1)
    with pytest.raises(PermissionError):
        f.service.execute(request)
    assert _provider_calls(f) == (1, 1)
    assert f.original.checkpoint_path.read_bytes() == original


def test_correction_known_terminal_replays_after_seal_crash(tmp_path, monkeypatch):
    f = _fixture(tmp_path)
    original = f.original.checkpoint_path.read_bytes()
    tx, request = _correction(f)
    real_project = publishing.PublishTransaction.project
    def crash(self, state):
        if self.mode == "scope-correction-v1" and state == "TERMINAL_SEALED":
            raise publishing.PublishCrashInjected("after-terminal-before-sdk-seal")
        return real_project(self, state)
    with monkeypatch.context() as m:
        m.setattr(publishing.PublishTransaction, "project", crash)
        with pytest.raises(publishing.PublishCrashInjected):
            f.service.execute(request)
    result = publishing.publish_from_worktree(
        f.repo, tx.owned_paths, broker_client=f.service,
        publish_authority=publishing.PublishAuthorityPreimages(tx.checkpoint_root, tx.envelope_authority_preimage),
        checkpoint_root=tx.checkpoint_root, pr_body=tx.pr_body,
        scope_correction_from=(f.original.checkpoint_root, f.original.store.node_id),
    )
    assert result["status"] == "published"
    assert _provider_calls(f) == (1, 1)
    assert f.original.checkpoint_path.read_bytes() == original
    assert publishing.inspect_publish_resume_candidate(f.repo, checkpoint_root=tx.checkpoint_root,
        node_id=tx.store.node_id).state == "TERMINAL_SEALED"
