"""FABPUB (v10) falsifiers — shared repository epoch allocator + publish identity.

SL-0 tests-only boundary.  Every production-dependent falsifier here:

* is skipped while the FABPUB capability is inactive (per-test ``skipif`` only —
  no module-level skip, no ``xfail``);
* probes new symbols lazily via :func:`_fabpub_tdd_guard.fabpub_symbol` so an
  activated run fails with an ``AssertionError`` carrying its unique frozen RED
  anchor rather than an ``ImportError`` at collection time;
* asserts its live source anchor BEFORE the fixture work, so the activated RED
  run is deterministic and cheap against production-identical ``main``.

**Non-vacuity rule (Consiliency/agent-harness#578 F1).**  Past the anchor gate,
every assertion is about a value PRODUCTION produced — a record the production
code appended to disk, a counter a spy wired into a production seam
incremented, a ref a production CAS moved, or the stdout of a real CLI
subprocess.  A test never asserts a list it filled in itself, and never asserts
mere symbol/attribute presence as if that were the behaviour.  Each falsifier
also carries a positive control that a "define the symbol and always block"
stub cannot satisfy.

Guard-control tests (``test_fabpub_guard_*``) never skip and are GREEN in every
mode: they hold the inline canonical vectors, the recomputed vector digests, and
the nodeid-inventory arithmetic honest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

import phase_loop_runtime.fabpub_tdd_chronology as fabpub_chronology
from phase_loop_runtime.fabpub_tdd_chronology import (
    audit_digest_bound_artifact,
    audit_plan_manifest_binding,
)

from _fabpub_tdd_guard import (
    FABPUB_ACTIVATION_ENV,
    FABPUB_ADAPTER_START_FENCE_NODEIDS,
    FABPUB_ADAPTER_START_FENCE_NODEIDS_SHA256,
    FABPUB_BASELINE_INVENTORY_AVAILABLE,
    FABPUB_COMMIT_OBJECT_VECTOR_SHA256,
    FABPUB_DEFAULT_SKIP_COUNT,
    FABPUB_EXPECTED_NODEIDS,
    FABPUB_FROZEN_SUBINVENTORY_CONTRIBUTIONS,
    FABPUB_FROZEN_SUBINVENTORY_TOTAL,
    FABPUB_IDENTITY_NODEIDS,
    FABPUB_IDENTITY_NODEIDS_SHA256,
    FABPUB_IDENTITY_VECTOR_SHA256,
    FABPUB_LEGACY_CUTOVER_NODEIDS,
    FABPUB_LEGACY_CUTOVER_NODEIDS_SHA256,
    FABPUB_LEGACY_CUTOVER_VECTOR_SHA256,
    FABPUB_MARKER_MODULE,
    FABPUB_MIGRATED_NODEIDS,
    FABPUB_NEW_PRODUCTION_NODEIDS,
    FABPUB_OWNED_PATHS,
    FABPUB_OWNED_PATHS_SHA256,
    FABPUB_RED_ANCHORS,
    FABPUB_RED_NODEIDS,
    FABPUB_REPOSITORY_IDENTITY_VECTOR_SHA256,
    FABPUB_RUN_TRAIN_RECOVERY_NODEIDS,
    FABPUB_SHARED_ALLOCATOR_NODEIDS,
    FABPUB_SHARED_ALLOCATOR_NODEIDS_SHA256,
    FABPUB_SKIP_REASON,
    FABPUB_SUPERSEDED_BASELINE_INVENTORY_SHA256,
    FABPUB_TEST_PATHS,
    FABPUB_TEST_PATHS_SHA256,
    FABPUB_WRITER_GENERATION_FENCE_NODEIDS,
    FABPUB_WRITER_GENERATION_FENCE_NODEIDS_SHA256,
    fabpub_capability_active,
    fabpub_inventory_digest,
    fabpub_marker_version,
    fabpub_require,
    fabpub_symbol,
    fabpub_this_nodeid,
)

pytestmark: list = []  # explicitly no module-level skip

_ACTIVE = fabpub_capability_active()
_requires_fabpub = pytest.mark.skipif(not _ACTIVE, reason=FABPUB_SKIP_REASON)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SRC = REPO_ROOT / "phase-loop-runtime" / "src"

# Domain separators frozen by IF-0-FABPUB-1.
TRANSACTION_DOMAIN = b"FABPUB-PUBLISH-TRANSACTION-v1\0"
REPOSITORY_DOMAIN = b"FABPUB-CANONICAL-REPOSITORY-IDENTITY-v1\0"
TRAILER_PREFIX = b"\n\nFABPUB-Intent-ID: "

#: The exact typed blocker every stale-generation entry must return.
GENERATION_BLOCKER = "legacy_writer_after_fabpub_activation"
#: The exact typed blocker every legacy-cutover integrity failure must return.
CUTOVER_BLOCKER = "legacy_cutover_conflict"


def canonical_bytes(payload: dict) -> bytes:
    """The one canonical serialization used by every FABPUB identity preimage."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def vector_digest(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


# ---------------------------------------------------------------------------
# Inline canonical vectors (frozen; their digests live in the guard)
# ---------------------------------------------------------------------------

#: ``CanonicalRepositoryIdentity.v1`` — the versioned explicit field set whose
#: domain-separated SHA-256 is the sole storage/keying ``BrokerRequest.repo``.
#: Neither the train path nor the worktree top-level is a member.
FABPUB_REPOSITORY_IDENTITY_VECTOR = {
    "schema": "CanonicalRepositoryIdentity.v1",
    "git_common_dir": "/srv/repos/agent-harness/.git",
    "git_object_format": "sha1",
}

#: Explicit caller inputs whose canonical bytes bind the envelope authority.
#: Production must derive their digest rather than trusting an opaque hash.
FABPUB_ENVELOPE_AUTHORITY_PREIMAGE = {
    "schema": "PublishEnvelopeAuthorityPreimage.v1",
    "train_id": "fabpub-train",
    "node_id": "repo-a",
    "action": "publish_committed_branch",
    "roadmap_digest": "8" * 64,
    "effective_code_digest": "9" * 64,
    "dependency_digest": "a" * 64,
    "verification_plan_digest": "b" * 64,
    "expected_version_predicate": "head == expected_commit_oid",
    "authority_domain_scope": (
        "repository:0f2b9f31d1de1b3f0a6c5e4d3c2b1a0918273645546372819a0b1c2d3e4f5061"
    ),
    "operation_identity": "publish:feat/fabpub-shared-epoch",
}

#: ``PublishPreTrailerIntent.v1`` — the exact immutable pre-trailer allowlist.
#: It contains NO ``transaction_id``, trailer, final-message, expected-head,
#: committed-head, or commit-object field.
FABPUB_IDENTITY_VECTOR = {
    "schema": "PublishPreTrailerIntent.v1",
    "canonical_repository_identity": (
        "0f2b9f31d1de1b3f0a6c5e4d3c2b1a0918273645546372819a0b1c2d3e4f5061"
    ),
    "branch": "feat/fabpub-shared-epoch",
    "base": "main",
    "base_tip_sha": "1111111111111111111111111111111111111111",
    "mode": "normal",
    "parent_head_sha": "2222222222222222222222222222222222222222",
    "staged_tree_oid": "3333333333333333333333333333333333333333",
    "owned_paths": ["phase-loop-runtime/src/phase_loop_runtime/publishing.py", "CHANGELOG.md"],
    "staged_diff_sha256": (
        "4444444444444444444444444444444444444444444444444444444444444444"
    ),
    # Derived below from FABPUB_IDENTITY_ORIGINAL_MESSAGE — never an opaque
    # caller-supplied constant (Consiliency/agent-harness#578 round 3, item 2).
    "original_commit_message_length": None,
    "original_commit_message_sha256": None,
    "draft": True,
    "pr_body_sha256": (
        "6666666666666666666666666666666666666666666666666666666666666666"
    ),
    # Expected output independently derived from the explicit caller preimage above.
    "envelope_authority_preimage_sha256": (
        "cd9348811cd61b31532d8c7d9bdf2b6ce1722df50459393cf339b668afaed5ec"
    ),
}

#: The exact original caller message bytes the identity vector's digests describe.
FABPUB_IDENTITY_ORIGINAL_MESSAGE = b"feat(FABPUB): shared repository epoch allocator"

# The message-derived members of the pre-trailer allowlist are computed HERE from
# the literal bytes above, so the vector can never declare a length or digest that
# disagrees with the message it describes.  Everything else in the vector is a
# genuine opaque input (a tree OID, a staged-diff digest), which is why only these
# two are derived.
FABPUB_IDENTITY_VECTOR["original_commit_message_length"] = len(FABPUB_IDENTITY_ORIGINAL_MESSAGE)
FABPUB_IDENTITY_VECTOR["original_commit_message_sha256"] = hashlib.sha256(
    FABPUB_IDENTITY_ORIGINAL_MESSAGE
).hexdigest()


def fabpub_identity_inputs(**overrides) -> dict:
    """Caller inputs for the expected vector, including the authority preimage."""
    payload = dict(FABPUB_IDENTITY_VECTOR)
    payload.pop("envelope_authority_preimage_sha256")
    payload["envelope_authority_preimage"] = dict(FABPUB_ENVELOPE_AUTHORITY_PREIMAGE)
    payload.update(overrides)
    return payload

#: ``CommitConstructionInputs.v1`` — every pre-construction byte that can affect
#: the commit object.  Frozen at ``PREPARED``, before the object is constructed.
FABPUB_COMMIT_OBJECT_VECTOR = {
    "schema": "CommitConstructionInputs.v1",
    "parent_head_sha": "2222222222222222222222222222222222222222",
    "tree_oid": "3333333333333333333333333333333333333333",
    "git_object_format": "sha1",
    "author_name": "Phase Loop",
    "author_email": "phase-loop@example.invalid",
    "author_date": "@1750000000 +0000",
    "committer_name": "Phase Loop",
    "committer_email": "phase-loop@example.invalid",
    "committer_date": "@1750000000 +0000",
    "encoding_header": None,
    "extra_headers": [],
    "signing_mode": "disabled",
    "signing_key": None,
    "signing_format": None,
    "signer_input_policy": "none",
    "constructor_argv": ["git", "commit-tree"],
    "constructor_config": ["core.abbrev=40", "commit.gpgsign=false"],
    "constructor_environment": ["GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"],
}

#: ``LegacyBrokerCutoverManifest.v2`` — metadata-only rows.  ``train_key`` is not
#: frozen (it hashes a runtime-resolved absolute path); ``repo_key`` IS frozen
#: because it hashes the exact historical serialized repository bytes.
FABPUB_LEGACY_CUTOVER_VECTOR = {
    "schema": "LegacyBrokerCutoverManifest.v2",
    "cutover_id": "fabpub-cutover-0001",
    "journal_states": [
        "DRAINING",
        "INVENTORY_SEALED",
        "SNAPSHOTS_VERIFIED",
        "SOURCES_RETIRED",
        "PARTITIONS_WRITTEN",
        "ARMED",
        "ACTIVE",
    ],
    "generation_states": ["LEGACY_OPEN", "DRAINING", "ACTIVE"],
    "rows": [
        {
            "serialized_repository": "/srv/repos/alpha",
            "invocation_working_directory": "/srv/repos",
            "resolution_mode": "absolute",
            "expected_canonical_repository": "alpha",
        },
        {
            "serialized_repository": "alpha",
            "invocation_working_directory": "/srv/repos",
            "resolution_mode": "workspace_argument_relative",
            "expected_canonical_repository": "alpha",
        },
        {
            "serialized_repository": "/srv/repos/beta",
            "invocation_working_directory": "/srv/repos",
            "resolution_mode": "absolute",
            "expected_canonical_repository": "beta",
        },
    ],
    "blocking_classes": [
        "legacy_cutover_conflict",
        "legacy_writer_after_fabpub_activation",
    ],
}


# ---------------------------------------------------------------------------
# Real-git helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _git_env(repo: Path, env_vars: dict, *args: str) -> str:
    env = dict(os.environ)
    env.update(env_vars)
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60, env=env
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, timeout=60)
    _git(path, "config", "user.email", "fabpub@example.invalid")
    _git(path, "config", "user.name", "FABPUB Test")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "seed.txt")
    _git(path, "commit", "-q", "-m", "seed")
    return path


def _make_cli_publishable(repo: Path, branch: str) -> None:
    """Give a real CLI probe a reachable origin and an unprotected branch."""
    origin = repo.parent / f"{repo.name}-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, timeout=60)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    _git(repo, "checkout", "-q", "-b", branch)


def _git_common_dir(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()


def _stage(repo: Path, relative: str, content: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", relative)


# ---------------------------------------------------------------------------
# Production seams / spies
# ---------------------------------------------------------------------------


def _supported_contracts(*verbs: str):
    """A test-local SUPPORTED matrix; the global one stays HUMAN_EXECUTED."""
    from phase_loop_runtime.convergence.provider_contracts import (
        ProviderAutomationDisposition,
        ProviderCompletionClassification,
        ProviderCompletionContract,
    )

    return tuple(
        ProviderCompletionContract(
            verb=verb,
            provider="github",
            classification=ProviderCompletionClassification.SUPPORTED,
            disposition=ProviderAutomationDisposition.AUTOMATED,
            status_endpoint="gh pr list",
            idempotency_key_supported="yes",
            terminal_success_evidence="remote head matches pushed sha",
            terminal_no_effect_evidence="no remote ref",
            non_late_commit_guarantee="fenced",
            guaranteed_processing_horizon="synchronous",
            expected_version_predicate="head == sha",
            revocation_affects_accepted="no",
            stabilization_drain_interval="0",
        )
        for verb in verbs
    )


class _CountingAdapter:
    """Records every provider effect the BROKER actually reached."""

    def __init__(self, *, explode: bool = False) -> None:
        self.calls: list = []
        self._explode = explode

    def execute(self, request):
        from phase_loop_runtime.convergence.contracts import (
            BrokerTerminalEvidence,
            PublishCommittedBranchResult,
        )

        self.calls.append(request)
        if self._explode:
            raise RuntimeError("provider effect interrupted")
        key = getattr(request.admission, "idempotency_key", None) or getattr(
            request.admission, "transaction_id", ""
        )
        return (
            PublishCommittedBranchResult(request.branch, request.head_sha, f"https://gh/pr/{len(self.calls)}"),
            BrokerTerminalEvidence(key, "effect_terminal_observed", "github-observed"),
        )


def _counting_store(root: Path, policy=None):
    """A real ``LinearizableAdmissionStore`` that counts BOTH admission methods."""
    store_cls = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.admission", "LinearizableAdmissionStore"
    )
    assert store_cls is not None

    class _Counting(store_cls):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.admit_calls = 0
            self.admit_next_calls = 0
            self.allocated_epochs: list = []

        def admit(self, request):
            self.admit_calls += 1
            return super().admit(request)

        def admit_next(self, make_request, **kwargs):
            self.admit_next_calls += 1
            record = super().admit_next(make_request, **kwargs)
            self.allocated_epochs.append(record.epoch)
            return record

    kwargs = {}
    latch_cls = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "WriterGenerationLatch"
    )
    if latch_cls is not None:
        latch = latch_cls.for_store_root(root)
        if latch.exists():
            generation = latch.read()
            if generation.generation_state == "ACTIVE":
                kwargs["generation_lease"] = latch.acquire(
                    generation=generation.generation
                )

    return _Counting(root, policy or (lambda _request: True), **kwargs)


def _service(root: Path, adapter, *, store=None, verbs=("publish_committed_branch",)):
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
    from phase_loop_runtime.convergence.broker.verbs import BrokerService

    evidence = BrokerEvidenceStore(root)
    admission = store if store is not None else _counting_store(root)
    return BrokerService(admission, evidence, adapter, contracts=_supported_contracts(*verbs))


def _authority_preimage(repository_identity: str, branch: str) -> dict:
    payload = dict(FABPUB_ENVELOPE_AUTHORITY_PREIMAGE)
    payload["authority_domain_scope"] = f"repository:{repository_identity}"
    payload["operation_identity"] = f"publish:{branch}"
    return payload


def _transaction_authority(repo: Path, branch: str) -> dict:
    identity_fn = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "canonical_repository_identity"
    )
    assert identity_fn is not None
    return _authority_preimage(identity_fn(repo), branch)


def _envelope(transaction, worktree: Path, *, branch: str = "feat/x", **extra):
    envelope_cls = fabpub_symbol("phase_loop_runtime.convergence.contracts", "PreAdmissionEnvelope")
    assert envelope_cls is not None
    return envelope_cls(
        **{
            key: value
            for key, value in _authority_preimage(
                transaction.canonical_repository_identity, branch
            ).items()
            if key != "schema"
        },
        canonical_repository_identity=transaction.canonical_repository_identity,
        original_commit_message_sha256=transaction.original_commit_message_sha256,
        pre_trailer_intent_sha256=transaction.pre_trailer_intent_sha256,
        transaction_id=transaction.transaction_id,
        final_commit_message_sha256=transaction.final_commit_message_sha256,
        expected_commit_oid=transaction.expected_commit_oid,
        committed_head_sha=transaction.committed_head_sha,
        final_commit_object_sha256=transaction.final_commit_object_sha256,
        adapter_worktree=str(worktree),
        checkpoint_root=str(transaction.checkpoint_root),
        **extra,
    )


def _publish_request(
    repo_identity: str,
    branch: str,
    head: str,
    admission,
    worktree: Path,
    *,
    owned_paths=("a.py",),
):
    from phase_loop_runtime.convergence.contracts import BrokerRequest, BrokerVerb

    return BrokerRequest(
        BrokerVerb.PUBLISH_COMMITTED_BRANCH,
        admission,
        repo_identity,
        branch,
        head,
        tuple(owned_paths),
        adapter_worktree=str(worktree),
    )


def _publish_transaction_request(repo_identity: str, branch: str, transaction, worktree: Path):
    return _publish_request(
        repo_identity,
        branch,
        transaction.committed_head_sha,
        _envelope(transaction, worktree, branch=branch),
        worktree,
        owned_paths=transaction.owned_paths,
    )


def _jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _seed_legacy_root(
    ledger_dir: Path,
    *,
    train_path: Path,
    serialized_repo: str,
    epochs=(1, 2, 3),
    terminal=None,
    ambiguous=False,
):
    """Write a PRODUCTION-SHAPED pre-FABPUB broker leaf.

    Layout and key derivation match the shipped CLI exactly:
    ``<ledger-dir>/broker/<sha256(resolved-train-path)[:16]>/<sha256(serialized-repo-bytes)[:16]>``.
    """
    train_key = hashlib.sha256(str(train_path.resolve()).encode("utf-8")).hexdigest()[:16]
    repo_key = hashlib.sha256(serialized_repo.encode("utf-8")).hexdigest()[:16]
    leaf = ledger_dir / "broker" / train_key / repo_key
    leaf.mkdir(parents=True, exist_ok=True)

    admissions = leaf / "admissions.jsonl"
    with admissions.open("w", encoding="utf-8") as stream:
        for sequence, epoch in enumerate(epochs, start=1):
            record = {
                "sequence": sequence,
                "epoch": epoch,
                "request": {
                    "attempt_id": f"legacy-attempt-{epoch}",
                    "lease_epoch": epoch,
                    "fence_token": f"legacy-fence-{epoch}",
                    "approval_digest": f"legacy-approval-{epoch}",
                    "expected_version_predicate": "head == committed",
                    "authority_domain_scope": serialized_repo,
                    "idempotency_key": f"legacy-key-{epoch}",
                },
            }
            stream.write(json.dumps(record, sort_keys=True) + "\n")

    evidence = leaf / "evidence.jsonl"
    lines = []
    if terminal is not None:
        lines.append({"idempotency_key": terminal[0], "state": "provider_call_in_flight", "evidence_reference": ""})
        lines.append({"idempotency_key": terminal[0], "state": "effect_terminal_observed", "evidence_reference": terminal[1]})
    if ambiguous:
        lines.append({"idempotency_key": "legacy-ambiguous", "state": "provider_call_in_flight", "evidence_reference": ""})
        lines.append({"idempotency_key": "legacy-ambiguous", "state": "outcome_ambiguous_blocked", "evidence_reference": "legacy-transient"})
    if lines:
        with evidence.open("w", encoding="utf-8") as stream:
            for line in lines:
                stream.write(json.dumps(line, sort_keys=True) + "\n")

    return {
        "leaf": leaf,
        "train_key": train_key,
        "repo_key": repo_key,
        "admissions": admissions,
        "evidence": evidence,
        "high_water": max(epochs) if epochs else 0,
    }


def _run_python(program: str, *argv: str, cwd: Path | None = None, env_extra=None):
    """Run a FRESH interpreter against the real runtime and return (rc, stdout, stderr)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(RUNTIME_SRC), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env.pop("PHASE_LOOP_TDD_EXPECT_FABPUB", None)
    if env_extra:
        env.update(env_extra)
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(program), *argv],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(cwd) if cwd else None,
        env=env,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _write_train(path: Path, repo_dir_name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Release Train: fabpub\n\n## Nodes\n\n"
        f"### Node: node-1 / specs/plan.md\n\n"
        f"**Workspace:** {repo_dir_name}\n"
        "**Depends on:** (none)\n**Channel:** (none)\n\n"
        f"### Node: node-2 / specs/plan.md\n\n"
        f"**Workspace:** {repo_dir_name}\n"
        "**Depends on:** (none)\n**Channel:** (none)\n",
        encoding="utf-8",
    )
    return path


#: A fresh-process probe that drives the REAL shipped CLI argv path.  It records
#: the exact ``build_routing_broker_client`` kwargs the CLI passed, the
#: coordinator root the CLI chose, and then performs real broker publications
#: through the runtime the CLI itself constructed.  Nothing here fabricates the
#: allocator route: every reported value comes out of production code.
_CLI_ALLOCATOR_PROBE = """
    import dataclasses, json, sys, subprocess
    from pathlib import Path

    train_path, worktree, head_a, head_b = sys.argv[1:5]
    replay = json.loads(sys.argv[5]) if len(sys.argv) > 5 else None

    import phase_loop_runtime.convergence.broker.live as live
    import phase_loop_runtime.train_runner as train_runner
    from phase_loop_runtime import cli

    observed = {
        "builder_kwargs": None,
        "builder_args": None,
        "client": None,
        "train_result": None,
        "coordinator_root": None,
        "store_roots": [],
    }
    real_builder = live.build_routing_broker_client

    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    real_store_init = LinearizableAdmissionStore.__init__

    def spy_store_init(self, root, *args, **kwargs):
        observed["store_roots"].append(str(Path(root).resolve()))
        return real_store_init(self, root, *args, **kwargs)

    LinearizableAdmissionStore.__init__ = spy_store_init

    class _Adapter:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def execute(self, request):
            from phase_loop_runtime.convergence.broker.verbs import (
                BrokerTerminalEvidence, PublishCommittedBranchResult,
            )
            self.calls += 1
            self.requests.append(request)
            key = getattr(request.admission, "idempotency_key", None) or getattr(
                request.admission, "transaction_id", "t"
            )
            return (
                PublishCommittedBranchResult(request.branch, request.head_sha, "https://gh/pr/%d" % self.calls),
                BrokerTerminalEvidence(key, "effect_terminal_observed", "obs"),
            )

    adapter = _Adapter()
    live.GitHubBrokerAdapter = lambda *_args, **_kwargs: adapter

    def spy_builder(*args, **kwargs):
        observed["builder_args"] = [repr(a) for a in args]
        observed["builder_kwargs"] = sorted(kwargs)
        client = real_builder(*args, **kwargs)
        observed["client"] = client
        return client

    live.build_routing_broker_client = spy_builder
    try:
        import phase_loop_runtime.convergence.broker as broker_pkg
        broker_pkg.build_routing_broker_client = spy_builder
    except Exception:
        pass

    heads = [head_a, head_b]
    head_idx = [0]

    def spy_run_loop(workspace, roadmap_path, **kwargs):
        idx = min(head_idx[0], len(heads) - 1)
        target_head = heads[idx]
        head_idx[0] += 1

        target = Path(workspace) / "seed.txt"
        target.write_text(f"content for {target_head}\\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(workspace), "add", "seed.txt"], check=True)
        from phase_loop_runtime.models import StateSnapshot
        return (
            StateSnapshot(
                timestamp="fabpub-cli-probe",
                repo=str(workspace),
                roadmap="specs/plan.md",
                phases={"p1": "complete"},
                phase_owned_dirty_paths=["seed.txt"],
            ),
            [],
        )

    train_runner._default_run_loop = spy_run_loop
    try:
        import phase_loop_runtime.runner as runner_pkg
        runner_pkg.run_loop = spy_run_loop
    except Exception:
        pass


    real_run_train = train_runner.run_train

    def spy_run_train(*args, **kwargs):
        runtime = kwargs["coordinator_runtime"]
        observed["coordinator_root"] = str(Path(runtime.coordinator_root).resolve())
        result = real_run_train(*args, **kwargs)
        observed["train_result"] = result
        return result

    train_runner.run_train = spy_run_train

    rc = cli.main(["run-train", "--train", train_path])

    published_identity = adapter.requests[0].repo
    store_roots = sorted(set(observed["store_roots"]))
    namespace = store_roots[0] if len(store_roots) == 1 else None

    admissions = Path(namespace) / "admissions.jsonl" if namespace else None
    epochs = []
    if admissions is not None and admissions.exists():
        for line in admissions.read_text(encoding="utf-8").splitlines():
            if line.strip():
                epochs.append(json.loads(line)["epoch"])

    replay_result = None
    if replay is not None:
        from phase_loop_runtime.convergence.contracts import AdmissionRequest, BrokerRequest, BrokerVerb

        request = BrokerRequest(
            verb=BrokerVerb.PUBLISH_COMMITTED_BRANCH,
            admission=AdmissionRequest(**replay["admission"]),
            repo=replay["repo"],
            branch=replay["branch"],
            head_sha=replay["head_sha"],
            owned_paths=tuple(replay["owned_paths"]),
            base=replay["base"],
            draft=replay["draft"],
            pr_body=replay["pr_body"],
            adapter_worktree=str(Path(worktree).resolve()),
        )
        before = adapter.calls
        outcome = observed["client"].execute(request)
        replay_result = {
            "accepted": outcome.accepted,
            "provider_calls_delta": adapter.calls - before,
        }

    published = []
    for request in adapter.requests:
        published.append({
            "admission": dataclasses.asdict(request.admission),
            "repo": request.repo,
            "branch": request.branch,
            "head_sha": request.head_sha,
            "owned_paths": list(request.owned_paths),
            "base": request.base,
            "draft": request.draft,
            "pr_body": request.pr_body,
        })

    print(json.dumps({
        "cli_exit": rc,
        "coordinator_root": observed["coordinator_root"],
        "builder_args": observed["builder_args"],
        "builder_kwargs": observed["builder_kwargs"],
        "namespace": namespace,
        "store_roots": store_roots,
        "identity": published_identity,
        "epochs": epochs,
        "adapter_calls": adapter.calls,
        "published": published,
        "train_status": (observed["train_result"] or {}).get("status"),
        "replay": replay_result,
    }, sort_keys=True))
"""



def _cli_allocator_probe(
    train: Path, worktree: Path, head_a: str, head_b: str, *, replay: dict | None = None
) -> dict:
    argv = [str(train), str(worktree), head_a, head_b]
    if replay is not None:
        argv.append(json.dumps(replay, sort_keys=True))
    rc, out, err = _run_python(
        _CLI_ALLOCATOR_PROBE,
        *argv,
        cwd=train.parent,
        env_extra={FABPUB_ACTIVATION_ENV: "1"},
    )
    assert rc == 0, f"CLI allocator probe failed (rc={rc}):\n{out}\n{err}"
    return json.loads(out.strip().splitlines()[-1])


# ===========================================================================
# Guard-control tests — never skip, GREEN in every mode
# ===========================================================================


def test_fabpub_guard_activation_contract_is_exact(monkeypatch):
    """Activation is EXACTLY ``PHASE_LOOP_TDD_EXPECT_FABPUB=1`` or the marker."""
    monkeypatch.delenv(FABPUB_ACTIVATION_ENV, raising=False)
    marker_installed = fabpub_marker_version() == 1
    assert fabpub_capability_active() is marker_installed, (
        "with the env switch unset, activation must follow the marker probe exactly"
    )

    monkeypatch.setenv(FABPUB_ACTIVATION_ENV, "1")
    assert fabpub_capability_active() is True

    for not_activation in ("0", "true", "yes", "", "01", " 1"):
        monkeypatch.setenv(FABPUB_ACTIVATION_ENV, not_activation)
        assert fabpub_capability_active() is marker_installed, (
            f"{not_activation!r} must not be treated as explicit activation"
        )

    # A missing marker module is the ordinary pre-SL-4 state and must never raise.
    monkeypatch.delenv(FABPUB_ACTIVATION_ENV, raising=False)
    assert fabpub_marker_version() in (None, 1)
    assert FABPUB_MARKER_MODULE == "phase_loop_runtime.fabpub_capability"


def test_fabpub_guard_vector_digests_match_inline_vectors():
    """The four frozen vector digests must equal the inline vectors' digests."""
    assert vector_digest(FABPUB_ENVELOPE_AUTHORITY_PREIMAGE) == FABPUB_IDENTITY_VECTOR[
        "envelope_authority_preimage_sha256"
    ]
    assert vector_digest(FABPUB_REPOSITORY_IDENTITY_VECTOR) == FABPUB_REPOSITORY_IDENTITY_VECTOR_SHA256
    assert vector_digest(FABPUB_IDENTITY_VECTOR) == FABPUB_IDENTITY_VECTOR_SHA256
    assert vector_digest(FABPUB_COMMIT_OBJECT_VECTOR) == FABPUB_COMMIT_OBJECT_VECTOR_SHA256
    assert vector_digest(FABPUB_LEGACY_CUTOVER_VECTOR) == FABPUB_LEGACY_CUTOVER_VECTOR_SHA256

    # The pre-trailer allowlist may not contain the identity it derives, nor any
    # post-object binding.  This is the acyclicity invariant, asserted on the
    # VECTOR itself so it holds independently of any implementation.
    forbidden = {
        "transaction_id",
        "final_commit_message_sha256",
        "expected_commit_oid",
        "committed_head_sha",
        "final_commit_object_sha256",
    }
    assert not (forbidden & set(FABPUB_IDENTITY_VECTOR)), (
        "PublishPreTrailerIntent.v1 must not contain transaction_id or any post-object field"
    )
    assert "worktree" not in json.dumps(FABPUB_REPOSITORY_IDENTITY_VECTOR), (
        "canonical repository identity must not hash a worktree path"
    )


def test_fabpub_guard_nodeid_inventories_are_disjoint_and_counted():
    """Inventory arithmetic, digests, and the ownership framing stay honest."""
    new = set(FABPUB_NEW_PRODUCTION_NODEIDS)
    migrated = set(FABPUB_MIGRATED_NODEIDS)
    assert not (new & migrated), "a nodeid is either newly added or migrated, never both"
    assert set(FABPUB_RED_NODEIDS) == new | migrated
    assert set(FABPUB_EXPECTED_NODEIDS) == set(FABPUB_RED_NODEIDS)
    assert FABPUB_DEFAULT_SKIP_COUNT == len(FABPUB_NEW_PRODUCTION_NODEIDS)

    # Every RED nodeid carries a UNIQUE anchor.
    anchors = [FABPUB_RED_ANCHORS[n] for n in FABPUB_RED_NODEIDS]
    assert len(set(anchors)) == len(anchors), "RED anchors must be unique per nodeid"
    assert set(FABPUB_RED_ANCHORS) == set(FABPUB_RED_NODEIDS)

    # Frozen sub-inventories are subsets of the new set with their exact counts.
    for inventory, count in (
        (FABPUB_IDENTITY_NODEIDS, 2),
        (FABPUB_SHARED_ALLOCATOR_NODEIDS, 2),
        (FABPUB_ADAPTER_START_FENCE_NODEIDS, 1),
        (FABPUB_WRITER_GENERATION_FENCE_NODEIDS, 1),
        (FABPUB_LEGACY_CUTOVER_NODEIDS, 8),
        (FABPUB_RUN_TRAIN_RECOVERY_NODEIDS, 1),
    ):
        assert len(inventory) == count
        assert len(set(inventory)) == count
        assert set(inventory) <= new

    assert fabpub_inventory_digest(FABPUB_IDENTITY_NODEIDS) == FABPUB_IDENTITY_NODEIDS_SHA256
    assert (
        fabpub_inventory_digest(FABPUB_SHARED_ALLOCATOR_NODEIDS)
        == FABPUB_SHARED_ALLOCATOR_NODEIDS_SHA256
    )
    assert (
        fabpub_inventory_digest(FABPUB_ADAPTER_START_FENCE_NODEIDS)
        == FABPUB_ADAPTER_START_FENCE_NODEIDS_SHA256
    )
    assert (
        fabpub_inventory_digest(FABPUB_WRITER_GENERATION_FENCE_NODEIDS)
        == FABPUB_WRITER_GENERATION_FENCE_NODEIDS_SHA256
    )
    assert (
        fabpub_inventory_digest(FABPUB_LEGACY_CUTOVER_NODEIDS)
        == FABPUB_LEGACY_CUTOVER_NODEIDS_SHA256
    )

    # Freeze the candidate-minus-four-sub-inventories reconstruction.  The
    # chronology reducer separately requires the independent runner-stamped JSON
    # operand before accepting the cumulative delta.
    additions = set().union(
        FABPUB_SHARED_ALLOCATOR_NODEIDS,
        FABPUB_ADAPTER_START_FENCE_NODEIDS,
        FABPUB_WRITER_GENERATION_FENCE_NODEIDS,
        FABPUB_LEGACY_CUTOVER_NODEIDS,
    )
    predecessor = new - additions
    assert len(predecessor) == 23
    assert fabpub_inventory_digest(predecessor) == FABPUB_SUPERSEDED_BASELINE_INVENTORY_SHA256
    assert FABPUB_BASELINE_INVENTORY_AVAILABLE is False
    assert FABPUB_FROZEN_SUBINVENTORY_CONTRIBUTIONS == {
        "shared_allocator": 2,
        "adapter_start_fence": 1,
        "writer_generation_fence": 1,
        "legacy_cutover": 8,
    }
    assert FABPUB_FROZEN_SUBINVENTORY_TOTAL == 12

    # Ownership framing: 25 owned paths, 12 of them the SL-0 test inventory.
    assert len(FABPUB_OWNED_PATHS) == 25 and len(set(FABPUB_OWNED_PATHS)) == 25
    assert len(FABPUB_TEST_PATHS) == 12
    assert fabpub_inventory_digest(FABPUB_OWNED_PATHS) == FABPUB_OWNED_PATHS_SHA256
    assert fabpub_inventory_digest(FABPUB_TEST_PATHS) == FABPUB_TEST_PATHS_SHA256

    # Every frozen test path exists in the candidate tree (this file included).
    for relative in FABPUB_TEST_PATHS:
        assert (REPO_ROOT / relative).exists(), f"frozen test path missing: {relative}"


def test_fabpub_manifest_binding_inherits_partial_rebinds_newest_to_oldest(tmp_path):
    inventories = {
        "owned_paths": ["new-owner.py"],
        "test_paths": ["test_fabpub.py"],
        "shared_allocator_nodeids": ["test_fabpub.py::test_allocator"],
        "legacy_cutover_nodeids": ["test_fabpub.py::test_cutover"],
        "adapter_start_fence_nodeids": ["test_fabpub.py::test_start"],
        "writer_generation_fence_nodeids": ["test_fabpub.py::test_generation"],
    }
    plan = tmp_path / "plans" / "phase-plan-v10-FABPUB.md"
    roadmap = tmp_path / "specs" / "phase-plans-v10.md"
    plan.parent.mkdir()
    roadmap.parent.mkdir()
    plan.write_text("# FABPUB\n", encoding="utf-8")
    roadmap.write_text("# v10\n", encoding="utf-8")
    plan_sha256 = hashlib.sha256(plan.read_bytes()).hexdigest()
    roadmap_sha256 = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    original = {
        **inventories,
        "owned_paths": ["old-owner.py"],
        "roadmap_sha256": roadmap_sha256,
    }
    lifecycle = [
        {"metadata": {"fabpub_plan_contract": original}},
        {
            "metadata": {
                "fabpub_plan_contract_rebind": {
                    "owned_paths": inventories["owned_paths"],
                    "owned_paths_sha256": fabpub_inventory_digest(inventories["owned_paths"]),
                }
            }
        },
        {"metadata": {"fabpub_plan_contract_rebind": {"plan_sha256": plan_sha256}}},
    ]
    manifest = {
        "plans": [{"file": "plans/phase-plan-v10-FABPUB.md", "lifecycle": lifecycle}]
    }
    (tmp_path / "plans" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    guard = SimpleNamespace(
        FABPUB_OWNED_PATHS=inventories["owned_paths"],
        FABPUB_TEST_PATHS=inventories["test_paths"],
        FABPUB_SHARED_ALLOCATOR_NODEIDS=inventories["shared_allocator_nodeids"],
        FABPUB_LEGACY_CUTOVER_NODEIDS=inventories["legacy_cutover_nodeids"],
        FABPUB_ADAPTER_START_FENCE_NODEIDS=inventories["adapter_start_fence_nodeids"],
        FABPUB_WRITER_GENERATION_FENCE_NODEIDS=inventories["writer_generation_fence_nodeids"],
    )

    report = audit_plan_manifest_binding(tmp_path, guard)

    assert report == {"evaluated": True, "record_id": plan_sha256, "errors": []}

    plan.write_text("# changed FABPUB\n", encoding="utf-8")
    drift = audit_plan_manifest_binding(tmp_path, guard)
    assert "plan_sha256 does not match plans/phase-plan-v10-FABPUB.md" in drift["errors"]


def test_fabpub_digest_bound_artifact_requires_external_expected_digest(tmp_path):
    artifact = tmp_path / "panel.json"
    artifact.write_text('{"verdict":"AGREE"}\n', encoding="utf-8")
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()

    assert audit_digest_bound_artifact(artifact, expected, label="test-panel")["errors"] == []
    assert audit_digest_bound_artifact(artifact, None, label="test-panel")["errors"] == [
        "the test-panel expected SHA-256 was not runner-stamped"
    ]
    mismatch = audit_digest_bound_artifact(artifact, "0" * 64, label="test-panel")
    assert mismatch["errors"] == ["the test-panel artifact SHA-256 does not match its runner stamp"]


def test_fabpub_pytest_invocation_receipt_binds_stage_head_tree_and_junit(tmp_path):
    junit = tmp_path / "stage.junit.xml"
    junit.write_text("<testsuites tests=\"0\"/>\n", encoding="utf-8")
    receipt = tmp_path / "stage.invocation.json"
    payload = {
        "schema": "fabpub_pytest_invocation.v1",
        "argv": ["env", "PHASE_LOOP_TDD_EXPECT_FABPUB=1", "pytest", "--junitxml", str(junit)],
        "exit_code": 0,
        "junit": str(junit),
        "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
        "head": "a" * 40,
        "test_tree_sha256": "b" * 64,
        "activation_env": "PHASE_LOOP_TDD_EXPECT_FABPUB=1",
        "marker_present": False,
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    report = fabpub_chronology.audit_pytest_invocation_receipt(
        receipt,
        junit,
        expected_head="a" * 40,
        expected_test_tree_sha256="b" * 64,
        expected_activation_env="PHASE_LOOP_TDD_EXPECT_FABPUB=1",
        expected_marker_present=False,
        label="preactivation",
    )
    assert report["errors"] == []

    payload["head"] = "c" * 40
    payload["activation_env"] = None
    payload["junit_sha256"] = "d" * 64
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    drift = fabpub_chronology.audit_pytest_invocation_receipt(
        receipt,
        junit,
        expected_head="a" * 40,
        expected_test_tree_sha256="b" * 64,
        expected_activation_env="PHASE_LOOP_TDD_EXPECT_FABPUB=1",
        expected_marker_present=False,
        label="preactivation",
    )
    assert any("head" in error for error in drift["errors"])
    assert any("activation" in error for error in drift["errors"])
    assert any("JUnit digest" in error for error in drift["errors"])

    payload["head"] = "a" * 40
    payload["junit_sha256"] = hashlib.sha256(junit.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    false_final = fabpub_chronology.audit_pytest_invocation_receipt(
        receipt,
        junit,
        expected_head="a" * 40,
        expected_test_tree_sha256="b" * 64,
        expected_activation_env=None,
        expected_marker_present=False,
        label="final",
    )
    assert "the final argv activation does not match its lifecycle stage" in false_final["errors"]


def test_fabpub_panel_envelope_binds_reviewed_inputs_and_four_usable_seats(tmp_path):
    panel = tmp_path / "panel.json"
    bindings = {
        "head": "a" * 40,
        "test_tree_sha256": "b" * 64,
        "guard_sha256": "c" * 64,
        "red_junit_sha256": "d" * 64,
        "default_junit_sha256": "e" * 64,
    }
    panel.write_text(
        json.dumps({"schema": "fabpub_test_panel.v1", **bindings, "usable_count": 4}),
        encoding="utf-8",
    )
    expected = hashlib.sha256(panel.read_bytes()).hexdigest()

    report = fabpub_chronology.audit_test_panel_envelope(
        panel, expected, expected_bindings=bindings
    )
    assert report["errors"] == []

    panel.write_text(
        json.dumps(
            {
                "schema": "fabpub_test_panel.v1",
                **bindings,
                "test_tree_sha256": "f" * 64,
                "usable_count": 3,
            }
        ),
        encoding="utf-8",
    )
    drift = fabpub_chronology.audit_test_panel_envelope(
        panel,
        hashlib.sha256(panel.read_bytes()).hexdigest(),
        expected_bindings=bindings,
    )
    assert any("test_tree_sha256" in error for error in drift["errors"])
    assert any("four usable seats" in error for error in drift["errors"])


def test_fabpub_final_junit_reduces_the_full_frozen_boundary(monkeypatch, tmp_path):
    seen = []

    def section(name):
        def audit(*_args, **_kwargs):
            seen.append(name)
            return {"errors": []}

        return audit

    monkeypatch.setattr(
        fabpub_chronology,
        "load_guard",
        lambda _repo: SimpleNamespace(FABPUB_ACTIVATION_ENV="PHASE_LOOP_TDD_EXPECT_FABPUB"),
    )
    monkeypatch.setattr(
        fabpub_chronology,
        "audit_head_binding",
        lambda _repo, _head: {"resolved": "head", "errors": []},
    )
    for name in (
        "audit_frozen_inventories",
        "audit_vectors",
        "audit_test_tree",
        "audit_plan_manifest_binding",
        "audit_marker",
        "audit_sl0_git_boundary",
        "audit_red_evidence",
        "audit_default_evidence",
        "audit_pytest_invocation_receipt",
        "audit_activated_pass_junit",
        "audit_phase_evidence",
        "audit_test_panel_envelope",
    ):
        monkeypatch.setattr(fabpub_chronology, name, section(name))
    args = SimpleNamespace(
        repo=str(tmp_path),
        head="HEAD",
        mode="final-junit",
        predecessor_inventory=None,
        base=None,
        tests_only=None,
        red_exit_code=None,
        red_junit=None,
        red_raw_log=None,
        red_invocation=None,
        default_junit=None,
        default_invocation=None,
        preactivation_junit=None,
        preactivation_invocation=None,
        final_junit=None,
        final_invocation=None,
        cutover_evidence=None,
        cutover_evidence_sha256=None,
        start_owner_evidence=None,
        start_owner_evidence_sha256=None,
        test_panel_record=None,
        test_panel_record_sha256=None,
        sha_c=None,
    )

    report = fabpub_chronology.build_report(args)

    assert report["ok"] is True
    for required in (
        "audit_frozen_inventories",
        "audit_vectors",
        "audit_test_tree",
        "audit_plan_manifest_binding",
        "audit_sl0_git_boundary",
        "audit_red_evidence",
        "audit_default_evidence",
        "audit_test_panel_envelope",
    ):
        assert required in seen


def test_fabpub_guard_transaction_identity_derivation_is_acyclic():
    """Pure-vector control: the derivation never hashes what it derives."""
    pre_trailer = canonical_bytes(FABPUB_IDENTITY_VECTOR)
    transaction_id = hashlib.sha256(TRANSACTION_DOMAIN + pre_trailer).hexdigest()
    assert transaction_id.encode("ascii") not in pre_trailer

    final_message = (
        FABPUB_IDENTITY_ORIGINAL_MESSAGE
        + TRAILER_PREFIX
        + transaction_id.encode("ascii")
        + b"\n"
    )
    assert final_message.count(b"FABPUB-Intent-ID:") == 1
    assert hashlib.sha256(final_message).hexdigest() != transaction_id

    # Changing ONE pre-trailer authority byte changes both digests.
    mutated = dict(FABPUB_IDENTITY_VECTOR, branch=FABPUB_IDENTITY_VECTOR["branch"] + "x")
    mutated_bytes = canonical_bytes(mutated)
    assert mutated_bytes != pre_trailer
    assert hashlib.sha256(TRANSACTION_DOMAIN + mutated_bytes).hexdigest() != transaction_id


# ===========================================================================
# Allocator falsifiers
# ===========================================================================


@_requires_fabpub
def test_fabpub_allocator_stale_epoch(tmp_path, request):
    """Stale presentation is refused against the authenticated high-water floor."""
    nodeid = fabpub_this_nodeid(request)
    store_cls = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.admission", "LinearizableAdmissionStore.admit_next"
    )
    fabpub_require(
        nodeid,
        store_cls is not None,
        "LinearizableAdmissionStore.admit_next is absent; fresh publish still uses admit()",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    repo = _init_repo(tmp_path / "allocator-stale-repo")
    _identity, root = _activate_repository_authority(
        tmp_path, repo, label="allocator-stale"
    )
    store = _counting_store(root)

    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", f"key-{epoch}")

    first = store.admit_next(make, attempt_id="attempt-1", precondition=lambda: True)
    second = store.admit_next(make, attempt_id="attempt-2", precondition=lambda: True)
    assert second.epoch == first.epoch + 1, "the allocator is strictly monotonic"

    # The FLOOR is production's, read back off disk — not a value this test set.
    persisted = _jsonl(root / "admissions.jsonl")
    assert [row["epoch"] for row in persisted] == [first.epoch, second.epoch]

    stale = AdmissionRequest("attempt-3", first.epoch, "fence", "digest", "predicate", "scope", "key-stale")
    with pytest.raises(PermissionError):
        store.admit(stale)
    assert len(_jsonl(root / "admissions.jsonl")) == 2, "a refused stale publish appends nothing"

    # A denying in-lock precondition allocates nothing and leaves the floor intact.
    with pytest.raises((PermissionError, ValueError)):
        store.admit_next(make, attempt_id="attempt-4", precondition=lambda: False)
    assert len(_jsonl(root / "admissions.jsonl")) == 2


@_requires_fabpub
def test_fabpub_allocator_epoch_equality(tmp_path, request):
    """``make_request`` must be handed — and must return — the allocated epoch."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        fabpub_symbol(
            "phase_loop_runtime.convergence.broker.admission",
            "LinearizableAdmissionStore.admit_next",
        )
        is not None,
        "LinearizableAdmissionStore.admit_next is absent",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    repo = _init_repo(tmp_path / "allocator-epoch-repo")
    _identity, root = _activate_repository_authority(
        tmp_path, repo, label="allocator-epoch"
    )
    store = _counting_store(root)
    offered: list = []

    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        offered.append(epoch)  # filled by PRODUCTION, which chooses the epoch
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", f"key-{epoch}")

    record = store.admit_next(make, attempt_id="attempt-1", precondition=lambda: True)
    assert offered == [record.epoch], "production must offer exactly the epoch it allocates"
    assert record.request.lease_epoch == record.epoch
    assert _jsonl(root / "admissions.jsonl")[0]["request"]["lease_epoch"] == record.epoch

    def divergent(epoch: int, attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest(attempt_id, epoch + 7, "fence", "digest", "predicate", "scope", "key-bad")

    with pytest.raises((ValueError, PermissionError)):
        store.admit_next(divergent, attempt_id="attempt-2", precondition=lambda: True)
    assert len(_jsonl(root / "admissions.jsonl")) == 1, "a rejected build must not append"

    # Positive control: after the rejection the allocator still advances normally.
    following = store.admit_next(make, attempt_id="attempt-3", precondition=lambda: True)
    assert following.epoch == record.epoch + 1


@_requires_fabpub
def test_fabpub_allocator_attempt_equality(tmp_path, request):
    """The supplied attempt identity is authoritative on both fresh and dedup paths."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        fabpub_symbol(
            "phase_loop_runtime.convergence.broker.admission",
            "LinearizableAdmissionStore.admit_next",
        )
        is not None,
        "LinearizableAdmissionStore.admit_next is absent",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    repo = _init_repo(tmp_path / "allocator-attempt-repo")
    _identity, root = _activate_repository_authority(
        tmp_path, repo, label="allocator-attempt"
    )
    store = _counting_store(root)
    rebuilt_epochs: list = []

    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        rebuilt_epochs.append(epoch)
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", "key-1")

    first = store.admit_next(make, attempt_id="deterministic-attempt", precondition=lambda: True)
    assert first.request.attempt_id == "deterministic-attempt"

    replayed = store.admit_next(make, attempt_id="deterministic-attempt", precondition=lambda: True)
    assert replayed == first, "an attempt_id hit rebuilds at the PRIOR epoch and returns the original"
    assert rebuilt_epochs == [first.epoch, first.epoch], (
        "the dedup path must rebuild at prior.epoch, never allocate a new one"
    )
    assert len(_jsonl(root / "admissions.jsonl")) == 1

    def wrong_attempt(epoch: int, _attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest("other-attempt", epoch, "fence", "digest", "predicate", "scope", "key-1")

    with pytest.raises((ValueError, PermissionError)):
        store.admit_next(wrong_attempt, attempt_id="deterministic-attempt", precondition=lambda: True)
    assert len(_jsonl(root / "admissions.jsonl")) == 1


@_requires_fabpub
def test_fabpub_allocator_shared_repository_epoch_across_linked_worktrees_and_train_roots(
    tmp_path, request
):
    """One canonical repository → one allocator across linked worktrees/train roots."""
    nodeid = fabpub_this_nodeid(request)
    identity_fn = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "canonical_repository_identity"
    )
    namespace_fn = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "repository_broker_namespace"
    )
    fabpub_require(
        nodeid,
        identity_fn is not None and namespace_fn is not None,
        "live.canonical_repository_identity / repository_broker_namespace are absent; "
        "routing still uses _repo_store_slug(worktree path)",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    primary = _init_repo(tmp_path / "primary")
    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-q", "-b", "feat/linked", str(linked))
    other = _init_repo(tmp_path / "other")

    primary_identity = identity_fn(primary)
    assert identity_fn(linked) == primary_identity, "linked worktrees share one repository identity"
    assert len(primary_identity) == 64 and all(c in "0123456789abcdef" for c in primary_identity)
    assert identity_fn(other) != primary_identity, "distinct git common dirs stay distinct"

    activated = _activate_repository_authorities(
        tmp_path, ((primary, "allocator-shared-primary"), (other, "allocator-shared-other"))
    )
    primary_ns = Path(namespace_fn(primary))
    assert activated[primary] == (primary_identity, primary_ns)
    assert Path(namespace_fn(linked)) == primary_ns
    common = _git_common_dir(primary)
    assert primary_ns == common / "phase-loop-fabpub-broker-v1" / "repositories" / primary_identity
    assert Path(namespace_fn(other)) != primary_ns

    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", f"k-{attempt_id}")

    # SEQUENTIAL: two stores constructed from DIFFERENT worktrees of one repository
    # must continue ONE epoch sequence, because production put them on one root.
    from_primary = _counting_store(primary_ns)
    from_linked = _counting_store(Path(namespace_fn(linked)))
    a = from_primary.admit_next(make, attempt_id="attempt-a", precondition=lambda: True)
    b = from_linked.admit_next(make, attempt_id="attempt-b", precondition=lambda: True)
    assert (a.epoch, b.epoch) == (1, 2), "one repository, one monotonic epoch space"

    # REPLAY across worktrees: the other worktree's store returns the SAME record.
    assert from_linked.admit_next(make, attempt_id="attempt-a", precondition=lambda: True) == a
    assert len(_jsonl(primary_ns / "admissions.jsonl")) == 2, "replay allocates nothing"

    # CONCURRENT: N threads race the ONE repository allocator through stores built
    # from BOTH worktrees.  Production must hand out unique consecutive epochs under
    # its advisory lock — a sequential-only proof cannot show that (plan:219/:348).
    import threading

    concurrency = 8
    barrier = threading.Barrier(concurrency)
    outcomes: list = []
    lock = threading.Lock()

    def race(index: int) -> None:
        store = _counting_store(Path(namespace_fn(primary if index % 2 == 0 else linked)))
        barrier.wait(timeout=30)
        try:
            record = store.admit_next(
                make, attempt_id=f"concurrent-{index}", precondition=lambda: True
            )
            with lock:
                outcomes.append(record.epoch)
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            with lock:
                outcomes.append(exc)

    threads = [threading.Thread(target=race, args=(i,)) for i in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert all(isinstance(o, int) for o in outcomes), f"a concurrent allocation failed: {outcomes}"
    assert len(outcomes) == concurrency
    assert len(set(outcomes)) == concurrency, f"epochs must be UNIQUE under concurrency: {outcomes}"
    assert sorted(outcomes) == list(range(3, 3 + concurrency)), (
        f"epochs must be CONSECUTIVE from the prior high-water: {sorted(outcomes)}"
    )
    rows = _jsonl(primary_ns / "admissions.jsonl")
    assert len(rows) == 2 + concurrency, "every concurrent winner appended exactly one row"
    assert [row["sequence"] for row in rows] == list(range(1, len(rows) + 1)), (
        "the append-only sequence stays contiguous under concurrency"
    )

    # DISTINCT REPOSITORY: an unrelated git common dir starts its OWN sequence at 1
    # and shares no rows with the first.  The primary namespace must be unchanged by
    # that allocation — compared against the row count production actually left after
    # the concurrency arm, never a stale constant.
    primary_rows_before = len(_jsonl(primary_ns / "admissions.jsonl"))
    assert primary_rows_before == 2 + concurrency
    other_ns = Path(namespace_fn(other))
    assert activated[other][1] == other_ns
    other_store = _counting_store(other_ns)
    assert other_store.admit_next(make, attempt_id="attempt-a", precondition=lambda: True).epoch == 1
    assert len(_jsonl(other_ns / "admissions.jsonl")) == 1, (
        "a distinct repository starts its own epoch space"
    )
    assert len(_jsonl(primary_ns / "admissions.jsonl")) == primary_rows_before, (
        "an unrelated repository's allocation must not touch this repository's log"
    )
    assert other_ns != primary_ns


@_requires_fabpub
def test_fabpub_default_cli_train_roots_share_git_common_repository_allocator_without_root_injection(
    tmp_path, request
):
    """Two ordinary CLI trains, no --ledger-dir, no root injection → one allocator.

    The falsifier drives the REAL shipped CLI argv path twice in FRESH processes.
    Every asserted value is production output: the kwargs the CLI passed to the
    routing builder, the coordinator root the CLI chose, the namespace
    ``live`` resolved, and the epochs the allocator wrote to disk.
    """
    nodeid = fabpub_this_nodeid(request)
    namespace_fn = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "repository_broker_namespace"
    )
    fabpub_require(
        nodeid,
        namespace_fn is not None,
        "live.repository_broker_namespace is absent; the production route still selects "
        "the allocator root from the caller's train-path hash",
    )

    repo = _init_repo(tmp_path / "repo")
    _make_cli_publishable(repo, "feat/shared")
    linked = tmp_path / "linked"
    unrelated = _init_repo(tmp_path / "unrelated")

    head_a, head_b = "a" * 40, "b" * 40

    # Two ordinary train files in UNRELATED parent directories; --ledger-dir omitted.
    alpha = _write_train(tmp_path / "trains-alpha" / "release.md", str(repo))
    beta = _write_train(tmp_path / "trains-beta" / "release.md", str(linked))

    first = _cli_allocator_probe(alpha, repo, head_a, head_b)
    assert len(first["published"]) == 2
    replay = first["published"][0]
    _git(repo, "checkout", "-q", "main")
    _git(repo, "worktree", "add", "-q", str(linked), "feat/shared")
    second = _cli_allocator_probe(beta, linked, "c" * 40, "d" * 40, replay=replay)

    # The CLI passes NO allocator root — asserted on the real builder call.
    for probe in (first, second):
        assert probe["cli_exit"] == 0
        assert probe["train_status"] in ("completed", "drafts_open")
        assert probe["builder_args"] == [], "the production builder takes no positional root"
        assert "broker_root" not in (probe["builder_kwargs"] or []), (
            "the activated production CLI must call the routing builder with no allocator root"
        )
        assert probe["store_roots"] == [probe["namespace"]], (
            "the asserted repository namespace must be the root production passed to its store"
        )
        assert probe["coordinator_root"] != probe["namespace"], (
            "train-local checkpoints and repository allocator records must use different roots"
        )

    # Distinct train-local coordinator roots, ONE repository allocator namespace.
    assert first["coordinator_root"] != second["coordinator_root"]
    assert first["namespace"] == second["namespace"]
    assert first["identity"] == second["identity"]

    # Each train publishes two distinct real commits.  Replaying the first train's
    # exact canonical (repo, branch, head) through the linked worktree is terminal.
    assert first["epochs"] == [1, 2], f"expected 1,2 from the shared allocator; got {first['epochs']}"
    assert second["epochs"] == [1, 2, 3, 4]
    assert second["adapter_calls"] == 2
    assert second["replay"] == {"accepted": True, "provider_calls_delta": 0}

    # No admission/evidence state under either default train ledger.
    for train in (alpha, beta):
        ledger = train.parent / ".train-ledger"
        assert not list(ledger.rglob("admissions.jsonl")), f"allocator rows leaked under {ledger}"
        assert not list(ledger.rglob("evidence.jsonl")), f"evidence rows leaked under {ledger}"

    # A distinct git common directory derives a different namespace/ambiguity domain.
    assert str(namespace_fn(unrelated)) != first["namespace"]


# ===========================================================================
# Broker fresh-publish gate
# ===========================================================================


@_requires_fabpub
def test_fabpub_fresh_finalized_publish_rejected_before_admission_and_adapter(tmp_path, request):
    """A fresh finalized publish is refused before either admission method or the adapter."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _envelope_cls_present(),
        "PreAdmissionEnvelope / admit_next are absent; a fresh finalized publish still admits",
    )

    from phase_loop_runtime.convergence.broker.verbs import publish_committed_branch_idempotency_key
    from phase_loop_runtime.convergence.contracts import (
        AdmissionRequest,
        BrokerRequest,
        BrokerVerb,
    )
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    worktree = _init_repo(tmp_path / "repo")
    root = tmp_path / "store"
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store, verbs=("publish_committed_branch", "merge"))

    finalized = AdmissionRequest("attempt", 1, "fence", "digest", "predicate", "scope", "key-1")
    fresh = _publish_request("repo-identity", "feat/x", "abc123", finalized, worktree)

    with pytest.raises(TypeError) as excinfo:
        service.execute(fresh)
    assert str(excinfo.value) == "fresh publish_committed_branch requires PreAdmissionEnvelope"
    assert (store.admit_calls, store.admit_next_calls) == (0, 0)
    assert store.replay() == ()
    assert service.evidence_store.replay() == {}
    assert adapter.calls == [], "the adapter must not be reached"

    # Positive control (a): a finalized request for a supported NON-publish verb
    # still reaches the legacy admit() path and its adapter exactly once.
    non_publish = BrokerRequest(
        BrokerVerb.MERGE, finalized, "repo-identity", "feat/x", "abc123", ("a.py",),
        adapter_worktree=str(worktree),
    )
    service.execute(non_publish)
    assert store.admit_calls == 1 and len(adapter.calls) == 1

    # Positive control (b): an already-completed terminal publish REPLAYS through a
    # finalized request with neither admission method nor the adapter called.
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord

    replay_repo, replay_txn, replay_identity, replay_root = _authorized_publish_fixture(
        tmp_path, name="fresh-finalized-replay"
    )
    replay_service = _service(replay_root, _CountingAdapter())
    replay_request = _publish_request(
        replay_identity,
        "feat/x",
        replay_txn.committed_head_sha,
        finalized,
        replay_repo,
    )
    completed_key = (
        "publish_committed_branch\0"
        + publish_committed_branch_idempotency_key(
            replay_identity, "feat/x", replay_txn.committed_head_sha
        )
    )
    replay_service.evidence_store.record_intent(completed_key)
    replay_service.evidence_store.record_terminal(
        EvidenceRecord(
            completed_key,
            TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
            "https://gh/pr/prior",
        )
    )
    replay_store = replay_service.admission_store
    replay_adapter = replay_service.adapter
    before = (
        replay_store.admit_calls,
        replay_store.admit_next_calls,
        len(replay_adapter.calls),
    )
    replay = replay_service.execute(replay_request)
    assert replay.accepted and replay.publish_result.pr_url == "https://gh/pr/prior"
    assert (
        replay_store.admit_calls,
        replay_store.admit_next_calls,
        len(replay_adapter.calls),
    ) == before

    # Positive control (c): a fresh ENVELOPE publish reaches admit_next and the
    # adapter with the broker-allocated epoch.
    positive_repo, positive_txn, positive_identity, positive_root = _authorized_publish_fixture(
        tmp_path, name="fresh-envelope-positive"
    )
    positive_adapter = _CountingAdapter()
    positive_store = _counting_store(positive_root)
    positive_service = _service(positive_root, positive_adapter, store=positive_store)
    envelope_request = _publish_transaction_request(
        positive_identity, "feat/x", positive_txn, positive_repo
    )
    outcome = positive_service.execute(envelope_request)
    assert outcome.accepted
    assert positive_store.admit_next_calls == 1 and positive_store.allocated_epochs == [1]
    assert len(positive_adapter.calls) == 1
    assert positive_adapter.calls[-1].admission.lease_epoch == 1, (
        "the adapter must receive the broker-FINALIZED request at the allocated epoch"
    )


def _envelope_cls_present() -> bool:
    return (
        fabpub_symbol("phase_loop_runtime.convergence.contracts", "PreAdmissionEnvelope") is not None
        and fabpub_symbol(
            "phase_loop_runtime.convergence.broker.admission",
            "LinearizableAdmissionStore.admit_next",
        )
        is not None
    )


@_requires_fabpub
def test_fabpub_broker_envelope_publish_allocates_through_admit_next(tmp_path, request):
    """A fresh envelope publish routes through ``admit_next`` and binds the transaction."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _envelope_cls_present(),
        "PreAdmissionEnvelope is absent; BrokerService cannot route a fresh publish to admit_next",
    )

    envelope_cls = fabpub_symbol("phase_loop_runtime.convergence.contracts", "PreAdmissionEnvelope")
    fields = set(envelope_cls.__dataclass_fields__)
    for forbidden in ("lease_epoch", "fence_token", "approval_digest", "idempotency_key"):
        assert forbidden not in fields, f"the envelope must be epoch/authority-free; found {forbidden}"
    for required in (
        "train_id",
        "node_id",
        "action",
        "roadmap_digest",
        "effective_code_digest",
        "dependency_digest",
        "verification_plan_digest",
        "expected_version_predicate",
        "authority_domain_scope",
        "operation_identity",
        "canonical_repository_identity",
        "original_commit_message_sha256",
        "pre_trailer_intent_sha256",
        "transaction_id",
        "final_commit_message_sha256",
        "expected_commit_oid",
        "committed_head_sha",
        "final_commit_object_sha256",
        "adapter_worktree",
        "checkpoint_root",
    ):
        assert required in fields

    worktree, transaction, identity, root = _authorized_publish_fixture(
        tmp_path, name="broker-envelope"
    )
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)

    head = transaction.committed_head_sha
    outcome = service.execute(
        _publish_transaction_request(identity, "feat/x", transaction, worktree)
    )
    assert outcome.accepted
    assert (store.admit_calls, store.admit_next_calls) == (0, 1), "fresh publish never uses legacy admit()"
    assert store.allocated_epochs == [1]

    # The ADAPTER received a finalized request the broker built, bound to the
    # transaction and carrying the allocated epoch — never the caller's envelope.
    delivered = adapter.calls[-1].admission
    assert not isinstance(delivered, envelope_cls)
    assert delivered.lease_epoch == 1
    persisted = _jsonl(root / "admissions.jsonl")
    assert len(persisted) == 1 and persisted[0]["request"]["lease_epoch"] == 1

    # Each equality failure gets a fresh activated store so terminal replay cannot
    # bypass authorization. Every mismatch is rejected before admission/evidence/effect.
    from dataclasses import replace

    def _mutate_authority(req, repo):
        return replace(
            req,
            admission=replace(req.admission, roadmap_digest="0" * 64),
        )

    def _mutate_repository(req, repo):
        return replace(
            req,
            admission=replace(
                req.admission,
                canonical_repository_identity="f" * 64,
            ),
        )

    def _mutate_request_repository(req, repo):
        return replace(req, repo="f" * 64)

    def _mutate_branch(req, repo):
        return replace(req, branch="feat/not-the-transaction")

    def _mutate_owned_paths(req, repo):
        return replace(req, owned_paths=("a.py", "extra.py"))

    def _mutate_adapter_worktree(req, repo):
        return replace(
            req,
            admission=replace(req.admission, adapter_worktree=str(repo.parent)),
        )

    def _mutate_request_adapter_worktree(req, repo):
        return replace(req, adapter_worktree=str(repo.parent))

    mismatches = (
        ("authority", _mutate_authority),
        ("envelope-canonical-repository", _mutate_repository),
        ("request-canonical-repository", _mutate_request_repository),
        ("branch", _mutate_branch),
        ("owned-paths", _mutate_owned_paths),
        ("envelope-adapter-worktree", _mutate_adapter_worktree),
        ("request-adapter-worktree", _mutate_request_adapter_worktree),
    )
    for label, mutate in mismatches:
        case_repo, case_transaction, case_identity, case_root = _authorized_publish_fixture(
            tmp_path, name=f"broker-envelope-mismatch-{label}"
        )
        case_adapter = _CountingAdapter()
        case_store = _counting_store(case_root)
        case_service = _service(case_root, case_adapter, store=case_store)
        valid = _publish_transaction_request(
            case_identity, "feat/x", case_transaction, case_repo
        )
        invalid = mutate(valid, case_repo)
        assert invalid != valid, label
        with pytest.raises((PermissionError, RuntimeError, TypeError, ValueError)):
            case_service.execute(invalid)
        assert (case_store.admit_calls, case_store.admit_next_calls) == (0, 0), label
        assert case_store.replay() == (), label
        assert case_service.evidence_store.replay() == {}, label
        assert case_adapter.calls == [], label

    # An envelope for a NON-publish verb fails before admission.
    from phase_loop_runtime.convergence.contracts import BrokerRequest, BrokerVerb

    with pytest.raises((TypeError, ValueError)):
        service.execute(
            BrokerRequest(
                BrokerVerb.MERGE,
                _envelope(transaction, worktree, branch="feat/x"),
                identity,
                "feat/x", head, ("a.py",), adapter_worktree=str(worktree),
            )
        )
    assert store.admit_next_calls == 1, "the rejected verb allocated nothing"


# ===========================================================================
# Repository-visible adapter-start ownership fence (EC-FABPUB-8)
# ===========================================================================


@_requires_fabpub
def test_fabpub_shared_adapter_start_fence_blocks_competing_train_before_and_after_possible_provider_effect(
    tmp_path, request
):
    """Two trains, ONE repository store, different heads; A crashes after the shared marker.

    Nothing in this body writes the lists it asserts on: the owner record is read
    back off the shared evidence store, and the competing train's admission and
    adapter counters are incremented only by production reaching those seams.
    """
    nodeid = fabpub_this_nodeid(request)
    ownership = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.evidence", "AdapterStartOwnership"
    )
    read_owner = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.evidence", "read_adapter_start_owner"
    )
    fabpub_require(
        nodeid,
        ownership is not None and read_owner is not None,
        "AdapterStartOwnership.v1 / read_adapter_start_owner are absent; "
        "a competing train is fenced only by a train-local ADAPTER_STARTED projection",
    )

    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState

    for crash_point in ("before_provider_effect", "after_possible_provider_effect"):
        worktree, transaction_a, identity, root = _authorized_publish_fixture(
            tmp_path, name=f"owner-{crash_point}"
        )
        head_a = transaction_a.committed_head_sha

        # --- train A: crashes INSIDE the adapter, after the shared owner is durable.
        adapter_a = _CountingAdapter(explode=(crash_point == "after_possible_provider_effect"))
        store_a = _counting_store(root)
        service_a = _service(root, adapter_a, store=store_a)
        request_a = _publish_transaction_request(identity, "feat/x", transaction_a, worktree)
        if crash_point == "before_provider_effect":
            # Kill after the pre-admission owner is fsynced but before admission.
            with pytest.raises(_CrashInjected):
                _execute_with_crash(service_a, request_a, after="adapter_start_owner")
        else:
            outcome_a = service_a.execute(request_a)
            assert not outcome_a.accepted, "an interrupted provider effect is never accepted"

        # PRODUCTION wrote the shared owner; read it back off the shared store.
        owner = read_owner(root, repository_identity=identity)
        assert owner is not None, "the shared adapter-start owner must be durable before admission"
        assert owner.committed_head == head_a
        assert owner.owner_nonce, "the owner carries a fresh nonce"

        # --- train B: DIFFERENT head, same canonical repository store.
        adapter_b = _CountingAdapter()
        store_b = _counting_store(root)
        service_b = _service(root, adapter_b, store=store_b)
        transaction_b = _next_authorized_transaction(
            tmp_path,
            worktree,
            name=f"competitor-b-{crash_point}",
            branch=f"feat/b-{crash_point}",
            relative_path="b.py",
        )
        head_b = transaction_b.committed_head_sha
        request_b = _publish_transaction_request(
            identity, f"feat/b-{crash_point}", transaction_b, worktree
        )
        with pytest.raises((PermissionError, RuntimeError)):
            service_b.execute(request_b)
        assert (store_b.admit_calls, store_b.admit_next_calls) == (0, 0), (
            "a competing train must obtain ZERO admissions while an unsealed owner exists"
        )
        assert adapter_b.calls == [], "a competing train must make ZERO adapter calls"

        # The production execute/recovery entry promotes the unsealed owner to
        # PERMANENT ambiguity; the test never calls the lower primitive itself.
        promoted_key = getattr(request_a.admission, "idempotency_key", None) or getattr(
            request_a.admission, "transaction_id", ""
        )
        promoted = service_b.evidence_store.replay()[promoted_key]
        assert promoted.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
        assert any(
            row["state"] == "outcome_ambiguous_blocked" for row in _jsonl(root / "evidence.jsonl")
        ), "the permanent block must be durable on the shared evidence store"

        # Neither train-local cleanup, another attempt, nor another head clears it.
        adapter_c = _CountingAdapter()
        store_c = _counting_store(root)
        service_c = _service(root, adapter_c, store=store_c)
        transaction_c = _next_authorized_transaction(
            tmp_path,
            worktree,
            name=f"competitor-c-{crash_point}",
            branch=f"feat/c-{crash_point}",
            relative_path="c.py",
        )
        with pytest.raises((PermissionError, RuntimeError)):
            service_c.execute(
                _publish_transaction_request(
                    identity, f"feat/c-{crash_point}", transaction_c, worktree
                )
            )
        assert adapter_c.calls == [] and store_c.admit_next_calls == 0

    # POSITIVE CONTROL — this is what an always-block stub cannot satisfy: one
    # UNCONTENDED train acquires ownership and invokes the adapter exactly once.
    clean_repo, clean_transaction, clean_identity, clean_root = _authorized_publish_fixture(
        tmp_path, name="uncontended"
    )
    adapter_ok = _CountingAdapter()
    store_ok = _counting_store(clean_root)
    service_ok = _service(clean_root, adapter_ok, store=store_ok)
    outcome = service_ok.execute(
        _publish_transaction_request(clean_identity, "feat/x", clean_transaction, clean_repo)
    )
    assert outcome.accepted
    assert len(adapter_ok.calls) == 1 and store_ok.admit_next_calls == 1
    sealed = read_owner(clean_root, repository_identity=clean_identity)
    assert sealed is not None and getattr(sealed, "sealed", False), (
        "a completed effect must SEAL its owner so the next publish is not fenced"
    )


class _CrashInjected(RuntimeError):
    """Marks the deterministic kill point injected by :func:`_execute_with_crash`."""


def _execute_with_crash(service, request, *, after: str):
    """Run ``BrokerService.execute`` and kill it right after a named production step.

    The kill point is a PRODUCTION seam, not a test-local flag: the wrapper
    replaces the named durable-write function and raises once it has returned, so
    the record under test is already fsynced when the process 'dies'.
    """
    from phase_loop_runtime.convergence.broker import evidence as evidence_module

    original = getattr(evidence_module, {"adapter_start_owner": "append_adapter_start_owner"}[after])

    def crashing(*args, **kwargs):
        result = original(*args, **kwargs)
        raise _CrashInjected(after)

    setattr(evidence_module, {"adapter_start_owner": "append_adapter_start_owner"}[after], crashing)
    try:
        return service.execute(request)
    finally:
        setattr(evidence_module, {"adapter_start_owner": "append_adapter_start_owner"}[after], original)


# ===========================================================================
# Legacy cutover / quiescence / onboarding (EC-FABPUB-9, EC-FABPUB-10)
# ===========================================================================


def _cutover_symbol(name: str):
    return fabpub_symbol("phase_loop_runtime.convergence.broker.live", name)


def _cutover_ready() -> bool:
    return all(
        _cutover_symbol(name) is not None
        for name in (
            "LegacyBrokerCutoverManifest",
            "LegacyBrokerCutoverTransaction",
            "LegacyRepositoryPartitionReceipt",
            "run_legacy_broker_cutover",
        )
    )


def _manifest_row(ledger_dir: Path, train: Path, repo: Path, serialized: str, cwd: Path):
    return {
        "legacy_root": str(ledger_dir / "broker"),
        "serialized_repository": serialized,
        "serialized_repository_bytes_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "invocation_working_directory": str(cwd),
        "resolution_mode": "absolute" if serialized.startswith("/") else "workspace_argument_relative",
        "resolved_train_path": str(train.resolve()),
        "expected_train_key": hashlib.sha256(str(train.resolve()).encode("utf-8")).hexdigest()[:16],
        "expected_repo_key": hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16],
        "expected_worktree": str(repo),
    }


def _activate_repository_authorities(
    tmp_path: Path, repositories: tuple[tuple[Path, str], ...]
):
    """Activate one global zero-history cutover over all supplied repositories."""
    rows = []
    for repo, label in repositories:
        ledger = tmp_path / f"legacy-{label}"
        train = _write_train(tmp_path / f"train-{label}" / "release.md", str(repo))
        _seed_legacy_root(ledger, train_path=train, serialized_repo=str(repo), epochs=())
        rows.append(_manifest_row(ledger, train, repo, str(repo), tmp_path))
    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    transaction = _cutover_symbol("run_legacy_broker_cutover")(
        manifest_cls(
            cutover_id="fabpub-" + "-".join(label for _repo, label in repositories),
            rows=tuple(rows),
        )
    )
    assert transaction.state == "ARMED"
    transaction.activate()
    assert transaction.state == "ACTIVE"
    return {
        repo: (
            _cutover_symbol("canonical_repository_identity")(repo),
            Path(_cutover_symbol("repository_broker_namespace")(repo)),
        )
        for repo, _label in repositories
    }


def _activate_repository_authority(tmp_path: Path, repo: Path, *, label: str):
    """Activate one zero-history repository through the real cutover contract."""
    return _activate_repository_authorities(tmp_path, ((repo, label),))[repo]


@_requires_fabpub
def test_fabpub_legacy_cutover_preserves_high_water_before_activation(tmp_path, request):
    """The first post-cutover epoch is ``legacy_max + 1``, never 1."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _cutover_ready(),
        "LegacyBrokerCutoverTransaction.v2 / LegacyRepositoryPartitionReceipt.v2 are absent; "
        "a canonical store would start at epoch 1 and re-admit a stale publish",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    repo = _init_repo(tmp_path / "repo")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "repo")
    seeded = _seed_legacy_root(ledger, train_path=train, serialized_repo=str(repo), epochs=(1, 2, 7))

    run_cutover = _cutover_symbol("run_legacy_broker_cutover")
    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    manifest = manifest_cls(
        cutover_id="fabpub-cutover-0001",
        rows=(_manifest_row(ledger, train, repo, str(repo), tmp_path),),
    )
    transaction = run_cutover(manifest)
    assert transaction.state == "ARMED"

    receipt = transaction.receipt_for(repo)
    assert receipt.legacy_epoch_high_water == seeded["high_water"] == 7, (
        "the receipt must carry the authenticated legacy floor read off the seeded leaf"
    )

    namespace = Path(_cutover_symbol("repository_broker_namespace")(repo))
    store = _counting_store(namespace)

    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", f"k-{epoch}")

    first = store.admit_next(make, attempt_id="post-cutover", precondition=lambda: True)
    assert first.epoch == 8, f"first post-cutover epoch must be legacy_max+1; got {first.epoch}"

    # A stale presentation at a retired legacy epoch is refused.
    with pytest.raises(PermissionError):
        store.admit(AdmissionRequest("stale", 7, "fence", "digest", "predicate", "scope", "k-stale"))

    # The legacy leaf is RETIRED, not deleted: a tombstone replaces it and the
    # source moved into the archive.
    assert seeded["leaf"].is_file() or (seeded["leaf"] / "RETIRED").exists(), (
        "the legacy leaf must be replaced by a durable retirement tombstone"
    )
    assert list((ledger / "broker" / "legacy-archive").rglob("admissions.jsonl")), (
        "the legacy source must be archived, never deleted"
    )


@_requires_fabpub
def test_fabpub_legacy_cutover_replays_terminal_completed_effect_before_activation(tmp_path, request):
    """An authenticated legacy completed effect replays with zero admission/adapter."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _cutover_ready(),
        "no receipt-bound legacy archive view; a completed legacy effect would be re-executed",
    )

    from phase_loop_runtime.convergence.broker.verbs import publish_committed_branch_idempotency_key
    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    repo = _init_repo(tmp_path / "repo")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "repo")
    head = "a" * 40
    serialized = str(repo)
    legacy_key = f"publish_committed_branch\0{publish_committed_branch_idempotency_key(serialized, 'feat/x', head)}"
    _seed_legacy_root(
        ledger, train_path=train, serialized_repo=serialized, epochs=(1, 2),
        terminal=(legacy_key, "https://gh/pr/legacy-7"),
    )

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    transaction = _cutover_symbol("run_legacy_broker_cutover")(
        manifest_cls(cutover_id="fabpub-cutover-0001", rows=(_manifest_row(ledger, train, repo, serialized, tmp_path),))
    )
    assert transaction.state == "ARMED"

    namespace = Path(_cutover_symbol("repository_broker_namespace")(repo))
    identity = _cutover_symbol("canonical_repository_identity")(repo)
    adapter = _CountingAdapter()
    store = _counting_store(namespace)
    service = _service(namespace, adapter, store=store)

    outcome = service.execute(
        _publish_request(
            identity,
            "feat/x",
            head,
            AdmissionRequest("legacy-replay", 1, "fence", "digest", "predicate", identity, "key"),
            repo,
        )
    )
    assert outcome.accepted, "the promoted legacy terminal must replay as accepted"
    assert outcome.publish_result.pr_url == "https://gh/pr/legacy-7", (
        "the replay must return the ORIGINAL legacy effect reference"
    )
    assert (store.admit_calls, store.admit_next_calls) == (0, 0)
    assert adapter.calls == [], "an authenticated legacy replay never re-enters the provider"

    # Provenance is recorded on the promoted canonical record.
    promoted = [row for row in _jsonl(namespace / "evidence.jsonl") if row["state"] == "effect_terminal_observed"]
    assert promoted, "the canonical store must carry the promoted terminal"

    # POSITIVE CONTROL: a genuinely different head still reaches the provider once.
    transaction.activate()
    fresh = _next_authorized_transaction(
        tmp_path,
        repo,
        name="legacy-replay-fresh",
        branch="feat/fresh",
        relative_path="fresh.py",
    )
    other = fresh.committed_head_sha
    assert service.execute(
        _publish_transaction_request(identity, "feat/fresh", fresh, repo)
    ).accepted
    assert len(adapter.calls) == 1 and store.admit_next_calls == 1


@_requires_fabpub
def test_fabpub_legacy_cutover_preserves_outcome_ambiguous_block_before_activation(tmp_path, request):
    """Archived permanent ambiguity blocks ONLY its authenticated repository partition."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _cutover_ready(),
        "no receipt-bound legacy archive view; archived permanent ambiguity would be lost",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    poisoned = _init_repo(tmp_path / "poisoned")
    healthy = _init_repo(tmp_path / "healthy")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "poisoned")
    _seed_legacy_root(ledger, train_path=train, serialized_repo=str(poisoned), epochs=(1, 2), ambiguous=True)
    _seed_legacy_root(ledger, train_path=train, serialized_repo=str(healthy), epochs=(1,))

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    transaction = _cutover_symbol("run_legacy_broker_cutover")(
        manifest_cls(
            cutover_id="fabpub-cutover-0001",
            rows=(
                _manifest_row(ledger, train, poisoned, str(poisoned), tmp_path),
                _manifest_row(ledger, train, healthy, str(healthy), tmp_path),
            ),
        )
    )
    assert transaction.state == "ARMED"

    namespace_fn = _cutover_symbol("repository_broker_namespace")
    identity_fn = _cutover_symbol("canonical_repository_identity")

    poisoned_adapter = _CountingAdapter()
    poisoned_store = _counting_store(Path(namespace_fn(poisoned)))
    poisoned_service = _service(Path(namespace_fn(poisoned)), poisoned_adapter, store=poisoned_store)
    with pytest.raises(PermissionError):
        poisoned_service.execute(
            _publish_request(
                identity_fn(poisoned),
                "feat/x",
                "a" * 40,
                AdmissionRequest("legacy-block", 1, "fence", "digest", "predicate", str(poisoned), "key"),
                poisoned,
            )
        )
    assert poisoned_store.admit_next_calls == 0 and poisoned_adapter.calls == []

    # The BLAST RADIUS is exactly one repository partition.
    healthy_adapter = _CountingAdapter()
    healthy_store = _counting_store(Path(namespace_fn(healthy)))
    healthy_service = _service(Path(namespace_fn(healthy)), healthy_adapter, store=healthy_store)
    transaction.activate()
    healthy_transaction = _next_authorized_transaction(
        tmp_path,
        healthy,
        name="healthy-fresh",
        branch="feat/healthy",
        relative_path="healthy.py",
    )
    assert healthy_service.execute(
        _publish_transaction_request(
            identity_fn(healthy), "feat/healthy", healthy_transaction, healthy
        )
    ).accepted
    assert len(healthy_adapter.calls) == 1


@_requires_fabpub
def test_fabpub_legacy_cutover_conflict_collision_and_idempotent_resume_before_activation(
    tmp_path, request
):
    """Malformed history, collisions, and source recreation block; restart is idempotent."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _cutover_ready()
        and _cutover_symbol("crash_at_cutover_step") is not None,
        "LegacyBrokerCutoverTransaction.v2 / crash_at_cutover_step are absent; there is no "
        "journal to resume idempotently and no frozen kill point before/after each source "
        "retirement and partition write",
    )

    transaction_cls = _cutover_symbol("LegacyBrokerCutoverTransaction")
    assert tuple(transaction_cls.JOURNAL_STATES) == tuple(FABPUB_LEGACY_CUTOVER_VECTOR["journal_states"])

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    run_cutover = _cutover_symbol("run_legacy_broker_cutover")

    repo = _init_repo(tmp_path / "repo")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "repo")
    seeded = _seed_legacy_root(ledger, train_path=train, serialized_repo=str(repo), epochs=(1, 2, 3))
    rows = (_manifest_row(ledger, train, repo, str(repo), tmp_path),)

    # (1) MALFORMED history — a non-contiguous sequence blocks globally.
    good = seeded["admissions"].read_text(encoding="utf-8")
    seeded["admissions"].write_text(good.replace('"sequence": 2', '"sequence": 9'), encoding="utf-8")
    with pytest.raises(Exception) as bad_history:
        run_cutover(manifest_cls(cutover_id="c1", rows=rows))
    assert CUTOVER_BLOCKER in str(bad_history.value)
    seeded["admissions"].write_text(good, encoding="utf-8")

    # (2) UNCLAIMED leaf — an extra legacy child not covered by the manifest blocks.
    stray = seeded["leaf"].parent / ("f" * 16)
    stray.mkdir(parents=True, exist_ok=True)
    (stray / "admissions.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(Exception) as unclaimed:
        run_cutover(manifest_cls(cutover_id="c2", rows=rows))
    assert CUTOVER_BLOCKER in str(unclaimed.value)
    subprocess.run(["rm", "-rf", str(stray)], check=True, timeout=60)

    # (3) CRASH BEFORE AND AFTER EVERY source retirement and partition write.
    # plan:220 requires kills at each boundary, each resuming idempotently to ONE
    # byte-identical logical ARMED with no duplicate move, row, or receipt.
    crash_at = _cutover_symbol("crash_at_cutover_step")
    assert crash_at is not None, "the cutover must expose its frozen kill points"
    reference = run_cutover(manifest_cls(cutover_id="ref", rows=rows))
    assert reference.state == "ARMED"
    reference_journal = reference.journal_path.read_bytes()
    reference_archives = sorted(
        path.name for path in (ledger / "broker" / "legacy-archive").rglob("admissions.jsonl")
    )

    for step in (
        "before_source_retirement",
        "after_source_retirement",
        "before_partition_write",
        "after_partition_write",
        "before_armed",
    ):
        step_repo = _init_repo(tmp_path / f"repo-{step}")
        killed_ledger = tmp_path / f"ledger-{step}"
        killed_train = _write_train(tmp_path / f"trains-{step}" / "release.md", str(step_repo))
        _seed_legacy_root(
            killed_ledger, train_path=killed_train, serialized_repo=str(step_repo), epochs=(1, 2, 3)
        )
        killed_rows = (_manifest_row(killed_ledger, killed_train, step_repo, str(step_repo), tmp_path),)
        cutover_id = f"k-{step}"
        with crash_at(step):
            with pytest.raises(Exception):
                run_cutover(manifest_cls(cutover_id=cutover_id, rows=killed_rows))
        # Resume after the kill: the SAME cutover_id must reach ARMED idempotently.
        resumed = run_cutover(manifest_cls(cutover_id=cutover_id, rows=killed_rows))
        assert resumed.state == "ARMED", f"{step}: resume must reach ARMED"
        assert resumed.journal_path.read_bytes().count(b"ARMED") == 1, (
            f"{step}: the journal must record ARMED exactly once"
        )
        archives = sorted(
            path.name
            for path in (killed_ledger / "broker" / "legacy-archive").rglob("admissions.jsonl")
        )
        assert archives == reference_archives, f"{step}: duplicate or missing archive move"
        namespace = Path(_cutover_symbol("repository_broker_namespace")(step_repo))
        assert len(list(namespace.glob("partition-receipt*.json"))) == 1, (
            f"{step}: exactly one partition receipt survives the kill/resume"
        )


    # A restart with the same cutover_id on the already-ARMED reference is a no-op.
    again = run_cutover(manifest_cls(cutover_id="ref", rows=rows))
    assert again.state == "ARMED"
    assert again.journal_path.read_bytes() == reference_journal, (
        "resume must reach the same logical ARMED bytes"
    )
    first = reference

    def fresh_adversary(name):
        case_repo = _init_repo(tmp_path / f"adversary-repo-{name}")
        case_ledger = tmp_path / f"adversary-ledger-{name}"
        case_train = _write_train(
            tmp_path / f"adversary-train-{name}" / "release.md", str(case_repo)
        )
        case_seeded = _seed_legacy_root(
            case_ledger,
            train_path=case_train,
            serialized_repo=str(case_repo),
            epochs=(1, 2, 3),
        )
        case_rows = (
            _manifest_row(case_ledger, case_train, case_repo, str(case_repo), tmp_path),
        )
        return case_repo, case_ledger, case_seeded, case_rows

    # (3b) TRUNCATED-HASH COLLISION: two distinct serialized preimages whose declared
    # 16-hex repo keys collide must block rather than silently merge partitions.  This
    # uses a fresh unretired source, so a prior cutover-id conflict cannot satisfy it.
    _, _, _, collision_rows = fresh_adversary("collision")
    collided = list(collision_rows)
    collided.append(dict(collision_rows[0], serialized_repository="other-preimage"))
    collided[1]["expected_repo_key"] = collision_rows[0]["expected_repo_key"]
    with pytest.raises(Exception) as collision:
        run_cutover(manifest_cls(cutover_id="c-collision", rows=tuple(collided)))
    assert CUTOVER_BLOCKER in str(collision.value)

    # (3c) PATH ESCAPE: a legacy root or leaf that escapes its declared root via
    # `..` or a symlink must block before any move.  Each arm starts unretired.
    _, escape_ledger, _, escape_rows = fresh_adversary("dotdot")
    escape_root = tmp_path / "escape"
    escape_root.mkdir(exist_ok=True)
    escaped = list(escape_rows)
    escaped[0] = dict(
        escape_rows[0], legacy_root=str(escape_ledger / "broker" / ".." / "broker")
    )
    with pytest.raises(Exception) as escape:
        run_cutover(manifest_cls(cutover_id="c-escape", rows=tuple(escaped)))
    assert CUTOVER_BLOCKER in str(escape.value)

    _, symlink_ledger, _, symlink_rows = fresh_adversary("symlink")
    symlinked = symlink_ledger / "broker" / "symlinked-leaf"
    if not symlinked.exists():
        symlinked.symlink_to(escape_root, target_is_directory=True)
    with pytest.raises(Exception) as symlink_escape:
        run_cutover(manifest_cls(cutover_id="c-symlink", rows=symlink_rows))
    assert CUTOVER_BLOCKER in str(symlink_escape.value)
    symlinked.unlink()

    # (3d) UNATTESTED CANONICAL ROW: a canonical admission that no receipt authorises
    # must block; the cutover may never adopt state it did not migrate.  Again, no
    # earlier cutover has retired this source or occupied its transaction ID.
    unattested_repo, _, _, unattested_rows = fresh_adversary("unattested")
    unattested_ns = Path(_cutover_symbol("repository_broker_namespace")(unattested_repo))
    unattested_ns.mkdir(parents=True, exist_ok=True)
    (unattested_ns / "admissions.jsonl").write_text(
        json.dumps(
            {
                "sequence": 1,
                "epoch": 99,
                "request": {
                    "attempt_id": "unattested", "lease_epoch": 99, "fence_token": "f",
                    "approval_digest": "d", "expected_version_predicate": "p",
                    "authority_domain_scope": "s", "idempotency_key": "unattested",
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception) as unattested:
        run_cutover(manifest_cls(cutover_id="c-unattested", rows=unattested_rows))
    assert CUTOVER_BLOCKER in str(unattested.value)
    (unattested_ns / "admissions.jsonl").unlink()

    # (4) SOURCE RECREATION after retirement blocks rather than silently re-migrating.
    seeded["leaf"].parent.mkdir(parents=True, exist_ok=True)
    recreated = seeded["leaf"] if seeded["leaf"].is_dir() else seeded["leaf"].parent / seeded["repo_key"]
    subprocess.run(["rm", "-rf", str(recreated)], check=True, timeout=60)
    recreated.mkdir(parents=True, exist_ok=True)
    (recreated / "admissions.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(Exception) as recreated_error:
        run_cutover(manifest_cls(cutover_id="c3", rows=rows))
    assert CUTOVER_BLOCKER in str(recreated_error.value)

    # (5) A DIFFERENT cutover_id against already-retired sources blocks too.
    with pytest.raises(Exception) as wrong_id:
        run_cutover(manifest_cls(cutover_id="c4", rows=rows))
    assert CUTOVER_BLOCKER in str(wrong_id.value)


@_requires_fabpub
def test_fabpub_legacy_cutover_preserves_exact_serialized_repo_preimages_and_resolution_context_before_activation(
    tmp_path, request
):
    """Two textually distinct but contextually equivalent strings map to one repository."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _cutover_ready(),
        "LegacyBrokerCutoverManifest.v2 is absent; the exact historical serialized "
        "repository preimage and its resolution context are unrecorded",
    )

    repo = _init_repo(tmp_path / "repo")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "repo")

    absolute = str(repo)
    relative = "repo"
    # Two leaves, DIFFERENT legacy repo keys, ONE canonical repository.
    left = _seed_legacy_root(ledger, train_path=train, serialized_repo=absolute, epochs=(1, 4))
    right = _seed_legacy_root(ledger, train_path=train, serialized_repo=relative, epochs=(1, 9))
    assert left["repo_key"] != right["repo_key"], "the exact serialized bytes keep distinct legacy keys"

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    run_cutover = _cutover_symbol("run_legacy_broker_cutover")
    rows = (
        _manifest_row(ledger, train, repo, absolute, tmp_path),
        _manifest_row(ledger, train, repo, relative, tmp_path),
    )
    transaction = run_cutover(manifest_cls(cutover_id="c1", rows=rows))
    assert transaction.state == "ARMED"

    receipt = transaction.receipt_for(repo)
    assert receipt.legacy_epoch_high_water == 9, "both preimages fold into ONE partition floor"
    assert sorted(receipt.serialized_repository_preimages) == sorted((absolute, relative))

    # Changing the recorded CWD breaks the relative row's resolution and blocks.
    wrong_cwd = list(rows)
    wrong_cwd[1] = dict(rows[1], invocation_working_directory=str(tmp_path / "elsewhere"))
    with pytest.raises(Exception) as cwd_error:
        run_cutover(manifest_cls(cutover_id="c2", rows=tuple(wrong_cwd)))
    assert CUTOVER_BLOCKER in str(cwd_error.value)

    # Changing the resolution mode blocks.
    wrong_mode = list(rows)
    wrong_mode[1] = dict(rows[1], resolution_mode="absolute")
    with pytest.raises(Exception) as mode_error:
        run_cutover(manifest_cls(cutover_id="c3", rows=tuple(wrong_mode)))
    assert CUTOVER_BLOCKER in str(mode_error.value)

    # Recomputing a legacy key from the RESOLVED path instead of the exact bytes blocks.
    aliased = list(rows)
    aliased[1] = dict(rows[1], expected_repo_key=left["repo_key"])
    with pytest.raises(Exception) as alias_error:
        run_cutover(manifest_cls(cutover_id="c4", rows=tuple(aliased)))
    assert CUTOVER_BLOCKER in str(alias_error.value)


@_requires_fabpub
def test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation(
    tmp_path, request
):
    """One train root, several repositories: disjoint receipts, crash-idempotent ARMED."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _cutover_ready(),
        "no global cutover transaction; a per-repository receipt cannot inventory a shared "
        "train root holding leaves for several repositories",
    )

    alpha = _init_repo(tmp_path / "alpha")
    beta = _init_repo(tmp_path / "beta")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "alpha")
    _seed_legacy_root(ledger, train_path=train, serialized_repo=str(alpha), epochs=(1, 5))
    _seed_legacy_root(ledger, train_path=train, serialized_repo=str(beta), epochs=(1, 2), ambiguous=True)

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    run_cutover = _cutover_symbol("run_legacy_broker_cutover")
    rows = (
        _manifest_row(ledger, train, alpha, str(alpha), tmp_path),
        _manifest_row(ledger, train, beta, str(beta), tmp_path),
    )

    # A manifest that omits one repository leaves an unclaimed leaf → global block.
    with pytest.raises(Exception) as partial:
        run_cutover(manifest_cls(cutover_id="c1", rows=(rows[0],)))
    assert CUTOVER_BLOCKER in str(partial.value)

    # Two FRESH processes race complete, overlapping, digest-distinct manifests.
    # Neither is handed a transaction path: production must rendezvous through its
    # one well-known durable global authority and permit exactly one winner.
    race_program = """
        import json, os, sys, time
        from pathlib import Path
        from phase_loop_runtime.convergence.broker import live

        manifest_payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        start = Path(sys.argv[2])
        while not start.exists():
            time.sleep(0.01)
        try:
            manifest = live.LegacyBrokerCutoverManifest(**manifest_payload)
            transaction = live.run_legacy_broker_cutover(manifest)
            print(json.dumps({
                "status": "won",
                "cutover_id": manifest_payload["cutover_id"],
                "state": transaction.state,
                "journal_path": str(transaction.journal_path.resolve()),
                "journal_sha256": __import__("hashlib").sha256(
                    transaction.journal_path.read_bytes()
                ).hexdigest(),
            }, sort_keys=True))
        except Exception as error:
            print(json.dumps({
                "status": "blocked",
                "cutover_id": manifest_payload["cutover_id"],
                "error": str(error),
            }, sort_keys=True))
    """
    race_dir = tmp_path / "cutover-race"
    race_dir.mkdir()
    manifests = []
    for cutover_id in ("c2-racer-a", "c2-racer-b"):
        path = race_dir / f"{cutover_id}.json"
        path.write_text(
            json.dumps({"cutover_id": cutover_id, "rows": rows}, sort_keys=True),
            encoding="utf-8",
        )
        manifests.append(path)
    start = race_dir / "start"
    race_env = dict(os.environ)
    race_env["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_SRC), race_env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    race_env[FABPUB_ACTIVATION_ENV] = "1"
    racers = [
        subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(race_program), str(path), str(start)],
            cwd=str(tmp_path),
            env=race_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for path in manifests
    ]
    start.write_text("go\n", encoding="ascii")
    race_results = []
    for racer in racers:
        stdout, stderr = racer.communicate(timeout=120)
        assert racer.returncode == 0, stderr
        race_results.append(json.loads(stdout.strip().splitlines()[-1]))
    winners = [result for result in race_results if result["status"] == "won"]
    losers = [result for result in race_results if result["status"] == "blocked"]
    assert len(winners) == len(losers) == 1, race_results
    assert CUTOVER_BLOCKER in losers[0]["error"]

    # A third fresh process, given only the winning metadata manifest, discovers
    # and resumes the same durable authority byte-for-byte.
    winning_manifest = manifests[
        ("c2-racer-a", "c2-racer-b").index(winners[0]["cutover_id"])
    ]
    replay = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(race_program), str(winning_manifest), str(start)],
        cwd=str(tmp_path),
        env=race_env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert replay.returncode == 0, replay.stderr
    replay_result = json.loads(replay.stdout.strip().splitlines()[-1])
    assert replay_result == winners[0]

    transaction = run_cutover(
        manifest_cls(cutover_id=winners[0]["cutover_id"], rows=rows)
    )
    assert transaction.state == "ARMED"

    namespace_fn = _cutover_symbol("repository_broker_namespace")
    alpha_receipt = transaction.receipt_for(alpha)
    beta_receipt = transaction.receipt_for(beta)
    assert alpha_receipt.legacy_epoch_high_water == 5
    assert beta_receipt.legacy_epoch_high_water == 2
    assert Path(namespace_fn(alpha)) != Path(namespace_fn(beta)), "target namespaces are disjoint"
    assert alpha_receipt.ambiguous is False and beta_receipt.ambiguous is True, (
        "each partition keeps its own ambiguity state"
    )

    # CRASH-IDEMPOTENT resume: rerunning the same cutover_id reproduces the same
    # journal bytes and duplicates neither archive moves nor receipts.
    journal = transaction.journal_path.read_bytes()
    resumed = run_cutover(
        manifest_cls(cutover_id=winners[0]["cutover_id"], rows=rows)
    )
    assert resumed.state == "ARMED"
    assert resumed.journal_path.read_bytes() == journal
    receipts = list(Path(namespace_fn(alpha)).glob("partition-receipt*.json"))
    assert len(receipts) == 1, "a resumed cutover writes exactly one receipt per partition"

    # KILL AT EVERY MULTI-REPOSITORY RETIREMENT AND PARTITION WRITE (plan:220).
    # With TWO repositories under one train root, a kill between alpha's and beta's
    # retirement — or between their partition writes — must resume to one
    # byte-identical logical ARMED with no duplicate move, row, receipt, or effect.
    crash_at = _cutover_symbol("crash_at_cutover_step")
    assert crash_at is not None
    for step in (
        "before_source_retirement",
        "between_source_retirements",
        "after_source_retirement",
        "before_partition_write",
        "between_partition_writes",
        "after_partition_write",
    ):
        step_alpha = _init_repo(tmp_path / f"alpha-{step}")
        step_beta = _init_repo(tmp_path / f"beta-{step}")
        killed_ledger = tmp_path / f"multi-{step}"
        killed_train = _write_train(tmp_path / f"multi-trains-{step}" / "release.md", str(step_alpha))
        _seed_legacy_root(
            killed_ledger, train_path=killed_train, serialized_repo=str(step_alpha), epochs=(1, 5)
        )
        _seed_legacy_root(
            killed_ledger, train_path=killed_train, serialized_repo=str(step_beta), epochs=(1, 2),
            ambiguous=True,
        )
        killed_rows = (
            _manifest_row(killed_ledger, killed_train, step_alpha, str(step_alpha), tmp_path),
            _manifest_row(killed_ledger, killed_train, step_beta, str(step_beta), tmp_path),
        )
        cutover_id = f"m-{step}"
        with crash_at(step):
            with pytest.raises(Exception):
                run_cutover(manifest_cls(cutover_id=cutover_id, rows=killed_rows))
        recovered = run_cutover(manifest_cls(cutover_id=cutover_id, rows=killed_rows))
        assert recovered.state == "ARMED", f"{step}: resume must reach ARMED"
        assert recovered.journal_path.read_bytes().count(b"ARMED") == 1, (
            f"{step}: ARMED recorded exactly once"
        )
        assert recovered.receipt_for(step_alpha).legacy_epoch_high_water == 5, f"{step}: alpha floor"
        assert recovered.receipt_for(step_beta).legacy_epoch_high_water == 2, f"{step}: beta floor"
        assert recovered.receipt_for(step_beta).ambiguous is True, f"{step}: beta ambiguity preserved"
        for partition in (step_alpha, step_beta):
            partition_ns = Path(namespace_fn(partition))
            assert len(list(partition_ns.glob("partition-receipt*.json"))) == 1, (
                f"{step}: exactly one receipt for {partition.name}"
            )
        archives = list((killed_ledger / "broker" / "legacy-archive").rglob("admissions.jsonl"))
        assert len(archives) == 2, f"{step}: exactly one archive move per repository"



@_requires_fabpub
def test_fabpub_legacy_writer_quiescence_blocks_armed_activation_and_fences_supported_restarts(
    tmp_path, request
):
    """A live pre-FABPUB writer makes DRAINING/ARMED/activation refuse with zero effect."""
    nodeid = fabpub_this_nodeid(request)
    quiescence = _cutover_symbol("LegacyWriterQuiescence")
    latch = _cutover_symbol("WriterGenerationLatch")
    fabpub_require(
        nodeid,
        quiescence is not None
        and latch is not None
        and _cutover_ready()
        and _cutover_symbol("LegacyWriterQuiescence.inventory") is not None,
        "LegacyWriterQuiescence.v1 / its launcher-supervisor inventory / "
        "WriterGenerationLatch.v1 are absent; a pre-FABPUB writer can create a late legacy "
        "repository after inventory sealing, and neither root injection nor a check/use "
        "race is fenced",
    )
    assert tuple(latch.GENERATION_STATES) == tuple(FABPUB_LEGACY_CUTOVER_VECTOR["generation_states"])

    repo = _init_repo(tmp_path / "repo")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "repo")
    _seed_legacy_root(ledger, train_path=train, serialized_repo=str(repo), epochs=(1, 2))

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    run_cutover = _cutover_symbol("run_legacy_broker_cutover")
    rows = (_manifest_row(ledger, train, repo, str(repo), tmp_path),)

    # Hold the real predecessor `phase-loop run-train` route alive in a fresh
    # process.  The probe pauses inside the ordinary preflight only after entering
    # the public run_train boundary; it never constructs a latch itself.  Cutover
    # must discover and drain that supported writer rather than trusting a
    # test-created lease.
    writer_ready = tmp_path / "writer-ready"
    writer_release = tmp_path / "writer-release"
    hook_dir = tmp_path / "writer-probe-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import os, time
            from pathlib import Path
            from phase_loop_runtime import train_runner

            def hold_current_predecessor(*args, **kwargs):
                ready = Path(os.environ["FABPUB_WRITER_READY"])
                release = Path(os.environ["FABPUB_WRITER_RELEASE"])
                ready.write_text(str(os.getpid()) + "\\n", encoding="ascii")
                while not release.exists():
                    time.sleep(0.02)
                return ["intentional predecessor probe stop"]

            train_runner._default_preflight = hold_current_predecessor
            """
        ),
        encoding="utf-8",
    )
    phase_loop_entrypoint = shutil.which("phase-loop")
    assert phase_loop_entrypoint is not None, "the shipped phase-loop CLI entrypoint is unavailable"
    writer_env = dict(os.environ)
    writer_env["PYTHONPATH"] = os.pathsep.join(
        [str(hook_dir), str(RUNTIME_SRC), writer_env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    writer_env["FABPUB_WRITER_READY"] = str(writer_ready)
    writer_env["FABPUB_WRITER_RELEASE"] = str(writer_release)
    writer = subprocess.Popen(
        [phase_loop_entrypoint, "run-train", "--train", str(train)],
        cwd=str(tmp_path),
        env=writer_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(500):
            if writer_ready.exists():
                break
            assert writer.poll() is None, writer.stderr.read() if writer.stderr else "writer exited"
            __import__("time").sleep(0.01)
        assert writer_ready.exists(), "the predecessor CLI did not reach its production run_train entry"
        writer_pid = int(writer_ready.read_text(encoding="ascii").strip())

        inventory = quiescence.inventory(repo)
        matching = [
            entry
            for entry in inventory.writers
            if str(writer_pid) in json.dumps(entry, sort_keys=True)
        ]
        assert matching, "inventory did not bind the live predecessor run-train process"
        assert any(entry["surface"] == "phase_loop_run_train_command" for entry in matching)

        # An UNDRAINED predecessor writer refuses cutover before inventory can seal.
        with pytest.raises(Exception) as blocked:
            run_cutover(manifest_cls(cutover_id="c1", rows=rows))
        assert GENERATION_BLOCKER in str(blocked.value) or CUTOVER_BLOCKER in str(blocked.value)
        namespace = Path(_cutover_symbol("repository_broker_namespace")(repo))
        assert not (namespace / "admissions.jsonl").exists(), "zero canonical admission before drain"
        live_writer_states = []
        for candidate in tmp_path.rglob("*"):
            if not candidate.is_file():
                continue
            for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    state = json.loads(line).get("state")
                except (AttributeError, json.JSONDecodeError):
                    continue
                if state in ("INVENTORY_SEALED", "ARMED", "ACTIVE"):
                    live_writer_states.append((str(candidate), state))
        assert live_writer_states == [], (
            "a live predecessor must block before INVENTORY_SEALED, ARMED, or ACTIVE; "
            f"observed {live_writer_states}"
        )
    finally:
        writer_release.write_text("release\n", encoding="ascii")
        stdout, stderr = writer.communicate(timeout=120)
        assert writer.returncode == 1, f"predecessor CLI failed unexpectedly:\n{stdout}\n{stderr}"
        assert "intentional predecessor probe stop" in stderr

    # After exact quiescence the cutover ARMS.
    latch_state = latch.open(repo)
    transaction = run_cutover(manifest_cls(cutover_id="c1", rows=rows))
    assert transaction.state == "ARMED"
    journal_states = [
        json.loads(line)["state"]
        for line in transaction.journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert journal_states.index("INVENTORY_SEALED") < journal_states.index("ARMED")

    # A stale/legacy generation is fenced from every supported entry AFTER DRAINING.
    with pytest.raises(Exception) as fenced:
        latch_state.acquire(generation="legacy")
    assert GENERATION_BLOCKER in str(fenced.value)

    # LAUNCHER / SUPERVISOR INVENTORY (plan:221).  Quiescence must enumerate every
    # supported restart surface — the phase-loop `run-train` command, the direct
    # `run_train` entry, and the shipped skill aliases — and bind each discovered
    # writer's launcher/module/entrypoint identity.  An UNMANAGED source copy is not
    # claimed fenceable: discovering one blocks rather than creating an exception.
    inventory = quiescence.inventory(repo)
    surfaces = {entry["surface"] for entry in inventory.writers}
    for required in ("phase_loop_run_train_command", "direct_run_train_entry", "skill_alias"):
        assert required in surfaces, f"quiescence omits the {required} restart surface"
    for entry in inventory.writers:
        for binding in ("process_identity", "module_digest", "entrypoint_digest", "host", "launcher"):
            assert entry.get(binding), f"{entry['surface']} omits its {binding} binding"
    assert inventory.supervisors, "the supervisor inventory must not be empty"

    unmanaged = tmp_path / "unmanaged-copy"
    unmanaged.mkdir(exist_ok=True)
    (unmanaged / "run_train.py").write_text("# an arbitrary unmanaged source copy\n", encoding="utf-8")
    with pytest.raises(Exception) as unmanaged_error:
        quiescence.inventory(repo, extra_search_paths=(unmanaged,)).require_fenceable()
    assert GENERATION_BLOCKER in str(unmanaged_error.value) or "unmanaged" in str(unmanaged_error.value)

    # EVIDENCE-STORE / ROOT INJECTION: an activated production route may not accept a
    # caller-supplied allocator or evidence root.
    builder = _cutover_symbol("build_routing_broker_client")
    with pytest.raises(Exception) as injected:
        builder(broker_root=tmp_path / "injected-root")
    assert "root" in str(injected.value).lower() or CUTOVER_BLOCKER in str(injected.value)
    assert not (tmp_path / "injected-root").exists(), "a refused injection creates no directory"

    # CHECK/USE RACE: a generation validated at entry but revoked before the append
    # must fail at the APPEND, not merely at the entry check.
    namespace = Path(_cutover_symbol("repository_broker_namespace")(repo))
    racing_store = _counting_store(namespace)
    racing_lease = latch_state.acquire(generation=latch_state.read().generation)
    latch_state.begin_draining()
    with pytest.raises(Exception) as race_error:
        racing_store.admit_next(
            lambda epoch, attempt_id: __import__(
                "phase_loop_runtime.convergence.contracts", fromlist=["AdmissionRequest"]
            ).AdmissionRequest(attempt_id, epoch, "f", "d", "p", "s", "k"),
            attempt_id="raced",
            precondition=lambda: True,
        )
    assert GENERATION_BLOCKER in str(race_error.value)
    assert _jsonl(namespace / "admissions.jsonl") == [], "a raced generation appends nothing"
    racing_lease.release()
    with pytest.raises(Exception) as rollback_error:
        latch_state.rollback()
    assert "ARMED" in str(rollback_error.value) or "rollback" in str(rollback_error.value).lower()

    # POSITIVE CONTROL: the current canonical generation still gets a lease.
    current = latch_state.acquire(generation=latch_state.read().generation)
    assert current is not None
    current.release()


@_requires_fabpub
def test_fabpub_post_armed_zero_legacy_repository_onboarding_is_serialized_and_fail_closed(
    tmp_path, request
):
    """A repository first seen after ACTIVE onboards exactly once, never by empty-store fallback."""
    nodeid = fabpub_this_nodeid(request)
    onboard = _cutover_symbol("onboard_zero_legacy_repository")
    fabpub_require(
        nodeid,
        onboard is not None
        and _cutover_ready()
        and _cutover_symbol("inject_before_onboarding_seal") is not None,
        "no serialized post-ACTIVE onboarding contract or pre-seal boundary seam; a "
        "repository first seen later would be admitted by an empty-store fallback and no "
        "late tombstone/receipt injection could be falsified",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    known = _init_repo(tmp_path / "known")
    fresh = _init_repo(tmp_path / "fresh")
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", "known")
    _seed_legacy_root(ledger, train_path=train, serialized_repo=str(known), epochs=(1, 3))

    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    transaction = _cutover_symbol("run_legacy_broker_cutover")(
        manifest_cls(cutover_id="c1", rows=(_manifest_row(ledger, train, known, str(known), tmp_path),))
    )
    assert transaction.state == "ARMED"
    transaction.activate()
    assert transaction.state == "ACTIVE"

    namespace = Path(_cutover_symbol("repository_broker_namespace")(fresh))

    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", f"k-{attempt_id}")

    # Admission BEFORE the receipt seals is refused — no empty-store fallback.
    store = _counting_store(namespace)
    with pytest.raises((PermissionError, ValueError)):
        store.admit_next(make, attempt_id="premature", precondition=lambda: True)
    assert not (namespace / "admissions.jsonl").exists() or _jsonl(namespace / "admissions.jsonl") == []

        # TWO RACING NORMAL CLI TRAINS (plan:220, EC-FABPUB-10).  Both are fresh
    # processes running the real shipped CLI argv path against the same
    # never-before-seen repository; they must serialize to ONE byte-equivalent
    # zero-high-water receipt and ONE monotonic first epoch.
    import concurrent.futures

    _make_cli_publishable(fresh, "feat/onboard")
    alpha = _write_train(tmp_path / "trains-alpha" / "release.md", str(fresh))
    beta = _write_train(tmp_path / "trains-beta" / "release.md", str(fresh))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_cli_allocator_probe, train, fresh, "a" * 40, "b" * 40)
            for train in (alpha, beta)
        ]
        probes = [future.result(timeout=300) for future in futures]

    for probe in probes:
        assert probe["cli_exit"] == 0
        assert "broker_root" not in (probe["builder_kwargs"] or [])
    assert probes[0]["namespace"] == probes[1]["namespace"] == str(namespace)
    assert probes[0]["identity"] == probes[1]["identity"]
    assert probes[0]["coordinator_root"] != probes[1]["coordinator_root"], (
        "racing trains keep DISTINCT train-local coordinator roots"
    )

    receipts = list(namespace.glob("partition-receipt*.json"))
    assert len(receipts) == 1, "a racing onboarding must not write a second receipt"
    receipt_payload = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt_payload["legacy_epoch_high_water"] == 0, "a zero-legacy onboarding floor"
    assert receipt_payload.get("zero_source_proof"), "the receipt carries its zero-source proof"

    epochs = [row["epoch"] for row in _jsonl(namespace / "admissions.jsonl")]
    assert epochs == sorted(set(epochs)) and epochs[0] == 1, (
        f"the racing trains must produce ONE monotonic first epoch; got {epochs}"
    )
    assert len(epochs) == len(set(epochs)), "no duplicate epoch under the onboarding race"

    # A direct helper call after the race is a byte-equivalent no-op.
    again = onboard(fresh)
    assert again.legacy_epoch_high_water == 0
    assert len(list(namespace.glob("partition-receipt*.json"))) == 1

    # LATE PRE-SEAL BOUNDARY INJECTIONS (plan:220).  At every boundary BEFORE the
    # receipt seals, injecting a matching legacy source, archive, retirement
    # tombstone, or prior receipt must fail closed with zero directory, admission,
    # and provider effect.
    inject_at = _cutover_symbol("inject_before_onboarding_seal")
    assert inject_at is not None, "onboarding must expose its frozen pre-seal boundaries"
    another = _init_repo(tmp_path / "another")
    another_ns = Path(_cutover_symbol("repository_broker_namespace")(another))

    for boundary in ("before_zero_source_proof", "before_receipt_write", "before_receipt_fsync"):
        for injection in ("legacy_source", "archive", "retirement_tombstone", "prior_receipt"):
            with inject_at(boundary, injection):
                with pytest.raises(Exception) as injected_error:
                    onboard(another)
            assert CUTOVER_BLOCKER in str(injected_error.value), (
                f"{boundary}/{injection} must fail closed"
            )
            assert not list(another_ns.glob("partition-receipt*.json")), (
                f"{boundary}/{injection} sealed a receipt anyway"
            )
            assert _jsonl(another_ns / "admissions.jsonl") == [], (
                f"{boundary}/{injection} produced an admission"
            )

    # With no injection the same repository onboards cleanly — the reached positive arm.
    clean_receipt = onboard(another)
    assert clean_receipt.legacy_epoch_high_water == 0
    assert len(list(another_ns.glob("partition-receipt*.json"))) == 1

    # Late legacy evidence appearing for an already-onboarded repository fails closed.
    late = _seed_legacy_root(ledger, train_path=train, serialized_repo=str(fresh), epochs=(1, 6))
    assert late["leaf"].exists()
    with pytest.raises(Exception) as late_error:
        onboard(fresh)
    assert CUTOVER_BLOCKER in str(late_error.value)


# ===========================================================================
# Post-activation writer-generation fence (EC-FABPUB-9)
# ===========================================================================


@_requires_fabpub
def test_fabpub_post_activation_writer_generation_fence_blocks_direct_and_old_cli_restarts(
    tmp_path, request
):
    """DRAINING waits for an in-flight writer; ACTIVE fences every stale entry."""
    nodeid = fabpub_this_nodeid(request)
    latch = _cutover_symbol("WriterGenerationLatch")
    lease = _cutover_symbol("WriterGenerationLease")
    exclusive_lease = _cutover_symbol("ExclusiveActivationLease")
    force_generation = _cutover_symbol("force_writer_generation")
    crash_at = _cutover_symbol("crash_at_cutover_step")
    quiescence = _cutover_symbol("LegacyWriterQuiescence")
    restart_supervisor = _cutover_symbol("restart_legacy_supervisor")
    fabpub_require(
        nodeid,
        latch is not None
        and lease is not None
        and exclusive_lease is not None
        and force_generation is not None,
        "WriterGenerationLatch.v1 / WriterGenerationLease.v1 / ExclusiveActivationLease.v1 / "
        "force_writer_generation are absent; an already-running or restarted pre-FABPUB / direct "
        "run_train writer is unfenced after activation and the stale-restart arm cannot be driven",
    )
    assert latch.STALE_GENERATION_BLOCKER == GENERATION_BLOCKER

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    repo = _init_repo(tmp_path / "repo")
    latch_state = latch.open(repo)
    assert latch_state.read().state == "LEGACY_OPEN"

    # EXCLUSIVE ACTIVATION LEASE (C3b): held through migration (DRAINING -> ARMED -> ACTIVE)
    activation_lease = exclusive_lease.acquire(repo)
    assert activation_lease is not None

    # (1) DRAINING WAITS for an in-flight legacy writer and creates no late leaf.
    held = latch_state.acquire(generation="legacy")
    latch_state.begin_draining()
    assert latch_state.read().state == "DRAINING"
    with pytest.raises(Exception) as during_drain:
        latch_state.await_quiescent(timeout=0.2)
    assert GENERATION_BLOCKER in str(during_drain.value) or "DRAINING" in str(during_drain.value)
    with pytest.raises(Exception) as new_legacy:
        latch_state.acquire(generation="legacy")
    assert GENERATION_BLOCKER in str(new_legacy.value)

    # ROLLBACK MATRIX (C3b): even pre-mutation DRAINING may roll back only after
    # every legacy lease is gone.
    with pytest.raises(Exception) as leased_rollback:
        latch_state.rollback()
    assert GENERATION_BLOCKER in str(leased_rollback.value) or "lease" in str(
        leased_rollback.value
    ).lower()
    held.release()
    latch_state.await_quiescent(timeout=5)
    latch_state.rollback()
    assert latch_state.read().state == "LEGACY_OPEN"

    # Re-enter DRAINING for a real retirement/cutover transaction.
    latch_state.begin_draining()
    latch_state.await_quiescent(timeout=5)

    fabpub_require(
        nodeid,
        _cutover_ready()
        and crash_at is not None
        and quiescence is not None
        and restart_supervisor is not None,
        "the writer-generation test requires a real cutover crash seam, supervisor inventory, "
        "and guarded supervisor restart; a state-only resume stub cannot prove generation fencing",
    )
    ledger = tmp_path / "ledger"
    train = _write_train(tmp_path / "trains" / "release.md", str(repo))
    seeded = _seed_legacy_root(
        ledger, train_path=train, serialized_repo=str(repo), epochs=(1, 2)
    )
    manifest_cls = _cutover_symbol("LegacyBrokerCutoverManifest")
    run_cutover = _cutover_symbol("run_legacy_broker_cutover")
    manifest = manifest_cls(
        cutover_id="writer-generation-crash",
        rows=(_manifest_row(ledger, train, repo, str(repo), tmp_path),),
    )

    # A real crash while the generation is DRAINING must leave retirement
    # recoverable and must not reopen legacy authority.
    with crash_at("before_source_retirement"):
        with pytest.raises(Exception):
            run_cutover(manifest)
    assert latch.open(repo).read().state == "DRAINING"
    with pytest.raises(Exception) as post_crash_legacy:
        latch.open(repo).acquire(generation="legacy")
    assert GENERATION_BLOCKER in str(post_crash_legacy.value)

    # Restart the same durable transaction to one ARMED receipt/archive, then
    # reopen it again at ARMED to prove idempotent process recovery.
    transaction = run_cutover(manifest)
    assert transaction.state == "ARMED"
    armed_journal = transaction.journal_path.read_bytes()
    resumed = run_cutover(manifest)
    assert resumed.state == "ARMED"
    assert resumed.journal_path.read_bytes() == armed_journal
    assert seeded["leaf"].is_file() or (seeded["leaf"] / "RETIRED").exists()
    receipt_paths = Path(_cutover_symbol("repository_broker_namespace")(repo)).glob(
        "partition-receipt*.json"
    )
    assert len(list(receipt_paths)) == 1

    resumed.activate()
    latch_state = latch.open(repo)
    assert latch_state.read().state == "ACTIVE"

    # POST-MUTATION ROLLBACK REFUSAL MATRIX (C3b): Rollback post-mutation / post-ACTIVE is refused.
    with pytest.raises(Exception) as post_mutation_rollback:
        latch_state.rollback()
    assert GENERATION_BLOCKER in str(post_mutation_rollback.value) or "ACTIVE" in str(post_mutation_rollback.value) or "refused" in str(post_mutation_rollback.value).lower()

    # Releasing the temporary activation lease does NOT expire the durable ACTIVE latch
    activation_lease.release()
    assert latch_state.read().state == "ACTIVE"

    generation = latch_state.read().generation
    namespace = Path(_cutover_symbol("repository_broker_namespace")(repo))

    # A supervised legacy restart and a raw evidence-store append are both
    # production writer surfaces; neither may bypass the durable ACTIVE latch.
    inventory = quiescence.inventory(repo)
    assert inventory.supervisors
    with pytest.raises(Exception) as stale_supervisor:
        restart_supervisor(
            repo,
            supervisor=inventory.supervisors[0],
            generation="legacy",
        )
    assert GENERATION_BLOCKER in str(stale_supervisor.value)

    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore

    evidence_before = _jsonl(namespace / "evidence.jsonl")
    with pytest.raises(Exception) as raw_evidence_append:
        BrokerEvidenceStore(namespace, generation_lease=None).record_intent(
            "stale-raw-evidence"
        )
    assert GENERATION_BLOCKER in str(raw_evidence_append.value)
    assert _jsonl(namespace / "evidence.jsonl") == evidence_before

    # (2) Every supported STALE entry is fenced BEFORE mkdir/append/admission/effect.
    def make(epoch: int, attempt_id: str) -> AdmissionRequest:
        return AdmissionRequest(attempt_id, epoch, "fence", "digest", "predicate", "scope", f"k-{attempt_id}")

    stale_entries = []

    # (a) a raw admission-store append on a stale generation
    stale_store = _counting_store(namespace)
    stale_store.generation_lease = None
    with pytest.raises(Exception) as raw_append:
        stale_store.admit_next(make, attempt_id="stale", precondition=lambda: True)
    stale_entries.append(str(raw_append.value))

    # (b) a direct adapter entry on a stale generation
    from phase_loop_runtime.convergence.broker.credsep import GitHubBrokerAdapter

    with pytest.raises(Exception) as adapter_entry:
        GitHubBrokerAdapter(repo, run=lambda *a, **k: None, generation_lease=None).execute(
            _publish_request(
                "id",
                "feat/x",
                "a" * 40,
                AdmissionRequest("attempt", 1, "fence", "digest", "predicate", "scope", "key"),
                repo,
            )
        )
    stale_entries.append(str(adapter_entry.value))

    # (c) a stale CLI/direct run_train restart in a FRESH process
    rc, out, err = _run_python(
        """
        import sys
        from pathlib import Path
        import phase_loop_runtime.convergence.broker.live as live
        latch = live.WriterGenerationLatch.open(Path(sys.argv[1]))
        try:
            latch.acquire(generation="legacy")
        except Exception as exc:
            print(str(exc))
            raise SystemExit(0)
        raise SystemExit("a stale generation acquired a lease after ACTIVE")
        """,
        str(repo),
    )
    assert rc == 0, err
    stale_entries.append(out.strip())

    for message in stale_entries:
        assert GENERATION_BLOCKER in message, f"expected {GENERATION_BLOCKER}; got {message!r}"
    assert not (namespace / "admissions.jsonl").exists() or _jsonl(namespace / "admissions.jsonl") == [], (
        "a fenced entry must create no directory, row, admission, or provider effect"
    )

    # (2d) A STALE CLI / direct `run_train` restart in a fresh process must be
    # fenced BEFORE any directory, row, admission, or provider effect.
    train = _write_train(tmp_path / "trains-stale" / "release.md", str(repo))
    rc, out, err = _run_python(
        """
        import json, sys
        from pathlib import Path
        import phase_loop_runtime.convergence.broker.live as live
        import phase_loop_runtime.train_runner as train_runner
        from phase_loop_runtime import cli
        from phase_loop_runtime.train_roadmap import load_train_roadmap

        train_path, worktree = sys.argv[1:3]
        live.force_writer_generation(Path(worktree), "legacy")   # a stale restart
        observed = {"cli": None, "direct": None}
        try:
            cli.main(["run-train", "--train", train_path])
        except Exception as exc:
            observed["cli"] = str(exc)
        try:
            train_runner.run_train(load_train_roadmap(train_path), Path(train_path).parent / "ledger",
                                   resolve_workspace=lambda _n: Path(worktree))
        except Exception as exc:
            observed["direct"] = str(exc)
        namespace = Path(live.repository_broker_namespace(Path(worktree)))
        observed["admissions"] = (namespace / "admissions.jsonl").exists()
        print(json.dumps(observed, sort_keys=True))
        """,
        str(train), str(repo),
    )
    assert rc == 0, err
    stale_cli = json.loads(out.strip().splitlines()[-1])
    assert GENERATION_BLOCKER in (stale_cli["cli"] or ""), (
        f"a stale CLI restart must be fenced; got {stale_cli['cli']!r}"
    )
    assert GENERATION_BLOCKER in (stale_cli["direct"] or ""), (
        f"a stale direct run_train must be fenced; got {stale_cli['direct']!r}"
    )
    assert stale_cli["admissions"] is False, "a fenced entry creates no admission row"

        # (3) POSITIVE ARM — a fresh CURRENT-generation process runs the REAL CLI, onboards,
    # and produces exactly ONE admission and ONE provider effect.  An always-block
    # implementation cannot satisfy this reached arm.
    _make_cli_publishable(repo, "feat/positive")
    positive_train = _write_train(tmp_path / "trains-positive" / "release.md", str(repo))
    probe = _cli_allocator_probe(positive_train, repo, "a" * 40, "b" * 40)
    assert probe["cli_exit"] == 0
    assert probe["namespace"] == str(namespace)
    assert probe["epochs"] == [1, 2], f"the current generation allocates monotonically: {probe['epochs']}"
    assert probe["adapter_calls"] == 2, "each distinct head reaches the provider exactly once"
    assert probe["train_status"] in ("completed", "drafts_open")
    assert len(probe["published"]) == 2

    latch_after = latch.open(repo).read()
    assert latch_after.state == "ACTIVE" and latch_after.generation == generation, (
        "a successful current-generation publish does not rotate the activated generation"
    )


# ===========================================================================
# Acyclic transaction identity (EC-FABPUB-4)
# ===========================================================================


@_requires_fabpub
def test_fabpub_intent_identity_pre_trailer_vector_rejects_self_or_final_message_derivation(
    tmp_path, request
):
    """Independently derive the frozen vector and compare production byte-for-byte."""
    nodeid = fabpub_this_nodeid(request)
    derive = fabpub_symbol("phase_loop_runtime.publishing", "derive_publish_transaction_id")
    build_intent = fabpub_symbol("phase_loop_runtime.publishing", "build_pre_trailer_intent")
    fabpub_require(
        nodeid,
        derive is not None and build_intent is not None,
        "derive_publish_transaction_id / build_pre_trailer_intent are absent; the publish "
        "identity is not yet acyclic pre-trailer-derived",
    )

    pre_trailer_bytes = canonical_bytes(FABPUB_IDENTITY_VECTOR)
    expected_pre_trailer_sha = hashlib.sha256(pre_trailer_bytes).hexdigest()
    expected_transaction_id = hashlib.sha256(TRANSACTION_DOMAIN + pre_trailer_bytes).hexdigest()

    produced = build_intent(fabpub_identity_inputs(), original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)
    assert produced.pre_trailer_intent_bytes == pre_trailer_bytes
    assert produced.pre_trailer_intent_sha256 == expected_pre_trailer_sha
    assert derive(pre_trailer_bytes) == expected_transaction_id
    assert produced.transaction_id == expected_transaction_id

    expected_final = (
        FABPUB_IDENTITY_ORIGINAL_MESSAGE
        + TRAILER_PREFIX
        + expected_transaction_id.encode("ascii")
        + b"\n"
    )
    assert produced.final_commit_message_bytes == expected_final
    assert produced.final_commit_message_sha256 == hashlib.sha256(expected_final).hexdigest()
    assert produced.final_commit_message_bytes.count(b"FABPUB-Intent-ID:") == 1

    # Mutation audit: injecting any self- or post-object field into the hashed
    # preimage must fail closed, never fixed-point-search.
    for injected in (
        "transaction_id",
        "final_commit_message_sha256",
        "expected_commit_oid",
        "committed_head_sha",
        "final_commit_object_sha256",
    ):
        poisoned = fabpub_identity_inputs(**{injected: "0" * 64})
        with pytest.raises(ValueError) as excinfo:
            build_intent(poisoned, original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)
        assert str(excinfo.value) in (
            "circular_transaction_identity",
            "forbidden_transaction_identity_field",
        )

        # NESTED AUTHORITY / DIGEST INJECTION (C3a): nested dicts inside envelope_authority_preimage
        # must also fail closed on self/post-object field injection.
        nested_authority = dict(FABPUB_ENVELOPE_AUTHORITY_PREIMAGE, **{injected: "0" * 64})
        nested_poisoned = fabpub_identity_inputs(envelope_authority_preimage=nested_authority)
        with pytest.raises(ValueError) as excinfo_nested:
            build_intent(nested_poisoned, original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)
        assert str(excinfo_nested.value) in (
            "circular_transaction_identity",
            "forbidden_transaction_identity_field",
        )


    # A preexisting FABPUB trailer in the caller message is refused.
    with pytest.raises(ValueError):
        build_intent(
            fabpub_identity_inputs(),
            original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE + b"\n\nFABPUB-Intent-ID: x\n",
        )

    # OPAQUE CALLER-SUPPLIED DIGESTS ARE NOT ACCEPTED (IF-0-FABPUB-1).  The vector's
    # message-derived members are computed from the literal bytes here, and production
    # must RE-DERIVE them from the message it is handed: a declared length or digest
    # that disagrees with the actual bytes fails closed rather than being trusted.
    assert FABPUB_IDENTITY_VECTOR["original_commit_message_length"] == len(
        FABPUB_IDENTITY_ORIGINAL_MESSAGE
    )
    assert FABPUB_IDENTITY_VECTOR["original_commit_message_sha256"] == hashlib.sha256(
        FABPUB_IDENTITY_ORIGINAL_MESSAGE
    ).hexdigest()
    for field, wrong in (
        ("original_commit_message_length", len(FABPUB_IDENTITY_ORIGINAL_MESSAGE) - 4),
        ("original_commit_message_sha256", "5" * 64),
    ):
        mismatched = fabpub_identity_inputs(**{field: wrong})
        with pytest.raises(ValueError):
            build_intent(mismatched, original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)
    # The same message under a DIFFERENT byte string must also be refused when the
    # declared members still describe the original.
    with pytest.raises(ValueError):
        build_intent(
            fabpub_identity_inputs(),
            original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE + b" (amended)",
        )

    # POSITIVE CONTROL: one changed pre-trailer authority byte changes BOTH digests.
    drifted = build_intent(
        fabpub_identity_inputs(branch="feat/other"), original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE
    )
    assert drifted.pre_trailer_intent_sha256 != expected_pre_trailer_sha
    assert drifted.transaction_id != expected_transaction_id


@_requires_fabpub
def test_fabpub_intent_identity_retry_is_deterministic_and_commit_bound_separately(
    tmp_path, request
):
    """Faithful retries reproduce every binding; an alternate OID is never adopted."""
    nodeid = fabpub_this_nodeid(request)
    build_intent = fabpub_symbol("phase_loop_runtime.publishing", "build_pre_trailer_intent")
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    fabpub_require(
        nodeid,
        build_intent is not None and prepare is not None,
        "build_pre_trailer_intent / prepare_publish_transaction are absent; retry determinism "
        "and separate commit binding cannot be asserted",
    )

    with pytest.raises(ValueError):
        build_intent(dict(FABPUB_IDENTITY_VECTOR), original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)

    first = build_intent(fabpub_identity_inputs(), original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)
    for _ in range(3):
        again = build_intent(fabpub_identity_inputs(), original_message=FABPUB_IDENTITY_ORIGINAL_MESSAGE)
        assert again.transaction_id == first.transaction_id
        assert again.pre_trailer_intent_bytes == first.pre_trailer_intent_bytes
        assert again.final_commit_message_bytes == first.final_commit_message_bytes

    # Real git: drive a transaction to COMMIT_OBJECT_DURABLE, then rewrite the branch
    # to a commit with the SAME parent/tree/message/trailer but a different committer
    # date.  It must produce a different OID and be REFUSED, never adopted.
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    _stage(repo, "a.py", "x = 1\n")
    checkpoint_root = tmp_path / "coordinator" / "node"
    transaction = prepare(
        repo,
        owned_paths=("a.py",),
        checkpoint_root=checkpoint_root,
        branch="feat/x",
        envelope_authority_preimage=_transaction_authority(repo, "feat/x"),
    )
    assert transaction.state == "COMMIT_OBJECT_DURABLE"
    expected_oid = transaction.expected_commit_oid
    parent = transaction.parent_head_sha
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == parent, (
        "the branch ref must NOT have moved before COMMIT_OBJECT_DURABLE"
    )

    # ref-at-parent → retry the SAME CAS to the already-recorded object.
    resumed = transaction.resume()
    assert resumed.committed_head_sha == expected_oid
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == expected_oid
    assert transaction.resume().committed_head_sha == expected_oid, "ref-at-expected finalizes"

    # FULL IDENTITY REWRITE MATRIX (C3a): independently rewrite current branch
    # to commits with the same parent/tree/message/trailer but different:
    # 1. author name / email (author identity)
    # 2. author date / timezone (author date/timezone)
    # 3. committer name / email (committer identity)
    # 4. committer date / timezone (committer date/timezone)
    # 5. signature (gpgsig header)
    # 6. encoding header (encoding header)
    # 7. ordered extra header (extra headers)
    # Each produces a different OID and MUST be rejected before admission, never adopted.
    def _identity_alternate(label: str, current_repo: Path, txn, current_parent: str) -> str:
        message = txn.final_commit_message_bytes.decode("utf-8")
        commit_tree = ("commit-tree", txn.tree_oid, "-p", current_parent, "-m", message)
        identity_env = {
            "GIT_AUTHOR_NAME": "Phase Loop",
            "GIT_AUTHOR_EMAIL": "phase-loop@example.invalid",
            "GIT_AUTHOR_DATE": "@1750000000 +0000",
            "GIT_COMMITTER_NAME": "Phase Loop",
            "GIT_COMMITTER_EMAIL": "phase-loop@example.invalid",
            "GIT_COMMITTER_DATE": "@1750000000 +0000",
        }
        if label == "author_identity":
            return _git_env(
                current_repo,
                identity_env
                | {
                    "GIT_AUTHOR_NAME": "Other Author",
                    "GIT_AUTHOR_EMAIL": "author@example.invalid",
                },
                *commit_tree,
            )
        if label == "author_date_tz":
            return _git_env(
                current_repo,
                identity_env | {"GIT_AUTHOR_DATE": "@1750000100 +0200"},
                *commit_tree,
            )
        if label == "committer_identity":
            return _git_env(
                current_repo,
                identity_env
                | {
                    "GIT_COMMITTER_NAME": "Other Committer",
                    "GIT_COMMITTER_EMAIL": "committer@example.invalid",
                },
                *commit_tree,
            )
        if label == "committer_date_tz":
            return _git_env(
                current_repo,
                identity_env | {"GIT_COMMITTER_DATE": "@1750000100 -0500"},
                *commit_tree,
            )
        header = {
            "signature": "gpgsig -----BEGIN PGP SIGNATURE-----\n Version: 1\n -----END PGP SIGNATURE-----\n",
            "encoding": "encoding ISO-8859-1\n",
            "extra_header": "extra-header value\n",
        }[label]
        raw = (
            f"tree {txn.tree_oid}\nparent {current_parent}\n"
            "author Phase Loop <phase-loop@example.invalid> 1750000000 +0000\n"
            "committer Phase Loop <phase-loop@example.invalid> 1750000000 +0000\n"
            f"{header}\n{message}"
        ).encode("utf-8")
        return subprocess.run(
            ["git", "-C", str(current_repo), "hash-object", "-w", "-t", "commit", "--stdin"],
            input=raw,
            capture_output=True,
            check=True,
        ).stdout.decode("ascii").strip()

    for label in (
        "author_identity",
        "author_date_tz",
        "committer_identity",
        "committer_date_tz",
        "signature",
        "encoding",
        "extra_header",
    ):
        case_repo = _init_repo(tmp_path / f"identity-{label}")
        _git(case_repo, "checkout", "-q", "-b", "feat/x")
        _stage(case_repo, "a.py", "x = 1\n")
        case_txn = prepare(
            case_repo,
            owned_paths=("a.py",),
            checkpoint_root=tmp_path / "identity-checkpoints" / label,
            branch="feat/x",
            envelope_authority_preimage=_transaction_authority(case_repo, "feat/x"),
        )
        case_expected = case_txn.expected_commit_oid
        case_parent = case_txn.parent_head_sha
        assert case_txn.resume().committed_head_sha == case_expected
        assert case_txn.resume().committed_head_sha == case_expected
        alt_oid = _identity_alternate(label, case_repo, case_txn, case_parent)
        assert alt_oid != case_expected, f"{label}: changed identity must produce a different OID"
        _git(case_repo, "update-ref", "refs/heads/feat/x", alt_oid, case_expected)
        with pytest.raises(Exception) as conflict:
            case_txn.resume()
        assert "CONFLICTED" in str(conflict.value) or "conflict" in str(conflict.value).lower(), (
            f"{label}: alternate commit OID must be rejected before admission"
        )
        assert _git(case_repo, "rev-parse", "refs/heads/feat/x") == alt_oid, (
            f"{label}: a refused resume must not move the ref"
        )



# ===========================================================================
# Pre-ref expected-commit state machine (EC-FABPUB-4/-5/-6)
# ===========================================================================


def _prepared_transaction(tmp_path: Path, *, name: str = "repo"):
    """Drive PRODUCTION to ``COMMIT_OBJECT_DURABLE`` on a real repository."""
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    repo = _init_repo(tmp_path / name)
    _git(repo, "checkout", "-q", "-b", "feat/x")
    _stage(repo, "a.py", "x = 1\n")
    transaction = prepare(
        repo,
        owned_paths=("a.py",),
        checkpoint_root=tmp_path / "coordinator" / name,
        branch="feat/x",
        envelope_authority_preimage=_transaction_authority(repo, "feat/x"),
    )
    return repo, transaction


def _authorized_prepared_transaction(tmp_path: Path, *, name: str):
    """Prepare a transaction only after repository authority is active."""
    repo = _init_repo(tmp_path / name)
    identity, namespace = _activate_repository_authority(tmp_path, repo, label=name)
    _git(repo, "checkout", "-q", "-b", "feat/x")
    _stage(repo, "a.py", "x = 1\n")
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    transaction = prepare(
        repo,
        owned_paths=("a.py",),
        checkpoint_root=tmp_path / "coordinator" / name,
        branch="feat/x",
        envelope_authority_preimage=_authority_preimage(identity, "feat/x"),
    )
    return repo, transaction, identity, namespace


def _authorized_publish_fixture(tmp_path: Path, *, name: str):
    """Return one real committed transaction in an activated repository partition."""
    repo, transaction, identity, namespace = _authorized_prepared_transaction(
        tmp_path, name=name
    )
    transaction.resume()
    assert transaction.committed_head_sha == transaction.expected_commit_oid
    assert transaction.canonical_repository_identity == identity
    return repo, transaction, identity, namespace


def _next_authorized_transaction(
    tmp_path: Path,
    repo: Path,
    *,
    name: str,
    branch: str,
    relative_path: str,
):
    """Prepare and resolve another exact transaction in an already-active repository."""
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    identity = _cutover_symbol("canonical_repository_identity")(repo)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", branch)
    _stage(repo, relative_path, f"{name} = 1\n")
    transaction = prepare(
        repo,
        owned_paths=(relative_path,),
        checkpoint_root=tmp_path / "coordinator" / name,
        branch=branch,
        envelope_authority_preimage=_authority_preimage(identity, branch),
    )
    transaction.resume()
    assert transaction.committed_head_sha == transaction.expected_commit_oid
    return transaction


@_requires_fabpub
def test_fabpub_expected_commit_object_is_durable_before_ref_cas(tmp_path, request):
    """The object, its OID, and its raw digest are durable BEFORE the ref moves."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction") is not None,
        "prepare_publish_transaction is absent; publish still commits via porcelain and can "
        "lose the crash window between commit and broker entry",
    )

    repo, transaction = _prepared_transaction(tmp_path)
    assert transaction.state == "COMMIT_OBJECT_DURABLE"

    # The object EXISTS in the odb while the ref is still at its parent.
    assert _git(repo, "cat-file", "-t", transaction.expected_commit_oid) == "commit"
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == transaction.parent_head_sha

    # Both exact values are on disk, not just in memory.
    checkpoint = json.loads(transaction.checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["expected_commit_oid"] == transaction.expected_commit_oid
    raw = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "commit", transaction.expected_commit_oid],
        capture_output=True, check=True, timeout=60,
    ).stdout
    assert checkpoint["final_commit_object_sha256"] == hashlib.sha256(raw).hexdigest()
    assert b"FABPUB-Intent-ID: " + transaction.transaction_id.encode("ascii") in raw

    # Only the CAS moves the ref, and it moves it to exactly that OID.
    transaction.resume()
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == transaction.expected_commit_oid
    assert len(_git(repo, "rev-list", "--count", "feat/x").split()) == 1


@_requires_fabpub
def test_fabpub_checkpoint_conflict_blocks_alternate_oid_before_admission(tmp_path, request):
    """Any other ref OID blocks BEFORE admission with zero side effects."""
    nodeid = fabpub_this_nodeid(request)
    inspect = fabpub_symbol("phase_loop_runtime.publishing", "inspect_publish_resume_candidate")
    fabpub_require(
        nodeid,
        inspect is not None,
        "inspect_publish_resume_candidate is absent; an alternate same-semantic commit "
        "could be adopted on recovery",
    )

    repo, transaction = _prepared_transaction(tmp_path)
    unrelated = _git(repo, "commit-tree", transaction.tree_oid, "-p", transaction.parent_head_sha, "-m", "unrelated")
    _git(repo, "update-ref", "refs/heads/feat/x", unrelated, transaction.parent_head_sha)

    root = tmp_path / "store"
    adapter = _CountingAdapter()
    store = _counting_store(root)
    _service(root, adapter, store=store)

    candidate = inspect(repo, checkpoint_root=transaction.checkpoint_root, node_id="node")
    assert candidate.state == "CONFLICTED", f"expected CONFLICTED; got {candidate.state}"
    assert (store.admit_calls, store.admit_next_calls) == (0, 0)
    assert adapter.calls == []
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == unrelated, "a conflict must not move the ref"

    # POSITIVE CONTROL: restoring the exact parent arm makes the same seam resumable.
    _git(repo, "update-ref", "refs/heads/feat/x", transaction.parent_head_sha, unrelated)
    assert inspect(repo, checkpoint_root=transaction.checkpoint_root, node_id="node").state == (
        "COMMIT_OBJECT_DURABLE"
    )


@_requires_fabpub
def test_fabpub_transaction_state_machine_enforces_ordered_projection(tmp_path, request):
    """Only the frozen order projects; an out-of-order write is refused."""
    nodeid = fabpub_this_nodeid(request)
    states = fabpub_symbol("phase_loop_runtime.publishing", "PublishTransactionState")
    fabpub_require(
        nodeid,
        states is not None and fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction") is not None,
        "PublishTransactionState is absent; there is no ordered train-local projection",
    )

    expected = (
        "PREPARED",
        "COMMIT_OBJECT_DURABLE",
        "COMMITTED_HEAD_RESOLVED",
        "ADMISSION_DURABLE",
        "BROKER_INTENT_DURABLE",
        "ADAPTER_STARTED",
        "TERMINAL_SEALED",
    )
    assert tuple(states.ORDERED) == expected
    for tombstone in ("ABANDONED", "CONFLICTED"):
        assert hasattr(states, tombstone)

    repo, transaction = _prepared_transaction(tmp_path)

    # SKIPPING a state is refused, and the on-disk projection does not advance.
    before = transaction.checkpoint_path.read_bytes()
    with pytest.raises(Exception):
        transaction.project("ADAPTER_STARTED")
    assert transaction.checkpoint_path.read_bytes() == before, (
        "a refused projection must leave the durable record byte-identical"
    )

    # The legal next step advances and is durable.
    transaction.resume()
    assert json.loads(transaction.checkpoint_path.read_text(encoding="utf-8"))["state"] == (
        "COMMITTED_HEAD_RESOLVED"
    )
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == transaction.expected_commit_oid

    # A tombstone never authorizes a later projection.
    transaction.abandon()
    with pytest.raises(Exception):
        transaction.project("ADMISSION_DURABLE")


@_requires_fabpub
def test_fabpub_intent_conflict_never_overwrites_active_mismatch(tmp_path, request):
    """A mismatching intent is refused and the active record is left byte-identical."""
    nodeid = fabpub_this_nodeid(request)
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    fabpub_require(
        nodeid,
        prepare is not None,
        "prepare_publish_transaction is absent; an active mismatch cannot be compared",
    )

    repo, transaction = _prepared_transaction(tmp_path)
    original = transaction.checkpoint_path.read_bytes()

    # A DIFFERENT owned-path set is a different pre-trailer identity for the same node.
    _stage(repo, "b.py", "y = 2\n")
    with pytest.raises(Exception) as mismatch:
        prepare(
            repo,
            owned_paths=("a.py", "b.py"),
            checkpoint_root=transaction.checkpoint_root,
            branch="feat/x",
            envelope_authority_preimage=_transaction_authority(repo, "feat/x"),
        )
    assert "conflict" in str(mismatch.value).lower() or "mismatch" in str(mismatch.value).lower()
    assert transaction.checkpoint_path.read_bytes() == original, (
        "an active mismatch must never be overwritten"
    )

    # POSITIVE CONTROL: the identical input reproduces the same transaction.
    _git(repo, "restore", "--staged", "b.py")
    (repo / "b.py").unlink()
    same = prepare(
        repo,
        owned_paths=("a.py",),
        checkpoint_root=transaction.checkpoint_root,
        branch="feat/x",
        envelope_authority_preimage=_transaction_authority(repo, "feat/x"),
    )
    assert same.transaction_id == transaction.transaction_id
    assert same.expected_commit_oid == transaction.expected_commit_oid


@_requires_fabpub
def test_fabpub_intent_cleanup_tombstone_precedes_pointer_clear(tmp_path, request):
    """Cleanup fsyncs the tombstone BEFORE it clears the active pointer."""
    nodeid = fabpub_this_nodeid(request)
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    fabpub_require(
        nodeid,
        prepare is not None,
        "prepare_publish_transaction is absent; cleanup ordering cannot be asserted",
    )

    repo, transaction = _prepared_transaction(tmp_path)
    order: list = []
    real_write = transaction.write_tombstone
    real_clear = transaction.clear_active_pointer

    def spy_write(*args, **kwargs):
        result = real_write(*args, **kwargs)
        order.append(("tombstone", transaction.tombstone_path.exists()))
        return result

    def spy_clear(*args, **kwargs):
        order.append(("clear", transaction.tombstone_path.exists()))
        return real_clear(*args, **kwargs)

    transaction.write_tombstone = spy_write
    transaction.clear_active_pointer = spy_clear
    transaction.abandon()

    assert [step for step, _ in order] == ["tombstone", "clear"], (
        "the tombstone must be durable before the active pointer is cleared"
    )
    assert order[1][1] is True
    assert transaction.tombstone_path.exists() and not transaction.active_pointer_path.exists()

    # A tombstoned transaction never authorizes admission or effect.
    root = tmp_path / "store"
    adapter = _CountingAdapter()
    store = _counting_store(root)
    with pytest.raises(Exception):
        transaction.resume()
    assert (store.admit_calls, store.admit_next_calls) == (0, 0) and adapter.calls == []


@_requires_fabpub
def test_fabpub_dual_path_normal_and_prebuilt_share_one_transaction_contract(tmp_path, request):
    """Prebuilt freezes the supplied head; it never appends, rewrites, or CAS-moves."""
    nodeid = fabpub_this_nodeid(request)
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    prepare_prebuilt = fabpub_symbol("phase_loop_runtime.publishing", "prepare_prebuilt_transaction")
    fabpub_require(
        nodeid,
        prepare is not None and prepare_prebuilt is not None,
        "prepare_prebuilt_transaction is absent; prebuilt and normal publication do not yet "
        "share one transaction contract",
    )

    normal_repo, normal = _prepared_transaction(tmp_path, name="normal")
    assert normal.state == "COMMIT_OBJECT_DURABLE"

    prebuilt_repo = _init_repo(tmp_path / "prebuilt")
    _git(prebuilt_repo, "checkout", "-q", "-b", "feat/y")
    _stage(prebuilt_repo, "c.py", "z = 3\n")
    _git(prebuilt_repo, "commit", "-q", "-m", "prebuilt work")
    head_before = _git(prebuilt_repo, "rev-parse", "HEAD")
    count_before = _git(prebuilt_repo, "rev-list", "--count", "feat/y")

    prebuilt = prepare_prebuilt(
        prebuilt_repo,
        checkpoint_root=tmp_path / "coordinator" / "prebuilt",
        branch="feat/y",
        envelope_authority_preimage=_transaction_authority(prebuilt_repo, "feat/y"),
    )
    assert prebuilt.expected_commit_oid == head_before == prebuilt.committed_head_sha
    assert _git(prebuilt_repo, "rev-parse", "HEAD") == head_before, "prebuilt must not move the ref"
    assert _git(prebuilt_repo, "rev-list", "--count", "feat/y") == count_before, (
        "prebuilt must not create a commit"
    )
    assert type(prebuilt).__name__ == type(normal).__name__, "one transaction contract, two routes"

    # A prebuilt head carrying a misleading FABPUB trailer is refused.
    _git(prebuilt_repo, "checkout", "-q", "-b", "feat/z")
    _stage(prebuilt_repo, "d.py", "w = 4\n")
    _git(prebuilt_repo, "commit", "-q", "-m", "work\n\nFABPUB-Intent-ID: deadbeef\n")
    with pytest.raises(ValueError):
        prepare_prebuilt(
            prebuilt_repo,
            checkpoint_root=tmp_path / "coordinator" / "z",
            branch="feat/z",
            envelope_authority_preimage=_transaction_authority(prebuilt_repo, "feat/z"),
        )


@_requires_fabpub
def test_fabpub_faithful_retry_preserves_every_identity_binding(tmp_path, request):
    """A faithful retry from each arm reproduces every binding byte-for-byte."""
    nodeid = fabpub_this_nodeid(request)
    validate = fabpub_symbol("phase_loop_runtime.publishing", "validate_transaction_owned_workspace")
    fabpub_require(
        nodeid,
        validate is not None,
        "validate_transaction_owned_workspace is absent; a faithful retry cannot be "
        "distinguished from a conflicting one",
    )

    repo, transaction = _prepared_transaction(tmp_path)
    frozen = {
        "transaction_id": transaction.transaction_id,
        "pre_trailer": transaction.pre_trailer_intent_sha256,
        "final_message": transaction.final_commit_message_sha256,
        "expected_oid": transaction.expected_commit_oid,
        "raw_digest": transaction.final_commit_object_sha256,
    }

    # The exact transaction-owned staged state validates at the parent arm.
    validate(repo, transaction)

    # ONE extra staged path is refused.
    _stage(repo, "extra.py", "extra = 1\n")
    with pytest.raises(Exception):
        validate(repo, transaction)
    _git(repo, "restore", "--staged", "extra.py")
    (repo / "extra.py").unlink()

    # ONE unstaged byte is refused.
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(Exception):
        validate(repo, transaction)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "--", "a.py")

    # An UNTRACKED path is refused.
    (repo / "untracked.txt").write_text("dirt\n", encoding="utf-8")
    with pytest.raises(Exception):
        validate(repo, transaction)
    (repo / "untracked.txt").unlink()

    # Faithful retries across both arms preserve every binding and update the ref once.
    validate(repo, transaction)
    transaction.resume()
    for _ in range(3):
        transaction.resume()
    assert {
        "transaction_id": transaction.transaction_id,
        "pre_trailer": transaction.pre_trailer_intent_sha256,
        "final_message": transaction.final_commit_message_sha256,
        "expected_oid": transaction.expected_commit_oid,
        "raw_digest": transaction.final_commit_object_sha256,
    } == frozen
    assert _git(repo, "rev-list", "--count", "feat/x") == "2", "exactly one new commit exists"


@_requires_fabpub
def test_fabpub_terminal_replay_returns_prior_result_without_admission_or_adapter(
    tmp_path, request
):
    """A completed terminal publish replays before authorization, with zero side effects."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _envelope_cls_present(),
        "PreAdmissionEnvelope is absent; terminal replay ordering cannot be asserted "
        "against the fresh-publish gate",
    )

    from phase_loop_runtime.convergence.contracts import AdmissionRequest

    worktree, transaction, identity, root = _authorized_publish_fixture(
        tmp_path, name="terminal-replay"
    )
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)

    head = transaction.committed_head_sha
    first = service.execute(
        _publish_transaction_request(identity, "feat/x", transaction, worktree)
    )
    assert first.accepted and len(adapter.calls) == 1 and store.admit_next_calls == 1

    # A repeat under a DIFFERENT transaction id but the same canonical triple replays.
    replay_admission = AdmissionRequest(
        "replay-attempt", 999, "untrusted-fence", "untrusted-digest",
        "untrusted-predicate", identity, "different-transaction-id",
    )
    replay = service.execute(
        _publish_request(identity, "feat/x", head, replay_admission, worktree)
    )
    assert replay.accepted
    assert replay.publish_result == first.publish_result
    assert len(adapter.calls) == 1, "the canonical triple must de-dup: one real effect"
    assert store.admit_next_calls == 1, "a terminal replay allocates nothing"
    assert len(_jsonl(root / "admissions.jsonl")) == 1


@_requires_fabpub
def test_fabpub_different_head_allocates_the_next_epoch(tmp_path, request):
    """A genuinely different head is a new effect at the next epoch."""
    nodeid = fabpub_this_nodeid(request)
    fabpub_require(
        nodeid,
        _envelope_cls_present(),
        "admit_next is absent; a genuine different head cannot obtain the next epoch",
    )

    worktree, first_transaction, identity, root = _authorized_publish_fixture(
        tmp_path, name="different-head"
    )
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)

    second_transaction = _next_authorized_transaction(
        tmp_path,
        worktree,
        name="different-head-second",
        branch="feat/different-head-second",
        relative_path="second.py",
    )
    for index, transaction in enumerate((first_transaction, second_transaction), start=1):
        outcome = service.execute(
            _publish_transaction_request(
                identity,
                "feat/x" if index == 1 else "feat/different-head-second",
                transaction,
                worktree,
            )
        )
        assert outcome.accepted
        assert store.allocated_epochs[-1] == index
        assert len(adapter.calls) == index

    assert [row["epoch"] for row in _jsonl(root / "admissions.jsonl")] == [1, 2]


@_requires_fabpub
def test_fabpub_conflicting_resume_is_refused_before_admission(tmp_path, request):
    """A conflicting resume is refused before admission with zero side effects."""
    nodeid = fabpub_this_nodeid(request)
    inspect = fabpub_symbol("phase_loop_runtime.publishing", "inspect_publish_resume_candidate")
    fabpub_require(
        nodeid, inspect is not None, "inspect_publish_resume_candidate is absent"
    )

    repo, transaction = _prepared_transaction(tmp_path)
    root = tmp_path / "store"
    adapter = _CountingAdapter()
    store = _counting_store(root)
    _service(root, adapter, store=store)

    # Corrupt the recorded expected object: the exact-OID arm can no longer be proven.
    checkpoint = json.loads(transaction.checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["final_commit_object_sha256"] = "0" * 64
    transaction.checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True), encoding="utf-8")

    candidate = inspect(repo, checkpoint_root=transaction.checkpoint_root, node_id="node")
    assert candidate.state == "CONFLICTED"
    assert (store.admit_calls, store.admit_next_calls) == (0, 0) and adapter.calls == []
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == transaction.parent_head_sha


@_requires_fabpub
def test_fabpub_genuine_resume_dedups_one_admission_and_one_effect(tmp_path, request):
    """A faithful resume yields exactly one admission and one provider effect."""
    nodeid = fabpub_this_nodeid(request)
    inspect = fabpub_symbol("phase_loop_runtime.publishing", "inspect_publish_resume_candidate")
    fabpub_require(
        nodeid, inspect is not None, "inspect_publish_resume_candidate is absent"
    )

    repo, transaction, identity, root = _authorized_prepared_transaction(
        tmp_path, name="genuine-resume"
    )
    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)

    candidate = inspect(repo, checkpoint_root=transaction.checkpoint_root, node_id="node")
    assert candidate.state == "COMMIT_OBJECT_DURABLE"
    transaction.resume()
    head = transaction.committed_head_sha

    for _ in range(3):
        outcome = service.execute(
            _publish_transaction_request(identity, "feat/x", transaction, repo)
        )
        assert outcome.accepted
    assert store.admit_next_calls == 1, "a faithful resume dedups to ONE admission"
    assert len(adapter.calls) == 1, "a faithful resume dedups to ONE provider effect"


# ===========================================================================
# Live train authority handoff (EC-FABPUB-4)
# ===========================================================================


@_requires_fabpub
def test_fabpub_train_handoff_returns_publish_authority_preimages_only(tmp_path, request):
    """The train hands over PRE-commit authority only — never a broker-legal envelope."""
    nodeid = fabpub_this_nodeid(request)
    preimages = fabpub_symbol("phase_loop_runtime.train_runner", "PublishAuthorityPreimages")
    builder = fabpub_symbol("phase_loop_runtime.train_runner", "_default_build_publish_authority")
    fabpub_require(
        nodeid,
        preimages is not None and builder is not None,
        "_default_build_publish_authority / PublishAuthorityPreimages are absent; the train "
        "still constructs a finalized AdmissionRequest before the commit identity exists",
    )

    fields = set(preimages.__dataclass_fields__)
    for forbidden in (
        "admission", "envelope", "lease_epoch", "attempt_id", "fence_token",
        "approval_digest", "idempotency_key", "committed_head_sha", "expected_commit_oid",
    ):
        assert forbidden not in fields, f"pre-commit inputs only; found {forbidden}"
    assert "checkpoint_root" in fields
    assert fabpub_symbol("phase_loop_runtime.train_runner", "_default_build_admission") is None, (
        "the superseded finalized-admission builder must be absent after migration"
    )

    # Drive the REAL builder against a real workspace and assert what it produced.
    from phase_loop_runtime.train_runner import CoordinatorRuntime

    repo = _init_repo(tmp_path / "repo")
    runtime = CoordinatorRuntime("train", tmp_path / "coord", "train.md", "digest", "workspace")
    node = type("Node", (), {"node_id": "repo-a", "roadmap": "specs/plan.md"})()
    produced = builder(runtime, node, repo, ["a.py"])
    assert isinstance(produced, preimages)
    assert Path(produced.checkpoint_root).is_absolute()
    payload = json.dumps(produced.__dict__, sort_keys=True, default=str)
    for leaked in ("lease_epoch", "idempotency_key", "expected_commit_oid"):
        assert leaked not in payload, f"{leaked} leaked into the pre-commit handoff"


@_requires_fabpub
def test_fabpub_train_resume_normal_recovers_exact_oid(tmp_path, request):
    """A normal post-commit crash resumes the recorded object, never nothing_staged."""
    nodeid = fabpub_this_nodeid(request)
    inspect = fabpub_symbol("phase_loop_runtime.publishing", "inspect_publish_resume_candidate")
    fabpub_require(
        nodeid,
        inspect is not None,
        "inspect_publish_resume_candidate is absent; a normal post-commit crash still exits "
        "at nothing_staged",
    )

    repo, transaction, identity, root = _authorized_prepared_transaction(
        tmp_path, name="train-resume-normal"
    )
    transaction.resume()
    head = transaction.committed_head_sha
    assert _git(repo, "rev-parse", "refs/heads/feat/x") == head

    # The tree is now CLEAN — the pre-FABPUB failure mode.  Recovery must still find
    # the transaction and reuse the exact OID rather than restage.
    assert _git(repo, "status", "--short") == ""
    candidate = inspect(repo, checkpoint_root=transaction.checkpoint_root, node_id="node")
    assert candidate.state in ("COMMITTED_HEAD_RESOLVED", "TERMINAL_SEALED")
    assert candidate.committed_head_sha == head

    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)
    outcome = service.execute(
        _publish_transaction_request(identity, "feat/x", transaction, repo)
    )
    assert outcome.accepted and len(adapter.calls) == 1
    assert _git(repo, "rev-list", "--count", "feat/x") == "2", "recovery created no second commit"


@_requires_fabpub
def test_fabpub_train_resume_prebuilt_never_rewrites_a_commit(tmp_path, request):
    """Prebuilt resume reuses the frozen head and never rewrites or re-signs."""
    nodeid = fabpub_this_nodeid(request)
    prepare_prebuilt = fabpub_symbol("phase_loop_runtime.publishing", "prepare_prebuilt_transaction")
    fabpub_require(
        nodeid,
        prepare_prebuilt is not None,
        "prepare_prebuilt_transaction is absent; prebuilt resume has no exact-OID contract",
    )

    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feat/y")
    _stage(repo, "c.py", "z = 3\n")
    _git(repo, "commit", "-q", "-m", "prebuilt work")
    head = _git(repo, "rev-parse", "HEAD")
    count = _git(repo, "rev-list", "--count", "feat/y")

    identity, root = _activate_repository_authority(
        tmp_path, repo, label="train-resume-prebuilt"
    )

    checkpoint_root = tmp_path / "coordinator" / "prebuilt"
    authority_preimage = _authority_preimage(identity, "feat/y")
    first = prepare_prebuilt(
        repo,
        checkpoint_root=checkpoint_root,
        branch="feat/y",
        envelope_authority_preimage=authority_preimage,
    )
    resumed = prepare_prebuilt(
        repo,
        checkpoint_root=checkpoint_root,
        branch="feat/y",
        envelope_authority_preimage=authority_preimage,
    )
    assert resumed.transaction_id == first.transaction_id
    assert resumed.expected_commit_oid == resumed.committed_head_sha == head
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "rev-list", "--count", "feat/y") == count, "prebuilt resume created no commit"

    adapter = _CountingAdapter()
    store = _counting_store(root)
    service = _service(root, adapter, store=store)
    for _ in range(2):
        assert service.execute(
            _publish_transaction_request(identity, "feat/y", first, repo)
        ).accepted
    assert len(adapter.calls) == 1 and store.admit_next_calls == 1


# ===========================================================================
# SL-4 documentation retraction
# ===========================================================================


@_requires_fabpub
def test_fabpub_changelog_records_publish_byte_neutrality_retraction(request):
    """The CHANGELOG must explicitly retract publish byte-neutrality."""
    nodeid = fabpub_this_nodeid(request)
    changelog = REPO_ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    fabpub_require(
        nodeid,
        "FABPUB-Intent-ID" in text and "byte-neutrality" in text,
        "CHANGELOG.md does not retract publish byte-neutrality (epoch renumbering, the "
        "deterministic FABPUB-Intent-ID trailer, and canonical-repository-bound effect keys)",
    )
    assert "repository-scoped" in text, (
        "the retraction must state that permanent ambiguity is now repository-scoped"
    )
