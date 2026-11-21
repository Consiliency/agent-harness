"""The rules the rolling catalog job and the catalog verifier share (AGYROLL ROLLJOB, SL-0).

Standard library only. Nothing here imports ``agy_qualification``, ``gemini_heartbeat`` or
``panel_invoker``, so the base-branch verifier's ``--catalog-pr`` mode (the required
``agy catalog provenance`` check) can import this one module and nothing else. Where a rule
also lives in the runtime (the strict catalog parser, the record's closed vocabularies), the
copy here is tested equal to the runtime's.

It holds: the canonical bytes of a qualification record and its job signature
(``ssh-keygen -Y``); catalog aging and the automatic-promotion diff class; building the
promoted catalog; the intake issue body format; the attestation file reader and author
authentication; the headroom thresholds; and the watch's tick-status file.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

SERIES_RETRIES = 3
CATALOG_KEEP = 3
CATALOG_MIN_AGE_S = 14 * 86_400
LAG_BOUND_S = 48 * 3_600
HEADROOM_WARN_PERCENT = 80
HEADROOM_FAIL_PERCENT = 90
CATALOG_LABEL = "agy-catalog-auto"
INTAKE_LABEL = "agy-intake"
INTAKE_SCHEMA = "agy-intake.v1"
MAX_RECORD_BYTES = 60_000
RESUBMIT_AFTER_S = 86_400
CATALOG_BRANCH_PREFIX = "agy-catalog/"
LAG_ENFORCE_ENV = "AGY_LAG_ENFORCE"
UPSTREAM_REPO = "google-antigravity/antigravity-cli"   # the only upstream; never taken from a submission
ATTESTATION_PATH = "config/agy-rollout-attestation.json"
ATTESTATION_SCHEMA = "agy_rollout_attestation.v1"
IN_FLIGHT_MAX_S = 86_400
INTAKE_STALE_AFTER_S = 6 * 3_600
MAX_PROMOTION_ATTEMPTS = 6
MAX_PREPR_FAILURES = 6
LAG_LABEL = "agy-lag"
SIGNATURE_NAMESPACE = "agy-qualification"
SIGNER_PRINCIPAL = "agy-watch"
ALLOWED_SIGNERS = "plans/evidence/agy-allowed-signers"
CATALOG_PATH = "phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json"
RECORD_PATH = re.compile(r"plans/evidence/agy-(\d+\.\d+\.\d+)-linux-x64-qualification\.json")
SIGNING_KEY_ENV = "AGY_WATCH_SIGNING_KEY"
TICK_STATUS_SCHEMA = "agy_watch_tick.v1"

SIGNING_UNAVAILABLE = "agy_watch_signing_unavailable"

# The catalog and record shapes, tested equal to ``gemini_heartbeat`` (the catalog parser and
# ``PROFILE_ID``), ``agy_attestation`` (the two status vocabularies) and the verifier
# (``RECORD_KEYS``, ``UPSTREAM_KEYS``, ``ROUTE``, ``ASSET``).
CATALOG_SCHEMA = "qualified_agy_catalog.v3"
CATALOG_ROUTE = "linux-x64"
RECORD_SCHEMA = "agy_redacted_qualification_summary.v2"
PROFILE_ID = "agy_memfd_home_deny_all_v1"
ASSET = "agy_cli_linux_x64.tar.gz"
ROUTE = {"provider": "gemini", "route": "brokered_subscription_heartbeat_only",
         "platform": "linux", "architecture": "x86_64"}
RECORD_KEYS = frozenset({
    "schema", "provider", "route", "platform", "architecture", "release_version", "image_sha256",
    "help_sha256", "isolation_profile", "raw_receipts_local_only", "records", "role",
    "upstream_asset_name", "upstream_asset_sha256", "upstream_release_url", "validator",
    "qci", "qualified_under", "upstream", "signatures",
})
UPSTREAM_KEYS = frozenset({"asset_sha256", "release_url", "attestation", "second_channel"})
ATTESTATION_STATUSES = ("absent", "present_unverified", "not_checked")
SECOND_CHANNEL_STATUSES = ("match", "not_listed", "not_checked")
OPERATIONS = ("cancel", "completion", "owner-loss")

_CATALOG_MEMBER_KEYS = ("release_version", "image_sha256", "help_sha256", "asset_sha256",
                        "qci", "published_at", "pinned", "record")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_RFC3339 = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]+)?"
                      r"(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])")
_PRINCIPAL = re.compile(r"[A-Za-z0-9._-]{1,64}")
_MAX_SIGNATURE_CHARS = 8192
_MAX_SIGNATURES = 8
_SSH_TIMEOUT_S = 30
_ARMOR = "-----BEGIN SSH SIGNATURE-----"


# ------------------------------------------------------------------ records and signatures

def canonical_record(record: dict) -> bytes:
    """The bytes a job signature covers: the record without ``signatures``, keys sorted,
    compact separators, ASCII only, UTF-8."""
    if not isinstance(record, dict):
        raise ValueError("agy record is not an object")
    body = {key: value for key, value in record.items() if key != "signatures"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _ssh_keygen() -> str | None:
    return shutil.which("ssh-keygen")


def sign_record(record: dict, key_path, *, runner=subprocess.run) -> dict:
    """The record with one job signature appended (``ssh-keygen -Y sign``, namespace
    ``agy-qualification``, principal ``agy-watch``).

    A missing key, a key that is not a regular file or that group or others can read, a
    missing ``ssh-keygen`` or a non-zero exit all raise ``ValueError(SIGNING_UNAVAILABLE)``.
    The key path is never printed: no message here carries it."""
    if not key_path:
        raise ValueError(SIGNING_UNAVAILABLE)
    try:
        info = os.stat(key_path, follow_symlinks=False)
    except OSError:
        raise ValueError(SIGNING_UNAVAILABLE) from None
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError(SIGNING_UNAVAILABLE)
    program = _ssh_keygen()
    if program is None:
        raise ValueError(SIGNING_UNAVAILABLE)
    try:
        done = runner([program, "-Y", "sign", "-n", SIGNATURE_NAMESPACE, "-f", os.fspath(key_path)],
                      input=canonical_record(record), capture_output=True, check=False,
                      timeout=_SSH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        raise ValueError(SIGNING_UNAVAILABLE) from None
    armored = done.stdout.decode("ascii", "replace") if isinstance(done.stdout, bytes) else str(done.stdout or "")
    if done.returncode != 0 or not armored.startswith(_ARMOR) or len(armored) > _MAX_SIGNATURE_CHARS:
        raise ValueError(SIGNING_UNAVAILABLE)
    signatures = list(record.get("signatures") or [])
    signatures.append({"principal": SIGNER_PRINCIPAL, "namespace": SIGNATURE_NAMESPACE, "signature": armored})
    return {**record, "signatures": signatures}


def _signature_entries(record):
    entries = record.get("signatures") if isinstance(record, dict) else None
    if not isinstance(entries, list):
        return
    for entry in entries[:_MAX_SIGNATURES]:
        if (isinstance(entry, dict) and set(entry) == {"principal", "namespace", "signature"}
                and isinstance(entry["principal"], str) and _PRINCIPAL.fullmatch(entry["principal"])
                and entry["namespace"] == SIGNATURE_NAMESPACE
                and isinstance(entry["signature"], str) and entry["signature"].startswith(_ARMOR)
                and len(entry["signature"]) <= _MAX_SIGNATURE_CHARS):
            yield entry


def verified_signers(record: dict, allowed_signers_path, *, runner=subprocess.run) -> list[str]:
    """The distinct principals whose signature over ``canonical_record(record)`` verifies
    against ``allowed_signers_path`` (``ssh-keygen -Y verify``), in record order.

    A malformed entry is ignored, never an error, and so is a missing ``ssh-keygen``: an empty
    result is the caller's refusal."""
    program = _ssh_keygen()
    if program is None:
        return []
    try:
        payload = canonical_record(record)
    except (TypeError, ValueError):
        return []
    verified = []
    with tempfile.TemporaryDirectory(prefix="agy-signers-") as scratch:
        for index, entry in enumerate(_signature_entries(record)):
            if entry["principal"] in verified:
                continue
            signature = Path(scratch) / f"sig-{index}"
            signature.write_text(entry["signature"], encoding="ascii")
            try:
                done = runner([program, "-Y", "verify", "-f", os.fspath(allowed_signers_path),
                               "-I", entry["principal"], "-n", SIGNATURE_NAMESPACE, "-s", str(signature)],
                              input=payload, capture_output=True, check=False, timeout=_SSH_TIMEOUT_S)
            except (OSError, subprocess.SubprocessError, UnicodeError):
                continue
            if done.returncode == 0:
                verified.append(entry["principal"])
    return verified


# ----------------------------------------------------------------- catalog and its members

def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("agy catalog repeats a key")
        value[key] = item
    return value


def parse_catalog(text: str) -> list[dict]:
    """The members of a ``qualified_agy_catalog.v3`` document, or ``ValueError``. Closed keys,
    hex64 digests, unique images, versions and records, exactly the ``linux-x64`` route.
    Tested equal to ``gemini_heartbeat.parse_catalog`` on accepting and rejecting fixtures."""
    catalog = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(catalog, dict) or set(catalog) != {"schema", "routes"} or catalog["schema"] != CATALOG_SCHEMA:
        raise ValueError("agy catalog schema mismatch")
    routes = catalog["routes"]
    if not isinstance(routes, dict) or set(routes) != {CATALOG_ROUTE} or not isinstance(routes[CATALOG_ROUTE], list):
        raise ValueError("agy catalog route mismatch")
    members = routes[CATALOG_ROUTE]
    for member in members:
        if not isinstance(member, dict) or set(member) != set(_CATALOG_MEMBER_KEYS):
            raise ValueError("agy catalog member keys mismatch")
        if not all(isinstance(member[key], str) and _HEX64.fullmatch(member[key])
                   for key in ("image_sha256", "help_sha256", "asset_sha256", "qci")):
            raise ValueError("agy catalog digest malformed")
        version = member["release_version"]
        if not isinstance(version, str) or not _RELEASE.fullmatch(version):
            raise ValueError("agy catalog release version malformed")
        if not isinstance(member["published_at"], str) or not _RFC3339.fullmatch(member["published_at"]):
            raise ValueError("agy catalog published_at malformed")
        datetime.fromisoformat(member["published_at"].replace("z", "Z"))  # a real instant
        if type(member["pinned"]) is not bool:
            raise ValueError("agy catalog pinned is not a bool")
        if member["record"] != f"agy-{version}-linux-x64-qualification.json":
            raise ValueError("agy catalog record name mismatch")
    for key in ("image_sha256", "release_version", "record"):
        if len({member[key] for member in members}) != len(members):
            raise ValueError(f"agy catalog repeats a {key}")
    return members


def render_catalog(members: list[dict]) -> str:
    """The catalog file for ``members``, in the shipped layout; it must parse."""
    ordered = [{key: member[key] for key in _CATALOG_MEMBER_KEYS} for member in members]
    text = json.dumps({"schema": CATALOG_SCHEMA, "routes": {CATALOG_ROUTE: ordered}}, indent=2) + "\n"
    parse_catalog(text)
    return text


def release_key(version) -> tuple[int, int, int] | None:
    """``x.y.z`` as an integer tuple, or ``None`` when it is not one."""
    match = _RELEASE.fullmatch(version) if isinstance(version, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def parse_instant(text) -> float | None:
    """An RFC 3339 instant as a POSIX timestamp, or ``None`` when it is not one."""
    if not isinstance(text, str) or not _RFC3339.fullmatch(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("z", "Z")).timestamp()
    except ValueError:
        return None


def rfc3339(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def aging(members: list[dict], *, now: float) -> tuple[list[dict], list[dict]]:
    """``(kept, pruned)``, each in catalog order. A member is kept when it is ``pinned``, or
    among the ``CATALOG_KEEP`` highest versions, or published less than ``CATALOG_MIN_AGE_S``
    before ``now``. An unparseable ``published_at`` or version keeps the member."""
    keyed = [(release_key(member.get("release_version")), index) for index, member in enumerate(members)]
    newest = {index for _key, index in sorted((item for item in keyed if item[0] is not None),
                                              reverse=True)[:CATALOG_KEEP]}
    kept, pruned = [], []
    for (key, index), member in zip(keyed, members):
        published = parse_instant(member.get("published_at"))
        keep = (member.get("pinned") is True or key is None or index in newest or published is None
                or now - published < CATALOG_MIN_AGE_S)
        (kept if keep else pruned).append(member)
    return kept, pruned


@dataclass(frozen=True)
class CatalogChange:
    """How a head catalog differs from its base, and whether the difference is the one diff
    class automatic promotion may carry (``auto``); ``reasons`` names each failed condition."""
    added: tuple
    removed: tuple
    modified: tuple
    auto: bool
    reasons: tuple


def catalog_change(base: list[dict], head: list[dict], *, now: float) -> CatalogChange:
    """``auto`` only when (1) exactly one member is added, not ``pinned`` and newer than every
    base member; (2) every removed member is in ``aging(base + added, now)``'s pruned list;
    and (3) no surviving base member differs in any field, ``pinned`` included."""
    base_by = {member["release_version"]: member for member in base}
    head_by = {member["release_version"]: member for member in head}
    added = tuple(member for member in head if member["release_version"] not in base_by)
    removed = tuple(member for member in base if member["release_version"] not in head_by)
    modified = tuple(member for member in head
                     if member["release_version"] in base_by and member != base_by[member["release_version"]])
    reasons = []
    if len(added) != 1:
        reasons.append("added_count_not_one")
    else:
        new = added[0]
        if new.get("pinned") is not False:
            reasons.append("added_member_pinned")
        key = release_key(new.get("release_version"))
        if key is None or any((release_key(m["release_version"]) or (-1,)) >= key for m in base):
            reasons.append("added_member_not_newest")
    _kept, pruned = aging(list(base) + list(added), now=now)
    if any(member not in pruned for member in removed):
        reasons.append("removed_member_not_aged_out")
    if modified:
        reasons.append("surviving_member_modified")
    return CatalogChange(added, removed, modified, not reasons, tuple(reasons))


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def candidate_member(record: dict) -> dict:
    """The catalog member a closed v2 record for this route describes (without
    ``published_at`` and ``pinned``), or ``ValueError``. Validity only: it does not look at
    any catalog, so an existing or older version is still a valid candidate."""
    _require(isinstance(record, dict) and set(record) == RECORD_KEYS, "record is not a closed v2 record")
    _require(record["schema"] == RECORD_SCHEMA, "record schema mismatch")
    version = record["release_version"]
    _require(isinstance(version, str) and _RELEASE.fullmatch(version) is not None, "record version malformed")
    for key, value in {**ROUTE, "upstream_asset_name": ASSET, "isolation_profile": PROFILE_ID,
                       "upstream_release_url": f"https://github.com/{UPSTREAM_REPO}/releases/tag/{version}"}.items():
        _require(record[key] == value, f"record {key} mismatch")
    for key in ("image_sha256", "help_sha256", "upstream_asset_sha256", "qci"):
        _require(isinstance(record[key], str) and _HEX64.fullmatch(record[key]) is not None, f"record {key} malformed")
    upstream = record["upstream"]
    _require(isinstance(upstream, dict) and set(upstream) == UPSTREAM_KEYS, "record upstream is not closed")
    _require(upstream["asset_sha256"] == record["upstream_asset_sha256"]
             and upstream["release_url"] == record["upstream_release_url"], "record upstream mismatch")
    _require(upstream["attestation"] in ATTESTATION_STATUSES, "record upstream attestation unknown")
    _require(upstream["second_channel"] in SECOND_CHANNEL_STATUSES, "record upstream second_channel unknown")
    _require(isinstance(record["signatures"], list), "record signatures malformed")
    _require(isinstance(record["qualified_under"], str) and record["qualified_under"], "record qualified_under malformed")
    _require(record["validator"] == {"validated": 3, "operations": list(OPERATIONS), "route_qualified": True},
             "record validator mismatch")
    rows = record["records"]
    _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
             and sorted(str(row.get("operation")) for row in rows) == list(OPERATIONS),
             "record operations mismatch")
    for row in rows:
        profile = row.get("profile")
        _require(row.get("image_sha256") == record["image_sha256"] and row.get("help_sha256") == record["help_sha256"]
                 and isinstance(profile, dict) and profile.get("id") == PROFILE_ID
                 and profile.get("image_sha256") == record["image_sha256"], "record image or profile mismatch")
    return {"release_version": version, "image_sha256": record["image_sha256"],
            "help_sha256": record["help_sha256"], "asset_sha256": record["upstream_asset_sha256"],
            "qci": record["qci"], "record": f"agy-{version}-linux-x64-qualification.json"}


def build_catalog(base: list[dict], record: dict, *, published_at: str, now: float) -> list[dict]:
    """``base`` plus ``candidate_member(record)`` as a non-pinned member published at
    ``published_at``, minus ``aging``'s pruned list. The only place eligibility is decided:
    a version that is already a member, or is not newer than every member, refuses."""
    member = candidate_member(record)
    _require(parse_instant(published_at) is not None, "published_at is not an RFC 3339 instant")
    key = release_key(member["release_version"])
    _require(all(m["release_version"] != member["release_version"] for m in base), "version is already a member")
    _require(all((release_key(m["release_version"]) or (-1,)) < key for m in base), "version is not the newest")
    proposed = list(base) + [{**member, "published_at": published_at, "pinned": False}]
    kept, _pruned = aging(proposed, now=now)
    return [{k: m[k] for k in _CATALOG_MEMBER_KEYS} for m in kept]


# ------------------------------------------------------------------------ the intake body

_INTAKE = re.compile(r"agy-intake\.v1 ((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)) ([0-9a-f]{64}) "
                     r"([0-9a-f]{64})\n\n```json\n([^\n`]+)\n```\n?")


def _record_text(record) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def render_intake(record: dict) -> str:
    """The intake issue body: one header line ``agy-intake.v1 <version> <qci> <sha256 of the
    record text>``, a blank line, and one fenced ``json`` block holding the record text (the
    record, signatures included, serialized sorted and compact). It must parse back."""
    text = _record_text(record)
    body = (f"{INTAKE_SCHEMA} {record.get('release_version')} {record.get('qci')} "
            f"{sha256(text.encode('ascii')).hexdigest()}\n\n```json\n{text}\n```\n")
    if parse_intake(body) != record:
        raise ValueError("agy intake body does not round-trip")
    return body


def parse_intake(body: str) -> dict:
    """The record an intake body carries, or ``ValueError``: a full match of the frozen shape,
    at most ``MAX_RECORD_BYTES``, a header that agrees with the record, a digest that agrees
    with the block and a block that is the record's own sorted serialization. It evaluates
    and imports nothing."""
    _require(isinstance(body, str), "agy intake body is not text")
    _require(len(body.encode("utf-8")) <= MAX_RECORD_BYTES, "agy intake body is too large")
    match = _INTAKE.fullmatch(body)
    _require(match is not None, "agy intake body is malformed")
    version, qci, digest, text = match.groups()
    _require(sha256(text.encode("utf-8")).hexdigest() == digest, "agy intake digest mismatch")
    record = json.loads(text, object_pairs_hook=_unique_object)
    _require(isinstance(record, dict), "agy intake record is not an object")
    _require(_record_text(record) == text, "agy intake record is not in its sorted form")
    _require(record.get("release_version") == version and record.get("qci") == qci, "agy intake header disagrees")
    return record


# ------------------------------------------------------ attestation and author authentication

@dataclass(frozen=True)
class AppIdentity:
    app_id: int
    bot_user_id: int


@dataclass(frozen=True)
class Attestation:
    """The parsed ``config/agy-rollout-attestation.json`` (ROLLJOB-detail §4.5)."""
    status: str
    intake_app: AppIdentity
    promotion_app: AppIdentity
    main_ruleset: dict
    catalog_ruleset: dict
    promotion_environment: dict
    attested_by: str
    attested_at: str

    @property
    def attested(self) -> bool:
        return self.status == "attested"


_ATTESTATION_KEYS = {"schema", "status", "intake_app", "promotion_app", "main_ruleset", "catalog_ruleset",
                     "promotion_environment", "attested_by", "attested_at"}
_APP_KEYS = {"app_id", "bot_user_id"}
_MAIN_RULESET_KEYS = {"id", "target", "enforcement", "bypass_actors", "strict_required_status_checks",
                      "required_checks"}
_CATALOG_RULESET_KEYS = {"id", "target", "enforcement", "rules", "bypass_actors"}
_ACTOR_KEYS = {"actor_type", "actor_id", "bypass_mode"}
_ENVIRONMENT_KEYS = {"name", "branches", "required_reviewers", "admin_bypass"}


def _closed(value, keys, where):
    _require(isinstance(value, dict), f"attestation {where} is not an object")
    _require(set(value) == keys, f"attestation {where} keys mismatch")
    return value


def _int(value, where):
    _require(type(value) is int and value >= 0, f"attestation {where} is not a non-negative integer")
    return value


def _str(value, where):
    _require(isinstance(value, str), f"attestation {where} is not text")
    return value


def _strs(value, where):
    _require(isinstance(value, list) and all(isinstance(item, str) for item in value), f"attestation {where} is not a list of text")
    return list(value)


def _actors(value, where):
    _require(isinstance(value, list), f"attestation {where} is not a list")
    actors = []
    for actor in value:
        actor = _closed(actor, _ACTOR_KEYS, where)
        actors.append({"actor_type": _str(actor["actor_type"], where), "actor_id": _int(actor["actor_id"], where),
                       "bypass_mode": _str(actor["bypass_mode"], where)})
    return actors


def load_attestation(text: str) -> Attestation:
    """The attestation file, under a closed schema. Any missing, extra or mistyped field
    raises; nothing is defaulted (an absent bypass list is an error, never an empty list).
    A ``status`` other than ``attested`` is returned as unattested. An attested file must
    name non-zero App, bot user and ruleset ids."""
    document = _closed(json.loads(text, object_pairs_hook=_unique_object), _ATTESTATION_KEYS, "file")
    _require(document["schema"] == ATTESTATION_SCHEMA, "attestation schema mismatch")
    status = _str(document["status"], "status")
    apps = {}
    for name in ("intake_app", "promotion_app"):
        app = _closed(document[name], _APP_KEYS, name)
        apps[name] = AppIdentity(_int(app["app_id"], name), _int(app["bot_user_id"], name))
    main = _closed(document["main_ruleset"], _MAIN_RULESET_KEYS, "main_ruleset")
    _require(type(main["strict_required_status_checks"]) is bool, "attestation main_ruleset strict flag is not a bool")
    main = {"id": _int(main["id"], "main_ruleset"), "target": _str(main["target"], "main_ruleset"),
            "enforcement": _str(main["enforcement"], "main_ruleset"),
            "bypass_actors": _actors(main["bypass_actors"], "main_ruleset"),
            "strict_required_status_checks": main["strict_required_status_checks"],
            "required_checks": _strs(main["required_checks"], "main_ruleset")}
    catalog = _closed(document["catalog_ruleset"], _CATALOG_RULESET_KEYS, "catalog_ruleset")
    catalog = {"id": _int(catalog["id"], "catalog_ruleset"), "target": _str(catalog["target"], "catalog_ruleset"),
               "enforcement": _str(catalog["enforcement"], "catalog_ruleset"),
               "rules": _strs(catalog["rules"], "catalog_ruleset"),
               "bypass_actors": _actors(catalog["bypass_actors"], "catalog_ruleset")}
    environment = _closed(document["promotion_environment"], _ENVIRONMENT_KEYS, "promotion_environment")
    _require(type(environment["admin_bypass"]) is bool, "attestation admin_bypass is not a bool")
    environment = {"name": _str(environment["name"], "promotion_environment"),
                   "branches": _strs(environment["branches"], "promotion_environment"),
                   "required_reviewers": _int(environment["required_reviewers"], "promotion_environment"),
                   "admin_bypass": environment["admin_bypass"]}
    attestation = Attestation(status, apps["intake_app"], apps["promotion_app"], main, catalog, environment,
                              _str(document["attested_by"], "attested_by"), _str(document["attested_at"], "attested_at"))
    if attestation.attested:
        _require(all(value > 0 for app in (attestation.intake_app, attestation.promotion_app)
                     for value in (app.app_id, app.bot_user_id)) and main["id"] > 0 and catalog["id"] > 0,
                 "an attested file must name every App, bot user and ruleset id")
    return attestation


def authentic_author(user: dict, via_app: dict | None, expected: AppIdentity) -> bool:
    """True only when the author's immutable numeric ``id`` is the attested bot user id, its
    ``type`` is ``Bot``, and the App object GitHub attaches (``performed_via_github_app``) is
    present with the attested App id. Any missing or mistyped field, or an unset (zero)
    expected identity, is ``False``."""
    if not isinstance(expected, AppIdentity) or expected.app_id <= 0 or expected.bot_user_id <= 0:
        return False
    if not isinstance(user, dict) or not isinstance(via_app, dict):
        return False
    user_id, app_id = user.get("id"), via_app.get("id")
    return (type(user_id) is int and user_id == expected.bot_user_id and user.get("type") == "Bot"
            and type(app_id) is int and app_id == expected.app_id)


# ------------------------------------------------------------------------------ headroom

def headroom(size: int, bound: int) -> str:
    """``fail`` at ``HEADROOM_FAIL_PERCENT`` of ``bound`` or more, else ``warn`` at
    ``HEADROOM_WARN_PERCENT`` or more, else ``ok``."""
    if size * 100 >= bound * HEADROOM_FAIL_PERCENT:
        return "fail"
    if size * 100 >= bound * HEADROOM_WARN_PERCENT:
        return "warn"
    return "ok"


# --------------------------------------------------------------------------- tick status

_TICK_KEYS = {"schema", "at", "status", "exit", "version"}
_MAX_TICK_BYTES = 4096


def tick_status_path(environ=None) -> Path:
    """``<state home>/phase-loop/agy-watch/last-tick.json``; the state home is
    ``$XDG_STATE_HOME`` or ``~/.local/state``. Outside the qualification store, whose entry
    types are closed."""
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_STATE_HOME") or str(Path(environ.get("HOME") or Path.home()) / ".local" / "state")
    return Path(base) / "phase-loop" / "agy-watch" / "last-tick.json"


def _private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise OSError("agy watch status directory is not a private directory")
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(path, 0o700)


def write_tick_status(status: str, exit_code: int, *, version=None, environ=None, now=None) -> None:
    """Write the tick status (0600, in a 0700 directory) through a temporary name and a rename."""
    path = tick_status_path(environ)
    _private_dir(path.parent)
    at = rfc3339(now if now is not None else datetime.now(timezone.utc).timestamp())
    body = json.dumps({"schema": TICK_STATUS_SCHEMA, "at": at, "status": str(status), "exit": int(exit_code),
                       "version": None if version is None else str(version)}, sort_keys=True).encode() + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".last-tick-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_tick_status(environ=None) -> dict | None:
    """The last tick status, or ``None`` for a missing, foreign-owned, symlinked, oversized
    or malformed file."""
    path = tick_status_path(environ)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > _MAX_TICK_BYTES:
            return None
        data = os.read(fd, _MAX_TICK_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        value = json.loads(data, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        return None
    if (not isinstance(value, dict) or set(value) != _TICK_KEYS or value["schema"] != TICK_STATUS_SCHEMA
            or not isinstance(value["status"], str) or not value["status"]
            or type(value["exit"]) is not int or parse_instant(value["at"]) is None
            or not (value["version"] is None or isinstance(value["version"], str))):
        return None
    return value
