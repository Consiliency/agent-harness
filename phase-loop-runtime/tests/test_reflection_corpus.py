"""agent-harness#1301: the skill-reflection loop must read what it writes.

Each test pins one break from the issue: scope (execute-detailed, claude-*,
advisor-panel), the `What didn't` section, the threshold trigger, the capture
quality filter, archival, and the planner/editor prose that drives the loop.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
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
    monkeypatch.delenv("PHASE_LOOP_SKILL_BUNDLE", raising=False)
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


def test_unstructured_headings_cannot_open_bundle_sections(tmp_path):
    root = tmp_path / "skills"
    put(root, "codex-execute-phase", "h", "b", "r1", "# Title\n\n## Remaining work\nLoose notes about friction.\n")

    bundle = rc.render_bundle(rc.collect([root])[0])

    assert [line for line in bundle.splitlines() if line.startswith("## ")] == ["## execute-phase (1 reflections)"]
    assert "**Remaining work**" in bundle and "Loose notes about friction." in bundle


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


def test_identical_reports_from_independent_runs_both_count(tmp_path):
    root = tmp_path / "skills"
    same = reflection(didnt="The validator rejected the template lane index.")
    put(root, "codex-plan-phase", "repoA", "b", "r1", same)
    put(root, "codex-plan-phase", "repoB", "b", "r1", same)

    corpus, _ = rc.collect([root])

    assert len(corpus.admitted) == 2 and corpus.ready_skills() == ["plan-phase"]


def test_a_line_repeated_across_repos_is_evidence_not_boilerplate(tmp_path):
    root = tmp_path / "skills"
    friction = "Closeout audit blocked on ignored outputs this run did not create."
    for repo in ("r1", "r2", "r3"):
        put(root, "codex-execute-phase", repo, "b", "x", reflection(didnt=f"{friction}\nOther detail from {repo}."))

    corpus, boilerplate = rc.collect([root])

    assert boilerplate == []
    assert rc.render_bundle(corpus).count(friction) == 3


def test_under_threshold_skills_are_not_consumed(tmp_path):
    root = tmp_path / "skills"
    put(root, "codex-plan-phase", "h", "b1", "r", reflection(didnt="Ready one."))
    put(root, "codex-plan-phase", "h", "b2", "r", reflection(didnt="Ready two."))
    lone = put(root, "codex-execute-detailed", "h", "b1", "r", reflection(didnt="Only one so far."))
    repo_specific = put(root, "codex-execute-detailed", "h", "b2", "r", reflection(didnt="Copied.", improvements="Fix other-repo#3."))

    corpus, boilerplate = rc.collect([root])
    consumed = rc.manifest(corpus, boilerplate)["reflections_consumed"]

    assert str(lone) not in consumed
    # Its What didn't is still evidence (agent-harness#1371), so it waits in place.
    assert str(repo_specific) not in consumed
    assert len(consumed) == 2


def test_consumption_is_ready_admitted_plus_duplicates_and_empty_reports(tmp_path):
    root = tmp_path / "skills"
    ready = [put(root, "codex-plan-phase", "h", f"b{i}", "r", reflection(didnt=f"Ready friction {i}.")) for i in (1, 2)]
    duplicate = put(root, "codex-plan-phase", "h", "b1", "s", reflection(didnt="Ready friction 1.", stamp="2026-10-02T00:00:00Z"))
    empty = put(root, "codex-plan-phase", "h", "b3", "r", reflection(didnt="", improvements="None."))
    ready_repo_specific = put(root, "codex-plan-phase", "h", "b4", "r", reflection(improvements="Fix other-repo#3."))
    capped = [
        put(root, "codex-plan-phase", "h", "busy", f"r{day}", reflection(didnt=f"Busy friction {day}.", stamp=f"2026-10-0{day}T00:00:00Z"))
        for day in (1, 2)
    ]
    pending = put(root, "codex-execute-detailed", "h", "b1", "r", reflection(didnt="Pending more evidence."))
    pending_duplicate = put(root, "codex-execute-detailed", "h", "b1", "s", reflection(didnt="Pending more evidence.", stamp="2026-10-02T00:00:00Z"))
    pending_repo_specific = put(root, "codex-execute-detailed", "h", "b2", "r", reflection(improvements="Fix other-repo#4."))

    corpus, boilerplate = rc.collect([root], per_branch_cap=1)
    consumed = set(rc.manifest(corpus, boilerplate)["reflections_consumed"])

    assert corpus.ready_skills() == ["plan-phase"]
    newest_busy, oldest_busy = capped[1], capped[0]
    assert {str(p) for p in (*ready, newest_busy, duplicate, empty, pending_duplicate)} == consumed
    for left in (oldest_busy, ready_repo_specific, pending, pending_repo_specific):
        assert str(left) not in consumed


def test_skill_bundle_override_root_is_scanned(tmp_path, home, monkeypatch):
    custom = tmp_path / "custom-bundle"
    put(custom, "codex-plan-phase", "h", "b1", "r", reflection())
    monkeypatch.setenv("PHASE_LOOP_SKILL_BUNDLE", str(custom))

    corpus, _ = rc.collect()

    assert custom in corpus.roots and len(corpus.scanned) == 1


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


def test_archive_moves_consumed_and_next_collect_skips_them(tmp_path, home):
    root = tmp_path / "skills"
    first = put(root, "codex-plan-phase", "h", "b", "r1", reflection())
    put(root, "codex-plan-phase", "h", "b2", "r2", reflection(didnt="Other."))
    corpus, boilerplate = rc.collect([root])
    out = rc.write_corpus(corpus, boilerplate, tmp_path / "out")

    assert rc.archive([first], roots=[root], dry_run=True) == [(first, first.parent / "archive" / "r1.md")]
    assert first.exists()
    assert rc.main(["archive", "--manifest", str(out["manifest"]), "--root", str(root)]) == 0

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


def test_archive_preserves_reflections_skipped_below_the_threshold(tmp_path, home):
    root = tmp_path / "skills"
    pending = None
    moved = []
    for skill, branch, friction in (
        ("codex-plan-phase", "one", "Planning friction one."),
        ("codex-plan-phase", "two", "Planning friction two."),
        ("codex-execute-phase", "one", "Execution friction pending more evidence."),
    ):
        path = root / skill / "reflections/repo" / branch / "run.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            f"## What didn't\n{friction}\n## Improvements to SKILL.md\nNone.\n",
            encoding="utf-8",
        )
        if skill == "codex-execute-phase":
            pending = path
        else:
            moved.append(path)
    excluded_ready = put(root, "codex-plan-phase", "repo", "three", "run", reflection(improvements="Fix other-repo#5."))
    corpus, boilerplate = rc.collect([root], min_reflections=2)
    assert corpus.ready_skills() == ["plan-phase"]
    artifacts = rc.write_corpus(corpus, boilerplate, tmp_path / "corpus")
    assert rc.main(["archive", "--manifest", str(artifacts["manifest"]), "--root", str(root)]) == 0
    assert pending.exists(), "the editor archived a skill the planner was instructed to skip"
    assert excluded_ready.exists(), "an excluded reflection of a ready skill was archived"
    for path in moved:
        assert not path.exists() and (path.parent / "archive" / path.name).exists()


def test_a_newer_superset_reflection_is_not_a_duplicate(tmp_path):
    root = tmp_path / "skills"
    shared = "\n".join(f"Shared friction line {i}." for i in range(5))
    put(root, "codex-plan-phase", "h", "b", "r1", reflection(didnt=shared))
    put(root, "codex-plan-phase", "h", "b", "r2", reflection(
        didnt=f"{shared}\nNEW-FRICTION-ONE surfaced later.\nNEW-FRICTION-TWO surfaced later.",
        stamp="2026-10-02T00:00:00Z",
    ))

    corpus, _ = rc.collect([root])
    bundle = rc.render_bundle(corpus)

    assert [r.excluded for r in corpus.scanned] == [None, None]
    assert "NEW-FRICTION-ONE" in bundle and "NEW-FRICTION-TWO" in bundle


def test_collector_does_not_read_a_symlink_outside_its_root(tmp_path):
    root = tmp_path / "skills"
    outside = tmp_path / "outside.md"
    outside.write_text(
        "## What didn't\nOUTSIDE-ROOT-CONTENT\n"
        "## Improvements to SKILL.md\nNone.\n",
        encoding="utf-8",
    )
    link = root / "codex-plan-phase/reflections/repo/branch/run.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    try:
        corpus, _ = rc.collect([root], min_reflections=1)
    except (ValueError, OSError):
        return
    assert not corpus.scanned, "a file outside the scan root was read through a symlink"


def test_collector_skips_symlinks_and_directories_that_leave_the_reflections_dir(tmp_path):
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.md").write_text("## What didn't\nOUTSIDE-DIR-CONTENT\n", encoding="utf-8")
    reflections = root / "codex-plan-phase" / "reflections"
    (reflections / "repo").mkdir(parents=True)
    (reflections / "repo" / "linked-branch").symlink_to(outside, target_is_directory=True)
    kept = put(root, "codex-plan-phase", "repo", "real", "run", reflection(didnt="Real friction."))
    (reflections / "repo" / "real" / "alias.md").symlink_to(kept)

    corpus, _ = rc.collect([root], min_reflections=1)

    assert [r.path for r in corpus.scanned] == [kept]
    assert "OUTSIDE-DIR-CONTENT" not in rc.render_bundle(corpus)


def _two_root_manifest(tmp_path):
    inside_root, other_root = tmp_path / "skills", tmp_path / "notes"
    inside = put(inside_root, "codex-plan-phase", "h", "b", "r", reflection())
    other = put(other_root, "codex-plan-phase", "h", "b", "r", reflection())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reflections_consumed": [str(inside), str(other)]}))
    return inside_root, other_root, inside, other, manifest


def test_archive_refuses_a_manifest_path_outside_every_root(tmp_path, home):
    inside_root, other_root, inside, other, manifest = _two_root_manifest(tmp_path)

    assert rc.main(["archive", "--manifest", str(manifest), "--root", str(inside_root)]) != 0
    assert inside.exists() and other.exists(), "a refused archive moved something"

    assert rc.main(["archive", "--manifest", str(manifest), "--root", str(inside_root), "--root", str(other_root)]) == 0
    assert not inside.exists() and not other.exists()
    assert (inside.parent / "archive" / "r.md").exists() and (other.parent / "archive" / "r.md").exists()


def test_archive_roots_come_from_the_environment_not_the_manifest(tmp_path, home, monkeypatch):
    _inside_root, other_root, _inside, other, manifest = _two_root_manifest(tmp_path)
    data = json.loads(manifest.read_text())
    data["inventory"] = {"roots": [{"root": str(other_root), "count": 1}]}
    manifest.write_text(json.dumps(data))

    assert rc.main(["archive", "--manifest", str(manifest)]) != 0
    assert other.exists()

    monkeypatch.setenv("PHASE_LOOP_SKILL_BUNDLE", str(other_root))
    data["reflections_consumed"] = [str(other)]
    manifest.write_text(json.dumps(data))
    assert rc.main(["archive", "--manifest", str(manifest)]) == 0
    assert not other.exists()


def test_archive_refuses_paths_that_are_not_reflections_of_a_skill(tmp_path, home):
    root = tmp_path / "notes"
    stray = root / "reflections" / "x.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("x")
    real = put(root, "codex-plan-phase", "h", "b", "r", reflection())
    link = real.parent / "alias.md"
    link.symlink_to(real)

    for listed in (stray, link):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"reflections_consumed": [str(real), str(listed)]}))
        assert rc.main(["archive", "--manifest", str(manifest), "--root", str(root)]) != 0
        assert real.exists() and stray.exists()


def test_relative_exclude_leaves_the_consumed_file_in_place(tmp_path, home, monkeypatch, capsys):
    root = tmp_path / "skills"
    kept = put(root, "codex-plan-phase", "h", "b1", "r", reflection())
    moved = put(root, "codex-plan-phase", "h", "b2", "r", reflection(didnt="Other."))
    out = rc.write_corpus(*rc.collect([root]), tmp_path / "out")
    monkeypatch.chdir(tmp_path)

    exclude = str(kept.relative_to(tmp_path))
    assert rc.main(["archive", "--manifest", str(out["manifest"]), "--root", str(root), "--exclude", exclude]) == 0

    assert kept.exists() and not moved.exists()
    assert json.loads(capsys.readouterr().out)["left_in_place"] == 1


def test_an_exclude_that_matches_no_consumed_path_is_an_error(tmp_path, home):
    root = tmp_path / "skills"
    first = put(root, "codex-plan-phase", "h", "b1", "r", reflection())
    put(root, "codex-plan-phase", "h", "b2", "r", reflection(didnt="Other."))
    out = rc.write_corpus(*rc.collect([root]), tmp_path / "out")

    assert rc.main(["archive", "--manifest", str(out["manifest"]), "--root", str(root), "--exclude", str(tmp_path / "nope.md")]) != 0
    assert first.exists()


def test_prompt_inputs_do_not_retain_credentials_or_stripped_ledger_text(tmp_path):
    root = tmp_path / "skills"
    credential = "sk-proj-" + "A" * 64
    ledger = "Repeated ledger: other-repo#123 at /home/example/private-repo/file.py"
    for index in range(3):
        path = root / "codex-plan-phase/reflections/repo" / f"branch-{index}/run.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            f"## What worked\n{ledger}\n"
            f"## What didn't\nDistinct friction {index}; API_KEY={credential}; retry={index}.\n"
            "## Improvements to SKILL.md\nNone.\n",
            encoding="utf-8",
        )
    corpus, boilerplate = rc.collect([root])
    bundle = rc.render_bundle(corpus)
    manifest = json.dumps(rc.manifest(corpus, boilerplate))
    leaks = []
    if credential in bundle:
        leaks.append("synthetic API credential in bundle")
    if ledger in manifest:
        leaks.append("unredacted stripped ledger text in manifest")
    assert not leaks, leaks


def test_unstructured_reflections_are_credential_redacted(tmp_path):
    root = tmp_path / "skills"
    token = "ghp_" + "Rt9Kp2Lv8Hn3cQz7mXw4Yb6Na1Ds5Fe0Gh"
    put(root, "codex-execute-phase", "h", "b", "r", f"# Notes\nThe run exported GITHUB_TOKEN={token} by mistake.\n")

    bundle = rc.render_bundle(rc.collect([root], min_reflections=1)[0])

    assert token not in bundle and "by mistake." in bundle


def test_one_reflection_cannot_stall_the_collector(tmp_path):
    root = tmp_path / "skills"
    path = root / "codex-plan-phase/reflections/repo/branch/run.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## What didn't\n" + "ledger-" * 100000
        + "\n## Improvements to SKILL.md\nNone.\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, "-c",
         "import sys; from pathlib import Path; "
         "from phase_loop_runtime.reflection_corpus import collect; "
         "collect([Path(sys.argv[1])])", str(root)],
        timeout=3,
        check=True,
        capture_output=True,
    )


def test_an_oversized_reflection_is_excluded_unread(tmp_path):
    root = tmp_path / "skills"
    big = put(root, "codex-plan-phase", "h", "b1", "r", reflection(didnt="OVERSIZED-MARKER " + "x" * rc.MAX_REFLECTION_BYTES))
    put(root, "codex-plan-phase", "h", "b2", "r", reflection(didnt="Normal friction."))

    corpus, boilerplate = rc.collect([root], min_reflections=1)
    entry = next(r for r in rc.manifest(corpus, boilerplate)["reflections"] if r["path"] == str(big))

    assert entry["excluded"] == f"oversized:{big.stat().st_size}"
    assert "OVERSIZED-MARKER" not in rc.render_bundle(corpus)
    assert str(big) not in rc.manifest(corpus, boilerplate)["reflections_consumed"]


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
