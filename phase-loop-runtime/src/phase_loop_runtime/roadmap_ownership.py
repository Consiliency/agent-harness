"""Roadmap-ownership preflight (ah#633).

A roadmap block that binds only the agents who READ the roadmap is advisory. This
turns the per-phase ``Key files`` lists into a check that fires on the first edit,
without anyone choosing to consult anything.

The motivating incident: nine commits were built against
``phase_worktree_executor.py`` and closed as superseded, because
``specs/phase-plans-v10.md`` already assigned that file to Phase 5 lane A, ah#354
already said "No SCHED runtime edits are authorized", and ah#616 already held a
better design. Nothing stopped it and nothing noticed. The ownership data was
present and machine-readable the whole time -- ``roadmap_lint`` already parses
``Key files`` into ``Phase.key_files`` and already ERRORS when a phase omits them.
Nothing consumed it as ownership.

Deliberately ADVISORY in this first form: it annotates, it never fails. A gate
that blocks merges is only worth turning on once its false-positive rate has been
measured against real history (``--report`` over merged PRs). Shipping it
blocking-first would red the repo on the day it landed, which is how a gate gets
disabled rather than fixed.

This module IMPORTS ``roadmap_lint`` rather than editing it: that file belongs to
Phase 0 (LEGIBLE), and the point of this check is to stop people writing into
another phase's files. Doing so while building it would be a poor advertisement.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .roadmap_lint import Phase, _extract_phases

#: A PR body/commit trailer that records a deliberate edit into an owned file.
#: The goal is NOT to prevent the edit -- an urgent fix in a reserved file is a
#: real thing, and a gate nobody can clear in an emergency is a gate everyone
#: learns to route around. The goal is to make it impossible to make the edit
#: ACCIDENTALLY AND SILENTLY, which is the failure this exists for.
DISPOSITION_TRAILER = "Roadmap-Disposition:"


class RoadmapUnreadable(RuntimeError):
    """The roadmap could not be resolved or parsed.

    Raised rather than returning "no findings". A preflight that silently passes
    when it cannot read its own ownership map is the exact absence-reads-as-success
    failure this repo keeps hitting (ah#618, ah#545, ah#630) -- it would report
    green for every PR the moment the roadmap moved.
    """


@dataclass(frozen=True)
class Ownership:
    """One changed path and the phase that claims it."""

    path: str
    phase_alias: str
    phase_name: str
    is_current: bool


def resolve_roadmap(repo: Path) -> Path:
    """The roadmap the runner is actually driving.

    ``.phase-loop/state.json`` names it explicitly; that is authoritative because
    it is what the runner reads. The glob is only a fallback for a checkout with
    no runner state, and picks the highest version -- note ``v10`` sorts BEFORE
    ``v7`` lexically, so the sort is numeric.
    """

    state = repo / ".phase-loop" / "state.json"
    if state.is_file():
        try:
            declared = json.loads(state.read_text()).get("roadmap")
        except (OSError, ValueError):
            declared = None
        if declared:
            path = Path(declared)
            if not path.is_absolute():
                path = repo / path
            if path.is_file():
                return path

    candidates = sorted(
        (repo / "specs").glob("phase-plans-v*.md"),
        key=lambda p: _version_key(p.name),
    )
    if not candidates:
        raise RoadmapUnreadable(
            f"no roadmap found: {state} names none and specs/phase-plans-v*.md "
            f"matched nothing under {repo}"
        )
    return candidates[-1]


def _version_key(name: str) -> Tuple[int, str]:
    digits = "".join(c for c in name.split("-v")[-1] if c.isdigit())
    return (int(digits) if digits else -1, name)


def current_phase(repo: Path) -> Optional[str]:
    state = repo / ".phase-loop" / "state.json"
    if not state.is_file():
        return None
    try:
        return json.loads(state.read_text()).get("current_phase")
    except (OSError, ValueError):
        return None


def _strip_token(raw: str) -> str:
    """`Key files` entries are markdown bullets, usually backticked."""

    return raw.strip().strip("`").strip()


def ownership_map(roadmap_text: str) -> Dict[str, List[Phase]]:
    """path -> the phases claiming it.

    A LIST, not one phase: `runner.py` legitimately appears under several phases,
    and collapsing that would silently drop a claim.

    Fails loudly on an empty map. ``roadmap_lint`` already errors when a phase has
    no ``Key files``, so an empty ownership map means the roadmap moved out from
    under this parser -- reporting "nothing is owned" would be a lie that reads as
    a pass on every PR.
    """

    phases = _extract_phases(roadmap_text)
    if not phases:
        raise RoadmapUnreadable(
            "parsed zero phases from the roadmap; refusing to report an empty "
            "ownership map (that would pass every PR)"
        )
    mapping: Dict[str, List[Phase]] = {}
    for phase in phases:
        for raw in phase.key_files:
            token = _strip_token(raw)
            if token:
                mapping.setdefault(token, []).append(phase)
    if not mapping:
        raise RoadmapUnreadable(
            f"parsed {len(phases)} phase(s) but no Key files entries; the roadmap "
            f"format changed and this check can no longer see ownership"
        )
    return mapping


def owners_for(path: str, mapping: Dict[str, List[Phase]]) -> List[Phase]:
    """Phases claiming ``path``, matching exact paths and directory prefixes.

    Directory prefixes matter: CONFORM claims ``conformance/_contract/``, and a PR
    editing a file beneath it is editing that phase's material.
    """

    hits: List[Phase] = []
    for owned, phases in mapping.items():
        if path == owned or (owned.endswith("/") and path.startswith(owned)):
            for phase in phases:
                if phase not in hits:
                    hits.append(phase)
    return hits


def changed_paths(repo: Path, base: str) -> List[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RoadmapUnreadable(
            f"could not list changed paths against {base}: "
            f"{result.stderr.strip() or 'git diff failed'}"
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


def audit(repo: Path, base: str) -> List[Ownership]:
    roadmap = resolve_roadmap(repo)
    mapping = ownership_map(roadmap.read_text(encoding="utf-8"))
    active = current_phase(repo)
    found: List[Ownership] = []
    for path in changed_paths(repo, base):
        for phase in owners_for(path, mapping):
            found.append(
                Ownership(
                    path=path,
                    phase_alias=phase.alias,
                    phase_name=phase.name,
                    is_current=(phase.alias == active),
                )
            )
    return found


def has_disposition(text: str) -> bool:
    return any(
        line.strip().startswith(DISPOSITION_TRAILER)
        for line in (text or "").splitlines()
    )


def render(found: Sequence[Ownership], disposition: bool) -> str:
    if not found:
        return "roadmap-ownership: OK — no changed path is claimed by a roadmap phase"
    lines = [
        f"roadmap-ownership: {len(found)} claimed path(s) — ADVISORY, not blocking",
        "",
    ]
    for own in sorted(found, key=lambda o: (o.path, o.phase_alias)):
        marker = " (CURRENT PHASE)" if own.is_current else ""
        lines.append(f"  • {own.path}")
        lines.append(f"      claimed by {own.phase_alias} — {own.phase_name}{marker}")
    lines += [
        "",
        "This is information, not a refusal. Editing a phase's Key files is often",
        "correct — an urgent fix does not stop being urgent because a roadmap names",
        "the file. What this prevents is doing it without knowing.",
        "",
        "Before continuing, check the phase for an authorization bar: those have",
        "lived in PR comments, not only in the roadmap (ah#354 said 'No SCHED runtime",
        "edits are authorized' and nothing in the roadmap file repeated it).",
    ]
    if disposition:
        lines += ["", f"A {DISPOSITION_TRAILER} trailer is present — recorded."]
    else:
        lines += [
            "",
            f"To record a deliberate edit, add a {DISPOSITION_TRAILER} <reason>",
            "trailer to the PR body.",
        ]
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="roadmap_ownership")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--body", default="", help="PR body, scanned for the trailer")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv[1:])

    try:
        found = audit(args.repo, args.base)
    except RoadmapUnreadable as exc:
        # Non-zero even in advisory mode: this is the check failing, not the PR.
        # Silence here would be indistinguishable from a clean run.
        print(f"roadmap-ownership: CANNOT EVALUATE — {exc}", file=sys.stderr)
        return 2

    disposition = has_disposition(args.body)
    if args.json:
        print(
            json.dumps(
                {
                    "claimed": [vars(o) for o in found],
                    "disposition_present": disposition,
                    "advisory": True,
                },
                indent=2,
            )
        )
    else:
        print(render(found, disposition))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
