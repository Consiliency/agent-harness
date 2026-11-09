"""Offline in-image identity, payload and ELF closure check; no vendor execution."""
import grp
import hashlib
import json
import mmap
import os
from pathlib import Path
import platform
import pwd
import re
import struct
import subprocess
import sys


def elf_interpreter(data):
    if data[:4] != b'\x7fELF':
        return None
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 62:
        raise ValueError('expected amd64 ELF64')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    for index in range(count):
        at = offset + index * size
        if struct.unpack_from('<I', data, at)[0] == 3:
            start = struct.unpack_from('<Q', data, at + 8)[0]
            length = struct.unpack_from('<Q', data, at + 32)[0]
            return data[start:start + length].rstrip(b'\0').decode('ascii')
    return None


def checked_path(path):
    real = Path(path).resolve(strict=True)
    if not real.is_file() or not str(real).startswith(('/usr/', '/lib/', '/opt/advisors/')):
        raise ValueError('unexpected runtime realpath: ' + str(real))
    return str(real)


def dependencies(output, returncode):
    if 'not found' in output:
        raise ValueError('unresolved ELF dependency')
    if returncode and output.strip() not in ('not a dynamic executable', 'statically linked'):
        raise ValueError('ELF inspection failed')
    result = set()
    for line in output.splitlines():
        match = re.search(r'(/[^\s]+)', line)
        if match:
            result.add(checked_path(match[1]))
        elif line.strip() and not any(s in line for s in ('linux-vdso', 'statically linked', 'not a dynamic executable')):
            raise ValueError('unrecognized ELF dependency output')
    return result


def main():
    if (os.geteuid(), os.getegid()) != (10001, 10001):
        raise ValueError('check must run as sandbox 10001:10001')
    if platform.machine() != 'x86_64':
        raise ValueError('linux/amd64 required')
    account = pwd.getpwnam('sandbox')
    if (account.pw_uid, account.pw_gid, grp.getgrnam('sandbox').gr_gid) != (10001, 10001, 10001):
        raise ValueError('sandbox account identity mismatch')
    lock = json.loads(Path('/usr/share/advisor-workload/payload.lock.json').read_text())
    root = Path('/opt/advisors')
    rows = []
    closure = set()
    for entry in lock['files']:
        path = root / entry['target']
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError('payload digest mismatch')
        if entry['executable'] and not os.access(path, os.X_OK):
            raise ValueError('payload is not executable')
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise ValueError('payload must be root owned and not group/world writable')
        row = {'path': str(path), 'realpath': checked_path(path), 'sha256': digest}
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic == b'\x7fELF':
            with path.open('rb') as stream, mmap.mmap(
                stream.fileno(), 0, access=mmap.ACCESS_READ
            ) as data:
                loader = elf_interpreter(data)
            row['interpreter'] = checked_path(loader) if loader else None
            run = subprocess.run(['/usr/bin/ldd', str(path)], capture_output=True, text=True,
                                 timeout=30, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            row['libraries'] = sorted(dependencies(run.stdout + run.stderr, run.returncode))
            closure.update(row['libraries'])
            if row['interpreter']:
                closure.add(row['interpreter'])
        rows.append(row)
    for name in ('claude', 'codex', 'agy', 'grok', 'node'):
        checked_path('/usr/local/bin/' + name)
    # Include native verifier imports and ldd's Debian shell interpreter.
    support = {sys.executable, '/bin/sh', '/bin/bash'}
    support.update(
        str(module.__file__) for module in sys.modules.values()
        if str(getattr(module, '__file__', '')).endswith('.so')
    )
    for path in sorted(support):
        closure.add(checked_path(path))
        run = subprocess.run(['/usr/bin/ldd', path], capture_output=True, text=True,
                             timeout=30, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        closure.update(dependencies(run.stdout + run.stderr, run.returncode))
    libraries = []
    for path in sorted(closure):
        with Path(path).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        libraries.append({'realpath': path, 'sha256': digest})
    print(json.dumps({'platform': 'linux/amd64', 'uid': 10001, 'gid': 10001,
                      'payloads': rows, 'runtime_closure': libraries}, indent=2))


if __name__ == '__main__':
    main()
