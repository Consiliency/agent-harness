"""Explicit, fail-closed local SDK qualification; never activates offload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

MANIFEST = Path(__file__).with_name('openshell-sdk-manifest.json')
ROOT = Path(__file__).resolve().parents[1]


def verify(directory, pins):
    for name, expected in pins.items():
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'missing or mismatched qualification input: {name}')


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
    # Test dependencies belong to the caller's read-only environment.
    import pytest  # noqa: F401
    work = args.work.resolve()
    work.mkdir(mode=0o700)
    proto, wheels, deps, generated = [work / p for p in ('proto', 'wheels', 'deps', 'generated')]
    for directory in (proto, wheels, generated):
        directory.mkdir()
    for name in manifest['proto_inputs']:
        content = subprocess.check_output(['git', '-C', str(args.server), 'show',
                                          f"{manifest['server_commit']}:proto/{name}"])
        (proto / name).write_bytes(content)
    verify(proto, manifest['proto_inputs'])
    requirements = []
    for name, wheel in manifest['wheels'].items():
        with urllib.request.urlopen(wheel['url'], timeout=60) as response:
            (wheels / wheel['filename']).write_bytes(response.read())
        verify(wheels, {wheel['filename']: wheel['sha256']})
        requirements.append(f"{name}=={wheel['version']} --hash=sha256:{wheel['sha256']}")
    lock = work / 'requirements.txt'
    lock.write_text('\n'.join(requirements) + '\n')
    subprocess.run(['uv', 'pip', 'install', '--no-cache', '--no-index', '--find-links', str(wheels),
                    '--require-hashes', '--only-binary=:all:', '--python', sys.executable,
                    '--target', str(deps), '-r', str(lock)], check=True)
    verify(deps, manifest['generator_inputs'])
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=os.pathsep.join(map(str, (deps, ROOT / 'src', ROOT / 'tests'))),
               OPENSHELL_GENERATED_DIR=str(generated), OPENSHELL_SDK_QUALIFICATION='1',
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTEST_ADDOPTS', None)
    subprocess.run([sys.executable, '-B', '-m', 'grpc_tools.protoc', '-I', str(proto),
                    f'--python_out={generated}', f'--grpc_python_out={generated}',
                    f'--descriptor_set_out={generated / "openshell.desc"}', '--include_imports',
                    *map(str, sorted(proto.glob('*.proto')))], env=env, check=True)
    verify(generated, manifest['generated_outputs'])
    subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                    '-p', '_openshell_qualification',
                    'tests/test_openshell_transport.py', 'tests/test_openshell_transport_grpc.py',
                    'tests/test_openshell_channel.py'], cwd=ROOT, env=env, check=True, timeout=180)
    (work / 'verified-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
