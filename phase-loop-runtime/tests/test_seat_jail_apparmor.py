"""The AppArmor override for the seat jail on Ubuntu 24.04+/26.04 (agent-harness#1276).

The policy cannot be loaded in CI, so these tests pin what makes it safe (narrow, named, no
path attachment, stacked, hands the seat back) and run the generated root scripts against a
scratch directory with a fake `apparmor_parser`.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import seat_jail_apparmor as aa
from phase_loop_runtime import seat_jail_autoqualify as autoqualify


def _shipped_profile(tmp_path: Path) -> Path:
    directory = tmp_path / "apparmor.d"
    (directory / "local").mkdir(parents=True)
    (directory / "bwrap-userns-restrict").write_text("# the shipped profile\n")
    return directory


def _fake_parser(tmp_path: Path) -> Path:
    log = tmp_path / "parser.log"
    script = tmp_path / "fake-apparmor-parser"
    script.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _run(script: str, directory: Path, parser: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "AA_DIR": str(directory), "APPARMOR_PARSER": str(parser)}
    return subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)


def test_the_profile_is_narrow_named_and_has_no_path_attachment():
    text = aa.PROFILE_TEXT
    header = re.search(r"^profile (\S+) (.*)\{$", text, re.MULTILINE)
    assert header and header.group(1) == aa.PROFILE_NAME
    # No attachment path: a plain `setpriv` elsewhere on the host must stay untouched.
    assert "/usr/bin/setpriv" not in header.group(0)
    caps = re.findall(r"^\s*allow capability (\w+),$", text, re.MULTILINE)
    assert sorted(caps) == ["setgid", "setpcap", "setuid"]
    assert not re.search(r"^\s*(allow )?capability,", text, re.MULTILINE)   # never a blanket grant
    assert "allow pix /** -> &bwrap//&unpriv_bwrap," in text   # the seat is handed back


def test_the_local_block_is_one_stacked_rule_for_setpriv_only():
    rules = [line for line in aa.LOCAL_TEXT.splitlines() if line and not line.startswith("#")]
    assert rules == [f"allow pix /usr/bin/setpriv -> &bwrap//&{aa.PROFILE_NAME},"]
    assert aa.LOCAL_TEXT.startswith(aa.BEGIN_MARK) and aa.LOCAL_TEXT.rstrip().endswith(aa.END_MARK)


def test_install_writes_both_files_and_loads_the_profile_before_the_bwrap_profile(tmp_path):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    result = _run(aa.install_script(), directory, parser)
    assert result.returncode == 0, result.stderr
    assert (directory / aa.PROFILE_FILE).read_text() == aa.PROFILE_TEXT
    assert (directory / aa.LOCAL_FILE).read_text() == aa.LOCAL_TEXT
    calls = (tmp_path / "parser.log").read_text().splitlines()
    assert calls == [f"-r {directory / aa.PROFILE_FILE}", f"-r {directory / 'bwrap-userns-restrict'}"]


def test_install_is_idempotent_and_keeps_an_administrators_local_rules(tmp_path):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    local = directory / aa.LOCAL_FILE
    local.write_text("allow /srv/data/** r,\n")           # the administrator's own rule
    assert _run(aa.install_script(), directory, parser).returncode == 0
    assert _run(aa.install_script(), directory, parser).returncode == 0
    text = local.read_text()
    assert text.startswith("allow /srv/data/** r,\n")      # not clobbered
    assert text.count(aa.BEGIN_MARK) == 1                  # appended exactly once


def test_install_does_nothing_on_a_host_that_does_not_confine_bwrap(tmp_path):
    directory = tmp_path / "apparmor.d"
    directory.mkdir()
    result = _run(aa.install_script(), directory, _fake_parser(tmp_path))
    assert result.returncode == 0 and "nothing to do" in result.stderr
    assert not (directory / aa.PROFILE_FILE).exists()


def test_revert_removes_only_our_block_and_the_profile(tmp_path):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    local = directory / aa.LOCAL_FILE
    local.write_text("allow /srv/data/** r,\n")
    assert _run(aa.install_script(), directory, parser).returncode == 0
    assert _run(aa.revert_script(), directory, parser).returncode == 0
    assert local.read_text() == "allow /srv/data/** r,\n"   # the administrator's rule survives
    assert not (directory / aa.PROFILE_FILE).exists()


def test_revert_removes_a_local_file_that_only_held_our_block(tmp_path):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    assert _run(aa.install_script(), directory, parser).returncode == 0
    assert _run(aa.revert_script(), directory, parser).returncode == 0
    assert not (directory / aa.LOCAL_FILE).exists()
    assert not (directory / aa.PROFILE_FILE).exists()


def test_the_command_prints_the_scripts_and_refuses_unknown_flags(capsys):
    assert aa.main([]) == 0 and capsys.readouterr().out == aa.install_script()
    assert aa.main(["--revert"]) == 0 and capsys.readouterr().out == aa.revert_script()
    assert aa.main(["--profile"]) == 0 and capsys.readouterr().out == aa.PROFILE_TEXT
    assert aa.main(["--local"]) == 0 and capsys.readouterr().out == aa.LOCAL_TEXT
    assert aa.main(["--nope"]) == 2


def test_the_typed_reason_names_the_command_that_prints_the_override():
    fix = autoqualify.REASON_FIXES["uid_switch_denied"]
    assert "phase_loop_runtime.seat_jail_apparmor" in fix and "unpriv_bwrap" in fix


@pytest.mark.parametrize("script", [aa.install_script(), aa.revert_script()])
def test_the_scripts_are_valid_posix_sh(script):
    assert subprocess.run(["sh", "-n", "-c", script], capture_output=True, timeout=30).returncode == 0
