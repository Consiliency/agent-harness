"""Export only locked, credential-free release payloads; never run a vendor CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('expected a bounded relative payload path')
    return path


def prepare(lock, roots, destination):
    if lock['platform'] != 'linux/amd64':
        raise ValueError('unsupported platform')
    checked = []
    targets = set()
    for entry in lock['files']:
        root = roots[entry['root']].resolve(strict=True)
        source = root / relative(entry['source'])
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(root) or source.is_symlink():
            raise ValueError('payload must remain within its release root')
        target = relative(entry['target'])
        if target in targets:
            raise ValueError('duplicate payload target')
        targets.add(target)
        if not source.is_file() or digest(source) != entry['sha256']:
            raise ValueError('payload digest mismatch: ' + entry['target'])
        checked.append((source, target, entry))
    # No partial destination is created when source verification fails.
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for source, target, entry in checked:
        output = destination / target
        output.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, output.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        if digest(output) != entry['sha256']:
            raise ValueError('payload changed during export')
        output.chmod(0o755 if entry['executable'] else 0o644)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tooling', required=True, type=Path)
    parser.add_argument('--agy', required=True, type=Path)
    parser.add_argument('--debian', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    lock = json.loads(Path(__file__).with_name('payload.lock.json').read_text())
    prepare(lock, {'tooling': args.tooling, 'agy': args.agy, 'debian': args.debian}, args.output)
