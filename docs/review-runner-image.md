# Review-runner image: build, hand-over and pin

Operator guide for the RRIMAGE phase (`plans/phase-plan-v1-rrimage-RRIMAGE.md`). The
frozen contract is `plans/artifacts/rrimage-v1-contract.md`, and it wins wherever this guide
disagrees with it. The pin record schema is
`plans/artifacts/rrimage-v1-pin-record.schema.json`.

agent-harness builds the review-runner image from
`phase-loop-runtime/images/review-runner/Containerfile` and hands over the exact OCI archive
and its raw manifest bytes. ai-stack pushes the archive, pulls it on `ai` and returns a
receipt. agent-harness verifies that receipt against its own digests, and only then is the
record `pinned`.

## Who does what

| Step | Owner | Needs |
| --- | --- | --- |
| Build twice to OCI archives, commit the `built` record (SL-4) | agent-harness | G-RR-BUILD |
| Post the handoff on ViperJuice/ai-stack#504 (SL-4) | agent-harness | coordinator authority |
| EXT-RR-REGISTRY, EXT-RR-PUSH, EXT-RR-PULL, EXT-RR-ALLOWLIST | ai-stack | ai-stack's own gates |
| Verify the receipt, promote to `pinned` (SL-5) | agent-harness | the receipt |

agent-harness never pushes to a registry, never pulls on `ai`, never transfers the archive,
never holds a registry credential and never acts on `ai`.

### The one agent-harness grant: G-RR-BUILD

G-RR-BUILD is the only grant agent-harness needs. It provides:

- a native `linux/amd64` build host that is **not `ai`**;
- a build window;
- read access on that host to the pinned helper source;
- heavy-work admission on that host;
- a private directory there that keeps the archives until SL-5.

The evidence records the grant by name and date, never with a credential. The SL-4 and SL-5
posts on ViperJuice/ai-stack#504 also need the RRIMAGE coordinator's authority, recorded the
same way. Without it, the lane writes the handoff file and stops before posting. A missing
grant, authority or receipt stops the lane with `blocker_class=human_required`, and nothing
retries it in a loop.

### The ai-stack gates, in order

No agent-harness lane performs these.

| Gate | ai-stack action |
| --- | --- |
| EXT-RR-REGISTRY | PREP freezes the push tool, the destination, the verified CA and the root-only push credential. |
| EXT-RR-PUSH | The owner pushes the exact OCI archive with a version-pinned, digest-preserving tool. |
| EXT-RR-PULL | The owner verifies the manifest bytes and pull-account access on `ai`, and publishes the receipt. |
| EXT-RR-ALLOWLIST | ai-stack makes the root-owned allowlist entry on `ai`. |

The order is:

1. SL-4 builds and posts the handoff.
2. EXT-RR-REGISTRY, at any time before EXT-RR-PUSH.
3. EXT-RR-PUSH.
4. EXT-RR-PULL, which produces the receipt.
5. SL-5 verifies the receipt, and the record becomes `pinned`.

EXT-RR-ALLOWLIST comes after the receipt. It gates ai-stack's qualification, not the
`pinned` status.

The archive stays in the build host's private directory. Moving it to the push input is the
ai-stack owner's own action under EXT-RR-PUSH, and the archive's sha256 in the handoff is
its integrity check. Publishing the archive anywhere on agent-harness's side would be a new
grant and a contract amendment.

## The recipe

`review_runner_image.py plan` prints the recipe and runs nothing: no subprocess, no file
read, no network call.

```bash
python3 phase-loop-runtime/scripts/review_runner_image.py plan --source-commit <40-hex commit>
```

Run the printed commands with bash, under G-RR-BUILD on the build host. Run them from an
agent-harness checkout at the source commit, so that `record` checks P4 against it. Set
`RR_WORK` to a new, empty, private directory first. The plan covers these steps:

1. **Source export.** `git archive` of the source commit into an empty context directory, so
   untracked files, caches and the checkout's umask never reach the image.
   `SOURCE_DATE_EPOCH` is the commit's committer time.
2. **Helper source.** A read-only fetch of `Consiliency/agent-toolkit` at the pinned commit,
   path `harnesses/pi/sandbox/landlock`, into a second empty directory. It is passed as
   `--build-context landlock-source=…`. The Containerfile's hash checks are the
   verification, and no token enters the build.
3. **Builder.** A `docker buildx` `docker-container` builder whose BuildKit image is named
   by digest: `moby/buildkit` v0.18.2. The contract floor is v0.13.0, the first release with
   the `rewrite-timestamp` exporter option.
4. **Two builds.** Each attempt uses
   `--output type=oci,dest=<attempt>.tar,rewrite-timestamp=true`, `--platform linux/amd64`,
   `SOURCE_DATE_EPOCH`, `--provenance=false`, `--sbom=false` and `--no-cache`, with two
   labels: `org.opencontainers.image.revision=<source commit>` and
   `dev.consiliency.review-runner.containerfile-sha256=<Containerfile sha256 at that commit>`.
   Attempt 1's archive is the hand-over artifact. Nothing on the agent-harness side loads
   it or pushes it again.
5. **Local evidence.** The helper's sha256 is read from the attempt-1 layer that holds
   `helper.path`. No container is run.
6. **Record.** Write the build metadata file, then run `record` (below).

The Containerfile has these properties, and SL-1's tests audit them:

- every `FROM` is pinned by digest;
- every `RUN` is `--network=none`, except the hash-pinned pip install;
- `LICENSES/` is checked against the `BUILD.lock` notice hashes;
- `ARG SOURCE_DATE_EPOCH` is declared in the runtime stage;
- the setuid and setgid bits are stripped after the last instruction that adds files.

Reproducibility is measured, and it is not a gate. Both attempts are recorded under P10. On
a layer mismatch, SL-4 lists the differing layers and files a repository-qualified issue, per
`docs/registers/deferred-findings.md`.

**Known limitation.** If two attempts differ only in their image config, with identical
layers, `record` currently refuses with `P10 pin_reproducibility_inconsistent` and writes
nothing. P10 needs a non-empty `differing_layers` for unequal digests, and the schema holds
layer digests only, so no record can describe that case truthfully. The fix is a contract
erratum, tracked as agent-harness#2122. Until it lands, a config-only difference stops SL-4.

### `record`, `--replace` and `verify-receipt`

```bash
python3 phase-loop-runtime/scripts/review_runner_image.py record \
  --layout <layout-1> --archive <attempt-1.tar> --second-layout <layout-2> \
  --meta <build-meta.json> --repo-root . [--deferred-finding <issue URL>] [--replace]
```

`record` reads the extracted OCI layout. Its `index.json` must hold exactly one image-manifest
descriptor whose digest and size match its blob. `record` then commits three files under
`plans/evidence/review-runner/`:

- the manifest blob byte-for-byte as `manifest.json`;
- the config blob it names as `config.json`;
- the `built` record as `pin-record.json`.

It first validates a staged copy with strict P4, then switches in the whole new evidence
directory with one rename. A refusal never leaves a mixed set.

If the evidence already exists, `record` refuses unless `--replace` is passed. `--replace`
records a **new build** as a `built` record. It never confers `pinned`, and it never clears
the stale marker: other files in the evidence directory, including
`pin-record.stale.json`, are carried over unchanged.

```bash
python3 phase-loop-runtime/scripts/review_runner_image.py verify-receipt \
  --receipt plans/evidence/review-runner/receipt-ai-stack.json \
  --registry <registry> --repository <repository> --repo-root .
```

`verify-receipt` is the separate step that completes a pin or a re-pin. It applies ai-stack's
receipt to the committed `built` record and requires a strict `pinned` verdict. It rewrites
`pin-record.json` only on success. Otherwise the record stays `built`.

Refusals from either command print `<rule> <code>: <field>` and exit 2. Messages never carry
record values.

## The pin record and rules P1–P10

`phase_loop_runtime.review_runner_pin.validate_pin_record(record, repo_root, *,
allow_stale_marker=False)` applies these rules. A record is `built` after SL-4, with `image`
and `receipt` null, and `pinned` after SL-5.

| Rule | Check | Refusal |
| --- | --- | --- |
| P1 | The record validates against the schema, and every object is closed. | `pin_schema_invalid` |
| P2 | `image.reference` is `<registry>/<repository>@<manifest_digest>`, with no tag. | `pin_reference_mismatch` |
| P3 | The artifact and receipt media types name a single-platform image manifest, never an index. | `pin_index_refused` |
| P4 | `source.containerfile_sha256` equals the checkout's Containerfile sha256 (scope below). | `pin_containerfile_stale` |
| P5 | `helper.sha256`, `helper.source_commit` and `helper.path` agree with the Containerfile and `PIN.json`. | `pin_helper_mismatch` |
| P6 | For `pinned`, every receipt digest, the platform, `input_archive_sha256` and the not-started evidence match the record. | `pin_receipt_mismatch` |
| P7 | No string matches a credential sentinel; digest fields are exempt from the base64 test. | `pin_credential_sentinel` |
| P8 | For `pinned`, `recorded_at` is not earlier than `receipt.pulled_at`. | `pin_receipt_mismatch` |
| P9 | The committed manifest and config bytes hash to the recorded digests, and the config labels equal `source.*`. | `pin_digest_mismatch`, `pin_source_mismatch` |
| P10 | The reproducibility fields are consistent. | `pin_reproducibility_inconsistent` |

A consumer that needs `pinned` and receives another status gets `pin_not_pinned`. The
contract's §2 table is the full statement of each rule.

### P4 scope and the stale marker

- Consumers call `validate_pin_record(record, repo_root)` with the default, which enforces P4
  strictly.
- The receipt test in required CI always enforces P1–P3 and P5–P10. A P4 mismatch passes that
  test only when `plans/evidence/review-runner/pin-record.stale.json` names the record:

  ```json
  {"schema": "review_runner_pin_stale.v1", "record_sha256": "<hex64>", "reason": "<text>"}
  ```

  `record_sha256` is the sha256 of the record's RFC 8785 canonical bytes. The PR that changes
  the Containerfile adds the marker. The verdict is then `stale`, and no consumer accepts it.
- The record is bound to its source. The receipt test checks that the sha256 of
  `git show <source.commit>:<source.containerfile_path>` equals
  `source.containerfile_sha256`, and P9 ties the same values to the image config's labels.
  Editing the recorded hash to match a newer Containerfile therefore fails both checks.

**Re-pinning after a Containerfile change:**

1. The Containerfile PR adds the stale marker.
2. A new SL-4 build runs under G-RR-BUILD, with `record --replace`. The record is `built`
   again, and the marker stays.
3. A new handoff goes out, and ai-stack returns a new receipt.
4. `verify-receipt` promotes the new record to `pinned`.
5. The same PR deletes the stale marker.

## Consumers

Every consumer accepts only a `pinned` verdict from the default strict call, and refuses
`stale` and `built`.

- **v13 ACTIVATE readiness** admits the review-runner image only on that verdict (IF-XR-2,
  agent-harness#2107).
- **The LANEEXEC `openshell` route** takes the helper path and digest only from a record that
  passes that call. Otherwise it refuses with a typed refusal and launches nothing (IF-XR-3,
  agent-harness#2108).
- **The SL-5 hand-back to ai-stack** posts the `pinned` record's sha256 on
  ViperJuice/ai-stack#504.

This phase does not edit ACTIVATE or LANEEXEC. Those obligations belong to the issues above.

## Not in scope

These are out of scope:

- image signing;
- the per-target SEATS REMOTE images;
- any adapter, route, `policies.json`, LANEEXEC or ACTIVATE change;
- a CI image build or push;
- a multi-platform index;
- any push, pull or other action on `ai` by agent-harness.
