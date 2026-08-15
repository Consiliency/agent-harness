"""Atomically refresh every v10 roadmap digest representation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Sequence


ASSUMPTIONS_REL = Path("phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py")
SIDECAR_REL = Path("specs/roadmap-assumption-probes-v10.json")
FIXTURE_REL = Path("phase-loop-runtime/tests/fixtures/roadmap-assumption-probes-v10.json")
_CONSTANT = re.compile(
    r'^(CANONICAL_ROADMAP_SHA256 = ")[0-9a-f]{64}("\s*)$', re.MULTILINE
)


class RoadmapResealError(RuntimeError):
    pass


def _render(repo: Path, roadmap: Path) -> tuple[str, bytes]:
    digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    assumptions_path = repo / ASSUMPTIONS_REL
    assumptions = assumptions_path.read_text(encoding="utf-8")
    rendered, count = _CONSTANT.subn(rf"\g<1>{digest}\g<2>", assumptions)
    if count != 1:
        raise RoadmapResealError("canonical roadmap digest constant is missing or ambiguous")

    sidecar = json.loads((repo / SIDECAR_REL).read_text(encoding="utf-8"))
    sidecar["roadmap_sha256"] = digest
    sidecar_bytes = (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return rendered, sidecar_bytes


def reseal_roadmap(repo: Path, roadmap: Path, *, write: bool) -> str:
    repo = Path(repo).resolve()
    roadmap = Path(roadmap)
    if not roadmap.is_absolute():
        roadmap = repo / roadmap
    digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    assumptions, sidecar = _render(repo, roadmap)
    expected = {
        repo / ASSUMPTIONS_REL: assumptions.encode("utf-8"),
        repo / SIDECAR_REL: sidecar,
        repo / FIXTURE_REL: sidecar,
    }
    if write:
        for path, content in expected.items():
            path.write_bytes(content)
    else:
        drifted = [str(path.relative_to(repo)) for path, content in expected.items() if path.read_bytes() != content]
        if drifted:
            raise RoadmapResealError(f"roadmap seal drift: {', '.join(drifted)}")
    return digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh or check v10 roadmap digest seals")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--roadmap", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        digest = reseal_roadmap(args.repo, args.roadmap, write=args.write)
    except (OSError, json.JSONDecodeError, RoadmapResealError) as exc:
        print(f"roadmap_reseal: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"roadmap_sha256": digest, "mode": "write" if args.write else "check"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
