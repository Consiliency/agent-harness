#!/usr/bin/env python3
"""Mutation matrix for the ah#312 phase-state disagreement detector (agent-harness#832).

This detector is the only thing that tells an operator the runner snapshot and
`plans/manifest.json` disagree about whether a phase finished, and `render.py` wraps it in
a bare `except Exception: return []` so `status` can never break. That means EVERY defect
here is silent: the detector does not misreport, it simply says nothing, and a silent
detector is indistinguishable from a clean repository. A green suite proves nothing on its
own — both blocking findings on this PR were statuses that could never be reported, found
by mutation and not by the suite.

Each mutant reverts ONE guard to the defect that actually shipped, or to the shape a board
seat showed was wrong, and the suite must turn RED **by a named test**. A mutant that is
genuinely EQUIVALENT is recorded as such with the argument, never quietly dropped.

    python3 phase-loop-runtime/scripts/mutate_phase_state_guards.py [repo-root]
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path
SRC = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
P = "phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py"
R = "phase-loop-runtime/src/phase_loop_runtime/render.py"
T = ["phase-loop-runtime/tests/test_phase_state_disagreement_312.py"]
# (name, file, old, new, MUST_FAIL) — the last element is the defect this mutant
# reintroduces, named by the test that exists to catch it. A mutant that reds the suite
# some OTHER way is not caught; it is a broken mutant.
MUTANTS = [
 # --- the two operands, and the hand-listing defect on each -------------------
 ("M1 manifest operand back to the shipped literal", P,
  "_MANIFEST_IN_FLIGHT = frozenset(TRANSITIONS)", '_MANIFEST_IN_FLIGHT = {"executing"}',
  "test_in_flight_set_is_derived_from_the_lifecycle_table"),
 ("M2 manifest operand widened to every status (sweeps in the terminal ones)", P,
  "_MANIFEST_IN_FLIGHT = frozenset(TRANSITIONS)", "_MANIFEST_IN_FLIGHT = frozenset(PLAN_STATUSES)",
  "test_terminal_manifest_statuses_are_never_in_flight"),
 ("M3 snapshot operand back to the r6 literal (drops `unknown`)", P,
  "_SNAPSHOT_IN_FLIGHT = frozenset(PHASE_STATUSES) - set(_SNAPSHOT_DONE) - _SNAPSHOT_EXCLUDED",
  '_SNAPSHOT_IN_FLIGHT = {\n    "executing", "planned", "blocked", "awaiting_phase_closeout", "executed",\n}',
  "test_the_DIRTY_TREE_disguise_of_executing_is_still_reported"),
 ("M4 snapshot operand sweeps in `unplanned` (the one enumerated exclusion)", P,
  "- set(_SNAPSHOT_DONE) - _SNAPSHOT_EXCLUDED", "- set(_SNAPSHOT_DONE)",
  "test_unplanned_phase_is_not_a_contradiction"),
 # --- attribution: the five settlement cases, one per round -------------------
 ("M5 attribute per RECORD again, not per phase (r5)", P,
  "        attributable = _phase_attributable_records(entries, alias, in_scope)",
  "        attributable = [e for e in entries if getattr(e, 'phase_alias', None) == alias]",
  "test_settlement_r2_a_DIFFERENT_roadmaps_completed_must_not_settle"),
 ("M6 the file arm lets a FOREIGN roadmap settle through a shared filename (r2)", P,
  "        or (not claims_a_roadmap(e) and plan_file(e) is not None",
  "        or (plan_file(e) is not None",
  "test_a_same_file_record_TAGGED_to_another_roadmap_does_not_settle"),
 ("M7 a record naming NO plan file becomes attributable by file (r5)", P,
  "and plan_file(e) is not None\n            and plan_file(e) in scoped_files",
  "and plan_file(e) in scoped_files",
  "test_a_record_with_no_plan_file_is_not_attributable_by_file"),
 ("M8 the closure is seeded from OUT-OF-SCOPE records too", P,
  "    scoped_files = {plan_file(e) for e in own if in_scope(e, alias)}",
  "    scoped_files = {plan_file(e) for e in own}",
  "test_a_file_named_only_by_an_OUT_OF_SCOPE_record_does_not_seed_the_closure"),
 # --- the loop guards --------------------------------------------------------
 ("M9 look up a phase the snapshot does not carry (r3)", P,
  "            # total silence rather than as an error. (r3, fable.)\n            continue",
  "            # total silence rather than as an error. (r3, fable.)\n            pass",
  "test_an_entry_for_a_phase_absent_from_the_snapshot_is_skipped_not_looked_up"),
 ("M10 a done record no longer settles the phase (r1)", P,
  "                continue            # a record reached done: the phase is settled",
  "                pass                # a record reached done: the phase is settled",
  "test_settlement_r1_same_file_committed_beside_completed"),
 # --- the operator surface ---------------------------------------------------
 ("M11 the header counts ROWS again, not phases (r2)", R,
  "len({phase for phase, _, _ in clashes})", "len(clashes)",
  "test_the_rendered_header_counts_PHASES_not_rows"),
]
# RECORDED EQUIVALENT, deliberately not in the matrix above: turning the
# `if not attributable: continue` guard into `pass`. With no attributable record the
# status set is EMPTY, and the empty set intersects neither operand, so both branches
# append nothing whether the guard returns early or falls through. Measured: survives all
# tests. Asserted as an equivalence over the operands in
# test_the_ONLY_equivalent_continue_is_the_no_attributable_guard rather than faked as a
# behavioural test. (ah#832 r6.)

def run(root):
    r = subprocess.run(["python3","-m","pytest",*[str(Path(root)/t) for t in T],"-q","-p","no:cacheprovider"],
                       cwd=root, capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    tail = [l for l in out.strip().splitlines() if "passed" in l or "failed" in l]
    names = [l.split("::")[-1].split()[0] for l in out.splitlines() if l.startswith("FAILED")]
    # A COLLECTION OR IMPORT ERROR IS NOT A CAUGHT MUTANT. pytest exits non-zero for
    # those too, so classifying on the return code alone counts a broken mutant as a
    # kill — the exact false-"caught" mode this matrix exists to rule out, and the one
    # this script itself had. Exit 2 is usage/collection; an "errors" summary or a
    # zero-collection run is equally disqualifying. (ah#834 r3, codex.)
    # A KILL REQUIRES PYTEST'S ORDINARY FAILURE STATUS, NOT MERELY "NOT ZERO".
    #
    # pytest exits 1 for test failures, 2 for usage/collection, 3 for INTERNALERROR, 4
    # for a usage error. Rejecting only 2 let a run that printed the required FAILED line
    # and THEN crashed (INTERNALERROR, status 3) score as a kill: a genuine failure
    # followed by an invalid run is still an invalid run, because nothing downstream can
    # tell which of them the red belongs to. (ah#834 r5, codex.)
    invalid = (
        r.returncode not in (0, 1)
        or "INTERNALERROR" in out
        or " error" in (tail[-1] if tail else "")
        or "ERROR collecting" in out
        or "no tests ran" in out
    )
    # PIN THE COLLECTED COUNT. Classification is by failing test NAME, which cannot tell
    # "this mutant broke the guard" from "this mutant broke something else the named test
    # also touches" — a seat proved it by breaking the exception's message formatter,
    # leaving the guard intact, and scoring `caught`. Name-matching stays (cause-matching
    # would mean asserting on messages, which is its own trap), but a mutant that changes
    # what the suite COLLECTS is now invalid: that is the cheap, robust half of the
    # signal. (ah#834 r4, fable.)
    collected = None
    for line in tail:
        # `line.split()` leaves the comma attached in "1 failed, 107 passed", which
        # silently dropped the failure count and made every mutant look like it had
        # changed the suite size. Strip punctuation before matching the keyword.
        words = [w.strip(",.") for w in line.split()]
        counts = [int(tok) for tok, word in zip(words, words[1:])
                  if tok.isdigit() and word in ("passed", "failed", "skipped", "error", "errors")]
        if counts:
            collected = sum(counts)
            break
    return r.returncode, (tail[-1] if tail else "?"), names, invalid, collected
print("baseline (unmutated):")
rc, tail, _, invalid, BASELINE_COLLECTED = run(SRC)
print(f"  rc={rc}  {tail}  (collected {BASELINE_COLLECTED})")
if rc != 0 or invalid: sys.exit("baseline not green — fix that before mutating")
surv=[]
broken=[]
for name, rel, old, new, must_fail in MUTANTS:
    with tempfile.TemporaryDirectory(prefix="mut832-") as tmp:
        root = Path(tmp)/"repo"
        shutil.copytree(SRC, root, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        f = root/rel; text = f.read_text()
        if text.count(old) != 1:
            print(f"  [ANCHOR {'MISS' if old not in text else 'AMBIGUOUS'}] {name}")
            broken.append(name); continue
        f.write_text(text.replace(old,new,1))
        rc, tail, names, invalid, collected = run(root)
        if collected is not None and BASELINE_COLLECTED is not None and collected != BASELINE_COLLECTED:
            v, note = "BROKEN", (f"collected {collected} tests, baseline collected "
                                 f"{BASELINE_COLLECTED} — the mutant changed the SUITE, "
                                 "so a red proves nothing about the guard")
            broken.append(name)
        elif invalid:
            v, note = "BROKEN", "the run is invalid (collection/import error) — not a kill"
            broken.append(name)
        elif rc == 0:
            v, note = "SURVIVES", "the suite stayed green"
            surv.append(name)
        elif must_fail not in names:
            v, note = "WRONG-RED", f"red, but NOT via {must_fail} — a mutant that reds some other way is not caught"
            broken.append(name)
        else:
            v, note = "caught", f"via {must_fail}"
        print(f"  [{v:>9}] {name}\n             {tail}  {note}")
print()
if surv:  print("SURVIVORS (a real coverage gap; record it in-source, never hide it):", surv)
if broken: print("BROKEN MUTANTS (the matrix cannot vouch for these):", broken)
if not surv and not broken: print("no survivors; every kill verified by its named test")
# EXIT NON-ZERO so a survivor or a broken mutant cannot pass unnoticed in CI or a
# pre-merge check. Printing a problem and exiting 0 is how a checker gets ignored.
sys.exit(1 if (surv or broken) else 0)
