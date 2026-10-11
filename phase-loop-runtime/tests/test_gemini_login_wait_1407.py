"""agent-harness#1407 and agent-harness#1420 (section 2): a Gemini seat is not refused merely
because of when it was launched, and the renewal acts on the store the seat reads.

What agy does, measured on agy 1.2.11, 1.3.1 and 1.3.3 (the PR records the runs):

- it renews a login that has expired (and, on these builds, one with under 300 s left); no
  command forces it earlier. The seat needs 600 s, so for five minutes of each hour the
  launch gate's renewal (``agy models``) exits 0 and changes nothing: the seat was refused
  ``gemini_credential_near_expiry``;
- it keeps the login in the OS keyring when it can reach one over the D-Bus session bus and in
  its file otherwise. The runtime reads the file. With a reachable keyring the renewal
  refreshed the keyring's copy and left the file expired: the seat was refused whatever the
  clock said.

The mechanism under test: before a Gemini seat is launched on a login that is short but not
yet expired, the launch SLEEPS until the login has expired. The sleep starts no process and
takes no lock. Then main's unchanged gate runs its one renewal, which renews an expired login.

``_FAKE_AGY`` is a real executable, run through the real gate, the real
``_refresh_gemini_credential`` and the real ``launch_provider``. By default it renews ONLY a
login that has expired -- the one fact the mechanism relies on -- so a sleep that ends a
moment early is refused. Most tests replace the sleep by the clock reaching the login's
expiry (``sleeps``); the tests of the sleep itself run it for real on a login a second from
expiry.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_integrity, launcher, sandbox_egress, seat_jail
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as pi

pytestmark = pytest.mark.skipif(os.name != "posix" or not Path("/proc/self/fd").is_dir(),
                                reason="the renewal executes its image through /proc/self/fd")

TOKEN = ".gemini/antigravity-cli/antigravity-oauth-token"
NO_BUS = "unix:path=/dev/null"
NEAR_EXPIRY = "gemini_credential_near_expiry"
AGY_MEASURED_MARGIN_S = 300      # the stand-in's, where a test wants agy as measured

# ``$HOME/agy.plan`` (JSON): ``margin`` is how close to its expiry the stand-in renews a login
# (0, the default: only once it has expired), ``never`` makes it renew nothing, ``keyring``
# makes a reachable session bus take the login instead of the file, ``exit`` fails every call,
# ``delay`` makes a run take that many seconds.
# Every call is appended to ``$HOME/agy.calls`` with its argv, cwd listing, pid and the
# environment NAMES it was given.
_FAKE_AGY = r'''#!/usr/bin/python3
import datetime, json, os, sys, time
home = os.environ["HOME"]
plan = json.load(open(os.path.join(home, "agy.plan")))
bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
with open(os.path.join(home, "agy.calls"), "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": sorted(os.listdir(".")), "bus": bus,
                          "env": sorted(os.environ), "pid": os.getpid()}) + "\n")
if plan.get("exit"):
    sys.exit(plan["exit"])
time.sleep(plan.get("delay", 0))
token = os.path.join(home, ".gemini/antigravity-cli/antigravity-oauth-token")
state = json.load(open(token))
expiry = datetime.datetime.fromisoformat(state["token"]["expiry"][:26] + "+00:00")
left = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
keyring = plan.get("keyring") and bus != "unix:path=/dev/null"
if (left <= plan.get("margin", 0) and not plan.get("never") and not keyring
        and "refresh_token" in state["token"]):
    fresh = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    state["token"].update(access_token="synthetic-renewed-access",
                          expiry=fresh.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z")
    with open(token, "w") as out:      # agy rewrites its file in place (measured)
        json.dump(state, out)
print("gemini-3.8-flash-high\tGemini 3.8 Flash (High)")
'''


def _login(home: Path, left_s: float, *, refresh_token: bool = True) -> datetime:
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
    return expiry


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
    """An operator home with a fake agy on the provider search path."""
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

    def plan(**behaviour):
        (home / "agy.plan").write_text(json.dumps(behaviour))

    def calls():
        path = home / "agy.calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    plan()
    return SimpleNamespace(home=home, agy=agy, image=image, plan=plan, calls=calls,
                           env={"HOME": str(home), "PATH": str(bindir)},
                           command=["agy", "--model", "gemini-3.8-flash-medium", "--print="])


def _left(host) -> float:
    return pi._gemini_login_left_s(host.home)


@pytest.fixture
def sleeps(host, monkeypatch):
    """Replace the sleep by the clock reaching the login's expiry: the login file is
    rewritten as expired a second ago. Each sleep is recorded as ``(home, seconds)``."""
    slept = []

    def expire(home, left, **kwargs):
        slept.append((Path(home), left))
        state = json.loads((Path(home) / TOKEN).read_text())
        gone = datetime.now(timezone.utc) - timedelta(seconds=1)
        state["token"]["expiry"] = gone.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z"
        (Path(home) / TOKEN).write_text(json.dumps(state))
        return "expired"

    monkeypatch.setattr(pi, "_gemini_login_sleep", expire, raising=False)
    return slept


@pytest.fixture
def processes(monkeypatch):
    """A process spy: every ``subprocess.Popen`` the runtime makes, in order."""
    started = []
    real = subprocess.Popen

    class Spy(real):
        def __init__(self, args, *a, **k):
            started.append([os.fspath(arg) for arg in args] if not isinstance(args, str) else args)
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", Spy)
    return started


class _LaunchReached(Exception):
    pass


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


def _monitor(tmp_path, cancel=None):
    return pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, cancel or threading.Event())


def _login_wait(tmp_path):
    return json.loads((tmp_path / "monitor.json").read_text()).get("login_wait")


# ------------------------------------------------- agent-harness#1420: the store the seat reads

def test_the_renewal_acts_on_the_login_file_where_a_keyring_is_reachable(host):
    """The real renewal, the real launch, a fake agy that prefers a reachable keyring (as agy
    did on a desktop host: the keyring's copy was renewed and the file stayed 14 h expired).

    Mutation: do not set ``DBUS_SESSION_BUS_ADDRESS`` in the renewal's environment."""
    _login(host.home, -3600)
    host.plan(keyring=True)
    pi._refresh_gemini_credential(host.home, host.image)
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

@pytest.mark.parametrize("margin", [0, AGY_MEASURED_MARGIN_S])
def test_a_seat_in_the_window_sleeps_to_the_logins_expiry_and_the_gate_renews_it_once(
        host, sleeps, monkeypatch, tmp_path, caplog, margin):
    """450 s left: under the seat's 600 s, above agy's 300 s. Main refused the seat here.
    Now the launch sleeps to the login's expiry, main's gate runs its ONE renewal on an
    expired login, and the seat launches -- with an agy that renews only an expired login,
    and with agy as measured.

    Mutations: do not call ``_await_gemini_login``; shift the notice's time; say something
    other than the notice row."""
    expiry = _login(host.home, 450)
    host.plan(margin=margin)
    with caplog.at_level(logging.INFO, logger=pi.__name__), pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 1 and _left(host) > 3500
    (home, slept_for), = sleeps
    assert home == host.home and 445 < slept_for <= 450
    waiting, = [r.getMessage() for r in caplog.records if "gemini_credential_awaiting_refresh" in r.getMessage()]
    # The notice's own literals (what is happening, what to run), then when the wait ends.
    _what, why, fix = seat_jail.NOTICES["gemini_credential_awaiting_refresh"]
    assert why in waiting and waiting.endswith(fix)
    numbers = re.search(r"\((4[0-9]{2}) s left; until (\d\d):(\d\d):(\d\d) UTC\)", waiting)
    assert numbers and int(numbers.group(1)) == int(slept_for)
    # The time given is the login's own expiry, to the second.
    stated = expiry.replace(hour=int(numbers.group(2)), minute=int(numbers.group(3)),
                            second=int(numbers.group(4)), microsecond=0)
    assert abs((stated - expiry).total_seconds()) <= 2


def test_the_real_sleep_starts_no_process_takes_no_lock_and_ends_on_the_files_expiry(
        host, processes, monkeypatch, tmp_path):
    """The whole thing for real, on a login a second from expiry and an agy that renews ONLY
    an expired login -- so a sleep that ended a moment early would be refused here.

    While the launch sleeps, the process spy has seen nothing, and neither the renewal lock
    nor the quiescence latch's launch lock is held (sampled at every read of the login
    file). Then exactly one renewal, the gate's, and the launch.

    Mutations: run a renewal from inside the sleep; hold either lock across it; end the sleep
    before the file's expiry; report its end as something else."""
    _login(host.home, 1.2)
    latch = pi._ProviderQuiescenceLatch()
    during, ended = [], []
    sleeping = threading.Event()
    real_left, real_sleep = pi._gemini_login_left_s, pi._gemini_login_sleep

    def sleep(home, left, **kwargs):
        sleeping.set()
        try:
            ended.append(real_sleep(home, left, **kwargs))
            return ended[-1]
        finally:
            sleeping.clear()

    def left_s(home):
        if sleeping.is_set():       # one of the sleep's own reads of the login file
            free = latch._lock.acquire(blocking=False)
            if free:
                latch._lock.release()
            during.append((len(processes), pi._GEMINI_REFRESH_LOCK.locked(), free))
        return real_left(home)

    monkeypatch.setattr(pi, "_gemini_login_sleep", sleep)
    monkeypatch.setattr(pi, "_gemini_login_left_s", left_s)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path, quiescence_latch=latch)
    assert ended == ["expired"]
    assert len(during) >= 3 and set(during) == {(0, False, True)}
    assert [argv[1:] for argv in processes] == [["models"]] and len(host.calls()) == 1
    assert _left(host) > 3500 and latch.is_quiescent()


@pytest.mark.parametrize("one_latch", [True, False])
def test_three_seats_sleeping_on_one_login_all_launch_from_one_renewal(host, monkeypatch, tmp_path,
                                                                       one_latch):
    """Three launches sleep on the same login, for real, sharing ONE quiescence latch or
    none. Each holds nothing while it sleeps; then main's gate serialises them (under the
    latch's launch lock, and without one on the renewal's own lock and its re-check): the
    first renews, the others find the login fresh.

    Mutations: hold the latch across the sleep; drop the renewal's re-check under its lock."""
    _needs_seat_owner()
    _login(host.home, 1.2)
    host.plan(delay=1.0)      # the first renewal is still running when the others reach it
    latch = pi._ProviderQuiescenceLatch() if one_latch else None
    monkeypatch.setattr(pi, "launch_owned",
                        lambda command, **k: (_ for _ in ()).throw(_LaunchReached(command)))
    results = []

    def seat(name):
        egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
        cwd = tmp_path / name
        cwd.mkdir()
        try:
            pi._run_leg_with_liveness(host.command, cwd=cwd, env=host.env, deadline_s=1800,
                                      quiescence_latch=latch)
        except BaseException as error:  # noqa: BLE001 - the assertion is on what was raised
            results.append(type(error))
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(egress)

    threads = [threading.Thread(target=seat, args=(name,), daemon=True) for name in "abc"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not any(thread.is_alive() for thread in threads), "seats sharing a latch deadlocked"
    assert results == [_LaunchReached] * 3 and len(host.calls()) == 1
    assert _left(host) > 3500 and (latch is None or latch.is_quiescent())


@pytest.mark.parametrize("login,outcome,runs", [
    ("fresh", _LaunchReached, 0),                 # 600 s or more: launched at once
    ("at_the_floor", _LaunchReached, 0),
    ("expired", _LaunchReached, 1),               # the gate renews it, as on main
    ("expired_and_never_renewed", NEAR_EXPIRY, 1),
    ("unreadable", NEAR_EXPIRY, 1),               # main's refusal, from main's one run
    ("missing", "seat_profile_unavailable", 0),
])
def test_a_login_that_is_fresh_expired_unreadable_or_missing_is_not_slept_on(
        host, sleeps, monkeypatch, tmp_path, login, outcome, runs):
    """The sleep applies to one state only: a readable login with more than 0 and less than
    600 s left. Every other state goes straight to main's gate and is main's.

    Mutations: move the 600 s floor; sleep on an expired login; sleep on an unreadable one."""
    if login in ("fresh", "at_the_floor"):
        _login(host.home, 3000 if login == "fresh" else 605)
    elif login.startswith("expired"):
        _login(host.home, -5)
        host.plan(never=login == "expired_and_never_renewed")
    elif login == "unreadable":
        (host.home / TOKEN).parent.mkdir(parents=True)
        (host.home / TOKEN).write_text(json.dumps({"token": {"expiry": "not a time"}}))
    expected = outcome if isinstance(outcome, type) else sandbox_egress.SeatIdentityUnverified
    with pytest.raises(expected, match=None if isinstance(outcome, type) else outcome):
        _run_leg(host, monkeypatch, tmp_path)
    assert sleeps == [] and len(host.calls()) == runs
    assert pi._await_gemini_login(host.command, host.env) == 0.0 and sleeps == []


def test_a_login_under_600_s_is_slept_on_just_under_the_floor(host, sleeps, monkeypatch, tmp_path):
    """595 s: under the floor. It sleeps (main refused it, or launched it only if agy chose
    to renew). Mutation: move ``_GEMINI_LOGIN_MIN_S`` down."""
    _login(host.home, 595)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(sleeps) == 1 and len(host.calls()) == 1


def test_a_login_main_renewed_at_once_now_also_waits_to_its_expiry(host, sleeps, monkeypatch,
                                                                    tmp_path):
    """A behaviour change against main, stated in the PR: with agy as measured, main renews a
    login with under 300 s at once. The sleep knows no figure of agy's, so it cannot tell
    that login from one agy would leave alone: the seat waits to the expiry (here 200 s) and
    is then launched from the same single renewal.

    Mutation: skip the sleep under a figure of agy's."""
    _login(host.home, 200)
    host.plan(margin=AGY_MEASURED_MARGIN_S)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    (_home, slept_for), = sleeps
    assert 195 < slept_for <= 200 and len(host.calls()) == 1 and _left(host) > 3500


def test_after_the_sleep_the_gate_is_mains_a_login_agy_does_not_renew_is_refused(
        host, sleeps, monkeypatch, tmp_path):
    """One sleep, one renewal, main's refusal: no retry, no second sleep, no second run.

    Mutation: sleep or renew again."""
    _login(host.home, 450)
    host.plan(never=True)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(sleeps) == 1 and len(host.calls()) == 1


@pytest.mark.parametrize("check", ["bind", "owner", "provider"])
def test_a_request_main_refuses_for_another_reason_starts_nothing_before_its_refusal(
        host, sleeps, processes, monkeypatch, tmp_path, check):
    """A request main refuses before its credential gate (a linked bind source, no owner
    platform, no provider on the search path) is refused the same way, with no host renewal:
    the process spy sees nothing.
    Stated in the PR: it is refused AFTER the sleep, where main refused it at once.

    Mutation: run a renewal before the launch."""
    _login(host.home, 450)
    if check == "bind":
        source = tmp_path / "source"
        source.write_text("synthetic input")
        link = tmp_path / "input-link"
        link.symlink_to(source)
        host.command += ["--file", str(link)]
        code = "seat_bind_source_unavailable"
    elif check == "provider":
        empty = tmp_path / "no-provider"
        empty.mkdir()
        monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(empty))
        code = "seat_provider_unavailable"
    else:
        def no_owner():
            raise sandbox_egress.SeatIdentityUnverified("seat_owner_unavailable")

        monkeypatch.setattr(pi, "_require_owner_platform", no_owner)
        code = "seat_owner_unavailable"
    refusal = FileNotFoundError if check == "provider" else sandbox_egress.SeatIdentityUnverified
    with pytest.raises(refusal, match=code):
        _run_leg(host, monkeypatch, tmp_path)
    assert host.calls() == [] and processes == [] and len(sleeps) == 1


# ------------------------------------------------------------------ the sleep itself

_CANCELS = ["monitor", "board_context", "latch_cancel", "latch_trip"]


def _cancel_sources(how, tmp_path):
    cancel = threading.Event()
    latch = pi._ProviderQuiescenceLatch() if how.startswith("latch") else None
    monitor = _monitor(tmp_path, cancel) if how == "monitor" else None

    def fire():
        if how == "latch_cancel":
            latch.cancel()
        elif how == "latch_trip":
            latch.trip(pi.ProviderProcessGroupQuiescenceError("sibling group"))
        else:
            cancel.set()

    return cancel, latch, monitor, fire


def _await_in_thread(host, how, cancel, latch, monitor):
    outcome, done = [], threading.Event()

    def run():
        token = pi._BOARD_CANCEL.set(cancel) if how == "board_context" else None
        try:
            outcome.append(pi._await_gemini_login(host.command, host.env, review_monitor=monitor,
                                                  quiescence_latch=latch))
        except BaseException as error:  # noqa: BLE001 - the assertion is on what was raised
            outcome.append(error)
        finally:
            if token is not None:
                pi._BOARD_CANCEL.reset(token)
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome, done


def _real_sleep_announced(monkeypatch):
    """Use the real sleep (past the conftest guard) and say when it has been entered."""
    entered = threading.Event()
    real = pi._gemini_login_sleep.real

    def announced(home, left, **kwargs):
        entered.set()
        return real(home, left, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_sleep", announced)
    return entered


@pytest.mark.parametrize("already", [False, True])
@pytest.mark.parametrize("how", _CANCELS)
def test_a_cancel_or_a_latch_ends_the_sleep_and_nothing_was_started(
        host, processes, monkeypatch, tmp_path, how, already):
    """A 450 s sleep, cancelled from another thread (or cancelled before it starts). It ends
    as cancelled (a latch trip: with the latch's own error), long before it would have run
    out, and the process spy saw nothing: there is no helper to end and no lock to release.

    Mutations: sleep on a private event; do not re-check the latch; return instead of raising."""
    _login(host.home, 450)
    cancel, latch, monitor, fire = _cancel_sources(how, tmp_path)
    entered = _real_sleep_announced(monkeypatch)
    if already:
        fire()
    thread, outcome, done = _await_in_thread(host, how, cancel, latch, monitor)
    assert entered.wait(30)
    fired = time.monotonic()
    if not already:
        fire()
    assert done.wait(30)
    expected = (pi.ProviderProcessGroupQuiescenceError if how == "latch_trip"
                else pi._ReviewOperationCancelled)
    assert len(outcome) == 1 and isinstance(outcome[0], expected), outcome
    assert time.monotonic() - fired < 10        # it was woken; it did not run out (450 s)
    assert processes == [] and host.calls() == [] and not pi._GEMINI_REFRESH_LOCK.locked()
    assert latch is None or latch.is_quiescent()
    if monitor is not None:
        assert _login_wait(tmp_path)["state"] == "cancelled"


@pytest.mark.parametrize("change,state", [("renewed", "refreshed"), ("garbled", "unreadable"),
                                          ("removed", "unreadable")])
def test_the_sleep_ends_on_the_file_when_it_is_renewed_or_can_no_longer_be_read(
        host, processes, monkeypatch, tmp_path, change, state):
    """The sleep reads the login file each slice, as the gate reads it. Something else renewing
    the login, or the file becoming unreadable, ends it; the launch (main's gate) follows.

    Mutation: sleep on arithmetic, without reading the file again."""
    _login(host.home, 450)
    entered = _real_sleep_announced(monkeypatch)
    cancel = threading.Event()
    monitor = _monitor(tmp_path, cancel)
    thread, outcome, done = _await_in_thread(host, "monitor", cancel, None, monitor)
    assert entered.wait(30)
    if change == "renewed":
        _login(host.home, 3000)                  # e.g. the operator's own agy
    elif change == "garbled":
        (host.home / TOKEN).write_text("{")
    else:
        (host.home / TOKEN).unlink()
    ended = done.wait(30)
    cancel.set()                                 # only matters if it did not end by itself
    thread.join(30)
    assert ended and isinstance(outcome[0], float), outcome     # ended, well before the 450 s
    assert _login_wait(tmp_path)["state"] == state and processes == []


def test_the_sleep_never_lasts_longer_than_the_life_read_when_it_began(host, monkeypatch):
    """A login 1 s from expiry is replaced, mid-sleep, by another short one (449 s). The sleep
    ends at its bound, not 449 s later. Mutation: drop the bound."""
    _login(host.home, 1.0)
    real = pi._gemini_login_sleep.real
    result = []
    thread = threading.Thread(target=lambda: result.append(real(host.home, 1.0)), daemon=True)
    thread.start()
    time.sleep(0.3)
    _login(host.home, 449)
    thread.join(30)
    assert result == ["bound"]


# ------------------------------------------------------------------ monitoring and deadlines

def test_heartbeat_only_records_the_sleep_and_restarts_the_stall_clock(host, sleeps, tmp_path):
    """Recorded as ``login_wait``; a monitored leg's backstop deadline does not decide it.

    Mutations: do not restart the stall clock; apply the bounded rule under heartbeat."""
    _login(host.home, 450)
    monitor = _monitor(tmp_path)
    monitor.started = time.monotonic() - 10_000        # an old start: the sleep must reset it
    states = []
    real_note = monitor.note
    monitor.note = lambda **fields: (states.append(fields["login_wait"]["state"]), real_note(**fields))[1]
    pi._await_gemini_login(host.command, host.env, review_monitor=monitor, deadline_s=5)
    assert states == ["awaiting_refresh", "expired"] and len(sleeps) == 1
    assert 445 < _login_wait(tmp_path)["max_wait_s"] <= 450
    assert time.monotonic() - monitor.started < 60


@pytest.mark.parametrize("left,margin,deadline_s,waits,outcome", [
    (450, 0, 1800, True, _LaunchReached),                 # the default deadline: it waits
    (450, 0, 1051, True, _LaunchReached),                 # 1051 - 450 >= 600: it waits
    (450, 0, 1049, False, NEAR_EXPIRY),                   # it does not: main's refusal, at once
    (450, 0, 600, False, NEAR_EXPIRY),
    (450, 0, 455.5, False, NEAR_EXPIRY),                  # the sleep would merely fit: it does not
    (200, AGY_MEASURED_MARGIN_S, 799, False, _LaunchReached),   # it does not: main's launch, at once
    (450, 0, 5, False, NEAR_EXPIRY),                      # an explicit short deadline: exactly main
])
def test_a_bounded_leg_waits_only_when_600_s_of_its_deadline_are_left_after_the_sleep(
        host, sleeps, monkeypatch, tmp_path, left, margin, deadline_s, waits, outcome):
    """A bounded leg sleeps only if at least 600 s of its deadline remain afterwards. Otherwise
    it does not sleep and main's gate decides at once, launching or refusing exactly as on
    main. The wait never turns either into a timeout.

    Mutations: drop the rule; compare with the bare deadline; apply it the wrong way round."""
    _login(host.home, left)
    host.plan(margin=margin)
    expected = outcome if isinstance(outcome, type) else sandbox_egress.SeatIdentityUnverified
    with pytest.raises(expected, match=None if isinstance(outcome, type) else outcome):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=deadline_s)
    assert len(sleeps) == (1 if waits else 0) and len(host.calls()) == 1


@pytest.mark.parametrize("slept_s,state,remaining", [(450, "expired", 750),
                                                     (100, "refreshed", 1100)])
def test_a_bounded_leg_is_charged_the_time_it_actually_slept(host, monkeypatch, tmp_path,
                                                             slept_s, state, remaining):
    """450 s to the login's expiry, a 1200 s deadline. The leg sleeps (injected clock) and
    its own backstop then reports what is LEFT: 750 s after the whole sleep, 1100 s when
    something else renewed the login 100 s in.

    Mutations: do not subtract; charge the life read at the start, not the time slept."""
    _login(host.home, 450)
    actual, offset = time.monotonic, [0.0]
    monkeypatch.setattr(pi.time, "monotonic", lambda: actual() + offset[0])

    def sleep(home, left, **kwargs):
        offset[0] += slept_s
        return state

    @contextmanager
    def no_profile(command, **kwargs):
        yield list(command), pi.SeatProfile(env={})

    def seat(command, **kwargs):
        process = subprocess.Popen(["/bin/sleep", "600"], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        poll = process.poll

        def outlives_any_deadline(*a, **k):     # so the leg's backstop fires on its next look
            process.poll = poll
            offset[0] += 10_000.0
            return poll(*a, **k)

        process.poll = outlives_any_deadline
        return process

    monkeypatch.setattr(pi, "_gemini_login_sleep", sleep)
    monkeypatch.setattr(pi, "_seat_command_profile", no_profile)
    monkeypatch.setattr(pi, "launch_owned", seat)
    egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
    try:
        with pytest.raises(subprocess.TimeoutExpired) as expired:
            pi._run_leg_with_liveness(host.command, cwd=tmp_path, env=host.env, deadline_s=1200,
                                      stall_threshold_s=1e9)   # the deadline, not the stall
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(egress)
    assert remaining - 5 < expired.value.timeout < remaining + 5


# ------------------------------------------------------------------ every caller

@pytest.fixture
def heartbeat(host, tmp_path, monkeypatch):
    """The REAL heartbeat profile (``gemini_heartbeat.owned_profile``: its mount arguments,
    its credential link, its sealed image and that image's digest) over the fake agy."""
    _needs_seat_owner()
    monkeypatch.setattr(agy_integrity, "admit_for_seat",
                        lambda *a, **k: pytest.fail("a heartbeat launch looked its image up again"))
    _login(host.home, 3000)      # the profile links a login that exists; each test rewrites it
    data = host.agy.read_bytes()
    admission = gh.Admission(gh.VerifiedImage.from_bytes(data, str(host.agy)), None,
                             "qualification_candidate")
    try:
        with gh.owned_profile({"PATH": "/usr/bin:/bin"}, settings_bytes=pi._broker_agy_settings_bytes(),
                              credential_path=host.home / TOKEN, admission=admission) as profile:
            assert profile.evidence["provider_image_sha256"] == sha256(data).hexdigest()
            yield profile
    finally:
        admission.close()


def _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, argv, **kwargs):
    host.command = [heartbeat.executable, *argv]
    host.env = heartbeat.env
    return _run_leg(host, monkeypatch, tmp_path, gemini_profile=heartbeat,
                    **{"review_monitor": _monitor(tmp_path), **kwargs})


def test_the_heartbeat_seat_and_the_president_rung_sleep_on_the_operators_login(
        host, heartbeat, sleeps, monkeypatch, tmp_path):
    """The heartbeat route (the board seat, the qualification's seat and the president's
    Gemini rung all launch this way): the login slept on is the one the profile links, not
    ``HOME``'s, and the gate's one renewal runs the profile's own sealed image, re-hashed
    against the profile's digest, with no second lookup.

    Mutation: read ``HOME``'s login in the sleep."""
    _login(host.home, 450)
    with pytest.raises(_LaunchReached):
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--model", "m", "--print="])
    assert len(host.calls()) == 1 and _left(host) > 3500
    (home, _slept_for), = sleeps
    assert home == host.home and _login_wait(tmp_path)["state"] == "expired"


def test_the_help_measurement_neither_sleeps_nor_renews(host, heartbeat, sleeps, monkeypatch,
                                                        tmp_path):
    """``agy --help`` makes no request. An availability probe and an admission lookup measure
    help; in the window they were refused (and the board lost its Google seat at composition).

    Mutations: make ``_gemini_launch_needs_login`` return True for ``--help``; make the gate
    ignore ``needs_login``."""
    for left in (450, -60):
        _login(host.home, left)
        with pytest.raises(_LaunchReached) as reached:
            _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--help"])
        assert reached.value.args[0][1:] == ["--help"] and host.calls() == [] and sleeps == []
    # Only that exact launch: anything else on the same profile needs its login.
    assert pi._gemini_launch_needs_login([heartbeat.executable, "--help"], heartbeat) is False
    for argv in (["--help", "--print="], ["-p", "--help"], ["--version"], []):
        assert pi._gemini_launch_needs_login([heartbeat.executable, *argv], heartbeat) is True
    assert pi._gemini_launch_needs_login(["agy", "--help"], None) is True


def test_the_executor_review_route_sleeps_before_it_holds_anything(host, sleeps, monkeypatch):
    """``launcher.launch(action="review")`` reaches the same gate; the same sleep comes first,
    before its egress namespace. Mutation: remove the call from ``launcher.launch``."""
    _login(host.home, 450)
    order = []

    class _Stop(Exception):
        pass

    def isolated_network(**kwargs):
        order.append(("network", len(sleeps)))
        raise _Stop

    monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
    with pytest.raises(_Stop):
        launcher.launch(host.command, action="review", env=host.env, cwd=str(host.home))
    assert order == [("network", 1)] and sleeps[0][0] == host.home


def test_other_providers_are_not_looked_at(host, monkeypatch):
    monkeypatch.setattr(pi, "_gemini_login_left_s", lambda home: pytest.fail("not a Gemini launch"))
    for command in (["codex", "exec"], ["claude", "-p"], ["grok"], []):
        assert pi._await_gemini_login(command, host.env) == 0.0


# ------------------------------------------------------------------------------ the notices

def test_the_notices_say_what_happens_when_it_ends_and_the_command():
    what, why, fix = seat_jail.NOTICES["gemini_credential_near_expiry"]
    assert what == "leg refused" and "under 10 minutes" in why and "`agy models`" in why
    # ONE command, the renewal's own.
    command = "`DBUS_SESSION_BUS_ADDRESS=unix:path=/dev/null agy models`"
    assert fix.startswith("run " + command + ", then re-run") and "sign in" in fix
    what, why, fix = seat_jail.NOTICES["gemini_credential_refresh_timeout"]
    assert command in fix and "interactively" not in fix
    what, why, fix = seat_jail.NOTICES["gemini_credential_awaiting_refresh"]
    assert what == "waiting" and "until this login's expiry and then renews it once" in why
    assert "ends at the login's expiry" in fix
    # No figure of agy's is promised in a notice.
    for code in ("gemini_credential_near_expiry", "gemini_credential_awaiting_refresh",
                 "gemini_credential_refresh_timeout"):
        assert not re.search(r"5 minutes|300", " ".join(seat_jail.NOTICES[code]))
    assert pi._GEMINI_LOGIN_AWAITING in seat_jail.NOTICE_CODES
    assert pi._GEMINI_LOGIN_AWAITING in pi._HARNESS_DETAIL_CODES
    assert len(seat_jail.NOTICES) == 71      # main's 70 and this one


def test_the_suite_never_sleeps_through_a_real_long_gemini_login_sleep(host):
    """The conftest guard: a test that reaches the real sleep for a long login fails."""
    _login(host.home, 450)
    with pytest.raises(pytest.fail.Exception, match="real Gemini login sleep"):
        pi._await_gemini_login(host.command, host.env)
