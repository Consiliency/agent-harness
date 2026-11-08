"""Synthetic-login Codex CLI cases. The live cases require an explicit jail gate."""
import json
import os
from pathlib import Path
import secrets
import shutil
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi, seat_codex_credential as cred
from phase_loop_runtime import seat_jail, seat_uid, sandbox_egress, seat_egress_proxy
from phase_loop_runtime import seat_profile_codex as codex, seat_subject
from test_seat_profile_codex import codex_profile as _codex_profile
from test_seat_egress_allowlist_codex import (
    codex_front as _codex_front,  # noqa: F401 - pytest fixture requested dynamically after the gate
    _live_jail_or_fail, _synthetic_login,
)
from fixtures.codex_fixture_provider import CodexFixtureProvider, FIXTURE_CONFIG, scripted_call, response_events

codex_profile = _codex_profile


@pytest.fixture
def codex_front(request):
    # Fixture setup precedes the test body. Opt out before even probing Node/srt
    # or generating a CA (their own readiness deadlines can be much longer).
    _live_jail_or_fail()
    return request.getfixturevalue("_codex_front")


@pytest.mark.parametrize("opt_in", [None, "0"])
def test_live_opt_out_precedes_all_proxy_and_host_probes(monkeypatch, opt_in):
    if opt_in is None:
        monkeypatch.delenv("PHASE_LOOP_REQUIRE_LIVE_JAIL", raising=False)
    else:
        monkeypatch.setenv("PHASE_LOOP_REQUIRE_LIVE_JAIL", opt_in)
    def unexpected(*args, **kwargs):
        pytest.fail("an opted-out live test reached host or proxy setup")
    monkeypatch.setattr(seat_uid, "seat_uid_available", unexpected)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", unexpected)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_reason", unexpected)
    with pytest.raises(pytest.skip.Exception, match="PHASE_LOOP_REQUIRE_LIVE_JAIL"):
        codex_front.__wrapped__(SimpleNamespace(getfixturevalue=unexpected))


def test_required_live_run_fails_missing_prerequisites_before_proxy_setup(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_REQUIRE_LIVE_JAIL", "1")
    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda: False)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_reason", lambda: "fixture missing srt")
    def unexpected(*args, **kwargs):
        pytest.fail("missing prerequisites reached proxy setup")
    with pytest.raises(pytest.fail.Exception, match="live jail unavailable"):
        codex_front.__wrapped__(SimpleNamespace(getfixturevalue=unexpected))


@pytest.mark.parametrize("name,key", [("shell_command", "command"), ("exec_command", "cmd"), ("shell", "command")])
def test_fixture_scripts_a_tool_then_a_completed_response(name, key):
    call = scripted_call({"tools": [{"name": name}]}, "cat /seat/tree/SENTINEL")
    assert call["name"] == name and key in json.loads(call["arguments"])
    events = response_events(call)
    assert b"response.output_item.done" in events and b"response.completed" in events


def test_fixture_rejects_a_cli_without_the_scripted_tool():
    with pytest.raises(ValueError, match="fixture shell tool unavailable"):
        scripted_call({"tools": []}, "cat /seat/tree/SENTINEL")


@pytest.mark.parametrize("case", ["sentinel", "planted_markers", "rewritten_auth", "nested_namespace", "workspace_write"])
@pytest.mark.host_seat_credentials  # Existing installed-CLI opt-in; this test supplies only synthetic auth.
def test_live_jail_codex_fixture_provider(tmp_path, monkeypatch, codex_profile, codex_front, case, live_seat_attempt):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(seat_jail, "state_home", lambda: tmp_path / "state")
    cli = shutil.which("codex")
    assert cli is not None, "Codex CLI is required"
    native = os.environ.get("PHASE_LOOP_CODEX_FIXTURE_NATIVE")
    subject = (seat_subject.SeatSubject("codex", "standalone", Path(native).resolve(), None, None)
               if native else seat_subject.resolve_seat_subject("codex", {"PATH": os.environ.get("PATH", "")}))
    assert subject.source == "standalone", "provider-free run requires the developer CLI"
    assert subject.subject_path is not None
    # A real native runtime and production profile; only provider replies and login are synthetic.
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (subject, None))
    operator = tmp_path / "operator"
    (operator / ".codex").mkdir(parents=True)
    login = _synthetic_login()
    # The fixture access token also states the scope baseline the host checks.
    import base64
    parts = login["tokens"]["access_token"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    claims["scp"] = sorted(cred.CODEX_SCOPE_CEILING)
    parts[1] = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    login["tokens"]["access_token"] = ".".join(parts)
    auth = operator / ".codex/auth.json"
    auth.write_text(json.dumps(login))
    auth.chmod(0o600)
    review = tmp_path / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    sentinel = secrets.token_hex(16)
    (tree / "SENTINEL").write_text(sentinel)
    markers = []
    for path in codex.CODEX_PLANTED_PATHS:
        marker = "PLANTED_" + secrets.token_hex(16)
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(marker)
        markers.append(marker)
    fd = seat_jail.open_dir_nofollow(tree)
    try:
        digest = seat_jail.tree_manifest_sha256_at(fd)
    finally:
        os.close(fd)
    command = "cat /seat/tree/SENTINEL"
    if case == "rewritten_auth":
        command = """/usr/bin/python3 -I -c 'import json; p="/seat/home/.codex/auth.json"; d=json.load(open(p)); d["tokens"]["refresh_token"]="fixture-changed"; json.dump(d,open(p,"w"))'; cat /seat/tree/SENTINEL"""
    if case == "nested_namespace":
        command = "if /usr/bin/unshare -U /bin/sh -c 'echo NESTED_CREATED'; then echo NESTED_ALLOWED; else echo NESTED_REFUSED; fi"
    upstream = codex_front(hosts=["chatgpt.com"], upstream_class=lambda *a, **k: CodexFixtureProvider(*a, command=command, **k))
    original_command = codex.jailed_codex_command
    def configured(inputs):
        argv = list(original_command(inputs))
        argv[-1:-1] = FIXTURE_CONFIG
        if case == "workspace_write":
            argv[argv.index("--sandbox") + 1] = "workspace-write"
        return tuple(argv)
    monkeypatch.setattr(codex, "jailed_codex_command", configured)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, sandbox_egress.isolated_network(
                timeout_s=120, required=True, seat_uid_map=True, proxy_socket=proxy.socket,
                proxy_port=seat_egress_proxy.SEAT_PROXY_PORT) as prefix:
            token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
            try:
                seat = pi._prepare_jailed_codex(review, tmp_path / "seat",
                    type("Authorization", (), {"staged_tree_sha256": digest})(), n,
                    seat_uid.holder_pid_from_prefix(prefix), ("fixture", "fixture"), proxy,
                    env={"HOME": str(operator), "PATH": os.environ.get("PATH", "")})
                # The provider-free receipt does not create an EC-EXECFIND-2 host pass.
                monkeypatch.setattr(seat_jail, "pass_record_verdict", lambda _: (True, "pass"))
                # Check the jailed connect in a jail pair of its own: a launch spends the
                # descriptors of the jail it runs in.
                def connect_jail(name):
                    directory = seat.seat_dir / name
                    (directory / seat_jail.HOST_TREE_DIRNAME).mkdir(mode=0o700, parents=True)
                    return pi._build_jail_with_owned_inputs(
                        "codex", directory, Path(seat.jail.provider_path), artifact=b"",
                        instructions=b"", seat_ids=seat.jail.seat_ids,
                        egress_ca=pi._write_egress_ca(directory, proxy.ca_cert),
                        egress_proxy=proxy.proxy_url, dependency=None)
                check, check_probe = connect_jail("seat-connect"), connect_jail("seat-connect-probe")
                try:
                    probe = pi._run_leg_with_liveness(
                        ["/usr/bin/python3", "-I", "-c",
                         "import socket\ntry:\n s=socket.create_connection(('127.0.0.1',3128),timeout=3); s.close(); print('connected')\nexcept OSError as e:\n print('connect_errno='+str(e.errno)); raise SystemExit(1)"],
                        cwd="/seat/home/workspace", env=dict(check.env), deadline_s=10,
                        seat_jail=check, probe_jail=check_probe)
                finally:
                    for built in (check, check_probe):
                        seat_jail.close_jail_fds(built)
                    for name in ("seat-connect", "seat-connect-probe"):
                        seat_uid.teardown_in_h(seat.holder_pid, str(seat.seat_dir / name))
                if probe.returncode != 0:
                    pi._cleanup_jailed_seat(seat)
                    pytest.fail("jailed connect unavailable: " + probe.stdout.strip())
                sink = []
                result = pi._exec_jailed_codex_leg(seat, deadline_s=90, model="fixture", effort="max",
                    prompt="Follow the fixture command, then give your review.", broker_evidence={}, failure_detail_sink=sink)
            finally:
                pi._EGRESS_LAUNCH_PREFIX.reset(token)
    assert not upstream.problems
    assert upstream.bodies, "fixture received no CLI request"
    assert not any(marker.encode() in body for marker in markers for body in upstream.bodies)
    if case in {"rewritten_auth", "workspace_write"}:
        expected = "codex_seat_token_refreshed_in_jail" if case == "rewritten_auth" else "codex_seat_tools_unavailable"
        assert result == ("DEGRADED", "") and sink[-1].template == expected
    else:
        assert result[0] == "OK"
        outputs = json.dumps(upstream.tool_outputs)
        if case == "nested_namespace":
            assert "NESTED_REFUSED" in outputs and "NESTED_CREATED" not in outputs
            assert "Operation not permitted" in outputs
        else:
            assert sentinel in outputs
