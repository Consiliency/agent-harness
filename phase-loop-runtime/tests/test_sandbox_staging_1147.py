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
import sys
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


def _dev(path) -> str:
    st = os.stat(path)
    return f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"


class TestMountinfo:
    """The mount serving a path is found by DEVICE. Both layouts below leave a hidden disk
    entry that a longest-prefix or last-line rule picks instead of the visible tmpfs."""

    def _write(self, tmp_path, monkeypatch, lines):
        info = tmp_path / "mountinfo"
        info.write_text("".join(lines), encoding="utf-8")
        monkeypatch.setattr(sandbox_policy, "_MOUNTINFO", info)

    def test_a_tmpfs_over_a_dir_with_a_hidden_disk_submount(self, tmp_path, monkeypatch):
        top = tmp_path / "a b"
        (top / "sub").mkdir(parents=True)
        here = _dev(top / "sub")  # the device really serving the path: our "tmpfs"
        esc = str(top).replace(" ", "\\040")
        self._write(tmp_path, monkeypatch, [
            "1 0 999:1 / / rw - ext4 /dev/sda1 rw\n",
            f"2 1 999:2 / {esc} rw - ext4 /dev/sdb rw\n",
            f"3 2 999:3 / {esc}/sub rw - ext4 /dev/sdc rw\n",   # hidden by line 4
            f"4 2 {here} / {esc} rw - tmpfs tmpfs rw\n",
        ])
        assert sandbox_policy._mount_fstype(top / "sub") == "tmpfs"
        assert sandbox_policy.is_ram_backed(top / "sub" / "not-yet-created")

    def test_an_older_tmpfs_moved_over_a_newer_bind(self, tmp_path, monkeypatch):
        where = tmp_path / "m"
        where.mkdir()
        here = _dev(where)
        self._write(tmp_path, monkeypatch, [
            "1 0 999:1 / / rw - ext4 /dev/sda1 rw\n",
            f"5 1 {here} / {where} rw - tmpfs tmpfs rw\n",       # older id, moved on top
            f"9 1 999:1 /data {where} rw - ext4 /dev/sda1 rw\n",  # newer bind, underneath
        ])
        assert sandbox_policy._mount_fstype(where) == "tmpfs"

    def test_no_device_match_falls_back_to_the_visible_path(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, [
            "1 0 999:1 / / rw - ext4 /dev/sda1 rw\n",
            f"2 1 999:2 / {tmp_path} rw - btrfs /dev/sdb rw\n",
        ])
        assert sandbox_policy._mount_fstype(tmp_path) == "btrfs"

    def test_no_mount_table_is_unknown_not_tmpfs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_MOUNTINFO", tmp_path / "absent")
        assert sandbox_policy._mount_fstype(tmp_path) is None
        assert sandbox_policy.is_ram_backed(tmp_path) is False


_REAL_LAYOUT = r"""
set -e
root="$1"; disk="$root/disk"; mkdir -p "$disk/one" "$disk/two" "$root/a" "$root/t" "$root/m"
# Layout 1: a disk bind at a/, a disk submount at a/sub, then a tmpfs over a/.
# `-n`: no userspace mount table. Older util-linux cannot update it inside an unprivileged
# namespace and exits 16 even though the kernel mount succeeded (seen on the CI runner).
mount -n --bind "$disk/one" "$root/a"; mkdir -p "$root/a/sub"
mount -n --bind "$disk/two" "$root/a/sub"; mount -n -t tmpfs none "$root/a"; mkdir -p "$root/a/sub"
# Layout 2: an older tmpfs at t/ moved over a newer disk bind at m/.
mount -n -t tmpfs none "$root/t"; mount -n --bind "$disk/two" "$root/m"; mount -n --move "$root/t" "$root/m"
echo LAYOUT-READY
exec python3 -c 'import sys; from phase_loop_runtime import sandbox_policy as p
print(p._mount_fstype(sys.argv[1] + "/a/sub"), p._mount_fstype(sys.argv[1] + "/m"))' "$root"
"""


def test_real_overmount_layouts_in_a_mount_namespace(tmp_path, monkeypatch):
    """The two layouts the board reproduced, built for real, not as ordered fixtures."""
    import shutil as _shutil

    if _shutil.which("unshare") is None or not sys.platform.startswith("linux"):
        pytest.skip("needs unshare(1) on Linux")
    if subprocess.run(["unshare", "-rm", "true"], capture_output=True).returncode != 0:
        pytest.skip("unprivileged user+mount namespaces are unavailable here")
    monkeypatch.setattr(sandbox_policy, "_MOUNTINFO", Path("/proc/self/mountinfo"))
    if sandbox_policy.is_ram_backed(tmp_path):
        pytest.skip("tmp_path is itself tmpfs, so the 'disk' side would be RAM too")
    src = Path(sandbox_policy.__file__).resolve().parents[1]
    result = subprocess.run(
        ["unshare", "-rm", "sh", "-c", _REAL_LAYOUT, "sh", str(tmp_path)],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(src)},
    )
    if "LAYOUT-READY" not in result.stdout:
        # The kernel or sandbox refused to BUILD the layout; nothing about the probe ran.
        pytest.skip(f"cannot build the mount layout here: {result.stderr.strip()[:200]}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[1:] == ["tmpfs", "tmpfs"], result.stdout


class TestCapacityProbe:
    def test_the_relative_cap_applies_without_statvfs(self, tmp_path, monkeypatch):
        """Windows has no os.statvfs; the capacity probe must not depend on it. There,
        shutil.disk_usage is served by the OS's own call -- stood in for by the value this
        host measured before os.statvfs is removed."""
        import shutil as _shutil

        measured = _shutil.disk_usage(tmp_path)
        total = measured.total
        monkeypatch.delattr(os, "statvfs", raising=False)
        monkeypatch.setattr(_shutil, "disk_usage", lambda p: measured)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES", raising=False)
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "ext4", raising=False)
        assert sandbox_policy._fs_total_bytes(tmp_path) == total
        assert sandbox_policy.effective_max_total_bytes(tmp_path) == min(40 * GiB, int(total * 0.25))


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

    @pytest.mark.parametrize("total, ram", [
        (1 * GiB, True), (15 * GiB, True), (64 * GiB, True),
        (1 * GiB, False), (4 * GiB, False), (91 * GiB, False), (1000 * GiB, False),
    ])
    def test_the_effective_limits_always_fit_the_filesystem(self, tmp_path, monkeypatch, total, ram):
        """The EFFECTIVE cap and floor, not the fractions: together they never claim more
        than half the filesystem, and the floor never demands more than exists."""
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", raising=False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES", raising=False)
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: total)
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs" if ram else "ext4")
        cap = sandbox_policy.effective_max_total_bytes(tmp_path)
        floor = sandbox_policy.effective_floor_bytes(tmp_path)
        assert 0 < floor < total and 0 < cap
        assert cap + floor <= total // 2, (cap, floor, total)

    def test_a_floor_configured_at_exactly_the_default_is_not_scaled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", str(2 * GiB))
        monkeypatch.setattr(sandbox_policy, "_fs_total_bytes", lambda p: 4 * GiB)
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "ext4", raising=False)
        assert sandbox_policy.effective_floor_bytes(tmp_path) == 2 * GiB
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs", raising=False)
        assert sandbox_policy.effective_floor_bytes(tmp_path) == 2 * GiB

    def test_a_live_round_outlives_the_ttl(self, tmp_path):
        live = _marked(tmp_path, "pl-panel-long", age_s=48 * 3600, owner_pid=os.getpid())
        cold = _marked(tmp_path, "pl-panel-dead", age_s=48 * 3600)
        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600)
        assert live.exists(), "the TTL reaped a round whose owner is still running"
        assert not cold.exists()


class TestMarkerPublication:
    def test_a_half_written_marker_is_never_visible_to_a_concurrent_reap(self, tmp_path, monkeypatch):
        """The legal interleaving the board exercised: a reap runs after the marker file is
        created and before its owner line lands. Whatever the writer uses -- open(),
        Path.open, Path.write_text, Path.write_bytes or os.open -- the reap is run at
        that point."""
        import builtins
        import pathlib

        box = tmp_path / "pl-panel-live"
        (box / "work").mkdir(parents=True)

        def _reap_now():
            sandbox_retention.reap_until_free(
                tmp_path, floor_bytes=1, free_bytes=lambda p: 0,
            )

        real_open, real_write_text, real_os_open = builtins.open, pathlib.Path.write_text, os.open
        real_path_open = pathlib.Path.open

        def _path_open(self, mode="r", *a, **k):
            handle = real_path_open(self, mode, *a, **k)
            if any(c in mode for c in "wax") and self.parent == box:
                _reap_now()
            return handle

        def _open(file, mode="r", *a, **k):
            handle = real_open(file, mode, *a, **k)
            if "w" in mode and Path(file).parent == box:
                _reap_now()
            return handle

        def _write_text(self, data, *a, **k):
            if self.parent == box:
                real_open(self, "w").close()
                _reap_now()
            return real_write_text(self, data, *a, **k)

        def _os_open(path, flags, *a, **k):
            fd = real_os_open(path, flags, *a, **k)
            if flags & os.O_CREAT and Path(path).parent == box:
                _reap_now()
            return fd

        monkeypatch.setattr(sandbox_retention, "open", _open, raising=False)
        monkeypatch.setattr(pathlib.Path, "write_text", _write_text)
        monkeypatch.setattr(pathlib.Path, "open", _path_open)
        monkeypatch.setattr(sandbox_retention.os, "open", _os_open)

        try:
            sandbox_retention.mark_as_sandbox(box, owner_pid=os.getpid())
        except OSError:
            pass  # the old code's write lands in a directory the reap already removed
        assert box.exists(), "a concurrent reap deleted a live round through a half-written marker"
        assert sandbox_retention._owner_alive(box)


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
        "brokered": panel_invoker._broker_leg_env(dict(base), "claude"),
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
        on_disk = panel_invoker._broker_leg_env(dict(base), "claude")
        marker = sandbox_policy.CHILD_SCRATCH_MARKER  # every decided env is stamped
        assert set(on_disk) == {"PATH", "HOME", marker}, on_disk

        _slash_tmp_is_ram(monkeypatch)
        on_ram = panel_invoker._broker_leg_env(dict(base), "codex")
        assert set(on_ram) == {"PATH", "HOME", "TMPDIR", "CLAUDE_CODE_TMPDIR", marker}, on_ram
        assert on_ram["TMPDIR"] == on_ram["CLAUDE_CODE_TMPDIR"] == str(cache / "phase-loop" / "tmp")

        # A bounded Gemini leg runs on the host and is relocated like any leg. Only the
        # heartbeat seat (its jail has its own private /tmp) and the shared allowlist agy
        # qualification uses stay exactly the allowlist.
        assert panel_invoker._broker_leg_env(dict(base), "gemini")["TMPDIR"] == on_ram["TMPDIR"]
        # The heartbeat env is returned as built; its exception is stamped at the launch.
        assert set(panel_invoker._broker_leg_env(dict(base), "gemini", private_tmp=True)) == {
            "PATH", "HOME"}
        assert set(panel_invoker._broker_subscription_env(dict(base))) == {"PATH", "HOME"}

    def test_the_brokered_exec_route_fills_by_leg(self, tmp_path, monkeypatch):
        """Intercept `_exec_leg`'s brokered route at its auth preflight, per leg."""
        from phase_loop_runtime import panel_invoker

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        seen: dict[str, dict] = {}

        def _auth(leg, env):
            seen[leg] = dict(env)
            return False, "auth_failure"

        monkeypatch.setattr(panel_invoker, "_leg_auth_ok", _auth)
        review = tmp_path / "review"
        review.mkdir()
        (review / "review-bundle.md").write_text("x", encoding="utf-8")
        for leg in ("codex", "gemini"):
            panel_invoker._exec_leg(
                leg, review, tmp_path / "out", 60, "x", "review", None, None,
                {"PATH": "/usr/bin", "HOME": str(tmp_path)}, broker_prompt="p",
            )
        assert seen["codex"].get("TMPDIR") == str(cache / "phase-loop" / "tmp"), seen
        # Bounded (no review monitor): the Gemini leg runs on the host, so it is relocated.
        assert seen["gemini"].get("TMPDIR") == str(cache / "phase-loop" / "tmp"), seen

    def test_no_disk_backed_dir_leaves_the_env_alone_and_says_so_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs", raising=False)
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", set(), raising=False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", raising=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
            sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert env == {"PATH": "/usr/bin"}
        assert len([w for w in caught if "DEGRADED" in str(w.message)]) == 1

    def test_claude_scratch_is_judged_on_its_own_when_tmpdir_is_on_disk(self, tmp_path, monkeypatch):
        """A caller's disk TMPDIR does not move Claude's `/tmp/claude-<uid>` fallback."""
        from phase_loop_runtime import panel_invoker

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        disk_tmp = tmp_path / "disk-tmp"
        disk_tmp.mkdir()
        env = panel_invoker._subscription_env({"TMPDIR": str(disk_tmp), "PATH": "/usr/bin"})
        assert env["TMPDIR"] == str(disk_tmp)
        assert env.get("CLAUDE_CODE_TMPDIR") == str(cache / "phase-loop" / "tmp")

    def test_an_advisory_seats_explicit_env_is_filled_at_the_exec_boundary(self, tmp_path, monkeypatch):
        """Board seats hand `_exec_leg` their own `resolve_seat_env` dict; intercept the
        leg at its auth preflight and look at the env it would launch with."""
        from phase_loop_runtime import panel_invoker

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        seen = {}

        def _auth(leg, env):
            seen.update(env)
            return False, "auth_failure"

        monkeypatch.setattr(panel_invoker, "_leg_auth_ok", _auth)
        review = tmp_path / "review"
        review.mkdir()
        (review / "review-bundle.md").write_text("x", encoding="utf-8")
        panel_invoker._exec_leg(
            "gemini", review, tmp_path / "out", 60, "x", "advisory", None, None,
            {"PATH": "/usr/bin", "HOME": str(tmp_path)},
        )
        assert seen.get("TMPDIR") == seen.get("CLAUDE_CODE_TMPDIR") == str(cache / "phase-loop" / "tmp")

    def test_child_scratch_is_private_never_an_ambient_shared_dir(self, tmp_path, monkeypatch):
        """With the cache unusable the fallback is a 0700 per-user dir, not the temp dir."""
        shared = tmp_path / "shared"
        shared.mkdir()
        shared.chmod(0o1777)
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
        monkeypatch.setattr(tempfile, "tempdir", str(shared))
        _slash_tmp_is_ram(monkeypatch)
        env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        target = Path(env["TMPDIR"])
        assert target != shared and target.is_relative_to(shared)
        assert target.stat().st_mode & 0o777 == 0o700

        # Pre-existing and loosened (or planted by someone else as a link): tightened or
        # refused, never handed to a child as found.
        target.chmod(0o777)
        env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert Path(env["TMPDIR"]).stat().st_mode & 0o777 == 0o700
        target.rmdir()
        target.symlink_to(shared)
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", {"child scratch"})
        env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert "TMPDIR" not in env, "a symlinked scratch dir was handed to a child"

    def test_every_component_below_the_shared_dir_is_private(self, tmp_path, monkeypatch):
        """Under the shared temp dir, the per-user parent is held to the leaf's rule."""
        shared = tmp_path / "shared"
        shared.mkdir()
        shared.chmod(0o1777)
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
        monkeypatch.setattr(tempfile, "tempdir", str(shared))
        _slash_tmp_is_ram(monkeypatch)
        target = Path(sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})["TMPDIR"])
        parent = target.parent
        assert parent != shared and parent.parent == shared
        assert parent.stat().st_mode & 0o777 == 0o700

        parent.chmod(0o777)
        sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert parent.stat().st_mode & 0o777 == 0o700

        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "tmp").mkdir(parents=True, mode=0o700)
        elsewhere.chmod(0o700)
        target.rmdir()
        parent.rmdir()
        parent.symlink_to(elsewhere)
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", {"child scratch"})
        env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert "TMPDIR" not in env, "a scratch dir under a linked parent was handed to a child"

    def test_child_scratch_is_not_moved_onto_a_full_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", {"child scratch"})
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", raising=False)
        _slash_tmp_is_ram(monkeypatch)
        monkeypatch.setattr(sandbox_policy, "_free_bytes", lambda p: 0)
        assert sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


class TestRefuseRam:
    def test_fail_closed_refuses_a_round_instead_of_staging_into_ram(self, tmp_path, monkeypatch):
        fake_tmp = tmp_path / "tmp"
        fake_tmp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(fake_tmp))
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
        _fake_ram_mounts(monkeypatch, tmp_path)

        seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)

        assert "base" not in seen
        assert seen["result"][:2] == ("DEGRADED", "")
        assert seen["result"][2] == "env_failure: no disk-backed scratch and RAM fallback refused"

    def test_fail_closed_refuses_child_scratch_in_ram(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs", raising=False)
        with pytest.raises(sandbox_policy.SandboxRamBackedError):
            sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})

    def test_default_is_the_degraded_fallback_not_a_refusal(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", raising=False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", {"sandboxes"})
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        _fake_ram_mounts(monkeypatch, tmp_path)
        location = sandbox_policy.resolve_staging()
        assert location.degraded and _inside(location.path, tmp_path)


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

    def test_the_reap_before_refusing_archives_first(self, tmp_path, monkeypatch):
        """The production reap-before-refuse call keeps archive-before-reap."""
        staging = tmp_path / "staging"
        staging.mkdir()
        archive = tmp_path / "archive"
        archive.mkdir()
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_FLOOR_BYTES", str(2 * GiB))
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_ARCHIVE_DEST", str(archive))
        leftover = _marked(staging, "pl-panel-leftover", age_s=3600)

        def _free(path):
            return 3 * GiB if not leftover.exists() else 1 * GiB

        monkeypatch.setattr(sandbox_policy, "_free_bytes", _free)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: _free(loc.path))

        seen = _run_a_sandboxed_leg(tmp_path, monkeypatch)

        assert "base" in seen and not leftover.exists()
        assert any(archive.iterdir()), "reaped without archiving"

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


class TestClaudeSeatObservesItsTranscript:
    """With the stage under `~/.cache`, a Claude seat's cwd contains a dot. Claude Code
    names the transcript dir by mapping every character outside [A-Za-z0-9-] to "-"
    (observed: `/home/u/.cache/x/pl-panel-a_b/out` -> `-home-u--cache-x-pl-panel-a-b-out`).
    The adapter kept the dot, looked in a directory that never exists, never saw the
    seat's progress or its finished review, and the brokered seat hung until cancelled."""

    def test_progress_and_the_review_are_found_under_a_dotted_cwd(self, tmp_path, monkeypatch):
        import json as _json

        from phase_loop_runtime import panel_invoker

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(panel_invoker.Path, "home", classmethod(lambda cls: tmp_path))
        cwd = f"{tmp_path}/.cache/phase-loop/sandboxes/pl-panel-a_b.c/out"
        slug = cwd.replace("/", "-").replace(".", "-").replace("_", "-")
        project = tmp_path / ".claude" / "projects" / slug
        project.mkdir(parents=True)
        (project / "11111111-2222-4333-8444-555555555555.jsonl").write_text(
            _json.dumps({"type": "assistant", "message": {
                "role": "assistant", "content": [{"type": "text", "text": "REVIEW BODY\nAGREE"}],
            }}) + "\n",
            encoding="utf-8",
        )

        assert panel_invoker._claude_project_dir_for_cwd(cwd) == project
        assert panel_invoker._latest_claude_transcript_activity(cwd, since=0) > 0
        assert "REVIEW BODY" in panel_invoker._latest_claude_transcript_text(cwd, since=0)


class TestEveryAgentLaunchIsRelocated:
    """Round 2 (agent-harness#1161): bounded Gemini, the president, privacy of the whole
    runtime-created chain, and the remaining staging defaults."""

    def test_a_ram_backed_cache_is_not_where_child_scratch_goes(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        disk_tmp = tmp_path / "disk-tmp"
        disk_tmp.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        monkeypatch.setattr(tempfile, "tempdir", str(disk_tmp))
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs" if (
            os.path.realpath(p) == "/tmp" or Path(os.path.realpath(p)).is_relative_to(cache)
        ) else "ext4")
        # Room everywhere, so only the RAM check can rule the cache out (not this host's disk).
        monkeypatch.setattr(sandbox_policy, "_free_bytes", lambda p: 1 << 50)
        env = sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})
        assert Path(env["TMPDIR"]).is_relative_to(disk_tmp), env

    def test_a_bounded_agy_home_is_created_in_the_relocated_dir(self, tmp_path, monkeypatch):
        from phase_loop_runtime import panel_invoker

        home = tmp_path / "home"
        token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
        token.parent.mkdir(parents=True)
        token.write_text("reference", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        with panel_invoker._brokered_agy_environment({"TMPDIR": str(scratch)}, None) as env:
            assert Path(env["HOME"]).parent == scratch, env

    def test_the_bounded_gemini_president_is_relocated(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from phase_loop_runtime import panel_invoker, president_adapter

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        seen = {}

        def _launch(command, **kwargs):
            seen.update(kwargs["env"])
            raise OSError("stop at the launch")

        monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", _launch)
        fake_self = SimpleNamespace(base_env={"PATH": "/usr/bin", "HOME": str(tmp_path)})
        with pytest.raises(OSError):
            president_adapter.PresidentInvoke._launch_gemini(
                fake_self, "gemini-3.8-flash-high", "prompt", tmp_path)
        assert seen.get("TMPDIR") == str(cache / "phase-loop" / "tmp"), seen
        assert Path(seen["HOME"]).parent == cache / "phase-loop" / "tmp", seen

    def test_a_component_owned_by_another_account_is_refused(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        (cache / "phase-loop" / "tmp").mkdir(parents=True, mode=0o700)
        assert sandbox_policy._private(cache / "phase-loop" / "tmp", cache)  # control
        _owned_by_someone_else(monkeypatch, cache / "phase-loop")
        assert not sandbox_policy._private(cache / "phase-loop" / "tmp", cache)

    def test_the_staging_root_requires_real_directories_in_the_cache(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "sandboxes").mkdir(parents=True, mode=0o700)
        (cache / "phase-loop").symlink_to(elsewhere, target_is_directory=True)
        disk_tmp = tmp_path / "disk-tmp"
        disk_tmp.mkdir()
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        monkeypatch.setattr(tempfile, "tempdir", str(disk_tmp))
        assert sandbox_policy.resolve_staging().path == disk_tmp

    def test_a_review_stage_with_no_parent_uses_the_staging_root(self, tmp_path, monkeypatch):
        from phase_loop_runtime import review_stage

        root = tmp_path / "staging-root"
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(root))
        staged = review_stage.stage_review_tree(_repo(tmp_path))
        assert staged.parent == root, staged

    def test_the_capture_route_keeps_its_frozen_env(self, tmp_path, monkeypatch):
        """The agy capture jail (agent-harness#1179) is launched with the frozen decision."""
        from types import SimpleNamespace

        from phase_loop_runtime import panel_invoker

        _slash_tmp_is_ram(monkeypatch)
        seen = {}

        def _launch(command, **kwargs):
            seen["decision"] = kwargs.get("child_scratch")
            raise OSError("stop at the launch")

        authority = SimpleNamespace(
            rewrite_provider_output_path=lambda p: "/run/out",
            outer_environment=lambda: {"PATH": "/usr/bin"},
        )
        monkeypatch.setattr(panel_invoker, "_capture_provider_preflight", lambda a, c, l: c)
        monkeypatch.setattr(panel_invoker, "_record_capture_review_attempt", lambda *a, **k: None)
        monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", _launch)
        review = tmp_path / "review"
        review.mkdir()
        (review / "review-bundle.md").write_text("x", encoding="utf-8")
        with pytest.raises(OSError):
            panel_invoker._exec_leg(
                "codex", review, tmp_path / "out", 60, "x", "review", None, None,
                {"PATH": "/usr/bin"}, agy_capture=object(), provider_authority=authority,
            )
        assert seen["decision"] == sandbox_policy.CHILD_SCRATCH_FROZEN_CAPTURE

    def test_a_failing_scratch_probe_is_never_silent(self, tmp_path, monkeypatch):
        _slash_tmp_is_ram(monkeypatch)
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", set())

        def _boom():
            raise RuntimeError("probe broke")

        monkeypatch.setattr(sandbox_policy, "_child_tmp_dir", _boom)
        with pytest.warns(RuntimeWarning, match="scratch probe failed"):
            assert sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
        with pytest.raises(sandbox_policy.SandboxRamBackedError):
            sandbox_policy.fill_child_tmp_env({"PATH": "/usr/bin"})


def _record_scratch_script(seen: Path) -> list[str]:
    return ["/bin/sh", "-c",
            'printf "%s\\n%s\\n" "${TMPDIR-unset}" "${CLAUDE_CODE_TMPDIR-unset}" > "$0"', str(seen)]


class TestRound3Coverage:
    """Round 3 (agent-harness#1161): the Agent View executor route, and launches whose
    relocation no test pinned."""

    def test_the_agent_view_executor_launch_goes_through_the_provider_interface(
        self, tmp_path, monkeypatch,
    ):
        from phase_loop_runtime import panel_invoker
        from phase_loop_runtime.claude_agent_view import ClaudeAgentViewAdapter

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        calls = []
        real = panel_invoker.run_provider

        def _spy(argv, **kwargs):
            calls.append(argv)
            return real(argv, **kwargs)

        monkeypatch.setattr(panel_invoker, "run_provider", _spy)
        seen = tmp_path / "seen.txt"
        result = ClaudeAgentViewAdapter()._runner(
            _record_scratch_script(seen), cwd=str(tmp_path), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert result.returncode == 0 and len(calls) == 1
        assert seen.read_text(encoding="utf-8").splitlines() == [
            str(cache / "phase-loop" / "tmp")] * 2

    def test_the_print_executor_route_relocates_at_the_launch(self, tmp_path, monkeypatch):
        from phase_loop_runtime import launcher

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        seen = tmp_path / "seen.txt"
        launcher.launch(_record_scratch_script(seen), env={"PATH": "/usr/bin:/bin"})
        assert seen.read_text(encoding="utf-8").splitlines() == [
            str(cache / "phase-loop" / "tmp")] * 2

    def test_the_capture_preflight_probe_keeps_its_frozen_env(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from phase_loop_runtime import panel_invoker

        seen = {}

        def _launch(command, **kwargs):
            seen["decision"] = kwargs.get("child_scratch")
            return SimpleNamespace(returncode=0)

        def _preflight(command, *, probe_runner, publish):
            probe_runner(["probe"], {"PATH": "/usr/bin"}, 5)
            return command

        monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", _launch)
        latch = SimpleNamespace(execute_if_open=lambda *a, **k: None)
        panel_invoker._capture_provider_preflight(
            SimpleNamespace(preflight=_preflight), ["codex"], latch)
        assert seen["decision"] == sandbox_policy.CHILD_SCRATCH_FROZEN_CAPTURE

    def test_the_falsifier_dependency_snapshot_uses_the_staging_root(self, tmp_path, monkeypatch):
        from phase_loop_runtime import review_stage

        root = tmp_path / "staging-root"
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(root))
        where = {}
        monkeypatch.setattr(review_stage, "_falsifier_interpreter_scope", lambda: ("py", (), "id"))
        monkeypatch.setattr(review_stage, "_falsifier_interpreter_digest", lambda e, d: "digest")
        monkeypatch.setattr(review_stage, "_snapshot_falsifier_dependencies",
                            lambda stage, destination: where.setdefault("deps", destination))
        monkeypatch.setattr(review_stage, "_require_single_link_files", lambda roots: None)
        monkeypatch.setattr(review_stage, "_run_bounded_falsifier_node",
                            lambda **kwargs: (0, b"", b"", None, None))
        review_stage.run_bounded_falsifier_node(
            staged=tmp_path, nodeid="t::n", wall_clock_s=1, output_cap_bytes=1)
        assert Path(where["deps"]).parent == root

    def test_a_convergence_refusal_is_a_failed_envelope(self, tmp_path, monkeypatch):
        from phase_loop_runtime.convergence.adapters import (
            AdapterExecutionRequest, run_claude_adapter,
        )
        from phase_loop_runtime.convergence.contracts import AdmissionRequest

        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs")
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", set())
        admission = AdmissionRequest("a", 1, "f", "d", "head==abc", "repo", "key")
        request = AdapterExecutionRequest("a", admission, ("claude",), tmp_path, 10, "execute")
        envelope = run_claude_adapter(request)
        assert envelope.status.value == "failed"
        assert "RAM fallback is refused" in envelope.detail

    def test_the_credentialless_president_home_is_in_the_relocated_dir(self, tmp_path, monkeypatch):
        from phase_loop_runtime import president_adapter

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        with president_adapter._president_agy_environment({"TMPDIR": str(scratch)}) as env:
            assert Path(env["HOME"]).parent == scratch, env

    def test_an_empty_env_still_gets_the_decision(self, tmp_path, monkeypatch):
        from phase_loop_runtime import panel_invoker

        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        _slash_tmp_is_ram(monkeypatch)
        seen = tmp_path / "seen.txt"
        panel_invoker.run_provider(_record_scratch_script(seen), env={})
        assert seen.read_text(encoding="utf-8").splitlines() == [
            str(cache / "phase-loop" / "tmp")] * 2

    def test_a_base_others_may_write_must_be_sticky(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        base.chmod(0o777)
        assert not sandbox_policy._private(base / "phase-loop" / "tmp", base)
        base.chmod(0o1777)
        assert sandbox_policy._private(base / "phase-loop" / "tmp", base)

    def test_persistent_residue_is_swept_only_once_its_owner_is_gone(self, tmp_path, monkeypatch):
        """Owner, never age: a dead owner's copy goes; a live owner's copy and a copy with
        no owner record stay, however old; an orphaned owner record is dropped."""
        from phase_loop_runtime import panel_invoker

        staging = tmp_path / "staging"
        cache = tmp_path / "cache"
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        scratch = cache / "phase-loop" / "tmp"
        dead = subprocess.Popen(["true"])
        dead.wait()
        old = time.time() - 30 * 24 * 3600
        residue = [staging / "pl-review-stage-a", staging / "pl-falsifier-deps-b",
                   scratch / "phase-loop-broker-agy-c", scratch / "phase-loop-president-agy-d"]
        for path in residue:
            (path / "inner").mkdir(parents=True)
            sandbox_retention.claim_scratch_dir(path, owner_pid=dead.pid)
            os.utime(path, (old, old))
        live = staging / "pl-review-stage-live"
        (live / "inner").mkdir(parents=True)
        sandbox_retention.claim_scratch_dir(live)
        os.utime(live, (old, old))
        unclaimed = scratch / "phase-loop-broker-agy-unclaimed"
        unclaimed.mkdir(parents=True)
        os.utime(unclaimed, (old, old))
        orphan = staging / ("pl-review-stage-gone" + sandbox_retention.OWNER_SUFFIX)
        orphan.write_text("pid=1 start=\n", encoding="utf-8")
        panel_invoker._gc_stale_panel_scratch()
        assert not any(p.exists() for p in residue)
        assert not any(p.with_name(p.name + sandbox_retention.OWNER_SUFFIX).exists()
                       for p in residue)
        assert live.exists() and unclaimed.exists() and not orphan.exists()


class TestExceptionsAreDecidedAfterTheEnvIsBuilt:
    """Round 4 (agent-harness#1161): an env builder takes no scratch decision, so a ruled
    exception is never refused by a relocation it is exempt from."""

    @pytest.fixture(autouse=True)
    def _nothing_on_disk(self, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda path: "tmpfs")
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
        monkeypatch.setattr(sandbox_policy, "_RAM_FALLBACK_WARNED", set())

    def test_the_shared_allowlist_builder_takes_no_decision(self, tmp_path):
        from phase_loop_runtime import panel_invoker

        base = {"PATH": "/usr/bin", "HOME": str(tmp_path)}
        assert panel_invoker._broker_subscription_env(dict(base)) == base

    def test_a_relocated_route_is_still_refused(self, tmp_path):
        from phase_loop_runtime import panel_invoker

        with pytest.raises(sandbox_policy.SandboxRamBackedError):
            panel_invoker._broker_leg_env({"PATH": "/usr/bin", "HOME": str(tmp_path)}, "codex")

    def test_the_capture_route_with_no_env_reaches_its_frozen_launch(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from phase_loop_runtime import panel_invoker

        seen = {}

        def _launch(command, **kwargs):
            seen["decision"] = kwargs.get("child_scratch")
            raise OSError("stop at the launch")

        authority = SimpleNamespace(rewrite_provider_output_path=lambda p: "/run/out",
                                    outer_environment=lambda: {"PATH": "/usr/bin"})
        monkeypatch.setattr(panel_invoker, "_capture_provider_preflight", lambda a, c, l: c)
        monkeypatch.setattr(panel_invoker, "_record_capture_review_attempt", lambda *a, **k: None)
        monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", _launch)
        review = tmp_path / "review"
        review.mkdir()
        (review / "review-bundle.md").write_text("x", encoding="utf-8")
        with pytest.raises(OSError, match="stop at the launch"):
            panel_invoker._exec_leg(
                "codex", review, tmp_path / "out", 60, "x", "review", None, None, None,
                agy_capture=object(), provider_authority=authority,
            )
        assert seen["decision"] == sandbox_policy.CHILD_SCRATCH_FROZEN_CAPTURE


class TestPerRunScratchRecordsItsOwner:
    """Every per-run directory the residue sweep may remove records a live owner while in
    use, and drops the record once removed (agent-harness#1161 round 4)."""

    @staticmethod
    def _owned_by_us(path: Path) -> bool:
        return not sandbox_retention.scratch_owner_gone(path) and Path(
            str(path) + sandbox_retention.OWNER_SUFFIX).is_file()

    def test_the_launcher_review_copy(self, tmp_path, monkeypatch):
        from phase_loop_runtime import launcher

        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path / "staging"))
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("x\n", encoding="utf-8")
        staged = launcher._stage_review_tree(repo, None)
        assert self._owned_by_us(staged)
        launcher._cleanup_paths((str(staged),))
        assert not Path(str(staged) + sandbox_retention.OWNER_SUFFIX).exists()

    def test_the_owned_agy_home(self, tmp_path, monkeypatch):
        from phase_loop_runtime import panel_invoker

        home = tmp_path / "home"
        token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
        token.parent.mkdir(parents=True)
        token.write_text("reference", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        with panel_invoker._brokered_agy_environment({"TMPDIR": str(scratch)}, None) as env:
            agy_home = Path(env["HOME"])
            assert self._owned_by_us(agy_home)
        assert not Path(str(agy_home) + sandbox_retention.OWNER_SUFFIX).exists()

    def test_the_credentialless_president_home(self, tmp_path, monkeypatch):
        from phase_loop_runtime import president_adapter

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        with president_adapter._president_agy_environment({"TMPDIR": str(scratch)}) as env:
            empty = Path(env["HOME"])
            assert self._owned_by_us(empty)
        assert not Path(str(empty) + sandbox_retention.OWNER_SUFFIX).exists()

    def test_the_falsifier_dependency_snapshot(self, tmp_path, monkeypatch):
        from phase_loop_runtime import review_stage

        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path / "staging"))
        seen = {}
        monkeypatch.setattr(review_stage, "_falsifier_interpreter_scope", lambda: ("py", (), "id"))
        monkeypatch.setattr(review_stage, "_falsifier_interpreter_digest", lambda e, d: "digest")
        monkeypatch.setattr(review_stage, "_snapshot_falsifier_dependencies",
                            lambda stage, destination: seen.setdefault("deps", destination))
        monkeypatch.setattr(review_stage, "_require_single_link_files", lambda roots: None)

        def _run(**kwargs):
            seen["owned"] = self._owned_by_us(kwargs["dependencies"])
            return (0, b"", b"", None, None)

        monkeypatch.setattr(review_stage, "_run_bounded_falsifier_node", _run)
        review_stage.run_bounded_falsifier_node(
            staged=tmp_path, nodeid="t::n", wall_clock_s=1, output_cap_bytes=1)
        assert seen["owned"]
        assert not Path(str(seen["deps"]) + sandbox_retention.OWNER_SUFFIX).exists()


def test_a_private_base_under_a_shared_parent_is_refused(tmp_path):
    """The base's ancestors count too: a parent others may write (not sticky) lets them
    rename the whole base away after the check."""
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    base = shared / "cache"
    base.mkdir(mode=0o700)
    assert not sandbox_policy._private(base / "phase-loop" / "tmp", base)
    shared.chmod(0o1777)
    assert sandbox_policy._private(base / "phase-loop" / "tmp", base)


def _owned_by_someone_else(monkeypatch, target: Path) -> None:
    """Report ``target`` as owned by an account that is neither this one nor root -- by
    its stat result, so the check holds inside a user namespace too, where this account
    is mapped to root and every file looks root-owned."""
    import pathlib

    target = Path(os.path.realpath(target))
    other = os.getuid() + 4242
    real_stat, real_lstat = pathlib.Path.stat, pathlib.Path.lstat

    def _forge(result):
        fields = list(result)
        fields[4] = other  # st_uid
        return os.stat_result(fields)

    def _stat(self, *a, **k):
        result = real_stat(self, *a, **k)
        return _forge(result) if Path(os.path.realpath(self)) == target else result

    def _lstat(self):
        result = real_lstat(self)
        return _forge(result) if Path(os.path.realpath(self)) == target else result

    monkeypatch.setattr(pathlib.Path, "stat", _stat)
    monkeypatch.setattr(pathlib.Path, "lstat", _lstat)


def test_a_base_owned_by_another_account_is_refused(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()
    assert sandbox_policy._held_by_us_or_root(base)  # control
    _owned_by_someone_else(monkeypatch, base)
    assert not sandbox_policy._held_by_us_or_root(base)


def test_an_unreadable_owner_record_is_an_unknown_owner(tmp_path):
    copy = tmp_path / "pl-review-stage-x"
    copy.mkdir()
    record = Path(str(copy) + sandbox_retention.OWNER_SUFFIX)
    for text in ("garbage\n", "pid=notanumber start=\n", ""):
        record.write_text(text, encoding="utf-8")
        assert not sandbox_retention.scratch_owner_gone(copy), text


class TestRecordsAreCreatedExclusively:
    """Owner records and sandbox markers are created exclusively at an unpredictable
    staging name and never follow a link (agent-harness#1161)."""

    def test_a_link_or_file_at_a_staging_name_is_never_followed_or_truncated(
        self, tmp_path, monkeypatch,
    ):
        import secrets as _secrets

        scratch = tmp_path / "pl-review-stage-x"
        scratch.mkdir()
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me\n", encoding="utf-8")
        record = scratch.name + sandbox_retention.OWNER_SUFFIX
        names = iter(["planted-link", "planted-file", "fresh"])
        monkeypatch.setattr(_secrets, "token_hex", lambda n=8: next(names))
        (tmp_path / f"{record}.planted-link.tmp").symlink_to(victim)
        (tmp_path / f"{record}.planted-file.tmp").write_text("not ours to truncate\n",
                                                              encoding="utf-8")
        sandbox_retention.claim_scratch_dir(scratch)
        assert victim.read_text(encoding="utf-8") == "keep me\n"
        assert (tmp_path / f"{record}.planted-file.tmp").read_text(
            encoding="utf-8") == "not ours to truncate\n"
        assert not (tmp_path / f"{record}.fresh.tmp").exists()  # renamed into place
        assert not sandbox_retention.scratch_owner_gone(scratch)
        assert (tmp_path / record).read_text(encoding="utf-8").startswith(f"pid={os.getpid()} ")

    def test_no_free_staging_name_fails_closed_with_a_typed_reason(self, tmp_path, monkeypatch):
        import secrets as _secrets

        scratch = tmp_path / "pl-review-stage-y"
        scratch.mkdir()
        record = scratch.name + sandbox_retention.OWNER_SUFFIX
        monkeypatch.setattr(_secrets, "token_hex", lambda n=8: "taken")
        (tmp_path / f"{record}.taken.tmp").write_text("x", encoding="utf-8")
        with pytest.raises(sandbox_retention.ScratchRecordError, match="no free staging name"):
            sandbox_retention.claim_scratch_dir(scratch)
        assert not (tmp_path / record).exists()

    def test_a_rename_that_cannot_land_fails_closed_and_leaves_no_staging_file(
        self, tmp_path, monkeypatch,
    ):
        scratch = tmp_path / "pl-review-stage-z"
        scratch.mkdir()
        (tmp_path / (scratch.name + sandbox_retention.OWNER_SUFFIX)).mkdir()  # cannot be replaced
        with pytest.raises(sandbox_retention.ScratchRecordError, match="could not publish"):
            sandbox_retention.claim_scratch_dir(scratch)
        assert not list(tmp_path.glob("*.tmp"))

    def test_a_record_that_is_a_link_or_not_ours_is_an_unknown_owner(self, tmp_path, monkeypatch):
        scratch = tmp_path / "pl-review-stage-w"
        scratch.mkdir()
        record = tmp_path / (scratch.name + sandbox_retention.OWNER_SUFFIX)
        dead = subprocess.Popen(["true"])
        dead.wait()
        target = tmp_path / "elsewhere"
        target.write_text(f"pid={dead.pid} start=\n", encoding="utf-8")
        record.symlink_to(target)
        assert not sandbox_retention.scratch_owner_gone(scratch)  # a link: never followed
        record.unlink()
        record.write_text(f"pid={dead.pid} start=\n", encoding="utf-8")
        assert sandbox_retention.scratch_owner_gone(scratch)  # control: ours, dead owner
        real_fstat = os.fstat

        def _fstat(fd):
            result = real_fstat(fd)
            fields = list(result)
            fields[4] = os.getuid() + 4242
            return os.stat_result(fields)

        monkeypatch.setattr(os, "fstat", _fstat)
        assert not sandbox_retention.scratch_owner_gone(scratch)  # another account's record

    def test_release_never_removes_a_link_or_another_accounts_record(self, tmp_path):
        scratch = tmp_path / "pl-review-stage-v"
        record = tmp_path / (scratch.name + sandbox_retention.OWNER_SUFFIX)
        target = tmp_path / "target"
        target.write_text("x", encoding="utf-8")
        record.symlink_to(target)
        sandbox_retention.release_scratch_dir(scratch)
        assert record.is_symlink() and target.exists()

    def test_the_sandbox_marker_uses_the_same_exclusive_publication(self, tmp_path, monkeypatch):
        import secrets as _secrets

        box = tmp_path / "pl-panel-box"
        box.mkdir()
        victim = tmp_path / "victim"
        victim.write_text("keep\n", encoding="utf-8")
        names = iter(["planted", "fresh"])
        monkeypatch.setattr(_secrets, "token_hex", lambda n=8: next(names))
        (box / f"{sandbox_retention.SANDBOX_MARKER}.planted.tmp").symlink_to(victim)
        sandbox_retention.mark_as_sandbox(box, owner_pid=os.getpid())
        assert victim.read_text(encoding="utf-8") == "keep\n"
        assert sandbox_retention._owner_alive(box)


@pytest.mark.parametrize("code", ["EACCES", "ENOSPC", "EROFS"])
@pytest.mark.parametrize("step", ["create", "write", "fsync", "replace"])
def test_every_publication_failure_is_typed_and_leaves_no_stage(tmp_path, monkeypatch, code, step):
    """Round 9 (agent-harness#1161): whichever step fails, with whichever errno, the claim
    raises ScratchRecordError, leaves no staging file and no record; a name collision
    alone still retries on a fresh name."""
    import errno

    scratch = tmp_path / "pl-review-stage-e"
    scratch.mkdir()
    error = OSError(getattr(errno, code), os.strerror(getattr(errno, code)))
    real = {"create": os.open, "write": os.write, "fsync": os.fsync, "replace": os.replace}

    def failing(*args, **kwargs):
        if step == "create" and not (args[1] & os.O_CREAT):
            return real["create"](*args, **kwargs)
        raise error

    monkeypatch.setattr(os, {"create": "open"}.get(step, step), failing)
    with pytest.raises(sandbox_retention.ScratchRecordError, match="could not publish"):
        sandbox_retention.claim_scratch_dir(scratch)
    monkeypatch.undo()
    assert not list(tmp_path.glob("*.tmp"))
    assert not (tmp_path / (scratch.name + sandbox_retention.OWNER_SUFFIX)).exists()
