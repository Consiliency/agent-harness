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

The invariant the tests hold the wait to: it turns exactly one outcome into a wait -- a
renewal that exits 0 and leaves an unexpired login short. Every other outcome is main's:
what main launched is launched, what main refused is refused with main's code and in main's
place, and a failure main treated as fatal is fatal.

``_FAKE_AGY`` is a real executable with agy's two measured behaviours, run through the real
``_refresh_gemini_credential`` and the real ``launch_provider``; nothing here stubs the
renewal's launch or its environment. Time is not slept through: the fake renews on a stated
call (the clock entering agy's margin) and the wait's poll is a few milliseconds.
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

# agy's measured behaviours. ``$HOME/agy.plan`` (JSON) says on which call the login enters
# agy's renewal margin (``renew_on_call``; 0 = never), whether a reachable session bus makes
# agy use a keyring instead of the file (``keyring``), which calls fail (``exit`` for every
# call, ``exit_on_calls`` for some, ``exit_after`` for the call that wrote the file), which calls
# block until ``$HOME/release`` exists (``block_on_calls``) and whether every call hangs
# (``hang``). Every call is appended to ``$HOME/agy.calls`` with its argv, cwd listing and the
# environment NAMES it was given.
_FAKE_AGY = r'''#!/usr/bin/python3
import datetime, json, os, sys, time
home = os.environ["HOME"]
plan = json.load(open(os.path.join(home, "agy.plan")))
calls = os.path.join(home, "agy.calls")
count = sum(1 for _ in open(calls)) + 1 if os.path.exists(calls) else 1
bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
with open(calls, "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": sorted(os.listdir(".")), "bus": bus,
                          "env": sorted(os.environ), "pid": os.getpid()}) + "\n")
if plan.get("exit") or count in plan.get("exit_on_calls", ()):
    sys.exit(plan.get("exit") or 1)
while plan.get("hang") or (count in plan.get("block_on_calls", ())
                           and not os.path.exists(os.path.join(home, "release"))):
    time.sleep(0.01)
token = os.path.join(home, ".gemini/antigravity-cli/antigravity-oauth-token")
state = json.load(open(token))
expiry = datetime.datetime.fromisoformat(state["token"]["expiry"][:26] + "+00:00")
left = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
in_margin = left < 300 or (plan["renew_on_call"] and count >= plan["renew_on_call"])
keyring = plan.get("keyring") and bus != "unix:path=/dev/null"
wrote = in_margin and not keyring and "refresh_token" in state["token"]
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
    """An operator home with a fake agy on the provider search path. The wait is capped at
    20 s and polled every 10 ms, so nothing is slept through and nothing can spin for long."""
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
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_POLL_MIN_S", 0.0)
    monkeypatch.setenv(pi._GEMINI_LOGIN_POLL_ENV, "0.01")
    monkeypatch.setenv(pi._GEMINI_LOGIN_WAIT_ENV, "20")

    def plan(renew_on_call=0, **more):
        (home / "agy.plan").write_text(json.dumps({"renew_on_call": renew_on_call, **more}))

    def calls():
        path = home / "agy.calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    plan()
    return SimpleNamespace(home=home, agy=agy, image=image, plan=plan, calls=calls,
                           admitted=admitted, env={"HOME": str(home), "PATH": str(bindir)},
                           command=["agy", "--model", "gemini-3.8-flash-medium", "--print="])


def _left(host) -> float:
    return pi._gemini_login_left_s(host.home)


def _gone(pid: int) -> bool:
    """The run's process group (the helper is its leader) is no longer present."""
    return not pi._process_group_exists(pid)


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

    Mutations: make ``_await_gemini_login`` do nothing; shift the "clears by" time."""
    expiry = _login(host.home, 450)
    host.plan(renew_on_call=3)       # the clock enters agy's margin at the third renewal run
    with caplog.at_level(logging.INFO, logger=pi.__name__), pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 3 and _left(host) > 3500
    waiting, = [r.getMessage() for r in caplog.records if "gemini_credential_awaiting_refresh" in r.getMessage()]
    # The notice's own literals (what is happening, what to run), then this wait's numbers.
    _what, why, fix = seat_jail.NOTICES["gemini_credential_awaiting_refresh"]
    assert why in waiting and waiting.endswith(fix)
    numbers = re.search(r"\((4[0-9]{2}) s left; waiting up to (\d+) s, renewing every (\d+) s; it "
                        r"clears by (\d\d):(\d\d):(\d\d) UTC at the latest\)", waiting)
    assert numbers and numbers.group(2) == "20"
    # "Clears by" is the login's own expiry, to the second: the one time the operator is given.
    clears = expiry.replace(hour=int(numbers.group(4)), minute=int(numbers.group(5)),
                            second=int(numbers.group(6)), microsecond=0)
    assert abs((clears - expiry).total_seconds()) <= 2
    assert any("was renewed after" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("left,runs,deadline_s", [(605, 0, 1), (595, 1, 600)])
def test_the_gates_floor_is_600_s_and_the_wait_adds_nothing_above_it(host, monkeypatch, tmp_path,
                                                                     left, runs, deadline_s):
    """Main launched every login with 600 s or more at once, however short the leg's
    deadline; so does this: no renewal run, and the step before the launch gathers nothing
    (the one image lookup is the seat's own). Under 600 s the renewal runs, on its own lookup.

    Mutations: move ``_GEMINI_LOGIN_MIN_S``; make the wait ask for more than the gate."""
    _login(host.home, left)
    host.plan(renew_on_call=1)
    with pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=deadline_s)
    assert len(host.calls()) == runs and len(host.admitted) == runs + 1


def test_a_login_inside_agys_margin_is_renewed_at_once(host, monkeypatch, tmp_path):
    """Under 300 s agy renews on its first run: no wait. (Also the expired case.)"""
    for left in (200, -60):
        _login(host.home, left)
        (host.home / "agy.calls").unlink(missing_ok=True)
        with pytest.raises(_LaunchReached):
            _run_leg(host, monkeypatch, tmp_path)
        assert len(host.calls()) == 1 and _left(host) > 3500


# ------------------------- what main refused is refused with main's code, from main's one run

def test_a_login_agy_never_renews_ends_the_wait_refused_with_mains_code(host, monkeypatch,
                                                                       tmp_path, caplog):
    """The wait is bounded; when it ends short the seat is refused typed, the monitor says
    ``timeout``, and the gate runs no renewal of its own.

    Mutation: let the gate run its own renewal when a refusal was carried to it."""
    _needs_seat_owner()
    _login(host.home, 450)
    monkeypatch.setenv(pi._GEMINI_LOGIN_WAIT_ENV, "0.05")
    monitor = _monitor(tmp_path)
    with caplog.at_level(logging.WARNING, logger=pi.__name__):
        outcome = pi._await_gemini_login(host.command, host.env, review_monitor=monitor)
    assert isinstance(outcome.refusal, sandbox_egress.SeatIdentityUnverified)
    assert str(outcome.refusal) == NEAR_EXPIRY and _login_wait(tmp_path)["state"] == "timeout"
    assert any("was not renewed within" in r.getMessage() and "the seat does not run" in r.getMessage()
               for r in caplog.records)
    waited_runs = len(host.calls())
    assert waited_runs >= 2      # the first run and at least one in the wait
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY) as refused:
        with pi.seat_profile(harness="gemini", executable=str(host.agy), env=host.env,
                             cwd=tmp_path, login_refusal=outcome.refusal):
            pytest.fail("a refused login was admitted")
    assert refused.value is outcome.refusal and len(host.calls()) == waited_runs


@pytest.mark.parametrize("state", ["no_wait_allowed", "expired_not_renewed", "run_fails",
                                   "expiry_unreadable"])
def test_every_refusal_costs_one_renewal_run_as_on_main(host, monkeypatch, tmp_path, state):
    """Main ran the renewal once and refused. So does this: one run, main's code, no wait.

    Mutations: drop the ``left <= 0`` return; wait after a run that failed; let the gate
    run a second renewal."""
    _login(host.home, {"expired_not_renewed": -10}.get(state, 450),
           refresh_token=state != "expired_not_renewed")
    if state == "no_wait_allowed":
        monkeypatch.setenv(pi._GEMINI_LOGIN_WAIT_ENV, "0")
    elif state == "run_fails":
        host.plan(exit=1)
    elif state == "expiry_unreadable":
        (host.home / TOKEN).write_text(json.dumps({"token": {"expiry": "not a time"}}))
    waits = []
    real_wait = pi._gemini_login_wait
    monkeypatch.setattr(pi, "_gemini_login_wait",
                        lambda *a, **k: waits.append(k) or real_wait(*a, **k), raising=False)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 1 and waits == []


def test_a_renewal_that_hangs_is_refused_after_one_run_and_leaves_no_process(host, monkeypatch,
                                                                             tmp_path):
    """Main: one run, ``gemini_credential_refresh_timeout`` after the run's limit. The same
    here -- not two limits. Mutation: let the gate run its own renewal after the wait's."""
    _login(host.home, 450)
    host.plan(hang=True)
    monkeypatch.setattr(pi, "_GEMINI_REFRESH_TIMEOUT_S", 0.3)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified,
                       match="gemini_credential_refresh_timeout"):
        _run_leg(host, monkeypatch, tmp_path)
    call, = host.calls()
    assert _gone(call["pid"])


# ------------------- a failure main refused is never a launch (codex F003, grok G1)

@pytest.mark.parametrize("run", ["first", "polled"])
@pytest.mark.parametrize("failure", ["exit", "quiescence"])
def test_a_failed_renewal_is_never_a_launch(host, monkeypatch, tmp_path, failure, run):
    """The renewal writes a FRESH login and then exits non-zero, or its process group cannot
    be proven gone. The file is fresh afterwards; the seat must still not launch. Main
    refused the first and raised the second.

    Mutations: do not carry the wait's refusal to the gate; catch the quiescence error."""
    _login(host.home, 200 if run == "first" else 450)
    failing_call = 1 if run == "first" else 2
    expected, pattern = sandbox_egress.SeatIdentityUnverified, NEAR_EXPIRY
    if failure == "exit":
        host.plan(renew_on_call=failing_call, exit_on_calls=[], exit_after=1)
    else:
        host.plan(renew_on_call=failing_call)
        terminate = pi._terminate_process_group
        seen = []

        def failed_cleanup(process, **kwargs):
            terminate(process, **kwargs)
            seen.append(process)
            if len(seen) == failing_call:
                raise pi.ProviderProcessGroupQuiescenceError("renewal group not quiescent")

        monkeypatch.setattr(pi, "_terminate_process_group", failed_cleanup)
        expected, pattern = pi.ProviderProcessGroupQuiescenceError, "renewal group not quiescent"
    with pytest.raises(expected, match=pattern):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == failing_call and _left(host) > 3500   # fresh file, no launch


def test_a_quiescence_failure_of_the_image_admission_is_raised_not_retried(host, monkeypatch,
                                                                           tmp_path):
    """Admitting a self-qualified image measures its help in a seat; a group left unproven
    there is fatal on main. Mutation: carry it as a refusal, or admit again."""
    _login(host.home, 450)
    host.plan(renew_on_call=1)
    attempts = []

    def admit(executable, env):
        attempts.append(executable)
        raise pi.ProviderProcessGroupQuiescenceError("help measurement group not quiescent")

    monkeypatch.setattr(agy_integrity, "admit_for_seat", admit)
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError, match="help measurement"):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(attempts) == 1 and host.calls() == []


def test_a_run_that_fails_in_the_middle_of_the_wait_ends_the_leg_with_mains_code(
        host, monkeypatch, tmp_path):
    """Only an exit 0 that renewed nothing is retried. A later run that fails is main's
    refusal, at once; the wait does not go on, and the monitor says ``failed``.

    Mutation: treat a failing run mid-wait as "not yet"."""
    _login(host.home, 450)
    host.plan(renew_on_call=3, exit_on_calls=[2])
    monitor = _monitor(tmp_path)
    outcome = pi._await_gemini_login(host.command, host.env, review_monitor=monitor)
    assert str(outcome.refusal) == NEAR_EXPIRY and len(host.calls()) == 2
    assert _login_wait(tmp_path)["state"] == "failed" and _left(host) < 600


def test_a_run_that_fails_is_refused_even_when_it_left_a_fresh_login(host):
    """Unchanged from main and kept as strong: the renewal must have RUN cleanly. A run that
    exits non-zero is refused whatever the file says afterwards, for the gate and the wait.

    Mutation: accept a fresh file without looking at the run's exit code."""
    for required in (True, False):
        _login(host.home, 200)
        host.plan(exit_after=1)
        with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
            pi._refresh_gemini_credential(host.home, host.image, **({} if required else {"required": False}))
        assert _left(host) > 3500      # the fake did renew the file; the run still failed


@pytest.mark.parametrize("failure", ["refusal", "quiescence"])
def test_a_refusal_keeps_mains_place_and_a_quiescence_failure_is_never_behind_anything(
        host, monkeypatch, tmp_path, failure):
    """Main checks the owner platform (and the provider, the bind sources, the outputs)
    before its gate. A state that fails there AND has a login the renewal refuses keeps the
    earlier check's code. A process group the renewal cannot prove gone is different: it is
    raised at once, never carried behind a check that could replace it.

    Mutations: raise the wait's refusal from the wait itself; carry the quiescence error."""
    _login(host.home, 450)

    def no_owner():
        raise sandbox_egress.SeatIdentityUnverified("seat_owner_unavailable")

    monkeypatch.setattr(pi, "_require_owner_platform", no_owner)
    expected, pattern = sandbox_egress.SeatIdentityUnverified, "seat_owner_unavailable"
    if failure == "refusal":
        host.plan(exit=1)
    else:
        terminate = pi._terminate_process_group

        def failed_cleanup(process, **kwargs):
            terminate(process, **kwargs)
            raise pi.ProviderProcessGroupQuiescenceError("renewal group not quiescent")

        monkeypatch.setattr(pi, "_terminate_process_group", failed_cleanup)
        expected, pattern = pi.ProviderProcessGroupQuiescenceError, "renewal group not quiescent"
    with pytest.raises(expected, match=pattern):
        _run_leg(host, monkeypatch, tmp_path)
    assert len(host.calls()) == 1


# ------------------------------------------------------------------ the wait's own bounds

def test_the_wait_is_bounded_by_the_logins_own_life(host, monkeypatch):
    """At most the login's remaining life plus 45 s: by then agy renews on any start.

    Mutations: drop the ``left + _GEMINI_LOGIN_WAIT_GRACE_S`` bound; set the grace to 0."""
    _login(host.home, 450)
    monkeypatch.setenv(pi._GEMINI_LOGIN_WAIT_ENV, "900")
    monkeypatch.setenv(pi._GEMINI_LOGIN_POLL_ENV, "30")
    seen = {}

    def wait(attempt, *, max_wait_s, poll_s, wait):
        seen.update(max_wait_s=max_wait_s, poll_s=poll_s)
        return False, 0.0

    monkeypatch.setattr(pi, "_gemini_login_wait", wait)
    outcome = pi._await_gemini_login(host.command, host.env)
    assert 440 + 45 < seen["max_wait_s"] <= 450 + 45 and seen["poll_s"] == 30.0
    assert str(outcome.refusal) == NEAR_EXPIRY


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


_SETTINGS = [  # (wait, poll) -> (cap, poll, ignored names)
    ((None, None), (900.0, 30.0, ())),
    (("", "  "), (900.0, 30.0, ())),
    (("0", "5"), (0.0, 5.0, ())),
    (("1e12", "1e12"), (1e12, 1e12, ())),
    (("inf", "inf"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("nan", "-inf"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("-1", "0"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("soon", "1e-6"), (900.0, 30.0, ("WAIT", "POLL"))),
    (("120", "4.99"), (120.0, 30.0, ("POLL",))),
]


@pytest.mark.parametrize("given,expected", _SETTINGS)
def test_a_wait_setting_that_is_not_usable_falls_back_to_the_default(given, expected):
    """Unset, empty, zero, negative, huge, infinite, not a number -- for both settings. A
    poll under 5 s would run agy back to back with the operator's login; it is not accepted.

    Mutation: accept any float (``inf`` then crashed the wait's log line)."""
    env = {name: value for name, value in zip((pi._GEMINI_LOGIN_WAIT_ENV, pi._GEMINI_LOGIN_POLL_ENV),
                                              given) if value is not None}
    cap, poll, ignored = pi._gemini_login_wait_settings(env)
    names = {"WAIT": pi._GEMINI_LOGIN_WAIT_ENV, "POLL": pi._GEMINI_LOGIN_POLL_ENV}
    assert (cap, poll, ignored) == (expected[0], expected[1], tuple(names[n] for n in expected[2]))


def test_an_unusable_setting_is_a_typed_notice_never_a_crash(host, monkeypatch, tmp_path, caplog):
    """Through the real launch path with ``inf`` (which crashed) for both settings."""
    _login(host.home, 450)
    host.plan(renew_on_call=2)
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_POLL_DEFAULT_S", 0.01)
    monkeypatch.setattr(pi, "_GEMINI_LOGIN_WAIT_DEFAULT_S", 20.0)
    monkeypatch.setenv(pi._GEMINI_LOGIN_WAIT_ENV, "inf")
    monkeypatch.setenv(pi._GEMINI_LOGIN_POLL_ENV, "inf")
    with caplog.at_level(logging.WARNING, logger=pi.__name__), pytest.raises(_LaunchReached):
        _run_leg(host, monkeypatch, tmp_path)
    notices = [r.getMessage() for r in caplog.records if "gemini_login_wait_setting_ignored" in r.getMessage()]
    assert len(notices) == 2 and len(host.calls()) == 2
    _what, why, fix = seat_jail.NOTICES["gemini_login_wait_setting_ignored"]
    for name, notice in zip((pi._GEMINI_LOGIN_WAIT_ENV, pi._GEMINI_LOGIN_POLL_ENV), notices):
        assert name in notice and why in notice and fix in notice


def test_the_claude_login_waits_settings_do_not_move_this_wait(host, monkeypatch):
    """They were shared: a cap set for the Claude wait changed this one. Mutation: read
    ``PHASE_LOOP_SEAT_LOGIN_REFRESH_*`` here."""
    from phase_loop_runtime import seat_credentials as sc

    monkeypatch.setenv(sc.WAIT_ENV, "0")
    monkeypatch.setenv(sc.POLL_ENV, "7")
    monkeypatch.delenv(pi._GEMINI_LOGIN_WAIT_ENV)
    monkeypatch.delenv(pi._GEMINI_LOGIN_POLL_ENV)
    assert pi._gemini_login_wait_settings() == (900.0, 30.0, ())
    assert {pi._GEMINI_LOGIN_WAIT_ENV, pi._GEMINI_LOGIN_POLL_ENV}.isdisjoint({sc.WAIT_ENV, sc.POLL_ENV})


# ------------------------------------- cancellation, the latch and the runs (codex F006)

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
    errors, done = [], threading.Event()

    def run():
        token = pi._BOARD_CANCEL.set(cancel) if how == "board_context" else None
        try:
            pi._await_gemini_login(host.command, host.env, review_monitor=monitor,
                                   quiescence_latch=latch)
        except BaseException as error:  # noqa: BLE001 - the assertion is on what was raised
            errors.append(error)
        finally:
            if token is not None:
                pi._BOARD_CANCEL.reset(token)
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors, done


def _ended_as(how, errors):
    expected = (pi.ProviderProcessGroupQuiescenceError if how == "latch_trip"
                else pi._ReviewOperationCancelled)
    assert len(errors) == 1 and isinstance(errors[0], expected), errors


def test_a_cancelled_poll_loop_raises_and_runs_no_further_renewal():
    attempts = []
    with pytest.raises(pi._ReviewOperationCancelled, match="review_operation_cancelled"):
        pi._gemini_login_wait(lambda: attempts.append(1), max_wait_s=600.0, poll_s=30.0,
                              wait=lambda seconds: True, monotonic=lambda: 0.0)
    assert attempts == []


@pytest.mark.parametrize("how", _CANCELS)
def test_nothing_is_started_for_a_leg_already_cancelled_or_latched(host, tmp_path, how):
    """Main's renewal ran inside the latch's launch, so a cancelled or tripped leg ran none.
    Neither does the wait -- not the image lookup either. Mutation: drop the check made
    before anything is gathered."""
    _login(host.home, 450)
    host.plan(renew_on_call=1)
    cancel, latch, monitor, fire = _cancel_sources(how, tmp_path)
    fire()
    thread, errors, done = _await_in_thread(host, how, cancel, latch, monitor)
    assert done.wait(30)
    _ended_as(how, errors)
    assert host.calls() == [] and host.admitted == [] and _left(host) < 600


@pytest.mark.parametrize("how", _CANCELS)
def test_board_cancellation_wakes_the_wait(host, monkeypatch, tmp_path, how):
    """The cancel arrives from another thread while the poll would sleep. What is asserted is
    that the wait ENDED AS CANCELLED after its first renewal and before a second -- not how
    long it took. Mutations: sleep on a private event; drop the latch re-check."""
    _login(host.home, 450)
    monkeypatch.setenv(pi._GEMINI_LOGIN_POLL_ENV, "60")
    cancel, latch, monitor, fire = _cancel_sources(how, tmp_path)
    entered = threading.Event()
    real_wait = pi._gemini_login_wait.real      # past the conftest guard: this wait IS cancelled

    def announced_wait(attempt, *, wait, **kwargs):
        def waiting(seconds):
            entered.set()
            return wait(seconds)
        return real_wait(attempt, wait=waiting, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_wait", announced_wait)
    thread, errors, done = _await_in_thread(host, how, cancel, latch, monitor)
    assert entered.wait(30)
    fired = time.monotonic()
    fire()
    assert done.wait(30)
    _ended_as(how, errors)
    assert len(host.calls()) == 1 and _left(host) < 600
    # It was the SLEEP that woke, not the sleep running out (20 s here) into the next check.
    assert time.monotonic() - fired < 10
    if monitor is not None:
        assert _login_wait(tmp_path)["state"] == "cancelled"


@pytest.mark.parametrize("how", _CANCELS)
def test_a_cancel_during_a_renewal_run_ends_it_and_leaves_no_process(host, monkeypatch,
                                                                      tmp_path, how):
    """The second renewal run is alive (blocked until the test releases it, which it does
    only afterwards) when the cancel arrives. The wait must end on the cancel, and the run's
    process group must be gone; with a latch, the latch's own sweep has accounted for it.

    Mutations: run the helper with one blocking ``communicate``; launch it outside the latch."""
    _login(host.home, 450)
    host.plan(renew_on_call=3, block_on_calls=[2])
    cancel, latch, monitor, fire = _cancel_sources(how, tmp_path)
    original_launch, launches, in_flight = pi.launch_provider, [], threading.Event()

    def launch(*args, **kwargs):
        process = original_launch(*args, **kwargs)
        launches.append(process)
        if len(launches) == 2:
            communicate = process.communicate

            def announced(*a, **k):
                in_flight.set()
                return communicate(*a, **k)

            process.communicate = announced
        return process

    monkeypatch.setattr(pi, "launch_provider", launch)
    thread, errors, done = _await_in_thread(host, how, cancel, latch, monitor)
    try:
        assert in_flight.wait(30)
        if latch is not None:
            assert not latch.is_quiescent()      # the run is the latch's, like any provider group
        fire()
        if how == "latch_trip":
            assert _gone(launches[1].pid)        # the trip's sweep returned with the run gone
        ended = done.wait(30)
    finally:
        (host.home / "release").touch()
        thread.join(30)
    assert ended and not thread.is_alive(), "the cancel did not end the renewal run in flight"
    _ended_as(how, errors)
    assert len(launches) == 2 and all(_gone(process.pid) for process in launches)
    assert latch is None or latch.is_quiescent()
    assert _left(host) < 600


def test_a_cancel_ends_a_wait_queued_behind_another_seats_renewal(host, tmp_path):
    """Renewals of several seats queue on one lock. A seat cancelled while it queues starts
    nothing afterwards. Mutation: take the lock with a plain blocking acquire."""
    _login(host.home, 450)
    host.plan(renew_on_call=1)
    cancel, latch, monitor, fire = _cancel_sources("monitor", tmp_path)
    with pi._GEMINI_REFRESH_LOCK:                 # another seat's renewal is in flight
        thread, errors, done = _await_in_thread(host, "monitor", cancel, latch, monitor)
        assert not done.wait(0.3)                 # it queues; it has not given up
        fire()
        assert done.wait(30)
    _ended_as("monitor", errors)
    assert host.calls() == []


def test_a_cancel_arriving_as_the_renewals_lock_is_taken_starts_nothing(host, monkeypatch,
                                                                         tmp_path):
    """The check made before a run is started is made with the lock held: a cancel that
    lands between the queue and the launch still starts nothing.

    Mutation: check only before the lock is taken."""
    _login(host.home, 450)
    host.plan(renew_on_call=1)
    cancel = threading.Event()

    class _CancelledAsTaken:
        def acquire(self, timeout=None):
            cancel.set()
            return True

        def release(self):
            pass

    launched = []
    launch = pi.launch_provider
    monkeypatch.setattr(pi, "launch_provider",
                        lambda *a, **k: launched.append(a) or launch(*a, **k))
    monkeypatch.setattr(pi, "_GEMINI_REFRESH_LOCK", _CancelledAsTaken())
    with pytest.raises(pi._ReviewOperationCancelled):
        pi._await_gemini_login(host.command, host.env, review_monitor=_monitor(tmp_path, cancel))
    assert launched == [] and host.calls() == []


def test_the_wait_runs_outside_the_quiescence_latchs_launch_lock(host, monkeypatch, tmp_path):
    """The latch launches a seat under one lock; a minutes-long wait inside it would block
    every cancel and trip. While the seat waits, the lock is free.

    Mutation: hold the latch's lock around the wait."""
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
    assert held == [False] and latch.is_quiescent()


def test_the_legs_renewal_is_one_provider_spawn_however_often_it_is_re_run(host):
    """Main counted the renewal as one provider spawn of the leg. Polling must not multiply
    that in the leg's evidence. Mutation: count every run."""
    _login(host.home, 450)
    host.plan(renew_on_call=5)
    counter = pi._SpawnCounter()
    token = pi._LEG_SPAWNS.set(counter)
    try:
        outcome = pi._await_gemini_login(host.command, host.env)
    finally:
        pi._LEG_SPAWNS.reset(token)
    assert outcome.refusal is None and len(host.calls()) == 5 and counter.count == 1


# ------------------------------------------------------- monitoring and deadlines (codex F007)

def test_heartbeat_only_records_a_login_wait_and_restarts_the_stall_clock(host, tmp_path):
    _login(host.home, 450)
    host.plan(renew_on_call=3)
    monitor = _monitor(tmp_path)
    monitor.started = time.monotonic() - 10_000        # an old start: the wait must reset it
    states = []
    real_note = monitor.note
    monitor.note = lambda **fields: (states.append(fields["login_wait"]["state"]), real_note(**fields))[1]
    outcome = pi._await_gemini_login(host.command, host.env, review_monitor=monitor)
    assert outcome.refusal is None and outcome.spent_s > 0
    assert states == ["awaiting_refresh", "refreshed"]
    assert _login_wait(tmp_path)["max_wait_s"] == 20.0
    assert time.monotonic() - monitor.started < 60


def _slow_renewals(monkeypatch, seconds):
    """Every renewal run takes ``seconds`` of injected monotonic time (codex's instrument).
    Returns the injected offset, so a test can move the clock further."""
    actual_clock, elapsed = time.monotonic, [0.0]
    monkeypatch.setattr(pi.time, "monotonic", lambda: actual_clock() + elapsed[0])
    original_launch = pi.launch_provider

    def launch(*args, **kwargs):
        process = original_launch(*args, **kwargs)
        communicate = process.communicate

        def slow(*a, **k):
            result = communicate(*a, **k)
            elapsed[0] += seconds
            return result

        process.communicate = slow
        return process

    monkeypatch.setattr(pi, "launch_provider", launch)
    return elapsed


def test_the_first_renewal_is_charged_to_a_bounded_legs_deadline(host, monkeypatch, tmp_path):
    """The renewal succeeds at once but took 3 s of a 1 s deadline: there is no leg left to
    run. Mutation: charge only the time spent waiting."""
    _login(host.home, 200)
    _slow_renewals(monkeypatch, 3.0)
    with pytest.raises(subprocess.TimeoutExpired):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=1.0)
    assert len(host.calls()) == 1 and _left(host) > 3500


def test_a_bounded_leg_keeps_what_the_renewal_and_the_wait_left_of_its_deadline(
        host, monkeypatch, tmp_path):
    """3 s per run, the login renewed on the second: 6 s (and the poll) are charged to a 20 s
    deadline, and the leg's own backstop then reports what is LEFT. Mutation: do not subtract."""
    _login(host.home, 450)
    host.plan(renew_on_call=2)
    clock = _slow_renewals(monkeypatch, 3.0)

    def seat(command, **kwargs):
        process = subprocess.Popen(["/bin/sleep", "600"], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        poll = process.poll

        def outlives_any_deadline(*a, **k):     # so the leg's backstop fires on its next look
            process.poll = poll
            clock[0] += 1000.0
            return poll(*a, **k)

        process.poll = outlives_any_deadline
        return process

    monkeypatch.setattr(pi, "_seat_command_profile", _no_profile)
    monkeypatch.setattr(pi, "launch_owned", seat)
    egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
    try:
        with pytest.raises(subprocess.TimeoutExpired) as expired:
            pi._run_leg_with_liveness(host.command, cwd=tmp_path, env=host.env, deadline_s=20,
                                      stall_threshold_s=1e9)   # the deadline, not the stall
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(egress)
    assert 8 < expired.value.timeout <= 14 and len(host.calls()) == 2


def test_a_bounded_wait_that_runs_out_is_mains_refusal_not_a_timeout(host, monkeypatch, tmp_path):
    """450 s left and a deadline too short to reach agy's renewal. Main refused at once,
    typed. Waiting must not retype that as the leg's deadline, and the wait is bounded by
    what the first run left of the deadline (1 s per run here, injected).

    Mutations: raise ``TimeoutExpired`` when a refusal is pending; ignore the deadline."""
    _login(host.home, 450)
    _slow_renewals(monkeypatch, 1.0)
    seen = {}
    real_wait = pi._gemini_login_wait

    def wait(attempt, *, max_wait_s, **kwargs):
        seen["max_wait_s"] = max_wait_s
        return real_wait(attempt, max_wait_s=max_wait_s, **kwargs)

    monkeypatch.setattr(pi, "_gemini_login_wait", wait)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=5.5)
    assert 0 < seen["max_wait_s"] <= 4.5 and 2 <= len(host.calls()) <= 6


def test_a_run_cut_by_a_bounded_legs_deadline_is_not_renewed_and_leaves_no_process(
        host, monkeypatch, tmp_path):
    """A run still alive when the leg's deadline arrives is ended there. That is "not
    renewed" (main's refusal for a short login), not the run's own timeout.

    Mutation: give every run its full limit whatever the deadline."""
    _login(host.home, 450)
    host.plan(hang=True)
    started = time.monotonic()
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=NEAR_EXPIRY):
        _run_leg(host, monkeypatch, tmp_path, deadline_s=0.4)
    assert time.monotonic() - started < pi._GEMINI_REFRESH_TIMEOUT_S   # not the run's 15 s
    assert host.calls() and all(_gone(call["pid"]) for call in host.calls())


def test_a_heartbeat_legs_wait_ignores_the_backstop_deadline(host, monkeypatch, tmp_path):
    _login(host.home, 450)
    seen = {}
    monkeypatch.setattr(pi, "_gemini_login_wait",
                        lambda attempt, *, max_wait_s, poll_s, wait: seen.update(m=max_wait_s) or (False, 0.0))
    pi._await_gemini_login(host.command, host.env, review_monitor=_monitor(tmp_path), deadline_s=5)
    assert seen["m"] == 20.0


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


def test_the_heartbeat_seat_and_the_president_rung_wait_on_the_operators_login(
        host, heartbeat, monkeypatch, tmp_path):
    """The heartbeat route (the board seat, the qualification's seat and the president's
    Gemini rung all launch this way): the login is the one the profile links, not ``HOME``'s,
    and the renewal runs the profile's own sealed image, re-hashed against the profile's
    digest, with no second lookup.

    Mutations: read ``HOME``'s login; look the image up again; hand ``VerifiedImage`` a
    digest other than the profile's."""
    _login(host.home, 450)
    host.plan(renew_on_call=2)
    with pytest.raises(_LaunchReached):
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--model", "m", "--print="])
    assert len(host.calls()) == 2 and _left(host) > 3500
    assert _login_wait(tmp_path)["state"] == "refreshed"


def test_a_cancelled_board_renews_nothing_on_the_heartbeat_route(host, heartbeat, monkeypatch,
                                                                 tmp_path):
    _login(host.home, 450)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(pi._ReviewOperationCancelled):
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--model", "m", "--print="],
                       review_monitor=_monitor(tmp_path, cancel))
    assert host.calls() == []


def test_the_help_measurement_neither_waits_nor_needs_a_fresh_login(host, heartbeat, monkeypatch,
                                                                     tmp_path):
    """``agy --help`` makes no request. An availability probe and an admission lookup measure
    help; in the window they were refused (and the board lost its Google seat at composition).

    Mutation: make ``_gemini_launch_needs_login`` return True for ``--help``."""
    _login(host.home, 450)
    monkeypatch.setattr(pi, "_gemini_login_wait", lambda *a, **k: pytest.fail("help waited"),
                        raising=False)
    with pytest.raises(_LaunchReached) as reached:
        _run_heartbeat(host, heartbeat, monkeypatch, tmp_path, ["--help"])
    assert reached.value.args[0][1:] == ["--help"] and host.calls() == []
    # Only that exact launch: anything else on the same profile needs its login.
    assert pi._gemini_launch_needs_login([heartbeat.executable, "--help"], heartbeat) is False
    for argv in (["--help", "--print="], ["-p", "--help"], ["--version"], []):
        assert pi._gemini_launch_needs_login([heartbeat.executable, *argv], heartbeat) is True
    assert pi._gemini_launch_needs_login(["agy", "--help"], None) is True


def test_the_executor_review_route_waits_first_and_hands_its_refusal_to_the_gate(host, monkeypatch):
    """``launcher.launch(action="review")`` reaches the same gate: the wait comes before
    anything is held, and what it refused is what the gate is given.

    Mutations: remove the call from ``launcher.launch``; do not pass the refusal on."""
    order, refusal = [], sandbox_egress.SeatIdentityUnverified(NEAR_EXPIRY)

    def wait(command, env, **kwargs):
        order.append(("wait", list(command), env["HOME"]))
        return pi._GeminiLoginWait(1.0, refusal)

    class _Stop(Exception):
        pass

    @contextmanager
    def isolated_network(**kwargs):
        order.append(("network",))
        yield ("synthetic-filtered-namespace",)

    def profile(command, **kwargs):
        order.append(("gate", kwargs.get("gemini_login_refusal")))
        raise _Stop

    monkeypatch.setattr(pi, "_await_gemini_login", wait)
    monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
    monkeypatch.setattr(pi, "_seat_command_profile", profile)
    with pytest.raises(_Stop):
        launcher.launch(host.command, action="review", env=host.env, cwd=str(host.home))
    assert order == [("wait", host.command, str(host.home)), ("network",), ("gate", refusal)]


def test_other_providers_and_what_main_refuses_before_its_gate_are_left_alone(host, monkeypatch):
    nothing = pi._GeminiLoginWait()
    with monkeypatch.context() as patch:
        patch.setattr(pi, "_gemini_login_left_s", lambda home: pytest.fail("not a Gemini launch"))
        for command in (["codex", "exec"], ["claude", "-p"], ["grok"], []):
            assert pi._await_gemini_login(command, host.env) == nothing
    # No login file: the launch refuses it (seat_profile_unavailable) before its gate.
    assert pi._await_gemini_login(["agy", "--print="], host.env) == nothing
    # No such provider: the same.
    _login(host.home, 450)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(host.home))
    assert pi._await_gemini_login(["agy", "--print="], host.env) == nothing
    assert host.calls() == [] and host.admitted == []


# ------------------------------------------------------------------------------ the notices

def test_the_notices_say_what_happens_when_it_clears_and_the_command():
    what, why, fix = seat_jail.NOTICES["gemini_credential_near_expiry"]
    assert what == "leg refused" and "under 10 minutes" in why and "`agy models`" in why
    # ONE command, the renewal's own.
    command = "`DBUS_SESSION_BUS_ADDRESS=unix:path=/dev/null agy models`"
    assert fix.startswith("run " + command + ", then re-run") and "sign in" in fix
    what, why, fix = seat_jail.NOTICES["gemini_credential_refresh_timeout"]
    assert command in fix and "interactively" not in fix
    what, why, fix = seat_jail.NOTICES["gemini_credential_awaiting_refresh"]
    assert what == "waiting" and "by the login's expiry at the latest" in fix
    # agy's measured margin is a measurement, not a promise the notices make.
    for code in ("gemini_credential_near_expiry", "gemini_credential_awaiting_refresh",
                 "gemini_credential_refresh_timeout"):
        assert "5 minutes" not in " ".join(seat_jail.NOTICES[code])
    for code in (pi._GEMINI_LOGIN_AWAITING, pi._GEMINI_LOGIN_SETTING_IGNORED):
        assert code in seat_jail.NOTICE_CODES and code in pi._HARNESS_DETAIL_CODES
    # The command in the notices is the address the renewal itself uses.
    assert pi._GEMINI_REFRESH_NO_SESSION_BUS == NO_BUS


@pytest.mark.parametrize("poll", ["0.01", "30"])
def test_the_suite_never_sleeps_through_a_real_long_gemini_login_wait(host, monkeypatch, poll):
    """The conftest guard: a test that reaches the real wait with a long bound fails,
    however short its poll (a short poll with a long bound spins the most processes)."""
    _login(host.home, 450)
    monkeypatch.setenv(pi._GEMINI_LOGIN_WAIT_ENV, "900")
    monkeypatch.setenv(pi._GEMINI_LOGIN_POLL_ENV, poll)
    with pytest.raises(pytest.fail.Exception, match="real Gemini login wait"):
        pi._await_gemini_login(host.command, host.env)
