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
that blocks merges is only worth turning on once its flag rate has been measured
against real history (the flag rate, not the false-positive rate: nothing here
establishes which flags were wrong) -- which is what ``--report`` does. Shipping it
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

from .roadmap_lint import ROADMAP_STATUS_REGISTRY_REL, Phase, _extract_phases, declared_active_roadmap

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


#: Claims that fire on nearly every PR, and why each is expected rather than
#: informative. `CHANGELOG.md` is claimed by RELEASE while the docs-audit gate
#: REQUIRES a CHANGELOG entry for any public-surface change -- so the two rules
#: together make the flag near-universal.
#:
#: These are DEMOTED, never dropped. A warning that fires on every PR is tuned out
#: within a week, and then the substantive findings underneath it are tuned out
#: too. Hiding them would be worse: the claim is real and a reader deciding
#: whether to add a disposition needs to see it. So they move below the fold with
#: the reason attached.
EXPECTED_CLAIMS: Dict[str, str] = {
    "CHANGELOG.md": "docs-audit requires an entry for public-surface changes",
}


def render(found: Sequence[Ownership], disposition: bool) -> str:
    if not found:
        return "roadmap-ownership: OK — no changed path is claimed by a roadmap phase"

    expected = [o for o in found if o.path in EXPECTED_CLAIMS]
    notable = [o for o in found if o.path not in EXPECTED_CLAIMS]

    if not notable:
        head = (
            f"roadmap-ownership: OK — no notable claims "
            f"({len(expected)} expected, listed below)"
        )
    else:
        head = (
            f"roadmap-ownership: {len(notable)} claimed path(s) — ADVISORY, not blocking"
        )
    lines = [head, ""]
    for own in sorted(notable, key=lambda o: (o.path, o.phase_alias)):
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
    if expected:
        lines += ["", "Expected — shown for completeness, not action:"]
        for own in sorted(expected, key=lambda o: (o.path, o.phase_alias)):
            lines.append(
                f"  · {own.path} — claimed by {own.phase_alias}; "
                f"{EXPECTED_CLAIMS[own.path]}"
            )
    if disposition:
        lines += ["", f"A {DISPOSITION_TRAILER} trailer is present — recorded."]
    else:
        lines += [
            "",
            f"To record a deliberate edit, add a {DISPOSITION_TRAILER} <reason>",
            "trailer to the PR body.",
        ]
    return "\n".join(lines)


@dataclass(frozen=True)
class ReplayRow:
    """One historical merge, replayed."""

    sha: str
    subject: str
    notable: int
    expected: int
    phases: "tuple[str, ...]"
    skipped_reason: str = ""


def _landed_commits(repo: Path, limit: int, rev: str = "HEAD") -> List["tuple[str, str]"]:
    """The last ``limit`` changes that LANDED on this branch.

    ``--first-parent``, not ``--merges``. This repo lands PRs both ways -- the
    other agent's arrive as merge commits, mine arrive squashed -- and
    ``--merges`` silently samples only the first population. My own ah#644 and
    ah#650 were invisible to my own measurement, which is a sampling bias in the
    one number this tool exists to produce.

    First-parent gives exactly one entry per landed change of either shape, and
    ``<sha>^1..<sha>`` is the right diff for both: a merge's first parent is the
    previous mainline tip, and a squash commit's only parent is the same thing.
    """

    out = subprocess.run(
        # Space-separated, not a control character: a literal NUL in argv is
        # rejected by subprocess outright. The sha is fixed-width, so a single
        # split is unambiguous even when the subject contains spaces.
        #
        # `rev` is the MERGE TARGET, not HEAD. Run from a feature branch with no
        # revision, `git log` walks the branch: the top entries are the PR's own
        # unlanded commits, which displace real landings and silently make the
        # population "my branch" instead of "what landed". That is the same
        # sampling defect as `--merges`, one level up.
        ["git", "-C", str(repo), "log", "--first-parent", "-n", str(limit),
         "--format=%H %s", rev],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise RoadmapUnreadable(f"could not list landed commits: {out.stderr.strip()}")
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and len(parts[0]) == 40:
            rows.append((parts[0], parts[1]))
    return rows


def _roadmap_rel_at(repo: Path, sha: str, fallback_rel: str) -> "tuple[Optional[str], Optional[str]]":
    """Which roadmap was GOVERNING at ``sha``.

    Resolving the path once from HEAD and reading it at every historical commit
    is wrong across a roadmap version flip: pre-flip commits either read as
    "absent" or, worse, get scored against a file that existed only as an
    unratified draft. The registry is itself versioned, so ask it at each commit.

    Returns ``(roadmap_rel, unscorable_reason)``. An ABSENT registry falls back
    to the HEAD-resolved path -- the legacy/synthetic-repo case
    ``declared_active_roadmap`` also tolerates. A registry that is PRESENT but
    unreadable, or that names anything other than exactly one active roadmap,
    yields a reason instead: scoring it against HEAD's roadmap would measure it
    under a roadmap its own registry did not name.
    """

    out = subprocess.run(
        ["git", "-C", str(repo), "show", f"{sha}:{ROADMAP_STATUS_REGISTRY_REL}"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        # ABSENT registry is the legacy/synthetic case `declared_active_roadmap`
        # also tolerates: fall back, and score.
        return fallback_rel, None
    try:
        entries = json.loads(out.stdout).get("roadmaps", [])
    except (ValueError, AttributeError):
        return None, "roadmap registry unreadable at commit"
    active = [e.get("path") for e in entries if e.get("status") == "active"]
    if len(active) == 1 and active[0]:
        return active[0], None
    # PRESENT but incoherent is different: falling back to HEAD's roadmap would
    # silently score the commit against a roadmap that demonstrably was not the
    # one its own registry named. Everywhere else this module counts what it
    # cannot read and says why; do that here too rather than fail open.
    return None, f"roadmap registry at commit names {len(active)} active roadmaps"


def _is_shallow(repo: Path) -> bool:
    """A shallow clone's boundary commit also has no ``^1``.

    Reporting it as a root commit would misattribute a fetch-depth artifact to
    repo history -- and in a shallow CI checkout that is the common case, not the
    rare one.
    """

    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip() == "true"


def replay(repo: Path, limit: int, roadmap_rel: str, rev: str = "HEAD") -> List[ReplayRow]:
    """Replay the check over the last ``limit`` LANDED changes.

    Uses the roadmap **as it existed at each commit**, not today's. Measuring
    historical PRs against the current roadmap would answer "what would fire
    now", when the question a graduation decision needs is "what WOULD have
    fired" -- and `Key files` lists change, so those differ.

    WHICH roadmap is also resolved per commit, from the versioned registry at
    that sha -- not once from HEAD. A window crossing a version flip (v9 -> v10)
    would otherwise read pre-flip commits as "roadmap absent", or score them
    against a file that existed then only as an unratified draft.

    ``rev`` is the merge target. Sampling ``HEAD`` from a feature branch measures
    the branch, not what landed.

    A commit whose roadmap cannot be read is recorded with a reason and counted,
    never dropped. A silently shrinking denominator would flatter the rate, which
    is the one number this exists to produce honestly.
    """

    rows: List[ReplayRow] = []
    for sha, subject in _landed_commits(repo, limit, rev):
        rel_at_sha, registry_reason = _roadmap_rel_at(repo, sha, roadmap_rel)
        if registry_reason:
            rows.append(ReplayRow(sha, subject, 0, 0, (), registry_reason))
            continue
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{sha}:{rel_at_sha}"],
            capture_output=True, text=True, check=False,
        )
        if blob.returncode != 0:
            rows.append(ReplayRow(sha, subject, 0, 0, (), "roadmap absent at commit"))
            continue
        try:
            mapping = ownership_map(blob.stdout)
        except RoadmapUnreadable as exc:
            rows.append(ReplayRow(sha, subject, 0, 0, (), f"unparseable: {exc}"))
            continue
        has_parent = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"{sha}^1"],
            capture_output=True, text=True, check=False,
        )
        if has_parent.returncode != 0:
            # The root commit is the initial import: every path in the tree is
            # "changed", so scoring it would flag everything and distort the very
            # rate this produces. Unscorable with an accurate reason -- not the
            # generic "diff failed", which would misreport a normal repo boundary
            # as a tooling error.
            reason = ("shallow-clone boundary (no parent to diff)" if _is_shallow(repo)
                      else "root commit (no parent to diff)")
            rows.append(ReplayRow(sha, subject, 0, 0, (), reason))
            continue
        diff = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only", f"{sha}^1", sha],
            capture_output=True, text=True, check=False,
        )
        if diff.returncode != 0:
            rows.append(ReplayRow(sha, subject, 0, 0, (), "diff failed"))
            continue
        notable = expected = 0
        phases: List[str] = []
        for path in (p for p in diff.stdout.splitlines() if p.strip()):
            owners = owners_for(path, mapping)
            if not owners:
                continue
            if path in EXPECTED_CLAIMS:
                expected += 1
            else:
                notable += 1
                phases.extend(p.alias for p in owners)
        rows.append(ReplayRow(sha, subject, notable, expected, tuple(sorted(set(phases)))))
    return rows


def render_report(rows: Sequence[ReplayRow]) -> str:
    total = len(rows)
    skipped = [r for r in rows if r.skipped_reason]
    scored = [r for r in rows if not r.skipped_reason]
    flagged = [r for r in scored if r.notable]
    lines = [
        f"roadmap-ownership --report: {total} landed change(s) replayed "
        f"({len(scored)} scored, {len(skipped)} unscorable)",
        "",
    ]
    if scored:
        pct = 100.0 * len(flagged) / len(scored)
        lines.append(
            f"  would have flagged: {len(flagged)}/{len(scored)} ({pct:.0f}%)"
        )
        lines.append(
            "  ^ THIS is the graduation number. A blocking gate at this rate stops "
            f"{pct:.0f}% of merges."
        )
    counts: Dict[str, int] = {}
    for r in flagged:
        for a in r.phases:
            counts[a] = counts.get(a, 0) + 1
    if counts:
        lines += ["", "  by phase:"]
        for alias, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {alias:<14} {n}")
    if counts and scored:
        # Leave-one-phase-out. The headline rate answers "is blocking viable
        # NOW"; it does NOT answer "would narrowing the dominant claim make it
        # viable", which is the actual next decision. Reviewers read the first
        # number as licensing the second, so compute the second explicitly.
        #
        # Exact, not an estimate: `phases` aggregates the owners of a row's
        # notable paths, so a row survives the counterfactual iff some OTHER
        # phase still claims one of them.
        dominant = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        remaining = [r for r in flagged if set(r.phases) - {dominant}]
        rpct = 100.0 * len(remaining) / len(scored)
        lines += ["", f"  counterfactual — if {dominant} claimed nothing:"]
        lines.append(f"    would STILL flag: {len(remaining)}/{len(scored)} ({rpct:.0f}%)")
        if len(remaining) == len(flagged):
            # Removing it changes nothing, so it is not even necessary --
            # calling it necessary here would misdirect the remediation.
            lines.append(
                f"    ^ {dominant} is NOT the binding constraint: every flagged "
                "change is claimed by some other phase as well."
            )
        elif remaining:
            lines.append(
                f"    ^ narrowing {dominant} is NECESSARY but NOT SUFFICIENT — "
                f"{len(remaining)} change(s) are claimed by other phases too."
            )
        else:
            lines.append(
                f"    ^ {dominant} is the sole cause; narrowing it alone would "
                "clear the gate."
            )
    if skipped:
        # Counted, never dropped: a shrinking denominator flatters the rate.
        lines += ["", f"  unscorable ({len(skipped)}) — excluded from the rate:"]
        for r in skipped[:5]:
            lines.append(f"    {r.sha[:8]} {r.skipped_reason}")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="roadmap_ownership")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--body", default="", help="PR body, scanned for the trailer")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--report",
        type=int,
        metavar="N",
        help="replay the check over the last N landed changes (merge OR squash) and print the flag rate; "
             "this is the measurement a graduation decision needs",
    )
    args = parser.parse_args(argv[1:])

    if args.report is not None:
        try:
            roadmap_rel = str(
                resolve_roadmap(args.repo).relative_to(Path(args.repo).resolve())
            )
            rows = replay(args.repo, args.report, roadmap_rel, args.base)
        except RoadmapUnreadable as exc:
            print(f"roadmap-ownership: CANNOT EVALUATE — {exc}")
            return 2
        print(render_report(rows))
        # Nothing scored means the instrument failed to produce its number.
        # Exiting 0 there would read as "measured, and the answer was fine".
        # This includes the empty case (`--report 0`): a report over zero
        # changes is not a measurement, and the CHANGELOG promises fail-closed
        # without an exception for it.
        if not any(not r.skipped_reason for r in rows):
            return 2
        return 0

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
