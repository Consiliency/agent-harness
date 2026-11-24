"""Local mount-device evidence and chain-start interlocks."""

import os
from pathlib import Path
from stat import ST_DEV
import subprocess
import tempfile
import threading
import time

import pytest

from test_launch_service import launch_tmp_path as _launch_tmp_path
from test_launch_service import local_case
from test_launch_admission import admitted_fixture

launch_tmp_path = _launch_tmp_path


def mount_or_skip(path, unavailable, required):
    if path is None:
        if required:
            pytest.fail("E2-4 mount fixture unavailable: " + unavailable)
        pytest.skip("E2-4 mount fixture unavailable: " + unavailable)
    return path


@pytest.mark.parametrize("case", ["M1", "M2", "M3", "M4", "M5"])
def test_mount_device(tmp_path, monkeypatch, record_testsuite_property, case):
    from phase_loop_runtime import launch_supervisor as sup, sandbox_policy
    from phase_loop_runtime import launch_exec

    # conftest hides the host mount table for ordinary unit tests. These five
    # cases deliberately verify the real resolver on the actual fixture mounts.
    monkeypatch.setattr(sandbox_policy, "_MOUNTINFO", Path("/proc/self/mountinfo"))
    required = os.environ.get("PHASE_LOOP_TEST_REQUIRE_MOUNTS", "0")
    record_testsuite_property("PHASE_LOOP_TEST_REQUIRE_MOUNTS", required)
    tmp_path = tmp_path.resolve()
    primary = tmp_path
    secondary = os.environ.get("PHASE_LOOP_TEST_SECOND_BLOCK_DIR")
    ram = os.environ.get("PHASE_LOOP_TEST_TMPFS_DIR")
    if os.major(primary.stat().st_dev) == 0:
        mount_or_skip(None, "second block device", required == "1")
    if case == "M2":
        second = Path(secondary) if secondary else None
        witness = mount_or_skip(
            second
            if second
            and second.is_dir()
            and os.major(second.stat().st_dev)
            and second.stat().st_dev != primary.stat().st_dev
            else None,
            "second block device",
            required == "1",
        )
    elif case in ("M3", "M4", "M5"):
        tmpfs = Path(ram) if ram else None
        if tmpfs and tmpfs.is_dir():
            # GNU stat -f obtains f_type from statfs.
            magic = subprocess.check_output(
                ["/usr/bin/stat", "-f", "-c", "%t", str(tmpfs)], text=True
            ).strip()
        else:
            magic = None
        witness = mount_or_skip(tmpfs if magic == "1021994" else None, "tmpfs", required == "1")
    else:
        witness = primary
    with tempfile.TemporaryDirectory(dir=witness if case == "M3" else primary) as state:
        admitted_fixture(monkeypatch, tmp_path)
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(witness))
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1" if case == "M5" else "0")
        outcomes = []
        original = sup.local_devices

        witnesses = []
        staging_root = sandbox_policy.staging_root

        def devices(directories):
            def observe_witness():
                found = staging_root()
                witnesses.append(found)
                return found

            try:
                with monkeypatch.context() as patch:
                    patch.setattr(sandbox_policy, "staging_root", observe_witness)
                    result = original(directories)
            except (ValueError, sandbox_policy.SandboxRamBackedError) as error:
                outcomes.append((type(error), str(error)))
                raise
            outcomes.append(("admitted", result))
            return result

        monkeypatch.setattr(sup, "local_devices", devices)
        _, svc, req = local_case(tmp_path, state=Path(state) / "inventory")
        monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **k: "launch_input_unbound")
        result = svc.launch(req, cancelled=threading.Event())
        assert result.worker_invocations == 0 and not svc.lifecycle.launch_claim_record(
            req.reservation.reservation_id
        )
        assert witnesses == ([] if case == "M5" else [witness])
        if case == "M1":
            assert outcomes == [("admitted", (primary.stat().st_dev, primary.stat().st_ino))]
            assert result.admission_diagnostic == "launch_input_unbound"
        else:
            assert result.code == "sandbox_placement_capability_unmet" and len(outcomes) == 1
            if case == "M5":
                assert outcomes[0][0] is sandbox_policy.SandboxRamBackedError
            else:
                assert outcomes[0] == (
                    ValueError,
                    "anonymous attempt device" if case == "M3" else "different staging device",
                )


def test_new_scratch_device_mismatch_refuses_before_claim(tmp_path, monkeypatch):
    from phase_loop_runtime import launch_exec, launch_supervisor as sup

    admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **k: None)
    local_devices = sup.local_devices
    fstat = os.fstat
    generation_scratch = None

    def check_devices(directories):
        if directories[-1] != generation_scratch:
            return local_devices(directories)

        scratch = generation_scratch.stat()

        def other_device(fd):
            info = fstat(fd)
            if (info.st_dev, info.st_ino) == (scratch.st_dev, scratch.st_ino):
                fields = list(info)
                fields[ST_DEV] = os.makedev(os.major(info.st_dev), os.minor(info.st_dev) ^ 1)
                return os.stat_result(fields)
            return info

        with monkeypatch.context() as patch:
            patch.setattr(os, "fstat", other_device)
            return local_devices(directories)

    def runner(h):
        nonlocal generation_scratch
        prepared = svc.lifecycle.launch_prepare_record(h.reservation_id)
        generation_scratch = svc.lifecycle.launch_run_dir(prepared["run_id"]) / h.generation
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

    def popen(*args, **kwargs):
        pytest.fail("device mismatch must refuse before spawn")

    monkeypatch.setattr(sup, "local_devices", check_devices)
    _, svc, req = local_case(tmp_path, capped_popen=popen, supervisor_runner=runner)
    result = svc.launch(req, cancelled=threading.Event())

    assert (result.state, result.code, result.worker_invocations) == (
        "refused", "sandbox_placement_capability_unmet", 0,
    )
    life = svc.lifecycle
    assert life.launch_claim_record(req.reservation.reservation_id) is None
    assert generation_scratch is not None
    for kind in ("scratch", "stage"):
        assert life._launch_read(f"{kind}-intents", generation_scratch.name)["phase"] == "collected"
    assert not any(generation_scratch.parent.iterdir())
    assert not (life.launch_root / "stages" / generation_scratch.name).exists()


@pytest.mark.parametrize("fault", ["publication", "caps", "spawn"])
def test_claim_publication_and_start_intent(tmp_path, monkeypatch, fault):
    from phase_loop_runtime import launch_exec, launch_supervisor as sup

    controllers = admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **k: None)
    calls = []

    def popen(command, *, seat_key, **kwargs):
        calls.append((command, seat_key, kwargs))
        raise OSError("fixture cap failure")

    def runner(h):
        if fault == "publication":
            from dataclasses import replace

            h = replace(h, controller=h.controller + b" ")
        load = svc.load_caps if fault != "caps" else lambda: None
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                load,
                svc.readiness_code,
                time.monotonic,
                containment_ready=lambda: True,
            ),
        )

    _, svc, req = local_case(tmp_path, capped_popen=popen, supervisor_runner=runner)
    result = svc.launch(req, cancelled=threading.Event())
    claim = svc.lifecycle.launch_claim_record(req.reservation.reservation_id)
    assert result.worker_invocations == 0 and result.return_ is None
    assert claim and claim["claimed"] == (fault != "caps")
    if fault == "caps":
        assert result.code == "sandbox_placement_capability_unmet" and result.state == "refused"
        assert claim["completed_rollback"]["cause"] == "caps_recheck_refused"
    else:
        assert result.state == "finished" and result.termination.reason == "failed_to_start"
    assert len(calls) == int(fault == "spawn")
    assert len(list(controllers.iterdir())) == int(fault != "publication")
    if calls:
        command, seat_key, kwargs = calls[0]
        assert "-I" in command and "phase_loop_runtime.supervised_worker_cli" in command
        assert (
            seat_key == "laneexec:agent-harness:" + req.reservation.reservation_id
            and "before_spawn" not in kwargs
        )
        row = svc.lifecycle._launch_read("dispositions", claim["generation"])
        assert row["start_intent"] and row["debt"]["parent_collected"] is False


@pytest.mark.parametrize("decision", [False, True, None, "fence"])
def test_verified_return_is_interlocked_with_fence_and_retained_after_release(
    tmp_path, monkeypatch, decision
):
    from pathlib import Path
    from types import SimpleNamespace
    from phase_loop_runtime import launch_exec, launch_supervisor as sup
    from test_launch_return import patch_bytes, store_proposal, worker, _identity
    from phase_loop_runtime.convergence.adapters.patch_return import JournalAnchor
    from dataclasses import replace

    admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *args, **kwargs: None)
    evidence = tmp_path / "evidence"
    (evidence / "a-run").mkdir(parents=True, mode=0o700)
    data = patch_bytes()
    observed = worker(store_proposal({"evidence": evidence}, data))
    handoffs = []

    def run(h):
        handoffs.append(h)
        import json

        admitted = json.loads(sup.read_blob(h.stage_fd, "envelope.blob", 1 << 20))
        identity = replace(
            _identity(),
            run_id=h.run_id,
            attempt_id=h.run_id,
            assignment_digest=admitted["assignment_digest"],
            envelope_digest=admitted["envelope_digest"],
        )
        result = replace(
            observed, identity=identity, journal_complete=True, journal_anchor=JournalAnchor(3, "f" * 64)
        )
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                svc.load_caps,
                svc.readiness_code,
                time.monotonic,
                observe_result=lambda *_: sup.TerminatedAttempt(1, result, evidence, True, True),
                containment_ready=lambda: True,
            ),
        )

    env, svc, req = local_case(
        tmp_path,
        supervisor_runner=run,
        capped_popen=lambda *a, **kw: SimpleNamespace(poll=lambda: 0, returncode=0),
    )
    calls = []

    def predicate(candidate):
        calls.append(candidate)
        if decision == "fence":
            assert svc.lifecycle.fence_launch(
                *handoffs[0].ids, cause="release", deadline=time.monotonic() + 2
            )
            return False
        return decision

    result = svc.launch(req, cancelled=threading.Event(), withhold=predicate)
    assert result.state == "finished" and result.worker_invocations == 1
    assert calls == [data]
    if decision is False:
        retained = Path(result.return_.path)
        assert retained.read_bytes() == data and "returns" in retained.parts
        assert env.release(req.reservation.to_json(), "agent-harness")[0].state == "released"
        assert retained.read_bytes() == data
    else:
        assert result.return_ is None and result.code == "sandbox_launch_result_withheld"
        assert not list((svc.lifecycle.launch_root / "returns").rglob("*.patch"))


def test_witness_replaced_after_claim_rolls_back(tmp_path, monkeypatch):
    from phase_loop_runtime import launch_exec, launch_supervisor as sup

    admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **kw: None)
    second = tmp_path / "other-witness"
    second.mkdir(mode=0o700)
    real = sup.publish_controller

    def change(*args):
        assert svc.lifecycle.launch_claim_record(req.reservation.reservation_id)["claimed"]
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(second))
        return real(*args)

    monkeypatch.setattr(sup, "publish_controller", change)

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

    _, svc, req = local_case(tmp_path, supervisor_runner=runner)
    out = svc.launch(req, cancelled=threading.Event())
    assert out.code == "sandbox_placement_capability_unmet" and out.worker_invocations == 0
    assert not svc.lifecycle.launch_claim_record(req.reservation.reservation_id)["claimed"]
