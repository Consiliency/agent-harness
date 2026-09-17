"""agent-harness#655: the readmission authority digest is an unambiguous, versioned encoding.

The v1 digest joined `owned_scope` with commas, so `("a.py", "b.py")` and `("a.py,b.py",)` hashed
identically, and `LinearizableAdmissionStore.admit_next` deduplicates on digest equality before the
scope re-diff. A grant could therefore be reused for an authority with a different scope. The v2
digest hashes a domain-separated canonical JSON encoding of the same bound fields. A replay whose
stored grant binding carries the authority's legacy v1 digest is refused explicitly, before
deduplication and the branch-history, scope and diff predicates.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace

import pytest

from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority

from _fabreadmit_tdd_guard import FABREADMIT_SKIP_REASON, fabreadmit_capability_active

BOUND_FIELDS = (
    "repository",
    "branch",
    "prior_head_sha",
    "proposed_head_sha",
    "train_id",
    "node_id",
    "fab_run_id",
    "roadmap_digest",
    "provenance_digest",
)


# Known-answer vectors for `_authority()`: the v2 digest, the legacy v1 digest, and the attempt identity.
# These are SHA-256 outputs of public test inputs, not credentials.
KNOWN_ANSWERS = (
    "5d9c8a8a4a725ee5611c4b810ce508c0dbdaece20152bf51d1ba6aadc6842b1c",
    "b5c612dde54ca0171af9761d364d70109bef8c55a1c5307f3541aabb88d923c9",
    "cf49cbf4b2836e18f4f7d4ba14c4c76663eb568fa0528d739a3f622e68ec1435",
)

def _authority(**overrides) -> DeltaReadmitAuthority:
    fields = dict(
        repository="github.com/example/repo",
        adapter_worktree="/work/tree",
        checkpoint_root="/work/ckpt",
        branch="feat/x",
        base="main",
        prior_head_sha="1" * 40,
        proposed_head_sha="2" * 40,
        train_id="train-1",
        node_id="node-1",
        fab_run_id="run-1",
        roadmap_digest="r" * 64,
        provenance_digest="p" * 64,
        owned_scope=("a.py", "b.py"),
    )
    fields.update(overrides)
    return DeltaReadmitAuthority(**fields)


def _v1_digest(auth: DeltaReadmitAuthority) -> str:
    payload = (
        f"{auth.repository}\0{auth.branch}\0{auth.prior_head_sha}\0"
        f"{auth.proposed_head_sha}\0{auth.train_id}\0{auth.node_id}\0"
        f"{auth.fab_run_id}\0{auth.roadmap_digest}\0{auth.provenance_digest}\0"
        f"{','.join(auth.owned_scope)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_comma_joined_scopes_no_longer_collide():
    split = _authority(owned_scope=("a.py", "b.py"))
    joined = _authority(owned_scope=("a.py,b.py",))
    assert _v1_digest(split) == _v1_digest(joined)  # the v1 collision this issue records
    assert split.authority_digest != joined.authority_digest


def test_nul_in_a_field_cannot_shift_a_field_boundary():
    left = _authority(repository="repo\0feat", branch="x")
    right = _authority(repository="repo", branch="feat\0x")
    assert _v1_digest(left) == _v1_digest(right)
    assert left.authority_digest != right.authority_digest


def test_digest_is_domain_separated_from_v1_and_deterministic():
    auth = _authority()
    assert auth.authority_digest != _v1_digest(auth)
    assert auth.authority_digest == _authority().authority_digest
    assert len(auth.authority_digest) == 64 and int(auth.authority_digest, 16) >= 0


def test_every_bound_field_changes_the_digest_and_unbound_fields_do_not():
    base = _authority()
    for name in BOUND_FIELDS:
        changed = replace(base, **{name: getattr(base, name) + "x"})
        assert changed.authority_digest != base.authority_digest, name
    assert replace(base, owned_scope=("a.py",)).authority_digest != base.authority_digest
    assert replace(base, owned_scope=("b.py", "a.py")).authority_digest != base.authority_digest
    # The field set is unchanged from v1: worktree, checkpoint root and base stay outside the digest.
    for name, value in (("adapter_worktree", "/other"), ("checkpoint_root", "/other"), ("base", "develop")):
        assert replace(base, **{name: value}).authority_digest == base.authority_digest, name


def test_known_answer_vectors():
    auth = _authority()
    preimage = json.dumps(
        {name: getattr(auth, name) for name in BOUND_FIELDS} | {"owned_scope": list(auth.owned_scope)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    independent = hashlib.sha256(b"FABREADMIT-AUTHORITY-DIGEST-v2\0" + preimage.encode("utf-8")).hexdigest()
    assert auth.authority_digest == independent == KNOWN_ANSWERS[0]
    assert auth.legacy_v1_authority_digest == _v1_digest(auth) == KNOWN_ANSWERS[1]
    assert auth.attempt_identity == KNOWN_ANSWERS[2]


def test_attempt_identity_follows_the_v2_digest():
    split = _authority(owned_scope=("a.py", "b.py"))
    joined = _authority(owned_scope=("a.py,b.py",))
    assert split.attempt_identity != joined.attempt_identity
    expected = hashlib.sha256(b"FABREADMIT-READMISSION-ATTEMPT-v1\0" + bytes.fromhex(split.authority_digest)).hexdigest()
    assert split.attempt_identity == expected


def _readmit_fixture(tmp_path, name, owned_paths):
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from test_fabpub_shared_epoch import (
        _CountingAdapter,
        _activate_repository_authority,
        _authority_preimage,
        _git,
        _init_repo,
        _publish_transaction_request,
        _service,
        _stage,
        fabpub_symbol,
    )

    # The shared fixture's transaction owns only `a.py`. A comma collision needs a multi-path scope,
    # so prepare one exact multi-path transaction through the same activated-authority helpers.
    repo_dir = _init_repo(tmp_path / name)
    identity, store_root = _activate_repository_authority(tmp_path, repo_dir, label=name)
    _git(repo_dir, "checkout", "-q", "-b", "feat/x")
    for path in owned_paths:
        _stage(repo_dir, path, f"{path.replace('.', '_')} = 1\n")
    transaction = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")(
        repo_dir,
        owned_paths=tuple(owned_paths),
        checkpoint_root=tmp_path / "coordinator" / name,
        branch="feat/x",
        envelope_authority_preimage=_authority_preimage(identity, "feat/x"),
    )
    transaction.resume()
    assert transaction.committed_head_sha == transaction.expected_commit_oid
    store = LinearizableAdmissionStore(store_root, lambda _: True)
    svc = _service(store_root, _CountingAdapter(), store=store)
    branch = "feat/x"
    request = _publish_transaction_request(identity, branch, transaction, repo_dir)
    assert svc.execute(request).accepted
    envelope = request.admission
    ckpt = transaction.checkpoint_root
    (ckpt / "train.json").write_text(
        json.dumps({"train_id": envelope.train_id, "repository": identity}), encoding="utf-8"
    )
    (ckpt / f"{envelope.node_id}.json").write_text(json.dumps({"node_id": envelope.node_id}), encoding="utf-8")
    (repo_dir / "a.py").write_text("v2 advance\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "advance"], check=True)
    proposed = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    def authority(owned_scope):
        return DeltaReadmitAuthority(
            repository=identity,
            adapter_worktree=str(repo_dir),
            checkpoint_root=str(ckpt),
            branch=branch,
            base="main",
            prior_head_sha=transaction.committed_head_sha,
            proposed_head_sha=proposed,
            train_id=envelope.train_id,
            node_id=envelope.node_id,
            fab_run_id="run1",
            roadmap_digest=envelope.roadmap_digest,
            provenance_digest="p" * 64,
            owned_scope=owned_scope,
        )

    return store, authority


def test_dedup_does_not_reuse_a_grant_for_a_comma_joined_scope(tmp_path):
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)
    store, authority = _readmit_fixture(tmp_path, "digest-v2-collision", ("a.py", "b.py"))
    granted = store.admit_next(authority(("a.py", "b.py")))
    count = len(store.replay())

    # Positive control: the identical authority still deduplicates to the same grant.
    assert store.admit_next(authority(("a.py", "b.py"))) == granted
    assert len(store.replay()) == count

    # The comma-joined scope is a different authority. Before v2 it deduplicated onto `granted`
    # (returned it, no error). Now it takes the full admission path, which refuses it and writes nothing.
    with pytest.raises(PermissionError):
        store.admit_next(authority(("a.py,b.py",)))
    assert len(store.replay()) == count


def _rewrite_grant_as_v1(store, auth):
    """Rewrite the durable grant exactly as a pre-v2 host stored it: v1 digest AND the attempt identity derived from it."""
    v1 = _v1_digest(auth)
    v1_attempt = hashlib.sha256(b"FABREADMIT-READMISSION-ATTEMPT-v1\0" + bytes.fromhex(v1)).hexdigest()
    text = store.path.read_text(encoding="utf-8")
    assert auth.authority_digest in text and auth.attempt_identity in text
    rewritten = text.replace(auth.authority_digest, v1).replace(auth.attempt_identity, v1_attempt)
    store.path.write_text(rewritten, encoding="utf-8")
    stored = [r for r in store.replay() if r.binding is not None]
    assert stored[-1].binding.authority_digest == v1
    return rewritten


def test_a_replay_of_a_v1_grant_is_refused_and_writes_nothing(tmp_path):
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)
    store, authority = _readmit_fixture(tmp_path, "digest-v2-migration", ("a.py",))
    auth = authority(("a.py",))
    store.admit_next(auth)
    before = _rewrite_grant_as_v1(store, auth)

    with pytest.raises(PermissionError, match=r"legacy v1 authority digest"):
        store.admit_next(auth)
    assert store.path.read_text(encoding="utf-8") == before


def test_a_v1_grant_behind_later_history_is_still_refused(tmp_path):
    """Codex round 1 on agent-harness#885: v1 grant A->B, then B->A, then replay A->B.

    The replay's prior head A is the branch's latest head again, so the history predicates alone would
    issue a FRESH grant. The legacy check must scan every stored grant, not just the latest record.
    """
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)
    store, authority = _readmit_fixture(tmp_path, "digest-v2-history", ("a.py",))
    forward = authority(("a.py",))  # A -> B
    store.admit_next(forward)
    _rewrite_grant_as_v1(store, forward)

    back = replace(forward, prior_head_sha=forward.proposed_head_sha, proposed_head_sha=forward.prior_head_sha)
    back_grant = store.admit_next(back)  # B -> A under v2; not refused: its v1 digest matches no stored grant
    assert back_grant.binding is not None and back_grant.binding.authority_digest == back.authority_digest
    before = store.path.read_text(encoding="utf-8")

    with pytest.raises(PermissionError, match=r"legacy v1 authority digest"):
        store.admit_next(forward)
    assert store.path.read_text(encoding="utf-8") == before


def test_an_unrelated_authority_is_not_refused_by_the_legacy_check(tmp_path):
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)
    store, authority = _readmit_fixture(tmp_path, "digest-v2-unrelated", ("a.py", "b.py"))
    split = authority(("a.py", "b.py"))
    granted = store.admit_next(split)
    # A v2-era store holds no v1 digests: the identical authority still deduplicates to its own grant.
    assert store.admit_next(split) == granted
