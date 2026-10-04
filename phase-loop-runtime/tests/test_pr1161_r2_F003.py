import os
import tempfile

from phase_loop_runtime import sandbox_policy


def test_preplanted_cache_parent_is_rejected(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o1777)
    shared.chmod(0o1777)
    planted = tmp_path / "planted"
    (planted / "tmp").mkdir(parents=True, mode=0o700)
    (shared / "phase-loop").symlink_to(planted, target_is_directory=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(shared))
    monkeypatch.setattr(tempfile, "tempdir", str(shared))
    monkeypatch.setattr(
        sandbox_policy, "_mount_fstype",
        lambda p: "tmpfs" if os.path.realpath(p) == "/tmp" else "ext4",
    )
    env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
    assert env.get("TMPDIR") != str(shared / "phase-loop/tmp"), env
