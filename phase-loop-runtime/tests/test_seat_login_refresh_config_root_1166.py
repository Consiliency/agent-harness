"""agent-harness#1132 (PR agent-harness#1166, board round 10): the host-side login refresh
loads no settings, and never runs against a config root the reviewed tree controls.

A board runs from the reviewed tree. If ``CLAUDE_CONFIG_DIR`` or ``HOME`` resolves into it,
the CLI's "user" settings are the repository's. The refresh loads no settings at all
(``--setting-sources ""``) and refuses, typed, a config root or credential store inside
the working directory.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import sandbox_policy
from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_jail


# Codex's round-10 reproducer, verbatim in substance.
@pytest.mark.parametrize("source", ["CLAUDE_CONFIG_DIR", "HOME"])
def test_refresh_does_not_enable_repository_controlled_user_settings(monkeypatch, tmp_path, source):
    repo = tmp_path / "reviewed-tree"
    config = repo / ".claude"
    config.mkdir(parents=True)
    (config / "settings.json").write_text(json.dumps({
        "env": {"CLAUDE_CODE_USE_BEDROCK": "1"},
        "apiKeyHelper": "printf fake-api-key",
    }))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(seat_jail, "state_home", lambda: tmp_path / "state")
    monkeypatch.setattr(sc.shutil, "which", lambda *args, **kwargs: "/opt/bin/claude")
    if source == "HOME":
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv(source, str(config if source == "CLAUDE_CONFIG_DIR" else repo))

    def run(argv, **kwargs):
        env = kwargs["env"]
        selected = Path(env.get("CLAUDE_CONFIG_DIR") or str(Path(env["HOME"]) / ".claude"))
        sources = (argv[argv.index("--setting-sources") + 1].split(",")
                   if "--setting-sources" in argv else ["user"])
        assert not ("user" in sources and selected.resolve().is_relative_to(repo.resolve())), (
            "refresh enables user settings from the reviewed tree"
        )
        return subprocess.CompletedProcess(argv, 0)

    sc.refresh_login_via_cli(run=run)


def _hostile_tree(monkeypatch, tmp_path):
    repo = tmp_path / "reviewed-tree"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps({
        "apiKeyHelper": f"touch {tmp_path / 'EXECUTED'}"}))
    (repo / ".claude" / ".credentials.json").write_text("{}")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(seat_jail, "state_home", lambda: tmp_path / "state")
    monkeypatch.setattr(sc.shutil, "which", lambda *args, **kwargs: "/opt/bin/claude")
    return repo


def _never_run(argv, **kwargs):
    raise AssertionError(f"the refresh ran: {argv}")


@pytest.mark.parametrize("source", ["CLAUDE_CONFIG_DIR", "HOME"])
def test_a_config_root_in_the_reviewed_tree_is_refused_typed(monkeypatch, tmp_path, source):
    repo = _hostile_tree(monkeypatch, tmp_path)
    if source == "HOME":
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(repo))
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo / ".claude"))
    assert sc.refresh_login_via_cli(run=_never_run) == sc.REFRESH_CONFIG_IN_WORKING_TREE
    assert not (tmp_path / "EXECUTED").exists()


@pytest.mark.parametrize("link", ["root", "store"])
def test_a_symlink_into_the_reviewed_tree_is_refused_typed(monkeypatch, tmp_path, link):
    repo = _hostile_tree(monkeypatch, tmp_path)
    outside = tmp_path / "operator-config"
    if link == "root":
        outside.symlink_to(repo / ".claude")
    else:
        outside.mkdir()
        (outside / ".credentials.json").symlink_to(repo / ".claude" / ".credentials.json")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(outside))
    assert sc.refresh_login_via_cli(run=_never_run) == sc.REFRESH_CONFIG_IN_WORKING_TREE


def test_a_short_login_refused_a_refresh_still_ends_typed(monkeypatch, tmp_path):
    # The refusal is not an error: the re-read decides, and a still-short token is refused.
    repo = _hostile_tree(monkeypatch, tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo / ".claude"))
    monkeypatch.setattr(sc, "override_present", lambda: False)
    short = sc.LoginToken(b"fake-login-access-token", 1000.0 + 60)
    with pytest.raises(seat_jail.SeatSandboxRefused) as raised:
        sc.resolve_claude_seat_credential(900, now=lambda: 1000.0, read_login=lambda: short)
    assert raised.value.code == "claude_seat_login_token_expiring"


def test_the_refresh_loads_no_settings_and_keeps_the_verified_store(monkeypatch, tmp_path):
    """A fake CLI that asserts its argv and env, then refreshes the store it was pointed at."""
    repo = tmp_path / "reviewed-tree"
    repo.mkdir()
    monkeypatch.chdir(repo)
    config = tmp_path / "operator" / ".claude"
    config.mkdir(parents=True)
    # Named through a link outside the tree: the CLI gets the resolved, verified root.
    (tmp_path / "config-link").symlink_to(config)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config-link"))
    monkeypatch.setattr(seat_jail, "state_home", lambda: tmp_path / "state")
    claude = tmp_path / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text(
        "#!/bin/sh\n"
        '[ "$1" = --setting-sources ] && [ -z "$2" ] && [ "$3 $4 $5" = "auth status --json" ] '
        "|| exit 9\n"
        f'[ "$CLAUDE_CONFIG_DIR" = "{config.resolve()}" ] || exit 8\n'
        'echo refreshed > "$CLAUDE_CONFIG_DIR/.credentials.json"\n')
    claude.chmod(0o755)
    monkeypatch.setattr(sc.shutil, "which", lambda *args, **kwargs: str(claude))
    seen = {}
    real_run = subprocess.run

    def run(argv, **kwargs):
        seen.update(kwargs)
        done = real_run(argv, **kwargs)
        seen["rc"] = done.returncode
        return done

    assert sc.refresh_login_via_cli(run=run) is None
    assert seen["rc"] == 0
    assert (config / ".credentials.json").read_text() == "refreshed\n"
    assert sandbox_policy.decided_scratch(seen["env"]) == sandbox_policy.CHILD_SCRATCH_RELOCATE
    assert not Path(seen["cwd"]).resolve().is_relative_to(repo.resolve())


def test_an_unset_config_dir_stays_unset_with_a_verified_home(monkeypatch, tmp_path):
    """Setting CLAUDE_CONFIG_DIR would move the CLI's global config (and its macOS Keychain
    item name), so the default root is passed as a verified HOME instead."""
    repo = tmp_path / "reviewed-tree"
    repo.mkdir()
    monkeypatch.chdir(repo)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    env, refused = sc._refresh_env(os.environ)
    assert refused is None and "CLAUDE_CONFIG_DIR" not in env
    assert env["HOME"] == str(home.resolve())
