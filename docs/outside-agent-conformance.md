# Outside-Agent Conformance

Consiliency/spec owns outside-agent contract truth. Agent-harness consumes a
pinned metadata view of that contract: schema version, package version or git
SHA, vector manifest name, vector manifest hash, source owner, and redaction
posture.

The advisory path is not acceptance authority. It can catch cheap mistakes and
explain readiness before review, but governed-pipeline remains the real
acceptance fence and reruns validation against the same pinned contract.

Agent-harness must not copy canonical outside-agent schemas, raw vector bodies,
provider payloads, secrets, or local environment values. During the pre-release
train it may validate a Consiliency/spec checkout by immutable git SHA and
vector manifest hash. Once Consiliency/spec is published, production consumers
should pin the published `consiliency-spec` package version and the same
manifest hash.

## Shared Core

`phase_loop_runtime.conformance.outside_agent_core.validate_outside_agent_submission()`
is the shared deterministic core for OACORE consumers. It accepts local
metadata-only submission dictionaries for `work_request`,
`implementation_submission`, and `ambiguity_report`; it does not call provider
clients, read credentials, consult network services, or load environment secret
values.

The return value is an `OutsideAgentConformanceVerdict` with the pinned verdict
schema version, typed submission kind, `pass` or `blocked` status, typed
`OutsideAgentBlocker` entries, the pinned contract metadata, an input digest,
repo-relative provenance refs, metadata-only evidence refs, and
`redaction_posture="metadata_only"`.

The core fails closed on unsupported schema versions, unsupported submission
kinds, unknown fields, incomplete metadata, absolute paths, path traversal,
missing digests, digest mismatches, raw payload fields, provider response
bodies, raw logs, copied vector bodies, local environment values, and
secret-shaped fields or values. Verdict output is limited to metadata, digests,
repo-relative refs, typed failure information, contract pin metadata, and
metadata-only vector result evidence.

`outside_agent_vectors.run_outside_agent_vectors()` runs metadata-only vector
manifests through the same core and compares expected outcomes without copying
canonical Consiliency/spec vector bodies into this repository.

OACORE only produces shared conformance facts. OAMOCK can later wrap those facts
with advisory labeling. OAREAL can later attach the governed-pipeline runtime
surface and authoritative acceptance behavior.

## Advisory Preflight

Producers and outside agents can run a local advisory preflight before attaching
work to a GitHub issue or PR:

```bash
phase-loop outside-agent-preflight path/to/outside-agent-submission.json --output outside-agent-advisory.json
```

The command reads one local metadata-only outside-agent submission JSON file,
runs the same shared core, and emits advisory evidence with
`authority="advisory"` and `redaction_posture="metadata_only"`. The output
contains the typed core status and blockers, the pinned contract metadata, an
input digest, repo-relative provenance refs, and metadata-only evidence refs. It
does not include `accepted_for_merge`, `merge_verdict`, or any acceptance field.

Exit code `0` means the advisory preflight found no blocker. Exit code `2`
means the submission is malformed, `3` means it contains redaction-forbidden
content, `4` means provenance or digest metadata failed, and `1` is reserved for
unexpected internal failures.

Attach the generated advisory JSON as supporting evidence only. It can help
reviewers and producers find cheap contract mistakes early, but governed-pipeline
remains the authoritative acceptance and merge boundary.
