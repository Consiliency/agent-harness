# Deferred-findings register

## Purpose and status

This is a record, not a work queue. Nothing in the runtime, CI or phase discovery reads this file. In the
words of the register it absorbs (Consiliency/agent-harness#361): "Do not schedule from this register directly."

## How findings enter

1. **Filing is unchanged.** Filing is governed by the maintainer-ratified design on
   Consiliency/agent-harness#442 — "every `DEFERRED` finding must have a filed issue carrying its verbatim text before dispatch" — and by v10 Execution Notes gate 2
   (`specs/phase-plans-v10.md`) — "a downstream finding is mapped to its existing criterion, or filed as a repository-qualified issue when unscheduled". This register neither adds nor removes a filing obligation.
2. **Disposition.** Each issue filed under those sources receives a disposition comment naming its
   category (below) before the board's PR merges.
   - PARKED or OBSOLETE: its row lands in a register PR, which may batch rows. The issue is closed as not
     planned only once its row is on main, with a permalink to the row. Until then it stays open with its
     disposition recorded.
   - SCHEDULED, STILL-LIVE or DECISION-REQUIRED: the issue stays open.
3. **Scope.** This is a documented convention only; nothing enforces it at runtime.

## Categories and precedence

Each issue is tested in this order, and the first category that applies is its disposition:

**EXCLUDED > SCHEDULED > DECISION-REQUIRED > STILL-LIVE > ALREADY-FIXED > OBSOLETE > PARKED**

| Disposition | Applies when |
|---|---|
| EXCLUDED | The issue is in flight elsewhere (an open PR, an agent branch, or an operator hold). |
| SCHEDULED | The issue is bound to unfinished roadmap or plan work. |
| DECISION-REQUIRED | The issue asks for a maintainer choice that changes production behaviour or policy. |
| STILL-LIVE | The defect is reachable on main; or it is safety-floor class with no reachability negative; or it contradicts a frozen requirement — frozen spec or phase-plan text, or the class Consiliency/agent-harness#442 names non-deferrable: "a finding contradicting staged prober evidence, an attestation claim, or a frozen-test invariant is NOT deferrable". |
| ALREADY-FIXED | Every ask in the issue verifiably holds on main. |
| OBSOLETE | The mechanism the finding concerns has been removed from main. |
| PARKED | The original ruling classed the finding `DEFERRED`, non-blocking or nit, and no earlier category applies. |

**Safety floor.** The floor classes are:
- path containment;
- credentials;
- authorization or authority;
- fail-open verification;
- concurrency or TOCTOU on an authority or evidence path.

A floor-class finding closes as OBSOLETE or PARKED only with a reachability negative: the code was
removed, or every production caller is enumerated and shown not to reach the defect. A deferral's own
reasoning, a mitigation, a fail-closed CLI in front of a live API path, or "not urgent" never counts.

## Promotion rule

- **Trigger:** a row returns to scheduled work only on new reachability evidence — a new production caller,
  a changed trust boundary, or a demonstrated exploit or failure path — and the evidence is cited.
- **Mechanism:** reopen the row's source issue with that evidence. The row is then marked
  `PROMOTED <date> <evidence link>` and is never deleted.

Rows R-001..R-005 come from Consiliency/agent-harness#361, whose promotion text was: "split it back out as its own P-ranked issue WITH the reachability evidence". Reopening a
row's source issue satisfies that text, because the source issue is that residual's own issue.

## Row format

Each row's `finding` holds the issue's body and comments, byte-for-byte, in fenced blocks. Field lines and
row markers count only outside fences. A row does not record the issue's GitHub state; GitHub does.
Ruling quotes are verbatim, with line wrapping collapsed.

## Rows

<!-- row:R-001 -->
### R-001 — `_is_git_tracked` parses trusted git stdout with `.strip()` not byte-exact
- **source:** Consiliency/agent-harness#276 (migrated from Consiliency/agent-harness#361)
- **origin:** cross-vendor CR residual consolidated in Consiliency/agent-harness#361
- **original ruling:** "verified NON-EXPLOITABLE; trusted-input boundary" — #361's table, "explicitly adjudicated **non-blocking** at filing"
- **bound criteria:** none
- **current-main check:** not re-checked at migration; carried verbatim from #361
- **safety floor:** carried from #361's adjudication; not re-evaluated at migration
- **disposition:** PARKED — migrated from #361's accepted-residual table
- **promotion:** none
- **finding:**
````markdown
| #276 | `_is_git_tracked` parses trusted git stdout with `.strip()` not byte-exact | verified NON-EXPLOITABLE; trusted-input boundary |
````

<!-- row:R-002 -->
### R-002 — content-SHA cannot distinguish moved-repo from byte-identical distinct repo
- **source:** Consiliency/agent-harness#273 (migrated from Consiliency/agent-harness#361)
- **origin:** cross-vendor CR residual consolidated in Consiliency/agent-harness#361
- **original ruling:** "operator BREAKGLASS SL-2 boundary, #85C-scoped" — #361's table, "explicitly adjudicated **non-blocking** at filing"
- **bound criteria:** none
- **current-main check:** not re-checked at migration; carried verbatim from #361
- **safety floor:** carried from #361's adjudication; not re-evaluated at migration
- **disposition:** PARKED — migrated from #361's accepted-residual table
- **promotion:** none
- **finding:**
````markdown
| #273 | content-SHA cannot distinguish moved-repo from byte-identical distinct repo | operator BREAKGLASS SL-2 boundary, #85C-scoped |
````

<!-- row:R-003 -->
### R-003 — FAV avatar-surface detector is a starting allowlist
- **source:** Consiliency/agent-harness#272 (migrated from Consiliency/agent-harness#361)
- **origin:** cross-vendor CR residual consolidated in Consiliency/agent-harness#361
- **original ruling:** "detector is one of TWO required signals; operator-accepted" — #361's table, "explicitly adjudicated **non-blocking** at filing"
- **bound criteria:** none
- **current-main check:** not re-checked at migration; carried verbatim from #361
- **safety floor:** carried from #361's adjudication; not re-evaluated at migration
- **disposition:** PARKED — migrated from #361's accepted-residual table
- **promotion:** none
- **finding:**
````markdown
| #272 | FAV avatar-surface detector is a starting allowlist | detector is one of TWO required signals; operator-accepted |
````

<!-- row:R-004 -->
### R-004 — space-separated flags in free-text command STRINGS unredacted
- **source:** Consiliency/agent-harness#269 (migrated from Consiliency/agent-harness#361)
- **origin:** cross-vendor CR residual consolidated in Consiliency/agent-harness#361
- **original ruling:** "inherent regex/prose ambiguity; structured argv IS covered" — #361's table, "explicitly adjudicated **non-blocking** at filing"
- **bound criteria:** none
- **current-main check:** not re-checked at migration; carried verbatim from #361
- **safety floor:** carried from #361's adjudication; not re-evaluated at migration
- **disposition:** PARKED — migrated from #361's accepted-residual table
- **promotion:** none
- **finding:**
````markdown
| #269 | space-separated flags in free-text command STRINGS unredacted | inherent regex/prose ambiguity; structured argv IS covered |
````

<!-- row:R-005 -->
### R-005 — belt-and-suspenders redaction of ledger/launch.json diagnostics
- **source:** Consiliency/agent-harness#266 (migrated from Consiliency/agent-harness#361)
- **origin:** cross-vendor CR residual consolidated in Consiliency/agent-harness#361
- **original ruling:** "on-disk is local-full BY DESIGN; egress surface already redacted" — #361's table, "explicitly adjudicated **non-blocking** at filing"
- **bound criteria:** none
- **current-main check:** not re-checked at migration; carried verbatim from #361
- **safety floor:** carried from #361's adjudication; not re-evaluated at migration
- **disposition:** PARKED — migrated from #361's accepted-residual table
- **promotion:** none
- **finding:**
````markdown
| #266 | belt-and-suspenders redaction of ledger/launch.json diagnostics | on-disk is local-full BY DESIGN; egress surface already redacted |
````

<!-- row:R-006 -->
### R-006 — Contract-floor guard (#378/#382): round-7 non-blocking follow-ups
- **source:** Consiliency/agent-harness#399
- **origin:** contract-floor guard, round-7 convergence board of agent-harness#382 (merged `a3fbb19`), fable seat; 4/4 AGREE, zero blockers
- **original ruling:** "the four **non-blocking** follow-ups raised by the fable seat"
- **bound criteria:** none
- **current-main check:** c0e51591: `_requirement_from_adjacent_pyproject` still at consiliency_layout.py:405; phase-loop-runtime/pyproject.toml:45 pins `consiliency-contract>=0.6.5,<0.7`
- **safety floor:** fail-open verification — item 3 (a specifier-less pin yields a vacuous `SpecifierSet`) is floor-class; the callers negative below holds; callers negative: phase-loop-runtime/src/phase_loop_runtime/consiliency_layout.py:550 (declared_contract_requirement -> _requirement_from_adjacent_pyproject): reads only this package's own pyproject, whose pin carries the specifier `>=0.6.5,<0.7` (pyproject.toml:45); the specifier-less branch is never taken; phase-loop-runtime/src/phase_loop_runtime/consiliency_layout.py:642 (check_installed_contract_floor -> assert_contract_floor_satisfied): its requirement comes from declared_contract_requirement (:627), the same specified pin, so the SpecifierSet is never empty
- **disposition:** PARKED — Non-blocking follow-ups (comment anchors, dynamic-deps fallback, specifier-less pin, ambient test coupling); the only floor-class item is unreachable from its production callers.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Contract-floor guard (agent-harness#378 / #382): round-7 follow-ups

Grouped tracking issue for the four **non-blocking** follow-ups raised by the fable seat at
**round-7 convergence of agent-harness#382** (merged to `main` as `a3fbb19`; the round closed
4/4 AGREE, zero blockers). None are urgent — each is either pre-existing or a future-shape the
current code does not yet meet. **The round-7 board results are the authoritative record of these
findings**; the descriptions below are a code-grounded triage interpretation to make them
actionable, and should be reconciled against that record before work starts.

All line refs are `phase-loop-runtime/src/phase_loop_runtime/consiliency_layout.py` on `a3fbb19`.

### 1. Rename-staleness / comment-anchor coupling
Docstrings and mutation-table comments cite symbols and line numbers as anchors (e.g. `:499`,
`:543`, "`test_...` at `:291`/`:330`"). A rename or line shift desyncs the prose from the code
with no failing signal — this already happened once in-flight (a `:499` anchor drifted to `:543`
across edits). *Shape:* prefer symbol-relative references, or a lightweight check that flags
comment line-anchors that no longer resolve. Documentation-integrity, not a runtime defect.

### 2. Dynamic-dependencies pyproject shape
`_requirement_from_adjacent_pyproject` reads `project.get("dependencies", ())`. A pyproject that
declares `[project] dynamic = ["dependencies"]` (deps resolved by the build backend, not listed
statically) yields an empty list, so the helper returns `None` and metadata governs. That is a
**safe fallback**, not a mis-enforcement — but the pin is silently not consulted for that layout.
*Shape:* if a dynamic-deps project must still be pin-governed, resolve deps another way; else
document the fallback as intended.

### 3. Specifier-less pin
If an (owned) pyproject lists `consiliency-contract` with **no version specifier**, the helper
returns the bare `"consiliency-contract"`, and `assert_contract_floor_satisfied` builds an empty
`SpecifierSet` whose `.contains(...)` is `True` for every version — so the floor is silently
unenforced. *Shape:* treat a specifier-less pin as "no floor declared" explicitly (and/or warn),
rather than enforcing a vacuous one.

### 4. Ambient-contract test coupling
Tests that lean on the *ambient installed* `consiliency-contract` version (rather than fully
pinned literals/monkeypatch) couple their outcome to the host environment. *Shape:* audit those
tests and bind the installed operand explicitly where feasible, so the suite result is
environment-independent.

---
Context: shipped across two folds on #382 (r5 pyproject-pin governance + ownership gate; r6
canonical identity at all four decision sites + scope-sound AST walk + end-to-end acceptance
test). Closes-adjacent work (repin `spec@v0.2.2`, agent-harness#389) is tracked separately and is
not part of this issue.

````

<!-- row:R-007 -->
### R-007 — CONFORM lifecycle ancestry is contaminated by unrelated refs
- **source:** Consiliency/agent-harness#460
- **origin:** CONFORM immutable lifecycle capture, candidate `24cc7a3c`
- **original ruling:** "Non-blocking for current CONFORM execution because the ref-isolated clean-room workaround is available."
- **bound criteria:** none
- **current-main check:** c0e51591: the walk is scoped to HEAD's ancestry (test_outside_agent_conform_evidence.py:1972,1997); `git grep '"--all"'` finds nothing in that file
- **safety floor:** not floor-class — selecting the unrelated commit failed the ancestry assertion (fail-closed)
- **disposition:** OBSOLETE — The `git log --all` walk this finding concerns was removed by `e69a3132`.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Summary

CONFORM's immutable lifecycle capture can select an unrelated local branch commit and fail an otherwise exact candidate because it discovers the test commit with `git log --all`.

## Reproduction

At candidate `24cc7a3c310434f51a3201ada3154695efdcf891`, run the plan's literal A2 broad-minus-stale selector in a repository that also has a local branch containing newer commits with byte-identical `CONFORM_IMMUTABLE_LIFECYCLE_PATHS`:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests \
python3 -m pytest phase-loop-runtime/tests -q \
  -k "outside_agent and not (test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes or test_v7_disposition_records_merged_contract_and_final_installed_behavior or test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary or test_public_docs_point_to_handoff_without_claiming_release_dispatch)"
```

Observed after 32 minutes:

```text
test_commit = 87d64db81d65f73bd538331548391087e001f6a0
candidate_commit = 24cc7a3c310434f51a3201ada3154695efdcf891
git merge-base --is-ancestor <test_commit> <candidate_commit> -> 1
1 failed, 88 passed, 23 skipped, 4465 deselected
```

The failing path is `test_outside_agent_conform_evidence.py::_capture_immutable_lifecycle()`: it enumerates `git log --format=%H --all -- <test paths>`, selects the first commit whose test blobs equal HEAD, and only afterward checks ancestry. A newer unrelated ref with the same blobs can therefore win selection.

## Control

Fetching the same exact candidate into a fresh ref-isolated repository with no refs other than detached HEAD removes the unrelated commit from `--all`; the same immutable selector then measures the intended candidate ancestry. This is the current execution workaround and does not change test or production bytes.

## Expected

Lifecycle discovery should be candidate-reachable by construction, for example by walking the candidate's ancestry rather than `--all`, or by filtering all blob-equal candidates to ancestors before choosing one. Unrelated local refs must not affect the result.

## Scope

Non-blocking for current CONFORM execution because the ref-isolated clean-room workaround is available. Do not change the frozen CONFORM tests during the active phase; repair this after the phase's immutable-test boundary is released, with a regression that creates a newer unrelated blob-equal branch.

````

Comment by ViperJuice at 2026-08-05T18:39:40Z:

````markdown
Fresh coordinator control on 2026-08-05 against exact CONFORM candidate `403f0b63b5f5b446440bb402fb3c3a521f22caac` confirms the issue diagnosis and workaround.

A single-ref repository fetched only that candidate. Direct invocation of `_capture_immutable_lifecycle` selected test ancestor `4718462c486dfd22e6e2e3528730edfd9ce00ec8` and completed with:

- default: exit 0, 10 required skips
- activated: nonzero exit, all 48 required RED failures

The same helper in the shared worktree selected unrelated `87d64db` through `git log --all` and failed the ancestry assertion before lifecycle execution. No frozen CONFORM bytes were changed. Continue using the issue's ref-isolated execution workaround for the active phase; retain the candidate-reachable history repair for after the immutable-test boundary is released.

````

<!-- row:R-010 -->
### R-010 — PROOFGATE: make candidate-mode probes compatible with clean-worktree verification
- **source:** Consiliency/agent-harness#474
- **origin:** PROOFGATE, exact-head review of draft agent-harness#473 at `eee91759`, PGB-003
- **original ruling:** "one finding that the Fable president classified `DEFERRED`"
- **bound criteria:** none
- **current-main check:** c0e51591: guard text still present (phase-loop-runtime/tests/proofgate_bootstrap_verifier.py:1134)
- **safety floor:** not floor-class — the clean-worktree guard raises (fail-closed); it blocks verification rather than accepting it
- **disposition:** PARKED — President-DEFERRED interaction between a fail-closed guard and a reviewer's workspace layout.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Context

The exact-head review of draft `agent-harness#473` at
`eee91759d57b07b7f19df2f18c0f3315aa7e0951` identified one finding that the
Fable president classified `DEFERRED`. It is filed before any repair dispatch
to satisfy the MAINTAINER-RATIFIED `agent-harness#442` rule.

## Verbatim deferred finding

> PGB-003 — Candidate-mode verification blocked by the clean-worktree guard.
>
> Exact text, `phase-loop-runtime/tests/proofgate_tdd_guard.py:1101-1103`:
>
>     status_proc = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
>     if status_proc.stdout.strip():
>         raise err_cls("Worktree or index is not clean against candidate_oid")
>
> Rationale for deferral. The mechanism is exactly as Terra described, and I confirmed it.
> But the load-bearing premise — that probe outputs *must* live under `.phase-loop-probe-tmp`
> inside the candidate worktree — is not established by the plan, the guard, or the bundle,
> and probe output can be written outside the repository. `proofgate_tdd_guard.py` is not one
> of the five changed files, so this is a pre-existing verifier constraint interacting with a
> reviewer's chosen workspace layout rather than a defect in the change under review. I
> concur with Grok and Opus.
>
> Deferral here is narrow and does not rescue the verification posture: the substantive gap
> behind Terra's failed probe is captured separately by PGB-007.

## Evidence

- Review bundle SHA-256: `a7c0eb65919543ad06593b2c4d8259e425996b8e9be17cf242b1011035ecbcb0`
- Complete board record SHA-256: `e39e19d133287a9b423a956c475d983998293268706817735e5c69fee2a9b319`
- Fable round-1 record SHA-256: `3f7e908d05caadb59025a373c09f10a05207aa08a49fba5d14fc4cbf144384a3`
- Fable round-2 record SHA-256: `b4eab03bd91418b8172f129486259f499a606ab924de3df45e77f31453d2d30b`

This issue does not authorize or unblock `agent-harness#473`. The president
ruled the other twelve findings blocking.

````

<!-- row:R-011 -->
### R-011 — Harden CONFORM B2 replay and transition proof edges
- **source:** Consiliency/agent-harness#487
- **origin:** CONFORM, Fable president ruling on agent-harness#484 / agent-harness#485 at `be52ff1a`
- **original ruling:** "These findings are DEFERRED and non-blocking for the tests-only ordinary-CI/B2 repair"
- **bound criteria:** none
- **current-main check:** c0e51591: `normalize_junit_tree` still at phase-loop-runtime/tests/test_outside_agent_conform_evidence.py:572
- **safety floor:** not floor-class — test-evidence hygiene (normalizer symmetry, a missing positive case, a dead guard); no acceptance path is widened
- **disposition:** PARKED — President-DEFERRED test hardening.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Follow-up required by the Fable president ruling on agent-harness#484 / agent-harness#485. These findings are DEFERRED and non-blocking for the tests-only ordinary-CI/B2 repair at `be52ff1a81bcfacd45c581ad88a7c8db1b46f624`.

Verbatim reviewer findings:

1. Grok: "JUnit `message` attributes / absolute traceback paths are not normalized; fine under the plan’s “element text” wording and same-host address/duration volatility."

   Opus: "`normalize_junit_tree` normalizes element `text`/`tail` but not `<failure message=\"…\">` attributes. Under B2 a failing probe could still replay non-deterministically if pytest puts a volatile repr in `message`. A valid B2 run requires every EC probe to pass (no failure elements at all), and the authorization scopes normalization to \"element text\", so this is out of scope here — but it is a real residual edge on the already-blocked path."

2. Opus: "`assert _b2_compatibility_evidence_due() is False` short-circuits on the env check, so it would also pass if the conjunction's second operand were wrong. The separate `_sl2_compatibility_transitioned() is True` assertion and the source-literal pin mitigate this, but there is no positive case asserting `True` with both conditions met."

3. Opus: "`_capture_immutable_lifecycle` records `junit_sha256` for the activated/default lifecycle runs without applying the new normalizer. Same-run recomputation is all that is asserted, so nothing breaks; noting it for symmetry."

4. Opus: "`if contract_bug_landing is None or …` (`:3707-3708`) is dead after the tuple unpacking two lines above."

Requested downstream hardening:
- Decide whether JUnit failure `message` attributes and immutable-lifecycle JUnit should share the frozen normalizer.
- Add a positive behavioral proof for `_b2_compatibility_evidence_due()` with both operands true.
- Remove the dead chronology guard if it remains unreachable after CONFORM lands.

This issue must not reopen the accepted scope of agent-harness#484. The president found no blocking correctness, safety, or acceptance defect and authorized agent-harness#485 to land once these findings were filed.

````

<!-- row:R-013 -->
### R-013 — Record prerequisite object presence in CONFORM dual-tag GREEN evidence
- **source:** Consiliency/agent-harness#505
- **origin:** CONFORM, Fable president at the agent-harness#504 plan gate, plan commit `c0073622`
- **original ruling:** "President ruling: DEFERRED and non-blocking because both frozen range proofs fail loudly if either commit is absent."
- **bound criteria:** none
- **current-main check:** c0e51591: the GREEN text is unchanged in plans/phase-plan-v10-CONFORM.md (:504)
- **safety floor:** not floor-class — both frozen range proofs fail loudly if either commit is absent
- **disposition:** PARKED — President-DEFERRED free tightening of frozen GREEN text.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Deferred by the Fable president at the exact agent-harness#504 plan gate. This issue preserves the board finding verbatim as required by the maintainer-ratified agent-harness#442 policy.

Artifact binding: `c0073622661e6b0866229345cd3e476fdbdfba82`; `plans/phase-plan-v10-CONFORM.md` SHA-256 `18d53316ee5ecf2793ce9d272006c89be7c7252c5ac0cc57d0b4299da3ad0d95`.

> The GREEN does not explicitly require recording that 287d447 and 2a495c4 are present after the `--no-tags` main fetch. Both range proofs fail loudly if they are not, so this is implied rather than a hole; adding the two `cat-file -e` lines would be a free tightening.

President ruling: DEFERRED and non-blocking because both frozen range proofs fail loudly if either commit is absent. Any tightening touches frozen GREEN text and therefore requires a later reviewed amendment; it must not alter the current implementation dispatch.
````

<!-- row:R-014 -->
### R-014 — LEGIBLE sidecar test: the canonical arm makes a live call against issue 396 and never runs in CI
- **source:** Consiliency/agent-harness#539
- **origin:** LEGIBLE sidecar test, filed 2026-08-13
- **original ruling:** "Severity: environment-dependent-local. Not a regression, not release-blocking."
- **bound criteria:** none
- **current-main check:** c0e51591: `_canonical_repo_ready` still at phase-loop-runtime/tests/test_legible_evidence.py:230
- **safety floor:** not floor-class — a test arm's environment dependency; no production verification or authority path
- **disposition:** PARKED — A non-blocking test asymmetry filed for the record.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Summary

`test_verification_sidecar_runner_captures_bounded_redacted_fable_probe_evidence`
(`phase-loop-runtime/tests/test_legible_evidence.py:1064`) has two arms selected by
`_canonical_repo_ready()` (`:230`). The **canonical** arm makes a live call whose result
depends on the current state of Consiliency/agent-harness#396. It fails today on a normal
developer checkout, and — more importantly — it is **never exercised in CI**, in any lane.

Severity: environment-dependent-local. Not a regression, not release-blocking. Filed so the
asymmetry is on the record rather than rediscovered.

## Reproduction

On a canonical checkout (`.git` present, `plans/phase-plan-v10-LEGIBLE.md` present):

```
PYTHONPATH=src:tests python3 -m pytest -q tests/test_legible_evidence.py \
  -k test_verification_sidecar_runner_captures_bounded_redacted_fable_probe_evidence
```

```
        state = _classify_reviewtruth_transition(classification_input)
        if state is None:
>           raise LegibleSidecarError(
                "unrecognized_transition_state",
                "reviewtruth_fable_transition matched neither the pending nor resolved contract",
            )
E       phase_loop_runtime.legible_evidence.LegibleSidecarError:
        reviewtruth_fable_transition matched neither the pending nor resolved contract

src/phase_loop_runtime/legible_evidence.py:749: LegibleSidecarError
```

Verified pre-existing: fails identically on unmodified `origin/main`. It is **not** a
regression from #537.

## Mechanism

```python
canonical = _canonical_repo_ready()
repo = REPO_ROOT if canonical else _synthetic_legible_repo(tmp_path).path
...
if not canonical:
    monkeypatch.setattr(module, _FABLE_ADAPTER_BOUNDARY, lambda *a, **k: _RAW_FABLE_OBSERVATION, ...)
record = probe(repo, repository="Consiliency/agent-harness", issue=396, model="claude-fable-5")
```

- **not canonical** → the adapter boundary is monkeypatched with a fixed raw observation.
  Deterministic, offline, and it still exercises the real bounding/redaction route. Good arm.
- **canonical** → no monkeypatch. `probe(...)` runs the real adapter against live issue 396,
  and the assertion `record.state in ("pending", "resolved")` is really an assertion about
  the present-day state of a GitHub issue. Issue 396 has since moved to a transition state
  matching neither contract, so the arm raises.

`_canonical_repo_ready()` is `(REPO_ROOT / ".git").exists() and PLAN_PATH.is_file()`, with
`REPO_ROOT = Path(__file__).resolve().parents[2]`.

## Why CI never catches it

`test_legible_evidence.py` is deliberately excluded from the main suite run and re-run from a
**copied, tests-only tree** to exercise the standalone-consumer posture — both on the hosted
lanes and in the Dagger offload:

```
--ignore tests/test_legible_evidence.py
...
cp -r tests "$suite_root/tests"
PYTHONPATH="$suite_root/tests" python -m pytest "$suite_root/tests/test_legible_evidence.py" ...
```

In that tree `REPO_ROOT` has no `.git` and no `plans/`, so `_canonical_repo_ready()` is
False and the **synthetic arm always wins**. Confirmed empirically: the LEGIBLE leg reports
85 passed in CI while the same test fails locally.

So the canonical arm is unfalsifiable where it would gate anything, and coupled to mutable
external state where it does run. Both directions are bad: on a developer machine it is a
standing false alarm that trains people to ignore a red LEGIBLE module; in CI it is silently
absent, so no amount of green says anything about it.

## Suggested direction (not prescriptive)

Decouple *liveness* from *canonicality*. Canonical-checkout detection is a reasonable proxy
for "has real git history" — which several other nodeids in this module legitimately need —
but it is the wrong proxy for "may make a live network call against a mutable issue".
Options, roughly in increasing cost:

1. Gate the live arm on an explicit opt-in env var (the idiom already used by
   `test_grokexec.py:379` for the live grok proof and by `test_specpkgmin_wheel.py` via
   `_required_root`), so the default everywhere — dev and CI alike — is the deterministic
   synthetic arm.
2. Keep a live arm but assert only what is time-invariant (bounds, schema, redaction,
   sha length), not `state in ("pending", "resolved")`, which encodes a snapshot of issue 396.
3. Pin the live arm to a recorded observation captured at a known issue state, so it stays a
   real regression test rather than a weather report.

Option 1 alone would close the false alarm; 1 + 2 would also stop the arm rotting again.

## Provenance

Found while enumerating unguarded external-binary invocations for the Dagger CI offload work
(plan 2, agent-harness#534). Not caused by that work.

````

<!-- row:R-015 -->
### R-015 — PROOFGATE: consolidate duplicate unmatched-anchor guards
- **source:** Consiliency/agent-harness#565
- **origin:** PROOFGATE, Opus early-prober on agent-harness#564 at `193865b0`
- **original ruling:** "Why this is not blocking: (a) EC-PROOFGATE-2's declared falsifier is satisfied at the group level"
- **bound criteria:** none
- **current-main check:** c0e51591: the inline guard is still at phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py:1341
- **safety floor:** not floor-class — deleting either duplicate guard still leaves a non-killed status and aggregate `blocked` (fail-closed)
- **disposition:** PARKED — Non-blocking duplicate-guard consolidation.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Follow-up from the exact-head Opus early-prober review of agent-harness#564 at `193865b09dfd72c4abf7e4f89b898cb175008e74`.

## Verbatim board finding

> The imprecision: the manifest executor `execute_proofgate_mutation_manifest` does NOT call this helper. `_execute_one` carries its own structurally identical unmatched-anchor guard at `verification_evidence.py:1237` (`if content.count(anchor) != 1:`), and that copy is neither the mutated site nor covered by any other parameter. So "the executor's unmatched-anchor `count != 1` guard is replaced" is not accurate as written; the replaced guard is the standalone primitive.
>
> Why this is not blocking: (a) EC-PROOFGATE-2's declared falsifier is satisfied at the group level - ec-2 also contains `test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline` (`test_verification_evidence.py:519-554`), which drives the real executor end to end for this same parameter and requires `applied_replacements == 1`, exercising line 1237 positively; and (b) deleting line 1237's guard degrades an unmatched anchor from `mutation_not_applied` to `survived`, and both are non-killed statuses that fail `coverage_ok` and force aggregate status `"blocked"` (`verification_evidence.py:1130-1144, 1260-1266`), so the fail-closed posture is preserved either way.
>
> Recommended production follow-up (not for this tests-only amendment): collapse `_execute_one` onto `apply_proofgate_mutation_anchor` so one guard carries the invariant and one mutation covers it.

## Disposition

Nonblocking for agent-harness#564. The inaccurate wording is corrected in that PR. Schedule the implementation consolidation after PROOFGATE closeout so it does not reopen the tests-only freeze.
````

<!-- row:R-016 -->
### R-016 — FABPUB: preserve frozen implementation-coupling follow-up
- **source:** Consiliency/agent-harness#579
- **origin:** FABPUB, exact-head tests-only board for agent-harness#578 at `075eb30e`, finding F5
- **original ruling:** "This is a schedule/rework risk, not a present correctness or safety defect."
- **bound criteria:** none
- **current-main check:** c0e51591: `_execute_with_crash` still at phase-loop-runtime/tests/test_fabpub_shared_epoch.py:2161
- **safety floor:** not floor-class — frozen tests fail closed if the implementation diverges (schedule risk)
- **disposition:** PARKED — A deferred schedule risk, not a defect.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Context

Deferred review finding from the exact-head tests-only board for Consiliency/agent-harness#578 at `075eb30e18a782bc0d42288be3a45196def5ca9a`.

- review artifact SHA-256: `0c5324480e94c2782c8aa4047196d4962970778c17b13dc9992635fa48e7032d`
- completed board SHA-256: `df762ee83a685de0a6aecb2bb0913781d600e4e2619ffa2cf499ddae51163047`

This is a schedule/rework risk, not a present correctness or safety defect. Preserve it downstream rather than expanding the current SL-0 repair.

## Verbatim finding

F5 — Frozen tests hard-couple to implementation names and import style SL-1..SL-4
     cannot renegotiate.

Because the test tree is immutable after this commit, several assertions pin details the
downstream lanes must match exactly: `_execute_with_crash` monkeypatches
`evidence_module.append_adapter_start_owner` as a module attribute
(test_fabpub_shared_epoch.py:1249-1261), which silently stops being a kill point if SL-2
imports that function by name into verbs.py; `stale_store.generation_lease = None`
(:1813) pins an attribute name on LinearizableAdmissionStore;
`GitHubBrokerAdapter(repo, run=..., generation_lease=None)` (:1822) pins a constructor
keyword; and `latch.STALE_GENERATION_BLOCKER` (:1779) pins a class constant. All of these
fail closed if the implementation diverges, so they are a schedule/rework risk rather
than a correctness hazard, but they are worth naming now while the surface is still
editable.

## Disposition

DEFERRED. The downstream FABPUB implementation lanes must either conform to these frozen names/import seams or resolve this issue through a governed test-contract change before implementation diverges.

````

<!-- row:R-017 -->
### R-017 — fix(plan): make FABPUB manifest verification lifecycle-position independent
- **source:** Consiliency/agent-harness#590
- **origin:** FABPUB plan verification command, filed 2026-08-18
- **original ruling:** "Non-blocking for FABPUB implementation; tracked to avoid changing the paneled plan mid-execution."
- **bound criteria:** none
- **current-main check:** c0e51591: tail-position selection still at plans/phase-plan-v10-FABPUB.md:368
- **safety floor:** not floor-class — a plan verification command that fails loudly (`KeyError`)
- **disposition:** PARKED — A non-blocking plan-example fix.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Problem

The verification command embedded in `plans/phase-plan-v10-FABPUB.md` selects:

- `row["lifecycle"][-2]["metadata"]["fabpub_plan_contract_rebind"]`
- `row["lifecycle"][-1]["metadata"]["fabpub_plan_contract_rebind"]`

That is valid only before execution appends a non-rebind lifecycle event. The implementation lane correctly appended an `executing` event, after which the documented verification command raises:

```
KeyError: 'fabpub_plan_contract_rebind'
```

The ledger is not corrupt: all v2-v8 rebind events are present and the latest semantic rebind validates. The command is position-dependent.

## Current workaround

Select lifecycle events whose metadata contains `fabpub_plan_contract_rebind`, then use the final two such events. This validates the v8 payload, current plan/roadmap digests, all inventory counts/digests, and record ID successfully.

## Requested follow-up

Make phase-plan manifest-binding examples select lifecycle events by semantic type rather than fixed tail position. Add a test where an `executing` or review event follows the latest contract rebind.

Non-blocking for FABPUB implementation; tracked to avoid changing the paneled plan mid-execution.

````

<!-- row:R-018 -->
### R-018 — Follow up FABPUB auth-preflight and test-seam hygiene
- **source:** Consiliency/agent-harness#596
- **origin:** FABPUB, Grok 4.6 board president, exact-head review of agent-harness#587 at `fd0708b1`
- **original ruling:** "**DEFERRED.** Style / future-test hygiene. N1 is not reachable from `cli.py` today."
- **bound criteria:** none
- **current-main check:** c0e51591: `requires_gh_auth_preflight` still at phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py:5333
- **safety floor:** not floor-class — preflight coverage and test hygiene; a `gh` call that skips preflight still fails at call time, and nothing here is an authorization control
- **disposition:** PARKED — President-DEFERRED style and test hygiene.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Deferred by the Grok 4.6 board president during the exact-head review of agent-harness#587 at `fd0708b19e485a2d7035a122d7eb6b2d1f4507a0`.

Verbatim finding and disposition:

> **Claude N1 / N2 / N3** — `requires_gh_auth_preflight` does not cover coordinator-owned `gh` calls; `_seed_run` uses `pytest.raises(Exception)`; identity-gate kwargs.
>
> **DEFERRED.** Style / future-test hygiene. N1 is not reachable from `cli.py` today.

This issue is the required downstream record before dispatch. It does not block agent-harness#587. The separate president-overruled writer-generation seam and quiescence findings are not restated as deferred findings here.
````

<!-- row:R-019 -->
### R-019 — FABREADMIT: normalize canonical max effort tokens in plan and review policy
- **source:** Consiliency/agent-harness#634
- **origin:** FABREADMIT final plan board, plan digest `da8becbe`, finding sol-1
- **original ruling:** "so the pin is a dispatch-token mismatch rather than a planner-boundary downgrade"
- **bound criteria:** none
- **current-main check:** c0e51591: `effort=`xhigh`` still at plans/phase-plan-v10-FABREADMIT.md:275,280
- **safety floor:** not floor-class — a vocabulary token; the president ruled `xhigh` is Codex's encoding of canonical `max`, not a reasoning downgrade
- **disposition:** PARKED — A president-DEFERRED vocabulary normalization.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Deferred board finding

Plan digest: `da8becbe1f0f7cc61c4b4eeb5cef577704acb82e78febb0408c659322b64453f`

The final FABREADMIT plan board recorded the following finding verbatim:

> FINDING sol-1: The plan pins its planner-of-record to `effort=xhigh` (`plans/phase-plan-v10-FABREADMIT.md:270`), overriding the governing roadmap’s mandatory `effort=max` planner boundary (`specs/phase-plans-v10.md:1337,1344`); this nonwaivable policy regression requires a repaired digest and renewed panel before SL-0 dispatch.

## President disposition

> FINDING sol-1: DEFERRED — Codex `xhigh` is this executor’s CLI encoding of canonical `max`, so the pin is a dispatch-token mismatch rather than a planner-boundary downgrade; SL-0 does not invoke the planner, and this confirmation round already sat at max, so a digest repair plus renewed panel is not required before the tests-only lane may begin. File the finding verbatim before dispatch.
>
> FORCING DECISION: PROCEED — file sol-1 before SL-0 dispatch; no repaired digest or renewed panel.

## Follow-up scope

Normalize the FABREADMIT plan and review policy surfaces to express canonical `max` while preserving the executor-specific Codex mapping to `xhigh`. The current launcher mapping treats canonical `max` as Codex `xhigh`; this issue records a vocabulary mismatch, not a runtime reasoning downgrade.

This issue is non-blocking for the FABREADMIT tests-only lane under the digest-bound president ruling above.

````

<!-- row:R-022 -->
### R-022 — test(PROOFGATE): prevent detached Git maintenance from racing temp-repo cleanup
- **source:** Consiliency/agent-harness#656
- **origin:** FABREADMIT broad selector at candidate `b4ace6e8`; Grok 4.6 president ruling on agent-harness#655
- **original ruling:** "president disposition: **DEFERRED; does not block FABREADMIT code**."
- **bound criteria:** none
- **current-main check:** c0e51591: node still at phase-loop-runtime/tests/test_tdd_chronology.py:5746; no `gc.auto` stabilization under phase-loop-runtime/tests
- **safety floor:** not floor-class — a temp-directory cleanup race that fails loudly (`OSError`)
- **disposition:** PARKED — President-DEFERRED test-infrastructure flake.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Problem

The broad FABREADMIT selector intermittently fails after all substantive assertions pass because `test_pr_r_blocker_fable_f008_verifier_requires_candidate_binding_and_whole_file_reports_digest` calls `TemporaryDirectory.cleanup()` while detached Git auto-maintenance is still recreating content under the synthetic repository's `.git` directory.

Observed at FABREADMIT candidate `b4ace6e83985f6daaac4603d4c012e2123b30f3c`; this test and its helper are unchanged from tests-only base `a4fd0fed00c246435e69e866ca9226dd59054c45`.

## Reproduction

```bash
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q \
  phase-loop-runtime/tests -k "broker or admission or convergence or fab"
```

The selector can end `1 failed, 664 passed` with:

```text
tmp.cleanup()
OSError: [Errno 39] Directory not empty: '.git'
```

After the failure, the otherwise removed synthetic repository contained only `.git/objects/info`, confirming a post-cleanup Git writer. The node passes by itself on both the untouched base and candidate. A process-local run with `gc.auto=0` is terminal green:

```bash
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=gc.auto \
GIT_CONFIG_VALUE_0=0 \
PYTHONPATH=phase-loop-runtime/src \
python3 -m pytest -q phase-loop-runtime/tests \
  -k "broker or admission or convergence or fab"
```

Result: `665 passed, 26 skipped, 4548 deselected, 80 subtests passed`.

The likely trigger is `_setup_real_repo_candidate_history()` copying and initially committing a large source tree, which crosses Git's auto-maintenance threshold; the detached writer outlives the synchronous `git commit` subprocess.

## Requested repair

Disable Git auto-maintenance in the synthetic repository itself before its first commit, or explicitly wait for/avoid detached maintenance before `tmp.cleanup()`. Add a broad-selector regression proving cleanup is deterministic without requiring coordinator environment overrides.

Related review record: agent-harness#655. This issue is verification-infrastructure work and does not by itself determine the FABREADMIT president disposition.

````

Comment by ViperJuice at 2026-08-25T07:27:31Z:

````markdown
FABREADMIT candidate `b4ace6e83985f6daaac4603d4c012e2123b30f3c` president disposition: **DEFERRED; does not block FABREADMIT code**. The unstabilized selector failed only during `TemporaryDirectory.cleanup()` while `.git/objects/info` was recreated; the process-local `gc.auto=0` run was terminal green at 665 passed / 26 skipped / 80 subtests. Full verbatim ruling: agent-harness#655 comment 5406980246.
````

<!-- row:R-024 -->
### R-024 — Test follow-up: distinguish final confirmation exhaustion reason from first observation
- **source:** Consiliency/agent-harness#847
- **origin:** publish confirmation, final four-vendor panel of agent-harness#846 at `55bd7ff6`
- **original ruling:** "this is a test-strengthening gap, not an observed production bug."
- **bound criteria:** none
- **current-main check:** c0e51591: phase-loop-runtime/tests/test_pr_readback_789.py:109-112 still has only the matching-classification exhaustion cases
- **safety floor:** not floor-class — a test-strengthening gap; the merged implementation recomputes the final reason
- **disposition:** PARKED — Non-blocking test strengthening.
- **promotion:** none
- **finding:**

Issue body:

````markdown
## Non-blocking review follow-up

The final native four-vendor panel for agent-harness#846 approved head
`55bd7ff67e0bfce904ae061d26d867b70c911234` unanimously. Fable identified one
additional negative control worth adding after this bounded fix landed.

The mixed exhaustion cases currently use empty/stale/empty and
stale/empty/stale. They exercise mixed observations, but their initial and final
classifications match. They do not distinguish a deliberately stateful mutant
that retains the first observation's terminal reason from the required final
observation's reason. The merged implementation recomputes the final reason
correctly; this is a test-strengthening gap, not an observed production bug.

## Acceptance

- Add empty/empty/stale and stale/stale/empty exhaustion cases to the existing
  confirmation tests, with exact final reason, observation and sleep counts.
- Prove a first-observation-reason mutant fails these cases.
- Retain immediate refusal, bounded observation, and once-only push/create
  controls. No production change is expected.

Parent incident: agent-harness#789. Source and full review record:
https://github.com/Consiliency/agent-harness/pull/846#issuecomment-5672494503

````
