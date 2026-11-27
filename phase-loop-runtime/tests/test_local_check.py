"""`scripts/local_check.py` picks the tests a diff can reach (agent-harness#1029)."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local_check.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file(), reason="scripts/ is absent from the standalone consumer layout"
)


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("local_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pkg(tmp_path):
    root = tmp_path / "phase-loop-runtime"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_uses_a.py").write_text("from phase_loop_runtime.pkg.a import thing\n")
    (root / "tests" / "test_uses_a_leaf.py").write_text("from phase_loop_runtime.pkg import (\n    a,\n)\n")
    (root / "tests" / "test_uses_ab.py").write_text("import phase_loop_runtime.pkg.ab\n")
    (root / "tests" / "test_ci_x.py").write_text("")
    (root / "tests" / "test_own.py").write_text("")
    return root


def test_module_name(lc):
    assert lc.module_name("phase-loop-runtime/src/phase_loop_runtime/pkg/a.py") == "phase_loop_runtime.pkg.a"
    assert lc.module_name("phase-loop-runtime/src/phase_loop_runtime/pkg/__init__.py") == "phase_loop_runtime.pkg"
    assert lc.module_name("phase-loop-runtime/tests/test_x.py") is None


def test_a_changed_module_selects_its_importers_and_not_a_prefix_namesake(lc, pkg):
    tests, _ = lc.select(pkg, ["phase-loop-runtime/src/phase_loop_runtime/pkg/a.py"])
    # `pkg.ab` shares the prefix `pkg.a` but is a different module: it must not be picked.
    assert tests == ["tests/test_uses_a.py", "tests/test_uses_a_leaf.py"]


def test_a_changed_test_and_ci_plumbing(lc, pkg):
    tests, reasons = lc.select(pkg, ["phase-loop-runtime/tests/test_own.py", ".github/workflows/test.yml"])
    assert tests == ["tests/test_ci_x.py", "tests/test_own.py"]
    assert any("CI plumbing" in r for r in reasons)


def test_shared_config_runs_the_whole_suite(lc, pkg):
    tests, _ = lc.select(pkg, ["phase-loop-runtime/pyproject.toml"])
    assert tests is None


def test_parenthesised_multiline_leaf_import_is_seen(lc, pkg):
    """#1031 r1 (codex): `from phase_loop_runtime.pkg import (\n    a,\n)` imports pkg.a."""
    text = (pkg / "tests" / "test_uses_a_leaf.py").read_text()
    assert lc.imports_module(text, "phase_loop_runtime.pkg.a")
    assert lc.imports_module("def f():\n    import phase_loop_runtime.pkg.a\n", "phase_loop_runtime.pkg.a")
    assert not lc.imports_module("import phase_loop_runtime.pkg.ab\n", "phase_loop_runtime.pkg.a")
    tests, _ = lc.select(pkg, ["phase-loop-runtime/src/phase_loop_runtime/pkg/a.py"])
    assert "tests/test_uses_a_leaf.py" in tests


def _git(repo, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def test_a_rename_reports_both_endpoints(lc, tmp_path):
    """#1031 r1 (codex): importers of the OLD module path must still be selected."""
    _git(tmp_path, "init", "-q", "-b", "main")
    src = tmp_path / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "pkg"
    src.mkdir(parents=True)
    (src / "a.py").write_text("value = 1\n" * 20)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "mv", str(src / "a.py"), str(src / "b.py"))
    files = lc.changed_files(tmp_path, "main")
    assert "phase-loop-runtime/src/phase_loop_runtime/pkg/a.py" in files
    assert "phase-loop-runtime/src/phase_loop_runtime/pkg/b.py" in files


def test_the_venv_cache_key_tracks_project_metadata(lc, tmp_path):
    (tmp_path / "phase-loop-runtime").mkdir()
    pyproject = tmp_path / "phase-loop-runtime" / "pyproject.toml"
    pyproject.write_text('requires-python = ">=3.10"\n')
    before = lc.cache_key(tmp_path)
    pyproject.write_text('requires-python = ">=3.11"\n')
    assert lc.cache_key(tmp_path) != before


def test_no_linter_is_not_a_pass(lc, monkeypatch, capsys):
    monkeypatch.setattr(lc.shutil, "which", lambda name: None if name == "uvx" else name)
    monkeypatch.setattr(lc, "changed_files", lambda repo, base: [])
    monkeypatch.setenv("LOCAL_CHECK_PYTHON", lc.sys.executable)
    assert lc.main([]) == 1
    assert "FAIL" in capsys.readouterr().out


WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml"


@pytest.mark.skipif(not WORKFLOW.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_the_ci_mirrors_match_the_workflow(lc):
    """RUFF_PIN and CI_TEST_DEPS are copied from test.yml by hand; keep them honest."""
    text = WORKFLOW.read_text()
    assert f"'{lc.RUFF_PIN}'" in text
    install = next(line for line in text.splitlines() if "pip install \"./phase-loop-runtime[visual,claude-sdk,grok-catalog]\"" in line)
    for dep in lc.CI_TEST_DEPS:
        assert (f'"{dep}"' if dep != "pytest" else " pytest ") in install, dep


def test_changed_files_handles_odd_paths(lc, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "keep.txt").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / 'we"ird é.py').write_text("x")
    raw = os.fsdecode(b"review-\xff.txt")  # not valid UTF-8 (#1031 r2 codex)
    try:
        (tmp_path / raw).write_text("example\n")
    except OSError:  # macOS: HFS+/APFS reject names that are not valid UTF-8 (#1031 r3)
        raw = None
    assert lc.changed_files(tmp_path, "main") == sorted(p for p in (raw, 'we"ird é.py') if p)


def test_a_changed_script_selects_the_tests_that_name_it(lc, pkg):
    (pkg / "tests" / "test_runs_tool.py").write_text('SCRIPT = ROOT / "scripts" / "tool.py"\n')
    tests, _ = lc.select(pkg, ["phase-loop-runtime/scripts/tool.py"])
    assert tests == ["tests/test_runs_tool.py"]


def test_an_unparsable_importer_fails_open(lc):
    """#1031 r2 (claude): a host Python older than the test's syntax must not drop it."""
    newer = "match x:\n    case 1: pass\nfrom phase_loop_runtime.foo import f\n"
    if lc.imported_modules(newer) is None:  # host cannot parse `match`
        assert lc.imports_module(newer, "phase_loop_runtime.foo")
    assert lc.imports_module("def (:\nimport phase_loop_runtime.foo\n", "phase_loop_runtime.foo")
    assert lc.imports_module("\ufeffimport phase_loop_runtime.foo\n", "phase_loop_runtime.foo")
    assert lc.imports_module("x = '\\0'\0\nimport phase_loop_runtime.foo\n", "phase_loop_runtime.foo")


def test_the_clean_env_has_a_ci_runners_system_path(lc):
    """agent-harness#1036: sandbox tests need sbin (iptables); a CI runner has it."""
    env = lc.clean_env("/opt/venv/bin/python")
    dirs = env["PATH"].split(":")
    assert dirs[0] == "/opt/venv/bin"
    assert {"/usr/sbin", "/sbin", "/usr/bin", "/bin"} <= set(dirs)
    assert not any(d.startswith(str(lc.Path.home())) for d in dirs), "no user dirs"


def test_the_legible_files_run_from_a_copied_tree_like_ci(lc, tmp_path):
    """agent-harness#1057: CI runs these two files from a copy of tests/ with no .git (their
    live GitHub probes skip there); local_check must do the same, not run them in-checkout."""
    pkg = tmp_path / "phase-loop-runtime"
    (pkg / "tests").mkdir(parents=True)
    (pkg / "tests" / "test_legible_evidence.py").write_text("")
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "phase-plans-v10.md").write_text("roadmap")
    (tmp_path / ".git").mkdir()
    argv, cwd, env = lc.copied_tree_run(tmp_path, pkg, "/py", ["tests/test_legible_evidence.py"])
    assert not any((d / ".git").exists() for d in (cwd, *cwd.parents)), "the copy must sit outside any repo"
    assert (cwd.parent / "specs" / "phase-plans-v10.md").read_text() == "roadmap"
    assert argv[-1] == str(cwd / "tests" / "test_legible_evidence.py")
    assert env["PYTHONPATH"].split(os.pathsep) == [str(cwd / "tests"), str(pkg / "src")]


@pytest.mark.skipif(not WORKFLOW.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_the_copied_tree_files_are_the_ones_ci_ignores(lc):
    text = WORKFLOW.read_text()
    for rel in lc.SUITE_IGNORES:
        assert f"--ignore {rel}" in text, rel
        # ...and CI's copied-tree step runs exactly that file from the copy.
        assert f'"$suite_root/{rel}"' in text, rel


@pytest.mark.parametrize("selected,copied_code,expected", [
    (None, 5, 1),                                        # full suite: CI would fail on 5
    (["tests/test_legible_evidence.py",
      "tests/test_legible_roadmap_contract.py"], 5, 1),  # both files = CI's whole copied step
    (["tests/test_legible_evidence.py"], 5, 0),          # a strict subset may collect nothing
    (None, 1, 1),                                        # a real copied failure always fails
    (None, 0, 0),
])
def test_the_copied_run_exit_code_is_aggregated(lc, monkeypatch, tmp_path, selected, copied_code, expected):
    """#1059 r1 (codex, grok, claude): exit 5 from the copied run must not turn a full-suite
    run into PASS. Drives main() with lint 0, main run 0, copied run ``copied_code``."""
    monkeypatch.setattr(lc, "is_shared_host", lambda *a, **k: (False, None))
    monkeypatch.setattr(lc, "changed_files", lambda repo, base: ["x"])
    monkeypatch.setattr(lc, "select", lambda pkg_root, files: (selected, ["test"]))
    monkeypatch.setattr(lc, "check_python", lambda repo: lc.sys.executable)
    monkeypatch.setattr(lc, "copied_tree_run", lambda *a: (["copied"], tmp_path, {}))
    # Hermetic: a linter must be "available" whatever the host has (CI runners have no uvx,
    # and a missing linter is itself a FAIL).
    monkeypatch.setattr(lc.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(cmd, *args, **kwargs):
        rc = copied_code if cmd == ["copied"] else 0
        if cmd[:2] == ["bash", str(Path(lc.__file__).resolve().parents[2] / "ci" / "chronology-scope.sh")]:
            return subprocess.CompletedProcess(cmd, 0, "tests/x.py::test_node\n", "")
        return subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(lc.subprocess, "run", run)
    assert lc.main(["--full"] if selected is None else []) == expected


def _stub_main_env(lc, monkeypatch, *, selected, shared, has_xdist=True):
    recorded: list[list[str]] = []
    monkeypatch.setattr(lc, "is_shared_host", lambda *a, **k: shared)
    monkeypatch.setattr(lc, "changed_files", lambda repo, base: ["phase-loop-runtime/tests/test_x.py"])
    monkeypatch.setattr(lc, "select", lambda pkg_root, files: (selected, ["stub"]))
    monkeypatch.setattr(lc, "check_python", lambda repo: lc.sys.executable)
    monkeypatch.setattr(lc.shutil, "which", lambda name: f"/usr/bin/{name}")
    for var in (
        lc.SHARED_HOST_ENV,
        lc.WORKERS_ENV,
        lc.OVERRIDE_ENV,
        lc.CPU_LIMIT_ENV,
        lc.MEMORY_LIMIT_GIB_ENV,
    ):
        monkeypatch.delenv(var, raising=False)

    def run(cmd, *args, **kwargs):
        if cmd[1:3] == ["-c", "import sys; print(sys.version.split()[0])"]:
            return subprocess.CompletedProcess(cmd, 0, "3.12.0\n", "")
        if cmd[1:3] == ["-c", "import xdist"]:
            return subprocess.CompletedProcess(cmd, 0 if has_xdist else 1, "", "")
        if cmd[:2] == ["bash", str(Path(lc.__file__).resolve().parents[2] / "ci" / "chronology-scope.sh")]:
            return subprocess.CompletedProcess(cmd, 0, "tests/x.py::test_node\n", "")
        recorded.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(lc.subprocess, "run", run)
    return recorded


def test_is_shared_host_marker_wins_and_env_opts_in(lc, tmp_path):
    marker = tmp_path / "team-host"
    assert lc.is_shared_host({}, marker=marker) == (False, None)
    assert lc.is_shared_host({lc.SHARED_HOST_ENV: "0"}, marker=marker) == (False, None)
    shared, reason = lc.is_shared_host({lc.SHARED_HOST_ENV: "1"}, marker=marker)
    assert shared and lc.SHARED_HOST_ENV in (reason or "")
    marker.write_text("team\n")
    # Setting LOCAL_CHECK_SHARED_HOST=0 cannot bypass /etc/consiliency/team-host.
    shared_marker, reason_marker = lc.is_shared_host({lc.SHARED_HOST_ENV: "0"}, marker=marker)
    assert shared_marker and str(marker) in (reason_marker or "")


def test_default_workers_capped_at_two_never_auto_and_printed(lc, monkeypatch, capsys):
    recorded = _stub_main_env(
        lc, monkeypatch, selected=["tests/test_x.py"], shared=(False, None), has_xdist=True
    )
    assert lc.main([]) == 0
    out = capsys.readouterr().out
    assert "workers: 2 (xdist, --dist loadfile)" in out
    pytest_cmds = [cmd for cmd in recorded if "-m" in cmd and "pytest" in cmd]
    assert len(pytest_cmds) == 1
    assert ["-n", "2", "--dist", "loadfile", "--max-worker-restart=0"] == pytest_cmds[0][
        pytest_cmds[0].index("-n") : pytest_cmds[0].index("-n") + 5
    ]
    assert "auto" not in pytest_cmds[0]


def test_workers_zero_runs_serial_and_auto_is_refused(lc, monkeypatch, capsys):
    recorded = _stub_main_env(
        lc, monkeypatch, selected=["tests/test_x.py"], shared=(True, "team-host"), has_xdist=True
    )
    assert lc.main(["--workers", "0"]) == 0
    out = capsys.readouterr().out
    assert "workers: 0 (serial, -n 0)" in out
    pytest_cmds = [cmd for cmd in recorded if "-m" in cmd and "pytest" in cmd]
    assert len(pytest_cmds) == 1
    assert ["-n", "0"] == pytest_cmds[0][pytest_cmds[0].index("-n") : pytest_cmds[0].index("-n") + 2]

    recorded.clear()
    assert lc.main(["--workers", "auto"]) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "auto" in err
    assert recorded == []


@pytest.mark.parametrize("argv,selected", [
    (["--full"], ["tests/test_x.py"]),
    ([], None),
])
def test_shared_host_refuses_full_suite_by_default(lc, monkeypatch, capsys, argv, selected):
    recorded = _stub_main_env(
        lc, monkeypatch, selected=selected, shared=(True, "team-host marker"), has_xdist=True
    )
    # Must refuse before check_python/venv provisioning or pytest launch.
    monkeypatch.setattr(lc, "check_python", lambda _repo: (_ for _ in ()).throw(AssertionError("check_python reached")))
    assert lc.main(argv) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "hosted CI" in err and "Gate A" in err
    assert recorded == []


def test_shared_host_caps_workers_unless_owner_override_with_limits(lc, monkeypatch, capsys, tmp_path):
    recorded = _stub_main_env(
        lc, monkeypatch, selected=["tests/test_x.py"], shared=(True, "team-host marker"), has_xdist=True
    )
    monkeypatch.setattr(lc, "copied_tree_run", lambda *a: (["copied"], tmp_path, {}))

    # Without override, >2 workers is refused.
    assert lc.main(["--workers", "4"]) == 2
    assert "shared-host cap of 2" in capsys.readouterr().err
    assert recorded == []

    # Override without both CPU and memory limits is refused.
    assert lc.main(["--full", "--allow-shared-host-override"]) == 2
    err = capsys.readouterr().err
    assert "--cpu-limit" in err and "--memory-limit-gib" in err

    assert lc.main(["--full", "--allow-shared-host-override", "--cpu-limit", "4", "--memory-limit-gib", "nan"]) == 2
    assert "memory-limit-gib" in capsys.readouterr().err

    # Override with stated CPU and memory limits allows --full up to --cpu-limit.
    assert lc.main([
        "--full",
        "--workers",
        "4",
        "--allow-shared-host-override",
        "--cpu-limit",
        "4",
        "--memory-limit-gib",
        "8",
    ]) == 0
    out = capsys.readouterr().out
    assert "owner override active (cpu_limit=4, memory_limit_gib=8)" in out
    assert "workers: 4 (xdist, --dist loadfile)" in out
    pytest_cmds = [cmd for cmd in recorded if "-m" in cmd and "pytest" in cmd]
    assert len(pytest_cmds) == 1
    assert ["-n", "4"] == pytest_cmds[0][pytest_cmds[0].index("-n") : pytest_cmds[0].index("-n") + 2]

    # Exceeding the override's own --cpu-limit is still refused.
    recorded.clear()
    assert lc.main([
        "--workers",
        "5",
        "--allow-shared-host-override",
        "--cpu-limit",
        "4",
        "--memory-limit-gib",
        "8",
    ]) == 2
    assert "exceeds the override --cpu-limit of 4" in capsys.readouterr().err
    assert recorded == []

    # An override with --cpu-limit 1 and no explicit --workers clamps the default to 1.
    assert lc.main([
        "--full",
        "--allow-shared-host-override",
        "--cpu-limit",
        "1",
        "--memory-limit-gib",
        "4",
    ]) == 0
    assert "workers: 1 (xdist, --dist loadfile)" in capsys.readouterr().out
