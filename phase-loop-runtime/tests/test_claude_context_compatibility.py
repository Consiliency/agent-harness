"""Claude login-context and lifecycle compatibility with synthetic private stores."""
import json
import os
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail, seat_uid

TOKEN = b"SYNTHETIC-CORRECTNESS-TOKEN-r1-ONLY"
INIT = {"type": "system", "subtype": "init", "apiKeySource": "none"}
RESULT = {"type": "result", "subtype": "success", "result": "Reviewed.\nAGREE", "is_error": False}


def make_seat(root):
    jail = types.SimpleNamespace(
        leg="claude", provider_argv0="/seat/bin/claude", env={"HOME": "/seat/home"},
        profile_digest="d" * 64, profile_id="jail", filter_digest="f" * 64,
        redacted_owner=lambda: ["bwrap", "--"], pass_fds=(),
    )
    jail.pass_fds = (seat_jail.token_pipe(TOKEN),)
    probe = types.SimpleNamespace(pass_fds=(seat_jail.token_pipe(b"probe"),))
    return pi._JailedSeat(jail, probe, 1, TOKEN, root / "review", root / "seat",
                          claude_subscription_proven=True)


@pytest.mark.parametrize("record_failure", [False, True])
@pytest.mark.parametrize("route,boundary", [("print", "auth"), ("print", "review"), ("tui", "auth")])
def test_private_roots_follow_process_lifecycle(tmp_path, route, boundary, record_failure, monkeypatch):
    seat = make_seat(tmp_path)
    registered = []
    def record(path):
        registered.append(path)
        if record_failure and (boundary == "auth" or path not in (
                seat.seat_dir / "seat-auth", seat.seat_dir / "seat-auth-probe")):
            raise OSError("synthetic retention recorder unavailable")
    monkeypatch.setattr(seat_uid, "record_retention", record)
    teardown_calls = []
    descriptors = [*seat.jail.pass_fds, *seat.probe_jail.pass_fds]
    fatal = pi.ProviderProcessGroupQuiescenceError("synthetic unquiescent process group")

    def build(seat, directory, token):
        fd = seat_jail.token_pipe(token)
        descriptors.append(fd)
        return types.SimpleNamespace(
            provider_argv0="/seat/bin/claude", env={}, pass_fds=(fd,),
            profile_digest=seat.jail.profile_digest, filter_digest=seat.jail.filter_digest,
        )

    def run(command, **kw):
        if command[1:4] == ["auth", "status", "--json"] and boundary == "review":
            assert os.read(kw["seat_jail"].pass_fds[0], 4096) == TOKEN
            return pi._LegRun(0, json.dumps({"loggedIn": True, "authMethod": "oauth_token",
                                            "apiProvider": "firstParty"}), "")
        raise fatal

    with patch.dict(os.environ, {"PHASE_LOOP_PANEL_CLAUDE_ROUTE": route}), \
            patch.object(pi, "_claude_code_support_status", return_value=(True, "supported")), \
            patch.object(pi, "_build_claude_auth_jail", side_effect=build), \
            patch.object(pi, "_run_leg_with_liveness", side_effect=run), \
            patch.object(seat_uid, "teardown_in_h", side_effect=lambda h, p: teardown_calls.append(p) or []):
        with pytest.raises(pi.ProviderProcessGroupQuiescenceError) as raised:
            pi._exec_jailed_claude_leg(
                seat, timeout_s=5, backstop_s=5, model="claude-opus-5-5", effort="high",
                prompt="Synthetic review.", broker_evidence={}, env={},
            )
    assert raised.value is fatal
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    # The auth roots of a successfully quiesced auth run may already be removed.
    forbidden = teardown_calls if boundary == "auth" else [
        p for p in teardown_calls if p in (str(seat.review_dir), str(seat.seat_dir),
                                          str(seat.seat_dir / pi._JAIL_PROBE_DIRNAME))]
    assert seat.review_dir / seat_jail.HOST_TREE_DIRNAME in registered
    assert seat.seat_dir / seat_jail.HOST_HOME_DIRNAME in registered
    assert seat.seat_dir / pi._JAIL_PROBE_DIRNAME / seat_jail.HOST_HOME_DIRNAME in registered
    if boundary == "auth":
        assert seat.seat_dir / "seat-auth" / seat_jail.HOST_HOME_DIRNAME in registered
        assert seat.seat_dir / "seat-auth-probe" / seat_jail.HOST_HOME_DIRNAME in registered
    assert not forbidden, f"teardown attempted despite fatal quiescence: {forbidden}"


@pytest.mark.parametrize("configured", [None, ""])
@pytest.mark.parametrize("stale_nested_identity", [False, True])
def test_default_home_account_selection(tmp_path, stale_nested_identity, configured):
    sc = pi._seat_credentials
    home, state, review = tmp_path / "home", tmp_path / "state", tmp_path / "review"
    config = home / ".claude"
    config.mkdir(parents=True)
    identity_a = {"oauthAccount": {"accountUuid": "current-A", "organizationUuid": "org-A"}}
    identity_b = {"oauthAccount": {"accountUuid": "old-B", "organizationUuid": "org-B"}}
    (home / ".claude.json").write_text(json.dumps(identity_a))
    if stale_nested_identity:
        (config / ".claude.json").write_text(json.dumps(identity_b))
    (config / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "synthetic-login-A", "expiresAt": 4102444800000,
        "scopes": ["user:inference"], "subscriptionType": "synthetic"}}))
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "source.txt").write_text("synthetic\n")
    fd = seat_jail.open_dir_nofollow(tree)
    try:
        digest = seat_jail.tree_manifest_sha256_at(fd)
    finally:
        os.close(fd)
    with patch.dict(os.environ, {"HOME": str(home), "XDG_STATE_HOME": str(state),
                                "PATH": "/usr/bin:/bin"}, clear=True), \
            patch.object(pi, "_resolve_claude_executable", return_value=Path("/usr/bin/true")):
        if configured is not None:
            os.environ["CLAUDE_CONFIG_DIR"] = configured
        # Create a real private override record without touching any host state.
        adapter = sc.ClaudeCredentialAdapter()
        record = adapter.record_path()
        record.parent.mkdir(mode=0o700, parents=True)
        bound = identity_b if stale_nested_identity else identity_a
        account = bound["oauthAccount"]
        record.write_text(json.dumps({"schema": sc.RECORD_SCHEMA,
                                     "account": account["accountUuid"],
                                     "organization": account["organizationUuid"],
                                     "token": "synthetic-override"}))
        record.chmod(0o600)
        # This is the pre-change default jailed selection, and the store-token identity.
        original = sc.resolve_claude_seat_credential(0)
        expected_source = "login" if stale_nested_identity else "seat_token"
        assert original.source == expected_source
        selected = dict(os.environ)
        assert sc.override_present(env=selected) is (not stale_nested_identity)
        assert sc.claude_seat_credential_present(env=selected)
        wait = sc.await_login_margin(10**12, max_wait_s=0, poll_s=1, wait=lambda _: False, env=selected)
        assert wait.outcome == (sc.LOGIN_TIMEOUT if stale_nested_identity else sc.LOGIN_READY)
        assert bool(pi._ignored_override("claude", selected)) is stale_nested_identity
        seat = pi._prepare_jailed_claude(
            review, tmp_path / "seat", types.SimpleNamespace(staged_tree_sha256=digest),
            1, 1, ("synthetic-bundle", "synthetic-instructions"), timeout_s=5,
        )
    try:
        assert seat.source == expected_source, (
            f"default account context changed: expected {expected_source}, got {seat.source}; "
            f"stale_nested_identity={stale_nested_identity}")
    finally:
        seat_jail.close_jail_fds(seat.jail)
        seat_jail.close_jail_fds(seat.probe_jail)


@pytest.mark.parametrize("selected", [{}, {"PATH": "/usr/bin:/bin"}, {"HOME": "", "CLAUDE_CONFIG_DIR": ""}])
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_explicit_context_requires_a_login_location(tmp_path, monkeypatch, selected, platform):
    sc = pi._seat_credentials
    actual_platform = sc.sys.platform
    home = tmp_path / "ambient"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/.credentials.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "synthetic-ambient", "expiresAt": 4102444800000,
        "scopes": ["user:inference"], "subscriptionType": "synthetic"}}))
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "accountUuid": "ambient", "organizationUuid": "ambient-org"}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(sc.sys, "platform", platform)
    calls = []
    real_read = sc._read_store_file
    monkeypatch.setattr(sc, "_read_store_file", lambda path: calls.append(path) or real_read(path))
    monkeypatch.setattr(sc, "_read_store_keychain", lambda *a: calls.append("keychain") or b"{}")
    monkeypatch.setattr(sc, "_read_owner_only", lambda *a, **k: calls.append("identity"))
    monkeypatch.setattr(sc.ClaudeCredentialAdapter, "read_override", lambda _: calls.append("override"))
    assert not sc.claude_seat_credential_present(env=selected,
        read_login=lambda: pytest.fail("login callback read without a selected location"))
    assert pi._ignored_override("claude", selected) == ()
    assert not sc.login_subscription_proven(env=selected,
        read_store=lambda: pytest.fail("metadata callback read without a selected location"))
    assert sc.ClaudeCredentialAdapter(selected).current_identity() is None
    assert sc.await_login_margin(5, max_wait_s=0, poll_s=1, wait=lambda _: False,
                                 env=selected, read_login=lambda: pytest.fail("wait read")).outcome == sc.LOGIN_MISSING
    with pytest.raises(seat_jail.SeatSandboxRefused, match="claude_seat_token_missing"):
        sc.resolve_claude_seat_credential(1, env=selected, read_login=lambda: pytest.fail("resolver read"))
    monkeypatch.setattr(sc.sys, "platform", actual_platform)
    _, _, refusal = pi._seat_route_for_spawn(
        "claude", types.SimpleNamespace(staged_tree_sha256="a" * 64),
        eligible=True, env=selected,
        qualify_on_first_use=lambda _: pytest.fail("qualification launched"))
    assert refusal == "claude_seat_token_missing"
    assert calls == []


@pytest.mark.parametrize("init_id,result_id", [
    (None, "expected"), ("expected", None), ("other", "expected"),
    ("expected", "other"), (3, "expected"), ("expected", 3),
    ("other", "other"), ("expected", "expected"),
])
def test_print_events_follow_command_session(monkeypatch, init_id, result_id):
    expected = "11111111-1111-4111-8111-111111111111"
    other = "22222222-2222-4222-8222-222222222222"
    def event(base, value):
        return {**base, **({"session_id": expected if value == "expected" else other if value == "other" else value}
                          if value is not None else {})}
    wire = b"".join(json.dumps(e).encode() + b"\n" for e in
                    (event(INIT, init_id), event(RESULT, result_id)))
    def run(command, **kw):
        kw["stdout_guard"](wire)
        return pi._LegRun(0, wire.decode(), "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    observed = {}
    rc, text, log, _ = pi._run_claude_print_session(
        ["/synthetic/claude", "-p", "--session-id", expected], "synthetic",
        env={}, cwd=Path("/tmp"), timeout_s=5, seat_jail=object(), observed=observed)
    if init_id == result_id == "expected":
        assert (rc, text, log) == (0, "Reviewed.\nAGREE", "claude_print_result")
    else:
        assert rc != 0 and not text and log == "claude_print_session_unproven"
        leg = pi.PanelLegResult(leg="claude", status="UNAVAILABLE", text=text, detail=log)
        assert leg.detail == "claude_print_session_unproven"
    assert expected not in repr(observed) and other not in repr(observed)


@pytest.mark.parametrize("configured", [None, ""])
def test_default_keychain_context_preserves_account_and_service(tmp_path, configured):
    sc = pi._seat_credentials
    selected = {"HOME": str(tmp_path), "USER": "synthetic-user"}
    if configured is not None:
        selected["CLAUDE_CONFIG_DIR"] = configured
    calls = []
    def run(command, **kw):
        calls.append(command)
        return types.SimpleNamespace(returncode=0, stdout=b"{}")
    sc.read_login_store(platform="darwin", env=selected, run=run)
    assert calls == [["/usr/bin/security", "find-generic-password", "-a", "synthetic-user",
                      "-s", "Claude Code-credentials", "-w"]]


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_print_transport_checks_token_forms_across_chunks(monkeypatch, channel):
    expected = "11111111-1111-4111-8111-111111111111"
    wire = b"".join(json.dumps({**e, "session_id": expected}).encode() + b"\n" for e in (INIT, RESULT))
    for form in seat_jail.secret_encodings(TOKEN):
        for split in range(1, len(form)):
            def run(command, **kw):
                assert not kw["output_guard"]("stdout", wire)
                assert not kw["stdout_guard"](wire)
                assert not kw["output_guard"](channel, form[:split])
                assert kw["output_guard"](channel, form[split:])
                return pi._LegRun(1, "", "provider_output_refused")
            monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
            observed = {}
            result = pi._run_claude_print_session(
                ["/synthetic/claude", "-p", "--session-id", expected], "synthetic",
                env={}, cwd=Path("/tmp"), timeout_s=5, seat_jail=object(),
                seat_token=TOKEN, observed=observed)
            assert result == (1, "", "claude_seat_token_in_output", "")
            assert observed == {}
