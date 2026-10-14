"""Synchronous publisher exclusion for agent-harness#820; no live providers."""

import contextlib
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime.convergence.broker import live
from phase_loop_runtime.convergence.broker.credsep import GitHubBrokerAdapter
from phase_loop_runtime.convergence.broker.verbs import read_adapter_start_owner
from test_convergence_broker_credsep import (
    _BRANCH, _FakeRun, _base_responses, _request, _same_repo_pr,
)
from test_fabpub_recovery_controls_789 import _two_partitions
from test_fabpub_shared_epoch import (
    _authorized_publish_fixture, _git, _publish_transaction_request, _service,
)


@pytest.fixture(autouse=True)
def _activated_contract():
    assert live.fabpub_capability_active(), "run with PHASE_LOOP_TDD_EXPECT_FABPUB=1"


@pytest.fixture
def fx(tmp_path):
    repo, transaction, identity, root = _authorized_publish_fixture(tmp_path, name="effect")
    latch = live.WriterGenerationLatch.for_store_root(root)
    lease = latch.acquire(generation=latch.read().generation)
    request = _publish_transaction_request(identity, _BRANCH, transaction, repo)
    responses = _base_responses()
    responses[1] = (("rev-parse",), transaction.committed_head_sha, 0)
    run = _FakeRun(responses + [
        (("ls-remote",), f"{transaction.committed_head_sha}\trefs/heads/{_BRANCH}", 0),
        (("list",), json.dumps([_same_repo_pr(head=transaction.committed_head_sha)]), 0),
    ])
    adapter = GitHubBrokerAdapter(repo, run=run, generation_lease=lease)
    yield SimpleNamespace(repo=repo, root=root, identity=identity, latch=latch,
                          lease=lease, request=request, run=run, adapter=adapter)
    lease.release()


def _lock_available(path):
    result = subprocess.run([
        sys.executable, "-c",
        "import fcntl,sys\n"
        "with open(sys.argv[1], 'a+') as f:\n"
        " try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        " except BlockingIOError: sys.exit(17)\n",
        str(path),
    ], capture_output=True, text=True, timeout=5)
    assert result.returncode in (0, 17), result.stderr
    return result.returncode == 0


def _wait_file(path, process):
    deadline = time.monotonic() + 10
    while not path.exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"contender exited before acknowledgement: {stdout!r} {stderr!r}")
        time.sleep(0.01)
    assert path.exists(), "independent contender did not acknowledge readiness"


@contextlib.contextmanager
def _contender(fx, tmp_path, operation, *, store_lock=None):
    directory = tmp_path / f"contender-{operation}"
    directory.mkdir()
    ready, done = directory / "ready", directory / "done"
    config = {"root": str(fx.latch.root), "generation": fx.lease.generation,
              "nonce": fx.lease.nonce, "operation": operation,
              "ready": str(ready), "done": str(done),
              "store_lock": str(store_lock) if store_lock else None}
    # exec starts a fresh interpreter: no inherited reentrancy table or lock fd.
    code = """
import contextlib, fcntl, json, sys
from pathlib import Path
from phase_loop_runtime.convergence.broker.live import WriterGenerationLatch, WriterGenerationLease
c = json.loads(sys.argv[1])
latch = WriterGenerationLatch(Path(c['root']))
with contextlib.ExitStack() as stack:
    if c['store_lock']:
        lock = stack.enter_context(open(c['store_lock'], 'a+'))
        fcntl.flock(lock, fcntl.LOCK_EX)
    Path(c['ready']).write_text('ready')
    if c['operation'] == 'release':
        WriterGenerationLease(latch, c['generation'], c['nonce']).release()
    else:
        latch.begin_draining()
Path(c['done']).write_text('done')
"""
    process = subprocess.Popen([sys.executable, "-c", code, json.dumps(config)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_file(ready, process)
        yield process, done
    finally:
        if process.poll() is None:
            process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        (directory / "stdout.txt").write_text(stdout)
        (directory / "stderr.txt").write_text(stderr)


@contextlib.contextmanager
def _pause_at(fx, token, invoke=None):
    entered, resume = threading.Event(), threading.Event()

    def run(args, **kwargs):
        if token in args:
            entered.set()
            assert resume.wait(10), "test watchdog: provider pause was not released"
        return fx.run(args, **kwargs)

    fx.adapter.run = run
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke or (lambda: fx.adapter.execute(fx.request)))
        try:
            assert entered.wait(10), "publisher did not reach requested pause"
            yield future, resume
        finally:
            resume.set()


def _mutations(fx, token):
    return sum(token in args for args in fx.run.calls)


@pytest.mark.parametrize("effect", ["push", "create"])
@pytest.mark.parametrize("operation", ["release", "drain"])
def test_effect_excludes_independent_release_and_drain(fx, tmp_path, effect, operation):
    before = fx.latch.read()
    with _pause_at(fx, effect) as (future, resume):
        assert not _lock_available(fx.latch.lock_path), "synchronous mutation lost its generation lock"
        with _contender(fx, tmp_path, operation) as (process, done):
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.1)
            assert not done.exists()
            assert process.poll() is None
            assert fx.latch.read() == before
            resume.set()
            assert process.wait(timeout=10) == 0
            assert done.exists(), "lease/drain must complete after the synchronous effect"
        try:
            future.result(timeout=10)
        except live.WriterGenerationBlocked:
            pass  # Revocation may win the separate next-effect check.
    assert _lock_available(fx.latch.lock_path)
    assert _mutations(fx, effect) == 1


@pytest.mark.parametrize("temporary", [False, True])
def test_drain_between_effects_retains_inflight_unsealed_owner(fx, tmp_path, temporary):
    if temporary:
        fx.adapter = GitHubBrokerAdapter(fx.repo, run=fx.run)
    service = _service(fx.root, fx.adapter)
    try:
        with _pause_at(fx, "log", lambda: service.execute(fx.request)) as (future, resume):
            assert _mutations(fx, "push") == 1
            assert _lock_available(fx.latch.lock_path), "title probe must be outside both fences"
            with _contender(fx, tmp_path, "drain") as (process, done):
                assert process.wait(timeout=10) == 0
                assert done.exists() and fx.latch.read().generation_state == "DRAINING"
                resume.set()
                with pytest.raises(live.WriterGenerationBlocked):
                    future.result(timeout=10)
        assert _mutations(fx, "create") == 0, "PR-create ran after the acknowledged drain"
        records = service.evidence_store.replay()
        assert len(records) == 1
        assert next(iter(records.values())).state.value == "provider_call_in_flight"
        owner = read_adapter_start_owner(fx.root, repository_identity=fx.identity)
        assert owner is not None and not owner.sealed
        if temporary:
            assert len(list(fx.latch.lease_dir.glob('*.json'))) == 2
        else:
            assert fx.lease.path.exists()
    finally:
        service.admission_store.generation_lease.release()


@pytest.mark.parametrize("authority", ["missing", "revoked", "draining", "unknown-nonce"])
def test_authority_refused_before_first_effect(fx, authority):
    if authority == "missing":
        fx.adapter.generation_lease = None
    elif authority == "revoked":
        fx.lease.release()
    elif authority == "draining":
        fx.latch.begin_draining()
    else:
        fx.adapter.generation_lease = live.WriterGenerationLease(fx.latch, "stale", "absent")
    with pytest.raises(live.WriterGenerationBlocked):
        fx.adapter.execute(fx.request)
    assert _mutations(fx, "push") == _mutations(fx, "create") == 0


@pytest.mark.parametrize("site", ["before-push", "before-create"])
@pytest.mark.parametrize("refusal", ["draining", "revoked"])
def test_post_entry_refusal_retains_inflight_unsealed_owner(fx, tmp_path, site, refusal):
    service = _service(fx.root, fx.adapter)
    service.evidence_store.generation_lease = fx.lease
    token = "get-url" if site == "before-push" else "log"
    expected_pushes = 0 if site == "before-push" else 1
    try:
        with _pause_at(fx, token, lambda: service.execute(fx.request)) as (future, resume):
            assert _mutations(fx, "push") == expected_pushes
            assert _lock_available(fx.latch.lock_path)
            operation = "drain" if refusal == "draining" else "release"
            with _contender(fx, tmp_path, operation) as (process, done):
                assert process.wait(timeout=10) == 0
                assert done.exists()
                if refusal == "draining":
                    assert fx.latch.read().generation_state == "DRAINING"
                else:
                    assert not fx.lease.path.exists()
                resume.set()
                with pytest.raises(live.WriterGenerationBlocked):
                    future.result(timeout=10)
        assert _mutations(fx, "push") == expected_pushes
        assert _mutations(fx, "create") == 0
        records = service.evidence_store.replay()
        assert len(records) == 1
        assert next(iter(records.values())).state.value == "provider_call_in_flight"
        owner = read_adapter_start_owner(fx.root, repository_identity=fx.identity)
        assert owner is not None and not owner.sealed
    finally:
        service.admission_store.generation_lease.release()


@pytest.mark.parametrize("effect", ["push", "create"])
def test_provider_exception_releases_lock(fx, effect):
    failure = RuntimeError("owned fake provider failure")

    def run(args, **kwargs):
        if effect in args:
            assert not _lock_available(fx.latch.lock_path)
            raise failure
        return fx.run(args, **kwargs)

    fx.adapter.run = run
    with pytest.raises(RuntimeError) as caught:
        fx.adapter.execute(fx.request)
    assert caught.value is failure
    assert _lock_available(fx.latch.lock_path)
    fx.lease.release()
    fx.latch.begin_draining()


def test_normal_fenced_publish_keeps_probes_and_readback_outside(fx):
    def run(args, **kwargs):
        mutation = "push" in args or "create" in args
        assert _lock_available(fx.latch.lock_path) is not mutation
        return fx.run(args, **kwargs)

    fx.adapter.run = run
    result, evidence = fx.adapter.execute(fx.request)
    assert evidence.terminal_state == "effect_terminal_observed"
    assert result.head_sha == fx.request.head_sha
    assert _mutations(fx, "push") == _mutations(fx, "create") == 1
    assert _mutations(fx, "ls-remote") == 1


def test_linked_worktree_resolves_the_same_held_gate(fx, tmp_path):
    linked = tmp_path / "linked"
    _git(fx.repo, "worktree", "add", "--detach", str(linked), "HEAD")
    root = live.repository_broker_namespace(linked)
    latch = live.WriterGenerationLatch.for_store_root(root)
    assert latch.lock_path == fx.latch.lock_path
    with _pause_at(fx, "push") as (future, resume):
        assert not _lock_available(latch.lock_path)
        resume.set()
        future.result(timeout=10)
    assert _lock_available(latch.lock_path)


def test_unrelated_repository_gate_remains_independent(tmp_path):
    alpha, beta = _two_partitions(tmp_path)
    latch_a = live.WriterGenerationLatch.for_store_root(alpha.root)
    latch_b = live.WriterGenerationLatch.for_store_root(beta.root)
    try:
        def effect():
            assert not _lock_available(latch_a.lock_path)
            assert _lock_available(latch_b.lock_path)
            return 19
        assert live.require_current_generation(alpha.root, alpha.store.generation_lease,
                                               effect=effect) == 19
    finally:
        alpha.store.generation_lease.release()
        beta.store.generation_lease.release()


def test_recovery_store_then_latch_order_completes_before_terminal_append(fx, tmp_path):
    service = _service(fx.root, fx.adapter)
    try:
        with _pause_at(fx, "create", lambda: service.execute(fx.request)) as (future, resume):
            assert not _lock_available(fx.latch.lock_path)
            with _contender(fx, tmp_path, "drain", store_lock=service.admission_store.lock_path) as (process, done):
                assert not _lock_available(service.admission_store.lock_path)
                assert not done.exists()
                resume.set()
                assert process.wait(timeout=10) == 0
                with pytest.raises(live.WriterGenerationBlocked):
                    future.result(timeout=10)
        assert _mutations(fx, "push") == _mutations(fx, "create") == 1
        owner = read_adapter_start_owner(fx.root, repository_identity=fx.identity)
        assert owner is not None and not owner.sealed
        assert next(iter(service.evidence_store.replay().values())).state.value == "provider_call_in_flight"
        assert _lock_available(fx.latch.lock_path)
        assert _lock_available(service.admission_store.lock_path)
    finally:
        service.admission_store.generation_lease.release()


@pytest.mark.parametrize("callback", [False, True])
def test_validation_lifetime_covers_complete_checks_only_for_callback(fx, monkeypatch, callback):
    original_validate = live.WriterGenerationLatch.validate_lease
    original_active = live._require_active_generation_root
    checkpoints = []

    def validate(latch, lease, *, strict=True):
        original_validate(latch, lease, strict=strict)
        checkpoints.append("lease")
        assert _lock_available(latch.lock_path) is not callback

    def active(root):
        original_active(root)
        checkpoints.append("active")
        assert _lock_available(fx.latch.lock_path) is not callback

    monkeypatch.setattr(live.WriterGenerationLatch, "validate_lease", validate)
    monkeypatch.setattr(live, "_require_active_generation_root", active)
    sentinel = object()

    def effect():
        checkpoints.append("effect")
        assert not _lock_available(fx.latch.lock_path)
        return sentinel

    if callback:
        assert live.require_current_generation(fx.root, fx.lease, effect=effect) is sentinel
    else:
        assert live.require_current_generation(fx.root, fx.lease) is None
    assert checkpoints == ["lease", "active"] + (["effect"] if callback else [])
    assert _lock_available(fx.latch.lock_path)


def test_callback_exception_identity_and_unwind(fx):
    failure = RuntimeError("callback failure")
    calls = []

    def effect():
        calls.append(1)
        assert not _lock_available(fx.latch.lock_path)
        raise failure

    with pytest.raises(RuntimeError) as caught:
        live.require_current_generation(fx.root, fx.lease, effect=effect)
    assert caught.value is failure and calls == [1]
    assert _lock_available(fx.latch.lock_path)


@pytest.mark.parametrize("mode", ["capability-off", "resolution-exception", "missing-latch"])
@pytest.mark.parametrize("raises", [False, True])
def test_compatibility_callback_once_without_creating_authority(tmp_path, monkeypatch, mode, raises):
    root = tmp_path / "unactivated" / "broker"
    adapter = GitHubBrokerAdapter(tmp_path / "not-a-repository")
    if mode == "capability-off":
        monkeypatch.setattr(live, "fabpub_capability_active", lambda: False)
    calls, sentinel = [], object()
    failure = RuntimeError("compatibility effect failure")

    def effect():
        calls.append(1)
        if raises:
            raise failure
        return sentinel

    def invoke(effect=None):
        if mode == "missing-latch":
            return live.require_current_generation(root, effect=effect)
        return adapter._revalidate_generation_before_effect(effect=effect)

    assert invoke() is None
    if raises:
        with pytest.raises(RuntimeError) as caught:
            invoke(effect)
        assert caught.value is failure
    else:
        assert invoke(effect) is sentinel
    assert calls == [1]
    assert not root.exists()
    assert not list(tmp_path.rglob("writer-generation.json"))
    assert not list(tmp_path.rglob("generation-leases"))


def test_authenticated_receipt_refuses_missing_latch(fx):
    assert live.load_partition_receipt(fx.root) is not None
    saved = fx.latch.path.with_suffix(".saved")
    fx.latch.path.rename(saved)
    calls = []
    try:
        with pytest.raises(live.WriterGenerationBlocked):
            live.require_current_generation(fx.root, fx.lease, effect=lambda: calls.append(1))
        assert calls == [] and not fx.latch.path.exists()
    finally:
        saved.rename(fx.latch.path)


def test_undeclared_validation_compatibility_retains_none_result(fx):
    assert live.require_current_generation(fx.root, live.UNDECLARED_LEASE) is None
    assert live.require_current_generation(fx.root, live.UNDECLARED_LEASE, effect=lambda: 23) == 23
