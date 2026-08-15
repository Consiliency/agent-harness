"""EC-GOVLEAN-7 / IF-0-GOVLEAN-5 — fleet planner/roadmap policy parity.

Reads fleet sources and the eventual generated/package copies. It does not
modify those trees. Falsified when any planner or roadmap variant omits a
required content/behavior policy clause, or when generated/package copies
lag the same clauses.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .govlean_freeze_receipt import govlean_api_available

REPO = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO / "skills-src"
GENERATED_BUNDLE = REPO / "phase-loop-skills"
PACKAGED_BUNDLE = (
    REPO / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "skills_bundle"
)

HARNESSES = ("claude", "codex", "gemini", "opencode")
PLANNER_ROADMAP_SKILLS = ("plan-phase", "phase-roadmap-builder")
EXECUTE_PHASE_SKILL = "execute-phase"

# Distinctive IF-0-GOVLEAN-5 / EC-GOVLEAN-7 clauses. Each marker is a set of
# required substrings that must appear together so a partial paraphrase cannot
# vacuous-pass the rest of the policy.
POLICY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "content-behavior-falsifiers",
        ("content and behavior", "never commit topology"),
    ),
    (
        "external-only-pins",
        ("declared external inputs",),
    ),
    (
        "plan-size-budget",
        ("3000-word", "justification required above it"),
    ),
    (
        "sol-cross-vendor-ablation",
        ("cross-vendor ablation", "Sol-authored"),
    ),
    (
        "proof-cost-findings",
        (
            "single node over roughly five minutes",
            "unable to report multiple failures",
        ),
    ),
)


def _source_policy_present() -> bool:
    canonical = SKILLS_SRC / "claude" / "claude-plan-phase" / "SKILL.md"
    if not canonical.is_file():
        return False
    text = canonical.read_text(encoding="utf-8").lower()
    return "content and behavior" in text and "never commit topology" in text


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.plan_manifest", "IssueDisposition")
    and not _source_policy_present(),
    reason="GOVLEAN fleet prose policy absent",
)


def _require_skill_trees() -> None:
    if not SKILLS_SRC.is_dir():
        pytest.skip("canonical skills-src/ sources absent (from-wheel layout)")
    if not GENERATED_BUNDLE.is_dir():
        pytest.skip("committed phase-loop-skills/ absent (from-wheel layout)")
    if not PACKAGED_BUNDLE.is_dir():
        pytest.skip("packaged skills_bundle/ absent (from-wheel layout)")


def _source_skill(harness: str, skill: str) -> Path:
    return SKILLS_SRC / harness / f"{harness}-{skill}" / "SKILL.md"


def _generated_skill(skill: str) -> Path:
    return GENERATED_BUNDLE / skill / "SKILL.md"


def _packaged_skill(harness: str, skill: str) -> Path:
    return PACKAGED_BUNDLE / f"{harness}-{skill}" / "SKILL.md"


def _source_inventory() -> list[tuple[str, Path]]:
    return [
        (f"skills-src/{harness}/{harness}-{skill}/SKILL.md", _source_skill(harness, skill))
        for skill in PLANNER_ROADMAP_SKILLS
        for harness in HARNESSES
    ]


def _execute_phase_source_inventory() -> list[tuple[str, Path]]:
    return [
        (
            f"skills-src/{harness}/{harness}-{EXECUTE_PHASE_SKILL}/SKILL.md",
            _source_skill(harness, EXECUTE_PHASE_SKILL),
        )
        for harness in HARNESSES
    ]


def _generated_inventory() -> list[tuple[str, Path]]:
    return [
        (f"phase-loop-skills/{skill}/SKILL.md", _generated_skill(skill))
        for skill in PLANNER_ROADMAP_SKILLS
    ]


def _packaged_inventory() -> list[tuple[str, Path]]:
    return [
        (
            f"skills_bundle/{harness}-{skill}/SKILL.md",
            _packaged_skill(harness, skill),
        )
        for skill in PLANNER_ROADMAP_SKILLS
        for harness in HARNESSES
    ]


def _present_markers(text: str) -> set[str]:
    lowered = text.lower()
    present: set[str] = set()
    for marker, fragments in POLICY_MARKERS:
        if all(fragment.lower() in lowered for fragment in fragments):
            present.add(marker)
    return present


def _assert_policy_markers(label: str, path: Path) -> None:
    assert path.is_file(), f"{label} is missing"
    present = _present_markers(path.read_text(encoding="utf-8"))
    expected = {marker for marker, _fragments in POLICY_MARKERS}
    assert present == expected, (
        f"{label} is missing GOVLEAN planner/roadmap policy marker(s): "
        f"{sorted(expected - present)}"
    )


@pytest.mark.parametrize(
    ("label", "path"),
    _source_inventory(),
    ids=[label for label, _path in _source_inventory()],
)
def test_fleet_source_planner_roadmap_skills_state_govlean_policy(
    label: str, path: Path
) -> None:
    _require_skill_trees()
    _assert_policy_markers(label, path)


@pytest.mark.parametrize(
    ("label", "path"),
    _execute_phase_source_inventory(),
    ids=[label for label, _path in _execute_phase_source_inventory()],
)
def test_execute_phase_completed_lifecycle_enrolls_issue_closeout_arrays(
    label: str, path: Path
) -> None:
    _require_skill_trees()
    assert path.is_file(), f"{label} is missing"
    text = path.read_text(encoding="utf-8")
    lifecycle = text.split("### Manifest lifecycle", 1)[-1].split("\n### ", 1)[0]
    assert lifecycle != text, f"{label} is missing its Manifest lifecycle section"
    closeout = lifecycle.split("During closeout", 1)[-1].split("\n\n", 1)[0]
    assert closeout != lifecycle, f"{label} is missing its closeout caller contract"
    assert "completed" in closeout, f"{label} does not describe completed closeout"
    for field in ("issue_inventory", "issue_dispositions"):
        assert field in closeout, (
            f"{label} completed lifecycle caller omits mandatory {field}"
        )


@pytest.mark.parametrize(
    ("label", "path"),
    _generated_inventory(),
    ids=[label for label, _path in _generated_inventory()],
)
def test_generated_planner_roadmap_skills_state_govlean_policy(
    label: str, path: Path
) -> None:
    _require_skill_trees()
    _assert_policy_markers(label, path)


@pytest.mark.parametrize(
    ("label", "path"),
    _packaged_inventory(),
    ids=[label for label, _path in _packaged_inventory()],
)
def test_packaged_planner_roadmap_skills_state_govlean_policy(
    label: str, path: Path
) -> None:
    _require_skill_trees()
    _assert_policy_markers(label, path)


@pytest.mark.parametrize("skill", PLANNER_ROADMAP_SKILLS)
def test_planner_roadmap_source_variants_agree_on_policy_markers(skill: str) -> None:
    _require_skill_trees()
    by_harness = {
        harness: _present_markers(_source_skill(harness, skill).read_text(encoding="utf-8"))
        for harness in HARNESSES
    }
    expected = {marker for marker, _fragments in POLICY_MARKERS}
    for harness, present in by_harness.items():
        assert present == expected, (
            f"skills-src/{harness}/{harness}-{skill}/SKILL.md policy markers "
            f"{sorted(present)} disagree with required {sorted(expected)}"
        )
    unique = {frozenset(present) for present in by_harness.values()}
    assert len(unique) == 1, (
        f"{skill} harness variants disagree on GOVLEAN policy markers: {by_harness}"
    )


def test_source_generated_and_packaged_policy_markers_stay_aligned() -> None:
    """Eventual generated/package parity: every layer carries the same clauses."""
    _require_skill_trees()
    expected = {marker for marker, _fragments in POLICY_MARKERS}
    observed: dict[str, set[str]] = {}
    for label, path in (
        *_source_inventory(),
        *_generated_inventory(),
        *_packaged_inventory(),
    ):
        observed[label] = _present_markers(path.read_text(encoding="utf-8"))
    drifted = {
        label: sorted(markers)
        for label, markers in observed.items()
        if markers != expected
    }
    assert drifted == {}, (
        "planner/roadmap policy markers drifted across source/generated/package "
        f"layers: {drifted}"
    )
