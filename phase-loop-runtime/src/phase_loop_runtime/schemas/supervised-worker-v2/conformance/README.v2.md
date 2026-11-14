# Conformance vectors: admitted_launch_envelope.v2

Status: **provisional**. `admitted_launch_envelope.v2` is a harness-neutral, language-neutral contract, published
alongside the frozen `admitted_launch_envelope.v1`. It names no deployment, repository, host or application, and is
meant to be vendored unchanged. `README.md` in this directory still describes v1 and `supervised_run_status.v1`; it is
part of the frozen v1 pin set, so it is not edited.

## Files

| File | Content |
|---|---|
| `../admitted-launch-envelope.v2.schema.json` | JSON Schema (draft 2020-12) for the v2 envelope, plus its normative annotations: tiers, constraint semantics, route qualification and grant coverage, locator grammar, environment commitment, process boundary, digest forms, apply outcomes, evaluation order and semantic rules |
| `envelope.v2.vectors.json` | admission and caller-context echo vectors |
| `envelope.v2.canonical.vectors.json` | RFC 8785 number, document and parse-boundary vectors, and source-tree capture vectors |
| `envelope.v2.apply.vectors.json` | write_scope apply-check vectors and runtime-journal vectors |
| `README.v2.md` | this file |
| `SHA256SUMS` | its first five lines are the v1 manifest, byte for byte; the lines after them add the five v2 files |

v1 files and their digests do not change. A v1 envelope is not a v2 envelope (the `schema` const differs and `launch`
is required); a reader selects the contract by `schema`.

## What v2 binds

v2 keeps every v1 field with its v1 meaning and adds one required, closed `launch` block. It binds, by digest or
logical locator only, every input that determines what process starts and what it is given:

| `launch` field | Binds |
|---|---|
| `action`, `transport_id`, `stdin` | execution or review; the route the harness selected; stdin is the instruction bytes once then end of file (`input`) or nothing (`devnull`) |
| `instructions` | SHA-256 and length of the exact instruction bytes, and their `source` (null only when genuinely inline) |
| `references` | ordered role, SHA-256, length and `source` of every other consumed byte sequence: exactly one `baseline`, plus `context` and `config` files |
| `argv` | SHA-256 of the UTF-8 RFC 8785 array that starts the outermost chain entry, and its length |
| `executable_chain` | every wrapper, outermost first, then the executable: locator (repository-relative or a declared name) and raw-file SHA-256 |
| `workspace_state` | base commit (or null), tree-manifest digest of the materialized source tree including overlays, the worker `cwd`, and the workspace-to-protected target map |
| `environment` | SHA-256 of the redacted environment object (no secret values), and the id and raw-byte digest of the policy that builds and classifies it |
| `trusted_policy` | raw-byte SHA-256 of the trusted configuration, the template (including declared helper transformations) and the qualification evidence (null when there is none) |
| `stop` | `timeout_seconds` (integer, 1 to 3600) and `deadline_action` |
| `grants` (optional) | `{canonical_form, sha256}` of the filesystem view, descriptor capabilities, dependency projection, supervisor identity and egress policy actually applied |

Tier and constraints, and the assignment, snapshot, project and dependency authority, stay where v1 has them.
`caller_context` stays required and opaque, and is never a source of any launch input.

## Locators and sources

Every relative locator follows `x-locator-grammar`: one or more `/`-separated segments, none empty, `.` or `..`; no
`:`, backslash, control character, or leading, trailing or repeated `/`. Invalid input is refused
(`locator_not_repo_relative`), never normalized; only a cwd path may be exactly `.`.

A source is one of:

- `{"namespace": "workspace", "path": ...}`: a path in the captured source tree. The tree must hold exactly one
  regular or executable file entry at that path with the same digest. A symlink or a missing entry does not count.
- `{"namespace": "declared_root", "root": ..., "path": ...}`: under a root the trusted configuration declares. The
  physical location stays local.
- `{"namespace": "descriptor", "descriptor": ...}`: behind a descriptor that the bound descriptor_capabilities grant
  lists.

Sources outside the workspace are captured, hashed and rechecked where they are. They are never copied into the
workspace to fit the schema.

The working directory is `{"namespace": "workspace", "path": ...}`, relative to the source tree, or
`{"namespace": "view_root", "root": ..., "path": ...}`, under a root the bound filesystem_view grant declares. Moving the
cwd never changes the source-tree digest. Files a route discovers from its cwd must be bound as references.

## Environment commitment and secrets

`environment.map_sha256` is the SHA-256 of the UTF-8 RFC 8785 serialization of the closed object below:

- `non_secret`: every non-secret variable of the effective worker environment, with its value;
- `secret_names`: the secret variables actually present, sorted by UTF-16 code units, names only.

The bound environment policy classifies every variable, in trust, as non-secret or as secret with its credential
source. A variable it does not classify fails closed. Each secret's source must be authorized by the single matching
qualification record (`grant_unqualified` otherwise).

No secret value, and no digest of one, may appear in any commitment: the envelope itself, `caller_context`
included (member names, nested values and arrays, after decoding escapes), argv, references, and policy, template or
grant documents. `caller_context` stays opaque. That means no field has a meaning, and generic secret-safety
validation is not interpretation. Its producer must not put secrets in it, and a known secret or derived digest
found there is `launch_input_unbound`; the payload is never redacted to pass. A route that would need one bound is not representable. Rotating a secret value leaves the envelope
unchanged; the vectors `E2-secret-env` and `E2-secret-env-rotated` show this. The digest is deterministic, unsalted
and unkeyed. It commits the non-secret content but does not keep it confidential.

## Process boundary and delivery

- **argv:** binds the outermost spawn.
- **environment and cwd:** bind the effective worker after the helper transformations declared in the bound template.
  These are argument consumption, consumed and set variables, and a cwd change. The spawn environment and cwd are
  exactly what those transformations need, with nothing ambient.
- **deadline:** starts at the first launch-chain process and is never restarted.
- **qualification probes:** run before admission. They are not worker invocations and must not change captured
  material.
- **refusals:** every admission refusal happens with zero launch-chain processes and zero worker invocations. A
  failure after the chain starts is `running -> finished` (`failed_to_start`), never `refused`.

Interactive terminal delivery is not representable in v2. That covers a pseudo-terminal, prompt responses, paste
framing and input after output. Routes that need it are out of scope and refused; no transport label or grant
changes that.

## Tiers, qualification and grants

`x-enforcement-tiers` states each tier's semantics and limits; it does not qualify any installed tool.

Admission under a defined tier needs **exactly one** validator-held record that matches the route key. That key is the
tier, action, transport, executable chain, template digest and qualification digest. Zero or several matches, including
duplicates, are `route_not_qualified`, decided before any grant check. Records are never chosen by order or merged.
The single record covers each grant by its exact `{canonical_form, sha256}`. A template or profile record with
placeholders does not cover a concrete per-run grant.

A tier's `checked_before_apply` guarantee runs whether or not `required_constraints` lists it. The write_scope apply
check rejects the whole proposal, or applies all of it, as an `x-apply-outcomes` work outcome. The attempt's journal
is still `running -> finished`; a post-launch `refused` is `refused_after_launch`. `write_prevention` is never
provided by a defined tier.

## Reading a vector

Each envelope case has `role`:

- `control`: a complete `input`, admitted (`expected: []`, effect `queued`).
- `negative`: a JSON Patch (RFC 6902 `add`, `remove` and `replace`, RFC 6901 pointers) applied to a copy of the named
  control's input. The envelope stays schema-valid; it must be refused by the semantic rules in `expected`.
- `schema_negative`: a patch that makes the envelope schema-invalid. `expected` is `["envelope_schema_invalid"]`, and
  `expected_schema_errors` is the exact set of `{instance_path, keyword}` pairs. A `type` failure masks the other
  keywords at its node, and `anyOf` is reported at its own node.

With `rehash: true`, recompute `envelope_digest` by RFC 8785 after patching. `expected` is the exact set of diagnostics
of the first reporting stage of `x-evaluation-order`. `expected_effect` is matched as a subset. `finding` names the
review item a case closes.

An admission input has three parts.

- `envelope`: the record under test.
- `validator_context`: what the validator holds independently. That is the expected authority values,
  `timeout_max_seconds`, and `qualified_routes`. Each route has `tier`, `action`, `transport_id`, `executable_chain`,
  `template_sha256`, `qualification_sha256`, `grants` (kind to `{canonical_form, sha256}`) and `credential_sources`.
- `launch_material`: what the harness captured and is about to use. Text stands for exact UTF-8 bytes.
  - `instructions`, `references[]`: `source`, `content` (null when not captured) and `within_root`.
  - `stdin`: `mode`, which is `pipe`, `devnull` or `pty`, and `writes`, each `{after: start|output, text}`.
  - `process`:
    - `spawn` and `worker`, each `{argv, env, cwd}`;
    - `cwd_resolution` (`within_root`, `discovered` sources);
    - `deadline` (`origin`, `seconds`, `restarted_at_helper`);
    - qualification `probes`.
  - `executable_chain`: the resolved-file digests.
  - `workspace`: `base_commit`, a `capture` listing of filesystem objects, and `target_map`.
  - `environment`: `policy_id`, and `policy` as JSON text with `classification`.
  - `policy`: `config` (with `root <id> = ...` lines), `template` (JSON text with `argv`, `spawn_cwd` and `helpers`),
    `qualification`, and `grants`. Each grant is `{canonical_form: raw_bytes, text}` or
    `{canonical_form: rfc8785, value}`.
  - `unbound_inputs`: any input not covered by the launch block.

## Canonicalization (envelope.v2.canonical.vectors.json)

RFC 8785 throughout:

- members are sorted by UTF-16 code units;
- numbers use the ECMAScript form, and `-0` serializes as `0`;
- strings use only the RFC 8785 escapes;
- the output is UTF-8.

Before anything is hashed, the v2 input boundary is checked on raw input and again on in-memory values:

- valid UTF-8, no duplicate member names, no lone surrogates;
- `__proto__` is an ordinary member name like any other;
- numbers are finite binary64 values, and an integer-valued number must lie within -9007199254740991 through
  9007199254740991, whatever its spelling. So `9007199254740992`, `9007199254740992.0`, `9.007199254740992e15`,
  `1e21` and `999999999999999900000` are all refused. Non-integral numbers stay valid.

This is a deliberately narrower v2 profile, not a claim that RFC 8785 disallows larger doubles; large opaque
identifiers can be strings. Unrepresentable launch input is `launch_input_unbound`.

The file contains:

- `numbers`: serializer primitives only. They are IEEE-754 bit patterns and their ECMAScript Number-to-String form,
  with the RFC 8785 Appendix B rows copied from the RFC. They prove serialization, not acceptance;
- `domain`: number tokens, each accepted with its canonical form or refused, through both raw parsing and in-memory
  commitment;
- `documents`: raw text, the exact canonical text and its digest, or `reject`;
- `alternates`: wrong preimages that must not match;
- `tree_captures`: capture listings, the manifest each must yield and its digest, or `unbindable`;
- `tree_alternates`: the manifests a wrong walk produces, which fail `launch_workspace_mismatch`.

Capture follows these rules:

- The root `.git` (directory, file or symlink) is excluded without descending; a nested `.git` is ordinary content.
- A regular file is `executable_file` when its POSIX mode has any of `0o111` set.
- A symlink hashes its raw target bytes and is never followed.
- Entries are sorted by the UTF-8 bytes of their path.
- Other object types, duplicate or ungrammatical paths, and missing modes are unbindable.
- A represented file, symlink or other non-directory object is never a proper ancestor of another listed path,
  whatever the listing order; directories may be implicit. Capture never traverses a symlink ancestor.

## Apply and journals (envelope.v2.apply.vectors.json)

- `applications`: a proposal against the bound scope and target map. Each gives the `x-apply-outcomes` outcome and
  the protected state afterwards, which is unchanged unless the outcome is `proposal_applied`. Every fixture has an
  empty `required_constraints`.
- `journals`: `supervised_run_status.v1` journals whose lines validate against the frozen `journal_line` schema, with
  the diagnostics the frozen rules give.

## Worked example: grants with per-run resources (control `E2-grants-worked`)

A run writes its output to a run-specific resource. The contract names that resource by logical identity, purpose and
access (`run-output`, `output`, `write`). The directory it maps to, any descriptor number and any host path stay local.
The trusted evidence that establishes the concrete mapping for this run is the qualification evidence the validator
holds, a per-run attestation here; its digest is bound by `trusted_policy.qualification_sha256`.

`filesystem_view_sha256`, form `rfc8785` (in-memory structure). Exact UTF-8 preimage:

```json
{"resources":[{"access":"write","id":"run-output","purpose":"output"}],"roots":[{"access":"read","id":"tree"}]}
```

SHA-256: `53b5dee41446896ad01e9dbf6690489b8384a263a8c3c406b7bbc4cb7b6c3e27`

`descriptor_capabilities_sha256`, form `rfc8785` (in-memory structure). Exact UTF-8 preimage:

```json
{"descriptors":[{"access":"write","id":"run-output","purpose":"output"}]}
```

SHA-256: `bec2a4cd7032cb76308098bce96308a231bf93127eff0ab673a40ec87a212957`

`egress_policy_sha256`, form `raw_bytes` (the loaded document, rules in order). Exact bytes:

```text
egress v1
1 allow api.example:443
2 deny *
```

SHA-256: `ed47ec90e18651569e52e868eded06823ebdffd6803805ea8c245859e1d433b7`

The envelope's `launch.grants`:

```json
{
  "filesystem_view_sha256": {
    "canonical_form": "rfc8785",
    "sha256": "53b5dee41446896ad01e9dbf6690489b8384a263a8c3c406b7bbc4cb7b6c3e27"
  },
  "descriptor_capabilities_sha256": {
    "canonical_form": "rfc8785",
    "sha256": "bec2a4cd7032cb76308098bce96308a231bf93127eff0ab673a40ec87a212957"
  },
  "egress_policy_sha256": {
    "canonical_form": "raw_bytes",
    "sha256": "ed47ec90e18651569e52e868eded06823ebdffd6803805ea8c245859e1d433b7"
  }
}
```

The single validator-held qualification record for this route, which covers exactly these commitments (`grants`, serialized by RFC 8785):

```json
{"descriptor_capabilities_sha256":{"canonical_form":"rfc8785","sha256":"bec2a4cd7032cb76308098bce96308a231bf93127eff0ab673a40ec87a212957"},"egress_policy_sha256":{"canonical_form":"raw_bytes","sha256":"ed47ec90e18651569e52e868eded06823ebdffd6803805ea8c245859e1d433b7"},"filesystem_view_sha256":{"canonical_form":"rfc8785","sha256":"53b5dee41446896ad01e9dbf6690489b8384a263a8c3c406b7bbc4cb7b6c3e27"}}
```

Its full route key and coverage:

```json
{
  "tier": "provider_readonly_patch_return_audit",
  "action": "execution",
  "transport_id": "cli",
  "executable_chain": [
    {
      "locator_kind": "declared",
      "locator": "provider-cli",
      "sha256": "4b70047af52679bb9d2955b7270a2f1941c6942ecbd8540f75229d7819f933a0"
    }
  ],
  "template_sha256": "297f770282a217a9b0c482d20b080d1baa9eb7bf9ec308fb013ccf501bcc1fe0",
  "qualification_sha256": "ef315227a572d65ee3bd3092be7c0fe9b655867496c6253a8dcd0025b73c3a77",
  "grants": {
    "filesystem_view_sha256": {
      "canonical_form": "rfc8785",
      "sha256": "53b5dee41446896ad01e9dbf6690489b8384a263a8c3c406b7bbc4cb7b6c3e27"
    },
    "descriptor_capabilities_sha256": {
      "canonical_form": "rfc8785",
      "sha256": "bec2a4cd7032cb76308098bce96308a231bf93127eff0ab673a40ec87a212957"
    },
    "egress_policy_sha256": {
      "canonical_form": "raw_bytes",
      "sha256": "ed47ec90e18651569e52e868eded06823ebdffd6803805ea8c245859e1d433b7"
    }
  },
  "credential_sources": []
}
```

A record covering only the placeholder template (`{run_output}` in place of `run-output`) does not cover this grant
(`S2-grant-template-only`). Neither does a record that lacks the egress commitment (`S2-grant-uncovered-per-run`) or
lists the same digest under another form (`S2-grant-form-wrong`). Changing the applied bytes or structure is
`launch_policy_mismatch` (`S2-grant-raw-whitespace`, `S2-grant-raw-rule-order`, `S2-grant-jcs-value-changed`,
`S2-grant-jcs-list-order`).
