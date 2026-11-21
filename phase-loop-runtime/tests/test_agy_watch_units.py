"""The watch's hourly user timer: ``watch --install-units`` and ``watch --check`` (ROLLJOB-detail §3, §6.2).

No test runs a real ``systemctl``: every call goes to a fake runner, and the unit directory
and the state home are temporary directories.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

from phase_loop_runtime import agy_catalog_policy as policy
from phase_loop_runtime import agy_watch_units as units

REPO = Path(__file__).resolve().parents[2]
UNIT_SOURCE = REPO / "docs/ops/agy-upstream-watch"
NOW = 1_800_000_000.0

pytestmark = pytest.mark.skipif(not UNIT_SOURCE.is_dir(), reason="the unit files are repository source")


class Systemctl:
    """A fake ``systemctl --user``: records every call; ``is-enabled`` answers ``enabled``."""

    def __init__(self, *, enabled="enabled", fail=None):
        self.calls, self.enabled, self.fail = [], enabled, fail

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        assert argv[:2] == ["systemctl", "--user"], argv
        if self.fail and self.fail in argv:
            return subprocess.CompletedProcess(argv, 1, "", "failed")
        if argv[2] == "is-enabled":
            return subprocess.CompletedProcess(argv, 0 if self.enabled == "enabled" else 1, self.enabled + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


@pytest.fixture
def home(tmp_path):
    """A checkout with the unit files, and an environment whose config and state are private."""
    checkout = tmp_path / "checkout"
    shutil.copytree(UNIT_SOURCE, checkout / units.UNIT_DIR)
    environ = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
               "XDG_STATE_HOME": str(tmp_path / "state")}
    return checkout, environ


def _args(**kwargs):
    from types import SimpleNamespace
    values = {"action": "watch", "repo": None, "install_units": False, "check": False, "watch_dry_run": False,
              "dry_run": False}
    values.update(kwargs)
    return SimpleNamespace(**values)


def _lines(path):
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


# ------------------------------------------------------------------------------ unit files

def test_the_timer_is_hourly_with_the_frozen_lines():
    lines = _lines(UNIT_SOURCE / units.TIMER)
    timer = lines[lines.index("[Timer]") + 1:lines.index("[Install]")]
    assert timer == ["OnCalendar=hourly", "RandomizedDelaySec=10m", "Persistent=true"]
    assert "WantedBy=timers.target" in lines


def test_the_service_names_both_keys_and_the_intake_ids_file_and_holds_no_secret():
    lines = _lines(UNIT_SOURCE / units.SERVICE)
    assert f"Environment={policy.SIGNING_KEY_ENV}=%h/.config/phase-loop/agy-watch/signing_key" in lines
    assert "Environment=AGY_INTAKE_APP_KEY=%h/.config/phase-loop/agy-watch/intake_app_key.pem" in lines
    assert "EnvironmentFile=-%h/.config/phase-loop/agy-watch/intake.env" in lines
    assert "ExecStart=%h/.local/bin/phase-loop agy-qualification watch --repo %h/code/agent-harness" in lines
    text = (UNIT_SOURCE / units.SERVICE).read_text()
    assert "PRIVATE KEY" not in text and "ghs_" not in text and "ghp_" not in text
    assert not [line for line in lines if line.startswith("Environment=") and "AGY_INTAKE_APP_ID" in line]


# --------------------------------------------------------------------------- --install-units

def test_install_units_copies_both_reloads_and_enables_and_is_idempotent(home):
    checkout, environ = home
    runner, out = Systemctl(), []
    assert units.install_units(checkout, runner=runner, environ=environ, out=out.append) == 0
    target = units.user_unit_dir(environ)
    assert target == Path(environ["XDG_CONFIG_HOME"]) / "systemd/user"
    for name in units.UNITS:
        assert (target / name).read_bytes() == (UNIT_SOURCE / name).read_bytes()
        assert stat.S_IMODE((target / name).stat().st_mode) == 0o644
    assert runner.calls == [["systemctl", "--user", "daemon-reload"],
                            ["systemctl", "--user", "enable", "--now", units.TIMER]]
    assert json.loads(out[-1]) == {"agy_watch_install": "installed", "changed": list(units.UNITS)}
    before = {name: (target / name).stat().st_mtime_ns for name in units.UNITS}
    assert units.install_units(checkout, runner=runner, environ=environ, out=out.append) == 0
    assert json.loads(out[-1]) == {"agy_watch_install": "installed", "changed": []}
    assert {name: (target / name).stat().st_mtime_ns for name in units.UNITS} == before
    assert sorted(p.name for p in target.iterdir()) == sorted(units.UNITS)


def test_install_units_dry_run_runs_nothing_and_writes_nothing(home):
    checkout, environ = home
    runner, out = Systemctl(), []
    assert units.main(_args(install_units=True, watch_dry_run=True, repo=str(checkout)), runner=runner,
                      environ=environ, out=out.append) == 0
    assert runner.calls == [] and not units.user_unit_dir(environ).exists()
    report = json.loads(out[-1])
    assert report["agy_watch_install"] == "dry_run"
    assert report["actions"][-2:] == ["systemctl --user daemon-reload", f"systemctl --user enable --now {units.TIMER}"]


def test_install_units_reports_a_failing_systemctl(home):
    checkout, environ = home
    out = []
    assert units.install_units(checkout, runner=Systemctl(fail="enable"), environ=environ, out=out.append) == 2
    assert json.loads(out[-1]) == {"agy_watch_install": "systemctl_failed", "step": f"enable --now {units.TIMER}"}


def test_install_units_needs_the_checkouts_unit_files(tmp_path):
    runner, out = Systemctl(), []
    assert units.install_units(tmp_path, runner=runner, environ={"XDG_CONFIG_HOME": str(tmp_path / "c")},
                               out=out.append) == 2
    assert runner.calls == [] and json.loads(out[-1])["agy_watch_install"] == "units_not_in_checkout"


def test_install_units_creates_no_key_login_or_credential(home):
    checkout, environ = home
    units.install_units(checkout, runner=Systemctl(), environ=environ, out=lambda line: None)
    made = {p.relative_to(Path(environ["XDG_CONFIG_HOME"])) for p in Path(environ["XDG_CONFIG_HOME"]).rglob("*")
            if p.is_file()}
    assert made == {Path("systemd/user") / name for name in units.UNITS}
    assert not Path(environ["HOME"]).exists() and not Path(environ["XDG_STATE_HOME"]).exists()


# ---------------------------------------------------------------------------------- --check

def _installed(home):
    checkout, environ = home
    units.install_units(checkout, runner=Systemctl(), environ=environ, out=lambda line: None)
    return checkout, environ


def _check(checkout, environ, runner=None, now=NOW):
    out = []
    code = units.main(_args(check=True, repo=str(checkout)), runner=runner or Systemctl(), environ=environ,
                      out=out.append, now=now)
    return code, json.loads(out[-1])


def test_check_reports_installed_only_with_current_enabled_units_and_a_recent_passing_tick(home):
    checkout, environ = _installed(home)
    policy.write_tick_status("up_to_date", 0, version="9.9.9", environ=environ, now=NOW - 600)
    assert _check(checkout, environ) == (0, {"agy_watch_check": "installed", "last_tick": "up_to_date"})


@pytest.mark.parametrize("missing", list(units.UNITS))
def test_check_absent_when_either_unit_is_not_installed(home, missing):
    checkout, environ = _installed(home)
    policy.write_tick_status("series_violation", 2, environ=environ, now=NOW - 600)  # failed would match too
    (units.user_unit_dir(environ) / missing).unlink()
    assert _check(checkout, environ) == (1, {"agy_watch_check": "absent", "last_tick": "series_violation"})


def test_check_failed_names_the_last_status_even_when_it_is_also_stale(home):
    checkout, environ = _installed(home)
    policy.write_tick_status("gemini_login_expired", 2, environ=environ, now=NOW - 10 * 3600)
    assert _check(checkout, environ, runner=Systemctl(enabled="disabled")) == (
        1, {"agy_watch_check": "failed: gemini_login_expired", "last_tick": "gemini_login_expired"})


@pytest.mark.parametrize("cause", ["unit_differs", "timer_disabled", "no_status", "malformed_status", "old_status"])
def test_check_stale(home, cause):
    checkout, environ = _installed(home)
    runner = Systemctl()
    policy.write_tick_status("up_to_date", 0, environ=environ, now=NOW - 600)
    if cause == "unit_differs":
        (checkout / units.UNIT_DIR / units.TIMER).write_text("[Timer]\nOnCalendar=daily\n")
    elif cause == "timer_disabled":
        runner = Systemctl(enabled="disabled")
    elif cause == "no_status":
        policy.tick_status_path(environ).unlink()
    elif cause == "malformed_status":
        policy.tick_status_path(environ).write_text("{not json")
    else:
        policy.write_tick_status("up_to_date", 0, environ=environ, now=NOW - units.CHECK_FRESH_S - 1)
    code, report = _check(checkout, environ, runner=runner)
    assert code == 1 and report["agy_watch_check"] == "stale"
    assert report["last_tick"] == (None if cause in ("no_status", "malformed_status") else "up_to_date")


def test_check_reads_is_enabled_through_the_runner_only(home):
    checkout, environ = _installed(home)
    policy.write_tick_status("up_to_date", 0, environ=environ, now=NOW)
    runner = Systemctl()
    _check(checkout, environ, runner=runner)
    assert runner.calls == [["systemctl", "--user", "is-enabled", units.TIMER]]


# --------------------------------------------------------------------------------- the CLI

def test_the_two_flags_are_mutually_exclusive():
    from phase_loop_runtime import cli
    with pytest.raises(SystemExit) as raised:
        cli.build_parser().parse_args(["agy-qualification", "watch", "--install-units", "--check"])
    assert raised.value.code == 2


def test_the_flags_dispatch_to_the_units_module_and_plain_watch_is_unchanged(monkeypatch):
    from phase_loop_runtime import agy_watch, cli
    seen = {}
    monkeypatch.setattr(units, "main", lambda args: seen.setdefault("units", []).append(
        (args.install_units, args.check)) or 0)
    monkeypatch.setattr(agy_watch, "main", lambda **kw: seen.setdefault("watch", []).append(kw) or 0)
    assert cli.main(["agy-qualification", "watch", "--check"]) == 0
    assert cli.main(["agy-qualification", "watch", "--install-units", "--repo", "/x"]) == 0
    assert seen.pop("units") == [(False, True), (True, False)] and "watch" not in seen
    assert cli.main(["agy-qualification", "watch", "--repo", "/x"]) == 0
    assert cli.main(["--dry-run", "agy-qualification", "watch"]) == 0
    assert [(kw["repo"], kw["dry_run"]) for kw in seen.pop("watch")] == [("/x", False), (None, True)]
    assert "units" not in seen


def test_the_flags_need_the_watch_action():
    out = []
    assert units.main(_args(action="status", check=True), out=out.append) == 2
    assert json.loads(out[-1]) == {"agy_watch": "units_flags_need_watch"}
