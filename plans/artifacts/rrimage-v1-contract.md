# RRIMAGE v1 contract: build and pin the review-runner image

Frozen planning input for `specs/phase-plans-rrimage-v1.md` and
`plans/phase-plan-v1-rrimage-RRIMAGE.md`. A change needs a reviewed repin of this file's
sha256 in both. It pins inputs only. No section names a commit, digest or count that this
phase will itself produce.

## §1 Need and sources

- **ai-stack Unit 7** (ViperJuice/ai-stack `specs/phase-plans-v17-sandbox-coordinator-unit7.md`
  at `059abc2178e31db109998f0045ffdea6e97a38f3`, foreign prompt for Consiliency/agent-harness):
  "Supply review-runner exact image evidence from
  phase-loop-runtime/images/review-runner/Containerfile in the seats work, not a LANEEXEC
  image: resolve source/build receipt, OCI manifest digest/platform, registry repository and
  verified pull evidence without activating its adapter. … v1 uses exact digest plus ai's
  root-owned allowlist; no image signing. … Report missing review-runner as a blocker."
- **LANEEXEC-v1-errata-2 draft** (agent-harness#2102, head
  `d8aba601eb7a7ce38d07aca3f395fa679e01e0bc`), binding §6 E2-6: the definition of "pinned"
  and the grants list. OWNER-DECISION RR-1 option (c), recommended there, is this phase: a
  small phase run in parallel with LANEEXEC, whose pin record ACTIVATE consumes.
- **Containerfile** `phase-loop-runtime/images/review-runner/Containerfile` at planning time,
  sha256 `f2d317873366426a8cd71ebe41090d2a3867750690072d73df85460cc81673f2`. It already pins
  the rust and python base images by digest, the landlock-exec source commit
  (`Consiliency/agent-toolkit` `d945fdd060aab9ad9471845f4f8e78406a0ac841`), five source-file
  hashes, the helper output hash and the `rfc8785` wheel hash. The test pin
  `phase-loop-runtime/tests/data/landlock-exec/PIN.json` repeats the commit, helper hash and
  toolchain.

## §2 Pin record (`review_runner_pin.v1`)

Schema: `plans/artifacts/rrimage-v1-pin-record.schema.json` (frozen). SL-0 packages it
byte-equal as `phase_loop_runtime/contracts/placement/review-runner-pin-v1.schema.json`;
`contracts/placement/**` is already package data.

A record is **pinned** only when `status = "pinned"` and every rule below holds. A record with
`status = "pushed"` and `pull = null` is valid but not pinned. Consumers accept `pinned` only.

| Rule | Check |
| --- | --- |
| P1 | The record validates against the schema. Every object is closed (`additionalProperties: false`). |
| P2 | `image.reference == image.registry + "/" + image.repository + "@" + image.manifest_digest`. A tag never appears. |
| P3 | `image.manifest_media_type` is a single-platform image manifest. An index is refused in v1. |
| P4 | `source.containerfile_sha256` equals the sha256 of the Containerfile in the checkout under test. A later Containerfile edit makes the committed record stale, by design: re-pin or supersede. |
| P5 | `helper.sha256` equals the `/landlock-exec` hash line in the Containerfile and `PIN.json` `helper_sha256`; `helper.source_commit` equals `PIN.json` `commit`; `helper.path` equals the Containerfile's `COPY --from=landlock … /landlock-exec <dest>` destination. |
| P6 | For `pinned`: `pull.manifest_digest`, `pull.config_digest` and `pull.helper_sha256` equal `image.manifest_digest`, `platform.config_digest` and `helper.sha256`; `pull.os`/`pull.architecture` equal `platform`; `pull.host == "ai"`; `pull.by_digest` is true; `pull.entrypoint_started` is false. |
| P7 | No string in the record matches the credential sentinels: `ghp_`, `gho_`, `ghs_`, `github_pat_`, `glpat-`, `Bearer `, `Basic `, `"auths"`, `password`, `token`, `secret`, a `user:pass@` userinfo, or a base64 run of 40 or more characters outside a digest field. |
| P8 | `recorded_at` is not earlier than `pull.pulled_at` for `pinned`. |

Refusals are closed codes: `pin_schema_invalid`, `pin_reference_mismatch`,
`pin_index_refused`, `pin_containerfile_stale`, `pin_helper_mismatch`,
`pin_pull_mismatch`, `pin_credential_sentinel`, `pin_not_pinned`. Messages name the rule
and field, never the offending value.

## §3 Build recipe

The recipe is a command plan printed by `phase-loop-runtime/scripts/review_runner_image.py
plan`, which executes nothing. The live lane runs the printed commands under the grants of §5.

1. **Source export.** `git archive <source commit>` into an empty context directory, so
   untracked files, `__pycache__` and the checkout's umask never enter the image.
2. **Helper source.** Read-only fetch of `Consiliency/agent-toolkit` at
   `d945fdd060aab9ad9471845f4f8e78406a0ac841`, path `harnesses/pi/sandbox/landlock`, into a
   second empty directory, passed as `--build-context landlock-source=<dir>`. The
   Containerfile's hash checks are the verification. No token enters the build.
3. **Builder.** `docker buildx` with a BuildKit image named by digest
   (`moby/buildkit@sha256:…`), chosen and recorded by SL-1 from a release at least two weeks
   old. The tool version is recorded.
4. **Determinism options.** `--platform linux/amd64`; `SOURCE_DATE_EPOCH` set to the source
   commit's committer time and passed as a build arg; `--provenance=false --sbom=false`;
   output `type=image,oci-mediatypes=true,rewrite-timestamp=true`; `--no-cache` and
   `--pull=false` with the digest-pinned bases.
5. **Network.** Every `RUN` step is either `RUN --network=none` or a hash-pinned install
   (`pip … --require-hashes --only-binary=:all:`). No `curl`, `wget`, `git clone`, `apt-get`,
   `ADD <url>` or unpinned `pip` appears.
6. **Unhashed copies.** The Containerfile today copies `PROVENANCE.md` and `LICENSES/**` from
   the helper source without a hash check. SL-1 adds `sha256sum -c` lines for them, with values
   read at the pinned commit through read-only `gh api`. A file it cannot read stays a
   recorded gap and is not invented.
7. **Reproducibility.** Measured, not assumed. The live build runs twice from the same
   export and records both manifest digests in `build.reproduced`. Inequality is reported
   with the differing layer, and is not a gate (known candidates: `useradd`'s shadow
   `lastchg`, and byte-compiled files). The first build's digest is the one pushed.

## §4 Offline tests

- `tests/test_review_runner_pin.py` (SL-0): P1–P8 with a valid fixture record and one
  mutation per rule. The valid fixture is built from the checked-in Containerfile and
  `PIN.json`, so P4/P5 are exercised against real bytes. The packaged schema equals the
  artifact byte for byte.
- `tests/test_review_runner_recipe.py` (SL-1): every `FROM` is by digest; every `RUN`
  satisfies §3.5; every helper-source `COPY` is hash-checked; `plan` prints the §3 options,
  never `--push` without `--allow-push`, and runs no subprocess (asserted by a patched
  `subprocess` that refuses any call).
- `tests/test_review_runner_pin_receipt.py` (SL-4): the committed record is `pinned` under
  P1–P8 against the checkout.

## §5 Grants and live sequence

Each grant is given by the owner separately and recorded in the evidence file by name and
date, never with a credential.

| Gate | Grant | Unblocks |
| --- | --- | --- |
| G-RR-REGISTRY | The registry and repository names, and a push credential on the build host held by the host's own credential helper. It never appears in the repository, environment dumps, build args or evidence. | SL-3.2 |
| G-RR-BUILD | A native `linux/amd64` build host, a build window, read access there to the pinned helper source, and heavy-work admission on that host. | SL-3.1 |
| G-RR-PUSH | One push of the first build, by digest. | SL-3.2 |
| G-RR-PULL | One pull by digest on `ai`, with inspection and a `create`/`cp` helper read. The entrypoint is never started, and the container is removed afterwards. | SL-3.3 |

External, not an agent-harness grant: **EXT-RR-ALLOWLIST**. ai-stack adds the root-owned
allowlist entry on `ai` from the handoff (§6). The pull of G-RR-PULL does not depend on it.
If ai-stack's runtime refuses a pull that is not allowlisted, SL-3.3 stops and reports, and
the order of the two is the owner's to settle.

Live sequence:

1. SL-3.1 (G-RR-BUILD): export, fetch, build twice, inspect locally. Record `build.*`.
2. SL-3.2 (G-RR-REGISTRY, G-RR-PUSH): push the first build; read the manifest and config
   digests from the registry with `buildx imagetools inspect --raw`. Write a `pushed` record.
3. SL-3.3 (G-RR-PULL): on `ai`, `pull <reference>`, inspect the manifest digest, platform and
   config digest, read the helper through `create` + `cp` + `sha256sum`, then remove it.
   Promote the record to `pinned` only if P6 holds; otherwise keep it `pushed` and stop.

## §6 Handoff to ai-stack

`plans/evidence/review-runner/HANDOFF-ai-stack.md`, posted as a comment on
ViperJuice/ai-stack#504. It carries `image.reference`, the platform and config digest, the
source commit and Containerfile hash, the helper path and hash, and the pull evidence date.
It asks for the allowlist entry and states what is not done: no adapter activation, no
signing, no client configuration and no LANEEXEC route change.

## §7 Non-goals

Image signing; SEATS REMOTE per-target vendor images, which derive from this base; any
adapter, route or `policies.json` change; LANEEXEC or ACTIVATE edits; a CI image build or
push; a multi-platform index.
