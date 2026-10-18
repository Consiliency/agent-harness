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


@pytest.mark.parametrize('outcome', ['skipped', 'xfailed'])
def test_qualification_refuses_nonpasses(outcome):
    from types import SimpleNamespace
    from _openshell_qualification import pytest_sessionfinish
    reporter = SimpleNamespace(stats={outcome: [object()]})
    manager = SimpleNamespace(get_plugin=lambda name: reporter)
    session = SimpleNamespace(config=SimpleNamespace(pluginmanager=manager), exitstatus=0)
    pytest_sessionfinish(session, 0)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
