"""The shape of the JEV Drill companion workflow (JEVHOST §8 [C4])."""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "jevdrill-companion.yml"
SCRIPT = RUNTIME / "scripts" / "jevdrill_receipt.py"

pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(), reason="repository source absent from the standalone-from-wheel layout"
)


def _load_receipt():
    spec = importlib.util.spec_from_file_location("jevdrill_receipt_shape", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R = _load_receipt()

SYNC_TEMPLATE = (
    "uv sync --project phase-loop-runtime --group test --extra visual --locked --python ${{ matrix.harness_python }}"
)
JEV_SYNC = "uv sync --locked --python cpython-3.14"
RECEIPT_LINUX = "receipt (linux, py3.12)"
INSTALLED_LINUX = "installed (linux, py3.12 + jev cpython-3.14)"
INFORMATIONAL = "informational: harness py3.14 (not R3/R6 evidence)"
DISPATCH_RUNNERS = {"linux": "ubuntu-24.04", "macos": "macos-15", "windows": "windows-2025"}
TWELVE_ARGS = [f"tests/{name}" for name in R.TWELVE_FILES]

# JEVHOST §8's path filter, before the jevdrill_install.py helper the preflight added.
REQUIRED_PATHS = {
    *(f"phase-loop-runtime/src/phase_loop_runtime/{m}.py" for m in (
        "jevdrill_adapter", "jevdrill_queue", "runner", "launcher", "observability",
        "file_lock", "windows_process", "windows_storage",
    )),
    *(f"phase-loop-runtime/tests/{name}" for name in R.TWELVE_FILES),
    "phase-loop-runtime/tests/jevdrill_fixture_values.py",
    "phase-loop-runtime/tests/phase_loop_test_utils.py",
    "phase-loop-runtime/tests/fixtures/jevdrill/**",
    "phase-loop-runtime/tests/conftest.py",
    "phase-loop-runtime/tests/launch_audit_hook.py",
    "phase-loop-runtime/pyproject.toml",
    "phase-loop-runtime/uv.lock",
    "phase-loop-runtime/scripts/jevdrill_receipt.py",
    ".github/workflows/jevdrill-companion.yml",
}


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wf(text) -> dict:
    return yaml.safe_load(text)


def _triggers(wf: dict) -> dict:
    return wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True


def _matrices(job: dict) -> tuple[list, list]:
    """The (dispatch, push/pull_request) matrix rows of a job's fromJSON expression."""
    expr = job["strategy"]["matrix"]
    assert isinstance(expr, str)
    match = re.fullmatch(
        r"\$\{\{ fromJSON\(github\.event_name == 'workflow_dispatch' && '(\{.*?\})' \|\| '(\{.*?\})'\) \}\}", expr
    )
    assert match, expr
    dispatch, default = (json.loads(group)["include"] for group in match.groups())
    return dispatch, default


def _step(job: dict, needle: str) -> dict:
    found = [s for s in job["steps"] if needle in (s.get("run") or "") or needle == s.get("name")]
    assert len(found) == 1, (needle, found)
    return found[0]


def _commands(run: str) -> list[list[str]]:
    """Each shell line of a run block, split as the shell would (no continuations here)."""
    return [shlex.split(line) for line in run.splitlines() if line.strip() and not line.strip().startswith("#")]


def _pytest_runs(run: str) -> list[list[str]]:
    return [cmd for cmd in _commands(run) if cmd[:5] == ["uv", "run", "--no-sync", "python", "-m"] and cmd[5] == "pytest"]


def _classifier_runs(run: str) -> list[list[str]]:
    return [cmd for cmd in _commands(run) if "scripts/jevdrill_receipt.py" in cmd and "classify" in cmd]


# --- triggers, permissions, input ------------------------------------------------------------


def test_triggers_and_path_filter(wf):
    triggers = _triggers(wf)
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}
    paths = set(triggers["pull_request"]["paths"])
    assert REQUIRED_PATHS <= paths, REQUIRED_PATHS - paths
    assert paths - REQUIRED_PATHS <= {"phase-loop-runtime/tests/jevdrill_install.py"}


def test_permissions_secrets_and_no_pull_request_target(wf, text):
    assert wf["permissions"] == {"contents": "read"}
    for job in wf["jobs"].values():
        assert "permissions" not in job
    assert "secrets" not in text
    assert "pull_request_target" not in text


def test_jevdrill_ref_input_defaults_to_the_synced_sha_and_is_checked_first(wf):
    assert re.fullmatch(r"[0-9a-f]{40}", R.JEVDRILL_REF_DEFAULT)
    inputs = _triggers(wf)["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"jevdrill_ref"}
    assert inputs["jevdrill_ref"]["default"] == R.JEVDRILL_REF_DEFAULT
    assert wf["env"]["JEVDRILL_REF"] == f"${{{{ inputs.jevdrill_ref || '{R.JEVDRILL_REF_DEFAULT}' }}}}"
    for name, job in wf["jobs"].items():
        first = job["steps"][0]
        assert first["name"] == "Validate jevdrill_ref", name
        assert '[[ ! "$JEVDRILL_REF" =~ ^[0-9a-f]{40}$ ]]' in first["run"]
        assert "exit 1" in first["run"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash absent")
@pytest.mark.parametrize(
    "ref, ok",
    [(R.JEVDRILL_REF_DEFAULT, True), (R.JEVDRILL_REF_DEFAULT[:12], False), (R.JEVDRILL_REF_DEFAULT.upper(), False),
     ("main", False), (R.JEVDRILL_REF_DEFAULT + "\nx", False), ("", False)],
)
def test_the_ref_check_accepts_only_a_full_sha(wf, tmp_path, ref, ok):
    script = wf["jobs"]["installed"]["steps"][0]["run"]
    out = tmp_path / "out"
    result = subprocess.run(
        ["bash", "-e", "-c", script], env={"JEVDRILL_REF": ref, "GITHUB_OUTPUT": str(out), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=30,
    )
    assert (result.returncode == 0) is ok, result.stderr
    if ok:
        assert out.read_text() == f"sha={ref}\n"


# --- legs ------------------------------------------------------------------------------------


def test_the_push_and_pull_request_legs_and_their_names(wf):
    assert set(wf["jobs"]) == {"receipt", "installed"}
    for name, job in wf["jobs"].items():
        assert job["name"] == "${{ matrix.job_name }}"
        assert job["runs-on"] == "${{ matrix.runner }}"
        assert isinstance(job["timeout-minutes"], int) and 0 < job["timeout-minutes"] <= 120
        assert job["strategy"]["fail-fast"] is False
        assert "if" not in job, name
    assert _matrices(wf["jobs"]["receipt"])[1] == [
        {"job_name": RECEIPT_LINUX, "runner": "ubuntu-24.04", "os_label": "linux", "harness_python": "3.12"}
    ]
    assert _matrices(wf["jobs"]["installed"])[1] == [
        {"job_name": INSTALLED_LINUX, "runner": "ubuntu-24.04", "os_label": "linux", "harness_python": "3.12"}
    ]


def test_the_dispatched_matrix_and_the_informational_leg(wf):
    receipt, _ = _matrices(wf["jobs"]["receipt"])
    installed, _ = _matrices(wf["jobs"]["installed"])
    expected_receipt = [
        {"job_name": f"receipt ({os}, py3.12)", "runner": runner, "os_label": os, "harness_python": "3.12"}
        for os, runner in DISPATCH_RUNNERS.items()
    ] + [{"job_name": INFORMATIONAL, "runner": "ubuntu-24.04", "os_label": "linux", "harness_python": "3.14"}]
    assert receipt == expected_receipt
    assert installed == [
        {"job_name": f"installed ({os}, py3.12 + jev cpython-3.14)", "runner": runner, "os_label": os,
         "harness_python": "3.12"}
        for os, runner in DISPATCH_RUNNERS.items()
    ]
    # harness_python is 3.12 on every R3 leg, and 3.14 only on the labelled informational leg [C8].
    for row in receipt + installed + _matrices(wf["jobs"]["receipt"])[1] + _matrices(wf["jobs"]["installed"])[1]:
        if row["harness_python"] != "3.12":
            assert row == expected_receipt[-1]
            assert "not R3/R6 evidence" in row["job_name"]


# --- sync, interpreter, checkout ----------------------------------------------------------------


def test_one_harness_sync_template(wf):
    for name, job in wf["jobs"].items():
        syncs = [s["run"] for s in job["steps"] if "uv sync --project" in (s.get("run") or "")]
        assert syncs == [SYNC_TEMPLATE], name


def test_jev_drill_runs_on_cpython_314_and_records_its_interpreter(wf):
    installed = wf["jobs"]["installed"]
    checkout = _step(installed, "Check out JEV Drill at jevdrill_ref")
    assert checkout["with"] == {
        "repository": "Consiliency/jevdrill",
        "ref": "${{ steps.ref.outputs.sha }}",
        "path": "_jevdrill",
        "persist-credentials": False,
    }
    assert installed["steps"][0]["id"] == "ref"
    jev = _step(installed, JEV_SYNC)
    assert jev["id"] == "jev" and jev["working-directory"] == "_jevdrill"
    assert jev["run"].splitlines()[0] == JEV_SYNC
    assert "sys.implementation.name" in jev["run"] and "sys.version" in jev["run"]
    assert '>> "$GITHUB_STEP_SUMMARY"' in jev["run"]
    assert '[ "$impl" != "cpython" ]' in jev["run"] and '[[ "$version" != 3.14.* ]]' in jev["run"]
    for job in wf["jobs"].values():
        assert all("--python cpython" not in (s.get("run") or "") for s in job["steps"] if s is not jev)


def test_the_checkout_comparison_runs_before_the_tests(wf):
    steps = wf["jobs"]["installed"]["steps"]
    compare = _step(wf["jobs"]["installed"], "compare-contract")
    assert "--jevdrill \"$WORKSPACE/_jevdrill\" --harness tests/fixtures/jevdrill" in compare["run"]
    assert steps.index(compare) < steps.index(_step(wf["jobs"]["installed"], "classify"))
    assert "compare-contract" not in yaml.safe_dump(wf["jobs"]["receipt"])


# --- variables ------------------------------------------------------------------------------------


def test_sched_is_set_on_every_leg(wf):
    assert wf["env"]["PHASE_LOOP_TDD_EXPECT_SCHED"] == "1"
    for job in wf["jobs"].values():
        assert "PHASE_LOOP_TDD_EXPECT_SCHED" not in (job.get("env") or {})
        for step in job["steps"]:
            assert "PHASE_LOOP_TDD_EXPECT_SCHED" not in (step.get("env") or {})
            assert "PHASE_LOOP_TDD_EXPECT_SCHED" not in (step.get("run") or "")


def test_neither_variable_on_the_receipt_leg(wf, text):
    receipt = wf["jobs"]["receipt"]
    assert "JEVDRILL_TEST" not in yaml.safe_dump(receipt)
    assert "JEVDRILL_TEST" not in yaml.safe_dump(wf["env"])
    assert "GITHUB_ENV" not in _step(wf["jobs"]["installed"], JEV_SYNC)["run"]


def test_both_variables_from_one_environment_on_the_installed_leg(wf):
    installed = wf["jobs"]["installed"]
    run_step = _step(installed, "classify")
    assert run_step["env"]["JEVDRILL_TEST_PYTHON"] == "${{ steps.jev.outputs.python }}"
    assert run_step["env"]["JEVDRILL_TEST_CLI"] == "${{ steps.jev.outputs.cli }}"
    jev = _step(installed, JEV_SYNC)["run"]
    assert jev.count('python="${venv}/') == 2 and jev.count('cli="${venv}/') == 2
    assert 'python="${venv}/Scripts/python.exe"' in jev and 'cli="${venv}/Scripts/jevdrill.exe"' in jev
    assert 'python="${venv}/bin/python"' in jev and 'cli="${venv}/bin/jevdrill"' in jev
    assert 'echo "python=$python" >> "$GITHUB_OUTPUT"' in jev and 'echo "cli=$cli" >> "$GITHUB_OUTPUT"' in jev
    for step in installed["steps"]:
        if step is not run_step:
            assert not {"JEVDRILL_TEST_PYTHON", "JEVDRILL_TEST_CLI"} & set(step.get("env") or {})


# --- PYTHONPATH -------------------------------------------------------------------------------------


@pytest.mark.parametrize("job", ["receipt", "installed"])
def test_pythonpath_is_computed_in_bash_from_runner_os(wf, job):
    step = _step(wf["jobs"][job], "Compute PYTHONPATH")
    assert step["shell"] == "bash"
    assert step["env"]["HOST_OS"] == "${{ runner.os }}"
    steps = wf["jobs"][job]["steps"]
    assert steps.index(step) < steps.index(_step(wf["jobs"][job], "classify"))


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash absent")
@pytest.mark.parametrize(
    "host_os, workspace, expected",
    [
        ("Linux", "/home/runner/work/r/r", "/home/runner/work/r/r/phase-loop-runtime/src:/home/runner/work/r/r/phase-loop-runtime/tests"),
        ("macOS", "/Users/runner/work/r/r", "/Users/runner/work/r/r/phase-loop-runtime/src:/Users/runner/work/r/r/phase-loop-runtime/tests"),
        ("Windows", r"D:\a\r\r", r"D:\a\r\r\phase-loop-runtime\src;D:\a\r\r\phase-loop-runtime\tests"),
    ],
)
def test_the_pythonpath_separator_rule(wf, tmp_path, host_os, workspace, expected):
    for job in ("receipt", "installed"):
        script = _step(wf["jobs"][job], "Compute PYTHONPATH")["run"]
        env_file = tmp_path / f"{job}.env"
        subprocess.run(
            ["bash", "-e", "-c", script],
            env={"HOST_OS": host_os, "WORKSPACE": workspace, "GITHUB_ENV": str(env_file), "PATH": "/usr/bin:/bin"},
            check=True, timeout=30,
        )
        assert env_file.read_text() == f"PYTHONPATH={expected}\n"


# --- the pytest and classifier invocations ---------------------------------------------------------


def _assert_suite_run(cmd: list[str], junit_var: str) -> None:
    assert cmd[6:12] == ["-q", "-rs", "-p", "no:cacheprovider", "-m", "not dotfiles_integration"]
    assert cmd[12] == f"--junitxml={junit_var}"
    assert cmd[13:] == [*TWELVE_ARGS, "||", "rc=$?"]
    assert "-n" not in cmd and not any(a.startswith(("-n", "--numprocesses", "--dist")) for a in cmd[6:13])


def test_the_receipt_invocation(wf):
    run = _step(wf["jobs"]["receipt"], "classify")
    assert run["working-directory"] == "phase-loop-runtime"
    assert run["env"] == {"LEG_OS": "${{ matrix.os_label }}", "LEG_TITLE": "${{ matrix.job_name }}"}
    pytests = _pytest_runs(run["run"])
    assert len(pytests) == 1
    _assert_suite_run(pytests[0], "$junit")
    lines = [line.strip() for line in run["run"].splitlines()]
    assert lines.index("rc=0") < next(i for i, line in enumerate(lines) if "-m pytest" in line)
    assert _classifier_runs(run["run"]) == [[
        "uv", "run", "--no-sync", "python", "scripts/jevdrill_receipt.py", "classify", "--leg", "receipt",
        "--os", "$LEG_OS", "--junit", "$junit", "--exit-code", "$rc", "--title", "$LEG_TITLE",
    ]]
    assert lines[-1].startswith("uv run --no-sync python scripts/jevdrill_receipt.py classify")


def test_the_installed_invocation(wf):
    run = _step(wf["jobs"]["installed"], "classify")
    assert run["working-directory"] == "phase-loop-runtime"
    pytests = _pytest_runs(run["run"])
    assert len(pytests) == 2
    collect, suite = pytests
    assert collect[6:] == ["-q", "-p", "no:cacheprovider", "--collect-only", "-m", "jevdrill_installed",
                           *TWELVE_ARGS, ">", "$collected"]
    _assert_suite_run(suite, "$junit")
    assert _classifier_runs(run["run"]) == [[
        "uv", "run", "--no-sync", "python", "scripts/jevdrill_receipt.py", "classify", "--leg", "installed",
        "--os", "$LEG_OS", "--junit", "$junit", "--exit-code", "$rc", "--collected", "$collected",
        "--title", "$LEG_TITLE",
    ]]
    lines = [line.strip() for line in run["run"].splitlines()]
    assert lines[-1].startswith("uv run --no-sync python scripts/jevdrill_receipt.py classify")


def test_the_suite_shell_is_bash_with_errexit(wf):
    assert wf["defaults"] == {"run": {"shell": "bash"}}
    for job in wf["jobs"].values():
        for step in job["steps"]:
            assert step.get("shell", "bash") == "bash"
            assert "continue-on-error" not in step


def test_the_classifier_exposes_the_allowlist_constant():
    assert list(R.SKIP_ALLOWLIST) == ["dotfiles_integration", "jevdrill_installed", "windows_only_files", "sched_unset"]
    assert sum(len(v) for v in R.SKIP_ALLOWLIST.values()) == 5
    assert set(R.WINDOWS_ONLY_REASON_FILES) == set(R.SKIP_ALLOWLIST["windows_only_files"])


@pytest.mark.parametrize(
    "path, reason",
    [
        ("conftest.py", "requires dotfiles tree (dotfiles_integration)"),
        ("test_phase_worktree_executor.py", "SCHED RED suite inactive; set PHASE_LOOP_TDD_EXPECT_SCHED=1"),
        ("test_windows_processes.py", 'reason="Native Windows Job Object proof"'),
        ("test_windows_storage.py", 'reason="Native NTFS storage proof"'),
        ("conftest.py", "jevdrill_installed: neither JEVDRILL_TEST_CLI nor JEVDRILL_TEST_PYTHON is set"),
    ],
)
def test_each_allowlisted_reason_is_the_string_its_source_emits(path, reason):
    source = TESTS / path
    assert source.is_file(), path
    assert reason in source.read_text(encoding="utf-8")


# --- actions and existing workflows ------------------------------------------------------------------


def _uses(node) -> list[str]:
    if isinstance(node, dict):
        return ([node["uses"]] if isinstance(node.get("uses"), str) else []) + [u for v in node.values() for u in _uses(v)]
    if isinstance(node, list):
        return [u for v in node for u in _uses(v)]
    return []


def test_actions_are_ones_the_repository_already_uses(wf):
    others = set()
    for path in WORKFLOWS.glob("*.yml"):
        if path != WORKFLOW:
            others.update(_uses(yaml.safe_load(path.read_text(encoding="utf-8"))))
    mine = set(_uses(wf))
    assert mine == {"actions/checkout@v4", "astral-sh/setup-uv@v6", "actions/upload-artifact@v4"}
    assert mine <= others
    for job in wf["jobs"].values():
        for step in job["steps"]:
            if step.get("uses") == "actions/checkout@v4":
                assert step["with"]["persist-credentials"] is False


COMPANION_ROW = ["A", ".github/workflows/jevdrill-companion.yml"]


def workflow_change_violations(base_has_companion: bool, name_status: list[str]) -> list[str]:
    """JEVHOST §8 [C4]: the phase adds the companion workflow and changes no existing one.

    A one-time check of this phase's own diff. It is live only while the comparison base
    does not yet hold the companion workflow, which is true on the phase branch before it
    merges, however often it is rebased. Once ``main`` holds the workflow, later pull
    requests may edit any workflow, the companion included, and nothing is reported.
    """
    if base_has_companion:
        return []
    return [line for line in name_status if line.split("\t") != COMPANION_ROW]


@pytest.mark.parametrize("base_has_companion,name_status,expected", [
    (False, ["A\t.github/workflows/jevdrill-companion.yml"], []),
    (False, ["A\t.github/workflows/jevdrill-companion.yml", "M\t.github/workflows/test.yml"],
     ["M\t.github/workflows/test.yml"]),
    (False, ["D\t.github/workflows/docs-audit.yml"], ["D\t.github/workflows/docs-audit.yml"]),
    # After the merge: a later pull request editing any workflow, the companion included.
    (True, ["M\t.github/workflows/docs-audit.yml"], []),
    (True, ["M\t.github/workflows/jevdrill-companion.yml"], []),
])
def test_workflow_change_rule_is_one_time(base_has_companion, name_status, expected):
    assert workflow_change_violations(base_has_companion, name_status) == expected


def _base_ref() -> str | None:
    for ref in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            base = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "merge-base", result.stdout.strip(), "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            if base.returncode == 0:
                return base.stdout.strip()
    return None


@pytest.mark.skipif(shutil.which("git") is None or not (REPO_ROOT / ".git").exists(), reason="no git checkout")
def test_no_existing_workflow_changed():
    base = _base_ref()
    if base is None:
        pytest.skip("no main ref to compare against in this checkout")
    changed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-status", base, "--", ".github/workflows"],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.splitlines()
    base_has_companion = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{base}:.github/workflows/jevdrill-companion.yml"],
        capture_output=True, timeout=30,
    ).returncode == 0
    assert workflow_change_violations(base_has_companion, changed) == []
