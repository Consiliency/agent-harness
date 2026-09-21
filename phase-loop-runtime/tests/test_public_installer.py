"""Exercise the public shell installer without network or user-home effects."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from phase_loop_runtime.skill_install import REQUIRED_SKILLS


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install-agent-harness.sh"
REPO = "https://github.com/Consiliency/agent-harness"
pytestmark = pytest.mark.skipif(
    not INSTALLER.is_file() or not shutil.which("bash") or not shutil.which("git"),
    reason="requires checkout, bash and git",
)


@pytest.fixture
def installation(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    tools = tmp_path / "bin"
    tools.mkdir()
    template = tmp_path / "template"
    template.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{tools}:/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "AGENT_HARNESS_REPO": REPO,
        "AGENT_HARNESS_HOME": str(home / "managed"),
        "AGENT_HARNESS_REF": "v1.2.3",
        "AGENT_HARNESS_HARNESS": "codex",
        "AGENT_HARNESS_SKILL_DEST": str(home / "skills"),
        "PYTHONPATH": str(ROOT / "phase-loop-runtime/src"),
        "INSTALL_TEST_LOG": str(tmp_path / "effects.jsonl"),
        "INSTALL_TEST_TEMPLATE": str(template),
    }
    git = shutil.which("git")

    def git_run(*args):
        return subprocess.run([git, *args], env=env, check=True, capture_output=True, text=True)

    git_run("init", "-q", str(template))
    (template / "RELEASE_PIN").write_text("v1.2.3\n")
    (template / "install-agent-harness.sh").write_text("# fixture\n")
    for name in REQUIRED_SKILLS:
        skill = template / "phase-loop-skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\nFixture\n")
    git_run("-C", str(template), "add", ".")
    git_run("-C", str(template), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    git_run("-C", str(template), "remote", "add", "origin", REPO)
    git_run("-C", str(template), "tag", "v1.2.3")

    wrapper = f"""#!{sys.executable}
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
command = args[2] if name == 'git' and args[:1] == ['-C'] else (args[0] if args else '')
if name == 'git' and command not in ('fetch', 'checkout', 'clone'):
    os.execv({git!r}, [{git!r}, *args])
with open(os.environ['INSTALL_TEST_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\\n')
if name == 'git' and command == 'clone':
    subprocess.run([{git!r}, 'clone', '-q', '--local', os.environ['INSTALL_TEST_TEMPLATE'], args[-1]], check=True)
elif name == 'git' and command == 'fetch':
    if os.environ.get('INSTALL_TEST_REAL_UPDATE'):
        args[args.index('origin')] = os.environ['INSTALL_TEST_TEMPLATE']
        sys.exit(subprocess.run([{git!r}, *args]).returncode)
    sys.exit(int(os.environ.get('INSTALL_TEST_FETCH_RC', '0')))
elif name == 'git' and command == 'checkout' and os.environ.get('INSTALL_TEST_REAL_UPDATE'):
    sys.exit(subprocess.run([{git!r}, *args]).returncode)
elif name == 'phase-loop' and 'install' in args:
    from phase_loop_runtime.cli import main
    sys.exit(main([*args, '--json']))
elif name == 'phase-loop':
    print('phase-loop 1.2.3')
elif name == 'curl':
    sys.exit('unexpected network request')
"""
    for name in ("git", "uv", "phase-loop", "curl"):
        path = tools / name
        path.write_text(wrapper)
        path.chmod(0o755)
    return env, template, git_run


def run_installer(env):
    return subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True)


def effects(env):
    path = Path(env["INSTALL_TEST_LOG"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("kind", [
    "file", "directory", "empty_directory", "symlink", "symlink_trailing_slash",
    "dangling_symlink", "linked_worktree", "wrong_origin", "dirty", "untracked",
    "git_symlink", "incomplete_checkout",
])
def test_unmanaged_destination_is_preserved_before_install_effects(installation, kind):
    env, template, git_run = installation
    target = Path(env["AGENT_HARNESS_HOME"])
    sentinel = template / "RELEASE_PIN"
    before = sentinel.read_bytes()
    if kind == "file":
        target.write_text("keep me\n")
    elif kind in ("directory", "empty_directory"):
        target.mkdir()
        if kind == "directory":
            (target / "sentinel").write_text("keep me\n")
    elif kind in ("symlink", "symlink_trailing_slash", "dangling_symlink"):
        target.symlink_to(template if kind != "dangling_symlink" else template / "absent")
        if kind == "symlink_trailing_slash":
            env["AGENT_HARNESS_HOME"] += "/"
    elif kind == "linked_worktree":
        git_run("-C", str(template), "worktree", "add", "-q", "--detach", str(target))
    else:
        shutil.copytree(template, target)
        if kind == "wrong_origin":
            git_run("-C", str(target), "remote", "set-url", "origin", "https://example.invalid/unrelated")
        elif kind == "dirty":
            (target / "RELEASE_PIN").write_text("local changes\n")
        elif kind == "untracked":
            (target / "sentinel").write_text("keep me\n")
        elif kind == "git_symlink":
            (target / ".git").rename(target / "git-metadata")
            (target / ".git").symlink_to(target / "git-metadata")
        else:
            (target / "install-agent-harness.sh").unlink()
            git_run("-C", str(target), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qam", "incomplete")
    before_contents = {
        p.relative_to(target): p.read_bytes()
        for p in target.rglob("*") if p.is_file() and ".git" not in p.relative_to(target).parts
    } if target.is_dir() else {}
    result = run_installer(env)
    assert result.returncode != 0
    assert "refusing existing AGENT_HARNESS_HOME" in result.stderr
    assert effects(env) == []
    assert target.exists() or target.is_symlink()
    assert sentinel.read_bytes() == before
    if kind == "file":
        assert target.read_text() == "keep me\n"
    for relative, content in before_contents.items():
        assert (target / relative).read_bytes() == content


@pytest.mark.parametrize("existing", [False, True])
def test_absent_or_recognized_checkout_installs_copies(installation, existing):
    env, template, _ = installation
    target = Path(env["AGENT_HARNESS_HOME"])
    if existing:
        shutil.copytree(template, target)
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    calls = effects(env)
    git_calls = [call for call in calls if call[0] == "git"]
    assert any(("fetch" if existing else "clone") in call for call in git_calls)
    installs = [call for call in calls if call[0] == "phase-loop" and "install" in call]
    assert len(installs) == 1
    assert "--copy" in installs[0] and "--symlink" not in installs[0]
    assert '"mode": "copy"' in result.stdout
    installed = Path(env["AGENT_HARNESS_SKILL_DEST"]) / "codex-plan-detailed"
    assert installed.is_dir() and not installed.is_symlink()
    assert "name: codex-plan-detailed" in (installed / "SKILL.md").read_text()


def test_failed_fetch_does_not_checkout_stale_ref_or_replace_skills(installation):
    env, template, _ = installation
    shutil.copytree(template, env["AGENT_HARNESS_HOME"])
    env["INSTALL_TEST_FETCH_RC"] = "1"
    result = run_installer(env)
    assert result.returncode != 0
    calls = effects(env)
    assert not any("checkout" in call for call in calls)
    assert not any(call[0] == "phase-loop" and "install" in call for call in calls)


def test_update_preserves_ignored_file_that_new_ref_tracks(installation):
    env, template, git_run = installation
    target = Path(env["AGENT_HARNESS_HOME"])
    shutil.copytree(template, target)
    (target / ".git/info/exclude").write_text("local-notes\n")
    (target / "local-notes").write_text("operator content\n")
    (template / "local-notes").write_text("new release content\n")
    git_run("-C", str(template), "add", "local-notes")
    git_run("-C", str(template), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "new release")
    git_run("-C", str(template), "tag", "v1.2.4")
    env.update(AGENT_HARNESS_REF="v1.2.4", INSTALL_TEST_REAL_UPDATE="1")
    result = run_installer(env)
    assert result.returncode != 0
    assert (target / "local-notes").read_text() == "operator content\n"
    assert not any(call[0] == "phase-loop" and "install" in call for call in effects(env))
