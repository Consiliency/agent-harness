"""Regression tests for Consiliency/agent-harness#1951:
1. Codex route credential checks (L5 ``credential_present`` and L6 preconditions) read
   from the caller's environment (``RouteRequest.env``) so route pre-check, admission
   gate, and seat setup always resolve the same credential file.
2. Codex access-token margin scales with the leg's actual bounded deadline
   (``deadline_s + CODEX_LOGIN_SLACK_S``) across route selection, admission gate, and
   ``_prepare_jailed_codex``, while heartbeat-only legs enforce the 2100 s launch floor
   (``CODEX_LOGIN_MIN_S``).
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import (
    panel_invoker as pi,
    sandbox_egress,
    seat_codex_credential as cred,
    seat_codex_runtime,
    seat_jail,
    seat_profile_codex as codex_profile_mod,
    seat_profiles,
    seat_route,
    seat_route_contract as contract,
)
from phase_loop_runtime.seat_subject import SeatSubject
from test_seat_codex_cli_shape import EXEC_HELP_0_167_0, FEATURES_0_167_0
from test_seat_codex_credential import NOW, _claims, _login
from test_seat_profile_codex import codex_profile as _codex_profile

codex_profile = _codex_profile


def _write_auth(directory: Path, payload: bytes, *, mode: int = 0o600) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "auth.json"
    path.write_bytes(payload)
    path.chmod(mode)
    return path


def _valid_login_bytes(*, exp: int, scopes: str = "openid profile email") -> bytes:
    return json.dumps(_login(claims=_claims(exp=exp, scope=scopes))).encode("utf-8")


def _route_request(env: dict[str, str], *, deadline_s: float | None = None) -> contract.RouteRequest:
    return contract.RouteRequest(
        leg="codex",
        seat_key="codex",
        host_class="standard",
        run_kind="review",
        staged_tree_approved=True,
        env=env,
        deadline_s=deadline_s,
    )


def _resolve(request: contract.RouteRequest, policy: contract.RoutePolicy) -> contract.RouteDecision:
    return seat_route.resolve(
        request,
        policy=policy,
        remote=seat_route.INACTIVE_REMOTE_RUNG,
        native=seat_route.NO_NATIVE_FILL,
        capacity=SimpleNamespace(try_lease=lambda: None),
    )


def _stub_route_after_l6(monkeypatch) -> None:
    """Stop the resolver cleanly at L7 once L5 and L6 pass so tests isolate L5/L6."""
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: False)


def _prepare_codex_with_deadline(tmp_path: Path, monkeypatch, *, expiry: int, deadline_s: float | None):
    root = tmp_path / "vendor/x86_64-unknown-linux-musl"
    for relative in seat_codex_runtime.CODEX_RUNTIME_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    review = tmp_path / "review"
    tree = review / "reviewed-tree"
    tree.mkdir(parents=True)
    tree_fd = seat_jail.open_dir_nofollow(tree)
    try:
        digest = seat_jail.tree_manifest_sha256_at(tree_fd)
    finally:
        os.close(tree_fd)
    auth = _write_auth(tmp_path / "operator/.codex", _valid_login_bytes(exp=expiry))
    monkeypatch.setattr(
        pi,
        "_resolved_jail_subject",
        lambda *args: (SeatSubject("codex", "standalone", root / "bin/codex", None, None), None),
    )
    monkeypatch.setattr(
        pi,
        "run_provider",
        lambda cmd, **k: SimpleNamespace(
            returncode=0,
            stdout=EXEC_HELP_0_167_0 if "--help" in cmd else FEATURES_0_167_0,
        ),
    )
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"certificate")
    proxy = SimpleNamespace(ca_cert=ca, proxy_url="http://srt:synthetic-proxy-password@127.0.0.1:3128")
    authorization = SimpleNamespace(staged_tree_sha256=digest)
    return pi._prepare_jailed_codex(
        review,
        tmp_path / "seat",
        authorization,
        1,
        1,
        ("bundle", "instructions"),
        proxy,
        env={"HOME": str(auth.parents[1])},
        deadline_s=deadline_s,
    )


def test_present_uses_caller_env_over_process_env(tmp_path, monkeypatch):
    proc_home = tmp_path / "proc-home"
    caller_home = tmp_path / "caller-home"
    caller_codex = tmp_path / "caller-codex-home"

    _write_auth(proc_home / ".codex", b"{}")
    monkeypatch.setenv("HOME", str(proc_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    assert cred.present() is True
    assert cred.present({"HOME": str(caller_home)}) is False

    _write_auth(caller_codex, b"{}")
    assert cred.present({"HOME": str(caller_home), "CODEX_HOME": str(caller_codex)}) is True

    monkeypatch.setenv("HOME", str(caller_home))
    assert cred.present() is False
    assert cred.present({"HOME": str(proc_home)}) is True


def test_seat_route_uses_caller_env_for_codex_l5_and_l6(tmp_path, monkeypatch, codex_profile):
    _stub_route_after_l6(monkeypatch)
    proc_home = tmp_path / "proc-home"
    caller_home = tmp_path / "caller-home"
    empty_home = tmp_path / "empty-home"
    bad_home = tmp_path / "bad-home"
    policy = contract.RoutePolicy(schema="seat_route_policy.v1", routed_remote=frozenset(), exceptions={})

    valid = _valid_login_bytes(exp=int(time.time()) + 7200)
    _write_auth(proc_home / ".codex", valid)
    monkeypatch.setenv("HOME", str(proc_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    # 1. Process env has valid login, caller env has NO login -> L5 refusal.
    missing = _resolve(_route_request({"HOME": str(empty_home)}), policy)
    assert missing.code == "codex_seat_credential_missing"
    assert missing.steps[-1].step == "L5"

    # 2. Process env has NO login, caller env has valid login -> passes L5 & L6 (reaches L7).
    monkeypatch.setenv("HOME", str(empty_home))
    _write_auth(caller_home / ".codex", valid)
    reached_l7 = _resolve(_route_request({"HOME": str(caller_home)}), policy)
    assert reached_l7.code == "seat_sandbox_egress_opt_out"
    assert reached_l7.steps[-1].step == "L7"

    # 3. Process env has valid login, caller env has API-key / unsafe / over-scoped auth -> L6 refusal.
    monkeypatch.setenv("HOME", str(proc_home))
    _write_auth(bad_home / ".codex", json.dumps({"auth_mode": "api_key"}).encode())
    api_refused = _resolve(_route_request({"HOME": str(bad_home)}), policy)
    assert api_refused.code == "codex_seat_api_key_refused"
    assert api_refused.steps[-1].step == "L6"

    unsafe_home = tmp_path / "unsafe-home"
    _write_auth(unsafe_home / ".codex", valid, mode=0o644)
    unsafe = _resolve(_route_request({"HOME": str(unsafe_home)}), policy)
    assert unsafe.code == "seat_sandbox_refused:token_file_unsafe"
    assert unsafe.steps[-1].step == "L6"


def test_seat_route_for_spawn_preserves_explicit_empty_env_and_threads_deadline(monkeypatch):
    seen: list[contract.RouteRequest] = []

    def fake_resolve(request, **kwargs):
        seen.append(request)
        return contract.RouteDecision(
            leg=request.leg,
            vendor="codex",
            mode="degraded",
            code="codex_seat_credential_missing",
            steps=(),
            exception=None,
            variant=None,
            qualification_key=None,
            also=(),
            lease=None,
        )

    monkeypatch.setattr(seat_route, "resolve", fake_resolve)
    monkeypatch.setenv("CODEX_HOME", "/should-not-leak-into-empty-env")
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    pi._seat_route_for_spawn("codex", auth, eligible=True, env={}, deadline_s=3600.0)
    assert len(seen) == 1
    assert seen[0].env == {}
    assert seen[0].deadline_s == 3600.0


def test_required_margin_s_and_token_margin_problem():
    assert cred.CODEX_LOGIN_SLACK_S == 300
    assert cred.required_margin_s(None) == float(cred.CODEX_LOGIN_MIN_S) == 2100.0
    assert cred.required_margin_s(1800) == 2100.0
    assert cred.required_margin_s(3600) == 3900.0
    assert cred.required_margin_s(300) == 600.0
    assert cred.required_margin_s(0) == 300.0

    for bad in (-1, -0.1, math.nan, math.inf, -math.inf, True, False):
        with pytest.raises(ValueError):
            cred.required_margin_s(bad)
        with pytest.raises(ValueError):
            cred.token_margin_problem(_valid_login_bytes(exp=NOW + 5000), now=NOW, margin_s=bad)

    raw = _valid_login_bytes(exp=NOW + 1000)
    assert cred.token_margin_problem(raw, now=NOW) == "codex_seat_token_expiring"
    assert cred.token_margin_problem(raw, now=NOW, margin_s=1000) is None
    assert cred.token_margin_problem(raw, now=NOW, margin_s=1001) == "codex_seat_token_expiring"


def test_deadline_tied_margin_agrees_across_route_admission_and_prepare(
    tmp_path, monkeypatch, codex_profile
):
    _stub_route_after_l6(monkeypatch)
    now = int(time.time())
    policy = contract.RoutePolicy(schema="seat_route_policy.v1", routed_remote=frozenset(), exceptions={})

    # Token valid for 2500 s: passes default 2100 s, FAILS bounded deadline_s=3600 (needs 3900 s).
    long_home = tmp_path / "long-home"
    _write_auth(long_home / ".codex", _valid_login_bytes(exp=now + 2500))
    long_env = {"HOME": str(long_home)}

    default_route = _resolve(_route_request(long_env, deadline_s=None), policy)
    assert default_route.steps[-1].step == "L7"

    long_route = _resolve(_route_request(long_env, deadline_s=3600.0), policy)
    assert long_route.code == "codex_seat_token_expiring"
    assert long_route.steps[-1].step == "L6"

    long_verdict = codex_profile_mod.codex_admission_gate("codex", long_env, False, deadline_s=3600.0)
    assert long_verdict is not None and long_verdict.code == "codex_seat_token_expiring"

    with pytest.raises(seat_jail.SeatSandboxRefused) as long_refused:
        _prepare_codex_with_deadline(tmp_path / "prep-long", monkeypatch, expiry=now + 2500, deadline_s=3600.0)
    assert long_refused.value.code == "codex_seat_token_expiring"

    # Token valid for 900 s: FAILS default 2100 s, PASSES bounded deadline_s=300 (needs 600 s).
    short_home = tmp_path / "short-home"
    _write_auth(short_home / ".codex", _valid_login_bytes(exp=now + 900))
    short_env = {"HOME": str(short_home)}

    default_short = _resolve(_route_request(short_env, deadline_s=None), policy)
    assert default_short.code == "codex_seat_token_expiring"
    assert default_short.steps[-1].step == "L6"

    short_route = _resolve(_route_request(short_env, deadline_s=300.0), policy)
    assert short_route.steps[-1].step == "L7"

    short_verdict = codex_profile_mod.codex_admission_gate("codex", short_env, False, deadline_s=300.0)
    assert short_verdict is not None and short_verdict.reason == "launch_measurement"

    seat = _prepare_codex_with_deadline(tmp_path / "prep-short", monkeypatch, expiry=now + 900, deadline_s=300.0)
    try:
        assert seat.codex_copy is not None
    finally:
        seat_jail.close_jail_fds(seat.jail)
        seat_jail.close_jail_fds(seat.probe_jail)


def test_heartbeat_only_uses_default_floor_not_bounded_override():
    assert pi._codex_seat_deadline_s(None) is None
    assert pi._codex_seat_deadline_s(3600) == 3600.0
    assert pi._codex_seat_deadline_s(300) == 300.0
    assert pi._codex_seat_deadline_s(300, review_monitor=object()) is None
    assert pi._codex_seat_deadline_s(None, review_monitor=object()) is None


def test_zero_arg_profile_stubs_remain_compatible(monkeypatch, codex_profile):
    _stub_route_after_l6(monkeypatch)
    policy = contract.RoutePolicy(schema="seat_route_policy.v1", routed_remote=frozenset(), exceptions={})
    zero_arg = replace(
        seat_profiles.profile_for("codex"),
        credential_present=lambda: True,
        preconditions=(contract.Precondition("stub", lambda: None),),
    )
    monkeypatch.setattr(seat_profiles, "profile_for", lambda leg: zero_arg if leg == "codex" else None)
    decision = _resolve(_route_request({"HOME": "/nonexistent"}, deadline_s=300.0), policy)
    assert decision.steps[-1].step == "L7"
