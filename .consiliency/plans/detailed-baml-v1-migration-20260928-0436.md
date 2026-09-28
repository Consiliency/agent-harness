# Detailed plan: migrate BAML v0 (baml-py 0.222) to BAML v1 0.20.1 (baml-bridge)

Tracking issue: agent-harness#1135. Spike evidence is in the issue body and in two comments: the D1a addendum and the round-1 addendum. Spike directory: `/mnt/workspace/spikes/baml-v1`. This plan cites the evidence and does not repeat it.

Revision 2 folds in:
- the maintainer's decisions (D1: v1 renders the closeout prompt; D2/D3/D4/D5/D6 as recommended);
- the lead's D1a;
- the agent-harness#1136 round-1 board findings (codex 1–5, claude B1–B6, grok §1–§7);
- an item-by-item check of the upstream 0.20.1 release notes.

## Task

Replace the `baml-py>=0.222,<0.223` dependency of `phase-loop-runtime` with BAML v1 0.20.1, published as `baml-bridge==0.20.1` (import name `baml_bridge`).

- The `.baml` sources and `baml_modular.py` move to the v1 language and runtime.
- Every public behavior of `phase_loop_runtime.baml_modular` is either preserved or listed in the **divergence register** below with a disposition. No divergence may be left unlisted.

## Research summary

- **Runtime surface.** Only `baml_modular._runtime()` imports `baml_py`. Two live paths reach the runtime:
  1. `discovery.py` → `parse_baml_response("EmitPhaseCloseout")`. This is the closeout path.
  2. `evidence_audit.py` → `build_baml_request("EvaluateSuspectedFakeEvidence")`. This is the tier-3 HTTP request.
- **Under D1 a third path moves onto the runtime:** `injection.py` → `build_baml_request("EmitPhaseCloseout")`.
- Everything else is regex over the `.baml` text and does not touch the runtime: schema export, class-name parses, and `render_baml_prompt`.
- **Pre-render is already wired.** `_read_baml_files()` returns `render_baml_prompt(path.read_text(), _baml_prompt_context_constants())` for every file. That is what both v0 `from_files` and the planned `initialize_runtime` receive. This refutes grok §5's "placeholder wiring hole". Spike: after pre-render, no `{{` or `{%` is left in any planned source.
- **v1 language and API changes:**
  - Removed: `client<llm>` (E0010), `#"…"#` (E0098) and Jinja. Only the two function files fail `baml check` as-is.
  - `BamlRuntime.initialize_runtime(root, files)` is an in-memory, process-global singleton. The root is virtual: a decoy `./baml_src` in the cwd is ignored.
  - `Fn@spec(k = v, …).parse(raw)` and `.build_request()` replace `parse_llm_response` and `build_request_sync`.
  - Python calls packaged bridge functions through `define_function("user.<fn>", "sync", params)`. The bridge functions return only primitives, so no codegen typemap is needed.
- **Parity, measured against real v0 on main** (round-1 addendum):
  - Evidence request, 3 sentinel payloads: url, method, headers, body and prompt are all **equal**.
  - Closeout parse corpus: **93 of 94 identical**. The inputs are 30 synthetic cases plus 64 real fixtures.
  - Schema dump (24 classes, 26 exports, enum map): **equal** under D3.
  - Closeout prompt: differs by design (D1). Exactly two hunk classes, and the D1a tail is byte-identical.
- **CI installs with `pip install "./phase-loop-runtime[visual]"`** (`.github/workflows/test.yml:315`), so pyproject bounds are what CI enforces. `uv.lock` is advisory there.

## Frozen public surface

These names keep their signatures, return shapes and exception type (`BamlValidationError`):
`build_baml_request`, `parse_baml_response`, `export_function_schema`, `inject_schema_description`, `render_baml_prompt`, `BamlValidationError`, `PhaseLoopCloseoutV1`, `BamlRequest`, `ParsedResponse`.

Allowed changes are only the ones in the divergence register. `protocol.md` (both copies) names only these symbols, and its schema-hash promise (around line 1341 / 1418) is kept by D1a, so **no protocol edit and no new vocabulary**. The closeout field set and enum literals are unchanged. Exception message text is not contractual: v0 messages were already runtime-specific. Tests assert types, not text.

## Divergence register (every v0→v1 difference found; nothing left open)

| # | Divergence (evidence) | Disposition | Pinned by |
|---|---|---|---|
| 1 | Evidence request role `system` instead of v0 `user` | **Neutralized**: `${role("user")}` in the prompt | evidence v0 golden (full request equality) |
| 2 | v1 drops the `baml-original-url` header (codex 1, B1, grok) | **Neutralized**: `EvidenceAuditClient = openai.GenericClient.new(…, headers = {"baml-original-url": "https://example.invalid/v1"})`. Spike: headers equal v0 | evidence v0 golden |
| 3 | Tier-3 prompt/body could drift: dedent, output format, client options, message count, content shape (B1, grok div. 4) | **Neutralized, and measured equal**: all fields identical to v0 for 3 sentinel payloads (`${PROJECT}`, `{{ x }}`, `{% for %}`, backtick, backslash, newline, non-ASCII, empty, padded). The file has no loops, so loop layout cannot apply | evidence v0 golden (3 payloads) |
| 4 | Closeout loop layout: no blank lines between items | **Accepted (D1)** | Prompt-byte refresh |
| 5 | Closeout output-format block: v1 `{ field: type }` replaces the per-field list with enums | **Accepted (D1)**. Enums remain in the "Required contract" prose and in the D1a block | Prompt-byte refresh; test asserts every enum literal still appears in the prompt |
| 6 | Closeout schema-description block (marker + `schema_sha256`) absent from v1 | **Neutralized (D1a)**: Python appends it; tail byte-identical to v0 | D1a test |
| 7 | Extra payload key: v0 ignores it, v1 raises `BamlError` | **Neutralized**: Python filters the payload to the function's parameters, read from the `.baml` signature | real-runtime test |
| 8 | Missing payload key: v0 raises `BamlValidationError`, v1 raises `BamlError` | **Neutralized**: Python raises `BamlValidationError` naming the key before any runtime call | real-runtime test |
| 9 | `closeout_commit_sha=""`: v0 renders `none`, v1 renders empty (`??` only replaces null) | **Neutralized**: normalize as v0 did (`sha or None`; lists `or []`; items `str()`; `phase_alias` `str(… or "")`) | real-runtime test |
| 10 | Backslash in a closeout list value: **v0 raises `re.error`** (pre-existing bug in `_render_baml_list_loop`; not caught by `injection.py`); v1 renders it literally | **Accepted: this is a fix** | real-runtime test (the `C:\new\s` case renders literally) |
| 11 | `${…}`/`{{…}}`/`{%…%}` inside caller values (codex 3, B6) | **Parity, measured**: literal in both. Under D1 values are interpolated by v1, never by our pre-render | real-runtime test with `docs/${PROJECT}/guide.md`, `P${PROJECT}{{ x }}`, `{% if %}` |
| 12 | Parse: int > i64 is clamped in v0, `null` in v1 (the only corpus divergence) | **Accepted**: the field is optional, and the visual gate decides from the decoded image | v0 parse-corpus golden (entry marked as the disclosed divergence) |
| 13 | `BamlPanic` is a `BaseException`: compile failure at init, call before init, call after `shutdown_runtime()` | **Neutralized**: mapped to `BamlValidationError` (see ownership contract) | subprocess real-panic tests |
| 14 | In-BAML runtime panics surface as `BamlError` ("Unknown class FQN 'baml.panics.*'") | **Neutralized**: every bridge call maps `Exception` to `BamlValidationError` | real-runtime test via foreign re-init |
| 15 | Process-global runtime; `atexit(shutdown_runtime)`; an import-time unhandled-spawn hook that calls **`os._exit(1)`** and cannot be replaced (spike: re-registering does not override it) | **Contained**: one owner, lock, per-call fingerprint (below); hook kept unreachable (no `spawn` in our sources; 0 `spawn` in the builtins on our call paths); `baml_bridge` imported lazily; **disclosed** (D6, CHANGELOG) | ownership, no-spawn and lazy-import tests; subprocess exit-code tests |
| 16 | First call about 0.7 s (v0 about 0.18 s) | **Accepted**, disclosed | none |
| 17 | New transitive `protobuf` | **Bounded** in pyproject: `protobuf>=6.31.1,<8` | dependency test |
| 18 | baml-py's `baml` / `baml-cli` console scripts disappear | **Accepted**, disclosed. Nothing in this repo invokes them | none |
| 19 | Exception message text | **Accepted**, not contractual | none |
| 20 | `BamlRequest.id`: v0 evidence requests carry a random per-call `breq_…` (spike: two calls, two ids); v1 has none, so it becomes `None` | **Accepted**: the value was nondeterministic and `git grep` finds no consumer of `BamlRequest.id` outside `baml_modular.py`; the closeout path already returned `None` | evidence golden compares every field except `id`; test asserts `id is None` |

## Decisions (all decided)

- **D1 — DECIDED by the maintainer (agent-harness#1135): v1 renders the closeout prompt, and its bytes change.** This was not my recommendation. The Python renderer is deleted: `_build_emit_phase_closeout_request`, `_render_emit_phase_closeout_prompt`, `_render_baml_list_loop`, `_function_prompt_template`, `_closeout_output_format`, `_schema_type_label`. `git grep` finds no callers outside `baml_modular.py`. This also retires grok §5's `_function_prompt_template` regex issue.
- **D1a — DECIDED by the lead under D1.**
  - Python appends `"\n\n" + _render_schema_description(export_function_schema("EmitPhaseCloseout"))` to both `BamlRequest.prompt` and `body["messages"][0]["content"]`.
  - The role is set in BAML with `${role("user")}`.
  - The prompt text comes from the built request (`_extract_prompt(body)`), not from `.prompt().to_string()`, which prepends `[user]\n`.
  - Reason: `injection.py` (around line 436) cuts at `"\n\nPhase-loop closeout JSON schema description:\n"`, and `protocol.md` promises the schema hash. `schema_sha256` hashes the canonical JSON of the exported schema dict (`_render_schema_description`: `json.dumps(schema, sort_keys=True, separators=(",", ":"))`), not the source text. D3 leaves the schema equal, so the hash stays `77e72437…`.
- **D2 — DECIDED: in-memory `initialize_runtime` plus a packaged bridge `.baml`.** The process-scope collision that codegen avoided at install time still exists at process scope. It is handled by the ownership contract; nothing about it is assumed away.
- **D3 — DECIDED:**
  - `_class_fields` accepts both field forms with one regex: `([A-Za-z_]\w*)\s*:?\s*([A-Za-z_]\w*(?:\[\])?)(\?)?\s*,?`.
  - All sources are formatted with `baml fmt`.
  - CI enforces fmt stability (see `baml-sources` job).
  - Spike: the schema dump is equal, and the regex returns v0's result on the legacy text.
- **D4 — DECIDED: hard switch.** That makes Step 0 (capture the v0 baselines before the switch) mandatory.
- **D5 — DECIDED: hash-enforced install stays out of scope.** It is compensated by bounding the one new transitive dependency in pyproject (grok §4, B-Q4).
  - Justification for `protobuf>=6.31.1,<8`: baml-bridge's `_pb2` files are generated for protobuf 6.31.1 and call `ValidateProtobufRuntimeVersion(PUBLIC, 6, 31, …)`. The floor matches that gencode. The spike loads and parses cleanly under `-W error` on both 6.31.1 and 7.36.2. protobuf's runtime-version policy rejects a runtime more than one major version ahead of the gencode, so `<8` excludes the first version expected to break.
- **D6 — DECIDED: exact `baml-bridge==0.20.1`; the maintainer accepted the canary.** Full risk list as disclosed in the CHANGELOG:
  - the process hooks (#15);
  - process-global ownership (#15);
  - the protobuf window (#17);
  - platforms not load-tested (below);
  - the less-travelled `define_function` path (D2);
  - first-call latency (#16);
  - rollback: revert to `baml-py>=0.222,<0.223` and cut a patch release (a full revert of this PR; no data migration).

## Runtime ownership contract (codex 2, B4, grok §3)

- **State.** Module-level `_RUNTIME: _RuntimeHandle | None` guarded by `_RUNTIME_LOCK = threading.Lock()`. This replaces `lru_cache` on `_runtime()`, which does not serialize a cold miss.
- **`_read_baml_files()` becomes two-step, and it is the single source for every consumer:** the schema regexes, `_runtime()`, the CI `baml-cli check` and the tripwire.
  1. Read the raw packaged files.
  2. Compute `fp = sha256(canonical JSON of {name: raw_text})`. It is computed over raw bytes, so it is not circular.
  3. Render with `render_baml_prompt(text, {**taxonomy, "phase_loop_bridge_fingerprint": fp})`.
  4. Fail closed (`BamlValidationError`) if any `{{` or `{%` remains in a rendered file. This template check replaces the old "no `${` in output" idea (codex 3, B6), because caller data never passes through the pre-render.

  It returns the rendered map, and `fp` is exposed with it (for example `_read_baml_files_with_fingerprint()`, with `_read_baml_files()` delegating to it).
- **Initialization** (under the lock; runs only when `_RUNTIME is None`): take the rendered map and `fp` from the step above, call `initialize_runtime`, then verify that `phase_loop_bridge_fingerprint()` round-trips.

  A failed init raises `BamlValidationError`, leaves `_RUNTIME` as `None`, and retries on the next call. Spike: a failed init keeps the previously loaded native runtime.
- **Per-call ownership.** Every bridge function returns `map<string, string>` whose keys are `"fingerprint"` plus exactly one of `"ok"`, `"error"` or `"request"`. Python requires that exact key set and `fingerprint == handle.fp`; anything else raises `BamlValidationError("BAML v1 runtime is not owned by phase_loop_runtime …")`. Because the check is inside the same call, there is no check-then-call race.
  - A foreign program without our functions raises `BamlError`, which maps to `BamlValidationError`.
  - A same-shape program built from different files returns the wrong fingerprint, which is rejected.
  - After `shutdown_runtime()`, `BamlPanic` maps to `BamlValidationError`.
  - **No silent re-initialization.** A replaced runtime fails closed until the process restarts; this is disclosed.
- **Test hook.** `_reset_runtime_for_tests()`, a private helper that clears the state under the lock. Fixtures that swap sources must call it again in teardown.
- **Exception mapping (`_call_bridge`).**
  - `except Exception` → `BamlValidationError`.
  - `except BaseException as e`: map to `BamlValidationError` when `isinstance(e, sys.modules["baml_bridge.errors"].BamlPanic)` or it is `pyo3_runtime.PanicException`; otherwise re-raise. `KeyboardInterrupt`, `SystemExit` and `GeneratorExit` are never mapped.
  - `isinstance` replaces the name check (B3). Laziness is kept, because a bridge exception implies the module is already loaded.
- **Hooks.**
  - `baml_bridge` is imported only inside `_runtime()`, so importing `baml_modular`, `discovery`, `evidence_audit` or `injection` installs nothing.
  - The `os._exit(1)` path needs a detached `spawn` that fails. None exists in our sources, and none exists in the builtins our calls reach (checked with `baml describe`; see the round-1 addendum).
- **Evidence-audit semantics are unchanged.** `BamlValidationError` subclasses `ValueError`, so `evaluate_suspected_fake_evidence` keeps returning `_uncertain_fallback`, as it does today. It is never a pass.

## Step 0 — capture v0 baselines on main BEFORE the switch (B1, B2, B5)

- **Environment.** Run in a baml-py 0.222.0 venv against a clean `origin/main` worktree. Record the main SHA and the `baml-py` version inside each file.
- **Script.** `phase-loop-runtime/tests/data/baml_v0_baseline/capture_v0.py` is committed. It is not collected (no `test_` prefix), and a provenance header says it is one-shot. It writes:
  - `parse_corpus.json`: inputs → v0 outcome, either the full `ParsedResponse.payload` or `"BamlValidationError"`.
    - Inputs: the spike's 30 synthetic cases, including truncated string or object, two objects, trailing comma, single quotes, JS comment, extra key, required `null`, `null` list, wrong nested types, array root, wrapped, enum case, `dry_run`, complete with no gates, bad or `none` blocker, pixel values `2**70` and `5.7`, and unicode.
    - Plus every file under `tests/fixtures/**.json` and `tests/data/*closeout*` that contains `"terminal_status"` (64 today).
  - `evidence_requests.json`: the 3 sentinel payloads → the full v0 `BamlRequest` (url, method, headers, body, prompt).
  - `closeout_prompts_v0.json`: the "before" half of the refresh. It holds the payloads `empty`, `two_gates_sha`, `two_gates_nosha`, `sentinels` and `sha_empty` → v0 prompt text and sha256. `backslash` is recorded as `re.error`.
  - `schema_dump.json`: `_class_fields` for every class, `export_function_schema` for every class and PascalCase function, and `_enum_literal_map`.
- **Commit.** These files are the first commit of the implementation PR, `test(baml-v1): capture v0 baselines (agent-harness#1135)`, and are never regenerated after the switch. The spike already produced equivalents in `/mnt/workspace/spikes/baml-v1`; the implementer regenerates them on the then-current main.

## Changes

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project].dependencies` — replace `"baml-py>=0.222,<0.223"` with `"baml-bridge==0.20.1"` and add `"protobuf>=6.31.1,<8"` (D5/D6). The package-data glob `baml_src/*.baml` is unchanged and ships the bridge file.

### `phase-loop-runtime/uv.lock` (modify)
- Run `uv lock`. Expected: remove `baml-py`; add `baml-bridge 0.20.1` and `protobuf` inside the bound. Check that the baml-bridge wheel hashes equal the PyPI digests in agent-harness#1135. The lock stays advisory in CI (D5).

### `baml_src/emit_phase_closeout.baml` (modify)
- `client PhaseLoopCloseoutClient = openai.GenericClient.new(model = "phase-loop-closeout", base_url = "https://example.invalid/v1");`
- `EmitPhaseCloseout`:
  - `client:` / ``prompt: `${role("user")}` …``;
  - `${phase_alias}`;
  - loops become `${xs.map((g) -> { "- " + g }).join("\n")}`;
  - `${closeout_commit_sha ?? "none"}`;
  - `${ctx.output_format()}`;
  - the taxonomy `{{ allowed_* | join(', ') }}` placeholders stay, because they are pre-rendered.
- `PhaseLoopCloseoutV1`: `name: type,` (D3). Comments and enum-literal comment blocks stay byte-identical.

### `baml_src/evaluate_suspected_fake_evidence.baml` (modify)
- `client EvidenceAuditClient = openai.GenericClient.new(model = "phase-loop-evidence-audit", base_url = "https://example.invalid/v1", headers = {"baml-original-url": "https://example.invalid/v1"});` (register #2).
- `EvaluateSuspectedFakeEvidence`: `client:`, ``prompt: `${role("user")}` …``, `${arg}`, `${ctx.output_format()}`.
- `EvidenceJudgment`: D3 syntax.

### Other six `.baml` files (modify — D3 syntax only)
- Apply `baml fmt`. `// … enum literals:` comments stay byte-identical, and the schema dump must equal Step 0.

### `baml_src/phase_loop_bridge.baml` (create — new host-glue logic, not mechanical syntax)
- `phase_loop_bridge_fingerprint() -> string` returns `"{{ phase_loop_bridge_fingerprint }}"`, pre-rendered.
- `phase_loop_parse_closeout(raw: string) -> map<string, string>`:
  - `EmitPhaseCloseout@spec(phase_alias = "", plan_produces = [], plan_owned_files = [], closeout_commit_sha = null).parse(raw)`;
  - catch `baml.errors.ParseError` and return `{fingerprint, error}`;
  - otherwise return `{fingerprint, ok: baml.json.to_string(v)}`.
- `phase_loop_closeout_request(phase_alias, plan_produces, plan_owned_files, closeout_commit_sha) -> map<string, string>` returns `{fingerprint, request: baml.json.to_string(EmitPhaseCloseout@spec(<by keyword>).build_request())}`.
- `phase_loop_evidence_request(tier2_signal_summary, sample_artifact_content, expected_artifact_characteristics) -> map<string, string>`: the same shape.
- Every `@spec` call passes arguments **by keyword** (spike-verified), so a reorder cannot silently swap two `string` arguments (B1).
- The file contains no `class`, so the schema regexes cannot see it, and no `spawn`.
- **Spike-verified exactly as written.** The round-1 addendum's `parity.py` and `corpus.py` were rerun against this shape, with the fingerprint embedded in every returned map including the `catch` arm. The exact key set and the fingerprint match were asserted on every call. Results: evidence equality on 3 of 3 payloads, and the corpus at 93 of 94 identical.

### `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py` (modify)
- `_runtime`, `_RuntimeHandle`, `_RUNTIME_LOCK`, `_call_bridge`, `_reset_runtime_for_tests`: add or modify per the ownership contract.
- `build_baml_request`:
  - Look up the bridge by function name (`EmitPhaseCloseout`, `EvaluateSuspectedFakeEvidence`). Anything else raises `BamlValidationError("no v1 bridge for <fn>")`. v0 accepted any function; only these two exist.
  - Filter and require the payload per register #7/#8, using the parameter list read from the `.baml` signature, and call **by keyword**.
  - Normalize the closeout payload (#9).
  - Build `BamlRequest(url, method, headers, body=json.loads(body), prompt=_extract_prompt(body))`.
  - For `EmitPhaseCloseout`, append the D1a block to both the prompt and `messages[0].content`.
  - `id` is `None` (register #20).
- `parse_baml_response`, runtime branch: `phase_loop_parse_closeout`, then `error` → `BamlValidationError`, else `PhaseLoopCloseoutV1.model_validate(json.loads(ok))`. The pydantic validators stay the final gate. The class-name branch is unchanged.
- `_class_fields`: the D3 dual-form regex.
- Delete the D1 renderer set, `_type_modules`, and `_filtered_env`. `_filtered_env`'s only callers were the v0 runtime calls, and `initialize_runtime` takes no env (release-notes item (d)).
- `_is_pyo3_panic` / `_raise_baml_validation_error`: fold into `_call_bridge`.

### `phase-loop-runtime/scripts/_gate_a_probe.py` (modify) — release-notes (f)
- In the BAML resolution block (around line 44), add: assert `importlib.metadata.version("baml-bridge") == baml_bridge.get_toolchain_version() == "0.20.1"`, then run a real `parse_baml_response("EmitPhaseCloseout", <valid>)`. This runs in the PR `wheel smoke` job and in Gate A on push, nightly and tags. It is a script, so it is outside the agy pin set.

### `.github/workflows/publish-pypi.yml` (modify) — release-notes (f)
- Release-wheel smoke heredoc (around line 93): add the same version assertion and real parse.

### `.github/workflows/test.yml` (modify) — D3 / release-notes (e) (B5)
- New job `baml-sources` (its own job, following the rationale in the `lint` job's comment; `ubuntu-latest`, Python 3.12, `pip install ./phase-loop-runtime`, because step 5 imports the package):
  1. Download `baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz`.
  2. `sha256sum -c` against its `.sha256` **and** against the literal `6067729f14483eca4ab61bfcd3c1921818e9ecc66da035bc64fbbfeb850e2795`.
  3. Assert `baml-cli --version` = `baml-cli 0.20.1`.
  4. `(cd phase-loop-runtime/src/phase_loop_runtime && baml-cli --agent-skill-check off fmt baml_src/*.baml)`, then `git diff --exit-code` (fmt round-trip on the RAW sources; the spike showed fmt needs no `baml.toml`).
  5. Write the pre-rendered sources to a temp project with `_read_baml_files()`, then `baml-cli check` (expect 9 files).
- **Make it blocking the way this workflow already does it.** A skipped job satisfies a required check, and the `gate` job runs with `if: always()`, so being listed in `needs` alone does not fail it. Therefore:
  - add `baml-sources` to the `gate` job's `needs` (it currently reads `needs: [offload, hosted]`);
  - add `BAMLSRC: ${{ needs.baml-sources.result }}` to its env;
  - make the step `exit 1` unless `BAMLSRC` is `success`, alongside the existing exactly-one-verdict check.

  `baml-sources` itself must not have an `if:` that can skip it.

## Tests

New file `tests/test_phase_loop_baml_v1_runtime.py`, real runtime, no stubs. Tests that swap sources restore the runtime in teardown with `_reset_runtime_for_tests()`.

- **Parse corpus:** every Step 0 `parse_corpus.json` entry gives exactly the same payload or `BamlValidationError` under v1. The one disclosed entry (`pix_2p70`) asserts `null`.
- **Evidence request:** for each Step 0 `evidence_requests.json` payload, the full `BamlRequest` equals v0 (url, method, headers including `baml-original-url`, body, prompt); `id is None` (#20).
- **Payload handling:** an extra key is ignored and equals v0; a missing key raises `BamlValidationError`.
- **Closeout:** the refreshed goldens (see refresh), plus:
  - D1a: the marker appears exactly once, `schema_sha256` equals the export, one user message, content equals the prompt, and no leading `[`;
  - every taxonomy literal appears in the prompt (#5);
  - the sentinel, `${PROJECT}` and backslash values render literally (#10, #11);
  - `sha=""` renders `none` (#9).
- **Schema dump:** equals Step 0 `schema_dump.json`.
- **Ownership:**
  - 8 threads on a cold state call `parse_baml_response` concurrently. `BamlRuntime.initialize_runtime` is entered exactly once, counted two ways:
    - a pass-through spy that still calls the real function (spike: assigning the attribute on the PyO3 class works);
    - a module-level init counter incremented inside the lock.

    All 8 threads also see the same `_RuntimeHandle` identity;
  - repeated `_runtime()` does not re-initialize;
  - a foreign re-init (`initialize_runtime` with an unrelated program) makes both public entrypoints raise `BamlValidationError`;
  - a different-files re-init gives a fingerprint mismatch and raises `BamlValidationError`;
  - `baml_bridge.shutdown_runtime()` followed by a public call raises `BamlValidationError`.
- **Real panics, in a subprocess** (B3, codex 4). Each case runs `python -c` in a child process. The test requires exit code 0 and a printed `BamlValidationError` line, so an abnormal exit fails the test:
  - a broken `.baml` injected via `_read_baml_files` gives init `BamlPanic`, and both public entrypoints raise `BamlValidationError`;
  - a call after `shutdown_runtime()` gives an invocation `BamlPanic`, which maps to `BamlValidationError`;
  - `KeyboardInterrupt` raised from a patched bridge callable propagates unmapped.
- **Tripwires:**
  - `not issubclass(baml_bridge.errors.BamlPanic, Exception)`;
  - no `\bspawn\b` in any packaged `.baml`;
  - importing `baml_modular`, `discovery`, `evidence_audit` or `injection` in a fresh subprocess leaves `baml_bridge` out of `sys.modules`;
  - no `{{` or `{%` remains in `_read_baml_files()` output.

Other test changes:
- `tests/test_phase_loop_baml_dependency.py`:
  - pin assertions become `"baml-bridge==0.20.1"` and `"protobuf>=6.31.1,<8"`;
  - `test_baml_py_imports_after_install` is renamed `test_baml_bridge_loads_after_install`. It is **not** marked `dotfiles_integration`, so it runs on every pytest lane. It checks the version equality and does a real init plus parse (release-notes (f));
  - `phase_loop_bridge.baml` is added to the packaged list.
- `tests/test_phase_loop_baml_modular.py`: the pyo3-panic fake test is **replaced** by the subprocess real-panic tests (disclosed).
- Prompt-text tests, expected to change under D1 and re-baselined only in the refresh commit:
  - `test_phase_loop_baml_modular.py`
  - `test_phase_loop_baml_schema_export.py`
  - `test_phase_loop_schema_flow.py`
  - `test_phase_loop_closeout_owned_dirty_fallback.py`
  - `tests/data/launchspec_golden/launchspec_golden.json`, read by `test_launchspec_golden.py` and `test_executor_exited_without_closeout_785.py`
- Unchanged, and any red is a finding:
  - `test_phase_loop_baml_{end_to_end,injection,runner_closeout,schema_export,schema_source}.py`
  - `test_phase_loop_skill_baml_closeout.py`
  - `test_phase_loop_terminal_summary_mirrors_baml_closeout.py`
  - `test_phase_loop_{adoption_bundle,closeout_hardening,dotfiles_schemas,dotfiles_sources,evidence_audit_tier3,evidence_audit,plan_manifest,protocol_contract,runtime_projection,discovery,v22_e2e,v22_principles}.py`
  - `test_phase_loop_baml_prompt_taxonomy.py`, which uses synthetic strings for our own pre-render syntax
  - `test_gate_a_wheel_isolation.py`
- **Coverage rule** (codex 5), replacing "identical node list":
  - diff `pytest --collect-only -q` between main and the branch;
  - no existing node may disappear unless the PR body lists it as replaced, with the replacing node and a reason;
  - new nodes are allowed and listed;
  - edited assertions in existing tests are listed with their old and new text.

## Prompt-byte refresh (D1) — one separate, reviewed commit

The commit is `test(baml-v1): refresh closeout-prompt goldens (D1, agent-harness#1135)`, and it is the only place prompt goldens move.

1. **Before.** Use the Step 0 `closeout_prompts_v0.json` hashes:
   - empty: `578144449bebcc1ca7e237fe012b09d6b9f9226712d1aef65c5ce6ed030afa15`
   - two-gates-with-sha: `0097cdc81a57d23d964c53b61e2cd7c4b5db65903c467c0be415e740ca6b5b4f`
   - two-gates-no-sha: `288057f433fd2d598f59af9978bf1f97119984badfbad54940b81f0add4277f6`
2. **After.** Compute the v1+D1a hashes on the migrated tree and store them in `tests/data/baml_closeout_prompt_goldens.json`. The spike value for two-gates-with-sha is `b28df4b29c50e471334dbadaa16e082d30d21353e0ff1049f95eaedae1127e33`. It is informative only, and will differ if main moved.
3. **Diff for review.** The PR body carries `diff -u` of the v0 and v1 prompts for two-gates-with-sha. Every hunk must be exactly one of:
   - #4, loop blank lines;
   - #5, the output-format block.

   The D1a tail must show **no** hunk. Any other hunk is a defect, not part of the refresh. The spike diff has exactly these two classes.
4. **Launchspec golden.**
   - Run `PYTHONPATH=src:tests PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1 python -m pytest -q tests/test_launchspec_golden.py`.
   - Then run it again without the variable; it must pass.
   - The golden diff is confined to the two embedded closeout-prompt strings, with `schema_sha256: 77e72437…` unchanged.
5. **Other consumers of the prompt bytes** (checked on main; nothing else pins them):
   - `injection.py`'s marker cut is kept by D1a.
   - `PromptBundle.body_sha256` / `context_sha256` are recorded per launch and checked only within that launch. Old and new events show different hashes for the same phase; that is expected.
   - Skills cite only the file and function name.
   - The tier-3 prompt is unchanged (#3).

## BAML 0.20.1 release notes, checked item by item

Source: https://boundaryml.com/blog/baml-0.20.1 (read 2026-09-28).

- **(a) Collector, FunctionLog, Timing, Usage and LLMCall exports removed, along with the `collectors` argument; replaced by `ai.Journal` / `ai.Agent`.** Not used by v0 (`git grep -i collector` over `baml_modular.py`, `baml_src/` and the BAML tests is empty), and not used by this plan, which calls only `define_function` bridges and `@spec().parse()/.build_request()`. No impact.
- **(b) Bigints serialize as JSON numbers; `baml.json.json` gained a `bigint` arm.**
  - We declare no `bigint` and never match on `baml.json.json`, so E0062 cannot fire.
  - Integers crossing the runtime: the three optional closeout pixel fields. Evidence arguments are all `string`, and `EvidenceJudgment` is parsed on the Python class path.
  - Spike, v0 vs v1: `12`, `2^53+1` (exact), `5.0`→5, `5.7`→6, `"42"`→42 and `-1` are equal. `2^70` is register #12.
- **(c) Streaming redesign; `stream_types` removed.** There is no `@stream`, `Fn@stream`, `*_stream` or `stream_types` in our sources, module or tests. v0 used only request build and parse; the plan uses only `@spec`. No impact.
- **(d) Empty or whitespace `BAML_HOME` / `HOME` is treated as unset.**
  - `_filtered_env` is deleted, and `initialize_runtime` takes no env.
  - Spike: init and parse succeed with `HOME` set to `''` or `'   '`, `BAML_HOME` set to `''` or `'  '`, `HOME` unset, and under `env -i`.
  - The discovery and tilde changes affect only the CLI, which we run with explicit paths.
- **(e) "Update toolchain and bridge package together."** Enforced by the `baml-sources` job and verification step 2: the CLI's sha256 against the release file and the recorded literal, then `baml-cli --version` = bridge `get_toolchain_version()` = `0.20.1`.
- **(f) The 0.20.0 fingerprint failure hit "all four Linux Python wheels".** A real init plus parse runs on every CI lane:
  - the pytest matrix: `test_baml_bridge_loads_after_install`;
  - the PR wheel smoke and Gate A: `_gate_a_probe.py`;
  - the release lane: the `publish-pypi.yml` release-wheel smoke.

  The 0.20.0 failure did not reproduce on our host in the in-memory path. The gate exists because the notes report it, and a future canary could regress the same way.
- **Not applicable:** reflection changes (no `reflect`), memory and GC, TypeScript, and `baml agent install` (we ship no BAML agent skill).

## Platforms

- **Verified:** x86_64 glibc (host 3.10 and 3.12, `python:3.10-slim`) and musl (`python:3.10-alpine`, `python:3.12-alpine`).
- **Not load-tested:** aarch64 (`manylinux_2_24` needs glibc ≥ 2.24), macOS and Windows.
- **Pre-merge step.** Run verification step 3 once on GitHub-hosted `ubuntu-24.04-arm`, `macos-14`, `macos-13` and `windows-latest`, using a throwaway `workflow_dispatch` on a scratch branch that is not merged. Record the results in the PR. If a platform cannot be run, the CHANGELOG lists it as unverified.

## Documentation impact
- `CHANGELOG.md` — `[Unreleased]` — add "BAML v1 0.20.1 (agent-harness#1135)", covering:
  - `baml-py` replaced by `baml-bridge==0.20.1`;
  - `protobuf>=6.31.1,<8`, which breaks environments pinned to `protobuf<6`;
  - v1 source syntax;
  - the public API is unchanged;
  - **the closeout prompt text changed (D1)**, with loop layout and output-format block listed and the schema-description block kept (D1a);
  - the evidence request is unchanged;
  - the fixed backslash crash (#10);
  - the pixel `null` divergence (#12);
  - the process-global v1 runtime owned by this package, with the `atexit` and `os._exit(1)` hooks (#15);
  - about 0.7 s first-call cost;
  - `baml` / `baml-cli` console scripts no longer installed (#18);
  - platform coverage;
  - rollback.
- `docs/reviews/2026-09-01-codebase-review.md` — no edit (historical). C-8 is now covered by the D3 dual-form regex, the Step 0 schema-dump equality test and the CI fmt round-trip; the CHANGELOG says so in those terms.
- `protocol.md` (both copies) — none (see the frozen-surface section).
- Skills (`skills_bundle/*/SKILL.md`, `phase-loop-skills/**`) — none. They cite `EmitPhaseCloseout` / `emit_phase_closeout.baml` by name and field set, both unchanged.
- READMEs and `docs/TEAM-ONBOARDING.md` — none; they contain no BAML references.

## Release and agy-requalification consequences
- **This PR.** It changes `phase_loop_runtime/**/*.py`, so since agent-harness#1032 it runs only `--route-core`. No requalification is needed here.
- **The next release cut.** It must requalify both agy images, because `baml_modular.py` is in the full `source_sha256` pin set (`plans/evidence/agy-1.2.*-linux-x64-qualification.json`).
  - Recipe: `qualify_gemini_heartbeat.py` (completion, cancel, owner-loss) → `--validate` → regenerate the record → `verify_qualified_agy_image.py --source-only`.
  - Budget for observer repair (the agent-harness#1067 lesson).
  - Record the `baml-bridge` and `protobuf` versions in the release notes, because `source_sha256` covers `.py` files only (B-Q6).
- **Pre-merge check (B-Q6).** Run the qualification recipe's cancel and owner-loss ops once on this branch. That shows the in-process native runtime and its hooks do not disturb cancellation.

## Dependencies & order
1. **Step 0 baselines**, committed first, captured on main with baml-py.
2. Pin, protobuf bound and lock.
3. `.baml` migration, `baml fmt` and the bridge file, together with the `_class_fields` dual form, so schema export never breaks between steps.
4. `baml_modular.py` (ownership contract, bridges, D1/D1a) plus the probe and workflow edits.
5. New tests, then the **separate** prompt-byte refresh commit.
6. CHANGELOG.

Scope: 3 source files, 9 `.baml` files (8 syntax changes plus 1 new logic file), 3 CI sites (`_gate_a_probe.py`, `publish-pypi.yml`, `test.yml`), 1 new test file, the Step 0 data and the goldens. This is at the edge of the bounded-plan threshold. The commits are split so each piece can be reviewed apart.

## Verification
Run from `phase-loop-runtime/` in fresh venvs built from this tree, on py3.10 **and** py3.12. Nothing is stubbed.

```bash
# 1. CI-equivalent install; v0 gone; bridge, toolchain and protobuf versions as pinned.
python -m pip install "./[visual]" pytest
python -c "import importlib.util as u, importlib.metadata as md, baml_bridge as b, google.protobuf as pb; assert u.find_spec('baml_py') is None; assert md.version('baml-bridge')==b.get_toolchain_version()=='0.20.1'; assert 6<=int(pb.__version__.split('.')[0])<8"

# 2. Pinned, sha-verified CLI; fmt round-trip on RAW sources; check on pre-rendered sources.
gh release download baml-language-0.20.1 -R BoundaryML/baml -p 'baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz*' -D /tmp/bamlcli
(cd /tmp/bamlcli && sha256sum -c baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz.sha256 \
  && echo "6067729f14483eca4ab61bfcd3c1921818e9ecc66da035bc64fbbfeb850e2795  baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz" | sha256sum -c - \
  && tar -xzf baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz)
export PATH=/tmp/bamlcli/bin:$PATH
test "$(baml-cli --version 2>/dev/null)" = "baml-cli 0.20.1"
(cd src/phase_loop_runtime && baml-cli --agent-skill-check off fmt baml_src/*.baml) && git diff --exit-code -- src/phase_loop_runtime/baml_src
python -c "from phase_loop_runtime import baml_modular as m; import pathlib; d=pathlib.Path('/tmp/bamlchk/baml_src'); d.mkdir(parents=True, exist_ok=True); [ (d/n).write_text(t) for n,t in m._read_baml_files().items() ]"
printf '[package]\nname = "bamlchk"\n' > /tmp/bamlchk/baml.toml
baml-cli --agent-skill-check off check --project /tmp/bamlchk   # "Finished checked 9 file(s)"

# 3. Real-runtime parity and contracts (the new test file, plus the Step 0 goldens).
python -m pytest -q tests/test_phase_loop_baml_v1_runtime.py tests/test_phase_loop_baml_dependency.py

# 4. Affected suites, plus the coverage-rule diff.
python -m pytest -q tests/test_phase_loop_baml_*.py tests/test_phase_loop_skill_baml_closeout.py tests/test_phase_loop_terminal_summary_mirrors_baml_closeout.py \
  tests/test_phase_loop_adoption_bundle.py tests/test_phase_loop_closeout_hardening.py tests/test_phase_loop_dotfiles_schemas.py tests/test_phase_loop_dotfiles_sources.py \
  tests/test_phase_loop_evidence_audit.py tests/test_phase_loop_evidence_audit_tier3.py tests/test_phase_loop_plan_manifest.py tests/test_phase_loop_protocol_contract.py \
  tests/test_phase_loop_runtime_projection.py tests/test_phase_loop_discovery.py tests/test_phase_loop_v22_e2e.py tests/test_phase_loop_v22_principles.py \
  tests/test_phase_loop_schema_flow.py tests/test_phase_loop_closeout_owned_dirty_fallback.py tests/test_launchspec_golden.py tests/test_executor_exited_without_closeout_785.py \
  tests/test_gate_a_wheel_isolation.py
python -m pytest --collect-only -q > /tmp/nodes.branch   # compare with the same on main; apply the coverage rule

# 5. Wheel: 9 .baml files shipped; clean-venv probe.
python -m build --wheel && unzip -l dist/*.whl | grep -c 'baml_src/.*\.baml$'   # 9
bash scripts/gate_a_cleanroom.sh

# 6. musl, no network after install: py3.10 and py3.12.
for img in python:3.10-alpine python:3.12-alpine; do
  vol="bamlv1-$(echo "$img" | tr ':.' '--')"
  docker run --rm -v "$vol:/venv" -v "$PWD/dist:/d:ro" "$img" sh -c 'python -m venv /venv/v && /venv/v/bin/pip install -q /d/*.whl pytest'
  docker run --rm --network none -v "$vol:/venv" -v "$PWD:/w:ro" -w /w "$img" \
    /venv/v/bin/python -m pytest -q -p no:cacheprovider tests/test_phase_loop_baml_v1_runtime.py tests/test_phase_loop_baml_dependency.py
  docker volume rm "$vol"
done
```

## Acceptance criteria
- [ ] Step 0 baselines are committed first, captured on main with baml-py 0.222.0, with provenance recorded.
- [ ] `pip install ./phase-loop-runtime` on py3.10 and py3.12 installs `baml-bridge==0.20.1` and a protobuf in `[6.31.1, 8)`, and no `baml-py`. Verification step 1 exits 0.
- [ ] `tests/test_phase_loop_baml_v1_runtime.py` passes on py3.10 and py3.12. This covers the parse corpus (identical except the disclosed entry), full evidence-request equality, payload handling, closeout refreshed goldens plus D1a, schema dump equality, ownership (concurrency, repeat, foreign, different-files, shutdown), subprocess real-panic cases with exit 0, and tripwires.
- [ ] The CI job `baml-sources` (sha-verified CLI 0.20.1, fmt round-trip zero diff, `check` of 9 files) and the bridge load test (pytest lanes, wheel smoke / Gate A probe, publish-pypi smoke) are green and blocking.
- [ ] The prompt-byte refresh is its own commit. The PR body carries the v0→v1 diff with every hunk attributed to #4 or #5, the launchspec golden diff confined to the closeout-prompt strings with `schema_sha256: 77e72437…` unchanged, and the coverage-rule node diff with every replacement disclosed.

## Execution Policy
- execute: effort=high, reason=replaces the runtime under the closeout parser; process-global ownership, real-panic containment and a reviewed prompt change are subtle.
