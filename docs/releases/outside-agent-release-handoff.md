# Outside-Agent Release Handoff

This handoff records release-preparation and post-publication evidence for the
outside-agent conformance runtime. It is metadata-only: the document itself did
not publish a package, create a tag, dispatch a workflow, edit governed-pipeline,
or make production merge enforcement live.

## Package Identity

- Package: `phase-loop-runtime`
- Version: `0.7.14`
- Runtime `phase_loop_runtime.__version__`: `0.7.14`
- Version pin prepared for downstream pinning: `phase-loop-runtime==0.7.14`
- Console scripts: `phase-loop`, `codex-phase-loop`

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

- `publication_status=published`
- Release PR: `Consiliency/agent-harness#649`; reviewed head
  `8d6332d66bbf5ebe2fc1f4466acd6250008c661f`; base
  `6981ba6fe4d9a3abf0947c7791af1dbc7fad9a4a`; native GPT-5.6 Sol exact-head
  verdict: `AGREE`.
- Exact-head PR gates: publish workflow `32776585825`, build/Gate A job
  `97588926177`, offloaded suite job `97588950399`, and aggregate suite-gate job
  `97606897017`; all completed successfully.
- Merge commit: `0c4d3a89054efa80a1f7663bd65e70d0f547c76e`.
- Signed annotated tag: `v0.7.14`; tag object
  `2de6c06973b84890b62184fa023d387f6044a43c`; GitHub verification: `valid`.
- Trusted-publish workflow `32783112944`: build/Gate A job `97609245453` and
  publish job `97625905153` completed successfully. The publish job downloaded
  the build artifacts, verified both entries in `SHA256SUMS`, and published
  without rebuilding.
- PyPI publication: `phase-loop-runtime==0.7.14`, wheel and sdist both present
  and not yanked. A fresh public-PyPI Python 3.10 install resolved 0.7.14 from
  site-packages and `phase-loop --version` reported 0.7.14.
- GitHub Release: `https://github.com/Consiliency/agent-harness/releases/tag/v0.7.14`.
- Fleet adoption: the supported installer refreshed Claude, Codex, Gemini, and
  OpenCode skill roots from `v0.7.14`. All eight installed advisor-board/panel
  skill bodies contain `claude-fable-5`, `gpt-5.6-sol`, `grok-4.6`, and
  `gemini-3.7-flash`, and contain none of `Harness Fable`, `Harness 3.7 Flash`,
  or `<harness>-3.7-flash`.
- Installed behavior: president order is Fable, Sol, Grok 4.6, then Gemini 3.7
  Flash. A blocking Fable ruling did not fall back; typed
  `president_unavailable` traversed all four rungs; untyped unavailability failed
  at Fable. General executor defaults were not changed by the release PR.

## Sealed Implementation Evidence

This release handoff covers phase-loop-runtime 0.7.14 with a digest-enumerated
contract mirror. Publication, tag creation, workflow dispatch, and downstream
adoption remained maintainer-owned and were not published or not dispatched by
this metadata document.

- candidate implementation commit: `8d6332d66bbf5ebe2fc1f4466acd6250008c661f`
- candidate implementation tree: `80ad6aaf8925977d3202d1e841963be24aa9e3b9`
- release merge commit: `0c4d3a89054efa80a1f7663bd65e70d0f547c76e`
- release merge tree: `80ad6aaf8925977d3202d1e841963be24aa9e3b9`
- pre-publication package evidence: exact-head workflow `32776585825`, job
  `97588926177`, success

### Package Archive Digests

- direct-wheel sha256: `08ec0e61c91b95ccd822a6c6dafc47f607455c594ea1d8a253c7c0b1f7ab4fa7`
- direct-sdist sha256: `d6731f120f694c8046eb5a1d77ad49d68e356edad672c41790ef4c72b5583c37`
- sdist-derived-wheel sha256: not claimed. A raw wheel rebuilt from the published
  sdist is timestamp/toolchain-dependent, and the release workflow did not retain
  a normalized derived-wheel artifact. Release identity is bound only to the
  direct wheel and sdist verified by `SHA256SUMS` and published without rebuilding.

## Package Surface Inventory

- Wheel artifact: `phase_loop_runtime-0.7.14-py3-none-any.whl`
- Sdist artifact: `phase_loop_runtime-0.7.14.tar.gz`
- Wheel top-level entries: `phase_loop_runtime`, `phase_loop_runtime-0.7.14.data`, `phase_loop_runtime-0.7.14.dist-info`
- Wheel file count: `460`
- Sdist top-level entries: `MANIFEST.in`, `PKG-INFO`, `README.md`, `protocol`, `pyproject.toml`, `setup.cfg`, `src`, `tests`
- Sdist file count: `881`
- Wheel entry points: `phase-loop = phase_loop_runtime.cli:main`; `codex-phase-loop = phase_loop_runtime.cli:main`
- Runtime plugin entry points: `dotfiles = phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands`; `dotfiles = phase_loop_runtime.skill_sources_plugin:register_skill_sources`

## Governed-Pipeline Pinning

Governed-pipeline may consume this published runtime as an authoritative
validator by pinning `phase-loop-runtime==0.7.14`, then calling:

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

- The package was not published from this handoff; trusted workflow `32783112944`
  published it from the signed `v0.7.14` tag.
- The git tag was not created from this handoff; its verified tag object is
  `2de6c06973b84890b62184fa023d387f6044a43c`.
- The PyPI workflow was not dispatched from this handoff; the tag push triggered
  it and the workflow completed successfully.
- Production governed-pipeline enforcement is not claimed by this handoff.
- Maintainers retain ownership of future publishing, tagging, workflow dispatch,
  and downstream production pin rollout.
