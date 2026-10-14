"""Consiliency/agent-harness#1315: a routing client built before a partition rotation.

``build_routing_broker_client()`` returns, under FABPUB, a
``_RepositoryRoutingBrokerService`` that caches one admission + evidence store
pair per repository and the ``WriterGenerationLease`` they write under.  A
partition rotation (``rotate_blocked_partition``) seals generation N and makes
N+1 ACTIVE.  This module pins what an SDK caller that built its client BEFORE
the rotation meets, through the public constructor and ``execute``:

* while the client still holds its cached lease, the rotation's drain counts
  it and the rotation refuses typed (``PartitionRotationRefused``), keeping the
  latch nonce, so the client keeps working on generation N
  (docs/fabpub-partition-rotation-runbook.md §1(c));
* if the lease file was removed anyway (the runbook §6 deviation) and the
  rotation completed, the stale client refuses typed
  (``WriterGenerationBlocked``) before any write, leaves the retired and the
  successor generation byte-identical, never reaches the provider, and does not
  block a freshly built client from publishing on the successor.

The contract is refusal, not transparent rebind: the client cannot tell an
orphaned lease from a live one, and the rotation handoff tells operators to
restart broker processes.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
from pathlib import Path

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_partition_rotation_789d import (
    GENERATIONS_DIR,
    ROTATED_KEY,
    _block_key,
    _bootstrap,
    _fresh_request,
    _latch_bytes,
    _live,
    _release_all,
    _rotate,
)
from test_fabpub_shared_epoch import _CountingAdapter, _git, _supported_contracts

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)


def _tree(root: Path) -> dict[str, tuple[str, int]]:
    """Every file of ONE generation: sha256 and mtime_ns, keyed by relative path.

    Generation 0 is the container itself, so the successors under its
    ``generations/`` directory are excluded from its tree.
    """
    out = {}
    for path in sorted(root.rglob("*")):
        if GENERATIONS_DIR in path.relative_to(root).parts:
            continue
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            out[str(path.relative_to(root))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.st_mtime_ns,
            )
    return out


def _client(adapter):
    """The PUBLIC constructor, with the provider seam swapped for a counter."""
    live = _live()
    client = live.build_routing_broker_client(admission_policy=lambda _request: True)
    assert isinstance(client, live._RepositoryRoutingBrokerService)
    client._contracts = _supported_contracts("publish_committed_branch")
    real = client._service_for

    def _service_for(request_or_worktree):
        service = real(request_or_worktree)
        service.adapter = adapter
        return service

    client._service_for = _service_for
    return client


@contextlib.contextmanager
def _short_drain(monkeypatch):
    """The ceremony's drain waits 60s for leases; a held lease is the point here."""
    live = _live()
    real = live.WriterGenerationLatch.await_quiescent

    def _await(self, *, worktree, timeout=60.0):
        return real(self, worktree=worktree, timeout=0.2)

    monkeypatch.setattr(live.WriterGenerationLatch, "await_quiescent", _await)
    yield


def _published_client(tmp_path, monkeypatch):
    """A client that published once (so its stores and lease are cached), then a block."""
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    adapter = _CountingAdapter()
    client = _client(adapter)
    landed = client.execute(p.request)
    assert landed.accepted is True, landed.reason
    assert len(adapter.calls) == 1
    assert p.identity in client._leases and p.identity in client._stores
    # The partition becomes ambiguity-blocked, which is what a rotation exists for.
    _block_key(p, ROTATED_KEY)
    _release_all(p)
    return fx, p, client, adapter


def test_held_client_lease_refuses_the_rotation_typed_and_keeps_the_client_working(tmp_path, monkeypatch):
    live = _live()
    fx, p, client, adapter = _published_client(tmp_path, monkeypatch)
    try:
        lease = client._leases[p.identity]
        latch = live.WriterGenerationLatch.for_store_root(p.container)
        assert lease.path in latch.held_leases()
        latch_before = _latch_bytes(p)
        gen0 = _tree(p.container)

        with _short_drain(monkeypatch), pytest.raises(live.PartitionRotationRefused, match="did not drain"):
            _rotate(None, p, release=False)

        # Refused: no successor, the latch is ACTIVE on the SAME nonce, generation 0 untouched.
        assert not (p.container / GENERATIONS_DIR).exists()
        assert _latch_bytes(p) == latch_before
        assert latch.read().generation_state == "ACTIVE"
        assert _tree(p.container) == gen0
        # The client was not wedged by the refused ceremony: its lease still validates
        # and it replays its landed publish without reaching the provider again.
        latch.validate_lease(lease)
        replay = client.execute(p.request)
        assert replay.accepted is True
        assert len(adapter.calls) == 1
    finally:
        client.close()


def test_stale_client_after_rotation_refuses_typed_without_writing(tmp_path, monkeypatch):
    live = _live()
    fx, p, client, adapter = _published_client(tmp_path, monkeypatch)
    lease = client._leases[p.identity]
    # Runbook §6 deviation: the lease file is removed while its holder survives.
    lease.path.unlink()
    outcome = _rotate(None, p, release=False)
    assert outcome.state == "ACTIVE" and outcome.generation == 1
    assert live.repository_snapshot(p.repo).store_root == outcome.store_root

    fresh = _fresh_request(p, "after-rotation")
    namespace = live.WriterGenerationLatch.for_store_root(p.container).root
    gen0 = _tree(p.container)
    gen1 = _tree(outcome.store_root)
    latch_before = _latch_bytes(p)
    try:
        # A fresh head, the head the client already published (which main served
        # as a replay out of the retired ledger), and the same repository reached
        # through a linked worktree the client has no cached service for.
        linked = tmp_path / "linked-alpha"
        _git(p.repo, "worktree", "add", "-q", "--detach", str(linked))
        via_linked = dataclasses.replace(fresh, adapter_worktree=str(linked))
        gen0 = _tree(p.container)
        for request in (fresh, p.request, via_linked):
            with pytest.raises(live.WriterGenerationBlocked, match="retired partition generation"):
                client.execute(request)
        assert len(adapter.calls) == 1, "the stale client reached the provider"
        assert _tree(p.container) == gen0, "the stale client wrote to the retired generation"
        assert _tree(outcome.store_root) == gen1, "the stale client wrote to the successor"
        assert _latch_bytes(p) == latch_before
        assert not list((namespace / "generation-leases").glob("*.json"))
    finally:
        client.close()

    # The stale client neither blocked nor mutated the successor: a client built
    # after the rotation publishes there.
    adapter2 = _CountingAdapter()
    after = _client(adapter2)
    try:
        published = after.execute(fresh)
        assert published.accepted is True, published.reason
        assert len(adapter2.calls) == 1
    finally:
        after.close()
    assert _tree(p.container) == gen0
