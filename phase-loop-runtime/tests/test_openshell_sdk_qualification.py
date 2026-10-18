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
    root = tmp_path / 'source'
    (root / 'scripts').mkdir(parents=True)
    (root / 'tests').mkdir()
    (root / 'tests' / '_openshell_qualification.py').write_bytes(
        Path(__file__).with_name('_openshell_qualification.py').read_bytes())
    (root / 'scripts' / 'qualify_openshell_sdk.py').write_bytes(SCRIPT.read_bytes())
    (root / 'tests' / 'test_case.py').write_text('def test_ok(): pass\n')
    generator = '''import pathlib, sys
out = pathlib.Path(next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--python_out=')))
(out / 'sdk.py').write_bytes(b'sdk')
if pathlib.Path(__file__).with_name('tamper').exists():
    pathlib.Path(__file__).parents[1].joinpath('runtime.py').write_bytes(b'changed')
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
    state = {'tamper': False, 'pytest_called': False, 'dirty': False}

    def output(argv, **kwargs):
        if 'show' in argv:
            return b'proto'
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
            if state['tamper']:
                (target / 'grpc_tools' / 'tamper').touch()
            return subprocess.CompletedProcess(argv, 0)
        if 'tests/test_openshell_transport.py' in argv:
            state['pytest_called'] = True
            argv = argv[:-3] + ['tests/test_case.py']
        return real_run(argv, **kwargs)

    monkeypatch.setattr(recipe.subprocess, 'check_output', output)
    monkeypatch.setattr(recipe.subprocess, 'run', run)
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
