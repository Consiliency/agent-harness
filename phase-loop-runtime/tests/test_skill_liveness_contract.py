"""The advisor-board skills must not describe a HARD DEADLINE as a stall bound.

agent-harness#727. `timeouts_by_leg` is honoured as a hard wall-clock deadline that
REPLACES the runtime's generous backstop (`panel_invoker._leg_deadline_from`: an explicit
value returns `(timeout_s, timeout_s)`; only the input-scaled default is raised to
`_MAX_LEG_TIMEOUT_S`). The skill previously told operators to pass it "to BOUND a
slow/stalled leg", which conflates two different controls:

* **stall reclamation** — heartbeat extinction, automatic, already handles a dead leg;
* **a hard ceiling** — a caller policy that fires even while the leg is healthy.

Reaching for the second because you observed the first converts a recoverable stall into a
guaranteed kill. That is not hypothetical: it is how several governed panels in this repo were
killed by their own callers, including panels whose parent process died before any verdict was
written.

The same fact lives in SIXTEEN places — four canonical `skills-src/<harness>/` sources, four
generated `phase-loop-skills/` outputs, and the eight wheel-shipped `skills_bundle/` copies
(four boards plus their `advisor-panel` aliases) that a pinned install actually reads — so
this asserts by OCCURRENCE across every site rather than spot-checking one file. That is the ah#693 shape: one fact stated in several
places drifts silently, and a `grep -l` sweep reports a file as covered when only its first
mention was fixed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The operator-facing claim that must accompany every mention of the override.
REQUIRED_WARNING = "HARD DEADLINE, not a stall threshold"

#: Prose that actively misleads: it invites the override as a fix for a stall.
FORBIDDEN = "BOUND a slow/stalled leg"

#: Heartbeat semantics an operator needs in order to tell the two failures apart.
#:
#: These are PHRASES that carry the claim, not scattered keywords. A first version listed
#: "heartbeat" / "stdout" / "stderr" / "backstop", and stripping the mechanism from all
#: eight sites still passed — those words occur incidentally elsewhere in the same section,
#: so the check tested vocabulary rather than meaning.
REQUIRED_SEMANTICS = (
    "stdout/stderr byte",   # what actually counts as a heartbeat
    "process-group CPU",    # the secondary, extend-only signal
    "REPLACES the backstop",  # what an explicit override does to the default
)


def _skill_sites() -> list[Path]:
    """Every surface that carries the section: THREE layers, not two.

        skills-src/  ->  phase-loop-skills/  ->  src/phase_loop_runtime/skills_bundle/

    The third layer ships in the wheel and is what a pinned `pip install` actually
    reads (`skill_inventory.resolve_source_skill_dir` falls back to package data).
    The first version of this test globbed only the first two layers -- eight
    sites -- and reported green while all eight packaged copies, including the
    `advisor-panel` aliases, still carried the old guidance. That is the ah#693
    shape exactly: a corrected contract that never reaches the surface operators
    read. Cross-vendor review caught it; this file had not.
    """
    sites = sorted(REPO_ROOT.glob("skills-src/*/*-advisor-board/SKILL.md"))
    sites += sorted(REPO_ROOT.glob("phase-loop-skills/advisor-board/SKILL.md"))
    sites += sorted(REPO_ROOT.glob("phase-loop-skills/advisor-board/_overrides/*/SKILL.md"))
    sites += sorted(REPO_ROOT.glob(
        "phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-*/SKILL.md"
    ))
    return sites


def test_the_sites_are_discovered_at_all() -> None:
    """A sweep that finds nothing passes every other assertion vacuously."""
    sites = _skill_sites()
    packaged = [s for s in sites if "skills_bundle" in str(s)]
    assert len(sites) >= 16, f"expected 4 sources + 4 generated + 8 packaged, found {len(sites)}"
    assert len(packaged) >= 8, (
        "the wheel-shipped copies (4 boards + 4 panel aliases) must be swept; "
        f"found {len(packaged)}"
    )


@pytest.mark.parametrize("site", _skill_sites(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_mention_of_the_override_carries_the_hard_deadline_warning(site: Path) -> None:
    text = site.read_text(encoding="utf-8")
    mentions = len(re.findall(r"timeouts_by_leg", text))
    if not mentions:
        pytest.skip("this surface does not mention the override")
    # Counted by OCCURRENCE, not presence: a file may describe the override twice.
    warnings = len(re.findall(re.escape(REQUIRED_WARNING), text))
    assert warnings >= 1, (
        f"{site.relative_to(REPO_ROOT)} mentions timeouts_by_leg {mentions}x but never says "
        f"it is a {REQUIRED_WARNING!r} that replaces the backstop"
    )


@pytest.mark.parametrize("site", _skill_sites(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_site_invites_the_override_as_a_stall_fix(site: Path) -> None:
    text = " ".join(site.read_text(encoding="utf-8").split())
    assert FORBIDDEN not in text, (
        f"{site.relative_to(REPO_ROOT)} still tells operators to use timeouts_by_leg to "
        f"{FORBIDDEN!r}; stalls are reclaimed by heartbeat extinction, and an override "
        f"shorter than the real work guarantees the kill it was meant to prevent"
    )


SECTION = re.compile(r"^## Bounding A Slow Leg$.*?(?=^## )", re.M | re.S)


def _section(site: Path) -> str:
    found = SECTION.search(site.read_text(encoding="utf-8"))
    assert found, f"{site} has no 'Bounding A Slow Leg' section"
    return found.group(0)


@pytest.mark.parametrize("site", _skill_sites(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_heartbeat_semantics_are_described(site: Path) -> None:
    # Scoped to the SECTION, not the whole file. Scanning the file passed while the
    # section itself lost the detail, because these words occur elsewhere — a
    # mutation deleting the mechanism from the section killed only the drift test.
    text = _section(site).lower()
    if "timeouts_by_leg" not in text:
        pytest.skip("this surface does not mention the override")
    missing = [w for w in REQUIRED_SEMANTICS if w.lower() not in text]
    assert not missing, (
        f"{site.relative_to(REPO_ROOT)} describes the override without the semantics needed "
        f"to tell a heartbeat stall from a hard-deadline expiry; missing: {missing}"
    )


def test_generated_copies_match_their_canonical_sources() -> None:
    """The generated bundle is regenerated from `skills-src/`, so the section must agree.

    Without this, a source fix silently fails to reach the surface operators actually read —
    which is the half of ah#693 that made a corrected contract look shipped.
    """
    bodies = {}
    for site in _skill_sites():
        bodies.setdefault(" ".join(_section(site).split()), []).append(
            str(site.relative_to(REPO_ROOT))
        )
    assert len(bodies) == 1, (
        "the 'Bounding A Slow Leg' section differs across sites; regenerate the bundle from "
        f"skills-src. Variants: { {k[:60]: v for k, v in bodies.items()} }"
    )
