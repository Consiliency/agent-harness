"""Per-seat filesystem jail for tooled review seats (agent-harness#1132).

A jailed seat runs its provider CLI with its full tool set, because the jail -- not the
CLI's own permission settings -- is the boundary. Outside a jail nothing changes: a seat
that is not jailed keeps the sealed inline route byte-for-byte.

This module owns the pieces that do not need a live seat:

* the notice vocabulary (``NOTICES``), rendered only from the literals below;
* the J14 seccomp filter, a static classic-BPF program for the host's own architecture;
* the J7 route decision, evaluated in a fixed order so every failure has one code;
* the Claude seat token: owner-only storage, delivery through one drained pipe, and the
  output scan for its bytes and their standard encodings;
* the J10 hardened reads: fd-relative, one component at a time, never following a link;
* the D7 Gemini credential copy;
* the jail itself: the bwrap argv, the declared environment and descriptors, and the
  profile digest that names all of it.

The subordinate seat uid (D8) lives in :mod:`phase_loop_runtime.seat_uid`; the session
keyring shim in :mod:`phase_loop_runtime.seat_keyring_exec`.
"""

from __future__ import annotations

import base64
import dataclasses
import binascii
import errno
import hashlib
import json
import logging
import os
import platform
import re
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

PROFILE_ID = "seat_jail_v1"
_LOG = logging.getLogger(__name__)

SEAT_ROOT = "/seat"
SEAT_BIN = "/seat/bin"
SEAT_TREE = "/seat/tree"
SEAT_HOME = "/seat/home"
SEAT_OUT = "/seat/out"
SEAT_REVIEW = "/seat/review"
SEAT_BUNDLE = SEAT_REVIEW + "/review-bundle.md"
SEAT_INSTRUCTIONS = SEAT_REVIEW + "/review-instructions.md"
SEAT_CLAUDE_CONFIG = SEAT_HOME + "/.claude"
# The seat's scratch (agent-harness#1147): in its home, which is on the disk-backed staging
# root. The jail's own `/tmp` is a tmpfs, so it is not the seat's TMPDIR.
SEAT_TMP_DIRNAME = ".tmp"
SEAT_TMP = SEAT_HOME + "/" + SEAT_TMP_DIRNAME

# Host layout under a leg's review dir.
HOST_TREE_DIRNAME = "reviewed-tree"
HOST_HOME_DIRNAME = "seat-home"
HOST_OUT_DIRNAME = "seat-out"
HOST_GEMINI_CONFIG_DIRNAME = "gemini-config"

# The Claude output file the seat writes and the parent reads through the J10 reader.
CLAUDE_OUTPUT_NAME = "panel-claude.txt"

# Read-only system paths (J1). On a merged-/usr host `/bin`, `/sbin` and `/lib*` are
# symlinks into `/usr`; they are recreated as the same symlinks, never bound.
SYSTEM_READONLY_PATHS: tuple[str, ...] = (
    "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32",
)
ETC_READONLY_SUBSET: tuple[str, ...] = (
    "ssl", "resolv.conf", "hosts", "nsswitch.conf", "passwd", "group", "localtime",
    "ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives",
)

# The three capabilities bwrap leaves the hand-off -- each needed by the drop and nothing
# else (plan "Seat uid", step 4).
JAIL_CAP_ADD: tuple[str, ...] = ("CAP_SETUID", "CAP_SETGID", "CAP_SETPCAP")

# Size caps for the J10 reader.
OUTPUT_READ_CAP_BYTES = 8 * 1024 * 1024
TRANSCRIPT_READ_CAP_BYTES = 64 * 1024 * 1024
TOKEN_FILE_CAP_BYTES = 16 * 1024
GEMINI_CREDENTIAL_CAP_BYTES = 64 * 1024

# The placeholder that stands for the token fd wherever an argv, environment or evidence
# record is shown. The real number is only ever in the launched process's environment.
TOKEN_FD_PLACEHOLDER = "<seat-token-fd>"
CLAUDE_TOKEN_FD_ENV = "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"


# --------------------------------------------------------------------------------------
# Notices (plan "Typed notices"). Every code below is also an exact literal in
# `panel_invoker._HARNESS_DETAIL_CODES` (F030); a test holds the two in step.
# --------------------------------------------------------------------------------------

REFUSED_PREFIX = "seat_sandbox_refused:"

NOTICES: Mapping[str, tuple[str, str, str]] = {
    "seat_sandbox_unavailable_host": (
        "inline fallback", "host capability missing",
        "install bwrap, slirp4netns and unshare; enable unprivileged user namespaces"),
    "seat_sandbox_unavailable_seat_uid": (
        "inline fallback", "no subordinate seat uid on this host",
        "root once: apt install uidmap, and usermod --add-subuids/--add-subgids for the operator"),
    "seat_sandbox_unavailable_tiocsti": (
        "inline fallback", "host allows keystroke injection",
        "kernel >= 6.2 and dev.tty.legacy_tiocsti=0"),
    "seat_sandbox_not_staged": (
        "inline fallback", "caller requested no tree", "pass a staged-tree authorization"),
    "seat_sandbox_refused:jail_build": (
        "leg refused", "jail setup failed", "report a defect"),
    "seat_sandbox_refused:namespace": (
        "leg refused", "namespace setup failed", "check slirp4netns"),
    "seat_sandbox_refused:identity": (
        "leg refused",
        "seat not provably confined (seat ids, capabilities, mountinfo, fd set, or the jail "
        "is not the qualified profile)",
        "report a defect"),
    "seat_sandbox_refused:jail_unqualified": (
        "leg refused",
        "no EC-EXECFIND-2 pass is recorded on this host for this jail's profile digest (a new "
        "host, a changed host layout, or a changed jail)",
        "run the per-host EC-EXECFIND-2 jail qualification, which records the pass at "
        "$XDG_STATE_HOME/phase-loop/seat-jail-passes/<digest>.json; or remove the seat token "
        "to use the sealed route"),
    "seat_sandbox_refused:pass_store_unsafe": (
        "leg refused",
        "the pass store or one of its parent directories is a link, not yours, "
        "other-writable, or group-writable by a group that is not your user-private group",
        "chmod go-w (or 0700) $XDG_STATE_HOME, $XDG_STATE_HOME/phase-loop and "
        "$XDG_STATE_HOME/phase-loop/seat-jail-passes; a group-writable directory is accepted "
        "only when its group is your own user-private group"),
    "seat_sandbox_refused:preseed": (
        "leg refused", "seat-home not writable", "check disk"),
    "seat_sandbox_refused:token_file_unsafe": (
        "leg refused", "seat-token file not owner-only", "chmod 600, dir 700, own it"),
    "seat_sandbox_refused:gemini_credential_unsafe": (
        "leg refused", "operator agy credential file unsafe or unreadable",
        "fix owner, mode, or re-login agy"),
    "seat_sandbox_retained_after_teardown": (
        "directory retained",
        "teardown could not remove seat-owned files, which may include the seat token",
        "run `phase-loop seat-sandbox reap`; revoke the seat token if the leg is suspect"),
    "seat_sandbox_refused:stage_not_private": (
        "leg refused", "staged tree shares an inode with a file outside the stage",
        "re-stage; report a defect in staging"),
    "seat_sandbox_refused:stage_changed": (
        "leg refused", "staged tree changed", "re-run"),
    "seat_sandbox_refused:output_unsafe": (
        "leg rejected", "seat tampered with its output", "none"),
    "seat_sandbox_egress_opt_out": (
        "ran unfiltered", "operator opt-out", "unset it on a capable host"),
    "seat_sandbox_root_fell_back": (
        "staged on fallback root", "configured root unreachable", "fix the root"),
    "seat_sandbox_root_unapplied": (
        "staged locally", "remote co-location not implemented", "none yet"),
    "seat_staging_below_floor": (
        "leg refused", "disk", "free space"),
    "seat_filesystem_unconfined": (
        "seat can read and write operator files and jailed seats' host directories",
        "not jailed yet", "agent-harness#895 follow-up"),
    "seat_tool_denied": (
        "tool use denied", "agy auto-denied a tool",
        "on the tooled profile a defect; on the sealed route expected"),
    "claude_seat_token_missing": (
        "leg refused", "no Claude login found and no seat token override; the seat does not run",
        "run `claude auth login`, then re-run"),
    "claude_seat_token_rejected": (
        "leg ended", "the seat token override was rejected (revoked or expired)",
        "store a fresh `claude setup-token` token with `phase-loop seat-sandbox store-token`, "
        "or remove the override to use your Claude login"),
    "claude_seat_token_in_output": (
        "leg rejected", "seat tried to publish its credential", "revoke the token"),
    # Not a jail fault: the jail ran, and the provider refused the seat token's subscription.
    "claude_seat_token_rate_limited": (
        "leg ended",
        "the seat token's subscription is rate- or usage-limited (the leg detail names the "
        "provider's reset time when it gives one)",
        "rotate or replace the seat token with one for another subscription, or wait for the "
        "reset"),
    # The same outcomes when the credential is the user's Claude login (plan amendment A1).
    # Maintainer ruling 2026-10-05: a seat's credential follows the launching session's
    # subscription; an override bound to another account (or to none) is not used.
    "claude_seat_override_other_subscription": (
        "seat token override ignored",
        "the stored seat token is not bound to the subscription this session is logged in to "
        "(or the binding or the session's account cannot be determined); the seat uses your "
        "login",
        "remove the override, or log in to the account it belongs to; or store a token for "
        "this account with `phase-loop seat-sandbox store-token`"),
    "claude_seat_login_rate_limited": (
        "leg ended",
        "your Claude subscription is rate- or usage-limited (the leg detail names the reset "
        "time when the provider gives one)",
        "wait for the reset, or log in to another subscription"),
    "claude_seat_login_rejected": (
        "leg ended", "the Claude login's access token was rejected", "run `claude auth login`"),
    "claude_seat_login_token_expired": (
        "leg ended", "the Claude login's access token expired during the run",
        "re-run the seat: each launch reads a fresh token"),
    # Plan amendment A2: the first-use qualification failed or could not run.
    "seat_jail_qualification_failed": (
        "leg refused",
        "this host's seat jail is not qualified: the automatic first-use qualification "
        "failed or could not run (the mode line names the reason); the seat does not run",
        "run `phase-loop seat-sandbox qualify` to see why"),
    "claude_seat_login_token_expiring": (
        "leg refused",
        "the Claude login's access token expires before the seat's deadline and was not "
        "renewed within the wait; the seat does not run",
        "run `claude auth login` (or use Claude to refresh it), then re-run"),
    "claude_seat_login_token_awaiting_refresh": (
        "waiting",
        "the Claude login's access token expires before the seat's deadline; the seat waits "
        "for it to be renewed",
        "use Claude or run `claude auth login`"),
    "claude_seat_bypass_ack_blocked": (
        "leg refused", "pre-seed stale for this CLI", "upgrade runtime"),
    "claude_tui_workspace_trust_blocked": (
        "leg refused", "pre-seed stale for this CLI", "upgrade runtime"),
    "gemini_seat_credential_missing": (
        "sealed route", "agy not logged in", "log in to agy"),
    "gemini_seat_credential_unusable": (
        "sealed route", "agy cannot run tooled on the stripped credential",
        "none until agy changes"),
    "gemini_seat_token_scope_excess": (
        "sealed route", "the stripped agy token's scopes go beyond inference",
        "maintainer ruling on the measured scopes, then re-run P4"),
    "gemini_seat_stream_split_unavailable": (
        "sealed route",
        "agy tool and subagent activity or workspace config cannot be controlled",
        "none until agy changes"),
    "gemini_seat_egress_unconfined": (
        "sealed route",
        "jail egress cannot be limited to agy's inference hosts, so the token's cloud-platform "
        "scope is not contained",
        "host-level egress filtering for the seat; then re-run the P4 containment probe"),
    "gemini_seat_token_refreshed_in_jail": (
        "sealed route", "agy obtained or refreshed a token inside the jail",
        "none until agy changes; re-run the P4 containment probe"),
    "gemini_seat_profile_unqualified": (
        "sealed route", "image not qualified for the tooled profile", "requalify"),
    "gemini_seat_token_expired": (
        "leg ended", "short-lived seat credential expired", "re-run"),
    "gemini_seat_token_in_output": (
        "leg rejected", "seat tried to publish its credential",
        "none; the copy expires on its own"),
    "gemini_seat_subagent_or_unknown_event": (
        "leg ended", "subagent or unrecorded agy activity", "none"),
    "native_seat_unavailable_heartbeat_only": (
        "seat not filled", "heartbeat cannot bind a native fill",
        "run bounded, or accept the brokered seat"),
    "under_claude_code": (
        "seat deferred to the driving session", "nested TUI unavailable",
        "fill natively or run from a plain shell"),
    "seat_prompt_over_cap": (
        "leg refused", "inline fallback cannot carry this bundle",
        "run where a jail is available"),
    "seat_identity_unverified": (
        "leg refused", "seat not provably the operator, locked down", "report a defect"),
}

NOTICE_CODES: frozenset[str] = frozenset(NOTICES)

# The leg details that mean the provider refused the seat token's subscription for a rate
# or usage limit. ``usage_limit`` and ``usage_limit (resets ...)`` are the shared tail
# classifier's (``panel_invoker._leg_failure_detail``). The ``claude_seat_*_limited`` codes
# are the Claude session give-up classes of agent-harness#1194 (still open when this was
# written); a test holds every limit code in the closed detail vocabulary to this list.
LIMIT_DETAIL_CODES: frozenset[str] = frozenset({
    "usage_limit", "claude_seat_rate_limited", "claude_seat_usage_limited",
})


def is_limit_detail(detail: object) -> bool:
    """Does this leg detail say the provider refused the seat token for a rate/usage limit?

    A detail may carry a rendered reset (``usage_limit (resets 17:00)``) or a route prefix
    (``claude_tui_pty_eof_no_output: usage_limit``); each part is compared exactly."""
    if not isinstance(detail, str):
        return False
    for part in str.__str__(detail).split(": "):
        head = part.split(" (resets ", 1)[0]
        if head in LIMIT_DETAIL_CODES:
            return True
    return False

# Codes that send a seat to the sealed route (J7 steps 0-4) rather than refusing it.
SEALED_FALLBACK_CODES: frozenset[str] = frozenset({
    "seat_sandbox_not_staged",
    "gemini_seat_credential_unusable", "gemini_seat_token_scope_excess",
    "gemini_seat_stream_split_unavailable", "gemini_seat_egress_unconfined",
    "gemini_seat_token_refreshed_in_jail",
    "seat_sandbox_unavailable_host", "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "gemini_seat_credential_missing",
    "gemini_seat_profile_unqualified",
})
#: Plan amendment A3b: a jail-eligible Claude seat that cannot run jailed is DEGRADED and
#: not run, never a toolless (sealed) substitute. ``decide_seat_route`` may still name one
#: of these on a non-jailed route; the spawn and the modes turn it into that refusal.
JAIL_NOT_RUN_CODES: frozenset[str] = frozenset({
    "claude_seat_token_missing", "seat_jail_qualification_failed",
    "claude_seat_login_token_expiring",
})


@dataclass(frozen=True)
class Notice:
    code: str
    seat_key: str
    what: str
    why: str
    fix: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "seat_key": self.seat_key, "what": self.what,
                "why": self.why, "fix": self.fix}


def render_notice(code: object, seat_key: object) -> Notice | None:
    """A notice for ``code``, from the literals above, or ``None`` for anything else.

    ``code`` is looked up, never interpreted: text that merely LOOKS like a code (a CLI
    printing ``seat_sandbox_refused:identity``) is not a key of a plain-``str`` equality
    lookup unless it is exactly one, and only the harness puts codes into evidence. The
    rendered fields are always the table's own literals.
    """
    if type(code) is not str or code not in NOTICES:
        return None
    what, why, fix = NOTICES[code]
    key = seat_key if type(seat_key) is str else ""
    return Notice(code=code, seat_key=key, what=what, why=why, fix=fix)


class SeatSandboxRefused(RuntimeError):
    """A pre-launch or runtime refusal. ``code`` is exactly one notice literal."""

    def __init__(self, code: str, message: str = "") -> None:
        if code not in NOTICES:
            raise ValueError(f"unknown seat sandbox code {code!r}")
        super().__init__(message or code)
        self.code = code


def refused(sub: str) -> str:
    code = REFUSED_PREFIX + sub
    if code not in NOTICES:
        raise ValueError(f"unknown refusal {code!r}")
    return code


# --------------------------------------------------------------------------------------
# J14: the seccomp filter.
# --------------------------------------------------------------------------------------

AUDIT_ARCH_X86_64 = 0xC000003E
AUDIT_ARCH_AARCH64 = 0xC00000B7
AUDIT_ARCH_I386 = 0x40000003
X32_SYSCALL_BIT = 0x40000000

SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000

CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
AF_ALG = 38
TIOCSTI = 0x5412
TIOCLINUX = 0x541C

_SYSCALLS: Mapping[str, Mapping[str, int]] = {
    "x86_64": {
        "unshare": 272, "clone": 56, "setns": 308, "clone3": 435, "keyctl": 250,
        "add_key": 248, "request_key": 249, "socket": 41, "socketpair": 53, "ioctl": 16,
    },
    "aarch64": {
        "unshare": 97, "clone": 220, "setns": 268, "clone3": 435, "keyctl": 219,
        "add_key": 217, "request_key": 218, "socket": 198, "socketpair": 199, "ioctl": 29,
    },
}
_AUDIT_ARCH = {"x86_64": AUDIT_ARCH_X86_64, "aarch64": AUDIT_ARCH_AARCH64}

# Classic BPF opcodes (linux/bpf_common.h).
_LD_W_ABS = 0x20
_JEQ_K = 0x15
_JGE_K = 0x35
_JSET_K = 0x45
_RET_K = 0x06

# `struct seccomp_data` offsets. Arguments are 64-bit; the low half of argument i sits at
# 16 + 8*i on a little-endian host (both supported architectures).
_OFF_NR = 0
_OFF_ARCH = 4


def _arg_low(index: int) -> int:
    return 16 + 8 * index


def host_arch() -> str:
    machine = platform.machine()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64",
            "arm64": "aarch64"}.get(machine.lower())
    if arch is None or sys.byteorder != "little":
        raise SeatSandboxRefused(refused("jail_build"),
                                 f"no seat seccomp filter for {machine}/{sys.byteorder}")
    return arch


def build_seccomp_filter(arch: str | None = None, *, key_rules: bool = True) -> bytes:
    """The J14 filter as `struct sock_filter[]` bytes, ready for `bwrap --seccomp FD`.

    Rule order is fixed: architecture (anything else is KILL_PROCESS), then -- on x86_64
    -- every x32 number (EPERM, before any per-syscall rule, because x32 calls arrive
    with the x86_64 arch value), then the per-syscall denials, then allow.

    ``key_rules=False`` is the TEST-ONLY variant that lacks the key and AF_ALG rules. It
    has its own digest, and the identity check refuses any launch whose filter digest is
    not :data:`PRODUCTION_FILTER_DIGEST`.
    """
    arch = arch or host_arch()
    if arch not in _SYSCALLS:
        raise SeatSandboxRefused(refused("jail_build"), f"no seat seccomp filter for {arch}")
    nr = _SYSCALLS[arch]
    program: list[tuple[int, object, object, int]] = []  # (code, jt, jf, k); jt/jf labels

    def emit(code: int, k: int, jt: object = 0, jf: object = 0, label: str | None = None):
        program.append((code, jt, jf, k))
        if label is not None:
            labels[label] = len(program) - 1

    labels: dict[str, int] = {}
    emit(_LD_W_ABS, _OFF_ARCH)
    emit(_JEQ_K, _AUDIT_ARCH[arch], 0, "kill")
    emit(_LD_W_ABS, _OFF_NR)
    if arch == "x86_64":
        emit(_JGE_K, X32_SYSCALL_BIT, "eperm", 0)
    emit(_JEQ_K, nr["unshare"], "ns_flags", 0)
    emit(_JEQ_K, nr["clone"], "ns_flags", 0)
    emit(_JEQ_K, nr["setns"], "eperm", 0)
    emit(_JEQ_K, nr["clone3"], "enosys", 0)
    if key_rules:
        emit(_JEQ_K, nr["keyctl"], "eperm", 0)
        emit(_JEQ_K, nr["add_key"], "eperm", 0)
        emit(_JEQ_K, nr["request_key"], "eperm", 0)
        emit(_JEQ_K, nr["socket"], "af_alg", 0)
        emit(_JEQ_K, nr["socketpair"], "af_alg", 0)
    emit(_JEQ_K, nr["ioctl"], "ioctl", 0)
    emit(_RET_K, SECCOMP_RET_ALLOW)
    emit(_LD_W_ABS, _arg_low(0), label="ns_flags")
    emit(_JSET_K, CLONE_NEWUSER | CLONE_NEWNS, "eperm", "allow")
    if key_rules:
        emit(_LD_W_ABS, _arg_low(0), label="af_alg")
        emit(_JEQ_K, AF_ALG, "eperm", "allow")
    # The kernel truncates the ioctl request to 32 bits, so only the low half is compared.
    emit(_LD_W_ABS, _arg_low(1), label="ioctl")
    emit(_JEQ_K, TIOCSTI, "eperm", 0)
    emit(_JEQ_K, TIOCLINUX, "eperm", "allow")
    emit(_RET_K, SECCOMP_RET_KILL_PROCESS, label="kill")
    emit(_RET_K, SECCOMP_RET_ERRNO | errno.EPERM, label="eperm")
    emit(_RET_K, SECCOMP_RET_ERRNO | errno.ENOSYS, label="enosys")
    emit(_RET_K, SECCOMP_RET_ALLOW, label="allow")

    out = bytearray()
    for index, (code, jt, jf, k) in enumerate(program):
        def offset(target: object) -> int:
            if isinstance(target, int):
                return target
            distance = labels[str(target)] - index - 1
            if not 0 <= distance <= 255:
                raise SeatSandboxRefused(refused("jail_build"), "seccomp jump out of range")
            return distance
        out += struct.pack("<HBBI", code, offset(jt), offset(jf), k)
    return bytes(out)


def filter_digest(program: bytes) -> str:
    return hashlib.sha256(program).hexdigest()


def production_filter_digest(arch: str | None = None) -> str:
    return filter_digest(build_seccomp_filter(arch))


# --------------------------------------------------------------------------------------
# J7 step 2: host capability, decided once before staging.
# --------------------------------------------------------------------------------------

TIOCSTI_SYSCTL = Path("/proc/sys/dev/tty/legacy_tiocsti")
BWRAP = "/usr/bin/bwrap"


def tiocsti_safe(path: Path = TIOCSTI_SYSCTL) -> bool:
    """`dev.tty.legacy_tiocsti` must be present and 0; a missing sysctl is unsafe (J11)."""
    try:
        return path.read_text(encoding="ascii").strip() == "0"
    except OSError:
        return False


def _host_capable() -> bool:
    from . import sandbox_egress

    return (
        sys.platform.startswith("linux")
        and os.access(BWRAP, os.X_OK)
        and os.access("/usr/bin/setpriv", os.X_OK)
        and os.access("/usr/bin/nsenter", os.X_OK)
        and sandbox_egress.egress_isolation_available()
    )


def seat_sandbox_capable(
    *,
    host_capable: Callable[[], bool] = _host_capable,
    tiocsti: Callable[[], bool] = tiocsti_safe,
    seat_uid_available: Callable[[], bool] | None = None,
) -> str | None:
    """``None`` when this host can run a jailed seat, else the ONE code that says why.

    Spawns ``unshare`` (through the egress probe), so it is called only after the
    public-entry authorization has been validated (EC-HARDEN-5).
    """
    if seat_uid_available is None:
        from . import seat_uid

        seat_uid_available = seat_uid.seat_uid_available
    if not host_capable():
        return "seat_sandbox_unavailable_host"
    if not tiocsti():
        return "seat_sandbox_unavailable_tiocsti"
    if not seat_uid_available():
        return "seat_sandbox_unavailable_seat_uid"
    return None


# --------------------------------------------------------------------------------------
# J7: the route decision, in a fixed order.
# --------------------------------------------------------------------------------------

JAILED_LEGS: frozenset[str] = frozenset({"claude"})
"""Legs with a jailed route in this runtime. Gemini joins only when P4 and P3 pass (L3);
codex and grok follow under agent-harness#895."""

# The recorded P4/P3 outcome for Gemini (J7 step 1). P4 found scopes beyond inference
# (`cloud-platform`, `cclog`, `experimentsandconfigs`; p4-agy-d7-credential.json). The
# maintainer ruled "prove then enable": tools only if (a) the staged copy is access-token-only
# and (b) jail egress reaches only agy's inference hosts. The containment probe
# (p4-containment.json, 2026-09-29) proved (a) and failed (b): storage, cloudresourcemanager,
# compute and iam.googleapis.com all answer from inside the jail, iam shares the inference
# host's front-end addresses, and the egress namespace filters by address only. Gemini
# stays sealed with this code; P3 was not run.
GEMINI_RECORDED_STOP: str | None = "gemini_seat_egress_unconfined"


@dataclass(frozen=True)
class SeatRoute:
    """The outcome of J7 steps 0-4. ``jailed`` or sealed; a sealed route always carries
    exactly one notice code."""

    jailed: bool
    code: str | None = None

    def __post_init__(self) -> None:
        if self.jailed and self.code is not None:
            raise ValueError("a jailed route carries no fallback code")
        if not self.jailed and self.code not in SEALED_FALLBACK_CODES | JAIL_NOT_RUN_CODES:
            raise ValueError(f"a sealed route needs a fallback code, got {self.code!r}")


def _claude_credential_present() -> bool:
    # A seat-token override or the user's Claude login (plan amendment A1).
    from .seat_credentials import claude_seat_credential_present

    return claude_seat_credential_present()


def decide_seat_route(
    leg: str,
    *,
    staged_tree_approved: bool,
    capable: Callable[[], str | None] = seat_sandbox_capable,
    claude_token_present: Callable[[], bool] | None = None,
    gemini_credential_present: Callable[[], bool] | None = None,
    gemini_qualified: Callable[[], bool] | None = None,
    gemini_recorded_stop: str | None = GEMINI_RECORDED_STOP,
) -> SeatRoute | None:
    """J7 steps 0-4. ``None`` for a leg this plan does not jail (codex, grok, ...).

    The steps run in order and the first that fails wins:

    0. no staged tree approved -> ``seat_sandbox_not_staged``; nothing else runs;
    1. a recorded Gemini route stop -> that stop's code;
    2. host capability -> ``seat_sandbox_unavailable_*``;
    3. credential presence (Claude: an override or a login) -> ``claude_seat_token_missing`` /
       ``gemini_seat_credential_missing``;
    4. Gemini tooled-profile qualification -> ``gemini_seat_profile_unqualified``.
    """
    if leg not in ("claude", "gemini"):
        return None
    if not staged_tree_approved:
        return SeatRoute(False, "seat_sandbox_not_staged")
    if leg == "gemini" and gemini_recorded_stop is not None:
        return SeatRoute(False, gemini_recorded_stop)
    code = capable()
    if code is not None:
        return SeatRoute(False, code)
    if leg == "claude":
        present = claude_token_present or _claude_credential_present
        if not present():
            return SeatRoute(False, "claude_seat_token_missing")
    else:
        if not (gemini_credential_present or gemini_operator_credential_present)():
            return SeatRoute(False, "gemini_seat_credential_missing")
        # Step 4. A leg outside JAILED_LEGS is never qualified: clearing the recorded stop
        # without also shipping the tooled profile (L3) can never jail it.
        if leg not in JAILED_LEGS or gemini_qualified is None or not gemini_qualified():
            return SeatRoute(False, "gemini_seat_profile_unqualified")
    return SeatRoute(True)


# --------------------------------------------------------------------------------------
# J10: hardened fd-relative reads, walks and teardown.
# --------------------------------------------------------------------------------------

# POSIX-only flags, looked up without failing at import: `panel_invoker` imports this module
# on every platform, and only the Linux jail ever reaches these reads (a Windows host is
# never seat-sandbox capable, so it never calls them).
_O_READ = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
_O_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class UnsafeSeatObject(OSError):
    """A seat-writable object that is not what the parent may read."""


def open_dir_nofollow(path: str | os.PathLike[str], *, dir_fd: int | None = None) -> int:
    """Open a directory without following a final symlink."""
    return os.open(path, _O_DIR, dir_fd=dir_fd)


def _components(relpath: str) -> list[str]:
    parts = [p for p in str(relpath).split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise UnsafeSeatObject(errno.EINVAL, f"not a contained relative path: {relpath!r}")
    return parts


def read_regular_file_at(root_fd: int, relpath: str, cap_bytes: int) -> bytes:
    """Read ``relpath`` under ``root_fd`` one component at a time, never following a link.

    Every intermediate component is opened ``O_DIRECTORY|O_NOFOLLOW``; the leaf
    ``O_NOFOLLOW|O_NONBLOCK`` (so a FIFO never blocks) and must pass an ``fstat``
    regular-file check and ``cap_bytes``. Anything else raises :class:`UnsafeSeatObject`.
    """
    parts = _components(relpath)
    fds: list[int] = []
    try:
        current = root_fd
        for part in parts[:-1]:
            try:
                current = os.open(part, _O_DIR, dir_fd=current)
            except OSError as exc:
                raise UnsafeSeatObject(exc.errno, f"unsafe directory component {part!r}") from exc
            fds.append(current)
        try:
            leaf = os.open(parts[-1], _O_READ, dir_fd=current)
        except OSError as exc:
            raise UnsafeSeatObject(exc.errno, f"unsafe leaf {parts[-1]!r}") from exc
        fds.append(leaf)
        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeSeatObject(errno.EINVAL, "not a regular file")
        if info.st_size > cap_bytes:
            raise UnsafeSeatObject(errno.EFBIG, "over the size cap")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(leaf, 1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > cap_bytes:
                raise UnsafeSeatObject(errno.EFBIG, "grew past the size cap")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def write_new_file_at(root_fd: int, relpath: str, data: bytes, mode: int = 0o600) -> None:
    """Create ``relpath`` under ``root_fd`` exclusively, never through a link (pre-seed)."""
    parts = _components(relpath)
    fds: list[int] = []
    try:
        current = root_fd
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            current = os.open(part, _O_DIR, dir_fd=current)
            fds.append(current)
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, mode, dir_fd=current)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def tree_manifest_sha256_at(tree_fd: int) -> str:
    """The staged-tree digest, computed fd-relatively without following any link.

    Byte-identical to :func:`review_stage.review_tree_manifest_sha256` on a stage: the
    same path set (regular files and symlinks, nothing under any ``.git`` component),
    the same fixed-width records, the executable bit by ``access(X_OK)``, and symlinks by
    their target text. A FIFO or device is skipped exactly as the path walk skips it, and
    is never opened.
    """
    records: list[tuple[str, bytes, bool, bytes]] = []

    def walk(dir_fd: int, prefix: str) -> None:
        for name in sorted(os.listdir(dir_fd)):
            if name == ".git":
                continue
            rel = f"{prefix}{name}"
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(name, dir_fd=dir_fd)
                records.append((rel, b"link", False, os.fsencode(target)))
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(name, _O_DIR, dir_fd=dir_fd)
                try:
                    walk(child, rel + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                fd = os.open(name, _O_READ, dir_fd=dir_fd)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise UnsafeSeatObject(errno.EINVAL, f"{rel!r} changed type")
                    chunks = []
                    while True:
                        chunk = os.read(fd, 1 << 16)
                        if not chunk:
                            break
                        chunks.append(chunk)
                finally:
                    os.close(fd)
                executable = os.access(name, os.X_OK, dir_fd=dir_fd, follow_symlinks=False)
                records.append((rel, b"blob", executable, b"".join(chunks)))

    walk(tree_fd, "")
    digest = hashlib.sha256()
    for rel, kind, executable, payload in sorted(records, key=lambda r: r[0]):
        digest.update(
            kind + (b"1" if executable else b"0")
            + hashlib.sha256(payload).hexdigest().encode("ascii")
            + b"%020d" % len(payload)
            + hashlib.sha256(rel.encode("utf-8")).hexdigest().encode("ascii")
        )
    return digest.hexdigest()


def tree_is_private(tree_fd: int) -> bool:
    """Every non-directory entry has ``st_nlink == 1`` (the hand-off's precondition)."""
    for name in os.listdir(tree_fd):
        info = os.stat(name, dir_fd=tree_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, _O_DIR, dir_fd=tree_fd)
            try:
                if not tree_is_private(child):
                    return False
            finally:
                os.close(child)
        elif info.st_nlink != 1:
            return False
    return True


def remove_tree_at(parent_fd: int, name: str) -> None:
    """Delete ``name`` under ``parent_fd`` recursively, never following a link (J2).

    A symlink is unlinked, never traversed, so a planted link to an outside file removes
    the link and leaves the target. Raises on the first entry that cannot be removed.
    """
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return
    child = os.open(name, _O_DIR, dir_fd=parent_fd)
    try:
        os.chmod(child, 0o700)
        for entry in os.listdir(child):
            remove_tree_at(child, entry)
    finally:
        os.close(child)
    os.rmdir(name, dir_fd=parent_fd)


# --------------------------------------------------------------------------------------
# The Claude seat token (D2).
# --------------------------------------------------------------------------------------

def state_home() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    return Path(configured) if configured and os.path.isabs(configured) else (
        Path.home() / ".local" / "state"
    )


def claude_seat_token_path() -> Path:
    return state_home() / "phase-loop" / "seat-credentials" / "claude"


def claude_seat_token_present(path: Path | None = None) -> bool:
    """J7 step 3: presence only. Hygiene is checked at read time (step 5)."""
    target = path or claude_seat_token_path()
    return os.path.lexists(target)


def _owner_only_dir(path: Path) -> bool:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0)


def read_claude_seat_token(path: Path | None = None) -> bytes:
    """Read the seat token: 0600 file in a 0700 directory, both owned by the euid.

    Opened ``O_NOFOLLOW`` and checked with ``fstat``. Any failure raises
    ``seat_sandbox_refused:token_file_unsafe``. The token is stripped of surrounding
    whitespace and must be non-empty printable ASCII.
    """
    target = path or claude_seat_token_path()
    unsafe = refused("token_file_unsafe")
    if not _owner_only_dir(target.parent):
        raise SeatSandboxRefused(unsafe)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise SeatSandboxRefused(unsafe) from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > TOKEN_FILE_CAP_BYTES):
            raise SeatSandboxRefused(unsafe)
        data = os.read(fd, TOKEN_FILE_CAP_BYTES + 1)
    finally:
        os.close(fd)
    token = data.strip()
    if not token or len(data) > TOKEN_FILE_CAP_BYTES or not all(0x21 <= b <= 0x7E for b in token):
        raise SeatSandboxRefused(unsafe)
    return token


def claude_seat_token_ready(path: Path | None = None) -> bool:
    """The jailed route's authentication proof, in place of ``_claude_subscription_auth_ok``.

    ``claude auth status`` does not validate a token (plan, measured), so the only local
    proof is that a hygienic token file exists; a rejected token is recognised at run time
    by its P2 signature (``claude_seat_token_rejected``).
    """
    try:
        read_claude_seat_token(path)
    except SeatSandboxRefused:
        return False
    return True


def token_pipe(token: bytes) -> int:
    """The token's only channel: a pipe whose read end is returned and whose write end is
    already closed. Once the CLI drains it, reopening the fd yields nothing."""
    if len(token) > 4096:  # below PIPE_BUF-sized writes on every Linux; never blocks
        raise SeatSandboxRefused(refused("token_file_unsafe"))
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, token)
    finally:
        os.close(write_fd)
    os.set_inheritable(read_fd, True)
    return read_fd


def secret_encodings(secret: bytes) -> tuple[bytes, ...]:
    """The byte strings the output scan looks for: the secret itself, and its standard,
    URL-safe and hex encodings at every alignment.

    Base64 of a substring depends on its offset mod 3, so the secret is encoded after 0, 1
    and 2 bytes of prefix and the characters that depend on the prefix are dropped; each
    residue yields one stable core that appears in ANY base64 text containing the secret
    at that alignment. Split or transformed forms still pass; D3 says so.
    """
    if not secret:
        return ()
    found: set[bytes] = {secret, binascii.hexlify(secret), binascii.hexlify(secret).upper()}
    for pad in range(3):
        encoded = base64.b64encode(b"\0" * pad + secret)
        start = (pad * 4 + 2) // 3 if pad else 0
        # Drop the trailing group that mixes with whatever follows the secret.
        end = len(encoded) - (0 if (pad + len(secret)) % 3 == 0 else 4)
        core = encoded[start:end].rstrip(b"=")
        if len(core) >= 8:
            found.add(core)
            found.add(core.replace(b"+", b"-").replace(b"/", b"_"))
    return tuple(sorted(found))


def contains_secret(data: bytes, secret: bytes) -> bool:
    return any(form in data for form in secret_encodings(secret))


# --------------------------------------------------------------------------------------
# D7: the Gemini seat credential copy.
# --------------------------------------------------------------------------------------

def gemini_operator_credential_path() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"


def gemini_operator_credential_present(path: Path | None = None) -> bool:
    return os.path.lexists(path or gemini_operator_credential_path())


def build_gemini_seat_copy(path: Path | None = None, *, keep_id_token: bool = False) -> bytes:
    """The D7 copy: the operator's agy credential with ``refresh_token`` removed (and
    ``id_token`` unless P4 shows agy needs it). Never the full file.

    Operator-file hygiene -- a symlink, the wrong owner, group/other access, over the
    cap, unparseable, or no ``access_token`` -- raises
    ``seat_sandbox_refused:gemini_credential_unsafe``.
    """
    target = path or gemini_operator_credential_path()
    unsafe = refused("gemini_credential_unsafe")
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise SeatSandboxRefused(unsafe) from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > GEMINI_CREDENTIAL_CAP_BYTES):
            raise SeatSandboxRefused(unsafe)
        raw = os.read(fd, GEMINI_CREDENTIAL_CAP_BYTES + 1)
    finally:
        os.close(fd)
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SeatSandboxRefused(unsafe) from exc
    if not isinstance(document, dict):
        raise SeatSandboxRefused(unsafe)
    token = document.get("token")
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str) \
            or not token["access_token"]:
        raise SeatSandboxRefused(unsafe)
    copy = dict(document)
    copy["token"] = {k: v for k, v in token.items() if k != "refresh_token"}
    copy.pop("refresh_token", None)
    if not keep_id_token:
        copy.pop("id_token", None)
        copy["token"].pop("id_token", None)
    return json.dumps(copy, sort_keys=True).encode("utf-8")


# --------------------------------------------------------------------------------------
# The jail (J1-J5, J11, J14).
# --------------------------------------------------------------------------------------

# The Claude pre-seed, pinned by live probe P1 (plans/evidence/seat-jail-1132/
# p1-claude-config-pty.json, Claude Code 2.1.284): an ablation showed each key suppresses
# exactly one modal -- onboarding (theme), workspace trust for /seat/tree, and the
# bypass-permissions acknowledgement -- and `lastOnboardingVersion` is not needed. A CLI
# that adds a modal still fails closed: the detector never answers one on a jailed seat.
CLAUDE_PRESEED: Mapping[str, object] = {
    "hasCompletedOnboarding": True,
    "bypassPermissionsModeAccepted": True,
    "projects": {SEAT_TREE: {"hasTrustDialogAccepted": True}},
}


@dataclass(frozen=True)
class SeatJail:
    """Everything a jailed launch needs, and nothing it may not have.

    ``process_owner`` is the bwrap argv (up to and excluding the provider argv);
    ``env`` the exact jail environment (``--clearenv`` then these); ``pass_fds`` the
    declared descriptors beyond 0-2. Host paths never appear in the provider argv.
    """

    leg: str
    process_owner: tuple[str, ...]
    path_map: Mapping[str, str]
    env: Mapping[str, str]
    pass_fds: tuple[int, ...]
    seccomp_fd: int
    profile_id: str
    profile_digest: str
    filter_digest: str
    seat_ids: tuple[int, int] | None = None
    provider_argv0: str = ""
    review_dir: str = ""
    tree_dir: str = ""
    token_fd: int | None = None
    provider_path: str = ""
    bundle_fd: int = -1
    instructions_fd: int = -1

    def redacted_owner(self) -> list[str]:
        """The owner argv with every descriptor number replaced by a placeholder, for
        evidence and logs."""
        out: list[str] = []
        fds = {str(fd) for fd in (*self.pass_fds, self.seccomp_fd)}
        for item in self.process_owner:
            out.append(TOKEN_FD_PLACEHOLDER if item in fds else item)
        return out


def _system_mounts() -> list[str]:
    args: list[str] = []
    for path in SYSTEM_READONLY_PATHS:
        if os.path.islink(path):
            args += ["--symlink", os.readlink(path), path]
        elif os.path.isdir(path):
            args += ["--ro-bind", path, path]
    # `/etc` is created explicitly world-searchable, like the seat directories: as the
    # parent of file binds bwrap would create it 0700 and owned by H-root (P5).
    args += ["--perms", "0755", "--dir", "/etc"]
    for name in ETC_READONLY_SUBSET:
        host = os.path.join("/etc", name)
        if os.path.lexists(host):
            args += ["--ro-bind", host, host]
    return args


# Placeholders that stand for the per-launch values in the CANONICAL owner argv. The
# profile digest is taken over the argv with these substituted, so it binds the ACTUAL
# policy the launch uses: an added bind, a dropped flag or a different filter changes it.
_PLACEHOLDERS = {"tree": "<tree>", "home": "<home>", "out": "<out>", "provider": "<provider>",
                 "bundle_fd": "<bundle-fd>", "instructions_fd": "<instructions-fd>",
                 "token_fd": "<token-fd>", "seccomp_fd": "<seccomp-fd>"}


def _profile_digest_of(leg: str, owner: Sequence[str], filter_sha256: str, arch: str) -> str:
    document = {"profile_id": PROFILE_ID, "leg": leg, "arch": arch, "owner": list(owner),
                "drop": [*setpriv_drop("<seat-id>"), *seat_cwd(), *seat_fd_closer("<token-fd>")],
                "filter_sha256": filter_sha256}
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode("utf-8")).hexdigest()


def jail_profile_digest(leg: str, arch: str | None = None) -> str:
    """The digest of the canonical jail for ``leg`` on this host: the production owner argv
    (placeholders for the per-launch values) and the production filter. EC-EXECFIND-2's pass
    is recorded against exactly this digest, and every launch must reproduce it."""
    arch = arch or host_arch()
    owner = _owner_argv(leg, tree=_PLACEHOLDERS["tree"], home=_PLACEHOLDERS["home"],
                        out=_PLACEHOLDERS["out"], provider=_PLACEHOLDERS["provider"],
                        bundle_fd=_PLACEHOLDERS["bundle_fd"],
                        instructions_fd=_PLACEHOLDERS["instructions_fd"],
                        token_fd=_PLACEHOLDERS["token_fd"] if leg == "claude" else None,
                        seccomp_fd=_PLACEHOLDERS["seccomp_fd"])
    return _profile_digest_of(leg, owner, production_filter_digest(arch), arch)


def installed_filter_sha256(jail: "SeatJail") -> str:
    """The digest of the bytes ACTUALLY in the jail's seccomp memfd -- what bwrap will load --
    never a stored attribute."""
    # bwrap reads the program from the descriptor's CURRENT offset, so the digest is only
    # the program bwrap loads when that offset is 0. A descriptor that has been read from, or
    # rewound anywhere else, would hand bwrap a suffix of the program: refused.
    if os.lseek(jail.seccomp_fd, 0, os.SEEK_CUR) != 0:
        raise SeatSandboxRefused(refused("identity"), "seccomp descriptor is not at offset 0")
    size = os.fstat(jail.seccomp_fd).st_size
    return filter_digest(os.pread(jail.seccomp_fd, size, 0))


def actual_profile_digest(jail: "SeatJail", arch: str | None = None) -> str:
    """The profile digest of THIS jail's real owner argv and installed filter bytes."""
    arch = arch or host_arch()
    substitute = {jail.tree_dir: _PLACEHOLDERS["tree"],
                  str(Path(jail.review_dir) / HOST_HOME_DIRNAME): _PLACEHOLDERS["home"],
                  str(Path(jail.review_dir) / HOST_OUT_DIRNAME): _PLACEHOLDERS["out"],
                  jail.provider_path: _PLACEHOLDERS["provider"],
                  str(jail.bundle_fd): _PLACEHOLDERS["bundle_fd"],
                  str(jail.instructions_fd): _PLACEHOLDERS["instructions_fd"],
                  str(jail.seccomp_fd): _PLACEHOLDERS["seccomp_fd"]}
    if jail.token_fd is not None:
        substitute[str(jail.token_fd)] = _PLACEHOLDERS["token_fd"]
    owner = [substitute.get(item, item) for item in jail.process_owner]
    return _profile_digest_of(jail.leg, owner, installed_filter_sha256(jail), arch)


def seat_env(leg: str, *, token_fd: int | None, lang: str = "C.UTF-8",
             term: str = "xterm-256color") -> dict[str, str]:
    """The exact jail environment. Non-secret values only: a token fd's NUMBER, never its
    bytes."""
    env = {
        "HOME": SEAT_HOME,
        "XDG_CONFIG_HOME": SEAT_HOME + "/.config",
        "XDG_CACHE_HOME": SEAT_HOME + "/.cache",
        "XDG_DATA_HOME": SEAT_HOME + "/.local/share",
        "XDG_STATE_HOME": SEAT_HOME + "/.local/state",
        "TMPDIR": SEAT_TMP,
        "PATH": SEAT_BIN + ":/usr/bin:/bin",
        "LANG": lang,
        "TERM": term,
        "DISABLE_AUTOUPDATER": "1",
    }
    if leg == "claude":
        env["CLAUDE_CONFIG_DIR"] = SEAT_CLAUDE_CONFIG
        env["CLAUDE_CODE_TMPDIR"] = SEAT_TMP
        if token_fd is not None:
            env[CLAUDE_TOKEN_FD_ENV] = str(token_fd)
    return env


def memfd_with(name: str, data: bytes) -> int:
    """A sealed memfd holding ``data``: neither the seat nor any same-uid process can
    change it after this returns."""
    fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.lseek(fd, 0, os.SEEK_SET)
        import fcntl

        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK
                    | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
    except BaseException:
        os.close(fd)
        raise
    os.set_inheritable(fd, True)
    return fd


def _owner_argv(leg: str, *, tree: str, home: str, out: str, provider: str, bundle_fd: str,
                instructions_fd: str, token_fd: str | None, seccomp_fd: str) -> list[str]:
    """The bwrap owner argv, as a pure function of its per-launch values, so the canonical
    profile (placeholders) and every real launch are built by the same code."""
    owner: list[str] = [
        BWRAP, "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--unshare-cgroup-try",
        # P5 (measured): bwrap run as H-root keeps EVERY capability unless told otherwise,
        # so the set is emptied first and exactly the three the drop needs are added back.
        "--cap-drop", "ALL",
        *(item for cap in JAIL_CAP_ADD for item in ("--cap-add", cap)),
        *_system_mounts(),
        # The tmpfs mounts are sticky world-writable: bwrap would make them 0755 and owned by
        # H-root, and the seat could not create its own temp files (P1: Claude EACCES).
        "--proc", "/proc", "--dev", "/dev", "--perms", "1777", "--tmpfs", "/tmp",
        "--perms", "1777", "--tmpfs", "/dev/shm",
        # Explicit, world-searchable seat directories (P5): bwrap creates the parent of a
        # FILE bind 0700 and owned by H-root, which the seat uid could not traverse.
        *(item for directory in (SEAT_ROOT, SEAT_BIN, SEAT_REVIEW)
          for item in ("--perms", "0755", "--dir", directory)),
        "--ro-bind", provider, f"{SEAT_BIN}/{leg}",
        "--perms", "0444", "--ro-bind-data", bundle_fd, SEAT_BUNDLE,
        "--perms", "0444", "--ro-bind-data", instructions_fd, SEAT_INSTRUCTIONS,
        "--bind", tree, SEAT_TREE,
        "--bind", home, SEAT_HOME,
        "--bind", out, SEAT_OUT,
        "--remount-ro", "/",
        # No `--chdir`: with no DAC capability, H-root cannot enter the seat's 0700 tree.
        # The cwd is entered after the drop, as the seat (`seat_cwd`).
        "--clearenv",
    ]
    env = seat_env(leg, token_fd=None)
    if leg == "claude" and token_fd is not None:
        env[CLAUDE_TOKEN_FD_ENV] = token_fd
    for key in sorted(env):
        owner += ["--setenv", key, env[key]]
    if leg == "gemini":
        owner.append("--new-session")
    owner += ["--seccomp", seccomp_fd]
    return owner


def build_seat_jail(
    leg: str,
    review_dir: Path,
    provider_executable: Path,
    *,
    tree: Path | None = None,
    bundle_memfd: int,
    instructions_memfd: int,
    token_fd: int | None = None,
    seat_ids: tuple[int, int] | None = None,
    arch: str | None = None,
    seccomp_program: bytes | None = None,
) -> SeatJail:
    """The bwrap owner for one jailed launch (plan "Seat jail").

    Host layout under ``review_dir``: ``seat-home/`` and ``seat-out/`` (fresh, 0700), and
    the stage -- ``tree``, by default ``review_dir/reviewed-tree/``. The bundle and instructions are sealed memfds bound
    0444 at ``/seat/review``; the provider image is bound read-only at
    ``/seat/bin/<leg>``. No ``--unshare-user`` (the D8 holder is the user namespace), no
    ``--unshare-net`` (the egress namespace is the network), no ``/run`` and no
    ``--bind / /``.
    """
    if leg not in ("claude", "gemini"):
        raise SeatSandboxRefused(refused("jail_build"), f"no jail for leg {leg!r}")
    arch = arch or host_arch()
    review_dir = Path(review_dir)
    tree = Path(tree) if tree is not None else review_dir / HOST_TREE_DIRNAME
    home = review_dir / HOST_HOME_DIRNAME
    out = review_dir / HOST_OUT_DIRNAME
    if not tree.is_dir() or tree.is_symlink():
        raise SeatSandboxRefused(refused("jail_build"), "staged tree missing")
    for directory in (home, out, home / SEAT_TMP_DIRNAME):
        try:
            os.mkdir(directory, 0o700)
        except OSError as exc:
            raise SeatSandboxRefused(refused("jail_build"), f"{directory.name}: {exc}") from exc
    provider = Path(provider_executable)
    if not provider.is_absolute() or not provider.is_file():
        raise SeatSandboxRefused(refused("jail_build"), "provider executable not found")
    program = seccomp_program if seccomp_program is not None else build_seccomp_filter(arch)
    seccomp_fd = memfd_with("seat-seccomp", program)
    seat_bin = f"{SEAT_BIN}/{leg}"
    owner = _owner_argv(leg, tree=str(tree), home=str(home), out=str(out), provider=str(provider),
                        bundle_fd=str(bundle_memfd), instructions_fd=str(instructions_memfd),
                        token_fd=None if token_fd is None else str(token_fd),
                        seccomp_fd=str(seccomp_fd))
    env = seat_env(leg, token_fd=token_fd)
    pass_fds = tuple(fd for fd in (bundle_memfd, instructions_memfd, token_fd) if fd is not None)
    jail = SeatJail(
        leg=leg,
        process_owner=tuple(owner),
        provider_path=str(provider),
        bundle_fd=bundle_memfd,
        instructions_fd=instructions_memfd,
        path_map={str(tree): SEAT_TREE, str(home): SEAT_HOME, str(out): SEAT_OUT,
                  str(provider): seat_bin},
        env=env,
        pass_fds=(*pass_fds, seccomp_fd),
        seccomp_fd=seccomp_fd,
        profile_id=PROFILE_ID,
        profile_digest="",
        filter_digest=filter_digest(program),
        seat_ids=seat_ids,
        provider_argv0=seat_bin,
        review_dir=str(review_dir),
        tree_dir=str(tree),
        token_fd=token_fd,
    )
    return dataclasses.replace(jail, profile_digest=actual_profile_digest(jail, arch))


# bwrap's own `--dev` populates these mount points (and `/dev/console` when its stdout is a
# terminal, which the pipe-attached identity probe never is).
BWRAP_DEV_MOUNTS: tuple[str, ...] = (
    "/dev/full", "/dev/null", "/dev/pts", "/dev/random", "/dev/tty", "/dev/urandom", "/dev/zero",
)
def expected_mount_points(jail: SeatJail) -> list[str]:
    """J1: the DECLARED mount set, from the profile's constants and this host's layout --
    independently of the argv the launch uses, so an extra bind in that argv is a mismatch,
    not a new expectation."""
    points = {"/", "/proc", "/dev", *BWRAP_DEV_MOUNTS, "/tmp", "/dev/shm",
              f"{SEAT_BIN}/{jail.leg}", SEAT_BUNDLE, SEAT_INSTRUCTIONS, SEAT_TREE, SEAT_HOME,
              SEAT_OUT}
    for path in SYSTEM_READONLY_PATHS:
        if os.path.isdir(path) and not os.path.islink(path):
            points.add(path)
    for name in ETC_READONLY_SUBSET:
        if os.path.lexists(os.path.join("/etc", name)):
            points.add(os.path.join("/etc", name))
    return sorted(points)


# The jailed identity probe (J6, J15): seat ids, every capability set, no-new-privs,
# seccomp mode, the open descriptors, the mount points, and whether a host marker is
# visible. Printed through the very prefix the provider uses.
JAIL_PROBE = (
    'id -u; id -g; '
    'grep -E "^(CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs|Seccomp|Seccomp_filters):" '
    '/proc/self/status; '
    # Behavioural: the J14 filter itself must refuse a nested user namespace. A seccomp mode
    # inherited from an outer sandbox shows `Seccomp: 2` without this jail's filter.
    '/usr/bin/unshare -U /bin/true 2>/dev/null && echo nested-userns-allowed '
    '|| echo nested-userns-denied; '
    # The descriptors a child inherits from the seat's shell, listed by that child: a plain
    # command, so the shell holds no pipe while it forks it. (`ls /proc/$$/fd` in a pipeline
    # raced the shell's own pipe descriptors: a spurious extra fd refused the seat.)
    "/usr/bin/python3 -I -S -c 'import os\n"
    "def ok(n):\n"
    " try: os.fstat(int(n)); return True\n"
    " except OSError: return False\n"
    "print(\" \".join(n for n in sorted(os.listdir(\"/proc/self/fd\"), key=int) if ok(n)) + \" \")'; "
    'awk "{print \\$5}" /proc/self/mountinfo | sort; '
    'if test -e "$1"; then echo host-marker-visible; else echo host-marker-hidden; fi'
)


def expected_probe_lines(jail: SeatJail) -> list[str]:
    if jail.seat_ids is None:
        raise SeatSandboxRefused(refused("identity"), "jail has no seat ids")
    uid, gid = jail.seat_ids
    fds = " ".join(str(fd) for fd in sorted({0, 1, 2, *(
        () if jail.token_fd is None else (jail.token_fd,))})) + " "
    return [str(uid), str(gid),
            *(f"{name}:\t{0:016x}" for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")),
            "NoNewPrivs:\t1", "Seccomp:\t2", f"Seccomp_filters:\t{_own_seccomp_filters() + 1}",
            "nested-userns-denied", fds, *expected_mount_points(jail), "host-marker-hidden"]


def _own_seccomp_filters() -> int:
    """How many seccomp filters the CALLING THREAD already carries -- the probe is forked from
    it and inherits them -- so the jail's own filter makes exactly one more. `thread-self`,
    not `self`: `self` is the thread-group leader, whose filters can differ."""
    try:
        for line in Path("/proc/thread-self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("Seccomp_filters:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def setpriv_drop(seat_id: int) -> list[str]:
    """Step 5 of the D8 launch order: from H-root to seat uid n with nothing left."""
    return ["/usr/bin/setpriv", "--reuid", str(seat_id), "--regid", str(seat_id),
            "--clear-groups", "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all",
            "--no-new-privs", "--"]


def seat_cwd() -> list[str]:
    """The seat enters its tree AFTER the drop, as the tree's owner (P5)."""
    return ["/usr/bin/env", f"--chdir={SEAT_TREE}", "--"]


# J3 descriptors: some bwrap versions leave their own and the data/seccomp descriptors open
# in the sandboxed process (measured on a hosted CI runner). The last step before the
# provider therefore closes every descriptor except 0-2 and the declared token fd, as the
# seat, and execs the provider. It runs /usr/bin/python3 in isolated mode with no site.
_FD_CLOSER = (
    "import os,sys\n"
    "keep={0,1,2}|{int(x) for x in sys.argv[1].split(',') if x}\n"
    "for name in os.listdir('/proc/self/fd'):\n"
    " fd=int(name)\n"
    " if fd not in keep:\n"
    "  try: os.close(fd)\n"
    "  except OSError: pass\n"
    "os.execv(sys.argv[2],sys.argv[2:])\n"
)


def seat_fd_closer(keep: "str") -> list[str]:
    """``keep``: the declared extra descriptors, comma-separated (the token fd, or empty)."""
    return ["/usr/bin/python3", "-I", "-S", "-c", _FD_CLOSER, keep]


def close_jail_fds(jail: SeatJail) -> None:
    for fd in set(jail.pass_fds):
        try:
            os.close(fd)
        except OSError:
            pass


# --------------------------------------------------------------------------------------
# EC-EXECFIND-2: a jail digest reaches the jailed route only with a recorded pass.
# --------------------------------------------------------------------------------------

def jail_pass_dir() -> Path:
    """Where THIS host's EC-EXECFIND-2 jail passes live (maintainer decision: option A).

    Per user and per host, never package data: the canonical digest binds this host's
    layout (`/lib*`, the `/etc` subset), so a pass recorded elsewhere does not apply here."""
    return state_home() / "phase-loop" / "seat-jail-passes"


def falsifier_layout_identity() -> str:
    """The identity of the EC-EXECFIND-2 falsifier-run layout (agent-harness#1163/#1164): a
    digest of the code that stages, isolates and runs a falsifier -- the staging, the
    dependency snapshot, the bounded bwrap run, the interpreter scope and the system mounts.
    A change to any of it changes the identity, so every recorded jail pass is invalidated
    until the jail falsifiers are re-run against the new layout (EC-EXECFIND-2)."""
    import inspect

    from . import falsifier, review_stage

    parts = [inspect.getsource(obj) for obj in (
        falsifier.run_finding_falsifier, review_stage.stage_review_tree,
        review_stage.run_bounded_falsifier_node, review_stage._run_bounded_falsifier_node,
        review_stage._snapshot_falsifier_dependencies, review_stage._falsifier_interpreter_scope,
        review_stage._require_single_link_files,
    )]
    parts += [repr(review_stage._FALSIFIER_SYSTEM_ROOTS), repr(review_stage._FALSIFIER_PYTHON_FLAGS),
              repr(sorted(review_stage._FALSIFIER_PYTHON_ENV.items()))]
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"execfind-falsifier-layout.v1:{digest}"

PASS_RECORD_SCHEMA = "seat_jail_pass.v1"
_PASS_RECORD_CAP = 64 * 1024
_PASS_EVIDENCE_CAP = 16 * 1024 * 1024
_MACHINE_ID = Path("/etc/machine-id")


def host_identity(path: Path = _MACHINE_ID) -> str | None:
    """sha256 of this host's machine-id (read-only), or None when there is none."""
    try:
        raw = path.read_bytes().strip()
    except OSError:
        return None
    return hashlib.sha256(raw).hexdigest() if raw else None


def _account_db():
    """``(operator passwd entry, grp.getgrgid, pwd.getpwall)``, or None without an account
    database (then no group-writable directory is ever accepted)."""
    try:
        import grp
        import pwd
    except ImportError:
        return None
    return pwd.getpwuid(os.geteuid()), grp.getgrgid, pwd.getpwall


def _operator_private_group(gid: int) -> bool:
    """Is ``gid`` the operator's user-private group (the umask-002 layout)? All of: it is the
    operator's primary gid, the group is named after the operator, it lists no other member,
    and no other account has it as its primary group. Then group-writable grants nobody else."""
    db = _account_db()
    if db is None:
        return False
    me, getgrgid, getpwall = db
    if gid != me.pw_gid:
        return False
    try:
        group = getgrgid(gid)
    except KeyError:
        return False
    if group.gr_name != me.pw_name or any(m != me.pw_name for m in group.gr_mem):
        return False
    return not any(acct.pw_gid == gid and acct.pw_uid != me.pw_uid for acct in getpwall())


def pass_store_dir_problem(path: Path) -> str | None:
    """Why ``path`` is not a directory the operator alone controls, or None when it is.

    ``"missing"`` when it does not exist; otherwise ``"not_owned"`` (not a directory owned by
    the euid -- a link is refused here), ``"other_writable"``, or ``"group_writable"`` unless
    the group is the operator's user-private group (:func:`_operator_private_group`)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "not_owned"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        return "not_owned"
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o002:
        return "other_writable"
    if mode & 0o020 and not _operator_private_group(info.st_gid):
        return "group_writable"
    return None


def _read_private_file(directory: Path, name: str, cap: int) -> bytes | None:
    """Read ``directory/name`` safely or not at all: no link, no block on a FIFO or device,
    a regular file owned by the euid, not group/other-writable, within ``cap``."""
    if "/" in name or name in ("", ".", ".."):
        return None
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(directory / name, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > cap):
            return None
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def _parse_json(data: bytes | None) -> object:
    if data is None:
        return None
    try:
        return json.loads(data)
    except (ValueError, RecursionError, MemoryError, UnicodeDecodeError):
        return None


def execfind_pass_recorded(profile_digest: str, *, root: Path | None = None,
                           layout: str | None = None, host: str | None = None) -> bool:
    """Is there a qualification of exactly this jail on THIS host from the EC-EXECFIND-2
    falsifier run? Every rejection is a plain ``False`` and nothing here blocks or raises;
    :func:`pass_record_verdict` gives the typed reason the route refuses with.

    The record ``<jail_pass_dir()>/<digest>.json`` must bind all of:
    - the jail's profile digest;
    - this host (sha256 of ``/etc/machine-id``), so a copied record does not qualify
      another host;
    - the falsifier-run layout (:func:`falsifier_layout_identity`), so a change to EXECFIND's
      staging or run invalidates every pass;
    - the run's evidence: a file in the same directory whose sha256 the record names, and
      which itself names the same digest, host, layout and a pass. The gate re-hashes it.

    The pass directory and its parents up to the state home must be real directories the
    operator alone controls (:func:`pass_store_dir_problem`): owned by the operator, never
    other-writable, and group-writable only when the group is the operator's user-private
    group (the umask-002 default). Otherwise the route refuses with
    ``seat_sandbox_refused:pass_store_unsafe``, whose notice names the chmod. Threat model: the operator's own account can forge a record,
    and is trusted to; the store defends against the seat uid (which cannot reach this
    directory, and whose files are refused by owner), stale records, other hosts, and
    accidental reuse.
    """
    # ONE fail-closed boundary around the WHOLE evaluation -- path building, opening,
    # reading, parsing, binding checks and evidence re-hashing. Any Exception is "no pass"
    # (the route then refuses with `seat_sandbox_refused:jail_unqualified` and launches
    # nothing); its class is logged and is the verdict's reason, `error:<class>`. A new failure shape therefore can never escape as an
    # uncaught error. BaseException (KeyboardInterrupt, SystemExit) is not swallowed.
    return pass_record_verdict(profile_digest, root=root, layout=layout, host=host)[0]


def pass_record_verdict(profile_digest: str, *, root: Path | None = None,
                        layout: str | None = None, host: str | None = None) -> tuple[bool, str]:
    """``(passed, reason)``. ``reason`` is ``"pass"``, one of ``no_record``,
    ``binding_mismatch``, ``evidence_mismatch``, ``store_unsafe:<problem>:<directory>``, or
    ``error:<ExceptionClass>`` -- see :func:`execfind_pass_recorded` for what must bind."""
    # ONE fail-closed boundary around the WHOLE evaluation (see execfind_pass_recorded).
    try:
        return _evaluate_pass_record(profile_digest, root=root, layout=layout, host=host)
    except Exception as exc:
        _LOG.warning("seat jail pass record rejected: %s", type(exc).__name__)
        return False, f"error:{type(exc).__name__}"


def _evaluate_pass_record(profile_digest: str, *, root: Path | None, layout: str | None,
                          host: str | None) -> tuple[bool, str]:
    if layout is None:
        layout = falsifier_layout_identity()
    host = host if host is not None else host_identity()
    if not layout or not host or not re.fullmatch(r"[0-9a-f]{64}", profile_digest or ""):
        return False, "binding_mismatch"
    base = root if root is not None else jail_pass_dir()
    chain = [base] if root is not None else [state_home(), state_home() / "phase-loop", base]
    for directory in chain:
        problem = pass_store_dir_problem(directory)
        if problem == "missing":
            return False, "no_record"
        if problem is not None:
            return False, f"store_unsafe:{problem}:{directory}"
    record = _parse_json(_read_private_file(base, f"{profile_digest}.json", _PASS_RECORD_CAP))
    if not isinstance(record, dict):
        return False, "no_record"
    bound = {"schema": PASS_RECORD_SCHEMA, "profile_digest": profile_digest, "result": "pass",
             "host_identity": host, "falsifier_layout": layout}
    if any(record.get(key) != value for key, value in bound.items()):
        return False, "binding_mismatch"
    evidence_name, evidence_sha = record.get("evidence"), record.get("evidence_sha256")
    if not isinstance(evidence_name, str) or not isinstance(evidence_sha, str):
        return False, "evidence_mismatch"
    evidence_bytes = _read_private_file(base, evidence_name, _PASS_EVIDENCE_CAP)
    if evidence_bytes is None or hashlib.sha256(evidence_bytes).hexdigest() != evidence_sha:
        return False, "evidence_mismatch"
    evidence = _parse_json(evidence_bytes)
    if isinstance(evidence, dict) and all(
            evidence.get(key) == value for key, value in bound.items() if key != "schema"):
        return True, "pass"
    return False, "evidence_mismatch"
