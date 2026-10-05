"""Where a jailed Claude seat's credential comes from (agent-harness#1132, plan amendment A1).

Resolved afresh at every jailed launch, in this order:

1. the **seat-token override**: the owner-only file :func:`seat_jail.claude_seat_token_path`,
   when it exists (for example, to bill a different subscription). It is expected to be a
   long-lived ``claude setup-token`` token and has no expiry metadata;
2. the **current Claude login**: only ``claudeAiOauth.accessToken`` from the CLI's own store,
   never the refresh token or anything else in the store.

The login store is the CLI's: ``$CLAUDE_CONFIG_DIR/.credentials.json`` (else
``~/.claude/.credentials.json``) on Linux, WSL and Windows, and the login Keychain on macOS.
A login token whose remaining lifetime is below the margin is never renewed here: the
harness does not run the Claude CLI for credentials (plan amendment A3). The seat waits,
reading the store read-only (:func:`await_login_margin`), for the login to be renewed by its
owner; a wait that ends short seals the seat. This module never uses a refresh token.
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
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
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
# --------------------------------------------------------------------------------------

#: The notice for an override that is not used because it is not bound to the launching
#: session's account (or either account cannot be determined).
OVERRIDE_OTHER_SUBSCRIPTION = "claude_seat_override_other_subscription"
#: The binding beside the override: ``{"schema": BINDING_SCHEMA, "account": "<id>"}``.
BINDING_SCHEMA = "seat_credential_binding.v1"
_BINDING_CAP_BYTES = 4096
_ACCOUNT_FILE_CAP_BYTES = 16 << 20


@dataclass(frozen=True)
class OverrideDecision:
    """Whether a stored override is used for this launch, and the notice when it is not."""
    applies: bool
    notice: str | None = None


class SeatCredentialAdapter(Protocol):
    """One harness's view of its seat credential. The resolver asks only these questions,
    so the rule "an override must belong to the launching session's subscription" is the
    same for every harness that has an override."""

    harness: str
    #: The notice raised when an override is present but not used.
    override_ignored_notice: str
    #: The credential sources, in precedence order (the override applies only when bound).
    sources: tuple[str, ...]

    def override_present(self) -> bool: ...

    def override_path(self) -> Path: ...

    def binding_path(self) -> Path: ...

    def override_account(self) -> str | None:
        """The account the stored override is bound to, or ``None`` when unknown."""

    def current_account(self) -> str | None:
        """The account the launching session is logged in to, or ``None`` when unknown."""


def _read_owner_only(path: Path, cap: int, *, private_dir: bool) -> bytes | None:
    """A regular file owned by the euid, not group/other-writable, read without following a
    final link (and, with ``private_dir``, in a 0700 directory). ``None`` otherwise."""
    if private_dir:
        try:
            info = os.stat(path.parent, follow_symlinks=False)
        except OSError:
            return None
        if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())):
            return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > cap
                or stat.S_IMODE(info.st_mode) & 0o022
                or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())):
            return None
        chunks, total = [], 0
        while total <= cap:
            chunk = os.read(fd, min(1 << 20, cap + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks) if total <= cap else None
    finally:
        os.close(fd)


def _account_id(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 256 and value.isprintable() else None


class ClaudeCredentialAdapter:
    """Claude: the override is ``seat-credentials/claude``, its binding
    ``seat-credentials/claude.account``; the session's account is the CLI's own
    ``oauthAccount.accountUuid`` (``$CLAUDE_CONFIG_DIR/.claude.json``, else ``~/.claude.json``),
    read without running the CLI."""

    harness = "claude"
    override_ignored_notice = OVERRIDE_OTHER_SUBSCRIPTION
    sources = (SOURCE_OVERRIDE, SOURCE_LOGIN)

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env

    def override_present(self) -> bool:
        return seat_jail.claude_seat_token_present()

    def override_path(self) -> Path:
        return seat_jail.claude_seat_token_path()

    def binding_path(self) -> Path:
        token = self.override_path()
        return token.with_name(token.name + ".account")

    def override_account(self) -> str | None:
        raw = _read_owner_only(self.binding_path(), _BINDING_CAP_BYTES, private_dir=True)
        try:
            record = json.loads(raw) if raw else None
        except (ValueError, UnicodeError, RecursionError):
            return None
        if not isinstance(record, dict) or record.get("schema") != BINDING_SCHEMA:
            return None
        return _account_id(record.get("account"))

    def current_account(self) -> str | None:
        env = os.environ if self._env is None else self._env
        directory = env.get("CLAUDE_CONFIG_DIR")
        path = Path(directory) if directory else Path.home()
        raw = _read_owner_only(path / ".claude.json", _ACCOUNT_FILE_CAP_BYTES, private_dir=False)
        try:
            config = json.loads(raw) if raw else None
        except (ValueError, UnicodeError, RecursionError):
            return None
        account = config.get("oauthAccount") if isinstance(config, dict) else None
        return _account_id(account.get("accountUuid")) if isinstance(account, dict) else None


def override_decision(adapter: SeatCredentialAdapter | None = None) -> OverrideDecision:
    """Is the stored override used for THIS launch? Only when both accounts are known and
    equal; a present override that is not used carries the adapter's notice."""
    adapter = adapter or ClaudeCredentialAdapter()
    if not adapter.override_present():
        return OverrideDecision(False)
    current, bound = adapter.current_account(), adapter.override_account()
    if current is not None and bound is not None and current == bound:
        return OverrideDecision(True)
    return OverrideDecision(False, adapter.override_ignored_notice)


class StoreRefused(RuntimeError):
    """``store_override`` refused; the message names the fix and never carries the token."""


def _write_private(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` as a new 0600 file, atomically (a temp in the same
    directory, then a rename)."""
    staged = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    except BaseException:
        try:
            os.unlink(staged)
        except OSError:
            pass
        raise


def store_override(token: bytes, adapter: SeatCredentialAdapter | None = None) -> None:
    """Store a seat-token override bound to the account the CURRENT session is logged in to
    (maintainer decision 2026-10-05: "Store command binds it").

    The directory is created 0700 (an existing one must be private and owned by the euid).
    The old binding is removed first, then the token is written, then its binding, so an
    interrupted store leaves an unbound override, which is ignored. Raises
    :class:`StoreRefused` without touching anything when the token is malformed or the
    session's account cannot be determined."""
    adapter = adapter or ClaudeCredentialAdapter()
    token = token.strip()
    if (not token or len(token) > seat_jail.TOKEN_FILE_CAP_BYTES
            or not all(0x21 <= b <= 0x7E for b in token)):
        raise StoreRefused("the token is empty, too long, or not printable ASCII")
    account = adapter.current_account()
    if account is None:
        raise StoreRefused(f"no {adapter.harness} login found to bind the token to: log in "
                           "with the subscription the token belongs to, then store it again")
    path, binding = adapter.override_path(), adapter.binding_path()
    directory = path.parent
    for parent in (directory.parent, directory):
        try:
            parent.mkdir(mode=0o700, parents=True)
        except FileExistsError:
            pass
    info = os.stat(directory, follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
            or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())):
        raise StoreRefused(f"{directory} must be a directory you own with mode 0700 "
                           f"(chmod 700 {directory})")
    try:
        os.unlink(binding)
    except FileNotFoundError:
        pass
    _write_private(path, token + b"\n")
    _write_private(binding, json.dumps({"schema": BINDING_SCHEMA, "account": account},
                                       sort_keys=True).encode("utf-8") + b"\n")


def override_present() -> bool:
    """Whether the launch uses the override: present AND bound to the launching session's
    account (the name is kept for its callers; an unbound override is not "present" to them)."""
    return override_decision().applies


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
    if decision.applies:
        return SeatCredential(seat_jail.read_claude_seat_token(), SOURCE_OVERRIDE)
    ignored = (decision.notice,) if decision.notice else ()
    if ignored:
        logging.getLogger(__name__).warning(
            "seat claude [%s]: the stored seat token is not bound to this session's account; "
            "using the login", decision.notice)
    login = read_login()
    if login is None:
        raise seat_jail.SeatSandboxRefused("claude_seat_token_missing")
    if login.expires_at is not None and login.expires_at - now() < margin_s:
        raise seat_jail.SeatSandboxRefused("claude_seat_login_token_expiring")
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
