"""Shared pytest fixtures for the phase-loop-runtime test suite."""
from __future__ import annotations

import functools
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
# dominates the CI wall clock (47.5 min on the py3.10 lane, 66.2 min on Gate A)
# even though its source bytes are unchanged between v0.7.14 and v0.7.15. The
# block below attributes that wall clock to call sites and records the counters
# that could couple it to repo size (child processes, bytes hashed, tree copies,
# tar members extracted, files read).
#
# It is inert unless PHASE_LOOP_CONFORM_TIMING=1 is set in the *parent* pytest
# process. The mutation/EC probes build an explicit child environment, so the
# flag never reaches a nested pytest run and probe output bytes are unchanged.
# ---------------------------------------------------------------------------

_CONFORM_TIMING_ENV = "PHASE_LOOP_CONFORM_TIMING"


def _conform_timing_enabled() -> bool:
    return os.environ.get(_CONFORM_TIMING_ENV) == "1"


class _ConformTimingRecorder:
    """Wall-clock and scale accounting for one test, keyed by call site."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.counters: dict[str, int] = {}
        self.started = 0.0
        self.active = False

    # -- accounting ---------------------------------------------------------
    def bump(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def add(self, *, kind: str, label: str, site: str, seconds: float, **extra) -> None:
        self.events.append(
            {
                "kind": kind,
                "label": label,
                "site": site,
                "seconds": seconds,
                "offset": max(0.0, (time.perf_counter() - seconds) - self.started),
                **extra,
            }
        )

    # -- call-site attribution ---------------------------------------------
    @staticmethod
    def site() -> str:
        frame = sys._getframe(1)
        skip = (__file__, subprocess.__file__, shutil.__file__, tarfile.__file__)
        while frame is not None:
            filename = frame.f_code.co_filename
            if not any(filename == candidate for candidate in skip if candidate):
                name = os.path.basename(filename)
                return f"{name}:{frame.f_lineno} {frame.f_code.co_name}"
            frame = frame.f_back
        return "<unknown>"

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
    def report(self, nodeid: str, total: float) -> str:
        lines: list[str] = []
        write = lines.append
        write("")
        write("=" * 78)
        write(f"CONFORM TIMING agent-harness#945 :: {nodeid}")
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
        write("scale counters (what grows with the repo)")
        for key, value in sorted(self.counters.items()):
            write(f"  {key}: {value}")
        write("=" * 78)
        return "\n".join(lines)


_CONFORM_TIMING = _ConformTimingRecorder()


@functools.lru_cache(maxsize=1)
def _conform_repo_scale_cached() -> tuple[tuple[str, int], ...]:
    return tuple(sorted(_conform_repo_scale().items()))


def _conform_repo_scale() -> dict[str, int]:
    """Repo-size facts recorded alongside the timings, not inferred."""
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
        completed = _CONFORM_REAL_POPEN(
            argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        out, _ = completed.communicate()
        if completed.returncode != 0:
            continue
        scale[key] = int(out.strip()) if key.startswith("first_parent") else len(out.splitlines())
    scale["test_files"] = len(list((root / "phase-loop-runtime" / "tests").glob("test_*.py")))
    return scale


_CONFORM_REAL_POPEN = subprocess.Popen
_CONFORM_REAL_COPYTREE = shutil.copytree
_CONFORM_REAL_RMTREE = shutil.rmtree
_CONFORM_REAL_EXTRACTALL = tarfile.TarFile.extractall
_CONFORM_REAL_READ_BYTES = Path.read_bytes
_CONFORM_REAL_READ_TEXT = Path.read_text


class _TimedPopen(_CONFORM_REAL_POPEN):  # type: ignore[misc,valid-type]
    """Behaviour-identical Popen that records wall time and output size."""

    def __init__(self, args, *posargs, **kwargs):
        self._conform_started = time.perf_counter()
        self._conform_site = _ConformTimingRecorder.site()
        self._conform_label = _ConformTimingRecorder.command_label(args)
        self._conform_recorded = False
        super().__init__(args, *posargs, **kwargs)

    def _conform_record(self, out_bytes: int = 0) -> None:
        if self._conform_recorded or not _CONFORM_TIMING.active:
            return
        self._conform_recorded = True
        _CONFORM_TIMING.add(
            kind="process",
            label=self._conform_label,
            site=self._conform_site,
            seconds=time.perf_counter() - self._conform_started,
            out_bytes=out_bytes,
        )
        _CONFORM_TIMING.bump("child_processes")
        _CONFORM_TIMING.bump(f"child_processes::{self._conform_label}")
        _CONFORM_TIMING.bump("child_output_bytes", out_bytes)

    def communicate(self, *posargs, **kwargs):
        stdout, stderr = super().communicate(*posargs, **kwargs)
        self._conform_record(sum(len(part or ()) for part in (stdout, stderr)))
        return stdout, stderr

    def wait(self, *posargs, **kwargs):
        returncode = super().wait(*posargs, **kwargs)
        self._conform_record()
        return returncode


def _timed_copytree(src, dst, *posargs, **kwargs):
    started = time.perf_counter()
    site = _ConformTimingRecorder.site()
    result = _CONFORM_REAL_COPYTREE(src, dst, *posargs, **kwargs)
    if _CONFORM_TIMING.active:
        copied = sum(len(files) for _, _, files in os.walk(dst))
        _CONFORM_TIMING.add(
            kind="fs", label="shutil.copytree", site=site,
            seconds=time.perf_counter() - started, files=copied,
        )
        _CONFORM_TIMING.bump("copytree_calls")
        _CONFORM_TIMING.bump("copytree_files", copied)
    return result


def _timed_rmtree(path, *posargs, **kwargs):
    started = time.perf_counter()
    site = _ConformTimingRecorder.site()
    result = _CONFORM_REAL_RMTREE(path, *posargs, **kwargs)
    if _CONFORM_TIMING.active:
        _CONFORM_TIMING.add(
            kind="fs", label="shutil.rmtree", site=site,
            seconds=time.perf_counter() - started,
        )
        _CONFORM_TIMING.bump("rmtree_calls")
    return result


def _timed_extractall(self, *posargs, **kwargs):
    started = time.perf_counter()
    site = _ConformTimingRecorder.site()
    result = _CONFORM_REAL_EXTRACTALL(self, *posargs, **kwargs)
    if _CONFORM_TIMING.active:
        try:
            members = len(self.getmembers())
        except Exception:  # pragma: no cover - accounting must never fail a test
            members = -1
        _CONFORM_TIMING.add(
            kind="fs", label="tar.extractall", site=site,
            seconds=time.perf_counter() - started, members=members,
        )
        _CONFORM_TIMING.bump("tar_extractall_calls")
        if members > 0:
            _CONFORM_TIMING.bump("tar_members_extracted", members)
    return result


def _timed_read_bytes(self, *posargs, **kwargs):
    data = _CONFORM_REAL_READ_BYTES(self, *posargs, **kwargs)
    if _CONFORM_TIMING.active:
        _CONFORM_TIMING.bump("path_read_calls")
        _CONFORM_TIMING.bump("path_read_bytes", len(data))
    return data


def _timed_read_text(self, *posargs, **kwargs):
    data = _CONFORM_REAL_READ_TEXT(self, *posargs, **kwargs)
    if _CONFORM_TIMING.active:
        _CONFORM_TIMING.bump("path_read_calls")
        _CONFORM_TIMING.bump("path_read_bytes", len(data))
    return data


if _conform_timing_enabled():
    subprocess.Popen = _TimedPopen  # type: ignore[assignment]
    shutil.copytree = _timed_copytree  # type: ignore[assignment]
    shutil.rmtree = _timed_rmtree  # type: ignore[assignment]
    tarfile.TarFile.extractall = _timed_extractall  # type: ignore[assignment]
    Path.read_bytes = _timed_read_bytes  # type: ignore[assignment]
    Path.read_text = _timed_read_text  # type: ignore[assignment]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Emit one timing summary per test when PHASE_LOOP_CONFORM_TIMING=1."""
    if not _conform_timing_enabled():
        yield
        return
    _CONFORM_TIMING.events.clear()
    _CONFORM_TIMING.counters.clear()
    _CONFORM_TIMING.started = time.perf_counter()
    _CONFORM_TIMING.active = True
    try:
        yield
    finally:
        total = time.perf_counter() - _CONFORM_TIMING.started
        _CONFORM_TIMING.active = False
        if not _CONFORM_TIMING.events and total < 1.0:
            return
        report = _CONFORM_TIMING.report(item.nodeid, total)
        print(report, flush=True)
        print(report, file=sys.stderr, flush=True)
