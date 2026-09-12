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

SCOPE OF "no survivors": it is a claim about the guards ENUMERATED below, exercised by
`tests/test_phase_state_disagreement_312.py`. It is NOT a claim about the module, and not
about guards this matrix does not carry — two of the last four blocking findings lived in
guards it did not enumerate (r7's `slug`, r8's load path), so the qualification is
load-bearing rather than modesty.

SUBSTRATE, PROVEN RATHER THAN ASSUMED: the driver runs pytest with `cwd=<copytree copy>`
and no `PYTHONPATH`, which is exactly the shape that would silently exercise an installed
package and make every "caught" meaningless. Measured — a sentinel confined to the copy
reds that copy's suite (32 failed), while `import phase_loop_runtime` from the same cwd
raises `ModuleNotFoundError`, so the import resolves through pytest's rootdir insertion of
`src` and not a site package. (Technique from the ah#834 r8 fable seat.)
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
  """        attributable = _phase_attributable_records(
            entries, alias, in_scope,
            attribute_by_file=attribution_evidence_complete,
        )""",
  "        attributable = [e for e in entries if getattr(e, 'phase_alias', None) == alias]",
  "test_settlement_r2_a_DIFFERENT_roadmaps_completed_must_not_settle"),
 ("M7 a record naming NO plan file becomes attributable by file (r5)", P,
  "and plan_file(e) is not None\n            and plan_file(e) in scoped_files",
  "and plan_file(e) in scoped_files",
  "test_a_record_with_no_plan_file_is_not_attributable_by_file"),
 ("M8 the closure is seeded from OUT-OF-SCOPE records too", P,
  "    scoped_files = {plan_file(e) for e in own if in_scope(e, alias)}",
  "    scoped_files = {plan_file(e) for e in own}",
  "test_a_file_named_only_by_an_OUT_OF_SCOPE_record_does_not_seed_the_closure"),
 ("M12 the file arm guesses a roadmap from a CONTESTED file (r6 codex)", P,
  "            and plan_file(e) in scoped_files\n            and plan_file(e) not in contested_files)",
  "            and plan_file(e) in scoped_files)",
  "test_a_legacy_record_on_a_CONTESTED_file_settles_nothing"),
 ("M13 contested keyed on RECORD count, not distinct roadmaps", P,
  "    contested_files = {name for name, slugs in claimed_by.items() if len(slugs) > 1}",
  "    contested_files = {name for name in claimed_by}",
  "test_CONTESTED_counts_distinct_ROADMAPS_not_records"),
 # --- the slug normaliser: r5's defect on the SIBLING field (r7 fable F1) -----
 ("M15 the normaliser swallows a REAL foreign claim too", P,
  "    return stripped\n\n\ndef _phase_attributable_records",
  "    return None\n\n\ndef _phase_attributable_records",
  "test_a_ref_naming_a_REAL_OTHER_roadmap_is_still_out_of_scope"),
 ("M22 the slugless ref discards the roadmap named by its FILE (r8 codex)", P,
  '        ref_file = getattr(ref, "file", None)',
  "        ref_file = None",
  "test_a_slugless_ref_that_names_a_FOREIGN_roadmap_by_FILE_settles_nothing"),
 ("M23 the file fallback swallows a ref that names NOTHING (r7 F1 regression)", P,
  '            if stem not in ("", "None"):',
  "            if True:",
  "test_a_ref_that_names_NOTHING_AT_ALL_is_still_legacy"),
 # --- the exclusion set can only grow if a test pins it (r7 fable F2) ---------
 ("M16 _SNAPSHOT_EXCLUDED silently grows by `planned`", P,
  '_SNAPSHOT_EXCLUDED = frozenset({"unplanned"})',
  '_SNAPSHOT_EXCLUDED = frozenset({"unplanned", "planned"})',
  "test_manifest_done_vs_snapshot_PLANNED_is_reported"),
 # --- the loop guards --------------------------------------------------------
 ("M9 look up a phase the snapshot does not carry (r3)", P,
  "            # total silence rather than as an error. (r3, fable.)\n            continue",
  "            # total silence rather than as an error. (r3, fable.)\n            pass",
  "test_an_entry_for_a_phase_absent_from_the_snapshot_is_skipped_not_looked_up"),
 ("M10 a done record no longer settles the phase (r1)", P,
  "                continue            # a record reached done: the phase is settled",
  "                pass                # a record reached done: the phase is settled",
  "test_settlement_r1_same_file_committed_beside_completed"),
 # --- the class sweep: a parser value no guard handled (r7) -------------------
 ("M17 the alias census accepts a non-string (one entry silences EVERYTHING)", P,
  "        if isinstance(a, str) and a:",
  "        if a:",
  "test_a_malformed_phase_alias_does_not_SILENCE_THE_WHOLE_detector"),
 ("M18 the alias ORDER loop accepts a non-string", P,
  """        if (
            getattr(entry, "type", None) == "phase"
            and isinstance(alias, str) and alias and alias not in ordered_aliases
        ):""",
  """        if (
            getattr(entry, "type", None) == "phase"
            and alias and alias not in ordered_aliases
        ):""",
  "test_a_malformed_phase_alias_does_not_SILENCE_THE_WHOLE_detector"),
 # --- the LOAD: all-or-nothing vs per-row (r8 fable) --------------------------
 ("M19 render goes back to the all-or-nothing read_manifest", R,
  "        rows = parseable_plan_entries(Path(snapshot.repo))",
  "        from .plan_manifest import read_manifest, ParseablePlanRows\n        rows = ParseablePlanRows(entries=read_manifest(Path(snapshot.repo)).plans)",
  "test_a_parse_hostile_SIBLING_row_does_not_delete_an_EXPLICITLY_CLAIMED_report"),
 ("M20 the per-row parse swallows STRUCTURAL failures too", P,
  '        raise ValueError("manifest plans must be an array")\n    entries: list[DotfilesPlanEntry] = []',
  "        return ()\n    entries: list[DotfilesPlanEntry] = []",
  "test_a_STRUCTURAL_failure_still_hides_the_WHOLE_manifest"),
 ("M21 the load uses valid_phase_entries (drops a renamed plan file)", P,
  "    entries: list[DotfilesPlanEntry] = []\n    skipped = 0\n    for row in plans:",
  "    return ParseablePlanRows(entries=valid_phase_entries(manifest_path) or ())\n    entries: list[DotfilesPlanEntry] = []\n    skipped = 0\n    for row in plans:",
  "test_a_RENAMED_plan_file_is_still_reported"),
 # --- incomplete evidence must disable the GUESSING arms (r9 fable F1 + codex) -
 ("M24 the legacy admission ignores that a row was unparseable", P,
  "        if not attribution_evidence_complete:\n            return False",
  "        if False:\n            return False",
  "test_a_NO_CLAIM_record_is_REFUSED_while_a_row_is_unparseable"),
 ("M25 the file arm ignores that a row was unparseable", P,
  "        or (attribute_by_file and not claims_a_roadmap(e)",
  "        or (not claims_a_roadmap(e)",
  "test_a_skipped_FOREIGN_claimant_does_not_uncontest_a_file"),
 ("M26 render stops threading the skipped count", R,
  "            attribution_evidence_complete=rows.skipped == 0,",
  "            attribution_evidence_complete=True,",
  "test_a_NO_CLAIM_record_is_REFUSED_while_a_row_is_unparseable"),
 # --- the skipped-row exemption must be NARROW, both ways (r10 fable B1) ------
 ("M29 a skipped non-phase row disarms the guessing arms again", P,
  '            declared = row.get("type") if isinstance(row, dict) else None\n            if isinstance(declared, str) and declared != "phase":\n                continue',
  "            pass",
  "test_a_skipped_NON_PHASE_row_does_not_disarm_the_guessing_arms"),
 ("M30 the exemption widens to ANY skipped row", P,
  '            if isinstance(declared, str) and declared != "phase":',
  "            if True:",
  "test_a_skipped_row_that_MIGHT_have_been_a_phase_row_still_disarms"),
 ("M31 an unreadable `type` is treated as an exemption", P,
  '            if isinstance(declared, str) and declared != "phase":',
  '            if declared != "phase":',
  "test_a_skipped_row_that_MIGHT_have_been_a_phase_row_still_disarms"),
 # --- a row that PARSES but is unusable is lost evidence too (r10 codex) ------
 ("M32 an unusable phase alias no longer counts as lost evidence", P,
  "            if not (isinstance(candidate_alias, str) and candidate_alias):\n                attribution_evidence_complete = False\n                break",
  "            if False:\n                attribution_evidence_complete = False\n                break",
  "test_an_UNUSABLE_alias_counts_as_incomplete_evidence"),
 # --- the sixth surface: entry `type` (r9 fable F2) ---------------------------
 ("M27 a type:detailed row speaks for a phase again", P,
  '        and getattr(e, "type", None) == "phase"',
  "        and True",
  "test_a_type_DETAILED_row_does_not_speak_for_a_PHASE"),
 ("M28 the alias census counts non-phase rows", P,
  '        if getattr(e, "type", None) != "phase":\n            continue',
  "        if False:\n            continue",
  "test_a_DETAILED_row_does_not_make_an_alias_look_AMBIGUOUS"),
 # --- the operator surface ---------------------------------------------------
 ("M11 the header counts ROWS again, not phases (r2)", R,
  "len({phase for phase, _, _ in clashes})", "len(clashes)",
  "test_the_rendered_header_counts_PHASES_not_rows"),
]
# RECORDED EQUIVALENT #3 (was M14 until r8): dropping `_roadmap_claim`'s
# `isinstance(value, str)` guard. Until r8 this mutant was CAUGHT, because that guard was
# what made an empty/`"None"` slug read as "names nothing". r8 moved that property into
# the `stripped in ("", "None")` branch and its FILE fallback, which M23 and
# test_a_ref_that_names_NOTHING_AT_ALL_is_still_legacy now own. What the isinstance check
# still guards is a NON-STRING slug — and `_ref_from_json` coerces with `str(...)`, so no
# manifest this parser can produce reaches it. Every test built through `read_manifest`
# therefore passes with it removed.
#
# Kept anyway, and the reason is the r8 sweep's own finding: a truthy unhashable value
# returned from here flows into `claimed_by.setdefault(...).add(slug)` and raises
# `TypeError: unhashable type`, which `render.py`'s bare `except` turns into total silence
# for every phase — the exact hazard the `phase_alias` guards were added to close. Three
# guards doing the same arithmetic should not disagree about it. A latent-path guard, held
# deliberately, measured as equivalent rather than printed as a kill. (ah#832 r8, fable NB3.)
#
# RECORDED EQUIVALENT #2 (was M6 until r7): dropping the file arm's
# `not claims_a_roadmap(e)` clause. It is the r2 guard — three seats found that defect
# independently — and it is now SUBSUMED by M12's contested-file rule. Proof, and it turns
# on a DISTANT invariant, which is why the clause stays in the source:
#
#   1. The file arm is only consulted when `roadmap_slug is not None`. Otherwise
#      `in_scope` is True for every record and the `or` short-circuits before it.
#   2. With a roadmap slug set, a null-ref record is in scope only if its alias is
#      `_alias_counts` (search the symbol, not a line number — an earlier revision of
#      this proof cited :892-897, which at the current head is an unrelated comment; a
#      file:line anchor in a proof drifts with every edit and a seat caught this one)
#      counts every `phase` entry, so unambiguous means the alias appears exactly once,
#      i.e. `len(own) == 1`.
#   3. An alias with one record has no OTHER record to admit, so every seeder of
#      `scoped_files` is a record that explicitly claims the active roadmap.
#   4. Therefore a foreign explicit record sharing a seeded file always makes that file
#      contested ({active, foreign}), and M12's guard rejects it first.
#
# Step 2 depends on how ambiguity is COUNTED, two hundred lines away. Count it per
# roadmap instead and the subsumption silently fails, so the clause is kept as the local
# statement of the r2 rule rather than deleted on the strength of this argument.
# Measured: survives all 71 tests at this head. (ah#832 r7.)
#
# RECORDED EQUIVALENT #1, deliberately not in the matrix above: turning the
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
    # STRIP THE PARAMETRISATION before matching. pytest reports a parametrised failure as
    # `test_name[the case]`, and splitting on whitespace lands mid-bracket, so a
    # parametrised test can never match its own name and every mutant it catches scores
    # [WRONG-RED]. Found by the sibling matrix on itself, then reproduced here the moment
    # a parametrised test was added. (ah#832 r7 / ah#834 r7.)
    names = [l.split("::")[-1].split()[0].split("[")[0]
             for l in out.splitlines() if l.startswith("FAILED")]
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
