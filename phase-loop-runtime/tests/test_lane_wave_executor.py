import hashlib
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import lane_wave_executor as lanes
from phase_loop_runtime.lane_capacity import memory_capacity
from phase_loop_runtime.lane_scheduler import _patterns_overlap
from phase_loop_runtime.models import PhasePlanIR, PhasePlanLane
from phase_loop_runtime.worker_pool import run_phase_worker_pool
from phase_loop_runtime.launcher import LaunchResult


@pytest.fixture(autouse=True)
def deterministic_runner_capacity(monkeypatch):
    from phase_loop_runtime.lane_capacity import LaneCapacity
    monkeypatch.setattr('phase_loop_runtime.lane_capacity.memory_capacity',
                        lambda ceiling, budget: LaneCapacity(ceiling, ceiling, 'available', 2*1024**3))


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'user.name', 'Test')
    (repo / 'plan.md').write_text('plan')
    (repo / 'delete.txt').write_text('old')
    (repo / 'unrelated.txt').write_text('base')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')
    monkeypatch.setenv('WORKTREE_ROOT', str(tmp_path / 'worktrees'))
    return repo


def setup_ir(repo, monkeypatch, count=5, dependent=False):
    entries = [PhasePlanLane(f'SL-{i}', 'lane', 'lane', owned_files=(f'{i}.txt',), parallel_safe=True) for i in range(count)]
    if dependent:
        entries[-1] = PhasePlanLane(f'SL-{count-1}', 'last', 'last', owned_files=(f'{count-1}.txt',), depends_on=tuple(x.lane_id for x in entries[:-1]))
    ir = PhasePlanIR(str(repo / 'plan.md'), {'phase': 'P'}, lanes=tuple(entries))
    monkeypatch.setattr(lanes, 'parse_phase_plan_ir', lambda _: ir)
    return ir


def invoke(repo, **kwargs):
    return lanes.execute_lane_waves(repo=repo, roadmap=repo / 'plan.md', plan=repo / 'plan.md', phase='P', executor='command', max_workers=kwargs.pop('max_workers', 4), prepare=kwargs.pop('prepare', lambda h, a: SimpleNamespace(available=True, repo=h.worktree_path, lane=a.lane_id)), trusted_closeout=lambda r, s: {'closeout_trusted': not r.failed}, event=lambda *args: None, **kwargs)


def artifacts(repo, phase, action, index, spec):
    root = repo / '.phase-loop' / 'runs' / phase
    root.mkdir(parents=True, exist_ok=True)
    return {'root': root, 'log': root / 'out', 'heartbeat': root / 'heartbeat'}


@pytest.mark.parametrize('cap', [4, 2])
@pytest.mark.parametrize('dependent', [False, True])
def test_bounded_concurrent_pool_then_dependent_snapshot(repository, monkeypatch, cap, dependent):
    repo = repository
    setup_ir(repo, monkeypatch, dependent=dependent)
    monkeypatch.setattr(lanes, 'run_artifacts', artifacts)
    head = git(repo, 'rev-parse', 'HEAD')
    (repo / 'unrelated.txt').write_text('staged')
    git(repo, 'add', 'unrelated.txt')
    index = git(repo, 'write-tree')
    (repo / 'unrelated.txt').write_text('unstaged')
    barrier = threading.Barrier(cap, timeout=10)
    active = 0
    maximum = 0
    lock = threading.Lock()
    roots = []
    def launch(spec, **kwargs):
        nonlocal active, maximum
        number = int(spec.lane.split('-')[1])
        with lock:
            active += 1
            maximum = max(active, maximum)
            roots.append(kwargs['log_path'])
        if number < 4:
            barrier.wait()
        else:
            assert all((spec.repo / f'{i}.txt').read_text() == str(i) for i in range(4))
        assert (spec.repo / 'unrelated.txt').read_text() == 'base'
        (spec.repo / f'{number}.txt').write_text(str(number))
        with lock:
            active -= 1
        return LaunchResult(command=[], returncode=0, executor='command')
    monkeypatch.setattr('phase_loop_runtime.worker_pool.launch_with_spec', launch)
    result = invoke(repo, max_workers=cap, pool=run_phase_worker_pool)
    assert result.status == 'complete', result
    assert maximum == cap
    assert len(set(roots)) == 5
    assert git(repo, 'rev-parse', 'HEAD') == head
    assert git(repo, 'write-tree') == index
    assert (repo / 'unrelated.txt').read_text() == 'unstaged'
    assert all((repo / f'{i}.txt').read_text() == str(i) for i in range(5))


def test_preparation_failure_reclaims_before_pool(repository, monkeypatch):
    setup_ir(repository, monkeypatch)
    def prepare(*args):
        raise ValueError('unavailable')
    result = invoke(repository, prepare=prepare, pool=lambda *a, **k: pytest.fail('must not launch'))
    assert (result.status, result.reason) == ('serial', 'worktree_unavailable')
    assert len(git(repository, 'worktree', 'list', '--porcelain').split('worktree ')) == 2


@pytest.mark.parametrize('after_completed_wave', [False, True])
def test_prompt_worker_outage_propagates_and_reclaims_unlaunched_wave(repository, monkeypatch, after_completed_wave):
    from phase_loop_runtime.baml_modular import BamlWorkerError

    setup_ir(repository, monkeypatch, count=3, dependent=True)
    if after_completed_wave:
        head = git(repository, 'rev-parse', 'HEAD')
        lanes._write_journal(repository / '.phase-loop/lane-attempts/prior.json', {
            'phase': 'P', 'executor': 'command', 'attempt': 'prior', 'head': head,
            'plan_identity': hashlib.sha256((repository / 'plan.md').read_bytes()).hexdigest(),
            'lanes': {f'SL-{i}': {'status': 'complete', 'paths': []} for i in range(2)},
        })
    fault = BamlWorkerError('died', rc=-9)
    def prepare(*args):
        raise fault
    with pytest.raises(BamlWorkerError) as raised:
        invoke(repository, prepare=prepare, pool=lambda *a, **k: pytest.fail('must not launch'))
    assert raised.value is fault
    assert len(git(repository, 'worktree', 'list', '--porcelain').split('worktree ')) == 2
    assert not lanes.lane_recovery_blocker(repository, 'P')
    if after_completed_wave:
        journal = json.loads((repository / '.phase-loop/lane-attempts/prior.json').read_text())
        assert all(record['status'] == 'complete' for record in journal['lanes'].values())


def test_preview_does_not_write_lane_state(repository, monkeypatch):
    setup_ir(repository, monkeypatch)
    assert invoke(repository, dry_run=True).status == 'preview'
    assert not (repository / '.phase-loop' / 'lane-attempts').exists()


def test_uncertain_old_plan_blocks_even_new_plan(repository):
    path = repository / '.phase-loop' / 'lane-attempts' / 'old.json'
    lanes._write_journal(path, {'phase': 'P', 'plan_identity': 'old', 'lanes': {'SL-0': {'status': 'transport_intent'}}})
    assert lanes.lane_recovery_blocker(repository, 'P')
    assert invoke(repository).reason == 'lane_recovery_required'


def test_prefixless_glob_is_ambiguous():
    assert _patterns_overlap('*.py', 'src/*')
    assert _patterns_overlap('?', 'src/file')


def test_memory_capacity_ancestor_and_unknown():
    gib = 1024 ** 3
    values = {'/proc/meminfo': f'MemAvailable: {20*gib//1024} kB', '/proc/self/cgroup': '0::/group/child', '/sys/fs/cgroup/group/child/memory.max': 'max', '/sys/fs/cgroup/group/memory.max': str(6*gib), '/sys/fs/cgroup/group/memory.current': str(2*gib), '/sys/fs/cgroup/memory.max': 'max'}
    assert memory_capacity(4, 2*gib, read=lambda p: values[str(p)]).effective == 2
    assert memory_capacity(4, gib, read=lambda p: values[str(p)]).effective == 4
    assert memory_capacity(4, None, read=lambda p: values[str(p)]).effective == 2
    assert memory_capacity(4, None, read=lambda p: '').reason == 'capacity_unknown'
    values['/sys/fs/cgroup/group/memory.max'] = str(25*gib)
    values['/sys/fs/cgroup/group/memory.current'] = str(int(16.9*gib))
    assert memory_capacity(4, None, read=lambda p: values[str(p)]).effective == 4
    with pytest.raises(ValueError):
        memory_capacity(0, gib)


def test_snapshot_add_delete_does_not_borrow_index(repository):
    repo = repository
    head = git(repo, 'rev-parse', 'HEAD')
    (repo / 'unrelated.txt').write_text('staged')
    git(repo, 'add', 'unrelated.txt')
    index = git(repo, 'write-tree')
    (repo / 'delete.txt').unlink()
    (repo / 'added.txt').write_text('new')
    snapshot = lanes.snapshot_lane_outputs(repo, head, ['delete.txt', 'added.txt'])
    assert git(repo, 'show', f'{snapshot}:added.txt') == 'new'
    assert 'delete.txt' not in git(repo, 'ls-tree', '--name-only', snapshot).splitlines()
    assert git(repo, 'show', f'{snapshot}:unrelated.txt') == 'base'
    assert git(repo, 'write-tree') == index
    assert git(repo, 'rev-parse', 'HEAD') == head


def test_refused_ownership_preserves_generation_without_parent_write(repository, monkeypatch):
    repo = repository
    setup_ir(repo, monkeypatch, count=2)
    monkeypatch.setattr(lanes, 'run_artifacts', artifacts)
    def launch(spec, **kwargs):
        (spec.repo / 'foreign.txt').write_text('not owned')
        return LaunchResult(command=[], returncode=0, executor='command')
    monkeypatch.setattr('phase_loop_runtime.worker_pool.launch_with_spec', launch)
    result = invoke(repo, pool=run_phase_worker_pool)
    assert result.reason == 'lane_transport_refused'
    assert not (repo / 'foreign.txt').exists()
    assert all(Path(record['worktree']).exists() for record in result.metadata['lanes'].values())
    assert lanes.lane_recovery_blocker(repo, 'P')


def test_interrupted_transport_is_not_reapplied(repository, monkeypatch):
    repo = repository
    setup_ir(repo, monkeypatch, count=2)
    monkeypatch.setattr(lanes, 'run_artifacts', artifacts)
    monkeypatch.setattr('phase_loop_runtime.worker_pool.launch_with_spec', lambda *a, **k: LaunchResult(command=[], returncode=0))
    def interrupted(*args, **kwargs):
        raise RuntimeError('after intent')
    monkeypatch.setattr(lanes, 'transfer_phase_worktree_dirty', interrupted)
    result = invoke(repo, pool=run_phase_worker_pool)
    assert result.reason == 'lane_recovery_required'
    assert 'transport_intent' in {r['status'] for r in result.metadata['lanes'].values()}
    assert invoke(repo, pool=lambda *a, **k: pytest.fail('no relaunch')).reason == 'lane_recovery_required'


def test_actual_closeout_predicate_rejects_bare_or_blocked(monkeypatch):
    from phase_loop_runtime import runner
    monkeypatch.setattr(runner, '_parsed_child_automation', lambda r, s: {})
    assert not runner._trusted_concurrent_worker_closeout(LaunchResult(command=[], returncode=0), None)['closeout_trusted']
    parsed = {'automation_status': 'complete', 'automation_verification_status': 'passed'}
    monkeypatch.setattr(runner, '_parsed_child_automation', lambda r, s: parsed)
    assert runner._trusted_concurrent_worker_closeout(LaunchResult(command=[], returncode=0), None)['closeout_trusted']
    parsed['automation_parse_error'] = True
    assert not runner._trusted_concurrent_worker_closeout(LaunchResult(command=[], returncode=0), None)['closeout_trusted']


@pytest.mark.parametrize('mode,cap,expected', [('concurrent', 4, True), ('off', 4, False), ('concurrent', 1, False)])
def test_runner_default_and_explicit_serial_switches(tmp_path, monkeypatch, mode, cap, expected):
    from phase_loop_runtime import runner
    from phase_loop_runtime.events import read_events
    from phase_loop_test_utils import make_repo, write_phase_plan, commit_fixture_paths
    from test_phase_loop_wave_runner import _concurrent_wave_body
    repo = make_repo(tmp_path)
    roadmap = repo / 'specs' / 'phase-plans-v1.md'
    plan = write_phase_plan(repo, 'RUNNER', roadmap, body=_concurrent_wave_body())
    commit_fixture_paths(repo, 'fixture', plan)
    calls = []
    def execute(**kwargs):
        calls.append(kwargs)
        return lanes.LaneExecutionResult('preview', 'ready', {})
    from phase_loop_runtime.models import PromptBundle
    monkeypatch.setattr(runner, 'build_prompt', lambda *a, **k: PromptBundle('fake', 'fixture', 'context_file'))
    monkeypatch.setattr(lanes, 'execute_lane_waves', execute)
    runner.run_loop(repo, roadmap, phase='RUNNER', dry_run=True, lane_scheduler_mode=mode, max_parallel_lanes=cap)
    assert bool(calls) is expected
    if expected:
        assert calls[0]['max_workers'] == 4
        assert read_events(repo)[-1]['selected_executor']


@pytest.mark.parametrize('gate', ['review', 'force_replan', 'auth'])
def test_runner_gates_precede_lane_execution(tmp_path, monkeypatch, gate):
    from phase_loop_runtime import runner
    from phase_loop_runtime.models import PromptBundle
    from phase_loop_test_utils import make_repo, write_phase_plan, commit_fixture_paths
    from test_phase_loop_wave_runner import _concurrent_wave_body
    repo = make_repo(tmp_path)
    roadmap = repo / 'specs' / 'phase-plans-v1.md'
    plan = write_phase_plan(repo, 'RUNNER', roadmap, body=_concurrent_wave_body())
    commit_fixture_paths(repo, 'fixture', plan)
    monkeypatch.setattr(runner, 'build_prompt', lambda *a, **k: PromptBundle('fake', 'fixture', 'context_file'))
    monkeypatch.setattr(lanes, 'execute_lane_waves', lambda **k: pytest.fail('gate must precede lanes'))
    monkeypatch.setattr(runner, 'launch_with_spec', lambda *a, **k: LaunchResult(command=[], returncode=0, dry_run=True))
    monkeypatch.setattr(runner, '_execute_dispatch_preflight_gates', lambda *a, **k: None)
    if gate == 'auth':
        monkeypatch.setattr(runner, 'run_auth_preflight', lambda s: SimpleNamespace(ok=False, metadata={}, blocker_class='contract_bug', blocker_summary='fixture auth refusal'))
    if gate == 'force_replan':
        monkeypatch.setattr(runner, '_latest_phase_event_status', lambda *a: 'planned')
    kwargs = {'product_action_override': 'review'} if gate == 'review' else ({'force_replan': True} if gate == 'force_replan' else {})
    runner.run_loop(repo, roadmap, phase='RUNNER', dry_run=gate != 'auth', **kwargs)


@pytest.mark.parametrize('passed', [True, False])
def test_combined_verification_before_closeout(tmp_path, monkeypatch, passed):
    from phase_loop_runtime import runner
    from phase_loop_runtime.models import PromptBundle
    from phase_loop_test_utils import make_repo, write_phase_plan, commit_fixture_paths
    from test_phase_loop_wave_runner import _concurrent_wave_body
    repo = make_repo(tmp_path)
    roadmap = repo / 'specs' / 'phase-plans-v1.md'
    plan = write_phase_plan(repo, 'RUNNER', roadmap, body=_concurrent_wave_body())
    commit_fixture_paths(repo, 'fixture', plan)
    order = []
    monkeypatch.setattr(runner, 'build_prompt', lambda *a, **k: PromptBundle('fake', 'fixture', 'context_file'))
    monkeypatch.setattr(runner, '_execute_dispatch_preflight_gates', lambda *a, **k: None)
    monkeypatch.setattr(runner, 'run_auth_preflight', lambda s: SimpleNamespace(ok=True, metadata={}))
    def execute(**kwargs):
        order.append('transport')
        return lanes.LaneExecutionResult('complete', 'accepted', {})
    def verify(**kwargs):
        order.append('verification')
        assert kwargs['repo'] == repo
        return {'ok': passed, 'code': 'ok' if passed else 'nonzero_exit'}
    monkeypatch.setattr(lanes, 'execute_lane_waves', execute)
    monkeypatch.setattr(runner, '_run_execute_verification', verify)
    monkeypatch.setattr(runner, 'launch_with_spec', lambda *a, **k: pytest.fail('no coarse launch'))
    snapshot, _ = runner.run_loop(repo, roadmap, phase='RUNNER', closeout_mode='manual')
    assert order == ['transport', 'verification']
    assert snapshot.phases['RUNNER'] == ('awaiting_phase_closeout' if passed else 'blocked')


def test_cli_precedence_and_invalid_values():
    import argparse
    from phase_loop_runtime.cli import build_parser, _resolve_lane_options
    parser = build_parser()
    args = parser.parse_args(['run'])
    assert _resolve_lane_options(args, {}) == ('concurrent', 4, None)
    assert _resolve_lane_options(args, {'PHASE_LOOP_LANE_SCHEDULER': 'off', 'PHASE_LOOP_MAX_PARALLEL_LANES': '2'}) == ('off', 2, None)
    args = parser.parse_args(['run', '--lane-scheduler', 'concurrent', '--max-parallel-lanes', '4'])
    assert _resolve_lane_options(args, {'PHASE_LOOP_LANE_SCHEDULER': 'off', 'PHASE_LOOP_MAX_PARALLEL_LANES': '2'}) == ('concurrent', 4, None)
    for value in ['0', '-1', 'bad']:
        with pytest.raises(SystemExit):
            parser.parse_args(['run', '--max-parallel-lanes', value])
        with pytest.raises(argparse.ArgumentTypeError):
            _resolve_lane_options(parser.parse_args(['run']), {'PHASE_LOOP_MAX_PARALLEL_LANES': value})


@pytest.mark.parametrize('source,mode,dry_run,blocked', [
    ('work_unit', 'concurrent', False, False),
    ('lane_scheduler', 'concurrent', True, False),
    ('lane_scheduler', 'serialized', False, False),
    ('lane_scheduler', 'concurrent', False, True),
])
def test_recovery_ignores_unrelated_work_units(repository, monkeypatch, source, mode, dry_run, blocked):
    state = SimpleNamespace(identity=SimpleNamespace(phase='P'), status='running',
                            policy={'source': source, 'mode': mode, 'dry_run': dry_run})
    monkeypatch.setattr('phase_loop_runtime.state.load_work_unit_state', lambda _: {'unit': state})
    details = lanes.lane_recovery_blocker(repository, 'P')
    assert bool(details) is blocked
    if blocked:
        assert details['work_unit_ids'] == ['unit']


@pytest.mark.parametrize('foreign', [False, True])
def test_directory_ownership_transport(repository, monkeypatch, foreign):
    repo = repository
    entries = tuple(PhasePlanLane(f'SL-{i}', 'lane', 'lane', owned_files=(f'dir{i}/',), parallel_safe=True) for i in range(2))
    monkeypatch.setattr(lanes, 'parse_phase_plan_ir', lambda _: PhasePlanIR(str(repo/'plan.md'), {'phase':'P'}, lanes=entries))
    monkeypatch.setattr(lanes, 'run_artifacts', artifacts)
    def launch(spec, **kwargs):
        number = int(spec.lane.split('-')[1])
        directory = spec.repo / (f'dir{1-number}' if foreign else f'dir{number}')
        directory.mkdir()
        (directory / 'a.txt').write_text('output')
        return LaunchResult(command=[], returncode=0, executor='command')
    monkeypatch.setattr('phase_loop_runtime.worker_pool.launch_with_spec', launch)
    result = invoke(repo, pool=run_phase_worker_pool)
    assert result.status == ('blocked' if foreign else 'complete')
    if not foreign:
        assert (repo / 'dir0/a.txt').read_text() == 'output'


@pytest.mark.parametrize('closeout_mode', ['manual', 'commit'])
def test_lane_outputs_reach_ordinary_closeout(tmp_path, monkeypatch, closeout_mode):
    from phase_loop_runtime import runner
    from phase_loop_runtime.models import PromptBundle
    from phase_loop_test_utils import make_repo, write_phase_plan, commit_fixture_paths
    from test_phase_loop_wave_runner import _concurrent_wave_body
    repo = make_repo(tmp_path)
    roadmap = repo / 'specs/phase-plans-v1.md'
    plan = write_phase_plan(repo, 'RUNNER', roadmap, body=_concurrent_wave_body())
    commit_fixture_paths(repo, 'fixture', plan)
    monkeypatch.setattr(runner, 'build_prompt', lambda *a, **k: PromptBundle('fake', 'fixture', 'context_file'))
    monkeypatch.setattr(runner, '_execute_dispatch_preflight_gates', lambda *a, **k: None)
    monkeypatch.setattr(runner, 'run_auth_preflight', lambda s: SimpleNamespace(ok=True, metadata={}))
    def execute(**kwargs):
        (repo / 'producer-a.py').write_text('a = 1\n')
        (repo / 'producer-b.py').write_text('b = 2\n')
        return lanes.LaneExecutionResult('complete', 'accepted', {})
    monkeypatch.setattr(lanes, 'execute_lane_waves', execute)
    monkeypatch.setattr(runner, '_run_execute_verification', lambda **k: {'ok': True})
    monkeypatch.setattr(runner, 'launch_with_spec', lambda *a, **k: pytest.fail('no coarse launch'))
    snapshot, _ = runner.run_loop(repo, roadmap, phase='RUNNER', closeout_mode=closeout_mode)
    if closeout_mode == 'manual':
        assert snapshot.phases['RUNNER'] == 'awaiting_phase_closeout', snapshot
        assert set(snapshot.phase_owned_dirty_paths) == {'producer-a.py', 'producer-b.py'}
    else:
        assert snapshot.phases['RUNNER'] == 'complete', snapshot
        assert git(repo, 'show', 'HEAD:producer-a.py') == 'a = 1'
        assert git(repo, 'show', 'HEAD:producer-b.py') == 'b = 2'


@pytest.mark.parametrize('enforcement,expected', [('warn','awaiting_phase_closeout'), ('hard','blocked')])
def test_lane_soft_verification_matches_coarse(tmp_path, monkeypatch, enforcement, expected):
    from phase_loop_runtime import runner
    from phase_loop_runtime.models import PromptBundle
    from phase_loop_test_utils import make_repo, write_phase_plan, commit_fixture_paths
    from test_phase_loop_wave_runner import _concurrent_wave_body
    repo = make_repo(tmp_path)
    roadmap = repo / 'specs/phase-plans-v1.md'
    plan = write_phase_plan(repo, 'RUNNER', roadmap, body=_concurrent_wave_body())
    commit_fixture_paths(repo, 'fixture', plan)
    monkeypatch.setenv('PHASE_LOOP_VERIFY_ENFORCE', enforcement)
    monkeypatch.setattr(runner, 'build_prompt', lambda *a, **k: PromptBundle('fake', 'fixture', 'context_file'))
    monkeypatch.setattr(runner, '_execute_dispatch_preflight_gates', lambda *a, **k: None)
    monkeypatch.setattr(runner, 'run_auth_preflight', lambda s: SimpleNamespace(ok=True, metadata={}))
    monkeypatch.setattr(lanes, 'execute_lane_waves', lambda **k: lanes.LaneExecutionResult('complete', 'accepted', {}))
    monkeypatch.setattr(runner, '_run_execute_verification', lambda **k: {'ok': False, 'code':'missing_run_dir'})
    snapshot, _ = runner.run_loop(repo, roadmap, phase='RUNNER', closeout_mode='manual')
    assert snapshot.phases['RUNNER'] == expected


def test_explicit_mount_precedes_environment(tmp_path, monkeypatch):
    from phase_loop_runtime.runtime_paths import lane_worktree_root
    explicit = tmp_path / 'explicit'
    explicit.mkdir()
    monkeypatch.setenv('WORKTREE_ROOT', str(tmp_path / 'ambient'))
    assert lane_worktree_root(tmp_path, workspace_mount=explicit) == explicit / 'worktrees'
    assert lane_worktree_root(tmp_path, workspace_mount=tmp_path/'missing') == tmp_path.parent
    assert lane_worktree_root(tmp_path) == tmp_path / 'ambient'
