"""The AppArmor override for the seat jail on Ubuntu 24.04+/26.04 (agent-harness#1276).

The policy cannot be loaded in CI, so these tests pin what makes it safe (narrow, named, no
path attachment, entered stacked, hands the seat back out of the profile) and run the
generated root scripts against a scratch directory with a fake `apparmor_parser`. Where the
host has a parser, the profile is also compiled with it, without loading anything. The live
check that a jailed seat reaches its proxy after the hand-back (agent-harness#1915) is in
`test_seat_jail_proxy_reach_1915.py`.
"""

from __future__ import annotations

import os
import re
import shutil
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
    assert "allow px /** -> bwrap//&unpriv_bwrap," in text   # the seat is handed back


def test_the_hand_back_leaves_the_uid_drop_profile():
    """agent-harness#1915: the one exec rule is a transition to `bwrap//&unpriv_bwrap`, not a
    stack on this profile (no leading `&`), so after the drop the seat runs with the same
    confinement as every other bwrap child; `px` has no inherit fallback, so the seat never
    stays here. The profile itself stays narrow: no network or other rule is added to it."""
    exec_rules = re.findall(r"^\s*allow (\w+) (\S+) -> (\S+),$", aa.PROFILE_TEXT, re.MULTILINE)
    assert exec_rules == [("px", "/**", "bwrap//&unpriv_bwrap")]
    body = aa.PROFILE_TEXT.split("{", 1)[1]
    rules = [line.strip() for line in body.splitlines()
             if line.strip() and not line.strip().startswith(("#", "}"))]
    assert rules == [
        "allow capability setuid,", "allow capability setgid,", "allow capability setpcap,",
        "allow file rwlkm /{**,},", "allow signal,", "allow unix,",
        "allow px /** -> bwrap//&unpriv_bwrap,",
    ]


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


def test_reinstall_over_an_earlier_profile_rewrites_it_and_keeps_one_local_block(tmp_path):
    """A host that installed the earlier, stacked hand-back reruns the script: the profile is
    rewritten, the local block it already holds is not appended again, and both reload."""
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    earlier = aa.PROFILE_TEXT.replace(
        "allow px /** -> bwrap//&unpriv_bwrap,", "allow pix /** -> &bwrap//&unpriv_bwrap,")
    assert earlier != aa.PROFILE_TEXT
    (directory / aa.PROFILE_FILE).write_text(earlier)
    (directory / aa.LOCAL_FILE).write_text(aa.LOCAL_TEXT)
    result = _run(aa.install_script(), directory, parser)
    assert result.returncode == 0, result.stderr
    assert (directory / aa.PROFILE_FILE).read_text() == aa.PROFILE_TEXT
    assert (directory / aa.LOCAL_FILE).read_text() == aa.LOCAL_TEXT
    calls = (tmp_path / "parser.log").read_text().splitlines()
    assert calls == [f"-r {directory / aa.PROFILE_FILE}", f"-r {directory / 'bwrap-userns-restrict'}"]


def test_the_profile_compiles_with_the_hosts_parser(tmp_path):
    """Compile only (`-Q` skips the kernel load, `-K` the cache): nothing is installed or
    loaded. Skips where the host has no parser or cannot compile a trivial control profile."""
    parser = shutil.which("apparmor_parser") or next(
        (path for path in ("/usr/sbin/apparmor_parser", "/sbin/apparmor_parser")
         if os.access(path, os.X_OK)), None)
    if parser is None:
        pytest.skip("no apparmor_parser on this host")
    control = tmp_path / "control"
    preamble = [line for line in aa.PROFILE_TEXT.splitlines()
                if line.startswith(("abi ", "include "))]
    assert preamble == ["abi <abi/5.0>,", "include <tunables/global>"]
    control.write_text("\n".join(preamble)
                       + "\nprofile phase_loop_compile_control {\n  allow file r /,\n}\n")
    if subprocess.run([parser, "-Q", "-K", str(control)], capture_output=True,
                      timeout=60).returncode != 0:
        pytest.skip("this host's parser cannot compile a control profile here")
    profile = tmp_path / aa.PROFILE_FILE
    profile.write_text(aa.PROFILE_TEXT)
    done = subprocess.run([parser, "-Q", "-K", str(profile)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr


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
