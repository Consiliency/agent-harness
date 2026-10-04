import subprocess
import time

from phase_loop_runtime import launcher, panel_invoker, sandbox_policy


def test_active_launcher_review_stage_survives_crash_sweep(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    monkeypatch.setattr(sandbox_policy, "_user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(sandbox_policy, "legacy_staging_root", lambda: staging)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("x = 1\n")
    active = launcher._stage_review_tree(repo, None)
    created = active.stat().st_mtime
    with subprocess.Popen(["/bin/sh", "-c", "read hold; test -f source.py"],
                          cwd=active, stdin=subprocess.PIPE) as child:
        assert child.poll() is None
        monkeypatch.setattr(time, "time", lambda: created + 2 * 24 * 3600)
        panel_invoker._gc_stale_panel_scratch()
        child.communicate(b"continue\n", timeout=5)
        assert child.returncode == 0, "live launcher review stage was reaped"
