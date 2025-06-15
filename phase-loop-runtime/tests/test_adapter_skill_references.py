"""agent-harness#1358: context-file adapter runs can read the `references/` files a skill links.

`_skill_bodies` inlines only each skill's `SKILL.md` into `context.md`, so a section moved
into `references/` would vanish from gemini, grok, opencode and `command` runs. The launch
copies those files beside `context.md` under `skills/<skill>/references/`, and the context
says so for each skill that has any. Ungated: needs no dotfiles tree.
"""
from __future__ import annotations

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
def test_skills_without_references_leave_context_unchanged(tmp_path, monkeypatch, harness):
    # The shipped gemini/opencode packs link no references/ yet: no note, no copies.
    def resolve(_repo, harness_target, pack):
        return {name: PACKAGED / name for name in pack}

    monkeypatch.setattr(injection, "_resolve_pack_skill_dirs", resolve)
    for action, pack in injection.HARNESS_ACTION_SKILLS[harness].items():
        context = injection._skill_bodies(tmp_path, harness, pack)
        assert context, (harness, action)
        assert NOTE not in context, (harness, action)
        assert injection.skill_reference_files(tmp_path, harness, pack) == (), (harness, action)
