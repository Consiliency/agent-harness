import os
import tempfile
from pathlib import Path

from phase_loop_runtime import launcher, sandbox_policy


def test_launcher_review_stage_avoids_ram_when_disk_is_usable(tmp_path, monkeypatch):
    ram = tmp_path / "ram"
    ram.mkdir()
    cache = tmp_path / "cache"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("x = 1\n")
    monkeypatch.setattr(tempfile, "tempdir", str(ram))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
    monkeypatch.setattr(
        sandbox_policy, "_mount_fstype",
        lambda p: "tmpfs" if Path(os.path.realpath(p)).is_relative_to(ram) else "ext4",
    )
    assert not sandbox_policy.resolve_staging().degraded
    command = ["agy", "--add-dir", launcher.GEMINI_REVIEW_STAGE_PREFIX + str(repo)]
    staged_command = launcher._resolve_review_stage(
        command, launcher.GEMINI_REVIEW_STAGE_PREFIX, None,
    )
    staged = Path(staged_command[2])
    assert (staged / "source.py").read_text() == "x = 1\n"
    assert not sandbox_policy.is_ram_backed(staged), str(staged)
