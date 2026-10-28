from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Callable

import rfc8785

from phase_loop_runtime.executable_dependency_startup import (
    DependencyRequirement,
    ExecutableRequirementIdentity,
)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def mode(path: Path) -> str:
    return f"0{stat.S_IMODE(path.stat(follow_symlinks=False).st_mode):03o}"


def file_identity(path: Path, digest: str | None = None) -> dict[str, Any]:
    observed = path.stat(follow_symlinks=False)
    return {
        "path": str(path),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "uid": observed.st_uid,
        "gid": observed.st_gid,
        "mode": mode(path),
        "nlink": observed.st_nlink,
        "size": observed.st_size,
        "sha256": digest or sha256(path.read_bytes()),
    }


def directory_identity(path: Path) -> dict[str, Any]:
    observed = path.stat(follow_symlinks=False)
    return {
        "path": str(path),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "uid": observed.st_uid,
        "gid": observed.st_gid,
        "mode": mode(path),
    }


@dataclass
class BuiltFixture:
    root: Path
    release: Path
    subject: Path
    helper: Path
    subject_destination: Path
    helper_destination: Path
    declaration_path: Path
    authority_path: Path
    declaration: dict[str, Any]
    authority: dict[str, Any]
    requirement: DependencyRequirement
    authority_bytes: bytes
    authority_fd: int

    def close(self) -> None:
        try:
            os.close(self.authority_fd)
        except OSError:
            pass


def build_fixture(
    root: Path,
    *,
    layout: str = "layout-a",
    provider: str = "synthetic",
    authority_transform: Callable[[dict[str, Any]], bytes | dict[str, Any]] | None = None,
) -> BuiltFixture:
    release = root / ("release-a" if layout == "layout-a" else "versions/v2")
    activation = root / ("admin/a1" if layout == "layout-a" else "alternate-admin/b7")
    subject = release / "bin/tool"
    helper = release / "lib/helper"
    destination_root = Path("/fixture") / sha256(str(root).encode("utf-8"))[:12] / "runtime"
    subject_destination = destination_root / "bin/tool"
    helper_destination = destination_root / "lib/helper"
    subject.parent.mkdir(parents=True, mode=0o755)
    helper.parent.mkdir(parents=True, mode=0o755)
    activation.mkdir(parents=True, mode=0o755)
    for directory in (release, subject.parent, helper.parent, activation):
        directory.chmod(0o755)
    subject.write_bytes(b"tool-v1")
    subject.chmod(0o755)
    helper.write_bytes(b"helper-v1")
    helper.chmod(0o644)
    uid, gid = os.getuid(), os.getgid()
    base_profile = "1" * 64
    exclusions: list[dict[str, str]] = []
    exclusions_sha256 = sha256(rfc8785.dumps(exclusions))
    entries: list[dict[str, Any]] = [
        {
            "source": None,
            "destination": str(subject_destination.parent),
            "kind": "directory",
            "uid": uid,
            "gid": gid,
            "mode": "0755",
            "nlink": None,
            "size": None,
            "sha256": None,
            "link_text": None,
            "target": None,
        },
        {
            "source": None,
            "destination": str(helper_destination.parent),
            "kind": "directory",
            "uid": uid,
            "gid": gid,
            "mode": "0755",
            "nlink": None,
            "size": None,
            "sha256": None,
            "link_text": None,
            "target": None,
        },
        {
            "source": str(helper),
            "destination": str(helper_destination),
            "kind": "file",
            "uid": uid,
            "gid": gid,
            "mode": "0644",
            "nlink": 1,
            "size": helper.stat().st_size,
            "sha256": sha256(helper.read_bytes()),
            "link_text": None,
            "target": None,
        },
    ]
    if layout == "layout-b":
        entries.append(
            {
                "source": None,
                "destination": str(helper_destination.parent / "helper-link"),
                "kind": "symlink",
                "uid": uid,
                "gid": gid,
                "mode": "0777",
                "nlink": 1,
                "size": len("helper"),
                "sha256": None,
                "link_text": "helper",
                "target": str(helper_destination),
            }
        )
    declaration: dict[str, Any] = {
        "schema": "org.agent-harness.executable-dependency-declaration.v1",
        "declaration_id": "0" * 64,
        "adapter": {"id": "synthetic-adapter", "version": "1"},
        "provider": provider,
        "policy": {"id": "synthetic-policy", "version": "1"},
        "subject": {
            "source": str(subject),
            "destination": str(subject_destination),
            "kind": "file",
            "uid": uid,
            "gid": gid,
            "mode": "0755",
            "nlink": 1,
            "size": subject.stat().st_size,
            "sha256": sha256(subject.read_bytes()),
            "forwarding": "original-argv",
        },
        "entries": entries,
        "base_system": {
            "base_profile_sha256": base_profile,
            "exclusions_sha256": exclusions_sha256,
            "exclusions": exclusions,
        },
    }
    unsigned_declaration = dict(declaration)
    unsigned_declaration.pop("declaration_id")
    declaration["declaration_id"] = sha256(rfc8785.dumps(unsigned_declaration))
    declaration_bytes = rfc8785.dumps(declaration)
    declaration_path = activation / "declaration.json"
    declaration_path.write_bytes(declaration_bytes)
    declaration_path.chmod(0o644)

    authority: dict[str, Any] = {
        "schema": "org.agent-harness.executable-dependency-authority.v1",
        "authority_id": "0" * 64,
        "authority_version": 1,
        "adapter": {"id": "synthetic-adapter", "version": "1"},
        "subject": {"provider": provider, "executable": file_identity(subject)},
        "declaration": file_identity(declaration_path),
        "source_roots": [directory_identity(release)],
        "destination_policy": {
            "provider_destination": str(subject_destination),
            "allowed_roots": [str(destination_root)],
        },
        "owner_mode_policy": {
            "allowed_uids": [uid],
            "allowed_gids": [gid],
            "file_modes": ["0644", "0755"],
            "directory_modes": ["0755"],
            "symlink_mode": "0777",
            "single_link_files": True,
        },
        "limits": {
            "authority_bytes": 131_072,
            "declaration_bytes": 16_777_216,
            "entry_count": 1_024,
            "file_bytes": 536_870_912,
            "aggregate_file_bytes": 2_147_483_648,
            "path_bytes": 4_096,
            "link_text_bytes": 4_096,
        },
        "base_profile": {
            "base_profile_sha256": base_profile,
            "exclusions_sha256": exclusions_sha256,
        },
        "provenance": {
            "issuer": "synthetic",
            "upstream_receipt_sha256": "2" * 64,
            "upstream_manifest_sha256": "3" * 64,
            "adapter_evidence_sha256": "4" * 64,
        },
        "activation_nonce": "5" * 64,
    }
    unsigned_authority = dict(authority)
    unsigned_authority.pop("authority_id")
    authority["authority_id"] = sha256(rfc8785.dumps(unsigned_authority))
    authority_bytes: bytes
    if authority_transform is None:
        authority_bytes = rfc8785.dumps(authority)
    else:
        transformed = authority_transform(authority)
        authority_bytes = transformed if isinstance(transformed, bytes) else rfc8785.dumps(transformed)
    authority_path = activation / "authority.json"
    authority_path.write_bytes(authority_bytes)
    authority_path.chmod(0o600)
    requirement = DependencyRequirement(
        provider=provider,
        selected_executable=ExecutableRequirementIdentity(
            path=str(subject),
            kind="file",
            mode="0755",
            size=subject.stat().st_size,
            sha256=sha256(subject.read_bytes()),
        ),
        authority_id=authority["authority_id"],
        expected_authority_sha256=sha256(authority_bytes),
        adapter_id="synthetic-adapter",
        adapter_version="1",
        policy_id="synthetic-policy",
        policy_version="1",
        base_profile_sha256=base_profile,
    )
    return BuiltFixture(
        root=root,
        release=release,
        subject=subject,
        helper=helper,
        subject_destination=subject_destination,
        helper_destination=helper_destination,
        declaration_path=declaration_path,
        authority_path=authority_path,
        declaration=declaration,
        authority=authority,
        requirement=requirement,
        authority_bytes=authority_bytes,
        authority_fd=os.open(authority_path, os.O_RDONLY | os.O_CLOEXEC),
    )
