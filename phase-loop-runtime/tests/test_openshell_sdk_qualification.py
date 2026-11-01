"""Qualification input refusals, independent of an installed generated SDK."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'qualify_openshell_sdk.py'
spec = importlib.util.spec_from_file_location('qualification_recipe', SCRIPT)
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)



@pytest.mark.parametrize('name', ['openshell.proto', 'openshell_pb2.py', 'approved.whl'])
def test_missing_and_corrupt_bytes_refused(tmp_path, name):
    pins = {name: hashlib.sha256(b'reviewed bytes').hexdigest()}
    with pytest.raises(ValueError, match='missing or mismatched'):
        recipe.verify(tmp_path, pins)
    (tmp_path / name).write_bytes(b'reviewed bytes')
    recipe.verify(tmp_path, pins)
    (tmp_path / name).write_bytes(b'corrupt bytes')
    with pytest.raises(ValueError, match='missing or mismatched'):
        recipe.verify(tmp_path, pins)


def test_explicit_pytest_mode_refuses_missing_sdk(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1')
    env.pop('OPENSHELL_GENERATED_DIR', None)
    env.pop('PYTEST_ADDOPTS', None)
    result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider',
                             '-p', '_openshell_qualification', str(tmp_path)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert 'qualification requires OPENSHELL_GENERATED_DIR' in result.stderr


@pytest.mark.parametrize('state', ['corrupt', 'missing'])
def test_explicit_pytest_mode_refuses_bad_sdk(tmp_path, state):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent),
               OPENSHELL_GENERATED_DIR=str(tmp_path / 'sdk'),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTEST_ADDOPTS', None)
    if state == 'corrupt':
        import json
        sdk = tmp_path / 'sdk'
        sdk.mkdir()
        for name in json.loads(recipe.MANIFEST.read_text())['generated_outputs']:
            (sdk / name).write_bytes(b'corrupted')
    result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider',
                             '-p', '_openshell_qualification', str(tmp_path)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert 'missing or mismatched qualification input' in result.stderr


@pytest.mark.parametrize('outcome', ['skipped', 'xfailed', 'xpassed'])
def test_qualification_refuses_nonpasses(outcome):
    from types import SimpleNamespace
    from _openshell_qualification import pytest_sessionfinish
    reporter = SimpleNamespace(stats={outcome: [object()]})
    manager = SimpleNamespace(get_plugin=lambda name: reporter)
    session = SimpleNamespace(config=SimpleNamespace(pluginmanager=manager), exitstatus=0)
    pytest_sessionfinish(session, 0)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


@pytest.fixture
def qualification_run(tmp_path, monkeypatch):
    """Exercise recipe subprocess startup with tiny local wheel/source inputs."""
    import io
    import json
    import zipfile
    root = tmp_path / 'source' / 'phase-loop-runtime'
    (root / 'scripts').mkdir(parents=True)
    (root / 'tests').mkdir()
    (root / 'tests' / '_openshell_qualification.py').write_bytes(
        Path(__file__).with_name('_openshell_qualification.py').read_bytes())
    (root / 'scripts' / 'qualify_openshell_sdk.py').write_bytes(SCRIPT.read_bytes())
    (root / 'tests' / 'test_case.py').write_text('def test_ok(): pass\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
    generator = '''import pathlib, sys
out = pathlib.Path(next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--python_out=')))
(out / 'sdk.py').write_bytes(b'sdk')
'''
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, 'w') as archive:
        for name, data in {'grpc_tools/__init__.py': '', 'grpc_tools/protoc.py': generator,
                           'runtime.py': 'original'}.items():
            archive.writestr(name, data)
    digest = lambda b: hashlib.sha256(b).hexdigest()
    manifest = dict(python=recipe.platform.python_version(),
                    platform=f'{sys.platform}-{recipe.platform.machine()}', server_commit='server',
                    proto_inputs={'test.proto': digest(b'proto')}, generator_inputs={},
                    generated_outputs={'sdk.py': digest(b'sdk')},
                    wheels={'fixture': dict(version='1', filename='fixture.whl', url='https://fixture',
                                            sha256=digest(wheel.getvalue()))})
    manifest_path = root / 'scripts' / recipe.MANIFEST.name
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(recipe, 'ROOT', root)
    monkeypatch.setattr(recipe, 'MANIFEST', manifest_path)
    monkeypatch.setattr(recipe.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(wheel.getvalue()))
    real_run = subprocess.run
    real_output = subprocess.check_output
    state = {'tamper': False, 'pytest_called': False, 'dirty': False}

    def output(argv, **kwargs):
        if 'show' in argv:
            return b'proto'
        if argv[0] == 'git' and state.get('real_git'):
            return real_output(argv, **kwargs)
        if 'status' in argv:
            return b' M tracked.py' if state['dirty'] else b''
        if '--version' in argv:
            return b'uv fixture\n'
        return b'tree\n' if 'HEAD^{tree}' in argv else b'commit\n'

    def run(argv, **kwargs):
        if argv[0] == 'uv':
            target = Path(argv[argv.index('--target') + 1])
            with zipfile.ZipFile(io.BytesIO(wheel.getvalue())) as archive:
                archive.extractall(target)
            return subprocess.CompletedProcess(argv, 0)
        if 'tests/test_openshell_transport.py' in argv:
            state['pytest_called'] = True
            argv = argv[:argv.index('tests/test_openshell_transport.py')] + ['tests/test_case.py']
        result = real_run(argv, **kwargs)
        if 'tests/test_case.py' in argv and state.get('after_pytest'):
            state['after_pytest']()
        if any('grpc_tools.protoc' in str(arg) for arg in argv):
            if state['tamper']:
                (work / 'deps' / 'runtime.py').write_bytes(b'changed')
            if state.get('after_generation'):
                state['after_generation'](work / 'deps')
        return result

    monkeypatch.setattr(recipe.subprocess, 'check_output', output)
    monkeypatch.setattr(recipe.subprocess, 'run', run)
    # uv is simulated by `run`/`output` above, so satisfy only its PATH prerequisite.
    # git and openssl keep real resolution; the real recipe stays strict about all three.
    real_which = recipe.shutil.which
    monkeypatch.setattr(recipe.shutil, 'which',
                        lambda cmd, *a, **kw: '/fixture/bin/uv' if cmd == 'uv' else real_which(cmd, *a, **kw))
    work = tmp_path / 'work'
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--server', str(tmp_path), '--work', str(work)])
    return state, work, root


def test_caller_directory_is_independent(qualification_run, tmp_path, monkeypatch):
    _, work, _ = qualification_run
    shadow = tmp_path / 'grpc_tools'
    shadow.mkdir()
    (shadow / '__init__.py').write_text('')
    (shadow / 'protoc.py').write_text("raise RuntimeError('caller generator loaded')")
    (tmp_path / 'sitecustomize.py').write_text("raise RuntimeError('caller startup loaded')")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PYTHONPATH', str(tmp_path))
    recipe.main()
    assert (work / 'qualification-receipt.json').is_file()


def test_explicit_plugin_selection(qualification_run, monkeypatch):
    _, work, root = qualification_run
    (root / 'tests' / 'ambient_plugin.py').write_text("raise RuntimeError('ambient plugin loaded')")
    monkeypatch.setenv('PYTEST_PLUGINS', 'ambient_plugin')
    monkeypatch.setenv('PYTEST_ADDOPTS', '--collect-only')
    recipe.main()
    assert (work / 'qualification-receipt.json').is_file()


def test_installed_bytes_rechecked_after_generation(qualification_run):
    state, work, _ = qualification_run
    state['tamper'] = True
    with pytest.raises(ValueError, match='runtime.py'):
        recipe.main()
    assert not state['pytest_called']
    assert not (work / 'qualification-receipt.json').exists()


def test_receipt_records_observed_run(qualification_run):
    import json
    _, work, _ = qualification_run
    recipe.main()
    receipt = json.loads((work / 'qualification-receipt.json').read_text())
    assert receipt['source'] == {'commit': 'commit', 'tree': 'tree'}
    assert receipt['interpreter']['path'] == sys.executable
    assert receipt['interpreter']['version'] == recipe.platform.python_version()
    assert receipt['uv_version'] == 'uv fixture'
    assert receipt['tests'] == dict(collected=1, passed=1, failed=0, errors=0,
                                    skipped=0, xfailed=0, xpassed=0, exitstatus=0)
    assert receipt['hashes']['installed']['runtime.py'] == hashlib.sha256(b'original').hexdigest()
    assert receipt['hashes']['generated']['sdk.py'] == hashlib.sha256(b'sdk').hexdigest()
    assert receipt['manifest_sha256'] == hashlib.sha256(recipe.MANIFEST.read_bytes()).hexdigest()
    assert receipt['server_commit'] == 'server'
    assert receipt['completed_at']


def test_dirty_source_refuses_receipt(qualification_run):
    state, work, _ = qualification_run
    state['dirty'] = True
    with pytest.raises(ValueError, match='dirty'):
        recipe.main()
    assert not (work / 'qualification-receipt.json').exists()


@pytest.mark.parametrize('level', [0, 1, 2])
@pytest.mark.parametrize('name', ['conftest.py', 'pytest.ini', '.pytest.ini', 'tox.ini', 'setup.cfg'])
def test_pytest_discovery_is_bounded(qualification_run, level, name):
    _, work, root = qualification_run
    ancestor = [root, root.parent, root.parent.parent][level]
    marker = work.parent / 'ancestor-ran'
    payload = f'from pathlib import Path; Path({str(marker)!r}).touch(); raise RuntimeError("ancestor loaded")\n'
    if name == 'conftest.py':
        content = payload
    else:
        (ancestor / 'ancestor_plugin.py').write_text(payload)
        section = 'tool:pytest' if name == 'setup.cfg' else 'pytest'
        content = f'[{section}]\npythonpath = {ancestor}\naddopts = -p ancestor_plugin\n'
    (ancestor / name).write_text(content)
    # Model the real packaged tests, including a potentially importable parent.
    (root / 'tests' / '__init__.py').write_text('')
    (root / '__init__.py').write_text(payload)
    (root / 'tests' / 'conftest.py').write_text(
        'import pytest\n@pytest.fixture\ndef bounded_fixture(): return 42\n')
    (root / 'tests' / 'test_case.py').write_text(
        'import sys\ndef test_ok(bounded_fixture):\n'
        '    assert bounded_fixture == 42\n'
        f'    assert not set({[str(root), str(root.parent), str(root.parent.parent)]!r}) & set(sys.path)\n')
    recipe.main()
    assert (work / 'qualification-receipt.json').is_file()
    assert not marker.exists()


@pytest.fixture
def qualification_git(qualification_run):
    state, work, root = qualification_run
    (root / 'src').mkdir()
    (root / 'src' / 'tracked.py').write_text('')
    (root.parent / '.gitignore').write_text('*.py[cod]\n')
    for args in (['init'], ['add', '.'],
                 ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                  'commit', '-m', 'fixture']):
        subprocess.run(['git', '-C', str(root.parent), *args], check=True,
                       capture_output=True, timeout=20)
    state['real_git'] = True
    return state, work, root


@pytest.mark.parametrize('stage', ['start', 'generation', 'end'])
@pytest.mark.parametrize('relative,ignore', [
    (f'{directory}/pytest.pyc' if ignore == 'repository' else f'{directory}/pytest.py', ignore)
    for directory in ('src', 'tests', 'scripts')
    for ignore in ('repository', 'global', 'info')
] + [('_quarantine.pyc', 'repository'), ('conftest.py', 'global'), ('pytest.ini', 'global')])
def test_ignored_import_files_refuse_receipt(qualification_git, monkeypatch, stage, relative, ignore):
    import marshal
    state, work, root = qualification_git
    target = root / relative
    marker = root.parent / 'shadow-ran'
    payload = (f'from pathlib import Path; Path({str(marker)!r}).touch()\n'
               'import json, os\n'
               'Path(os.environ["OPENSHELL_TEST_RESULTS"]).write_text(json.dumps('
               'dict(collected=265, passed=265, exitstatus=0)))\n')
    if ignore == 'repository':
        content = (importlib.util.MAGIC_NUMBER + b'\0' * 12 +
                   marshal.dumps(compile(payload, str(target), 'exec')))
    else:
        content = payload.encode()
        excludes = root.parent / ('.git/info/exclude' if ignore == 'info' else 'global-ignore')
        excludes.write_text(f'/phase-loop-runtime/{relative}\n')
        if ignore == 'global':
            excludes.rename(work.parent / 'global-ignore')
            home = work.parent / 'home'
            home.mkdir()
            monkeypatch.setenv('HOME', str(home))
            monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(home / '.gitconfig'))
            subprocess.run(['git', '-C', str(root), 'config', '--global', 'core.excludesFile',
                            str(work.parent / 'global-ignore')], check=True, timeout=20)

    def plant(*args):
        target.write_bytes(content)
        assert not subprocess.check_output(
            ['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=all'])

    if stage == 'start':
        plant()
    else:
        state['after_generation' if stage == 'generation' else 'after_pytest'] = plant
    with pytest.raises(ValueError, match='dirty qualification import paths'):
        recipe.main()
    assert state['pytest_called'] == (stage == 'end')
    assert not (work / 'qualification-receipt.json').exists()
    assert not marker.exists()
    assert target.read_bytes() == content  # Refusal must not delete user files.


@pytest.mark.parametrize('stage', ['start', 'generation', 'end'])
@pytest.mark.parametrize('name', ['tracked.py', 'untracked.py'])
def test_changed_import_files_refuse_receipt(qualification_git, stage, name):
    state, work, root = qualification_git

    def plant(*args):
        (root / 'src' / name).write_text('changed = True\n')

    if stage == 'start':
        plant()
    else:
        state['after_generation' if stage == 'generation' else 'after_pytest'] = plant
    with pytest.raises(ValueError, match='dirty qualification source'):
        recipe.main()
    assert state['pytest_called'] == (stage == 'end')
    assert not (work / 'qualification-receipt.json').exists()


@pytest.mark.parametrize('entry', ['extra', 'symlink', 'directory_symlink'])
def test_exact_sdk_entries(qualification_run, entry):
    _, work, _ = qualification_run
    recipe.main()
    sdk = work / 'generated'
    if entry == 'extra':
        (sdk / 'grpc.py').write_text('')
    elif entry == 'symlink':
        (work / 'same-bytes.py').write_bytes((sdk / 'sdk.py').read_bytes())
        (sdk / 'sdk.py').unlink()
        (sdk / 'sdk.py').symlink_to(work / 'same-bytes.py')
    else:
        alias = work / 'sdk-alias'
        alias.symlink_to(sdk, target_is_directory=True)
        sdk = alias
    import json
    with pytest.raises(ValueError):
        recipe.verify(sdk, json.loads(recipe.MANIFEST.read_text())['generated_outputs'], exact=True)


@pytest.mark.parametrize('body', [
    'import pytest\ndef test_case(): pytest.skip("fixture")\n',
    'import pytest\n@pytest.mark.xfail\ndef test_case(): assert False\n',
    'import pytest\n@pytest.mark.xfail\ndef test_case(): pass\n',
    'def test_case(): assert False\n',
])
def test_unsuccessful_run_has_no_receipt(qualification_run, body):
    _, work, root = qualification_run
    (root / 'tests' / 'test_case.py').write_text(body)
    with pytest.raises(subprocess.CalledProcessError):
        recipe.main()
    assert not (work / 'qualification-receipt.json').exists()


@pytest.mark.parametrize('name', ['pytest.py', 'phase_loop_runtime/__init__.py',
                                  '_openshell_qualification.py'])
def test_installed_inventory_rechecked(qualification_run, name):
    state, work, _ = qualification_run

    def add(deps):
        path = deps / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('raise RuntimeError("unexpected module")')

    state['after_generation'] = add
    with pytest.raises(ValueError, match='unexpected qualification input'):
        recipe.main()
    assert not state['pytest_called']
    assert not (work / 'qualification-receipt.json').exists()


@pytest.mark.parametrize('change', ['remove', 'file_symlink', 'directory_symlink', 'metadata'])
def test_installed_tree_changes_refused(qualification_run, change):
    state, work, _ = qualification_run

    def alter(deps):
        if change == 'metadata':
            (deps / '.lock').write_text('new metadata')
        elif change == 'directory_symlink':
            (deps / 'grpc_tools').rename(work / 'moved')
            (deps / 'grpc_tools').symlink_to(work / 'moved', target_is_directory=True)
        else:
            (deps / 'runtime.py').unlink()
            if change == 'file_symlink':
                (work / 'same.py').write_text('original')
                (deps / 'runtime.py').symlink_to(work / 'same.py')

    state['after_generation'] = alter
    with pytest.raises(ValueError):
        recipe.main()
    assert not state['pytest_called']
    assert not (work / 'qualification-receipt.json').exists()


@pytest.mark.parametrize('module', ['grpc_tools.protoc', 'pytest'])
def test_child_uses_fresh_cache(tmp_path, monkeypatch, module):
    import importlib.util
    import marshal
    source = tmp_path / 'source'
    source.mkdir()
    path = source.joinpath(*module.split('.')).with_suffix('.py')
    path.parent.mkdir(exist_ok=True)
    if '.' in module:
        (path.parent / '__init__.py').write_text('')
    path.write_text('print("source executed")')
    poisoned = (importlib.util.MAGIC_NUMBER + (1).to_bytes(4, 'little') +
                importlib.util.source_hash(path.read_bytes()) +
                marshal.dumps(compile('raise RuntimeError("cached code executed")', str(path), 'exec')))
    monkeypatch.setattr(sys, 'pycache_prefix', None)
    local_cache = Path(importlib.util.cache_from_source(str(path)))
    local_cache.parent.mkdir(exist_ok=True)
    local_cache.write_bytes(poisoned)
    work = tmp_path / 'work'
    work.mkdir()
    # A predictable cache under the chosen work directory must not be reused.
    old_prefix = work / 'pycache'
    prefix_cache = old_prefix / str(path.parent).lstrip('/') / local_cache.name
    prefix_cache.parent.mkdir(parents=True)
    prefix_cache.write_bytes(poisoned)
    command = recipe.python_command([source], module, work)
    baseline = subprocess.run(command[:3] + command[5:], capture_output=True,
                              text=True, timeout=20)
    assert baseline.returncode != 0
    assert 'cached code executed' in baseline.stderr
    next_command = recipe.python_command([source], module, work)
    assert command[4] != next_command[4]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    assert result.stdout.strip() == 'source executed'


@pytest.mark.parametrize('entry', ['pytest.py', 'runtime.py', 'runtime.pyc',
                                   'fixture.dist-info/extra.py', '.lock'])
def test_install_snapshot_is_wheel_bound(tmp_path, entry):
    tmp_path = tmp_path / 'deps'
    tmp_path.mkdir()
    (tmp_path / 'runtime.py').write_bytes(b'original')
    payload = {'runtime.py': hashlib.sha256(b'original').hexdigest()}
    snapshot = recipe.installed_tree(tmp_path, payload)
    path = tmp_path / entry
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b'changed')
    if entry == '.lock':
        snapshot = recipe.installed_tree(tmp_path, payload)
        path.write_bytes(b'changed again')
    else:
        with pytest.raises(ValueError):
            recipe.installed_tree(tmp_path, payload)
    with pytest.raises(ValueError):
        recipe.installed_tree(tmp_path, payload, snapshot)
