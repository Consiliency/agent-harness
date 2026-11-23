<!--
RRIMAGE SL-3 handoff template (contract plans/artifacts/rrimage-v1-contract.md §5.1 and §6).
SL-4 copies this file to HANDOFF-ai-stack.md and fills every {{placeholder}} from the
committed `built` record, plans/evidence/review-runner/pin-record.json. Every value must equal
the record; the SL-5 receipt test checks this. Do not add host names, host paths or
credentials. Delete this comment block before posting on ViperJuice/ai-stack#504.
-->

# RRIMAGE review-runner image: hand-over to ai-stack Unit 7

Consiliency/agent-harness hands over the review-runner image for ai-stack Unit 7 (IF-XR-1),
answering the foreign prompt at Unit 7 line 383.

- Posted under the authority of: {{coordinator_name}}, {{authority_date}}
- Build grant: G-RR-BUILD, recorded {{grant_date}}
- Pin record: `plans/evidence/review-runner/pin-record.json` at agent-harness commit
  {{evidence_commit}}, status `built`, record sha256 {{record_sha256}}

## Artifact

| Field | Value |
| --- | --- |
| `artifact.manifest_digest` | {{artifact.manifest_digest}} |
| `artifact.manifest_media_type` | {{artifact.manifest_media_type}} |
| `artifact.manifest_size` | {{artifact.manifest_size}} |
| `artifact.manifest_path` | {{artifact.manifest_path}} |
| `artifact.config_path` | {{artifact.config_path}} |
| `artifact.oci_archive_sha256` | {{artifact.oci_archive_sha256}} |
| `platform.os` / `platform.architecture` | {{platform.os}} / {{platform.architecture}} |
| `platform.config_digest` | {{platform.config_digest}} |

The OCI archive is attempt 1 of the build. It stays in the build host's private directory
until SL-5. agent-harness transfers no bytes. Moving the archive to your push input is the
owner's action under EXT-RR-PUSH, and its sha256 above is the integrity check.

## Source

| Field | Value |
| --- | --- |
| `source.repository` | {{source.repository}} |
| `source.commit` | {{source.commit}} |
| `source.containerfile_path` | {{source.containerfile_path}} |
| `source.containerfile_sha256` | {{source.containerfile_sha256}} |

The image config carries `org.opencontainers.image.revision` = `source.commit` and
`dev.consiliency.review-runner.containerfile-sha256` = `source.containerfile_sha256`.

## Helper

| Field | Value |
| --- | --- |
| `helper.path` | {{helper.path}} |
| `helper.sha256` | {{helper.sha256}} |
| `helper.source_repository` | {{helper.source_repository}} |
| `helper.source_commit` | {{helper.source_commit}} |

## Build and reproducibility

| Field | Value |
| --- | --- |
| `build.tool` / `build.tool_version` | {{build.tool}} / {{build.tool_version}} |
| `build.buildkit_image` | {{build.buildkit_image}} |
| `build.buildkit_version` | {{build.buildkit_version}} |
| `build.source_date_epoch` | {{build.source_date_epoch}} |
| `build.setuid_stripped` | {{build.setuid_stripped}} |
| `build.first_manifest_digest` | {{build.first_manifest_digest}} |
| `build.reproduced.attempted` | {{build.reproduced.attempted}} |
| `build.reproduced.second_manifest_digest` | {{build.reproduced.second_manifest_digest}} |
| `build.reproduced.equal` | {{build.reproduced.equal}} |
| `build.reproduced.differing_layers` | {{build.reproduced.differing_layers}} |
| `build.reproduced.deferred_finding` | {{build.reproduced.deferred_finding}} |

Reproducibility is measured, and it is not a gate. Trust rests on the exact digest plus your
root-owned allowlist.

## What we need back: the pull receipt (§5.1)

Please publish a receipt with these fields. They map onto the pin record's `receipt` object.
agent-harness verifies the digest equalities (P6 and P9). They are the authority, not the
tools' own claims.

- **Push tool.** Version-pinned and digest-preserving, copying from `oci-archive:`, for
  example `skopeo copy --preserve-digests` or `regctl image import`. It must not recompress
  layers or convert media types. A `docker load` followed by `docker push` is refused.
  - `push_tool`: {{receipt.push_tool}} (`skopeo` or `regctl`)
  - `push_tool_version`: {{receipt.push_tool_version}}
  - `input_archive_sha256`, the sha256 of the archive actually pushed:
    {{receipt.input_archive_sha256}}
- **Reference.** A pull by digest, `<registry>/<repository>@<digest>`.
  - `by_digest`: {{receipt.by_digest}}
  - `pull_account`, the authenticated pull account's name, never a credential:
    {{receipt.pull_account}}
  - `host`, the role alias: {{receipt.host}}
  - `producer`: {{receipt.producer}}
  - `pulled_at`: {{receipt.pulled_at}}
- **Runtime.** `runtime.name` and `runtime.version`: {{receipt.runtime.name}}
  {{receipt.runtime.version}}; `image_store`: {{receipt.image_store}}
- **Digests.**
  - `registry_manifest_digest`: {{receipt.registry_manifest_digest}}
  - `docker_content_digest`, the `Docker-Content-Digest` response header:
    {{receipt.docker_content_digest}}
  - `raw_manifest_sha256`, the sha256 of the raw manifest bytes fetched from the registry:
    {{receipt.raw_manifest_sha256}}
  - `raw_manifest_media_type`: {{receipt.raw_manifest_media_type}}
- **Config digest.** Read from the raw manifest's config descriptor
  (`config_digest_method = raw_manifest_config_descriptor`), never from
  `docker image inspect .Id`.
  - `config_digest`: {{receipt.config_digest}}
  - `os` / `architecture`: {{receipt.os}} / {{receipt.architecture}}
- **Helper.** Read through `create` and then `cp`. `cp` reads `helper.path` as a regular
  file, not through a symlink. `helper_sha256` is taken from the copied file.
  - `helper_sha256`: {{receipt.helper_sha256}}
  - Before `rm`, capture `State.Status` as `created` (`container_state`:
    {{receipt.container_state}}) and `State.StartedAt` as `0001-01-01T00:00:00Z`
    (`started_at_zero`: {{receipt.started_at_zero}}). Together they are the evidence for
    `entrypoint_started` = {{receipt.entrypoint_started}}, which must be false.
- **Location.** A stable link to the receipt (`ref`: {{receipt.ref}}) and the sha256 of its
  bytes (`ref_sha256`: {{receipt.ref_sha256}}).

The receipt must match the record exactly:

- `registry_manifest_digest` = `docker_content_digest` = `artifact.manifest_digest`;
- `raw_manifest_sha256` = the hex of that digest;
- `config_digest` = `platform.config_digest`;
- `helper_sha256` = `helper.sha256`;
- `os` and `architecture` = `platform`;
- `input_archive_sha256` = `artifact.oci_archive_sha256`;
- `container_state` = `created`, `started_at_zero` = true and `entrypoint_started` = false.

## Request: run with `no-new-privileges`

The image strips every setuid and setgid bit at build time. Please still run the
review-runner container with `no-new-privileges`.

## Order from here

1. EXT-RR-REGISTRY, at any time before EXT-RR-PUSH.
2. EXT-RR-PUSH.
3. EXT-RR-PULL, which publishes the receipt above.
4. agent-harness SL-5 verifies the receipt, marks the record `pinned` and posts the pinned
   record's sha256 here.

EXT-RR-ALLOWLIST and block10 follow the receipt, and they gate your qualification, not the
`pinned` status.

## Not done by agent-harness

- No adapter activation.
- No signing.
- No client configuration.
- No LANEEXEC route change.
- No access to `ai`: agent-harness pushes nothing, pulls nothing and holds no registry
  credential.
