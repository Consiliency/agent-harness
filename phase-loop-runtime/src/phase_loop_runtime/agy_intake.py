"""Submit a signed qualification record through the INTAKE App (AGYROLL ROLLJOB, R9′; SL-2).

The upstream watch makes no git write. Its only credential is the INTAKE App's private key,
an organization-owned GitHub App that can write issues and nothing else. A tick mints a
short-lived installation token limited to this repository and ``issues: write``, and submits
the record as data: one issue whose body is ``agy_catalog_policy.render_intake(record)``. A
trusted workflow on ``main`` verifies it and authors the catalog pull request itself.

The JWT is assembled here and signed with ``cryptography`` (RS256, PKCS#1 v1.5 with SHA-256),
which comes from the optional ``agy-watch`` extra and is imported lazily: without it the tick
ends with ``agy_intake_dependency_missing`` before any live operation. The transport is
``http.client`` to ``api.github.com`` only: no proxy, the compiled-in trust store, no
redirect. The key and the token never reach a log, an argv or a status line.

A submission leaves a receipt in the qualification store. The store's entry types are closed,
so the receipt reuses ``watch_push`` under a context no push receipt ever had
(``{"kind": "intake_receipt.v1", "version", "qci"}``) and a payload of another shape
(``{"issue", "record_sha256", "at"}``); a historical push receipt can never read as one.
"""
from __future__ import annotations

import base64
from datetime import datetime
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlencode

from . import agy_catalog_policy as policy

APP_KEY_ENV = "AGY_INTAKE_APP_KEY"
APP_ID_ENV = "AGY_INTAKE_APP_ID"
INSTALLATION_ID_ENV = "AGY_INTAKE_INSTALLATION_ID"
REPO_OWNER = "Consiliency"
REPOSITORY = "agent-harness"
REPO_SLUG = f"{REPO_OWNER}/{REPOSITORY}"
API_HOST = "api.github.com"
#: The only permission an intake token is requested with (and granted, besides metadata).
TOKEN_PERMISSIONS = {"issues": "write"}

UNAVAILABLE = "agy_intake_unavailable"
DEPENDENCY_MISSING = "agy_intake_dependency_missing"
SUBMIT_FAILED = "agy_intake_submit_failed"
STALLED = "intake_stalled"

RECEIPT_TYPE = "watch_push"
RECEIPT_KIND = "intake_receipt.v1"
_JWT_LIFETIME_S = 540
_MAX_KEY_BYTES = 16_384
_MAX_RESPONSE_BYTES = 8_000_000
_ISSUE_PAGE = 50
_MAX_ISSUE_PAGES = 20
_TIMEOUT_S = 30
_USER_AGENT = "agent-harness-agy-intake"


class IntakeError(ValueError):
    """A fixed, content-free intake refusal: ``str(exc)`` is the tick status."""


# ----------------------------------------------------------------------------- the key

def _require_ids(app_id, installation_id) -> tuple[int, int]:
    try:
        values = int(str(app_id)), int(str(installation_id))
    except (TypeError, ValueError):
        raise IntakeError(UNAVAILABLE) from None
    if any(value <= 0 for value in values):
        raise IntakeError(UNAVAILABLE)
    return values


def read_key(key_path) -> bytes:
    """The INTAKE key's bytes: a regular file (never a symlink), owned by this account and
    readable by it alone; anything else is ``agy_intake_unavailable``."""
    if not key_path:
        raise IntakeError(UNAVAILABLE)
    try:
        fd = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError:
        raise IntakeError(UNAVAILABLE) from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or info.st_size > _MAX_KEY_BYTES):
            raise IntakeError(UNAVAILABLE)
        return os.read(fd, _MAX_KEY_BYTES + 1)
    except OSError:
        raise IntakeError(UNAVAILABLE) from None
    finally:
        os.close(fd)


def _crypto():
    """The ``cryptography`` primitives, imported lazily from the ``agy-watch`` extra."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        raise IntakeError(DEPENDENCY_MISSING) from None
    return hashes, serialization, padding, rsa


def preflight(environ=None) -> tuple[int, int, str]:
    """Before any live operation: the extra is installed, the key is safe and the ids are
    set. Returns ``(app_id, installation_id, key_path)``; raises the tick's refusal."""
    environ = os.environ if environ is None else environ
    _crypto()
    ids = _require_ids(environ.get(APP_ID_ENV), environ.get(INSTALLATION_ID_ENV))
    key_path = environ.get(APP_KEY_ENV)
    _private_key(read_key(key_path))
    return ids[0], ids[1], key_path


def _private_key(data: bytes):
    _hashes, serialization, _padding, rsa = _crypto()
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError):
        raise IntakeError(UNAVAILABLE) from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise IntakeError(UNAVAILABLE)
    return key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def app_jwt(app_id, key_path, *, now=None) -> str:
    """A short-lived RS256 App JWT: ``iat`` a minute in the past (clock drift), ``exp`` nine
    minutes ahead (GitHub's limit is ten), ``iss`` the App id."""
    hashes, _serialization, padding, _rsa = _crypto()
    key = _private_key(read_key(key_path))
    issued = int(time.time() if now is None else now)
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"iat": issued - 60, "exp": issued + _JWT_LIFETIME_S, "iss": str(app_id)},
                             separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    return f"{header}.{claims}.{_b64(key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256()))}"


# ------------------------------------------------------------------------- the transport

class _Transport:
    """https to ``api.github.com`` only, through ``http.client`` (no proxy), the compiled-in
    trust store and no redirect. ``request`` returns ``(status, parsed JSON or None)``."""

    def __init__(self, *, connection=http.client.HTTPSConnection, context_factory=None, timeout=_TIMEOUT_S):
        if context_factory is None:
            from .agy_provenance import _trust_context as context_factory
        self.connection, self.context_factory, self.timeout = connection, context_factory, timeout

    def request(self, method, path, *, authorization, body=None):
        if not path.startswith("/") or "\n" in path or "\r" in path:
            raise IntakeError(SUBMIT_FAILED)
        conn = self.connection(API_HOST, 443, context=self.context_factory(), timeout=self.timeout)
        try:
            payload = None if body is None else json.dumps(body).encode()
            headers = {"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT,
                       "X-GitHub-Api-Version": "2022-11-28", "Authorization": authorization}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            data = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise IntakeError(SUBMIT_FAILED)
            return response.status, (json.loads(data) if data else None)
        finally:
            conn.close()


def _call(transport, method, path, *, authorization, body=None, expect=(200,), code=SUBMIT_FAILED):
    """One API call, or the fixed refusal ``code``: no message carries a header or a body."""
    try:
        status, value = (transport or _Transport()).request(method, path, authorization=authorization, body=body)
    except IntakeError:
        raise IntakeError(code) from None
    except (OSError, ValueError, http.client.HTTPException):
        raise IntakeError(code) from None
    if status not in expect:
        raise IntakeError(code)
    return value


def installation_token(app_id, installation_id, key_path, *, transport=None, now=None) -> str:
    """An installation token for this repository with ``issues: write`` only. A grant that is
    any wider (another repository, another permission beyond metadata read) is refused."""
    app_id, installation_id = _require_ids(app_id, installation_id)
    jwt = app_jwt(app_id, key_path, now=now)
    value = _call(transport, "POST", f"/app/installations/{installation_id}/access_tokens",
                  authorization=f"Bearer {jwt}",
                  body={"repositories": [REPOSITORY], "permissions": dict(TOKEN_PERMISSIONS)},
                  expect=(201,), code=UNAVAILABLE)
    if not isinstance(value, dict) or not isinstance(value.get("token"), str) or not value["token"]:
        raise IntakeError(UNAVAILABLE)
    granted = value.get("permissions")
    if not isinstance(granted, dict) or granted.get("issues") != "write" or any(
            (name, level) != ("metadata", "read") for name, level in granted.items() if name != "issues"):
        raise IntakeError(UNAVAILABLE)
    repositories = value.get("repositories")
    if not isinstance(repositories, list) or [
            r.get("full_name") if isinstance(r, dict) else None for r in repositories] != [REPO_SLUG]:
        raise IntakeError(UNAVAILABLE)
    return value["token"]


# ------------------------------------------------------------------------ the issues

def _own(issue, app_id) -> bool:
    """An issue (not a pull request) that this App created."""
    via = issue.get("performed_via_github_app") if isinstance(issue, dict) else None
    user = issue.get("user") if isinstance(issue, dict) else None
    return (isinstance(via, dict) and type(via.get("id")) is int and via["id"] == int(app_id)
            and isinstance(user, dict) and user.get("type") == "Bot" and "pull_request" not in issue
            and type(issue.get("number")) is int)


def _first_line(issue) -> str:
    body = issue.get("body") if isinstance(issue, dict) else None
    return body.split("\n", 1)[0] if isinstance(body, str) else ""


def own_open_issues(token, app_id, *, transport=None, code=SUBMIT_FAILED) -> list[dict]:
    """Every open ``agy-intake`` issue this App created, paged to a short page."""
    found = []
    for page in range(1, _MAX_ISSUE_PAGES + 1):
        query = urlencode({"state": "open", "labels": policy.INTAKE_LABEL, "per_page": _ISSUE_PAGE, "page": page})
        value = _call(transport, "GET", f"/repos/{REPO_SLUG}/issues?{query}", authorization=f"Bearer {token}",
                      code=code)
        if not isinstance(value, list):
            raise IntakeError(code)
        found += [issue for issue in value if _own(issue, app_id)]
        if len(value) < _ISSUE_PAGE:
            return found
    raise IntakeError(code)  # the listing never ended: not a complete answer


def _receipt_context(version, qci) -> dict:
    return {"kind": RECEIPT_KIND, "version": version, "qci": qci}


def _store(store=None):
    from .agy_qualification import Store
    return store or Store()


def write_receipt(version, qci, issue, record_sha256, *, store=None, now=None) -> None:
    store = _store(store)
    if store.status() == "absent":
        store.create()
    context = _receipt_context(version, qci)
    store.put(RECEIPT_TYPE, context, context, {"issue": int(issue), "record_sha256": record_sha256,
                                                "at": int(time.time() if now is None else now)})


def read_receipt(version, qci, *, store=None) -> dict | None:
    """The receipt for ``(version, qci)``, or ``None``: missing, tampered, or not shaped like
    an intake receipt (a historical push receipt has another context and payload)."""
    context = _receipt_context(version, qci)
    try:
        payload = _store(store).get(RECEIPT_TYPE, context, context)
    except (OSError, ValueError):
        return None
    if (not isinstance(payload, dict) or set(payload) != {"issue", "record_sha256", "at"}
            or type(payload["issue"]) is not int or type(payload["at"]) is not int
            or not isinstance(payload["record_sha256"], str) or len(payload["record_sha256"]) != 64):
        return None
    return payload


def record_sha256(record) -> str:
    return sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def submit(record, token, *, transport=None, store=None, now=None, app_id=None) -> int:
    """Submit ``record`` and write its receipt; returns the issue number.

    It first lists the open issues this App created: one whose first line is this record's
    header is adopted (how a lost POST response is recovered without a duplicate). Otherwise
    it creates one issue titled ``agy intake: <version>``, labelled ``agy-intake``."""
    app_id = int(os.environ.get(APP_ID_ENV, "0") if app_id is None else app_id)
    body = policy.render_intake(record)
    header = body.split("\n", 1)[0]
    version, qci = record["release_version"], record["qci"]
    adopted = [issue for issue in own_open_issues(token, app_id, transport=transport) if _first_line(issue) == header]
    if adopted:
        number = min(issue["number"] for issue in adopted)
    else:
        created = _call(transport, "POST", f"/repos/{REPO_SLUG}/issues", authorization=f"Bearer {token}",
                        body={"title": f"agy intake: {version}", "body": body, "labels": [policy.INTAKE_LABEL]},
                        expect=(201,))
        if not isinstance(created, dict) or type(created.get("number")) is not int:
            raise IntakeError(SUBMIT_FAILED)
        number = created["number"]
    try:
        write_receipt(version, qci, number, record_sha256(record), store=store, now=now)
    except (OSError, ValueError):
        raise IntakeError(SUBMIT_FAILED) from None
    return number


def _age(issue, now) -> float | None:
    try:
        created = datetime.fromisoformat(str(issue["created_at"]).replace("z", "Z")).timestamp()
    except (KeyError, TypeError, ValueError):
        return None
    return now - created


def _open_state(issue, now) -> bool:
    """``True`` for an open issue younger than ``INTAKE_STALE_AFTER_S``; ``intake_stalled``
    for an older one (the hosted reconcile owns its retry; the job does not re-qualify)."""
    age = _age(issue, now)
    if age is None or age >= policy.INTAKE_STALE_AFTER_S:
        raise IntakeError(STALLED)
    return True


def pending(version, qci, token, *, transport=None, store=None, now=None, app_id=None, ignore_wait=False) -> bool:
    """Whether a submission for ``(version, qci)`` is pending, decided from the receipt and
    the issue's current state, read back:

    - open and younger than ``INTAKE_STALE_AFTER_S``: pending (the tick is ``up_to_date``);
    - open and older: ``IntakeError(intake_stalled)``;
    - closed (refused or exhausted; the version is not a member, or the tick would have
      stopped at ``already_pinned``): pending until ``RESUBMIT_AFTER_S`` after the receipt,
      unless ``ignore_wait`` (an operator re-run with ``--version``);
    - no receipt and no own open issue for it: not pending.

    An API failure here, before any qualification, is ``agy_intake_unavailable``."""
    now = time.time() if now is None else now
    app_id = int(os.environ.get(APP_ID_ENV, "0") if app_id is None else app_id)
    receipt = read_receipt(version, qci, store=store)
    if receipt is not None:
        issue = _call(transport, "GET", f"/repos/{REPO_SLUG}/issues/{receipt['issue']}",
                      authorization=f"Bearer {token}", code=UNAVAILABLE)
        if isinstance(issue, dict) and _own(issue, app_id):
            if issue.get("state") == "open":
                return _open_state(issue, now)
            if issue.get("state") == "closed":
                return not ignore_wait and now - receipt["at"] < policy.RESUBMIT_AFTER_S
            raise IntakeError(UNAVAILABLE)
    prefix = f"{policy.INTAKE_SCHEMA} {version} {qci} "
    for issue in own_open_issues(token, app_id, transport=transport, code=UNAVAILABLE):
        line = _first_line(issue)
        if line.startswith(prefix):
            # A submission whose POST response was lost: adopt it, so its closing is seen later.
            try:
                write_receipt(version, qci, issue["number"], line[len(prefix):], store=store, now=now)
            except (OSError, ValueError):
                raise IntakeError(UNAVAILABLE) from None
            return _open_state(issue, now)
    return False


# ------------------------------------------------------------- kept records (the outbox)

def outbox_dir(environ=None) -> Path:
    """Signed records not yet submitted: ``<state home>/phase-loop/agy-watch/outbox`` (0700)."""
    return policy.tick_status_path(environ).parent / "outbox"


def keep(record, *, environ=None) -> Path:
    """Keep a signed record (0600) until its submission is receipted."""
    directory = outbox_dir(environ)
    policy._private_dir(directory.parent)
    policy._private_dir(directory)
    path = directory / f"agy-{record['release_version']}-{record['qci'][:16]}.json"
    temporary = directory / f".{path.name}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream, sort_keys=True)
    os.replace(temporary, path)
    return path


def kept(qci, *, environ=None) -> list[dict]:
    """The kept records for ``qci`` (a record for another QCI is discarded: it can no longer
    pass the intake's QCI check)."""
    directory = outbox_dir(environ)
    records = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return records
    for path in entries:
        if path.name.startswith(".") or path.suffix != ".json" or path.is_symlink():
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        if isinstance(record, dict) and record.get("qci") == qci and record.get("signatures"):
            records.append(record)
        else:
            path.unlink(missing_ok=True)
    return records


def discard(record, *, environ=None) -> None:
    (outbox_dir(environ) / f"agy-{record['release_version']}-{record['qci'][:16]}.json").unlink(missing_ok=True)
