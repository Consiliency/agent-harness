"""agent-harness#1282 board round 1: the narrowest credential for every harness, redaction of
every copied bearer, and a typed owner refusal on hosts that cannot own a seat."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, seat_jail


def _copied(profile, suffix):
    args = profile.mount_args
    return next(os.pread(int(args[i + 1]), 1_000_000, 0) for i, arg in enumerate(args)
                if arg == "--file" and args[i + 2].endswith(suffix))


# -- codex F002 / claude BLOCKING-1: opencode ------------------------------------------------

@pytest.mark.parametrize("role", [pi.SeatLaunchRole.PROVIDER_REVIEW, pi.SeatLaunchRole.PROVIDER_ADMIN])
def test_opencode_profile_does_not_copy_refresh_credentials(tmp_path, role):
    home = tmp_path / "operator"
    auth = home / ".local/share/opencode/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({"openai": {
        "type": "oauth", "access": "synthetic-access-token",
        "refresh": "synthetic-refresh-token", "expires": 9999999999999,
    }, "anthropic": {"type": "api", "key": "synthetic-api-key-value"}}))
    with pi.seat_profile(harness="opencode", executable="/usr/bin/true",
                         env={"HOME": str(home)}, cwd=tmp_path, role=role) as (_, profile):
        copied = _copied(profile, "/opencode/auth.json")
        assert b"synthetic-refresh-token" not in copied
        assert b"synthetic-access-token" in copied
        text = pi._redact_seat_credentials(
            "synthetic-access-token synthetic-api-key-value REVIEW END")
    assert "synthetic-access-token" not in text and "synthetic-api-key-value" not in text


# -- codex F004: grok's copied bearer ----------------------------------------------------------

def test_grok_copied_bearer_is_redacted_from_review_text(tmp_path):
    home = tmp_path / "operator"
    auth = home / ".grok/auth.json"
    auth.parent.mkdir(parents=True)
    token = "synthetic-grok-bearer-token"
    auth.write_text(json.dumps({"https://auth.example::id": {"key": token}}))
    (auth.parent / "agent_id").write_text("synthetic-agent")
    with pi.seat_profile(harness="grok", executable="/usr/bin/true",
                         env={"HOME": str(home)}, cwd=tmp_path) as (_, profile):
        assert token.encode() in _copied(profile, "/.grok/auth.json")
        assert token not in pi._redact_seat_credentials("REVIEW END\nAGREE\n" + token)


# -- codex F005 / grok O-1: typed owner refusals -------------------------------------------------

def test_an_identity_probe_that_saw_nothing_is_seat_owner_unavailable(monkeypatch):
    monkeypatch.setattr(pi.subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 1, "", ""))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified) as caught:
        pi._require_seat_identity(["/usr/bin/bwrap"])
    assert pi._exception_failure(caught.value) == "seat_owner_unavailable"
    assert seat_jail.render_notice("seat_owner_unavailable", "codex:a").fix


def test_a_wrong_identity_is_typed_seat_identity_unverified(monkeypatch):
    monkeypatch.setattr(pi.subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 0, "65534\n65534\n", ""))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified) as caught:
        pi._require_seat_identity(["/usr/bin/bwrap"])
    assert pi._exception_failure(caught.value) == "seat_identity_unverified"


def test_a_host_without_memfd_refuses_the_owner_typed(tmp_path, monkeypatch):
    monkeypatch.delattr(pi.os, "memfd_create", raising=False)
    home = tmp_path / "operator"
    (home / ".grok").mkdir(parents=True)
    (home / ".grok/auth.json").write_text('{"x": {"key": "synthetic"}}')
    (home / ".grok/agent_id").write_text("synthetic-agent")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified) as caught:
        with pi.seat_profile(harness="grok", executable="/usr/bin/true",
                             env={"HOME": str(home)}, cwd=tmp_path):
            pass
    assert pi._exception_failure(caught.value) == "seat_owner_unavailable"


def test_the_owned_auth_preflight_does_not_pre_empt_the_typed_refusal(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise sandbox_egress.SeatIdentityUnverified("seat_owner_unavailable")

    monkeypatch.setattr(pi, "run_provider", refuse)
    # Inconclusive: the leg's own launch then refuses with its typed code.
    assert pi._leg_auth_ok("codex", {"PATH": "/usr/bin:/bin"}) == (True, "")


# -- end to end: a host that cannot own a seat (president M3) ----------------------------------

def _fake_clis(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "grok"):
        cli = bin_dir / name
        cli.write_text("#!/bin/sh\necho should-not-run\n")
        cli.chmod(0o755)
    home = tmp_path / "operator"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/auth.json").write_text('{"tokens": {"access_token": "synthetic-access"}}')
    (home / ".grok").mkdir(parents=True)
    (home / ".grok/auth.json").write_text('{"x": {"key": "synthetic-grok-key"}}')
    (home / ".grok/agent_id").write_text("synthetic-agent")
    path = f"{bin_dir}{os.pathsep}/usr/bin:/bin"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", path)
    pi._recorded_provider_hashes.cache_clear()


def _assert_typed_owner_refusal(result):
    assert [leg.leg for leg in result.legs] == ["codex", "grok"]
    for leg in result.legs:
        assert (leg.status, leg.detail) == ("DEGRADED", "seat_owner_unavailable"), (leg.leg, leg.detail)
        notice = next(n for n in leg.seat_notices if n.code == "seat_owner_unavailable")
        assert "a Linux host" in notice.fix and "/usr/bin/bwrap" in notice.fix


@pytest.mark.skipif(not os.path.exists("/usr/bin/bwrap") or os.getuid() == 0,
                    reason="needs an unprivileged /usr/bin/bwrap")
def test_bwrap_that_exits_before_the_seat_starts_degrades_typed_end_to_end(tmp_path, monkeypatch):
    _fake_clis(tmp_path, monkeypatch)
    real_owner = pi._seat_owner

    def broken_owner(view, *, filtered_network=False):
        real_owner(view, filtered_network=filtered_network)  # the real checks still run
        # bwrap starts, then exits 1 before any seat runs (a host that denies it userns).
        return ["/usr/bin/bwrap", "--option-this-bwrap-refuses", "--"]

    monkeypatch.setattr(pi, "_seat_owner", broken_owner)
    _assert_typed_owner_refusal(pi.invoke_panel(
        "Synthetic advisory question.", ["codex", "grok"], mode="advisory", repo_dir=tmp_path))


def test_a_host_without_memfd_degrades_typed_end_to_end(tmp_path, monkeypatch):
    _fake_clis(tmp_path, monkeypatch)
    monkeypatch.delattr(pi.os, "memfd_create", raising=False)
    _assert_typed_owner_refusal(pi.invoke_panel(
        "Synthetic advisory question.", ["codex", "grok"], mode="advisory", repo_dir=tmp_path))
