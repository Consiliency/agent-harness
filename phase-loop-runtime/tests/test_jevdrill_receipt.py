"""The JEV Drill receipt classifier (JEVHOST §8, [N-RC]) on synthetic junit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jevdrill_receipt.py"
HARNESS_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jevdrill"


def _load():
    spec = importlib.util.spec_from_file_location("jevdrill_receipt", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Gate A's standalone-from-wheel clean room checks out tests/ without the repository's
# CI scripts and workflows; this CI-side classifier is tested only in the repository.
if not SCRIPT.is_file():
    pytest.skip("repository source absent from the standalone-from-wheel layout",
                allow_module_level=True)

R = _load()

BOTH = frozenset(R.JEVDRILL_VARIABLES)
RECEIPT_LINUX = R.Leg("receipt", "linux")
RECEIPT_MACOS = R.Leg("receipt", "macos")
RECEIPT_WINDOWS = R.Leg("receipt", "windows")
INSTALLED_LINUX = R.Leg("installed", "linux", BOTH)
INSTALLED_WINDOWS = R.Leg("installed", "windows", BOTH)
DOTFILES, = R.SKIP_ALLOWLIST["dotfiles_integration"]
JOB_OBJECT, NTFS = R.SKIP_ALLOWLIST["windows_only_files"]
SCHED, = R.SKIP_ALLOWLIST["sched_unset"]
ROUTE = "test_jevdrill_adapter.py::test_real_jevdrill_cli_route_and_durable_reports"
PARAMETRIZED_INSTALLED = (
    "test_jevdrill_discovery.py::test_entered_linked_launch_rejections[forged]",
    "test_jevdrill_discovery.py::test_installed_discovery_status_gates_planning[needs_context]",
)
EXPECTED_INSTALLED = [*R.INSTALLED_CONTROLS, ROUTE, *PARAMETRIZED_INSTALLED]


# --- synthetic junit --------------------------------------------------------------------


def _case(node_id: str, outcome: str = "passed", reason: str = "", kind: str = "pytest.skip") -> str:
    """A junit testcase in pytest's own shape for a node ID relative to tests/."""
    path, *rest = node_id.split("::")
    classname = ".".join(["tests", path[:-3].replace("/", "."), *rest[:-1]])
    head = f"<testcase classname={quoteattr(classname)} name={quoteattr(rest[-1])} time=\"0.01\""
    if outcome == "passed":
        return head + " />"
    if outcome == "skipped":
        return head + f"><skipped type={quoteattr(kind)} message={quoteattr(reason)}>{path}:1: {reason}</skipped></testcase>"
    return head + f"><{outcome} message=\"boom\">trace</{outcome}></testcase>"


def _junit(tmp_path: Path, cases: list[str]) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        f'tests="{len(cases)}">' + "".join(cases) + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def _complete(leg, overrides: dict | None = None, extra: list | None = None) -> list[str]:
    """A complete run for ``leg``: every file, every control at its required outcome."""
    rows: dict[str, tuple] = {}
    for name in R.TWELVE_FILES:
        rows[f"{name}::test_generic_{name[5:-3]}"] = ("passed",)
    if leg.os != "windows":
        rows["test_windows_processes.py::test_generic_windows_processes"] = ("skipped", JOB_OBJECT)
        rows["test_windows_storage.py::test_generic_windows_storage"] = ("skipped", NTFS)
    for node in R.NON_INSTALLED_CONTROLS:
        rows[node] = ("passed",)
    installed = [*R.INSTALLED_CONTROLS, ROUTE, *PARAMETRIZED_INSTALLED]
    for node in installed:
        rows[node] = ("passed",) if leg.kind == "installed" else ("skipped", R.JEVDRILL_INSTALLED_REASON)
    rows.update(overrides or {})
    return [_case(node, *spec) for node, spec in rows.items() if spec is not None] + list(extra or [])


def _classify(tmp_path, leg, cases, exit_code=0, expected=None):
    if expected is None and leg.kind == "installed":
        expected = EXPECTED_INSTALLED
    return R.classify(R.read_junit(_junit(tmp_path, cases)), leg, exit_code, expected)


def _passes(tmp_path, leg, cases, **kw) -> bool:
    return _classify(tmp_path, leg, cases, **kw).passed


# --- the baselines ----------------------------------------------------------------------


@pytest.mark.parametrize("leg", [RECEIPT_LINUX, RECEIPT_MACOS, RECEIPT_WINDOWS, INSTALLED_LINUX, INSTALLED_WINDOWS])
def test_a_complete_clean_run_passes(tmp_path, leg):
    report = _classify(tmp_path, leg, _complete(leg))
    assert report.passed, report.failures


def test_the_allowlist_is_exactly_four_reasons():
    assert list(R.SKIP_ALLOWLIST) == ["dotfiles_integration", "jevdrill_installed", "windows_only_files", "sched_unset"]
    assert R.SKIP_ALLOWLIST["jevdrill_installed"] == (
        "jevdrill_installed: neither JEVDRILL_TEST_CLI nor JEVDRILL_TEST_PYTHON is set",
    )
    assert R.SKIP_ALLOWLIST["windows_only_files"] == ("Native Windows Job Object proof", "Native NTFS storage proof")
    assert SCHED == "SCHED RED suite inactive; set PHASE_LOOP_TDD_EXPECT_SCHED=1"


# --- each allowance passes only on its allowed legs --------------------------------------


EXTRA = "test_jevdrill_input.py::test_extra_row"


@pytest.mark.parametrize("leg", [RECEIPT_LINUX, RECEIPT_WINDOWS, INSTALLED_LINUX, INSTALLED_WINDOWS])
def test_dotfiles_integration_is_allowed_on_every_leg(tmp_path, leg):
    assert _passes(tmp_path, leg, _complete(leg, {EXTRA: ("skipped", DOTFILES)}))


def test_jevdrill_installed_reason_passes_with_neither_variable(tmp_path):
    assert _passes(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {EXTRA: ("skipped", R.JEVDRILL_INSTALLED_REASON)}))


@pytest.mark.parametrize("variables", [frozenset({"JEVDRILL_TEST_CLI"}), frozenset({"JEVDRILL_TEST_PYTHON"}), BOTH])
def test_a_jevdrill_installed_skip_with_a_variable_set_fails(tmp_path, variables):
    leg = R.Leg("installed", "linux", variables)
    report = _classify(tmp_path, leg, _complete(INSTALLED_LINUX, {EXTRA: ("skipped", R.JEVDRILL_INSTALLED_REASON)}))
    assert not report.passed
    assert any(EXTRA in f and "not allowed on this leg" in f for f in report.failures), report.failures


@pytest.mark.parametrize("variable", R.JEVDRILL_VARIABLES)
def test_the_receipt_leg_with_a_variable_set_fails(tmp_path, variable):
    leg = R.Leg("receipt", "linux", frozenset({variable}))
    report = _classify(tmp_path, leg, _complete(RECEIPT_LINUX))
    assert not report.passed
    assert any("must set neither" in f for f in report.failures)
    # Its installed skips are no longer allowed either.
    assert any("not allowed on this leg" in f for f in report.failures)


@pytest.mark.parametrize("leg", [RECEIPT_LINUX, RECEIPT_MACOS, INSTALLED_LINUX])
def test_windows_only_reasons_pass_off_windows(tmp_path, leg):
    assert _passes(tmp_path, leg, _complete(leg))


@pytest.mark.parametrize("leg", [RECEIPT_WINDOWS, INSTALLED_WINDOWS])
@pytest.mark.parametrize(
    "node, reason",
    [
        ("test_windows_processes.py::test_generic_windows_processes", JOB_OBJECT),
        ("test_windows_storage.py::test_generic_windows_storage", NTFS),
    ],
)
def test_windows_only_reasons_fail_on_windows(tmp_path, leg, node, reason):
    report = _classify(tmp_path, leg, _complete(leg, {node: ("skipped", reason)}))
    assert not report.passed
    assert any(node in f and "not allowed" in f for f in report.failures), report.failures


def test_a_windows_only_reason_outside_its_file_fails(tmp_path):
    report = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {EXTRA: ("skipped", NTFS)}))
    assert not report.passed


def test_sched_reason_passes_only_where_sched_is_unset(tmp_path):
    cases = _complete(RECEIPT_LINUX, {EXTRA: ("skipped", SCHED)})
    assert _passes(tmp_path, R.Leg("receipt", "linux", sched_set=False), cases)
    assert not _passes(tmp_path, R.Leg("receipt", "linux", sched_set=True), cases)
    installed = _complete(INSTALLED_LINUX, {EXTRA: ("skipped", SCHED)})
    assert _passes(tmp_path, R.Leg("installed", "linux", BOTH, sched_set=False), installed)
    assert not _passes(tmp_path, INSTALLED_LINUX, installed)


@pytest.mark.parametrize(
    "reason",
    [
        "requires a network",
        "Skipped: requires dotfiles tree (dotfiles_integration)",
        R.JEVDRILL_INSTALLED_REASON + " ",
        "native windows job object proof",
        "",
    ],
)
def test_an_unknown_reason_fails(tmp_path, reason):
    report = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {EXTRA: ("skipped", reason)}))
    assert not report.passed
    assert any("outside the allowlist" in f for f in report.failures), report.failures


def test_an_xfail_is_not_an_allowed_skip(tmp_path):
    cases = _complete(RECEIPT_LINUX, extra=[_case(EXTRA, "skipped", DOTFILES, kind="pytest.xfail")])
    assert not _passes(tmp_path, RECEIPT_LINUX, cases)


# --- failures and errors ------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["failure", "error"])
@pytest.mark.parametrize("leg", [RECEIPT_LINUX, INSTALLED_LINUX])
def test_a_failure_or_an_error_fails(tmp_path, leg, outcome):
    report = _classify(tmp_path, leg, _complete(leg, {EXTRA: (outcome,)}))
    assert not report.passed
    assert f"{EXTRA}: {outcome}" in report.failures


def test_a_teardown_error_on_a_passing_row_fails(tmp_path):
    cases = _complete(RECEIPT_LINUX, extra=[_case(R.NON_INSTALLED_CONTROLS[0], "error")])
    report = _classify(tmp_path, RECEIPT_LINUX, cases)
    assert not report.passed
    assert any(R.NON_INSTALLED_CONTROLS[0] in f and "control is error" in f for f in report.failures)


# --- the installed leg --------------------------------------------------------------------


@pytest.mark.parametrize("node", EXPECTED_INSTALLED)
def test_an_expected_installed_node_missing_fails(tmp_path, node):
    report = _classify(tmp_path, INSTALLED_LINUX, _complete(INSTALLED_LINUX, {node: None}))
    assert not report.passed
    assert any(node in f and "missing" in f for f in report.failures), report.failures


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped"])
@pytest.mark.parametrize("node", [ROUTE, *PARAMETRIZED_INSTALLED])
def test_an_expected_installed_node_not_passed_fails(tmp_path, node, outcome):
    spec = ("skipped", DOTFILES) if outcome == "skipped" else (outcome,)
    report = _classify(tmp_path, INSTALLED_LINUX, _complete(INSTALLED_LINUX, {node: spec}))
    assert not report.passed
    assert any(node in f for f in report.failures), report.failures


def test_an_installed_skip_fails_even_with_an_allowlisted_reason(tmp_path):
    node = PARAMETRIZED_INSTALLED[0]
    report = _classify(tmp_path, INSTALLED_LINUX, _complete(INSTALLED_LINUX, {node: ("skipped", DOTFILES)}))
    assert any("jevdrill_installed item skipped on the installed leg" in f for f in report.failures)


def test_the_installed_leg_needs_a_collected_set_holding_the_installed_controls(tmp_path):
    cases = _complete(INSTALLED_LINUX)
    assert not _classify(tmp_path, INSTALLED_LINUX, cases, expected=[]).passed
    partial = [n for n in EXPECTED_INSTALLED if n != R.INSTALLED_CONTROLS[1]]
    report = _classify(tmp_path, INSTALLED_LINUX, cases, expected=partial)
    assert any("not in the collected jevdrill_installed set" in f for f in report.failures)


def test_the_installed_leg_must_set_both_variables(tmp_path):
    leg = R.Leg("installed", "linux", frozenset({"JEVDRILL_TEST_PYTHON"}))
    report = _classify(tmp_path, leg, _complete(INSTALLED_LINUX))
    assert any("must set both" in f for f in report.failures)


def test_the_collected_set_is_read_from_collect_only_output():
    text = textwrap.dedent(
        """\
        tests/test_jevdrill_adapter.py::test_real_jevdrill_cli_route_and_durable_reports
        tests/test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[alpha]
        tests/test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[beta]
        tests/test_jevdrill_discovery.py::test_entered_linked_launch_rejections[stale_catalog]

        4/900 tests collected (896 deselected) in 1.20s
        """
    )
    assert R.parse_collected(text) == [
        ROUTE,
        R.INSTALLED_CONTROLS[0],
        R.INSTALLED_CONTROLS[1],
        "test_jevdrill_discovery.py::test_entered_linked_launch_rejections[stale_catalog]",
    ]
    assert R.parse_collected("phase-loop-runtime/tests/test_windows_storage.py::test_w[bad\\\\name]\n") == [
        "test_windows_storage.py::test_w[bad\\\\name]"
    ]
    assert R.parse_collected("\n5 tests collected\n") == []
    with pytest.raises(ValueError):
        R.parse_collected("ERROR tests/test_x.py - ImportError\n")


# --- [N-RC] an empty or partial run --------------------------------------------------------


@pytest.mark.parametrize("leg", [RECEIPT_LINUX, INSTALLED_LINUX])
def test_an_empty_run_fails(tmp_path, leg):
    report = _classify(tmp_path, leg, [])
    assert not report.passed
    assert any("empty run" in f for f in report.failures)


@pytest.mark.parametrize("name", R.TWELVE_FILES)
def test_each_of_the_twelve_files_must_contribute_a_testcase(tmp_path, name):
    cases = [c for c in _complete(RECEIPT_LINUX) if f'classname="tests.{name[:-3]}"' not in c]
    report = _classify(tmp_path, RECEIPT_LINUX, cases)
    assert not report.passed
    assert f"{name}: contributed no testcase (partial run)" in report.failures


@pytest.mark.parametrize("node", [*R.NON_INSTALLED_CONTROLS, *R.INSTALLED_CONTROLS])
def test_each_control_must_appear_by_node_id(tmp_path, node):
    report = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {node: None}))
    assert f"{node}: control missing from the junit" in report.failures


@pytest.mark.parametrize("node", R.NON_INSTALLED_CONTROLS)
def test_a_non_installed_control_must_pass(tmp_path, node):
    report = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {node: ("skipped", DOTFILES)}))
    assert f"{node}: control is skipped, expected passed" in report.failures


@pytest.mark.parametrize("node", R.INSTALLED_CONTROLS)
def test_an_installed_control_on_the_receipt_leg_must_skip_with_the_fixed_reason(tmp_path, node):
    passed = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {node: ("passed",)}))
    assert f"{node}: control is passed, expected skipped" in passed.failures
    other = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX, {node: ("skipped", DOTFILES)}))
    assert any(node in f and "without the fixed reason" in f for f in other.failures)


def test_a_parametrized_control_is_bound_by_its_id(tmp_path):
    alpha, beta = R.INSTALLED_CONTROLS[:2]
    cases = _complete(RECEIPT_LINUX, {beta: None}, extra=[_case(alpha, "skipped", R.JEVDRILL_INSTALLED_REASON)])
    assert f"{beta}: control missing from the junit" in _classify(tmp_path, RECEIPT_LINUX, cases).failures


@pytest.mark.parametrize("exit_code", [1, 2, 3, 4, 5, 137])
def test_a_nonzero_pytest_exit_fails_whatever_the_junit_says(tmp_path, exit_code):
    report = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX), exit_code=exit_code)
    assert not report.passed
    assert any(f"pytest exited {exit_code}" in f for f in report.failures)


# --- node IDs from junit --------------------------------------------------------------------


@pytest.mark.parametrize(
    "classname, name, node",
    [
        ("tests.test_jevdrill_queue", "test_a", "test_jevdrill_queue.py::test_a"),
        ("phase-loop-runtime.tests.test_jevdrill_queue", "test_a", "test_jevdrill_queue.py::test_a"),
        ("tests.test_phase_loop_launcher.PhaseLoopLauncherTest", "test_b", "test_phase_loop_launcher.py::PhaseLoopLauncherTest::test_b"),
        ("tests.test_x.TestOuter.TestInner", "test_c[a.b-1]", "test_x.py::TestOuter::TestInner::test_c[a.b-1]"),
        ("tests.sub.test_y", "test_d[alpha]", "sub/test_y.py::test_d[alpha]"),
        ("test_z", "test_e", "test_z.py::test_e"),
    ],
)
def test_junit_rows_map_back_to_node_ids(classname, name, node):
    assert R.junit_node_id(classname, name) == node


def test_real_pytest_junit_maps_to_its_collected_node_ids(tmp_path):
    """pytest's own junit and --collect-only agree through the classifier's mapping."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tests / "test_sample.py").write_text(
        textwrap.dedent(
            """\
            import pytest

            @pytest.mark.parametrize("objective", ["alpha", "beta", "a.b", "x::y", "bad\\\\name"])
            def test_param(objective):
                pass

            class TestGroup:
                @pytest.mark.parametrize("n", [1, 2])
                def test_method(self, n):
                    pass

                def test_skipped(self):
                    pytest.skip("requires dotfiles tree (dotfiles_integration)")
            """
        ),
        encoding="utf-8",
    )
    base = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", "--rootdir", str(tmp_path)]
    collected = subprocess.run(
        [*base, "-q", "--collect-only", "tests/test_sample.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=True,
    ).stdout
    junit = tmp_path / "out.xml"
    subprocess.run(
        [*base, "-q", f"--junitxml={junit}", "tests/test_sample.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=True,
    )
    expected = R.parse_collected(collected)
    rows = R.read_junit(junit)
    assert len(expected) == 8
    assert "test_sample.py::test_param[bad\\\\name]" in expected
    assert sorted(node for node, _, _ in rows) == sorted(expected)
    assert ("test_sample.py::TestGroup::test_skipped", "skipped", DOTFILES) in rows
    assert "test_sample.py::test_param[a.b]" in expected


# --- the summary and the CLI ---------------------------------------------------------------


def test_the_summary_lists_every_skip_with_node_id_and_reason(tmp_path):
    report = _classify(tmp_path, RECEIPT_LINUX, _complete(RECEIPT_LINUX))
    text = R.render_summary(report, RECEIPT_LINUX)
    assert "PASS" in text
    for node in R.INSTALLED_CONTROLS:
        assert f"| `{node}` | {R.JEVDRILL_INSTALLED_REASON} |" in text
    assert f"| `test_windows_storage.py::test_generic_windows_storage` | {NTFS} |" in text


def _cli(tmp_path, monkeypatch, cases, *args, env=None):
    junit = _junit(tmp_path, cases)
    summary = tmp_path / "summary.md"
    for name in R.JEVDRILL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PHASE_LOOP_TDD_EXPECT_SCHED", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    code = R.main(["classify", "--junit", str(junit), "--os", R.host_os(), *args])
    return code, summary.read_text(encoding="utf-8") if summary.exists() else ""


def test_cli_receipt_pass_writes_the_step_summary(tmp_path, monkeypatch):
    leg = R.Leg("receipt", R.host_os())
    code, summary = _cli(tmp_path, monkeypatch, _complete(leg), "--leg", "receipt", "--exit-code", "0")
    assert code == 0
    assert R.JEVDRILL_INSTALLED_REASON in summary and "PASS" in summary


def test_cli_hands_the_pytest_exit_code_to_the_verdict(tmp_path, monkeypatch):
    leg = R.Leg("receipt", R.host_os())
    code, summary = _cli(tmp_path, monkeypatch, _complete(leg), "--leg", "receipt", "--exit-code", "5")
    assert code == 1 and "pytest exited 5" in summary


def test_cli_reads_the_variables_from_the_environment(tmp_path, monkeypatch):
    leg = R.Leg("receipt", R.host_os())
    code, summary = _cli(
        tmp_path, monkeypatch, _complete(leg), "--leg", "receipt", "--exit-code", "0",
        env={"JEVDRILL_TEST_CLI": "/opt/jev/bin/jevdrill"},
    )
    assert code == 1 and "must set neither" in summary


def test_cli_installed_leg(tmp_path, monkeypatch):
    collected = tmp_path / "collected.txt"
    collected.write_text("".join(f"tests/{n}\n" for n in EXPECTED_INSTALLED) + "\n7 tests collected\n", encoding="utf-8")
    leg = R.Leg("installed", R.host_os(), BOTH)
    env = {"JEVDRILL_TEST_CLI": "/x/bin/jevdrill", "JEVDRILL_TEST_PYTHON": "/x/bin/python"}
    args = ("--leg", "installed", "--exit-code", "0", "--collected", str(collected))
    assert _cli(tmp_path, monkeypatch, _complete(leg), *args, env=env)[0] == 0
    missing = _complete(leg, {PARAMETRIZED_INSTALLED[1]: None})
    assert _cli(tmp_path, monkeypatch, missing, *args, env=env)[0] == 1
    assert R.main(["classify", "--junit", str(tmp_path / "junit.xml"), "--os", R.host_os(),
                   "--leg", "installed", "--exit-code", "0"]) == 2


def test_cli_refuses_a_mislabelled_os_and_a_missing_junit(tmp_path):
    other = next(o for o in R.OSES if o != R.host_os())
    junit = _junit(tmp_path, _complete(RECEIPT_LINUX))
    assert R.main(["classify", "--junit", str(junit), "--os", other, "--leg", "receipt", "--exit-code", "0"]) == 2
    assert R.main(["classify", "--junit", str(tmp_path / "nope.xml"), "--os", R.host_os(),
                   "--leg", "receipt", "--exit-code", "0"]) == 1


# --- compare-contract (JEVHOST §5) -----------------------------------------------------------


def _contract_pair(tmp_path):
    harness, jev = tmp_path / "harness", tmp_path / "jev"
    (jev / "schemas").mkdir(parents=True)
    (jev / "tests" / "contracts" / "fixtures").mkdir(parents=True)
    harness.mkdir()
    digests = {}
    for i in range(R.SCHEMA_COUNT):
        name = f"Schema{i:02d}.json"
        body = json.dumps({"$id": name, "n": i}).encode() + b"\n"
        (harness / name).write_bytes(body)
        (jev / "schemas" / name).write_bytes(body)
        digests[name] = hashlib.sha256(body).hexdigest()
    (harness / R.DIGESTS_NAME).write_text(json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name in R.FIXTURE_NAMES:
        theirs = b'{"rows": [{"counter": "utf8-bytes-upper-bound-v1"}, {"x": 1}]}\n'
        (jev / "tests" / "contracts" / "fixtures" / name).write_bytes(theirs)
        (harness / name).write_bytes(theirs.replace(R.COUNTER_LITERAL, R.COUNTER_PLACEHOLDER))
    return harness, jev


def test_compare_contract_passes_on_a_matching_checkout(tmp_path):
    harness, jev = _contract_pair(tmp_path)
    (jev / "schemas" / "Future.json").write_bytes(b"{}")
    problems, notes = R.compare_contract(jev, harness)
    assert problems == []
    assert any("Future.json" in n for n in notes)


def test_compare_contract_fails_on_one_changed_schema_byte(tmp_path):
    harness, jev = _contract_pair(tmp_path)
    target = jev / "schemas" / "Schema03.json"
    target.write_bytes(target.read_bytes().replace(b"3", b"4"))
    assert R.compare_contract(jev, harness)[0] == ["schemas/Schema03.json: bytes differ from the harness copy"]


def test_compare_contract_fails_on_a_removed_fixture_row(tmp_path):
    harness, jev = _contract_pair(tmp_path)
    (harness / "host.json").write_bytes(b'{"rows": [{"counter": "<jev-token-counter-revision>"}]}\n')
    problems = R.compare_contract(jev, harness)[0]
    assert problems == ["fixtures/host.json: differs from jevdrill's after the placeholder substitution"]


def test_compare_contract_fails_on_a_stale_digest_or_a_literal(tmp_path):
    harness, jev = _contract_pair(tmp_path)
    digests = json.loads((harness / R.DIGESTS_NAME).read_text())
    digests["Schema00.json"] = "0" * 64
    (harness / R.DIGESTS_NAME).write_text(json.dumps(digests))
    (harness / "discovery.json").write_bytes((jev / "tests" / "contracts" / "fixtures" / "discovery.json").read_bytes())
    problems = R.compare_contract(jev, harness)[0]
    assert any("digests.json: does not recompute (Schema00.json)" == p for p in problems)
    assert any("discovery.json: the harness copy holds the counter literal" in p for p in problems)


def test_compare_contract_fails_on_a_missing_jevdrill_file(tmp_path):
    harness, jev = _contract_pair(tmp_path)
    (jev / "schemas" / "Schema05.json").unlink()
    (jev / "tests" / "contracts" / "fixtures" / "route-inputs.json").unlink()
    problems = R.compare_contract(jev, harness)[0]
    assert "schemas/Schema05.json: absent from the jevdrill checkout" in problems
    assert "tests/contracts/fixtures/route-inputs.json: absent from the jevdrill checkout" in problems


@pytest.mark.skipif(not (HARNESS_FIXTURES / R.DIGESTS_NAME).is_file(), reason="harness jevdrill fixtures absent")
def test_compare_contract_accepts_the_harness_copies_against_their_own_reverse_substitution(tmp_path):
    jev = tmp_path / "jev"
    (jev / "schemas").mkdir(parents=True)
    fixtures = jev / "tests" / "contracts" / "fixtures"
    fixtures.mkdir(parents=True)
    for path in HARNESS_FIXTURES.glob("*.json"):
        if path.name in R.FIXTURE_NAMES:
            (fixtures / path.name).write_bytes(path.read_bytes().replace(R.COUNTER_PLACEHOLDER, R.COUNTER_LITERAL))
        elif path.name != R.DIGESTS_NAME:
            (jev / "schemas" / path.name).write_bytes(path.read_bytes())
    assert R.compare_contract(jev, HARNESS_FIXTURES) == ([], [])
