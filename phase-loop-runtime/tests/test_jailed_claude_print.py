"""Claude print transport compatibility on the existing pointer-seat launch chain.

Synthetic protocol cases complement live, credential-free executable tests. No model
request is made, and these tests do not qualify tooled seats as sealed HARDEN evidence.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import threading
import types

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, seat_jail, seat_uid

from ._seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready

TOKEN = b"SEAT-JAIL-SENTINEL-print-compatibility"
INIT = {"type": "system", "subtype": "init", "apiKeySource": "none"}
RESULT = {"type": "result", "subtype": "success", "result": "Reviewed.\nAGREE", "is_error": False}


def _login_store(token=TOKEN, subscription=True):
    return json.dumps({"claudeAiOauth": {
        "accessToken": token.decode(), "expiresAt": 4102444800000,
        "scopes": ["user:inference"], "subscriptionType": "synthetic" if subscription else None,
    }}).encode()


@pytest.mark.parametrize("events,code", [
    ([RESULT, INIT], "claude_print_subscription_unproven"),
    ([INIT, INIT, RESULT], "claude_print_subscription_unproven"),
    ([{**INIT, "apiKeySource": "key"}, RESULT], "claude_print_subscription_unproven"),
    ([INIT, {"type": "system", "subtype": "api_retry", "error": "billing_error"}, RESULT], "claude_print_auth_drift"),
    ([INIT, {**RESULT, "subtype": "error_during_execution"}], "claude_print_result_unproven"),
    ([INIT, {**RESULT, "is_error": True}], "claude_print_result_unproven"),
    ([INIT, RESULT, RESULT], "claude_print_result_unproven"),
])
def test_stream_admission_requires_one_success_after_subscription_init(events, code):
    stream = pi._ClaudePrintStream()
    data = b"".join(json.dumps(event).encode() + b"\n" for event in events)
    for byte in data:
        stream.feed(bytes([byte]))
    stream.finish()
    assert stream.violation == code


@pytest.fixture
def fake_seat(monkeypatch, tmp_path):
    jail = types.SimpleNamespace(
        leg="claude", provider_argv0="/seat/bin/claude", env={"HOME": "/seat/home"},
        profile_digest="d" * 64, profile_id="jail", filter_digest="f" * 64,
        redacted_owner=lambda: ["bwrap", "--"],
    )
    seat = pi._JailedSeat(jail, jail, 1, TOKEN, tmp_path / "review", tmp_path / "seat",
                          claude_subscription_proven=True)
    monkeypatch.delenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", raising=False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda **kw: (True, "supported"))
    monkeypatch.setattr(pi, "_jailed_claude_subscription_auth_ok",
                        lambda seat, **kw: seat.claude_subscription_proven)
    monkeypatch.setattr(seat_jail, "close_jail_fds", lambda jail: None)
    removed = []
    monkeypatch.setattr(seat_uid, "teardown_in_h", lambda holder, parent: removed.append(parent) or [])
    return seat, removed


def _exec(seat, evidence, **kwargs):
    return pi._exec_jailed_claude_leg(
        seat, timeout_s=5, backstop_s=5, model="claude-opus-5-5", effort="high",
        prompt="Review the staged pointer.", broker_evidence=evidence, env={}, **kwargs,
    )


def test_default_print_uses_jail_and_retains_only_observed_stream_evidence(fake_seat, monkeypatch):
    seat, removed = fake_seat
    seen = {}

    def run(command, **kw):
        seen.update(command=command, **kw)
        data = json.dumps(INIT).encode() + b"\n" + json.dumps(RESULT).encode() + b"\n"
        assert not kw["output_guard"]("stdout", data)
        assert not kw["stdout_guard"](data)
        return pi._LegRun(0, data.decode(), "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: pytest.fail("TUI launched"))
    evidence = {}
    assert _exec(seat, evidence) == ("OK", "Reviewed.\nAGREE")
    command = seen["command"]
    assert command[:2] == ["/seat/bin/claude", "-p"]
    assert command[command.index("--tools") + 1] == "default"
    assert command[command.index("--model") + 1] == "claude-opus-5-5"
    assert "--no-session-persistence" in command and "--bare" not in command
    assert seen["seat_jail"] is seat.jail and seen["probe_jail"] is seat.probe_jail
    assert seen["input_text"].startswith(pi._BROKER_CLAUDE_DIRECT_REQUEST)
    assert evidence["claude_route"] == "print"
    assert evidence["claude_api_key_source"] == "none" and evidence["claude_result_count"] == 1
    assert len(evidence["claude_result_event_sha256"]) == 64
    assert evidence["provider_input_inline"] is False
    assert evidence["provider_cwd_class"] == "seat_jail_tree"
    assert evidence["provider_prompt_transport"] == "stdin"
    assert not any(key.startswith("claude_transcript_") for key in evidence)
    assert len(removed) == 3


@pytest.mark.parametrize("route,code", [("sdk", "panel_claude_transport_not_admitted"),
                                       ("unknown", "panel_claude_route_invalid")])
def test_unadmitted_selection_cleans_up_without_launch(fake_seat, monkeypatch, route, code):
    seat, removed = fake_seat
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", route)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k: pytest.fail("launched"))
    assert _exec(seat, {}) == ("UNAVAILABLE", code)
    assert len(removed) == 3


def test_metadata_subscription_admission_precedes_provider(fake_seat, monkeypatch):
    seat, removed = fake_seat
    seat.claude_subscription_proven = False
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k: pytest.fail("launched"))
    assert _exec(seat, {}) == ("UNAVAILABLE", "subscription_auth_unproven")
    assert len(removed) == 3


LIVE = [pytest.mark.host_seat_credentials,
        pytest.mark.skipif(not seat_jail.execfind_pass_recorded(seat_jail.jail_profile_digest("claude")),
                           reason="recorded Claude jail qualification unavailable"),
        pytest.mark.skipif(not seat_uid_ready(), reason=SEAT_UID_PREREQUISITE),
        pytest.mark.skipif(not sandbox_egress.egress_isolation_available(), reason="filtered egress unavailable")]


@pytest.fixture(scope="module")
def executable_standin(tmp_path_factory):
    if shutil.which("cc") is None:
        pytest.skip("C compiler unavailable for executable compatibility fixture")
    root = tmp_path_factory.mktemp("claude-print-image")
    source, image = root / "standin.c", root / "claude"
    source.write_text(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    const char *mode = "success";
    for (int i=1; i+1<argc; i++) if (!strcmp(argv[i], "--name")) mode=argv[i+1];
    const char *auth_mode = "good";
    if (argc == 4 && !strcmp(argv[1], "auth") && !strcmp(argv[2], "status") && !strcmp(argv[3], "--json")) {
        char token[256]={0};
        const char *fd=getenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR");
        if (!getuid() || !fd || read(atoi(fd),token,sizeof(token)-1) <= 0 ||
            strcmp(token,"SEAT-JAIL-SENTINEL-print-compatibility")) return 40;
        if (strcmp(getenv("HOME"),"/seat/home") || strcmp(getenv("CLAUDE_CONFIG_DIR"),"/seat/home/.claude")) return 41;
        if (!strcmp(auth_mode,"timeout")) { while(1) pause(); }
        if (!strcmp(auth_mode,"missing")) return 0;
        if (!strcmp(auth_mode,"malformed")) { puts("not-json"); return 0; }
        if (!strcmp(auth_mode,"foreign")) { puts("{\"loggedIn\":true,\"authMethod\":\"oauth_token\",\"apiProvider\":\"bedrock\"}"); return 0; }
        if (!strcmp(auth_mode,"auth-key")) { puts("{\"loggedIn\":true,\"authMethod\":\"api_key\",\"apiProvider\":\"firstParty\"}"); return 0; }
        if (!strcmp(auth_mode,"key")) { puts("{\"loggedIn\":true,\"authMethod\":\"oauth_token\",\"apiProvider\":\"firstParty\",\"apiKeySource\":\"none\"}"); return 0; }
        if (!strcmp(auth_mode,"false")) { puts("{\"loggedIn\":false,\"authMethod\":\"oauth_token\",\"apiProvider\":\"firstParty\"}"); return 0; }
        if (!strcmp(auth_mode,"secret-stdout")) { write(1,token,12); usleep(150000); puts(token+12); while(1) pause(); }
        if (!strcmp(auth_mode,"secret-stderr")) { write(2,token,12); usleep(150000); fputs(token+12,stderr); fflush(stderr); while(1) pause(); }
        puts("{\"loggedIn\":true,\"authMethod\":\"oauth_token\",\"apiProvider\":\"firstParty\",\"email\":\"synthetic-private@example.invalid\"}");
        return !strcmp(auth_mode,"nonzero") ? 1:0;
    }
    char review_token[256]={0};
    const char *review_fd=getenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR");
    if (!review_fd || read(atoi(review_fd),review_token,sizeof(review_token)-1) <= 0 ||
        strcmp(review_token,"SEAT-JAIL-SENTINEL-print-compatibility")) return 42;
    char cwd[1024];
    if (!getuid() || !getcwd(cwd,sizeof(cwd)) || strcmp(cwd,"/seat/tree")) return 30;
    FILE *f=fopen("/seat/tree/source.txt","r"); if(!f) return 31; fclose(f);
    f=fopen("/seat/tree/disposable.txt","w"); if(!f) return 32; fputs("clone scratch",f); fclose(f);
    f=fopen("/seat/out/work.txt","w"); if(!f) return 33; fputs("scratch",f); fclose(f);
    char buf[1024]; while(fread(buf,1,sizeof(buf),stdin)) {}
    puts("{\"type\":\"system\",\"subtype\":\"init\",\"apiKeySource\":\"none\"}"); fflush(stdout);
    if (!strcmp(mode,"cancel") || !strcmp(mode,"timeout")) { while(1) pause(); }
    if (!strcmp(mode,"missing")) { puts("{\"type\":\"assistant\",\"content\":\"AGREE\"}"); return 0; }
    if (!strcmp(mode,"auth")) { puts("{\"type\":\"system\",\"subtype\":\"api_retry\",\"error\":\"billing_error\"}"); fflush(stdout); while(1) pause(); }
    if (!strcmp(mode,"bad-result")) { puts("{\"type\":\"result\",\"subtype\":\"error_during_execution\",\"result\":\"AGREE\"}"); return 0; }
    if (!strcmp(mode,"no-verdict")) { puts("{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"Reviewed the artifact.\"}"); return 0; }
    puts("{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":false,\"result\":\"Reviewed.\\nAGREE\"}"); fflush(stdout);
    if (!strncmp(mode,"secret-",7)) {
        int fd=!strcmp(mode,"secret-stderr") ? 2:1;
        const char *secret="SEAT-JAIL-SENTINEL-print-compatibility";
        write(fd,secret,12); usleep(150000); write(fd,secret+12,strlen(secret)-12);
        while(1) pause();
    }
    return 0;
}
''')
    subprocess.run(["cc", "-O2", "-o", str(image), str(source)], check=True, capture_output=True)
    image.chmod(0o755)
    return image


@contextlib.contextmanager
def live_seat(tmp_path, monkeypatch, executable, *, login_env=None, synthetic=True):
    # Real jail, subordinate UID, seccomp, keyring, identity probe and filtered egress.
    # Only the test credential and executable selection replace provider/account inputs.
    if synthetic:
        monkeypatch.setattr(pi._seat_credentials, "resolve_claude_seat_credential",
                            lambda *a, **kw: types.SimpleNamespace(token=TOKEN, source="seat_token", expires_at=None, notices=[]))
        monkeypatch.setattr(pi._seat_credentials, "read_login_store", lambda **kw: _login_store())
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda **kw: (True, "supported"))
    monkeypatch.setattr(pi, "_resolve_claude_executable", lambda: executable)
    monkeypatch.delenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", raising=False)
    review = tmp_path / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "source.txt").write_text("source\n")
    tree_fd = seat_jail.open_dir_nofollow(tree)
    try:
        auth = types.SimpleNamespace(staged_tree_sha256=seat_jail.tree_manifest_sha256_at(tree_fd))
    finally:
        os.close(tree_fd)
    uids, gids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE), seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=120, required=True, seat_uid_map=True) as prefix:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
        try:
            seat = pi._prepare_jailed_claude(review, tmp_path / "seat", auth, n,
                                            seat_uid.holder_pid_from_prefix(prefix), ("bundle", "brief"), timeout_s=5,
                                            env={} if login_env is None else login_env)
            yield seat
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)


@pytest.mark.parametrize("scenario,expected", [
    ("success", "OK"), ("missing", "DEGRADED"), ("auth", "UNAVAILABLE"),
    ("bad-result", "DEGRADED"), ("no-verdict", "DEGRADED"),
    ("secret-stdout", "DEGRADED"), ("secret-stderr", "DEGRADED"),
])
@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
def test_executable_print_transport_on_production_jail(tmp_path, monkeypatch, executable_standin, scenario, expected, _live):
    evidence, sink = {}, []
    with live_seat(tmp_path, monkeypatch, executable_standin) as seat:
        status, text = _exec(seat, evidence, session_name=scenario, failure_detail_sink=sink)
    assert status == expected, (status, text, sink)
    if scenario.startswith("secret-"):
        assert text == "" and sink[-1].template == "claude_seat_token_in_output"
    assert TOKEN.decode() not in repr((text, evidence, sink))
    assert not (tmp_path / "review" / seat_jail.HOST_TREE_DIRNAME).exists()
    assert not (tmp_path / "seat" / seat_jail.HOST_HOME_DIRNAME).exists()


@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
def test_cancelled_print_reaps_group_and_releases_latch(tmp_path, monkeypatch, executable_standin, _live):
    cancel = threading.Event()
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "compatibility", 0, cancel)
    latch = pi._ProviderQuiescenceLatch()
    spawned = []
    real_launch = pi.launch_provider

    def launch(*a, **kw):
        proc = real_launch(*a, **kw)
        if isinstance(kw.get("process_owner"), seat_jail.SeatJail):
            spawned.append(proc)
            if "-p" in a[0]:
                threading.Timer(0.5, cancel.set).start()
        return proc

    monkeypatch.setattr(pi, "launch_provider", launch)
    with live_seat(tmp_path, monkeypatch, executable_standin) as seat:
        assert _exec(seat, {}, session_name="cancel", review_monitor=monitor,
                     quiescence_latch=latch) == ("UNAVAILABLE", "review_operation_cancelled")
    assert len(spawned) == 2 and all(proc.poll() is not None for proc in spawned)
    latch.raise_if_set()
    assert not latch._processes


@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
@pytest.mark.parametrize("help_args,expected", [
    (["-h"], "--print"), (["auth", "-h"], "status"),
    (["auth", "status", "-h"], "--json"),
])
def test_native_image_help_uses_the_same_jail_launcher(tmp_path, monkeypatch, _live, help_args, expected):
    executable = pi._resolve_claude_executable()
    with live_seat(tmp_path, monkeypatch, executable) as seat:
        try:
            result = pi._run_leg_with_liveness(
                [seat.jail.provider_argv0, *help_args], cwd=seat_jail.SEAT_TREE,
                env=dict(seat.jail.env), deadline_s=30,
                seat_jail=seat.jail, probe_jail=seat.probe_jail,
            )
            assert result.returncode == 0, result.stderr
            assert expected in result.stdout
            assert TOKEN not in (result.stdout + result.stderr).encode()
        finally:
            seat_jail.close_jail_fds(seat.jail)
            seat_jail.close_jail_fds(seat.probe_jail)
            for parent in (seat.review_dir, seat.seat_dir, seat.seat_dir / pi._JAIL_PROBE_DIRNAME):
                seat_uid.teardown_in_h(seat.holder_pid, str(parent))


@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
@pytest.mark.parametrize("boundary", ["deadline", "stall"])
def test_bounded_print_reclaims_native_wait(tmp_path, monkeypatch, executable_standin, _live, boundary):
    latch = pi._ProviderQuiescenceLatch()
    monkeypatch.setattr(pi, "_broker_claude_stall_threshold",
                        lambda *a: 0.1 if boundary == "stall" else 30.0)
    with live_seat(tmp_path, monkeypatch, executable_standin) as seat:
        status, text = _exec(seat, {}, session_name="timeout", quiescence_latch=latch)
    assert status == ("TIMEOUT" if boundary == "deadline" else "DEGRADED")
    assert text == ""
    latch.raise_if_set()
    assert not latch._processes


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_retained_streams_are_checked_before_result_or_tail(fake_seat, monkeypatch, channel):
    seat, removed = fake_seat
    def run(command, **kw):
        data = json.dumps(INIT).encode() + b"\n" + json.dumps(RESULT).encode() + b"\n"
        kw["stdout_guard"](data)
        # A retained-only stand-in intentionally does not call the chunk guard. Put the
        # sentinel before a long suffix so a tail-only check would not cover it.
        retained = TOKEN.decode() + "x" * 4000
        return pi._LegRun(0, retained if channel == "stdout" else data.decode(),
                         retained if channel == "stderr" else "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    sink, evidence = [], {}
    assert _exec(seat, evidence, failure_detail_sink=sink) == ("DEGRADED", "")
    assert sink[-1].template == "claude_seat_token_in_output"
    assert len(removed) == 3
    assert TOKEN.decode() not in repr((sink, evidence))


_REAL_JAILED_AUTH = pi._jailed_claude_subscription_auth_ok
AUTH_STATUS = {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}


@pytest.mark.parametrize("payload,rc,timeout", [
    ("", 0, False), ("not-json", 0, False), ("[]", 0, False),
    (json.dumps({**AUTH_STATUS, "apiProvider": "bedrock"}), 0, False),
    (json.dumps({**AUTH_STATUS, "authMethod": "claude.ai"}), 0, False),
    (json.dumps({**AUTH_STATUS, "authMethod": "api_key"}), 0, False),
    (json.dumps({**AUTH_STATUS, "apiKeySource": "none"}), 0, False),
    (json.dumps({**AUTH_STATUS, "loggedIn": False}), 0, False),
    (json.dumps(AUTH_STATUS), 1, False), ("", 0, True),
    (json.dumps(AUTH_STATUS), 0, False),
])
def test_private_auth_status_admission_and_cleanup(fake_seat, monkeypatch, payload, rc, timeout, caplog):
    seat, removed = fake_seat
    built, descriptors, launched = [], [], []

    def build(seat, directory, token):
        fd = seat_jail.token_pipe(token)
        descriptors.append(fd)
        jail = types.SimpleNamespace(provider_argv0="/seat/bin/claude", env={},
                                     profile_digest=seat.jail.profile_digest,
                                     filter_digest=seat.jail.filter_digest, pass_fds=(fd,))
        built.append(jail)
        return jail

    def run(command, **kw):
        launched.append(command)
        assert kw["seat_jail"] is built[0] and kw["probe_jail"] is built[1]
        assert all(jail is not seat.jail for jail in built)
        assert os.read(built[0].pass_fds[0], 1024) == TOKEN
        assert os.read(built[1].pass_fds[0], 1024) == b"probe"
        if timeout:
            raise subprocess.TimeoutExpired(command, 0.1, output="private-status-identity")
        return pi._LegRun(rc, payload, "private-status-identity")

    monkeypatch.setattr(pi, "_build_claude_auth_jail", build)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    monkeypatch.setattr(pi, "run_provider", lambda *a, **k: pytest.fail("generic provider reread"))
    monkeypatch.setattr(seat_jail, "close_jail_fds", lambda jail: [os.close(fd) for fd in jail.pass_fds])
    assert _REAL_JAILED_AUTH(seat) is (payload == json.dumps(AUTH_STATUS) and rc == 0 and not timeout)
    assert launched == [["/seat/bin/claude", "auth", "status", "--json"]]
    assert len(removed) == 2
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert "private-status-identity" not in caplog.text
    assert payload not in caplog.text if payload else True


@pytest.mark.parametrize("mode", ["missing", "malformed", "foreign", "key", "auth-key", "false", "nonzero",
                                  "timeout", "secret-stdout", "secret-stderr"])
@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
def test_actual_auth_status_refusal_prevents_review_and_cleans_up(
    tmp_path, monkeypatch, executable_standin, mode, _live, caplog,
):
    source, image = tmp_path / "auth.c", tmp_path / "claude"
    source.write_text(executable_standin.with_name("standin.c").read_text().replace(
        'const char *auth_mode = "good";', f'const char *auth_mode = "{mode}";'))
    subprocess.run(["cc", "-O2", "-o", str(image), str(source)], check=True, capture_output=True)
    launches, fds, sink, evidence = [], [], [], {}
    real_launch, real_build = pi.launch_provider, pi._build_claude_auth_jail

    def launch(command, **kw):
        if isinstance(kw.get("process_owner"), seat_jail.SeatJail):
            launches.append(command)
        return real_launch(command, **kw)

    def build(*args):
        jail = real_build(*args)
        fds.extend(jail.pass_fds)
        return jail

    monkeypatch.setattr(pi, "launch_provider", launch)
    monkeypatch.setattr(pi, "_build_claude_auth_jail", build)
    monkeypatch.setattr(pi, "_jailed_claude_subscription_auth_ok",
                        lambda seat, **kw: _REAL_JAILED_AUTH(seat, **{**kw, "timeout_s": 0.5}))
    latch = pi._ProviderQuiescenceLatch()
    with live_seat(tmp_path, monkeypatch, image) as seat:
        fds.extend((*seat.jail.pass_fds, *seat.probe_jail.pass_fds))
        assert _exec(seat, evidence, failure_detail_sink=sink, quiescence_latch=latch) == (
            "UNAVAILABLE", "subscription_auth_unproven")
    assert launches == [["/seat/bin/claude", "auth", "status", "--json"]]
    assert evidence == {} and sink == []
    assert "synthetic-private" not in repr((caplog.text, evidence, sink))
    assert TOKEN.decode() not in repr((caplog.text, evidence, sink))
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)
    for directory in (seat.seat_dir, seat.seat_dir / "seat-auth", seat.seat_dir / "seat-auth-probe"):
        assert not (directory / seat_jail.HOST_HOME_DIRNAME).exists()
    assert not (seat.review_dir / seat_jail.HOST_TREE_DIRNAME).exists()
    latch.raise_if_set()
    assert not latch._processes


@pytest.mark.parametrize("context_kind", ["config", "home"])
@pytest.mark.parametrize("selected_subscription", [True, False])
@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
def test_selected_login_context_controls_metadata_and_actual_descriptor(
    tmp_path, monkeypatch, executable_standin, context_kind, selected_subscription, _live,
):
    # Actual synthetic stores and resolver: the process login disagrees with the selected
    # one. No real account or store may participate, and execution never re-selects one.
    selected, ambient = tmp_path / "selected", tmp_path / "ambient"
    selected.mkdir()
    ambient.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(ambient))
    monkeypatch.setattr(seat_jail, "claude_seat_token_path",
                        lambda: tmp_path / "synthetic-state" / "claude")
    (selected / ".credentials.json").write_bytes(_login_store(subscription=selected_subscription))
    (ambient / ".credentials.json").write_bytes(_login_store(b"other-account-token", not selected_subscription))
    login_env = ({"CLAUDE_CONFIG_DIR": str(selected)} if context_kind == "config" else
                 {"HOME": str(tmp_path / "selected-home")})
    if context_kind == "home":
        home = tmp_path / "selected-home"
        home.mkdir()
        (home / ".claude").symlink_to(selected, target_is_directory=True)
    reads = []
    real_read = pi._seat_credentials.read_login_store

    def read(**kw):
        reads.append(kw["env"]["CLAUDE_CONFIG_DIR"])
        return real_read(**kw)

    monkeypatch.setattr(pi._seat_credentials, "read_login_store", read)
    with live_seat(tmp_path, monkeypatch, executable_standin, login_env=login_env, synthetic=False) as seat:
        assert seat.token == TOKEN and seat.source == "login"
        assert seat.claude_subscription_proven is selected_subscription
        # Deliberately change the later caller context: it must neither prove nor select
        # a credential. The actual auth executable accepts only the selected TOKEN bytes.
        status, text = pi._exec_jailed_claude_leg(
            seat, timeout_s=5, backstop_s=5, model="claude-opus-5-5", effort="high",
            prompt="Review.", broker_evidence={}, env={"CLAUDE_CONFIG_DIR": str(ambient)},
        )
    assert status == ("OK" if selected_subscription else "UNAVAILABLE"), (status, text)
    assert len(reads) == 1 and reads[0] != str(ambient)


@pytest.mark.parametrize("context_kind", ["config", "home"])
def test_login_wait_reads_only_the_explicit_login_context(tmp_path, monkeypatch, context_kind):
    sc = pi._seat_credentials
    selected, ambient = tmp_path / "selected" / ".claude", tmp_path / "ambient"
    selected.mkdir(parents=True)
    ambient.mkdir()
    short = json.loads(_login_store())
    short["claudeAiOauth"]["expiresAt"] = 1000
    (selected / ".credentials.json").write_text(json.dumps(short))
    (ambient / ".credentials.json").write_bytes(_login_store())
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(ambient))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    login_env = ({"CLAUDE_CONFIG_DIR": str(selected)} if context_kind == "config" else
                 {"HOME": str(selected.parent)})
    monkeypatch.setenv(sc.WAIT_ENV, "0")
    reads = []
    real_read = sc.read_login_store

    def read(**kw):
        reads.append(kw["env"]["CLAUDE_CONFIG_DIR"])
        return real_read(**kw)

    monkeypatch.setattr(sc, "read_login_store", read)
    assert pi._await_claude_login(5, None, env=login_env).outcome == sc.LOGIN_TIMEOUT
    assert reads and set(reads) == {str(selected)}
    (selected / ".credentials.json").write_bytes(_login_store())
    assert pi._await_claude_login(5, None, env=login_env).outcome == sc.LOGIN_READY
    assert set(reads) == {str(selected)}


@pytest.mark.parametrize("_live", [pytest.param(None, marks=LIVE)])
@pytest.mark.parametrize("bound", [True, False])
def test_auth_uses_exact_override_record_bytes_bound_to_selected_account(
    tmp_path, monkeypatch, executable_standin, bound, _live,
):
    sc = pi._seat_credentials
    config = tmp_path / "selected"
    config.mkdir()
    (config / ".credentials.json").write_bytes(_login_store(b"selected-login" if bound else TOKEN))
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "accountUuid": "selected-account", "organizationUuid": "selected-org"}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "unselected"))
    # Keep the actual qualification store; only the synthetic override-record path moves.
    monkeypatch.setattr(seat_jail, "claude_seat_token_path",
                        lambda: tmp_path / "synthetic-state" / "claude")
    record = sc.ClaudeCredentialAdapter().record_path()
    record.parent.mkdir(mode=0o700, parents=True)
    record.write_text(json.dumps({"schema": sc.RECORD_SCHEMA,
                                 "account": "selected-account" if bound else "unselected-account",
                                 "organization": "selected-org", "token": TOKEN.decode()}))
    record.chmod(0o600)
    original = sc.ClaudeCredentialAdapter.read_override
    reads = []

    def read(adapter):
        value = original(adapter)
        reads.append(value)
        # Concurrent replacement after the binding read must not replace the selected
        # token; the unchanged resolver returns the bytes in the checked record.
        record.write_text(json.dumps({"schema": sc.RECORD_SCHEMA, "account": "selected-account",
                                     "organization": "selected-org", "token": "other-record-token"}))
        return value

    monkeypatch.setattr(sc.ClaudeCredentialAdapter, "read_override", read)
    with live_seat(tmp_path, monkeypatch, executable_standin,
                   login_env={"CLAUDE_CONFIG_DIR": str(config)}, synthetic=False) as seat:
        assert seat.source == ("seat_token" if bound else "login")
        assert seat.token == TOKEN
        assert _exec(seat, {}) == ("OK", "Reviewed.\nAGREE")
    assert len(reads) == 1


def test_auth_jail_construction_failure_closes_allocated_descriptors(fake_seat, monkeypatch):
    seat, removed = fake_seat
    seat.jail.provider_path = "/synthetic/claude"
    seat.jail.seat_ids = (1, 1)
    descriptors = []
    real_memfd, real_pipe = seat_jail.memfd_with, seat_jail.token_pipe

    def memfd(*a):
        fd = real_memfd(*a)
        descriptors.append(fd)
        return fd

    def pipe(*a):
        fd = real_pipe(*a)
        descriptors.append(fd)
        return fd

    monkeypatch.setattr(seat_jail, "memfd_with", memfd)
    monkeypatch.setattr(seat_jail, "token_pipe", pipe)
    monkeypatch.setattr(seat_jail, "build_seat_jail", lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic")))
    monkeypatch.setattr(pi, "_jailed_claude_subscription_auth_ok", _REAL_JAILED_AUTH)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k: pytest.fail("review launched"))
    assert _exec(seat, {}) == ("UNAVAILABLE", "subscription_auth_unproven")
    assert len(descriptors) == 3 and len(removed) == 5
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
