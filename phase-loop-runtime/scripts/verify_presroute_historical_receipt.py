"""Verify PRESROUTE's original tests-first receipt at its historical landing."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile


LANDING = "4f792cf7903c97a1b1f1813b88218efaf23c8ba6"
EVIDENCE_DIR = ".phase-loop/evidence/PRESROUTE"


def worktree_root(repo: Path) -> Path:
    if Path("/etc/consiliency/team-host").exists():
        return Path(os.environ.get("WORKTREE_ROOT") or Path.home() / "workspace/worktrees")
    if Path("/mnt/workspace").exists():
        return Path("/mnt/workspace/worktrees")
    return repo.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    repo = parser.parse_args().repo.resolve()
    subprocess.run(["git", "diff", "--exit-code", LANDING, "--", EVIDENCE_DIR],
                   cwd=repo, check=True)
    root = worktree_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="agent-harness-presroute-receipt-", dir=root))
    checkout = scratch / "landing"
    added = False
    try:
        subprocess.run(["git", "worktree", "add", "--detach", str(checkout), LANDING],
                       cwd=repo, check=True, stdout=subprocess.DEVNULL)
        added = True
        subprocess.run([
            "uv", "run", "--project", "phase-loop-runtime", "python",
            "phase-loop-runtime/tests/presroute_content_tdd_adapter.py", "verify",
            "--repo", ".", "--landing-ref", LANDING,
            "--receipt", f"{EVIDENCE_DIR}/content-tdd-receipt.json",
        ], cwd=checkout, check=True)
    finally:
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(checkout)],
                           cwd=repo, check=True, stdout=subprocess.DEVNULL)
        scratch.rmdir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
