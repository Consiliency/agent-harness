"""The agy verifier's CI wiring after R1 (AGYROLL §3.3; RECBIND SL-1, EC-RECBIND-3/5).

``--contract`` runs on every pull request and push, with no path filter, because the seat
QCI reads files outside any agy-specific path. ``publish-pypi.yml`` gates the build on a
strict conformance run plus ``--release``. The removed gates -- ``--route-core``
(agent-harness#1029) and the full pin ``--source-only`` with ``agy_full_pin_scope.sh``
(agent-harness#1032) -- stay removed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REPO = Path(__file__).resolve().parents[2]
PUBLISH = REPO / ".github" / "workflows" / "publish-pypi.yml"
QUALIFIED = REPO / ".github" / "workflows" / "qualified-agy-image.yml"
PROBE = REPO / ".github" / "workflows" / "seat-caps-gate.yml"
REPORT = '"$RUNNER_TEMP/agy-conformance/conformance.xml"'

pytestmark = pytest.mark.skipif(not QUALIFIED.is_file() or not PUBLISH.is_file() or not PROBE.is_file(),
                                reason="the workflows are repository source")


def _workflow(path):
    value = yaml.safe_load(path.read_text())
    return value, value.get("on", value.get(True))


def test_the_contract_runs_on_every_pull_request_and_push_without_a_path_filter():
    workflow, triggers = _workflow(QUALIFIED)
    assert "pull_request" in triggers and "push" in triggers
    for event in ("pull_request", "push"):
        assert not (triggers[event] or {}).get("paths") and not (triggers[event] or {}).get("paths-ignore")
    assert triggers["push"]["branches"] == ["main"] and "schedule" in triggers
    (step,) = [s for s in workflow["jobs"]["verify"]["steps"] if "verify_qualified_agy_image.py" in s.get("run", "")]
    assert step["run"] == "uv run --locked python scripts/verify_qualified_agy_image.py --contract"
    assert step["working-directory"] == "phase-loop-runtime"
    assert "if" not in step and "continue-on-error" not in step
    assert "if" not in workflow["jobs"]["verify"]


def _gate(workflow, job):
    steps = workflow["jobs"][job]["steps"]
    (gate,) = [step for step in steps if "verify_qualified_agy_image.py" in step.get("run", "")]
    return steps, gate


def _bounds_s(run: str) -> int:
    """Worst case of every `timeout [-k K] N` in a step: N plus its kill grace."""
    total = 0
    for kill, seconds in re.findall(r"\btimeout (?:-k (\d+) )?(\d+)\b", run):
        total += int(seconds) + int(kill or 0)
    return total


def test_publication_gates_on_release_which_runs_strict_conformance_before_the_build():
    workflow, _ = _workflow(PUBLISH)
    steps, gate = _gate(workflow, "build")
    names = [step.get("name", "") for step in steps]
    run = gate["run"]
    # --release executes the strict suite itself and writes the report it then validates
    # (agent-harness#1937 re-check M4); no step runs the suite or hands it a report.
    assert f"--release --conformance-report {REPORT}" in run
    assert not any("tests/test_agy_route_conformance.py" in step.get("run", "") for step in steps)
    assert 'mkdir -p -m 0700 "$RUNNER_TEMP/agy-conformance"' in run
    # The locked test environment is synced and every Python runs from it by absolute path:
    # a bare `python` would be the setup-python interpreter without the locked test group.
    assert "uv sync --locked --group test --no-install-project" in run
    assert gate["env"] == {"UV_PROJECT_ENVIRONMENT": "${{ runner.temp }}/agy-conformance-venv",
                           "GITHUB_TOKEN": "${{ github.token }}"}
    assert 'py="$UV_PROJECT_ENVIRONMENT/bin/python"' in run
    assert not re.search(r"(?<![\w/$\"])python3? ", run.replace("python -m pip install uv", ""))
    # The host prerequisites (agent-harness#1895, agent-harness#1993) come from the host script,
    # always by absolute path, in this order: host context, delegation, in-unit baseline,
    # scratch device, provisioned report, device assertion, then the verifier in the manager.
    assert 'host="$GITHUB_WORKSPACE/ci/seat-caps-host.sh"' in run
    order = [
        '"$host" context -- timeout 60 "$py" "$report" --label host-context',
        '"$host" delegate',
        '"$host" run --baseline -- timeout 60 "$py" "$report" --label baseline',
        '"$host" provision',
        "\ncd phase-loop-runtime\n",
        '"$host" run -- timeout 60 "$py" "$report" --label provisioned ',
        '--expect-device "$majmin"',
        # agent-harness#1993: the strict suite resolves its scratch inside a test session
        # (below pytest's tmp_path); that binding is checked the same way, before the verifier.
        '"$host" run -- env CI_SCRATCH_DEVICE="$majmin" PYTHONPATH="$PWD/src:$PWD/tests"',
        "tests/test_seat_caps_scratch_binding.py",
        '"$host" run --pass-env GITHUB_TOKEN -- timeout 1200 "$py" scripts/verify_qualified_agy_image.py',
    ]
    positions = [run.index(item) for item in order]
    assert positions == sorted(positions)
    # A failed delegation or provision still leaves a host-context report behind.
    assert '"$host" delegate || after_failure delegate' in run
    assert '"$host" provision || after_failure provision' in run
    assert "SEAT_CAPS" not in run and "readiness_code" not in run
    assert "AGY_CONFORMANCE_STRICT" not in run
    assert "if" not in gate and "continue-on-error" not in gate
    assert names.index("Install review sandbox prerequisites") < names.index(gate["name"]) \
        < names.index("Seat caps scratch teardown") < names.index("Upload seat caps evidence") \
        < names.index("Verify tag matches phase-loop-runtime version") \
        < names.index("Build sdist + wheel")
    by_name = {step.get("name"): step for step in steps}
    teardown = by_name["Seat caps scratch teardown"]
    upload = by_name["Upload seat caps evidence"]
    assert teardown["if"] == "always()" and upload["if"] == "always()"
    assert teardown["run"] == '"$GITHUB_WORKSPACE/ci/seat-caps-host.sh" teardown'
    assert upload["uses"] == "actions/upload-artifact@v4"
    assert "${{ runner.temp }}/seat-caps-evidence/" in upload["with"]["path"]
    assert "continue-on-error" not in teardown and "continue-on-error" not in upload


def test_the_host_script_provisions_the_real_prerequisites_without_forcing_or_bypassing():
    script = (REPO / "ci" / "seat-caps-host.sh").read_text()
    assert os.access(REPO / "ci" / "seat-caps-host.sh", os.X_OK)
    for required in (
        "Delegate=cpu cpuset io memory pids", "loginctl enable-linger",
        # Without Type=oneshot, systemd counts death by SIGHUP/INT/TERM/PIPE as a clean exit,
        # and timeout re-raises its child's signal: a killed gate would read as success.
        "-p Type=oneshot", "--same-dir", "systemd-run --user --pipe --wait",
        'export XDG_RUNTIME_DIR="/run/user/$uid"',
        'export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"',
        "losetup --find --show",
        '-E "PHASE_LOOP_SANDBOX_STAGING_DIR=${st[mount]}/sandboxes"',
        '-E "XDG_CACHE_HOME=${st[mount]}/cache"',
        # The suite's isolation re-roots both automatic paths at pytest's tmp_path, whose
        # root is the temporary directory (agent-harness#1993).
        '-E "TMPDIR=${st[mount]}/tmp"', 'mkdir -m 0700 "$mnt/tmp"',
    ):
        assert required in script, required
    assert "losetup -D" not in script and "umount -l" not in script
    assert "SEAT_CAPS" not in script and "readiness_code" not in script
    assert "AGY_CONFORMANCE_STRICT" not in script


def test_every_gate_bound_fits_inside_the_job_so_cleanup_and_evidence_still_run():
    """A job timeout shorter than the gate's own bounds would kill the job before the
    always-run teardown and evidence upload (agent-harness#1993)."""
    setup_minutes = 5
    for path, job in ((PUBLISH, "build"), (PROBE, "probe")):
        workflow, _ = _workflow(path)
        steps, gate = _gate(workflow, job)
        # pip install uv and uv sync are allowed three minutes on top of the explicit bounds.
        assert _bounds_s(gate["run"]) + 180 <= gate["timeout-minutes"] * 60, path
        after = steps[steps.index(gate) + 1:]
        always = [step for step in after if step.get("if") == "always()"
                  or "seat_caps_loop_validation.py" in step.get("run", "")]
        for step in always:
            assert "timeout-minutes" in step, step.get("name")
        budget = setup_minutes + gate["timeout-minutes"] + sum(s["timeout-minutes"] for s in always)
        limit = workflow["jobs"][job]["timeout-minutes"]
        if isinstance(limit, str):
            match = re.fullmatch(r"\$\{\{ github\.event_name == 'pull_request' && (\d+) \|\| (\d+) \}\}",
                                 limit)
            assert match, limit
            pull_request, other = int(match.group(1)), int(match.group(2))
            assert other == 140  # the measured tag/dispatch allowance is unchanged
            assert pull_request >= budget and other >= budget
        else:
            assert limit >= budget, path


def test_seat_caps_gate_workflow_mirrors_the_release_gate():
    release, _ = _workflow(PUBLISH)
    probe, triggers = _workflow(PROBE)
    assert set(triggers) == {"workflow_dispatch", "pull_request"}
    paths = triggers["pull_request"]["paths"]
    for path in ("ci/seat-caps-host.sh", ".github/workflows/seat-caps-gate.yml",
                 ".github/workflows/publish-pypi.yml", "phase-loop-runtime/scripts/seat_caps_*.py"):
        assert path in paths
    assert probe["permissions"] == {"contents": "read"}
    build, job = release["jobs"]["build"], probe["jobs"]["probe"]
    assert job["runs-on"] == build["runs-on"] == "ubuntu-24.04"
    assert job["strategy"]["fail-fast"] is False and len(job["strategy"]["matrix"]["shard"]) >= 6
    assert job["timeout-minutes"] >= 35
    release_steps, release_gate = _gate(release, "build")
    probe_steps, probe_gate = _gate(probe, "probe")
    # checkout, setup-python and the prerequisites are the release build's, verbatim.
    assert probe_steps[:3] == release_steps[:3]
    assert probe_steps[2]["name"] == "Install review sandbox prerequisites"
    # The gate is identical apart from the documented handoff check: the verifier's run
    # starts without an inherited manager connection.
    prefix = "env -u XDG_RUNTIME_DIR -u DBUS_SESSION_BUS_ADDRESS \\\n  "
    assert prefix in probe_gate["run"]
    assert probe_gate["run"].replace(prefix, "") == release_gate["run"]
    assert {k: v for k, v in probe_gate.items() if k != "run"} \
        == {k: v for k, v in release_gate.items() if k != "run"}
    names = [step.get("name") for step in probe_steps]
    by_name = {step.get("name"): step for step in probe_steps}
    release_by_name = {step.get("name"): step for step in release_steps}
    assert by_name["Seat caps scratch teardown"] == release_by_name["Seat caps scratch teardown"]
    upload, release_upload = by_name["Upload seat caps evidence"], release_by_name["Upload seat caps evidence"]
    assert upload["with"]["name"] == "seat-caps-evidence-${{ matrix.shard }}-${{ github.run_attempt }}"
    assert {k: v for k, v in upload["with"].items() if k != "name"} \
        == {k: v for k, v in release_upload["with"].items() if k != "name"}
    assert upload["if"] == release_upload["if"] == "always()"
    validation = by_name["Seat caps enforcement validation"]
    # A step starts in the workspace root: the directory, host script and interpreter are explicit.
    assert validation["working-directory"] == "phase-loop-runtime"
    assert validation["env"] == {"UV_PROJECT_ENVIRONMENT": release_gate["env"]["UV_PROJECT_ENVIRONMENT"]}
    # It runs even after a failed gate, so a provisioned shard always records enforcement.
    assert validation["if"] == "${{ !cancelled() }}"
    assert '"$GITHUB_WORKSPACE/ci/seat-caps-host.sh"' in validation["run"]
    assert '"$UV_PROJECT_ENVIRONMENT/bin/python"' in validation["run"]
    assert "$GITHUB_WORKSPACE/phase-loop-runtime/scripts/seat_caps_loop_validation.py" in validation["run"]
    assert names.index(probe_gate["name"]) < names.index("Seat caps enforcement validation") \
        < names.index("Seat caps scratch teardown") < names.index("Upload seat caps evidence") \
        < names.index("Seat caps summary")
    assert by_name["Seat caps summary"]["if"] == "always()"
    assert not any("continue-on-error" in step for step in probe_steps)
    assert "continue-on-error" not in job


@pytest.mark.parametrize("path", [PUBLISH, QUALIFIED])
def test_the_removed_gates_stay_removed(path):
    text = path.read_text()
    assert "--source-only" not in text and "--route-core" not in text and "agy_full_pin_scope" not in text


def test_the_full_pin_scope_script_and_old_catalog_are_deleted():
    assert not (SCRIPTS / "agy_full_pin_scope.sh").exists()
    assert not (REPO / "plans" / "evidence" / "qualified-provider-images.json").exists()


def test_the_verifier_has_exactly_the_three_modes():
    text = (SCRIPTS / "verify_qualified_agy_image.py").read_text()
    for flag in ("--contract", "--release", "--upstream-only", "--conformance-report"):
        assert f'"{flag}"' in text
    for flag in ("--source-only", "--route-core"):
        assert f'"{flag}"' not in text


# --- the releases API token (agent-harness#1993: shared runner addresses hit the limit) ---

def _verifier_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image_token",
                                                  SCRIPTS / "verify_qualified_agy_image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Json:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *_args):
        return b"{}"


def test_the_releases_api_read_carries_the_token_only_to_the_api(monkeypatch):
    verifier = _verifier_module()
    seen = []
    monkeypatch.setattr(verifier, "urlopen", lambda request, timeout: seen.append(request) or _Json())
    api = "https://api.github.com/repos/o/r/releases/tags/1.0.0"
    verifier.fetch_release(api, environ={"GITHUB_TOKEN": "tok-123"})
    verifier.fetch_release(api, environ={})
    verifier.fetch_release("https://example.invalid/releases", environ={"GITHUB_TOKEN": "tok-123"})
    headers = [dict(request.header_items()) for request in seen]
    assert headers[0]["Authorization"] == "Bearer tok-123"
    assert "Authorization" not in headers[1] and "Authorization" not in headers[2]


def test_asset_downloads_and_the_conformance_run_never_receive_the_token(monkeypatch, tmp_path):
    import subprocess
    verifier = _verifier_module()
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    requests = []

    class _Body:
        def __init__(self):
            self.sent = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *_args):
            if self.sent:
                return b""
            self.sent = True
            return b"x"

    verifier.download_asset("https://github.com/o/r/releases/download/1.0.0/a.tar.gz",
                            tmp_path / "a", opener=lambda request, timeout: requests.append(request) or _Body(),
                            sleep=lambda _s: None)
    assert all("Authorization" not in dict(request.header_items()) for request in requests)
    seen = {}

    def runner(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    verifier.run_conformance_suite(tmp_path / "conformance.xml", runner=runner)
    assert "GITHUB_TOKEN" not in seen["env"]


def test_only_the_verifier_unit_receives_the_read_only_token():
    for path, job in ((PUBLISH, "build"), (PROBE, "probe")):
        workflow, _ = _workflow(path)
        assert workflow["permissions"] == {"contents": "read"}, path
        assert "permissions" not in workflow["jobs"][job], path
        _steps, gate = _gate(workflow, job)
        assert gate["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
        passing = [line for line in gate["run"].splitlines() if "--pass-env" in line]
        assert [line.strip() for line in passing] == [
            '"$host" run --pass-env GITHUB_TOKEN -- timeout 1200 "$py" scripts/verify_qualified_agy_image.py \\']
        # The token is never put on a command line.
        assert "github.token" not in gate["run"] and "$GITHUB_TOKEN" not in gate["run"]
    upstream = yaml.safe_load(QUALIFIED.read_text())["jobs"]["upstream"]
    (step,) = [s for s in upstream["steps"] if "--upstream-only" in s.get("run", "")]
    assert step["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
