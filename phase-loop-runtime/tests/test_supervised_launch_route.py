import pytest
import os
from pathlib import Path
import subprocess

from phase_loop_runtime import executable_dependency_startup as startup
from phase_loop_runtime import supervised_dependency as route
from phase_loop_runtime import supervised_launch as launch
from phase_loop_runtime import supervised_launch_binding as binding
from test_executable_dependency_startup import FakeDependency, register_session
from test_supervised_launch import case as _case, refused
from test_supervised_launch_mutations import mutant

case = _case


@pytest.mark.parametrize("bound,reason", [(False, "task_unbound"), (True, "dependency_route_unwired")])
@pytest.mark.parametrize("command", ["supervised-launch", "supervised-cancel"])
def test_required_route_before_effects(case, bound, reason, command):
    route_witness(case, route, bound, reason, command)


def route_witness(case, module, bound=False, reason="task_unbound", command="supervised-launch"):
    session = register_session(FakeDependency())
    lease = session.acquire_task("synthetic-task") if bound else None
    calls = []
    def effect(*args, **kwargs):
        calls.append("effect")
        raise AssertionError("unexpected route effect")
    def composed():
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(subprocess, "Popen", effect)
            for name in ("system", "fork", "posix_spawn", "posix_spawnp"):
                patch.setattr(os, name, effect)
            patch.setattr(Path, "read_bytes", effect)
            patch.setattr(Path, "write_bytes", effect)
            patch.setattr(binding, "_load_absolute", effect)
            result = module.preflight_supervised_route(command)
        assert result == launch.Refused(reason)
        assert calls == []
    try:
        if lease:
            with lease.bind_current():
                composed()
        else:
            composed()
    finally:
        if lease:
            lease.release()
        session.close()


@pytest.mark.parametrize("bound,reason", [(False, "task_unbound"), (True, "dependency_route_unwired")])
def test_direct_api_guard_before_decode(case, bound, reason, module=launch):
    session = register_session(FakeDependency())
    lease = session.acquire_task("synthetic-direct") if bound else None
    calls = []
    def direct():
        result = module.prepare_launch(b"not even JSON", validator=lambda view: calls.append("validator"),
                                       decoder=lambda raw: calls.append("decoder"), config=None)
        assert result == module.Refused(reason)
        assert calls == []
    try:
        if lease:
            with lease.bind_current():
                direct()
        else:
            direct()
    finally:
        if lease:
            lease.release()
        session.close()


@pytest.mark.parametrize("bound,reason", [(False, "task_unbound"), (True, "dependency_route_unwired")])
def test_direct_api_guard_mutation(case, monkeypatch, bound, reason):
    module = mutant(monkeypatch, launch, "direct_route")
    with pytest.raises(AssertionError):
        test_direct_api_guard_before_decode(case, bound, reason, module)


def test_classification_and_status_preserve_generic_inventory():
    session = register_session(FakeDependency())
    try:
        assert startup._classify_cli_route(("status",)) == "provider_free"
        assert startup._classify_cli_route(("supervised-status",)) == "dependency_unwired"
        assert route.preflight_supervised_route("supervised-status") is None
        assert route.classify_supervised_command("supervised-launch") == "dependency_unwired"
        assert route.classify_supervised_command("supervised-cancel") == "dependency_unwired"
        assert route.preflight_supervised_route("unknown") == launch.Refused("task_unbound")
    finally:
        session.close()


def test_standalone_dependency_declaration(case):
    assert route.preflight_supervised_route("supervised-launch") is None
    assert route.preflight_supervised_route("supervised-cancel") is None
    case.envelope["dependency_declaration"] = [{"synthetic": "required"}]
    calls = []
    refused(case, validator=lambda view: calls.append("validator"), reason="dependency_route_unwired")
    assert calls == []


def test_route_classification_mutation(case, monkeypatch):
    module = mutant(monkeypatch, route, "route_classification")
    with pytest.raises(AssertionError):
        route_witness(case, module)


def test_declared_dependency_mutation(case, monkeypatch):
    module = mutant(monkeypatch, launch, "dependency_route_unwired")
    case.envelope["dependency_declaration"] = ["synthetic-required"]
    with pytest.raises(AssertionError):
        refused(case, module)
