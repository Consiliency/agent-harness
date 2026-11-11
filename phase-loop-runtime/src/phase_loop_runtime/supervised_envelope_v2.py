"""Public v2 JSON domain and RFC 8785 codec; decoding grants no launch authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import math
from types import MappingProxyType

import rfc8785

from .supervised_contracts import ContractBundle, ContractError, _v2_json, validate_record

PUBLIC_CODEC = "admitted_launch_envelope.v2"


@dataclass(frozen=True, slots=True)
class ParsedV2:
    value: object
    raw: bytes


@dataclass(frozen=True, slots=True)
class V2Envelope:
    value: Mapping
    raw: bytes
    raw_digest: str
    public_digest: str


@dataclass(frozen=True, slots=True)
class V2Decision:
    admitted: bool
    diagnostics: tuple[str, ...]


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _plain(value):
    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError()
            key.encode("utf-8")
            result[key] = _plain(child)
        return result
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if type(value) is str:
        value.encode("utf-8")
    elif type(value) in (int, float):
        if not math.isfinite(value) or (value == int(value) and abs(value) > 9007199254740991):
            raise ValueError()
    elif value is not None and type(value) is not bool:
        raise ValueError()
    return value


def canonicalize_v2(value) -> bytes:
    failed = False
    try:
        result = rfc8785.dumps(_plain(value))
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        failed = True
    if failed:
        raise ContractError("record_json_invalid") from None
    return result


def parse_v2(raw: bytes) -> ParsedV2:
    value = _v2_json(raw)
    return ParsedV2(_freeze(value), raw)


def decode_v2(raw: bytes, *, bundle: ContractBundle) -> V2Envelope:
    parsed = parse_v2(raw)
    validate_record(bundle, "admitted_launch_envelope.v2", raw)
    payload = {key: child for key, child in parsed.value.items() if key != "envelope_digest"}
    return V2Envelope(parsed.value, raw, sha256(raw).hexdigest(), sha256(canonicalize_v2(payload)).hexdigest())


def _relative(value, *, cwd=False):
    if cwd and value == ".":
        return True
    return (type(value) is str and bool(value) and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and not any(c in value for c in (":", "\\", "\x00"))
            and all(part not in ("", ".", "..") for part in value.split("/")))


def _strings(value):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield key
            yield from _strings(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def _route_key(envelope):
    launch = envelope["launch"]
    policy = launch["trusted_policy"]
    return dict(tier=envelope["enforcement"]["tier"], action=launch["action"], transport_id=launch["transport_id"],
                executable_chain=[{key: entry[key] for key in ("locator_kind", "locator", "sha256")}
                                  for entry in launch["executable_chain"]],
                template_sha256=policy["template_sha256"], qualification_sha256=policy["qualification_sha256"])


def _evaluate_v2_admission(envelope: V2Envelope, *, context, capture, attempt, prefix_only=False) -> V2Decision:
    """Evaluate the pinned reporting stages over independently held commitments."""
    if type(envelope) is not V2Envelope:
        return V2Decision(False, ("envelope_schema_invalid",))
    value = envelope.value
    if value["envelope_digest"] != envelope.public_digest:
        return V2Decision(False, ("envelope_digest_mismatch",))
    if (value["assignment_digest"] != context.expected_assignment_digest
            or value["units"]["crosswalk_ref"] != context.expected_crosswalk_ref):
        return V2Decision(False, ("authority_foreign",))
    if value["units"]["snapshot_ref"] != context.expected_snapshot_ref:
        return V2Decision(False, ("authority_baseline_stale",))
    launch = value["launch"]
    diagnostics = []
    locators = list(value["workspace"]["repo_relative_locators"])
    for source in (launch["instructions"]["source"], *(row["source"] for row in launch["references"])):
        if source is not None and source["namespace"] in ("workspace", "declared_root"):
            locators.append(source["path"])
    locators.extend(row["locator"] for row in launch["executable_chain"] if row["locator_kind"] == "repo_relative")
    for row in launch["workspace_state"]["target_map"]:
        locators.extend((row["workspace_locator"], row["protected_locator"]))
    if (not all(_relative(locator) for locator in locators)
            or not _relative(launch["workspace_state"]["cwd"]["path"], cwd=True)):
        diagnostics.append("locator_not_repo_relative")
    public = {key: child for key, child in value.items() if key != "caller_context"}
    if any(len(text) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in text) for text in _strings(public)):
        diagnostics.append("raw_output_in_record")
    dependency = value["executable_dependencies"]
    if dependency["declared"] and dependency["admitted_dependency_digest"] is None:
        diagnostics.append("dependency_digest_required")
    if value["workspace"]["kind"] in ("separate_clone", "git_worktree_of_protected") and launch["workspace_state"]["base_commit"] is None:
        diagnostics.append("workspace_source_inconsistent")
    chain = launch["executable_chain"]
    import re
    if (chain[-1]["role"] != "executable" or any(row["role"] != "wrapper" for row in chain[:-1])
            or any(row["locator_kind"] == "declared" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", row["locator"]) is None for row in chain)):
        diagnostics.append("executable_chain_invalid")
    if sum(row["role"] == "baseline" for row in launch["references"]) != 1:
        diagnostics.append("baseline_reference_required")
    scopes = value["workspace"]["repo_relative_locators"]
    if any(not any(row["protected_locator"] == scope or row["protected_locator"].startswith(scope + "/") for scope in scopes)
           for row in launch["workspace_state"]["target_map"]):
        diagnostics.append("target_map_outside_scope")
    if diagnostics:
        return V2Decision(False, tuple(diagnostics))
    tier = value["enforcement"]["tier"]
    if tier == "os_enforced":
        return V2Decision(False, ("tier_unqualified",))
    route_key = _route_key(value)
    matches = [row for row in context.qualified_routes
               if all(_plain(row.get(key)) == _plain(item) for key, item in route_key.items())]
    if launch["trusted_policy"]["qualification_sha256"] is None or len(matches) != 1:
        return V2Decision(False, ("route_not_qualified",))
    record = matches[0]
    diagnostics = []
    constraints = value["enforcement"]["required_constraints"]
    if any(constraint != "write_scope" or tier != "provider_readonly_patch_return_audit" for constraint in constraints):
        diagnostics.append("constraint_unsupported")
    if tier == "provider_readonly_patch_return_audit" and value["workspace"]["kind"] not in ("separate_clone", "separate_copy"):
        diagnostics.append("workspace_not_separate_copy")
    grants = launch.get("grants", {})
    sources = [launch["instructions"]["source"], *(row["source"] for row in launch["references"])]
    if (any(_plain(record.get("grants", {}).get(name)) != _plain(commitment) for name, commitment in grants.items())
            or ("dependency_projection_sha256" in grants and not dependency["declared"])
            or (any(source is not None and source["namespace"] == "descriptor" for source in sources)
                and "descriptor_capabilities_sha256" not in grants)
            or (launch["workspace_state"]["cwd"]["namespace"] == "view_root" and "filesystem_view_sha256" not in grants)
            or not set(capture.credential_sources) <= set(record.get("credential_sources", ()))):
        diagnostics.append("grant_unqualified")
    if launch["action"] == "execution" and launch["stop"]["deadline_action"] == "not_armed":
        diagnostics.append("stop_policy_unbounded")
    if launch["stop"]["timeout_seconds"] > context.timeout_max_seconds:
        diagnostics.append("timeout_over_declared_max")
    if diagnostics:
        return V2Decision(False, tuple(diagnostics))
    if prefix_only:
        return V2Decision(True, ())
    groups = (
        ("launch_instructions_mismatch", ("instructions",)),
        ("launch_reference_mismatch", ("references",)),
        ("launch_argv_mismatch", ("argv",)),
        ("launch_executable_mismatch", ("executable_chain",)),
        ("launch_workspace_mismatch", ("workspace_state",)),
        ("launch_environment_mismatch", ("environment",)),
        ("launch_policy_mismatch", ("trusted_policy", "grants")),
        ("launch_timeout_mismatch", ("stop",)),
    )
    diagnostics = [code for code, members in groups
                   if code in capture.diagnostics or any(member not in getattr(capture, "uncheckable", ())
                       and _plain(launch.get(member)) != _plain(capture.commitments.get(member)) for member in members)]
    if ("launch_input_unbound" in capture.diagnostics
            or any(member in capture.commitments and capture.commitments[member] != launch[member] for member in ("action", "transport_id"))
            or ("stdin" in capture.commitments and capture.commitments["stdin"] != launch["stdin"]) or not capture.suitable(value["caller_context"], context, attempt)
            or capture.contains_secret(value)):
        diagnostics.append("launch_input_unbound")
    return V2Decision(not diagnostics, tuple(diagnostics))



def validate_v2_admission(envelope: V2Envelope, *, context, capture, attempt) -> V2Decision:
    return _evaluate_v2_admission(envelope, context=context, capture=capture, attempt=attempt)


def precheck_v2_admission(envelope: V2Envelope, *, context, spec, attempt) -> tuple[str, ...]:
    """Report early stages before I/O capture; this produces no admission or token."""
    from types import SimpleNamespace
    capture = SimpleNamespace(credential_sources=tuple(source for _name, source, _path in spec.secret_sources))
    return _evaluate_v2_admission(envelope, context=context, capture=capture, attempt=attempt, prefix_only=True).diagnostics
