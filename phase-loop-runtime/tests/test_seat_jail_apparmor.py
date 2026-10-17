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
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import seat_jail_apparmor as aa
from phase_loop_runtime import seat_jail_autoqualify as autoqualify

needs_codex_owner = pytest.mark.skipif(
    sys.platform != "linux" or os.getuid() == 0 or not Path("/usr/bin/bwrap").is_file(),
    reason="requires Linux non-root seat owner",
)


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


def test_codex_policy_keeps_setup_capabilities_out_of_owner_and_payload():
    assert aa.CODEX_OWNER_PATH == "/run/phase-loop-seat/codex-owner"
    assert aa.CODEX_PROVIDER_PATH == "/run/phase-loop-seat/codex-runtime/bin/codex"
    assert aa.CODEX_BWRAP_PATH == "/run/phase-loop-seat/codex-sandbox-bin/bwrap"
    owner, rest = aa.CODEX_PROFILE_TEXT.split("profile phase_loop_codex_setup", 1)
    setup, payload = rest.split("profile phase_loop_codex_payload", 1)
    assert "allow capability" not in owner
    assert "allow capability" not in payload
    caps = re.findall(r"allow capability (\w+),", setup)
    assert set(caps) == {"sys_admin", "sys_chroot", "net_admin", "setuid", "setgid", "sys_ptrace", "setpcap"}
    assert not re.search(r"^\s*(allow )?capability,", aa.CODEX_PROFILE_TEXT, re.MULTILINE)
    assert "allow px /** -> bwrap//&unpriv_bwrap//&phase_loop_codex_payload," in setup
    assert "codex_finalize" not in aa.CODEX_PROFILE_TEXT
    rules = [line for line in aa.CODEX_LOCAL_TEXT.splitlines() if line.startswith("allow")]
    assert rules == [
        f"allow px {aa.CODEX_OWNER_PATH} -> bwrap//&phase_loop_codex_owner,",
        f"allow px {aa.CODEX_PROVIDER_PATH} -> bwrap//&phase_loop_codex_owner,",
        f"allow px {aa.CODEX_BWRAP_PATH} -> bwrap//&phase_loop_codex_setup,",
    ]
    assert "/usr/bin/python" not in aa.CODEX_LOCAL_TEXT and "/usr/bin/bwrap" not in aa.CODEX_LOCAL_TEXT


def test_codex_exec_transitions_replace_the_prior_stage_and_refuse_missing_targets():
    # Leading '&' makes the kernel attach/ix fallback retain the previous stage before
    # merging the target. A no-capability owner then denies inner bwrap setup forever.
    for text in (aa.CODEX_PROFILE_TEXT, aa.CODEX_LOCAL_TEXT):
        rules = [line.strip() for line in text.splitlines() if " -> " in line]
        assert rules
        for rule in rules:
            mode, target = re.fullmatch(r"allow (\w+) .+ -> (.+),", rule).groups()
            assert mode == "px"  # No inherited fallback if a named profile is unavailable.
            assert target.startswith("bwrap//&")  # Preserve the no-new-privs base profile.
    owner, setup = aa.CODEX_PROFILE_TEXT.split("profile phase_loop_codex_setup", 1)
    assert f"{aa.CODEX_BWRAP_PATH} -> bwrap//&phase_loop_codex_setup," in owner
    assert "phase_loop_codex_owner" not in setup
    assert "-> bwrap//&unpriv_bwrap//&phase_loop_codex_payload," in setup


def test_codex_payload_denies_new_user_namespaces_and_keeps_the_denial_after_exec():
    profiles = dict(re.findall(r"^profile (\w+) flags=\([^\n]+\) \{\n(.*?)^\}",
                               aa.CODEX_PROFILE_TEXT, re.MULTILINE | re.DOTALL))
    assert set(profiles) == {"phase_loop_codex_owner", "phase_loop_codex_setup", "phase_loop_codex_payload"}
    payload = profiles["phase_loop_codex_payload"]
    assert "deny userns," in payload and "allow userns," not in payload
    assert "allow capability" not in payload
    target = "allow px /** -> bwrap//&unpriv_bwrap//&phase_loop_codex_payload,"
    for profile in profiles.values():
        assert target in profile
    assert [line.strip() for line in payload.splitlines() if " -> " in line] == [target]


def test_codex_install_and_revert_preserve_the_claude_override_and_admin_rules(tmp_path):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    assert _run(aa.install_script(), directory, parser).returncode == 0
    local = directory / aa.LOCAL_FILE
    before = local.read_text() + "allow /srv/data/** r,\n"
    local.write_text(before)
    assert _run(aa.install_script(codex=True), directory, parser).returncode == 0
    assert _run(aa.install_script(codex=True), directory, parser).returncode == 0
    assert local.read_text() == before + aa.CODEX_LOCAL_TEXT
    assert _run(aa.revert_script(codex=True), directory, parser).returncode == 0
    assert local.read_text() == before
    assert (directory / aa.PROFILE_FILE).read_text() == aa.PROFILE_TEXT
    assert not (directory / aa.CODEX_PROFILE_FILE).exists()


@pytest.mark.parametrize("collision", ["profile", "local", "profile-symlink", "local-symlink"])
def test_codex_installer_refuses_collisions_before_writing_or_loading(tmp_path, collision):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    profile, local = directory / aa.CODEX_PROFILE_FILE, directory / aa.LOCAL_FILE
    if collision == "profile":
        profile.write_text("administrator policy\n")
    elif collision == "local":
        local.write_text(aa.CODEX_BEGIN_MARK + "\nchanged rule\n" + aa.CODEX_END_MARK + "\n")
    else:
        external = tmp_path / "external"
        external.write_text(aa.CODEX_PROFILE_TEXT if collision == "profile-symlink" else "must survive\n")
        (profile if collision == "profile-symlink" else local).symlink_to(external)
    before = {p: p.read_bytes() for p in [profile, local] if p.exists()}
    result = _run(aa.install_script(codex=True), directory, parser)
    assert result.returncode != 0
    assert {p: p.read_bytes() for p in [profile, local] if p.exists()} == before
    assert not (tmp_path / "parser.log").exists()


def test_codex_rollback_does_not_report_success_when_reload_fails(tmp_path):
    directory, parser = _shipped_profile(tmp_path), _fake_parser(tmp_path)
    assert _run(aa.install_script(codex=True), directory, parser).returncode == 0
    parser.write_text('#!/bin/sh\nexit 1\n')
    result = _run(aa.revert_script(codex=True), directory, parser)
    assert result.returncode != 0 and "removed" not in result.stdout
    assert (directory / aa.CODEX_PROFILE_FILE).exists()


def test_codex_print_flags_do_not_execute_the_scripts(capsys):
    for args, text in [(["--codex"], aa.install_script(codex=True)),
                       (["--codex", "--revert"], aa.revert_script(codex=True)),
                       (["--codex", "--profile"], aa.CODEX_PROFILE_TEXT),
                       (["--codex", "--local"], aa.CODEX_LOCAL_TEXT)]:
        assert aa.main(args) == 0 and capsys.readouterr().out == text


def _native_codex_profile(tmp_path, monkeypatch, *, writable=True, role="PROVIDER_REVIEW", elf=True,
                          image="/usr/bin/true"):
    import shutil
    from phase_loop_runtime import panel_invoker as pi

    runtime = tmp_path / "vendor/x86_64-unknown-linux-musl"
    (runtime / "bin").mkdir(parents=True)
    (runtime / "codex-path").mkdir()
    native = runtime / "bin/codex"
    shutil.copyfile(image, native)
    native.chmod(0o700)
    if not elf:
        native.write_text("#!/bin/sh\nexit 0\n")
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setattr(pi, "_seat_credential", lambda *args: b'{"tokens":{"access_token":"synthetic"}}')
    return pi.seat_profile(harness="codex", executable=native, env={"HOME": str(tmp_path)},
                           cwd=tmp_path, role=role, writable_trees=(tree,) if writable else ())


@needs_codex_owner
@pytest.mark.parametrize("writable,role,elf,expected", [
    (True, "PROVIDER_REVIEW", True, True),
    (False, "PROVIDER_REVIEW", True, False),
    (True, "PROVIDER_ADMIN", True, False),
    (True, "PROVIDER_REVIEW", False, False),
])
def test_codex_owner_paths_are_limited_to_native_writable_review_seats(
        tmp_path, monkeypatch, writable, role, elf, expected):
    with _native_codex_profile(tmp_path, monkeypatch, writable=writable, role=role, elf=elf) as (_, profile):
        assert profile.codex_namespace_owner is expected
        assert (aa.CODEX_OWNER_PATH in profile.mount_args) is expected
        assert (aa.CODEX_BWRAP_PATH in profile.mount_args) is expected
        assert profile.env["PATH"].startswith(str(Path(aa.CODEX_BWRAP_PATH).parent) + ":") is expected


@needs_codex_owner
def test_codex_aliases_keep_both_keyring_links_in_the_owned_route(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi

    captured = {}
    monkeypatch.setattr(pi, "_filtered_holder_namespace", lambda: 1)

    def launch(command, **kwargs):
        captured.update(command=command, **kwargs)
        return object()

    monkeypatch.setattr(pi, "launch_provider", launch)
    with _native_codex_profile(tmp_path, monkeypatch) as (provider, profile):
        pi.launch_owned([provider, "sandbox", "--", "true"],
                        role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=profile, cwd=tmp_path)
        command = captured["command"]
        assert command[0] == aa.CODEX_OWNER_PATH
        assert command[2:4] == ["-S", "/run/phase-loop-seat/keyring.py"]
        assert command[5] == aa.CODEX_OWNER_PATH
        assert "--cap-drop" not in command   # applied by the unchanged outer owner
        prefix = pi._compose_launch_prefix(tmp_path, captured["process_owner"])
        assert prefix[prefix.index("--cap-drop") + 1] == "ALL"
        assert "--unshare-net" not in prefix  # still uses the filtered egress namespace
        assert captured["child_scratch"] == pi._sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP


@needs_codex_owner
def test_codex_aliases_execute_with_empty_capabilities_and_keyring_filter(
        tmp_path, monkeypatch, owned_review_network):
    import json
    from phase_loop_runtime import panel_invoker as pi

    # A copied system Python image, not a provider: no inference or operator credentials.
    code = """import ctypes,errno,json,platform
from pathlib import Path
libc=ctypes.CDLL(None,use_errno=True)
rc=libc.syscall({'x86_64':250,'aarch64':219}[platform.machine()],1,0,0,0,0)
print(json.dumps({'cwd':str(Path.cwd()),'capabilities':{line.split(':')[0]:line.split(':')[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if line.startswith(('Cap','NoNewPrivs','Seccomp:'))},'keyctl_denied':rc==-1 and ctypes.get_errno()==errno.EPERM}))
"""
    with _native_codex_profile(tmp_path, monkeypatch, image="/usr/bin/python3") as (provider, profile):
        process = pi.launch_owned([provider, "-I", "-S", "-c", code],
                                  role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=profile,
                                  cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=30)
        finally:
            pi._terminate_process_group(process)
    assert process.returncode == 0, stderr
    separator = process.args.index("--", process.args.index("/usr/bin/bwrap"))
    assert process.args[separator + 1] == aa.CODEX_OWNER_PATH
    record = json.loads(stdout)
    assert Path(record["cwd"]) == tmp_path.resolve()
    assert record["keyctl_denied"]
    assert {key for key in record["capabilities"] if key.startswith("Cap")} == {
        "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
    assert all(value == "0000000000000000" for key, value in record["capabilities"].items()
               if key.startswith("Cap"))
    assert record["capabilities"]["NoNewPrivs"] == "1"
    assert record["capabilities"]["Seccomp"] == "2"


@needs_codex_owner
@pytest.mark.parametrize("same_cwd", [True, False, None])
def test_owned_cwd_handoff_is_removed_only_when_bwrap_already_sets_it(tmp_path, same_cwd):
    from phase_loop_runtime import panel_invoker as pi

    held = ("nsenter", "--", "/usr/bin/setpriv", "--bounding-set=-all", "--")
    token = pi._EGRESS_LAUNCH_PREFIX.set(held)
    try:
        owner_cwd = tmp_path if same_cwd else tmp_path / "different"
        owner = ["/usr/bin/bwrap", *(["--chdir", str(owner_cwd)] if same_cwd is not None else []), "--"]
        prefix = pi._compose_launch_prefix(tmp_path, owner)
        separator = prefix.index("--", prefix.index("/usr/bin/bwrap"))
        assert prefix[separator + 1:] == ([] if same_cwd else [
            "/usr/bin/env", "--chdir=" + str(tmp_path), "--"])
        assert prefix[prefix.index("--cap-drop") + 1] == "ALL"
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)


@pytest.mark.parametrize("script", [aa.install_script(codex=True), aa.revert_script(codex=True)])
def test_codex_scripts_are_valid_posix_sh(script):
    assert subprocess.run(["sh", "-n", "-c", script], capture_output=True, timeout=30).returncode == 0
