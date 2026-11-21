# GROKROLL v1 contract: grok release catalog and measured-build query (frozen artifact)

Status: draft r4 (2026-11-21), after three independent plan reviews and a scope split. Frozen
once the plan review accepts it. A change after that is an erratum appended at the end,
with a repin in `specs/phase-plans-grokroll-v1.md`.

**Scope.** This contract covers the release catalog, its provenance and enforcement, and
the read-only status query. The job that stages a new release and the approval of its
counted launches are a deferred follow-up phase, GROKROLL-B (§7). Nothing here stages,
executes or measures a grok build.

"Tool-surface" means `plans/artifacts/grok-tool-surface-contract-v1.md`. "AGYROLL" means
`plans/artifacts/agyroll-v1-contract.md`. This contract adds to both and edits neither.

## §0 Facts and assumptions

Observed on 2026-11-21 from the public npm registry and, on one installed host, by reading
files only. No provider binary was executed and no model was called.

| Fact | Observation |
|---|---|
| Cadence | `@xai-official/grok` 1.0.88 to 1.0.93 were published on six consecutive days. |
| Stable marker | The main package's `latest` dist-tag (1.0.92) trails its `alpha` tag (1.0.93). |
| Payload package | `@xai-official/grok-linux-x64`, pinned by the main package's `optionalDependencies` at the same version. Its own `latest` dist-tag is stale (0.1.220). |
| Payload member | One binary member, `package/bin/grok.br`: the ELF, brotli-compressed. About 59 MB compressed, 208 MB expanded. |
| Identity | The expanded member is byte-identical to the installed native binary of the same version (one host, one version). |
| Version documents | A per-version registry document carries no publication time; only the package's full document does (`time`). |
| Publisher attestation | None; the attestations endpoint returns 404. |
| Evidence readers | `grok_tool_surface.load_host_record` returns `None` alike for a missing record, a denied read, a wrong mode and a parse failure. `host_route_current` returns `False` alike for a withdrawn route and an unreadable attempt register. `panel_invoker._read_grok_receipt` returns decoded content before any field is validated, and raises for a missing file. |
| Launch admission | `grok_tool_gate` always needs a `tool_probe.v1` receipt. A receipt with no `basis`, or `basis: list_tools`, and no frozen fields is a listing receipt; a `frozen_measurement` receipt is a cache that is re-resolved against the record on every use. |
| Hosted test install | The ordinary hosted pytest job installs `./phase-loop-runtime[visual,claude-sdk]` by an explicit pip line; it does not read the `test` dependency group. That line is mirrored by hand in `scripts/local_check.py` (`CI_TEST_DEPS`) and in the Gate A suite container (`ci/dagger/src/agent_harness_ci/main.py`), and is asserted verbatim by `tests/test_local_check.py` and `tests/test_ci_xdist_adoption.py`. |
| Shipped surface catalog | `data/grok_tool_surfaces.json` is empty; measured records exist only host-locally. |

**Signature vector**, verified with OpenSSL on 2026-11-21 and used as a test input:

- message, UTF-8: `@xai-official/grok-linux-x64@1.0.89:sha512-Pn8FmBEpl/r/rGmnKbHFHmOdJdy/cT0gaJNDO67bPIF0YqCDWvpRo/MdDnzS+1F2DVIzunypsMRTEdESB8H7zw==`
- signature, base64 DER: `MEQCIE1vGxkiiQQ6NRBZOGowpKeSYjbjYijpgqVbuiCqSTsBAiAGZ0eiOBIRKjikQAnrFhYPpSy0UjrsxqG+Qm528GFBTw==`
- key id `SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U`, SubjectPublicKeyInfo, base64 DER:
  `MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEY6Ya7W++7aUPzvMTrezH6Ycx3c+HOKYCcNGybJZSCJq/fd7Qa8uuAKtdIkUQtQiEKERhAmE5lMMJhP8OkDOa2g==`
- algorithm: ECDSA P-256 over SHA-256.

**Assumption A1 — the default subject is the native binary.** The production resolver
(`panel_invoker._seat_provider_source`) follows only the wrapper shapes
`_shell_wrapper_target` recognises. Gate: §3's default subject must begin with the ELF
magic, otherwise the query fails `status_unavailable` (`subject_not_native`) instead of
reporting a launcher's digest. A false A1 on a supported wrapper shape stops the status
lane.

The installed-binary identity fact is not relied on for admission: a host whose binary
differs from the catalog digest gets `release: "unknown"` (§3) and no shipped record
applies to it.

## §1 Release catalog

`phase_loop_runtime/data/grok_releases.json`, read only through `importlib.resources`. It
lands empty and stays empty until the gate of §2.5 is attested. It holds at most
`MAX_RELEASES = 24` entries.

```json
{
  "schema": "grok_release_catalog.v1",
  "platform": "linux-x64",
  "releases": [
    {
      "version": "1.0.89",
      "package": "@xai-official/grok-linux-x64",
      "tarball_integrity": "sha512-<base64 of 64 bytes>",
      "registry_keyid": "SHA256:<base64>",
      "registry_signature": "<base64 DER>",
      "member": "package/bin/grok.br",
      "binary_sha256": "<64 lowercase hex>",
      "binary_bytes": 208487936,
      "pinned": false
    }
  ]
}
```

**Field classes.**

| Class | Fields | Rule |
|---|---|---|
| Registry-derived, immutable | `version`, `package`, `tarball_integrity`, `member`, `binary_sha256`, `binary_bytes` | re-derived and compared exactly (§2.2) |
| Registry-signed, verifiable offline | `registry_keyid`, `registry_signature` | the entry's own signature must verify under a pinned key; it need not equal what the registry serves today |
| Review-controlled | `pinned` | set only by a reviewed pull request; exempts from aging (§5.2) |

Nothing time-dependent or locally observed is stored.

**What the stored signature binds.** The name, the version and the tarball integrity. It
does not bind `binary_sha256` or `binary_bytes`; only online re-derivation (§2.2 steps 4 to
6) ties those to the signed integrity.

**Loader rules**, all fail-closed (the loader reports the catalog `unavailable`, §3.1): a
file over 256 KiB; invalid JSON or a duplicate object key at any level; a wrong `schema` or
`platform`; any missing or unknown key; a wrong JSON type; `version` not canonical numeric
`MAJOR.MINOR.PATCH`; `package` or `member` other than the literals above; a digest not 64
lowercase hex; an integrity not of the stated form; `binary_bytes` outside
`1..MAX_BINARY_BYTES`; a `registry_keyid` not in `REGISTRY_KEYS`; a duplicate version or
digest; entries not sorted by version; more than `MAX_RELEASES` entries. One bad entry
voids the file.

**Order.** Versions compare as integer triples. No other ordering exists.

**Parity with the surface catalog**, enforced whenever the gate file reads attested (§2.5):
every `surfaces[].binary_sha256` is a release member, and the `x.y.z` token parsed from
that surface's `version` text equals the member's `version` exactly. While unattested, a
surface may exist with no member; §3 reports it `release: "unknown"`.

## §2 Provenance

An entry is believed because a check anyone can re-run derives it from a fixed upstream,
not because of who wrote it (AGYROLL's model).

### §2.1 Fixed upstream and transport

- Registry `https://registry.npmjs.org` only: the main package and the payload package.
- Transport rules as `agy_provenance._Transport`: no proxy, no credential, the compiled-in
  trust store, no redirect to another host. That class is reused or its rules copied with
  the same tests; `agy_provenance.py` is not edited.
- **Stable** is the version the main package's `latest` dist-tag names when observed. The
  tag only chooses what a person derives. Re-deriving an entry never consults a tag or a
  time.

### §2.2 Derivation `derive_release(version)`

Deterministic: the same version gives the same six derived fields or a refusal.

1. The main package's document for `version` has that exact name and version, and its
   `optionalDependencies["@xai-official/grok-linux-x64"]` equals `version` exactly.
2. The payload package's document for `version` has that exact name and version, a
   `dist.tarball` equal to
   `https://registry.npmjs.org/@xai-official/grok-linux-x64/-/grok-linux-x64-<version>.tgz`,
   and a `dist.integrity` of the §1 form.
3. A signature in `dist.signatures` whose `keyid` is in `REGISTRY_KEYS` verifies, by §0's
   algorithm, on the UTF-8 bytes `<name>@<version>:<integrity>`. `REGISTRY_KEYS` is a
   constant in `grok_roll/catalog.py`, beside `verify_entry_signature`, with one entry: the
   key id and public key of §0. The key id is the registry's label and is matched as a
   string. A key the registry lists but the constant lacks is unknown. Changing the
   constant is a reviewed code change.
4. The tarball is fetched once, at most `MAX_TARBALL_BYTES = 128 MiB`, and its SHA-512
   equals `dist.integrity`.
5. The archive holds exactly one member under `package/bin/`, named `grok.br`, a regular
   file. A link, device or other special member anywhere refuses the archive. Expanded
   archive size is capped at `2 * MAX_TARBALL_BYTES`.
6. The member is brotli-decoded as a stream into a sealed descriptor, at most
   `MAX_BINARY_BYTES = 512 MiB`, and is never executed. The output begins with the ELF
   magic. Its SHA-256 is `binary_sha256` and its length `binary_bytes`.

Codes: `grok_release_unavailable` (transport, a missing document, a missing dependency),
`grok_release_unverified` (any mismatch above), `grok_release_platform_unsupported`.

**Dependencies.** `cryptography` (signature) and `brotli` (step 6) form the optional extra
`grok-catalog`, imported lazily. The status query needs neither. The extra reaches every
suite environment in one change set (§0): the hosted pytest job's install line, its two
hand-kept mirrors (`CI_TEST_DEPS` and the Gate A suite container), the two tests that
assert that line verbatim, and the `test` dependency group. The signature test has no skip
path: it fails if `cryptography` is missing. The installed-wheel smoke is a separate
environment that installs the built wheel alone, with no extra, and runs the status
command from the installed entry point.

### §2.3 What this proves, and what it does not

It proves the registry served these bytes for this name and version under a pinned registry
key. It does **not** authenticate the publisher, any claim a build's help text makes, or
any measurement evidence. A compromised publisher account is outside this bound.

### §2.4 Verifier modes

`verify_grok_release.py`, run from the tree it is checked out in.

**The tree invariant `check_tree()`**, offline, in `grok_roll/catalog.py`. It reads the
gate file, the release catalog and the surface catalog from package data and needs no
network. It is run by the hermetic test of §2.5 layer 1 and by the two modes that validate a
tree, `--catalog-pr` (on a changed head) and `--release`:

1. the gate file is well formed (§2.5);
2. the release catalog loads, which includes the `MAX_RELEASES` bound;
3. if the gate is unattested, the release catalog is empty;
4. every entry's stored signature verifies under `REGISTRY_KEYS`;
5. if the gate is attested, §1 parity holds for every surface.

Tool-surface §3.3's own parity keeps its existing test and is not restated here.

Modes:

- `--derive <version>` prints the entry, and separately reports the attestation status
  (`absent`, `present_unverified` or `unknown`). A failed attestation lookup is `unknown`
  and blocks nothing.
- `--catalog-pr <base> <head-dir>` watches four files in the head: the two catalogs, the
  gate file and `plans/evidence/seat-grok/tool-surface.json`. It
  passes at once when none changed. Otherwise:
  - `check_tree` on the head's three files must pass. Because the gate file is watched, a
    pull request that only flips the gate to attested is checked against the resulting
    tree, so it fails while any shipped surface lacks a member;
  - every release entry the head adds or changes is re-derived and its six derived fields
    must be equal;
  - a gate change from attested to unattested passes only with an empty release catalog;
  - a removal passes only under §5.2;
  - a change to `pinned`, to the surface catalog's `revoked` list or to the gate file is
    reported in the output and does not fail by itself;
  - at most `CHECK_MAX_ENTRIES = 4` derivations, or `SURFACE_KEEP` on the pull request
    that attests the gate; more fails `grok_catalog_change_too_large`.
- `--release` is the pre-publish check. It keeps no baseline and trusts no earlier run:
  `check_tree` on the tree being published, then every entry re-derived online, one at a
  time, one image held. An unattested tree has no entries and passes after `check_tree`.
  Any refusal, including `grok_release_unavailable`, fails the publish.
  **Sizing.** Retention (§5.2) can legally keep more than `RELEASE_KEEP` entries, because
  pinned and surfaced entries are kept beyond it; the hard bound is `MAX_RELEASES = 24`,
  enforced by the loader. The publish step is sized for that bound, not for twelve: at
  most 24 tarballs of at most `MAX_TARBALL_BYTES` each (3 GiB worst case, about 1.4 GB at
  the §0 sizes), with a step timeout of 60 minutes. A catalog that would exceed the bound
  cannot merge or publish; the remedy is to unpin or prune.
- `--upstream-only --report` is §5.4.

### §2.5 Enforcement, stated honestly

The gate file is package data, `phase_loop_runtime/data/grok_catalog_gate.json`, schema
`grok_catalog_gate.v1`, so it is present wherever the runtime is. It ships as
`{"schema": "grok_catalog_gate.v1", "attested": false, "ruleset_scope": null,
"ruleset_id": null, "workflow_ref": null, "attested_at": null}`. Well formed means:

- exactly those six keys;
- `schema` is always the string `grok_catalog_gate.v1`;
- `attested` is a boolean;
- when `attested` is false, the four fields `ruleset_scope`, `ruleset_id`, `workflow_ref`
  and `attested_at` are all `null` (`schema` and `attested` are not part of that rule);
- when `attested` is true, `ruleset_scope` is `organization` or `enterprise`, `ruleset_id`
  a positive integer, `workflow_ref` a full branch or tag ref, `attested_at` a UTC time.

Three layers, in the order they become effective.

1. **Empty until attested (effective at the first lane).** `check_tree` is provided by
   the first lane and runs there as a hermetic test in the ordinary hosted pytest job, on
   the shipped package data and on fixture trees for each of its five steps. Before the
   gate is live there is no entry to be wrong about.
2. **The merge gate (effective on owner decision OD-3).** `grok catalog provenance` runs
   `--catalog-pr` with the verifier and its locked environment from the base commit. A
   status check from a workflow file in the pull request is not a gate, because the pull
   request can edit that file. The platform's documentation describes required workflows
   under organization or enterprise rulesets, run from a named source ref. The gate is live
   when the owner:
   - creates such a rule targeting `main`, naming this workflow at a source ref a pull
     request cannot change;
   - verifies both facts on the live rule;
   - records the scope, the ruleset id and the ref in the gate file with `attested: true`,
     by a reviewed pull request that `--catalog-pr` checks as above.

   The attestation is the owner's statement. No token in this repository's workflows can
   read an organization ruleset, so nothing here re-verifies it; the gate file being
   attested with no such rule is inside the residual authority below.
3. **The release gate.** `publish-pypi.yml` runs `--release` before any upload. An entry
   that does not re-derive does not ship to hosts, whatever merged.

**If the protected-workflow facility is unavailable** to this repository's plan or
organization, the provenance workflow ships manual-dispatch only, the gate stays
unattested, the catalog stays empty, and layers 1 and 3 are what holds. The lane that
writes the workflow establishes which case applies from current platform documentation and
reports it.

**Residual authority.** A repository writer can change the trust roots — the gate file,
`REGISTRY_KEYS`, the verifier, the workflows — through an ordinary reviewed pull request,
as with any code and as Consiliency/agent-harness#2046 records for agy. No automated path
in this phase writes them.

## §3 The measured-build query

```
phase-loop seat-window status --vendor grok
    [--binary <path> | --binary-digest <sha256> | --release-version <x.y.z>]
    [--candidate <path> | --candidate-digest <sha256> | --candidate-version <x.y.z>]
    [--require-route review|sealed|staged]...   [--schema v1]   [--exit-code]
```

With no subject selector the subject is the binary a grok seat would launch on this host,
found by the production resolver. If no `grok` is installed the subject is `null`.

**Guarantees.** No network or model call. No provider binary executed. Nothing written and
no directory created. A path is opened with `O_NOFOLLOW | O_NONBLOCK`, must be a regular
file of at most `MAX_BINARY_BYTES`, and is hashed through that one descriptor; if its
`fstat` differs before and after, the query fails rather than blocking or guessing.

### §3.1 Typed evidence

The query never uses a reader that folds failure into absence. `grok_roll/evidence.py`
reads each source itself and returns one of three results:

| Result | Meaning |
|---|---|
| `ok` | read and valid |
| `absent` | positively absent: the file does not exist (`ENOENT`) inside a directory that passed its checks, or the record directory itself does not exist |
| `invalid` | anything else: a denied read, a wrong owner or mode, a link, a non-regular file, an over-size or unparseable file, a wrong schema, an unknown key, a record for another host, a receipt that fails a field check |

Sources and their checks:

- **the surface catalog and the release catalog**: `ok` or `invalid`, by their loaders. A
  corrupt surface catalog hides its `revoked` list;
- **a host-local record** for a digest: the directory and file checks of tool-surface §3.2;
- **the attempt register** for a digest (`grok-surface-<digest>.attempts.json`): the same
  directory and file checks, and the structure `grok_tool_surface._read_register` requires;
- **a `tool_probe.v1` receipt** for a digest and argv digest: the descriptor checks of
  `panel_invoker._read_grok_receipt`, with one stricter rule stated here: a file over
  16384 bytes is `invalid`.

`grok_tool_surface.py` and `panel_invoker.py` are not edited. Three separate conformance
tests keep the typed readers honest, each with its own oracle:

1. **Frozen resolution**, oracle `grok_tool_surface.frozen_surface(digest, argv_digest)`:
   §3.2's frozen result is `usable`, `refused` or `stale` exactly when the oracle returns a
   record, with the same source and surface digest; it is `withdrawn`, `none` or `invalid`
   exactly when the oracle returns nothing.
2. **Receipt reading**, oracle `_read_grok_receipt`: the typed reader returns `ok` with
   equal decoded content exactly when the oracle returns content; where the oracle returns
   `None` or raises, the typed reader returns `absent` for a missing file and `invalid`
   otherwise. This conformance says nothing about fields.
3. **Admission**, oracle `grok_tool_gate` at its provisional step: whenever the gate
   admits a form, §3.2 reports that route `usable` with the same basis; and whenever §3.2
   reports `usable` with basis `list_tools`, the gate admits. Two intended differences,
   both where the query is stricter or reads less than the gate, are excluded from the
   implication and tested as named exceptions:
   - §3.2 reports a frozen route `usable` from the record alone, where the gate also needs
     the receipt that `probe-tools` writes at no cost.
   - Where the gate admits a form from a valid listing receipt while a host-local record,
     the attempt register or a catalog beside it is corrupt, §3.2 reports `invalid`. The
     gate does not consult that evidence for a listing receipt; the query refuses to
     advance on any invalid input.

`inputs` in the output reports `surface_catalog` and `release_catalog` (`ok` or `invalid`)
and `host_records` (`ok`, `absent` when there is no record directory, `invalid` when the
directory fails its checks).

### §3.2 Route state and build state

**Required routes.** `REQUIRED_ROUTES = ("review",)` unless `--require-route` names more;
the set used is echoed in `required_routes`. A consumer that depends on another form asks
for it.

Each route form, at its argv digest for the frozen measurement model and effort, has one
`evidence` value, computed in three steps.

**Step 1 — frozen result**, following tool-surface §3.2 precedence exactly:

1. If the surface catalog has the route for the digest, it decides alone and host-local
   sources are not consulted: `usable` (running context digest, admitted), `refused`
   (running context digest, not admitted) or `stale` (another context digest).
2. Otherwise the host-local record is read. `invalid` record: `invalid`. `absent` record,
   or a record without the route: `none`.
3. Otherwise the attempt register is read. `invalid` register: `invalid`. The route is
   **published** only when the register's `published` entry for the argv digest names the
   same grant and reservation as its latest `attempts` entry and the route's own surface
   digest. A register that is `absent`, or valid but not publishing the route (a newer
   attempt superseded it, or it was never published): `withdrawn`.
4. A published route gives `usable`, `refused` or `stale` as in step 1.

**Step 2 — receipt class**, from the typed receipt read:

| Class | Condition |
|---|---|
| `invalid` | the read is `invalid`; or the content is not a `tool_probe.v1` object for this digest and argv digest; or `passed` is true and any of these holds: the tools are not admitted for the form, the version digest is malformed, the `basis` is unknown, a listing receipt carries a frozen field, a frozen receipt's four frozen fields are malformed |
| `none` | the read is `absent`; or the receipt is well formed with `passed` false |
| `listing` | `passed` true, `basis` missing (a legacy receipt) or `list_tools`, no frozen field |
| `frozen_cache` | `passed` true, `basis: frozen_measurement`, four well-formed frozen fields. Its content is a cache of step 1 and is never itself evidence |

**Step 3 — the route's `evidence`**, first match:

| `evidence` | Condition | `basis`, `source` |
|---|---|---|
| `invalid` | the frozen result or the receipt class is `invalid` | `none`, `null` |
| `usable` | the receipt class is `listing` (it is what the launch gate reads, so it decides even beside frozen evidence of any kind) | `list_tools`, `receipt` |
| `usable` | the frozen result is `usable` | `frozen_measurement`, `catalog` or `host_local` |
| `refused` | the frozen result is `refused` | `none`, `null` |
| `withdrawn` | the frozen result is `withdrawn` | `none`, `null` |
| `stale` | the frozen result is `stale`; or it is `none` and the receipt class is `frozen_cache` (a receipt whose backing route is gone) | `none`, `null` |
| `absent` | the frozen result is `none` and the receipt class is `none` | `none`, `null` |

So an ordinary context change yields `stale`, never `invalid`; a withdrawn host-local route
is never `usable`; and a malformed receipt is `invalid`, never `stale`. A help text that
merely advertises a listing is not evidence of any kind.

Each of `subject` and `candidate` has one `state`, the first that applies:

| `state` | Condition |
|---|---|
| `unresolved` | no digest: a version selector that is not a release member |
| `invalid` | a catalog input is `invalid`, `host_records` is `invalid`, or any required route's `evidence` is `invalid` (a corrupt record, register or receipt) |
| `revoked` | the digest is in the surface catalog's `revoked` list; this precedes all evidence, a listing receipt included |
| `measured` | every required route is `usable` |
| `partial` | at least one required route is `usable`, `refused` or `withdrawn`, and not all are `usable` |
| `stale_context` | no required route is `usable`, `refused` or `withdrawn`, and at least one is `stale` |
| `unmeasured` | every required route is `absent` |

So `unmeasured` is reported only when absence was positively established for every
required route; a build with evidence for some routes, or whose host-local route was
withdrawn, is `partial`, never `unmeasured` and never `measured`. `measured` is the boolean `state == "measured"`.

**Limits, stated.** The query does not compare a build's literal `--help` and `--version`
bytes, which needs execution; the launch gate does, and stays the authority at launch.
Revocation here is stricter than at launch: today's gate applies the `revoked` list to
frozen-basis receipts only, and a listing receipt has no context check. So a revoked build
with a listing receipt is `revoked` here and stays launchable until its receipt is removed;
withdrawing such a build means removing its receipts on affected hosts. Closing that at
the gate is a tool-surface change, recorded as a follow-up.

### §3.3 Output: `grok_seat_status.v1`

One JSON object on stdout. Every key is always present; nullable keys are `null`, never
omitted.

| Key | Type | Values |
|---|---|---|
| `schema` | string | `grok_seat_status.v1` |
| `vendor` | string | `grok` |
| `context_digest` | string | 64 hex |
| `inputs` | object | §3.1: three string keys |
| `required_routes` | array of string | from `review`, `sealed`, `staged` |
| `subject` | build object, nullable | `null` only with no selector and no grok installed |
| `candidate` | build object, nullable | `null` with no candidate selector |
| `decision` | object, nullable | `{"action", "reason"}`, §5.1; `null` when `candidate` is `null` |
| `advance_to` | target object, nullable | newest release member whose state is `measured` |
| `rollback_to` | target object, nullable | newest `measured` member with a version below the subject's; `null` when the subject's version is unknown |

Build object: `binary_sha256` (string, nullable), `version` (string, nullable), `release`
(`member` or `unknown`), `state` (§3.2), `measured` (boolean), `routes` (array, always the
three measured route forms: `route`, `argv_digest`, `evidence` (the seven values of §3.2
step 3), `basis` in
`frozen_measurement | list_tools | none`, `source` in `catalog | host_local | receipt` or
`null`, `surface_digest` nullable), `context_digest` (the record's, nullable),
`measured_at` (UTC string, nullable).

Target object: `version`, `binary_sha256`, `tarball_integrity`, all strings. Each member
considered as a target gets the full §3.2 evaluation, register included. A member whose
state is anything but `measured` is never a target, so a withdrawn, invalid, partial, stale
or revoked member cannot be one. Both targets are `null` when a catalog input or
`host_records` is `invalid`.

**Exit status.** 0 whenever an answer was printed. 2 for a usage error. 3, with
`{"schema": "grok_seat_status.v1", "error": "status_unavailable", "detail": "<code>"}` and
nothing else, when the query itself failed: `subject_unreadable`, `subject_not_regular`,
`subject_changed`, `subject_too_large`, `subject_not_native`, and the same for
`candidate_`. With `--exit-code`, 1 replaces 0 when the subject is not measured or the
decision is `hold`.

**Stability.** Consumers ignore unknown keys. Within `v1`, keys and enumerated values are
only added. Removing a key or changing a meaning needs `v2`; `--schema v1` then keeps
emitting `v1` for at least one minor release. `--schema` accepts only `v1` today. A golden
test pins every key, type, nullability and enumerated value. The CLI is the supported
surface; the Python functions behind it are not.

## §4 Not in this phase

Staging, executing or measuring a build; the job; approvals; the standing grant. See §7.
A release becomes measured exactly as today: tool-surface §5.10 under an owner grant.
What this phase adds for that path is the catalog entry that names the measured digest's
release, and the query that reports the result.

## §5 Hold, retention, rollback and lag

### §5.1 Hold: the decision table

No launch path changes. The harness says `advance` in exactly one case: sound inputs and a
measured candidate. First matching row wins:

| # | Condition | `action` | `reason` |
|---|---|---|---|
| 1 | a catalog input or `host_records` is `invalid` | `hold` | `inputs_invalid` |
| 2 | candidate `unresolved` | `hold` | `candidate_unresolved` |
| 3 | candidate `invalid` | `hold` | `candidate_evidence_invalid` |
| 4 | candidate `revoked` | `hold` | `candidate_revoked` |
| 5 | subject `invalid` | `hold` | `subject_evidence_invalid` |
| 6 | subject not `null` and its digest equals the candidate's | `hold` | `same_build` |
| 7 | candidate `measured` | `advance` | `candidate_measured` |
| 8 | candidate `partial` | `hold` | `candidate_partial` |
| 9 | subject `revoked` | `hold` | `subject_revoked` |
| 10 | subject in {`measured`, `partial`} | `hold` | `candidate_unmeasured` |
| 11 | subject `null` | `hold` | `first_install_unmeasured` |
| 12 | subject in {`unmeasured`, `stale_context`, `unresolved`} and candidate in {`unmeasured`, `stale_context`} | `hold` | `no_measured_build` |

Rows 1 to 12 are exhaustive for every non-null candidate (with no candidate, `decision`
is `null`); a test enumerates every pair and asserts that row 7 is the only `advance`. A
`partial` build, which is where a withdrawn route lands, reaches only rows 8 and 10,
neither of which a consumer may override. Rows 11 and 12 are still `hold`: absence of evidence never
becomes `advance`. They carry their own reasons because no measured build is displaced in
those two cases, which a consumer may act on by its own policy (§6); the harness does not
decide that for it.

### §5.2 Retention

- **Measured records are never deleted** by anything in this phase.
- **Surface catalog aging.** A surface stays while it is among the newest
  `SURFACE_KEEP = 8` by release version, or its release is `pinned`. Pruning happens only
  in a pull request that also adds a newer measured surface.
- **Release catalog aging.** An entry stays while it has a surface, is `pinned`, or is
  among the newest `RELEASE_KEEP = 12`. Pinned and surfaced entries can take the total
  past twelve; it can never pass `MAX_RELEASES = 24` (§1), so a pull request that would
  pin or keep a twenty-fifth entry fails the loader until something is unpinned or pruned. An entry, with its surface, may also be removed
  when the registry no longer serves its version document, so one withdrawn upstream
  version cannot block every release (§2.4).
- **The `revoked` list** is not aged. Removing a digest from it is its own reviewed change,
  reported by the check.
- **Binaries.** The harness keeps none. Old builds live in the downstream bootstrap's
  release directories (§6).

### §5.3 Rollback

- **A host** rolls back by re-selecting the build `rollback_to` names, or `advance_to` when
  `rollback_to` is `null`. Its record still exists, so the seat works with no new
  measurement.
- **A bad measured build** is withdrawn with the surface catalog's `revoked` list. The query
  reports it `revoked` on every host with that catalog. §3.2 states the listing-receipt
  limit and its operational consequence.
- **A context change** makes every frozen record stale at once; listing receipts are not
  context-bound. No rollback helps a frozen-basis build; it is measured again under the
  owner's grant.

### §5.4 Lag report

A nightly hosted run on `main` (`--upstream-only --report`) reports two things separately:
the newest stable version with its registry publication time, read live from the main
package's full document, and the newest catalog member with a surface. Lag is measured from
that publication time. It is report-only. Past `LAG_NOTICE = 72 h` it creates or updates
exactly one open issue labelled `grok-measure`, naming the version, and closes it on the
next pass that finds the catalog current. While the gate is unattested the catalog is
empty by rule, so the report says so and opens no issue.

## §6 Downstream bootstrap contract

1. Ask only through §3's command. Import no harness module; read no file under the private
   record root.
2. Stage the update target and pass it as `--candidate`. On `decision.action == "advance"`
   move the selected build.
3. On `hold`, do not move — with one choice left to the bootstrap: for the reasons
   `first_install_unmeasured` and `no_measured_build` no measured build is displaced, so a
   bootstrap may proceed by its own stated policy. For every other reason it holds.
4. Name the routes relied on with `--require-route`; `review` is the default.
5. Treat a non-zero exit, a timeout, unparseable output or an unknown `schema` as `hold`
   with no choice, report it, and do not fail the rest of the tooling build for it.
6. Read only the keys of §3.3. Ignore others. Treat `null` as "no value", never as false.
7. Keep the selected build and the build `rollback_to` names. Others may be pruned.
8. Optionally install `advance_to.version` instead of the vendor's newest, comparing the
   tarball integrity.
9. A build admitted by listing becomes measured on a host only after `probe-tools` has
   passed there.

## §7 Deferred follow-up: GROKROLL-B (non-normative)

Planned later, after the owner rules on OD-B1 and after the first real grok measurement
under tool-surface D4 gives real cost and timing. Nothing in this section binds a lane.

**What it would add.** A job on the measurement host that notices a new stable release,
derives and stages it, and brings the owner one decision; and the approval of the counted
launches.

**Its interfaces with this phase**, which this phase freezes for it:

- `grok_roll.provenance.derive_release` and `stable_version` (§2.2);
- the release catalog entry shape and `--catalog-pr` (§1, §2.4), the path a measured
  build's entry takes to `main`;
- `grok_roll.status.query` for "is this digest already measured?" (§3);
- the nightly `grok-measure` issue (§5.4), which it would extend.

**Owner decisions it needs.**

- **OD-B1 — how the counted launches are approved.**
  - *A, detect and queue.* The job only prepares; the owner grants each image and an
    operator runs the procedure by hand, attended, as today. Trade-off: nothing runs
    unwatched, but every release measured costs a person's time.
  - *C, one approval per image (recommended).* The owner runs one command per image and
    the job then runs the procedure, at most five counted requests. Trade-off: the owner
    still decides each image, but the launches run with nobody watching.
  - *B, a standing budget.* The owner sets a weekly cap once and the job measures new
    releases inside it. Trade-off: no per-release effort at all, in exchange for spending
    requests on images nobody looked at, bounded by the cap and stop conditions.
- **OD-B2 — the standing budget's numbers**, only for B: requests per week, images per
  week, a total, an expiry. Recommendation: do not rule until C has run for a few
  releases and shows what a measurement really costs.

**Review findings it must resolve** (round-2 review, `REQUIRED` numbers):

- 1 — schedule the staged-image stage-chain test under the required zero-skip hosted job,
  and prove the staged fixture is what answered the route probes.
- 2 — make pre-approval staging credential-free (the help and version runner projects a
  login today), drop or define the rehearsal-before-approval branch, and define who
  attests the hosted egress-check run.
- 5 — make recovery agree with the ledger: an interrupted rehearsal spends its slot, a
  committed result is not a measured one, and `resume` needs a defined transition.
- 6 — contain the whole process tree, require the shared-host admission mechanism, and
  make selection and the idle-tick bound durable across crashes.
- 7, option-A half — a rendered-procedure control through the real CLI with no approval
  actions.

## §8 Integrity: what moves and what must not

`seat_window.runtime_digest()` hashes the runtime's top-level `*.py`, `advisor_board/*.py`
and `seat_egress/*`.

- New code lives in `phase_loop_runtime/grok_roll/`, outside that hash. The status lane's
  edit to `seat_window.py` is the only edit this phase makes to a hashed file. Window
  records on the old key need requalification, as after any runtime edit.
- Must not move, each with a named guard: `grok_tool_surface.context_digest()`; the egress
  allow-list digests; the route forms and their argv digests; the `tool_probe.v1` receipt.
- Not edited by any lane: `grok_tool_surface.py`, `panel_invoker.py`, `agy_provenance.py`,
  `cli.py`, `seat_egress/**`. A lane that needs to stops and reports.
- This phase adds no process launch.

## §9 Codes

`grok_release_unavailable`, `grok_release_unverified`, `grok_release_platform_unsupported`,
`grok_catalog_change_too_large`, `grok_catalog_too_many_releases`,
`grok_catalog_dependency_missing`, `status_unavailable`
with the details of §3.3. None enters the seat's public detail-code vocabulary.

## §10 Not in any lane

Owner acts, after merge: OD-3's ruleset and its attestation; the first catalog entry; the
`grok-measure` label. The phase ships inert: an empty catalog and an unattested gate.

## §11 Alternatives evaluated

| Alternative | Verdict |
|---|---|
| Advance when nothing is measured on either side | Rejected. The harness never turns absent evidence into `advance`; it reports the case by reason and leaves the choice to the consumer. |
| Reuse `load_host_record` for the query | Rejected. It cannot tell a corrupt record from a missing one. |
| Treat an advertised listing flag as measured | Rejected. A help text is not a validated receipt. |
| A delta release check against the previous release | Rejected. It needs a trusted baseline; re-deriving every entry needs none. |
| Store publication time or attestation status in the catalog | Rejected. Both can change after the fact, which breaks re-derivation. |
| A harness-side cache of measured binaries | Deferred. It needs a launch-path change. |
| A runtime catalog fetch | Deferred. It needs a signed side channel. |
