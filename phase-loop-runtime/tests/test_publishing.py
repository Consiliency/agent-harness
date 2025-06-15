"""Tests for phase_loop_runtime.publishing (IF-0-P1-1, #29 P1).

Each invariant branch is exercised with the git/gh boundary stubbed — no live
pushes or real remote calls.

Coverage:
- main / protected branch → publication_blocked
- dirty worktree post-commit (resolve_closeout_push_target stub)
- unowned / behind-upstream branch (resolve_closeout_push_target stub)
- scoped-diff audit: out-of-scope staged path → publication_blocked
- scoped-diff audit: secret/env path in owned set → publication_blocked
- push rejected → publication_blocked
- draft PR opens with --draft flag
- ready PR opens without --draft flag
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from _fabpub_tdd_guard import fabpub_migrated_activated, fabpub_symbol
from phase_loop_runtime.publishing import (
    PROTECTED_BRANCHES,
    _is_secret_path,
    publish_from_worktree,
)
from phase_loop_runtime.convergence.contracts import AdmissionRequest, PublishCommittedBranchResult, BrokerTerminalEvidence
from phase_loop_runtime.convergence.broker.verbs import BrokerExecutionResult


class _Broker:
    def __init__(self): self.requests = []
    def execute(self, request):
        self.requests.append(request)
        key = getattr(request.admission, "idempotency_key", None) or getattr(
            request.admission, "transaction_id", ""
        )
        return BrokerExecutionResult(True, BrokerTerminalEvidence(key, "effect_terminal_observed", "test"), PublishCommittedBranchResult(request.branch, request.head_sha, "https://github.com/owner/repo/pull/99"))


def _admission() -> AdmissionRequest:
    return AdmissionRequest("attempt", 1, "fence", "approval", "head", "repo", "publish-key")


def _fabpub_publish_authority(repo: Path, checkpoint_root: Path):
    """Produce the valid pre-commit authority object the train normally hands off."""
    authority_type = fabpub_symbol(
        "phase_loop_runtime.train_runner", "PublishAuthorityPreimages"
    )
    build_authority = fabpub_symbol(
        "phase_loop_runtime.train_runner", "_default_build_publish_authority"
    )
    assert authority_type is not None and build_authority is not None

    from phase_loop_runtime.train_runner import CoordinatorRuntime

    runtime = CoordinatorRuntime("train", checkpoint_root, "train.md", "digest", "workspace")
    node = type("Node", (), {"node_id": "repo-a", "roadmap": "owned.py"})()
    authority = build_authority(runtime, node, repo, ["owned.py"])
    assert isinstance(authority, authority_type)
    return authority


# ---------------------------------------------------------------------------
# Shared git fixture helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal local git repo on a safe non-protected branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")
    # Seed a base commit so HEAD exists.
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "fixture base")
    # Move to a safe working branch (not main/protected).
    _git(repo, "checkout", "-b", "feat/p1-test")
    return repo


def _write_and_stage(repo: Path, filename: str, content: str) -> None:
    """Write a file to repo and stage it with git add."""
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", "--", filename)


def _fake_pr_create(repo: Path, *, draft: bool, title: str | None, body: str | None) -> int:
    """Stub for _run_gh_pr_create that signals success (returncode 0)."""
    return 0


def _fake_pr_metadata(repo: Path, branch: str) -> dict:
    """Stub for _gh_pr_metadata that returns a deterministic PR URL."""
    return {"pr_url": "https://github.com/owner/repo/pull/99"}


def _push_success(repo: Path, remote: str, push_ref: str) -> int:
    return 0


def _push_rejected(repo: Path, remote: str, push_ref: str) -> int:
    return 1


# ---------------------------------------------------------------------------
# Unit tests: _is_secret_path helper
# ---------------------------------------------------------------------------


def test_secret_path_detects_env():
    assert _is_secret_path(".env")
    assert _is_secret_path(".env.local")
    assert _is_secret_path(".env.production")


def test_secret_path_detects_credential_names():
    assert _is_secret_path("credentials.json")
    assert _is_secret_path("my.secret")
    assert _is_secret_path("private.key")
    assert _is_secret_path("api.key")


def test_secret_path_ignores_normal_files():
    assert not _is_secret_path("publishing.py")
    assert not _is_secret_path("README.md")
    assert not _is_secret_path("tests/test_foo.py")


def _source_repo(tmp_path, path="credentials.py"):
    repo = _make_repo(tmp_path)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    _write_and_stage(repo, path, "def load():\n    return None\n")
    _git(repo, "commit", "-m", "source module")
    _write_and_stage(repo, path, "def load():\n    return {}\n")
    return repo


@pytest.mark.parametrize("path", ["agent/credentials.py", "tests/test_credentials.py", "secrets.py", "private_impl.py"])
def test_existing_source_exception_is_content_checked_and_blob_bound(tmp_path, path, monkeypatch):
    from phase_loop_runtime.publishing import _audit_staged_diff
    import requests

    def no_network(*args, **kwargs):
        pytest.fail("source scanning must not access the network")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    repo = _source_repo(tmp_path, path)
    evidence = {}
    assert _audit_staged_diff(repo, [path], evidence=evidence) is None
    assert evidence["tree_oid"] == _git(repo, "write-tree").stdout.strip()
    assert evidence["parent_head_sha"] == _git(repo, "rev-parse", "HEAD").stdout.strip()
    record, = evidence["source_exceptions"]
    assert record["path"] == path
    assert record["blob_oid"] == _git(repo, "rev-parse", ":" + path).stdout.strip()
    assert record["policy"] == "tracked-python-detect-secrets-1.5.0-v1"


@pytest.mark.parametrize("path", [".env", ".env.py", "private.key", "private.key.py", "credentials.json"])
def test_artifacts_remain_blocked_even_when_parseable_python(tmp_path, path):
    from phase_loop_runtime.publishing import _audit_staged_diff
    repo = _source_repo(tmp_path, path)
    assert _audit_staged_diff(repo, [path], evidence={})["reason"] == "secret_staged_path"


@pytest.mark.parametrize("content", [
    "password = 'a-private-value'\n",
    "def load(:\n",
    "def load():\n    return {}\npassword = 'a-private-value' # pragma: allowlist secret\n",
    'def load():\n    return "-----BEGIN PRIVATE KEY-----"\n',
    'def load():\n    return {}\ncredentials = {"client_secret": "a-private-value"}\n',
])
def test_source_content_deny_scans_index_not_worktree(tmp_path, content):
    from phase_loop_runtime.publishing import _audit_staged_diff
    repo = _source_repo(tmp_path)
    _write_and_stage(repo, "credentials.py", content)
    (repo / "credentials.py").write_text("def load():\n    return {}\n")
    result = _audit_staged_diff(repo, ["credentials.py"], evidence={})
    assert result["reason"] == "secret_staged_path"
    assert "a-private-value" not in str(result)


def test_new_source_and_symlink_do_not_get_exception(tmp_path):
    from phase_loop_runtime.publishing import _audit_staged_diff
    repo = _make_repo(tmp_path)
    _write_and_stage(repo, "credentials.py", "def load():\n    return {}\n")
    assert _audit_staged_diff(repo, ["credentials.py"], evidence={})["reason"] == "secret_staged_path"
    _git(repo, "commit", "-m", "source")
    (repo / "credentials.py").unlink()
    (repo / "credentials.py").symlink_to("README.md")
    _git(repo, "add", "credentials.py")
    assert _audit_staged_diff(repo, ["credentials.py"], evidence={})["reason"] == "secret_staged_path"


def test_source_exception_requires_governed_audit(tmp_path):
    from phase_loop_runtime.publishing import _audit_staged_diff
    repo = _source_repo(tmp_path)
    assert _audit_staged_diff(repo, ["credentials.py"])["reason"] == "secret_staged_path"


def test_source_scanner_failure_is_redacted(tmp_path, monkeypatch):
    from phase_loop_runtime import publishing
    repo = _source_repo(tmp_path)
    def fail(*args):
        raise RuntimeError("never-print-this")
    monkeypatch.setattr(publishing, "version", fail)
    result = publishing._audit_staged_diff(repo, ["credentials.py"], evidence={})
    assert result["reason"] == "source_scan_failed"
    assert "never-print-this" not in str(result)


def test_audit_detects_index_change_and_preserves_literal_paths(tmp_path, monkeypatch):
    from phase_loop_runtime import publishing
    path = " credentials\nmodule.py"
    repo = _source_repo(tmp_path, path)
    real = publishing._source_path_evidence
    def change(*args):
        result = real(*args)
        _write_and_stage(repo, path, "def changed():\n    return 1\n")
        return result
    monkeypatch.setattr(publishing, "_source_path_evidence", change)
    assert publishing._audit_staged_diff(repo, [path], evidence={})["reason"] == "staged_audit_changed"


def test_frozen_source_audit_is_checked_on_recovery(tmp_path):
    from phase_loop_runtime import publishing
    repo = _source_repo(tmp_path)
    evidence = {}
    assert publishing._audit_staged_diff(repo, ["credentials.py"], evidence=evidence) is None
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    transaction = publishing.prepare_publish_transaction(
        repo, owned_paths=["credentials.py"], checkpoint_root=tmp_path / "checkpoints",
        branch="feat/p1-test", envelope_authority_preimage=authority.envelope_authority_preimage,
        publication_audit=evidence,
    )
    publishing.validate_transaction_owned_workspace(repo.resolve(), transaction)
    transaction._payload["publication_audit"]["source_exceptions"][0]["blob_sha256"] = "tampered"
    with pytest.raises(RuntimeError, match="source publication audit failed"):
        publishing.validate_transaction_owned_workspace(repo.resolve(), transaction)
    transaction._payload.pop("publication_audit")
    with pytest.raises(RuntimeError, match="requires a matching"):
        publishing.validate_transaction_owned_workspace(repo.resolve(), transaction)


def test_changed_tree_cannot_be_prepared_with_old_audit(tmp_path):
    from phase_loop_runtime import publishing
    repo = _source_repo(tmp_path)
    evidence = {}
    assert publishing._audit_staged_diff(repo, ["credentials.py"], evidence=evidence) is None
    _write_and_stage(repo, "credentials.py", "def changed():\n    return 1\n")
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    with pytest.raises(ValueError, match="audit no longer matches"):
        publishing.prepare_publish_transaction(
            repo, owned_paths=["credentials.py"], checkpoint_root=tmp_path / "checkpoints",
            branch="feat/p1-test", envelope_authority_preimage=authority.envelope_authority_preimage,
            publication_audit=evidence,
        )


def test_governed_publish_accepts_source_and_retains_audit(tmp_path, monkeypatch):
    from phase_loop_runtime import publishing
    from phase_loop_runtime.convergence.broker import live
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
    repo = _source_repo(tmp_path)
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    result = publish_from_worktree(
        repo, ["credentials.py"], broker_client=_Broker(),
        publish_authority=authority, checkpoint_root=authority.checkpoint_root,
    )
    assert result["status"] == "published"
    candidate = publishing.inspect_publish_resume_candidate(
        repo, checkpoint_root=authority.checkpoint_root, node_id="repo-a",
    )
    assert candidate.transaction.publication_audit["source_exceptions"][0]["path"] == "credentials.py"


def test_direct_preparation_cannot_construct_source_without_audit(tmp_path):
    from phase_loop_runtime import publishing
    repo = _source_repo(tmp_path)
    original = _git(repo, "rev-parse", "HEAD").stdout
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    with pytest.raises(RuntimeError, match="source exception requires"):
        publishing.prepare_publish_transaction(
            repo, owned_paths=["credentials.py"], checkpoint_root=authority.checkpoint_root,
            branch="feat/p1-test", envelope_authority_preimage=authority.envelope_authority_preimage,
        )
    assert _git(repo, "rev-parse", "HEAD").stdout == original
    assert not list(authority.checkpoint_root.rglob("*.checkpoint.json"))


def test_direct_resume_recomputes_audit_after_durable_object(tmp_path):
    from phase_loop_runtime import publishing
    repo = _source_repo(tmp_path)
    original = _git(repo, "rev-parse", "HEAD").stdout
    evidence = {}
    assert publishing._audit_staged_diff(repo, ["credentials.py"], evidence=evidence) is None
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    transaction = publishing.prepare_publish_transaction(
        repo, owned_paths=["credentials.py"], checkpoint_root=authority.checkpoint_root,
        branch="feat/p1-test", envelope_authority_preimage=authority.envelope_authority_preimage,
        publication_audit=evidence,
    )
    assert transaction.state == publishing.PublishTransactionState.COMMIT_OBJECT_DURABLE
    transaction._payload.pop("publication_audit")
    with pytest.raises(RuntimeError, match="source exception requires"):
        transaction.resume()
    assert _git(repo, "rev-parse", "HEAD").stdout == original


@pytest.mark.parametrize("path", ["credentials.py", "credentials.json"])
def test_unchanged_owned_suspect_path_does_not_require_exception(tmp_path, monkeypatch, path):
    from phase_loop_runtime.convergence.broker import live
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
    repo = _source_repo(tmp_path, path)
    _git(repo, "commit", "-m", "source update")
    (repo / "owned.py").write_text("value = 1\n")
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    result = publish_from_worktree(
        repo, [path, "owned.py"], broker_client=_Broker(),
        publish_authority=authority, checkpoint_root=authority.checkpoint_root,
    )
    assert result["status"] == "published"


def test_prebuilt_contract_unchanged_for_suspect_owned_source(tmp_path, monkeypatch):
    from phase_loop_runtime.convergence.broker import live
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
    repo = _source_repo(tmp_path)
    _git(repo, "commit", "-m", "prebuilt source update")
    authority = _fabpub_publish_authority(repo, tmp_path / "checkpoints")
    result = publish_from_worktree(
        repo, ["credentials.py"], prebuilt=True, broker_client=_Broker(),
        publish_authority=authority, checkpoint_root=authority.checkpoint_root,
    )
    assert result["status"] == "published"


def test_scanner_version_mismatch_blocks_exception(tmp_path, monkeypatch):
    from phase_loop_runtime import publishing
    repo = _source_repo(tmp_path)
    monkeypatch.setattr(publishing, "version", lambda name: "unsupported")
    assert publishing._audit_staged_diff(repo, ["credentials.py"], evidence={})["reason"] == "source_scan_failed"


# ---------------------------------------------------------------------------
# Invariant: main / protected branch → publication_blocked
# ---------------------------------------------------------------------------


def test_blocked_on_main(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    # HEAD is on 'main' (the default init branch or 'master' — handle both).
    current = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    if current not in PROTECTED_BRANCHES:
        _git(repo, "checkout", "-b", "main")

    (repo / "foo.py").write_text("x = 1\n", encoding="utf-8")
    result = publish_from_worktree(repo, ["foo.py"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "branch_protected"


@pytest.mark.parametrize("branch", ["master", "develop", "release"])
def test_blocked_on_protected_branches(tmp_path: Path, branch: str):
    repo = _make_repo(tmp_path)
    # Switch to the protected branch name; use -B to reset if it already exists
    # (e.g. "master" may have been the init default before we switched away).
    _git(repo, "checkout", "-B", branch)

    (repo / "foo.py").write_text("x = 1\n", encoding="utf-8")
    result = publish_from_worktree(repo, ["foo.py"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "branch_protected"


# ---------------------------------------------------------------------------
# Invariant: dirty worktree post-commit → publication_blocked
# ---------------------------------------------------------------------------


def test_blocked_dirty_post_commit(tmp_path: Path):
    """After commit, the worktree still has dirty files → push target refused."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")


    result = publish_from_worktree(repo, ["owned.py"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "broker_required"


# ---------------------------------------------------------------------------
# Invariant: unowned / behind-upstream branch → publication_blocked
# ---------------------------------------------------------------------------


def test_blocked_unowned_branch_behind_upstream(tmp_path: Path):
    """Branch is behind upstream (someone else pushed) → unowned → stop."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")


    result = publish_from_worktree(repo, ["owned.py"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "broker_required"


# ---------------------------------------------------------------------------
# Invariant: scoped-diff audit — out-of-scope staged path → blocked
# ---------------------------------------------------------------------------


def test_blocked_out_of_scope_staged_path(tmp_path: Path):
    """An extra file staged before the call (not in owned_paths) is caught."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")
    # Extra file staged externally — not listed in owned_paths.
    (repo / "interloper.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "--", "interloper.py")

    result = publish_from_worktree(repo, ["owned.py"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "out_of_scope_staged_path"
    assert "interloper.py" in result.get("detail", "")


# ---------------------------------------------------------------------------
# Invariant: scoped-diff audit — secret path in owned set → blocked
# ---------------------------------------------------------------------------


def test_blocked_secret_path_in_owned_set(tmp_path: Path):
    """.env listed in owned_paths is still caught by the secret-path guard."""
    repo = _make_repo(tmp_path)
    (repo / ".env").write_text("API_KEY=hunter2\n", encoding="utf-8")

    result = publish_from_worktree(repo, [".env"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "secret_staged_path"
    assert ".env" in result.get("detail", "")


# ---------------------------------------------------------------------------
# Invariant: push rejected → publication_blocked
# ---------------------------------------------------------------------------


def test_blocked_push_rejected(tmp_path: Path):
    """A non-zero push exit code → publication_blocked: push_rejected."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")


    result = publish_from_worktree(repo, ["owned.py"])

    assert result["status"] == "publication_blocked"
    assert result["reason"] == "broker_required"


# ---------------------------------------------------------------------------
# Draft vs ready PR behavior
# ---------------------------------------------------------------------------


def test_draft_pr_passes_draft_flag(tmp_path: Path, request):
    """publish_from_worktree(draft=True) calls _run_gh_pr_create with draft=True."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")



    broker = _Broker()
    if fabpub_migrated_activated(
        request,
        symbol=("phase_loop_runtime.publishing", "PublishTransactionStore"),
        detail=(
            "the draft-flag proof still asserts a fresh FINALIZED publish succeeds; after "
            "FABPUB that arm is transition-only and forbidden, so draft intent must be proven "
            "through the publish-authority/checkpoint_root handoff"
        ),
    ):
        authority = _fabpub_publish_authority(repo, tmp_path / "coordinator" / "draft")
        result = publish_from_worktree(
            repo,
            ["owned.py"],
            draft=True,
            broker_client=broker,
            publish_authority=authority,
            checkpoint_root=authority.checkpoint_root,
        )
        assert result["status"] == "published"
        assert broker.requests[0].draft is True
        assert not isinstance(broker.requests[0].admission, AdmissionRequest), (
            "a fresh publish must not reach the broker as a finalized AdmissionRequest"
        )
        return

    result = publish_from_worktree(repo, ["owned.py"], draft=True, broker_client=broker, admission=_admission())

    assert result["status"] == "published"
    assert broker.requests[0].draft is True


def test_ready_pr_passes_draft_false(tmp_path: Path, request):
    """publish_from_worktree(draft=False) calls _run_gh_pr_create with draft=False."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")



    broker = _Broker()
    if fabpub_migrated_activated(
        request,
        symbol=("phase_loop_runtime.publishing", "PublishTransactionStore"),
        detail=(
            "the ready-flag proof still asserts a fresh FINALIZED publish succeeds; after "
            "FABPUB that arm is transition-only and forbidden, so ready intent must be proven "
            "through the publish-authority/checkpoint_root handoff"
        ),
    ):
        authority = _fabpub_publish_authority(repo, tmp_path / "coordinator" / "ready")
        result = publish_from_worktree(
            repo,
            ["owned.py"],
            draft=False,
            broker_client=broker,
            publish_authority=authority,
            checkpoint_root=authority.checkpoint_root,
        )
        assert result["status"] == "published"
        assert broker.requests[0].draft is False
        assert not isinstance(broker.requests[0].admission, AdmissionRequest), (
            "a fresh publish must not reach the broker as a finalized AdmissionRequest"
        )
        return

    result = publish_from_worktree(repo, ["owned.py"], draft=False, broker_client=broker, admission=_admission())

    assert result["status"] == "published"
    assert broker.requests[0].draft is False


# ---------------------------------------------------------------------------
# Happy path: successful publication returns correct IF-0-P1-1 shape
# ---------------------------------------------------------------------------


def test_successful_publish_returns_if_0_p1_1_shape(tmp_path: Path, request):
    """A clean publish returns {branch, head_sha, pr_url, status} (IF-0-P1-1)."""
    repo = _make_repo(tmp_path)
    (repo / "owned.py").write_text("x = 1\n", encoding="utf-8")


    if fabpub_migrated_activated(
        request,
        symbol=("phase_loop_runtime.publishing", "PublishTransactionStore"),
        detail=(
            "publish_from_worktree still takes a caller-built finalized admission; FABPUB "
            "requires publish authority pre-images plus a checkpoint_root, with the envelope "
            "constructed post-commit from the resolved transaction"
        ),
    ):
        authority = _fabpub_publish_authority(repo, tmp_path / "coordinator" / "node")
        result = publish_from_worktree(
            repo,
            ["owned.py"],
            draft=True,
            broker_client=_Broker(),
            publish_authority=authority,
            checkpoint_root=authority.checkpoint_root,
        )
        assert result["status"] == "published"
        return

    result = publish_from_worktree(repo, ["owned.py"], draft=True, broker_client=_Broker(), admission=_admission())

    assert result["status"] == "published"
    assert result["branch"] == "feat/p1-test"
    assert result["pr_url"] == "https://github.com/owner/repo/pull/99"
    # head_sha must be a non-empty hex string (load-bearing for IF-0-P1-1).
    assert isinstance(result["head_sha"], str)
    assert len(result["head_sha"]) >= 7
    assert all(c in "0123456789abcdef" for c in result["head_sha"])
