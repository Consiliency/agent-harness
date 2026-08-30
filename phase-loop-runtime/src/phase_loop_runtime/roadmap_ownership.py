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

The POST-hoc audit (``audit`` / ``--report``) is deliberately ADVISORY: it
annotates, it never fails. A gate that blocks merges is only worth turning on once
its flag rate has been measured against real history (the flag rate, not the
false-positive rate: nothing here establishes which flags were wrong) -- which is
what ``--report`` does. Shipping it blocking-first would red the repo on the day it
landed, which is how a gate gets disabled rather than fixed.

``--preflight`` is the PRE-edit question and is scriptable, so it does exit
non-zero -- 1 when somebody else claims a path, 2 when ownership cannot be
evaluated at all. Those two must never collide: a caller that reads "cannot
evaluate" as "you are blocked" (or the reverse) is exactly the confusion the
module exists to prevent, so every failure to resolve the roadmap is normalized
through ``resolve_roadmap`` into ``RoadmapUnreadable`` and reported as 2.

This module IMPORTS ``roadmap_lint`` rather than editing it: that file belongs to
Phase 0 (LEGIBLE), and the point of this check is to stop people writing into
another phase's files. Doing so while building it would be a poor advertisement.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import tempfile
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .roadmap_lint import (
    RoadmapStatusError,
    validate_roadmap_status_coherence,
)
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
        loaded = json.loads(state.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        # Valid JSON is not necessarily an OBJECT. A state file containing `[]`
        # reached `.get` on a list and raised AttributeError, which audit-mode
        # `main` does not catch -- exiting 1 with no ownership claim at all.
        return None
    return loaded.get("current_phase")


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
    if owned.endswith("/") and path.rstrip("/") == owned.rstrip("/"):
        # The directory ITSELF, spelled without the trailing slash. `--preflight`
        # normalizes through `Path.resolve()`, which drops it, so the exact token
        # the roadmap uses (`skills-src/`, `phase-loop-runtime/tests/`) arrived
        # here as `skills-src` and matched nothing: files UNDER a claimed
        # directory were flagged while the directory itself came back "no path is
        # claimed". Normalization preserves directory-ness now, and this handles
        # it from the other side too -- a fail-open on the most obvious spelling
        # of a claim is worth closing twice.
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


def read_roadmap(roadmap: Path) -> str:
    """The roadmap's text, with read failures normalized to ``RoadmapUnreadable``.

    ``resolve_roadmap`` normalizes RESOLUTION failures; this normalizes the READ.
    Both call sites need it and only ``preflight`` had it: an unreadable or
    non-UTF-8 roadmap escaped ``audit`` as an uncaught exception, and the
    interpreter's exit 1 is the code ``--preflight`` reserves for "claimed by
    another phase". Stated once here rather than at each call site, because the
    version of this fix that lived in one caller is exactly how the other kept
    the hole.
    """

    try:
        return roadmap.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RoadmapUnreadable(
            f"could not read the active roadmap {roadmap}: {exc}. Refusing to "
            f"report ownership from a roadmap this command cannot read."
        ) from exc


def audit(repo: Path, base: str) -> List[Ownership]:
    roadmap = resolve_roadmap(repo)
    mapping = ownership_map(read_roadmap(roadmap))
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
    """The qualification on the MOST SPECIFIC token claiming ``path``.

    A phase can claim both a file and its parent directory with different
    qualifications -- GOVLEAN does exactly that in v10. Returning the first
    match made the answer depend on bullet ORDER in the roadmap: reordering two
    semantically identical lines could replace an exact file's narrow
    qualification with the broad directory note, which silently widens the scope
    a reader believes they have.

    Ranked, most specific first:

    1. an EXACT token (``owned == path``) -- it claims that path and nothing else;
    2. otherwise, the longest LITERAL PREFIX (the part before the first wildcard),
       because that prefix is what actually bounds the claim;
    3. then overall length, as a tie-break within the same prefix.

    Two earlier versions of this ranking were wrong in opposite directions, and
    both are worth naming because the shape recurs:

    * **Raw length** -- ``src/beta/[xyz][.]py`` is 19 characters and matches the
      13-character ``src/beta/x.py``, so a longer GLOB outranked the exact file.
    * **Literal-beats-glob** -- the repair for that ranked any token without a
      wildcard above any token with one, so the broad directory ``src/beta/``
      outranked the far narrower ``src/beta/parser_*.py``. A glob character says
      nothing about breadth; where the wildcard SITS does.

    Both produced the same user-visible error the ordering fix existed to stop:
    a broad qualification attached to a narrow path.
    """

    # Scoped to THIS alias. The round-3 filter `_NOTES.get(f"{alias}\x00{owned}")`
    # was quietly doing two jobs: skipping unqualified tokens, and keeping the
    # ranking inside one phase. Round 4 removed both, and only the first removal
    # was intended -- so another phase's exact claim won the global rank and
    # GOVLEAN's scoped directory note vanished from every file some other phase
    # names exactly (`runner.py`, `test_reviewtruth_phase.py`, dozens more on live
    # v10). That is a scoped claim presented as unconditional: the exact failure
    # `Ownership.note` exists to prevent.
    matches = [
        owned
        for owned, phases in mapping.items()
        if _claims(owned, path) and any(p.alias == alias for p in phases)
    ]
    if not matches:
        return ""

    def note_of(owned: str) -> str:
        return _NOTES.get(f"{alias}\x00{owned}", "")

    # An EXACT token claims this path and nothing else, so a qualification on it
    # describes this path unambiguously and needs no attribution.
    for owned in matches:
        if owned == path and note_of(owned):
            return note_of(owned)

    # Every other qualification is ATTRIBUTED to the token carrying it.
    #
    # Returning a bare note was the last form of the recurring defect: given a
    # qualified `src/beta/` and an UNQUALIFIED `src/beta/parser_*.py`, the
    # directory's "(the whole lane-B tree)" came back as the qualification on
    # `parser_impl.py` -- a broader qualification attached to a narrower,
    # unconditional claim, for the fourth time.
    #
    # The bug was never the ordering; it was reporting a qualification without
    # saying WHICH claim it qualifies. Naming the token makes the misattribution
    # unrepresentable, so no ranking is needed and none is attempted -- for two
    # globs sharing a literal prefix, breadth is not length anyway (`[a]*.py` is
    # narrower than `[a-z]*.py` and shorter), so no honest total order exists.
    attributed = sorted(
        f"`{owned}` {note_of(owned)}" for owned in matches if note_of(owned)
    )
    return " | ".join(attributed)


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


def _git(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _roadmap_rel_at(repo: Path, sha: str, tmp_root: Path) -> "tuple[Optional[str], Optional[str]]":
    """Which roadmap was GOVERNING at ``sha``, decided by the CANONICAL readers
    against a REAL checkout of that commit.

    Nothing about the authority rules is re-implemented here, and nothing about
    the repository is emulated. Earlier versions did both, and each approximation
    was wrong where the real thing was not:

    * a private JSON reader drifted from the canonical schema rules;
    * `parse_roadmap_status_manifest` alone checks schema but explicitly NOT
      banner coherence or tracked-path coverage;
    * hand-building a scratch index with ``git add -A`` loses file modes and
      lets ignore rules and host git config decide what is "tracked", while
      `validate_roadmap_status_coherence` depends on the exact ``git ls-files``
      set.

    So the commit gets an actual detached worktree, sparse-checked-out to the
    paths the validators read. The index is git's own, built from the commit,
    so modes and tracked-path coverage are exact rather than reconstructed.

    Fails CLOSED: any git failure yields an unscorable reason. A materialization
    that half-succeeded must never be scored as if it were the commit. Only the
    ``worktree add`` failure is test-pinned -- the sparse-checkout and checkout
    failures are defensive against git I/O errors that are not reliably
    inducible in a fixture, and are not claimed as covered.
    """

    wt = tmp_root / f"wt-{sha[:12]}"
    add = _git(["-C", str(repo), "worktree", "add", "--detach", "--no-checkout",
                "-q", str(wt), sha])
    if add.returncode != 0:
        return None, f"could not check out commit: {add.stderr.strip()[:80]}"
    try:
        # `plans/` carries the versioned marker the canonical validator uses to
        # tell a post-registry commit (registry REQUIRED) from a legacy one.
        sparse = _git(["-C", str(wt), "sparse-checkout", "set", "--no-cone",
                       "/specs/", "/plans/"])
        if sparse.returncode != 0:
            return None, f"could not scope checkout: {sparse.stderr.strip()[:80]}"
        checkout = _git(["-C", str(wt), "checkout"])
        if checkout.returncode != 0:
            return None, f"could not populate checkout: {checkout.stderr.strip()[:80]}"
        try:
            # required=False, DELIBERATELY -- and this is the one place a
            # reviewer's `required=True` recommendation was not taken.
            #
            # `required=True` demands a registry wherever the versioned LEGIBLE
            # marker exists. That is the right rule for the working tree, but
            # applying it to history is an anachronism: the marker predates the
            # registry, which arrived 2026-08-03. Measured on this repo, a
            # 150-commit window contains 19 commits carrying the marker with no
            # registry -- an era that simply had no registry to carry, not an
            # era of incoherent ones. Under `required=True` all 19 are ejected
            # as MalformedRegistryError, shrinking the denominator by 13% on
            # exactly the false basis this module counts unscorable rows to
            # prevent.
            #
            # Replay asks what a commit DECLARED, not whether it would satisfy
            # today's rules. `required=False` asks the first question.
            status = validate_roadmap_status_coherence(wt, required=False)
        except RoadmapStatusError as exc:
            return None, f"roadmap authority incoherent at commit: {type(exc).__name__}"
        if status is not None:
            return status["selected_roadmap"], None
        try:
            resolved = declared_active_roadmap(wt)
        except RoadmapStatusError as exc:
            return None, f"no active roadmap declared at commit: {type(exc).__name__}"
        try:
            return resolved.relative_to(wt.resolve()).as_posix(), None
        except ValueError:
            return None, "roadmap resolved outside the commit tree"
    finally:
        _git(["-C", str(repo), "worktree", "remove", "--force", str(wt)])
        _git(["-C", str(repo), "worktree", "prune"])


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

    with tempfile.TemporaryDirectory(prefix="roadmap-replay-") as tmp_root:
        return _replay_rows(repo, limit, rev, Path(tmp_root))


def _replay_rows(repo: Path, limit: int, rev: str, tmp_root: Path) -> List[ReplayRow]:
    rows: List[ReplayRow] = []
    for sha, subject in _landed_commits(repo, limit, rev):
        rel_at_sha, registry_reason = _roadmap_rel_at(repo, sha, tmp_root)
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


def _most_relievable_phase(
    flagged: Sequence[ReplayRow], counts: Dict[str, int]
) -> str:
    """The phase whose removal would clear the MOST changes.

    The counterfactual exists to steer remediation, so the phase it names should
    be the one worth narrowing. Frequency is the wrong ranking for that: a phase
    can appear on many rows while sole-claiming none of them, in which case
    narrowing it clears nothing at all. What a reader can act on is the number of
    rows a phase claims ALONE, because those are exactly the rows its removal
    frees.

    The two agree whenever one phase dominates -- on this repo GOVLEAN sole-claims
    23 of 33 flagged rows -- which is why the frequency version reported the right
    figure. They diverge under skewed overlap, and there the frequency pick
    understates what narrowing could achieve.

    Ties break on frequency, then alias, so the choice is deterministic and, when
    nothing is solely claimed, still lands on the phase a reader would expect.
    """

    def solely_claimed(alias: str) -> int:
        return sum(1 for r in flagged if set(r.phases) == {alias})

    return sorted(
        counts, key=lambda a: (-solely_claimed(a), -counts[a], a)
    )[0]


def preflight(
    repo: Path, paths: Sequence[str], current_phase: str | None = None
) -> Dict[str, List[Ownership]]:
    """Which phases claim each of ``paths`` -- the pre-EDIT question.

    agent-harness#633 asks for a gate that fails a change touching a BLOCKED phase's key
    files. Ownership is machine-readable and answered exactly here; **block state
    is not**, so this reports and does not decide.

    Measured, not assumed: scanning phase bodies for a ``BLOCKED`` marker matches
    6 phases in v10 of which exactly ONE is a real phase-level block. The others
    are exit-criteria prose containing ``OUTCOME_AMBIGUOUS_BLOCKED``, "a merge
    blocked on president-unavailability", and similar. A gate keyed on that
    signal would fire falsely on five phases, so this deliberately stops at
    ownership and leaves the disposition to a reader who can see the phase.

    ``current_phase`` excludes your own phase, which is the form the question
    actually takes: "does this path belong to somebody ELSE?"

    Resolution goes through ``resolve_roadmap``, NOT ``declared_active_roadmap``
    directly. The raw reader raises ``RoadmapStatusError`` subclasses that no
    caller here catches, so an incoherent roadmap escaped as an uncaught exception
    and Python exited 1 -- the code this command defines as "claimed by another
    phase". "I cannot tell" then read as "you are blocked". ``resolve_roadmap``
    normalizes every such failure into ``RoadmapUnreadable``, which the CLI maps
    to 2.

    Paths are normalized before matching, and an uninterpretable one RAISES rather
    than being skipped -- see ``_normalize_preflight_path``.
    """

    repo = Path(repo)
    mapping = ownership_map(read_roadmap(resolve_roadmap(repo)))
    owned: Dict[str, List[Ownership]] = {}
    for raw in paths:
        claims: List[Ownership] = []
        seen: set = set()
        for path in _preflight_identities(repo, raw):
            for phase in owners_for(path, mapping):
                if phase.alias == current_phase or (phase.alias, path) in seen:
                    continue
                seen.add((phase.alias, path))
                claims.append(
                    Ownership(
                        path=path,
                        phase_alias=phase.alias,
                        phase_name=phase.name,
                        is_current=False,
                        note=_note_for(phase.alias, path, mapping),
                    )
                )
        if claims:
            owned[raw] = sorted(claims, key=lambda o: (o.phase_alias, o.path))
    return owned


class PathNotInRepo(ValueError):
    """A ``--preflight`` argument that cannot be read as a path inside the repo.

    Raised rather than skipped. Skipping an argument this command cannot
    interpret makes it vanish from the result, and an empty result is printed as
    "no path is claimed" and exits 0 -- a clean bill of health produced by not
    having looked. Same absence-reads-as-success shape as ``RoadmapUnreadable``.
    """


def _preflight_identities(repo: Path, raw: str) -> List[str]:
    """Every repo-relative POSIX identity a ``--preflight`` argument denotes.

    Ownership tokens in the roadmap are repo-relative (``phase-loop-runtime/src/...``)
    and ``_claims`` compares them by exact match or ``str.startswith``. So the
    matcher only ever saw the argument as typed, and the SAME file answered
    differently depending on how it was written::

        phase-loop-runtime/src/.../roadmap_ownership.py   -> exit 1, claimed
        ./phase-loop-runtime/src/.../roadmap_ownership.py -> exit 0, "no path is claimed"
        /abs/path/to/.../roadmap_ownership.py             -> exit 0, "no path is claimed"

    Both false-clear forms are what a human or an agent actually types -- shell tab
    completion produces ``./``, and tooling passes absolute paths. A safety
    preflight whose answer depends on the spelling of its input is worse than none,
    because the wrong answer is the reassuring one. ``audit`` never hit this: its
    paths come from ``git diff --name-only``, which is always repo-relative.

    Normalization is LEXICAL first and only falls back to symlink resolution.
    Resolving first was wrong: it rewrites a repo-internal symlink to its target,
    so a `bin/` ownership token whose directory links elsewhere in the tree
    normalized to the target's path and matched no token -- pasting the roadmap's
    own text exited 0 as unclaimed. Ownership is a statement about the repository's
    PATHS, not about where those paths happen to point. The resolving fallback
    remains for the case that motivated it: a symlinked CHECKOUT ROOT
    (``/mnt/workspace`` -> ``/mnt/HC_Volume_...``), where the lexical form is
    genuinely outside the root as written.
    """

    if not raw:
        raise PathNotInRepo(
            "an empty --preflight argument names no path. Refusing to report it "
            "as unclaimed -- it matches no ownership token, so it would exit 0."
        )
    root_lexical = Path(os.path.normpath(os.path.abspath(str(Path(repo)))))
    try:
        root = Path(repo).resolve()
    except (OSError, RuntimeError) as exc:
        # `Path.resolve()` raises RuntimeError on a symlink loop and OSError on
        # assorted filesystem failures. Uncaught, either escaped `main` as the
        # interpreter's exit 1 -- the code reserved for "claimed by another phase".
        raise PathNotInRepo(
            f"could not resolve the repository root {Path(repo)}: {exc}"
        ) from exc
    candidate = Path(raw)
    uncollapsed = candidate if candidate.is_absolute() else root_lexical / candidate
    lexical = Path(os.path.normpath(str(uncollapsed)))
    try:
        # Resolve the UNCOLLAPSED path. Resolving the lexical form instead is
        # useless as a safety check: `os.path.normpath` has already erased the
        # symlink that `..` crossed, so `resolve()` never sees it and reports the
        # rewritten path as inside. The first version of this guard made exactly
        # that mistake and its own test caught it.
        resolved = uncollapsed.resolve()
    except (OSError, RuntimeError) as exc:
        raise PathNotInRepo(
            f"could not resolve {raw!r}: {exc}. Refusing to report it as "
            f"unclaimed -- this command could not evaluate it at all."
        ) from exc
    # Containment is checked against the RESOLVED path regardless of which form
    # supplies the answer. Lexical `..` collapsing is not filesystem-truthful: it
    # erases a symlink before the check, so with `/var/run -> /run` the argument
    # `run/../etc/passwd` reads as `/var/etc/passwd` -- inside -- while it really
    # resolves to `/etc/passwd`, outside. Ownership would then be evaluated for a
    # path the caller never named.
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathNotInRepo(
            f"{raw!r} resolves to {resolved}, outside {root}. Refusing to report "
            f"it as unclaimed -- this command cannot evaluate ownership for a "
            f"path it cannot place in the repository."
        ) from exc
    # BOTH identities are returned; neither is chosen. Every attempt to pick one
    # was wrong in one direction or the other, and the panel found each:
    #
    #   lexical only    a path under a symlinked directory is evaluated only under
    #                   the link's name. If ALPHA owns `src/link/` and BETA owns
    #                   `src/real/` with `link -> real`, ALPHA preflighting
    #                   `src/link/owned.py` is filtered as its own phase and exits
    #                   0 -- while the edit mutates BETA's file.
    #   resolved only   `Path.resolve()` realpaths EVERY component, not just a
    #                   symlink that `..` cancelled, so a token naming the symlink
    #                   stops matching and the answer names a path the caller did
    #                   not.
    #
    # An edit through a symlink mutates both the name the caller typed and the
    # bytes the target owns, so both are genuinely the caller's business and the
    # union is not a hedge -- it is the answer. Same shape as the qualification
    # fix one function up: the bug was trying to choose.
    #
    # BUT the lexical form is only an identity the argument DENOTES when no `..`
    # cancelled a symlink. With `link -> a/b`, `link/../owned.py` denotes
    # `a/owned.py`; the lexical `owned.py` is neither the name typed nor the bytes
    # written -- it is a phantom. Unioning it produced the two failures both seats
    # found in round 7:
    #
    #   false claim (exit 1)   whoever owns `owned.py` is reported for an edit
    #                          that never touches it.
    #   false abort (exit 2)   `link/..` collapses lexically to `.`, tripping the
    #                          whole-repository guard, although it resolves to the
    #                          perfectly ordinary directory `a/`.
    #
    # Round 6 had this right and round 7 dropped it while adding the union. Both
    # are needed: union when the lexical form is sound, resolved alone when it is
    # not.
    sources = [(resolved, root)]
    if ".." not in candidate.parts:
        sources.insert(0, (lexical, root_lexical))
    forms: List[str] = []
    for base, base_root in sources:
        try:
            relative = base.relative_to(base_root).as_posix()
        except ValueError:
            # The lexical form of a symlinked CHECKOUT ROOT legitimately sits
            # outside the lexical root; the resolved form covers it.
            continue
        if relative == ".":
            # `""`, `.`, and the absolute repo root land here. None matches any
            # ownership token, so each exited 0 -- "the whole repository is
            # unclaimed", the most confidently wrong answer this command can give.
            # Skipped rather than raised, then reported once below if NOTHING
            # survives. That mattered in round 7, where the lexical form was
            # unioned unconditionally: `link/..` collapsed lexically to `.` and
            # aborted the argument before the real identity `a/` was reached.
            # Excluding the unsound lexical form already removes that case, so
            # skipping is now equivalent to raising here -- verified: no input
            # produces a `.` identity beside a non-`.` sibling. Kept as the
            # single-exit shape rather than a claimed guard.
            continue
        # `Path.resolve()` drops a trailing slash, but `_claims` reads that slash
        # as the marker of a DIRECTORY token. Losing it turned the roadmap's own
        # spelling of a claim (`skills-src/`) into an unclaimed path.
        directoryish = base.is_dir() or (
            raw.endswith(("/", os.sep)) and not base.is_file()
        )
        form = f"{relative}/" if directoryish else relative
        if form not in forms:
            forms.append(form)
    if not forms:
        raise PathNotInRepo(
            f"{raw!r} resolves to the repository root. Ownership is per-path; "
            f"this command cannot evaluate a whole-repository scope, and must "
            f"not report one as unclaimed."
        )
    return forms


def render_preflight(
    owned: Dict[str, List[Ownership]], current_phase: str | None = None
) -> str:
    # "another phase" is only true when a current phase was named to be excluded.
    # Without --current-phase the question is "does ANY phase claim this?", and
    # calling the answer "another phase" implies an exclusion that never happened.
    other = "another phase" if current_phase else "a phase"
    if not owned:
        scope = f" outside {current_phase}" if current_phase else ""
        return f"roadmap-ownership --preflight: no path is claimed by a phase{scope}."
    lines = [
        f"roadmap-ownership --preflight: {len(owned)} path(s) claimed by {other}.",
        "",
        "  Ownership is machine-readable; BLOCK STATE IS NOT (agent-harness#633). Read the",
        "  owning phase before editing -- this reports, it does not authorize.",
        "",
    ]
    for path in sorted(owned):
        lines.append(f"    {path}")
        for own in owned[path]:
            lines.append(f"        claimed by: {own.phase_alias} — {own.phase_name}")
            if own.note:
                # Verbatim, for the same reason `audit` does it: a parenthetical
                # like "(new evidence, lint, and governance modules)" scopes a
                # directory claim to PART of that directory, and this matcher
                # cannot tell which part. Dropping it presents a scoped claim as
                # an unconditional one -- the reading that once had GOVLEAN
                # owning the whole source tree.
                lines.append(
                    f"            SCOPED — the roadmap qualifies this: {own.note}"
                )
    return "\n".join(lines)


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
        relievable = _most_relievable_phase(flagged, counts)
        remaining = [r for r in flagged if set(r.phases) - {relievable}]
        rpct = 100.0 * len(remaining) / len(scored)
        lines += ["", f"  counterfactual — if {relievable} claimed nothing:"]
        lines.append(f"    would STILL flag: {len(remaining)}/{len(scored)} ({rpct:.0f}%)")
        if len(remaining) == len(flagged):
            # Removing it changes nothing, so it is not even necessary --
            # calling it necessary here would misdirect the remediation.
            lines.append(
                f"    ^ {relievable} is NOT the binding constraint: every flagged "
                "change is claimed by some other phase as well."
            )
        elif remaining:
            lines.append(
                f"    ^ narrowing {relievable} is NECESSARY but NOT SUFFICIENT — "
                f"{len(remaining)} change(s) are claimed by other phases too."
            )
        else:
            lines.append(
                f"    ^ {relievable} is the sole cause; narrowing it alone would "
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
        "--preflight", nargs="+", metavar="PATH",
        help="before editing: report which phases claim these paths; exit 1 if any is "
             "claimed by a phase other than --current-phase",
    )
    parser.add_argument("--current-phase", default=None)
    parser.add_argument(
        "--report",
        type=int,
        metavar="N",
        help="replay the check over the last N landed changes (merge OR squash) and print the flag rate; "
             "this is the measurement a graduation decision needs",
    )
    args = parser.parse_args(argv[1:])

    if args.preflight:
        try:
            owned = preflight(args.repo, args.preflight, args.current_phase)
        except (RoadmapUnreadable, PathNotInRepo) as exc:
            # BOTH map to 2, never to 1. Exit 1 means "somebody else claims this";
            # anything that means "I could not evaluate" must be distinguishable
            # from it, or a caller reads a broken roadmap as an ownership block.
            print(f"roadmap-ownership: CANNOT EVALUATE — {exc}")
            return 2
        print(render_preflight(owned, args.current_phase))
        return 1 if owned else 0

    if args.report is not None:
        if args.report < 0:
            # `git log -n -1` is not "one"; it is unlimited. A negative N would
            # silently replay all of history rather than fail.
            print("roadmap-ownership: --report N must be >= 0")
            return 2
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


def console_main() -> int:
    """Console-script entrypoint (``roadmap-ownership``).

    A ``[project.scripts]`` target is invoked with NO arguments, so it cannot be
    ``main`` directly -- that signature takes an argv list.

    Needed for the same reason ``phase-loop-closeout-audit`` is (ah#670, ah#693):
    the primary installer is ``uv tool install``, which puts the package in an
    isolated environment where ``python -m phase_loop_runtime.roadmap_ownership``
    fails to import. That import failure exits 1 -- the exact code ``--preflight``
    defines as "claimed by another phase" -- so on the supported install a tool
    with only a module form reports a phantom ownership block for every path. A
    guard whose failure mode is a false BLOCK gets switched off.
    """

    return main(sys.argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
