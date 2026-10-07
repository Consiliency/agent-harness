"""Review governance is read from the main commit only (agent-harness#1222 §5c).

A checkout with no main ref (a detached clone, such as the standalone Gate A layout) has
no trusted base. Its own copy of the governance files is never read: the authority-switch
check takes the stricter rule, and the repository's president ladder layer is not in force.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from phase_loop_runtime import panel_invoker
from phase_loop_runtime.advisor_board import config


def _detached_without_main(path: Path) -> Path:
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.email=f@example.invalid", "-c", "user.name=f",
           "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    (path / "plans").mkdir()
    (path / "plans/manifest.json").write_text('{"plans": []}')
    (path / ".agent-harness").mkdir()
    (path / ".agent-harness/advisor-boards.toml").write_text('[president]\nladder = ["grok"]\n')
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "candidate"], check=True)
    subprocess.run([*git, "checkout", "-q", "--detach"], check=True)
    for branch in ("main", "master"):
        subprocess.run([*git, "branch", "-q", "-D", branch], capture_output=True)
    return path


def test_no_base_takes_the_stricter_authority_rule(tmp_path):
    assert panel_invoker._govlean_authority_switched(_detached_without_main(tmp_path / "r")) is True


def test_no_base_leaves_the_repository_ladder_out_of_force(tmp_path):
    repo = _detached_without_main(tmp_path / "r")
    ladder = config.load_president_ladder(path=tmp_path / "no-user.toml", repo_dir=repo, review_base=True)
    assert ladder == panel_invoker.PRESIDENT_LADDER
