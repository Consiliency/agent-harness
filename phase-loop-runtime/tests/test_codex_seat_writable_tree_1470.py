"""OD-4 retires agent-harness#1470's inner-sandbox writable-tree grant."""
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi


@pytest.mark.parametrize("harness", ["codex", "grok", "gemini"])
@pytest.mark.parametrize("sandbox", ["workspace-write", "read-only", "danger-full-access"])
def test_stale_writable_tree_grant_is_refused_before_any_setup(tmp_path, monkeypatch, harness, sandbox):
    tree = tmp_path / "tree"
    tree.mkdir()
    out = tmp_path / "out"
    def unexpected(*args, **kwargs):
        pytest.fail("retired writable-tree grant reached credential or provider setup")
    monkeypatch.setattr(pi, "_seat_provider_source", unexpected)
    command = [harness, "exec", "--cd", str(tree), "--sandbox", sandbox]
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        with pi._seat_command_profile(command, env={}, cwd=tmp_path, outputs=(out,), writable_tree=tree):
            pytest.fail("retired grant admitted")
    assert not out.exists()


def test_retry_cannot_resurrect_a_checked_writable_tree_grant(tmp_path):
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        with pi._seat_command_profile(["codex"], env={}, cwd=tmp_path, writable_tree_checked=True):
            pytest.fail("checked-grant marker bypassed retirement")


def test_brokered_staged_codex_keeps_no_capabilities_or_writable_grants(tmp_path, monkeypatch):
    calls = []
    out = tmp_path / "out"
    out.mkdir()
    review = tmp_path / "review"
    (review / "reviewed-tree").mkdir(parents=True)
    def run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[command.index("--output-last-message") + 1]).write_text("AGREE")
        return pi._LegRun(0, "AGREE", "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pi, "_codex_command_sandbox_cannot_start", lambda *a, **k:
                        pytest.fail("sealed broker route probed an inner sandbox"))
    rc, text, _ = pi._exec_leg("codex", review, out, env={}, artifact="fixture",
                              broker_prompt="fixture", broker_evidence={})
    assert (rc, text) == (0, "AGREE")
    assert calls
    for command, kwargs in calls:
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert command[command.index("--cd") + 1] == str(out)
        assert not kwargs.get("retain_caps")
        assert "writable_tree" not in kwargs and "writable_tree_checked" not in kwargs


def _read_only_input_cannot_be_written(tmp_path, flag):
    import subprocess
    directory = tmp_path / "input"
    directory.mkdir()
    source = directory / "SOURCE"
    source.write_text("original")
    source.chmod(0o666)
    out = tmp_path / "out"
    out.mkdir()
    # Replace only the provider with a shell; the real profile parses Codex's input flag.
    command = ["/bin/sh", "-c", 'if printf changed > "$1/SOURCE"; then exit 7; fi; cat "$1/SOURCE"',
               "codex-fixture", str(directory), flag, str(directory), "--sandbox", "read-only"]
    with pi._seat_command_profile(command, env={"PATH": "/usr/bin:/bin"}, cwd=out,
                                  role=pi.SeatLaunchRole.PROVIDER_ADMIN) as (owned, profile):
        child = pi.launch_owned(owned, role=pi.SeatLaunchRole.PROVIDER_ADMIN, profile=profile,
                                cwd=str(out), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            stdout, stderr = child.communicate(timeout=20)
        finally:
            pi._terminate_process_group(child)
    assert child.returncode == 0, (stdout, stderr)
    assert stdout == b"original" and source.read_text() == "original"
    assert b"Read-only file system" in stderr


@pytest.mark.usefixtures("owned_review_network", "live_seat_attempt")
def test_the_unbrokered_read_only_codex_seat_still_cannot_write_its_tree(tmp_path):
    _read_only_input_cannot_be_written(tmp_path, "--cd")


@pytest.mark.usefixtures("owned_review_network", "live_seat_attempt")
def test_add_dir_is_never_writable(tmp_path):
    _read_only_input_cannot_be_written(tmp_path, "--add-dir")


def test_the_view_refuses_a_writable_tree_that_is_not_a_directory(tmp_path):
    from phase_loop_runtime import sandbox_egress
    bad = tmp_path / "not-a-directory"
    bad.write_text("fixture")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        pi._seat_filesystem_view(tmp_path, writable_trees=(bad,))
