"""Verify PRESROUTE's original tests-first receipt at its historical landing."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile


LANDING = "4f792cf7903c97a1b1f1813b88218efaf23c8ba6"
EVIDENCE_DIR = ".phase-loop/evidence/PRESROUTE"
EVIDENCE_FILES = (
    f"{EVIDENCE_DIR}/content-tdd-receipt.json",
    f"{EVIDENCE_DIR}/content-tdd-receipt.red.stdout.log",
    f"{EVIDENCE_DIR}/content-tdd-receipt.red.stderr.log",
)


def registered_checkout(repo: Path, checkout: Path) -> bool:
    listing = subprocess.run(["git", "worktree", "list", "--porcelain"],
                             cwd=repo, check=True, capture_output=True, text=True)
    return any(
        Path(line.removeprefix("worktree ")).resolve() == checkout.resolve()
        for line in listing.stdout.splitlines() if line.startswith("worktree ")
    )


def worktree_root(repo: Path) -> Path:
    if Path("/etc/consiliency/team-host").exists():
        return Path(os.environ.get("WORKTREE_ROOT") or Path.home() / "workspace/worktrees")
    if Path("/mnt/workspace").exists():
        return Path("/mnt/workspace/worktrees")
    return repo.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    requested_repo = parser.parse_args().repo.resolve()
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=requested_repo,
                         check=True, capture_output=True, text=True).stdout.strip()
    repo = Path(top).resolve()
    receipt = repo / EVIDENCE_FILES[0]
    if not receipt.is_file() or receipt.is_symlink():
        raise FileNotFoundError(f"PRESROUTE receipt missing or not regular: {receipt}")
    subprocess.run(["git", "merge-base", "--is-ancestor", LANDING, "HEAD"],
                   cwd=repo, check=True)
    subprocess.run(["git", "diff", "--exit-code", LANDING, "--", *EVIDENCE_FILES],
                   cwd=repo, check=True)
    root = worktree_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agent-harness-presroute-receipt-", dir=root) as temp:
        checkout = Path(temp) / "landing"
        try:
            subprocess.run(["git", "worktree", "add", "--detach", str(checkout), LANDING],
                           cwd=repo, check=True, stdout=subprocess.DEVNULL)
            subprocess.run([
                "uv", "run", "--project", "phase-loop-runtime", "python",
                "phase-loop-runtime/tests/presroute_content_tdd_adapter.py", "verify",
                "--repo", ".", "--landing-ref", LANDING,
                "--receipt", f"{EVIDENCE_DIR}/content-tdd-receipt.json",
            ], cwd=checkout, check=True)
        finally:
            if registered_checkout(repo, checkout):
                subprocess.run(["git", "worktree", "remove", "--force", str(checkout)],
                               cwd=repo, check=True, stdout=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
