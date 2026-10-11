"""The placement lease journal and its reaper (agent-harness#896, amendment C6).

A lease is one file, fsynced with its directory before the first call with a remote
effect and held under `flock` by the owning process. The reaper decides by lease lock,
never by a pid, an age or whether a sandbox reference was recorded: a held lease is live,
a free one is the reaper's, and an entry is cleared only when a kill by that lease id was
acknowledged and nothing is listed for it.

The backend here is an in-process fake of a far side that tags what it holds by owner and
lease. The owner that dies is a real process, killed with SIGKILL.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import cli, placement_lease, sandbox_policy
from phase_loop_runtime import sandbox_placement as sp

ROOT = "resto://stage-host.invalid:2200/srv/stage"
TIMEOUT = "sandbox_placement_operation_timeout"


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # No root from the environment, and none from the user's own configuration.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for name in ("ROOT", "REMOTE_REQUIRED"):
        monkeypatch.delenv(f"PHASE_LOOP_SANDBOX_{name}", raising=False)


def _root(text: str = ROOT):
    return sandbox_policy.candidate_roots([("stage", text)])[0]


def _entry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def _files() -> list[str]:
    directory = placement_lease._lease_dir()
    return sorted(os.listdir(directory)) if directory.is_dir() else []


def _locked(path: Path) -> bool:
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def _bound(timeout_s: float = 5.0) -> sp.OperationBound:
    return sp.OperationBound(timeout_s, threading.Event())


class Remote:
    """What a far side holds: `(owner, lease) -> sandbox`. `kill` fences and removes; a
    listing is filtered by owner and arrives in pages. An EMPTY owner filter lists
    everything, as a real listing API does when the filter is dropped."""

    def __init__(self) -> None:
        self.sandboxes: dict[str, tuple[str, str]] = {}     # lease -> (owner, ref)
        self.calls: list[tuple] = []
        self.kill_fails: set[str] = set()
        self.kill_is_noop: set[str] = set()
        self.fenced: set[str] = set()
        self.page_size = 1

    def hold(self, owner: str, lease_id: str, ref: str) -> None:
        self.sandboxes[lease_id] = (owner, ref)

    def list_owned(self, owner_id, bound):
        self.calls.append(("list_owned", owner_id))
        rows = [(ref, lease_id) for lease_id, (owner, ref) in self.sandboxes.items()
                if not owner_id or owner == owner_id]

        def pages():
            for start in range(0, len(rows), self.page_size):
                yield from rows[start:start + self.page_size]

        return pages()

    def kill(self, lease_id, bound):
        self.calls.append(("kill", lease_id))
        if lease_id in self.kill_fails:
            raise sp.PlacementUnavailable(TIMEOUT)
        self.fenced.add(lease_id)
        if lease_id not in self.kill_is_noop:
            self.sandboxes.pop(lease_id, None)

    def killed(self) -> list[str]:
        return [call[1] for call in self.calls if call[0] == "kill"]


class Lookup:
    """`backends(scheme)`, counting how often the reaper asks."""

    def __init__(self, remote: Remote | None) -> None:
        self.remote = remote
        self.asked: list[str] = []

    def __call__(self, scheme: str):
        self.asked.append(scheme)
        return self.remote


# --------------------------------------------------------------------------------------
# The owner id.
# --------------------------------------------------------------------------------------

def test_the_owner_id_is_random_created_once_and_private(tmp_path, monkeypatch):
    first = placement_lease.owner_id()
    path = tmp_path / "state" / "phase-loop" / "placement-owner-id"
    assert len(first) == 32 and int(first, 16) >= 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="ascii").strip() == first
    placement_lease._OWNER.clear()
    assert placement_lease.owner_id() == first              # read back, not regenerated
    # It names no user and no host.
    assert os.environ.get("USER", "\0") not in first and os.uname().nodename not in first
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "another-state"))
    assert placement_lease.owner_id() != first


def test_a_malformed_or_foreign_owner_id_is_refused(tmp_path):
    path = tmp_path / "state" / "phase-loop" / "placement-owner-id"
    path.parent.mkdir(parents=True)
    path.write_text("../../not-an-id\n", encoding="ascii")
    with pytest.raises(ValueError):
        placement_lease.owner_id()
    path.unlink()
    path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        placement_lease.owner_id()


# --------------------------------------------------------------------------------------
# One lease.
# --------------------------------------------------------------------------------------

def test_a_lease_is_one_private_file_synced_with_its_directory_before_it_is_returned(monkeypatch):
    """The entry is written under a pending name, synced, renamed into place, and its
    directory synced, in that order. Mutation: return before the directory is synced."""
    order: list[str] = []
    real_fsync, real_rename = placement_lease._fsync, os.rename

    def fsync(fd):
        order.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def rename(src, dst, **kwargs):
        order.append("rename")
        return real_rename(src, dst, **kwargs)

    owner = placement_lease.owner_id()
    monkeypatch.setattr(placement_lease, "_fsync", fsync)
    monkeypatch.setattr(os, "rename", rename)
    before = time.time()
    lease = placement_lease.open_lease("stage", _root())
    assert order == ["fsync-file", "rename", "fsync-dir"]
    directory = placement_lease._lease_dir()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(lease.path.stat().st_mode) == 0o600
    assert _files() == [f"{lease.lease_id}.json"] and lease.path.parent == directory
    entry = _entry(lease.path)
    assert set(entry) == {
        "lease_id", "backend", "root", "sandbox_ref", "created_at", "confirmed_killed_at",
        "abandoned",
    }
    assert (entry["lease_id"], entry["backend"], entry["root"]) == (lease.lease_id, "stage", ROOT)
    assert (entry["sandbox_ref"], entry["confirmed_killed_at"], entry["abandoned"]) == (None, None, False)
    assert before <= entry["created_at"] <= time.time()
    assert lease.owner_id == owner and lease.held and not lease.fenced
    assert _locked(lease.path)
    assert len({placement_lease.open_lease("stage", _root()).lease_id for _ in range(5)}) == 5


def test_the_journal_never_holds_the_configured_text(tmp_path):
    for written in ("resto://operator:s3cret@stage-host.invalid:2200/srv/stage?token=qvalue#fragpart",
                    _root("resto://operator:s3cret@stage-host.invalid:2200/srv/stage?token=qvalue")):
        lease = placement_lease.open_lease(None, written)
        text = lease.path.read_text(encoding="utf-8")
        assert _entry(lease.path)["root"] == ROOT and _entry(lease.path)["backend"] == ""
        for leak in ("s3cret", "operator", "token", "qvalue", "fragpart"):
            assert leak not in text


def test_the_reference_and_the_kill_are_recorded_and_the_lock_follows_the_lease():
    lease = placement_lease.open_lease("stage", _root())
    lease.record_sandbox_ref("sbx-1")
    lease.note_killed()
    entry = _entry(lease.path)
    assert entry["sandbox_ref"] == "sbx-1" and entry["confirmed_killed_at"] is not None
    # A shorter rewrite leaves one complete line, not a tail of the longer one.
    lease.record_sandbox_ref("s")
    assert lease.path.read_text(encoding="utf-8").count("\n") == 1
    assert _entry(lease.path)["sandbox_ref"] == "s"

    lease.abandon()
    assert lease.fenced and not lease.held and not _locked(lease.path)
    assert _entry(lease.path)["abandoned"] is True
    lease.record_sandbox_ref("after")                      # no longer this process's entry
    assert _entry(lease.path)["sandbox_ref"] == "s"

    cleared = placement_lease.open_lease("stage", _root())
    cleared.clear()
    assert not cleared.held and not cleared.path.exists()
    cleared.clear()                                        # again: nothing to do, no error


def test_a_lease_directory_that_is_a_link_or_someone_elses_is_refused(tmp_path, monkeypatch):
    directory = placement_lease._lease_dir()
    directory.parent.mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    directory.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        placement_lease.open_lease("stage", _root())
    assert os.listdir(tmp_path / "elsewhere") == []
    directory.unlink()

    directory.mkdir(mode=0o755)
    with monkeypatch.context() as patch:
        patch.setattr(os, "geteuid", lambda: os.getuid() + 1)
        with pytest.raises(PermissionError):
            placement_lease.open_lease("stage", _root())
    assert _files() == []
    lease = placement_lease.open_lease("stage", _root())   # this user's and too open: tightened
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    lease.clear()


# --------------------------------------------------------------------------------------
# The heartbeat.
# --------------------------------------------------------------------------------------

def test_the_heartbeat_renews_while_the_lock_is_held_and_stops_with_the_leg():
    lease = placement_lease.open_lease("stage", _root())
    beats: list[float] = []
    stop = lease.heartbeat(lambda: beats.append(time.monotonic()), 0.02)
    time.sleep(0.2)
    stop()
    time.sleep(0.05)
    count = len(beats)
    assert count >= 3
    time.sleep(0.1)
    assert len(beats) == count                              # stopped with the leg

    released: list[int] = []
    other = placement_lease.open_lease("stage", _root())
    other.heartbeat(lambda: released.append(1), 0.02)
    other.abandon()                                         # the lock is given up
    time.sleep(0.15)
    assert len(released) <= 1                               # at most one in flight
    lease.clear()


def test_the_heartbeat_gives_up_on_a_time_out_and_goes_on_after_another_failure():
    lease = placement_lease.open_lease("stage", _root())
    attempts: list[str] = []

    def failing():
        attempts.append("x")
        raise RuntimeError("a refused renewal")

    stop = lease.heartbeat(failing, 0.02)
    time.sleep(0.15)
    stop()
    assert len(attempts) >= 3

    timed_out: list[str] = []

    def timing_out():
        timed_out.append("x")
        raise sp.PlacementUnavailable(TIMEOUT)

    stop = lease.heartbeat(timing_out, 0.02)
    time.sleep(0.15)
    stop()
    assert timed_out == ["x"]
    lease.clear()


# --------------------------------------------------------------------------------------
# The reaper.
# --------------------------------------------------------------------------------------

def test_reap_with_nothing_free_contacts_nothing(monkeypatch):
    """An empty lease directory, and one holding only live leases: zero backend calls, and
    the lookup is never asked, so no plugin is imported. Mutation: call `list_owned`
    unconditionally."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no plugin is loaded while no lease is free")

    monkeypatch.setattr(sp, "_load_plugins", forbidden)
    monkeypatch.setattr(sp, "_entry_points", forbidden)
    lookup = Lookup(Remote())
    assert placement_lease.reap(lookup, _bound()) == {"cleared": (), "kept": ()}
    live = [placement_lease.open_lease("stage", _root()) for _ in range(3)]
    assert placement_lease.reap(lookup, _bound()) == {"cleared": (), "kept": ()}
    assert lookup.asked == [] and lookup.remote.calls == []
    assert _files() == sorted(f"{lease.lease_id}.json" for lease in live)
    assert all(lease.held and _locked(lease.path) for lease in live)
    # The command, with a remote root configured and only live leases: the same.
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", ROOT)
    assert cli.main(["placement", "reap"]) == 0


_DYING_OWNER = r"""
import sys, time
from phase_loop_runtime import placement_lease, sandbox_policy
root = sandbox_policy.candidate_roots([("stage", sys.argv[1])])[0]
lease = placement_lease.open_lease("stage", root)
# `commit` has returned on the far side; the reference is NOT recorded yet.
print(lease.owner_id, lease.lease_id, flush=True)
time.sleep(600)
"""


def test_an_owner_killed_before_its_reference_was_recorded_is_found_by_its_lease():
    """The owner dies with SIGKILL between `commit` returning and the reference being
    recorded, while a second leg of the same owner is committing. `reap` kills the first
    leg's sandbox, found by its lease id, and leaves the second. Mutations: decide by
    `sandbox_ref` presence; decide liveness by pid or by age."""
    src = str(Path(placement_lease.__file__).resolve().parents[1])
    child = subprocess.Popen(
        [sys.executable, "-c", _DYING_OWNER, ROOT], stdout=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": src},
    )
    try:
        owner, dead_lease = child.stdout.readline().split()
        dead_path = placement_lease._lease_dir() / f"{dead_lease}.json"
        assert _locked(dead_path) and _entry(dead_path)["sandbox_ref"] is None
        assert owner == placement_lease.owner_id()

        living = placement_lease.open_lease("stage", _root())   # the second leg, committing
        remote = Remote()
        remote.hold(owner, dead_lease, "sbx-dead-owner")
        remote.hold(owner, living.lease_id, "sbx-live-leg")

        # While the first owner is alive nothing is touched.
        assert placement_lease.reap(Lookup(remote), _bound()) == {"cleared": (), "kept": ()}
        assert remote.calls == []

        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
        assert not _locked(dead_path)                           # the kernel released it
        lookup = Lookup(remote)
        done = placement_lease.reap(lookup, _bound())
    finally:
        child.kill()
        child.stdout.close()
    assert done == {"cleared": (dead_lease,), "kept": ()}
    assert remote.killed() == [dead_lease] and lookup.asked == ["resto"]
    assert set(remote.sandboxes) == {living.lease_id} and living.lease_id not in remote.fenced
    assert _files() == [f"{living.lease_id}.json"] and living.held
    # The pid of the dead owner being reused, or the entry being old, changes nothing: only
    # the lock was asked.
    assert "pid" not in _entry(living.path)
    living.clear()


@pytest.mark.parametrize("attempt", ["kill-fails", "kill-acknowledged-still-listed", "list-fails"])
def test_a_kept_entry_is_asked_again_and_cleared_only_when_confirmed(attempt):
    """After an unconfirmed release the entry is kept. At the next `reap` the backend is
    asked again by lease id; the entry is cleared only when the kill is acknowledged AND
    nothing is listed. Mutation: clear a kept entry after one attempt."""
    owner = placement_lease.owner_id()
    lease = placement_lease.open_lease("stage", _root())
    lease.record_sandbox_ref("sbx-left")
    lease.abandon()
    remote = Remote()
    remote.hold(owner, lease.lease_id, "sbx-left")
    real_list = remote.list_owned
    if attempt == "kill-fails":
        remote.kill_fails.add(lease.lease_id)
    elif attempt == "kill-acknowledged-still-listed":
        remote.kill_is_noop.add(lease.lease_id)
    else:
        def lost_after_the_kill(owner_id, bound):
            if remote.killed():
                raise ConnectionResetError("the listing was lost")
            return real_list(owner_id, bound)

        remote.list_owned = lost_after_the_kill
    for attempts in (1, 2):
        assert placement_lease.reap(Lookup(remote), _bound()) == {
            "cleared": (), "kept": (lease.lease_id,)}
        assert _files() == [f"{lease.lease_id}.json"]
        assert remote.killed() == [lease.lease_id] * attempts      # asked again, by lease id
    entry = _entry(lease.path)
    assert entry["abandoned"] is True and entry["sandbox_ref"] == "sbx-left"
    assert (entry["confirmed_killed_at"] is not None) is (attempt != "kill-fails")

    remote.kill_fails.clear()
    remote.kill_is_noop.clear()
    remote.list_owned = real_list
    assert placement_lease.reap(Lookup(remote), _bound()) == {
        "cleared": (lease.lease_id,), "kept": ()}
    assert _files() == [] and lease.lease_id not in remote.sandboxes


def test_an_abandoned_entry_is_never_cleared_on_an_empty_listing_alone():
    """The far side lists nothing for the lease (the admission may still be on its way)
    and does not acknowledge the kill: the entry stays. The kill is sent even though
    nothing is listed, because it is also the fence."""
    lease = placement_lease.open_lease("stage", _root())
    lease.abandon()
    remote = Remote()
    remote.kill_fails.add(lease.lease_id)
    assert placement_lease.reap(Lookup(remote), _bound())["kept"] == (lease.lease_id,)
    assert remote.killed() == [lease.lease_id] and _files() == [f"{lease.lease_id}.json"]
    remote.kill_fails.clear()
    assert placement_lease.reap(Lookup(remote), _bound())["cleared"] == (lease.lease_id,)
    assert lease.lease_id in remote.fenced


def test_another_owners_sandbox_survives_and_a_sandbox_on_the_second_page_is_reaped():
    """Mutations: drop the owner filter; read the first page only. A listed sandbox of this
    owner with no journal entry is never killed: the reaper kills only its own free
    entries, by lease id (agent-harness#1492 board round 1)."""
    owner = placement_lease.owner_id()
    first = placement_lease.open_lease("stage", _root())
    last = placement_lease.open_lease("stage", _root())
    for lease in (first, last):
        lease.abandon()
    remote = Remote()
    remote.page_size = 1
    remote.hold(owner, first.lease_id, "sbx-page-one")
    remote.hold("f" * 32, "e" * 32, "sbx-of-another-owner")
    remote.hold(owner, "a" * 32, "sbx-paused-no-entry")       # this owner's, journal lost
    remote.hold(owner, last.lease_id, "sbx-page-two")
    done = placement_lease.reap(Lookup(remote), _bound())
    assert sorted(done["cleared"]) == sorted([first.lease_id, last.lease_id])
    assert set(remote.sandboxes) == {"e" * 32, "a" * 32}
    assert "e" * 32 not in remote.killed() and "a" * 32 not in remote.killed()
    assert {call[1] for call in remote.calls if call[0] == "list_owned"} == {owner}


def test_a_listed_lease_that_is_live_is_never_killed_even_without_being_reaped_for():
    owner = placement_lease.owner_id()
    dead = placement_lease.open_lease("stage", _root())
    dead.abandon()
    live = placement_lease.open_lease("stage", _root())
    remote = Remote()
    remote.hold(owner, dead.lease_id, "sbx-dead")
    remote.hold(owner, live.lease_id, "sbx-live")
    placement_lease.reap(Lookup(remote), _bound())
    assert remote.killed() == [dead.lease_id] and live.lease_id in remote.sandboxes
    live.clear()


def test_an_entry_whose_backend_is_not_configured_or_unreadable_is_kept():
    lease = placement_lease.open_lease("stage", _root())
    lease.abandon()
    assert placement_lease.reap(Lookup(None), _bound()) == {"cleared": (), "kept": (lease.lease_id,)}
    assert _files() == [f"{lease.lease_id}.json"]

    def broken(scheme):
        raise sp.PlacementUnavailable("sandbox_placement_plugin_unavailable")

    assert placement_lease.reap(broken, _bound())["kept"] == (lease.lease_id,)
    lease.path.write_text("not json\n", encoding="utf-8")
    lookup = Lookup(Remote())
    assert placement_lease.reap(lookup, _bound())["kept"] == (lease.lease_id,)
    assert lookup.asked == [] and _files() == [f"{lease.lease_id}.json"]


def test_an_entry_that_cannot_be_opened_is_kept_and_never_acted_on(monkeypatch, capsys):
    """An entry that exists but cannot be opened is reported kept, no backend call is made
    for it, and the command exits 1. Monkeypatched, so it holds when run as root.
    Mutation: skip an unopenable entry silently."""
    import errno

    owner = placement_lease.owner_id()
    blocked = placement_lease.open_lease("stage", _root())
    blocked.abandon()
    remote = Remote()
    remote.hold(owner, blocked.lease_id, "sbx-blocked")
    real_open = os.open

    def deny(path, *args, **kwargs):
        if str(path).endswith(f"{blocked.lease_id}.json"):
            raise PermissionError(errno.EACCES, "permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny)
    lookup = Lookup(remote)
    assert placement_lease.reap(lookup, _bound()) == {"cleared": (), "kept": (blocked.lease_id,)}
    assert lookup.asked == [] and remote.calls == [] and "sbx-blocked" in str(remote.sandboxes)

    sp.register_backend("resto", _Protocol(remote))
    try:
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", ROOT)
        assert cli.main(["placement", "reap"]) == 1
        assert "0 cleared, 1 kept" in capsys.readouterr().out and remote.calls == []
    finally:
        sp._REGISTRY.pop("resto", None)
        sp._BACKEND_CODES.pop("resto", None)


def test_a_pending_entry_is_removed_only_when_nobody_holds_it():
    """An entry that never got its name was never followed by `admit`."""
    directory = placement_lease._lease_dir()
    placement_lease.open_lease("stage", _root()).clear()
    stale, held = directory / f".{'1' * 32}.pending", directory / f".{'2' * 32}.pending"
    stale.write_text("{}\n", encoding="utf-8")
    held.write_text("{}\n", encoding="utf-8")
    fd = os.open(held, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        lookup = Lookup(Remote())
        assert placement_lease.reap(lookup, _bound()) == {"cleared": (), "kept": ()}
        assert _files() == [held.name] and lookup.asked == []
    finally:
        os.close(fd)


def test_reap_is_bounded_when_the_backend_never_returns():
    lease = placement_lease.open_lease("stage", _root())
    lease.abandon()
    release = threading.Event()
    remote = Remote()

    def never(*_args):
        release.wait(30)
        return []

    remote.list_owned = never
    remote.kill = never
    started = time.monotonic()
    try:
        done = placement_lease.reap(Lookup(remote), _bound(0.3))
    finally:
        release.set()
    assert time.monotonic() - started < 5.0
    assert done == {"cleared": (), "kept": (lease.lease_id,)}


def test_the_command_reaps_only_for_configured_backends(tmp_path, monkeypatch, capsys):
    """`phase-loop placement reap` contacts the backend of a configured root, leaves an
    entry whose root is not configured, and refuses a malformed configuration."""
    owner = placement_lease.owner_id()
    remote = Remote()
    sp.register_backend("resto", _Protocol(remote))
    try:
        lease = placement_lease.open_lease("stage", _root())
        lease.abandon()
        remote.hold(owner, lease.lease_id, "sbx-left")

        assert cli.main(["placement", "reap"]) == 1            # no root configured: kept
        assert "0 cleared, 1 kept" in capsys.readouterr().out and remote.calls == []

        config = tmp_path / "config" / "agent-harness"
        config.mkdir(parents=True)
        (config / "advisor-boards.toml").write_text('[sandbox]\nroots = "not a table"\n')
        assert cli.main(["placement", "reap"]) == 2
        assert "sandbox_config_invalid" in capsys.readouterr().err and remote.calls == []

        monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", ROOT)
        assert cli.main(["placement", "reap"]) == 0
        assert "1 cleared, 0 kept" in capsys.readouterr().out
        assert remote.killed() == [lease.lease_id] and _files() == []
    finally:
        sp._REGISTRY.pop("resto", None)
        sp._BACKEND_CODES.pop("resto", None)


class _Protocol:
    """Just enough of the protocol to register `Remote` as a backend."""

    name = "resto"

    def __init__(self, remote: Remote) -> None:
        self.list_owned, self.kill = remote.list_owned, remote.kill

    def capabilities(self):
        return frozenset()

    def declaration(self):
        return sp.Declaration()

    def available(self, request):
        return True

    def endpoint(self, root):
        return None

    def admit(self, request, bound):
        raise AssertionError("reap never admits")

    def commit(self, prepared, request, bound=None):
        raise AssertionError("reap never commits")

    def release(self, prepared, bound=None):
        return None

    def execute(self, sandbox_ref, spec, bound):
        raise AssertionError("reap never executes")

    def wait(self, sandbox_ref, wait_s):
        raise AssertionError("reap never waits")

    def cancel(self, sandbox_ref, bound):
        return None

    def renew(self, sandbox_ref, until_s, bound):
        return None
