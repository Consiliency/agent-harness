# Outside-Agent Release Handoff

This handoff records release-preparation evidence for the outside-agent
conformance runtime. It is metadata-only and does not publish a package, create a
tag, dispatch a workflow, edit governed-pipeline, or claim production merge
enforcement is live.

## Package Identity

- Package: `phase-loop-runtime`
- Version: `0.7.14`
- Runtime `phase_loop_runtime.__version__`: `0.7.14`
- Version pin prepared for downstream pinning: `phase-loop-runtime==0.7.14`
- Console scripts: `phase-loop`, `codex-phase-loop`
- Installed agy evidence commands are six `phase-loop` subcommands, not
  standalone console scripts: `agy-canary-clean-settings`, `agy-canary-probe`,
  `agy-canary-bootstrap-attest`, `agy-canary-prepare`, `agy-canary-verify`, and
  `agy-canary-finalize`.

## v0.7.14 Source Boundary

- Source implementation authority: the exact merged
  `Consiliency/agent-harness#545` commit, to be recorded after that PR merges.
- Release authority: the exact reviewed `Consiliency/agent-harness#546` head
  rebased onto that source commit.
- The release delta may change packaging, release metadata, the dedicated PyPI
  workflow, and its release-surface regression. It must leave every
  `Consiliency/agent-harness#545` source and test blob byte-identical.
- The agy evidence path remains opt-in and fail-closed. This handoff does not
  assert a live provider canary, approve a downstream pin, or claim fleet
  convergence.

## Validator Identity

- Governed-pipeline validator authority: `governed_pipeline_validator`
- Validator version: `0.7.14`
- Validator command: `phase-loop outside-agent-validate`
- Advisory preflight command: `phase-loop outside-agent-preflight`
- Advisory output remains supporting evidence only; governed-pipeline remains
  the authoritative acceptance boundary.

## Contract Pin

These values are authoritative as stated here and were verified in-repo by re-hashing
the raw contract bytes at tag `v0.2.1`. `plans/oapack/RELEASE-ANCHOR.md` in
Consiliency/spec is cited as *provenance* for which release is canonical, not as the
authority these values are read from — so this section stays correct even if that
document is momentarily inconsistent (it currently is: its repin-instruction section
still names the superseded `v0.2.0`, reported upstream on `Consiliency/spec#118`).

- `contract_package`: `consiliency-spec`
- `contract_version`: `0.2.1`
- `contract_git_tag`: `v0.2.1` (immutable release anchor). `v0.2.0` is superseded — its
  wheel-shipped router laundered validation-error values into route verdicts; do not pin
  it. The three pinned contract artifacts are byte-identical between the two tags.
- `contract_git_sha`: `b862f977897a7b87c4419680a3e83735d4ff07b0` (commit the tag derefs to)
- `schema_version`: `outside_agent_submission.v0.1`
- `verdict_schema_version`: `outside_agent_route_verdict.v0.1`
- `submission_schema_sha256`: `5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a`
- `verdict_schema_sha256`: `86169277d3a0823db1a6c9fa4d20a838b0bc2820818ad00ebd53dcdd03c2b1c2`
- `vector_manifest_name`: `test-vectors/outside-agent/manifest.json`
- `vector_manifest_hash`: `78858828e9eace93eaf31d90717666ddce54ccb3666113df9d033d67c20cfca0`
- `source_owner`: `Consiliency/spec`
- `redaction_posture`: `metadata_only`

## Release-Check Evidence

- `publication_status=pending` while the v0.7.14 source, isolated-wheel, and
  exact-head review gates run.
- The release PR will record the exact focused/full-suite counts and candidate
  artifact digests after they are produced from its final clean head.
- Tag, workflow, GitHub Release, and PyPI evidence are recorded only after the
  reviewed release PR merges; none is claimed by this preparation record.
- Final tag/workflow/GitHub-Release/PyPI facts belong to a separate
  post-publication handoff-only evidence commit after those facts are live and
  independently revalidated.

## Sealed Implementation Evidence

This release handoff covers phase-loop-runtime 0.7.14 with a digest-enumerated
contract mirror. Publication, tag creation, and workflow dispatch remain
maintainer-owned and are not published or not dispatched here.

- candidate implementation commit: pending exact release PR head
- candidate implementation tree: pending exact release PR tree
- pre-publication package evidence: pending exact-head verification

### Package Archive Digests

- direct-wheel sha256: pending exact-head build
- direct-sdist sha256: pending exact-head build
- sdist-derived-wheel sha256: pending exact-head rebuild

## Package Surface Inventory

- Wheel artifact: `phase_loop_runtime-0.7.14-py3-none-any.whl`
- Sdist artifact: `phase_loop_runtime-0.7.14.tar.gz`
- Wheel top-level entries: `phase_loop_runtime`, `phase_loop_runtime-0.7.14.data`, `phase_loop_runtime-0.7.14.dist-info`
- Wheel file count: recorded from the exact-head build before review
- Sdist top-level entries: `MANIFEST.in`, `PKG-INFO`, `README.md`, `protocol`, `pyproject.toml`, `setup.cfg`, `src`, `tests`
- Sdist file count: recorded from the exact-head build before review
- Wheel entry points: `phase-loop = phase_loop_runtime.cli:main`; `codex-phase-loop = phase_loop_runtime.cli:main`
- Runtime plugin entry points: `dotfiles = phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands`; `dotfiles = phase_loop_runtime.skill_sources_plugin:register_skill_sources`

## Governed-Pipeline Pinning

Governed-pipeline should consume this runtime as an authoritative validator only
after a maintainer publishes or pins it. Pin the released package
`phase-loop-runtime==0.7.14`, then call:

```bash
phase-loop outside-agent-validate path/to/outside-agent-submission.json \
  --output outside-agent-verdict.json \
  --submitted-ref src/agent.py \
  --submitted-ref docs/evidence.md
```

The governed-pipeline side should also pin the Consiliency/spec contract fields
listed above, including `contract_version`, `contract_git_tag`,
`contract_git_sha`, `schema_version`, `verdict_schema_version`,
`submission_schema_sha256`, `verdict_schema_sha256`, and `vector_manifest_hash`.
The per-source `sha256` digests are verified over the raw contract bytes, so a
byte change that preserves the manifest hash no longer slips past this pin.

## Outside-Agent Advisory Preflight

Outside-agent producers can run local advisory preflight before submitting work:

```bash
phase-loop outside-agent-preflight path/to/outside-agent-submission.json \
  --output outside-agent-advisory.json
```

The advisory result can catch metadata-only schema, redaction, provenance, and
digest issues early. It is not acceptance authority and must not be treated as a
merge verdict.

## Release Step — bump `RELEASE_PIN` in lockstep (PUSHFLOW)

- When cutting a release, bump the checked-in `RELEASE_PIN` to the new
  `vX.Y.Z` **in the same release commit** as the `phase-loop-runtime` package
  version (they are kept equal by the release-consistency guard in
  `tests/test_release_pin_autotrack.py`).
- `install-agent-harness.sh` pins the persistent clone at
  `~/.local/share/agent-harness` (or `$AGENT_HARNESS_HOME`) to `RELEASE_PIN`. If
  `RELEASE_PIN` is not bumped, previously installed clones stay behind (the live
  gap where clones sat at `0.6.0` under `RELEASE_PIN=v0.7.0`).
- `phase-loop doctor` surfaces a `stale` BOM verdict for
  `pinned agent clone (~/.local/share/agent-harness)` when a local clone is behind
  `RELEASE_PIN`. The remediation is to re-run `install-agent-harness.sh` (which
  runs `git -C ~/.local/share/agent-harness fetch + checkout $REF`). The check is
  advisory (WARN, never gating).

## Maintainer Dispatch Boundary

- The package is not published from this handoff.
- A git tag is not created from this handoff.
- The PyPI workflow is not dispatched from this handoff.
- Production governed-pipeline enforcement is not claimed by this handoff.
- Maintainers own publish, tag, workflow dispatch, and downstream production pin
  rollout after reviewing this evidence.
