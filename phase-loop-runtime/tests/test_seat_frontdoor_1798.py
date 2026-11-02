"""agent-harness#1798: seats follow a Consiliency guarded frontdoor to its native provider.

The shared team-host CLIs are ``#!/bin/sh`` frontdoors whose last line re-enters a
release-pinned Python launcher (``exec /usr/bin/python3 -I <release>/source/lib/
user_agent_tools.py launch --provider P --shared <native> --node-bin <dir> -- "$@"``).
The seat cannot see the release's launcher, so it must bind the ``--shared`` native target,
under the agent-harness#1318 trust checks plus release containment and ownership checks.
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


@pytest.fixture(autouse=True)
def _fixed_umask():
    """The trust checks refuse group/other-writable directories, so fixtures must not
    depend on the caller's umask (dev0 uses 002, CI 022)."""
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def releases(tmp_path, monkeypatch):
    root = tmp_path / "releases"
    root.mkdir()
    monkeypatch.setattr(pi, "_FRONTDOOR_RELEASES", root)
    monkeypatch.setattr(pi, "_FRONTDOOR_OWNERS", frozenset({0, os.getuid()}))
    return root


def _release(releases: Path, name: str = "2026.10.17-claude.1-21bd3fbd8923") -> Path:
    release = releases / name
    _exe(release / "source/lib/user_agent_tools.py", "# launcher\n", 0o644)
    (release / "node/bin").mkdir(parents=True, exist_ok=True)
    for path in [release, *release.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
    return release


def _frontdoor(bin_dir: Path, name: str, release: Path, shared: Path, *, provider: str | None = None,
               interpreter: str = "/usr/bin/python3", extra: str = "") -> Path:
    return _exe(bin_dir / name,
                "#!/bin/sh\n"
                f'export PATH={release}/node/bin:"$PATH"\n'
                "export DISABLE_AUTOUPDATER=1\n"
                f"exec {interpreter} -I {release}/source/lib/user_agent_tools.py launch"
                f" --provider {provider or name} --shared {shared}{extra}"
                f' --node-bin {release}/node/bin -- "$@"\n')


def _source(monkeypatch, bin_dir: Path, name: str):
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
    return pi._seat_provider_source(name, {"PATH": str(bin_dir)})


@pytest.mark.parametrize("name,rel", [("grok", "native/grok"),
                                      ("claude", "npm/node_modules/@anthropic-ai/claude-code-linux-x64/claude")])
def test_a_frontdoor_resolves_to_its_shared_native_target(releases, tmp_path, monkeypatch, name, rel):
    release = _release(releases)
    native = _exe(release / rel, "\x7fELF")
    _frontdoor(tmp_path / "bin", name, release, native)
    assert _source(monkeypatch, tmp_path / "bin", name) == (name, str(native))


def test_a_frontdoor_npm_codex_resolves_to_the_vendored_binary(releases, tmp_path, monkeypatch):
    machine = os.uname().machine
    if machine not in {"x86_64", "aarch64"}:
        pytest.skip("codex ships linux binaries for x86_64/aarch64 only")
    suffix = {"x86_64": "x64", "aarch64": "arm64"}[machine]
    release = _release(releases)
    modules = release / "npm/node_modules"
    _exe(modules / "@openai/codex/bin/codex.js", "#!/usr/bin/env node\n")
    (modules / ".bin").mkdir(parents=True)
    (modules / ".bin/codex").symlink_to("../@openai/codex/bin/codex.js")
    native = _exe(modules / f"@openai/codex-linux-{suffix}/vendor/{machine}-unknown-linux-musl/bin/codex", "\x7fELF")
    _frontdoor(tmp_path / "bin", "codex", release, modules / ".bin/codex")
    assert _source(monkeypatch, tmp_path / "bin", "codex") == ("codex", str(native))


def _target(path: Path, provider: str):
    return pi._shell_wrapper_target(path, provider)


def test_a_release_outside_the_releases_root_is_not_followed(releases, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    release = _release(other)
    native = _exe(release / "native/grok", "\x7fELF")
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, native), "grok") is None


def test_a_shared_target_outside_the_release_is_not_followed(releases, tmp_path):
    release = _release(releases)
    native = _exe(tmp_path / "loose/grok", "\x7fELF")
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, native), "grok") is None


def test_a_symlink_escaping_the_release_is_not_followed(releases, tmp_path):
    release = _release(releases)
    outside = _exe(tmp_path / "loose/grok", "\x7fELF")
    (release / "native").mkdir(parents=True, exist_ok=True)
    (release / "native/grok").symlink_to(outside)
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, release / "native/grok"), "grok") is None


def test_a_provider_mismatch_is_not_followed(releases, tmp_path):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    door = _frontdoor(tmp_path / "bin", "claude", release, native, provider="grok")
    assert _target(door, "claude") is None


def test_a_shared_target_that_is_not_the_provider_is_not_followed(releases, tmp_path):
    release = _release(releases)
    other = _exe(release / "native/bash", "\x7fELF")
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, other), "grok") is None


@pytest.mark.parametrize("interpreter", ["/usr/bin/python3.12", "/usr/bin/env python3", "/tmp/python3"])
def test_another_interpreter_is_not_followed(releases, tmp_path, interpreter):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, native, interpreter=interpreter), "grok") is None


def test_extra_launcher_arguments_are_not_followed(releases, tmp_path):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    door = _frontdoor(tmp_path / "bin", "grok", release, native, extra=" --account other")
    assert _target(door, "grok") is None


def test_a_group_writable_release_is_not_followed(releases, tmp_path):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    release.chmod(0o775)
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, native), "grok") is None


def test_a_release_owned_by_someone_else_is_not_followed(releases, tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "_FRONTDOOR_OWNERS", frozenset({0}))
    if os.getuid() == 0:
        pytest.skip("running as root")
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, native), "grok") is None


def test_an_untrusted_frontdoor_file_is_not_followed(releases, tmp_path):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    door = _frontdoor(tmp_path / "bin", "grok", release, native)
    door.chmod(0o777)
    assert _target(door, "grok") is None


# --- Review r1 (agent-harness#1802): trust the whole chain of the image actually executed. ---

def test_a_writable_directory_between_release_and_target_is_not_followed(releases, tmp_path, monkeypatch):
    release = _release(releases)
    native = _exe(release / "native/sub/grok", "\x7fELF")
    (release / "native").chmod(0o777)
    _frontdoor(tmp_path / "bin", "grok", release, native)
    assert _target(tmp_path / "bin/grok", "grok") is None


def test_a_writable_target_image_is_not_followed(releases, tmp_path):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF", 0o777)
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, native), "grok") is None


def test_a_target_owned_by_someone_else_is_not_followed(releases, tmp_path, monkeypatch):
    release = _release(releases)
    native = _exe(release / "native/grok", "\x7fELF")
    door = _frontdoor(tmp_path / "bin", "grok", release, native)
    real_lstat = os.lstat
    image = str(native.resolve())

    def lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.fspath(path) == image:
            return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink, 4242,
                                   info.st_gid, info.st_size, info.st_atime, info.st_mtime, info.st_ctime))
        return info
    monkeypatch.setattr(pi.os, "lstat", lstat)
    assert _target(door, "grok") is None


def test_codex_vendored_binary_outside_the_release_is_not_followed(releases, tmp_path):
    machine = os.uname().machine
    if machine not in {"x86_64", "aarch64"}:
        pytest.skip("codex ships linux binaries for x86_64/aarch64 only")
    suffix = {"x86_64": "x64", "aarch64": "arm64"}[machine]
    release = _release(releases)
    modules = release / "npm/node_modules"
    _exe(modules / "@openai/codex/bin/codex.js", "#!/usr/bin/env node\n")
    (modules / ".bin").mkdir(parents=True)
    (modules / ".bin/codex").symlink_to("../@openai/codex/bin/codex.js")
    outside = _exe(tmp_path / "loose/codex", "\x7fELF")
    vendored = modules / f"@openai/codex-linux-{suffix}/vendor/{machine}-unknown-linux-musl/bin"
    vendored.mkdir(parents=True)
    (vendored / "codex").symlink_to(outside)
    door = _frontdoor(tmp_path / "bin", "codex", release, modules / ".bin/codex")
    assert _target(door, "codex") is None


def test_the_returned_path_is_the_final_validated_image(releases, tmp_path):
    release = _release(releases)
    native = _exe(release / "native/v1/grok", "\x7fELF")
    (release / "native/grok").symlink_to("v1/grok")
    door = _frontdoor(tmp_path / "bin", "grok", release, release / "native/grok")
    assert _target(door, "grok") == native.resolve()


def test_a_symlink_swapped_to_an_outside_image_before_the_check_is_not_followed(releases, tmp_path):
    release = _release(releases)
    _exe(release / "native/grok-1.0", "\x7fELF")
    outside = _exe(tmp_path / "loose/grok", "\x7fELF")
    link = release / "native/grok"
    link.symlink_to(outside)
    assert _target(_frontdoor(tmp_path / "bin", "grok", release, link), "grok") is None
