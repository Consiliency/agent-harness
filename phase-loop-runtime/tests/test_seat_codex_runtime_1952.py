"""Regression tests for Consiliency/agent-harness#1952.

Standalone Codex runtime validation must:
1. Verify every ancestor up to `/` is trusted (owned by root or the operator, not
   group- or other-writable, with the standard root-owned sticky-directory exception for
   strict ancestors only, and descriptor-anchored symlink/lookup-chain validation).
2. Carry validated file identities via held read-only descriptors into both admission
   execution and jail binding (`--ro-bind-data`), verifying live projection descriptors,
   modes, destinations, and zero offsets at each spawn boundary while preserving the
   canonical Codex jail profile digest.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from types import SimpleNamespace

import pytest

from phase_loop_runtime import (
    panel_invoker as pi,
    seat_codex_credential as cred,
    seat_codex_runtime as runtime,
    seat_jail,
    seat_profile_codex,
    seat_subject,
)
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime.seat_subject import SeatSubject
from test_seat_codex_credential import _claims, _login


IDENTITY = "seat_sandbox_refused:identity"
UNAVAILABLE = "seat_provider_unavailable"


def _make_target(base: Path, layout: str = "npm/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl") -> Path:
    target = base / layout
    for relpath in runtime.CODEX_RUNTIME_FILES:
        path = target / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x7fELFfixture-" + relpath.encode("ascii") if relpath.startswith(("bin/", "codex-path/")) else b'{"name":"codex"}')
        path.chmod(0o755 if relpath.startswith(("bin/", "codex-path/")) else 0o644)
    resources = target / "codex-resources"
    resources.mkdir(exist_ok=True)
    (resources / "bwrap").write_bytes(b"\x7fELF")
    current = target
    while current != base and base in current.parents:
        current.chmod(0o755)
        current = current.parent
    for directory in (target, target / "bin", target / "codex-path", resources):
        directory.chmod(0o755)
    return target


def _make_jail_with_runtime(tmp_path: Path, admitted: runtime.AdmittedStandaloneRuntime) -> seat_jail.SeatJail:
    directory = tmp_path / "jail"
    tree = directory / "reviewed-tree"
    tree.mkdir(parents=True, exist_ok=True)
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"certificate")
    return seat_jail.build_seat_jail(
        "codex",
        directory,
        Path(admitted.subject_source),
        tree=tree,
        bundle_memfd=seat_jail.memfd_with("b", b"bundle"),
        instructions_memfd=seat_jail.memfd_with("i", b"instructions"),
        seat_ids=(1, 1),
        egress_ca=ca,
        egress_proxy="http://fixture:password@127.0.0.1:3128",
        standalone_runtime=admitted,
    )


# --- 1. Ancestor trust verification --------------------------------------------------


@pytest.mark.parametrize("ancestor_rel", ("npm", "npm/node_modules/@openai", "npm/node_modules/@openai/codex-linux-x64/vendor"))
@pytest.mark.parametrize("mode", (0o775, 0o757, 0o1777))
def test_untrusted_ancestor_directory_is_refused_identity(tmp_path, ancestor_rel, mode):
    """Group-writable, world-writable, and non-root sticky ancestors must all refuse."""
    target = _make_target(tmp_path)
    (tmp_path / ancestor_rel).chmod(mode)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.resolve_runtime(target / "bin/codex")
    assert caught.value.code == IDENTITY


def test_target_itself_refuses_sticky_writable_even_if_root_owned(tmp_path, monkeypatch):
    """Root-owned sticky exception applies only to strict ancestors, never target or below."""
    info = os.stat_result((stat.S_IFDIR | 0o1777, 1, 1, 2, 0, 0, 0, 0, 0, 0))
    owners = frozenset({0, os.geteuid()})
    # Strict ancestor passes:
    runtime._require_trusted_ancestor(info, owners, "runtime ancestor '/tmp'")
    # Target or runtime subdir refuses:
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime._require_trusted(info, owners, "runtime target")
    assert caught.value.code == IDENTITY


def test_trusted_operator_symlink_ancestor_resolves_and_validates(tmp_path):
    real_base = tmp_path / "real"
    real_base.mkdir(mode=0o755)
    target = _make_target(real_base)
    link_parent = tmp_path / "links"
    link_parent.mkdir(mode=0o755)
    link = link_parent / "current"
    link.symlink_to(target)
    resolved = runtime.resolve_runtime(link / "bin/codex")
    assert resolved.target == target.resolve()
    assert resolved.files and resolved.ancestry


def test_symlink_inside_untrusted_ancestor_is_refused_identity(tmp_path):
    real_base = tmp_path / "real"
    real_base.mkdir(mode=0o755)
    target = _make_target(real_base)
    untrusted_dir = tmp_path / "untrusted"
    untrusted_dir.mkdir(mode=0o775)
    untrusted_dir.chmod(0o775)
    link = untrusted_dir / "current"
    link.symlink_to(target)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.resolve_runtime(link / "bin/codex")
    assert caught.value.code == IDENTITY


def test_symlink_ancestor_loop_is_refused_identity(tmp_path):
    loop_a = tmp_path / "loop_a"
    loop_b = tmp_path / "loop_b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.resolve_runtime(loop_a / "bin/codex")
    assert caught.value.code == IDENTITY


def test_parent_dotdot_resolves_against_verified_directory_stack(tmp_path):
    """`..` after a symlink inside an untrusted directory cannot escape the ancestor check."""
    real_base = tmp_path / "real"
    real_base.mkdir(mode=0o755)
    target = _make_target(real_base)
    untrusted = tmp_path / "untrusted"
    untrusted.mkdir(mode=0o775)
    untrusted.chmod(0o775)
    # Path traverses `untrusted` then `..` back to trusted `real`:
    tricky = Path(f"{untrusted}/../real/npm/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex")
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.resolve_runtime(tricky)
    assert caught.value.code == IDENTITY


# --- 2. Lookup-bound standalone Codex discovery --------------------------------------


def test_path_discovery_refuses_symlink_in_untrusted_directory(tmp_path):
    target = _make_target(tmp_path)
    untrusted_bin = tmp_path / "untrusted-bin"
    untrusted_bin.mkdir(mode=0o775)
    untrusted_bin.chmod(0o775)
    (untrusted_bin / "codex").symlink_to(target / "bin/codex")
    with pytest.raises(ExecutableDependencyError, match="subject_mismatch"):
        seat_subject.resolve_seat_subject("codex", {"PATH": str(untrusted_bin)})


def test_path_discovery_wrapper_to_codex_js_binds_lookup_chain(tmp_path):
    machine = os.uname().machine
    suffix = {"x86_64": "x64", "aarch64": "arm64"}.get(machine)
    if suffix is None:
        pytest.skip("unsupported arch")
    triple = f"{machine}-unknown-linux-musl"
    pkg_root = tmp_path / "pkg"
    target = _make_target(
        pkg_root,
        layout=f"node_modules/@openai/codex-linux-{suffix}/vendor/{triple}",
    )
    js_bin = pkg_root / "bin"
    js_bin.mkdir(parents=True, mode=0o755)
    js_bin.chmod(0o755)
    codex_js = js_bin / "codex.js"
    codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    codex_js.chmod(0o755)
    wrapper_dir = tmp_path / "path-bin"
    wrapper_dir.mkdir(mode=0o755)
    wrapper_dir.chmod(0o755)
    wrapper = wrapper_dir / "codex"
    wrapper.write_text(f'#!/bin/sh\nexec {codex_js} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    subject = seat_subject.resolve_seat_subject("codex", {"PATH": str(wrapper_dir)})
    assert subject.source == "standalone"
    assert subject.subject_path == (target / "bin/codex").resolve()
    assert len(subject.lookup_chain) == 3
    assert subject.lookup_chain[0][0] == str(wrapper.resolve())
    assert subject.lookup_chain[1][0] == str(codex_js.resolve())
    assert subject.lookup_chain[2][0] == str((target / "bin/codex").resolve())

    resolved = runtime.subject_runtime(subject)
    assert resolved is not None
    with runtime.admit_runtime(resolved, lookup_chain=subject.lookup_chain) as admitted:
        admitted.revalidate()
        # Mutating the wrapper hop after discovery causes revalidation to fail closed.
        wrapper.write_text("#!/bin/sh\nexec /bin/false \"$@\"\n", encoding="utf-8")
        with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
            admitted.revalidate()
        assert caught.value.code == IDENTITY


def test_session_lease_precedence_preserved_over_standalone_lookup(tmp_path, monkeypatch):
    def _never(*_args, **_kwargs):
        raise AssertionError("standalone lookup must not run when session_lease is active")

    monkeypatch.setattr(runtime, "resolve_trusted_codex_lookup", _never)
    monkeypatch.setattr(seat_subject, "_current_dependency", lambda leg: object() if leg == "codex" else None)
    subject = seat_subject.resolve_seat_subject("codex", {"PATH": str(tmp_path)})
    assert subject.source == "session_lease"
    assert runtime.subject_runtime(subject) is None


# --- 3. Carried validated file identities & jail projection --------------------------


def test_admit_runtime_rejects_forged_codex_runtime_without_identities(tmp_path):
    target = _make_target(tmp_path)
    forged = runtime.CodexRuntime(
        target,
        tuple((rel, str(target / rel)) for rel in runtime.CODEX_RUNTIME_FILES),
    )
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        runtime.admit_runtime(forged)
    assert caught.value.code == IDENTITY


def test_standalone_runtime_jail_binds_descriptors_and_preserves_golden_digest(tmp_path):
    target = _make_target(tmp_path)
    with runtime.open_runtime(target / "bin/codex") as admitted:
        jail = _make_jail_with_runtime(tmp_path, admitted)
        try:
            assert jail.dependency is None
            assert jail.standalone_runtime is admitted
            assert jail.provider_argv0 == runtime.CODEX_RUNTIME_DESTINATIONS[0]
            assert jail.path_map[jail.provider_path] == runtime.CODEX_RUNTIME_DESTINATIONS[0]
            # Zero pathname --ro-bind for runtime files or /seat/bin/codex:
            assert "/seat/bin/codex" not in jail.process_owner
            assert str(target / "bin/codex") not in jail.process_owner
            assert "/seat/bin/codex" not in seat_jail.expected_mount_points(jail)
            for dest in runtime.CODEX_RUNTIME_DESTINATIONS:
                assert dest in seat_jail.expected_mount_points(jail)
            assert jail.profile_digest == seat_jail.jail_profile_digest("codex")
            assert seat_jail.actual_profile_digest(jail) == seat_jail.jail_profile_digest("codex")
        finally:
            seat_jail.close_jail_fds(jail)


@pytest.mark.parametrize("tamper", ("mode", "destination", "fd_missing", "offset", "swapped_fd", "argv0"))
def test_tampered_standalone_projection_refuses_identity(tmp_path, tamper):
    target = _make_target(tmp_path)
    extra_fd = None
    with runtime.open_runtime(target / "bin/codex") as admitted:
        jail = _make_jail_with_runtime(tmp_path, admitted)
        try:
            mutated = jail
            if tamper == "mode":
                mounts = list(jail.standalone_runtime_mount_args)
                mounts[1] = "0777"
                owner = list(jail.process_owner)
                idx = owner.index(runtime.CODEX_RUNTIME_DESTINATIONS[0]) - 4
                owner[idx + 1] = "0777"
                mutated = replace(jail, process_owner=tuple(owner), standalone_runtime_mount_args=tuple(mounts))
            elif tamper == "destination":
                mounts = list(jail.standalone_runtime_mount_args)
                mounts[4] = "/run/phase-loop-seat/codex-runtime/bin/other"
                owner = list(jail.process_owner)
                idx = owner.index(runtime.CODEX_RUNTIME_DESTINATIONS[0])
                owner[idx] = "/run/phase-loop-seat/codex-runtime/bin/other"
                mutated = replace(jail, process_owner=tuple(owner), standalone_runtime_mount_args=tuple(mounts))
            elif tamper == "fd_missing":
                mutated = replace(jail, pass_fds=tuple(fd for fd in jail.pass_fds if fd != jail.standalone_runtime_fds[0]))
            elif tamper == "offset":
                os.lseek(jail.standalone_runtime_fds[0], 1, os.SEEK_SET)
            elif tamper == "swapped_fd":
                other = tmp_path / "other-file"
                other.write_bytes(b"different")
                extra_fd = os.open(other, os.O_RDONLY | os.O_CLOEXEC)
                mounts = list(jail.standalone_runtime_mount_args)
                old_fd = jail.standalone_runtime_fds[0]
                mounts[3] = str(extra_fd)
                owner = list(jail.process_owner)
                idx = owner.index(runtime.CODEX_RUNTIME_DESTINATIONS[0]) - 4
                owner[idx + 3] = str(extra_fd)
                mutated = replace(
                    jail,
                    process_owner=tuple(owner),
                    standalone_runtime_mount_args=tuple(mounts),
                    standalone_runtime_fds=(extra_fd, *jail.standalone_runtime_fds[1:]),
                    pass_fds=tuple(extra_fd if fd == old_fd else fd for fd in jail.pass_fds),
                )
            elif tamper == "argv0":
                mutated = replace(jail, provider_argv0="/seat/bin/codex")
            with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
                seat_jail.actual_profile_digest(mutated)
            assert caught.value.code == IDENTITY
        finally:
            if extra_fd is not None:
                os.close(extra_fd)
            seat_jail.close_jail_fds(jail)


def test_file_replacement_on_disk_refuses_revalidate_and_launch(tmp_path):
    target = _make_target(tmp_path)
    with runtime.open_runtime(target / "bin/codex") as admitted:
        jail = _make_jail_with_runtime(tmp_path, admitted)
        try:
            # Replace bin/codex on disk with a new inode after admission.
            codex_path = target / "bin/codex"
            codex_path.unlink()
            codex_path.write_bytes(b"\x7fELFswapped-binary")
            codex_path.chmod(0o755)
            with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
                seat_jail.verify_standalone_runtime_projection(jail)
            assert caught.value.code == IDENTITY
        finally:
            seat_jail.close_jail_fds(jail)


# --- 4. Fresh per-invocation descriptors in _fresh_window_launch_jails ---------------


def test_fresh_window_launch_jails_reopens_independent_offset_zero_descriptors(tmp_path):
    target = _make_target(tmp_path)
    with runtime.open_runtime(target / "bin/codex") as admitted:
        jail = _make_jail_with_runtime(tmp_path, admitted)
        probe = _make_jail_with_runtime(tmp_path / "probe", admitted)
        seat = SimpleNamespace(jail=jail, probe_jail=probe, token=b"")
        try:
            with pi._fresh_window_launch_jails(seat) as (cloned_jail, cloned_probe):
                assert set(cloned_jail.standalone_runtime_fds).isdisjoint(jail.standalone_runtime_fds)
                assert set(cloned_probe.standalone_runtime_fds).isdisjoint(probe.standalone_runtime_fds)
                assert set(cloned_jail.standalone_runtime_fds).isdisjoint(cloned_probe.standalone_runtime_fds)
                assert seat_jail.actual_profile_digest(cloned_jail) == seat_jail.jail_profile_digest("codex")
                assert seat_jail.actual_profile_digest(cloned_probe) == seat_jail.jail_profile_digest("codex")
                # Advance every cloned fd to EOF to simulate a completed invocation.
                for fd in (*cloned_jail.standalone_runtime_fds, *cloned_probe.standalone_runtime_fds):
                    os.read(fd, 1024)
                stale_fds = (*cloned_jail.standalone_runtime_fds, *cloned_probe.standalone_runtime_fds)
            # Cloned fds must be closed on exit; template fds remain valid at offset 0.
            for fd in stale_fds:
                with pytest.raises(OSError):
                    os.fstat(fd)
            seat_jail.verify_standalone_runtime_projection(jail)
            # A second invocation gets brand-new offset-0 descriptors.
            with pi._fresh_window_launch_jails(seat) as (second_jail, second_probe):
                seat_jail.verify_standalone_runtime_projection(second_jail)
                seat_jail.verify_standalone_runtime_projection(second_probe)
        finally:
            seat_jail.close_jail_fds(jail)
            seat_jail.close_jail_fds(probe)


# --- 5. Owned admission path & nonzero-offset regression test ------------------------


def test_owned_admission_path_refuses_nonzero_projection_offset_without_spawning(tmp_path, monkeypatch):
    """Held runtime stays valid on disk, but a per-invocation projection fd has a nonzero
    offset: `launch_owned` must fail closed before spawning any process."""
    target = _make_target(tmp_path)
    home = tmp_path / "operator"
    home.mkdir(mode=0o700)
    cwd = tmp_path / "work"
    cwd.mkdir(mode=0o755)

    spawned: list[object] = []

    def _forbid_popen(*args, **kwargs):
        spawned.append((args, kwargs))
        raise AssertionError("provider must never spawn when projection fd offset is nonzero")

    monkeypatch.setattr(subprocess, "Popen", _forbid_popen)
    monkeypatch.setattr(pi, "_require_owner_platform", lambda: None)
    monkeypatch.setattr(pi, "_probes_seat", lambda *a, **k: False)

    with runtime.open_runtime(target / "bin/codex") as admitted:
        with pi._seat_command_profile(
            [admitted.subject_source, "exec", "--help"],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            cwd=cwd,
            role=pi.SeatLaunchRole.PROVIDER_ADMIN,
            standalone_runtime=admitted,
        ) as (command, profile):
            assert command[0] == runtime.CODEX_RUNTIME_DESTINATIONS[0]
            assert profile.standalone_runtime is admitted
            assert profile.standalone_runtime_projection is not None
            # No host codex-resources directory or pathname runtime bind in mount_args:
            assert not any("codex-resources" in arg for arg in profile.mount_args)
            assert admitted.subject_source not in profile.mount_args

            # Advance one per-invocation projection fd while held runtime stays valid on disk.
            proj_fd = profile.standalone_runtime_projection.pass_fds[0]
            assert os.lseek(proj_fd, 1, os.SEEK_SET) == 1
            admitted.revalidate()  # held runtime itself is still completely valid

            with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
                pi.launch_owned(
                    command,
                    role=pi.SeatLaunchRole.PROVIDER_ADMIN,
                    profile=profile,
                    cwd=cwd,
                )
            assert caught.value.code == IDENTITY
            assert spawned == []


def test_codex_admission_gate_returns_typed_identity_refusal_not_inventory_failed(tmp_path, monkeypatch):
    target = _make_target(tmp_path)
    # Make an ancestor group-writable so standalone validation refuses identity.
    (tmp_path / "npm").chmod(0o775)
    home = tmp_path / "operator"
    auth = home / ".codex/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps(_login(claims=_claims(exp=int(time.time()) + 7200))), encoding="utf-8")
    auth.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(cred, "auth_path", lambda env=None: auth)
    subject = SeatSubject("codex", "standalone", target / "bin/codex", None, None)
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (subject, None))
    verdict = seat_profile_codex.codex_admission_gate("codex", {"HOME": str(home)}, True)
    assert verdict is not None
    assert verdict.status == "refuses"
    assert verdict.code == IDENTITY


def test_prepare_jailed_codex_fails_closed_when_subject_runtime_returns_non_runtime(tmp_path, monkeypatch):
    review = tmp_path / "review"
    tree = review / "reviewed-tree"
    tree.mkdir(parents=True)
    tree_fd = seat_jail.open_dir_nofollow(tree)
    try:
        digest = seat_jail.tree_manifest_sha256_at(tree_fd)
    finally:
        os.close(tree_fd)
    subject = SeatSubject("codex", "standalone", tmp_path / "codex", None, None)
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (subject, None))
    monkeypatch.setattr(runtime, "subject_runtime", lambda *a: object())
    proxy = SimpleNamespace(ca_cert=tmp_path / "ca.pem", proxy_url="http://srt:tok@127.0.0.1:3128")
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        pi._prepare_jailed_codex(
            review,
            tmp_path / "seat",
            SimpleNamespace(staged_tree_sha256=digest),
            1,
            1,
            ("bundle", "instructions"),
            proxy,
            env={"HOME": str(tmp_path)},
        )
    assert caught.value.code == IDENTITY
    assert not (tmp_path / "seat").exists()


def test_owned_admission_path_rejects_conflicting_session_dependency(tmp_path, monkeypatch):
    target = _make_target(tmp_path)
    monkeypatch.setattr(
        "phase_loop_runtime.executable_dependency_startup.current_dependency_for_provider",
        lambda *a, **k: object(),
    )
    with runtime.open_runtime(target / "bin/codex") as admitted:
        with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
            with pi._seat_command_profile(
                [admitted.subject_source, "exec", "--help"],
                env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                cwd=tmp_path,
                role=pi.SeatLaunchRole.PROVIDER_ADMIN,
                standalone_runtime=admitted,
            ):
                pass
        assert caught.value.code == IDENTITY
