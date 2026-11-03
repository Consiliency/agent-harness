"""Unregistered one-shot implementation worker boundary.

There is deliberately no host fallback or CLI activation. The caller must supply an
endpoint-owned isolation adapter with immutable runtime executables, protected source
ownership, private HOME/build/tmp, denied ambient imports/config, and confirmed process
quiescence. The guest entry loads once and uses the shared inner Landlock helper;
without a qualified runtime adapter it refuses after restriction. A process group alone does not implement that contract.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import json
from importlib.resources import files
import math
import re
import stat
import struct
import subprocess
import sys
import os
from pathlib import Path
import tempfile
import time
from typing import Protocol

import rfc8785

from .openshell_artifacts import (
    Bound, Identity, Refused, SourceBundle, canonical, decode, digest, git,
    init_tree, native_witness, scan, stage_files, run_process, Limits, SourceFile,
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
    if any(not isinstance(x, str) for x in (nonce, generation, image_sha256)):
        raise Refused("identity_invalid")
    if (not isinstance(task, str) or not task or not tests or
            any(not isinstance(t, str) or not t or len(t) > 4096 for t in tests) or
            type(end_s) not in (int, float) or not math.isfinite(end_s) or end_s <= 0):
        raise Refused("request_invalid")
    return {"schema": "openshell.implementation.v1", "base": bundle.base,
            "tree": bundle.tree, "source_sha256": bundle.sha256, "nonce": nonce,
            "generation": generation, "image_sha256": image_sha256,
            "limits_sha256": digest(canonical(asdict(bundle.limits))),
            "task": task, "tests": tests, "must_end_within_s": end_s,
            "load_sha256": digest(canonical(load_document(bundle, nonce)))}


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
                      "load": load_document(bundle, nonce),
                      "credential": {"access_token": login.token.decode("ascii"),
                                     "expires_at": login.expires_at}})
    if len(wire) > min(request_cap, STOCK_STDIN_LIMIT):
        raise Refused("request_limit")
    return identity, wire


def read_request(wire: bytes, bundle: SourceBundle, request_cap: int) -> WorkerRequest:
    value = decode(wire, min(request_cap, STOCK_STDIN_LIMIT))
    if set(value) != {"metadata", "identity", "credential", "load"}:
        raise Refused("request_invalid")
    meta, credential = value["metadata"], value["credential"]
    try:
        if not isinstance(meta["tests"], list):
            raise Refused("request_invalid")
        expected = _metadata(bundle, meta["nonce"], meta["generation"], meta["image_sha256"],
                             meta["task"], tuple(meta["tests"]), meta["must_end_within_s"])
        validate_load(value["load"], bundle, meta["nonce"])
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
    remote callers must enter through load_restrict_exec before this adapter seam.
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


# Stock v0.1.4 proto/sandbox.proto, NVIDIA/OpenShell 5a7728c304b5528e954e9ae900cf21f84e1a12b1.
# Field/type inventory only; policy documents are always consumed from the contract vectors.
_POLICY_FIELDS = {'SandboxPolicy': {'version': 'uint32',
                   'filesystem': 'FilesystemPolicy',
                   'landlock': 'LandlockPolicy',
                   'process': 'ProcessPolicy',
                   'network_policies': 'map<string, NetworkPolicyRule>',
                   'network_middlewares': 'map<string, NetworkMiddlewareConfig>'},
 'FilesystemPolicy': {'include_workdir': 'bool', 'read_only': '[]string', 'read_write': '[]string'},
 'LandlockPolicy': {'compatibility': 'string'},
 'ProcessPolicy': {'run_as_user': 'string', 'run_as_group': 'string'},
 'NetworkPolicyRule': {'name': 'string',
                       'endpoints': '[]NetworkEndpoint',
                       'binaries': '[]NetworkBinary'},
 'NetworkEndpoint': {'host': 'string',
                     'port': 'uint32',
                     'protocol': 'string',
                     'tls': 'NetworkTlsMode',
                     'enforcement': 'NetworkEnforcementMode',
                     'access': 'NetworkAccessPreset',
                     'rules': '[]L7Rule',
                     'allowed_ips': '[]string',
                     'ports': '[]uint32',
                     'deny_rules': '[]L7DenyRule',
                     'allow_encoded_slash': 'bool',
                     'persisted_queries': 'string',
                     'graphql_persisted_queries': 'map<string, GraphqlOperation>',
                     'graphql_max_body_bytes': 'uint32',
                     'path': 'string',
                     'websocket_credential_rewrite': 'bool',
                     'request_body_credential_rewrite': 'bool',
                     'advisor_proposed': 'bool',
                     'credential_signing': 'string',
                     'signing_service': 'string',
                     'signing_region': 'string',
                     'json_rpc_max_body_bytes': 'uint32',
                     'mcp': 'McpOptions',
                     'credential_binding': 'NetworkCredentialBinding',
                     'allow_uninspected_credentials': 'bool',
                     'provider_credentialed': 'bool',
                     'token_grant_owner': 'string'},
 'L7Rule': {'allow': 'L7Allow'},
 'L7Allow': {'method': 'string',
             'path': 'string',
             'command': 'string',
             'query': 'map<string, L7QueryMatcher>',
             'operation_type': 'string',
             'operation_name': 'string',
             'fields': '[]string',
             'params': 'map<string, L7QueryMatcher>'},
 'L7QueryMatcher': {'glob': 'string', 'any': '[]string'},
 'L7DenyRule': {'method': 'string',
                'path': 'string',
                'command': 'string',
                'query': 'map<string, L7QueryMatcher>',
                'operation_type': 'string',
                'operation_name': 'string',
                'fields': '[]string',
                'params': 'map<string, L7QueryMatcher>'},
 'GraphqlOperation': {'operation_type': 'string', 'operation_name': 'string', 'fields': '[]string'},
 'McpOptions': {'strict_tool_names': 'bool',
                'allow_all_known_mcp_methods': 'bool',
                'versions': '[]string'},
 'NetworkCredentialBinding': {'provider': 'string'},
 'NetworkBinary': {'path': 'string'},
 'NetworkMiddlewareConfig': {'name': 'string',
                             'middleware': 'string',
                             'config': 'google.protobuf.Struct',
                             'on_error': 'string',
                             'endpoints': 'MiddlewareEndpointSelector',
                             'order': 'int32'},
 'MiddlewareEndpointSelector': {'include': '[]string', 'exclude': '[]string'}}
_POLICY_ENUMS = {'NetworkTlsMode': {'NETWORK_TLS_MODE_UNSPECIFIED': 0,
                    'NETWORK_TLS_MODE_SKIP': 1,
                    'NETWORK_TLS_MODE_TERMINATE': 2,
                    'NETWORK_TLS_MODE_PASSTHROUGH': 3},
 'NetworkEnforcementMode': {'NETWORK_ENFORCEMENT_MODE_UNSPECIFIED': 0,
                            'NETWORK_ENFORCEMENT_MODE_ENFORCE': 1,
                            'NETWORK_ENFORCEMENT_MODE_AUDIT': 2},
 'NetworkAccessPreset': {'NETWORK_ACCESS_PRESET_UNSPECIFIED': 0,
                         'NETWORK_ACCESS_PRESET_READ_ONLY': 1,
                         'NETWORK_ACCESS_PRESET_READ_WRITE': 2,
                         'NETWORK_ACCESS_PRESET_FULL': 3},
 'SettingScope': {'SETTING_SCOPE_UNSPECIFIED': 0,
                  'SETTING_SCOPE_SANDBOX': 1,
                  'SETTING_SCOPE_GLOBAL': 2},
 'PolicySource': {'POLICY_SOURCE_UNSPECIFIED': 0,
                  'POLICY_SOURCE_SANDBOX': 1,
                  'POLICY_SOURCE_GLOBAL': 2}}
# Digest of the checked-in full-remote-pi-runner vector, never a locally authored policy.
REVIEW_POLICY_DIGEST = "sha256:767400727c35828c350a7adaa01a8eed40e14bdc86fd934812910872a935ec2c"
STOCK_MESSAGE_LIMIT = 4 * 1024 * 1024
# Leave room for stock routing, request_id, argv and timeout fields. No streaming spill.
STOCK_STDIN_LIMIT = STOCK_MESSAGE_LIMIT - 16384
HELPER = "/usr/libexec/agent-toolkit/landlock-exec"
HELPER_SHA256 = "775d4f7af61dff58e5094eeac56fcda2fdb7e56d3f05fbf008b1caf1f84500aa"


def review_policy():
    vectors = json.loads((files("phase_loop_runtime") /
        "contracts/placement/vectors/policies.json").read_text())
    return next(v for v in vectors["valid"] if v["name"] == "full-remote-pi-runner")


def stock_policy_digest(policy):
    """Strict proto field names, preserving arbitrary user map/Struct keys verbatim."""
    def check(value, typ):
        if typ.startswith("[]"):
            if not isinstance(value, list):
                raise Refused("stock_policy_invalid")
            for item in value:
                check(item, typ[2:])
        elif typ.startswith("map<"):
            if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
                raise Refused("stock_policy_invalid")
            for item in value.values():
                check(item, typ.split(",")[1].strip(" >"))
        elif typ in _POLICY_FIELDS:
            if not isinstance(value, dict) or not set(value) <= _POLICY_FIELDS[typ].keys():
                raise Refused("stock_policy_field")
            for key, item in value.items():
                check(item, _POLICY_FIELDS[typ][key])
        elif typ == "google.protobuf.Struct":
            if not isinstance(value, dict):
                raise Refused("stock_policy_invalid")
            rfc8785.dumps(value)
        elif typ == "string":
            if not isinstance(value, str):
                raise Refused("stock_policy_invalid")
        elif typ == "bool":
            if type(value) is not bool:
                raise Refused("stock_policy_invalid")
        elif typ in ("uint32", "int32"):
            low, high = (0, 2**32-1) if typ == "uint32" else (-2**31, 2**31-1)
            if type(value) not in (int, float) or not low <= value <= high or int(value) != value:
                raise Refused("stock_policy_invalid")
        elif typ in _POLICY_ENUMS:
            if not ((isinstance(value, str) and value in _POLICY_ENUMS[typ]) or
                    (type(value) is int and value in _POLICY_ENUMS[typ].values())):
                raise Refused("stock_policy_invalid")
        else:
            raise Refused("stock_policy_invalid")
    try:
        check(policy, "SandboxPolicy")
        if policy.get("landlock", {}).get("compatibility") != "hard_requirement":
            raise Refused("landlock_required")
        return "sha256:" + digest(rfc8785.dumps(policy))
    except (ValueError, TypeError, OverflowError) as error:
        if isinstance(error, Refused):
            raise
        raise Refused("stock_policy_invalid") from None


def landlock_manifest(rules, uid=10001, gid=10001):
    """Version 1 shared binary manifest; the pinned helper rechecks filesystem invariants."""
    if any(type(x) is not int or not 0 < x <= 0xfffffffe for x in (uid, gid)):
        raise Refused("manifest_root_id")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 512:
        raise Refused("manifest_count")
    checked = []
    for rule in rules:
        try:
            path, role, kind = rule["path"], rule["role"], rule["type"]
            raw = path.encode("utf-8")
            follow = rule.get("follow", False)
            if (not 2 <= len(raw) <= 4095 or not path.startswith("/") or
                    any(x in ("", ".", "..") for x in path[1:].split("/")) or "\0" in path):
                raise Refused("manifest_path")
            if role not in ("ro", "rw", "dev") or kind not in ("dir", "file", "char"):
                raise Refused("manifest_type")
            if (type(follow) is not bool or follow and (role, kind) != ("ro", "dir") or
                    (role == "dev") != (kind == "char") or role == "dev" and not path.startswith("/dev/")):
                raise Refused("manifest_type")
            checked.append((raw, role, kind, follow))
        except (KeyError, TypeError, AttributeError, UnicodeError):
            raise Refused("manifest_invalid") from None
    checked.sort()
    if len({r[0] for r in checked}) != len(checked):
        raise Refused("manifest_order")
    for path, role, kind, _ in checked:
        if role == "rw" and kind == "dir" and any(
                r == "ro" and (p == path or p.startswith(path + b"/")) for p, r, _, _ in checked):
            raise Refused("manifest_overlap")
    wire = struct.pack("<8sIIII", b"LLEXEC01", 1, uid, gid, len(checked))
    for path, role, kind, follow in checked:
        wire += struct.pack("<BBBBI", {"ro": 1, "rw": 2, "dev": 3}[role],
                            {"dir": 1, "file": 2, "char": 3}[kind], int(follow), 0, len(path)) + path
    if len(wire) > 1048576:
        raise Refused("manifest_size")
    return wire


def load_document(bundle, run_id):
    bundle.validate()
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", run_id):
        raise Refused("load_mapping_invalid")
    root = "/work/" + run_id
    return {"version": 1, "source": bundle.manifest, "source_sha256": bundle.sha256,
            "guest": {"input": root + "/input", "output": root + "/output", "scratch": root + "/scratch"},
            "projections": [], "content": [base64.b64encode(f.data).decode("ascii") for f in bundle.files]}


def validate_load(value, bundle, run_id):
    if canonical(value) != canonical(load_document(bundle, run_id)):
        raise Refused("load_digest_mismatch")


def preflight_worker(bundle, create, *, task, tests, deadline_s, request_cap, generation,
                     dependency_required=False, exec_request=None):
    """Pure validation; no credentials, filesystem writes, journal or remote effects.

    Dependency context is resolved by the caller on its originating task thread.
    A conservative maximum credential/metadata envelope is checked before reserve.
    """
    if dependency_required:
        raise Refused("dependency_route_unwired")
    if not isinstance(create, dict) or not {"policy", "policy_digest"} <= create.keys():
        raise Refused("stock_policy_invalid")
    policy_digest = stock_policy_digest(create["policy"])
    if create["policy_digest"] != policy_digest:
        raise Refused("policy_digest_mismatch")
    if policy_digest != REVIEW_POLICY_DIGEST:
        raise Refused("review_policy_mismatch")
    meta = _metadata(bundle, "f" * 64, generation, "f" * 64, task, tests, deadline_s)
    meta["load_sha256"] = digest(canonical(load_document(bundle, "f" * 64)))
    candidate = canonical({"metadata": meta, "identity": asdict(_identity(meta)),
        "credential": {"access_token": "\\" * 4096, "expires_at": 1.7976931348623157e308},
        "load": load_document(bundle, "f" * 64)})
    if type(request_cap) is not int or not 0 < len(candidate) <= min(request_cap, STOCK_STDIN_LIMIT):
        raise Refused("request_limit")
    if exec_request is not None:
        message = exec_request(candidate, deadline_s)
        # The stock channel adds these bounded routing fields before its one call.
        message.sandbox = "f" * 36
        message.request_id = "f" * 36
        if message.stdin != candidate or message.ByteSize() > STOCK_MESSAGE_LIMIT:
            raise Refused("exec_input_limit")
    return policy_digest


def guest_rules(mapping):
    rules = [{"path": p, "role": "ro", "type": "dir", "follow": p == "/lib"}
             for p in ("/etc", "/lib", "/proc", "/usr", "/var/log")]
    rules += [{"path": "/dev/urandom", "role": "ro", "type": "char"}]
    # Character devices use the helper's device role (never ordinary file grants).
    rules[-1]["role"] = "dev"
    rules += [{"path": "/dev/null", "role": "dev", "type": "char"}]
    rules += [{"path": p, "role": "ro" if key == "input" else "rw", "type": "dir"}
              for key, p in mapping.items()]
    return rules


def verify_helper_metadata():
    helper = Path(HELPER)
    row = helper.lstat()
    if (not stat.S_ISREG(row.st_mode) or row.st_uid != 0 or row.st_gid != 0 or
            stat.S_IMODE(row.st_mode) != 0o755):
        raise Refused("landlock_helper_invalid")
    for parent in helper.parents:
        row = parent.lstat()
        if (not stat.S_ISDIR(row.st_mode) or row.st_uid != 0 or row.st_mode & 0o022 or
                parent == helper.parent and stat.S_IMODE(row.st_mode) != 0o755):
            raise Refused("landlock_helper_invalid")


def _guest_execute(argv, *, bound, input=b"", capture_output=True, timeout, check=False):
    code, out, err = run_process(tuple(argv), cwd=Path("/work"), env={}, data=input,
                                 cap=STOCK_MESSAGE_LIMIT, bound=bound)
    return subprocess.CompletedProcess(argv, code, out, err)


def load_restrict_exec(wire, bundle, *, request_cap, bound, execute=None,
                       restricted_argv=None, reclaims=()):
    """Guest bootstrap. The only workload launch is through the pinned helper.

    execute is an offline test seam. It must synchronously drain stdin and join the
    helper's process tree within bound; production remains unregistered.
    The helper closes token fds, so the restricted worker receives credentials only
    through stdin and creates its provider token pipe after restriction.
    """
    if execute is None:
        def execute(argv, **kwargs):
            return _guest_execute(argv, bound=bound, **kwargs)
    read_request(wire, bundle, request_cap)
    value = decode(wire, min(request_cap, STOCK_STDIN_LIMIT))
    bound.check()
    if (any(get_id() != 10001 for get_id in (os.getuid, os.geteuid, os.getgid, os.getegid)) or
            digest(Path(HELPER).read_bytes()) != HELPER_SHA256):
        raise Refused("landlock_helper_invalid")
    verify_helper_metadata()
    probe = execute((HELPER, "--probe"), capture_output=True, timeout=bound.check(), check=False)
    match = re.fullmatch(rb"landlock-exec: abi ([3-8]) supported fs=0x(7fff|ffff)\n", probe.stdout)
    if (probe.returncode != 0 or not match or
            int(match[2], 16) != (0x7fff if int(match[1]) < 5 else 0xffff)):
        raise Refused("landlock_abi_unsupported")
    mapping = value["load"]["guest"]
    parent = Path(mapping["input"]).parent
    # Exclusive creation refuses replay, symlinks, or a previous partial transfer.
    parent.mkdir(mode=0o700)
    for path in mapping.values():
        Path(path).mkdir(mode=0o700)
    for entry in bundle.files:
        bound.check()
        target = Path(mapping["input"]) / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(entry.data)
        target.chmod(entry.mode & 0o777)
    # Re-read loaded bytes before publishing the restriction manifest.
    if scan(Path(mapping["input"]), bundle.limits, bound) != bundle.files:
        raise Refused("load_digest_mismatch")
    manifest = landlock_manifest(guest_rules(mapping))
    policy_path = parent / "landlock.bin"
    with policy_path.open("xb") as stream:
        stream.write(manifest)
    bound.check()
    argv = restricted_argv or (sys.executable, "-I", "-m", "phase_loop_runtime.openshell_worker", "--restricted")
    if not argv or not Path(argv[0]).is_absolute():
        raise Refused("runtime_program_invalid")
    result = execute((HELPER, "--policy", str(policy_path), "--", *argv),
                     input=wire, capture_output=True, timeout=bound.check(), check=False)
    return result, {"read_only_enforced_by": "client-landlock",
                    "policy_digest": stock_policy_digest(review_policy()["policy"]),
                    "restricted_roots": [mapping["input"]], "guest_mapping": mapping,
                    "load_sha256": digest(canonical(value["load"])),
                    "landlock_manifest_sha256": digest(manifest),
                    "exec_claimed": True, "exec_claim_attested_by": "client",
                    "reclaims": list(reclaims)}


def bundle_from_envelope(wire, cap):
    value = decode(wire, min(cap, STOCK_STDIN_LIMIT))
    try:
        source = value["load"]["source"]
        content = value["load"]["content"]
        if len(content) != len(source["files"]):
            raise Refused("load_digest_mismatch")
        entries = tuple(SourceFile(row["path"], row["mode"], base64.b64decode(data, validate=True))
                        for row, data in zip(source["files"], content, strict=True))
        bundle = SourceBundle(source["base"], source["tree"], entries,
                              tuple(source["owned_paths"]), Limits(**source["limits"]))
        bundle.validate()
        read_request(wire, bundle, cap)
        return bundle
    except (KeyError, TypeError, ValueError):
        raise Refused("load_digest_mismatch") from None


def main():
    """Image entry point, closed until a trusted runtime adapter is installed.

    The model runtime cannot be selected over the wire. A qualified image installs
    its runtime adapter at this source boundary; no arbitrary import or command
    from an envelope is used. An unavailable adapter exits 126, never falls back.
    """
    try:
        wire = sys.stdin.buffer.read(STOCK_STDIN_LIMIT + 1)
        bundle = bundle_from_envelope(wire, STOCK_STDIN_LIMIT)
        request = read_request(wire, bundle, STOCK_STDIN_LIMIT)
        if sys.argv[1:] == ["--restricted"]:
            # Runtime-reported evidence is not a host attestation. This entry is
            # reached through the helper, with credentials still only on stdin.
            if not re.fullmatch(r"1:abi=[3-8]:fs=0x(?:7fff|ffff)",
                                os.environ.get("AGENT_TOOLKIT_LANDLOCK", "")):
                raise Refused("landlock_evidence_missing")
            raise Refused("isolation_adapter_unavailable")
        if sys.argv[1:]:
            raise Refused("worker_arguments_invalid")
        result, _ = load_restrict_exec(wire, bundle, request_cap=STOCK_STDIN_LIMIT,
            bound=Bound(time.monotonic() + min(request.must_end_within_s,
                                               request.expires_at - time.time()), lambda: False))
        if result.returncode == 0:
            sys.stdout.buffer.write(result.stdout)
        elif result.stderr == b"worker refused: isolation_adapter_unavailable\n":
            raise Refused("isolation_adapter_unavailable")
        return result.returncode
    except Refused as error:
        sys.stderr.write("worker refused: " + str(error) + "\n")
        return 126
    except (OSError, subprocess.SubprocessError):
        sys.stderr.write("worker refused: guest_bootstrap_failed\n")
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
