# Phase roadmap RRIMAGE v1: build and pin the review-runner image

> # ADVISORY — not runner-selected (2026-11-22)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md` remains the
> sole active runner-selected roadmap. It grants no build, push, pull, workflow dispatch or
> access to any host. Its live lane runs only under the owner grants named below.

## Context

ai-stack Unit 7, the remote sandbox coordinator on `ai`, needs a distinct, pinned
review-runner image for end-to-end qualification, and treats a missing one as a blocker
(RRIMAGE §1). `phase-loop-runtime/images/review-runner/Containerfile` pins its inputs, but no
image digest, pin record or pull evidence exists. No lane owned the work. The LANEEXEC-v1
errata-2 draft (agent-harness#2102) scopes it as OWNER-DECISION RR-1 and recommends option
(c): a small phase run in parallel with v13 LANEEXEC. The coordinator adopted that option, and
this roadmap is that phase. It is a separate roadmap so that the pinned `roadmap_sha256` of
the v13 plans stays valid.

## Architecture North Star

```
 Containerfile @ source commit ──git archive──> clean context ─┐
 agent-toolkit helper @ pinned commit ──read-only──> context ──┴─> buildx (linux/amd64,
      digest-pinned bases and BuildKit, SOURCE_DATE_EPOCH, no unpinned network)
        ──push by digest──> registry ──pull by digest on ai──> inspect
        ──> review_runner_pin.v1 record (metadata only, status pinned)
        ──> ai-stack allowlist handoff;  ACTIVATE and LANEEXEC operator config consume it
```

## Assumptions

- A1. `docker buildx` with a digest-pinned BuildKit can build the Containerfile from a
  `git archive` export with no Containerfile change other than RRIMAGE §3.5–§3.6. If that is
  false, the recipe lane stops and the contract is amended.
- A2. The container runtime on `ai` can pull by digest and `create`/`cp` without starting the
  entrypoint. If it cannot, SL-3.3 stops and reports.

## External Inputs

| Input | Pin |
| --- | --- |
| RRIMAGE contract | `plans/artifacts/rrimage-v1-contract.md`, sha256 `10ad467a3c74a182d913b8252d1523ce5688c370e5bd3792b97a6498ef0818a9` |
| Pin record schema | `plans/artifacts/rrimage-v1-pin-record.schema.json`, sha256 `bd5f510f417081acb81a2ad6a94b3ab0d16a5fac09a8304fb7d46620eba451ec` |
| Containerfile at planning time | sha256 `f2d317873366426a8cd71ebe41090d2a3867750690072d73df85460cc81673f2` |
| landlock-exec source | `Consiliency/agent-toolkit` `d945fdd060aab9ad9471845f4f8e78406a0ac841` |
| ai-stack Unit 7 handoff | ViperJuice/ai-stack `specs/phase-plans-v17-sandbox-coordinator-unit7.md` at `059abc2178e31db109998f0045ffdea6e97a38f3` |
| Errata scoping | agent-harness#2102 head `d8aba601eb7a7ce38d07aca3f395fa679e01e0bc`, binding §6 E2-6 |

These are immutable planning inputs, and a change needs a reviewed repin. No plan pins a
future implementation commit, image digest, commit count or landing topology.

## External Readiness Gates

Owner grants, each given separately (RRIMAGE §5):

- **G-RR-REGISTRY** — the registry and repository, and push credentials held by the build
  host's credential helper.
- **G-RR-BUILD** — a native `linux/amd64` build host and window, with read access to the
  pinned helper source.
- **G-RR-PUSH** — one push of the built image.
- **G-RR-PULL** — one pull by digest on `ai`, with inspection and no entrypoint start.

External: **EXT-RR-ALLOWLIST** — ai-stack's root-owned allowlist entry on `ai`, made by
ai-stack from the handoff.

## Non-Goals

Image signing; per-target SEATS REMOTE vendor images; any adapter, route, `policies.json`,
LANEEXEC or ACTIVATE change; a CI build or push; a multi-platform index.

## Cross-Cutting Principles

- **Metadata only.** No credential, auth file, token or private host path enters the
  repository, the record, the evidence or the build.
- **Offline first.** Every lane before the live lane runs with no grant.
- **Shared-host test limits.** Targeted pytest files, serially, under `timeout`. The build
  holds heavy-work admission on its host.

## Top Interface-Freeze Gates

- IF-0-RRIMAGE-1 — The `review_runner_pin.v1` schema, rules P1–P8 and the validator API (RRIMAGE §2).
- IF-0-RRIMAGE-2 — The build recipe and the offline recipe audit (RRIMAGE §3, §4).

## Phases

### Phase 1 — Review-runner image build and pin (RRIMAGE)

**Objective**

A `pinned` `review_runner_pin.v1` record for the review-runner image, proven by a pull by
digest on `ai`, is committed and handed to ai-stack for its allowlist.

**Exit criteria**

- [ ] EC-RRIMAGE-1 — The pin record schema and validator enforce RRIMAGE §2 P1–P8 offline, with one refusing mutation per rule, and the packaged schema equals the frozen artifact.
- [ ] EC-RRIMAGE-2 — The build recipe meets RRIMAGE §3: digest-pinned bases and BuildKit, hash-pinned or network-disabled `RUN` steps, hash-checked helper-source copies, a clean source export and the determinism options. The planner executes nothing.
- [ ] EC-RRIMAGE-3 — Under G-RR-BUILD, G-RR-REGISTRY and G-RR-PUSH, one image is built from a named source commit and pushed by digest. Its manifest and `linux/amd64` config digests and its reproducibility result are recorded.
- [ ] EC-RRIMAGE-4 — Under G-RR-PULL, a pull by digest on `ai` and an inspection that never starts the entrypoint match the record, and the record is committed as `pinned`.
- [ ] EC-RRIMAGE-5 — The handoff reaches ai-stack with the record values. Nothing is activated, signed or configured.

**Scope notes**

Five lanes. The pin contract, the recipe and the docs run before any grant. The live lane
needs all four grants. The reducer commits the record and the handoff.

**Key files**

- `phase-loop-runtime/images/review-runner/Containerfile`
- `phase-loop-runtime/src/phase_loop_runtime/review_runner_pin.py`
- `phase-loop-runtime/scripts/review_runner_image.py`
- `plans/evidence/review-runner/`
- `docs/review-runner-image.md`

**Depends on**

- (none)

**Produces**

- IF-0-RRIMAGE-1 — Pin record schema, rules and validator.
- IF-0-RRIMAGE-2 — Build recipe and recipe audit.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/review-runner-image.md`, `CHANGELOG.md`;
evidence paths: `plans/evidence/review-runner/RRIMAGE.md`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

## Phase Dependency DAG

```
RRIMAGE: pin contract ──> recipe ──> docs ──> live (4 grants) ──> record + handoff
v13: PLACECLI ──> LANEEXEC ──> ACTIVATE   (ACTIVATE consumes the RRIMAGE record)
```

## Execution Notes

- **Planning.** `plans/phase-plan-v1-rrimage-RRIMAGE.md`.
- SL-0 to SL-2 may start now. SL-3 waits on the grants; SL-4 waits on SL-3.
- The phase runs in parallel with v13 LANEEXEC and has no edge to it. v13 ACTIVATE consumes
  its record through its own readiness lane; this roadmap edits no v13 file.

## Acceptance Criteria

- [ ] Every EC-RRIMAGE exit criterion is met, or recorded as unmet with its reason.
- [ ] The image reference, the source commit and the handoff comment link are reported to
  the coordinator.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_review_runner_pin.py tests/test_review_runner_recipe.py
```
