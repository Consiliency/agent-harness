"""Live-enablement tests for the single SUPPORTED broker verb.

The git/gh seam is mocked (``run`` injection) — NO live GitHub is contacted.
Covers: (a) matching remote head -> effect_terminal_observed + real url +
PublishCommittedBranchResult; (b) remote-head mismatch -> outcome_ambiguous_blocked
(NOT success); (c) idempotent replay returns the prior result; (d) ONLY
publish_committed_branch/github is SUPPORTED and every other verb is refused
fail-closed; (e) the live broker builder constructs a working client.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess
import subprocess

import pytest

from _fabpub_tdd_guard import fabpub_migrated_activated, fabpub_symbol
from phase_loop_runtime.convergence.broker import build_github_broker_client, build_routing_broker_client
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.broker.credsep import GitHubBrokerAdapter
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
from phase_loop_runtime.convergence.broker.verbs import BrokerService
from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    BrokerRequest,
    BrokerVerb,
    PublishCommittedBranchResult,
)
from phase_loop_runtime.convergence.provider_contracts import (
    PROVIDER_COMPLETION_CLASSIFICATIONS,
    ProviderCompletionClassification,
)

_BRANCH = "feat/live-enable"
_HEAD = "a" * 40
_URL = "https://github.com/o/r/pull/7"
_CANONICAL_REPOSITORY_IDENTITY = "canonical-repository-identity"
_ADAPTER_WORKTREE = "o/r"
_FABPUB_AUTHORITY_PREIMAGE = {
    "schema": "PublishEnvelopeAuthorityPreimage.v1",
    "train_id": "fabpub-live-train",
    "node_id": "node-1",
    "action": "publish_committed_branch",
    "roadmap_digest": "8" * 64,
    "effective_code_digest": "9" * 64,
    "dependency_digest": "a" * 64,
    "verification_plan_digest": "b" * 64,
    "expected_version_predicate": "head == expected_commit_oid",
    "authority_domain_scope": "repository:fabpub-live",
    "operation_identity": "publish:fabpub-live",
}


def _admission(key: str) -> AdmissionRequest:
    return AdmissionRequest("attempt", 1, "fence", "digest", "head == committed", "scope", key)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def _prepared_publish_fixture(
    tmp_path: Path, *, label: str, branch: str, owned_file: str = "plan.md"
):
    """Build one repository and its exact pre-activation manifest row."""
    repo = tmp_path / label
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "FABPUB Test")
    _git(repo, "config", "user.email", "fabpub@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    train = tmp_path / "trains" / label / "release.md"
    train.parent.mkdir(parents=True)
    train.write_text(
        "# Release Train: fabpub-live\n\n## Nodes\n\n"
        "### Node: node-1 / specs/plan.md\n\n"
        f"**Workspace:** {repo}\n**Depends on:** (none)\n**Channel:** (none)\n",
        encoding="utf-8",
    )
    serialized = str(repo)
    train_key = hashlib.sha256(str(train.resolve()).encode("utf-8")).hexdigest()[:16]
    repo_key = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    legacy_root = tmp_path / "legacy" / label
    leaf = legacy_root / "broker" / train_key / repo_key
    leaf.mkdir(parents=True)
    (leaf / "admissions.jsonl").write_text("", encoding="utf-8")

    row = {
        "legacy_root": str(legacy_root / "broker"),
        "serialized_repository": serialized,
        "serialized_repository_bytes_sha256": hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest(),
        "invocation_working_directory": str(tmp_path),
        "resolution_mode": "absolute",
        "resolved_train_path": str(train.resolve()),
        "expected_train_key": train_key,
        "expected_repo_key": repo_key,
        "expected_worktree": str(repo),
    }
    return repo, row, owned_file, branch, label


def _activate_manifest(*, cutover_id: str, rows: tuple[dict, ...]):
    manifest_cls = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "LegacyBrokerCutoverManifest"
    )
    run_cutover = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "run_legacy_broker_cutover"
    )
    cutover = run_cutover(manifest_cls(cutover_id=cutover_id, rows=rows))
    assert cutover.state == "ARMED"
    cutover.activate()
    assert cutover.state == "ACTIVE"


def _publish_request_for_active_repo(
    tmp_path: Path, repo: Path, owned_file: str, branch: str, label: str
):
    """Prepare and resolve the transaction only after repository activation."""
    identity_fn = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "canonical_repository_identity"
    )
    identity = identity_fn(repo)
    authority_preimage = dict(_FABPUB_AUTHORITY_PREIMAGE)
    authority_preimage["authority_domain_scope"] = f"repository:{identity}"
    authority_preimage["operation_identity"] = f"publish:{branch}"
    _git(repo, "checkout", "-q", "-b", branch)
    (repo / owned_file).write_text(f"{label}\n", encoding="utf-8")
    _git(repo, "add", owned_file)
    prepare = fabpub_symbol("phase_loop_runtime.publishing", "prepare_publish_transaction")
    transaction = prepare(
        repo,
        owned_paths=(owned_file,),
        checkpoint_root=tmp_path / "coordinator" / label,
        branch=branch,
        envelope_authority_preimage=authority_preimage,
    )
    transaction.resume()

    namespace_fn = fabpub_symbol(
        "phase_loop_runtime.convergence.broker.live", "repository_broker_namespace"
    )
    assert transaction.canonical_repository_identity == identity
    envelope_cls = fabpub_symbol(
        "phase_loop_runtime.convergence.contracts", "PreAdmissionEnvelope"
    )
    envelope = envelope_cls(
        **{
            key: value
            for key, value in authority_preimage.items()
            if key != "schema"
        },
        canonical_repository_identity=identity,
        original_commit_message_sha256=transaction.original_commit_message_sha256,
        pre_trailer_intent_sha256=transaction.pre_trailer_intent_sha256,
        transaction_id=transaction.transaction_id,
        final_commit_message_sha256=transaction.final_commit_message_sha256,
        expected_commit_oid=transaction.expected_commit_oid,
        committed_head_sha=transaction.committed_head_sha,
        final_commit_object_sha256=transaction.final_commit_object_sha256,
        adapter_worktree=str(repo),
        checkpoint_root=str(transaction.checkpoint_root),
    )
    request = BrokerRequest(
        BrokerVerb.PUBLISH_COMMITTED_BRANCH,
        envelope,
        identity,
        branch,
        transaction.committed_head_sha,
        (owned_file,),
        adapter_worktree=str(repo),
    )
    return repo, Path(namespace_fn(repo)), request


def _activated_publish_fixture(
    tmp_path: Path, *, label: str, branch: str, owned_file: str = "plan.md"
):
    """Build one real transaction and activate its repository partition."""
    repo, row, owned_file, branch, label = _prepared_publish_fixture(
        tmp_path, label=label, branch=branch, owned_file=owned_file
    )
    _activate_manifest(cutover_id=f"fabpub-live-{label}", rows=(row,))
    return _publish_request_for_active_repo(
        tmp_path, repo, owned_file, branch, label
    )


def _request(admission_key: str, *, verb: BrokerVerb = BrokerVerb.PUBLISH_COMMITTED_BRANCH) -> BrokerRequest:
    return BrokerRequest(verb, _admission(admission_key), "o/r", _BRANCH, _HEAD, ("plan.md",))


def _fake_git_gh(
    *, head: str = _HEAD, branch: str = _BRANCH,
    remote_sha: str | None = None, pr_head: str | None = None, pr_base: str = "main"
):
    """Return a fake ``run`` dispatching the adapter's git/gh calls."""

    remote_sha = head if remote_sha is None else remote_sha
    pr_head = head if pr_head is None else pr_head

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            sub = cmd[3:]  # after: git -C <path>
            if sub[:2] == ["branch", "--show-current"]:
                return CompletedProcess(cmd, 0, stdout=branch + "\n", stderr="")
            if sub[0] == "rev-parse":
                return CompletedProcess(cmd, 0, stdout=head + "\n", stderr="")
            if sub[0] == "diff":  # #202/#250 server-authoritative scope diff (owns plan.md), -z NUL-delimited
                return CompletedProcess(cmd, 0, stdout=b"plan.md\0", stderr=b"")
            if sub[0] == "log":
                return CompletedProcess(cmd, 0, stdout="commit subject line\n", stderr="")
            if sub[0] == "push":
                return CompletedProcess(cmd, 0, stdout="", stderr="")
            if sub[0] == "ls-remote":
                return CompletedProcess(cmd, 0, stdout=f"{remote_sha}\trefs/heads/{branch}\n", stderr="")
            if sub[:2] == ["remote", "get-url"]:
                return CompletedProcess(cmd, 0, stdout="https://github.com/owner/repo.git\n", stderr="")
        if cmd[0] == "gh":
            if cmd[1:3] == ["pr", "create"]:
                return CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd[1:3] == ["pr", "list"]:
                body = json.dumps([{"headRefOid": pr_head, "url": _URL, "baseRefName": pr_base}])
                return CompletedProcess(cmd, 0, stdout=body, stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    return fake_run


def _service(root: Path, worktree: Path, run) -> BrokerService:
    return BrokerService(
        LinearizableAdmissionStore(root, lambda _req: True),
        BrokerEvidenceStore(root),
        GitHubBrokerAdapter(worktree, run=run),
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,  # the REAL, verb-gated matrix
    )


# (a) --------------------------------------------------------------------------
def test_matching_remote_head_yields_effect_terminal_observed_with_real_url(tmp_path, request):
    activated = fabpub_migrated_activated(
        request,
        detail=(
            "the live publish path still admits a finalized AdmissionRequest; FABPUB "
            "requires a PreAdmissionEnvelope naming the resolved COMMITTED_HEAD_RESOLVED "
            "transaction plus a separately validated adapter_worktree"
        ),
    )
    if activated:
        repo, root, publish = _activated_publish_fixture(
            tmp_path, label="matching", branch=_BRANCH
        )
        run = _fake_git_gh(head=publish.head_sha, branch=publish.branch)
    else:
        repo = root = tmp_path
        root, publish = tmp_path, _request("key-1")
        run = _fake_git_gh()
    svc = _service(root, repo, run)
    result = svc.execute(publish)
    assert result.accepted
    assert result.evidence.terminal_state == "effect_terminal_observed"
    assert isinstance(result.publish_result, PublishCommittedBranchResult)
    assert result.publish_result.pr_url == _URL
    assert result.publish_result.head_sha == publish.head_sha


# (b) --------------------------------------------------------------------------
def test_remote_head_mismatch_fails_closed_to_ambiguous_not_success(tmp_path, request):
    activated = fabpub_migrated_activated(
        request,
        detail=(
            "fail-closed ambiguity is still proven through a finalized fresh publish; "
            "FABPUB routes it through the envelope plus admit_next"
        ),
    )
    # Remote advertises a DIFFERENT sha than we pushed: never inferred as no-effect,
    # never fabricated as success — a permanent ambiguous block.
    if activated:
        repo, root, publish = _activated_publish_fixture(
            tmp_path, label="mismatch", branch=_BRANCH
        )
        run = _fake_git_gh(
            head=publish.head_sha,
            branch=publish.branch,
            remote_sha="b" * 40,
        )
    else:
        repo = root = tmp_path
        root, publish = tmp_path, _request("key-1")
        run = _fake_git_gh(remote_sha="b" * 40)
    svc = _service(root, repo, run)
    result = svc.execute(publish)
    assert not result.accepted
    assert result.publish_result is None
    assert result.evidence.terminal_state == "outcome_ambiguous_blocked"


# (c) --------------------------------------------------------------------------
def test_idempotent_replay_returns_prior_result(tmp_path, request):
    activated = fabpub_migrated_activated(
        request,
        detail=(
            "completed-terminal replay must remain shape-agnostic without authorizing a "
            "fresh publish through an incomplete envelope"
        ),
    )
    if activated:
        repo, root, publish = _activated_publish_fixture(
            tmp_path, label="replay", branch=_BRANCH
        )
        run = _fake_git_gh(head=publish.head_sha, branch=publish.branch)
    else:
        repo, root, publish = None, tmp_path, _request("key-1")
        run = _fake_git_gh()
    calls = {"n": 0}

    def counting_run(cmd, **kwargs):
        if cmd[0] == "gh" and cmd[1:3] == ["pr", "create"]:
            calls["n"] += 1
        return run(cmd, **kwargs)

    svc = _service(root, repo or root, counting_run)
    first = svc.execute(publish)
    if activated:
        replay_request = BrokerRequest(
            publish.verb,
            _admission("key-2"),
            publish.repo,
            publish.branch,
            publish.head_sha,
            publish.owned_paths,
            adapter_worktree=str(repo),
        )
    else:
        replay_request = _request("key-2")
    replay = svc.execute(replay_request)  # DIFFERENT admission key, same triple
    assert calls["n"] == 1, "canonical triple must de-dup: one real effect only"
    assert replay.accepted
    assert replay.publish_result == first.publish_result
    assert replay.publish_result.pr_url == _URL


# (d) --------------------------------------------------------------------------
def test_only_publish_committed_branch_github_is_supported():
    supported = [
        (c.verb, c.provider)
        for c in PROVIDER_COMPLETION_CLASSIFICATIONS
        if c.classification is ProviderCompletionClassification.SUPPORTED
    ]
    assert supported == [("publish_committed_branch", "github")]
    # No non-github provider is present at all (absence == gated / fail-closed).
    assert all(c.provider == "github" for c in PROVIDER_COMPLETION_CLASSIFICATIONS)


@pytest.mark.parametrize("verb", [BrokerVerb.PUBLISH, BrokerVerb.MERGE, BrokerVerb.RELEASE, BrokerVerb.PACKAGE])
def test_every_other_verb_is_refused_before_start(tmp_path, verb):
    class _ExplodingAdapter:
        def execute(self, request):  # pragma: no cover - must never run
            raise AssertionError("gated verb must be refused before the adapter is called")

    svc = BrokerService(
        LinearizableAdmissionStore(tmp_path, lambda _req: True),
        BrokerEvidenceStore(tmp_path),
        _ExplodingAdapter(),
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
    )
    result = svc.execute(_request("key-1", verb=verb))
    assert not result.accepted
    assert result.reason == "provider_not_supported"
    assert result.evidence.terminal_state == "rejected_before_start"


# (e) --------------------------------------------------------------------------
def test_live_broker_builder_constructs_working_client(tmp_path, request):
    _fabpub = fabpub_migrated_activated(
        request,
        detail=(
            "the activated production builder must reject caller-selected allocator roots; "
            "an explicit-root constructor is test-only"
        ),
    )
    broker_root = tmp_path / "coordinator"  # OUTSIDE the worktree by construction
    repo_path = tmp_path / "worktree"
    if _fabpub:
        with pytest.raises((TypeError, ValueError, PermissionError, RuntimeError)):
            build_routing_broker_client(broker_root=broker_root)
        assert not broker_root.exists()
        repo_path, _root, publish = _activated_publish_fixture(
            tmp_path, label="builder", branch=_BRANCH
        )
        client = build_routing_broker_client(
            run=_fake_git_gh(head=publish.head_sha, branch=publish.branch)
        )
        result = client.execute(publish)
        assert result.accepted
        assert result.publish_result.pr_url == _URL
        assert result.publish_result.head_sha == publish.head_sha
        return
    client = build_github_broker_client(
        repo_path,
        broker_root=broker_root,
        run=_fake_git_gh(),
    )
    result = client.execute(_request("key-1"))
    assert result.accepted
    assert result.publish_result.pr_url == _URL
    # Broker state is durable under broker_root, never inside the published worktree.
    assert (broker_root / "evidence.jsonl").exists()
    assert not (repo_path / "evidence.jsonl").exists()


# (f) Routing broker: ONE client serves a MULTI-repo train ---------------------
def _routing_fake(repos, seen_paths):
    """git/gh fake that responds PER repo path, recording which path git ran under."""

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            path = cmd[2]  # after: git -C <path>
            seen_paths.append(path)
            meta = repos[path]
            sub = cmd[3:]
            if sub[:2] == ["branch", "--show-current"]:
                return CompletedProcess(cmd, 0, stdout=meta["branch"] + "\n", stderr="")
            if sub[0] == "rev-parse":
                return CompletedProcess(cmd, 0, stdout=meta["head"] + "\n", stderr="")
            if sub[0] == "diff":  # #202/#250 server-authoritative scope diff (owns plan.md), -z NUL-delimited
                return CompletedProcess(cmd, 0, stdout=b"plan.md\0", stderr=b"")
            if sub[0] == "log":
                return CompletedProcess(cmd, 0, stdout=f"{meta['branch']} subject\n", stderr="")
            if sub[0] == "push":
                return CompletedProcess(cmd, 0, stdout="", stderr="")
            if sub[0] == "ls-remote":
                return CompletedProcess(cmd, 0, stdout=f'{meta["head"]}\trefs/heads/{meta["branch"]}\n', stderr="")
            if sub[:2] == ["remote", "get-url"]:
                return CompletedProcess(cmd, 0, stdout="https://github.com/owner/repo.git\n", stderr="")
        if cmd[0] == "gh":
            meta = repos[str(kwargs.get("cwd"))]
            if cmd[1:3] == ["pr", "create"]:
                return CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd[1:3] == ["pr", "list"]:
                return CompletedProcess(cmd, 0, stdout=json.dumps([{"headRefOid": meta["head"], "url": meta["url"], "baseRefName": meta.get("base", "main")}]), stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    return fake_run


def _routing_request(repo_path, meta, key):
    admission = AdmissionRequest("attempt", 1, "fence", "digest", "head == committed", "scope", key)
    return BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, admission, repo_path, meta["branch"], meta["head"], ("plan.md",), base=meta.get("base", "main"))


def _activated_routing_cases(tmp_path: Path):
    repos = {}
    requests = {}
    prepared = []
    for label in ("alpha", "beta"):
        branch = f"feat/{label}"
        prepared.append(_prepared_publish_fixture(
            tmp_path, label=label, branch=branch
        ))
    _activate_manifest(
        cutover_id="fabpub-live-routing",
        rows=tuple(item[1] for item in prepared),
    )
    for label, (repo, _row, owned_file, branch, fixture_label) in zip(
        ("alpha", "beta"), prepared, strict=True
    ):
        _repo, _root, publish = _publish_request_for_active_repo(
            tmp_path, repo, owned_file, branch, fixture_label
        )
        path = str(repo)
        repos[path] = {
            "branch": branch,
            "head": publish.head_sha,
            "url": f"https://gh/pr/{label}",
        }
        requests[label] = publish
    return repos, requests


def test_routing_broker_binds_each_request_to_its_own_repo(tmp_path, request):
    activated = fabpub_migrated_activated(
        request,
        detail=(
            "routing still binds the adapter to BrokerRequest.repo as a worktree PATH; "
            "FABPUB keeps repo as CanonicalRepositoryIdentity.v1 and binds the adapter "
            "to the separately typed adapter_worktree"
        ),
    )
    if activated:
        repos, requests = _activated_routing_cases(tmp_path)
    else:
        repos = {
            "/ws/alpha": {"branch": "feat/alpha", "head": "a" * 40, "url": "https://gh/pr/alpha"},
            "/ws/beta": {"branch": "feat/beta", "head": "b" * 40, "url": "https://gh/pr/beta"},
        }
        requests = {}
    seen_paths: list = []
    run = _routing_fake(repos, seen_paths)
    broker = (
        build_routing_broker_client(run=run)
        if activated
        else build_routing_broker_client(broker_root=tmp_path / "coord", run=run)
    )

    for label, (path, meta) in zip(("alpha", "beta"), repos.items(), strict=True):
        publish = requests[label] if activated else _routing_request(path, meta, key=f"k-{path}")
        result = broker.execute(publish)
        assert result.accepted, f"{path} not accepted"
        assert result.publish_result.pr_url == meta["url"], f"{path} routed to the wrong repo's PR"
        assert result.publish_result.head_sha == meta["head"]

    # Each node's git ran under ITS OWN worktree path — the whole point of routing.
    assert set(repos).issubset(seen_paths)


def test_routing_broker_dedups_within_a_repo_not_across(tmp_path, request):
    activated = fabpub_migrated_activated(
        request,
        detail=(
            "de-dup is still scoped by a worktree-path slug; FABPUB scopes it by the "
            "canonical git-common-dir repository namespace"
        ),
    )
    # Each repo has its OWN store, and within a repo the de-dup key
    # sha256(repo\0branch\0head) makes a replay under a fresh admission key return the
    # prior result; a different repo is a distinct store + triple (a real second effect).
    if activated:
        repos, requests = _activated_routing_cases(tmp_path)
        alpha_path, beta_path = tuple(repos)
    else:
        repos = {
            "/ws/alpha": {"branch": "feat/alpha", "head": "a" * 40, "url": "https://gh/pr/alpha"},
            "/ws/beta": {"branch": "feat/beta", "head": "b" * 40, "url": "https://gh/pr/beta"},
        }
        requests = {}
        alpha_path, beta_path = "/ws/alpha", "/ws/beta"
    creates = {"n": 0}

    def counting(cmd, **kwargs):
        if cmd[0] == "gh" and cmd[1:3] == ["pr", "create"]:
            creates["n"] += 1
        return _routing_fake(repos, [])(cmd, **kwargs)

    broker = (
        build_routing_broker_client(run=counting)
        if activated
        else build_routing_broker_client(broker_root=tmp_path / "coord", run=counting)
    )
    alpha = requests["alpha"] if activated else _routing_request(alpha_path, repos[alpha_path], key="k1")
    beta = requests["beta"] if activated else _routing_request(beta_path, repos[beta_path], key="k3")
    first = broker.execute(alpha)
    replay_request = (
        BrokerRequest(
            alpha.verb,
            _admission("k2-different"),
            alpha.repo,
            alpha.branch,
            alpha.head_sha,
            alpha.owned_paths,
            adapter_worktree=str(alpha_path),
        )
        if activated
        else _routing_request(alpha_path, repos[alpha_path], key="k2-different")
    )
    replay = broker.execute(replay_request)
    other = broker.execute(beta)

    assert creates["n"] == 2, "alpha's replay must de-dup (1 real effect); beta is a distinct triple"
    assert replay.publish_result == first.publish_result
    assert other.publish_result.pr_url == repos[beta_path]["url"]


def test_one_repo_ambiguous_outcome_does_not_poison_other_repos(tmp_path, request):
    activated = fabpub_migrated_activated(
        request,
        detail=(
            "ambiguity isolation is still per worktree-path slug; after FABPUB permanent "
            "ambiguity is REPOSITORY-scoped (all linked worktrees and train roots of one "
            "canonical repository share it), not per-train"
        ),
    )
    """A benign transient making repo alpha's publish ambiguous must NOT fail-close beta.

    ``epoch_blocked`` is a global scan over a store, an ambiguous terminal is durable +
    permanent, and it fires on benign transients (here: alpha's ls-remote read fails).
    With a SHARED store this would set the global epoch and beta would raise
    ``PermissionError('epoch permanently blocked')``.  Per-repo stores scope the
    fail-closed epoch to ONLY alpha (agent-harness#208 CR).
    """
    if activated:
        repos, requests = _activated_routing_cases(tmp_path)
        alpha_path, beta_path = tuple(repos)
    else:
        repos = {
            "/ws/alpha": {"branch": "feat/alpha", "head": "a" * 40, "url": "https://gh/pr/alpha"},
            "/ws/beta": {"branch": "feat/beta", "head": "b" * 40, "url": "https://gh/pr/beta"},
        }
        requests = {}
        alpha_path, beta_path = "/ws/alpha", "/ws/beta"

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            path = cmd[2]
            meta = repos[path]
            sub = cmd[3:]
            if sub[:2] == ["branch", "--show-current"]:
                return CompletedProcess(cmd, 0, stdout=meta["branch"] + "\n", stderr="")
            if sub[0] == "rev-parse":
                return CompletedProcess(cmd, 0, stdout=meta["head"] + "\n", stderr="")
            if sub[0] == "diff":  # #202/#250 server-authoritative scope diff (owns plan.md), -z NUL-delimited
                return CompletedProcess(cmd, 0, stdout=b"plan.md\0", stderr=b"")
            if sub[0] == "log":
                return CompletedProcess(cmd, 0, stdout="subject\n", stderr="")
            if sub[0] == "push":
                return CompletedProcess(cmd, 0, stdout="", stderr="")
            if sub[0] == "ls-remote":
                if path == alpha_path:  # benign transient: remote read fails -> ambiguous
                    return CompletedProcess(cmd, 1, stdout="", stderr="network hiccup")
                return CompletedProcess(cmd, 0, stdout=f'{meta["head"]}\trefs/heads/{meta["branch"]}\n', stderr="")
            if sub[:2] == ["remote", "get-url"]:
                return CompletedProcess(cmd, 0, stdout="https://github.com/owner/repo.git\n", stderr="")
        if cmd[0] == "gh":
            meta = repos[str(kwargs.get("cwd"))]
            if cmd[1:3] == ["pr", "create"]:
                return CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd[1:3] == ["pr", "list"]:
                return CompletedProcess(cmd, 0, stdout=json.dumps([{"headRefOid": meta["head"], "url": meta["url"], "baseRefName": meta.get("base", "main")}]), stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    broker = (
        build_routing_broker_client(run=fake_run)
        if activated
        else build_routing_broker_client(broker_root=tmp_path / "coord", run=fake_run)
    )

    alpha_request = requests["alpha"] if activated else _routing_request(alpha_path, repos[alpha_path], key="ka")
    alpha = broker.execute(alpha_request)
    assert not alpha.accepted
    assert alpha.evidence.terminal_state == "outcome_ambiguous_blocked"

    # beta must still publish — alpha's ambiguous epoch is scoped to alpha's store.
    beta_request = requests["beta"] if activated else _routing_request(beta_path, repos[beta_path], key="kb")
    beta = broker.execute(beta_request)
    assert beta.accepted, "beta was fail-closed by alpha's ambiguous outcome (shared-epoch poison)"
    assert beta.publish_result.pr_url == repos[beta_path]["url"]
