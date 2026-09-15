"""Retained native directory-execution witnesses for agent-harness#428."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from phase_loop_runtime import verification_evidence as ve
from test_verification_venv_identity_428 import (
    IDENTITY, _assert_identity, _direct, _identity_argv, _repo, _run, _script, _venv,
)


def _pair(path, *, pip=False):
    (path / 'real/nested').mkdir(parents=True)
    physical = _venv(path / 'real/chosen', pip=pip)
    sibling = _venv(path / 'chosen', pip=pip)
    (path / 'link').symlink_to(path / 'real/nested', target_is_directory=True)
    return physical, sibling, path / 'link/../chosen/bin/python'


def _startup_log(physical, sibling, log):
    for python in (physical, sibling):
        site = Path(subprocess.check_output(
            [str(python), '-c', "import sysconfig;print(sysconfig.get_path('purelib'))"], text=True
        ).strip())
        (site / 'sitecustomize.py').write_text(
            'import json,os,sys\n'
            f'with open({str(log)!r},"a") as stream:\n'
            ' stream.write(json.dumps({"prefix":sys.prefix,"executable":sys.executable,'
            '"orig_argv":sys.orig_argv,"path":os.environ.get("PATH")})+"\\n")\n'
        )


def _rows(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def _probes(log):
    return [row for row in _rows(log) if any('sys.version_info[:3]' in part for part in row['orig_argv'])]


def _tree_argv(name, child, grandchild):
    code = IDENTITY + '\nimport subprocess\nsubprocess.run([sys.executable,"-c",' + repr(IDENTITY) + ',sys.argv[2]],check=True)\n'
    return [str(name), '-c', code, str(child), str(grandchild)]


def _assert_tree(child, grandchild, python):
    _assert_identity(child, python, (str(grandchild),))
    _assert_identity(grandchild, python)


def test_direct_directory_controls(tmp_path):
    physical, sibling, lexical = _pair(tmp_path / 'a')
    _direct(physical, tmp_path / 'physical.json')
    _direct(sibling, tmp_path / 'sibling.json')
    for label, name, path in (
        ('exact-lexical', lexical, lexical.parent),
        ('bare-lexical', 'python', lexical.parent),
        ('bare-physical', 'python', physical.parent),
    ):
        child, grandchild = tmp_path / (label + '.json'), tmp_path / (label + '-grandchild.json')
        process = subprocess.run(_tree_argv(name, child, grandchild), cwd=tmp_path,
                                 env={**os.environ, 'PATH': str(path)}, capture_output=True)
        (tmp_path / (label + '.stdout')).write_bytes(process.stdout)
        (tmp_path / (label + '.stderr')).write_bytes(process.stderr)
        assert process.returncode == 0, 'direct fixture execution must succeed'
        assert child.is_file() and grandchild.is_file()
        if label == 'bare-physical':
            _assert_tree(child, grandchild, physical)


def test_probe_argv_selects_physical_environment(tmp_path, monkeypatch):
    a, repo = tmp_path / 'a', _repo(tmp_path / 'b')
    physical, sibling, lexical = _pair(a)
    _direct(physical, a / 'physical-control.json')
    log = tmp_path / 'startup.jsonl'
    _startup_log(physical, sibling, log)
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', str(physical.parent))
    result, valid, _ = _run(repo, 'probe-argv', _identity_argv('python', repo / 'identity.json'), pin=str(lexical))
    assert result.suite.exit_code == 0 and valid.ok
    probes = _probes(log)
    assert probes and all(Path(row['prefix']).resolve() == physical.parent.parent for row in probes), 'version probe selected the sibling environment'
    _assert_identity(repo / 'identity.json', physical)


@pytest.mark.parametrize('alias', ['python', 'python3'])
def test_launcher_selects_physical_environment(tmp_path, monkeypatch, alias):
    a, repo = tmp_path / 'a', _repo(tmp_path / 'b')
    physical, _, lexical = _pair(a)
    _direct(physical, a / 'physical-control.json')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', str(physical.parent))
    output = repo / 'identity.json'
    result, valid, run = _run(repo, alias, _identity_argv(alias, output), pin=str(lexical))
    assert result.suite.exit_code == 0 and valid.ok
    _assert_identity(output, physical)
    assert (run / '_interp_shim' / alias).is_symlink()


def test_pip_location_and_execution_argv_agree_with_lexical_selection(tmp_path, monkeypatch):
    a, repo = tmp_path / 'a', _repo(tmp_path / 'b')
    physical, sibling, lexical = _pair(a, pip=True)
    for label, python in (('physical', physical), ('sibling', sibling)):
        control = subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True)
        (repo / (label + '-pip.stdout')).write_bytes(control.stdout)
        (repo / (label + '-pip.stderr')).write_bytes(control.stderr)
        assert control.returncode == 0 and str(python.parent.parent).encode() in control.stdout
    log = tmp_path / 'startup.jsonl'
    _startup_log(physical, sibling, log)
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', str(physical.parent))
    output = repo / 'identity.json'
    refresh = {'triggered': True, 'manifests': ['pyproject.toml'], 'install_argv': ['python', '-m', 'pip', '--version']}
    result, valid, run = _run(repo, 'pip', _identity_argv('python', output), pin=str(lexical), refresh=refresh)
    assert result.env_refresh.exit_code == 0 and result.suite.exit_code == 0 and valid.ok
    native_log = (run / 'verification.log').read_bytes()
    assert (repo / 'physical-pip.stdout').read_bytes().strip() in native_log, 'pip executed in the sibling environment'
    assert result.env_refresh.install_argv[0] == str(physical)
    assert str(lexical).encode() in native_log, 'declared lexical selection was lost from metadata'
    pip_rows = [row for row in _rows(log) if '-m' in row['orig_argv'] and 'pip' in row['orig_argv']]
    assert pip_rows and all(Path(row['prefix']) == physical.parent.parent for row in pip_rows)
    _assert_identity(output, physical)


def test_delegated_probe_path_selects_physical_environment(tmp_path, monkeypatch):
    a, repo = tmp_path / 'a', _repo(tmp_path / 'b')
    physical, sibling, lexical = _pair(a)
    for python in (physical, sibling):
        (python.parent / 'ah428_delegate').symlink_to('python')
    log = tmp_path / 'startup.jsonl'
    _startup_log(physical, sibling, log)
    wrapper = _script(tmp_path / 'wrappers/python-boundary-probe', 'exec ah428_delegate "$@"\n')
    control = subprocess.run([str(wrapper), '-c', "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
                             cwd=repo, env={**os.environ, 'PATH': str(physical.parent)}, capture_output=True)
    (repo / 'direct-probe.stdout').write_bytes(control.stdout)
    (repo / 'direct-probe.stderr').write_bytes(control.stderr)
    assert control.returncode == 0
    assert Path(_probes(log)[0]['prefix']) == physical.parent.parent
    before = len(_rows(log))
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', str(lexical.parent))
    output = repo / 'identity.json'
    result, valid, _ = _run(repo, 'delegated', _identity_argv('python', output), pin=str(wrapper))
    assert result.suite.exit_code == 0 and valid.ok
    delegated = [row for row in _rows(log)[before:] if Path(row['executable']).name == 'ah428_delegate'
                 and any('sys.version_info[:3]' in part for part in row['orig_argv'])]
    assert delegated and all(Path(row['prefix']).resolve() == physical.parent.parent for row in delegated), 'delegated probe PATH selected the sibling environment'
    _assert_identity(output, physical)


@pytest.mark.parametrize('path_kind', ['relative', 'absolute'])
@pytest.mark.parametrize('alias', ['python', 'python3', 'versioned'])
def test_unredirected_path_preserves_child_and_grandchild(tmp_path, monkeypatch, path_kind, alias):
    a, b = tmp_path / 'a', tmp_path / 'b'
    physical, _, lexical = _pair(a)
    other, _, _ = _pair(b)
    repo = _repo(b)
    _direct(physical, a / 'physical-control.json')
    _direct(other, b / 'physical-control.json')
    monkeypatch.chdir(a)
    monkeypatch.setenv('PATH', 'link/../chosen/bin' if path_kind == 'relative' else str(lexical.parent))
    name = f'python3.{sys.version_info.minor}' if alias == 'versioned' else alias
    child, grandchild = repo / 'child.json', repo / 'grandchild.json'
    result, valid, run = _run(repo, 'unredirected', _tree_argv(name, child, grandchild))
    assert result.suite.exit_code == 0 and valid.ok
    assert not (run / '_interp_shim/_selected_python').exists(), 'witness must bypass the bare launcher'
    assert not (run / '_interp_shim' / name).exists(), 'witness must be an unredirected name'
    _assert_tree(child, grandchild, physical)


def test_equal_override_and_later_process_use_current_directory_anchors(tmp_path, monkeypatch):
    a, b, c = (tmp_path / name for name in ('a', 'b', 'c'))
    physical_a, _, lexical_a = _pair(a)
    physical_b, _, _ = _pair(b)
    physical_c, _, _ = _pair(c)
    repo = _repo(b)
    for root, python in ((a, physical_a), (b, physical_b), (c, physical_c)):
        _direct(python, root / 'physical-control.json')
    monkeypatch.chdir(a)
    relative = 'link/../chosen/bin'
    monkeypatch.setenv('PATH', relative)
    initial = repo / 'initial.json'
    result, valid, run = _run(repo, 'initial', _identity_argv('python', initial), pin=str(lexical_a))
    assert result.suite.exit_code == 0 and valid.ok
    artifact = run / 'verification.json'
    before_artifact, before_log = artifact.read_bytes(), (run / 'verification.log').read_bytes()
    versioned = f'python3.{sys.version_info.minor}'
    commands = [
        _tree_argv('python', repo / 'pin-child.json', repo / 'pin-grandchild.json'),
        _tree_argv(versioned, repo / 'inherited-child.json', repo / 'inherited-grandchild.json'),
        ['PATH=' + relative, *_tree_argv(versioned, repo / 'override-child.json', repo / 'override-grandchild.json')],
    ]
    code = 'from pathlib import Path;from phase_loop_runtime.verification_evidence import _append_verification_command;import json,sys\nfor argv in json.loads(sys.argv[3]):\n result=_append_verification_command(Path(sys.argv[1]),Path(sys.argv[2]),argv,60);assert result.exit_code==0\n'
    environment = {**os.environ, 'PATH': relative, 'PYTHONPATH': str(Path(ve.__file__).resolve().parent.parent)}
    process = subprocess.run([sys.executable, '-c', code, str(repo), str(artifact), json.dumps(commands)],
                             cwd=c, env=environment, capture_output=True)
    (run / 'append.stdout').write_bytes(process.stdout)
    (run / 'append.stderr').write_bytes(process.stderr)
    assert process.returncode == 0
    assert ve.validate_verification_artifact(artifact).ok
    assert artifact.read_bytes() != before_artifact and (run / 'verification.log').read_bytes() != before_log
    assert len(json.loads(artifact.read_text())['commands']) == 3
    _assert_identity(initial, physical_a)
    for label, python in (('pin', physical_a), ('inherited', physical_c), ('override', physical_b)):
        _assert_tree(repo / (label + '-child.json'), repo / (label + '-grandchild.json'), python)


@pytest.mark.parametrize('kind', ['missing', 'loop', 'non-directory', 'permission-denied'])
def test_invalid_directory_does_not_admit_candidate(tmp_path, monkeypatch, kind):
    repo = _repo(tmp_path / 'repo')
    selected = _venv(tmp_path / 'selected')
    _direct(selected, tmp_path / 'selected-control.json')
    (selected.parent.parent / 'walk').mkdir()
    monkeypatch.setenv('PATH', str(selected.parent.parent / 'walk/../bin'))
    result, valid, _ = _run(repo, 'traversable-control', _identity_argv('python', repo / 'control.json'))
    assert result.suite.exit_code == 0 and valid.ok
    _assert_identity(repo / 'control.json', selected)
    root = tmp_path / 'path'
    root.mkdir()
    component = root / 'component'
    if kind == 'loop':
        component.symlink_to('component')
    elif kind == 'non-directory':
        target = root / 'regular-file'
        target.write_text('not a directory')
        component.symlink_to(target)
    elif kind == 'permission-denied':
        assert os.getuid() == os.geteuid() and os.geteuid() != 0, 'denial must be effective for the acceptance UID'
        component.mkdir()
        component.chmod(0)
    name = f'python3.{sys.version_info.minor}'
    effect = tmp_path / 'unexpected-candidate-effect'
    candidate = _script(root / 'existing-bin' / name,
                        f'case "$*" in *sys.version_info*) exit 23;; esac\n: > {shlex.quote(str(effect))}\n')
    entry = root / 'component/../existing-bin'
    modes = {'kind': kind, 'uid': os.geteuid(), 'denied_mode': 0 if kind == 'permission-denied' else None}
    try:
        with pytest.raises(OSError) as denied:
            os.stat(entry)
        modes['traversal_errno'] = denied.value.errno
        if kind == 'permission-denied':
            assert denied.value.errno == 13 and not os.access(entry, os.X_OK)
        monkeypatch.setenv('PATH', str(entry))
        assert ve._interpreter_path(name) is None
        assert candidate.is_file()
        result, valid, run = _run(repo, 'invalid', [name], pin=str(selected))
        assert not effect.exists(), 'directory conversion admitted a previously undiscovered candidate'
        assert result.suite.exit_code != 0 and not valid.ok
        assert (run / 'verification.json').is_file() and (run / 'verification.log').is_file()
    finally:
        if kind == 'permission-denied':
            component.chmod(0o700)
            modes['archival_mode'] = component.stat().st_mode & 0o777
        (tmp_path / 'traversal-observation.json').write_text(json.dumps(modes, indent=2))


def test_resolution_runtime_error_preserves_native_failure(tmp_path, monkeypatch):
    repo = _repo(tmp_path / 'repo')
    selected = _venv(tmp_path / 'selected')
    _direct(selected, tmp_path / 'selected-control.json')
    (selected.parent.parent / 'walk').mkdir()
    directory = selected.parent.parent / 'walk/../bin'
    monkeypatch.setenv('PATH', str(directory))
    original_resolve = Path.resolve
    injections = []

    def resolution_failure(path, *args, **kwargs):
        if path == directory:
            injections.append(str(path))
            raise RuntimeError('fixture: directory resolution unavailable')
        return original_resolve(path, *args, **kwargs)

    output = repo / 'child-path.json'
    command = [str(selected), '-c', 'import json,os,pathlib,sys;pathlib.Path(sys.argv[1]).write_text(json.dumps(os.environ["PATH"]));sys.exit(23)', str(output)]
    with monkeypatch.context() as limited:
        limited.setattr(Path, 'resolve', resolution_failure)
        result, valid, run = _run(repo, 'resolution-error', command, pin=str(selected))
    (tmp_path / 'resolution-injections.json').write_text(json.dumps({'paths': injections, 'source_sha256': __import__('hashlib').sha256(Path(ve.__file__).read_bytes()).hexdigest()}, indent=2))
    assert result.suite.exit_code == 23 and not valid.ok
    assert json.loads(output.read_text()) == str(run / '_interp_shim') + os.pathsep + str(directory)
    assert (run / 'verification.json').is_file() and (run / 'verification.log').is_file()


def test_absolute_path_strings_survive_probe_and_guarded_child(tmp_path, monkeypatch):
    repo = _repo(tmp_path / 'repo')
    physical, sibling, _ = _pair(tmp_path / 'a')
    _direct(physical, tmp_path / 'physical-control.json')
    log = tmp_path / 'startup.jsonl'
    _startup_log(physical, sibling, log)
    entry = str(physical.parent) + '//./'
    raw = entry + os.pathsep + entry
    monkeypatch.setenv('PATH', raw)
    output = repo / 'identity.json'
    result, valid, run = _run(repo, 'path-strings', _identity_argv('python', output), pin=str(physical))
    assert result.suite.exit_code == 0 and valid.ok
    _assert_identity(output, physical)
    probes = _probes(log)
    assert probes and all(row['path'] == raw for row in probes), 'version probe changed absolute PATH entry spelling or order'
    suite = [row for row in _rows(log) if str(output) in row['orig_argv']]
    assert suite and all(row['path'] == str(run / '_interp_shim') + os.pathsep + raw for row in suite), 'guarded child changed absolute PATH entry spelling or order'
