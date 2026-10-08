"""agent-harness#1318: seats resolve team-host launcher wrappers to the native provider.

Team-host tooling ships each CLI as a ``#!/bin/sh`` wrapper that exports PATH and then
``exec``s a binary elsewhere in the release. The seat binds only the provider file, so it
must bind the wrapper's target, never the wrapper. Only a trusted wrapper of exactly that
shape is followed; anything else is bound as-is, as before.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi


def _exe(path: Path, text: str, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


def _wrapper(bin_dir: Path, name: str, target: Path, extra: str = "") -> Path:
    return _exe(bin_dir / name,
                f'#!/bin/sh\nexport PATH=/opt/node/bin:"$PATH"\nexport DISABLE_AUTOUPDATER=1\n'
                f'{extra}exec {target} -c check_for_update_on_startup=false "$@"\n')


def _source(monkeypatch, bin_dir: Path, name: str) -> tuple[str, str]:
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
    return pi._seat_provider_source(name, {"PATH": str(bin_dir)})


def test_a_trusted_wrapper_resolves_to_its_native_target(tmp_path, monkeypatch):
    native = _exe(tmp_path / "release/native/grok", "\x7fELF")
    _wrapper(tmp_path / "release/bin", "grok", native)
    assert _source(monkeypatch, tmp_path / "release/bin", "grok") == ("grok", str(native))


def test_a_wrapped_hoisted_npm_codex_resolves_to_the_vendored_binary(tmp_path, monkeypatch):
    modules = tmp_path / "release/npm/node_modules"
    launcher = _exe(modules / "@openai/codex/bin/codex.js", "#!/usr/bin/env node\n")
    (modules / ".bin").mkdir(parents=True)
    (modules / ".bin/codex").symlink_to("../@openai/codex/bin/codex.js")
    machine = os.uname().machine
    if machine not in {"x86_64", "aarch64"}:
        pytest.skip("codex ships linux binaries for x86_64/aarch64 only")
    suffix = {"x86_64": "x64", "aarch64": "arm64"}[machine]
    native = _exe(modules / f"@openai/codex-linux-{suffix}/vendor/{machine}-unknown-linux-musl/bin/codex", "\x7fELF")
    _wrapper(tmp_path / "release/bin", "codex", modules / ".bin/codex")
    assert launcher.is_file()
    assert _source(monkeypatch, tmp_path / "release/bin", "codex") == ("codex", str(native))


@pytest.mark.parametrize("body", [
    '#!/bin/sh\nrm -rf "$HOME"\nexec /opt/x/grok "$@"\n',          # an extra command
    '#!/bin/bash\nexec /opt/x/grok "$@"\n',                         # another interpreter
    '#!/bin/sh\nexec opt/x/grok "$@"\n',                            # a relative target
    '#!/bin/sh\nexec /opt/x/grok "$@"; touch /tmp/x\n',             # a trailing command
    '#!/bin/sh\nexec /opt/$(id)/grok "$@"\n',                       # a substitution
    '#!/bin/sh\nexport PATH=$(id)\nexec /opt/x/grok "$@"\n',        # a substitution in export
])
def test_an_unexpected_wrapper_shape_is_not_followed(tmp_path, body):
    assert pi._shell_wrapper_target(_exe(tmp_path / "bin/grok", body)) is None


def test_a_wrapper_others_can_write_is_not_followed(tmp_path):
    native = _exe(tmp_path / "native/grok", "\x7fELF")
    wrapper = _wrapper(tmp_path / "bin", "grok", native)
    assert pi._shell_wrapper_target(wrapper) == native
    wrapper.chmod(0o775)
    assert pi._shell_wrapper_target(wrapper) is None


def test_a_wrapper_another_account_owns_is_not_followed(tmp_path, monkeypatch):
    native = _exe(tmp_path / "native/grok", "\x7fELF")
    wrapper = _wrapper(tmp_path / "bin", "grok", native)
    operator = os.getuid()
    if operator == 0:
        pytest.skip("root owns the fixture, which is a trusted owner")
    monkeypatch.setattr(pi.os, "getuid", lambda: operator + 1)
    assert pi._shell_wrapper_target(wrapper) is None


def test_a_plain_binary_is_bound_as_before(tmp_path, monkeypatch):
    native = _exe(tmp_path / "bin/grok", "\x7fELF")
    assert _source(monkeypatch, tmp_path / "bin", "grok") == ("grok", str(native))


# --- advisor-board stack review ------------------------------------------------------


@pytest.mark.parametrize("line", [
    'exec /usr/bin/env node /opt/x/cli.js "$@"',   # an interpreter with a script
    'exec /opt/node/bin/node /opt/x/cli.js "$@"',  # a named interpreter
    'exec /opt/x/grok --sandbox off "$@"',         # a flag that is not -c key=value
])
def test_an_interpreter_or_flagged_exec_line_is_not_followed(tmp_path, line):
    assert pi._shell_wrapper_target(_exe(tmp_path / "bin/grok", f"#!/bin/sh\n{line}\n"), "grok") is None


def test_a_target_not_named_for_the_provider_is_not_followed(tmp_path):
    wrapper = _exe(tmp_path / "bin/grok", '#!/bin/sh\nexec /opt/node/bin/node "$@"\n')
    assert pi._shell_wrapper_target(wrapper, "grok") is None
    assert pi._shell_wrapper_target(wrapper) == Path("/opt/node/bin/node")


def test_a_fifo_or_symlinked_wrapper_is_read_without_blocking_or_following(tmp_path):
    fifo = tmp_path / "bin/grok"
    fifo.parent.mkdir(parents=True)
    os.mkfifo(fifo)
    assert pi._shell_wrapper_target(fifo, "grok") is None
    native = _exe(tmp_path / "native/grok", "\x7fELF")
    real = _wrapper(tmp_path / "real", "grok", native)
    link = tmp_path / "linked/grok"
    link.parent.mkdir()
    link.symlink_to(real)
    assert pi._shell_wrapper_target(link, "grok") is None
    assert pi._shell_wrapper_target(real, "grok") == native
