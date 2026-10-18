"""Explicit, fail-closed local SDK qualification; never activates offload."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

MANIFEST = Path(__file__).with_name('openshell-sdk-manifest.json')
ROOT = Path(__file__).resolve().parents[1]
# Authoritative wall-clock limits in seconds for this bounded recipe.
TIMEOUTS = dict(git=30, uv=120, protoc=60, pytest=180, download=60)


def verify(directory, pins, *, exact=False):
    if directory.is_symlink():
        raise ValueError('symlinked qualification directory')
    observed = {}
    for name, expected in pins.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'missing or mismatched qualification input: {name}')
        observed[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed[name] != expected:
            raise ValueError(f'missing or mismatched qualification input: {name}')
    if exact and {p.name for p in directory.iterdir()} != set(pins):
        raise ValueError('unexpected qualification input entries')
    return observed


def wheel_payload(wheels, manifest):
    # Expected bytes come from verified archives, never an installed-tree snapshot.
    expected = {}
    for wheel in manifest['wheels'].values():
        verify(wheels, {wheel['filename']: wheel['sha256']})
        with zipfile.ZipFile(wheels / wheel['filename']) as archive:
            for entry in archive.infolist():
                if entry.is_dir() or len(Path(entry.filename).parts) == 2 and entry.filename.endswith('.dist-info/RECORD'):
                    continue  # uv rewrites RECORD during installation.
                name = entry.filename
                if Path(name).is_absolute() or '..' in Path(name).parts or '.data' in name.split('/'):
                    raise ValueError(f'unsupported wheel layout: {name}')
                expected[name] = hashlib.sha256(archive.read(entry)).hexdigest()
    return expected


def installed_tree(directory, payload, snapshot=None):
    # Only installer-owned additions may supplement the verified wheel payload.
    allowed = {'.lock'}
    for name in payload:
        parts = Path(name).parts
        if len(parts) == 2 and parts[0].endswith('.dist-info'):
            allowed.update(f'{parts[0]}/{leaf}' for leaf in
                           ('RECORD', 'INSTALLER', 'REQUESTED', 'uv_cache.json'))
    if 'grpc_tools/protoc.py' in payload:
        allowed.add('bin/python-grpc-tools-protoc')
    names = set(payload) | allowed if snapshot is None else set(snapshot)
    directories = {str(parent) for name in names for parent in Path(name).parents
                   if str(parent) != '.'}
    observed = {}
    if directory.is_symlink():
        raise ValueError('symlinked qualification directory')
    for path in directory.rglob('*'):
        name = str(path.relative_to(directory))
        if path.is_symlink():
            raise ValueError(f'symlinked qualification input: {name}')
        if path.is_dir() and name in directories:
            continue
        if not path.is_file() or name not in names:
            raise ValueError(f'unexpected qualification input: {name}')
        observed[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    verify(directory, payload)
    if snapshot is not None and observed != snapshot:
        raise ValueError('installed qualification file set or bytes changed')
    return observed


def source_identity(env):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args], env=env,
                                       timeout=TIMEOUTS['git']).decode().strip()
    if git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('dirty qualification source; commit changes before qualification')
    if git('status', '--porcelain', '--ignored', '--untracked-files=all',
           '--', 'src', 'tests', 'scripts'):
        raise ValueError('dirty qualification import paths; use a clean worktree without ignored files in src, tests or scripts')
    return dict(commit=git('rev-parse', 'HEAD'), tree=git('rev-parse', 'HEAD^{tree}'))


def python_command(paths, module, work):
    # -I excludes caller CWD/PYTHON* and user site; shared interpreter site remains
    # an explicit prerequisite. Add only this stage's controlled import paths.
    cache = tempfile.mkdtemp(prefix='pycache-', dir=work)
    return [sys.executable, '-I', '-B', '-X', f'pycache_prefix={cache}', '-c',
            f'import runpy, sys; sys.path[:0] = {list(map(str, paths))!r}; '
            f'runpy.run_module({module!r}, run_name="__main__")']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True, help='read-only OpenShell Git repository')
    parser.add_argument('--work', type=Path, required=True, help='new private directory (must not exist)')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if platform.python_version() != manifest['python'] or f'{sys.platform}-{platform.machine()}' != manifest['platform']:
        parser.error('interpreter/platform differs from reviewed manifest')
    for command in ('git', 'uv', 'openssl'):
        if not shutil.which(command):
            parser.error(f'missing prerequisite: {command}')
    # Inherited Python/pytest/uv/git startup options are deliberately not forwarded.
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG') if key in os.environ}
    source = source_identity(env)
    uv_version = subprocess.check_output(['uv', '--version'], env=env, timeout=TIMEOUTS['uv']).decode().strip()
    # Test dependencies belong to the caller's read-only environment.
    import pytest  # noqa: F401
    work = args.work.resolve()
    work.mkdir(mode=0o700)
    env.update(PYTHONDONTWRITEBYTECODE='1', UV_CACHE_DIR=str(work / 'uv-cache'))
    hashes = {}
    proto, wheels, deps, generated = [work / p for p in ('proto', 'wheels', 'deps', 'generated')]
    for directory in (proto, wheels, generated):
        directory.mkdir()
    for name in manifest['proto_inputs']:
        content = subprocess.check_output(['git', '-C', str(args.server), 'show',
                                          f"{manifest['server_commit']}:proto/{name}"],
                                          env=env, timeout=TIMEOUTS['git'])
        (proto / name).write_bytes(content)
    hashes['proto'] = verify(proto, manifest['proto_inputs'])
    hashes['wheels'] = {}
    requirements = []
    for name, wheel in manifest['wheels'].items():
        with urllib.request.urlopen(wheel['url'], timeout=TIMEOUTS['download']) as response:
            (wheels / wheel['filename']).write_bytes(response.read())
        hashes['wheels'].update(verify(wheels, {wheel['filename']: wheel['sha256']}))
        requirements.append(f"{name}=={wheel['version']} --hash=sha256:{wheel['sha256']}")
    lock = work / 'requirements.txt'
    lock.write_text('\n'.join(requirements) + '\n')
    expected = wheel_payload(wheels, manifest)
    subprocess.run(['uv', 'pip', 'install', '--no-cache', '--no-index', '--find-links', str(wheels),
                    '--require-hashes', '--only-binary=:all:', '--python', sys.executable,
                    '--target', str(deps), '-r', str(lock)], env=env, cwd=work,
                   check=True, timeout=TIMEOUTS['uv'])
    installed = installed_tree(deps, expected)
    hashes['generator'] = verify(deps, manifest['generator_inputs'])
    subprocess.run(python_command([deps], 'grpc_tools.protoc', work) + ['-I', str(proto),
                    f'--python_out={generated}', f'--grpc_python_out={generated}',
                    f'--descriptor_set_out={generated / "openshell.desc"}', '--include_imports',
                    *map(str, sorted(proto.glob('*.proto')))], cwd=work, env=env,
                   check=True, timeout=TIMEOUTS['protoc'])
    hashes['generated'] = verify(generated, manifest['generated_outputs'], exact=True)
    env.update(OPENSHELL_GENERATED_DIR=str(generated), OPENSHELL_SDK_QUALIFICATION='1',
               OPENSHELL_TEST_RESULTS=str(work / 'test-results.json'),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    hashes['installed_tree'] = installed_tree(deps, expected, installed)
    hashes['installed'] = verify(deps, expected)
    if source_identity(env) != source:
        raise ValueError('qualification source changed during generation')
    subprocess.run(python_command([deps, ROOT / 'src', ROOT / 'tests'], 'pytest', work) +
                   ['-q', '-p', 'no:cacheprovider',
                    '-p', '_openshell_qualification',
                    'tests/test_openshell_transport.py', 'tests/test_openshell_transport_grpc.py',
                    'tests/test_openshell_channel.py'], cwd=ROOT, env=env, check=True, timeout=TIMEOUTS['pytest'])
    results = json.loads((work / 'test-results.json').read_text())
    if results['exitstatus'] or results['collected'] <= 0 or results['passed'] != results['collected']:
        raise ValueError('qualification requires a complete passing test run')
    if source_identity(env) != source:
        raise ValueError('qualification source changed during run')
    receipt = dict(source=source, server_commit=manifest['server_commit'],
                   interpreter=dict(path=sys.executable, version=platform.python_version()),
                   uv_version=uv_version, platform=manifest['platform'],
                   manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
                   hashes=hashes, tests=results, timeouts_seconds=TIMEOUTS,
                   completed_at=datetime.now(timezone.utc).isoformat())
    (work / 'qualification-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
