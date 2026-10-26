"""agent-harness#1358: context-file adapter runs can read the `references/` files a skill links.

`_skill_bodies` inlines only each skill's `SKILL.md` into `context.md`, so a section moved
into `references/` would vanish from gemini, grok, opencode and `command` runs. The launch
copies those files beside `context.md` under `skills/<skill>/references/`, and the context
says so for each skill that has any. Ungated: needs no dotfiles tree.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from phase_loop_runtime import injection, launcher, prompts
from phase_loop_runtime.models import ModelSelection
from phase_loop_runtime.skill_inventory import SkillParity

PACKAGED = Path(injection.__file__).resolve().parent / "skills_bundle"
NOTE = "This skill's linked `references/` files are copied beside this context file"


def _skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n\nSee [a](references/a.md).\n", encoding="utf-8")
    (skill_dir / "references" / "a.md").write_bytes(b"# A\n\nmoved detail\n")
    return skill_dir


def _bundle(repo: Path, harness: str, skill: str, action: str, monkeypatch):
    monkeypatch.setitem(injection.HARNESS_ACTION_SKILLS, harness, {action: (skill,)})
    monkeypatch.setattr(prompts, "_roadmap_repo_root", lambda _: repo)
    monkeypatch.setattr(injection, "_render_baml_closeout_instruction", lambda **_: "Fixture closeout.")
    monkeypatch.setattr(injection, "inspect_skill_parity", lambda *_: SkillParity(
        recommended_installed_roots=(), installed_skill_roots=(), installed_skill_warnings=(),
    ))
    return prompts.build_prompt(
        action, roadmap=repo / "specs" / "phase-plans-v1.md", phase="REFERENCES",
        harness_target=harness,
    )


@pytest.mark.parametrize("harness", ["gemini", "opencode"])
@pytest.mark.parametrize("action", ["plan", "execute", "review"])
def test_context_file_harnesses_get_linked_references(tmp_path, monkeypatch, harness, action):
    skill = f"{harness}-{action}-phase"
    monkeypatch.setattr(launcher.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    skill_dir = _skill(repo / "skills-src" / harness, skill)
    binary = skill_dir / "references" / "nested" / "data.bin"
    binary.parent.mkdir()
    binary.write_bytes(bytes(range(256)))
    expected = {"a.md": (skill_dir / "references" / "a.md").read_bytes(),
                "nested/data.bin": binary.read_bytes()}
    launch_repo = tmp_path / "worktree"
    launch_repo.mkdir()
    other = _skill(launch_repo / "skills-src" / harness, skill)
    (other / "references" / "a.md").write_bytes(b"Different worktree bytes\n")
    monkeypatch.setattr(injection, "_resolve_pack_skill_dirs", lambda root, target, pack: {
        name: root / "skills-src" / target / name for name in pack
    })
    bundle = _bundle(repo, harness, skill, action, monkeypatch)
    assert f"{NOTE} under `skills/{skill}/references/`" in bundle.render_context()
    (skill_dir / "references" / "a.md").write_bytes(b"Edited after the prompt was built\n")
    assert _bundle(repo, harness, skill, action, monkeypatch).skill_bundle_sha256 != bundle.skill_bundle_sha256
    request = launcher.build_launch_request(
        executor=harness, action=action, repo=launch_repo,
        roadmap=launch_repo / "specs" / "phase-plans-v1.md", phase="REFERENCES", plan=None,
        model_selection=ModelSelection(profile="plan", effort="high",
                                       model="gemini-4-argon" if harness == "gemini" else "openai/gpt-6-astra"),
        prompt_bundle=bundle, json_output=True, bypass_approvals=False,
    )
    spec = launcher.build_launch_spec(request)
    assert spec.wrapped_cwd is None
    before = spec.to_json()
    assert "skill_reference_files" not in bundle.to_json()
    log_path = tmp_path / "run" / "launch.log"
    log_path.parent.mkdir()
    launcher._resolve_command_context(spec, log_path, dry_run=True)

    context_files = list((tmp_path / ("home" if harness == "gemini" else "run")).rglob("context.md"))
    assert len(context_files) == 1
    for rel, content in expected.items():
        copied = context_files[0].parent / "skills" / skill / "references" / rel
        assert copied.read_bytes() == content
    assert spec.to_json() == before


def test_canonical_override_references_are_found(tmp_path):
    skill_dir = tmp_path / "plan-phase"
    override = skill_dir / "_overrides" / "gemini" / "references"
    override.mkdir(parents=True)
    (override / "b.md").write_text("gemini only\n", encoding="utf-8")

    assert [rel for rel, _ in injection._skill_reference_sources(skill_dir, "gemini")] == ["b.md"]
    assert injection._skill_reference_sources(skill_dir, "opencode") == ()

    before = injection._skill_references_sha256(skill_dir, "gemini")
    (override / "b.md").write_text("gemini only, edited\n", encoding="utf-8")
    after = injection._skill_references_sha256(skill_dir, "gemini")
    assert list(before) == ["_overrides/gemini/references/b.md"]
    assert before != after


@pytest.mark.parametrize("harness", ["gemini", "opencode"])
def test_shipped_packs_note_and_copy_exactly_their_references(tmp_path, monkeypatch, harness):
    # A shipped pack skill gets the note and copies only when it ships references/;
    # one without references adds no line and copies nothing.
    def resolve(_repo, harness_target, pack):
        return {name: PACKAGED / name for name in pack}

    monkeypatch.setattr(injection, "_resolve_pack_skill_dirs", resolve)
    for action, pack in injection.HARNESS_ACTION_SKILLS[harness].items():
        context = injection._skill_bodies(tmp_path, harness, pack)
        assert context, (harness, action)
        files = injection.skill_reference_files(tmp_path, harness, pack)
        for skill in pack:
            shipped = sorted(
                f"skills/{skill}/references/{path.relative_to(PACKAGED / skill / 'references').as_posix()}"
                for path in (PACKAGED / skill / "references").rglob("*") if path.is_file()
            )
            assert sorted(dest for dest, _ in files if dest.startswith(f"skills/{skill}/")) == shipped
            note = f"{NOTE} under `skills/{skill}/references/`"
            assert (note in context) == bool(shipped), (harness, action, skill)


@pytest.mark.parametrize("harness", ["gemini", "claude"])
def test_execute_phase_links_resolve_to_shipped_references(harness):
    skill = PACKAGED / f"{harness}-execute-phase"
    linked = set(re.findall(r"\]\((references/[^)#]+)", (skill / "SKILL.md").read_text(encoding="utf-8")))
    assert linked
    for rel in linked:
        assert (skill / rel).is_file(), rel


# References are read at their linking step, not preloaded with the entrypoint.
# Each list item is its own block, so a sibling bullet cannot satisfy another's trigger.
def _blocks(text: str) -> list[tuple[str, str]]:
    heading, out = "", []
    for block in re.split(r"\n\s*\n", text):
        for item in re.split(r"\n(?=[ \t]*- )", block):
            for line in item.splitlines():
                if line.startswith("#"):
                    heading = line.lstrip("# ").strip()
            out.append((heading, " ".join(item.split())))
    return out


def _home(skill: Path, needle: str) -> str | None:
    if needle in (skill / "SKILL.md").read_text(encoding="utf-8"):
        return None
    homes = [p.relative_to(skill).as_posix() for p in sorted((skill / "references").glob("*.md"))
             if needle in p.read_text(encoding="utf-8")]
    assert len(homes) == 1, (needle, homes)
    return homes[0]


def _linking(skill: Path, rel: str, text: str | None = None) -> list[tuple[str, str]]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8") if text is None else text
    return [(h, b) for h, b in _blocks(text) if f"]({rel}" in b]


@pytest.mark.parametrize("explicit_plan", [False, True])
@pytest.mark.parametrize("needle", [
    "On the FIRST commit of a phase", "immediately before each `git push`",
])
@pytest.mark.parametrize("harness", ["gemini", "claude"])
def test_publication_rules_reachable_before_first_commit(harness, explicit_plan, needle):
    skill = PACKAGED / f"{harness}-execute-phase"
    rel = _home(skill, needle)
    if rel is None:
        return
    early = [b for h, b in _linking(skill, rel)
             if h != "Publication mode"
             and (not explicit_plan or "If no plan path is explicit" not in b)
             and re.search(r"first[- ]commit|before (each|every|any) [^.]*push|before execution",
                           f"{h} {b}", re.I)]
    assert early, f"{needle!r} in {rel} needs a trigger before the first commit"
    # Reading interactive publication must never become a runner/governed instruction.
    assert all("interactive" in b.lower() for b in early)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    runner = text.split("- (a) Runner-managed closeout", 1)[1].split("- (b)", 1)[0]
    assert "OR ambiguous mode" in runner
    assert "the RUNNER owns closeout and commit" in runner
    assert "Do NOT" in runner and "independently publish" in runner
    assert f"]({rel}" not in runner


CLAUDE_EXECUTE = PACKAGED / "claude-execute-phase"
BROWSER_RULE = "If the repo lacks a Playwright config, add one in the lane"


def _sections(text: str, title: str) -> set[str]:
    """Headings of the level-2 section ``title`` and everything nested under it."""
    names, inside = set(), False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip() == title
        if inside and line.startswith("#"):
            names.add(line.lstrip("# ").strip())
    return names


def _intake_triggers(text: str) -> list[str]:
    rel = _home(CLAUDE_EXECUTE, BROWSER_RULE)
    assert rel == "references/merge-and-verify.md"
    # Adapter mode overrides the interactive workflow, and the adapter section is adapter-only.
    excluded = (_sections(text, "Workflow (orchestrator-only main thread)")
                | _sections(text, "Phase-Loop Adapter Mode"))
    return [b for h, b in _linking(CLAUDE_EXECUTE, f"{rel}#browser-verification", text)
            if h not in excluded and "both modes" in b.lower() and "plan intake" in b
            and "before implementation or lane dispatch" in b]


def test_claude_browser_setup_reachable_at_plan_intake_in_both_modes():
    text = (CLAUDE_EXECUTE / "SKILL.md").read_text(encoding="utf-8")
    trigger, = _intake_triggers(text)
    assert "claude-in-chrome" in trigger and "lane" in trigger
    brief = (CLAUDE_EXECUTE / "references" / "lane-dispatch.md").read_text(encoding="utf-8")
    assert "](merge-and-verify.md#browser-verification)" in brief.split("**Teammate brief**", 1)[1]
    line, = (line for line in text.splitlines() if "#browser-verification)" in line)
    assert " ".join(line.split()) == trigger
    without = text.replace(line + "\n", "")
    # Negative controls: no trigger; the trigger only on the interactive path; its words
    # in a sibling bullet beside an unrelated link.
    assert _intake_triggers(without) == []
    marker = "### Interactive steps\n"
    assert _intake_triggers(without.replace(marker, f"{marker}\n{line}\n")) == []
    link = re.search(r"\[[^]]*\]\([^)]*\)", line).group(0)
    sibling = f"## Sibling\n\n- {line.replace(link, 'browser setup')}\n- See {link}.\n"
    assert _intake_triggers(without + "\n" + sibling) == []


def test_gemini_worktree_sweep_triggered_at_phase_start_and_closeout():
    skill = PACKAGED / "gemini-execute-phase"
    rel = _home(skill, "Run the sweep at closeout (and, cheaply, at phase start)")
    if rel is None:
        return
    assert any("phase start" in b and "closeout" in b and "interactive" not in b.lower()
               for _, b in _linking(skill, rel))


@pytest.mark.parametrize("action", ["execute", "repair"])
def test_packaged_opencode_execute_references_reach_context(tmp_path, monkeypatch, action):
    skill = "opencode-execute-phase"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(injection, "_resolve_pack_skill_dirs", lambda root, target, pack: {
        name: PACKAGED / name for name in pack
    })
    bundle = _bundle(repo, "opencode", skill, action, monkeypatch)
    assert f"{NOTE} under `skills/{skill}/references/`" in bundle.render_context()
    expected = {
        f"skills/{skill}/references/{name}": (PACKAGED / skill / "references" / name).read_bytes()
        for name in ("interactive-publication.md", "worktree-pruning.md")
    }
    assert dict(bundle.skill_reference_files) == expected
    request = launcher.build_launch_request(
        executor="opencode", action=action, repo=repo,
        roadmap=repo / "roadmap.md", phase="REFERENCES", plan=None,
        model_selection=ModelSelection(profile=action, effort="high", model="openai/gpt-6-astra"),
        prompt_bundle=bundle, json_output=True, bypass_approvals=False,
    )
    spec = launcher.build_launch_spec(request)
    log_path = tmp_path / "run" / "launch.log"
    log_path.parent.mkdir()
    launcher._resolve_command_context(spec, log_path, dry_run=True)
    contexts = list(log_path.parent.rglob("context.md"))
    assert len(contexts) == 1
    for relative_path, content in expected.items():
        assert (contexts[0].parent / relative_path).read_bytes() == content


@pytest.mark.parametrize("harness", ["claude", "codex", "gemini", "opencode"])
def test_opencode_execute_references_install_only_for_opencode(tmp_path, harness):
    from phase_loop_runtime.skill_install import install_skills

    source = Path(__file__).resolve().parents[2] / "phase-loop-skills"
    if not source.is_dir():
        pytest.skip("committed bundle absent (from-wheel layout)")
    destination = tmp_path / harness
    install_skills(harness=harness, source=source, destination=destination, mode="copy", apply=True)
    for name in ("interactive-publication.md", "worktree-pruning.md"):
        installed = destination / f"{harness}-execute-phase" / "references" / name
        packaged = PACKAGED / f"{harness}-execute-phase" / "references" / name
        if harness == "opencode":
            assert installed.read_bytes() == packaged.read_bytes()
        else:
            expected = (PACKAGED / "opencode-execute-phase" / "references" / name).read_bytes()
            # Siblings may own a reference with the same name, but not OpenCode's bytes.
            for sibling in (installed, packaged):
                if sibling.exists():
                    assert sibling.read_bytes() != expected


@pytest.mark.parametrize("explicit_plan", [False, True])
@pytest.mark.parametrize("needle", [
    "On the FIRST commit of a phase", "immediately before each `git push`",
])
def test_opencode_publication_rules_reachable_before_first_commit(explicit_plan, needle):
    skill = PACKAGED / "opencode-execute-phase"
    rel = _home(skill, needle)
    if rel is None:
        return
    early = [b for h, b in _linking(skill, rel)
             if h != "Publication mode"
             and (not explicit_plan or "If no plan path is explicit" not in b)
             and re.search(r"first[- ]commit|before (each|every|any) [^.]*push|before execution",
                           f"{h} {b}", re.I)]
    assert early, f"{needle!r} in {rel} needs a trigger before the first commit"
    # Reading interactive publication must never become a runner/governed instruction.
    assert all("interactive" in b.lower() for b in early)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    runner = text.split("- (a) Runner-managed closeout", 1)[1].split("- (b)", 1)[0]
    assert "OR ambiguous mode" in runner
    assert "the RUNNER owns closeout and commit" in runner
    assert "Do NOT" in runner and "independently publish" in runner
    assert f"]({rel}" not in runner


def test_codex_native_execute_references_install_without_cross_harness_leakage(tmp_path):
    """The prompt-only Codex path reads native installed files, not context-file copies."""
    from phase_loop_runtime.skill_install import install_skills

    canonical = Path(__file__).resolve().parents[2] / "phase-loop-skills"
    if not (canonical / "execute-phase" / "SKILL.md").is_file():
        pytest.skip("canonical source absent in wheel-only layout")
    references = ("interactive-path.md", "worker-fanout.md")
    authored = canonical / "execute-phase" / "_overrides" / "codex" / "references"
    for harness in ("codex", "claude", "gemini", "opencode"):
        destination = tmp_path / harness / "skills"
        install_skills(harness=harness, source=canonical, destination=destination,
                       mode="copy", apply=True)
        installed = destination / f"{harness}-execute-phase"
        for name in references:
            expected = (authored / name).read_bytes()
            target = installed / "references" / name
            packaged = PACKAGED / f"{harness}-execute-phase" / "references" / name
            if harness == "codex":
                assert target.read_bytes() == packaged.read_bytes() == expected
                assert f"(references/{name})" in (installed / "SKILL.md").read_text()
                assert not (canonical / "execute-phase" / "references" / name).exists()
            else:
                # Another provider may later author its own file with the same name.
                assert not target.exists() or target.read_bytes() != expected
                assert not packaged.exists() or packaged.read_bytes() != expected



def test_codex_reference_bytes_participate_in_the_skill_digest(tmp_path):
    canonical = Path(__file__).resolve().parents[2] / "phase-loop-skills" / "execute-phase"
    if not (canonical / "SKILL.md").is_file():
        pytest.skip("canonical source absent in wheel-only layout")
    import shutil

    skill = tmp_path / "execute-phase"
    shutil.copytree(canonical, skill)
    before = injection._skill_references_sha256(skill, "codex")
    other_before = injection._skill_references_sha256(skill, "opencode")
    reference = skill / "_overrides" / "codex" / "references" / "worker-fanout.md"
    reference.write_bytes(reference.read_bytes() + b"\nSynthetic digest mutation.\n")
    after = injection._skill_references_sha256(skill, "codex")
    assert before.keys() == after.keys()
    assert before != after
    assert injection._skill_references_sha256(skill, "opencode") == other_before
