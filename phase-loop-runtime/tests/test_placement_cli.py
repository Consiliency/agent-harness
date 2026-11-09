"""v13 PLACECLI SL-3: ``agent-harness-placement`` as a process.

Subprocess cases run the installed console script and the module path with isolated imports
(``-I``), a controlled HOME holding the operator configuration and hostile selection
variables that must change nothing. The black-box corpus (``tests/fixtures/placement-cli``)
runs through the real ``placement_cli.main`` in its own process against the fake coordinator.
"""

from __future__ import annotations

import ast
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

from phase_loop_runtime import cli, placement_cli
from phase_loop_runtime import placement_process_contract as contract
from phase_loop_runtime import sandbox_placement as sp
from phase_loop_runtime import seat_resource_caps

FIXTURES = Path(__file__).parent / "fixtures" / "placement-cli"
SOURCE = Path(contract.__file__).resolve().parents[1]
PREVIOUS_SHA256 = "7bf7781dd30de55e7b30200d70f6b90b49a7c7a9b73804892408fa7667181105"
HOSTILE = {
    "XDG_CONFIG_HOME": "/nonexistent/hostile-config",
    "XDG_RUNTIME_DIR": "/nonexistent/hostile-runtime",
    "AGENT_HARNESS_PLACEMENT_CLIENT": "agent-harness",
    "AGENT_HARNESS_PLACEMENT_CONFIG": "/nonexistent/hostile.json",
    "PLACEMENT_INVENTORY": "agent-harness",
    "PHASE_LOOP_SANDBOX_ROOT": "openshell://hostile.invalid/x",
    "PHASE_LOOP_SANDBOX_REMOTE_REQUIRED": "1",
    "PHASE_LOOP_SANDBOX_ADMIT_WAIT_S": "1",
    "PYTHONPATH": "/nonexistent/hostile-path",
}
SENTINEL = "sk-SENTINEL-must-not-leak-424242"


@pytest.fixture
def home():
    path = Path(tempfile.mkdtemp(prefix="plh", dir="/tmp"))
    config = path / ".config" / "agent-harness" / "placement"
    config.mkdir(parents=True, mode=0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def write_config(home: Path, name: str, body: dict) -> None:
    path = home / ".config" / "agent-harness" / "placement" / name
    path.write_text(json.dumps(body))
    os.chmod(path, 0o600)


def entry_points() -> list[list[str]]:
    module = [sys.executable, "-I", "-m", "phase_loop_runtime.placement_cli"]
    script = Path(sys.executable).with_name("agent-harness-placement")
    names = {entry.name for entry in metadata.entry_points(group="console_scripts")}
    if "agent-harness-placement" not in names or not script.exists():
        pytest.skip("the agent-harness-placement console script is not installed here")
    return [module, [str(script)]]


def run(argv: list[str], home: Path, stdin: bytes = b"", hostile: bool = True):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    if hostile:
        env.update(HOSTILE)
    done = subprocess.run(argv, input=stdin, capture_output=True, env=env, timeout=120, cwd=home)
    return done.returncode, done.stdout, done.stderr


def effects(home: Path) -> list[str]:
    root = home / ".local" / "state" / "agent-harness" / "placement"
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                  if p.is_file() and not p.name.endswith(".lock"))


# -- the installed entry and the module path ----------------------------------------------

def test_version_is_the_same_from_both_entries_and_ignores_hostile_variables(home):
    write_config(home, "agent-toolkit.json", {"schema": "placement.client-config.v1", "client": "agent-toolkit"})
    outputs = []
    for entry in entry_points():
        code, out, err = run([*entry, "--client", "agent-toolkit", "version"], home)
        assert (code, err) == (0, b"") and out.endswith(b"\n") and out.count(b"\n") == 1
        outputs.append(out)
    assert outputs[0] == outputs[1]
    version = contract.decode_response("version", outputs[0])
    assert version.client == "agent-toolkit"
    assert version.protocol_schema_sha256 == contract.protocol_schema_sha256()
    assert version.local_headroom.to_json() == {
        "memory_available_bytes_minimum_floor": 4294967296,
        "memory_available_total_ram_fraction_minimum": 0.1,
        "load_per_cpu_percent_maximum_exclusive": 70,
        "io_pressure_full_avg10_percent_maximum_exclusive": 10,
        "memory_pressure_some_avg10_percent_maximum_exclusive": 10,
        "live_sandboxes_maximum_exclusive": 4, "observation_age_seconds_maximum": 5}
    calm = run([*entry_points()[0], "--client", "agent-toolkit", "version"], home, hostile=False)[1]
    assert calm == outputs[0]
    assert effects(home) == []                       # version makes no placement effect


@pytest.mark.parametrize("argv", [[], ["version"], ["--client", "agent-toolkit"],
                                  ["--client", "toolkit", "version"], ["--client", "agent-toolkit", "launch"],
                                  ["--client", "agent-toolkit", "--client", "agent-harness", "version"],
                                  ["--client", "agent-toolkit", "version", "reserve"]])
def test_the_client_flag_is_required_and_values_never_echo(home, argv):
    code, out, err = run([*entry_points()[0], *argv], home)
    assert code == 70 and out == b"" and err == b"agent-harness-placement: invocation_invalid\n"


# -- errata-1 T2: schema-invalid input is exit 70 with stdout absent --------------------------

RESERVE = {"schema": "placement.reserve.request.v1", "request_id": "r-1", "workload": "pi-runner",
           "ttl_s": 60, "image_digest": "sha256:" + "a" * 64, "policy_vector": "full-remote-pi-runner",
           "providers": ["anthropic"], "deadline_ms": 1000, "caller_context": {}}
RELEASE = {"schema": "placement.release.request.v1", "request_id": "x", "reservation": {}, "deadline_ms": 1,
           "caller_context": {}}
REAP = {"schema": "placement.reap.request.v1", "request_id": "p", "scope": "caller_inventory",
        "deadline_ms": 1, "max_items": 0, "caller_context": {}}
T2_CASES = [
    ("reserve", b'{"schema":"placement.reserve.request.v1","schema":"x"}', "input_duplicate_key"),
    ("reserve", json.dumps(RESERVE).encode() + b"{}", "input_trailing_data"),
    ("reserve", b"\xc3\x28", "input_not_utf8"),
    ("reserve", json.dumps({**RESERVE, "deadline_ms": 1}).encode().replace(b'"deadline_ms": 1', b'"deadline_ms": NaN'),
     "input_non_finite_number"),
    ("reserve", b" " * 65537, "input_too_large"),
    ("reserve", json.dumps({**RESERVE, "providers": [SENTINEL]}).encode(), "schema_invalid"),
    ("release", json.dumps(RELEASE).encode(), "schema_invalid"),
    ("reap", json.dumps(REAP).encode(), "schema_invalid"),
    ("version", b"{}", "version_input_not_empty"),
]


@pytest.mark.parametrize("verb,data,diagnostic", T2_CASES)
def test_t2_schema_invalid_input_exits_70_with_stdout_absent(home, verb, data, diagnostic):
    for entry in entry_points():
        code, out, err = run([*entry, "--client", "agent-toolkit", verb], home, data)
        assert code == 70 and out == b""
        assert err == f"agent-harness-placement: protocol_failure {diagnostic}\n".encode()
        assert SENTINEL.encode() not in err
    assert effects(home) == []


class Counting:
    """An instrumented lifecycle at the CLI's construction site: counts every effect verb."""

    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        attribute = getattr(self.inner, name)
        if name in ("reserve", "release", "reap"):
            def counted(*args, **kwargs):
                self.calls.append(name)
                return attribute(*args, **kwargs)
            return counted
        return attribute


def _in_process(monkeypatch, capfdbinary, tmp_path, argv, data, **lifecycle):
    """``placement_cli.main`` in this process, with an instrumented lifecycle at its
    construction site; stdin is supplied, stdout and stderr are captured at the fd level."""
    counting = []

    def build(client):
        instance = Counting(sp.PlacementLifecycle(
            client, state_root=tmp_path / "state", config_root=tmp_path / "config", **lifecycle))
        counting.append(instance)
        return instance

    monkeypatch.setattr(placement_cli, "build_lifecycle", build)
    monkeypatch.setattr(placement_cli, "_read_stdin", lambda: data)
    capfdbinary.readouterr()
    code = placement_cli.main(argv)
    out, err = capfdbinary.readouterr()
    return code, out, err, [call for c in counting for call in c.calls]


@pytest.mark.parametrize("verb,data,diagnostic", T2_CASES)
def test_t2_schema_invalid_input_reaches_no_lifecycle_effect(monkeypatch, capfdbinary, tmp_path, verb, data,
                                                            diagnostic):
    code, out, err, calls = _in_process(monkeypatch, capfdbinary, tmp_path, ["--client", "agent-toolkit", verb], data)
    assert (code, out, calls) == (70, b"", [])
    assert diagnostic.encode() in err


@pytest.mark.parametrize("kind", ["intact", "killed"])
def test_t2_mutation_control_a_json_refusal_on_stdout_is_caught(monkeypatch, capfdbinary, tmp_path, kind):
    if kind == "killed":
        original = placement_cli._diagnostic

        def chatty(code):
            os.write(1, b'{"outcome":"refused"}\n')
            return original(code)
        monkeypatch.setattr(placement_cli, "_diagnostic", chatty)
    code, out, _err, _calls = _in_process(monkeypatch, capfdbinary, tmp_path, ["--client", "agent-toolkit", "reap"], b"{}")
    assert (code == 70 and out == b"") is (kind == "intact")


# -- errata-1 T3: a client pinned to the previous bytes refuses on version ---------------------

def test_t3_a_client_pinned_to_pre_erratum_bytes_refuses_before_any_effect(home):
    entry = entry_points()[0]
    code, out, _err = run([*entry, "--client", "agent-toolkit", "version"], home)
    assert code == 0
    # The pinned client reads only the identity field it trusts before decoding anything else.
    observed = json.loads(out)["protocol_schema_sha256"]
    assert observed != PREVIOUS_SHA256
    proceed = observed == PREVIOUS_SHA256
    if proceed:  # pragma: no cover - the refusal is the asserted path
        run([*entry, "--client", "agent-toolkit", "reserve"], home, json.dumps(RESERVE).encode())
    assert effects(home) == []


# -- outcomes, stderr and the caps state -------------------------------------------------------

def test_a_client_workload_mismatch_is_refused_before_effects(home):
    write_config(home, "agent-harness.json", {"schema": "placement.client-config.v1", "client": "agent-harness"})
    code, out, err = run([*entry_points()[0], "--client", "agent-harness", "reserve"], home,
                         json.dumps(RESERVE).encode())
    assert (code, err) == (10, b"")
    response = contract.decode_response("reserve", out)
    assert response.code == "sandbox_placement_workload_unsupported"
    assert not [p for p in effects(home) if "leases" in p or "slots" in p]


def test_an_unreadable_caps_record_keeps_version_and_help_working(monkeypatch, capfdbinary, tmp_path):
    def unreadable():
        raise seat_resource_caps.CapsUnavailable("seat_resource_caps_unavailable")

    code, out, err, calls = _in_process(monkeypatch, capfdbinary, tmp_path, ["--client", "agent-toolkit", "version"], b"",
                                        caps_loader=unreadable)
    assert (code, err, calls) == (0, b"", [])
    version = contract.decode_response("version", out)
    expected = sp.sandbox_policy.load_placement_client_config(
        "agent-toolkit", config_root=tmp_path / "config",
        seat_caps_sha256=sha256(b"seat_resource_caps_unavailable").hexdigest())
    assert version.config_sha256 == expected.config_sha256
    code, out, err, _calls = _in_process(monkeypatch, capfdbinary, tmp_path, ["--help"], b"", caps_loader=unreadable)
    assert code == 0 and err == b""
    assert out.decode().splitlines()[-1] == "seat resource caps: unavailable (seat_resource_caps_unavailable)"
    code, out, _err, _calls = _in_process(monkeypatch, capfdbinary, tmp_path, ["--help"], b"",
                                          caps_loader=lambda: seat_resource_caps.DEFAULT_CAPS)
    assert out.decode().splitlines()[-1] == "seat resource caps: available"
    code, out, err, calls = _in_process(monkeypatch, capfdbinary, tmp_path, ["--client", "agent-toolkit", "reserve"],
                                        json.dumps(RESERVE).encode(), caps_loader=unreadable)
    assert code == 10 and err == b"" and calls == ["reserve"]
    assert contract.decode_response("reserve", out).code == "sandbox_placement_capability_unmet"


def test_an_invalid_configuration_is_exit_70_with_a_closed_diagnostic(home):
    write_config(home, "agent-toolkit.json", {"schema": "placement.client-config.v1", "client": "agent-toolkit",
                                              "secret": SENTINEL})
    code, out, err = run([*entry_points()[0], "--client", "agent-toolkit", "version"], home)
    assert code == 70 and out == b"" and err == b"agent-harness-placement: placement_config_invalid\n"


def test_the_legacy_reaper_reaches_the_same_service_with_an_explicit_client(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    from test_placement_lifecycle_process import Env, reserve

    (tmp_path / "fixture").mkdir()
    env = Env(tmp_path / "fixture")
    env.state = tmp_path / ".local" / "state" / "agent-harness" / "placement"
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    env.clock.now = time.time()
    reserve(env.lifecycle(), "legacy", ttl_s=1)
    time.sleep(1.5)
    assert cli.main(["placement", "reap", "--client", "agent-harness"]) == 0
    assert "0 destroyed, 0 pending (0 examined, client agent-harness)" in capsys.readouterr().out
    assert len(env.slots()) == 1
    assert cli.main(["placement", "reap", "--client", "agent-toolkit"]) == 0
    assert "1 destroyed, 0 pending (1 examined, client agent-toolkit)" in capsys.readouterr().out
    assert env.slots() == []


def test_the_bridge_helper_launches_only_through_the_trusted_argv():
    source = (SOURCE / "phase_loop_runtime" / "placement_bridge.py").read_text()
    tree = ast.parse(source)
    spawn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                 and node.name == "_spawn_helper")
    names = {node.id for node in ast.walk(spawn) if isinstance(node, ast.Name)}
    assert "trusted_module_argv" in names and "-m" not in source.split("def _spawn_helper")[1].split("def ")[0]
    for module in ("placement_cli", "placement_process_contract"):
        text = (SOURCE / "phase_loop_runtime" / f"{module}.py").read_text()
        assert "subprocess" not in text and "importlib.import_module" not in text


# -- the black-box corpus, through the real CLI in its own process -----------------------------

CASES = json.loads((FIXTURES / "cases.json").read_text())["cases"]


def _lookup(value, dotted: str):
    for part in dotted.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_black_box_case(home, case):
    write_config(home, f"{case['client']}.json", case["config"])
    work = home / "w"
    work.mkdir()
    behaviour = {"state": str(work / "coordinator.json"), "upstream": str(work / "guest.sock"),
                 "admit": "ok", "kill": "ok"}
    outputs: list[bytes] = []
    responses: list[dict | None] = []
    for index, step in enumerate(case["steps"]):
        behaviour.update(step.get("coordinator", {}))
        (work / "behaviour.json").write_text(json.dumps(behaviour))
        before = json.loads((work / "coordinator.json").read_text())["calls"] if (work / "coordinator.json").exists() else []
        if "stdin_bytes" in step:
            data = step["stdin_bytes"].encode()
        elif step["verb"] == "version":
            data = step.get("stdin", "").encode()
        else:
            request = json.loads(json.dumps(step["request"]))
            if isinstance(request.get("reservation"), str):
                source = int(request["reservation"].split(".")[0][1:])
                request["reservation"] = responses[source]["reservation"]
            data = json.dumps(request).encode()
        argv = [sys.executable, "-I", str(FIXTURES / "run_cli.py"), str(SOURCE), str(FIXTURES),
                str(work / "behaviour.json"), "--", "--client", case["client"], step["verb"]]
        code, out, err = run(argv, home, data)
        expect = step["expect"]
        assert code == expect["exit"], (case["id"], index, out, err)
        if expect.get("stdout") == "absent":
            assert out == b"" and err == expect["stderr"].encode()
            responses.append(None)
        else:
            assert err == b"" and out.endswith(b"\n") and out.count(b"\n") == 1
            decoded = contract.decode_response(step["verb"], out)
            assert contract.exit_class(decoded) == code
            body = json.loads(out)
            for dotted, value in expect.get("response", {}).items():
                assert _lookup(body, dotted) == value, (case["id"], index, dotted)
            if "same_as" in expect:
                assert out == outputs[expect["same_as"]]
            responses.append(body)
        outputs.append(out)
        after = json.loads((work / "coordinator.json").read_text())["calls"] if (work / "coordinator.json").exists() else []
        if "coordinator_calls" in step:
            assert after[len(before):] == step["coordinator_calls"]
        assert not {"commit", "execute", "wait"} & set(after)
        if step.get("bridge") == "private_socket":
            socket_path = Path(responses[-1]["reservation"]["bridge"]["socket_path"])
            assert oct(socket_path.lstat().st_mode & 0o777) == "0o600"
            assert oct(socket_path.parent.lstat().st_mode & 0o777) == "0o700"
        if step.get("bridge") == "removed":
            socket_path = Path(responses[0]["reservation"]["bridge"]["socket_path"])
            assert not socket_path.exists() and not socket_path.parent.exists()
    bridges = home / ".local" / "state" / "agent-harness" / "placement" / "b"
    assert not bridges.exists() or not list(bridges.rglob("s")), "a case left a bridge behind"
