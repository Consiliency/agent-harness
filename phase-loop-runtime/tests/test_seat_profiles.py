"""Private per-launch subscription profiles contain only declared state."""

import json
import hashlib
import os
from pathlib import Path
import sys

import pytest

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
    (home / ".codex/auth.json").write_text('{"tokens":{"access_token":"synthetic-access-token","refresh_token":"synthetic-refresh-token"}}')
    (home / ".claude/.credentials.json").write_text('{"claudeAiOauth":{"accessToken":"synthetic-access-token","refreshToken":"synthetic-refresh-token","expiresAt":9999999999999}}')
    (home / ".grok/auth.json").write_text('{"token":"synthetic-grok-token"}')
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
        if harness == "codex":
            config = next(data for path, data in files.items() if path.endswith("config.toml"))
            assert b'cli_auth_credentials_store = "file"' in config
            assert not profile.env["HOME"].startswith(("/dev/", "/tmp/"))
        if harness in ("claude", "gemini"):
            credential = next(data for path, data in files.items()
                              if path.endswith((".credentials.json", "antigravity-oauth-token")))
            assert b"synthetic-access-token" in credential
            assert b"synthetic-refresh-token" not in credential
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
token=state['tokens']['access_token']
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
    assert '[credential redacted]' in text
    assert panel_invoker._SEAT_REDACTIONS.get() == ()


def test_tui_caller_redacts_the_returned_terminal_detail(operator_home, tmp_path, monkeypatch):
    from phase_loop_runtime import sandbox_egress

    executable = tmp_path / 'provider-entry'
    executable.write_text('''#!/usr/bin/python3
import json,os,pathlib,sys
state=json.loads((pathlib.Path(os.environ['CLAUDE_CONFIG_DIR'])/'.credentials.json').read_text())
token=state['claudeAiOauth']['accessToken']
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
