"""Provider-backing selector + auth-enforcement contract (IF-0-ABDFREEZE-3).

Two orthogonal per-seat axes, frozen here:

* **backing** (``homebrew | omnigent``) — the transport. Selected per seat;
  ``homebrew`` is the default and keeps the built-3 + native host leg.
* **auth** (``subscription | api_key``) — the credential lane. Subscription is
  the default; api-key is reachable only behind ``Board.allow_api_key_fallback``.

**No-silent-key is enforced by ACTIVE environment scrubbing**, freezing the
existing ``_subscription_env`` pattern (panel_invoker.py:226-230,348-353) into a
per-seat, vendor-keyed contract:

* a **subscription** seat scrubs EVERY vendor API-key var from the subprocess env
  / gateway payload (identical to ``_subscription_env`` today); and
* an **api-key fallback** seat scrubs everything, then injects ONLY the seat
  vendor's key var(s) — never another vendor's, never silently.

``VENDOR_API_KEY_VARS`` is the flat ``panel_invoker._API_KEY_VARS`` tuple
re-expressed keyed by vendor family, so "inject only the seat vendor's key" is
expressible. The union of its values equals the current flat tuple (asserted in
``tests/test_advisor_board_backcompat.py``), so scrubbing stays byte-equivalent.
The reference env functions below are pure and importable; ABDHOME wires them
into the real launch/gateway env (this module changes no running path).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
import platform
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import struct
import weakref

from .schema import (
    AUTH_API_KEY,
    AUTH_SUBSCRIPTION,
    BACKING_HOMEBREW,
    BACKING_OMNIGENT,
    PROVIDER_BACKINGS,
    Board,
    Seat,
    seat_vendor_family,
)


# Vendor family -> the provider API-key env var(s) that vendor authenticates with.
# The UNION of all values MUST equal ``panel_invoker._API_KEY_VARS`` so subscription
# scrubbing is byte-equivalent to ``_subscription_env`` today.
VENDOR_API_KEY_VARS: dict[str, tuple[str, ...]] = {
    "codex": ("OPENAI_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
}

# HARDEN's only executable public-review routes.  The parent keeps subscription
# state; a child receives neither credentials nor a provider client, only this
# brokered intended-inference contract and immutable staged input.
PARENT_UNIX_BROKER_V1 = "parent_unix_broker_v1"
HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES: dict[str, str] = {
    "claude": "claude-fable-5",  # model-id-source: HARDEN Fable 5 subscription route
    "codex": "gpt-5.6-sol",  # model-id-source: HARDEN Sol subscription route
    "gemini": "gemini-3.6-flash-high",  # model-id-source: HARDEN Gemini 3.6 Flash high subscription route
    "grok": "grok-4.5",  # model-id-source: HARDEN Grok 4.5 subscription route
}
_HARDEN_ACCEPTED_CONFIGURED_MODELS: dict[str, tuple[str, ...]] = {
    "claude": ("claude-fable-5",),  # model-id-source: HARDEN configured Fable compatibility edge
    "codex": ("gpt-5.6-sol",),  # model-id-source: HARDEN configured Sol compatibility edge
    # Keep the current fleet defaults structurally intact while the brokered
    # HARDEN operation resolves its plan-pinned subscription route.
    "gemini": ("gemini-3.6-flash-high", "gemini-3.7-flash"),  # model-id-source: HARDEN exact and fleet-default compatibility edge
    "grok": ("grok-4.5", "grok-4.6"),  # model-id-source: HARDEN exact and fleet-default compatibility edge
}


def harden_subscription_model(harness: str, configured_model: str) -> str:
    """Resolve an allowed fleet configuration to HARDEN's exact provider route."""
    route = HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES.get(harness)
    if route is None or configured_model not in _HARDEN_ACCEPTED_CONFIGURED_MODELS.get(harness, ()):
        raise ValueError("HARDEN review route is unsupported")
    return route


def harden_subscription_review_board(board: Board) -> Board:
    """Use HARDEN's fixed review fleet without changing ordinary board defaults."""
    seats: list[Seat] = []
    for seat in board.seats:
        harness = str(seat.harness or "").lower()
        model = harden_subscription_model(harness, seat.model)
        seats.append(replace(seat, model=model))
    return replace(board, seats=tuple(seats))
_REVIEW_READONLY_TOOLS = ("Read", "Glob", "Grep", "LS")
_AUTHORIZATION_SEAL = object()
_BROKER_MAX_BYTES = 16384
_BROKER_RESPONSE_MAX_BYTES = 65536
_BROKER_RESPONSE_STATUSES = frozenset({
    "OK", "EMPTY", "TIMEOUT", "ERROR", "DEGRADED", "UNAVAILABLE",
})
_BROKER_TRANSPORT_ALLOWANCE_NS = 2_000_000_000
_PRE_ACTIVATION_FRESHNESS_NS = 30_000_000_000
_LEASES_LOCK = threading.RLock()
_REVIEW_LEASES: dict[int, tuple[weakref.ReferenceType["ReviewIsolationAuthorization"], "_ReviewInvocationLease"]] = {}
_LEG_CLAIMS: dict[int, tuple[weakref.ReferenceType["ReviewLegAuthorization"], "_ReviewLegClaim"]] = {}
_COMPOSITION_AUTHORIZATION: ContextVar["ReviewCompositionAuthorization | None"] = ContextVar(
    "harden_review_composition_authorization", default=None
)
_REVIEW_INSTRUCTIONS_SHA256: ContextVar[str | None] = ContextVar(
    "harden_review_instructions_sha256", default=None
)


@dataclass(frozen=True)
class BrokerRequest:
    operation: str
    nonce: str
    harness: str
    model: str
    purpose: str
    input_sha256: str


@dataclass(frozen=True)
class ReviewLegAuthorization:
    """Sealed short-lived authority for exactly one brokered provider leg."""

    operation: str
    purpose: str
    input_sha256: str
    instructions_sha256: str
    canonical_repo_sha256: str
    broker_contract: str
    harness: str
    model: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    _seal: object


@dataclass(frozen=True)
class ReviewCompositionAuthorization:
    """Short pre-effect authority for a single review-board composition."""

    operation: str
    issued_monotonic_ns: int
    _seal: object


class _ReviewInvocationLease:
    """Private, process-local lifecycle state; it is deliberately not evidence."""

    def __init__(self, authorization: "ReviewIsolationAuthorization") -> None:
        self.lock = threading.RLock()
        self.prepared_monotonic_ns = authorization.issued_monotonic_ns
        self.route_counts = Counter(authorization.routes)
        self.active = False
        self.closed = False


class _ReviewLegClaim:
    """Private single-consumer state for a minted leg capability."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.claimed = False


class _BrokerInferenceAdapter:
    """Internal adapter with an owned cancellation and quiescence contract."""

    __slots__ = ("invoke", "cancel", "is_quiescent", "_seal")

    def __init__(
        self,
        invoke: Callable[[], tuple[str, str]],
        cancel: Callable[[], None],
        is_quiescent: Callable[[], bool],
        *,
        seal: object,
    ) -> None:
        self.invoke = invoke
        self.cancel = cancel
        self.is_quiescent = is_quiescent
        self._seal = seal


_ADAPTER_SEAL = object()


def _make_broker_inference_adapter(
    invoke: Callable[[], tuple[str, str]],
    cancel: Callable[[], None],
    is_quiescent: Callable[[], bool],
) -> _BrokerInferenceAdapter:
    """Create the only accepted broker adapter; bare callbacks are rejected."""
    if not all(callable(value) for value in (invoke, cancel, is_quiescent)):
        raise ValueError("broker inference adapter requires cancellation and quiescence")
    if not is_quiescent():
        raise ValueError("broker inference adapter is not initially quiescent")
    return _BrokerInferenceAdapter(invoke, cancel, is_quiescent, seal=_ADAPTER_SEAL)


def _remember_lease(authorization: "ReviewIsolationAuthorization") -> None:
    key = id(authorization)

    def discard(reference: weakref.ReferenceType[ReviewIsolationAuthorization]) -> None:
        with _LEASES_LOCK:
            current = _REVIEW_LEASES.get(key)
            if current is not None and current[0] is reference:
                _REVIEW_LEASES.pop(key, None)

    with _LEASES_LOCK:
        _REVIEW_LEASES[key] = (weakref.ref(authorization, discard), _ReviewInvocationLease(authorization))


def _lease_for(authorization: "ReviewIsolationAuthorization") -> _ReviewInvocationLease:
    with _LEASES_LOCK:
        current = _REVIEW_LEASES.get(id(authorization))
        if current is None or current[0]() is not authorization:
            raise ValueError("missing HARDEN review invocation lease")
        return current[1]


def _remember_leg_claim(authorization: ReviewLegAuthorization) -> None:
    key = id(authorization)

    def discard(reference: weakref.ReferenceType[ReviewLegAuthorization]) -> None:
        with _LEASES_LOCK:
            current = _LEG_CLAIMS.get(key)
            if current is not None and current[0] is reference:
                _LEG_CLAIMS.pop(key, None)

    with _LEASES_LOCK:
        _LEG_CLAIMS[key] = (weakref.ref(authorization, discard), _ReviewLegClaim())


def _claim_leg_authorization(authorization: ReviewLegAuthorization) -> None:
    with _LEASES_LOCK:
        current = _LEG_CLAIMS.get(id(authorization))
        if current is None or current[0]() is not authorization:
            raise ValueError("missing HARDEN review leg claim")
        claim = current[1]
    with claim.lock:
        if claim.claimed:
            raise ValueError("HARDEN review leg capability already consumed")
        claim.claimed = True


def _recv_frame(sock: socket.socket, maximum: int) -> bytes:
    """Read one length-delimited AF_UNIX message; streams have no message edges."""
    def exact(size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ValueError("truncated broker frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    size = struct.unpack("!I", exact(4))[0]
    if size > maximum:
        raise ValueError("broker frame too large")
    return exact(size)


def _send_frame(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(struct.pack("!I", len(payload)) + payload)


class ParentUnixBroker:
    """One-request parent-owned AF_UNIX broker; child selects no provider action."""
    def __init__(
        self,
        authorization: ReviewLegAuthorization,
        *,
        harness: str,
        model: str,
        staged_dir: Path,
        canonical_repo: Path,
    ) -> None:
        if (
            not isinstance(authorization, ReviewLegAuthorization)
            or authorization._seal is not _AUTHORIZATION_SEAL
            or authorization.broker_contract != PARENT_UNIX_BROKER_V1
            or (harness, model) != (authorization.harness, authorization.model)
            or time.monotonic_ns() >= authorization.expires_monotonic_ns
        ):
            raise ValueError("broker route is not authorized")
        _claim_leg_authorization(authorization)
        bundle = staged_dir / "review-bundle.md"
        instructions = staged_dir / "review-instructions.md"
        if (
            not bundle.is_file()
            or not instructions.is_file()
            or bundle.stat().st_mode & 0o222
            or instructions.stat().st_mode & 0o222
            or sha256(bundle.read_bytes()).hexdigest() != authorization.input_sha256
            or sha256(instructions.read_bytes()).hexdigest() != authorization.instructions_sha256
        ):
            raise ValueError("broker stage is not immutable and bound")
        self.authorization, self.harness, self.model = authorization, harness, model
        self.staged_dir = staged_dir.resolve()
        self.canonical_repo = canonical_repo.resolve()
        if (
            not self.canonical_repo.is_dir()
            or _canonical_repo_digest(self.canonical_repo)
            != authorization.canonical_repo_sha256
        ):
            raise ValueError("broker canonical repository authority is not probeable")
        try:
            listed = subprocess.check_output(
                ["git", "-C", str(self.canonical_repo), "ls-files", "-z"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).split("\0")
            probe_file = next(
                (
                    self.canonical_repo / relative
                    for relative in listed
                    if relative
                    and (self.canonical_repo / relative).is_file()
                ),
                None,
            )
        except (OSError, subprocess.SubprocessError):
            probe_file = None
        if probe_file is None:
            raise ValueError("broker canonical repository authority is not probeable")
        self._canonical_probe_file = probe_file
        self._instruction_sha256 = sha256(instructions.read_bytes()).hexdigest()
        self.nonce = secrets.token_hex(32)
        self.root = Path(tempfile.mkdtemp(prefix="phase-loop-broker-")); self.root.chmod(0o700)
        secret_fd, secret_path = tempfile.mkstemp(prefix="phase-loop-host-probe-")
        try:
            os.fchmod(secret_fd, 0o600)
            os.write(secret_fd, secrets.token_bytes(32))
        finally:
            os.close(secret_fd)
        self._host_secret_probe = Path(secret_path)
        self.path = self.root / "intended-inference.sock"; self._used = False
        self.evidence: dict[str, object] = {
            "schema": PARENT_UNIX_BROKER_V1,
            "stage_bundle_sha256": authorization.input_sha256,
            "stage_instructions_sha256": self._instruction_sha256,
            "leg_authorization_instructions_sha256": authorization.instructions_sha256,
            "leg_authorization_issued_monotonic_ns": authorization.issued_monotonic_ns,
            "leg_authorization_expires_monotonic_ns": authorization.expires_monotonic_ns,
            "canonical_repo_sha256": authorization.canonical_repo_sha256,
            "canonical_repo_probe_file_sha256": sha256(str(probe_file).encode()).hexdigest(),
            "cleanup_root_removed": False,
            "child_quiescent": False,
        }
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); self._sock.bind(str(self.path)); self._sock.listen(1); self._sock.settimeout(10)
        self.path.chmod(0o600)
    def close(self) -> None:
        self._sock.close()
        try: self.path.unlink()
        except FileNotFoundError: pass
        try: self.root.rmdir()
        except OSError: pass
        try: self._host_secret_probe.unlink()
        except FileNotFoundError: pass
        self.evidence["cleanup_root_removed"] = not self.root.exists()
        self.evidence["host_secret_probe_removed"] = not self._host_secret_probe.exists()
    @staticmethod
    def _proc_stat(pid: int) -> tuple[int, int]:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        end = raw.rfind(")")
        fields = raw[end + 2:].split()
        if end < 1 or len(fields) < 20 or not all(x.lstrip("-").isdigit() for x in (fields[1], fields[19])):
            raise ValueError("unverifiable broker proc stat")
        return int(fields[1]), int(fields[19])  # ppid, start-time ticks

    @classmethod
    def _descends_from(cls, peer_pid: int, root_pid: int, root_start: int) -> bool:
        seen: set[int] = set(); current = peer_pid
        for _ in range(32):
            if current in seen or current <= 1: return False
            seen.add(current)
            ppid, started = cls._proc_stat(current)
            if current == root_pid: return started == root_start
            current = ppid
        return False

    def serve_once(
        self,
        adapter: _BrokerInferenceAdapter,
        *,
        expected_pid: int,
        expected_start: int,
    ) -> None:
        conn, _ = self._sock.accept()
        with conn:
            if not hasattr(socket, "SO_PEERCRED"): raise ValueError("peer credentials unavailable")
            peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            pid, uid, gid = struct.unpack("3i", peer)
            if uid != os.getuid() or gid != os.getgid() or not self._descends_from(pid, expected_pid, expected_start): raise ValueError("broker peer ancestry mismatch")
            self.evidence.update({"peer_pid": pid, "peer_uid": uid, "peer_gid": gid, "peer_ancestry_verified": True})
            if time.monotonic_ns() >= self.authorization.expires_monotonic_ns: raise ValueError("broker authorization expired")
            raw = _recv_frame(conn, _BROKER_MAX_BYTES)
            data = json.loads(raw)
            if set(data) != {"schema","operation","nonce","harness","model","purpose","input_sha256"}: raise ValueError("broker request grammar")
            if self._used or data != {"schema":PARENT_UNIX_BROKER_V1,"operation":self.authorization.operation,"nonce":self.nonce,"harness":self.harness,"model":self.model,"purpose":self.authorization.purpose,"input_sha256":self.authorization.input_sha256}: raise ValueError("broker request binding")
            self._used = True; status, text = adapter.invoke()
            if (
                status not in _BROKER_RESPONSE_STATUSES
                or not isinstance(text, str)
                or len(text.encode()) > _BROKER_RESPONSE_MAX_BYTES
            ):
                raise ValueError("broker response grammar")
            # The response schema has no control channel: text is opaque inference
            # prose, while redirect/auth/session/provider/tool/command metadata has
            # no representable field and is rejected by the exact-key check below.
            _send_frame(conn, json.dumps({"schema":PARENT_UNIX_BROKER_V1,"status":status,"text":text}, separators=(",", ":")).encode())

    def run_credentialless_client(
        self, adapter: _BrokerInferenceAdapter, *, deadline_s: float,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Run the sole child operation: a fixed broker request in a no-net namespace."""
        if (
            not isinstance(adapter, _BrokerInferenceAdapter)
            or adapter._seal is not _ADAPTER_SEAL
            or not adapter.is_quiescent()
        ):
            raise ValueError("broker requires a quiescent cancellable inference adapter")
        bwrap = Path("/usr/bin/bwrap")
        python = Path("/usr/bin/python3")
        if platform.system() != "Linux" or not bwrap.is_file() or not os.access(bwrap, os.X_OK) or not python.is_file():
            raise ValueError("HARDEN broker requires canonical bwrap and python3")
        request = {"schema":PARENT_UNIX_BROKER_V1,"operation":self.authorization.operation,"nonce":self.nonce,"harness":self.harness,"model":self.model,"purpose":self.authorization.purpose,"input_sha256":self.authorization.input_sha256}
        host_netns_inode = os.stat("/proc/self/ns/net").st_ino
        # This program is generated only from parent-owned constants.  It has no
        # command, provider, prompt, credential, or route parameter: it proves the
        # mount/env/socket posture before making the one fixed broker request.
        code = "\n".join((
            "import hashlib, json, os, socket, sys",
            "from pathlib import Path",
            "root = Path('/run/phase-loop-review')",
            f"assert hashlib.sha256((root / 'review-bundle.md').read_bytes()).hexdigest() == {self.authorization.input_sha256!r}",
            f"assert hashlib.sha256((root / 'review-instructions.md').read_bytes()).hexdigest() == {self._instruction_sha256!r}",
            "assert not any(name in os.environ for name in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY','HOME','XDG_CONFIG_HOME'))",
            "assert not ((root / 'review-bundle.md').stat().st_mode & 0o222)",
            "assert not ((root / 'review-instructions.md').stat().st_mode & 0o222)",
            "try:\n    (root / 'review-bundle.md').write_bytes(b'x')\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('stage writable')",
            f"try:\n    Path({str(self.staged_dir / 'review-bundle.md')!r}).read_bytes()\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('live bundle exposed')",
            f"try:\n    Path({str(self.staged_dir / 'review-instructions.md')!r}).read_bytes()\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('live instructions exposed')",
            f"try:\n    Path({str(self._host_secret_probe)!r}).read_bytes()\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('host secret exposed')",
            f"try:\n    Path({str(self._canonical_probe_file)!r}).read_bytes()\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('canonical repo file exposed')",
            f"try:\n    Path({str(self.canonical_repo)!r}).stat()\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('canonical repo directory exposed')",
            "try:\n    os.fstat(3)\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('inherited fd')",
            "probe = socket.socket(socket.AF_UNIX)\ntry:\n    probe.connect('/run/phase-loop-broker/not-the-broker.sock')\nexcept OSError:\n    pass\nelse:\n    raise RuntimeError('alternate socket')\nfinally:\n    probe.close()",
            f"if os.stat('/proc/self/ns/net').st_ino == {host_netns_inode}:\n    raise RuntimeError('network namespace shared')",
            "sock = socket.socket(socket.AF_UNIX)",
            "sock.connect('/run/phase-loop-broker/intended-inference.sock')",
            "request = sys.stdin.buffer.read()",
            "sock.sendall(len(request).to_bytes(4, 'big') + request)",
            "def exact(size):\n    parts=[]\n    while size:\n        part=sock.recv(size)\n        if not part: raise RuntimeError('truncated response')\n        parts.append(part); size -= len(part)\n    return b''.join(parts)",
            "response_size = int.from_bytes(exact(4), 'big')",
            "assert response_size <= 65536",
            "response = json.loads(exact(response_size))",
            "assert set(response) == {'schema','status','text'} and response['schema'] == 'parent_unix_broker_v1'",
            "assert response['status'] in {'OK','EMPTY','TIMEOUT','ERROR','DEGRADED','UNAVAILABLE'} and isinstance(response['text'], str)",
            "print(json.dumps(response, separators=(',', ':')))",
        ))
        runtime_binds: list[str] = ["--ro-bind", "/usr", "/usr"]
        for runtime in ("/lib", "/lib64"):
            if Path(runtime).exists(): runtime_binds.extend(("--ro-bind", runtime, runtime))
        argv = [str(bwrap),"--unshare-all","--die-with-parent","--new-session","--clearenv",*runtime_binds,"--dir","/run","--ro-bind",str(self.root),"/run/phase-loop-broker","--ro-bind",str(self.staged_dir),"/run/phase-loop-review","--tmpfs","/tmp","--proc","/proc","--dev","/dev","--setenv","PATH","/usr/bin","--setenv","PYTHONNOUSERSITE","1","--setenv","PYTHONDONTWRITEBYTECODE","1",str(python),"-I","-S","-c",code]
        error: list[BaseException] = []
        child: list[tuple[subprocess.Popen[bytes], int]] = []
        child_ready = threading.Event()
        def serve() -> None:
            if not child_ready.wait(timeout=max(1.0, deadline_s)):
                error.append(ValueError("broker child launch was not observed")); return
            try:
                self.serve_once(
                    adapter, expected_pid=child[0][0].pid, expected_start=child[0][1]
                )
            except BaseException as exc: error.append(exc)
        thread=threading.Thread(target=serve, daemon=False); thread.start()
        proc=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/bin","PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1"},close_fds=True,start_new_session=True)
        _ppid, start = self._proc_stat(proc.pid)
        child.append((proc, start)); child_ready.set()
        stdout = b""; stderr = b""; timed_out = False; provider_cancelled = False
        try:
            # Include a small transport allowance only after the bounded parent
            # inference deadline; this is never the former fixed 15-second wall.
            stdout, stderr = proc.communicate(
                json.dumps(request,separators=(",",":")).encode(),
                timeout=max(1.0, float(deadline_s)) + 2.0,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, 15)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, 9)
                except ProcessLookupError:
                    pass
                stdout, stderr = proc.communicate()
        finally:
            # Closing the listener wakes an accept that has not reached the
            # inference call.  The non-daemon server is joined before returning.
            try: self._sock.close()
            except OSError: pass
            if timed_out:
                adapter.cancel()
                provider_cancelled = True
            # The only accepted adapter is parent-owned and must acknowledge
            # cancellation.  A bounded join prevents an uncooperative injected
            # callback from turning the broker into an unbounded hidden thread.
            thread.join(timeout=_BROKER_TRANSPORT_ALLOWANCE_NS / 1_000_000_000)
        adapter_quiescent = adapter.is_quiescent()
        self.evidence.update({
            "bwrap": str(bwrap), "outer_bwrap_pid": proc.pid, "outer_bwrap_start": start,
            "network_unshared": "--unshare-all" in argv and "--share-net" not in argv,
            "close_fds_requested": True,
            "socket": "/run/phase-loop-broker/intended-inference.sock",
            "stage": "/run/phase-loop-review", "argv_sha256": sha256("\0".join(argv).encode()).hexdigest(),
            "socket_present_before_launch": self.path.is_socket(),
            "stage_bundle_mode": (self.staged_dir / "review-bundle.md").stat().st_mode & 0o777,
            "stage_instructions_mode": (self.staged_dir / "review-instructions.md").stat().st_mode & 0o777,
            "client_probe_program_sha256": sha256(code.encode()).hexdigest(),
            "client_probe_assertions": ("credentialless_env", "readonly_stage", "no_live_bundle", "no_live_instructions", "no_host_secret", "no_live_tree", "no_inherited_fd", "fixed_socket_only", "no_af_inet"),
            "canonical_repo_file_denied": proc.returncode == 0,
            "canonical_repo_directory_denied": proc.returncode == 0,
            "host_stage_path_denied": proc.returncode == 0,
            "child_returncode": proc.returncode, "child_quiescent": proc.poll() is not None,
            "no_inherited_fd_observed": proc.returncode == 0,
            "child_stderr_sha256": sha256(stderr).hexdigest(),
            "operation_deadline_s": float(deadline_s),
            "child_timeout": timed_out,
            "broker_thread_quiescent": not thread.is_alive(),
            "provider_adapter_quiescent": adapter_quiescent,
            "provider_cancel_requested": provider_cancelled,
        })
        if timed_out or error or thread.is_alive() or not adapter_quiescent or proc.returncode != 0:
            raise ValueError(f"credentialless broker client failed: {error[0] if error else 'deadline' if timed_out else proc.returncode}")
        result=json.loads(stdout)
        if set(result) != {"schema", "status", "text"} or result.get("schema") != PARENT_UNIX_BROKER_V1:
            raise ValueError("broker child response grammar")
        return result, self.evidence


@dataclass(frozen=True)
class ReviewIsolationAuthorization:
    """Unforgeable-in-normal-use capability for one brokered review operation.

    It deliberately contains only metadata and an input digest: no child
    credentials, provider method, host command, live-tree path, or mutable
    cleanup handle can cross this boundary.  ``_seal`` is identity-checked by
    this module and is never serialized or accepted from external JSON.
    """

    operation: str
    purpose: str
    input_sha256: str
    instructions_sha256: str | None
    broker_contract: str
    routes: tuple[tuple[str, str], ...]
    readonly_tools: tuple[str, ...]
    child_credentialless: bool
    child_network_egress: bool
    live_tree_exposed: bool
    api_fallback: bool
    canonical_repo_sha256: str
    issued_monotonic_ns: int
    _seal: object


def _canonical_repo_digest(canonical_repo_authority: Path | str | None) -> str:
    candidate = Path(canonical_repo_authority) if canonical_repo_authority is not None else Path.cwd()
    try:
        root = subprocess.check_output(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError("HARDEN review has no canonical repository authority") from None
    if not root:
        raise ValueError("HARDEN review has no canonical repository authority")
    return sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()


def set_review_instruction_digest(instructions: str):
    """Bind resolved immutable instructions to the current public operation.

    The context is process-local authority only.  It is never retained in the
    authorization's serialized evidence and lets existing injectable factory
    seams keep their frozen call signature.
    """
    return _REVIEW_INSTRUCTIONS_SHA256.set(
        sha256(instructions.encode("utf-8", errors="strict")).hexdigest()
    )


def reset_review_instruction_digest(token: object) -> None:
    _REVIEW_INSTRUCTIONS_SHA256.reset(token)  # type: ignore[arg-type]


def prepare_review_composition_authorization() -> ReviewCompositionAuthorization:
    """Mint pre-effect authority used only while resolving a live review board."""
    if platform.system() != "Linux":
        raise ValueError("HARDEN review composition requires Linux")
    authorization = ReviewCompositionAuthorization(
        operation="public_board_review_composition.v1",
        issued_monotonic_ns=time.monotonic_ns(),
        _seal=_AUTHORIZATION_SEAL,
    )
    _COMPOSITION_AUTHORIZATION.set(authorization)
    return authorization


def current_review_composition_authorization() -> ReviewCompositionAuthorization | None:
    return _COMPOSITION_AUTHORIZATION.get()


def clear_review_composition_authorization() -> None:
    _COMPOSITION_AUTHORIZATION.set(None)


def revalidate_review_composition_authorization(
    authorization: ReviewCompositionAuthorization | None,
) -> None:
    if (
        not isinstance(authorization, ReviewCompositionAuthorization)
        or authorization._seal is not _AUTHORIZATION_SEAL
        or authorization.operation != "public_board_review_composition.v1"
        or time.monotonic_ns() - authorization.issued_monotonic_ns
        > _PRE_ACTIVATION_FRESHNESS_NS
    ):
        raise ValueError("missing, forged, or expired HARDEN composition authorization")


def prepare_review_isolation_authorization(
    board: object,
    artifact: str,
    *,
    mode: str,
    canonical_repo_authority: Path | str | None = None,
) -> ReviewIsolationAuthorization:
    """Authorize a review before composition or any provider/session effect.

    The caller must provide the final immutable artifact bytes.  Unsupported or
    non-subscription seats are rejected rather than silently downgraded.
    """
    if platform.system() != "Linux" or mode != "review":
        raise ValueError("HARDEN review isolation requires a Linux review operation")
    seats = getattr(board, "seats", ())
    routes: list[tuple[str, str]] = []
    for seat in seats:
        harness = str(getattr(seat, "harness", "") or "").lower()
        model = str(getattr(seat, "model", ""))
        if not harness:
            continue
        if getattr(seat, "auth", None) != AUTH_SUBSCRIPTION or getattr(seat, "backing", None) != BACKING_HOMEBREW:
            continue
        try:
            routes.append((harness, harden_subscription_model(harness, model)))
        except ValueError:
            # A non-policy Claude seat under Claude Code is a typed native-host
            # deferral, never a brokered provider route.  Retain its no-effect
            # authorization shape; invoke_board independently rejects it unless
            # the actual native-host deferral predicate holds.
            if harness != "claude":
                raise
    canonical_repo_sha256 = _canonical_repo_digest(canonical_repo_authority)
    instructions_sha256 = _REVIEW_INSTRUCTIONS_SHA256.get()
    issued = time.monotonic_ns()
    authorization = ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose=str(getattr(board, "purpose", "")),
        input_sha256=sha256(artifact.encode("utf-8")).hexdigest(),
        instructions_sha256=instructions_sha256,
        broker_contract=PARENT_UNIX_BROKER_V1, routes=tuple(routes),
        readonly_tools=_REVIEW_READONLY_TOOLS, child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256=canonical_repo_sha256,
        issued_monotonic_ns=issued,
        _seal=_AUTHORIZATION_SEAL,
    )
    _remember_lease(authorization)
    return authorization


def _expected_review_fields(
    board: object,
    artifact: str,
    *,
    mode: str,
    canonical_repo_authority: Path | str | None = None,
) -> dict[str, object]:
    """Pure structural expectation; unlike prepare it does not mint a lease."""
    if platform.system() != "Linux" or mode != "review":
        raise ValueError("HARDEN review isolation requires a Linux review operation")
    routes: list[tuple[str, str]] = []
    for seat in getattr(board, "seats", ()):
        harness = str(getattr(seat, "harness", "") or "").lower()
        model = str(getattr(seat, "model", ""))
        if not harness:
            continue
        if getattr(seat, "auth", None) != AUTH_SUBSCRIPTION or getattr(seat, "backing", None) != BACKING_HOMEBREW:
            continue
        try:
            routes.append((harness, harden_subscription_model(harness, model)))
        except ValueError:
            if harness != "claude":
                raise
    return {
        "operation": "public_board_review.v1",
        "purpose": str(getattr(board, "purpose", "")),
        "input_sha256": sha256(artifact.encode("utf-8")).hexdigest(),
        "instructions_sha256": _REVIEW_INSTRUCTIONS_SHA256.get(),
        "broker_contract": PARENT_UNIX_BROKER_V1,
        "routes": tuple(routes),
        "readonly_tools": _REVIEW_READONLY_TOOLS,
        "child_credentialless": True,
        "child_network_egress": False,
        "live_tree_exposed": False,
        "api_fallback": False,
        "canonical_repo_sha256": _canonical_repo_digest(canonical_repo_authority),
    }


def revalidate_review_isolation_authorization(
    authorization: ReviewIsolationAuthorization | None, board: object | None, artifact: str, *, mode: str,
    staged_dir: Path | None = None,
    canonical_repo_authority: Path | str | None = None,
) -> None:
    """Independently revalidate the operation capability immediately before use."""
    if not isinstance(authorization, ReviewIsolationAuthorization) or authorization._seal is not _AUTHORIZATION_SEAL:
        raise ValueError("missing or forged HARDEN review authorization")
    if board is not None:
        expected = _expected_review_fields(
            board,
            artifact,
            mode=mode,
            canonical_repo_authority=canonical_repo_authority,
        )
        for field, value in expected.items():
            if getattr(authorization, field) != value:
                raise ValueError(f"stale or mismatched HARDEN review authorization: {field}")
    elif (platform.system() != "Linux" or mode != "review" or
          authorization.operation != "public_board_review.v1" or
          authorization.broker_contract != PARENT_UNIX_BROKER_V1 or
          authorization.readonly_tools != _REVIEW_READONLY_TOOLS or not authorization.child_credentialless or
          authorization.child_network_egress or authorization.live_tree_exposed or authorization.api_fallback or
          authorization.input_sha256 != sha256(artifact.encode("utf-8")).hexdigest()):
        raise ValueError("invalid HARDEN review launch authorization")
    if canonical_repo_authority is not None and (
        _canonical_repo_digest(canonical_repo_authority)
        != authorization.canonical_repo_sha256
    ):
        raise ValueError("HARDEN review canonical repository authority mismatch")
    if staged_dir is not None:
        bundle = staged_dir / "review-bundle.md"
        instructions = staged_dir / "review-instructions.md"
        if (
            not bundle.is_file()
            or not instructions.is_file()
            or sha256(bundle.read_bytes()).hexdigest() != authorization.input_sha256
            or authorization.instructions_sha256 is None
            or sha256(instructions.read_bytes()).hexdigest() != authorization.instructions_sha256
        ):
            raise ValueError("HARDEN review staged input does not match authorization")
        if bundle.stat().st_mode & 0o222 or instructions.stat().st_mode & 0o222:
            raise ValueError("HARDEN review staged input is writable")


def activate_review_isolation_authorization(
    authorization: ReviewIsolationAuthorization | None,
    board: object,
    artifact: str,
    *,
    mode: str,
    canonical_repo_authority: Path | str | None = None,
) -> None:
    """Activate one prepared board immediately before executable seat work."""
    revalidate_review_isolation_authorization(
        authorization,
        board,
        artifact,
        mode=mode,
        canonical_repo_authority=canonical_repo_authority,
    )
    assert authorization is not None
    lease = _lease_for(authorization)
    with lease.lock:
        now = time.monotonic_ns()
        if lease.closed or lease.active:
            raise ValueError("HARDEN review authorization is not available for activation")
        if now - lease.prepared_monotonic_ns > _PRE_ACTIVATION_FRESHNESS_NS:
            raise ValueError("HARDEN review authorization expired before activation")
        lease.active = True


def close_review_isolation_authorization(
    authorization: ReviewIsolationAuthorization | None,
) -> None:
    """Close a board lease on every path; closed leases can never be revived."""
    if not isinstance(authorization, ReviewIsolationAuthorization):
        return
    try:
        lease = _lease_for(authorization)
    except ValueError:
        return
    with lease.lock:
        lease.active = False
        lease.closed = True


def derive_review_leg_authorization(
    authorization: ReviewIsolationAuthorization | None,
    artifact: str,
    *, harness: str, model: str, deadline_s: float, mode: str,
    canonical_repo_authority: Path | str | None,
) -> ReviewLegAuthorization:
    """Mint the short-lived, single-route capability immediately before launch."""
    revalidate_review_isolation_authorization(
        authorization,
        None,
        artifact,
        mode=mode,
        canonical_repo_authority=canonical_repo_authority,
    )
    if (
        not isinstance(authorization, ReviewIsolationAuthorization)
        or (harness, model) not in authorization.routes
        or deadline_s <= 0
    ):
        raise ValueError("invalid HARDEN review leg authority")
    lease = _lease_for(authorization)
    route = (harness, model)
    with lease.lock:
        if lease.closed or not lease.active:
            raise ValueError("HARDEN review authorization is not active")
        if lease.route_counts[route] <= 0:
            raise ValueError("HARDEN review route occurrence already consumed")
        lease.route_counts[route] -= 1
    issued = time.monotonic_ns()
    leg = ReviewLegAuthorization(
        operation=authorization.operation, purpose=authorization.purpose,
        input_sha256=authorization.input_sha256,
        instructions_sha256=authorization.instructions_sha256 or "",
        canonical_repo_sha256=authorization.canonical_repo_sha256,
        broker_contract=PARENT_UNIX_BROKER_V1, harness=harness, model=model,
        issued_monotonic_ns=issued,
        expires_monotonic_ns=issued + int(float(deadline_s) * 1_000_000_000) + _BROKER_TRANSPORT_ALLOWANCE_NS,
        _seal=_AUTHORIZATION_SEAL,
    )
    _remember_leg_claim(leg)
    return leg

# Credentials and routing selectors that can move a Claude Code process away
# from the first-party Claude.ai subscription lane.  This is deliberately
# broader than ``VENDOR_API_KEY_VARS``: the latter remains the frozen cross-
# vendor API-key map, while this set also covers helpers, gateways, and cloud
# providers that Claude Code gives precedence over subscription OAuth.
CLAUDE_SUBSCRIPTION_BLOCKED_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_FOUNDRY_RESOURCE",
    "ANTHROPIC_AWS_BASE_URL",
    "ANTHROPIC_AWS_WORKSPACE_ID",
    "AWS_BEARER_TOKEN_BEDROCK",
    "CLAUDE_CODE_API_KEY_HELPER_TTL_MS",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
    "CLAUDE_CODE_SKIP_FOUNDRY_AUTH",
    "CLAUDE_CODE_SKIP_MANTLE_AUTH",
    "CLAUDE_CODE_SKIP_VERTEX_AUTH",
)


def all_vendor_key_vars() -> tuple[str, ...]:
    """Every vendor API-key var (scrub set for a subscription seat)."""
    seen: list[str] = []
    for vars_ in VENDOR_API_KEY_VARS.values():
        for var in vars_:
            if var not in seen:
                seen.append(var)
    return tuple(seen)


def scrub_subscription_env(base_env: Mapping[str, str]) -> dict[str, str]:
    """Return a subscription-only child environment.

    All vendor API keys are removed. Claude-specific credential helpers,
    custom request headers, alternate endpoints, and cloud-provider selectors
    are removed as well so a Claude seat cannot silently escape the first-party
    subscription lane.
    """
    blocked = set(all_vendor_key_vars()) | set(CLAUDE_SUBSCRIPTION_BLOCKED_ENV_VARS)
    return {key: value for key, value in base_env.items() if key not in blocked}


# --- backing selector -------------------------------------------------------


@dataclass(frozen=True)
class BackingDecision:
    """Which transport a seat resolves to, and why. Fail-closed: an ``omnigent``
    seat whose gateway is unavailable degrades to ``skip`` (never a silent
    homebrew fallback for a breadth harness — hand-writing breadth defeats the
    Omnigent maintenance-offload, per ABDHOME non-goals)."""

    backing: str
    skip: bool = False
    reason: str = ""


def select_backing(seat: Seat, *, gateway_available: bool = True) -> BackingDecision:
    """Freeze the selector contract: honor ``seat.backing``; an ``omnigent`` seat
    with no gateway degrades skip-with-warning. ABDHOME/ABDOMNI supply the real
    availability probes; this fixes the DECISION SHAPE they return."""
    if seat.backing not in PROVIDER_BACKINGS:
        raise ValueError(f"seat.backing {seat.backing!r} not in {PROVIDER_BACKINGS}")
    if seat.backing == BACKING_OMNIGENT and not gateway_available:
        return BackingDecision(BACKING_OMNIGENT, skip=True, reason="omnigent gateway unavailable")
    return BackingDecision(seat.backing)


# --- auth enforcement (active env scrubbing) --------------------------------


def resolve_seat_env(
    seat: Seat,
    base_env: Mapping[str, str],
    *,
    allow_api_key_fallback: bool = False,
) -> dict[str, str]:
    """Reference implementation of the frozen no-silent-key env contract.

    * Always scrub EVERY vendor API-key var from a copy of ``base_env`` (the
      ``_subscription_env`` behavior — a subscription seat ends here).
    * For an ``api_key`` seat, and ONLY when the board opts in
      (``allow_api_key_fallback``), re-inject ONLY the seat vendor's key var(s)
      from ``base_env``. Any other lane / a disallowed board leaves the env
      scrubbed (fail-closed).

    Raises when a seat requests the api-key lane without the board opt-in, so a
    silent key can never slip through. Pure and side-effect-free; ABDHOME wires
    it into the subprocess/gateway env.
    """
    env = scrub_subscription_env(base_env)
    if seat.auth == AUTH_SUBSCRIPTION:
        return env
    if seat.auth == AUTH_API_KEY:
        vendor = seat_vendor_family(seat)
        if vendor == "claude" and seat.model.lower().startswith(("claude-fable-", "claude-opus-")):
            raise ValueError(
                f"seat {seat.seat_key} requires Claude Code TUI subscription auth; "
                "api_key fallback is forbidden"
            )
        if not allow_api_key_fallback:
            raise ValueError(
                f"seat {seat.seat_key} requests the api_key lane but the board did not "
                "opt in (allow_api_key_fallback=False) — never-silent-key"
            )
        for var in VENDOR_API_KEY_VARS.get(vendor, ()):  # ONLY this vendor's key(s)
            if var in base_env:
                env[var] = base_env[var]
        return env
    raise ValueError(f"unknown seat.auth {seat.auth!r}")


__all__ = [
    "PARENT_UNIX_BROKER_V1",
    "HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES",
    "harden_subscription_model",
    "harden_subscription_review_board",
    "ReviewIsolationAuthorization",
    "ReviewCompositionAuthorization",
    "ReviewLegAuthorization",
    "ParentUnixBroker",
    "prepare_review_isolation_authorization",
    "prepare_review_composition_authorization",
    "current_review_composition_authorization",
    "clear_review_composition_authorization",
    "activate_review_isolation_authorization",
    "close_review_isolation_authorization",
    "derive_review_leg_authorization",
    "revalidate_review_isolation_authorization",
    "revalidate_review_composition_authorization",
    "VENDOR_API_KEY_VARS",
    "CLAUDE_SUBSCRIPTION_BLOCKED_ENV_VARS",
    "all_vendor_key_vars",
    "scrub_subscription_env",
    "BackingDecision",
    "select_backing",
    "resolve_seat_env",
    "AUTH_SUBSCRIPTION",
    "AUTH_API_KEY",
    "BACKING_HOMEBREW",
    "BACKING_OMNIGENT",
]
