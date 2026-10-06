"""Where a jailed Claude seat's credential comes from (agent-harness#1132, plan amendment A1).

Resolved afresh at every jailed launch, in this order:

1. the **seat-token override**: the bound record ``seat-credentials/claude.override.json``
   written by ``phase-loop seat-sandbox store-token`` (plan amendment A4), used only while the
   launching session is logged in to the account it was stored under -- so it never bills a
   different subscription from the session's. It is expected to be a long-lived
   ``claude setup-token`` token and has no expiry metadata. The store cannot verify that the
   token belongs to that account; the operator attests it by storing while logged in to it;
2. the **current Claude login**: only ``claudeAiOauth.accessToken`` from the CLI's own store,
   never the refresh token or anything else in the store.

The login store is the CLI's: ``$CLAUDE_CONFIG_DIR/.credentials.json`` (else
``~/.claude/.credentials.json``) on Linux, WSL and Windows, and the login Keychain on macOS.
A login token whose remaining lifetime is below the margin is never renewed here: the
harness does not run the Claude CLI for credentials (plan amendment A3). The seat waits,
reading the store read-only (:func:`await_login_margin`), for the login to be renewed by its
owner; a wait that ends short degrades the seat. This module never uses a refresh token.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol

from . import seat_jail

SOURCE_OVERRIDE = "seat_token"
SOURCE_LOGIN = "login"

#: Seconds; overrides the default margin (the leg's deadline).
MARGIN_ENV = "PHASE_LOOP_SEAT_LOGIN_TOKEN_MARGIN_S"
#: The margin when neither the caller nor the environment gives one.
DEFAULT_MARGIN_S = 900

_STORE_CAP_BYTES = 1 << 20
_KEYCHAIN_SERVICE = "Claude Code-credentials"
#: Plan amendment A3: how long a seat waits for a short login to be renewed (0: no wait),
#: and how often the store is re-read meanwhile.
WAIT_ENV = "PHASE_LOOP_SEAT_LOGIN_REFRESH_WAIT_S"
DEFAULT_WAIT_S = 900
POLL_ENV = "PHASE_LOOP_SEAT_LOGIN_REFRESH_POLL_S"
DEFAULT_POLL_S = 30


@dataclass(frozen=True)
class SeatCredential:
    token: bytes = field(repr=False)
    source: str
    #: Epoch seconds; ``None`` for the override, which carries no expiry.
    expires_at: float | None = None
    #: Notice codes the resolution raised without refusing (e.g. an ignored override).
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoginToken:
    token: bytes = field(repr=False)
    expires_at: float | None


# --------------------------------------------------------------------------------------
# The login store, per platform.
# --------------------------------------------------------------------------------------

def claude_config_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    configured = env.get("CLAUDE_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".claude"


def keychain_service(env: Mapping[str, str] | None = None) -> str:
    """The CLI's Keychain service name: suffixed with the first 8 hex digits of the config
    directory's sha256 when a non-default config directory is in use."""
    env = os.environ if env is None else env
    secure = env.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    if secure is not None:
        directory, default = secure, not secure
    else:
        directory, default = env.get("CLAUDE_CONFIG_DIR", ""), not env.get("CLAUDE_CONFIG_DIR")
    if default:
        return _KEYCHAIN_SERVICE
    digest = hashlib.sha256(unicodedata.normalize("NFC", directory).encode("utf-8")).hexdigest()
    return f"{_KEYCHAIN_SERVICE}-{digest[:8]}"


def _keychain_account(env: Mapping[str, str]) -> str:
    user = env.get("USER") or ""
    if not user:
        try:
            import pwd

            user = pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            user = ""
    allowed = user and all(c.isalnum() or c in "._-" for c in user)
    return user if allowed else "claude-code-user"


def _read_store_file(path: Path) -> bytes | None:
    """The file store, opened without following a final link; owned by the euid, regular,
    and not writable by anyone else. ``None`` when absent or unsuitable."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > _STORE_CAP_BYTES
                or stat.S_IMODE(info.st_mode) & 0o022
                or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())):
            return None
        return os.read(fd, _STORE_CAP_BYTES + 1)
    finally:
        os.close(fd)


def _read_store_keychain(env: Mapping[str, str],
                         run: Callable[..., subprocess.CompletedProcess]) -> bytes | None:
    security = shutil.which("security", path="/usr/bin:/bin") or "/usr/bin/security"
    try:
        done = run([security, "find-generic-password", "-a", _keychain_account(env),
                    "-s", keychain_service(env), "-w"],
                   capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout or len(done.stdout) > _STORE_CAP_BYTES:
        return None
    return bytes(done.stdout)


def read_login_store(*, platform: str | None = None, env: Mapping[str, str] | None = None,
                     run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                     ) -> bytes | None:
    """The raw store for this platform, or ``None``. Its content is never logged."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "darwin":
        return _read_store_keychain(env, run)
    return _read_store_file(claude_config_dir(env) / ".credentials.json")


def parse_login_token(raw: bytes | None) -> LoginToken | None:
    """Only ``claudeAiOauth.accessToken`` and ``expiresAt`` (epoch ms). Anything malformed is
    no login."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    if not isinstance(token, str) or not token or not all(0x21 <= ord(c) <= 0x7E for c in token):
        return None
    expires = oauth.get("expiresAt")
    if isinstance(expires, bool) or not isinstance(expires, (int, float)):
        expires_at = None
    else:
        expires_at = float(expires) / 1000.0
    return LoginToken(token.encode("ascii"), expires_at)


def read_login_token(**store_kwargs: object) -> LoginToken | None:
    return parse_login_token(read_login_store(**store_kwargs))


# --------------------------------------------------------------------------------------
# Refresh through the CLI, and the resolution order.
# --------------------------------------------------------------------------------------

def login_margin_s(deadline_s: float | None = None, env: Mapping[str, str] | None = None) -> float:
    """The lifetime a login token must still have at launch: ``MARGIN_ENV`` when set to a
    non-negative number, else the leg's deadline, else :data:`DEFAULT_MARGIN_S`."""
    env = os.environ if env is None else env
    configured = env.get(MARGIN_ENV)
    if configured:
        try:
            value = float(configured)
        except ValueError:
            value = -1.0
        if value >= 0:
            return value
    return float(deadline_s) if deadline_s else float(DEFAULT_MARGIN_S)


# --------------------------------------------------------------------------------------
# The launching session's subscription (maintainer ruling 2026-10-05): a seat's credential
# follows the subscription the session that launched the leg is logged in to. An override is
# used only when it is bound to that session's account.
#
# The token and the account it is bound to are ONE record (``<harness>.override.json``),
# written with one atomic rename and read once: the token the launch uses is the token whose
# account was checked, whatever runs concurrently. A hand-placed raw token file (the A1
# format) has no binding, so it is never used.
# --------------------------------------------------------------------------------------

#: The notice for an override that is not used because it is not bound to the launching
#: session's account (or either account cannot be determined).
OVERRIDE_OTHER_SUBSCRIPTION = "claude_seat_override_other_subscription"
#: The refusal for an override record that is not a private regular file the euid owns.
OVERRIDE_UNSAFE = "seat_sandbox_refused:token_file_unsafe"
#: The bound record: ``{"schema": RECORD_SCHEMA, "account": "<id>", "organization": "<id>",
#: "token": "<token>"}``. Maintainer ruling 2026-10-05: the override binds the account AND the
#: organization of the login it was stored under; a v1 (account-only) record binds nothing.
RECORD_SCHEMA = "seat_credential_override.v2"
_RECORD_CAP_BYTES = seat_jail.TOKEN_FILE_CAP_BYTES + 4096
_ACCOUNT_FILE_CAP_BYTES = 16 << 20
#: Every metadata and store open: never follow a final link, never block (a FIFO or device
#: is opened, then rejected as non-regular), never leak into a child.
_O_READ = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
           | getattr(os, "O_CLOEXEC", 0))


@dataclass(frozen=True)
class Identity:
    """The login a credential belongs to: its account and its organization, both known."""
    account: str
    organization: str


@dataclass(frozen=True)
class OverrideRecord:
    """One stored override as read: ``identity`` and ``token`` are ``None`` when the record's
    content is malformed or of an older schema (it then binds nothing)."""
    identity: Identity | None
    token: bytes | None = field(default=None, repr=False)

    @property
    def account(self) -> str | None:
        return self.identity.account if self.identity else None


@dataclass(frozen=True)
class OverrideDecision:
    """Whether a stored override is used for this launch. ``token`` is the exact bytes whose
    binding was checked (``applies`` only). ``notice`` is set when an override exists but is
    not used; ``refusal`` when the stored record is unsafe (the launch refuses)."""
    applies: bool
    notice: str | None = None
    token: bytes | None = field(default=None, repr=False, compare=False)
    refusal: str | None = None


class UnsafeOverride(RuntimeError):
    """The stored override record is not a private regular file the euid owns."""


class SeatCredentialAdapter(Protocol):
    """One harness's view of its seat credential. The resolver asks only these questions,
    so the rule "an override must belong to the launching session's subscription" is the
    same for every harness that has an override."""

    harness: str
    #: The notice raised when an override is present but not used.
    override_ignored_notice: str
    #: The credential sources, in precedence order (the override applies only when bound).
    sources: tuple[str, ...]

    def record_path(self) -> Path:
        """Where the bound override record lives."""

    def override_present(self) -> bool:
        """A bound record or an unbound legacy override exists (presence only)."""

    def read_override(self) -> OverrideRecord | None:
        """The bound record, read ONCE; ``None`` when there is none. Raises
        :class:`UnsafeOverride` for a record that is not a private regular file."""

    def current_identity(self) -> Identity | None:
        """The account and organization the launching session is logged in to, or ``None``
        when either is unknown."""

    def account_source(self) -> Path:
        """The file :meth:`current_identity` reads (named in a store refusal)."""


def _regular_private(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and not stat.S_IMODE(info.st_mode) & 0o022
            and (not hasattr(os, "geteuid") or info.st_uid == os.geteuid()))


def _read_fd(fd: int, cap: int) -> bytes | None:
    chunks, total = [], 0
    while total <= cap:
        chunk = os.read(fd, min(1 << 20, cap + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks) if total <= cap else None


def _private_dir(info: os.stat_result) -> bool:
    return (stat.S_ISDIR(info.st_mode) and not stat.S_IMODE(info.st_mode) & 0o077
            and (not hasattr(os, "geteuid") or info.st_uid == os.geteuid()))


def _read_owner_only(path: Path, cap: int, *, private_dir: bool) -> bytes | None:
    """A regular file owned by the euid, not group/other-writable, read without following a
    final link and without blocking (and, with ``private_dir``, in a 0700 directory).
    ``None`` otherwise."""
    if private_dir:
        try:
            if not _private_dir(os.stat(path.parent, follow_symlinks=False)):
                return None
        except OSError:
            return None
    try:
        fd = os.open(path, _O_READ)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not _regular_private(info) or info.st_size > cap:
            return None
        return _read_fd(fd, cap)
    finally:
        os.close(fd)


def _account_id(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 256 and value.isprintable() else None


def _valid_token(token: bytes) -> bool:
    return (0 < len(token) <= seat_jail.TOKEN_FILE_CAP_BYTES
            and all(0x21 <= b <= 0x7E for b in token))


def parse_override_record(raw: bytes) -> OverrideRecord:
    """The record's account and token, or an unbound record when anything is malformed."""
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return OverrideRecord(None)
    if not isinstance(record, dict) or record.get("schema") != RECORD_SCHEMA:
        return OverrideRecord(None)
    account = _account_id(record.get("account"))
    organization = _account_id(record.get("organization"))
    token = record.get("token")
    if account is None or organization is None or not isinstance(token, str):
        return OverrideRecord(None)
    try:
        token_bytes = token.encode("ascii")
    except UnicodeError:
        return OverrideRecord(None)
    if not _valid_token(token_bytes):
        return OverrideRecord(None)
    return OverrideRecord(Identity(account, organization), token_bytes)


class ClaudeCredentialAdapter:
    """Claude: the bound override is ``seat-credentials/claude.override.json``; a raw
    ``seat-credentials/claude`` (the A1 hand-placed format) is an unbound override. The
    session's account is the CLI's own ``oauthAccount.accountUuid``
    (``$CLAUDE_CONFIG_DIR/.claude.json``, else ``$HOME/.claude.json``), read without running
    the CLI. ``env`` (default: the process environment) supplies ``CLAUDE_CONFIG_DIR`` and
    ``HOME``; the override's directory always follows ``XDG_STATE_HOME`` of the process.

    On macOS the CLI's Keychain service follows ``CLAUDE_SECURESTORAGE_CONFIG_DIR`` when that
    is set, while its account file follows ``CLAUDE_CONFIG_DIR``; the CLI itself reads the
    two from those two variables, and so does this adapter."""

    harness = "claude"
    override_ignored_notice = OVERRIDE_OTHER_SUBSCRIPTION
    sources = (SOURCE_OVERRIDE, SOURCE_LOGIN)

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env

    def legacy_path(self) -> Path:
        return seat_jail.claude_seat_token_path()

    def record_path(self) -> Path:
        legacy = self.legacy_path()
        return legacy.with_name(legacy.name + ".override.json")

    def override_present(self) -> bool:
        return os.path.lexists(self.record_path()) or os.path.lexists(self.legacy_path())

    def read_override(self) -> OverrideRecord | None:
        path = self.record_path()
        if not os.path.lexists(path):
            return None
        try:
            directory = os.stat(path.parent, follow_symlinks=False)
            fd = os.open(path, _O_READ)
        except OSError as exc:
            raise UnsafeOverride(type(exc).__name__) from None
        try:
            info = os.fstat(fd)
            # Owner-only, like A1's token file: ANY group or other bit refuses (the shared
            # `_regular_private` rule, which allows a readable 0644 account file, is not
            # enough for a credential).
            if (not _private_dir(directory) or not _regular_private(info)
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > _RECORD_CAP_BYTES):
                raise UnsafeOverride("not a private regular file")
            raw = _read_fd(fd, _RECORD_CAP_BYTES)
        finally:
            os.close(fd)
        if raw is None:
            raise UnsafeOverride("too large")
        return parse_override_record(raw)

    def account_source(self) -> Path:
        env = os.environ if self._env is None else self._env
        directory = env.get("CLAUDE_CONFIG_DIR")
        if directory:
            return Path(directory) / ".claude.json"
        home = env.get("HOME")
        return (Path(home) if home else Path.home()) / ".claude.json"

    def current_identity(self) -> Identity | None:
        # Both from the SAME read of the same file: the CLI's oauthAccount.
        raw = _read_owner_only(self.account_source(), _ACCOUNT_FILE_CAP_BYTES, private_dir=False)
        try:
            config = json.loads(raw) if raw else None
        except (ValueError, UnicodeError, RecursionError):
            return None
        oauth = config.get("oauthAccount") if isinstance(config, dict) else None
        if not isinstance(oauth, dict):
            return None
        account = _account_id(oauth.get("accountUuid"))
        organization = _account_id(oauth.get("organizationUuid"))
        return Identity(account, organization) if account and organization else None


def override_decision(adapter: SeatCredentialAdapter | None = None) -> OverrideDecision:
    """Is the stored override used for THIS launch? Only when its record binds an account
    AND an organization equal to the launching session's; the decision then carries the very bytes it checked.
    A present override that is not used carries the adapter's notice; an unsafe record
    carries the refusal."""
    adapter = adapter or ClaudeCredentialAdapter()
    if SOURCE_OVERRIDE not in adapter.sources or not adapter.override_present():
        return OverrideDecision(False)
    try:
        record = adapter.read_override()
    except UnsafeOverride:
        return OverrideDecision(False, refusal=OVERRIDE_UNSAFE)
    current = adapter.current_identity()
    if (record is not None and record.identity is not None and record.token is not None
            and current is not None and record.identity == current):
        return OverrideDecision(True, token=record.token)
    return OverrideDecision(False, adapter.override_ignored_notice)


class StoreRefused(RuntimeError):
    """``store_override`` refused; the message names the fix and never carries the token."""


def _dir_problem(info: os.stat_result, *, exact_private: bool) -> str | None:
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "geteuid") and info.st_uid != os.geteuid()):
        return "is not a directory you own"
    mode = stat.S_IMODE(info.st_mode)
    if exact_private:
        return None if not mode & 0o077 else "must be mode 0700"
    if mode & 0o002:
        return "is writable by others"
    if mode & 0o020 and not seat_jail._operator_private_group(info.st_gid):
        return "is group-writable and its group is not your user-private group"
    return None


def _open_store_dir(record: Path) -> int:
    """The record's directory as a held descriptor, opened component by component from the
    state root (the root included) without following links, each component checked by ``fstat`` on the
    descriptor actually held. Raises :class:`StoreRefused`."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    root = seat_jail.state_home()
    relative = record.parent.relative_to(root).parts
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(root, flags | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise StoreRefused(
            f"{root} is a link (or not a directory): set XDG_STATE_HOME to the directory it "
            f"names ({os.path.realpath(root)}) and store again") from exc
    try:
        problem = _dir_problem(os.fstat(fd), exact_private=False)
        if problem:
            raise StoreRefused(f"{root} {problem}")
        here = root
        for index, name in enumerate(relative):
            here = here / name
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                child = os.open(name, flags | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            except OSError as exc:
                raise StoreRefused(f"{here} is not a directory you own (a link is refused)") from exc
            os.close(fd)
            fd = child
            last = index == len(relative) - 1
            problem = _dir_problem(os.fstat(fd), exact_private=last)
            if problem:
                raise StoreRefused(f"{here} {problem}" + (f" (chmod 700 {here})" if last else ""))
        return fd
    except BaseException:
        os.close(fd)
        raise


#: Whether this platform has every descriptor-relative operation the store needs (decided
#: once, at import).
_DIR_FD_STORE = bool(hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd
                     and os.rename in os.supports_dir_fd and os.mkdir in os.supports_dir_fd
                     and os.unlink in os.supports_dir_fd and os.stat in os.supports_dir_fd
                     and os.listdir in os.supports_fd)


def _sweep_stale_temps(fd: int, name: str, *, older_than_s: float = 60.0) -> None:
    """Remove temp records a killed store left behind (each may hold a token), relative to
    the held directory. A temp younger than ``older_than_s`` may belong to a running store
    and is left alone."""
    prefix, now = f".{name}.", time.time()
    for entry in os.listdir(fd):
        if not (entry.startswith(prefix) and entry.endswith(".tmp")):
            continue
        try:
            info = os.stat(entry, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and now - info.st_mtime > older_than_s:
                os.unlink(entry, dir_fd=fd)
        except OSError:
            continue


def store_override(token: bytes, adapter: SeatCredentialAdapter | None = None) -> Identity:
    """Store a seat-token override bound to the account the CURRENT session is logged in to
    (maintainer decision 2026-10-05: "Store command binds it"), and to its organization
    (maintainer ruling 2026-10-05). Returns that identity.

    The token and its account are one record, written as a new 0600 file under a random
    name and renamed into place, all relative to the held directory descriptor: a store is
    atomic, and concurrent stores leave one complete record. Raises :class:`StoreRefused`
    without writing when the token is malformed, the session's account cannot be
    determined, or the directory chain is unsafe."""
    import secrets

    if not _DIR_FD_STORE:
        raise StoreRefused("this platform cannot store the override safely "
                           "(no descriptor-relative file operations)")
    adapter = adapter or ClaudeCredentialAdapter()
    token = token.strip()
    if not _valid_token(token):
        raise StoreRefused("the token is empty, too long, or not printable ASCII")
    identity = adapter.current_identity()
    if identity is None:
        source = adapter.account_source()
        if os.path.lexists(source):
            raise StoreRefused(f"{source} names no account and organization this tool can "
                               "trust: it must be a regular file you own that only you can "
                               "write (not a link), with a login in it")
        raise StoreRefused(f"no {adapter.harness} login found to bind the token to: log in "
                           "with the subscription the token belongs to, then store it again")
    record = json.dumps({"schema": RECORD_SCHEMA, "account": identity.account,
                         "organization": identity.organization,
                         "token": token.decode("ascii")}, sort_keys=True).encode("utf-8") + b"\n"
    path = adapter.record_path()
    fd = _open_store_dir(path)
    _sweep_stale_temps(fd, path.name)
    staged = f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        out = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                      | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=fd)
        try:
            with os.fdopen(out, "wb") as handle:
                handle.write(record)
                handle.flush()
                os.fsync(handle.fileno())
            os.rename(staged, path.name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(staged, dir_fd=fd)
            except OSError:
                pass
            raise
    finally:
        os.close(fd)
    return identity


def override_status(adapter: SeatCredentialAdapter | None = None) -> dict[str, object]:
    """What the stored override is bound to and whether it applies now. Never the token."""
    adapter = adapter or ClaudeCredentialAdapter()
    session = adapter.current_identity()
    status: dict[str, object] = {
        "harness": adapter.harness, "record": str(adapter.record_path()),
        "session_account": session.account if session else None,
        "session_organization": session.organization if session else None,
        "bound_account": None, "bound_organization": None}
    try:
        record = adapter.read_override()
    except UnsafeOverride:
        status["state"] = "unsafe"
    else:
        if record is None:
            status["state"] = "unbound" if adapter.override_present() else "none"
        elif record.identity is None:
            status["state"] = "malformed"
        else:
            status.update(state="stored", bound_account=record.identity.account,
                          bound_organization=record.identity.organization)
    decision = override_decision(adapter)
    status["applies"] = decision.applies
    status["notice"] = decision.notice or decision.refusal
    return status


def ignored_override_notices(adapter: SeatCredentialAdapter | None = None) -> tuple[str, ...]:
    """The notice for an override that exists but is not used, or ``()``: carried beside any
    refusal of a seat that does not run, so the operator sees why their override did not
    apply (agent-harness#1253 board round 1)."""
    decision = override_decision(adapter)
    return (decision.notice,) if decision.notice else ()


def override_present() -> bool:
    """Whether the launch's credential is settled by the stored override: it is used (bound
    to the launching session's account) or its record is unsafe (the launch refuses). An
    unbound override is not "present" to the callers: they take the login."""
    decision = override_decision()
    return decision.applies or decision.refusal is not None


def claude_seat_credential_present(
    *, read_login: Callable[[], LoginToken | None] | None = None,
) -> bool:
    """J7 step 3: a seat-token override exists, or a Claude login is found. Presence only;
    the expiry margin is checked at launch."""
    return override_present() or (read_login or read_login_token)() is not None


def resolve_claude_seat_credential(
    margin_s: float, *,
    now: Callable[[], float] | None = None,
    read_login: Callable[[], LoginToken | None] | None = None,
) -> SeatCredential:
    """The credential for ONE launch. Raises ``SeatSandboxRefused`` with exactly one notice
    code: ``seat_sandbox_refused:token_file_unsafe`` (an unsafe override),
    ``claude_seat_token_missing`` (neither source), or ``claude_seat_login_token_expiring``
    (a login with less than ``margin_s`` left; nothing is run to renew it)."""
    now = now or time.time
    read_login = read_login or read_login_token
    decision = override_decision()
    if decision.refusal is not None:
        raise seat_jail.SeatSandboxRefused(decision.refusal)
    if decision.applies:
        # The very bytes whose binding was checked: no second read.
        return SeatCredential(decision.token, SOURCE_OVERRIDE)
    ignored = (decision.notice,) if decision.notice else ()
    if ignored:
        logging.getLogger(__name__).warning(
            "seat claude [%s]: the stored seat token is not bound to this session's account; "
            "using the login", decision.notice)
    login = read_login()
    if login is None:
        raise seat_jail.SeatSandboxRefused("claude_seat_token_missing", also=ignored)
    if login.expires_at is not None and login.expires_at - now() < margin_s:
        raise seat_jail.SeatSandboxRefused("claude_seat_login_token_expiring", also=ignored)
    return SeatCredential(login.token, SOURCE_LOGIN, login.expires_at, ignored)


# --------------------------------------------------------------------------------------
# Plan amendment A3: wait, read-only, for a short login to be renewed by its owner.
# --------------------------------------------------------------------------------------

#: The outcomes of :func:`await_login_margin`.
LOGIN_READY = "ready"          # an override, or a login already clearing the margin
LOGIN_REFRESHED = "refreshed"  # a renewed login cleared the margin during the wait
LOGIN_TIMEOUT = "timeout"      # still short when the wait ended (or no wait allowed)
LOGIN_MISSING = "missing"      # the store yielded no login (at the start or mid-wait)


def _seconds_env(name: str, default: float, env: Mapping[str, str] | None) -> float:
    env = os.environ if env is None else env
    try:
        value = float(env.get(name, ""))
    except ValueError:
        return float(default)
    return value if value >= 0 else float(default)


def login_refresh_wait_s(env: Mapping[str, str] | None = None) -> float:
    """``WAIT_ENV`` seconds when set to a non-negative number, else :data:`DEFAULT_WAIT_S`."""
    return _seconds_env(WAIT_ENV, DEFAULT_WAIT_S, env)


def login_refresh_poll_s(env: Mapping[str, str] | None = None) -> float:
    """``POLL_ENV`` seconds when set to a positive number, else :data:`DEFAULT_POLL_S`."""
    value = _seconds_env(POLL_ENV, DEFAULT_POLL_S, env)
    return value if value > 0 else float(DEFAULT_POLL_S)


def login_seconds_left(margin_s: float, *, now: Callable[[], float] | None = None,
                       read_login: Callable[[], LoginToken | None] | None = None,
                       ) -> float | None:
    """Read-only preflight: the seconds left on a login that is SHORT of ``margin_s``, or
    ``None`` when the seat needs no wait (an override, no login, no expiry, or enough)."""
    if override_present():
        return None
    login = (read_login or read_login_token)()
    if login is None or login.expires_at is None:
        return None
    left = login.expires_at - (now or time.time)()
    return left if left < margin_s else None


@dataclass(frozen=True)
class LoginWait:
    outcome: str
    waited_s: float


def await_login_margin(
    margin_s: float, *,
    max_wait_s: float,
    poll_s: float,
    wait: Callable[[float], bool],
    now: Callable[[], float] | None = None,
    monotonic: Callable[[], float] | None = None,
    read_login: Callable[[], LoginToken | None] | None = None,
) -> LoginWait:
    """Wait for the login to clear ``margin_s``, reading the store read-only and running
    nothing. ``wait(seconds)`` sleeps and returns True when the wait was cancelled, which
    raises :class:`LoginWaitCancelled`. Returns the outcome and the seconds waited."""
    now = now or time.time
    monotonic = monotonic or time.monotonic
    read_login = read_login or read_login_token
    if override_present():
        return LoginWait(LOGIN_READY, 0.0)
    start = monotonic()
    waited = False
    while True:
        login = read_login()
        if login is None:
            return LoginWait(LOGIN_MISSING, monotonic() - start)
        if login.expires_at is None or login.expires_at - now() >= margin_s:
            return LoginWait(LOGIN_REFRESHED if waited else LOGIN_READY, monotonic() - start)
        remaining = max_wait_s - (monotonic() - start)
        if remaining <= 0:
            return LoginWait(LOGIN_TIMEOUT, monotonic() - start)
        if wait(min(poll_s, remaining)):
            raise LoginWaitCancelled("review_operation_cancelled")
        waited = True


class LoginWaitCancelled(RuntimeError):
    """The board was cancelled while a seat waited for its login to be renewed."""
