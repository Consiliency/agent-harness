# Detailed plan: content-checked TypeScript publication

## Task

Resolve Consiliency/agent-harness#1765 so the supported normal publisher can classify real new or existing TypeScript implementation modules whose filenames match its secret heuristic. Keep actual credential artifacts and scanner findings refused. This prerequisite serves ViperJuice/delta-pi#7; no Pi activation, credential provisioning, live browser input or business action is included.

## Research summary

Input base is origin/main `bcc9b7eac6cc19de82b9fb0334fdaafe65c6b86e`; the new owned worktree starts clean. In `phase-loop-runtime/src/phase_loop_runtime/publishing.py`, `_is_secret_path` deliberately rejects credential-like names. `_source_path_evidence` currently accepts only existing regular Python blobs which parse/compile, contain a top-level function/class and pass built-in detect-secrets1.5.0 detectors. `_audit_staged_diff` binds evidence to the frozen parent/tree; `_validate_transaction_source_audit` rederives it during construction/resume. Existing Python tests pin this safety policy. The normal route has no caller exemption; existing prebuilt behavior is distinct and unchanged.

The actual consumer refusal is preserved at `/tmp/delta-authlogin-source-r2/publication-result.json`; its frozen source acceptance is `/tmp/delta-authlogin-source-r2/source-acceptance.json`. Source module and test are new `.ts` files. Offline detector inspection returns no finding for the implementation and a KeywordDetector finding for a synthetic literal in the companion test. This repair must keep that finding blocked; consumer fixture correction and renewed source validation are separate work.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/publishing.py` (modify)

- Extend `_source_path_evidence` by an explicitly separate TypeScript branch, keeping existing Python behavior and policy records unchanged. Reuse literal Git object lookup, returned-path equality, regular modes, bounded blob size and frozen hashes; do not read candidate worktree content or execute repository code.
- TypeScript scope requires first path component exactly `src`, `test` or `tests`, and a final component ending in `.ts`. Refuse a lowercased final name ending in `.d.ts` before suffix admission; preserve part-wise `.env*`, `.key`, `.pem`, `.p12`, `.pfx` exclusions. Other roots/languages, TSX, JavaScript, nonregular entries and deletions remain refused. Do not alter `_is_secret_path` or add allowlists.
- Use one literal `ls-tree -z` per revision. `None` means lookup failure and refuses; only a successful parent `b""` means absence. A staged empty/failed lookup or any present nonregular entry refuses. An addition is membership in the frozen `--name-only --no-renames -z` enumeration, plus that proven parent absence, plus the exact-path regular staged blob. No separate status query. Existing TypeScript requires both revisions to pass the same bounded regular-file, strict UTF-8, NUL-free and body/parse checks; a data-only parent cannot gain a body through this exception. Preserve new-Python refusal.
- Inside the TS branch only, version-check/import installed `tree-sitter==0.25.2` and `tree-sitter-typescript==0.23.2`. Decode once with strict UTF-8, refuse NUL, and parse the bytes using the TypeScript grammar under warnings-as-errors. Require a present tree with `root_node.has_error is False`. Require existence of `function_declaration`, `generator_function_declaration` or `class_declaration` with non-null body, directly under `program` or as the declaration of one top-level `export_statement`. Imports/types/interfaces may coexist. Other forms cannot qualify on their own; the companion matrix names them. Parsing is not compilation or execution-safety proof. Missing/mismatched parser raises into fixed `source_scan_failed`; warnings, invalid input and missing trees refuse without source diagnostics. No new parse-time guarantee.
- Scan every line of the entire staged text with the unchanged pinned detect-secrets1.5.0 built-in detectors, passing the repo-relative filename; no repository configuration, baseline, inline suppression, filter exemptions or online verification. Any finding refuses, including test canaries. Preserve the existing line-splitting policy. The quote-required TS keyword rules can miss typed assignments (`name: Type = "…"`) and keywords split from literals across lines; these are detected only if another detector fires. Encoded/obfuscated/separator-split values can also evade detection. Admitting new heuristic-named files exposes those misses on the same detector-bounded basis as existing Python; ordinary filenames already publish unscanned. Source review remains required; no universal secret-absence claim.
- TS evidence has exactly seven JSON-native string/null fields: `path`, `parent_blob_oid` (null only for proven addition), `blob_oid`, `blob_sha256` of raw staged bytes, `tree_sitter_version="0.25.2"`, `tree_sitter_typescript_version="0.23.2"`, and `policy="typescript-detect-secrets-1.5.0-v1"`. Python retains its exact five keys/policy. Construction/resume rederive evidence from frozen objects; no new envelope, broker authority, journal vocabulary, manual receipt or prebuilt shortcut.

### `phase-loop-runtime/pyproject.toml` and `phase-loop-runtime/uv.lock` (modify)

- Add the two exact parser dependencies; run `uv lock` without upgrade, inspect only those pins/their requirements, then lock-check and locked-sync. No runtime version bump, unrelated upgrade or Node/toolchain dependency. Verify clean installed-wheel tests on CPython3.12 and current3.14, each importing the grammar and parsing. Unavailable packages are technical prerequisites to resolve, never skips.

### `phase-loop-runtime/tests/test_publishing.py` (modify)

- Implement the mandatory failing-first fixture matrix in this plan's `_reviews.md` companion: mixed implementation statements, clean test module, generator/class, new/existing/deleted paths, recovered syntax errors, `.d.ts`, detector canary, exclusions and privacy/import controls. No consumer literal or source copy.
- Preserve staged-versus-worktree, literal-path, drift, bounded-size and detector failure negatives. Capture result/stdout/stderr/warnings and use the no-network guard on a finding-producing canary negative as well as clean positives. No candidate execution.
- New/existing/mixed Python+TS transaction positives reload via `inspect_publish_resume_candidate` after construction and seal, asserting non-CONFLICTED state and fresh-rederive equality. Persisted audit tampering, missing/direct-preparation audit and parent/newness/policy/blob drift refuse before further ref/provider effects. Pin both record key sets/literals. Existing Python/prebuilt/owned-scope/recovery regressions stay intact.

### `phase-loop-runtime/README.md` (modify)

- Own only "Publication source audit": preserve the existing Python/new-Python policy; describe the narrow TS roots, named body/parse checks, both-revision or proven-addition requirements, exclusions, scanner/warning behavior and detector limits above. Historical review/changelog text remains unchanged.

### `docs/reviews/typescript-source-publication-1765.md` (create)

- Document bounded policy, exact parser/scanner versions, compatibility/limits, actual verification and independent reviews. Also record inherited Unicode-separator alignment and Git replacement/object-identity limitations; no partial hardening is claimed. Keep historical `publish-source-893.md` unchanged. New labels are internal metadata.

Planning controls: this plan and its `_reviews.md` companion (mandatory fixture matrix and actual review history). No other source paths are owned. The consumer's accepted tree stays untouched. Actual R1 ruling and adopted/deferred records are bound in the companion; filing Consiliency/agent-harness#1766 precedes implementation dispatch. Deferred breadth is not reopened without new criterion/reachability evidence.

Execution scope amendment: `CONTRIBUTING.md` requires an Unreleased changelog entry for user-visible behavior. Own only a short new `CHANGELOG.md` Unreleased entry describing this TypeScript source policy and dependency pins; leave all historical entries unchanged. The original unanimously reviewed plan bytes and acceptance remain frozen externally. This bookkeeping amendment and its implementation require the fresh source board's approval; original plan votes do not approve the amendment.

## Dependencies and order

1. Four fresh read-only plan lenses: native Astra/max, Grok4.7 adversarial/xhigh, Grok4.7 alternative/xhigh, manually launched first-party Frontier Opus5.5/max with Read/Glob/Grep and owner-authorized sandbox bypass. Unlimited rounds until all agree; a separate Frontier president for every nonunanimous round. Collect all finals before one combined repair. Never convert a provider failure to approval.
2. Root implements only after plan convergence. Add failing controls first, then narrow code/dependency changes, then batched verification. No write-capable review workers.
3. Four fresh final source reviews with the same policy. Bind actual artifact/tree/wheel hashes externally without fabricating runtime review or publication authority. Repair findings until convergence.
4. Publish through the supported normal human-invoked FABPUB adapter, link the actual PR immediately, inspect exact head/base/checks/comments, watch CI, merge only after readiness, archive proof and prune the owned merged worktree/branches.
5. Install only the reviewed/tested local runtime artifact through supported tooling. Audit-only probe the exact preserved consumer index; a fixture detector finding remains refused. Correct that synthetic fixture separately with fresh generated canary data, rerun display/ARM verification and fresh consumer reviews as required, then retry the original supported source publisher. Do not rename files, suppress detectors, hand-edit authority, force a prebuilt route or bypass the gate to land the consumer.

## Verification

Use public `run_verification` with actual command executions and validate actual verification artifacts. Environment preflight: existing Python/runtime, uv, config, lock and dependencies. Run narrow publishing tests before the adjacent transaction/broker selectors; repeat only for a new change or unresolved failure.

```sh
uv lock --project phase-loop-runtime --check
uv sync --project phase-loop-runtime --group test --locked
uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_publishing.py
uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_unadmitted_prebuilt_recovery.py phase-loop-runtime/tests/test_fabpub_sealed_head_recovery_1296.py phase-loop-runtime/tests/test_fabpub_recovery_chain_1310.py phase-loop-runtime/tests/test_fabpub_typed_handoffs.py phase-loop-runtime/tests/test_train_prebuilt.py phase-loop-runtime/tests/test_publish_scope_correction.py
uv build --project phase-loop-runtime --wheel --out-dir .phase-loop/verification/typescript-source-publication/wheels
git diff --check
```

Install the wheel in separate private CPython3.12/3.14 environments; actually import the grammar/parse a sample and run packaged publishing/adjacent tests without source PYTHONPATH. Check exact Requires-Dist pins, installed versions, lock delta, packaged bytes and offline behavior. Complete appropriate repository checks/closeout audit. An audit-only consumer probe passes only if implementation classification yields TS evidence, the companion canary refuses, and output contains metadata/digests only with zero publish calls; this is not consumer acceptance.

## Acceptance criteria

- [ ] New/existing in-scope TypeScript source passes only with actual syntax/body classification and a clean full frozen-blob detector scan; proven by real publishing fixtures and packaged tests.
- [ ] Findings from the pinned built-in detectors on any line of the staged blob (including synthetic canaries), artifact/declaration/data-only paths and content, parser failures including recovered syntax errors, unsupported inputs, and substitution by worktree decoy, literal/glob/newline path, staged tree/parent drift or missing/tampered audit records remain refused with no secret/source diagnostics; proven by negative fixture controls.
- [ ] Normal transaction construction and resume independently rederive exact TypeScript audit records; missing/tampered/newness/blob metadata refuses before publication side effects; proven by transaction regressions.
- [ ] Existing Python/new-Python refusal, prebuilt/recovery/owned-scope behavior remains unchanged; proven by all existing publishing and adjacent tests.
- [ ] Built wheel declares exactly both parser pins in Requires-Dist and contains verified source; clean installed tests on both interpreters and audit-only metadata probe pass, with no live/credential actions or false consumer-success claim.
- [ ] Actual four-seat plan/source convergence, supported publication/required checks, reviewed installation and cleanup are separately recorded; live consumer acceptance remains unclaimed.

Automation suite command: `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_publishing.py`.
