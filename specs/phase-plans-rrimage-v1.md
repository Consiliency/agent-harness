# Phase roadmap RRIMAGE v1: build and pin the review-runner image

> # ADVISORY — not runner-selected (2026-11-22)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md` remains the
> sole active runner-selected roadmap. It grants no build, push, pull, workflow dispatch or
> access to any host. Its build lane runs only under G-RR-BUILD. agent-harness never pushes
> to a registry and never acts on `ai`.

## Context

ai-stack Unit 7 is the remote sandbox coordinator on `ai`. For end-to-end qualification it
needs a distinct, pinned review-runner image, and it treats a missing one as a blocker
(RRIMAGE §1). `phase-loop-runtime/images/review-runner/Containerfile` pins its inputs, but no
image digest, pin record or pull evidence exists, and until now no lane owned the work.

The LANEEXEC-v1 errata-2 draft (agent-harness#2102) scopes the work as OWNER-DECISION RR-1
and recommends option (c): a small phase run in parallel with v13 LANEEXEC. The coordinator
adopted option (c), and this roadmap is that phase. It is a separate roadmap so that the
pinned `roadmap_sha256` of the v13 plans stays valid.

Revision 2 (2026-11-22) applies the review of agent-harness#2106 (RRIMAGE contract,
revision 2). Under the coordinator's ruling on B1:
- RRIMAGE builds the image and hands over the exact OCI archive and its manifest bytes.
- ai-stack pushes the image and pulls it on `ai`.
- RRIMAGE pins only after verifying ai-stack's pull receipt.

## Architecture North Star

```
 Containerfile @ source commit ──git archive──> clean context ─┐
 agent-toolkit helper @ pinned commit ──read-only──> context ──┴─> buildx linux/amd64
      (digest-pinned bases and BuildKit, network-disabled RUN, SOURCE_DATE_EPOCH)
        ──> OCI archive + raw manifest/config bytes ──> built record ──> handoff
 ai-stack (owner): push exact archive ──> pull by digest on ai ──> receipt
        ──> RRIMAGE verifies receipt (P6, P9) ──> pinned record
        ──> ACTIVATE and the LANEEXEC operator config consume it (strict P4)
```

## Assumptions

- A1. `docker buildx` with a digest-pinned BuildKit can build the Containerfile from a
  `git archive` export. It needs no Containerfile change beyond those in RRIMAGE §3.5–§3.8.
  If that is false, the hardening lane stops and the contract is amended.
- A2. ai-stack's PREP can name a digest-preserving push tool from `oci-archive:` input
  (RRIMAGE §5.1). If it cannot, SL-5 waits, and the owner rules on the push path.

## External Inputs

| Input | Pin |
| --- | --- |
| RRIMAGE contract | `plans/artifacts/rrimage-v1-contract.md`, sha256 `0952c0f30258d39b50e202c62b920ea72157acd8d6cc27653a246d427d4e8db8` |
| Pin record schema | `plans/artifacts/rrimage-v1-pin-record.schema.json`, sha256 `8a9ee36a773f2f03dc3379679d3663a32caa1e770edad8430667faef2c942903` |
| Containerfile at planning time | sha256 `f2d317873366426a8cd71ebe41090d2a3867750690072d73df85460cc81673f2` |
| landlock-exec source | `Consiliency/agent-toolkit` `d945fdd060aab9ad9471845f4f8e78406a0ac841` |
| ai-stack Unit 7 | ViperJuice/ai-stack `specs/phase-plans-v17-sandbox-coordinator-unit7.md` at `059abc2178e31db109998f0045ffdea6e97a38f3`, lines 10, 249, 270, 311, 348 and 383 |
| Errata scoping | agent-harness#2102, `plans/artifacts/v13-LANEEXEC-landed-binding.md` §6 E2-6, section sha256 `b128afc43a0b156f175e3d3f37848c04467b181ba1fb0ef516e53fc25eae8786` (RRIMAGE §1 defines the span) |

These are immutable planning inputs, and a change needs a reviewed repin. No plan pins a
future implementation commit, image digest, commit count or landing topology.

## External Readiness Gates

**The one agent-harness owner grant** (RRIMAGE §5):

- **G-RR-BUILD** — a native `linux/amd64` build host and window, with read access to the
  pinned helper source, heavy-work admission and a private directory that keeps the archive.

The handoff posts on ViperJuice/ai-stack#504 are made under the RRIMAGE coordinator's
authority, which is recorded in the evidence.

**Gates owned by ai-stack**, which no agent-harness lane performs (RRIMAGE §5):

- **EXT-RR-REGISTRY** — the push tool, the destination, the CA and the root-only push
  credential (Unit 7 line 249).
- **EXT-RR-PUSH** — the owner pushes the exact archive with a digest-preserving tool (line 348;
  ai-stack#503).
- **EXT-RR-PULL** — the owner verifies the manifest bytes and pull-account access on `ai`, and
  publishes the receipt (lines 270, 311 and 348).
- **EXT-RR-ALLOWLIST** — the root-owned allowlist entry on `ai` (lines 10 and 383). It comes
  after the receipt and does not gate `pinned`.

## Non-Goals

- image signing;
- the per-target SEATS REMOTE vendor images;
- any adapter, route, `policies.json`, LANEEXEC or ACTIVATE change;
- a CI build or push;
- a multi-platform index;
- any registry push, pull or other action on `ai` by agent-harness.

## Cross-Cutting Principles

- **Metadata only.** No credential, auth file, token or host path enters the repository, the
  record, the evidence or the build. `ai` is a public role alias.
- **Offline first.** No lane before SL-4 needs a grant or makes a network call.
- **Shared-host test limits.** Targeted pytest files run serially, under `timeout`. The build
  holds heavy-work admission on its host.

## Top Interface-Freeze Gates

- IF-0-RRIMAGE-1 — The `review_runner_pin.v1` schema, rules P1–P10, the P4 scope and the validator API (RRIMAGE §2).
- IF-0-RRIMAGE-2 — The build recipe, the Containerfile hardening and the offline audits (RRIMAGE §3, §4).
- IF-0-RRIMAGE-3 — The hand-over artifact and the pull-receipt requirements (RRIMAGE §5.1, §6).

## Phases

### Phase 1 — Review-runner image build and pin (RRIMAGE)

**Objective**

agent-harness builds the review-runner image and hands it to ai-stack as an exact OCI
archive. Once ai-stack's pull receipt verifies against it, a committed `pinned`
`review_runner_pin.v1` record follows.

**Exit criteria**

- [ ] EC-RRIMAGE-1 — The pin record schema and validator enforce RRIMAGE §2 P1–P10 offline, with one refusing mutation per rule, and with the §2.1 P4 scope. The packaged schema equals the frozen artifact.
- [ ] EC-RRIMAGE-2 — The Containerfile and the recipe meet RRIMAGE §3, and the planner executes nothing. That requires all of the following: digest-pinned bases and BuildKit; network-disabled or hash-pinned `RUN` steps; no unpinned `# syntax=`; `LICENSES/` checked against `BUILD.lock`; no unhashed `PROVENANCE.md` copy; setuid and setgid bits stripped; `ARG SOURCE_DATE_EPOCH`; a clean source export; OCI-archive output.
- [ ] EC-RRIMAGE-3 — Under G-RR-BUILD, two builds from a named source commit are recorded, and a `built` record passes P1–P3, P5, P7, P9 and P10. Its archive and raw manifest bytes are handed over on ViperJuice/ai-stack#504, with the reproducibility result and the §5.1 receipt requirements.
- [ ] EC-RRIMAGE-4 — ai-stack's pull receipt passes P6, P8 and P9 against the `built` record, and the record is committed as `pinned`.
- [ ] EC-RRIMAGE-5 — Nothing is activated, signed or configured, and agent-harness neither pushes nor acts on `ai`.

**Scope notes**

The phase has six lanes.
- Before any grant: the pin contract, the Containerfile hardening, the recipe CLI and the
  operator guide.
- Under G-RR-BUILD: the build and the handoff.
- After ai-stack's receipt: the receipt reducer pins the record.

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
- IF-0-RRIMAGE-2 — Build recipe, hardening and audits.
- IF-0-RRIMAGE-3 — Hand-over artifact and receipt requirements.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/review-runner-image.md`, `CHANGELOG.md`;
evidence paths: `plans/evidence/review-runner/RRIMAGE.md`, `plans/evidence/review-runner/pin-record.json`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

## Phase Dependency DAG

```
RRIMAGE: {pin contract, Containerfile hardening, guide} ──> recipe CLI ──> build + handoff (G-RR-BUILD)
         ──> [ai-stack: EXT-RR-REGISTRY ──> EXT-RR-PUSH ──> EXT-RR-PULL receipt] ──> pin + docs sweep
v13: PLACECLI ──> LANEEXEC ──> ACTIVATE   (ACTIVATE consumes the pinned record)
```

## Execution Notes

- **Planning.** `plans/phase-plan-v1-rrimage-RRIMAGE.md`.
- SL-0 to SL-3 may start now. SL-4 waits on G-RR-BUILD, and SL-5 waits on ai-stack's receipt.
- The phase runs in parallel with v13 LANEEXEC and has no edge to it. v13 ACTIVATE consumes
  the record through its own readiness lane. This roadmap edits no v13 file.

## Acceptance Criteria

- [ ] Every EC-RRIMAGE exit criterion is met, or recorded as unmet with its reason.
- [ ] The archive and manifest digests, the source commit, the receipt link and the handoff
  comment links are reported to the coordinator.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_review_runner_pin.py tests/test_review_runner_containerfile.py tests/test_review_runner_recipe.py
```
