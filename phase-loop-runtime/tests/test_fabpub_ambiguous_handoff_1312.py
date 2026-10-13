"""Consiliency/agent-harness#1312: an ambiguous publication gets the rotation handoff.

A human publication whose provider outcome is ``outcome_ambiguous_blocked``
blocks its key in the active partition generation until an operator rotation
adjudicates the effect.  Every retry before that rotation replays the block
from evidence.  The human route used to answer that replay with the generic
``repair_publication_precheck_and_retry`` handoff, which no retry can satisfy.
These tests drive the block through the real human route (zero-history
bootstrap, real barrier and router); only the GitHub adapter is replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_shared_epoch import _CountingAdapter, _jsonl
from test_publishing import _git, _human_publish_artifacts, _make_repo

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

AMBIGUOUS = "outcome_ambiguous_blocked"
ROTATION_STEP = "adjudicate_publication_by_partition_rotation"
GENERIC_STEP = "repair_publication_precheck_and_retry"


def _human_route(tmp_path, monkeypatch, adapter):
    """A FABPUB-authorized repository whose live GitHub adapter is ``adapter``."""
    from phase_loop_runtime import publishing
    from phase_loop_runtime.convergence.broker import live

    repo = _make_repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    plan, verification = _human_publish_artifacts(tmp_path)
    (repo / "owned.py").write_text("value = 1\n", encoding="utf-8")
    authority_root = tmp_path / "authority"
    inventory = live.probe_zero_history_bootstrap(
        cutover_id="ambiguous-handoff-1312",
        authority_root=authority_root,
        worktrees=(repo,),
    )
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(authority_root))
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
    monkeypatch.setattr(publishing, "_check_gh_auth", lambda: None)
    monkeypatch.setattr(
        live.GitHubBrokerAdapter, "execute", lambda _self, request: adapter.execute(request)
    )

    def publish():
        result = publishing.publish_human_invoked_from_worktree(
            repo, ["owned.py"], plan_path=plan, verification_artifact_path=verification
        )
        assert live.WriterGenerationLatch.open(repo).held_leases() == ()
        return result

    return repo, publish


def _assert_rotation_handoff(result, repo: Path):
    assert result["status"] == "publication_blocked", result
    assert result["terminal_state"] == AMBIGUOUS
    handoff = result["handoff"]
    assert handoff["schema"] == "HumanPublicationHandoff.v1"
    assert handoff["next_step"] == ROTATION_STEP
    assert handoff["recovery_procedure"].startswith("docs/fabpub-partition-rotation-runbook.md")
    assert "8a" in handoff["recovery_procedure"]
    command = handoff["rotate_command"]
    assert command[:2] == ["phase-loop", "fabpub-rotate-partition"]
    assert command[command.index("--worktree") + 1] == str(repo.resolve())
    assert "--attestation" in command and "--cutover-id" in command
    assert "observed_landed" in handoff["rotate_requires"]
    assert "attested_not_landed" in handoff["rotate_requires"]
    assert "not proof" in handoff["rotate_requires"]
    assert "restart any broker process" in handoff["after_rotation"]
    assert handoff["resume"].startswith("only after the rotation")
    assert "checkpoint_root" in result


def _evidence_states(repo: Path) -> list[str]:
    from phase_loop_runtime.convergence.broker import live

    store_root = live.repository_snapshot(repo).store_root
    return [row["state"] for row in _jsonl(Path(store_root) / "evidence.jsonl")]


def test_retry_of_an_ambiguous_key_gets_the_rotation_handoff(tmp_path, monkeypatch):
    """The issue: the retry replays ``outcome_ambiguous_blocked`` and must say "rotate"."""
    adapter = _CountingAdapter(terminal_state=AMBIGUOUS)
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)

    first = publish()
    assert len(adapter.calls) == 1
    assert first["reason"] == AMBIGUOUS
    _assert_rotation_handoff(first, repo)
    assert _evidence_states(repo)[-1] == AMBIGUOUS

    retry = publish()
    assert len(adapter.calls) == 1, "the retry reached the provider: it was not a replay"
    assert retry["reason"] == AMBIGUOUS
    _assert_rotation_handoff(retry, repo)
    assert retry["handoff"]["rotate_command"] == first["handoff"]["rotate_command"]


def test_adapter_exception_gets_the_rotation_handoff(tmp_path, monkeypatch):
    """An adapter exception names reason ``outcome_ambiguous``; the typed state decides."""
    adapter = _CountingAdapter(explode=True)
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)

    first = publish()
    assert len(adapter.calls) == 1
    assert first["reason"] == "outcome_ambiguous"
    _assert_rotation_handoff(first, repo)

    retry = publish()
    assert len(adapter.calls) == 1
    _assert_rotation_handoff(retry, repo)


def test_a_non_ambiguous_blocked_result_keeps_the_generic_handoff(tmp_path, monkeypatch):
    """A provider rejection proves no effect; the partition is not blocked, no rotation applies."""
    adapter = _CountingAdapter(terminal_state="no_effect_terminal_proven")
    repo, publish = _human_route(tmp_path, monkeypatch, adapter)

    result = publish()
    assert len(adapter.calls) == 1
    assert result["status"] == "publication_blocked", result
    assert result["terminal_state"] == "no_effect_terminal_proven"
    handoff = result["handoff"]
    assert handoff["next_step"] == GENERIC_STEP
    assert "rotate_command" not in handoff
    assert "rotate_requires" not in handoff
