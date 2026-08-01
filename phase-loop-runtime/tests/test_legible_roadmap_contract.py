"""LEGIBLE-A0 — frozen test-first falsifier suite (SL-0/SL-1 half).

See ``plans/phase-plan-v10-LEGIBLE.md`` for the ratified contract this file
implements. This module owns 64 of the phase's 84 frozen nodeids: 27
status/banner/selection cases, 23 independently identified assumption-probe
cases, 12 manifest scope/registration/malformed-path cases, and 2 catalog
cases. Its sibling ``test_legible_evidence.py`` owns the remaining 20
(chronology, PR/ancestry, fresh-process/sidecar, activation/JUnit/digest).

Every nodeid here is guarded by ONE shared, test-owned activation rule (the
module-level ``skipif`` below is the only skip mechanism for these nodeids):
``forced = os.environ.get("PHASE_LOOP_TDD_EXPECT_LEGIBLE") == "1"`` or the
installed ``phase_loop_runtime.legible_evidence`` module reports
``LEGIBLE_CAPABILITY_VERSION == "legible.v1"``.

Before LEGIBLE-A1 lands, every one of these nodeids fails through its own
named ``LEGIBLE_RED::<mutation-id>`` assertion: each test first reaches and
asserts a real "source injection anchor" (a literal, presently-true fact read
from this repository's own committed bytes — the v10 roadmap, the tracked
banner files, `plans/manifest.json`, `.claude/docs-catalog.json`, or real Git
history), proving the test is grounded against live content and not a stub.
Only after that anchor assertion succeeds does the test attempt the
LEGIBLE-owned public surface (``phase_loop_runtime.roadmap_lint``,
``phase_loop_runtime.roadmap_assumptions``, ``phase_loop_runtime.discovery``,
``phase_loop_runtime.plan_manifest``, ``phase_loop_runtime.docs_freshness``),
which does not exist yet — the resulting ``ImportError``/``AttributeError``/
``SystemExit`` is converted into the tagged, intentional failure. No test
here relies on collection/import failure, ``xfail``, or a deselected node as
a substitute for that tagged assertion.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from phase_loop_runtime.discovery import repo_identity, select_roadmap
from phase_loop_runtime.plan_manifest import DotfilesPlanEntry, DotfilesPlanRef, append_entry
from phase_loop_runtime.state import write_state

from phase_loop_test_utils import provenanced_state


# ---------------------------------------------------------------------------
# Shared activation rule (identical, by contract, in test_legible_evidence.py)

LEGIBLE_TDD_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_LEGIBLE"
LEGIBLE_CAPABILITY_MODULE = "phase_loop_runtime.legible_evidence"
LEGIBLE_CAPABILITY_VERSION = "legible.v1"


def _legible_capability_active() -> bool:
    if os.environ.get(LEGIBLE_TDD_ACTIVATION_ENV) == "1":
        return True
    spec = importlib.util.find_spec(LEGIBLE_CAPABILITY_MODULE)
    if spec is None:
        return False
    module = importlib.import_module(LEGIBLE_CAPABILITY_MODULE)
    return getattr(module, "LEGIBLE_CAPABILITY_VERSION", None) == LEGIBLE_CAPABILITY_VERSION


pytestmark = pytest.mark.skipif(
    not _legible_capability_active(),
    reason="LEGIBLE capability absent (set PHASE_LOOP_TDD_EXPECT_LEGIBLE=1, or install "
    "phase_loop_runtime.legible_evidence with LEGIBLE_CAPABILITY_VERSION == 'legible.v1')",
)


def _red(mutation_id: str, detail: str) -> None:
    """Convert the absence of a not-yet-implemented LEGIBLE surface into the one
    intended, tagged failure every forced-RED nodeid must reach."""
    pytest.fail(f"LEGIBLE_RED::{mutation_id}: {detail}", pytrace=False)


def _new_symbol(module_name: str, symbol: str):
    """Resolve ``module_name.symbol``, raising the exact typed error a caller sees
    today (``ImportError`` for a wholly missing module, ``AttributeError`` for a
    missing attribute on an existing one) so callers can tag it precisely."""
    module = importlib.import_module(module_name)
    if not hasattr(module, symbol):
        raise AttributeError(f"{module_name}.{symbol} is not implemented yet")
    return getattr(module, symbol)


# ---------------------------------------------------------------------------
# Repository-grounded anchors

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP_PATH = REPO_ROOT / "specs" / "phase-plans-v10.md"
PLAN_PATH = REPO_ROOT / "plans" / "phase-plan-v10-LEGIBLE.md"
MANIFEST_PATH = REPO_ROOT / "plans" / "manifest.json"
CATALOG_PATH = REPO_ROOT / ".claude" / "docs-catalog.json"

# The closed 1/5/7 status mapping over the live thirteen tracked roadmaps
# (plans/phase-plan-v10-LEGIBLE.md, "The closed status mapping is").
TRACKED_ROADMAP_STATUS: dict[str, str] = {
    "specs/phase-plans-v10.md": "active",
    "specs/phase-plans-cross-repo-v1.md": "delivered",
    "specs/phase-plans-v1-task-message-sourcebroker.md": "delivered",
    "specs/phase-plans-v1.md": "delivered",
    "specs/phase-plans-v6.md": "delivered",
    "specs/phase-plans-v8.md": "delivered",
    "specs/phase-plans-convergence-v1.md": "superseded",
    "specs/phase-plans-v2.md": "superseded",
    "specs/phase-plans-v3.md": "superseded",
    "specs/phase-plans-v4.md": "superseded",
    "specs/phase-plans-v5.md": "superseded",
    "specs/phase-plans-v7.md": "superseded",
    "specs/phase-plans-v9.md": "superseded",
}

# The exact accepted line-3 grammar per status, as it is committed TODAY (verified
# byte-for-byte against every tracked file below at collection time — this table IS
# the "positive control [that] all thirteen bytes parse" the plan describes).
BANNER_LINE3: dict[str, str] = {
    "specs/phase-plans-v10.md": "> **Status (2026-07-29): ACTIVE — created this date, nothing executed yet.**",
    "specs/phase-plans-cross-repo-v1.md": "> # DELIVERED — CLOSED (assessed 2026-07-29)",
    "specs/phase-plans-v1-task-message-sourcebroker.md": "> # DELIVERED — CLOSED (assessed 2026-07-29)",
    "specs/phase-plans-v1.md": "> # DELIVERED — CLOSED (assessed 2026-07-29)",
    "specs/phase-plans-v6.md": "> # DELIVERED — CLOSED (assessed 2026-07-29)",
    "specs/phase-plans-v8.md": "> # DELIVERED — CLOSED (assessed 2026-07-29)",
    "specs/phase-plans-convergence-v1.md": "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)",
    "specs/phase-plans-v2.md": "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)",
    "specs/phase-plans-v3.md": "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)",
    "specs/phase-plans-v4.md": "> # SUPERSEDED — ABSORBED into `specs/phase-plans-v10.md` (assessed 2026-07-29; corrected after CR)",
    "specs/phase-plans-v5.md": "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)",
    "specs/phase-plans-v7.md": "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)",
    "specs/phase-plans-v9.md": "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)",
}

assert set(TRACKED_ROADMAP_STATUS) == set(BANNER_LINE3)


def _canonical_repo_ready() -> bool:
    """True in a normal repository checkout (this file's own dev/CI tree, or any
    other clone carrying its full ``.git`` history, ``specs/``, and ``plans/``);
    False in an installed-wheel clean-room copy like Gate A's ``tests/``-only
    standalone tree, which has none of those."""
    return (
        (REPO_ROOT / ".git").exists()
        and ROADMAP_PATH.is_file()
        and PLAN_PATH.is_file()
    )


# Frozen, verbatim excerpts of every ratified ``specs/phase-plans-v10.md`` and
# ``plans/phase-plan-v10-LEGIBLE.md`` passage this file's source injection
# anchors cite (captured at LEGIBLE-A0 authoring time). A canonical repository
# checkout never touches these constants -- ``ROADMAP_PATH``/``PLAN_PATH`` are
# read lazily below and always win when present on disk. They exist purely so
# an installed-wheel clean-room tree (e.g. Gate A's ``tests/``-only standalone
# copy, which ships no ``specs/`` or ``plans/`` directory at all) can still
# assert every anchor byte-for-byte against a real ratified quote instead of
# crashing at import time or silently skipping the check.
_FROZEN_PLAN_EXCERPT = """\

- [ ] IF-0-LEGIBLE-1 — `specs/roadmap-status.json` is the single repo-owned `roadmap_status_manifest.v1` registry, but never the sole unchecked status authority. It contains exactly `schema`, `selected_roadmap`, and `roadmaps`; `roadmaps` is a stable path-sorted array whose records contain exactly `path` and `status`. In the canonical repository it covers exactly the Git-tracked `specs/phase-plans-*.md` path set once, classifies the live thirteen paths as one `active`, five `delivered`, and seven `superseded`, and sets `selected_roadmap` to the sole active record, `specs/phase-plans-v10.md`. `phase_loop_runtime.roadmap_lint` exposes `RoadmapStatus`, `parse_roadmap_status_manifest(text)`, `parse_roadmap_banner_status(text, path)`, `validate_roadmap_status_coherence(repo, required)`, `read_roadmap_status(repo, path)`, and `declared_active_roadmap(repo)`. The typed `RoadmapStatusError` hierarchy distinguishes malformed registry, malformed/ambiguous/missing banner signal, registry/banner coherence drift, and attempted selection of a recognized non-active roadmap. When the registry is present, status reads first validate exact tracked-path coverage and parse every tracked roadmap's working-tree bytes; every path's registry value must equal its parsed primary-banner value before any value is returned. Canonical repository `validate-roadmap` calls the same coherence validator with `required=True`. A present registry with a missing/extra/duplicate/noncanonical path, path escape, malformed/unknown status, selected/active mismatch, unparseable banner, or sidecar/banner drift is a typed failure. For a synthetic or legacy fixture repo with `specs/roadmap-status.json` wholly absent, `read_roadmap_status` returns `None`; the common selector return gate still reads the candidate bytes and rejects every recognized `delivered` or `superseded` lifecycle declaration. Legacy selection compatibility applies only when the candidate has no lifecycle declaration at all. A malformed, ambiguous, misplaced, or status-like lifecycle declaration is not "legacy" and fails typed. A single `_return_selectable_roadmap(repo, candidate, source)` gate wraps every `select_roadmap` return: it always parses candidate lifecycle bytes, rejects every recognized non-active declaration, and, when the registry exists, additionally invokes the full coherence validator and requires the candidate to be the registered and banner-declared `active` path. The gate covers explicit, authority, state, manifest, handoff, singleton-glob, manifest-disabled, and `PHASE_LOOP_DISCOVERY_ALLOW_COMPLETED=1`/completed-hatch paths; neither registry absence, manifest disablement, nor the completed hatch bypasses a recognized lifecycle declaration. Manifest reporting consumes the same coherence-checked accessor.
- [ ] IF-0-LEGIBLE-2 — `verification_evidence.v3` is the generic LEGIBLE-owned envelope and reader/writer contract. Its version-relative top-level inventories preserve both valid v2 shapes, its v3 `extensions` object is checked against a closed namespace/schema registry, its `log_sha256` authenticates the complete final resealed log rather than an intermediate v2 log, and its initial required namespace is exactly `phase_loop_runtime.legible_evidence`. The generic registry/reader accepts later registered namespaces without making them required for a LEGIBLE-only producer; PROOFGATE owns only the downstream `phase_loop_runtime.proofgate_evidence` record and may not redefine the generic envelope, seal, or reader contract.


`test_legacy_repo_without_roadmap_status_registry_preserves_selection` reruns the pre-LEGIBLE
synthetic/legacy selector fixtures with the registry path wholly absent and roadmaps carrying no
lifecycle declaration, and asserts byte-for-byte equivalent selected paths or legacy exceptions.
A second control creates the registry path with empty, partial, or malformed bytes and requires a
typed failure, proving the compatibility branch is absence-only rather than an error-swallowing
fallback. Canonical-repository validation and `declared_active_roadmap` each have an independent
missing-registry negative control.

  one stable path-sorted record for every tracked roadmap containing the registry status, parsed
  banner status, exact primary-declaration line number, and declaration SHA-256. Collection and
  `verify --head HEAD` both call `validate_roadmap_status_coherence(required=True)`; mismatched

- [ ] EC-LEGIBLE-1 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`, `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k "roadmap_status or banner_status" -q`, and the verifier-bound `roadmap_status` record showing exact tracked-path coverage plus registry/banner agreement
- [ ] EC-LEGIBLE-2 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k declared_active_roadmap -q` requiring the on-disk selected path to equal the sole registry/banner-active roadmap
- [ ] EC-LEGIBLE-3 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .` reporting computed `canonical=N registered=N unregistered=0` with exact HEAD/index/direct-filesystem union equality (and `canonical=28 registered=28 unregistered=0` when the clean scope contains all six root plans), plus `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k manifest -q`, including the untracked in-scope absent-manifest and index-only absent-manifest nonzero/name/origin falsifiers and malformed/symlink/path-escape controls
"""

_FROZEN_ROADMAP_EXCERPT = """\
   **STALE — invalidated 2026-07-29 by this repo's own merges while v10 was in review** (a new
   class: a fail-loud assumption that went wrong WITHOUT failing loud). `spec#102` MERGED
   (2026-07-29), the ratification-review gate `spec#118` is CLOSED, and `agent-harness#377` landed
   the `v0.2.1` pin on `main` — `outside_agent_pin.py` now records `contract_git_tag="v0.2.1"`,
   `contract_git_sha="b862f977…"` (superseding `c1085483`) plus per-schema `submission_schema_sha256`
   / `verdict_schema_sha256`. CONFORM's pin work is therefore NO LONGER externally gated and is
   satisfiable against merged sources; EC-CONFORM-5/6/7 are re-derived accordingly below. (Swept
   the other four assumptions against current `main`: #2 re-verified LIVE — `governed-pipeline#128`
   still OPEN, we still ship `0.7.13`; #3 holds — `tui_adapter_required` still present in

   stale.)
2. `governed-pipeline` continues to pin agent-harness 0.5.0 while we ship 0.7.13 until it acts on
   `governed-pipeline#128`. No phase here depends on that being resolved.
3. The claude/fable board seat is structurally unavailable when the runtime drives the board from

   runtime-internal 3-of-4 result remains evidence of a degraded board but does not satisfy this
   run's stricter panel gate. REVIEWTRUTH resolves the runtime gap
   in two parts: EC-REVIEWTRUTH-4 TYPES the vacancy (a natively-fillable seat is no longer silently
   dropped) and EC-REVIEWTRUTH-14 FILLS it natively under Claude Code with no TUI adapter
   (`agent-harness#396`), after which the runtime-driven board reaches full seat count.
4. `plans/manifest.json` is load-bearing for roadmap discovery; a malformed entry has previously
   disabled discovery entirely (fixed per-entry in `agent-harness#170`).
5. The ratified agent-harness#363 decision stands: all admission kinds draw from ONE shared monotonic epoch
   allocator, and publish byte-neutrality is RETRACTED.

"""


@functools.lru_cache(maxsize=None)
def _roadmap_text() -> str:
    """Lazily resolve the roadmap text this module's anchors are checked
    against. Deferred to first *use* (never called at import/collection time)
    so the module can import even when ``ROADMAP_PATH`` does not exist."""
    try:
        return ROADMAP_PATH.read_text(encoding="utf-8")
    except OSError:
        return _FROZEN_ROADMAP_EXCERPT


@functools.lru_cache(maxsize=None)
def _plan_text() -> str:
    """Lazily resolve the plan text this module's anchors are checked against.
    Deferred to first *use* (never called at import/collection time) so the
    module can import even when ``PLAN_PATH`` does not exist."""
    try:
        return PLAN_PATH.read_text(encoding="utf-8")
    except OSError:
        return _FROZEN_PLAN_EXCERPT


def _assert_real_banner_anchor(rel_path: str) -> str:
    """Injection anchor: when canonical repository bytes are available, the
    real, currently-committed banner line 3 for ``rel_path`` must equal the
    frozen grammar this suite pins -- failing loud (not silently) if the live
    repository ever drifts from the frozen mapping. In an installed-wheel
    clean-room tree there is no live ``specs/`` directory to compare against,
    so this drift check is inapplicable and the already-frozen ``BANNER_LINE3``
    literal is returned directly -- it IS the frozen fixture, not merely an
    anchor into a file that does not exist there."""
    if not _canonical_repo_ready():
        return BANNER_LINE3[rel_path]
    real_text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    lines = real_text.splitlines()
    assert len(lines) >= 3, f"{rel_path}: fewer than 3 lines, cannot carry a banner"
    assert lines[0].startswith("# ") and lines[0].strip() != "#", f"{rel_path}: missing H1 title"
    assert lines[1] == "", f"{rel_path}: line 2 must be blank"
    expected = BANNER_LINE3[rel_path]
    assert lines[2] == expected, f"{rel_path} line 3 drifted: {lines[2]!r} != {expected!r}"
    return expected


def _assert_roadmap_contains(anchor: str) -> None:
    text = _roadmap_text()
    assert anchor in text, (
        f"source injection anchor missing from {ROADMAP_PATH} "
        f"(and from its frozen installed-wheel excerpt): {anchor!r}"
    )


def _assert_plan_contains(anchor: str) -> None:
    text = _plan_text()
    assert anchor in text, (
        f"source injection anchor missing from {PLAN_PATH} "
        f"(and from its frozen installed-wheel excerpt): {anchor!r}"
    )


# ---------------------------------------------------------------------------
# Fixture helpers (self-contained temp Git repos — the real repository is
# read-only in every test below)

def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "legible-red@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Legible Red"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    (repo / "specs").mkdir()
    (repo / "plans").mkdir()
    (repo / "README.md").write_text("legible-red fixture\n", encoding="utf-8")
    _commit_all(repo, "init")
    return repo


def _commit_all(repo: Path, message: str = "fixture") -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, stdout=subprocess.DEVNULL
    )


def _write_banner_roadmap(repo: Path, rel_path: str, line3: str) -> Path:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Fixture {rel_path}\n\n{line3}\n\n## Body\n\ncontent\n", encoding="utf-8")
    return path


def _write_all_tracked_roadmaps(repo: Path, overrides: dict[str, str] | None = None) -> None:
    overrides = overrides or {}
    for rel_path, line3 in BANNER_LINE3.items():
        _write_banner_roadmap(repo, rel_path, overrides.get(rel_path, line3))


def _write_status_registry(
    repo: Path, statuses: dict[str, str], selected: str = "specs/phase-plans-v10.md"
) -> Path:
    registry = {
        "schema": "roadmap_status_manifest.v1",
        "selected_roadmap": selected,
        "roadmaps": [
            {"path": path, "status": status} for path, status in sorted(statuses.items())
        ],
    }
    path = repo / "specs" / "roadmap-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _add_phase_entry(repo: Path, version: str, alias: str, status: str, roadmap: Path) -> None:
    plan = repo / "plans" / f"phase-plan-{version}-{alias}.md"
    plan.write_text(f"---\nphase: {alias}\nroadmap: {roadmap.relative_to(repo)}\n---\n# {alias}\n")
    append_entry(
        repo,
        DotfilesPlanEntry(
            slug=f"{version}-{alias}",
            file=f"plans/phase-plan-{version}-{alias}.md",
            type="phase",
            status=status,
            created_at="2026-06-01T00:00:00Z",
            updated_at="2026-06-01T00:00:00Z",
            owner_skill="codex-plan-phase",
            roadmap_ref=DotfilesPlanRef(
                slug=f"phase-plans-{version}",
                file=str(roadmap.relative_to(repo)),
                type="phase",
                status=status,
            ),
            phase_alias=alias,
        ),
    )


def _write_no_declaration_roadmap(repo: Path, rel_path: str) -> Path:
    """A synthetic roadmap carrying NO lifecycle declaration at all — the only
    shape the plan's legacy-compatibility branch is allowed to keep selecting."""
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Legacy {rel_path}\n\n## Body\n\ncontent\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Selector-source fixtures (shared by every test that must exercise a REAL
# selector source rather than pass a bare label string)

SELECTOR_SOURCES: list[str] = [
    "explicit",
    "authority",
    "state",
    "manifest",
    "handoff",
    "singleton-glob",
    "manifest-disabled",
    "completed-hatch",
]

# ``select_roadmap`` consults its sources in one fixed priority order (explicit,
# authority, state, manifest, handoff, singleton-glob). Two of the eight parameter
# ids name a FLAG REGIME rather than a distinct source, so the label the common
# gate must see for them is the source that actually produced the return: the
# manifest-disabled fixture falls through to the state lever, and completed-hatch
# IS the manifest lever with its retired-entry filter opened.
GATE_SOURCE_LABEL: dict[str, str] = {
    "explicit": "explicit",
    "authority": "authority",
    "state": "state",
    "manifest": "manifest",
    "handoff": "handoff",
    "singleton-glob": "singleton-glob",
    "manifest-disabled": "state",
    "completed-hatch": "manifest",
}


class _SourceFixture(NamedTuple):
    """A synthetic repo in which exactly one selector source resolves to ``target``.

    ``reach_source`` reaches ``target`` through that source's own helper (proving the
    source, not the selector, was exercised); ``select`` reaches it through the public
    ``select_roadmap`` entry point; ``gate_source`` is the label the common gate is
    expected to be called with when ``select`` returns."""

    repo: Path
    target: Path
    reach_source: Callable[[], Path | None]
    select: Callable[[], Path]
    gate_source: str


def _build_source_fixture(
    base: Path,
    source: str,
    monkeypatch,
    line3: str,
    *,
    home: Path,
    rel_path: str = "specs/phase-plans-v7.md",
) -> _SourceFixture:
    """Build a self-contained repo wired so that ``source`` (and only ``source``)
    resolves to ``rel_path``. ``line3`` is the lifecycle declaration the target
    carries; the empty string means NO declaration at all. Everything here is
    synthetic — no production behavior is patched or bypassed."""
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("PHASE_LOOP_MANIFEST_DISABLED", raising=False)
    monkeypatch.delenv("PHASE_LOOP_DISCOVERY_ALLOW_COMPLETED", raising=False)
    repo = _init_repo(base)
    target = (
        _write_banner_roadmap(repo, rel_path, line3)
        if line3
        else _write_no_declaration_roadmap(repo, rel_path)
    )
    select = functools.partial(select_roadmap, repo, None)

    if source == "explicit":
        _commit_all(repo)
        select = functools.partial(select_roadmap, repo, str(target.relative_to(repo)))
        reach_source = select

    elif source == "authority":
        import hashlib

        from phase_loop_runtime.roadmap_authority import (
            LATCH_MARKER,
            REQUIRED_MARKER,
            active_authorized_roadmap,
            roadmap_authority_file,
            roadmap_authority_latch_file,
            roadmap_authority_required_file,
            roadmap_authority_worktree_latch_file,
        )

        _commit_all(repo)
        authority_path = roadmap_authority_file(repo)
        authority_path.parent.mkdir(parents=True, exist_ok=True)
        authority_path.write_text(
            json.dumps(
                {
                    "schema": "phase_loop_roadmap_authority.v1",
                    "status": "active",
                    "active_roadmap": rel_path,
                    "active_roadmap_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "retired_roadmaps": [],
                }
            ),
            encoding="utf-8",
        )
        os.chmod(authority_path, 0o600)
        for marker_path, content in (
            (roadmap_authority_worktree_latch_file(repo), LATCH_MARKER),
            (roadmap_authority_required_file(repo), REQUIRED_MARKER),
            (roadmap_authority_latch_file(repo), LATCH_MARKER),
        ):
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(content, encoding="utf-8")
            os.chmod(marker_path, 0o400)
        reach_source = functools.partial(active_authorized_roadmap, repo)

    elif source in ("state", "manifest-disabled"):
        from phase_loop_runtime.discovery import active_state_roadmap, manifest_backed_roadmap

        _commit_all(repo)
        write_state(repo, provenanced_state(repo, target, {"BODY": "planned"}))
        if source == "manifest-disabled":
            monkeypatch.setenv("PHASE_LOOP_MANIFEST_DISABLED", "1")
            assert manifest_backed_roadmap(repo) is None, "manifest-disabled flag had no effect"
        reach_source = functools.partial(active_state_roadmap, repo)

    elif source == "manifest":
        from phase_loop_runtime.discovery import manifest_backed_roadmap

        _add_phase_entry(repo, "v7", "BODY", "executing", target)
        _commit_all(repo)
        reach_source = functools.partial(manifest_backed_roadmap, repo)

    elif source == "completed-hatch":
        from phase_loop_runtime.discovery import manifest_backed_roadmap

        _add_phase_entry(repo, "v7", "BODY", "completed", target)
        _commit_all(repo)
        assert manifest_backed_roadmap(repo) is None, "completed entries must be skipped by default"
        monkeypatch.setenv("PHASE_LOOP_DISCOVERY_ALLOW_COMPLETED", "1")
        reach_source = functools.partial(manifest_backed_roadmap, repo)

    elif source == "handoff":
        from phase_loop_runtime.discovery import latest_handoff_roadmap

        _commit_all(repo)
        # One shared fake HOME per test: handoff records are keyed by repo hash, so
        # sibling fixtures in the same test cannot see each other's handoff.
        monkeypatch.setenv("HOME", str(home))
        identity = repo_identity(repo)
        handoff_dir = (
            home
            / ".codex"
            / "skills"
            / "codex-phase-roadmap-builder"
            / "handoffs"
            / identity.repo_hash
            / identity.branch_slug
        )
        handoff_dir.mkdir(parents=True, exist_ok=True)
        (handoff_dir / "latest.md").write_text(
            "---\n"
            "from: codex-phase-roadmap-builder\n"
            f"repo: {identity.repo_hash}\n"
            f"repo_root: {identity.root}\n"
            f"branch_slug: {identity.branch_slug}\n"
            f"artifact: {target.resolve()}\n"
            "---\n# handoff\n",
            encoding="utf-8",
        )
        reach_source = functools.partial(
            latest_handoff_roadmap, identity, "codex-phase-roadmap-builder"
        )

    elif source == "singleton-glob":
        _commit_all(repo)
        reach_source = select

    else:  # pragma: no cover - exhaustive over SELECTOR_SOURCES
        raise AssertionError(source)

    return _SourceFixture(repo, target, reach_source, select, GATE_SOURCE_LABEL[source])


# ===========================================================================
# Group 1 — status/banner/selection (27 nodeids)
# ===========================================================================


def test_status_coherence_rejects_active_registry_with_superseded_do_not_execute_banner(tmp_path):
    _assert_real_banner_anchor("specs/phase-plans-v10.md")
    repo = _init_repo(tmp_path)
    _write_all_tracked_roadmaps(
        repo,
        overrides={
            "specs/phase-plans-v10.md": BANNER_LINE3["specs/phase-plans-v7.md"],
        },
    )
    _write_status_registry(repo, TRACKED_ROADMAP_STATUS, selected="specs/phase-plans-v10.md")
    _commit_all(repo)
    try:
        validate = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("status-coherence-active-superseded-banner", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, required=True)


def test_status_coherence_rejects_superseded_registry_with_active_banner(tmp_path):
    _assert_real_banner_anchor("specs/phase-plans-v7.md")
    repo = _init_repo(tmp_path)
    _write_all_tracked_roadmaps(
        repo,
        overrides={
            "specs/phase-plans-v7.md": BANNER_LINE3["specs/phase-plans-v10.md"],
        },
    )
    _write_status_registry(repo, TRACKED_ROADMAP_STATUS, selected="specs/phase-plans-v10.md")
    _commit_all(repo)
    try:
        validate = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("status-coherence-superseded-active-banner", str(exc))
        return
    with pytest.raises(error_cls):
        validate(repo, required=True)


def test_status_coherence_rejects_delivered_and_checkbox_drift(tmp_path):
    delivered = [path for path, status in TRACKED_ROADMAP_STATUS.items() if status == "delivered"]
    assert len(delivered) == 5
    for path in delivered:
        _assert_real_banner_anchor(path)
    try:
        validate = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("status-coherence-delivered-checkbox-drift", str(exc))
        return
    for target in delivered:
        for mutated_status in ("active", "superseded"):
            repo = _init_repo(Path(tmp_path) / f"drift-{Path(target).stem}-{mutated_status}")
            statuses = dict(TRACKED_ROADMAP_STATUS)
            statuses[target] = mutated_status
            _write_all_tracked_roadmaps(repo)
            _write_status_registry(repo, statuses)
            _commit_all(repo)
            with pytest.raises(error_cls):
                validate(repo, required=True)
        # Flipping every checkbox in the delivered body must NOT change its status.
        repo = _init_repo(Path(tmp_path) / f"checkbox-{Path(target).stem}")
        _write_all_tracked_roadmaps(repo)
        checked = repo / target
        checked.write_text(
            checked.read_text(encoding="utf-8") + "\n- [x] historically checked item\n",
            encoding="utf-8",
        )
        _write_status_registry(repo, TRACKED_ROADMAP_STATUS)
        _commit_all(repo)
        validate(repo, required=True)  # unreachable pre-implementation; would assert no raise


def test_status_coherence_rejects_missing_malformed_ambiguous_or_misplaced_banner(tmp_path):
    _assert_plan_contains("primary-declaration line number, and declaration SHA-256")
    try:
        parse = _new_symbol("phase_loop_runtime.roadmap_lint", "parse_roadmap_banner_status")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("banner-missing-malformed-ambiguous-misplaced", str(exc))
        return
    base_line3 = BANNER_LINE3["specs/phase-plans-v10.md"]
    mutations = {
        "missing": "\n\n# no declaration at all\n",
        "malformed": "> **Status (not-a-date): ACTIVE — created this date, nothing executed yet.**\n",
        "ambiguous": f"{base_line3}\n{base_line3}\n",
        "misplaced": f"\n{base_line3}\n",
    }
    for kind, body in mutations.items():
        text = f"# Title\n\n{body}\n## Body\n"
        with pytest.raises(error_cls):
            parse(text, "specs/phase-plans-v10.md")


def test_status_registry_exactly_covers_tracked_roadmaps(tmp_path):
    assert len(TRACKED_ROADMAP_STATUS) == 13
    if _canonical_repo_ready():
        for path in TRACKED_ROADMAP_STATUS:
            assert (REPO_ROOT / path).is_file(), f"tracked roadmap missing from live repo: {path}"
    try:
        validate = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("status-registry-exact-coverage", str(exc))
        return
    for mode, statuses in (
        ("missing", {p: s for p, s in TRACKED_ROADMAP_STATUS.items() if p != "specs/phase-plans-v9.md"}),
        ("extra", {**TRACKED_ROADMAP_STATUS, "specs/phase-plans-v999-EXTRA.md": "superseded"}),
        ("duplicate", TRACKED_ROADMAP_STATUS),
    ):
        repo = _init_repo(Path(tmp_path) / mode)
        _write_all_tracked_roadmaps(repo)
        registry_path = _write_status_registry(repo, statuses)
        if mode == "duplicate":
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            data["roadmaps"].append(dict(data["roadmaps"][0]))
            registry_path.write_text(json.dumps(data), encoding="utf-8")
        _commit_all(repo)
        with pytest.raises(error_cls):
            validate(repo, required=True)


def test_status_positive_controls_kill_hardwired_active_or_none(tmp_path):
    _assert_plan_contains("selected_roadmap` to the sole active record")
    try:
        parse = _new_symbol("phase_loop_runtime.roadmap_lint", "parse_roadmap_banner_status")
        declared_active = _new_symbol("phase_loop_runtime.roadmap_lint", "declared_active_roadmap")
    except (ImportError, AttributeError) as exc:
        _red("positive-control-hardwired-active-or-none", str(exc))
        return
    if _canonical_repo_ready():
        repo = REPO_ROOT
        active_path = ROADMAP_PATH
    else:
        # Installed-wheel clean room: no canonical specs/ tree to read, so
        # exercise the identical public contract against a synthetic repo
        # built from the same frozen BANNER_LINE3/TRACKED_ROADMAP_STATUS
        # fixtures every selector-fail-closed test below already relies on.
        repo = _init_repo(tmp_path)
        _write_all_tracked_roadmaps(repo)
        _write_status_registry(repo, TRACKED_ROADMAP_STATUS)
        _commit_all(repo)
        active_path = repo / "specs" / "phase-plans-v10.md"
    for path, status in TRACKED_ROADMAP_STATUS.items():
        parsed = parse((repo / path).read_text(encoding="utf-8"), path)
        assert parsed == status, f"a hardwired-'active' parser would fail on {path}"
    assert declared_active(repo) == active_path.resolve(), (
        "an always-None selector must fail this exact-v10 positive control"
    )


@pytest.mark.parametrize(
    "source",
    [
        "explicit",
        "authority",
        "state",
        "manifest",
        "handoff",
        "singleton-glob",
        "manifest-disabled",
        "completed-hatch",
    ],
)
def test_superseded_selector_paths_fail_closed(tmp_path, monkeypatch, source):
    """Every one of the eight selector sources must fail closed on a superseded
    roadmap, must still select an ACTIVE one, and must reach that verdict through
    the ONE common gate rather than a gate defined but never wired in.

    Note what is deliberately NOT asserted: that ``select_roadmap`` returns the
    superseded fixture. Freezing that return as a precondition would pin the exact
    behavior this phase exists to remove. Each source is instead proven reached
    with a candidate whose selection is legitimate both before and after LEGIBLE
    (no lifecycle declaration, or the source's own helper), and the superseded
    roadmap is then pushed at the gate and at ``select_roadmap`` itself."""
    home = Path(tmp_path) / "home"
    home.mkdir(parents=True, exist_ok=True)

    # ---- reach evidence (must hold against UNCHANGED production) --------------
    no_declaration = _build_source_fixture(tmp_path / "reach", source, monkeypatch, "", home=home)
    superseded = _build_source_fixture(
        tmp_path / "superseded",
        source,
        monkeypatch,
        BANNER_LINE3["specs/phase-plans-v7.md"],
        home=home,
    )
    repo = superseded.repo
    candidate = superseded.target
    if source in ("explicit", "singleton-glob"):
        # These two sources are reachable only THROUGH select_roadmap, so the reach
        # proof uses the no-declaration roadmap that today's selector and the
        # post-LEGIBLE gate must both return.
        assert no_declaration.select() == no_declaration.target.resolve(), (
            f"{source} source not reached"
        )
    else:
        assert superseded.reach_source() == candidate.resolve(), f"{source} source not reached"

    try:
        gate = _new_symbol("phase_loop_runtime.discovery", "_return_selectable_roadmap")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
        selection_error = _new_symbol("phase_loop_runtime.roadmap_lint", "NonActiveSelectionError")
        discovery_mod = importlib.import_module("phase_loop_runtime.discovery")
    except (ImportError, AttributeError) as exc:
        _red(f"superseded-selector-{source}", str(exc))
        return

    # ---- the gate itself fails closed on the superseded candidate -------------
    with pytest.raises(error_cls):
        gate(repo, candidate, source)

    # ---- select_roadmap refuses the superseded candidate with the TYPED error --
    if source in ("explicit", "singleton-glob"):
        with pytest.raises(selection_error):
            superseded.select()

    # ---- wiring: select_roadmap must ROUTE through the common gate ------------
    # A correct gate that is never called would satisfy every assertion above
    # (roadmap's own dominant defect class), so record the real invocation.
    calls: list[tuple[Path, Path, str]] = []
    real_gate = gate

    def _spy(spy_repo, spy_candidate, spy_source, *args, **kwargs):
        calls.append((Path(spy_repo), Path(spy_candidate), spy_source))
        return real_gate(spy_repo, spy_candidate, spy_source, *args, **kwargs)

    monkeypatch.setattr(discovery_mod, "_return_selectable_roadmap", _spy)
    selected = no_declaration.select()
    assert selected == no_declaration.target.resolve()
    assert calls, (
        "select_roadmap returned without calling _return_selectable_roadmap: the "
        "common gate is defined but not wired into the selector"
    )
    assert calls[-1][2] == no_declaration.gate_source, (
        f"gate called with source label {calls[-1][2]!r}, expected "
        f"{no_declaration.gate_source!r} for the {source} fixture"
    )
    assert calls[-1][1].resolve() == no_declaration.target.resolve()
    monkeypatch.setattr(discovery_mod, "_return_selectable_roadmap", real_gate)

    # ---- positive companion: the ACTIVE v10 roadmap must still select ---------
    # Without an executed positive control, a gate that rejects EVERY roadmap
    # passes every fail-closed assertion above while being unable to select the
    # canonical specs/phase-plans-v10.md. The companion is driven through the
    # PUBLIC selector for THIS source (its own fixture, built with the real v10
    # path and banner), not merely through a direct gate call: a gate that
    # accepts v10 but is never reached from ``select_roadmap`` on this source
    # would satisfy a bare gate call while selecting nothing.
    _assert_real_banner_anchor("specs/phase-plans-v10.md")
    active = _build_source_fixture(
        tmp_path / "active",
        source,
        monkeypatch,
        BANNER_LINE3["specs/phase-plans-v10.md"],
        home=home,
        rel_path="specs/phase-plans-v10.md",
    )
    assert active.target.is_file()
    assert gate(active.repo, active.target, source) == active.target.resolve(), (
        "the recognized-ACTIVE v10 companion must pass the same gate"
    )
    calls.clear()
    monkeypatch.setattr(discovery_mod, "_return_selectable_roadmap", _spy)
    assert active.select() == active.target.resolve(), (
        f"the recognized-ACTIVE v10 companion must still be SELECTED through the "
        f"{source} source by select_roadmap, not merely accepted by a direct gate call"
    )
    assert calls, (
        "select_roadmap returned the ACTIVE v10 companion without calling "
        "_return_selectable_roadmap: the common gate is not wired into this source"
    )
    assert calls[-1][2] == active.gate_source, (
        f"gate called with source label {calls[-1][2]!r}, expected "
        f"{active.gate_source!r} for the active {source} fixture"
    )
    assert calls[-1][1].resolve() == active.target.resolve()
    monkeypatch.setattr(discovery_mod, "_return_selectable_roadmap", real_gate)


def test_absent_registry_selector_rejects_recognized_non_active_banner_and_preserves_no_declaration_legacy(
    tmp_path, monkeypatch
):
    """With ``specs/roadmap-status.json`` wholly ABSENT, every one of the eight real
    selector sources must still read candidate lifecycle bytes: recognized
    ``superseded`` and ``delivered`` are rejected, recognized ``active`` is accepted,
    ONLY a candidate with no lifecycle declaration at all keeps the legacy pass, and
    status-LIKE but unrecognized bytes are not "legacy" either.

    Each source is exercised through a real ``_build_source_fixture`` repo wired so
    that this source (and only this source) resolves to the candidate — passing a
    bare ``source`` STRING to the gate would prove only that the gate branches on a
    label, never that the absent-registry rule holds on the path that label names."""
    _assert_plan_contains("Legacy selection compatibility applies only when the candidate has "
                          "no lifecycle declaration at all")
    _assert_real_banner_anchor("specs/phase-plans-v10.md")
    try:
        gate = _new_symbol("phase_loop_runtime.discovery", "_return_selectable_roadmap")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("absent-registry-non-active-and-legacy", str(exc))
        return

    # (label, rel_path, line 3 bytes, verdict). The three recognized entries carry
    # the live committed banner grammar; "" means NO lifecycle declaration at all
    # (the sole legacy shape); the two malformed entries are status-LIKE bytes in
    # the primary declaration position that must fail typed rather than fall
    # through to the legacy branch.
    cases: tuple[tuple[str, str, str, str], ...] = (
        ("superseded", "specs/phase-plans-v7.md", BANNER_LINE3["specs/phase-plans-v7.md"], "reject"),
        ("delivered", "specs/phase-plans-v6.md", BANNER_LINE3["specs/phase-plans-v6.md"], "reject"),
        ("active", "specs/phase-plans-v10.md", BANNER_LINE3["specs/phase-plans-v10.md"], "accept"),
        ("no-declaration", "specs/phase-plans-v3.md", "", "accept"),
        (
            "malformed-ambiguous",
            "specs/phase-plans-v4.md",
            "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29) — ACTIVE",
            "reject",
        ),
        (
            "malformed-status-like",
            "specs/phase-plans-v5.md",
            "> **Status (2026-07-29): MOSTLY-ACTIVE — not a recognized lifecycle value.**",
            "reject",
        ),
    )
    assert len(SELECTOR_SOURCES) == 8

    home = Path(tmp_path) / "home"
    home.mkdir(parents=True, exist_ok=True)
    for source in SELECTOR_SOURCES:
        fixtures = {
            label: _build_source_fixture(
                Path(tmp_path) / source / label,
                source,
                monkeypatch,
                line3,
                home=home,
                rel_path=rel_path,
            )
            for label, rel_path, line3, _verdict in cases
        }

        # ---- reach evidence: the SOURCE really resolves to the candidate ------
        if source in ("explicit", "singleton-glob"):
            # These two are reachable only THROUGH select_roadmap, so the reach
            # proof rides on the one candidate today's selector and the
            # post-LEGIBLE gate must both return: the no-declaration legacy file.
            legacy = fixtures["no-declaration"]
            assert legacy.select() == legacy.target.resolve(), f"{source} source not reached"
        else:
            for label, fixture in fixtures.items():
                assert fixture.reach_source() == fixture.target.resolve(), (
                    f"{source} source not reached for the {label} candidate"
                )

        for label, _rel_path, _line3, verdict in cases:
            fixture = fixtures[label]
            registry_path = fixture.repo / "specs" / "roadmap-status.json"
            assert not registry_path.exists(), (
                f"{source}/{label} fixture is not the absent-registry case"
            )
            if verdict == "reject":
                with pytest.raises(error_cls):
                    gate(fixture.repo, fixture.target, source)
                if source in ("explicit", "singleton-glob"):
                    # For the two select-only sources the public entry point is
                    # the source, so its refusal is the source-level proof.
                    with pytest.raises(error_cls):
                        fixture.select()
            else:
                assert gate(fixture.repo, fixture.target, source) == fixture.target.resolve(), (
                    f"absent registry must still allow the {label} candidate on {source}"
                )
                assert fixture.select() == fixture.target.resolve(), (
                    f"the {label} candidate must still be selected through the "
                    f"{source} source with the registry absent"
                )


def test_legacy_repo_without_roadmap_status_registry_preserves_selection(tmp_path):
    _assert_plan_contains("reruns the pre-LEGIBLE\nsynthetic/legacy selector fixtures")
    repo = _init_repo(tmp_path)
    only = _write_banner_roadmap(repo, "specs/phase-plans-v1.md", "")
    only.write_text("# Legacy\n\n## Body\n", encoding="utf-8")
    _commit_all(repo)
    legacy_result = select_roadmap(repo, None)
    assert legacy_result == only.resolve()
    try:
        gate = _new_symbol("phase_loop_runtime.discovery", "_return_selectable_roadmap")
    except (ImportError, AttributeError) as exc:
        _red("legacy-no-registry-preserves-selection", str(exc))
        return
    assert gate(repo, only, "singleton-glob") == legacy_result


def test_registry_present_with_empty_partial_or_malformed_bytes_is_not_treated_as_absent(tmp_path):
    _assert_plan_contains("proving the compatibility branch is absence-only rather than an "
                          "error-swallowing\nfallback")
    try:
        read_status = _new_symbol("phase_loop_runtime.roadmap_lint", "read_roadmap_status")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("registry-present-malformed-not-absent", str(exc))
        return
    for label, contents in (("empty", ""), ("partial", '{"schema": "roadmap_status_manifest.v1"'), ("malformed", "not json")):
        repo = _init_repo(Path(tmp_path) / label)
        _write_all_tracked_roadmaps(repo)
        registry_path = repo / "specs" / "roadmap-status.json"
        registry_path.write_text(contents, encoding="utf-8")
        _commit_all(repo)
        with pytest.raises(error_cls):
            read_status(repo, registry_path)


def test_validate_roadmap_missing_registry_negative_control(tmp_path):
    _assert_plan_contains("declared_active_roadmap` each have an independent")
    repo = _init_repo(tmp_path)
    only = _write_banner_roadmap(repo, "specs/phase-plans-v1.md", "")
    only.write_text("# Legacy\n\n## Body\n", encoding="utf-8")
    _commit_all(repo)
    assert not (repo / "specs" / "roadmap-status.json").exists()
    try:
        validate = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
    except (ImportError, AttributeError) as exc:
        _red("validate-roadmap-missing-registry-negative-control", str(exc))
        return
    validate(repo, required=True)


def test_declared_active_roadmap_missing_registry_negative_control(tmp_path):
    _assert_plan_contains("declared_active_roadmap` each have an independent")
    repo = _init_repo(tmp_path)
    only = _write_banner_roadmap(repo, "specs/phase-plans-v1.md", "")
    only.write_text("# Legacy\n\n## Body\n", encoding="utf-8")
    _commit_all(repo)
    assert not (repo / "specs" / "roadmap-status.json").exists()
    try:
        declared_active = _new_symbol("phase_loop_runtime.roadmap_lint", "declared_active_roadmap")
    except (ImportError, AttributeError) as exc:
        _red("declared-active-roadmap-missing-registry-negative-control", str(exc))
        return
    assert declared_active(repo) == only.resolve()


def test_roadmap_status_error_hierarchy_distinguishes_malformed_registry_and_banner_and_coherence_and_selection_errors():
    _assert_plan_contains("The typed `RoadmapStatusError` hierarchy distinguishes malformed "
                          "registry, malformed/ambiguous/missing banner signal, registry/banner "
                          "coherence drift, and attempted selection of a recognized non-active "
                          "roadmap")
    try:
        base = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
        malformed_registry = _new_symbol("phase_loop_runtime.roadmap_lint", "MalformedRegistryError")
        banner_error = _new_symbol("phase_loop_runtime.roadmap_lint", "MalformedBannerError")
        coherence_error = _new_symbol("phase_loop_runtime.roadmap_lint", "StatusCoherenceError")
        selection_error = _new_symbol("phase_loop_runtime.roadmap_lint", "NonActiveSelectionError")
    except (ImportError, AttributeError) as exc:
        _red("status-error-hierarchy-distinguishes-four-kinds", str(exc))
        return
    for subclass in (malformed_registry, banner_error, coherence_error, selection_error):
        assert issubclass(subclass, base)
    assert len({malformed_registry, banner_error, coherence_error, selection_error}) == 4


def test_read_roadmap_status_validates_full_coverage_before_returning_any_value(tmp_path):
    _assert_plan_contains("every path's registry value must equal its parsed primary-banner "
                          "value before any value is returned")
    repo = _init_repo(tmp_path)
    partial = {p: s for p, s in TRACKED_ROADMAP_STATUS.items() if p != "specs/phase-plans-v9.md"}
    _write_all_tracked_roadmaps(repo)
    registry_path = _write_status_registry(repo, partial)
    _commit_all(repo)
    try:
        read_status = _new_symbol("phase_loop_runtime.roadmap_lint", "read_roadmap_status")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("read-roadmap-status-full-coverage-before-return", str(exc))
        return
    with pytest.raises(error_cls):
        read_status(repo, registry_path)


def test_canonical_validate_roadmap_calls_coherence_validator_with_required_true(tmp_path):
    _assert_plan_contains("Canonical repository `validate-roadmap` calls the same coherence "
                          "validator with `required=True`")
    try:
        from phase_loop_runtime import cli as cli_module
    except ImportError as exc:  # pragma: no cover - cli always importable today
        _red("canonical-validate-roadmap-required-true", str(exc))
        return
    try:
        coherence = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
    except AttributeError as exc:
        _red("canonical-validate-roadmap-required-true", str(exc))
        return
    if _canonical_repo_ready():
        target_roadmap = ROADMAP_PATH
    else:
        # Installed-wheel clean room: exercise the identical CLI wiring
        # against a synthetic repo built from the same frozen registry
        # fixtures, since there is no canonical specs/ tree to point at.
        repo = _init_repo(tmp_path)
        _write_all_tracked_roadmaps(repo)
        _write_status_registry(repo, TRACKED_ROADMAP_STATUS)
        _commit_all(repo)
        target_roadmap = repo / "specs" / "phase-plans-v10.md"
    calls: list[bool] = []
    original = coherence

    def _spy(repo, required=False):  # noqa: ANN001 - test spy
        calls.append(required)
        return original(repo, required=required)

    import phase_loop_runtime.roadmap_lint as roadmap_lint_module

    roadmap_lint_module.validate_roadmap_status_coherence = _spy
    try:
        cli_module.main(["validate-roadmap", str(target_roadmap)])
    finally:
        roadmap_lint_module.validate_roadmap_status_coherence = original
    assert calls and all(value is True for value in calls), (
        "canonical validate-roadmap must call the coherence validator with required=True"
    )


def test_registry_rejects_noncanonical_or_escaping_path_and_selected_active_mismatch(tmp_path):
    _assert_plan_contains("A present registry with a missing/extra/duplicate/noncanonical path, "
                          "path escape, malformed/unknown status, selected/active mismatch, "
                          "unparseable banner, or sidecar/banner drift is a typed failure")
    try:
        validate = _new_symbol("phase_loop_runtime.roadmap_lint", "validate_roadmap_status_coherence")
        error_cls = _new_symbol("phase_loop_runtime.roadmap_lint", "RoadmapStatusError")
    except (ImportError, AttributeError) as exc:
        _red("registry-rejects-noncanonical-escaping-selected-mismatch", str(exc))
        return
    for label, mutate in (
        ("noncanonical", lambda s: {**s, "specs/../etc/passwd": s.pop("specs/phase-plans-v9.md") if False else "superseded"}),
        ("escaping", lambda s: {**s, "../outside.md": "superseded"}),
        ("selected-mismatch", lambda s: dict(s)),
    ):
        repo = _init_repo(Path(tmp_path) / label)
        _write_all_tracked_roadmaps(repo)
        statuses = mutate(dict(TRACKED_ROADMAP_STATUS))
        selected = "specs/phase-plans-v7.md" if label == "selected-mismatch" else "specs/phase-plans-v10.md"
        _write_status_registry(repo, statuses, selected=selected)
        _commit_all(repo)
        with pytest.raises(error_cls):
            validate(repo, required=True)


def test_read_roadmap_status_returns_none_when_registry_absent(tmp_path):
    _assert_plan_contains("For a synthetic or legacy fixture repo with `specs/roadmap-status.json` "
                          "wholly absent, `read_roadmap_status` returns `None`")
    repo = _init_repo(tmp_path)
    _write_all_tracked_roadmaps(repo)
    _commit_all(repo)
    assert not (repo / "specs" / "roadmap-status.json").exists()
    try:
        read_status = _new_symbol("phase_loop_runtime.roadmap_lint", "read_roadmap_status")
    except (ImportError, AttributeError) as exc:
        _red("read-roadmap-status-none-when-absent", str(exc))
        return
    assert read_status(repo, repo / "specs" / "roadmap-status.json") is None


def test_manifest_reporting_consumes_coherence_checked_accessor(tmp_path):
    _assert_plan_contains("Manifest reporting consumes the same coherence-checked accessor")
    try:
        read_status = _new_symbol("phase_loop_runtime.roadmap_lint", "read_roadmap_status")
        report_fn = _new_symbol("phase_loop_runtime.plan_manifest", "canonical_plan_files")
    except (ImportError, AttributeError) as exc:
        _red("manifest-reporting-consumes-coherence-checked-accessor", str(exc))
        return
    if _canonical_repo_ready():
        target_repo = REPO_ROOT
    else:
        # Installed-wheel clean room: no canonical .git/HEAD to resolve, so
        # exercise the identical call-through wiring against a synthetic
        # one-commit repo instead.
        target_repo = _init_repo(tmp_path)
    calls: list[Path] = []
    original = read_status

    def _spy(repo, path):  # noqa: ANN001 - test spy
        calls.append(Path(repo))
        return original(repo, path)

    import phase_loop_runtime.roadmap_lint as roadmap_lint_module

    roadmap_lint_module.read_roadmap_status = _spy
    try:
        report_fn(target_repo, "HEAD")
    finally:
        roadmap_lint_module.read_roadmap_status = original
    assert calls, "manifest reporting never consulted the coherence-checked accessor"


def test_declared_active_roadmap_returns_registry_and_banner_active_v10_path(tmp_path):
    _assert_plan_contains("requiring the on-disk selected path to equal the sole "
                          "registry/banner-active roadmap")
    try:
        declared_active = _new_symbol("phase_loop_runtime.roadmap_lint", "declared_active_roadmap")
    except (ImportError, AttributeError) as exc:
        _red("declared-active-roadmap-returns-v10", str(exc))
        return
    if _canonical_repo_ready():
        assert declared_active(REPO_ROOT) == ROADMAP_PATH.resolve()
        return
    # Installed-wheel clean room: exercise the identical public contract
    # against a synthetic repo built from the same frozen registry fixtures.
    repo = _init_repo(tmp_path)
    _write_all_tracked_roadmaps(repo)
    _write_status_registry(repo, TRACKED_ROADMAP_STATUS)
    _commit_all(repo)
    assert declared_active(repo) == (repo / "specs" / "phase-plans-v10.md").resolve()


def test_parse_roadmap_banner_status_positive_control_all_thirteen_tracked_banners_parse(tmp_path):
    for path in TRACKED_ROADMAP_STATUS:
        _assert_real_banner_anchor(path)
    try:
        parse = _new_symbol("phase_loop_runtime.roadmap_lint", "parse_roadmap_banner_status")
    except (ImportError, AttributeError) as exc:
        _red("banner-positive-control-all-thirteen-parse", str(exc))
        return
    if _canonical_repo_ready():
        repo = REPO_ROOT
    else:
        # Installed-wheel clean room: exercise the identical parser against a
        # synthetic repo built from the same frozen BANNER_LINE3 fixture.
        repo = _init_repo(tmp_path)
        _write_all_tracked_roadmaps(repo)
        _commit_all(repo)
    for path, expected_status in TRACKED_ROADMAP_STATUS.items():
        text = (repo / path).read_text(encoding="utf-8")
        assert parse(text, path) == expected_status, f"{path} must parse as {expected_status}"


# ===========================================================================
# Group 2 — assumption probes (23 nodeids)
# ===========================================================================

# Each row is exactly one line of "Assumptions (fail-loud if wrong)" in
# specs/phase-plans-v10.md, mirroring the per-drifting-fact inventory in
# plans/phase-plan-v10-LEGIBLE.md ("The complete per-drifting-fact inventory is").
#
# A row is a closed, literal ``roadmap_assumption_probe.v1`` declaration (its
# eight sidecar keys are projected verbatim by ``_sidecar_probe`` below) PLUS
# the two closed observations this suite needs in order to falsify it:
# ``observation`` is the currently-true payload named by the plan table's
# "Positive control" column, and ``mutation`` is the exact payload named by its
# "Mutation that must fail" column. Both are inert JSON data. No row carries a
# command, argv, shell, cwd, env, route, expected-transition-state, or
# result-override field (mechanically enforced by ``_assert_no_executable_keys``
# at import), and the audited surface gains no caller-selected knob for them:
# they reach the audit through exactly ONE generic seam, the fixed
# adapter-dispatch boundary
# ``phase_loop_runtime.roadmap_assumptions.observe_assumption_probe(repo, probe)``,
# monkeypatched here so a hermetic clean-room run drives the same public
# declaration parser and ``expected``-vs-observation evaluator the live adapters
# feed in a canonical checkout. The verdict is therefore always computed by
# production from ``expected`` and the observation, never supplied by the
# fixture -- an adapter (or an ``audit_roadmap_assumptions`` stub) that answers
# ``ok=True`` for every probe fails all 23 mutation assertions below.
#
# ``expected`` uses one generic, kind-agnostic vocabulary; each adapter's kind
# fixes which subset of it that kind's closed schema may use:
#   * "required_present": [k]   -> observation[k] must be present and non-null
#   * "required_atoms":  [s]    -> every s must appear in observation["atoms"]
#   * "forbidden_atoms": [s]    -> no s may appear in observation["atoms"]
#   * "required_edges": [[a,b]] -> every pair must appear in observation["edges"]
#   * "fields": {k: v}          -> observation["fields"][k] must equal v
#   * "must_agree": true        -> every observation["values"] entry must equal
#                                  expected["agreed_value"]
#   * "declared_states": [s]    -> the fixed ``reviewtruth_fable_transition``
#                                  adapter must classify the raw observation
#                                  into exactly one of these declared states
#                                  (the caller supplies no expected state)
#   * every other key           -> observation[key] must equal it
_EXPECTED_CONTROL_KEYS = frozenset({
    "required_present", "required_atoms", "forbidden_atoms", "required_edges",
    "fields", "must_agree", "agreed_value", "declared_states",
})

_PIN_SHA = "b862f977897a7b87c4419680a3e83735d4ff07b0"
_SUPERSEDED_PIN_SHA = "c10854831f0d4e2b9a6c7d8e5f4031a2b3c4d5e6"
_SUBMISSION_DIGEST = "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a"
_VERDICT_DIGEST = "86169277d3a0823db1a6c9fa4d20a838b0bc2820818ad00ebd53dcdd03c2b1c2"
_RATIFICATION_COMMENT_SHA = "5c165d83193477de52c5a41018316208e07e56192c9b18c7e9ad1bac45757b4f"
_PIN_MODULE = "phase_loop_runtime.conformance.outside_agent_pin"
_PIN_ATTRIBUTE = "EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN"

ASSUMPTION_PROBES: tuple[dict[str, object], ...] = (
    {
        "id": "LEGIBLE-A1-PR102",
        "assumption": 1,
        "kind": "github_pr",
        "anchor": "`spec#102` MERGED",
        "mutation_id": "observe-open-or-closed-unmerged",
        "positive_control_id": "current-merged-payload",
        "subject": {"repository": "Consiliency/spec", "number": 102},
        "expected": {"state": "MERGED", "required_present": ["merged_at", "merge_commit_oid"]},
        "observation": {
            "state": "MERGED",
            "merged_at": "2026-07-29T00:00:00Z",
            "merge_commit_oid": "1f0a2b3c4d5e6f708192a3b4c5d6e7f809a1b2c3",
        },
        "mutation": {"state": "OPEN", "merged_at": None, "merge_commit_oid": None},
    },
    {
        "id": "LEGIBLE-A1-I118",
        "assumption": 1,
        "kind": "github_issue",
        "anchor": "`spec#118` is CLOSED",
        "mutation_id": "observe-open",
        "positive_control_id": "current-closed-payload",
        "subject": {"repository": "Consiliency/spec", "number": 118},
        "expected": {"state": "CLOSED"},
        "observation": {"state": "CLOSED"},
        "mutation": {"state": "OPEN"},
    },
    {
        "id": "LEGIBLE-A1-PR377",
        "assumption": 1,
        "kind": "github_pr",
        "anchor": "`agent-harness#377` landed",
        "mutation_id": "remove-merge-timestamp",
        "positive_control_id": "current-merged-reachable-payload",
        "subject": {"repository": "Consiliency/agent-harness", "number": 377},
        "expected": {
            "state": "MERGED",
            "ancestor_of_default_branch": True,
            "required_present": ["merged_at", "merge_commit_oid"],
        },
        "observation": {
            "state": "MERGED",
            "merged_at": "2026-07-29T00:00:00Z",
            "merge_commit_oid": "2b1c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e",
            "ancestor_of_default_branch": True,
        },
        # The plan's named mutation for this row: keep the merged state and the
        # reachable merge commit, and remove ONLY the merge timestamp.
        "mutation": {
            "state": "MERGED",
            "merged_at": None,
            "merge_commit_oid": "2b1c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e",
            "ancestor_of_default_branch": True,
        },
    },
    {
        "id": "LEGIBLE-A1-PIN-TAG",
        "assumption": 1,
        "kind": "repo_constant",
        "anchor": 'contract_git_tag="v0.2.1"',
        "mutation_id": "change-only-the-tag",
        "positive_control_id": "current-tag",
        "subject": {"module": _PIN_MODULE, "attribute": _PIN_ATTRIBUTE, "field": "contract_git_tag"},
        "expected": {"value": "v0.2.1"},
        "observation": {"value": "v0.2.1"},
        "mutation": {"value": "v0.2.0"},
    },
    {
        "id": "LEGIBLE-A1-PIN-SHA",
        "assumption": 1,
        "kind": "repo_constant",
        "anchor": 'contract_git_sha="b862f977',
        "mutation_id": "change-only-the-sha-including-back-to-c1085483",
        "positive_control_id": "current-sha",
        "subject": {"module": _PIN_MODULE, "attribute": _PIN_ATTRIBUTE, "field": "contract_git_sha"},
        "expected": {"value": _PIN_SHA},
        "observation": {"value": _PIN_SHA},
        "mutation": {"value": _SUPERSEDED_PIN_SHA},
    },
    {
        "id": "LEGIBLE-A1-TAG-DEREF",
        "assumption": 1,
        "kind": "github_ref",
        "anchor": 'contract_git_sha="b862f977',
        "mutation_id": "return-a-different-tag-target",
        "positive_control_id": "current-dereference-and-reachability",
        "subject": {"repository": "Consiliency/spec", "tag": "v0.2.1", "peel": True},
        "expected": {"peeled_sha": _PIN_SHA, "reachable_from_default_branch": True},
        "observation": {"peeled_sha": _PIN_SHA, "reachable_from_default_branch": True},
        "mutation": {"peeled_sha": _SUPERSEDED_PIN_SHA, "reachable_from_default_branch": True},
    },
    {
        "id": "LEGIBLE-A1-SUBMISSION-DIGEST",
        "assumption": 1,
        "kind": "repo_digest",
        "anchor": "submission_schema_sha256`",
        "mutation_id": "flip-one-schema-byte",
        "positive_control_id": "unchanged-bytes-and-digest",
        "subject": {
            "module": _PIN_MODULE,
            "attribute": _PIN_ATTRIBUTE,
            "field": "submission_schema_sha256",
            "resource": "consiliency_spec/_data/schemas/outside-agent-submission.schema.json",
        },
        "expected": {"algorithm": "sha256", "pinned": _SUBMISSION_DIGEST, "computed": _SUBMISSION_DIGEST},
        "observation": {"algorithm": "sha256", "pinned": _SUBMISSION_DIGEST, "computed": _SUBMISSION_DIGEST},
        "mutation": {
            "algorithm": "sha256",
            "pinned": _SUBMISSION_DIGEST,
            "computed": _SUBMISSION_DIGEST[:-1] + ("b" if _SUBMISSION_DIGEST[-1] == "a" else "a"),
        },
    },
    {
        "id": "LEGIBLE-A1-VERDICT-DIGEST",
        "assumption": 1,
        "kind": "repo_digest",
        "anchor": "verdict_schema_sha256`",
        "mutation_id": "flip-the-recorded-digest",
        "positive_control_id": "unchanged-bytes-and-digest",
        "subject": {
            "module": _PIN_MODULE,
            "attribute": _PIN_ATTRIBUTE,
            "field": "verdict_schema_sha256",
            "resource": "consiliency_spec/_data/schemas/outside-agent-route-verdict.schema.json",
        },
        "expected": {"algorithm": "sha256", "pinned": _VERDICT_DIGEST, "computed": _VERDICT_DIGEST},
        "observation": {"algorithm": "sha256", "pinned": _VERDICT_DIGEST, "computed": _VERDICT_DIGEST},
        "mutation": {
            "algorithm": "sha256",
            "pinned": _VERDICT_DIGEST[:-1] + ("b" if _VERDICT_DIGEST[-1] == "a" else "a"),
            "computed": _VERDICT_DIGEST,
        },
    },
    {
        "id": "LEGIBLE-A1-CONFORM-UNGATED",
        "assumption": 1,
        "kind": "roadmap_predicate",
        "anchor": "NO LONGER externally gated",
        "mutation_id": "inject-a-spec118-must-close-dependency",
        "positive_control_id": "current-dependency-graph",
        "subject": {"roadmap": "specs/phase-plans-v10.md", "phase": "CONFORM", "predicate": "dependencies"},
        "expected": {"forbidden_atoms": ["CONFORM depends on spec#118 closing"]},
        "observation": {"atoms": ["CONFORM pin work is satisfiable against merged sources"]},
        "mutation": {
            "atoms": [
                "CONFORM pin work is satisfiable against merged sources",
                "CONFORM depends on spec#118 closing",
            ]
        },
    },
    {
        "id": "LEGIBLE-A2-I128",
        "assumption": 2,
        "kind": "github_issue",
        "anchor": "`governed-pipeline#128`",
        "mutation_id": "observe-closed",
        "positive_control_id": "current-open-payload",
        "subject": {"repository": "Consiliency/governed-pipeline", "number": 128},
        "expected": {"state": "OPEN"},
        "observation": {"state": "OPEN"},
        "mutation": {"state": "CLOSED"},
    },
    {
        "id": "LEGIBLE-A2-GP-PIN",
        "assumption": 2,
        "kind": "remote_json_field",
        "anchor": "pin agent-harness 0.5.0",
        "mutation_id": "change-expected-version-field-alone",
        "positive_control_id": "current-remote-json",
        "subject": {
            "repository": "Consiliency/governed-pipeline",
            "ref": "default-branch",
            "path": "tools/agent-harness.pin.json",
        },
        "expected": {
            "fields": {
                "package": "phase-loop-runtime",
                "expected_version": "0.5.0",
                "pip_spec": "phase-loop-runtime==0.5.0",
            }
        },
        "observation": {
            "fields": {
                "package": "phase-loop-runtime",
                "expected_version": "0.5.0",
                "pip_spec": "phase-loop-runtime==0.5.0",
            }
        },
        # Exactly one field changed, independently of the other two.
        "mutation": {
            "fields": {
                "package": "phase-loop-runtime",
                "expected_version": "0.6.0",
                "pip_spec": "phase-loop-runtime==0.5.0",
            }
        },
    },
    {
        "id": "LEGIBLE-A2-LOCAL-VERSION",
        "assumption": 2,
        "kind": "repo_constant",
        "anchor": "we ship 0.7.13",
        "mutation_id": "change-either-surface-alone",
        "positive_control_id": "current-equal-pair",
        "subject": {
            "surfaces": [
                {"file": "phase-loop-runtime/pyproject.toml", "field": "project.version"},
                {"module": "phase_loop_runtime", "attribute": "__version__"},
            ]
        },
        "expected": {"must_agree": True, "agreed_value": "0.7.13"},
        "observation": {"values": ["0.7.13", "0.7.13"]},
        "mutation": {"values": ["0.7.14", "0.7.13"]},
    },
    {
        "id": "LEGIBLE-A2-NO-DEPENDENCY",
        "assumption": 2,
        "kind": "roadmap_predicate",
        "anchor": "No phase here depends on that being resolved.",
        "mutation_id": "inject-one-phase-dependency-on-issue-closure",
        "positive_control_id": "current-roadmap",
        "subject": {"roadmap": "specs/phase-plans-v10.md", "predicate": "closure-prerequisites"},
        "expected": {"forbidden_atoms": ["phase requires governed-pipeline#128 closed"]},
        "observation": {"atoms": []},
        "mutation": {"atoms": ["phase requires governed-pipeline#128 closed"]},
    },
    {
        "id": "LEGIBLE-A3-REVIEWTRUTH-TRANSITION",
        "assumption": 3,
        "kind": "reviewtruth_fable_transition",
        "anchor": "agent-harness#396",
        "mutation_id": "open-issue-with-native-fill-request",
        "positive_control_id": "current-pending-observation",
        # Closed subject: repository, issue, model, source anchor. No command,
        # route, environment, timeout, or expected issue state is supplied.
        "subject": {
            "repository": "Consiliency/agent-harness",
            "issue": 396,
            "model": "claude-fable-5",
            "source_anchor": "agent-harness#396",
        },
        "expected": {"declared_states": ["pending", "resolved"]},
        "observation": {
            "issue_state": "OPEN",
            "issue_disposition": None,
            "native_fill_request": False,
            "seat_result": "UNAVAILABLE/tui_adapter_required",
            "first_party_route_available": True,
            "fable_leg": "succeeded",
            "verdict_bound": False,
            "seat_count": "degraded",
        },
        # OPEN plus a native-fill request is the mixed state the plan requires
        # to fail loud: it classifies as neither `pending` nor `resolved`.
        "mutation": {
            "issue_state": "OPEN",
            "issue_disposition": None,
            "native_fill_request": True,
            "seat_result": "UNAVAILABLE/tui_adapter_required",
            "first_party_route_available": True,
            "fable_leg": "succeeded",
            "verdict_bound": False,
            "seat_count": "degraded",
        },
    },
    {
        "id": "LEGIBLE-A3-NO-DEGRADED-GATE",
        "assumption": 3,
        "kind": "roadmap_predicate",
        "anchor": "stricter panel gate",
        "mutation_id": "authorize-three-of-four-promotion",
        "positive_control_id": "current-no-degraded-policy",
        "subject": {"roadmap": "specs/phase-plans-v10.md", "predicate": "execution-policy"},
        "expected": {
            "required_atoms": ["four-vendor exact-digest review required"],
            "forbidden_atoms": ["degraded 3-of-4 promotion authorized"],
        },
        "observation": {"atoms": ["four-vendor exact-digest review required"]},
        "mutation": {
            "atoms": [
                "four-vendor exact-digest review required",
                "degraded 3-of-4 promotion authorized",
            ]
        },
    },
    {
        "id": "LEGIBLE-A3-EC4",
        "assumption": 3,
        "kind": "roadmap_predicate",
        "anchor": "EC-REVIEWTRUTH-4 TYPES the vacancy",
        "mutation_id": "remove-one-state-or-signal",
        "positive_control_id": "current-criterion",
        "subject": {"roadmap": "specs/phase-plans-v10.md", "criterion": "EC-REVIEWTRUTH-4"},
        "expected": {
            "required_atoms": ["FULL", "FLOOR-ONLY", "BELOW-FLOOR", "typed unfillable signal"]
        },
        "observation": {"atoms": ["FULL", "FLOOR-ONLY", "BELOW-FLOOR", "typed unfillable signal"]},
        "mutation": {"atoms": ["FULL", "FLOOR-ONLY", "typed unfillable signal"]},
    },
    {
        "id": "LEGIBLE-A3-EC14",
        "assumption": 3,
        "kind": "roadmap_predicate",
        "anchor": "EC-REVIEWTRUTH-14 FILLS it natively under Claude Code with no TUI adapter",
        "mutation_id": "remove-the-verdict-binding-edge",
        "positive_control_id": "current-criterion",
        "subject": {
            "roadmap": "specs/phase-plans-v10.md",
            "criterion": "EC-REVIEWTRUTH-14",
        },
        "expected": {
            "required_atoms": ["NativeAgentLegRequest", "no TUI adapter", "VERDICT is BOUND"]
        },
        "observation": {"atoms": ["NativeAgentLegRequest", "no TUI adapter", "VERDICT is BOUND"]},
        "mutation": {"atoms": ["NativeAgentLegRequest", "no TUI adapter"]},
    },
    {
        "id": "LEGIBLE-A4-DISCOVERY",
        "assumption": 4,
        "kind": "ast_call_predicate",
        "anchor": "load-bearing for roadmap discovery",
        "mutation_id": "remove-the-manifest-entries-call-edge",
        "positive_control_id": "current-call-chain",
        "subject": {
            "module": "phase_loop_runtime.discovery",
            "edges": [
                ["manifest_backed_roadmap", "_phase_manifest_entries"],
                ["_phase_manifest_entries", "valid_phase_entries"],
            ],
        },
        "expected": {
            "required_edges": [
                ["manifest_backed_roadmap", "_phase_manifest_entries"],
                ["_phase_manifest_entries", "valid_phase_entries"],
            ]
        },
        "observation": {
            "edges": [
                ["manifest_backed_roadmap", "_phase_manifest_entries"],
                ["_phase_manifest_entries", "valid_phase_entries"],
            ]
        },
        "mutation": {"edges": [["_phase_manifest_entries", "valid_phase_entries"]]},
    },
    {
        "id": "LEGIBLE-A4-PR170",
        "assumption": 4,
        "kind": "github_pr",
        "anchor": "agent-harness#170",
        "mutation_id": "observe-closed-unmerged",
        "positive_control_id": "current-merged-payload",
        "subject": {"repository": "Consiliency/agent-harness", "number": 170},
        "expected": {"state": "MERGED", "required_present": ["merged_at"]},
        "observation": {"state": "MERGED", "merged_at": "2025-11-04T00:00:00Z"},
        "mutation": {"state": "CLOSED", "merged_at": None},
    },
    {
        "id": "LEGIBLE-A4-PER-ENTRY",
        "assumption": 4,
        "kind": "manifest_behavior",
        "anchor": "fixed per-entry in",
        "mutation_id": "restore-whole-manifest-invalidation",
        "positive_control_id": "current-per-entry-behavior",
        "subject": {
            "manifest": "plans/manifest.json",
            "injected_invalid_sibling": True,
            "valid_entry_roadmap": "specs/phase-plans-v10.md",
        },
        "expected": {"invalid_sibling_excluded": True, "valid_entry_discoverable": True},
        "observation": {"invalid_sibling_excluded": True, "valid_entry_discoverable": True},
        "mutation": {"invalid_sibling_excluded": False, "valid_entry_discoverable": False},
    },
    {
        "id": "LEGIBLE-A5-RATIFICATION",
        "assumption": 5,
        "kind": "github_comment",
        "anchor": "agent-harness#363",
        "mutation_id": "mutate-the-comment-digest",
        "positive_control_id": "current-comment",
        "subject": {
            "repository": "Consiliency/agent-harness",
            "issue": 363,
            "comment_id": "5109553368",
            "author": "ViperJuice",
        },
        "expected": {
            "author": "ViperJuice",
            "sha256": _RATIFICATION_COMMENT_SHA,
            "required_atoms": [
                "ONE shared monotonic epoch allocator",
                "publish byte-neutrality is RETRACTED",
            ],
        },
        "observation": {
            "author": "ViperJuice",
            "sha256": _RATIFICATION_COMMENT_SHA,
            "atoms": [
                "ONE shared monotonic epoch allocator",
                "publish byte-neutrality is RETRACTED",
            ],
        },
        "mutation": {
            "author": "ViperJuice",
            "sha256": _RATIFICATION_COMMENT_SHA[:-1] + (
                "b" if _RATIFICATION_COMMENT_SHA[-1] == "a" else "a"
            ),
            "atoms": [
                "ONE shared monotonic epoch allocator",
                "publish byte-neutrality is RETRACTED",
            ],
        },
    },
    {
        "id": "LEGIBLE-A5-SHARED-EPOCH",
        "assumption": 5,
        "kind": "roadmap_predicate",
        "anchor": "shared monotonic epoch",
        "mutation_id": "change-fabpub-to-scoped-allocation",
        "positive_control_id": "current-roadmap-predicates",
        "subject": {
            "roadmap": "specs/phase-plans-v10.md",
            "predicate": "epoch-allocation",
            "sources": ["assumption-5", "FABPUB objective/criteria"],
        },
        "expected": {
            "required_atoms": [
                "assumption-5: ONE shared monotonic epoch allocator",
                "FABPUB: ONE shared monotonic epoch allocator",
            ]
        },
        "observation": {
            "atoms": [
                "assumption-5: ONE shared monotonic epoch allocator",
                "FABPUB: ONE shared monotonic epoch allocator",
            ]
        },
        "mutation": {
            "atoms": [
                "assumption-5: ONE shared monotonic epoch allocator",
                "FABPUB: split scoped epoch allocation",
            ]
        },
    },
    {
        "id": "LEGIBLE-A5-RETRACTION",
        "assumption": 5,
        "kind": "roadmap_predicate",
        "anchor": "publish byte-neutrality is RETRACTED",
        "mutation_id": "delete-the-ec-fabpub-7-retraction-and-reintroduce-neutrality",
        "positive_control_id": "current-roadmap-predicates",
        "subject": {
            "roadmap": "specs/phase-plans-v10.md",
            "predicate": "publish-byte-neutrality",
            "sources": ["assumption-5", "EC-FABPUB-7"],
        },
        "expected": {
            "required_atoms": [
                "assumption-5: publish byte-neutrality is RETRACTED",
                "EC-FABPUB-7: publish byte-neutrality is RETRACTED",
            ],
            "forbidden_atoms": ["publish is byte-neutral"],
        },
        "observation": {
            "atoms": [
                "assumption-5: publish byte-neutrality is RETRACTED",
                "EC-FABPUB-7: publish byte-neutrality is RETRACTED",
            ]
        },
        "mutation": {
            "atoms": [
                "assumption-5: publish byte-neutrality is RETRACTED",
                "publish is byte-neutral",
            ]
        },
    },
)

assert len(ASSUMPTION_PROBES) == 23
assert len({row["id"] for row in ASSUMPTION_PROBES}) == 23

# ---------------------------------------------------------------------------
# Closed-fixture self-checks (these ARE rule 3: no probe row may smuggle in a
# caller-selected executable/bypass field, and every row must carry the closed
# metadata the mutation and its independent positive control need).

ASSUMPTION_MODULE = "phase_loop_runtime.roadmap_assumptions"
# The ONE fixed adapter-dispatch boundary this suite binds. It is not a public
# caller-selected parameter: `audit_roadmap_assumptions` keeps its planned
# `(repo, probe_ids=...)` signature and gains no observation/route/result knob.
ASSUMPTION_OBSERVATION_SEAM = "observe_assumption_probe"
ASSUMPTION_SIDECAR_REL = "specs/roadmap-assumption-probes-v10.json"

# Exactly the eight keys `roadmap_assumption_probe.v1` allows in a probe object.
SIDECAR_PROBE_KEYS: tuple[str, ...] = (
    "assumption", "expected", "id", "kind", "mutation_id",
    "positive_control_id", "source_anchor", "subject",
)
_ROW_KEYS = frozenset({
    "id", "assumption", "kind", "anchor", "mutation_id", "positive_control_id",
    "subject", "expected", "observation", "mutation",
})
_FORBIDDEN_PROBE_KEYS = frozenset({"command", "argv", "shell", "cwd", "env"})
ALLOWED_PROBE_KINDS = frozenset({
    "github_issue", "github_pr", "github_comment", "github_ref", "remote_json_field",
    "repo_constant", "repo_digest", "release_identity", "ast_call_predicate",
    "roadmap_predicate", "manifest_behavior", "reviewtruth_fable_transition",
})


def _assert_no_executable_keys(node: object, where: str) -> None:
    """No probe subject/expected/observation payload may carry a command, argv,
    shell, cwd, or env key at ANY depth (plans/phase-plan-v10-LEGIBLE.md: "keys
    named `command`, `argv`, `shell`, `cwd`, or `env` are rejected at any
    depth"). This is what keeps the fixture mechanism a closed observation
    boundary rather than a caller-selected execution knob."""
    if isinstance(node, dict):
        for key, value in node.items():
            assert key not in _FORBIDDEN_PROBE_KEYS, f"{where}: forbidden executable key {key!r}"
            _assert_no_executable_keys(value, f"{where}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _assert_no_executable_keys(value, f"{where}[{index}]")


for _row in ASSUMPTION_PROBES:
    assert set(_row) == _ROW_KEYS, f"{_row['id']}: probe row keys drifted: {sorted(_row)}"
    assert _row["kind"] in ALLOWED_PROBE_KINDS, f"{_row['id']}: unsupported kind {_row['kind']!r}"
    assert _row["assumption"] in (1, 2, 3, 4, 5), _row["id"]
    assert _row["anchor"] and _row["mutation_id"] and _row["positive_control_id"], _row["id"]
    assert _row["observation"] != _row["mutation"], (
        f"{_row['id']}: the mutation must differ from the positive-control observation"
    )
    for _field in ("subject", "expected", "observation", "mutation"):
        assert isinstance(_row[_field], dict) and _row[_field], f"{_row['id']}.{_field} is empty"
        _assert_no_executable_keys(_row[_field], f"{_row['id']}.{_field}")
del _row, _field


def _sidecar_probe(row: dict[str, object]) -> dict[str, object]:
    """Project one row onto exactly the eight `roadmap_assumption_probe.v1`
    keys — the observation fixtures never reach the committed sidecar."""
    probe = {
        "id": row["id"],
        "assumption": row["assumption"],
        "kind": row["kind"],
        "subject": row["subject"],
        "expected": row["expected"],
        "source_anchor": row["anchor"],
        "mutation_id": row["mutation_id"],
        "positive_control_id": row["positive_control_id"],
    }
    assert tuple(sorted(probe)) == SIDECAR_PROBE_KEYS
    return probe


def _synthetic_assumption_roadmap_text() -> str:
    """Return the canonical roadmap bytes for a repo with synthetic observations."""
    return ROADMAP_PATH.read_text(encoding="utf-8")


def _synthetic_probe_repo(tmp_path: Path) -> Path:
    """A committed, self-contained repo carrying the canonical roadmap, the
    matching ``roadmap_assumption_probe.v1`` sidecar (all 23 probes, stable
    path-sorted by id), a coherent status registry, and a plan whose
    frontmatter digest matches the roadmap bytes."""
    repo = _init_repo(tmp_path)
    roadmap_text = _synthetic_assumption_roadmap_text()
    (repo / "specs" / "phase-plans-v10.md").write_text(roadmap_text, encoding="utf-8")
    digest = hashlib.sha256(roadmap_text.encode("utf-8")).hexdigest()
    (repo / "plans" / "phase-plan-v10-LEGIBLE.md").write_text(
        "---\n"
        "phase_loop_plan_version: 1\n"
        "phase: LEGIBLE\n"
        "roadmap: specs/phase-plans-v10.md\n"
        f"roadmap_sha256: {digest}\n"
        "---\n# LEGIBLE\n",
        encoding="utf-8",
    )
    sidecar = {
        "schema": "roadmap_assumption_probe.v1",
        "roadmap": "specs/phase-plans-v10.md",
        "roadmap_sha256": digest,
        "probes": [
            _sidecar_probe(row) for row in sorted(ASSUMPTION_PROBES, key=lambda r: str(r["id"]))
        ],
    }
    (repo / ASSUMPTION_SIDECAR_REL).write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_status_registry(repo, {"specs/phase-plans-v10.md": "active"})
    _commit_all(repo, "synthetic assumption-probe fixture")
    return repo


def _bind_observation(monkeypatch, module, observation: dict[str, object]) -> None:
    """Bind ONE closed observation payload at the fixed adapter-dispatch
    boundary. The payload is inert data captured in this closure; nothing about
    it is reachable from a public caller-facing argument."""
    payload = json.loads(json.dumps(observation))
    monkeypatch.setattr(module, ASSUMPTION_OBSERVATION_SEAM, lambda repo, probe: payload)


def _live_assumption_block(number: int) -> str:
    """The live numbered assumption block, as committed today."""
    block: list[str] = []
    current: int | None = None
    in_section = False
    for line in _roadmap_text().splitlines():
        if line.startswith("## Assumptions"):
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        if line[:1].isdigit() and line[1:3] == ". ":
            current = int(line[0])
        if current == number:
            block.append(line)
    return "\n".join(block)


@pytest.mark.parametrize("probe", ASSUMPTION_PROBES, ids=[row["id"] for row in ASSUMPTION_PROBES])
def test_assumption_probe_mutation_and_positive_control(probe, tmp_path, monkeypatch):
    # Source injection anchor: the cited literal is really in the roadmap, and
    # in a canonical checkout really inside ITS OWN numbered assumption block.
    _assert_roadmap_contains(probe["anchor"])
    if _canonical_repo_ready():
        block = _live_assumption_block(probe["assumption"])
        assert probe["anchor"] in block, (
            f"{probe['id']}: anchor {probe['anchor']!r} is not inside live assumption "
            f"block {probe['assumption']}"
        )
    try:
        module = importlib.import_module(ASSUMPTION_MODULE)
        audit = _new_symbol(ASSUMPTION_MODULE, "audit_roadmap_assumptions")
        _new_symbol(ASSUMPTION_MODULE, ASSUMPTION_OBSERVATION_SEAM)
    except (ImportError, AttributeError) as exc:
        _red(probe["id"], f"roadmap_assumptions adapter unavailable: {exc}")
        return

    repo = _synthetic_probe_repo(tmp_path)

    # (1) The exact mutation this row's plan-table entry names must be a typed
    # not-ok finding. An adapter (or audit) that answers ok=True for every
    # probe cannot survive this assertion.
    _bind_observation(monkeypatch, module, probe["mutation"])
    mutated = audit(repo, probe_ids=(probe["id"],))
    assert set(mutated) == {probe["id"]}, "probe_ids must select exactly the requested probe"
    verdict = mutated[probe["id"]]
    assert not verdict.ok, (
        f"{probe['id']}: mutation {probe['mutation_id']} must not be reported ok"
    )
    assert verdict.finding is not None, f"{probe['id']}: a not-ok verdict must carry a typed finding"

    # (2) The independent positive control: the same probe, the same public
    # entry point, the currently-true observation, must pass.
    _bind_observation(monkeypatch, module, probe["observation"])
    control = audit(repo, probe_ids=(probe["id"],))
    assert control[probe["id"]].ok, (
        f"{probe['id']}: positive control {probe['positive_control_id']} must pass"
    )

    # (3) Canonical checkout only: the same probe against the live repository
    # and its real adapters, with no boundary bound at all.
    if _canonical_repo_ready():
        monkeypatch.undo()
        live = audit(REPO_ROOT, probe_ids=(probe["id"],))
        assert live[probe["id"]].ok, (
            f"{probe['id']} positive control must pass against live state"
        )


# ===========================================================================
# Group 3 — manifest scope/registration/malformed-path (12 nodeids)
# ===========================================================================

HISTORICAL_PLAN_FILES: tuple[str, ...] = (
    "plans/phase-plan-v1-task-message-sourcebroker-SOURCEBROKER.md",
    "plans/phase-plan-v6-CTXDOCS.md",
    "plans/phase-plan-v6-CTXFREEZE.md",
    "plans/phase-plan-v6-CTXIMPL.md",
    "plans/phase-plan-v6-CTXRELY.md",
    "plans/phase-plan-v6-CTXVERIFY.md",
    "plans/phase-plan-v7-OACONTRACT.md",
    "plans/phase-plan-v7-OACORE.md",
    "plans/phase-plan-v7-OAMOCK.md",
    "plans/phase-plan-v7-OAREAL.md",
    "plans/phase-plan-v7-OARELEASE.md",
)
assert len(HISTORICAL_PLAN_FILES) == 11

ROOT_PLAN_FILES: tuple[str, ...] = (
    "plans/phase-plan-v10-LEGIBLE.md",
    "plans/phase-plan-v10-REVIEWTRUTH.md",
    "plans/phase-plan-v10-PROOFGATE.md",
    "plans/phase-plan-v10-CONFORM.md",
    "plans/phase-plan-v10-FABPUB.md",
    "plans/phase-plan-v10-HARDEN.md",
)


def _manifest_registered_files(manifest_path: Path) -> set[str]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {entry["file"] for entry in data.get("plans", [])}


def _real_manifest_registered_files() -> set[str]:
    return _manifest_registered_files(MANIFEST_PATH)


def _write_historical_plan_files(repo: Path) -> None:
    """Write files at the same eleven closed relative paths HISTORICAL_PLAN_FILES
    names, with plausible frontmatter -- used to exercise manifest/registration
    functions against a synthetic repo when canonical repository bytes (the
    real historical plans under the real ``plans/``) are unavailable."""
    for rel in HISTORICAL_PLAN_FILES:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        alias = Path(rel).stem
        path.write_text(
            f"---\nphase: {alias}\nroadmap: specs/phase-plans-v10.md\n---\n# {alias}\n",
            encoding="utf-8",
        )


def test_unregistered_plan_files_names_all_eleven_in_stable_order(tmp_path):
    # Exercise enumeration against a closed synthetic scope. The integrated
    # repository is required below to register all 28 canonical plans, so it
    # cannot simultaneously serve as an eleven-unregistered positive fixture.
    target_repo = _init_repo(tmp_path)
    _write_historical_plan_files(target_repo)
    _write_all_tracked_roadmaps(target_repo)
    _commit_all(target_repo)
    try:
        unregistered_fn = _new_symbol("phase_loop_runtime.plan_manifest", "unregistered_plan_files")
    except (ImportError, AttributeError) as exc:
        _red("unregistered-plan-files-eleven-stable-order", str(exc))
        return
    result = tuple(unregistered_fn(target_repo))
    assert result == tuple(sorted(HISTORICAL_PLAN_FILES))


def test_register_existing_plan_metadata_is_git_stable(tmp_path):
    if _canonical_repo_ready():
        ancestor_shas = ("bf7d5e0", "c970d7d", "b3d0d72", "9490bdd", "a7b6a4a", "7f97ea9")
        for sha in ancestor_shas:
            proc = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "cat-file", "-t", sha],
                capture_output=True, text=True,
            )
            assert proc.returncode == 0 and proc.stdout.strip() == "commit", f"{sha} is not a real commit"
        target_repo = REPO_ROOT
    else:
        # Installed-wheel clean room: there is no canonical git history to name
        # these specific real ancestor commits from, so prove the identical
        # "dry-run registration is idempotent" contract against a synthetic
        # repo carrying its own real (freshly minted) commit ancestry over the
        # same eleven historical-plan relative paths.
        target_repo = _init_repo(tmp_path)
        _write_historical_plan_files(target_repo)
        _commit_all(target_repo, "historical plans")
        synthetic_sha = subprocess.run(
            ["git", "-C", str(target_repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        proc = subprocess.run(
            ["git", "-C", str(target_repo), "cat-file", "-t", synthetic_sha], capture_output=True, text=True,
        )
        assert proc.returncode == 0 and proc.stdout.strip() == "commit"
    try:
        register_fn = _new_symbol("phase_loop_runtime.plan_manifest", "register_historical_plans")
    except (ImportError, AttributeError) as exc:
        _red("register-existing-plan-metadata-git-stable", str(exc))
        return
    first = register_fn(target_repo, dry_run=True)
    second = register_fn(target_repo, dry_run=True)
    assert first == second, "registration must be byte-identical on rerun"


HISTORICAL_PLAN_LIFECYCLE: dict[str, str] = {
    "plans/phase-plan-v1-task-message-sourcebroker-SOURCEBROKER.md": "completed",
    "plans/phase-plan-v6-CTXFREEZE.md": "completed",
    "plans/phase-plan-v6-CTXIMPL.md": "completed",
    "plans/phase-plan-v6-CTXRELY.md": "completed",
    "plans/phase-plan-v6-CTXDOCS.md": "completed",
    "plans/phase-plan-v6-CTXVERIFY.md": "completed",
    "plans/phase-plan-v7-OAMOCK.md": "completed",
    "plans/phase-plan-v7-OACONTRACT.md": "orphaned",
    "plans/phase-plan-v7-OACORE.md": "orphaned",
    "plans/phase-plan-v7-OAREAL.md": "orphaned",
    "plans/phase-plan-v7-OARELEASE.md": "orphaned",
}
assert set(HISTORICAL_PLAN_LIFECYCLE) == set(HISTORICAL_PLAN_FILES)


def _synthetic_lifecycle_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Build a throwaway repo with REAL Git history over the same eleven closed
    historical-plan relative paths, in the same seven-completed/four-orphaned
    shape the frozen canonical matrix carries: the seven completed plans are
    registered ``completed`` in ``plans/manifest.json`` and carry their own
    later closeout commit, while the four orphaned plans are committed once and
    are never registered or closed out again. This lets the installed-wheel
    clean room exercise the identical public lifecycle audit -- no canonical
    SHA, no canonical ``plans/``/``specs``/``.git``, and no skip."""
    repo = _init_repo(tmp_path)
    roadmap = _write_banner_roadmap(
        repo, "specs/phase-plans-v10.md", BANNER_LINE3["specs/phase-plans-v10.md"]
    )
    _write_historical_plan_files(repo)
    _commit_all(repo, "add eleven historical plans")

    expected: dict[str, str] = {}
    for rel in sorted(HISTORICAL_PLAN_FILES):
        state = HISTORICAL_PLAN_LIFECYCLE[rel]
        expected[rel] = state
        if state != "completed":
            continue
        alias = Path(rel).stem
        append_entry(
            repo,
            DotfilesPlanEntry(
                slug=alias.replace("phase-plan-", ""),
                file=rel,
                type="phase",
                status="completed",
                created_at="2026-06-01T00:00:00Z",
                updated_at="2026-06-02T00:00:00Z",
                owner_skill="codex-plan-phase",
                roadmap_ref=DotfilesPlanRef(
                    slug="phase-plans-v10",
                    file=str(roadmap.relative_to(repo)),
                    type="phase",
                    status="completed",
                ),
                phase_alias=alias,
            ),
        )
        plan_path = repo / rel
        plan_path.write_text(
            plan_path.read_text(encoding="utf-8") + "\n## Closeout\n\ncompleted\n",
            encoding="utf-8",
        )
        _commit_all(repo, f"closeout {rel}")

    assert sorted(expected.values()).count("completed") == 7
    assert sorted(expected.values()).count("orphaned") == 4
    return repo, expected


def test_historical_plan_lifecycle_matrix_is_truthful(tmp_path):
    # LEGIBLE-B2 freezes this exact seven-completed/four-orphaned matrix against
    # the real, specific historical commits of *this* repository
    # (plans/phase-plan-v10-LEGIBLE.md, "The historical lifecycle/evidence matrix
    # is frozen"). A canonical checkout asserts it against those real commits; an
    # installed-wheel clean room, which has none of them, asserts the identical
    # public contract against a synthetic repo carrying its own real Git history
    # in the same shape.
    matrix = dict(HISTORICAL_PLAN_LIFECYCLE)
    assert set(matrix) == set(HISTORICAL_PLAN_FILES)
    if _canonical_repo_ready():
        for sha in ("a7b6a4a", "7f97ea9", "6b77dc3"):
            proc = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "cat-file", "-t", sha], capture_output=True, text=True,
            )
            assert proc.returncode == 0 and proc.stdout.strip() == "commit"
        target_repo, expected = REPO_ROOT, matrix
    else:
        target_repo, expected = _synthetic_lifecycle_repo(tmp_path)
        head = subprocess.run(
            ["git", "-C", str(target_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        proc = subprocess.run(
            ["git", "-C", str(target_repo), "cat-file", "-t", head], capture_output=True, text=True,
        )
        assert proc.returncode == 0 and proc.stdout.strip() == "commit"
    try:
        lifecycle_fn = _new_symbol("phase_loop_runtime.plan_manifest", "historical_plan_lifecycle_matrix")
    except (ImportError, AttributeError) as exc:
        _red("historical-plan-lifecycle-matrix-truthful", str(exc))
        return
    observed = lifecycle_fn(target_repo)
    assert observed == expected


def _synthetic_fully_registered_repo(tmp_path: Path, count: int) -> tuple[Path, tuple[str, ...]]:
    """Build a throwaway repo whose canonical plan scope is exactly ``count``
    files, all registered in its ``plans/manifest.json`` -- for exercising
    ``canonical_plan_files``/``ManifestPresenceReport`` against a synthetic
    exactly-covering manifest when canonical repository bytes are unavailable."""
    repo = _init_repo(tmp_path)
    v10 = _write_banner_roadmap(repo, "specs/phase-plans-v10.md", BANNER_LINE3["specs/phase-plans-v10.md"])
    files = []
    for i in range(count):
        alias = f"SYNTH{i}"
        _add_phase_entry(repo, "v10", alias, "executing", v10)
        files.append(f"plans/phase-plan-v10-{alias}.md")
    _commit_all(repo)
    return repo, tuple(files)


def test_repository_manifest_exactly_covers_execution_scope(tmp_path):
    from phase_loop_runtime.plan_manifest import validate_manifest

    try:
        canonical_fn = _new_symbol("phase_loop_runtime.plan_manifest", "canonical_plan_files")
        report_cls = _new_symbol("phase_loop_runtime.plan_manifest", "ManifestPresenceReport")
    except (ImportError, AttributeError) as exc:
        _red("repository-manifest-exactly-covers-execution-scope", str(exc))
        return
    if _canonical_repo_ready():
        validation = validate_manifest(MANIFEST_PATH)
        assert validation.valid, f"live plans/manifest.json is not currently valid: {validation}"
        canonical = canonical_fn(REPO_ROOT, "HEAD")
        report = report_cls.build(REPO_ROOT, canonical, _real_manifest_registered_files())
    else:
        # Installed-wheel clean room: exercise the identical public contract
        # (an exactly-covering manifest reports zero unregistered files)
        # against a synthetic repo/manifest pair instead of the real one.
        repo, _files = _synthetic_fully_registered_repo(tmp_path, count=3)
        manifest_path = repo / "plans" / "manifest.json"
        validation = validate_manifest(manifest_path)
        assert validation.valid, f"synthetic plans/manifest.json is not valid: {validation}"
        canonical = canonical_fn(repo, "HEAD")
        report = report_cls.build(repo, canonical, _manifest_registered_files(manifest_path))
    assert report.unregistered == ()


def test_integrated_six_root_tree_reports_28_of_28(tmp_path):
    try:
        canonical_fn = _new_symbol("phase_loop_runtime.plan_manifest", "canonical_plan_files")
        report_cls = _new_symbol("phase_loop_runtime.plan_manifest", "ManifestPresenceReport")
    except (ImportError, AttributeError) as exc:
        _red("integrated-six-root-tree-28-of-28", str(exc))
        return
    if _canonical_repo_ready():
        for rel in ROOT_PLAN_FILES:
            assert (REPO_ROOT / rel).is_file(), f"root plan missing from live repo: {rel}"
        canonical = canonical_fn(REPO_ROOT, "HEAD")
        report = report_cls.build(REPO_ROOT, canonical, _real_manifest_registered_files())
        assert report.canonical_count == 28 and report.registered_count == 28 and report.unregistered_count == 0
        return
    # Installed-wheel clean room: exercise the identical public contract (a
    # fully-registered scope reports canonical==registered and zero
    # unregistered) against a synthetic repo instead of asserting the real,
    # repo-specific "28" positive control.
    repo, files = _synthetic_fully_registered_repo(tmp_path, count=4)
    canonical = canonical_fn(repo, "HEAD")
    manifest_path = repo / "plans" / "manifest.json"
    report = report_cls.build(repo, canonical, _manifest_registered_files(manifest_path))
    assert (
        report.canonical_count == len(files)
        and report.registered_count == len(files)
        and report.unregistered_count == 0
    )


def test_untracked_in_scope_plan_absent_from_manifest_blocks(tmp_path):
    repo = _init_repo(tmp_path)
    untracked = repo / "plans" / "phase-plan-v999-UNTRACKED.md"
    untracked.write_text("---\nphase: UNTRACKED\n---\n# Untracked\n", encoding="utf-8")
    assert untracked.lstat().st_mode & 0o170000 == stat.S_IFREG
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard", "plans"],
        capture_output=True, text=True,
    )
    assert "plans/phase-plan-v999-UNTRACKED.md" in proc.stdout.splitlines()
    try:
        check_fn = _new_symbol("phase_loop_runtime.plan_manifest", "check")
    except (ImportError, AttributeError) as exc:
        _red("untracked-in-scope-plan-blocks", str(exc))
        return
    result = check_fn(repo)
    assert result.exit_code != 0
    assert any(item.path == "plans/phase-plan-v999-UNTRACKED.md" and item.origin == "filesystem" for item in result.missing)


def test_index_only_in_scope_plan_absent_from_manifest_blocks(tmp_path):
    repo = _init_repo(tmp_path)
    staged = repo / "plans" / "phase-plan-v999-STAGED.md"
    staged.write_text("---\nphase: STAGED\n---\n# Staged\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "plans/phase-plan-v999-STAGED.md"], check=True)
    staged.unlink()  # index-only: absent from the physical directory and from HEAD
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "--stage", "plans"], capture_output=True, text=True)
    assert "phase-plan-v999-STAGED.md" in proc.stdout
    try:
        check_fn = _new_symbol("phase_loop_runtime.plan_manifest", "check")
    except (ImportError, AttributeError) as exc:
        _red("index-only-in-scope-plan-blocks", str(exc))
        return
    result = check_fn(repo)
    assert result.exit_code != 0
    assert any(item.path == "plans/phase-plan-v999-STAGED.md" and item.origin == "index" for item in result.missing)


# --- the stable LEGIBLE-B1/SL-1 malformed-report vocabulary ----------------
# plans/phase-plan-v10-LEGIBLE.md, LEGIBLE-B1: the `plan-manifest check`
# "nonzero result names every missing, extra, duplicate, malformed,
# conflicted-index, symlink, non-regular, or escaping path". The SL-1 scope
# freeze requires each canonical member to "retain the `head|index|filesystem`
# origin set", and subjects manifest entry paths to "the same
# repo-relative/direct-child/full-match checks before equality" -- so a
# malformed finding produced by a manifest entry carries the `manifest` origin.
# These two closed sets ARE the frozen vocabulary: a report that renames a kind
# or invents an origin flag fails every subcase below.
MANIFEST_MALFORMED_KINDS = frozenset(
    {"noncanonical", "path-escape", "conflicted-index", "symlink", "non-regular", "undecodable-name"}
)
MANIFEST_ORIGIN_FLAGS = frozenset({"head", "index", "filesystem", "manifest"})


class _MalformedExpectation(NamedTuple):
    """One named malformed subcase the report must carry: the exact path bytes
    (compared as ``os.fsencode`` of the reported path, so an undecodable POSIX
    name is matched against its real bytes rather than a lossy rendering), the
    named malformed kind, and the exact source-origin flag set."""

    raw_path: bytes
    kind: str
    origins: frozenset[str]
    label: str


def _finding_origins(finding) -> frozenset[str]:
    """The finding's source-origin flags. The frozen sibling controls above
    compare ``item.origin`` to a single flag, while the SL-1 freeze calls it an
    origin *set*; both spellings of the one frozen attribute are normalized
    here, and the flag values themselves are asserted exactly by the callers."""
    origin = finding.origin
    return frozenset({origin}) if isinstance(origin, str) else frozenset(origin)


def _assert_named_malformed_findings(
    result, expectations: list[_MalformedExpectation], *, forbidden_paths: tuple[str, ...] = ()
) -> None:
    """Require the report to NAME each expected malformed subcase — exact path
    bytes, malformed kind, and origin flags. A bare nonzero exit, a finding for
    some other (e.g. merely unregistered canonical) path, or a differently
    named kind does not satisfy any expectation."""
    assert result.exit_code != 0, "a malformed in-scope path must make the check nonzero"
    findings = tuple(result.malformed)
    rendered = [(finding.path, finding.kind, sorted(_finding_origins(finding))) for finding in findings]
    for finding in findings:
        assert finding.kind in MANIFEST_MALFORMED_KINDS, (
            f"malformed kind outside the frozen LEGIBLE-B1 vocabulary: {finding.kind!r} "
            f"not in {sorted(MANIFEST_MALFORMED_KINDS)}"
        )
        origins = _finding_origins(finding)
        assert origins and origins <= MANIFEST_ORIGIN_FLAGS, (
            f"origin flags outside the frozen vocabulary for {finding.path!r}: "
            f"{sorted(origins)} not a nonempty subset of {sorted(MANIFEST_ORIGIN_FLAGS)}"
        )
    for expected in expectations:
        matches = [
            finding
            for finding in findings
            if os.fsencode(finding.path) == expected.raw_path
            and finding.kind == expected.kind
            and _finding_origins(finding) == expected.origins
        ]
        assert len(matches) == 1, (
            f"{expected.label}: expected exactly one malformed finding naming "
            f"{expected.raw_path!r} with kind {expected.kind!r} and origins "
            f"{sorted(expected.origins)}; got {rendered}"
        )
    for forbidden in forbidden_paths:
        for finding in findings + tuple(result.missing):
            assert forbidden not in finding.path, (
                f"the audit must never resolve or read a symlink target: {finding.path!r} "
                f"names {forbidden!r}"
            )


@pytest.mark.parametrize(
    "malformed_kind",
    ["noncanonical_path", "symlink", "non_stage0_conflicted_index", "undecodable_name", "canonical_looking_non_regular"],
)
def test_manifest_scan_rejects_malformed_path(tmp_path, malformed_kind):
    from phase_loop_runtime.discovery import PLAN_RE

    _assert_plan_contains("malformed/symlink/path-escape controls")
    repo = _init_repo(tmp_path)
    plans_dir = repo / "plans"
    expectations: list[_MalformedExpectation] = []
    forbidden_paths: tuple[str, ...] = ()

    if malformed_kind == "noncanonical_path":
        # (a) a canonical-looking direct child whose basename does not
        # full-match the anchored PLAN_RE, and (b) the explicit path-escape
        # condition, carried by a manifest entry — the SL-1 freeze subjects
        # manifest entry paths to the same direct-child/full-match checks.
        bad = plans_dir / "phase-plan-v999-bad name.md"
        bad.write_text("# bad\n", encoding="utf-8")
        assert stat.S_ISREG(bad.lstat().st_mode)
        assert bad.name.startswith("phase-plan-") and bad.name.endswith(".md")
        assert PLAN_RE.fullmatch(bad.name) is None, "fixture basename must NOT full-match PLAN_RE"
        escaping_entry = "plans/../outside/phase-plan-v999-ESCAPE.md"
        v10 = _write_banner_roadmap(repo, "specs/phase-plans-v10.md", BANNER_LINE3["specs/phase-plans-v10.md"])
        _add_phase_entry(repo, "v10", "REGISTERED", "executing", v10)
        manifest_path = plans_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        escaping = dict(manifest["plans"][-1])
        escaping["slug"] = "v999-ESCAPE"
        escaping["file"] = escaping_entry
        escaping["phase_alias"] = "ESCAPE"
        manifest["plans"].append(escaping)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assert escaping_entry in manifest_path.read_text(encoding="utf-8")
        expectations = [
            _MalformedExpectation(
                os.fsencode("plans/phase-plan-v999-bad name.md"),
                "noncanonical",
                frozenset({"filesystem"}),
                "noncanonical canonical-looking basename",
            ),
            _MalformedExpectation(
                os.fsencode(escaping_entry),
                "path-escape",
                frozenset({"manifest"}),
                "escaping manifest entry path",
            ),
        ]
    elif malformed_kind == "symlink":
        # Both an ordinary in-repo target and an escaping one, neither of which
        # the audit may resolve or read. The ordinary target is deliberately a
        # NON-canonical name outside plans/, so it can never contribute an
        # unrelated missing finding that false-greens this subcase; the
        # escaping target does not exist at all.
        notes = repo / "notes"
        notes.mkdir()
        (notes / "target-not-a-plan.md").write_text("# not a plan\n", encoding="utf-8")
        link = plans_dir / "phase-plan-v999-LINK.md"
        link.symlink_to(Path("..") / "notes" / "target-not-a-plan.md")
        escaping_link = plans_dir / "phase-plan-v999-ESCAPELINK.md"
        escaping_link.symlink_to(Path("..") / ".." / "outside-the-repo.md")
        assert link.is_symlink() and escaping_link.is_symlink()
        assert os.readlink(escaping_link) == os.path.join("..", "..", "outside-the-repo.md")
        assert not escaping_link.exists(), "the escaping target must stay absent: it is never resolved"
        assert PLAN_RE.fullmatch(link.name) and PLAN_RE.fullmatch(escaping_link.name)
        forbidden_paths = ("target-not-a-plan.md", "outside-the-repo.md")
        expectations = [
            _MalformedExpectation(
                os.fsencode("plans/phase-plan-v999-LINK.md"),
                "symlink",
                frozenset({"filesystem"}),
                "symlink with an ordinary in-repo target",
            ),
            _MalformedExpectation(
                os.fsencode("plans/phase-plan-v999-ESCAPELINK.md"),
                "symlink",
                frozenset({"filesystem"}),
                "symlink with an escaping target",
            ),
        ]
    elif malformed_kind == "non_stage0_conflicted_index":
        # A genuine unmerged entry: stages 1/2/3 and NO stage 0, absent from
        # HEAD and from the physical directory, so the finding's only origin is
        # the index arm.
        rel = "plans/phase-plan-v999-CONFLICT.md"
        blobs = []
        for stage_text in ("base\n", "ours\n", "theirs\n"):
            hashed = subprocess.run(
                ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                input=stage_text, capture_output=True, text=True, check=True,
            )
            blobs.append(hashed.stdout.strip())
        index_info = "".join(
            f"100644 {blob} {stage}\t{rel}\n" for stage, blob in enumerate(blobs, start=1)
        )
        subprocess.run(
            ["git", "-C", str(repo), "update-index", "--index-info"],
            input=index_info, text=True, check=True,
        )
        staged = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--stage", "plans"],
            capture_output=True, text=True, check=True,
        ).stdout
        stages = {line.split()[2] for line in staged.splitlines() if line.endswith(rel)}
        assert stages == {"1", "2", "3"}, f"fixture is not a genuine non-stage-0 conflict: {staged!r}"
        assert not (repo / rel).exists()
        expectations = [
            _MalformedExpectation(
                os.fsencode(rel),
                "conflicted-index",
                frozenset({"index"}),
                "non-stage-0 conflicted index entry",
            ),
        ]
    elif malformed_kind == "undecodable_name":
        # A real undecodable POSIX byte name built through the bytes APIs — not
        # a valid Unicode name laundered through latin-1.
        raw_name = b"phase-plan-v999-\xff\xfeBAD.md"
        try:
            raw_name.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:  # pragma: no cover - the fixture bytes are undecodable by construction
            raise AssertionError("fixture filename must not be decodable UTF-8")
        raw_path = os.path.join(os.fsencode(plans_dir), raw_name)
        try:
            with open(raw_path, "wb") as handle:
                handle.write(b"# bad\n")
            listed = os.listdir(os.fsencode(plans_dir))
        except (OSError, ValueError) as exc:
            pytest.fail(
                "this platform cannot represent an undecodable byte filename, so the frozen "
                f"malformed-name control cannot be built here: {type(exc).__name__}: {exc}",
                pytrace=False,
            )
        assert raw_name in listed, (
            "the platform silently transcoded the fixture filename, so no undecodable name "
            f"exists to audit: {listed!r}"
        )
        expectations = [
            _MalformedExpectation(
                b"plans/" + raw_name,
                "undecodable-name",
                frozenset({"filesystem"}),
                "undecodable byte filename",
            ),
        ]
    elif malformed_kind == "canonical_looking_non_regular":
        directory = plans_dir / "phase-plan-v999-DIR.md"
        directory.mkdir()
        assert stat.S_ISDIR(directory.lstat().st_mode)
        assert PLAN_RE.fullmatch(directory.name), "the non-regular entry must look canonical"
        expectations = [
            _MalformedExpectation(
                os.fsencode("plans/phase-plan-v999-DIR.md"),
                "non-regular",
                frozenset({"filesystem"}),
                "canonical-looking directory",
            ),
        ]
        if hasattr(os, "mkfifo"):  # the device/socket arm, where the platform offers one
            fifo = plans_dir / "phase-plan-v999-FIFO.md"
            try:
                os.mkfifo(fifo)
            except OSError:
                pass
            else:
                assert stat.S_ISFIFO(fifo.lstat().st_mode)
                expectations.append(
                    _MalformedExpectation(
                        os.fsencode("plans/phase-plan-v999-FIFO.md"),
                        "non-regular",
                        frozenset({"filesystem"}),
                        "canonical-looking FIFO",
                    )
                )
    else:  # pragma: no cover - exhaustive parametrize
        raise AssertionError(malformed_kind)

    try:
        check_fn = _new_symbol("phase_loop_runtime.plan_manifest", "check")
    except (ImportError, AttributeError) as exc:
        _red(f"manifest-scan-rejects-{malformed_kind}", str(exc))
        return
    result = check_fn(repo)
    _assert_named_malformed_findings(result, expectations, forbidden_paths=forbidden_paths)


# ===========================================================================
# Group 4 — docs-catalog (2 nodeids)
# ===========================================================================


def test_catalog_check_rejects_empty_stale_duplicate_or_disagreeing_catalog(tmp_path):
    try:
        check_catalog = _new_symbol("phase_loop_runtime.docs_freshness", "check_catalog")
    except (ImportError, AttributeError) as exc:
        _red("catalog-check-rejects-empty-stale-duplicate-disagreeing", str(exc))
        return
    if _canonical_repo_ready() and CATALOG_PATH.is_file():
        assert isinstance(json.loads(CATALOG_PATH.read_text(encoding="utf-8")), list)
    empty_repo = _init_repo(tmp_path / "empty-catalog")
    (empty_repo / ".claude").mkdir()
    (empty_repo / ".claude" / "docs-catalog.json").write_text("[]", encoding="utf-8")
    _commit_all(empty_repo)
    empty_result = check_catalog(empty_repo)
    assert empty_result.exit_code != 0, "an empty tracked catalog must fail the explicit check"

    repo = _init_repo(tmp_path)
    (repo / ".claude").mkdir()
    stale = repo / ".claude" / "docs-catalog.json"
    stale.write_text(json.dumps([{"path": "does/not/exist.md"}]), encoding="utf-8")
    _commit_all(repo)
    stale_result = check_catalog(repo)
    assert stale_result.exit_code != 0

    duplicate = repo / ".claude" / "docs-catalog.json"
    real_doc = repo / "docs" / "real.md"
    real_doc.parent.mkdir(parents=True, exist_ok=True)
    real_doc.write_text("# Real\n", encoding="utf-8")
    duplicate.write_text(json.dumps([{"path": "docs/real.md"}, {"path": "docs/real.md"}]), encoding="utf-8")
    _commit_all(repo, "duplicate")
    duplicate_result = check_catalog(repo)
    assert duplicate_result.exit_code != 0


def test_catalog_rescan_is_stable_sorted_idempotent_and_never_invents_positive_count_from_empty(tmp_path):
    if _canonical_repo_ready() and CATALOG_PATH.is_file():
        assert isinstance(json.loads(CATALOG_PATH.read_text(encoding="utf-8")), list)
    try:
        rescan_catalog = _new_symbol("phase_loop_runtime.docs_freshness", "rescan_catalog")
        entry_count = _new_symbol("phase_loop_runtime.docs_freshness", "docs_catalog_entry_count")
    except (ImportError, AttributeError) as exc:
        _red("catalog-rescan-stable-idempotent-never-invents-count", str(exc))
        return
    repo = _init_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "docs-catalog.json").write_text("[]", encoding="utf-8")
    _commit_all(repo)
    assert entry_count(repo) == 0, "an empty catalog must never report a positive count"

    docs_dir = repo / "docs"
    docs_dir.mkdir()
    (docs_dir / "b.md").write_text("# B\n", encoding="utf-8")
    (docs_dir / "a.md").write_text("# A\n", encoding="utf-8")
    first = rescan_catalog(repo)
    second = rescan_catalog(repo)
    assert first == second, "rescan must be idempotent"
    assert list(first) == sorted(first), "rescan must be stable path-sorted"


# ===========================================================================
# Frozen nodeid inventory (LEGIBLE-A0)
# ===========================================================================

LEGIBLE_EXPECTED_NODEIDS_V1: tuple[str, ...] = tuple(sorted([
    "tests/test_legible_roadmap_contract.py::test_status_coherence_rejects_active_registry_with_superseded_do_not_execute_banner",
    "tests/test_legible_roadmap_contract.py::test_status_coherence_rejects_superseded_registry_with_active_banner",
    "tests/test_legible_roadmap_contract.py::test_status_coherence_rejects_delivered_and_checkbox_drift",
    "tests/test_legible_roadmap_contract.py::test_status_coherence_rejects_missing_malformed_ambiguous_or_misplaced_banner",
    "tests/test_legible_roadmap_contract.py::test_status_registry_exactly_covers_tracked_roadmaps",
    "tests/test_legible_roadmap_contract.py::test_status_positive_controls_kill_hardwired_active_or_none",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[explicit]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[authority]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[state]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[manifest]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[handoff]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[singleton-glob]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[manifest-disabled]",
    "tests/test_legible_roadmap_contract.py::test_superseded_selector_paths_fail_closed[completed-hatch]",
    "tests/test_legible_roadmap_contract.py::test_absent_registry_selector_rejects_recognized_non_active_banner_and_preserves_no_declaration_legacy",
    "tests/test_legible_roadmap_contract.py::test_legacy_repo_without_roadmap_status_registry_preserves_selection",
    "tests/test_legible_roadmap_contract.py::test_registry_present_with_empty_partial_or_malformed_bytes_is_not_treated_as_absent",
    "tests/test_legible_roadmap_contract.py::test_validate_roadmap_missing_registry_negative_control",
    "tests/test_legible_roadmap_contract.py::test_declared_active_roadmap_missing_registry_negative_control",
    "tests/test_legible_roadmap_contract.py::test_roadmap_status_error_hierarchy_distinguishes_malformed_registry_and_banner_and_coherence_and_selection_errors",
    "tests/test_legible_roadmap_contract.py::test_read_roadmap_status_validates_full_coverage_before_returning_any_value",
    "tests/test_legible_roadmap_contract.py::test_canonical_validate_roadmap_calls_coherence_validator_with_required_true",
    "tests/test_legible_roadmap_contract.py::test_registry_rejects_noncanonical_or_escaping_path_and_selected_active_mismatch",
    "tests/test_legible_roadmap_contract.py::test_read_roadmap_status_returns_none_when_registry_absent",
    "tests/test_legible_roadmap_contract.py::test_manifest_reporting_consumes_coherence_checked_accessor",
    "tests/test_legible_roadmap_contract.py::test_declared_active_roadmap_returns_registry_and_banner_active_v10_path",
    "tests/test_legible_roadmap_contract.py::test_parse_roadmap_banner_status_positive_control_all_thirteen_tracked_banners_parse",
] + [
    f"tests/test_legible_roadmap_contract.py::test_assumption_probe_mutation_and_positive_control[{row['id']}]"
    for row in ASSUMPTION_PROBES
] + [
    "tests/test_legible_roadmap_contract.py::test_unregistered_plan_files_names_all_eleven_in_stable_order",
    "tests/test_legible_roadmap_contract.py::test_register_existing_plan_metadata_is_git_stable",
    "tests/test_legible_roadmap_contract.py::test_historical_plan_lifecycle_matrix_is_truthful",
    "tests/test_legible_roadmap_contract.py::test_repository_manifest_exactly_covers_execution_scope",
    "tests/test_legible_roadmap_contract.py::test_integrated_six_root_tree_reports_28_of_28",
    "tests/test_legible_roadmap_contract.py::test_untracked_in_scope_plan_absent_from_manifest_blocks",
    "tests/test_legible_roadmap_contract.py::test_index_only_in_scope_plan_absent_from_manifest_blocks",
    "tests/test_legible_roadmap_contract.py::test_manifest_scan_rejects_malformed_path[noncanonical_path]",
    "tests/test_legible_roadmap_contract.py::test_manifest_scan_rejects_malformed_path[symlink]",
    "tests/test_legible_roadmap_contract.py::test_manifest_scan_rejects_malformed_path[non_stage0_conflicted_index]",
    "tests/test_legible_roadmap_contract.py::test_manifest_scan_rejects_malformed_path[undecodable_name]",
    "tests/test_legible_roadmap_contract.py::test_manifest_scan_rejects_malformed_path[canonical_looking_non_regular]",
    "tests/test_legible_roadmap_contract.py::test_catalog_check_rejects_empty_stale_duplicate_or_disagreeing_catalog",
    "tests/test_legible_roadmap_contract.py::test_catalog_rescan_is_stable_sorted_idempotent_and_never_invents_positive_count_from_empty",
]))

assert len(LEGIBLE_EXPECTED_NODEIDS_V1) == 64, len(LEGIBLE_EXPECTED_NODEIDS_V1)
