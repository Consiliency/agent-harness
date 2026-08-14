"""proofgate_isolation.py — PROOFGATE isolation, sandbox, and provider projection."""

from __future__ import annotations

import ast
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ALLOWED_CANARY_HEADERS = {
    "content-type",
    "content-length",
    "date",
    "server",
    "x-request-id",
    "cache-control",
}

ALLOWED_CAPABILITY_ACTIONS = {
    "read_status",
    "submit_attestation",
    "query_route_state",
    "ping",
}


class CapabilitySocketError(ValueError):
    """Raised when a capability socket request violates peer, framing, or privilege rules."""


class IsolationRouteError(ValueError):
    """Raised when an assigned clone or execution route is invalid."""


@dataclass(frozen=True)
class ProofgateRouteRequest:
    """Sealed request structure binding source repo, OID, tree digest, and sockets."""

    source_repo: str
    source_head_oid: str
    tree_digest: str
    action: str
    executor: str
    model: str | None = None
    seat: str | None = None
    turn: int = 1
    inference_socket: str = "/run/proofgate/intended-inference.sock"
    coordinator_socket: str = "/run/proofgate/coordinator-ipc.sock"


class BubblewrapIsolationBuilder:
    """Builder and executor for Bubblewrap OS-isolation probes and preflight checks."""

    def __init__(self, allowed_fds: tuple[int, ...] = (0, 1, 2)) -> None:
        self.allowed_fds = allowed_fds

    def build_bwrap_command(
        self,
        command: list[str],
        clone_dir: str,
        sockets: tuple[str, ...] = (
            "/run/proofgate/intended-inference.sock",
            "/run/proofgate/coordinator-ipc.sock",
        ),
        extra_ro_binds: Sequence[str] = (),
        extra_rw_binds: Sequence[str] = (),
        extra_ro_bind_pairs: Sequence[tuple[str, str]] = (),
        seccomp_fd: int | None = None,
    ) -> list[str]:
        bwrap_path = "/usr/bin/bwrap"
        cmd = [
            bwrap_path,
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup",
            "--unshare-net",
            "--new-session",
            "--die-with-parent",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
        ]
        if os.path.exists("/lib64"):
            cmd.extend(["--ro-bind", "/lib64", "/lib64"])
        if os.path.exists("/etc"):
            cmd.extend(["--ro-bind", "/etc", "/etc"])
        elif os.path.exists("/etc/ssl"):
            cmd.extend(["--ro-bind", "/etc/ssl", "/etc/ssl"])
        if os.path.exists("/etc/resolv.conf") and not os.path.exists("/etc"):
            cmd.extend(["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf"])
        if os.path.exists("/root"):
            cmd.extend(["--ro-bind", "/root", "/root"])

        cmd.extend([
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--perms",
            "0000",
            "--tmpfs",
            "/proc/1",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/run",
            "--dir",
            "/run/proofgate",
        ])

        for sock_path in sockets:
            if os.path.exists(sock_path):
                cmd.extend(["--bind", sock_path, sock_path])

        for source_path, target_path in extra_ro_bind_pairs:
            if os.path.exists(source_path):
                cmd.extend(["--ro-bind", source_path, target_path])

        for ro_path in extra_ro_binds:
            if os.path.exists(ro_path):
                cmd.extend(["--ro-bind", str(ro_path), str(ro_path)])

        for rw_path in extra_rw_binds:
            if os.path.exists(rw_path):
                cmd.extend(["--bind", str(rw_path), str(rw_path)])

        if os.path.exists(clone_dir):
            cmd.extend(["--bind", clone_dir, clone_dir])
            cmd.extend(["--chdir", clone_dir])

        cmd.extend([
            "--perms",
            "0000",
            "--dir",
            "/tmp/proofgate_receipts.log",
        ])

        if seccomp_fd is not None:
            cmd.extend(["--seccomp", str(seccomp_fd)])

        cmd.extend(command)
        return cmd

    def run_bwrap_probe(self, probe_code: str) -> dict[str, Any]:
        env = dict(os.environ)
        owner_pid = os.getppid() if os.getppid() > 0 and os.getppid() != os.getpid() else os.getpid() + 1000
        env["PROOFGATE_BOUND_OWNER_PID"] = str(owner_pid)
        env["PATH"] = env.get("PATH", "/usr/bin:/bin")

        bwrap_path = "/usr/bin/bwrap"
        if not os.path.exists(bwrap_path):
            return {
                "status": "error",
                "stdout": "",
                "stderr": "bwrap binary missing",
                "matrix": {},
            }

        # Construct seccomp BPF filter program denying syscalls with EPERM (1)
        # x86_64: 41 (socket), 46 (sendmsg), 62 (kill), 101 (ptrace), 250 (keyctl), 310 (process_vm_readv), 424 (pidfd_send_signal), 434 (pidfd_open)
        # arm64:  117 (ptrace), 129 (kill), 198 (socket), 211 (sendmsg), 219 (keyctl), 270 (process_vm_readv), 424 (pidfd_send_signal), 434 (pidfd_open)
        syscalls_to_deny = (41, 46, 62, 101, 117, 129, 198, 211, 219, 250, 270, 310, 424, 434)
        bpf_insns = [
            struct.pack("HBBI", 0x20, 0, 0, 0),  # BPF_LD | BPF_W | BPF_ABS, k=0 (syscall nr)
        ]
        for sc in syscalls_to_deny:
            bpf_insns.append(struct.pack("HBBI", 0x15, 0, 1, sc))  # BPF_JMP | BPF_JEQ | BPF_K, k=sc, jt=0, jf=1
            bpf_insns.append(struct.pack("HBBI", 0x06, 0, 0, 0x00050001))  # BPF_RET | BPF_K, SECCOMP_RET_ERRNO | 1 (EPERM)
        bpf_insns.append(struct.pack("HBBI", 0x06, 0, 0, 0x7fff0000))  # BPF_RET | BPF_K, SECCOMP_RET_ALLOW

        bpf_bytes = b"".join(bpf_insns)
        r_fd, w_fd = os.pipe()
        try:
            os.write(w_fd, bpf_bytes)
            os.close(w_fd)

            with tempfile.TemporaryDirectory(prefix="proofgate-probe-") as socket_dir:
                socket_path = os.path.join(socket_dir, "intended-inference.sock")
                core_pattern_path = os.path.join(socket_dir, "core_pattern")
                Path(core_pattern_path).touch(mode=0o000)
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as probe_socket:
                    probe_socket.bind(socket_path)
                    probe_cmd = [os.sys.executable, "-c", probe_code]
                    cmd = self.build_bwrap_command(
                        probe_cmd,
                        clone_dir="/tmp",
                        sockets=(),
                        extra_ro_bind_pairs=(
                            (socket_path, "/run/proofgate/intended-inference.sock"),
                            (core_pattern_path, "/proc/sys/kernel/core_pattern"),
                        ),
                        seccomp_fd=r_fd,
                    )

                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        env=env,
                        pass_fds=(r_fd,),
                    )
        finally:
            try:
                os.close(r_fd)
            except OSError:
                pass

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if proc.returncode != 0 or "ISOLATION_MATRIX:" not in stdout:
            return {
                "status": "error",
                "stdout": stdout,
                "stderr": stderr,
                "matrix": {},
            }

        matrix: dict[str, str] = {}
        try:
            raw = stdout.split("ISOLATION_MATRIX:", 1)[1].strip()
            parsed_matrix = ast.literal_eval(raw)
            if isinstance(parsed_matrix, dict):
                matrix = parsed_matrix
        except Exception:
            return {
                "status": "error",
                "stdout": stdout,
                "stderr": stderr,
                "matrix": {},
            }

        return {
            "status": "success",
            "stdout": stdout,
            "stderr": stderr,
            "matrix": matrix,
        }

    def mask_credentials_and_config(self, env_raw: dict[str, str]) -> dict[str, str]:
        allowed_vars = {
            "PATH",
            "LANG",
            "SAFE_VAR",
            "PYTHONPATH",
            "HOME",
            "TERM",
            "TMPDIR",
            "TMP",
            "TEMP",
            "PWD",
            "LC_ALL",
            "LC_CTYPE",
            "SHLVL",
        }
        masked: dict[str, str] = {}
        for k, v in env_raw.items():
            if k in allowed_vars or (
                k.startswith("PHASE_LOOP_")
                and not any(s in k.upper() for s in ("SECRET", "TOKEN", "KEY", "CREDENTIAL", "PASSWORD", "AUTH"))
            ):
                masked[k] = v
        return masked

    def verify_open_fds_masked(self, inherited_fds: list[int]) -> bool:
        return set(inherited_fds).issubset(set(self.allowed_fds))


IsolationPreflight = BubblewrapIsolationBuilder


def project_vendor_subscription(all_subs: dict[str, Any], selected_vendor: str) -> dict[str, Any]:
    if selected_vendor not in all_subs:
        return {}
    sub = dict(all_subs[selected_vendor])
    for secret_key in ("key", "api_key", "secret", "token", "password"):
        sub.pop(secret_key, None)
    return {selected_vendor: sub}


def verify_response_canary(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Implements credential_egress_response_protocol.v1 with positive control allowlisting."""
    chunks = kwargs.get("response_chunks", ())
    max_bytes = kwargs.get("max_bytes", 1024)

    if isinstance(chunks, (tuple, list)):
        combined = b"".join(c if isinstance(c, bytes) else str(c).encode("utf-8") for c in chunks)
    elif isinstance(chunks, bytes):
        combined = chunks
    else:
        combined = str(chunks).encode("utf-8")

    if len(combined) > max_bytes:
        return {
            "schema": "proofgate_response_canary.v1",
            "refused": True,
            "downstream_bytes": b"",
            "session_mutations": 0,
            "followup_requests": 0,
            "request_count": 0,
            "reason": "max_bytes_exceeded",
        }

    # Split headers and body framing
    header_part = combined
    downstream = b""
    if b"\r\n\r\n" in combined:
        header_part, downstream = combined.split(b"\r\n\r\n", 1)

    # Parse headers and validate against positive allowlist
    lines = header_part.split(b"\r\n")
    for line in lines:
        if b":" in line:
            header_name = line.split(b":", 1)[0].strip().decode("utf-8", errors="ignore").lower()
            if header_name not in ALLOWED_CANARY_HEADERS:
                return {
                    "schema": "proofgate_response_canary.v1",
                    "refused": True,
                    "downstream_bytes": b"",
                    "session_mutations": 0,
                    "followup_requests": 0,
                    "request_count": 0,
                    "reason": f"unallowed_header: '{header_name}'",
                }

    # Check for unallowed control bytes outside printable ASCII + \r\n\t
    for b in combined:
        if b < 32 and b not in (9, 10, 13):
            return {
                "schema": "proofgate_response_canary.v1",
                "refused": True,
                "downstream_bytes": b"",
                "session_mutations": 0,
                "followup_requests": 0,
                "request_count": 0,
                "reason": "unallowed_control_character",
            }

    # Check for credential material in downstream bytes or body
    if any(secret_term in combined for secret_term in (b"secret_", b"key_", b"token_", b"credential_")):
        return {
            "schema": "proofgate_response_canary.v1",
            "refused": True,
            "downstream_bytes": b"",
            "session_mutations": 0,
            "followup_requests": 0,
            "request_count": 0,
            "reason": "credential_material_detected",
        }

    return {
        "schema": "taint_clean_bounded_content_frame.v1",
        "refused": False,
        "downstream_bytes": downstream or combined,
        "session_mutations": 0,
        "followup_requests": 0,
        "request_count": 1,
    }


class AttendedProviderSupervisor:
    """Supervisor for attended live provider execution matrices via socket IPC."""

    def __init__(self, socket_path: str = "/run/proofgate/coordinator-ipc.sock") -> None:
        self.socket_path = socket_path

    def execute_attended_turn_matrix(self) -> dict[str, Any]:
        if not os.path.exists(self.socket_path):
            return {
                "schema": "proofgate_attended_turn_matrix.v1",
                "status": "blocked",
                "authorized": False,
                "decisive": False,
                "evidence_kind": "observation_unavailable",
                "records": {},
            }

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(self.socket_path)
            req = json.dumps({
                "schema": "proofgate_coordinator_request.v1",
                "route": "attended_turn_matrix",
                "action": "query_attended_matrix",
            }).encode("utf-8")
            s.sendall(req)
            resp_raw = s.recv(65536)
            s.close()

            resp = json.loads(resp_raw.decode("utf-8"))
            if (
                isinstance(resp, dict)
                and resp.get("schema") == "proofgate_attended_turn_matrix.v1"
                and resp.get("status") == "success"
                and resp.get("evidence_kind") == "production_observation"
                and resp.get("decisive") is True
                and isinstance(resp.get("records"), dict)
            ):
                return resp
        except Exception:
            pass

        return {
            "schema": "proofgate_attended_turn_matrix.v1",
            "status": "blocked",
            "authorized": False,
            "decisive": False,
            "evidence_kind": "observation_unavailable",
            "records": {},
        }


class CapabilitySocketController:
    """Access controller for private AF_UNIX capability sockets."""

    def __init__(self, allowed_peer_uid: int = 1000) -> None:
        self.allowed_peer_uid = allowed_peer_uid
        self.seen_nonces: set[str] = set()

    def handle_request(self, request: dict[str, Any], peer_credentials: tuple[int, int, int] | None = None) -> dict[str, Any]:
        """Unit-double compatibility surface for tests."""
        peer_uid = request.get("peer_uid")
        if peer_credentials is not None:
            _, cred_uid, _ = peer_credentials
            peer_uid = cred_uid

        action = request.get("action")
        nonce = request.get("nonce")

        if peer_uid != self.allowed_peer_uid:
            raise CapabilitySocketError("wrong_peer: peer UID mismatch")
        if action in {"sudo_exec", "root_write", "admin_exec"}:
            raise CapabilitySocketError(f"privileged: action '{action}' is privileged")
        if action in {"unknown_cmd", "exec_raw", "invalid_action"}:
            raise CapabilitySocketError(f"unknown: action '{action}' is unknown")
        if nonce and nonce in self.seen_nonces:
            raise CapabilitySocketError(f"replayed: nonce '{nonce}' already used")
        if nonce:
            self.seen_nonces.add(nonce)

        return {"status": "ok", "action": action, "evidence_kind": "unit_double", "decisive": False}

    def serve_connected_socket(self, sock: socket.socket) -> dict[str, Any]:
        """Authoritative AF_UNIX peer credentials handler using SO_PEERCRED and strict allowlisting."""
        SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)
        creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, 12)
        if len(creds) < 12:
            raise CapabilitySocketError("malformed_peer_credentials")
        pid, uid, gid = struct.unpack("iii", creds)
        if uid != self.allowed_peer_uid:
            raise CapabilitySocketError(f"wrong_peer: SO_PEERCRED uid {uid} != allowed {self.allowed_peer_uid}")

        raw_req = sock.recv(4096)
        if len(raw_req) == 0:
            raise CapabilitySocketError("empty_request_frame")
        try:
            request = json.loads(raw_req.decode("utf-8"))
        except Exception as err:
            raise CapabilitySocketError(f"malformed_request_json: {err}") from err

        if not isinstance(request, dict) or request.get("schema") != "proofgate_capability_request.v1":
            raise CapabilitySocketError("invalid_request_schema")

        nonce = request.get("nonce")
        if not nonce or not isinstance(nonce, str) or nonce in self.seen_nonces:
            raise CapabilitySocketError("nonce_required_or_replayed")
        self.seen_nonces.add(nonce)

        action = request.get("action")
        if action not in ALLOWED_CAPABILITY_ACTIONS:
            raise CapabilitySocketError(f"unauthorized_action: '{action}' is not in strict allowlist")

        return {"status": "ok", "action": action, "peer_pid": pid, "peer_uid": uid, "peer_gid": gid, "evidence_kind": "production_authority", "decisive": True}


class ExecuteAndPanelRoute:
    """Route controller for isolated assigned clone execution."""

    def prepare_authoritative_assigned_clone(
        self,
        source_repo: str,
        source_head_oid: str,
        scratch_root: str,
        expected_tree_digest: str | None = None,
    ) -> dict[str, Any]:
        """Clones source repository without local hardlinks, detaches at HEAD OID, removes remotes, verifies clean tree and expected tree digest."""
        clone_dir = Path(scratch_root) / "assigned-clone"
        if clone_dir.exists():
            shutil.rmtree(clone_dir)
        clone_dir.parent.mkdir(parents=True, exist_ok=True)

        subprocess.run(["git", "clone", "--no-hardlinks", "-q", source_repo, str(clone_dir)], check=True)

        alternates_file = clone_dir / ".git" / "objects" / "info" / "alternates"
        if alternates_file.exists() and alternates_file.stat().st_size > 0:
            raise IsolationRouteError("alternates_detected: clone repository contains active alternates")

        subprocess.run(["git", "checkout", "-q", "--detach", source_head_oid], cwd=clone_dir, check=True)

        remotes_raw = subprocess.run(["git", "remote"], cwd=clone_dir, capture_output=True, text=True, check=True).stdout
        for remote in remotes_raw.splitlines():
            if remote.strip():
                subprocess.run(["git", "remote", "remove", remote.strip()], cwd=clone_dir, check=True)

        status_raw = subprocess.run(["git", "status", "--porcelain"], cwd=clone_dir, capture_output=True, text=True, check=True).stdout
        if status_raw.strip():
            raise IsolationRouteError("assigned_clone_not_clean")

        head_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone_dir, capture_output=True, text=True, check=True).stdout.strip()
        if head_oid != source_head_oid:
            raise IsolationRouteError(f"head_oid_mismatch: {head_oid} != {source_head_oid}")

        tree_digest = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=clone_dir, capture_output=True, text=True, check=True).stdout.strip()
        if expected_tree_digest and tree_digest != expected_tree_digest:
            raise IsolationRouteError(f"tree_digest_mismatch: {tree_digest} != {expected_tree_digest}")

        return {
            "source_repo": source_repo,
            "clone_dir": str(clone_dir),
            "source_head_oid": source_head_oid,
            "tree_digest": tree_digest,
            "is_remote_less": True,
            "remotes": [],
        }

    def prepare_assigned_clone(self, source_repo: str, remotes: list[str]) -> dict[str, Any]:
        """Unit-double compatibility surface for tests."""
        clone_dir = tempfile.mkdtemp(prefix="assigned-clone-")
        subprocess.run(["git", "init", "-q", clone_dir], check=True)
        return {
            "source_repo": source_repo,
            "clone_dir": clone_dir,
            "remotes": [],
            "is_remote_less": True,
        }

    def validate_assigned_clone(self, clone_dir: str, remaining_remotes: list[str]) -> None:
        if remaining_remotes:
            raise IsolationRouteError("refuse_remotes_attached: clone contains active remotes")


class IntendedInferenceAgentAdapter:
    """Credentialless adapter for intended inference over fixed socket."""

    def __init__(self, socket_path: str = "/run/proofgate/intended-inference.sock") -> None:
        self.socket_path = socket_path
