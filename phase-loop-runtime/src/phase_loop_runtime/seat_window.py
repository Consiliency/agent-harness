"""Attended seat-window collection and closed-field offline reduction."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Mapping

from . import sandbox_policy, seat_egress_proxy, seat_jail

SCHEMA = "seat_window.v1"
VENDORS = ("claude", "gemini", "codex", "grok", "pi")
CONTAINMENT_FIELDS = ("credential_scope", "refresh_detection", "project_settings", "hooks",
                      "mcp_servers", "provider_overrides")
EGRESS_FIELDS = ("allowed_proxy", "refused_proxy", "direct_dns", "direct_ip")
KEY_FIELDS = ("runtime_digest", "profile_digest", "allowlist_digest")
DIGEST_FIELDS = (*KEY_FIELDS, "board_digest", "exec_record_digest", "tool_receipt_digest",
                 "board_input_digest", "delivered_turn_digest")
BINDING_FIELDS = (
    "image_sha256", "admission_class", "help_sha256", "stage_manifest_sha256",
    "plant_layout_sha256", "contract_sha256", "control_argv_sha256",
    "production_argv_sha256", "control_input_sha256", "measured_input_sha256",
    "board_input_sha256", "jail_profile_sha256", "production_allowlist_sha256",
    "refuse_all_allowlist_sha256", "watch_sha256", "proxy_sha256", "validator_sha256",
    "dependency_subject_sha256", "dependency_projection_sha256", "context_id",
    "account_label",
)
PRIVATE_FIELDS = (
    "rows", "canaries", "token_endpoint_events", "credential_events", "lookups", "home_row",
    "manifest_differences", "delivered_copy_sha256", "bracket", "issuer",
    "unavailable_reasons",
)
OWNER_SUMMARY_FIELDS = (
    "schema", "context_id", "outcomes", "unavailable_reasons", "undefined_surfaces",
    "plugin_validation", "home_row_baseline", "counted_lookups",
    "uncounted_home_lookups", "voided_controls", "expired_copy_control", "private_route",
)
CONTAINMENT_CONTRACT_SHA256 = "a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6"
WINDOW_LAUNCH_TIMEOUT_S = 600.0
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[ac][0-9a-f]{31}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
#: The live W1 and conservative W1 evidence cutoff is independent of route renewals.
OWNER_W1_APPROVED_UNTIL = "2026-12-04T00:00:00+00:00"
_EXPIRES = OWNER_W1_APPROVED_UNTIL
# The shipped matrix is the source of truth for named exceptions and their renewals.
_NAMED_EXCEPTIONS = {
    "claude": ("open egress", "2027-01-03T00:00:00+00:00",
               "plans/amendments/seats-claude-open-egress-renewal-20261124.md"),
    "codex": ("unconfined", _EXPIRES, None),
    "grok": ("unconfined", _EXPIRES, None),
}
_COMMON_RECORD_FIELDS = {
    "schema", "window", "context_id", "account_label", "host_class", "host_digest",
    "operator_id", "board_outcome", "admission", "staged_read", "account_isolation",
    "co_seats", "containment", "containment_outcomes",
    "containment_binding", "egress", "rows", "observed_at", "qualification_keys",
    "record_digest", "source_attempt", "row_observations", *DIGEST_FIELDS,
}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def measurement(checks: dict, *, observation_digest=None) -> dict:
    payload = {"checks": checks, "observation_digest": observation_digest or digest(checks)}
    return {**payload, "evidence_digest": digest(payload)}


def readiness_rows() -> list[dict]:
    """Return the complete matrix; rows remain candidate until reduced W1 evidence passes."""
    from . import president_adapter
    from .seat_profiles import profile_for, registered_legs

    profiles = {
        profile.vendor: profile
        for leg in registered_legs()
        if (profile := profile_for(leg)) is not None
    }
    vendors = (*VENDORS, *(vendor for vendor in sorted(profiles) if vendor not in VENDORS))
    rows = []
    for kind in ("vendor", "remote"):
        for vendor in vendors:
            profile = profiles.get(vendor)
            exception, expiry, renewal_record = (
                _NAMED_EXCEPTIONS.get(vendor, (None, None, None))
                if kind == "vendor" else (None, None, None)
            )
            if profile is not None and (
                exception == "unconfined"
                or exception == "open egress" and profile.allowlist_id is not None
            ):
                exception = expiry = renewal_record = None
            rows.append({"id": f"{kind}:{vendor}", "kind": kind, "vendor": vendor,
                "route": "remote" if kind == "remote" else (
                    "jailed" if profile is not None else "local"),
                "claude_transport": "print" if vendor == "claude" else None,
                "profile_digest": None,
                "allowlist_id": profile.allowlist_id if profile is not None else None,
                "allowlist_digest": None, "tool_surface": None,
                "credential_lane": "subscription", "projection": None,
                "host_classes": ["standard"], "qualification_record": None,
                "live_evidence_digest": None,
                "status": "remote-pending" if kind == "remote" else "candidate",
                "exception": exception, "expiry": expiry, "renewal_record": renewal_record,
                "end_condition": "row window or owning phase exit",
                "interim_route": "degraded"})
    for entry in president_adapter.president_rung_inventory():
        vendor = {"fable": "claude", "sol": "codex"}.get(entry["rung"], entry["rung"])
        base = next(row for row in rows if row["id"] == f"vendor:{vendor}").copy()
        base.update(entry, id=f"president:{entry['rung']}:{entry['route']}", kind="president")
        rows.append(base)
    return rows


def window_rows_for(vendor: str):
    """Return the unique registered vendor's window-kit rows, or ``None``."""
    from .seat_profiles import profile_for, registered_legs

    matches = [profile.window for leg in registered_legs()
               if (profile := profile_for(leg)) is not None
               and profile.vendor == vendor and profile.window is not None]
    if len(matches) > 1:
        raise ValueError("window vendor profile is ambiguous")
    return matches[0] if matches else None


def _window_data_for(vendor: str):
    """Return the unique profile's separately registered window vocabulary."""
    from .seat_profiles import profile_for, registered_legs, window_data_for

    profiles = [profile for leg in registered_legs()
                if (profile := profile_for(leg)) is not None
                and profile.vendor == vendor and profile.window is not None]
    data = window_data_for(vendor)
    if (len(profiles) != 1 or data is None or data.vendor != vendor
            or data.leg != profiles[0].leg):
        return None
    return data


def _record_fields(data) -> set[str]:
    return {*_COMMON_RECORD_FIELDS, *data.record_fields.values()}


def _window_data_for_record(record):
    from .seat_profiles import registered_window_data

    matches = [data for data in registered_window_data()
               if set(data.record_fields.values()) <= set(record)]
    return matches[0] if len(matches) == 1 else None


def candidates(rows, host_class):
    """Select a context's rows: `host_classes` names where a row qualifies (OD-12), and a
    team context re-runs those same rows only for later `done-team` validation."""
    if host_class not in {"team", "standard"}:
        raise ValueError("window host class unavailable")
    return [row for row in rows if row["status"] == "candidate"
            and "standard" in row["host_classes"]]


def candidate_observations(rows, evidence):
    """Represent every selected row; board vendor records do not qualify president rows."""
    if isinstance(evidence, Mapping):
        identities = evidence
    else:
        identities = {}
        for leg in evidence:
            metadata = getattr(leg, "_leg_exec_metadata", None)
            identities[leg.leg] = metadata.get("record_digest") if metadata else None
    observations = []
    for row in rows:
        identity = identities.get(row["vendor"]) if row["kind"] == "vendor" else None
        observations.append({"id": row["id"],
            "outcome": "observed" if _is_digest(identity) else "unavailable",
            "exec_record_digest": identity if _is_digest(identity) else None})
    return observations


def preflight(*, is_available=None, auth_ok=None, composed_out=None):
    from .advisor_board.composition import compose_review_board_report, default_board_auth_ok
    from .advisor_board.registries import DEFAULT_HARNESS_REGISTRY
    from .advisor_board import backing
    available = is_available or DEFAULT_HARNESS_REGISTRY.is_available
    auth = auth_ok or default_board_auth_ok
    authorization = backing.prepare_review_composition_authorization()
    try:
        backing.revalidate_review_composition_authorization(authorization)
        states = {vendor: (bool(available(vendor)), bool(auth(vendor)))
                  for vendor in VENDORS[:4]}
    finally:
        backing.clear_review_composition_authorization()
    composed = compose_review_board_report(is_available=lambda vendor: states[vendor][0],
                                           auth_ok=lambda vendor: states[vendor][1])
    if composed_out is not None:  # a row window binds its snapshot to this composition
        composed_out.append(composed.board)
    return composed.policy_outcome("plan")


#: The live W1 owner grant (owner decision 2026-11-21: agents run the windows once the owner
#: approves one packet). The reviewed change that sets ``OWNER_W1_GRANT_SHA256`` and
#: ``OWNER_W1_PACKET_SHA256`` is the approval. Setting the constants proves nothing by itself:
#: the review of that change must check the owner's approval of the named packet. The grant
#: digest names the first line of one private grant file, minted on the designated host by
#: :func:`mint_w1_grant`. That line binds the host, the start window, the vendor, the standard
#: context, exactly one attempt, the packet digest and a nonce. ``None`` keeps live W1 closed.
OWNER_W1_GRANT_SHA256: str | None = None
OWNER_W1_PACKET_SHA256: str | None = None
#: The window vendor a grant can admit, and the only context `done-local` reads.
OWNER_W1_VENDOR = "gemini"
OWNER_W1_HOST_CLASS = "standard"
#: A start must leave the run's outer bound (7200 s), its kill grace (120 s) and cleanup,
#: collection, owner review, verification and export (3480 s) before the earlier of the
#: grant's end and the cutoff.
W1_COMPLETION_MARGIN_S = 10800
W1_GRANT_NAME = "w1-grant.jsonl"
W1_GRANT_SCHEMA = "seat_window_w1_grant.v1"
W1_ATTEMPT_SCHEMA = "seat_window_w1_attempt.v1"
W1_GRANT_FIELDS = ("schema", "host_digest", "not_before", "not_after", "vendor",
                   "host_class", "max_attempts", "packet_sha256", "nonce")
_W1_ATTEMPT_FIELDS = ("schema", "nonce", "attempt", "claimed_at", "previous_sha256")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_W1_GRANT_LIMIT = 8192


def _w1_grant_dir() -> Path:
    """The grant's fixed admission directory, from the account's passwd home, never from
    ``XDG_STATE_HOME`` or ``HOME``, so moving the state root cannot present a second copy."""
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "state" / "agent-harness" / \
        "w1-admission"


def _private_dir_fd(path: Path, *, create: bool) -> int:
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=directory)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                            | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = child
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("w1 admission directory unavailable")
        return directory
    except BaseException:
        os.close(directory)
        raise


def mint_w1_grant(*, not_before: str, not_after: str, packet_sha256: str) -> str:
    """Write this host's one W1 grant (never overwriting one) and return the digest the
    approval change pins. Runs on the designated host, after the owner approves the packet."""
    line = (json.dumps({"schema": W1_GRANT_SCHEMA, "host_digest": _host_digest(),
                        "not_before": not_before, "not_after": not_after,
                        "vendor": OWNER_W1_VENDOR, "host_class": OWNER_W1_HOST_CLASS,
                        "max_attempts": 1, "packet_sha256": packet_sha256,
                        "nonce": secrets.token_hex(16)},
                       sort_keys=True, separators=(",", ":")) + "\n").encode()
    directory = _private_dir_fd(_w1_grant_dir(), create=True)
    try:
        fd = os.open(W1_GRANT_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(line).hexdigest()


def _w1_journal(raw: bytes) -> tuple[dict, list[dict]] | None:
    """Parse grant bytes: the pinned grant line, then a hash-chained attempt journal."""
    lines = raw.split(b"\n")
    if len(raw) > _W1_GRANT_LIMIT or lines[-1] != b"" or len(lines) < 2:
        return None
    if hashlib.sha256(lines[0] + b"\n").hexdigest() != OWNER_W1_GRANT_SHA256:
        return None
    grant = json.loads(lines[0])
    if type(grant) is not dict or set(grant) != set(W1_GRANT_FIELDS):
        return None
    attempts, offset = [], len(lines[0]) + 1
    for number, line in enumerate(lines[1:-1], start=1):
        entry = json.loads(line)
        if (type(entry) is not dict or set(entry) != set(_W1_ATTEMPT_FIELDS)
                or entry["schema"] != W1_ATTEMPT_SCHEMA or entry["nonce"] != grant["nonce"]
                or entry["attempt"] != number
                or entry["previous_sha256"] != hashlib.sha256(raw[:offset]).hexdigest()):
            return None
        attempts.append(entry)
        offset += len(line) + 1
    return grant, attempts


def _w1_witnesses(nonce: str) -> int | None:
    """Count the independent per-attempt witnesses beside the grant, in the same fixed
    admission directory (never under ``XDG_STATE_HOME``), or ``None`` when they are not a
    contiguous run from 1."""
    root = _w1_grant_dir()
    try:
        numbers = sorted(int(match.group(1)) for path in root.glob(f"w1-attempt-{nonce}-*.json")
                         if (match := re.fullmatch(rf"w1-attempt-{nonce}-([1-9])\.json",
                                                   path.name)))
    except OSError:
        return None
    return len(numbers) if numbers == list(range(1, len(numbers) + 1)) else None


def _w1_grant_usable(grant: dict, attempts: list[dict], now: dt.datetime) -> bool:
    try:
        not_before = dt.datetime.fromisoformat(grant["not_before"])
        not_after = dt.datetime.fromisoformat(grant["not_after"])
        cutoff = dt.datetime.fromisoformat(OWNER_W1_APPROVED_UNTIL)
    except (TypeError, ValueError):
        return False
    if (grant["schema"] != W1_GRANT_SCHEMA or grant["vendor"] != OWNER_W1_VENDOR
            or grant["host_class"] != OWNER_W1_HOST_CLASS
            or grant["host_digest"] != _host_digest()
            or type(grant["max_attempts"]) is not int or grant["max_attempts"] != 1
            or not _is_digest(OWNER_W1_PACKET_SHA256)
            or grant["packet_sha256"] != OWNER_W1_PACKET_SHA256
            or type(grant["nonce"]) is not str or _NONCE.fullmatch(grant["nonce"]) is None
            or not_before.tzinfo is None or not_after.tzinfo is None):
        return False
    # Prior attempt evidence must be complete: the journal and the independent witnesses
    # agree, so removing either one (or restoring the grant's original bytes) refuses.
    if _w1_witnesses(grant["nonce"]) != len(attempts) or len(attempts) >= grant["max_attempts"]:
        return False
    latest_start = min(not_after, cutoff) - dt.timedelta(seconds=W1_COMPLETION_MARGIN_S)
    return not_before <= now <= latest_start


def owner_w1_grant(now: dt.datetime | None = None) -> dict | None:
    """The approved grant, when it can admit an attempt now on this host, else ``None``.
    Reads only."""
    if not _is_digest(OWNER_W1_GRANT_SHA256):
        return None
    now = _now() if now is None else now
    try:
        directory = _private_dir_fd(_w1_grant_dir(), create=False)
        try:
            fd = os.open(W1_GRANT_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=directory)
        finally:
            os.close(directory)
        try:
            info = os.fstat(fd)
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                    or not stat.S_ISREG(info.st_mode)):
                return None
            parsed = _w1_journal(os.read(fd, _W1_GRANT_LIMIT + 1))
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if parsed is None or not _w1_grant_usable(*parsed, now):
        return None
    return parsed[0]


def owner_w1_approved(now: dt.datetime | None = None) -> bool:
    """The live W1 gate: admit the grant's ONE attempt.

    Under an exclusive lock on the grant file, the grant and its journal are re-read and
    checked (:func:`_w1_grant_usable`), a hash-chained attempt line is appended and fsynced,
    and an independent witness is written beside the grant, all before anything else runs.
    The attempt counts whatever it later returns, a preflight refusal included, and is never
    released. Removing the witness or the journal line refuses further attempts; no
    environment variable moves either. A trusted operator who restores both from a copy is
    outside this guard; the runbook's ledger and the owner's quiet slot cover that case.
    """
    import fcntl
    if not _is_digest(OWNER_W1_GRANT_SHA256):
        return False
    now = _now() if now is None else now
    try:
        directory = _private_dir_fd(_w1_grant_dir(), create=False)
        try:
            fd = os.open(W1_GRANT_NAME, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=directory)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                info = os.fstat(fd)
                if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                        or not stat.S_ISREG(info.st_mode)):
                    return False
                raw = os.pread(fd, _W1_GRANT_LIMIT + 1, 0)
                parsed = _w1_journal(raw)
                if parsed is None or not _w1_grant_usable(*parsed, now):
                    return False
                grant, attempts = parsed
                attempt = len(attempts) + 1
                entry = {"schema": W1_ATTEMPT_SCHEMA, "nonce": grant["nonce"],
                         "attempt": attempt, "claimed_at": now.isoformat(),
                         "previous_sha256": hashlib.sha256(raw).hexdigest()}
                os.pwrite(fd, (json.dumps(entry, sort_keys=True, separators=(",", ":"))
                               + "\n").encode(), len(raw))
                os.fsync(fd)
                os.fsync(directory)
                witness = os.open(f"w1-attempt-{grant['nonce']}-{attempt}.json",
                                  os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                  | os.O_CLOEXEC, 0o600, dir_fd=directory)
                try:
                    os.write(witness, (json.dumps(entry, sort_keys=True) + "\n").encode())
                    os.fsync(witness)
                finally:
                    os.close(witness)
                os.fsync(directory)
                return True
            finally:
                os.close(fd)
        finally:
            os.close(directory)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _is_digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _check_measurement(value, fields_):
    return (type(value) is dict and set(value) == {"checks", "observation_digest",
                                                   "evidence_digest"}
            and type(value["checks"]) is dict and set(value["checks"]) == set(fields_)
            and all(item is True for item in value["checks"].values())
            and _is_digest(value["observation_digest"])
            and value["evidence_digest"] == digest(
                {key: value[key] for key in ("checks", "observation_digest")}))


def _containment_outcomes_valid(value, data):
    return (type(value) is dict
        and set(value) == set(data.containment_outcomes)
        and all(value[field] in outcomes
                for field, outcomes in data.containment_outcomes.items()))


def _json_value(value):
    """Convert frozen producer values to closed JSON without retaining secret bytes."""
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)
                if item.name != "content"}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return "<bytes>"
    if value is None or type(value) in (str, int, float, bool):
        return value
    if hasattr(value, "__dict__"):
        return {key: _json_value(item) for key, item in vars(value).items()
                if key != "content" and not key.startswith("_")}
    raise TypeError("window value is not closed JSON")


def _source_record(name, expected, *, root=None, file_digest=False):
    from . import president_adapter
    if not _is_digest(expected) or Path(name).name != name:
        raise ValueError("window source unavailable")
    observed = []
    value = _read_record((root or president_adapter.private_record_root()) / name,
                         digest_sink=observed)
    if type(value) is not dict:
        raise ValueError("window source unavailable")
    actual = observed[0] if file_digest else digest(value)
    if actual != expected:
        raise ValueError("window source unavailable")
    return value


def _find_exec_source_attempt(expected, *, root=None):
    from . import president_adapter
    if not _is_digest(expected):
        return None
    values = []
    for path in sorted((root or president_adapter.private_record_root()).glob("leg-*.json")):
        match = re.fullmatch(r"leg-([0-9a-f]{32})\.json", path.name)
        if match is None:
            continue
        seen = []
        try:
            record = _read_record(path, digest_sink=seen)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if (seen == [expected] and type(record) is dict
                and record.get("attempt_id") == match.group(1)):
            values.append(match.group(1))
    return values[0] if len(values) == 1 else None


def _stream_decisions(stream) -> list[str]:
    if stream is None:
        return []
    events = list(getattr(stream, "outside_events", ()) or ())
    for window in getattr(stream, "windows", ()) or ():
        events.extend(getattr(window, "events", ()) or ())
    return [event.decision for event in events
            if getattr(event, "decision", None) in {"allow", "deny"}]


def _egress_observation(context_id, measured, board, leg_observation) -> dict:
    direct = next((row for row in getattr(getattr(measured, "bracket", None), "rows", ())
                   if getattr(row, "row", None) == "b_direct_without_proxy"), None)
    return {"schema": "seat_window_egress.v1", "context_id": context_id,
            "measured_decisions": _stream_decisions(getattr(measured, "stream", None)),
            "board_decisions": _stream_decisions(getattr(leg_observation, "stream", None)),
            "direct_without_proxy": getattr(direct, "outcome", None),
            "board_sha256": board.board_sha256,
            "board_input_sha256": leg_observation.input_sha256,
            "delivered_turn_sha256": board.delivered_turn_sha256,
            "exec_record_sha256": board.exec_record_sha256,
            "tool_receipt_sha256": board.tool_receipt_sha256}


def _egress_checks(observation) -> dict:
    decisions = observation["measured_decisions"] + observation["board_decisions"]
    direct = observation["direct_without_proxy"] == "refused"
    return {"allowed_proxy": "allow" in decisions, "refused_proxy": "deny" in decisions,
            "direct_dns": direct, "direct_ip": direct}


def _record_contract_sha256(record):
    data = _window_data_for_record(record)
    return getattr(data, "contract_sha256", None)


def _binding_valid(binding, record):
    if type(binding) is not dict or set(binding) != set(BINDING_FIELDS):
        return False
    digest_keys = set(BINDING_FIELDS) - {"admission_class", "dependency_subject_sha256",
        "dependency_projection_sha256", "context_id", "account_label"}
    if any(not _is_digest(binding[key]) for key in digest_keys):
        return False
    return (type(binding["admission_class"]) is str
        and all(binding[key] is None or _is_digest(binding[key])
                for key in ("dependency_subject_sha256", "dependency_projection_sha256"))
        and binding["context_id"] == record["context_id"]
        and binding["account_label"] == record["account_label"]
        and binding["contract_sha256"] == _record_contract_sha256(record)
        and binding["jail_profile_sha256"] == record["profile_digest"]
        and binding["production_allowlist_sha256"] == record["allowlist_digest"]
        and binding["board_input_sha256"] == record["board_input_digest"])


def _private_observation_valid(observation):
    if type(observation) is not dict or set(observation) != set(PRIVATE_FIELDS):
        return False
    home = observation["home_row"]
    return (type(home) is dict and set(home) == {"baseline", "measured"}
        and all(value is None or _is_digest(value) for value in home.values())
        and type(observation["manifest_differences"]) is bool
        and (observation["delivered_copy_sha256"] is None
             or _is_digest(observation["delivered_copy_sha256"])))


READ_RECEIPT_FIELDS = ("schema", "access_observed", "tool_observed", "input_sha256",
                       "tree_digest")


def _read_receipt_valid(read, record) -> bool:
    """The board's retained staged-read receipt: a tool read observed in the staged tree the
    containment reduction bound (the reducer requires the board leg's launch binding to name
    the reference stage), for exactly the board input the record binds."""
    binding = record.get("containment_binding")
    return (type(read) is dict and set(read) == set(READ_RECEIPT_FIELDS)
            and read["schema"] == "seat_window_read.v1"
            and read["access_observed"] is True and read["tool_observed"] is True
            and _is_digest(read["tree_digest"])
            and type(binding) is dict
            and read["tree_digest"] == binding.get("stage_manifest_sha256")
            and read["input_sha256"] == record["board_input_digest"])


def _reconcile_sources(record, *, root=None):
    try:
        data = _window_data_for_record(record)
        if data is None:
            return False
        attempt = record["source_attempt"]
        if type(attempt) is not str or _ATTEMPT.fullmatch(attempt) is None:
            return False
        execution = _source_record("leg-" + attempt + ".json", record["exec_record_digest"],
                                   root=root, file_digest=True)
        observation_id = record["containment"]["observation_digest"]
        observation = _source_record("window-observation-" + observation_id + ".json",
                                     observation_id, root=root)
        egress_id = record["egress"]["observation_digest"]
        egress = _source_record("window-egress-" + egress_id + ".json", egress_id, root=root)
        read = _source_record("window-read-" + record["tool_receipt_digest"] + ".json",
                              record["tool_receipt_digest"], root=root)
        if (execution.get("schema") != "leg_exec.v1" or execution.get("attempt_id") != attempt
            or execution.get("vendor") != data.vendor
            or type(execution.get("exit_code")) is not int
            or execution["exit_code"] != 0 or execution.get("outcome") != "leg_execution_completed"
            or execution.get("model_turn") is not True or execution.get("verdict") is not True):
            return False
        if not _read_receipt_valid(read, record):
            return False
        if (not _private_observation_valid(observation)
            or not _containment_outcomes_valid(record["containment_outcomes"], data)
            or set(record["containment_outcomes"]) != set(record["containment"]["checks"])
            or record["containment"]["checks"] != {
                key: value in {"not_loaded", "pass"}
                for key, value in record["containment_outcomes"].items()}):
            return False
        if (set(egress) != {"schema", "context_id", "measured_decisions", "board_decisions",
                            "direct_without_proxy", "board_sha256", "board_input_sha256",
                            "delivered_turn_sha256", "exec_record_sha256",
                            "tool_receipt_sha256"}
            or egress["schema"] != "seat_window_egress.v1"
            or egress["context_id"] != record["context_id"]
            or any(type(values) is not list or any(item not in {"allow", "deny"} for item in values)
                   for values in (egress["measured_decisions"], egress["board_decisions"]))
            or _egress_checks(egress) != record["egress"]["checks"]
            or egress["board_sha256"] != record["board_digest"]
            or egress["board_input_sha256"] != record["board_input_digest"]
            or egress["delivered_turn_sha256"] != record["delivered_turn_digest"]
            or egress["exec_record_sha256"] != record["exec_record_digest"]
            or egress["tool_receipt_sha256"] != record["tool_receipt_digest"]):
            return False
        return _binding_valid(record["containment_binding"], record)
    except (AttributeError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return False


def _valid_record(record, now, source_root=None):
    if type(record) is not dict:
        return False
    data = _window_data_for_record(record)
    if data is None or set(record) != _record_fields(data):
        return False
    if record["schema"] != SCHEMA or record["window"] != "W1":
        return False
    if not all(type(record[key]) is str and _LABEL.fullmatch(record[key])
               for key in ("context_id", "account_label")):
        return False
    if not all(_is_digest(record[key]) for key in (*DIGEST_FIELDS, "host_digest", "record_digest")):
        return False
    if record["record_digest"] != digest({key: value for key, value in record.items()
                                           if key != "record_digest"}):
        return False
    if record["qualification_keys"] != {key: record[key] for key in KEY_FIELDS}:
        return False
    if (record["host_class"] not in {"team", "standard"}
        or type(record["operator_id"]) is not int or record["operator_id"] < 0
        or record["admission"] != "admitted" or record["board_outcome"] != "terminated"
        or record[data.record_fields["route"]] != data.route_literal
        or any(record[key] is not True for key in (
            data.record_fields["canonical"], "staged_read"))
        # A one-account host has no peer record; a team context needs a passing peer probe.
        or record["account_isolation"] is not (True if record["host_class"] == "team" else None)):
        return False
    if (type(record["co_seats"]) is not list
            or set(record["co_seats"]) != set(data.co_seats)
            or len(record["co_seats"]) != len(data.co_seats)):
        return False
    if not _w1_rows_valid(record, data):
        return False
    if not _containment_outcomes_valid(record["containment_outcomes"], data):
        return False
    try:
        observed = dt.datetime.fromisoformat(record["observed_at"])
        if observed.tzinfo is None or not dt.timedelta(0) <= now - observed <= dt.timedelta(days=30):
            return False
        if _w1_expired(record, data, now, source_root):
            return False
    except (TypeError, ValueError):
        return False
    return (_check_measurement(record["containment"], CONTAINMENT_FIELDS)
            and _check_measurement(record["egress"], EGRESS_FIELDS)
            and _reconcile_sources(record, root=source_root))


def _standard_records(records) -> list[dict]:
    """Return the contexts `done-local` reads: the designated standard host alone (OD-12).

    Every other context is ignored here, whatever its shape; later `done-team` validation
    owns the retained team fields and peer observations.
    """
    return [record for record in records
            if type(record) is dict and record.get("host_class") == "standard"]


def verify_records(records, *, now=None, source_root=None, vendor=None, window=None) -> dict:
    """With no vendor and window, Gemini W1 in the base shape (plus an ``unclassified``
    count); otherwise the named partition."""
    if vendor is not None or window not in (None, "W1"):
        return verify_window(records, vendor or OWNER_W1_VENDOR, window or "W1", now=now,
                             source_root=source_root)
    result = verify_partitions(records, now=now, source_root=source_root)
    verdict = result["partitions"].get((OWNER_W1_VENDOR, "W1"))
    passed = bool(verdict and verdict["passed"])
    return {"schema": "seat_window_verification.v1", "window": "W1", "passed": passed,
            "records_valid": passed, "status": "done-local" if passed else "candidate",
            "code": "window_verified" if passed else "window_review_required",
            "unclassified": result["unclassified"]}


def reduce_readiness(records, *, now=None, source_root=None) -> list[dict]:
    """Reduce every partition: a passing partition sets only its own vendor's row (R4).
    A team context never sets a row status, and no path here emits `done-team`."""
    verdicts = verify_partitions(records, now=now, source_root=source_root)["partitions"]
    return _reduce_partitions(verdicts)


def export_records(records, destination: Path, *, reviewed=False, source_root=None,
                   vendor=None, window=None):
    if window == ROW_WINDOW:
        return _row_export(records, destination, vendor, reviewed=reviewed,
                           source_root=source_root)
    if reviewed is not True or not verify_records(records, source_root=source_root)["passed"]:
        raise ValueError("window export unavailable")
    records = [record for record in _standard_records(records)
               if classify(record) == (OWNER_W1_VENDOR, "W1")]
    public = {"schema": "seat_window_export.v1", "window": "W1", "pre_post_reviewed": True,
        "contexts": [{key: record[key] for key in (
            "context_id", "account_label", "host_class", "record_digest")} for record in records],
        "rows": [{key: row[key] for key in (
            "id", "status", "exception", "expiry", "qualification_record",
            "live_evidence_digest")} for row in reduce_readiness(records, source_root=source_root)]}
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.fchmod(fd, 0o644)
    with os.fdopen(fd, "w") as output:
        json.dump(public, output, sort_keys=True, indent=2)
        output.write("\n")
    return public


def _read_record(path: Path, *, digest_sink=None):
    directory = seat_jail.open_dir_nofollow(path.parent)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("window storage unavailable")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                or not stat.S_ISREG(info.st_mode) or info.st_size > 16384):
                raise ValueError("window record unavailable")
            raw = os.read(fd, 16385)
            if len(raw) > 16384:
                raise ValueError("window record unavailable")
            if digest_sink is not None:
                digest_sink.append(hashlib.sha256(raw).hexdigest())
            return json.loads(raw)
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def account_isolation(peer_record: Path | None) -> bool | None:
    if peer_record is None:
        return None
    try:
        fd = os.open(peer_record, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except PermissionError:
        return True
    except OSError:
        return None
    os.close(fd)
    return False


def runtime_digest():
    root = Path(__file__).parent
    files_ = [*root.glob("*.py"), *root.glob("advisor_board/*.py"), *root.glob("seat_egress/*")]
    return digest({path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(files_) if path.is_file() and not path.is_symlink()})


def _read_machine_id(path="/etc/machine-id", limit=4096) -> str:
    """The machine id, read without blocking through one descriptor with a bound. A link is
    followed as before (distributions ship it as one); a non-regular, oversize or non-ASCII
    file raises ``OSError`` so the caller falls back exactly as for a missing one."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | getattr(os, "O_NOCTTY", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("machine id is not a regular file")
        raw = os.read(descriptor, limit + 1)
    finally:
        os.close(descriptor)
    if len(raw) > limit:
        raise OSError("machine id exceeds its bound")
    try:
        return raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise OSError("machine id is not ASCII") from exc


def _host_digest():
    try:
        identity = _read_machine_id()
    except OSError:
        identity = os.uname().nodename
    return hashlib.sha256(("seat-window-host\0" + identity).encode()).hexdigest()


def _dependency_binding(provider: str):
    from .executable_dependency_startup import current_dependency_for_provider
    dependency = current_dependency_for_provider(provider)
    if dependency is None:
        return None, None
    return dependency.subject_sha256, dependency.projection_digest


def _required_interfaces(jailq, panel):
    jail_names = ("plant_layout", "build_qualification_input", "definition_probe",
                  "ContextBinding", "ContainmentInputs", "reduce_containment")
    panel_names = ("WindowLaunchSpec", "WindowBoardSpec", "window_control_launch",
                   "window_board_launch")
    return all(hasattr(jailq, name) for name in jail_names) and all(
        hasattr(panel, name) for name in panel_names)


def _profile_plant_layout(jailq, *, plugin_form, window_rows):
    """Pass profile rows to the window supplier's explicit interface."""
    return jailq.plant_layout(plugin_form=plugin_form, window=window_rows)


def run_native_window(*, repo, monitoring_policy, host_class, model=None, vendor=None, row=None):
    """Run frozen I-15 through the vendor's supplier and assemble the containment reducer's
    sole input. ``row`` is a claimed row window (§6, §9); without it this is W1, unchanged."""
    from . import panel_invoker as panel, president_adapter, seat_window_supply
    if vendor is None:
        from .seat_profiles import default_window_data
        default = default_window_data()
        if default is None:
            return {"status": "candidate", "code": "window_supplier_unavailable"}
        vendor = default.vendor
    window_rows = window_rows_for(vendor)
    data = _window_data_for(vendor)
    jailq = seat_window_supply.available(vendor) if data is not None else None
    if (window_rows is None or data is None or jailq is None
            or not _required_interfaces(jailq, panel)):
        return {"status": "candidate", "code": "window_supplier_unavailable"}
    if host_class not in {"team", "standard"} or monitoring_policy != "bounded":
        raise ValueError("window policy unavailable")
    context_id = "c" + secrets.token_hex(16)[1:] if row is None else row.context_id
    account_label = "a" + secrets.token_hex(16)[1:]
    dependency_subject, dependency_projection = _dependency_binding(data.dependency_provider)
    selected_model = model or panel.DEFAULT_LEG_MODELS[data.model_leg]
    control_launch = getattr(panel, data.control_launcher, None)
    board_launch = getattr(panel, data.board_launcher, None)
    if not callable(control_launch) or not callable(board_launch):
        return {"status": "candidate", "code": "window_supplier_unavailable"}
    leg_kwargs = {} if row is None else {"leg": data.leg}
    kinds = data.launch_kinds if row is not None else None
    run = {"binding": None, "binding_digest": None, "reference": None, "status": "aborted"}

    def _abort_receipt(board=None):
        # §6.2: a run that ended after its binding still leaves a receipt and its counts.
        if row is None or run["binding_digest"] is None or run["status"] != "aborted":
            return
        try:
            write_completion(
                vendor=vendor, context_id=context_id,
                run_binding_digest=run["binding_digest"], status="aborted",
                board_input_sha256=run["binding"]["board_input_sha256"],
                board_stage_sha256=getattr(board, "board_stage_sha256", None),
                source_attempt=getattr(board, "source_attempt", None), sources={},
                counts=row.ledger.counts())
        except (OSError, ValueError):
            pass

    def _row_bind(qualification_input):
        reference = panel.window_reference_stage(qualification_input)
        if not _is_digest(reference):
            raise seat_window_supply.WindowRefused("window_stage_mismatch")
        snapshot = _snapshot_document(vendor, context_id, row.board)
        exceptions_sha256 = _write_row_file(f"window-exceptions-{vendor}-{context_id}.json",
                                            snapshot)
        row.ledger.bind(snapshot["entries"],
                        ledger_routes(vendor, snapshot["president_routes"]),
                        composition=snapshot["board_sha256"], board=row.board)
        binding, binding_digest = write_run_binding(
            vendor=vendor, context_id=context_id, account_label=account_label,
            attempt=row.attempt, data=data, exceptions_sha256=exceptions_sha256,
            board_input_sha256=panel.window_board_input_sha256(),
            reference_stage_sha256=reference, qualification_key=_launch_key(data))
        run.update(binding=binding, binding_digest=binding_digest, reference=reference)

    def _same_stage(result):
        stage = getattr(getattr(result, "binding", None), "stage_manifest_sha256", None)
        if row is not None and stage != run["reference"]:
            raise seat_window_supply.WindowRefused("window_stage_mismatch")
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="phase-loop-window-",
                                         dir=sandbox_policy.staging_root()) as temporary:
            base = Path(temporary)
            layout = _profile_plant_layout(
                jailq, plugin_form="nested", window_rows=window_rows,
            )
            q0 = jailq.build_qualification_input(layout, base)

            def launch(kind, qualification_input):
                spec = panel.WindowLaunchSpec(kind=kind, qualification_input=qualification_input,
                    model=selected_model, timeout_s=WINDOW_LAUNCH_TIMEOUT_S, **leg_kwargs)
                return control_launch(spec)

            help_result = launch("help", q0) if kinds is None or "help" in kinds else None
            plugin_result = None
            if (help_result is not None and help_result.help_lists_plugin is True
                    and (kinds is None or "plugin_validation" in kinds)):
                plugin_result = launch("plugin_validation", q0)
            elif "plugin_json" in getattr(jailq, "plugin_forms", ("plugin_json",)):
                layout = _profile_plant_layout(
                    jailq, plugin_form="plugin_json", window_rows=window_rows,
                )
            qualification_input = jailq.build_qualification_input(layout, base)
            if row is not None:
                _row_bind(qualification_input)
            controls = [_same_stage(launch("tree_control", qualification_input)),
                        _same_stage(launch("runtime_control", qualification_input))]
            definition = jailq.definition_probe(layout, controls)
            if definition.credentialed_control_required:
                controls.extend((
                    _same_stage(launch("credentialed_tree_control", qualification_input)),
                    _same_stage(launch("credentialed_runtime_control", qualification_input))))
            measured = _same_stage(launch("measured", qualification_input))
            expired = _same_stage(launch("expired_copy", qualification_input))
            board_spec = panel.WindowBoardSpec(qualification_input=qualification_input,
                                               monitoring_policy=monitoring_policy, **leg_kwargs)
            board = board_launch(board_spec)
            if board.composition != "admitted":
                _abort_receipt(board)
                return {"status": "candidate", "code": "review_composition_refused"}
            leg_observation = getattr(board, data.board_fields["leg"], None)
            canonical = getattr(board, data.board_fields["canonical"], None)
            if leg_observation is None or canonical is None or (
                    row is not None and board.board_stage_sha256 != run["reference"]):
                _abort_receipt(board)
                return {"status": "candidate", "code": "window_reduction_unavailable"}
            context = jailq.ContextBinding(context_id=context_id, account_label=account_label,
                dependency_subject_sha256=dependency_subject,
                dependency_projection_sha256=dependency_projection)
            inputs = jailq.ContainmentInputs(context=context, layout=layout, help=help_result,
                plugin_validation=plugin_result, controls=tuple(controls), measured=measured,
                expired_copy=expired, board=leg_observation)
            reduction = jailq.reduce_containment(inputs)
    except seat_window_supply.WindowRefused:
        _abort_receipt()
        raise

    private = _json_value(reduction.private)
    outcomes = _json_value(reduction.containment)
    checks = _json_value(reduction.checks)
    binding = _json_value(reduction.binding)
    owner = _json_value(reduction.owner_summary)
    if (type(private) is not dict or set(private) != set(PRIVATE_FIELDS)
        or digest(private) != reduction.observation_sha256
        or not _containment_outcomes_valid(outcomes, data)
        or type(checks) is not dict or checks != {
            key: value in {"not_loaded", "pass"} for key, value in outcomes.items()}
        or type(binding) is not dict or set(binding) != set(BINDING_FIELDS)
        or binding["context_id"] != context_id or binding["account_label"] != account_label
        or binding["contract_sha256"] != data.contract_sha256
        or leg_observation.input_sha256 != binding["board_input_sha256"]
        or type(owner) is not dict or set(owner) != set(OWNER_SUMMARY_FIELDS)
        or owner["schema"] != "seat_window_owner_summary.v1"
        or owner["context_id"] != context_id
        or type(owner["counted_lookups"]) is not dict
        or type(owner["uncounted_home_lookups"]) is not dict):
        _abort_receipt(board)
        return {"status": "candidate", "code": "window_reduction_unavailable"}
    president_adapter.write_private_record(
        "window-observation-" + reduction.observation_sha256 + ".json", private)
    egress_source = _egress_observation(context_id, measured, board, leg_observation)
    egress_identity = digest(egress_source)
    president_adapter.write_private_record("window-egress-" + egress_identity + ".json",
                                           egress_source)
    window = "W1" if row is None else ROW_WINDOW
    owner_name = ("owner-summary-W1-" + context_id + ".json" if row is None
                  else f"owner-summary-row-{vendor}-{context_id}.json")
    president_adapter.write_private_record(owner_name, owner)
    selected = candidates(readiness_rows(), host_class) if row is None else [
        item for item in readiness_rows() if item["id"] == f"vendor:{vendor}"]
    source_attempt = _find_exec_source_attempt(board.exec_record_sha256)
    if row is not None and (source_attempt is None or source_attempt != board.source_attempt):
        _abort_receipt(board)
        return {"status": "candidate", "code": "window_reduction_unavailable"}
    record = {"schema": SCHEMA, "window": window, "context_id": context_id,
        "account_label": account_label, "host_class": host_class, "host_digest": _host_digest(),
        "operator_id": os.getuid(), "board_outcome": board.board_outcome,
        "admission": "admitted" if reduction.admitted else "withheld_private",
        data.record_fields["canonical"]: canonical, "staged_read": board.staged_read,
        data.record_fields["route"]: data.route_literal,
        "account_isolation": None, "co_seats": list(board.co_seats),
        "containment": measurement(checks, observation_digest=reduction.observation_sha256),
        "containment_outcomes": outcomes, "containment_binding": binding,
        "egress": measurement(_egress_checks(egress_source), observation_digest=egress_identity),
        "rows": [item["id"] for item in selected], "observed_at": _now().isoformat(),
        "runtime_digest": runtime_digest(), "profile_digest": binding["jail_profile_sha256"],
        "allowlist_digest": binding["production_allowlist_sha256"],
        "board_digest": board.board_sha256, "exec_record_digest": board.exec_record_sha256,
        "tool_receipt_digest": board.tool_receipt_sha256,
        "board_input_digest": leg_observation.input_sha256,
        "delivered_turn_digest": board.delivered_turn_sha256,
        "source_attempt": source_attempt,
        "row_observations": candidate_observations(selected, board.leg_exec_records)}
    if row is None:
        record["qualification_keys"] = {key: record[key] for key in KEY_FIELDS}
        return record
    # §6.3 check 4: the key is the one the board leg's launch attested, beside its exec.
    try:
        attested = _read_record(_private_root() / f"window-launch-{source_attempt}.json")
        launch_key = attested["launch"]["qualification_key"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        _abort_receipt(board)
        return {"status": "candidate", "code": "window_reduction_unavailable"}
    if launch_key != run["binding"]["qualification_key"]:
        _abort_receipt(board)
        return {"status": "candidate", "code": "window_key_stale"}
    record["qualification_keys"] = dict(launch_key)
    record["row_observations"] = [{"id": f"vendor:{vendor}", "outcome": "observed",
                                   "exec_record_digest": board.exec_record_sha256}]
    record["runtime_digest"] = run["binding"]["runtime_digest"]
    names = _row_source_names(vendor, context_id, record)
    root = _private_root()
    try:
        sources = {label: _file_sha256(root / name) for label, name in names.items()}
    except OSError:
        _abort_receipt(board)
        return {"status": "candidate", "code": "window_reduction_unavailable"}
    receipt, completion_digest = write_completion(
        vendor=vendor, context_id=context_id, run_binding_digest=run["binding_digest"],
        status="completed", board_input_sha256=run["binding"]["board_input_sha256"],
        board_stage_sha256=board.board_stage_sha256, source_attempt=board.source_attempt,
        sources=sources, counts=row.ledger.counts())
    run["status"] = "completed"
    record["observed_at"] = receipt["completed_at"]
    record["run_binding_digest"] = run["binding_digest"]
    record["completion_digest"] = completion_digest
    return record


def qualify(*, window, monitoring_policy, repo=".", host_class="standard", attended=False,
            peer_record=None, model=None, vendor=None):
    from . import president_adapter
    if window == ROW_WINDOW and monitoring_policy == "bounded":
        kwargs = {"monitoring_policy": monitoring_policy, "repo": repo,
                  "host_class": host_class, "attended": attended, "model": model,
                  "peer_record": peer_record}
        if vendor is None:
            return qualify_batch(**kwargs)
        return _qualify_row(vendor=vendor, **kwargs)
    if window != "W1" or monitoring_policy != "bounded":
        raise ValueError("window policy unavailable")
    from .seat_profiles import default_window_data
    default = default_window_data()
    # The grant admits one vendor in the one standard context, so a team context or another
    # window vendor never claims an attempt slot or reaches preflight.
    if host_class != OWNER_W1_HOST_CLASS or (
            vendor or (None if default is None else default.vendor)) != OWNER_W1_VENDOR:
        return {"status": "candidate", "code": "window_owner_approval_required"}
    if not owner_w1_approved():
        return {"status": "candidate", "code": "window_owner_approval_required"}
    outcome = preflight()
    if outcome.status != "admitted":
        return {"status": "candidate", "code": outcome.code}
    if not attended:
        return {"status": "candidate", "code": "window_attendance_required"}
    from .seat_profiles import profile_for, registered_legs

    if vendor is None:
        from .seat_profiles import default_window_data
        default = default_window_data()
        vendor = None if default is None else default.vendor
    if vendor != OWNER_W1_VENDOR:
        return {"status": "candidate", "code": "window_owner_approval_required"}
    profiles = [profile for leg in registered_legs()
                if (profile := profile_for(leg)) is not None and profile.vendor == vendor]
    profile = profiles[0] if len(profiles) == 1 else None
    if (profile is None or profile.window is None
        or not seat_jail.execfind_pass_recorded(seat_jail.jail_profile_digest(profile.leg))
        or profile.allowlist_id is not None and seat_egress_proxy.unavailable_reason() is not None):
        return {"status": "candidate", "code": "window_host_readiness_required"}
    record = run_native_window(repo=Path(repo), monitoring_policy=monitoring_policy,
                               host_class=host_class, model=model, vendor=vendor)
    if record.get("schema") != SCHEMA:
        return record
    record["account_isolation"] = account_isolation(Path(peer_record) if peer_record else None)
    record["record_digest"] = digest(record)
    president_adapter.write_private_record("window-W1-" + record["context_id"] + ".json", record)
    return {"status": "candidate", "code": "window_review_required"}


# ======================================================================================
# K-1: row windows for every vendor (contract seats-window-kit-k1-contract.md r4).
# ======================================================================================

ROW_WINDOW = "row"
WINDOWS = ("W1", ROW_WINDOW)
ROW_GRANT_SCHEMA = "seat_window_row_grant.v1"
ROW_ATTEMPT_SCHEMA = "seat_window_row_attempt.v1"
RUN_BINDING_SCHEMA = "seat_window_run.v1"
COMPLETION_SCHEMA = "seat_window_complete.v1"
SNAPSHOT_SCHEMA = "seat_window_exceptions.v1"
#: A row start leaves the run's outer bound (7200 s), kill grace (120 s) and cleanup,
#: collection, owner review, verification and export before the grant's end (as W1).
ROW_COMPLETION_MARGIN_S = 10800
#: §6.3 check 7 and the legacy W1 interval: the run's outer bound plus its kill grace.
RUN_OUTER_BOUND_S = 7320
ROW_GRANT_FIELDS = ("schema", "host_digest", "host_class", "operator_uid", "vendor",
                    "window", "not_before", "not_after", "max_attempts", "packet_sha256",
                    "release_identity", "launch_envelope", "nonce")
_ROW_ATTEMPT_FIELDS = ("schema", "nonce", "attempt", "claimed_at", "context_id",
                       "host_digest", "operator_uid", "previous_sha256")
RUN_BINDING_FIELDS = ("schema", "vendor", "window", "context_id", "account_label",
                      "host_digest", "host_class", "operator_uid", "grant_sha256", "attempt",
                      "started_at", "deadline", "runtime_digest", "release_identity",
                      "exceptions_sha256", "qualification_key", "board_input_sha256",
                      "reference_stage_sha256")
COMPLETION_FIELDS = ("schema", "run_binding_digest", "status", "completed_at",
                     "board_input_sha256", "board_stage_sha256", "source_attempt", "sources",
                     "counts")
ROW_KEY_FIELDS = ("profile_digest", "allowlist_digest", "falsifier_layout",
                  "projection_digest", "variant", "host_identity", "arch", "runtime_digest")
ROW_EXTRA_FIELDS = ("run_binding_digest", "completion_digest")
#: The W1 run's contemporaneous private record that links a W1 context to its grant attempt
#: (K1-T2). The base W1 run writes none, so a real W1 record gets the conservative rule.
W1_LINK_SCHEMA = "seat_window_w1_attempt_link.v1"
_ROW_GRANT_LIMIT = 16384


class WindowClaimRefused(ValueError):
    """A grant read or claim refused before any login; ``code`` is a closed slug."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _iso_time(value):
    try:
        parsed = dt.datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_identity(root: Path | None = None) -> str:
    """§8: the sha256 of the files ``runtime_digest`` hashes, less ``seat_window_grants.py``,
    so publishing a grant pin never moves the identity the grant names. ``root`` is the
    package directory (this one by default)."""
    root = Path(__file__).parent if root is None else Path(root)
    files_ = [*root.glob("*.py"), *root.glob("advisor_board/*.py"), *root.glob("seat_egress/*")]
    return digest({path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(files_) if path.is_file() and not path.is_symlink()
                   and path.relative_to(root).as_posix() != "seat_window_grants.py"})


# --- K1-T1: the grants module's grammar, read from its checked bytes, never imported. ---

_GRANTS_PATH = Path(__file__).with_name("seat_window_grants.py")
_GRANT_NAMES = ("ROW_GRANTS", "RETIRED_ROW_GRANTS")


def _pin_valid(pin) -> bool:
    return (type(pin) is tuple and len(pin) == 3 and _is_digest(pin[0]) and _is_digest(pin[1])
            and _iso_time(pin[2]) is not None)


def _literal_table(node):
    import ast
    if not isinstance(node, ast.Dict) or any(key is None for key in node.keys):
        raise WindowClaimRefused("window_grants_invalid")
    keys = [key.value if isinstance(key, ast.Constant) else None for key in node.keys]
    if any(type(key) is not str for key in keys) or len(set(keys)) != len(keys):
        raise WindowClaimRefused("window_grants_invalid")
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise WindowClaimRefused("window_grants_invalid") from exc


def row_grant_pins(source: bytes | None = None):
    """Parse the grants module from its bytes: exactly one assignment to each of
    ``ROW_GRANTS`` and ``RETIRED_ROW_GRANTS`` and nothing else, literal tables keyed by
    table vendors, every pin a ``(64-hex, 64-hex, aware ISO time)`` tuple, retired pins a
    vendor → tuple of pins, none equal to the active pin. Returns ``(active, retired)``."""
    import ast
    from .seat_window_supply import SUPPLIERS
    try:
        raw = _GRANTS_PATH.read_bytes() if source is None else source
        tree = ast.parse(raw)
    except (OSError, SyntaxError, ValueError) as exc:
        raise WindowClaimRefused("window_grants_invalid") from exc
    found = {}
    for node in tree.body:
        if (not isinstance(node, ast.Assign) or len(node.targets) != 1
                or not isinstance(node.targets[0], ast.Name)
                or node.targets[0].id not in _GRANT_NAMES or node.targets[0].id in found):
            raise WindowClaimRefused("window_grants_invalid")
        found[node.targets[0].id] = _literal_table(node.value)
    if set(found) != set(_GRANT_NAMES):
        raise WindowClaimRefused("window_grants_invalid")
    active, retired = found["ROW_GRANTS"], found["RETIRED_ROW_GRANTS"]
    if not set(active) <= set(SUPPLIERS) or not set(retired) <= set(SUPPLIERS):
        raise WindowClaimRefused("window_grants_invalid")
    if not all(_pin_valid(pin) for pin in active.values()):
        raise WindowClaimRefused("window_grants_invalid")
    for vendor, pins in retired.items():
        if (type(pins) is not tuple or not all(_pin_valid(pin) for pin in pins)
                or len(set(pins)) != len(pins) or active.get(vendor) in pins):
            raise WindowClaimRefused("window_grants_invalid")
    return active, retired


# --- §8: the row grant file, its hash-chained journal and the attempt witnesses. ---

def _row_admission_dir() -> Path:
    """From the account's passwd home, never ``XDG_STATE_HOME`` or ``HOME`` (as W1)."""
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "state" / "agent-harness" / \
        "window-admission"


def _private_root() -> Path:
    from . import president_adapter
    return president_adapter.private_record_root()


def mint_row_grant(vendor: str, window: str = ROW_WINDOW, *, not_before: str, not_after: str,
                   packet_sha256: str, launch_envelope: Mapping[str, int],
                   max_attempts: int = 1) -> str:
    """Write one new row grant on the designated host (never overwriting one) and return the
    digest a reviewed pin change publishes. Runs after the owner approves the packet."""
    from .seat_window_supply import ENVELOPE_ITEMS, SUPPLIERS
    if vendor not in SUPPLIERS or window != ROW_WINDOW or max_attempts not in (1, 2):
        raise WindowClaimRefused("window_grant_unavailable")
    if set(launch_envelope) != set(ENVELOPE_ITEMS):
        raise WindowClaimRefused("window_envelope_invalid")
    nonce = secrets.token_hex(16)
    line = (json.dumps({"schema": ROW_GRANT_SCHEMA, "host_digest": _host_digest(),
                        "host_class": OWNER_W1_HOST_CLASS, "operator_uid": os.getuid(),
                        "vendor": vendor, "window": window, "not_before": not_before,
                        "not_after": not_after, "max_attempts": max_attempts,
                        "packet_sha256": packet_sha256,
                        "release_identity": release_identity(),
                        "launch_envelope": dict(launch_envelope), "nonce": nonce},
                       sort_keys=True, separators=(",", ":")) + "\n").encode()
    directory = _private_dir_fd(_row_admission_dir(), create=True)
    try:
        fd = os.open(f"row-grant-{vendor}-{nonce}.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(line).hexdigest()


def _row_journal(raw: bytes, grant_sha256: str):
    """The pinned grant line and its hash-chained attempts, or ``None`` when any part of the
    file disagrees (a corrupt or partial journal)."""
    lines = raw.split(b"\n")
    if len(raw) > _ROW_GRANT_LIMIT or lines[-1] != b"" or len(lines) < 2:
        return None
    if hashlib.sha256(lines[0] + b"\n").hexdigest() != grant_sha256:
        return None
    try:
        grant = json.loads(lines[0])
        if type(grant) is not dict or set(grant) != set(ROW_GRANT_FIELDS):
            return None
        attempts, offset = [], len(lines[0]) + 1
        for number, line in enumerate(lines[1:-1], start=1):
            entry = json.loads(line)
            if (type(entry) is not dict or set(entry) != set(_ROW_ATTEMPT_FIELDS)
                    or entry["schema"] != ROW_ATTEMPT_SCHEMA or entry["nonce"] != grant["nonce"]
                    or entry["attempt"] != number
                    or entry["previous_sha256"] != hashlib.sha256(raw[:offset]).hexdigest()):
                return None
            attempts.append(entry)
            offset += len(line) + 1
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return grant, attempts


def _witness_name(vendor: str, nonce: str, number: int) -> str:
    return f"window-attempt-{vendor}-{nonce}-{number}.json"


def _row_witnesses(vendor: str, nonce: str, root: Path) -> list[dict] | None:
    """The contiguous witnesses from 1, read through the private-record reader, or ``None``."""
    try:
        numbers = sorted(int(match.group(1)) for path in root.glob(
            f"window-attempt-{vendor}-{nonce}-*.json")
            if (match := re.fullmatch(rf"window-attempt-{vendor}-{nonce}-([1-9])\.json",
                                      path.name)))
        if numbers != list(range(1, len(numbers) + 1)):
            return None
        return [_read_record(root / _witness_name(vendor, nonce, number)) for number in numbers]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _find_row_grant(vendor: str, grant_sha256: str):
    """``(path, raw)`` of the one grant file whose first line hashes to the pin."""
    root = _row_admission_dir()
    try:
        directory = _private_dir_fd(root, create=False)
    except (OSError, ValueError) as exc:
        raise WindowClaimRefused("window_grant_unavailable") from exc
    try:
        matches = []
        for name in sorted(os.listdir(directory)):
            if re.fullmatch(rf"row-grant-{re.escape(vendor)}-[0-9a-f]{{32}}\.jsonl", name) is None:
                continue
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                        or not stat.S_ISREG(info.st_mode)):
                    raise WindowClaimRefused("window_grant_unavailable")
                raw = os.read(fd, _ROW_GRANT_LIMIT + 1)
            finally:
                os.close(fd)
            if hashlib.sha256(raw.split(b"\n", 1)[0] + b"\n").hexdigest() == grant_sha256:
                matches.append((root / name, raw))
    finally:
        os.close(directory)
    if len(matches) != 1:
        raise WindowClaimRefused("window_grant_unavailable")
    return matches[0]


def _row_grant_usable(vendor, window, grant, attempts, pin, now, witnesses) -> str | None:
    """The refusal code for this grant at ``now``, or ``None`` when it admits an attempt."""
    from .seat_window_supply import ENVELOPE_ITEMS
    not_before, not_after = _iso_time(grant["not_before"]), _iso_time(grant["not_after"])
    approved_until = _iso_time(pin[2])
    envelope = grant["launch_envelope"]
    if (grant["schema"] != ROW_GRANT_SCHEMA or grant["vendor"] != vendor
            or grant["window"] != window or not_before is None or not_after is None
            or type(grant["nonce"]) is not str or _NONCE.fullmatch(grant["nonce"]) is None
            or type(envelope) is not dict or set(envelope) != set(ENVELOPE_ITEMS)
            or not all(type(value) is int and value >= 0 for value in envelope.values())):
        return "window_grant_unavailable"
    if (grant["host_digest"] != _host_digest() or grant["host_class"] != OWNER_W1_HOST_CLASS
            or grant["operator_uid"] != os.getuid()):
        return "window_grant_wrong_host"
    if grant["packet_sha256"] != pin[1]:
        return "window_grant_packet_mismatch"
    if grant["release_identity"] != release_identity():
        return "window_grant_release_mismatch"
    if (type(grant["max_attempts"]) is not int or grant["max_attempts"] not in (1, 2)):
        return "window_grant_unavailable"
    if witnesses is None or len(witnesses) != len(attempts) or any(
            witness != attempt for witness, attempt in zip(witnesses, attempts)):
        return "window_journal_corrupt"
    if len(attempts) >= grant["max_attempts"]:
        return "window_attempts_exhausted"
    latest = min(not_after, approved_until) - dt.timedelta(seconds=ROW_COMPLETION_MARGIN_S)
    if not not_before <= now <= latest:
        return "window_grant_outside_window"
    return None


def _row_pin(vendor: str, window: str):
    active, _retired = row_grant_pins()
    pin = active.get(vendor)
    if window != ROW_WINDOW or pin is None:
        raise WindowClaimRefused("window_grant_unavailable")
    return pin


def window_grant(vendor: str, window: str = ROW_WINDOW, now: dt.datetime | None = None) -> bool:
    """Eligibility only: reads, takes no lock and calls no preflight, auth or provider."""
    now = _now() if now is None else now
    try:
        pin = _row_pin(vendor, window)
        _path, raw = _find_row_grant(vendor, pin[0])
        parsed = _row_journal(raw, pin[0])
        if parsed is None:
            return False
        grant, attempts = parsed
        witnesses = _row_witnesses(vendor, grant["nonce"], _private_root())
        return _row_grant_usable(vendor, window, grant, attempts, pin, now, witnesses) is None
    except (WindowClaimRefused, OSError, ValueError, TypeError):
        return False


def claim_window_attempt(vendor: str, window: str, context_id: str,
                         now: dt.datetime | None = None) -> dict:
    """§8's atomic claim, before preflight and so before any login: an exclusive
    non-blocking lock, a re-read and revalidation, then the hash-chained journal line
    (fsynced) and the witness. Every claim counts and none is released."""
    import fcntl
    now = _now() if now is None else now
    if type(context_id) is not str or _LABEL.fullmatch(context_id) is None:
        raise WindowClaimRefused("window_grant_unavailable")
    pin = _row_pin(vendor, window)
    path, _raw = _find_row_grant(vendor, pin[0])
    directory = _private_dir_fd(path.parent, create=False)
    try:
        fd = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise WindowClaimRefused("window_claim_locked") from exc
            raw = os.pread(fd, _ROW_GRANT_LIMIT + 1, 0)
            parsed = _row_journal(raw, pin[0])
            if parsed is None:
                raise WindowClaimRefused("window_journal_corrupt")
            grant, attempts = parsed
            root = _private_root()
            witnesses = _row_witnesses(vendor, grant["nonce"], root)
            code = _row_grant_usable(vendor, window, grant, attempts, pin, now, witnesses)
            if code is not None:
                raise WindowClaimRefused(code)
            number = len(attempts) + 1
            entry = {"schema": ROW_ATTEMPT_SCHEMA, "nonce": grant["nonce"], "attempt": number,
                     "claimed_at": now.isoformat(), "context_id": context_id,
                     "host_digest": grant["host_digest"], "operator_uid": os.getuid(),
                     "previous_sha256": hashlib.sha256(raw).hexdigest()}
            os.pwrite(fd, (json.dumps(entry, sort_keys=True, separators=(",", ":"))
                           + "\n").encode(), len(raw))
            os.fsync(fd)
            os.fsync(directory)
            from . import president_adapter
            president_adapter.write_private_record(
                _witness_name(vendor, grant["nonce"], number), entry)
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    return {"nonce": grant["nonce"], "number": number, "claimed_at": entry["claimed_at"],
            "context_id": context_id, "grant_sha256": pin[0], "pin": pin,
            "launch_envelope": dict(grant["launch_envelope"]),
            "not_after": grant["not_after"]}


# --- R6: the potential-route snapshot. ---

def _reachable_president_routes() -> list[str]:
    """The president rows a row window can reach: Fable alone (the envelope budgets only
    Fable; any descent is refused), on the route its adapter selects now."""
    from . import panel_invoker
    route = panel_invoker.window_fable_president_route()
    return [] if route is None else [f"president:fable:{route}"]


def _snapshot_entries(vendor: str, legs, president_routes=None) -> dict[str, dict]:
    """The subject, every composed co-seat (``legs``) and every reachable president rung
    (on its selected route), from the exact release's packaged matrix: route, exception,
    exclusive expiry and renewal record."""
    if president_routes is None:
        president_routes = _reachable_president_routes()
    wanted = {f"vendor:{vendor}", *(f"vendor:{leg}" for leg in legs), *president_routes}
    entries = {}
    for row in readiness_rows():
        if row["id"] in wanted:
            entries[row["id"]] = {"route": row["route"], "exception": row["exception"],
                                  "expiry": row["expiry"],
                                  "renewal_record": row["renewal_record"]}
    return entries


def ledger_routes(vendor: str, president_routes=None) -> dict[str, str | None]:
    """Which snapshot entry each credential-bearing item's dispatch uses by default. The
    president wrapper always names the route its adapter actually selects."""
    if president_routes is None:
        president_routes = _reachable_president_routes()
    fable = next((route for route in president_routes
                  if route.startswith("president:fable:")), None)
    routes = {"subject": f"vendor:{vendor}", "claude_seat": "vendor:claude",
              "codex_seat": "vendor:codex", "gemini_seat": "vendor:gemini",
              "grok_seat": "vendor:grok", "fable_president": fable,
              "claude_login_proof": "vendor:claude", "gemini_issuer": "vendor:gemini"}
    from .seat_window_supply import ENVELOPE_ITEMS
    return {item: routes.get(item) for item in ENVELOPE_ITEMS}


def _composed_legs(board) -> list[str]:
    return sorted(str(seat.harness or "") for seat in board.seats)


def _snapshot_document(vendor: str, context_id: str, board) -> dict:
    """Written after composition: bound to the composed board by its digest and holding
    exactly that board's co-seats."""
    from . import panel_invoker
    legs = [leg for leg in _composed_legs(board) if leg != vendor]
    president_routes = _reachable_president_routes()
    return {"schema": SNAPSHOT_SCHEMA, "vendor": vendor, "context_id": context_id,
            "release_identity": release_identity(),
            "board_sha256": panel_invoker._window_board_composition_digest(board),
            "co_seats": legs, "president_routes": president_routes,
            "entries": _snapshot_entries(vendor, legs, president_routes)}


# --- R8: the qualification key, at launch and at verification. ---

def _launch_key(data) -> dict:
    from .seat_profiles import profile_for
    from . import seat_qualification_key
    profile = profile_for(data.leg)
    if profile is None:
        raise ValueError("window_key_stale")
    variant = None
    if profile.variant is not None:
        variant, code = profile.variant(dict(os.environ))
        if code is not None:
            raise ValueError("window_key_stale")
    allowlist = (seat_egress_proxy.allowlist_ref(profile.allowlist_id).content_digest
                 if profile.allowlist_id is not None else None)
    try:
        from .seat_route import _projection_for_launch
        projection = _projection_for_launch(profile, dict(os.environ))
    except Exception:
        projection = None
    key = seat_qualification_key.key_for_launch(profile, variant=variant,
                                                allowlist_digest=allowlist,
                                                projection=projection)
    return {"profile_digest": key.profile_digest, "allowlist_digest": key.allowlist_digest,
            "falsifier_layout": key.falsifier_layout, "projection_digest": key.projection_digest,
            "variant": key.variant, "host_identity": key.host_identity,
            "arch": seat_jail.host_arch(), "runtime_digest": runtime_digest()}


def _key_current(record, data) -> bool:
    """R8 on the designated host: the same key over today's resolved inputs, this arch, and
    a recorded execfind pass. ``runtime_digest`` is provenance only."""
    try:
        current = _launch_key(data)
    except Exception:
        return False
    recorded = record["qualification_keys"]
    if (type(recorded) is not dict or set(recorded) != set(ROW_KEY_FIELDS)
            or any(recorded[key] != current[key] for key in ROW_KEY_FIELDS
                   if key != "runtime_digest")):
        return False
    try:
        return bool(seat_jail.execfind_pass_recorded(recorded["profile_digest"]))
    except Exception:
        return False


# --- §6: the run binding and the completion receipt. ---

def _write_row_file(name: str, value: dict) -> str:
    from . import president_adapter
    path = president_adapter.write_private_record(name, value)
    return _file_sha256(path)


def write_run_binding(*, vendor, context_id, account_label, attempt, data,
                      exceptions_sha256, board_input_sha256, reference_stage_sha256,
                      qualification_key) -> tuple[dict, str]:
    started = _now()
    pin_until = _iso_time(attempt["pin"][2])
    not_after = _iso_time(attempt["not_after"])
    deadline = (min(not_after, pin_until) - dt.timedelta(seconds=ROW_COMPLETION_MARGIN_S))
    binding = {"schema": RUN_BINDING_SCHEMA, "vendor": vendor, "window": ROW_WINDOW,
               "context_id": context_id, "account_label": account_label,
               "host_digest": _host_digest(), "host_class": OWNER_W1_HOST_CLASS,
               "operator_uid": os.getuid(), "grant_sha256": attempt["grant_sha256"],
               "attempt": {key: attempt[key] for key in
                           ("nonce", "number", "claimed_at", "context_id")},
               "started_at": started.isoformat(), "deadline": deadline.isoformat(),
               "runtime_digest": runtime_digest(), "release_identity": release_identity(),
               "exceptions_sha256": exceptions_sha256,
               "qualification_key": qualification_key,
               "board_input_sha256": board_input_sha256,
               "reference_stage_sha256": reference_stage_sha256}
    if not started <= deadline:
        raise WindowClaimRefused("window_grant_outside_window")
    return binding, _write_row_file(f"window-run-{vendor}-{context_id}.json", binding)


def write_completion(*, vendor, context_id, run_binding_digest, status, board_input_sha256,
                     board_stage_sha256, source_attempt, sources, counts) -> tuple[dict, str]:
    receipt = {"schema": COMPLETION_SCHEMA, "run_binding_digest": run_binding_digest,
               "status": status, "completed_at": _now().isoformat(),
               "board_input_sha256": board_input_sha256,
               "board_stage_sha256": board_stage_sha256, "source_attempt": source_attempt,
               "sources": dict(sources), "counts": dict(counts)}
    return receipt, _write_row_file(f"window-complete-{vendor}-{context_id}.json", receipt)


def _row_source_names(vendor, context_id, record) -> dict[str, str]:
    return {"exec": f"leg-{record['source_attempt']}.json",
            "observation": f"window-observation-{record['containment']['observation_digest']}.json",
            "egress": f"window-egress-{record['egress']['observation_digest']}.json",
            "read": f"window-read-{record['tool_receipt_digest']}.json",
            "exceptions": f"window-exceptions-{vendor}-{context_id}.json",
            "ledger": f"window-ledger-{vendor}-{context_id}.jsonl",
            "owner_summary": f"owner-summary-row-{vendor}-{context_id}.json",
            "launch": f"window-launch-{record['source_attempt']}.json"}


def _read_private_bytes(root: Path, name: str, limit: int = 1 << 20) -> bytes:
    """One retained source's bytes under the same 0700/0600 owner checks as records."""
    if Path(name).name != name:
        raise ValueError("window source unavailable")
    directory = seat_jail.open_dir_nofollow(root)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("window storage unavailable")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                    or not stat.S_ISREG(info.st_mode) or info.st_size > limit):
                raise ValueError("window source unavailable")
            return os.read(fd, limit + 1)
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _ledger_lines(raw: bytes) -> list[dict]:
    lines = []
    for number, line in enumerate(raw.split(b"\n")[:-1], start=1):
        entry = json.loads(line)
        if (type(entry) is not dict or entry.get("schema") != "seat_window_ledger.v1"
                or entry.get("seq") != number
                or entry.get("op") not in {"reserve", "dispatch", "start"}):
            raise ValueError("window ledger corrupt")
        lines.append(entry)
    if raw and not raw.endswith(b"\n"):
        raise ValueError("window ledger corrupt")
    return lines


def _ledger_counts(lines) -> dict[str, int]:
    from .seat_window_supply import ENVELOPE_ITEMS
    counts = {item: 0 for item in ENVELOPE_ITEMS}
    for entry in lines:
        if entry["item"] not in counts or type(entry["units"]) is not int:
            raise ValueError("window ledger corrupt")
        counts[entry["item"]] += entry["units"]
    return counts


# --- §6.3 and R1–R9: when a row record verifies. Each failure is a closed code. ---

def _row_journal_check(vendor, binding, attempt):
    """§6.3 check 3: ``None`` when the designated host's journal holds the attempt."""
    try:
        _path, raw = _find_row_grant(vendor, binding["grant_sha256"])
    except WindowClaimRefused:
        return "window_journal_unavailable"
    except (OSError, ValueError):
        return "window_journal_unavailable"
    parsed = _row_journal(raw, binding["grant_sha256"])
    if parsed is None:
        return "window_journal_corrupt"
    grant, attempts = parsed
    matching = [entry for entry in attempts if entry["attempt"] == attempt["number"]]
    if (len(matching) != 1 or grant["nonce"] != attempt["nonce"]
            or any(matching[0][key] != attempt[key] for key in ("claimed_at", "context_id"))
            or matching[0]["host_digest"] != binding["host_digest"]
            or matching[0]["operator_uid"] != binding["operator_uid"]):
        return "window_journal_corrupt"
    return None, grant


def _row_record_code(record, now, source_root, data) -> str | None:
    """``None`` when the row record verifies, else the closed failure code."""
    from . import seat_window_supply as supply
    from .seat_window_supply import ENVELOPE_ITEMS
    root = source_root or _private_root()
    vendor = data.vendor
    fields_ = {*_COMMON_RECORD_FIELDS, *data.record_fields.values(), *ROW_EXTRA_FIELDS}
    if set(record) != fields_ or record["schema"] != SCHEMA or record["window"] != ROW_WINDOW:
        return "window_record_invalid"
    if ROW_WINDOW not in data.windows:
        return "window_vendor_unavailable"
    if not all(type(record[key]) is str and _LABEL.fullmatch(record[key])
               for key in ("context_id", "account_label")):
        return "window_record_invalid"
    if not all(_is_digest(record[key]) for key in (*DIGEST_FIELDS, "host_digest",
                                                   "record_digest", *ROW_EXTRA_FIELDS)):
        return "window_record_invalid"
    if record["record_digest"] != digest({key: value for key, value in record.items()
                                           if key != "record_digest"}):
        return "window_record_invalid"
    if (record["host_class"] != OWNER_W1_HOST_CLASS
            or type(record["operator_id"]) is not int or record["operator_id"] < 0
            or record["admission"] != "admitted" or record["board_outcome"] != "terminated"
            or record[data.record_fields["route"]] != data.route_literal
            or any(record[key] is not True for key in (data.record_fields["canonical"],
                                                       "staged_read"))
            or record["account_isolation"] is not None):
        return "window_record_invalid"
    if (type(record["co_seats"]) is not list or set(record["co_seats"]) != set(data.co_seats)
            or len(record["co_seats"]) != len(data.co_seats)):
        return "window_record_invalid"
    row_id = f"vendor:{vendor}"
    observations = record["row_observations"]
    if (record["rows"] != [row_id] or type(observations) is not list or len(observations) != 1
            or observations[0] != {"id": row_id, "outcome": "observed",
                                   "exec_record_digest": record["exec_record_digest"]}):
        return "window_record_invalid"
    if not _containment_outcomes_valid(record["containment_outcomes"], data):
        return "window_record_invalid"
    observed = _iso_time(record["observed_at"])
    if observed is None or not dt.timedelta(0) <= now - observed <= dt.timedelta(days=30):
        return "window_record_stale"
    if not (_check_measurement(record["containment"], CONTAINMENT_FIELDS)
            and _check_measurement(record["egress"], EGRESS_FIELDS)
            and _reconcile_sources(record, root=source_root)):
        return "window_sources_mismatch"
    try:
        binding_raw = _read_private_bytes(root, f"window-run-{vendor}-{record['context_id']}.json")
        receipt_raw = _read_private_bytes(root,
                                          f"window-complete-{vendor}-{record['context_id']}.json")
        binding, receipt = json.loads(binding_raw), json.loads(receipt_raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "window_binding_unavailable"
    if (hashlib.sha256(binding_raw).hexdigest() != record["run_binding_digest"]
            or type(binding) is not dict or set(binding) != set(RUN_BINDING_FIELDS)
            or binding["schema"] != RUN_BINDING_SCHEMA):
        return "window_binding_mismatch"
    # Check 1: an active or retired pin of this vendor and window.
    try:
        active, retired = row_grant_pins()
    except WindowClaimRefused:
        return "window_grants_invalid"
    pins = [pin[0] for pin in (active.get(vendor), *retired.get(vendor, ())) if pin]
    if binding["grant_sha256"] not in pins:
        return "window_grant_unavailable"
    # Check 2: the witness.
    attempt = binding["attempt"]
    if type(attempt) is not dict or set(attempt) != {"nonce", "number", "claimed_at",
                                                     "context_id"}:
        return "window_binding_mismatch"
    try:
        witness = _read_record(root / _witness_name(vendor, attempt["nonce"],
                                                     attempt["number"]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "window_witness_mismatch"
    if (type(witness) is not dict or witness.get("schema") != ROW_ATTEMPT_SCHEMA
            or any(witness.get(key) != attempt[key] for key in ("nonce", "claimed_at",
                                                                 "context_id"))
            or witness.get("attempt") != attempt["number"]
            or witness.get("host_digest") != binding["host_digest"]
            or witness.get("operator_uid") != binding["operator_uid"]):
        return "window_witness_mismatch"
    # Check 3: the journal, on the designated host only.
    journal = _row_journal_check(vendor, binding, attempt)
    if isinstance(journal, str):
        return journal
    grant = journal[1]
    # Check 4: the binding.
    if (binding["vendor"] != vendor or binding["window"] != ROW_WINDOW
            or binding["context_id"] != record["context_id"]
            or attempt["context_id"] != record["context_id"]
            or binding["account_label"] != record["account_label"]
            or binding["host_digest"] != record["host_digest"]
            or binding["host_digest"] != _host_digest()
            or binding["host_class"] != record["host_class"]
            or binding["operator_uid"] != record["operator_id"]
            or binding["runtime_digest"] != record["runtime_digest"]
            or binding["qualification_key"] != record["qualification_keys"]):
        return "window_binding_mismatch"
    key = record["qualification_keys"]
    launch = record["containment_binding"]
    if (type(key) is not dict or key.get("profile_digest") != launch["jail_profile_sha256"]
            or key.get("allowlist_digest") != launch["production_allowlist_sha256"]
            or key.get("profile_digest") != record["profile_digest"]
            or key.get("allowlist_digest") != record["allowlist_digest"]
            or key.get("runtime_digest") != record["runtime_digest"]):
        return "window_key_stale"
    # The exec source's own launch attestation: written beside the exec record from what
    # the board leg's launch bound, keyed by its attempt and bound to its digest.
    try:
        attested = json.loads(_read_private_bytes(root, f"window-launch-{record['source_attempt']}.json"))
        bound = attested["launch"]["binding"]
        if (type(attested) is not dict or attested.get("schema") != "seat_window_launch.v1"
                or attested.get("attempt_id") != record["source_attempt"]
                or attested.get("exec_record_sha256") != record["exec_record_digest"]
                or attested["launch"].get("leg") != data.leg
                or attested["launch"].get("qualification_key") != key
                or bound.get("jail_profile_sha256") != launch["jail_profile_sha256"]
                or bound.get("allowlist_sha256") != launch["production_allowlist_sha256"]
                or bound.get("input_sha256") != record["board_input_digest"]
                or bound.get("stage_manifest_sha256") != binding["reference_stage_sha256"]):
            return "window_key_stale"
    except (OSError, ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        return "window_key_stale"
    # Check 5: the snapshot.
    names = _row_source_names(vendor, record["context_id"], record)
    try:
        snapshot_raw = _read_private_bytes(root, names["exceptions"])
        snapshot = json.loads(snapshot_raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "window_snapshot_mismatch"
    if (hashlib.sha256(snapshot_raw).hexdigest() != binding["exceptions_sha256"]
            or type(snapshot) is not dict or snapshot.get("schema") != SNAPSHOT_SCHEMA
            or snapshot.get("vendor") != vendor
            or snapshot.get("context_id") != record["context_id"]
            or snapshot.get("release_identity") != binding["release_identity"]
            or type(snapshot.get("entries")) is not dict):
        return "window_snapshot_mismatch"
    legs = sorted(record["co_seats"])
    if (snapshot.get("board_sha256") != record["board_digest"]
            or snapshot.get("co_seats") != legs
            or not {f"vendor:{vendor}", *(f"vendor:{leg}" for leg in legs)}
            <= set(snapshot["entries"])):
        return "window_snapshot_mismatch"
    president_routes = snapshot.get("president_routes")
    if (type(president_routes) is not list
            or any(type(route) is not str or not route.startswith("president:fable:")
                   for route in president_routes)
            or not set(president_routes) <= set(snapshot["entries"])):
        return "window_snapshot_mismatch"
    if (binding["release_identity"] == release_identity()
            and snapshot["entries"] != _snapshot_entries(vendor, legs, president_routes)):
        return "window_snapshot_mismatch"
    # Check 6: the completion receipt.
    if (hashlib.sha256(receipt_raw).hexdigest() != record["completion_digest"]
            or type(receipt) is not dict or set(receipt) != set(COMPLETION_FIELDS)
            or receipt["schema"] != COMPLETION_SCHEMA
            or receipt["run_binding_digest"] != record["run_binding_digest"]
            or receipt["status"] != "completed"
            or receipt["completed_at"] != record["observed_at"]):
        return "window_completion_mismatch"
    # Check 7: the deadline.
    claimed, started = _iso_time(attempt["claimed_at"]), _iso_time(binding["started_at"])
    deadline, completed = _iso_time(binding["deadline"]), _iso_time(receipt["completed_at"])
    if (None in (claimed, started, deadline, completed) or not claimed <= started <= deadline
            or not completed <= started + dt.timedelta(seconds=RUN_OUTER_BOUND_S)):
        return "window_deadline_exceeded"
    # Check 8: the sources.
    sources = receipt["sources"]
    if type(sources) is not dict or set(sources) != set(names):
        return "window_sources_mismatch"
    try:
        for label, name in names.items():
            if hashlib.sha256(_read_private_bytes(root, name)).hexdigest() != sources[label]:
                return "window_sources_mismatch"
        egress = _source_record(names["egress"], record["egress"]["observation_digest"],
                                root=source_root)
        read = _source_record(names["read"], record["tool_receipt_digest"], root=source_root)
        ledger = _ledger_lines(_read_private_bytes(root, names["ledger"]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "window_sources_mismatch"
    stage = receipt["board_stage_sha256"]
    if (receipt["source_attempt"] != record["source_attempt"]
            or egress["context_id"] != record["context_id"]
            or not _is_digest(stage) or read["tree_digest"] != stage
            or stage != binding["reference_stage_sha256"]
            or stage != launch["stage_manifest_sha256"]
            or len({binding["board_input_sha256"], receipt["board_input_sha256"],
                    egress["board_input_sha256"], record["board_input_digest"]}) != 1):
        return "window_sources_mismatch"
    # Check 9: the counts.
    try:
        counts = _ledger_counts(ledger)
    except ValueError:
        return "window_counts_mismatch"
    envelope = grant["launch_envelope"]
    if (counts != receipt["counts"] or set(envelope) != set(ENVELOPE_ITEMS)
            or any(counts[item] > envelope[item] for item in ENVELOPE_ITEMS)):
        return "window_counts_mismatch"
    if any(entry["op"] == "dispatch" and entry.get("stage_sha256") not in (None, stage)
           for entry in ledger):
        return "window_sources_mismatch"
    # R6: the subject's current exception at now, then every used entry at its launch time.
    for row in readiness_rows():
        if row["id"] == row_id and row["expiry"] and now >= dt.datetime.fromisoformat(
                row["expiry"]):
            return "window_exception_expired"
    for entry in ledger:
        # Every start that names a route: a debited dispatch, and a prepaid start the
        # call site's dispatch covered.
        if entry["op"] not in {"dispatch", "start"} or entry["route"] is None:
            continue
        bound = snapshot["entries"].get(entry["route"])
        if not supply.route_agrees(entry["route"], bound, {
                "mode": entry.get("resolved_mode"), "exception": entry.get("exception"),
                "expiry": entry.get("expiry"), "transport": entry.get("resolved_transport")}):
            return "window_exception_expired"
        launched = _iso_time(entry["launch_time"])
        expiry = bound.get("expiry")
        if launched is None or (expiry is not None and not launched < dt.datetime.fromisoformat(
                expiry)):
            return "window_exception_expired"
    # R8: the key over today's inputs on this (designated) host.
    if not _key_current(record, data):
        return "window_key_stale"
    return None


# --- R6's legacy W1 exception (K1-T2) and R7's own-rows comparison. ---

_ROW_ID = re.compile(r"(vendor|remote|president):[a-z0-9_:.-]+\Z")


def _w1_rows_valid(record, data) -> bool:
    """R7 for a legacy W1 record: its rows and row observations against each other, never
    against today's candidates. Only the window vendor's row is read."""
    rows, observations = record["rows"], record["row_observations"]
    if (type(rows) is not list or type(observations) is not list
            or any(type(row) is not str or _ROW_ID.fullmatch(row) is None for row in rows)
            or len(set(rows)) != len(rows)):
        return False
    if (len(observations) != len(rows)
            or any(type(row) is not dict or set(row) != {"id", "outcome", "exec_record_digest"}
                   or not (row["outcome"] == "observed" and _is_digest(row["exec_record_digest"])
                           or row["outcome"] == "unavailable"
                           and row["exec_record_digest"] is None)
                   for row in observations)):
        return False
    ids = [row["id"] for row in observations]
    own = f"vendor:{data.vendor}"
    if len(set(ids)) != len(ids) or set(ids) != set(rows) or own not in rows:
        return False
    return next(row for row in observations if row["id"] == own)[
        "exec_record_digest"] == record["exec_record_digest"]


def _w1_legacy_relaxed(record, source_root) -> bool:
    """Whether the relaxed W1 expiry applies: the W1 grant's host and class, the journal's
    first line hashing to the pin, exactly one attempt (with its witness, naming the same
    nonce) whose claim interval holds ``observed_at``, that claim inside the margin, and a
    contemporaneous private link record naming this context and that attempt."""
    try:
        observed = _iso_time(record["observed_at"])
        cutoff = _iso_time(OWNER_W1_APPROVED_UNTIL)
        if (observed is None or not _is_digest(OWNER_W1_GRANT_SHA256)
                or not observed < cutoff or record["host_class"] != OWNER_W1_HOST_CLASS):
            return False
        directory = _private_dir_fd(_w1_grant_dir(), create=False)
        try:
            fd = os.open(W1_GRANT_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                        or not stat.S_ISREG(info.st_mode)):
                    return False
                parsed = _w1_journal(os.read(fd, _W1_GRANT_LIMIT + 1))
            finally:
                os.close(fd)
        finally:
            os.close(directory)
        if parsed is None:
            return False
        grant, attempts = parsed
        if grant["host_digest"] != record["host_digest"] or \
                grant["host_class"] != OWNER_W1_HOST_CLASS:
            return False
        bound = dt.timedelta(seconds=RUN_OUTER_BOUND_S)
        within = [entry for entry in attempts
                  if (claimed := _iso_time(entry["claimed_at"])) is not None
                  and claimed <= observed <= claimed + bound]
        if len(within) != 1:
            return False
        attempt = within[0]
        witness_path = _w1_grant_dir() / f"w1-attempt-{grant['nonce']}-{attempt['attempt']}.json"
        witness = json.loads(witness_path.read_bytes())
        if witness != attempt or witness.get("nonce") != grant["nonce"]:
            return False
        latest = min(_iso_time(grant["not_after"]), cutoff) - dt.timedelta(
            seconds=W1_COMPLETION_MARGIN_S)
        if not _iso_time(attempt["claimed_at"]) <= latest:
            return False
        link = _read_record((source_root or _private_root())
                            / f"window-W1-attempt-{record['context_id']}.json")
        return (type(link) is dict and link == {
            "schema": W1_LINK_SCHEMA, "context_id": record["context_id"],
            "nonce": grant["nonce"], "attempt": attempt["attempt"]})
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _w1_expired(record, data, now, source_root) -> bool:
    rows = readiness_rows()
    if _w1_legacy_relaxed(record, source_root):
        rows = [row for row in rows if row["id"] == f"vendor:{data.vendor}"]
    elif now >= dt.datetime.fromisoformat(_EXPIRES):
        return True
    return any(row["expiry"] and now >= dt.datetime.fromisoformat(row["expiry"])
               for row in rows)


# --- R3/R4: partitions. ---

class UnreadableRecord:
    """A record file the reader refused; it fails only the partition its name names."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name


def _partition_of_name(name: str):
    if re.fullmatch(r"window-W1-.*\.json", name):
        return (OWNER_W1_VENDOR, "W1")
    match = re.fullmatch(r"window-row-([a-z]+)-.*\.json", name)
    if match is not None:
        from .seat_window_supply import SUPPLIERS
        return (match.group(1), ROW_WINDOW) if match.group(1) in SUPPLIERS else None
    return None


def classify(record):
    """``(vendor, window)`` for a classified record, else ``None`` (counted, inert)."""
    from . import seat_window_supply
    if type(record) is not dict:
        return None
    data = _window_data_for_record(record)
    window = record.get("window")
    if data is None or window not in WINDOWS or window not in data.windows:
        return None
    if window == ROW_WINDOW and seat_window_supply.available(data.vendor) is None:
        return None
    return (data.vendor, window)


def verify_partitions(records, *, now=None, source_root=None) -> dict:
    """Every partition's verdict: exactly one valid standard record, cardinality counted
    before validity; a read error fails only the partition its file name names."""
    from . import seat_window_supply
    seat_window_supply.load_all()
    now = now or _now()
    grouped: dict[tuple[str, str], list] = {}
    failed: dict[tuple[str, str], str] = {}
    unclassified = 0
    for item in records:
        if isinstance(item, UnreadableRecord):
            key = _partition_of_name(item.name)
            if key is None:
                unclassified += 1
            else:
                failed[key] = "window_record_unavailable"
            continue
        key = classify(item)
        if key is None:
            unclassified += 1
            continue
        if item.get("host_class") != OWNER_W1_HOST_CLASS:
            continue  # team contexts are retained for later done-team validation only
        grouped.setdefault(key, []).append(item)
    def root_of(record):
        return source_root.get(id(record)) if isinstance(source_root, dict) else source_root

    verdicts = {}
    for key in sorted(set(grouped) | set(failed)):
        if key in failed:
            verdicts[key] = {"passed": False, "code": failed[key], "record": None}
            continue
        members = grouped[key]
        if len(members) != 1:
            verdicts[key] = {"passed": False, "code": "window_duplicate_records", "record": None}
            continue
        record = members[0]
        if key[1] == "W1":
            try:
                passed = _valid_record(record, now, root_of(record))
            except (KeyError, TypeError, ValueError):
                passed = False
            code = "window_verified" if passed else "window_review_required"
        else:
            try:
                code = _row_record_code(record, now, root_of(record),
                                        _window_data_for_record(record))
            except (KeyError, TypeError, ValueError, AttributeError):
                code = "window_record_invalid"
            passed = code is None
            code = "window_verified" if passed else code
        verdicts[key] = {"passed": passed, "code": code, "record": record}
    return {"partitions": verdicts, "unclassified": unclassified}


def _completion_time(key, record):
    return _iso_time(record["observed_at"])


def _apply_row(rows, row_id, record) -> None:
    """Write one passing partition's row: R5's live evidence from the ``vendor:V``
    observation, which carries the record's exec digest."""
    row = next((item for item in rows if item["id"] == row_id), None)
    observation = next((item for item in record["row_observations"]
                        if item["id"] == row_id), None)
    if row is None or observation is None or observation["outcome"] != "observed":
        return
    row["status"] = "done-local"
    row["qualification_record"] = digest([record["record_digest"]])
    row["live_evidence_digest"] = digest([observation["exec_record_digest"]])
    row["profile_digest"] = record["profile_digest"]
    row["allowlist_digest"] = record["allowlist_digest"]


def _reduce_partitions(verdicts) -> list[dict]:
    rows = readiness_rows()
    before = json.loads(json.dumps(rows, sort_keys=True))
    winners: dict[str, tuple[tuple[str, str], dict]] = {}
    for key, verdict in verdicts.items():
        if not verdict["passed"]:
            continue
        previous = winners.get(key[0])
        if previous is not None:
            later = _completion_time(key, verdict["record"])
            earlier = _completion_time(*previous)
            if later < earlier or later == earlier and key[1] != ROW_WINDOW:
                continue
        winners[key[0]] = (key, verdict["record"])
    for vendor, (key, record) in winners.items():
        _apply_row(rows, f"vendor:{vendor}", record)
    # R4: a partition writes only its own `vendor:V` row.
    allowed = {f"vendor:{vendor}" for vendor in winners}
    for old, new in zip(before, rows, strict=True):
        if old["id"] not in allowed and old != new:
            raise AssertionError("window reduction changed another vendor's row")
    return rows


def verify_window(records, vendor, window, *, now=None, source_root=None) -> dict:
    result = verify_partitions(records, now=now, source_root=source_root)
    verdict = result["partitions"].get((vendor, window))
    passed = bool(verdict and verdict["passed"])
    code = (verdict["code"] if verdict else "window_review_required")
    return {"schema": "seat_window_verification.v1", "window": window, "vendor": vendor,
            "passed": passed, "records_valid": passed,
            "status": "done-local" if passed else "candidate",
            "code": "window_verified" if passed else (
                code if code != "window_verified" else "window_review_required"),
            "unclassified": result["unclassified"]}


def _row_export(records, destination: Path, vendor, *, reviewed, source_root):
    if reviewed is not True:
        raise ValueError("window export unavailable")
    result = verify_partitions(records, source_root=source_root)
    verdict = result["partitions"].get((vendor, ROW_WINDOW))
    if not verdict or not verdict["passed"]:
        raise ValueError("window export unavailable")
    record = verdict["record"]
    rows = _reduce_partitions({(vendor, ROW_WINDOW): verdict})
    public = {"schema": "seat_window_export.v1", "window": ROW_WINDOW, "vendor": vendor,
              "pre_post_reviewed": True,
              "contexts": [{key: record[key] for key in (
                  "context_id", "account_label", "host_class", "record_digest")}],
              "rows": [{key: row[key] for key in (
                  "id", "status", "exception", "expiry", "qualification_record",
                  "live_evidence_digest")} for row in rows if row["id"] == f"vendor:{vendor}"]}
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.fchmod(fd, 0o644)
    with os.fdopen(fd, "w") as output:
        json.dump(public, output, sort_keys=True, indent=2)
        output.write("\n")
    return public


# --- The row launcher (§6, §9) and its CLI. ---

@dataclass
class _RowRun:
    vendor: str
    context_id: str
    attempt: dict
    ledger: object
    data: object
    board: object = None


def _row_ready_codes(vendor):
    from . import seat_window_supply
    # K-1 r5.2 §10.B (B1): a supplier may hold its vendor's row window with a typed
    # row-ready code; it refuses before any claim, preflight, jail or proxy.
    hold = getattr(seat_window_supply.load(vendor), "ROW_WINDOW_HOLD", None)
    if hold is not None:
        return str(hold), None
    data = _window_data_for(vendor)
    if (seat_window_supply.available(vendor) is None or data is None
            or ROW_WINDOW not in data.windows):
        return "window_vendor_unavailable", None
    return None, data


def _qualify_row(*, vendor, monitoring_policy, repo, host_class, attended, model,
                 peer_record) -> dict:
    from . import panel_invoker as panel, president_adapter, seat_window_supply as supply
    code, data = _row_ready_codes(vendor)
    if code is not None:
        return {"status": "candidate", "code": code}
    if host_class != OWNER_W1_HOST_CLASS or model is not None or peer_record is not None:
        return {"status": "candidate", "code": "window_owner_approval_required"}
    context_id = "c" + secrets.token_hex(16)[1:]
    try:
        attempt = claim_window_attempt(vendor, ROW_WINDOW, context_id)
    except WindowClaimRefused as exc:
        return {"status": "candidate", "code": exc.code}
    except (OSError, ValueError, TypeError):
        return {"status": "candidate", "code": "window_grant_unavailable"}
    try:
        ledger = supply.WindowLedger(_private_root() / f"window-ledger-{vendor}-{context_id}.jsonl",
                                     attempt["launch_envelope"], clock=lambda: _now())
    except (OSError, supply.WindowRefused):
        return {"status": "candidate", "code": "window_envelope_invalid"}
    with supply.ledger_scope(ledger):
        composed = []
        try:
            with supply.item_scope("auth_probe"):
                outcome = preflight(composed_out=composed)
        except supply.WindowRefused as exc:
            return {"status": "candidate", "code": exc.code}
        if outcome.status != "admitted":
            return {"status": "candidate", "code": outcome.code}
        if not attended:
            return {"status": "candidate", "code": "window_attendance_required"}
        # §9.1: before any work, the composed board and ladder against the envelope's
        # assumptions (one seat per vendor, Fable first).
        if len(composed) != 1 or not panel._window_board_shape_ok(composed[0]):
            return {"status": "candidate", "code": "window_envelope_mismatch"}
        from .seat_profiles import profile_for
        profile = profile_for(data.leg)
        if (profile is None or profile.window is None
                or not seat_jail.execfind_pass_recorded(seat_jail.jail_profile_digest(profile.leg))
                or profile.allowlist_id is not None
                and seat_egress_proxy.unavailable_reason() is not None):
            return {"status": "candidate", "code": "window_host_readiness_required"}
        row = _RowRun(vendor=vendor, context_id=context_id, attempt=attempt, ledger=ledger,
                      data=data, board=composed[0])
        try:
            record = run_native_window(repo=Path(repo), monitoring_policy=monitoring_policy,
                                       host_class=host_class, vendor=vendor, row=row)
        except supply.WindowRefused as exc:
            return {"status": "candidate", "code": exc.code}
    if record.get("schema") != SCHEMA:
        return record
    record["record_digest"] = digest(record)
    president_adapter.write_private_record(f"window-row-{vendor}-{context_id}.json", record)
    return {"status": "candidate", "code": "window_review_required"}


def _retained_records(root: Path):
    items = []
    for path in sorted(root.glob("window-*.json")):
        if _partition_of_name(path.name) is None:
            continue
        try:
            items.append(_read_record(path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            items.append(UnreadableRecord(path.name))
    return items


def batch_candidates() -> list[str]:
    """Landed-supplier vendors whose row is not ``done-local`` under a verified reduction of
    this host's retained records and whose grant is eligible. Claims nothing."""
    from . import seat_window_supply
    loaded = seat_window_supply.load_all()
    try:
        verdicts = verify_partitions(_retained_records(_private_root()))["partitions"]
        rows = {row["id"]: row for row in _reduce_partitions(verdicts)}
    except (OSError, ValueError):
        rows = {}
    candidates_ = []
    for vendor in sorted(loaded):
        data = _window_data_for(vendor)
        if data is None or ROW_WINDOW not in data.windows:
            continue
        if rows.get(f"vendor:{vendor}", {}).get("status") == "done-local":
            continue
        if window_grant(vendor, ROW_WINDOW):
            candidates_.append(vendor)
    return candidates_


def qualify_batch(**kwargs) -> dict:
    vendors = batch_candidates()
    codes = {vendor: _qualify_row(vendor=vendor, **kwargs)["code"] for vendor in vendors}
    if not codes:
        return {"status": "candidate", "code": "window_no_eligible_vendor", "vendors": {}}
    ok = all(code == "window_review_required" for code in codes.values())
    return {"status": "passed" if ok else "candidate",
            "code": "window_review_required" if ok else "window_batch_incomplete",
            "vendors": codes}


def ready(vendor: str, window: str) -> dict:
    """Reads only: grant eligibility, supplier availability and login-file presence."""
    from . import seat_window_supply
    from .seat_profiles import profile_for, registered_legs
    logins = {}
    for leg in sorted(set(registered_legs()) | {"claude", "codex", "gemini", "grok"}):
        profile = profile_for(leg)
        try:
            logins[leg] = bool(profile.credential_present()) if profile is not None else None
        except Exception:
            logins[leg] = False
    available = seat_window_supply.available(vendor) is not None
    if window == "W1":
        eligible = (vendor == OWNER_W1_VENDOR and available
                    and owner_w1_grant() is not None)
    else:
        eligible = window == ROW_WINDOW and available and window_grant(vendor, window)
    return {"status": "passed" if eligible and all(value is not False for value in
                                                    logins.values()) else "candidate",
            "vendor": vendor, "window": window, "available": available,
            "grant": bool(eligible), "logins": logins}


def register_parser(subparsers):
    parser = subparsers.add_parser("seat-window", help="Qualify, verify or export seat-window metadata")
    from .seat_window_supply import SUPPLIERS
    parser.add_argument("action", choices=("qualify", "verify", "export", "probe-tools", "matrix",
                                           "measure-tools", "status", "ready"))
    parser.add_argument("--window", default=None, choices=WINDOWS)
    parser.add_argument("--monitoring-policy", default="bounded", choices=("bounded",))
    parser.add_argument("--host-class", default="standard", choices=("team", "standard"))
    parser.add_argument("--attended", action="store_true")
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--peer-record")
    # The supplier table's keys: parsing imports no supplier. probe-tools, measure-tools and
    # status keep their Grok behavior with grok as the default vendor.
    parser.add_argument("--vendor", choices=tuple(SUPPLIERS), default=None)
    parser.add_argument("--output")
    parser.add_argument("--model")
    parser.add_argument("--effort", default="high")
    # measure-tools (grok tool-surface contract v1, section 5.10): one stage per invocation.
    measure = parser.add_argument_group("measure-tools")
    measure.add_argument("--grant")
    measure.add_argument("--binary")
    measure.add_argument("--expect-binary-sha256")
    measure.add_argument("--new-grant", action="store_true")
    measure.add_argument("--planned")
    measure.add_argument("--retries", type=int)
    measure.add_argument("--route", action="append", choices=("review", "sealed", "staged"))
    measure.add_argument("--require-measured", choices=("review", "sealed", "staged"))
    measure.add_argument("--aggregate", action="store_true")
    measure.add_argument("--verify-probe", choices=("initial", "final"))
    measure.add_argument("--status", action="store_true")
    measure.add_argument("--reprocess")
    measure.add_argument("--purge", action="store_true")
    measure.add_argument("--rehearse", action="store_true")
    measure.add_argument("--require-rehearsed", choices=("review", "sealed", "staged"))
    measure.add_argument("--hosted-check")
    # status (GROKROLL §3): read-only; reuses --binary above as the subject path selector.
    status = parser.add_argument_group("status")
    status.add_argument("--binary-digest")
    status.add_argument("--release-version")
    status.add_argument("--candidate")
    status.add_argument("--candidate-digest")
    status.add_argument("--candidate-version")
    status.add_argument("--require-route", action="append", choices=("review", "sealed", "staged"))
    status.add_argument("--schema", choices=("v1",), default="v1")
    status.add_argument("--exit-code", action="store_true")


def probe_tool_rows(*, model=None, effort="high") -> list[dict]:
    """One ``seat-window probe-tools`` row per grok route form: ``route``, ``passed`` and the
    ``basis`` the receipt rests on (grok tool-surface contract §4.5)."""
    from . import panel_invoker as panel
    forms = panel.grok_runtime_forms(model=model, effort=effort)
    routes = []
    for route, command in forms.items():
        receipt = panel.probe_grok_tools(
            command, allowed_tools=panel._grok_allowed_tools(command))
        passed = receipt.get("passed") is True
        row = {"route": route, "passed": passed,
               "basis": receipt.get("basis", "none") if passed else "none"}
        if row["basis"] == "frozen_measurement":
            row["source"] = receipt.get("surface_source")
            if receipt.get("shadowed"):
                row["shadowed"] = receipt["shadowed"]
        routes.append(row)
    return routes


def _selected_records(args, president_adapter, *, pattern="window-W1-*.json"):
    """The named record files (or this host's retained ones). A file the reader refuses is
    kept as an :class:`UnreadableRecord`, which fails only the partition its name names."""
    paths = [Path(path) for path in args.record] or sorted(
        president_adapter.private_record_root().glob(pattern))
    records, roots = [], {}
    for path in paths:
        try:
            record = _read_record(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            records.append(UnreadableRecord(path.name))
            continue
        records.append(record)
        # Each record's retained sources are the ones beside it.
        roots[id(record)] = path.parent.resolve()
    return records, roots


def cli_main(args):
    if args.action == "status":
        from .grok_roll.status import cli_main as status_main
        return status_main(args)
    from . import president_adapter, seat_window_supply
    # Callers of the Grok actions (probe-tools, measure-tools) may pass a namespace that
    # carries none of the window options; those actions read neither.
    window_option = getattr(args, "window", None)
    window = window_option or "W1"
    vendor = getattr(args, "vendor", None)
    try:
        if args.action == "matrix":
            if args.record:
                records, source_root = _selected_records(args, president_adapter)
                verdicts = verify_partitions(records, source_root=source_root)["partitions"]
                verdicts = {key: value for key, value in verdicts.items()
                            if (vendor is None or key[0] == vendor)
                            and (window_option is None or key[1] == window_option)}
                value = _reduce_partitions(verdicts)
            else:
                value = readiness_rows()
            print(json.dumps(value, sort_keys=True))
            return 0
        if args.action in {"qualify", "ready", "verify", "export"} and (
                window == "W1" and vendor not in (None, OWNER_W1_VENDOR)
                or vendor is not None and seat_window_supply.available(vendor) is None):
            result = {"status": "candidate", "code": "window_vendor_unavailable"}
        elif args.action == "ready":
            result = ready(vendor or OWNER_W1_VENDOR, window)
        elif args.action == "qualify" and (args.model is not None or args.record
                                           or args.peer_record is not None):
            # The owner grant approves the default window model and no peer context.
            result = {"status": "candidate", "code": "window_owner_approval_required"}
        elif args.action == "qualify" and window == ROW_WINDOW:
            result = qualify(window=ROW_WINDOW, monitoring_policy=args.monitoring_policy,
                repo=args.repo or ".", host_class=args.host_class, attended=args.attended,
                vendor=vendor)
            print(json.dumps(result, sort_keys=True))
            return 0 if result.get("code") == "window_review_required" else 1
        elif args.action == "qualify":
            result = qualify(window=window, monitoring_policy=args.monitoring_policy,
                repo=args.repo or ".", host_class=args.host_class, attended=args.attended,
                peer_record=args.peer_record, model=args.model)
        elif args.action == "probe-tools":
            routes = probe_tool_rows(model=args.model, effort=args.effort)
            result = {"status": "passed" if all(row["passed"] for row in routes) else "candidate",
                      "routes": routes}
        elif args.action == "measure-tools":
            from . import grok_tool_surface
            code, report = grok_tool_surface.measure_tools_cli(args)
            print(json.dumps(report, sort_keys=True))
            return code
        else:
            row = window == ROW_WINDOW
            pattern = f"window-row-{vendor}-*.json" if row else "window-W1-*.json"
            records, source_root = _selected_records(args, president_adapter, pattern=pattern)
            if row:
                result = verify_window(records, vendor, ROW_WINDOW, source_root=source_root)
            else:
                result = verify_records(records, source_root=source_root)
            if args.action == "export":
                if not args.output:
                    raise ValueError("window output required")
                export_records(records, Path(args.output), reviewed=args.reviewed,
                               source_root=source_root, vendor=vendor,
                               window=ROW_WINDOW if row else None)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("passed") or result.get("status") == "passed" else 1
    except (OSError, ValueError, TypeError, RuntimeError):
        print(json.dumps({"status": "candidate", "code": "window_record_unavailable"}))
        return 1
