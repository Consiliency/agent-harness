"""ah#345: the headless agy leg must be able to READ the staged bundle — and nothing more.

The failure is real and directly reproducible against the CLI, but INTERMITTENT through the
panel: whether agy invokes `read_file` depends on the run. So these tests pin the
deterministic thing — that a correctly SCOPED grant is staged — rather than the CLI's mood.

The scoping is the security-load-bearing part. A review leg ingests deliberately untrusted
material (the bundle is attacker-controlled by construction), so `--dangerously-skip-permissions`
would put arbitrary command execution one prompt-injection away. Verified against the real
CLI while developing this:

    allow=["read_file"]  -> reads the staged bundle   (works)
    allow=["read_file"]  -> `echo PWNED` via shell    (DENIED, rc==0, no output)
"""
from __future__ import annotations

import json
from pathlib import Path

from phase_loop_runtime.panel_invoker import _grant_staged_read_permission


def test_grant_is_written_into_the_staged_dir(tmp_path: Path):
    _grant_staged_read_permission(tmp_path)
    cfg = tmp_path / ".gemini" / "settings.json"
    assert cfg.is_file(), "the staged dir must carry its own grant"
    assert json.loads(cfg.read_text()) == {"permissions": {"allow": ["read_file"]}}


def test_grant_allows_read_file_ONLY(tmp_path: Path):
    """THE SECURITY PROPERTY. Mutation: add "command" (or swap to a blanket allow) -> fails.

    A review leg consumes untrusted material; granting `command` would make a prompt
    injection in a bundle into arbitrary execution."""
    _grant_staged_read_permission(tmp_path)
    allow = json.loads((tmp_path / ".gemini" / "settings.json").read_text())["permissions"]["allow"]
    assert allow == ["read_file"]
    assert "command" not in allow
    assert not any(a.startswith("command") for a in allow)


def test_grant_never_touches_global_config(tmp_path: Path, monkeypatch):
    """The grant is ephemeral. It must never write to the operator's ~/.gemini."""
    fake_home = tmp_path / "home"
    (fake_home / ".gemini").mkdir(parents=True)
    global_cfg = fake_home / ".gemini" / "settings.json"
    global_cfg.write_text('{"security": {}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    staged = tmp_path / "staged"
    staged.mkdir()
    _grant_staged_read_permission(staged)

    assert json.loads(global_cfg.read_text()) == {"security": {}}, "global config must be untouched"


def test_grant_failure_is_non_fatal(tmp_path: Path):
    """Best-effort: a staging failure must not break the panel — the leg then fails the way
    it does today, loudly, via the surfaced stderr.

    The obstruction must be REAL. A first version of this test passed a non-existent path,
    which `mkdir(parents=True)` simply creates — so it raised nothing and asserted nothing.
    Here `.gemini` already exists as a FILE, so mkdir genuinely raises.
    Mutation: narrow `except Exception` to a subclass that misses it -> this fails."""
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / ".gemini").write_text("i am a file, not a directory", encoding="utf-8")

    _grant_staged_read_permission(staged)  # must not raise

    assert (staged / ".gemini").is_file(), "the obstruction is still there; we just did not crash"
