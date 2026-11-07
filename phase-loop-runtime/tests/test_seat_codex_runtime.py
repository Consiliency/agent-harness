"""SEATS CODEX SL-1.1 (agent-harness#1820): the Codex runtime file set (IF-0-CODEX-2).

A standalone subject's native image names a vendored target. The seat binds only
``CODEX_RUNTIME_FILES`` from it, each from one regular, unlinked host file, read-only under
``CODEX_RUNTIME_ROOT``. ``codex-resources/`` and the target directory are never bound. A
``session_lease`` or ``managed_release`` subject is admitted through the profile's
projection and never reaches ``resolve_runtime``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from phase_loop_runtime import seat_codex_runtime as runtime
from phase_loop_runtime import seat_jail
from phase_loop_runtime.seat_subject import SeatSubject


IDENTITY = "seat_sandbox_refused:identity"
UNAVAILABLE = "seat_provider_unavailable"

# The two install layouts a standalone native image is found in: the npm platform
# package's vendored target, and a versioned release directory.
LAYOUTS = (
    "npm/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl",
    "home/.codex/releases/0.167.0-x86_64-unknown-linux-musl",
)


def _target(base: Path, layout: str = LAYOUTS[0]) -> Path:
    """A synthetic vendored target with the full CLI layout, modes set explicitly so the
    runner's umask never decides the outcome."""
    target = base / layout
    for relpath in runtime.CODEX_RUNTIME_FILES:
        path = target / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x7fELF" if relpath.startswith(("bin/", "codex-path/")) else b"{}")
        path.chmod(0o755)
    resources = target / "codex-resources"
    resources.mkdir()
    (resources / "bwrap").write_bytes(b"\x7fELF")
    for directory in (target, target / "bin", target / "codex-path", resources):
        directory.chmod(0o755)
    return target


def _native(target: Path) -> Path:
    return target / "bin" / "codex"


def _refusal(native: Path) -> str:
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.resolve_runtime(native)
    return caught.value.code


@pytest.mark.parametrize("layout", LAYOUTS)
def test_each_layout_resolves_the_runtime_file_set(tmp_path, layout):
    target = _target(tmp_path, layout)
    resolved = runtime.resolve_runtime(_native(target))
    assert resolved.target == target.resolve()
    assert tuple(rel for rel, _source in resolved.sources) == runtime.CODEX_RUNTIME_FILES
    assert all(source == str(target.resolve() / rel) for rel, source in resolved.sources)


def test_two_layouts_bind_the_same_destinations(tmp_path):
    first = runtime.resolve_runtime(_native(_target(tmp_path / "a", LAYOUTS[0])))
    second = runtime.resolve_runtime(_native(_target(tmp_path / "b", LAYOUTS[1])))
    first_binds, second_binds = runtime.runtime_binds(first), runtime.runtime_binds(second)
    assert first_binds[0::3] == second_binds[0::3] == ("--ro-bind",) * 4
    assert first_binds[2::3] == second_binds[2::3] == runtime.CODEX_RUNTIME_DESTINATIONS
    assert runtime.CODEX_RUNTIME_DESTINATIONS == tuple(
        f"{runtime.CODEX_RUNTIME_ROOT}/{rel}" for rel in runtime.CODEX_RUNTIME_FILES)


def test_no_bind_names_the_resources_or_the_target_directory(tmp_path):
    target = _target(tmp_path)
    binds = runtime.runtime_binds(runtime.resolve_runtime(_native(target)))
    assert (target / "codex-resources").is_dir()
    assert not any("codex-resources" in word for word in binds)
    sources = binds[1::3]
    assert str(target) not in binds and str(target.resolve()) not in binds
    assert all(Path(source).parent != Path(runtime.CODEX_RUNTIME_ROOT) for source in sources)
    assert runtime.CODEX_RUNTIME_ROOT not in binds
    assert len(sources) == len(set(sources)) == len(runtime.CODEX_RUNTIME_FILES)


@pytest.mark.parametrize("relpath", runtime.CODEX_RUNTIME_FILES)
def test_a_missing_file_is_provider_unavailable(tmp_path, relpath):
    target = _target(tmp_path)
    (target / relpath).unlink()
    assert _refusal(_native(target)) == UNAVAILABLE


def test_a_missing_directory_is_provider_unavailable(tmp_path):
    target = _target(tmp_path)
    (target / "codex-path" / "rg").unlink()
    (target / "codex-path").rmdir()
    assert _refusal(_native(target)) == UNAVAILABLE


@pytest.mark.parametrize("native", (
    "vendor/x86_64-unknown-linux-musl/codex/codex",       # not bin/codex
    "vendor/x86_64-unknown-linux-musl/bin/codex-exec",    # not the codex image
    "lib/x86_64-unknown-linux-musl/bin/codex",            # not a vendored target
    "vendor/x86_64-unknown-linux-gnu/bin/codex",          # not a musl target
))
def test_an_unsupported_layout_is_provider_unavailable(tmp_path, native):
    path = tmp_path / native
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x7fELF")
    assert _refusal(path) == UNAVAILABLE


def test_a_relative_native_path_is_provider_unavailable():
    assert _refusal(Path("vendor/x86_64-unknown-linux-musl/bin/codex")) == UNAVAILABLE


@pytest.mark.parametrize("relpath", runtime.CODEX_RUNTIME_FILES)
def test_a_symlinked_file_is_refused_identity(tmp_path, relpath):
    target = _target(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_bytes(b"\x7fELF")
    elsewhere.chmod(0o755)
    (target / relpath).unlink()
    (target / relpath).symlink_to(elsewhere)
    assert _refusal(_native(target)) == IDENTITY


@pytest.mark.parametrize("relpath", runtime.CODEX_RUNTIME_FILES)
def test_a_hard_linked_file_is_refused_identity(tmp_path, relpath):
    target = _target(tmp_path)
    os.link(target / relpath, tmp_path / "second-name")
    assert _refusal(_native(target)) == IDENTITY


def test_a_symlinked_directory_is_refused_identity(tmp_path):
    target = _target(tmp_path)
    real = tmp_path / "real-path-dir"
    (target / "codex-path").rename(real)
    (target / "codex-path").symlink_to(real)
    assert _refusal(_native(target)) == IDENTITY


@pytest.mark.parametrize("relpath", runtime.CODEX_RUNTIME_FILES)
@pytest.mark.parametrize("mode", (0o775, 0o757))
def test_a_group_or_other_writable_file_is_refused_identity(tmp_path, relpath, mode):
    target = _target(tmp_path)
    (target / relpath).chmod(mode)
    assert _refusal(_native(target)) == IDENTITY


@pytest.mark.parametrize("directory", ("", "bin", "codex-path"))
def test_a_group_writable_directory_is_refused_identity(tmp_path, directory):
    target = _target(tmp_path)
    (target / directory).chmod(0o775)
    assert _refusal(_native(target)) == IDENTITY


def test_a_wrongly_owned_file_is_refused_identity(tmp_path, monkeypatch):
    target = _target(tmp_path)
    # Files a test creates are owned by its euid; trusting only another uid makes every
    # one of them wrongly owned, whether the runner is root or not.
    monkeypatch.setattr(runtime, "_trusted_owners", lambda: frozenset({os.geteuid() + 4242}))
    assert _refusal(_native(target)) == IDENTITY


@pytest.mark.parametrize("kind", ("directory", "fifo"))
def test_a_file_that_is_not_regular_is_refused_identity(tmp_path, kind):
    target = _target(tmp_path)
    path = target / "codex-package.json"
    path.unlink()
    if kind == "directory":
        path.mkdir()
        path.chmod(0o755)
    else:
        os.mkfifo(path, 0o644)
    assert _refusal(_native(target)) == IDENTITY


def test_a_component_that_is_a_file_is_refused_identity(tmp_path):
    target = _target(tmp_path)
    (target / "codex-path" / "rg").unlink()
    (target / "codex-path").rmdir()
    (target / "codex-path").write_bytes(b"")
    (target / "codex-path").chmod(0o644)
    assert _refusal(_native(target)) == IDENTITY


def test_runtime_binds_refuses_a_file_set_it_did_not_resolve(tmp_path):
    resolved = runtime.resolve_runtime(_native(_target(tmp_path)))
    extra = runtime.CodexRuntime(
        resolved.target,
        (*resolved.sources, ("codex-resources/bwrap", str(resolved.target / "codex-resources/bwrap"))))
    missing = runtime.CodexRuntime(resolved.target, resolved.sources[:-1])
    for forged in (extra, missing):
        with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
            runtime.runtime_binds(forged)
        assert caught.value.code == IDENTITY
    with pytest.raises(TypeError):
        runtime.runtime_binds(resolved.sources)


def test_every_refusal_code_is_a_notice():
    assert IDENTITY in seat_jail.NOTICES and UNAVAILABLE in seat_jail.NOTICES


# --- subjects ------------------------------------------------------------------------

@pytest.mark.parametrize("source", ("managed_release", "session_lease"))
def test_a_projected_subject_never_reaches_resolve_runtime(tmp_path, monkeypatch, source):
    def _never(_native):
        raise AssertionError("resolve_runtime reached for a projected subject")

    monkeypatch.setattr(runtime, "resolve_runtime", _never)
    native = _native(_target(tmp_path))
    subject = SeatSubject(
        "codex", source, native if source == "managed_release" else None,
        "release-1" if source == "managed_release" else None, None)
    assert runtime.subject_runtime(subject) is None


def test_a_standalone_subject_resolves_its_own_path(tmp_path, monkeypatch):
    native = _native(_target(tmp_path))
    seen: list[Path] = []
    real = runtime.resolve_runtime

    def _spy(path):
        seen.append(path)
        return real(path)

    monkeypatch.setattr(runtime, "resolve_runtime", _spy)
    resolved = runtime.subject_runtime(SeatSubject("codex", "standalone", native, None, None))
    assert seen == [native]
    assert resolved is not None and tuple(r for r, _s in resolved.sources) == runtime.CODEX_RUNTIME_FILES


def test_a_standalone_subject_without_a_path_is_provider_unavailable():
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.subject_runtime(SeatSubject("codex", "standalone", None, None, None))
    assert caught.value.code == UNAVAILABLE


def test_another_leg_or_source_is_refused(tmp_path):
    native = _native(_target(tmp_path))
    with pytest.raises(ValueError):
        runtime.subject_runtime(SeatSubject("gemini", "standalone", native, None, None))
    with pytest.raises(ValueError):
        runtime.subject_runtime(SeatSubject("codex", "elsewhere", native, None, None))  # type: ignore[arg-type]
