"""SL-3 falsifiers for the bounded provider adapters (EC-RUNTIME-3)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from phase_loop_runtime.convergence.adapters import (
    AdapterExecutionRequest, run_claude_adapter, run_codex_adapter, run_outside_agent_adapter,
)
from phase_loop_runtime.convergence.contracts import AdmissionRequest
from phase_loop_runtime.train_ledger import ConvergenceResultStatus

from _runtime_tdd_guard import RuntimeCapabilityMissing, require_source_capability
from runtime_content_tdd_adapter import RUNTIME_CASES, run_mapped_case

_SECRET = "ghp_1111111111111111111111111111111111"
_FROZEN_STATUSES = ("completed", "verified", "blocked", "needs_clarification", "degraded", "failed")


def _admission(**overrides) -> AdmissionRequest:
    value = dict(
        attempt_id="a", lease_epoch=1, fence_token="fence", approval_digest="approval",
        expected_version_predicate="head==abc", authority_domain_scope="repo",
        idempotency_key="key",
    )
    value.update(overrides)
    return AdmissionRequest(**value)


def _request(argv, cwd: Path, *, timeout: float = 10.0, **overrides) -> AdapterExecutionRequest:
    value = dict(
        attempt_id="a", admission=_admission(), argv=tuple(argv), cwd=cwd,
        timeout_seconds=timeout, allowed_action="execute",
    )
    value.update(overrides)
    return AdapterExecutionRequest(**value)


def _install(bin_dir: Path, name: str, body: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return script


def _emit(payload: dict) -> str:
    return f"printf '%s' '{json.dumps(payload)}'"


# ---------------------------------------------------------------------------
# Retained skeleton behaviour and the EC-RUNTIME-3 path-entered control


def test_adapter_rejects_out_of_bounds_command(tmp_path: Path):
    request = _request(("not-codex",), tmp_path)
    assert run_codex_adapter(request).status.value == "blocked"


def test_each_provider_executes_one_bounded_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """EC-RUNTIME-3 path-entered control: one valid bounded run per provider."""
    bin_dir = tmp_path / "bin"
    for name in ("codex", "claude", "outside-agent"):
        _install(bin_dir, name, _emit({"status": "completed"}), monkeypatch)
    for name, runner in (("codex", run_codex_adapter), ("claude", run_claude_adapter)):
        envelope = runner(_request((name,), tmp_path))
        assert envelope.status is ConvergenceResultStatus.COMPLETED
        assert envelope.attempt_id == "a"


def test_bounded_request_rejects_unbounded_or_unowned_shapes(tmp_path: Path):
    with pytest.raises(ValueError):
        _request((), tmp_path)
    with pytest.raises(ValueError):
        _request(("codex",), tmp_path, timeout=0)
    with pytest.raises(ValueError):
        _request(("codex",), tmp_path, allowed_action="publish")
    with pytest.raises(ValueError):
        _request(("codex",), tmp_path, attempt_id="other")


# ---------------------------------------------------------------------------
# SL-3 mapped falsifiers


def test_executable_identity_is_exact_not_a_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``codex-rogue`` shares codex's prefix but is a different executable."""
    _install(tmp_path / "bin", "codex-rogue", _emit({"status": "completed"}), monkeypatch)
    envelope = run_codex_adapter(_request(("codex-rogue",), tmp_path))

    def probe():
        if envelope.status is not ConvergenceResultStatus.BLOCKED:
            raise RuntimeCapabilityMissing("provider identity is matched by prefix, not exactly")

    def assertion():
        assert envelope.status is ConvergenceResultStatus.BLOCKED
        assert envelope.attempt_id == "a"

    run_mapped_case("adapters.exact-executable-identity", probe=probe, assertion=assertion)


def test_child_environment_is_credential_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mutation credentials and subscription escapes must never reach the child."""
    leaked = tmp_path / "env.txt"
    _install(tmp_path / "bin", "codex", f"env > {leaked}; {_emit({'status': 'completed'})}", monkeypatch)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(name, _SECRET)
    run_codex_adapter(_request(("codex",), tmp_path))
    observed = leaked.read_text(encoding="utf-8") if leaked.is_file() else ""

    def probe():
        if any(f"{name}=" in observed for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_BASE_URL")):
            raise RuntimeCapabilityMissing("the child environment still carries credential material")

    def assertion():
        assert observed, "the bounded child must actually run"
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
            assert f"{name}=" not in observed, f"{name} reached the adapter child"

    run_mapped_case("adapters.environment-is-credential-stripped", probe=probe, assertion=assertion)


def test_timeout_reclaims_the_child_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A timed-out adapter must reclaim its whole process group, not just the child."""
    case = RUNTIME_CASES["adapters.timeout-reclaims-process-group"]
    _install(tmp_path / "bin", "codex", "sleep 30", monkeypatch)
    killed: list[int] = []

    def probe():
        require_source_capability(case.production_path, case.symbol, "killpg")

    def assertion():
        real_killpg = os.killpg

        def recording_killpg(pgid, signal_number):
            killed.append(pgid)
            return real_killpg(pgid, signal_number)

        monkeypatch.setattr(os, "killpg", recording_killpg)
        started = time.monotonic()
        envelope = run_codex_adapter(_request(("codex",), tmp_path, timeout=0.5))
        monkeypatch.undo()
        assert envelope.status is ConvergenceResultStatus.DEGRADED
        assert envelope.attempt_id == "a"
        assert time.monotonic() - started < 20
        assert killed, "the timed-out child's process group must be reclaimed"

    run_mapped_case("adapters.timeout-reclaims-process-group", probe=probe, assertion=assertion)


def test_blank_expected_version_predicate_is_rejected(tmp_path: Path):
    """A whitespace predicate is truthy but is not a nonempty exact-version binding."""
    blank = AdmissionRequest("a", 1, "fence", "approval", "   ", "repo", "key")
    raised = False
    try:
        _request(("codex",), tmp_path, admission=blank)
    except ValueError:
        raised = True

    def probe():
        if not raised:
            raise RuntimeCapabilityMissing("a blank expected-version predicate is accepted")

    def assertion():
        assert raised
        assert _request(("codex",), tmp_path).admission.expected_version_predicate.strip()

    run_mapped_case("adapters.expected-version-predicate-is-bound", probe=probe, assertion=assertion)


def test_malformed_adapter_output_is_not_reported_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unparseable provider output must never be laundered into ``completed``."""
    _install(tmp_path / "bin", "codex", "printf '%s' 'not json at all'", monkeypatch)
    envelope = run_codex_adapter(_request(("codex",), tmp_path))

    def probe():
        if envelope.status in (ConvergenceResultStatus.COMPLETED, ConvergenceResultStatus.VERIFIED):
            raise RuntimeCapabilityMissing("malformed output is reported as success")

    def assertion():
        assert envelope.status in (
            ConvergenceResultStatus.BLOCKED,
            ConvergenceResultStatus.DEGRADED,
            ConvergenceResultStatus.FAILED,
        )
        assert envelope.attempt_id == "a"

    run_mapped_case("adapters.malformed-output-is-not-success", probe=probe, assertion=assertion)


def test_unvalidated_third_party_submission_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``run_outside_agent_adapter`` with no validated submission must block, not execute.

    The name deliberately avoids the ``outside_agent`` substring: the frozen
    corpus in ``test_outside_agent_canonical_corpus.py`` is owned by another
    phase and closes over every collected node id matching it.
    """
    _install(tmp_path / "bin", "outside-agent", _emit({"status": "completed"}), monkeypatch)
    envelope = run_outside_agent_adapter(_request(("outside-agent",), tmp_path))

    def probe():
        if envelope.status is not ConvergenceResultStatus.BLOCKED:
            raise RuntimeCapabilityMissing("a missing submission bypasses the conformance validator")

    def assertion():
        assert envelope.status is ConvergenceResultStatus.BLOCKED
        assert envelope.attempt_id == "a"
        assert run_outside_agent_adapter(
            _request(("outside-agent",), tmp_path), {"not": "conformant"}
        ).status is ConvergenceResultStatus.BLOCKED

    run_mapped_case("adapters.outside-agent-requires-conformance", probe=probe, assertion=assertion)


def _status_matrix(runner, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple]:
    observed: dict[str, tuple] = {}
    for status in _FROZEN_STATUSES:
        bin_dir = tmp_path / f"bin-{status}"
        _install(bin_dir, name, _emit({"status": status, "note": _SECRET}), monkeypatch)
        envelope = runner(_request((name,), tmp_path))
        observed[status] = (
            envelope.status.value,
            envelope.attempt_id,
            _SECRET in (envelope.detail or ""),
        )
    return observed


def test_codex_envelope_is_frozen_and_metadata_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    observed = _status_matrix(run_codex_adapter, "codex", tmp_path, monkeypatch)

    def probe():
        if any(leaked for _status, _attempt, leaked in observed.values()):
            raise RuntimeCapabilityMissing("adapter diagnostics are not kept metadata-only")

    def assertion():
        for status in _FROZEN_STATUSES:
            value, attempt, leaked = observed[status]
            assert value == status, f"codex did not preserve the frozen {status} status"
            assert attempt == "a"
            assert not leaked

    run_mapped_case("adapters.codex-binds-provider-identity", probe=probe, assertion=assertion)


def test_claude_envelope_matches_codex_for_every_frozen_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    codex = _status_matrix(run_codex_adapter, "codex", tmp_path / "codex", monkeypatch)
    claude = _status_matrix(run_claude_adapter, "claude", tmp_path / "claude", monkeypatch)

    def probe():
        if any(leaked for _status, _attempt, leaked in claude.values()):
            raise RuntimeCapabilityMissing("adapter diagnostics are not kept metadata-only")

    def assertion():
        assert claude == codex, "all adapters must return the same frozen envelope"
        for status in _FROZEN_STATUSES:
            assert claude[status] == (status, "a", False)

    run_mapped_case("adapters.claude-binds-provider-identity", probe=probe, assertion=assertion)
