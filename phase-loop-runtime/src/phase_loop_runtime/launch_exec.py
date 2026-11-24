"""LaneExec caller-side request election, validation and admission."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import time
from dataclasses import replace
from pathlib import Path

from . import launch_routes as routes
from . import launch_snapshot as snapshots
from . import launch_supervisor as supervisor
from . import run_status, seat_resource_caps
from . import sandbox_placement as placement
from .launch_lifetime import budget_permits
from .launch_process_contract import (
    LaunchResponse,
    PreparedPaths,
    SeedLimits,
    encode_launch_response,
)
from .launch_settings import decode_launch_object
from .placement_process_contract import canonical_bytes


def _refusal(req, code, diagnostic=None):
    return LaunchResponse(
        req.request_id,
        req.reservation.reservation_id,
        None,
        "refused",
        code,
        None,
        None,
        diagnostic,
        None,
        0,
        None,
        None,
        None,
        None,
        None,
        req.caller_context,
    )


def _gate(service, req, settings):
    reservation = req.reservation
    kind = reservation.target.kind
    if req.workload != reservation.workload:
        return "sandbox_launch_refused"
    if req.image_digest != reservation.image_digest or not settings.image_allowed(
        req.workload, kind, req.image_digest
    ):
        return "sandbox_launch_image_refused"
    # Recheck the config even if the caps loader is down. Unreadable caps
    # have their own wire refusal after the lifetime check.
    readable, digest = service.lifecycle.caps_state()
    live_config = service.lifecycle.config(digest if readable else service.config.seat_caps_sha256)
    if (
        set(req.providers) != set(reservation.providers)
        or req.policy_vector != reservation.policy_vector
        or routes.pi_policy_refusal(req.workload, kind, req.policy_vector)
        or hashlib.sha256(service.config.canonical).hexdigest() != reservation.config_sha256
        or live_config.canonical != service.config.canonical
    ):
        return "sandbox_launch_input_mismatch"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", reservation.transport_id):
        return "sandbox_launch_input_mismatch"
    if kind == "openshell":
        code = placement.openshell_launch_refusal(
            service.config,
            workload=reservation.workload,
            target_kind=kind,
            providers=reservation.providers,
            config_sha256=reservation.config_sha256,
            egress_sha256=reservation.egress_sha256,
            route_state=service.route_state,
        )
        if code:
            return code
    return routes.activation_refusal(settings, workload=req.workload, target_kind=kind)


def _validate(service, req, cancelled):
    settings = decode_launch_object(
        json.loads(service.config.canonical).get("launch"), client=service.client
    )
    code = routes.static_route_refusal(
        settings,
        client=service.client,
        workload=req.workload,
        action=req.action,
        result_kind=req.result_kind,
    )
    if code:
        return _refusal(req, code)
    rid = req.reservation.reservation_id
    with service.lifecycle.launch_lock(
        rid, timeout_s=placement.ANSWER_BOUND_S, cancelled=cancelled
    ) as lock:
        if not lock.held:
            return _refusal(req, "sandbox_placement_operation_timeout")
        paths = lock.ensure_prepare(req)
        if isinstance(paths, str):
            return _refusal(req, paths)
        code, active = lock.window(req.reservation_json or req.reservation.to_json())
        if code:
            return _refusal(req, code)
    try:
        code = _gate(service, req, settings)
    except placement.LifecycleError:
        return _refusal(req, "sandbox_launch_input_mismatch")
    if code:
        return _refusal(req, code)
    registry = routes.register_templates(settings)
    try:
        template = routes.select_template(
            registry,
            req.command,
            workload=req.workload,
            target_kind=req.reservation.target.kind,
            policy_vector=req.policy_vector,
            action=req.action,
            result_kind=req.result_kind,
            image_digest=req.image_digest,
        )
    except routes.TemplateRefused:
        return _refusal(req, routes.TEMPLATE_CODE)
    ttl = active.get("ttl_s")
    if ttl is None:
        # Legacy active rows retain the original integral TTL in their two wall timestamps.
        expires = placement._epoch(req.reservation.expires_at)
        if expires is not None:
            ttl = int(expires - math.floor(active["created_at"]))
    maximum = None
    if req.reservation.target.kind == "openshell":
        effect = active["effect"]
        backend = service.lifecycle.backend_for(
            placement.PlacementLifecycle._parsed_root(effect["root"], effect["target"])
        )
        if backend is None:
            return _refusal(req, "sandbox_launch_lifetime_unbounded")
        try:
            maximum = backend.declaration().max_lifetime_s
        except Exception:
            return _refusal(req, "sandbox_launch_lifetime_unbounded")
    if not budget_permits(
        ttl_s=ttl,
        maximum=maximum,
        snapshot_s=settings.snapshot_budget_s,
        timeout_s=req.timeout_seconds,
        return_s=settings.return_budget_s,
        template_timeout=template.record["max_timeout_seconds"],
    ):
        return _refusal(req, "sandbox_launch_lifetime_unbounded")
    try:
        digest = seat_resource_caps.caps_sha256(service.load_caps())
    except Exception:
        return _refusal(req, "sandbox_placement_capability_unmet")
    if digest != service.config.seat_caps_sha256:
        return _refusal(req, "sandbox_launch_input_mismatch")
    if req.reservation.target.kind == "local":
        try:
            if service.readiness_code():
                return _refusal(req, "sandbox_placement_capability_unmet")
        except Exception:
            return _refusal(req, "sandbox_placement_capability_unmet")
    if (req.reservation.target.kind, req.workload) != ("openshell", "pi-runner"):
        from . import sandbox_policy

        baseline = sandbox_policy.placement_policy_baseline(req.policy_vector)
        endpoints = {name: provider.endpoints for name, provider in service.config.providers.items()}
        try:
            _, egress = placement.effective_egress(req.providers, baseline, endpoints)
        except placement.LifecycleError:
            return _refusal(req, "sandbox_launch_input_mismatch")
        if egress != req.reservation.egress_sha256:
            return _refusal(req, "sandbox_launch_admission_refused", "launch_input_unbound")
    return paths, settings, registry, template, ttl


def launch_attempt(
    service, request, *, cancelled, pre_exec=None, withhold=None, origin="process", lane_context=None
):
    lifecycle = service.lifecycle
    body = request.to_json()
    if request.reservation_json:
        body["reservation"] = dict(request.reservation_json)
    digest = hashlib.sha256(canonical_bytes(body)).hexdigest()
    rid = request.reservation.reservation_id
    key = request.request_id
    end = time.monotonic() + placement.ANSWER_BOUND_S
    while True:
        with lifecycle.launch_request_lock(key, timeout_s=max(0, end - time.monotonic())) as held:
            if held:
                record = lifecycle.launch_record(key)
                if record is None:
                    pid = os.getpid()
                    owner = {"pid": pid, "start": run_status.process_start_identity(pid)}
                    if not owner["start"]:
                        return _refusal(request, "sandbox_placement_capability_unmet")
                    generation = secrets.token_hex(16)
                    record = dict(
                        version=1,
                        generation=generation,
                        request_id=key,
                        reservation_id=rid,
                        body_sha256=digest,
                        phase="caller",
                        owner=owner,
                        caller_context=dict(request.caller_context),
                        run_id=None,
                        terminal=None,
                    )
                    lifecycle.write_launch_record(key, record)
                    break
                if record.get("body_sha256") != digest:
                    return _refusal(request, "sandbox_launch_refused")
                terminal = lifecycle.launch_terminal(key)
                if terminal is not None:
                    return terminal
                if record.get("phase") == "caller" and lifecycle.launch_owner(record) == "gone":
                    if not record.get("handoff") and not service._claim_held(record, key):
                        dead = _refusal(request, "sandbox_launch_refused")
                        record.update(phase="terminal", terminal=encode_launch_response(dead).decode())
                        lifecycle.write_launch_record(key, record)
                        return dead
        if cancelled.is_set() or time.monotonic() >= end:
            observed = lifecycle.launch_record(key) or dict(reservation_id=rid)
            return service._uncertain(observed, key, service._claim_held(observed, key))
        cancelled.wait(min(0.05, max(0, end - time.monotonic())))
    result = _validate(service, request, cancelled)
    if not isinstance(result, LaunchResponse):
        result = _capture_attempt(
            service, request, generation, owner, result, origin, lane_context, cancelled, pre_exec, withhold
        )
        observed = lifecycle.launch_terminal(key)
        if observed is not None:
            return observed
    if result.state == "uncertain":
        return result
    with lifecycle.launch_request_lock(key, timeout_s=placement.ANSWER_BOUND_S) as held:
        latest = lifecycle.launch_record(key) if held else None
        if (
            latest is None
            or latest.get("generation") != generation
            or latest.get("owner") != owner
            or latest.get("phase") != "caller"
        ):
            return service._uncertain(record, key, service._claim_held(record, key))
        latest.update(phase="terminal", terminal=encode_launch_response(result).decode("utf-8"))
        lifecycle.write_launch_record(key, latest)
    return result


def isolated_admission(envelope, controller, *, cancelled, bound_s):
    """Drain both sides under one deadline. Byte 4097 is an immediate protocol failure."""
    import selectors
    import signal
    import subprocess

    from .launch_admission import BLOB_CAP, FALLBACK
    from .placement_process_contract import load_strict_object, validate_message
    from .seat_uid import trusted_module_argv

    if any(len(part) > BLOB_CAP for part in (envelope, controller)):
        return FALLBACK
    frame = memoryview(b"".join(len(part).to_bytes(8, "big") + part for part in (envelope, controller)))
    deadline = time.monotonic() + bound_s
    proc = None
    leader_collected = False
    try:
        proc = subprocess.Popen(
            trusted_module_argv("phase_loop_runtime.launch_admission"),
            cwd="/",
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        out = bytearray()
        with selectors.DefaultSelector() as selector:
            for stream, event in ((proc.stdin, selectors.EVENT_WRITE), (proc.stdout, selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event)
            while selector.get_map():
                left = deadline - time.monotonic()
                if left <= 0 or cancelled.is_set():
                    return FALLBACK
                for key, _ in selector.select(min(0.05, left)):
                    if key.fileobj is proc.stdin:
                        count = os.write(key.fd, frame[:65536])
                        frame = frame[count:]
                        if not frame:
                            selector.unregister(proc.stdin)
                            proc.stdin.close()
                    else:
                        chunk = os.read(key.fd, 4097 - len(out))
                        if not chunk:
                            selector.unregister(proc.stdout)
                        out.extend(chunk)
                        if len(out) > 4096:
                            return FALLBACK
        while proc.poll() is None:
            if cancelled.wait(0.01) or time.monotonic() >= deadline:
                return FALLBACK
        leader_collected = True
        if proc.returncode != 0 or not out.endswith(b"\n") or out.count(b"\n") != 1:
            return FALLBACK
        value = load_strict_object(bytes(out))
        if set(value) == {"admitted"} and value["admitted"] is True:
            return None
        if (
            set(value) == {"admitted", "diagnostic"}
            and value["admitted"] is False
            and validate_message("AdmissionDiagnostic", value["diagnostic"])
        ):
            return value["diagnostic"]
        return FALLBACK
    except (OSError, ValueError):
        return FALLBACK
    finally:
        if proc is not None:
            if not leader_collected:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.stdin.close()
            proc.stdout.close()
            proc.wait()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _cgroup_entry():
    return Path(seat_resource_caps.__file__).with_name("seat_resource_caps_enter.py")


class _LaneAuthorityUnavailable(ValueError):
    """SL-4 has not supplied independent lane assignment material."""


def _bound_material(req, paths, settings, template, tree, seed, stage, slots, argv, origin):
    """Project the captured inputs and passive managed declarations into the two v2 documents."""
    from . import supervised_launch_binding as binding
    from .convergence.broker.live import repository_snapshot
    from .supervised_envelope_v2 import canonicalize_v2, parse_v2
    from .supervised_launch import Refused, trusted_bytes

    if origin == "lane":
        raise _LaneAuthorityUnavailable
    locator = binding.read_binding_locator(binding.MANAGED_BINDING)
    if isinstance(locator, Refused):
        raise ValueError("unavailable managed binding")
    declarations = parse_v2(locator.binding_bytes).value
    spec = parse_v2(trusted_bytes(Path(declarations["spec"]))).value
    launch = spec["launch"]
    target = Path(req.snapshot.root)
    # The private managed declaration must identify the protected tree. The
    # request alone cannot grant its target slot write authority.
    if launch["target"] != str(target):
        raise ValueError("protected target not independently bound")
    declared = launch.get("declared_roots", {})
    declared = dict(declared)
    stage_slots = {}
    baseline_name = launch["references"][0]["source"]["root"]
    for name, value in tuple(declared.items()):
        if isinstance(value, str):
            continue
        if set(value) != {"slot"} or spec["slots"].get(value["slot"]) != "root":
            raise ValueError("unbound private root")
        if name == baseline_name:
            private = stage
        elif name == "laneexec_seed" and seed.manifest is not None:
            private = stage / "manifests"
        else:
            raise ValueError("unbound private root")
        stage_slots[value["slot"]] = declared[name] = str(private)
    roots = launch["reference_roots"]
    if roots == {"slot": "reference_roots"}:
        roots = tuple(declared.values())
    if not isinstance(roots, tuple) or any(not isinstance(p, str) for p in roots):
        raise ValueError("unbound reference root")
    excluded = dict(workspace=tree.tree, target=target, reference_roots=tuple(Path(p) for p in roots))
    ctx = binding.load_v2_context(Path(declarations["context"]), **excluded)
    if isinstance(ctx, Refused):
        raise ValueError("unavailable managed context")
    body = req.to_json()
    body.pop("caller_context")
    if req.reservation_json:
        body["reservation"] = dict(req.reservation_json)
    assignment = _hash(canonicalize_v2(body))
    repo = repository_snapshot(target)
    identity = _hash(
        canonicalize_v2(
            dict(
                schema="CanonicalRepositoryIdentity.v1",
                git_common_dir=str(repo.common_dir),
                git_object_format=repo.object_format,
            )
        )
    )
    units = dict(
        target_unit_ids=["launch:" + req.request_id],
        readonly_neighbor_unit_ids=[],
        snapshot_ref=tree.inventory_sha256,
        crosswalk_ref=identity,
    )
    locators = tree.top_level_entries
    definitions = ()
    values = dict(workspace=str(tree.tree), target=str(target), reference_roots=roots, **stage_slots)
    for name, kind in spec["slots"].items():
        if name in values:
            continue
        if kind == "argv" and name in slots and slots[name] in argv:
            values[name] = slots[name]
        elif kind == "root" and name in declared and declared[name] in roots:
            values[name] = declared[name]
        else:
            raise ValueError("unbound controller slot")
    if set(values) != set(spec["slots"]):
        raise ValueError("incomplete controller slots")

    def source(raw, wire):
        return dict(source=wire, sha256=_hash(raw), byte_length=len(raw))

    baseline = launch["references"][0]
    if baseline["role"] != "baseline":
        raise ValueError("unbound baseline")
    base_source = baseline["source"]
    baseline_path = Path(declared[base_source["root"]]) / base_source["path"]
    if (
        base_source["namespace"] != "declared_root"
        or baseline_path != stage / "baseline"
        or trusted_bytes(baseline_path) != tree.descriptor_bytes
    ):
        raise ValueError("baseline not bound to the capture")
    if seed.manifest and declared.get("laneexec_seed") != str(stage / "manifests"):
        raise ValueError("seed reference not bound to the capture")
    refs = [dict(role="baseline", **source(tree.descriptor_bytes, base_source))]
    expected_refs = template.record["references"]
    managed_refs = launch["references"][1 : 1 + len(expected_refs)]
    if len(expected_refs) != len(managed_refs):
        raise ValueError("unbound template reference")
    for name, row in zip(expected_refs, managed_refs, strict=True):
        wire = row["source"]
        if wire["namespace"] != "declared_root" or wire["path"] != name:
            raise ValueError("unbound template reference")
        data = trusted_bytes(Path(declared[wire["root"]]) / name)
        refs.append(dict(role=row["role"], **source(data, wire)))
    if seed.manifest:
        refs.append(seed.reference())
    if req.instructions.source == "inline":
        data = base64.b64decode(req.instructions.base64, validate=True)
        data.decode("utf-8")
        instructions = source(data, None)
    elif req.instructions.source == "snapshot":
        path = tree.tree / req.instructions.path
        # No dereference of links in the capture. An inventory leaf must be a file.
        with supervisor.trusted_directory(path.parent) as directory:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                data = stream.read((1 << 20) + 1)
        if len(data) > 1 << 20:
            raise ValueError("instruction cap")
        instructions = source(data, dict(namespace="workspace", path=req.instructions.path))
    else:
        instructions = source(b"", None)

    tier = "provider_readonly_patch_return_audit"
    original = template.record["executable_chain"]
    projected = []
    # The managed route prefix must be independently identifiable on this host.
    chain = launch["executable_chain"]
    if len(chain) != len(original) + 1 or req.reservation.target.kind != "local":
        raise ValueError("unbound route executable")
    for i, entry in enumerate(chain):
        path = entry["path"]
        if i == 0 and Path(path) != _cgroup_entry():
            raise ValueError("cgroup entry mismatch")
        with supervisor.trusted_directory(Path(path).parent) as directory:
            import stat

            fd = os.open(Path(path).name, os.O_NOFOLLOW | os.O_RDONLY | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_mode & 0o022
                    or info.st_uid not in (0, os.geteuid())
                ):
                    raise ValueError("untrusted executable")
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        role = "executable" if i == len(chain) - 1 else "wrapper"
        wire = dict(role=role, locator_kind="declared", locator=f"exec-{i}")
        if entry["wire"] != wire:
            raise ValueError("unbound executable")
        if i:
            item = original[i - 1]
            if (
                item["locator_kind"] != "declared"
                or item["locator"] != path
                or item["sha256"] != digest
                or item["role"] != ("worker" if role == "executable" else role)
            ):
                raise ValueError("template executable changed")
        projected.append(dict(**wire, sha256=digest))
    qualification = [
        r
        for r in ctx.qualified_routes
        if r["tier"] == tier
        and r["action"] == req.action
        and r["transport_id"] == req.reservation.transport_id
        and r["template_sha256"] == template.template_sha256
        and canonicalize_v2(r["executable_chain"])
        == canonicalize_v2([{k: v for k, v in row.items() if k != "role"} for row in projected])
    ]
    policy = dict(
        config_sha256=req.reservation.config_sha256,
        template_sha256=template.template_sha256,
        qualification_sha256=qualification[0]["qualification_sha256"] if len(qualification) == 1 else None,
    )
    environment = dict(
        canonical_form="rfc8785_redacted_environment",
        map_sha256=_hash(canonicalize_v2(dict(non_secret={}, secret_names=[]))),
        policy=dict(
            id=launch["environment_policy_id"],
            sha256=_hash(trusted_bytes(Path(launch["environment_policy_path"]))),
        ),
    )
    payload = dict(
        action=req.action,
        transport_id=req.reservation.transport_id,
        stdin="devnull" if req.instructions.source == "none" else "input",
        instructions=instructions,
        references=refs,
        argv=dict(
            canonical_form="rfc8785_array_of_strings",
            sha256=_hash(canonicalize_v2(argv)),
            element_count=len(argv),
        ),
        executable_chain=projected,
        workspace_state=dict(
            base_commit=tree.envelope_base_commit,
            content_form="rfc8785_tree_manifest",
            content_sha256=tree.content_sha256,
            cwd=dict(namespace="workspace", path=tree.cwd),
            target_map=[dict(workspace_locator=p, protected_locator=p) for p in locators]
            if req.result_kind == "patch"
            else [],
        ),
        environment=environment,
        trusted_policy=policy,
        grants=dict(
            egress_policy_sha256=dict(
                canonical_form="rfc8785", sha256=req.reservation.egress_sha256.removeprefix("sha256:")
            )
        ),
        stop=dict(timeout_seconds=req.timeout_seconds, deadline_action="terminate_process_group"),
    )
    env = dict(
        schema="admitted_launch_envelope.v2",
        assignment_digest=assignment,
        units=units,
        workspace=dict(kind="separate_copy", repo_relative_locators=locators),
        enforcement=dict(tier=tier, required_constraints=[]),
        launch=payload,
        obligations=dict(definition_digests=definitions),
        executable_dependencies=dict(declared=False, admitted_dependency_digest=None),
        caller_context=dict(req.caller_context),
        redaction_posture="digests_and_repo_relative_locators_only",
    )
    env["envelope_digest"] = _hash(canonicalize_v2(env))
    envelope = canonicalize_v2(env)
    authority = dict(
        expected_assignment_digest=assignment,
        expected_snapshot_ref=units["snapshot_ref"],
        expected_crosswalk_ref=units["crosswalk_ref"],
        qualified_routes=ctx.qualified_routes,
        policy_epoch=ctx.policy_epoch,
        revoked_record_ids=ctx.revoked_record_ids,
        timeout_max_seconds=min(ctx.timeout_max_seconds, template.record["max_timeout_seconds"]),
        caller_context_suitability=ctx.caller_context_suitability,
    )
    controller = dict(
        h=_hash(envelope),
        context=authority,
        slots=values,
        attempt=dict(assignment_digest=assignment, run_id=paths.run_id, attempt_id=paths.run_id),
    )
    return envelope, canonicalize_v2(controller)


def _binds_tree(argv, tree, destination):
    # A later mount can obscure the destination even if the expected bind exists.
    # Options after the command delimiter belong to the child program.
    options = argv[: argv.index("--")] if "--" in argv else argv
    target = Path(destination)
    found = False
    two_arguments = {
        "--bind",
        "--ro-bind",
        "--dev-bind",
        "--bind-try",
        "--ro-bind-try",
        "--dev-bind-try",
        "--symlink",
        "--file",
        "--bind-data",
        "--ro-bind-data",
    }
    one_argument = {"--proc", "--dev", "--tmpfs", "--mqueue"}
    for i, word in enumerate(options):
        if word in two_arguments and i + 2 < len(options):
            dest = options[i + 2]
        elif word in one_argument and i + 1 < len(options):
            dest = options[i + 1]
        else:
            continue
        if found and (Path(dest).is_relative_to(target) or target.is_relative_to(Path(dest))):
            return False
        if dest == destination and word in ("--bind", "--ro-bind") and options[i + 1] == str(tree):
            found = True
    return found


def _capture_attempt(
    service, req, generation, owner, validated, origin, lane, cancelled, pre_exec, withhold
):
    from .supervised_envelope_v2 import parse_v2

    life = service.lifecycle
    paths, settings, registry, template, ttl = validated
    ids = req.reservation.reservation_id, req.request_id, generation
    stage = life.launch_root / "stages" / generation
    run = life.launch_run_dir(paths.run_id)
    kind = req.reservation.target.kind
    fields = dict(kind="stage", run_id=paths.run_id, owner=owner, basename=generation)
    refused = _refusal(req, "sandbox_launch_refused")
    if not life.record_allocation(
        *ids, **fields, file_id=None, deadline=time.monotonic() + placement.ANSWER_BOUND_S
    ):
        return refused
    try:
        with supervisor.trusted_directory(stage.parent) as parent:
            os.mkdir(generation, 0o700, dir_fd=parent)
            info = os.stat(generation, dir_fd=parent, follow_symlinks=False)
            os.fsync(parent)
        if not life.record_allocation(
            *ids,
            **fields,
            file_id=(info.st_dev, info.st_ino),
            deadline=time.monotonic() + placement.ANSWER_BOUND_S,
        ):
            return refused
        for directory in ("home", "out"):
            (stage / directory).mkdir(mode=0o700)
        policy = snapshots.SnapshotPolicy(
            req.workload,
            req.result_kind,
            limits=snapshots.SnapshotLimits(**settings.effective_snapshot_limits(req.workload, kind)),
            budget_s=settings.snapshot_budget_s,
        )
        with snapshots.snapshot_budget(settings.snapshot_budget_s):
            tree = snapshots.build_snapshot(
                req.snapshot, policy=policy, scratch=stage / "snapshot", cancelled=cancelled.is_set
            )
            stored = life.launch_prepare_record(ids[0])
            if not stored or PreparedPaths.from_json(stored) != paths:
                return _refusal(req, "sandbox_launch_input_mismatch")
            guest = "/work/" + paths.run_id
            local = kind == "local"
            dest = req.snapshot.root if local else guest + "/fs" + req.snapshot.root
            scratch = str(run / "scratch") if local else guest + "/scratch"
            if paths.tree_path != dest or paths.scratch_path != scratch:
                return _refusal(req, "sandbox_launch_input_mismatch")
            slots = dict(
                tree=str(tree.tree) if local else dest,
                tree_dest=req.snapshot.root,
                home=str(stage / "home") if local else guest + "/home",
                out=str(stage / "out") if local else guest + "/out",
                scratch=scratch,
                run_id=paths.run_id,
            )
            if req.reservation.bridge and template.record["link"]:
                slots.update(
                    relay_port=str(template.record["link"]["guest_port"]),
                    relay_endpoint=routes.relay_endpoint_argument(template),
                )
            if not local:
                slots["manifest"] = guest + "/inputs/landlock-policy.bin"
            # Only verified restriction-manifest bytes can supply manifest_digest.
            # Production OpenShell registration is closed pending an attested image.
            try:
                argv = routes.expand_argv(template, slots)
            except ValueError:
                return _refusal(req, "sandbox_launch_template_refused")
            witness = None
            if local:
                # Validate the actual adjacent mount operands in the expanded command.
                if not _binds_tree(argv, tree.tree, paths.tree_path):
                    return _refusal(req, "sandbox_launch_input_mismatch")
                try:
                    witness = supervisor.local_devices(
                        (
                            tree.tree,
                            stage / "home",
                            stage / "out",
                            run / "scratch" if os.path.lexists(run / "scratch") else run,
                        )
                    )
                except (ValueError, RuntimeError, OSError):
                    return _refusal(req, "sandbox_placement_capability_unmet")
            seed = snapshots.build_seed(
                req.seed,
                request_id=req.request_id,
                seed_root=settings.seed_root,
                limits=SeedLimits(**settings.effective_seed_limits(req.workload, kind)),
                staging=stage / "seed",
                cancelled=cancelled.is_set,
            )
            seed.check_image_links(template.record["image_links"])
        supervisor.write_blob(stage, "baseline", tree.descriptor_bytes)
        if seed.manifest is not None:
            refs = stage / "manifests"
            refs.mkdir(mode=0o700)
            supervisor.write_blob(refs, req.request_id + ".seed.json", seed.manifest)
        try:
            envelope, controller = _bound_material(
                req, paths, settings, template, tree, seed, stage, slots, argv, origin
            )
        except _LaneAuthorityUnavailable:
            isolated_admission(b"", b"", cancelled=cancelled, bound_s=service.admission_bound_s)
            return _refusal(req, "sandbox_launch_admission_refused", "launch_input_unbound")
        except Exception:
            # No positive receipt can authorize a missing independent declaration.
            # Still enter the isolated helper once at the admission stage.
            isolated_admission(b"", b"", cancelled=cancelled, bound_s=service.admission_bound_s)
            return _refusal(req, "sandbox_launch_admission_refused", "codec_unavailable")
        diagnostic = isolated_admission(
            envelope, controller, cancelled=cancelled, bound_s=service.admission_bound_s
        )
        if diagnostic:
            return _refusal(req, "sandbox_launch_admission_refused", diagnostic)
        # The isolated helper decoded and admitted these exact immutable bytes.
        decoded = parse_v2(envelope).value if origin == "lane" else None
        if origin == "lane" and (
            lane is None
            or lane.assignment_digest != decoded["assignment_digest"]
            or lane.units.target_unit_ids != decoded["units"]["target_unit_ids"]
            or lane.definition_digests != decoded["obligations"]["definition_digests"]
        ):
            return _refusal(req, "sandbox_launch_admission_refused", "launch_input_unbound")
        routes.recheck_template(template, registry, settings)
        tree.recheck()
        seed.recheck(cancelled=cancelled.is_set)
        if cancelled.is_set():
            return refused
        if pre_exec:
            try:
                if pre_exec() is not None:
                    return _refusal(req, "sandbox_launch_pre_exec_refused")
            except Exception:
                return _refusal(req, "sandbox_launch_pre_exec_refused")
        return supervisor.handoff_attempt(
            service,
            req,
            generation,
            stage,
            paths,
            ttl,
            argv,
            tree,
            template,
            seed,
            envelope,
            controller,
            settings,
            cancelled,
            withhold,
            witness,
        )
    except snapshots.SnapshotRefused as error:
        return replace(_refusal(req, error.code), snapshot_reason=error.reason)
    except snapshots.SeedRefused as error:
        return replace(_refusal(req, error.code), seed_reason=error.reason)
    except routes.TemplateRefused:
        return _refusal(req, routes.TEMPLATE_CODE)
    except (snapshots.ConstructionCancelled, OSError, ValueError):
        return refused
    finally:
        # Only the current owner can collect. After transfer the supervisor keeps
        # the generation's immutable capture until it records a terminal disposition.
        current = life.launch_record(req.request_id)
        if current and current.get("phase") == "caller" and not current.get("handoff"):
            life.collect_allocation(
                *ids, kind="stage", deadline=time.monotonic() + placement.ANSWER_BOUND_S
            )
