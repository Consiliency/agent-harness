---
phase_loop_plan_version: 1
phase: RRIMAGE
roadmap: specs/phase-plans-rrimage-v1.md
roadmap_sha256: 4cb691621ea760f3494513485dbc65abfdda3c9bcd7532152533db0546da899e
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_review_runner_pin.py tests/test_review_runner_containerfile.py tests/test_review_runner_recipe.py tests/test_openshell_worker.py"]
---

# RRIMAGE: Review-runner image build and pin

## Context

ai-stack Unit 7 needs a distinct, pinned review-runner image, with platform and pull
evidence, for end-to-end qualification on `ai` (RRIMAGE §1). The Containerfile already pins
its bases, the landlock-exec source, its hashes and the wheel hash. Nothing yet records what
was built, or proves that `ai` can pull it. This phase is OWNER-DECISION RR-1 option (c) of
the LANEEXEC-v1-errata-2 draft (agent-harness#2102), run in parallel with v13 LANEEXEC.

**Revision 2 (2026-11-22)** applies the first review of agent-harness#2106.
- B1: agent-harness builds and hands over the exact OCI archive and its manifest bytes.
  ai-stack pushes and pulls on `ai`. The record moves to `pinned` only after ai-stack's
  receipt is verified.
- B2: builds go to OCI archives, `build.first_manifest_digest` is recorded, and P9 is added.
- E1–E10: see RRIMAGE revision 2, §2–§6.
- The Containerfile hardening is its own lane, SL-1.

Frozen inputs, read before building:

- `plans/artifacts/rrimage-v1-contract.md`, which covers:
  - sources and ownership (§1);
  - rules P1–P10, the digest fields and the refusal codes (§2);
  - the scope of P4 (§2.1);
  - the recipe (§3) and the offline tests (§4);
  - the grant, the external gates and their order (§5);
  - the receipt requirements (§5.1), the handoff (§6) and the non-goals (§7).
- `plans/artifacts/rrimage-v1-pin-record.schema.json`.
- `phase-loop-runtime/images/review-runner/Containerfile` and
  `phase-loop-runtime/tests/data/landlock-exec/PIN.json` at their current bytes.

**Before any grant.** SL-0 to SL-3 need no grant and make no network call. SL-4 needs
G-RR-BUILD, and its posts run under the coordinator authority recorded in RRIMAGE §5. SL-5
needs ai-stack's receipt (EXT-RR-PULL). No lane pushes, pulls or acts on `ai`.

## Interface Freeze Gates

- [ ] IF-0-RRIMAGE-1 — `review_runner_pin.v1`.
  - The frozen schema is packaged byte-equal as
    `contracts/placement/review-runner-pin-v1.schema.json`.
  - The API:
    - `load_pin_record(path)`;
    - `validate_pin_record(record, repo_root, *, allow_stale_marker=False) -> PinVerdict`;
    - `assemble_built_record(layout_dir, build_meta)`;
    - `apply_receipt(record, receipt) -> record`.
  - These raise only the RRIMAGE §2 closed codes, `from None`, and messages never carry
    record values.
- [ ] IF-0-RRIMAGE-2 — The hardened Containerfile (RRIMAGE §3.5–§3.8) and the recipe CLI
  `review_runner_image.py plan|record|verify-receipt`. `plan` prints the commands and runs no
  subprocess. `record` and `verify-receipt` read local files and call the IF-0-RRIMAGE-1 API.
- [ ] IF-0-RRIMAGE-3 — The hand-over content of RRIMAGE §6 and the receipt requirements of
  §5.1.

## Cross-Repo Gates

- [ ] IF-XR-1 (ai-stack Unit 7, consumer and producer) — ai-stack consumes the SL-4 handoff
  on ViperJuice/ai-stack#504. It performs EXT-RR-REGISTRY, EXT-RR-PUSH, EXT-RR-PULL and
  EXT-RR-ALLOWLIST, and it produces the §5.1 receipt that SL-5 consumes. No agent-harness lane
  writes ai-stack files.

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
  Blocks: SL-2, SL-3, SL-4, SL-5
  Parallel-safe: yes

SL-1 — Containerfile hardening
  Depends on: (none)
  Blocks: SL-4, SL-5
  Parallel-safe: yes

SL-2 — Recipe CLI
  Depends on: SL-0
  Blocks: SL-3, SL-4, SL-5
  Parallel-safe: yes

SL-3 — Operator guide and handoff template
  Depends on: SL-0, SL-2
  Blocks: SL-4, SL-5
  Parallel-safe: yes

SL-4 — Build and hand-over (G-RR-BUILD)
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: SL-5
  Parallel-safe: no

SL-5 — Receipt back-fill, pin and docs sweep
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: (none)
  Parallel-safe: no

| Lane | Needs | May run now |
| --- | --- | --- |
| SL-0, SL-1, SL-2, SL-3 | nothing | yes |
| SL-4 | G-RR-BUILD; coordinator authority for the post | no |
| SL-5 | the ai-stack receipt (EXT-RR-PULL, after EXT-RR-REGISTRY and EXT-RR-PUSH); coordinator authority for the post | no |

## Lanes

### SL-0 — Pin record contract and validator

- **Scope**: Package the frozen schema and implement rules P1–P10, with the §2.1 P4 scope, as a pure validator.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/review_runner_pin.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/review-runner-pin-v1.schema.json`, `phase-loop-runtime/tests/test_review_runner_pin.py`, `phase-loop-runtime/tests/fixtures/review_runner_pin/**`
- **Interfaces provided**: `load_pin_record`, `validate_pin_record`, `assemble_built_record`, `apply_receipt`, `PinVerdict`
- **Interfaces consumed**: `plans/artifacts/rrimage-v1-pin-record.schema.json`, `jsonschema` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_review_runner_pin.py`, `tests/fixtures/review_runner_pin/**` | RRIMAGE §4 first bullet: valid `built` and `pinned` records; one refusing mutation per P1–P10; P7 digest-field exemption both ways; P4 strict by default, and the stale marker accepted only with `allow_stale_marker=True` and only for the named record; packaged schema equals artifact; messages exclude values | `V0` |
| SL-0.2 | impl | SL-0.1 | `review_runner_pin.py`, packaged schema | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 owned files | all SL-0 tests | `V0`; deleting any single rule check fails at least one test |

### SL-1 — Containerfile hardening

- **Scope**: Apply RRIMAGE §3.5–§3.8 to the Containerfile, with no network call, and audit it statically.
- **Owned files**: `phase-loop-runtime/images/review-runner/Containerfile`, `phase-loop-runtime/tests/test_review_runner_containerfile.py`
- **Interfaces provided**: hardened Containerfile
- **Interfaces consumed**: `phase-loop-runtime/tests/data/landlock-exec/PIN.json` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_review_runner_containerfile.py` | every `FROM` by digest; no `# syntax=` unless digest-pinned; every `RUN` `--network=none` except the hash-pinned pip step; no fetch tool; `LICENSES/` checked against the two `BUILD.lock` notice hashes, with an exact-set assertion; no `PROVENANCE.md` copy; `ARG SOURCE_DATE_EPOCH` in the runtime stage; the setuid/setgid strip and its fail check after the last package step | `V1` |
| SL-1.2 | impl | SL-1.1 | Containerfile | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | SL-1 tests and the existing Containerfile tests | `V1`, then `V2` |

### SL-2 — Recipe CLI

- **Scope**: Add the CLI that prints the RRIMAGE §3 commands, assembles the `built` record from an OCI layout and verifies a receipt, without running any build, push or pull.
- **Owned files**: `phase-loop-runtime/scripts/review_runner_image.py`, `phase-loop-runtime/tests/test_review_runner_recipe.py`, `phase-loop-runtime/tests/fixtures/review_runner_layout/**`
- **Interfaces provided**: `review_runner_image.py plan`, `review_runner_image.py record`, `review_runner_image.py verify-receipt`
- **Interfaces consumed**: `validate_pin_record`, `assemble_built_record`, `apply_receipt` (SL-0)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_review_runner_recipe.py`, layout fixtures | RRIMAGE §4 third bullet: `plan` prints `git archive`, `type=oci,dest=`, `rewrite-timestamp=true`, `--platform linux/amd64`, `SOURCE_DATE_EPOCH`, `--provenance=false`, `--sbom=false`, `--no-cache` and a digest-pinned BuildKit, contains no push or `ai` command, and makes zero subprocess calls; `record` refuses an index, a mismatched blob or a second manifest; `verify-receipt` refuses each P6 and P9 mismatch | `V3` |
| SL-2.2 | impl | SL-2.1 | `scripts/review_runner_image.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests | `V3` |

### SL-3 — Operator guide and handoff template

- **Scope**: Write the operator guide for the recipe, the ownership split, the rules and the consumers, and draft the handoff with placeholders.
- **Owned files**: `docs/review-runner-image.md`, `phase-loop-runtime/openshell-private-transport.md`, `plans/evidence/review-runner/HANDOFF-ai-stack.template.md`
- **Interfaces provided**: operator guide, handoff template
- **Interfaces consumed**: `validate_pin_record` (SL-0), `review_runner_image.py plan` (SL-2)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | docs | — | guide, transport doc pointer | the recipe; G-RR-BUILD as the only agent-harness grant; the four ai-stack gates and their order; P1–P10; the P4 scope and stale marker (§2.1); the consumers | — |
| SL-3.2 | docs | SL-3.1 | handoff template | RRIMAGE §6 fields and the §5.1 receipt requirements as placeholders; the `no-new-privileges` request | — |
| SL-3.3 | verify | SL-3.2 | SL-3 owned files | — | `V0`; the docs name no host other than the role alias `ai` and no host path |

### SL-4 — Build and hand-over (G-RR-BUILD)

- **Scope**: Build twice to OCI archives under G-RR-BUILD, commit the `built` record and its raw manifest and config bytes, and post the handoff.
- **Owned files**: `plans/evidence/review-runner/RRIMAGE.md`, `plans/evidence/review-runner/pin-record.json`, `plans/evidence/review-runner/manifest.json`, `plans/evidence/review-runner/config.json`, `plans/evidence/review-runner/HANDOFF-ai-stack.md`
- **Interfaces provided**: `built` pin record, IF-XR-1 handoff
- **Interfaces consumed**: `review_runner_image.py plan`, `review_runner_image.py record` (SL-2), `validate_pin_record` (SL-0), handoff template (SL-3)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | evidence | — | `RRIMAGE.md`, `manifest.json`, `config.json` | G-RR-BUILD recorded by name and date; export, helper fetch, two OCI-archive builds; raw manifest and config extracted byte-for-byte; helper sha256 read from the archive layer; archives kept in the host's private directory | the `plan` commands, under heavy-work admission on the build host |
| SL-4.2 | evidence | SL-4.1 | `pin-record.json`, `RRIMAGE.md` | `record` writes the `built` record; on a reproducibility mismatch, a repository-qualified deferred-finding issue is filed and linked | `review_runner_image.py record` |
| SL-4.3 | docs | SL-4.2 | `HANDOFF-ai-stack.md` | filled from the `built` record; coordinator authority recorded; posted on ViperJuice/ai-stack#504 | — |
| SL-4.4 | verify | SL-4.3 | SL-4 owned files | — | `V0`; `gitleaks` on the evidence files |

### SL-5 — Receipt back-fill, pin and docs sweep

- **Scope**: Back-fill ai-stack's now-known pushed reference and receipt into the record, pin it behind a receipt test, post the pinned record's hash and close the phase.
- **Owned files**: `phase-loop-runtime/tests/test_review_runner_pin_receipt.py`, `plans/evidence/review-runner/receipt-ai-stack.json`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: `pinned` pin record
- **Interfaces consumed**: `built` pin record (SL-4), `review_runner_image.py verify-receipt` (SL-2), `validate_pin_record` (SL-0), operator guide (SL-3)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | `tests/test_review_runner_pin_receipt.py` | the committed record is `pinned` under §2.1 (P1–P3 and P5–P10 always; P4, or the stale marker); `receipt-ai-stack.json` hashes to `receipt.ref_sha256`; the handoff values equal the record | `V4` |
| SL-5.2 | evidence | SL-5.1 | `receipt-ai-stack.json`, plus `pin-record.json` and `RRIMAGE.md` by SL-4's hand-off | receipt copied from `receipt.ref`; `verify-receipt` promotes to `pinned` or stops with the record left at `built` | `review_runner_image.py verify-receipt` |
| SL-5.3 | docs | SL-5.2 | `CHANGELOG.md`, `.claude/docs-catalog.json`, `plans/manifest.json` | one Unreleased entry; catalog rows; pinned-record sha256 posted on ViperJuice/ai-stack#504; lifecycle event appended | — |
| SL-5.4 | verify | SL-5.3 | SL-5 owned files | receipt test | `V4`, then `V0` |

## Execution Policy

- execute: effort=medium, reason=small contract-bound phase
- SL-4: effort=high, reason=live build and outward hand-over

## Execution Notes

- **Single-writer files.**
  - SL-1: the Containerfile.
  - SL-4: `pin-record.json` and `RRIMAGE.md`. SL-5 edits them after SL-4 merges, which is the
    only cross-lane hand-off.
  - SL-5: `CHANGELOG.md`, `.claude/docs-catalog.json` and `plans/manifest.json`.
  - `test_openshell_worker.py` is not edited, and its Containerfile assertions must keep
    passing (V2).
- **Containerfile and the record.** SL-1 lands before SL-4 builds. A later Containerfile PR
  passes required CI only by adding the stale marker of RRIMAGE §2.1, and no consumer accepts
  a stale record.
- **Ownership.** No lane pushes to a registry, pulls on `ai`, transfers the archive or holds a
  registry credential. Those steps are ai-stack's (RRIMAGE §5). A missing grant, authority or
  receipt stops the lane with `blocker_class=human_required` and no retry loop.
- **Known destructive changes**: SL-1 removes the `PROVENANCE.md` `COPY` from the
  Containerfile. Every other change is purely additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none.
- **Shared host**: only plan validators run on shared hosts. V0–V4 run serially with
  `timeout` and no xdist. SL-4 holds heavy-work admission on its build host.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Not in this phase**: signing, the per-target SEATS REMOTE images, activating an adapter
  or route, `policies.json`, edits to LANEEXEC or ACTIVATE, CI image builds, any ai-stack file,
  and any action on `ai`.

Next phase: RRIMAGE SL-0 to SL-3, ready after plan review.
Next command: `claude-execute-phase plans/phase-plan-v1-rrimage-RRIMAGE.md` for SL-0 to SL-3,
under execution authority. SL-4 starts only after G-RR-BUILD.

## Acceptance Criteria

- [ ] EC-RRIMAGE-1 — proven by V0 (`tests/test_review_runner_pin.py`) through `validate_pin_record` on the packaged schema; falsified by any one-rule mutation passing, a stale record accepted without `allow_stale_marker`, or a refusal message containing a record value, each entered through the path-entered production call `validate_pin_record(record, repo_root)`.
- [ ] EC-RRIMAGE-2 — proven by V1 (`tests/test_review_runner_containerfile.py`) on the checked-in Containerfile and V3 (`tests/test_review_runner_recipe.py`) through `review_runner_image.py plan`; falsified by an unpinned `FROM` or `# syntax=`, a networked unhashed `RUN`, an extra or unhashed `LICENSES/` file, a `PROVENANCE.md` copy, a remaining setuid file check, a missing determinism or OCI-output option, or any subprocess call from `plan`.
- [ ] EC-RRIMAGE-3 — proven by `plans/evidence/review-runner/RRIMAGE.md` and a `built` record passing `validate_pin_record` with its committed `manifest.json` and `config.json` (P9); falsified by manifest bytes whose sha256 differs from the digest, an index, a P10 inconsistency, or an unrecorded grant or authority.
- [ ] EC-RRIMAGE-4 — proven by V4 (`tests/test_review_runner_pin_receipt.py`) on the committed `pinned` record and receipt; falsified by any P6 or P9 mismatch, a header-only digest match, `container_state` other than `created`, or a config digest read by any method other than the raw manifest's descriptor.
- [ ] EC-RRIMAGE-5 — proven by V4 (`tests/test_review_runner_pin_receipt.py`: every handoff value equals the record) and V3 (`tests/test_review_runner_recipe.py`: `plan` emits no push or `ai` command); falsified by a differing handoff value, a push or `ai` command in `plan` output, or an adapter, route or configuration file in the phase diff.

## Verification

Execution-time commands; this planning change runs none of them. Each group runs as
`cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider <files>`.

- V0: `tests/test_review_runner_pin.py`
- V1: `tests/test_review_runner_containerfile.py`
- V2: `tests/test_openshell_worker.py`
- V3: `tests/test_review_runner_recipe.py`
- V4: `tests/test_review_runner_pin_receipt.py`

At execution preflight, validate V0–V4 and `automation.suite_command` with
`verification_evidence.validate_verification_commands` (IF-0-VC-2). EC-RRIMAGE-3 and
EC-RRIMAGE-4 rest on operational evidence. A runner-stamped roadmap amendment lists the EC
IDs, the record's sha256, the receipt's sha256 and the actual results before ACTIVATE relies
on them.
