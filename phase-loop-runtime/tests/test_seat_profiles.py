"""Private per-launch subscription profiles contain only declared state."""

import json
import hashlib
import os
from pathlib import Path
import sys

import pytest

from phase_loop_runtime import seat_jail
from phase_loop_runtime import panel_invoker, gemini_heartbeat


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat profiles")


def test_environment_preparation_does_not_claim_completed_profile_cleanup():
    evidence = {}
    with panel_invoker._brokered_agy_environment({'HOME': '/synthetic-home'}, evidence) as env:
        assert env == {'HOME': '/synthetic-home'}
        assert evidence.get('provider_agy_home_cleanup_verified') is not True
        assert 'provider_agy_subscription_reference' not in evidence
    assert evidence.get('provider_agy_home_cleanup_verified') is not True


@pytest.fixture
def operator_home(tmp_path, monkeypatch):
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES,
                        hashlib.sha256(Path("/usr/bin/true").read_bytes()).hexdigest(), "synthetic-help")
    home = tmp_path / "operator"
    home.mkdir()
    for directory in (".codex", ".claude", ".grok", ".gemini/antigravity-cli"):
        (home / directory).mkdir(parents=True)
    (home / ".codex/auth.json").write_text('{"OPENAI_API_KEY":"synthetic-codex-api-key","tokens":{"id_token":"synthetic-id-token","access_token":"synthetic-access-token","refresh_token":"synthetic-refresh-token"}}')
    (home / ".claude/.credentials.json").write_text('{"claudeAiOauth":{"accessToken":"synthetic-access-token","refreshToken":"synthetic-refresh-token","expiresAt":9999999999999}}')
    (home / ".claude/.credentials.json").chmod(0o600)  # as the CLI stores it (#1253 reads only that)
    (home / ".grok/auth.json").write_text('{"https://auth.example::id":{"key":"synthetic-grok-token","refresh_token":"synthetic-refresh-token"}}')
    (home / ".grok/agent_id").write_text("synthetic-agent")
    (home / ".gemini/antigravity-cli/antigravity-oauth-token").write_text(json.dumps({
        "auth_method": "oauth", "token": {"access_token": "synthetic-access-token",
        "refresh_token": "synthetic-refresh-token", "token_type": "Bearer", "expiry": "2099-01-01T00:00:00Z"}}))
    return home


def _files(profile):
    args = profile.mount_args
    return {args[index + 2]: os.pread(int(args[index + 1]), 1_000_000, 0)
            for index, item in enumerate(args) if item == "--file"}


@pytest.mark.parametrize("harness", ["codex", "claude", "grok", "gemini"])
def test_profile_uses_copies_and_scrubs_ambient_state(operator_home, tmp_path, harness):
    env = {"HOME": str(operator_home), "PATH": "/usr/bin:/bin",
           "SYNTHETIC_OPERATOR_SECRET": "must-not-forward", "NODE_OPTIONS": "must-not-forward"}
    with panel_invoker.seat_profile(harness=harness, executable="/usr/bin/true", env=env,
                                   cwd=tmp_path) as (command, profile):
        assert command == "/run/phase-loop-seat/provider"
        assert profile.env["HOME"] != str(operator_home)
        assert "SYNTHETIC_OPERATOR_SECRET" not in profile.env
        assert "NODE_OPTIONS" not in profile.env
        assert "--symlink" not in profile.mount_args
        assert str(operator_home) not in profile.mount_args
        files = _files(profile)
        assert files
        assert all(descriptor in profile.pass_fds for descriptor in
                   [int(profile.mount_args[i + 1]) for i, item in enumerate(profile.mount_args) if item == "--file"])
        if harness in ("codex", "grok"):
            # The narrowest credential each CLI runs with: never the refresh token.
            copied = next(data for path, data in files.items() if path.endswith("auth.json"))
            assert b"synthetic-refresh-token" not in copied
            assert b"synthetic-access-token" in copied or b"synthetic-grok-token" in copied
            if harness == "codex":
                tokens = json.loads(copied)["tokens"]
                assert tokens["refresh_token"] == "" and tokens["id_token"] == "synthetic-id-token"
        if harness == "codex":
            config = next(data for path, data in files.items() if path.endswith("config.toml"))
            assert b'cli_auth_credentials_store = "file"' in config
            assert not profile.env["HOME"].startswith(("/dev/", "/tmp/"))
        if harness == "gemini":
            credential = next(data for path, data in files.items()
                              if path.endswith("antigravity-oauth-token"))
            assert b"synthetic-access-token" in credential
            assert b"synthetic-refresh-token" not in credential
        if harness == "claude":
            # agent-harness#1253's one decision, delivered through one drained pipe that the
            # seat keeps: the access token only, never a credential file in its home.
            assert not any(path.endswith(".credentials.json") for path in files)
            descriptor = int(profile.env[seat_jail.CLAUDE_TOKEN_FD_ENV])
            assert descriptor in profile.pass_fds and descriptor in profile.keep_fds
            assert os.read(descriptor, 4096) == b"synthetic-access-token"
        descriptors = profile.pass_fds
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_claude_profile_preseeds_only_the_current_workspace(operator_home, tmp_path):
    with panel_invoker.seat_profile(harness="claude", executable="/usr/bin/true",
                                   env={"HOME": str(operator_home)}, cwd=tmp_path) as (_, profile):
        settings = json.loads(next(data for path, data in _files(profile).items() if path.endswith(".claude.json")))
        assert settings["hasCompletedOnboarding"] is True
        assert set(settings["projects"]) == {str(tmp_path)}


def test_profile_refuses_linked_credentials(operator_home, tmp_path):
    path = operator_home / ".codex/auth.json"
    path.unlink()
    path.symlink_to(operator_home / ".grok/auth.json")
    with pytest.raises(Exception, match="seat_output|seat_profile"):
        with panel_invoker.seat_profile(harness="codex", executable="/usr/bin/true",
                                       env={"HOME": str(operator_home)}, cwd=tmp_path):
            pytest.fail("profile accepted linked state")


def test_heartbeat_profile_uses_private_access_copy(operator_home, tmp_path):
    from types import SimpleNamespace
    image = os.open('/usr/bin/true', os.O_RDONLY)
    settings = os.memfd_create('synthetic-settings', os.MFD_CLOEXEC)
    os.write(settings, b'{}')
    original = operator_home / '.gemini/antigravity-cli/antigravity-oauth-token'
    destination = gemini_heartbeat.PRIVATE_HOME + '/.gemini/antigravity-cli/antigravity-oauth-token'
    admitted = SimpleNamespace(
        mount_args=('--symlink', str(original), destination),
        executable='/run/phase-loop-seat/provider', image_fd=image, settings_fd=settings,
        pass_fds=(image, settings), evidence={},
    )
    try:
        with panel_invoker.seat_profile(harness='gemini', executable=admitted.executable,
                                       env={'HOME': str(operator_home)}, cwd=tmp_path,
                                       gemini_profile=admitted) as (_, profile):
            assert '--symlink' not in profile.mount_args
            assert str(original) not in profile.mount_args
            copied = _files(profile)[destination]
            assert b'synthetic-access-token' in copied
            assert b'synthetic-refresh-token' not in copied
            assert admitted.evidence['provider_agy_subscription_reference'] == 'private_access_token_copy'
    finally:
        os.close(image)
        os.close(settings)


def test_codex_caller_redacts_the_returned_and_retained_review(operator_home, tmp_path, monkeypatch):
    from phase_loop_runtime import sandbox_egress

    executable = tmp_path / 'provider-entry'
    executable.write_text('''#!/usr/bin/python3
import json,os,pathlib,sys
if 'login' in sys.argv:
 print('Logged in');sys.exit(0)
state=json.loads((pathlib.Path.home()/'.codex/auth.json').read_text())
token=state['tokens']['access_token']+' '+state['OPENAI_API_KEY']
text='The declared candidate was reviewed successfully. '+token+'\\nAGREE\\n'
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(text)
print(text,flush=True)
''')
    executable.chmod(0o700)
    monkeypatch.setattr(panel_invoker, '_seat_provider_source',
                        lambda *_: ('codex', str(executable)))
    review = tmp_path / 'review'
    output = tmp_path / 'output'
    review.mkdir()
    output.mkdir()
    (review / 'review-bundle.md').write_text('declared review data')
    with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
        try:
            rc, text, detail = panel_invoker._exec_leg(
                'codex', review, output, 30, '', 'review', 'gpt-6.1-sol',
                env={'HOME': str(operator_home), 'PATH': '/usr/bin:/bin'},
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert rc == 0, detail
    for value in (text, detail, (output / 'panel-codex.txt').read_text()):
        assert 'synthetic-access-token' not in value
        assert 'synthetic-codex-api-key' not in value
    assert '[credential redacted]' in text
    assert panel_invoker._SEAT_REDACTIONS.get() == ()


def test_tui_caller_redacts_the_returned_terminal_detail(operator_home, tmp_path, monkeypatch):
    from phase_loop_runtime import sandbox_egress

    executable = tmp_path / 'provider-entry'
    executable.write_text('''#!/usr/bin/python3
import json,os,pathlib,sys
token=os.read(int(os.environ['CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR']),4096).decode()
print('Fixture terminal detail: '+token,flush=True)
sys.exit(1)
''')
    executable.chmod(0o700)
    monkeypatch.setattr(panel_invoker, '_seat_provider_source',
                        lambda *_: ('claude', str(executable)))
    with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
        try:
            rc, text, reason, tail = panel_invoker._run_claude_tui_session(
                command=[str(executable)], cwd=tmp_path, prompt='fixture review',
                output_file=tmp_path / 'answer.txt', timeout_s=15,
                env={'HOME': str(operator_home), 'PATH': '/usr/bin:/bin'},
            )
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert rc != 0
    assert reason in {'claude_tui_pty_eof_no_output', 'claude_tui_missing_canonical_output'}
    assert 'synthetic-access-token' not in text + tail
    assert '[credential redacted]' in tail
    assert panel_invoker._SEAT_REDACTIONS.get() == ()


@pytest.mark.parametrize("directory", ["bin", ".local/bin", ".cargo/bin"])
def test_standalone_codex_profile_mounts_only_executable(operator_home, tmp_path, directory):
    executable = operator_home / directory / "codex"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(Path("/usr/bin/true").read_bytes())
    executable.chmod(0o700)
    with panel_invoker.seat_profile(harness="codex", executable=str(executable),
                                   env={"HOME": str(operator_home)}, cwd=tmp_path) as (command, profile):
        assert command == "/run/phase-loop-seat/provider"
        assert str(executable.parent.parent) not in profile.mount_args
        assert "/run/phase-loop-seat/codex-runtime" not in profile.mount_args


def test_claude_profile_takes_the_single_credential_decision(operator_home, tmp_path, monkeypatch):
    """agent-harness#1253 feeds the owned Claude seat too: the decision's token (here a bound
    override) is what the seat receives; its refusal refuses a review seat, typed, and an
    administrative probe runs without a credential."""
    from phase_loop_runtime import seat_credentials

    seen = []

    def decide(margin_s, *, env=None, **_):
        seen.append(env["HOME"])
        return seat_credentials.SeatCredential(b"bound-override-token", seat_credentials.SOURCE_OVERRIDE)

    monkeypatch.setattr(seat_credentials, "resolve_claude_seat_credential", decide)
    env = {"HOME": str(operator_home), "PATH": "/usr/bin:/bin"}
    with panel_invoker.seat_profile(harness="claude", executable="/usr/bin/true", env=env,
                                   cwd=tmp_path) as (_command, profile):
        descriptor = int(profile.env[seat_jail.CLAUDE_TOKEN_FD_ENV])
        assert os.read(descriptor, 4096) == b"bound-override-token"
    assert seen == [str(operator_home)]

    def refuse(*_args, **_kwargs):
        raise seat_jail.SeatSandboxRefused("claude_seat_token_missing")

    monkeypatch.setattr(seat_credentials, "resolve_claude_seat_credential", refuse)
    with pytest.raises(seat_jail.SeatSandboxRefused, match="claude_seat_token_missing"):
        with panel_invoker.seat_profile(harness="claude", executable="/usr/bin/true", env=env,
                                       cwd=tmp_path):
            pass
    with panel_invoker.seat_profile(harness="claude", executable="/usr/bin/true", env=env,
                                   cwd=tmp_path, role=panel_invoker.SeatLaunchRole.PROVIDER_ADMIN
                                   ) as (_command, profile):
        assert seat_jail.CLAUDE_TOKEN_FD_ENV not in profile.env


def test_the_decision_reads_the_launching_session_s_login(operator_home, monkeypatch):
    from phase_loop_runtime import seat_credentials

    monkeypatch.setenv("XDG_STATE_HOME", str(operator_home / "state"))  # no stored override
    credential = seat_credentials.resolve_claude_seat_credential(
        60, env={"HOME": str(operator_home)})
    assert (credential.token, credential.source) == (b"synthetic-access-token",
                                                     seat_credentials.SOURCE_LOGIN)
