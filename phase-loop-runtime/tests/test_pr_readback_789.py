"""Bounded observation controls for agent-harness#789; no live provider calls."""
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from phase_loop_runtime.convergence.broker import credsep
from phase_loop_runtime.convergence.broker.verbs import read_adapter_start_owner
from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
from phase_loop_runtime.publishing import PublishCrashInjected
from test_convergence_broker_credsep import (
    _FakeRun, _base_responses, _existing_pr_diagnostic, _request, _same_repo_pr,
)
from test_convergence_live_enable import _activated_publish_fixture, _service


def _response(stdout, rc=0, stderr="CREATE_STDERR_MARKER"):
    return SimpleNamespace(stdout=stdout, returncode=rc, stderr=stderr)


class _SequenceRun(_FakeRun):
    def __init__(self, request, observations, *, remotes=None, diagnostic=None,
                 origin="https://github.com/owner/repo.git"):
        responses = [
            (("branch", "--show-current"), request.branch, 0),
            (("rev-parse",), request.head_sha, 0),
            (("get-url",), origin, 0),
            (("log",), "SUBJECT_MARKER", 0),
            (("create",), "", int(diagnostic is not None), diagnostic or "CREATE_STDERR_MARKER"),
        ]
        super().__init__(responses + _base_responses())
        self.request = request
        self.observations = list(observations)
        self.remotes = list(remotes) if remotes is not None else [
            _response(f"{request.head_sha}\trefs/heads/{request.branch}") for _ in observations
        ]
        self.events = []
        self.sleeps = []

    def __call__(self, args, **kwargs):
        if "ls-remote" in args:
            self.events.append("remote")
            self.calls.append(list(args))
            assert self.remotes, "unexpected additional remote read"
            return self.remotes.pop(0)
        if args[:3] == ["gh", "pr", "list"]:
            self.events.append("list")
            self.calls.append(list(args))
            assert self.observations, "unexpected additional PR read"
            return self.observations.pop(0)
        if "push" in args:
            self.events.append("push")
        if args[:3] == ["gh", "pr", "create"]:
            self.events.append("create")
        return super().__call__(args, **kwargs)

    def sleep(self, seconds):
        self.events.append("sleep")
        self.sleeps.append(seconds)


def _observation(kind, request):
    if kind == "empty":
        return _response("[]")
    head = request.head_sha if kind == "match" else "b" * len(request.head_sha)
    return _response(json.dumps([_same_repo_pr(head=head, base=request.base)]))


def _diagnostics(caplog):
    return [record for record in caplog.records if record.name == credsep.__name__]


def _assert_trace(run, rounds, sleeps, *, final_list=True):
    expected = ["push", "create"]
    for index in range(rounds):
        expected.append("remote")
        if index < rounds - 1 or final_list:
            expected.append("list")
        if index < len(sleeps):
            expected.append("sleep")
    assert run.events == expected
    assert run.sleeps == sleeps
    mutations = [c for c in run.calls if "push" in c or c[:3] == ["gh", "pr", "create"]]
    assert len(mutations) == 2
    assert mutations[0][-1] == f"{run.request.head_sha}:refs/heads/{run.request.branch}"
    for call in run.calls:
        if "ls-remote" in call:
            assert call[-1] == f"refs/heads/{run.request.branch}"
        if call[:3] == ["gh", "pr", "list"]:
            assert call[call.index("--head") + 1] == run.request.branch
            assert call[call.index("--state") + 1] == "open"
            assert call[call.index("--json") + 1] == "url,headRefOid,baseRefName,headRepositoryOwner,isCrossRepository"


_SEQUENCES = [
    ("first", ["match"]),
    ("second-empty", ["empty", "match"]),
    ("second-stale", ["stale", "match"]),
    ("third-empty", ["empty", "empty", "match"]),
    ("third-stale", ["stale", "stale", "match"]),
    ("third-mixed", ["empty", "stale", "match"]),
    ("empty-exhausted", ["empty"] * 3),
    ("stale-exhausted", ["stale"] * 3),
    ("mixed-empty", ["empty", "stale", "empty"]),
    ("mixed-stale", ["stale", "empty", "stale"]),
]


@pytest.mark.parametrize("width,sequence", [
    pytest.param(width, sequence, id=f"{width}-{name}")
    for width in (40, 64) for name, sequence in _SEQUENCES
])
def test_confirmation_sequence(tmp_path, monkeypatch, caplog, width, sequence):
    request = replace(_request(), head_sha="a" * width)
    run = _SequenceRun(request, [_observation(k, request) for k in sequence])
    monkeypatch.setattr(credsep, "sleep", run.sleep, raising=False)
    result, evidence = credsep.GitHubBrokerAdapter(tmp_path, run=run).execute(request)
    success = sequence[-1] == "match"
    assert evidence.terminal_state == ("effect_terminal_observed" if success else "outcome_ambiguous_blocked")
    if success:
        assert result is not None and result.head_sha == request.head_sha
        assert result.pr_url == "https://github.com/owner/repo/pull/9"
    else:
        assert result is None
        assert evidence.evidence_reference == ("pr-list-empty" if sequence[-1] == "empty" else "pr-head-unconfirmed")
    _assert_trace(run, len(sequence), list(range(1, len(sequence))))
    assert not run.observations and not run.remotes
    expected = [
        f"publication-confirmation round={i} classification={'pr-list-empty' if kind == 'empty' else 'pr-head-unconfirmed'} continue={'true' if i < 3 else 'false'}"
        for i, kind in enumerate(sequence, 1) if kind != "match"
    ]
    assert [r.getMessage() for r in _diagnostics(caplog)] == expected
    assert all(r.levelno == logging.WARNING for r in _diagnostics(caplog))


def _invalid_observations(head):
    pr = _same_repo_pr(head=head)
    malformed_heads = [None, 1, "", "short", "A" * 40, "g" * 40, "b" * 64,
                       "b" * 40 + "\n", "0x" + "ab" * 19]
    cases = [(f"head-{i}", json.dumps([dict(pr, headRefOid=value)]), "pr-read-unparsable")
             for i, value in enumerate(malformed_heads)]
    missing = dict(pr)
    del missing["headRefOid"]
    cases.extend([
        ("missing-head", json.dumps([missing]), "pr-read-unparsable"),
        ("blank", "", "pr-read-unparsable"),
        ("whitespace", " \n", "pr-read-unparsable"),
        ("none-stdout", None, "pr-read-unparsable"),
        ("bad-json", "[", "pr-read-unparsable"),
        ("non-list", "{}", "pr-read-unparsable"),
        ("non-object", "[null]", "pr-read-unparsable"),
        ("multiple", json.dumps([pr, pr]), "pr-list-ambiguous"),
    ])
    for name, changes, reason in [
        ("base", {"baseRefName": "other-base"}, "pr-base-unconfirmed"),
        ("owner", {"headRepositoryOwner": {"login": "other-owner"}}, "pr-head-repository-unconfirmed"),
        ("owner-case", {"headRepositoryOwner": {"login": "Owner"}}, "pr-head-repository-unconfirmed"),
        ("owner-shape", {"headRepositoryOwner": None}, "pr-head-repository-unconfirmed"),
        ("fork", {"isCrossRepository": True}, "pr-head-repository-unconfirmed"),
        ("numeric-fork", {"isCrossRepository": 0}, "pr-head-repository-unconfirmed"),
        ("url", {"url": "https://github.com/other/repo/pull/9"}, "pr-url-unconfirmed"),
        ("diagnostic-url", {"url": "https://github.com/owner/repo/pull/10"}, "pr-url-readback-mismatch"),
    ]:
        cases.append((name, json.dumps([dict(pr, **changes)]), reason))
    return cases


@pytest.mark.parametrize("name,stdout,reason", [
    pytest.param(f"{kind}-{name}", stdout, reason, id=f"{kind}-{name}")
    for kind, head in (("stale", "b" * 40), ("exact", "a" * 40))
    for name, stdout, reason in _invalid_observations(head)
])
@pytest.mark.parametrize("after_wait", [False, True], ids=["first", "after-wait"])
def test_invalid_observation_stops_before_success_bait(tmp_path, monkeypatch, caplog, name, stdout, reason, after_wait):
    request = _request()
    prefix = [_observation("empty", request)] if after_wait else []
    bait = _observation("match", request)
    diagnostic = _existing_pr_diagnostic() if name.endswith("diagnostic-url") else None
    run = _SequenceRun(request, prefix + [_response(stdout), bait], diagnostic=diagnostic)
    monkeypatch.setattr(credsep, "sleep", run.sleep, raising=False)
    result, evidence = credsep.GitHubBrokerAdapter(tmp_path, run=run).execute(request)
    assert result is None and evidence.terminal_state == "outcome_ambiguous_blocked"
    assert evidence.evidence_reference == reason
    _assert_trace(run, 2 if after_wait else 1, [1] if after_wait else [])
    assert run.observations == [bait]
    assert [r.getMessage() for r in _diagnostics(caplog)] == (
        ["publication-confirmation round=1 classification=pr-list-empty continue=true"] if after_wait else []
    )


@pytest.mark.parametrize("kind,reason", [
    ("remote-error", "remote-read-failed"), ("remote-empty", "remote-branch-absent"),
    ("remote-mismatch", "remote-head-mismatch"), ("pr-error", "pr-read-failed"),
])
@pytest.mark.parametrize("after_wait", [False, True])
def test_read_error_stops_at_its_round(tmp_path, monkeypatch, caplog, kind, reason, after_wait):
    request = _request()
    remote = _response(f"{request.head_sha}\trefs/heads/{request.branch}")
    bad_remote = {"remote-error": _response("", 1), "remote-empty": _response(""),
                  "remote-mismatch": _response("b" * 40 + "\trefs/heads/feat/x")}.get(kind, remote)
    prefix = [_observation("empty", request)] if after_wait else []
    bait = _observation("match", request)
    observations = prefix + ([_response("READ_STDOUT_MARKER", 1)] if kind == "pr-error" else []) + [bait]
    run = _SequenceRun(request, observations, remotes=([remote] if after_wait else []) + [bad_remote, remote])
    monkeypatch.setattr(credsep, "sleep", run.sleep, raising=False)
    result, evidence = credsep.GitHubBrokerAdapter(tmp_path, run=run).execute(request)
    assert result is None and evidence.terminal_state == "outcome_ambiguous_blocked"
    assert evidence.evidence_reference == reason
    _assert_trace(run, 2 if after_wait else 1, [1] if after_wait else [], final_list=kind == "pr-error")
    assert run.observations == [bait]
    assert len(_diagnostics(caplog)) == int(after_wait)
    if after_wait:
        assert _diagnostics(caplog)[0].getMessage() == "publication-confirmation round=1 classification=pr-list-empty continue=true"


@pytest.mark.parametrize("kind", ["empty", "stale"])
def test_exhausted_terminal_replays_without_adapter_calls(tmp_path, monkeypatch, kind):
    repo, root, request = _activated_publish_fixture(tmp_path, label="exhaustion", branch="feat/exhaustion", owned_file="a.py")
    run = _SequenceRun(request, [_observation(kind, request)] * 3)
    monkeypatch.setattr(credsep, "sleep", run.sleep, raising=False)
    service = _service(root, repo, run)
    first = service.execute(request)
    assert not first.accepted and first.evidence.terminal_state == "outcome_ambiguous_blocked"
    _assert_trace(run, 3, [1, 2])
    assert first.evidence.evidence_reference == ("pr-list-empty" if kind == "empty" else "pr-head-unconfirmed")
    calls = list(run.calls)
    replay = _service(root, repo, run).execute(request)
    assert not replay.accepted and replay.evidence == first.evidence
    assert run.calls == calls and service.evidence_store.epoch_blocked


def test_wait_interruption_preserves_unsealed_owner_and_refuses_restart(tmp_path, monkeypatch):
    repo, root, request = _activated_publish_fixture(tmp_path, label="interrupted-wait", branch="feat/interrupted-wait", owned_file="a.py")
    run = _SequenceRun(request, [_observation("empty", request), _observation("match", request)])
    service = _service(root, repo, run)
    held = []

    def interrupt(seconds):
        run.sleep(seconds)
        lease = service.adapter.generation_lease
        owner = read_adapter_start_owner(root, repository_identity=request.repo)
        assert lease.path.exists()
        assert owner is not None and not owner.sealed
        assert service.evidence_store.replay()[owner.idempotency_key].state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT
        held.append((lease, owner))
        raise PublishCrashInjected("confirmation-wait")

    monkeypatch.setattr(credsep, "sleep", interrupt, raising=False)
    with pytest.raises(PublishCrashInjected, match="confirmation-wait"):
        service.execute(request)
    assert len(held) == 1
    lease, owner = held[0]
    assert not lease.path.exists()
    assert service.evidence_store.replay()[owner.idempotency_key].state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT
    assert not read_adapter_start_owner(root, repository_identity=request.repo).sealed
    _assert_trace(run, 1, [1])
    calls = list(run.calls)
    with pytest.raises(PermissionError, match="unsealed adapter-start owner blocks fresh provider effect"):
        _service(root, repo, run).execute(request)
    assert run.calls == calls
    terminal = service.evidence_store.replay()[owner.idempotency_key]
    assert terminal.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
    assert terminal.evidence_reference == "unsealed-adapter-start-owner"


@pytest.mark.parametrize("final", ["empty", "stale", "match"])
def test_diagnostics_reach_default_publisher_stderr_without_sensitive_fields(tmp_path, final):
    code = '''
from phase_loop_runtime import cli, train_runner, publishing
from test_pr_readback_789 import *
from test_pr_readback_789 import _SequenceRun, _response, _request, _same_repo_pr, _existing_pr_diagnostic
request = replace(_request(), branch="BRANCH_MARKER", base="BASE_MARKER", head_sha="c" * 40, repo="REPOSITORY_MARKER",
                  admission=replace(_request().admission, idempotency_key="KEY_MARKER", attempt_id="ATTEMPT_MARKER"))
url = "https://github.com/OWNER_MARKER/ORIGIN_MARKER/pull/947"
pr = _same_repo_pr(head="d" * 40, base=request.base, url=url)
pr["headRepositoryOwner"] = {"login": "OWNER_MARKER"}
pr["payload"] = "PAYLOAD_MARKER"
final = sys.argv[2]
last = [] if final == "empty" else [dict(pr, headRefOid=request.head_sha if final == "match" else "d" * 40)]
diagnostic = _existing_pr_diagnostic(head=request.branch, base=request.base, url=url)
run = _SequenceRun(request, [_response("[]"), _response(json.dumps([pr])), _response(json.dumps(last))],
                   diagnostic=diagnostic, origin="https://github.com/OWNER_MARKER/ORIGIN_MARKER.git")
credsep.sleep = run.sleep
result, evidence = credsep.GitHubBrokerAdapter(Path(sys.argv[1]), run=run).execute(request)
assert run.sleeps == [1, 2]
assert evidence.terminal_state == ("effect_terminal_observed" if final == "match" else "outcome_ambiguous_blocked")
'''
    root = Path(__file__).resolve().parents[1]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
           "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "tests"))),
           "PHASE_LOOP_FABPUB_AUTHORITY_ROOT": str(tmp_path / "authority")}
    process = subprocess.run([sys.executable, "-X", f"pycache_prefix={tmp_path / 'cold-cache'}",
                              "-c", code, str(tmp_path / "WORKDIR_MARKER"), final],
                             env=env, capture_output=True, text=True, check=True)
    expected = ["publication-confirmation round=1 classification=pr-list-empty continue=true",
                "publication-confirmation round=2 classification=pr-head-unconfirmed continue=true"]
    if final != "match":
        reason = "pr-list-empty" if final == "empty" else "pr-head-unconfirmed"
        expected.append(f"publication-confirmation round=3 classification={reason} continue=false")
    assert process.stdout == ""
    # Cold imports may emit these existing compile-time warnings outside this fix.
    warning_path = re.escape(str(root / "src/phase_loop_runtime/fab_delta.py"))
    diagnostics = re.sub(
        rf'^{warning_path}:\d+: SyntaxWarning: [^\n]*invalid escape sequence[^\n]*\n  [^\n]*\n',
        "", process.stderr, flags=re.MULTILINE,
    )
    assert diagnostics.splitlines() == expected
    for marker in ("BRANCH_MARKER", "BASE_MARKER", "c" * 40, "d" * 40, "KEY_MARKER", "ATTEMPT_MARKER",
                   "REPOSITORY_MARKER", "OWNER_MARKER", "ORIGIN_MARKER", "/pull/947", "PAYLOAD_MARKER",
                   "WORKDIR_MARKER", "CREATE_STDERR_MARKER", "SUBJECT_MARKER"):
        assert marker not in process.stderr


@pytest.mark.parametrize("kind", ["oversized-integer", "decoder-recursion"])
@pytest.mark.parametrize("after_wait", [False, True], ids=["first", "after-wait"])
def test_decoder_failure_stops_before_success_bait(tmp_path, monkeypatch, caplog, kind, after_wait):
    request = _request()
    if kind == "oversized-integer":
        limit = sys.get_int_max_str_digits()
        assert limit > 0
        payload = "[" + "9" * (limit + 1) + "]"
    else:
        payload = '["DECODER_RECURSION_MARKER"]'
        original_loads = json.loads

        def loads(value, *args, **kwargs):
            # Synthetic decoder exception control, not a platform depth claim.
            if value == payload:
                raise RecursionError("decoder recursion control")
            return original_loads(value, *args, **kwargs)

        monkeypatch.setattr(credsep.json, "loads", loads)
    prefix = [_observation("empty", request)] if after_wait else []
    bait = _observation("match", request)
    run = _SequenceRun(request, prefix + [_response(payload), bait])
    monkeypatch.setattr(credsep, "sleep", run.sleep)
    result, evidence = credsep.GitHubBrokerAdapter(tmp_path, run=run).execute(request)
    assert result is None and evidence.terminal_state == "outcome_ambiguous_blocked"
    assert evidence.evidence_reference == "pr-read-unparsable"
    _assert_trace(run, 2 if after_wait else 1, [1] if after_wait else [])
    assert run.observations == [bait] and len(run.remotes) == 1
    assert [r.getMessage() for r in _diagnostics(caplog)] == (
        ["publication-confirmation round=1 classification=pr-list-empty continue=true"] if after_wait else []
    )
