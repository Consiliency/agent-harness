"""agent-harness#1301: the skill-reflection loop must read what it writes.

Each test pins one break from the issue: scope (execute-detailed, claude-*,
advisor-panel), the `What didn't` section, the threshold trigger, the capture
quality filter, archival, and the planner/editor prose that drives the loop.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from phase_loop_runtime import reflection_corpus as rc
from phase_loop_runtime.events import read_events
from phase_loop_runtime.maintenance import MaintenanceOptions, collect_reflection_inventory, run_maintenance
from phase_loop_test_utils import make_repo

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO_ROOT / "skills-src"


def reflection(worked="Read the target first.", didnt="Edge case X surprised the run.", improvements="Add a step that checks X.", *, didnt_heading="What didn't", stamp="2026-10-01T00:00:00Z"):
    return (
        f"# reflection\n\n## Run context\nSkill: s\nTimestamp: {stamp}\n\n"
        f"## What worked\n{worked}\n\n## {didnt_heading}\n{didnt}\n\n## Improvements to SKILL.md\n{improvements}\n"
    )


def put(root: Path, skill: str, repo_hash: str, branch: str, name: str, text: str) -> Path:
    path = root / skill / "reflections" / repo_hash / branch / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_scope_includes_execute_detailed_claude_and_advisor_panel(home):
    codex, claude = home / ".codex" / "skills", home / ".claude" / "skills"
    put(codex, "codex-execute-detailed", "h1", "b1", "r1", reflection())
    put(codex, "codex-execute-detailed", "h1", "b2", "r2", reflection(didnt="Another surprise."))
    put(codex, "claude-plan-detailed", "h2", "b1", "r3", reflection(didnt="Third surprise."))
    put(claude, "claude-plan-phase", "h3", "b1", "r4", reflection(didnt="Fourth surprise."))
    put(codex, "codex-advisor-panel", "h4", "b1", "r5", reflection(didnt="Fifth surprise."))

    inventory = collect_reflection_inventory(home)

    assert inventory["total"] == 5
    assert inventory["by_skill"] == {"advisor-board": 1, "execute-detailed": 2, "plan-detailed": 1, "plan-phase": 1}
    assert inventory["ready_skills"] == ["execute-detailed"]
    assert inventory["due"] is True


def test_what_didnt_reaches_the_bundle_including_did_not_variant(tmp_path):
    root = tmp_path / "skills"
    put(root, "codex-plan-phase", "h", "b1", "r1", reflection(didnt="FRICTION-ALPHA happened."))
    put(root, "codex-plan-phase", "h", "b2", "r2", reflection(didnt="FRICTION-BETA happened.", didnt_heading="What did not"))

    corpus, _ = rc.collect([root])
    bundle = rc.render_bundle(corpus)

    assert "FRICTION-ALPHA" in bundle and "FRICTION-BETA" in bundle
    assert bundle.count("**What didn't**") == 2


def test_exact_and_near_duplicates_collapse(tmp_path):
    root = tmp_path / "skills"
    body = reflection(didnt="Line one of friction.\nLine two of friction.\nLine three of friction.\nLine four.")
    put(root, "codex-execute-detailed", "h", "b", "r1", body)
    put(root, "codex-execute-detailed", "h", "b", "r2", body)
    put(root, "codex-execute-detailed", "h", "b", "r3", body.replace("Line four.", "Line four, amended."))

    corpus, _ = rc.collect([root])

    assert len(corpus.admitted) == 1
    assert sorted(r.excluded.split(":")[0] for r in corpus.scanned if r.excluded) == ["duplicate_of", "duplicate_of"]


def test_boilerplate_is_stripped_before_the_repo_agnostic_gate(tmp_path):
    root = tmp_path / "skills"
    copied = "Lifecycle reconciliation remains under some-repo#361; nothing is rewritten here."
    for index in range(3):
        put(root, "codex-plan-detailed", "h", f"b{index}", "r", reflection(
            didnt=f"Distinct friction {index}.",
            improvements=f"{copied}\nDistinct generic proposal {index}.",
        ))
    put(root, "codex-plan-detailed", "h", "b9", "r", reflection(didnt="Own friction.", improvements="Fix the bug tracked in other-repo#12."))
    put(root, "codex-plan-detailed", "h", "b8", "r", reflection(didnt=copied, improvements="None."))

    corpus, boilerplate = rc.collect([root])
    reasons = {r.branch_slug: r.excluded for r in corpus.scanned}

    assert boilerplate == [copied]
    assert reasons["b0"] is None and reasons["b1"] is None and reasons["b2"] is None
    assert "some-repo#361" not in rc.render_bundle(corpus)
    assert reasons["b9"] == "improvements_repo_specific"
    assert reasons["b8"] == "no_friction_or_proposal"


def test_improvements_classification():
    assert rc.classify_improvements("None.") == "none"
    assert rc.classify_improvements("No skill edits are proposed.") == "none"
    assert rc.classify_improvements("None required. Inspect argument semantics first.") == "agnostic"
    assert rc.classify_improvements("Track in Consiliency/agent-harness#1.") == "repo_specific"
    assert rc.classify_improvements("Write to ~/.codex/skills/<skill>/reflections/.") == "agnostic"
    assert rc.classify_improvements("Read /home/someone/repo/file.py first.") == "repo_specific"


def test_ledger_detail_is_redacted():
    text = "Publication result: {\"status\": \"published\"}\nHosted CI: success\nRan /mnt/workspace/x/y.json at " + "a" * 40 + " see https://example.com/z"
    assert rc.redact(text) == "Ran <path> at <sha> see <url>"


def test_per_branch_cap_keeps_newest(tmp_path):
    root = tmp_path / "skills"
    for day in range(1, 6):
        put(root, "codex-execute-detailed", "h", "busy", f"r{day}", reflection(didnt=f"Unique friction on day {day}.", stamp=f"2026-10-0{day}T00:00:00Z"))

    corpus, _ = rc.collect([root], per_branch_cap=2)

    assert sorted(r.run_id for r in corpus.admitted) == ["r4", "r5"]


def test_archive_moves_consumed_and_next_collect_skips_them(tmp_path):
    root = tmp_path / "skills"
    first = put(root, "codex-plan-phase", "h", "b", "r1", reflection())
    put(root, "codex-plan-phase", "h", "b2", "r2", reflection(didnt="Other."))
    corpus, boilerplate = rc.collect([root])
    out = rc.write_corpus(corpus, boilerplate, tmp_path / "out")

    assert rc.archive([first], dry_run=True) == [(first, first.parent / "archive" / "r1.md")]
    assert first.exists()
    assert rc.main(["archive", "--manifest", str(out["manifest"])]) == 0

    assert (first.parent / "archive" / "r1.md").exists() and not first.exists()
    assert rc.collect([root])[0].scanned == []
    with pytest.raises(ValueError):
        rc.archive_target(first.parent / "archive" / "r1.md")


def test_maintain_skills_skips_launch_below_threshold(tmp_path, home):
    repo = make_repo(tmp_path)
    put(home / ".codex" / "skills", "codex-execute-detailed", "h", "b", "r1", reflection())

    snapshot, results = run_maintenance(repo, repo / "specs" / "phase-plans-v1.md", MaintenanceOptions(min_reflections=2), dry_run=True)

    assert results == []
    event = read_events(repo)[-1]
    assert event["status"] == "plan_skipped"
    assert event["metadata"]["reflection_inventory"]["due"] is False


def test_maintain_skills_hands_the_planner_a_filtered_corpus(tmp_path, home):
    repo = make_repo(tmp_path)
    for branch in ("b1", "b2"):
        put(home / ".codex" / "skills", "codex-execute-detailed", "h", branch, "r", reflection(didnt=f"Friction on {branch}."))

    snapshot, results = run_maintenance(repo, repo / "specs" / "phase-plans-v1.md", MaintenanceOptions(min_reflections=2), dry_run=True)

    command = " ".join(results[0].command)
    match = re.search(r"--corpus (\S+)", command)
    assert "codex-skill-improvement-planner --min-reflections 2" in command and match
    corpus_dir = Path(match.group(1))
    assert "Friction on b1." in (corpus_dir / "bundle.md").read_text()
    assert len(json.loads((corpus_dir / "manifest.json").read_text())["reflections_consumed"]) == 2


# --- prose enforcer: the skill text that drives the loop must match the collector.

PLANNERS = sorted(SKILLS_SRC.glob("*/*-skill-improvement-planner/SKILL.md"))
EDITORS = sorted(SKILLS_SRC.glob("*/*-skill-editor/SKILL.md"))
DEAD_PATHS = re.compile(r"\b(?:codex|claude|gemini|opencode)-config/|vendor/phase-loop-skills|end-of-v36 cutover")


@pytest.mark.parametrize("planner", PLANNERS, ids=lambda p: p.parent.name)
def test_planner_prose_covers_full_scope_and_what_didnt(planner):
    text = planner.read_text()
    harness = planner.parent.name.split("-")[0]
    missing = [skill for skill in rc.IN_SCOPE_SKILLS if f"{harness}-{skill}" not in text]
    assert not missing, f"{planner} omits {missing}"
    assert "What didn't" in text
    assert "phase_loop_runtime.reflection_corpus" in text


@pytest.mark.parametrize("skill_md", PLANNERS + EDITORS, ids=lambda p: p.parent.name)
def test_planner_and_editor_target_skills_src(skill_md):
    text = skill_md.read_text()
    assert not DEAD_PATHS.findall(text), f"{skill_md} points at a path that does not exist"
    assert "skills-src/" in text


def test_aggregator_prompt_reads_four_sections():
    prompt = (SKILLS_SRC / "claude" / "claude-skill-improvement-planner" / "assets" / "aggregator_prompt.md").read_text()
    assert "two sections" not in prompt
    assert "What didn't" in prompt


def test_scan_sets_are_non_empty():
    assert len(PLANNERS) == 4 and len(EDITORS) == 4
