"""Real cleanup failures and retained proof outcomes for agent-harness#858."""

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import pytest

from phase_loop_runtime import verification_evidence as ve


TARGET = 'phase-loop-runtime/src/phase_loop_runtime/cleanup_fixture.py'
SCRIPT = '''from pathlib import Path
import sys
MUTATED = False
mode, behavior = sys.argv[1:]
if MUTATED or behavior == 'baseline_failed':
    generated = Path('generated')
    generated.mkdir()
    (generated / 'retained.txt').write_text('owned synthetic proof evidence\\n')
    generated.chmod(int(mode, 8))
    print('mutant_killed cleanup_observable', flush=True)
    raise SystemExit(0 if behavior == 'survived' else 1)
print('baseline passed', flush=True)
'''


def _bytes(value):
    return value.encode() if isinstance(value, str) else value or b''


def _blob(raw):
    return {'sha256': sha256(raw).hexdigest(), 'base64': base64.b64encode(raw).decode()}


@pytest.fixture
def proof(tmp_path, monkeypatch, record_property):
    workspace = Path('/mnt/workspace/worktrees')
    root = Path(tempfile.mkdtemp(prefix='agent-harness-858-',
                                 dir=workspace if workspace.is_dir() else None))
    repo = root / 'repo'
    repo.mkdir()
    evidence = root / 'evidence'
    evidence.mkdir()
    foreign = root / 'foreign.txt'
    foreign.write_text('unrelated fixture sentinel\n')
    target = repo / TARGET
    target.parent.mkdir(parents=True)
    target.write_text(SCRIPT)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo, stderr=subprocess.STDOUT)
    git('init', '-b', 'fixture')
    git('config', 'user.name', 'PROOFGATE fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    git('add', '--', TARGET)
    git('-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
        'commit', '-m', 'test fixture: cleanup behavior')
    candidate = git('rev-parse', 'HEAD').decode().strip()
    git('bundle', 'create', str(evidence / 'fixture.bundle'), 'HEAD')
    state = SimpleNamespace(root=root, repo=repo, evidence=evidence, candidate=candidate,
                            calls=[], allocated=[], residue=[], results=[], fault=None,
                            cleanup_fault=None, proof_calls=0, initial_removals=[])
    real_run = subprocess.run
    real_rmtree = ve.shutil.rmtree

    def remove_initial_empty(path, *args, **kwargs):
        path = Path(path)
        assert path.parent == (workspace if workspace.is_dir() else repo.parent)
        assert path.name.startswith('proofgate-mutation-') and not list(path.iterdir())
        state.initial_removals.append(str(path))
        return real_rmtree(path, *args, **kwargs)

    def no_permission_repair(*args, **kwargs):
        raise AssertionError('executor attempted permission repair')

    def run(argv, *args, **kwargs):
        argv = list(argv)
        row = {'argv': argv}
        state.calls.append(row)
        cleanup = argv[:3] == ['git', 'worktree', 'remove']
        if argv[:3] == ['git', 'worktree', 'add']:
            path = Path(argv[-2])
            state.allocated.append(path)
            assert str(path) in state.initial_removals
            if state.fault in ('add', 'partial_add'):
                if state.fault == 'partial_add':
                    path.mkdir()
                    (path / 'partial-setup.txt').write_text('partial setup evidence\n')
                row['exception'] = 'OSError'
                raise OSError('original worktree add failure')
        if cleanup:
            path = Path(argv[-1])
            assert path in state.allocated
            retained = {'path': str(path), 'exists_before': path.exists(), 'files': []}
            if path.exists():
                for p in sorted(path.rglob('*')):
                    if p.is_file() and not p.is_symlink():
                        retained['files'].append({'path': str(p.relative_to(path)),
                            'mode': p.stat().st_mode, **_blob(p.read_bytes())})
            state.residue.append(retained)
            if state.cleanup_fault == 'oserror':
                row['exception'] = 'OSError'
                raise OSError('secondary cleanup unavailable')
            if state.cleanup_fault == 'nonzero':
                completed = subprocess.CompletedProcess(argv, 37, b'cleanup\xff', b'failed\xfe')
            else:
                completed = real_run(argv, *args, **kwargs)
        else:
            if len(argv) > 1 and argv[1] == TARGET:
                state.proof_calls += 1
                if state.proof_calls == 2 and state.fault in ('execute', 'interrupt'):
                    row['exception'] = 'OSError' if state.fault == 'execute' else 'KeyboardInterrupt'
                    if state.fault == 'interrupt':
                        raise KeyboardInterrupt('original proof interruption')
                    raise OSError('original proof execution failure')
            completed = real_run(argv, *args, **kwargs)
        row.update(returncode=completed.returncode, stdout=_blob(_bytes(completed.stdout)),
                   stderr=_blob(_bytes(completed.stderr)))
        return completed

    monkeypatch.chdir(repo)
    monkeypatch.setattr(ve.subprocess, 'run', run)
    monkeypatch.setattr(ve.shutil, 'rmtree', remove_initial_empty)
    monkeypatch.setattr(ve.os, 'chmod', no_permission_repair)
    try:
        yield state
    finally:
        assert foreign.read_text() == 'unrelated fixture sentinel\n'
        cleanup_calls = [c for c in state.calls if c['argv'][:3] == ['git', 'worktree', 'remove']]
        assert [c['argv'][-1] for c in cleanup_calls] == [str(p) for p in state.allocated]
        assert all(c['argv'][:3] != ['git', 'worktree', 'prune'] for c in state.calls)
        report = {'uid': os.getuid(), 'euid': os.geteuid(), 'root': str(root),
                  'synthetic_fixture_only': True, 'candidate': candidate,
                  'bundle': _blob((evidence / 'fixture.bundle').read_bytes()),
                  'calls': state.calls, 'results': state.results, 'residue_before_cleanup': state.residue,
                  'allocated': [{'path': str(p), 'exists_after': p.exists()} for p in state.allocated],
                  'foreign_unchanged': True, 'fixture_retirement_performed': False}
        raw = json.dumps(report, sort_keys=True)
        (evidence / 'custody.json').write_text(raw + '\n')
        assert json.loads((evidence / 'custody.json').read_text()) == report
        (tmp_path / 'proofgate-cleanup-custody.json').write_text(raw + '\n')
        record_property('proofgate_cleanup_custody', raw)


def _parameter(identifier='one', mode='0700', behavior='killed'):
    return {'parameter_id': identifier, 'target_path': TARGET,
            'injection_anchor': 'MUTATED = False', 'replacement_bytes': 'MUTATED = True',
            'proof_command': ['python', TARGET, mode, behavior],
            'target_nodeid': 'synthetic-proof',
            'expected_observable': {'result_code': 'mutant_killed', 'rule_id': 'cleanup_observable'}}


def _execute(proof, parameters=None, *, aggregate=False):
    parameters = parameters or [_parameter()]
    manifest = proof.evidence / 'manifest.json'
    manifest.write_text(json.dumps({'declarations': [{'parameters': parameters}]}))
    try:
        result = ve.execute_proofgate_mutation_manifest(
            manifest, proof.candidate, parameter_id=None if aggregate else parameters[0]['parameter_id'])
    except BaseException as exc:
        proof.results.append({'uncaught_exception': type(exc).__name__, 'message': str(exc)})
        raise
    proof.results.append(result)
    return result


def _cleanup(proof, result, *, add_completed=True, actual_permission=False):
    calls = [c for c in proof.calls if c['argv'][:3] == ['git', 'worktree', 'remove']]
    assert len(calls) == 1
    path = proof.allocated[0]
    cleanup = result['cleanup']
    assert cleanup['worktree'] == str(path)
    assert cleanup['add_completed'] is add_completed
    assert cleanup['path_exists_after_cleanup'] is path.exists()
    if proof.cleanup_fault == 'oserror':
        assert cleanup['returncode'] is None and cleanup['exception_type'] == 'OSError'
    else:
        assert cleanup['returncode'] == calls[0]['returncode'] != 0
        assert cleanup['exception_type'] is None
        for key in ('stdout', 'stderr'):
            original = base64.b64decode(calls[0][key]['base64'])
            assert cleanup[key] == original.decode('utf-8', errors='replace')
    if actual_permission:
        assert path.exists() and (path / 'generated/retained.txt').is_file()
        assert 'Permission denied' in cleanup['stderr']
        assert 'exception' not in calls[0]
    assert isinstance(cleanup['stdout'], str) and isinstance(cleanup['stderr'], str)
    json.dumps(result)


@pytest.mark.parametrize('behavior', ['killed', 'survived', 'baseline_failed'])
def test_successful_cleanup_preserves_original_result(proof, behavior):
    result = _execute(proof, [_parameter(behavior=behavior)])
    assert result['status'] == behavior
    expected = {'status', 'baseline_status', 'applied_replacements', 'bindings'}
    if behavior == 'baseline_failed':
        expected.add('diagnostic')
        assert result['applied_replacements'] == 0 and 'mutant_killed' in result['diagnostic']
    else:
        assert result['applied_replacements'] == 1 and proof.proof_calls == 2
    assert set(result) == expected
    assert not proof.allocated[0].exists()
    assert proof.calls[-1]['returncode'] == 0


@pytest.mark.parametrize('behavior', ['killed', 'baseline_failed'])
def test_real_permission_failure_preserves_proof_and_residue(proof, behavior):
    assert os.getuid() == os.geteuid() != 0, 'ordinary-user acceptance prerequisite'
    result = _execute(proof, [_parameter(mode='0500', behavior=behavior)])
    assert result['status'] == 'execution_failure'
    assert result['reason'] == 'worktree_cleanup_failed'
    original = result['proof_result']
    assert original['status'] == behavior
    assert result['bindings'] == original['bindings']
    assert result['applied_replacements'] == original['applied_replacements'] == (behavior == 'killed')
    if behavior == 'baseline_failed':
        assert 'mutant_killed' in original['diagnostic']
    else:
        assert proof.proof_calls == 2
        snapshot = next(p for p in proof.residue[0]['files'] if p['path'] == TARGET)
        assert b'MUTATED = True' in base64.b64decode(snapshot['base64'])
    _cleanup(proof, result, actual_permission=True)


@pytest.mark.parametrize('cleanup_fault', ['nonzero', 'oserror'])
def test_execution_failure_survives_secondary_cleanup_error(proof, cleanup_fault):
    proof.fault = 'execute'
    proof.cleanup_fault = cleanup_fault
    result = _execute(proof)
    assert result['status'] == 'execution_failure' and result['reason'] == 'worktree_cleanup_failed'
    assert result['proof_result'] == {'status': 'execution_failure',
        'reason': 'original proof execution failure', 'applied_replacements': 0}
    assert result['applied_replacements'] == 0 and 'bindings' not in result
    _cleanup(proof, result)


def test_cleanup_oserror_retains_completed_proof(proof):
    proof.cleanup_fault = 'oserror'
    result = _execute(proof)
    assert result['reason'] == 'worktree_cleanup_failed'
    assert result['proof_result']['status'] == 'killed'
    assert result['bindings'] == result['proof_result']['bindings']
    assert result['applied_replacements'] == 1
    _cleanup(proof, result)


@pytest.mark.parametrize('cleanup_fault', [None, 'nonzero', 'oserror'])
@pytest.mark.parametrize('add_fault', ['add', 'partial_add'])
def test_failed_add_keeps_original_setup_failure(proof, cleanup_fault, add_fault):
    proof.fault = add_fault
    proof.cleanup_fault = cleanup_fault
    result = _execute(proof)
    assert result['status'] == 'execution_failure'
    assert result['reason'] == 'original worktree add failure'
    assert result['applied_replacements'] == 0 and 'proof_result' not in result
    assert proof.proof_calls == 0
    _cleanup(proof, result, add_completed=False)


@pytest.mark.parametrize('cleanup_fault', [None, 'nonzero', 'oserror'])
def test_uncaught_interrupt_survives_cleanup(proof, cleanup_fault):
    proof.fault = 'interrupt'
    proof.cleanup_fault = cleanup_fault
    with pytest.raises(KeyboardInterrupt, match='original proof interruption'):
        _execute(proof)
    assert len([c for c in proof.calls if c['argv'][:3] == ['git', 'worktree', 'remove']]) == 1


def test_aggregate_blocks_cleanup_failure_despite_killed_proof(proof):
    assert os.getuid() == os.geteuid() != 0, 'ordinary-user acceptance prerequisite'
    result = _execute(proof, [_parameter('bad', mode='0500'), _parameter('good')], aggregate=True)
    assert result['status'] == 'blocked'
    assert (result['parameters_count'], result['killed_count'], result['survived_count'], result['block_count']) == (2, 1, 0, 1)
    assert result['classifications'] == {'bad': 'execution_failure', 'good': 'killed'}
    assert set(result['cleanup_failures']) == {'bad'}
    failed = result['cleanup_failures']['bad']
    assert failed['proof_result']['status'] == 'killed'
    assert failed['bindings'] == result['bindings']['bad']
    assert failed['cleanup']['returncode'] != 0


def test_aggregate_preserves_normal_shape(proof):
    result = _execute(proof, [_parameter('one'), _parameter('two')], aggregate=True)
    assert result['status'] == 'killed' and result['killed_count'] == 2
    assert set(result) == {'parameters_count', 'killed_count', 'survived_count',
                           'block_count', 'status', 'classifications', 'bindings'}
    assert not any(p.exists() for p in proof.allocated)


def test_aggregate_reports_secondary_setup_cleanup_failure(proof):
    proof.fault = 'add'
    proof.cleanup_fault = 'oserror'
    result = _execute(proof, aggregate=True)
    assert result['status'] == 'blocked' and result['block_count'] == 1
    failed = result['cleanup_failures']['one']
    assert failed['reason'] == 'original worktree add failure'
    assert failed['cleanup']['add_completed'] is False
    assert failed['cleanup']['exception_type'] == 'OSError'


@pytest.fixture
def failed_observation(proof, monkeypatch, record_property):
    state = SimpleNamespace(armed=False, error=PermissionError, calls=[])
    real_run = ve.subprocess.run
    real_stat = os.stat

    def run(argv, *args, **kwargs):
        try:
            return real_run(argv, *args, **kwargs)
        finally:
            if list(argv)[:3] == ['git', 'worktree', 'remove']:
                state.armed = True

    def stat(path, *args, **kwargs):
        if state.armed and isinstance(path, (str, os.PathLike)) and Path(path) in proof.allocated:
            state.armed = False
            state.calls.append(str(path))
            raise state.error(13 if state.error is PermissionError else 5,
                              'residue observation unavailable', str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(ve.subprocess, 'run', run)
    monkeypatch.setattr(ve.os, 'stat', stat)
    try:
        yield state
    finally:
        state.armed = False
        record_property('proofgate_observation_fault', json.dumps({
            'exception_type': state.error.__name__, 'observed_paths': state.calls,
            'synthetic_fault_injection': True}))


@pytest.mark.parametrize('error', [PermissionError, OSError])
@pytest.mark.parametrize('cleanup_fault', ['nonzero', 'oserror'])
@pytest.mark.parametrize('fault', [None, 'execute', 'add', 'partial_add'])
def test_unavailable_residue_observation_preserves_primary_result(
        proof, failed_observation, error, cleanup_fault, fault):
    proof.fault = fault
    proof.cleanup_fault = cleanup_fault
    failed_observation.error = error
    result = _execute(proof)
    assert result['status'] == 'execution_failure'
    if fault in ('add', 'partial_add'):
        assert result['reason'] == 'original worktree add failure'
        assert 'proof_result' not in result
        assert result['applied_replacements'] == 0
    else:
        assert result['reason'] == 'worktree_cleanup_failed'
        original = result['proof_result']
        assert original['status'] == ('killed' if fault is None else 'execution_failure')
        assert result['applied_replacements'] == original['applied_replacements']
        if fault is None:
            assert result['bindings'] == original['bindings']
        else:
            assert original['reason'] == 'original proof execution failure'
    cleanup = result['cleanup']
    assert cleanup['path_exists_after_cleanup'] is None
    assert cleanup['path_observation_error']['exception_type'] == error.__name__
    assert 'residue observation unavailable' in cleanup['path_observation_error']['message']
    assert cleanup['returncode'] == (37 if cleanup_fault == 'nonzero' else None)
    assert failed_observation.calls == [str(proof.allocated[0])]
    json.dumps(result)


@pytest.mark.parametrize('error', [PermissionError, OSError])
@pytest.mark.parametrize('cleanup_fault', [None, 'nonzero', 'oserror'])
def test_unavailable_residue_observation_does_not_mask_interrupt(
        proof, failed_observation, error, cleanup_fault):
    proof.fault = 'interrupt'
    proof.cleanup_fault = cleanup_fault
    failed_observation.error = error
    with pytest.raises(KeyboardInterrupt, match='original proof interruption'):
        _execute(proof)
    if cleanup_fault is not None:
        assert failed_observation.calls == [str(proof.allocated[0])]
