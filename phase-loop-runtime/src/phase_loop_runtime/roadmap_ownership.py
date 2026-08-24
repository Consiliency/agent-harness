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
measured against real history. NOTE: no measurement flag exists yet -- that is a
real gap, not an oversight to gloss (ah#633). Shipping it
blocking-first would red the repo on the day it landed, which is how a gate gets
disabled rather than fixed.

This module IMPORTS ``roadmap_lint`` rather than editing it: that file belongs to
Phase 0 (LEGIBLE), and the point of this check is to stop people writing into
another phase's files. Doing so while building it would be a poor advertisement.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .roadmap_lint import Phase, _extract_phases, declared_active_roadmap

#: A PR body/commit trailer that records a deliberate edit into an owned file.
#: The goal is NOT to prevent the edit -- an urgent fix in a reserved file is a
#: real thing, and a gate nobody can clear in an emergency is a gate everyone
#: learns to route around. The goal is to make it impossible to make the edit
#: ACCIDENTALLY AND SILENTLY, which is the failure this exists for.
DISPOSITION_TRAILER = "Roadmap-Disposition:"


#: Qualifications keyed "<alias>\\x00<token>", populated by ownership_map.
_NOTES: Dict[str, str] = {}


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
    #: The roadmap's own qualification on this claim, verbatim, or "".
    #: GOVLEAN writes "`<dir>/` (new evidence, lint, and governance modules)" --
    #: the parenthetical SCOPES the claim to part of that directory. Discarding it
    #: turns a scoped claim into a whole-directory claim, which is how this module
    #: briefly had GOVLEAN owning the entire source tree. The matcher cannot decide
    #: what the prose means, so it surfaces it instead of guessing either way.
    note: str = ""


def resolve_roadmap(repo: Path) -> Path:
    """The roadmap this repository declares ACTIVE.

    Delegates to `roadmap_lint.declared_active_roadmap`, which reads the registry
    at `specs/roadmap-status.json` -- the repository's own authority on which
    roadmap is selected, with `delivered` and `superseded` ones recorded alongside.

    An earlier version of this function hand-rolled the choice: state.json, then
    the numerically highest `phase-plans-v*.md`. That picks a SUPERSEDED roadmap
    the moment a higher-numbered one is delivered, and would then audit ownership
    against a map nobody is working from -- producing confident, wrong answers.
    Re-implementing a selection rule the repo already owns was the mistake; this
    check exists because I did not read what already existed.
    """

    try:
        return declared_active_roadmap(Path(repo))
    except Exception as exc:  # registry absent/unreadable, or no single active
        raise RoadmapUnreadable(
            f"could not determine the active roadmap for {repo}: {exc}. "
            f"Refusing to guess -- auditing ownership against the wrong roadmap "
            f"would produce credible-looking false results."
        ) from exc


def current_phase(repo: Path) -> Optional[str]:
    state = repo / ".phase-loop" / "state.json"
    if not state.is_file():
        return None
    try:
        return json.loads(state.read_text()).get("current_phase")
    except (OSError, ValueError):
        return None


_BACKTICKED = re.compile(r"`([^`]+)`")


def _strip_token(raw: str) -> str:
    """The PATH out of a `Key files` bullet.

    Bullets are not uniformly `` `path` ``. Real entries in this roadmap include
    an annotation after the path::

        - `phase-loop-runtime/src/phase_loop_runtime/` (new evidence, lint, ...)
        - `skills-src/` planner and roadmap skills plus regeneration outputs

    Stripping the whole bullet's outer backticks left the annotation attached, so
    the token never matched anything. My own dry-run of this module reported "no
    changed path is claimed" for a PR that edits two directories GOVLEAN claims --
    a FALSE NEGATIVE from the check whose entire purpose is not missing ownership.
    Take the first backticked span; fall back to the bare bullet when there is
    none.
    """

    return _split_token(raw)[0]


def _split_token(raw: str) -> "tuple[str, str]":
    """(path, qualification) from a `Key files` bullet."""

    raw = raw.strip()
    found = _BACKTICKED.search(raw)
    if not found:
        return raw, ""
    path = found.group(1).strip()
    rest = raw[found.end():].strip()
    return path, rest


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
    barren = [p.alias for p in phases if not p.key_files]
    if barren:
        # PARTIAL drift, which the all-or-nothing guards below cannot see: one
        # phase losing its `Key files` heading leaves the other phases' entries
        # intact, so the map looks healthy while that phase's claims vanish.
        # `roadmap_lint.check_phase_fields` already errors on this, so a phase
        # with none means the roadmap changed shape under this parser.
        raise RoadmapUnreadable(
            f"phase(s) {', '.join(barren)} declare no Key files; the roadmap "
            f"changed shape and their claims would silently disappear"
        )
    mapping: Dict[str, List[Phase]] = {}
    notes: Dict[str, str] = {}
    for phase in phases:
        for raw in phase.key_files:
            token, note = _split_token(raw)
            if token:
                mapping.setdefault(token, []).append(phase)
                if note:
                    notes[f"{phase.alias}\x00{token}"] = note
    _NOTES.clear()
    _NOTES.update(notes)
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
        if _claims(owned, path):
            for phase in phases:
                if phase not in hits:
                    hits.append(phase)
    return hits


def _claims(owned: str, path: str) -> bool:
    """Does an ownership token claim ``path``?

    Three token shapes appear in real `Key files` lists and all three must work:

    * exact file -- claims only itself;
    * directory (trailing ``/``) -- claims everything beneath it;
    * GLOB (``specs/phase-plans-v*.md``, LEGIBLE) -- claims what it matches.
      Stored literally, a glob matched nothing, so LEGIBLE's claim on every
      roadmap file was silently inert.
    """

    if path == owned:
        return True
    if owned.endswith("/") and path.startswith(owned):
        return True
    if any(ch in owned for ch in "*?[") and fnmatch.fnmatch(path, owned):
        return True
    return False


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
                    note=_note_for(phase.alias, path, mapping),
                )
            )
    return found


def _note_for(alias: str, path: str, mapping: Dict[str, List[Phase]]) -> str:
    for owned in mapping:
        if _claims(owned, path):
            note = _NOTES.get(f"{alias}\x00{owned}")
            if note:
                return note
    return ""


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
        if own.note:
            # The roadmap qualifies this claim. Shown verbatim rather than
            # interpreted: "(new evidence, lint, and governance modules)" scopes a
            # directory claim to part of it, and this matcher cannot tell which
            # part. Reporting the whole directory as owned would overstate;
            # dropping the entry would understate.
            lines.append(f"      SCOPED — the roadmap qualifies this: {own.note}")
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
        # stdout, not stderr: the workflow pipes stdout through `tee` into the job
        # summary. On stderr the reason vanished from the summary and lived only in
        # the raw log -- a check that cannot say WHY it failed where people look.
        print(f"roadmap-ownership: CANNOT EVALUATE — {exc}")
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
