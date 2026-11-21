"""Attended seat-window collection and closed-field offline reduction."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
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
_EXPIRES = "2026-12-04T00:00:00+00:00"
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
    exceptions = {"claude": "open egress", "codex": "unconfined", "grok": "unconfined"}
    for kind in ("vendor", "remote"):
        for vendor in vendors:
            profile = profiles.get(vendor)
            exception = exceptions.get(vendor) if kind == "vendor" else None
            if profile is not None and (
                exception == "unconfined"
                or exception == "open egress" and profile.allowlist_id is not None
            ):
                exception = None
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
                "exception": exception, "expiry": _EXPIRES if exception else None,
                "renewal_record": None, "end_condition": "row window or owning phase exit",
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


def preflight(*, is_available=None, auth_ok=None):
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
#: No live W1 starts at or after this instant (UTC), whatever the grant says. It is its own
#: literal, never derived from a named exception's expiry, so renewing an exception never
#: reopens W1.
OWNER_W1_APPROVED_UNTIL = "2026-12-04T00:00:00+00:00"
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
        and binding["contract_sha256"] == CONTAINMENT_CONTRACT_SHA256
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
    expected = {row["id"] for row in candidates(readiness_rows(), record["host_class"])}
    if (type(record["rows"]) is not list or set(record["rows"]) != expected
            or len(record["rows"]) != len(expected)):
        return False
    observations = record["row_observations"]
    if (type(observations) is not list or len(observations) != len(expected)
        or {row["id"] for row in observations} != expected
        or any(set(row) != {"id", "outcome", "exec_record_digest"}
            or not (row["outcome"] == "observed" and _is_digest(row["exec_record_digest"])
                    or row["outcome"] == "unavailable" and row["exec_record_digest"] is None)
            for row in observations)
        or next(row for row in observations if row["id"] == f"vendor:{data.vendor}")[
            "exec_record_digest"] != record["exec_record_digest"]):
        return False
    if not _containment_outcomes_valid(record["containment_outcomes"], data):
        return False
    try:
        observed = dt.datetime.fromisoformat(record["observed_at"])
        if observed.tzinfo is None or not dt.timedelta(0) <= now - observed <= dt.timedelta(days=30):
            return False
        if any(row["expiry"] and now >= dt.datetime.fromisoformat(row["expiry"])
               for row in readiness_rows()):
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


def verify_records(records, *, now=None, source_root=None) -> dict:
    now = now or _now()
    try:
        standard = _standard_records(records)
        passed = len(standard) == 1 and _valid_record(standard[0], now, source_root)
    except (KeyError, TypeError, ValueError):
        passed = False
    return {"schema": "seat_window_verification.v1", "window": "W1", "passed": passed,
            "records_valid": passed, "status": "done-local" if passed else "candidate",
            "code": "window_verified" if passed else "window_review_required"}


def reduce_readiness(records, *, now=None, source_root=None) -> list[dict]:
    rows = readiness_rows()
    if not verify_records(records, now=now, source_root=source_root)["passed"]:
        return rows
    # A team context never sets a row status, and no path here emits `done-team`.
    records = _standard_records(records)
    evidence = digest(sorted(record["record_digest"] for record in records))
    # A window qualifies only its own vendor's row: the record's containment, egress,
    # profile and allow-list evidence are that vendor's. A co-seat's exec record shows
    # only that its leg ran on the board (degraded or not), never that its row qualified.
    window_rows = {f"vendor:{data.vendor}" for record in records
                   if (data := _window_data_for_record(record)) is not None}
    for row in rows:
        if row["id"] not in window_rows:
            continue
        observed = []
        for record in records:
            match = next((item for item in record["row_observations"] if item["id"] == row["id"]), None)
            observed.append(match)
        if observed and all(item is not None and item["outcome"] == "observed" for item in observed):
            row["status"] = "done-local"
            row["qualification_record"] = evidence
            row["live_evidence_digest"] = digest([item["exec_record_digest"] for item in observed])
            profiles = {record["profile_digest"] for record in records}
            allowlists = {record["allowlist_digest"] for record in records}
            row["profile_digest"] = next(iter(profiles)) if len(profiles) == 1 else None
            row["allowlist_digest"] = next(iter(allowlists)) if len(allowlists) == 1 else None
    return rows


def export_records(records, destination: Path, *, reviewed=False, source_root=None):
    if reviewed is not True or not verify_records(records, source_root=source_root)["passed"]:
        raise ValueError("window export unavailable")
    records = _standard_records(records)
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


def run_native_window(*, repo, monitoring_policy, host_class, model=None, vendor=None):
    """Run frozen I-15 and assemble the sole input to the containment reducer."""
    from . import panel_invoker as panel, president_adapter
    from . import seat_jail_qualification as jailq
    if vendor is None:
        from .seat_profiles import default_window_data
        default = default_window_data()
        if default is None:
            return {"status": "candidate", "code": "window_supplier_unavailable"}
        vendor = default.vendor
    window_rows = window_rows_for(vendor)
    data = _window_data_for(vendor)
    if window_rows is None or data is None or not _required_interfaces(jailq, panel):
        return {"status": "candidate", "code": "window_supplier_unavailable"}
    if host_class not in {"team", "standard"} or monitoring_policy != "bounded":
        raise ValueError("window policy unavailable")
    context_id = "c" + secrets.token_hex(16)[1:]
    account_label = "a" + secrets.token_hex(16)[1:]
    dependency_subject, dependency_projection = _dependency_binding(data.dependency_provider)
    selected_model = model or panel.DEFAULT_LEG_MODELS[data.model_leg]
    control_launch = getattr(panel, data.control_launcher, None)
    board_launch = getattr(panel, data.board_launcher, None)
    if not callable(control_launch) or not callable(board_launch):
        return {"status": "candidate", "code": "window_supplier_unavailable"}

    with tempfile.TemporaryDirectory(prefix="phase-loop-window-",
                                     dir=sandbox_policy.staging_root()) as temporary:
        base = Path(temporary)
        layout = _profile_plant_layout(
            jailq, plugin_form="nested", window_rows=window_rows,
        )
        q0 = jailq.build_qualification_input(layout, base)

        def launch(kind, qualification_input):
            spec = panel.WindowLaunchSpec(kind=kind, qualification_input=qualification_input,
                model=selected_model, timeout_s=WINDOW_LAUNCH_TIMEOUT_S)
            return control_launch(spec)

        help_result = launch("help", q0)
        plugin_result = None
        if help_result.help_lists_plugin is True:
            plugin_result = launch("plugin_validation", q0)
        else:
            layout = _profile_plant_layout(
                jailq, plugin_form="plugin_json", window_rows=window_rows,
            )
        qualification_input = jailq.build_qualification_input(layout, base)
        controls = [launch("tree_control", qualification_input),
                    launch("runtime_control", qualification_input)]
        definition = jailq.definition_probe(layout, controls)
        if definition.credentialed_control_required:
            controls.extend((launch("credentialed_tree_control", qualification_input),
                             launch("credentialed_runtime_control", qualification_input)))
        measured = launch("measured", qualification_input)
        expired = launch("expired_copy", qualification_input)
        board_spec = panel.WindowBoardSpec(qualification_input=qualification_input,
                                           monitoring_policy=monitoring_policy)
        board = board_launch(board_spec)
        if board.composition != "admitted":
            return {"status": "candidate", "code": "review_composition_refused"}
        leg_observation = getattr(board, data.board_fields["leg"], None)
        canonical = getattr(board, data.board_fields["canonical"], None)
        if leg_observation is None or canonical is None:
            return {"status": "candidate", "code": "window_reduction_unavailable"}
        context = jailq.ContextBinding(context_id=context_id, account_label=account_label,
            dependency_subject_sha256=dependency_subject,
            dependency_projection_sha256=dependency_projection)
        inputs = jailq.ContainmentInputs(context=context, layout=layout, help=help_result,
            plugin_validation=plugin_result, controls=tuple(controls), measured=measured,
            expired_copy=expired, board=leg_observation)
        reduction = jailq.reduce_containment(inputs)

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
        or binding["contract_sha256"] != CONTAINMENT_CONTRACT_SHA256
        or leg_observation.input_sha256 != binding["board_input_sha256"]
        or type(owner) is not dict or set(owner) != set(OWNER_SUMMARY_FIELDS)
        or owner["schema"] != "seat_window_owner_summary.v1"
        or owner["context_id"] != context_id
        or type(owner["counted_lookups"]) is not dict
        or type(owner["uncounted_home_lookups"]) is not dict):
        return {"status": "candidate", "code": "window_reduction_unavailable"}
    president_adapter.write_private_record(
        "window-observation-" + reduction.observation_sha256 + ".json", private)
    egress_source = _egress_observation(context_id, measured, board, leg_observation)
    egress_identity = digest(egress_source)
    president_adapter.write_private_record("window-egress-" + egress_identity + ".json",
                                           egress_source)
    president_adapter.write_private_record("owner-summary-W1-" + context_id + ".json", owner)
    selected = candidates(readiness_rows(), host_class)
    source_attempt = _find_exec_source_attempt(board.exec_record_sha256)
    record = {"schema": SCHEMA, "window": "W1", "context_id": context_id,
        "account_label": account_label, "host_class": host_class, "host_digest": _host_digest(),
        "operator_id": os.getuid(), "board_outcome": board.board_outcome,
        "admission": "admitted" if reduction.admitted else "withheld_private",
        data.record_fields["canonical"]: canonical, "staged_read": board.staged_read,
        data.record_fields["route"]: data.route_literal,
        "account_isolation": None, "co_seats": list(board.co_seats),
        "containment": measurement(checks, observation_digest=reduction.observation_sha256),
        "containment_outcomes": outcomes, "containment_binding": binding,
        "egress": measurement(_egress_checks(egress_source), observation_digest=egress_identity),
        "rows": [row["id"] for row in selected], "observed_at": _now().isoformat(),
        "runtime_digest": runtime_digest(), "profile_digest": binding["jail_profile_sha256"],
        "allowlist_digest": binding["production_allowlist_sha256"],
        "board_digest": board.board_sha256, "exec_record_digest": board.exec_record_sha256,
        "tool_receipt_digest": board.tool_receipt_sha256,
        "board_input_digest": leg_observation.input_sha256,
        "delivered_turn_digest": board.delivered_turn_sha256,
        "source_attempt": source_attempt,
        "row_observations": candidate_observations(selected, board.leg_exec_records)}
    record["qualification_keys"] = {key: record[key] for key in KEY_FIELDS}
    return record


def qualify(*, window, monitoring_policy, repo=".", host_class="standard", attended=False,
            peer_record=None, model=None, vendor=None):
    from . import president_adapter
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


def register_parser(subparsers):
    parser = subparsers.add_parser("seat-window", help="Qualify, verify or export seat-window metadata")
    parser.add_argument("action", choices=("qualify", "verify", "export", "probe-tools", "matrix",
                                           "measure-tools", "status"))
    parser.add_argument("--window", default="W1", choices=("W1",))
    parser.add_argument("--monitoring-policy", default="bounded", choices=("bounded",))
    parser.add_argument("--host-class", default="standard", choices=("team", "standard"))
    parser.add_argument("--attended", action="store_true")
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--peer-record")
    parser.add_argument("--vendor", choices=("grok",), default="grok")
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


def _selected_records(args, president_adapter):
    paths = [Path(path) for path in args.record] or sorted(
        president_adapter.private_record_root().glob("window-W1-*.json"))
    records = [_read_record(path) for path in paths]
    roots = {path.parent.resolve() for path in paths}
    if len(roots) != 1:
        raise ValueError("window source storage unavailable")
    return records, roots.pop()


def cli_main(args):
    if args.action == "status":
        from .grok_roll.status import cli_main as status_main
        return status_main(args)
    from . import president_adapter
    try:
        if args.action == "matrix":
            if args.record:
                records, source_root = _selected_records(args, president_adapter)
                value = reduce_readiness(records, source_root=source_root)
            else:
                value = readiness_rows()
            print(json.dumps(value, sort_keys=True))
            return 0
        if args.action == "qualify" and (args.model is not None or args.record
                                         or args.peer_record is not None):
            # The owner grant approves the default window model and no peer context.
            result = {"status": "candidate", "code": "window_owner_approval_required"}
        elif args.action == "qualify":
            result = qualify(window=args.window, monitoring_policy=args.monitoring_policy,
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
            records, source_root = _selected_records(args, president_adapter)
            result = verify_records(records, source_root=source_root)
            if args.action == "export":
                if not args.output:
                    raise ValueError("window output required")
                export_records(records, Path(args.output), reviewed=args.reviewed,
                               source_root=source_root)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("passed") or result.get("status") == "passed" else 1
    except (OSError, ValueError, TypeError, RuntimeError):
        print(json.dumps({"status": "candidate", "code": "window_record_unavailable"}))
        return 1
