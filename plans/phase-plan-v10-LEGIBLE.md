---
phase_loop_plan_version: 1
phase: LEGIBLE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 040fe81fd36fd48486bb4d6d9550296a830789b5d7a94a9300d3d19ff31cfd2e
legible_lifecycle_contract: legible_tdd_candidate_main.v1
legible_tdd_activation_env: PHASE_LOOP_TDD_EXPECT_LEGIBLE
legible_capability_marker: phase_loop_runtime.legible_evidence:LEGIBLE_CAPABILITY_VERSION=legible.v1
legible_expected_nodeids: 84
legible_owned_paths_count: 18
legible_owned_paths_sha256: ad11f462c732dabae8a7f51e61a3b229dbb1a8f45954c266d14cb9547cfdd240
automation:
  suite_command: [bash, -lc, 'cd phase-loop-runtime && PYTHONPATH=src python -m pytest -m "not dotfiles_integration" -q && bash scripts/gate_a_cleanroom.sh']
---

# LEGIBLE: Roadmap and Manifest Legibility

## Context

LEGIBLE makes the repository itself authoritative for roadmap lifecycle, active-roadmap
selection, plan-manifest coverage, and stale-assumption detection. The canonical
`.phase-loop/` ledger started the initial planning run at clean HEAD
`1627e3fe51d34a9b8be46fa1d9718d300a606d3c` with LEGIBLE `unplanned`; this
mandatory dissent repair is grounded at source head
`f893eae0d00fa4fc1a7e69d376a5ac059b73f68a`, and no legacy `.codex/phase-loop/`
state is used.

An earlier exact-digest panel blocked plan digest
`aff9a02c37b9f7622492bf7143215880443c9de21f4a44579f15109453ccbcc4`.
Its authoritative dissent found that the plan added a
`verification_evidence_sidecar.v1` record to schema-v2 `verification.json` and changed
`run_verification` validation/call semantics even though
`phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`
freezes v2's exact top-level fields and the public function signature. The same digest omitted
that public contract document from its fifteen-path ownership set and incorrectly claimed no
public-document change even though `cli.py` and `_contract_docs` are public surfaces. This repair
therefore owns the exact contract document, defines the versioned compatibility boundary below,
and initially expanded the closed owned set to sixteen paths. The C5 chronology repair below adds
only its regression-test file and this exact phase plan, producing the final eighteen-path set. The
next exact-digest panel then blocked plan
digest `45a321c4fb38708d217b47021462311b06441fbafc5763bf12ac3f4a987014eb`:
GPT-5.6 Sol found that current `run_verification` serializes a nonempty
`operational_exemptions` value as a tenth schema-v2 top-level field and the pre-existing
`test_preflight_verification.py::PreflightVerificationTest::test_operational_evidence_is_recorded_but_not_executed`
requires it, so exact-nine v2 plus additional-field rejection could not preserve current public
behavior. This repair explicitly versions that existing optional field and makes v3 preserve it
while adding only the namespaced extension. Neither blocked verdict transfers to this changed
digest: before LEGIBLE-A0, the repaired exact plan digest must receive a fresh four-seat panel
under the unchanged v10 policy.

The latest immutable local-three panel at
`.phase-loop/reviews/v10-legible-plan-panel.json` has SHA-256
`b2b306a2e56229df7194da489ab8a158616691c8f063f1515c3b4bc7b3bfc585`. It
reviewed predecessor plan SHA-256
`2765aa6606242b5d68124e13d8ef798b0075a549371be1f4f23b53e3dbd56cef`,
roadmap SHA-256 `1e8ea70ceae55d326cd84b092e1b9e879180d7b0e774140c3dd00e6ed63b7071`,
bundle SHA-256 `9c81cf956d851721064fa2f442dfe31010a7b589ef0a94eb4f86d2b9df61bcf8`,
and instructions SHA-256
`4b166729c4352ac8c086b19b5c68d279258ffd08068c176122dee2533a3c5160`;
Grok and Gemini returned usable `AGREE`, GPT-5.6 Sol returned usable `DISAGREE`,
and Fable was absent, so it authorizes nothing. The blocking review found both the
v2-value-preservation/log-reseal contradiction and the impossible concurrent ownership of the
closed v3 extension map. This repair makes `log_sha256` an explicitly derived value, makes the
new hash authenticate the final v3-sealed log, defines the shared registered-namespace envelope,
and binds PROOFGATE behind LEGIBLE in the amended roadmap. The predecessor panel remains
immutable historical dissent; this changed plan/roadmap pair requires a fresh exact-digest
four-seat panel before LEGIBLE-A0.

The newest immutable local-three review at
`.phase-loop/reviews/v10-legible-plan-panel.json` has file SHA-256
`3d9712c05aa988746c14549d6bda550efa9ddef6eb82470ba5e096a62554c538`.
It reviewed predecessor plan SHA-256
`5e7e563bf96ada32ad054b4e7ac8f5117fffd9ba7742e551826d93c644cae7e0`,
roadmap SHA-256 `4d652aaff71b484806ea6d1770c9475e0c1e8de90c39e5447c6fadb8d0fa2c6f`,
bundle SHA-256 `0a2ecfbeb2fecc6afade833d9c24ab1f3d05caae66541e79a66283715dbb0f05`
(`140117` bytes), and instructions SHA-256
`4b166729c4352ac8c086b19b5c68d279258ffd08068c176122dee2533a3c5160`. Two legs returned usable
`AGREE`; GPT-5.6 Sol returned usable `DISAGREE`, finding that the common selector return gate
accepted a recognized non-active lifecycle banner when `specs/roadmap-status.json` was absent.
This immutable historical dissent authorizes nothing. The repair below parses every recognized
lifecycle declaration on every common return, even without the registry, and preserves
compatibility only when the roadmap has no lifecycle declaration.

The current immutable local-three artifact at that path has SHA-256
`1ee400d1c4aa4f6892675969b3b5b831dff5bc9418c71e71dd989e101295b702`.
It reviewed plan SHA-256
`234a8412a875a58b447d2f9cbbf4ce7edd60397133594281c08165e7bed7e89f`,
roadmap SHA-256 `158c9f28857ef1df02a6b8ca72aef93f3a8a2acc8e591ca6adc70dd53ddb854d`,
bundle SHA-256 `23e65ab41a2ed96c9bb169eef61e067a3c40078cec9cd70c98ae09c5e0311232`
(`146984` bytes), and instructions SHA-256
`4b166729c4352ac8c086b19b5c68d279258ffd08068c176122dee2533a3c5160`;
all three available legs returned usable `AGREE`. It remains immutable
historical evidence only; the roadmap/digest rebind below requires review of
the changed bytes before execution.

The repository currently has thirteen `specs/phase-plans-*.md` roadmaps whose primary banners
describe one active roadmap, five delivered roadmaps, and seven superseded roadmaps, but there
is no frozen machine-readable status registry, selected-roadmap marker, parser, or coherence
check. LEGIBLE adds a repo-owned registry without treating it as an unchecked replacement for
the roadmaps' own declarations: every registered status must agree with the closed primary-banner
grammar below. The live thirteen banners are deterministic enough to parse without changing any
`specs/phase-plans-*.md` bytes. In particular, `specs/phase-plans-v10.md` remains byte-identical
to the roadmap bound by this plan's `roadmap_sha256` throughout execution and final
`validate_plan_doc.py` verification. Any future banner outside the frozen grammar fails closed
and requires an explicit, digest-invalidating roadmap amendment; no code may silently infer or
invent its status. `plans/manifest.json` is schema-version 1 and already
anchors `specs/phase-plans-v10.md`, but it does not register the closed eleven-plan historical
set: the five v6 plans, the five v7 plans, and
`plans/phase-plan-v1-task-message-sourcebroker-SOURCEBROKER.md`. That planning-time gap is not a
cardinality invariant: canonical plan paths are derived from the exact union of the
runner-captured execution `HEAD`, the current Git index, and a security-bounded direct scan of
the repository's physical `plans/` directory. That union includes committed, staged/index-only,
and untracked canonical phase plans, so concurrent root-plan integration changes the computed
total without changing this plan and no on-disk plan can disappear merely because it is absent
from `HEAD`. `.claude/docs-catalog.json` is an empty array and has no repo-local rescan
implementation.

Mandatory-repair live probes on 2026-07-30 found
`Consiliency/agent-harness#347` open, draft, `MERGEABLE`/`CLEAN`, with current server checks
successful at refreshed head `H == 0f12c4614e859fd1082525be852fca4e52624890` against
the then-current `main` refresh base
`B0 == 648be2f68d6804ecdc4046bb7d4f5ee81a90c356`. The exact body SHA-256 remains
`1b8410a0c2eab1c20f9d6e469336d933654003907425daded453b37faa7df0db`; its six commit-table
rows (`10f1e3d`, `0a0438a`, `1b3f091`, `f22030e`, `a493b95`, and `a89dd82`) all resolve
to ancestors of `H`. `H` is the coordinator's ordinary refresh merge with ordered parents
`[H0 == a89dd82ed7253193a4084ab9f2e15136fe12ea05, B0]`. That exact main merge-parent
ancestry is permitted, but the refreshed contribution is only the net `B0..H` delta: one modified
regular file, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, mode `100644`,
`33` additions and `1` deletion, with identical Python tokens after comments and comment-only
newlines are removed. At `B0` the path is Git blob
`dcec427c79e0843ef84362c6753b9bbff3c48384`, `197853` bytes, SHA-256
`dd0437470b4d0fb16ecbe4b87fc46f753136cd39445ed0ad35b61de4ea0376ed`; at refreshed
`H` it is Git blob `29c0e9868ba2eea4fb4ee4114614bfb65191176d`, `200381` bytes,
SHA-256 `014dab9890bc97f0f46f774f11cbeefe2d98a6aa47c81d7bbee17fb56949785a`.
The result is not inferred from the obsolete raw `H0` blob. The reducer recomputes a clean result
tree `T_B0H` in a private temporary index from merge base `B0` and tips `[B0, H]`, requires
`T_B0H == H^{tree} == f99de68b288da3d565afd98fc739664f1d28c368`, and defines resulting
external blob `R` as `T_B0H`'s blob at that path; `R` must be the refreshed `29c0e986…` identity
above. The planned tests-only landing then advances target `main`; the later exact server merge
base `B` is recorded separately and must descend from `B0`, contain the canonical tests-only
landing, and retain the `B0` mode/blob/length/SHA-256 at the external path. A second private-index
merge from merge base `B0` and tips `[B, H]` must be clean, retain every `B` path except the exact
singleton external transition, and produce `R` at that path. Any server base/head/body,
refresh-parent, ancestry, path, mode, comment-only, blob, result, or check/readiness drift requires
plan repair and a new exact-digest panel rather than a broadened path exception.
`Consiliency/agent-harness#367` remains open, so LEGIBLE must not use the catalog-deletion arm:
it implements a populated, countable repo-owned catalog without claiming to resolve the
separate client-document decision.

## Interface Freeze Gates

- [ ] IF-0-LEGIBLE-1 — `specs/roadmap-status.json` is the single repo-owned `roadmap_status_manifest.v1` registry, but never the sole unchecked status authority. It contains exactly `schema`, `selected_roadmap`, and `roadmaps`; `roadmaps` is a stable path-sorted array whose records contain exactly `path` and `status`. In the canonical repository it covers exactly the Git-tracked `specs/phase-plans-*.md` path set once, classifies the live thirteen paths as one `active`, five `delivered`, and seven `superseded`, and sets `selected_roadmap` to the sole active record, `specs/phase-plans-v10.md`. `phase_loop_runtime.roadmap_lint` exposes `RoadmapStatus`, `parse_roadmap_status_manifest(text)`, `parse_roadmap_banner_status(text, path)`, `validate_roadmap_status_coherence(repo, required)`, `read_roadmap_status(repo, path)`, and `declared_active_roadmap(repo)`. The typed `RoadmapStatusError` hierarchy distinguishes malformed registry, malformed/ambiguous/missing banner signal, registry/banner coherence drift, and attempted selection of a recognized non-active roadmap. When the registry is present, status reads first validate exact tracked-path coverage and parse every tracked roadmap's working-tree bytes; every path's registry value must equal its parsed primary-banner value before any value is returned. Canonical repository `validate-roadmap` calls the same coherence validator with `required=True`. A present registry with a missing/extra/duplicate/noncanonical path, path escape, malformed/unknown status, selected/active mismatch, unparseable banner, or sidecar/banner drift is a typed failure. For a synthetic or legacy fixture repo with `specs/roadmap-status.json` wholly absent, `read_roadmap_status` returns `None`; the common selector return gate still reads the candidate bytes and rejects every recognized `delivered` or `superseded` lifecycle declaration. Legacy selection compatibility applies only when the candidate has no lifecycle declaration at all. A malformed, ambiguous, misplaced, or status-like lifecycle declaration is not "legacy" and fails typed. A single `_return_selectable_roadmap(repo, candidate, source)` gate wraps every `select_roadmap` return: it always parses candidate lifecycle bytes, rejects every recognized non-active declaration, and, when the registry exists, additionally invokes the full coherence validator and requires the candidate to be the registered and banner-declared `active` path. The gate covers explicit, authority, state, manifest, handoff, singleton-glob, manifest-disabled, and `PHASE_LOOP_DISCOVERY_ALLOW_COMPLETED=1`/completed-hatch paths; neither registry absence, manifest disablement, nor the completed hatch bypasses a recognized lifecycle declaration. Manifest reporting consumes the same coherence-checked accessor.
- [ ] IF-0-LEGIBLE-2 — `verification_evidence.v3` is the generic LEGIBLE-owned envelope and reader/writer contract. Its version-relative top-level inventories preserve both valid v2 shapes, its v3 `extensions` object is checked against a closed namespace/schema registry, its `log_sha256` authenticates the complete final resealed log rather than an intermediate v2 log, and its initial required namespace is exactly `phase_loop_runtime.legible_evidence`. The generic registry/reader accepts later registered namespaces without making them required for a LEGIBLE-only producer; PROOFGATE owns only the downstream `phase_loop_runtime.proofgate_evidence` record and may not redefine the generic envelope, seal, or reader contract.

The closed status mapping is `active`: `specs/phase-plans-v10.md`; `delivered`:
`specs/phase-plans-cross-repo-v1.md`, `specs/phase-plans-v1-task-message-sourcebroker.md`,
`specs/phase-plans-v1.md`, `specs/phase-plans-v6.md`, and `specs/phase-plans-v8.md`;
`superseded`: `specs/phase-plans-convergence-v1.md`, `specs/phase-plans-v2.md`,
`specs/phase-plans-v3.md`, `specs/phase-plans-v4.md`, `specs/phase-plans-v5.md`,
`specs/phase-plans-v7.md`, and `specs/phase-plans-v9.md`. Frozen tests require exact path/status
equality, not counts alone.

`parse_roadmap_banner_status` is closed over the actual thirteen tracked banners. It first
requires a nonempty Markdown H1 on line 1 and an empty line 2. It then scans only the leading
banner, before the first `## ` body heading, for the following full-line declarations, requires
exactly one match, and requires that match at line 3:

| Parsed status | Exact accepted line-3 grammar |
|---|---|
| `active` | ``> **Status (`YYYY-MM-DD`): ACTIVE — created this date, nothing executed yet.**`` |
| `delivered` | ``> # DELIVERED — CLOSED (assessed `YYYY-MM-DD`)`` |
| `superseded` | ``> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (`YYYY-MM-DD`)`` |
| `superseded` | ``> # SUPERSEDED — ABSORBED into `specs/phase-plans-v10.md` (assessed `YYYY-MM-DD`; corrected after CR)`` |

Backticks around `YYYY-MM-DD` in the table denote an ISO-date slot, not literal backticks; the
implementation uses anchored full matches and validates the date with `date.fromisoformat`.
Case, spacing, punctuation, emphasis, target path, and trailing annotation are otherwise exact.
Later prose such as “active”, “delivered”, “do not execute”, stale next-phase text, and checked
or unchecked task boxes is deliberately not a status signal. Zero matches, a status-like but
nonmatching line 3, a recognized declaration away from line 3, or multiple recognized
declarations is respectively a typed missing, malformed, misplaced, or ambiguous banner error.
The current 1/5/7 path mapping above is the positive control proving all thirteen bytes parse
without a roadmap amendment.

The frozen status/selection mutation matrix is:

| Falsifier | Mutation and required result | Positive control |
|---|---|---|
| `test_status_coherence_rejects_active_registry_with_superseded_do_not_execute_banner` | keep v10 `active` in the registry, replace its line 3 with the accepted superseded declaration and its leading prose with the existing do-not-execute form; canonical `validate-roadmap`, `read_roadmap_status`, and selection raise typed coherence drift | unmodified v10 parses `active`, agrees with the registry, and is selected |
| `test_status_coherence_rejects_superseded_registry_with_active_banner` | keep v7 `superseded` in the registry and replace only its line 3 with the accepted active declaration; the same three surfaces raise typed coherence drift | unmodified v7 parses `superseded` and is refused as non-active |
| `test_status_coherence_rejects_delivered_and_checkbox_drift` | for each delivered roadmap, independently swap its primary declaration to active/superseded or its registry value away from delivered; each mutation fails. Flipping all body checkboxes does not change `delivered`, while removing/mangling line 3 with every box checked raises a banner error rather than inferring completion | all five delivered banners parse `delivered` despite their historical checked/unchecked bodies and agree path-for-path with the registry |
| `test_status_coherence_rejects_missing_malformed_ambiguous_or_misplaced_banner` | delete, alter, duplicate, or move the primary declaration independently; each raises the corresponding typed banner failure | every one of the thirteen unmodified banners has exactly one line-3 match |
| `test_status_registry_exactly_covers_tracked_roadmaps` | independently add/remove a tracked roadmap or add/remove/duplicate a registry row; repository validation names the exact missing/extra/duplicate path and exits nonzero | the Git-tracked path set equals the registry path set exactly |
| `test_status_positive_controls_kill_hardwired_active_or_none` | mutation-run the implementation with the banner/registry result hardwired to `active`, and separately with the selector hardwired to `None`; the 1/5/7 mapping assertions and exact-return positive controls must kill both mutants | the real parser returns the exact closed mapping and every active-source control returns v10 |

`test_superseded_selector_paths_fail_closed` parameterizes eight independent source fixtures.
Each fixture first proves its source is reached, then attempts to return a banner-parsed
superseded roadmap, requires a typed failure from `_return_selectable_roadmap`, and has an
unmutated companion that returns exactly the banner/registry-active v10 path:

| Selector case | Superseded attempt |
|---|---|
| explicit | pass v7 as the explicit roadmap |
| authority | make the active authority marker name v7 |
| state | make `.phase-loop/state.json` name v7 |
| manifest | make the otherwise selectable plan-manifest candidate resolve to v7 |
| handoff | make the latest roadmap-builder handoff name v7 |
| singleton-glob | isolate the glob return with v7 as its sole candidate |
| manifest-disabled | set `PHASE_LOOP_MANIFEST_DISABLED=1` while the state source names v7; the status registry remains enabled |
| completed-hatch | set `PHASE_LOOP_DISCOVERY_ALLOW_COMPLETED=1` with the completed/state candidate resolving to v7 |

The selector parameterization asserts the common gate was called with the expected source label,
not merely that some earlier branch failed. Its v10 companions make an always-`None` selector
fail, while the exact mapping and banner-coherence controls make a hardwired sidecar-`active`
implementation fail.

`test_legacy_repo_without_roadmap_status_registry_preserves_selection` reruns the pre-LEGIBLE
synthetic/legacy selector fixtures with the registry path wholly absent and roadmaps carrying no
lifecycle declaration, and asserts byte-for-byte equivalent selected paths or legacy exceptions.
A second control creates the registry path with empty, partial, or malformed bytes and requires a
typed failure, proving the compatibility branch is absence-only rather than an error-swallowing
fallback. Canonical-repository validation and `declared_active_roadmap` each have an independent
missing-registry negative control.

`phase-loop-runtime/tests/test_legible_roadmap_contract.py::test_absent_registry_selector_rejects_recognized_non_active_banner_and_preserves_no_declaration_legacy`
is one non-parameter-expanded frozen node with an internal literal source table covering explicit,
authority, state, manifest, handoff, singleton-glob, manifest-disabled, and completed-hatch
returns. Each subcase proves its source was reached, removes the registry, rejects recognized
`delivered` and `superseded` declarations, accepts the recognized active declaration, preserves
the old result only for a roadmap with no lifecycle declaration, and rejects a malformed
lifecycle-like declaration. The node kills both an absent-registry early return and an
always-active parser.

## Lane Index & Dependencies

SL-0 — Test-first roadmap status, selection, and assumption contract
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Manifest presence reporting
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: yes

SL-2 — agent-harness#347 evidence, verification contract, and docs-catalog rescan
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Test-first roadmap status, selection, and assumption contract

- **Scope**: Land and panel the complete LEGIBLE falsifier and public-contract compatibility suite before production or implementation-contract-document changes, then freeze the banner-coherent roadmap registry/accessor and bounded assumption grammar while making status drift, stale assumptions, and every discovery return path fail closed.
- **Owned files**: `specs/roadmap-status.json`, `specs/roadmap-assumption-probes-v10.json`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py`, `phase-loop-runtime/src/phase_loop_runtime/discovery.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_legible_roadmap_contract.py`, `phase-loop-runtime/tests/test_legible_evidence.py`
- **Interfaces provided**: `IF-0-LEGIBLE-1`, `roadmap_status_manifest.v1`, closed primary-banner grammar, `roadmap_assumption_probe.v1`, `reviewtruth_fable_transition`, `RoadmapStatus`, `RoadmapStatusError`, `parse_roadmap_status_manifest`, `parse_roadmap_banner_status`, `validate_roadmap_status_coherence`, `read_roadmap_status`, `declared_active_roadmap`, `_return_selectable_roadmap`, `audit_roadmap_assumptions`, `phase-loop attest`, `LEGIBLE frozen falsifier suite`
- **Interfaces consumed**: `select_roadmap` (pre-existing), `validate-roadmap` (pre-existing), `RoadmapAuthorityError` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:

- test: LEGIBLE-A0 creates the immutable two-file falsifier suite with the test-owned activation guard, including contract-document assertions and compatibility controls for legacy-v2 round trip, exact v1/v2/v3 top-level inventories, v2 no-exemption and nonempty-`operational_exemptions` behavior, v3 preservation of either v2 form while adding the sidecar extension, unknown-version/unknown-field rejection, the absent-registry lifecycle falsifier, and the frozen public CLI/function surface; it proves the no-env tests-only state is `84 skipped / 0 failed / 0 errors`, then sets `PHASE_LOOP_TDD_EXPECT_LEGIBLE=1` and proves the same exact 84 nodeids execute and fail by their intended `LEGIBLE_RED::<mutation-id>` assertions with zero skips, xfails, import failures, or collection errors before any production or implementation-contract-document path changes.
- impl: LEGIBLE-A1 depends on the landed LEGIBLE-A0 test-only commit, accepted test-tree/nodeid digests, default-CI JUnit, panel verdict, and raw asserted-anchor RED JUnit/log; it adds the roadmap registry, closed banner parser, typed coherence/accessor surface, bounded probes, CLI check, common discovery return gate, and the generic fresh-process attestation entrypoint without changing either frozen test blob or any roadmap bytes; the downstream evidence owner installs the capability marker only in the final complete implementation candidate.
- verify: LEGIBLE-A2 depends on LEGIBLE-A1 and, until the marker is installed, forces the SL-0 subset with `PHASE_LOOP_TDD_EXPECT_LEGIBLE=1`; after the final marker-bearing candidate it runs the same subset with no activation env plus the pre-existing roadmap/discovery suites, requiring every selected LEGIBLE nodeid to pass with zero skipped. Manifest, catalog, chronology, PR-evidence, runner-sidecar, and artifact-digest falsifiers remain unsatisfied until their owning lanes implement them.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| LEGIBLE-A0 | test | none | `phase-loop-runtime/tests/test_legible_roadmap_contract.py`, `phase-loop-runtime/tests/test_legible_evidence.py` | the complete exact-path, banner/parser/coherence, selector-source, absent-registry lifecycle, status, assumption, manifest, catalog, chronology, activation, frozen-test-blob, artifact-digest, exact-PR-head/body, fresh-process, ancestry, JUnit, post-merge evidence, and verification-contract falsifiers; the frozen 84-nodeid inventory asserts the contract document's version-relative top-level field tables and unchanged signature, legacy v1/v2 load/round-trip behavior, exact nine-field v2 output when `operational_exemptions` is absent or empty, exact ten-field v2 output preserving a nonempty `operational_exemptions`, valid sidecar-bearing v3 output both without and with that optional field, preservation of every v2 JSON value except `schema_version` and derived `log_sha256`, independent authentication of the final v3-sealed log by the replacement `log_sha256`, registered extension-namespace ownership, unknown top-level/extension-version/unregistered-namespace and per-version additional-field rejection, and public `phase-loop` CLI plus `run_verification`/loader/validator signature-behavior controls; both files define their literal `LEGIBLE_EXPECTED_NODEIDS_V1` tuples and one shared immutable activation rule | no env: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py tests/test_legible_evidence.py --junitxml=../.phase-loop/runs/<run-id>/legible-tests-only-default.junit.xml -q` must exit 0 with exactly 84 skips; forced RED: prepend `PHASE_LOOP_TDD_EXPECT_LEGIBLE=1`, write raw output and `legible-tests-only-red.junit.xml`, and require exit 1 with exactly 84 intended failures and zero skips/errors |
| LEGIBLE-A1 | impl | LEGIBLE-A0 test-only landing is on the target/default branch, its exact two-file blob/nodeid-set digests are accepted by the mandatory panel, default-CI and forced-RED evidence are runner-owned, and the implementation branch is based from the landing | `specs/roadmap-status.json`, `specs/roadmap-assumption-probes-v10.json`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py`, `phase-loop-runtime/src/phase_loop_runtime/discovery.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py` | both LEGIBLE-A0 test files and their activation logic are frozen; no implementation task may modify either path | add the closed status registry and assumption-probe sidecar without modifying roadmap bytes; implement the closed banner grammar, typed registry/banner/coherence/accessor surface, fixed assumption adapters, coherent repository `validate-roadmap --check-assumptions`, common `_return_selectable_roadmap` gate, and `phase-loop attest --stage candidate|canonical-main`; do not install or counterfeit the SL-2-owned capability marker |
| LEGIBLE-A2 | verify | LEGIBLE-A1 | SL-0 owned files | frozen SL-0 subsets only; later-lane subsets remain unsatisfied until implemented | `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap --check-assumptions specs/phase-plans-v10.md`, forced-before-marker/default-after-marker `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k "roadmap_status or banner_status or declared_active_roadmap or assumption or superseded_selector" -q`, and `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_phase_loop_roadmap_validate.py tests/test_discovery_hygiene_legacy.py tests/test_roadmap_authority.py -q` |

The chronology is exact and reducer-enforced:

1. Clear the four-vendor panel for the exact plan digest recorded in the LEGIBLE manifest
   entry metadata, with the plan frontmatter lifecycle fields and roadmap digest validated.
2. Complete both LEGIBLE-A0 files on a tests-only branch whose first-parent diff contains only
   those paths. The tests include the contract-document and v1/v2/v3 compatibility controls above
   before the owned public contract document or any production path changes. The files share the
   activation rule
   `forced = os.environ.get("PHASE_LOOP_TDD_EXPECT_LEGIBLE") == "1"` or
   `installed = importlib.util.find_spec("phase_loop_runtime.legible_evidence") is not None`
   followed by
   `legible_evidence.LEGIBLE_CAPABILITY_VERSION == "legible.v1"`; the module-level
   `skipif(not (forced or installed), reason="LEGIBLE capability absent")` is the only skip
   mechanism for the 84 new nodeids.
3. With the marker absent and no env override, run the tests-only targeted command and ordinary
   broad CI. The targeted JUnit must say `tests=84`, `skipped=84`, `failures=0`, `errors=0`;
   the broad suite must stay green and its only newly skipped nodeids must be those exact 84.
   Separately run the pre-existing
   `test_preflight_verification.py::PreflightVerificationTest::test_operational_evidence_is_recorded_but_not_executed`
   nodeid and require it green; it is outside the 84 new nodeids and outside phase write
   ownership, so it is a compatibility sentinel, not an activation-migrated test.
4. Panel the exact two test-blob OIDs plus the SHA-256 of the sorted literal nodeid tuple. The
   panel must confirm that the frozen tests pin the exact public `run_verification` signature,
   v2's optional `operational_exemptions` behavior, the four no-sidecar/sidecar compatibility
   cases, v3 namespaced sidecar validation, version-relative unknown-field rejection, and
   contract-document text before implementation. Then
   set `PHASE_LOOP_TDD_EXPECT_LEGIBLE=1` against the unchanged pre-implementation production
   base. Raw RED output and JUnit must prove all 84 nodeids ran, every node failed its intended
   `LEGIBLE_RED::<mutation-id>` assertion after its source injection anchor assertion succeeded,
   exit code was 1, and failures/skips/errors were exactly `84/0/0`; collection/import failure
   and `xfail`/`xpass` are forbidden substitutes.
5. Land the tests-only change on the target/default branch through ordinary green merge gates.
   Record the canonical landing commit whose first-parent diff changes exactly the two test
   paths. The original two-file RED landing is
   `1c57cc43134506bfeb8f9c21220f8aeef32af384`. A later pre-base test-only correction at
   `a76b9f8bc305b9dd7f663c4a071c9ec4c154b5ea` changed only
   `phase-loop-runtime/tests/test_legible_roadmap_contract.py` to bind its fixture to the canonical
   roadmap digest. The reducer's `tests_landing` field names that latest corrective anchor; both
   frozen blobs at that anchor must be byte-identical at `B`, `P`, `I`, and canonical main. Cut the
   implementation branch from a fetched target head containing both test-only commits.
6. Implement without editing either test path or activation logic. Before the capability marker
   exists, implementation iterations force these tests with the env; SL-2 installs
   `legible_evidence.LEGIBLE_CAPABILITY_VERSION = "legible.v1"` only after every lane's
   production surface is complete, after which the same immutable tests run by default.
7. Freeze and push committed phase-authored candidate `P`. The remote branch OID, local `HEAD`,
   and recorded phase-authored head must be the same 40-hex OID. The builder process stops at
   `awaiting_phase_closeout`; its already-loaded `runner.py` or `verification_evidence.py`, any
   verification it performs, and any executor-authored sidecar are explicitly non-attesting.
8. Launch a new repo-local `phase-loop attest --stage candidate` transition process from a clean
   worktree checked out at `P`. It snapshots the server-recorded `Consiliency/agent-harness#347`
   base `B`, refreshed head `H`, body, and exact commit graph before any merge; requires the
   identities above, `B` to equal the implementation base and fetched target head, `B` to descend
   from `B0` while retaining `B0`'s external-path preimage, `parents(H) == [H0, B0]`, every exact
   body-table SHA to be an ancestor of `H`, and `B0..H` to be the frozen singleton comment-only
   path/blob transition. In private temporary indexes it revalidates `T_B0H`/`R`, then recomputes
   clean server result tree `T_BH` from merge base `B0` and tips `[B, H]`, requires no unmerged
   index stages, `changed(B, T_BH) == E`, and result blob `R`. Only then may it merge that exact
   PR head with merge-commit method. Finalize server merge `M` only when its ordered parents are
   exactly `[B, H]`, `M^{tree} == T_BH`, and its first-parent delta is the same frozen one-file
   transition ending at `R`.
9. From the unchanged phase-authored candidate `P`, create target-integration merge `I` with
   ordered parents exactly `[P, M]`, no conflict or manual resolution, and a tree equal to a
   second private-index merge recomputation from merge base `B` and tips `[P, M]`. `I` must change
   exactly the frozen one-file contribution relative to `P`, and its path blob must equal
   recomputed refreshed result `R`, never the obsolete raw `H0` blob; push `I` as the final
   candidate, then launch a different fresh clean-worktree candidate attestation whose startup
   head and remote OID both equal `I`. That process alone runs the broad compatible suite, final
   84-nodeid JUnit, exact-head implementation panel, and candidate evidence.
10. After candidate evidence and merge gates pass, merge the implementation PR without changing
    candidate `I`. Fetch canonical main, resolve one exact canonical main OID containing `I`,
    create another clean worktree at that OID, and launch a third new repo-local
    `phase-loop attest --stage canonical-main` process. Only its exact-main-bound artifact can
    close LEGIBLE.

The implementation range must contain no diff at either frozen test path. The implementation
base/head and final canonical main must descend from the original landing and the corrective test
anchor, and both test blobs
must remain identical at the test landing, implementation base, candidate head, and canonical
main. The reducer records the original landing and its two blobs separately; its `tests_landing`
blob-equality anchor is the latest corrective commit. Plan and roadmap bytes at each attesting ref
must match the plan contract recorded for that ref. A
same-branch `base -> tests -> implementation` sequence, a candidate not first pushed, reuse of
the builder process, or evidence from an earlier candidate/main OID fails. No existing test is
migrated by this plan. If integration makes migration unavoidable, planning must be repaired
before implementation: pre-capability/default mode preserves the legacy assertions, forced mode
uses the new assertions, marker-present mode selects those same new assertions automatically,
and the implementation still cannot edit the test or activation branch.

The exact capability-owned inventory is 84 nodeids: 64 in
`test_legible_roadmap_contract.py` (27 status/banner/selection cases, 23 independently identified
assumption-probe cases, 12 manifest scope/registration/malformed-path cases, and 2 catalog cases)
and 20 in `test_legible_evidence.py` (5 chronology cases, 4 PR/ancestry cases, 7
fresh-process/sidecar cases, and 4 activation/JUnit/digest cases). Each file contains a literal,
stable-sorted `LEGIBLE_EXPECTED_NODEIDS_V1` tuple with explicit parameter IDs; collection must
equal the union exactly and the chronology artifact stores its count and SHA-256. Adding,
removing, renaming, deselecting, or newly skipping one nodeid after the tests-only panel is test
contract drift.

Assumption declarations use one dedicated `specs/roadmap-assumption-probes-v10.json` sidecar;
roadmap bytes are not an embedding surface. Its exact grammar is a JSON object containing only
`schema`, `roadmap`, `roadmap_sha256`, and `probes`. `schema` is
`roadmap_assumption_probe.v1`; `roadmap` is `specs/phase-plans-v10.md`;
`roadmap_sha256` is the frontmatter digest of this plan; and `probes` is stable-sorted by `id`.
Each probe object contains exactly `id`, `assumption`, `kind`, `subject`, `expected`,
`source_anchor`, `mutation_id`, and `positive_control_id`. `assumption` is integer `1..5`;
`source_anchor` is a nonempty literal from that numbered assumption and must occur within its
parsed assumption block; IDs and control IDs are nonempty unique strings; `subject` and
`expected` are JSON data consumed only by the selected fixed adapter. Each adapter owns a
closed kind-specific `subject`/`expected` schema, and keys named `command`, `argv`, `shell`,
`cwd`, or `env` are rejected at any depth. Allowed `kind` values are
`github_issue`, `github_pr`, `github_comment`, `github_ref`, `remote_json_field`,
`repo_constant`, `repo_digest`, `release_identity`, `ast_call_predicate`,
`roadmap_predicate`, `manifest_behavior`, and `reviewtruth_fable_transition`.
Unknown/additional keys, unsupported kinds,
duplicate IDs, a roadmap/digest mismatch, missing anchors, arbitrary command fields, or an
unavailable/contradictory required observation are typed fail-loud findings. No roadmap or
sidecar text becomes a command. The complete per-drifting-fact inventory is:

| Probe ID | Independently mutable assertion | Required source and expected observation | Mutation that must fail | Positive control |
|---|---|---|---|---|
| LEGIBLE-A1-PR102 | `Consiliency/spec#102` is merged | GitHub PR state is `MERGED`, with non-null `mergedAt` and merge commit | observe `OPEN` or `CLOSED`-unmerged | current merged payload passes |
| LEGIBLE-A1-I118 | `Consiliency/spec#118` is closed | GitHub issue state is `CLOSED` | observe `OPEN` | current closed payload passes |
| LEGIBLE-A1-PR377 | `Consiliency/agent-harness#377` landed on main | GitHub PR state is `MERGED`; merge commit is reachable from the default-branch head | remove the merge timestamp or return a non-ancestor merge commit | current merged/reachable payload passes |
| LEGIBLE-A1-PIN-TAG | the local contract tag is `v0.2.1` | `phase_loop_runtime.conformance.outside_agent_pin.EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN.contract_git_tag == "v0.2.1"` | change only the tag | current tag passes |
| LEGIBLE-A1-PIN-SHA | the local contract SHA is `b862f977897a7b87c4419680a3e83735d4ff07b0` | `EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN.contract_git_sha` equals all 40 hex characters | change only the SHA, including back to `c1085483…` | current SHA passes |
| LEGIBLE-A1-TAG-DEREF | the tag and SHA identify the same merged spec source | `Consiliency/spec` tag `v0.2.1^{}` dereferences to the local `contract_git_sha` and is reachable from default-branch head | return a different tag target or an unreachable target | current dereference/reachability passes |
| LEGIBLE-A1-SUBMISSION-DIGEST | the submission schema digest is present and current | pinned `submission_schema_sha256` equals SHA-256 of the owned vendored submission-schema bytes | flip one schema byte or the recorded digest | unchanged bytes/digest pass |
| LEGIBLE-A1-VERDICT-DIGEST | the verdict schema digest is present and current | pinned `verdict_schema_sha256` equals SHA-256 of the owned vendored verdict-schema bytes | flip one schema byte or the recorded digest | unchanged bytes/digest pass |
| LEGIBLE-A1-CONFORM-UNGATED | CONFORM is no longer blocked on `spec#118` | v10 dependency/criterion predicates contain no unresolved `spec#118` prerequisite for CONFORM | inject a `spec#118 must close` dependency | current dependency graph passes |
| LEGIBLE-A2-I128 | `Consiliency/governed-pipeline#128` remains open | GitHub issue state is `OPEN` | observe `CLOSED` | current open payload passes |
| LEGIBLE-A2-GP-PIN | governed-pipeline still pins agent-harness `0.5.0` | default-branch `tools/agent-harness.pin.json` has package `phase-loop-runtime`, `expected_version == "0.5.0"`, and `pip_spec == "phase-loop-runtime==0.5.0"` | change any one field independently | current remote JSON passes |
| LEGIBLE-A2-LOCAL-VERSION | agent-harness ships `0.7.13` | `phase-loop-runtime/pyproject.toml` and `phase_loop_runtime.__version__` both equal `0.7.13` | change either surface alone | current equal pair passes |
| LEGIBLE-A2-NO-DEPENDENCY | no v10 phase depends on governed-pipeline#128 resolving | roadmap dependency/criterion predicate finds no closure prerequisite | inject one phase dependency on issue closure | current roadmap passes |
| LEGIBLE-A3-REVIEWTRUTH-TRANSITION | Assumption 3 is in exactly one declared before/after state | fixed `reviewtruth_fable_transition` adapter classifies `pending` or `resolved` from one issue/source/behavior/live-route observation | exercise every inconsistent issue/source/route combination, or make the required live Fable leg unavailable | current pending observation passes; a resolved native-fill fixture with a bound live verdict reaches FULL |
| LEGIBLE-A3-NO-DEGRADED-GATE | a runtime-internal 3-of-4 result cannot satisfy this run's gate | v10 execution policy requires four-vendor exact-digest review and forbids degraded promotion | mutate the policy to authorize 3-of-4 | current no-degraded policy passes |
| LEGIBLE-A3-EC4 | REVIEWTRUTH owns typed FULL/FLOOR-ONLY/BELOW-FLOOR vacancy classification | the `EC-REVIEWTRUTH-4` roadmap predicate contains all three states and the typed unfillable signal | remove one state/signal | current criterion passes |
| LEGIBLE-A3-EC14 | REVIEWTRUTH owns native fill of the Fable vacancy without a TUI adapter | the `EC-REVIEWTRUTH-14` predicate binds the returned native verdict before counting the seat | remove native fill, no-TUI posture, or verdict binding | current criterion passes |
| LEGIBLE-A4-DISCOVERY | the manifest is a live roadmap-discovery input | AST predicate binds `manifest_backed_roadmap` to `_phase_manifest_entries` and that reader to `valid_phase_entries` | remove either call edge | current call chain passes |
| LEGIBLE-A4-PR170 | the per-entry manifest fix from `agent-harness#170` is merged | GitHub PR state is `MERGED`, with non-null `mergedAt` | observe open/closed-unmerged | current merged payload passes |
| LEGIBLE-A4-PER-ENTRY | one malformed manifest row does not hide valid siblings | injected invalid sibling is excluded while the valid v10 entry remains discoverable | restore whole-manifest invalidation | current per-entry behavior passes |
| LEGIBLE-A5-RATIFICATION | the maintainer-ratified `agent-harness#363` decision still says Option B | issue comment `5109553368` by `ViperJuice` has SHA-256 `5c165d83193477de52c5a41018316208e07e56192c9b18c7e9ad1bac45757b4f` and the required decision atoms | mutate the comment digest or either atom | current comment passes |
| LEGIBLE-A5-SHARED-EPOCH | the standing decision is one shared monotonic allocator for every admission kind | v10 Assumption 5 and FABPUB objective/criteria agree on the shared allocator | change either to split/scoped allocation | current roadmap predicates pass |
| LEGIBLE-A5-RETRACTION | publish byte-neutrality is retracted | v10 Assumption 5 and `EC-FABPUB-7` both carry the retraction | reintroduce a neutrality promise or delete either retraction | current roadmap predicates pass |

`reviewtruth_fable_transition` has a closed subject schema containing only repository
`Consiliency/agent-harness`, issue `396`, model `claude-fable-5`, and the Assumption 3 source
anchor; callers cannot supply a command, route, environment, timeout, or expected issue state.
Its fixed adapter reads one live GitHub issue snapshot, then performs the metadata-only
first-party Claude subscription capability probe and one real Fable self-PTY leg with the
existing 600-second activity bound and 1,800-second hard backstop. The currently reachable
`pending` state requires all of: `Consiliency/agent-harness#396` is `OPEN`; a Fable seat
driven under the asserted Claude marker produces no native-fill request and remains
`UNAVAILABLE/tui_adapter_required`; and the external first-party route capability plus live
Fable leg succeeds. The `resolved` classifier contract is exercised through typed fixtures in
LEGIBLE but remains intentionally unreachable through the production adapter until the
maintainer-owned REVIEWTRUTH lane D work recorded on `Consiliency/agent-harness#396` lands; that
lane extends the adapter to consume the runner-captured execution tree. Once landed, `resolved`
requires all of: the issue is `CLOSED` with completed/ratified rather than not-planned
disposition; the execution tree contains the matching native-fill request, verdict-binding, and
seat-count behavior; and binding the real bounded Fable verdict through that path with the other
three reviewing seats reaches FULL. OPEN plus native-fill,
CLOSED plus the old no-fill behavior, CLOSED-not-planned, an unavailable required route, an
unbound verdict, or any other mixed state fails loud. A transition racing the observation may
fail once and pass on a complete rerun; it can neither be silently accepted nor permanently pin
the audit to the planning-time OPEN state. Assumption 3 itself declares both sides of this
transition, so this fixed classification changes no roadmap bytes.

`test_legible_roadmap_contract.py` parameterizes every row so each mutation and positive
control executes independently; tests fail if the declared inventory and test cases differ.
The whole-phase `validate-roadmap --check-assumptions` runs every required live adapter and
prints a stable per-probe verdict/count, not one aggregate verdict per numbered assumption.

### SL-1 — Manifest presence reporting

- **Scope**: Add a deterministic exact HEAD/index/filesystem-scope manifest audit, register the closed eleven historical plans with truthful lifecycle state, and report roadmap status through the frozen accessor.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`, `plans/manifest.json`
- **Interfaces provided**: `ManifestPresenceReport`, `canonical_plan_files`, `unregistered_plan_files`, deterministic historical-plan registration, `plan-manifest check`
- **Interfaces consumed**: `read_roadmap_status`, `LEGIBLE frozen falsifier suite`
- **Parallel-safe**: yes
- **Tasks**:

- test: LEGIBLE-B0 consumes SL-0's frozen manifest tests first and runs `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k manifest -q` before LEGIBLE-B1 starts.
- impl: LEGIBLE-B1 depends on LEGIBLE-B0 and implements the deterministic audit/registration surface; LEGIBLE-B2 then registers only the closed eleven-plan set in `plans/manifest.json`.
- verify: LEGIBLE-B3 depends on LEGIBLE-B2 and runs `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .` and `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k manifest tests/test_phase_loop_plan_manifest.py tests/test_manifest_per_entry_164.py -q`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| LEGIBLE-B0 | test | SL-0 | `phase-loop-runtime/tests/test_legible_roadmap_contract.py` | frozen tests `test_unregistered_plan_files_names_all_eleven_in_stable_order`, `test_register_existing_plan_metadata_is_git_stable`, `test_historical_plan_lifecycle_matrix_is_truthful`, `test_repository_manifest_exactly_covers_execution_scope`, `test_integrated_six_root_tree_reports_28_of_28`, `test_untracked_in_scope_plan_absent_from_manifest_blocks`, `test_index_only_in_scope_plan_absent_from_manifest_blocks`, and canonical-looking malformed/symlink/path-escape controls from LEGIBLE-A0 | `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k manifest -q` |
| LEGIBLE-B1 | impl | LEGIBLE-B0 | `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py` | none; tests remain owned and frozen by SL-0 | implement `canonical_plan_files(repo, tree_oid)` as the stable union of canonical phase-plan paths in the runner-captured `HEAD`, stage-0 index, and bounded direct physical `plans/` scan, preserving source-origin flags in `ManifestPresenceReport`; compare that exact set with unique valid canonical phase-entry paths; add a read-only `python -m phase_loop_runtime.plan_manifest check --repo <repo>` command whose nonzero result names every missing, extra, duplicate, malformed, conflicted-index, symlink, non-regular, or escaping path; add explicit historical registration whose timestamps derive only from the frozen Git evidence below, never filesystem mtime or wall clock; preserve per-entry validation and append/update behavior |
| LEGIBLE-B2 | impl | LEGIBLE-B1 | `plans/manifest.json` | frozen in LEGIBLE-A0 | register the exact eleven paths below using the frozen seven-completed/four-orphaned matrix, stable slug/frontmatter phase/roadmap refs, Git-derived timestamps, and evidence metadata; preserve all already-registered current/root plans and do not auto-register arbitrary discoveries |
| LEGIBLE-B3 | verify | LEGIBLE-B2 | SL-1 owned files | frozen in LEGIBLE-A0 | `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .` and `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k manifest tests/test_phase_loop_plan_manifest.py tests/test_manifest_per_entry_164.py -q` |

The registration set is closed and explicit:

- `plans/phase-plan-v1-task-message-sourcebroker-SOURCEBROKER.md`
- `plans/phase-plan-v6-CTXDOCS.md`
- `plans/phase-plan-v6-CTXFREEZE.md`
- `plans/phase-plan-v6-CTXIMPL.md`
- `plans/phase-plan-v6-CTXRELY.md`
- `plans/phase-plan-v6-CTXVERIFY.md`
- `plans/phase-plan-v7-OACONTRACT.md`
- `plans/phase-plan-v7-OACORE.md`
- `plans/phase-plan-v7-OAMOCK.md`
- `plans/phase-plan-v7-OAREAL.md`
- `plans/phase-plan-v7-OARELEASE.md`

The historical lifecycle/evidence matrix is frozen as follows. `created_at`, lifecycle `at`,
and `updated_at` are normalized UTC committer timestamps read from these exact Git objects;
registration records one terminal reconciliation event and does not invent unsupported
execution history.

| Plans | Terminal status | Git and lifecycle evidence |
|---|---|---|
| `v1-task-message-sourcebroker-SOURCEBROKER` | `completed` | first-add/delivery `bf7d5e0` (`Consiliency/agent-harness#168`); hardening through `c970d7d` (`Consiliency/agent-harness#190`), including `agent-harness#176`, `agent-harness#178`, `agent-harness#180`, and `agent-harness#184`; roadmap banner says DELIVERED |
| `v6-CTXFREEZE` | `completed` | plan `b3d0d72`, execute `9490bdd`, merged release proof `a7b6a4a` (`Consiliency/agent-harness#118`) |
| `v6-CTXIMPL` | `completed` | plan `b122b38`, execute `4b5f3cc`, merged release proof `a7b6a4a` |
| `v6-CTXRELY` | `completed` | plan `6743461`, execute `37008a0`, merged release proof `a7b6a4a` |
| `v6-CTXDOCS` | `completed` | combined plan/execute `b4bd9a0`, merged release proof `a7b6a4a` |
| `v6-CTXVERIFY` | `completed` | plan `e2d5053`, execute `271da13`, merged release proof `a7b6a4a`; the v6 banner binds 27 passing mechanism tests |
| `v7-OAMOCK` | `completed` | merged squash `7f97ea9` and the v7 banner's explicit “genuinely complete” disposition |
| `v7-OACONTRACT`, `v7-OACORE`, `v7-OAREAL`, `v7-OARELEASE` | `orphaned` | created in `7f97ea9`; orphaned at v10 consolidation `6b77dc3` (`Consiliency/agent-harness#375`) with metadata naming `specs/phase-plans-v10.md`, phase `CONFORM`, and the carried unfinished obligation; no `completed` event is permitted |

The check path is observational: it never auto-registers, deletes, or silently ignores a
plan. Registration is a separate explicit operation over the closed list above, leaves an
already-identical entry untouched, and must produce a byte-identical manifest on rerun.
Malformed manifest structure remains a separate fail-closed error. The authoritative plan
scope is frozen as follows:

- Resolve the caller-supplied repository root with `resolve(strict=True)`. Require its physical
  `plans/` child to exist as a real directory, not a symlink, and enumerate only direct children;
  nested directories, `.phase-loop/`, `.git/`, detailed plans, editor/backup files, and any
  path outside this one directory are excluded.
- Collect the union of (a) `git ls-tree -z --name-only <execution-head> -- plans/`, (b)
  `git ls-files -z --stage -- plans/` stage-0 entries, including a path absent from `HEAD` or
  from the working tree, and (c) `os.scandir(plans_dir)` physical entries, including untracked
  and Git-ignored files. Ignored status is not an exclusion: the filesystem arm examines only
  direct-child name/type metadata and never reads plan content. Use NUL-delimited Git output and
  filesystem-safe decoding; do not parse newline-delimited names or follow directory-entry
  symlinks.
- A member is a canonical phase plan only when its repo-relative POSIX path is exactly
  `plans/<basename>`, the basename full-matches the existing anchored `PLAN_RE`, and its physical
  entry, when present, is a regular file under the same resolved `plans/` directory. Union
  duplicate origins into one path and retain the `head|index|filesystem` origin set for
  diagnostics. A staged deletion remains represented by `HEAD`; a true index-only addition
  remains represented by `index`; an untracked regular file remains represented by
  `filesystem`.
- A direct child or Git path with the canonical `phase-plan-` prefix and `.md` suffix that does
  not full-match `PLAN_RE`, an absolute/noncanonical/backslash/`.`/`..` path, a non-stage-0
  conflicted index entry, undecodable name, canonical-looking directory/device/socket, or a
  symlink (including one targeting inside the repo) is a named malformed finding and makes the
  check nonzero. The audit never resolves or reads a symlink target. Manifest entry paths are
  subjected to the same repo-relative/direct-child/full-match checks before equality.

The equality invariant is the exact set assertion
`registered_canonical_paths == canonical_plan_files(execution_head, index, filesystem)` after
both sides pass the malformed-path gate. The report is stable path-sorted and prints each
missing path with its origin flags plus every extra/duplicate/malformed path; the summary is
`canonical=N registered=N unregistered=0`, never compared with a frozen `N`. The mandatory
falsifier creates a regular untracked
`plans/phase-plan-v999-UNTRACKED.md` in a temporary repo without adding it to Git or the
manifest, asserts the file's `lstat`/scope/full-match anchors, and requires the check to exit
nonzero while naming that exact path with origin `filesystem`. Its positive control adds one
valid manifest row and passes. A separate index-only fixture writes a blob directly to a
stage-0 index path absent from both `HEAD` and the physical directory and requires origin
`index` plus the same nonzero missing-path result.

The six concurrent root paths are exactly `plans/phase-plan-v10-LEGIBLE.md`,
`plans/phase-plan-v10-REVIEWTRUTH.md`, `plans/phase-plan-v10-PROOFGATE.md`,
`plans/phase-plan-v10-CONFORM.md`, `plans/phase-plan-v10-FABPUB.md`, and
`plans/phase-plan-v10-HARDEN.md`. They are current-root plans, not historical registration
targets; each is registered when present in any authoritative origin. When all six exist in the
clean execution scope, the required result is
`canonical=28 registered=28 unregistered=0`; a root present in scope but missing from the
manifest is reported, never filtered out. `validate_manifest(...).valid` must also be true.

### SL-2 — agent-harness#347 evidence, verification contract, and docs-catalog rescan

- **Scope**: Populate the inert docs catalog, evolve and document the verification-evidence contract without changing the existing schema-v2 writer or frozen public function/CLI behavior, implement the executable LEGIBLE evidence reducer plus fresh-process runner-owned verification-sidecar stamping/validation, and promote and merge `Consiliency/agent-harness#347` only after exact-head body-ancestry and governance checks pass.
- **Owned files**: `.claude/docs-catalog.json`, `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`, `phase-loop-runtime/src/phase_loop_runtime/docs_freshness.py`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/tests/test_legible_review_repairs.py`, `plans/phase-plan-v10-LEGIBLE.md`
- **Interfaces provided**: `IF-0-LEGIBLE-2`, `docs_catalog_entry_count`, `docs-catalog rescan`, `legible_evidence.v1`, `verification_evidence.v3`, its final-log seal protocol and closed extension registry, `verification_evidence_sidecar.v1`, `agent-harness#347 exact-head merge evidence`
- **Interfaces consumed**: `LEGIBLE frozen falsifier suite`, `ManifestPresenceReport`, `reviewtruth_fable_transition`, `phase-loop attest`, `verification_evidence.v2` (pre-existing), frozen `run_verification` signature (pre-existing)
- **Parallel-safe**: no
- **Tasks**:

- test: LEGIBLE-C0 consumes the SL-0/SL-1 frozen catalog, status-evidence, PR-evidence, chronology, activation/JUnit, fresh-process, runner-sidecar, artifact-digest, contract-document, version-relative v1/v2/v3 inventories, both v2 `operational_exemptions` forms, both corresponding v3-sidecar forms, unknown-version/unknown-field, and public CLI/function compatibility tests first and forces them with `PHASE_LOOP_TDD_EXPECT_LEGIBLE=1` before LEGIBLE-C1 or LEGIBLE-C2 starts; the pre-existing operational-evidence sentinel also runs green unchanged.
- prerequisite test correction: prover-discovered regression tests in `phase-loop-runtime/tests/test_legible_review_repairs.py` originally landed on the target branch before implementation base `B`, skip as one file while the capability module is absent, and execute after the marker is installed. They are not part of the frozen 84-nodeid inventory and do not change either frozen test blob. The C5-discovered `test_attester_distinguishes_original_landing_from_corrective_anchor`, `test_repaired_plan_has_no_stale_owned_set_contract`, `test_merged_pr_transition_rebinds_fresh_candidate_without_mutation`, `test_merged_candidate_dispatches_to_rebind_without_builder_intent`, `test_post_merge_transition_rejects_open_pr_before_staging`, `test_rebind_recovery_preserves_type_and_rejects_crossed_pairing`, `test_candidate_remote_binds_current_delivery_pr`, `test_legible_panel_stages_small_bundle_contents`, and `test_pr_transition_loader_rejects_review_panel_drift` are the later additions to that file; this plan repair adds the file and plan to the exact phase-owned set `O` and binds their resulting `B..P` delta instead of misreporting them as pre-base bytes.
- impl: LEGIBLE-C1 and LEGIBLE-C2 depend on LEGIBLE-C0 and implement catalog rescan, the public contract-document evolution, the C2-available reducer primitives, staged verifier, dormant `phase-loop attest` command/aggregate-assembly framework and final validators, and runner/verification-evidence probe-sidecar binding without changing the public `run_verification` signature or either existing v2 serialization form; the candidate-building process may exercise these changes only as a subprocess test target and may not attest itself. C4/C5/C7 execute that already-frozen command after their merge-dependent inputs exist; C2 does not claim that the complete candidate/canonical-main `legible_evidence.v1` aggregate already exists.
- verify: LEGIBLE-C3 through LEGIBLE-C7 freeze/push the implementation candidate, use fresh exact-head processes for the `Consiliency/agent-harness#347` transition and implementation panel/evidence, merge only after the broad compatible gate, and finally use another fresh process bound to exact canonical main; only C7 may produce the phase-closing verification artifact.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| LEGIBLE-C0 | test | SL-0, SL-1 | `phase-loop-runtime/tests/test_legible_roadmap_contract.py`, `phase-loop-runtime/tests/test_legible_evidence.py` | frozen catalog tests plus `test_status_evidence_rejects_registry_banner_drift_or_path_set_change`, `test_pr_evidence_rejects_non_ancestor_body_sha`, `test_pr_evidence_rejects_head_or_body_change_before_merge`, `test_pr_evidence_requires_merged_result_for_snapshotted_head`, `test_pr_evidence_rejects_unbound_target_integration_delta`, `test_chronology_rejects_non_test_only_commit`, `test_chronology_rejects_same_branch_sequence`, `test_chronology_requires_test_landing_on_target_before_implementation_base`, `test_chronology_rejects_test_path_diff_in_implementation_pr_range`, `test_chronology_rejects_changed_frozen_test_blob`, candidate/main bootstrap-head and process-separation controls, exact manifest/frontmatter plan-digest ancestry, default/RED/final JUnit count/set/status controls, `test_verification_sidecar_runner_captures_bounded_redacted_fable_probe_evidence`, `test_verification_sidecar_runner_rejects_self_reported_fable_probe_evidence`, `test_runner_stamps_legible_sidecar_path_and_digest`, missing/drift/path-escape/oversize sidecar controls, and the contract-document/v1-v2-v3 field-inventory/operational-exemptions/no-sidecar/v3-sidecar/unknown-version/unknown-field/public-compatibility controls frozen by LEGIBLE-A0; the pre-existing operational-evidence nodeid remains outside ownership and must stay green | `cd phase-loop-runtime && PHASE_LOOP_TDD_EXPECT_LEGIBLE=1 PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py tests/test_legible_evidence.py -k "catalog or status_evidence or pr_evidence or chronology or activation or junit or fresh_process or artifact_digest or verification_sidecar or verification_contract or public_compatibility" -q && PYTHONPATH=src python -m pytest tests/test_preflight_verification.py -k operational_evidence_is_recorded_but_not_executed -q` |
| LEGIBLE-C1 | impl | LEGIBLE-C0 | `.claude/docs-catalog.json`, `phase-loop-runtime/src/phase_loop_runtime/docs_freshness.py` | none; tests remain owned and frozen by SL-0 | add deterministic `rescan-catalog` and `check-catalog` module commands, populate repo-owned document entries including the owned verification-evidence contract document, and make empty mean count zero; do not infer or catalog client-owned documents while `Consiliency/agent-harness#367` is unresolved |
| LEGIBLE-C2 | impl | LEGIBLE-C0 | `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/tests/test_legible_review_repairs.py`, `plans/phase-plan-v10-LEGIBLE.md` | the nine C5 chronology/rebind/delivery tests named above; the two SL-0 test files remain frozen | update the public contract document and implement strict version-relative schema parsing, the closed registered-extension namespace interface, coherent roadmap-status collection/revalidation, TDD activation/JUnit and exact-digest chronology collection/validation helpers, phase-authored versus exact target-integration partition validators, implementation-PR test-path range rejection, bootstrap identity helpers, PR snapshot/finalization validators, artifact SHA-256 helpers, the dormant repo-local `phase-loop attest` command/aggregate-assembly framework and final validators, and staged `python -m phase_loop_runtime.legible_evidence verify`; preserve the exact public `run_verification(repo, run_dir, commands, suite_command, env_refresh, timeout_s, operational_exemptions=None, python_pin=None, phase_alias=None) -> VerificationResult` signature, exact nine-field v2 output when exemptions are absent/empty, exact ten-field v2 output when they are nonempty, and the value/return behavior required by the existing preflight test; have the runner invoke/capture the fixed `reviewtruth_fable_transition` adapter rather than accepting executor-authored JSON; bind that bounded probe/pointer record through the LEGIBLE-owned namespace, re-resolve/re-hash it on validation, and reject unsupported top-level/extension versions, unregistered namespaces, fields outside the selected version's allowed inventory, missing/path-escaping/symlinked/oversized, digest-drift, invalid stage/head/bootstrap/token binding, and self-reported/raw-probe evidence. C2 implements and freezes the command and assembly/validation machinery but does not claim the merge-dependent aggregate, implementation panel, candidate/main provenance, or phase-closing evidence: C4/C5/C7 execute that machinery and own those records after `M`, `I`, and canonical main exist. Install `LEGIBLE_CAPABILITY_VERSION = "legible.v1"` only after SL-0, SL-1, C1, and C2 are complete |
| LEGIBLE-C3 | operational | LEGIBLE-C1, LEGIBLE-C2 | committed phase-authored candidate `P` and its remote branch | frozen chronology, activation, scope, and fresh-process falsifiers | require the capability marker and every production surface to be present; run the broad candidate-compatible gate as subprocesses; commit all exact phase-owned changes without either frozen test path or the frozen `agent-harness#347` integration path; push `P`, require remote branch OID equals local `HEAD`, record builder run/process identity, and return `awaiting_phase_closeout` without treating same-process verification as evidence |
| LEGIBLE-C4 | operational | LEGIBLE-C3 | external `Consiliency/agent-harness#347` state and runner-owned candidate-transition evidence | all four frozen PR-evidence falsifiers, including exact refresh-base/merge-base/refreshed-head/body/refresh-parent/net-path/comment-only/blob/result binding, are consumed without modification | from a new clean worktree at pushed phase-authored candidate `P`, launch fresh repo-local `phase-loop attest --stage candidate`; snapshot exact server merge-time base `B`, exact `H`, body, commit table, checks/reviews, paths/blobs, and `parents(H) == [H0, B0]`; require `B` equals the implementation base and fetched target head, descends from exact refresh base `B0`, contains the tests-only landing, and retains `B0`'s external preimage; revalidate singleton comment-only `B0..H` plus exact `T_B0H`/`R`, then require a private-index merge from merge base `B0` and tips `[B, H]` to be clean and yield `T_BH` with `changed(B, T_BH) == E` and result blob `R`; merge with merge-commit method and finalize server merge `M` only when the PR remains bound to the snapshot, `parents(M) == [B, H]`, `M^{tree} == T_BH`, and `B..M` is exactly the frozen path transition ending at `R`; no handwritten JSON, builder-process substitute, post-snapshot base advancement, squash/rebase merge, body/head/parent/path/blob drift, or phase-author refresh is allowed. If the exact PR is already `MERGED` before this candidate exists, a separate `transition_rebound` producer may bind immutable `M` to current `P` only after independently re-proving the same frozen snapshot, ancestry, body/check/review, singleton-path, semantic-token, private-index tree, and refreshed-result-blob facts and obtaining a fresh unanimous four-seat exact-`P` transition panel; that producer performs no push or PR mutation, records `Consiliency/agent-harness#347` as the merge publisher, refuses any existing mismatched builder transition or intent, and leaves every downstream `head == P` equality check unchanged |
| LEGIBLE-C5 | operational | LEGIBLE-C4 | exact phase-authored candidate `P`, server merge `M`, two-parent target-integration merge `I`, and `.phase-loop/runs/<run-id>/legible-operational-evidence.json` | frozen exact-head, external-delta partition, process-boundary, broad-suite, panel, JUnit, and sidecar falsifiers | fetch target `M`; from unchanged `P`, create runner-controlled no-conflict target-integration merge `I` with ordered parents `[P, M]` and tree equal to the private-index recomputation from merge base `B` and tips `[P, M]`; require `P..I` to be exactly the frozen `agent-harness#347` path transition with result blob `R`, not the raw `H0` blob, and set final candidate equal to `I`; push `I`, rerun the broad compatible gate, then launch a different fresh clean-worktree `phase-loop attest --stage candidate` process whose startup head/imported runtime blobs/remote OID equal `I`; after that process runs the implementation panel and writes the fresh v2 verification artifact, its runner coordinator calls `_finalize_legible_operational_evidence` with only fixed-collector records to seal, validate, and bind the candidate aggregate |
| LEGIBLE-C6 | operational | LEGIBLE-C5, mandatory exact-head implementation panel | implementation PR state | frozen merge-gate and exact-candidate evidence | require the full candidate gate and panel to bind still-current pushed integration candidate `I`, confirm required checks/reviews, and merge the implementation PR without head/body drift or any commit after `I`; no suite subset beyond the explicitly deferred canonical-main evidence wrapper is permitted |
| LEGIBLE-C7 | verify | LEGIBLE-C6 | canonical main plus runner-owned metadata evidence | all 84 frozen nodeids and all pre-existing compatible tests | fetch canonical main, require one exact OID containing final candidate `I`, launch another fresh repo-local `phase-loop attest --stage canonical-main` process from a clean worktree at that OID, run every Verification command and the broad suite, re-prove the phase/external delta partition, require final JUnit `84 passed / 0 failed / 0 errors / 0 skipped`, then call `_finalize_legible_operational_evidence` to seal, validate, and bind the exact-main aggregate into `verification.json` |

The verification-evidence evolution is contract-first, explicit, and backward compatible:

- Let `B` be the exact nine required top-level fields `schema_version`, `run_id`,
  `phase_alias`, `commands`, `env_refresh`, `suite`, `started_at`, `finished_at`, and
  `log_sha256`. The version-relative top-level inventories are closed and noncontradictory:
  schema v1 is read-only legacy with required set `B` and no optional top-level fields; schema v2
  has required set `B` plus the optional top-level field `operational_exemptions`; schema v3 has
  required set `B ∪ {extensions}` plus the same optional `operational_exemptions`. Therefore a
  valid v2 artifact has exactly nine fields when exemptions are absent or empty and exactly ten
  when a nonempty exemption list is serialized. A valid v3 artifact has exactly ten fields
  without exemptions and exactly eleven with them. A field outside the selected version's
  required-plus-optional inventory is rejected; `operational_exemptions` is not an unknown v2/v3
  addition.
- The public
  `run_verification(repo, run_dir, commands, suite_command, env_refresh, timeout_s, operational_exemptions=None, python_pin=None, phase_alias=None) -> VerificationResult`
  signature does not gain a sidecar parameter. Its current v2 writer behavior is frozen:
  absent or empty exemptions omit `operational_exemptions`, while a nonempty list is copied to
  that top-level field, returned on `VerificationResult`, covered by the existing artifact seal,
  recorded for operator inspection, and never executed as a verification command. Both forms
  preserve current phase-alias precedence, failure/non-raise behavior, and seal/log validation.
  Sidecar omission always leaves either form at schema v2; it never silently selects v3.
- A sidecar-bearing attestation uses a new internal post-run binder after `run_verification`
  returns. The binder accepts only the just-written, successfully validated v2 artifact and
  runner-owned sidecar metadata, then atomically upgrades the artifact to schema version 3 and
  re-seals the sibling log. It changes `schema_version` from 2 to 3 and preserves every v2 JSON
  value exactly except the derived `log_sha256`, including a present
  `operational_exemptions` list, then adds the required `extensions` object. The generic v3
  envelope owns a closed, versioned namespace registry: at the LEGIBLE landing the sole
  registered key is `phase_loop_runtime.legible_evidence`; the registry reserves
  `phase_loop_runtime.proofgate_evidence` to downstream PROOFGATE, and no other phase may claim
  either key. The LEGIBLE value is a
  `verification_evidence_sidecar.v1` record containing exactly `schema`, `path`, `byte_length`,
  `sha256`, `stage`, `expected_head`, `bootstrap_head`, and `process_start_token`. The binder
  removes the prior final seal trailer, canonicalizes the v3 payload with derived `log_sha256`
  omitted, appends exactly one final v3 seal trailer for that payload, computes the replacement
  `log_sha256` over the complete final v3-sealed log bytes, writes that value into the final
  artifact, and validates the artifact/log pair before the atomic replacement. Thus the new
  `log_sha256` authenticates the final re-sealed log rather than an intermediate log. The binder
  uses same-directory temporary files plus atomic replacements; interruption may leave a typed
  integrity mismatch but may never yield a false pass. No public CLI or function caller can
  inject an extension through a new argument.
- New readers accept schema versions 1, 2, and 3. Existing v1/v2 evidence remains readable with
  its present defaults, result shape, seal/unsealed split, exit reduction, redaction, and
  diagnostics behavior. New v2/v3 readers accept and preserve the optional exemption list on the
  existing `VerificationResult.operational_exemptions` field; absence retains the current empty
  result. Existing v2 readers remain compatible with all no-sidecar output, including the current
  ten-field operational-evidence artifact, because that output remains v2; when intentionally
  given a v3 artifact, a legacy reader rejects the unsupported version rather than misreading it.
  A new plan-aware reader requires exactly the registered namespace set declared by the
  producing phase contract. For LEGIBLE that is the LEGIBLE namespace and sidecar-v1 field set;
  it reopens and rehashes the referenced sidecar and validates its stage/head/token binding
  before returning `ok`. Generic readers accept any registry-known namespace with its registered
  closed record schema, so adding PROOFGATE's reserved namespace downstream does not invalidate
  LEGIBLE-only artifacts or tests; plan-aware LEGIBLE validation never requires the PROOFGATE
  namespace.
- Unknown top-level schema versions, unregistered v3 extension namespaces, incompatible registered
  extension
  schema versions, missing required fields, and fields outside the version-relative inventories
  fail closed. The loader keeps its public call signature and raises a typed `ValueError`
  subclass carrying the stable contract code; `validate_verification_artifact` keeps its public
  signature and converts that failure to `VerificationArtifactValidation` with
  `unsupported_schema_version`, `unsupported_extension_namespace`, or
  `unsupported_extension_version` as appropriate. Structurally malformed known versions,
  including a v1 `operational_exemptions`, a v2 `extensions`, a v3 missing `extensions`, or any
  other per-version additional field, remain `malformed_artifact`. These new typed outcomes apply
  only to the new/unsupported contract cases; valid v1/v2 verdict codes and CLI rendering remain
  unchanged.

LEGIBLE-C0 freezes these rules before C2 may edit either implementation or contract documentation.
The frozen tests assert the exact contract-document field/signature tables and the following
matrix without changing the 84-nodeid inventory:

| Input to the unchanged public writer / internal binder | Required top-level result |
|---|---|
| no or empty `operational_exemptions`; no sidecar | schema v2, exactly `B` |
| nonempty `operational_exemptions`; no sidecar | schema v2, exactly `B ∪ {operational_exemptions}`, with the list preserved and not executed |
| no or empty `operational_exemptions`; valid sidecar | schema v3, exactly `B ∪ {extensions}` |
| nonempty `operational_exemptions`; valid sidecar | schema v3, exactly `B ∪ {operational_exemptions, extensions}`, with the list preserved through bind/load/validate |

The tests also round-trip sealed and unsealed legacy v1/v2 fixtures, independently reject every
per-version additional-field case plus unknown top-level and extension versions, and inspect the
public `run_verification`, loader, validator, and `phase-loop` CLI call surfaces. The already
existing
`phase-loop-runtime/tests/test_preflight_verification.py::PreflightVerificationTest::test_operational_evidence_is_recorded_but_not_executed`
is an immutable compatibility sentinel outside LEGIBLE's two test-owned paths and 84-nodeid
activation inventory; it must pass on the pre-implementation base, candidate, and canonical main.
The document change and implementation must land together only after the new assertions have been
paneled RED; prose added after implementation cannot satisfy the gate.

The v2-to-v3 preservation oracle removes exactly `schema_version` and `log_sha256` from the
before/after comparison and requires canonical equality for every remaining JSON value. A
separate fresh-reader oracle independently removes/replaces the final trailer, recomputes the
canonical v3 payload digest and complete final-log SHA-256, and requires both to match the
written artifact. It also mutates the final trailer and proves `log_sha256` fails, preventing an
intermediate-log hash or copied v2 hash from satisfying the gate. Namespace tests accept only
registry-enumerated closed records, reject every unregistered key and every extra field within a
registered record, and prove that registering PROOFGATE's reserved namespace later leaves a
LEGIBLE-only artifact and LEGIBLE plan-aware validation compatible.

The catalog rescan is stable-sorted and idempotent, stores repo-relative paths only, and never
turns an empty catalog into a positive count. It preserves the existing permissive read behavior
for absent/malformed catalogs while exposing an explicit check command that fails when the
tracked catalog is empty, stale, duplicated, or disagrees with the current rescan.

The final operational reducer owns schema `legible_evidence.v1` at
`.phase-loop/runs/<run-id>/legible-operational-evidence.json`. Its assembly is explicitly staged:
C2 provides the validators and evidence primitives whose inputs already exist, while ordinary
phase execution binds only the bounded `roadmap_assumption_probe.v1` Fable transition record.
C4 records the exact server-side PR transition; C5, after `M` and `I` exist, passes the fixed
collector records to the committed runner-owned `_finalize_legible_operational_evidence`
entrypoint, which assembles and atomically seals the complete candidate aggregate, semantically
validates it, and binds its path/length/digest/stage/head/process token into the fresh v2
verification artifact as the LEGIBLE v3 extension. C7 uses the same entrypoint for the
corresponding canonical-main aggregate. No C2 command may claim EC-LEGIBLE-0 or EC-LEGIBLE-4 from the staged
roadmap-status verifier or probe sidecar alone. The final C5/C7 aggregate produces and validates:

When `Consiliency/agent-harness#347` is already merged, C4 does not replay or claim its publish.
The runner creates a separately typed `transition_rebound` record under the current builder run
only after it re-derives immutable `M` and its exact `[B, H]` parents/tree/path/result blob from
Git and the live merged snapshot, proves current `P` descends from `B`, and runs a new unanimous
four-seat transition panel bound to `P`. Existing transition or intent evidence for that builder
is never rewritten or silently rebound, and C5's existing candidate-head equality remains the
acceptance boundary. If the process restarts after persisting the rebind intent, recovery must
preserve the `transition_rebound` type, producer, publisher, and expected-tree provenance; the
loader rejects either lawful intent type paired with the other transition type.

Both C4 transition producers use a runner-authored review brief scoped only to the exact
`Consiliency/agent-harness#347` transition slice and explicitly reserve whole-candidate
implementation review and verification for C5/C6. The transition panel binds that brief by
repo-relative path and SHA-256 and revalidates its scope and bytes on every load; the C5
implementation panel retains the ordinary whole-feature review brief. The transition intent and
sealed/rebound transition also bind the non-usable `legible_c4_early_prover.v1` receipt by path and
SHA-256. Loaders require its exact head, `role=early_prover`, `binding_prover=false`, and
`usable=false`, and require its recorded bundle digest to equal the SHA-256 of the panel-reviewed
bundle prefix before the unique `Early prover evidence` section. This preserves the truthful
pre-append prover input while the final panel digest binds the appended receipt disclosure. C5 and
C7 include the receipt, final transition bundle, and scoped brief in their artifact inventory; a
missing, symlinked, altered, schema/head/role-drifted, usable/binding, prefix-mismatched, or unbound
attachment fails closed.

- `roadmap_status`: registry path/length/SHA-256, selected path, Git-tracked path-set digest, and
  one stable path-sorted record for every tracked roadmap containing the registry status, parsed
  banner status, exact primary-declaration line number, and declaration SHA-256. Collection and
  `verify --head HEAD` both call `validate_roadmap_status_coherence(required=True)`; mismatched
  status, changed path coverage, malformed/ambiguous/missing declaration, or digest drift fails.
- `chronology`: pre-implementation base, tests-only source and canonical landing commits,
  implementation/target-integration base `B`, phase-authored candidate `P`, server-recorded
  `agent-harness#347` head `H`, server merge `M`, two-parent target-integration merge/final
  candidate `I`, every pushed candidate head, exact canonical-main head, target/default branch
  name, exact phase-authored `B..P`, target PR `B..M`, integration `P..I`, combined `B..I`, and
  implementation PR ranges, exact two test paths, plan and roadmap paths/digests, blob OIDs and
  SHA-256 values at every lifecycle ref, asserted mutation IDs, RED/default/final commands and
  exits, raw-log/JUnit digests and parsed counts/status sets, literal nodeid inventory digest,
  test-contract and implementation-panel subject digests/verdicts, remote-ref equality,
  ordered-parent identities, recomputed integration-tree identity, target-landing ancestry,
  phase/external path partition, implementation-merge identity, and canonical-main ancestry.
- `process_attestations`: builder, `agent-harness#347` transition, final-candidate, and
  canonical-main run IDs plus unguessable runner start tokens; process IDs/start times; repo and
  worktree realpaths; requested and observed stage; startup `HEAD`; expected head; fetched remote
  ref/OID; `sys.executable`; repo-local `PYTHONPATH`; loaded `runner.py`,
  `verification_evidence.py`, `cli.py`, and `legible_evidence.py` paths, blob OIDs, lengths, and
  SHA-256 values; the public verification-evidence contract document path/blob/length/SHA-256;
  plan/manifest/frontmatter validation; worktree cleanliness; parent/builder identity; suite,
  JUnit, panel, and sidecar digests. Candidate attestations require startup
  `HEAD == expected candidate == remote branch OID`; canonical-main requires startup
  `HEAD == expected head == fetched canonical main`, with the final candidate as an ancestor.
  The attesting process start token must differ from the builder's and from every earlier-stage
  token.
- `test_execution`: exact frozen 84-nodeid set/count/digest and three structured observations:
  tests-only default (`passed command`, 84 skipped, zero failure/error), forced pre-implementation
  RED (exit 1, 84 intended failures, zero skip/error, one successful asserted injection anchor
  and `LEGIBLE_RED::<mutation-id>` failure per nodeid), and final marker-active candidate/main
  (`84 passed`, zero failure/error/skip). It records marker absence/presence at each ref and
  rejects xfail/xpass, collection/import errors, deselection, missing/extra nodeids, or a skip
  reason outside the one test-owned guard.
- `pull_request`: repository/number, base ref, exact refresh base OID `B0`, exact pre-merge server
  base OID `B`, exact refreshed head OID `H`, ordered refresh parents `[H0, B0]`, PR-body
  SHA-256, exact parsed commit-table SHAs, one ancestry verdict per SHA, checks/review readiness,
  exact net `B0..H` changed-path set and comment-token equality, and per-path
  status/mode/preimage/refreshed-result Git blob OIDs, byte lengths, and SHA-256 values. It also
  records `B0` ancestry and external-preimage equality at `B`, the private-index `T_B0H`/`R` and
  `T_BH` recomputations, unchanged-body/head/base proof, post-merge state, `mergedAt`, server
  merge commit OID `M`, ordered merge parents `[B, H]`, `M^{tree} == T_BH`, and post-merge head
  equality.
- `target_integration`: phase-authored candidate `P`, server merge `M`, integration commit `I`,
  ordered parents `[P, M]`, refresh base `B0`, merge-time base `B`, all independently recomputed
  private-index clean merge tree OIDs, exact `B0..H`, `B..P`, `B..M`, `P..I`, and `B..I` path
  sets, and the one frozen external path's mode/blob/length/SHA-256 values at `B0`, `B`, `P`,
  refreshed `H`, `M`, and `I`, including derived result `R`. This is an identity-bound
  `Consiliency/agent-harness#347` transition record, not an unowned-path allowlist.
- `assumption_probes`: runner-captured execution-head OID and one bounded record per probe. The
  Fable transition record contains only probe ID, classified state, issue state/reason and
  response digest, source/behavior booleans and blob digests, fixed route/model, capability
  verdict, live-leg status/final-verdict token, elapsed milliseconds, configured activity/hard
  bounds, response byte length, and response SHA-256.
- `artifacts`: repo-relative path, byte length, and SHA-256 for the status registry, tests-only
  default JUnit, raw RED log/JUnit, final candidate/main JUnit, both panel records, frozen test
  blobs/nodeid inventory, PR-body snapshot, process-bootstrap records, broad-suite logs, and
  every referenced evidence attachment.

The collector reads committed blobs with Git object APIs rather than trusting working-tree
bytes. It proves the canonical tests-only landing's first-parent diff changed exactly the two
frozen test paths; the fetched target/default branch contained that landing before recorded
implementation/target base `B`; exact refresh base
`B0 == 648be2f68d6804ecdc4046bb7d4f5ee81a90c356` precedes that tests-only landing;
refreshed target PR head `H` has exact parents `[H0, B0]`; and phase-authored candidate `P`,
server merge `M`, integration candidate `I`, and canonical main have the exact ancestry and
ordered parents above. `B` must descend from `B0`, but the target cannot advance between the
execution-time `B` snapshot and server merge: server PR base, implementation base, and fetched
target head must all be the same exact recorded `B`.

The reducer partitions chronology instead of treating every `B..I` path as phase-owned. Let
`O` be the exact 18-item manifest/lane-owned set and let `E` be the singleton frozen
`Consiliency/agent-harness#347` path above. The canonical `O` digest is SHA-256
`ad11f462c732dabae8a7f51e61a3b229dbb1a8f45954c266d14cb9547cfdd240` over the
UTF-8, bytewise path-sorted list with one repo-relative path plus `\n` per record. The plan
frontmatter count/digest, parsed lane union, and manifest list/count/digest must all equal that
same material. The reducer requires `O ∩ E = ∅` and
`changed(B, P) ⊆ O`, with both frozen test paths and `E` absent. The separately server-bound
external record requires exact PR/refresh-base/head/body identities,
`parents(H) == [H0, B0]`, every body-table SHA to be an ancestor of `H`, and
`changed(B0, H) == E`; the permitted merge-parent ancestry from `main` therefore cannot broaden
the refreshed net PR delta. Execution-time server base `B` must descend from `B0`, contain the
tests-only landing, and retain `B0`'s external-path mode/blob/length/SHA-256. For `E`, `B0`, `B`,
and `P` must retain mode `100644` and the frozen `dcec427…` identity, while refreshed `H` must
have mode `100644` and the frozen `29c0e986…` identity. A Python-token comparison of the exact
`B0` and `H` blobs drops
only `ENCODING`, `COMMENT`, and comment-only `NL` tokens and requires every remaining
`(token_type, token_string)` pair to be identical, proving the `33`-addition/`1`-deletion net
change is comment-only rather than a semantic source edit.

For each clean merge recomputation, the reducer uses a private temporary `GIT_INDEX_FILE`, runs
`git read-tree -i -m <merge-base> <ours> <theirs>`, requires `git ls-files -u` to be empty, and
records `git write-tree`; it never changes the worktree or repository index. Applied first with
`<merge-base>=B0`, `<ours>=B0`, and `<theirs>=H`, this yields exact
`T_B0H == H^{tree}` and defines `R = blob(T_B0H, E) == 29c0e986…`. Applied next with
`<merge-base>=B0`, `<ours>=B`, and `<theirs>=H`, it yields server result tree `T_BH`; the reducer
requires `changed(B, T_BH) == E` and `blob(T_BH, E) == R`, proving every post-refresh target
change survives. Server merge `M` must then have ordered parents `[B, H]`,
`M^{tree} == T_BH`, `changed(B, M) == E`, and blob `R` at `E`. Applied finally with
`<merge-base>=B`, `<ours>=P`, and `<theirs>=M`, it yields the required `I^{tree}`; integration
merge `I` must have parents `[P, M]`, final candidate exactly `I`, `changed(P, I) == E`,
`blob(I, E) == R`, and `changed(B, I) == changed(B, P) ∪ E`. After subtracting this exact
identity-bound delta, every remaining candidate path must be in `O`.

No result is accepted from the obsolete raw `H0` blob or from a phase-authored reconstruction.
No commit may follow `I` before the implementation merge. Thus neither the phase author nor a
manual conflict resolution can modify, recreate, or launder the external path. Any extra
`B0..H`, `B..M`, or `P..I` path; semantic-token, body, ancestry, parent, tree, mode, blob, digest,
or result drift; or any external delta other than this exact refreshed
`Consiliency/agent-harness#347` contribution fails closed and requires plan repair. `E` is never
added to lane ownership or generalized into an unowned-path allowlist.

The original two-file landing and its blob inventory are recorded independently. Both test blobs
and the literal nodeid inventory remain byte-identical at the corrective `tests_landing`, `B`,
`P`, `I`, and canonical main. The plan and roadmap at each attesting ref match that ref's
manifest/frontmatter digests; base `B` retains its predecessor contract while repaired `P`, `I`,
and canonical main carry the repaired contract. The collector parses the LEGIBLE manifest entry's
`lifecycle[0].metadata.legible_plan_contract`, requires its `plan_sha256`, exact 18-item
`owned_paths`, `owned_paths_count`, `owned_paths_sha256`, two `test_paths`, activation env,
capability marker, expected-nodeid count, and lifecycle literal to agree with the live plan
frontmatter/lane IR, then requires the
implementation-panel record to bind that same plan digest and exact partition. A same-branch
sequence, unlanded tests, test/activation edits, marker-present tests-only commit, stale plan
digest, unpushed candidate, phase-owned/integration-delta overlap, or earlier-head artifact fails
even when local ancestry otherwise looks plausible.

`phase-loop attest` is implemented and tested in A1/C2 before C3 freezes and pushes every
phase-owned production surface. It is executed only as a C4/C5/C7 runner attestation work unit
that never edits its clean attesting worktree, not an executor closeout field. C4's separately typed runner-owned transition may merge
the exact external PR only after its pre-merge snapshot passes, and C5 creates `I` before its
fresh attestation starts; neither operation permits the attester or phase author to edit the
external path. The caller supplies `--stage candidate|canonical-main`, `--expected-head`, and the
prior builder/candidate run identity. Before importing any phase-owned attestation helper, the
fresh CLI process resolves the clean repo/worktree and exact `HEAD`, requires the expected
40-hex commit, snapshots its runner start token, then imports only from that worktree's
`phase-loop-runtime/src`; it rejects installed-runtime, different-worktree, dirty-tree, remote
OID, or loaded-module blob drift. Candidate stage runs the full broad compatible suite and every
Verification command except the one operational canonical-main wrapper whose precondition cannot
exist before landing, validates the 84-nodeid zero-skip JUnit, performs the exact-head mandatory
implementation panel, invokes the fixed Fable adapter, and seals candidate evidence. Canonical
main stage re-runs the complete broad suite and all wrappers, requires the candidate and
`Consiliency/agent-harness#347` merge ancestry, and seals a new exact-main artifact. Neither stage
may reuse a builder/earlier-stage token or accept a sidecar copied from another run directory.

The fresh phase-loop runner owns live-probe capture, implementation-panel invocation, and final
binding rather than trusting a reducer command's exit or any executor-authored availability
claim. It invokes the fixed Fable adapter with no caller-supplied executable fields, caps retained
response metadata at 64 KiB and the serialized probe record at 16 KiB, and writes only the typed
metadata above. Raw auth JSON, account/subscription identity, prompt/body text, provider
transcript, stdout/stderr, environment values, credentials, and provider payloads are never
retained. Missing, over-bound, unredacted, handwritten, copied, same-process, or injected probe
evidence fails. After all verification commands return and before it seals `verification.json`,
the freshly loaded `runner.py` parses the required sidecar declaration below, resolves the
`<run-id>` token to its own runner-owned run directory, rejects
absolute/escaping/symlinked paths, requires the sidecar to exist, and passes its repo-relative
path, byte length, schema, SHA-256, stage, expected head, bootstrap head, and process start token
to the internal post-run binder, never to the frozen public `run_verification` signature. The
freshly loaded `verification_evidence.py` validates the just-written v2 artifact, upgrades only
that sidecar-bearing artifact to v3, writes those values under
`extensions.phase_loop_runtime.legible_evidence` as the separately versioned
`verification_evidence_sidecar.v1` record, and replaces the seal/log digest so the extension is
covered by whole-artifact integrity.
The fresh operational attester then reopens the sidecar, revalidates bootstrap/module blobs and
head/plan/manifest/JUnit ancestry available at that stage, requires the recorded schema/length/path/digest/stage/head/token
to match, and fails on missing or drifted bytes. Prose, a handwritten record, builder-process
verification, an unbound green command result, the planning-time snapshot above, or a green
check without chronology/merged-state/ancestry assertions satisfies neither EC-LEGIBLE-0 nor
EC-LEGIBLE-4. The frozen generic `validate_verification_artifact_for_plan(path,
required_namespaces)` compatibility surface has no repository argument and may validate a copied
sealed envelope outside `.phase-loop`; that compatibility result is not operational attestation
evidence and cannot satisfy either criterion.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- execute: executor=`claude`, model=`claude-sonnet-5`, effort=`high`, work-unit=`lane_execute`, unsupported=`inherit_default`, inherit-default=`true`, reason=`LEGIBLE is assigned to one whole-phase Claude Sonnet 5 implementation author`

## Execution Notes

- Policy precedence is CLI/operator override, this phase plan, roadmap policy, `Dispatch Hints`,
  then registry defaults. Silent executor/model/effort downgrade is forbidden unless an explicit
  fallback or declared default inheritance applies. LEGIBLE's implementation assignment is one
  whole-phase `executor=claude`, `model=claude-sonnet-5`, `effort=high` author; every
  implementation lane and repair remains under that author vendor, and the coordinator records
  the assignment explicitly.
- Before LEGIBLE-A0, hash this exact plan and re-panel its changed digest with exactly the
  roadmap-required four reviewing seats: Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5.
  Fable 5 and GPT-5.6 Sol are mandatory reviewing seats; any unavailable, errored, empty, capped,
  refused, or timed-out mandatory leg blocks dispatch. The panel is by-reference: each leg
  receives an immutable staged bundle path or `context_refs` naming the exact plan, roadmap,
  manifest record, cited implementation, cited existing test, and their digests, and must open
  those referenced bytes rather than substitute pasted prose or a different checkout. Re-panel
  every changed digest.
- Keep both runtime schedulers off as required by the v10 roadmap: launch with
  `--phase-scheduler off --lane-scheduler off`. The lane DAG records ownership and ordering but
  does not authorize scheduler fanout or cross-vendor work-unit rotation. Any explicitly
  authorized same-vendor native workers remain under the one Claude Sonnet 5 author policy and
  use disjoint isolated worktrees; no two workers may write the same path.
- LEGIBLE-A0 is a true test-first boundary, not merely table order. Preserve the tests-only
  default-CI JUnit, forced raw RED log/JUnit, asserted injection anchors, exact nodeid-set digest,
  panel verdict, canonical target landing, implementation base/candidate/main heads, and both
  frozen test blob identities in `legible_evidence.v1`; the fresh-process verification artifact
  binds that record by digest. The reducer blocks unless the tests-only landing was first present
  on the target/default branch before implementation/target base `B`, phase-authored `B..P`
  contains only frozen owned paths, combined implementation range `B..I` excludes both test
  paths and differs from `B..P` only by the exact target-integration delta, the marker was absent
  at the landing and present at the candidate, all lifecycle refs retain the frozen tests, and
  the three JUnit observations have exactly the required 84-nodeid status sets.
- Ordinary CI stays GREEN by default on the tests-only landing; forced activation supplies the
  asserted pre-implementation RED evidence. There is no `xfail`, `xpass`, import failure, or
  collection failure escape hatch.
- LEGIBLE-A2 is deliberately not a whole-phase gate. It may green only the status, selection,
  assumption, and legacy-suite behavior SL-0 owns. The manifest falsifiers stay unsatisfied until
  LEGIBLE-B0/B1/B2, and the catalog, status-evidence, chronology, PR-evidence, fresh-runner-sidecar,
  and artifact-digest falsifiers stay unsatisfied until LEGIBLE-C0/C1/C2. The builder run may
  execute subprocess tests but cannot attest; only the fresh C4 transition and C5
  final-candidate processes can clear pre-merge evidence, and only the fresh C7 canonical-main
  process runs both frozen files and every final wrapper as phase-closing evidence.
- SL-1 may proceed after SL-0. SL-2 may proceed only after both SL-0 and SL-1; it consumes the
  manifest report and must not be described or scheduled as ready after SL-0 alone. SL-2 is also
  operationally serialized because it changes external PR state. Re-read live
  `Consiliency/agent-harness#347` and `Consiliency/agent-harness#367`; never rely on this plan's
  point-in-time GitHub snapshot.
- The transition and final-candidate commands are frozen to fresh repo-local phase-loop
  processes. C4 starts at phase-authored `P` with
  `PYTHONPATH=<candidate-worktree>/phase-loop-runtime/src <candidate-python> -m phase_loop_runtime.cli attest --repo <candidate-worktree> --roadmap specs/phase-plans-v10.md --phase LEGIBLE --stage candidate --expected-head <phase-authored-P-oid> --builder-run-id <builder-run-id>`.
  C5 uses a different clean worktree/process at integrated final candidate `I`, the same command
  with `--expected-head <integration-I-oid>`, and the C4 transition run identity. After the
  implementation merge, the canonical command uses a third clean worktree/process and replaces
  stage/head with `--stage canonical-main --expected-head <fetched-canonical-main-oid>
  --candidate-head <integration-I-oid>`.
  The command implementation rejects a module resolved outside the named worktree and records
  its fresh process token before importing phase-owned runner/evidence modules.
- Candidate implementation-panel and merge gates run the frontmatter
  `automation.suite_command`, every pre-existing compatible test, all 84 marker-active LEGIBLE
  nodeids, catalog/status/manifest/evidence commands, and `git diff --check`. The only pre-merge
  exclusion is the operational `canonical-main` attestation wrapper, because its asserted
  canonical-main OID and merge ancestry do not exist before landing; no unit test, broad-suite
  family, cleanroom gate, or candidate-stage evidence command may be filtered out. Candidate and
  canonical-main panels use immutable by-reference bundles bound to their exact heads and require
  each reviewing leg to open the referenced files. C7 runs the deferred wrapper plus the same
  broad suite again.
- `Consiliency/agent-harness#347` readiness/merge occurs only after body-ancestry, exact-head CI,
  and mandatory review gates pass. Its allowance is the refreshed singleton comment-only
  `B0..H` transition tied to exact refresh base `B0`, exact execution-time server base `B`,
  refreshed head `H`, refresh parents `[H0, B0]`, recomputed result `R`, server two-parent merge
  `M`, and deterministic two-parent integration `I`; it does not alter the exact 18-item
  phase-owned set. Missing merge authority, target-base drift, or any
  head/body/parent/path/comment-only/blob/result mismatch blocks accurately rather than rewriting
  the criterion, accepting a different PR contribution, laundering it through a phase-authored
  commit, or claiming an open PR merged.
- `Consiliency/agent-harness#367` is not resolved by this phase. The selected catalog-population
  arm is valid whether that issue remains open or later ratifies a broader client-doc design;
  LEGIBLE must not claim the broader decision.
- Public-document decision: implementation contract documentation changes at exactly
  `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`.
  SL-2 owns that public document along with the public `cli.py` surface, and the tests-first
  contract assertions plus catalog/docs audit must prove the documented v2/v3 compatibility and
  unchanged public function/CLI behavior. `.claude/docs-catalog.json` must account for the
  contract document under the deterministic repo-owned rescan. No doc change is required for
  README, CHANGELOG, other public API docs, package metadata, or release notes, and all
  roadmap bytes other than the planning-authorized LEGIBLE→PROOFGATE dependency amendment remain
  unchanged. That amendment is required because the two phases share three implementation paths;
  it does not add release scope.
- Digest continuity is a preflight and closeout invariant: before every lane, and again before
  final verification, SHA-256 of `specs/phase-plans-v10.md` must equal
  `040fe81fd36fd48486bb4d6d9550296a830789b5d7a94a9300d3d19ff31cfd2e`. Any roadmap-byte
  change blocks as an unpaneled contract change; this plan provides no mid-phase rebind path
  because none is required by the sidecar architecture. In particular, Assumption 3 already
  declares both the pending and resolved REVIEWTRUTH states, so the fixed sidecar adapter
  classifies that transition without mutating or rebinding roadmap bytes.
- The existing LEGIBLE manifest entry is the non-self-referential plan-digest authority. Its
  `lifecycle[0].metadata.legible_plan_contract` records the final plan SHA-256, exact 18-item
  lane-owned path list/count/digest, two frozen test paths, lifecycle literal, activation env,
  capability marker, and expected-nodeid count. Every planning, tests-only, candidate, panel, and
  canonical-main artifact must recompute the plan digest and compare that metadata with the
  plan frontmatter and parsed lane IR; the frozen `agent-harness#347` path must remain absent from
  that owned set and is accepted only through the exact target-integration contract in this plan.
  The plan cannot carry its own SHA-256 in frontmatter; omitting this manifest comparison,
  accepting a stale panel digest, or allowing an attesting ref's plan/roadmap bytes to differ from
  the contract bound at that ref is a hard chronology failure.
- IF-0-VC-2 command preflight is satisfied only when the plan validator resolves the roadmap
  digest, `verification_commands_from_plan` extracts every command bullet, and
  `resolve_suite_command_doc` resolves the exact frontmatter `automation.suite_command` retained
  in the runner verification artifact. The `## Verification` section contains no fenced command
  block or body pseudo-field.
  Collection-only, skipped-falsifier, earlier-SHA, or prose-only results are not passing evidence.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/**`, `plans/manifest.json`
- evidence paths: `.phase-loop/runs/*/verification.json`, `.phase-loop/runs/*/legible-operational-evidence.json`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment`

This closeout decision is metadata-only downstream routing, not implementation write
authorization. LEGIBLE remains limited to the exact 18 lane-owned paths and does not mutate any
`specs/phase-plans-*.md` bytes. The owned verification-evidence contract document is an in-phase
implementation/public-contract surface, not a `spec_delta_closeout` target; its edit and docs
audit are governed by SL-2. The preserved `roadmap_amendment` decision and target surfaces
`specs/**`, `plans/manifest.json` continue to route later source-spec reconciliation only and must
not be conflated with that implementation documentation. The evidence paths carry only
roadmap-status and digest references; they must not embed raw specifications or diffs.

## Verification Evidence Sidecars

- schema: `legible_evidence.v1`
- path: `.phase-loop/runs/<run-id>/legible-operational-evidence.json`
- required: `true`
- binding: `verification_evidence.v3.extensions.phase_loop_runtime.legible_evidence`

## Verification

- `PYTHONPATH=phase-loop-runtime/src python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-LEGIBLE.md`
- `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap --check-assumptions specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .`
- `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.docs_freshness check-catalog --repo .`
- `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.legible_evidence verify --repo . --stage canonical-main --head HEAD`
- `PYTHONPATH=phase-loop-runtime/src python -m pytest phase-loop-runtime/tests -k "verification_contract or verification_sidecar or public_compatibility" -q`
- `PYTHONPATH=phase-loop-runtime/src python -m pytest phase-loop-runtime/tests/test_preflight_verification.py -k operational_evidence_is_recorded_but_not_executed -q`
- `PYTHONPATH=phase-loop-runtime/src python -m pytest phase-loop-runtime/tests -k "roadmap_status or banner_status or superseded_selector" -q`
- `PYTHONPATH=phase-loop-runtime/src python -m pytest phase-loop-runtime/tests -k "legible_roadmap_contract or legible_evidence" -q`
- `git diff --check`

For `Consiliency/agent-harness#347`, the runner performs the equivalent of:
require server `baseRefName == main`, exact refresh base
`B0 == 648be2f68d6804ecdc4046bb7d4f5ee81a90c356`, and exact refreshed head
`H == 0f12c4614e859fd1082525be852fca4e52624890`; snapshot exact execution-time server base
`B`, require it equals both the implementation base and current target head, descends from `B0`,
contains the canonical tests-only landing, and retains `B0`'s external-path identity; require
`parents(H) == [a89dd82ed7253193a4084ab9f2e15136fe12ea05, B0]`, the exact body SHA-256,
and the singleton net `B0..H` path/comment-only/blob contract frozen above; parse only rows matching
`` | `<7-40 lowercase hex>` | `` from the PR body's commit table; run
`git merge-base --is-ancestor <sha> H` for every parsed SHA; require at least one
SHA, the exact six-row set frozen above, and all results zero. In private temporary indexes,
recompute exact `T_B0H`/`R` from merge base `B0` and tips `[B0, H]`, then recompute `T_BH` from
merge base `B0` and tips `[B, H]`; require no unmerged stages, `T_B0H == H^{tree}`,
`changed(B, T_BH)` to be the singleton external path, and the exact refreshed result identity
above. Require the PR to be non-draft with required checks/reviews satisfied; merge with
merge-commit method; then require
`state == MERGED`, non-null `mergedAt`, and a
non-null server merge commit `M` from
`gh pr view 347 --repo Consiliency/agent-harness --json state,mergedAt,mergeCommit,headRefOid,body`.
The runner requires `parents(M) == [B, H]`, `M^{tree} == T_BH`, and `changed(B, M)` to be exactly
the frozen transition ending at `R`; it creates integration commit `I` with
`parents(I) == [P, M]`, a second private-index recomputed clean-merge tree, and blob `R` at the
external path, then proves the phase/external partition above. The runner writes only redacted
metadata and digests to the operational evidence artifact.

## Acceptance Criteria

- [ ] EC-LEGIBLE-0 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.legible_evidence verify --repo . --stage canonical-main --head HEAD`, the frozen activation/default-84-skip/forced-84-RED/final-84-pass chronology and fresh-process falsifiers, tests-first v1/v2/v3 field-inventory and `operational_exemptions` compatibility controls, the unchanged pre-existing operational-evidence sentinel, exact immutable test/plan/roadmap ancestry, and canonical-main runner-stamped `.phase-loop/runs/<run-id>/verification.json` v3 extension path/length/digest/head/process-token binding of the validated `legible_evidence.v1` artifact
- [ ] EC-LEGIBLE-1 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`, `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k "roadmap_status or banner_status" -q`, and the verifier-bound `roadmap_status` record showing exact tracked-path coverage plus registry/banner agreement
- [ ] EC-LEGIBLE-2 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k declared_active_roadmap -q` requiring the on-disk selected path to equal the sole registry/banner-active roadmap
- [ ] EC-LEGIBLE-3 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .` reporting computed `canonical=N registered=N unregistered=0` with exact HEAD/index/direct-filesystem union equality (and `canonical=28 registered=28 unregistered=0` when the clean scope contains all six root plans), plus `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k manifest -q`, including the untracked in-scope absent-manifest and index-only absent-manifest nonzero/name/origin falsifiers and malformed/symlink/path-escape controls
- [ ] EC-LEGIBLE-4 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.legible_evidence verify --repo . --stage canonical-main --head HEAD` and `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_evidence.py -k pr_evidence -q`
- [ ] EC-LEGIBLE-5 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.docs_freshness check-catalog --repo .` and `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k catalog -q`
- [ ] EC-LEGIBLE-6 — proven by `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap --check-assumptions specs/phase-plans-v10.md`, `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k assumption -q`, and the fresh exact-canonical-main process's bounded/redacted `assumption_probes` record inside the digest/head/process-bound `legible_evidence.v1` sidecar
- [ ] EC-LEGIBLE-7 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py -k "banner_status or superseded_selector" -q` covering registry/banner drift plus explicit, authority, state, manifest, handoff, singleton-glob, manifest-disabled, and completed-hatch return paths independently, with exact-v10 positive controls that kill an always-`None` selector
- [ ] EC-LEGIBLE-8 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_legible_roadmap_contract.py tests/test_legible_evidence.py -k "verification_contract or verification_sidecar or public_compatibility" -q` and canonical-main `phase_loop_runtime.legible_evidence verify`, requiring both legal v2 shapes, the generic v3 registry/reader seam, the registered `phase_loop_runtime.legible_evidence` extension, independent final-log reseal authentication, rejection of unregistered namespaces, and compatibility after downstream registration of `phase_loop_runtime.proofgate_evidence`
