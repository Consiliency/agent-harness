"""Real retained venv controls for agent-harness#428; no network or fixture cleanup."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import venv

import pytest

from phase_loop_runtime import verification_evidence as ve


IDENTITY = """import importlib.util,json,pathlib,sys
spec=importlib.util.find_spec('ah428_identity_marker')
pathlib.Path(sys.argv[1]).write_text(json.dumps({
 'prefix':sys.prefix,'base_prefix':sys.base_prefix,'executable':sys.executable,
 'marker':spec.origin if spec else None,'args':sys.argv[2:]}))
"""


def _venv(path, *, pip=False):
    venv.EnvBuilder(with_pip=pip, symlinks=True).create(path)
    python = path / 'bin/python'
    assert python.is_symlink(), 'fixture must reproduce a symlink-backed venv'
    site = Path(subprocess.check_output(
        [str(python), '-c', "import sysconfig;print(sysconfig.get_path('purelib'))"], text=True
    ).strip())
    (site / 'ah428_identity_marker.py').write_text('VALUE = "venv-local"\n')
    return python


def _repo(path, spec='>=3.10'):
    path.mkdir(parents=True, exist_ok=True)
    constraint = f'requires-python = "{spec}"\n' if spec else ''
    (path / 'pyproject.toml').write_text('[project]\nname="fixture"\nversion="0"\n' + constraint)
    return path


def _script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n' + body)
    path.chmod(0o755)
    return path


def _identity_argv(python, output, *args):
    return [str(python), '-c', IDENTITY, str(output), *args]


def _assert_identity(output, python, args=()):
    assert output.is_file(), 'child identity JSON must exist'
    data = json.loads(output.read_text())
    expected = python.parent.parent.resolve()
    assert Path(data['prefix']).resolve() == expected, 'selected venv prefix was lost'
    assert Path(data['base_prefix']).resolve() != expected
    assert data['marker'] and Path(data['marker']).resolve().is_relative_to(expected), 'venv marker was lost'
    assert Path(data['executable']).parent.parent.resolve() == expected, 'selected executable was lost'
    assert data['args'] == list(args), 'literal argv forwarding changed'
    return data


def _direct(python, output, *args):
    completed = subprocess.run(_identity_argv(python, output, *args), capture_output=True)
    output.with_suffix('.stdout').write_bytes(completed.stdout)
    output.with_suffix('.stderr').write_bytes(completed.stderr)
    assert completed.returncode == 0, 'direct fixture control must succeed'
    return _assert_identity(output, python, args)


def _run(repo, name, argv, *, pin=None, refresh=None):
    run = repo / '.phase-loop' / name
    result = ve.run_verification(repo, run, [], argv, refresh, 60, python_pin=pin)
    validation = ve.validate_verification_artifact(run / 'verification.json')
    (run / 'validation.json').write_text(json.dumps(validation.to_json(), indent=2))
    return result, validation, run


def _candidates(monkeypatch, mapping):
    # Deterministic discovery only; every version probe and launcher executes for real.
    monkeypatch.setattr(ve, '_interpreter_path', lambda name: mapping.get(name))


def test_direct_venv_control(tmp_path):
    python = _venv(tmp_path / 'selected')
    _direct(python, tmp_path / 'direct.json', 'space argument', "'quoted'", '$literal')


@pytest.mark.parametrize('alias', ['python', 'python3', 'login-shell'])
def test_pinned_alias_preserves_identity_and_literal_arguments(tmp_path, monkeypatch, alias):
    python = _venv(tmp_path / "venv space 'quote' $(touch injected) $HOME `touch injected2`")
    repo = _repo(tmp_path / 'repo')
    _direct(python, tmp_path / 'direct.json')
    _candidates(monkeypatch, {str(python): python})
    output = repo / 'identity.json'
    literal = ['a b', "a'b", '$(touch argv-injected)', '$HOME', ';exit 77']
    argv = _identity_argv('python' if alias == 'login-shell' else alias, output, *literal)
    if alias == 'login-shell':
        argv = ['/bin/bash', '-lc', shlex.join(argv)]
    result, valid, run = _run(repo, 'identity', argv, pin=str(python))
    assert result.suite.exit_code == 0
    _assert_identity(output, python, literal)
    assert valid.ok
    for name in ('injected', 'injected2', 'argv-injected'):
        assert not (repo / name).exists(), 'launcher interpolated shell syntax'
    assert (run / '_interp_shim/python').is_symlink()
    assert (run / '_interp_shim/python3').is_symlink()


@pytest.mark.parametrize('branch', ['pin', 'fallback', 'already-satisfying'])
def test_selected_metadata_and_pip_alignment_keep_lexical_venv(tmp_path, monkeypatch, branch):
    python = _venv(tmp_path / 'selected')
    repo = _repo(tmp_path / 'repo')
    _direct(python, tmp_path / 'direct.json')
    versioned = python.with_name(f'python3.{sys.version_info.minor}')
    mapping = {str(python): python, versioned.name: versioned}
    if branch == 'already-satisfying':
        mapping.update(python=python, python3=python.with_name('python3'))
    _candidates(monkeypatch, mapping)
    monkeypatch.setenv('PATH', str(python.parent))
    selected = ve._resolve_suite_interpreter(repo, repo / 'selection', str(python) if branch == 'pin' else None)
    expected = mapping['python3'] if branch == 'already-satisfying' else versioned if branch == 'fallback' else python
    assert selected.blocker is None
    assert selected.interpreter == str(expected), 'selected metadata dereferenced the venv'
    assert ve._align_install_interpreter(['python', '-m', 'pip', '--version'], selected.interpreter)[0] == str(expected)
    output = repo / 'identity.json'
    result, valid, _ = _run(repo, 'native', _identity_argv('python', output), pin=str(python) if branch == 'pin' else None)
    assert result.suite.exit_code == 0
    _assert_identity(output, python)
    assert valid.ok


@pytest.mark.parametrize('alias', ['python', 'python3', 'versioned'])
def test_relative_path_discovery_and_execution_use_same_directory(tmp_path, monkeypatch, alias):
    a, b = tmp_path / 'a', _repo(tmp_path / 'b')
    python_a = _venv(a / 'selected')
    python_b = _venv(b / 'selected')
    _direct(python_a, a / 'direct.json')
    _direct(python_b, b / 'direct.json')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', 'selected/bin')
    name = f'python3.{sys.version_info.minor}' if alias == 'versioned' else alias
    output = b / 'identity.json'
    result, valid, _ = _run(b, 'relative', _identity_argv(name, output))
    assert result.suite.exit_code == 0
    _assert_identity(output, python_a)
    assert valid.ok
    selected = ve._resolve_suite_interpreter(b, b / 'selection', None)
    assert selected.interpreter == str(a / 'selected/bin/python3')
    assert ve._align_install_interpreter(['python', '-m', 'pip'], selected.interpreter)[0] == selected.interpreter


def test_symlink_dotdot_spelling_survives_discovery_launcher_and_metadata(tmp_path, monkeypatch):
    a, b = tmp_path / 'a', _repo(tmp_path / 'b')
    (a / 'real/nested').mkdir(parents=True)
    python = _venv(a / 'real/chosen')
    _venv(a / 'chosen')
    (a / 'link').symlink_to(a / 'real/nested', target_is_directory=True)
    _direct(python, a / 'direct.json')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', 'link/../chosen/bin')
    expected = a / 'link/../chosen/bin/python'
    assert ve._interpreter_path('link/../chosen/bin/python') == expected
    assert ve._interpreter_path('python') == expected
    selected = ve._resolve_suite_interpreter(b, b / 'selection', 'link/../chosen/bin/python')
    assert selected.interpreter == str(expected), 'lexical metadata spelling changed'
    output = b / 'identity.json'
    result, valid, _ = _run(b, 'lexical', _identity_argv('python', output), pin='link/../chosen/bin/python')
    assert result.suite.exit_code == 0
    _assert_identity(output, python)
    assert valid.ok


def test_distinct_satisfying_aliases_keep_their_venvs(tmp_path, monkeypatch):
    repo = _repo(tmp_path / 'repo')
    first, second = _venv(tmp_path / 'first'), _venv(tmp_path / 'second')
    _direct(first, tmp_path / 'first.json')
    _direct(second, tmp_path / 'second.json')
    bins = tmp_path / 'aliases'
    _script(bins / 'python', f'exec {shlex.quote(str(first))} "$@"\n')
    _script(bins / 'python3', f'exec {shlex.quote(str(second))} "$@"\n')
    monkeypatch.setenv('PATH', str(bins))
    for name, python in [('python', first), ('python3', second)]:
        output = repo / (name + '.json')
        result, valid, run = _run(repo, name, _identity_argv(name, output))
        assert result.suite.exit_code == 0 and valid.ok
        _assert_identity(output, python)
        assert not (run / '_interp_shim/_selected_python').exists()
        assert not (run / '_interp_shim/python').exists()
    selected = ve._resolve_suite_interpreter(repo, repo / 'selection', None)
    assert selected.interpreter == str(bins / 'python3')
    assert ve._align_install_interpreter(['python', '-m', 'pip'], selected.interpreter)[0] == str(bins / 'python3')


def test_empty_path_unprobeable_versioned_candidate_is_shadowed(tmp_path, monkeypatch):
    a, b = tmp_path / 'a', _repo(tmp_path / 'b')
    python = _venv(a / 'selected')
    _direct(python, a / 'direct.json')
    effect = tmp_path / 'candidate-executed'
    name = f'python3.{sys.version_info.minor}'
    body = f'case "$*" in *sys.version_info*) exit 23;; esac\n: > {shlex.quote(str(effect))}\n'
    for root in (a, b):
        _script(root / name, body)
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', '')
    assert ve._interpreter_full_version(a / name, b) is None
    assert not effect.exists(), 'probe fixture must have no suite effect'
    result, valid, run = _run(b, 'empty', [name], pin=str(python))
    assert result.suite.exit_code != 0, 'unprobeable versioned candidate escaped its shadow'
    assert not effect.exists(), 'unprobeable candidate executed during suite'
    assert (run / '_interp_shim' / name).is_file()
    assert valid.code == 'nonzero_exit'


@pytest.mark.parametrize('default_kind', ['confstr', 'attribute-fallback', 'value-fallback'])
def test_missing_path_discovery_default_and_pinned_execution(tmp_path, monkeypatch, default_kind):
    python = _venv(tmp_path / 'selected')
    repo = _repo(tmp_path / 'repo')
    _direct(python, tmp_path / 'direct.json')
    monkeypatch.delenv('PATH', raising=False)
    if default_kind == 'confstr':
        monkeypatch.setattr(os, 'confstr', lambda name: str(python.parent))
        monkeypatch.setattr(os, 'defpath', '/absent-default')
    else:
        def unavailable(name):
            raise AttributeError(name) if default_kind == 'attribute-fallback' else ValueError(name)
        monkeypatch.setattr(os, 'confstr', unavailable)
        monkeypatch.setattr(os, 'defpath', str(python.parent))
    assert ve._interpreter_path('python') == python
    output = repo / 'identity.json'
    result, valid, _ = _run(repo, 'missing', _identity_argv('python', output), pin=str(python))
    assert result.suite.exit_code == 0
    _assert_identity(output, python)
    assert valid.ok
    assert 'PATH' not in os.environ


@pytest.mark.parametrize('assignment,expected_anchor', [('PATH=selected/bin', 'b'), ('PATH=./selected/bin', 'b'), ('LABEL=value', 'a')])
def test_consumed_override_uses_repo_and_unrelated_assignment_keeps_caller(tmp_path, monkeypatch, assignment, expected_anchor):
    a, b = tmp_path / 'a', _repo(tmp_path / 'b')
    python_a, python_b = _venv(a / 'selected'), _venv(b / 'selected')
    _direct(python_a, a / 'direct.json')
    _direct(python_b, b / 'direct.json')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', 'selected/bin')
    output = b / 'identity.json'
    result, valid, _ = _run(b, 'override', [assignment, *_identity_argv('python', output)])
    assert result.suite.exit_code == 0
    _assert_identity(output, python_b if expected_anchor == 'b' else python_a)
    assert valid.ok


def test_probe_and_execution_share_delegated_venv_identity(tmp_path, monkeypatch):
    a, b = tmp_path / 'a', _repo(tmp_path / 'b')
    python_a, python_b = _venv(a / 'selected'), _venv(b / 'selected')
    _direct(python_a, a / 'direct.json')
    _direct(python_b, b / 'direct.json')
    for root, python in ((a, python_a), (b, python_b)):
        recorder = root / 'record.py'
        recorder.write_text(
            'import json,os,sys\n'
            f'with open({str(root / "delegation.jsonl")!r},"a") as f: f.write(json.dumps({{"prefix":sys.prefix,"argv":sys.argv[1:]}})+"\\n")\n'
            'os.execv(sys.executable,[sys.executable,*sys.argv[1:]])\n'
        )
        _script(root / 'delegates/venv_delegate', f'exec {shlex.quote(str(python))} {shlex.quote(str(recorder))} "$@"\n')
    name = f'python3.{sys.version_info.minor}'
    wrapper = _script(tmp_path / 'wrappers' / name, 'exec venv_delegate "$@"\n')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', str(wrapper.parent) + ':delegates')
    monkeypatch.setattr(ve, '_CANDIDATE_MINORS', (sys.version_info.minor,))
    control = subprocess.run([str(wrapper), '-c', 'import sys;print(sys.version)'], capture_output=True)
    (a / 'delegated-control.stdout').write_bytes(control.stdout)
    assert control.returncode == 0
    assert json.loads((a / 'delegation.jsonl').read_text().splitlines()[0])['prefix'] == str(python_a.parent.parent)
    output = b / 'identity.json'
    result, valid, _ = _run(b, 'delegated', _identity_argv('python', output))
    assert result.suite.exit_code == 0
    _assert_identity(output, python_a)
    assert not (b / 'delegation.jsonl').exists(), 'probe selected B while execution must select A'
    records = [json.loads(line) for line in (a / 'delegation.jsonl').read_text().splitlines()]
    assert len(records) >= 4 and all(Path(row['prefix']) == python_a.parent.parent for row in records)
    assert valid.ok


def test_fresh_process_append_keeps_pin_and_uses_current_path_anchors(tmp_path, monkeypatch):
    a, b, c = tmp_path / 'a', _repo(tmp_path / 'b'), tmp_path / 'c'
    python_a, python_b, python_c = (_venv(root / 'selected') for root in (a, b, c))
    for root, python in ((a, python_a), (b, python_b), (c, python_c)):
        _direct(python, root / 'direct.json')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', 'selected/bin')
    result, valid, run = _run(b, 'initial', _identity_argv('python', b / 'initial.json'), pin=str(python_a))
    assert result.suite.exit_code == 0
    _assert_identity(b / 'initial.json', python_a)
    assert valid.ok
    artifact = run / 'verification.json'
    initial = artifact.read_bytes()
    initial_log = (run / 'verification.log').read_bytes()
    name = f'python3.{sys.version_info.minor}'
    commands = [
        _identity_argv('python', b / 'bare.json'),
        _identity_argv(name, b / 'inherited.json'),
        ['PATH=selected/bin', *_identity_argv(name, b / 'override.json')],
    ]
    code = 'from pathlib import Path;from phase_loop_runtime.verification_evidence import _append_verification_command;import json,sys\nfor argv in json.loads(sys.argv[3]):\n r=_append_verification_command(Path(sys.argv[1]),Path(sys.argv[2]),argv,60);assert r.exit_code==0\n'
    env = {**os.environ, 'PATH': 'selected/bin', 'PYTHONPATH': str(Path(ve.__file__).resolve().parent.parent)}
    child = subprocess.run([sys.executable, '-c', code, str(b), str(artifact), json.dumps(commands)], cwd=c, env=env, capture_output=True)
    (run / 'append.stdout').write_bytes(child.stdout)
    (run / 'append.stderr').write_bytes(child.stderr)
    assert child.returncode == 0
    _assert_identity(b / 'bare.json', python_a)
    _assert_identity(b / 'inherited.json', python_c)
    _assert_identity(b / 'override.json', python_b)
    assert ve.validate_verification_artifact(artifact).ok
    assert artifact.read_bytes() != initial and (run / 'verification.log').read_bytes() != initial_log
    assert len(json.loads(artifact.read_text())['commands']) == 3


def test_native_pip_refresh_uses_selected_venv(tmp_path, monkeypatch):
    python = _venv(tmp_path / 'selected-with-pip', pip=True)
    repo = _repo(tmp_path / 'repo')
    _direct(python, tmp_path / 'direct.json')
    control = subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True)
    (repo / 'pip-direct.stdout').write_bytes(control.stdout)
    (repo / 'pip-direct.stderr').write_bytes(control.stderr)
    assert control.returncode == 0 and str(python.parent.parent).encode() in control.stdout
    _candidates(monkeypatch, {str(python): python})
    refresh = {'triggered': True, 'manifests': ['pyproject.toml'], 'install_argv': ['python', '-m', 'pip', '--version']}
    output = repo / 'identity.json'
    result, valid, run = _run(repo, 'pip', _identity_argv('python', output), pin=str(python), refresh=refresh)
    assert result.env_refresh.install_argv[0] == str(python), 'pip metadata dereferenced the selected venv'
    assert result.env_refresh.exit_code == 0
    log = (run / 'verification.log').read_bytes()
    assert control.stdout.strip() in log, 'native pip location differs from direct selected venv'
    _assert_identity(output, python)
    assert valid.ok


def test_symlink_fallback_preserves_argv_identity_and_exit(tmp_path, monkeypatch):
    python = _venv(tmp_path / "venv 'quote' $(touch injected) $HOME `touch injected2`")
    repo = _repo(tmp_path / 'repo')
    _direct(python, tmp_path / 'direct.json')
    def unavailable(*args, **kwargs):
        raise OSError('fixture: symlinks unavailable')
    with monkeypatch.context() as limited:
        limited.setattr(ve.os, 'symlink', unavailable)
        shim = ve._build_interpreter_shim(repo / 'run', python)
    for name in ('python', 'python3'):
        output = repo / (name + '.json')
        literal = ['$(touch argv-injected)', 'a b', "x'y"]
        child = subprocess.run([str(shim / name), '-c', IDENTITY + '\nsys.exit(37)\n', str(output), *literal], cwd=repo, capture_output=True)
        (repo / (name + '.stdout')).write_bytes(child.stdout)
        (repo / (name + '.stderr')).write_bytes(child.stderr)
        assert child.returncode == 37, 'fallback launcher lost target exit status'
        _assert_identity(output, python, literal)
        assert (shim / name).read_bytes() == (shim / '_selected_python').read_bytes()
    assert not any((repo / name).exists() for name in ('injected', 'injected2', 'argv-injected'))


def test_launcher_does_not_write_through_existing_symlink(tmp_path):
    python = _venv(tmp_path / 'selected')
    outside = tmp_path / 'sentinel'
    outside.write_bytes(b'preserve outside bytes')
    run = tmp_path / 'run'
    shim = run / '_interp_shim'
    shim.mkdir(parents=True)
    (shim / '_selected_python').symlink_to(outside)
    ve._build_interpreter_shim(run, python)
    assert outside.read_bytes() == b'preserve outside bytes'
    assert not (shim / '_selected_python').is_symlink()
    child = subprocess.run(_identity_argv(shim / 'python', tmp_path / 'identity.json'), capture_output=True)
    assert child.returncode == 0
    _assert_identity(tmp_path / 'identity.json', python)


def test_unsatisfiable_pin_blocks_refresh_and_suite(tmp_path, monkeypatch):
    python = _venv(tmp_path / 'selected')
    repo = _repo(tmp_path / 'repo', '>=99')
    _direct(python, tmp_path / 'direct.json')
    _candidates(monkeypatch, {str(python): python})
    refresh = {'triggered': True, 'install_argv': [str(python), '-c', "from pathlib import Path;Path('refresh-effect').touch()"]}
    result, valid, _ = _run(repo, 'blocked', _identity_argv('python', repo / 'suite.json'), pin=str(python), refresh=refresh)
    assert result.suite.exit_code != 0 and result.env_refresh is None
    assert not (repo / 'refresh-effect').exists() and not (repo / 'suite.json').exists()
    assert valid.code == 'nonzero_exit'


def test_no_spec_no_pin_keeps_environment_and_adds_no_shim(tmp_path, monkeypatch):
    repo = _repo(tmp_path / 'repo', None)
    monkeypatch.setenv('PATH', 'relative::/absolute:relative')
    selected = ve._resolve_suite_interpreter(repo, repo / 'selection', None)
    assert selected.shim_dir is None and selected.interpreter is None and selected.blocker is None
    output = repo / 'environment.json'
    argv = [sys.executable, '-c', "import json,os,pathlib;pathlib.Path('environment.json').write_text(json.dumps(os.environ['PATH']))"]
    result, valid, run = _run(repo, 'unchanged', argv)
    assert result.suite.exit_code == 0 and valid.ok
    assert json.loads(output.read_text()) == 'relative::/absolute:relative'
    assert not (run / '_interp_shim').exists()
