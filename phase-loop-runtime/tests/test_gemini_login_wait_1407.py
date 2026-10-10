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

The mechanism under test: the launch gate is main's. When its renewal ran cleanly and left the
login short, the launch SLEEPS -- it starts no process and takes no lock -- until the login
has expired, and then goes through the same gate again. Everything else is main's: its
checks before the gate, its one renewal lock, its refusals and their codes.

``_FAKE_AGY`` is a real executable with agy's measured behaviours, run through the real gate,
the real ``_refresh_gemini_credential`` and the real ``launch_provider``. Most tests replace
the sleep by ``_expire`` (the clock reaching the login's expiry); the ones that are about the
sleep itself run it for real on a login a second from expiry.
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
# The sleep's own settings, by their documented names (so that this file also runs, and is
# red for the right reasons, against a tree that predates them).
WAIT_ENV = "PHASE_LOOP_SEAT_GEMINI_LOGIN_REFRESH_WAIT_S"
POLL_ENV = "PHASE_LOOP_SEAT_GEMINI_LOGIN_REFRESH_POLL_S"

# agy's measured behaviours. ``$HOME/agy.plan`` (JSON): ``margin`` is how close to its expiry
# agy renews a login (300 s measured; 0 = only once it has expired, the one fact the runtime
# relies on), ``never`` makes it renew nothing, ``keyring`` makes a reachable session bus take
# the login instead of the file, ``exit`` fails every call, ``exit_after`` fails the call that
# wrote the file. Every call is appended to ``$HOME/agy.calls`` with its argv, cwd listing,
# pid and the environment NAMES it was given.
_FAKE_AGY = r'''#!/usr/bin/python3
import datetime, json, os, sys
home = os.environ["HOME"]
plan = json.load(open(os.path.join(home, "agy.plan")))
calls = os.path.join(home, "agy.calls")
bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
with open(calls, "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": sorted(os.listdir(".")), "bus": bus,
                          "env": sorted(os.environ), "pid": os.getpid()}) + "\n")
if plan.get("exit"):
    sys.exit(plan["exit"])
token = os.path.join(home, ".gemini/antigravity-cli/antigravity-oauth-token")
state = json.load(open(token))
expiry = datetime.datetime.fromisoformat(state["token"]["expiry"][:26] + "+00:00")
left = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
keyring = plan.get("keyring") and bus != "unix:path=/dev/null"
wrote = (left < plan.get("margin", 300) and not plan.get("never") and not keyring
         and "refresh_token" in state["token"])
if wrote:
    fresh = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    state["token"].update(access_token="synthetic-renewed-access",
                          expiry=fresh.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z")
    with open(token, "w") as out:      # agy rewrites its file in place (measured)
        json.dump(state, out)
if wrote and plan.get("exit_after"):
    sys.exit(plan["exit_after"])
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
    admitted = []

    def admit_for_seat(executable, env):
        admitted.append(executable)
        return image

    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bindir))
    monkeypatch.setattr(agy_integrity, "admit_for_seat", admit_for_seat)
    monkeypatch.delenv(WAIT_ENV, raising=False)
    monkeypatch.delenv(POLL_ENV, raising=False)

    def plan(**behaviour):
        (home / "agy.plan").write_text(json.dumps(behaviour))

    def calls():
        path = home / "agy.calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    plan()
    return SimpleNamespace(home=home, agy=agy, image=image, plan=plan, calls=calls,
                           admitted=admitted, env={"HOME": str(home), "PATH": str(bindir)},
                           command=["agy", "--model", "gemini-3.8-flash-medium", "--print="])


def _left(host) -> float:
    return pi._gemini_login_left_s(host.home)


@pytest.fixture
def sleeps(host, monkeypatch):
    """Replace the sleep by the clock reaching the login's expiry: the login file is
    rewritten as expired. Each sleep is recorded as ``(home, seconds it would have slept)``."""
    slept = []

    def expire(home, need, **kwargs):
        slept.append((Path(home), need))
        state = json.loads((Path(home) / TOKEN).read_text())
        gone = datetime.now(timezone.utc) - timedelta(seconds=1)
        state["token"]["expiry"] = gone.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z"
        (Path(home) / TOKEN).write_text(json.dumps(state))
        return "expired"

    monkeypatch.setattr(pi, "_gemini_login_sleep_until", expire, raising=False)
    return slept


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


def _monitor(tmp_path, cancel=None):
    return pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, cancel or threading.Event())


def _login_wait(tmp_path):
    return json.loads((tmp_path / "monitor.json").read_text()).get("login_wait")


def _short(host):
    """The gate's refusal for a login a clean renewal left short, as the gate raises it."""
    return pi._GeminiLoginLeftShort(NEAR_EXPIRY, host.home)


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

def test_a_seat_in_the_window_sleeps_until_the_login_expires_and_then_launches(
        host, sleeps, monkeypatch, tmp_path, caplog):
    """450 s left: under the seat's 600 s, above agy's 300 s. Main refused the seat here.
    The gate's renewal is a no-op; the launch sleeps to the login's expiry (plus 5 s); the
    same gate then renews an expired login and the seat launches.

    Mutations: do not catch the gate's refusal in ``_run_leg_with_liveness``; shift the
    notice's time; say something other than the notice row."""
    expiry = _login(host.home, 450)
    with caplog.at_level(logging.INFO, logger=pi.__name__), pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 2 and _left(host) > 3500
    (home, need), = sleeps
    assert home == host.home and 445 + 5 < need <= 450 + 5
    waiting, = [r.getMessage() for r in caplog.records if "gemini_credential_awaiting_refresh" in r.getMessage()]
    # The notice's own literals (what is happening, what to run), then this sleep's numbers.
    _what, why, fix = seat_jail.NOTICES["gemini_credential_awaiting_refresh"]
    assert why in waiting and waiting.endswith(fix)
    numbers = re.search(r"\((4[0-9]{2}) s left; waiting (4[0-9]{2}) s, until (\d\d):(\d\d):(\d\d) UTC; "
                        r"re-reading the login every 30 s\)", waiting)
    assert numbers and int(numbers.group(2)) == int(need)
    # The time given is when the sleep ends: the login's expiry plus the margin, to the second.
    ends = expiry + timedelta(seconds=5)
    stated = ends.replace(hour=int(numbers.group(3)), minute=int(numbers.group(4)),
                          second=int(numbers.group(5)), microsecond=0)
    assert abs((stated - ends).total_seconds()) <= 2


def test_the_real_sleep_starts_no_process_and_takes_no_lock(host, processes, monkeypatch, tmp_path):
    """The whole thing for real, on a login a second from expiry and an agy that renews only
    an expired login (the one fact relied on): a no-op renewal, a real sleep, a renewal.
    The process spy sees the two renewals and nothing in between; while the launch sleeps,
    neither the renewal lock nor the quiescence latch's launch lock is held.

    Mutations: run a renewal from inside the sleep; hold either lock across it; report a
    sleep that ran out as a renewal."""
    _login(host.home, 1.2)
    host.plan(margin=0)
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_WAIT_MARGIN_S", 0.3)
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_POLL_MIN_S", 0.0)
    monkeypatch.setenv(POLL_ENV, "0.05")
    latch = pi._ProviderQuiescenceLatch()
    during = []
    real_fresh = pi._gemini_credential_fresh
    sleeping = threading.Event()
    real_sleep = pi._gemini_login_sleep_until

    ended = []

    def sleep(home, need, **kwargs):
        sleeping.set()
        try:
            ended.append(real_sleep(home, need, **kwargs))
            return ended[-1]
        finally:
            sleeping.clear()

    def fresh(home):
        if sleeping.is_set():       # one of the sleep's re-reads of the login file
            free = latch._lock.acquire(blocking=False)
            if free:
                latch._lock.release()
            during.append((len(processes), pi._GEMINI_REFRESH_LOCK.locked(), free))
        return real_fresh(home)

    monkeypatch.setattr(pi, "_gemini_login_sleep_until", sleep)
    monkeypatch.setattr(pi, "_gemini_credential_fresh", fresh)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path, quiescence_latch=latch)
    assert len(host.calls()) == 2 and _left(host) > 3500
    assert [argv[1:] for argv in processes] == [["models"], ["models"]]
    assert len(during) >= 3 and set(during) == {(1, False, True)}
    assert ended == ["expired"] and latch.is_quiescent()     # it ran out; nothing renewed it


@pytest.mark.parametrize("left,runs,deadline_s", [(605, 0, 1), (595, 1, 600)])
def test_the_gates_floor_is_600_s_and_nothing_is_added_above_it(host, sleeps, monkeypatch, tmp_path,
                                                                left, runs, deadline_s):
    """Main launched every login with 600 s or more at once, however short the leg's
    deadline; so does this, with no renewal run. Under 600 s the gate's renewal runs once.

    Mutation: move ``_GEMINI_LOGIN_MIN_S``."""
    _login(host.home, left)
    host.plan(margin=100_000)       # this agy would renew anything it is asked to
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=deadline_s)
    assert len(host.calls()) == runs and sleeps == []


def test_a_login_inside_agys_margin_is_renewed_at_once_without_a_sleep(host, sleeps, monkeypatch,
                                                                       tmp_path):
    """Under 300 s agy renews on the gate's one run, as on main: no sleep. (Also expired.)

    Mutation: sleep whenever the login is short, before the gate has tried."""
    for left in (200, -60):
        _login(host.home, left)
        (host.home / "agy.calls").unlink(missing_ok=True)
        with pytest.raises(_LaunchReached):
            _run_leg(host, monkeypatch, tmp_path)
        assert len(host.calls()) == 1 and _left(host) > 3500 and sleeps == []


# ------------------------- what main refused is refused with main's code, from main's one run

@pytest.mark.parametrize("state", ["never_wait", "sleep_longer_than_allowed", "expired_not_renewed",
                                   "run_fails", "run_fails_after_writing", "expiry_unreadable"])
def test_every_refusal_is_mains_from_one_renewal_run_and_no_sleep(host, sleeps, monkeypatch,
                                                                  tmp_path, state):
    """Main ran the renewal once and refused ``gemini_credential_near_expiry``. So does this
    in every state that is not "agy ran cleanly and the login can still expire". A renewal
    that wrote a fresh login and then failed is never a launch.

    Mutations: sleep for an expired login; sleep whatever the setting; sleep after a run
    that failed."""
    _login(host.home, {"expired_not_renewed": -10, "run_fails_after_writing": 200}.get(state, 450),
           refresh_token=state != "expired_not_renewed")
    if state == "never_wait":
        monkeypatch.setenv(WAIT_ENV, "0")
    elif state == "sleep_longer_than_allowed":
        monkeypatch.setenv(WAIT_ENV, "454")       # the sleep would be 455 s
    elif state == "run_fails":
        host.plan(exit=1)
    elif state == "run_fails_after_writing":
        host.plan(exit_after=1)
    elif state == "expiry_unreadable":
        (host.home / TOKEN).write_text(json.dumps({"token": {"expiry": "not a time"}}))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 1 and sleeps == []
    if state == "run_fails_after_writing":
        assert _left(host) > 3500      # the file IS fresh; the seat still did not launch


def test_a_login_agy_does_not_renew_even_once_expired_is_refused_after_one_sleep(
        host, sleeps, monkeypatch, tmp_path):
    """The sleep is taken once. If the gate's renewal still leaves the login short after it,
    that is main's refusal; there is no second sleep. Mutation: sleep again."""
    _login(host.home, 450)
    host.plan(never=True)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 2 and len(sleeps) == 1


@pytest.mark.parametrize("failure", ["exit", "quiescence"])
def test_a_renewal_that_fails_after_the_sleep_is_mains_too(host, sleeps, monkeypatch, tmp_path,
                                                           failure):
    """The second pass through the gate is the gate: a renewal that writes a fresh login and
    exits non-zero is refused, and one whose process group cannot be proven gone raises that,
    exactly as on main. (codex F003, grok G1: nothing here can swallow either.)"""
    _login(host.home, 450)
    expected, pattern = sandbox_egress.SeatIdentityUnverified, NEAR_EXPIRY
    if failure == "exit":
        host.plan(exit_after=1)
    else:
        terminate = pi._terminate_process_group
        seen = []

        def failed_cleanup(process, **kwargs):
            terminate(process, **kwargs)
            seen.append(process)
            if len(seen) == 2:
                raise pi.ProviderProcessGroupQuiescenceError("renewal group not quiescent")

        monkeypatch.setattr(pi, "_terminate_process_group", failed_cleanup)
        expected, pattern = pi.ProviderProcessGroupQuiescenceError, "renewal group not quiescent"
    with pytest.raises(expected, match=pattern):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 2 and len(sleeps) == 1 and _left(host) > 3500


def test_a_quiescence_failure_of_the_first_renewal_is_raised_and_nothing_sleeps(
        host, sleeps, monkeypatch, tmp_path):
    _login(host.home, 450)
    terminate = pi._terminate_process_group

    def failed_cleanup(process, **kwargs):
        terminate(process, **kwargs)
        raise pi.ProviderProcessGroupQuiescenceError("renewal group not quiescent")

    monkeypatch.setattr(pi, "_terminate_process_group", failed_cleanup)
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError, match="renewal group not quiescent"):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 1 and sleeps == []


@pytest.mark.parametrize("check", ["bind", "owner"])
def test_what_main_refuses_before_its_gate_runs_no_renewal_and_does_not_sleep(
        host, sleeps, processes, monkeypatch, tmp_path, check):
    """codex F010: a request main refuses BEFORE its credential gate (a linked bind source,
    no owner platform) is refused the same way here: no host renewal with the operator's
    login, no sleep. The sleep can only follow the gate, so it is behind every such check.

    Mutation: sleep (or renew) before the launch's own checks."""
    _login(host.home, 450)
    if check == "bind":
        source = tmp_path / "source"
        source.write_text("synthetic input")
        link = tmp_path / "input-link"
        link.symlink_to(source)
        host.command += ["--file", str(link)]
        code = "seat_bind_source_unavailable"
    else:
        def no_owner():
            raise sandbox_egress.SeatIdentityUnverified("seat_owner_unavailable")

        monkeypatch.setattr(pi, "_require_owner_platform", no_owner)
        code = "seat_owner_unavailable"
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=code):
        _run_leg(host, monkeypatch, tmp_path)
    assert host.calls() == [] and processes == [] and sleeps == []


def test_the_gates_refusal_is_the_same_refusal_for_every_other_caller(host):
    """``_GeminiLoginLeftShort`` is ``gemini_credential_near_expiry``: same class family, same
    message, same leg detail. Only the launch that may sleep tells the two apart."""
    _login(host.home, 450)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY) as refused:
        pi._refresh_gemini_credential(host.home, host.image)
    assert type(refused.value) is pi._GeminiLoginLeftShort and refused.value.home == host.home
    assert str(refused.value) == NEAR_EXPIRY and pi._exception_failure(refused.value) == NEAR_EXPIRY
    host.plan(exit=1)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY) as failed:
        pi._refresh_gemini_credential(host.home, host.image)
    assert type(failed.value) is sandbox_egress.SeatIdentityUnverified     # a failure: no sleep


# ------------------------------------------------------------------ the sleep itself

def _sleep_in_thread(host, how, cancel, latch, monitor, **kwargs):
    outcome, done = [], threading.Event()

    def run():
        token = pi._BOARD_CANCEL.set(cancel) if how == "board_context" else None
        try:
            outcome.append(pi._gemini_login_sleep(_short(host), review_monitor=monitor,
                                                  quiescence_latch=latch, **kwargs))
        except BaseException as error:  # noqa: BLE001 - the assertion is on what was raised
            outcome.append(error)
        finally:
            if token is not None:
                pi._BOARD_CANCEL.reset(token)
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome, done


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


@pytest.mark.parametrize("already", [False, True])
@pytest.mark.parametrize("how", _CANCELS)
def test_a_cancel_or_a_latch_ends_the_sleep_at_once_and_there_is_nothing_to_clean_up(
        host, processes, monkeypatch, tmp_path, how, already):
    """A 455 s sleep, cancelled from another thread (or cancelled before it starts). It ends
    as cancelled (a latch trip: with the latch's own error), long before it would have run
    out, and the process spy saw nothing: there is no helper to end and no lock to release.

    Mutations: sleep on a private event; do not re-check the latch."""
    _login(host.home, 450)
    cancel, latch, monitor, fire = _cancel_sources(how, tmp_path)
    entered = threading.Event()
    real = pi._gemini_login_sleep_until.real    # past the conftest guard: this sleep IS cancelled

    def announced(home, need, **kwargs):
        entered.set()
        return real(home, need, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_sleep_until", announced)
    if already:
        fire()
    thread, outcome, done = _sleep_in_thread(host, how, cancel, latch, monitor)
    assert entered.wait(30)
    fired = time.monotonic()
    if not already:
        fire()
    assert done.wait(30)
    expected = (pi.ProviderProcessGroupQuiescenceError if how == "latch_trip"
                else pi._ReviewOperationCancelled)
    assert len(outcome) == 1 and isinstance(outcome[0], expected), outcome
    assert time.monotonic() - fired < 10        # it was woken; it did not run out (455 s)
    assert processes == [] and not pi._GEMINI_REFRESH_LOCK.locked()
    assert latch is None or latch.is_quiescent()
    if monitor is not None:
        assert _login_wait(tmp_path)["state"] == "cancelled"


def test_the_sleep_ends_early_when_something_else_renews_the_login(host, processes, monkeypatch,
                                                                   tmp_path):
    """The sleep re-reads the login file every interval, only to notice this. The launch
    then passes the gate with no renewal run of its own.

    Mutation: never re-read during the sleep."""
    _login(host.home, 450)
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_POLL_MIN_S", 0.0)
    monkeypatch.setenv(POLL_ENV, "0.05")
    entered = threading.Event()
    real = pi._gemini_login_sleep_until.real

    def announced(home, need, **kwargs):
        entered.set()
        return real(home, need, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_sleep_until", announced)
    cancel = threading.Event()
    monitor = _monitor(tmp_path, cancel)
    thread, outcome, done = _sleep_in_thread(host, "monitor", cancel, None, monitor)
    assert entered.wait(30)
    _login(host.home, 3000)                      # e.g. the operator's own agy renewed it
    ended = done.wait(30)
    cancel.set()                                 # only matters if it did not end by itself
    thread.join(30)
    assert ended and isinstance(outcome[0], float), outcome     # ended, well before the 455 s
    assert _login_wait(tmp_path)["state"] == "refreshed" and processes == []
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert host.calls() == []


def test_a_login_renewed_between_the_gate_and_the_sleep_launches_again_without_sleeping(
        host, sleeps, monkeypatch, tmp_path):
    """The gate refused; by the time the launch would sleep, something else has renewed the
    login. No sleep, and no refusal either: the launch goes through the gate again.

    Mutation: treat a login that is fresh by then like one that cannot be slept on."""
    _login(host.home, 450)
    short = _short(host)
    _login(host.home, 3000)
    assert pi._gemini_login_sleep(short) == 0.0 and sleeps == []
    _login(host.home, 450)
    real = pi._gemini_login_sleep

    def renewed_meanwhile(short, **kwargs):
        _login(host.home, 3000)
        return real(short, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_sleep", renewed_meanwhile)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 1 and sleeps == []


@pytest.mark.parametrize("login", ["unreadable", "expired", "gone"])
def test_there_is_no_sleep_for_a_login_whose_expiry_is_unreadable_or_past(host, sleeps, login):
    """Whatever happened to the login file between the gate's refusal and the sleep, the
    sleep either has a future expiry to sleep to or does not happen: never an error of its
    own. Mutations: sleep for an expired login; drop the unreadable case."""
    _login(host.home, -5 if login == "expired" else 450)
    short = _short(host)
    if login == "unreadable":
        (host.home / TOKEN).write_text(json.dumps({"token": {"expiry": "not a time"}}))
    elif login == "gone":
        (host.home / TOKEN).write_text("")
    assert pi._gemini_login_sleep(short) is None and sleeps == []


def test_two_seats_in_the_window_sharing_one_latch_both_launch(host, monkeypatch, tmp_path):
    """Two launches in the window, sharing ONE quiescence latch (grok H1's deadlock shape),
    for real on a login a second from expiry. Each sleeps without holding anything; the
    gate's one lock order is main's. Both launch; the second finds the login renewed.

    Mutation: take the renewal lock, or the latch, around the sleep."""
    _needs_seat_owner()
    _login(host.home, 1.2)
    host.plan(margin=0)
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_WAIT_MARGIN_S", 0.3)
    latch = pi._ProviderQuiescenceLatch()
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

    threads = [threading.Thread(target=seat, args=(name,), daemon=True) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not any(thread.is_alive() for thread in threads), "two seats sharing a latch deadlocked"
    assert results == [_LaunchReached, _LaunchReached]
    assert 3 <= len(host.calls()) <= 4 and _left(host) > 3500 and latch.is_quiescent()


_SETTINGS = [  # (longest wait, re-read interval) -> (longest, interval, ignored names)
    ((None, None), (900.0, 30.0, ())),
    (("", "  "), (900.0, 30.0, ())),
    (("0", "1"), (0.0, 1.0, ())),
    (("1e12", "1e12"), (1e12, 1e12, ())),
    (("inf", "inf"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("nan", "-inf"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("-1", "0"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("soon", "1e-6"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("120", "0.99"), (120.0, 30.0, ("POLL",))),
]


@pytest.mark.parametrize("given,expected", _SETTINGS)
def test_a_setting_that_is_not_usable_falls_back_to_the_default(given, expected):
    """Unset, empty, zero, negative, huge, infinite, not a number -- for both settings.

    Mutations: accept any float (``inf`` crashed a log line); drop the interval's floor."""
    env = {name: value for name, value in zip((WAIT_ENV, POLL_ENV), given) if value is not None}
    longest, poll, ignored = pi._gemini_login_wait_settings(env)
    names = {"WAIT": WAIT_ENV, "POLL": POLL_ENV}
    assert (longest, poll, ignored) == (expected[0], expected[1], tuple(names[n] for n in expected[2]))


def test_an_unusable_setting_is_a_typed_notice_never_a_crash(host, sleeps, monkeypatch, tmp_path,
                                                             caplog):
    """Through the real launch path with ``inf`` for both settings: two typed notices, the
    defaults are used, and the seat waits and launches. Mutation: do not announce it."""
    _login(host.home, 450)
    monkeypatch.setenv(WAIT_ENV, "inf")
    monkeypatch.setenv(POLL_ENV, "inf")
    with caplog.at_level(logging.WARNING, logger=pi.__name__), pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    notices = [r.getMessage() for r in caplog.records if "gemini_login_wait_setting_ignored" in r.getMessage()]
    assert len(notices) == 2 and len(sleeps) == 1
    _what, why, fix = seat_jail.NOTICES["gemini_login_wait_setting_ignored"]
    for name, notice in zip((WAIT_ENV, POLL_ENV), notices):
        assert name in notice and why in notice and fix in notice


@pytest.mark.parametrize("poll", ["1", "30", "1e12"])
def test_the_time_the_notice_gives_does_not_depend_on_the_settings(host, sleeps, monkeypatch,
                                                                   tmp_path, caplog, poll):
    """codex F011: the notice's time is when the sleep ends -- the login's expiry plus the
    margin -- whatever the re-read interval is; and a longest wait too short for that sleep
    means no sleep and no notice at all, never a promise the settings break.

    Mutation: derive the notice's time from the interval or the longest wait."""
    expiry = _login(host.home, 450)
    monkeypatch.setenv(POLL_ENV, poll)
    with caplog.at_level(logging.WARNING, logger=pi.__name__):
        assert pi._gemini_login_sleep(_short(host)) is not None
    line, = [r.getMessage() for r in caplog.records if "gemini_credential_awaiting_refresh" in r.getMessage()]
    hour, minute, second = map(int, re.search(r"until (\d\d):(\d\d):(\d\d) UTC", line).groups())
    ends = expiry + timedelta(seconds=5)
    assert abs((ends.replace(hour=hour, minute=minute, second=second, microsecond=0) - ends).total_seconds()) <= 2
    (_home, need), = sleeps
    assert 450 < need <= 455
    caplog.clear()
    monkeypatch.setenv(WAIT_ENV, "400")
    with caplog.at_level(logging.WARNING, logger=pi.__name__):
        assert pi._gemini_login_sleep(_short(host)) is None
    assert not [r for r in caplog.records if "gemini_credential_awaiting_refresh" in r.getMessage()]


def test_the_claude_login_waits_settings_do_not_move_this_sleep(host, monkeypatch):
    """Mutation: read ``PHASE_LOOP_SEAT_LOGIN_REFRESH_*`` here."""
    from phase_loop_runtime import seat_credentials as sc

    monkeypatch.setenv(sc.WAIT_ENV, "0")
    monkeypatch.setenv(sc.POLL_ENV, "7")
    assert pi._gemini_login_wait_settings() == (900.0, 30.0, ())
    assert (pi._GEMINI_LOGIN_WAIT_ENV, pi._GEMINI_LOGIN_POLL_ENV) == (WAIT_ENV, POLL_ENV)
    assert {WAIT_ENV, POLL_ENV}.isdisjoint({sc.WAIT_ENV, sc.POLL_ENV})


# ------------------------------------------------------------------ monitoring and deadlines

def test_heartbeat_only_records_the_sleep_and_restarts_the_stall_clock(host, sleeps, tmp_path):
    """Recorded as ``login_wait``; the backstop deadline does not bound a monitored sleep.

    Mutations: do not restart the stall clock; bound a heartbeat sleep by the deadline."""
    _login(host.home, 450)
    monitor = _monitor(tmp_path)
    monitor.started = time.monotonic() - 10_000        # an old start: the sleep must reset it
    states = []
    real_note = monitor.note
    monitor.note = lambda **fields: (states.append(fields["login_wait"]["state"]), real_note(**fields))[1]
    assert pi._gemini_login_sleep(_short(host), review_monitor=monitor, deadline_s=5) is not None
    assert states == ["awaiting_refresh", "expired"] and len(sleeps) == 1
    assert 450 < _login_wait(tmp_path)["max_wait_s"] <= 455
    assert time.monotonic() - monitor.started < 60


@pytest.mark.parametrize("deadline_s,sleeps_expected", [(455.5, 1), (449, 0)])
def test_a_bounded_leg_sleeps_only_when_the_whole_sleep_fits_its_deadline(
        host, sleeps, monkeypatch, tmp_path, deadline_s, sleeps_expected):
    """A sleep that would not fit in the leg's deadline is not started: the gate's refusal
    stands, with main's code and at once, as on main (grok G2, claude F2). One that fits is
    taken. Mutation: sleep anyway and let the deadline cut it."""
    _login(host.home, 450)
    host.plan(never=True)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=deadline_s)
    assert len(sleeps) == sleeps_expected and len(host.calls()) == 1 + sleeps_expected


def test_a_bounded_leg_is_charged_the_whole_sleep(host, monkeypatch, tmp_path):
    """450 s to the login's expiry, a 600 s deadline: the leg sleeps 455 s (injected clock)
    and its own backstop then reports what is LEFT. Mutation: do not subtract the sleep."""
    _login(host.home, 450)
    actual, offset = time.monotonic, [0.0]
    monkeypatch.setattr(pi.time, "monotonic", lambda: actual() + offset[0])

    def sleep(home, need, **kwargs):
        offset[0] += need
        _login(host.home, -1)
        return "expired"

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

    monkeypatch.setattr(pi, "_gemini_login_sleep_until", sleep)
    monkeypatch.setattr(pi, "_seat_command_profile", _fresh_or_left_short(host))
    monkeypatch.setattr(pi, "launch_owned", seat)
    egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
    try:
        with pytest.raises(subprocess.TimeoutExpired) as expired:
            pi._run_leg_with_liveness(host.command, cwd=tmp_path, env=host.env, deadline_s=600,
                                      stall_threshold_s=1e9)   # the deadline, not the stall
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(egress)
    assert 140 < expired.value.timeout < 150


def _fresh_or_left_short(host):
    """A launch profile whose gate is main's rule on the login file, without the seat owner
    (so this runs where sealed memfds are missing too)."""
    @contextmanager
    def profile(command, **kwargs):
        if pi._gemini_login_left_s(host.home) > 0:
            raise pi._GeminiLoginLeftShort(NEAR_EXPIRY, host.home)
        yield list(command), pi.SeatProfile(env={})
    return profile


# ------------------------------------------------------------------ every caller of the gate

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
    ``HOME``'s, and both of the gate's renewals run the profile's own sealed image,
    re-hashed against the profile's digest, with no second lookup."""
    _login(host.home, 450)
    with pytest.raises(_LaunchReached):
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--model", "m", "--print="])
    assert len(host.calls()) == 2 and _left(host) > 3500
    (home, _need), = sleeps
    assert home == host.home and _login_wait(tmp_path)["state"] == "expired"


def test_a_cancelled_board_renews_nothing_and_does_not_sleep(host, heartbeat, sleeps, monkeypatch,
                                                             tmp_path):
    _login(host.home, 450)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(pi._ReviewOperationCancelled):
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--model", "m", "--print="],
                       review_monitor=_monitor(tmp_path, cancel))
    assert host.calls() == [] and sleeps == []


def test_the_help_measurement_neither_sleeps_nor_needs_a_fresh_login(host, heartbeat, sleeps,
                                                                     monkeypatch, tmp_path):
    """``agy --help`` makes no request. An availability probe and an admission lookup measure
    help; in the window they were refused (and the board lost its Google seat at composition).

    Mutations: make ``_gemini_launch_needs_login`` return True for ``--help``; make the gate
    ignore ``needs_login``."""
    _login(host.home, 450)
    with pytest.raises(_LaunchReached) as reached:
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--help"])
    assert reached.value.args[0][1:] == ["--help"] and host.calls() == [] and sleeps == []
    # Only that exact launch: anything else on the same profile needs its login.
    assert pi._gemini_launch_needs_login([heartbeat.executable, "--help"], heartbeat) is False
    for argv in (["--help", "--print="], ["-p", "--help"], ["--version"], []):
        assert pi._gemini_launch_needs_login([heartbeat.executable, *argv], heartbeat) is True
    assert pi._gemini_launch_needs_login(["agy", "--help"], None) is True


def test_the_executor_review_route_sleeps_and_goes_through_the_gate_again(host, sleeps, monkeypatch):
    """``launcher.launch(action="review")`` reaches the same gate through
    ``_seat_command_profile_after_gemini_login``: the gate, the sleep, the gate again. With
    no sleep the gate's refusal stands.

    Mutations: have the launcher call ``_seat_command_profile``; do not enter it again."""
    _login(host.home, 450)
    order = []

    class _Stop(Exception):
        pass

    @contextmanager
    def isolated_network(**kwargs):
        order.append("network")
        yield ("synthetic-filtered-namespace",)

    real_profile = _fresh_or_left_short(host)

    @contextmanager
    def profile(command, **kwargs):
        order.append("gate")
        with real_profile(command, **kwargs) as entered:
            yield entered

    def nested(command, **kwargs):      # the review itself, once the profile is entered
        order.append("review")
        raise _Stop

    monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
    monkeypatch.setattr(pi, "_seat_command_profile", profile)
    real_launch = launcher.launch
    monkeypatch.setattr(launcher, "launch", lambda command, **kwargs: (
        nested(command, **kwargs) if kwargs.get("_review_profile") is not None
        else real_launch(command, **kwargs)))
    with pytest.raises(_Stop):
        launcher.launch(host.command, action="review", env=host.env, cwd=str(host.home))
    assert order == ["network", "gate", "gate", "review"] and len(sleeps) == 1
    # No sleep allowed: the refusal, from one pass.
    _login(host.home, 450)
    order.clear()
    monkeypatch.setenv(WAIT_ENV, "0")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        launcher.launch(host.command, action="review", env=host.env, cwd=str(host.home))
    assert order == ["network", "gate"] and len(sleeps) == 1


def test_a_seat_that_slept_counts_the_gates_two_renewals(host, sleeps, monkeypatch, tmp_path):
    """Disclosed, not hidden: the gate ran its renewal twice (before and after the sleep), and
    each is counted as a provider spawn of the leg, as main counts the gate's one."""
    _login(host.home, 450)
    counter = pi._SpawnCounter()
    token = pi._LEG_SPAWNS.set(counter)
    try:
        with pytest.raises(_LaunchReached):
            _run_leg(host, monkeypatch, tmp_path)
    finally:
        pi._LEG_SPAWNS.reset(token)
    assert len(host.calls()) == 2 and counter.count == 2


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
    assert what == "waiting" and "has expired" in why and "ends when the login expires" in fix
    # agy's measured margin is a measurement, not a promise the notices make.
    for code in ("gemini_credential_near_expiry", "gemini_credential_awaiting_refresh",
                 "gemini_credential_refresh_timeout"):
        assert "5 minutes" not in " ".join(seat_jail.NOTICES[code])
    for code in (pi._GEMINI_LOGIN_AWAITING, pi._GEMINI_LOGIN_SETTING_IGNORED):
        assert code in seat_jail.NOTICE_CODES and code in pi._HARNESS_DETAIL_CODES
    # The command in the notices is the address the renewal itself uses.
    assert pi._GEMINI_REFRESH_NO_SESSION_BUS == NO_BUS


def test_the_suite_never_sleeps_through_a_real_long_gemini_login_sleep(host):
    """The conftest guard: a test that reaches the real sleep for a long login fails."""
    _login(host.home, 450)
    with pytest.raises(pytest.fail.Exception, match="real Gemini login sleep"):
        pi._gemini_login_sleep(_short(host))
