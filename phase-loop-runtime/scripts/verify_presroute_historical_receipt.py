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
                             cwd=repo, check=True, capture_output=True)
    return b"worktree " + os.fsencode(checkout.resolve()) + b"\n" in listing.stdout


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
    subprocess.run(["git", "merge-base", "--is-ancestor", LANDING, "HEAD"],
                   cwd=repo, check=True)
    for rel in EVIDENCE_FILES:
        path = repo / rel
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"frozen PRESROUTE evidence drift: {rel} is missing or not regular")
        original = subprocess.run(["git", "show", f"{LANDING}:{rel}"], cwd=repo,
                                  check=True, capture_output=True).stdout
        committed = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=repo,
                                   check=True, capture_output=True).stdout
        staged = subprocess.run(["git", "show", f":{rel}"], cwd=repo,
                                check=True, capture_output=True).stdout
        if path.read_bytes() != original or committed != original or staged != original:
            raise ValueError(f"frozen PRESROUTE evidence drift: {rel}")
    root = worktree_root(repo).resolve()
    if any(ord(char) < 32 or ord(char) == 127
           for path in (repo, root) for char in str(path)):
        raise ValueError("PRESROUTE receipt worktree paths contain control characters")
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
