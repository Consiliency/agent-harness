"""The jailed Grok seat's credential staging (SEATS GROK IF-0-GROK-1 "Credential").

The operator's Grok login is ``$HOME/.grok/auth.json`` plus ``$HOME/.grok/agent_id``. The
jailed seat never sees that store. Per launch, before the hand-off, the launch site calls
:func:`stage_grok_seat_credential`, which writes the staged read-only ``.grok`` directory
``<review_dir>/grok-config/`` of the jail contract
(``plans/artifacts/grok-jail-tool-surface-contract-v1.md`` section 2.3): the 424-byte seat
config, the access-only copy of ``auth.json``, ``agent_id``, the empty ``logs/`` and
``sessions/`` mount points and the two empty lock-file mount points. Files are mode 0444,
directories 0555, all owned by the operator; the dropped seat UID reads them as "other".
The profile (SL-2) binds the directory read-only at ``/seat/home/.grok``.

**The subscription discriminator.** A store is admitted only when it shows the client's
sign-in shape and nothing else: exactly one credential scope, the sign-in issuer
:data:`SIGN_IN_SCOPE` (where the client keeps the bearer it sends to the subscription
inference proxy), whose ``key`` is a text bearer of at least 8 characters that is not in
the API-key form (:data:`API_KEY_PREFIX`), and no API-key field anywhere in the store.
Anything else, including a second scope or a malformed entry, is ambiguous and refuses
``grok_seat_credential_refused``. The marker is decided from the store shape offline; the
pre-grant reader of the jail contract section 7.2 refines it on the owner's fresh sign-in.

**Expiry.** The entry's ``expires_at`` must parse (an aware ISO 8601 time, or epoch
seconds or milliseconds) and the remaining lifetime must exceed ``margin_s`` (the leg
deadline plus 300 s, supplied by the caller), else ``grok_seat_token_expired``. A seat
never renews (agent-harness#1289).

**Scan values.** :class:`GrokSeatCredential` carries, from the exact projected bytes, every
secret value of ``panel_invoker._seat_secret_values`` (at least 8 characters) and each
value's last 12 characters, in memory only (:class:`ScanValues` refuses to be pickled,
copied or encoded).

**The seat config's byte source.** :func:`seat_config_bytes` takes
``grok_tool_surface.seat_config()`` once E8-A has put that function on main, and until then
the literal bytes of erratum 8 r3 (the gating input this lane names). Either way the bytes
must hash to :data:`SEAT_CONFIG_SHA256` or staging refuses before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _dt
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import stat
import time
from typing import Iterable, Iterator

from . import seat_jail


#: The staged directory's fixed name inside the review directory (jail contract 2.3).
HOST_GROK_CONFIG_DIRNAME = "grok-config"
STORE_DIRNAME = ".grok"
AUTH_FILE_NAME = "auth.json"
AGENT_ID_FILE_NAME = "agent_id"
CONFIG_FILE_NAME = "config.toml"
#: The writable entries' mount points: empty directories and empty lock files.
MOUNT_POINT_DIRS = ("logs", "sessions")
MOUNT_POINT_FILES = (".config-init.lock", "managed_config.lock")
#: Every entry the staged directory holds, and nothing else.
STAGED_ENTRIES = frozenset({CONFIG_FILE_NAME, AUTH_FILE_NAME, AGENT_ID_FILE_NAME,
                            *MOUNT_POINT_DIRS, *MOUNT_POINT_FILES})

AUTH_CAP_BYTES = 64 * 1024
AGENT_ID_CAP_BYTES = 4096
#: The after-check reads at most this much of one file (credential stores are small); a
#: larger file is a finding, not a skip.
_AFTER_READ_CAP = 1024 * 1024
_AFTER_MAX_ENTRIES = 100_000
_AFTER_MAX_DEPTH = 64

#: The pinned seat config (plan IF-0-GROK-1; TS contract erratum 8 r3 item 1a).
SEAT_CONFIG_SHA256 = "2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780"

#: Erratum 8 r3's 424 bytes, transcribed verbatim. E8-A switch: once
#: ``grok_tool_surface.seat_config`` is on main, :func:`seat_config_bytes` uses it and this
#: transcription is only the fallback; SL-3 asserts the two are equal.
_ERRATUM8_SEAT_CONFIG = (
    b'[model."grok-4.7"]\n'
    b'model = "grok-4.7"\n'
    b'name = "grok-4.7 (pinned local entry)"\n'
    b'base_url = "https://cli-chat-proxy.grok.com/v1"\n'
    b'api_backend = "chat_completions"\n'
    b'\n'
    b'[[model."grok-4.7".reasoning_efforts]]\n'
    b'value = "low"\n'
    b'label = "Low Effort"\n'
    b'\n'
    b'[[model."grok-4.7".reasoning_efforts]]\n'
    b'value = "medium"\n'
    b'label = "Medium Effort"\n'
    b'\n'
    b'[[model."grok-4.7".reasoning_efforts]]\n'
    b'value = "high"\n'
    b'label = "High Effort"\n'
    b'\n'
    b'[features]\n'
    b'remote_fetch = false\n'
)

#: The client's sign-in scope: the store key under which it keeps its session bearer.
SIGN_IN_SCOPE = "https://accounts.x.ai/sign-in"
#: The console API-key form, never admitted as a seat credential.
API_KEY_PREFIX = "xai-"
#: Field names (lower case, ``_`` and ``-`` removed) that carry or select an API key.
_API_KEY_FIELDS = frozenset({"apikey", "xaiapikey", "envkey"})

CREDENTIAL_MISSING = "grok_seat_credential_missing"
CREDENTIAL_REFUSED = "grok_seat_credential_refused"
TOKEN_EXPIRED = "grok_seat_token_expired"
REFRESHED_IN_JAIL = "grok_seat_token_refreshed_in_jail"
STORE_UNSAFE = "seat_profile_unavailable"
_REFUSAL_CODES = frozenset({CREDENTIAL_MISSING, CREDENTIAL_REFUSED, TOKEN_EXPIRED,
                            STORE_UNSAFE})

_O_READ = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
           | getattr(os, "O_NOCTTY", 0))
_O_DIR = seat_jail._O_DIR


class GrokCredentialRefused(seat_jail.SeatSandboxRefused):
    """A staging refusal: one of the three Grok credential codes, or
    ``seat_profile_unavailable`` for an unsafe store or staging target."""

    def __init__(self, code: str, message: str = "") -> None:
        if code not in _REFUSAL_CODES:
            raise ValueError(f"not a grok credential refusal: {code!r}")
        super().__init__(code, message)


class ScanValues:
    """The secret values an output scan looks for, held in memory only. Iterable and
    sized; it cannot be pickled, copied or JSON-encoded, and its repr shows no value."""

    __slots__ = ("_values",)

    def __init__(self, values: Iterable[bytes]) -> None:
        collected: dict[bytes, None] = {}
        for value in values:
            if not isinstance(value, bytes):
                raise TypeError("scan values are bytes")
            collected[value] = None
        object.__setattr__(self, "_values", tuple(collected))

    def __setattr__(self, name, value):  # noqa: ANN001 - immutable
        raise AttributeError("scan values are immutable")

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, item: object) -> bool:
        return item in self._values

    def __repr__(self) -> str:
        return f"<ScanValues: {len(self._values)} redacted>"

    def _refuse(self, *_args, **_kwargs):
        raise TypeError("grok seat scan values are held in memory only")

    __reduce__ = __reduce_ex__ = __getstate__ = __copy__ = __deepcopy__ = _refuse


@dataclass(frozen=True)
class GrokSeatCredential:
    """The staged directory, the scan values, the digest of the two staged credential
    files (:func:`credential_digest`) and the bearer's expiry (epoch seconds)."""

    config_dir: Path
    scan_values: ScanValues = field(repr=False, compare=False)
    digest: str
    expires_at: int


# --------------------------------------------------------------------------------------
# The seat config.
# --------------------------------------------------------------------------------------

def seat_config_bytes() -> bytes:
    """The jailed seat's ``config.toml``: E8-A's ``grok_tool_surface.seat_config()`` when it
    exists, else erratum 8 r3's transcription. Bytes that miss :data:`SEAT_CONFIG_SHA256`
    refuse ``seat_profile_unavailable``."""
    from . import grok_tool_surface

    source = getattr(grok_tool_surface, "seat_config", None)
    data = source() if callable(source) else _ERRATUM8_SEAT_CONFIG
    if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != SEAT_CONFIG_SHA256:
        raise GrokCredentialRefused(STORE_UNSAFE, "the grok seat config misses its pin")
    return data


# --------------------------------------------------------------------------------------
# The operator's store.
# --------------------------------------------------------------------------------------

def _operator_home() -> Path:
    home = os.environ.get("HOME")
    return Path(home) if home else Path(pwd.getpwuid(os.geteuid()).pw_dir)


def _owner_uid() -> int:
    return os.geteuid()


def grok_seat_credential_present() -> bool:
    """Is there a login file to check? Reads no secret: a link or other object is present
    here and refused when it is staged."""
    return os.path.lexists(_operator_home() / STORE_DIRNAME / AUTH_FILE_NAME)


def _read_store_file(dir_fd: int, name: str, cap: int, forbidden_mode: int) -> bytes:
    try:
        fd = os.open(name, _O_READ, dir_fd=dir_fd)
    except FileNotFoundError as exc:
        raise GrokCredentialRefused(CREDENTIAL_MISSING) from exc
    except OSError as exc:
        raise GrokCredentialRefused(STORE_UNSAFE) from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != _owner_uid()
                or stat.S_IMODE(info.st_mode) & forbidden_mode or info.st_size > cap):
            raise GrokCredentialRefused(STORE_UNSAFE)
        chunks = []
        remaining = cap + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) > cap:
        raise GrokCredentialRefused(STORE_UNSAFE)
    return data


def _read_store() -> tuple[bytes, bytes]:
    """``(auth.json, agent_id)`` from the operator's ``.grok``, never through a link.

    No store, no ``auth.json`` or no (or an empty) ``agent_id`` refuses
    ``grok_seat_credential_missing``. A linked or foreign-owned ``.grok`` or file, a
    ``.grok`` writable by others, an ``auth.json`` with any group or other access, an
    ``agent_id`` writable by others, anything but a regular file, or a file over its cap
    refuses ``seat_profile_unavailable``."""
    try:
        dir_fd = os.open(_operator_home() / STORE_DIRNAME, _O_DIR)
    except FileNotFoundError as exc:
        raise GrokCredentialRefused(CREDENTIAL_MISSING) from exc
    except OSError as exc:
        raise GrokCredentialRefused(STORE_UNSAFE) from exc
    try:
        info = os.fstat(dir_fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != _owner_uid()
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise GrokCredentialRefused(STORE_UNSAFE)
        auth = _read_store_file(dir_fd, AUTH_FILE_NAME, AUTH_CAP_BYTES, 0o077)
        agent_id = _read_store_file(dir_fd, AGENT_ID_FILE_NAME, AGENT_ID_CAP_BYTES, 0o022)
    finally:
        os.close(dir_fd)
    if not agent_id:
        raise GrokCredentialRefused(CREDENTIAL_MISSING)
    return auth, agent_id


def _normalised(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "")


def _has_api_key_field(value: object) -> bool:
    if isinstance(value, dict):
        return any((isinstance(key, str) and _normalised(key) in _API_KEY_FIELDS)
                   or _has_api_key_field(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_api_key_field(item) for item in value)
    return False


class _DuplicateMember(ValueError):
    """A JSON object repeats a member name: a later value would hide an earlier one."""


def _unique_members(pairs: list[tuple[str, object]]) -> dict:
    document: dict = {}
    for name, value in pairs:
        if name in document:
            raise _DuplicateMember("a JSON object repeats a member name")
        document[name] = value
    return document


def _strict_json(data: bytes) -> object:
    """``json.loads`` refusing a repeated member name at any object depth
    (:class:`_DuplicateMember`)."""
    return json.loads(data, object_pairs_hook=_unique_members)


def _sign_in_entry(raw: bytes) -> tuple[dict, dict] | None:
    """The store document and its sign-in entry when ``raw`` shows the positive
    subscription marker, else ``None``. A repeated member name at any depth, and depth
    exhaustion while decoding or walking the store, show no marker."""
    try:
        document = _strict_json(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    if not isinstance(document, dict) or list(document) != [SIGN_IN_SCOPE]:
        return None
    entry = document[SIGN_IN_SCOPE]
    if not isinstance(entry, dict):
        return None
    bearer = entry.get("key")
    if not isinstance(bearer, str) or len(bearer) < 8 or bearer.startswith(API_KEY_PREFIX):
        return None
    try:
        if _has_api_key_field(document):
            return None
    except RecursionError:
        return None
    return document, entry


def _expiry(value: object) -> int | None:
    """Epoch seconds from an aware ISO 8601 text, or epoch seconds or milliseconds."""
    if type(value) in (int, float):
        if not math.isfinite(value):
            return None
        if 1e9 <= value < 1e11:
            return math.floor(value)
        if 1e12 <= value < 1e14:
            return math.floor(value / 1000)
        return None
    if isinstance(value, str) and 0 < len(value) <= 64:
        text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        try:
            moment = _dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        if moment.tzinfo is None or moment.utcoffset() is None:
            return None
        return math.floor(moment.timestamp())
    return None


def _checked_margin(margin_s: object) -> float:
    if type(margin_s) not in (int, float) or not math.isfinite(margin_s) or margin_s < 0:
        raise ValueError("margin_s must be a finite, non-negative number of seconds")
    return float(margin_s)


def _projected_copy(document: dict) -> bytes:
    from .panel_invoker import _access_token_only

    return json.dumps(_access_token_only(document), separators=(",", ":")).encode("utf-8")


def _scan_values(projected: bytes) -> ScanValues:
    """Every secret value of the projected copy and its last 12 characters."""
    from .panel_invoker import _seat_secret_values

    values: list[bytes] = []
    for value in _seat_secret_values(json.loads(projected)):
        values.append(value.encode("utf-8"))
        values.append(value[-12:].encode("utf-8"))
    return ScanValues(values)


def credential_digest(auth_json: bytes, agent_id: bytes) -> str:
    """The digest the spawn-boundary check compares the two staged credential files with
    (jail contract 2.3, "Integrity at spawn"): sha256 over each name and length-framed
    content."""
    digest = hashlib.sha256(b"grok-seat-credential.v1\0")
    for name, data in ((AUTH_FILE_NAME, auth_json), (AGENT_ID_FILE_NAME, agent_id)):
        digest.update(name.encode("ascii") + b"\0" + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


# --------------------------------------------------------------------------------------
# Staging.
# --------------------------------------------------------------------------------------

def _write_read_only(dir_fd: int, name: str, data: bytes) -> None:
    """Create ``name`` exclusively under ``dir_fd``, never through a link, then make it
    0444."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
        os.fchmod(fd, 0o444)
    finally:
        os.close(fd)


def _mount_point_dir(dir_fd: int, name: str) -> None:
    os.mkdir(name, 0o700, dir_fd=dir_fd)
    fd = os.open(name, _O_DIR, dir_fd=dir_fd)
    try:
        os.fchmod(fd, 0o555)
    finally:
        os.close(fd)


def _remove_partial(dir_fd: int) -> None:
    """Remove what a failed staging created under ``dir_fd``; best effort."""
    try:
        os.fchmod(dir_fd, 0o700)
    except OSError:
        return
    for name in os.listdir(dir_fd):
        try:
            if name in MOUNT_POINT_DIRS:
                os.rmdir(name, dir_fd=dir_fd)
            else:
                os.unlink(name, dir_fd=dir_fd)
        except OSError:
            pass


def _stage(config_dir: Path, files: tuple[tuple[str, bytes], ...]) -> None:
    parent, name = os.path.split(os.path.abspath(config_dir))
    if name != HOST_GROK_CONFIG_DIRNAME:
        raise ValueError(f"the staged directory must be <review_dir>/{HOST_GROK_CONFIG_DIRNAME}")
    try:
        parent_fd = os.open(parent, _O_DIR)
    except OSError as exc:
        raise GrokCredentialRefused(STORE_UNSAFE) from exc
    try:
        info = os.fstat(parent_fd)
        if info.st_uid != _owner_uid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise GrokCredentialRefused(STORE_UNSAFE, "the review directory is not private")
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except OSError as exc:
            raise GrokCredentialRefused(STORE_UNSAFE, "the staged directory exists") from exc
        try:
            dir_fd = os.open(name, _O_DIR, dir_fd=parent_fd)
        except OSError as exc:
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
            raise GrokCredentialRefused(STORE_UNSAFE, "the staged directory cannot be opened") \
                from exc
        try:
            try:
                for file_name, data in files:
                    _write_read_only(dir_fd, file_name, data)
                for dir_name in MOUNT_POINT_DIRS:
                    _mount_point_dir(dir_fd, dir_name)
                os.fsync(dir_fd)
                os.fchmod(dir_fd, 0o555)
            except BaseException:
                _remove_partial(dir_fd)
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                except OSError:
                    pass
                raise
        finally:
            os.close(dir_fd)
    finally:
        os.close(parent_fd)


def stage_grok_seat_credential(config_dir: str | os.PathLike[str], *,
                               margin_s: float) -> GrokSeatCredential:
    """Check the operator's store and write the staged read-only ``.grok`` directory at
    ``config_dir`` (``<review_dir>/grok-config``, which must not exist; its parent must be
    the operator's private review directory).

    Every check runs before anything is written, so a refusal leaves nothing on disk:
    ``grok_seat_credential_missing``, ``seat_profile_unavailable`` (an unsafe store, an
    existing or linked target, a shared review directory, or a seat config off its pin),
    ``grok_seat_credential_refused`` unless the store shows the positive subscription
    marker, and ``grok_seat_token_expired`` unless the expiry parses and the remaining
    lifetime exceeds ``margin_s``."""
    margin = _checked_margin(margin_s)
    config_dir = Path(os.path.abspath(config_dir))
    if config_dir.name != HOST_GROK_CONFIG_DIRNAME:
        raise ValueError(f"the staged directory must be <review_dir>/{HOST_GROK_CONFIG_DIRNAME}")
    auth, agent_id = _read_store()
    marked = _sign_in_entry(auth)
    if marked is None:
        raise GrokCredentialRefused(CREDENTIAL_REFUSED)
    document, entry = marked
    expires_at = _expiry(entry.get("expires_at"))
    if expires_at is None or expires_at - time.time() <= margin:
        raise GrokCredentialRefused(TOKEN_EXPIRED)
    # The marker walked the whole document, deeper per level than these walks do.
    projected = _projected_copy(document)
    scan_values = _scan_values(projected)
    config = seat_config_bytes()
    _stage(config_dir, (
        (CONFIG_FILE_NAME, config),
        (AUTH_FILE_NAME, projected),
        (AGENT_ID_FILE_NAME, agent_id),
        *((lock, b"") for lock in MOUNT_POINT_FILES),
    ))
    return GrokSeatCredential(config_dir=config_dir, scan_values=scan_values,
                              digest=credential_digest(projected, agent_id),
                              expires_at=expires_at)


# --------------------------------------------------------------------------------------
# The refresh after-check (president note B5).
# --------------------------------------------------------------------------------------

def _credential_shaped(data: bytes) -> bool:
    """A store-shaped document (an ``https://`` scope holding a ``key``), one that carries
    a refresh credential, or one that cannot be inspected completely: a repeated member
    name (a later value could hide a credential) or depth exhaustion while decoding or
    walking it. Bytes that are not JSON are not credential-shaped."""
    from .panel_invoker import _REFRESH_KEYS

    try:
        document = _strict_json(data)
    except (_DuplicateMember, RecursionError):
        return True
    except (ValueError, UnicodeDecodeError):
        return False

    def walk(value: object) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    continue
                if (key.startswith("https://") and isinstance(item, dict)
                        and isinstance(item.get("key"), str) and item["key"]):
                    return True
                if (key.lower().replace("_", "") in _REFRESH_KEYS
                        and isinstance(item, str) and item):
                    return True
                if walk(item):
                    return True
        elif isinstance(value, list):
            return any(walk(item) for item in value)
        return False

    try:
        return walk(document)
    except RecursionError:
        return True


def _scan_dir(dir_fd: int, depth: int, budget: list[int]) -> bool:
    if depth > _AFTER_MAX_DEPTH:
        return True
    for name in os.listdir(dir_fd):
        budget[0] -= 1
        if budget[0] < 0:
            return True
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            return True
        if name == AUTH_FILE_NAME and (stat.S_ISREG(info.st_mode)
                                        or stat.S_ISLNK(info.st_mode)):
            return True
        if stat.S_ISDIR(info.st_mode):
            try:
                child = os.open(name, _O_DIR, dir_fd=dir_fd)
            except OSError:
                return True
            try:
                if _scan_dir(child, depth + 1, budget):
                    return True
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            if info.st_size > _AFTER_READ_CAP:
                return True  # not inspected within the bound: a finding, never a skip
            try:
                fd = os.open(name, _O_READ, dir_fd=dir_fd)
            except OSError:
                return True
            try:
                data = os.read(fd, _AFTER_READ_CAP + 1)
            except OSError:
                return True
            finally:
                os.close(fd)
            if len(data) > _AFTER_READ_CAP:
                return True
            if _credential_shaped(data):
                return True
    return False


def grok_seat_credential_after(seat_home: str | os.PathLike[str],
                               delivered: GrokSeatCredential) -> str | None:
    """``grok_seat_token_refreshed_in_jail`` if a credential-shaped file appeared in the
    seat's host-visible writable state, else ``None``.

    Under the read-only projection the seat's ``.grok`` is a mount point and its ``logs``
    and ``sessions`` are tmpfs, so the check walks all of seat-home (``.grok-rw/**``, the
    measurement sink and every stub), never following a link: any ``auth.json`` (file or
    link), any document in the store's shape or carrying a refresh credential, and any
    entry it cannot inspect completely (fail closed) fires it -- an unreadable entry, a
    file over the read bound, a repeated JSON member name, or depth exhaustion. The staged directory is never under
    seat-home. The proxy's refusal of the sign-in hosts remains the primary detection."""
    if not isinstance(delivered, GrokSeatCredential):
        raise TypeError("delivered must be the GrokSeatCredential staged for this launch")
    home = os.path.abspath(seat_home)
    if not os.path.lexists(home):
        return None
    try:
        root = os.open(home, _O_DIR)
    except OSError:
        return REFRESHED_IN_JAIL
    try:
        return REFRESHED_IN_JAIL if _scan_dir(root, 0, [_AFTER_MAX_ENTRIES]) else None
    except OSError:
        return REFRESHED_IN_JAIL
    finally:
        os.close(root)


__all__ = [
    "AGENT_ID_CAP_BYTES", "AUTH_CAP_BYTES", "API_KEY_PREFIX", "GrokCredentialRefused",
    "GrokSeatCredential", "HOST_GROK_CONFIG_DIRNAME", "SEAT_CONFIG_SHA256", "SIGN_IN_SCOPE",
    "STAGED_ENTRIES", "ScanValues", "credential_digest", "grok_seat_credential_after",
    "grok_seat_credential_present", "seat_config_bytes", "stage_grok_seat_credential",
]
