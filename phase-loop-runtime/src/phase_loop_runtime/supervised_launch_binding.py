"""Explicit operator bindings; no discovery, ambient imports or default codec."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import pwd
import sys
from types import ModuleType
from typing import Callable

from .supervised_launch import (
    LaunchConfig, Refused, Validator, _Refusal, _json, _path, _require, sha256, trusted_bytes,
)


def _managed_binding():
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/phase-loop/supervised-launch-binding.json"
    except (KeyError, OSError, TypeError, ValueError):
        return None


MANAGED_BINDING = _managed_binding()


@dataclass(frozen=True)
class ValidatorBinding:
    validator: Validator
    decoder: Callable
    config: LaunchConfig
    binding_digest: str
    implementation_digests: tuple[str, str]


def _load_absolute(path: Path, data: bytes) -> ModuleType:
    # Execute exactly the verified bytes; importlib loaders can reread a swapped path
    # or prefer a stale bytecode cache. Isolated Python supplies transitive imports.
    module = ModuleType("_supervised_binding_" + sha256(data))
    module.__file__ = str(path)
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module


def load_validator_binding(path: Path | None, *, workspace: Path, target: Path) -> ValidatorBinding | Refused:
    """Load only in the trusted installed interpreter's isolated (-I) mode.

    WORKER must call route preflight before this API or any envelope file read.
    The callable injection API in supervised_launch remains available offline.
    """
    try:
        _require(sys.flags.isolated, "isolated_python_required")
        _require(path is not None, "binding_unavailable")
        excluded = (workspace, target)
        raw = trusted_bytes(path, excluded=excluded)
        binding = _json(raw)
        _require(set(binding) == {"validator", "codec", "config", "template", "qualification"}, "binding_fields")
        config = LaunchConfig(_path(binding["config"]), _path(binding["template"]),
                              _path(binding["qualification"]) if binding["qualification"] else None)
        settings = _json(trusted_bytes(config.config_path, excluded=excluded))
        excluded += tuple(_path(root) for root in settings["reference_roots"])
        trusted_bytes(path, excluded=excluded)
        trusted_bytes(config.config_path, excluded=excluded)
        trusted_bytes(config.template_path, excluded=excluded)
        if config.qualification_path is not None:
            trusted_bytes(config.qualification_path, excluded=excluded)
        functions = []
        digests = []
        for kind, symbol in (("validator", "validate"), ("codec", "decode")):
            path = _path(binding[kind])
            data = trusted_bytes(path, excluded=excluded)
            module = _load_absolute(path, data)
            function = getattr(module, symbol, None)
            _require(callable(function), "binding_callable")
            functions.append(function)
            digests.append(sha256(data))
        return ValidatorBinding(functions[0], functions[1], config, sha256(raw), tuple(digests))
    except BaseException as exc:
        return Refused(str(exc) if isinstance(exc, _Refusal) else "binding_invalid")


@dataclass(frozen=True, slots=True)
class BindingLocator:
    binding_bytes: bytes
    controller_root: Path


@dataclass(frozen=True, slots=True)
class ValidatorContext:
    expected_assignment_digest: str
    expected_snapshot_ref: str
    expected_crosswalk_ref: str
    timeout_max_seconds: int
    qualified_routes: tuple
    policy_epoch: str
    revoked_record_ids: tuple[str, ...]
    caller_context_suitability: object
    policy: object
    snapshots: tuple[tuple[Path, bytes], ...]


@dataclass(frozen=True, slots=True)
class V2Binding:
    binding_bytes: bytes
    controller_root: Path
    context: ValidatorContext
    spec: object
    declarations: object
    implementations: tuple[tuple[str, Path, bytes], ...]
    snapshots: tuple[tuple[Path, bytes], ...]
    exclusions: tuple[Path, ...]
    bundle: object
    agreement: object = None
    codec: object = None
    validator: object = None


def _v2_data(raw):
    from .supervised_contracts import _v2_json
    from .supervised_envelope_v2 import _freeze
    value = _v2_json(raw)
    _require(isinstance(value, dict), "binding_invalid")
    return _freeze(value)


def _private_snapshot(path, *, excluded):
    import stat
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and not before.st_mode & 0o077, "binding_invalid")
    raw = trusted_bytes(path, excluded=excluded)
    after = path.lstat()
    _require((before.st_dev, before.st_ino, before.st_mode) == (after.st_dev, after.st_ino, after.st_mode), "binding_invalid")
    return raw


def _binding_reason(error):
    return str(error) if isinstance(error, _Refusal) else "binding_invalid"


def read_binding_locator(path: Path | None):
    """Read only the controller locator; references and selected code stay passive."""
    try:
        _require(path is not None, "binding_unavailable")
        raw = trusted_bytes(path)
        document = _v2_data(raw)
        return BindingLocator(raw, _path(document["controller_root"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, _Refusal) as error:
        return Refused(_binding_reason(error))


def load_v2_context(binding: Path, *, workspace: Path, target: Path, reference_roots: tuple[Path, ...]):
    """Capture the independent context, entire route store and its pinned evidence."""
    import time
    from .supervised_envelope_v2 import _freeze, _plain
    try:
        excluded = (workspace, target, *reference_roots)
        raw = _private_snapshot(binding, excluded=excluded)
        document = _v2_data(raw)
        required = {"expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref", "timeout_max_seconds",
                    "qualified_routes", "policy_epoch", "revoked_record_ids", "caller_context_suitability", "policy"}
        _require(set(document) == required, "binding_invalid")
        import re
        for field in ("expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref"):
            _require(type(document[field]) is str and re.fullmatch(r"[0-9a-f]{64}", document[field]) is not None, "binding_invalid")
        maximum = document["timeout_max_seconds"]
        _require(type(maximum) in (int, float) and maximum == int(maximum) and 0 < maximum <= 3600, "binding_invalid")
        policy = document["policy"]
        _require({"issuer_records", "time_basis"} <= set(policy) <= {"issuer_records", "time_basis", "caller_context_records"} and policy["time_basis"] == "system_utc", "binding_invalid")
        _require(isinstance(document["qualified_routes"], tuple) and isinstance(document["revoked_record_ids"], tuple)
                 and type(document["policy_epoch"]) is str and bool(document["policy_epoch"]), "binding_invalid")
        snapshots = [(binding, raw)]
        records = []
        now = time.time()
        for locator in document["qualified_routes"]:
            record_path = _path(locator["path"])
            record_raw = _private_snapshot(record_path, excluded=excluded)
            _require(sha256(record_raw) == locator["sha256"], "binding_invalid")
            record = _v2_data(record_raw)
            fields = {"record_id", "issuer_id", "policy_epoch", "valid_from", "expires_at", "evidence", "tier", "action",
                      "transport_id", "executable_chain", "template_sha256", "qualification_sha256", "grants",
                      "credential_sources", "observed_versions"}
            _require(set(record) == fields, "binding_invalid")
            _require(record["policy_epoch"] == document["policy_epoch"]
                     and record["record_id"] not in document["revoked_record_ids"]
                     and record["valid_from"] <= now < record["expires_at"], "binding_invalid")
            # The independent operator policy pins the collector's exact record.
            approved = policy["issuer_records"].get(record["issuer_id"], {})
            _require(approved.get(record["record_id"]) == sha256(record_raw), "binding_invalid")
            _require(len(record["observed_versions"]) == len(record["executable_chain"])
                     and all(type(version) is str and version for version in record["observed_versions"]), "binding_invalid")
            _require(bool(record["evidence"]), "binding_invalid")
            for evidence in record["evidence"]:
                evidence_path = _path(evidence["path"])
                evidence_raw = _private_snapshot(evidence_path, excluded=excluded)
                _require(sha256(evidence_raw) == evidence["sha256"], "binding_invalid")
                snapshots.append((evidence_path, evidence_raw))
            snapshots.append((record_path, record_raw))
            records.append(_freeze(_plain(record)))
        return ValidatorContext(*(document[name] for name in ("expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref")),
            int(maximum), tuple(records), document["policy_epoch"], document["revoked_record_ids"],
            document["caller_context_suitability"], policy, tuple(snapshots))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, _Refusal) as error:
        return Refused(_binding_reason(error))


def load_v2_binding(path: Path, *, workspace: Path, target: Path, reference_roots: tuple[Path, ...]):
    """Verify a passive v2 binding under the complete controller exclusions."""
    from .supervised_contracts import V2_INPUT_ARTIFACT_SHA256, load_contract_bundle
    from .supervised_envelope_v2 import _freeze, _plain
    try:
        _require(sys.flags.isolated, "isolated_python_required")
        _require(path is not None, "binding_unavailable")
        exclusions = (workspace, target, *reference_roots)
        raw = trusted_bytes(path, excluded=exclusions)
        document = _v2_data(raw)
        _require(set(document) == {"schema", "controller_root", "context", "spec", "implementations", "input_seal", "context_slots"}
                 and document["schema"] == "agent-harness.supervised-launch-binding.v2"
                 and document["input_seal"] == V2_INPUT_ARTIFACT_SHA256, "binding_invalid")
        controller_root = _path(document["controller_root"])
        context_path, spec_path = _path(document["context"]), _path(document["spec"])
        context = load_v2_context(context_path, workspace=workspace, target=target, reference_roots=reference_roots)
        if isinstance(context, Refused):
            return context
        spec_raw = _private_snapshot(spec_path, excluded=exclusions)
        spec = _v2_data(spec_raw)
        _require(set(spec) == {"slots", "launch"}, "binding_invalid")
        _require(isinstance(document["context_slots"], tuple)
                 and set(document["context_slots"]) <= {"expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref",
                                                         "timeout_max_seconds", "caller_context_suitability"}, "binding_invalid")
        implementations, snapshots = [], [(path, raw), (spec_path, spec_raw), *context.snapshots]
        for member in ("config_path", "template_path", "qualification_path", "environment_policy_path"):
            referenced = _path(spec["launch"][member])
            snapshots.append((referenced, _private_snapshot(referenced, excluded=exclusions)))
        _require(set(document["implementations"]) == {"codec", "validator"}, "binding_invalid")
        for kind in ("codec", "validator"):
            selected = document["implementations"][kind]
            _require(set(selected) == {"path", "sha256"}, "binding_invalid")
            module_path = _path(selected["path"])
            data = trusted_bytes(module_path, excluded=exclusions)
            _require(sha256(data) == selected["sha256"], "binding_invalid")
            implementations.append((kind, module_path, data))
            snapshots.append((module_path, data))
        bundle = load_contract_bundle(version="v2")
        package_root = Path(__file__).parent
        for name, data in bundle._captured:
            resource = package_root / "schemas/supervised-worker-v2" / name
            _require(trusted_bytes(resource, excluded=exclusions) == data, "binding_invalid")
            snapshots.append((resource, data))
        return V2Binding(raw, controller_root, context, spec, _freeze(_plain(document)), tuple(implementations),
                         tuple(snapshots), exclusions, bundle)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, _Refusal) as error:
        return Refused(_binding_reason(error))


def reconcile_v2_binding(locator: BindingLocator, binding: V2Binding, *, controller, attempt):
    """Reconcile held documents before any selected implementation executes."""
    from dataclasses import replace
    from .supervised_envelope_v2 import _freeze, _plain
    try:
        _require(type(locator) is BindingLocator and type(binding) is V2Binding
                 and locator.binding_bytes == binding.binding_bytes
                 and locator.controller_root == binding.controller_root, "binding_invalid")
        _require(set(controller) == {"h", "attempt", "context", "slots"}, "binding_invalid")
        from .supervised_launch import AttemptBinding
        from dataclasses import asdict
        import re
        _require(type(attempt) is AttemptBinding and _plain(controller["attempt"]) == asdict(attempt)
                 and type(controller["h"]) is str and re.fullmatch(r"[0-9a-f]{64}", controller["h"]) is not None,
                 "binding_invalid")
        context = controller["context"]
        fields = {"expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref", "timeout_max_seconds",
                  "qualified_routes", "policy_epoch", "revoked_record_ids", "caller_context_suitability"}
        _require(set(context) == fields and attempt.assignment_digest == context["expected_assignment_digest"], "binding_invalid")
        allowed = binding.declarations["context_slots"]
        for name in fields - set(allowed):
            _require(_plain(context[name]) == _plain(getattr(binding.context, name)), "binding_invalid")
        maximum = context["timeout_max_seconds"]
        _require(type(maximum) in (int, float) and maximum == int(maximum)
                 and 0 < maximum <= binding.context.timeout_max_seconds, "binding_invalid")
        import re
        for name in ("expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref"):
            _require(type(context[name]) is str and re.fullmatch(r"[0-9a-f]{64}", context[name]) is not None, "binding_invalid")
        slots = controller["slots"]
        _require(set(slots) == set(binding.spec["slots"]), "binding_invalid")
        for name, kind in binding.spec["slots"].items():
            value = slots[name]
            if kind == "root":
                _path(value)
            elif kind == "roots":
                _require(isinstance(value, (tuple, list)), "binding_invalid")
                for root in value:
                    _path(root)
            else:
                _require(kind == "argv" and type(value) is str and "\x00" not in value, "binding_invalid")
                value.encode("utf-8")
        def substitute(value):
            if hasattr(value, "keys"):
                if set(value) == {"slot"}:
                    return slots[value["slot"]]
                return {key: substitute(child) for key, child in value.items()}
            if isinstance(value, tuple):
                return [substitute(child) for child in value]
            return value
        launch = substitute(binding.spec["launch"])
        roots = (_path(launch["workspace"]), _path(launch["target"]), *(_path(root) for root in launch["reference_roots"]))
        _require(roots == binding.exclusions, "binding_invalid")
        effective = replace(binding.context, snapshots=binding.snapshots,
                            **{name: _freeze(_plain(context[name])) for name in allowed})
        agreement = (attempt, controller["h"], _freeze(_plain(controller)))
        spec = _spec_from_document(launch)
        return replace(binding, context=effective, spec=spec, agreement=agreement)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, _Refusal) as error:
        return Refused(_binding_reason(error))


def activate_v2_binding(binding: V2Binding):
    """Activate the approved held bytes only after controller agreement."""
    from dataclasses import replace
    try:
        _require(type(binding) is V2Binding and binding.agreement is not None and sys.flags.isolated, "binding_invalid")
        handles = {}
        for kind, path, data in binding.implementations:
            name = "_supervised_v2_" + kind + "_" + sha256(data)
            module = ModuleType(name)
            module.__file__, module.__package__ = str(path), "phase_loop_runtime"
            sys.modules[name] = module
            try:
                exec(compile(data, str(path), "exec"), module.__dict__)
            except BaseException:
                sys.modules.pop(name, None)
                raise
            handles[kind] = module
        codec, validator = handles["codec"], handles["validator"]
        _require(getattr(codec, "PUBLIC_CODEC", None) == "admitted_launch_envelope.v2"
                 and all(callable(getattr(codec, name, None)) for name in ("decode_v2", "validate_v2_admission", "canonicalize_v2"))
                 and callable(getattr(validator, "validate", None)), "binding_invalid")
        return replace(binding, codec=codec, validator=validator.validate)
    except BaseException as error:
        return Refused(_binding_reason(error))



def _spec_from_document(document):
    """Construct a final immutable local spec from the agreed operator slots."""
    from .supervised_capture_v2 import SourceSpec, TrustedLaunchSpec
    def source(value):
        _require(set(value) <= {"source", "path", "descriptor", "content"} and "source" in value, "binding_invalid")
        descriptor = value.get("descriptor")
        if descriptor is not None:
            _require(type(descriptor) in (int, float) and descriptor == int(descriptor) and descriptor >= 0, "binding_invalid")
            descriptor = int(descriptor)
        content = value.get("content")
        _require(content is None or type(content) is str, "binding_invalid")
        return SourceSpec(value["source"], _path(value["path"]) if "path" in value else None,
                          descriptor, content.encode() if content is not None else None)
    required = {"workspace", "target", "reference_roots", "argv", "cwd", "cwd_locator", "instructions", "references",
                "executable_chain", "config_path", "template_path", "qualification_path", "environment_policy_path",
                "environment_policy_id", "non_secret_environment", "secret_sources", "timeout_seconds", "deadline_action",
                "tier", "base_commit", "target_map"}
    optional = {"grants", "envelope_cap", "reference_cap", "aggregate_cap", "stdin", "declared_roots", "view_roots",
                "template_slots", "discovery_names", "action", "transport_id"}
    _require(required <= set(document) and set(document) <= required | optional, "binding_invalid")
    values = dict(document)
    for name in ("workspace", "target", "cwd", "config_path", "template_path", "qualification_path", "environment_policy_path"):
        values[name] = _path(values[name])
    values["reference_roots"] = tuple(_path(path) for path in values["reference_roots"])
    values["instructions"] = source(values["instructions"])
    values["references"] = tuple((row["role"], source({key: value for key, value in row.items() if key != "role"})) for row in values["references"])
    values["executable_chain"] = tuple((row["wire"], _path(row["path"])) for row in values["executable_chain"])
    values["non_secret_environment"] = tuple(values["non_secret_environment"].items())
    values["secret_sources"] = tuple((row["name"], row["source"], _path(row["path"])) for row in values["secret_sources"])
    values["argv"] = tuple(values["argv"])
    values["target_map"] = tuple(values["target_map"])
    values["grants"] = tuple((name, row["canonical_form"], _path(row["path"]) if row["canonical_form"] == "raw_bytes" else row["value"])
                            for name, row in values.get("grants", {}).items())
    for name in ("declared_roots", "view_roots"):
        values[name] = tuple((key, _path(path)) for key, path in values.get(name, {}).items())
    values["template_slots"] = tuple(values.get("template_slots", {}).items())
    values["discovery_names"] = tuple(values.get("discovery_names", ()))
    for name in ("timeout_seconds", "envelope_cap", "reference_cap", "aggregate_cap"):
        if name in values:
            number = values[name]
            _require(type(number) in (int, float) and number == int(number) and number > 0, "binding_invalid")
            values[name] = int(number)
    return TrustedLaunchSpec(**values)
