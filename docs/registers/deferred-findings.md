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
- **disposition:** EXCLUDED — reproduced in package CI after substantive assertions; agent-harness#656 is in flight in a separate repair branch, outside agent-harness#883.
- **status (2026-10-14):** agent-harness#656 was fixed and closed on 2026-09-23 (`gc.auto=0` in `test_tdd_chronology.py`); agent-harness#945 (`3eb083b7`) extended the same setting to `phase_loop_test_utils.make_repo`.
- **promotion:** PROMOTED 2026-09-17 — [agent-harness#656 recurrence evidence](https://github.com/Consiliency/agent-harness/issues/656#issuecomment-5712891240).
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

<!-- row:R-025 -->
### R-025 — FABPUB: deferred board findings from agent-harness#1552 (stale routing client wording and handoff)
- **source:** Consiliency/agent-harness#1573
- **origin:** FABPUB, advisor-board ruling on agent-harness#1552 (fixes agent-harness#1315), merge authorized at `9f0fbc18`
- **original ruling:** "FINDING F008: DEFERRED — four non-blocking suggestions: S1 double pointer read affects the message only (ruled above); S2 dead `gen0` reassignment in the test is harmless; S3 a comment on the refuse-until-close behaviour would help readers; S4 the "restart after rotation" SDK handoff is Lane C work and should be tracked there. None names a broken acceptance, contract or test." — president
- **bound criteria:** none
- **current-main check:** 8db24571: ask 1 — runbook §6 still says the client "refuses every later request … before it reads or writes either generation's store" (docs/fabpub-partition-rotation-runbook.md:343-345); ask 2 — `_stores_for` still reads `snapshot.store_root` in both the comparison and the message (phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py:6070,6078); ask 3 — the message still says "A partition rotation completed" (live.py:6078); ask 5 — `gen0 = _tree(p.container)` is still assigned twice (phase-loop-runtime/tests/test_fabpub_stale_client_1315.py:156,166); ask 4 resolved by agent-harness#1626 (`7ae99e04`, `rebuild_broker_client_and_retry`, publishing.py:1539)
- **safety floor:** concurrency or TOCTOU on an evidence path — ask 1 documents the check-to-execute window of the per-request generation check; asks 2, 3 and 5 are message text and test tidying, not floor-class; callers negative: phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py:6040 (`_stores_for`, the only builder of a routing client's store pair): it acquires a writer-generation lease for the client's lifetime (live.py:6058), and a rotation refuses at DRAINING while any generation lease is held (live.py:741), so no production caller reaches the window; it opens only after an operator clears that lease by hand under runbook §6
- **disposition:** PARKED — President-DEFERRED wording, message and test tidying (asks 1, 2, 3, 5); ask 4 was resolved by agent-harness#1626.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Deferred findings from the advisor-board ruling on Consiliency/agent-harness#1552, which fixes agent-harness#1315. The president deferred every one of them (non-blocking) and authorized the merge at `9f0fbc18`. Filed under the agent-harness#442 rule that every `DEFERRED` finding gets an issue carrying its verbatim text.

## Verbatim president rulings (deferred findings with content)

```
FINDING F001: DEFERRED — Grok seat ERRORed before reviewing (agent-harness#1460, host defect); no finding to rule on. Stand-in rulings: S1 DEFERRED — the check-to-execute window is real (reproduced: replay `accepted=True` from the retired ledger, or untyped `epoch permanently blocked`; no write, no provider call) but exists only in the §6 deviation, gives pre-PR behaviour, does not break agent-harness#1315's acceptance, and the runbook/CHANGELOG sentence describes post-flip requests on its plain reading; tighten to "every request it starts after the flip" in a follow-up doc touch; S2 DEFERRED — "a partition rotation completed" is imprecise after an `after_pointer_flip` crash; "moved the ACTIVE generation" is the accurate phrase; message text only; S3 DEFERRED — the `repair_fabpub_authority` handoff for this refusal is publishing-side work the PR correctly leaves to Lane C.
FINDING F008: DEFERRED — four non-blocking suggestions: S1 double pointer read affects the message only (ruled above); S2 dead `gen0` reassignment in the test is harmless; S3 a comment on the refuse-until-close behaviour would help readers; S4 the "restart after rotation" SDK handoff is Lane C work and should be tracked there. None names a broken acceptance, contract or test.
FINDING F014: DEFERRED — concurrence; note the hot-path cost is one pointer-file read per request, not purely an in-memory comparison, which is negligible and fail-closed as the Claude seat states.
```

## Verbatim: stand-in adversarial seat S1–S3 (substituted for the Grok seat, agent-harness#1460)

## Suggestions (non-blocking)
- **S1 (wording; residual TOCTOU).** The check is per-request at entry, not under the store lock. A rotation that completes between the check and `BrokerService.execute` gives the pre-PR answers: a replay from the retired ledger, or an untyped `epoch permanently blocked` (probes 3 and 4). This can only happen in the §6 deviation, because a held lease makes the rotation refuse. It does not break agent-harness#1315's acceptance ("refuses typed rather than writing to the retired generation or blocking it"): nothing is written and the successor stays usable. It does make the runbook §6 and CHANGELOG sentence "refuses every later request … before it reads or writes either generation's store" slightly stronger than what the code guarantees for a request that is already in flight. Consider "every request that starts after the flip". Alternatively, note that an in-flight request can still get the retired generation's answer and that the write fences remain the backstop.
- **S2 (message precision).** The message says "A partition rotation completed after the client was built". After an `after_pointer_flip` crash, the pointer has moved but the ceremony has not finished. The refusal is still correct, but "a partition rotation moved the ACTIVE generation" would be accurate in every case.
- **S3 (handoff, out of scope).** An SDK caller that routes this refusal through `publishing.py` gets `next_step="repair_fabpub_authority"`. The real remedy is "close or restart the client". The PR already defers this to Lane C, and that is the right owner.


## Verbatim: Claude seat suggestions

## Non-blocking suggestions
- S1: The refusal message reads `snapshot.store_root` a second time, which means a second pointer read. If a further rotation lands between the comparison and the message, the message names the newer generation, or the second read can raise `PartitionRoutingRefused`. Binding `active = snapshot.store_root` once would make the comparison and the message consistent. This affects the message only.
- S2: In the test, `gen0 = _tree(p.container)` is assigned twice, before and after `git worktree add`. The first assignment is dead code. `git worktree add` writes under `.git/worktrees`, outside the container, so either value works.
- S3: The stale `_stores`/`_leases` entries stay after the refusal, by design (no rebind). `close()` releases the orphaned lease with exceptions suppressed, which is correct. A one-line comment saying so would make the refuse-forever behaviour explicit for future readers.
- S4: An SDK-facing handoff that says "restart after rotation", distinct from `repair_fabpub_authority`, is correctly deferred to the publishing lane. Make sure it is tracked.


## Asks
1. Runbook §6 and CHANGELOG wording: say "every request it starts after the flip …; a request already past the check when the flip lands gets the retired generation's answer and is still fenced from writing."
2. In `_stores_for`, read the ACTIVE `snapshot.store_root` into a variable once and use it in both the comparison and the message.
3. In the refusal message, say "moved the ACTIVE generation" instead of "a partition rotation completed".
4. Have the publishing handoff for `WriterGenerationBlocked` (an SDK client built before a rotation) say "close/restart the client" instead of `repair_fabpub_authority`. This belongs with the typed-handoff follow-up.
5. Tidy the test: remove the dead `gen0` reassignment and add a comment explaining that clients refuse until they are closed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-13T02:34:35Z:

````markdown
Disposition (docs/registers/deferred-findings.md): **PARKED**. The board classed every item here DEFERRED and non-blocking. None is safety-floor class: the in-flight window is fenced from writes by `_authorize`/`_require_generation`, which the president reproduced (no write, no provider call). Ask 4 overlaps with the typed-handoff follow-up for publishing.py. This stays open until it is picked up or a register row lands.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-14T08:19:11Z:

````markdown
**Ask 4 is resolved by agent-harness#1626** (merged). A routing client built before a rotation now gets `rebuild_broker_client_and_retry`. The remaining asks stay PARKED.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

<!-- row:R-026 -->
### R-026 — FABPUB: deferred board findings from agent-harness#1553 (post-provider failure mislabelled ambiguous; handoff wording)
- **source:** Consiliency/agent-harness#1574
- **origin:** FABPUB, advisor-board ruling on agent-harness#1553 (fixes agent-harness#1312), merge authorized at `d2210f85`
- **original ruling:** "FINDING F009: DEFERRED — suggestions S1-S4 (cite runbook §1/§6; note `--authority-root`/env parity, a gap shared with the pre-existing `resolve_publication_recovery_refusal` argv; "sealed checkpoint's transaction_id" wording; train route gets the field but no handoff, outside agent-harness#1312's human-route scope). None names a broken acceptance, declared contract, or regressed test; doc/wording hygiene for a follow-up." — president
- **bound criteria:** none
- **current-main check:** 8db24571: ask 4 — phase-loop-runtime/src/phase_loop_runtime/train_runner.py:2692 still calls `publish_from_worktree` directly, and train_runner.py attaches no handoff (`git grep handoff` is empty there); asks 1–3 resolved by agent-harness#1593 (`6ec65342`), agent-harness#1626 (`7ae99e04`) and agent-harness#1633 (`cd67eb28`, `test_human_handoff_requires_observed_landed_and_its_builder_rotates` at phase-loop-runtime/tests/test_fabpub_observed_after_ambiguity_1591.py:576)
- **safety floor:** not floor-class — a missing advisory handoff on the governed route; the extra `terminal_state` key is additive and no authority or evidence decision reads it
- **disposition:** PARKED — Ask 4 only, a President-DEFERRED handoff gap outside agent-harness#1312's scope; asks 1–3 were resolved by agent-harness#1593, agent-harness#1626 and agent-harness#1633.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Deferred findings from the advisor-board ruling on Consiliency/agent-harness#1553, which fixes agent-harness#1312. The president deferred all of them (non-blocking) and authorized the merge at `d2210f85`. This issue is filed under the agent-harness#442 rule that every `DEFERRED` finding gets an issue carrying its verbatim text.

## Verbatim president rulings (deferred findings with content)

```
FINDING F009: DEFERRED — suggestions S1-S4 (cite runbook §1/§6; note `--authority-root`/env parity, a gap shared with the pre-existing `resolve_publication_recovery_refusal` argv; "sealed checkpoint's transaction_id" wording; train route gets the field but no handoff, outside agent-harness#1312's human-route scope). None names a broken acceptance, declared contract, or regressed test; doc/wording hygiene for a follow-up.
FINDING SG-F1: DEFERRED — reproduced by execution on d2210f85 (probe: first attempt reports `terminal_state=outcome_ambiguous_blocked` and the rotation handoff while the store holds `effect_terminal_observed`; a plain retry replays `published` with no second provider call). It does not block under the charter rule: (1) the mislabel is pre-existing on main — `_fresh_publish`'s `except` returns `OUTCOME_AMBIGUOUS_BLOCKED` / `reason="outcome_ambiguous"` regardless of the stored row, so main already reported this post-provider failure as an ambiguous block; the PR only changed which handoff text attaches, and main's generic retry advice was right by accident, not by any stated guarantee; (2) agent-harness#1312's acceptance (a genuine `outcome_ambiguous_blocked` replay gets `adjudicate_publication_by_partition_rotation`) is met; (3) the PR's declared contract is to key on the typed enum rather than message text, which the code does — the enum value is wrong upstream in verbs.py (Lane A, outside the declared NARROW blast radius); (4) no existing test or invariant covers this path. Harm is bounded and fails closed: `epoch_blocked` derives only from stored `outcome_ambiguous_blocked` rows (evidence.py:300), and the rotation refuses with "has no ambiguity-blocked effect; nothing to rotate" (live.py:4713); any retry self-heals. Required follow-up (file as an issue): fix the verbs.py label to return `current.state` when the stored row is already terminal, and/or soften `resume`/`next_step_source` to "if a retry returns `published`, no rotation is needed".
FINDING SG-F2: DEFERRED — `recovery_procedure` omits runbook §6 (and §1); consistent with runbook 8a step 3 itself, so doc hygiene for the same follow-up as F009/S1.
FINDING SG-F3: DEFERRED — repeat-ambiguity warning ("do not attest `attested_not_landed` a second time without new evidence") not repeated in `rotate_requires`; the runbook 8a the handoff cites already carries it. Wording suggestion.
FINDING SG-F4: DEFERRED — the runbook's "retry after the rotation replays it as published" claim is tested only at broker level (test_fabpub_partition_rotation_789d.py); an end-to-end human-route test is a welcome follow-up, not a regression.
```

## Verbatim: stand-in adversarial seat (it replaced the Grok seat, see agent-harness#1460)

- Adversarial probe `tests/test_adv_1553_probe.py` (scratch only) is described under F1.

## Attack surface checked, no defect found

1. **Can a non-ambiguous state get the rotation handoff?** Only `publish_human_invoked_from_worktree` attaches it, and only when `result["terminal_state"] == TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value`. `rejected_before_start`, `no_effect_terminal_proven` and `provider_not_supported` keep the generic handoff. The test covers `no_effect_terminal_proven`. Results that already carry a handoff (for example `resolve_publication_recovery_refusal`) are not touched, because of the `"handoff" not in result` guard. That branch is unchanged.
2. **Governed/train route.** `train_runner.py:2692` calls `publish_from_worktree` directly. No handoff is attached there. The only change it sees is one extra key in the `detail` dict it returns. The ledger `LedgerRecord` does not persist `detail`. I found no JSON or YAML schema, contract test or exact-dict assertion on `publication_blocked` / `HumanPublicationHandoff` anywhere in the repo. The train tests pass.
3. **The rotate argv.** It is identical to the existing `rotate_command_when_key_blocked` and matches the CLI parser (`cli.py:899-906`): `--worktree`, `--attestation` and `--cutover-id` are required, and `--json` is valid. The authority root is optional and is derived from `FABPUB_AUTHORITY_ROOT` the same way the route derives it. The attestation and cutover id are placeholders, so the command cannot run as pasted. The verb refuses an attestation inside the ceremony directory. `rotate_blocked_partition` refuses a predecessor that is not ambiguity-blocked. A mistaken rotate therefore fails closed.
4. **Docs vs code.** The runbook 8a paragraph, the pre-admission-ambiguity paragraph and the CHANGELOG all match the code. One exception is the narrow case in F1.

## Findings

### F1 (non-blocking, confirmed by execution): a synthetic "ambiguous" result gets an authoritative "rotate, only after the rotation" handoff although the key is not blocked

`_fresh_publish` (verbs.py:772-782) wraps the adapter call **and** the steps after it in a single `try`: recording the terminal, sealing the owner and `advance("TERMINAL_SEALED")`. Its `except` always returns `BrokerTerminalEvidence(key, OUTCOME_AMBIGUOUS_BLOCKED, "adapter-exception")`. It records ambiguity in the store only if the stored row is still `provider_call_in_flight`. So if the provider call succeeded and a later step raises, the result says `outcome_ambiguous_blocked` while the store holds the real terminal. Examples of such a step: `seal_adapter_start_owner` raising an I/O error, or the checkpoint projection failing.

The probe stubbed the adapter to return `effect_terminal_observed` and made the first `seal_adapter_start_owner` raise `OSError`:

```
FIRST publication_blocked outcome_ambiguous outcome_ambiguous_blocked adjudicate_publication_by_partition_rotation
STORE ['provider_call_in_flight', 'effect_terminal_observed']
RETRY published None None None 1        # replayed as published, no second provider call
```

On main, this case got `repair_publication_precheck_and_retry`, and that advice was correct: the retry succeeds. On this head the operator is told:
- `resume`: "only after the rotation";
- `next_step_source`: "a retry before a rotation replays the same block";
- to follow a procedure whose §6 calls for a maintenance-reboot boundary.

All three are false here. The harm is bounded. The rotation would refuse, since the partition is not ambiguity-blocked, so nothing unsafe can happen. Any retry self-heals. The trigger is an I/O failure after the provider call.

It does not block, because it breaks no stated acceptance criterion, declared contract or existing test. But it contradicts the PR's own claim that the match is "on the typed state". In this path the "typed" `terminal_state` is the `except` branch's placeholder, not the recorded evidence. The root fix is in verbs.py (Lane A). It would return `current.state` when the stored row is already terminal.

Cheap mitigations in this PR, either one:
- (a) Soften `resume` / `next_step_source`: "a retry replays the block if the key is ambiguous in the store; if a retry returns `published`, no rotation is needed".
- (b) In the human route, confirm the key's latest evidence row before choosing the rotation step.

Suggest filing the verbs.py mislabel as a follow-up either way.

### F2 (suggestion): `recovery_procedure` leaves out runbook §6

The handoff cites §§3, 4, 7 and 8a. §6 ("Stop writers and clear orphaned leases — STATE CHANGE, needs go", including the maintenance-reboot boundary) is what lets the §4 preflight return `ready`. 8a step 3 skips it too, so the handoff is consistent with 8a. Still, a handoff that operators will follow literally should name §6 and §8 step 1. `after_rotation` covers the broker restart but not §6.

### F3 (suggestion): repeat ambiguity in generation N+1

After a recovery attempt that is itself ambiguous, this handoff fires again and points to the same rotation. Runbook 8a says: "Do not attest `attested_not_landed` a second time without new evidence ... Two ambiguous pushes are not evidence of no effect." `rotate_requires` does not repeat that warning. Consider adding one clause.

### F4 (note): the doc claim about `observed_landed` is tested only at broker level

The new runbook sentence "the retry after the rotation replays it as published" matches broker behaviour: `test_fabpub_partition_rotation_789d.py::test_partition_rotation_a1_observed_landed_is_answered_as_a_duplicate`. I traced `publish_from_worktree` and found no transaction gate that would refuse a TERMINAL_SEALED checkpoint before the broker replay. However, no human-route test covers this end to end. Not blocking.

## Verdict

The change does what agent-harness#1312 asks for. A genuine `outcome_ambiguous_blocked` replay, and the first ambiguous attempt in both its adapter-terminal and adapter-exception forms, now get `adjudicate_publication_by_partition_rotation`. Every other blocked state and the `resolve_publication_recovery_refusal` branch are unchanged. The emitted command matches the CLI and fails closed. `terminal_state` is purely additive for every consumer I could find.

F1 is a real but bounded mis-instruction on a post-provider I/O-failure path. It is worth a wording fix or a follow-up, and it does not block.


## Asks
1. **SG-F1 (substantive).** `verbs.py` `_fresh_publish` labels any exception raised *after* the provider call as `outcome_ambiguous_blocked`, even when the store already holds the real outcome (`effect_terminal_observed`). The human route now turns that label into a rotation handoff the operator doesn't need. Fix: when the stored row is already terminal, return its state; and/or soften `resume`/`next_step_source` to say "if a retry returns `published`, no rotation is needed". The probe that reproduces this is `phase-loop-runtime/tests/test_adv_1553_probe.py` in the stand-in's scratch tree.
2. **Handoff wording:**
   - cite runbook §1/§6 in `recovery_procedure`;
   - note that `--authority-root`/env must match;
   - say "the sealed checkpoint's `transaction_id`";
   - repeat the warning against a second `attested_not_landed` attestation without new evidence.
3. **Test.** Add an end-to-end human-route test for "a retry after rotation replays `published`".
4. **Not in agent-harness#1312's scope.** The train/governed route now receives `terminal_state` but no handoff.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-13T02:35:02Z:

````markdown
Disposition (docs/registers/deferred-findings.md):
- **Ask 1 (SG-F1): STILL-LIVE.** The mislabel is reachable on main: `_fresh_publish`'s `except` branch returns `OUTCOME_AMBIGUOUS_BLOCKED` whatever the stored row says. It fails closed. The rotation refuses with "nothing to rotate", and a plain retry replays `published`.
- **Asks 2–4: PARKED.** These are wording and test-coverage suggestions that the board classed as DEFERRED.

The issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-13T16:07:13Z:

````markdown
**Ask 1 (SG-F1) is resolved by agent-harness#1593**, merged as 6ec65342. After the provider call, the broker now returns the terminal state the store holds instead of always reporting `outcome_ambiguous_blocked`. A failure before the provider call, such as a lease refusal, no longer records ambiguity. Asks 2–4 (wording and tests) remain PARKED, so this issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-14T08:19:15Z:

````markdown
**Ask 2 is resolved by agent-harness#1626** (merged). Rotation handoffs now:
- cite runbook §§1, 3, 4, 6, 7, 8a;
- require authority-root parity;
- name the source of the `transaction_id`;
- warn against a second `attested_not_landed`.

Ask 3, an end-to-end test of retry after rotation, is still open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

<!-- row:R-027 -->
### R-027 — FABPUB: deferred board findings from agent-harness#1550 (mixed-version recovery-record conflict; chain-walk docs)
- **source:** Consiliency/agent-harness#1576
- **origin:** FABPUB, advisor-board ruling on agent-harness#1550 (fixes agent-harness#1310), merge authorized at `b9a0e75d`
- **original ruling:** "FINDING F022: DEFERRED — S2 doc/test precision; docstring "(None)" is inaccurate (carry check raises RecoveryChainSuperseded first), outcome unchanged; a real-rotation observed_landed test is a welcome follow-up." — president; SA-F5: "O(A^2) receipt loads on the recovery path only, acceptable"
- **bound criteria:** none
- **current-main check:** 8db24571: ask 3a — the `attested_not_landed_recovery` docstring still says `observed_landed` "hides an older `attested_not_landed` (`None`)" (phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py:1606); ask 3b — runbook §8a still says a later receipt "carries or re-adjudicates it" (docs/fabpub-partition-rotation-runbook.md:516); ask 3c — no test drives the walk through a real `observed_landed` rotation; ask 4 — the runbook has no walk-cost note; asks 1 and 5 resolved by agent-harness#1627 (`cba3aebd`; the authorization-record sentence is at runbook:539), ask 2 by agent-harness#1551 (`b5f943d4`) with its regression in agent-harness#1593
- **safety floor:** not floor-class — docstring and runbook precision, a test gap and a recovery-path cost; the walk's refusal outcome is unchanged and nothing is accepted that should be refused
- **disposition:** PARKED — President-DEFERRED docs, test and cost items (asks 3a, 3b, 3c, 4); asks 1, 2 and 5 were resolved by agent-harness#1627 and agent-harness#1551/agent-harness#1593.
- **promotion:** none
- **finding:**

Issue body:

````markdown
These are the deferred findings from the advisor-board ruling on Consiliency/agent-harness#1550, which fixes agent-harness#1310. The president deferred every finding as non-blocking and authorized the merge at `b9a0e75d`. They are filed under the agent-harness#442 rule that every `DEFERRED` finding gets an issue that carries its verbatim text.

## Verbatim president rulings (deferred findings with content)

```
FINDING F001: DEFERRED — Grok seat ERRORed (agent-harness#1460); lens covered by the Opus stand-in, whose probes I re-ran (7 passed). Stand-in rulings: SA-F1 DEFERRED — reproduced both directions; typed PublishTransactionConflict before any owner/admission/provider call, blocked result not tombstone, same-version retry proceeds; the ah#789 contract (typed refusal before durable owner acquisition, no stranded owner) holds, no acceptance item or existing test regresses; follow-up: accept existing record equal to payload minus the three new fields (or emit them only with intervening rotations) and name the record in the conflict handoff; SA-F2 DEFERRED — pre-existing, lock section unchanged except message text, fresh publishes on main behave the same; closed by sibling agent-harness#1551 `_restore_owner_bytes`; SA-F3 DEFERRED — negative result, lease refuses the mid-walk rotation, confirms safety argument; SA-F4 DEFERRED — negative result, two attestations yield exactly two calls, observed_landed never reaches the older disposition; SA-F5 DEFERRED — O(A^2) receipt loads on the recovery path only, acceptable; SA-F6 DEFERRED — docstring "(None)" and runbook 8a wording inaccurate but outcome is still refusal and no safety contract is falsified, one-sentence fixes; SA-F7 DEFERRED — provenance-first record is main's design, document it as an authorization record.
FINDING F005: DEFERRED — summary of a non-blocking liveness regression (S1); ruled with SA-F1 above: fails closed before any write, follow-up.
FINDING F020: DEFERRED — S1 consequence (key waits for an unrelated rotation or record removal; handoff does not name the record); narrow skew window, no owner or provider call, follow-up.
FINDING F021: DEFERRED — S1 proposed fix; endorsed as the follow-up (subset-accept in record_recovery, or conditional fields) but not required for this head.
FINDING F022: DEFERRED — S2 doc/test precision; docstring "(None)" is inaccurate (carry check raises RecoveryChainSuperseded first), outcome unchanged; a real-rotation observed_landed test is a welcome follow-up.
```

## Verbatim Claude seat suggestions

## Suggestions (non-blocking)

**S1. Mixed-version record conflict (confirmed).** Scenario:
1. A 1296-era runtime, in the disposing generation `d == A`, writes `<tid>.recovery.<A>.json`.
2. It then fails before the owner write (a crash, or contention).
3. The runtime is upgraded.
4. The retry in the same generation now raises `PublishTransactionConflict("a different recovery is already recorded ...")`, because the new payload has three extra fields.

My scratch test reproduces this with no provider call. Generation `A` holds no evidence for the key, so it is not blocked and cannot be rotated for this key. Recovery then needs an unrelated blocking rotation, or a maintainer to remove the record. The `resolve_publication_transaction_conflict` handoff does not point at the record.

Suggested fix: in `record_recovery`, accept an existing record that equals the new payload minus `disposing_generation`, `readmitting_generation` and `intervening_rotations`. This only applies when `d == A`, and every shared field is then identical by construction. Alternatively, omit those three fields when `d == A`.

**S2. Doc/test precision.** The docstring and PR say a newer `observed_landed` "hides" an older disposition and returns `None`. But `_rotation_carried_effects` also puts `observed_landed` keys into `legacy_completed_effect_keys`, so the walk raises `RecoveryChainSuperseded` ("carries ... as a completed effect") before it reads the disposition. The outcome is still a refusal, and in practice `_legacy_terminal_replay` answers first because receipt `A` carries the key. C4 as shipped tests re-attestation, not `observed_landed`, and the carry test is monkeypatched. A real-rotation `observed_landed` test would close that gap.

**S3. Cost.** The cost is O(A·(A−d)) re-authentications, which is acceptable as argued. Note it in the runbook if partitions are ever expected to rotate often.


## Verbatim stand-in adversarial/red-team findings (the Grok seat was replaced, agent-harness#1460; Codex reviewed diff-only, agent-harness#1335)

**SA-F1 (suggestion, the strongest mixed-version item). The recovery record conflicts in BOTH directions, and an unrelated rotation clears it but leaves a stale record.**
- *Probe:* `test_old_record_self_heals_on_unrelated_rotation_and_reverse_direction`. First, a 1296-format record is written in generation 1 and the runtime crashes before the owner write. A retry on the new runtime then fails with `(a) PublishTransactionConflict a different recovery is already recorded at …`. Next, one unrelated block and rotation to generation 2 lets the new runtime recover: `(b) BrokerExecutionResult True 1`, records `['….recovery.1.json', '….recovery.2.json']`. The generation-1 file still states that a re-admission was authorized in generation 1, which never ran.
- *Reverse direction:* `test_reverse_mixed_version_new_record_then_main_retry` shows that a new-format record followed by a main/1296-format retry in the same generation also fails, with `REVERSE PublishTransactionConflict`. The correctness seat tested only old→new. This direction is the realistic one during a staggered fleet upgrade, where one host runs main and another runs this PR.
- *Reachability:* a record is written but no owner follows. That happens after a crash, or after the PermissionError `contended twice in one publish; retry`. Both occur after `record_recovery` and before any owner write by this attempt.
- *Why not blocking:* the ah#789 contract (`docs/fabpub-pre-admission-ambiguity.md`, Workstream A) is a typed, actionable refusal before durable owner acquisition. That still holds: the refusal comes before any owner or provider call. The key is not stranded permanently either. It recovers after any later rotation or after the stale file is removed by hand.
- *Fix (cheap, closes both directions):* emit `disposing_generation`, `readmitting_generation` and `intervening_rotations` only when `intervening_rotations` is non-empty. A record with no intervening rotation is then byte-identical to the 1296 payload, because `generation` = disposing = active, as in 1296. A record with an intervening rotation is never written by main, because main refuses before `record_recovery`. This fix requires changing one assertion in the PR's own test: `test_the_newest_disposition_is_the_current_word` asserts `(record["disposing_generation"], record["intervening_rotations"]) == (2, [])`, which would fail with `KeyError`. Alternatively, `record_recovery` could accept an existing record whose fields are a subset of the new payload. The PR body's claim "With no intervening rotation, every existing field keeps today's value" is true, but it is not byte compatibility, and the record comparison is byte/dict equality.

**SA-F2 (suggestion; pre-existing, outside this PR's diff, file as a follow-up). A denied in-lock admission leaves an unsealed owner, which uses up the disposition with no provider effect.**
- *Probe:* `test_toctou_rotation_between_walk_and_owner_write`. After the walk authorizes a recovery in generation 2, an unrelated key is blocked in generation 2. That is an evidence-lock append, which can interleave with the admissions lock. Output: `RACE result PermissionError broker admission denied calls 0`, then `RACE owner after {... 'effect_key': K, 'sealed': False, 'transaction_id': T1}`.
- *Cause:* `_owner_and_admission_under_one_lock` writes the owner (`append_adapter_start_owner`). Only then does `admit_next` check `self.epoch_blocked()` and raise `broker admission denied`. The traceback confirms this site: `RACE denial frames ['verbs.py:810', 'verbs.py:726', 'verbs.py:555', 'admission.py:533']`.
- *Consequence (observed):* the next retry fails with `RACE next retry PermissionError unsealed adapter-start owner blocks fresh provider effect calls 0`, and K's rows in generation 2 become `['provider_call_in_flight', 'outcome_ambiguous_blocked']`. K is now blocked permanently in the generation that was meant to re-admit it. Every later retry replays that blocked row. The disposition is used up without any provider call, and a fresh attestation and rotation are needed. This is the 1296 failure class ("a denied precondition used to leave a fresh unsealed owner behind"), reached through the epoch-block leg instead of the state leg.
- *Why not blocking:* the lock section is unchanged by this PR (only its message text changed), and fresh publishes on main have the same behaviour. It fails closed, with no double effect. Suggested fix: check `admission_store.epoch_blocked()` / `evidence_store.epoch_blocked` inside the section before `append_adapter_start_owner`.

**SA-F3 (suggestion: negative result, no change requested; TOCTOU between the walk and the write).** The same probe also tries to rotate the partition between the walk and the owner write. The rotation is refused: `PartitionRotationRefused('… DRAINING did not reach zero before INVENTORY_SEALED: 1 held generation lease(s)')`. The routed service's generation lease therefore closes the window. Separately, a write from a stale-generation service is refused by `_require_active_generation_root` (inside the lock, through `append_adapter_start_owner`'s authorize). Sealed generations cannot race, because the walk reads each file once and checks it against its digest. The safety argument in the PR body holds.

**SA-F4 (suggestion: negative result, no change requested; multi-rotation and mixed-disposition chains).**
- `test_chain_two_dispositions_interleaved_unrelated_rotations` runs this sequence: K disposed@1, unrelated@2, ambiguous recovery in generation 2, K re-disposed attested_not_landed@3, unrelated@4, recovery lands in generation 4 (`RECORD@4 3 ['rotation-adv-4']`), unrelated@5. The retry then replays (`AFTER@5 BrokerExecutionResult True 1`). Two attestations produced exactly two provider calls, never a third.
- `test_chain_redisposed_observed_landed_never_recovers` runs: K disposed@1, unrelated@2, ambiguous recovery in generation 2, K adjudicated `observed_landed`@3, unrelated@4. Result: 0 provider calls, the carried terminal is replayed (accepted=True), and the walk raises `RecoveryChainSuperseded`. The older attested_not_landed disposition is never reached.
- Carried effects build up across rotations (`_rotation_carried_effects` starts from the predecessor's sealed effects). A key that has landed therefore stays carried in every later receipt and is checked before any disposition. A key gets "popped" from the carried set only by a new adjudication, and adjudication requires the key to be blocked in the predecessor.

**SA-F5 (suggestion: cost).** `test_walk_cost_counts_receipt_loads` prints `LOADS for walk 4->1: 24` for a 3-step walk. Each `load_partition_receipt(g)` re-authenticates the whole chain down to generation 0, so the walk costs O(A²) receipt loads plus digest reads. Every rotation needs a blocked key, so A stays small in practice. If it grows, cache the authenticated receipts for the duration of one walk.

**SA-F6 (suggestion: docs).**
- The `attested_not_landed_recovery` docstring says that a newer `observed_landed` "hides an older `attested_not_landed` (`None`)". The code actually raises `RecoveryChainSuperseded`, because observed_landed is also carried in `legacy_completed_effect_keys`, which the walk checks first (probe SA-F4). Users see the correct behaviour, because `execute` → `_legacy_terminal_replay` replays first.
- The runbook §8a says the retry is refused when a later receipt "carries or re-adjudicates it". A later attested_not_landed re-adjudication actually *recovers* (M3), so that wording is wrong for that case.

**SA-F7 (suggestion: provenance).** `record_recovery` runs before the in-lock checks. A recovery that is then refused or loses a race (SA-F1(b), SA-F2) still leaves `.recovery.<N>.json`, which reads "re-admission authorized in generation N" even though no admission exists. The docstring calls this file the history of what happened. Either document that it records an authorization, not an attempt, or have readers join it to generation N's evidence.

## Correctness-seat conclusions I attacked and could not break
- **Substituting a receipt from another partition or repository:** `load_partition_receipt` binds the identity, container and chain, and the walk binds each walked object to its successor's sealed `RECEIPT_FILENAME` digest (M5).
- **A receipt truncated or missing mid-chain:** routing of the active generation fails before the walk runs. If it does not, the walk raises a typed `LegacyCutoverConflict` ("has no receipt" / "not the receipt its successor sealed"), and verbs.py maps that to `PublicationRecoveryRequired` before any write.
- **Symlinks (reasoned, not probed):** every swept byte is read once and must match the sealed digest, and every receipt is bound to its `target_namespace`/identity. A symlinked file or generation dir therefore only works if its bytes are identical, and then it gains nothing. Any later divergence is refused. No executable falsifier was run for this angle.
- **The sweep boundary `[d, A)`:** this is correct. d-1 legitimately holds the blocked row, and A is checked inside the lock.
- **A different transaction under the same key:** it stays bound through `transaction_id`, and a fresh publish under the same key by another transaction leaves evidence that the sweep refuses (fail-closed).
- **The 1296 test deletion:** the deleted test's no-write-on-refusal property is still covered by `_assert_refused_without_writes` in the new tests.

## Verdict
- **No blocking candidates.**
- **SA-F1 is worth fixing before merge:** a one-line conditional on the three fields removes both mixed-version conflict directions.
- **SA-F2 is a pre-existing gap and should become its own issue.**


## Asks
1. **Mixed-version recovery-record conflict (S1 / SA-F1).** Reproduced in both directions within the same generation: the old record followed by a new retry, and the new record followed by an old retry. Either case raises a typed `PublishTransactionConflict` before any owner write or provider call, and the key waits for an unrelated rotation or for the record to be removed. Fix: have `record_recovery` accept a record that matches on the old fields (a subset match), or emit the three new fields only when an intervening rotation exists. Also make the conflict handoff name the record path.
2. **SA-F2: the owner is written before `admit_next`'s blocked-generation check, so the disposition is consumed with zero provider calls.** This predates this PR. The president notes that agent-harness#1551's `_restore_owner_bytes` closes it. Verify once agent-harness#1551 lands.
3. **Docs (S2 / SA-F6):**
   - The docstring says a newer `observed_landed` makes the walk return `None`; in fact it raises `RecoveryChainSuperseded`.
   - Runbook §8a says a later re-adjudication is refused, but a later `attested_not_landed` recovers.
   - Add a test that drives a real `observed_landed` rotation instead of the monkeypatched carry.
4. **SA-F5.** The walk's cost grows quadratically with the number of generations it crosses. Add a runbook note if partitions rotate often.
5. **SA-F7.** `.recovery.<N>.json` is written before the under-lock checks. Document it as an authorization record, not as proof that the key was re-admitted.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-13T02:46:24Z:

````markdown
Disposition (docs/registers/deferred-findings.md):
- **Ask 2 (SA-F2): STILL-LIVE** on main. It is expected to be closed by agent-harness#1551; re-check once that lands.
- **Ask 1: STILL-LIVE.** This is a mixed-version skew introduced with this PR's record fields. It is a typed refusal before any write, and it is not a floor-class authority path.
- **Asks 3–5: PARKED** (docs and cost).

The issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-13T16:07:17Z:

````markdown
**Ask 2 (SA-F2) is resolved.** The code fix came in agent-harness#1551. agent-harness#1593, merged as 6ec65342, adds the recovery-path regression test (`test_recovery_path_epoch_block_restores_owner`). Ask 1, the mixed-version recovery-record conflict, is still STILL-LIVE, and asks 3–5 remain PARKED, so this issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-14T06:54:08Z:

````markdown
**Ask 1 resolved by agent-harness#1627** (merged). When no rotation intervened, the recovery record is byte-identical to the agent-harness#1296 format again. New readers accept the no-rotation shape from agent-harness#1550, and conflicts name the record path. One combination still conflicts: a record written by #1627 and then retried on the unreleased #1550 runtime. That case is documented in runbook §8a. The remaining asks (3–5) are still PARKED, so this issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

<!-- row:R-028 -->
### R-028 — FABPUB: deferred board findings from agent-harness#1551 (post-section gap, NFS doc, restore edge cases)
- **source:** Consiliency/agent-harness#1578
- **origin:** FABPUB, advisor-board ruling on agent-harness#1551 (agent-harness#1314, agent-harness#1313, agent-harness#1311), merge authorized at `d2b363d5`
- **original ruling:** "None names an acceptance item, declared contract or existing test it breaks." — president, F012; F001: "SA-F4 DEFERRED — `KeyboardInterrupt` in `admit_next` skips the restore, identical on main (unsealed owner, promoted on retry, 0 provider calls), fail-closed"
- **bound criteria:** none
- **current-main check:** 8db24571: ask 2 — the NFS paragraph is unchanged (docs/fabpub-pre-admission-ambiguity.md:95-98); ask 3 — the restore still runs only under `except Exception` (phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py:903); ask 4 — a failed restore is still swallowed by `except OSError: pass` (verbs.py:910-912); ask 6b — `_owner_writer_alive` still catches only `FileNotFoundError` (verbs.py:253); ask 6c — the only fork without exec in phase-loop-runtime/src is phase-loop-runtime/src/phase_loop_runtime/lease_supervisor.py:351; asks 6a and 6d not re-checked beyond the unchanged section; asks 1 and 5 resolved by agent-harness#1593 (`6ec65342`) and agent-harness#1626 (`7ae99e04`, `retry_after_inflight_publication`)
- **safety floor:** path containment (ask 6b) and concurrency on an evidence path (ask 6c); asks 2, 3, 4, 6a and 6d are not floor-class (docs, an availability-only unsealed owner with zero provider calls, a log line, an fsync failure and plan wording); ask 6b is not a containment defect: the probe opens with `O_NOFOLLOW` (verbs.py:251), so a symlinked owner is refused, never followed; callers negative for 6c: phase-loop-runtime/src/phase_loop_runtime/lease_supervisor.py:351 is the only fork without exec in phase-loop-runtime/src, and it forks the executor before any publication exists in that process; the liveness descriptor is opened `O_CLOEXEC` (verbs.py:224), so no production publish path inherits it
- **disposition:** PARKED — President-DEFERRED docs and fail-closed edge cases (asks 2, 3, 4, 6a–6d); asks 1 and 5 were resolved by agent-harness#1593 and agent-harness#1626.
- **promotion:** none
- **finding:**

Issue body:

````markdown
These are the remaining deferred findings from the advisor-board ruling on Consiliency/agent-harness#1551 (agent-harness#1314/#1313/#1311). The president deferred all of them and authorized the merge at `d2b363d5`. The mixed-version promotion finding (SA-F1) is filed separately as agent-harness#1577. These are filed under the agent-harness#442 rule.

## Verbatim president rulings (deferred findings with content)
```
FINDING F001: DEFERRED — Grok seat ERRORed before reviewing (agent-harness#1460); its adversarial slot is covered by the repository-grounded stand-in, whose 30 probes I re-ran serially on head (30 passed). Stand-in rulings: SA-F1 DEFERRED — an old-runtime prober promoting a live head writer, reproduces (P5 main re-run: 1 provider call, record ambiguous, owner unsealed; there the promotion landed on an already in-flight record), and the section-to-`record_intent` gap variant, where the writer proceeds because `record_intent` (evidence.py:415-418) returns the existing ambiguous record without refusing, is shown by the stand-in's P1 main control; both shapes are main-identical and is exactly the behaviour the PR declares for an older reader; the ah#789 contract (typed refusal before owner mutation on an incompatible schema, no unreadable field or file, C-keep) is untouched, the probe never turns a refusal into a proceed, so no declared contract, acceptance item or existing test breaks; the post-`record_intent` in-flight guard is a `_fresh_publish` change outside #1314/#1313/#1311 that needs its own design and board, file it as a follow-up with the doc sentence that #1313 protection holds only once every writer is upgraded; SA-F2 DEFERRED — the NFS paragraph is inaccurate (`_require_lock_held` is granted under per-process POSIX emulation, so publish raises `RuntimeError` and never runs on NFS) but is explanatory text, not a declared contract, and ah#789 mixed-version is about runtime versions, not filesystems; doc fix follow-up; SA-F3 DEFERRED — fork-without-exec keeps a descriptor alive, availability only, no reachable fork-without-exec during a publish; wording follow-up; SA-F4 DEFERRED — `KeyboardInterrupt` in `admit_next` skips the restore, identical on main (unsealed owner, promoted on retry, 0 provider calls), fail-closed; SA-F5 DEFERRED — `AdapterStartOwnerLive` surfaces as the `repair_fabpub_authority` handoff, declared Lane C follow-up, live attempt still completes; SA-F6 DEFERRED — a failed restore is swallowed by `except OSError: pass`, leaving today's fail-closed unsealed owner while the original exception still propagates; a log line is a suggestion.
FINDING F010: DEFERRED — the post-section/pre-provider gap (e.g. generation lease superseded before `record_intent`) is outside the three issues' acceptance, exists identically on main, is declared by the PR under "Not changed / follow-ups", and fails closed (zero provider calls, never two). Follow-up issue, not a block.
FINDING F012: DEFERRED — S1 (file the post-section gap; restoring before `record_intent` is safe, after it needs design) DEFERRED, follow-up issue; S2 (map `AdapterStartOwnerLive` to a retry next step in `publishing.py`) DEFERRED, declared Lane C follow-up; S3 (directory-fsync failure after `os.replace` inside `append_adapter_start_owner` is outside the restore try) DEFERRED, main-identical, fail-closed; S4 (`_owner_writer_alive` only catches `FileNotFoundError`, so `ELOOP`/`EACCES` raise `OSError`) DEFERRED, fail-closed on an already-invalid state the inventories refuse; S5 (NFS doc incomplete) DEFERRED, folded into the SA-F2 doc fix; S6 (plan says the descriptor is closed on the restore path, code closes it in `_fresh_publish`'s `finally` when a holder is supplied) DEFERRED, functionally equivalent since the inode is already replaced or unlinked, plan wording; S7 (fork-without-exec inherits the descriptor) DEFERRED, availability only, same as SA-F3. None names an acceptance item, declared contract or existing test it breaks.
```

## Verbatim: Claude seat, known gap and suggestions
## Known gap: a failure after the section returns, before the provider call

**Ruling: follow-up, not blocking.**
- **Not in scope.** agent-harness#1314 is scoped to refusals inside `admit_next` that run
  after `append_adapter_start_owner`, and that acceptance is met. The gap covers
  `advance("ADMISSION_DURABLE")`, `record_intent`, `_crash_at` and
  `validate_adapter_start_owner`'s `_authorize`. It exists identically on main.
- **No regression.** This PR does not make the gap worse. The descriptor is closed in
  `_fresh_publish`'s `finally`, so after such a failure the owner reads dead and is promoted
  exactly as today.
- **Follow-up wanted.** A generation-lease supersession landing between the section and
  `record_intent` / `validate_adapter_start_owner` is the realistic trigger. It
  permanently blocks the partition with no provider call ever made, so it deserves its
  own issue.

## Suggestions (non-blocking)

- S1: File the post-section/pre-provider gap above as its own issue. Restoring before
  `record_intent` is safe for the same reason the in-section restore is. After
  `record_intent`, an `IN_FLIGHT` record would remain with no owner, so that part needs its
  own design.
- S2: Map `AdapterStartOwnerLive` to a "retry" next step in `publishing.py` (Lane C, already
  noted in the PR). Today it surfaces as a plain `PermissionError`. That is no regression,
  because the live writer still completes.
- S3: A `_owner_atomic_write` failure *after* `os.replace` (the directory fsync) happens
  inside `append_adapter_start_owner`, outside the new `try`. It still leaves an unlocked
  unsealed owner, as on main. It could be folded into the restore scope.
- S4: `_owner_writer_alive` catches only `FileNotFoundError`. A symlinked owner path
  (`O_NOFOLLOW` gives `ELOOP`) or `EACCES` now raises `OSError` instead of promoting. That
  is fail-closed on an already-invalid state, since `_tree_file_inventory` refuses
  symlinks. Nit.
- S5: NFS documentation is incomplete. With `flock` emulated as per-process POSIX locks,
  closing *any* descriptor on the file in the writer process drops the lock, for example
  `read_adapter_start_owner`'s `read_text` in `validate_adapter_start_owner`. The writer
  therefore reads dead to every host, not only to its own process. This is still today's
  behaviour, so it is safe.
- S6: The plan says the descriptor is "also closed on the #1314 restore path". In the code,
  when a holder is supplied, `_fresh_publish`'s `finally` closes it. That is functionally
  equivalent, since the inode is already replaced or unlinked. It is a plan/code wording
  mismatch.
- S7: A `fork()` without `exec` (for example a multiprocessing `fork` pool started
  mid-attempt) inherits the open file description and keeps the owner "alive" after the
  parent exits. That costs availability only.


## Verbatim: stand-in findings SA-F2 to SA-F6
**SA-F2 (suggestion; doc accuracy).** The NFS paragraph in `docs/fabpub-pre-admission-ambiguity.md` and the PR body describes a situation that cannot arise.
- Evidence, from `tests/test_adv_1551_probes.py::test_nfs_style_posix_locks_cannot_publish_at_all`, run on head and on the main control (`fcntl.flock` emulated with POSIX `lockf`, as Linux NFS does): the result is `RuntimeError: admit_next(lock_held=True) called without admissions.lock held`, from `_require_lock_held`, which a same-process POSIX lock never blocks. That is 0 provider calls on both trees. Head leaves **no owner**; main leaves an unsealed owner, so this PR is strictly better here.
- So FABPUB publish does not run on NFS-style locking at all.
- If it did, the paragraph would also understate the problem. Under POSIX semantics the writer's own `read_adapter_start_owner` (in `validate_adapter_start_owner`, before the provider call) closes an fd on the owner file and drops the liveness lock for **every** process, not only for in-process probes.
- Fix: replace the paragraph with "requires local `flock` semantics; NFS is unsupported (admission refuses)".

**SA-F3 (suggestion).** A descriptor inherited through fork-without-exec keeps a dead writer "alive".
- Evidence, from `tests/test_adv_1551_probes.py::test_fork_inherited_owner_lock_reads_alive_after_parent_death`: the writer takes the lock via `_hold_owner_liveness`, forks a helper without exec, and is SIGKILLed. Output: `probe alive=True`, next publish `AdapterStartOwnerLive`, and `alive=False` only after the helper exits.
- Reachability: I grepped `src/` for `os.fork`, `pass_fds` and `close_fds=False`. The only fork-without-exec is `lease_supervisor.py:351`, which forks before any publish exists, so no current publish path can reach this. `O_CLOEXEC` plus Popen's `close_fds=True` covers `gh`/git. The cost is availability only; it never causes a second effect.
- Fix: wording only. "The kernel releases the lock when the writer process dies" should become "when every process sharing the descriptor exits; do not fork without exec while an attempt is in flight".

**SA-F4 (suggestion).** A `BaseException` raised inside the section gets no restore and strands the partition.
- Evidence, from `tests/test_adv_1551_probes.py::test_keyboard_interrupt_in_admit_next_strands_partition`: `KeyboardInterrupt` in `admit_next` leaves `owner sealed=False alive=False`. The retry gets `unsealed adapter-start owner blocks fresh provider effect`, states `['provider_call_in_flight','outcome_ambiguous_blocked']`, and **0 provider calls**: permanent ambiguity with no effect. Running the same test on the main control gives an identical result (unsealed owner, promotion on retry, 0 calls), so this is not a regression.
- The doc says "if anything refuses after the owner write". SIGINT or `SystemExit` in-process is recoverable rather than a crash.
- Fix: restore on `BaseException` other than `PublishCrashInjected`, or state the exclusion explicitly.

**SA-F5 (suggestion).** Retryable contention reaches callers as human handoffs.
- `AdapterStartOwnerLive` is a `PermissionError`, which `publishing.py:1579-1588` maps to `repository_publication_authority_refused` / `next_step=repair_fabpub_authority`. The PR names this as a follow-up.
- Separately, a same-key racer that arrives after the live attempt has advanced its transaction gets `PublicationRecoveryRequired` ("… is ADAPTER_STARTED for the current head …"; seen in the `tests/test_adv_1551_probes.py::test_stress_processes_fork` logs), which maps to the rotation-recovery handoff. A plain retry replays the terminal and is accepted, as in P2. This part is pre-existing.
- A caller that follows either handoff does the wrong thing.

**SA-F6 (suggestion, minor; by inspection, `verbs.py` `_owner_and_admission_under_one_lock` `except OSError: pass`).** `_restore_owner_bytes` failures are swallowed with a bare `pass`. When it fails, this attempt's unsealed owner remains (fail-closed, same as main), but the re-raised error does not say so. Attach a note or log line so the operator knows the next attempt will promote it.


## Asks
1. **Gap between the section and the provider call.** A failure after `_owner_and_admission_under_one_lock` returns but before the provider call strands the partition with zero provider calls. One trigger is the writer's generation lease being superseded before `record_intent`. Restoring the owner before `record_intent` is safe; restoring it after `record_intent` needs a design.
2. **SA-F2.** The NFS paragraph in `docs/fabpub-pre-admission-ambiguity.md` describes something that can't happen: `_require_lock_held` already refuses, so publishing can't run on NFS at all. Replace it with "NFS unsupported".
3. **SA-F4.** A `KeyboardInterrupt` or other `BaseException` raised inside the section skips the restore.
4. **SA-F6.** A failed restore is swallowed, so the raised error should say an unsealed owner was left behind.
5. **SA-F5 / S2.** Map `AdapterStartOwnerLive` to a "retry shortly, another publication is in progress" handoff in `publishing.py`. This belongs with the typed-handoff follow-up.
6. **S3–S7 / SA-F3.**
   - Directory-fsync failure after `os.replace`.
   - A symlinked owner path.
   - A fork without exec keeping the lock alive.
   - Plan/code wording on where the descriptor is closed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-13T02:53:20Z:

````markdown
Disposition (docs/registers/deferred-findings.md):
- **Ask 1 (the gap between the section and the provider call): STILL-LIVE.** It is reachable on main, and it fails closed with zero provider calls.
- **Asks 2–6: PARKED.** These are docs and edge-case suggestions that fail closed.

The issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-13T16:07:15Z:

````markdown
**Ask 1 is resolved by agent-harness#1593**, merged as 6ec65342. The maintainer chose option (i): restore the owner only when `advance("ADMISSION_DURABLE")` fails while the checkpoint is still `COMMITTED_HEAD_RESOLVED`. Every other failure in that window is documented as fail-closed and recoverable by rotation, and results now report `provider_call_made`. Option (ii), moving the intent into the section, was declined. Asks 2–6 remain PARKED, so this issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-14T08:19:12Z:

````markdown
**Ask 5 is resolved by agent-harness#1626** (merged). `AdapterStartOwnerLive`/`AdapterStartOwnerContended` now get `retry_after_inflight_publication`. The remaining asks stay PARKED.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

<!-- row:R-029 -->
### R-029 — FABPUB: deferred board findings from agent-harness#1593 (guard edge cases, lease-refusal handoff, doc precision)
- **source:** Consiliency/agent-harness#1594
- **origin:** FABPUB, advisor-board rulings on agent-harness#1593 (fixes agent-harness#1577), round 2 authorized the merge at `d9b0d6f7`
- **original ruling:** "SA-F4 DEFERRED — owner removed after record_intent has no production path, fail-closed, 0 calls, strand main-identical; typed raise / _replay shape as follow-up" — president, round 1; round 2: "FINDING F016: DEFERRED — non-blocking wording"
- **bound criteria:** none
- **current-main check:** 8db24571: ask 3 — `_provider_entry_guard` still returns the stored row for a mismatched or missing owner rather than raising typed (phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py:959-965); ask 5a — one "`attested_not_landed` by construction" phrase remains (docs/fabpub-partition-rotation-runbook.md:476); ask 6 — "right before the provider call" remains at CHANGELOG.md:182 and docs/fabpub-pre-admission-ambiguity.md:109, and the old section comment at phase-loop-runtime/tests/test_fabpub_owner_section_1314_1313_1311.py:353-354; asks 4 and 5b carried from the prior triage; asks 1 and 2 resolved by agent-harness#1626 (`7ae99e04`, `retry_once_before_partition_rotation`) and agent-harness#1633 (`cd67eb28`)
- **safety floor:** not floor-class — ask 3 concerns the guard on a concurrency path, but every non-`None` return refuses provider entry (verbs.py:959-965), so only the result's label and shape are at issue, not the provider-entry decision; ask 4 is an availability-only parked checkpoint, main-identical; asks 5a, 5b and 6 are wording, a test comment and test parametrization
- **disposition:** PARKED — President-DEFERRED guard-result shape, a parked checkpoint and wording (asks 3, 4, 5a leftover phrase, 5b, 6); asks 1 and 2 were resolved by agent-harness#1626 and agent-harness#1633.
- **promotion:** none
- **finding:**

Issue body:

````markdown
These are the deferred findings from the advisor-board rulings on Consiliency/agent-harness#1593, which fixes agent-harness#1577. In round 1 the board required changes, and in round 2 it authorized the merge at `d9b0d6f7`. The items below are non-blocking. They are filed under the agent-harness#442 rule. The window that remains open after the guard is tracked separately in agent-harness#1591.

## Verbatim president rulings with content

Round 1 (F001 carries the rulings on the stand-in's findings):
```
FINDING F001: BLOCKING — Grok seat ERRORed before reviewing (agent-harness#1460); its adversarial slot is covered by the repository-grounded stand-in, whose Q2 I re-ran on head (real pre-#1313 prober process, both park points: 1 provider call, provider_call_made=True, checkpoint ADAPTER_STARTED). Stand-in rulings: SA-F1 BLOCKING — a promotion landing after `_provider_entry_guard` releases `admissions.lock` and before `adapter.execute` (inside `advance("ADAPTER_STARTED")`, request finalization or the lease acquisition) still gets one provider call, which falsifies the PR's declared contract sentence ("never calls the provider for a key whose record is no longer this attempt's in-flight record"), the mixed-version table row "window (b) ... before the provider call | Closed", the doc bullet "after the owner section and before the provider call", runbook 8a and CHANGELOG "promotion during the provider call is not covered", and leaves the interval outside agent-harness#1591's scope; the code follows the ratified guard placement, the residual is irreducible without holding the lock across a network call, so the required change is to re-scope the declared contract and window boundary at the guard's lock release, scope #1591 to match, and pin the residual with a test (no guard relocation required); SA-F2 DEFERRED — a refused lease needs one retry before rotation, nothing strands, main under DRAINING is no better; doc line suggested; SA-F3 DEFERRED — release failure after a definite result records ambiguity per design item 3 (row still in flight), main-identical, legacy lease path, honestly labelled provider_call_made=True; follow-up; SA-F4 DEFERRED — owner removed after record_intent has no production path, fail-closed, 0 calls, strand main-identical; typed raise / _replay shape as follow-up; SA-F5 DEFERRED — "of another key" doc precision, fold into the wording round; SA-F6 DEFERRED — negative result on the restore's four conditions, concur; SA-F7 DEFERRED — negative result, no foreign terminal can mask this attempt's ambiguity, concur; SA-F8 DEFERRED — provider_call_made values verified across paths, concur.
```

Round 2:
```
FINDING F001: DEFERRED — Grok seat ERRORed (agent-harness#1460), no content. Stand-in (adversarial + red-team) ruled here: its round-1 SA-F1 dissent is withdrawn and it AGREEs; behaviour unchanged (Q2 at both park points and the codex falsifier give 1 call, `provider_call_made=True`), its M1/M2/M3 mutations show the pin catches both a silent narrowing and a mislabel. N1 (looser "right before" phrasings) DEFERRED, qualified in place; N2 (lease-acquisition park) DEFERRED, optional parametrization, the ruling required only the projection park and the during-call pin bounds the other end; N3 (plan mutation-table rows) DEFERRED, optional.
FINDING F016: DEFERRED — non-blocking wording: the doc heading "A guard right before the provider call" and the CHANGELOG "Right before the provider call" are each followed in the same bullet/paragraph by the in-lock condition and the lock-release-through-call residual, so neither re-creates the over-claim; the test-file section comment (lines 353-354) is the old phrasing but a test comment, not a declared surface — adopt the seat's rewording in a follow-up.
```

## Verbatim: Claude seat round-1 suggestions
## Suggestions (non-blocking)

- **S1, wording of window (a) and (b), probe B.** The PR table, the CHANGELOG and the doc say window (b) is "Closed" and that only "promotion during the provider call" remains. In fact the open window starts when `_provider_entry_guard` releases `admissions.lock`: it spans `advance("ADAPTER_STARTED")`, `make_request` and the lease acquisition. The declared contract ("never calls the provider for a key whose record is no longer this attempt's in-flight record") therefore holds only up to the guard. I am not ruling this blocking: the gap is a check-then-act race of the same class D1 already defers, and it is no worse than main. Fixes:
  - Reword to "from the guard's lock release through the provider call" and scope agent-harness#1591 to match.
  - Optionally move the guard to immediately before `adapter.execute`, after `ADAPTER_STARTED` and the lease acquisition, releasing the lease on refusal. That shrinks the gap to the call itself, and a refusal at `ADAPTER_STARTED` is still an admitted, rotation-recoverable state.
- **S2.** For a terminal stored row in the guard's mismatch branch, return the `_replay` shape. For the guard, treat `current_owner is None` the same as the missing-row case (raise typed) rather than returning an in-flight row labelled ambiguous.
- **S3.** If `release_lease` raises after `adapter.execute` returned a terminal, the `except` still records `outcome_ambiguous_blocked` although the adapter's terminal is in hand. This is main-identical and occurs only on the legacy-builder lease path. Recording `evidence.terminal_state` when `result`/`evidence` are bound would complete the "never invent" rule.
- **S4.** When a non-observed terminal (`no_effect_terminal_proven`) is returned after a post-provider failure, the checkpoint stays `ADAPTER_STARTED` (probe C). It never reaches `TERMINAL_SEALED`, because the SDK closeout seals only on `accepted`. This is main-identical. A best-effort `advance("TERMINAL_SEALED")` in the terminal-durable branch, or a doc line, would avoid a parked checkpoint.
- **S5, doc.** The doc says "`attested_not_landed` by construction" for pre-provider failures. The resulting ambiguous row (`unsealed-adapter-start-owner`) cannot be told apart from a mid-provider crash. Operators should be pointed at the original error, or at `provider_call_made` where present, rather than at the row.

No blocking defects: no acceptance item of agent-harness#1577, agent-harness#1574 ask 1, agent-harness#1578 ask 1 (option i) or agent-harness#1576 ask 2 is unmet, no declared ah#789 contract is broken, and no existing test regresses.


## Asks
1. **SA-F2, the handoff after a refused lease.** After a lease refusal, a direct rotation is refused with "intents without a terminal". One retry first turns the row ambiguous. The handoff should tell the operator to retry once before rotating.
2. **SA-F3 / Claude S3, a lease release that fails after a definite result.** The broker records ambiguity and throws away the adapter's known terminal. Behaviour on main is identical, and this happens only on the legacy lease path.
3. **SA-F4 / Claude S2, the guard's edge cases.** When the owner no longer matches but the row is still in flight, the guard should raise the typed `PermissionError` and should not label the result an ambiguous block. A terminal row should be returned in the `_replay` shape, and a missing owner should be a typed refusal.
4. **Claude S4.** After `no_effect_terminal_proven` and then a seal failure, the checkpoint stays at `ADAPTER_STARTED`. Main behaves the same way.
5. **Claude S5 / SA-F5, doc precision.**
   - Pre-provider failures are not "`attested_not_landed` by construction". The resulting ambiguous row looks the same as one left by a crash during the call, so operators need the original error to tell them apart.
   - After a seal failure, only a publish of a *different* key seals the leftover owner.
6. **Round-2 nits.**
   - The wording "right before the provider call" in the CHANGELOG and in one doc heading.
   - The stale section comment around line 353 of `test_fabpub_owner_section_1314_1313_1311.py`.
   - A lease-acquisition parametrization of the boundary pin.
   - The missing rows in the plan's mutation table.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-13T15:33:28Z:

````markdown
Disposition (docs/registers/deferred-findings.md): **PARKED** for all asks. The board classed each one DEFERRED. Each fails closed with no second provider call, and each either behaves identically on main or is docs-only. The safety-relevant residual is tracked separately in agent-harness#1591. This issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

Comment by ViperJuice at 2026-10-14T08:19:13Z:

````markdown
**Ask 1 (SA-F2) is resolved by agent-harness#1626** (merged). A refusal after admission but before the provider call now gets `retry_once_before_partition_rotation`. The remaining asks stay PARKED.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

<!-- row:R-030 -->
### R-030 — FABPUB: deferred board findings from agent-harness#1627 (recovery-record compat follow-ups)
- **source:** Consiliency/agent-harness#1629
- **origin:** FABPUB, advisor-board ruling on agent-harness#1627 (agent-harness#1576 ask 1), merge authorized at `b00c3585`
- **original ruling:** "SA-F4 DEFERRED — the residual (this record → 1550 retry) is a typed refusal before any owner or provider call, no tombstone, cleared by a current-runtime retry, reproduced by me with the real 1550 runtime; 1550 was never tagged and the runbook §8a paragraph documents the remedy; acceptable." — president, F001; SA-F6: "suggestion only"
- **bound criteria:** none
- **current-main check:** 8db24571: ask 1 — runbook §8a documents the agent-harness#1550 residual (docs/fabpub-partition-rotation-runbook.md:531-535); ask 3 — the handoff test still raises a faked `RecoveryRecordConflict` (phase-loop-runtime/tests/test_fabpub_recovery_record_compat_1576.py:359); ask 4 — the record path still reaches only the in-process human handoff; ask 5 resolved by agent-harness#1627 (runbook:539); ask 2 is STILL-LIVE and is not part of this row
- **safety floor:** not floor-class — ask 1 is a typed refusal before any owner or provider call on a runtime that was never released; asks 3 and 4 are test coverage and error-surface visibility
- **disposition:** PARKED — Asks 1, 3 and 4 only; ask 2 is STILL-LIVE outside this row, so agent-harness#1629 stays open until it is fixed, and ask 5 was resolved by agent-harness#1627.
- **promotion:** none
- **finding:**

Issue body:

````markdown
These are the deferred findings from the advisor-board ruling on Consiliency/agent-harness#1627, which addresses agent-harness#1576 ask 1. The board authorized the merge at `b00c3585`, and every finding below was deferred as non-blocking. They are filed under the agent-harness#442 rule.

## Verbatim president rulings
```
FINDING F001: DEFERRED — Grok seat ERRORed (agent-harness#1460); lens covered by the Opus stand-in whose probes I re-ran (9 passed plus 3 residual). Stand-in rulings: SA-F1 DEFERRED — negative result; 27 forged no-rotation/walk-stripped shapes all refuse `RecoveryRecordConflict`, normalization only equates values fully implied by `generation`, `cutover_id` stays in the core, forgery surface unchanged from base. SA-F2 DEFERRED — negative result; record-then-rotation with r1296/r1550/head retrying in turn totals exactly 1 call, r1296 refuses `PublicationRecoveryRequired` without writing; the base→r1296 control reproduces the defect and the PR fixes it. SA-F3 DEFERRED — the pre-#1313 live-owner promotion hazard (an a1c3937e writer in its provider call probed by a newer runtime leaves the key `outcome_ambiguous_blocked` after a real call) is pre-existing: the control shows base and head identical, and `_block_unsealed_owner` runs before `_recovery_authority`/`record_recovery` on both; this PR neither introduces nor widens it; a one-sentence runbook caveat (do not retry on a pre-#1313 runtime while any attempt for the key may be live) is a welcome follow-up, not a condition of merge. SA-F4 DEFERRED — the residual (this record → 1550 retry) is a typed refusal before any owner or provider call, no tombstone, cleared by a current-runtime retry, reproduced by me with the real 1550 runtime; 1550 was never tagged and the runbook §8a paragraph documents the remedy; acceptable. SA-F5 DEFERRED — no reader of the three fields exists in `src/` and at-most-once rests on the evidence replay, the `[d, A)` sweep and the in-lock section, none of which read the record. SA-F6 DEFERRED — all three `except PublishTransactionConflict` sites still catch the subclass, no name/type dispatch anywhere; the handoff test faking the error through a monkeypatched `publish_from_worktree` is a coverage gap (an end-to-end real-conflict test) but the propagation path is exercised by my residual and the stand-in's b-probes; suggestion only.
FINDING F024: DEFERRED — three non-blocking notes: record path reaches only the in-process human handoff (message still names the path; open question 3), record written before in-lock checks is SA-F7/ask 5 and out of scope here, the 1310 test edit still pins `cutover_id` and `generation`; none names a contract or test this PR breaks.
```

## Asks
1. **Leftover conflict with the agent-harness#1550 runtime.** A record written by this PR, followed by a retry on the agent-harness#1550 runtime (never released), is refused before any write. A retry on a current runtime then recovers once. Runbook §8a documents this. No code change, unless an agent-harness#1550 runtime actually ships.
2. **SA-F3, which predates this PR.** A retry on the released agent-harness#1296 runtime has no live-owner protection (agent-harness#1313). If it races a live attempt, it can leave the key ambiguous even after a real provider call. Add a runbook warning: don't retry on a 1296 runtime while another attempt may be live.
3. **SA-F6.** The handoff test fakes `RecoveryRecordConflict`. Add an end-to-end test that produces a real record conflict.
4. **Record path visibility.** Only the in-process human handoff surfaces the record path. Other callers get it only in the exception message.
5. **The recovery record is still written before the locked checks** (SA-F7 from agent-harness#1550, ask 5 of agent-harness#1576). Document it as an authorization record.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-14T06:27:13Z:

````markdown
Disposition (docs/registers/deferred-findings.md):
- **Ask 2: STILL-LIVE.** It is reachable today on a released 1296 runtime, though it fails closed with at most one provider call.
- **Asks 1, 3, 4 and 5: PARKED.**

This issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

<!-- row:R-031 -->
### R-031 — FABPUB: deferred board findings from agent-harness#1626 (refusal names the pre-lock owner; incomplete blocking-key list; wording nits)
- **source:** Consiliency/agent-harness#1635
- **origin:** FABPUB, advisor-board rulings on agent-harness#1626 (typed publication handoffs), round 2 authorized the merge at `3b37a819`
- **original ruling:** "SA-F1 DEFERRED — reproduced (handoff names owner A, store promoted B) but it is PR deviation 5, a declared and documented limitation" — president, round 1; round 2: "S1 CHANGELOG DEFERRED, S2 helper DEFERRED, S3 wording/pickle DEFERRED, S4 SA-F1/SA-F2 DEFERRED as ruled in round 1"
- **bound criteria:** none
- **current-main check:** 8db24571: ask 1 — `_block_unsealed_owner` still returns `bool` (phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py:636); ask 2 — `blocking_effect_keys` still lists only the promoted owner's key (phase-loop-runtime/src/phase_loop_runtime/publishing.py:1734); ask 3 — `_provider_entry_refusal` still builds the dual type unconditionally (verbs.py:405); ask 4 — `rebuild_broker_client_and_retry` unchanged (publishing.py:1539); ask 5 resolved by agent-harness#1633 (`cd67eb28`); asks 3d and 3e may be touched by the in-flight fix for agent-harness#1628
- **safety floor:** concurrency or TOCTOU on an evidence path (asks 1 and 2: a refusal built around a promotion race); asks 3 and 4 are wording, a helper self-guard, pickling and resume text, not floor-class; callers negative: phase-loop-runtime/src/phase_loop_runtime/publishing.py:1487 and :1517-1534 are the only readers of `blocking_effect_keys` and of the named owner, and they only build handoff text; the rotation's authority decision reads the sealed predecessor ledger and refuses any attestation whose effect set differs from it (phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py:4938)
- **disposition:** PARKED — President-DEFERRED refusal-text accuracy and nits (asks 1–4); ask 5 was resolved by agent-harness#1633.
- **promotion:** none
- **finding:**

Issue body:

````markdown
Deferred findings from the advisor-board rulings on Consiliency/agent-harness#1626 (typed FABPUB publication handoffs). Round 1 required changes, and round 2 authorized the merge at `3b37a819`. These items are non-blocking. They are filed under the agent-harness#442 rule.

## Verbatim president rulings with content
Round 1 (F001 carries the stand-in rulings):
```
FINDING F001: DEFERRED — Grok seat ERRORed before reviewing (agent-harness#1460, host defect); nothing to rule on. Stand-in rulings (Opus, adversarial + red-team): SA-F1 DEFERRED — reproduced (handoff names owner A, store promoted B) but it is PR deviation 5, a declared and documented limitation; the window is A's remaining run plus B's whole attempt; a wrong-key attestation is refused by the rotation's exact-set check (`set(effects) != set(ledger.blocked)` lists missing/extra keys), so the operator is redirected, not misled into a wrong disposition; no ask requires naming the promoted owner. File the cheap fix (have `_block_unsealed_owner` surface the owner it promoted, e.g. via an out-list to keep the `bool` seam) as a follow-up. SA-F2 DEFERRED — same fail-closed containment; the union with replayed ambiguous keys (as `_epoch_blocked_refusal` already does) is a follow-up. SA-F3 DEFERRED — reproduced, but it names no broken declared contract: the plan's "OSError keeps the environment handoff" was never true of a `PermissionError` on main (main control: `repair_fabpub_authority`), so for EACCES / `EvidenceStoreIncompatible` the change is authority-repair -> retry-once, both pre-provider and write-free; the president probe shows a persistent fault converges to `repair_fabpub_authority` on the very next attempt with zero provider calls, so the "could cycle retry/rotation" harm does not occur. Recommended, not required: make the plan's "Not changed" bullet precise ("a non-permission `OSError`") and consider excluding errno-bearing `PermissionError`/`*StoreIncompatible` from the wrap in a follow-up. SA-F4/SA-F5/SA-F6: no finding; concur.
```

Round 2:
```
FINDING F001: DEFERRED — Grok seat ERRORed before reviewing (agent-harness#1460, host defect); nothing to rule on. Stand-in rulings (Opus, adversarial + red-team, AGREE): SA-F3 requirement MET — re-run confirms eacces and store_incompatible pass on 3b37a819 with the same object, errno and filename reaching the route; SA-F3b DEFERRED — fails only via a direct unit call to `_provider_entry_refusal` that no production site makes (helper self-guard nit above); SA-F4/SA-F5 pass, concur; the three real-fault r2 falsifiers (DRAINING, chmod EACCES, receipt removed) pass under my re-run, concur; A1 (no other `PermissionError` can be wrapped: two `WriterGenerationBlocked` subclasses only) independently confirmed; A2 dual class sound, concur; A3 no retry-once refusal dropped, concur; A4 mapping-order DEFERRED (nit ruling above); S1 CHANGELOG DEFERRED, S2 helper DEFERRED, S3 wording/pickle DEFERRED, S4 SA-F1/SA-F2 DEFERRED as ruled in round 1.
```

## Asks
1. **SA-F1: the unsealed-owner refusal can name the wrong owner.** The refusal is built from the owner read *before* the lock. Under a race, the owner promoted inside the lock can be a different one. Have `_block_unsealed_owner` return the owner it promoted, and build the refusal from that owner. This fails closed at the rotation's exact-set check.
2. **SA-F2: the blocking key list is incomplete.** When an owner is promoted, `blocking_effect_keys` lists only that owner's key, even if other keys in the generation are already ambiguous. Union it with the replayed ambiguous keys, as `_epoch_blocked_refusal` already does. This also fails closed.
3. **Round-2 nits:**
   - The CHANGELOG sentence order reads as if EACCES and incompatible-store errors get retry-once.
   - `_provider_entry_refusal` doesn't guard itself: it always builds the dual type, so it relies on callers to pass only a `WriterGenerationBlocked`.
   - `ProviderEntryRefused` and the dual type can't be pickled or copied.
   - The DRAINING wording describes the lease when it means the evidence store's generation check.
   - Routing depends on mapping order: no row for plain `WriterGenerationBlocked` may come before the `ProviderEntryRefused` row.
   - The `ProviderEntryRefused` docstring says it always has a cause, but the guard raises it without one.
4. **Claude round-1 N3.** The human route builds a fresh client on every call, so `rebuild_broker_client_and_retry` is only reachable with an injected client. Its `resume` text could just say "retry".
5. **agent-harness#1574 ask 3** is still open: an end-to-end test of "retry after rotation replays published".

🤖 Generated with [Claude Code](https://claude.com/claude-code)

````

Comment by ViperJuice at 2026-10-14T07:08:42Z:

````markdown
Disposition (docs/registers/deferred-findings.md): **PARKED**. Each ask fails closed: the rotation's exact-set check names any missing or extra keys. The remaining asks are wording only. This issue stays open.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````
