---
phase_loop_plan_version: 1
phase: RRIMAGE
roadmap: specs/phase-plans-rrimage-v1.md
roadmap_sha256: 004ad222bd60f62f82bd7c7da05eb927762b558934e26b9da7111e02b3ac6c62
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_review_runner_pin.py tests/test_review_runner_recipe.py tests/test_openshell_worker.py"]
---

# RRIMAGE: Review-runner image build and pin

## Context

ai-stack Unit 7 needs a distinct, pinned review-runner image, with platform and pull
evidence, for end-to-end qualification on `ai` (RRIMAGE §1). The Containerfile already pins
its bases, the landlock-exec source, its hashes and the wheel hash. Nothing records what
was built, where it was pushed or that `ai` can pull it. This phase adds a metadata-only pin
record, an offline-checked build recipe, one owner-gated build, push and pull, and the
handoff to ai-stack. It is OWNER-DECISION RR-1 option (c) of the LANEEXEC-v1-errata-2 draft
(agent-harness#2102), run in parallel with v13 LANEEXEC.

Frozen inputs, read before building:

- `plans/artifacts/rrimage-v1-contract.md`: sources (§1), pin record rules P1–P8 and refusal
  codes (§2), recipe (§3), offline tests (§4), grants and live sequence (§5), handoff (§6) and
  non-goals (§7).
- `plans/artifacts/rrimage-v1-pin-record.schema.json`: the `review_runner_pin.v1` schema.
- `phase-loop-runtime/images/review-runner/Containerfile` and
  `phase-loop-runtime/tests/data/landlock-exec/PIN.json` at their current bytes.

**Before any grant.** SL-0, SL-1 and SL-2 need no grant and may start at once.
SL-3 needs G-RR-BUILD, G-RR-REGISTRY, G-RR-PUSH and G-RR-PULL, each given separately. SL-4
needs no further grant; it runs after SL-3.

## Interface Freeze Gates

- [ ] IF-0-RRIMAGE-1 — `review_runner_pin.v1`: the frozen schema packaged byte-equal as
  `contracts/placement/review-runner-pin-v1.schema.json`, and the validator API
  `load_pin_record(path)`, `validate_pin_record(record, repo_root) -> PinVerdict`,
  `assemble_pin_record(build, push_inspect, pull_inspect | None)` and
  `check_pull_evidence(record, pull_inspect)`. They raise only the RRIMAGE §2 closed codes,
  `from None`, and messages never carry record values.
- [ ] IF-0-RRIMAGE-2 — The recipe CLI `review_runner_image.py plan|record|verify-pull`. `plan`
  prints the RRIMAGE §3 commands and runs no subprocess. `record` and `verify-pull` read
  inspection JSON files and call the IF-0-RRIMAGE-1 API.

## Cross-Repo Gates

- [ ] IF-XR-1 (ai-stack Unit 7, consumer) — the handoff of RRIMAGE §6 on
  ViperJuice/ai-stack#504. ai-stack makes the allowlist entry (EXT-RR-ALLOWLIST). No
  agent-harness lane writes ai-stack files or touches `ai` configuration.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/review-runner-image.md`, `CHANGELOG.md`
- evidence paths: `plans/evidence/review-runner/RRIMAGE.md`, `plans/evidence/review-runner/pin-record.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Lane Index & Dependencies

SL-0 — Pin record contract and validator
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4
  Parallel-safe: yes

SL-1 — Reproducible build recipe and audit
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: yes

SL-2 — Operator guide and handoff template
  Depends on: SL-0, SL-1
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-3 — Live build, push and pull (owner-gated)
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — Post-push evidence back-fill, handoff and docs sweep
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

| Lane | Grant needed | May run now |
| --- | --- | --- |
| SL-0, SL-1, SL-2 | none | yes |
| SL-3.1 | G-RR-BUILD | no |
| SL-3.2 | G-RR-REGISTRY, G-RR-PUSH | no |
| SL-3.3 | G-RR-PULL | no |
| SL-4 | none beyond SL-3 | after SL-3 |

## Lanes

### SL-0 — Pin record contract and validator

- **Scope**: Package the frozen schema and implement rules P1–P8 as a pure validator with closed refusal codes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/review_runner_pin.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/review-runner-pin-v1.schema.json`, `phase-loop-runtime/tests/test_review_runner_pin.py`, `phase-loop-runtime/tests/fixtures/review_runner_pin/**`
- **Interfaces provided**: `load_pin_record`, `validate_pin_record`, `assemble_pin_record`, `check_pull_evidence`, `PinVerdict`
- **Interfaces consumed**: `plans/artifacts/rrimage-v1-pin-record.schema.json`, `jsonschema` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_review_runner_pin.py`, `tests/fixtures/review_runner_pin/**` | P1–P8, each with a valid record and one refusing mutation: an extra field, a tag reference, an index media type, a one-byte Containerfile change, a helper path or hash drift, each pull mismatch, a started entrypoint, each credential sentinel, a `pinned` status with null pull; packaged schema equals the artifact; refusal messages exclude record values | `V0` |
| SL-0.2 | impl | SL-0.1 | `review_runner_pin.py`, packaged schema | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 owned files | all SL-0 tests | `V0`; deleting any single rule check fails at least one test |

### SL-1 — Reproducible build recipe and audit

- **Scope**: Close the RRIMAGE §3.5–§3.6 gaps in the Containerfile and add the recipe CLI that prints, but never runs, the build, push and pull commands.
- **Owned files**: `phase-loop-runtime/images/review-runner/Containerfile`, `phase-loop-runtime/scripts/review_runner_image.py`, `phase-loop-runtime/tests/test_review_runner_recipe.py`
- **Interfaces provided**: `review_runner_image.py plan`, `review_runner_image.py record`, `review_runner_image.py verify-pull`
- **Interfaces consumed**: `validate_pin_record`, `assemble_pin_record`, `check_pull_evidence` (SL-0)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_review_runner_recipe.py` | every `FROM` by digest; every `RUN` `--network=none` or hash-pinned; no fetch tool; `PROVENANCE.md` and `LICENSES/**` hash-checked; `plan` prints `git archive`, `--platform linux/amd64`, `SOURCE_DATE_EPOCH`, `--provenance=false`, `rewrite-timestamp=true` and a digest-pinned BuildKit, omits `--push` without `--allow-push`, and makes zero subprocess calls; `record` and `verify-pull` refuse fixture inspections that break P2, P3 or P6 | `V1` |
| SL-1.2 | impl | SL-1.1 | Containerfile, `scripts/review_runner_image.py` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | SL-1 tests and the existing Containerfile tests | `V1`, then `V2` |

### SL-2 — Operator guide and handoff template

- **Scope**: Document the recipe, the grants, the record and its consumers, and draft the handoff with placeholders.
- **Owned files**: `docs/review-runner-image.md`, `phase-loop-runtime/openshell-private-transport.md`, `plans/evidence/review-runner/HANDOFF-ai-stack.template.md`
- **Interfaces provided**: review-runner image documentation, handoff template
- **Interfaces consumed**: `validate_pin_record` (SL-0), `review_runner_image.py plan` (SL-1)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | docs | — | `docs/review-runner-image.md`, the transport doc pointer | recipe, the four grants as separately named gates, rules P1–P8, the stale-record tripwire (P4), the consumers (ACTIVATE, LANEEXEC operator config, ai-stack) | — |
| SL-2.2 | docs | SL-2.1 | handoff template | RRIMAGE §6 fields as placeholders | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | — | `V0`; the docs name no private host or path |

### SL-3 — Live build, push and pull (owner-gated)

- **Scope**: Under the named grants, build twice, push once and pull by digest on `ai`, writing only metadata evidence.
- **Owned files**: `plans/evidence/review-runner/RRIMAGE.md`, `plans/evidence/review-runner/pin-record.json`
- **Interfaces provided**: the `pinned` pin record
- **Interfaces consumed**: `review_runner_image.py plan`, `review_runner_image.py record`, `review_runner_image.py verify-pull` (SL-1), `validate_pin_record` (SL-0)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | evidence | — | `RRIMAGE.md` | G-RR-BUILD recorded; export, helper fetch, two builds, local inspect; `build.reproduced` filled | the `plan` commands, under heavy-work admission on the build host |
| SL-3.2 | evidence | SL-3.1 | `RRIMAGE.md`, `pin-record.json` | G-RR-REGISTRY and G-RR-PUSH recorded; one push; registry inspection; `record` writes a `pushed` record | `review_runner_image.py record` |
| SL-3.3 | evidence | SL-3.2 | `RRIMAGE.md`, `pin-record.json` | G-RR-PULL recorded; pull by digest on `ai`, inspection, helper read without entrypoint start, container removed; promote to `pinned` only if `verify-pull` passes | `review_runner_image.py verify-pull` |
| SL-3.4 | verify | SL-3.3 | SL-3 owned files | — | `V0`; `gitleaks` on the evidence files |

### SL-4 — Post-push evidence back-fill, handoff and docs sweep

- **Scope**: Back-fill the now-known image reference and source commit into the handoff and changelog, commit the pinned record behind a receipt test, post the handoff and close the phase.
- **Owned files**: `phase-loop-runtime/tests/test_review_runner_pin_receipt.py`, `plans/evidence/review-runner/HANDOFF-ai-stack.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: IF-XR-1 handoff
- **Interfaces consumed**: the `pinned` pin record (SL-3), `validate_pin_record` (SL-0), handoff template (SL-2)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | `tests/test_review_runner_pin_receipt.py` | the committed record is `pinned` under P1–P8 against the checkout, and every handoff value equals the record | `V3` |
| SL-4.2 | docs | SL-4.1 | `HANDOFF-ai-stack.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `plans/manifest.json` | handoff filled from the record and posted on ViperJuice/ai-stack#504; one Unreleased entry; catalog rows for the new doc and evidence; lifecycle event appended | — |
| SL-4.3 | verify | SL-4.2 | SL-4 owned files | receipt test | `V3`, then `V0` |

## Execution Policy

- execute: effort=medium, reason=small contract-bound phase
- SL-3: effort=high, reason=live external effects under separate grants

## Execution Notes

- **Single-writer files**: the Containerfile (SL-1); `CHANGELOG.md`,
  `.claude/docs-catalog.json` and `plans/manifest.json` (SL-4). `test_openshell_worker.py`
  is not edited. Its Containerfile substring assertions must keep passing (V2).
- **Containerfile change and the record.** The pin record binds whatever Containerfile is at
  the built source commit. SL-1 lands before SL-3 builds. Any later Containerfile edit fails
  the SL-4 receipt test until the image is re-pinned (P4).
- **Grants.** Each SL-3 task records its grant by name and date before acting. A missing
  grant stops that task with `blocker_class=human_required`. A failed check stops with the
  record left at `pushed`, and is never retried in a loop.
- **Credentials.** Push credentials stay in the build host's credential helper. No lane reads,
  prints or copies them. Evidence carries registry and repository names only.
- **Known destructive changes**: none — every lane is purely additive, apart from SL-1's
  Containerfile edits.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none.
- **Shared host**: plan validators only on shared hosts. V0–V3 run serially with `timeout`
  and no xdist. The SL-3 build holds heavy-work admission on its build host.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Not in this phase**: signing, per-target SEATS REMOTE images, adapter or route
  activation, `policies.json`, LANEEXEC or ACTIVATE edits, CI image builds, any ai-stack
  file.

Next phase: RRIMAGE SL-0 to SL-2 — ready after plan review.
Next command: `claude-execute-phase plans/phase-plan-v1-rrimage-RRIMAGE.md` for SL-0 to SL-2
under execution authority. SL-3 starts only after the owner grants.

## Acceptance Criteria

- [ ] EC-RRIMAGE-1 — proven by V0 (`tests/test_review_runner_pin.py`) through `validate_pin_record` on the packaged schema; falsified by any one-rule mutation of a valid record passing, or by a refusal message containing a record value.
- [ ] EC-RRIMAGE-2 — proven by V1 (`tests/test_review_runner_recipe.py`) on the checked-in Containerfile and through `review_runner_image.py plan`; falsified by an unpinned `FROM`, a networked unhashed `RUN`, an unhashed helper-source copy, a missing determinism option, or any subprocess call from `plan`.
- [ ] EC-RRIMAGE-3 — proven by `plans/evidence/review-runner/RRIMAGE.md` (SL-3.1, SL-3.2) and a `pushed` record that passes `validate_pin_record`; falsified by a tag reference, an index digest, a missing config digest or an unrecorded grant.
- [ ] EC-RRIMAGE-4 — proven by V3 (`tests/test_review_runner_pin_receipt.py`) on the committed `pinned` record; falsified by any P6 mismatch, `entrypoint_started` true, or a Containerfile edit after the pinned commit.
- [ ] EC-RRIMAGE-5 — proven by `plans/evidence/review-runner/HANDOFF-ai-stack.md`, which links its posted comment and whose values equal the record (checked in V3); falsified by a differing value or by any adapter, route or configuration change in the diff.

## Verification

Execution-time commands; this planning change runs none of them. Each group runs as
`cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider <files>`.

- V0: `tests/test_review_runner_pin.py`
- V1: `tests/test_review_runner_recipe.py`
- V2: `tests/test_openshell_worker.py`
- V3: `tests/test_review_runner_pin_receipt.py`

At execution preflight, validate V0–V3 and `automation.suite_command` with
`verification_evidence.validate_verification_commands` (IF-0-VC-2). The live evidence of
EC-RRIMAGE-3 and EC-RRIMAGE-4 is operational. A runner-stamped roadmap amendment lists the
EC IDs, the record's sha256 and the actual results before ACTIVATE relies on them.
