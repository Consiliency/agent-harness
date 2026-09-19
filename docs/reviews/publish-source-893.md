# Publication Source Audit Review

Tracks Consiliency/agent-harness#893. Base: `8954c9fe`.

## Scope

Normal FABPUB publication gains a bounded exception for existing, owned, regular
Python implementation files whose names match the credential heuristic. Both
parent and staged blobs must parse/compile without warnings and contain a top-level function/class; the
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
- Latest reconciled source: 155 focused publication, FABPUB, recovery and train tests passed.
- Wheel build passed; all 48 packaged publication tests passed without the
  source-mode provenance warning.
- Pinned Gitleaks v8.21.2 diff scan, changed-file pyflakes and `git diff --check` passed.
- Audit-only consumer probe accepted both previously blocked staged Python files;
  no consumer publication or fleet-wide runtime installation was performed by that probe.
- Source-mode tests emitted the existing contract-floor provenance warning;
  no full-suite or production-readiness claim is made.

Source/dependency/test patch SHA-256:
`2596eb3b6e28cbfa81f427cf5542d2d3f3ab646886c062de13650462b2b16f4f`.

Tested wheel SHA-256:
`468edd48c271400c1520d416914cc365c7738e17cd9f0dcf0c593fec0a761ab6`.

## Review

Initial round cap: three, explicitly lifted by the user for closure review.
Four seats across three vendors, with default heartbeat policy
and no shortened deadlines. Claude was unavailable under the typed TUI adapter
condition tracked by Consiliency/agent-harness#806; a distinct-lens Grok seat was
the explicit replacement, not a claimed Claude review.

Round one found missing direct durable-resume validation and a mismatch between
staged audit scope and recovery's broader owned-path scope, including prebuilt
compatibility. All seats finished before changes. Those findings were reconciled
with construction/resume checks, frozen-diff scoping, sorted records, and targeted
regressions. Round two confirmed those fixes and raised semantic compilation and
Git-path concerns. Semantic compilation failures reproduced and were fixed;
nested-path and glob-substitution claims did not reproduce with the actual Git
commands or existing tests. Literal pathspec selection and byte-exact returned
path validation were nevertheless made explicit and regression-tested.

Round three left three standing AGREE verdicts (Grok adversarial and Gemini fresh,
Grok correctness carried from round two). GPT-6 Astra found that compiler warnings
could render credential-bearing source lines before scanning. The local fix
turns all parsing/compilation warnings into rejected input, uses a synthetic
filename, and adds two diagnostic-redaction regressions. Verification above is
for that fix. After the user lifted the cap, GPT-6 Astra reviewed the exact helper
delta against round three at commit `4348080d54c27d6f683549284b59944d92f86136`
and returned AGREE: no blocking finding or directly introduced regression.
The reviewer confirmed caught parser/compiler warnings, synthetic filenames,
fixed rejection diagnostics, and both diagnostic-redaction regressions.

All four seats now have standing AGREE verdicts: fresh GPT-6 Astra closure,
carried Grok adversarial/Gemini round three, and carried Grok correctness round
two. No blocking finding was waived. The current implementation commit passed
GitHub suite, lint, chronology, docs, secret, check and package verification gates.
Documentation-only closeout still requires its own publication checks.
PR: Consiliency/agent-harness#894. This is not installed-door acceptance.

| Artifact | SHA-256 |
| --- | --- |
| Round-one bundle | `03b6cf60971e8b4c774f113475783ef1b2e9178f6e2ccc3528a06011ff78f931` |
| Round-one results | `0baa8d84bc3dd3a5154b26d5f9625d20f68097523dbf41dfa27d71e2672d2765` |
| Round-two bundle | `49007f9fd06487f77c4b6fb16541b58d280cdf7ed5e784acdba5fe69efea103d` |
| Round-two results | `6981817c80dd3b7f2b3b7197309cde7116c0dcc64fffc34935100a810619d876` |
| Round-three bundle | `6b591557ae062ac6bd11bb535c7434b251e5c821a200fd004d4cd0825f590902` |
| Round-three results | `7d5277d7a9d2c25e187dcf0db6188ef83460102fc26fc708ae7313897154b2ae` |
| Warning closure bundle | `d1b4951c50dc957308587eaeea103d7306366fee0a3b7d4b420f9304f8dceadb` |
| Warning closure results | `9b9bd72d3efb2c28d6fa4bb17e371ab5a6e48a5e01ff710c7cb0ce379f7ee99c` |

No hardware, cloud credentials or installed services changed.
