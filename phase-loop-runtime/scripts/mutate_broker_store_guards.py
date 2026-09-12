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
MUTANTS = [
 ("M1 replay: bare constructor (the ah#789 shape)", E,
  '                try:\n                    raw["state"] = TerminalOutcomeState(raw["state"])\n                    record = EvidenceRecord(**raw)\n                except (TypeError, ValueError, KeyError) as error:',
  '                raw["state"] = TerminalOutcomeState(raw["state"])\n                record = EvidenceRecord(**raw)\n                if False:\n                    error = None'),
 ("M2 coercion back OUTSIDE the guard (r1 fable N1)", E,
  '                try:\n                    raw["state"] = TerminalOutcomeState(raw["state"])\n                    record = EvidenceRecord(**raw)',
  '                raw["state"] = TerminalOutcomeState(raw["state"])\n                try:\n                    record = EvidenceRecord(**raw)'),
 ("M3 base class back to RuntimeError (r1 fable N2)", E,
  'class EvidenceStoreIncompatible(PermissionError):', 'class EvidenceStoreIncompatible(RuntimeError):'),
 ("M4 replay SKIPS the unreadable row instead of refusing", E,
  '                except (TypeError, ValueError, KeyError) as error:\n                    unknown, missing = constructor_key_mismatch(EvidenceRecord, raw)',
  '                except (TypeError, ValueError, KeyError) as error:\n                    continue\n                    unknown, missing = constructor_key_mismatch(EvidenceRecord, raw)'),
 ("M5 collapse the two ambiguity codes", C,
  '            if not prs:\n                return self._ambiguous(request, "pr-list-empty")\n', ''),
 ("M6 empty case becomes a proven NO-EFFECT (fail open)", C,
  '                return self._ambiguous(request, "pr-list-empty")',
  '                return self._scope_rejected(request, "pr-list-empty")'),
 ("M7 predicate swap: not prs -> not head_matches (r1 grok)", C,
  '            if not prs:\n                return self._ambiguous(request, "pr-list-empty")',
  '            if not head_matches:\n                return self._ambiguous(request, "pr-list-empty")'),
]
def run(root):
    r = subprocess.run(["python3","-m","pytest",*[str(Path(root)/t) for t in T],"-q","-p","no:cacheprovider"],
                       cwd=root, capture_output=True, text=True, timeout=900)
    tail = [l for l in (r.stdout+r.stderr).strip().splitlines() if "passed" in l or "failed" in l]
    names = [l.split("::")[-1].split()[0] for l in (r.stdout+r.stderr).splitlines() if l.startswith("FAILED")]
    return r.returncode, (tail[-1] if tail else "?"), names
print("baseline (unmutated):")
rc, tail, _ = run(SRC); print(f"  rc={rc}  {tail}")
if rc != 0: sys.exit("baseline not green")
surv=[]
for name, rel, old, new in MUTANTS:
    with tempfile.TemporaryDirectory(prefix="mut834-") as tmp:
        root = Path(tmp)/"repo"
        shutil.copytree(SRC, root, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        f = root/rel; text = f.read_text()
        if old not in text:
            print(f"  [ANCHOR MISS] {name}"); surv.append(name); continue
        f.write_text(text.replace(old,new,1))
        rc, tail, names = run(root)
        v = "caught" if rc != 0 else "SURVIVES"
        if rc == 0: surv.append(name)
        print(f"  [{v:>8}] {name}\n             {tail}  via {names[:3]}")
print()
print("SURVIVORS:", surv if surv else "none")
