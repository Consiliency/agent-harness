"""Shared pytest fixtures for the phase-loop-runtime test suite."""
from __future__ import annotations

import functools
import hashlib
import os
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from _outside_agent_canonical import (
    ALL_OUTSIDE_AGENT_NODE_IDS,
    CONFORM_MIGRATED_EXISTING_NODE_IDS,
    CONFORM_NEW_PRODUCTION_NODE_IDS,
    assert_named_canonical_capability,
    canonical_mode_enabled,
    normalized_nodeid,
)
from _dotfiles_tree import dotfiles_tree_present
from _quarantine import deselect_quarantined


_CONFORM_BODY_COUNTER_ENV = "PHASE_LOOP_CONFORM_BODY_COUNTER"

# DECOUPLE SL-1: the dotfiles-domain CLI commands (adoption-bundle, sync-skills,
# build-bundle, hotfix) now load only via the dotfiles-profile plugin. The bulk of
# the suite exercises those commands through build_parser()/main() and expects them
# present, so opt the dotfiles profile in suite-wide (matching how
# phase_loop_test_utils pins PHASE_LOOP_RUNNER_REPO_ROOT). Tests that assert the
# *gating* behavior (test_phase_loop_cli_plugin_load.py) override this explicitly
# via patch.dict / build_parser_with_profile.
os.environ.setdefault(
    "PHASE_LOOP_PROFILE_PLUGINS",
    "phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands",
)

# DISENTANGLE (EXTRACTSKILLS SL-2): the per-harness overlay source roots moved out
# of skill_inventory.HARNESS_SOURCE_ROOTS and behind the
# phase_loop_runtime.skill_sources seam. In source-mode (PYTHONPATH=src:tests, how
# this suite and CI run) the dist-info entry point is not live, so opt the in-tree
# dotfiles skill-sources plugin in suite-wide -- exactly as the profile plugin above
# -- so resolve_source_skill_dir / classify_skill_like_directories still resolve the
# dotfiles roots. Tests that assert the EMPTY/clean-runtime behavior override this
# explicitly (pop the env var + cache_clear).
os.environ.setdefault(
    "PHASE_LOOP_SKILL_SOURCE_PLUGINS",
    "phase_loop_runtime.skill_sources_plugin:register_skill_sources",
)


@pytest.fixture(autouse=True)
def _isolate_host_state(monkeypatch, tmp_path):
    """Keep the suite off the developer's host state (Consiliency/agent-harness#779).

    Two production resolvers deliberately read the REAL account/environment, and a
    test that reaches them without an explicit override otherwise inherits whatever
    the host carries:

    * ``convergence.broker.live.default_fabpub_authority_root`` falls back to
      ``$XDG_STATE_HOME/phase-loop/fabpub/authority-v1`` -- on a host that has run
      ``phase-loop fabpub-bootstrap`` that is a live ACTIVE bootstrap whose sealed
      inventory names worktrees that may since have been pruned, so the cutover path
      raises ``LegacyCutoverConflict`` in tests that never asked for it
      (``test_train_runner.py::TestCLIRegistration``, ``test_fabpub_shared_epoch.py``).
    * ``agy_canary_evidence.inventory_customizations`` reads ``os.environ`` (via
      ``prepare``'s ``dict(os.environ)`` default and the pre-launch revalidation) and
      fails closed on ANY name under ``_CUSTOMIZATION_ENV_PREFIXES``; one stray
      ``GEMINI_*``/``AGY_*``/``XDG_CONFIG_*`` export in the developer shell turns ~45
      canary nodes red with "active agy customization source detected".

    Neither is a product defect -- both guards are meant to fire on real hosts -- so
    the isolation lives here, per test, and never in the resolvers. Tests that
    exercise the fallback or the guard deliberately still win: they monkeypatch after
    this fixture has run (``delenv`` / ``setenv`` on the same ``monkeypatch``), and
    ``freeze_customization_inventory`` takes ``env=`` explicitly. CI's bare container
    carries no such state, which is why only local runs ever saw these reds.
    """
    from phase_loop_runtime.agy_canary_evidence import (
        _CUSTOMIZATION_ENV_EXEMPT,
        _CUSTOMIZATION_ENV_PREFIXES,
    )
    from phase_loop_runtime.convergence.broker.live import FABPUB_AUTHORITY_ROOT_ENV

    authority_root = tmp_path / "fabpub-authority-isolated"
    authority_root.mkdir()
    monkeypatch.setenv(FABPUB_AUTHORITY_ROOT_ENV, str(authority_root))
    for name in list(os.environ):
        if name.startswith(_CUSTOMIZATION_ENV_PREFIXES) and name not in _CUSTOMIZATION_ENV_EXEMPT:
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _isolate_implicit_review_authority(monkeypatch):
    from phase_loop_runtime import panel_invoker

    real_check = panel_invoker._govlean_authority_switched
    monkeypatch.setattr(
        panel_invoker,
        "_govlean_authority_switched",
        lambda repo_dir: False if repo_dir is None else real_check(repo_dir),
    )


def pytest_configure(config):
    """Register the dotfiles_integration marker from conftest so it is known both
    in-tree (where pyproject.toml's [tool.pytest.ini_options] also registers it)
    and STANDALONE in the extracted agent-harness layout (where the wheel does not
    carry pyproject.toml, so the ini registration is absent and an unregistered
    marker would emit PytestUnknownMarkWarning)."""
    config.addinivalue_line(
        "markers",
        "dotfiles_integration: test requires a dotfiles fleet tree (skipped standalone)",
    )

    # Consiliency/agent-harness#378: abort collection with ONE actionable line if
    # the installed consiliency-contract violates this package's declared floor.
    # A stale contract (e.g. 0.6.0 below the >=0.6.5 floor) ships a manifest schema
    # that rejects its own version const, fanning a single ValidationError out into
    # ~60 opaque node failures -- indistinguishable, in a raw "74 failed" count,
    # from a real regression. Failing here converts that into a readable, non-zero
    # exit before any scaffold-using test runs. It is a no-op when the contract
    # satisfies the floor (CI, clean-room wheel) or when the state is unreadable.
    from phase_loop_runtime.consiliency_layout import (
        ContractFloorError,
        check_installed_contract_floor,
    )

    from _contract_floor_wiring import CONTRACT_FLOOR_PREFLIGHT_RAN

    try:
        check_installed_contract_floor()
    except ContractFloorError as exc:
        raise pytest.UsageError(str(exc)) from exc
    # WIRING sentinel (board #382 r3, Blocker 2): record that the preflight was actually
    # invoked in THIS collection. test_conftest_actually_invokes_the_floor_preflight
    # reds if this block is deleted -- a guard that is never called must not read as one
    # that passed. Set only on the non-aborting path (a raise becomes a UsageError above,
    # which aborts collection, so no test observes the stash anyway).
    config.stash[CONTRACT_FLOOR_PREFLIGHT_RAN] = True


def pytest_collection_modifyitems(config, items):
    """TESTDECOUPLE SL-0: skip ``dotfiles_integration``-marked items when no
    dotfiles fleet tree is reachable (the extracted ``agent-harness`` standalone
    layout). In-tree (the tree is present) they run unchanged.

    This run-time hook covers items whose modules import WITHOUT touching dotfiles
    paths. Integration modules that read dotfiles paths at *import* time carry an
    additional module-level ``pytest.skip(..., allow_module_level=True)`` guard
    (SL-1), because markers are only consulted after a module is imported.
    """
    if not dotfiles_tree_present():
        skip_marker = pytest.mark.skip(reason="requires dotfiles tree (dotfiles_integration)")
        for item in items:
            if item.get_closest_marker("dotfiles_integration") is not None:
                item.add_marker(skip_marker)

    # agent-harness#1029: active only when PHASE_LOOP_DESELECT_QUARANTINE=1 (hosted PR suite).
    deselect_quarantined(config, items)

    canonical_mode = canonical_mode_enabled()
    for item in items:
        raw_nodeid = getattr(item, "nodeid", None)
        # Unit tests of this hook use deliberately minimal synthetic items.  They
        # exercise dotfiles selection only, so CONFORM classification must remain
        # a no-op until pytest has supplied a real string node id.
        if not isinstance(raw_nodeid, str):
            continue
        nodeid = normalized_nodeid(raw_nodeid)
        if nodeid not in ALL_OUTSIDE_AGENT_NODE_IDS:
            continue
        item.user_properties.append(("conform_expected_node_id", nodeid))
        if not canonical_mode and nodeid in CONFORM_NEW_PRODUCTION_NODE_IDS:
            item.add_marker(
                pytest.mark.skip(
                    reason="CONFORM SL-0 awaits the exact production capability marker"
                )
            )


def _record_migrated_body_invocation(nodeid: str) -> None:
    """Record the actual pyfunc call only when the focused falsifier opts in."""
    counter_path = os.environ.get(_CONFORM_BODY_COUNTER_ENV)
    if not counter_path:
        return
    path = Path(counter_path)
    counts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    counts[nodeid] = counts.get(nodeid, 0) + 1
    path.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run each activated migrated test's one strict dialect-adapted body.

    Historical bodies intentionally keep their legacy assertions for default
    compatibility mode.  Activation selects the strict adapter for the same
    named guarantee; it must not first run incompatible legacy assertions or
    issue a second validator call.
    """
    nodeid = normalized_nodeid(pyfuncitem.nodeid)
    if not (
        canonical_mode_enabled()
        and nodeid in CONFORM_MIGRATED_EXISTING_NODE_IDS
    ):
        return None
    _record_migrated_body_invocation(nodeid)
    assert_named_canonical_capability(nodeid)
    return True


@pytest.fixture(autouse=True)
def _pin_claude_print_route_by_default():
    """Pin PHASE_LOOP_CLAUDE_ROUTE=print as the suite-wide test default.

    DFCHROUTE flipped the PRODUCTION default for an unset Claude route from
    `claude_print` to `claude_channel` (the v47-validated default). The bulk of
    the suite, however, exercises the Claude *execution* path (closeout parsing,
    auth preflight, schema delivery, repair/closeout flow) and just needs a
    runnable Claude spec — it does not care about the route default. Without an
    explicit route those tests would now resolve to `claude_channel`, which
    correctly blocks with no session and so never produces a launchable spec.

    Pinning the explicit `print` route keeps the execution-path tests testing
    execution. The route-default FLIP itself is asserted explicitly (with explicit
    env) in tests/test_phase_loop_claude_route_selection.py, and tests that need a
    different route override this via patch.dict / explicit `env=`.
    """

    # Also neutralize CI so the suite default is a deterministic interactive
    # context regardless of the host (this repo's own GitHub Actions set CI=true):
    # without this, a test that does patch.dict(..., clear=True) and then builds a
    # Claude spec would, under real CI, resolve an unset route to claude_channel and
    # block with no session — a CI-only flake. Tests that exercise the CI-block path
    # set CI explicitly via patch.dict (which overrides this).
    prior_route = os.environ.get("PHASE_LOOP_CLAUDE_ROUTE")
    prior_ci = os.environ.get("CI")
    os.environ["PHASE_LOOP_CLAUDE_ROUTE"] = "print"
    os.environ.pop("CI", None)
    try:
        yield
    finally:
        if prior_route is None:
            os.environ.pop("PHASE_LOOP_CLAUDE_ROUTE", None)
        else:
            os.environ["PHASE_LOOP_CLAUDE_ROUTE"] = prior_route
        if prior_ci is None:
            os.environ.pop("CI", None)
        else:
            os.environ["CI"] = prior_ci


# ---------------------------------------------------------------------------
# Opt-in CI phase timing (Consiliency/agent-harness#945)
#
# The CONFORM chronology node
# `test_mutation_definitions_are_frozen_but_not_executed_preimplementation`
# is the single longest node in CI even though its source bytes are unchanged
# between v0.7.14 and v0.7.15. Earlier revisions of this header quoted 47.5 min
# (py3.10) and 66.2 min (Gate A); those came from ONE main run (35583021739) and
# are WITHDRAWN -- superseded by the nine-point main-push series on
# agent-harness#945, which is measured across content-inert and optimisation
# commits and revises the cost DOWNWARD. Do not re-quote the single-run pair. The
# block below attributes that wall clock to call sites and records the counters
# that could couple it to repo size (child processes, bytes hashed, tree copies,
# tar members extracted, files read).
#
# It has no behavioural side effect unless PHASE_LOOP_CONFORM_TIMING=1 is set in
# the *parent* pytest process. With the flag unset the hook below returns
# immediately, no wrapper class is built and no symbol is rebound, so
# `subprocess.Popen`, `shutil.copytree`, `shutil.rmtree`,
# `tarfile.TarFile.extractall`, `Path.read_bytes` and `Path.read_text` keep their
# original identities. With the flag set the wrappers are installed for the
# duration of one measured test call and restored in a `finally` at the end of
# that call. That alone does NOT keep a wrapper out of teardown: a fixture that
# captured the wrapper during the call can reinstall it on teardown (the
# resurrection documented at `_conform_timing_sweep`). It is the teardown SWEEP
# that unbinds such a wrapper before the next test runs.
#
# The mutation and EC probes build an explicit child environment from a fixed
# whitelist, so the flag never reaches THOSE nested pytest runs and probe output
# bytes are unchanged. This is scoped to the probes: other nested pytest runs in
# the suite may inherit `os.environ`, and with the flag set would print their own
# timing reports into their own stdout.
# ---------------------------------------------------------------------------

_CONFORM_TIMING_ENV = "PHASE_LOOP_CONFORM_TIMING"

# Children that outlive the test that spawned them are charged to that test
# (see `_TimedPopen._conform_record`). If one completes after its test's report
# has already printed, the event lands here and is reported at session end
# rather than being silently attributed to an unrelated test.
_CONFORM_LATE_EVENTS: list[dict] = []


def _conform_timing_enabled() -> bool:
    return os.environ.get(_CONFORM_TIMING_ENV) == "1"


class _ConformTimingRecorder:
    """Wall-clock and scale accounting for one test, keyed by call site."""

    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.events: list[dict] = []
        self.counters: dict[str, int] = {}
        self.started = time.perf_counter()
        self.reported = False

    # -- accounting ---------------------------------------------------------
    def bump(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def add(self, *, kind: str, label: str, site: str, seconds: float, **extra) -> dict:
        event = {
            "kind": kind,
            "label": label,
            "site": site,
            "seconds": seconds,
            "offset": max(0.0, (time.perf_counter() - seconds) - self.started),
            **extra,
        }
        self.events.append(event)
        if self.reported:
            # The report for this test has already printed; surface the event at
            # session end instead of losing it or charging it to another test.
            _CONFORM_LATE_EVENTS.append({"nodeid": self.nodeid, **event})
        return event

    # -- call-site attribution ---------------------------------------------
    @staticmethod
    def site(depth: int = 3) -> str:
        """Name the call site as a short caller chain.

        One frame is not enough here: every probe and most git calls funnel
        through the `_run_bound_child` / `git` pass-through wrappers, so a
        single frame collapses unrelated phases onto one line.
        """
        frame = sys._getframe(1)
        skip = (__file__, subprocess.__file__, shutil.__file__, tarfile.__file__)
        chain: list[str] = []
        while frame is not None and len(chain) < depth:
            filename = frame.f_code.co_filename
            if not any(filename == candidate for candidate in skip if candidate):
                chain.append(
                    f"{os.path.basename(filename)}:{frame.f_lineno} {frame.f_code.co_name}"
                )
            frame = frame.f_back
        return " <- ".join(chain) if chain else "<unknown>"

    @staticmethod
    def command_label(argv) -> str:
        try:
            parts = [str(part) for part in argv]
        except TypeError:
            return "<opaque>"
        if not parts:
            return "<empty>"
        head = os.path.basename(parts[0])
        if head == "git":
            return "git " + " ".join(parts[1:2])
        if "-m" in parts[:3] and "pytest" in parts[:4]:
            return "python -m pytest"
        if "-c" in parts[:2]:
            return "python -c <probe>"
        return head

    # -- report -------------------------------------------------------------
    def report(self, total: float) -> str:
        lines: list[str] = []
        write = lines.append
        write("")
        write("=" * 78)
        write(f"CONFORM TIMING agent-harness#945 :: {self.nodeid}")
        write(f"total wall seconds: {total:.2f}")
        for key, value in _conform_repo_scale_cached():
            write(f"repo scale :: {key}: {value}")
        write("-" * 78)

        by_site: dict[tuple[str, str], list[float]] = {}
        by_label: dict[str, list[float]] = {}
        for event in self.events:
            by_site.setdefault((event["site"], event["label"]), []).append(event["seconds"])
            by_label.setdefault(event["label"], []).append(event["seconds"])

        write("phase breakdown by call site (seconds, calls, label)")
        ranked = sorted(by_site.items(), key=lambda item: -sum(item[1]))
        for (site, label), seconds in ranked[:30]:
            write(
                f"  {sum(seconds):9.2f}s  {100 * sum(seconds) / total if total else 0:5.1f}%"
                f"  n={len(seconds):<5d} {label:<22s} {site}"
            )
        write("-" * 78)
        write("aggregate by command kind")
        for label, seconds in sorted(by_label.items(), key=lambda item: -sum(item[1])):
            write(
                f"  {sum(seconds):9.2f}s  {100 * sum(seconds) / total if total else 0:5.1f}%"
                f"  n={len(seconds):<5d} {label}"
            )
        write("-" * 78)
        write("slowest individual calls (offset from test start)")
        for event in sorted(self.events, key=lambda item: -item["seconds"])[:15]:
            extra = " ".join(
                f"{key}={value}"
                for key, value in event.items()
                if key not in {"kind", "label", "site", "seconds", "offset"}
            )
            write(
                f"  t+{event['offset']:8.2f}s  {event['seconds']:8.2f}s"
                f"  {event['label']:<22s} {event['site']}  {extra}"
            )
        write("-" * 78)
        write("probe children by payload identity (seconds, calls, stdin digests)")
        by_probe: dict[str, list[dict]] = {}
        for event in self.events:
            probe = event.get("probe")
            if probe:
                by_probe.setdefault(probe, []).append(event)
        for probe, probe_events in sorted(
            by_probe.items(), key=lambda item: -sum(event["seconds"] for event in item[1])
        ):
            digests = sorted({event.get("stdin_sha256", "?")[:12] for event in probe_events})
            write(
                f"  {sum(event['seconds'] for event in probe_events):9.2f}s"
                f"  n={len(probe_events):<4d} {probe}"
                f"  distinct stdin: {len(digests)} {','.join(digests)}"
            )
        write("-" * 78)
        write("scale counters (what grows with the repo)")
        for key, value in sorted(self.counters.items()):
            write(f"  {key}: {value}")
        write("=" * 78)
        return "\n".join(lines)


@functools.lru_cache(maxsize=1)
def _conform_repo_scale_cached() -> tuple[tuple[str, int], ...]:
    """Repo-size facts recorded alongside the timings, not inferred.

    Resolved before the wrappers are installed, so these children are never
    charged to the measured test.
    """
    root = Path(__file__).resolve().parents[2]
    scale: dict[str, int] = {}
    probes = {
        "tracked_files": ["git", "ls-files"],
        "tracked_files_runtime": ["git", "ls-files", "phase-loop-runtime"],
        "first_parent_commits_since_chronology_base": [
            "git",
            "rev-list",
            "--first-parent",
            "--count",
            "54b5eb703324a9da97d849fee9c107cbeebb0d25..HEAD",
        ],
    }
    for key, argv in probes.items():
        completed = subprocess.run(
            argv, cwd=root, capture_output=True, text=True, check=False
        )
        if completed.returncode != 0:
            continue
        scale[key] = (
            int(completed.stdout.strip())
            if key.startswith("first_parent")
            else len(completed.stdout.splitlines())
        )
    scale["test_files"] = len(list((root / "phase-loop-runtime" / "tests").glob("test_*.py")))
    return tuple(sorted(scale.items()))


# Installs nest: the falsifier suite installs while a flag-set session already
# has the wrappers bound. Only the OUTERMOST install rebinds a symbol and only
# the outermost restore puts it back, so a second layer can never wrap a wrapper
# and clobber the inner layer's attribution. The stack's last entry is the
# recorder a child started right now belongs to.
_CONFORM_RECORDER_STACK: list["_ConformTimingRecorder"] = []

# Restoration happens at the end of the CALL phase, but `monkeypatch` undoes in
# TEARDOWN. A test that patches one of the six wrapped symbols saves whatever is
# current -- the wrapper -- and reinstalls it after this hook has already put the
# real symbol back, resurrecting a wrapper with no recorder behind it. Two
# independent defences: every wrapper degrades to the real symbol when the stack
# is empty (so a resurrected wrapper is harmless and records nothing), and the
# teardown hook sweeps any wrapper it still finds bound (so it does not persist).
_CONFORM_RETIRED_BINDINGS: list[list[tuple[str, object, object, object, object]]] = []

# The values these symbols carry at conftest import, before any fixture has run.
# The sweep needs a predecessor it can SHOW is still valid. The value captured at
# install time is not that: an independent fixture may have installed its own
# replacement first, in which case `real` is that fixture's object and is stale
# the moment the fixture tears down. Restoring it then leaks an expired patch
# into every later test. The import-time value is the one the session started
# with and cannot expire, so the sweep restores that.
_CONFORM_PRISTINE: dict[str, object] = {
    "subprocess.Popen": subprocess.Popen,
    "shutil.copytree": shutil.copytree,
    "shutil.rmtree": shutil.rmtree,
    "tarfile.TarFile.extractall": tarfile.TarFile.extractall,
    "pathlib.Path.read_bytes": Path.read_bytes,
    "pathlib.Path.read_text": Path.read_text,
}


# Re-entrancy depth per SEAM, module-level so that two wrapper layers -- a
# surviving one and a freshly installed one -- coordinate through the same
# counter. The outermost layer for a seam records; any layer re-entered inside
# it passes straight through. Per-seam rather than global so that a read nested
# inside a copytree is still its own measurement, as it was before.
_CONFORM_SEAM_DEPTH: dict[str, int] = {}


class _conform_seam:
    """Own a seam for the duration of one call, or defer to the layer that does."""

    def __init__(self, seam: str) -> None:
        self.seam = seam
        self.owns = False

    def __enter__(self) -> "_conform_seam":
        self.owns = _CONFORM_SEAM_DEPTH.get(self.seam, 0) == 0
        _CONFORM_SEAM_DEPTH[self.seam] = _CONFORM_SEAM_DEPTH.get(self.seam, 0) + 1
        return self

    def __exit__(self, *exc_info) -> None:
        _CONFORM_SEAM_DEPTH[self.seam] -= 1


def _conform_current_recorder():
    """The recorder a seam belongs to right now, or None outside a measured call."""
    return _CONFORM_RECORDER_STACK[-1] if _CONFORM_RECORDER_STACK else None


def _conform_timing_sweep() -> None:
    """Unbind any wrapper a fixture teardown resurrected after `restore()`.

    It installs the IMPORT-TIME value, not the predecessor captured at install.
    For a FUNCTION-scoped fixture that is sound: its teardown has already run by
    the time this executes, so its predecessor has expired and putting it back
    would leak that fixture's object into every later test.

    What is NOT established (codex, rounds 6 and 7) -- stated as limits, because
    each was first written here as something stronger than the evidence:

    * "Every independent fixture predecessor has expired" is true per-function
      and NOT true for module/session scope -- in both directions. Such a
      predecessor MAY still be live, and it may equally have finalized already
      when this sweep follows the final test in its scope. This function applies
      the same restoration policy either way; what differs is whether the
      displaced predecessor was still valid.
    * A live predecessor is not erased -- `bindings` still holds it as `real` --
      so it is recoverable by a sweep that knows it is still live. This sweep
      keeps no fixture-lifetime information, so it cannot tell a live predecessor
      from an expired one and installs the import-time value rather than guess.
      That is a limit of THIS restoration policy, not an impossibility.
    * Displacing a live fixture patch is therefore possible here, and nothing in
      this function prevents it. The opt-in flag confines the exposure to runs
      that set it; that is all it does. There is NO record: this list is a work
      QUEUE, appended at install and `pop`ped here, and nothing logs or persists
      a retirement -- so a displacement would be silent. The residual is open.
    """
    while _CONFORM_RETIRED_BINDINGS:
        for name, get, set_value, wrapper, real in _CONFORM_RETIRED_BINDINGS.pop():
            if get() is wrapper:
                set_value(_CONFORM_PRISTINE.get(name, real))


def _conform_timing_install(recorder: "_ConformTimingRecorder"):
    """Wrap the measured seams; return a callable that restores every original.

    Nothing here runs unless the caller decided the flag is set, so with the flag
    unset no wrapper class exists and no symbol is rebound.
    """
    depth = len(_CONFORM_RECORDER_STACK)
    _CONFORM_RECORDER_STACK.append(recorder)
    if depth:
        # Already bound by an outer scope. Attribution follows the stack, so the
        # only thing this scope owns is its own entry.
        def restore_nested() -> None:
            del _CONFORM_RECORDER_STACK[depth:]

        return restore_nested

    real_popen = subprocess.Popen
    real_copytree = shutil.copytree
    real_rmtree = shutil.rmtree
    real_extractall = tarfile.TarFile.extractall
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text

    def probe_name(input_text: str) -> str | None:
        """Name a probe child by the payload it is fed on stdin.

        The mutation and EC probes are all spawned from the same two lines, so
        the command line alone cannot tell them apart; the stdin payload can.
        """
        if not input_text.startswith("{"):
            return None
        try:
            payload = json.loads(input_text)
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        for key in ("mutation_id", "id", "case_id", "nodeid"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        return None

    class _TimedPopen(real_popen):  # type: ignore[misc,valid-type]
        """Behaviour-identical Popen that records wall time and output size."""

        def __init__(self, args, *posargs, **kwargs):
            # Charge the child to the test that STARTED it, not to whichever
            # test happens to be running when it is awaited. Outside a measured
            # call -- a wrapper a fixture teardown resurrected -- the recorder is
            # None and this behaves exactly like the real Popen.
            #
            # `hasattr` guards the case where a resurrected wrapper sits in this
            # instance's MRO: the OUTER class assigns first, and the inner one
            # must not overwrite it on the way down to the real `__init__`.
            if not hasattr(self, "_conform_started"):
                self._conform_recorder = _conform_current_recorder()
                self._conform_started = time.perf_counter()
                self._conform_site = _ConformTimingRecorder.site()
                self._conform_label = _ConformTimingRecorder.command_label(args)
                self._conform_event = None
                self._conform_probe = None
                self._conform_stdin_sha256 = None
            super().__init__(args, *posargs, **kwargs)

        def _conform_record(self, out_size: int = 0, out_kind: str = "bytes") -> None:
            owner = self._conform_recorder
            if owner is None:
                return
            counter = (
                "child_output_chars" if out_kind == "chars" else "child_output_bytes"
            )
            if self._conform_event is not None:
                # `communicate` calls `wait` internally, so the event is created
                # before the output sizes are known, and a caller may call
                # `communicate` again -- a second call drains nothing and returns
                # empty. Output is monotonic: a later completion cannot unproduce
                # bytes, so only a HIGHER count moves the event, and it moves the
                # counter by the delta. Repeated completions add nothing twice
                # and cannot subtract what was already counted.
                if out_size > self._conform_event["out_size"]:
                    owner.bump(counter, out_size - self._conform_event["out_size"])
                    self._conform_event["out_size"] = out_size
                    self._conform_event["out_kind"] = out_kind
                return
            self._conform_event = owner.add(
                kind="process",
                label=self._conform_label,
                site=self._conform_site,
                seconds=time.perf_counter() - self._conform_started,
                out_size=out_size,
                out_kind=out_kind,
                probe=self._conform_probe,
                stdin_sha256=self._conform_stdin_sha256,
            )
            owner.bump("child_processes")
            owner.bump(f"child_processes::{self._conform_label}")
            if out_size:
                # `wait` completes before the sizes are known and reports 0; the
                # unit is only known once `communicate` returns, so do not create
                # a zero entry under the wrong one.
                owner.bump(counter, out_size)

        def communicate(self, *posargs, **kwargs):
            payload = None
            if posargs and isinstance(posargs[0], str):
                payload = posargs[0]
            elif isinstance(kwargs.get("input"), str):
                payload = kwargs["input"]
            if payload is not None and self._conform_stdin_sha256 is None:
                self._conform_stdin_sha256 = hashlib.sha256(
                    payload.encode("utf-8")
                ).hexdigest()
                self._conform_probe = probe_name(payload)
                if self._conform_event is not None:
                    self._conform_event["probe"] = self._conform_probe
                    self._conform_event["stdin_sha256"] = self._conform_stdin_sha256
            stdout, stderr = super().communicate(*posargs, **kwargs)
            # `len` on a text-mode stream counts CHARACTERS, not bytes. Count the
            # unit that was actually measured and say which it is, rather than
            # labelling characters as bytes.
            out_kind = "chars" if isinstance(stdout or stderr, str) else "bytes"
            self._conform_record(
                sum(len(part or ()) for part in (stdout, stderr)), out_kind
            )
            return stdout, stderr

        def wait(self, *posargs, **kwargs):
            returncode = super().wait(*posargs, **kwargs)
            self._conform_record()
            return returncode

    def timed_copytree(src, dst, *posargs, **kwargs):
        # `shutil._copytree` recurses by calling the module-global `copytree`, so
        # a nested directory re-enters the wrapper, and a surviving wrapper layer
        # would re-enter it too. Recording only the layer that owns the seam keeps
        # durations additive and stops `os.walk(dst)` recounting descendants.
        if _conform_current_recorder() is None:
            return real_copytree(src, dst, *posargs, **kwargs)
        started = time.perf_counter()
        site = _ConformTimingRecorder.site()
        with _conform_seam("shutil.copytree") as seam:
            result = real_copytree(src, dst, *posargs, **kwargs)
        if seam.owns:
            copied = sum(len(files) for _, _, files in os.walk(dst))
            current = _conform_current_recorder()
            current.add(
                kind="fs", label="shutil.copytree", site=site,
                seconds=time.perf_counter() - started, files=copied,
            )
            current.bump("copytree_calls")
            current.bump("copytree_files", copied)
        return result

    def timed_rmtree(path, *posargs, **kwargs):
        if _conform_current_recorder() is None:
            return real_rmtree(path, *posargs, **kwargs)
        started = time.perf_counter()
        site = _ConformTimingRecorder.site()
        with _conform_seam("shutil.rmtree") as seam:
            result = real_rmtree(path, *posargs, **kwargs)
        if not seam.owns:
            return result
        current = _conform_current_recorder()
        current.add(
            kind="fs", label="shutil.rmtree", site=site,
            seconds=time.perf_counter() - started,
        )
        current.bump("rmtree_calls")
        return result

    def timed_extractall(self, *posargs, **kwargs):
        if _conform_current_recorder() is None:
            return real_extractall(self, *posargs, **kwargs)
        started = time.perf_counter()
        site = _ConformTimingRecorder.site()
        with _conform_seam("tarfile.TarFile.extractall") as seam:
            result = real_extractall(self, *posargs, **kwargs)
        if not seam.owns:
            return result
        try:
            members = len(self.getmembers())
        except Exception:  # pragma: no cover - accounting must never fail a test
            members = -1
        current = _conform_current_recorder()
        current.add(
            kind="fs", label="tar.extractall", site=site,
            seconds=time.perf_counter() - started, members=members,
        )
        current.bump("tar_extractall_calls")
        if members > 0:
            current.bump("tar_members_extracted", members)
        return result

    def timed_read_bytes(self, *posargs, **kwargs):
        with _conform_seam("pathlib.Path.read_bytes") as seam:
            data = real_read_bytes(self, *posargs, **kwargs)
        current = _conform_current_recorder()
        if current is None or not seam.owns:
            return data
        current.bump("path_read_calls")
        current.bump("path_read_bytes", len(data))
        return data

    def timed_read_text(self, *posargs, **kwargs):
        with _conform_seam("pathlib.Path.read_text") as seam:
            data = real_read_text(self, *posargs, **kwargs)
        current = _conform_current_recorder()
        if current is None or not seam.owns:
            return data
        current.bump("path_read_calls")
        # `read_text` returns str, so `len` counts CHARACTERS. Recording those
        # under `path_read_bytes` conflated two units in one counter, which is
        # the same defect as the child-output one and one seam away from it.
        current.bump("path_read_chars", len(data))
        return data

    bindings = [
        (
            "subprocess.Popen",
            lambda: subprocess.Popen,
            lambda value: setattr(subprocess, "Popen", value),
            _TimedPopen,
            real_popen,
        ),
        (
            "shutil.copytree",
            lambda: shutil.copytree,
            lambda value: setattr(shutil, "copytree", value),
            timed_copytree,
            real_copytree,
        ),
        (
            "shutil.rmtree",
            lambda: shutil.rmtree,
            lambda value: setattr(shutil, "rmtree", value),
            timed_rmtree,
            real_rmtree,
        ),
        (
            "tarfile.TarFile.extractall",
            lambda: tarfile.TarFile.extractall,
            lambda value: setattr(tarfile.TarFile, "extractall", value),
            timed_extractall,
            real_extractall,
        ),
        (
            "pathlib.Path.read_bytes",
            lambda: Path.read_bytes,
            lambda value: setattr(Path, "read_bytes", value),
            timed_read_bytes,
            real_read_bytes,
        ),
        (
            "pathlib.Path.read_text",
            lambda: Path.read_text,
            lambda value: setattr(Path, "read_text", value),
            timed_read_text,
            real_read_text,
        ),
    ]
    for _name, _get, set_value, wrapper, _real in bindings:
        set_value(wrapper)

    def restore() -> None:
        del _CONFORM_RECORDER_STACK[depth:]
        for _name, get, set_value, wrapper, real in bindings:
            # Put back only what THIS scope displaced. A fixture that patched the
            # symbol during setup keeps its patch instead of being clobbered.
            if get() is wrapper:
                set_value(real)
        # Fixture teardown can still resurrect these; the teardown hook sweeps.
        _CONFORM_RETIRED_BINDINGS.append(bindings)

    return restore


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Emit one timing summary per test when PHASE_LOOP_CONFORM_TIMING=1."""
    if not _conform_timing_enabled():
        yield
        return
    _conform_repo_scale_cached()  # resolve before wrapping, never charged
    recorder = _ConformTimingRecorder(item.nodeid)
    restore = _conform_timing_install(recorder)
    try:
        yield
    finally:
        restore()
        total = time.perf_counter() - recorder.started
        recorder.reported = True
        if recorder.events or total >= 1.0:
            report = recorder.report(total)
            print(report, flush=True)
            print(report, file=sys.stderr, flush=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Sweep wrappers a fixture teardown resurrected after the call-phase restore.

    Deliberately NOT gated on the current flag. A test may delete
    PHASE_LOOP_CONFORM_TIMING after the call phase installed the wrappers; if the
    sweep re-read the flag it would skip, fixture undo would restore both the
    flag and the wrapper, and the next measured test would wrap a wrapper and
    count every read twice. The sweep is gated on what this session actually
    retired, which is the only state that can require cleaning up. With the flag
    never set there is nothing retired and this returns immediately.
    """
    try:
        yield
    finally:
        _conform_timing_sweep()


def pytest_sessionfinish(session, exitstatus):
    """Report children that completed after their own test's report printed."""
    if not _CONFORM_LATE_EVENTS:
        return
    lines = ["", "=" * 78, "CONFORM TIMING agent-harness#945 :: late completions"]
    for event in _CONFORM_LATE_EVENTS:
        lines.append(
            f"  {event['seconds']:8.2f}s  {event['label']:<22s}"
            f"  charged to {event['nodeid']}  {event['site']}"
        )
    lines.append("=" * 78)
    report = "\n".join(lines)
    print(report, flush=True)
    print(report, file=sys.stderr, flush=True)
