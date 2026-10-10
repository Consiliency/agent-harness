"""agent-harness#1407 and agent-harness#1420 (section 2): a Gemini seat is not refused merely
because of when it was launched, and the renewal acts on the store the seat reads.

What agy does, measured on agy 1.2.11, 1.3.1 and 1.3.3 (the PR records the runs):

- at start it renews a login that has under 300 s left, and no command forces it earlier. The
  seat needs 600 s, so for five minutes of each hour the renewal (``agy models``) exits 0 and
  changes nothing: the seat was refused ``gemini_credential_near_expiry``;
- it keeps the login in the OS keyring when it can reach one over the D-Bus session bus and in
  its file otherwise. The runtime reads the file. With a reachable keyring the renewal
  refreshed the keyring's copy and left the file expired: the seat was refused whatever the
  clock said.

``_fake_agy`` is a real executable with exactly those two behaviours, run through the real
``_refresh_gemini_credential`` and the real ``launch_provider``; nothing here stubs the
renewal's launch or its environment. Time is not slept through: the fake renews on a stated
call (the clock entering agy's margin), and the wait's poll is a few milliseconds.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_integrity, launcher, sandbox_egress, seat_jail
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_credentials as sc

pytestmark = pytest.mark.skipif(os.name != "posix" or not Path("/proc/self/fd").is_dir(),
                                reason="the renewal executes its image through /proc/self/fd")

TOKEN = ".gemini/antigravity-cli/antigravity-oauth-token"
NO_BUS = "unix:path=/dev/null"

# agy's two measured behaviours. ``$HOME/agy.plan`` (JSON) says on which call the login enters
# agy's renewal margin (``renew_on_call``; 0 = never), whether a reachable session bus makes
# agy use a keyring instead of the file (``keyring``), and which calls fail (``exit`` for
# every call, ``exit_on_calls`` for some). Every call is appended to
# ``$HOME/agy.calls`` with its argv, cwd listing and the environment NAMES it was given.
_FAKE_AGY = r'''#!/usr/bin/python3
import datetime, json, os, sys
home = os.environ["HOME"]
plan = json.load(open(os.path.join(home, "agy.plan")))
calls = os.path.join(home, "agy.calls")
count = sum(1 for _ in open(calls)) + 1 if os.path.exists(calls) else 1
bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
with open(calls, "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": sorted(os.listdir(".")), "bus": bus,
                          "env": sorted(os.environ)}) + "\n")
if plan.get("exit") or count in plan.get("exit_on_calls", ()):
    sys.exit(plan.get("exit") or 1)
token = os.path.join(home, ".gemini/antigravity-cli/antigravity-oauth-token")
state = json.load(open(token))
expiry = datetime.datetime.fromisoformat(state["token"]["expiry"][:26] + "+00:00")
left = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
in_margin = left < 300 or (plan["renew_on_call"] and count >= plan["renew_on_call"])
keyring = plan.get("keyring") and bus != "unix:path=/dev/null"
if in_margin and not keyring and "refresh_token" in state["token"]:
    fresh = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    state["token"].update(access_token="synthetic-renewed-access",
                          expiry=fresh.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z")
    with open(token, "w") as out:      # agy rewrites its file in place (measured)
        json.dump(state, out)
print("gemini-3.8-flash-high\tGemini 3.8 Flash (High)")
'''


def _login(home: Path, left_s: float, *, refresh_token: bool = True) -> Path:
    """agy's real file shape: RFC 3339 expiry with nanoseconds and ``Z``, mode 0600."""
    expiry = datetime.now(timezone.utc) + timedelta(seconds=left_s)
    token = {"access_token": "synthetic-access", "token_type": "Bearer",
             "expiry": expiry.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z"}
    if refresh_token:
        token["refresh_token"] = "synthetic-refresh"
    path = home / TOKEN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token, "auth_method": "consumer",
                                "id_token": "synthetic-id"}))
    path.chmod(0o600)
    return path


class _Image:
    """Stands in for the verified agy image: ``reopen`` yields a descriptor of the fake."""

    sha256 = "0" * 64

    def __init__(self, path: Path):
        self.path = path

    def reopen(self) -> int:
        return os.open(self.path, os.O_RDONLY)

    def close(self) -> None:
        pass


@pytest.fixture
def host(tmp_path, monkeypatch):
    """An operator home with a fake agy on the provider search path; no wait is slept through."""
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    agy = bindir / "agy"
    agy.write_text(_FAKE_AGY)
    agy.chmod(0o755)
    image = _Image(agy)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bindir))
    monkeypatch.setattr(agy_integrity, "admit_for_seat", lambda executable, env: image)
    monkeypatch.setenv(sc.POLL_ENV, "0.01")
    monkeypatch.delenv(sc.WAIT_ENV, raising=False)

    def plan(renew_on_call=0, **more):
        (home / "agy.plan").write_text(json.dumps({"renew_on_call": renew_on_call, **more}))

    def calls():
        path = home / "agy.calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    plan()
    return SimpleNamespace(home=home, agy=agy, image=image, plan=plan, calls=calls,
                           env={"HOME": str(home), "PATH": str(bindir)},
                           command=["agy", "--model", "gemini-3.8-flash-medium", "--print="])


def _left(host) -> float:
    return pi._gemini_login_left_s(host.home)


class _LaunchReached(Exception):
    pass


@contextmanager
def _no_profile(command, **kwargs):
    yield list(command), pi.SeatProfile(env={})


def _needs_seat_owner():
    if not hasattr(os, "memfd_create"):
        pytest.skip("the seat-launch owner needs sealed memfds (seat_owner_unavailable here)")


def _run_leg(host, monkeypatch, tmp_path, **kwargs):
    """The real seat launch path down to the launch itself (``launch_owned`` is the stop)."""
    _needs_seat_owner()
    def launch_owned(command, **launch):
        raise _LaunchReached(command)

    monkeypatch.setattr(pi, "launch_owned", launch_owned)
    egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
    cwd = tmp_path / "out"
    cwd.mkdir(exist_ok=True)
    try:
        return pi._run_leg_with_liveness(host.command, cwd=cwd, env=host.env,
                                         **{"deadline_s": 1800, **kwargs})
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(egress)


# ------------------------------------------------- agent-harness#1420: the store the seat reads

def test_the_renewal_acts_on_the_login_file_where_a_keyring_is_reachable(host):
    """The real renewal, the real launch, a fake agy that prefers a reachable keyring (as agy
    did on a desktop host: the keyring's copy was renewed and the file stayed 14 h expired).

    Mutation: do not set ``DBUS_SESSION_BUS_ADDRESS`` in the renewal's environment."""
    _login(host.home, -3600)
    host.plan(keyring=True)
    assert pi._refresh_gemini_credential(host.home, host.image) is True
    assert _left(host) > 3500
    call, = host.calls()
    assert call["argv"] == ["models"] and call["cwd"] == [] and call["bus"] == NO_BUS
    # Nothing of the operator's session reaches the renewal: no SSH_*, no XDG_*, no bus but ours.
    assert set(call["env"]) <= {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "NO_COLOR", "PATH", "TERM",
                                "TMPDIR", "PHASE_LOOP_SCRATCH_DECIDED", "DBUS_SESSION_BUS_ADDRESS"}


def test_the_seat_gets_a_copy_of_the_login_the_renewal_wrote(host, monkeypatch, tmp_path):
    """The join: what the gate renews is the file the seat's access-only copy is taken from."""
    _needs_seat_owner()
    _login(host.home, -3600)
    host.plan(keyring=True)
    cwd = tmp_path / "out"
    cwd.mkdir()
    with pi.seat_profile(harness="gemini", executable=str(host.agy), env=host.env, cwd=cwd) as (
            _provider, profile):
        args = profile.mount_args
        target = "/home/phase-loop-seat/" + TOKEN
        descriptor = int(next(args[i + 1] for i, a in enumerate(args)
                              if a == "--file" and args[i + 2] == target))
        copy = json.loads(os.pread(descriptor, 1 << 16, 0))
    assert copy["token"]["access_token"] == "synthetic-renewed-access"
    assert "refresh_token" not in copy["token"] and "id_token" not in copy


# ------------------------------------------------ agent-harness#1407: the window agy cannot act in

def test_a_seat_in_the_window_agy_cannot_renew_waits_and_then_launches(host, monkeypatch,
                                                                       tmp_path, caplog):
    """450 s left: under the seat's 600 s, above agy's 300 s. Main refused the seat here.

    Mutation: remove the ``_await_gemini_login`` call from ``_run_leg_with_liveness``."""
    _login(host.home, 450)
    host.plan(renew_on_call=3)       # the clock enters agy's margin at the third renewal run
    with caplog.at_level(logging.INFO, logger=pi.__name__), pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 3 and _left(host) > 3500
    waiting, = [r.getMessage() for r in caplog.records if "gemini_credential_awaiting_refresh" in r.getMessage()]
    # What is happening, when it clears, and that there is nothing to run.
    assert "has 4" in waiting and "s left" in waiting and "under the 600 s a seat needs" in waiting
    assert "clears by itself by" in waiting and "UTC" in waiting and "nothing to run" in waiting
    assert any("was renewed after" in r.getMessage() for r in caplog.records)


def test_a_login_that_is_fresh_launches_without_a_renewal_or_a_wait(host, monkeypatch, tmp_path):
    _login(host.home, 3000)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert host.calls() == []


def test_a_login_inside_agys_margin_is_renewed_at_once(host, monkeypatch, tmp_path):
    """Under 300 s agy renews on its first run: no wait. (Also the expired case.)"""
    for left in (200, -60):
        _login(host.home, left)
        (host.home / "agy.calls").unlink(missing_ok=True)
        with pytest.raises(_LaunchReached):
            _run_leg(host, monkeypatch, tmp_path)
        assert len(host.calls()) == 1 and _left(host) > 3500


def test_a_login_that_would_slip_under_the_gate_is_renewed_before_it(host, monkeypatch, tmp_path):
    """615 s clears the gate's 600 s now and not a moment later: the wait asks for the gate's
    floor plus its margin, so the seat is not refused between the wait and the gate.

    Mutation: make the wait ask for ``_GEMINI_LOGIN_MIN_S`` only."""
    _login(host.home, 615)
    host.plan(renew_on_call=2)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 2 and _left(host) > 3500


def test_a_login_agy_does_not_renew_ends_the_wait_and_is_refused_typed(host, monkeypatch,
                                                                       tmp_path, caplog):
    """Never renewed: the wait is bounded and the gate refuses with the typed notice."""
    _login(host.home, 450)
    monkeypatch.setenv(sc.WAIT_ENV, "0.05")
    with caplog.at_level(logging.WARNING, logger=pi.__name__), \
            pytest.raises(sandbox_egress.SeatIdentityUnverified, match="gemini_credential_near_expiry"):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) >= 3      # the first try, at least one in the wait, the gate's own
    assert any("was not renewed within" in r.getMessage() and "the seat will not run" in r.getMessage()
               for r in caplog.records)


def test_no_wait_allowed_refuses_as_before(host, monkeypatch, tmp_path):
    _login(host.home, 450)
    monkeypatch.setenv(sc.WAIT_ENV, "0")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="gemini_credential_near_expiry"):
        _run_leg(host, monkeypatch, tmp_path)


def test_an_expired_login_agy_does_not_renew_is_refused_without_waiting(host, monkeypatch, tmp_path):
    """Past expiry agy renews on any start; when it ran and did not, waiting cannot help.
    (10 s past expiry is still inside the wait's grace, so only this check stops a wait.)

    Mutation: drop the ``left <= 0`` return from ``_await_gemini_login``."""
    _login(host.home, -10, refresh_token=False)        # nothing to renew it with
    waits = []
    monkeypatch.setattr(pi, "_gemini_login_wait", lambda *a, **k: waits.append(k) or (False, 0.0))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="gemini_credential_near_expiry"):
        _run_leg(host, monkeypatch, tmp_path)
    assert waits == []


def test_a_renewal_run_that_fails_refuses_without_waiting(host, monkeypatch, tmp_path):
    """agy exiting non-zero (signed out, no network) is not the window: no wait."""
    _login(host.home, 450)
    host.plan(exit=1)
    waits = []
    monkeypatch.setattr(pi, "_gemini_login_wait", lambda *a, **k: waits.append(k) or (False, 0.0))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="gemini_credential_near_expiry"):
        _run_leg(host, monkeypatch, tmp_path)
    assert waits == []


def test_a_failed_run_in_the_middle_of_the_wait_is_not_yet(host, monkeypatch, tmp_path):
    """The first run decides whether there is a window to wait out. A run that fails LATER
    (a network blip in a five-minute wait) does not end the wait; the next poll tries again.

    Mutation: let a failing run mid-wait propagate."""
    _login(host.home, 450)
    host.plan(renew_on_call=3, exit_on_calls=[2])
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 3 and _left(host) > 3500


def test_the_wait_is_bounded_by_the_logins_own_life(host, monkeypatch):
    """At most the login's remaining life plus the grace: by then agy renews on any start.

    Mutation: drop the ``left + _GEMINI_LOGIN_WAIT_GRACE_S`` bound."""
    _login(host.home, 450)
    seen = {}

    def wait(attempt, *, max_wait_s, poll_s, wait):
        seen.update(max_wait_s=max_wait_s, poll_s=poll_s)
        return False, 0.0

    monkeypatch.setattr(pi, "_gemini_login_wait", wait)
    monkeypatch.setenv(sc.POLL_ENV, "30")
    pi._await_gemini_login(host.command, host.env)
    assert 440 + pi._GEMINI_LOGIN_WAIT_GRACE_S < seen["max_wait_s"] <= 450 + pi._GEMINI_LOGIN_WAIT_GRACE_S
    assert seen["poll_s"] == 30.0


def test_the_poll_loop_makes_its_last_attempt_at_the_bound():
    """Pure loop, injected clock: attempts every poll, one at the bound, then it gives up."""
    clock = [0.0]
    slept, attempts = [], []

    def wait(seconds):
        slept.append(seconds)
        clock[0] += seconds
        return False

    def attempt():
        attempts.append(clock[0])
        return False

    assert pi._gemini_login_wait(attempt, max_wait_s=100.0, poll_s=30.0, wait=wait,
                                 monotonic=lambda: clock[0]) == (False, 100.0)
    assert slept == [30.0, 30.0, 30.0, 10.0] and attempts == [30.0, 60.0, 90.0, 100.0]
    attempts.clear()
    assert pi._gemini_login_wait(lambda: attempts.append(1) or len(attempts) == 2, max_wait_s=100.0,
                                 poll_s=30.0, wait=wait, monotonic=lambda: clock[0])[0] is True
    assert len(attempts) == 2


# ------------------------------------------------------------- cancellation and the latch

def test_a_cancelled_poll_loop_raises_and_runs_no_further_renewal():
    attempts = []
    with pytest.raises(pi._ReviewOperationCancelled, match="review_operation_cancelled"):
        pi._gemini_login_wait(lambda: attempts.append(1), max_wait_s=600.0, poll_s=30.0,
                              wait=lambda seconds: True, monotonic=lambda: 0.0)
    assert attempts == []


@pytest.mark.parametrize("how", ["monitor", "board_context", "latch_cancel", "latch_trip"])
def test_board_cancellation_wakes_the_wait(host, monkeypatch, tmp_path, how):
    """The cancel arrives from another thread, mid-wait, while the poll would sleep a minute.
    What is asserted is that the wait ENDED AS CANCELLED after its first renewal and before a
    second -- not how long it took.

    Mutation: wait on a private event instead of the monitor's / the board context's; drop
    the latch re-check."""
    _login(host.home, 450)
    monkeypatch.setenv(sc.POLL_ENV, "60")
    cancel = threading.Event()
    latch = pi._ProviderQuiescenceLatch()
    monitor = (pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, cancel)
               if how == "monitor" else None)
    entered = threading.Event()
    real_wait = pi._gemini_login_wait.real      # past the conftest guard: this wait IS cancelled

    def announced_wait(attempt, *, wait, **kwargs):
        def waiting(seconds):
            entered.set()
            return wait(seconds)
        return real_wait(attempt, wait=waiting, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_wait", announced_wait)

    def fire():
        assert entered.wait(30)
        if how == "latch_cancel":
            latch.cancel()
        elif how == "latch_trip":
            latch.trip(pi.ProviderProcessGroupQuiescenceError("fake provider group"))
        else:
            cancel.set()

    token = pi._BOARD_CANCEL.set(cancel) if how == "board_context" else None
    thread = threading.Thread(target=fire, daemon=True)
    thread.start()
    try:
        with pytest.raises((pi._ReviewOperationCancelled, pi.ProviderProcessGroupQuiescenceError)):
            pi._await_gemini_login(host.command, host.env, review_monitor=monitor,
                                   quiescence_latch=latch if how.startswith("latch") else None)
    finally:
        if token is not None:
            pi._BOARD_CANCEL.reset(token)
        thread.join(30)
    assert len(host.calls()) == 1 and _left(host) < 600
    if monitor is not None:
        assert json.loads((tmp_path / "monitor.json").read_text())["login_wait"]["state"] == "cancelled"


def test_a_board_already_cancelled_renews_nothing(host, heartbeat, monkeypatch, tmp_path):
    """Mutation: drop the early cancel check from ``_await_gemini_login``."""
    _login(host.home, 450)
    cancel = threading.Event()
    cancel.set()
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, cancel)
    host.command = [heartbeat.executable, "--model", "m", "--print="]
    with pytest.raises(pi._ReviewOperationCancelled):
        _run_leg(host, monkeypatch, tmp_path, review_monitor=monitor, gemini_profile=heartbeat)
    assert host.calls() == []


def test_the_wait_runs_outside_the_quiescence_latchs_launch_lock(host, monkeypatch, tmp_path):
    """The latch launches a seat under one lock; a minutes-long wait inside it would block
    every cancel and trip. While the seat waits, the lock is free.

    Mutation: move the wait into ``seat_profile`` (which runs inside ``latch.launch``)."""
    _login(host.home, 450)
    host.plan(renew_on_call=2)
    latch = pi._ProviderQuiescenceLatch()
    held = []
    real_wait = pi._gemini_login_wait

    def wait(attempt, *, wait, **kwargs):
        def observed(seconds):
            free = latch._lock.acquire(blocking=False)
            held.append(not free)
            if free:
                latch._lock.release()
            return wait(seconds)
        return real_wait(attempt, wait=observed, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_wait", wait)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path, quiescence_latch=latch)
    assert held == [False]


# ------------------------------------------------------------------ monitoring and deadlines

def test_heartbeat_only_records_a_login_wait_and_restarts_the_stall_clock(host, tmp_path):
    _login(host.home, 450)
    host.plan(renew_on_call=3)
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, threading.Event())
    monitor.started = time.monotonic() - 10_000        # an old start: the wait must reset it
    states = []
    real_note = monitor.note
    monitor.note = lambda **fields: (states.append(fields["login_wait"]["state"]), real_note(**fields))[1]
    waited = pi._await_gemini_login(host.command, host.env, review_monitor=monitor)
    assert waited > 0 and states == ["awaiting_refresh", "refreshed"]
    record = json.loads((tmp_path / "monitor.json").read_text())
    assert record["login_wait"]["state"] == "refreshed" and record["login_wait"]["max_wait_s"] > 440
    assert time.monotonic() - monitor.started < 60


def test_a_bounded_legs_wait_is_bounded_by_and_charged_to_its_deadline(host, monkeypatch, tmp_path):
    """Under a bounded policy the wait cannot outlast the leg's deadline, and the leg keeps
    only what is left of it. Mutation: do not subtract the wait from ``deadline_s``."""
    _login(host.home, 450)
    seen = {}

    def wait(attempt, *, max_wait_s, poll_s, wait):
        seen["max_wait_s"] = max_wait_s
        return False, 0.0

    monkeypatch.setattr(pi, "_gemini_login_wait", wait)
    pi._await_gemini_login(host.command, host.env, deadline_s=20)
    assert seen["max_wait_s"] == 20.0
    # A wait as long as the deadline leaves no leg to run.
    monkeypatch.setattr(pi, "_await_gemini_login", lambda *a, **k: 20.0)
    with pytest.raises(subprocess.TimeoutExpired):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=20)
    # A shorter one leaves the rest: the leg's own backstop then reports the REMAINING time.
    monkeypatch.setattr(pi, "_await_gemini_login", lambda *a, **k: 19.75)
    monkeypatch.setattr(pi, "_seat_command_profile", _no_profile)
    monkeypatch.setattr(pi, "launch_owned", lambda command, **k: subprocess.Popen(
        ["/bin/sleep", "600"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True))
    egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
    try:
        with pytest.raises(subprocess.TimeoutExpired) as expired:
            pi._run_leg_with_liveness(host.command, cwd=tmp_path, env=host.env, deadline_s=20)
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(egress)
    assert expired.value.timeout == pytest.approx(0.25)


def test_a_heartbeat_legs_wait_ignores_the_backstop_deadline(host, monkeypatch, tmp_path):
    _login(host.home, 450)
    seen = {}
    monkeypatch.setattr(pi, "_gemini_login_wait",
                        lambda attempt, *, max_wait_s, poll_s, wait: seen.update(m=max_wait_s) or (False, 0.0))
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, threading.Event())
    pi._await_gemini_login(host.command, host.env, review_monitor=monitor, deadline_s=20)
    assert seen["m"] > 440


# ------------------------------------------------------------------ every caller of the gate

def _heartbeat_profile(host, tmp_path):
    """The heartbeat profile's facts the gate and the wait read: the credential link, the
    image descriptor and its digest (``gemini_heartbeat.owned_profile``'s real mount shape)."""
    from phase_loop_runtime import gemini_heartbeat as gh

    config = gh.PRIVATE_HOME + "/.gemini/antigravity-cli"
    mounts = ["--info-fd", "0", "--block-fd", "0"]
    for directory in (gh.PRIVATE_HOME, gh.PRIVATE_HOME + "/.gemini", config):
        mounts += ["--perms", "0700", "--dir", directory]
    mounts += ["--symlink", str(host.home / TOKEN), config + "/antigravity-oauth-token"]
    image_fd = os.open(host.agy, os.O_RDONLY)
    settings_fd = os.open(os.devnull, os.O_RDONLY)
    return SimpleNamespace(executable=gh.PRIVATE_HOME + "/agy", mount_args=mounts, image_fd=image_fd,
                           settings_fd=settings_fd, pass_fds=(image_fd, settings_fd),
                           env={"HOME": gh.PRIVATE_HOME, "PATH": "/usr/bin:/bin"},
                           evidence={"provider_image_sha256": "0" * 64}, process=None, identity=None)


@pytest.fixture
def heartbeat(host, tmp_path, monkeypatch):
    from phase_loop_runtime import gemini_heartbeat as gh

    profile = _heartbeat_profile(host, tmp_path)
    # The profile's image is a sealed memfd in production; here it is the fake's descriptor.
    monkeypatch.setattr(gh, "VerifiedImage", lambda fd, digest, path=None: SimpleNamespace(
        reopen=lambda: os.dup(fd), close=lambda: os.close(fd), sha256=digest, fd=fd))
    monkeypatch.setattr(agy_integrity, "admit_for_seat",
                        lambda *a, **k: pytest.fail("a heartbeat launch looked its image up again"))
    yield profile
    for fd in (profile.image_fd, profile.settings_fd):
        os.close(fd)


def _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, argv):
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, threading.Event())
    host.command = [heartbeat.executable, *argv]
    host.env = heartbeat.env
    return _run_leg(host, monkeypatch, tmp_path, review_monitor=monitor, gemini_profile=heartbeat)


def test_the_heartbeat_seat_and_the_president_rung_wait_on_the_operators_login(
        host, heartbeat, monkeypatch, tmp_path):
    """The heartbeat route (the board seat, the qualification's seat and the president's
    Gemini rung all launch this way): the login is the one the profile links, not ``HOME``'s,
    and the renewal runs the profile's own verified image."""
    _login(host.home, 450)
    host.plan(renew_on_call=2)
    with pytest.raises(_LaunchReached):
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--model", "m", "--print="])
    assert len(host.calls()) == 2 and _left(host) > 3500
    assert json.loads((tmp_path / "monitor.json").read_text())["login_wait"]["state"] == "refreshed"


def test_the_help_measurement_neither_waits_nor_needs_a_fresh_login(host, heartbeat, monkeypatch,
                                                                     tmp_path):
    """``agy --help`` makes no request. An availability probe and an admission lookup measure
    help; in the window they were refused (and the board lost its Google seat at composition).

    Mutation: make ``_gemini_launch_needs_login`` return True for ``--help``."""
    _login(host.home, 450)
    monkeypatch.setattr(pi, "_gemini_login_wait", lambda *a, **k: pytest.fail("help waited"))
    with pytest.raises(_LaunchReached) as reached:
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--help"])
    assert reached.value.args[0][1:] == ["--help"] and host.calls() == []
    # Only that exact launch: anything else on the same profile needs its login.
    assert pi._gemini_launch_needs_login([heartbeat.executable, "--help"], heartbeat) is False
    for argv in (["--help", "--print="], ["-p", "--help"], ["--version"], []):
        assert pi._gemini_launch_needs_login([heartbeat.executable, *argv], heartbeat) is True
    assert pi._gemini_launch_needs_login(["agy", "--help"], None) is True


def test_the_executor_review_route_waits_before_it_holds_anything(host, monkeypatch):
    """``launcher.launch(action="review")`` reaches the same gate; its wait comes first.

    Mutation: remove the ``_await_gemini_login`` call from ``launcher.launch``."""
    order = []
    monkeypatch.setattr(pi, "_await_gemini_login",
                        lambda command, env, **k: order.append(("wait", list(command), env["HOME"])) or 0.0)

    class _Stop(Exception):
        pass

    def isolated_network(**kwargs):
        order.append(("network",))
        raise _Stop

    monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
    with pytest.raises(_Stop):
        launcher.launch(host.command, action="review", env=host.env, cwd=str(host.home))
    assert order == [("wait", host.command, str(host.home)), ("network",)]


def test_other_providers_and_an_unreadable_login_are_left_to_the_launch(host, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(pi, "_gemini_login_left_s", lambda home: pytest.fail("not a Gemini launch"))
        for command in (["codex", "exec"], ["claude", "-p"], ["grok"], []):
            assert pi._await_gemini_login(command, host.env) == 0.0
    # No login file: the gate refuses it (seat_profile_unavailable), the wait does nothing.
    assert pi._await_gemini_login(["agy", "--print="], host.env) == 0.0
    # An expiry that does not parse: the same.
    (host.home / TOKEN).parent.mkdir(parents=True)
    (host.home / TOKEN).write_text(json.dumps({"token": {"expiry": "not a time"}}))
    assert pi._gemini_login_left_s(host.home) is None
    assert pi._await_gemini_login(["agy", "--print="], host.env) == 0.0


# ------------------------------------------------------------------------------ the notices

def test_the_notices_say_what_happens_when_it_clears_and_the_command():
    what, why, fix = seat_jail.NOTICES["gemini_credential_near_expiry"]
    assert what == "leg refused" and "under 10 minutes" in why and "last 5 minutes" in why
    assert "re-run in 5 minutes" in fix
    assert "`DBUS_SESSION_BUS_ADDRESS=unix:path=/dev/null agy`" in fix
    what, why, fix = seat_jail.NOTICES["gemini_credential_awaiting_refresh"]
    assert what == "waiting" and "last 5 minutes" in why and "clears by itself within 5 minutes" in fix
    assert pi._GEMINI_LOGIN_AWAITING in seat_jail.NOTICE_CODES
    # The command in the notice is the address the renewal itself uses.
    assert pi._GEMINI_REFRESH_NO_SESSION_BUS == NO_BUS


def test_the_suite_never_sleeps_through_a_real_long_gemini_login_wait(host, monkeypatch):
    """The conftest guard: a test that reaches the real wait with a long poll fails."""
    _login(host.home, 450)
    monkeypatch.setenv(sc.POLL_ENV, "30")
    with pytest.raises(pytest.fail.Exception, match="real Gemini login wait"):
        pi._await_gemini_login(host.command, host.env)
