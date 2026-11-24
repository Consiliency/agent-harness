"""V3c isolated admission and publication at the ordinary service boundary."""

import hashlib
import json
from pathlib import Path
import sys
import threading

import pytest
import rfc8785

from test_launch_service import launch_tmp_path as _launch_tmp_path
from test_launch_service import local_case

launch_tmp_path = _launch_tmp_path


def admitted_fixture(monkeypatch, root):
    """Explicit admitted transport fixture. The isolated codec itself is tested separately."""
    from phase_loop_runtime import launch_exec, supervised_launch_binding as binding
    from phase_loop_runtime import supervised_capture_v2

    vector_file = Path(supervised_capture_v2.__file__).parent / (
        "schemas/supervised-worker-v2/conformance/envelope.v2.vectors.json"
    )
    vector = json.loads(vector_file.read_bytes())["cases"][0]["input"]["envelope"]
    envelope = rfc8785.dumps(vector)
    directory = root / "controllers"
    directory.mkdir(mode=0o700)
    locator = root / "managed.json"
    locator.write_text(json.dumps(dict(controller_root=str(directory))))
    locator.chmod(0o600)
    monkeypatch.setattr(binding, "MANAGED_BINDING", locator)

    def material(req, paths, settings, template, tree, seed, stage, slots, argv, origin, *_unused_context):
        assignment = vector["assignment_digest"]
        controller = dict(
            h=hashlib.sha256(envelope).hexdigest(),
            attempt=dict(assignment_digest=assignment, run_id=paths.run_id, attempt_id=paths.run_id),
            context=dict(
                expected_assignment_digest=assignment,
                expected_snapshot_ref=vector["units"]["snapshot_ref"],
                expected_crosswalk_ref=vector["units"]["crosswalk_ref"],
                qualified_routes=[],
                revoked_record_ids=[],
                policy_epoch="test",
                timeout_max_seconds=60,
                caller_context_suitability=None,
            ),
            slots=dict(workspace=str(tree.tree), target=req.snapshot.root, reference_roots=[]),
        )
        return envelope, rfc8785.dumps(controller)

    monkeypatch.setattr(launch_exec, "_bound_material", material)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(root))
    return directory


@pytest.mark.parametrize(
    ("output", "exit_code", "expected"),
    [
        (b'{"admitted":false,"diagnostic":"launch_input_unbound"}\n', 0, "launch_input_unbound"),
        (b'{"admitted":true}\n{}\n', 0, "codec_unavailable"),
        (b'{"admitted":true,"admitted":true}\n', 0, "codec_unavailable"),
        (b'{"admitted":true}\n', 1, "codec_unavailable"),
        (b"invalid\n", 0, "codec_unavailable"),
    ],
)
def test_isolated_reply_through_launch(tmp_path, monkeypatch, output, exit_code, expected):
    from phase_loop_runtime import seat_uid

    admitted_fixture(monkeypatch, tmp_path)
    calls = []

    def helper(module):
        calls.append(module)
        return [
            sys.executable,
            "-I",
            "-c",
            "import sys,os; sys.stdin.buffer.read(); "
            "assert sys.flags.isolated and os.getcwd()=='/' and 'HOME' not in os.environ; "
            f"sys.stdout.buffer.write({output!r}); sys.exit({exit_code})",
        ]

    monkeypatch.setattr(seat_uid, "trusted_module_argv", helper)
    _, svc, req = local_case(tmp_path)
    result = svc.launch(req, cancelled=threading.Event())
    assert result.code == "sandbox_launch_admission_refused" and result.admission_diagnostic == expected
    assert calls == ["phase_loop_runtime.launch_admission"]
    assert svc.lifecycle.launch_claim_record(req.reservation.reservation_id) is None


def test_overflow_while_helper_keeps_stdout_open(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_uid
    import time

    admitted_fixture(monkeypatch, tmp_path)
    pidfile = tmp_path / "helper-id"
    source = (
        "import os,sys,time; sys.stdin.buffer.read(); "
        f"open({str(pidfile)!r},'w').write(str(os.getpid())); "
        "os.write(1,b'x'*4097); time.sleep(30)"
    )
    monkeypatch.setattr(
        seat_uid, "trusted_module_argv", lambda module: [sys.executable, "-I", "-c", source]
    )
    _, svc, req = local_case(tmp_path, admission_bound_s=15)
    start = time.monotonic()
    result = svc.launch(req, cancelled=threading.Event())
    assert result.admission_diagnostic == "codec_unavailable" and result.worker_invocations == 0
    assert time.monotonic() - start < 10
    assert not Path("/proc", pidfile.read_text()).exists()


def test_real_isolated_helper_refuses_without_writing_controller(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_uid

    directory = admitted_fixture(monkeypatch, tmp_path)
    _, svc, req = local_case(tmp_path)
    real = seat_uid.trusted_module_argv
    calls = []

    def observed(name):
        argv = real(name)
        assert "-I" in argv and "-m" not in argv
        calls.append(name)
        return argv

    monkeypatch.setattr(seat_uid, "trusted_module_argv", observed)
    result = svc.launch(req, cancelled=threading.Event())
    assert (
        result.code == "sandbox_launch_admission_refused"
        and result.admission_diagnostic == "codec_unavailable"
    )
    assert calls == ["phase_loop_runtime.launch_admission"] and not list(directory.iterdir())


from test_supervised_launch import case as _operator_case
from test_supervised_launch_binding import v2_operator as _operator

case = _operator_case
v2_operator = _operator


def install_private_codec(tmp_path, monkeypatch, locator):
    from phase_loop_runtime import launch_exec, supervised_launch_binding as binding, seat_uid
    from phase_loop_runtime.supervised_contracts import load_contract_bundle

    # A contributor checkout may allow group writes. The operator fixture holds
    # the exact sealed resources under private, trusted ancestors, as an install does.
    package = tmp_path / "installed"
    resources = package / "schemas" / "supervised-worker-v2"
    for name, raw in load_contract_bundle(version="v2")._captured:
        path = resources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
    for directory in [package, *[p for p in package.rglob("*") if p.is_dir()]]:
        directory.chmod(0o700)
    monkeypatch.setattr(binding, "__file__", str(package / "supervised_launch_binding.py"))
    runtime = Path(launch_exec.__file__).resolve().parent.parent
    bootstrap = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0,{str(runtime)!r}); "
        "from phase_loop_runtime import launch_admission as a; "
        f"a.binding.MANAGED_BINDING=Path({str(locator)!r}); "
        f"a.binding.__file__={binding.__file__!r}; sys.exit(a.main())"
    )
    monkeypatch.setattr(
        seat_uid, "trusted_module_argv", lambda name: [sys.executable, "-I", "-c", bootstrap]
    )


@pytest.mark.parametrize("fault", ["qualified", "caller_context", "malformed", "prefix", "incompatible"])
def test_managed_codec_through_isolated_service(tmp_path, monkeypatch, v2_operator, fault):
    """Send held compatible or incompatible fixture material through the real helper pipeline."""
    from phase_loop_runtime import launch_exec
    from phase_loop_runtime.supervised_launch import discard_admission
    from test_supervised_capture_v2 import build_v2_attempt

    install_private_codec(tmp_path, monkeypatch, v2_operator.path)
    built = build_v2_attempt(v2_operator)
    discard_admission(built.prepared)
    built.capture.close()
    envelope = built.envelope.copy()
    if fault == "caller_context":
        envelope["caller_context"] = {"opaque": "echo"}
        envelope["envelope_digest"] = hashlib.sha256(
            rfc8785.dumps({k: v for k, v in envelope.items() if k != "envelope_digest"})
        ).hexdigest()
    if fault == "prefix":
        v2_operator.codec.write_text(
            v2_operator.codec.read_text()
            + '\ndef precheck_v2_admission(*a,**kw): return ("launch_timeout_mismatch",)\n'
        )
        document = json.loads(v2_operator.path.read_bytes())
        document["implementations"]["codec"]["sha256"] = hashlib.sha256(
            v2_operator.codec.read_bytes()
        ).hexdigest()
        v2_operator.path.write_text(json.dumps(document))
    raw = b"{}" if fault == "malformed" else rfc8785.dumps(envelope)
    controller = dict(v2_operator.controller, h=hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(launch_exec, "_bound_material", lambda *args: (raw, rfc8785.dumps(controller)))
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path))
    _, svc, req = local_case(tmp_path)
    if fault == "incompatible":
        spec = json.loads(v2_operator.spec_path.read_bytes())["launch"]
        Path(spec["template_path"]).write_bytes(
            json.loads(svc.config.canonical)["launch"]["templates"][0].encode()
        )
        Path(spec["config_path"]).write_bytes(svc.config.canonical)
    result = svc.launch(req, cancelled=threading.Event(), pre_exec=lambda: "operator_stop")
    if fault == "qualified":
        assert result.code == "sandbox_launch_pre_exec_refused"
    else:
        assert result.code == "sandbox_launch_admission_refused"
        if fault != "incompatible":
            assert (
                result.admission_diagnostic
                == {
                    "caller_context": "launch_input_unbound",
                    "malformed": "envelope_schema_invalid",
                    "prefix": "launch_timeout_mismatch",
                }[fault]
            )
    assert not svc.lifecycle.launch_claim_record(req.reservation.reservation_id)


@pytest.mark.parametrize("fault", ["equal", "different", "hardlink", "failed_fsync", "replacement"])
def test_controller_exclusive_publication_preserves_existing_identity(tmp_path, monkeypatch, fault):
    import os
    import time
    from phase_loop_runtime import launch_exec, launch_supervisor as sup

    controllers = admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **k: None)
    seen = []

    def run(h):
        dest = controllers / (json.loads(h.controller)["h"] + ".json")
        if fault in ("equal", "different", "hardlink"):
            dest.write_bytes(b"preexisting" if fault == "different" else h.controller)
            dest.chmod(0o600)
            if fault == "hardlink":
                os.link(dest, controllers / "other")
        original = sup.publish_controller

        def publication(*args):
            with monkeypatch.context() as patch:
                if fault in ("failed_fsync", "replacement"):
                    real_fsync = os.fsync

                    def fail(fd):
                        if dest.exists() and os.path.samestat(os.fstat(fd), dest.stat()):
                            if fault == "replacement":
                                dest.unlink()
                                dest.write_bytes(b"independent replacement")
                            raise OSError("sync failed")
                        return real_fsync(fd)

                    patch.setattr(os, "fsync", fail)
                ok = original(*args)
            seen.append((ok, dest.read_bytes() if dest.exists() else None))
            return ok

        monkeypatch.setattr(sup, "publish_controller", publication)
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
        expected = {
            "equal": h.controller,
            "hardlink": h.controller,
            "different": b"preexisting",
            "failed_fsync": None,
            "replacement": b"independent replacement",
        }[fault]
        assert seen == [(fault == "equal", expected)]

    def failed_start(*args, **kw):
        raise OSError

    _, svc, req = local_case(tmp_path, supervisor_runner=run, capped_popen=failed_start)
    result = svc.launch(req, cancelled=threading.Event())
    assert result.termination.reason == "failed_to_start" and result.worker_invocations == 0
    assert svc.lifecycle.launch_claim_record(req.reservation.reservation_id)["claimed"]


@pytest.mark.parametrize("origin", ["process", "lane"])
def test_original_commitments_reach_real_capture_through_managed_projection(
    tmp_path, monkeypatch, v2_operator, origin
):
    """The managed fixture qualifies the real projection while retaining both original byte commitments."""
    import time
    from phase_loop_runtime import launch_exec, supervised_launch_binding as binding
    from phase_loop_runtime.supervised_envelope_v2 import decode_v2
    from phase_loop_runtime.supervised_contracts import load_contract_bundle

    install_private_codec(tmp_path, monkeypatch, v2_operator.path)
    monkeypatch.setattr(binding, "MANAGED_BINDING", v2_operator.path)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path.resolve()))
    _, svc, req = local_case(tmp_path)
    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    spec = json.loads(v2_operator.spec_path.read_bytes())
    launch = spec["launch"]
    private = tmp_path.resolve()
    entry = private / "cgroup-entry"
    entry.write_bytes(launch_exec._cgroup_entry().read_bytes())
    entry.chmod(0o700)
    monkeypatch.setattr(launch_exec, "_cgroup_entry", lambda: entry)
    image = json.loads(svc.config.canonical)["launch"]["templates"][0].encode()
    Path(launch["template_path"]).write_bytes(image)
    Path(launch["config_path"]).write_bytes(svc.config.canonical)
    chain = [
        dict(wire=dict(role=role, locator_kind="declared", locator=f"exec-{i}"), path=str(path))
        for i, (role, path) in enumerate([("wrapper", entry), ("executable", private / "fixture-worker")])
    ]
    spec["slots"]["baseline_root"] = "root"
    launch.update(
        executable_chain=chain,
        tier="provider_readonly_patch_return_audit",
        target=req.snapshot.root,
        declared_roots={"refs": {"slot": "baseline_root"}},
        instructions={"source": None, "content": "hello"},
        non_secret_environment={},
        argv=[str(entry), str(private / "fixture-worker")],
    )
    qualification = Path(launch["qualification_path"])
    grant = dict(canonical_form="rfc8785", sha256=req.reservation.egress_sha256.removeprefix("sha256:"))
    now = time.time()
    record = dict(
        record_id="managed-projection",
        issuer_id="operator",
        policy_epoch="epoch-1",
        valid_from=now - 60,
        expires_at=now + 300,
        evidence=[dict(path=str(qualification), sha256=digest(qualification.read_bytes()))],
        tier=launch["tier"],
        action=req.action,
        transport_id=req.reservation.transport_id,
        executable_chain=[
            dict(
                locator_kind="declared",
                locator=row["wire"]["locator"],
                sha256=digest(Path(row["path"]).read_bytes()),
            )
            for row in chain
        ],
        template_sha256=digest(image),
        qualification_sha256=digest(qualification.read_bytes()),
        grants={"egress_policy_sha256": grant},
        credential_sources=[],
        observed_versions=["fixture", "fixture"],
    )
    rec = v2_operator.write("original-route.json", record)
    record_digest = digest(rec.read_bytes())
    ctx = json.loads(v2_operator.context_path.read_bytes())
    ctx.update(qualified_routes=[dict(path=str(rec), sha256=record_digest)])
    ctx["policy"]["issuer_records"] = {"operator": {"managed-projection": record_digest}}
    v2_operator.context_path.write_text(json.dumps(ctx))
    project = launch_exec._bound_material
    observed = []

    def managed(*args):
        stage = args[6]
        launch["references"][0]["path"] = str(stage / "baseline")
        v2_operator.spec_path.write_text(json.dumps(spec))
        if origin == "lane":
            observed.append("attempted real lane projection")
            return project(*args)
        env, controller = project(*args)
        decoded = decode_v2(env, bundle=load_contract_bundle(version="v2")).value
        trusted = decoded["launch"]["trusted_policy"]
        assert trusted["config_sha256"] == digest(svc.config.canonical) == req.reservation.config_sha256
        assert trusted["template_sha256"] == digest(image) == req.command.template_sha256
        assert trusted["qualification_sha256"] == record["qualification_sha256"]
        assert decoded["units"]["target_unit_ids"] == ("launch:" + req.request_id,)
        assert decoded["launch"]["grants"]["egress_policy_sha256"] == grant
        assert json.loads(controller)["slots"]["workspace"] == str(args[4].tree)
        observed.append(True)
        return env, controller

    monkeypatch.setattr(launch_exec, "_bound_material", managed)
    if origin == "lane":
        from phase_loop_runtime.launch_service import LaneContext, LaneUnits

        context = LaneContext("a" * 64, LaneUnits(("wrong",), (), "b" * 64, "c" * 64), ("src",), ())
        result = svc.launch_lane(req, lane_context=context, cancelled=threading.Event())
        assert observed == ["attempted real lane projection"]
        assert not v2_operator.marker.exists()
    else:
        result = svc.launch(req, cancelled=threading.Event())
        assert observed == [True] and v2_operator.marker.exists()
    assert (
        result.code == "sandbox_launch_admission_refused"
        and result.admission_diagnostic == "launch_input_unbound"
    )
    assert result.worker_invocations == 0 and not svc.lifecycle.launch_claim_record(
        req.reservation.reservation_id
    )
