"""JEVHOST §6 [C2]: a configured but broken JEV Drill install fails; only "neither" skips.

Each case runs the real route test (and once the real ``installed_discovery`` fixture)
in a separate pytest process through ``pytester``, so the real ``conftest.py`` marker
rules and ``jevdrill_install.resolve_install()`` decide the outcome.

The fakes are POSIX shell scripts and rely on execute bits, so this file runs on POSIX;
the required Linux suite runs it.
"""
import os
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX execute bits and shell-script fakes")

TESTS = Path(__file__).resolve().parent
ROUTE_TEST = f"{TESTS / 'test_jevdrill_adapter.py'}::test_real_jevdrill_cli_route_and_durable_reports"
DISCOVERY_TEST = f"{TESTS / 'test_jevdrill_discovery.py'}::test_entered_discovery_requires_harness_decomposition"
SKIP_REASON = "jevdrill_installed: neither JEVDRILL_TEST_CLI nor JEVDRILL_TEST_PYTHON is set"
CLI, PYTHON = "JEVDRILL_TEST_CLI", "JEVDRILL_TEST_PYTHON"

# Answers the preflight's probes as a JEV Drill interpreter would, with its own
# directory as ``sys.prefix``. It is not JEV Drill, so nothing past the preflight works.
JEV_LIKE_PYTHON = """#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
case "$*" in
  *"-m jevdrill.cli --help"*) echo "usage: jevdrill [-h] {route,report}"; exit 0;;
  *"import jevdrill"*) printf '{"prefix": "%s", "file": null}\\n' "$here"; exit 0;;
  *"sys.prefix"*) echo "$here"; exit 0;;
esac
exit 1
"""
JEV_LIKE_CLI = "#!/bin/sh\necho 'usage: jevdrill [-h] {route,report}'\n"
# Exits 0 and echoes its argv, so "jevdrill" appears in its output but not as the prefix.
ECHO = '#!/bin/sh\necho "$0 $*"\n'


def script(path: Path, text: str, *, executable: bool = True) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)
    return str(path)


def install(root: Path, fault: str) -> dict[str, str]:
    """A fake install dir whose CLI (and its own interpreter) carries ``fault``."""
    bin_dir = root / "bin"
    if fault == "missing":
        return {CLI: str(bin_dir / "jevdrill"), PYTHON: str(bin_dir / "python")}
    if fault == "non_executable":
        return {CLI: script(bin_dir / "jevdrill", JEV_LIKE_CLI, executable=False),
                PYTHON: script(bin_dir / "python", JEV_LIKE_PYTHON, executable=False)}
    assert fault == "non_jev"
    return {CLI: script(bin_dir / "jevdrill", ECHO), PYTHON: sys.executable}


def run_inner(pytester, monkeypatch, env: dict[str, str], node: str = ROUTE_TEST):
    for name in (CLI, PYTHON):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return pytester.runpytest_subprocess(node, "-p", "no:cacheprovider", "-p", "no:xdist", "-rs",
                                         timeout=300)


def outcome(result) -> dict[str, int]:
    return {key: value for key, value in result.parseoutcomes().items()
            if key in ("passed", "failed", "skipped", "errors", "error")}


@pytest.mark.parametrize("fault", ["missing", "non_executable", "non_jev"])
@pytest.mark.parametrize("variables", ["cli", "python", "both"])
def test_configured_broken_install_fails_and_never_skips(pytester, monkeypatch, tmp_path, fault, variables):
    broken = install(tmp_path / "broken", fault)
    if variables == "cli":
        # A JEV-like interpreter beside the broken CLI, so the CLI's own check decides.
        if fault != "missing":
            script(Path(broken[CLI]).parent / "python", JEV_LIKE_PYTHON)
        env, named = {CLI: broken[CLI]}, CLI
    elif variables == "python":
        env, named = {PYTHON: broken[PYTHON]}, PYTHON
    else:
        env, named = {CLI: broken[CLI], PYTHON: broken[PYTHON]}, None
        if fault == "non_jev":
            # A JEV-like interpreter, so the non-JEV CLI decides; a sibling keeps one install.
            env[PYTHON] = script(Path(broken[CLI]).parent / "python", JEV_LIKE_PYTHON)
    result = run_inner(pytester, monkeypatch, env)
    assert outcome(result) == {"failed": 1}, result.stdout.str()
    text = result.stdout.str()
    assert SKIP_REASON not in text
    prefix = f"JEV Drill install preflight: {named}: " if named else "JEV Drill install preflight: JEVDRILL_TEST_"
    assert prefix in text
    reason = {"missing": "does not exist", "non_executable": "is not executable",
              "non_jev": "is not JEV Drill" if variables != "python" else "cannot import jevdrill"}[fault]
    assert reason in text


def test_mixed_pair_fails(pytester, monkeypatch, tmp_path):
    first = tmp_path / "first" / "bin"
    second = tmp_path / "second" / "bin"
    script(first / "python", JEV_LIKE_PYTHON)
    env = {CLI: script(first / "jevdrill", JEV_LIKE_CLI), PYTHON: script(second / "python", JEV_LIKE_PYTHON)}
    result = run_inner(pytester, monkeypatch, env)
    assert outcome(result) == {"failed": 1}, result.stdout.str()
    assert "JEV Drill install preflight: JEVDRILL_TEST_CLI: mixed pair" in result.stdout.str()


def test_installed_discovery_fixture_runs_the_preflight(pytester, monkeypatch, tmp_path):
    result = run_inner(pytester, monkeypatch, {PYTHON: str(tmp_path / "missing" / "python")}, DISCOVERY_TEST)
    counts = outcome(result)
    assert counts.get("skipped", 0) == 0 and counts.get("passed", 0) == 0, result.stdout.str()
    assert counts.get("errors", 0) + counts.get("error", 0) == 1, result.stdout.str()
    assert "JEV Drill install preflight: JEVDRILL_TEST_PYTHON: interpreter" in result.stdout.str()


def test_neither_variable_skips_with_the_fixed_reason(pytester, monkeypatch):
    result = run_inner(pytester, monkeypatch, {})
    assert outcome(result) == {"skipped": 1}, result.stdout.str()
    assert SKIP_REASON in result.stdout.str()
