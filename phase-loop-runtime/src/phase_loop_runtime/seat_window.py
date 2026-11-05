"""Seat-window commands and closed-field offline reduction."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import president_adapter, seat_egress_proxy, seat_jail

SCHEMA = "seat_window.v1"
VENDORS = ("claude", "gemini", "codex", "grok", "pi")
CONTAINMENT_FIELDS = ("credential_scope", "refresh_detection", "project_settings", "hooks",
                      "mcp_servers", "provider_overrides")
EGRESS_FIELDS = ("allowed_proxy", "refused_proxy", "direct_dns", "direct_ip")
KEY_FIELDS = ("runtime_digest", "profile_digest", "allowlist_digest")
DIGEST_FIELDS = (*KEY_FIELDS, "board_digest", "exec_record_digest", "tool_receipt_digest")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[ac][0-9a-f]{31}\Z")
_EXPIRES = "2026-12-04T00:00:00+00:00"
_RECORD_FIELDS = {"schema", "window", "context_id", "account_label", "host_class", "host_digest",
    "operator_id", "board_outcome", "admission", "canonical_gemini", "staged_read", "gemini_route",
    "account_isolation", "co_seats", "containment", "egress", "rows", "observed_at",
    "qualification_keys", "record_digest", *DIGEST_FIELDS}
_RECORD_FIELDS.add("source_attempt")
_RECORD_FIELDS.add("row_observations")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def measurement(checks: dict, *, observation_digest=None) -> dict:
    payload = {"checks": checks, "observation_digest": observation_digest or digest(checks)}
    return {**payload, "evidence_digest": digest(payload)}


def readiness_rows() -> list[dict]:
    """The complete inventory; no source-checkout result qualifies a host."""
    rows = []
    exceptions = {"claude": "open egress", "codex": "unconfined", "grok": "unconfined"}
    for kind in ("vendor", "remote"):
        for vendor in VENDORS:
            exception = exceptions.get(vendor) if kind == "vendor" else None
            rows.append({"id": f"{kind}:{vendor}", "kind": kind, "vendor": vendor,
                "route": "remote" if kind == "remote" else ("jailed" if vendor == "gemini" else "local"),
                "claude_transport": "print" if vendor == "claude" else None,
                "profile_digest": None, "allowlist_id": "gemini" if vendor == "gemini" else None,
                "allowlist_digest": None, "tool_surface": None, "credential_lane": "subscription",
                "projection": None, "host_classes": ["team", "standard"],
                "qualification_record": None, "live_evidence_digest": None,
                "status": "remote-pending" if kind == "remote" else "candidate",
                "exception": exception, "expiry": _EXPIRES if exception else None,
                "renewal_record": None, "end_condition": "row window or owning phase exit",
                "interim_route": "degraded"})
    for entry in president_adapter.president_rung_inventory():
        vendor = {"fable": "claude", "sol": "codex"}.get(entry["rung"], entry["rung"])
        base = next(r for r in rows if r["id"] == f"vendor:{vendor}").copy()
        base.update(entry, id=f"president:{entry['rung']}:{entry['route']}", kind="president")
        rows.append(base)
    return rows


def candidates(rows, host_class):
    if host_class not in {"team", "standard"}:
        raise ValueError("window host class unavailable")
    return [row for row in rows if row["status"] == "candidate" and host_class in row["host_classes"]]


def candidate_observations(rows, legs):
    """Collect each selected row separately; never reuse a vendor leg for a rung."""
    observations = []
    for row in rows:
        matches = [leg for leg in legs if row["kind"] == "vendor" and leg.leg == row["vendor"]]
        metadata = getattr(matches[0], "_leg_exec_metadata", None) if len(matches) == 1 else None
        identity = metadata.get("record_digest") if metadata else None
        observations.append({"id": row["id"], "outcome": "observed" if _is_digest(identity) else "unavailable",
                             "exec_record_digest": identity if _is_digest(identity) else None})
    return observations


def preflight(*, is_available=None, auth_ok=None):
    from .advisor_board.composition import compose_review_board_report, default_board_auth_ok
    from .advisor_board.registries import DEFAULT_HARNESS_REGISTRY
    available = is_available or DEFAULT_HARNESS_REGISTRY.is_available
    auth = auth_ok or default_board_auth_ok
    # Do not short-circuit a vendor's auth check when its executable is absent.
    from .advisor_board import backing
    authorization = backing.prepare_review_composition_authorization()
    try:
        backing.revalidate_review_composition_authorization(authorization)
        states = {v: (bool(available(v)), bool(auth(v))) for v in VENDORS[:4]}
    finally:
        backing.clear_review_composition_authorization()
    composed = compose_review_board_report(is_available=lambda v: states[v][0],
                                          auth_ok=lambda v: states[v][1])
    return composed.policy_outcome("plan")


def _is_digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _check_measurement(value, fields):
    return (type(value) is dict and set(value) == {"checks", "observation_digest", "evidence_digest"}
            and type(value["checks"]) is dict and set(value["checks"]) == set(fields)
            and all(v is True for v in value["checks"].values())
            and _is_digest(value["observation_digest"])
            and value["evidence_digest"] == digest({k: value[k] for k in ("checks", "observation_digest")}))


def _source_record(name, expected, *, root=None, file_digest=False):
    """Read bounded retained receipts through the same operator-storage checks."""
    if not _is_digest(expected) or Path(name).name != name:
        raise ValueError("window source unavailable")
    observed = []
    value = _read_record((root or president_adapter.private_record_root()) / name, digest_sink=observed)
    if type(value) is not dict:
        raise ValueError("window source unavailable")
    actual = observed[0] if file_digest else digest(value)
    if actual != expected:
        raise ValueError("window source unavailable")
    return value


def _reconcile_sources(record, *, root=None):
    try:
        attempt = record["source_attempt"]
        if type(attempt) is not str or re.fullmatch(r"[0-9a-f]{32}", attempt) is None:
            return False
        execution = _source_record("leg-" + attempt + ".json", record["exec_record_digest"],
                                   root=root, file_digest=True)
        identity = record["containment"]["observation_digest"]
        observation = _source_record("window-observation-" + identity + ".json", identity, root=root)
        read = _source_record("window-read-" + record["tool_receipt_digest"] + ".json",
                              record["tool_receipt_digest"], root=root)
        if (execution.get("schema") != "leg_exec.v1" or execution.get("attempt_id") != attempt
            or execution.get("vendor") != "gemini" or type(execution.get("exit_code")) is not int
            or execution["exit_code"] != 0 or execution.get("outcome") != "leg_execution_completed"
            or execution.get("model_turn") is not True or execution.get("verdict") is not True):
            return False
        if (read.get("schema") != "seat_window_read.v1" or read.get("access_observed") is not True
            or read.get("tool_observed") is not True or read.get("observation_digest") != identity
            or not _is_digest(read.get("tree_digest"))
            or read["tree_digest"] != observation.get("tree_digest")
            or read["tree_digest"] != observation.get("final_tree_digest")):
            return False
        contract = observation.get("contract_observation") or {}
        if type(contract) is not dict:
            return False
        expected = {**dict.fromkeys(CONTAINMENT_FIELDS[2:], "not_loaded"),
            "credential_scope": "no wider than the recorded baseline", "refresh_detection": "passed"}
        binding = contract.get("binding", {})
        if (type(binding) is not dict or contract.get("outcomes") != expected
            or any(binding.get(k) != record[k] for k in ("profile_digest", "allowlist_digest"))):
            return False
        return (observation.get("schema") == "seat_window_observation.v1"
            and all(observation.get(k) is True for k in ("stopped", "watch_complete", "proxy_complete"))
            and type(observation.get("allowed_requests")) is int and observation["allowed_requests"] > 0
            and type(observation.get("refused_requests")) is int and observation["refused_requests"] > 0
            and all(observation.get(when, {}).get(k) == "refused" for when in ("before", "after")
                    for k in ("direct_dns", "direct_ip", "unlisted_status"))
            and record["egress"]["observation_digest"] == identity)
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        return False


def _valid_record(record, now, source_root=None):
    if type(record) is not dict or set(record) != _RECORD_FIELDS:
        return False
    if record["schema"] != SCHEMA or record["window"] != "W1":
        return False
    if not all(type(record[k]) is str and _LABEL.fullmatch(record[k]) for k in ("context_id", "account_label")):
        return False
    if not all(_is_digest(record[k]) for k in (*DIGEST_FIELDS, "host_digest", "record_digest")):
        return False
    if record["record_digest"] != digest({k: v for k, v in record.items() if k != "record_digest"}):
        return False
    if record["qualification_keys"] != {k: record[k] for k in KEY_FIELDS}:
        return False
    if (record["host_class"] not in {"team", "standard"} or type(record["operator_id"]) is not int
        or record["operator_id"] < 0 or record["admission"] != "admitted"
        or record["board_outcome"] != "terminated" or record["gemini_route"] != "jailed"
        or any(record[k] is not True for k in ("canonical_gemini", "staged_read", "account_isolation"))):
        return False
    if (type(record["co_seats"]) is not list or set(record["co_seats"]) != {"codex", "grok"}
        or len(record["co_seats"]) != 2):
        return False
    expected = {r["id"] for r in candidates(readiness_rows(), record["host_class"])}
    if type(record["rows"]) is not list or set(record["rows"]) != expected or len(record["rows"]) != len(expected):
        return False
    observations = record["row_observations"]
    if (type(observations) is not list or len(observations) != len(expected)
        or {r["id"] for r in observations} != expected
        or any(set(r) != {"id", "outcome", "exec_record_digest"}
            or not (r["outcome"] == "observed" and _is_digest(r["exec_record_digest"])
                    or r["outcome"] == "unavailable" and r["exec_record_digest"] is None)
            for r in observations)
        or next(r for r in observations if r["id"] == "vendor:gemini")["exec_record_digest"]
            != record["exec_record_digest"]):
        return False
    try:
        observed = dt.datetime.fromisoformat(record["observed_at"])
        if observed.tzinfo is None or not dt.timedelta(0) <= now - observed <= dt.timedelta(days=30):
            return False
        if any(r["expiry"] and now >= dt.datetime.fromisoformat(r["expiry"]) for r in readiness_rows()):
            return False
    except (TypeError, ValueError):
        return False
    return (_check_measurement(record["containment"], CONTAINMENT_FIELDS)
            and _check_measurement(record["egress"], EGRESS_FIELDS)
            and _reconcile_sources(record, root=source_root))


def verify_records(records, *, now=None, source_root=None) -> dict:
    now = now or _now()
    try:
        valid = bool(records) and all(_valid_record(r, now, source_root) for r in records)
        contexts = {r["context_id"] for r in records}
        team = [r for r in records if r["host_class"] == "team"]
        pairs = {(r["host_digest"], r["operator_id"]) for r in records}
        labels = {(r["host_digest"], r["account_label"]) for r in records}
        team_hosts = {r["host_digest"] for r in team}
        coverage = (len(team_hosts) == 1 and len({r["operator_id"] for r in team}) >= 2
                    and any(r["host_class"] == "standard" and r["host_digest"] not in team_hosts for r in records)
                    and len(contexts) == len(records) == len(pairs) == len(labels))
        passed = bool(valid and coverage)
    except (KeyError, TypeError, ValueError):
        passed = False
    return {"schema": "seat_window_verification.v1", "window": "W1", "passed": passed,
            "status": "done-local" if passed else "candidate"}


def export_records(records, destination: Path, *, reviewed=False, source_root=None):
    if reviewed is not True or not verify_records(records, source_root=source_root)["passed"]:
        raise ValueError("window export unavailable")
    public = {"schema": "seat_window_export.v1", "window": "W1", "pre_post_reviewed": True,
        "contexts": [{k: r[k] for k in ("context_id", "account_label", "host_class", "record_digest")}
                     for r in records],
        "rows": [{"id": r["id"], "status": "done-local" if r["id"] == "vendor:gemini" else r["status"],
                  "exception": r["exception"], "expiry": r["expiry"]} for r in readiness_rows()]}
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
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
    files = [*root.glob("*.py"), *root.glob("advisor_board/*.py"), *root.glob("seat_egress/*")]
    return digest({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(files) if p.is_file() and not p.is_symlink()})


def run_native_window(*, repo, monitoring_policy, host_class):
    return {"status": "candidate", "code": "window_supplier_unavailable"}


def qualify(*, window, monitoring_policy, repo=".", host_class="team", attended=False, peer_record=None):
    if window != "W1" or monitoring_policy != "bounded":
        raise ValueError("window policy unavailable")
    outcome = preflight()
    if outcome.status != "admitted":
        return {"status": "candidate", "code": outcome.code}
    if not attended:
        return {"status": "candidate", "code": "window_attendance_required"}
    if (not seat_jail.execfind_pass_recorded(seat_jail.jail_profile_digest("gemini"))
        or seat_egress_proxy.unavailable_reason() is not None):
        return {"status": "candidate", "code": "window_host_readiness_required"}
    record = run_native_window(repo=Path(repo), monitoring_policy=monitoring_policy, host_class=host_class)
    if record.get("code") == "window_supplier_unavailable":
        return record
    if record.get("schema") == SCHEMA:
        record["account_isolation"] = account_isolation(Path(peer_record) if peer_record else None)
        record.pop("record_digest", None)
        record["record_digest"] = digest(record)
        president_adapter.write_private_record("window-W1-" + record["context_id"] + ".json", record)
    return {"status": "candidate", "code": "window_review_required"}


def register_parser(subparsers):
    parser = subparsers.add_parser("seat-window", help="Qualify, verify or export seat-window metadata")
    parser.add_argument("action", choices=("qualify", "verify", "export", "probe-tools", "matrix"))
    parser.add_argument("--window", default="W1", choices=("W1",))
    parser.add_argument("--monitoring-policy", default="bounded", choices=("bounded",))
    parser.add_argument("--host-class", default="team", choices=("team", "standard"))
    parser.add_argument("--attended", action="store_true")
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--peer-record")
    parser.add_argument("--vendor", choices=("grok",), default="grok")
    parser.add_argument("--output")


def cli_main(args):
    try:
        if args.action == "matrix":
            print(json.dumps(readiness_rows(), sort_keys=True))
            return 0
        if args.action == "qualify":
            result = qualify(window=args.window, monitoring_policy=args.monitoring_policy,
                repo=args.repo or ".", host_class=args.host_class, attended=args.attended,
                peer_record=args.peer_record)
        elif args.action == "probe-tools":
            from . import panel_invoker as pi
            command = pi._brokered_grok_command(model=None, out_dir=Path("/definition-probe"),
                                                grok_effort_args=())
            receipt = pi.probe_grok_tools(command, allowed_tools=set(pi.GROK_SANDBOX_TOOLS.split(",")))
            result = {"status": "passed" if receipt.get("passed") else "candidate"}
        else:
            paths = [Path(p) for p in args.record] or sorted(
                president_adapter.private_record_root().glob("window-W1-*.json"))
            records = [_read_record(p) for p in paths]
            roots = {p.parent.resolve() for p in paths}
            if len(roots) != 1:
                raise ValueError("window source storage unavailable")
            source_root = roots.pop()
            result = verify_records(records, source_root=source_root)
            if args.action == "export":
                if not args.output:
                    raise ValueError("window output required")
                export_records(records, Path(args.output), reviewed=args.reviewed, source_root=source_root)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("passed") or result.get("status") == "passed" else 1
    except (OSError, ValueError, TypeError):
        print(json.dumps({"status": "candidate", "code": "window_record_unavailable"}))
        return 1
