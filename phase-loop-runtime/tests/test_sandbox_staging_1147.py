"""Sandbox staging must never spend RAM or fill a small filesystem (agent-harness#1147).

On dev0 `/tmp` is a 15 GiB tmpfs. Review scratch was staged there unconditionally, and the
retention ceiling was a fixed 40 GiB -- larger than the whole filesystem, so it could never
trigger. These tests pin the four properties the fix exists for, each at the level where
it lives or dies (the production `_default_spawn` / `_gc_stale_panel_scratch`, not only the
helpers), so each goes red on the code before the fix for the reason it claims:

* a tmpfs temp dir is not where a round stages; the platform's per-user cache dir is;
* the retention ceiling scales down on a small filesystem;
* an explicit staging override is honoured;
* a spawned agent CLI's own scratch (``TMPDIR``, ``CLAUDE_CODE_TMPDIR``) is moved off a
  RAM-backed temp dir, and never over a value the caller set.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import warnings
from pathlib import Path

import pytest

from phase_loop_runtime import sandbox_policy, sandbox_retention

GiB = 1024**3


def _fake_ram_mounts(monkeypatch, *ram_dirs: Path) -> None:
    """Report every path under ``ram_dirs`` as tmpfs and everything else as ext4."""
    roots = [os.path.realpath(d) for d in ram_dirs]

    def _fstype(path):
        real = os.path.realpath(path)
        return "tmpfs" if any(real == r or real.startswith(r + os.sep) for r in roots) else "ext4"

    monkeypatch.setattr(sandbox_policy, "_mount_fstype", _fstype, raising=False)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"], check=True,
    )
    return repo


def _run_a_sandboxed_leg(tmp_path, monkeypatch) -> dict[str, Path]:
    """Drive the production `_default_spawn` through staging; return where it staged."""
    from phase_loop_runtime import panel_invoker, review_stage
    from phase_loop_runtime.advisor_board import backing

    repo = _repo(tmp_path)
    seen: dict[str, Path] = {}

    def _capture(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
        seen["base"] = Path(review_dir).parent
        return 0, "ok", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", _capture)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
    auth = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=review_stage.review_tree_manifest_sha256(repo),
    )
    seen["result"] = panel_invoker._default_spawn(
        "gemini", "BODY", repo_dir=repo,
        review_authorization=auth, canonical_repo_authority=repo,
    )
    return seen


def _inside(path: Path, root: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root))


class TestStagingRoot:
    def test_a_tmpfs_temp_dir_is_not_where_a_round_stages(self, tmp_path, monkeypatch):
        fake_tmp = tmp_path / "tmp"
        fake_tmp.mkdir()
        cache = tmp_path / "cache"
        monkeypatch.setattr(tempfile, "tempdir", str(fake_tmp))
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _fake_ram_mounts(monkeypatch, fake_tmp)

        seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)

        assert "base" in seen, f"the leg never staged: {seen.get('result')!r}"
        assert not _inside(seen["base"], fake_tmp), "a round staged into a tmpfs"
        assert _inside(seen["base"], cache / "phase-loop" / "sandboxes")

    def test_an_explicit_override_is_honoured_even_on_tmpfs(self, tmp_path, monkeypatch):
        chosen = tmp_path / "chosen"
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(chosen))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        _fake_ram_mounts(monkeypatch, chosen)
        # The fake makes this host's real disk look like RAM, whose raised floor it may not
        # meet; placement is what is under test here, not the floor.
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", "1")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)

        assert "base" in seen, f"the leg never staged: {seen.get('result')!r}"
        assert Path(os.path.realpath(seen["base"])).parent == Path(os.path.realpath(chosen))
        assert any("RAM-backed" in str(w.message) for w in caught), "honoured silently"

    @pytest.mark.parametrize("platform, expected", [
        ("linux", Path(".cache")),
        ("darwin", Path("Library") / "Caches"),
        ("win32", Path("AppData") / "Local"),
    ])
    def test_the_platform_user_cache_dir_is_chosen(self, tmp_path, monkeypatch, platform, expected):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.setattr(sandbox_policy.Path, "home", classmethod(lambda cls: home))
        monkeypatch.setattr(sandbox_policy.sys, "platform", platform)
        _fake_ram_mounts(monkeypatch)

        assert sandbox_policy.staging_root() == home / expected / "phase-loop" / "sandboxes"

    def test_localappdata_wins_on_windows(self, tmp_path, monkeypatch):
        local = tmp_path / "Local"
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.setattr(sandbox_policy.sys, "platform", "win32")
        assert sandbox_policy.staging_root() == local / "phase-loop" / "sandboxes"

    def test_only_linux_mount_tables_count_as_ram(self, tmp_path, monkeypatch):
        _fake_ram_mounts(monkeypatch, tmp_path)
        assert sandbox_policy.is_ram_backed(tmp_path)
        for platform in ("darwin", "win32"):
            monkeypatch.setattr(sandbox_policy.sys, "platform", platform)
            assert not sandbox_policy.is_ram_backed(tmp_path)

    def test_a_tmpfs_cache_is_skipped_too(self, tmp_path, monkeypatch):
        """Not a path-name rule: whichever candidate is RAM-backed is passed over."""
        cache = tmp_path / "cache"
        disk_tmp = tmp_path / "tmp"
        disk_tmp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(disk_tmp))
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        _fake_ram_mounts(monkeypatch, cache)

        assert sandbox_policy.staging_root() == disk_tmp

    def test_when_only_ram_is_left_the_least_bad_is_used_clamped_and_never_crashes(
        self, tmp_path, monkeypatch,
    ):
        """Every candidate RAM-backed: the round still runs, one warning says why, and
        retention there is clamped to a tenth of the filesystem with a quarter kept free."""
        fake_tmp = tmp_path / "tmp"
        fake_tmp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(fake_tmp))
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES", raising=False)
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", "1")  # see the override test
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", set())
        _fake_ram_mounts(monkeypatch, tmp_path)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)
            root = sandbox_policy.staging_root()

        assert "base" in seen, f"the round failed instead of degrading: {seen.get('result')!r}"
        assert _inside(seen["base"], root)
        ram = [w for w in caught if "RAM-backed or unwritable" in str(w.message)]
        assert len(ram) == 1, [str(w.message) for w in caught]
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES")
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 15 * GiB)
        assert sandbox_policy.effective_max_total_bytes(root) == int(15 * GiB * 0.10)
        assert sandbox_policy.effective_floor_bytes(root) == int(15 * GiB * 0.25)


class TestMountinfo:
    def test_the_fstype_comes_from_the_longest_mountpoint_and_the_last_overmount(
        self, tmp_path, monkeypatch,
    ):
        target = tmp_path / "a b" / "deep"
        target.mkdir(parents=True)
        mount = str(tmp_path / "a b").replace(" ", "\\040")
        info = tmp_path / "mountinfo"
        info.write_text(
            "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n"
            f"2 1 0:1 / {mount} rw - ext4 /dev/sdb rw\n"
            f"3 1 0:2 / {mount} rw shared:1 - tmpfs tmpfs rw\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(sandbox_policy, "_MOUNTINFO", info)
        assert sandbox_policy._mount_fstype(target) == "tmpfs"
        assert sandbox_policy._mount_fstype(tmp_path) == "ext4"
        assert sandbox_policy.is_ram_backed(target / "not-yet-created")

    def test_no_mount_table_is_unknown_not_tmpfs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_MOUNTINFO", tmp_path / "absent")
        assert sandbox_policy._mount_fstype(tmp_path) is None
        assert sandbox_policy.is_ram_backed(tmp_path) is False


def _marked(root: Path, name: str, *, age_s: float, owner_pid: int | None = None) -> Path:
    box = root / name
    (box / "work").mkdir(parents=True)
    (box / "work" / "notes.md").write_text("n\n", encoding="utf-8")
    if owner_pid is None:
        sandbox_retention.mark_as_sandbox(box)
    else:
        sandbox_retention.mark_as_sandbox(box, owner_pid=owner_pid)
    old = time.time() - age_s
    os.utime(box, (old, old))
    return box


class TestRelativeCaps:
    def test_the_retention_cap_scales_down_on_a_small_filesystem(self, tmp_path, monkeypatch):
        """3 x 1.5 GiB retained on a 15 GiB filesystem is over a quarter of it (3.75 GiB),
        so the oldest goes -- where a fixed 40 GiB cap would keep all three forever."""
        from phase_loop_runtime import panel_invoker

        monkeypatch.delenv("PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES", raising=False)
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 15 * GiB, raising=False)
        monkeypatch.setattr(sandbox_retention, "_size_of", lambda p: 3 * GiB // 2)
        oldest = _marked(tmp_path, "pl-panel-a", age_s=3 * 3600)
        middle = _marked(tmp_path, "pl-panel-b", age_s=2 * 3600)
        newest = _marked(tmp_path, "pl-panel-c", age_s=1 * 3600)

        panel_invoker._gc_stale_panel_scratch(root=tmp_path)

        assert not oldest.exists(), "the relative cap never triggered"
        assert middle.exists() and newest.exists(), "reaped more than the cap requires"

    def test_a_live_round_is_never_reaped_by_the_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_retention, "_size_of", lambda p: 2 * GiB)
        live = _marked(tmp_path, "pl-panel-live", age_s=3 * 3600, owner_pid=os.getpid())
        cold = _marked(tmp_path, "pl-panel-cold", age_s=2 * 3600)
        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600, max_total_bytes=1)
        assert live.exists(), "the cap deleted a concurrent round's sandbox"
        assert not cold.exists()

    def test_a_recycled_pid_is_not_a_live_owner(self, tmp_path):
        box = _marked(tmp_path, "pl-panel-x", age_s=0, owner_pid=os.getpid())
        marker = box / sandbox_retention.SANDBOX_MARKER
        marker.write_text(
            marker.read_text(encoding="utf-8").replace("start=", "start=0"), encoding="utf-8",
        )
        if sandbox_retention._process_start(os.getpid()) is None:
            pytest.skip("no /proc start times on this platform")
        assert sandbox_retention._owner_alive(box) is False

    def test_the_cap_is_never_above_the_configured_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES", str(3 * GiB))
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 1000 * GiB)
        assert sandbox_policy.effective_max_total_bytes(tmp_path) == 3 * GiB

    def test_the_default_floor_scales_on_a_small_filesystem(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", raising=False)
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 4 * GiB)
        assert sandbox_policy.effective_floor_bytes(tmp_path) == 1 * GiB
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 1000 * GiB)
        assert sandbox_policy.effective_floor_bytes(tmp_path) == 2 * GiB

    def test_an_explicit_floor_is_used_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", str(3 * GiB))
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 4 * GiB)
        assert sandbox_policy.effective_floor_bytes(tmp_path) == 3 * GiB

    def test_cap_and_floor_always_fit_together(self):
        assert sandbox_policy._MAX_TOTAL_FRACTION + sandbox_policy._FLOOR_FRACTION <= 0.5
        assert sandbox_policy._RAM_MAX_TOTAL_FRACTION + sandbox_policy._FLOOR_FRACTION <= 0.5


def _slash_tmp_is_ram(monkeypatch):
    """Only the system default `/tmp` is a tmpfs; everything else (tmp_path included) is disk."""
    monkeypatch.setattr(
        sandbox_policy, "_mount_fstype",
        lambda p: "tmpfs" if os.path.realpath(p) == "/tmp" else "ext4", raising=False,
    )


def _child_envs(base):
    """Every production choke point that builds a spawned CLI's environment."""
    from phase_loop_runtime import harness_env_signatures, panel_invoker

    return {
        "leg": panel_invoker._subscription_env(dict(base)),
        "brokered": panel_invoker._broker_subscription_env(dict(base)),
        "executor": harness_env_signatures.child_executor_env(dict(base)),
    }


class TestChildCliScratch:
    """Claude Code writes its scratch to $CLAUDE_CODE_TMPDIR, else /tmp/claude-<uid>: on
    dev0 that was 6 GB of a 15 GB RAM `/tmp`, and it is what the OOM killer reaped."""

    def test_filled_when_the_temp_dir_is_ram_backed(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        _slash_tmp_is_ram(monkeypatch)
        base = {"HOME": str(tmp_path), "PATH": "/usr/bin", "XDG_CACHE_HOME": str(cache)}
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))

        for route, env in _child_envs(base).items():
            for name in ("TMPDIR", "CLAUDE_CODE_TMPDIR"):
                assert env.get(name) == str(cache / "phase-loop" / "tmp"), (route, name, env)
        assert (cache / "phase-loop" / "tmp").is_dir()

    def test_left_alone_on_disk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "ext4", raising=False)
        base = {"HOME": str(tmp_path), "PATH": "/usr/bin"}
        for route, env in _child_envs(base).items():
            assert "TMPDIR" not in env and "CLAUDE_CODE_TMPDIR" not in env, (route, env)

    def test_a_value_the_caller_set_is_never_overridden(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        _slash_tmp_is_ram(monkeypatch)
        from phase_loop_runtime import harness_env_signatures, panel_invoker

        both = {"TMPDIR": "/tmp", "CLAUDE_CODE_TMPDIR": "/tmp/mine", "PATH": "/usr/bin"}
        for env in (panel_invoker._subscription_env(dict(both)),
                    harness_env_signatures.child_executor_env(dict(both))):
            assert env["TMPDIR"] == "/tmp" and env["CLAUDE_CODE_TMPDIR"] == "/tmp/mine"
        only_tmpdir = {"TMPDIR": "/tmp", "PATH": "/usr/bin"}
        env = panel_invoker._subscription_env(only_tmpdir)
        assert env["TMPDIR"] == "/tmp", "the caller's TMPDIR was replaced"
        assert env["CLAUDE_CODE_TMPDIR"] == str(tmp_path / "cache" / "phase-loop" / "tmp")

    def test_the_brokered_allowlist_adds_only_the_runtime_dir(self, tmp_path, monkeypatch):
        """The sealed route's allowlist is not widened to ambient values: a caller's TMPDIR
        and CLAUDE_CODE_TMPDIR are still dropped, and what comes back is only the
        runtime's own per-user dir -- and only when the child's temp dir is RAM."""
        from phase_loop_runtime import panel_invoker

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        base = {"PATH": "/usr/bin", "HOME": str(tmp_path), "TMPDIR": "/ambient/tmp",
                "CLAUDE_CODE_TMPDIR": "/ambient/claude", "SOME_TOKEN": "x"}

        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "ext4", raising=False)
        on_disk = panel_invoker._broker_subscription_env(dict(base))
        assert set(on_disk) == {"PATH", "HOME"}, on_disk

        _slash_tmp_is_ram(monkeypatch)
        on_ram = panel_invoker._broker_subscription_env(dict(base))
        assert set(on_ram) == {"PATH", "HOME", "TMPDIR", "CLAUDE_CODE_TMPDIR"}, on_ram
        assert on_ram["TMPDIR"] == on_ram["CLAUDE_CODE_TMPDIR"] == str(cache / "phase-loop" / "tmp")

    def test_no_disk_backed_dir_leaves_the_env_alone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs")
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", {"tmp"})
        env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert env == {"PATH": "/usr/bin"}


class TestReapBeforeRefusing:
    def test_a_round_is_not_refused_while_retained_sandboxes_are_reclaimable(
        self, tmp_path, monkeypatch,
    ):
        """Free space counts only what is NOT held by a leftover: with it present the
        filesystem is below the floor, and reclaiming it is what makes room."""
        staging = tmp_path / "staging"
        staging.mkdir()
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", str(2 * GiB))
        leftover = _marked(staging, "pl-panel-leftover", age_s=3600)

        def _free(path):
            return 3 * GiB if not leftover.exists() else 1 * GiB

        monkeypatch.setattr(sandbox_policy, "_free_bytes", _free)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: _free(loc.path))

        seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)

        assert "base" in seen, f"refused while a reclaimable sandbox existed: {seen.get('result')!r}"
        assert not leftover.exists()

    def test_it_still_refuses_when_nothing_can_be_reclaimed(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        staging.mkdir()
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", str(2 * GiB))
        live = _marked(staging, "pl-panel-live", age_s=3600, owner_pid=os.getpid())
        monkeypatch.setattr(sandbox_policy, "_free_bytes", lambda p: 1 * GiB)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 1 * GiB)

        seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)

        assert "base" not in seen, "staged below the floor"
        assert live.exists(), "reclaimed a live round to make room"


class TestLegacyRootIsSwept:
    def test_both_the_staging_root_and_the_old_tmp_root_are_swept(self, tmp_path, monkeypatch):
        from phase_loop_runtime import panel_invoker

        staging = tmp_path / "staging"
        old_tmp = tmp_path / "tmp"
        staging.mkdir()
        old_tmp.mkdir()
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
        monkeypatch.setattr(tempfile, "tempdir", str(old_tmp))
        stale_new = _marked(staging, "pl-panel-new", age_s=48 * 3600)
        stale_old = _marked(old_tmp, "pl-panel-old", age_s=48 * 3600)

        panel_invoker._gc_stale_panel_scratch()

        assert not stale_old.exists(), "a pre-#1147 /tmp staging root was stranded"
        assert not stale_new.exists(), "the current staging root is not swept"
