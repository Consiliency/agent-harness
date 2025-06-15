# Publication Source Audit Review

Tracks Consiliency/agent-harness#893. Base: `8954c9fe`.

## Scope

Normal FABPUB publication gains a bounded exception for existing, owned, regular
Python implementation files whose names match the credential heuristic. Both
parent and staged blobs must parse and contain a top-level function/class; the
complete staged blob must pass pinned offline detect-secrets 1.5.0 detectors.
There is no path allowlist, inline suppression, repository scanner configuration,
or online credential verification. Other artifact names remain blocked.

The audit records metadata only and is rederived against frozen objects before
normal transaction construction and on resume. Required evidence covers the
frozen changed-path set, not every owned path. Existing prebuilt behavior and
FABPUB transaction identity/envelope schemas are unchanged. Heuristic content
scanning does not prove absence of deliberately obfuscated secrets.

## Verification

- Baseline: 15 publication tests passed.
- Reconciled source: 149 focused publication, FABPUB, recovery and train tests passed.
- Wheel build passed; all 42 packaged publication tests passed without the
  source-mode provenance warning.
- Pinned Gitleaks v8.21.2 diff scan, changed-file pyflakes and `git diff --check` passed.
- Audit-only consumer probe accepted both previously blocked staged Python files;
  no consumer publication or fleet-wide runtime installation was performed by that probe.
- Source-mode tests emitted the existing contract-floor provenance warning;
  no full-suite or production-readiness claim is made.

Source/dependency/test patch SHA-256:
`379f2739d315ae43eda2ce026e852bbfd24810ea2ebf3a4e95c53fbe45e0ef8b`.

Tested wheel SHA-256:
`d2841239de029ee46f8a2cdbfd316d778403e75edda52f8f8e19aebabbe56574`.

## Review

Round cap: three. Four seats across three vendors, with default heartbeat policy
and no shortened deadlines. Claude was unavailable under the typed TUI adapter
condition tracked by Consiliency/agent-harness#806; a distinct-lens Grok seat was
the explicit replacement, not a claimed Claude review.

Round one found missing direct durable-resume validation and a mismatch between
staged audit scope and recovery's broader owned-path scope, including prebuilt
compatibility. All seats finished before changes. Those findings were reconciled
with construction/resume checks, frozen-diff scoping, sorted records, and targeted
regressions. Round two is pending; this report is not yet approval to merge.

| Artifact | SHA-256 |
| --- | --- |
| Round-one bundle | `03b6cf60971e8b4c774f113475783ef1b2e9178f6e2ccc3528a06011ff78f931` |
| Round-one results | `0baa8d84bc3dd3a5154b26d5f9625d20f68097523dbf41dfa27d71e2672d2765` |
| Round-two bundle | `49007f9fd06487f77c4b6fb16541b58d280cdf7ed5e784acdba5fe69efea103d` |

No hardware, cloud credentials or installed services changed.
