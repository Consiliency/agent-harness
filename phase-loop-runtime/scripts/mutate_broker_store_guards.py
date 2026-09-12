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
T = ["phase-loop-runtime/tests/test_convergence_broker_credsep.py",
     "phase-loop-runtime/tests/test_broker_evidence_schema_drift_789.py"]
# (name, file, old, new, MUST_FAIL) — the last element is the defect this mutant
# reintroduces, named by the test that exists to catch it. A mutant that reds the suite
# some OTHER way is not caught; it is a broken mutant.
MUTANTS = [
 ("M1 replay: bare constructor (the ah#789 shape)", E,
  '                try:\n                    raw["state"] = TerminalOutcomeState(raw["state"])\n                    record = EvidenceRecord(**raw)\n                except (TypeError, ValueError, KeyError) as error:',
  '                raw["state"] = TerminalOutcomeState(raw["state"])\n                record = EvidenceRecord(**raw)\n                if False:\n                    error = None',
  "test_an_unknown_field_refuses_with_a_typed_error_not_a_TypeError"),
 ("M2 coercion back OUTSIDE the guard (r1 fable N1)", E,
  '                try:\n                    raw["state"] = TerminalOutcomeState(raw["state"])\n                    record = EvidenceRecord(**raw)',
  '                raw["state"] = TerminalOutcomeState(raw["state"])\n                try:\n                    record = EvidenceRecord(**raw)',
  "test_an_unknown_STATE_VALUE_is_also_a_typed_refusal"),
 ("M3 base class back to RuntimeError (r1 fable N2)", E,
  'class EvidenceStoreIncompatible(PermissionError):', 'class EvidenceStoreIncompatible(RuntimeError):',
  "test_the_refusal_matches_the_admission_stores_fail_closed_base_class"),
 ("M4 replay SKIPS the unreadable row instead of refusing", E,
  '                except (TypeError, ValueError, KeyError) as error:\n                    unknown, missing = constructor_key_mismatch(EvidenceRecord, raw)',
  '                except (TypeError, ValueError, KeyError) as error:\n                    continue\n                    unknown, missing = constructor_key_mismatch(EvidenceRecord, raw)',
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
]
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
    invalid = (
        r.returncode == 2
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
