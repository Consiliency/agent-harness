"""Bounded CLI transport for the separate JEV Drill environment.

Run-bound explicit reports (EC-HOST-2 item 3 hook). A launched run keeps one ordered
ExecutionEvent stream. Integrations that report on that run use three public methods of
``JevDrillAdapter``:

- ``run_event_identity(execution_run_id)`` returns the run's ``task_id``,
  ``routing_decision_id`` and ``execution_run_id``, plus the stream's ``source_id`` and the
  next ``source_sequence`` it would allocate;
- ``enqueue_run_event(execution_run_id, payload)`` is the public enqueue path for hooks. It
  assigns the envelope, ``event_id``, ``source_id`` and the next ``source_sequence`` under
  the same lock the host's own lifecycle reports use, then enqueues through the adapter's
  ``ReportQueue`` and sanitizer. Sequence allocation and enqueue happen together, so on one
  run hook and host reports never share a ``source_sequence`` and enter the queue in
  sequence order. Delivery order is not guaranteed: a report in retry backoff can be
  delivered after a later one, so consumers order a run's events by ``source_sequence``.
  Lifecycle payloads stay host-owned and are refused. It returns the queue disposition
  (``queued``, ``duplicate``, ``conflict``, ``overflow`` or ``deleted``);
- ``run_report_counts(execution_run_id)`` returns that run's enqueue-time queue entries and
  losses. Losses after enqueue (expiry, delivery conflict or rejection) are counted only
  queue-wide, by ``adapter.queue.status()``.

Run handles live in memory, for at most ``RUN_HANDLE_LIMIT`` most recently launched runs.
They do not survive a restart: after one, an unknown run ID raises ``KeyError``.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import threading
import time
import weakref
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from collections import OrderedDict

from .host_integration import (ACCEPTANCE_FAILURE_CLASSES, DEACTIVATION_REASONS, RetryBudget,
                               annotate_disconnect, deactivation_reason, disconnect_advice)
from .jevdrill_queue import ReportQueue

_CODEX_USAGE_METHODS = ("codex_exec_jsonl_0_159_2_v1", "codex_exec_jsonl_0_159_2_v2")
# GAPS §5 Q2: a fixed reserve for the child CLI's own start, measured, never learned.
SPAWN_ALLOWANCE_MS = 250
_BUDGETED_COMMANDS = ("route", "discover", "notices", "report", "inspect-discovery", "delete-discovery")
RETRY_LEDGER_LIMIT = 256
RUN_HANDLE_LIMIT = 256
ROUTED_BUNDLE_LIMIT = 65_536
_SOURCE_ID = "agent-harness"


def load_harness_declarations(repo: Path, *, allowed_ignored_paths=()):
    """Read the versioned project declaration only; never execute or discover tools."""
    repo = repo.resolve()
    path = repo / ".jevdrill" / "harnesses.yaml"
    if not path.exists():
        return None
    if path.resolve() != path.absolute() or path.parent.resolve() != (repo.resolve() / ".jevdrill"):
        raise ValueError("Harness declaration symlinks are not allowed")
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", ".jevdrill/harnesses.yaml"],
                             cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if ignored.returncode not in (0, 1):
        raise ValueError("Cannot establish declaration read boundary")
    if ignored.returncode == 0 and path.resolve() not in {Path(p).resolve() for p in allowed_ignored_paths}:
        raise ValueError("Ignored harness declaration requires an exact read allowance")
    with path.open("rb") as stream:
        raw = stream.read(JevDrillTransport.MAX_BYTES + 1)
    if len(raw) > JevDrillTransport.MAX_BYTES:
        raise ValueError("Harness declaration exceeds size limit")
    class DeclarationLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ValueError("Duplicate or non-string declaration key")
            result[key] = loader.construct_object(value_node)
        return result
    DeclarationLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(raw)):
        raise ValueError("Declaration aliases are not allowed")
    value = yaml.load(raw, Loader=DeclarationLoader)
    if not isinstance(value, dict) or set(value) != {"schema_version", "harnesses"} or value["schema_version"] != "1":
        raise ValueError("Unsupported harness declaration contract")
    if not isinstance(value["harnesses"], list):
        raise ValueError("Harness declarations must be a list")
    from uuid import UUID
    seen = set()
    for row in value["harnesses"]:
        if not isinstance(row, dict) or set(row) != {"harness_id", "execution_target_id", "declared_capabilities", "access_routes"}:
            raise ValueError("Unexpected harness declaration fields")
        for key in ("harness_id", "execution_target_id"):
            if not isinstance(row[key], str) or str(UUID(row[key])) != row[key]:
                raise ValueError("Harness identities must be UUIDs")
        identity = row["harness_id"], row["execution_target_id"]
        if identity in seen:
            raise ValueError("Duplicate harness identity")
        seen.add(identity)
        for key in ("declared_capabilities", "access_routes"):
            if not isinstance(row[key], list) or any(not isinstance(v, str) or not v for v in row[key]):
                raise ValueError("Harness capability and route declarations must be strings")
    return value


class JevDrillTransport:
    MAX_BYTES = 1_000_000

    def __init__(self, argv: tuple[str, ...], storage: Path, schemas: Path,
                 schema_digests: dict[str, str]):
        if not argv:
            raise ValueError("JEV Drill CLI argv is required")
        self.argv = argv
        self.storage = storage
        self.validators = {}
        for name, expected in schema_digests.items():
            if Path(name).name != name:
                raise ValueError("Schema names must be filenames")
            raw = (schemas / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("JEV Drill schema digest mismatch")
            schema = json.loads(raw)
            Draft202012Validator.check_schema(schema)
            self.validators[Path(name).stem] = Draft202012Validator(schema, format_checker=FormatChecker())

    def call(self, command: str, payload: dict, *, started_at: float | None = None) -> dict:
        deadline = (time.monotonic() if started_at is None else started_at) + 5
        names = {
            "route": ("DiscoveryRouteInputs" if payload.get("schema_version") == "2" else "RouteInputs", "RoutingDecision"),
            "discover": ("DiscoveryInputs", "DiscoveryResult"),
            "inspect-discovery": ("DiscoveryInspectRequest", "DiscoveryResult"),
            "delete-discovery": ("DiscoveryDeleteRequest", None),
            "report": ("ReportRequest", "ReportAcknowledgment"),
            "notices": ("NoticeRequest", "NoticeInbox"),
            "delete": ("DeleteRequest", None),
        }
        request_schema, response_schema = names[command]
        self.validators[request_schema].validate(payload)
        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
        if len(encoded) > self.MAX_BYTES:
            raise ValueError("JEV Drill request exceeds transport limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("JEV Drill deadline expired before spawn")
        argv = [*self.argv, "--storage", str(self.storage)]
        budget_index = None
        if command in _BUDGETED_COMMANDS:
            argv += ["--remaining-budget-ms", ""]
            budget_index = len(argv) - 1
        argv.append(command)
        if command == "delete":
            argv += ["--task-id", payload["task_id"], "--scope", json.dumps(payload["scope"])]
            encoded = b""
        elif command == "inspect-discovery":
            argv += ["--discovery-id", payload["discovery_id"], "--scope", json.dumps(payload["scope"])]
            if payload["replay"]:
                raise ValueError("Host launch revalidation requires the strict stored result")
            encoded = b""
        elif command == "delete-discovery":
            argv += ["--work-objective-id", payload["work_objective_id"], "--scope", json.dumps(payload["scope"])]
            encoded = b""
        if budget_index is not None:
            # The child anchors its deadline at its own start, so reserve its startup time.
            budget_ms = int((deadline - time.monotonic()) * 1000) - SPAWN_ALLOWANCE_MS
            if budget_ms <= 0:
                raise TimeoutError("JEV Drill budget is within the spawn reserve before spawn")
            argv[budget_index] = str(budget_ms)
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, shell=False)
        output = bytearray()
        overflow = threading.Event()
        write_failed = threading.Event()

        def write():
            try:
                process.stdin.write(encoded)
                process.stdin.close()
            except OSError:
                write_failed.set()

        def read():
            while chunk := process.stdout.read(8192):
                if len(output) + len(chunk) > self.MAX_BYTES:
                    overflow.set()
                    process.kill()
                    break
                output.extend(chunk)

        writer = threading.Thread(target=write, daemon=True)
        reader = threading.Thread(target=read, daemon=True)
        writer.start()
        reader.start()
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
            reader.join(timeout=max(0, deadline - time.monotonic()))
            writer.join(timeout=max(0, deadline - time.monotonic()))
            if reader.is_alive() or writer.is_alive():
                raise TimeoutError("JEV Drill streams exceeded deadline")
            if overflow.is_set():
                raise ValueError("JEV Drill response exceeds transport limit")
            if process.returncode not in (0, 3) or write_failed.is_set():
                raise OSError("JEV Drill CLI failed")
            def strict_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("Duplicate response key")
                    value[key] = item
                return value
            def invalid_constant(_):
                raise ValueError("Non-finite response value")
            response = json.loads(output, object_pairs_hook=strict_object, parse_constant=invalid_constant)
            if response_schema is None:
                field = "work_objective_id" if command == "delete-discovery" else "task_id"
                if response != {"schema_version": "1", "status": "deleted", field: payload[field]}:
                    raise ValueError("Invalid deletion acknowledgment")
            elif command == "inspect-discovery" and response == {"schema_version": "1", "status": "not_found"}:
                pass
            else:
                self.validators[response_schema].validate(response)
            if process.returncode == 3 and not (command == "report" and response["status"] == "conflict"):
                raise OSError("JEV Drill CLI failed")
            if time.monotonic() >= deadline:
                raise TimeoutError("JEV Drill response validation exceeded deadline")
            return response
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("JEV Drill CLI exceeded deadline") from exc
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            writer.join(timeout=0.1)
            reader.join(timeout=0.1)
            if not writer.is_alive():
                process.stdin.close()
            if not reader.is_alive():
                process.stdout.close()


class JevDrillUnavailable(ValueError):
    """Routing could not establish a launch that respects host authority."""

    def __init__(self, message, *, decision=None):
        super().__init__(message)
        self.decision = deepcopy(decision)


def _bundle_fingerprint(bundle):
    """A digest of every dataclass field, kept across copies and field reconstruction."""
    from dataclasses import astuple, is_dataclass
    value = astuple(bundle) if is_dataclass(bundle) else (type(bundle).__name__, id(bundle))
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _fresh(snapshot):
    now = datetime.now(timezone.utc)
    return (datetime.fromisoformat(snapshot["verified_at"].replace("Z", "+00:00")) <= now
            < datetime.fromisoformat(snapshot["expires_at"].replace("Z", "+00:00")))


class JevDrillAdapter:
    """Explicit host integration; callbacks are trusted host policy, never model output.

    inputs_for supplies authorized task context. verify_candidate independently
    checks the live inventory identity. limits_enforced checks the FINAL launch
    spec and establishes total-run input/output enforcement when a spending,
    retry-spend or token ceiling is requested. Without a requested ceiling,
    verified executors may use estimated-cost routing without token enforcement.
    """

    def __init__(self, transport, queue_path, *, inputs_for, verify_candidate,
                 limits_enforced, notice_sink, capabilities_for, allowed_ignored_paths=(),
                 recommendation_action=None):
        required = {"RouteInputs", "RoutingDecision", "ReportRequest", "ReportAcknowledgment",
                    "NoticeRequest", "NoticeInbox", "ExecutionRun", "DeleteRequest"}
        if not required <= transport.validators.keys():
            raise ValueError("Incomplete JEV Drill contract schema set")
        self.transport = transport
        self.inputs_for = inputs_for
        self.verify_candidate = verify_candidate
        self.limits_enforced = limits_enforced
        self.notice_sink = notice_sink
        self.capabilities_for = capabilities_for
        self.allowed_ignored_paths = allowed_ignored_paths
        self.queue = ReportQueue(queue_path, sanitize=self.sanitize_report)
        self._pending = {}
        self.delivery_warnings = []
        self.last_decision = None
        self.recommendation_action = recommendation_action or (lambda _decision, _context: "apply")
        self._prompt_bases = {}
        # Retry ledger (GAPS §3.1): open tasks only, never evicted, lost on restart.
        self._ledger_lock = threading.RLock()
        self._ledger = {}
        self._run_index = {}
        self._ledger_generation = 0
        # Routing provenance by bundle content: fingerprint -> ids of its pending bindings.
        self._routed = OrderedDict()
        # One lock orders every event on a run's stream, host and hook alike.
        self._report_lock = threading.RLock()
        self._runs = OrderedDict()

    def _call(self, command, payload, *, started_at=None, operation="route"):
        """Call the CLI; a transport failure keeps its object and gains resolution advice."""
        try:
            return self.transport.call(command, payload, started_at=started_at)
        except (OSError, TimeoutError) as exc:
            if getattr(exc, "resolution_advice", None) is None:
                annotate_disconnect(exc, operation)
                if operation == "route":
                    self._emit_notice(self._disconnect_notice("route"))
            raise

    @staticmethod
    def _disconnect_notice(operation):
        return {"kind": "transport_disposition", "status": "disconnected", "operation": operation,
                "resolution_advice": list(disconnect_advice(operation))}

    def discover_objective(self, inputs, *, started_at=None):
        started = time.monotonic() if started_at is None else started_at
        inputs = deepcopy(inputs)
        self.transport.validators["DiscoveryInputs"].validate(inputs)
        with self.queue.objective_guard():
            if self.queue.objective_deleted(inputs["envelope"], inputs["work_objective_id"]):
                raise JevDrillUnavailable("Objective is deleted")
            self._notices(inputs["envelope"], started_at=started)
            result = self._call("discover", inputs, started_at=started)
            self.transport.validators["DiscoveryResult"].validate(result)
            details = result["details"]
            if details["work_objective_id"] != inputs["work_objective_id"]:
                raise JevDrillUnavailable("Discovery objective identity mismatch")
            if result["status"] not in ("selected_guidance", "no_optional_guidance"):
                raise JevDrillUnavailable("JEV Drill discovery outcome: " + result["status"], decision=result)
            ref = {key: details[key] for key in ("discovery_id", "work_objective_id", "trace_digest")}
            self.transport.validators["DiscoveryRef"].validate(ref)
            self.queue.bind_objective(inputs["envelope"], ref)
            return result

    def _check_discovery(self, envelope, ref, *, started_at=None, gate=None):
        self.transport.validators["DiscoveryRef"].validate(ref)
        if not self.queue.objective_bound(envelope, ref):
            raise JevDrillUnavailable("Objective binding is missing or deleted")
        if gate is not None:
            gate()
        scope = {"project_id": envelope["project_id"], "workspace_id": envelope["workspace_id"],
                 "producer": envelope["harness_id"], "operation": "discover"}
        result = self._call("inspect-discovery", {"schema_version": "1", "scope": scope,
                            "discovery_id": ref["discovery_id"], "replay": False},
                            started_at=started_at)
        if result["status"] not in ("selected_guidance", "no_optional_guidance") or any(
                result["details"][key] != value for key, value in ref.items()):
            raise JevDrillUnavailable("Stored discovery is unavailable or changed")
        return result

    def delete_objective(self, scope, work_objective_id):
        payload = {"schema_version": "1", "scope": scope, "work_objective_id": work_objective_id}
        self.transport.validators["DiscoveryDeleteRequest"].validate(payload)
        with self.queue.objective_guard():
            self.queue.delete_objective(scope["project_id"], scope["workspace_id"], work_objective_id)
            started = time.monotonic()
            self._notices({"project_id": scope["project_id"], "workspace_id": scope["workspace_id"],
                           "harness_id": scope["producer"], "operation": "discover"}, started_at=started)
            return self.transport.call("delete-discovery", payload, started_at=started)

    def sanitize_report(self, report):
        self.transport.validators["ReportRequest"].validate(report)
        clean = deepcopy(report)
        event, envelope = clean["event"], clean["envelope"]
        payload = event["payload"]
        if payload["kind"] == "lifecycle":
            # Only a closed deactivation code survives; free text never persists.
            if not (payload["event_type"] == "guidance_deactivated"
                    and payload["reason"] in DEACTIVATION_REASONS):
                payload["reason"] = None
        elif payload["kind"] == "host_choice":
            from uuid import UUID
            if str(UUID(payload["selected_run_id"])) != payload["selected_run_id"]:
                raise ValueError("Host choice must identify a run UUID")
            payload["reason"] = "redacted"
        else:
            self._validate_measurements(payload["measurements"])
            if payload["kind"] == "evaluation":
                payload["check_results"] = {hashlib.sha256(k.encode()).hexdigest(): v
                                            for k, v in payload["check_results"].items()}
                for key in ("evaluator_ref", "rubric_revision"):
                    payload[key] = hashlib.sha256(payload[key].encode()).hexdigest()
        applied = payload.get("applied_plan_id")
        if applied is not None:
            from uuid import UUID
            if str(UUID(applied)) != applied:
                raise ValueError("Invalid applied plan identity")
        for field in ("idempotency_key",):
            envelope[field] = hashlib.sha256(envelope[field].encode()).hexdigest()
        # Host identities are protocol linkage, not redaction targets. Require
        # explicit opaque identifiers so callers cannot persist arbitrary paths.
        from uuid import UUID
        for field in ("execution_target_id", "harness_id"):
            if str(UUID(envelope[field])) != envelope[field]:
                raise ValueError("Host report identities must be opaque UUIDs")
        envelope["extensions"] = {}
        event["source_id"] = hashlib.sha256(event["source_id"].encode()).hexdigest()
        self.transport.validators["ReportRequest"].validate(clean)
        if len(json.dumps(clean, allow_nan=False, separators=(",", ":")).encode()) > self.transport.MAX_BYTES:
            raise ValueError("Sanitized report exceeds transport limit")
        return clean

    @staticmethod
    def _validate_measurements(measurements):
        units = {"completion_time_ms": "ms", "input_tokens": "tokens", "output_tokens": "tokens",
                 "cached_input_tokens": "tokens", "reasoning_tokens": "tokens", "quality_score": "score"}
        for measurement in measurements:
            metric = measurement["metric_id"]
            if (metric not in units or measurement["metric_version"] != "1"
                    or measurement["method"] not in ("monotonic_ns", "provider_reported", "host_reported", "evaluator", *_CODEX_USAGE_METHODS)
                    or measurement["parent_metric_id"] not in (None, *units)):
                raise ValueError("Unregistered measurement metadata")
            value = measurement["measurement_value"]
            if value["kind"] == "known" and (value["unit"] != units[metric]
                    or not math.isfinite(value["value"]) or value["value"] < 0):
                raise ValueError("Invalid measurement value")
            if measurement["method"] in _CODEX_USAGE_METHODS:
                parent = "input_tokens" if metric == "cached_input_tokens" else "output_tokens" if metric == "reasoning_tokens" else None
                if (metric not in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
                        or measurement["source"] != "host" or measurement["scope"] != "run"
                        or measurement["parent_metric_id"] != parent
                        or measurement["counting_semantics"] != ("subset" if parent else "disjoint")
                        or (value["kind"] == "known" and (isinstance(value["value"], bool)
                            or not 0 <= value["value"] <= 2**53-1 or int(value["value"]) != value["value"]))):
                    raise ValueError("Invalid Codex usage metadata or counter")
        by_metric = {m["metric_id"]: m for m in measurements}
        if len(by_metric) != len(measurements):
            raise ValueError("Duplicate metric")
        for subset, parent in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
            m = by_metric.get(subset)
            if m and m["method"] in _CODEX_USAGE_METHODS and m["measurement_value"]["kind"] == "known":
                p = by_metric.get(parent, {}).get("measurement_value", {})
                if p.get("kind") != "known" or m["measurement_value"]["value"] > p["value"]:
                    raise ValueError("Invalid Codex subset")

    def _notices(self, envelope, *, started_at=None, operation="route", deferred=None):
        inbox = self._call("notices", {"schema_version": "1", "scope": {
            "project_id": envelope["project_id"], "workspace_id": envelope["workspace_id"],
            "producer": envelope["harness_id"], "operation": "report" if envelope["operation"] == "report" else "route"}},
            started_at=started_at, operation=operation)
        for notice in inbox["notices"]:
            if deferred is not None:
                deferred.append(notice)
            else:
                self._emit_notice(notice)

    def _emit_notice(self, notice):
        try:
            self.notice_sink(notice)
        except Exception:
            self.delivery_warnings.append({"kind": "transport_disposition", "status": "notice_delivery_failed"})

    def prepare(self, *, mode, dry_run, **kwargs):
        if dry_run:
            return kwargs
        started = time.monotonic()
        routing_started = time.monotonic_ns()
        inputs = deepcopy(self.inputs_for({"mode": mode, **kwargs}))
        linked = inputs.get("schema_version") == "2"
        self.transport.validators["DiscoveryRouteInputs" if linked else "RouteInputs"].validate(inputs)
        request = inputs["route_inputs"]["request"] if linked else inputs["request"]
        if request["recursion_bypass"]:
            return kwargs
        with self.queue.objective_guard():
            return self._prepare(mode=mode, inputs=inputs, started_at=started,
                                 routing_started=routing_started, **kwargs)

    def _prepare(self, *, mode, inputs, started_at, routing_started, **kwargs):
        started = started_at
        context = {"mode": mode, **kwargs}
        linked = inputs.get("schema_version") == "2"
        self.transport.validators["DiscoveryRouteInputs" if linked else "RouteInputs"].validate(inputs)
        wrapper = inputs if linked else None
        inputs = inputs["route_inputs"] if linked else inputs
        request = inputs["request"]
        if request["recursion_bypass"]:
            return kwargs
        from uuid import UUID
        for field in ("execution_target_id", "harness_id"):
            value = request["envelope"][field]
            if str(UUID(value)) != value:
                raise JevDrillUnavailable("Host route identities must be opaque UUIDs")
        if request["execution_mode"] != ("main" if mode == "main" else "delegated"):
            raise JevDrillUnavailable("Execution mode does not match host entrypoint")
        # GAPS §3.8 (Q1): a present declaration that omits this identity gets no CLI request.
        declarations = load_harness_declarations(kwargs["repo"], allowed_ignored_paths=self.allowed_ignored_paths) if "repo" in kwargs else None
        declaration = None
        if declarations is not None:
            envelope = request["envelope"]
            declaration = next((row for row in declarations["harnesses"]
                                if row["harness_id"] == envelope["harness_id"]
                                and row["execution_target_id"] == envelope["execution_target_id"]), None)
            if declaration is None:
                raise JevDrillUnavailable("Harness identity is not declared")
        ledger_key = (request["envelope"]["project_id"], request["envelope"]["workspace_id"], request["task_id"])
        admission = self._admit_route(ledger_key, request, routing_started)
        request["retry_context"] = admission["context"]
        self._notices(request["envelope"], started_at=started)
        if linked:
            self._check_discovery(request["envelope"], wrapper["discovery_ref"], started_at=started)
        if self.queue.is_deleted(request["envelope"]["project_id"], request["envelope"]["workspace_id"], request["task_id"]):
            raise JevDrillUnavailable("Task is deleted")
        inventory = inputs["inventory"]
        if inventory is None or not _fresh(inventory):
            raise JevDrillUnavailable("Verified inventory is unavailable or stale")
        if inventory["target"] != request["envelope"]["execution_target_id"]:
            raise JevDrillUnavailable("Inventory target does not match request")
        executor = kwargs["executor"]
        capabilities = request["capabilities"]
        declared, runtime = self.capabilities_for(context)
        declared_routes = None
        if declaration is not None:
            declared = set(declared) & set(declaration["declared_capabilities"])
            declared_routes = set(declaration["access_routes"])
        capabilities["declared"] = sorted(set(capabilities["declared"]) & set(declared))
        capabilities["runtime"] = sorted(set(capabilities["runtime"]) & set(runtime))
        allowed = set(capabilities["declared"]) & set(capabilities["runtime"])
        if not _fresh(capabilities):
            raise JevDrillUnavailable("Host capabilities are stale")
        candidates = []
        constraints = request["hard_constraints"]
        requested_limits = constraints.get("execution_token_limits")
        limits_required = (requested_limits is not None
                           or constraints["spending_ceiling"] is not None
                           or (request["retry_context"] is not None
                               and request["retry_context"]["remaining_spend"] is not None))
        for candidate in inventory["candidates"]:
            limits = candidate.get("execution_token_limits")
            if limits_required and (limits is None or (requested_limits is not None and
                    any(limits[key] > requested_limits[key] for key in requested_limits))):
                continue
            if (candidate["access_route"] != executor + "_cli" or not _fresh(candidate)
                    or (declared_routes is not None and candidate["access_route"] not in declared_routes)
                    or not candidate["resolved_model_revision"] or not candidate["token_counter_revision"]
                    or not set(candidate["required_capabilities"]) <= allowed
                    or not self.verify_candidate(deepcopy(candidate), context)):
                continue
            candidates.append(candidate)
        inventory["candidates"] = candidates
        decision = self._call("route", wrapper if linked else inputs, started_at=started)
        self.last_decision = deepcopy(decision)
        if decision["status"] != "ready":
            raise JevDrillUnavailable("JEV Drill outcome: " + decision["status"], decision=decision)
        details, plan = decision["details"], decision["execution_plan"]
        if linked and details.get("discovery_ref") != wrapper["discovery_ref"]:
            raise JevDrillUnavailable("Routing discovery reference mismatch")
        readiness = decision["readiness"]
        if (readiness["inventory_revision"] != inventory["revision"]
                or not _fresh({"verified_at": readiness["verified_at"], "expires_at": readiness["valid_until"]})):
            raise JevDrillUnavailable("Decision readiness is stale", decision=decision)
        if (details["task_id"] != request["task_id"]
                or details["request_id"] != request["envelope"]["request_id"]
                or plan["harness_id"] != request["envelope"]["harness_id"]
                or plan["execution_target_id"] != request["envelope"]["execution_target_id"]):
            raise JevDrillUnavailable("Routing identity mismatch")
        candidate = next((c for c in candidates if all(c[k] == plan[k] for k in
                         ("provider", "model_id", "resolved_model_revision", "access_route", "native_effort"))), None)
        if candidate is None or not set(plan["required_capabilities"]) <= allowed:
            raise JevDrillUnavailable("Selected identity or capabilities are unverified")
        if admission["unrecorded"]:
            # Never forwarded as accepted retry authority, never launchable.
            raise JevDrillUnavailable("Supplied retry context is unverified: no host retry record",
                                      decision=decision)
        selection = kwargs["model_selection"]
        effort = plan["native_effort"]
        if effort["kind"] != "explicit" or effort["native_value"] not in candidate["supported_efforts"]:
            raise JevDrillUnavailable("Native effort is not enforceable by this bridge")
        selected_effort = effort["native_value"]
        if selection.source not in ("default", executor + "_default") and (
                plan["model_id"] != selection.model or selected_effort != selection.effort):
            raise JevDrillUnavailable("Routing would replace an operator or policy override")
        if any(g not in plan["required_guidance"] for g in request["active_guidance"]):
            raise JevDrillUnavailable("Required guidance was removed")
        if self.recommendation_action(deepcopy(decision), context) != "apply":
            raise JevDrillUnavailable("Host declined routing recommendation", decision=decision)
        bundle = kwargs["prompt_bundle"]
        prior = self._prompt_bases.get(id(bundle))
        if prior is not None and prior[0]() is bundle:
            bundle = prior[1]
        base_bundle = bundle
        additions, seen = [], set()
        for guidance in plan["optional_guidance"]:
            key = (guidance["resource_id"], guidance["revision"], guidance["content_hash"])
            if key in seen:
                continue
            seen.add(key)
            resource = next((r for r in (inputs["catalog"] or {}).get("resources", [])
                             if (r["resource_id"], r["revision"], r["content_hash"]) == key), None)
            if (resource is None or guidance["task_id"] != request["task_id"]
                    or resource["admission"] not in ("policy_admitted", "explicitly_enabled")
                    or hashlib.sha256(resource["instructions"].encode()).hexdigest() != key[2]):
                raise JevDrillUnavailable("Optional guidance identity is unverified")
            additions.append(resource["instructions"])
        if additions:
            extra = "\n\n" + "\n\n".join(additions)
            bundle = replace(bundle, body=bundle.body + extra,
                             context_body=(bundle.context_body + extra if bundle.context_body is not None else None))
        else:
            bundle = replace(bundle)
        self._prompt_bases[id(bundle)] = (
            weakref.ref(bundle, lambda _ref, identity=id(bundle): self._prompt_bases.pop(identity, None)),
            base_bundle,
        )
        chosen = (replace(selection, model=plan["model_id"], effort=selected_effort, source="jevdrill")
                  if selection.source in ("default", executor + "_default") else selection)
        kwargs = {**kwargs, "prompt_bundle": bundle, "model_selection": chosen}
        if executor == "codex":
            kwargs["json_output"] = True
        run_id = str(uuid4())
        if linked:
            self.queue.bind_task(request["envelope"], wrapper["discovery_ref"], request["task_id"],
                                 details["routing_decision_id"], run_id)
        # Every fallible step is done: only now does the ledger hold this prepare.
        generation = self._commit_route(admission)
        fingerprint = _bundle_fingerprint(bundle)
        self._pending[id(bundle)] = {"request": request, "decision": decision, "candidate": candidate,
                                    "linked_inputs": deepcopy(wrapper),
                                    "limits_required": limits_required, "fingerprint": fingerprint,
                                    "context": context, "run_id": run_id, "sequence": 0,
                                    "ledger_key": ledger_key, "ledger_generation": generation,
                                    "counts": {"queued": 0, "losses": {}},
                                    "routing_ms": (time.monotonic_ns() - routing_started) / 1_000_000,
                                    "guidance": bool(additions),
                                    "freshness": [{"verified_at": row["verified_at"], "expires_at": row["expires_at"]}
                                                  for row in (inventory, capabilities)]}
        weakref.finalize(bundle, self._pending.pop, id(bundle), None)
        self._routed.setdefault(fingerprint, []).append(id(bundle))
        self._routed.move_to_end(fingerprint)
        while len(self._routed) > ROUTED_BUNDLE_LIMIT:
            self._routed.popitem(last=False)
        return kwargs

    # --- Retry ledger (GAPS §3.1) -------------------------------------------------------

    def _admit_route(self, key, request, routing_started):
        """Check the task's retry budget before any CLI contact.

        Returns an admission for ``_commit_route``. The budget comes from the trusted host
        request and is only ever tightened. Retry context is generated only from a recorded
        acceptance failure, counting every launched attempt; a supplied context must agree
        with that record and may not widen it. A supplied context with no ledger entry may
        be routed, but ``unrecorded`` makes ``_prepare`` refuse it before any launchable
        decision (erratum 1, row 1d). A first entry is only committed by a prepare that
        succeeds, so a refused prepare never holds a ledger slot.
        """
        constraints = request["hard_constraints"]
        offered = RetryBudget(constraints["max_attempts"], constraints["total_deadline_ms"], routing_started)
        supplied = request["retry_context"]
        admission = {"key": key, "budget": offered, "context": None, "unrecorded": False, "generation": None}
        with self._ledger_lock:
            entry = self._ledger.get(key)
            if entry is not None:
                admission["generation"] = entry["generation"]
            if entry is None:
                if len(self._ledger) >= RETRY_LEDGER_LIMIT:
                    raise JevDrillUnavailable("Retry ledger is full")
                # No host record: a context-free request is a first attempt.
                admission.update(context=supplied, unrecorded=supplied is not None)
                return admission
            entry["budget"] = budget = entry["budget"].tighten(offered)
            attempts = entry["attempts"]
            judged = sum(1 for attempt in attempts if attempt["outcome"] != "launched")
            now = time.monotonic_ns()
            # A launch with no verdict yet is counted at launch admission (erratum 1, row 1c).
            if budget.exhausted(judged, now):
                raise JevDrillUnavailable("Retry budget is exhausted")
            latest = attempts[-1] if attempts else None
            if latest is None or latest["outcome"] not in ACCEPTANCE_FAILURE_CLASSES:
                if supplied is not None:
                    raise JevDrillUnavailable("Supplied retry context is unverified: no recorded failure")
                return admission
            used = len(attempts)
            if budget.exhausted(used, now):
                raise JevDrillUnavailable("Retry budget is exhausted")
            remaining_attempts, remaining_time_ms = budget.remaining(used, now)
            generated = {"failure_class": latest["outcome"],
                         "failure_summary": "host_acceptance_failed:" + latest["outcome"],
                         "prior_execution_run_id": latest["execution_run_id"],
                         "prior_routing_decision_id": latest["routing_decision_id"],
                         "remaining_attempts": remaining_attempts,
                         "remaining_time_ms": remaining_time_ms, "remaining_spend": None}
            if supplied is not None and (
                    any(supplied[field] != generated[field] for field in
                        ("failure_class", "prior_execution_run_id", "prior_routing_decision_id"))
                    or supplied["remaining_attempts"] > remaining_attempts
                    or supplied["remaining_time_ms"] > remaining_time_ms):
                raise JevDrillUnavailable("Supplied retry context is unverified or widens the host budget")
            admission["context"] = generated
            return admission

    def _commit_route(self, admission):
        """Open or tighten the task's entry for a successful prepare; return its generation.

        A prepare admitted against an entry that closed during routing fails; it never opens
        a fresh generation.
        """
        with self._ledger_lock:
            entry = self._ledger.get(admission["key"])
            if admission["generation"] is not None and (
                    entry is None or entry["generation"] != admission["generation"]):
                raise JevDrillUnavailable("Retry record closed during routing")
            if entry is None:
                if len(self._ledger) >= RETRY_LEDGER_LIMIT:
                    raise JevDrillUnavailable("Retry ledger is full")
                self._ledger_generation += 1
                entry = self._ledger[admission["key"]] = {
                    "budget": admission["budget"], "attempts": [], "generation": self._ledger_generation}
            else:
                entry["budget"] = entry["budget"].tighten(admission["budget"])
            return entry["generation"]

    def _ledger_refusal(self, binding, *, commit=False):
        """Refuse a binding whose entry closed or whose budget is spent; optionally spend one.

        The caller holds ``_ledger_lock`` when ``commit`` is true, so the check and the
        attempt append are one atomic step.
        """
        with self._ledger_lock:
            entry = self._ledger.get(binding["ledger_key"])
            if entry is None or entry["generation"] != binding["ledger_generation"]:
                return "Retry record is closed"
            if entry["budget"].exhausted(len(entry["attempts"]), time.monotonic_ns()):
                return "Retry budget is exhausted"
            if commit:
                entry["attempts"].append({"execution_run_id": binding["run_id"],
                                          "routing_decision_id": binding["decision"]["details"]["routing_decision_id"],
                                          "outcome": "launched"})
                self._run_index[binding["run_id"]] = binding["ledger_key"]
        return None

    def _gate(self, binding):
        refusal = self._ledger_refusal(binding)
        if refusal is not None:
            raise JevDrillUnavailable(refusal)

    def record_acceptance_outcome(self, execution_run_id, *, passed, failure_class):
        """IF-0-JEVHOST-5 observer: the host's acceptance verdict for a launched run."""
        if passed:
            if failure_class is not None:
                raise ValueError("A passed verdict carries no failure class")
        elif failure_class not in ACCEPTANCE_FAILURE_CLASSES:
            raise ValueError(f"Unknown acceptance failure class: {failure_class!r}")
        with self._ledger_lock:
            key = self._run_index.get(execution_run_id)
            entry = self._ledger.get(key) if key is not None else None
            if entry is None:
                return
            attempt = next(a for a in entry["attempts"] if a["execution_run_id"] == execution_run_id)
            if attempt["outcome"] != "launched":
                return
            if passed:
                self._close_ledger(key)
            else:
                attempt["outcome"] = failure_class

    def _close_ledger(self, key):
        with self._ledger_lock:
            entry = self._ledger.pop(key, None)
            for attempt in (entry or {}).get("attempts", ()):
                self._run_index.pop(attempt["execution_run_id"], None)

    # --- Run event streams (EC-HOST-2 item 3 hook) -----------------------------------------

    def _run_binding(self, execution_run_id):
        binding = self._runs.get(execution_run_id)
        if binding is None:
            raise KeyError("Unknown or expired launched run")
        return binding

    def run_event_identity(self, execution_run_id):
        """Return the ExecutionEvent identity of a launched run's single report stream."""
        binding = self._run_binding(execution_run_id)
        with self._report_lock:
            return {"task_id": binding["request"]["task_id"],
                    "routing_decision_id": binding["decision"]["details"]["routing_decision_id"],
                    "execution_run_id": binding["run_id"], "source_id": _SOURCE_ID,
                    "next_source_sequence": binding["sequence"]}

    def enqueue_run_event(self, execution_run_id, payload):
        """Enqueue an explicit report on a launched run's stream; return the queue disposition.

        The adapter assigns the envelope, ``event_id``, ``source_id`` and next
        ``source_sequence``. Lifecycle events are host-owned and are refused.
        """
        binding = self._run_binding(execution_run_id)
        if not isinstance(payload, dict) or payload.get("kind") == "lifecycle":
            raise ValueError("Run-bound reports carry a non-lifecycle payload")
        return self._report(binding, payload=deepcopy(payload))

    def run_report_counts(self, execution_run_id):
        """Return the run's enqueue-time queue entries and losses by disposition."""
        binding = self._run_binding(execution_run_id)
        with self._report_lock:
            return deepcopy(binding["counts"])

    def _register_run(self, binding):
        # The caller already holds ``_report_lock``.
        with self._report_lock:
            self._runs[binding["run_id"]] = binding
            while len(self._runs) > RUN_HANDLE_LIMIT:
                self._runs.popitem(last=False)

    def _take_binding(self, bundle):
        """Return the routed binding for ``bundle``, or None for an unrouted bundle.

        Routing provenance is the bundle's content fingerprint, so a copied or rebuilt
        routed bundle is recognized. A copy of a pending bundle takes that binding once; a
        bundle whose bindings were all launched, refused or collected fails closed. A
        bundle identical in every field to a routed bundle is treated as routed.
        """
        fingerprint = _bundle_fingerprint(bundle)
        pending = self._routed.get(fingerprint)
        if pending is None:
            return None
        binding = self._pending.get(id(bundle))
        identity = id(bundle) if binding is not None and binding["fingerprint"] == fingerprint else next(
            (i for i in pending if i in self._pending and self._pending[i]["fingerprint"] == fingerprint), None)
        if identity is None:
            raise JevDrillUnavailable("Routed launch binding was already used or refused")
        pending.remove(identity)
        return self._pending.pop(identity)

    def _report(self, binding, event_type=None, *, payload=None, reason=None):
        with self._report_lock:
            envelope = deepcopy(binding["request"]["envelope"])
            event_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            envelope.update(operation="report", request_id=event_id, idempotency_key=event_id, created_at=now)
            event = {"schema_version": "1", "event_id": event_id,
                     "execution_run_id": binding["run_id"], "task_id": binding["request"]["task_id"],
                     "routing_decision_id": binding["decision"]["details"]["routing_decision_id"],
                     "occurred_at": now, "source_id": _SOURCE_ID, "source_sequence": binding["sequence"],
                     "supersedes_event_id": None, "payload": payload or {"kind": "lifecycle", "event_type": event_type,
                     "applied_plan_id": binding.get("applied_plan_id"), "reason": reason}}
            binding["sequence"] += 1
            disposition = self.queue.enqueue({"envelope": envelope, "event": event})
            counts = binding.setdefault("counts", {"queued": 0, "losses": {}})
            if disposition == "queued":
                counts["queued"] += 1
            else:
                counts["losses"][disposition] = counts["losses"].get(disposition, 0) + 1
        if disposition != "queued":
            self._emit_notice({"kind": "transport_disposition", "status": disposition})
        return disposition

    def launch(self, launch, spec, **kwargs):
        with self.queue.objective_guard():
            return self._launch(launch, spec, **kwargs)

    def _launch(self, launch, spec, **kwargs):
        binding = self._take_binding(spec.prompt_bundle)
        if binding is None:
            return launch(spec, **kwargs)
        # A closed entry or a spent budget is refused before any CLI or executor contact.
        self._gate(binding)
        candidate = binding["candidate"]
        request = binding["request"]
        linked = binding.get("linked_inputs")
        if linked is not None:
            # A verdict takes effect when recorded: one that closes the entry before this
            # locked gate prevents the CLI request; a later one is applied at final admission.
            self._check_discovery(request["envelope"], linked["discovery_ref"], gate=lambda: self._gate(binding))
            current = deepcopy(self.inputs_for(binding["context"]))
            self.transport.validators["DiscoveryRouteInputs"].validate(current)
            if (current["discovery_ref"] != linked["discovery_ref"]
                    or current["route_inputs"].get("catalog") != linked["route_inputs"].get("catalog")
                    or current["route_inputs"]["request"]["versions"] != request["versions"]):
                raise JevDrillUnavailable("Authorized discovery catalog or revisions changed")
        if self.queue.is_deleted(request["envelope"]["project_id"], request["envelope"]["workspace_id"], request["task_id"]):
            raise JevDrillUnavailable("Task is deleted")
        readiness = binding["decision"]["readiness"]
        if (not _fresh(candidate) or not all(_fresh(row) for row in binding["freshness"])
                or not _fresh({"verified_at": readiness["verified_at"], "expires_at": readiness["valid_until"]})
                or not self.verify_candidate(deepcopy(candidate), binding["context"])
                or (binding["limits_required"] and not self.limits_enforced(spec, deepcopy(candidate)))
                or spec.selected_model != candidate["model_id"]
                or spec.effective_effort != candidate["native_effort"]["native_value"]
                or spec.claude_route in ("claude_channel", "claude_agent_view")):
            raise JevDrillUnavailable("Final executor identity or token bounds are not enforceable")
        reporting_started = time.monotonic_ns()
        self._report(binding, "started")
        reporting_ms = (time.monotonic_ns() - reporting_started) / 1_000_000
        # GAPS §3.6: every lock that can block is taken first; then the final readiness
        # check, the attempt commit and run registration sit directly before dispatch.
        with self._report_lock, self._ledger_lock:
            if (not _fresh(candidate) or not all(_fresh(row) for row in binding["freshness"])
                    or not _fresh({"verified_at": readiness["verified_at"], "expires_at": readiness["valid_until"]})):
                refusal = "Final executor readiness expired; launch is not enforceable"
            else:
                refusal = self._ledger_refusal(binding, commit=True)
            if refusal is None:
                self._register_run(binding)
        if refusal is not None:
            self._report(binding, "canceled")
            if binding["guidance"]:
                self._report(binding, "guidance_deactivated", reason="launch_canceled")
            raise JevDrillUnavailable(refusal)
        terminal = "failed"
        result = None
        mismatch = False
        try:
            if spec.executor == "codex":
                kwargs["codex_usage_capture"] = True
                kwargs["codex_input_capture"] = True
            started = time.monotonic_ns()
            try:
                result = launch(spec, **kwargs)
            finally:
                elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
            terminal = "canceled" if result.interrupted else "failed" if result.timed_out or result.stalled or result.failed or not result.available else "completed"
            mismatch = ((result.selected_model is not None and result.selected_model != candidate["model_id"])
                        or (result.effective_effort is not None and result.effective_effort != candidate["native_effort"]["native_value"]))
            binding["applied_plan_id"] = None if mismatch or not result.available else binding["decision"]["execution_plan"]["execution_plan_id"]
            execution_run = {"execution_run_id": binding["run_id"], "task_id": request["task_id"],
                             "selected_plan_id": binding["decision"]["execution_plan"]["execution_plan_id"],
                             "applied_plan_id": binding["applied_plan_id"],
                             "execution_mode": request["execution_mode"], "substitution_reason": "executor_unavailable" if not result.available else "executor_identity_mismatch" if mismatch else None,
                             "prior_execution_run_id": (request["retry_context"] or {}).get("prior_execution_run_id")}
            self.transport.validators["ExecutionRun"].validate(execution_run)
        finally:
            reporting_started = time.monotonic_ns()
            try:
                self._report(binding, terminal)
                measurements = []
                for metric in ("completion_time_ms", "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "quality_score"):
                    timing = metric == "completion_time_ms"
                    subset = metric in ("cached_input_tokens", "reasoning_tokens")
                    measurements.append({"metric_id": metric, "metric_version": "1", "scope": "run",
                        "source": "host" if timing else "evaluator" if metric == "quality_score" else "provider",
                        "method": "monotonic_ns" if timing else "evaluator" if metric == "quality_score" else "provider_reported",
                        "counting_semantics": "subset" if subset else "not_applicable" if timing or metric == "quality_score" else "disjoint",
                        "parent_metric_id": "input_tokens" if metric == "cached_input_tokens" else "output_tokens" if metric == "reasoning_tokens" else None,
                        "measurement_value": {"kind": "known", "unit": "ms", "value": elapsed_ms} if timing
                                             else {"kind": "unknown", "reason": "not_reported"}})
                receipt = result.jevdrill_usage if result is not None else None
                if receipt is not None:
                    try:
                        candidate_report = {"kind": "usage", "measurements": deepcopy(receipt["measurements"])}
                        if set(receipt) != {"kind", "measurements"} or receipt["kind"] != "usage":
                            raise ValueError("Invalid receipt fields")
                        rows = candidate_report["measurements"]
                        if len(rows) != 4 or {m["metric_id"] for m in rows} != {m["metric_id"] for m in measurements[1:5]}:
                            raise ValueError("Invalid receipt metrics")
                        if len({m["method"] for m in rows}) != 1 or any(m["method"] not in _CODEX_USAGE_METHODS for m in rows):
                            raise ValueError("Invalid receipt method")
                        self._validate_measurements(rows)
                        # Validate exact BAML-generated fields before replacing fallbacks.
                        from jsonschema import Draft202012Validator
                        schema = self.transport.validators["ReportRequest"].schema
                        Draft202012Validator({"$ref": "#/$defs/UsagePayload", "$defs": schema["$defs"]}).validate(candidate_report)
                        if not any(m["measurement_value"]["kind"] == "known" and m["measurement_value"]["value"] > 0 for m in rows):
                            raise ValueError("Ambiguous zero receipt")
                        measurements[1:5] = rows
                    except Exception:
                        self._emit_notice({"kind": "transport_disposition", "status": "invalid_usage_receipt"})
                self._report(binding, payload={"kind": "usage", "measurements": measurements})
                # Guidance is confined to this immutable prompt, never installed globally.
                if binding["guidance"]:
                    self._report(binding, "guidance_deactivated", reason=deactivation_reason(
                        result_returned=result is not None,
                        available=result is not None and result.available,
                        identity_mismatch=mismatch,
                        interrupted=result is not None and result.interrupted))
                self.flush()
            except Exception:
                warning = {"kind": "transport_disposition", "status": "delivery_failed"}
                self.delivery_warnings.append(warning)
                self._emit_notice(warning)
            finally:
                reporting_ms += (time.monotonic_ns() - reporting_started) / 1_000_000
        return replace(result, jevdrill_execution_run=execution_run, jevdrill_timings={
            "schema_version": "1", "method": "monotonic_ns", "unit": "ms",
            "routing_ms": binding["routing_ms"], "launcher_ms": elapsed_ms,
            "reporting_ms": reporting_ms, "provider_generation_ms": None})

    def flush(self):
        disconnected, inbox = [], []
        def send(report):
            started = time.monotonic()
            try:
                # Notices are held until the queue's write transaction ends.
                self._notices(report["envelope"], started_at=started, operation="report", deferred=inbox)
                return self._call("report", report, started_at=started, operation="report")
            except (OSError, TimeoutError) as exc:
                # Re-raised into the queue, which commits its backoff for this row.
                disconnected.append(exc)
                raise
        result = self.queue.deliver_one(send)
        for notice in inbox:
            self._emit_notice(notice)
        if result == "retry" and disconnected:
            self._emit_notice(self._disconnect_notice("report"))
        dispositions = self.queue.status()["dispositions"]
        if dispositions:
            self._emit_notice({"kind": "transport_dispositions", "counts": dispositions})
        return result

    def delete_task(self, scope, task_id):
        payload = {"schema_version": "1", "scope": scope, "task_id": task_id}
        self.transport.validators["DeleteRequest"].validate(payload)
        # Commit transport tombstone before contacting JEV. A lost response can
        # safely retry this operation; the tombstone must never be rolled back.
        self.queue.delete_task(scope["project_id"], scope["workspace_id"], task_id)
        self._close_ledger((scope["project_id"], scope["workspace_id"], task_id))
        return self.transport.call("delete", payload)


def build_jevdrill_request(adapter, builder, *, mode, dry_run, **kwargs):
    if adapter is not None:
        kwargs = adapter.prepare(mode=mode, dry_run=dry_run, **kwargs)
    return builder(**kwargs)


def launch_jevdrill(adapter, launch, spec, **kwargs):
    return launch(spec, **kwargs) if adapter is None else adapter.launch(launch, spec, **kwargs)
