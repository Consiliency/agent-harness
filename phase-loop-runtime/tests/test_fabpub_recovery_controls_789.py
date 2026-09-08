"""Consiliency/agent-harness#789 Workstream C-keep — recovery controls.

Plan: ``plans/detailed-789-fabpub-pre-admission-compat-20260906.md``, Workstream
C (decided C-keep, 2026-09-06).  These are CONTROLS over behaviour this tree
already has, not RED-first falsifiers: they are GREEN here and their evidence is
mutation kill, recorded in the PR body.  They exist so the two properties the
maintainer chose to KEEP cannot be weakened silently by a later change.

**Negative control — an unknown effect stays unknown.**  A repository partition
holding an ``OUTCOME_AMBIGUOUS_BLOCKED`` evidence record refuses a fresh publish
of the exact intended branch, and the refusal is derived ONLY from local durable
evidence.  Every ``git ls-remote`` route is replaced by a raising sentinel for
the duration of the call, so a refusal path that tried to consult the remote
would surface ``_RemoteProbeAttempted`` instead of the typed
``PermissionError``.  Stated explicitly, because it decides what the control
proves: the property is asserted by the test demanding the TYPED refusal
(``PermissionError("epoch permanently blocked")``) while the probe sentinel is
armed — the sentinel raising is the FAILURE mode, never the pass mode.  This is
Consiliency/agent-harness#789 acceptance item 3, "never infer no-effect merely
from remote absence or timeout": absence of a remote branch is not evidence, and
neither is a timeout, so the runtime must not look.

**Positive control — fencing is not weakened for unrelated operations.**  Two
repository partitions activated through ONE global zero-history cutover: block
the first, publish through the second.  The second admits exactly once and
reaches the adapter exactly once; the first stays blocked and still refuses.
``BrokerEvidenceStore.epoch_blocked`` is repository-scoped by construction
(``evidence.py:86-95`` scans one store root; ``live.py:3324-3325`` — "each repo
gets its OWN admission + evidence store ... the stores are NOT shared").

**Carried, not discharged** (plan round-1 finding F3): item (5)'s FIRST half —
"a completed recovery can publish the exact intended branch once" — has no
governed path under C-keep.  The only governed recovery is partition rotation
(Workstream D), deferred to its own plan, so no test here promises it and
Consiliency/agent-harness#789 stays open.

This is a NEW file: the count-guarded FABPUB corpus in ``tests/_fabpub_tdd_guard.py``
is untouched, and every helper is IMPORTED from the sibling modules rather than
copied.
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from _fabpub_tdd_guard import (
    FABPUB_SKIP_REASON,
    fabpub_capability_active,
    fabpub_symbol,
)
from test_fabpub_admission_compat_789 import (
    _assert_refused_before_owner,
    _routed,
    _snapshot,
)
from test_fabpub_shared_epoch import (
    _CountingAdapter,
    _activate_repository_authorities,
    _authority_preimage,
    _counting_store,
    _git,
    _init_repo,
    _jsonl,
    _publish_transaction_request,
    _service,
    _stage,
)

pytestmark: list = []  # explicitly no module-level skip

_requires_fabpub = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

#: The effect key of a PRIOR transaction on the partition that ended ambiguous.
#: Deliberately not the fresh publish's dedup key: the incident's recovery
#: attempt is a NEW transaction for the SAME branch, so it must be refused by the
#: partition-wide block at ``verbs.py:533`` and not by terminal replay.
BLOCKED_KEY = "ah789-prior-ambiguous-transaction"

#: The exact evidence reference production wrote in the incident (issue step 4).
BLOCKED_REFERENCE = "unsealed-adapter-start-owner"

#: The typed refusal ``BrokerService._fresh_publish`` raises (``verbs.py:533-534``).
REFUSAL_MESSAGE = "epoch permanently blocked"

#: The storage-layer permanence raise (``evidence.py:229-230``).
PERMANENCE_MESSAGE = "outcome_ambiguous_blocked is permanent; no transition out"


class _RemoteProbeAttempted(AssertionError):
    """Raised when anything under test shells out to ``git ls-remote``."""


@contextlib.contextmanager
def _no_remote_probe(monkeypatch):
    """Replace every ``subprocess`` entry point with a remote-probe sentinel.

    Non-remote git calls (the envelope revalidation reads the worktree) pass
    straight through to the real implementation; only an argv carrying
    ``ls-remote`` trips.  Patching the ``subprocess`` module attributes covers
    the ``import subprocess`` / ``subprocess.run(...)`` form every production
    caller in this package uses (``live._git_out``, ``credsep``,
    ``train_runner``).
    """
    real = {name: getattr(subprocess, name) for name in ("run", "check_output", "Popen")}

    def _guarded(name):
        def _call(args, *rest, **kwargs):
            argv = list(args) if isinstance(args, (list, tuple)) else [args]
            if any("ls-remote" == str(token) for token in argv):
                raise _RemoteProbeAttempted(
                    "the refusal consulted the remote: "
                    f"subprocess.{name}({argv!r}) — Consiliency/agent-harness#789 item 3 "
                    "forbids inferring no-effect from remote absence or timeout"
                )
            return real[name](args, *rest, **kwargs)

        return _call

    with monkeypatch.context() as patch:
        for name in real:
            patch.setattr(subprocess, name, _guarded(name))
        yield


def _block_partition(service) -> None:
    """Drive PRODUCTION to write one permanent ambiguity into this partition.

    ``record_intent`` then ``record_terminal`` is the exact pair
    ``BrokerService._fresh_publish`` uses on its own adapter-exception path
    (``verbs.py:614-617``); the test never writes the JSONL itself.
    """
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    store = service.evidence_store
    store.record_intent(BLOCKED_KEY)
    store.record_terminal(
        EvidenceRecord(BLOCKED_KEY, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, BLOCKED_REFERENCE)
    )
    assert store.epoch_blocked is True, "production must report the partition blocked"


def _partition(tmp_path: Path, repo: Path, identity: str, root: Path, *, label: str) -> SimpleNamespace:
    """One committed transaction + a real routed service for an ACTIVE partition."""
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    assert prepare is not None
    _git(repo, "checkout", "-q", "-b", "feat/x")
    _stage(repo, "a.py", "x = 1\n")
    transaction = prepare(
        repo,
        owned_paths=("a.py",),
        checkpoint_root=tmp_path / "coordinator" / label,
        branch="feat/x",
        envelope_authority_preimage=_authority_preimage(identity, "feat/x"),
    )
    transaction.resume()
    assert transaction.committed_head_sha == transaction.expected_commit_oid
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)
    return SimpleNamespace(
        label=label,
        repo=repo,
        identity=identity,
        root=root,
        transaction=transaction,
        adapter=adapter,
        store=store,
        service=service,
        request=_publish_transaction_request(identity, "feat/x", transaction, repo),
        admissions=root / "admissions.jsonl",
        evidence=root / "evidence.jsonl",
        owner=root / "adapter-start-owner.json",
    )


def _two_partitions(tmp_path: Path) -> tuple[SimpleNamespace, SimpleNamespace]:
    """Two repository partitions activated by ONE global zero-history cutover.

    The multi-repository fixture shape of
    ``test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation``
    (``test_fabpub_shared_epoch.py:2700-2717``): one manifest, several rows, one
    ``ACTIVE`` transaction, a disjoint receipt per repository.  The conftest's
    autouse ``_isolate_host_state`` pins ``PHASE_LOOP_FABPUB_AUTHORITY_ROOT`` into
    ``tmp_path``, so both partitions are governed by one authority root here.
    """
    alpha_repo = _init_repo(tmp_path / "alpha")
    beta_repo = _init_repo(tmp_path / "beta")
    activated = _activate_repository_authorities(
        tmp_path, ((alpha_repo, "alpha"), (beta_repo, "beta"))
    )
    alpha = _partition(tmp_path, alpha_repo, *activated[alpha_repo], label="alpha")
    beta = _partition(tmp_path, beta_repo, *activated[beta_repo], label="beta")
    assert alpha.root != beta.root, "two repositories must hold two disjoint partitions"
    assert alpha.identity != beta.identity
    return alpha, beta


# ---------------------------------------------------------------------------
# Negative control — an unknown effect stays unknown
# ---------------------------------------------------------------------------


@_requires_fabpub
def test_blocked_partition_refuses_fresh_publish_without_consulting_the_remote(tmp_path, monkeypatch):
    """A permanently blocked partition refuses locally: no remote read, nothing moves.

    The typed ``PermissionError`` is the pass condition WHILE the ls-remote
    sentinel is armed; a refusal that probed the remote would raise
    ``_RemoteProbeAttempted`` (an ``AssertionError``, not a ``PermissionError``)
    and fail the ``pytest.raises`` block instead.
    """
    fx = _routed(tmp_path, name="recovery-blocked")
    _block_partition(fx.service)

    # The fresh publish targets the EXACT intended branch of the fixture
    # transaction (``feat/x``) under a different, live effect key.
    assert fx.service._dedup_key(fx.request) != BLOCKED_KEY

    before = _snapshot(fx)
    assert before["evidence"] is not None, "the blocked record must be durable before the attempt"

    with _no_remote_probe(monkeypatch):
        with pytest.raises(PermissionError) as info:
            fx.service.execute(fx.request)

    assert REFUSAL_MESSAGE in str(info.value), (
        f"the refusal must stay the typed permanent-block refusal; got: {info.value!r}"
    )
    # Nothing durable moved and the adapter was never entered: no owner file, no
    # admission, byte-identical evidence, transaction still COMMITTED_HEAD_RESOLVED.
    _assert_refused_before_owner(fx, before)
    assert fx.store.admit_next_calls == 0, "a blocked partition allocates no epoch"
    assert _jsonl(fx.admissions) == [], "a blocked partition writes no admission"

    # The blocked record itself is unchanged, and the storage layer refuses any
    # transition out of it (``evidence.py:229-230``) — the ONLY caller path that
    # reaches that raise is ``rejected_before_start``, which skips transition
    # validation and appends directly.
    with pytest.raises(ValueError) as permanence:
        fx.service.evidence_store.rejected_before_start(BLOCKED_KEY, "operator-retry")
    assert PERMANENCE_MESSAGE in str(permanence.value)
    assert fx.evidence.read_bytes() == before["evidence"], "evidence.jsonl must be byte-identical"

    # A second attempt behaves identically: the block is permanent, not one-shot.
    with _no_remote_probe(monkeypatch):
        with pytest.raises(PermissionError) as again:
            fx.service.execute(fx.request)
    assert REFUSAL_MESSAGE in str(again.value)
    _assert_refused_before_owner(fx, before)


# ---------------------------------------------------------------------------
# Positive control — unrelated operations keep their fencing
# ---------------------------------------------------------------------------


@_requires_fabpub
def test_blocked_partition_does_not_fence_an_unrelated_repository_partition(tmp_path, monkeypatch):
    """Blocking one repository partition leaves the other publishable, exactly once."""
    alpha, beta = _two_partitions(tmp_path)
    _block_partition(alpha.service)

    assert alpha.service.evidence_store.epoch_blocked is True
    assert beta.service.evidence_store.epoch_blocked is False, (
        "epoch_blocked is repository-scoped: one partition's permanent ambiguity "
        "must not fence another repository's partition"
    )

    outcome = beta.service.execute(beta.request)

    assert outcome.accepted, "the unrelated partition must still publish"
    assert len(beta.adapter.calls) == 1, "exactly one provider effect"
    assert beta.store.admit_next_calls == 1, "exactly one admission allocation"
    assert len(_jsonl(beta.admissions)) == 1, "exactly one durable admission record"
    assert beta.owner.exists(), "the unrelated publish took the real owner seam"

    # Alpha is untouched by beta's success and still refuses.
    assert alpha.service.evidence_store.epoch_blocked is True
    assert _jsonl(alpha.admissions) == []
    assert not alpha.owner.exists()
    with _no_remote_probe(monkeypatch):
        with pytest.raises(PermissionError) as info:
            alpha.service.execute(alpha.request)
    assert REFUSAL_MESSAGE in str(info.value)
    assert alpha.adapter.calls == []
    assert _jsonl(alpha.admissions) == []

    # Beta stays at exactly one effect after alpha's refusal.
    assert len(beta.adapter.calls) == 1
    assert len(_jsonl(beta.admissions)) == 1
