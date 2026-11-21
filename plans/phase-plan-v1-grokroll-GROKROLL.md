---
phase_loop_plan_version: 1
phase: GROKROLL
roadmap: specs/phase-plans-grokroll-v1.md
roadmap_sha256: d99671cc8f98d892b4911abe4726e5e0a924e5f60e4747e1d940bc82ef1aaef6
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_grok_release_catalog.py tests/test_grok_evidence.py tests/test_grok_seat_status.py tests/test_grok_release_provenance.py tests/test_verify_grok_release.py tests/test_grok_catalog_workflows.py tests/test_ci_grok_measure_issue.py tests/test_grok_tool_surface.py"]
---

# GROKROLL: grok release catalog and measured-build query

## Context

A grok seat runs only on a binary digest with a measured tool surface. This phase adds a
supported "is this build measured?" command (Consiliency/agent-harness#2047) and an
authenticated version-to-digest catalog. It stages, executes and measures nothing.

**Revision 4 (2026-11-21).** It applies the third review's five findings, all inside the
kept lanes: the attempt register joins typed evidence; receipt reading and admission get
separate conformance tests; SL-0 itself provides and runs the offline tree check; the
install path and its mirrors change together; and the release check is sized for a hard
catalog bound.

**Revision 3 (2026-11-21).** After the second independent review the coordinator split the
phase. The job and approval lanes of earlier revisions are deferred to a follow-up,
GROKROLL-B, recorded non-normatively in GROKROLL §7 with its owner decisions and the review
findings it must resolve. What stays is four lanes. For those, r3 closes the review's
findings on evidence typing and the decision table, on gate activation and the release
check, and on the hosted dependency path and the wheel proof.

**Frozen inputs.** Both are pinned by sha256 in the roadmap's External Inputs.

- GROKROLL (`plans/artifacts/grokroll-v1-contract.md`): every schema, rule, constant and
  code in this plan. Read-only during execution.
- Tool-surface (`plans/artifacts/grok-tool-surface-contract-v1.md`): the records, receipts
  and precedence the query reads. Not edited.

**What the plan decides, and where.**

| Decision | Where |
|---|---|
| The release catalog, its field classes and how an entry is authenticated | GROKROLL §1, §2 |
| What stops an unverifiable entry: three layers, activation, the release check | GROKROLL §2.4, §2.5 |
| Typed evidence, the attempt register, receipt classes and precedence | GROKROLL §3.1, §3.2 |
| The query's typed output | GROKROLL §3.3 |
| Hold: one `advance` row | GROKROLL §5.1 |
| Retention, rollback, lag | GROKROLL §5.2–§5.4 |
| What a downstream bootstrap changes | GROKROLL §6 |
| What is deferred, and the owner decisions that go with it | GROKROLL §7 |

**First slice.** SL-0 alone answers Consiliency/agent-harness#2047: no network, no
credential, no vendor contact, no owner decision. It may merge and release by itself.

**Stop rules.**

- A lane that needs to edit `grok_tool_surface.py`, `panel_invoker.py`, `agy_provenance.py`,
  `cli.py` or anything under `seat_egress/` stops and reports (GROKROLL §8).
- SL-0 stops if A1's gate fails on a wrapper shape the resolver supports (GROKROLL §0), or
  if any of the three conformance tests of GROKROLL §3.1 cannot pass without editing the
  existing readers.
- No lane sets `attested: true` in the gate file or adds a release entry.
  Both follow OD-3 and are owner acts.
- No lane executes a grok binary, makes a provider or model call, runs
  `tests/test_panel_invoker.py`, or touches the measurement host. Tests use fixture
  registry documents, a fake transport and a synthetic fixture tarball signed with a
  fixture key, plus the one real signature vector of GROKROLL §0.
- SL-2 establishes from current platform documentation whether a ruleset can require this
  workflow from a protected source ref for this repository. If not, the provenance workflow
  ships manual-dispatch only and the lane reports that OD-3 has no mechanism yet.

**Shared-host rule.** Only the files a lane lists, serially without `-n`, under `timeout`,
after a headroom check. Full suites and the wheel smoke run in hosted CI or Gate A.

## Interface Freeze Gates

- [ ] IF-0-GROKROLL-1 — GROKROLL §1, §2.4, §2.5: `grok_roll.catalog.parse_releases`, `load_releases`, `ReleaseCatalog`, `MAX_RELEASES`, `aging`, `REGISTRY_KEYS`, `verify_entry_signature`, `load_gate`, `check_tree`, the empty `data/grok_releases.json` and the unattested `data/grok_catalog_gate.json`.
- [ ] IF-0-GROKROLL-2 — GROKROLL §3 and §5.1: `grok_roll.evidence` and its three results over catalogs, host records, attempt registers and receipts; the three-step route evidence; the `seat-window status` flags; route and build states; the `grok_seat_status.v1` field table; the decision table; exit statuses; `grok_roll.status.query`.
- [ ] IF-0-GROKROLL-3 — GROKROLL §2.1–§2.4: `grok_roll.provenance.derive_release`, `stable_version`, `ReleaseError.code`, the size constants, the four verifier modes, and the check name `grok catalog provenance`.
- [ ] IF-0-GROKROLL-4 — GROKROLL §6: the downstream bootstrap contract. No lane implements it; SL-3 publishes it.

## Lane Index & Dependencies

SL-0 — STATUS: catalog loader, gate file, typed evidence and the status query (first slice)
  Depends on: (none)
  Blocks: SL-1, SL-3
  Parallel-safe: no

SL-1 — PROVENANCE: release derivation and the verifier script
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — HOSTED: the provenance check, the release gate and the nightly lag report
  Depends on: SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — DOCS: operations page and changelog (reducer)
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

Source paths are under `phase-loop-runtime/src/phase_loop_runtime/`; test paths are under
`phase-loop-runtime/`.

### SL-0 — STATUS: catalog loader, gate file, typed evidence and the status query

- **Scope**: Add the `grok_roll` subpackage with the catalog loader, the offline tree check, the signature check, the typed evidence readers and the status query; wire the `status` action; ship the unattested gate file; and bring the new extra into every suite environment in one change set.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/src/phase_loop_runtime/grok_roll/__init__.py`, `phase-loop-runtime/src/phase_loop_runtime/grok_roll/catalog.py`, `phase-loop-runtime/src/phase_loop_runtime/grok_roll/evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/grok_roll/status.py`, `phase-loop-runtime/src/phase_loop_runtime/data/grok_releases.json`, `phase-loop-runtime/src/phase_loop_runtime/data/grok_catalog_gate.json`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `.github/workflows/test.yml`, `phase-loop-runtime/scripts/local_check.py`, `ci/dagger/src/agent_harness_ci/main.py`, `phase-loop-runtime/tests/test_local_check.py`, `phase-loop-runtime/tests/test_ci_xdist_adoption.py`, `phase-loop-runtime/tests/test_grok_release_catalog.py`, `phase-loop-runtime/tests/test_grok_evidence.py`, `phase-loop-runtime/tests/test_grok_seat_status.py`, `phase-loop-runtime/tests/test_grok_ci_install.py`, `phase-loop-runtime/tests/fixtures/grok_roll/status/**`, `phase-loop-runtime/tests/fixtures/grok_roll/trees/**`
- **Interfaces provided**: `IF-0-GROKROLL-1`, `IF-0-GROKROLL-2`
- **Interfaces consumed**: `grok_tool_surface.load_catalog`, `frozen_surface`, `context_digest`, `attempts_name`, `MEASUREMENT_MODEL`, `MEASUREMENT_EFFORT`, `panel_invoker.grok_runtime_forms`, `_grok_argv_digest`, `_grok_tools_admitted`, `_read_grok_receipt`, `grok_tool_gate`, `_seat_provider_source`, `seat_window.register_parser` (pre-existing)
- **Interface notes**: `frozen_surface`, `_read_grok_receipt` and `grok_tool_gate` are consumed only as the three conformance oracles; the query's own reads go through `grok_roll.evidence`.
- **Parallel-safe**: no
- **Tasks**:
  - test: one loader refusal per rule of GROKROLL §1, including 25 entries; a 24-entry catalog with pinned and surfaced entries beyond the newest twelve loads and survives `aging`; the void-on-one-bad-entry rule.
  - test: the gate file: the shipped unattested file is well formed; each malformed shape, including an unattested file with a non-null field and an attested file missing one.
  - test: `check_tree` on the shipped package data, and on fixture trees where each of its five steps fails alone, including a non-empty unattested catalog and an attested tree with a surface lacking a member.
  - test: `verify_entry_signature` on the real vector of GROKROLL §0 under the pinned key, on that vector with one byte changed, and on a key id the constant lacks. The test imports `cryptography` unconditionally and has no skip path.
  - test: typed reads, per source (catalogs, host record, attempt register, receipt): `ok`; `absent` for a missing file and a missing directory; `invalid` for a denied read, wrong owner, wrong directory or file mode, a link, a FIFO, an over-size file, bad JSON, a wrong schema, an unknown key and another host's record.
  - test: frozen result, with fixtures for a current publication, a superseding attempt, a missing register and an invalid register, each as subject, as candidate and as a target member; a catalog route deciding alone beside a corrupt host record. Then conformance 1 against `frozen_surface`.
  - test: receipt classes: a legacy listing receipt with no `basis`; a `list_tools` receipt; a listing receipt carrying a frozen field; a failing receipt; a frozen receipt whose record is current, whose context went stale, and whose backing route is gone; malformed frozen fields; an unknown basis. Then conformance 2 against `_read_grok_receipt`, descriptor cases only, and conformance 3 against `grok_tool_gate`.
  - test: route evidence, every row of GROKROLL §3.2 step 3, including a listing receipt beside frozen evidence of each kind; every build state, including `partial` from one usable and one absent route, from a refused route and from a withdrawn route; revocation ahead of all of them; a help-text listing claim with no receipt.
  - test: the decision table by exhaustive enumeration over non-null candidates and both `inputs` failures: row 7 is the only `advance`; each falsifier of EC-GROKROLL-3; both targets over revoked, stale, partial, withdrawn, invalid and unknown-version members.
  - test: the golden field table (keys, types, nulls, enumerations, error object, exit statuses, `--schema`, `--require-route`); path selectors: a FIFO, a directory, a link, an oversize file and a file rewritten during the read each fail with their detail code and never block.
  - test: A1 and the no-effect guard together through the production resolver, unmocked: each wrapper shape `_shell_wrapper_target` recognises, one it does not (`subject_not_native`), and no grok installed (`subject: null`), all with `socket.socket`, `subprocess.Popen`, `os.execve` and write-mode `os.open` patched to fail and the private record root absent.
  - test: through `cli.main` with `brotli` and `cryptography` import-blocked, `seat-window status` answers.
  - test: `tests/test_grok_ci_install.py`: the hosted install line, `CI_TEST_DEPS` and the Gate A suite container all name `[visual,claude-sdk,grok-catalog]`; the wheel-smoke step installs a built wheel with no extra in its own environment and runs the status command.
  - impl: `catalog.py` (with `check_tree`), `evidence.py`, `status.py`, the two data files and their package-data entries, and the `grok-catalog` extra (`cryptography` at the lock's existing pin, `brotli`), also added to the `test` dependency group.
  - impl: one change set for the install path: the ordinary pytest job's install line in `.github/workflows/test.yml`, `CI_TEST_DEPS` in `scripts/local_check.py`, the suite container in `ci/dagger/src/agent_harness_ci/main.py`, and the verbatim assertions in `tests/test_local_check.py` and `tests/test_ci_xdist_adoption.py`, all to `[visual,claude-sdk,grok-catalog]`. The seat-jail job's separate install line is not touched.
  - impl: a wheel-smoke step in the ordinary job of `.github/workflows/test.yml`: build the wheel, create a fresh virtual environment, install only the wheel, run `phase-loop seat-window status --vendor grok`, and require exit 0 or 3 with a well-formed object.
  - impl: in `seat_window.py`, the `status` action and its flags only, reusing the parser's existing `--binary` option.
  - verify: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_grok_release_catalog.py tests/test_grok_evidence.py tests/test_grok_seat_status.py tests/test_grok_ci_install.py tests/test_local_check.py tests/test_ci_xdist_adoption.py tests/test_grok_tool_surface.py`
  - verify: on the integration base after any rebase, re-read `data/grok_tool_surfaces.json`. If it now holds surfaces, add a status case over the shipped data for each (expected `release: "unknown"`); `check_tree` on the shipped data must still pass unattested, which SL-0's own test asserts.
  - verify (hosted): the ordinary pytest job passes with the signature vector test collected, and its wheel-smoke step passes; a Gate A suite run passes in the updated container.

### SL-1 — PROVENANCE: release derivation and the verifier script

- **Scope**: Derive a release entry from the vendor registry under GROKROLL §2.2 and expose the four verifier modes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/grok_roll/provenance.py`, `phase-loop-runtime/scripts/verify_grok_release.py`, `phase-loop-runtime/tests/test_grok_release_provenance.py`, `phase-loop-runtime/tests/test_verify_grok_release.py`, `phase-loop-runtime/tests/fixtures/grok_roll/registry/**`
- **Interfaces provided**: `IF-0-GROKROLL-3`
- **Interfaces consumed**: `IF-0-GROKROLL-1` from SL-0, including `check_tree`; `agy_provenance._Transport` (pre-existing), reused, or its rules copied with the same tests.
- **Parallel-safe**: no
- **Tasks**:
  - test: the genuine fixture derives its six fields, twice, identically; one tampered fixture per step of §2.2 with its code; a signature under a key the constant lacks; a redirect off-host; a proxy variable in the environment; a brotli stream past the bound; the expanded member never executed.
  - test: `--catalog-pr` on fixture trees: untouched; one genuine added entry; a changed derived field; a stored signature that does not verify; a gate-only flip to attested with a shipped surface lacking a member (fails) and with every member present (passes); a malformed attested gate; attested back to unattested with a non-empty catalog (fails); a removal §5.2 forbids; the removal of an entry upstream no longer serves; `pinned`, `revoked` and gate changes reported; five added entries.
  - test: `--release`: an unattested empty tree passes with no network; an attested tree of 24 entries re-derives all 24, one image held at a time; one entry `unavailable` fails; a tree that fails `check_tree` fails before any fetch.
  - test: `--derive` reporting each attestation status; `--upstream-only --report` for current, inside and beyond `LAG_NOTICE`, and for an unattested catalog.
  - impl: `provenance.py`, the member streamed to a sealed descriptor with one image held; the script, importing only from the tree it runs in.
  - verify: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_grok_release_provenance.py tests/test_verify_grok_release.py`

### SL-2 — HOSTED: the provenance check, the release gate and the nightly lag report

- **Scope**: The pull-request check from the base commit's tree and locked environment, the pre-publish re-derivation, and the nightly report that keeps one `grok-measure` issue.
- **Owned files**: `.github/workflows/grok-catalog-provenance.yml`, `.github/workflows/grok-release-watch.yml`, `.github/workflows/publish-pypi.yml`, `ci/grok-measure-issue.sh`, `phase-loop-runtime/tests/test_grok_catalog_workflows.py`, `phase-loop-runtime/tests/test_ci_grok_measure_issue.py`
- **Interfaces provided**: `grok catalog provenance`
- **Interface notes**: also the release gate step and the `grok-measure` issue rule of GROKROLL §5.4.
- **Interfaces consumed**: `IF-0-GROKROLL-3`
- **Parallel-safe**: no
- **Tasks**:
  - test: workflow shape: the verifier and its environment (`uv sync --locked --extra grok-catalog`) come from the base ref; the head is fetched as data into a separate path and never executed; the path filter includes the gate file; permissions are read-only for the check and `issues: write` only for the nightly job; no `pull_request_target`; the nightly job runs on `main` only; the publish workflow runs `--release` in a step every upload step depends on, with a 60-minute timeout.
  - test: the issue script against a fake API: create, update in place, close when current, never a second open issue, no issue while unattested.
  - impl: the two new workflows, the one added step in `publish-pypi.yml`, and the script. If the protected-workflow facility is not confirmed, `grok-catalog-provenance.yml` has `workflow_dispatch` as its only trigger.
  - verify: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_grok_catalog_workflows.py tests/test_ci_grok_measure_issue.py`; record for SL-3 which case applies.

### SL-3 — DOCS: operations page and changelog

- **Scope**: Publish how the catalog and the query work and what a downstream bootstrap may rely on, after reading every producer lane's result.
- **Owned files**: `docs/ops/grok-release-catalog.md`, `CHANGELOG.md`
- **Interfaces provided**: `IF-0-GROKROLL-4`
- **Interfaces consumed**: `IF-0-GROKROLL-1`, `IF-0-GROKROLL-2`, `IF-0-GROKROLL-3`
- **Findings consumed**: SL-2's result on the protected-workflow facility; the state of OD-3.
- **Parallel-safe**: no
- **Tasks**:
  - test: the entry-doc and docs-audit checks that already run in hosted CI.
  - impl: the operations page: the status command with one example per decision row; evidence states and what an operator does about `invalid`; how an entry is derived and added; the three enforcement layers, the owner's activation steps for OD-3 and the residual authority (GROKROLL §2.5); withdrawing a build, including the listing-receipt limit; the downstream contract of §6; and a pointer to GROKROLL-B. The changelog: the new command, the new extra, the effect of the `seat_window.py` edit on `runtime_digest()` and the requalification it needs, and that everything ships inert.
  - verify: `git diff --stat` shows only the two owned files; the hosted docs checks pass.

## Verification

Per lane: the commands above. Whole phase: the frontmatter `suite_command`, then,
read-only, `phase-loop seat-window status --vendor grok` (one `grok_seat_status.v1` object,
exit 0).

Hosted CI before each merge: the ordinary pytest job, which now installs the
`grok-catalog` extra and runs the wheel smoke in a separate environment without it; a
Gate A suite run for SL-0. `grok catalog provenance` runs
on a pull request only if SL-2 confirmed the protected-workflow facility; otherwise it is
dispatched by hand and is no gate (GROKROLL §2.5). Nothing in this phase is verified by a
live measurement.

## Execution Notes

- **Single-writer files.** `seat_window.py`, `pyproject.toml`, `uv.lock`,
  `.github/workflows/test.yml`, `scripts/local_check.py`, the Gate A suite container and
  the two install-mirror tests: SL-0. `CHANGELOG.md`: SL-3.
- **EXT-2046.** After Consiliency/agent-harness#2046 merges or closes, SL-0 and SL-3 rebase
  onto it and re-check: the `test` dependency group with both extras, the regenerated lock
  and its `cryptography` pin, the changelog and the manifest tail.
- **Requalification.** SL-0's edit to `seat_window.py` moves `runtime_digest()`. Window
  records on the old key need requalification, as after any runtime edit.
- **Not pinned here.** No commit, commit count or landing order of this phase's own work.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`.

- [ ] EC-GROKROLL-1 — proven by `pytest tests/test_grok_evidence.py tests/test_grok_seat_status.py -k ec_grokroll_1`; falsified by a corrupt or unreadable record, attempt register, receipt or catalog fixture reported as `unmeasured` or `measured`, by a withdrawn route reported `usable`, by a stale frozen receipt reported `invalid`, by the revoked, other-host or help-claim fixtures reporting `measured: true`, or by the no-effect guard recording a socket, a launch or a write. Path-entered control: through `cli.main` with `seat-window status` and the production resolver, over catalogs, records and receipts on disk.
- [ ] EC-GROKROLL-2 — proven by `pytest tests/test_grok_seat_status.py -k ec_grokroll_2 tests/test_grok_ci_install.py` and the hosted wheel-smoke step; falsified by retyping or deleting a key in the emitted object and the golden test still passing. Path-entered control: through the installed `phase-loop` entry point with the extra absent.
- [ ] EC-GROKROLL-3 — proven by `pytest tests/test_grok_seat_status.py -k ec_grokroll_3`; falsified by any `advance` outside row 7 in the exhaustive enumeration, or by a withdrawn member named as a target. Path-entered control: through `cli.main` with a candidate selector.
- [ ] EC-GROKROLL-4 — proven by `pytest tests/test_grok_release_catalog.py -k ec_grokroll_4 tests/test_grok_ci_install.py`, in SL-0, executed in the ordinary hosted pytest job; falsified by a file with one bad entry yielding any entry, 25 entries loading, a non-empty unattested catalog passing `check_tree`, or the vector test being skipped. Path-entered control: through `load_releases` and `check_tree` on the package-data paths.
- [ ] EC-GROKROLL-5 — proven by `pytest tests/test_grok_release_provenance.py -k ec_grokroll_5`; falsified by any tampered fixture deriving, or the transport following an off-host redirect. Path-entered control: through `derive_release` over the fake transport serving fixture bytes.
- [ ] EC-GROKROLL-6 — proven by `pytest tests/test_verify_grok_release.py -k ec_grokroll_6 tests/test_grok_catalog_workflows.py`; falsified by a head tree that replaces the verifier and passes, a gate-only flip passing while a shipped surface has no member, or a publish workflow with an upload that does not depend on `--release`. Path-entered control: through the script's `main` on fixture base and head trees.
- [ ] EC-GROKROLL-7 — proven by `pytest tests/test_grok_release_catalog.py -k ec_grokroll_7 tests/test_ci_grok_measure_issue.py`; falsified by `aging` dropping a pinned or surfaced entry, or two open issues. Path-entered control: through `aging`, `--catalog-pr` on a removal, and the script against the fake API.
- [ ] EC-GROKROLL-8 — proven by `pytest tests/test_grok_tool_surface.py tests/test_seat_reference_inventory.py` unchanged and green, and by `git diff --stat` against the phase base listing none of the files GROKROLL §8 forbids; falsified by a moved context digest or argv digest. Path-entered control: the existing guards, unedited.
- [ ] EC-GROKROLL-9 — proven by `phase-loop seat-window status --vendor grok --candidate <staged path>` driving the hold test in the downstream bootstrap's repository under EXT-BOOT; falsified by that hold importing a harness module or reading a file under the private record root. Path-entered control: through that repository's update step. No lane here changes it; recorded as external until that change lands.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/ops/grok-release-catalog.md`, `CHANGELOG.md`
- evidence paths: `phase-loop-runtime/tests/test_grok_seat_status.py`, `phase-loop-runtime/tests/test_grok_evidence.py`, `phase-loop-runtime/tests/test_grok_release_provenance.py`
- redaction posture: `metadata_only`
- downstream handling: EC-GROKROLL-9 lands in a downstream bootstrap under EXT-BOOT; GROKROLL-B is planned by roadmap amendment after OD-B1 and the first real measurement
