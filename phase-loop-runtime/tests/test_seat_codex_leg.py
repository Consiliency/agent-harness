"""Codex preparation and parent-held post-launch decisions, without a provider."""
import contextlib
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi, seat_codex_credential as cred, seat_jail
from phase_loop_runtime.seat_subject import SeatSubject
from test_seat_codex_credential import _login, _claims
from test_seat_codex_evidence import stream
from test_seat_profile_codex import codex_profile as _codex_profile

codex_profile = _codex_profile


@pytest.mark.parametrize("mask", [0o077, 0o027])
def test_egress_ca_copy_is_readable_by_the_seat_under_a_private_umask(tmp_path, mask):
    source = tmp_path / "source-ca.pem"
    source.write_bytes(b"public certificate bytes")
    seat = tmp_path / "seat"
    seat.mkdir(mode=0o700)
    previous = os.umask(mask)
    try:
        copied = pi._write_egress_ca(seat, source)
    finally:
        os.umask(previous)
    assert copied.read_bytes() == source.read_bytes()
    assert copied.stat().st_mode & 0o777 == 0o444
    assert seat.stat().st_mode & 0o777 == 0o700


def prepare(tmp_path, monkeypatch, *, expiry=None):
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_FILES
    root = tmp_path / "vendor/x86_64-unknown-linux-musl"
    for relative in CODEX_RUNTIME_FILES:
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
    auth = tmp_path / "operator/.codex/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps(_login(claims=_claims(exp=expiry or int(time.time()) + 7200))))
    auth.chmod(0o600)
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (
        SeatSubject("codex", "standalone", root / "bin/codex", None, None), None))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"certificate")
    proxy = SimpleNamespace(ca_cert=ca, proxy_url="http://srt:synthetic-proxy-password@127.0.0.1:3128")
    authorization = SimpleNamespace(staged_tree_sha256=digest)
    seat = pi._prepare_jailed_codex(review, tmp_path / "seat", authorization, 1, 1,
                                   ("bundle", "instructions"), proxy,
                                   env={"HOME": str(auth.parents[1])})
    return seat


def local_reads(monkeypatch):
    def read(holder, root, relative, cap):
        fd = seat_jail.open_dir_nofollow(root)
        try:
            return seat_jail.read_regular_file_at(fd, relative, cap)
        except FileNotFoundError as exc:
            raise pi._seat_uid.SeatObjectMissing(relative) from exc
        finally:
            os.close(fd)
    monkeypatch.setattr(pi._seat_uid, "read_in_h", read)
    def cleanup(seat, **kwargs):
        seat_jail.close_jail_fds(seat.jail)
        seat_jail.close_jail_fds(seat.probe_jail)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", cleanup)


def test_clock_margin_refuses_before_install(tmp_path, monkeypatch, codex_profile):
    installed = []
    monkeypatch.setattr(cred, "install_seat_copy", lambda *a: installed.append(True))
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        prepare(tmp_path, monkeypatch, expiry=int(time.time()) + 2099)
    assert refused.value.code == "codex_seat_token_expiring"
    assert installed == []


def test_production_and_probe_views_agree_without_a_probe_credential(tmp_path, monkeypatch, codex_profile):
    seat = prepare(tmp_path, monkeypatch)
    try:
        assert seat.jail.profile_digest == seat.probe_jail.profile_digest == seat_jail.jail_profile_digest("codex")
        assert seat.jail.env == seat.probe_jail.env
        copied = seat.seat_dir / "seat-home/.codex/auth.json"
        assert copied.read_bytes() == seat.codex_copy.data
        assert copied.stat().st_mode & 0o777 == 0o600
        assert not (Path(seat.probe_jail.review_dir) / "seat-home/.codex/auth.json").exists()
    finally:
        seat_jail.close_jail_fds(seat.jail)
        seat_jail.close_jail_fds(seat.probe_jail)


def test_clock_margin_is_rechecked_immediately_before_delivery(tmp_path, monkeypatch, codex_profile):
    installed = []
    calls = []
    def margin(raw, *, now):
        calls.append(now)
        return None if len(calls) == 1 else "codex_seat_token_expiring"
    monkeypatch.setattr(cred, "token_margin_problem", margin)
    monkeypatch.setattr(cred, "install_seat_copy", lambda *a: installed.append(True))
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        prepare(tmp_path, monkeypatch)
    assert refused.value.code == "codex_seat_token_expiring" and len(calls) == 2
    assert installed == []


@pytest.mark.parametrize("case,expected", [
    ("success", None), ("zero_commands", "codex_seat_tools_unavailable"),
    ("unknown", "codex_seat_unknown_event"), ("refresh", "codex_seat_token_refreshed_in_jail"),
    ("expired", "codex_seat_token_expiring"), ("secret", "codex_seat_token_in_output"),
    ("expired_no_command", "codex_seat_token_expiring"),
    ("failed_commands", "codex_seat_tools_unavailable"),
    ("stderr", "codex_seat_token_in_output"), ("output", "codex_seat_token_in_output"),
    ("proxy", "codex_seat_token_in_output"),
])
def test_real_liveness_output_and_post_launch_order(tmp_path, monkeypatch, codex_profile, case, expected):
    seat = prepare(tmp_path, monkeypatch)
    local_reads(monkeypatch)
    copy = seat.codex_copy
    if case in {"secret", "stderr", "output", "proxy", "refresh"}:
        path = seat.seat_dir / "seat-home/.codex/auth.json"
        path.write_text('{}')
    if case in {"expired", "refresh", "expired_no_command"}:
        seat.codex_copy = replace(copy, expires_at=0)
    data = stream(command=case not in {"zero_commands", "expired_no_command"},
                  exit_code=1 if case == "failed_commands" else 0,
                  extra=({"type": "new.event"},) if case == "unknown" else ())
    secret = copy.secrets[0] if case != "proxy" else b"synthetic-proxy-password"
    out = data + (secret if case in {"secret", "proxy"} else b"")
    err = secret if case == "stderr" else b""
    review = secret if case == "output" else b"The fixture was read.\n\nAGREE"
    (seat.seat_dir / "seat-out/panel-codex.txt").write_bytes(review)
    child = "import sys; sys.stdin.read(); sys.stdout.buffer.write(" + repr(out) + "); sys.stderr.buffer.write(" + repr(err) + "); sys.exit(" + str(1 if case in {"expired", "refresh", "expired_no_command"} else 0) + ")"
    def launch(argv, **kwargs):
        assert kwargs["process_owner"] is seat.jail and kwargs["probe_owner"] is seat.probe_jail
        return subprocess.Popen([sys.executable, "-c", child], stdin=kwargs["stdin"],
                                stdout=kwargs["stdout"], stderr=kwargs["stderr"], start_new_session=True)
    monkeypatch.setattr(pi, "launch_provider", launch)
    sink, evidence = [], {}
    result = pi._exec_jailed_codex_leg(seat, deadline_s=20, model="fixture", prompt="fixture",
                                      broker_evidence=evidence, failure_detail_sink=sink)
    if expected:
        assert result == ("DEGRADED", "") and sink[-1].template == expected
    else:
        assert result == ("OK", review.decode()) and not sink
        assert evidence["provider_stream_tool_steps"] == 1


@pytest.mark.parametrize("case,expected", [
    ("success", None), ("zero_commands", "codex_seat_tools_unavailable"),
    ("unknown", "codex_seat_unknown_event"), ("refresh", "codex_seat_token_refreshed_in_jail"),
    ("expired", "codex_seat_token_expiring"), ("secret", "codex_seat_token_in_output"),
    ("expired_no_command", "codex_seat_token_expiring"),
    ("failed_commands", "codex_seat_tools_unavailable"),
])
def test_default_spawn_holds_route_lease_through_codex_leg(tmp_path, monkeypatch, codex_profile, case, expected):
    from test_seat_notices import _brokered
    seat = prepare(tmp_path, monkeypatch)
    local_reads(monkeypatch)
    cleanup = pi._cleanup_jailed_seat
    def cleanup_with_notice(seat, **kwargs):
        cleanup(seat, **kwargs)
        seat.notices.append("seat_sandbox_retained_after_teardown")
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", cleanup_with_notice)
    if case in {"refresh", "secret"}:
        (seat.seat_dir / "seat-home/.codex/auth.json").write_text("{}")
    if case in {"expired", "refresh", "secret", "expired_no_command"}:
        seat.codex_copy = replace(seat.codex_copy, expires_at=0)
    (seat.seat_dir / "seat-out/panel-codex.txt").write_text("Fixture read.\n\nAGREE")
    data = stream(command=case not in {"zero_commands", "expired_no_command"},
                  exit_code=1 if case == "failed_commands" else 0,
                  extra=({"type": "new.event"},) if case == "unknown" else ())
    if case == "secret":
        data += seat.codex_copy.secrets[0]
    child = "import sys; sys.stdin.read(); sys.stdout.buffer.write(" + repr(data) + "); sys.exit(" + str(1 if case in {"expired", "refresh", "secret", "expired_no_command"} else 0) + ")"
    released = []
    lease = SimpleNamespace(seat_id=7, release=lambda: released.append(True))
    route = SimpleNamespace(jailed=True, lease=lease)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (route, [], None))
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda _: 42)
    monkeypatch.setattr(pi._seat_egress_proxy, "start_proxy", lambda **k: contextlib.nullcontext(
        SimpleNamespace(socket="fixture", proxy_url="fixture")))
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda _: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", lambda **k: contextlib.nullcontext(("fixture",)))
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda **k: {})
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    def staged(repo, review):
        tree = Path(review) / "pl-panel-stage-fixture"
        (tree / ".git").mkdir(parents=True)
        (tree / ".git/phase-loop-source-commit").write_text("c" * 40)
        return tree
    # The authorization/staging seams keep this dispatch test provider-free.
    monkeypatch.setattr(pi._review_stage, "stage_review_tree", staged)
    monkeypatch.setattr(pi._sandbox_policy, "select_sandbox_root",
                        lambda **k: pi._sandbox_policy.SandboxRootChoice(
                            host=None, path=tmp_path, fell_back=False, reason=""))
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_exception_failure", lambda exc: (_ for _ in ()).throw(exc))
    def prepared(*a, **k):
        assert not released
        return seat
    monkeypatch.setattr(pi, "_prepare_jailed_codex", prepared)
    monkeypatch.setattr(pi, "_bind_route_qualification", lambda seat, route: seat)
    def launch(argv, **kwargs):
        assert not released
        return subprocess.Popen([sys.executable, "-c", child], stdin=kwargs["stdin"],
                                stdout=kwargs["stdout"], stderr=kwargs["stderr"], start_new_session=True)
    monkeypatch.setattr(pi, "launch_provider", launch)
    spawned = _brokered(monkeypatch, tmp_path, "codex", "a" * 64)
    assert tuple(spawned)[0] == ("DEGRADED" if expected else "OK")
    if expected:
        assert expected in spawned.seat_notices
    assert "seat_sandbox_retained_after_teardown" in spawned.seat_notices
    assert released == [True]
