"""Unregistered one-shot implementation worker boundary.

There is deliberately no host fallback or CLI activation. The caller must supply an
endpoint-owned isolation adapter with immutable runtime executables, protected source
ownership, private HOME/build/tmp, denied ambient imports/config, and confirmed process
quiescence. A process group alone does not implement that contract.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Protocol

from .openshell_artifacts import (
    Bound, Identity, Refused, SourceBundle, canonical, decode, digest, git,
    init_tree, native_witness, scan, stage_files,
)
from .seat_credentials import login_subscription_proven, parse_login_token
from .seat_jail import CLAUDE_TOKEN_FD_ENV, contains_secret, secret_encodings, token_pipe


@dataclass(frozen=True)
class WorkerRequest:
    identity: Identity
    task: str
    tests: tuple[str, ...]
    must_end_within_s: float
    token: bytes = field(repr=False)
    expires_at: float


def _metadata(bundle: SourceBundle, nonce: str, generation: str, image_sha256: str,
              task: str, tests: tuple[str, ...], end_s: float) -> dict:
    if (not isinstance(task, str) or not task or not tests or
            any(not isinstance(t, str) or not t or len(t) > 4096 for t in tests) or
            type(end_s) not in (int, float) or not math.isfinite(end_s) or end_s <= 0):
        raise Refused("request_invalid")
    return {"schema": "openshell.implementation.v1", "base": bundle.base,
            "tree": bundle.tree, "source_sha256": bundle.sha256, "nonce": nonce,
            "generation": generation, "image_sha256": image_sha256,
            "limits_sha256": digest(canonical(asdict(bundle.limits))),
            "task": task, "tests": tests, "must_end_within_s": end_s}


def _identity(metadata: dict) -> Identity:
    return Identity(digest(canonical(metadata)), metadata["base"], metadata["tree"],
                    metadata["source_sha256"], metadata["nonce"], metadata["generation"],
                    digest(metadata["task"].encode()), metadata["image_sha256"],
                    metadata["limits_sha256"])


def seal_request(bundle: SourceBundle, *, nonce: str, generation: str, image_sha256: str,
                 task: str, tests: tuple[str, ...], must_end_within_s: float,
                 login_store: bytes, request_cap: int) -> tuple[Identity, bytes]:
    """Seal from one first-party login snapshot; no override or refresh token route.

    Return bytes exclusively to the one-shot stdin transport, never journal/log/file.
    request_cap is resolved caller policy, not a new configuration default.
    """
    bundle.validate()
    meta = _metadata(bundle, nonce, generation, image_sha256, task, tests, must_end_within_s)
    identity = _identity(meta)
    identity.validate(bundle)
    login = parse_login_token(login_store)
    if (not login_subscription_proven(read_store=lambda: login_store) or login is None or
            login.expires_at is None or not math.isfinite(login.expires_at) or
            login.expires_at - time.time() < must_end_within_s or len(login.token) > 4096):
        raise Refused("finite_subscription_required")
    wire = canonical({"metadata": meta, "identity": asdict(identity),
                      "credential": {"access_token": login.token.decode("ascii"),
                                     "expires_at": login.expires_at}})
    if len(wire) > request_cap:
        raise Refused("request_limit")
    return identity, wire


def read_request(wire: bytes, bundle: SourceBundle, request_cap: int) -> WorkerRequest:
    value = decode(wire, request_cap)
    if set(value) != {"metadata", "identity", "credential"}:
        raise Refused("request_invalid")
    meta, credential = value["metadata"], value["credential"]
    try:
        if not isinstance(meta["tests"], list):
            raise Refused("request_invalid")
        expected = _metadata(bundle, meta["nonce"], meta["generation"], meta["image_sha256"],
                             meta["task"], tuple(meta["tests"]), meta["must_end_within_s"])
        identity = _identity(expected)
        identity.validate(bundle)
        if canonical(meta) != canonical(expected) or canonical(value["identity"]) != canonical(asdict(identity)):
            raise Refused("request_identity_mismatch")
        if set(credential) != {"access_token", "expires_at"}:
            raise Refused("credential_invalid")
        token = credential["access_token"].encode("ascii")
        expires = credential["expires_at"]
        if (not token or len(token) > 4096 or any(c < 0x21 or c > 0x7e for c in token) or
                type(expires) not in (int, float) or not math.isfinite(expires) or
                expires <= time.time()):
            raise Refused("credential_expired")
    except (KeyError, TypeError, AttributeError, UnicodeError):
        raise Refused("request_invalid") from None
    return WorkerRequest(identity, meta["task"], tuple(meta["tests"]),
                         meta["must_end_within_s"], token, expires)


@dataclass(frozen=True)
class Launch:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    stdin: bytes = field(repr=False)
    pass_fds: tuple[int, ...]


@dataclass(frozen=True)
class ProviderResult:
    exit_status: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    quiescent: bool


class IsolatedRuntime(Protocol):
    """Trusted adapter, never instantiated from request/result data.

    Must protect unowned files, deny access to supervisor/artifact state, close all
    inherited descriptors except pass_fds, enforce Bound inside its isolation unit,
    and return only after provider descendants stop. Tests are trusted-plan IDs,
    not shell strings. Tests run without the credential in the same isolated unit.
    No production adapter is supplied or qualified by this module.
    """
    provider_program: tuple[str, ...]

    def provider(self, launch: Launch, bound: Bound, cap: int) -> ProviderResult: ...

    def test(self, work: Path, home: Path, tests: tuple[str, ...],
             bound: Bound, cap: int) -> bool: ...


def run_worker(wire: bytes, bundle: SourceBundle, *, expected_identity: Identity, request_cap: int,
               runtime: IsolatedRuntime | None, scratch_parent: Path,
               cancelled) -> bytes:
    """Consume once, edit/test, and return bounded UNTRUSTED binary-safe evidence.

    scratch_parent must be runtime-owned and outside every user checkout. Actual
    source publication before EXEC is the server's responsibility, not this API.
    """
    start = time.monotonic()
    request = read_request(wire, bundle, request_cap)
    if request.identity != expected_identity:
        raise Refused("committed_identity_mismatch")
    if runtime is None:
        raise Refused("isolation_adapter_unavailable")
    bound = Bound(min(start + request.must_end_within_s,
                      time.monotonic() + request.expires_at - time.time()), cancelled)
    bound.check()
    cap = bundle.limits.output_bytes
    with tempfile.TemporaryDirectory(prefix="implementation-", dir=scratch_parent) as temp:
        private = Path(temp)
        work, home = private / "work", private / "home"
        home.mkdir(mode=0o700)
        init_tree(work, bundle, bound)
        # Keep Git metadata out of provider-visible work. The adapter must deny
        # access to the supervisor's sibling directories, not merely change cwd.
        metadata = private / "git-metadata"
        (work / ".git").rename(metadata)
        bound.check()
        fd = token_pipe(request.token)
        try:
            env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                   CLAUDE_TOKEN_FD_ENV: str(fd)}
            argv = (*runtime.provider_program, "-p", "--verbose", "--output-format", "stream-json",
                    "--setting-sources", "", "--strict-mcp-config", "--mcp-config",
                    '{"mcpServers":{}}', "--no-session-persistence")
            if not argv or not Path(argv[0]).is_absolute():
                raise Refused("runtime_program_invalid")
            result = runtime.provider(Launch(argv, work, env, request.task.encode(), (fd,)), bound, cap)
        finally:
            os.close(fd)
        bound.check()
        if (result.quiescent is not True or type(result.exit_status) is not int or result.exit_status != 0 or
                len(result.stdout) + len(result.stderr) > cap):
            raise Refused("provider_incomplete")
        native = result.stdout
        for encoding in secret_encodings(request.token):
            native = native.replace(encoding, b"[REDACTED]")
        native_witness(native)
        # Provider stderr is discarded, never persisted or emitted. Reject secret
        # bytes/known encodings in artifacts instead of corrupting a binary patch.
        if runtime.test(work, home, request.tests, bound, cap) is not True:
            raise Refused("tests_failed")
        bound.check()
        if (work / ".git").exists() or (work / ".git").is_symlink():
            raise Refused("metadata_modified")
        after = scan(work, bundle.limits, bound)
        SourceBundle(bundle.base, bundle.tree, after, bundle.owned_paths, bundle.limits).validate()
        before_map, after_map = ({f.path: f for f in entries} for entries in (bundle.files, after))
        for path in before_map.keys() | after_map.keys():
            if before_map.get(path) != after_map.get(path) and path not in bundle.owned_paths:
                raise Refused("ownership_escape")
        if any(contains_secret(f.data, request.token) for f in after):
            raise Refused("credential_in_artifact")
        # Rebuild from the immutable bundle in another disposable tree. Never run
        # Git against metadata the provider could have written.
        diff_root = private / "diff"
        init_tree(diff_root, bundle, bound)
        stage_files(diff_root, after, bundle.limits, bound)
        patch = git(diff_root, "diff", "--cached", "--binary", "--full-index", "--no-ext-diff",
                    "--no-textconv", "--no-renames", bundle.tree, "--", bound=bound,
                    cap=bundle.limits.patch_bytes)
        if contains_secret(patch, request.token):
            raise Refused("credential_in_artifact")
        envelope = canonical({"identity": asdict(request.identity),
                              "patch": base64.b64encode(patch).decode(),
                              "patch_sha256": digest(patch), "patch_size": len(patch),
                              "native": base64.b64encode(native).decode(),
                              "native_sha256": digest(native), "test_claim": "passed",
                              "truncated": False, "exit_status": 0})
        if len(envelope) > cap or contains_secret(envelope, request.token):
            raise Refused("result_limit_or_secret")
        bound.check()
        return envelope
