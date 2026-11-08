"""The Codex seat credential copy (SEATS CODEX IF-0-CODEX-2).

The operator's Codex login is ``auth.json`` in ``$CODEX_HOME`` (else ``~/.codex``). A
jailed seat receives a narrowed copy of it at ``seat-home/.codex/auth.json``, mode 0600,
before the hand-off. The admitted login is a subscription sign-in: ``auth_mode`` is
``chatgpt``, ``OPENAI_API_KEY`` is empty and ``tokens`` is an object. The copy keeps
``auth_mode``, ``last_refresh``, a null ``OPENAI_API_KEY`` and ``tokens`` with
``access_token``, ``id_token``, ``account_id`` and an empty ``refresh_token``. Every other
key is dropped.

Three ordered checks admit a login (``subscription_login``, ``token_margin``,
``scope_ceiling``). Each judges one property and returns one code or ``None``:

* :func:`subscription_login_problem`: ``codex_seat_api_key_refused``;
* :func:`token_margin_problem`: ``codex_seat_token_expiring``;
* :func:`scope_problem`: ``codex_seat_token_scope_excess``.

The scope check decodes the access token's claims on the host and calls no issuer. A token
whose claims cannot be decoded is the scope check's refusal; the margin check leaves it to
that check. A pass means the token's scopes are no wider than the recorded baseline,
:data:`CODEX_SCOPE_CEILING`.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import stat
from typing import Mapping

from . import seat_jail


AUTH_FILE_NAME = "auth.json"
#: Where the copy lands, relative to the seat's host home (``seat-home``).
SEAT_AUTH_RELPATH = ".codex/" + AUTH_FILE_NAME
AUTH_CAP_BYTES = 64 * 1024
_ACCESS_TOKEN_CAP = 16 * 1024

#: The scopes a seat's access token may carry: the set the 0.167.0 CLI's sign-in requests.
#: SL-1.5 measured a developer login's access token inside it
#: (``plans/evidence/seat-codex/credential-scope.json``).
CODEX_SCOPE_CEILING: frozenset[str] = frozenset({
    "openid", "profile", "email", "offline_access",
    "api.connectors.read", "api.connectors.invoke",
})

#: Seconds an access token must still be valid for a seat to receive it. SL-1.5 measured
#: no renewal by the 0.167.0 CLI while its access token is valid, at any ``last_refresh``
#: age up to 29 days, and a seat's copy cannot be renewed in the jail. So the copy must
#: outlast the longest leg: the panel's wall-clock backstop
#: (``panel_invoker._LEG_TIMEOUT_MAX_S``).
CODEX_LOGIN_MIN_S: int = 1800

API_KEY_REFUSED = "codex_seat_api_key_refused"
TOKEN_EXPIRING = "codex_seat_token_expiring"
SCOPE_EXCESS = "codex_seat_token_scope_excess"
CREDENTIAL_MISSING = "codex_seat_credential_missing"

#: The ``tokens`` fields a subscription login carries and the copy keeps.
_KEPT_TOKENS = ("access_token", "id_token", "account_id")
#: The ``tokens`` fields the CLI may present to the seat as secrets.
_SECRET_TOKENS = ("access_token", "id_token")


@dataclass(frozen=True)
class CodexSeatCopy:
    """The bytes written to the seat, the secrets an output scan looks for, the digest of
    the copied ``tokens`` object and the access token's ``exp`` (epoch seconds)."""

    data: bytes = field(repr=False)
    secrets: tuple[bytes, ...] = field(repr=False)
    tokens_sha256: str
    expires_at: int


def auth_path(env: Mapping[str, str] | None = None) -> Path:
    """``$CODEX_HOME/auth.json``, else ``$HOME/.codex/auth.json`` (the account's home when
    ``HOME`` is unset), as the CLI resolves it."""
    env = os.environ if env is None else env
    codex_home = env.get("CODEX_HOME")
    if codex_home:
        return Path(os.path.abspath(codex_home)) / AUTH_FILE_NAME
    home = env.get("HOME") or pwd.getpwuid(os.geteuid()).pw_dir
    return Path(home) / ".codex" / AUTH_FILE_NAME


def present() -> bool:
    """Is there a login file to check? A link or other object is present here and refused
    when it is read."""
    return os.path.lexists(auth_path())


def _owner_uid() -> int:
    return os.geteuid()


def read_auth(env: Mapping[str, str] | None = None) -> bytes:
    """The operator's ``auth.json`` bytes.

    No file refuses ``codex_seat_credential_missing``. A link, anything but a regular file,
    a file another account owns, any group or other access, or a file over
    :data:`AUTH_CAP_BYTES` refuses ``seat_sandbox_refused:token_file_unsafe``."""
    unsafe = seat_jail.refused("token_file_unsafe")
    path = auth_path(env)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                     | getattr(os, "O_NOCTTY", 0))
    except FileNotFoundError as exc:
        raise seat_jail.SeatSandboxRefused(CREDENTIAL_MISSING) from exc
    except OSError as exc:
        raise seat_jail.SeatSandboxRefused(unsafe) from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != _owner_uid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > AUTH_CAP_BYTES):
            raise seat_jail.SeatSandboxRefused(unsafe)
        raw = os.read(fd, AUTH_CAP_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > AUTH_CAP_BYTES:
        raise seat_jail.SeatSandboxRefused(unsafe)
    return raw


def _document(raw: bytes) -> dict | None:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > AUTH_CAP_BYTES:
        return None
    try:
        value = json.loads(bytes(raw))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _login(raw: bytes) -> tuple[dict, dict] | None:
    """The document and its ``tokens`` when ``raw`` is an admitted subscription login."""
    document = _document(raw)
    if document is None or document.get("auth_mode") != "chatgpt":
        return None
    if document.get("OPENAI_API_KEY") not in (None, ""):
        return None
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        return None
    if not all(isinstance(tokens.get(name), str) and tokens[name] for name in _KEPT_TOKENS):
        return None
    if not isinstance(document.get("last_refresh"), str):
        return None
    return document, tokens


def _claims(raw: bytes) -> dict | None:
    """The access token's claims, decoded without verifying anything, or ``None``."""
    document = _document(raw)
    tokens = document.get("tokens") if document is not None else None
    token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token or len(token) > _ACCESS_TOKEN_CAP:
        return None
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    payload = parts[1]
    try:
        decoded = base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_",
                                   validate=True)
        claims = json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def _expiry(claims: dict) -> int | None:
    exp = claims.get("exp")
    if type(exp) not in (int, float) or not math.isfinite(exp):
        return None
    return math.floor(exp)


def _scopes(claims: dict) -> frozenset[str] | None:
    """The scopes the token states in ``scp`` (a list) or ``scope`` (a string), or
    ``None`` when it states none or states them in another shape."""
    found: set[str] = set()
    stated = False
    if "scp" in claims:
        scp = claims["scp"]
        if not isinstance(scp, list) or not all(isinstance(item, str) for item in scp):
            return None
        found.update(scp)
        stated = True
    if "scope" in claims:
        scope = claims["scope"]
        if not isinstance(scope, str):
            return None
        found.update(scope.split())
        stated = True
    return frozenset(found) if stated else None


def subscription_login_problem(raw: bytes) -> str | None:
    """``codex_seat_api_key_refused`` unless ``raw`` is a subscription sign-in: ``auth_mode``
    ``chatgpt``, an empty ``OPENAI_API_KEY``, a ``tokens`` object with the kept fields and
    a ``last_refresh``."""
    return None if _login(raw) is not None else API_KEY_REFUSED


def token_margin_problem(raw: bytes, *, now: float) -> str | None:
    """``codex_seat_token_expiring`` when the access token is valid for less than
    :data:`CODEX_LOGIN_MIN_S` after ``now``, or states no expiry. Claims that cannot be
    decoded are left to :func:`scope_problem`, which refuses them."""
    claims = _claims(raw)
    if claims is None:
        return None
    expires_at = _expiry(claims)
    if expires_at is None or expires_at - now < CODEX_LOGIN_MIN_S:
        return TOKEN_EXPIRING
    return None


def scope_problem(raw: bytes) -> str | None:
    """``codex_seat_token_scope_excess`` unless the access token's claims decode on the host
    and state scopes inside :data:`CODEX_SCOPE_CEILING`. No issuer is called."""
    claims = _claims(raw)
    scopes = _scopes(claims) if claims is not None else None
    if scopes is None or not scopes <= CODEX_SCOPE_CEILING:
        return SCOPE_EXCESS
    return None


def _tokens_sha256(tokens: object) -> str:
    canonical = json.dumps(tokens, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_seat_copy(raw: bytes) -> CodexSeatCopy:
    """The seat's copy of an admitted login.

    A login that is not a subscription sign-in refuses ``codex_seat_api_key_refused``; one
    whose scopes the host cannot show to be inside the baseline refuses
    ``codex_seat_token_scope_excess``; one with no readable expiry refuses
    ``codex_seat_token_expiring``. The margin against the clock is
    :func:`token_margin_problem`'s, checked where the copy is used."""
    login = _login(raw)
    if login is None:
        raise seat_jail.SeatSandboxRefused(API_KEY_REFUSED)
    if scope_problem(raw) is not None:
        raise seat_jail.SeatSandboxRefused(SCOPE_EXCESS)
    expires_at = _expiry(_claims(raw) or {})
    if expires_at is None:
        raise seat_jail.SeatSandboxRefused(TOKEN_EXPIRING)
    document, tokens = login
    copied_tokens = {name: tokens[name] for name in _KEPT_TOKENS}
    copied_tokens["refresh_token"] = ""
    copy = {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "last_refresh": document["last_refresh"],
        "tokens": copied_tokens,
    }
    return CodexSeatCopy(
        data=json.dumps(copy, sort_keys=True, indent=2).encode("utf-8"),
        secrets=tuple(tokens[name].encode("utf-8") for name in _SECRET_TOKENS),
        tokens_sha256=_tokens_sha256(copied_tokens),
        expires_at=expires_at,
    )


def tokens_changed(copy: CodexSeatCopy, observed: bytes) -> bool:
    """Does the seat's ``auth.json``, read back before teardown, carry other tokens than
    the copy did? Anything that is not a readable ``tokens`` object counts as changed."""
    if not isinstance(copy, CodexSeatCopy):
        raise TypeError("copy must be a CodexSeatCopy")
    document = _document(observed)
    tokens = document.get("tokens") if document is not None else None
    if not isinstance(tokens, dict):
        return True
    return _tokens_sha256(tokens) != copy.tokens_sha256


def install_seat_copy(home_fd: int, copy: CodexSeatCopy) -> None:
    """Create ``.codex/auth.json`` under the seat's host home, mode 0600, never through a
    link and never over an existing file."""
    if not isinstance(copy, CodexSeatCopy):
        raise TypeError("copy must be a CodexSeatCopy")
    seat_jail.write_new_file_at(home_fd, SEAT_AUTH_RELPATH, copy.data, 0o600)


__all__ = [
    "AUTH_CAP_BYTES", "CODEX_LOGIN_MIN_S", "CODEX_SCOPE_CEILING", "CodexSeatCopy",
    "SEAT_AUTH_RELPATH", "auth_path", "build_seat_copy", "install_seat_copy", "present",
    "read_auth", "scope_problem", "subscription_login_problem", "token_margin_problem",
    "tokens_changed",
]
