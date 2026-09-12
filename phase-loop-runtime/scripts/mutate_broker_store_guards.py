#!/usr/bin/env python3
"""Mutation matrix for the broker store guards (agent-harness#789 / #834).

Every guard here protects a SEALED store whose replay decides `epoch_blocked`, and a
permanent ambiguity in it fail-closes a repository partition. A green suite proves
nothing on its own: agent-harness#789 opened because a forward-compatibility defect in
exactly this code was reachable and untested.

Each mutant reverts ONE guard to the defect that actually shipped, or to the shape a
board seat showed was wrong, and the suite must turn RED **by a named test** — not by a
collection error and not by a skip. A SURVIVOR is a real coverage gap and belongs in the
source as a recorded limitation, never hidden.

    python3 phase-loop-runtime/scripts/mutate_broker_store_guards.py [repo-root]
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path
SRC = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
E = "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/evidence.py"
C = "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py"
A = "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py"
T = ["phase-loop-runtime/tests/test_convergence_broker_credsep.py",
     "phase-loop-runtime/tests/test_broker_evidence_schema_drift_789.py"]
# (name, file, old, new, MUST_FAIL) — the last element is the defect this mutant
# reintroduces, named by the test that exists to catch it. A mutant that reds the suite
# some OTHER way is not caught; it is a broken mutant.
MUTANTS = [
 # M1/M2 are re-expressed as the OBSERVABLE defect rather than the old source shape:
 # r7 moved the decode inside the guard, so "the coercion sits above the try" is no longer
 # writable (`raw` does not exist above it). What the r1 findings were about is which
 # exception types reach the refusal, so each mutant now narrows the caught set by one and
 # lets exactly the defect's exception escape untyped.
 ("M1 TypeError escapes the guard again (the ah#789 shape)", E,
  "                except (TypeError, ValueError, KeyError, RecursionError) as error:",
  "                except (KeyError, RecursionError) as error:",
  "test_an_unknown_field_refuses_with_a_typed_error_not_a_TypeError"),
 ("M2 ValueError escapes again — an unknown STATE VALUE (r1 fable N1)", E,
  "                except (TypeError, ValueError, KeyError, RecursionError) as error:",
  "                except (TypeError, KeyError, RecursionError) as error:",
  "test_an_unknown_STATE_VALUE_is_also_a_typed_refusal"),
 ("M3 base class back to RuntimeError (r1 fable N2)", E,
  'class EvidenceStoreIncompatible(PermissionError):', 'class EvidenceStoreIncompatible(RuntimeError):',
  "test_the_refusal_matches_the_admission_stores_fail_closed_base_class"),
 ("M4 replay SKIPS the unreadable row instead of refusing", E,
  "                    raise EvidenceStoreIncompatible(",
  "                    continue\n                    raise EvidenceStoreIncompatible(",
  "test_the_record_is_NOT_skipped_or_coerced"),
 ("M5 collapse the two ambiguity codes", C,
  '            if not prs:\n                return self._ambiguous(request, "pr-list-empty")\n', '',
  "test_an_empty_pr_list_is_distinguishable_from_a_non_matching_one"),
 ("M6 empty case becomes a proven NO-EFFECT (fail open)", C,
  '                return self._ambiguous(request, "pr-list-empty")',
  '                return self._scope_rejected(request, "pr-list-empty")',
  "test_an_empty_pr_list_still_fails_CLOSED"),
 ("M7 predicate swap: not prs -> not head_matches (r1 grok)", C,
  '            if not prs:\n                return self._ambiguous(request, "pr-list-empty")',
  '            if not head_matches:\n                return self._ambiguous(request, "pr-list-empty")',
  "test_pr_head_unconfirmed_returns_ambiguous"),
 # The refusal's LINE NUMBER. Both of these survived r6 because nothing asserted it;
 # `evidence.jsonl` is append-only and grows for the life of a partition, so a refusal
 # without a row is a haystack. (ah#834 r6, fable.)
 ("M8 line numbering off by one (start=1 -> start=0)", E,
  "splitlines(), start=1)", "splitlines(), start=0)",
  "test_the_line_is_ONE_BASED_so_it_matches_what_a_reader_counts"),
 ("M9 the reported line becomes a constant", E,
  "line=index,", "line=1,",
  "test_the_refusal_NAMES_THE_LINE_of_the_offending_row"),
 # The helper's documented unconditional-call contract. Without the guard, the refusal
 # path raises inside its own except block: the ah#789 failure shape, relocated into the
 # error handler. (ah#834 r6, fable.)
 ("M10 constructor_key_mismatch loses its non-dataclass guard", A,
  "    if not dataclasses.is_dataclass(constructor):\n        return (), ()\n", "",
  "test_constructor_key_mismatch_returns_EMPTY_for_a_non_dataclass"),
 # The decode and the shape check, back OUTSIDE the guard. Three shapes escaped the typed
 # refusal entirely before r7 — including a truncated final append, the likeliest of them
 # on an append-only store. (ah#834 r7, codex.)
 ("M11 the shape check is dropped (a non-object row crashes untyped)", E,
  "                    if not isinstance(raw, dict):",
  "                    if False:",
  "test_a_row_that_is_not_a_usable_OBJECT_is_a_typed_refusal_naming_its_line"),
 ("M12 the json decode moves back above the guard", E,
  '                try:\n                    line = raw_line.decode("utf-8")\n                    raw = json.loads(line)',
  '                raw = json.loads(raw_line.decode("utf-8"))\n                try:\n                    line = None',
  "test_a_row_that_is_not_a_usable_OBJECT_is_a_typed_refusal_naming_its_line"),
 ("M13 a non-mapping row is handed to the mismatch helper", E,
  "                    unknown, missing = (\n                        constructor_key_mismatch(EvidenceRecord, raw)\n                        if isinstance(raw, dict) else ((), ())\n                    )",
  "                    unknown, missing = constructor_key_mismatch(EvidenceRecord, raw)",
  "test_a_row_that_is_not_a_usable_OBJECT_is_a_typed_refusal_naming_its_line"),
 # THE TWO SURVIVORS A SEAT FOUND THAT THIS MATRIX DID NOT ENUMERATE. Both were invisible
 # to all five kill conditions — they left the collected count unchanged and were simply
 # not here. The old fixture put the drifted row LAST with all-distinct keys, so the true
 # index equalled both the row count and the records-read count. (ah#834 r7, fable.)
 ("M14 line becomes the RECORDS-READ count (the plausible refactor)", E,
  "                        line=index,", "                        line=len(result) + 1,",
  "test_the_refusal_NAMES_THE_LINE_of_the_offending_row"),
 ("M15 line becomes the TOTAL ROW COUNT", E,
  "                        line=index,",
  "                        line=len(self.path.read_text(encoding='utf-8').splitlines()),",
  "test_the_refusal_NAMES_THE_LINE_of_the_offending_row"),
 # The key shape check: `result[raw["idempotency_key"]]` ran below the guard, so an
 # unhashable key was a bare TypeError out of replay() — the ah#789 signature — and a
 # hashable non-string key read SILENTLY into the mapping `epoch_blocked` is computed
 # over. (ah#834 r7, fable.)
 ("M16 the idempotency_key shape check is dropped", E,
  "                    if not isinstance(key, str):",
  "                    if False:",
  "test_a_NON_STRING_idempotency_key_is_a_typed_refusal"),
 ("M17 the key check also rejects an EMPTY string (fail-closes a readable store)", E,
  "                    if not isinstance(key, str):",
  "                    if not isinstance(key, str) or not key:",
  "test_an_EMPTY_STRING_key_still_reads"),
 # The decode, back outside the guard — r7's escape one layer further out. Every r7
 # fixture is valid UTF-8, so the suite could not see this. (ah#834 r8, codex.)
 ("M18 the whole file is decoded before the per-row guard", E,
  '            for index, raw_line in enumerate(self.path.read_bytes().splitlines(), start=1):',
  '            for index, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):\n                raw_line = line.encode()',
  "test_an_UNDECODABLE_row_is_a_typed_refusal_naming_its_line"),
 ("M19 split(b'\\n') instead of splitlines (fail-closes every real store)", E,
  "self.path.read_bytes().splitlines()", 'self.path.read_bytes().split(b"\\n")',
  "test_byte_splitlines_does_not_change_what_a_READABLE_store_yields"),
 # RecursionError is not a ValueError, so it needed naming explicitly. Every r8 non-object
 # fixture is shallow, which is why the suite could not see this. (ah#834 r9, codex.)
 ("M20 RecursionError escapes the guard again (deeply nested row)", E,
  "                except (TypeError, ValueError, KeyError, RecursionError) as error:",
  "                except (TypeError, ValueError, KeyError) as error:",
  "test_a_DEEPLY_NESTED_row_is_a_typed_refusal_naming_its_line"),
]
def run(root):
    r = subprocess.run(["python3","-m","pytest",*[str(Path(root)/t) for t in T],"-q","-p","no:cacheprovider"],
                       cwd=root, capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    tail = [l for l in out.strip().splitlines() if "passed" in l or "failed" in l]
    # STRIP THE PARAMETRISATION before matching. pytest reports a parametrised failure as
    # `test_name[the case]`, and splitting on whitespace lands mid-bracket, so a
    # parametrised test could never match its own name and every mutant it caught scored
    # [WRONG-RED]. Found by this matrix on itself when the r7 regression was added
    # parametrised — the fourth classifier defect in five rounds. (ah#834 r7.)
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
    with tempfile.TemporaryDirectory(prefix="mut834-") as tmp:
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
