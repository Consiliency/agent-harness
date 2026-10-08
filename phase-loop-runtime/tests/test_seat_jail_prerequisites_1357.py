"""pytest is a runtime prerequisite of the seat jail's qualification (agent-harness#1357).

The qualification runs a real falsifier run whose wrapper imports `pytest`; the run copies its
dependencies from the runtime's own environment. A host installed from the published package had
no `pytest`, the qualification could not start, and the failure read as "report a defect".
These tests pin: the typed reason and its literal fix, the up-front check, `phase-loop doctor`,
that the check answers like the snapshot it stands in for, and that the wrapper's imports are
declared runtime dependencies. The real clean-install check is `scripts/_gate_a_falsifier_probe.py`,
run by `gate_a_cleanroom.sh` against the built wheel."""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from importlib import metadata
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from phase_loop_runtime import (
    doctor,
    review_stage,
    sandbox_egress,
    seat_jail,
    seat_jail_autoqualify as aq,
    seat_jail_prerequisites as prerequisites,
    seat_jail_qualification as qualification,
    seat_uid,
)
from phase_loop_runtime.seat_jail_qualification import QualificationError

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.access("/usr/bin/python3", os.X_OK),
    reason="the falsifier dependency inventory runs /usr/bin/python3")


# --- the typed reason -----------------------------------------------------------------------

SENTINEL_RUN_ERROR = (
    "sentinel never became ready: {{'value': (1, b'', b'Traceback (most recent call last):\\n"
    "  File \"<string>\", line 1, in <module>\\n    import hashlib,hmac,json,os,pytest,sys\\n"
    "ModuleNotFoundError: No module named {quote}pytest{quote}\\n', None, None)}}")


@pytest.mark.parametrize("exc", [
    QualificationError(qualification.PYTEST_MISSING),
    QualificationError(SENTINEL_RUN_ERROR.format(quote="'")),
    QualificationError(SENTINEL_RUN_ERROR.format(quote="\\'")),     # the bytes repr escapes quotes
])
def test_a_missing_pytest_is_a_typed_prerequisite_not_a_defect(exc):
    assert aq.classify_failure(exc) == "prerequisite_missing"


@pytest.mark.parametrize("text", [
    "sentinel never became ready: {'value': (1, b'', b'... No module named \\'pytest_extras\\'...')}",
    "sentinel never became ready: {'value': (1, b'', b'... No module named \\'requests\\'...')}",
    "sentinel never became ready: {}",
])
def test_other_sentinel_failures_stay_falsifier_failures(text):
    assert aq.classify_failure(QualificationError(text)) == "falsifiers_failed"


def _pytest_status(monkeypatch, status):
    monkeypatch.setattr(prerequisites, "pytest_status", lambda: status)


def test_the_fix_for_a_missing_pytest_is_a_literal_command_not_report_a_defect(monkeypatch):
    _pytest_status(monkeypatch, "missing")
    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda: True)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)
    fix = aq.fix_for("prerequisite_missing")
    assert fix == prerequisites.PYTEST_FIX
    for command in ("uv tool upgrade phase-loop-runtime", "pip install --upgrade phase-loop-runtime",
                    "uv tool install --reinstall --with 'pytest>=8,<9' phase-loop-runtime",
                    "pip install 'pytest>=8,<9'", "phase-loop seat-sandbox qualify"):
        assert f"`{command}`" in fix
    assert "report a defect" not in fix


def test_the_fix_also_names_the_host_prerequisites_when_they_are_missing_too(monkeypatch):
    _pytest_status(monkeypatch, "missing")
    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda: False)
    fix = aq.fix_for("prerequisite_missing")
    assert fix.startswith(prerequisites.PYTEST_FIX) and aq.REASON_FIXES["prerequisite_missing"] in fix


@pytest.mark.parametrize("status", ["present", "unknown"])
def test_the_generic_fix_stays_when_pytest_is_not_known_to_be_missing(monkeypatch, status):
    _pytest_status(monkeypatch, status)
    assert aq.fix_for("prerequisite_missing") == aq.REASON_FIXES["prerequisite_missing"]


def test_other_reasons_keep_their_fixes_and_fix_for_never_raises(monkeypatch):
    for reason, text in aq.REASON_FIXES.items():
        if reason != "prerequisite_missing":
            assert aq.fix_for(reason) == text
    _pytest_status(monkeypatch, "missing")
    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda: (_ for _ in ()).throw(OSError("x")))
    assert aq.fix_for("prerequisite_missing").startswith(prerequisites.PYTEST_FIX)


def test_the_qualify_command_prints_the_literal_fix_for_a_missing_pytest(monkeypatch, capsys):
    import contextlib

    from phase_loop_runtime import cli

    _pytest_status(monkeypatch, "missing")
    _host_ready(monkeypatch)
    monkeypatch.setattr(aq, "qualification_lock", contextlib.nullcontext)
    monkeypatch.setattr(qualification, "main",
                        lambda argv: (_ for _ in ()).throw(QualificationError(qualification.PYTEST_MISSING)))
    assert cli.main(["seat-sandbox", "qualify"]) == 1
    err = capsys.readouterr().err
    assert "cannot run: " + qualification.PYTEST_MISSING in err
    assert "fix: " + prerequisites.PYTEST_FIX in err and "`pip install 'pytest>=8,<9'`" in err


def test_the_qualify_command_adds_no_fix_line_for_other_failures(monkeypatch, capsys):
    import contextlib

    from phase_loop_runtime import cli

    monkeypatch.setattr(aq, "qualification_lock", contextlib.nullcontext)
    monkeypatch.setattr(qualification, "main",
                        lambda argv: (_ for _ in ()).throw(QualificationError("sentinel process not found")))
    assert cli.main(["seat-sandbox", "qualify"]) == 1
    assert "fix:" not in capsys.readouterr().err


# --- the up-front check in qualify() --------------------------------------------------------

def _host_ready(monkeypatch):
    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda: True)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)


class _Reached(Exception):
    """Raised by the stand-in for the first step after the pytest check."""


def test_qualify_refuses_up_front_when_pytest_is_missing_and_starts_nothing(monkeypatch):
    _host_ready(monkeypatch)
    monkeypatch.setattr(review_stage, "falsifier_distribution_available", lambda name: False)
    monkeypatch.setattr(seat_jail, "jail_profile_digest",
                        lambda leg: (_ for _ in ()).throw(_Reached()))
    with pytest.raises(QualificationError) as raised:
        qualification.qualify()
    assert str(raised.value) == qualification.PYTEST_MISSING     # not a sentinel timeout


@pytest.mark.parametrize("probe", [
    lambda name: True,
    lambda name: (_ for _ in ()).throw(OSError("no /usr/bin/python3")),
])
def test_qualify_goes_on_when_pytest_is_present_or_the_inventory_cannot_tell(monkeypatch, probe):
    _host_ready(monkeypatch)
    monkeypatch.setattr(review_stage, "falsifier_distribution_available", probe)
    monkeypatch.setattr(seat_jail, "jail_profile_digest",
                        lambda leg: (_ for _ in ()).throw(_Reached()))
    with pytest.raises(_Reached):                                # got past the pytest check
        qualification.qualify()


def test_the_first_use_path_caches_the_pytest_failure_as_a_typed_prerequisite():
    class Store:
        def __init__(self):
            self.runs = 0

        def verdict(self, digest):
            return False, "no_record"

        def qualify(self, leg):
            self.runs += 1
            raise QualificationError(qualification.PYTEST_MISSING)

    store = Store()
    outcome = aq.ensure_qualified("claude", verdict=store.verdict, qualify=store.qualify,
                                  now=lambda: 1.0, retry_after_s=600, lock_wait_s=5)
    assert outcome == aq.Outcome(aq.FAILED, "prerequisite_missing")
    assert aq.ensure_qualified("claude", verdict=store.verdict, qualify=store.qualify,
                               now=lambda: 2.0, retry_after_s=600, lock_wait_s=5) == outcome
    assert store.runs == 1


# --- phase-loop doctor ----------------------------------------------------------------------

def _doctor_schema() -> dict:
    return json.loads((files("phase_loop_runtime") / "schemas" / "phase-loop-doctor.v1.schema.json").read_text())


def _report(monkeypatch, status):
    _pytest_status(monkeypatch, status)
    return doctor.build_doctor_report(PACKAGE_ROOT, fetch=lambda url: None)


@pytest.mark.parametrize("status", ["present", "missing", "unknown"])
def test_doctor_reports_the_prerequisite_and_validates_against_the_schema(monkeypatch, status):
    report = _report(monkeypatch, status)
    jsonschema.validate(report, _doctor_schema())
    (entry,) = report["seat_jail_prerequisites"]
    assert entry["name"] == "pytest" and entry["status"] == status
    assert ("fix" in entry) == (status == "missing")
    if status == "missing":
        assert entry["fix"] == prerequisites.PYTEST_FIX


def test_doctors_missing_pytest_fix_carries_no_absolute_path(monkeypatch):
    serialized = json.dumps(_report(monkeypatch, "missing"))
    for token in ("/home/", "/Users/", "/mnt/", "/opt/", sys.prefix):
        assert token not in serialized


def test_doctor_prints_the_fix_for_a_missing_pytest(monkeypatch, capsys):
    doctor._print_doctor(_report(monkeypatch, "missing"))
    out = capsys.readouterr().out
    assert "Seat jail prerequisites" in out and "pytest" in out and "missing" in out
    assert "fix: " + prerequisites.PYTEST_FIX in out


def test_a_v0725_doctor_payload_without_the_new_key_still_validates():
    golden = json.loads((files("phase_loop_runtime") / "schemas" / "phase-loop-doctor.v1.golden.json").read_text())
    del golden["seat_jail_prerequisites"]
    jsonschema.validate(golden, _doctor_schema())


# --- the check answers like the snapshot it stands in for -----------------------------------

def _stage_with_dependency(tmp_path: Path, name: str) -> Path:
    stage = tmp_path / "stage"
    (stage / "phase-loop-runtime").mkdir(parents=True)
    (stage / "phase-loop-runtime" / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "0"\ndependencies = ["{name}"]\n')
    return stage


def _install_fake_distribution(prefix: Path, name: str) -> Path:
    site = prefix / "lib" / "python3" / "site-packages"
    dist_info = site / f"{name}-1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (dist_info / "RECORD").write_text(f"{name}.py,,\n{name}-1.0.dist-info/METADATA,,\n")
    (site / f"{name}.py").write_text("VALUE = 1\n")
    return site


@linux_only
@pytest.mark.parametrize("installed", [True, False])
def test_the_availability_check_agrees_with_what_the_snapshot_actually_stages(tmp_path, monkeypatch, installed):
    name = "zzfake1357"
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    site = _install_fake_distribution(prefix, name) if installed else prefix / "lib" / "site-packages"
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "base_prefix", str(prefix))
    monkeypatch.setattr(sys, "path", [*sys.path, str(site)])
    destination = tmp_path / "deps"
    destination.mkdir()
    review_stage._snapshot_falsifier_dependencies(_stage_with_dependency(tmp_path, name), destination)
    staged = (destination / f"{name}.py").is_file()
    assert review_stage.falsifier_distribution_available(name) is installed
    assert staged is installed          # the check and the snapshot give the same answer


@linux_only
def test_the_availability_check_normalises_names_and_rejects_unknown_ones():
    assert review_stage.falsifier_distribution_available("pytest") is True
    assert review_stage.falsifier_distribution_available("PyTest") is True
    assert review_stage.falsifier_distribution_available("zz-no-such-dist-1357") is False


def test_an_inventory_that_cannot_run_is_unknown_not_missing(monkeypatch):
    def broken(name):
        raise subprocess.CalledProcessError(1, "x")

    monkeypatch.setattr(review_stage, "falsifier_distribution_available", broken)
    assert prerequisites.pytest_status() == "unknown" and prerequisites.missing() == []


def test_the_snapshot_and_the_layout_identity_were_not_touched():
    """Passes are bound to `falsifier_layout_identity`, which hashes the snapshot's source: a
    patch release must not reset every host's jail approval a second time. The identity on the
    0.7.25 release was 805042ce6314..., and this change must not move it."""
    assert seat_jail.falsifier_layout_identity().startswith("execfind-falsifier-layout.v1:805042ce")


# --- the wrapper's imports are runtime dependencies -----------------------------------------

def _wrapper_imports() -> list[str]:
    source = inspect.getsource(review_stage._run_bounded_falsifier_node)
    found = re.findall(r'"import ([A-Za-z_][A-Za-z0-9_,]*)\\n"', source)
    assert len(found) == 1, "the falsifier wrapper's import line moved; update this test and the Gate A probe"
    return found[0].split(",")


def _declared_runtime_dependencies() -> set[str]:
    pyproject = PACKAGE_ROOT / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib
        except ImportError:                                     # Python 3.10
            import tomli as tomllib
        requirements = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    else:                                                       # an installed wheel: no pyproject
        requirements = [r for r in (metadata.distribution("phase-loop-runtime").requires or [])
                        if "extra ==" not in r]
    return {re.split(r"[\s<>=!~;\[(]", r, maxsplit=1)[0].lower().replace("_", "-") for r in requirements}


def test_every_third_party_import_of_the_falsifier_wrapper_is_a_declared_runtime_dependency():
    declared = _declared_runtime_dependencies()
    third_party = [name for name in _wrapper_imports() if name not in sys.stdlib_module_names]
    assert "pytest" in third_party, "the wrapper no longer imports pytest; revisit agent-harness#1357"
    undeclared = []
    for name in third_party:
        owners = {d.lower().replace("_", "-") for d in metadata.packages_distributions().get(name, [name])}
        if not owners & declared:
            undeclared.append(name)
    assert not undeclared, (
        f"the jail qualification imports {undeclared}, which a clean install of the wheel does not "
        "provide: add them to [project].dependencies")


def test_pytest_is_a_runtime_dependency_and_not_only_a_test_dependency():
    pyproject = PACKAGE_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("source tree only")
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    runtime = [r for r in payload["project"]["dependencies"] if r.lower().startswith("pytest")]
    assert len(runtime) == 1 and ">=8" in runtime[0]            # a lower bound (maintainer ruling)
    assert not any(r.lower().startswith("pytest") for r in payload["dependency-groups"]["test"])
