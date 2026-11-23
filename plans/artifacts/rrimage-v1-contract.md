# RRIMAGE v1 contract: build and hand over the review-runner image, then pin it

Frozen planning input for `specs/phase-plans-rrimage-v1.md`. A change needs a reviewed repin
of this file's sha256 in the roadmap's External Inputs. The execution plan pins it
transitively, through its `roadmap_sha256`. The contract pins inputs only. No section names
a commit, digest or count that this phase will itself produce.

**Revision 2 (2026-11-22).** This revision applies the review of agent-harness#2106 at
`c028c985` (B1, B2, E1–E10).
- B1 moves the push and the pull on `ai` to ai-stack (§5).
- B2 builds to OCI archives and adds rule P9 (§2, §3).

**Revision 3 (2026-11-22).** This revision applies the re-review of agent-harness#2106 (A1–A8).
- A1: how the OCI layout is read (§3.4).
- A2: the BuildKit floor (§3.3).
- A3 and A4: push and start evidence in the receipt (§5.1, P6).
- A5: the source is bound into the image config (§3.4, P9, §4).
- A6: consumer obligations, routed to agent-harness#2107 and agent-harness#2108 (§2.1).
- A7: the build host is never `ai` (§5).
- A8: the setuid strip is placed last (§3.8).

## §1 Need, sources and ownership

- **ai-stack Unit 7** (ViperJuice/ai-stack `specs/phase-plans-v17-sandbox-coordinator-unit7.md`
  at `059abc2178e31db109998f0045ffdea6e97a38f3`).
  - Line 383, the foreign prompt to Consiliency/agent-harness: "Supply review-runner exact
    image evidence from phase-loop-runtime/images/review-runner/Containerfile in the seats
    work, not a LANEEXEC image: resolve source/build receipt, OCI manifest digest/platform,
    registry repository and verified pull evidence without activating its adapter. … **Do
    not access/change live ai** or apply client config. … v1 uses exact digest plus ai's
    root-owned allowlist; no image signing. … Report missing review-runner as a blocker."
  - Line 249: ai-stack PREP freezes "the push tool, exact OCI input and destination for each
    image, verified CA, root-only openshell-push credential path".
  - Line 348: the owner "separately pushes exact images … (ai-stack#503); capture digest
    receipt. Then independently verify BOTH manifest bytes and pull-account access".
  - Line 270 (EC-PREP-2): "raw manifest hash = expected digest = unique digest header".
- **Ownership (coordinator ruling on B1, 2026-11-22).** RRIMAGE builds the image, then hands
  over the exact OCI archive and its raw manifest bytes, with their digests. It never pushes
  to ai-stack's registry, never pulls on `ai` and never touches `ai`. The record becomes
  `pinned` only from ai-stack's pull receipt, which RRIMAGE verifies against its own recorded
  digests.
- **LANEEXEC-v1-errata-2 scoping** (agent-harness#2102). The input is `plans/artifacts/v13-LANEEXEC-landed-binding.md`
  §6 E2-6, sha256 `b128afc43a0b156f175e3d3f37848c04467b181ba1fb0ef516e53fc25eae8786`. The
  hash covers the bytes from the `### E2-6` line up to the next heading of level 2 or 3,
  exclusive. That section defines "pinned" and OWNER-DECISION RR-1. This phase is option (c).
- **Containerfile** `phase-loop-runtime/images/review-runner/Containerfile` at planning time,
  sha256 `f2d317873366426a8cd71ebe41090d2a3867750690072d73df85460cc81673f2`. It pins:
  - the base images, by digest;
  - the helper source, `Consiliency/agent-toolkit` at `d945fdd060aab9ad9471845f4f8e78406a0ac841`;
  - `BUILD.lock`, `LICENSE`, `build.sh`, `exec.c`, `uapi.h`, the helper output and the
    `rfc8785` wheel, each by hash.

  `phase-loop-runtime/tests/data/landlock-exec/PIN.json` repeats the commit, the helper hash
  and the toolchain.

## §2 Pin record (`review_runner_pin.v1`)

Schema: `plans/artifacts/rrimage-v1-pin-record.schema.json` (frozen). SL-0 packages it
byte-equal as `phase_loop_runtime/contracts/placement/review-runner-pin-v1.schema.json`.
`contracts/placement/**` is already package data.

Statuses:
- `built`: the record after SL-4. `image` and `receipt` are null.
- `pinned`: the record after SL-5 has verified ai-stack's receipt.

Consumers accept only `pinned`, under strict P4 (§2.1).

**Digest fields.** These are:
- every field typed `digest`, `hex64` or `commit` in the schema;
- the `@sha256:` suffix of every `pinned_reference` value.

| Rule | Check |
| --- | --- |
| P1 | The record validates against the schema, and every object is closed. |
| P2 | `image.reference` equals `image.registry + "/" + image.repository + "@" + artifact.manifest_digest`. A tag never appears. |
| P3 | `artifact.manifest_media_type` and `receipt.raw_manifest_media_type` each name a single-platform image manifest. An index is refused. |
| P4 | `source.containerfile_sha256` equals the sha256 of the Containerfile in the checkout under test. §2.1 sets the scope. |
| P5 | Three helper checks hold. `helper.sha256` equals the `/landlock-exec` hash line in the Containerfile and `PIN.json` `helper_sha256`. `helper.source_commit` equals `PIN.json` `commit`. `helper.path` equals the destination of the Containerfile's `COPY --from=landlock … /landlock-exec <dest>`. |
| P6 | For `pinned`, the receipt matches the record. Its `registry_manifest_digest` and `docker_content_digest` equal `artifact.manifest_digest`. Its `raw_manifest_sha256` equals the digest's hex. Its `config_digest` equals `platform.config_digest`, and its `helper_sha256` equals `helper.sha256`. Its `os` and `architecture` equal `platform`. Its `input_archive_sha256` equals `artifact.oci_archive_sha256`. Its `container_state` is `created`, `started_at_zero` is true and `entrypoint_started` is false. These digest equalities are the authority; `push_tool` and `push_tool_version` are recorded, but they prove nothing on their own. |
| P7 | No string matches the credential sentinels: `ghp_`, `gho_`, `ghs_`, `github_pat_`, `glpat-`, `Bearer `, `Basic `, `"auths"`, `password`, `token`, `secret`, a `user:pass@` userinfo, or a base64 run of 40 or more characters. Digest fields are exempt from the base64 test. The closed schema patterns already exclude most of these, so P7 is defence in depth. |
| P8 | For `pinned`, `recorded_at` is not earlier than `receipt.pulled_at`. |
| P9 | The digests and bytes agree. `build.first_manifest_digest` equals `artifact.manifest_digest`. sha256 of the committed `manifest.json` bytes equals that digest, and their length equals `artifact.manifest_size`. The manifest's `mediaType` is not an index, and its `config.digest` equals `platform.config_digest`. sha256 of the committed `config.json` bytes equals `platform.config_digest`. In that config, `os` and `architecture` equal `platform`. Its `config.Labels` hold `org.opencontainers.image.revision` equal to `source.commit` and `dev.consiliency.review-runner.containerfile-sha256` equal to `source.containerfile_sha256`. For `pinned`, P6's receipt digests equal this same digest. |
| P10 | The reproducibility fields agree. `attempted=false` implies `second_manifest_digest=null`, `equal=null`, `differing_layers=[]` and `deferred_finding=null`. `attempted=true` implies `equal == (second_manifest_digest == first_manifest_digest)`. `equal=false` implies a non-empty `differing_layers` and a non-null `deferred_finding`. |

Refusal codes are closed:
`pin_schema_invalid`, `pin_reference_mismatch`, `pin_index_refused`,
`pin_containerfile_stale`, `pin_helper_mismatch`, `pin_receipt_mismatch`,
`pin_credential_sentinel`, `pin_digest_mismatch`, `pin_reproducibility_inconsistent`,
`pin_source_mismatch` (P9 labels or the §2.1 `git show` check) and `pin_not_pinned`. Each message names the rule and the field, never the value.

### §2.1 Scope of P4 (the stale-pin tripwire)

- `validate_pin_record(record, repo_root, *, allow_stale_marker=False)`. Consumers call it
  with the default, which enforces P4 strictly. The consumers are ACTIVATE, the LANEEXEC
  operator configuration and the SL-5 hand-back to ai-stack. This phase may not edit ACTIVATE
  or LANEEXEC (§7), so their obligations are routed to their owners through plan gates
  IF-XR-2 and IF-XR-3, and filed as agent-harness#2107 (v13 ACTIVATE) and agent-harness#2108
  (LANEEXEC operator configuration).
- The receipt test, which runs in required CI, always enforces P1–P3 and P5–P10.
- A P4 mismatch passes that test only when a sibling marker
  `plans/evidence/review-runner/pin-record.stale.json` exists and names the record. The marker
  holds `{"schema": "review_runner_pin_stale.v1", "record_sha256": <hex64>, "reason": <text>}`,
  and the PR that changes the Containerfile adds it. The verdict is then `stale`, which no
  consumer accepts.
- Re-pinning means a new SL-4 build and SL-5 receipt, which delete the marker.
- **The record is bound to its source.** The receipt test checks that the sha256 of
  `git show <source.commit>:<source.containerfile_path>` equals `source.containerfile_sha256`.
  On a shallow checkout it fetches that one commit first. If it still cannot read the commit,
  the test fails with `pin_source_mismatch` and does not skip. P9 ties the same values to the image config's labels.
  Editing `source.containerfile_sha256` to match a newer Containerfile therefore fails both
  checks, and so cannot clear P4 without the marker.

## §3 Build recipe

`phase-loop-runtime/scripts/review_runner_image.py plan` prints the recipe as a command plan
and executes nothing. SL-4 runs the printed commands under G-RR-BUILD.

1. **Source export.** `git archive <source commit>` into an empty context directory, so
   untracked files, `__pycache__` and the checkout's umask never enter the image.
2. **Helper source.** Read-only fetch, under G-RR-BUILD, of `Consiliency/agent-toolkit` at
   `d945fdd060aab9ad9471845f4f8e78406a0ac841`, path `harnesses/pi/sandbox/landlock`, into a
   second empty directory. It is passed as `--build-context landlock-source=<dir>`. The
   Containerfile's hash checks are the verification. No token enters the build.
3. **Builder.** `docker buildx` with a `docker-container` driver whose BuildKit image is named
   by digest (`moby/buildkit@sha256:…`). SL-2 chooses it from a release at least two weeks old
   and records it with the buildx version. The release must be **v0.13.0 or later**: the
   `rewrite-timestamp` exporter option first appears there. Because an unpinned `# syntax=` is
   refused, the built-in Dockerfile frontend, and with it `RUN --network`, heredocs and
   `SOURCE_DATE_EPOCH`, is that same BuildKit version. `build.buildkit_version` records it.
4. **Output, preserving the digest.** Each attempt runs
   `--output type=oci,dest=<attempt>.tar,rewrite-timestamp=true`. The other options are
   `--platform linux/amd64`, `SOURCE_DATE_EPOCH` set to the source commit's committer time,
   `--provenance=false`, `--sbom=false`, `--no-cache`, and two labels:
   `--label org.opencontainers.image.revision=<source commit>` and
   `--label dev.consiliency.review-runner.containerfile-sha256=<Containerfile sha256 at that commit>`.
   The first attempt's archive is the hand-over artifact, and nothing loads or re-pushes it on
   the agent-harness side.

   **Reading the layout (`record`).**
   - The layout's `index.json` is always an OCI index. It is never a pin target, and it is never
     committed or pushed.
   - `record` requires `index.json` to hold exactly one descriptor, whose `mediaType` is an
     image manifest.
   - That descriptor's `digest` and `size` must equal the sha256 and the length of
     `blobs/sha256/<hex>`.
   - `record` commits that blob byte-for-byte as `manifest.json`. It commits the config blob
     named by that manifest as `config.json`.
   - A descriptor that points to a nested index is refused (`pin_index_refused`), as are a
     second descriptor and a size or digest mismatch (`pin_digest_mismatch`).
5. **Network.** Every `RUN` is either `RUN --network=none` or the hash-pinned pip install
   (`--require-hashes --only-binary=:all:`). Today that means adding `--network=none` to the
   RUN steps at Containerfile lines 9, 22 and 34. No `curl`, `wget`, `git clone`, `apt-get`,
   `ADD <url>` or unpinned `pip` may appear. A `# syntax=` directive is refused unless it is
   pinned by digest.
6. **Helper-source copies.** `LICENSES/**` is checked against the hashes in the `notices`
   block of the hash-checked `BUILD.lock`:
   - `LICENSES/GPL-2.0`: `8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa`
   - `LICENSES/Linux-syscall-note`: `8e378ab93586eb55135d3bc119cce787f7324f48394777d00c34fa3d0be3303f`

   A build step asserts that `LICENSES/` holds exactly that set. `PROVENANCE.md` is not in `BUILD.lock`, so its `COPY` is dropped. The pin
   record carries the provenance instead. No lane before SL-4 makes a network call.
7. **Timestamps.** The runtime stage declares `ARG SOURCE_DATE_EPOCH`, so the value reaches the
   `useradd` step's environment.
8. **setuid and setgid.** A `RUN --network=none` step placed after the last instruction that
   adds files to the runtime stage (after the final `COPY`, just before `USER`) runs
   `find / -xdev -perm /6000 -type f -exec chmod ug-s {} +` and then fails if any such file
   remains. The SL-1 test asserts that no instruction after it adds files, and that no
   `COPY --chmod` anywhere sets a bit in 6000. On the slim-bookworm base this covers `su`, `mount`, `umount`, `passwd`, `chsh`,
   `chfn`, `gpasswd` and `newgrp`. The handoff still asks ai-stack to run the image with
   `no-new-privileges`.
9. **Local evidence.** From the first archive, SL-4 reads the helper's sha256 from the layer
   that holds `helper.path`. It never runs a container.
10. **Reproducibility.** It is measured, and it is not a gate. Trust rests on the exact digest
    plus the root-owned allowlist (ai-stack line 10). Both attempts are recorded under P10.
    On a mismatch, SL-4 lists the differing layers in the record and the handoff, and files a
    repository-qualified issue with the finding verbatim, per
    `docs/registers/deferred-findings.md`. Known candidates are `useradd`'s shadow `lastchg`
    and byte-compiled files.

## §4 Offline tests

- `tests/test_review_runner_pin.py` (SL-0) covers P1–P10. It uses a valid `built` record and a
  valid `pinned` record, with one refusing mutation per rule.
  - Fixtures use the checked-in Containerfile and `PIN.json`, and a synthetic manifest and
    config whose digests are computed in the test.
  - Two P7 cases: a 40-hex commit passes, and a 40-character base64 run in a non-digest field
    is refused.
  - The P4 marker is tested in both directions.
  - The packaged schema equals the artifact.
- `tests/test_review_runner_containerfile.py` (SL-1) covers §3.5–§3.8 on the checked-in
  Containerfile.
- `tests/test_review_runner_recipe.py` (SL-2) covers three things.
  - `plan` prints the §3.1–§3.4 options and makes zero subprocess calls, asserted by a patched
    `subprocess` that refuses any call.
  - `record` builds a `built` record from a valid fixture OCI layout, whose top-level
    `index.json` it accepts. It refuses a descriptor that points to a nested index, a second
    descriptor, and a descriptor whose digest or size differs from its blob.
  - The pinned BuildKit's recorded version is at least v0.13.0, and `plan` passes both labels.
  - `verify-receipt` refuses each P6 and P9 mismatch in a fixture receipt.
- `tests/test_review_runner_pin_receipt.py` (SL-5) checks the committed record under §2.1, including the `git show` source check.

## §5 Grants, external gates and the live sequence

**The one agent-harness grant.** Each grant is recorded in the evidence by name and date,
never with a credential.

| Gate | Grant | Unblocks |
| --- | --- | --- |
| G-RR-BUILD | A native `linux/amd64` build host that is **not `ai`** (Unit 7 line 383: "Do not access/change live ai"; §7), a build window, read access there to the pinned helper source, heavy-work admission on that host, and a private directory there that keeps the archives until SL-5. | SL-4 |

**Handoff post authority.** The SL-4 and SL-5 comments on ViperJuice/ai-stack#504 are made
under the RRIMAGE coordinator's authority. That authority answers ai-stack's own request at
line 383, and the coordinator's name and the date are recorded in the evidence. Without it,
SL-4 and SL-5 write the handoff file and stop before posting.

**Transfer channel.** agent-harness transfers no bytes. The archive stays in the build host's
private directory, and the archive's sha256 in the handoff is its integrity check. Moving it
to the push input is the owner's own action under EXT-RR-PUSH, in ai-stack's step 2. It
needs no agent-harness grant. If the owner instead asks agent-harness to publish the archive
somewhere, that is a new grant and an amendment to this contract.

**External gates, owned by ai-stack.** No agent-harness lane performs these.

| Gate | Owner action | Source |
| --- | --- | --- |
| EXT-RR-REGISTRY | PREP freezes the push tool, the destination, the verified CA and the root-only openshell-push credential. | Unit 7 line 249 |
| EXT-RR-PUSH | The owner pushes the exact OCI archive with a version-pinned tool that preserves digests. | Unit 7 line 348; ai-stack#503 |
| EXT-RR-PULL | The owner verifies the manifest bytes and pull-account access on `ai`, and publishes the receipt (§5.1). | Unit 7 lines 270, 311 and 348 |
| EXT-RR-ALLOWLIST | ai-stack makes the root-owned allowlist entry on `ai`. | Unit 7 lines 10 and 383 |

**Order.**
1. SL-4 builds and posts the handoff.
2. EXT-RR-REGISTRY, which can run at any time before EXT-RR-PUSH.
3. EXT-RR-PUSH.
4. EXT-RR-PULL, which produces the receipt.
5. SL-5 verifies the receipt and the record becomes `pinned`.

EXT-RR-ALLOWLIST and ai-stack's block10 come after the receipt. They gate ai-stack's
qualification, not the `pinned` status.

### §5.1 Pull receipt that RRIMAGE consumes

The handoff states these requirements for ai-stack's receipt. They map onto the schema's
`receipt` object.

- **Push tool.** Version-pinned and digest-preserving, copying from `oci-archive:`, for
  example `skopeo copy --preserve-digests` or `regctl image import`. It must not recompress
  layers or convert media types. A `docker load` followed by `docker push` is refused. The
  receipt records `push_tool` (`skopeo` or `regctl`), `push_tool_version`, and
  `input_archive_sha256`, the sha256 of the archive actually pushed. That last field binds the
  owner's out-of-band transfer to the archive that was handed over. P6 and P9 are the
  authority, not the tool's claim.
- **Reference.** A pull by digest (`<registry>/<repository>@<digest>`), with the
  authenticated pull account named in `pull_account`. A name is recorded, never a credential.
- **Runtime.** The runtime's name and version, and its image store (`image_store`).
- **Digests.** `registry_manifest_digest`; the `Docker-Content-Digest` response header; the
  sha256 of the raw manifest bytes fetched from the registry, and their media type.
- **Config digest.** Read as the raw manifest's config descriptor
  (`config_digest_method = raw_manifest_config_descriptor`). It is never
  `docker image inspect .Id`, which on the containerd image store reports the manifest or
  index digest.
- **Helper.** Read through `create` and then `cp`, with `helper_sha256` taken from the copied
  file. `cp` reads `helper.path` as a regular file, not through a symlink. Before `rm`, the
  container's `State.Status` is captured as `created`, and `State.StartedAt` as the zero time
  `0001-01-01T00:00:00Z` (`started_at_zero = true`). Together they are the evidence for
  `entrypoint_started = false`.
- **Location.** A stable link (`ref`) to the receipt, and the sha256 of its bytes.

## §6 Handoff to ai-stack

`plans/evidence/review-runner/HANDOFF-ai-stack.md` is posted as a comment on
ViperJuice/ai-stack#504 under the authority in §5.

The SL-4 post carries:
- `artifact.*`, the platform and the config digest;
- the source commit and the Containerfile hash;
- the helper path and hash;
- the reproducibility result, with any differing layers and the deferred-finding link;
- the §5.1 receipt requirements and the `no-new-privileges` request.

The SL-5 post carries the `pinned` record's sha256.

Both posts state what is not done: no adapter activation, no signing, no client
configuration, no LANEEXEC route change, and no access to `ai`.

## §7 Non-goals

- image signing;
- the per-target SEATS REMOTE vendor images, which derive from this base;
- any change to an adapter, a route, `policies.json`, LANEEXEC or ACTIVATE;
- a CI image build or push;
- a multi-platform index;
- any push to a registry, or any pull or other action on `ai`, by agent-harness.
