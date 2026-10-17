"""agent-harness#1358: context-file adapter runs can read the `references/` files a skill links.

`_skill_bodies` inlines only each skill's `SKILL.md` into `context.md`, so a section moved
into `references/` would vanish from gemini, grok, opencode and `command` runs. The launch
copies those files beside `context.md` under `skills/<skill>/references/`, and the context
says so for each skill that has any. Ungated: needs no dotfiles tree.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import injection, launcher
from phase_loop_runtime.models import PromptBundle

REPO_ROOT = Path(injection.__file__).resolve().parents[3]
NOTE = "This skill's linked `references/` files are copied beside this context file"


def _skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n\nSee [a](references/a.md).\n", encoding="utf-8")
    (skill_dir / "references" / "a.md").write_bytes(b"# A\n\nmoved detail\n")
    return skill_dir


def _bundle(repo: Path, harness: str, skill: str) -> PromptBundle:
    return PromptBundle(
        workflow_command=f"{skill} plan.md",
        body="",
        injection_mode="context_file",
        context_body=injection._render_context_body(
            repo=repo,
            harness_target=harness,
            action="plan",
            body="",
            expected_skill_pack=(skill,),
            injection_mode="context_file",
        ),
        expected_skill_pack=(skill,),
        product_action="plan",
    )


@pytest.mark.parametrize("harness", ["gemini", "opencode"])
def test_context_file_harnesses_get_linked_references(tmp_path, monkeypatch, harness):
    skill = f"{harness}-plan-phase"
    skill_dir = _skill(tmp_path / "src", skill)
    monkeypatch.setattr(injection, "_resolve_pack_skill_dirs", lambda *_: {skill: skill_dir})
    monkeypatch.setattr(launcher.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _bundle(repo, harness, skill)
    assert f"{NOTE} under `skills/{skill}/references/`" in bundle.render_context()

    if harness == "gemini":
        command = ["agy", "--add-dir", str(repo), "-p", f"read {launcher.GEMINI_CONTEXT_PLACEHOLDER}"]
    else:
        command = ["opencode", "run", f"read {launcher.OPENCODE_CONTEXT_PLACEHOLDER}"]
    spec = SimpleNamespace(executor=harness, command=command, prompt_bundle=bundle, wrapped_cwd=str(repo))
    log_path = tmp_path / "run" / "launch.log"
    log_path.parent.mkdir()
    launcher._resolve_command_context(spec, log_path)

    context_files = list((tmp_path / ("home" if harness == "gemini" else "run")).rglob("context.md"))
    assert len(context_files) == 1
    copied = context_files[0].parent / "skills" / skill / "references" / "a.md"
    assert copied.read_bytes() == (skill_dir / "references" / "a.md").read_bytes()


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
        return {name: REPO_ROOT / "skills-src" / harness_target / name for name in pack}

    monkeypatch.setattr(injection, "_resolve_pack_skill_dirs", resolve)
    for action, pack in injection.HARNESS_ACTION_SKILLS[harness].items():
        context = injection._skill_bodies(REPO_ROOT, harness, pack)
        assert context, (harness, action)
        assert NOTE not in context, (harness, action)
        assert injection.skill_reference_files(REPO_ROOT, harness, pack) == (), (harness, action)
