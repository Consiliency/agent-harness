"""SL-8 launch order at the service boundary."""

import json
import threading

import pytest

from phase_loop_runtime import launch_process_contract as wire
from test_launch_prepare import DIGEST, Env, prepare
from test_launch_process_contract import implementation_request, local_pi_request


@pytest.mark.parametrize(
    ("client", "allow_image", "expected", "host_calls"),
    [
        ("agent-harness", False, "sandbox_launch_image_refused", 0),
        ("agent-harness", True, "sandbox_launch_route_disabled", 1),
        ("agent-toolkit", True, "sandbox_launch_local_route_interim", 0),
    ],
)
def test_image_binding_precedes_default_activation(tmp_path, client, allow_image, expected, host_calls):
    env = Env(tmp_path)
    local = client == "agent-toolkit"
    if allow_image:
        filename = client + ".json"
        config = json.loads((env.config / filename).read_bytes())
        config["launch"] = {
            "images": [
                {
                    "image_digest": DIGEST,
                    "workload": "pi-runner" if local else "implementation",
                    "target_kind": "local" if local else "openshell",
                }
            ]
        }
        env.write(filename, config)
    reservation = env.reserve(client)
    calls = []

    def host_gate():
        calls.append(True)
        return "disabled"

    service = env.service(client, route_state=host_gate)
    if local:
        prepared, _, _ = prepare(service, reservation, snapshot_root="/srv/repo")
        body = local_pi_request(paths=prepared.paths.to_json())
    else:
        body = implementation_request()
    body.update(reservation=reservation, image_digest=DIGEST, policy_vector=reservation["policy_vector"])
    request = wire.decode_launch_request("launch", json.dumps(body).encode())
    response = service.launch(request, cancelled=threading.Event())
    assert response.state == "refused" and response.code == expected
    assert response.worker_invocations == 0 and response.envelope_digest is None
    assert service.lifecycle.launch_claim_record(reservation["reservation_id"]) is None
    assert len(calls) == host_calls
    assert wire.decode_launch_response("launch", wire.encode_launch_response(response)) == response


def local_case(root, *, state=None, ttl=600, settings=None, **service_args):
    """A real local PLACECLI reservation, captured configuration and registered host template."""
    import hashlib
    import os
    import rfc8785
    from test_launch_snapshot import make_repo

    root = root.resolve()
    env = Env(root)
    if state is not None:
        env.state = state
    repo = make_repo(root / "source", {"src/file.txt": "fixture\n"})
    worker = root / "fixture-worker"
    worker.write_bytes(b"fixture executable identity")
    os.chmod(worker, 0o700)
    template = dict(
        template_id="implementation.local.v1",
        workload="implementation",
        target_kind="local",
        policy_vectors=["minimal-with-app"],
        action="execution",
        result_kinds=["patch"],
        image_digest=DIGEST,
        argv=[str(worker), "--bind", {"slot": "tree"}, {"slot": "tree_dest"}],
        executable_chain=[
            dict(
                role="worker",
                locator_kind="declared",
                locator=str(worker),
                sha256=hashlib.sha256(worker.read_bytes()).hexdigest(),
            )
        ],
        ro_trees=[],
        image_links=[],
        link=None,
        environment_policy="constructed",
        references=[],
        max_timeout_seconds=600,
        result_schema_id=None,
    )
    raw = rfc8785.dumps(template)
    config = json.loads((env.config / "agent-harness.json").read_bytes())
    config["seat_route"]["implementation"] = "local"
    config["launch"] = dict(
        lane_placement="enabled",
        templates=[raw.decode()],
        images=[dict(image_digest=DIGEST, workload="implementation", target_kind="local")],
    )
    config["launch"].update(settings or {})
    env.write("agent-harness.json", config)
    reservation = env.reserve("agent-harness", ttl_s=ttl)
    assert reservation["target"]["kind"] == "local"
    body = implementation_request(
        reservation=reservation,
        image_digest=DIGEST,
        command=dict(template_id=template["template_id"], template_sha256=hashlib.sha256(raw).hexdigest()),
        snapshot=dict(root=str(repo), mode="git", masks=[], mask_dirs=[], cwd="."),
        timeout_seconds=30,
        caller_context={},
    )
    req = wire.decode_launch_request("launch", json.dumps(body).encode())
    return env, env.service("agent-harness", **service_args), req


def test_ttl_floor_precedes_readiness_and_snapshot(tmp_path):
    def readiness():
        pytest.fail("readiness ran before TTL check")

    _, service, req = local_case(tmp_path, ttl=44, readiness_code=readiness)
    response = service.launch(req, cancelled=threading.Event())
    assert response.code == "sandbox_launch_lifetime_unbounded"
    assert not list((service.lifecycle.launch_root / "stages").iterdir())
    assert service.lifecycle.launch_claim_record(req.reservation.reservation_id) is None


def test_replay_preserves_terminal_under_conflicting_body(tmp_path):
    from dataclasses import replace

    _, service, req = local_case(tmp_path, readiness_code=lambda: "unavailable")
    first = service.launch(req, cancelled=threading.Event())
    assert first.code == "sandbox_placement_capability_unmet"
    saved = service.lifecycle.launch_record(req.request_id)
    other = replace(req, timeout_seconds=31)
    assert service.launch(other, cancelled=threading.Event()).code == "sandbox_launch_refused"
    assert service.launch(req, cancelled=threading.Event()) == first
    assert service.lifecycle.launch_record(req.request_id) == saved


def test_local_incompatible_admission_leaves_reusable_prepare(tmp_path, monkeypatch):
    from phase_loop_runtime import launch_exec

    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path.resolve()))
    _, service, req = local_case(tmp_path)
    calls = []
    real = launch_exec.isolated_admission

    def observed(*args, **kwargs):
        calls.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(launch_exec, "isolated_admission", observed)
    out = service.launch(req, cancelled=threading.Event())
    assert (
        out.code == "sandbox_launch_admission_refused" and out.admission_diagnostic == "codec_unavailable"
    )
    assert calls == [True] and out.worker_invocations == 0
    assert service.lifecycle.launch_prepare_record(req.reservation.reservation_id)
    assert not service.lifecycle.launch_claim_record(req.reservation.reservation_id)
    assert not list((service.lifecycle.launch_root / "stages").iterdir())


@pytest.mark.parametrize("field", ["assignment", "units", "definitions", "absent", "match"])
def test_lane_authority_checked_after_independent_decode(tmp_path, monkeypatch, field):
    from phase_loop_runtime import launch_exec, supervised_capture_v2
    from phase_loop_runtime.launch_service import LaneContext, LaneUnits
    from pathlib import Path
    from test_launch_admission import admitted_fixture

    admitted_fixture(monkeypatch, tmp_path)
    v = json.loads(
        (
            Path(supervised_capture_v2.__file__).parent
            / "schemas/supervised-worker-v2/conformance/envelope.v2.vectors.json"
        ).read_bytes()
    )["cases"][0]["input"]["envelope"]
    units = v["units"]
    ctx = LaneContext(
        "0" * 64 if field == "assignment" else v["assignment_digest"],
        LaneUnits(
            ("other",) if field == "units" else tuple(units["target_unit_ids"]),
            tuple(units["readonly_neighbor_unit_ids"]),
            units["snapshot_ref"],
            units["crosswalk_ref"],
        ),
        ("src",),
        ("1" * 64,) if field == "definitions" else tuple(v["obligations"]["definition_digests"]),
    )
    _, svc, req = local_case(tmp_path)
    calls = []

    def admitted(*args, **kwargs):
        calls.append("admission")

    def pre_exec():
        calls.append("pre_exec")
        return "operator refusal"

    monkeypatch.setattr(launch_exec, "isolated_admission", admitted)
    out = svc.launch_lane(
        req, lane_context=None if field == "absent" else ctx, cancelled=threading.Event(), pre_exec=pre_exec
    )
    assert calls == (["admission", "pre_exec"] if field == "match" else ["admission"])
    assert out.code == (
        "sandbox_launch_pre_exec_refused" if field == "match" else "sandbox_launch_admission_refused"
    )
    assert out.worker_invocations == 0 and not svc.lifecycle.launch_claim_record(
        req.reservation.reservation_id
    )


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("image", "sandbox_launch_image_refused"),
        ("policy", "sandbox_launch_input_mismatch"),
        ("providers", "sandbox_launch_input_mismatch"),
        ("config", "sandbox_launch_input_mismatch"),
        ("template", "sandbox_launch_template_refused"),
        ("writer", "sandbox_launch_writer_route_refused"),
        ("paths", "sandbox_launch_input_mismatch"),
        ("echo", "sandbox_launch_reservation_mismatch"),
        ("expired", "sandbox_launch_reservation_unknown"),
    ],
)
def test_closed_checks_precede_capture(tmp_path, monkeypatch, fault, expected):
    from dataclasses import replace
    from phase_loop_runtime import launch_snapshot

    env, svc, req = local_case(tmp_path)
    if fault == "image":
        req = replace(req, image_digest="sha256:" + "a" * 64)
    elif fault == "policy":
        req = replace(req, policy_vector="minimal-without-app")
    elif fault == "providers":
        req = replace(req, providers=("other",))
    elif fault == "template":
        req = replace(req, command=replace(req.command, template_sha256="1" * 64))
    elif fault == "writer":
        req = replace(req, result_kind="none")
    elif fault == "config":
        filename = "agent-harness.json"
        config = json.loads((env.config / filename).read_bytes())
        config["launch"]["snapshot_budget_s"] = 51
        env.write(filename, config)
    elif fault == "paths":
        saved, _, _ = prepare(svc, req.reservation.to_json(), snapshot_root=req.snapshot.root)
        req = replace(req, paths=replace(saved.paths, tree_path=req.snapshot.root + "/wrong"))
    elif fault == "echo":
        req = replace(req, reservation_json=dict(req.reservation_json, policy_vector="minimal-without-app"))
    elif fault == "expired":
        env.clock.now += 601

    monkeypatch.setattr(launch_snapshot, "build_snapshot", lambda *a, **kw: pytest.fail("capture began"))
    result = svc.launch(req, cancelled=threading.Event())
    assert result.code == expected and result.worker_invocations == 0
    assert not svc.lifecycle.launch_claim_record(req.reservation.reservation_id)


@pytest.mark.parametrize("target", ["local", "openshell"])
def test_unreadable_seat_caps_refuse_before_capture(tmp_path, target):
    if target == "local":
        env, svc, req = local_case(tmp_path)
    else:
        env = Env(tmp_path)
        reservation = env.reserve("agent-harness")
        req = wire.decode_launch_request(
            "launch", json.dumps(implementation_request(reservation=reservation)).encode()
        )
        svc = env.service("agent-harness")
    env.caps_error = True
    out = svc.launch(req, cancelled=threading.Event())
    assert out.code == "sandbox_placement_capability_unmet" and out.worker_invocations == 0
    assert not svc.lifecycle.launch_claim_record(req.reservation.reservation_id)


@pytest.mark.parametrize("fault", ["changed_template", "changed_tree", "expiry", "missing_owner"])
def test_recheck_and_provisioning_preserve_prepare(tmp_path, monkeypatch, fault):
    import time
    from phase_loop_runtime import launch_exec, launch_supervisor as sup
    from test_launch_admission import admitted_fixture

    admitted_fixture(monkeypatch, tmp_path)

    def runner(h):
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                svc.load_caps,
                svc.readiness_code,
                time.monotonic,
                containment_ready=lambda: True,
            ),
        )

    env, svc, req = local_case(tmp_path, supervisor_runner=runner)

    def admit(*a, **kw):
        if fault == "changed_template":
            (tmp_path / "fixture-worker").write_bytes(b"replacement")
        if fault == "changed_tree":
            (tree_file,) = (svc.lifecycle.launch_root / "stages").glob("*/snapshot/tree/src/file.txt")
            tree_file.write_bytes(b"changed")

    def pre_exec():
        if fault == "missing_owner":
            monkeypatch.setattr(sup, "_owner", lambda: None)
        if fault == "expiry":
            env.clock.now += 601

    monkeypatch.setattr(launch_exec, "isolated_admission", admit)
    out = svc.launch(req, cancelled=threading.Event(), pre_exec=pre_exec)
    assert (
        out.code
        == {
            "changed_template": "sandbox_launch_template_refused",
            "changed_tree": "sandbox_launch_snapshot_refused",
            "expiry": "sandbox_launch_reservation_unknown",
            "missing_owner": "sandbox_placement_capability_unmet",
        }[fault]
    )
    assert out.worker_invocations == 0
    assert not svc.lifecycle.launch_claim_record(req.reservation.reservation_id)


def test_concurrent_request_ids_take_one_claim(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    import time
    from phase_loop_runtime import launch_exec, launch_supervisor as sup
    from test_launch_admission import admitted_fixture

    admitted_fixture(monkeypatch, tmp_path)
    ready = threading.Barrier(2)

    def admission(*a, **kw):
        ready.wait(5)

    monkeypatch.setattr(launch_exec, "isolated_admission", admission)
    starts = []
    contender_finished = threading.Event()

    def spawn(*a, **kw):
        starts.append(1)
        assert contender_finished.wait(5)
        raise OSError("unconfirmed spawn")

    def runner(h):
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                svc.load_caps,
                svc.readiness_code,
                time.monotonic,
                containment_ready=lambda: True,
            ),
        )

    env, svc, req = local_case(tmp_path, capped_popen=spawn, supervisor_runner=runner)

    def launch(key):
        res = svc.launch(replace(req, request_id=key), cancelled=threading.Event())
        if res.state == "refused":
            contender_finished.set()
        return res

    with ThreadPoolExecutor(max_workers=2) as concurrent:
        calls = [concurrent.submit(launch, k) for k in ("request-a", "request-b")]
        results = [job.result(timeout=10) for job in calls]
    assert sorted(r.state for r in results) == ["finished", "refused"]
    (winner,) = [r for r in results if r.state == "finished"]
    assert next(r.code for r in results if r.state == "refused") == "sandbox_launch_exec_claimed"
    assert starts == [1]
    assert (
        svc.lifecycle.launch_claim_record(req.reservation.reservation_id)["request_id"] == winner.request_id
    )


@pytest.mark.parametrize(
    "fault", ["digest", "changed_source", "source_gone_after_recheck", "foreign_scratch", "link_failure"]
)
def test_seed_recheck_and_generation_owned_provisioning(tmp_path, monkeypatch, fault):
    from dataclasses import replace
    from pathlib import Path
    import shutil
    import stat
    import time
    from test_launch_admission import admitted_fixture
    from test_launch_snapshot import seed_tree
    from phase_loop_runtime import launch_supervisor as sup, launch_exec

    admitted_fixture(monkeypatch, tmp_path)
    data = b"frozen payload"
    name = "home/user/bin/tool"
    root, decl, manifest = seed_tree(
        tmp_path.resolve(), {name: data}, executable={name}, request_id="launch-1"
    )

    def runner(h):
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                svc.load_caps,
                svc.readiness_code,
                time.monotonic,
                containment_ready=lambda: True,
                child_stream=lambda *args: pytest.fail("no child started"),
            ),
        )

    def spawn(*args, **kw):
        loc = svc.lifecycle.launch_prepare_record(req.reservation.reservation_id)
        output = Path(loc["scratch_path"]) / name
        assert output.read_bytes() == data and stat.S_IMODE(output.stat().st_mode) == 0o700
        calls.append(True)
        raise OSError

    import hashlib
    import tempfile
    import rfc8785
    from phase_loop_runtime import launch_routes as routes
    from test_launch_routes import Host, fixture_manifest, local_record, pin_for
    from test_launch_snapshot import make_repo

    # The operator registers the real frozen Pi template against the SL-7
    # fixture host files. Only the byte source and its manifest pin are injected.
    host = Host(tmp_path)
    pins = rfc8785.dumps(fixture_manifest())
    actual = routes.register_templates

    def register(settings, **options):
        return actual(settings, host=host.files, pin=pin_for(pins))

    monkeypatch.setattr(routes, "register_templates", register)
    record = local_record(host, fixture_manifest(), image_digest=DIGEST)
    image = rfc8785.dumps(record)
    link_root = Path(tempfile.mkdtemp()).resolve()
    try:
        env = Env(tmp_path)
        conf = json.loads((env.config / "agent-toolkit.json").read_bytes())
        conf["launch"] = dict(
            seed_root=str(root),
            local_pi_runner_launcher="laneexec",
            local_link_root=str(link_root),
            templates=[image.decode()],
            toolkit_pins=pins.decode(),
            images=[dict(image_digest=DIGEST, workload="pi-runner", target_kind="local")],
        )
        env.write("agent-toolkit.json", conf)
        reservation = env.reserve()
        svc = env.service(supervisor_runner=runner, capped_popen=spawn)
        repo = make_repo(tmp_path.resolve() / "repository", {"source": "fixture"})
        saved, _, _ = prepare(svc, reservation, snapshot_root=str(repo))
        body = local_pi_request(
            reservation=reservation,
            policy_vector=reservation["policy_vector"],
            paths=saved.paths.to_json(),
            image_digest=DIGEST,
            snapshot=dict(root=str(repo), cwd=".", mode="git", masks=[], mask_dirs=[]),
            command=dict(
                template_id=record["template_id"], template_sha256=hashlib.sha256(image).hexdigest()
            ),
            seed=(replace(decl, manifest_sha256="0" * 64) if fault == "digest" else decl).to_json(),
            timeout_seconds=30,
        )
        req = wire.decode_launch_request("launch", json.dumps(body).encode())
        if fault == "link_failure":
            (link_root / reservation["reservation_id"]).mkdir(mode=0o700)
        calls = []

        def admit(*a, **kw):
            if fault == "changed_source":
                (root / req.request_id / name).write_bytes(b"changed")

        def pre_exec():
            if fault == "source_gone_after_recheck":
                shutil.rmtree(root)
            if fault == "foreign_scratch":
                record = svc.lifecycle.launch_prepare_record(req.reservation.reservation_id)
                holder = Path(record["scratch_path"])
                holder.mkdir(mode=0o700)
                (holder / "keep").write_bytes(b"independent")

        monkeypatch.setattr(launch_exec, "isolated_admission", admit)
        out = svc.launch(req, cancelled=threading.Event(), pre_exec=pre_exec)
        if fault == "source_gone_after_recheck":
            assert out.state == "finished" and calls == [True]
        elif fault == "link_failure":
            assert out.code == "sandbox_launch_bridge_lost" and not calls
            claim = svc.lifecycle.launch_claim_record(req.reservation.reservation_id)
            assert (
                not claim["claimed"]
                and claim["completed_rollback"]["cause"] == "link_socket_creation_failed"
            )
        else:
            assert not calls and out.code == "sandbox_launch_seed_refused"
            assert (
                out.seed_reason
                == {
                    "digest": "digest_mismatch",
                    "changed_source": "source_changed",
                    "foreign_scratch": "scratch_unprovisioned",
                }[fault]
            )
            assert not svc.lifecycle.launch_claim_record(req.reservation.reservation_id)
            if fault == "foreign_scratch":
                assert (
                    Path(
                        svc.lifecycle.launch_prepare_record(req.reservation.reservation_id)["scratch_path"]
                    )
                    / "keep"
                ).read_bytes() == b"independent"
    finally:
        shutil.rmtree(link_root)


@pytest.mark.parametrize("fault", ["unknown", "closed_image", "ttl", "budget", "staged"])
def test_remote_launch_uses_captured_host_gate_and_passes_fds_only_after_claim(
    tmp_path, monkeypatch, fault
):
    import hashlib
    import os
    import time
    import rfc8785
    from phase_loop_runtime import launch_supervisor as sup, launch_exec, launch_routes as routes
    from phase_loop_runtime import placement_process_contract as placement, sandbox_placement as sp
    from test_launch_admission import admitted_fixture
    from test_launch_routes import IMAGE_NODE, IMAGE_NODE_SHA, runtime_record, fixture_manifest
    from test_launch_snapshot import make_repo
    from test_launch_process_contract import review_request

    admitted_fixture(monkeypatch, tmp_path)
    env = Env(tmp_path)
    cfg = json.loads((env.config / "agent-harness.json").read_bytes())
    cfg["seat_route"]["qualification"] = "ai"
    tpl = dict(
        template_id="qualification.openshell.v1",
        workload="qualification",
        target_kind="openshell",
        policy_vectors=["minimal-with-app"],
        action="review",
        result_kinds=["result"],
        image_digest=DIGEST,
        argv=[IMAGE_NODE, {"slot": "tree"}],
        executable_chain=[
            dict(role="worker", locator_kind="declared", locator=IMAGE_NODE, sha256=IMAGE_NODE_SHA)
        ],
        ro_trees=[],
        image_links=[],
        link=None,
        environment_policy="constructed",
        references=[],
        max_timeout_seconds=600,
        result_schema_id=None,
    )
    raw = rfc8785.dumps(tpl)
    cfg["launch"] = dict(
        images=[dict(image_digest=DIGEST, workload="qualification", target_kind="openshell")],
        templates=[raw.decode()],
        routes_enabled=["qualification/openshell"],
    )
    env.write("agent-harness.json", cfg)
    life = env.lifecycle("agent-harness")
    reserve = dict(
        schema="placement.reserve.request.v1",
        request_id="reserve-review",
        workload="qualification",
        ttl_s=44 if fault == "ttl" else 600,
        image_digest=DIGEST,
        policy_vector="minimal-with-app",
        providers=["anthropic"],
        deadline_ms=60000,
        caller_context={},
    )
    res = life.reserve(
        placement.decode_request("reserve", json.dumps(reserve).encode()), cancelled=threading.Event()
    )
    assert res.outcome == "admitted"
    reservation = res.reservation.to_json()
    assert reservation["target"]["kind"] == "openshell"
    if fault == "budget":
        monkeypatch.setattr(env.coordinator, "declaration", lambda: sp.Declaration(max_lifetime_s=200))
    if fault != "closed_image":
        real_registry = routes.register_templates
        monkeypatch.setattr(
            routes,
            "register_templates",
            lambda settings, **opts: real_registry(
                settings, fixture_image_runtime=lambda image: runtime_record(fixture_manifest())
            ),
        )
    host_calls = []
    host_gate = sp.openshell_launch_refusal

    def host(config, **arguments):
        assert config is svc.config
        assert arguments["route_state"] is svc.route_state
        assert (
            arguments["config_sha256"] == reservation["config_sha256"]
            and arguments["egress_sha256"] == reservation["egress_sha256"]
        )
        host_calls.append(True)
        return host_gate(config, **arguments)

    monkeypatch.setattr(sp, "openshell_launch_refusal", host)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **k: None)
    stages = []

    def staged(h, *, staged, return_dir, lifetime):
        assert life.launch_claim_record(h.reservation_id)["generation"] == h.generation
        assert return_dir == life.launch_return_dir(h.reservation_id, h.run_id)
        assert (
            lifetime.ttl_s == 600
            and staged.paths.tree_path == "/work/" + h.run_id + "/fs" + req.snapshot.root
        )
        assert "source" in os.listdir(staged.tree_fd) and os.listdir(staged.scratch_fd) == []
        stages.append(staged.generation)
        _, blobs, recipe, _, paths = sup._verify(h, life)
        return sup._initial_responses(h, req, paths, recipe, blobs)[1]

    def run(h):
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                life, svc.capped_popen, svc.load_caps, svc.readiness_code, time.monotonic, run_staged=staged
            ),
        )

    svc = env.service(
        "agent-harness",
        lifecycle=life,
        route_state=lambda: "unknown" if fault == "unknown" else "enabled",
        supervisor_runner=run,
    )
    repo = make_repo(tmp_path.resolve() / "source-repo", {"source": "fixture"})
    body = review_request(
        "qualification",
        reservation=reservation,
        image_digest=DIGEST,
        policy_vector=reservation["policy_vector"],
        command=dict(template_id=tpl["template_id"], template_sha256=hashlib.sha256(raw).hexdigest()),
        snapshot=dict(root=str(repo), cwd=".", mode="git", masks=[], mask_dirs=[]),
        instructions={"source": "none"},
        timeout_seconds=30,
        caller_context={},
    )
    req = wire.decode_launch_request("launch", json.dumps(body).encode())
    out = svc.launch(req, cancelled=threading.Event())
    assert host_calls == [True]
    if fault == "staged":
        assert len(stages) == 1 and out.state == "finished"
    else:
        assert (
            out.code
            == {
                "ttl": "sandbox_launch_lifetime_unbounded",
                "budget": "sandbox_launch_lifetime_unbounded",
                "unknown": "sandbox_launch_route_disabled",
                "closed_image": "sandbox_launch_template_refused",
            }[fault]
        )
        assert not stages and not life.launch_claim_record(reservation["reservation_id"])
