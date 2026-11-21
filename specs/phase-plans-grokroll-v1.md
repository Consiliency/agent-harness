# Phase roadmap GROKROLL v1: a supported answer to "is this grok build measured?"

> # ADVISORY — not runner-selected (2026-11-21)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md` remains the
> sole active runner-selected roadmap. This status grants no live run, no measurement and no
> access to any host. The owner decisions below are open until recorded.

## Context

A grok seat is admitted only for a binary digest with a measured tool surface (the
tool-surface contract, External Inputs). Measurement spends counted model requests and needs
an owner grant per image. The vendor publishes a build almost every day. Two things are
missing, and this roadmap supplies them:

- a supported way to ask whether a build is measured (Consiliency/agent-harness#2047);
  today a downstream bootstrap reads private runtime symbols to decide whether to hold an
  update;
- an authenticated map from a release version to the digest that is measured.

A third, a job that stages each new release and brings the owner one decision, is deferred
to a follow-up phase (GROKROLL-B below). It waits for an owner ruling and for the first
real measurement to show what one costs.

This is the grok analogue of AGYROLL's HOLD phase and of the catalog half of its ROLLJOB.

## Architecture North Star

A release is derived from the vendor's registry by a check anyone can re-run and recorded
in a shipped catalog; one read-only command, asked by every host and every downstream tool,
reports whether a build is measured and says `advance` only for a measured candidate on
sound inputs.

## Assumptions

The fail-loud assumption is A1 in GROKROLL §0. If it is false the status lane stops.

## External Inputs

| Input | Pin |
| --- | --- |
| GROKROLL contract | `plans/artifacts/grokroll-v1-contract.md`, sha256 `bf7d701c7494151b7ffe15a139a39ecfbd29356b47b80e3005f9ba61e3487e8f` |
| grok tool-surface contract (§3, §4.1–§4.3, rulings D1 and D3) | `plans/artifacts/grok-tool-surface-contract-v1.md`, sha256 `9c56fc68e164d9ae7abbeb4969ee860c6844355c3d80569e4bb4600a3e6355d4`. This file is not edited. |
| AGYROLL contract (§1.1 transport rules) | `plans/artifacts/agyroll-v1-contract.md`, sha256 `eaa438944f8422f610bab426f5681f35e19363b050a5e8a9ebf36f13aa2abcae` |
| Vendor registry surface | the public npm registry documents, signatures and attestations endpoint for `@xai-official/grok` and `@xai-official/grok-linux-x64`, as observed in GROKROLL §0 on 2026-11-21 |

These are immutable planning inputs, and a change needs a reviewed repin. No plan pins a
future implementation commit, a commit count or a landing topology.

## Owner Decisions (open)

- **OD-3 — making the catalog gate live** (GROKROLL §2.5): an organization or enterprise
  ruleset that requires the provenance workflow from a protected source ref on `main`, and
  the owner's attestation of it. Until then the release catalog stays empty. A status check
  alone is not accepted as the gate. If the facility is unavailable, the catalog stays
  empty and the release gate alone applies.
- **OD-4 — the constants** `LAG_NOTICE`, `SURFACE_KEEP`, `RELEASE_KEEP` and `MAX_RELEASES`
  (GROKROLL §1, §5.2, §5.4). The contract's values stand unless ruled.

OD-1 and OD-2 of earlier drafts moved to GROKROLL-B as OD-B1 and OD-B2 (GROKROLL §7).

## External Readiness Gates

- **EXT-2046.** Consiliency/agent-harness#2046 shares `pyproject.toml`, `uv.lock`,
  `CHANGELOG.md` and `plans/manifest.json`. Lanes that write those files rebase onto it
  once it merges or closes.
- **EXT-BOOT.** EC-GROKROLL-9 lands in a downstream bootstrap under that repository's
  rules. It needs only the first lane of this phase in a released runtime.
- **EXT-L3.** The first measured surface reaches the shipped catalog by the tool-surface
  plan's own lane. Until OD-3 a surface may ship with no release member (GROKROLL §1).

## Non-Goals

- Staging, executing or measuring a grok build; the roll job; approvals; a standing grant
  (GROKROLL-B).
- Changing any grok launch path, the tool gate, the measurement ledger, the request budget
  or the egress policy.
- Platforms other than linux-x64.
- A harness-side cache of measured binaries and a runtime catalog fetch (GROKROLL §11).

## Cross-Cutting Principles

- **Fail closed.** Corrupt, partial and absent evidence are three different results. Only a
  measured candidate on sound inputs is ever `advance`.
- **Nothing here runs a provider binary.** No lane stages, executes or measures one, and
  no lane can cause a model request.
- **Digest, not version.** A version names and orders. Only a digest is measured.
- **Ships inert.** An empty catalog and an unattested gate.
- **Shared-host test limits.** Targeted pytest files, serially without `-n`, under
  `timeout`. Full suites go to hosted CI or Gate A.

## Top Interface-Freeze Gates

- IF-0-GROKROLL-1 — The release catalog `grok_release_catalog.v1`, its loader, the gate file and the offline signature check (GROKROLL §1, §2.5).
- IF-0-GROKROLL-2 — `seat-window status --vendor grok`, typed evidence, `grok_seat_status.v1` and the decision table (GROKROLL §3, §5.1).
- IF-0-GROKROLL-3 — `derive_release`, the verifier modes and `check_tree`, and the hosted check `grok catalog provenance` (GROKROLL §2).
- IF-0-GROKROLL-4 — The downstream bootstrap contract (GROKROLL §6).

## Phases

### Phase 1 — grok release catalog and measured-build query (GROKROLL)

**Objective**

Any host can ask, through a supported command, whether a grok build is measured and whether
to move onto an update; and a release's digest is recorded in a catalog that a re-runnable
check authenticates.

**Exit criteria**

- [ ] EC-GROKROLL-1 — `phase-loop seat-window status --vendor grok` answers for a path, a digest and a release version under GROKROLL §3: every source is read through typed evidence, so corrupt, partial and absent evidence give the distinct route and build states of §3.2; revocation precedes all evidence; a listing basis needs a validated receipt; and the command makes no network or model call, executes no provider binary and writes nothing. Falsified by a corrupt or unreadable record, attempt register, receipt or catalog reported as `unmeasured` or `measured`; by a withdrawn host-local route reported `usable`; by a context change reported as `invalid` instead of stale; by a revoked digest, another host's record or a help-text listing claim reported as measured; or by any write, launch or socket observed in the run.
- [ ] EC-GROKROLL-2 — The `grok_seat_status.v1` output is stable (GROKROLL §3.3): a golden test pins every key, type, nullability, enumerated value, error object and exit status, and the command works from an installed wheel with the optional extra absent; falsified by a removed, renamed or retyped key that the test does not catch.
- [ ] EC-GROKROLL-3 — The decision follows GROKROLL §5.1: over every pair of build states the only `advance` is a measured candidate on sound inputs, and `advance_to` and `rollback_to` name only measured members; falsified by an `advance` with an invalid input, an unresolved, invalid, revoked, partial, stale or unmeasured candidate, or an invalid subject, or by a target whose host-local route is withdrawn.
- [ ] EC-GROKROLL-4 — The release catalog loader refuses every malformed input in GROKROLL §1 and voids the whole file on one bad entry, the offline `check_tree` (GROKROLL §2.4) is provided by the first slice and holds in the ordinary hosted pytest job, with the real signature vector of GROKROLL §0 verified under the pinned key in every suite environment GROKROLL §2.2 names; falsified by a partial catalog, a catalog over `MAX_RELEASES`, a non-empty unattested catalog that passes, or the signature test skipping for a missing dependency.
- [ ] EC-GROKROLL-5 — `derive_release` (GROKROLL §2.2) derives a genuine fixture release deterministically and refuses each tampered one with its code: a wrong integrity, a bad or unknown-key signature, a payload pin mismatch, a second or special member, an oversize archive, an oversize or non-ELF expansion; the transport follows GROKROLL §2.1; falsified by any tampered fixture that derives.
- [ ] EC-GROKROLL-6 — The enforcement layers of GROKROLL §2.5 behave as stated: `--catalog-pr` runs the base commit's verifier and environment, watches the gate file, and fails an entry that does not re-derive, a gate attestation whose resulting tree breaks parity or is malformed, and a change over the entry bound; `--release` re-derives every entry of a catalog up to `MAX_RELEASES`, with no baseline, before any upload; falsified by a head-supplied verifier being executed, a gate-only change passing while a shipped surface has no member, or an upload preceding the release check.
- [ ] EC-GROKROLL-7 — Aging follows GROKROLL §5.2 and the nightly report maintains exactly one open `grok-measure` issue under GROKROLL §5.4; falsified by a pinned or surfaced entry pruned, or two open issues.
- [ ] EC-GROKROLL-8 — The pins of GROKROLL §8 hold: `seat_window.py` is the only hashed runtime file the phase edits; the context digest, the allow-list digests, the route argv digests and the receipt schema do not move; the files §8 lists as not edited are unchanged.
- [ ] EC-GROKROLL-9 — (downstream bootstrap) its grok update hold follows GROKROLL §6 and reads no private harness symbol or file; falsified by an import of a harness module or a read under the private record root.

**Scope notes**

The tool-surface plan's runtime lanes are already merged (agent-harness#2033), so this
phase has no phase dependency. Decompose into a first slice plus two lanes and a docs
reducer:

- **First slice:** the catalog loader, the gate file, typed evidence and the status query.
  It answers Consiliency/agent-harness#2047 and satisfies EC-GROKROLL-1 to 4 alone, with no
  network, no credential and no owner decision.
- **Provenance:** `derive_release` and the verifier script.
- **Hosted checks:** the provenance check, the release gate and the nightly report.
- **Docs:** the operations page and the changelog.

**Non-goals**

Every act in GROKROLL §10, and everything in GROKROLL-B.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/grok_roll/**`
- `phase-loop-runtime/src/phase_loop_runtime/data/grok_releases.json`
- `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`
- `phase-loop-runtime/scripts/verify_grok_release.py`
- `phase-loop-runtime/src/phase_loop_runtime/data/grok_catalog_gate.json`
- `phase-loop-runtime/scripts/local_check.py`
- `ci/dagger/src/agent_harness_ci/main.py`
- `.github/workflows/test.yml`
- `.github/workflows/grok-catalog-provenance.yml`
- `.github/workflows/grok-release-watch.yml`
- `.github/workflows/publish-pypi.yml`
- `docs/ops/grok-release-catalog.md`

**Depends on**

- (none)

**Produces**

- IF-0-GROKROLL-1 — The release catalog, its loader, the gate file and the signature check.
- IF-0-GROKROLL-2 — The status command, typed evidence and its output schema.
- IF-0-GROKROLL-3 — Release derivation, the verifier modes and the hosted provenance check.
- IF-0-GROKROLL-4 — The downstream bootstrap contract.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/ops/grok-release-catalog.md`, `CHANGELOG.md`;
evidence paths: `phase-loop-runtime/tests/test_grok_seat_status.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

## Deferred follow-up: GROKROLL-B

Not a phase of this roadmap yet. It is planned by roadmap amendment after the owner rules
on OD-B1 and after the first real grok measurement gives cost and timing. GROKROLL §7
records, non-normatively, what it would add, the interfaces this phase freezes for it, the
two owner decisions with a recommendation and trade-off each, and the review findings it
must resolve.

## Phase Dependency DAG

```
GROKROLL: first slice ──> provenance ──> hosted checks ──> docs
EXT-BOOT follows the first slice in a released runtime.
GROKROLL-B (deferred) follows GROKROLL, OD-B1 and the first real measurement.
```

## Execution Notes

- **Planning.** `plans/phase-plan-v1-grokroll-GROKROLL.md`.
- **Single-writer files.** `seat_window.py`, `pyproject.toml`, `uv.lock`,
  `.github/workflows/test.yml` and its install mirrors are written by the first slice only.
- **Activation** is not a phase here. After merge the owner performs GROKROLL §10.

## Acceptance Criteria

- [ ] Every EC-GROKROLL exit criterion is met, or recorded as unmet with its reason.
- [ ] Consiliency/agent-harness#2047 closes with the first slice's evidence linked.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_grok_release_catalog.py tests/test_grok_evidence.py tests/test_grok_seat_status.py \
  tests/test_grok_release_provenance.py tests/test_verify_grok_release.py \
  tests/test_grok_tool_surface.py
timeout 120 .venv/bin/phase-loop seat-window status --vendor grok   # read-only
```
