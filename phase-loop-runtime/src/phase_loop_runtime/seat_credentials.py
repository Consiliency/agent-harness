"""Where a jailed Claude seat's credential comes from (agent-harness#1132, plan amendment A1).

Resolved afresh at every jailed launch, in this order:

1. the **seat-token override**: the owner-only file :func:`seat_jail.claude_seat_token_path`,
   when it exists (for example, to bill a different subscription). It is expected to be a
   long-lived ``claude setup-token`` token and has no expiry metadata;
2. the **current Claude login**: only ``claudeAiOauth.accessToken`` from the CLI's own store,
   never the refresh token or anything else in the store.

The login store is the CLI's: ``$CLAUDE_CONFIG_DIR/.credentials.json`` (else
``~/.claude/.credentials.json``) on Linux, WSL and Windows, and the login Keychain on macOS.
A login token whose remaining lifetime is below the margin is refreshed on the HOST, only
through the CLI's own ``claude auth status``; if it is still short, the launch is refused
with ``claude_seat_login_token_expiring``. This module never uses a refresh token itself.
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
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from . import sandbox_policy, seat_jail

SOURCE_OVERRIDE = "seat_token"
SOURCE_LOGIN = "login"

#: Seconds; overrides the default margin (the leg's deadline).
MARGIN_ENV = "PHASE_LOOP_SEAT_LOGIN_TOKEN_MARGIN_S"
#: The margin when neither the caller nor the environment gives one.
DEFAULT_MARGIN_S = 900

_STORE_CAP_BYTES = 1 << 20
_KEYCHAIN_SERVICE = "Claude Code-credentials"
_REFRESH_TIMEOUT_S = 60


@dataclass(frozen=True)
class SeatCredential:
    token: bytes = field(repr=False)
    source: str
    #: Epoch seconds; ``None`` for the override, which carries no expiry.
    expires_at: float | None = None


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

def _refresh_parent() -> Path | None:
    """A private directory for the login refresh's working directory, chosen independently
    of the ambient temp variables: ``phase-loop/login-refresh`` under the per-user state
    root, every component created 0700 and owned by this account
    (``sandbox_policy._private``). ``None`` when it cannot be made, or when it would lie
    inside this process's working directory (a board runs from the reviewed tree)."""
    base = seat_jail.state_home()
    parent = base / "phase-loop" / "login-refresh"
    if not sandbox_policy._private(parent, base):
        return None
    try:
        here = Path.cwd().resolve()
        resolved = parent.resolve()
    except OSError:
        return None
    if resolved == here or here in resolved.parents:
        return None
    return parent


#: Why a login refresh did not run (it is never an error: the re-read decides).
REFRESH_NO_CLI = "login_refresh_no_cli"
REFRESH_NO_PRIVATE_DIR = "login_refresh_no_private_dir"
REFRESH_CONFIG_IN_WORKING_TREE = "login_refresh_config_root_in_working_tree"
REFRESH_FAILED = "login_refresh_failed"


def _inside(path: Path, here: Path) -> bool:
    return path == here or here in path.parents


def _refresh_env(base: Mapping[str, str]) -> "tuple[dict[str, str] | None, str | None]":
    """The env the refresh runs with, or ``(None, reason)``. The CLI's effective config root
    (``CLAUDE_CONFIG_DIR``, else ``$HOME/.claude``) and its credential store must not
    resolve (symlinks followed) into this process's working directory: a board runs from
    the reviewed tree, so a root there is repository-controlled. The verified roots are
    passed explicitly. ``CLAUDE_CONFIG_DIR`` is set only when it was set: setting it would
    move the CLI's global config, and on macOS its Keychain item name."""
    env = dict(base)
    try:
        here = Path.cwd().resolve()
        configured = env.get("CLAUDE_CONFIG_DIR")
        home = Path(env.get("HOME") or Path.home())
        root = Path(configured) if configured else home / ".claude"
        if not root.is_absolute():
            return None, REFRESH_CONFIG_IN_WORKING_TREE
        resolved = root.resolve()
        store = (root / ".credentials.json").resolve()
    except (OSError, RuntimeError):
        return None, REFRESH_CONFIG_IN_WORKING_TREE
    if _inside(resolved, here) or _inside(store, here):
        return None, REFRESH_CONFIG_IN_WORKING_TREE
    if configured:
        env["CLAUDE_CONFIG_DIR"] = str(resolved)
    else:
        env["HOME"] = str(home.resolve())
    return env, None


def refresh_login_via_cli(run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                          ) -> str | None:
    """Ask the CLI to bring its login up to date, on the host. Its output (which names the
    account) is discarded. Returns ``None`` when the refresh ran, else why it did not (one
    of the ``REFRESH_*`` reasons, logged); neither is an error here, the re-read decides.

    It runs from a fresh empty directory under :func:`_refresh_parent`, loads NO settings
    (``--setting-sources ""``, as the brokered seat does), and gets the verified config
    root from :func:`_refresh_env`, after the agent-harness#1147 scratch decision. The
    login store it reads and writes is the user's (``CLAUDE_CONFIG_DIR`` or ``~/.claude``)."""
    log = logging.getLogger(__name__)
    claude = shutil.which("claude")
    if claude is None:
        return REFRESH_NO_CLI
    env, refused = _refresh_env(os.environ)
    if env is None:
        log.warning("Claude login refresh not run: %s", refused)
        return refused
    parent = _refresh_parent()
    if parent is None:
        log.warning("Claude login refresh not run: %s", REFRESH_NO_PRIVATE_DIR)
        return REFRESH_NO_PRIVATE_DIR
    try:
        with tempfile.TemporaryDirectory(prefix="refresh-", dir=parent) as neutral:
            run([claude, "--setting-sources", "", "auth", "status", "--json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                timeout=_REFRESH_TIMEOUT_S, check=False, cwd=neutral,
                env=sandbox_policy.child_scratch_env(env, sandbox_policy.CHILD_SCRATCH_RELOCATE))
    except (OSError, subprocess.SubprocessError):
        return REFRESH_FAILED
    return None


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


def override_present() -> bool:
    return seat_jail.claude_seat_token_present()


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
    refresh: Callable[[], object] | None = None,
) -> SeatCredential:
    """The credential for ONE launch. Raises ``SeatSandboxRefused`` with exactly one notice
    code: ``seat_sandbox_refused:token_file_unsafe`` (an unsafe override),
    ``claude_seat_token_missing`` (neither source), or ``claude_seat_login_token_expiring``."""
    now = now or time.time
    read_login = read_login or read_login_token
    refresh = refresh or refresh_login_via_cli
    if override_present():
        return SeatCredential(seat_jail.read_claude_seat_token(), SOURCE_OVERRIDE)
    login = read_login()
    if login is None:
        raise seat_jail.SeatSandboxRefused("claude_seat_token_missing")
    if login.expires_at is not None and login.expires_at - now() < margin_s:
        refresh()
        login = read_login()
        if login is None or (login.expires_at is not None
                             and login.expires_at - now() < margin_s):
            raise seat_jail.SeatSandboxRefused("claude_seat_login_token_expiring")
    return SeatCredential(login.token, SOURCE_LOGIN, login.expires_at)
