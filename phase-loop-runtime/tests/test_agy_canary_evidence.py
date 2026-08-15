from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime import agy_canary_evidence as evidence
from phase_loop_runtime import cli
from phase_loop_runtime.cli import main


_REAL_ASSERT_QUIESCENT = evidence._assert_quiescent
_requires_memfd = pytest.mark.skipif(
    not hasattr(os, "memfd_create") or evidence.fcntl is None or
    not getattr(os, "MFD_ALLOW_SEALING", 0),
    reason="Linux sealed memfd support required",
)


def _private_root(tmp_path: Path) -> Path:
    root = Path("/tmp") / f"phase-loop-agy-canary.test-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    return root


def _evidence_masking(tmp_path: Path) -> dict[str, object]:
    root = _private_root(tmp_path)
    canonical, root_fd = evidence._validate_private_root(root)
    try:
        return evidence._evidence_root_masking_authority(canonical, root_fd)
    finally:
        os.close(root_fd)


def _settings(tmp_path: Path, allow: list[str]) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {"allow": allow, "deny": ["command(rm)"]},
                "toolPermission": "request-review",
                "allowNonWorkspaceAccess": False,
                "unrelated": {"preserved": [1, 2, 3]},
            },
            indent=2,
        )
        + "\n"
    )
    path.chmod(0o600)
    return path


def _use_empty_process_inventory(monkeypatch, tmp_path: Path) -> None:
    proc_root = tmp_path / "empty-proc"
    proc_root.mkdir(exist_ok=True)

    def inspect_empty_proc(settings, *, block_all_agy_processes):
        return _REAL_ASSERT_QUIESCENT(
            settings,
            block_all_agy_processes=block_all_agy_processes,
            proc_root=proc_root,
        )

    monkeypatch.setattr(evidence, "_assert_quiescent", inspect_empty_proc)


def _source_inventory(tmp_path: Path) -> dict[str, object]:
    return evidence.freeze_customization_inventory(home=tmp_path, project_dir=tmp_path, env={})


def _git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)


def _installation_identity() -> dict[str, object]:
    interpreter_authority = evidence._system_interpreter_authority()
    uv_store_authority = evidence._uv_store_authority(
        account_home=evidence._account_home()
    )
    tool_dir = Path(uv_store_authority["directories"]["tool"]["path"])
    environment_root = tool_dir / "phase-loop-runtime"
    return {
        "uv_executable": "/tool/bin/uv", "uv_tool_dir": str(tool_dir),
        "console_script": str(environment_root / "bin" / "phase-loop"),
        "interpreter": interpreter_authority["path"],
        "version": "0.7.14",
        "distribution_root": str(environment_root / "lib" / "python" / "site-packages"),
        "module_origin": str(environment_root / "lib" / "python" / "site-packages" / "phase_loop_runtime" / "__init__.py"),
        "environment_root": str(environment_root),
        "console_script_sha256": "b" * 64,
        "interpreter_sha256": interpreter_authority["sha256"],
        "interpreter_authority": interpreter_authority,
        "uv_store_authority": uv_store_authority,
        "package_tree_sha256": "d" * 64, "record_sha256": "e" * 64,
        "provenance": {
            "schema": "uv_registry_receipt.v1", "requirement": "phase-loop-runtime==0.7.14",
            "receipt_sha256": "a" * 64,
        },
    }


def _record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def _synthetic_wheel(
    *, members: dict[str, bytes] | None = None, record_rows: list[list[str]] | None = None,
) -> bytes:
    dist_info = "phase_loop_runtime-0.7.14.dist-info"
    payload = {
        "phase_loop_runtime/__init__.py": b'__version__ = "0.7.14"\n',
        f"{dist_info}/METADATA": b"Name: phase-loop-runtime\nVersion: 0.7.14\n",
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist_info}/entry_points.txt": b"[console_scripts]\nphase-loop = phase_loop_runtime.cli:main\ncodex-phase-loop = phase_loop_runtime.cli:main\n",
        "phase_loop_runtime-0.7.14.data/data/share/phase-loop-runtime/protocol/protocol.md": b"protocol\n",
    }
    if members:
        payload.update(members)
    if record_rows is None:
        record_rows = [
            [path, _record_hash(data), str(len(data))]
            for path, data in sorted(payload.items())
        ] + [[f"{dist_info}/RECORD", "", ""]]
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(record_rows)
    payload[f"{dist_info}/RECORD"] = output.getvalue().encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for path, data in payload.items():
            wheel.writestr(path, data)
    return archive.getvalue()


def _release_identity(*, wheel: bytes | None = None) -> dict[str, object]:
    wheel = _synthetic_wheel() if wheel is None else wheel
    wheel_filename = "phase_loop_runtime-0.7.14-py3-none-any.whl"
    wheel_digest = evidence._sha256(wheel)
    wheel_url_sha256 = evidence._sha256(b"https://example.invalid/wheel")
    binding = evidence._wheel_binding(
        wheel_bytes=wheel, filename=wheel_filename, digest=wheel_digest,
        url_sha256=wheel_url_sha256, version="0.7.14",
    )
    return {
        "version": "0.7.14", "handoff_commit": "a" * 40, "release_commit": "b" * 40,
        "tag_object": "c" * 40, "tag_peel": "b" * 40,
        "artifacts": [
            {"filename": wheel_filename, "packagetype": "bdist_wheel", "sha256": wheel_digest, "url_sha256": wheel_url_sha256},
            {"filename": "phase_loop_runtime-0.7.14.tar.gz", "packagetype": "sdist", "sha256": "f" * 64, "url_sha256": "0" * 64},
        ],
        "wheel_binding": binding,
    }


def _installed_wheel_fixture(
    tmp_path: Path, *, wheel: bytes | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, Path]]:
    wheel = _synthetic_wheel() if wheel is None else wheel
    release = _release_identity(wheel=wheel)
    account_home = tmp_path / "account-home"
    (account_home / ".local" / "share" / "uv" / "tools").mkdir(parents=True)
    (account_home / ".local" / "share" / "uv" / "python").mkdir(parents=True)
    (account_home / ".local" / "bin").mkdir(parents=True)
    (account_home / ".cache" / "uv").mkdir(parents=True)
    uv_store_authority = evidence._uv_store_authority(
        account_home=account_home, workspace_root=tmp_path / "no-workspace",
    )
    tool_dir = Path(uv_store_authority["directories"]["tool"]["path"])
    environment_root = tool_dir / "phase-loop-runtime"
    root = environment_root / "lib" / "python3.13" / "site-packages"
    paths: dict[str, Path] = {}
    installed_rows: list[list[str]] = []
    binding = release["wheel_binding"]
    assert isinstance(binding, dict)
    for row in binding["files"]:
        base = environment_root if row["scheme"] == "data" else root
        target = base / row["installed_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            data = archive.read(row["wheel_path"])
        target.write_bytes(data)
        relative = os.path.relpath(target, root).replace(os.sep, "/")
        installed_rows.append([relative, _record_hash(data), str(len(data))])
        paths[row["wheel_path"]] = target
    dist_info = root / "phase_loop_runtime-0.7.14.dist-info"
    interpreter = environment_root / "bin" / "python"
    interpreter_authority = evidence._system_interpreter_authority()
    generated = {
        dist_info / "INSTALLER": b"uv",
        dist_info / "REQUESTED": b"",
        dist_info / "uv_cache.json": (
            b'{"timestamp":{"secs_since_epoch":1,"nanos_since_epoch":0},'
            b'"commit":null,"tags":null,"env":{},"directories":{}}'
        ),
        environment_root / "bin" / "phase-loop": evidence._uv_console_script_bytes(
            interpreter=interpreter, target="phase_loop_runtime.cli:main"
        ),
        environment_root / "bin" / "codex-phase-loop": evidence._uv_console_script_bytes(
            interpreter=interpreter, target="phase_loop_runtime.cli:main"
        ),
    }
    for target, data in generated.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o700 if target.parent.name == "bin" else 0o600)
        relative = os.path.relpath(target, root).replace(os.sep, "/")
        installed_rows.append([relative, _record_hash(data), str(len(data))])
    record = dist_info / "RECORD"
    installed_rows.append([os.path.relpath(record, root).replace(os.sep, "/"), "", ""])
    record_output = io.StringIO(newline="")
    csv.writer(record_output, lineterminator="\n").writerows(installed_rows)
    record.write_bytes(record_output.getvalue().encode())
    interpreter.symlink_to(interpreter_authority["path"])
    module = root / "phase_loop_runtime" / "__init__.py"
    installation = {
        "uv_executable": str(tmp_path / "bin" / "uv"),
        "uv_tool_dir": str(tool_dir),
        "console_script": str(environment_root / "bin" / "phase-loop"),
        "interpreter": interpreter_authority["path"], "version": "0.7.14",
        "distribution_root": str(root), "module_origin": str(module),
        "environment_root": str(environment_root),
        "console_script_sha256": evidence._sha256(generated[environment_root / "bin" / "phase-loop"]),
        "interpreter_sha256": interpreter_authority["sha256"],
        "interpreter_authority": interpreter_authority,
        "uv_store_authority": uv_store_authority,
        "package_tree_sha256": evidence._runtime_tree_sha256(module.parent),
        "record_sha256": evidence._sha256(record.read_bytes()),
        "provenance": {
            "schema": "uv_registry_receipt.v1",
            "requirement": "phase-loop-runtime==0.7.14",
            "receipt_sha256": "a" * 64,
        },
    }
    paths.update({"record": record, "console": environment_root / "bin" / "phase-loop"})
    return release, installation, paths


def _bootstrap_receipt(
    *, installation: dict[str, object], dotfiles_repo: Path,
    evidence_root: Path | None = None,
    plan_bytes: bytes = b"review this\n",
    repo_head: str = "d" * 40, blobs: dict[str, str] | None = None,
    input_sha256: dict[str, str] | None = None,
) -> dict[str, object]:
    dotfiles_repo.mkdir(parents=True, exist_ok=True)
    bootstrap_path = dotfiles_repo / "bootstrap.sh"
    if not bootstrap_path.exists():
        bootstrap_path.write_bytes(b"#!/bin/sh\n")
    interpreter_authority = installation["interpreter_authority"]
    assert isinstance(interpreter_authority, dict)
    uv_store_authority = installation["uv_store_authority"]
    assert isinstance(uv_store_authority, dict)
    uv_executable = Path(str(installation["uv_executable"]))
    uv_environment = {
        "HOME": str(uv_store_authority["account_home"]),
        "PATH": str(uv_executable.parent) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "UV_TOOL_DIR": str(uv_store_authority["directories"]["tool"]["path"]),
        "UV_TOOL_BIN_DIR": str(uv_store_authority["directories"]["bin"]["path"]),
        "UV_CACHE_DIR": str(uv_store_authority["directories"]["cache"]["path"]),
        "UV_PYTHON_INSTALL_DIR": str(uv_store_authority["directories"]["python"]["path"]),
        "UV_PYTHON": str(interpreter_authority["path"]),
        "UV_PYTHON_DOWNLOADS": "never",
    }
    paths = ("bootstrap.sh", "shared/agent-harness.pin", "plans/manifest.json", "plans/canary.md")
    blobs = {name: "a" * 40 for name in paths} if blobs is None else blobs
    input_sha256 = {
        "bootstrap.sh": evidence._sha256(b"#!/bin/sh\n"),
        "shared/agent-harness.pin": evidence._sha256(b"v0.7.14\n"),
        "plans/manifest.json": evidence._sha256(b"{}\n"),
        "plans/canary.md": evidence._sha256(plan_bytes),
    } if input_sha256 is None else input_sha256
    if (dotfiles_repo / ".git").exists():
        snapshot = evidence._git_tree_snapshot(
            dotfiles_repo.resolve(strict=True), repo_head, materialize=False,
        )
        tree_snapshot = snapshot.authority
    else:
        tree_snapshot = {
            "schema": evidence._TREE_SNAPSHOT_SCHEMA, "commit": repo_head,
            "tree_oid": "b" * 40, "mount_path": str(dotfiles_repo.resolve(strict=True)),
            "inventory_sha256": "c" * 64, "entry_count": 1, "file_count": 1,
            "executable_count": 1, "symlink_count": 0, "gitlink_count": 0,
            "submodules": [],
        }
        snapshot = None
    mask_root = evidence_root or Path("/tmp") / (
        f"phase-loop-agy-mask-fixture-{os.getpid()}-" +
        evidence._sha256(str(dotfiles_repo).encode())[:12]
    )
    mask_root.mkdir(mode=0o700, exist_ok=True)
    mask_root.chmod(0o700)
    canonical_mask_root, mask_fd = evidence._validate_private_root(mask_root)
    try:
        evidence_root_masking = evidence._evidence_root_masking_authority(
            canonical_mask_root, mask_fd,
        )
    finally:
        os.close(mask_fd)
    if snapshot is not None:
        _argv, sandbox = evidence._tree_snapshot_bwrap_argv(
            snapshot=snapshot, bwrap=Path("/usr/bin/bwrap"), bash=Path("/usr/bin/bash"),
            environment=uv_environment,
            account_home=Path(str(uv_store_authority["account_home"])),
            uv_store_authority=uv_store_authority,
            evidence_root_masking=evidence_root_masking, identity_only=True,
        )
    else:
        sandbox = {
            "schema": evidence._TREE_SANDBOX_SCHEMA, "executable": "/usr/bin/bwrap",
            "argv_sha256": "d" * 64, "argv_count": 20, "argv_bytes": 500,
            "passed_fd_count": tree_snapshot["file_count"],
            "root": "read_only", "network": "shared",
            "mount_path": str(dotfiles_repo.resolve(strict=True)),
            "command": ["/usr/bin/bash", str(bootstrap_path.resolve(strict=True))],
            "writable_binds": sorted({
                str(uv_store_authority["account_home"]),
                *([] if uv_store_authority["workspace"] is None else [
                    str(uv_store_authority["workspace"]["resolved"]),
                ]),
            }),
            "tmpfs": ["/tmp", "/run", str(dotfiles_repo.resolve(strict=True))],
            "environment_sha256": evidence._sha256(evidence._canonical_json(uv_environment)),
            "evidence_root_masking": evidence_root_masking,
        }
    return {
        "schema": "agy_canary_bootstrap_attestation.v1", "repo_head": repo_head,
        "tree_snapshot": tree_snapshot,
        "blobs": blobs, "input_sha256": input_sha256,
        "targets": {"plan": "plans/canary.md", "manifest": "plans/manifest.json"},
        "bootstrap": {
            "sandbox": sandbox,
            "pid": 1, "returncode": 0,
            "script_sha256": input_sha256["bootstrap.sh"], "script_blob": blobs["bootstrap.sh"],
            "before_uv_tools_sha256": "e" * 64, "after_uv_tools_sha256": "f" * 64,
            "environment_names": [
                "HOME", "PATH", "UV_CACHE_DIR", "UV_PYTHON",
                "UV_PYTHON_DOWNLOADS", "UV_PYTHON_INSTALL_DIR",
                "UV_TOOL_BIN_DIR", "UV_TOOL_DIR",
            ],
            "uv_environment": uv_environment,
            "interpreter_authority": interpreter_authority,
            "uv_store_authority": uv_store_authority,
            "local_source_seams": {
                "bootstrap.local.sh": "absent",
                "hooks/post-bootstrap.local.sh": "absent",
            },
            "installation": installation,
        },
    }


def _probe_runtime_record() -> dict[str, object]:
    source = Path("/bin/true").resolve(strict=True)
    info = source.stat()
    return {
        "path": str(source), "device": info.st_dev, "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode), "sha256": evidence._sha256(source.read_bytes()),
        "version": "1.1.13",
    }


def test_uv_registry_receipt_binds_normal_tool_install_requirement(tmp_path):
    tool_dir = tmp_path / "uv-tools"
    receipt = tool_dir / "phase-loop-runtime" / "uv-receipt.toml"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        '[tool]\nrequirements = [{ name = "phase-loop-runtime", specifier = "==0.7.14" }]\n'
        'entrypoints = [{ name = "phase-loop", install-path = "/tmp/phase-loop", from = "phase-loop-runtime" }]\n'
    )
    provenance = evidence._uv_registry_provenance(tool_dir=tool_dir, version="0.7.14")
    assert provenance["requirement"] == "phase-loop-runtime==0.7.14"
    assert provenance["receipt_sha256"] == evidence._sha256(receipt.read_bytes())
    receipt.write_text('[tool]\nrequirements = [{ name = "phase-loop-runtime", specifier = "==0.7.13" }]\n')
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="does not pin"):
        evidence._uv_registry_provenance(tool_dir=tool_dir, version="0.7.14")


def test_clean_settings_cli_removes_exact_rule_and_preserves_structure(
    tmp_path, capsys, monkeypatch,
):
    root = _private_root(tmp_path)
    try:
        _use_empty_process_inventory(monkeypatch, tmp_path)
        settings = _settings(tmp_path, ["command(pwd)"])
        original_info = settings.stat()
        before = json.loads(settings.read_text())
        rc = main(
            [
                "agy-canary-clean-settings",
                "--evidence-root",
                str(root),
                "--settings-path",
                str(settings),
                "--maintenance-lock",
                str(tmp_path / "maintenance.lock"),
            ]
        )
        assert rc == 0
        status = json.loads(capsys.readouterr().out)
        assert status["state"] == "committed"
        assert status["result"] == "removed_exact_rule"
        assert status["structural_delta_valid"] is True
        after = json.loads(settings.read_text())
        before["permissions"]["allow"] = []
        assert after == before
        after_info = settings.stat()
        assert (
            after_info.st_uid, after_info.st_gid, stat.S_IMODE(after_info.st_mode),
        ) == (
            original_info.st_uid, original_info.st_gid,
            stat.S_IMODE(original_info.st_mode),
        )
        snapshot = root / "agy-settings.pre.json"
        assert not snapshot.is_symlink()
        assert json.loads(snapshot.read_text())["permissions"]["allow"] == ["command(pwd)"]
        state = json.loads((root / "cleanup-state.json").read_text())
        assert state["state"] == "committed"
        assert state["transitions"] == [
            "prepared",
            "exchanged_unverified",
            "verified",
            "committed",
        ]
        assert not list(tmp_path.glob(".phase-loop-agy-settings.*.tmp"))
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_clean_settings_cli_records_already_absent(tmp_path, capsys, monkeypatch):
    root = _private_root(tmp_path)
    try:
        _use_empty_process_inventory(monkeypatch, tmp_path)
        settings = _settings(tmp_path, [])
        original = settings.read_bytes()
        rc = main(
            [
                "agy-canary-clean-settings",
                "--evidence-root",
                str(root),
                "--settings-path",
                str(settings),
                "--maintenance-lock",
                str(tmp_path / "maintenance.lock"),
            ]
        )
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["result"] == "already_absent"
        assert settings.read_bytes() == original
        assert json.loads((root / "cleanup-state.json").read_text())["transitions"] == [
            "prepared",
            "verified",
            "committed",
        ]
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


@pytest.mark.parametrize(
    "payload",
    [
        {"permissions": {"allow": ["command(pwd)", "command(git)"]}},
        {"permissions": {"allow": ["command(pwd)", "command(pwd)"]}},
        {"permissions": {"allow": []}, "toolPermission": "always-proceed"},
        {"permissions": {"allow": []}, "allowNonWorkspaceAccess": True},
    ],
)
def test_clean_settings_fails_closed_without_mutation(tmp_path, payload):
    root = _private_root(tmp_path)
    try:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(payload))
        settings.chmod(0o600)
        original = settings.read_bytes()
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            evidence.clean_settings(
                evidence_root=root,
                settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        assert not (root / "agy-settings.pre.json").exists()
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_clean_settings_rejects_symlinked_evidence_root(tmp_path):
    target = _private_root(tmp_path)
    link = Path("/tmp") / f"phase-loop-agy-canary.link-{os.getpid()}-{tmp_path.name}"
    link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="real directory"):
            evidence.clean_settings(
                evidence_root=link,
                settings_path=_settings(tmp_path, []),
                maintenance_lock=tmp_path / "maintenance.lock",
            )
    finally:
        link.unlink()
        target.rmdir()


def test_clean_settings_rolls_back_after_exchange_failure(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        _use_empty_process_inventory(monkeypatch, tmp_path)
        settings = _settings(tmp_path, ["command(pwd)"])
        original = settings.read_bytes()
        real_validate = evidence._validate_opened_settings
        injected = False

        def fail_destination(opened, *, name, expected_data):
            nonlocal injected
            if not injected and opened.name != name and name == settings.name:
                injected = True
                raise evidence.AgyCanaryEvidenceError("injected post-exchange failure")
            return real_validate(opened, name=name, expected_data=expected_data)

        monkeypatch.setattr(evidence, "_validate_opened_settings", fail_destination)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="injected"):
            evidence.clean_settings(
                evidence_root=root,
                settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        assert injected
        state = json.loads((root / "cleanup-state.json").read_text())
        assert state["state"] == "rolled_back"
        assert state["transitions"][-2:] == ["rollback_required", "rolled_back"]
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_clean_settings_rejects_a_preexisting_open_handle(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    _use_empty_process_inventory(monkeypatch, tmp_path)
    settings = _settings(tmp_path, ["command(pwd)"])
    original = settings.read_bytes()
    extra_fd = os.open(settings, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="lease is unavailable: original"):
            evidence.clean_settings(
                evidence_root=root, settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        assert not (root / "agy-settings.pre.json").exists()
    finally:
        os.close(extra_fd)
        shutil.rmtree(root)


def test_clean_settings_detects_a_conflicting_open_lease_break(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    _use_empty_process_inventory(monkeypatch, tmp_path)
    settings = _settings(tmp_path, ["command(pwd)"])
    original = settings.read_bytes()
    real_create = evidence._create_replacement
    conflict_returncode = None

    def create_then_conflict(*, settings, name, data):
        nonlocal conflict_returncode
        replacement = real_create(settings=settings, name=name, data=data)
        conflict = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import errno, os, sys; "
                    "path=sys.argv[1]; "
                    "\ntry: os.close(os.open(path, os.O_RDONLY | os.O_NONBLOCK))"
                    "\nexcept OSError as exc: sys.exit(0 if exc.errno in "
                    "{errno.EAGAIN, errno.EWOULDBLOCK} else 2)"
                    "\nelse: sys.exit(3)"
                ),
                str(settings_path),
            ],
            check=False,
        )
        conflict_returncode = conflict.returncode
        return replacement

    settings_path = settings
    monkeypatch.setattr(evidence, "_create_replacement", create_then_conflict)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="lease broke: original"):
            evidence.clean_settings(
                evidence_root=root, settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert conflict_returncode == 0
        assert settings.read_bytes() == original
        assert not list(tmp_path.glob(".phase-loop-agy-settings.*.tmp"))
    finally:
        shutil.rmtree(root)


def test_clean_settings_rejects_replacement_ownership_drift(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    _use_empty_process_inventory(monkeypatch, tmp_path)
    settings = _settings(tmp_path, ["command(pwd)"])
    original = settings.read_bytes()
    real_create = evidence._create_replacement

    def create_with_wrong_owner_authority(*, settings, name, data):
        opened = real_create(settings=settings, name=name, data=data)
        return replace(opened, uid=opened.uid + 1)

    monkeypatch.setattr(
        evidence, "_create_replacement", create_with_wrong_owner_authority,
    )
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="ownership drifted"):
            evidence.clean_settings(
                evidence_root=root, settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        assert not list(tmp_path.glob(".phase-loop-agy-settings.*.tmp"))
    finally:
        shutil.rmtree(root)


def test_write_lease_contract_detects_persistent_rename_only_drift(
    tmp_path, monkeypatch,
):
    """Transient hostile same-UID rename-and-restore remains outside the contract."""
    root = _private_root(tmp_path)
    _use_empty_process_inventory(monkeypatch, tmp_path)
    settings = _settings(tmp_path, ["command(pwd)"])
    moved = settings.with_suffix(".moved")
    real_create = evidence._create_replacement

    def create_then_rename(*, settings, name, data):
        opened = real_create(settings=settings, name=name, data=data)
        settings_path.rename(moved)
        return opened

    settings_path = settings
    monkeypatch.setattr(evidence, "_create_replacement", create_then_rename)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="path identity drifted"):
            evidence.clean_settings(
                evidence_root=root, settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert moved.is_file()
        assert not list(tmp_path.glob(".phase-loop-agy-settings.*.tmp"))
    finally:
        if moved.exists():
            moved.rename(settings)
        shutil.rmtree(root)


@pytest.mark.parametrize("effective_uid", (0, os.geteuid() + 1))
def test_open_settings_rejects_root_or_nonowner_execution(
    tmp_path, monkeypatch, effective_uid,
):
    settings = _settings(tmp_path, [])
    monkeypatch.setattr(evidence.os, "geteuid", lambda: effective_uid)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="non-root settings owner"):
        evidence._open_settings(settings)


def test_write_lease_requires_one_signal_clean_main_thread(monkeypatch):
    monkeypatch.setattr(evidence.threading, "active_count", lambda: 2)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="one signal-clean main thread"):
        evidence._begin_lease_signal_guard()


def test_clean_settings_blocks_when_agy_process_is_active(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, ["command(pwd)"])

        def blocked(*_args, **_kwargs):
            raise evidence.AgyCanaryEvidenceError("settings tree is not quiescent: pid=123,process=agy")

        monkeypatch.setattr(evidence, "_assert_quiescent", blocked)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="not quiescent"):
            evidence.clean_settings(
                evidence_root=root,
                settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert json.loads(settings.read_text())["permissions"]["allow"] == ["command(pwd)"]
        assert not (root / "agy-settings.pre.json").exists()
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


@pytest.mark.parametrize(
    ("blocked_scan", "last_state"),
    ((2, "prepared"), (3, "rolled_back")),
)
def test_clean_settings_blocks_agy_relaunch_before_commit(
    tmp_path, monkeypatch, blocked_scan, last_state,
):
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, ["command(pwd)"])
    original = settings.read_bytes()
    scans = 0

    def block_relaunch(*_args, **_kwargs):
        nonlocal scans
        scans += 1
        if scans == blocked_scan:
            raise evidence.AgyCanaryEvidenceError(
                "settings tree is not quiescent: pid=456,process=agy"
            )

    monkeypatch.setattr(evidence, "_assert_quiescent", block_relaunch)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="not quiescent"):
            evidence.clean_settings(
                evidence_root=root, settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert scans == blocked_scan
        assert settings.read_bytes() == original
        state = json.loads((root / "cleanup-state.json").read_text())
        assert state["state"] == last_state
        assert not list(tmp_path.glob(".phase-loop-agy-settings.*.tmp"))
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    ("surface", "message"),
    [
        ("uid-status", "surface=uid-status"),
        ("uid-classification", "surface=uid-classification"),
        ("cmdline", "surface=cmdline"),
    ],
)
def test_clean_settings_rejects_unreadable_process_inventory_before_mutation(
    tmp_path, monkeypatch, surface, message,
):
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, ["command(pwd)"])
    original = settings.read_bytes()
    proc_root = tmp_path / "proc"
    pid_dir = proc_root / "424242"
    pid_dir.mkdir(parents=True)
    status = pid_dir / "status"
    status.write_text(f"Name:\ttest\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n")
    (pid_dir / "cmdline").write_bytes(b"/usr/bin/other\0")

    if surface == "uid-status":
        real_read_text = Path.read_text

        def deny_status(path, *args, **kwargs):
            if path == status:
                raise PermissionError("denied status")
            return real_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", deny_status)
    elif surface == "uid-classification":
        status.write_text("Name:\ttest\nUid:\tmalformed\n")
    elif surface == "cmdline":
        real_read_bytes = Path.read_bytes

        def deny_read_bytes(path):
            if path == pid_dir / "cmdline":
                raise PermissionError("denied cmdline")
            return real_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", deny_read_bytes)
    real_assert_quiescent = evidence._assert_quiescent

    def inspect_fake_proc(settings_value, *, block_all_agy_processes):
        return real_assert_quiescent(
            settings_value,
            block_all_agy_processes=block_all_agy_processes,
            proc_root=proc_root,
        )

    monkeypatch.setattr(evidence, "_assert_quiescent", inspect_fake_proc)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match=message):
            evidence.clean_settings(
                evidence_root=root, settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        assert not (root / "agy-settings.pre.json").exists()
        assert not (root / "cleanup-state.json").exists()
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_quiescence_ignores_real_foreign_uid_pid_one(tmp_path):
    real_pid = Path("/proc/1")
    process_uids = evidence._process_uids(real_pid)
    if process_uids is None:
        pytest.skip("PID 1 exited during read-only inventory test")
    settings_path = _settings(tmp_path, ["command(pwd)"])
    settings = evidence._open_settings(settings_path)
    if settings.uid in process_uids:
        os.close(settings.fd)
        os.close(settings.parent_fd)
        pytest.skip("PID 1 is not a foreign-UID process on this host")
    proc_root = tmp_path / "real-proc"
    proc_root.mkdir()
    (proc_root / "1").symlink_to(real_pid, target_is_directory=True)
    try:
        evidence._assert_quiescent(
            settings, block_all_agy_processes=True,
            proc_root=proc_root,
        )
    finally:
        os.close(settings.fd)
        os.close(settings.parent_fd)


def test_quiescence_ignores_unreadable_fd_inventory_for_real_sd_pam(tmp_path):
    settings_path = _settings(tmp_path, ["command(pwd)"])
    settings = evidence._open_settings(settings_path)
    candidate = None
    try:
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                process_uids = evidence._process_uids(pid_dir)
                command_name = (pid_dir / "comm").read_text().strip()
            except (OSError, UnicodeError):
                continue
            if process_uids is None or settings.uid not in process_uids:
                continue
            if command_name not in {"(sd-pam)", "sd-pam"}:
                continue
            try:
                list((pid_dir / "fd").iterdir())
            except PermissionError:
                candidate = pid_dir
                break
        if candidate is None:
            pytest.skip("no same-UID sd-pam with unreadable FD inventory on this host")
        proc_root = tmp_path / "real-proc"
        proc_root.mkdir()
        (proc_root / candidate.name).symlink_to(candidate, target_is_directory=True)
        evidence._assert_quiescent(
            settings, block_all_agy_processes=True, proc_root=proc_root,
        )
    finally:
        os.close(settings.fd)
        os.close(settings.parent_fd)


def test_capture_reducer_requires_complete_sealed_staged_reads(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = None
        try:
            review = tmp_path / "review"
            review.mkdir()
            instructions = review / "review-instructions.md"
            bundle = review / "review-bundle.md"
            instructions.write_text("read this first\n")
            bundle.write_text("review this\n")
            instructions.chmod(0o600)
            bundle.chmod(0o600)
            capture = _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", plan_bytes=bundle.read_bytes(),
            )
            _bind_stage(capture, review)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s1", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
                {"sequence": 1, "session_id": "s1", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "read this first\n"},
                {"sequence": 2, "session_id": "s1", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s1", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "review this\n"},
                {"sequence": 4, "session_id": "s1", "type": "terminal", "text": "Looks good\nAGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret prompt"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
            synthetic_board = _usable_private_board({"gemini_seat_key": "gemini-primary"})
            synthetic_board["legs"][0]["text"] = "Looks good\nAGREE"
            _seal_synthetic_provider_results(capture, synthetic_board)
            evidence.write_private_board(
                capture=capture,
                basename="board.json",
                payload={**synthetic_board, "agy_canary_capture": evidence.capture_summary(capture)},
            )
        finally:
            if capture is not None:
                capture.close()
        proof = evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
        assert proof["attempt_ids"] == ["gemini-1"]
        assert proof["attempts"][0]["counts"] == {"command": 0, "unsandboxed": 0, "non_read_tool": 0, "out_of_stage_read": 0}
        _root, root_fd = evidence._validate_private_root(root)
        try:
            registry = evidence._provider_registry(root_fd=root_fd)
            gemini = next(entry for entry in registry["entries"] if entry["provider"] == "gemini")
            result = evidence._read_json_at(root_fd, gemini["result_name"])
            retry = json.loads(json.dumps(result))
            retry["attempts"]["attempts"].append({"index": 1, **retry["attempts"]["launch"]})
            retry["attempts"]["terminal_attempt"] = 1
            evidence._write_replace_at(root_fd, gemini["result_name"], retry)
            assert evidence._verified_provider_results(root_fd=root_fd)[("gemini", "gemini-primary")]["status"] == "OK"
            too_many = json.loads(json.dumps(retry))
            too_many["attempts"]["attempts"].append({"index": 2, **too_many["attempts"]["launch"]})
            too_many["attempts"]["terminal_attempt"] = 2
            evidence._write_replace_at(root_fd, gemini["result_name"], too_many)
            with pytest.raises(evidence.AgyCanaryEvidenceError, match="attempt limit"):
                evidence._verified_provider_results(root_fd=root_fd)
            result["attempts"] = {"launch": None, "attempts": [], "terminal_attempt": None}
            evidence._write_replace_at(root_fd, gemini["result_name"], result)
            with pytest.raises(evidence.AgyCanaryEvidenceError, match="lacks an actual review attempt"):
                evidence._verified_provider_results(root_fd=root_fd)
        finally:
            os.close(root_fd)
    finally:
        shutil.rmtree(root)


def test_capture_reducer_rejects_missing_or_swapped_private_board(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = None
        try:
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            capture = _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", plan_bytes=(review / "review-bundle.md").read_bytes(),
            )
            _bind_stage(capture, review)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "review-instructions.md"},
                {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "review-bundle.md"},
                {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
            _seal_synthetic_provider_results(
                capture, _usable_private_board({"gemini_seat_key": "gemini-primary"})
            )
            evidence.write_private_board(capture=capture, basename="board.json", payload=_usable_private_board(evidence.capture_summary(capture)))
            (root / "board.json").write_text('{"agy_canary_capture":"swapped"}')
        finally:
            if capture is not None:
                capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="private board payload bytes drifted"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    "events",
    [
        [
            {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
            {"sequence": 1, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
        ],
        [
            {"sequence": 0, "session_id": "s", "type": "terminal", "text": "AGREE"},
            {"sequence": 1, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        ],
    ],
)
def test_stream_rejects_interleaved_or_post_terminal_events(events):
    with pytest.raises(evidence.AgyCanaryEvidenceError):
        evidence._parse_stream("\n".join(json.dumps(event) for event in events).encode())


def test_stream_rejects_duplicate_staged_read_even_when_one_copy_has_right_content():
    events = [
        {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "wrong"},
        {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "right"},
        {"sequence": 4, "session_id": "s", "type": "tool_call", "call_id": "c", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
        {"sequence": 5, "session_id": "s", "type": "tool_result", "call_id": "c", "outcome": "success", "content": "bundle"},
        {"sequence": 6, "session_id": "s", "type": "terminal", "text": "AGREE"},
    ]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="exactly two staged reads"):
        evidence._parse_stream("\n".join(json.dumps(event) for event in events).encode(), require_staged_reads=True)


def _prepare_production_capture(
    *, monkeypatch, tmp_path: Path, root: Path, settings: Path, seat_key: str,
    auth_paths: tuple[Path, ...] = (), plan_bytes: bytes = b"review this\n",
    agy_runtime: dict[str, object] | None = None, before_prepare=None,
) -> evidence.AgyCanaryCapture:
    _use_empty_process_inventory(monkeypatch, tmp_path)
    evidence.clean_settings(
        evidence_root=root, settings_path=settings,
        maintenance_lock=tmp_path / "prepare-maintenance.lock",
    )
    staged = {}
    for name in ("review-instructions.md", "review-bundle.md"):
        retained = f"agy-capability-stage-{name}"
        raw_stage = name.encode()
        (root / retained).write_bytes(raw_stage)
        staged[name] = {"name": retained, "bytes": len(raw_stage), "sha256": evidence._sha256(raw_stage)}
    rows = []
    for class_name, tool, target, outcome in evidence._CAPABILITY_CLASSES:
        name = f"agy-capability-{class_name}.jsonl"
        raw = _capability_stream(class_name).encode()
        (root / name).write_bytes(raw)
        rows.append({
            "class": class_name, "tool": tool, "target": target,
            "attempt": True, "execution": True, "result": "text", "outcome": outcome,
            "stream": {"name": name, "bytes": len(raw), "sha256": evidence._sha256(raw)},
        })
    (root / "agy_capability_probe.json").write_text(json.dumps({
        "schema": "agy_capability_probe.v2", "agy_version": "1.1.13",
        "agy_runtime": agy_runtime or _probe_runtime_record(),
        "help_sha256": "a" * 64, "mode": "stream_json", "complete": True,
        "classes": rows, "staged": staged,
    }))
    installation = _installation_identity()
    monkeypatch.setattr(evidence, "_installed_phase_loop_identity", lambda **_kwargs: installation)
    (root / "agy_canary_bootstrap_attestation.json").write_text(json.dumps(
        _bootstrap_receipt(
            installation=installation, plan_bytes=plan_bytes,
            dotfiles_repo=tmp_path / "bootstrap-receipt-dotfiles",
        )
    ))
    release = _release_identity()
    monkeypatch.setattr(evidence, "_reconcile_release_lineage", lambda **_kwargs: release)
    monkeypatch.setattr(evidence, "_validate_installed_wheel_binding", lambda **_kwargs: None)
    harness = tmp_path / "agent-harness"
    harness.mkdir(exist_ok=True)
    if before_prepare is not None:
        before_prepare()
    evidence.prepare_canary(
        evidence_root=root, settings_path=settings, seat_key=seat_key,
        auth_paths=auth_paths, agent_harness_repo=harness, handoff_commit="d" * 40,
        customization_home=tmp_path, project_dir=tmp_path, source_env={},
    )
    return evidence.AgyCanaryCapture(*evidence._validate_private_root(root))


def _bind_stage(capture: evidence.AgyCanaryCapture, review: Path) -> None:
    evidence.bind_staged_review_inputs(
        capture=capture, review_dir=review,
        bundle_bytes=(review / "review-bundle.md").read_bytes(),
        instruction_bytes=(review / "review-instructions.md").read_bytes(),
        generator_identity="phase_loop_runtime.panel_invoker._resolve_brief.v1",
    )


def _usable_private_board(summary: dict[str, object]) -> dict[str, object]:
    legs = [
        {"seat_key": summary["gemini_seat_key"], "leg": "gemini", "status": "OK", "detail": None, "text": "AGREE", "needs_native_agent": None},
        {"seat_key": "codex", "leg": "codex", "status": "OK", "detail": None, "text": "AGREE", "needs_native_agent": None},
        {"seat_key": "claude", "leg": "claude", "status": "OK", "detail": None, "text": "AGREE", "needs_native_agent": None},
        {"seat_key": "grok", "leg": "grok", "status": "OK", "detail": None, "text": "AGREE", "needs_native_agent": None},
    ]
    return {
        "board": "synthetic", "usable": True, "requested_seats": 4,
        "delivered_seats": 4,
        "shortfall": {"requested_seats": 4, "delivered_seats": 4, "unfilled_seats": [], "natively_fillable_seats": 0},
        "independence": {"level": "synthetic", "distinct_vendors": 4, "seats": 4},
        "legs": legs, "agy_canary_capture": summary,
    }


def _seal_synthetic_provider_results(
    capture: evidence.AgyCanaryCapture, payload: dict[str, object]
) -> None:
    """Build exact provider records for reducers that do not launch a CLI."""
    launch_authority = evidence._read_json_at(capture.root_fd, "agy_canary_launch_authority.json")
    stage_binding = evidence._read_json_at(capture.root_fd, "agy_canary_stage_binding.json")
    launch_digest = evidence._sha256(evidence._canonical_json(launch_authority))
    stage_digest = evidence._sha256(evidence._canonical_json(stage_binding))
    entries = []
    for leg in payload["legs"]:
        assert isinstance(leg, dict)
        provider = str(leg["leg"])
        seat_key = str(leg["seat_key"])
        names = evidence._provider_names(provider, seat_key)
        destinations = (
            [item["destination"] for item in launch_authority["auth_binds"]]
            if provider == "gemini" else [evidence._PROVIDER_AUTH_PATHS[provider][1]]
        )
        launch = {
            "schema": "agy_provider_launch.v1",
            "provider": provider,
            "seat_key": seat_key,
            "launch_authority_sha256": launch_digest,
            "stage_binding_sha256": stage_digest,
            "projected_auth": {
                "schema": "agy_provider_projected_auth.v1",
                "provider": provider,
                "runtime_destination": f"/run/phase-loop-bin/{evidence._PROVIDER_EXECUTABLES[provider]}",
                "runtime_sha256": "b" * 64,
                "records": ([
                    {"destination": item["destination"], "uid": item["uid"], "mode": item["mode"], "sha256": item["source_sha256"]}
                    for item in launch_authority["auth_binds"]
                ] if provider == "gemini" else [{"destination": destination, "uid": str(os.getuid()), "mode": "0600", "sha256": "c" * 64} for destination in destinations]),
            },
        }
        launch_bytes = evidence._canonical_json(launch)
        evidence._exclusive_write_at(capture.root_fd, names["authority"], launch_bytes, 0o600)
        terminal = str(leg["text"]).encode()
        evidence._exclusive_write_at(capture.root_fd, names["terminal"], terminal, 0o600)
        attempts = {
            "launch": {"argv_bytes": 1, "argv_sha256": "a" * 64},
            "attempts": [{"index": 0, "argv_bytes": 1, "argv_sha256": "a" * 64}],
            "terminal_attempt": 0,
        }
        result = {
            "schema": "agy_provider_result.v1",
            "provider": provider,
            "seat_key": seat_key,
            "registry_sha256": "pending",
            "authority_sha256": evidence._sha256(launch_bytes),
            "attempts": attempts,
            "status": leg["status"],
            "terminal": {
                "name": names["terminal"], "bytes": len(terminal),
                "sha256": evidence._sha256(terminal),
            },
            "detail": None,
        }
        entries.append((leg, names, result, launch_bytes))
    registry = {
        "schema": "agy_provider_launch_registry.v1",
        "launch_authority_sha256": launch_digest,
        "stage_binding_sha256": stage_digest,
        "entries": [
            {
                "provider": str(leg["leg"]), "seat_key": str(leg["seat_key"]),
                "authority": {
                    "name": names["authority"], "bytes": len(launch_bytes),
                    "sha256": evidence._sha256(launch_bytes),
                },
                "result_name": names["result"],
            }
            for leg, names, _result, launch_bytes in entries
        ],
    }
    registry_digest = evidence._sha256(evidence._canonical_json(registry))
    for _leg, names, result, _launch_bytes in entries:
        result["registry_sha256"] = registry_digest
        evidence._exclusive_write_at(
            capture.root_fd, names["result"], evidence._canonical_json(result), 0o600
        )
    evidence._exclusive_write_at(
        capture.root_fd, evidence._PROVIDER_REGISTRY_NAME,
        evidence._canonical_json(registry), 0o600,
    )


def _review_stream(*, instructions: str, bundle: str, terminal: str, terminal_only: bool = False, prohibited: bool = False, omit_bundle: bool = False) -> str:
    if terminal_only:
        return json.dumps({"sequence": 0, "session_id": "retry", "type": "terminal", "text": terminal})
    events = [
        {"sequence": 0, "session_id": "retry", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        {"sequence": 1, "session_id": "retry", "type": "tool_result", "call_id": "a", "outcome": "success", "content": instructions},
    ]
    if prohibited:
        events.extend([
            {"sequence": 2, "session_id": "retry", "type": "tool_call", "call_id": "bad", "tool": "command", "target": "true"},
            {"sequence": 3, "session_id": "retry", "type": "tool_result", "call_id": "bad", "outcome": "denied"},
        ])
    elif not omit_bundle:
        events.extend([
            {"sequence": 2, "session_id": "retry", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
            {"sequence": 3, "session_id": "retry", "type": "tool_result", "call_id": "b", "outcome": "success", "content": bundle},
        ])
    events.append({"sequence": len(events), "session_id": "retry", "type": "terminal", "text": terminal})
    return "\n".join(json.dumps(event) for event in events)


def _sealed_retry_capture(monkeypatch, tmp_path: Path, *, first_stream: str, second_stream: str, provider_text: str) -> tuple[Path, evidence.AgyCanaryCapture]:
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, [])
    review = tmp_path / "review"
    review.mkdir()
    instructions = review / "review-instructions.md"
    bundle = review / "review-bundle.md"
    instructions.write_text("read this first\n")
    bundle.write_text("review this\n")
    instructions.chmod(0o600)
    bundle.chmod(0o600)
    capture = _prepare_production_capture(
        monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
        seat_key="gemini-primary", plan_bytes=bundle.read_bytes(),
    )
    _bind_stage(capture, review)
    staged = evidence.retain_staged_files(capture=capture, review_dir=review)
    evidence.record_launch(
        capture=capture, seat_key="gemini-primary", attempt_id="gemini-1",
        argv=["agy", "-p", "secret"], returncode=9, stdout=first_stream, stderr="retry", staged=staged,
    )
    evidence.record_launch(
        capture=capture, seat_key="gemini-primary", attempt_id="gemini-2",
        argv=["agy", "-p", "secret"], returncode=0, stdout=second_stream, stderr="", staged=staged,
    )
    board = _usable_private_board({"gemini_seat_key": "gemini-primary"})
    board["legs"][0]["text"] = provider_text
    _seal_synthetic_provider_results(capture, board)
    evidence.write_private_board(
        capture=capture, basename="board.json",
        payload={**board, "agy_canary_capture": evidence.capture_summary(capture)},
    )
    return root, capture


def test_capture_reducer_accepts_ordered_retry_and_binds_final_provider_text(monkeypatch, tmp_path):
    first = _review_stream(instructions="", bundle="", terminal="retry exhausted", terminal_only=True)
    second = _review_stream(instructions="read this first\n", bundle="review this\n", terminal="AGREE attempt two")
    root, capture = _sealed_retry_capture(
        monkeypatch, tmp_path, first_stream=first, second_stream=second, provider_text="AGREE attempt two",
    )
    try:
        capture.close()
        proof = evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
        assert proof["attempt_ids"] == ["gemini-1", "gemini-2"]
        assert proof["accepted_review_sha256"] == evidence._sha256(b"AGREE attempt two")
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("attempt_ids", [["gemini-2", "gemini-1"], ["gemini-2"]])
def test_capture_reducer_rejects_reordered_or_skipped_authorized_attempts(monkeypatch, tmp_path, attempt_ids):
    stream = _review_stream(instructions="read this first\n", bundle="review this\n", terminal="AGREE")
    root, capture = _sealed_retry_capture(
        monkeypatch, tmp_path, first_stream=_review_stream(instructions="", bundle="", terminal="retry", terminal_only=True),
        second_stream=stream, provider_text="AGREE",
    )
    try:
        ledger = evidence._read_json_at(capture.root_fd, "agy-launch-ledger.json")
        if len(attempt_ids) == 1:
            ledger["attempts"] = [ledger["attempts"][1]]
        else:
            ledger["attempts"] = list(reversed(ledger["attempts"]))
        evidence._write_replace_at(capture.root_fd, "agy-launch-ledger.json", ledger)
        capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="authorized prefix"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    ("first_stream", "second_stream", "provider_text", "message"),
    [
        (_review_stream(instructions="read this first\n", bundle="", terminal="retry", prohibited=True), _review_stream(instructions="read this first\n", bundle="review this\n", terminal="AGREE"), "AGREE", "prohibited tool attempt"),
        (_review_stream(instructions="", bundle="", terminal="retry", terminal_only=True), _review_stream(instructions="read this first\n", bundle="", terminal="AGREE", omit_bundle=True), "AGREE", "did not read review-bundle.md"),
        (_review_stream(instructions="", bundle="", terminal="retry", terminal_only=True), _review_stream(instructions="read this first\n", bundle="review this\n", terminal="AGREE"), "different provider text", "does not match accepted terminal"),
    ],
)
def test_capture_reducer_rejects_retry_or_final_evidence_mismatch(monkeypatch, tmp_path, first_stream, second_stream, provider_text, message):
    root, capture = _sealed_retry_capture(
        monkeypatch, tmp_path, first_stream=first_stream, second_stream=second_stream, provider_text=provider_text,
    )
    try:
        capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match=message):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


def test_duplicate_cross_provider_seat_keys_are_rejected_at_every_evidence_boundary(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    capture = _prepare_production_capture(
        monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=_settings(tmp_path, []), seat_key="gemini-primary",
    )
    try:
        review = tmp_path / "review"
        review.mkdir()
        for name, content in (("review-instructions.md", "instructions"), ("review-bundle.md", "review this\n")):
            path = review / name
            path.write_text(content)
            path.chmod(0o600)
        _bind_stage(capture, review)
        board = _usable_private_board({"gemini_seat_key": "gemini-primary"})
        _seal_synthetic_provider_results(capture, board)
        summary = evidence.capture_summary(capture)
        board["agy_canary_capture"] = summary
        provider_results = evidence._verified_provider_results(root_fd=capture.root_fd)
        registry = evidence._provider_registry(root_fd=capture.root_fd)
        codex = next(entry for entry in registry["entries"] if entry["provider"] == "codex")
        codex["seat_key"] = "gemini-primary"
        codex["result_name"] = evidence._provider_names("codex", "gemini-primary")["result"]
        evidence._write_replace_at(capture.root_fd, evidence._PROVIDER_REGISTRY_NAME, registry)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="seat key is duplicated"):
            evidence._provider_registry(root_fd=capture.root_fd)

        duplicate_summary = json.loads(json.dumps(summary["provider_results"]))
        duplicate_summary["providers"][1]["seat_key"] = "gemini-primary"
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="provider results are duplicated"):
            evidence._validate_provider_result_summary(duplicate_summary)

        board["legs"][1]["seat_key"] = "gemini-primary"
        provider_results[("codex", "gemini-primary")] = provider_results.pop(("codex", "codex"))
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="provider result set is incomplete or substituted"):
            evidence._validate_private_board_payload(
                board, summary, require_usable=True, provider_results=provider_results,
            )
    finally:
        capture.close()
        shutil.rmtree(root)


def _mock_canonical_bwrap(monkeypatch) -> None:
    monkeypatch.setattr(evidence, "_canonical_bwrap", lambda: Path("/usr/bin/bwrap"))


def _mock_trusted_agy_runtime(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "trusted-agy"
    source.write_bytes(b"trusted-agy")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(
        source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)


def test_capture_namespace_reopens_auth_and_resolver_for_child_paths(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    _mock_trusted_agy_runtime(monkeypatch, tmp_path)
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, [])
    auth = tmp_path / "auth.json"
    auth.write_text('{"credential":"private"}')
    auth.chmod(0o600)
    capture = _prepare_production_capture(
        monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
        seat_key="gemini-primary", auth_paths=(auth,),
    )
    try:
        ledger = evidence._read_json_at(capture.root_fd, "agy-launch-ledger.json")
        destination = ledger["auth_binds"][0]["destination"]
        resolver = tmp_path / "resolv.conf"
        resolver.write_text("nameserver 127.0.0.1\n")
        monkeypatch.setattr(evidence, "_resolver_snapshot", lambda: (resolver, evidence._sha256(resolver.read_bytes())))
        path_resolve = evidence.Path.resolve
        resolver_target_path = Path("/run") / f"phase-loop-resolver-{os.getpid()}-{tmp_path.name}" / "resolv.conf"

        def resolver_target(path: Path, *, strict: bool = False) -> Path:
            if path == Path("/etc/resolv.conf"):
                return resolver_target_path
            return path_resolve(path, strict=strict)

        monkeypatch.setattr(evidence.Path, "resolve", resolver_target)
        stage = tmp_path / "launch-stage"
        stage.mkdir()
        namespace = evidence.capture_namespace(capture=capture, stage=stage)
        command = namespace.command(["agy", "--version"])
        assert destination in command
        assert str(auth) in command
        assert str(resolver) in command
        assert str(resolver_target_path) in command
        malformed_resolver = tmp_path / "malformed-resolv.conf"
        malformed_resolver.write_text("nameserver 127.0.0.1\n")

        def malformed_resolver_target(path: Path, *, strict: bool = False) -> Path:
            if path == Path("/etc/resolv.conf"):
                return malformed_resolver
            return path_resolve(path, strict=strict)

        monkeypatch.setattr(evidence.Path, "resolve", malformed_resolver_target)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="expected /run target"):
            namespace.command(["agy", "--version"])
    finally:
        capture.close()
        shutil.rmtree(root)


def test_prepare_and_capture_namespace_reject_replaced_probed_agy(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    source = tmp_path / "agy"
    source.write_bytes(b"probed-agy")
    source.chmod(0o700)
    info = source.stat()
    runtime_record = {
        "path": str(source), "device": info.st_dev, "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode), "sha256": evidence._sha256(source.read_bytes()),
        "version": "1.1.13",
    }
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, [])
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="trusted agy executable drifted"):
            _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", agy_runtime=runtime_record,
                before_prepare=lambda: source.write_bytes(b"replacement"),
            )
    finally:
        shutil.rmtree(root)

    source.write_bytes(b"probed-agy")
    source.chmod(0o700)
    info = source.stat()
    runtime_record.update({
        "device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
        "sha256": evidence._sha256(source.read_bytes()),
    })
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, [])
    capture = _prepare_production_capture(
        monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
        seat_key="gemini-primary", agy_runtime=runtime_record,
    )
    try:
        source.write_bytes(b"replacement")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="trusted agy executable drifted"):
            evidence.capture_namespace(capture=capture, stage=tmp_path)
    finally:
        capture.close()
        shutil.rmtree(root)


def test_bwrap_auth_bind_is_visible_only_at_child_lookup_path(tmp_path):
    try:
        evidence._canonical_bwrap()
    except evidence.AgyCanaryEvidenceError:
        pytest.skip("canonical bwrap is unavailable")
    root = _private_root(tmp_path)
    try:
        stage = tmp_path / "stage"
        stage.mkdir()
        home = tmp_path / "home"
        (home / ".gemini" / "antigravity-cli" / "auth").mkdir(parents=True)
        home.chmod(0o700)
        placeholder = home / ".gemini" / "antigravity-cli" / "auth" / "auth.json"
        placeholder.write_bytes(b"")
        placeholder.chmod(0o600)
        auth = tmp_path / "auth.json"
        auth.write_text("dummy-private-auth")
        auth.chmod(0o600)
        destination = "/home/phase-loop/.gemini/antigravity-cli/auth/auth.json"
        namespace = evidence.AgyCanaryNamespace(
            stage=stage, minimal_home=home, evidence_root=root,
            provider_hostname="example.invalid", auth_binds=((auth, destination),),
        )
        proc = evidence.subprocess.run(
            namespace.command(["/bin/sh", "-c", f"test \"$(cat {destination})\" = dummy-private-auth"]),
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr
    finally:
        shutil.rmtree(root)


def test_canonical_bwrap_fails_closed_when_not_executable(monkeypatch):
    monkeypatch.setattr(evidence.os, "access", lambda *_args: False)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="canonical /usr/bin/bwrap"):
        evidence._canonical_bwrap()


def test_capture_reducer_rejects_unpaired_tool_evidence(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = None
        try:
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            capture = _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", plan_bytes=(review / "review-bundle.md").read_bytes(),
            )
            _bind_stage(capture, review)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            broken = {"sequence": 0, "session_id": "s1", "type": "tool_call", "call_id": "bad", "tool": "command", "target": "true"}
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret prompt"], returncode=0, stdout=json.dumps(broken), stderr="", staged=staged)
        finally:
            if capture is not None:
                capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="complete"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


def test_capture_reducer_rejects_denied_command_and_alias_stage_read(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = None
        try:
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            capture = _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", plan_bytes=(review / "review-bundle.md").read_bytes(),
            )
            _bind_stage(capture, review)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/not-stage/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "review-instructions.md"},
                {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "command", "target": "true"},
                {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "denied"},
                {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
        finally:
            if capture is not None:
                capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="prohibited tool attempt"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


def test_capture_reducer_derives_staged_proof_from_content_not_reported_digest(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = None
        try:
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            capture = _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", plan_bytes=(review / "review-bundle.md").read_bytes(),
            )
            _bind_stage(capture, review)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "forged", "sha256": staged["review-instructions.md"]["sha256"], "bytes": staged["review-instructions.md"]["bytes"]},
                {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "review-bundle.md"},
                {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
        finally:
            if capture is not None:
                capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="schema"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


def test_namespace_masks_evidence_root_and_uses_fixed_stage(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    root = _private_root(tmp_path)
    try:
        stage = tmp_path / "stage"
        stage.mkdir()
        for name in ("review-instructions.md", "review-bundle.md"):
            (stage / name).write_text(name)
        home = tmp_path / "home"
        home.mkdir()
        namespace = evidence.AgyCanaryNamespace(stage, home, root, "example.invalid")
        command = namespace.command(["agy", "--version"])
        assert "--tmpfs" in command
        assert "/run/phase-loop-review" in command
        assert str(root) not in command
    finally:
        root.rmdir()


def test_namespace_uses_private_fixed_provider_output_mapping_and_pid_namespace(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    root = _private_root(tmp_path)
    output = Path("/tmp") / f"phase-loop-provider-output.test-{os.getpid()}-{tmp_path.name}"
    output.mkdir(mode=0o700)
    try:
        namespace = evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid", provider_output=output)
        command = namespace.command(["agent", "--result", namespace.rewrite_provider_output_path(output / "result.json")])
        assert "--unshare-pid" in command
        assert command.index("--unshare-pid") < command.index("--clearenv")
        output_dir = command.index("/run/phase-loop-output")
        assert command[output_dir - 1] == "--dir"
        assert command[output_dir + 1:output_dir + 4] == ["--bind", str(output), "/run/phase-loop-output"]
        assert str(root) not in command
        assert command[-1] == "/run/phase-loop-output/result.json"
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="escapes"):
            namespace.rewrite_provider_output_path(tmp_path / "outside.json")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="distinct"):
            evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid", provider_output=root).command(["agent"])
    finally:
        shutil.rmtree(output)
        root.rmdir()


def test_minimal_home_keeps_auth_bytes_outside_evidence_and_binds_read_only(tmp_path):
    root = _private_root(tmp_path)
    home = None
    try:
        auth = tmp_path / "auth.json"
        auth.write_text('{"token":"private"}')
        auth.chmod(0o600)
        home, binds = evidence.build_minimal_home(
            evidence_root=root, settings_path=_settings(tmp_path, []), auth_paths=(auth,)
        )
        assert root not in home.parents
        assert binds == ((auth, "/home/phase-loop/.gemini/antigravity-cli/auth/auth.json"),)
        assert (home / ".gemini" / "antigravity-cli" / "settings.json").is_file()
        assert (home / ".gemini" / "antigravity-cli" / "auth" / "auth.json").read_bytes() == b""
    finally:
        if home is not None:
            shutil.rmtree(home)
        root.rmdir()


def _capability_stream(class_name: str, mutation: str | None = None) -> str:
    capability = next(item for item in evidence._CAPABILITY_CLASSES if item[0] == class_name)
    _name, tool, target, outcome = capability
    calls = [("read-a", tool, "/run/phase-loop-review/review-instructions.md", "review-instructions.md")]
    if class_name == "allowed_read":
        calls.append(("read-b", tool, "/run/phase-loop-review/review-bundle.md", "review-bundle.md"))
    else:
        calls[0] = ("call", tool, target, "READY")
    events = []
    for call_id, call_tool, call_target, content in calls:
        events.extend([
            {"sequence": len(events), "session_id": class_name, "type": "tool_call", "call_id": call_id, "tool": call_tool, "target": call_target, "attempt": True},
            {"sequence": len(events) + 1, "session_id": class_name, "type": "tool_result", "call_id": call_id, "outcome": outcome, "content": content, "execution": True},
        ])
    if mutation == "omit":
        events = []
    elif mutation == "alias":
        events[2 if class_name == "allowed_read" else 0]["target"] = "/run/phase-loop-review/review-instructions.md"
    elif mutation == "unpair":
        events[1]["call_id"] = "other"
    elif mutation == "wrong_target":
        events[0]["target"] = "/wrong-target"
    elif mutation == "wrong_outcome":
        events[1] = {"sequence": 1, "session_id": class_name, "type": "tool_result", "call_id": events[0]["call_id"], "outcome": "denied", "execution": True}
    events.append({"sequence": len(events), "session_id": class_name, "type": "terminal", "text": "READY"})
    return "\n".join(json.dumps(item) for item in events)


def _probe_namespace(tmp_path: Path, root: Path) -> evidence.AgyCanaryNamespace:
    stage = tmp_path / "stage"
    stage.mkdir()
    for name in ("review-instructions.md", "review-bundle.md"):
        path = stage / name
        path.write_text(name)
        path.chmod(0o600)
    home = tmp_path / "home"
    home.mkdir()
    return evidence.AgyCanaryNamespace(stage, home, root, "example.invalid")


def _install_capability_process(monkeypatch, mutation: tuple[str, str] | None = None):
    calls = []
    source = Path("/bin/true").resolve(strict=True)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(
        source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)

    class Proc:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("env")))
        if command[-1:] == ["--version"]:
            return Proc("1.1.13\n")
        if command[-1:] == ["--help"]:
            return Proc("--output-format text, json, stream-json")
        prompt = command[-1] if command else ""
        class_name = next((name for name, *_rest in evidence._CAPABILITY_CLASSES if prompt == evidence._capability_prompt(name)), None)
        return Proc(_capability_stream(class_name, mutation[1] if mutation and mutation[0] == class_name else None) if class_name else "")

    monkeypatch.setattr(evidence.subprocess, "run", fake_run)
    return calls


def test_probe_selects_1_1_13_stream_json_only_after_complete_capability_matrix(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    root = _private_root(tmp_path)
    try:
        calls = _install_capability_process(monkeypatch)
        result = evidence.probe_capability(evidence_root=root, namespace=_probe_namespace(tmp_path, root))
        assert result["complete"] is True
        assert result["mode"] == "stream_json"
        assert result["schema"] == "agy_capability_probe.v2"
        assert result["agy_runtime"]["path"] == "/usr/bin/true"
        assert result["agy_runtime"]["version"] == result["agy_version"]
        assert [row["class"] for row in result["classes"]] == [item[0] for item in evidence._CAPABILITY_CLASSES]
        assert all(row["attempt"] and row["execution"] and row["result"] == "text" for row in result["classes"])
        assert any("--output-format" in command for command, _env in calls)
        assert all(env is not None and not any(name.startswith(("LD_", "DYLD_", "PYTHON")) for name in env) for _command, env in calls)
    finally:
        shutil.rmtree(root)


def test_probe_rejects_each_missing_aliased_unpaired_or_wrong_capability_class(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    for class_name, *_rest in evidence._CAPABILITY_CLASSES:
        for mutation in ("omit", "alias", "unpair", "wrong_target", "wrong_outcome"):
            root = _private_root(tmp_path)
            try:
                _install_capability_process(monkeypatch, (class_name, mutation))
                result = evidence.probe_capability(evidence_root=root, namespace=_probe_namespace(tmp_path, root))
                assert result["complete"] is False
                assert result["mode"] is None
                assert result["reason"].startswith(f"stream_json_capability_unproven:{class_name}:")
            finally:
                shutil.rmtree(root)
                shutil.rmtree(tmp_path / "stage")
                shutil.rmtree(tmp_path / "home")


def test_prepare_requires_bootstrap_and_binds_selected_mode(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        _use_empty_process_inventory(monkeypatch, tmp_path)
        settings = _settings(tmp_path, [])
        evidence.clean_settings(
            evidence_root=root,
            settings_path=settings,
            maintenance_lock=tmp_path / "maintenance.lock",
        )
        rows = []
        staged = {}
        for name in ("review-instructions.md", "review-bundle.md"):
            retained = f"agy-capability-stage-{name}"
            raw_stage = name.encode()
            (root / retained).write_bytes(raw_stage)
            staged[name] = {"name": retained, "bytes": len(raw_stage), "sha256": evidence._sha256(raw_stage)}
        for class_name, tool, target, outcome in evidence._CAPABILITY_CLASSES:
            name = f"agy-capability-{class_name}.jsonl"
            raw = _capability_stream(class_name).encode()
            (root / name).write_bytes(raw)
            rows.append({
                "class": class_name, "tool": tool, "target": target,
                "attempt": True, "execution": True, "result": "text", "outcome": outcome,
                "stream": {"name": name, "bytes": len(raw), "sha256": evidence._sha256(raw)},
            })
        (root / "agy_capability_probe.json").write_text(json.dumps({
            "schema": "agy_capability_probe.v2", "agy_version": "1.1.13",
            "agy_runtime": _probe_runtime_record(),
            "help_sha256": "a" * 64, "mode": "stream_json", "complete": True, "classes": rows,
            "staged": staged,
        }))
        installation = _installation_identity()
        monkeypatch.setattr(evidence, "_installed_phase_loop_identity", lambda **_kwargs: installation)
        (root / "agy_canary_bootstrap_attestation.json").write_text(json.dumps(
            _bootstrap_receipt(
                installation=installation,
                dotfiles_repo=tmp_path / "bootstrap-receipt-dotfiles",
            )
        ))
        release = _release_identity()
        monkeypatch.setattr(evidence, "_reconcile_release_lineage", lambda **_kwargs: release)
        monkeypatch.setattr(evidence, "_validate_installed_wheel_binding", lambda **_kwargs: None)
        harness = tmp_path / "agent-harness"
        harness.mkdir()
        prepared = evidence.prepare_canary(
            evidence_root=root, settings_path=settings, seat_key="gemini-primary",
            agent_harness_repo=harness, handoff_commit="d" * 40,
            customization_home=tmp_path, project_dir=tmp_path, source_env={},
        )
        assert prepared["seat_key"] == "gemini-primary"
        ledger = json.loads((root / "agy-launch-ledger.json").read_text())
        assert ledger["capture_mode"] == "stream_json"
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("minimal", "schema is malformed"),
        ("extra_nonce", "schema is malformed"),
        ("script", "child identity is malformed"),
    ],
)
def test_prepare_rejects_hand_authored_or_semantically_mutated_bootstrap_receipt(
    tmp_path, monkeypatch, mutation, match,
):
    root = _private_root(tmp_path)
    settings = _settings(tmp_path, [])

    def mutate_receipt():
        path = root / "agy_canary_bootstrap_attestation.json"
        receipt = json.loads(path.read_text())
        if mutation == "minimal":
            receipt = {"bootstrap": {"returncode": 0}}
        elif mutation == "extra_nonce":
            receipt["nonce_sha256"] = "0" * 64
        else:
            receipt["bootstrap"]["script_sha256"] = "0" * 64
        path.write_text(json.dumps(receipt))

    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match=match):
            _prepare_production_capture(
                monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
                seat_key="gemini-primary", before_prepare=mutate_receipt,
            )
        assert not (root / "agy-launch-ledger.json").exists()
    finally:
        shutil.rmtree(root)


def test_bootstrap_attest_rejects_caller_selected_child_command(tmp_path):
    root = _private_root(tmp_path)
    try:
        with pytest.raises(TypeError):
            evidence.bootstrap_attest(
                evidence_root=root,
                dotfiles_repo=tmp_path,
                bootstrap_command=("sh", "-c", "false"),  # type: ignore[call-arg]
            )
    finally:
        root.rmdir()


@pytest.mark.parametrize("location", ["home", "workspace"])
def test_bootstrap_attest_rejects_child_visible_evidence_root_before_launch(
    monkeypatch, tmp_path, location,
):
    if location == "home":
        parent = evidence._account_home()
    else:
        parent = Path("/mnt/workspace") if Path("/mnt/workspace").is_dir() else tmp_path
    root = parent / f"phase-loop-invalid-evidence-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(
        evidence.subprocess, "Popen",
        lambda *_args, **_kwargs: pytest.fail("bootstrap child launched before root rejection"),
    )
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="direct absolute child of /tmp"):
            evidence.bootstrap_attest(
                evidence_root=root, dotfiles_repo=tmp_path / "missing-repo",
                plan_path=Path("plans/canary.md"),
            )
        assert list(root.iterdir()) == []
    finally:
        root.rmdir()


@pytest.mark.parametrize("overlap", ["repo", "home", "workspace", "uv_tool"])
def test_bootstrap_evidence_root_isolation_rejects_every_child_visible_overlap(
    tmp_path, overlap,
):
    account_home = evidence._account_home()
    store = _installation_identity()["uv_store_authority"]
    if overlap == "workspace" and store["workspace"] is None:
        pytest.skip("workspace storage policy is not active")
    evidence_root = _private_root(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    if overlap == "repo":
        repo = evidence_root / "repo"
        repo.mkdir()
        candidate = evidence_root
    elif overlap == "home":
        candidate = account_home
    elif overlap == "workspace":
        workspace = store["workspace"]
        assert workspace is not None
        candidate = Path(workspace["resolved"])
    else:
        candidate = Path(store["directories"]["tool"]["resolved"])
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="overlaps"):
            evidence._validate_bootstrap_evidence_root_isolation(
                root=candidate, repo=repo, account_home=account_home,
                uv_store_authority=store,
            )
    finally:
        shutil.rmtree(evidence_root)


def test_bootstrap_evidence_root_authority_rejects_path_replacement(tmp_path):
    root = _private_root(tmp_path)
    canonical, root_fd = evidence._validate_private_root(root)
    authority = evidence._evidence_root_masking_authority(canonical, root_fd)
    moved = Path("/tmp") / f"{root.name}.moved"
    root.rename(moved)
    root.mkdir(mode=0o700)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="root is not canonical"):
            evidence._evidence_root_masking_authority(root, root_fd)
        assert authority["inode"] != root.stat().st_ino
    finally:
        os.close(root_fd)
        root.rmdir()
        moved.rmdir()


def test_finalizer_only_appends_canonical_proof_and_updates_matching_manifest(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        repo = tmp_path / "dotfiles"
        plans = repo / "plans"
        plans.mkdir(parents=True)
        plan = plans / "canary.md"
        manifest = plans / "manifest.json"
        plan.write_text("# Base plan\n")
        manifest.write_text(json.dumps({"plans": [{"slug": "agy-canary", "updated_at": "base"}]}))
        (repo / "bootstrap.sh").write_text("#!/bin/sh\n")
        (repo / "shared").mkdir()
        pin = repo / "shared" / "agent-harness.pin"
        pin.write_text("v0.7.13\n")
        _git_repo(repo)
        base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        plan.write_text("# Plan\n")
        manifest.write_text(json.dumps({"plans": [{"slug": "agy-canary", "updated_at": "old"}]}))
        pin.write_text("v0.7.14\n")
        subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md", "plans/manifest.json", "shared/agent-harness.pin"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate"], check=True)
        plan.chmod(0o640)
        manifest.chmod(0o600)
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        blobs = {
            name: subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"HEAD:{name}"], text=True).strip()
            for name in ("bootstrap.sh", "shared/agent-harness.pin", "plans/canary.md", "plans/manifest.json")
        }
        installation = _installation_identity()
        (root / "agy_canary_bootstrap_attestation.json").write_text(json.dumps(
            _bootstrap_receipt(
                installation=installation, dotfiles_repo=repo,
                repo_head=head, blobs=blobs,
                input_sha256={
                    name: evidence._sha256((repo / name).read_bytes())
                    for name in (
                        "bootstrap.sh", "shared/agent-harness.pin", "plans/canary.md",
                        "plans/manifest.json",
                    )
                },
            )
        ))
        release = _release_identity()
        (root / "agy_canary_prepare.json").write_text(json.dumps({
            "release": release,
            "release_sha256": evidence._sha256(evidence._canonical_json(release)),
            "wheel_binding_sha256": evidence._sha256(
                evidence._canonical_json(release["wheel_binding"])
            ),
            "installation_sha256": evidence._sha256(
                evidence._canonical_json(installation)
            ),
            "seat_key": "gemini-primary",
        }))
        proof = {
            "schema": evidence.SCHEMA_VERSION,
            "seat_key": "gemini-primary",
            "attempt_ids": ["gemini-1"],
            "capture_mode": "stream_json",
            "attempts": [{
                "attempt_id": "gemini-1",
                "counts": {
                    "command": 0, "unsandboxed": 0,
                    "non_read_tool": 0, "out_of_stage_read": 0,
                },
                "terminal_sha256": "1" * 64,
            }],
            "accepted_review_sha256": "2" * 64,
            "private_board_sha256": "3" * 64,
            "release_sha256": evidence._sha256(evidence._canonical_json(release)),
            "wheel_binding_sha256": evidence._sha256(evidence._canonical_json(release["wheel_binding"])),
            "installation_sha256": evidence._sha256(evidence._canonical_json(installation)),
            "provider_results": {
                "registry_sha256": "4" * 64,
                "result_set_sha256": "5" * 64,
                "providers": [
                    {"provider": "gemini", "seat_key": "gemini-primary"},
                    {"provider": "codex", "seat_key": "codex-primary"},
                    {"provider": "claude", "seat_key": "claude-primary"},
                    {"provider": "grok", "seat_key": "grok-primary"},
                ],
            },
            **evidence._FINAL_GOVERNANCE_POSTURE,
        }
        missing_provider = json.loads(json.dumps(proof))
        missing_provider["provider_results"]["providers"].pop()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="provider results"):
            evidence._validate_final_proof(missing_provider)
        missing_governance = json.loads(json.dumps(proof))
        del missing_governance["human_required"]
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="governance"):
            evidence._validate_final_proof(missing_governance)
        altered_governance = json.loads(json.dumps(proof))
        altered_governance["external_attestation"] = "present"
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="governance"):
            evidence._validate_final_proof(altered_governance)
        (root / "agy_canary_proof.json").write_bytes(evidence._canonical_json(proof))
        monkeypatch.setattr(evidence, "verify_capture", lambda **_kwargs: altered_governance)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="governance"):
            evidence.finalize_canary(
                evidence_root=root,
                expected_seat_key="gemini-primary",
                dotfiles_repo=repo,
                plan_path=Path("plans/canary.md"),
                manifest_path=Path("plans/manifest.json"),
                plan_slug="agy-canary",
            )
        monkeypatch.setattr(evidence, "verify_capture", lambda **_kwargs: proof)
        result = evidence.finalize_canary(
            evidence_root=root,
            expected_seat_key="gemini-primary",
            dotfiles_repo=repo,
            plan_path=Path("plans/canary.md"),
            manifest_path=Path("plans/manifest.json"),
            plan_slug="agy-canary",
        )
        canonical_proof_sha256 = evidence._sha256(evidence._canonical_json(proof))
        assert result["inputs_sha256"]
        assert result["canonical_proof_sha256"] == canonical_proof_sha256
        assert {name: result[name] for name in evidence._FINAL_GOVERNANCE_POSTURE} == evidence._FINAL_GOVERNANCE_POSTURE
        assert "## Execution evidence" in plan.read_text()
        assert json.loads(manifest.read_text())["plans"][0]["updated_at"] != "old"
        assert stat.S_IMODE(plan.stat().st_mode) == 0o640
        assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
        assert not [path for path in plans.iterdir() if path.name.startswith(".phase-loop-agy-finalize-")]
        assert (root / "agy_canary_inputs.json").is_file()
        _prefix, payload = evidence._parse_final_payload(plan.read_bytes())
        assert payload["proof"]["provider_results"] == proof["provider_results"]
        assert payload["attestation"]["proof"]["provider_results"] == proof["provider_results"]
        assert set(payload["attestation"]["bootstrap"]) == {
            "repo_head", "tree_snapshot", "blobs", "input_sha256", "sandbox",
        }
        assert payload["proof_sha256"] == canonical_proof_sha256
        assert {name: payload["proof"][name] for name in evidence._FINAL_GOVERNANCE_POSTURE} == evidence._FINAL_GOVERNANCE_POSTURE
        private_governance = json.loads(json.dumps(proof))
        private_governance["blocker_class"] = "release_approval"
        monkeypatch.setattr(evidence, "verify_capture", lambda **_kwargs: private_governance)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="governance"):
            evidence.check_private_final(
                evidence_root=root, expected_seat_key="gemini-primary", dotfiles_repo=repo,
                plan_path=Path("plans/canary.md"), manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
            )
        monkeypatch.setattr(evidence, "verify_capture", lambda **_kwargs: proof)
        checked = evidence.check_private_final(
            evidence_root=root, expected_seat_key="gemini-primary", dotfiles_repo=repo,
            plan_path=Path("plans/canary.md"), manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
        )
        assert checked["inputs_sha256"] == result["inputs_sha256"]
        assert checked["canonical_proof_sha256"] == canonical_proof_sha256
        assert {name: checked[name] for name in evidence._FINAL_GOVERNANCE_POSTURE} == evidence._FINAL_GOVERNANCE_POSTURE
        final_plan = plan.read_bytes()
        final_manifest = manifest.read_bytes()
        subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md", "plans/manifest.json"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate finalize"], check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", base], check=True)
        plan.write_bytes(final_plan)
        manifest.write_bytes(final_manifest)
        pin.write_text("v0.7.14\n")
        subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md", "plans/manifest.json", "shared/agent-harness.pin"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "squash finalize"], check=True)
        committed = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        monkeypatch.setattr(evidence, "_reconcile_release_lineage", lambda **_kwargs: release)
        committed_result = evidence.check_committed_final(
            dotfiles_repo=repo, commit=committed, plan_path=Path("plans/canary.md"),
            manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
            agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
        )
        assert committed_result["commit"] == committed
        assert committed_result["canonical_proof_sha256"] == canonical_proof_sha256
        assert {name: committed_result[name] for name in evidence._FINAL_GOVERNANCE_POSTURE} == evidence._FINAL_GOVERNANCE_POSTURE
        assert "shared/agent-harness.pin" in subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--name-only", f"{committed}^", committed], text=True,
        ).splitlines()
        detached_repo = tmp_path / "detached-dotfiles"
        subprocess.run(
            ["git", "clone", "-q", "--no-local", str(repo), str(detached_repo)],
            check=True,
        )
        detached_result = evidence.check_committed_final(
            dotfiles_repo=detached_repo, commit=committed,
            plan_path=Path("plans/canary.md"),
            manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
            agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
        )
        assert detached_result == committed_result
        bootstrap = json.loads((root / "agy_canary_bootstrap_attestation.json").read_text())
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="release"):
            evidence._validate_committed_attestation(
                repo=repo,
                attestation={
                    "bootstrap": {name: bootstrap[name] for name in ("repo_head", "blobs", "input_sha256")},
                    "release": {"version": "0.7.14", "release_commit": "b" * 40, "artifacts": []},
                    "release_sha256": evidence._sha256(evidence._canonical_json({"version": "0.7.14", "release_commit": "b" * 40, "artifacts": []})),
                    "proof": evidence._proof_identity(proof),
                    "reducer_proof_sha256": evidence._sha256(evidence._canonical_json(proof)),
                },
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        _prefix, payload = evidence._parse_final_payload(plan.read_bytes())
        tampered = json.loads(json.dumps(payload["attestation"]))
        tampered["bootstrap"]["input_sha256"]["bootstrap.sh"] = "0" * 64
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="bootstrap blob"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered, plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        omitted_snapshot = json.loads(json.dumps(payload["attestation"]))
        del omitted_snapshot["bootstrap"]["tree_snapshot"]
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="bootstrap identity"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=omitted_snapshot,
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        tampered_snapshot_commit = json.loads(json.dumps(payload["attestation"]))
        tampered_snapshot_commit["bootstrap"]["tree_snapshot"]["commit"] = "0" * 40
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="snapshot commit drifted"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered_snapshot_commit,
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        tampered_snapshot_tree = json.loads(json.dumps(payload["attestation"]))
        tampered_snapshot_tree["bootstrap"]["tree_snapshot"]["tree_oid"] = "0" * 40
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="snapshot authority drifted"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered_snapshot_tree,
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        tampered_snapshot = json.loads(json.dumps(payload["attestation"]))
        tampered_snapshot["bootstrap"]["tree_snapshot"]["inventory_sha256"] = "0" * 64
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="snapshot authority drifted"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered_snapshot,
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        tampered_mount = json.loads(json.dumps(payload["attestation"]))
        recorded_mount = Path(tampered_mount["bootstrap"]["tree_snapshot"]["mount_path"])
        decoy_mount = str(recorded_mount.with_name("x" * len(recorded_mount.name)))
        tampered_mount["bootstrap"]["tree_snapshot"]["mount_path"] = decoy_mount
        tampered_mount["bootstrap"]["sandbox"]["mount_path"] = decoy_mount
        tampered_mount["bootstrap"]["sandbox"]["command"][1] = str(
            Path(decoy_mount) / "bootstrap.sh"
        )
        tampered_mount["bootstrap"]["sandbox"]["tmpfs"][2] = decoy_mount
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="sandbox identity drifted"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered_mount,
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        tampered_sandbox = json.loads(json.dumps(payload["attestation"]))
        tampered_sandbox["bootstrap"]["sandbox"]["argv_sha256"] = "0" * 64
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="sandbox identity"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered_sandbox,
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        malformed_identity = json.loads(json.dumps(payload["attestation"]))
        malformed_identity["proof"]["human_required"] = False
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="proof governance"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=malformed_identity, plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", f"{head}:plans/manifest.json"]),
            )
        unexpected = repo / "unexpected.txt"
        unexpected.write_text("unexpected\n")
        subprocess.run(["git", "-C", str(repo), "add", "unexpected.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unrelated drift"], check=True)
        unrelated = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="unexpected paths"):
            evidence.check_committed_final(
                dotfiles_repo=repo, commit=unrelated, plan_path=Path("plans/canary.md"),
                manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
                agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
            )

        def commit_payload(payload_value: dict[str, object], message: str) -> str:
            plan.write_bytes(
                _prefix + b"\n## Execution evidence\n\n```json\n" +
                evidence._canonical_json(payload_value) + b"```\n"
            )
            subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=True)
            return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

        subprocess.run(["git", "-C", str(repo), "checkout", "-q", committed], check=True)
        release_tamper_payload = json.loads(json.dumps(payload))
        tampered_release = release_tamper_payload["attestation"]["release"]
        tampered_release["wheel_binding"]["record_sha256"] = "0" * 64
        tampered_release_sha256 = evidence._sha256(evidence._canonical_json(tampered_release))
        tampered_wheel_sha256 = evidence._sha256(
            evidence._canonical_json(tampered_release["wheel_binding"])
        )
        release_tamper_payload["proof"]["release_sha256"] = tampered_release_sha256
        release_tamper_payload["proof"]["wheel_binding_sha256"] = tampered_wheel_sha256
        release_tamper_payload["proof_sha256"] = evidence._sha256(
            evidence._canonical_json(release_tamper_payload["proof"])
        )
        release_tamper_payload["attestation"]["release_sha256"] = tampered_release_sha256
        release_tamper_payload["attestation"]["wheel_binding_sha256"] = tampered_wheel_sha256
        release_tamper_payload["attestation"]["proof"] = evidence._proof_identity(
            release_tamper_payload["proof"]
        )
        release_tamper_payload["attestation"]["reducer_proof_sha256"] = (
            release_tamper_payload["proof_sha256"]
        )
        release_tamper_commit = commit_payload(release_tamper_payload, "release binding tamper")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="reauthenticate immutable handoff"):
            evidence.check_committed_final(
                dotfiles_repo=repo, commit=release_tamper_commit,
                plan_path=Path("plans/canary.md"), manifest_path=Path("plans/manifest.json"),
                plan_slug="agy-canary", agent_harness_repo=repo,
                handoff_commit=release["handoff_commit"],
            )

        subprocess.run(["git", "-C", str(repo), "checkout", "-q", head], check=True)
        plan.write_text("# Candidate plan drift\n")
        subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate plan drift"], check=True)
        drifted_candidate = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", committed], check=True)
        candidate_drift_payload = json.loads(json.dumps(payload))
        candidate_drift_payload["attestation"]["bootstrap"]["repo_head"] = drifted_candidate
        candidate_drift_plan = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{drifted_candidate}:plans/canary.md"]
        )
        candidate_drift_payload["attestation"]["bootstrap"]["blobs"]["plans/canary.md"] = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", f"{drifted_candidate}:plans/canary.md"], text=True,
        ).strip()
        candidate_drift_payload["attestation"]["bootstrap"]["input_sha256"]["plans/canary.md"] = evidence._sha256(candidate_drift_plan)
        candidate_drift = commit_payload(candidate_drift_payload, "candidate payload drift")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="snapshot commit drifted"):
            evidence.check_committed_final(
                dotfiles_repo=repo, commit=candidate_drift, plan_path=Path("plans/canary.md"),
                manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
                agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
            )
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", committed], check=True)
        substituted_payload = json.loads(json.dumps(payload))
        substituted_payload["attestation"]["bootstrap"]["repo_head"] = base
        substituted = commit_payload(substituted_payload, "substituted candidate")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="snapshot commit drifted"):
            evidence.check_committed_final(
                dotfiles_repo=repo, commit=substituted, plan_path=Path("plans/canary.md"),
                manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
                agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
            )
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", committed], check=True)
        missing_candidate_payload = json.loads(json.dumps(payload))
        missing_candidate_payload["attestation"]["bootstrap"]["repo_head"] = "0" * 40
        missing_candidate = commit_payload(missing_candidate_payload, "missing candidate")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="git command failed: rev-parse"):
            evidence.check_committed_final(
                dotfiles_repo=repo, commit=missing_candidate, plan_path=Path("plans/canary.md"),
                manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
                agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
            )
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", committed], check=True)
        malformed_payload = json.loads(json.dumps(payload))
        malformed_payload["proof"]["external_attestation"] = "present"
        malformed_payload["proof_sha256"] = evidence._sha256(evidence._canonical_json(malformed_payload["proof"]))
        plan.write_bytes(
            _prefix + b"\n## Execution evidence\n\n```json\n" +
            evidence._canonical_json(malformed_payload) + b"```\n"
        )
        manifest.write_bytes(evidence._canonical_json({"plans": [{"slug": "agy-canary", "updated_at": "tampered"}]}))
        subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md", "plans/manifest.json"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "malformed governance"], check=True)
        malformed_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="governance"):
            evidence.check_committed_final(
                dotfiles_repo=repo, commit=malformed_commit, plan_path=Path("plans/canary.md"),
                manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
                agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
            )
    finally:
        shutil.rmtree(root)


def _stub_finalizer(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = _private_root(tmp_path)
    repo = tmp_path / "dotfiles"
    plans = repo / "plans"
    plans.mkdir(parents=True)
    plan = plans / "canary.md"
    manifest = plans / "manifest.json"
    plan.write_bytes(b"# Plan\n")
    manifest.write_bytes(b'{"plans":[{"slug":"agy-canary","updated_at":"old"}]}\n')
    plan.chmod(0o640)
    manifest.chmod(0o600)
    proof = {
        "schema": evidence.SCHEMA_VERSION,
        "seat_key": "gemini-primary",
        "attempt_ids": ["gemini-1"],
        "capture_mode": "stream_json",
        "attempts": [{
            "attempt_id": "gemini-1",
            "counts": {
                "command": 0, "unsandboxed": 0,
                "non_read_tool": 0, "out_of_stage_read": 0,
            },
            "terminal_sha256": "1" * 64,
        }],
        "accepted_review_sha256": "2" * 64,
        "private_board_sha256": "3" * 64,
        "provider_results": {
            "registry_sha256": "4" * 64,
            "result_set_sha256": "5" * 64,
            "providers": [
                {"provider": "gemini", "seat_key": "gemini-primary"},
                {"provider": "codex", "seat_key": "codex-primary"},
                {"provider": "claude", "seat_key": "claude-primary"},
                {"provider": "grok", "seat_key": "grok-primary"},
            ],
        },
        **evidence._FINAL_GOVERNANCE_POSTURE,
    }
    release = _release_identity()
    installation = _installation_identity()
    proof["release_sha256"] = evidence._sha256(evidence._canonical_json(release))
    proof["wheel_binding_sha256"] = evidence._sha256(
        evidence._canonical_json(release["wheel_binding"])
    )
    proof["installation_sha256"] = evidence._sha256(
        evidence._canonical_json(installation)
    )
    prepare = {
        "seat_key": "gemini-primary",
        "release": release,
        "release_sha256": evidence._sha256(evidence._canonical_json(release)),
        "wheel_binding_sha256": evidence._sha256(
            evidence._canonical_json(release["wheel_binding"])
        ),
        "installation_sha256": evidence._sha256(
            evidence._canonical_json(installation)
        ),
    }
    bootstrap_receipt = _bootstrap_receipt(
        installation=installation,
        dotfiles_repo=tmp_path / "bootstrap-receipt-dotfiles",
        evidence_root=root, plan_bytes=plan.read_bytes(),
    )
    bootstrap_receipt["input_sha256"]["plans/canary.md"] = evidence._sha256(
        plan.read_bytes()
    )
    bootstrap_receipt["input_sha256"]["plans/manifest.json"] = evidence._sha256(
        manifest.read_bytes()
    )

    monkeypatch.setattr(evidence, "verify_capture", lambda **_kwargs: proof)
    monkeypatch.setattr(
        evidence,
        "_attested_final_targets",
        lambda **_kwargs: (
            bootstrap_receipt,
            "plans/canary.md",
            "plans/manifest.json",
        ),
    )
    monkeypatch.setattr(
        evidence,
        "_read_json_at",
        lambda _fd, name: prepare if name == evidence._PREPARE_NAME else proof,
    )
    monkeypatch.setattr(evidence, "_final_suffix", lambda _proof, _attestation: b"\nproof\n")
    return root, repo, plan, manifest


def _run_stub_finalizer(root: Path, repo: Path) -> dict[str, object]:
    return evidence.finalize_canary(
        evidence_root=root,
        expected_seat_key="gemini-primary",
        dotfiles_repo=repo,
        plan_path=Path("plans/canary.md"),
        manifest_path=Path("plans/manifest.json"),
        plan_slug="agy-canary",
    )


def _set_stub_plan_preimage(plan: Path, value: bytes) -> None:
    plan.write_bytes(value)
    bootstrap, _plan_relative, _manifest_relative = evidence._attested_final_targets()
    bootstrap["input_sha256"]["plans/canary.md"] = evidence._sha256(value)


@pytest.mark.parametrize(
    "plan_before",
    (
        b"# Plan\n\nThe final step appends ## Execution evidence after acceptance.\n",
        b"# Plan\n\nExample marker:\n\n````text\n## Execution evidence\n````\n",
    ),
)
def test_finalizer_allows_execution_evidence_phrase_in_prose_or_example(
    monkeypatch, tmp_path, plan_before,
):
    root, repo, plan, _manifest = _stub_finalizer(monkeypatch, tmp_path)
    _set_stub_plan_preimage(plan, plan_before)
    try:
        _run_stub_finalizer(root, repo)
        assert plan.read_bytes() == plan_before + b"\nproof\n"
    finally:
        shutil.rmtree(root)


def test_finalizer_rejects_an_existing_canonical_execution_suffix(monkeypatch, tmp_path):
    root, repo, plan, _manifest = _stub_finalizer(monkeypatch, tmp_path)
    proof = evidence.verify_capture()
    payload = {
        "attestation": {},
        "proof": proof,
        "proof_sha256": evidence._sha256(evidence._canonical_json(proof)),
        "schema": "agy_canary_final.v1",
    }
    plan_before = (
        b"# Plan\n\n## Execution evidence\n\n```json\n"
        + evidence._canonical_json(payload)
        + b"```\n"
    )
    _set_stub_plan_preimage(plan, plan_before)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="already has execution evidence"):
            _run_stub_finalizer(root, repo)
        assert plan.read_bytes() == plan_before
    finally:
        shutil.rmtree(root)


def test_finalizer_preserves_concurrent_mutation_after_inputs_receipt(monkeypatch, tmp_path):
    root, repo, plan, manifest = _stub_finalizer(monkeypatch, tmp_path)
    manifest_before = manifest.read_bytes()
    original_write = evidence._write_replace_at

    def write_then_mutate(directory_fd, name, value):
        original_write(directory_fd, name, value)
        if name == evidence._INPUTS_NAME:
            plan.write_bytes(b"concurrent plan edit\n")

    monkeypatch.setattr(evidence, "_write_replace_at", write_then_mutate)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted before staging"):
            _run_stub_finalizer(root, repo)
        assert plan.read_bytes() == b"concurrent plan edit\n"
        assert manifest.read_bytes() == manifest_before
        assert (root / evidence._INPUTS_NAME).is_file()
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("mutated_target", ("plan", "manifest"))
def test_finalizer_revalidates_the_complete_pair_before_commit(monkeypatch, tmp_path, mutated_target):
    root, repo, plan, manifest = _stub_finalizer(monkeypatch, tmp_path)
    plan_before = plan.read_bytes()
    manifest_before = manifest.read_bytes()
    target_path = plan if mutated_target == "plan" else manifest
    concurrent_bytes = f"concurrent {mutated_target} edit\n".encode()
    original_verify = evidence._verify_final_target_exchange
    mutated = False

    def verify_then_mutate(target):
        nonlocal mutated
        original_verify(target)
        if not mutated and target.name == target_path.name:
            mutated = True
            target_path.write_bytes(concurrent_bytes)

    monkeypatch.setattr(evidence, "_verify_final_target_exchange", verify_then_mutate)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="exchanged target failed"):
            _run_stub_finalizer(root, repo)
        assert mutated
        assert plan.read_bytes() == plan_before
        assert manifest.read_bytes() == manifest_before
        assert (root / evidence._INPUTS_NAME).is_file()
        retained = [path for path in plan.parent.iterdir() if path.name.startswith(".phase-loop-agy-finalize-")]
        assert any(path.read_bytes() == concurrent_bytes for path in retained)
    finally:
        shutil.rmtree(root)


def test_finalizer_rolls_back_plan_when_manifest_exchange_fails(monkeypatch, tmp_path):
    root, repo, plan, manifest = _stub_finalizer(monkeypatch, tmp_path)
    plan_before = plan.read_bytes()
    manifest_before = manifest.read_bytes()
    original_exchange = evidence._rename_exchange

    def fail_manifest_exchange(directory_fd, left, right):
        if left == manifest.name:
            raise OSError("manifest exchange failed")
        original_exchange(directory_fd, left, right)

    monkeypatch.setattr(evidence, "_rename_exchange", fail_manifest_exchange)
    try:
        with pytest.raises(OSError, match="manifest exchange failed"):
            _run_stub_finalizer(root, repo)
        assert plan.read_bytes() == plan_before
        assert manifest.read_bytes() == manifest_before
        assert not [path for path in plan.parent.iterdir() if path.name.startswith(".phase-loop-agy-finalize-")]
    finally:
        shutil.rmtree(root)


def test_finalizer_retains_recovery_evidence_when_plan_rollback_fails(monkeypatch, tmp_path):
    root, repo, plan, manifest = _stub_finalizer(monkeypatch, tmp_path)
    original_exchange = evidence._rename_exchange
    plan_exchanges = 0

    def fail_second_exchange_and_plan_rollback(directory_fd, left, right):
        nonlocal plan_exchanges
        if left == manifest.name:
            raise OSError("manifest exchange failed")
        if left == plan.name:
            plan_exchanges += 1
            if plan_exchanges == 2:
                raise OSError("plan rollback failed")
        original_exchange(directory_fd, left, right)

    monkeypatch.setattr(evidence, "_rename_exchange", fail_second_exchange_and_plan_rollback)
    try:
        with pytest.raises(OSError, match="manifest exchange failed"):
            _run_stub_finalizer(root, repo)
        assert plan.read_bytes() == b"# Plan\n\nproof\n"
        assert manifest.read_bytes().endswith(b'"updated_at":"old"}]}\n')
        assert (root / evidence._INPUTS_NAME).is_file()
        assert [path for path in plan.parent.iterdir() if path.name.startswith(".phase-loop-agy-finalize-")]
    finally:
        shutil.rmtree(root)


def test_finalizer_reports_cleanup_residue_after_commit(monkeypatch, tmp_path):
    root, repo, plan, manifest = _stub_finalizer(monkeypatch, tmp_path)
    original_discard = evidence._discard_final_target_temporary

    def retain_plan_temporary(target):
        if target.name == plan.name:
            raise OSError("cleanup unavailable")
        original_discard(target)

    monkeypatch.setattr(evidence, "_discard_final_target_temporary", retain_plan_temporary)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="committed with recovery residue"):
            _run_stub_finalizer(root, repo)
        assert plan.read_bytes() == b"# Plan\n\nproof\n"
        assert b'"updated_at":"old"' not in manifest.read_bytes()
        assert (root / evidence._INPUTS_NAME).is_file()
        assert [path for path in plan.parent.iterdir() if path.name.startswith(".phase-loop-agy-finalize-")]
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    "basename",
    [
        *sorted(evidence._PRIVATE_BOARD_RESERVED_NAMES),
        "agy-provider-launch-gemini-seat.json",
        "agy-stream-gemini-1.jsonl",
        "agy-diagnostic-gemini-1.log",
        "agy-capability-command.jsonl",
        "staged-review-bundle.md",
        ".phase-loop-agy-finalize-plan.tmp",
    ],
)
def test_private_board_rejects_reserved_evidence_names_without_overwrite(tmp_path, basename):
    root = _private_root(tmp_path)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    capture = evidence.AgyCanaryCapture(root=root, root_fd=root_fd)
    (root / basename).write_bytes(b"sealed internal evidence")
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="reserved evidence"):
            evidence.write_private_board(capture=capture, basename=basename, payload={})
        assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    finally:
        capture.close()
        shutil.rmtree(root)


def test_projected_auth_proof_rejects_row_substitution(tmp_path):
    source = tmp_path / "provider"
    source.write_bytes(b"runtime")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedProviderRuntime(
        "codex", source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    records = ({
        "source": str(source), "destination": "/home/phase-loop/.codex/auth.json",
        "source_sha256": "a" * 64, "uid": str(os.getuid()), "mode": "0600",
    },)
    proof = {
        "schema": "agy_provider_projected_auth.v1", "provider": "codex",
        "runtime_destination": runtime.destination, "runtime_sha256": runtime.sha256,
        "records": [{"destination": records[0]["destination"], "uid": records[0]["uid"], "mode": "0600", "sha256": "a" * 64}],
    }
    for field, value in (("uid", "9999"), ("sha256", "b" * 64), ("destination", "/home/phase-loop/.grok/auth.json")):
        changed = json.loads(json.dumps(proof))
        changed["records"][0][field] = value
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="authentication record"):
            evidence._validate_projected_auth_proof(proof=changed, provider="codex", runtime=runtime, records=records)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="authentication proof"):
        evidence._validate_projected_auth_proof(proof={**proof, "records": []}, provider="codex", runtime=runtime, records=records)


def test_provider_authority_factory_reclaims_output_when_projection_fails(monkeypatch, tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    output = tmp_path / "provider-output"
    source = tmp_path / "agy"
    source.write_bytes(b"runtime")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedProviderRuntime("gemini", source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
    capture = type("Capture", (), {"root": tmp_path, "root_fd": -1})()
    authority = {
        "minimal_home": {"path": str(home), "identity": "ok"}, "auth_binds": [],
        "agy_runtime": {
            "path": str(source), "device": info.st_dev, "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode), "sha256": evidence._sha256(source.read_bytes()),
            "version": "1.1.13",
        },
    }
    monkeypatch.setattr(evidence, "_require_prepare_authority", lambda **_kwargs: ({}, {}, authority))
    monkeypatch.setattr(evidence, "_validate_stage_binding", lambda **_kwargs: None)
    monkeypatch.setattr(evidence, "_minimal_home_identity", lambda _home: "ok")
    monkeypatch.setattr(evidence, "_resolver_snapshot", lambda: (None, None))
    monkeypatch.setattr(evidence, "_trusted_provider_runtime", lambda _provider: runtime)
    monkeypatch.setattr(evidence.tempfile, "mkdtemp", lambda **_kwargs: str(output.mkdir() or output))
    monkeypatch.setattr(evidence, "_projected_auth_proof", lambda **_kwargs: (_ for _ in ()).throw(evidence.AgyCanaryEvidenceError("projection failed")))
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="projection failed"):
        evidence.prepare_provider_launch_authorities(capture=capture, stage=stage, providers=("gemini",))
    assert not output.exists()


def test_detached_provider_auth_reduction_binds_rows_and_owner_modes(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    review = tmp_path / "review"; review.mkdir()
    for name in ("review-bundle.md", "review-instructions.md"):
        (review / name).write_text(name); (review / name).chmod(0o600)
    auth1, auth2 = tmp_path / "auth1", tmp_path / "auth2"
    for auth in (auth1, auth2):
        auth.write_text("auth"); auth.chmod(0o600)
    capture = _prepare_production_capture(monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=_settings(tmp_path, []), seat_key="gemini-primary", auth_paths=(auth1, auth2), plan_bytes=(review / "review-bundle.md").read_bytes())
    try:
        _bind_stage(capture, review)
        _seal_synthetic_provider_results(capture, _usable_private_board({"gemini_seat_key": "gemini-primary"}))
        assert evidence._verified_provider_results(root_fd=capture.root_fd)
        registry = evidence._provider_registry(root_fd=capture.root_fd)
        def replace_launch(provider, mutate):
            entry = next(item for item in registry["entries"] if item["provider"] == provider)
            launch = evidence._read_json_at(capture.root_fd, entry["authority"]["name"])
            mutate(launch)
            data = evidence._canonical_json(launch)
            evidence._write_replace_at(capture.root_fd, entry["authority"]["name"], launch)
            entry["authority"].update({"bytes": len(data), "sha256": evidence._sha256(data)})
            registry_sha = evidence._sha256(evidence._canonical_json(registry))
            for current in registry["entries"]:
                result = evidence._read_json_at(capture.root_fd, current["result_name"])
                result["authority_sha256"] = current["authority"]["sha256"]
                result["registry_sha256"] = registry_sha
                evidence._write_replace_at(capture.root_fd, current["result_name"], result)
            evidence._write_replace_at(capture.root_fd, evidence._PROVIDER_REGISTRY_NAME, registry)
        replace_launch("codex", lambda launch: launch["projected_auth"]["records"][0].update({"mode": "0400"}))
        assert evidence._verified_provider_results(root_fd=capture.root_fd)
        replace_launch("codex", lambda launch: launch["projected_auth"]["records"][0].update({"mode": "0689"}))
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="authentication proof"):
            evidence._verified_provider_results(root_fd=capture.root_fd)
        replace_launch("codex", lambda launch: launch["projected_auth"]["records"][0].update({"mode": "0400"}))
        replace_launch("gemini", lambda launch: launch["projected_auth"]["records"][1].update({"sha256": "0" * 64}))
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="authentication proof"):
            evidence._verified_provider_results(root_fd=capture.root_fd)
    finally:
        capture.close(); shutil.rmtree(root)


def test_real_source_inventory_rejects_environment_override_and_generated_capture_never_claims_complete(tmp_path):
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="customization source"):
        evidence.freeze_customization_inventory(
            home=tmp_path, project_dir=tmp_path, env={"AGY_PLUGIN_PATH": "ignored"}
        )
    root = _private_root(tmp_path)
    try:
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            ledger = evidence.create_capture(capture=capture, settings_path=_settings(tmp_path, []), seat_key="gemini-primary")
            assert ledger["policy"]["sources_complete"] is False
        finally:
            capture.close()
    finally:
        shutil.rmtree(root)


def test_namespace_masks_all_xdg_sources_and_finalizer_requires_tracked_repo(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    root = _private_root(tmp_path)
    try:
        namespace = evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid")
        command = namespace.command(["agy", "--version"])
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_DIRS", "XDG_RUNTIME_DIR"):
            assert name in command
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="customization source"):
            evidence.freeze_customization_inventory(home=tmp_path, project_dir=tmp_path, env={"XDG_CONFIG_HOME": "/tmp/host-config"})
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="bootstrap-attested dotfiles repository"):
            evidence.finalize_canary(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


def test_namespace_binds_trusted_home_agi_at_fixed_path_without_exposing_home(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    root = _private_root(tmp_path)
    try:
        source = tmp_path / "agy"
        source.write_bytes(b"trusted-agy")
        source.chmod(0o700)
        info = source.stat()
        runtime = evidence._TrustedAgyRuntime(source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
        monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
        command = evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid").agy_command(["agy", "--version"])
        assert "--tmpfs" in command and "/home" in command
        assert str(source) in command and runtime.destination in command
        assert command[-3:] == ["--", runtime.destination, "--version"]
        source.write_bytes(b"replaced")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
            evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid").agy_command(["agy", "--version"])
    finally:
        shutil.rmtree(root)


def test_probe_revalidates_trusted_executable_before_host_exec(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    source = tmp_path / "agy"
    source.write_bytes(b"trusted")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
    monkeypatch.setattr(evidence._TrustedAgyRuntime, "revalidate", lambda _self: (_ for _ in ()).throw(evidence.AgyCanaryEvidenceError("drift")))
    monkeypatch.setattr(evidence.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("host agy must not execute after drift"))
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="drift"):
        evidence.probe_capability(evidence_root=root)
    shutil.rmtree(root)


def test_native_codex_runtime_requires_fixed_launcher_assets_and_provenance(monkeypatch, tmp_path):
    home = tmp_path / "account-home"
    vendor = home / ".npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl"
    for relative in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg", "codex-resources/bwrap", "codex-package.json"):
        path = vendor / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if relative.endswith(".json") else "native", encoding="utf-8")
        path.chmod(0o700)
    (vendor / "codex-package.json").write_text(json.dumps({"version": "0.147.0"}))
    package = vendor.parent.parent / "package.json"
    package.write_text(json.dumps({"name": "@openai/codex", "version": "0.147.0-linux-x64"}))
    launcher = home / ".npm-global/bin/codex"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to("../lib/node_modules/@openai/codex/bin/codex.js")
    monkeypatch.setattr(evidence, "_account_home", lambda: home)
    runtime = evidence._trusted_provider_runtime("codex")
    assert runtime.child_argv(["--version"]) == [
        "/run/phase-loop-bin/codex/bin/codex", "--version"
    ]
    assert runtime.runtime_binds() == ((vendor, "/run/phase-loop-bin/codex"),)
    launcher.unlink()
    launcher.symlink_to("../unsafe")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="launcher drifted"):
        runtime.revalidate()


def test_provider_launch_authority_revalidates_runtime_and_exactly_ingests_output(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    root = _private_root(tmp_path)
    output = Path("/tmp") / f"phase-loop-provider-output.test-{os.getpid()}-{tmp_path.name}"
    output.mkdir(mode=0o700)
    source = tmp_path / "codex"
    source.write_bytes(b"trusted-codex")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedProviderRuntime(
        "codex", source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    try:
        authority = evidence.ProviderLaunchAuthority(
            "codex", runtime,
            evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid", provider_output=output),
            (),
        )
        command = authority.command(["codex", "exec", "review"])
        assert "/run/phase-loop-bin/codex" in command
        proof = authority.projected_auth_proof()
        assert proof["provider"] == "codex" and proof["records"] == []
        assert "authenticated" not in proof and "logged_in" not in proof
        assert authority.write_expected_output("result.json", b"accepted") == b"accepted"
        assert authority.read_expected_output("result.json") == b"accepted"
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="not empty"):
            authority.write_expected_output("second.json", b"forged")
        (output / "result.json").unlink()
        (output / "result.json").symlink_to(source)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="not empty"):
            authority.write_expected_output("result.json", b"forged")
        (output / "result.json").unlink()
        (output / "extra.log").write_bytes(b"forged")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="not empty"):
            authority.write_expected_output("result.json", b"forged")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="output set"):
            authority.read_expected_output("result.json")
        (output / "extra.log").unlink()
        source.write_bytes(b"replaced")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
            authority.command(["codex", "exec", "review"])
    finally:
        shutil.rmtree(output)
        shutil.rmtree(root)


def test_stage_binding_rejects_swapped_plan_or_parent_instruction(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    try:
        (stage / "review-bundle.md").write_text("attested plan")
        (stage / "review-instructions.md").write_text("canonical instructions")
        for name in ("review-bundle.md", "review-instructions.md"):
            (stage / name).chmod(0o600)
        capture = _prepare_production_capture(
            monkeypatch=monkeypatch, tmp_path=tmp_path, root=root,
            settings=_settings(tmp_path, []), seat_key="gemini-primary",
            plan_bytes=b"attested plan",
        )
        try:
            _bind_stage(capture, stage)
            (stage / "review-bundle.md").write_text("swapped plan")
            (stage / "review-bundle.md").chmod(0o600)
            with pytest.raises(evidence.AgyCanaryEvidenceError, match="binding bytes drifted"):
                evidence.prepare_provider_launch_authorities(
                    capture=capture, stage=stage, providers=("gemini",)
                )
        finally:
            capture.close()
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("size", [evidence._MAX_FULL_STAGED_READ_BYTES, evidence._MAX_FULL_STAGED_READ_BYTES + 1])
def test_stage_binding_enforces_exact_full_read_limit(monkeypatch, tmp_path, size):
    root = _private_root(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    bundle = b"x" * size
    try:
        (stage / "review-bundle.md").write_bytes(bundle)
        (stage / "review-instructions.md").write_text("instructions")
        for name in ("review-bundle.md", "review-instructions.md"):
            (stage / name).chmod(0o600)
        capture = _prepare_production_capture(
            monkeypatch=monkeypatch, tmp_path=tmp_path, root=root,
            settings=_settings(tmp_path, []), seat_key="gemini-primary", plan_bytes=bundle,
        )
        try:
            if size == evidence._MAX_FULL_STAGED_READ_BYTES:
                _bind_stage(capture, stage)
            else:
                with pytest.raises(evidence.AgyCanaryEvidenceError, match="full-read evidence limit"):
                    _bind_stage(capture, stage)
        finally:
            capture.close()
    finally:
        shutil.rmtree(root)


def test_full_read_limit_includes_current_governed_plan_snapshot():
    current_governed_plan_bytes = 205_865
    assert evidence._MAX_FULL_STAGED_READ_BYTES == 262_144
    assert current_governed_plan_bytes <= evidence._MAX_FULL_STAGED_READ_BYTES


def test_provider_launch_authority_rejects_legacy_prepare_without_immutable_authority(tmp_path):
    root = _private_root(tmp_path)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    home = None
    try:
        ledger = evidence.create_capture(
            capture=capture, settings_path=_settings(tmp_path, []), seat_key="gemini-primary",
            source_inventory=_source_inventory(tmp_path),
        )
        home, _binds = evidence.build_minimal_home(
            evidence_root=root, settings_path=_settings(tmp_path, [])
        )
        ledger.update({"minimal_home": str(home), "auth_binds": []})
        evidence._write_replace_at(capture.root_fd, "agy-launch-ledger.json", ledger)
        evidence._exclusive_write_at(
            capture.root_fd, "agy_canary_prepare.json",
            evidence._canonical_json({
                "schema": "agy_canary_prepare.v1", "seat_key": ledger["seat_key"],
                "ledger_sha256": evidence._sha256(evidence._canonical_json(ledger)),
            }), 0o600,
        )
        stage = tmp_path / "legacy-stage"
        stage.mkdir()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="invalid private evidence record"):
            evidence.prepare_provider_launch_authorities(
                capture=capture, stage=stage, providers=("gemini",)
            )
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="invalid private evidence record"):
            evidence.capture_namespace(capture=capture, stage=stage)
    finally:
        capture.close()
        if home is not None:
            shutil.rmtree(home)
        shutil.rmtree(root)


def test_advisor_board_cli_seals_and_verifies_capture_summary(monkeypatch, tmp_path):
    """The public command, not its sink helper, must bind the private payload."""
    from phase_loop_runtime.advisor_board.schema import Board, Seat
    from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult
    from phase_loop_runtime.advisor_board import composition
    from phase_loop_runtime import panel_invoker

    root = _private_root(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    contents = {"review-instructions.md": "instructions", "review-bundle.md": "bundle"}
    for name, value in contents.items():
        path = stage / name
        path.write_text(value)
        path.chmod(0o600)
    settings = _settings(tmp_path, [])
    capture = None
    try:
        capture = _prepare_production_capture(
            monkeypatch=monkeypatch, tmp_path=tmp_path, root=root, settings=settings,
            seat_key="gemini-primary", plan_bytes=(stage / "review-bundle.md").read_bytes(),
        )
        _bind_stage(capture, stage)
        staged = evidence.retain_staged_files(capture=capture, review_dir=stage)
        events = [
            {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
            {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": contents["review-instructions.md"]},
            {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
            {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": contents["review-bundle.md"]},
            {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
        ]
        evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(item) for item in events), stderr="", staged=staged)
        _seal_synthetic_provider_results(
            capture, _usable_private_board({"gemini_seat_key": "gemini-primary"})
        )
        expected = evidence.capture_summary(capture)
    finally:
        if capture is not None:
            capture.close()
    board = Board("synthetic", "test", (
        Seat("gemini-3.6-flash", "high", harness="gemini"), Seat("gpt-5.6-sol", "high", harness="codex"), Seat("claude-opus", "high", harness="claude"), Seat("grok-4.5", "high", harness="grok"),
    ))
    result = PanelResult(tuple(PanelLegResult(leg=seat.harness or "x", seat_key="gemini-primary" if seat.harness == "gemini" else seat.harness, status="OK", text="AGREE") for seat in board.seats))
    object.__setattr__(result, "_agy_canary_capture", expected)
    monkeypatch.setattr(composition, "compose_review_board", lambda: board)
    monkeypatch.setattr(panel_invoker, "invoke_board", lambda *_args, **_kwargs: result)
    artifact = tmp_path / "review.md"
    artifact.write_text("review")
    monkeypatch.setenv("PHASE_LOOP_AGY_CANARY_EVIDENCE_DIR", str(root))
    args = argparse.Namespace(artifact=str(artifact), json=True, agy_canary_private_board_name="board.json")
    assert cli._advisor_board_command(args=args) == 0
    ledger = json.loads((root / "agy-launch-ledger.json").read_text())
    board_bytes = (root / "board.json").read_bytes()
    assert ledger["private_board"]["sha256"] == evidence._sha256(board_bytes)
    assert json.loads(board_bytes)["agy_canary_capture"] == ledger["private_board"]["capture"]
    proof = evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)
    assert proof["attempt_ids"] == ["gemini-1"]
    assert proof["provider_results"] == expected["provider_results"]
    _root, root_fd = evidence._validate_private_root(root)
    try:
        registry = evidence._provider_registry(root_fd=root_fd)
        codex = next(entry for entry in registry["entries"] if entry["provider"] == "codex")
        original_result = evidence._read_json_at(root_fd, codex["result_name"])
        changed_result = dict(original_result)
        changed_attempts = dict(original_result["attempts"])
        changed_attempts["attempts"] = [
            *changed_attempts["attempts"],
            {"index": 1, **changed_attempts["launch"]},
        ]
        changed_attempts["terminal_attempt"] = 1
        changed_result["attempts"] = changed_attempts
        evidence._write_replace_at(root_fd, codex["result_name"], changed_result)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="does not bind the sealed capture summary"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)
        evidence._write_replace_at(root_fd, codex["result_name"], original_result)
    finally:
        os.close(root_fd)
    retained = root / "staged-review-instructions.md"
    retained.write_text("forged")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="retained input bytes drifted"):
        evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)
    retained.write_text(contents["review-instructions.md"])
    (root / "board.json").write_text("{}")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
        evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)
    shutil.rmtree(root)


def test_advisor_board_cli_real_invoker_capture_path_binds_stage_before_launch(monkeypatch, tmp_path):
    from phase_loop_runtime.advisor_board.schema import Board, Seat
    from phase_loop_runtime.advisor_board import composition
    from phase_loop_runtime import panel_invoker
    root = _private_root(tmp_path)
    capture = _prepare_production_capture(
        monkeypatch=monkeypatch, tmp_path=tmp_path, root=root,
        settings=_settings(tmp_path, []), seat_key="gemini:gemini-3.6-flash:high", plan_bytes=b"review",
    )
    capture.close()
    source = tmp_path / "agy"; source.write_bytes(b"agy"); source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
    provider_runtime = evidence._TrustedProviderRuntime(
        "gemini", source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    monkeypatch.setattr(evidence, "_trusted_provider_runtime", lambda provider: provider_runtime)
    self_tests = []
    monkeypatch.setattr(
        evidence,
        "namespace_self_test",
        lambda **kwargs: self_tests.append(kwargs["namespace"]) or {"synthetic": True},
    )
    monkeypatch.setattr(
        evidence.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Preflight", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(composition, "compose_review_board", lambda: Board("one", "review", (Seat("gemini-3.6-flash", "high", harness="gemini"),)))
    seen = []
    def fake_liveness(command, *, cwd, **_kwargs):
        seen.append(command)
        review = Path(cwd)
        events = []
        for index, name in enumerate(("review-instructions.md", "review-bundle.md")):
            events += [{"sequence": index * 2, "session_id": "s", "type": "tool_call", "call_id": str(index), "tool": "read_file", "target": f"/run/phase-loop-review/{name}"}, {"sequence": index * 2 + 1, "session_id": "s", "type": "tool_result", "call_id": str(index), "outcome": "success", "content": (review / name).read_text()}]
        events.append({"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"})
        return panel_invoker._LegRun(0, "\n".join(json.dumps(item) for item in events), "")
    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", fake_liveness)
    artifact = tmp_path / "artifact.md"; artifact.write_text("review")
    monkeypatch.setenv("PHASE_LOOP_AGY_CANARY_EVIDENCE_DIR", str(root))
    assert cli._advisor_board_command(args=argparse.Namespace(artifact=str(artifact), json=True, agy_canary_private_board_name="real.json")) == 2
    assert not seen and not self_tests
    shutil.rmtree(root)


def test_bootstrap_environment_never_uses_attacker_path_or_home(monkeypatch, tmp_path):
    account_home = tmp_path / "kernel-account-home"
    (account_home / ".local" / "share" / "uv" / "tools").mkdir(parents=True)
    (account_home / ".local" / "share" / "uv" / "python").mkdir(parents=True)
    (account_home / ".cache" / "uv").mkdir(parents=True)
    trusted_uv = account_home / ".local" / "bin" / "uv"
    trusted_uv.parent.mkdir(parents=True)
    trusted_uv.write_text("#!/bin/sh\nexit 0\n")
    trusted_uv.chmod(0o700)
    attacker_bin = tmp_path / "attacker-bin"
    attacker_bin.mkdir()
    attacker_uv = attacker_bin / "uv"
    attacker_uv.write_text("#!/bin/sh\nexit 1\n")
    attacker_uv.chmod(0o700)
    monkeypatch.setattr(evidence, "_account_home", lambda: account_home)
    monkeypatch.setenv("PATH", f"{attacker_bin}:/usr/bin")
    monkeypatch.setenv("HOME", str(account_home))
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "attacker-tools"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "attacker-data"))
    interpreter_authority = evidence._system_interpreter_authority()
    uv_store_authority = evidence._uv_store_authority(
        account_home=account_home, workspace_root=tmp_path / "no-workspace",
    )
    environment = evidence._bootstrap_environment(
        uv_executable=Path("/trusted/uv"), account_home=account_home,
        interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )
    assert environment["PATH"].startswith("/trusted:")
    assert str(attacker_bin) not in environment["PATH"]
    assert environment["UV_PYTHON"] == interpreter_authority["path"]
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert environment["UV_TOOL_DIR"] == uv_store_authority["directories"]["tool"]["path"]
    assert environment["UV_TOOL_BIN_DIR"] == uv_store_authority["directories"]["bin"]["path"]
    assert environment["UV_CACHE_DIR"] == uv_store_authority["directories"]["cache"]["path"]
    assert environment["UV_PYTHON_INSTALL_DIR"] == uv_store_authority["directories"]["python"]["path"]
    assert uv_store_authority["policy"] == "home"
    assert "XDG_DATA_HOME" not in environment
    assert set(environment) == {
        "HOME", "PATH", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_CACHE_DIR",
        "UV_PYTHON_INSTALL_DIR", "UV_PYTHON", "UV_PYTHON_DOWNLOADS",
    }
    assert not any(name.startswith(("PHASE_LOOP_", "AGENT_HARNESS_")) or "NONCE" in name for name in environment)
    assert evidence._canonical_bash() != attacker_bin / "bash"
    assert evidence._canonical_uv() == trusted_uv
    fake_home = tmp_path / "attacker-home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    fake_uv = fake_home / ".local" / "bin" / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 0\n")
    fake_uv.chmod(0o700)
    monkeypatch.setenv("HOME", str(fake_home))
    assert evidence._canonical_uv() == trusted_uv
    assert evidence._canonical_uv() != fake_uv
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="HOME drift"):
        evidence._bootstrap_environment(
            uv_executable=Path("/trusted/uv"), account_home=account_home,
            interpreter_authority=interpreter_authority,
            uv_store_authority=uv_store_authority,
        )


def test_uv_store_authority_matches_committed_workspace_policy(tmp_path):
    account_home = tmp_path / "account-home"
    (account_home / ".local" / "bin").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    (workspace / "uv-data" / "tools").mkdir(parents=True)
    (workspace / "uv-data" / "python").mkdir(parents=True)
    (workspace / "uv-cache").mkdir()
    authority = evidence._uv_store_authority(
        account_home=account_home, workspace_root=workspace,
    )
    assert authority["policy"] == "workspace"
    assert authority["workspace"]["selector"] == str(workspace)
    assert authority["directories"]["tool"]["path"] == str(
        workspace / "uv-data" / "tools"
    )
    assert authority["directories"]["cache"]["path"] == str(workspace / "uv-cache")
    assert authority["directories"]["python"]["path"] == str(
        workspace / "uv-data" / "python"
    )
    environment = evidence._uv_environment(
        uv_executable=Path("/trusted/uv"),
        interpreter_authority=evidence._system_interpreter_authority(),
        uv_store_authority=authority,
    )
    assert environment["UV_TOOL_DIR"] == str(workspace / "uv-data" / "tools")
    assert environment["UV_CACHE_DIR"] == str(workspace / "uv-cache")
    assert environment["UV_PYTHON_INSTALL_DIR"] == str(workspace / "uv-data" / "python")


@pytest.mark.parametrize("override", ["UV_TOOL_DIR", "XDG_DATA_HOME"])
def test_bootstrap_attest_rejects_prepopulated_uv_store_substitution(
    monkeypatch, tmp_path, override,
):
    attacker = tmp_path / "attacker-store"
    forged = attacker / "uv" / "tools" / "phase-loop-runtime"
    forged.mkdir(parents=True)
    (forged / "uv-receipt.toml").write_text(
        'requirements = [{ name = "phase-loop-runtime", specifier = "==0.7.14" }]\n'
    )
    monkeypatch.setenv(override, str(attacker))
    root = _private_root(tmp_path)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match=override):
        evidence.bootstrap_attest(
            evidence_root=root,
            dotfiles_repo=tmp_path / "dotfiles",
            plan_path=Path("plans/canary.md"),
        )


@_requires_memfd
def test_sealed_tree_preserves_repo_zero_and_reads_exact_pin(tmp_path):
    repo = tmp_path / "dotfiles"
    (repo / "shared").mkdir(parents=True)
    bootstrap_path = repo / "bootstrap.sh"
    bootstrap_path.write_text(
        '#!/usr/bin/bash\nDOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'printf "%s\\n" "$DOTFILES_DIR"\n'
        'cat "$DOTFILES_DIR/shared/agent-harness.pin"\n'
    )
    bootstrap_path.chmod(0o755)
    (repo / "shared" / "agent-harness.pin").write_text("v0.7.14\n")
    _git_repo(repo)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    snapshot = evidence._git_tree_snapshot(repo.resolve(), head, materialize=True)
    store = _installation_identity()["uv_store_authority"]
    environment = {"PATH": "/usr/bin:/bin"}
    argv, sandbox = evidence._tree_snapshot_bwrap_argv(
        snapshot=snapshot, bwrap=Path("/usr/bin/bwrap"), bash=Path("/usr/bin/bash"),
        environment=environment, account_home=evidence._account_home(),
        uv_store_authority=store, evidence_root_masking=_evidence_masking(tmp_path),
    )
    try:
        proc = subprocess.run(
            argv, pass_fds=snapshot.fds, capture_output=True, text=True, check=False,
        )
    finally:
        snapshot.close()
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == [str(repo), "v0.7.14"]
    assert sandbox["passed_fd_count"] == 2
    assert "--remount-ro" in argv


@_requires_memfd
def test_sealed_tree_ignores_transient_host_mutation_and_untracked_extra(tmp_path):
    repo = tmp_path / "dotfiles"
    (repo / "shared").mkdir(parents=True)
    bootstrap = repo / "bootstrap.sh"
    helper = repo / "shared" / "helper.sh"
    pin = repo / "shared" / "agent-harness.pin"
    bootstrap.write_text(
        '#!/usr/bin/bash\nsleep 0.5\nDOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'cat "$DOTFILES_DIR/shared/agent-harness.pin"\n'
        'cat "$DOTFILES_DIR/shared/helper.sh"\n'
        'test -x "$DOTFILES_DIR/shared/helper.sh" && echo executable\n'
        'test ! -e "$DOTFILES_DIR/untracked-attacker" && echo no-extra\n'
        'test ! -e "$DOTFILES_DIR/.git" && echo no-git-metadata\n'
    )
    bootstrap.chmod(0o755)
    helper.write_text("trusted-helper\n")
    helper.chmod(0o755)
    pin.write_text("v0.7.14\n")
    (repo / "untracked-attacker").write_text("attacker\n")
    (repo / ".gitignore").write_text("untracked-attacker\n")
    _git_repo(repo)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    snapshot = evidence._git_tree_snapshot(repo.resolve(), head, materialize=True)
    store = _installation_identity()["uv_store_authority"]
    argv, _sandbox = evidence._tree_snapshot_bwrap_argv(
        snapshot=snapshot, bwrap=Path("/usr/bin/bwrap"), bash=Path("/usr/bin/bash"),
        environment={"PATH": "/usr/bin:/bin"}, account_home=evidence._account_home(),
        uv_store_authority=store, evidence_root_masking=_evidence_masking(tmp_path),
    )
    try:
        proc = subprocess.Popen(
            argv, pass_fds=snapshot.fds, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        pin.write_text("v9.9.9-attacker\n")
        helper.write_text("attacker-helper\n")
        namespace_pid = None
        for _attempt in range(50):
            pending = [proc.pid]
            descendants: list[int] = []
            while pending:
                parent_pid = pending.pop()
                children = Path(f"/proc/{parent_pid}/task/{parent_pid}/children")
                child_pids = [
                    int(value) for value in children.read_text().split()
                ] if children.exists() else []
                descendants.extend(child_pids)
                pending.extend(child_pids)
            for candidate in descendants:
                candidate_view = Path(f"/proc/{candidate}/root") / helper.relative_to("/")
                try:
                    if candidate_view.read_text() == "trusted-helper\n":
                        namespace_pid = candidate
                        break
                except (FileNotFoundError, PermissionError):
                    continue
            if namespace_pid is not None:
                break
            time.sleep(0.01)
        assert namespace_pid is not None
        child_view = Path(f"/proc/{namespace_pid}/root") / helper.relative_to("/")
        assert child_view.read_text() == "trusted-helper\n"
        with pytest.raises(OSError):
            fd = os.open(child_view, os.O_WRONLY | os.O_TRUNC)
            os.close(fd)
        pin.write_text("v0.7.14\n")
        helper.write_text("trusted-helper\n")
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        snapshot.close()
    assert proc.returncode == 0, stderr
    assert stdout.splitlines() == [
        "v0.7.14", "trusted-helper", "executable", "no-extra", "no-git-metadata",
    ]


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "a\\b", "line\nbreak", "a//b", "a/./b"],
)
def test_tree_snapshot_rejects_unsafe_inventory_paths(path):
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="path is unsafe"):
        evidence._snapshot_relative_path(path)


@pytest.mark.parametrize("target", [b"/etc/passwd", b"../../escape", b"bad\nname"])
def test_tree_snapshot_rejects_unsafe_symlink_targets(target):
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="symlink"):
        evidence._snapshot_symlink_target(Path("shared/link"), target)


@_requires_memfd
def test_tree_snapshot_mounts_safe_committed_symlink(tmp_path):
    repo = tmp_path / "dotfiles"
    (repo / "shared").mkdir(parents=True)
    bootstrap = repo / "bootstrap.sh"
    bootstrap.write_text('#!/usr/bin/bash\ncat "$(dirname "$0")/shared/pin-link"\n')
    bootstrap.chmod(0o755)
    (repo / "shared" / "agent-harness.pin").write_text("v0.7.14\n")
    (repo / "shared" / "pin-link").symlink_to("agent-harness.pin")
    _git_repo(repo)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    snapshot = evidence._git_tree_snapshot(repo.resolve(), head, materialize=True)
    store = _installation_identity()["uv_store_authority"]
    argv, _sandbox = evidence._tree_snapshot_bwrap_argv(
        snapshot=snapshot, bwrap=Path("/usr/bin/bwrap"), bash=Path("/usr/bin/bash"),
        environment={"PATH": "/usr/bin:/bin"}, account_home=evidence._account_home(),
        uv_store_authority=store, evidence_root_masking=_evidence_masking(tmp_path),
    )
    try:
        proc = subprocess.run(
            argv, pass_fds=snapshot.fds, capture_output=True, text=True, check=False,
        )
    finally:
        snapshot.close()
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "v0.7.14\n"


@pytest.mark.parametrize("mutation", ["missing", "extra", "digest"])
def test_tree_snapshot_authority_rejects_missing_extra_or_rebound_inventory(tmp_path, mutation):
    repo = tmp_path / "dotfiles"
    repo.mkdir()
    (repo / "bootstrap.sh").write_text("#!/bin/sh\n")
    (repo / "tracked.txt").write_text("tracked\n")
    _git_repo(repo)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    authority = evidence._git_tree_snapshot(repo.resolve(), head, materialize=False).authority
    authority = json.loads(json.dumps(authority))
    if mutation == "missing":
        authority["entry_count"] -= 1
        authority["file_count"] -= 1
    elif mutation == "extra":
        authority["entry_count"] += 1
        authority["file_count"] += 1
    else:
        authority["inventory_sha256"] = "0" * 64
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="authority drifted"):
        evidence._validate_tree_snapshot_authority(authority, repo=repo, commit=head)


def test_tree_snapshot_fails_when_exact_gitlink_checkout_is_unavailable(tmp_path):
    subrepo = tmp_path / "source-submodule"
    subrepo.mkdir()
    (subrepo / "tracked.txt").write_text("tracked\n")
    _git_repo(subrepo)
    submodule_commit = subprocess.check_output(
        ["git", "-C", str(subrepo), "rev-parse", "HEAD"], text=True,
    ).strip()
    repo = tmp_path / "dotfiles"
    repo.mkdir()
    (repo / "bootstrap.sh").write_text("#!/bin/sh\n")
    _git_repo(repo)
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--add", "--cacheinfo",
         f"160000,{submodule_commit},vendor"], check=True,
    )
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "gitlink"], check=True)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="submodule checkout"):
        evidence._git_tree_snapshot(repo.resolve(), head, materialize=False)


def _canonical_dotfiles_snapshot_sandbox(
    snapshot: evidence._GitTreeSnapshot,
) -> dict[str, object]:
    class FixedAccountHome:
        @staticmethod
        def resolve(*, strict):
            assert strict
            return Path("/home/viperjuice")

    environment = {
        "HOME": "/home/viperjuice",
        "PATH": "/home/viperjuice/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "UV_CACHE_DIR": "/mnt/workspace/uv-cache",
        "UV_PYTHON": "/usr/bin/python3.10",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_PYTHON_INSTALL_DIR": "/mnt/workspace/uv-data/python",
        "UV_TOOL_BIN_DIR": "/home/viperjuice/.local/bin",
        "UV_TOOL_DIR": "/mnt/workspace/uv-data/tools",
    }
    _argv, sandbox = evidence._tree_snapshot_bwrap_argv(
        snapshot=snapshot, bwrap=Path("/usr/bin/bwrap"),
        bash=Path("/usr/bin/bash"), environment=environment,
        account_home=FixedAccountHome(),  # type: ignore[arg-type]
        uv_store_authority={
            "workspace": {"resolved": "/mnt/HC_Volume_105438154"},
        },
        evidence_root_masking={
            "schema": "agy_canary_evidence_root_mask.v1",
            "path": "/tmp/canonical-fixture", "dev": 1, "inode": 1,
            "uid": 0, "mode": 0o700, "strategy": "private_tmpfs",
            "child_visible": False,
        },
        identity_only=True,
    )
    return sandbox


def test_tree_snapshot_real_inventory_scale_fits_process_boundary():
    mount_path = "/mnt/HC_Volume_105438154/code/dotfiles"
    parent_lengths = [38] * 209 + [37] * 55
    parents = [
        f"p{index:03d}" + "d" * (length - 4)
        for index, length in enumerate(parent_lengths)
    ]
    parent_contribution = sum(
        len(parents[index % len(parents)]) for index in range(1_212)
    )
    filename_bytes = 63_708 - parent_contribution - 1_212
    baseline_filename_bytes = 5 * 1_212
    filler_bytes, remainder = divmod(
        filename_bytes - baseline_filename_bytes, 1_212,
    )
    entries = tuple(
        evidence._TreeSnapshotEntry(
            path=(
                f"{parents[index % len(parents)]}/f{index:04d}" +
                "x" * (filler_bytes + (index < remainder))
            ),
            mode="100644", oid="a" * 40,
        )
        for index in range(1_212)
    )
    snapshot = evidence._GitTreeSnapshot(
        authority={"mount_path": mount_path, "file_count": 1_212},
        entries=entries,
    )
    sandbox = _canonical_dotfiles_snapshot_sandbox(snapshot)
    absolute_parents = {
        str(Path(mount_path) / parent) for parent in parents
    }
    assert len(entries) == sandbox["passed_fd_count"] == 1_212
    assert len(absolute_parents) == 264
    assert sum(len(entry.path.encode()) for entry in entries) == 63_708
    assert sum(len(path.encode()) for path in absolute_parents) == 20_273
    assert sandbox["argv_count"] == 6_648
    assert sandbox["argv_bytes"] == 235_828
    assert sandbox["argv_bytes"] < evidence._MAX_FULL_STAGED_READ_BYTES
    assert evidence._MAX_FULL_STAGED_READ_BYTES < os.sysconf("SC_ARG_MAX")


def test_exact_dotfiles_head_snapshot_boundary_when_checkout_is_available():
    head = "50966ed30d6a210c8b3006928b41ff2351e10e1b"
    plan_path = "plans/detailed-replan-176-agy-review-boundary-20260803-0715.md"
    candidates = [
        Path(value) for value in (
            os.environ.get("AGY_CANARY_DOTFILES_REPO", ""),
            "/home/viperjuice/code/dotfiles",
            "/mnt/HC_Volume_105438154/code/dotfiles",
        ) if value
    ]
    repo = next((path.resolve() for path in candidates if (path / ".git").exists()), None)
    if repo is None:
        pytest.skip("exact dotfiles checkout is unavailable")
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{head}^{{commit}}"],
        capture_output=True, text=True, check=False,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != head:
        pytest.skip("exact dotfiles commit is unavailable")
    try:
        snapshot = evidence._git_tree_snapshot(repo, head, materialize=False)
    except evidence.AgyCanaryEvidenceError as exc:
        if "submodule checkout" in str(exc):
            pytest.skip("exact dotfiles submodule checkout is unavailable")
        raise
    plan = subprocess.run(
        ["git", "-C", str(repo), "show", f"{head}:{plan_path}"],
        capture_output=True, check=True,
    ).stdout
    plan_blob = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", f"{head}:{plan_path}"], text=True,
    ).strip()
    assert plan_blob == "3fa210e59daa470b1cea25474200ae3a736c8316"
    assert len(plan) == 205_865
    assert snapshot.authority == {
        "schema": evidence._TREE_SNAPSHOT_SCHEMA,
        "commit": head,
        "tree_oid": "b1fa31dd01dac62863796e6cf944c065aa555ea6",
        "mount_path": str(repo),
        "inventory_sha256": "f5a83e216a8fbb17c1946d7fcb22d3baa401c0da4961205a014bdffebf32e7b2",
        "entry_count": 1_212, "file_count": 1_212,
        "executable_count": 161, "symlink_count": 0,
        "gitlink_count": 1,
        "submodules": [{
            "path": "anthropic-skills",
            "commit": "57546260929473d4e0d1c1bb75297be2fdfa1949",
            "tree_oid": "85bb6be91988eb679e3c636f755b91a7d65a680d",
            "inventory_sha256": "6abe23adc9cadc8223acf9b5ef056fc541a2873e55b54a836f655c411bf2e299",
            "entry_count": 398,
        }],
    }
    canonical_snapshot = evidence._GitTreeSnapshot(
        authority={
            **snapshot.authority,
            "mount_path": "/mnt/HC_Volume_105438154/code/dotfiles",
        },
        entries=snapshot.entries,
    )
    sandbox = _canonical_dotfiles_snapshot_sandbox(canonical_snapshot)
    assert sandbox["passed_fd_count"] == 1_212
    assert sandbox["argv_count"] == 6_648
    assert sandbox["argv_bytes"] == 235_828


@_requires_memfd
def test_sealed_tree_fd_uses_linux_abi_when_python_omits_fcntl_symbols(monkeypatch):
    real_fcntl = evidence.fcntl
    assert real_fcntl is not None

    class SymbolLessFcntl:
        fcntl = staticmethod(real_fcntl.fcntl)

    monkeypatch.setattr(evidence, "fcntl", SymbolLessFcntl)
    fd = evidence._sealed_tree_fd(data=b"trusted", executable=True, label="test")
    try:
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o755
        assert os.read(fd, 7) == b"trusted"
        assert real_fcntl.fcntl(fd, 1034) == 0xF
        with pytest.raises(OSError):
            os.write(fd, b"mutated")
    finally:
        os.close(fd)


def test_linux_memfd_abi_rejects_conflicting_python_binding(monkeypatch):
    class ConflictingFcntl:
        F_ADD_SEALS = 999

    monkeypatch.setattr(evidence, "fcntl", ConflictingFcntl)
    monkeypatch.setattr(evidence.os, "memfd_create", lambda *_args: -1, raising=False)
    monkeypatch.setattr(evidence.os, "MFD_ALLOW_SEALING", 2, raising=False)
    monkeypatch.setattr(evidence.os, "MFD_CLOEXEC", 1, raising=False)
    monkeypatch.setattr(evidence.sys, "platform", "linux")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="conflict"):
        evidence._linux_memfd_seal_abi()


@_requires_memfd
def test_tree_snapshot_short_write_closes_memfd(monkeypatch):
    created: list[int] = []
    real_create = os.memfd_create

    def record_create(name, flags):
        fd = real_create(name, flags)
        created.append(fd)
        return fd

    monkeypatch.setattr(evidence.os, "memfd_create", record_create)
    monkeypatch.setattr(evidence.os, "write", lambda _fd, _data: 0)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="short write"):
        evidence._sealed_tree_fd(data=b"tracked", executable=False, label="test")
    assert len(created) == 1
    with pytest.raises(OSError):
        os.fstat(created[0])


@_requires_memfd
def test_tree_snapshot_bwrap_rejects_missing_fd_and_argument_limit(monkeypatch, tmp_path):
    repo = tmp_path / "dotfiles"
    repo.mkdir()
    (repo / "bootstrap.sh").write_text("#!/bin/sh\n")
    _git_repo(repo)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    store = _installation_identity()["uv_store_authority"]
    evidence_root_masking = _evidence_masking(tmp_path)
    incomplete = evidence._git_tree_snapshot(repo.resolve(), head, materialize=False)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="descriptor is missing"):
        evidence._tree_snapshot_bwrap_argv(
            snapshot=incomplete, bwrap=Path("/usr/bin/bwrap"), bash=Path("/usr/bin/bash"),
            environment={"PATH": "/usr/bin:/bin"}, account_home=evidence._account_home(),
            uv_store_authority=store, evidence_root_masking=evidence_root_masking,
        )
    snapshot = evidence._git_tree_snapshot(repo.resolve(), head, materialize=True)
    real_sysconf = os.sysconf
    monkeypatch.setattr(
        evidence.os, "sysconf",
        lambda key: 1 if key == "SC_ARG_MAX" else real_sysconf(key),
    )
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="process argument"):
            evidence._tree_snapshot_bwrap_argv(
                snapshot=snapshot, bwrap=Path("/usr/bin/bwrap"), bash=Path("/usr/bin/bash"),
                environment={"PATH": "/usr/bin:/bin"}, account_home=evidence._account_home(),
                uv_store_authority=store,
                evidence_root_masking=evidence_root_masking,
            )
    finally:
        snapshot.close()


@pytest.mark.parametrize("failure", ["argmax", "popen"])
def test_bootstrap_snapshot_owner_closes_every_fd_before_child_failure(
    monkeypatch, tmp_path, failure,
):
    repo = tmp_path / "dotfiles"
    repo.mkdir()
    (repo / "bootstrap.sh").write_text("#!/bin/sh\n")
    read_fds: list[int] = []
    for _index in range(2):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        read_fds.append(read_fd)
    snapshot = evidence._GitTreeSnapshot(
        authority={"mount_path": str(repo), "file_count": 2},
        entries=tuple(
            evidence._TreeSnapshotEntry(
                path=f"tracked-{index}", mode="100644", oid=str(index + 1) * 40,
                fd=fd,
            )
            for index, fd in enumerate(read_fds)
        ),
    )
    monkeypatch.setattr(evidence, "_git_tree_snapshot", lambda *_args, **_kwargs: snapshot)
    store = _installation_identity()["uv_store_authority"]
    if failure == "argmax":
        real_sysconf = os.sysconf
        monkeypatch.setattr(
            evidence.os, "sysconf",
            lambda key: 1 if key == "SC_ARG_MAX" else real_sysconf(key),
        )
        match = "process argument"
    else:
        monkeypatch.setattr(
            evidence.subprocess, "Popen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("prelaunch")),
        )
        match = "could not start"
    with pytest.raises(evidence.AgyCanaryEvidenceError, match=match):
        evidence._launch_tree_snapshot_child(
            repo=repo, head="a" * 40, bwrap=Path("/usr/bin/bwrap"),
            bash=Path("/usr/bin/bash"), environment={"PATH": "/usr/bin:/bin"},
            account_home=evidence._account_home(), uv_store_authority=store,
            evidence_root_masking=_evidence_masking(tmp_path),
            local_source_seams=evidence._bootstrap_local_source_seams(repo),
        )
    for fd in read_fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize(
    "mutation",
    [
        "bootstrap_file", "bootstrap_symlink", "hook_file", "hook_symlink",
        "hooks_symlink", "hooks_unsafe_mode",
    ],
)
def test_bootstrap_local_source_seams_reject_files_and_symlinks(tmp_path, mutation):
    repo = tmp_path / "dotfiles"
    repo.mkdir()
    target = tmp_path / "target"
    target.write_text("attacker\n")
    if mutation == "bootstrap_file":
        (repo / "bootstrap.local.sh").write_text("attacker\n")
    elif mutation == "bootstrap_symlink":
        (repo / "bootstrap.local.sh").symlink_to(target)
    elif mutation == "hooks_symlink":
        (repo / "hooks").symlink_to(tmp_path, target_is_directory=True)
    else:
        (repo / "hooks").mkdir()
        if mutation == "hooks_unsafe_mode":
            (repo / "hooks").chmod(0o777)
        else:
            seam = repo / "hooks" / "post-bootstrap.local.sh"
            if mutation == "hook_file":
                seam.write_text("attacker\n")
            else:
                seam.symlink_to(target)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="local source seam"):
        evidence._bootstrap_local_source_seams(repo)


def test_bootstrap_receipt_revalidates_local_source_seam_absence(tmp_path):
    repo = tmp_path / "dotfiles"
    receipt = _bootstrap_receipt(
        installation=_installation_identity(), dotfiles_repo=repo,
    )
    (repo / "bootstrap.local.sh").write_text("attacker\n")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="local source seam"):
        evidence._validate_bootstrap_attestation(receipt=receipt)


def test_bootstrap_receipt_rejects_matching_decoy_source_path(tmp_path):
    repo = tmp_path / "dotfiles"
    receipt = _bootstrap_receipt(
        installation=_installation_identity(), dotfiles_repo=repo,
    )
    decoy = tmp_path / "decoy" / "bootstrap.sh"
    decoy.parent.mkdir()
    decoy.write_bytes((repo / "bootstrap.sh").read_bytes())
    receipt["tree_snapshot"]["mount_path"] = str(decoy.parent)
    receipt["bootstrap"]["sandbox"]["mount_path"] = str(decoy.parent)
    receipt["bootstrap"]["sandbox"]["command"][1] = str(decoy)
    receipt["bootstrap"]["sandbox"]["tmpfs"][2] = str(decoy.parent)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="mount path"):
        evidence._validate_bootstrap_attestation(receipt=receipt, repo=repo)


def test_uv_store_authority_rejects_symlink_and_sealed_identity_drift(tmp_path):
    account_home = tmp_path / "account-home"
    bin_dir = account_home / ".local" / "bin"
    uv_parent = account_home / ".local" / "share" / "uv"
    attacker_tools = tmp_path / "attacker-tools"
    bin_dir.mkdir(parents=True)
    uv_parent.mkdir(parents=True)
    (account_home / ".cache" / "uv").mkdir(parents=True)
    (uv_parent / "python").mkdir()
    attacker_tools.mkdir()
    (uv_parent / "tools").symlink_to(attacker_tools, target_is_directory=True)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="unsafe"):
        evidence._uv_store_authority(
            account_home=account_home, workspace_root=tmp_path / "no-workspace",
        )
    (uv_parent / "tools").unlink()
    (uv_parent / "tools").mkdir()
    authority = evidence._uv_store_authority(
        account_home=account_home, workspace_root=tmp_path / "no-workspace",
    )
    authority["directories"]["tool"]["inode"] += 1
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
        evidence._validate_uv_store_authority(authority, revalidate=True)


def test_bootstrap_receipt_rejects_self_consistent_manual_uv_store(tmp_path):
    installation = _installation_identity()
    receipt = _bootstrap_receipt(
        installation=installation,
        dotfiles_repo=tmp_path / "bootstrap-receipt-dotfiles",
    )
    attacker_home = tmp_path / "attacker-home"
    attacker_tool_dir = attacker_home / ".local" / "share" / "uv" / "tools"
    attacker_python_dir = attacker_home / ".local" / "share" / "uv" / "python"
    attacker_bin_dir = attacker_home / ".local" / "bin"
    attacker_cache_dir = attacker_home / ".cache" / "uv"
    attacker_tool_dir.mkdir(parents=True)
    attacker_python_dir.mkdir(parents=True)
    attacker_bin_dir.mkdir(parents=True)
    attacker_cache_dir.mkdir(parents=True)
    attacker_authority = evidence._uv_store_authority(
        account_home=attacker_home, workspace_root=tmp_path / "no-workspace",
    )
    forged_installation = receipt["bootstrap"]["installation"]
    assert isinstance(forged_installation, dict)
    forged_installation["uv_store_authority"] = attacker_authority
    forged_installation["uv_tool_dir"] = str(attacker_tool_dir)
    forged_installation["environment_root"] = str(attacker_tool_dir / "phase-loop-runtime")
    forged_installation["console_script"] = str(
        attacker_tool_dir / "phase-loop-runtime" / "bin" / "phase-loop"
    )
    forged_installation["distribution_root"] = str(
        attacker_tool_dir / "phase-loop-runtime" / "lib" / "python" / "site-packages"
    )
    forged_installation["module_origin"] = str(
        Path(forged_installation["distribution_root"]) /
        "phase_loop_runtime" / "__init__.py"
    )
    receipt["bootstrap"]["uv_store_authority"] = attacker_authority
    forged_environment = receipt["bootstrap"]["uv_environment"]
    assert isinstance(forged_environment, dict)
    forged_environment["HOME"] = str(attacker_home)
    forged_environment["UV_TOOL_DIR"] = str(attacker_tool_dir)
    forged_environment["UV_TOOL_BIN_DIR"] = str(attacker_bin_dir)
    forged_environment["UV_CACHE_DIR"] = str(attacker_cache_dir)
    forged_environment["UV_PYTHON_INSTALL_DIR"] = str(attacker_python_dir)
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="account home drifted"):
        evidence._validate_bootstrap_attestation(receipt=receipt)


@pytest.mark.parametrize("mutation", ["symlink", "uid", "mode", "hash"])
def test_interpreter_authority_rejects_wrong_symlink_owner_mode_or_hash(mutation):
    authority = evidence._system_interpreter_authority()
    authority = dict(authority)
    if mutation == "symlink":
        authority["path"] = authority["selector"]
    elif mutation == "uid":
        authority["uid"] = 1
    elif mutation == "mode":
        authority["mode"] |= stat.S_IWGRP
    else:
        authority["sha256"] = "0" * 64
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="authority"):
        evidence._validate_interpreter_authority(authority, revalidate=True)


@_requires_memfd
def test_bootstrap_attestation_has_no_parent_only_nonce_claim(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    marker = root / "host-secret-marker"
    marker.write_text("private-evidence-secret\n")
    repo = tmp_path / "dotfiles"
    plan = repo / "plans" / "canary.md"
    plan.parent.mkdir(parents=True)
    (repo / "shared").mkdir()
    (repo / "bootstrap.sh").write_text(
        f"#!/bin/sh\ntest ! -e {root}/host-secret-marker || exit 91\nexit 0\n"
    )
    (repo / "shared" / "agent-harness.pin").write_text("v0.7.14\n")
    plan.write_text("# canary\n")
    (repo / "plans" / "manifest.json").write_text("{}\n")
    _git_repo(repo)
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n")
    uv.chmod(0o700)
    installation = _installation_identity()
    installation["uv_executable"] = str(uv)
    monkeypatch.setattr(evidence, "_canonical_bash", lambda: Path("/usr/bin/bash"))
    monkeypatch.setattr(evidence, "_canonical_uv", lambda: uv)
    monkeypatch.setattr(evidence, "_validate_bootstrap_uv_policy", lambda **_kwargs: None)
    monkeypatch.setattr(evidence, "_installed_phase_loop_identity", lambda **_kwargs: installation)
    monkeypatch.setattr(evidence.sys, "platform", "linux")
    for name in list(os.environ):
        if (name in {"DEV_EDITABLE", "PYTHONPATH", "PYTHONHOME"} or
                name.startswith(("PHASE_LOOP_", "AGENT_HARNESS_", "UV_", "XDG_"))):
            monkeypatch.delenv(name)
    try:
        receipt = evidence.bootstrap_attest(
            evidence_root=root, dotfiles_repo=repo, plan_path=Path("plans/canary.md")
        )
        assert evidence._validate_bootstrap_attestation(
            receipt=receipt, installation=installation
        ) == receipt
        assert receipt["bootstrap"]["returncode"] == 0
        assert receipt["bootstrap"]["installation"] == installation
        assert receipt["bootstrap"]["sandbox"]["evidence_root_masking"]["path"] == str(root)
        assert b"private-evidence-secret" not in evidence._canonical_json(receipt)
        assert "nonce_sha256" not in receipt
        assert not any(
            name.startswith(("PHASE_LOOP_", "AGENT_HARNESS_")) or "NONCE" in name
            for name in receipt["bootstrap"]["environment_names"]
        )
    finally:
        shutil.rmtree(root)


def test_release_lineage_uses_merged_handoff_and_rehashes_downloads(tmp_path, monkeypatch):
    repo = tmp_path / "agent-harness"
    (repo / "docs" / "releases").mkdir(parents=True)
    handoff = repo / "docs" / "releases" / "outside-agent-release-handoff.md"
    handoff.write_text("pending\n")
    _git_repo(repo)
    release_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(repo), "tag", "-am", "release", "v0.7.14", release_commit], check=True)
    tag_object = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "refs/tags/v0.7.14"], text=True).strip()
    wheel, sdist = _synthetic_wheel(), b"synthetic sdist"
    rows = [
        {"filename": "phase_loop_runtime-0.7.14-py3-none-any.whl", "packagetype": "bdist_wheel", "url": "https://example.invalid/wheel", "digests": {"sha256": hashlib.sha256(wheel).hexdigest()}},
        {"filename": "phase_loop_runtime-0.7.14.tar.gz", "packagetype": "sdist", "url": "https://example.invalid/sdist", "digests": {"sha256": hashlib.sha256(sdist).hexdigest()}},
    ]
    record = {
        "schema": "release_evidence.v1", "version": "0.7.14", "release_commit": release_commit,
        "tag_object": tag_object, "tag_peel": release_commit,
        "release_url": "https://example.invalid/release", "workflow_url": "https://example.invalid/workflow",
        "pypi_metadata_url": "https://pypi.org/pypi/phase-loop-runtime/0.7.14/json",
        "artifacts": [{key: row[key] for key in ("filename", "packagetype", "url")} | {"sha256": row["digests"]["sha256"]} for row in rows],
    }
    handoff.write_bytes(b"<!-- release_evidence.v1:start -->" + evidence._canonical_json(record) + b"<!-- release_evidence.v1:end -->")
    subprocess.run(["git", "-C", str(repo), "add", "docs/releases/outside-agent-release-handoff.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "handoff"], check=True)
    handoff_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", handoff_commit], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/Consiliency/agent-harness.git"], check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/phase-loop/canonical-main", handoff_commit], check=True)
    real_run = evidence.subprocess.run
    workflow_id = 123456
    workflow_definition = {
        "id": workflow_id, "path": ".github/workflows/publish-pypi.yml", "state": "active",
    }
    workflow_runs = [{
        "workflow_id": workflow_id, "head_sha": release_commit,
        "head_branch": "v0.7.14", "status": "completed",
        "conclusion": "success", "event": "push", "html_url": record["workflow_url"],
    }]
    workflow_pages = [{"total_count": 1, "workflow_runs": workflow_runs}]

    def fake_run(argv, **kwargs):
        if argv[:3] == ["git", "-C", str(repo)] and argv[3:5] == ["fetch", "--quiet"]:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if argv[:3] == ["git", "-C", str(repo)] and argv[3:5] == ["verify-tag", "--raw"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"tagName": "v0.7.14", "url": record["release_url"]}), "")
        if argv[:2] == ["gh", "api"] and "--paginate" not in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(workflow_definition), "")
        if argv[:3] == ["gh", "api", "--paginate"]:
            return subprocess.CompletedProcess(argv, 0, "\n".join(json.dumps(page) for page in workflow_pages), "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(evidence.subprocess, "run", fake_run)
    blobs = {row["url"]: wheel if row["url"].endswith("wheel") else sdist for row in rows}
    result = evidence._reconcile_release_lineage(
        repo=repo, handoff_commit=handoff_commit,
        fetch_json=lambda _url: {"urls": rows}, download=lambda url: blobs[url],
    )
    assert result["release_commit"] == release_commit
    assert result["wheel_binding"]["record_path"] == (
        "phase_loop_runtime-0.7.14.dist-info/RECORD"
    )
    assert result["wheel_binding"]["sha256"] == hashlib.sha256(wheel).hexdigest()
    workflow_pages[:] = [
        {"total_count": 21, "workflow_runs": workflow_runs * 20},
        {"total_count": 21, "workflow_runs": workflow_runs},
    ]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="publish workflow"):
        evidence._reconcile_release_lineage(
            repo=repo, handoff_commit=handoff_commit,
            fetch_json=lambda _url: {"urls": rows}, download=lambda url: blobs[url],
        )
    workflow_pages[:] = [{"total_count": 2, "workflow_runs": workflow_runs}]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="publish workflow"):
        evidence._reconcile_release_lineage(
            repo=repo, handoff_commit=handoff_commit,
            fetch_json=lambda _url: {"urls": rows}, download=lambda url: blobs[url],
        )
    workflow_definition["state"] = "disabled_manually"
    workflow_pages[:] = [{"total_count": 1, "workflow_runs": workflow_runs}]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="workflow definition"):
        evidence._reconcile_release_lineage(
            repo=repo, handoff_commit=handoff_commit,
            fetch_json=lambda _url: {"urls": rows}, download=lambda url: blobs[url],
        )
    workflow_definition["state"] = "active"
    for field, value in (
        ("workflow_id", workflow_id + 1),
        ("status", "in_progress"),
        ("head_branch", "main"),
    ):
        invalid = dict(workflow_runs[0])
        invalid[field] = value
        workflow_pages[:] = [{"total_count": 1, "workflow_runs": [invalid]}]
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="publish workflow"):
            evidence._reconcile_release_lineage(
                repo=repo, handoff_commit=handoff_commit,
                fetch_json=lambda _url: {"urls": rows}, download=lambda url: blobs[url],
            )
    workflow_pages[:] = [{"total_count": 1, "workflow_runs": workflow_runs}]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="downloaded release artifact digest mismatch"):
        evidence._reconcile_release_lineage(
            repo=repo, handoff_commit=handoff_commit,
            fetch_json=lambda _url: {"urls": rows}, download=lambda _url: b"forged",
        )


def _wheel_rows(wheel: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        raw = archive.read("phase_loop_runtime-0.7.14.dist-info/RECORD").decode()
    return list(csv.reader(io.StringIO(raw, newline="")))


@pytest.mark.parametrize("mutation", ["traversal", "duplicate", "algorithm", "size"])
def test_wheel_binding_rejects_unsafe_or_malformed_record_rows(mutation):
    wheel = _synthetic_wheel()
    rows = _wheel_rows(wheel)
    if mutation == "traversal":
        rows[0][0] = "../escape"
    elif mutation == "duplicate":
        rows.insert(1, list(rows[0]))
    elif mutation == "algorithm":
        rows[0][1] = "sha512=" + rows[0][1].split("=", 1)[1]
    else:
        rows[0][2] = "01"
    malformed = _synthetic_wheel(record_rows=rows)
    with pytest.raises(evidence.AgyCanaryEvidenceError):
        evidence._wheel_binding(
            wheel_bytes=malformed,
            filename="phase_loop_runtime-0.7.14-py3-none-any.whl",
            digest=evidence._sha256(malformed), url_sha256="a" * 64,
            version="0.7.14",
        )


def test_wheel_binding_rejects_archive_path_traversal_and_wrong_wheel():
    traversal = _synthetic_wheel(members={"../escape": b"escape"})
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="path"):
        evidence._wheel_binding(
            wheel_bytes=traversal,
            filename="phase_loop_runtime-0.7.14-py3-none-any.whl",
            digest=evidence._sha256(traversal), url_sha256="a" * 64,
            version="0.7.14",
        )
    wheel = _synthetic_wheel()
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="digest mismatch"):
        evidence._wheel_binding(
            wheel_bytes=wheel,
            filename="phase_loop_runtime-0.7.14-py3-none-any.whl",
            digest="0" * 64, url_sha256="a" * 64, version="0.7.14",
        )


@pytest.mark.parametrize("entry_points", [
    b"[console_scripts]\nphase-loop = phase_loop_runtime.cli:main\n",
    b"[console_scripts]\nphase-loop = phase_loop_runtime.cli:run\ncodex-phase-loop = phase_loop_runtime.cli:main\n",
    b"[console_scripts]\nphase-loop = phase_loop_runtime.cli:main\ncodex-phase-loop = phase_loop_runtime.cli:main\nextra = phase_loop_runtime.cli:main\n",
])
def test_wheel_binding_rejects_missing_aliased_or_extra_console_entry_points(entry_points):
    wheel = _synthetic_wheel(members={
        "phase_loop_runtime-0.7.14.dist-info/entry_points.txt": entry_points,
    })
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="console entry points"):
        evidence._wheel_binding(
            wheel_bytes=wheel,
            filename="phase_loop_runtime-0.7.14-py3-none-any.whl",
            digest=evidence._sha256(wheel), url_sha256="a" * 64,
            version="0.7.14",
        )


def test_uv_console_launcher_derivation_matches_actual_uv_install(tmp_path):
    wheel = tmp_path / "phase_loop_runtime-0.7.14-py3-none-any.whl"
    wheel.write_bytes(_synthetic_wheel())
    account_home = tmp_path / "account-home"
    tool_dir = account_home / ".local" / "share" / "uv" / "tools"
    python_dir = account_home / ".local" / "share" / "uv" / "python"
    bin_dir = account_home / ".local" / "bin"
    cache_dir = account_home / ".cache" / "uv"
    tool_dir.mkdir(parents=True)
    python_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    uv_store_authority = evidence._uv_store_authority(
        account_home=account_home, workspace_root=tmp_path / "no-workspace",
    )
    interpreter_authority = evidence._system_interpreter_authority()
    uv = Path(shutil.which("uv") or "uv").resolve(strict=True)
    uv_environment = evidence._uv_environment(
        uv_executable=uv, interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )
    proc = subprocess.run(
        [
            str(uv), "tool", "install", "--no-index",
            "--find-links", str(tmp_path),
            "phase-loop-runtime==0.7.14",
        ],
        env=uv_environment,
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    launcher_environment = tool_dir / "phase-loop-runtime"
    environment_root = launcher_environment.resolve()
    launcher_interpreter = launcher_environment / "bin" / "python"
    interpreter = environment_root / "bin" / "python"
    expected = evidence._uv_console_script_bytes(
        interpreter=launcher_interpreter, target="phase_loop_runtime.cli:main"
    )
    assert (environment_root / "bin" / "phase-loop").read_bytes() == expected
    assert (environment_root / "bin" / "codex-phase-loop").read_bytes() == expected
    uv_probe = tmp_path / "uv-probe"
    uv_probe.write_text("#!/bin/sh\nprintf '%s\\n' \"$UV_TOOL_DIR\"\n")
    uv_probe.chmod(0o700)
    probe_environment = evidence._uv_environment(
        uv_executable=uv_probe, interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )
    installation = evidence._installed_phase_loop_identity(
        uv_executable=uv_probe, interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority, uv_environment=probe_environment,
    )
    assert interpreter.resolve() == Path(interpreter_authority["path"])
    evidence._validate_installed_wheel_binding(
        installation=installation, release=_release_identity(wheel=wheel.read_bytes())
    )


def test_installed_wheel_binding_accepts_normal_uv_registry_layout(tmp_path):
    release, installation, _paths = _installed_wheel_fixture(tmp_path)
    evidence._validate_installed_wheel_binding(
        installation=installation, release=release
    )


def test_installed_wheel_binding_rejects_forged_launcher_with_recomputed_authority(tmp_path):
    release, installation, paths = _installed_wheel_fixture(tmp_path)
    launcher = paths["console"]
    interpreter = Path(installation["environment_root"]) / "bin" / "python"
    launcher.write_bytes(
        f"#!{interpreter}\nimport os\nos.execvp('attacker', ['attacker'])\n".encode()
    )
    record = paths["record"]
    root = Path(installation["distribution_root"])
    relative = os.path.relpath(launcher, root).replace(os.sep, "/")
    rows = list(csv.reader(io.StringIO(record.read_text(), newline="")))
    for row in rows:
        if row[0] == relative:
            data = launcher.read_bytes()
            row[1:] = [_record_hash(data), str(len(data))]
            break
    else:
        raise AssertionError("fixture RECORD lacks phase-loop launcher")
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    record.write_text(output.getvalue())
    installation["console_script_sha256"] = evidence._sha256(launcher.read_bytes())
    installation["record_sha256"] = evidence._sha256(record.read_bytes())
    bootstrap_receipt = _bootstrap_receipt(
        installation=installation,
        dotfiles_repo=tmp_path / "bootstrap-receipt-dotfiles",
    )
    recomputed_proof_digest = evidence._sha256(evidence._canonical_json(
        bootstrap_receipt["bootstrap"]["installation"]
    ))
    assert recomputed_proof_digest == evidence._sha256(evidence._canonical_json(installation))
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="wheel authority"):
        evidence._validate_installed_wheel_binding(
            installation=installation, release=release
        )


def test_installed_wheel_binding_rejects_replaced_interpreter_before_execution(tmp_path):
    release, installation, _paths = _installed_wheel_fixture(tmp_path)
    interpreter = Path(installation["environment_root"]) / "bin" / "python"
    interpreter.unlink()
    sentinel = tmp_path / "untrusted-interpreter-executed"
    interpreter.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
    interpreter.chmod(0o700)
    data = interpreter.read_bytes()
    info = interpreter.stat()
    forged_authority = {
        "schema": "agy_canary_interpreter_authority.v1",
        "selector": "/usr/bin/python3", "path": str(interpreter),
        "dev": info.st_dev, "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode), "uid": 0,
        "size": info.st_size, "sha256": evidence._sha256(data),
    }
    installation["interpreter"] = str(interpreter)
    installation["interpreter_sha256"] = forged_authority["sha256"]
    installation["interpreter_authority"] = forged_authority
    bootstrap_receipt = _bootstrap_receipt(
        installation=installation,
        dotfiles_repo=tmp_path / "bootstrap-receipt-dotfiles",
    )
    recomputed_proof_digest = evidence._sha256(evidence._canonical_json(
        bootstrap_receipt["bootstrap"]["installation"]
    ))
    assert recomputed_proof_digest == evidence._sha256(evidence._canonical_json(installation))
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="authority"):
        evidence._validate_installed_wheel_binding(
            installation=installation, release=release
        )
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "mutation",
    ["content", "missing", "extra", "record_traversal", "console", "release"],
)
def test_installed_wheel_binding_rejects_drift_and_tampering(tmp_path, mutation):
    release, installation, paths = _installed_wheel_fixture(tmp_path)
    package_file = paths["phase_loop_runtime/__init__.py"]
    if mutation == "content":
        package_file.write_bytes(b"mutated\n")
    elif mutation == "missing":
        package_file.unlink()
    elif mutation == "extra":
        extra = package_file.parent / "extra.py"
        extra.write_bytes(b"extra\n")
        installation["package_tree_sha256"] = evidence._runtime_tree_sha256(package_file.parent)
    elif mutation == "record_traversal":
        record = paths["record"]
        record.write_bytes(record.read_bytes() + b"../../../../etc/passwd,sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,1\n")
        installation["record_sha256"] = evidence._sha256(record.read_bytes())
    elif mutation == "console":
        paths["console"].write_bytes(b"mutated launcher\n")
    else:
        release = json.loads(json.dumps(release))
        release["wheel_binding"]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(evidence.AgyCanaryEvidenceError):
        evidence._validate_installed_wheel_binding(
            installation=installation, release=release
        )


@pytest.mark.parametrize("mutate", [
    lambda record: record | {"extra": True},
    lambda record: {key: value for key, value in record.items() if key != "workflow_url"},
    lambda record: record | {"artifacts": record["artifacts"] * 2},
    lambda record: record | {"artifacts": record["artifacts"] + [{
        "filename": "unexpected.zip", "packagetype": "bdist_wheel",
        "url": "https://example.invalid/unexpected", "sha256": "d" * 64,
    }]},
])
def test_release_handoff_parser_rejects_noncanonical_schema_and_duplicate_artifacts(mutate):
    record = {
        "schema": "release_evidence.v1", "version": "0.7.14", "release_commit": "a" * 40,
        "tag_object": "b" * 40, "tag_peel": "a" * 40,
        "release_url": "https://example.invalid/release", "workflow_url": "https://example.invalid/workflow",
        "pypi_metadata_url": "https://pypi.org/pypi/phase-loop-runtime/0.7.14/json",
        "artifacts": [
            {
                "filename": "phase_loop_runtime-0.7.14-py3-none-any.whl",
                "packagetype": "bdist_wheel", "url": "https://example.invalid/wheel",
                "sha256": "c" * 64,
            },
            {
                "filename": "phase_loop_runtime-0.7.14.tar.gz",
                "packagetype": "sdist", "url": "https://example.invalid/sdist",
                "sha256": "d" * 64,
            },
        ],
    }
    bad = mutate(record)
    with pytest.raises(evidence.AgyCanaryEvidenceError):
        evidence._release_handoff_record(b"<!-- release_evidence.v1:start -->" + evidence._canonical_json(bad) + b"<!-- release_evidence.v1:end -->")


def test_release_identity_rejects_any_extra_artifact():
    release = _release_identity()
    release["artifacts"].append({
        "filename": "unexpected.zip", "packagetype": "bdist_wheel",
        "sha256": "1" * 64, "url_sha256": "2" * 64,
    })
    release["artifacts"].sort(key=lambda row: (row["filename"], row["packagetype"]))
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="artifacts"):
        evidence._validate_release_identity(release)
