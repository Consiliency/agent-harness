---
type: detailed
status: committed
review_status: pending_round_2
owner_skill: codex-plan-detailed
input_base_commit: cd33474856551a6645ac4db33253922a1db2e442
issues: [agent-harness#906]
related_issues: [agent-harness#915, treesitter-chunker#97]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests .venv/bin/python -m pytest -q phase-loop-runtime/tests/test_train_review_packet.py phase-loop-runtime/tests/test_train_review_authorization.py phase-loop-runtime/tests/test_train_merge.py phase-loop-runtime/tests/test_train_prebuilt.py phase-loop-runtime/tests/test_train_runner.py phase-loop-runtime/tests/test_train_e2e.py phase-loop-runtime/tests/test_train_invariants.py phase-loop-runtime/tests/test_native_claude_seat_fill.py phase-loop-runtime/tests/test_native_claude_seat_fill_green.py phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py phase-loop-runtime/tests/test_review_staged_tree_authorization.py phase-loop-runtime/tests/test_the_real_launch_carries_the_prefix.py phase-loop-runtime/tests/test_broker_staged_tree_delivery.py phase-loop-runtime/tests/test_sandbox_preamble.py phase-loop-runtime/tests/test_skills_canon_parity.py"
  verification_status: not_run
  human_required: false
---

# Detailed plan: give governed train reviewers the admitted changes

Revision 2 reconciles round 1: Gemini AGREE; Codex, Claude and Grok PARTIALLY
AGREE. All four accepted explicit compact disposal scope, three conditionally.
Reconciliation: `.dev-skills/handoffs/codex-plan-detailed/20260922T034200Z-train-review-packet-r1-reconciliation.md`.
`committed` is the plan-registry state; no Git commit or plan ratification is
claimed. The amended contract requires a fresh four-vendor round, capped at
three rounds total.

## Task and boundary

Repair the coordinator-owned review material blocking treesitter-chunker#97:
build a substantive, immutable review packet, preview it without model calls,
and bind approval reuse to those exact bytes. This standalone repair does not
claim completion of a v10 goal. The coordinator's publication, merge, authority,
isolation, reviewer floor and forward-only recovery rules remain authoritative.

Plan only: Default mode was active; implementation starts after cross-vendor
plan review and reconciliation. No supplier review, merge, release, install,
checkpoint change, ledger edit or additional consumer round is authorized here.

## Research summary

At the input base, `train_runner._build_train_review_bundle` supplies only the
train title, advisory tier, node label, PR link and shortened live-preferring
head. `governed_review.governed_board_gate` stages this text into a fresh provider
directory; no-tools routes require source inline regardless of whether a
separate authorized sandbox is staged for tool-capable seats. Native-fill
checks bind the text, but `already_approved` only checks status/reviewer count.
The repair therefore needs a shared packet identity before both paths.

Live read-only observation on 2026-09-22: treesitter-chunker#97 remains at
`f82bb81198316356c142b96baae4fb4b91746ffa`, base
`fb70922076c773d1865176329a03f67ff893fd90`. Its node is `CHANGELOG.md`, but its
scope is **4,778 changed paths**, including 4,696 deleted generated environment
entries. The remaining 82 paths include application source, tests, workflows,
lockfile and docs; their complete ordinary unified diff is 347,098 bytes.
Reading all 82 head files would add 1,563,400 bytes. A node label or an S27-only
cleanup diff cannot substitute for this full admitted candidate.

Input reports: [agent-harness#906 handoff](https://github.com/Consiliency/agent-harness/issues/906#issuecomment-5759905350)
and [agent-harness#915 approval residual](https://github.com/Consiliency/agent-harness/issues/915#issuecomment-5749922654).
No synthetic transport verdict is source approval.

## Three implementation decisions

### D1. Automatic Git material, explicit supporting evidence

Add `train_review_packet.py` as the single builder/validator. The coordinator
always derives change content from Git objects; it never accepts a caller's
patch as authoritative. Add `--review-material FILE` for a version-1 JSON
manifest of supporting material, keyed by the exact train node IDs. Require it
for a new governed review; absent/incomplete material returns `review_halted`
with a named reason before models. Autonomous draft publication is unchanged.

The manifest supplies, for each node, `head_sha`, a nonempty `acceptance` list,
`verification` records, optional `context` Git paths, and optional
`generated_removals` declarations. Unknown/duplicate nodes, fields or records,
invalid OIDs, missing acceptance or verification, and stale head bindings fail
closed. Evidence paths must be nonempty relative paths without `..`; resolve
against the manifest directory with no-follow handling of **every** component,
not only the leaf. Read only regular files, require their declared SHA-256,
and snapshot once. Each acceptance item has an ID, text and provenance. Each
verification record includes command/check name, observed result, exact head,
and evidence content/provenance. Local claims are explicitly **operator-supplied
attestations**, not independently authenticated executions; hosted CI records
are fetched read-only by check/run identity and checked against the admitted
head. URLs alone, status rollups lacking head identity, or an unbound
`verification.json` do not establish head-bound evidence. Preserve failure,
skip, unavailable and unknown results; none may be relabelled passed. An
explicit head-bound failure may be reviewed; missing/unbound evidence may not.

Freeze the material input shape as follows (all paths are strings; digests are
lowercase 64-character hex; Git OIDs use the repository's object format):

```text
{schema_version: 1, nodes: {<node_id>: {
  head_sha: GitOID,
  acceptance: [{id: string, text: nonempty-string,
                provenance: {path: string, sha256: SHA256}}],
  verification: [
    {id: string, kind: "github_check_run", check_run_id: positive-int,
     expected_name?: string, expected_app_slug?: string}, OR
    {id: string, kind: "attested_command", head_sha: GitOID,
     argv: nonempty-string-array, exit_code: int|null,
     result: "passed"|"failed"|"skipped"|"unknown", attested_by: string,
     observed_at: RFC3339, evidence: {path: string, sha256: SHA256}}
  ],
  context: [repo-relative-Git-path],
  generated_removals: [{path: repo-relative-directory, base_tree_oid: GitOID,
    rationale: nonempty-string, attestation: {path: string, sha256: SHA256}}]
}}}
```

`context`/`generated_removals` default empty; other fields are required.
Acceptance/evidence file bytes are included as text; there are no URL-only
provenance records. Attested command `passed` requires exit_code=0 and `failed`
a nonzero integer; skipped/unknown use null. Attribution is reported, not
cryptographically authenticated by this repair. A disposal attestation is a
JSON document with `attested_by`, `observed_at`, exact `base_tip_sha`, `merge_base_sha`, `head_sha`,
`path`, `base_tree_oid`, and nonempty `disposal_scope` text naming what may be
discarded; all identities must match. Its claim of generatedness is a human
semantic assertion explicitly shown to reviewers, not a fact inferred by code.

The builder reads the admitted full head from the ledger, resolves PR identity
and live base/head through the existing GitHub read-only boundary, and verifies
available local Git objects. Record full base tip, unique merge base, admitted
head, base/head tree IDs, PR identity, train node order/edges and train content
digest. The review patch is `merge-base(base-tip, admitted-head)..admitted-head`,
matching PR scope, not a two-dot diff that accidentally includes unrelated main
changes. Ambiguous/missing merge base or objects holds; do not fetch, checkout,
execute repo hooks, run textconv/external diff, or use live working files.
For every pending node, live head must equal admitted head in **both** review-only
and governed merge paths; a retargeted base is refused. Main-tip movement changes
packet identity and requires re-review. Node labels never restrict paths.

Resolve each node with the existing `resolve_workspace(node)` (including CLI
overrides/TrainNode.workspace), not the coordinator's canonical authority root.
Use that node's Git common object directory read-only through a fresh bare
reader in operation-owned scratch: its own empty config/index/refs/attributes,
no work tree, controlled `GIT_OBJECT_DIRECTORY` pointing to the node's objects,
and no source config or `info/attributes`. Clear inherited `GIT_*`; set
`GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_ATTR_NOSYSTEM=1`,
`GIT_NO_LAZY_FETCH=1`, and disable replacements. No source writes, lazy fetch,
hooks, index refresh or worktree attributes. Derive inventory using
`diff-tree -r --raw -z --no-renames --no-abbrev`; resolve blobs/tree modes with
plumbing. Render with explicit `--no-color --no-ext-diff --no-textconv
--full-index --no-renames --src-prefix=a/ --dst-prefix=b/
--ignore-submodules=none --diff-algorithm=myers --unified=3` and fixed
`diff.relative=false`, `diff.orderFile=/dev/null`, `diff.noprefix=false`,
`diff.mnemonicPrefix=false`, `core.quotepath=true`, `core.attributesFile=/dev/null`.
Cross-check patch headers against every noncertified inventory entry, including
mode-only entries. Record Git version/argv; tree IDs and inventory digest are
identity authority, while a version-dependent raw-diff digest is provenance.
Missing objects name their OIDs and remediation, never trigger an implicit fetch.

Base-name authority is the coordinator's existing `_DEFAULT_BASE` (`main`),
not a base name supplied by the new manifest; the current ledger has no base
field. Resolve by PR URL with read-only `gh pr view --json
url,state,headRefOid,baseRefName,baseRefOid,mergeCommit`; a different base name
is retargeting, and a changed `baseRefOid` is base drift. Read a selected check
with `gh api repos/<canonical-owner/repo>/check-runs/<id>`; verify its `head_sha`,
repository identity, name, status and conclusion, and include returned output
title/summary/text as untrusted evidence. Unavailable/malformed check data holds.
No PR body statement or status rollup substitutes for those head-bound fields.
Record check `app.id`/`app.slug` and check-suite ID (workflow-run ID when present),
labelled "reported by GitHub App X", not independently executed by this runtime.
Match supplied expected name/app fields; their absence is reported as unpinned.
Map completed conclusions: success→passed; failure/timed_out/cancelled/
action_required→failed; skipped/neutral→skipped; stale/null/other→unknown;
queued/in_progress→unknown regardless of conclusion. Bind observed values,
including raw status/conclusion, into the packet.

The deterministic UTF-8/LF `packet.md` contains all identities, acceptance,
head-bound evidence content, every **noncertified** changed-path/mode/object
inventory row plus one summary row per certificate,
and the complete substantive patch, including additions, deletions, modes and
renames represented canonically as delete/add. Add selected
unchanged/head source context by explicit Git path from the material manifest;
missing context produces a review dissent, never a fabricated complete-source
claim. All supplied content is untrusted data inside the existing broker
framing. No shell snippets, links or embedded instructions are executed.

All embedded text uses one reversible, legend-labelled presentation: escape
literal backslash as `\\`, CR as `\r`, and other transport-disallowed Unicode
categories Cc/Cf/Cs/Zl/Zp as fixed-width `\uHHHH` or `\UHHHHHHHH`; LF and TAB
remain separators. Encode metadata/path strings with the same rule. Record raw
bytes/digests before escaping and escaped-section digests after it; never
normalize source line endings. Invalid UTF-8/binary source holds outside a
certificate. Test backslash-vs-escape ambiguity, CRLF, CRLF→LF and lone CR.
The normal broker replica validator still applies; forbidden frame-looking
content holds with its source named, rather than weakening the broker grammar.
Before ready/store/use, assert `content_sha256(read_back(packet)) == packet_sha256`.

**Explicit proposed compact-removal policy; board must assess this decision.**
A caller may declare an entire deleted generated subtree using its exact base
tree OID, path, rationale and an operator-attestation evidence record bound to
that base/head. `base_tree_oid` means the subtree at the unique **merge base**;
derive both inventory and deletion diff from it. Its OID must also equal the
subtree at the live base tip: a base-side edit/addition under the group holds.
Unrelated base-side changes are allowed; whole-commit merge-base=base-tip is
unnecessarily restrictive when the exact subtree is identical. The builder
proves the subtree is absent at head and every covered path is deleted, with
no overlaps or surviving descendants. Additionally refuse when a newly added
path outside the group has the same blob OID as a deleted group blob; an
identical blob already present outside at merge base is allowed. This is an
**exact-blob new-copy-out check**, not proof that no semantic rename/copy
occurred. Modified copies and every other outside change remain fully visible
in the substantive patch. Refuse root groups, any group containing or nested
within top-level `.github`, or any subtree containing a `CODEOWNERS` file;
those deletions must stay substantive. It records
the complete deleted-path/mode/blob-ID inventory in `removals.json`, hashes the
complete unabridged canonical diff, and places the group path, tree OID,
counts/mode totals, inventory digest, full-diff digest, rationale and attestation
text in the inline packet. Deleted blob bodies and the individual inventory
rows are represented by this explicit mechanical certificate, **not claimed
to have been read by the model**. Git symlink objects are recorded as data,
never dereferenced. This is generic and opt-in: `.pubenv`, `.toxenv`, generated
file names or executable bits alone grant no exemption. Runtime objectively
certifies whole-tree deletion and exact attestation binding; it cannot certify
that every deleted blob is generated rather than project source. A source-
looking tree with a matching attestation is therefore shown as an explicit
disposal assertion for the board, not silently classified safe. If the
attestation is absent/mismatched, halt; if its semantic scope is disputed, retain full data
or halt for a separately reviewed scope decision; never silently compress it.

Each group also has an explicitly labelled bounded semantic summary: total
deleted bytes, mode totals, extension histogram and first-level children with
counts/bytes. Render the first 20 sorted extension/child rows and explicit
remainder counts/bytes; no ellipsis pretending to be complete. Full inventory
remains in `removals.json`, bound by its inline digest. That sidecar is retained
for operators only, never copied/mounted/referenced into a seat's scratch.

Other binary/submodule changes, malformed text or remaining forbidden framing
content halt before models, naming the affected path.
No placeholder pretending a binary hash is a source review. The packet reader
may accept up to 1 MiB, but a ready-to-review packet must pass the actual broker
renderer with the selected brief: `_BROKER_SEALED_PROMPT_MAX_BYTES` is
**512 * 1024 bytes for the complete rendered prompt**, including authoritative
instructions, frames and headers. Preview records both packet and rendered
prompt byte counts and rejects above that bound; test exact-bound and one-byte
overflow including framing overhead. Never equate the 1 MiB parser bound to
transport readiness or model token capacity. An over-limit candidate requires
scope decomposition under a separately reviewed plan, never truncation or
automatic multi-round spending. A complete packet that a provider refuses is
still a failed review, never proof of readiness.

### D2. One snapshot for preview, native fill and all governed reviews

Add `run-train --governed --review-only --preview-review DIR
--review-material FILE --json`. This writes only packet/receipt files to an
explicit fresh output directory outside node checkouts and coordinator state.
It reads the existing admission ledger and live PR metadata but branches
**before broker construction, lease acquisition, run_train, preflight recovery
or directory creation under the ledger**. Missing/open-stale/unadmitted nodes
hold. It must not repair a torn ledger, recover a merged row or admit a head.
Reject preview combined with native emission/fill or without review-only.
Require a nonexistent or empty directory with no symlink path components;
write operation-owned temporary names then rename finished artifacts, marking
`receipt.ready=true` only after all checks. On failure ready=false. The bare
Git readers live only in this operation scratch and are removed, not exposed.

Preview and production use the same builder, serializer and input validation.
Outputs: `packet.md`, `packet.json` (schema/identities/content digests),
`removals.json` when applicable, and `receipt.json` (runtime/source identity,
counts/bytes, per-section byte counts/digests, material-manifest digest,
exclusions represented by certificate,
read-only checks, errors and packet digest). Timestamps/output paths belong to
the receipt only, never the reviewed text. A successful preview is transport
material preparation, not review approval. A failure still emits a diagnostic
receipt but no review-ready packet. No new train-ledger status is introduced.

For actual P4 review, build and validate exactly once after the admitted set is
known, store immutable read-back packet bytes under
`<ledger-dir>/review-packets/<packet-sha256>/`, then use those same bytes for
native-fill emission, stale-fill comparison, `_default_train_review`, approval
stamping and review-only output. Include supporting file/attestation digests in
the packet so changed evidence, context or criteria changes its identity.
Never read a mutable external file again between authorization and review.
Immediately before approval recording, recheck pending PR base/head identities;
drift holds without approval. Existing exact-head merge pin remains a second
independent guard; no widening of the broker capability follows from the packet.

`governed_board_gate` keeps its existing isolated scratch and read-back digest
binding. It receives the full packet as `artifact`, not only paths to it.
Exercise the production broker inline renderer for all selected seats,
including Gemini's no-tools route; the packet must be available identically to
that seat without a checkout, network or file-read fallback. Do not introduce
new provider launch sites, `threading.Thread`, a broker bypass or new mounts.

Renderer feasibility: `_render_broker_inline_prompt` currently calls
`_require_staged_tree` for sandbox routes; preview must not fake that provenance.
Extract only its existing string assembly/byte-bound check into the proposed
private `_assemble_broker_inline_prompt` helper in `panel_invoker.py`, taking
the already-computed preamble, artifact/instructions and delimiter pairs. The
existing wrapper keeps generated-input validation, `_digest_bound_broker_delimiters`
and `_require_staged_tree` in their existing order, then calls this helper.
The helper retains `ValueError("brokered review input exceeds sealed transport bound")`;
existing production errors and output bytes remain identical. Preview performs
the same existing input/frame validations then
uses this same core with `_resolve_brief`, the real sealed preamble and the
real sandbox-preamble text for a conservative 4096-byte absolute-path bound
(Linux pathname bound, reported as a bound, not a validated or created tree).
Measure both reachable route variants and report their maximum; unsupported
variants hold rather than using a hand-counted estimate. No composition probes,
authorization or filesystem sandbox is needed for this conservative preview.
After actual composition/author filtering in `governed_board_gate`, resolve the
effective brief and repeat the pure preflight for each seat's reachable route
before `prepare_review_isolation_authorization`, native emission or any invoke.
Any invalid/over-limit input produces the existing block-result shape with zero
provider launches. Keep the production wrapper's actual-tree validation and
actual-prompt check at the existing launch boundary as well. Tests must show
the pure core and real validated wrapper produce identical bytes for actual
staged trees, that no fake stage becomes authority, and that an overflow on
the last composed seat prevents **all** launches. Only this packet-specific
preflight extends the gate; do not refactor its authorization sequence.
If the needed Gemini transport is not available on the integration base, wait
for the qualified agent-harness#944 capability; do not copy its implementation
or spend the consumer round on an unsupported route.

### D3. Content-bound approval with fail-toward-re-review compatibility

Add optional `review_packet_sha256` to `LedgerRecord`, preserving it in
`to_dict`, `append_record`'s timestamp replacement and `_dict_to_record`.
Omit when absent so historical/non-review records stay byte-compatible.
Persist it only with actual panel approval and existing usable-reviewer
evidence. Honor a cached approval only if its valid digest equals the current
read-back packet digest **and** the current usable-reviewer floor is met.
Legacy approvals without a digest, malformed/missing packet data and changed
head/base/evidence/criteria/context/train scope never authorize pending merges.
Missing data holds; a well-formed changed packet goes through fresh review.
Native-fill artifact/brief/composition checks still run before any cache hit;
their existing schema stays unchanged.

A cache candidate loads stored `packet.md`/`packet.json` by approved digest,
rehashes the text and checks parsed identity fields against that text's bound
metadata and the live pending-node/ledger identities. Material is required to
build/rebuild a packet. When explicitly supplied on resume, its current snapshot
must be compared and any changed byte invalidates the cache; when omitted,
stored acceptance/context/evidence snapshots remain the explicit review inputs,
not claims of newly refreshed checks. Missing/corrupt stored bytes hold. The
material-manifest digest is bound in the reviewed text as well as `packet.json`;
no mutable sidecar field can alone change what approval means.

For partial-merge resume, retain the original packet identities/material for
already-merged nodes only after validating the ledger's admitted head and live
merge outcome; base advancement caused by that merge must not rewrite that
historical material. Rebuild pending-node sections against current identities.
If a legacy partial train lacks a valid historical packet, return
`review_halted`/`historical_packet_unavailable` before models or pending merges.
The ledger has no historical comparison base, and this schema provides no
authority to reconstruct one: never use current main (which may now contain the
head) to produce an empty historical patch. Recovery/import of historical scope
is a separate bounded repair, not an inferred authority or operator file in
this feature. Do not bypass or merge the upstream again. Recheck pending identities before each
merge; base drift after an earlier merge holds the remaining train for a fresh
packet rather than treating the old bundle as approval of new base bytes.
This includes same-repository multi-node trains: a coordinator merge that
advances their base triggers a hold/re-review of remaining work. These checks
reject **observed** drift only. The existing `--match-head-commit` merge boundary
does not atomically pin base, so base can race after the last read; this repair
does not promise serializable or atomic base-bound merging. Stronger merge
concurrency control is a separate dependency if such a guarantee is required.

Frozen vocabulary: packaged protocol
`phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/protocol.md:2633-2638`
says `"status": "pending|running|pr_open|approved|merged|blocked"` and
`"head_sha": "<draft-PR-head-commit-SHA>"`; lines 2659-2660 reserve the
synthetic `_train_review_` record with status `approved`. Preserve these values,
the node grammar and native-fill vocabulary. This plan adds an optional field
and a new packet schema, not statuses to an existing frozen enum. Keep the
authorization-helper refactor and other agent-harness#915 residuals separate.

## Files and order

Production scope: six runtime files, three concepts above.

| File/entity | Action and purpose |
| --- | --- |
| `phase-loop-runtime/src/phase_loop_runtime/train_review_packet.py` | Create typed input validation, Git/evidence snapshot, deterministic renderer, preview writer and receipt. |
| `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` | Modify packet construction/call sites, common stale-identity gate, approval cache, partial resume and pre-merge identity check. Keep `(artifact, run_mode)` review seam. |
| `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py` | Add optional packet digest and preserve through every serializer/copy. |
| `phase-loop-runtime/src/phase_loop_runtime/cli.py` | Add material/preview flags, argument refusals, early read-only preview branch and actionable JSON/human diagnostics. |
| `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | Extract only the existing prompt string assembly into a pure formatter used by the unchanged validating wrapper; no launch/authorization change. |
| `phase-loop-runtime/src/phase_loop_runtime/governed_review.py` | Add per-composed-seat packet preflight before mint/emission/invoke, preserving existing block result and authorization order. |
| `phase-loop-runtime/tests/test_train_review_packet.py` | Create real temporary-Git boundary fixtures and zero-model preview tests. |
| Existing train authorization/merge/prebuilt/native-fill tests named in suite | Update genuine fixture admissions/material and add cache/native-fill/resume regressions. Do not retain fake-head-only fixtures as proof of Git binding. |
| `docs/phase-loop/cross-repo-train-authoring.md` | Document input schema, preview, limits, material provenance and supported prebuilt-root governed behavior; remove its stale manual-merge instruction. |
| Packaged protocol cross-repo section cited above | Document optional digest, compatibility and packet format without changing frozen vocabulary; inspect packaging source before editing generated copies. |
| Four `skills-src/*/*-run-train/SKILL.md` and generated run-train mirrors | Explain preview-first supported path; fix stale `--ledger`/`--dry-run` instructions to existing `--ledger-dir` and actual preview command. Regenerate `phase-loop-skills/` with `phase-loop-runtime/scripts/regenerate_skills_bundle.py`, then packaged copies with `phase-loop-runtime/scripts/sync_skills_bundle.py`; retain only run-train output changes. |
| `CHANGELOG.md`; interim-ratification ledger | Record behavior/compatibility under Unreleased; append this landing's real authority row when reviewed. Never rewrite historical authority. |

1. Reconcile the plan with a real cross-vendor panel, especially D1's explicit
   generated-subtree representation. Freeze that decision before implementation.
2. Write failing boundary tests against current main, retain actual RED output,
   then implement D1/D2 and D3. Do not pre-author future SHAs or commit topology.
3. Narrow tests, plan suite, full suite and whitespace check; review the exact
   implementation candidate before any approved installable handoff.
4. Produce the real chunker preview without model calls and compare its
   admission/branch/ledger/checkpoint before/after. The chunker owner separately
   authorizes any next consumer panel; this task neither spends nor resets its
   exhausted one-round allowance.

## Verification and acceptance

Run commands from repository root with a task-owned supported Python environment.
Do not run them during this planning-only task.

```sh
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests .venv/bin/python -m pytest -q phase-loop-runtime/tests/test_train_review_packet.py
# Then the exact automation.suite_command above.
PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests
git diff --check
```

The new boundary suite must prove the failure mechanisms, not only serializer
shape: real Git base/head distinct from workspace HEAD; out-of-band live head;
base drift; unrelated base commits; two-node partial resume; missing objects;
CHANGELOG-like node label with changed code; renamed/deleted/mode-only files;
binary and symlink safety; stale/unbound evidence; mutated acceptance/context;
deterministic bytes across output directories; exact-bound and one-byte-over
limit; whole deleted subtree accepted only with exact attestation, and
overlapping/live/changed/misattributed groups refused; a source-looking group
with a valid disposal assertion is labelled for board judgment, never auto-
certified generated. Inject sentinel model,
broker, publication, recovery-write and merge functions that fail if reached
on preview/refusal. Hash ledger/checkpoint/branch identities before and after.

Round-1 executable test mapping (all proposed nodes in
`test_train_review_packet.py`, included by the automation suite):

| ID / test-name group | Required observation |
| --- | --- |
| T1 `test_historical_packet_*` | Missing/corrupt historical packet on partial resume holds before models/merges; valid retained history survives; no reconstruction from current main. |
| T2 `test_certificate_comparison_tree_*` | Attested merge-base binds inventory; group changed on main refuses; unrelated main change with equal subtree succeeds. |
| T3 `test_certificate_copy_out_*` | New identical outside blob refuses; preexisting outside duplicate is allowed; modified outside copy remains in full patch without semantic-rename claim. |
| T4 `test_observed_identity_drift_*` | Observed drift before approval/next merge holds, including same-repo multi-node resume; the merge test asserts the existing head pin and makes no atomic-base assertion. |
| T5 `test_packet_text_encoding_*` | CRLF, CRLF→LF, lone CR, literal backslash and forbidden Unicode round-trip through explicit encoding; read-back digest equals stored/native artifact digest. |
| T6 `test_certificate_visibility_*` | Only noncertified rows/group summaries inline; counts/digests and capped histograms truthful; operator sidecar absent from every provider-visible stage; governance groups refused. |
| T7 `test_git_reader_isolation_*` | Node-specific stores; dirty attributes and hostile diff/config/env cannot alter scope; patch/inventory cross-check catches omission; missing object never fetches. |
| T8 `test_render_preflight_*` | Real wrapper/core byte and error parity; both reachable variants; exact/one-over full prompt; last-seat overflow zero launches; fake tree still rejected; preview never mints/composes. |
| T9 `test_material_provenance_*` | Every check status mapping/app/name/head binding, attestation distinction, no-follow intermediate paths and manifest digest mutation. |
| T10 `test_preview_output_*` | Nonempty/symlink output refuses; atomic ready receipt, per-section sizes, zero model/broker/ledger/checkpoint effects. |

Retain existing renderer regression modules in the suite; all paths above name
future meaningful boundary tests, not tests claimed executed during planning.

For delivery, exercise real `governed_board_gate`/`invoke_board` authorization
under the sanctioned factory seam and inspect each rendered provider input:
actual changed-code/evidence sentinels and packet digest must survive, including
the Gemini inline/no-tools arm. Preserve existing egress/thread/launch tests.
Cover native emission/fill from the same packet, stale-fill-before-cache,
legacy count-only approval, unchanged cache hit, and mutation of every bound
component causing re-review or a typed hold with zero merges.

Operational artifact:
`.phase-loop/train-review-packet/<run-id>/chunker-preview-evidence.json`, plus
the generated packet/receipt and raw read-only command logs. Record candidate
runtime/source pin, actual train/admitted/base/head identities, all 82 substantive
paths at the observed S27 input, the explicitly represented removal groups,
packet bytes/digest, validation evidence provenance, zero model calls, and
unchanged supplier ledger/checkpoint/branch. Those counts are observations of
the pinned input, not requirements on a future changed candidate. Store no
credentials or auth payloads. A generated preview cannot prove provider delivery;
the separate boundary receipt proves wiring, while a newly authorized consumer
review remains the end-to-end verdict. Import operational evidence through a
runner-stamped plan amendment and append its path/digest/disposition to this
plan's manifest lifecycle before downstream reliance; never replace historical
failed or proxy receipts with a success claim.

- [ ] **Packet scope and truthfulness:** all substantive admitted changes,
  criteria and head-bound evidence, with explicit removal certificates or
  clear pre-model refusal — `test_train_review_packet.py`.
- [ ] **Zero-model preview:** meaningful bytes/digests and no broker/model/
  publication/ledger/checkpoint/branch changes — CLI boundary tests in that suite.
- [ ] **Same material at every selected seat:** authorized inline packet
  includes source/evidence under existing isolation, including no-tools Gemini —
  packet delivery tests and `test_train_review_authorization.py`.
- [ ] **Approval and native-fill integrity:** changed inputs cannot reuse
  approval; legacy records re-review; untouched packet resumes safely;
  partial merge stays forward-only — packet/train-merge/native-fill suites.
- [ ] **Compatibility and governance:** plan suite, full suite,
  `test_skills_canon_parity.py` and `git diff --check`; no launch/broker/isolation
  relaxation or changed historical manifest authority.
- [ ] **Consumer handoff:** actual chunker zero-model preview evidence retained
  and runner-stamped; supported command plus reviewed/tested installable source
  pin returned to agent-harness#906. Do not claim treesitter-chunker#97 approved,
  merged, released or unblocked for landing without its own authorized result.
