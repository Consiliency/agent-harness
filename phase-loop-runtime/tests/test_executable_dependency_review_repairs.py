"""Offline boundary regressions for declared dependency launch compositions."""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
import signal
from types import SimpleNamespace

import pytest
import rfc8785

from executable_dependency_test_support import build_fixture, file_identity, sha256
from test_executable_dependency_startup import runtime_package
from phase_loop_runtime import executable_dependency_startup as startup
from phase_loop_runtime import gemini_heartbeat, launcher, panel_invoker as panel, seat_jail
from phase_loop_runtime.executable_dependency import (
    ExecutableDependencyError, ProjectionPolicy, admit_executable_dependency,
)


def _admit(fixture, **kwargs):
    return admit_executable_dependency(
        fixture.requirement, fixture.authority_fd,
        fixture.requirement.expected_authority_sha256, **kwargs,
    )


@contextmanager
def _managed(monkeypatch, fixture):
    monkeypatch.setattr(startup, '_validate_runtime_package', lambda _: None)
    session = startup.open_dependency_startup(startup.DependencyStartupSpec(
        fixture.requirement, fixture.authority_fd,
        fixture.requirement.expected_authority_sha256, runtime_package(),
    ))
    task = session.acquire_task('offline-review')
    try:
        with task.bind_current():
            yield session
    finally:
        task.release()
        session.close()


def _fds():
    result = set()
    for value in os.listdir('/proc/self/fd'):
        try:
            os.fstat(int(value))
        except OSError:
            continue
        result.add(int(value))
    return result


def _unreached(*args, **kwargs):
    pytest.fail('effect boundary reached')


def _jail_fixture(tmp_path, provider):
    fixture = build_fixture(tmp_path / 'fixture', provider=provider)
    fixture.declaration['entries'][-1]['destination'] = '/usr/lib/helper'
    fixture.declaration['entries'][1]['destination'] = '/usr/lib'
    unsigned = dict(fixture.declaration)
    unsigned.pop('declaration_id')
    fixture.declaration['declaration_id'] = sha256(rfc8785.dumps(unsigned))
    fixture.declaration_path.write_bytes(rfc8785.dumps(fixture.declaration))
    fixture.authority['declaration'] = file_identity(fixture.declaration_path)
    fixture.authority['destination_policy']['allowed_roots'].append('/usr')
    unsigned = dict(fixture.authority)
    unsigned.pop('authority_id')
    fixture.authority['authority_id'] = sha256(rfc8785.dumps(unsigned))
    fixture.authority_path.write_bytes(rfc8785.dumps(fixture.authority))
    fixture.requirement = replace(
        fixture.requirement, authority_id=fixture.authority['authority_id'],
        expected_authority_sha256=sha256(fixture.authority_path.read_bytes()),
    )
    return fixture


@pytest.mark.parametrize('provider', ['claude', 'gemini'])
def test_jail_floor_precedes_all_preparation_effects(tmp_path, monkeypatch, provider):
    fixture = _jail_fixture(tmp_path, provider)
    try:
        with _managed(monkeypatch, fixture):
            monkeypatch.setattr(panel._seat_credentials, 'resolve_claude_seat_credential', _unreached)
            for name in ('_refresh_gemini_credential', '_await_gemini_login', '_write_gemini_config', '_gemini_credential_fresh'):
                monkeypatch.setattr(panel, name, _unreached)
            monkeypatch.setattr(seat_jail, 'build_gemini_seat_copy', _unreached)
            monkeypatch.setattr(seat_jail, 'token_pipe', _unreached)
            seat_dir = tmp_path / 'seat'
            args = (tmp_path / 'review', seat_dir, None, 1, os.getpid(), ('bundle', 'brief'))
            with pytest.raises(seat_jail.SeatSandboxRefused, match='dependency destination overlaps'):
                if provider == 'claude':
                    panel._prepare_jailed_claude(*args)
                else:
                    panel._prepare_jailed_gemini(*args, SimpleNamespace())
            assert not seat_dir.exists()
    finally:
        fixture.close()


@pytest.mark.parametrize('route,action', [
    ('claude_channel', 'execute'), ('claude_agent_view', 'execute'), (None, 'execute'),
    ('claude_channel', 'review'), ('claude_agent_view', 'review'),
])
def test_required_executor_transports_refuse_before_staging(tmp_path, monkeypatch, route, action):
    fixture = build_fixture(tmp_path / 'fixture', provider='claude')
    try:
        with _managed(monkeypatch, fixture):
            for name in ('_launch_claude_channel', '_launch_claude_agent_view', '_resolve_command_context'):
                monkeypatch.setattr(launcher, name, _unreached)
            monkeypatch.setattr(panel.subprocess, 'Popen', _unreached)
            spec = SimpleNamespace(
                executor='claude', command=[str(fixture.subject), '--original'],
                prompt_bundle=SimpleNamespace(product_action=action), claude_route=route,
            )
            with pytest.raises(ExecutableDependencyError, match='dependency_route_unwired'):
                launcher.launch_with_spec(spec, log_path=tmp_path / 'output/log')
            assert not (tmp_path / 'output').exists()
    finally:
        fixture.close()


def test_direct_launch_and_maintenance_refuse_before_lookup_or_outputs(tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / 'fixture', provider='codex')
    try:
        with _managed(monkeypatch, fixture) as session:
            monkeypatch.setattr('phase_loop_runtime.agy_integrity.trusted_command', _unreached)
            monkeypatch.setattr(launcher, '_worktree_change_snapshot', _unreached)
            monkeypatch.setattr(panel.subprocess, 'Popen', _unreached)
            monkeypatch.setattr('phase_loop_runtime.cli.main', _unreached)
            with pytest.raises(ExecutableDependencyError, match='dependency_route_unwired'):
                session.run_cli(['maintain-skills'])
            with pytest.raises(ExecutableDependencyError, match='dependency_route_unwired'):
                launcher.launch(['codex', 'exec', 'synthetic'], log_path=tmp_path / 'out/log')
            with pytest.raises(ExecutableDependencyError, match='dependency_route_unwired'):
                panel.launch_owned([str(fixture.subject)], role=panel.SeatLaunchRole.EXECUTOR_TRUSTED,
                                   profile=panel.SeatProfile(env={}))
            assert not (tmp_path / 'out').exists()
    finally:
        fixture.close()


def test_president_heartbeat_refuses_before_capability_and_launch(tmp_path, monkeypatch):
    import threading
    from phase_loop_runtime import president_adapter
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    fixture = build_fixture(tmp_path / 'fixture', provider='gemini')
    try:
        with _managed(monkeypatch, fixture):
            monkeypatch.setattr(gemini_heartbeat, 'require_capability', _unreached)
            monkeypatch.setattr(gemini_heartbeat, 'owned_profile', _unreached)
            monkeypatch.setattr(panel, '_run_leg_with_liveness', _unreached)
            monkeypatch.setattr(panel.subprocess, 'Popen', _unreached)
            seam = president_adapter.build_president_invoke(DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={})
            monitor = panel._ReviewMonitor(tmp_path / 'm.json', 't', 0, threading.Event())
            with pytest.raises(ExecutableDependencyError, match='Gemini heartbeat'):
                seam._launch_gemini('gemini-model', 'F001: [x] y', tmp_path / 'out', monitor=monitor)
            assert not (tmp_path / 'out').exists()
    finally:
        fixture.close()


def test_heartbeat_composition_refuses_before_admission_credentials_and_outputs(tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / 'fixture', provider='gemini')
    try:
        with _managed(monkeypatch, fixture) as session:
            monkeypatch.setattr(gemini_heartbeat, '_local_capabilities', _unreached)
            monkeypatch.setattr(gemini_heartbeat, '_read_image', _unreached)
            monkeypatch.setattr(panel, '_seat_credential', _unreached)
            monkeypatch.setattr(panel, '_precreate_seat_output', _unreached)
            monkeypatch.setattr(panel.subprocess, 'Popen', _unreached)
            from phase_loop_runtime import agy_qualification
            monkeypatch.setattr(agy_qualification, 'ensure_admitted', _unreached)
            board = SimpleNamespace(seats=(SimpleNamespace(harness='gemini'),))
            with pytest.raises(ExecutableDependencyError, match='Gemini heartbeat'):
                panel._preflight_gemini_heartbeat(board, 'heartbeat_only', env={})
            with pytest.raises(ExecutableDependencyError, match='Gemini heartbeat'):
                with panel.seat_profile(harness='gemini', executable=str(fixture.subject), env={},
                                        cwd=tmp_path, dependency=session.dependency,
                                        gemini_profile=SimpleNamespace()):
                    pytest.fail('profile entered')
            with pytest.raises(ExecutableDependencyError, match='Gemini heartbeat'):
                with panel._seat_command_profile(
                    ['/heartbeat/agy'], env={}, cwd=tmp_path, gemini_profile=SimpleNamespace(executable='/heartbeat/agy'),
                    outputs=(tmp_path / 'out',),
                ):
                    pytest.fail('profile entered')
            assert not (tmp_path / 'out').exists()
    finally:
        fixture.close()


@pytest.mark.parametrize('route', ['profile', 'jail'])
def test_required_gemini_stale_login_refuses_host_refresh(tmp_path, monkeypatch, route):
    fixture = build_fixture(tmp_path / 'fixture', provider='gemini')
    try:
        with _managed(monkeypatch, fixture):
            monkeypatch.setattr(panel, '_gemini_credential_fresh', lambda _: False)
            for name in ('_refresh_gemini_credential', '_await_gemini_login', '_precreate_seat_output', '_write_gemini_config'):
                monkeypatch.setattr(panel, name, _unreached)
            monkeypatch.setattr(panel, '_seat_credential', _unreached)
            monkeypatch.setattr(panel.subprocess, 'Popen', _unreached)
            with pytest.raises(ExecutableDependencyError, match='Gemini host credential refresh'):
                if route == 'profile':
                    with panel._seat_command_profile([str(fixture.subject)], env={}, cwd=tmp_path,
                                                     outputs=(tmp_path / 'out',)):
                        pytest.fail('profile entered')
                else:
                    panel._prepare_jailed_gemini(tmp_path / 'review', tmp_path / 'seat', None,
                                                1, os.getpid(), ('bundle', 'brief'), SimpleNamespace())
            assert not (tmp_path / 'seat').exists()
            assert not (tmp_path / 'out').exists()
    finally:
        fixture.close()


def test_required_gemini_review_launch_refuses_short_login_without_waiting(tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / 'fixture', provider='gemini')
    try:
        with _managed(monkeypatch, fixture):
            monkeypatch.setattr(panel, '_gemini_login_left_s', lambda _home: 300.0)
            monkeypatch.setattr(panel, '_gemini_credential_fresh', lambda _home: False)
            # Reaching the wait's notice/sleep, network isolation or a spawn is a failure.
            monkeypatch.setattr(panel, '_BOARD_CANCEL', SimpleNamespace(get=_unreached))
            monkeypatch.setattr('phase_loop_runtime.sandbox_egress.isolated_network', _unreached)
            monkeypatch.setattr(panel.subprocess, 'Popen', _unreached)
            with pytest.raises(ExecutableDependencyError, match='Gemini host credential refresh'):
                launcher.launch(['agy', '--original'], log_path=tmp_path / 'out/log',
                                env={'HOME': str(tmp_path)}, cwd=tmp_path, action='review')
            assert not (tmp_path / 'out').exists()
    finally:
        fixture.close()


def _synthetic_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(panel._seat_credentials, 'resolve_claude_seat_credential', lambda *a, **k: SimpleNamespace(
        token=b'synthetic', source='synthetic', expires_at=None, notices=(),
    ))
    monkeypatch.setattr(panel, '_gemini_credential_fresh', lambda _: True)
    document = {'token': {'access_token': 'synthetic', 'expiry': '2099-01-01T00:00:00.000Z'}}
    monkeypatch.setattr(seat_jail, 'build_gemini_seat_copy', lambda _: json.dumps(document).encode())
    ca = tmp_path / 'ca.pem'
    ca.write_bytes(b'synthetic CA')
    return SimpleNamespace(ca_cert=ca, proxy_url='http://127.0.0.1:1')


@pytest.mark.parametrize('provider', ['claude', 'gemini'])
def test_second_jail_revalidation_failure_closes_all_inputs(tmp_path, monkeypatch, provider):
    fixture = build_fixture(tmp_path / 'fixture', provider=provider)
    try:
        with _managed(monkeypatch, fixture):
            egress = _synthetic_credentials(monkeypatch, tmp_path)
            review = tmp_path / 'review'
            tree = review / seat_jail.HOST_TREE_DIRNAME
            tree.mkdir(parents=True)
            tree_fd = seat_jail.open_dir_nofollow(tree)
            try:
                authorization = SimpleNamespace(staged_tree_sha256=seat_jail.tree_manifest_sha256_at(tree_fd))
            finally:
                os.close(tree_fd)
            original = seat_jail.build_seat_jail
            built = []

            def build(*args, **kwargs):
                jail = original(*args, **kwargs)
                built.append(jail)
                fixture.helper.write_bytes(b'changed')
                return jail

            monkeypatch.setattr(seat_jail, 'build_seat_jail', build)
            before = _fds()
            args = (review, tmp_path / 'seat', authorization, 1, os.getpid(), ('bundle', 'brief'))
            with pytest.raises(ExecutableDependencyError, match='source_changed'):
                if provider == 'claude':
                    panel._prepare_jailed_claude(*args)
                else:
                    panel._prepare_jailed_gemini(*args, egress)
            assert len(built) == 1
            assert not (tmp_path / 'seat').exists()
            assert _fds() == before
    finally:
        fixture.close()


@pytest.mark.parametrize('failure', ['missing-tree', 'input-allocation'])
def test_partial_jail_construction_returns_descriptors_to_baseline(tmp_path, monkeypatch, failure):
    fixture = build_fixture(tmp_path / 'fixture', provider='claude')
    dependency = _admit(fixture)
    try:
        original = seat_jail.memfd_with
        calls = []

        def allocate(*args):
            calls.append(args)
            if failure == 'input-allocation' and len(calls) == 2:
                raise OSError('synthetic allocation refusal')
            return original(*args)

        monkeypatch.setattr(seat_jail, 'memfd_with', allocate)
        before = _fds()
        with pytest.raises((seat_jail.SeatSandboxRefused, OSError), match='staged tree missing|synthetic allocation refusal'):
            panel._build_jail_with_owned_inputs(
                'claude', tmp_path / 'missing', fixture.subject,
                artifact=b'bundle', instructions=b'brief', token=b'token', dependency=dependency,
            )
        assert _fds() == before
    finally:
        dependency.close()
        fixture.close()


def test_generic_named_wrapper_probe_and_production_share_view(tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / 'fixture', provider='claude')
    try:
        with _managed(monkeypatch, fixture) as session:
            _synthetic_credentials(monkeypatch, tmp_path)
            monkeypatch.setattr(panel, '_seat_provider_source', _unreached)
            monkeypatch.setattr(panel, '_filtered_holder_namespace', lambda: None)
            monkeypatch.setattr(panel, '_seat_owner', lambda view, **kwargs: tuple(view))
            monkeypatch.setattr(panel, '_compose_launch_prefix', lambda cwd, owner, *a: tuple(owner))
            monkeypatch.setattr(panel, '_probes_seat', lambda *a: True)
            captured = []
            original_view = panel._seat_filesystem_view

            def view(*args, **kwargs):
                result = original_view(*args, **kwargs)
                captured.append((tuple(result), kwargs))
                return result

            monkeypatch.setattr(panel, '_seat_filesystem_view', view)
            expected = {str(fixture.subject_destination): fixture.subject.read_bytes(),
                        str(fixture.helper_destination): fixture.helper.read_bytes()}
            prod_fds = {}

            def projected(args):
                return {args[i + 2]: int(args[i + 1]) for i, word in enumerate(args) if word == '--ro-bind-data'
                        and args[i + 2] in expected}

            def probe_run(argv, **kwargs):
                fds = projected(argv)
                assert fds.keys() == expected.keys()
                assert set(fds.values()).isdisjoint(prod_fds.values())
                assert set(fds.values()) <= set(kwargs['pass_fds'])
                for dest, fd in fds.items():
                    assert os.read(fd, 1024) == expected[dest]
                return SimpleNamespace(stdout='synthetic-identity\n')

            monkeypatch.setattr(panel.subprocess, 'run', probe_run)
            monkeypatch.setattr(panel, '_expected_seat_identity', lambda *a: ['synthetic-identity'])
            monkeypatch.setattr(panel, '_count_provider_spawn', lambda: None)

            def spawn(argv, **kwargs):
                assert projected(argv) == prod_fds
                for dest, fd in prod_fds.items():
                    assert os.read(fd, 1024) == expected[dest]
                assert fixture.authority_fd not in kwargs['pass_fds']
                return SimpleNamespace()

            monkeypatch.setattr(panel.subprocess, 'Popen', spawn)
            before = _fds()
            with panel._seat_command_profile([str(fixture.subject), '--original'], env={}, cwd=tmp_path) as (command, profile):
                assert command == [str(fixture.subject_destination), '--original']
                assert profile.dependency is session.dependency
                assert profile.dependency_projection_digest == session.dependency.projection_digest
                prod_fds.update(projected(profile.mount_args))
                panel.launch_owned(command, role=panel.SeatLaunchRole.PROVIDER_ADMIN,
                                   profile=profile, cwd=tmp_path)
            assert _fds() == before
            assert len(captured) == 2
            assert captured[0][1]['outputs'] == captured[1][1]['outputs']
            assert captured[0][1]['writable_trees'] == captured[1][1]['writable_trees']
    finally:
        fixture.close()


@pytest.mark.parametrize('limit_delta', [0, -1])
def test_unique_file_sum_is_the_aggregate_boundary(tmp_path, limit_delta):
    fixture = build_fixture(tmp_path / 'fixture')
    try:
        total = fixture.subject.stat().st_size + fixture.helper.stat().st_size
        policy = ProjectionPolicy(aggregate_file_bytes=total+limit_delta)
        if limit_delta == 0:
            dependency = _admit(fixture, host_policy=policy)
            dependency.close()
        else:
            with pytest.raises(ExecutableDependencyError, match='aggregate size'):
                _admit(fixture, host_policy=policy)
    finally:
        fixture.close()


@pytest.mark.parametrize('location', ['subject', 'helper'])
def test_only_intermediate_source_directory_writable_is_refused(tmp_path, location):
    fixture = build_fixture(tmp_path / 'fixture')
    try:
        getattr(fixture, location).parent.chmod(0o777)
        before = _fds()
        with pytest.raises(ExecutableDependencyError, match='source ancestry'):
            _admit(fixture)
        assert _fds() == before
    finally:
        fixture.close()


def test_intermediate_mode_change_is_revalidated(tmp_path):
    fixture = build_fixture(tmp_path / 'fixture')
    dependency = _admit(fixture)
    try:
        fixture.helper.parent.chmod(0o777)
        with pytest.raises(ExecutableDependencyError, match='source_changed: source ancestry'):
            dependency.reopen_projection()
    finally:
        dependency.close()
        fixture.close()


@pytest.mark.parametrize('location', ['declaration_path', 'helper', 'subject'])
def test_fifo_refuses_without_waiting_for_a_writer(tmp_path, location):
    fixture = build_fixture(tmp_path / 'fixture')
    path = getattr(fixture, location)
    path.unlink()
    os.mkfifo(path, 0o644)
    previous = signal.signal(signal.SIGALRM, lambda *a: pytest.fail('FIFO open blocked'))
    signal.alarm(3)
    try:
        before = _fds()
        with pytest.raises(ExecutableDependencyError):
            _admit(fixture)
        assert _fds() == before
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        fixture.close()


def test_authority_requires_read_only_descriptor(tmp_path):
    fixture = build_fixture(tmp_path / 'fixture')
    os.close(fixture.authority_fd)
    fixture.authority_fd = os.open(fixture.authority_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        with pytest.raises(ExecutableDependencyError, match='authority descriptor must be read-only'):
            _admit(fixture)
    finally:
        fixture.close()


def test_deep_authority_has_stable_refusal(tmp_path):
    raw = b'{"nested":' + b'[' * 10000 + b'0' + b']' * 10000 + b'}'
    fixture = build_fixture(tmp_path / 'fixture', authority_transform=lambda _: raw)
    try:
        with pytest.raises(ExecutableDependencyError, match='authority_invalid'):
            _admit(fixture)
    finally:
        fixture.close()
