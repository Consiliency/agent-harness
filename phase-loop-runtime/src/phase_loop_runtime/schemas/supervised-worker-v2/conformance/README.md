# Conformance vectors: admitted_launch_envelope.v1 and supervised_run_status.v1

Status: **provisional**. These files define a harness-neutral, language-neutral contract and its golden valid and
negative vectors. They name no deployment, repository, host or application, and are meant to be vendored unchanged.

## Files

| File | Content |
|---|---|
| `../admitted-launch-envelope.schema.json` | JSON Schema (draft 2020-12) for the envelope a harness receives after admission, its fixed enforcement tiers (`x-enforcement-tiers`) and its semantic rules (`x-semantic-rules`) |
| `../run-status.schema.json` | JSON Schema for the journal line, projection, page request, page and reader view (`$defs`), journal rules (`x-journal-rules`) and semantic rules (`x-semantic-rules`) |
| `envelope.vectors.json` | admission and caller-context echo vectors |
| `run-status.vectors.json` | journal, projection, liveness, reader-view and page vectors |
| `SHA256SUMS` | sha256 of the four files above and this README; pin its digest when vendoring |

## Reading a vector

Each file has `cases`. A case with `role: control` carries a complete `input` and expects no diagnostics. A case with
`role: negative` names its `control` and a `patch`: a JSON Patch (RFC 6902, operations `add`, `remove` and `replace`
with RFC 6901 pointers) applied to a copy of the control's input. When `rehash` is `true`, recompute
`envelope.envelope_digest` after patching, so the negative authority self-verifies and must be refused on its merits.

`expected` is the exact set of diagnostic codes a conforming reader or validator reports. A refusal that comes from
JSON Schema validation instead of the named semantic rule does not satisfy a negative vector: every vector is
schema-valid by construction. `expected_effect`, when present, is matched as a subset of the reported effect:

- admission: `attempt.state` is `queued` when admitted, or `refused` with `worker_invocations: 0` and a typed
  `refusal` (`reason`, `constraint`, `tier`) before any process starts;
- journal and liveness: `display` lists the state shown per attempt (`unknown` for any fail-closed journal
  condition; `stale_unknown` when the owner is not live);
- projection: `display` is `current` or `stale`.

## Digests and bytes

- `envelope_digest` is the SHA-256 of the RFC 8785 (JCS) serialization of the envelope without `envelope_digest`.
  The vectors use ASCII object keys and integers only, so JCS key order is plain code-point order.
- A journal attempt is a list of segments. Each segment lists its lines: an object line is serialized with JCS and a
  string line is the exact raw text of that line. Segment bytes are the lines joined by LF, plus a final LF when
  `final_newline` is `true`. A segment header's `previous_segment_sha256` is the SHA-256 of the previous segment's
  bytes.

## Reader obligations the vectors exercise

- `seq` is the only ordering; `observed_at` is informational.
- A torn last line, an unknown schema or version, a foreign writer, a seq gap or regression, a broken segment chain or
  a foreign attempt identity fail closed: the attempt is shown unknown and the reader never truncates or repairs.
- `refused` exists only before a process starts. `finished` needs `termination {reason, signal, by}`.
  `completed` is runtime data, never a work outcome or evidence.
- Records hold digests and repository-relative locators only; event text is at most 200 characters, has no line
  breaks and is labelled `untrusted_display_text`.
- A later attempt never copies an earlier attempt's evidence; equal proposal digests across attempts are legitimate
  when each attempt binds its own envelope, run and attempt ids.
- A projection behind the journal tail is shown stale; pages are bounded (at most 100) and report `has_more` and
  omitted counts.
- `caller_context` is opaque and echoed byte-for-byte.
