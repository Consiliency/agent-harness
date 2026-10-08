"""Credential refresh is a fixed operator-side administrative operation."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress


def _state(home, expiry):
    path = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"auth_method": "oauth", "token": {
        "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
        "token_type": "Bearer", "expiry": expiry.isoformat()}}))
    return path


class _Image:
    def reopen(self):
        import os
        return os.open("/usr/bin/true", os.O_RDONLY)


def test_near_expiry_refresh_runs_once_with_empty_cwd_and_fixed_argv(tmp_path, monkeypatch):
    token_path = _state(tmp_path, datetime.now(timezone.utc) - timedelta(minutes=1))
    calls = []
    original = subprocess.Popen

    def launch(command, **kwargs):
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()
        calls.append((command, Path(kwargs["cwd"]), kwargs["env"], kwargs.get("process_owner")))
        token_path.write_text(json.dumps({"auth_method": "oauth", "token": {
            "access_token": "synthetic-fresh-access", "refresh_token": "synthetic-refresh",
            "token_type": "Bearer", "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}}))
        assert list(Path(kwargs["cwd"]).iterdir()) == []
        return original(["/bin/true"], **kwargs)

    monkeypatch.setattr(panel_invoker, "launch_provider", launch)
    panel_invoker._refresh_gemini_credential(tmp_path, _Image())
    assert len(calls) == 1
    command, cwd, env, owner = calls[0]
    assert command[0].startswith("/proc/self/fd/") and command[1:] == ["models"]
    assert owner is None
    assert env["HOME"] == str(tmp_path)
    assert not cwd.exists()


def test_failed_refresh_refuses_the_seat(tmp_path, monkeypatch):
    _state(tmp_path, datetime.now(timezone.utc) - timedelta(minutes=1))
    original = subprocess.Popen
    monkeypatch.setattr(panel_invoker, "launch_provider",
                        lambda _argv, **kwargs: original(["/bin/false"], **kwargs))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="gemini_credential_near_expiry"):
        panel_invoker._refresh_gemini_credential(tmp_path, _Image())


def test_fresh_credential_needs_no_provider_process(tmp_path, monkeypatch):
    _state(tmp_path, datetime.now(timezone.utc) + timedelta(hours=1))
    monkeypatch.setattr(panel_invoker, "launch_provider", lambda *a, **k: pytest.fail("unexpected refresh"))
    panel_invoker._refresh_gemini_credential(tmp_path, _Image())


def test_administrative_profile_does_not_request_a_refresh(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    _state(tmp_path, datetime.now(timezone.utc) - timedelta(minutes=1))

    class Image(_Image):
        def close(self):
            pass

    monkeypatch.setattr(agy_integrity, 'check', lambda executable, env=None: Image())
    monkeypatch.setattr(panel_invoker, '_refresh_gemini_credential',
                        lambda *a, **k: pytest.fail('administrative probe requested a refresh'))
    with panel_invoker.seat_profile(
        harness='gemini', executable='/usr/bin/true', env={'HOME': str(tmp_path)},
        cwd=tmp_path, role=panel_invoker.SeatLaunchRole.PROVIDER_ADMIN,
    ) as (_command, profile):
        assert profile.env['HOME'] != str(tmp_path)


def test_refresh_timeout_is_typed_and_reclaims_the_operation(tmp_path, monkeypatch):
    _state(tmp_path, datetime.now(timezone.utc) - timedelta(minutes=1))
    observed = []
    reclaimed = []

    class Process:
        stdout = stderr = None
        returncode = None

        def communicate(self, **kwargs):
            observed.append(kwargs.get('timeout'))
            raise subprocess.TimeoutExpired('fixed administrative operation', 15)

    process = Process()
    monkeypatch.setattr(panel_invoker, 'launch_provider', lambda *a, **k: process)
    monkeypatch.setattr(panel_invoker, '_anchor_process_group', lambda process: None)
    monkeypatch.setattr(panel_invoker, '_terminate_process_group', reclaimed.append)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match='gemini_credential_refresh_timeout'):
        panel_invoker._refresh_gemini_credential(tmp_path, _Image())
    assert observed == [15]
    assert reclaimed == [process]


def test_sibling_profiles_share_one_operator_refresh_and_private_copies(tmp_path, monkeypatch):
    import os
    import threading
    import time
    from phase_loop_runtime import agy_integrity
    from phase_loop_runtime.advisor_board.backing import start_context_carrying_thread

    token_path = _state(tmp_path, datetime.now(timezone.utc) - timedelta(minutes=1))
    sibling = tmp_path / '.gemini/antigravity-cli/sibling-settings'
    sibling.write_bytes(b'synthetic operator settings')
    calls, copies, errors = [], [], []
    entered = threading.Event()
    original = subprocess.Popen

    class Image(_Image):
        def close(self):
            pass

    def launch(command, **kwargs):
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()
        assert kwargs.get('process_owner') is None
        assert command[1:] == ['models'] and list(Path(kwargs['cwd']).iterdir()) == []
        calls.append(command)
        entered.set()
        time.sleep(.2)
        import tempfile
        state = {'auth_method': 'oauth', 'token': {
            'access_token': 'synthetic-new-access', 'refresh_token': 'synthetic-refresh',
            'token_type': 'Bearer', 'expiry': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}}
        with tempfile.NamedTemporaryFile(mode='w', dir=token_path.parent, delete=False) as replacement:
            replacement.write(json.dumps(state))
        Path(replacement.name).replace(token_path)
        return original(['/bin/true'], **kwargs)

    def profile():
        try:
            with panel_invoker.seat_profile(
                harness='gemini', executable='/usr/bin/true', cwd=tmp_path,
                env={'HOME': str(tmp_path)},
            ) as (_command, owned):
                destination = '/home/phase-loop-seat/.gemini/antigravity-cli/antigravity-oauth-token'
                arguments = owned.mount_args
                index = next(index for index, value in enumerate(arguments)
                             if value == '--file' and arguments[index + 2] == destination)
                descriptor = int(arguments[index + 1])
                copies.append(os.pread(descriptor, 4096, 0))
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(agy_integrity, 'check', lambda _path, env=None: Image())
    monkeypatch.setattr(panel_invoker, 'launch_provider', launch)
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(('synthetic sibling context',))
    try:
        first = start_context_carrying_thread(profile, daemon=True)
        assert entered.wait(5)
        second = start_context_carrying_thread(profile, daemon=True)
        first.join(timeout=10)
        second.join(timeout=10)
        assert not first.is_alive() and not second.is_alive()
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ('synthetic sibling context',)
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert not errors, errors
    assert len(calls) == 1
    assert len(copies) == 2
    assert all(b'synthetic-new-access' in state and b'synthetic-refresh' not in state
               for state in copies)
    assert sibling.read_bytes() == b'synthetic operator settings'


def test_missing_review_credential_refuses_before_refresh_or_image_lookup(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    monkeypatch.setattr(agy_integrity, 'check', lambda *_: pytest.fail('missing credential reached image lookup'))
    monkeypatch.setattr(panel_invoker, 'launch_provider', lambda *_a, **_k: pytest.fail('missing credential launched'))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match='seat_profile'):
        with panel_invoker.seat_profile(
            harness='gemini', executable='/usr/bin/true', cwd=tmp_path,
            env={'HOME': str(tmp_path)},
        ):
            pytest.fail('missing credential was admitted')
