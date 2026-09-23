"""agent-harness#1001: president rung launches run under the review seats' isolation.

Every non-native rung launch goes through egress isolation, a single-use broker
capability carrying the PRESIDENT operation, and the real ``ParentUnixBroker``; under
``heartbeat_only`` it runs with a ``_ReviewMonitor`` (no model-thinking deadline, no
silence kill). The provider transport is observed at ``PresidentInvoke._transport``,
which sits INSIDE the broker (not part of the injected-seam predicate), so the broker,
egress and lease below are all real.

Not part of the PRESROUTE SL-0 frozen corpus.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from phase_loop_runtime import panel_invoker, president_adapter, sandbox_egress
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

RULING = "FINDING F001: DEFERRED — ok\nFORCING DECISION: LAND"
PROVIDER_RUNGS = ("sol", "grok", "gemini")


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    return repo


needs_egress = pytest.mark.skipif(
    not sandbox_egress.egress_isolation_available(),
    reason="this host cannot enforce egress isolation (sandbox_egress.egress_isolation_available() is False)",
)


def _observe(seen: list[dict[str, object]]):
    def transport(self, harness, route_model, prompt, stage, out_dir, *, monitor=None, latch=None):
        seen.append({
            "harness": harness,
            "monitor": monitor,
            "latch": latch,
            "prefix": tuple(panel_invoker._EGRESS_LAUNCH_PREFIX.get()),
            "thread": threading.current_thread().name,
            "stage": sorted(p.name for p in stage.iterdir()),
        })
        return 0, RULING, ""
    return transport


@needs_egress
@pytest.mark.parametrize("rung", PROVIDER_RUNGS)
def test_a_heartbeat_rung_launches_under_monitor_broker_and_egress(tmp_path, rung):
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    brokers: list[backing.ParentUnixBroker] = []
    real_broker = backing.ParentUnixBroker

    def spy_broker(leg, **kwargs):
        broker = real_broker(leg, **kwargs)
        brokers.append(broker)
        return broker

    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)), patch.object(
        backing, "ParentUnixBroker", spy_broker
    ):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), stream_dir=tmp_path / "stream",
            base_env={}, monitoring_policy="heartbeat_only",
        )
        response = seam(rung, "F001: [x] the lock is never released")
    assert response["status"] == "ok" and response["text"] == RULING
    assert len(seen) == 1 and len(brokers) == 1
    observed = seen[0]
    monitor = observed["monitor"]
    # heartbeat: a monitor, no model deadline, no silence deadline
    assert isinstance(monitor, panel_invoker._ReviewMonitor)
    assert monitor.record["model_deadline_s"] is None and monitor.record["silence_deadline_s"] is None
    # isolation: a non-empty egress prefix reached the transport, inside the broker
    assert observed["prefix"], "the rung launched without an egress prefix"
    assert observed["latch"] is not None
    # the broker's capability carries the PRESIDENT operation, never the review one
    leg = brokers[0].authorization
    assert leg.operation == backing.PRESIDENT_OPERATION_V1
    assert leg.monitoring_policy == "heartbeat_only"
    assert brokers[0].evidence["child_quiescent"] is True
    # the monitor record is filed under the stream
    assert list((tmp_path / "stream" / "president-monitoring").rglob("rung-*.json"))


@needs_egress
def test_a_bounded_rung_is_brokered_and_isolated_too(tmp_path):
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="bounded",
        )
        response = seam("grok", "F001: [x] y")
    assert response["status"] == "ok"
    assert seen[0]["monitor"] is None and seen[0]["prefix"]


def test_no_canonical_repository_is_a_typed_refusal_before_any_launch(tmp_path):
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(tmp_path / "not-a-repo"), base_env={},
            monitoring_policy="heartbeat_only",
        )
        response = seam("sol", "F001: [x] y")
    assert seen == []
    assert response["status"] == "failed" and response["code"] == "president_invocation_failed"
    assert "canonical repository" in response["detail"]


def test_unavailable_egress_is_a_typed_refusal_before_any_launch(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="heartbeat_only",
        )
        response = seam("grok", "F001: [x] y")
    assert seen == []
    assert response["status"] == "failed"
    assert "egress" in response["detail"].lower()


@needs_egress
def test_a_cancelled_operation_never_launches(tmp_path):
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    cancel = threading.Event()
    cancel.set()
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="heartbeat_only",
        )
        seam.cancel_event = cancel
        response = seam("grok", "F001: [x] y")
    assert seen == []
    assert response["status"] == "failed"


def test_the_president_leg_capability_is_single_use_and_policy_bound(tmp_path):
    repo = _git_repo(tmp_path)
    brief = "F001: [x] y"
    auth = backing.prepare_president_isolation_authorization(
        DEFAULT_BOARD, brief, canonical_repo_authority=repo, monitoring_policy="heartbeat_only",
    )
    route = dict(auth.routes)["grok"]
    with pytest.raises(ValueError, match="not active"):
        backing.derive_president_leg_authorization(
            auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=None,
            instructions_sha256="0" * 64, canonical_repo_authority=repo,
        )
    backing.activate_president_isolation_authorization(
        auth, DEFAULT_BOARD, brief, canonical_repo_authority=repo
    )
    with pytest.raises(ValueError, match="invalid HARDEN president leg authority"):
        backing.derive_president_leg_authorization(  # a deadline under heartbeat_only
            auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=1800.0,
            instructions_sha256="0" * 64, canonical_repo_authority=repo,
        )
    leg = backing.derive_president_leg_authorization(
        auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=None,
        instructions_sha256="0" * 64, canonical_repo_authority=repo,
    )
    assert leg.operation == backing.PRESIDENT_OPERATION_V1
    with pytest.raises(ValueError, match="already consumed"):
        backing.derive_president_leg_authorization(
            auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=None,
            instructions_sha256="0" * 64, canonical_repo_authority=repo,
        )
    backing.close_president_isolation_authorization(auth)
    with pytest.raises(ValueError):
        backing.activate_president_isolation_authorization(
            auth, DEFAULT_BOARD, brief, canonical_repo_authority=repo
        )


def test_invoke_board_binds_its_operation_cancel_to_the_president_seam(tmp_path):
    # The board's cancellation reaches the president's heartbeat monitor.
    seen: dict[str, object] = {}
    real = president_adapter.build_president_invoke

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after wiring")

    cancel = threading.Event()
    with patch.object(president_adapter, "build_president_invoke", capture):
        with pytest.raises(RuntimeError, match="stop after wiring"):
            panel_invoker.invoke_board(
                DEFAULT_BOARD, "artifact", landing_tier="production_code",
                base_env={"CLAUDECODE": "1"}, repo_dir=str(tmp_path), cancel_event=cancel,
            )
    assert seen.get("cancel_event") is cancel
    assert real is president_adapter.build_president_invoke
