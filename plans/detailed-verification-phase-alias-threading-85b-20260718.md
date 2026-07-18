# Detailed plan: thread the live run alias into verification.json (ah#85 sub-bug b)

## Task
Consiliency/agent-harness#85 symptom (2): during an active execute run, `terminal-summary.json`
records the LIVE phase alias (e.g. `VIRTUALDEV`) but `verification.json`'s `phase_alias` is
RE-DERIVED from `.phase-loop/state.json:current_phase` and can disagree (reported as `OVERLAY`)
— a mis-attribution that drifts when a mid-run roadmap amendment changes `current_phase`. Fix:
thread the live run alias into `run_verification` on the execute path so `verification.json`
records the alias of the run that actually produced it, not a re-derived one.

This is sub-fix **B** of the #85+#90 reconcile cluster (split after a verification recon
confirmed each sub-bug still reproduces on current main `a00b5c8`). B is INDEPENDENT of the
others — it touches only `verification_evidence.py` + `runner.py`. (C = path portability
touches reconcile/classifier; D = #90 reconcile-artifact touches cli/reconcile; A = the
hash-scope product decision is deferred.)

## Research summary
Verified on current main:
- `run_verification` (`verification_evidence.py:305`) takes NO phase param; it sets
  `phase_alias=_phase_alias(repo_path)` at `:395` (the field is serialized to `verification.json`
  at `:717`).
- `_phase_alias(repo)` (`:782-794`) resolves: env `PHASE_LOOP_PHASE_ALIAS`/`PHASE_ALIAS` →
  `.phase-loop/state.json:current_phase` → `"unknown"`. Nothing in `src/` sets those env vars,
  so the escape-hatch is inert; in practice it always reads `current_phase`.
- The execute-path caller HAS the live alias: `runner.py:3508` is inside a scope where
  `alias` is the live phase alias (`post_launch_plan = find_plan_artifact(repo, alias, roadmap=…)`),
  and it calls `_run_execute_verification(repo=, roadmap=, plan=verification_plan, artifacts=)`
  (`runner.py:5963` def) WITHOUT threading `alias`; `_run_execute_verification` then calls
  `run_verification` (`runner.py:5994`).
- **Three callers of `run_verification`:** `runner.py:5994` (execute path — HAS the live alias,
  the fix target), `cli.py:2043` (the `hotfix` handler — no live phase-alias variable, has only
  a `--plan`), and `train_runner.py:597` (a `-reverify` run — no live phase-alias variable). Only
  the execute path is the reported #85b symptom; the other two legitimately have no live run
  alias and keep the existing `_phase_alias` fallback.

## Design decision: thread on the execute path; preserve env precedence + the fallback
Add an optional `phase_alias` param, threaded ONLY from the execute path (the symptom). Preserve
`_phase_alias`'s env-override precedence by passing the threaded alias as a fallback-default
INSIDE `_phase_alias` (env still wins as the operator escape hatch; the threaded live alias beats
`current_phase`; `current_phase` remains the last resort). The two non-execute callers pass
nothing → byte-identical behavior. Minimal, back-compat, zero risk to hotfix/train.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` (modify)
- `_phase_alias(repo)` (`:782`) — add a `provided: str | None = None` param — resolve order
  env → `provided` (when set) → `current_phase` → `"unknown"`. Reason: let a caller supply the
  live run alias without losing the env escape-hatch or the `current_phase` fallback.
- `run_verification(...)` (`:305`) — add a trailing keyword param `phase_alias: str | None = None`
  (after `python_pin`, keyword-only-safe: it's the last param and all existing callers use
  positional-then-keyword up to `python_pin`, so appending is back-compat). At `:395` change
  `phase_alias=_phase_alias(repo_path)` → `phase_alias=_phase_alias(repo_path, phase_alias)`.
  Reason: accept the live alias and forward it to `_phase_alias`. No `VerificationResult` schema
  change (the `phase_alias` field + serialization at `:717` are unchanged — only its SOURCE).

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)
- `_run_execute_verification(*, repo, roadmap, plan, artifacts)` (`:5963`) — add a keyword
  param `phase_alias: str | None = None`; pass it through to `run_verification(..., phase_alias=phase_alias)`
  at `:5994`. Reason: carry the live alias from the run loop to verification.
- The caller at `runner.py:3508` — pass `phase_alias=alias` (the live alias already in scope) to
  `_run_execute_verification(...)`. Reason: the actual fix — verification.json now records the
  run's real alias.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`
  (`:5`) — modify — the documented `run_verification(...)` signature gains the optional
  `phase_alias` param; note that when supplied it is the authoritative alias for
  `verification.json` (env override still wins; else falls back to `current_phase`).
- `CHANGELOG.md` — add — `verification.json`'s `phase_alias` is now sourced from the live run
  alias on the execute path (instead of re-derived from `.phase-loop/state.json:current_phase`),
  so it no longer drifts / mis-attributes when a mid-run roadmap amendment changes the current
  phase (ah#85).

## Frozen-vocabulary confirmation
The `verification.json` artifact schema (`schema_version`, its 9 keys incl. `phase_alias`) is
UNCHANGED — only the value's provenance changes. `VerificationResult.phase_alias` (`:266`),
`load_verification_artifact`'s required-keys (`:441-467`), and the sha-pairing are untouched. No
new vocabulary.

## Dependencies & order
Thread bottom-up: (1) `_phase_alias` param, (2) `run_verification` param + forward, (3)
`_run_execute_verification` param + forward, (4) the `runner.py:3508` caller passes `alias`.
No migration, no consumer change (readers of `verification.json.phase_alias` see a more-correct
value of the same type).

## Execution Policy
- execute: effort=low, reason=thread one optional param through 3 hops + preserve the fallback
  + one regression test.

## Verification
```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest tests/ -q -k "verification_evidence or phase_alias or run_verification or 85"
# direct: with a threaded alias that DIFFERS from state.json current_phase, verification.json
# records the threaded alias (the drift fix); with none, it falls back to current_phase; env wins.
PYTHONPATH=src python -c "
import tempfile, json
from pathlib import Path
from phase_loop_runtime import verification_evidence as ve
with tempfile.TemporaryDirectory() as td:
    repo = Path(td); (repo/'.phase-loop').mkdir()
    (repo/'.phase-loop/state.json').write_text(json.dumps({'current_phase':'OVERLAY'}))
    assert ve._phase_alias(repo) == 'OVERLAY'                    # fallback = current_phase
    assert ve._phase_alias(repo, 'VIRTUALDEV') == 'VIRTUALDEV'   # threaded live alias wins over current_phase
    import os; os.environ['PHASE_LOOP_PHASE_ALIAS']='ENVWINS'
    assert ve._phase_alias(repo, 'VIRTUALDEV') == 'ENVWINS'      # env escape-hatch still wins
    print('phase_alias precedence ok')
"
```
Edge cases: (a) threaded alias ≠ current_phase → verification.json = threaded alias; (b) no alias
threaded (hotfix/train) → current_phase (unchanged); (c) `PHASE_LOOP_PHASE_ALIAS` set → env wins;
(d) `run_verification`'s existing callers (cli/train) unaffected (append-only param).

## Test-visibility
Put the regression in an **UNMARKED** module. Check the target module's marker: if the natural
home (e.g. a `verification_evidence` test module) carries `pytestmark = pytest.mark.dotfiles_integration`
(CI runs `-m "not dotfiles_integration"` → skipped), use a new unmarked module
(`test_verification_phase_alias_85b.py`) so CI runs it. A `_phase_alias` precedence test needs
only a temp `.phase-loop/state.json` — no dotfiles tree.

## Acceptance criteria
- [ ] `verification_evidence._phase_alias(repo, "VIRTUALDEV")` returns `"VIRTUALDEV"` even when
      `.phase-loop/state.json:current_phase` is `"OVERLAY"`; returns `current_phase` when no alias
      is provided; the `PHASE_LOOP_PHASE_ALIAS` env override still wins over both.
- [ ] On the execute path, `run_verification` writes `verification.json.phase_alias` equal to the
      live run alias threaded from `runner.py:3508` (not `current_phase`) — pinned by a test that
      sets `current_phase` to a DIFFERENT value.
- [ ] The two non-execute callers (`cli.py:2043` hotfix, `train_runner.py:597`) are unchanged
      (no alias threaded → existing `_phase_alias` behavior); their suites stay green.
- [ ] Regression test lives in an unmarked module (runs under CI's `-m "not dotfiles_integration"`).
