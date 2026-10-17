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


def test_gemini_execute_phase_links_resolve_to_shipped_references():
    skill = PACKAGED / "gemini-execute-phase"
    linked = set(re.findall(r"\]\((references/[^)#]+)", (skill / "SKILL.md").read_text(encoding="utf-8")))
    assert linked
    for rel in linked:
        assert (skill / rel).is_file(), rel


# References are read at their linking step, not preloaded with the entrypoint.
def _blocks(text: str) -> list[tuple[str, str]]:
    heading, out = "", []
    for block in re.split(r"\n\s*\n", text):
        for line in block.splitlines():
            if line.startswith("#"):
                heading = line.lstrip("# ").strip()
        out.append((heading, " ".join(block.split())))
    return out


def _home(skill: Path, needle: str) -> str | None:
    if needle in (skill / "SKILL.md").read_text(encoding="utf-8"):
        return None
    homes = [p.relative_to(skill).as_posix() for p in sorted((skill / "references").glob("*.md"))
             if needle in p.read_text(encoding="utf-8")]
    assert len(homes) == 1, (needle, homes)
    return homes[0]


def _linking(skill: Path, rel: str) -> list[tuple[str, str]]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    return [(h, b) for h, b in _blocks(text) if f"]({rel}" in b]


@pytest.mark.parametrize("explicit_plan", [False, True])
@pytest.mark.parametrize("needle", [
    "On the FIRST commit of a phase", "immediately before each `git push`",
])
def test_gemini_publication_rules_reachable_before_first_commit(explicit_plan, needle):
    skill = PACKAGED / "gemini-execute-phase"
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


def test_gemini_worktree_sweep_triggered_at_phase_start_and_closeout():
    skill = PACKAGED / "gemini-execute-phase"
    rel = _home(skill, "Run the sweep at closeout (and, cheaply, at phase start)")
    if rel is None:
        return
    assert any("phase start" in b and "closeout" in b and "interactive" not in b.lower()
               for _, b in _linking(skill, rel))
